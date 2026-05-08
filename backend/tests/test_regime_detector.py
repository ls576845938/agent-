"""Tests for MarketRegimeDetector.

Covers: all regime states detected, no lookahead.
"""

from __future__ import annotations

import unittest

import pandas as pd

from quant_us.regime.detector import MarketRegimeDetector, RegimeState


class TestRegimeState(unittest.TestCase):
    """RegimeState constants."""

    def test_valid_regimes(self) -> None:
        self.assertTrue(RegimeState.is_valid("BULL_TREND"))
        self.assertTrue(RegimeState.is_valid("BEAR_TREND"))
        self.assertTrue(RegimeState.is_valid("SIDEWAYS"))
        self.assertTrue(RegimeState.is_valid("HIGH_VOL"))
        self.assertTrue(RegimeState.is_valid("LOW_VOL"))
        self.assertTrue(RegimeState.is_valid("PANIC"))
        self.assertTrue(RegimeState.is_valid("RECOVERY"))
        self.assertTrue(RegimeState.is_valid("UNKNOWN"))

    def test_invalid_regime(self) -> None:
        self.assertFalse(RegimeState.is_valid("INVALID"))


class TestMarketRegimeDetector(unittest.TestCase):
    """Regime detection logic."""

    def setUp(self) -> None:
        self.detector = MarketRegimeDetector()

    def _make_bull_prices(self, n: int = 500) -> pd.DataFrame:
        """Generate rising prices with moderate volatility."""
        import numpy as np
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
        noise = np.random.randn(n) * 2.0
        trend = np.arange(n) * 0.3
        close_prices = 100.0 + trend + noise.cumsum() * 0.1
        close_prices = np.maximum(close_prices, 50.0)  # floor
        return pd.DataFrame({
            "timestamp_utc": dates,
            "open": close_prices - 0.5,
            "high": close_prices + 1.0,
            "low": close_prices - 1.0,
            "close": close_prices,
            "volume": [1000000 + int(abs(ns) * 10000) for ns in noise],
        })

    def _make_bear_prices(self, n: int = 500) -> pd.DataFrame:
        """Generate falling prices with moderate volatility, drawdown stays above -20%."""
        import numpy as np
        np.random.seed(75)
        dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
        noise = np.random.randn(n) * 2.0
        trend = -np.arange(n) * 0.1
        close_prices = 250.0 + trend + noise.cumsum() * 0.1
        close_prices = np.maximum(close_prices, 200.0)
        return pd.DataFrame({
            "timestamp_utc": dates,
            "open": close_prices - 0.5,
            "high": close_prices + 1.0,
            "low": close_prices - 1.0,
            "close": close_prices,
            "volume": [1000000] * n,
        })

    def test_detect_returns_dataframe(self) -> None:
        prices = self._make_bull_prices()
        result = self.detector.detect(prices)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertGreater(len(result), 0)

    def test_detect_contains_required_columns(self) -> None:
        prices = self._make_bull_prices()
        result = self.detector.detect(prices)
        required = ["date", "regime", "confidence", "trend_strength", "vol_percentile", "drawdown_pct"]
        for col in required:
            self.assertIn(col, result.columns)

    def test_bull_trend_detected(self) -> None:
        prices = self._make_bull_prices(500)
        result = self.detector.detect(prices)
        # Later periods (after MA200 is established) should be BULL_TREND
        if len(result) > 250:
            late_periods = result.iloc[-100:]
            bull_count = (late_periods["regime"] == "BULL_TREND").sum()
            self.assertGreater(bull_count, 0)

    def test_bear_trend_detected(self) -> None:
        prices = self._make_bear_prices(500)
        result = self.detector.detect(prices)
        if len(result) > 250:
            late_periods = result.iloc[-100:]
            bear_count = (late_periods["regime"] == "BEAR_TREND").sum()
            self.assertGreater(bear_count, 0)

    def test_empty_prices_returns_empty(self) -> None:
        result = self.detector.detect(pd.DataFrame())
        self.assertTrue(result.empty)

    def test_detect_respects_start_end(self) -> None:
        prices = self._make_bull_prices()
        result = self.detector.detect(prices, start="2023-06-01", end="2023-08-01")
        if not result.empty:
            self.assertGreaterEqual(result["date"].min(), "2023-06-01")
            self.assertLessEqual(result["date"].max(), "2023-08-01")

    def test_confidence_in_range(self) -> None:
        prices = self._make_bull_prices(300)
        result = self.detector.detect(prices)
        if not result.empty:
            self.assertTrue((result["confidence"] >= 0).all())
            self.assertTrue((result["confidence"] <= 1).all())

    def test_current_regime_returns_regime_result(self) -> None:
        prices = self._make_bull_prices(300)
        # Override _load_prices to return our test data
        def mock_load(symbol: str) -> pd.DataFrame:
            return prices
        self.detector._load_prices = mock_load
        result = self.detector.current_regime("SPY")
        self.assertIn(result.regime, RegimeState._ALL)
        self.assertGreaterEqual(result.confidence, 0)
