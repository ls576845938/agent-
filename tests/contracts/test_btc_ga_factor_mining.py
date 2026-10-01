from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.research.ga_factor_mining import (
    DSLValidationError,
    FactorExpression,
    build_research_frame,
    build_walk_forward_splits,
    evaluate_expression,
    rolling_zscore,
    run_btc_ga_factor_mining,
)


TS = datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_dsl_rejects_unknown_operator_without_eval_surface() -> None:
    frame, rows, decision_time = _synthetic_inputs(180)
    research, _ = build_research_frame(market_frame=frame, derivative_rows=rows, decision_time=decision_time)
    expr = FactorExpression(op="__import__('os').system('echo unsafe')")

    with pytest.raises(DSLValidationError):
        evaluate_expression(expr, research)


def test_derivative_rows_after_decision_time_are_not_visible() -> None:
    frame, rows, decision_time = _synthetic_inputs(80)
    future_row = dict(rows[10])
    future_row["event_time"] = (decision_time - timedelta(hours=5)).isoformat()
    future_row["available_time"] = (decision_time + timedelta(hours=1)).isoformat()
    future_row["open_interest_usd"] = 999_999_999.0

    research, coverage = build_research_frame(
        market_frame=frame,
        derivative_rows=[future_row],
        decision_time=decision_time,
    )

    assert coverage["derivatives_total_rows"] == 1
    assert coverage["derivatives_visible_rows"] == 0
    assert 999_999_999.0 not in set(research["open_interest_usd"].dropna())


def test_derivative_alias_fields_are_normalized_before_join() -> None:
    frame, rows, decision_time = _synthetic_inputs(120)
    alias_rows = []
    for row in rows:
        alias_rows.append(
            {
                "event_time": row["event_time"],
                "available_time": row["available_time"],
                "ingested_at": row["ingested_at"],
                "processed_at": row["processed_at"],
                "venue": row["venue"],
                "symbol": row["symbol"],
                "source_provider": row["source_provider"],
                "is_final": row["is_final"],
                "sumOpenInterestValue": row["open_interest_usd"],
                "fundingRate": row["funding_rate"],
                "longLiquidationUsd": row["long_liquidation_usd"],
                "shortLiquidationUsd": row["short_liquidation_usd"],
                "longShortRatio": row["long_short_ratio"],
                "source_raw_payload_hash": row["source_raw_payload_hash"],
            }
        )

    research, coverage = build_research_frame(
        market_frame=frame,
        derivative_rows=alias_rows,
        decision_time=decision_time,
    )

    assert coverage["derivatives_alignment_status"] == "value_fields_present"
    assert coverage["field_non_null_counts_raw_visible"]["open_interest_usd"] > 0
    assert coverage["field_non_null_counts_after_join"]["funding_rate"] > 0
    assert research["long_short_ratio"].notna().sum() > 0


def test_ga_blocks_when_derivatives_have_values_but_no_market_time_overlap(tmp_path: Path) -> None:
    frame, rows, decision_time = _synthetic_inputs(520)
    shifted_rows = []
    for row in rows:
        shifted = dict(row)
        shifted["event_time"] = (datetime.fromisoformat(str(row["event_time"])) + timedelta(days=60)).isoformat()
        shifted["available_time"] = (datetime.fromisoformat(str(row["available_time"])) + timedelta(days=60)).isoformat()
        shifted_rows.append(shifted)
    shifted_decision_time = decision_time + timedelta(days=60)

    payload = run_btc_ga_factor_mining(
        output_root=tmp_path,
        market_frame=frame,
        derivative_rows=shifted_rows,
        decision_time=shifted_decision_time,
        lookback_hours=480,
        seed=11,
        population_size=10,
        generations=2,
        max_candidates=3,
    )

    assert payload["status"] == "blocked"
    assert "btc_ga_factor_mining_derivatives_alignment_no_market_derivatives_time_overlap" in payload["blockers"]
    assert payload["data_coverage"]["field_non_null_counts_raw_visible"]["open_interest_usd"] > 0
    assert payload["data_coverage"]["derivatives_market_overlap_rows"] == 0
    assert payload["ga_config"]["trial_count"] == 0
    assert payload["promotion"]["paper_candidate_generated"] is False


def test_rolling_zscore_uses_only_historical_window_not_full_sample() -> None:
    values = pd.Series([1.0 + (index % 5) * 0.1 for index in range(30)] + [100.0] * 5)
    full = rolling_zscore(values, 12)
    prefix = rolling_zscore(values.iloc[:20], 12)

    assert full.iloc[19] == pytest.approx(prefix.iloc[-1], abs=1e-12)


def test_walk_forward_splits_have_embargo_between_train_and_validation() -> None:
    splits = build_walk_forward_splits(480, fold_count=4, embargo_hours=4)

    assert len(splits) == 4
    for split in splits:
        assert split.train_end <= split.validation_start - 4
        assert split.train_start == 0
        assert split.validation_end > split.validation_start


def test_ga_factor_mining_fixed_seed_is_reproducible(tmp_path: Path) -> None:
    frame, rows, decision_time = _synthetic_inputs(520)

    first = run_btc_ga_factor_mining(
        output_root=tmp_path / "first",
        market_frame=frame,
        derivative_rows=rows,
        decision_time=decision_time,
        lookback_hours=480,
        seed=20260627,
        population_size=16,
        generations=3,
        max_candidates=5,
    )
    second = run_btc_ga_factor_mining(
        output_root=tmp_path / "second",
        market_frame=frame,
        derivative_rows=rows,
        decision_time=decision_time,
        lookback_hours=480,
        seed=20260627,
        population_size=16,
        generations=3,
        max_candidates=5,
    )

    assert first["status"] == "complete"
    assert second["status"] == "complete"
    assert _expression_hashes(first) == _expression_hashes(second)
    assert first["ga_config"]["trial_count"] == second["ga_config"]["trial_count"]


def test_ga_factor_mining_report_contains_gate_metrics_and_safety_flags(tmp_path: Path) -> None:
    frame, rows, decision_time = _synthetic_inputs(520)

    payload = run_btc_ga_factor_mining(
        output_root=tmp_path,
        market_frame=frame,
        derivative_rows=rows,
        decision_time=decision_time,
        lookback_hours=480,
        seed=7,
        population_size=14,
        generations=3,
        max_candidates=4,
    )

    assert validate_btc_artifact_schema(payload) == []
    assert payload["decision"] == "research_only_expression_review"
    assert payload["ga_config"]["trial_count"] > 0
    assert payload["ga_config"]["selected_candidate_count"] > 0
    assert payload["walk_forward"]["fold_count"] == 4
    assert "oos_stability" in payload["walk_forward"]
    assert payload["promotion"]["paper_candidate_generated"] is False
    assert payload["promotion"]["live_status"] == "FROZEN"
    assert payload["safety"]["broker_calls_allowed"] is False
    assert payload["safety"]["order_endpoints_allowed"] is False
    assert "base" in payload["top_candidates"][0]["cost_stress"]
    assert "max_drawdown" in payload["top_candidates"][0]["validation_metrics"]
    assert (tmp_path / "ga_factor_mining_report.json").exists()
    assert (tmp_path / "candidate_factor_expressions.json").exists()
    assert (tmp_path / "paper_live_safety_status.json").exists()


def test_ga_factor_mining_confirmatory_holdout_is_diagnostic_only(tmp_path: Path) -> None:
    frame, rows, decision_time = _synthetic_inputs(620)

    payload = run_btc_ga_factor_mining(
        output_root=tmp_path,
        market_frame=frame,
        derivative_rows=rows,
        decision_time=decision_time,
        lookback_hours=560,
        seed=17,
        population_size=14,
        generations=3,
        max_candidates=4,
        confirmatory_holdout_hours=72,
    )

    holdout = payload["confirmatory_holdout"]
    assert payload["status"] == "complete"
    assert holdout["enabled"] is True
    assert holdout["ga_selection_used_holdout"] is False
    assert holdout["holdout_rows"] == 72
    assert holdout["selection_rows"] == 488
    assert holdout["paper_queue_write_allowed"] is False
    assert holdout["live_unlock_allowed"] is False
    assert holdout["baseline_rows"]
    assert "candidate_rows" in holdout
    if holdout["candidate_rows"]:
        row = holdout["candidate_rows"][0]
        assert "trend_baseline_comparison" in row or row.get("status") == "blocked"
        if "regime_attribution" in row:
            assert "by_trend_regime" in row["regime_attribution"]
    assert payload["funding_timestamp_cost_audit"]["paper_queue_write_allowed"] is False
    assert payload["funding_timestamp_cost_audit"]["live_unlock_allowed"] is False


def _expression_hashes(payload: dict) -> list[str]:
    return [str(item["expression_hash"]) for item in payload["top_candidates"]]


def _synthetic_inputs(rows: int) -> tuple[pd.DataFrame, list[dict[str, object]], datetime]:
    index = pd.date_range(TS, periods=rows, freq="1h", tz="UTC")
    x = np.arange(rows, dtype=float)
    close = 60_000.0 + x * 8.0 + np.sin(x / 9.0) * 500.0
    open_ = close - np.sin(x / 7.0) * 40.0
    high = np.maximum(open_, close) + 80.0
    low = np.minimum(open_, close) - 80.0
    volume = 100.0 + (np.cos(x / 11.0) + 1.5) * 20.0
    market = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )
    derivative_rows = []
    for i, ts in enumerate(index):
        derivative_rows.append(
            {
                "event_time": ts.isoformat(),
                "available_time": (ts + timedelta(minutes=5)).isoformat(),
                "ingested_at": (ts + timedelta(minutes=6)).isoformat(),
                "processed_at": (ts + timedelta(minutes=7)).isoformat(),
                "venue": "okx_swap",
                "symbol": "BTCUSDT",
                "source_provider": "okx_free_public_fixture",
                "is_final": True,
                "open_interest_usd": 2_000_000_000.0 + i * 2_000_000.0 + np.sin(i / 5.0) * 10_000_000.0,
                "funding_rate": 0.00004 + np.sin(i / 17.0) * 0.00001,
                "long_liquidation_usd": max(0.0, np.sin(i / 13.0)) * 100_000.0,
                "short_liquidation_usd": max(0.0, np.cos(i / 13.0)) * 100_000.0,
                "long_short_ratio": 1.2 + np.sin(i / 15.0) * 0.2,
                "source_raw_payload_hash": "a" * 64,
            }
        )
    decision_time = index[-1].to_pydatetime() + timedelta(minutes=5)
    return market, derivative_rows, decision_time
