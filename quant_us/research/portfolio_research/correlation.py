"""Correlation cluster analysis for multi-strategy portfolios.

Analyses correlation among strategy manifests to detect redundancy,
compute diversification scores, and identify clustered strategies.
NEVER submits orders or triggers trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ClusterResult:
    """Result of a correlation cluster analysis."""

    strategy_ids: list[str]
    correlation_matrix: dict[str, dict[str, float]]
    cluster_labels: list[int]
    redundancy_score: float = 0.0
    diversification_score: float = 0.0
    redundant_pairs: list[tuple[str, str, float]] = field(default_factory=list)


class CorrelationClusterAnalyzer:
    """Analyze correlation structure across strategy manifests.

    Loads manifest scorecards to estimate pairwise correlations,
    then clusters strategies and quantifies redundancy / diversification.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.manifests_dir = self.data_root / "research" / "manifests"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        strategy_manifest_ids: list[str],
    ) -> ClusterResult:
        """Run full correlation analysis for a set of strategy manifests.

        Args:
            strategy_manifest_ids: List of strategy manifest IDs.

        Returns:
            ClusterResult with correlation matrix, cluster labels,
            redundancy/diversification scores, and redundant pairs.

        Raises:
            ValueError: If fewer than 2 manifests provided, or a manifest
                        is not found.
        """
        if len(strategy_manifest_ids) < 2:
            raise ValueError("Need at least 2 strategy manifests for correlation analysis")

        manifests = self._load_manifests(strategy_manifest_ids)
        corr_matrix = self._build_correlation_matrix(manifests)

        cluster_labels = self.detect_clusters(corr_matrix)
        redundant_pairs = self.find_redundant_pairs(corr_matrix)
        redundancy_score = self._compute_redundancy(corr_matrix)
        diversification_score = self.compute_diversification(corr_matrix)

        return ClusterResult(
            strategy_ids=list(corr_matrix.keys()),
            correlation_matrix=corr_matrix,
            cluster_labels=cluster_labels,
            redundancy_score=redundancy_score,
            diversification_score=diversification_score,
            redundant_pairs=redundant_pairs,
        )

    def detect_clusters(
        self,
        corr_matrix: dict[str, dict[str, float]],
        threshold: float = 0.70,
    ) -> list[int]:
        """Assign each strategy to a cluster based on correlation threshold.

        Uses a simple greedy approach: iterate strategies, if correlation
        with any member of existing cluster exceeds threshold, join it.

        Args:
            corr_matrix: Strategy ID -> {peer_id -> correlation}.
            threshold: Correlation threshold for cluster membership (default 0.70).

        Returns:
            List of cluster labels (ints), same order as corr_matrix keys.
        """
        ids = list(corr_matrix.keys())
        labels: list[int] = [-1] * len(ids)
        next_label = 0

        for i, sid in enumerate(ids):
            if labels[i] != -1:
                continue
            labels[i] = next_label
            for j in range(i + 1, len(ids)):
                if labels[j] != -1:
                    continue
                corr = corr_matrix.get(sid, {}).get(ids[j], 0.0)
                if abs(corr) >= threshold:
                    labels[j] = next_label
            next_label += 1

        # Assign un-clustered (still -1) singletons
        for i in range(len(ids)):
            if labels[i] == -1:
                labels[i] = next_label
                next_label += 1

        return labels

    def find_redundant_pairs(
        self,
        corr_matrix: dict[str, dict[str, float]],
        threshold: float = 0.80,
    ) -> list[tuple[str, str, float]]:
        """Find pairs of strategies with correlation above threshold.

        Args:
            corr_matrix: Correlation matrix.
            threshold: Correlation threshold for redundancy (default 0.80).

        Returns:
            List of (strategy_1, strategy_2, correlation) tuples sorted
            by absolute correlation descending.
        """
        pairs: list[tuple[str, str, float]] = []
        ids = list(corr_matrix.keys())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                corr = corr_matrix.get(ids[i], {}).get(ids[j], 0.0)
                if abs(corr) >= threshold:
                    pairs.append((ids[i], ids[j], round(corr, 4)))

        pairs.sort(key=lambda x: -abs(x[2]))
        return pairs

    def compute_diversification(
        self,
        corr_matrix: dict[str, dict[str, float]],
    ) -> float:
        """Compute diversification score as 1 - mean(|correlation|).

        A score of 1.0 means perfectly diversified (all correlations zero).
        A score of 0.0 means perfectly correlated.

        Args:
            corr_matrix: Correlation matrix.

        Returns:
            Diversification score in [0, 1].
        """
        ids = list(corr_matrix.keys())
        if len(ids) < 2:
            return 1.0

        total_abs_corr = 0.0
        pair_count = 0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total_abs_corr += abs(corr_matrix.get(ids[i], {}).get(ids[j], 0.0))
                pair_count += 1

        mean_abs_corr = total_abs_corr / max(pair_count, 1)
        return max(0.0, min(1.0, 1.0 - mean_abs_corr))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_manifests(self, manifest_ids: list[str]) -> list[Any]:
        """Load strategy manifests from disk."""
        from quant_us.research.strategy_manifest import StrategyManifestManager

        mgr = StrategyManifestManager(data_root=str(self.data_root))
        manifests: list[Any] = []
        for mid in manifest_ids:
            m = mgr.load(mid)
            if m is None:
                raise ValueError(f"Strategy manifest {mid} not found")
            manifests.append(m)
        return manifests

    def _build_correlation_matrix(
        self,
        manifests: list[Any],
    ) -> dict[str, dict[str, float]]:
        """Build pairwise correlation matrix from manifest scorecards."""
        from quant_us.research.portfolio_sim_bridge import PortfolioSimBridge

        bridge = PortfolioSimBridge(data_root=str(self.data_root))
        matrix: dict[str, dict[str, float]] = {}
        for m1 in manifests:
            sid1 = m1.strategy_candidate_id
            matrix[sid1] = {}
            for m2 in manifests:
                sid2 = m2.strategy_candidate_id
                corr = bridge._estimate_correlation(m1, m2)
                matrix[sid1][sid2] = corr
        return matrix

    def _compute_redundancy(
        self,
        corr_matrix: dict[str, dict[str, float]],
    ) -> float:
        """Compute redundancy score as mean absolute correlation among all pairs.

        Returns value in [0, 1]; higher = more redundant.
        """
        ids = list(corr_matrix.keys())
        if len(ids) < 2:
            return 0.0

        total_abs_corr = 0.0
        pair_count = 0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total_abs_corr += abs(corr_matrix.get(ids[i], {}).get(ids[j], 0.0))
                pair_count += 1

        return total_abs_corr / max(pair_count, 1)
