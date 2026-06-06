#!/usr/bin/env python3
"""Guarded BTC USD-M paper-validation runner.

Contract marker: btc_paper_validation_runtime_v1

This launcher is fail-closed. It starts no BTC paper-validation cycle unless
the BTC paper-validation preflight passes. The execution path uses a local
simulated paper broker through the canonical crypto event-driven runner; no
live broker or private/order endpoint is contacted.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.backtest.crypto_event import run_crypto_event_backtest
from quant_us.backtest.ledger_pnl import build_ledger_reconciliation_artifact
from quant_us.execution.ledger import JsonlLedgerStore
from scripts.check_btc_paper_validation_readiness import (
    DEFAULT_CONFIG,
    DEFAULT_COST_MODEL,
    DEFAULT_DATA_ROOT,
    DEFAULT_INTERVAL,
    DEFAULT_LEDGER_ROOT,
    DEFAULT_READINESS_REPORT,
    DEFAULT_START_REPORT,
    MARKET_TYPE,
    SYMBOL,
    check_btc_paper_validation_readiness,
)


SCHEMA_VERSION = "btc_paper_validation_run_v1"
ATTEMPT_SCHEMA_VERSION = "btc_paper_validation_start_attempt_v1"
RUNTIME_SYMBOL = "BTCUSDT"
RUNTIME_MARKET_TYPE = "usds_m_perpetual"
DEFAULT_CAPITAL = 25_000.0
DEFAULT_DAYS_REQUIRED = 30
DEFAULT_CYCLE_HOURS = 24
LEDGER_START_LOCK_NAME = "btc_paper_validation_start.lock.json"


@dataclass
class LedgerStartLock:
    path: Path
    claim_id: str
    fd: int
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            payload = _read_json_from_fd(self.fd)
            if str(payload.get("claim_id", "")) == self.claim_id:
                payload["status"] = "released"
                payload["released_at"] = _utc_z_now()
                _write_json_to_fd(self.fd, payload)
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.released = True

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


def run_btc_paper_validation(
    *,
    repo_root: Path | None = None,
    symbols: list[str] | None = None,
    market_type: str = MARKET_TYPE,
    interval: str = DEFAULT_INTERVAL,
    ledger_root: Path | None = None,
    data_root: Path | None = None,
    readiness_report: Path | None = None,
    start_report: Path | None = None,
    config_path: Path | None = None,
    strategy_id: str = "",
    strategy_params: Mapping[str, Any] | None = None,
    capital: float = DEFAULT_CAPITAL,
    commission_rate: float | None = None,
    slippage_bps: float | None = None,
    days_required: int = DEFAULT_DAYS_REQUIRED,
    cycle_hours: int = DEFAULT_CYCLE_HOURS,
    start: datetime | None = None,
    end: datetime | None = None,
    resume: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    ledger = _resolve(root, ledger_root or DEFAULT_LEDGER_ROOT)
    data = _resolve(root, data_root or DEFAULT_DATA_ROOT)
    readiness_path = _resolve(root, readiness_report or DEFAULT_READINESS_REPORT)
    start_path = _resolve(root, start_report or DEFAULT_START_REPORT)
    config_abs = _resolve(root, config_path or DEFAULT_CONFIG)
    generated = generated_at or _utc_z_now()

    preflight = check_btc_paper_validation_readiness(
        repo_root=root,
        symbols=symbols or [SYMBOL],
        market_type=market_type,
        interval=interval,
        ledger_root=ledger,
        data_root=data,
        readiness_report=readiness_path,
        start_report=start_path,
        config_path=config_abs,
        require_start_report_ready=True,
        generated_at=generated,
    )
    if preflight["status"] != "PASS":
        reason = (
            "btc_paper_validation_reconciliation_not_clean"
            if "btc_paper_validation_ledger_reconciliation_blocked" in preflight.get("blocking_reasons", [])
            else "btc_paper_validation_preflight_blocked"
        )
        payload = _attempt_payload(
            generated_at=generated,
            status="BLOCKED",
            ledger_root=ledger,
            preflight=preflight,
            reason=reason,
        )
        _write_attempt_report(ledger, payload)
        return payload

    start_lock = _claim_ledger_start_lock(
        ledger=ledger,
        generated_at=generated,
    )
    if start_lock is None:
        payload = _attempt_payload(
            generated_at=generated,
            status="BLOCKED",
            ledger_root=ledger,
            preflight={
                "status": "BLOCKED",
                "blocking_reasons": ["btc_paper_validation_ledger_root_start_lock_held"],
            },
            reason="btc_paper_validation_ledger_root_start_lock_held",
        )
        _write_attempt_report(ledger, payload)
        return payload

    def _blocked_after_start_lock(reason: str) -> dict[str, Any]:
        payload = _attempt_payload(
            generated_at=generated,
            status="BLOCKED",
            ledger_root=ledger,
            preflight=preflight,
            reason=reason,
        )
        try:
            _write_attempt_report(ledger, payload)
        finally:
            _clear_ledger_start_lock(start_lock)
        return payload

    def _call_after_start_lock(function: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except Exception:
            _clear_ledger_start_lock(start_lock)
            raise

    if _in_progress_cycle_marker_paths(ledger) or (
        resume and _ledger_has_any_runtime_records(ledger) and not _ledger_has_resumable_session(ledger)
    ):
        return _blocked_after_start_lock("btc_paper_validation_incomplete_cycle_recovery_required")

    if _ledger_has_runtime_records(ledger) and not resume:
        return _blocked_after_start_lock("btc_paper_validation_ledger_not_empty_without_resume")

    clean_start = _ledger_is_clean_start(ledger)
    resumable_session = _ledger_has_resumable_session(ledger)
    if resume and not resumable_session:
        return _blocked_after_start_lock("btc_paper_validation_resume_without_existing_state")

    if not resume and not clean_start:
        return _blocked_after_start_lock("btc_paper_validation_existing_session_requires_resume")

    cost_binding = _call_after_start_lock(
        _paper_cost_model_binding,
        preflight=preflight,
        root=root,
        requested_commission_rate=commission_rate,
        requested_slippage_bps=slippage_bps,
    )
    if not cost_binding["ok"]:
        return _blocked_after_start_lock(str(cost_binding["reason"]))
    resolved_commission_rate = float(cost_binding["commission_rate"])
    resolved_slippage_bps = float(cost_binding["slippage_bps"])
    cost_model_report = str(cost_binding["cost_model_report"])

    bundle_dir = Path(str(preflight["inputs"]["bundle_dir"]))
    if not bundle_dir.is_absolute():
        bundle_dir = root / bundle_dir
    frame = _call_after_start_lock(_load_bundle_frame, bundle_dir, interval=interval)
    window_start, window_end = _call_after_start_lock(
        _resolve_cycle_window,
        frame,
        start=start,
        end=end,
        cycle_hours=cycle_hours,
    )
    frame = _call_after_start_lock(
        lambda: frame[(frame.index >= pd.Timestamp(window_start)) & (frame.index <= pd.Timestamp(window_end))]
    )
    if frame.empty:
        return _blocked_after_start_lock("btc_paper_validation_cycle_window_empty")

    review = _mapping(preflight.get("approved_paper_review"))
    resolved_strategy = strategy_id.strip() or str(review.get("strategy_manifest_id", "")).strip()
    if not resolved_strategy:
        return _blocked_after_start_lock("btc_paper_validation_strategy_id_missing")

    strategy_binding = _call_after_start_lock(
        _paper_strategy_binding,
        review=review,
        requested_strategy_id=strategy_id,
        strategy_params=strategy_params or {},
    )
    if not strategy_binding["ok"]:
        return _blocked_after_start_lock(str(strategy_binding["reason"]))

    run_id = (
        f"btc_paper_{window_start.strftime('%Y%m%dT%H%M%SZ')}_"
        f"{window_end.strftime('%Y%m%dT%H%M%SZ')}_{resolved_strategy}"
    )
    cycle_key = _validation_cycle_key(
        preflight=preflight,
        window_start=window_start,
        window_end=window_end,
    )
    if _validation_cycle_already_completed(ledger=ledger, run_id=run_id, cycle_key=cycle_key):
        return _blocked_after_start_lock("btc_paper_validation_cycle_already_completed")
    if _validation_cycle_recovery_required(ledger=ledger, run_id=run_id, cycle_key=cycle_key):
        return _blocked_after_start_lock("btc_paper_validation_concurrent_start_claimed")
    cycle_claimed = _call_after_start_lock(
        _claim_in_progress_cycle_marker,
        ledger=ledger,
        generated_at=generated,
        run_id=run_id,
        cycle_key=cycle_key,
        window_start=window_start,
        window_end=window_end,
        preflight=preflight,
    )
    if not cycle_claimed:
        return _blocked_after_start_lock("btc_paper_validation_incomplete_cycle_recovery_required")
    if _validation_cycle_already_completed(ledger=ledger, run_id=run_id, cycle_key=cycle_key):
        _clear_in_progress_cycle_marker(ledger=ledger, run_id=run_id)
        return _blocked_after_start_lock("btc_paper_validation_cycle_already_completed")
    if _validation_cycle_recovery_required(ledger=ledger, run_id=run_id, cycle_key=cycle_key, ignore_run_id=run_id):
        _clear_in_progress_cycle_marker(ledger=ledger, run_id=run_id)
        return _blocked_after_start_lock("btc_paper_validation_incomplete_cycle_recovery_required")
    data_version = _call_after_start_lock(_data_version, preflight, window_start=window_start, window_end=window_end)
    strategy_version = f"{resolved_strategy}:paper_validation:{review.get('paper_review_id', '')}"
    try:
        result = run_crypto_event_backtest(
            source="binance_usdm_local_bundle",
            symbol=SYMBOL,
            interval=interval,
            start=window_start,
            end=window_end,
            strategy_id=resolved_strategy,
            params=dict(strategy_params or {}),
            capital=float(capital),
            commission_rate=resolved_commission_rate,
            slippage_bps=resolved_slippage_bps,
            data_version=data_version,
            strategy_version=strategy_version,
            manifest_root=ledger / "audit" / "manifests",
            market_loader=lambda **_: frame.copy(),
            run_id=run_id,
        )
    except Exception:
        _clear_ledger_start_lock(start_lock)
        raise
    risk_gate = _call_after_start_lock(_risk_gate_summary, result)
    if not bool(risk_gate.get("enforced", False)):
        _clear_in_progress_cycle_marker(ledger=ledger, run_id=run_id)
        return _blocked_after_start_lock("btc_paper_validation_risk_gate_not_enforced")

    ledger_store = JsonlLedgerStore(ledger)
    try:
        _write_in_progress_cycle_marker_status(
            ledger=ledger,
            generated_at=generated,
            run_id=run_id,
            cycle_key=cycle_key,
            window_start=window_start,
            window_end=window_end,
            preflight=preflight,
            status="ledger_write_pending",
        )
        ledger_store.write_result(result.unified.event_driven, include_events=True)
        recon = build_ledger_reconciliation_artifact(
            ledger_store,
            initial_cash=float(capital),
            market_prices_by_time=_market_prices_by_time(frame),
        )
        recon_status = _reconciliation_status(recon)
        recon_path = ledger_store.write_reconciliation_artifact(recon)
        state = _update_validation_state(
            ledger=ledger,
            run_id=run_id,
            days_required=days_required,
            window_start=window_start,
            window_end=window_end,
            preflight=preflight,
            result=result,
            recon_status=recon_status,
            recon_path=recon_path,
            recon_artifact_hash=str(getattr(recon, "artifact_hash", "") or ""),
        )
        _write_startup_sync(ledger, generated_at=generated)
        _write_session_manifest(
            ledger,
            generated_at=generated,
            run_id=run_id,
            preflight=preflight,
            strategy_id=resolved_strategy,
            strategy_params=dict(strategy_params or {}),
            capital=float(capital),
            commission_rate=resolved_commission_rate,
            slippage_bps=resolved_slippage_bps,
            cost_model_report=cost_model_report,
            data_version=data_version,
            strategy_version=strategy_version,
            recon_path=recon_path,
            risk_gate=risk_gate,
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "PASS" if state["consecutive_clean_days"] >= days_required else "IN_PROGRESS",
            "asset": "btc",
            "symbol": SYMBOL,
            "market_type": MARKET_TYPE,
            "run_id": run_id,
            "ledger_root": str(ledger),
            "validation_state_path": str(ledger / "validation_state.json"),
            "days_required": int(days_required),
            "days_completed": int(state["days_completed"]),
            "consecutive_clean_days": int(state["consecutive_clean_days"]),
            "cycle": {
                "start": window_start.isoformat().replace("+00:00", "Z"),
                "end": window_end.isoformat().replace("+00:00", "Z"),
                "interval": interval,
                "bar_count": int(len(frame)),
            },
            "strategy": {
                "strategy_id": resolved_strategy,
                "strategy_version": strategy_version,
                "params": dict(strategy_params or {}),
            },
            "risk_gate": risk_gate,
            "execution": {
                "paper_broker": "simulated",
                "broker_backend": "simulated",
                "real_order_submission": False,
                "allows_live_orders": False,
                "orders_require_risk_engine": True,
                "pnl_source": "fills_and_ledger",
                "cost_model_report": cost_model_report,
                "commission_rate": resolved_commission_rate,
                "slippage_bps": resolved_slippage_bps,
            },
            "summary": dict(result.summary),
            "diagnostics": dict(result.diagnostics),
            "ledger_reconciliation_artifact_path": str(recon_path),
            "preflight": preflight,
        }
        _write_json(ledger / "validation_report.json", report)
    except Exception:
        _clear_ledger_start_lock(start_lock)
        raise
    _clear_in_progress_cycle_marker(ledger=ledger, run_id=run_id)
    _clear_attempt_report(ledger)
    _clear_ledger_start_lock(start_lock)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one guarded BTC USD-M paper-validation cycle.")
    parser.add_argument("--symbols", default=SYMBOL)
    parser.add_argument("--market-type", default=MARKET_TYPE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--start-report", default=str(DEFAULT_START_REPORT))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--strategy-id", default="")
    parser.add_argument("--strategy-params-json", default="{}")
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    parser.add_argument("--commission-rate", type=float, default=None)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--days-required", type=int, default=DEFAULT_DAYS_REQUIRED)
    parser.add_argument("--cycle-hours", type=int, default=DEFAULT_CYCLE_HOURS)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_btc_paper_validation(
        repo_root=Path(args.repo_root),
        symbols=_parse_symbols(args.symbols),
        market_type=args.market_type,
        interval=args.interval,
        ledger_root=Path(args.ledger_root),
        data_root=Path(args.data_root),
        readiness_report=Path(args.readiness_report),
        start_report=Path(args.start_report),
        config_path=Path(args.config_path),
        strategy_id=args.strategy_id,
        strategy_params=_parse_json_object(args.strategy_params_json),
        capital=args.capital,
        commission_rate=args.commission_rate,
        slippage_bps=args.slippage_bps,
        days_required=args.days_required,
        cycle_hours=args.cycle_hours,
        start=_parse_optional_utc(args.start),
        end=_parse_optional_utc(args.end),
        resume=args.resume,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(f"BTC paper validation status: {payload['status']}")
        print(f"ledger_root: {payload.get('ledger_root', args.ledger_root)}")
        if payload.get("status") == "BLOCKED":
            print(f"reason: {payload.get('reason', 'unknown')}")
    raise SystemExit(0 if payload.get("status") in {"PASS", "IN_PROGRESS"} else 1)


def _attempt_payload(
    *,
    generated_at: str,
    status: str,
    ledger_root: Path,
    preflight: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": ATTEMPT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "asset": "btc",
        "symbol": SYMBOL,
        "market_type": MARKET_TYPE,
        "ledger_root": str(ledger_root),
        "reason": reason,
        "preflight_status": str(preflight.get("status", "")),
        "preflight_blocking_reasons": list(preflight.get("blocking_reasons", [])),
        "paper_broker": "simulated",
        "broker_backend": "simulated",
        "real_order_submission": False,
        "allows_live_orders": False,
        "orders_require_risk_engine": True,
        "pnl_source": "fills_and_ledger",
        "network_required": False,
    }


def _write_attempt_report(ledger_root: Path, payload: Mapping[str, Any]) -> None:
    _write_json(ledger_root / "audit" / "btc_paper_validation_start_attempt.json", dict(payload))


def _clear_attempt_report(ledger_root: Path) -> None:
    try:
        (ledger_root / "audit" / "btc_paper_validation_start_attempt.json").unlink()
    except FileNotFoundError:
        return


def _load_bundle_frame(bundle_dir: Path, *, interval: str) -> pd.DataFrame:
    path = bundle_dir / f"klines_{interval}.csv"
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["symbol"] = SYMBOL
    frame = frame.set_index("timestamp").sort_index()
    return frame[["symbol", "open", "high", "low", "close", "volume"]]


def _paper_cost_model_binding(
    *,
    preflight: Mapping[str, Any],
    root: Path,
    requested_commission_rate: float | None,
    requested_slippage_bps: float | None,
) -> dict[str, Any]:
    inputs = _mapping(preflight.get("inputs"))
    path = _resolve(root, Path(str(inputs.get("cost_model_report") or DEFAULT_COST_MODEL)))
    report = _read_json(path)
    fee_model = _mapping(report.get("fee_model"))
    slippage_model = _mapping(report.get("slippage_model"))
    blockers: list[str] = []
    if str(report.get("status", "")) != "pass":
        blockers.append("btc_cost_model_report_not_pass")
    if fee_model.get("fee_tier_verified") is not True:
        blockers.append("btc_cost_model_fee_tier_not_verified")
    taker_fee_bps = _float_or_none(fee_model.get("taker_fee_bps"))
    if taker_fee_bps is None or taker_fee_bps < 0:
        blockers.append("btc_cost_model_taker_fee_bps_missing_or_invalid")
    model_slippage_bps = _float_or_none(slippage_model.get("slippage_bps"))
    if model_slippage_bps is None or model_slippage_bps < 0:
        blockers.append("btc_cost_model_slippage_bps_missing_or_invalid")
    if blockers:
        return {
            "ok": False,
            "reason": "btc_paper_validation_cost_model_binding_failed",
            "blockers": _dedupe(blockers),
            "cost_model_report": str(path),
        }

    model_commission_rate = float(taker_fee_bps) / 10_000.0
    requested_commission = _float_or_none(requested_commission_rate) if requested_commission_rate is not None else None
    requested_slippage = _float_or_none(requested_slippage_bps) if requested_slippage_bps is not None else None
    override_blockers: list[str] = []
    if requested_commission is not None and not _number_close(requested_commission, model_commission_rate):
        override_blockers.append("btc_paper_validation_commission_override_mismatch")
    if requested_slippage is not None and not _number_close(requested_slippage, float(model_slippage_bps)):
        override_blockers.append("btc_paper_validation_slippage_override_mismatch")
    if override_blockers:
        return {
            "ok": False,
            "reason": "btc_paper_validation_cost_override_mismatch",
            "blockers": override_blockers,
            "cost_model_report": str(path),
        }
    return {
        "ok": True,
        "commission_rate": model_commission_rate,
        "slippage_bps": float(model_slippage_bps),
        "cost_model_report": str(path),
    }


def _paper_strategy_binding(
    *,
    review: Mapping[str, Any],
    requested_strategy_id: str,
    strategy_params: Mapping[str, Any],
) -> dict[str, Any]:
    approved_strategy = str(review.get("strategy_manifest_id", "") or "").strip()
    requested = requested_strategy_id.strip()
    blockers: list[str] = []
    if not approved_strategy:
        blockers.append("btc_paper_validation_approved_strategy_missing")
    if requested and requested != approved_strategy:
        blockers.append("btc_paper_validation_strategy_id_not_approved")
    if dict(strategy_params):
        blockers.append("btc_paper_validation_strategy_params_not_approved")
    return {
        "ok": not blockers,
        "reason": "btc_paper_validation_strategy_binding_failed",
        "approved_strategy_id": approved_strategy,
        "requested_strategy_id": requested,
        "blockers": _dedupe(blockers),
    }


def _resolve_cycle_window(
    frame: pd.DataFrame,
    *,
    start: datetime | None,
    end: datetime | None,
    cycle_hours: int,
) -> tuple[datetime, datetime]:
    latest = pd.Timestamp(end) if end else pd.Timestamp(frame.index.max())
    earliest = pd.Timestamp(start) if start else latest - pd.Timedelta(hours=max(1, int(cycle_hours)))
    if latest.tzinfo is None:
        latest = latest.tz_localize("UTC")
    else:
        latest = latest.tz_convert("UTC")
    if earliest.tzinfo is None:
        earliest = earliest.tz_localize("UTC")
    else:
        earliest = earliest.tz_convert("UTC")
    return earliest.to_pydatetime(), latest.to_pydatetime()


def _update_validation_state(
    *,
    ledger: Path,
    run_id: str,
    days_required: int,
    window_start: datetime,
    window_end: datetime,
    preflight: Mapping[str, Any],
    result: Any,
    recon_status: str,
    recon_path: Path,
    recon_artifact_hash: str,
) -> dict[str, Any]:
    path = ledger / "validation_state.json"
    state = _read_json(path)
    if not state:
        state = {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": SYMBOL,
            "market_type": MARKET_TYPE,
            "days_required": int(days_required),
            "days_completed": 0,
            "consecutive_clean_days": 0,
            "completed_cycle_keys": [],
            "daily_results": [],
        }
    cycle_key = _validation_cycle_key(
        preflight=preflight,
        window_start=window_start,
        window_end=window_end,
    )
    completed = set(str(item) for item in state.get("completed_cycle_keys", []))
    clean = bool(result.unified.equity_consistent) and recon_status in {"clean", "ok", "pass", "passed", "complete"}
    if cycle_key not in completed:
        state["days_completed"] = int(state.get("days_completed", 0) or 0) + 1
        state["consecutive_clean_days"] = int(state.get("consecutive_clean_days", 0) or 0) + 1 if clean else 0
        state.setdefault("completed_cycle_keys", []).append(cycle_key)
        state.setdefault("daily_results", []).append(
            {
                "run_id": run_id,
                "cycle_key": cycle_key,
                "start": window_start.isoformat().replace("+00:00", "Z"),
                "end": window_end.isoformat().replace("+00:00", "Z"),
                "clean": clean,
                "equity_consistent": bool(result.unified.equity_consistent),
                "reconciliation_status": recon_status,
                "ledger_reconciliation_artifact_path": str(recon_path),
                "ledger_reconciliation_artifact_hash": recon_artifact_hash,
                "orders": int(result.diagnostics.get("orders", 0)),
                "fills": int(result.diagnostics.get("fills", 0)),
            }
        )
    state["updated_at"] = _utc_z_now()
    _write_json(path, state)
    return state


def _validation_cycle_key(
    *,
    preflight: Mapping[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> str:
    inputs = _mapping(preflight.get("inputs"))
    return (
        f"{window_start.isoformat()}::{window_end.isoformat()}::"
        f"{inputs.get('bundle_dir', '')}::{inputs.get('interval', '')}"
    )


def _validation_cycle_already_completed(*, ledger: Path, run_id: str, cycle_key: str) -> bool:
    state = _read_json(ledger / "validation_state.json")
    completed = {str(item) for item in state.get("completed_cycle_keys", [])}
    history = ledger / "audit" / "paper_session_manifests" / f"{run_id}.json"
    return cycle_key in completed or history.exists()


def _validation_cycle_recovery_required(
    *,
    ledger: Path,
    run_id: str,
    cycle_key: str,
    ignore_run_id: str = "",
) -> bool:
    ignored_marker = _in_progress_cycle_marker_path(ledger=ledger, run_id=ignore_run_id) if ignore_run_id else None
    marker_paths = [
        path
        for path in _in_progress_cycle_marker_paths(ledger)
        if ignored_marker is None or path.resolve() != ignored_marker.resolve()
    ]
    if marker_paths:
        return True
    marker = _read_json(_in_progress_cycle_marker_path(ledger=ledger, run_id=run_id))
    if not ignore_run_id and marker and str(marker.get("cycle_key", "")) == cycle_key:
        return True
    if _ledger_has_run_id_records(ledger=ledger, run_id=run_id):
        return True
    return not _read_json(ledger / "validation_state.json") and _ledger_has_any_runtime_records(ledger)


def _claim_ledger_start_lock(*, ledger: Path, generated_at: str) -> LedgerStartLock | None:
    lock = _ledger_start_lock_path(ledger)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
    except Exception:
        os.close(fd)
        raise
    claim_id = uuid.uuid4().hex
    payload = {
        "schema_version": "btc_paper_validation_ledger_start_lock_v1",
        "generated_at": generated_at,
        "claim_id": claim_id,
        "owner_pid": os.getpid(),
        "asset": "btc",
        "symbol": SYMBOL,
        "market_type": MARKET_TYPE,
        "status": "start_claimed",
    }
    try:
        _write_json_to_fd(fd, payload)
    except Exception:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        raise
    return LedgerStartLock(path=lock, claim_id=claim_id, fd=fd)


def _clear_ledger_start_lock(lock: LedgerStartLock) -> None:
    lock.release()


def _ledger_start_lock_path(ledger: Path) -> Path:
    return ledger / "audit" / LEDGER_START_LOCK_NAME


def _claim_in_progress_cycle_marker(
    *,
    ledger: Path,
    generated_at: str,
    run_id: str,
    cycle_key: str,
    window_start: datetime,
    window_end: datetime,
    preflight: Mapping[str, Any],
) -> bool:
    marker = _in_progress_cycle_marker_path(ledger=ledger, run_id=run_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = _in_progress_cycle_marker_payload(
        generated_at=generated_at,
        run_id=run_id,
        cycle_key=cycle_key,
        window_start=window_start,
        window_end=window_end,
        preflight=preflight,
        status="backtest_running",
    )
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, default=str))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _write_in_progress_cycle_marker_status(
    *,
    ledger: Path,
    generated_at: str,
    run_id: str,
    cycle_key: str,
    window_start: datetime,
    window_end: datetime,
    preflight: Mapping[str, Any],
    status: str,
) -> None:
    _write_json(
        _in_progress_cycle_marker_path(ledger=ledger, run_id=run_id),
        _in_progress_cycle_marker_payload(
            generated_at=generated_at,
            run_id=run_id,
            cycle_key=cycle_key,
            window_start=window_start,
            window_end=window_end,
            preflight=preflight,
            status=status,
        ),
    )


def _in_progress_cycle_marker_payload(
    *,
    generated_at: str,
    run_id: str,
    cycle_key: str,
    window_start: datetime,
    window_end: datetime,
    preflight: Mapping[str, Any],
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": "btc_paper_validation_in_progress_cycle_v1",
        "generated_at": generated_at,
        "asset": "btc",
        "symbol": SYMBOL,
        "market_type": MARKET_TYPE,
        "run_id": run_id,
        "cycle_key": cycle_key,
        "start": window_start.isoformat().replace("+00:00", "Z"),
        "end": window_end.isoformat().replace("+00:00", "Z"),
        "bundle_dir": _mapping(preflight.get("inputs")).get("bundle_dir", ""),
        "interval": _mapping(preflight.get("inputs")).get("interval", ""),
        "status": status,
    }


def _clear_in_progress_cycle_marker(*, ledger: Path, run_id: str) -> None:
    try:
        _in_progress_cycle_marker_path(ledger=ledger, run_id=run_id).unlink()
    except FileNotFoundError:
        return


def _in_progress_cycle_marker_path(*, ledger: Path, run_id: str) -> Path:
    return ledger / "audit" / "paper_validation_in_progress" / f"{run_id}.json"


def _in_progress_cycle_marker_paths(ledger: Path) -> list[Path]:
    marker_dir = ledger / "audit" / "paper_validation_in_progress"
    if not marker_dir.exists():
        return []
    return sorted(path for path in marker_dir.glob("*.json") if path.is_file())


def _write_startup_sync(ledger: Path, *, generated_at: str) -> None:
    _write_json(
        ledger / "audit" / "paper_broker_adapter_startup_sync.json",
        {
            "schema_version": "btc_paper_validation_startup_sync_v1",
            "generated_at": generated_at,
            "status": "clean_start",
            "asset": "btc",
            "symbol": SYMBOL,
            "market_type": MARKET_TYPE,
            "paper_broker": "simulated",
            "broker_backend": "simulated",
            "real_order_submission": False,
            "allows_live_orders": False,
        },
    )


def _write_session_manifest(
    ledger: Path,
    *,
    generated_at: str,
    run_id: str,
    preflight: Mapping[str, Any],
    strategy_id: str,
    strategy_params: Mapping[str, Any],
    capital: float,
    commission_rate: float,
    slippage_bps: float,
    cost_model_report: str,
    data_version: str,
    strategy_version: str,
    recon_path: Path,
    risk_gate: Mapping[str, Any],
) -> None:
    manifest = {
        "schema_version": "btc_paper_validation_session_manifest_v1",
        "generated_at": generated_at,
        "run_id": run_id,
        "asset": "btc",
        "symbol": SYMBOL,
        "market_type": MARKET_TYPE,
        "paper_broker": "simulated",
        "broker_backend": "simulated",
        "real_order_submission": False,
        "allows_live_orders": False,
        "orders_require_risk_engine": True,
        "pnl_source": "fills_and_ledger",
        "strategy_id": strategy_id,
        "strategy_params": dict(strategy_params),
        "capital": capital,
        "commission_rate": commission_rate,
        "slippage_bps": slippage_bps,
        "cost_model_report": cost_model_report,
        "data_version": data_version,
        "strategy_version": strategy_version,
        "bundle_dir": preflight["inputs"]["bundle_dir"],
        "ledger_reconciliation_artifact_path": str(recon_path),
        "risk_gate": dict(risk_gate),
        "no_real_order_submission_proof": {
            "paper_broker": "simulated",
            "broker_backend": "simulated",
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "live_order_submission_enabled": False,
        },
    }
    _write_json(ledger / "audit" / "paper_session_manifest.json", manifest)
    history = ledger / "audit" / "paper_session_manifests" / f"{run_id}.json"
    _write_json(history, manifest)


def _risk_gate_summary(result: Any) -> dict[str, Any]:
    evidence = _mapping(result.unified.evidence)
    orders = _mapping(evidence.get("orders"))
    risk = _mapping(evidence.get("risk"))
    order_count = int(orders.get("count", 0) or 0)
    risk_check_count = int(risk.get("risk_check_count", 0) or 0)
    all_orders_have_risk_check_id = bool(orders.get("all_orders_have_risk_check_id", False))
    all_orders_created_by_oms = bool(orders.get("all_orders_created_by_oms", False))
    rejected = int(risk.get("rejected", 0) or 0)
    enforced = (
        all_orders_created_by_oms
        and all_orders_have_risk_check_id
        and risk_check_count >= order_count
    )
    return {
        "enforced": enforced,
        "risk_check_count": risk_check_count,
        "order_count": order_count,
        "approved": int(risk.get("approved", 0) or 0),
        "rejected": rejected,
        "rejection_reasons": _mapping(risk.get("rejection_reasons")),
        "all_orders_created_by_oms": all_orders_created_by_oms,
        "all_orders_have_risk_check_id": all_orders_have_risk_check_id,
    }


def _market_prices_by_time(frame: pd.DataFrame) -> dict[datetime, dict[str, float]]:
    return {timestamp.to_pydatetime(): {SYMBOL: float(row["close"])} for timestamp, row in frame.iterrows()}


def _reconciliation_status(recon: Any) -> str:
    reconciliation = _mapping(getattr(recon, "reconciliation", {}))
    summary = _mapping(reconciliation.get("summary"))
    if summary.get("passed") is True:
        return "clean"
    if summary.get("passed") is False:
        return "breaks_detected"
    integrity = _mapping(getattr(recon, "integrity", {}))
    return "clean" if integrity.get("passed") is True else "unknown"


def _data_version(preflight: Mapping[str, Any], *, window_start: datetime, window_end: datetime) -> str:
    bundle = _mapping(preflight.get("bundle"))
    bundle_id = str(bundle.get("selected_bundle_id", "btc_usdm_bundle"))
    return (
        f"qs-binance-usdm-{SYMBOL}-{preflight['inputs']['interval']}-"
        f"{window_start.strftime('%Y%m%dT%H%M')}-{window_end.strftime('%Y%m%dT%H%M')}-{bundle_id}"
    )


def _ledger_has_runtime_records(ledger: Path) -> bool:
    return any((ledger / name).exists() and (ledger / name).stat().st_size > 0 for name in ("orders.jsonl", "fills.jsonl"))


def _ledger_is_clean_start(ledger: Path) -> bool:
    return (
        not _read_json(ledger / "validation_state.json")
        and not _session_manifest_paths(ledger)
        and not _in_progress_cycle_marker_paths(ledger)
        and not _ledger_has_any_runtime_records(ledger)
    )


def _ledger_has_resumable_session(ledger: Path) -> bool:
    return _validation_state_valid(_read_json(ledger / "validation_state.json"))


def _session_manifest_paths(ledger: Path) -> list[Path]:
    history = ledger / "audit" / "paper_session_manifests"
    paths = [ledger / "audit" / "paper_session_manifest.json"]
    if history.exists():
        paths.extend(sorted(path for path in history.glob("*.json") if path.is_file()))
    return [path for path in paths if path.exists()]


def _ledger_has_any_runtime_records(ledger: Path) -> bool:
    return any(
        (ledger / name).exists() and (ledger / name).stat().st_size > 0
        for name in ("orders.jsonl", "fills.jsonl", "portfolio_snapshots.jsonl", "events.jsonl")
    )


def _ledger_has_run_id_records(*, ledger: Path, run_id: str) -> bool:
    for name in ("orders.jsonl", "fills.jsonl", "portfolio_snapshots.jsonl", "events.jsonl"):
        path = ledger / name
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return True
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                return True
            if isinstance(row, Mapping) and str(row.get("run_id", "")) == run_id:
                return True
    return False


def _parse_symbols(raw: str) -> list[str]:
    return sorted({item.strip().upper() for item in raw.split(",") if item.strip()})


def _parse_json_object(raw: str) -> dict[str, Any]:
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise SystemExit("--strategy-params-json must decode to an object")
    return payload


def _parse_optional_utc(raw: str) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _validation_state_valid(state: Mapping[str, Any]) -> bool:
    if not state:
        return False
    completed = state.get("completed_cycle_keys")
    daily = state.get("daily_results")
    if not isinstance(completed, list) or not all(isinstance(item, str) and item for item in completed):
        return False
    if not isinstance(daily, list) or not all(isinstance(item, Mapping) for item in daily):
        return False
    days_required = _nonnegative_int(state.get("days_required"))
    days_completed = _nonnegative_int(state.get("days_completed"))
    consecutive = _nonnegative_int(state.get("consecutive_clean_days"))
    return (
        state.get("schema_version") == "btc_paper_validation_state_v1"
        and state.get("asset") == "btc"
        and state.get("symbol") == SYMBOL
        and state.get("market_type") == MARKET_TYPE
        and days_required is not None
        and days_required > 0
        and days_completed is not None
        and consecutive is not None
        and consecutive <= days_completed
    )


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), indent=2, sort_keys=True, default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        return
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _read_json_from_fd(fd: int) -> dict[str, Any]:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 1_000_000).decode("utf-8").strip()
        if not raw:
            return {}
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json_to_fd(fd: int, payload: Mapping[str, Any]) -> None:
    data = (json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, data)
    os.fsync(fd)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _number_close(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
