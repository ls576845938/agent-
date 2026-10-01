"""Production-only composition for the BTC Demo execution seam.

The object in this module is deliberately a composition boundary rather than a
second execution engine.  It consumes explicit runtime/broker/ledger facts,
builds the existing T2/T3/T4 records, and hands an immutable T5 bundle back to
the existing OMS facade.  It never owns a client and never grants execution
permission; the dispatcher remains the only I/O authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Sequence

from quant_crypto.application.hosted_protection_facts import (
    normalize_hosted_protection_facts,
)
from quant_crypto.application.runtime_risk_guardian import (
    classify_order_risk,
    GuardianConfig,
    GuardianObservation,
    RuntimeRiskGuardian,
)
from quant_crypto.oms.shared_platform_v3 import (
    OMSOrderSubmissionBundle,
    OMSProofIdentity,
    SharedPlatformV3OMS,
    order_intent_execution_digest,
)
from quant_crypto.portfolio.decision import (
    BTCPortfolioDecision,
    RiskReductionPlan,
    build_btc_portfolio_decision,
)
from quant_crypto.risk import (
    ActionRiskEffect,
    RiskAssessment,
    RiskConstitution,
    assess_btc_risk,
)
from quant_crypto.trading_contracts import (
    OrderIntent,
    Signal,
    SignalDirection,
    TargetPosition,
)
from quant_shared.runtime.permissions import RuntimeAction


BTC_DEMO_INSTRUMENT_ID = "BTC-USDT-SWAP"
_PROFILE_LEVERAGE = {"baseline_1x": Decimal("1"), "stress_3x": Decimal("3")}
_HEX40 = set("0123456789abcdef")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if math.isfinite(candidate) else None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        candidate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return candidate if candidate.is_finite() else None


def _parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    return None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def expected_isolated_leverage(profile: str) -> Decimal:
    """Return the exact leverage selected by the Demo risk profile."""

    normalized = str(profile or "").strip().lower()
    try:
        return _PROFILE_LEVERAGE[normalized]
    except KeyError as exc:
        raise ValueError("demo_risk_profile_unknown") from exc


def validate_isolated_leverage(
    rows: Sequence[Mapping[str, Any]] | Any,
    expected: Decimal | str | int | float,
) -> tuple[str, ...]:
    """Validate the two-sided isolated leverage projection exactly once.

    The runtime's REST normalizer uses ``position_side``/``margin_mode`` /
    ``leverage``.  The raw aliases are accepted only for composition tests and
    never change the required two-row, long+short identity.
    """

    expected_decimal = _decimal(expected)
    if expected_decimal is None or expected_decimal <= 0:
        return ("leverage_expected_invalid",)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ("leverage_evidence_invalid",)
    normalized = [row for row in rows if isinstance(row, Mapping)]
    blockers: list[str] = []
    if len(normalized) != 2:
        blockers.append("leverage_sides_missing_or_duplicate")
    sides: set[str] = set()
    for row in normalized:
        side = str(row.get("position_side") or row.get("posSide") or row.get("side") or "").strip().lower()
        margin = str(row.get("margin_mode") or row.get("mgnMode") or row.get("tdMode") or "").strip().lower()
        observed = _decimal(row.get("leverage") if "leverage" in row else row.get("lever"))
        if side not in {"long", "short"}:
            blockers.append("leverage_side_invalid")
        else:
            sides.add(side)
        if margin != "isolated":
            blockers.append("leverage_margin_mode_mismatch")
        if observed is None or observed != expected_decimal:
            blockers.append("leverage_mismatch")
        instrument = row.get("instrument_id") or row.get("instId")
        if instrument is not None and str(instrument) != BTC_DEMO_INSTRUMENT_ID:
            blockers.append("leverage_instrument_mismatch")
    if sides != {"long", "short"}:
        blockers.append("leverage_sides_missing_or_duplicate")
    return tuple(sorted(set(blockers)))


def leverage_blocker_code(expected: Decimal | str | int | float, *, prefix: str = "okx_demo_paper") -> str:
    resolved = _decimal(expected)
    if resolved is None:
        return f"{prefix}_leverage_evidence_invalid"
    label = format(resolved, "f").rstrip("0").rstrip(".")
    return f"{prefix}_exact_isolated_{label}x_leverage_required"


def _extract_price(snapshot: Mapping[str, Any], *names: str) -> float | None:
    ticker = _mapping(snapshot.get("ticker"))
    mark = _mapping(snapshot.get("mark"))
    index = _mapping(snapshot.get("index"))
    instrument = _mapping(snapshot.get("instrument"))
    # The production snapshot deliberately keeps broker prices in separate
    # ``mark``/``index`` blocks.  Do not infer either value from account or
    # balance facts; a missing authoritative price must remain blocked.
    for source in (snapshot, ticker, mark, index, instrument):
        for name in names:
            candidate = _number(source.get(name))
            if candidate is not None and candidate > 0:
                return candidate
    return None


def _extract_equity(snapshot: Mapping[str, Any], ledger: Mapping[str, Any]) -> float | None:
    account = _mapping(snapshot.get("account"))
    balance = _mapping(snapshot.get("balance"))
    for source in (account, balance, snapshot, ledger):
        for name in ("equity", "equity_usdt", "account_equity", "totalEq", "cash", "balance"):
            candidate = _number(source.get(name))
            if candidate is not None and candidate > 0:
                return candidate
    return None


def contract_notional_usdt(
    contracts: Decimal | str | int | float,
    price: Decimal | str | int | float,
    contract_value_btc: Decimal | str | int | float,
) -> Decimal:
    """Convert OKX contract quantity into an auditable USDT notional."""

    quantity = _decimal(contracts)
    observed_price = _decimal(price)
    contract_value = _decimal(contract_value_btc)
    if (
        quantity is None
        or observed_price is None
        or contract_value is None
        or quantity < 0
        or observed_price <= 0
        or contract_value <= 0
    ):
        raise ValueError("contract_notional_facts_invalid")
    return quantity * observed_price * contract_value


def _contract_value_btc(
    exchange_snapshot: Mapping[str, Any],
    venue_facts: Mapping[str, Any] | None = None,
) -> Decimal:
    instrument = _mapping(exchange_snapshot.get("instrument"))
    venue = venue_facts or {}
    value = _decimal(
        instrument.get("contract_value_btc")
        or instrument.get("ctVal")
        or venue.get("contract_value_btc")
        or venue.get("ctVal")
    )
    if value is None or value <= 0:
        raise ValueError("contract_value_btc_missing")
    return value


def _observed_pnl_value(row: Mapping[str, Any], *names: str) -> float | None:
    observed = row.get("pnl_observed")
    if observed is False:
        return None
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            value = _number(row.get(name))
            if value is not None:
                return value
    return None


def _authoritative_pnl_facts(
    exchange_snapshot: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, float]:
    """Derive PnL/funding only from explicitly observed authoritative facts."""

    fills = _rows(exchange_snapshot.get("fills"))
    positions = _position_rows(exchange_snapshot)
    # A reconciliation match or a legacy ``pnl_consistent`` bit is not PnL
    # provenance.  Only observed fill/position/balance facts may establish the
    # values consumed by T2.  This keeps the production raw ledger shape
    # fail-closed when its optional summary fields are absent.
    realized = None
    if fills and all(row.get("pnl_observed") is True for row in fills):
        values = [_observed_pnl_value(row, "pnl", "realized_pnl") for row in fills]
        if all(value is not None for value in values):
            realized = float(sum(value for value in values if value is not None))
    if realized is None and positions and all(row.get("realized_pnl_observed") is True for row in positions):
        values = [_observed_pnl_value(row, "realized_pnl", "pnl") for row in positions]
        if all(value is not None for value in values):
            realized = float(sum(value for value in values if value is not None))

    unrealized = None
    if positions and all(row.get("unrealized_pnl_observed") is True for row in positions):
        values = [_observed_pnl_value(row, "unrealized_pnl", "pnl") for row in positions]
        if all(value is not None for value in values):
            unrealized = float(sum(value for value in values if value is not None))
    if unrealized is None:
        balance = _mapping(exchange_snapshot.get("balance"))
        if balance.get("unrealized_pnl_observed") is True:
            unrealized = _observed_pnl_value(balance, "unrealized_pnl_usdt", "unrealized_pnl")

    funding_error = ""
    try:
        funding = _funding_cashflow_from_snapshot(exchange_snapshot, ledger)
    except ValueError as exc:
        funding = None
        funding_error = str(exc)

    missing = [
        name
        for name, value in (
            ("realized_pnl", realized),
            ("unrealized_pnl", unrealized),
            ("funding_cashflow", funding),
        )
        if value is None
    ]
    if missing:
        if funding_error:
            missing.append("funding_cashflow[" + funding_error + "]")
        raise ValueError("authoritative_pnl_facts_missing:" + ",".join(missing))
    return {
        "realized_pnl": float(realized),
        "unrealized_pnl": float(unrealized),
        "funding_cashflow": float(funding),
    }


def _funding_cashflow_from_snapshot(
    exchange_snapshot: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> float:
    """Read funding only from a complete, count-bound bills snapshot.

    ``_commit_ledger_reconciliation`` publishes ``funding_bill_count`` and a
    signed ``funding_cashflow`` alongside the same exchange snapshot.  An
    empty list therefore means zero only when the caller supplies that full
    list and the durable count agrees; a missing list/count is unknown.
    """

    raw_bills = exchange_snapshot.get("bills")
    if not isinstance(raw_bills, Sequence) or isinstance(raw_bills, (str, bytes)):
        raise ValueError("authoritative_funding_snapshot_missing")
    bills = [row for row in raw_bills if isinstance(row, Mapping)]
    if len(bills) != len(raw_bills):
        raise ValueError("authoritative_funding_snapshot_invalid")
    count = ledger.get("funding_bill_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("authoritative_funding_bill_count_missing")
    funding_rows = [
        row
        for row in bills
        if str(row.get("type") or "") == "8"
        or str(row.get("sub_type") or "") == "173"
    ]
    if count != len(funding_rows):
        raise ValueError("authoritative_funding_bill_count_mismatch")
    observed_total = Decimal("0")
    for row in funding_rows:
        if row.get("balance_change_observed") is not True:
            raise ValueError("authoritative_funding_cashflow_unknown")
        value = _decimal(row.get("balance_change"))
        if value is None:
            raise ValueError("authoritative_funding_cashflow_unknown")
        observed_total += value
    ledger_value = _decimal(ledger.get("funding_cashflow"))
    if ledger_value is None or ledger_value != observed_total:
        raise ValueError("authoritative_funding_cashflow_mismatch")
    if ledger.get("funding_cashflow_reconciled") is not True:
        raise ValueError("authoritative_funding_cashflow_not_reconciled")
    return float(observed_total)


def _strict_rows(value: Any) -> tuple[list[Mapping[str, Any]], bool]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return [], False
    rows = [row for row in value if isinstance(row, Mapping)]
    return rows, len(rows) == len(value)


def _count_matches(ledger: Mapping[str, Any], key: str, rows: Sequence[Any]) -> bool:
    value = ledger.get(key)
    return isinstance(value, int) and not isinstance(value, bool) and value == len(rows)


def canonical_ledger_snapshot_facts(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact facts used by the runtime ledger UOW hash.

    This intentionally mirrors ``OkxDemoPaperRuntimeController``: only the
    seven canonical containers are included and funding bills are restricted
    to OKX funding types 8/173.  The runtime filters malformed rows before
    hashing; the evidence projection performs separate strict shape/count
    checks so filtering cannot silently grant authority.
    """

    def rows(name: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in snapshot.get(name, [])
            if isinstance(row, Mapping)
        ]

    bills = [
        dict(row)
        for row in snapshot.get("bills", [])
        if isinstance(row, Mapping)
        and (
            str(row.get("type") or "") == "8"
            or str(row.get("sub_type") or "") == "173"
        )
    ]
    return {
        "orders": rows("orders"),
        "pending_orders": rows("pending_orders"),
        "pending_algo_orders": rows("pending_algo_orders"),
        "fills": rows("fills"),
        "positions": rows("positions"),
        "balance": dict(_mapping(snapshot.get("balance"))),
        "funding_bills": bills,
    }


def canonical_ledger_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
    """Hash canonical ledger facts with the runtime's exact JSON bytes."""

    return hashlib.sha256(
        json.dumps(
            canonical_ledger_snapshot_facts(snapshot),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _project_reconciliation_evidence(
    exchange_snapshot: Mapping[str, Any],
    ledger: Mapping[str, Any],
    *,
    opening_protection: Mapping[str, Any] | None = None,
    expected_parent_client_order_id: str = "",
    opening: bool = False,
) -> dict[str, Any]:
    """Project raw runtime reconciliation into explicit T4 evidence.

    The durable ledger intentionally does not manufacture six summary boolean
    fields.  This adapter derives each one from the same current exchange
    snapshot, durable counts and observed provenance, preserving ``unknown``
    when a container or identity is absent.
    """

    blockers: list[str] = []
    snapshot_match = ledger.get("current_state_exchange_snapshot_match") is True
    snapshot_hash = ""
    snapshot_hash_match = False
    stored_snapshot_hash = ledger.get("exchange_snapshot_sha256")
    try:
        snapshot_hash = canonical_ledger_snapshot_sha256(exchange_snapshot)
    except (TypeError, ValueError, OverflowError):
        blockers.append("reconciliation_snapshot_hash_invalid")
    if stored_snapshot_hash in (None, ""):
        blockers.append("reconciliation_snapshot_hash_missing")
    elif not isinstance(stored_snapshot_hash, str) or len(stored_snapshot_hash) != 64 or any(
        char not in "0123456789abcdef" for char in stored_snapshot_hash
    ):
        blockers.append("reconciliation_snapshot_hash_invalid")
    elif snapshot_hash and stored_snapshot_hash != snapshot_hash:
        blockers.append("reconciliation_snapshot_hash_mismatch")
    else:
        snapshot_hash_match = bool(snapshot_hash)
    if not snapshot_match:
        blockers.append("reconciliation_snapshot_mismatch")

    positions, positions_shape = _strict_rows(exchange_snapshot.get("positions"))
    pending_orders, pending_shape = _strict_rows(exchange_snapshot.get("pending_orders"))
    pending_algos, algo_shape = _strict_rows(exchange_snapshot.get("pending_algo_orders"))
    orders, orders_shape = _strict_rows(exchange_snapshot.get("orders"))
    fills, fills_shape = _strict_rows(exchange_snapshot.get("fills"))
    bills, bills_shape = _strict_rows(exchange_snapshot.get("bills"))
    balance = exchange_snapshot.get("balance")
    balance_shape = isinstance(balance, Mapping) and bool(balance)
    if not positions_shape:
        blockers.append("positions_container_unknown")
    if not pending_shape:
        blockers.append("open_orders_container_unknown")
    if not algo_shape:
        blockers.append("protection_container_unknown")
    if not orders_shape:
        blockers.append("orders_container_unknown")
    if not fills_shape:
        blockers.append("fills_container_unknown")
    if not bills_shape:
        blockers.append("funding_bills_container_unknown")
    if not balance_shape:
        blockers.append("cash_container_unknown")

    position_identity = True
    for row in positions:
        instrument = str(row.get("instrument_id") or "").strip()
        side = str(row.get("position_side") or "").strip().lower()
        quantity = _decimal(row.get("contracts") or row.get("pos"))
        if instrument != BTC_DEMO_INSTRUMENT_ID or side not in {"long", "short"} or quantity is None or quantity < 0:
            position_identity = False
            break
    pending_identity = True
    for row in pending_orders:
        if not str(row.get("order_id") or row.get("client_order_id") or "").strip():
            pending_identity = False
            break
    orders_count_match = _count_matches(ledger, "order_count", orders)
    fills_count_match = _count_matches(ledger, "fill_count", fills)
    positions_count_match = _count_matches(ledger, "position_count", positions)
    pending_count_match = _count_matches(ledger, "pending_order_count", pending_orders)
    pending_algo_count_match = _count_matches(ledger, "pending_algo_order_count", pending_algos)
    funding_count_match = _count_matches(
        ledger,
        "funding_bill_count",
        [row for row in bills if str(row.get("type") or "") == "8" or str(row.get("sub_type") or "") == "173"],
    )
    for name, matched in (
        ("order", orders_count_match),
        ("fill", fills_count_match),
        ("position", positions_count_match),
        ("pending_order", pending_count_match),
        ("pending_algo_order", pending_algo_count_match),
        ("funding_bill", funding_count_match),
    ):
        if not matched:
            blockers.append(f"reconciliation_{name}_count_mismatch")
    positions_consistent = snapshot_match and snapshot_hash_match and positions_shape and position_identity and positions_count_match
    cash_consistent = snapshot_match and snapshot_hash_match and balance_shape and _number(balance.get("equity_usdt")) is not None and _number(balance.get("equity_usdt")) > 0
    open_orders_consistent = snapshot_match and snapshot_hash_match and pending_shape and pending_identity and pending_count_match

    try:
        contract_value = _contract_value_btc(exchange_snapshot)
        mark_price = _extract_price(exchange_snapshot, "mark_price", "markPx", "last", "last_price")
        exposure_consistent = positions_consistent and mark_price is not None and all(
            _decimal(row.get("contracts") or row.get("pos")) is not None for row in positions
        )
        if exposure_consistent:
            # Force the exact units through the shared conversion helper so the
            # projection cannot silently compare contracts with USDT.
            for row in positions:
                contract_notional_usdt(
                    _decimal(row.get("contracts") or row.get("pos")) or Decimal("0"),
                    mark_price or 0,
                    contract_value,
                )
    except ValueError:
        contract_value = None
        mark_price = None
        exposure_consistent = False
    if not exposure_consistent:
        blockers.append("exposure_consistency_unknown")

    try:
        pnl = _authoritative_pnl_facts(exchange_snapshot, ledger)
        pnl["daily"] = (
            pnl["realized_pnl"]
            + pnl["unrealized_pnl"]
            + pnl["funding_cashflow"]
        )
        pnl_consistent = snapshot_hash_match and fills_count_match
        if not pnl_consistent:
            blockers.append("reconciliation_pnl_source_unbound")
    except ValueError as exc:
        pnl = None
        pnl_consistent = False
        blockers.append(str(exc))

    protection_consistent = False
    protection_facts: dict[str, Any] = {
        "present": False,
        "required_for_action": bool(opening),
        "consistent": False,
        "source": "authoritative_reconciliation",
    }
    if opening_protection is not None:
        payload = _mapping(opening_protection.get("exchange_payload"))
        parent = str(opening_protection.get("parent_client_order_id") or "")
        quantity = _decimal(opening_protection.get("quantity"))
        protection_consistent = bool(
            opening
            and snapshot_hash_match
            and opening_protection.get("present") is True
            and payload
            and parent
            and parent == str(expected_parent_client_order_id)
            and quantity is not None
            and quantity > 0
            and str(opening_protection.get("order_type") or "").lower() == "oco"
        )
        protection_facts = dict(opening_protection)
        protection_facts["consistent"] = protection_consistent
        protection_facts["source"] = "t2_attached_protection_projection"
    elif pending_algos:
        protection_consistent = snapshot_match and snapshot_hash_match and algo_shape and pending_algo_count_match
        for row in pending_algos:
            instrument = str(row.get("instrument_id") or "").strip()
            side = str(row.get("position_side") or "").strip().lower()
            state = str(row.get("state") or "").strip().lower()
            size = _decimal(row.get("size") or row.get("contracts") or row.get("sz"))
            order_type = str(row.get("order_type") or row.get("ordType") or "").strip().lower()
            if (
                instrument != BTC_DEMO_INSTRUMENT_ID
                or side not in {"long", "short"}
                or state not in {"live", "effective"}
                or size is None
                or size <= 0
                or order_type not in {"oco", "conditional_oco"}
                or not str(row.get("algo_id") or row.get("algo_client_order_id") or "").strip()
            ):
                protection_consistent = False
                break
        protection_facts = {
            "present": True,
            "required_for_action": True,
            "consistent": protection_consistent,
            "source": "authoritative_reconciliation_pending_algo",
            "items": pending_algos,
        }
    elif not opening and algo_shape:
        # A risk-reduction action may safely flatten without an attached OCO;
        # this is an explicit, current ``no protection required`` fact, not a
        # non-None empty list pretending to be protection.
        protection_consistent = snapshot_match and snapshot_hash_match and pending_algo_count_match
        protection_facts = {
            "present": False,
            "required_for_action": False,
            "consistent": protection_consistent,
            "source": "authoritative_reconciliation_no_protection_required",
            "items": [],
        }
    if not protection_consistent:
        blockers.append("protection_consistency_unknown")

    evidence = {
        "source": "btc_demo_commit_ledger_reconciliation_v1",
        "snapshot_match": snapshot_match,
        "snapshot_hash": snapshot_hash,
        "snapshot_hash_match": snapshot_hash_match,
        "counts": {
            "orders": len(orders),
            "fills": len(fills),
            "positions": len(positions),
            "pending_orders": len(pending_orders),
            "pending_algo_orders": len(pending_algos),
            "funding_bills": len([row for row in bills if str(row.get("type") or "") == "8" or str(row.get("sub_type") or "") == "173"]),
        },
        "positions_consistent": positions_consistent,
        "cash_consistent": cash_consistent,
        "pnl_consistent": pnl_consistent,
        "exposure_consistent": exposure_consistent,
        "open_orders_consistent": open_orders_consistent,
        "protection_consistent": protection_consistent,
        "contract_value_btc": format(contract_value, "f") if contract_value is not None else "",
        "mark_price": str(mark_price or ""),
        "pnl": pnl or {},
        "protection": protection_facts,
        "blockers": sorted(set(blockers)),
    }
    projected_ledger = dict(ledger)
    projected_ledger.update({
        key: evidence[key]
        for key in (
            "positions_consistent",
            "cash_consistent",
            "pnl_consistent",
            "exposure_consistent",
            "open_orders_consistent",
            "protection_consistent",
        )
    })
    projected_ledger["reconciliation_evidence"] = evidence
    return {
        "ledger": projected_ledger,
        "evidence": evidence,
        "blockers": evidence["blockers"],
        "protection_facts": protection_facts,
    }


def _cost_inputs_from_bps(
    cost_facts: Mapping[str, Any],
    *,
    actual_notional: Decimal,
    observed_funding_cashflow: Decimal,
) -> dict[str, Any]:
    """Convert the existing risk bps model into explicit T2 cost amounts."""

    if cost_facts.get("cost_model_complete") is not True:
        raise ValueError("cost_model_incomplete")
    bps_values: dict[str, Decimal] = {}
    for key in ("fee_bps", "funding_bps", "slippage_budget_bps", "impact_bps"):
        value = _decimal(cost_facts.get(key))
        if value is None or value < 0:
            raise ValueError(f"cost_{key}_missing_or_invalid")
        bps_values[key] = value
    scale = Decimal("10000")
    result = dict(cost_facts)
    result.update({
        "fees": format(actual_notional * bps_values["fee_bps"] / scale, "f"),
        "slippage": format(actual_notional * bps_values["slippage_budget_bps"] / scale, "f"),
        "impact": format(actual_notional * bps_values["impact_bps"] / scale, "f"),
        "prospective_funding_budget_usdt": format(actual_notional * bps_values["funding_bps"] / scale, "f"),
        "funding_cashflow_observed": format(observed_funding_cashflow, "f"),
        "funding_budget_source": "prospective_bps_separate_from_observed_cashflow",
        "cost_inputs_source": "order_plan_risk_bps_x_contract_notional",
    })
    return result


def _reduction_cost_inputs(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Describe reduction-only cost treatment without opening-path defaults.

    A protective reduction cannot increase exposure and the native ledger may
    not publish a prospective fee/slippage/impact budget.  Observed values are
    consumed when present; otherwise the T2 risk call receives an explicit
    zero *new-risk budget* with provenance, never an opening cost estimate.
    """

    observed = {
        key: _number(ledger.get(key))
        for key in ("fees", "slippage", "impact")
    }
    if all(value is not None for value in observed.values()):
        return {
            **observed,
            "source": "observed_ledger_reduction_costs",
        }
    return {
        "fees": 0.0,
        "slippage": 0.0,
        "impact": 0.0,
        "source": "risk_reduction_no_new_cost_budget",
    }


def _read_target_generation_allowed(target: TargetPosition) -> bool | None:
    metadata = target.metadata if isinstance(target.metadata, Mapping) else {}
    value = metadata.get("order_generation_allowed")
    return value if type(value) is bool else None


def _adapt_protection_for_t2(
    payload: Mapping[str, Any],
    *,
    position_side: str,
    quantity: float,
    contract_value_btc: Decimal,
) -> dict[str, Any]:
    """Translate the exchange OCO shape into T2's explicit protection shape."""

    # T2 needs the adverse-price stop for both directions.  A short OCO still
    # closes on BUY, but its stop-loss trigger is the price above entry; the
    # take-profit trigger below entry is never a protection substitute.
    trigger = _decimal(payload.get("slTriggerPx"))
    if trigger is None or trigger <= 0:
        raise ValueError("attached_protection_trigger_missing")
    return {
        "present": True,
        "quantity": quantity,
        "trigger_price": float(trigger * contract_value_btc),
        "side": "sell" if position_side == "long" else "buy",
        "parent_client_order_id": str(payload.get("attachAlgoClOrdId") or "").removesuffix("A"),
        "position_side": position_side,
        "order_type": "oco",
        "exchange_payload": dict(payload),
    }


def _position_rows(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = snapshot.get("positions")
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else []


def _position_contracts(snapshot: Mapping[str, Any], position_side: str) -> float:
    total = 0.0
    for row in _position_rows(snapshot):
        side = str(row.get("position_side") or row.get("posSide") or "").lower()
        if side and side != position_side:
            continue
        value = _number(row.get("contracts") or row.get("pos"))
        if value is not None:
            total += value
    return total


def _account_identity(snapshot: Mapping[str, Any]) -> str:
    account = _mapping(snapshot.get("account"))
    identity = _mapping(account.get("identity"))
    # Account identity must be stable across balance changes.  Only the
    # already-redacted account-config digest is accepted; mutable balance or
    # permission facts can never become an identity fallback.
    value = str(identity.get("hash") or "").strip().lower()
    return value if len(value) == 64 and all(char in _HEX40 for char in value) else ""


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _fresh_bool(value: Any) -> bool | None:
    if type(value) is bool:
        return value
    return None


@dataclass
class BtcDemoProductionComposition:
    """Backend-owned T2/T3/T4/T5 composition seam.

    ``guardian_supervisor_factory`` is intentionally injected by the backend
    composition root.  A missing factory means the durable latch is unknown,
    which blocks opening but still permits a proven reduction bundle to be
    constructed for the existing dispatcher/recovery path.
    """

    source_head: str
    max_configured_leverage: Decimal = Decimal("1")
    max_abs_position: Decimal = Decimal("0.01")
    max_notional: Decimal = Decimal("10")
    credential_service: str = "quant-system.okx-demo.trade"
    guardian_supervisor_factory: Callable[[], Any] | None = None
    guardian_config: GuardianConfig | Mapping[str, Any] | None = None
    # Omitted preserves the legacy loss==notional policy for existing callers.
    max_loss_usdt: Decimal | None = None

    def __post_init__(self) -> None:
        head = str(self.source_head or "").strip().lower()
        if len(head) != 40 or any(char not in _HEX40 for char in head):
            raise ValueError("composition_source_head_invalid")
        self.source_head = head
        expected = _decimal(self.max_configured_leverage)
        if expected is None or expected <= 0:
            raise ValueError("composition_leverage_invalid")
        self.max_configured_leverage = expected
        if self.max_loss_usdt is not None:
            loss_limit = _decimal(self.max_loss_usdt)
            if loss_limit is None or loss_limit <= 0:
                raise ValueError("composition_loss_limit_invalid")
            self.max_loss_usdt = loss_limit
        self._guardian_supervisor: Any | None = None

    @property
    def loss_limit_usdt(self) -> Decimal:
        return self.max_notional if self.max_loss_usdt is None else self.max_loss_usdt

    def _supervisor(self) -> Any | None:
        if self._guardian_supervisor is None and self.guardian_supervisor_factory is not None:
            self._guardian_supervisor = self.guardian_supervisor_factory()
        return self._guardian_supervisor

    def _guardian_observation(self, *, exchange_snapshot: Mapping[str, Any], private_ws: Mapping[str, Any], ledger: Mapping[str, Any], runtime: Mapping[str, Any], reference_time: datetime, intent: OrderIntent, position_after: float, protection_facts: Any = None, normalized_pending_algos: Sequence[Mapping[str, Any]] | None = None) -> GuardianObservation:
        observed = _parse_utc(exchange_snapshot.get("captured_at_utc") or exchange_snapshot.get("captured_at"))
        heartbeat = _parse_utc(runtime.get("last_heartbeat_utc") or private_ws.get("last_heartbeat_utc") or private_ws.get("heartbeat_at_utc"))
        if observed is None or heartbeat is None:
            raise ValueError("guardian_observation_required")
        session_id = str(runtime.get("run_id") or runtime.get("session_id") or intent.run_id or "").strip()
        key_namespace = str(runtime.get("credential_namespace") or runtime.get("key_namespace") or self.credential_service).strip()
        expected_client_namespace = intent.client_order_id[:13]
        supplied_client_namespace = str(runtime.get("client_order_namespace") or "").strip()
        if supplied_client_namespace and supplied_client_namespace != expected_client_namespace:
            raise ValueError("guardian_client_order_namespace_mismatch")
        client_namespace = expected_client_namespace
        epoch_value = runtime.get("authoritative_liveness_epoch")
        if not session_id or not key_namespace or not client_namespace or type(epoch_value) is not int or epoch_value < 0:
            raise ValueError("guardian_observation_required")
        positions = _position_rows(exchange_snapshot)
        # An explicit empty exchange position list is authoritative flatness,
        # not an unknown position metric.  Preserve that distinction for T4
        # without inventing a non-zero broker position.
        position_facts: object = positions if positions else {
            "total": 0.0,
            "consistent": ledger.get("positions_consistent") is True,
        }
        pending_orders = _rows(exchange_snapshot.get("pending_orders"))
        pending_algos = _rows(
            normalized_pending_algos
            if normalized_pending_algos is not None
            else exchange_snapshot.get("pending_algo_orders")
        )
        open_orders = [*pending_orders, *pending_algos]
        risk_order_count, protective_order_count, order_risk_blockers = classify_order_risk(
            open_orders,
            positions,
        )
        account = _mapping(exchange_snapshot.get("account"))
        balance = _mapping(exchange_snapshot.get("balance"))
        cash_facts = {**account, **balance}
        ledger_status = str(ledger.get("status") or "")
        ws_ok = private_ws.get("connected") is True and private_ws.get("listener_alive") is True
        reconciliation_ok = ledger_status == "reconciled" and ledger.get("current_state_exchange_snapshot_match") is True and ledger.get("funding_cashflow_reconciled") is True
        explicit_fresh = exchange_snapshot.get("fresh")
        if type(explicit_fresh) is not bool:
            # The controller's authoritative exchange snapshot does not add a
            # synthetic ``fresh`` flag.  Derive freshness only from its
            # captured UTC timestamp and the explicit reference time supplied
            # by the caller; missing or malformed timestamps remain blocked.
            explicit_fresh = (
                observed is not None
                and reference_time.tzinfo is not None
                and 0.0 <= (reference_time.astimezone(timezone.utc) - observed).total_seconds() <= 30.0
            )
        equity = _extract_equity(exchange_snapshot, ledger)
        pnl = _authoritative_pnl_facts(exchange_snapshot, ledger)
        pnl["daily"] = (
            pnl["realized_pnl"]
            + pnl["unrealized_pnl"]
            + pnl["funding_cashflow"]
        )
        contract_value = _decimal(
            _mapping(exchange_snapshot.get("instrument")).get("contract_value_btc")
        )
        mark_price = _extract_price(exchange_snapshot, "mark_price", "markPx", "last", "last_price")
        contract_exposure = sum(
            abs(_number(row.get("contracts") or row.get("pos")) or 0.0)
            for row in positions
        )
        exposure_usdt = (
            contract_exposure * float(contract_value) * mark_price
            if contract_value is not None and mark_price is not None
            else None
        )
        return GuardianObservation(
            source_head=self.source_head,
            account_identity=_account_identity(exchange_snapshot),
            account_snapshot_sha256=str(
                ledger.get("exchange_snapshot_sha256") or ""
            ),
            session_id=session_id,
            key_namespace=key_namespace,
            client_order_namespace=client_namespace,
            owner_identity=str(
                runtime.get("guardian_owner_identity")
                or runtime.get("runtime_identity")
                or session_id
            ).strip(),
            epoch=epoch_value,
            observed_at_utc=observed,
            reference_time_utc=reference_time,
            heartbeat_at_utc=heartbeat,
            heartbeat_healthy=ws_ok,
            heartbeat={"connected": private_ws.get("connected"), "listener_alive": private_ws.get("listener_alive")},
            broker_truth=exchange_snapshot,
            broker_truth_fresh=explicit_fresh,
            facts_fresh=explicit_fresh and ws_ok and reconciliation_ok,
            reconciliation={"private_ws": private_ws, "ledger": ledger},
            reconciliation_passed=reconciliation_ok,
            ledger_reconciled=ledger_status == "reconciled",
            snapshot_match=ledger.get("current_state_exchange_snapshot_match") if type(ledger.get("current_state_exchange_snapshot_match")) is bool else None,
            funding_reconciled=ledger.get("funding_cashflow_reconciled") if type(ledger.get("funding_cashflow_reconciled")) is bool else None,
            positions=position_facts,
            cash=cash_facts,
            pnl=pnl,
            exposure={"contracts": contract_exposure, "notional_usdt": exposure_usdt},
            open_orders=open_orders,
            protection_facts=pending_algos if pending_algos else protection_facts,
            account_facts={
                "account": account,
                "balance": balance,
                "account_drawdown": _mapping(
                    ledger.get("account_drawdown_fact")
                ),
            },
            positions_consistent=ledger.get("positions_consistent") if type(ledger.get("positions_consistent")) is bool else None,
            cash_consistent=ledger.get("cash_consistent") if type(ledger.get("cash_consistent")) is bool else None,
            pnl_consistent=ledger.get("pnl_consistent") if type(ledger.get("pnl_consistent")) is bool else None,
            exposure_consistent=ledger.get("exposure_consistent") if type(ledger.get("exposure_consistent")) is bool else None,
            open_orders_consistent=ledger.get("open_orders_consistent") if type(ledger.get("open_orders_consistent")) is bool else None,
            protection_consistent=ledger.get("protection_consistent") if type(ledger.get("protection_consistent")) is bool else None,
            account_equity=equity,
            total_exposure=exposure_usdt,
            daily_pnl=_number(
                ledger.get("daily_pnl")
                if "daily_pnl" in ledger
                else pnl.get("daily")
            ),
            # Legacy bare drawdown values are intentionally not consumed.
            # The guardian selects amount/ratio only from the bound fact above.
            drawdown=None,
            open_order_count=len(open_orders),
            risk_increasing_open_order_count=risk_order_count,
            protective_reduce_only_order_count=protective_order_count,
            order_risk_blockers=order_risk_blockers,
            freshness={"exchange_captured_at_utc": True, "explicit": explicit_fresh},
            evidence_identity="btc_demo_production_composition_t4_observation_v2",
        )

    def _guardian(self, observation: GuardianObservation) -> tuple[Any, Mapping[str, Any]]:
        supervisor = self._supervisor()
        if supervisor is not None:
            decision = supervisor.evaluate(observation)
            # Persist a newly observed trip only when a durable record already
            # exists.  A missing/corrupt latch must remain a blocker and may
            # never be silently bootstrapped or cleared by this composition.
            if (
                decision.tripped
                and getattr(supervisor, "latch", None) is not None
                and not bool(getattr(supervisor, "tripped", False))
            ):
                decision = supervisor.trip(observation)
            latch = supervisor.latch.to_dict() if getattr(supervisor, "latch", None) is not None else {"tripped": True, "reason_codes": ["latch_persistence_missing"]}
            return decision, latch
        config = self.guardian_config if self.guardian_config is not None else GuardianConfig(
            max_abs_exposure=float(self.max_notional),
            max_daily_loss=float(self.loss_limit_usdt),
            max_drawdown=float(self.loss_limit_usdt),
            max_open_orders=0,
        )
        decision = RuntimeRiskGuardian(config).evaluate(observation)
        return decision.with_blockers("latch_persistence_missing"), {"tripped": True, "reason_codes": ["latch_persistence_missing"]}

    def build_order_submission_bundle(self, **kwargs: Any) -> OMSOrderSubmissionBundle:
        if kwargs.get("guardian_health") or kwargs.get("guardian_latch"):
            raise ValueError("guardian_observation_required")
        signal = kwargs.get("signal")
        target = kwargs.get("target_position")
        intent = kwargs.get("intent")
        if not isinstance(signal, Signal) or not isinstance(target, TargetPosition) or not isinstance(intent, OrderIntent):
            raise ValueError("authoritative_order_objects_required")
        exchange = _mapping(kwargs.get("exchange_snapshot"))
        private_ws = _mapping(kwargs.get("private_ws"))
        ledger = _mapping(kwargs.get("ledger_reconciliation"))
        runtime = _mapping(kwargs.get("runtime_facts") or kwargs.get("runtime_state"))
        supplied_source_head = str(kwargs.get("source_head") or "").strip().lower()
        if supplied_source_head and supplied_source_head != self.source_head:
            raise ValueError("source_head_evidence_mismatch")
        reference_time = kwargs.get("reference_time_utc")
        if not exchange or not private_ws or not ledger or not isinstance(reference_time, datetime):
            raise ValueError("guardian_observation_required")
        before = _number(kwargs.get("position_before"))
        after = _number(kwargs.get("position_after"))
        price = _number(kwargs.get("price"))
        quantity = _number(kwargs.get("quantity"))
        if before is None or after is None or price is None or quantity is None:
            raise ValueError("explicit_position_price_quantity_required")
        venue = dict(_mapping(kwargs.get("venue_facts")))
        if venue.get("instrument_id") != BTC_DEMO_INSTRUMENT_ID or str(venue.get("margin_mode") or "").lower() != "isolated":
            raise ValueError("venue_facts_invalid")
        position_side = str(venue.get("position_side") or "").lower()
        if position_side not in {"long", "short"}:
            raise ValueError("venue_position_side_invalid")
        leverage_blockers = validate_isolated_leverage(
            venue.get("leverage"),
            self.max_configured_leverage,
        )
        if leverage_blockers:
            raise ValueError("leverage_evidence_invalid:" + ";".join(leverage_blockers))
        costs = dict(_mapping(kwargs.get("cost_facts")))
        if not costs:
            raise ValueError("cost_facts_missing")
        contract_value = _contract_value_btc(exchange, venue)
        venue["contract_value_btc"] = format(contract_value, "f")
        account_equity = _extract_equity(exchange, ledger)
        index = _extract_price(exchange, "index_price", "indexPx", "last", "mark_price")
        mark = _extract_price(exchange, "mark_price", "markPx", "last", "last_price")
        if mark is None or index is None or account_equity is None:
            raise ValueError("broker_truth_facts_required")
        actual_notional = contract_notional_usdt(quantity, price, contract_value)
        if actual_notional > self.max_notional:
            raise ValueError("contract_notional_limit_breach")
        costs.update(
            {
                "contract_value_btc": format(contract_value, "f"),
                "contract_notional_usdt": format(actual_notional, "f"),
            }
        )
        authoritative_pnl = _authoritative_pnl_facts(exchange, ledger)
        costs = _cost_inputs_from_bps(
            costs,
            actual_notional=actual_notional,
            observed_funding_cashflow=Decimal(str(authoritative_pnl["funding_cashflow"])),
        )
        costs.update(authoritative_pnl)
        normalized_protection = normalize_hosted_protection_facts(
            pending_algo_orders=_rows(exchange.get("pending_algo_orders")),
            positions=_position_rows(exchange),
            account=_mapping(exchange.get("account")),
            runtime_facts=runtime,
            ownership_facts=_mapping(kwargs.get("hosted_protection_facts")),
            snapshot_sha256=canonical_ledger_snapshot_sha256(exchange),
            snapshot_captured_at_utc=exchange.get("captured_at_utc"),
            expected_instrument_id=BTC_DEMO_INSTRUMENT_ID,
        )
        normalized_pending_algos = normalized_protection["rows"]
        costs["hosted_protection_facts"] = {
            "schema_version": normalized_protection["schema_version"],
            "snapshot_sha256": normalized_protection["snapshot_sha256"],
            "blockers": list(normalized_protection["blockers"]),
        }
        opening = kwargs.get("action") is RuntimeAction.SUBMIT_NEW_ORDER or str(kwargs.get("action")) in {"submit_new_order", "RuntimeAction.SUBMIT_NEW_ORDER"}
        target_generation_allowed = _read_target_generation_allowed(target)
        if opening and target_generation_allowed is not True:
            raise ValueError("opening_requires_t3_approved_original_target")
        if not opening and target_generation_allowed is True:
            raise ValueError("reduction_target_generation_must_be_false")
        protection_before = _rows(exchange.get("pending_algo_orders"))
        protection_after = None
        protection = None
        if opening:
            policy = _mapping(kwargs.get("protection_policy"))
            if not policy:
                raise ValueError("attached_protection_policy_required")
            tick = _decimal(_mapping(exchange.get("instrument")).get("tick_size") or venue.get("tick_size") or "0.1")
            if tick is None or tick <= 0:
                raise ValueError("tick_size_required")
            protection = SharedPlatformV3OMS().build_attached_protection(
                policy=policy,
                entry_price=str(price),
                tick_size=str(tick),
                position_side=position_side,
                client_order_id=intent.client_order_id,
                contracts=str(quantity),
            )
            protection_after = _adapt_protection_for_t2(
                protection.to_exchange_payload(),
                position_side=position_side,
                quantity=quantity,
                contract_value_btc=contract_value,
            )
            costs["t2_protection_projection"] = dict(protection_after)
        reconciliation_projection = _project_reconciliation_evidence(
            exchange,
            ledger,
            opening_protection=protection_after,
            expected_parent_client_order_id=intent.client_order_id,
            opening=opening,
        )
        if reconciliation_projection["blockers"]:
            raise ValueError(
                "reconciliation_evidence_required:"
                + ";".join(reconciliation_projection["blockers"])
            )
        projected_ledger = reconciliation_projection["ledger"]
        costs["reconciliation_evidence"] = reconciliation_projection["evidence"]
        constitution = RiskConstitution(
            max_abs_position=float(self.max_abs_position),
            max_quantity=float(self.max_abs_position),
            max_notional=float(self.max_notional),
            max_leverage=float(self.max_configured_leverage),
            min_liquidation_buffer_bps=0.0,
            max_daily_loss=float(self.loss_limit_usdt),
            max_drawdown=float(self.loss_limit_usdt),
            max_combined_loss=float(self.loss_limit_usdt),
            protection_required=True,
        )
        assessment: RiskAssessment = assess_btc_risk(
            constitution=constitution,
            position_before=before,
            position_after=after,
            # T2 quantities remain in OKX contracts for T3/T5 identity.  Scale
            # prices into USDT-per-contract so its notional/leverage math is
            # explicitly equivalent to contracts * ctVal * BTC price.
            mark_price=mark * float(contract_value),
            index_price=index * float(contract_value),
            account_equity=account_equity,
            protection_before=protection_before,
            protection_after=protection_after,
            realized_pnl=authoritative_pnl["realized_pnl"],
            unrealized_pnl=authoritative_pnl["unrealized_pnl"],
            funding_cashflow=authoritative_pnl["funding_cashflow"],
            fees=_number(costs.get("fees")),
            slippage=_number(costs.get("slippage")),
            impact=_number(costs.get("impact")),
        )
        decision: BTCPortfolioDecision = build_btc_portfolio_decision(
            target,
            current_quantity=before,
            risk_assessment=assessment,
            decision_time_utc=reference_time,
            source="btc_demo_production_composition",
        )
        observation = self._guardian_observation(
            exchange_snapshot=exchange,
            private_ws=private_ws,
            ledger=projected_ledger,
            runtime=runtime,
            reference_time=reference_time,
            intent=intent,
            position_after=after,
            protection_facts=protection_after,
            normalized_pending_algos=normalized_pending_algos,
        )
        guardian_decision, latch = self._guardian(observation)
        effect = ActionRiskEffect.INCREASE_ABS_EXPOSURE if abs(after) > abs(before) else ActionRiskEffect.DECREASE_ABS_EXPOSURE if abs(after) < abs(before) else ActionRiskEffect.NO_POSITION_EFFECT
        proof = OMSProofIdentity(
            source_head=self.source_head,
            account_identity=observation.account_identity,
            session_id=observation.session_id,
            key_namespace=observation.key_namespace,
            client_order_namespace=observation.client_order_namespace,
            epoch=observation.epoch or 0,
            intent_digest=order_intent_execution_digest(intent),
            guardian_digest=guardian_decision.evidence_digest if guardian_decision.evidence_digest else "",
        )
        return OMSOrderSubmissionBundle(
            signal=signal,
            target_position=target,
            risk_assessment=assessment,
            portfolio_decision=decision,
            position_before=before,
            position_after=after,
            action=kwargs.get("action"),
            risk_effect=effect,
            proof_identity=proof,
            price=str(price),
            quantity=str(quantity),
            venue_facts=venue,
            cost_facts=costs,
            intent=intent,
            protection=protection,
            guardian_health=guardian_decision.to_dict(),
            guardian_latch=latch,
        )


def _derive_protective_capabilities_legacy(status: Mapping[str, Any], *, max_configured_leverage: Decimal | str | int | float = Decimal("1")) -> dict[str, Any]:
    """Project reduction-only capability from one authoritative status.

    This is intentionally evidence-shaped: a boolean from ``risk_control`` or
    an old action map is never treated as a reduction proof.
    """

    exchange = _mapping(status.get("exchange"))
    ledger = _mapping(status.get("ledger_reconciliation"))
    private_ws = _mapping(status.get("private_ws"))
    rows = _position_rows(exchange)
    nonflat = [row for row in rows if abs(_number(row.get("contracts") or row.get("pos")) or 0.0) > 0.0]
    blockers: list[str] = []
    reduction_cost_source = ""
    if len(nonflat) != 1:
        blockers.append("protective_position_not_unique")
    captured = _parse_utc(exchange.get("captured_at_utc"))
    if captured is None:
        blockers.append("protective_exchange_snapshot_missing")
    if private_ws.get("connected") is not True or private_ws.get("listener_alive") is not True:
        blockers.append("protective_private_ws_not_current")
    if str(ledger.get("status") or "") != "reconciled" or ledger.get("current_state_exchange_snapshot_match") is not True or ledger.get("funding_cashflow_reconciled") is not True:
        blockers.append("protective_ledger_not_reconciled")
    if _rows(exchange.get("pending_orders")):
        blockers.append("protective_pending_order_present")
    pending_algos = _rows(exchange.get("pending_algo_orders"))
    if len(pending_algos) > 1:
        blockers.append("protective_algo_identity_ambiguous")
    proof = not blockers
    reduction_plan: RiskReductionPlan | None = None
    if proof:
        row = nonflat[0]
        side = str(row.get("position_side") or row.get("posSide") or "").lower()
        qty = _number(row.get("contracts") or row.get("pos"))
        if side not in {"long", "short"} or qty is None or qty == 0:
            proof = False
            blockers.append("protective_position_identity_invalid")
        for algo in pending_algos:
            algo_instrument = str(algo.get("instrument_id") or algo.get("instId") or "").strip()
            algo_side = str(algo.get("position_side") or algo.get("posSide") or "").strip().lower()
            algo_state = str(algo.get("state") or algo.get("status") or "").strip().lower()
            algo_size = _number(algo.get("contracts") or algo.get("sz") or algo.get("size"))
            algo_type = str(algo.get("order_type") or algo.get("ordType") or algo.get("type") or "").strip().lower()
            if algo_instrument and algo_instrument != BTC_DEMO_INSTRUMENT_ID:
                blockers.append("protective_algo_instrument_mismatch")
            if not algo_instrument:
                blockers.append("protective_algo_instrument_missing")
            if algo_side and algo_side != side:
                blockers.append("protective_algo_position_side_mismatch")
            if not algo_side:
                blockers.append("protective_algo_position_side_missing")
            if algo_state and algo_state not in {"live", "effective"}:
                blockers.append("protective_algo_not_live")
            if not algo_state:
                blockers.append("protective_algo_state_missing")
            if algo_size is not None and qty is not None and abs(algo_size - qty) > 1e-12:
                blockers.append("protective_algo_quantity_mismatch")
            if algo_size is None:
                blockers.append("protective_algo_quantity_missing")
            if algo_type and algo_type not in {"oco", "conditional_oco"}:
                blockers.append("protective_algo_type_mismatch")
            if not algo_type:
                blockers.append("protective_algo_type_missing")
        proof = not blockers
    if proof:
        # Reuse the canonical T2/T3 path to prove a reduction capability.  The
        # projection is deliberately target=0 and order_generation_allowed is
        # false: it can only describe a signed decrease, never authorize an
        # opening action.
        strategy = _mapping(status.get("strategy"))
        signal_facts = _mapping(status.get("signal"))
        strategy_id = str(
            strategy.get("strategy_id")
            or strategy.get("id")
            or ""
        ).strip()
        forecast_id = str(
            strategy.get("forecast_id")
            or signal_facts.get("forecast_id")
            or strategy.get("strategy_version")
            or _mapping(status.get("runtime")).get("run_id")
            or ""
        ).strip()
        mark = _extract_price(exchange, "mark_price", "markPx", "last", "last_price")
        index = _extract_price(exchange, "index_price", "indexPx", "last", "last_price")
        equity = _extract_equity(exchange, ledger)
        captured = _parse_utc(exchange.get("captured_at_utc"))
        limits = _mapping(status.get("limits"))
        max_abs = _decimal(
            limits.get("max_net_contracts")
            or limits.get("max_abs_position")
            or limits.get("max_quantity")
        )
        max_notional = _decimal(
            limits.get("max_notional_usdt") or limits.get("max_order_notional_usdt")
        )
        max_loss = _decimal(limits.get("max_loss_usdt", max_notional))
        if not strategy_id or not forecast_id:
            blockers.append("protective_reduction_identity_missing")
        if mark is None or index is None or equity is None or captured is None:
            blockers.append("protective_reduction_facts_missing")
        if max_abs is None or max_abs <= 0 or max_notional is None or max_notional <= 0 or max_loss is None or max_loss <= 0:
            blockers.append("protective_policy_missing")
        if not blockers:
            assert qty is not None and mark is not None and index is not None and equity is not None
            assert max_abs is not None and max_notional is not None and captured is not None
            direction = SignalDirection.LONG if side == "long" else SignalDirection.SHORT
            signal = Signal(
                timestamp_utc=captured,
                strategy_id=strategy_id,
                symbol=BTC_DEMO_INSTRUMENT_ID,
                direction=direction,
                strength=1.0,
                horizon="authoritative_runtime_reduction",
                reason="authoritative_broker_truth_reduction_projection",
                metadata={"forecast_id": forecast_id},
            )
            target = TargetPosition(
                timestamp_utc=captured,
                strategy_id=strategy_id,
                symbol=BTC_DEMO_INSTRUMENT_ID,
                target_weight=0.0,
                target_quantity=0.0,
                signal_id=signal.signal_id,
                metadata={
                    "forecast_id": forecast_id,
                    "order_generation_allowed": False,
                },
            )
            constitution = RiskConstitution(
                max_abs_position=float(max_abs),
                max_quantity=float(max_abs),
                max_notional=float(max_notional),
                max_leverage=float(_decimal(max_configured_leverage) or Decimal("1")),
                min_liquidation_buffer_bps=0.0,
                max_daily_loss=float(max_loss),
                max_drawdown=float(max_loss),
                max_combined_loss=float(max_loss),
                protection_required=True,
            )
            reduction_costs = _reduction_cost_inputs(ledger)
            reduction_cost_source = str(reduction_costs["source"])
            assessment = assess_btc_risk(
                constitution=constitution,
                position_before=qty,
                position_after=0.0,
                mark_price=mark,
                index_price=index,
                account_equity=equity,
                protection_before=_rows(exchange.get("pending_algo_orders")),
                protection_after=None,
                realized_pnl=_number(ledger.get("realized_pnl")),
                unrealized_pnl=_number(ledger.get("unrealized_pnl")),
                funding_cashflow=_number(ledger.get("funding_cashflow")),
                fees=reduction_costs["fees"],
                slippage=reduction_costs["slippage"],
                impact=reduction_costs["impact"],
            )
            decision = build_btc_portfolio_decision(
                target,
                current_quantity=qty,
                risk_assessment=assessment,
                decision_time_utc=captured,
                source="btc_demo_production_composition_t3",
            )
            reduction_plan = decision.reduction_plan
            if not isinstance(reduction_plan, RiskReductionPlan):
                proof = False
                blockers.append("protective_reduction_plan_unavailable")
    capability = {
        "allowed": proof,
        "effect": "decrease" if proof else "unknown",
        "reduction_proof": proof,
        "position_authority": proof,
        "blockers": sorted(set(blockers)),
        "reduction_plan": reduction_plan.to_dict() if reduction_plan is not None else {},
        "reduction_cost_source": reduction_cost_source,
        "source": "btc_demo_production_composition_t3_reduction_projection",
    }
    return {
        "stop_and_flatten": dict(capability),
        "emergency_reduce_only_exit": dict(capability),
    }


def derive_protective_capabilities(
    status: Mapping[str, Any],
    *,
    max_configured_leverage: Decimal | str | int | float = Decimal("1"),
) -> dict[str, Any]:
    """Project a bounded, fresh, signed T3 reduction capability.

    This projection consumes one broker/ledger/WS snapshot.  It never uses
    wall-clock time, treats an empty algo list as *no protection evidence* (but
    not as a malformed list), and never grants opening authority.
    """

    exchange = _mapping(status.get("exchange"))
    ledger = _mapping(status.get("ledger_reconciliation"))
    private_ws = _mapping(status.get("private_ws"))
    runtime = _mapping(status.get("runtime"))
    reconciliation_projection = _project_reconciliation_evidence(
        exchange,
        ledger,
        opening=False,
    )
    ledger = reconciliation_projection["ledger"]
    rows = _position_rows(exchange)
    nonflat = [
        row for row in rows
        if abs(_number(row.get("contracts") or row.get("pos")) or 0.0) > 0.0
    ]
    # Preserve the explicit projection blockers so callers can distinguish a
    # missing raw evidence fact from a generic derived boolean mismatch.
    blockers: list[str] = list(reconciliation_projection["blockers"])
    reduction_cost_source = ""

    captured = _parse_utc(exchange.get("captured_at_utc") or exchange.get("captured_at"))
    reference = _parse_utc(
        status.get("as_of_utc")
        or runtime.get("last_heartbeat_utc")
        or exchange.get("reference_time_utc")
    )
    if captured is None:
        blockers.append("protective_exchange_snapshot_missing")
    if reference is None:
        blockers.append("protective_reference_time_missing")
    elif captured is not None:
        age = (reference - captured).total_seconds()
        if age < 0 or age > 120:
            blockers.append("protective_exchange_snapshot_stale")
    if exchange.get("fresh") is False or exchange.get("stale") is True:
        blockers.append("protective_exchange_snapshot_stale")

    if len(nonflat) != 1:
        blockers.append("protective_position_not_unique")
    if private_ws.get("connected") is not True or private_ws.get("listener_alive") is not True:
        blockers.append("protective_private_ws_not_current")
    if private_ws.get("reconciled") is False:
        blockers.append("protective_private_ws_not_reconciled")
    for left, right in (("generation", "current_generation"), ("epoch", "current_epoch")):
        if left in private_ws and right in private_ws and private_ws[left] != private_ws[right]:
            blockers.append("protective_private_ws_generation_mismatch")

    if (
        str(ledger.get("status") or "") != "reconciled"
        or ledger.get("current_state_exchange_snapshot_match") is not True
        or ledger.get("funding_cashflow_reconciled") is not True
    ):
        blockers.append("protective_ledger_not_reconciled")
    for field in (
        "positions_consistent",
        "cash_consistent",
        "pnl_consistent",
        "exposure_consistent",
        "open_orders_consistent",
        "protection_consistent",
    ):
        if ledger.get(field) is not True:
            blockers.append(
                f"protective_{field}_unknown"
                if field not in ledger
                else f"protective_{field}_mismatch"
            )
    if _rows(exchange.get("pending_orders")):
        blockers.append("protective_pending_order_present")
    pending_algos = _rows(exchange.get("pending_algo_orders"))
    if len(pending_algos) > 1:
        blockers.append("protective_algo_identity_ambiguous")

    row = nonflat[0] if len(nonflat) == 1 else {}
    side = str(row.get("position_side") or row.get("posSide") or "").strip().lower()
    qty = _number(row.get("contracts") or row.get("pos"))
    if side not in {"long", "short"} or qty is None or qty <= 0:
        blockers.append("protective_position_identity_invalid")

    for algo in pending_algos:
        instrument = str(algo.get("instrument_id") or algo.get("instId") or "").strip()
        algo_side = str(algo.get("position_side") or algo.get("posSide") or "").strip().lower()
        state = str(algo.get("state") or algo.get("status") or "").strip().lower()
        size = _number(algo.get("contracts") or algo.get("sz") or algo.get("size"))
        order_type = str(algo.get("order_type") or algo.get("ordType") or algo.get("type") or "").strip().lower()
        if instrument != BTC_DEMO_INSTRUMENT_ID:
            blockers.append("protective_algo_instrument_mismatch" if instrument else "protective_algo_instrument_missing")
        if algo_side != side:
            blockers.append("protective_algo_position_side_mismatch" if algo_side else "protective_algo_position_side_missing")
        if state not in {"live", "effective"}:
            blockers.append("protective_algo_not_live" if state else "protective_algo_state_missing")
        if size is None:
            blockers.append("protective_algo_quantity_missing")
        elif qty is not None and abs(size - qty) > 1e-12:
            blockers.append("protective_algo_quantity_mismatch")
        if order_type not in {"oco", "conditional_oco"}:
            blockers.append("protective_algo_type_mismatch" if order_type else "protective_algo_type_missing")

    try:
        contract_value = _contract_value_btc(exchange)
    except ValueError:
        contract_value = None
        blockers.append("protective_contract_value_missing")

    proof = not blockers
    reduction_plan: RiskReductionPlan | None = None
    if proof:
        strategy = _mapping(status.get("strategy"))
        signal_facts = _mapping(status.get("signal"))
        strategy_id = str(strategy.get("strategy_id") or strategy.get("id") or "").strip()
        forecast_id = str(
            strategy.get("forecast_id")
            or signal_facts.get("forecast_id")
            or strategy.get("strategy_version")
            or runtime.get("run_id")
            or ""
        ).strip()
        mark = _extract_price(exchange, "mark_price", "markPx", "last", "last_price")
        index = _extract_price(exchange, "index_price", "indexPx", "last", "last_price")
        equity = _extract_equity(exchange, ledger)
        limits = _mapping(status.get("limits"))
        max_abs = _decimal(
            limits.get("max_net_contracts")
            or limits.get("max_abs_position")
            or limits.get("max_quantity")
        )
        max_notional = _decimal(
            limits.get("max_notional_usdt") or limits.get("max_order_notional_usdt")
        )
        max_loss = _decimal(limits.get("max_loss_usdt", max_notional))
        if not strategy_id or not forecast_id:
            blockers.append("protective_reduction_identity_missing")
        if mark is None or index is None or equity is None or captured is None or contract_value is None:
            blockers.append("protective_reduction_facts_missing")
        try:
            pnl = _authoritative_pnl_facts(exchange, ledger)
        except ValueError as exc:
            pnl = None
            blockers.append(str(exc))
        if max_abs is None or max_abs <= 0 or max_notional is None or max_notional <= 0 or max_loss is None or max_loss <= 0:
            blockers.append("protective_policy_missing")
        if not blockers:
            assert qty is not None and mark is not None and index is not None and equity is not None
            assert max_abs is not None and max_notional is not None and captured is not None and contract_value is not None
            assert pnl is not None
            signed_qty = qty if side == "long" else -qty
            direction = SignalDirection.LONG if side == "long" else SignalDirection.SHORT
            signal = Signal(
                timestamp_utc=captured,
                strategy_id=strategy_id,
                symbol=BTC_DEMO_INSTRUMENT_ID,
                direction=direction,
                strength=1.0,
                horizon="authoritative_runtime_reduction",
                reason="authoritative_broker_truth_reduction_projection",
                metadata={"forecast_id": forecast_id},
            )
            target = TargetPosition(
                timestamp_utc=captured,
                strategy_id=strategy_id,
                symbol=BTC_DEMO_INSTRUMENT_ID,
                target_weight=0.0,
                target_quantity=0.0,
                signal_id=signal.signal_id,
                metadata={"forecast_id": forecast_id, "order_generation_allowed": False},
            )
            constitution = RiskConstitution(
                max_abs_position=float(max_abs),
                max_quantity=float(max_abs),
                max_notional=float(max_notional),
                max_leverage=float(_decimal(max_configured_leverage) or Decimal("1")),
                min_liquidation_buffer_bps=0.0,
                max_daily_loss=float(max_loss),
                max_drawdown=float(max_loss),
                max_combined_loss=float(max_loss),
                protection_required=True,
            )
            reduction_costs = _reduction_cost_inputs(ledger)
            reduction_cost_source = str(reduction_costs["source"])
            assessment = assess_btc_risk(
                constitution=constitution,
                position_before=signed_qty,
                position_after=0.0,
                mark_price=mark * float(contract_value),
                index_price=index * float(contract_value),
                account_equity=equity,
                protection_before=pending_algos,
                protection_after=None,
                realized_pnl=pnl["realized_pnl"],
                unrealized_pnl=pnl["unrealized_pnl"],
                funding_cashflow=pnl["funding_cashflow"],
                fees=reduction_costs["fees"],
                slippage=reduction_costs["slippage"],
                impact=reduction_costs["impact"],
            )
            decision = build_btc_portfolio_decision(
                target,
                current_quantity=signed_qty,
                risk_assessment=assessment,
                decision_time_utc=captured,
                source="btc_demo_production_composition_t3",
            )
            reduction_plan = decision.reduction_plan
            if not isinstance(reduction_plan, RiskReductionPlan):
                proof = False
                blockers.append("protective_reduction_plan_unavailable")

    capability = {
        "allowed": proof,
        "effect": "decrease" if proof else "unknown",
        "reduction_proof": proof,
        "position_authority": proof,
        "blockers": sorted(set(blockers)),
        "reduction_plan": reduction_plan.to_dict() if reduction_plan is not None else {},
        "reduction_cost_source": reduction_cost_source,
        "reconciliation_evidence": reconciliation_projection["evidence"],
        "source": "btc_demo_production_composition_t3_reduction_projection",
    }
    return {
        "stop_and_flatten": dict(capability),
        "emergency_reduce_only_exit": dict(capability),
    }


__all__ = [
    "BTC_DEMO_INSTRUMENT_ID",
    "BtcDemoProductionComposition",
    "contract_notional_usdt",
    "derive_protective_capabilities",
    "expected_isolated_leverage",
    "leverage_blocker_code",
    "validate_isolated_leverage",
]
