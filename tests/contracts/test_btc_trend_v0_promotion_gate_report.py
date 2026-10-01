from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.build_btc_trend_v0_promotion_gate_report import build_btc_trend_v0_promotion_gate_report


def test_btc_trend_v0_promotion_gate_blocks_insufficient_robustness(tmp_path: Path) -> None:
    robustness = tmp_path / "robustness.json"
    ledger = tmp_path / "ledger.csv"
    freeze = tmp_path / "freeze.json"
    robustness.write_text(
        json.dumps(
            {
                "status": "insufficient_history",
                "data": {"daily_rows": 400, "start": "2020-01-01T00:00:00Z", "end": "2021-02-03T00:00:00Z"},
                "guardrails": {
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "broker_calls_allowed": False,
                },
                "default_performance": [],
                "yearly_performance": [],
                "cost_stress": [],
            }
        ),
        encoding="utf-8",
    )
    ledger.write_text("timestamp,strategy_id,close,daily_return,raw_signal,signal_timestamp,effective_timestamp,exposure,turnover,cost_bps,strategy_daily_return,equity,reason\n", encoding="utf-8")
    _write_locked_freeze(freeze)

    payload = build_btc_trend_v0_promotion_gate_report(
        repo_root=tmp_path,
        robustness_report=robustness,
        position_ledger=ledger,
        freeze_report=freeze,
        output=tmp_path / "gate.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "rejected"
    assert payload["gate_type"] == "paper_operational_readiness_gate"
    assert payload["paper_candidate_ready"] is False
    assert payload["paper_candidate_ready_is_strategy_validation"] is False
    assert payload["guardrails"]["paper_candidate_ready_is_not_alpha_validation"] is True
    assert payload["guardrails"]["strategy_validation_gate_required_before_strategy_claims"] is True
    assert payload["selected_candidate"] == {}
    assert "btc_trend_v0_robustness_insufficient_history" in payload["blockers"]
    assert "btc_trend_v0_daily_rows_below_1095" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["do_not_reuse_5m_hft_ledger"] is True


def test_btc_trend_v0_promotion_gate_detects_lookahead_ledger(tmp_path: Path) -> None:
    robustness = tmp_path / "robustness.json"
    ledger = tmp_path / "ledger.csv"
    freeze = tmp_path / "freeze.json"
    _write_passing_robustness(robustness)
    _write_locked_freeze(freeze)
    with ledger.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "strategy_id",
                "close",
                "daily_return",
                "raw_signal",
                "signal_timestamp",
                "effective_timestamp",
                "exposure",
                "turnover",
                "cost_bps",
                "strategy_daily_return",
                "equity",
                "reason",
            ],
        )
        writer.writeheader()
        for strategy_id in [
            "buy_hold_btc",
            "fixed_50pct_btc",
            "ma120_200_trend_intended",
            "ma120_200_trend_vol_target_intended",
            "twelve_month_momentum_intended",
        ]:
            writer.writerow(
                {
                    "timestamp": "2026-01-02T00:00:00Z",
                    "strategy_id": strategy_id,
                    "close": "100",
                    "daily_return": "0.01",
                    "raw_signal": "1",
                    "signal_timestamp": "2026-01-02T00:00:00Z",
                    "effective_timestamp": "2026-01-02T00:00:00Z",
                    "exposure": "1",
                    "turnover": "1",
                    "cost_bps": "5",
                    "strategy_daily_return": "0.0095",
                    "equity": "10095",
                    "reason": "exposure_changed_from_prior_effective_signal",
                }
            )

    payload = build_btc_trend_v0_promotion_gate_report(
        repo_root=tmp_path,
        robustness_report=robustness,
        position_ledger=ledger,
        freeze_report=freeze,
        output=tmp_path / "gate.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "rejected"
    assert payload["paper_candidate_ready"] is False
    assert payload["ledger_audit"]["lookahead_pass"] is False
    assert "btc_trend_v0_position_ledger_lookahead_failed" in payload["blockers"]


def test_btc_trend_v0_promotion_gate_requires_5m_freeze_lock(tmp_path: Path) -> None:
    robustness = tmp_path / "robustness.json"
    ledger = tmp_path / "ledger.csv"
    freeze = tmp_path / "freeze.json"
    _write_passing_robustness(robustness)
    ledger.write_text("timestamp,strategy_id,close,daily_return,raw_signal,signal_timestamp,effective_timestamp,exposure,turnover,cost_bps,strategy_daily_return,equity,reason\n", encoding="utf-8")
    freeze.write_text(
        json.dumps(
            {
                "status": "frozen_rejected_as_high_frequency",
                "guardrails": {"parameter_tuning_allowed": True},
            }
        ),
        encoding="utf-8",
    )

    payload = build_btc_trend_v0_promotion_gate_report(
        repo_root=tmp_path,
        robustness_report=robustness,
        position_ledger=ledger,
        freeze_report=freeze,
        output=tmp_path / "gate.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "rejected"
    assert payload["paper_candidate_ready"] is False
    assert "btc_5m_hft_freeze_not_locked" in payload["blockers"]


def _write_locked_freeze(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "frozen_rejected_as_high_frequency",
                "guardrails": {
                    "parameter_tuning_allowed": False,
                    "reuse_as_hft_candidate_allowed": False,
                    "paper_or_live_unlock_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_passing_robustness(path: Path) -> None:
    candidates = [
        "ma120_200_trend_intended",
        "ma120_200_trend_vol_target_intended",
        "twelve_month_momentum_intended",
    ]
    default_performance = [
        {"strategy_id": "buy_hold_btc", "metrics": {"max_drawdown_abs_pct": 70.0}},
    ]
    for strategy_id in candidates:
        default_performance.append(
            {
                "strategy_id": strategy_id,
                "metrics": {
                    "total_return_pct": 50.0,
                    "max_drawdown_abs_pct": 30.0,
                },
            }
        )
    yearly = []
    for strategy_id in candidates:
        for year in range(2022, 2026):
            yearly.append({"strategy_id": strategy_id, "year": year, "acceptable": True})
    cost_stress = []
    for strategy_id in candidates:
        cost_stress.append(
            {
                "strategy_id": strategy_id,
                "cost_bps": 10.0,
                "metrics": {
                    "total_return_pct": 40.0,
                    "max_drawdown_abs_pct": 35.0,
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "status": "research_only",
                "data": {"daily_rows": 1200, "start": "2020-01-01T00:00:00Z", "end": "2023-04-14T00:00:00Z"},
                "guardrails": {
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "broker_calls_allowed": False,
                },
                "default_performance": default_performance,
                "yearly_performance": yearly,
                "cost_stress": cost_stress,
            }
        ),
        encoding="utf-8",
    )
