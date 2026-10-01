from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_crypto.research import regime_conditional_5m_alpha_search as module
from quant_crypto.research.regime_conditional_5m_alpha_search import (
    AlphaGenome,
    FixedRiskConstitution,
    FixedSizingPolicy,
    RegimeConditionalSearchError,
    apply_cost_aware_sizing,
    build_alpha_events,
    build_position_path_from_events,
    build_regime_conditional_target,
    classify_fold_evidence,
    run_regime_conditional_neighborhood_correction_on_frame,
    run_regime_conditional_search_on_frame,
    simulate_regime_conditional_next_open,
)


def _frame(rows: int = 8_000) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="5min", tz="UTC")
    x = np.arange(rows, dtype=float)
    regime = np.where((x // 1_500) % 2 == 0, 1.0, -1.0)
    compression = np.where((x // 300) % 3 == 0, 0.25, 1.0)
    returns = regime * 0.00010 + compression * 0.00045 * np.sin(x / 19.0)
    close = 30_000.0 * np.exp(np.cumsum(returns))
    open_price = np.concatenate(([close[0]], close[:-1]))
    spread = 0.0006 + 0.0004 * np.sin(x / 17.0) ** 2
    high = np.maximum(open_price, close) * (1.0 + spread)
    low = np.minimum(open_price, close) * (1.0 - spread)
    volume = 100.0 + 15.0 * np.sin(x / 23.0) ** 2
    return pd.DataFrame(
        {
            "open_time_ms": (index.astype("int64") // 1_000_000).astype("int64"),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


def _provenance(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "data_version": "synthetic-regime-conditional-contract-v1",
        "manifest_checksum": "a" * 64,
        "manifest_interval": "5m",
        "manifest_start": frame.index[0].isoformat(),
        "manifest_end": frame.index[-1].isoformat(),
        "manifest_row_count": len(frame),
        "resolved_row_count": len(frame),
        "resolved_slice_sha256": "b" * 64,
        "physical_access_mode": "synthetic_contract_fixture",
    }


def _genome(
    hypothesis_family: str = "compression_breakout_continuation",
    **overrides: object,
) -> AlphaGenome:
    values: dict[str, object] = {
        "hypothesis_family": hypothesis_family,
        "state_fast_bars": 12,
        "state_slow_bars": 48,
        "state_strength_atr": 1.0,
        "entry_window_bars": 24,
        "exit_window_bars": 12,
        "atr_window_bars": 14,
        "entry_buffer_atr": 0.0,
        "invalidation_atr": 2.0,
        "max_holding_bars": 24,
        "cooldown_bars": 3,
        "compression_ratio": 0.85,
    }
    values.update(overrides)
    return AlphaGenome(**values)


def _events(index: pd.DatetimeIndex) -> pd.DataFrame:
    events = pd.DataFrame(
        {
            "regime_eligible": False,
            "long_entry": False,
            "short_entry": False,
            "long_invalidation": False,
            "short_invalidation": False,
            "confidence": 1.0,
        },
        index=index,
    )
    events.loc[index[1], ["regime_eligible", "long_entry"]] = True
    events.loc[index[2]:, "regime_eligible"] = True
    return events


def test_alpha_genome_cannot_optimize_sizing_or_risk_constitution() -> None:
    genome_fields = {item.name for item in fields(AlphaGenome)}

    assert {
        "max_leverage",
        "target_volatility_pct",
        "drawdown_gate_pct",
        "daily_loss_limit_pct",
        "no_trade_band",
        "rebalance_interval_bars",
    }.isdisjoint(genome_fields)
    assert FixedSizingPolicy().max_abs_position == 1.0
    assert FixedRiskConstitution().max_abs_position == 1.0
    assert FixedRiskConstitution().venue_hosted_stop_proven is False
    with pytest.raises(RegimeConditionalSearchError, match="alpha_genome_values_invalid"):
        _genome(state_fast_bars=48, state_slow_bars=12)


@pytest.mark.parametrize(
    "family",
    [
        "compression_breakout_continuation",
        "trend_pullback_reclaim",
        "range_failed_breakout_reversal",
    ],
)
def test_all_preregistered_economic_hypothesis_families_are_causal(family: str) -> None:
    frame = _frame(3_000)
    changed = frame.copy()
    cutoff = 2_400
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("high")] *= 1.30
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("low")] *= 0.70
    changed.iloc[cutoff + 1 :, changed.columns.get_loc("close")] *= 1.15

    original = build_alpha_events(frame, _genome(family))
    mutated = build_alpha_events(changed, _genome(family))

    pd.testing.assert_frame_equal(original.iloc[: cutoff + 1], mutated.iloc[: cutoff + 1])
    assert original["hypothesis_family"].nunique() == 1
    assert original["hypothesis_family"].iloc[-1] == family


def test_cost_aware_sizing_uses_slow_rebalance_and_no_trade_band() -> None:
    index = pd.date_range("2026-01-01", periods=12, freq="5min", tz="UTC")
    raw = pd.Series(
        [0.0, 0.31, 0.36, 0.40, 0.44, 0.48, 0.52, 0.56, 0.60, 0.64, 0.68, 0.0],
        index=index,
    )
    policy = FixedSizingPolicy(
        max_abs_position=1.0,
        rebalance_interval_bars=3,
        no_trade_band=0.15,
        minimum_position_delta=0.15,
    )

    target, diagnostics = apply_cost_aware_sizing(raw, policy)

    assert diagnostics["raw_position_change_count"] == 11
    assert diagnostics["executed_position_change_count"] <= 3
    assert diagnostics["suppressed_rebalance_count"] >= 1
    assert target.iloc[-1] == 0.0


def test_time_stop_is_a_semantic_exit_not_a_risk_gene() -> None:
    frame = _frame(12)
    genome = _genome(max_holding_bars=3)

    direction, diagnostics = build_position_path_from_events(
        frame,
        _events(frame.index),
        genome,
        FixedRiskConstitution(structure_shock_atr_multiple=99.0),
    )

    assert diagnostics["time_stop_count"] == 1
    assert direction.iloc[1:4].tolist() == [1.0, 1.0, 1.0]
    assert direction.iloc[4] == 0.0


def test_structure_shock_forces_flat_and_fixed_pause() -> None:
    frame = _frame(16)
    frame.loc[frame.index[6], "high"] = frame.loc[frame.index[6], "close"] * 1.20
    frame.loc[frame.index[6], "low"] = frame.loc[frame.index[6], "close"] * 0.80
    risk = FixedRiskConstitution(
        structure_shock_atr_multiple=2.0,
        structure_pause_bars=3,
    )

    direction, diagnostics = build_position_path_from_events(
        frame,
        _events(frame.index),
        _genome(max_holding_bars=96),
        risk,
    )

    assert diagnostics["structure_shock_count"] >= 1
    assert direction.iloc[6:10].abs().sum() == 0.0
    assert diagnostics["risk_policy_digest"] == risk.policy_digest


def test_next_open_ledger_is_fill_position_cash_derived() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0],
            "high": [100.0, 110.0, 110.0],
            "low": [100.0, 100.0, 110.0],
            "close": [100.0, 110.0, 110.0],
            "volume": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    target = pd.Series([1.0, 1.0, 1.0], index=index)

    metrics, ledger = simulate_regime_conditional_next_open(
        frame,
        target,
        cost_bps=0.0,
        risk_constitution=FixedRiskConstitution(
            max_strategy_loss_pct=0.90,
            daily_loss_limit_pct=0.90,
        ),
    )

    assert metrics["total_return"] == pytest.approx(0.10)
    assert metrics["independent_bet_count"] == 1
    assert ledger["fill_samples_first"][0]["decision_time"] == index[0].isoformat()
    assert ledger["fill_samples_first"][0]["execution_time"] == index[1].isoformat()
    assert ledger["pnl_derived_from_fills_positions_cash"] is True
    assert ledger["signal_at_completed_close_execution_at_next_open"] is True
    assert ledger["reconciled"] is True


def test_fold_without_applicable_regime_is_not_forced_to_be_profitable() -> None:
    result = classify_fold_evidence(
        {
            "regime_eligible_rows": 0,
            "independent_bet_count": 0,
            "effective_bet_count": 0.0,
            "total_return": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "bankruptcy": False,
        },
        min_regime_rows=12,
        min_independent_bets=4,
    )

    assert result["status"] == "not_applicable_insufficient_regime_evidence"
    assert result["performance_gate_applied"] is False
    assert "total_return_non_positive" not in result["reasons"]


def test_search_reports_pareto_multiple_testing_and_neighborhood_evidence(
    tmp_path: Path,
) -> None:
    frame = _frame()
    report = run_regime_conditional_search_on_frame(
        frame=frame,
        data_provenance=_provenance(frame),
        output_root=tmp_path,
        seed=7,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=2,
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )

    search = report["search_protocol"]
    champion = report["top_candidates"][0]
    assert search["selection_method"] == "deterministic_pareto_genetic_search"
    assert search["fitness_is_single_weighted_scalar"] is False
    assert search["safety_parameters_in_genome"] is False
    assert search["cumulative_unique_evaluations"] >= search["run_unique_evaluations"]
    assert "multiple_testing" in champion
    assert "parameter_neighborhood_stability" in champion
    assert champion["parameter_neighborhood_stability"]["status"] in {"pass", "fail"}
    assert champion["parameter_neighborhood_stability"]["neighbor_count"] > 0
    assert "pareto_rank" in champion
    assert report["promotion"]["demo_strategy_registration_allowed"] is False
    assert report["promotion"]["paper_auto_start"] is False
    assert report["promotion"]["live_enabled"] is False
    assert report["safety"]["private_endpoints_allowed"] is False
    assert report["safety"]["order_endpoints_allowed"] is False
    assert report["safety"]["real_orders_created"] is False


def test_frozen_unseen_tail_is_not_read_when_selection_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frame = _frame(9_000)
    selection_end = 7_200
    changed = frame.copy()
    changed.iloc[selection_end:, changed.columns.get_loc("open")] *= 1.25
    changed.iloc[selection_end:, changed.columns.get_loc("high")] *= 1.30
    changed.iloc[selection_end:, changed.columns.get_loc("low")] *= 0.75
    changed.iloc[selection_end:, changed.columns.get_loc("close")] *= 0.80
    original_builder = module.build_regime_conditional_target
    observed_lengths: list[int] = []

    def build(candidate_frame: pd.DataFrame, *args: object, **kwargs: object):
        observed_lengths.append(len(candidate_frame))
        return original_builder(candidate_frame, *args, **kwargs)

    monkeypatch.setattr(module, "build_regime_conditional_target", build)
    monkeypatch.setattr(module, "_selection_gate_reasons", lambda **_: ["forced_fail"])
    common = {
        "data_provenance": _provenance(frame),
        "seed": 11,
        "population_size": 8,
        "generations": 1,
        "fold_count": 2,
        "max_candidates": 1,
        "prior_shared_tail_exposure": False,
        "frozen_unseen_holdout_start_utc": frame.index[selection_end].to_pydatetime(),
        "prior_research_cutoff_utc": frame.index[selection_end - 1].to_pydatetime(),
        "experiment_id": "contract-preserved-regime-tail",
        "generated_at_utc": pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    }
    first = run_regime_conditional_search_on_frame(
        frame=frame,
        output_root=tmp_path / "first",
        **common,
    )
    second = run_regime_conditional_search_on_frame(
        frame=changed,
        output_root=tmp_path / "second",
        **common,
    )

    assert set(observed_lengths) == {selection_end}
    assert first["decision"] == "reject_selection_batch_holdout_not_revealed"
    assert first["validation_design"]["holdout_revealed"] is False
    assert first["validation_design"]["holdout_exposure_after_run"] == "preserved_unseen"
    assert first["candidate_lock"]["reveal_authorized"] is False
    assert first["candidate_lock"]["semantic_sha256"] == second["candidate_lock"][
        "semantic_sha256"
    ]


def test_frozen_unseen_reveal_occurs_once_and_only_after_candidate_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frame = _frame(9_000)
    selection_end = 7_200
    output_root = tmp_path / "official"
    lock_path = output_root / "btc_5m_regime_conditional_candidate_lock.json"
    original_builder = module.build_regime_conditional_target
    full_frame_builds = 0

    def build(candidate_frame: pd.DataFrame, *args: object, **kwargs: object):
        nonlocal full_frame_builds
        if len(candidate_frame) == len(frame):
            full_frame_builds += 1
            assert lock_path.exists(), "candidate lock must predate unseen reveal"
        else:
            assert len(candidate_frame) == selection_end
        return original_builder(candidate_frame, *args, **kwargs)

    monkeypatch.setattr(module, "build_regime_conditional_target", build)
    monkeypatch.setattr(module, "_selection_gate_reasons", lambda **_: [])
    report = run_regime_conditional_search_on_frame(
        frame=frame,
        data_provenance=_provenance(frame),
        output_root=output_root,
        seed=13,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=1,
        prior_shared_tail_exposure=False,
        frozen_unseen_holdout_start_utc=frame.index[selection_end].to_pydatetime(),
        prior_research_cutoff_utc=frame.index[selection_end - 1].to_pydatetime(),
        experiment_id="contract-single-regime-reveal",
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )

    assert full_frame_builds == 1
    assert report["validation_design"]["holdout_revealed"] is True
    assert report["validation_design"]["holdout_candidate_count_revealed"] == 1
    assert report["candidate_lock"]["reveal_authorized"] is True
    assert report["top_candidates"][0]["frozen_unseen_holdout"]["cost_scenarios"]


def test_frozen_unseen_output_root_is_append_only(tmp_path: Path) -> None:
    frame = _frame(9_000)
    selection_end = 7_200
    output_root = tmp_path / "existing"
    output_root.mkdir()

    with pytest.raises(RegimeConditionalSearchError, match="output_root_must_be_new"):
        run_regime_conditional_search_on_frame(
            frame=frame,
            data_provenance=_provenance(frame),
            output_root=output_root,
            seed=17,
            population_size=8,
            generations=1,
            fold_count=2,
            max_candidates=1,
            prior_shared_tail_exposure=False,
            frozen_unseen_holdout_start_utc=frame.index[selection_end].to_pydatetime(),
            prior_research_cutoff_utc=frame.index[selection_end - 1].to_pydatetime(),
        )


def test_cli_help_is_available_without_market_or_network_access() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/research/run_btc_regime_conditional_5m_alpha_search.py",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "regime-conditional" in result.stdout.lower()
    assert "--frozen-unseen-holdout-start" in result.stdout


def test_candidate_definitions_never_register_or_unlock_execution(tmp_path: Path) -> None:
    report = run_regime_conditional_search_on_frame(
        frame=_frame(),
        data_provenance=_provenance(_frame()),
        output_root=tmp_path,
        seed=19,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=2,
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )
    definitions = json.loads(
        (tmp_path / "btc_5m_regime_conditional_candidate_definitions.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["status"] == "complete_research_only"
    assert definitions["demo_strategy_registration_allowed"] is False
    assert definitions["paper_queue_write_allowed"] is False
    assert definitions["live_unlock_allowed"] is False
    assert definitions["private_endpoints_allowed"] is False
    assert definitions["order_endpoints_allowed"] is False


def test_qcv2r1_preregistration_matches_engine_and_sealed_tail_contract() -> None:
    prereg = json.loads(
        Path(
            "docs/research/BTC_5M_REGIME_CONDITIONAL_ALPHA_SEARCH_01_PREREG.json"
        ).read_text(encoding="utf-8")
    )

    assert prereg["status"] == "frozen_before_search"
    assert prereg["engine_code_commit"] == "9a42e6eb55956aa5c6aa7c7d48fc83542f20ad05"
    assert prereg["data_binding"]["dataset_version"].endswith("-qc2r1")
    assert prereg["data_binding"]["five_minute_file_sha256"] == (
        "76e8654cd11fc40b873b30d4a6fa8b2ed618256721e3b7840e180bd0f0359c08"
    )
    assert prereg["frozen_windows"]["selection_rows"] == 248_270
    assert prereg["frozen_windows"]["unseen_holdout_rows"] == 30_658
    assert prereg["frozen_windows"]["unseen_holdout_used_for_parameter_selection"] is False
    assert prereg["search_protocol"]["algorithm"] == (
        "deterministic_pareto_genetic_search"
    )
    assert prereg["search_protocol"]["prior_search_unique_evaluations"] == 1_357
    assert prereg["search_protocol"]["single_weighted_fitness_used"] is False
    assert prereg["fixed_sizing_policy"]["policy_digest"] == (
        module.FixedSizingPolicy().policy_digest
    )
    assert prereg["fixed_risk_constitution"]["policy_digest"] == (
        module.FixedRiskConstitution().policy_digest
    )
    assert prereg["selection_gate"]["trades_per_day_gate_used"] is False
    assert prereg["conditional_holdout_reveal"][
        "write_candidate_lock_before_reading_holdout_strategy_metrics"
    ] is True
    assert prereg["guardrails"]["promotion_allowed"] is False
    assert prereg["guardrails"]["paper_allowed"] is False
    assert prereg["guardrails"]["live_allowed"] is False
    assert prereg["guardrails"]["private_endpoint_allowed"] is False
    assert prereg["guardrails"]["order_endpoint_allowed"] is False


def test_selection_only_neighborhood_correction_never_reads_unseen_tail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frame = _frame(9_000)
    selection_end = 7_200
    source_root = tmp_path / "source"
    monkeypatch.setattr(module, "_selection_gate_reasons", lambda **_: ["forced_fail"])
    source = run_regime_conditional_search_on_frame(
        frame=frame,
        data_provenance=_provenance(frame),
        output_root=source_root,
        seed=23,
        population_size=8,
        generations=1,
        fold_count=2,
        max_candidates=1,
        prior_shared_tail_exposure=False,
        frozen_unseen_holdout_start_utc=frame.index[selection_end].to_pydatetime(),
        prior_research_cutoff_utc=frame.index[selection_end - 1].to_pydatetime(),
        experiment_id="contract-neighborhood-correction",
        generated_at_utc=pd.Timestamp("2026-08-27T00:00:00Z").to_pydatetime(),
    )
    source_report_path = (
        source_root / "btc_5m_regime_conditional_alpha_search_report.json"
    )
    source_lock_path = source_root / "btc_5m_regime_conditional_candidate_lock.json"
    source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    sha256 = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()

    corrected = run_regime_conditional_neighborhood_correction_on_frame(
        frame=frame,
        data_provenance=_provenance(frame),
        source_report=source,
        source_lock=source_lock,
        source_report_file_sha256=sha256(source_report_path),
        source_lock_file_sha256=sha256(source_lock_path),
        output_root=tmp_path / "correction",
        generated_at_utc=pd.Timestamp("2026-08-27T01:00:00Z").to_pydatetime(),
    )

    stability = corrected["candidate"]["parameter_neighborhood_stability"]
    assert corrected["correction_unique_evaluations"] == stability["neighbor_count"]
    assert stability["neighbor_count"] > 0
    assert stability["status"] in {"pass", "fail"}
    assert corrected["holdout_strategy_metrics_read"] is False
    assert corrected["holdout_exposure_after_run"] == "preserved_unseen"
    assert corrected["correction_lock"]["reveal_authorized"] is False
    assert corrected["promotion"]["promotion_ready"] is False
    assert corrected["safety"]["private_endpoints_allowed"] is False
    assert corrected["safety"]["order_endpoints_allowed"] is False
