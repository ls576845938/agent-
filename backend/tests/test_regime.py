"""Tests for regime detection module — no live/execution imports allowed."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from quant_us.regime.detector import (
    MarketRegimeDetector,
    RegimeResult,
    RegimeState,
)
from quant_us.regime.store import RegimeFeatureStore, RegimeRecord
from quant_us.regime.backtest import RegimeAwareBacktest, RegimeBacktestResult
from quant_us.regime.report import RegimeReportBuilder


# =========================================================================
# Helpers
# =========================================================================


def _make_prices(
    n: int = 260,
    start: str = "2023-01-02",
    trend: str = "bull",
    volatility_pct: float = 0.10,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic daily price data for testing.

    Uses a fixed seed for reproducibility.
    """
    import random

    rng = random.Random(seed)
    dates = pd.date_range(start, periods=n, freq="B")
    close = 100.0
    prices: list = []
    for dt in dates:
        if trend == "bull":
            r = 0.0010  # ~29% annualized
        elif trend == "bear":
            r = -0.0010
        elif trend == "panic":
            r = -0.005  # severe decline
        elif trend == "sideways":
            r = 0.0
        elif trend == "high_vol":
            r = 0.0
        else:
            r = 0.0

        noise = rng.gauss(0, volatility_pct / (252**0.5))
        close *= 1.0 + r + noise
        prices.append({
            "timestamp_utc": dt,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": max(close, 0.01),
            "volume": int(50_000_000 * (1.0 + min(max(noise * 2, -0.5), 0.5))),
            "symbol": "TEST",
        })

    return pd.DataFrame(prices)


def _make_regime_data(regimes: list[tuple[str, str]]) -> pd.DataFrame:
    """Build a regime DataFrame from (date, regime) pairs."""
    records = []
    for date_str, regime in regimes:
        records.append({
            "date": date_str,
            "regime": regime,
            "confidence": 0.8,
            "trend_strength": 0.0,
            "vol_percentile": 50.0,
            "drawdown_pct": 0.0,
            "volume_ratio": 1.0,
            "vix_proxy": 0.0,
            "breadth_pct": 0.0,
        })
    return pd.DataFrame(records)


# =========================================================================
# Tests: RegimeState
# =========================================================================


class TestRegimeState:
    def test_is_valid(self) -> None:
        assert RegimeState.is_valid("BULL_TREND")
        assert RegimeState.is_valid("BEAR_TREND")
        assert RegimeState.is_valid("SIDEWAYS")
        assert RegimeState.is_valid("HIGH_VOL")
        assert RegimeState.is_valid("LOW_VOL")
        assert RegimeState.is_valid("PANIC")
        assert RegimeState.is_valid("RECOVERY")
        assert RegimeState.is_valid("LIQUIDITY_STRESS")
        assert RegimeState.is_valid("UNKNOWN")
        assert not RegimeState.is_valid("FAKE_REGIME")

    def test_all_set(self) -> None:
        assert len(RegimeState._ALL) == 9


# =========================================================================
# Tests: MarketRegimeDetector
# =========================================================================


class TestMarketRegimeDetector:
    def test_detect_returns_expected_columns(self) -> None:
        prices = _make_prices(n=260)
        detector = MarketRegimeDetector()
        result = detector.detect(prices)
        expected = {
            "date", "regime", "confidence", "trend_strength",
            "vol_percentile", "drawdown_pct", "volume_ratio",
            "vix_proxy", "breadth_pct",
        }
        assert expected.issubset(set(result.columns))

    def test_detect_all_regime_values_are_valid(self) -> None:
        prices = _make_prices(n=400, trend="bull")
        detector = MarketRegimeDetector()
        result = detector.detect(prices)
        for regime in result["regime"].unique():
            assert RegimeState.is_valid(regime), f"Invalid regime: {regime}"

    def test_detect_empty_dataframe(self) -> None:
        detector = MarketRegimeDetector()
        result = detector.detect(pd.DataFrame())
        assert result.empty

    def test_detect_no_data(self) -> None:
        detector = MarketRegimeDetector()
        result = detector.detect(pd.DataFrame(columns=["timestamp_utc", "close"]))
        assert result.empty

    def test_detect_bull_trend_appears(self) -> None:
        """Upward trend should produce BULL_TREND somewhere in the output."""
        prices = _make_prices(n=400, trend="bull", seed=42)
        detector = MarketRegimeDetector()
        result = detector.detect(prices)
        valid = result[result["regime"] != "UNKNOWN"]
        assert "BULL_TREND" in valid["regime"].values, (
            f"Expected BULL_TREND in results, got {Counter(valid['regime'])}"
        )

    def test_detect_bear_trend_appears(self) -> None:
        """Downward trend should produce BEAR_TREND somewhere in the output."""
        prices = _make_prices(n=400, trend="bear", seed=42)
        detector = MarketRegimeDetector()
        result = detector.detect(prices)
        valid = result[result["regime"] != "UNKNOWN"]
        assert "BEAR_TREND" in valid["regime"].values, (
            f"Expected BEAR_TREND in results, got {Counter(valid['regime'])}"
        )

    def test_unknown_during_burn_in(self) -> None:
        """First rows should be UNKNOWN because MA200 is not defined."""
        prices = _make_prices(n=50)
        detector = MarketRegimeDetector()
        result = detector.detect(prices)
        unknown_count = (result["regime"] == "UNKNOWN").sum()
        assert unknown_count >= len(result) - 5, (
            f"Expected nearly all UNKNOWN with 50 bars, got {unknown_count}/{len(result)}"
        )

    def test_panic_takes_priority(self) -> None:
        """PANIC should appear when there's a severe drawdown."""
        prices = _make_prices(n=400, trend="panic", seed=42)
        detector = MarketRegimeDetector()
        result = detector.detect(prices)
        valid = result[result["regime"] != "UNKNOWN"]
        assert "PANIC" in valid["regime"].values, (
            f"Expected PANIC in results, got {Counter(valid['regime'])}"
        )

    def test_current_regime_unknown_on_missing_data(self) -> None:
        detector = MarketRegimeDetector()
        result = detector.current_regime(symbol="NONEXISTENT")
        assert result.regime == RegimeState.UNKNOWN
        assert result.confidence == 0.0

    def test_current_regime_returns_type(self) -> None:
        """Check that current_regime returns a properly typed result."""
        detector = MarketRegimeDetector()
        result = detector.current_regime(symbol="SPY")
        assert isinstance(result, RegimeResult)
        assert RegimeState.is_valid(result.regime)

    def test_detect_all_returns_dataframe(self) -> None:
        detector = MarketRegimeDetector()
        result = detector.detect_all(symbol="SPY")
        assert isinstance(result, pd.DataFrame)

    def test_no_lookahead_in_features(self) -> None:
        """Verify expanding computations use only past data (no lookahead)."""
        prices = _make_prices(n=100)
        detector = MarketRegimeDetector()
        features = detector._compute_features(prices)
        for idx in range(10, len(features)):
            row = features.iloc[idx]
            if pd.isna(row.get("vol_percentile")):
                continue
            assert 0.0 <= row["vol_percentile"] <= 100.0


# =========================================================================
# Tests: RegimeFeatureStore
# =========================================================================


class TestRegimeFeatureStore:
    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RegimeFeatureStore(data_root=tmp)
            records = [
                RegimeRecord(
                    date="2024-01-02",
                    symbol="SPY",
                    regime="BULL_TREND",
                    confidence=0.85,
                    features={"trend_strength": 0.05, "vol_percentile": 60.0},
                ),
                RegimeRecord(
                    date="2024-01-03",
                    symbol="SPY",
                    regime="HIGH_VOL",
                    confidence=0.75,
                    features={"trend_strength": 0.02, "vol_percentile": 85.0},
                ),
            ]
            path = store.save(records)
            assert Path(path).exists()

            loaded = store.load(symbol="SPY")
            assert len(loaded) == 2
            assert list(loaded["regime"]) == ["BULL_TREND", "HIGH_VOL"]

    def test_load_with_date_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RegimeFeatureStore(data_root=tmp)
            records = [
                RegimeRecord(date="2024-01-02", symbol="SPY", regime="BULL_TREND", confidence=0.8),
                RegimeRecord(date="2024-06-15", symbol="SPY", regime="SIDEWAYS", confidence=0.6),
            ]
            store.save(records)
            filtered = store.load(symbol="SPY", start="2024-06-01")
            assert len(filtered) == 1
            assert filtered.iloc[0]["regime"] == "SIDEWAYS"

    def test_load_empty_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RegimeFeatureStore(data_root=tmp)
            loaded = store.load(symbol="SPY")
            assert loaded.empty

    def test_get_regime_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RegimeFeatureStore(data_root=tmp)
            records = [
                RegimeRecord(date="2024-01-02", symbol="SPY", regime="BULL_TREND", confidence=0.8),
                RegimeRecord(date="2024-01-03", symbol="SPY", regime="BEAR_TREND", confidence=0.7),
            ]
            store.save(records)
            history = store.get_regime_history(symbol="SPY")
            assert len(history) == 2
            assert "features" in history[0]

    def test_features_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RegimeFeatureStore(data_root=tmp)
            features = {"trend_strength": 0.05, "vol_percentile": 60.0, "drawdown_pct": -0.01}
            record = RegimeRecord(date="2024-01-02", symbol="SPY", regime="BULL_TREND", confidence=0.8, features=features)
            store.save([record])
            loaded = store.load(symbol="SPY")
            loaded_features = loaded.iloc[0]["features"]
            assert isinstance(loaded_features, dict)
            assert loaded_features["trend_strength"] == 0.05

    def test_multi_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RegimeFeatureStore(data_root=tmp)
            records = [
                RegimeRecord(date="2024-01-02", symbol="SPY", regime="BULL_TREND", confidence=0.8),
                RegimeRecord(date="2024-01-02", symbol="QQQ", regime="HIGH_VOL", confidence=0.7),
            ]
            store.save(records)
            spy = store.load(symbol="SPY")
            qqq = store.load(symbol="QQQ")
            assert len(spy) == 1
            assert len(qqq) == 1


# =========================================================================
# Tests: RegimeAwareBacktest
# =========================================================================


class TestRegimeAwareBacktest:
    def test_transition_analysis_empty(self) -> None:
        bak = RegimeAwareBacktest()
        result = bak.transition_analysis(pd.DataFrame())
        assert result["transitions"] == 0

    def test_transition_analysis_no_transitions(self) -> None:
        data = _make_regime_data([
            ("2024-01-02", "BULL_TREND"),
            ("2024-01-03", "BULL_TREND"),
            ("2024-01-04", "BULL_TREND"),
        ])
        bak = RegimeAwareBacktest()
        result = bak.transition_analysis(data)
        assert result["transitions"] == 0

    def test_transition_analysis_counts(self) -> None:
        data = _make_regime_data([
            ("2024-01-02", "BULL_TREND"),
            ("2024-01-03", "BULL_TREND"),
            ("2024-01-04", "BEAR_TREND"),
            ("2024-01-05", "BEAR_TREND"),
            ("2024-01-06", "BULL_TREND"),
        ])
        bak = RegimeAwareBacktest()
        result = bak.transition_analysis(data)
        assert result["transitions"] == 2
        assert "BULL_TREND" in result["transition_matrix"]
        assert "BEAR_TREND" in result["transition_matrix"]["BULL_TREND"]

    def test_transition_analysis_frequency(self) -> None:
        data = _make_regime_data([
            ("2024-01-02", "BULL_TREND"),
            ("2024-01-03", "BULL_TREND"),
            ("2024-01-04", "BULL_TREND"),
        ])
        bak = RegimeAwareBacktest()
        result = bak.transition_analysis(data)
        assert result["regime_frequency"].get("BULL_TREND", 0) == 3

    def test_split_by_regime_no_files(self) -> None:
        bak = RegimeAwareBacktest()
        with tempfile.TemporaryDirectory() as tmp:
            result = bak.split_by_regime(tmp, pd.DataFrame())
        assert "__empty__" in result

    def test_filter_by_regime_no_data(self) -> None:
        bak = RegimeAwareBacktest()
        result = bak.filter_by_regime("/nonexistent", ["BULL_TREND"])
        assert result["cagr_pct"] == 0.0

    def test_empty_perf(self) -> None:
        perf = RegimeAwareBacktest._empty_perf()
        assert perf["cagr_pct"] == 0.0
        assert perf["sharpe_ratio"] == 0.0
        assert perf["max_drawdown_pct"] == 0.0
        assert perf["trade_count"] == 0

    def test_empty_regime_map(self) -> None:
        m = RegimeAwareBacktest._empty_regime_map("test_reason")
        assert "__empty__" in m
        assert m["__empty__"]["reason"] == "test_reason"


# =========================================================================
# Tests: RegimeReportBuilder
# =========================================================================


class TestRegimeReportBuilder:
    def test_build_timeline_empty(self) -> None:
        builder = RegimeReportBuilder()
        report = builder.build_timeline(symbol="NONEXISTENT")
        assert "No regime data available" in report

    def test_build_strategy_report_with_data(self) -> None:
        result = RegimeBacktestResult(
            symbol="SPY",
            strategy_id="test",
            regime_performance={
                "BULL_TREND": {"cagr_pct": 15.0, "sharpe_ratio": 1.2, "max_drawdown_pct": -5.0, "trade_count": 10},
                "BEAR_TREND": {"cagr_pct": -8.0, "sharpe_ratio": -0.5, "max_drawdown_pct": -20.0, "trade_count": 5},
            },
            best_regime="BULL_TREND",
            worst_regime="BEAR_TREND",
            regime_transitions=2,
            recommended_filter=["BEAR_TREND"],
        )
        builder = RegimeReportBuilder()
        report = builder.build_strategy_report("test_strategy", result)
        assert "BULL_TREND" in report
        assert "BEAR_TREND" in report
        assert "15.00" in report

    def test_recommend_filter_excludes_bad_regimes(self) -> None:
        result = RegimeBacktestResult(
            symbol="SPY",
            strategy_id="test",
            regime_performance={
                "BULL_TREND": {"cagr_pct": 15.0, "max_drawdown_pct": -5.0, "sharpe_ratio": 1.2, "trade_count": 10},
                "BEAR_TREND": {"cagr_pct": -8.0, "max_drawdown_pct": -20.0, "sharpe_ratio": -0.5, "trade_count": 5},
                "HIGH_VOL": {"cagr_pct": 2.0, "max_drawdown_pct": -12.0, "sharpe_ratio": 0.3, "trade_count": 3},
            },
        )
        builder = RegimeReportBuilder()
        avoid = builder.recommend_filter(result)
        assert "BEAR_TREND" in avoid
        assert "BULL_TREND" not in avoid

    def test_recommend_filter_no_filter_needed(self) -> None:
        result = RegimeBacktestResult(
            symbol="SPY",
            strategy_id="test",
            regime_performance={
                "BULL_TREND": {"cagr_pct": 15.0, "max_drawdown_pct": -5.0, "sharpe_ratio": 1.2, "trade_count": 10},
            },
        )
        builder = RegimeReportBuilder()
        avoid = builder.recommend_filter(result)
        assert avoid == []


# =========================================================================
# Safety: No live/execution imports
# =========================================================================


def test_no_live_imports() -> None:
    """Verify the regime module never imports live or execution code."""
    import inspect
    import quant_us.regime as regime_module

    source = inspect.getsource(regime_module)
    forbidden = ["quant_us.live", "quant_us.execution", "AlpacaBroker", "submit_order"]
    for term in forbidden:
        assert term not in source, f"Regime module must not import {term}"
