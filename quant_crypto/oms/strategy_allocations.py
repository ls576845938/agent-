"""Non-economic attribution facts for shared-account BTC offline fills.

The exchange raw fills and bills remain the only economic ledger.  This
module binds those immutable rows to strategy members and proves quantity,
fee and funding conservation without rewriting the source rows.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


STRATEGY_ALLOCATIONS_SCHEMA_VERSION = "btc_strategy_allocations_v1"


class StrategyAllocationError(ValueError):
    pass


def _decimal(value: Any, code: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise StrategyAllocationError(code)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise StrategyAllocationError(code) from exc
    if not result.is_finite():
        raise StrategyAllocationError(code)
    return result


def _text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()


def empty_strategy_allocation_state(
    *, member_ids: Sequence[str], member_list_sha256: str
) -> dict[str, Any]:
    members = tuple(sorted(str(value) for value in member_ids))
    if len(members) != 2 or len(set(members)) != 2 or not member_list_sha256:
        raise StrategyAllocationError("strategy_allocation_members_invalid")
    return {
        "schema_version": STRATEGY_ALLOCATIONS_SCHEMA_VERSION,
        "member_list_sha256": member_list_sha256,
        "member_contracts": {member: "0" for member in members},
        "ownership_history": [],
        "fill_allocations": {},
        "funding_allocations": {},
        "protection_revision": {},
    }


def _member_deltas(plan: Mapping[str, Any]) -> dict[str, Decimal]:
    raw = plan.get("member_delta_contracts")
    if not isinstance(raw, Mapping) or len(raw) != 2:
        raise StrategyAllocationError("strategy_allocation_plan_deltas_invalid")
    deltas = {
        str(member): _decimal(value, "strategy_allocation_plan_delta_invalid")
        for member, value in raw.items()
    }
    nonzero = {member: value for member, value in deltas.items() if value}
    if not nonzero:
        raise StrategyAllocationError("strategy_allocation_plan_has_no_order")
    signs = {1 if value > 0 else -1 for value in nonzero.values()}
    if len(signs) != 1:
        raise StrategyAllocationError("strategy_allocation_plan_delta_direction_conflict")
    expected = _decimal(
        plan.get("order_delta_contracts"),
        "strategy_allocation_plan_order_delta_invalid",
    )
    if sum(deltas.values()) != expected:
        raise StrategyAllocationError("strategy_allocation_plan_delta_not_conserved")
    return deltas


def _event_time_ms(value: Mapping[str, Any], code: str) -> Decimal:
    timestamp = _decimal(value.get("timestamp_ms", value.get("ts")), code)
    if timestamp <= 0 or timestamp != timestamp.to_integral_value():
        raise StrategyAllocationError(code)
    return timestamp


def allocate_raw_fill(
    *,
    state: Mapping[str, Any],
    allocation_plan: Mapping[str, Any],
    raw_fill: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze one actual raw fill across member deltas with exact conservation."""

    if state.get("schema_version") != STRATEGY_ALLOCATIONS_SCHEMA_VERSION:
        raise StrategyAllocationError("strategy_allocation_state_schema_mismatch")
    if state.get("member_list_sha256") != allocation_plan.get("member_list_sha256"):
        raise StrategyAllocationError("strategy_allocation_member_list_mismatch")
    fill_id = str(raw_fill.get("fill_id") or raw_fill.get("tradeId") or "")
    order_id = str(raw_fill.get("order_id") or raw_fill.get("ordId") or "")
    if not fill_id or not order_id:
        raise StrategyAllocationError("strategy_allocation_fill_identity_missing")
    fill_digest = _digest(dict(raw_fill))
    prior_rows = state.get("fill_allocations")
    if not isinstance(prior_rows, Mapping):
        raise StrategyAllocationError("strategy_allocation_fill_state_invalid")
    prior = prior_rows.get(fill_id)
    if isinstance(prior, Mapping):
        if prior.get("raw_fill_sha256") != fill_digest:
            raise StrategyAllocationError("strategy_allocation_fill_identity_conflict")
        return json.loads(json.dumps(state))
    fill_time_ms = _event_time_ms(
        raw_fill, "strategy_allocation_fill_time_unproven"
    )

    deltas = _member_deltas(allocation_plan)
    requested = sum(abs(value) for value in deltas.values())
    quantity = _decimal(
        raw_fill.get("size", raw_fill.get("fillSz")),
        "strategy_allocation_fill_quantity_invalid",
    )
    if quantity <= 0 or quantity > requested:
        raise StrategyAllocationError("strategy_allocation_fill_quantity_out_of_plan")
    side = str(raw_fill.get("side") or "").lower()
    fill_sign = Decimal("1") if side == "buy" else Decimal("-1") if side == "sell" else None
    plan_sign = Decimal("1") if sum(deltas.values()) > 0 else Decimal("-1")
    if fill_sign is None or fill_sign != plan_sign:
        raise StrategyAllocationError("strategy_allocation_fill_side_mismatch")
    fee = _decimal(raw_fill.get("fee", 0), "strategy_allocation_fill_fee_invalid")
    ordered = sorted(member for member, value in deltas.items() if value)
    remaining_quantity = quantity
    remaining_fee = fee
    member_rows: dict[str, dict[str, str]] = {}
    for index, member in enumerate(ordered):
        if index == len(ordered) - 1:
            allocated_quantity = remaining_quantity
            allocated_fee = remaining_fee
        else:
            weight = abs(deltas[member]) / requested
            allocated_quantity = quantity * weight
            allocated_fee = fee * weight
            remaining_quantity -= allocated_quantity
            remaining_fee -= allocated_fee
        member_rows[member] = {
            "signed_contracts": _text(fill_sign * allocated_quantity),
            "fee": _text(allocated_fee),
        }
    if sum(Decimal(row["signed_contracts"]) for row in member_rows.values()) != fill_sign * quantity:
        raise StrategyAllocationError("strategy_allocation_fill_quantity_not_conserved")
    if sum(Decimal(row["fee"]) for row in member_rows.values()) != fee:
        raise StrategyAllocationError("strategy_allocation_fill_fee_not_conserved")

    result = json.loads(json.dumps(state))
    holdings = {
        member: _decimal(value, "strategy_allocation_member_contracts_invalid")
        for member, value in result["member_contracts"].items()
    }
    if set(holdings) != set(deltas):
        raise StrategyAllocationError("strategy_allocation_state_members_mismatch")
    for member, row in member_rows.items():
        updated = holdings[member] + Decimal(row["signed_contracts"])
        # A reduction fill may reach zero but may not cross into a new risk side.
        if holdings[member] and updated and (holdings[member] > 0) != (updated > 0):
            raise StrategyAllocationError("strategy_allocation_member_fill_reversal")
        holdings[member] = updated
    result["member_contracts"] = {
        member: _text(holdings[member]) for member in sorted(holdings)
    }
    history = result.get("ownership_history")
    if not isinstance(history, list):
        raise StrategyAllocationError("strategy_allocation_ownership_history_invalid")
    if history:
        latest_time = _decimal(
            history[-1].get("effective_at_ms")
            if isinstance(history[-1], Mapping)
            else None,
            "strategy_allocation_ownership_history_invalid",
        )
        if fill_time_ms < latest_time:
            raise StrategyAllocationError(
                "strategy_allocation_fill_time_out_of_order"
            )
    history.append(
        {
            "effective_at_ms": _text(fill_time_ms),
            "fill_id": fill_id,
            "member_contracts": dict(result["member_contracts"]),
        }
    )
    result["fill_allocations"][fill_id] = {
        "raw_fill_sha256": fill_digest,
        "order_id": order_id,
        "raw_quantity": _text(quantity),
        "raw_signed_quantity": _text(fill_sign * quantity),
        "raw_fee": _text(fee),
        "fee_currency": str(raw_fill.get("fee_currency") or raw_fill.get("feeCcy") or ""),
        "effective_at_ms": _text(fill_time_ms),
        "allocation_plan_sha256": str(
            allocation_plan.get("allocation_plan_sha256") or ""
        ),
        "members": member_rows,
    }
    return result


def allocate_funding_bill(
    *, state: Mapping[str, Any], raw_bill: Mapping[str, Any]
) -> dict[str, Any]:
    """Attribute one immutable funding bill by current absolute ownership."""

    if state.get("schema_version") != STRATEGY_ALLOCATIONS_SCHEMA_VERSION:
        raise StrategyAllocationError("strategy_allocation_state_schema_mismatch")
    bill_id = str(raw_bill.get("bill_id") or raw_bill.get("billId") or "")
    if not bill_id:
        raise StrategyAllocationError("strategy_allocation_funding_bill_id_missing")
    bill_digest = _digest(dict(raw_bill))
    prior_rows = state.get("funding_allocations")
    if not isinstance(prior_rows, Mapping):
        raise StrategyAllocationError("strategy_allocation_funding_state_invalid")
    prior = prior_rows.get(bill_id)
    if isinstance(prior, Mapping):
        if prior.get("raw_bill_sha256") != bill_digest:
            raise StrategyAllocationError("strategy_allocation_funding_identity_conflict")
        return json.loads(json.dumps(state))
    bill_time_ms = _event_time_ms(
        raw_bill, "strategy_allocation_funding_time_or_owner_unproven"
    )
    history = state.get("ownership_history")
    if not isinstance(history, list) or not history:
        raise StrategyAllocationError(
            "strategy_allocation_funding_time_or_owner_unproven"
        )
    ownership: Mapping[str, Any] | None = None
    for row in history:
        if not isinstance(row, Mapping):
            raise StrategyAllocationError(
                "strategy_allocation_ownership_history_invalid"
            )
        effective_at = _decimal(
            row.get("effective_at_ms"),
            "strategy_allocation_ownership_history_invalid",
        )
        if effective_at == bill_time_ms:
            raise StrategyAllocationError(
                "strategy_allocation_funding_time_or_owner_unproven"
            )
        if effective_at < bill_time_ms:
            ownership = row
    if ownership is None:
        raise StrategyAllocationError(
            "strategy_allocation_funding_time_or_owner_unproven"
        )
    ownership_contracts = ownership.get("member_contracts")
    if not isinstance(ownership_contracts, Mapping):
        raise StrategyAllocationError(
            "strategy_allocation_ownership_history_invalid"
        )
    holdings = {
        str(member): _decimal(value, "strategy_allocation_member_contracts_invalid")
        for member, value in ownership_contracts.items()
    }
    active = {member: abs(value) for member, value in holdings.items() if value}
    gross = sum(active.values())
    if not active or gross <= 0:
        raise StrategyAllocationError("strategy_allocation_funding_owner_missing")
    amount = _decimal(
        raw_bill.get("balance_change", raw_bill.get("balChg")),
        "strategy_allocation_funding_amount_invalid",
    )
    remaining = amount
    member_amounts: dict[str, str] = {}
    ordered = sorted(active)
    for index, member in enumerate(ordered):
        share = remaining if index == len(ordered) - 1 else amount * active[member] / gross
        remaining -= share
        member_amounts[member] = _text(share)
    if sum(Decimal(value) for value in member_amounts.values()) != amount:
        raise StrategyAllocationError("strategy_allocation_funding_not_conserved")
    result = json.loads(json.dumps(state))
    result["funding_allocations"][bill_id] = {
        "raw_bill_sha256": bill_digest,
        "raw_amount": _text(amount),
        "currency": str(raw_bill.get("currency") or raw_bill.get("ccy") or ""),
        "settled_at_ms": _text(bill_time_ms),
        "ownership_effective_at_ms": str(ownership["effective_at_ms"]),
        "ownership_fill_id": str(ownership.get("fill_id") or ""),
        "members": member_amounts,
    }
    return result


def validate_allocation_conservation(
    *, state: Mapping[str, Any], account_signed_contracts: Decimal
) -> dict[str, Any]:
    holdings = {
        str(member): _decimal(value, "strategy_allocation_member_contracts_invalid")
        for member, value in state.get("member_contracts", {}).items()
    }
    expected = _decimal(
        account_signed_contracts, "strategy_allocation_account_position_invalid"
    )
    blockers: list[str] = []
    if sum(holdings.values()) != expected:
        blockers.append("strategy_allocation_position_not_conserved")
    for row in state.get("fill_allocations", {}).values():
        member_rows = row.get("members", {}) if isinstance(row, Mapping) else {}
        if sum(Decimal(value["signed_contracts"]) for value in member_rows.values()) != Decimal(str(row.get("raw_signed_quantity"))):
            blockers.append("strategy_allocation_fill_quantity_not_conserved")
        if sum(Decimal(value["fee"]) for value in member_rows.values()) != Decimal(str(row.get("raw_fee"))):
            blockers.append("strategy_allocation_fill_fee_not_conserved")
    for row in state.get("funding_allocations", {}).values():
        members = row.get("members", {}) if isinstance(row, Mapping) else {}
        if sum(Decimal(value) for value in members.values()) != Decimal(str(row.get("raw_amount"))):
            blockers.append("strategy_allocation_funding_not_conserved")
    return {
        "reconciled": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "account_signed_contracts": _text(expected),
        "allocated_signed_contracts": _text(sum(holdings.values())),
    }


__all__ = [
    "STRATEGY_ALLOCATIONS_SCHEMA_VERSION",
    "StrategyAllocationError",
    "allocate_funding_bill",
    "allocate_raw_fill",
    "empty_strategy_allocation_state",
    "validate_allocation_conservation",
]
