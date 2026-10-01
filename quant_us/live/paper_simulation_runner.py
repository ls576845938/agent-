#!/usr/bin/env python3
"""Service layer for one US equity paper-simulation roll.

The service owns the broker-free paper use case and ledger materialization.
The CLI entrypoint only parses arguments. No private, order, or broker endpoint
is available from this module.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.live.paper_ledger_uow import (
    PaperLedgerCommitError,
    commit_paper_ledger_cycle,
    recover_incomplete_paper_ledger_transactions,
)
from quant_us.live.paper_simulation_roll import (
    DEFAULT_ACCOUNT_EQUITY,
    DEFAULT_SLIPPAGE_BPS,
    build_cash_entry,
    build_daily_report,
    build_fills,
    build_payload,
    build_position_entry,
    build_preflight_blockers,
    build_rebalance,
    build_reconciliation,
    build_snapshot,
    build_state,
    build_target_row,
    empty_rebalance,
    float_or,
    mapping,
)


DEFAULT_READINESS_REPORT = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json"
)
DEFAULT_FORWARD_LEDGER_ROOT = Path("data/forward_observation/us_etf_rotation_v1")
DEFAULT_LEDGER_ROOT = Path("data/paper_ledger/us_equity_etf_rotation_v1")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_roll_report.json")


def run_us_equity_paper_simulation_roll(
    *,
    repo_root: Path | None = None,
    readiness_report: Path = DEFAULT_READINESS_REPORT,
    forward_ledger_root: Path = DEFAULT_FORWARD_LEDGER_ROOT,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    output: Path = DEFAULT_OUTPUT,
    manual_start_approved: bool = False,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    readiness_path = _resolve(root, readiness_report)
    forward_root = _resolve(root, forward_ledger_root)
    paper_root = _resolve(root, ledger_root)
    output_path = _resolve(root, output)
    readiness = _read_json(readiness_path)
    blockers = build_preflight_blockers(
        readiness=readiness,
        readiness_path=readiness_path,
        forward_root=forward_root,
        paper_root=paper_root,
        root=root,
        manual_start_approved=manual_start_approved,
    )
    canonical_paper_root = (root / DEFAULT_LEDGER_ROOT).resolve()
    if paper_root.resolve() == canonical_paper_root:
        recovery = recover_incomplete_paper_ledger_transactions(paper_root)
        blockers.extend(
            f"us_equity_paper_simulation_ledger_recovery_failed:{item}"
            for item in recovery.blockers
        )

    if blockers:
        return _write_blocked_payload(
            generated=generated,
            root=root,
            output_path=output_path,
            readiness_path=readiness_path,
            forward_root=forward_root,
            paper_root=paper_root,
            readiness=readiness,
            manual_start_approved=manual_start_approved,
            blockers=blockers,
        )

    target_row = _latest_jsonl(forward_root / "target_positions.jsonl")
    if not target_row:
        return _write_blocked_payload(
            generated=generated,
            root=root,
            output_path=output_path,
            readiness_path=readiness_path,
            forward_root=forward_root,
            paper_root=paper_root,
            readiness=readiness,
            manual_start_approved=manual_start_approved,
            blockers=["us_equity_paper_simulation_forward_target_missing_or_unreadable"],
        )

    target_position = mapping(target_row.get("target_position"))
    timestamp = str(target_position.get("date") or target_row.get("timestamp") or "")
    state_path = paper_root / "validation_state.json"
    state = _read_json(state_path)
    if state.get("_read_error"):
        return _write_blocked_payload(
            generated=generated,
            root=root,
            output_path=output_path,
            readiness_path=readiness_path,
            forward_root=forward_root,
            paper_root=paper_root,
            readiness=readiness,
            manual_start_approved=manual_start_approved,
            blockers=["us_equity_paper_simulation_validation_state_unreadable"],
            target_position=target_position,
        )

    latest_snapshot = _latest_jsonl(paper_root / "portfolio_snapshots.jsonl")
    if state.get("last_processed_timestamp") == timestamp:
        if not latest_snapshot:
            return _write_blocked_payload(
                generated=generated,
                root=root,
                output_path=output_path,
                readiness_path=readiness_path,
                forward_root=forward_root,
                paper_root=paper_root,
                readiness=readiness,
                manual_start_approved=manual_start_approved,
                blockers=["us_equity_paper_simulation_processed_state_snapshot_missing_or_unreadable"],
                target_position=target_position,
            )
        payload = build_payload(
            generated_at=generated,
            status="PASS",
            cycle_status="SKIPPED_ALREADY_COMPLETED",
            root=root,
            output_path=output_path,
            readiness_path=readiness_path,
            forward_root=forward_root,
            paper_root=paper_root,
            readiness=readiness,
            manual_start_approved=manual_start_approved,
            blockers=[],
            target_position=target_position,
            rebalance=empty_rebalance(slippage_bps),
            fills=[],
            portfolio_snapshot=latest_snapshot,
            reconciliation={
                "status": "clean" if latest_snapshot.get("reconciliation_status") == "clean" else "unknown",
                "passed": latest_snapshot.get("reconciliation_status") == "clean",
            },
        )
        _write_json(output_path, payload)
        return payload

    paper_root.mkdir(parents=True, exist_ok=True)
    latest_position_entry = _latest_jsonl(paper_root / "positions.jsonl")
    latest_cash_entry = _latest_jsonl(paper_root / "cash_ledger.jsonl")
    state_position = mapping(state.get("current_position"))
    current_quantities = mapping(state.get("current_quantities"))
    if not current_quantities:
        current_quantities = mapping(state_position.get("quantities")) or mapping(state_position.get("shares"))
    if not current_quantities:
        current_quantities = {
            symbol: float_or(mapping(row).get("quantity"), 0.0)
            for symbol, row in mapping(latest_position_entry.get("positions")).items()
        }
    current_prices = mapping(target_position.get("prices"))
    marked_position_value = sum(
        float_or(quantity, 0.0) * float_or(current_prices.get(symbol), 0.0)
        for symbol, quantity in current_quantities.items()
    )
    if "current_cash" in state:
        prior_cash = float_or(state.get("current_cash"), 0.0)
    elif "ending_cash" in latest_cash_entry:
        prior_cash = float_or(latest_cash_entry.get("ending_cash"), 0.0)
    elif state:
        prior_cash = float_or(state.get("current_equity"), DEFAULT_ACCOUNT_EQUITY) - marked_position_value
    else:
        prior_cash = DEFAULT_ACCOUNT_EQUITY
    prior_equity = prior_cash + marked_position_value
    current_weights = {
        symbol: quantity * float_or(current_prices.get(symbol), 0.0) / prior_equity
        for symbol, raw_quantity in current_quantities.items()
        if prior_equity > 0 and abs(quantity := float_or(raw_quantity, 0.0)) > 1e-12
    }
    current_position = {
        "weights": current_weights,
        "quantities": current_quantities,
        "prices": current_prices,
        "marked_position_value": round(marked_position_value, 6),
        "cash": round(prior_cash, 6),
        "equity": round(prior_equity, 6),
    }
    rebalance = build_rebalance(
        current_position=current_position,
        target=target_position,
        prior_equity=prior_equity,
        slippage_bps=slippage_bps,
    )
    fills = build_fills(
        timestamp=timestamp,
        generated_at=generated,
        target=target_position,
        rebalance=rebalance,
        prior_equity=prior_equity,
    )
    target_quantities = mapping(rebalance.get("target_quantities"))
    trade_cash_flow = sum(
        -float_or(fill.get("notional"), 0.0)
        if str(fill.get("side", "")) == "buy"
        else float_or(fill.get("notional"), 0.0)
        for fill in fills
    )
    transaction_cost = sum(float_or(fill.get("commission"), 0.0) for fill in fills)
    financing_cost = float_or(rebalance.get("estimated_financing_daily"), 0.0)
    ending_cash = prior_cash + trade_cash_flow - transaction_cost - financing_cost
    position_value = sum(
        float_or(quantity, 0.0) * float_or(current_prices.get(symbol), 0.0)
        for symbol, quantity in target_quantities.items()
    )
    final_equity = ending_cash + position_value
    position_entry = build_position_entry(
        timestamp=timestamp,
        generated_at=generated,
        target=target_position,
        equity=final_equity,
        quantities=target_quantities,
    )
    cash_entry = build_cash_entry(
        timestamp=timestamp,
        generated_at=generated,
        prior_equity=prior_equity,
        final_equity=final_equity,
        target=target_position,
        rebalance=rebalance,
        prior_cash=prior_cash,
        ending_cash=ending_cash,
        trade_cash_flow=trade_cash_flow,
    )
    snapshot = build_snapshot(
        timestamp=timestamp,
        generated_at=generated,
        target=target_position,
        rebalance=rebalance,
        prior_equity=prior_equity,
        final_equity=final_equity,
        cash=ending_cash,
        position_value=position_value,
    )
    reconciliation = build_reconciliation(
        snapshot=snapshot,
        prior_equity=prior_equity,
        rebalance=rebalance,
    )
    if not reconciliation["passed"]:
        return _write_blocked_payload(
            generated=generated,
            root=root,
            output_path=output_path,
            readiness_path=readiness_path,
            forward_root=forward_root,
            paper_root=paper_root,
            readiness=readiness,
            manual_start_approved=manual_start_approved,
            blockers=["us_equity_paper_simulation_reconciliation_failed"],
            cycle_status="RECONCILIATION_FAILED",
            target_position=target_position,
            rebalance=rebalance,
            fills=fills,
            portfolio_snapshot=snapshot,
            reconciliation=reconciliation,
        )

    target_row_out = build_target_row(
        timestamp=timestamp,
        generated_at=generated,
        target_position=target_position,
        current_position=current_position,
        rebalance=rebalance,
    )
    state_out = build_state(
        generated_at=generated,
        target_position=target_position,
        previous_state=state,
        final_equity=final_equity,
        fill_count_delta=len(fills),
        timestamp=timestamp,
        ledger_root=paper_root,
        root=root,
        current_cash=ending_cash,
        current_quantities=target_quantities,
        current_position_entry=position_entry,
    )
    daily_report = build_daily_report(
        generated_at=generated,
        timestamp=timestamp,
        root=root,
        ledger_root=paper_root,
        target_position=target_position,
        rebalance=rebalance,
        fills=fills,
        position_entry=position_entry,
        cash_entry=cash_entry,
        portfolio_snapshot=snapshot,
        reconciliation=reconciliation,
    )
    try:
        commit_paper_ledger_cycle(
            ledger_root=paper_root,
            timestamp=timestamp,
            generated_at=generated,
            jsonl_rows={
                "target_positions.jsonl": [target_row_out],
                "fills.jsonl": fills,
                "positions.jsonl": [position_entry],
                "cash_ledger.jsonl": [cash_entry],
                "portfolio_snapshots.jsonl": [snapshot],
            },
            json_documents={
                "validation_state.json": state_out,
                f"daily_reports/{timestamp}.json": daily_report,
            },
        )
    except PaperLedgerCommitError as exc:
        rollback_status = "true" if exc.rollback_succeeded else "false"
        return _write_blocked_payload(
            generated=generated,
            root=root,
            output_path=output_path,
            readiness_path=readiness_path,
            forward_root=forward_root,
            paper_root=paper_root,
            readiness=readiness,
            manual_start_approved=manual_start_approved,
            blockers=[
                f"us_equity_paper_simulation_ledger_commit_failed:rollback_succeeded={rollback_status}"
            ],
            target_position=target_position,
            rebalance=rebalance,
            fills=fills,
            portfolio_snapshot=snapshot,
            reconciliation=reconciliation,
        )
    payload = build_payload(
        generated_at=generated,
        status="PASS",
        cycle_status="COMPLETED",
        root=root,
        output_path=output_path,
        readiness_path=readiness_path,
        forward_root=forward_root,
        paper_root=paper_root,
        readiness=readiness,
        manual_start_approved=manual_start_approved,
        blockers=[],
        target_position=target_position,
        rebalance=rebalance,
        fills=fills,
        portfolio_snapshot=snapshot,
        reconciliation=reconciliation,
        validation_state_path=state_path,
    )
    _write_json(output_path, payload)
    return payload


def _write_blocked_payload(
    *,
    generated: str,
    root: Path,
    output_path: Path,
    readiness_path: Path,
    forward_root: Path,
    paper_root: Path,
    readiness: Mapping[str, Any],
    manual_start_approved: bool,
    blockers: list[str],
    cycle_status: str = "NOT_RUN",
    target_position: Mapping[str, Any] | None = None,
    rebalance: Mapping[str, Any] | None = None,
    fills: list[Mapping[str, Any]] | None = None,
    portfolio_snapshot: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_payload(
        generated_at=generated,
        status="BLOCKED",
        cycle_status=cycle_status,
        root=root,
        output_path=output_path,
        readiness_path=readiness_path,
        forward_root=forward_root,
        paper_root=paper_root,
        readiness=readiness,
        manual_start_approved=manual_start_approved,
        blockers=blockers,
        target_position=target_position,
        rebalance=rebalance,
        fills=fills,
        portfolio_snapshot=portfolio_snapshot,
        reconciliation=reconciliation,
    )
    _write_json(output_path, payload)
    return payload


def _latest_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    latest = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            latest = line
    if not latest:
        return {}
    try:
        payload = json.loads(latest)
    except Exception:  # noqa: BLE001
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_read_error": type(exc).__name__}
    return dict(payload) if isinstance(payload, Mapping) else {"_read_error": "non_object_json"}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
