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

from quant_crypto.research import multiscale_trend_15m_1h_search as module


def _source_frame(rows: int = 180) -> pd.DataFrame:
    opens = pd.date_range("2024-01-01", periods=rows, freq="5min", tz="UTC")
    phase = np.arange(rows, dtype=float)
    close = 42_000.0 * np.exp(phase * 0.00002 + np.sin(phase / 11.0) * 0.001)
    open_price = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_price,
            "high": np.maximum(open_price, close) * 1.0005,
            "low": np.minimum(open_price, close) * 0.9995,
            "close": close,
            "volume": 1.0 + phase / 1000.0,
            "available_time": opens + pd.Timedelta(minutes=5) - pd.Timedelta(milliseconds=1),
            "is_finalized": True,
        },
        index=opens,
    )


def _genomes() -> list[object]:
    return [
        module.DynamicMomentumCycleGenome(12, 3, 6, 12, 24, 3),
        module.VolatilityChannelGenome(24, 14, 0.1, 12, 24, 3),
        module.PullbackReaccelerationGenome(12, 48, 0.5, 6, 12, 24, 3),
    ]


def test_fixed_manifest_binding_is_current_head_and_not_parameterized() -> None:
    assert module.SELECTION_MANIFEST_RELATIVE_PATH == (
        ".agent/data_manifests/btc-5m-qcv2r1-selection-prefix/"
        "btc-5m-qcv2r1-selection-prefix-248270-qc2r1.json"
    )
    assert module.EXPECTED_MANIFEST_GIT_BLOB_SHA == "7e083664a9bf0509695a3eb62c78c0d15d9dd752"
    assert module.EXPECTED_DATASET_VERSION == (
        "btc-5m-qcv2r1-selection-prefix-248270-parent76e8654c-mainbcc31f0b-corr01"
    )


def test_full_parent_is_rejected_before_any_payload_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(module, "_open_prefix_payload", lambda path: opened.append(path))
    with pytest.raises(module.SelectionPrefixBindingError, match="fixed_manifest_path_required"):
        module.load_committed_selection_prefix(tmp_path)
    assert opened == []


@pytest.mark.parametrize(
    ("minutes", "rows", "last_available"),
    [(15, 60, "2024-01-01T14:59:59.999000+00:00"), (30, 30, "2024-01-01T14:59:59.999000+00:00"), (60, 15, "2024-01-01T14:59:59.999000+00:00")],
)
def test_aggregation_requires_complete_epoch_buckets_and_uses_source_visibility(
    minutes: int, rows: int, last_available: str
) -> None:
    result, provenance = module.aggregate_completed_bars(_source_frame(), minutes=minutes)
    assert len(result) == rows
    assert result.index[0] == pd.Timestamp("2024-01-01T00:00:00Z")
    assert result["available_time"].iloc[-1].isoformat() == last_available
    assert provenance["source_bars_per_target_bar"] == minutes // 5
    assert provenance["complete_unique_consecutive_source_bars_required"] is True
    assert len(provenance["derived_frame_sha256"]) == 64


def test_aggregation_drops_incomplete_bucket_and_rejects_internal_gap() -> None:
    incomplete = _source_frame(179)
    result, _ = module.aggregate_completed_bars(incomplete, minutes=15)
    assert len(result) == 59
    gapped = _source_frame().drop(_source_frame().index[20])
    with pytest.raises(module.AggregationError, match="source_5m_sequence_not_contiguous"):
        module.aggregate_completed_bars(gapped, minutes=15)


@pytest.mark.parametrize("genome", _genomes())
def test_each_family_is_causal_and_genome_excludes_risk_cost_and_timeframe(genome: object) -> None:
    frame, _ = module.aggregate_completed_bars(_source_frame(1_800), minutes=15)
    cutoff = 400
    changed = frame.copy()
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("close")] *= 1.3
    original = module.build_family_events(frame, genome)
    mutated = module.build_family_events(changed, genome)
    pd.testing.assert_frame_equal(original.iloc[: cutoff + 1], mutated.iloc[: cutoff + 1])
    forbidden = {"timeframe", "leverage", "max_loss", "pause", "cost_bps", "slippage_bps"}
    assert forbidden.isdisjoint({item.name for item in fields(genome)})


def test_crossover_is_family_local() -> None:
    genomes = _genomes()
    child = module.crossover_within_stratum(genomes[0], genomes[0], random.Random(7))
    assert type(child) is type(genomes[0])
    with pytest.raises(module.SearchContractError, match="cross_family_crossover_forbidden"):
        module.crossover_within_stratum(genomes[0], genomes[1], random.Random(7))


def test_fold_embargo_is_exact_5760_five_minute_bar_duration() -> None:
    assert module.embargo_target_bars(15) == 1_920
    assert module.embargo_target_bars(30) == 960
    assert module.embargo_target_bars(60) == 480
    assert module.embargo_target_bars(15) * 15 == 5_760 * 5


def test_constraint_domination_prevents_zero_trade_candidate_from_winning() -> None:
    feasible = {"feasible": True, "pareto_rank": 2, "objectives": {"worst_conservative_return": 0.01}, "genome_hash": "b"}
    inactive = {"feasible": False, "pareto_rank": 0, "objectives": {"worst_conservative_return": 1.0}, "genome_hash": "a"}
    assert module.candidate_sort_key(feasible) < module.candidate_sort_key(inactive)


def test_prereg_freezes_strata_budget_gates_and_retired_holdout() -> None:
    prereg = json.loads(Path("docs/research/BTC_15M_1H_TREND_FAMILY_SEARCH_01_PREREG.json").read_text(encoding="utf-8"))
    assert prereg["status"] == "frozen_before_corrected_official_rerun"
    assert prereg["engine_code_commit"] == "242975b4674605d34c258c494ae9bbb999f27d6d"
    assert prereg["correction_commit"] == "f827ab73e2f2ca7eb4871fbaae271b4500667fdd"
    assert prereg["correction_scope"]["invalidated_artifact_semantic_hash"] == (
        "666c9ebb130f9910c2cc119379d213c6c9c6fa8b3ea3b690f30e7a2a68b92620"
    )
    assert prereg["correction_scope"]["threshold_seed_budget_genes_costs_folds_embargo_changed"] is False
    assert prereg["validation_design"]["classification"] == "purged_chronological_selection_folds_not_oos"
    assert prereg["search_protocol"] == {
        "timeframes_minutes": [15, 30, 60],
        "families_per_timeframe": 3,
        "population_per_stratum": 12,
        "generations": 4,
        "maximum_new_unique_evaluations": 450,
        "prior_unique_evaluations": 1840,
        "seed": 20260827,
    }
    assert prereg["holdout_policy"]["status"] == "legacy_qcv2r1_holdout_retired_without_metric_reveal"
    assert prereg["holdout_policy"]["old_holdout_metrics_read"] is False
    assert prereg["holdout_policy"]["new_future_unseen_required"] is True
    assert prereg["guardrails"]["promotion_allowed"] is False


def test_small_search_has_three_costs_fixed_risk_and_no_holdout(tmp_path: Path) -> None:
    source = _source_frame(24_000)
    frames = {minutes: module.aggregate_completed_bars(source, minutes=minutes)[0] for minutes in (15, 30, 60)}
    report = module.run_multiscale_search_on_frames(
        frames=frames,
        data_provenance={"dataset_version": module.EXPECTED_DATASET_VERSION},
        output_root=tmp_path / "artifact",
        seed=13,
        population_per_stratum=4,
        generations=1,
        fold_count=2,
        prior_unique_evaluations=1840,
        max_new_unique_evaluations=40,
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )
    assert report["validation_design"]["holdout_bytes_read"] == 0
    assert report["validation_design"]["old_holdout_metrics_read"] is False
    assert report["search_protocol"]["run_unique_evaluations"] <= 40
    assert set(report["cost_scenarios_bps"]) == {"base", "conservative", "stress"}
    assert report["risk_and_sizing"]["fixed_1x"] is True
    assert report["candidate_lock"]["maximum_locked_candidates"] == 1
    assert report["candidate_lock"]["evaluated_candidate_id"] == report["top_candidates"][0]["candidate_id"]
    assert all(not row.get("neighborhood_only", False) for row in report["top_candidates"])
    assert all(not row["eligible_for_selection"] for row in report["negative_controls"])
    assert report["safety"]["private"] is False
    assert report["safety"]["order"] is False


def test_target_timeframe_annualization_is_not_left_at_five_minute_scale() -> None:
    raw = {
        "row_count": 365 * 24,
        "total_return": 0.10,
        "annualized_return": 999.0,
        "annualized_volatility": 1.2,
        "sharpe": 2.4,
    }
    corrected = module._correct_timeframe_annualization(raw, 60)
    assert corrected["annualization_period_minutes"] == 60
    assert corrected["annualized_return"] == pytest.approx(0.10)
    assert corrected["annualized_volatility"] == pytest.approx(1.2 * np.sqrt(5 / 60))
    assert corrected["sharpe"] == pytest.approx(2.4 * np.sqrt(5 / 60))


def test_cli_has_no_holdout_argument() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/research/run_btc_multiscale_trend_15m_1h_search.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--output-root" in result.stdout
    assert "holdout" not in result.stdout.lower()
