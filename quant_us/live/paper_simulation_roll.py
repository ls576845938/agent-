"""Pure rules for the US equity paper-simulation roll.

The module is intentionally broker-free. It transforms an approved forward
target into simulated ledger rows and report payload fragments; the live
service layer owns file I/O and transaction boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_paper_simulation_roll_v1"
STATE_SCHEMA_VERSION = "us_equity_paper_simulation_state_v1"
DAILY_REPORT_SCHEMA_VERSION = "us_equity_paper_simulation_daily_report_v1"
STRATEGY_ID = "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"
EXPECTED_VARIANT = "min_adv_10m_to_shv"
DEFAULT_ACCOUNT_EQUITY = 10_000.0
DEFAULT_SLIPPAGE_BPS = 10.0
CANONICAL_LEDGER_ROOT = "data/paper_ledger/us_equity_etf_rotation_v1"
LEDGER_FILE_KEYS = (
    "target_positions",
    "fills",
    "positions",
    "cash_ledger",
    "portfolio_snapshots",
    "validation_state",
    "daily_reports",
)


def build_preflight_blockers(
    *,
    readiness: Mapping[str, Any],
    readiness_path: Path,
    forward_root: Path,
    paper_root: Path,
    root: Path,
    manual_start_approved: bool,
) -> list[str]:
    blockers: list[str] = []
    if not readiness_path.exists():
        blockers.append("us_equity_paper_simulation_readiness_report_missing")
    if str(readiness.get("status", "")) != "paper_simulation_ready_for_manual_start":
        blockers.append("us_equity_paper_simulation_readiness_not_ready")
    if str(readiness.get("decision", "")) != "manual_start_required":
        blockers.append("us_equity_paper_simulation_manual_start_decision_missing")
    if manual_start_approved is not True:
        blockers.append("us_equity_paper_simulation_manual_start_not_approved")
    if relpath(paper_root, root) != CANONICAL_LEDGER_ROOT:
        blockers.append("us_equity_paper_simulation_ledger_root_not_canonical")
    if paper_root == forward_root or "forward_observation" in paper_root.as_posix().replace("\\", "/"):
        blockers.append("us_equity_paper_simulation_reuses_forward_ledger_root")
    if nested(readiness, "required_runner_contract.independent_ledger_root", "") != CANONICAL_LEDGER_ROOT:
        blockers.append("us_equity_paper_simulation_required_runner_contract_mismatch")
    if nested(readiness, "required_runner_contract.must_not_reuse_forward_observation_ledger", False) is not True:
        blockers.append("us_equity_paper_simulation_contract_allows_forward_ledger_reuse")
    unsafe = unsafe_flags({"readiness": readiness})
    blockers.extend([f"us_equity_paper_simulation_unsafe_flag:{item}" for item in unsafe])
    if not (forward_root / "target_positions.jsonl").exists():
        blockers.append("us_equity_paper_simulation_forward_target_ledger_missing")
    return dedupe(blockers)


def build_payload(
    *,
    generated_at: str,
    status: str,
    cycle_status: str,
    root: Path,
    output_path: Path,
    readiness_path: Path,
    forward_root: Path,
    paper_root: Path,
    readiness: Mapping[str, Any],
    manual_start_approved: bool,
    blockers: list[str],
    target_position: Mapping[str, Any] | None = None,
    rebalance: Mapping[str, Any] | None = None,
    fills: list[Mapping[str, Any]] | None = None,
    portfolio_snapshot: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
    validation_state_path: Path | None = None,
) -> dict[str, Any]:
    timestamp = str((target_position or {}).get("date") or (portfolio_snapshot or {}).get("timestamp") or "not_run")
    outputs = paper_roll_outputs(root=root, output_path=output_path, paper_root=paper_root, timestamp=timestamp)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "cycle_status": cycle_status,
        "asset": "us_equity",
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "manual_start_approved": manual_start_approved,
        "readiness_status": str(readiness.get("status", "")),
        "readiness_decision": str(readiness.get("decision", "")),
        "ledger_root": relpath(paper_root, root),
        "forward_ledger_root": relpath(forward_root, root),
        "target_position": dict(target_position or {}),
        "rebalance": dict(rebalance or {}),
        "fills": list(fills or []),
        "portfolio_snapshot": dict(portfolio_snapshot or {}),
        "reconciliation": dict(reconciliation or {"status": "not_run", "passed": False}),
        "validation_state_path": relpath(validation_state_path, root) if validation_state_path else "",
        "ledger_materialization": build_ledger_materialization(
            status=status,
            cycle_status=cycle_status,
            root=root,
            paper_root=paper_root,
            forward_root=forward_root,
            fills=list(fills or []),
            blockers=blockers,
            reconciliation=reconciliation or {"status": "not_run", "passed": False},
            outputs=outputs,
        ),
        "blockers": blockers,
        "guardrails": paper_roll_guardrails(),
        "source_reports": {
            "paper_readiness": relpath(readiness_path, root),
            "forward_target_ledger": relpath(forward_root / "target_positions.jsonl", root),
        },
        "outputs": outputs,
    }


def paper_roll_outputs(*, root: Path, output_path: Path, paper_root: Path, timestamp: str = "not_run") -> dict[str, str]:
    safe_timestamp = timestamp or "not_run"
    return {
        "json": relpath(output_path, root),
        "target_positions": relpath(paper_root / "target_positions.jsonl", root),
        "fills": relpath(paper_root / "fills.jsonl", root),
        "positions": relpath(paper_root / "positions.jsonl", root),
        "cash_ledger": relpath(paper_root / "cash_ledger.jsonl", root),
        "portfolio_snapshots": relpath(paper_root / "portfolio_snapshots.jsonl", root),
        "validation_state": relpath(paper_root / "validation_state.json", root),
        "daily_reports": relpath(paper_root / "daily_reports", root),
        "daily_report": relpath(paper_root / "daily_reports" / f"{safe_timestamp}.json", root),
    }


def build_ledger_materialization(
    *,
    status: str,
    cycle_status: str,
    root: Path,
    paper_root: Path,
    forward_root: Path,
    fills: list[Mapping[str, Any]],
    blockers: list[str],
    reconciliation: Mapping[str, Any],
    outputs: Mapping[str, str],
) -> dict[str, Any]:
    paper_rel = relpath(paper_root, root)
    forward_rel = relpath(forward_root, root)
    independent = paper_rel == CANONICAL_LEDGER_ROOT and paper_rel != forward_rel and "forward_observation" not in paper_rel
    writes_performed = status == "PASS" and cycle_status == "COMPLETED"
    skipped = status == "PASS" and cycle_status == "SKIPPED_ALREADY_COMPLETED"
    blocked_before_write = status == "BLOCKED" and cycle_status in {"NOT_RUN", "RECONCILIATION_FAILED"}
    row_counts = {
        "target_positions": 1 if writes_performed else 0,
        "fills": len(fills) if writes_performed else 0,
        "positions": 1 if writes_performed else 0,
        "cash_ledger": 1 if writes_performed else 0,
        "portfolio_snapshots": 1 if writes_performed else 0,
        "validation_state": 1 if writes_performed else 0,
        "daily_reports": 1 if writes_performed else 0,
    }
    return {
        "status": _ledger_materialization_status(status=status, cycle_status=cycle_status),
        "writes_performed": writes_performed,
        "skipped_already_completed": skipped,
        "blocked_before_ledger_write": blocked_before_write,
        "paper_ledger_is_independent": independent,
        "canonical_ledger_root_verified": paper_rel == CANONICAL_LEDGER_ROOT,
        "uses_forward_observation_as_source_only": paper_rel != forward_rel and "forward_observation" in forward_rel,
        "must_not_reuse_forward_observation_ledger": True,
        "paper_ledger_root": paper_rel,
        "forward_ledger_root": forward_rel,
        "expected_ledger_files": list(LEDGER_FILE_KEYS),
        "output_paths": {key: str(outputs.get(key, "")) for key in (*LEDGER_FILE_KEYS, "daily_report")},
        "rows_written_this_cycle": row_counts,
        "simulated_fills_only": all(fill.get("simulated_only") is True for fill in fills),
        "broker_order_ids_absent": all(not str(fill.get("broker_order_id", "")) for fill in fills),
        "exchange_order_ids_absent": all(not str(fill.get("exchange_order_id", "")) for fill in fills),
        "reconciliation_passed_before_write": reconciliation.get("passed") is True,
        "blockers": list(blockers),
        "operator_next_action": _ledger_materialization_next_action(
            status=status,
            cycle_status=cycle_status,
            blockers=blockers,
            reconciliation=reconciliation,
        ),
    }


def _ledger_materialization_status(*, status: str, cycle_status: str) -> str:
    if status == "PASS" and cycle_status == "COMPLETED":
        return "ledger_rows_written"
    if status == "PASS" and cycle_status == "SKIPPED_ALREADY_COMPLETED":
        return "already_processed_no_new_rows"
    if cycle_status == "RECONCILIATION_FAILED":
        return "blocked_reconciliation_failed_no_rows_written"
    return "blocked_before_ledger_write"


def _ledger_materialization_next_action(
    *,
    status: str,
    cycle_status: str,
    blockers: list[str],
    reconciliation: Mapping[str, Any],
) -> str:
    if status == "PASS" and cycle_status == "COMPLETED":
        return "run paper simulation evaluation to verify independent ledger, fills, positions, cash, and snapshot reconciliation"
    if status == "PASS" and cycle_status == "SKIPPED_ALREADY_COMPLETED":
        return "no new ledger rows written; wait for the next target timestamp"
    if cycle_status == "RECONCILIATION_FAILED" or reconciliation.get("passed") is False and reconciliation.get("status") == "mismatch":
        return "inspect reconciliation mismatch before writing any paper ledger rows"
    if any("readiness" in item for item in blockers):
        return "resolve paper simulation readiness blockers before starting the independent ledger"
    if "us_equity_paper_simulation_manual_start_not_approved" in blockers:
        return "record explicit manual-start approval only after readiness is ready"
    return "keep paper simulation blocked and inspect blockers before writing ledger rows"


def empty_rebalance(slippage_bps: float) -> dict[str, Any]:
    return {
        "deltas": {},
        "quantity_deltas": {},
        "target_quantities": {},
        "turnover": 0.0,
        "estimated_trade_notional": 0.0,
        "slippage_bps": float(slippage_bps),
        "estimated_slippage": 0.0,
        "estimated_financing_daily": 0.0,
        "simulated_only": True,
    }


def build_rebalance(
    *,
    current_position: Mapping[str, Any],
    target: Mapping[str, Any],
    prior_equity: float,
    slippage_bps: float,
) -> dict[str, Any]:
    prices = mapping(target.get("prices"))
    current_quantities = mapping(current_position.get("quantities"))
    current_weights = mapping(current_position.get("weights"))
    target_weights = mapping(target.get("weights"))
    symbols = sorted(set(current_weights) | set(current_quantities) | set(target_weights))
    target_quantities: dict[str, float] = {}
    quantity_deltas: dict[str, float] = {}
    deltas: dict[str, float] = {}
    trade_notional = 0.0
    for symbol in symbols:
        price = float_or(prices.get(symbol), 0.0)
        target_weight = float_or(target_weights.get(symbol), 0.0)
        current_quantity = float_or(current_quantities.get(symbol), 0.0)
        if current_quantities and prior_equity > 0 and price > 0:
            current_weight = current_quantity * price / prior_equity
        else:
            current_weight = float_or(current_weights.get(symbol), 0.0)
            if price > 0 and prior_equity > 0:
                current_quantity = current_weight * prior_equity / price
        target_quantity = target_weight * prior_equity / price if price > 0 else 0.0
        quantity_delta = target_quantity - current_quantity
        delta_weight = quantity_delta * price / prior_equity if prior_equity > 0 else 0.0
        target_quantities[symbol] = round(target_quantity, 10)
        quantity_deltas[symbol] = round(quantity_delta, 10)
        deltas[symbol] = round(delta_weight, 10)
        trade_notional += abs(quantity_delta * price)
    turnover = trade_notional / prior_equity if prior_equity > 0 else 0.0
    return {
        "deltas": deltas,
        "quantity_deltas": quantity_deltas,
        "target_quantities": target_quantities,
        "turnover": round(turnover, 10),
        "estimated_trade_notional": round(trade_notional, 6),
        "slippage_bps": float(slippage_bps),
        "estimated_slippage": round(trade_notional * float(slippage_bps) / 10_000.0, 6),
        "estimated_financing_daily": 0.0,
        "simulated_only": True,
    }


def build_fills(
    *,
    timestamp: str,
    generated_at: str,
    target: Mapping[str, Any],
    rebalance: Mapping[str, Any],
    prior_equity: float,
) -> list[dict[str, Any]]:
    prices = mapping(target.get("prices"))
    deltas = mapping(rebalance.get("deltas"))
    quantity_deltas = mapping(rebalance.get("quantity_deltas"))
    estimated_slippage = float_or(rebalance.get("estimated_slippage"), 0.0)
    estimated_trade_notional = float_or(rebalance.get("estimated_trade_notional"), 0.0)
    fills: list[dict[str, Any]] = []
    for symbol in sorted(set(deltas) | set(quantity_deltas)):
        raw_delta = deltas.get(symbol, 0.0)
        delta = float_or(raw_delta, 0.0)
        price = float_or(prices.get(symbol), 0.0)
        if price <= 0:
            continue
        quantity_delta = float_or(quantity_deltas.get(symbol), delta * prior_equity / price)
        if abs(quantity_delta) <= 1e-12:
            continue
        notional = abs(quantity_delta * price)
        commission = estimated_slippage * notional / estimated_trade_notional if estimated_trade_notional > 0 else 0.0
        order_id = f"paper-{timestamp}-{symbol}"
        fills.append(
            {
                "timestamp": timestamp,
                "filled_at": f"{timestamp}T00:00:00Z" if "T" not in timestamp else timestamp,
                "strategy_id": STRATEGY_ID,
                "candidate_variant": EXPECTED_VARIANT,
                "order_id": order_id,
                "fill_id": f"{order_id}-fill",
                "symbol": symbol,
                "side": "buy" if quantity_delta > 0 else "sell",
                "delta_weight": round(delta, 10),
                "quantity": round(abs(quantity_delta), 10),
                "price": round(price, 6),
                "notional": round(notional, 6),
                "commission": round(commission, 6),
                "broker": "paper_simulation",
                "broker_order_id": "",
                "exchange_order_id": "",
                "simulated_only": True,
                "generated_at": generated_at,
            }
        )
    return fills


def build_position_entry(
    *,
    timestamp: str,
    generated_at: str,
    target: Mapping[str, Any],
    equity: float,
    quantities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    weights = mapping(target.get("weights"))
    prices = mapping(target.get("prices"))
    shares = mapping(quantities) or mapping(target.get("shares"))
    positions: dict[str, dict[str, float]] = {}
    for symbol in sorted(weights):
        weight = float_or(weights.get(symbol), 0.0)
        price = float_or(prices.get(symbol), 0.0)
        quantity = float_or(shares.get(symbol), weight * equity / price if price > 0 else 0.0)
        notional = quantity * price
        positions[symbol] = {
            "weight": round(weight, 10),
            "quantity": round(quantity, 10),
            "price": round(price, 6),
            "notional": round(notional, 6),
        }
    return {
        "timestamp": timestamp,
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "source": "paper_simulation_target_position",
        "positions": positions,
        "gross_exposure": round(float_or(target.get("gross_exposure"), 0.0), 10),
        "net_exposure": round(float_or(target.get("net_exposure"), 0.0), 10),
        "position_count": len(positions),
        "simulated_only": True,
        "generated_at": generated_at,
    }


def build_cash_entry(
    *,
    timestamp: str,
    generated_at: str,
    prior_equity: float,
    final_equity: float,
    target: Mapping[str, Any],
    rebalance: Mapping[str, Any],
    prior_cash: float | None = None,
    ending_cash: float | None = None,
    trade_cash_flow: float = 0.0,
) -> dict[str, Any]:
    gross_exposure = float_or(target.get("gross_exposure"), 0.0)
    unallocated_cash_weight = max(0.0, 1.0 - gross_exposure)
    return {
        "timestamp": timestamp,
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "source": "paper_simulation_cost_reconciliation",
        "prior_equity": round(prior_equity, 6),
        "prior_cash": round(prior_cash if prior_cash is not None else prior_equity, 6),
        "trade_cash_flow": round(trade_cash_flow, 6),
        "estimated_slippage": round(float_or(rebalance.get("estimated_slippage"), 0.0), 6),
        "estimated_financing_daily": round(float_or(rebalance.get("estimated_financing_daily"), 0.0), 6),
        "final_equity": round(final_equity, 6),
        "ending_cash": round(ending_cash if ending_cash is not None else final_equity * unallocated_cash_weight, 6),
        "unallocated_cash_weight": round(unallocated_cash_weight, 10),
        "unallocated_cash_notional": round(final_equity * unallocated_cash_weight, 6),
        "cash_reconciliation_status": "clean",
        "simulated_only": True,
        "generated_at": generated_at,
    }


def build_snapshot(
    *,
    timestamp: str,
    generated_at: str,
    target: Mapping[str, Any],
    rebalance: Mapping[str, Any],
    prior_equity: float,
    final_equity: float,
    cash: float | None = None,
    position_value: float | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "prior_equity": round(prior_equity, 6),
        "equity": round(final_equity, 6),
        "cash": round(cash if cash is not None else final_equity * max(0.0, 1.0 - float_or(target.get("gross_exposure"), 0.0)), 6),
        "position_value": round(position_value if position_value is not None else final_equity * float_or(target.get("gross_exposure"), 0.0), 6),
        "gross_exposure": round(float_or(target.get("gross_exposure"), 0.0), 10),
        "net_exposure": round(float_or(target.get("net_exposure"), 0.0), 10),
        "target_count": int(target.get("target_count", 0) or 0),
        "turnover": round(float_or(rebalance.get("turnover"), 0.0), 10),
        "estimated_trade_notional": round(float_or(rebalance.get("estimated_trade_notional"), 0.0), 6),
        "estimated_slippage": round(float_or(rebalance.get("estimated_slippage"), 0.0), 6),
        "estimated_financing_daily": round(float_or(rebalance.get("estimated_financing_daily"), 0.0), 6),
        "reconciliation_status": "clean",
        "generated_at": generated_at,
    }


def build_reconciliation(
    *,
    snapshot: Mapping[str, Any],
    prior_equity: float,
    rebalance: Mapping[str, Any],
) -> dict[str, Any]:
    cost_expected = prior_equity - float_or(rebalance.get("estimated_slippage"), 0.0) - float_or(
        rebalance.get("estimated_financing_daily"),
        0.0,
    )
    actual = float_or(snapshot.get("equity"), 0.0)
    ledger_expected = float_or(snapshot.get("cash"), 0.0) + float_or(snapshot.get("position_value"), 0.0)
    expected = ledger_expected if "cash" in snapshot and "position_value" in snapshot else cost_expected
    diff = actual - expected
    cost_diff = actual - cost_expected
    return {
        "status": "clean" if abs(diff) <= 0.01 and abs(cost_diff) <= 0.01 else "mismatch",
        "passed": abs(diff) <= 0.01 and abs(cost_diff) <= 0.01,
        "expected_equity": round(expected, 6),
        "actual_equity": round(actual, 6),
        "diff": round(diff, 8),
    }


def build_daily_report(
    *,
    generated_at: str,
    timestamp: str,
    root: Path,
    ledger_root: Path,
    target_position: Mapping[str, Any],
    rebalance: Mapping[str, Any],
    fills: list[Mapping[str, Any]],
    position_entry: Mapping[str, Any],
    cash_entry: Mapping[str, Any],
    portfolio_snapshot: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": DAILY_REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "timestamp": timestamp,
        "asset": "us_equity",
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "ledger_root": relpath(ledger_root, root),
        "target_position": dict(target_position),
        "rebalance": dict(rebalance),
        "fills": [dict(fill) for fill in fills],
        "position_entry": dict(position_entry),
        "cash_entry": dict(cash_entry),
        "portfolio_snapshot": dict(portfolio_snapshot),
        "reconciliation": dict(reconciliation),
        "simulated_only": True,
        "guardrails": paper_roll_guardrails(),
    }


def build_target_row(
    *,
    timestamp: str,
    generated_at: str,
    target_position: Mapping[str, Any],
    current_position: Mapping[str, Any],
    rebalance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "source": "forward_observation_latest_target",
        "target_position": dict(target_position),
        "current_position": dict(current_position),
        "rebalance": dict(rebalance),
        "reason": "manual_start_approved_paper_simulation_from_forward_target",
        "simulated_only": True,
        "generated_at": generated_at,
    }


def build_state(
    *,
    generated_at: str,
    target_position: Mapping[str, Any],
    previous_state: Mapping[str, Any],
    final_equity: float,
    fill_count_delta: int,
    timestamp: str,
    ledger_root: Path,
    root: Path,
    current_cash: float | None = None,
    current_quantities: Mapping[str, Any] | None = None,
    current_position_entry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_position = dict(target_position)
    if current_position_entry is not None:
        position_rows = mapping(current_position_entry.get("positions"))
        normalized_position = {
            "date": timestamp,
            "weights": {
                symbol: float_or(mapping(row).get("weight"), 0.0)
                for symbol, row in position_rows.items()
            },
            "prices": {
                symbol: float_or(mapping(row).get("price"), 0.0)
                for symbol, row in position_rows.items()
            },
            "quantities": {
                symbol: float_or(mapping(row).get("quantity"), 0.0)
                for symbol, row in position_rows.items()
            },
        }
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": generated_at,
        "strategy_id": STRATEGY_ID,
        "candidate_variant": EXPECTED_VARIANT,
        "current_equity": round(final_equity, 6),
        "current_cash": round(current_cash if current_cash is not None else final_equity, 6),
        "current_quantities": {
            str(symbol): round(float_or(quantity), 10)
            for symbol, quantity in mapping(current_quantities).items()
        },
        "current_position": normalized_position,
        "days_completed": int(previous_state.get("days_completed", 0) or 0) + 1,
        "target_position_count": int(previous_state.get("target_position_count", 0) or 0) + 1,
        "fill_count": int(previous_state.get("fill_count", 0) or 0) + fill_count_delta,
        "position_ledger_count": int(previous_state.get("position_ledger_count", 0) or 0) + 1,
        "cash_ledger_count": int(previous_state.get("cash_ledger_count", 0) or 0) + 1,
        "last_processed_timestamp": timestamp,
        "ledger_root": relpath(ledger_root, root),
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
    }


def paper_roll_guardrails() -> dict[str, bool]:
    return {
        "paper_simulation_runner_only": True,
        "simulated_only": True,
        "manual_start_required": True,
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "broker_calls_used": False,
    }


def unsafe_flags(payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    unsafe = []
    keys = {
        "paper_or_live_unlock_allowed",
        "paper_simulation_allowed",
        "live_order_allowed",
        "private_endpoint_allowed",
        "private_endpoint_used",
        "order_endpoint_allowed",
        "order_endpoint_used",
        "real_order_submitted",
        "broker_calls_used",
    }
    for root_name, payload in payloads.items():
        for path, value in walk(payload):
            if path.split(".")[-1] in keys and value is True:
                unsafe.append(f"{root_name}.{path}=true")
    return unsafe


def walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(walk(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(walk(child, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def nested(value: Any, dotted: str, default: Any = None) -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def float_or(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def relpath(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
