"""Event-ledger validation for BTC liquidation-shock recovery skeleton.

This module promotes the research skeleton only into candidate validation. It
does not create paper/live readiness, call brokers, or generate real orders.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from quant_us.research.btc_canonical import (
    build_canonical_report,
    build_trade_attribution,
    cost_stress_for_signal,
    evaluate_canonical_gate,
    git_commit_hash,
    regime_report_from_trades,
    rolling_walk_forward_for_signal,
    stable_hash,
    summarize_trade_attribution,
    write_json,
)
from quant_us.research.btc_compression_expansion_validation import (
    _fills_to_trade_ledger_diagnostic,
    _pbo_dsr_warnings,
    _run_event,
    ledger_segments_from_signal,
    time_exit_long_only_signal,
)
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_liquidation_shock_recovery import DEFAULT_CONFIG_PATH as HYPOTHESIS_CONFIG_PATH
from quant_us.research.btc_liquidation_shock_recovery import build_event_table, load_config as load_hypothesis_config


BTC_LIQUIDATION_SHOCK_VALIDATION_RUN_ID = "20260516T234000Z_liquidation_shock_eventledger"
BTC_LIQUIDATION_SHOCK_VALIDATION_ROOT = Path("artifacts/btc_candidate_validation")
DEFAULT_VALIDATION_CONFIG_PATH = Path("configs/btc/candidate_validation/liquidation_shock_recovery_v1_event_ledger.yaml")
SOURCE_HYPOTHESIS_RUN_DIR = Path("artifacts/btc_hypothesis/20260516T232000Z_liquidation_shock_recovery")


def load_validation_config(path: str | Path = DEFAULT_VALIDATION_CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"validation config must be a mapping: {path}")
    return payload


def run_liquidation_shock_event_ledger_validation(
    *,
    run_id: str = BTC_LIQUIDATION_SHOCK_VALIDATION_RUN_ID,
    config_path: str | Path = DEFAULT_VALIDATION_CONFIG_PATH,
    output_root: Path = BTC_LIQUIDATION_SHOCK_VALIDATION_ROOT,
) -> Path:
    config = load_validation_config(config_path)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    start = frame.index[0].to_pydatetime()
    end = frame.index[-1].to_pydatetime()
    strategy_id = str(config["strategy_id"])
    params = dict(config.get("params", {}))
    signal, diagnostics = liquidation_shock_signal(frame, params)
    event = _run_event(frame=frame, signal=signal, strategy_id=strategy_id, params=params, start=start, end=end, run_dir=run_dir)
    trades = ledger_segments_from_signal(
        run_id=run_id,
        strategy_id=strategy_id,
        frame=frame,
        signal=signal,
        manifest_path=Path(str(event["manifest_path"])),
    )
    trades.to_csv(run_dir / "trade_ledger.csv", index=False)
    fill_trades = _fills_to_trade_ledger_diagnostic(event["fills"], run_id=run_id, strategy_id=strategy_id)
    fill_trades.to_csv(run_dir / "fill_trade_ledger_diagnostic.csv", index=False)
    attribution = build_trade_attribution(
        run_id=run_id,
        strategy_id=strategy_id,
        frame=frame,
        trades=trades,
        signal=signal,
        diagnostics=diagnostics,
    )
    attribution.to_csv(run_dir / "trade_attribution.csv", index=False)
    write_json(run_dir / "trade_attribution_summary.json", summarize_trade_attribution(attribution))
    cost_stress = cost_stress_for_signal(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
    )
    walk_forward = rolling_walk_forward_for_signal(
        frame=frame,
        signal_builder=lambda local_frame, local_params: liquidation_shock_signal(local_frame, local_params),
        strategy_id=strategy_id,
        params=params,
        run_dir=run_dir,
        windows=4,
    )
    regime_report = regime_report_from_trades(frame, trades)
    report = build_canonical_report(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_version=f"{strategy_id}:event_ledger_candidate_validation_v1",
        params=params,
        frame=frame,
        signal=signal,
        diagnostics=diagnostics,
        event=event,
        trades=trades,
        cost_stress=cost_stress,
        walk_forward=walk_forward,
        regime_report=regime_report,
        config_hash=stable_hash(config),
    )
    gate = evaluate_canonical_gate(report)
    report["gate_decision"] = gate.to_dict()
    report["promotion_gate_status"] = gate.status
    report["fail_reasons"] = gate.fail_reasons
    write_json(run_dir / "canonical_backtest_report.json", report)
    write_json(run_dir / "gate_inputs.json", {"strategy_id": strategy_id, "report": report, "gate": gate.to_dict()})
    write_json(run_dir / "cost_stress_report.json", cost_stress)
    write_json(run_dir / "walk_forward_report.json", walk_forward)
    write_json(run_dir / "regime_report.json", regime_report)
    write_json(
        run_dir / "pbo_dsr_report.json",
        {
            "schema_version": "btc_candidate_pbo_dsr_report_v1",
            "strategy_id": strategy_id,
            "pbo": report["metrics"]["pbo"],
            "dsr": report["metrics"]["dsr"],
            "folds": walk_forward.get("windows", []),
            "warnings": _pbo_dsr_warnings(report["metrics"]),
        },
    )
    write_json(run_dir / "candidate_validation_result.json", _candidate_summary(report, gate.to_dict()))
    write_json(run_dir / "promotion_decision.json", _promotion_decision(run_id, gate.to_dict()))
    write_json(run_dir / "paper_live_safety_status.json", _paper_live_safety(run_id, gate.to_dict()))
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "btc_liquidation_shock_candidate_validation_manifest_v1",
            "run_id": run_id,
            "strategy_id": strategy_id,
            "source_hypothesis_run": str(SOURCE_HYPOTHESIS_RUN_DIR),
            "config_path": str(config_path),
            "config_hash": stable_hash(config),
            "code_commit": git_commit_hash(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_version": report["data_version"],
            "strategy_version": report["strategy_version"],
            "cost_model": report["cost_model_id"],
            "slippage_model": "crypto_slippage_4bps_base",
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    )
    return run_dir


def liquidation_shock_signal(frame: pd.DataFrame, params: Mapping[str, Any] | None = None) -> tuple[pd.Series, dict[str, pd.Series]]:
    cfg = {
        "time_exit_bars": 24,
        "cooldown_bars": 6,
        "signal_scale": 0.20,
        "min_reentry_delay_bars": 6,
        **dict(params or {}),
    }
    hypothesis_config = load_hypothesis_config(HYPOTHESIS_CONFIG_PATH)
    event_table = build_event_table(frame, hypothesis_config, drop_incomplete_labels=False)
    event_table["timestamp"] = pd.to_datetime(event_table["timestamp"], utc=True)
    index = pd.to_datetime(frame.index, utc=True)
    aligned = event_table.set_index("timestamp").reindex(index)
    entries = aligned["is_hypothesis_active"].fillna(False).astype(bool)
    signal = time_exit_long_only_signal(
        entries=entries,
        time_exit_bars=int(cfg["time_exit_bars"]),
        cooldown_bars=max(int(cfg["cooldown_bars"]), int(cfg.get("min_reentry_delay_bars", 0))),
        signal_scale=float(cfg["signal_scale"]),
    )
    diagnostics = {
        "liquidation_shock": aligned["liquidation_shock"].fillna(False).astype(float),
        "recent_liquidation_shock": aligned["recent_liquidation_shock"].fillna(False).astype(float),
        "recovery_confirmed": aligned["recovery_confirmed"].fillna(False).astype(float),
        "wick_recovery_score": pd.to_numeric(aligned["wick_recovery_score"], errors="coerce").fillna(0.0),
        "volume_ratio": pd.to_numeric(aligned["volume_ratio"], errors="coerce").fillna(1.0),
        "target_signal": signal,
        "raw_signal": signal,
    }
    for key, value in diagnostics.items():
        value.index = index
        diagnostics[key] = value
    return signal.reindex(index).fillna(0.0).clip(0.0, 1.0), diagnostics


def _candidate_summary(report: Mapping[str, Any], gate: Mapping[str, Any]) -> dict[str, Any]:
    metrics = report["metrics"]
    return {
        "schema_version": "btc_liquidation_shock_candidate_validation_result_v1",
        "run_id": report["run_id"],
        "strategy_id": report["strategy_id"],
        "status": gate["status"],
        "gate_passed": bool(gate["passed"]),
        "gate_fail_reasons": list(gate["fail_reasons"]),
        "metrics": {
            "profit_factor": metrics["profit_factor"],
            "event_profit_factor": metrics["event_profit_factor"],
            "sharpe": metrics["sharpe"],
            "max_drawdown": metrics["max_drawdown"],
            "annual_turnover": metrics["annual_turnover"],
            "walk_forward_pass_rate": metrics["walk_forward_pass_rate"],
            "regime_pass_rate": metrics["regime_pass_rate"],
            "pbo": metrics["pbo"],
            "dsr": metrics["dsr"],
            "trade_count": metrics["trade_count"],
            "fill_count": metrics["fill_count"],
        },
        "paper_queue": "LOCKED",
        "live": "FROZEN",
    }


def _promotion_decision(run_id: str, gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_liquidation_shock_promotion_decision_v1",
        "run_id": run_id,
        "candidate_gate_results": [gate],
        "paper_review": {
            "paper_review_queue_locked": True,
            "paper_review_pending": [],
            "paper_auto_start": False,
            "reason": "event_ledger_candidate_validation_only_manual_next_sprint_required",
        },
        "candidate_passed_internal_gate_count": 1 if bool(gate.get("passed", False)) else 0,
        "max_state": str(gate.get("status", "candidate_gate_failed")),
        "live_frozen": True,
        "forbidden_states": ["live_enabled", "live_ready", "paper_ready"],
    }


def _paper_live_safety(run_id: str, gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_liquidation_shock_paper_live_safety_v1",
        "run_id": run_id,
        "candidate_passed_internal_gate": 1 if bool(gate.get("passed", False)) else 0,
        "paper_queue": "LOCKED",
        "paper_queue_locked": True,
        "paper_auto_start": False,
        "live": "FROZEN",
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
    }


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
