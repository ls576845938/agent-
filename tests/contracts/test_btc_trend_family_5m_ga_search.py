from __future__ import annotations

import json
import random
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_crypto.research import trend_family_5m_ga_search as module
from quant_crypto.research.trend_family_5m_ga_search import (
    DirectionalEfficiencyGenome,
    SelectionPrefixError,
    TradingRangeBreakoutGenome,
    build_trend_events,
    crossover_within_family,
    load_immutable_selection_prefix,
    run_trend_family_search_on_selection_frame,
)


def _frame(rows: int = 9_000) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="5min", tz="UTC")
    phase = np.arange(rows, dtype=float)
    close = 30_000.0 * np.exp(phase * 0.000004 + np.sin(phase / 53.0) * 0.002)
    open_price = np.r_[close[0], close[:-1]]
    width = close * (0.0008 + 0.0002 * (1.0 + np.sin(phase / 17.0)))
    return pd.DataFrame(
        {
            "open": open_price,
            "high": np.maximum(open_price, close) + width,
            "low": np.minimum(open_price, close) - width,
            "close": close,
            "volume": 100.0 + np.cos(phase / 11.0),
        },
        index=index,
    )


def _breakout(**overrides: object) -> TradingRangeBreakoutGenome:
    values: dict[str, object] = {
        "channel_bars": 24,
        "retest_bars": 3,
        "exit_bars": 12,
        "atr_window_bars": 14,
        "entry_buffer_atr": 0.10,
        "retest_tolerance_atr": 0.25,
        "htf_fast_bars": 12,
        "htf_slow_bars": 48,
        "quality_threshold_atr": 0.5,
        "max_holding_bars": 24,
        "cooldown_bars": 6,
    }
    values.update(overrides)
    return TradingRangeBreakoutGenome(**values)


def _efficiency(**overrides: object) -> DirectionalEfficiencyGenome:
    values: dict[str, object] = {
        "efficiency_window_bars": 48,
        "efficiency_threshold": 0.35,
        "ema_fast_bars": 12,
        "ema_slow_bars": 48,
        "slope_lookback_bars": 6,
        "continuation_window_bars": 12,
        "exit_bars": 12,
        "atr_window_bars": 14,
        "entry_buffer_atr": 0.10,
        "max_holding_bars": 24,
        "cooldown_bars": 6,
    }
    values.update(overrides)
    return DirectionalEfficiencyGenome(**values)


def test_typed_genomes_hash_only_family_active_fields() -> None:
    breakout = _breakout()
    efficiency = _efficiency()
    assert breakout.family == "breakout_retest_continuation"
    assert efficiency.family == "directional_efficiency_continuation"
    assert "efficiency_window_bars" not in breakout.active_genes
    assert "channel_bars" not in efficiency.active_genes
    assert set(breakout.active_genes) == {item.name for item in fields(breakout)}
    assert set(efficiency.active_genes) == {item.name for item in fields(efficiency)}
    assert breakout.genome_hash != efficiency.genome_hash


def test_crossover_is_family_local_and_cross_family_is_rejected() -> None:
    left = _breakout(channel_bars=12)
    right = _breakout(channel_bars=48)
    child = crossover_within_family(left, right, random.Random(7))
    assert isinstance(child, TradingRangeBreakoutGenome)
    assert child.channel_bars in {12, 48}
    with pytest.raises(module.TrendFamilySearchError, match="cross_family"):
        crossover_within_family(left, _efficiency(), random.Random(7))


@pytest.mark.parametrize("genome", [_breakout(), _efficiency()])
def test_family_events_are_causal(genome: object) -> None:
    frame = _frame(3_000)
    changed = frame.copy()
    cutoff = 2_400
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("close")] *= 1.2
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("high")] *= 1.3
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("low")] *= 0.7
    original = build_trend_events(frame, genome)
    mutated = build_trend_events(changed, genome)
    pd.testing.assert_frame_equal(original.iloc[: cutoff + 1], mutated.iloc[: cutoff + 1])


def test_full_qcv2r1_partition_is_rejected_before_payload_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "shared_dataset_manifest_v1",
                "dataset_id": "btc-market-data-sqlite-snapshot",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_decode_selection_prefix", lambda *_: pytest.fail("opened full partition"))
    with pytest.raises(SelectionPrefixError, match="selection_prefix_role_required"):
        load_immutable_selection_prefix(manifest)


def test_fold_evaluation_resets_flat_and_counts_validation_entries_only() -> None:
    frame = _frame()
    report = run_trend_family_search_on_selection_frame(
        frame=frame,
        data_provenance={"payload_role": "selection_prefix", "row_count": len(frame)},
        output_root=None,
        seed=11,
        population_per_family=8,
        generations=1,
        fold_count=2,
        prior_unique_evaluations=1_587,
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )
    for candidate in report["top_candidates"]:
        for fold in candidate["walk_forward"]:
            assert fold["flat_at_fold_start"] is True
            assert fold["entries_counted_before_validation"] == 0
            assert set(fold["cost_scenarios"]) == {"base", "conservative", "stress"}


def test_search_is_selection_only_and_negative_control_cannot_win(tmp_path: Path) -> None:
    frame = _frame()
    report = run_trend_family_search_on_selection_frame(
        frame=frame,
        data_provenance={"payload_role": "selection_prefix", "row_count": len(frame)},
        output_root=tmp_path / "run",
        seed=13,
        population_per_family=8,
        generations=1,
        fold_count=2,
        prior_unique_evaluations=1_587,
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )
    assert report["validation_design"]["selection_only"] is True
    assert report["validation_design"]["holdout_bytes_read"] == 0
    assert report["validation_design"]["holdout_rows_decoded"] == 0
    assert report["validation_design"]["holdout_strategy_metrics_read"] is False
    assert report["candidate_lock"]["reveal_authorized"] is False
    assert report["negative_control"]["eligible_for_selection"] is False
    assert all(row["family"] != "fixed_ma_crossover_negative_control" for row in report["top_candidates"])
    assert report["search_protocol"]["prior_unique_evaluations"] == 1_587
    assert report["search_protocol"]["run_unique_evaluations"] <= 300
    assert report["search_protocol"]["cumulative_unique_evaluations"] <= 1_887
    assert report["safety"]["private_endpoints_allowed"] is False
    assert report["safety"]["order_endpoints_allowed"] is False


def test_fixed_sizing_and_risk_are_outside_all_genomes() -> None:
    forbidden = {
        "max_leverage", "max_abs_position", "daily_loss_limit_pct",
        "max_strategy_loss_pct", "no_trade_band", "rebalance_interval_bars",
    }
    assert forbidden.isdisjoint({item.name for item in fields(TradingRangeBreakoutGenome)})
    assert forbidden.isdisjoint({item.name for item in fields(DirectionalEfficiencyGenome)})
    assert module.FixedSizingPolicy().max_abs_position == 1.0
    assert module.FixedRiskConstitution().venue_hosted_stop_proven is False


def test_preregistration_freezes_budget_gates_and_no_reveal() -> None:
    prereg = json.loads(Path("docs/research/BTC_5M_TREND_FAMILY_GA_SEARCH_02_PREREG.json").read_text(encoding="utf-8"))
    assert prereg["status"] == "frozen_before_search"
    assert prereg["engine_code_commit"] == "b2499b3f0ab03f67272aead61de4b54e4993d2a9"
    assert prereg["data_binding"]["dataset_version"] == (
        "btc-5m-qcv2r1-selection-prefix-248270-parent76e8654c-mainbcc31f0b-corr01"
    )
    assert prereg["data_binding"]["payload_sha256"] == (
        "b00557b75b3b4049bde1c09bfa69d31a8856993bb9f4fbdc71cfb49078b8f9b5"
    )
    assert prereg["search_protocol"]["family_count"] == 2
    assert prereg["search_protocol"]["population_per_family"] == 24
    assert prereg["search_protocol"]["generations"] == 6
    assert prereg["search_protocol"]["maximum_new_unique_evaluations"] == 300
    assert prereg["search_protocol"]["prior_unique_evaluations"] == 1_587
    assert prereg["selection_gate"]["cost_scenario_bps"] == {"base": 10.0, "conservative": 16.5, "stress": 30.0}
    assert prereg["holdout_policy"]["reveal_code_path_present"] is False
    assert prereg["guardrails"]["promotion_allowed"] is False


def test_cli_help_requires_selection_prefix_manifest() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/research/run_btc_trend_family_5m_ga_search.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--selection-prefix-manifest" in result.stdout
    assert "holdout" not in result.stdout.lower()
