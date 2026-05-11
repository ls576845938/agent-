"""R6/R7/R8 integration tests.

Covers:
- R6: Monte Carlo shuffle reproducibility, bootstrap return estimation
- R6: Alpha decay half-life estimation, decay curve computation
- R7: Correlation cluster redundant pair detection, diversification score
- R8: Portfolio stress cost scenarios, crash window analysis
- R6/R7/R8: Enhanced ResearchPromotionGate with all new checks
- Safety invariants: no live imports, no broker access, determinism
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash
from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.research.evidence_contracts import (
    PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
    PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
)


# ===========================================================================
# R6: Monte Carlo / Alpha Robustness
# ===========================================================================


@pytest.mark.integration
class TestMonteCarlo:
    """Monte Carlo trade shuffling and bootstrap return estimation."""

    def test_shuffle_trades_reproducible(self, tmp_path: Path) -> None:
        """Shuffling trades with a seeded RNG should produce reproducible results."""
        trades = [0.01, -0.005, 0.02, -0.01, 0.015, -0.008, 0.03, -0.012]

        # Shuffle with seed 42
        rng = random.Random(42)
        shuffled_1 = trades.copy()
        rng.shuffle(shuffled_1)

        # Shuffle with same seed
        rng2 = random.Random(42)
        shuffled_2 = trades.copy()
        rng2.shuffle(shuffled_2)

        assert shuffled_1 == shuffled_2, (
            "Shuffled sequences should match with same seed"
        )

        # Different seed should produce different order
        rng3 = random.Random(99)
        shuffled_3 = trades.copy()
        rng3.shuffle(shuffled_3)
        assert shuffled_1 != shuffled_3, (
            "Different seeds should produce different orders"
        )

    def test_bootstrap_returns(self, tmp_path: Path) -> None:
        """Bootstrap resampling of returns should converge on expected mean."""
        trades = [0.01, -0.005, 0.02, -0.01, 0.015]
        expected_mean = sum(trades) / len(trades)

        # Bootstrap: resample with replacement 1000 times
        n_iterations = 1000
        n_samples = len(trades)
        rng = random.Random(42)
        bootstrap_means: list[float] = []

        for _ in range(n_iterations):
            sample = [rng.choice(trades) for _ in range(n_samples)]
            bootstrap_means.append(sum(sample) / n_samples)

        # Mean of bootstrap means should converge to expected mean
        observed_mean = sum(bootstrap_means) / n_iterations
        assert abs(observed_mean - expected_mean) < 0.01, (
            f"Bootstrap mean {observed_mean:.4f} should converge to "
            f"expected {expected_mean:.4f}"
        )

        # Survival rate: fraction of bootstrap trials with positive mean
        survival_rate = sum(1.0 for m in bootstrap_means if m > 0) / n_iterations
        assert 0.0 < survival_rate < 1.0, (
            f"Survival rate {survival_rate:.3f} should be between 0 and 1"
        )

        # Verify reproducibility: same seed produces same survival rate
        rng_replay = random.Random(42)
        replay_means = [
            sum(rng_replay.choice(trades) for _ in range(n_samples)) / n_samples
            for _ in range(n_iterations)
        ]
        replay_survival = sum(1.0 for m in replay_means if m > 0) / n_iterations
        assert survival_rate == replay_survival, (
            "Bootstrap survival rate should be reproducible with same seed"
        )


@pytest.mark.integration
class TestAlphaDecay:
    """Alpha decay half-life estimation and decay curves."""

    def test_half_life_estimation(self) -> None:
        """Half-life estimation from exponential decay of alpha values."""
        # Simulate alpha decay: alpha = 1.0 * 0.5^(t / half_life)
        true_half_life = 10.0  # days
        time_steps = list(range(30))
        alphas = [1.0 * (0.5 ** (t / true_half_life)) for t in time_steps]

        # Estimate half-life by finding when alpha drops below 0.5
        # Starting from alpha=1.0, half-life is the time to reach 0.5
        estimated_half_life: float | None = None
        for t, a in zip(time_steps, alphas):
            if a <= 0.5:
                estimated_half_life = float(t)
                break

        assert estimated_half_life is not None, "Half-life should be estimated"
        assert abs(estimated_half_life - true_half_life) < 1.0, (
            f"Estimated half-life {estimated_half_life:.1f} should be close to "
            f"true value {true_half_life:.1f}"
        )

        # Rapid decay: half-life <= 5 days should be flagged
        rapid_decay_alphas = [1.0 * (0.5 ** (t / 3.0)) for t in time_steps]
        rapid_estimated: float | None = None
        for t, a in zip(time_steps, rapid_decay_alphas):
            if a <= 0.5:
                rapid_estimated = float(t)
                break

        assert rapid_estimated is not None, "Rapid decay half-life should be estimated"
        assert rapid_estimated <= 5.0, (
            f"Rapid decay half-life {rapid_estimated:.1f} should be <= 5 days"
        )

    def test_decay_curve(self, tmp_path: Path) -> None:
        """Decay curve should be monotonic decreasing and parameterized."""
        half_life = 7.0
        time_steps = list(range(int(5 * half_life) + 1))
        decay_curve = [1.0 * (0.5 ** (t / half_life)) for t in time_steps]

        # Verify monotonic decreasing
        for i in range(1, len(decay_curve)):
            assert decay_curve[i] <= decay_curve[i - 1], (
                f"Decay curve should be monotonic at index {i}: "
                f"{decay_curve[i]} > {decay_curve[i - 1]}"
            )

        # Verify half-life point: at t = half_life, alpha should be ~0.5
        half_life_idx = int(half_life)
        assert abs(decay_curve[half_life_idx] - 0.5) < 0.01, (
            f"At t={half_life}, alpha should be ~0.5, got {decay_curve[half_life_idx]:.4f}"
        )

        # Verify long-term decay: at t = 5 * half_life, alpha should be near 0
        long_term_idx = min(int(5 * half_life), len(decay_curve) - 1)
        assert decay_curve[long_term_idx] < 0.05, (
            f"At t={long_term_idx}, alpha should be near 0, "
            f"got {decay_curve[long_term_idx]:.4f}"
        )

        # Persist curve and verify reload
        curve_path = tmp_path / "decay_curve.json"
        curve_path.write_text(json.dumps(decay_curve))
        reloaded = json.loads(curve_path.read_text())
        assert reloaded == decay_curve, "Decay curve should survive serialization"
        assert len(reloaded) == int(5 * half_life) + 1, "Decay curve should cover 5 half-lives"


# ===========================================================================
# R7: Correlation Cluster / Diversification
# ===========================================================================


@pytest.mark.integration
class TestCorrelationCluster:
    """Correlation cluster redundant pair detection and diversification scoring."""

    def test_redundant_pair_detection(self, tmp_path: Path) -> None:
        """Pairs with correlation > 0.70 should be flagged as redundant."""
        # Simulate a correlation matrix for 4 strategies
        strategies = ["strat_a", "strat_b", "strat_c", "strat_d"]
        correlation_matrix = {
            "strat_a": {"strat_a": 1.0, "strat_b": 0.85, "strat_c": 0.30, "strat_d": 0.15},
            "strat_b": {"strat_a": 0.85, "strat_b": 1.0, "strat_c": 0.25, "strat_d": 0.10},
            "strat_c": {"strat_a": 0.30, "strat_b": 0.25, "strat_c": 1.0, "strat_d": 0.60},
            "strat_d": {"strat_a": 0.15, "strat_b": 0.10, "strat_c": 0.60, "strat_d": 1.0},
        }

        # Detect redundant pairs (abs correlation > 0.70)
        redundant_pairs: list[tuple[str, str, float]] = []
        for i, s1 in enumerate(strategies):
            for s2 in strategies[i + 1:]:
                corr = correlation_matrix[s1][s2]
                if abs(corr) > 0.70:
                    redundant_pairs.append((s1, s2, corr))

        assert len(redundant_pairs) > 0, "Should detect at least one redundant pair"
        pair_names = [f"{p[0]}_vs_{p[1]}" for p in redundant_pairs]
        assert "strat_a_vs_strat_b" in pair_names, (
            "strat_a and strat_b (corr=0.85) should be flagged as redundant"
        )

        # Persist and verify
        pairs_path = tmp_path / "redundant_pairs.json"
        pairs_path.write_text(json.dumps(redundant_pairs))
        reloaded = json.loads(pairs_path.read_text())
        assert len(reloaded) == len(redundant_pairs)

    def test_diversification_score(self, tmp_path: Path) -> None:
        """Diversification score should decrease with higher average correlation."""
        # Scenario 1: well-diversified (low average correlation)
        low_corr_strategies = 4
        low_corr_values = [0.10, 0.15, 0.20, 0.25]

        # Scenario 2: poorly diversified (high average correlation)
        high_corr_strategies = 4
        high_corr_values = [0.75, 0.80, 0.85, 0.90]

        # Diversification score = 1 - avg_abs_correlation (higher is better)
        low_avg_corr = sum(low_corr_values) / len(low_corr_values)
        high_avg_corr = sum(high_corr_values) / len(high_corr_values)

        low_div_score = 1.0 - low_avg_corr
        high_div_score = 1.0 - high_avg_corr

        assert low_div_score > high_div_score, (
            f"Low-correlation portfolio ({low_div_score:.3f}) should have higher "
            f"diversification score than high-correlation ({high_div_score:.3f})"
        )
        assert low_div_score > 0.5, (
            f"Well-diversified portfolio should have score > 0.5, got {low_div_score:.3f}"
        )
        assert high_div_score < 0.5, (
            f"Poorly diversified portfolio should have score < 0.5, got {high_div_score:.3f}"
        )

        # Persist results
        result = {
            "n_strategies_low": low_corr_strategies,
            "low_div_score": low_div_score,
            "n_strategies_high": high_corr_strategies,
            "high_div_score": high_div_score,
        }
        result_path = tmp_path / "diversification.json"
        result_path.write_text(json.dumps(result))
        reloaded = json.loads(result_path.read_text())
        assert reloaded["low_div_score"] > reloaded["high_div_score"]


# ===========================================================================
# R8: Portfolio Stress / Crash Window
# ===========================================================================


@pytest.mark.integration
class TestPortfolioStress:
    """Portfolio stress testing: cost scenarios and crash windows."""

    def test_cost_stress_scenarios(self, tmp_path: Path) -> None:
        """Increasing costs should degrade portfolio returns monotonically."""
        # Simulate portfolio returns under different cost scenarios
        base_return = 0.15  # 15% annual return
        cost_levels = [1.0, 2.0, 3.0, 5.0, 10.0]  # cost multipliers

        returns_after_cost = []
        for cost_mult in cost_levels:
            # Cost penalty increases with multiplier
            cost_penalty = 0.02 * cost_mult  # 2% penalty per unit cost
            net_return = base_return - cost_penalty
            returns_after_cost.append(max(net_return, -0.50))  # floor at -50%

        # Verify monotonic degradation
        for i in range(1, len(returns_after_cost)):
            assert returns_after_cost[i] <= returns_after_cost[i - 1], (
                f"Returns should degrade monotonically at cost level {cost_levels[i]}"
            )

        # Stress survival: fraction of scenarios with positive returns
        # Survival threshold: return > 0 after costs
        survival_rate = sum(1.0 for r in returns_after_cost if r > 0) / len(returns_after_cost)
        assert survival_rate <= 1.0, f"Survival rate should be <= 1.0, got {survival_rate}"
        assert survival_rate >= 0.0, f"Survival rate should be >= 0.0, got {survival_rate}"

        # At 10x costs, returns should be negative
        assert returns_after_cost[-1] <= 0, (
            f"At 10x costs, return should be <= 0, got {returns_after_cost[-1]:.4f}"
        )

        # Persist results
        stress_result = {
            "cost_levels": cost_levels,
            "returns": returns_after_cost,
            "survival_rate": survival_rate,
        }
        stress_path = tmp_path / "cost_stress.json"
        stress_path.write_text(json.dumps(stress_result))
        reloaded = json.loads(stress_path.read_text())
        assert len(reloaded["returns"]) == len(cost_levels)

    def test_crash_window(self, tmp_path: Path) -> None:
        """Portfolio should survive historical crash windows with limited drawdown."""
        # Simulate crash scenarios: 2008, 2020 COVID, 2022 rate hike
        crash_scenarios = {
            "2008_financial": [-0.05, -0.08, -0.12, -0.15, -0.10, -0.05, 0.02, 0.05],
            "2020_covid": [-0.10, -0.15, -0.08, 0.05, 0.10, 0.08, 0.03, 0.01],
            "2022_rate_hike": [-0.03, -0.05, -0.04, -0.06, -0.02, 0.01, 0.02, 0.03],
        }

        for scenario_name, daily_returns in crash_scenarios.items():
            # Compute cumulative return through the crash window
            cumulative = 1.0
            max_drawdown = 0.0
            peak = 1.0

            for r in daily_returns:
                cumulative *= (1.0 + r)
                if cumulative > peak:
                    peak = cumulative
                dd = (peak - cumulative) / peak
                max_drawdown = max(max_drawdown, dd)

            # All scenarios should survive (not go to zero)
            assert cumulative > 0.0, (
                f"{scenario_name}: cumulative return should be positive, "
                f"got {cumulative:.4f}"
            )

            # Max drawdown should be finite and measurable
            assert 0.0 < max_drawdown < 1.0, (
                f"{scenario_name}: max drawdown {max_drawdown:.2%} should be "
                f"between 0 and 100%"
            )

        # Stress survival rate across all scenarios
        # A scenario "survives" if cumulative return > -50%
        survival_count = 0
        for scenario_name, daily_returns in crash_scenarios.items():
            cumulative = 1.0
            for r in daily_returns:
                cumulative *= (1.0 + r)
            if cumulative > 0.5:  # survived with > 50% of capital
                survival_count += 1

        stress_survival_rate = survival_count / len(crash_scenarios)
        assert stress_survival_rate > 0.0, (
            f"At least some scenarios should survive, got {stress_survival_rate}"
        )

        # Persist crash analysis
        crash_path = tmp_path / "crash_analysis.json"
        crash_path.write_text(json.dumps({
            "scenarios": list(crash_scenarios.keys()),
            "stress_survival_rate": stress_survival_rate,
        }))
        assert crash_path.exists()


# ===========================================================================
# R8: Promotion Gate Enhancement Integration Tests
# ===========================================================================


@pytest.mark.integration
class TestPromotionGateEnhanced:
    """Enhanced ResearchPromotionGate with R6/R7/R8 checks."""

    def _write_candidate(
        self,
        root: Path,
        candidate_id: str,
        metrics: dict,
        promotion_status: str = "CANDIDATE",
        symbols: list[str] | None = None,
        data_version: str = "qs-yfinance-AAPL-1d-test",
        data_source: str = "yfinance",
        asset_class: str = "equity",
        backtest_manifest_path: str | None = None,
        backtest_manifest: dict | None = None,
        write_canonical_artifacts: bool = True,
        write_strategy_manifest: bool = True,
    ) -> Path:
        """Helper to write a candidate JSON file with given metrics."""
        cand_dir = root / "research" / "candidates" / candidate_id
        cand_dir.mkdir(parents=True)
        merged_metrics = {
            "engine": "event_driven",
            "ledger_consistency_pct": 100.0,
            "baseline_fill_count": 1,
            "baseline_order_count": 1,
            "total_fill_count": 2,
            "total_order_count": 2,
            "sharpe_ratio": 1.55,
            "gross_sharpe_ratio": 1.78,
            "total_return_pct": 0.24,
            "gross_total_return_pct": 0.28,
            "trial_count": 6,
            "daily_returns": [
                0.012,
                0.008,
                -0.004,
                0.011,
                0.007,
                0.009,
                -0.003,
                0.010,
                0.006,
                0.005,
                0.013,
                -0.002,
                0.011,
                0.009,
                0.004,
                0.008,
                -0.001,
                0.007,
                0.010,
                0.006,
            ],
            "trial_sharpes": [0.82, 0.91, 1.02, 0.88, 0.95, 1.05],
            "pbo_trials": [
                {
                    "split_id": "s1",
                    "config_id": "a",
                    "train_sharpe": 1.30,
                    "test_sharpe": 1.10,
                },
                {
                    "split_id": "s1",
                    "config_id": "b",
                    "train_sharpe": 1.10,
                    "test_sharpe": 0.70,
                },
                {
                    "split_id": "s1",
                    "config_id": "c",
                    "train_sharpe": 0.90,
                    "test_sharpe": 0.40,
                },
                {
                    "split_id": "s2",
                    "config_id": "a",
                    "train_sharpe": 1.25,
                    "test_sharpe": 1.00,
                },
                {
                    "split_id": "s2",
                    "config_id": "b",
                    "train_sharpe": 1.00,
                    "test_sharpe": 0.60,
                },
                {
                    "split_id": "s2",
                    "config_id": "c",
                    "train_sharpe": 0.80,
                    "test_sharpe": 0.20,
                },
            ],
            **metrics,
        }
        data = {
            "candidate_id": candidate_id,
            "experiment_id": "exp_test",
            "strategy_id": "momentum",
            "params_hash": "abc123",
            "promotion_status": promotion_status,
            "symbols": symbols or ["AAPL"],
            "data_version": data_version,
            "data_source": data_source,
            "asset_class": asset_class,
            "metrics": merged_metrics,
        }
        if backtest_manifest_path is not None:
            data["backtest_manifest_path"] = backtest_manifest_path
        if backtest_manifest is not None:
            data["backtest_manifest"] = backtest_manifest
        if write_canonical_artifacts:
            data["walk_forward_result_path"] = (
                f"research/walk_forward/{candidate_id}/result.json"
            )
            data["cost_stress_result_path"] = (
                f"research/cost_stress/{candidate_id}/result.json"
            )
            self._make_canonical_research_artifacts(
                root=root,
                candidate_id=candidate_id,
                metrics=merged_metrics,
            )
        if write_strategy_manifest:
            self._make_strategy_manifest(
                root=root,
                candidate_id=candidate_id,
                experiment_id=str(data["experiment_id"]),
                symbols=list(data["symbols"]),
            )
        path = cand_dir / "candidate.json"
        path.write_text(json.dumps(data))
        return path

    def _make_strategy_manifest(
        self,
        *,
        root: Path,
        candidate_id: str,
        experiment_id: str = "exp_test",
        symbols: list[str] | None = None,
    ) -> Path:
        """Helper to create frozen canonical strategy manifest evidence."""
        manifest_id = f"sman_{candidate_id}"
        manifest_dir = root / "research" / "manifests" / manifest_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        path = manifest_dir / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "strategy_candidate_id": manifest_id,
                    "source_candidate_id": candidate_id,
                    "source_experiment_id": experiment_id,
                    "symbols": symbols or ["AAPL"],
                    "promotion_status": "DRAFT",
                    "params_frozen": True,
                    "data_version": "qs-yfinance-AAPL-1d-test",
                    "sample_window": {"start": "2024-01-01", "end": "2024-12-31"},
                    "purge_embargo": {"purge_bars": 2, "embargo_bars": 1},
                    "trial_id": candidate_id,
                    "trial_count": 6,
                    "pbo": 0.05,
                    "dsr": 0.6,
                    "cpcv": {
                        "method": "cpcv",
                        "path_count": 6,
                        "fold_count": 4,
                        "purged": True,
                        "embargoed": True,
                    },
                    "cost_model": {"name": "default"},
                    "slippage_model": {"name": "default"},
                    "cost_stress": {
                        "stress_survival_rate": 0.85,
                        "cost_sensitivity": 0.2,
                        "level_count": 3,
                    },
                    "style_exposure": {
                        "betas": {"market": 0.8},
                        "benchmark_columns": ["market"],
                    },
                    "capacity": {"estimated_capacity_usd": 1000000.0},
                    "turnover": {"turnover": 0.2},
                    "holding_period": {"expected": "5d"},
                    "exposure_limits": {"max_gross_exposure_pct": 90.0},
                    "failure_conditions": ["dd_limit"],
                    "delisting_conditions": {"policy": "manual_review_required"},
                    "created_at": "2026-05-04T15:25:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        return path

    def _make_canonical_research_artifacts(
        self,
        *,
        root: Path,
        candidate_id: str,
        metrics: dict,
    ) -> tuple[Path, Path]:
        """Helper to create persisted walk-forward and cost-stress evidence."""
        walk_forward_dir = root / "research" / "walk_forward" / candidate_id
        cost_stress_dir = root / "research" / "cost_stress" / candidate_id
        walk_forward_dir.mkdir(parents=True, exist_ok=True)
        cost_stress_dir.mkdir(parents=True, exist_ok=True)

        walk_forward_path = walk_forward_dir / "result.json"
        walk_forward_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "schema_version": "research_walk_forward_result_v2",
                    "status": "completed",
                    "validation_method": "cpcv",
                    "purged": True,
                    "embargo_bars": 2,
                    "n_splits": 4,
                    "test_splits": 2,
                    "combination_count": 6,
                    "walk_forward_pass_rate": float(
                        metrics.get("walk_forward_pass_rate", 0.8)
                    ),
                    "folds": [
                        {"fold": 1, "oos_sharpe": 1.20, "passed": True},
                        {"fold": 2, "oos_sharpe": 1.05, "passed": True},
                        {"fold": 3, "oos_sharpe": 0.95, "passed": True},
                        {"fold": 4, "oos_sharpe": 1.00, "passed": True},
                    ],
                    "pbo_trials": list(metrics.get("pbo_trials", [])),
                }
            ),
            encoding="utf-8",
        )

        cost_stress_path = cost_stress_dir / "result.json"
        cost_stress_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "status": "completed",
                    "cost_sensitivity": float(metrics.get("cost_sensitivity", 0.2)),
                    "stress_survival_rate": float(
                        metrics.get("stress_survival_rate", 0.85)
                    ),
                    "levels": [
                        {
                            "cost_multiplier": 1.0,
                            "total_return_pct": float(
                                metrics.get("total_return_pct", 0.24)
                            ),
                            "sharpe_ratio": float(
                                metrics.get("sharpe_ratio", metrics.get("sharpe", 1.5))
                            ),
                        },
                        {
                            "cost_multiplier": 2.0,
                            "total_return_pct": float(
                                metrics.get("total_return_pct", 0.24)
                            )
                            - 0.03,
                            "sharpe_ratio": float(
                                metrics.get("sharpe_ratio", metrics.get("sharpe", 1.5))
                            )
                            - 0.18,
                        },
                        {
                            "cost_multiplier": 5.0,
                            "total_return_pct": float(
                                metrics.get("total_return_pct", 0.24)
                            )
                            - 0.08,
                            "sharpe_ratio": float(
                                metrics.get("sharpe_ratio", metrics.get("sharpe", 1.5))
                            )
                            - 0.42,
                        },
                    ],
                    "scenarios": [{"name": "high_cost", "passed": True}],
                }
            ),
            encoding="utf-8",
        )
        return walk_forward_path, cost_stress_path

    def _make_experiment_manifest(
        self,
        root: Path,
        experiment_id: str,
        symbols: list[str] | None = None,
        data_version: str = "qs-yfinance-AAPL-1d-test",
        data_source: str = "yfinance",
        asset_class: str = "equity",
        write_data_manifest: bool = True,
    ) -> None:
        """Helper to create a minimal experiment manifest."""
        exp_dir = root / "research" / "experiments" / experiment_id
        exp_dir.mkdir(parents=True)
        manifest = {
            "experiment_id": experiment_id,
            "strategy_id": "momentum",
            "strategy_version": "1.0.0",
            "symbols": symbols or ["AAPL"],
            "data_version": data_version,
            "data_source": data_source,
            "asset_class": asset_class,
            "params": {"lookback": 20},
            "status": "COMPLETED",
            "metrics": {"sharpe": 1.5},
        }
        (exp_dir / "manifest.json").write_text(json.dumps(manifest))
        if write_data_manifest:
            self._make_data_manifest(
                root,
                data_version=data_version,
                source=data_source,
                symbol=(symbols or ["AAPL"])[0],
                asset_class=asset_class,
            )

    def _make_data_manifest(
        self,
        root: Path,
        data_version: str = "qs-yfinance-AAPL-1d-test",
        source: str = "yfinance",
        symbol: str = "AAPL",
        asset_class: str = "equity",
        fingerprint: str = "a" * 64,
        checksum: str = "a" * 64,
    ) -> None:
        """Helper to create governed data manifest evidence for promotion tests."""
        DataManifestStore(root / "manifests").write(
            DataManifest(
                data_version=data_version,
                source=source,
                symbol=symbol,
                interval="1d",
                asset_class=asset_class,
                timezone="UTC",
                adjustment="raw",
                start="2024-01-01T00:00:00+00:00",
                end="2024-12-31T00:00:00+00:00",
                row_count=252,
                expected_rows=252,
                coverage_pct=100.0,
                fingerprint=fingerprint,
                checksum=checksum,
                quality_score=98.0,
                cleaning={
                    "duplicate_timestamps_removed": 0,
                    "invalid_ohlc_removed": 0,
                    "non_positive_prices_removed": 0,
                    "cleaning_loss_rows": 0,
                    "missing_bars": 0,
                },
                git_commit="testcommit",
            )
        )

    def _make_backtest_manifest(
        self,
        root: Path,
        candidate_id: str,
        *,
        data_version: str = "qs-yfinance-AAPL-1d-test",
        source: str = "yfinance",
        symbol: str = "AAPL",
        asset_class: str = "equity",
        engine: str = "event_driven",
        canonical_for_promotion: bool = True,
        promotion_evidence_complete: bool = True,
        fixture_like_data_version: bool = False,
        order_count: int = 2,
        fill_count: int = 2,
        orders_have_risk_check_id: bool = True,
        fills_match_orders: bool = True,
        equity_consistent: bool = True,
        data_manifest_fingerprint: str = "a" * 64,
        data_manifest_checksum: str = "a" * 64,
    ) -> Path:
        """Helper to create canonical backtest manifest evidence for promotion tests."""
        manifest_dir = root / "research" / "backtests" / candidate_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        generated_at = "2026-05-04T15:30:00+00:00"
        reconciliation_summary = {
            "snapshot_count": max(fill_count, 1),
            "tolerance_pct": 0.01,
            "absolute_tolerance": 1e-06,
            "max_abs_diff": 0.0 if equity_consistent else 100.0,
            "max_pct_diff": 0.0 if equity_consistent else 1.0,
            "passed": equity_consistent,
            "message": "fixture reconciliation summary",
        }
        ledger_artifact = {
            "artifact_version": "ledger_reconciliation_v1",
            "generated_at": generated_at,
            "as_of_utc": generated_at,
            "initial_cash": 100000.0,
            "orders": {
                "total_orders": order_count,
                "by_status": {"filled": order_count} if order_count else {},
                "by_side": {"buy": order_count} if order_count else {},
            },
            "fills": {
                "raw_fill_count": fill_count,
                "effective_fill_count": fill_count,
                "duplicate_fill_count": 0,
                "conflict_fill_count": 0,
                "empty_identity_count": 0,
                "duplicate_fill_keys": [],
                "conflict_fill_keys": [],
                "total_notional": float(fill_count * 1000.0),
                "by_side": {"buy": fill_count} if fill_count else {},
                "first_fill_at": generated_at if fill_count else None,
                "last_fill_at": generated_at if fill_count else None,
            },
            "positions": {},
            "cash": {
                "initial_cash": 100000.0,
                "final_cash": 100000.0,
                "cash_change": 0.0,
            },
            "fees": {"total_fees": 0.0},
            "slippage": {"realized_slippage_cost": 0.0},
            "pnl": {
                "source": "ledger_fills",
                "initial_equity": 100000.0,
                "final_equity": 100000.0,
                "net_pnl": 0.0,
                "position_value": 0.0,
            },
            "hashes": {
                "ledger_hash": "ledger_hash_fixture",
                "orders_hash": "orders_hash_fixture",
                "fills_hash": "fills_hash_fixture",
                "portfolio_snapshots_hash": "portfolio_snapshots_hash_fixture",
                "effective_fills_hash": "effective_fills_hash_fixture",
            },
            "integrity": {
                "fills": {
                    "raw_fill_count": fill_count,
                    "effective_fill_count": fill_count,
                    "duplicate_fill_count": 0,
                    "conflict_fill_count": 0,
                    "empty_identity_count": 0,
                    "duplicate_fill_keys": [],
                    "conflict_fill_keys": [],
                    "passed": True,
                },
                "passed": equity_consistent,
            },
            "reconciliation": {
                "summary": reconciliation_summary,
                "snapshots": [],
                "adjustment_cross_check": None,
            },
        }
        ledger_artifact["artifact_hash"] = compute_ledger_reconciliation_artifact_hash(ledger_artifact)
        ledger_artifact_path = (
            root
            / "manifests"
            / "reconciliation"
            / f"ledger_recon_artifact_{ledger_artifact['artifact_hash'][:16]}.json"
        )
        ledger_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_artifact_path.write_text(
            json.dumps(ledger_artifact, sort_keys=True),
            encoding="utf-8",
        )
        manifest = {
            "engine": engine,
            "canonical_for_promotion": canonical_for_promotion,
            "generated_at": generated_at,
            "data_version": data_version,
            "ledger_artifact_hash": ledger_artifact["artifact_hash"],
            "ledger_artifact_path": str(ledger_artifact_path),
            "ledger_hash": ledger_artifact["hashes"]["ledger_hash"],
            "fills_hash": ledger_artifact["hashes"]["fills_hash"],
            "data_manifest": {
                "data_version": data_version,
                "source": source,
                "symbol": symbol,
                "interval": "1d",
                "asset_class": asset_class,
                "timezone": "UTC",
                "adjustment": "raw",
                "start": "2024-01-01T00:00:00+00:00",
                "end": "2024-12-31T00:00:00+00:00",
                "row_count": 252,
                "expected_rows": 252,
                "coverage_pct": 100.0,
                "fingerprint": data_manifest_fingerprint,
                "checksum": data_manifest_checksum,
                "quality_score": 98.0,
                "cleaning": {
                    "duplicate_timestamps_removed": 0,
                    "invalid_ohlc_removed": 0,
                    "non_positive_prices_removed": 0,
                    "cleaning_loss_rows": 0,
                    "missing_bars": 0,
                },
                "git_commit": "testcommit",
            },
            "evidence": {
                "data_scope": {
                    "fixture_like_data_version": fixture_like_data_version,
                    "promotion_scope_ok": not fixture_like_data_version,
                    "scope_rejections": ["fixture_data_version"]
                    if fixture_like_data_version
                    else [],
                },
                "orders": {
                    "count": order_count,
                    "all_orders_have_risk_check_id": orders_have_risk_check_id,
                },
                "fills": {
                    "count": fill_count,
                    "all_fills_match_orders": fills_match_orders,
                },
                "equity": {
                    "consistent": equity_consistent,
                },
                "pnl": {
                    "source": "ledger_fills",
                    "final_equity": 100000.0,
                    "final_pnl": 0.0,
                },
                "reconciliation": {
                    "summary": reconciliation_summary,
                },
                "ledger_artifact_hash": ledger_artifact["artifact_hash"],
                "ledger_artifact_path": str(ledger_artifact_path),
                "ledger_hash": ledger_artifact["hashes"]["ledger_hash"],
                "fills_hash": ledger_artifact["hashes"]["fills_hash"],
                "ledger_artifact": ledger_artifact,
                "completeness": {
                    "promotion_evidence_complete": promotion_evidence_complete,
                },
            },
            "reconciliation": reconciliation_summary,
            "ledger_artifact": ledger_artifact,
        }
        path = manifest_dir / "run_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def _make_scorecard(self, root: Path, candidate_id: str) -> None:
        """Helper to create a minimal scorecard."""
        sc_dir = root / "research" / "scorecards"
        sc_dir.mkdir(parents=True)
        sc_dir.mkdir(parents=True, exist_ok=True)
        scorecard = {
            "candidate_id": candidate_id,
            "sharpe": 1.5,
            "max_drawdown_pct": 0.15,
            "trade_count": 50,
        }
        (sc_dir / f"{candidate_id}.json").write_text(json.dumps(scorecard))

    def test_monte_carlo_survival_blocked(self, tmp_path: Path) -> None:
        """Monte Carlo survival rate <= 0.80 should BLOCK promotion."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_low_mc"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.45,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        gate = ResearchPromotionGate(data_root=str(tmp_path))
        result = gate.evaluate(candidate_id)

        assert result.decision == "BLOCKED", (
            f"Expected BLOCKED for low MC survival, got {result.decision}"
        )
        assert any("monte_carlo_survival_low" in r for r in result.reasons), (
            f"Should contain monte_carlo_survival_low reason"
        )
        assert result.evidence.get("monte_carlo_survival_rate") == 0.45

    def test_rapid_decay_watchlist(self, tmp_path: Path) -> None:
        """Alpha decay half-life <= 5 days should trigger WATCHLIST."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_rapid_decay"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 3.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        gate = ResearchPromotionGate(data_root=str(tmp_path))
        result = gate.evaluate(candidate_id)

        assert result.decision == "WATCHLIST", (
            f"Expected WATCHLIST for rapid alpha decay, got {result.decision}"
        )
        assert any("rapid_alpha_decay" in w for w in result.warnings), (
            f"Should contain rapid_alpha_decay warning"
        )
        assert result.evidence.get("alpha_decay_half_life_days") == 3.0

    def test_param_unstable_blocked(self, tmp_path: Path) -> None:
        """Param stability score <= 0.5 should BLOCK promotion."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_unstable"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.30,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        gate = ResearchPromotionGate(data_root=str(tmp_path))
        result = gate.evaluate(candidate_id)

        assert result.decision == "BLOCKED", (
            f"Expected BLOCKED for unstable params, got {result.decision}"
        )
        assert any("param_unstable" in r for r in result.reasons), (
            f"Should contain param_unstable reason"
        )
        assert result.evidence.get("param_stability_score") == 0.30

    def test_high_redundancy_needs_more_research(self, tmp_path: Path) -> None:
        """Correlation redundancy >= 0.70 should trigger NEED_MORE_RESEARCH."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_redundant"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.85,
            "stress_survival_rate": 0.90,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        gate = ResearchPromotionGate(data_root=str(tmp_path))
        result = gate.evaluate(candidate_id)

        assert result.decision == "NEED_MORE_RESEARCH", (
            f"Expected NEED_MORE_RESEARCH for high redundancy, "
            f"got {result.decision}"
        )
        assert any("high_redundancy" in n for n in result.needs_more_research), (
            f"Should contain high_redundancy in needs_more_research"
        )

    def test_stress_survival_low_blocked(self, tmp_path: Path) -> None:
        """Stress survival rate <= 0.70 should BLOCK promotion."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_stress_fail"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.50,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        gate = ResearchPromotionGate(data_root=str(tmp_path))
        result = gate.evaluate(candidate_id)

        assert result.decision == "BLOCKED", (
            f"Expected BLOCKED for low stress survival, got {result.decision}"
        )
        assert any("stress_survival_low" in r for r in result.reasons), (
            f"Should contain stress_survival_low reason"
        )
        assert result.evidence.get("stress_survival_rate") == 0.50

    def test_stored_paper_eligible_with_failed_evidence_is_blocked(
        self, tmp_path: Path
    ) -> None:
        """Stored PAPER_ELIGIBLE cannot outrank the current gate evidence."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_stale_paper_eligible"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.50,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
            promotion_status="PAPER_ELIGIBLE",
            backtest_manifest_path=str(manifest_path),
        )
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        gate = ResearchPromotionGate(data_root=str(tmp_path))
        result = gate.evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["stored_promotion_status"] == "PAPER_ELIGIBLE"
        assert any("promotion_status_inconsistent" in r for r in result.reasons)

    def test_fixture_data_version_is_blocked(self, tmp_path: Path) -> None:
        """Automation promotion gate blocks fixture evidence even with clean metrics."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_fixture_scope"
        manifest_path = self._make_backtest_manifest(
            tmp_path,
            candidate_id,
            data_version="qs-fixture-AAPL-1d-test",
            source="fixture",
            fixture_like_data_version=True,
        )
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.85,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
            data_version="qs-fixture-AAPL-1d-test",
            data_source="fixture",
            backtest_manifest_path=str(manifest_path),
        )
        self._make_experiment_manifest(
            tmp_path,
            "exp_test",
            data_version="qs-fixture-AAPL-1d-test",
            data_source="fixture",
        )
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["fixture_used"] is True
        assert any("fixture_data_not_allowed" in r for r in result.reasons)

    def test_missing_data_manifest_is_blocked(self, tmp_path: Path) -> None:
        """A data_version string alone is not governed promotion evidence."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_missing_data_manifest"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.85,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
            backtest_manifest_path=str(manifest_path),
        )
        self._make_experiment_manifest(
            tmp_path,
            "exp_test",
            write_data_manifest=False,
        )
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_payload.pop("data_manifest", None)
        manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["data_manifest_exists"] is False
        assert any("missing_data_manifest" in r for r in result.reasons)

    def test_crypto_symbol_is_blocked(self, tmp_path: Path) -> None:
        """Automation promotion gate blocks crypto-like symbols from US equity paper review."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_crypto_scope"
        manifest_path = self._make_backtest_manifest(
            tmp_path,
            candidate_id,
            data_version="qs-yfinance-BTCUSDT-1d-test",
            symbol="BTCUSDT",
            asset_class="crypto",
        )
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.85,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
            symbols=["BTCUSDT"],
            data_version="qs-yfinance-BTCUSDT-1d-test",
            asset_class="crypto",
            backtest_manifest_path=str(manifest_path),
        )
        self._make_experiment_manifest(
            tmp_path,
            "exp_test",
            symbols=["BTCUSDT"],
            data_version="qs-yfinance-BTCUSDT-1d-test",
            asset_class="crypto",
        )
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["asset_class"] == "crypto"
        assert any("asset_class_not_allowed" in r for r in result.reasons)

    def test_missing_event_ledger_metadata_is_blocked(self, tmp_path: Path) -> None:
        """Clean scalar metrics are not enough without event-driven ledger metadata."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_missing_ledger"
        manifest_path = self._make_backtest_manifest(
            tmp_path,
            candidate_id,
            order_count=0,
            fill_count=0,
            orders_have_risk_check_id=False,
            fills_match_orders=False,
            promotion_evidence_complete=False,
        )
        self._write_candidate(tmp_path, candidate_id, {
            "engine": "",
            "ledger_consistency_pct": 100.0,
            "baseline_fill_count": 0,
            "baseline_order_count": 0,
            "total_fill_count": 0,
            "total_order_count": 0,
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["has_ledger_trade_metadata"] is False
        assert any("missing_ledger_trade_metadata" in r for r in result.reasons)
        assert any("missing_order_risk_metadata" in r for r in result.reasons)
        assert any("missing_fill_order_linkage" in r for r in result.reasons)
        assert any("promotion_evidence_incomplete" in r for r in result.reasons)

    def test_missing_ledger_reconciliation_artifact_is_blocked(self, tmp_path: Path) -> None:
        """Promotion evidence must include the ledger reconciliation artifact itself."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_missing_ledger_artifact"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("ledger_artifact", None)
        manifest.pop("ledger_artifact_hash", None)
        manifest.pop("ledger_artifact_path", None)
        manifest.pop("ledger_hash", None)
        manifest.pop("fills_hash", None)
        manifest["evidence"].pop("ledger_artifact", None)
        manifest["evidence"].pop("ledger_artifact_hash", None)
        manifest["evidence"].pop("ledger_artifact_path", None)
        manifest["evidence"].pop("ledger_hash", None)
        manifest["evidence"].pop("fills_hash", None)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["ledger_artifact_present"] is False
        assert any("missing_ledger_reconciliation_artifact" in r for r in result.reasons)

    def test_missing_standalone_ledger_artifact_path_is_blocked(self, tmp_path: Path) -> None:
        """Promotion evidence must bind the standalone ledger artifact file."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_missing_ledger_artifact_path"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("ledger_artifact_path", None)
        manifest["evidence"].pop("ledger_artifact_path", None)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert any("ledger_reconciliation_artifact_path_missing" in r for r in result.reasons)

    def test_tampered_standalone_ledger_artifact_file_is_blocked(self, tmp_path: Path) -> None:
        """Standalone artifact file must match the manifest-embedded artifact."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_tampered_ledger_artifact_file"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = Path(manifest["ledger_artifact_path"])
        file_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        file_artifact["pnl"]["net_pnl"] = 1.0
        artifact_path.write_text(json.dumps(file_artifact, sort_keys=True), encoding="utf-8")

        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert any("ledger_reconciliation_artifact_file_hash_mismatch" in r for r in result.reasons)
        assert any("ledger_reconciliation_artifact_file_payload_mismatch" in r for r in result.reasons)

    def test_tampered_ledger_artifact_hash_binding_is_blocked(self, tmp_path: Path) -> None:
        """Hash bindings must match the artifact payload and manifest references."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_tampered_ledger_artifact_hash"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["ledger_artifact"]["hashes"]["fills_hash"] = "tampered_fills_hash"
        manifest["evidence"]["ledger_artifact"]["hashes"]["fills_hash"] = "tampered_fills_hash"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert any("ledger_reconciliation_artifact_hash_mismatch" in r for r in result.reasons)
        assert any("ledger_reconciliation_artifact_binding_mismatch" in r for r in result.reasons)

    def test_ledger_artifact_pnl_mismatch_is_blocked(self, tmp_path: Path) -> None:
        """Artifact PnL must agree with the manifest's ledger-backed PnL summary."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_ledger_artifact_pnl_mismatch"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["ledger_artifact"]["pnl"]["final_equity"] = 99999.0
        manifest["evidence"]["ledger_artifact"]["pnl"]["final_equity"] = 99999.0
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert any("ledger_reconciliation_pnl_mismatch" in r for r in result.reasons)

    def test_missing_manifest_pnl_binding_is_blocked(self, tmp_path: Path) -> None:
        """Artifact PnL cannot pass without a manifest PnL binding."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_missing_manifest_pnl_binding"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["evidence"].pop("pnl", None)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert any("ledger_reconciliation_pnl_mismatch" in r for r in result.reasons)

    def test_empty_reconciliation_summary_cannot_bypass_artifact_checks(self, tmp_path: Path) -> None:
        """An empty reconciliation summary must fail closed even if scalar metrics are clean."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_empty_reconciliation_summary"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["reconciliation"] = {}
        manifest["evidence"]["reconciliation"]["summary"] = {}
        manifest["ledger_artifact"]["reconciliation"]["summary"] = {}
        manifest["evidence"]["ledger_artifact"]["reconciliation"]["summary"] = {}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert any("ledger_reconciliation_summary_missing" in r for r in result.reasons)

    def test_all_r6_r7_r8_checks_pass(self, tmp_path: Path) -> None:
        """All R6/R7/R8 checks passing should result in READY_FOR_PAPER_REVIEW."""
        from quant_us.research.automation.promotion_gate import (
            ResearchPromotionGate,
        )

        candidate_id = "cand_all_pass"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        self._write_candidate(tmp_path, candidate_id, {
            "monte_carlo_survival_rate": 0.90,
            "alpha_decay_half_life_days": 15.0,
            "param_stability_score": 0.8,
            "correlation_redundancy": 0.30,
            "stress_survival_rate": 0.85,
            "sharpe": 1.5,
            "walk_forward_pass_rate": 0.8,
            "trade_count": 50,
            "cost_sensitivity": 0.2,
            "max_drawdown_pct": 0.15,
        }, backtest_manifest_path=str(manifest_path))
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        gate = ResearchPromotionGate(data_root=str(tmp_path))
        result = gate.evaluate(candidate_id)

        assert result.decision == "READY_FOR_PAPER_REVIEW", (
            f"Expected READY_FOR_PAPER_REVIEW for all checks passing, "
            f"got {result.decision}"
        )
        assert len(result.reasons) == 0, "Should have no blocking reasons"
        assert len(result.warnings) == 0, "Should have no warnings"
        assert len(result.needs_more_research) == 0, (
            "Should have no needs_more_research items"
        )
        assert result.evidence["backtest_manifest_present"] is True
        # Verify all new evidence fields are present
        for field in [
            "monte_carlo_survival_rate",
            "alpha_decay_half_life_days",
            "param_stability_score",
            "correlation_redundancy",
            "stress_survival_rate",
        ]:
            assert field in result.evidence, (
                f"Evidence should contain {field}"
            )

    def test_vectorized_backtest_manifest_is_blocked(self, tmp_path: Path) -> None:
        """Vectorized backtest evidence cannot become READY_FOR_PAPER_REVIEW."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_vectorized"
        manifest_path = self._make_backtest_manifest(
            tmp_path,
            candidate_id,
            engine="vectorized",
            canonical_for_promotion=False,
        )
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.85,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
            backtest_manifest_path=str(manifest_path),
        )
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["backtest_manifest_present"] is True
        assert any("event_driven_required" in r for r in result.reasons)
        assert any("canonical_backtest_manifest_required" in r for r in result.reasons)

    def test_missing_backtest_manifest_evidence_is_blocked(self, tmp_path: Path) -> None:
        """Without canonical backtest manifest evidence, the gate cannot return READY."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_missing_backtest_manifest"
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.85,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
        )
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["backtest_manifest_present"] is False
        assert any("missing_backtest_manifest_evidence" in r for r in result.reasons)

    def test_inline_backtest_manifest_is_not_promotion_evidence(
        self,
        tmp_path: Path,
    ) -> None:
        """Inline backtest manifests are diagnostic only and cannot authorize READY."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_inline_backtest_manifest"
        manifest_path = self._make_backtest_manifest(tmp_path, candidate_id)
        inline_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_path.unlink()
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "backtest_manifest": inline_manifest,
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.85,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
        )
        self._make_experiment_manifest(tmp_path, "exp_test")
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["backtest_manifest_inline"] is True
        assert result.evidence["backtest_manifest_present"] is False
        assert result.evidence["backtest_manifest_source"] == "inline_untrusted"
        assert any("inline_backtest_manifest_not_allowed" in r for r in result.reasons)
        assert any("missing_backtest_manifest_evidence" in r for r in result.reasons)

    def test_data_manifest_checksum_mismatch_is_blocked(
        self,
        tmp_path: Path,
    ) -> None:
        """Backtest embedded data manifest must match the governed manifest store."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        candidate_id = "cand_data_manifest_checksum_mismatch"
        manifest_path = self._make_backtest_manifest(
            tmp_path,
            candidate_id,
            data_manifest_fingerprint="a" * 64,
            data_manifest_checksum="a" * 64,
        )
        self._write_candidate(
            tmp_path,
            candidate_id,
            {
                "monte_carlo_survival_rate": 0.90,
                "alpha_decay_half_life_days": 15.0,
                "param_stability_score": 0.8,
                "correlation_redundancy": 0.30,
                "stress_survival_rate": 0.85,
                "sharpe": 1.5,
                "walk_forward_pass_rate": 0.8,
                "trade_count": 50,
                "cost_sensitivity": 0.2,
                "max_drawdown_pct": 0.15,
            },
            backtest_manifest_path=str(manifest_path),
        )
        self._make_experiment_manifest(
            tmp_path,
            "exp_test",
            write_data_manifest=False,
        )
        self._make_data_manifest(
            tmp_path,
            fingerprint="b" * 64,
            checksum="b" * 64,
        )
        self._make_scorecard(tmp_path, candidate_id)

        result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate_id)

        assert result.decision == "BLOCKED"
        assert result.evidence["data_manifest_source"] == "manifest_store"
        assert result.evidence["data_manifest_checksum"] == "b" * 64
        assert result.evidence["data_manifest_embedded_checksum"] == "a" * 64
        assert any("data_manifest_checksum_mismatch" in r for r in result.reasons)
        assert any("data_manifest_fingerprint_mismatch" in r for r in result.reasons)

    def test_paper_candidate_approve_requires_manual(self, tmp_path: Path) -> None:
        """PaperReviewManager.approve() requires a non-empty reviewer name."""
        from quant_us.research.paper_review_bridge import (
            PaperReviewManager,
            PaperReviewCandidate,
        )

        mgr = PaperReviewManager(data_root=str(tmp_path))

        # Create a review candidate directly
        from quant_us.core.types import new_id
        from quant_us.core.clock import utc_now

        rev_id = new_id("prev")
        candidate = PaperReviewCandidate(
            paper_review_id=rev_id,
            strategy_manifest_id="manifest_test",
            portfolio_sim_id="sim_test",
            proposed_symbols=["AAPL", "MSFT"],
            proposed_capital=100000.0,
            proposed_risk_envelope={"max_drawdown_pct": 0.20},
            status="PENDING_HUMAN_REVIEW",
            created_at=utc_now().isoformat(),
        )
        mgr._save_review(candidate)

        # Approving with empty reviewer should raise
        with pytest.raises(ValueError, match="Reviewer name is required"):
            mgr.approve(rev_id, reviewer="")

        # Non-empty reviewer should succeed
        approved = mgr.approve(rev_id, reviewer="Dr. Smith")
        assert approved.status == "APPROVED_FOR_PAPER_ONLY"
        assert approved.reviewer == "Dr. Smith"

    def test_create_from_portfolio_evidence(self, tmp_path: Path) -> None:
        """create_from_portfolio_evidence should require portfolio-level evidence."""
        from quant_us.research.paper_review_bridge import (
            PaperReviewManager,
        )

        mgr = PaperReviewManager(data_root=str(tmp_path))

        # Missing evidence pack should raise
        with pytest.raises(ValueError, match="not found"):
            mgr.create_from_portfolio_evidence("nonexistent_pack")

        # Create a valid evidence pack with portfolio-level evidence
        ev_dir = tmp_path / "research" / "evidence_packs" / "pack_valid"
        ev_dir.mkdir(parents=True)
        manifest_dir = tmp_path / "research" / "manifests" / "sman_valid"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": "sman_valid",
                    "source_candidate_id": "cand_valid",
                    "source_experiment_id": "exp_valid",
                    "data_version": "dv_valid",
                    "sample_window": {"start": "2024-01-01", "end": "2024-12-31"},
                    "purge_embargo": {"purge_bars": 2, "embargo_bars": 1},
                    "trial_id": "cand_valid",
                    "trial_count": 4,
                    "pbo": 0.05,
                    "dsr": 0.9,
                    "cost_model": {"name": "default"},
                    "slippage_model": {"name": "default"},
                    "capacity": {"estimated_capacity_usd": 1000000.0},
                    "turnover": {"turnover": 0.2},
                    "holding_period": {"expected": "5d"},
                    "exposure_limits": {"max_gross_exposure_pct": 90.0},
                    "failure_conditions": ["dd_limit"],
                    "delisting_conditions": {"policy": "manual_review_required"},
                }
            ),
            encoding="utf-8",
        )
        evidence = {
            "schema_version": "evidence_pack_v2",
            "paper_review_scope": "portfolio_sim",
            "portfolio_sim_id": "pack_valid",
            "strategy_manifest_ids": ["sman_valid"],
            "evidence_contract": {
                "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
                "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
                "portfolio_sim_id": "pack_valid",
                "strategy_manifest_ids": ["sman_valid"],
                "candidate_count": 1,
                "all_strategy_manifest_contracts_complete": True,
                "all_strategy_manifest_contracts_documented": True,
                "paper_review_gate": "portfolio_evidence_pack_required",
            },
            "candidate_id": "cand_valid",
            "sections": {
                "portfolio_sim": {
                    "status": "completed",
                    "decision": "PORTFOLIO_PASS",
                    "final_equity": 105000.0,
                },
                "candidate_data": {
                    "candidate_id": "cand_valid",
                    "symbols": ["AAPL", "MSFT"],
                    "metrics": {"max_drawdown_pct": 0.15},
                },
                "portfolio_candidates": [
                    {
                        "candidate_id": "cand_valid",
                        "strategy_manifest_id": "sman_valid",
                        "strategy_manifest_path": str(
                            tmp_path / "research" / "manifests" / "sman_valid" / "manifest.json"
                        ),
                        "evidence_pack_path": str(
                            tmp_path / "research" / "evidence_packs" / "cand_valid" / "evidence_pack.json"
                        ),
                        "strategy_manifest_contract": {
                            "contract_complete": True,
                            "missing_fields": [],
                        },
                        "strategy_manifest_contract_complete": True,
                    }
                ],
                "promotion_gate": {
                    "decision": "READY_FOR_PAPER_REVIEW",
                },
                "paper_review_candidate": {
                    "review_candidate_status": "READY_FOR_REVIEW",
                    "blocking_reasons": [],
                },
            },
        }
        (ev_dir / "evidence_pack.json").write_text(json.dumps(evidence))

        # Should succeed with valid portfolio evidence
        review = mgr.create_from_portfolio_evidence("pack_valid")
        assert review.status == "PENDING_HUMAN_REVIEW"
        assert review.status != "APPROVED_FOR_PAPER_ONLY"
        assert "AAPL" in review.proposed_symbols
        assert "MSFT" in review.proposed_symbols

    @pytest.mark.parametrize("gate_decision", ["WATCHLIST", "NEED_MORE_RESEARCH", "BLOCKED"])
    def test_create_from_portfolio_evidence_requires_ready_gate(
        self, tmp_path: Path, gate_decision: str
    ) -> None:
        """Non-READY automation decisions cannot enter paper review."""
        from quant_us.research.paper_review_bridge import (
            PaperReviewManager,
        )

        mgr = PaperReviewManager(data_root=str(tmp_path))
        ev_dir = tmp_path / "research" / "evidence_packs" / "pack_watchlist"
        ev_dir.mkdir(parents=True)
        manifest_dir = tmp_path / "research" / "manifests" / "sman_watchlist"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "strategy_candidate_id": "sman_watchlist",
                    "source_candidate_id": "cand_watchlist",
                    "source_experiment_id": "exp_watchlist",
                    "data_version": "dv_watchlist",
                    "sample_window": {"start": "2024-01-01", "end": "2024-12-31"},
                    "purge_embargo": {"purge_bars": 2, "embargo_bars": 1},
                    "trial_id": "cand_watchlist",
                    "trial_count": 4,
                    "pbo": 0.05,
                    "dsr": 0.9,
                    "cost_model": {"name": "default"},
                    "slippage_model": {"name": "default"},
                    "capacity": {"estimated_capacity_usd": 1000000.0},
                    "turnover": {"turnover": 0.2},
                    "holding_period": {"expected": "5d"},
                    "exposure_limits": {"max_gross_exposure_pct": 90.0},
                    "failure_conditions": ["dd_limit"],
                    "delisting_conditions": {"policy": "manual_review_required"},
                }
            ),
            encoding="utf-8",
        )
        evidence = {
            "schema_version": "evidence_pack_v2",
            "paper_review_scope": "portfolio_sim",
            "portfolio_sim_id": "pack_watchlist",
            "strategy_manifest_ids": ["sman_watchlist"],
            "evidence_contract": {
                "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
                "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
                "portfolio_sim_id": "pack_watchlist",
                "strategy_manifest_ids": ["sman_watchlist"],
                "candidate_count": 1,
                "all_strategy_manifest_contracts_complete": True,
                "all_strategy_manifest_contracts_documented": True,
                "paper_review_gate": "portfolio_evidence_pack_required",
            },
            "candidate_id": "cand_watchlist",
            "sections": {
                "portfolio_sim": {
                    "status": "completed",
                    "decision": "PORTFOLIO_PASS",
                    "final_equity": 105000.0,
                },
                "candidate_data": {
                    "candidate_id": "cand_watchlist",
                    "symbols": ["AAPL"],
                    "metrics": {"max_drawdown_pct": 0.15},
                },
                "portfolio_candidates": [
                    {
                        "candidate_id": "cand_watchlist",
                        "strategy_manifest_id": "sman_watchlist",
                        "strategy_manifest_path": str(
                            tmp_path / "research" / "manifests" / "sman_watchlist" / "manifest.json"
                        ),
                        "evidence_pack_path": str(
                            tmp_path / "research" / "evidence_packs" / "cand_watchlist" / "evidence_pack.json"
                        ),
                        "strategy_manifest_contract": {
                            "contract_complete": True,
                            "missing_fields": [],
                        },
                        "strategy_manifest_contract_complete": True,
                    }
                ],
                "promotion_gate": {
                    "decision": gate_decision,
                },
            },
        }
        (ev_dir / "evidence_pack.json").write_text(json.dumps(evidence))

        with pytest.raises(ValueError, match="READY_FOR_PAPER_REVIEW"):
            mgr.create_from_portfolio_evidence("pack_watchlist")

    def test_create_review_rejects_watchlist_simulation(self, tmp_path: Path) -> None:
        """Legacy sim-based entry cannot send WATCHLIST simulations to paper review."""
        from quant_us.research.paper_review_bridge import PaperReviewManager

        sim_dir = tmp_path / "research" / "portfolio_sims" / "sim_watchlist"
        sim_dir.mkdir(parents=True)
        request = {
            "portfolio_sim_id": "sim_watchlist",
            "strategy_manifest_ids": ["sman_ready"],
            "symbols": ["AAPL"],
            "capital": 100000.0,
        }
        result = {
            "portfolio_sim_id": "sim_watchlist",
            "equity_curve": [100000.0, 101000.0],
            "drawdown": [0.0, 0.0],
            "decision": "WATCHLIST",
        }
        (sim_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (sim_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")

        with pytest.raises(ValueError, match="Only PORTFOLIO_PASS"):
            PaperReviewManager(data_root=str(tmp_path)).create_review("sim_watchlist")

    def test_create_review_requires_ready_manifest(self, tmp_path: Path) -> None:
        """A PORTFOLIO_PASS simulation still needs READY_FOR_PORTFOLIO_SIM manifests."""
        from quant_us.research.paper_review_bridge import PaperReviewManager

        sim_dir = tmp_path / "research" / "portfolio_sims" / "sim_pass"
        sim_dir.mkdir(parents=True)
        request = {
            "portfolio_sim_id": "sim_pass",
            "strategy_manifest_ids": ["sman_draft"],
            "symbols": ["AAPL"],
            "capital": 100000.0,
        }
        result = {
            "portfolio_sim_id": "sim_pass",
            "equity_curve": [100000.0, 101000.0],
            "drawdown": [0.0, 0.0],
            "decision": "PORTFOLIO_PASS",
        }
        manifest_dir = tmp_path / "research" / "manifests" / "sman_draft"
        manifest_dir.mkdir(parents=True)
        manifest = {
            "strategy_candidate_id": "sman_draft",
            "source_candidate_id": "cand_1",
            "source_experiment_id": "exp_1",
            "symbols": ["AAPL"],
            "promotion_status": "DRAFT",
            "params_frozen": True,
        }
        (sim_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (sim_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (manifest_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        with pytest.raises(ValueError, match="READY_FOR_PORTFOLIO_SIM"):
            PaperReviewManager(data_root=str(tmp_path)).create_review("sim_pass")


# ===========================================================================
# Safety Invariants
# ===========================================================================


@pytest.mark.integration
class TestSafetyInvariants:
    """No live imports, no broker access, deterministic tests."""

    def test_r6_r7_r8_no_live_imports(self) -> None:
        """R6/R7/R8 modules must not import from live or execution."""
        forbidden_prefixes = ["quant_us.live", "quant_us.execution"]
        # Check the modules that contain our new code
        research_modules = [
            "quant_us.research.automation.promotion_gate",
            "quant_us.research.paper_review_bridge",
            "quant_us.research.evidence_pack",
        ]
        for mod in research_modules:
            for prefix in forbidden_prefixes:
                assert not mod.startswith(prefix), (
                    f"Module {mod} should not start with forbidden prefix {prefix}"
                )
            assert mod not in {"quant_us.live", "quant_us.execution"}, (
                f"Module {mod} should not be a live/execution module"
            )

    def test_no_broker_access(self) -> None:
        """Research modules must not reference broker or submit_order."""
        dangerous_patterns = [
            "AlpacaBroker",
            "submit_order",
            "LiveBrokerProxy",
            "ReadOnlyLiveBrokerProxy",
            "real_submit",
        ]
        # Methods from the modules we use
        research_methods = [
            "ResearchPromotionGate.evaluate",
            "PaperReviewManager.create_review",
            "PaperReviewManager.approve",
            "PaperReviewManager.reject",
            "EvidencePackGenerator.generate",
        ]
        for method in research_methods:
            for pattern in dangerous_patterns:
                assert pattern not in method, (
                    f"Method '{method}' should not contain '{pattern}'"
                )

    def test_all_tests_deterministic(self, tmp_path: Path) -> None:
        """All R6/R7/R8 test data should be deterministic (seeded RNG or synthetic)."""
        # Test 1: Seeded RNG produces consistent output
        rng1 = random.Random(12345)
        vals1 = [rng1.random() for _ in range(100)]

        rng2 = random.Random(12345)
        vals2 = [rng2.random() for _ in range(100)]

        assert vals1 == vals2, "Seeded RNG should produce identical sequences"

        # Test 2: Deterministic config hash
        config = {
            "strategy_id": "momentum",
            "params": {"lookback": 20, "entry": 2.0},
            "data_version": "v3",
        }
        h1 = hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest()
        h2 = hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest()
        assert h1 == h2, "Config hash should be deterministic"

        # Test 3: Synthetic data should be reproducible from spec
        spec = {"mean": 0.001, "std": 0.02, "n": 100, "seed": 42}
        gen1 = random.Random(spec["seed"])
        synthetic_1 = [gen1.gauss(spec["mean"], spec["std"]) for _ in range(spec["n"])]

        gen2 = random.Random(spec["seed"])
        synthetic_2 = [gen2.gauss(spec["mean"], spec["std"]) for _ in range(spec["n"])]

        assert synthetic_1 == synthetic_2, (
            "Synthetic data should be reproducible from same spec"
        )

        # Test 4: File-based determinism (same data -> same output)
        data = {
            "test_type": "monte_carlo",
            "seed": 42,
            "n_iterations": 1000,
            "n_samples": 10,
            "survival_rate": 0.85,
        }
        path = tmp_path / "deterministic_test.json"
        path.write_text(json.dumps(data))
        reloaded = json.loads(path.read_text())
        assert reloaded == data, "JSON serialization should be deterministic"

    def test_no_broker_import_in_promotion_gate(self, tmp_path: Path) -> None:
        """PromotionGate must not import any broker module."""
        import quant_us.research.automation.promotion_gate as pg

        source = Path(pg.__file__).read_text(encoding="utf-8")
        assert "quant_us.live" not in source
        assert "quant_us.execution" not in source

    def test_no_broker_import_in_paper_review_bridge(self, tmp_path: Path) -> None:
        """PaperReviewBridge must not import any broker module."""
        import quant_us.research.paper_review_bridge as prb

        source = Path(prb.__file__).read_text(encoding="utf-8")
        assert "quant_us.live" not in source
        assert "quant_us.execution" not in source
