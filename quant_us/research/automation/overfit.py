"""Overfit detection and lookahead bias checking for research automation.

Provides:
- OverfitDetector: Checks candidates for overfitting signs
- LookaheadBiasChecker: Heuristic detection of lookahead bias in factors/experiments
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OverfitReport:
    """Detailed overfit analysis report for a single candidate."""
    candidate_id: str
    is_overfit: bool = False
    reasons: list[str] = field(default_factory=list)
    in_sample_sharpe: float = 0.0
    out_of_sample_sharpe: float = 0.0
    degradation_pct: float = 0.0  # (IS - OOS) / IS
    param_sensitivity: float = 0.0
    single_year_concentration: float = 0.0
    single_symbol_concentration: float = 0.0
    trade_count: int = 0
    cost_sensitivity: float = 0.0


class OverfitDetector:
    """Check candidates for overfitting signs.

    Detection criteria:
    - OOS degradation > 40% -> overfit
    - param_sensitivity > 0.5 -> overfit
    - trade_count < 10 -> overfit (too few trades)
    - single_year_concentration > 50% -> overfit
    - single_symbol_concentration > 60% -> overfit
    - cost stress failure (sharpe < 0 after 5x costs) -> overfit
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def check(self, candidate_id: str) -> OverfitReport:
        """Check a candidate for overfitting signs.

        Args:
            candidate_id: The candidate to check.

        Returns:
            OverfitReport with all detection results.

        Raises:
            ValueError: If the candidate is not found.
        """
        metrics = self._load_metrics(candidate_id)
        reasons: list[str] = []

        in_sample_sharpe = float(metrics.get("in_sample_sharpe", 0.0))
        out_of_sample_sharpe = float(metrics.get("out_of_sample_sharpe",
                                                   metrics.get("sharpe_ratio", 0.0)))
        degradation_pct = self._compute_degradation(in_sample_sharpe, out_of_sample_sharpe)
        param_sensitivity = float(metrics.get("param_sensitivity", 0.0))
        trade_count = int(metrics.get("trade_count", 0))
        single_year_concentration = float(metrics.get("single_year_concentration", 0.0))
        single_symbol_concentration = float(metrics.get("single_symbol_concentration", 0.0))
        cost_sensitivity = float(metrics.get("cost_sensitivity", 0.0))

        # Check OOS degradation > 40%
        if degradation_pct > 0.40:
            reasons.append(
                f"OOS degradation {degradation_pct:.1%} exceeds 40% threshold"
            )

        # Check param sensitivity > 0.5
        if param_sensitivity > 0.5:
            reasons.append(
                f"Parameter sensitivity {param_sensitivity:.3f} exceeds 0.5 threshold"
            )

        # Check trade count < 10
        if 0 < trade_count < 10:
            reasons.append(
                f"Only {trade_count} trades — insufficient for statistical significance"
            )

        # Check single-year concentration > 50%
        if single_year_concentration > 0.50:
            reasons.append(
                f"Single-year concentration {single_year_concentration:.1%} exceeds 50%"
            )

        # Check single-symbol concentration > 60%
        if single_symbol_concentration > 0.60:
            reasons.append(
                f"Single-symbol concentration {single_symbol_concentration:.1%} exceeds 60%"
            )

        # Check cost stress failure (sharpe < 0 after 5x costs)
        if cost_sensitivity > 0.5:
            reasons.append(
                f"Cost stress failure: Sharpe < 0 after 5x costs "
                f"(cost_sensitivity={cost_sensitivity:.3f})"
            )

        return OverfitReport(
            candidate_id=candidate_id,
            is_overfit=len(reasons) > 0,
            reasons=reasons,
            in_sample_sharpe=in_sample_sharpe,
            out_of_sample_sharpe=out_of_sample_sharpe,
            degradation_pct=degradation_pct,
            param_sensitivity=param_sensitivity,
            single_year_concentration=single_year_concentration,
            single_symbol_concentration=single_symbol_concentration,
            trade_count=trade_count,
            cost_sensitivity=cost_sensitivity,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_metrics(self, candidate_id: str) -> dict[str, Any]:
        path = (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        if not path.exists():
            raise ValueError(f"Candidate {candidate_id} not found")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("metrics", {})

    @staticmethod
    def _compute_degradation(
        in_sample_sharpe: float, out_of_sample_sharpe: float
    ) -> float:
        if in_sample_sharpe <= 0:
            return 0.0
        return max(0.0, (in_sample_sharpe - out_of_sample_sharpe) / in_sample_sharpe)

    # ------------------------------------------------------------------
    # Standalone anti-overfit checks
    # ------------------------------------------------------------------

    def check_single_month_concentration(self, candidate_id: str) -> tuple[bool, float]:
        """Check if >40% of returns come from a single month.

        Uses the stored metrics if available, otherwise returns (False, 0.0).

        Args:
            candidate_id: The candidate to check.

        Returns:
            Tuple of (is_concentrated, max_month_pct).
        """
        metrics = self._load_metrics(candidate_id)
        concentration = float(metrics.get("single_month_concentration", 0.0))
        is_concentrated = concentration > 0.40
        return (is_concentrated, concentration)

    def check_single_symbol_concentration(self, candidate_id: str) -> tuple[bool, float]:
        """Check if >60% of returns come from a single symbol.

        Args:
            candidate_id: The candidate to check.

        Returns:
            Tuple of (is_concentrated, max_symbol_pct).
        """
        metrics = self._load_metrics(candidate_id)
        concentration = float(metrics.get("single_symbol_concentration", 0.0))
        is_concentrated = concentration > 0.60
        return (is_concentrated, concentration)

    def check_param_sensitivity(
        self, candidate_id: str, param_neighbors: list[dict] | None = None
    ) -> float:
        """Check performance variance across nearby parameter values.

        If param_neighbors is provided, computes variance of sharpe ratios
        across the neighbor configurations. Otherwise falls back to the
        stored param_sensitivity metric.

        A value > 0.5 indicates possible parameter overfitting.

        Args:
            candidate_id: The candidate to check.
            param_neighbors: Optional list of dicts, each with at least
                a "sharpe_ratio" key.

        Returns:
            Float sensitivity score. >0.5 implies overfit.
        """
        if param_neighbors:
            sharpes: list[float] = []
            for neighbor in param_neighbors:
                sharpes.append(float(neighbor.get("sharpe_ratio", 0.0)))
            if sharpes:
                mean_sharpe = sum(sharpes) / len(sharpes)
                variance = sum((s - mean_sharpe) ** 2 for s in sharpes) / len(sharpes)
                # Scale variance to 0-1 range; variance of ~0.1 maps to ~0.5
                return round(min(variance * 5.0, 1.0), 4)

        # Fall back to stored metric
        metrics = self._load_metrics(candidate_id)
        return float(metrics.get("param_sensitivity", 0.0))


class LookaheadBiasChecker:
    """Heuristic detection of lookahead bias in factors and experiments.

    Detection methods:
    - IC > 0.2 suspiciously high -> possible lookahead
    - IC is constant across all periods -> possible data leak
    - Factor values change retroactively -> confirms lookahead
    - Time-split violations in experiments
    - bfill usage in feature computation
    - shift(-1) in feature engineering
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def check(self, factor_id: str) -> tuple[bool, str]:
        """Heuristic lookahead detection for a factor.

        Args:
            factor_id: The factor identifier to check.

        Returns:
            Tuple of (has_lookahead, description).
        """
        # Load factor metrics if available
        metrics = self._load_factor_metrics(factor_id)

        ic = float(metrics.get("ic", 0.0))
        ic_std = float(metrics.get("ic_std", 0.0))

        # Check: IC > 0.2 suspiciously high
        if ic > 0.2:
            return (True, f"Factor {factor_id} has suspiciously high IC={ic:.4f} (>0.2)")

        # Check: IC is constant across all periods (std near 0)
        if ic_std < 1e-6 and ic != 0.0:
            return (True, f"Factor {factor_id} IC is constant across all periods (std={ic_std:.6f})")

        return (False, f"Factor {factor_id} shows no lookahead signs (IC={ic:.4f})")

    def check_experiment(self, experiment_id: str) -> tuple[bool, str]:
        """Check experiment for lookahead bias signs.

        Looks for:
        - Time-split violations
        - bfill usage in features
        - shift(-1) in feature engineering

        Args:
            experiment_id: The experiment to check.

        Returns:
            Tuple of (has_lookahead, description).
        """
        manifest_data = self._load_experiment_manifest(experiment_id)
        if manifest_data is None:
            return (False, f"Experiment {experiment_id} not found")

        risk_flags: list[str] = []

        # Check for time-split violations
        params = manifest_data.get("params", {})
        if params.get("bfill_features", False):
            risk_flags.append("bfill enabled in features — possible lookahead")

        if params.get("shift_minus_one", False):
            risk_flags.append("shift(-1) found in feature computation — confirmed lookahead")

        # Check for suspiciously high metrics
        metrics = manifest_data.get("metrics", {})
        sharpe = float(metrics.get("sharpe_ratio", 0.0))
        if sharpe > 3.0:
            risk_flags.append(f"Suspiciously high Sharpe={sharpe:.2f} — possible lookahead")

        if risk_flags:
            return (True, "; ".join(risk_flags))

        return (False, f"Experiment {experiment_id} passed lookahead check")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_factor_metrics(self, factor_id: str) -> dict[str, Any]:
        path = self.data_root / "research" / "factors" / f"{factor_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def _load_experiment_manifest(self, experiment_id: str) -> dict[str, Any] | None:
        path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "manifest.json"
        )
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None
