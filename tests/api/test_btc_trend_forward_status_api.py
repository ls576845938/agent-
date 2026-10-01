from __future__ import annotations

import json
from pathlib import Path

from backend.app.api.app_factory import _btc_trend_forward_status_payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_btc_trend_forward_status_payload_reads_artifacts_without_live_unlock(tmp_path: Path) -> None:
    latest = tmp_path / "artifacts/btc_trend_v0/latest"
    ledger_root = tmp_path / "data/forward_observation/btc_trend_raw_v1"
    hft_latest = tmp_path / "artifacts/btc_paper_readiness/latest"
    latest.mkdir(parents=True)
    ledger_root.mkdir(parents=True)
    hft_latest.mkdir(parents=True)

    _write_json(
        latest / "btc_trend_raw_forward_observation_daily_run_report.json",
        {
            "status": "PASS",
            "generated_at": "2026-06-23T12:47:20Z",
            "data": {"daily_rows": 1826, "sample_start": "2021-06-24T00:00:00Z", "sample_end": "2026-06-23T00:00:00Z"},
            "steps": {
                "data_refresh": {"status": "verified"},
                "readiness": {"status": "PASS"},
                "roll": {"status": "PASS"},
            },
            "forward_observation": {"cycle_status": "SKIPPED_ALREADY_COMPLETED", "evaluation_status": "raw_forward_observing"},
        },
    )
    _write_json(
        latest / "btc_trend_v0_strategy_validation_gate_report.json",
        {
            "status": "strategy_backtest_validated",
            "decision": "backtest_evidence_passed_internal_gate_manual_review_still_required",
            "selected_metrics": {"total_return_pct": 253.7, "max_drawdown_abs_pct": 28.1, "sharpe_ratio": 0.94},
            "buy_hold_metrics": {"total_return_pct": 81.3, "max_drawdown_abs_pct": 76.6, "sharpe_ratio": 0.49},
        },
    )
    _write_json(latest / "btc_trend_v0_promotion_gate_report.json", {"status": "paper_candidate_ready"})
    _write_json(
        latest / "btc_trend_raw_forward_observation_evaluation_report.json",
        {
            "status": "raw_forward_observing",
            "minimum_complete_days": 30,
            "metrics": {
                "observation_days": 1,
                "target_position_count": 1,
                "target_position_change_count": 0,
                "simulated_fill_count": 0,
                "total_return_pct": 0,
                "max_drawdown_abs_pct": 0,
                "milestone_progress": {"30": False, "60": False, "90": False},
                "final_equity": 25000,
            },
        },
    )
    _write_json(
        latest / "btc_trend_raw_forward_observation_roll_report.json",
        {
            "cycle": {
                "timestamp": "2026-06-23T00:00:00Z",
                "close": 62325,
                "raw_signal": 0,
                "target_exposure": 0,
                "signal_timestamp": "2026-06-22T00:00:00Z",
                "effective_timestamp": "2026-06-23T00:00:00Z",
                "reason": "t01_365d_momentum_non_positive_t_plus_1",
            }
        },
    )
    _write_json(latest / "btc_trend_volatility_position_freeze_report.json", {"status": "frozen_deferred_not_primary"})
    _write_json(hft_latest / "btc_5m_hft_freeze_report.json", {"status": "frozen_rejected_as_high_frequency"})
    _write_json(
        ledger_root / "validation_state.json",
        {"current_equity": 25000, "private_endpoint_used": False, "order_endpoint_used": False, "live_order_allowed": False},
    )
    (ledger_root / "target_positions.jsonl").write_text(
        json.dumps({"timestamp": "2026-06-23T00:00:00Z", "target_exposure": 0, "reason": "t01_365d_momentum_non_positive_t_plus_1"}) + "\n",
        encoding="utf-8",
    )
    (ledger_root / "portfolio_snapshots.jsonl").write_text(
        json.dumps({"timestamp": "2026-06-23T00:00:00Z", "equity": 25000, "reconciliation_status": "clean"}) + "\n",
        encoding="utf-8",
    )
    (ledger_root / "fills.jsonl").write_text("", encoding="utf-8")
    (latest / "btc_trend_v0_position_ledger.csv").write_text(
        "\n".join(
            [
                "timestamp,strategy_id,close,exposure,equity",
                "2026-06-22T00:00:00Z,buy_hold_btc,64027.6,1,45000",
                "2026-06-22T00:00:00Z,twelve_month_momentum_intended,64027.6,0,88000",
                "2026-06-23T00:00:00Z,buy_hold_btc,62325.0,1,43800",
                "2026-06-23T00:00:00Z,twelve_month_momentum_intended,62325.0,0,88000",
            ]
        ),
        encoding="utf-8",
    )

    payload = _btc_trend_forward_status_payload(tmp_path)

    assert payload["status"] == "ok"
    assert payload["missing_sources"] == []
    assert payload["daily_run"]["roll_cycle_status"] == "SKIPPED_ALREADY_COMPLETED"
    assert payload["strategy"]["candidate_id"] == "t01_momentum_binary_8e09e94c36"
    assert payload["current_signal"]["effective_timestamp"] == "2026-06-23T00:00:00Z"
    assert payload["forward_observation"]["observation_days"] == 1
    assert payload["gates"]["private_endpoint_used"] is False
    assert payload["gates"]["order_endpoint_used"] is False
    assert payload["gates"]["live_order_allowed"] is False
    assert len(payload["charts"]["strategy_series"]) == 2
    assert payload["source_files"]["ledger_root"] == "data/forward_observation/btc_trend_raw_v1"


def test_btc_trend_forward_status_payload_is_partial_when_artifacts_are_missing(tmp_path: Path) -> None:
    payload = _btc_trend_forward_status_payload(tmp_path)

    assert payload["status"] == "partial"
    assert "daily_run" in payload["missing_sources"]
    assert payload["gates"]["live_order_allowed"] is False
