from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.research.compare_btc_timesfm_vs_trend_baseline import (
    directional_accuracy,
    evaluate_score,
    max_drawdown,
    rank_ic,
    select_decision_points,
)


def test_select_decision_points_keeps_lookback_and_future_horizon_visible() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for idx in range(200):
        rows.append(
            {
                "close_time_utc": base + timedelta(hours=idx),
                "close": 100.0 + idx,
            }
        )
    decisions = select_decision_points(
        rows,
        lookback_hours=72,
        horizon_hours=24,
        holdout_days=10,
        stride_hours=24,
        max_decisions=5,
    )

    assert decisions
    for decision in decisions:
        assert decision.row_index >= 71
        assert decision.row_index + 24 < len(rows)
        assert decision.future_time_utc > decision.decision_time_utc


def test_evaluate_score_calibrates_threshold_before_evaluation() -> None:
    calibration_rows = [
        {"score": 0.1, "future_return": 0.01, "decision_time_utc": "2026-01-01T00:00:00+00:00"},
        {"score": 0.2, "future_return": 0.02, "decision_time_utc": "2026-01-02T00:00:00+00:00"},
        {"score": 0.3, "future_return": 0.03, "decision_time_utc": "2026-01-03T00:00:00+00:00"},
    ]
    evaluation_rows = [
        {"score": 0.4, "future_return": 0.04, "decision_time_utc": "2026-01-04T00:00:00+00:00"},
        {"score": -0.2, "future_return": -0.02, "decision_time_utc": "2026-01-05T00:00:00+00:00"},
        {"score": 0.5, "future_return": 0.03, "decision_time_utc": "2026-01-06T00:00:00+00:00"},
    ]

    metrics = evaluate_score(
        model_id="unit",
        score_field="score",
        calibration_rows=calibration_rows,
        evaluation_rows=evaluation_rows,
        fee_bps=5.0,
        slippage_bps=4.0,
    )

    assert metrics["status"] == "complete"
    assert metrics["calibration"]["rows"] == 3
    assert metrics["evaluation"]["rows"] == 3
    assert metrics["calibration"]["threshold_q70_after_direction"] < 0.4
    assert metrics["evaluation"]["profit_factor"] > 1.0
    assert metrics["cost_stress"]["costs_2x"]["cost_bps"] == 18.0


def test_metric_helpers_are_deterministic() -> None:
    score = [1.0, 2.0, -1.0, -2.0]
    label = [0.02, 0.04, -0.01, -0.03]

    assert rank_ic(score, label) == 1.0
    assert directional_accuracy(score, label) == 1.0
    assert max_drawdown([0.01, -0.02, 0.03]) < 0.0
