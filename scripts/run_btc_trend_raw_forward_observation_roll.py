#!/usr/bin/env python3
"""Run one BTC raw trend forward-observation cycle.

The runner writes a simulated observation ledger only. It never creates broker
orders, never uses private endpoints, and does not promote the strategy.
"""

from __future__ import annotations

import argparse
import hashlib
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

from quant_crypto.oms.lifecycle import BTCPaperOMS  # noqa: E402
from quant_crypto.portfolio.forecast import (  # noqa: E402
    BTCForecastQuality,
    BTCRiskBudget,
    BTCRiskState,
    btc_forecast_to_target_position,
    signal_to_btc_forecast,
)
from quant_crypto.portfolio.order_intent import BTCExecutionCostEstimate, btc_target_to_cost_aware_order_intent  # noqa: E402
from quant_crypto.trading_contracts import Signal, SignalDirection  # noqa: E402

from scripts.build_btc_only_trend_v0_report import _load_daily_bars  # noqa: E402
from scripts.check_btc_trend_raw_forward_observation_readiness import (  # noqa: E402
    DEFAULT_5M_FREEZE_REPORT,
    DEFAULT_BUNDLE_DIR,
    DEFAULT_LEDGER_ROOT,
    DEFAULT_OUTPUT as DEFAULT_READINESS_REPORT,
    DEFAULT_RAW_PLAN_REPORT,
    DEFAULT_TOP_VALIDATION_REPORT,
    DEFAULT_VOLATILITY_FREEZE_REPORT,
    EXPECTED_PRIMARY_CANDIDATE,
    EXPECTED_PRIMARY_FAMILY,
    EXPECTED_STRATEGY_ID,
    check_btc_trend_raw_forward_observation_readiness,
)


SCHEMA_VERSION = "btc_trend_raw_forward_observation_roll_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_roll_report.json")
DEFAULT_INITIAL_CAPITAL = 25_000.0
DEFAULT_FEE_BPS = 5.0
SYMBOL = "BTCUSDT"
MOMENTUM_WINDOW_DAYS = 365


def run_btc_trend_raw_forward_observation_roll(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    ledger_root: Path = DEFAULT_LEDGER_ROOT,
    top_validation_report: Path = DEFAULT_TOP_VALIDATION_REPORT,
    raw_plan_report: Path = DEFAULT_RAW_PLAN_REPORT,
    volatility_freeze_report: Path = DEFAULT_VOLATILITY_FREEZE_REPORT,
    five_minute_freeze_report: Path = DEFAULT_5M_FREEZE_REPORT,
    readiness_report: Path = DEFAULT_READINESS_REPORT,
    output: Path = DEFAULT_OUTPUT,
    as_of: str = "",
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    fee_bps: float = DEFAULT_FEE_BPS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    ledger = _resolve(root, ledger_root)
    output_path = _resolve(root, output)
    readiness = check_btc_trend_raw_forward_observation_readiness(
        repo_root=root,
        top_validation_report=top_validation_report,
        raw_plan_report=raw_plan_report,
        volatility_freeze_report=volatility_freeze_report,
        five_minute_freeze_report=five_minute_freeze_report,
        bundle_dir=bundle_dir,
        ledger_root=ledger_root,
        output=readiness_report,
        generated_at=generated,
    )
    if readiness.get("status") != "PASS":
        payload = _blocked_payload(
            generated_at=generated,
            ledger=ledger,
            output_path=output_path,
            readiness=readiness,
            blockers=[str(item) for item in readiness.get("blockers", []) if item],
        )
        _write_json(output_path, payload)
        return payload

    bundle_abs = _resolve(root, bundle_dir)
    try:
        daily = _load_daily_bars(bundle_abs)
    except Exception as exc:  # noqa: BLE001 - runner must fail closed with evidence.
        payload = _blocked_payload(
            generated_at=generated,
            ledger=ledger,
            output_path=output_path,
            readiness=readiness,
            blockers=[f"btc_trend_raw_forward_daily_bundle_unreadable:{exc}"],
        )
        _write_json(output_path, payload)
        return payload

    cycle = _select_cycle(daily, as_of=as_of)
    blockers = [str(item) for item in cycle.get("blockers", []) if item]
    if blockers:
        payload = _blocked_payload(
            generated_at=generated,
            ledger=ledger,
            output_path=output_path,
            readiness=readiness,
            blockers=blockers,
        )
        _write_json(output_path, payload)
        return payload

    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "fills.jsonl").touch(exist_ok=True)
    state_path = ledger / "validation_state.json"
    state = _read_json(state_path)
    cycle_timestamp = str(cycle["timestamp"])
    if str(state.get("last_processed_timestamp", "")) == cycle_timestamp:
        latest_snapshot = _latest_jsonl(ledger / "portfolio_snapshots.jsonl")
        boundary_chain = _build_forecast_target_order_chain(
            root=root,
            ledger=ledger,
            cycle=cycle,
            prior_equity=_float_or(latest_snapshot.get("equity"), _float_or(state.get("current_equity"), initial_capital)),
            prior_exposure=_float_or(state.get("current_exposure"), 0.0),
            target_exposure=_float_or(state.get("current_exposure"), 0.0),
            fee_bps=fee_bps,
            generated_at=generated,
            top_validation_report=top_validation_report,
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "PASS",
            "cycle_status": "SKIPPED_ALREADY_COMPLETED",
            "asset": "btc",
            "symbol": SYMBOL,
            "strategy_id": EXPECTED_STRATEGY_ID,
            "family_id": EXPECTED_PRIMARY_FAMILY,
            "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
            "ledger_root": _relpath(ledger, root),
            "readiness": _readiness_summary(readiness),
            "cycle": cycle,
            "prior_exposure": _float_or(state.get("current_exposure"), 0.0),
            "target_exposure": _float_or(state.get("current_exposure"), 0.0),
            "turnover": 0.0,
            "simulated_fee": 0.0,
            "final_equity": _float_or(latest_snapshot.get("equity"), _float_or(state.get("current_equity"), initial_capital)),
            "reconciliation": {"status": "clean", "passed": True, "reason": "cycle_already_completed"},
            "forecast_target_order_chain": boundary_chain,
            "guardrails": _guardrails(),
            "blockers": [],
        }
        _write_json(output_path, payload)
        return payload

    prior_equity = _float_or(state.get("current_equity"), float(initial_capital))
    prior_exposure = _float_or(state.get("current_exposure"), 0.0)
    target_exposure = float(cycle["target_exposure"])
    boundary_chain = _build_forecast_target_order_chain(
        root=root,
        ledger=ledger,
        cycle=cycle,
        prior_equity=prior_equity,
        prior_exposure=prior_exposure,
        target_exposure=target_exposure,
        fee_bps=fee_bps,
        generated_at=generated,
        top_validation_report=top_validation_report,
    )
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
            blockers=["btc_trend_raw_forward_equity_not_finite"],
        )
        _write_json(output_path, payload)
        return payload

    target_row = {
        "timestamp": cycle_timestamp,
        "strategy_id": EXPECTED_STRATEGY_ID,
        "family_id": EXPECTED_PRIMARY_FAMILY,
        "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
        "symbol": SYMBOL,
        "target_exposure": round(target_exposure, 10),
        "prior_exposure": round(prior_exposure, 10),
        "raw_signal": cycle["raw_signal"],
        "signal_timestamp": cycle["signal_timestamp"],
        "effective_timestamp": cycle["effective_timestamp"],
        "lookback_timestamp": cycle["lookback_timestamp"],
        "signal_close": cycle["signal_close"],
        "lookback_close": cycle["lookback_close"],
        "reason": cycle["reason"],
        "generated_at": generated,
        "simulated_only": True,
    }
    fill_row = _fill_row(
        cycle=cycle,
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
        "strategy_id": EXPECTED_STRATEGY_ID,
        "family_id": EXPECTED_PRIMARY_FAMILY,
        "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
        "symbol": SYMBOL,
        "prior_equity": round(prior_equity, 6),
        "equity": round(final_equity, 6),
        "prior_exposure": round(prior_exposure, 10),
        "target_exposure": round(target_exposure, 10),
        "daily_return": round(daily_return, 10),
        "strategy_daily_return": round(strategy_daily_return, 10),
        "turnover": round(turnover, 10),
        "fee_bps": float(fee_bps),
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
        "schema_version": "btc_trend_raw_forward_observation_state_v1",
        "updated_at": generated,
        "strategy_id": EXPECTED_STRATEGY_ID,
        "family_id": EXPECTED_PRIMARY_FAMILY,
        "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
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
        "live_order_allowed": False,
    }
    _write_json(state_path, new_state)

    reconciliation = _reconciliation(
        snapshot=snapshot,
        prior_equity=prior_equity,
        target_exposure=target_exposure,
        daily_return=daily_return,
        turnover=turnover,
        fee_bps=fee_bps,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "PASS" if reconciliation["passed"] else "BLOCKED",
        "cycle_status": "COMPLETED" if reconciliation["passed"] else "RECONCILIATION_FAILED",
        "asset": "btc",
        "symbol": SYMBOL,
        "strategy_id": EXPECTED_STRATEGY_ID,
        "family_id": EXPECTED_PRIMARY_FAMILY,
        "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
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
        "forecast_target_order_chain": boundary_chain,
        "validation_state_path": _relpath(state_path, root),
        "reconciliation": reconciliation,
        "guardrails": _guardrails(),
        "blockers": [] if reconciliation["passed"] else ["btc_trend_raw_forward_reconciliation_failed"],
    }
    _write_json(output_path, payload)
    return payload


def _select_cycle(daily: pd.DataFrame, *, as_of: str) -> dict[str, Any]:
    if daily.empty:
        return {"blockers": ["btc_trend_raw_forward_daily_bundle_empty"]}
    frame = daily.copy().sort_index()
    if as_of:
        as_of_ts = pd.Timestamp(as_of)
        if as_of_ts.tzinfo is None:
            as_of_ts = as_of_ts.tz_localize("UTC")
        else:
            as_of_ts = as_of_ts.tz_convert("UTC")
        frame = frame[frame.index <= as_of_ts]
    if len(frame) < MOMENTUM_WINDOW_DAYS + 2:
        return {"blockers": ["btc_trend_raw_forward_needs_365_day_signal_plus_t_plus_1"]}
    close = frame["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    effective_pos = len(close) - 1
    signal_pos = effective_pos - 1
    lookback_pos = signal_pos - MOMENTUM_WINDOW_DAYS
    effective_ts = close.index[effective_pos]
    signal_ts = close.index[signal_pos]
    lookback_ts = close.index[lookback_pos]
    signal_close = float(close.iloc[signal_pos])
    lookback_close = float(close.iloc[lookback_pos])
    raw = 1.0 if lookback_close > 0 and signal_close > lookback_close else 0.0
    return {
        "blockers": [],
        "timestamp": _timestamp_text(effective_ts),
        "effective_timestamp": _timestamp_text(effective_ts),
        "close": round(float(close.iloc[effective_pos]), 6),
        "prior_close": round(float(close.iloc[signal_pos]), 6),
        "daily_return": round(float(returns.iloc[effective_pos]), 10),
        "raw_signal": round(raw, 10),
        "signal_timestamp": _timestamp_text(signal_ts),
        "lookback_timestamp": _timestamp_text(lookback_ts),
        "signal_close": round(signal_close, 6),
        "lookback_close": round(lookback_close, 6),
        "target_exposure": round(raw, 10),
        "rule": "close[T] > close[T-365] then raw_signal=1 else 0; exposure effective T+1",
        "reason": "t01_365d_momentum_positive_t_plus_1" if raw > 0.0 else "t01_365d_momentum_non_positive_t_plus_1",
    }


def _fill_row(
    *,
    cycle: Mapping[str, Any],
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
        "strategy_id": EXPECTED_STRATEGY_ID,
        "family_id": EXPECTED_PRIMARY_FAMILY,
        "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
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


def _build_forecast_target_order_chain(
    *,
    root: Path,
    ledger: Path,
    cycle: Mapping[str, Any],
    prior_equity: float,
    prior_exposure: float,
    target_exposure: float,
    fee_bps: float,
    generated_at: str,
    top_validation_report: Path,
) -> dict[str, Any]:
    artifacts_dir = ledger / "artifacts" / "forecast_target_order_chain"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _parse_utc(str(cycle["timestamp"]))
    raw_signal = float(cycle.get("raw_signal", 0.0) or 0.0)
    direction = SignalDirection.LONG if raw_signal > 0.0 else SignalDirection.FLAT
    signal = Signal(
        timestamp_utc=timestamp,
        strategy_id=EXPECTED_STRATEGY_ID,
        symbol=SYMBOL,
        direction=direction,
        strength=abs(raw_signal),
        horizon="1d",
        reason=str(cycle.get("reason", "")),
        metadata={
            "source_boundary": "trend_cycle_to_signal",
            "signal_timestamp": cycle.get("signal_timestamp"),
            "effective_timestamp": cycle.get("effective_timestamp"),
            "rule": cycle.get("rule"),
        },
    )
    quality = BTCForecastQuality(
        ic=0.01,
        sample_size=1,
        evidence_path=_relpath(_resolve(root, top_validation_report), root),
        evidence_hash=_file_sha256(_resolve(root, top_validation_report)),
    )
    forecast = signal_to_btc_forecast(
        signal,
        quality=quality,
        horizon="1d",
        expiry_bars=1,
        bar_minutes=24 * 60,
        max_expected_return_bps=max(abs(float(cycle.get("daily_return", 0.0) or 0.0)) * 10_000.0, 1.0),
    )
    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=1.0,
            strategy_risk_budget=1.0,
            target_volatility=1.0,
            current_weight=prior_exposure,
            max_turnover=1.0,
            estimated_round_trip_cost_bps=float(fee_bps),
            require_funding_rate=False,
            require_liquidation_risk=False,
        ),
        risk_state=BTCRiskState(
            cash_fraction=max(0.0, 1.0 - abs(prior_exposure)),
            daily_loss_pct=0.0,
            current_drawdown_pct=0.0,
            funding_rate=0.0,
        ),
        account_equity=prior_equity,
        mark_price=float(cycle["close"]),
    )
    target = _override_target_to_raw_trend_exposure(target, target_exposure, prior_equity, float(cycle["close"]))
    cost_decision = btc_target_to_cost_aware_order_intent(
        target,
        current_quantity=prior_equity * prior_exposure / float(cycle["close"]),
        cost_estimate=BTCExecutionCostEstimate(
            fee_bps=float(fee_bps),
            spread_bps=0.0,
            slippage_bps=0.0,
            funding_bps=0.0,
            impact_bps=0.0,
            source="btc_raw_forward_simulated_daily_close",
        ),
        min_quantity=0.0,
        min_alpha_to_cost_ratio=0.0,
    )
    oms_payload: dict[str, Any]
    if cost_decision.approved and cost_decision.order_intent is not None:
        lifecycle = BTCPaperOMS().create_order(cost_decision.order_intent)
        lifecycle.mark_risk_checked(approved=True, reason="simulated_cost_gate_approved")
        oms_payload = {
            "source_boundary": "btc_paper_oms_lifecycle",
            "order_required": True,
            "lifecycle": lifecycle.to_dict(),
            "real_order_submitted": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        }
    else:
        oms_payload = {
            "source_boundary": "btc_paper_oms_lifecycle",
            "order_required": False,
            "reason": "no_order_intent_approved_or_delta_below_minimum",
            "cost_gate_blockers": cost_decision.blockers,
            "real_order_submitted": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        }
    signal_payload = {
        "source_boundary": "trend_cycle_to_signal",
        "signal": {
            "signal_id": signal.signal_id,
            "timestamp_utc": signal.timestamp_utc.isoformat(),
            "strategy_id": signal.strategy_id,
            "symbol": signal.symbol,
            "direction": signal.direction.value,
            "strength": signal.strength,
            "horizon": signal.horizon,
            "reason": signal.reason,
            "metadata": signal.metadata,
        },
    }
    forecast_payload = {"source_boundary": "signal_to_btc_forecast", "forecast": forecast.to_metadata()}
    target_payload = {
        "source_boundary": "forecast_to_target_position_no_order_intent",
        "target": {
            "target_position_id": target.target_position_id,
            "timestamp_utc": target.timestamp_utc.isoformat(),
            "strategy_id": target.strategy_id,
            "symbol": target.symbol,
            "target_weight": target.target_weight,
            "target_quantity": target.target_quantity,
            "signal_id": target.signal_id,
            "metadata": target.metadata,
        },
    }
    cost_gate_payload = {
        "source_boundary": "cost_gate_to_order_intent_no_broker_submit",
        "approved": cost_decision.approved,
        "blockers": cost_decision.blockers,
        "metadata": cost_decision.metadata,
    }
    order_intent_payload = {
        "source_boundary": "cost_gate_to_order_intent_no_broker_submit",
        "order_intent": None if cost_decision.order_intent is None else {
            "order_intent_id": cost_decision.order_intent.order_intent_id,
            "client_order_id": cost_decision.order_intent.client_order_id,
            "timestamp_utc": cost_decision.order_intent.timestamp_utc.isoformat(),
            "strategy_id": cost_decision.order_intent.strategy_id,
            "symbol": cost_decision.order_intent.symbol,
            "side": cost_decision.order_intent.side.value,
            "quantity": cost_decision.order_intent.quantity,
            "order_type": cost_decision.order_intent.order_type.value,
            "time_in_force": cost_decision.order_intent.time_in_force.value,
            "signal_id": cost_decision.order_intent.signal_id,
            "target_position_id": cost_decision.order_intent.target_position_id,
            "metadata": cost_decision.order_intent.metadata,
        },
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    }
    artifact_stem = _artifact_stem(str(cycle["timestamp"]))
    paths = {
        "signal_artifact": _write_chain_artifact(root, artifacts_dir / f"{artifact_stem}_signal.json", signal_payload),
        "forecast_artifact": _write_chain_artifact(root, artifacts_dir / f"{artifact_stem}_forecast.json", forecast_payload),
        "target_artifact": _write_chain_artifact(root, artifacts_dir / f"{artifact_stem}_target.json", target_payload),
        "cost_gate_artifact": _write_chain_artifact(root, artifacts_dir / f"{artifact_stem}_cost_gate.json", cost_gate_payload),
        "order_intent_artifact": _write_chain_artifact(root, artifacts_dir / f"{artifact_stem}_order_intent.json", order_intent_payload),
        "paper_oms_lifecycle_artifact": _write_chain_artifact(root, artifacts_dir / f"{artifact_stem}_paper_oms_lifecycle.json", oms_payload),
    }
    return {
        **paths,
        "forecast_source_boundary": "signal_to_btc_forecast",
        "target_source_boundary": "forecast_to_target_position_no_order_intent",
        "order_intent_source_boundary": "cost_gate_to_order_intent_no_broker_submit",
        "paper_oms_source_boundary": "btc_paper_oms_lifecycle",
        "order_intent_approved": cost_decision.approved,
        "order_required": oms_payload["order_required"],
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    }


def _override_target_to_raw_trend_exposure(target: Any, target_exposure: float, equity: float, close: float) -> Any:
    metadata = dict(target.metadata)
    metadata["raw_trend_target_override"] = {
        "source": "btc_trend_raw_forward_observation_roll",
        "reason": "preserve existing raw trend exposure semantics while routing through forecast/risk boundary",
        "target_exposure": target_exposure,
    }
    metadata["source_boundary"] = "forecast_to_target_position_no_order_intent"
    return type(target)(
        timestamp_utc=target.timestamp_utc,
        strategy_id=target.strategy_id,
        symbol=target.symbol,
        target_weight=float(target_exposure),
        target_quantity=float(equity) * float(target_exposure) / float(close),
        signal_id=target.signal_id,
        metadata=metadata,
        target_position_id=target.target_position_id,
    )


def _write_chain_artifact(root: Path, path: Path, payload: Mapping[str, Any]) -> str:
    _write_json(path, payload)
    return _relpath(path, root)


def _artifact_stem(value: str) -> str:
    return value.replace(":", "").replace("+", "").replace("/", "_").replace("\\", "_")


def _parse_utc(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": "BLOCKED",
        "cycle_status": "NOT_RUN",
        "asset": "btc",
        "symbol": SYMBOL,
        "strategy_id": EXPECTED_STRATEGY_ID,
        "family_id": EXPECTED_PRIMARY_FAMILY,
        "candidate_id": EXPECTED_PRIMARY_CANDIDATE,
        "ledger_root": str(ledger).replace("\\", "/"),
        "readiness": _readiness_summary(readiness),
        "guardrails": _guardrails(),
        "blockers": _dedupe(blockers),
        "output": str(output_path).replace("\\", "/"),
    }


def _readiness_summary(readiness: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": str(readiness.get("status", "")),
        "readiness_type": str(readiness.get("readiness_type", "")),
        "strategy_id": str(readiness.get("strategy_id", "")),
        "blockers": [str(item) for item in readiness.get("blockers", []) if item],
    }


def _guardrails() -> dict[str, Any]:
    return {
        "simulated_only": True,
        "forward_observation_is_not_alpha_validation": True,
        "paper_candidate_ready_not_implied": True,
        "paper_runner_started": False,
        "broker_calls_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
        "volatility_position_branch_used": False,
        "multi_timeframe_confluence_used": False,
        "parameter_tuning_used": False,
        "do_not_reuse_5m_hft_ledger": True,
        "do_not_reuse_old_trend_paper_ledger": True,
    }


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str))
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
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


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


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one BTC raw trend forward-observation cycle.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--top-validation-report", default=str(DEFAULT_TOP_VALIDATION_REPORT))
    parser.add_argument("--raw-plan-report", default=str(DEFAULT_RAW_PLAN_REPORT))
    parser.add_argument("--volatility-freeze-report", default=str(DEFAULT_VOLATILITY_FREEZE_REPORT))
    parser.add_argument("--five-minute-freeze-report", default=str(DEFAULT_5M_FREEZE_REPORT))
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--as-of", default="")
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_btc_trend_raw_forward_observation_roll(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir),
        ledger_root=Path(args.ledger_root),
        top_validation_report=Path(args.top_validation_report),
        raw_plan_report=Path(args.raw_plan_report),
        volatility_freeze_report=Path(args.volatility_freeze_report),
        five_minute_freeze_report=Path(args.five_minute_freeze_report),
        readiness_report=Path(args.readiness_report),
        output=Path(args.output),
        as_of=args.as_of,
        initial_capital=args.initial_capital,
        fee_bps=args.fee_bps,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])
    raise SystemExit(0 if payload.get("status") == "PASS" else 2)


if __name__ == "__main__":
    main()
