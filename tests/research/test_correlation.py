"""Tests for CorrelationClusterAnalyzer."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from quant_us.research.portfolio_research.correlation import (
    ClusterResult,
    CorrelationClusterAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers: create fake manifests for testing
# ---------------------------------------------------------------------------


@dataclass
class FakeManifest:
    strategy_candidate_id: str
    scorecard: dict = field(default_factory=dict)
    params_frozen: bool = True
    strategy_template: str = "momentum"
    symbols: list[str] = field(default_factory=list)


def _make_manifest_mgr(tmpdir: str, manifests: list[FakeManifest]) -> Any:
    """Create and return a StrategyManifestManager with fake manifests."""
    from quant_us.research.strategy_manifest import (
        StrategyManifestManager,
        StrategyCandidateManifest,
    )

    mgr = StrategyManifestManager(data_root=tmpdir)
    for m in manifests:
        sm = StrategyCandidateManifest(
            strategy_candidate_id=m.strategy_candidate_id,
            source_candidate_id=m.strategy_candidate_id,
            source_experiment_id="exp_1",
            strategy_template=m.strategy_template,
            params_frozen=m.params_frozen,
            symbols=m.symbols,
            scorecard=m.scorecard,
        )
        # Save directly
        path = mgr.manifests_dir / sm.strategy_candidate_id / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        import dataclasses
        path.write_text(
            json.dumps(dataclasses.asdict(sm), indent=2, default=str),
            encoding="utf-8",
        )
    return mgr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCorrelationClusterAnalyzer:
    """Tests for CorrelationClusterAnalyzer."""

    def test_analyze_requires_at_least_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CorrelationClusterAnalyzer(data_root=tmpdir)
            with pytest.raises(ValueError, match="at least 2"):
                analyzer.analyze(["manifest_1"])

    def test_analyze_returns_cluster_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_manifests = [
                FakeManifest(
                    strategy_candidate_id="strat_1",
                    strategy_template="momentum",
                    scorecard={"sharpe_ratio": 1.5, "max_drawdown_pct": 0.1, "total_return_pct": 15.0},
                ),
                FakeManifest(
                    strategy_candidate_id="strat_2",
                    strategy_template="value",
                    scorecard={"sharpe_ratio": 0.8, "max_drawdown_pct": 0.2, "total_return_pct": 8.0},
                ),
            ]
            _make_manifest_mgr(tmpdir, fake_manifests)
            analyzer = CorrelationClusterAnalyzer(data_root=tmpdir)
            result = analyzer.analyze(["strat_1", "strat_2"])
            assert isinstance(result, ClusterResult)
            assert result.strategy_ids == ["strat_1", "strat_2"]
            assert "strat_1" in result.correlation_matrix
            assert "strat_2" in result.correlation_matrix
            assert len(result.cluster_labels) == 2
            assert 0.0 <= result.diversification_score <= 1.0
            assert 0.0 <= result.redundancy_score <= 1.0

    def test_analyze_rejects_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = CorrelationClusterAnalyzer(data_root=tmpdir)
            with pytest.raises(ValueError, match="not found"):
                analyzer.analyze(["does_not_exist", "also_missing"])

    def test_detect_clusters_no_clustering(self) -> None:
        """Low correlation => each strategy is its own cluster."""
        corr_matrix = {
            "s1": {"s1": 1.0, "s2": 0.1, "s3": 0.05},
            "s2": {"s1": 0.1, "s2": 1.0, "s3": 0.2},
            "s3": {"s1": 0.05, "s2": 0.2, "s3": 1.0},
        }
        analyzer = CorrelationClusterAnalyzer()
        labels = analyzer.detect_clusters(corr_matrix, threshold=0.70)
        assert len(labels) == 3
        assert len(set(labels)) == 3  # each its own cluster

    def test_detect_clusters_high_correlation(self) -> None:
        """High correlation => all in same cluster."""
        corr_matrix = {
            "s1": {"s1": 1.0, "s2": 0.85, "s3": 0.82},
            "s2": {"s1": 0.85, "s2": 1.0, "s3": 0.91},
            "s3": {"s1": 0.82, "s2": 0.91, "s3": 1.0},
        }
        analyzer = CorrelationClusterAnalyzer()
        labels = analyzer.detect_clusters(corr_matrix, threshold=0.70)
        assert len(labels) == 3
        assert len(set(labels)) == 1  # all same cluster

    def test_find_redundant_pairs(self) -> None:
        corr_matrix = {
            "s1": {"s1": 1.0, "s2": 0.9, "s3": 0.3},
            "s2": {"s1": 0.9, "s2": 1.0, "s3": 0.4},
            "s3": {"s1": 0.3, "s2": 0.4, "s3": 1.0},
        }
        analyzer = CorrelationClusterAnalyzer()
        pairs = analyzer.find_redundant_pairs(corr_matrix, threshold=0.80)
        assert len(pairs) == 1
        assert pairs[0][0] in ("s1", "s2")
        assert pairs[0][1] in ("s1", "s2")
        assert pairs[0][0] != pairs[0][1]

    def test_find_redundant_pairs_no_threshold_exceeded(self) -> None:
        corr_matrix = {
            "s1": {"s1": 1.0, "s2": 0.3, "s3": 0.4},
            "s2": {"s1": 0.3, "s2": 1.0, "s3": 0.5},
            "s3": {"s1": 0.4, "s2": 0.5, "s3": 1.0},
        }
        analyzer = CorrelationClusterAnalyzer()
        pairs = analyzer.find_redundant_pairs(corr_matrix, threshold=0.80)
        assert len(pairs) == 0

    def test_compute_diversification_perfect(self) -> None:
        """Zero correlations => perfect diversification."""
        corr_matrix = {
            "s1": {"s1": 1.0, "s2": 0.0, "s3": 0.0},
            "s2": {"s1": 0.0, "s2": 1.0, "s3": 0.0},
            "s3": {"s1": 0.0, "s2": 0.0, "s3": 1.0},
        }
        analyzer = CorrelationClusterAnalyzer()
        score = analyzer.compute_diversification(corr_matrix)
        assert score == 1.0

    def test_compute_diversification_none(self) -> None:
        """Perfect correlations => no diversification."""
        corr_matrix = {
            "s1": {"s1": 1.0, "s2": 1.0, "s3": 1.0},
            "s2": {"s1": 1.0, "s2": 1.0, "s3": 1.0},
            "s3": {"s1": 1.0, "s2": 1.0, "s3": 1.0},
        }
        analyzer = CorrelationClusterAnalyzer()
        score = analyzer.compute_diversification(corr_matrix)
        assert score == 0.0

    def test_compute_diversification_single(self) -> None:
        """Single strategy => full diversification."""
        corr_matrix = {"s1": {"s1": 1.0}}
        analyzer = CorrelationClusterAnalyzer()
        score = analyzer.compute_diversification(corr_matrix)
        assert score == 1.0

    def test_redundancy_score_vs_diversification(self) -> None:
        """Redundancy + diversification should sum to approximately 1."""
        corr_matrix = {
            "s1": {"s1": 1.0, "s2": 0.6, "s3": 0.4},
            "s2": {"s1": 0.6, "s2": 1.0, "s3": 0.5},
            "s3": {"s1": 0.4, "s2": 0.5, "s3": 1.0},
        }
        analyzer = CorrelationClusterAnalyzer()
        redundancy = analyzer._compute_redundancy(corr_matrix)
        diversification = analyzer.compute_diversification(corr_matrix)
        # Should be inverse: redundancy = mean(absolute corr), diversification = 1 - mean(absolute corr)
        assert abs(redundancy + diversification - 1.0) < 1e-10
