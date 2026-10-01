#!/usr/bin/env python3
"""Run one BTC trend v0 daily paper cycle with simulated ledger only."""

from __future__ import annotations

import argparse
import json
import math
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

from scripts.build_btc_only_trend_v0_report import _load_daily_bars  # noqa: E402
from scripts.check_btc_trend_paper_readiness import (  # noqa: E402
    DEFAULT_FREEZE_REPORT,
    DEFAULT_LEDGER_ROOT,
    DEFAULT_PROMOTION_GATE,
    EXPECTED_SELECTED_CANDIDATE,
    check_btc_trend_paper_readiness,
)


SCHEMA_VERSION = "btc_trend_daily_paper_roll_report_v1"
DEFAULT_BUNDLE_DIR = Path("data/external/btc_spot/okx/bundles/btc_okx_spot_btcusdt_daily_5y_v1")
DEFAULT_READINESS_REPORT = Path("artifacts/btc_trend_v0/latest/btc_trend_paper_readiness_report.json")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_daily_paper_roll_report.json")
DEFAULT_INITIAL_CAPITAL = 25_000.0
DEFAULT_FEE_BPS = 5.0
SYMBOL = "BTCUSDT"


def run_btc_trend_daily_paper_roll(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    promotion_gate: Path = DEFAULT_PROMOTION_GATE,
    freeze_report: Path = DEFAULT_FREEZE_REPORT,
    readiness_report: Path = DEFAULT_READINESS_REPORT,
    output: Path = DEFAULT_OUTPUT,
    selected_candidate: str = EXPECTED_SELECTED_CANDIDATE,
    as_of: str = "",
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    fee_bps: float = DEFAULT_FEE_BPS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    output_path = _resolve(root, output)
    readiness = check_btc_trend_paper_readiness(
        repo_root=root,
        promotion_gate=promotion_gate,
        freeze_report=freeze_report,
        ledger_root=ledger_root,
        output=readiness_report,
        expected_selected_candidate=selected_candidate,
        generated_at=generated,
    )
    if readiness.get("status") != "PASS":
        payload = _blocked_payload(
            generated_at=generated,
            ledger=ledger,
            output_path=output_path,
            readiness=readiness,
            selected_candidate=selected_candidate,
            blockers=[str(item) for item in readiness.get("blockers", []) if item],
        )
        _write_json(output_path, payload)
        return payload

    bundle_abs = _resolve(root, bundle_dir)
    daily = _load_daily_bars(bundle_abs)
    cycle = _select_cycle(daily, as_of=as_of)
    blockers = list(cycle.get("blockers", []))
    if blockers:
        payload = _blocked_payload(
            generated_at=generated,
            ledger=ledger,
            output_path=output_path,
            readiness=readiness,
            selected_candidate=selected_candidate,
            blockers=[str(item) for item in blockers],
        )
        _write_json(output_path, payload)
        return payload

    ledger.mkdir(parents=True, exist_ok=True)
    # Keep the ledger contract stable even on no-trade days.
    (ledger / "fills.jsonl").touch(exist_ok=True)
    state_path = ledger / "validation_state.json"
    state = _read_json(state_path)
    cycle_timestamp = str(cycle["timestamp"])
    if str(state.get("last_processed_timestamp", "")) == cycle_timestamp:
        latest_snapshot = _latest_jsonl(ledger / "portfolio_snapshots.jsonl")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "PASS",
            "cycle_status": "SKIPPED_ALREADY_COMPLETED",
            "asset": "btc",
            "symbol": SYMBOL,
            "strategy_id": selected_candidate,
            "ledger_root": _relpath(ledger, root),
            "readiness": _readiness_summary(readiness),
            "cycle": cycle,
            "prior_exposure": state.get("current_exposure", 0.0),
            "target_exposure": state.get("current_exposure", 0.0),
            "turnover": 0.0,
            "simulated_fee": 0.0,
            "final_equity": _float_or(latest_snapshot.get("equity"), _float_or(state.get("current_equity"), initial_capital)),
            "reconciliation": {"status": "clean", "passed": True, "reason": "cycle_already_completed"},
            "guardrails": _guardrails(),
            "blockers": [],
        }
        _write_json(output_path, payload)
        return payload

    prior_equity = _float_or(state.get("current_equity"), float(initial_capital))
    prior_exposure = _float_or(state.get("current_exposure"), 0.0)
    target_exposure = float(cycle["target_exposure"])
    turnover = abs(target_exposure - prior_exposure)
    fee_rate = float(fee_bps) / 10_000.0
    simulated_fee = prior_equity * turnover * fee_rate
    daily_return = float(cycle["daily_return"])
    strategy_daily_return = target_exposure * daily_return - turnover * fee_rate
    final_equity = prior_equity * (1.0 + strategy_daily_return)
    if not math.isfinite(final_equity):
        payload = _blocked_payload(
            generated_at=generated,
            ledger=ledger,
            output_path=output_path,
            readiness=readiness,
            selected_candidate=selected_candidate,
            blockers=["btc_trend_daily_paper_equity_not_finite"],
        )
        _write_json(output_path, payload)
        return payload

    target_row = {
        "timestamp": cycle_timestamp,
        "strategy_id": selected_candidate,
        "symbol": SYMBOL,
        "target_exposure": round(target_exposure, 10),
        "prior_exposure": round(prior_exposure, 10),
        "raw_signal": cycle["raw_signal"],
        "signal_timestamp": cycle["signal_timestamp"],
        "effective_timestamp": cycle["timestamp"],
        "reason": cycle["reason"],
        "generated_at": generated,
        "simulated_only": True,
    }
    fill_row = _fill_row(
        cycle=cycle,
        selected_candidate=selected_candidate,
        prior_equity=prior_equity,
        prior_exposure=prior_exposure,
        target_exposure=target_exposure,
        turnover=turnover,
        simulated_fee=simulated_fee,
        fee_bps=fee_bps,
        generated_at=generated,
    )
    snapshot = {
        "timestamp": cycle_timestamp,
        "strategy_id": selected_candidate,
        "symbol": SYMBOL,
        "prior_equity": round(prior_equity, 6),
        "equity": round(final_equity, 6),
        "prior_exposure": round(prior_exposure, 10),
        "target_exposure": round(target_exposure, 10),
        "daily_return": round(daily_return, 10),
        "strategy_daily_return": round(strategy_daily_return, 10),
        "turnover": round(turnover, 10),
        "simulated_fee": round(simulated_fee, 6),
        "close": cycle["close"],
        "reconciliation_status": "clean",
        "generated_at": generated,
    }
    _append_jsonl(ledger / "target_positions.jsonl", target_row)
    if fill_row:
        _append_jsonl(ledger / "fills.jsonl", fill_row)
    _append_jsonl(ledger / "portfolio_snapshots.jsonl", snapshot)
    new_state = {
        "schema_version": "btc_trend_paper_validation_state_v1",
        "updated_at": generated,
        "strategy_id": selected_candidate,
        "initial_capital": float(initial_capital),
        "current_equity": round(final_equity, 6),
        "current_exposure": round(target_exposure, 10),
        "days_completed": int(state.get("days_completed", 0) or 0) + 1,
        "target_position_count": int(state.get("target_position_count", 0) or 0) + 1,
        "fill_count": int(state.get("fill_count", 0) or 0) + (1 if fill_row else 0),
        "last_processed_timestamp": cycle_timestamp,
        "last_signal_timestamp": cycle["signal_timestamp"],
        "ledger_root": _relpath(ledger, root),
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    }
    _write_json(state_path, new_state)
    reconciliation = _reconciliation(snapshot=snapshot, prior_equity=prior_equity, target_exposure=target_exposure, daily_return=daily_return, turnover=turnover, fee_bps=fee_bps)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "PASS" if reconciliation["passed"] else "BLOCKED",
        "cycle_status": "COMPLETED" if reconciliation["passed"] else "RECONCILIATION_FAILED",
        "asset": "btc",
        "symbol": SYMBOL,
        "strategy_id": selected_candidate,
        "ledger_root": _relpath(ledger, root),
        "readiness": _readiness_summary(readiness),
        "cycle": cycle,
        "prior_exposure": round(prior_exposure, 10),
        "target_exposure": round(target_exposure, 10),
        "turnover": round(turnover, 10),
        "simulated_fee": round(simulated_fee, 6),
        "fee_bps": float(fee_bps),
        "final_equity": round(final_equity, 6),
        "target_position": target_row,
        "fill": fill_row,
        "portfolio_snapshot": snapshot,
        "validation_state_path": _relpath(state_path, root),
        "reconciliation": reconciliation,
        "guardrails": _guardrails(),
        "blockers": [] if reconciliation["passed"] else ["btc_trend_daily_paper_reconciliation_failed"],
    }
    _write_json(output_path, payload)
    return payload


def _select_cycle(daily: pd.DataFrame, *, as_of: str) -> dict[str, Any]:
    if daily.empty:
        return {"blockers": ["btc_trend_daily_bundle_empty"]}
    frame = daily.copy().sort_index()
    if as_of:
        as_of_ts = pd.Timestamp(as_of)
        if as_of_ts.tzinfo is None:
            as_of_ts = as_of_ts.tz_localize("UTC")
        else:
            as_of_ts = as_of_ts.tz_convert("UTC")
        frame = frame[frame.index <= as_of_ts]
    if len(frame) < 2:
        return {"blockers": ["btc_trend_daily_cycle_needs_prior_day"]}
    close = frame["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    current_ts = close.index[-1]
    signal_ts = close.index[-2]
    source_pos = len(close) - 2
    raw = 0.0
    if source_pos >= 365:
        prior = float(close.iloc[source_pos - 365])
        raw = 1.0 if prior > 0 and float(close.iloc[source_pos]) / prior - 1.0 > 0.0 else 0.0
    return {
        "blockers": [],
        "timestamp": _timestamp_text(current_ts),
        "close": round(float(close.iloc[-1]), 6),
        "prior_close": round(float(close.iloc[-2]), 6),
        "daily_return": round(float(returns.iloc[-1]), 10),
        "raw_signal": round(raw, 10),
        "signal_timestamp": _timestamp_text(signal_ts),
        "effective_timestamp": _timestamp_text(current_ts),
        "target_exposure": round(raw, 10),
        "reason": "twelve_month_momentum_positive_t_plus_1" if raw > 0.0 else "twelve_month_momentum_non_positive_t_plus_1",
    }


def _fill_row(
    *,
    cycle: Mapping[str, Any],
    selected_candidate: str,
    prior_equity: float,
    prior_exposure: float,
    target_exposure: float,
    turnover: float,
    simulated_fee: float,
    fee_bps: float,
    generated_at: str,
) -> dict[str, Any] | None:
    if turnover <= 1e-12:
        return None
    delta = target_exposure - prior_exposure
    close = float(cycle["close"])
    notional = prior_equity * abs(delta)
    quantity = notional / close if close > 0 else 0.0
    return {
        "timestamp": cycle["timestamp"],
        "strategy_id": selected_candidate,
        "symbol": SYMBOL,
        "side": "buy" if delta > 0 else "sell",
        "price": round(close, 6),
        "quantity": round(quantity, 10),
        "notional": round(notional, 6),
        "prior_exposure": round(prior_exposure, 10),
        "target_exposure": round(target_exposure, 10),
        "turnover": round(turnover, 10),
        "fee_bps": float(fee_bps),
        "simulated_fee": round(simulated_fee, 6),
        "simulated_only": True,
        "broker_order_id": "",
        "exchange_order_id": "",
        "reason": cycle["reason"],
        "generated_at": generated_at,
    }


def _reconciliation(
    *,
    snapshot: Mapping[str, Any],
    prior_equity: float,
    target_exposure: float,
    daily_return: float,
    turnover: float,
    fee_bps: float,
) -> dict[str, Any]:
    expected = prior_equity * (1.0 + target_exposure * daily_return - turnover * (fee_bps / 10_000.0))
    actual = _float_or(snapshot.get("equity"), 0.0)
    diff = abs(expected - actual)
    return {
        "status": "clean" if diff <= 0.01 else "mismatch",
        "passed": diff <= 0.01,
        "expected_equity": round(expected, 6),
        "actual_equity": round(actual, 6),
        "difference": round(diff, 8),
    }


def _blocked_payload(
    *,
    generated_at: str,
    ledger: Path,
    output_path: Path,
    readiness: Mapping[str, Any],
    selected_candidate: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "BLOCKED",
        "cycle_status": "NOT_RUN",
        "asset": "btc",
        "symbol": SYMBOL,
        "strategy_id": selected_candidate,
        "ledger_root": str(ledger).replace("\\", "/"),
        "readiness": _readiness_summary(readiness),
        "guardrails": _guardrails(),
        "blockers": _dedupe(blockers),
        "output": str(output_path).replace("\\", "/"),
    }


def _readiness_summary(readiness: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(readiness.get("status", "")),
        "selected_candidate": str(readiness.get("selected_candidate", "")),
        "blockers": [str(item) for item in readiness.get("blockers", []) if item],
    }


def _guardrails() -> dict[str, Any]:
    return {
        "simulated_only": True,
        "paper_runner_is_not_strategy_validation": True,
        "strategy_validation_gate_required_before_strategy_claims": True,
        "broker_calls_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
        "do_not_reuse_5m_hft_ledger": True,
    }


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True, default=str))
        handle.write("\n")


def _latest_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    latest = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            latest = line
    if not latest:
        return {}
    payload = json.loads(latest)
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _float_or(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _timestamp_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one BTC trend v0 daily paper cycle.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--promotion-gate", default=str(DEFAULT_PROMOTION_GATE))
    parser.add_argument("--freeze-report", default=str(DEFAULT_FREEZE_REPORT))
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--selected-candidate", default=EXPECTED_SELECTED_CANDIDATE)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_btc_trend_daily_paper_roll(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir),
        ledger_root=Path(args.ledger_root),
        promotion_gate=Path(args.promotion_gate),
        freeze_report=Path(args.freeze_report),
        readiness_report=Path(args.readiness_report),
        output=Path(args.output),
        selected_candidate=args.selected_candidate,
        as_of=args.as_of,
        initial_capital=args.initial_capital,
        fee_bps=args.fee_bps,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])
    raise SystemExit(0 if payload.get("status") == "PASS" else 2)


if __name__ == "__main__":
    main()
