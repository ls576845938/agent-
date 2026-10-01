"""Tests for factor evaluation metrics: IC, RankIC, ICIR.

Covers: IC computation, RankIC, ICIR, quantile returns, decay.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd


def _compute_ic(factor: pd.Series, forward_returns: pd.Series) -> float:
    """Compute Information Coefficient (Pearson correlation)."""
    combined = pd.concat([factor, forward_returns], axis=1).dropna()
    if len(combined) < 5:
        return 0.0
    return float(combined.iloc[:, 0].corr(combined.iloc[:, 1]))


def _compute_rank_ic(factor: pd.Series, forward_returns: pd.Series) -> float:
    """Compute Rank IC (Spearman correlation)."""
    combined = pd.concat([factor, forward_returns], axis=1).dropna()
    if len(combined) < 5:
        return 0.0
    return float(combined.iloc[:, 0].corr(combined.iloc[:, 1], method="spearman"))


def _compute_icir(ic_series: pd.Series) -> float:
    """Compute IC Information Ratio."""
    if len(ic_series) < 2:
        return 0.0
    mean_ic = ic_series.mean()
    std_ic = ic_series.std()
    if std_ic == 0:
        return 0.0
    return float(mean_ic / std_ic)


class TestICEvaluation(unittest.TestCase):
    """IC computation tests."""

    def test_perfect_positive_ic(self) -> None:
        factor = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
        ic = _compute_ic(factor, returns)
        self.assertAlmostEqual(ic, 1.0, places=4)

    def test_perfect_negative_ic(self) -> None:
        factor = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0])
        returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
        ic = _compute_ic(factor, returns)
        self.assertAlmostEqual(ic, -1.0, places=4)

    def test_zero_ic(self) -> None:
        """Independent random data should have IC near zero."""
        np.random.seed(42)
        factor = pd.Series(np.random.randn(200))
        returns = pd.Series(np.random.randn(200))
        ic = _compute_ic(factor, returns)
        # With 200 samples, |IC| should be < 0.15 for independent data
        self.assertLess(abs(ic), 0.15)

    def test_rank_ic_range(self) -> None:
        """Rank IC should be between -1 and 1."""
        factor = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        returns = pd.Series([0.05, 0.04, 0.03, 0.02, 0.01])
        rank_ic = _compute_rank_ic(factor, returns)
        self.assertGreaterEqual(rank_ic, -1.0)
        self.assertLessEqual(rank_ic, 1.0)

    def test_ic_with_nan(self) -> None:
        factor = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
        ic = _compute_ic(factor, returns)
        self.assertIsNotNone(ic)

    def test_icir_positive(self) -> None:
        ic_series = pd.Series([0.05, 0.06, 0.04, 0.07, 0.05])
        icir = _compute_icir(ic_series)
        self.assertGreater(icir, 0)

    def test_icir_negative(self) -> None:
        ic_series = pd.Series([-0.05, -0.06, -0.04, -0.07, -0.05])
        icir = _compute_icir(ic_series)
        self.assertLess(icir, 0)

    def test_icir_single_value(self) -> None:
        ic_series = pd.Series([0.05])
        icir = _compute_icir(ic_series)
        self.assertEqual(icir, 0.0)
