"""Tests for quantile return analysis.

Covers: quantile returns monotonicity, long-short spread.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd


def _compute_quantile_returns(
    factor: pd.Series,
    forward_returns: pd.Series,
    n_quantiles: int = 5,
) -> dict[int, float]:
    """Compute mean forward return per factor quantile."""
    combined = pd.concat([factor, forward_returns], axis=1).dropna()
    combined.columns = ["factor", "return"]
    combined["quantile"] = pd.qcut(
        combined["factor"], n_quantiles, labels=False, duplicates="drop"
    )
    return {
        int(q): float(group["return"].mean())
        for q, group in combined.groupby("quantile")
    }


class TestQuantileReturns(unittest.TestCase):
    """Quantile return analysis tests."""

    def test_monotonic_positive_factor(self) -> None:
        """Factor positively correlated with returns: higher quantile = higher return."""
        np.random.seed(42)
        n = 200
        factor = pd.Series(np.random.randn(n))
        returns = pd.Series(factor * 0.1 + np.random.randn(n) * 0.01)
        quantiles = _compute_quantile_returns(factor, returns)
        # Q4 should have higher return than Q0
        keys = sorted(quantiles.keys())
        self.assertGreater(quantiles[keys[-1]], quantiles[keys[0]])

    def test_monotonic_negative_factor(self) -> None:
        """Factor negatively correlated with returns: lower quantile = higher return."""
        np.random.seed(42)
        n = 200
        factor = pd.Series(np.random.randn(n))
        returns = pd.Series(-factor * 0.1 + np.random.randn(n) * 0.01)
        quantiles = _compute_quantile_returns(factor, returns)
        keys = sorted(quantiles.keys())
        self.assertLess(quantiles[keys[-1]], quantiles[keys[0]])

    def test_long_short_spread_positive(self) -> None:
        """Long-short spread (top - bottom quantile) should be positive for good factor."""
        np.random.seed(42)
        n = 200
        factor = pd.Series(np.random.randn(n))
        returns = pd.Series(factor * 0.1 + np.random.randn(n) * 0.01)
        quantiles = _compute_quantile_returns(factor, returns)
        keys = sorted(quantiles.keys())
        spread = quantiles[keys[-1]] - quantiles[keys[0]]
        self.assertGreater(spread, 0)

    def test_five_quantiles(self) -> None:
        """Test with 5 quantiles."""
        np.random.seed(42)
        factor = pd.Series(np.random.randn(500))
        returns = pd.Series(np.random.randn(500) * 0.01)
        quantiles = _compute_quantile_returns(factor, returns, n_quantiles=5)
        self.assertEqual(len(quantiles), 5)

    def test_three_quantiles(self) -> None:
        """Test with 3 quantiles."""
        np.random.seed(42)
        factor = pd.Series(np.random.randn(300))
        returns = pd.Series(np.random.randn(300) * 0.01)
        quantiles = _compute_quantile_returns(factor, returns, n_quantiles=3)
        self.assertEqual(len(quantiles), 3)

    def test_handles_nan_gracefully(self) -> None:
        """Should handle NaN values without error."""
        factor = pd.Series([1.0, np.nan, 3.0, 4.0, np.nan, 6.0])
        returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
        quantiles = _compute_quantile_returns(factor, returns, n_quantiles=2)
        self.assertGreater(len(quantiles), 0)
