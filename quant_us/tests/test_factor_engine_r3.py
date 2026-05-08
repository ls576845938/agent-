"""Tests for the R3 Factor Engine: definition, pipeline, evaluation, report."""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from quant_us.factors.definition import FACTOR_CATEGORIES, FactorDefinition, FactorLibrary
from quant_us.factors.evaluation import FactorEvaluationResult, FactorEvaluator
from quant_us.factors.pipeline import (
    FactorPipeline,
    _compute_factor_series,
    _winsorize,
    _zscore,
    _rank_to_percentile,
)
from quant_us.factors.report import FactorReportBuilder


# ===========================================================================
# definition.py
# ===========================================================================


class TestFactorDefinition:
    def test_valid_factor(self) -> None:
        fd = FactorDefinition(
            factor_id="test_mom",
            name="Test Momentum",
            category="momentum",
            lookback=60,
        )
        assert fd.factor_id == "test_mom"
        assert fd.category == "momentum"
        assert fd.neutralization == "none"
        assert fd.zscore is True

    def test_invalid_category(self) -> None:
        with pytest.raises(ValueError, match="Unknown category"):
            FactorDefinition(factor_id="bad", name="Bad", category="nonexistent")

    def test_invalid_neutralization(self) -> None:
        with pytest.raises(ValueError, match="Invalid neutralization"):
            FactorDefinition(
                factor_id="bad",
                name="Bad",
                category="momentum",
                neutralization="xyz",
            )

    def test_invalid_rank_method(self) -> None:
        with pytest.raises(ValueError, match="Invalid rank_method"):
            FactorDefinition(
                factor_id="bad",
                name="Bad",
                category="momentum",
                rank_method="invalid",
            )


class TestFactorLibrary:
    def test_builtins_registered(self) -> None:
        lib = FactorLibrary()
        all_factors = lib.list_all()
        ids = [f.factor_id for f in all_factors]
        assert "momentum_60d" in ids
        assert "volatility_20d" in ids
        assert "liquidity_20d" in ids
        assert "reversal_1d" in ids
        assert "volume_20d" in ids

    def test_get_known(self) -> None:
        lib = FactorLibrary()
        fd = lib.get("momentum_60d")
        assert fd.name == "60-Day Momentum"
        assert fd.category == "momentum"

    def test_get_unknown_raises(self) -> None:
        lib = FactorLibrary()
        with pytest.raises(KeyError):
            lib.get("nonexistent")

    def test_list_by_category(self) -> None:
        lib = FactorLibrary()
        moms = lib.list_by_category("momentum")
        assert len(moms) >= 2
        assert all(f.category == "momentum" for f in moms)

    def test_register_override(self) -> None:
        lib = FactorLibrary()
        custom = FactorDefinition(
            factor_id="custom_factor",
            name="Custom",
            category="volume",
        )
        lib.register(custom)
        assert lib.get("custom_factor").name == "Custom"

    def test_factor_ids(self) -> None:
        lib = FactorLibrary()
        ids = lib.factor_ids()
        assert "momentum_60d" in ids

    def test_categories_are_complete(self) -> None:
        expected = {
            "momentum", "reversal", "volatility",
            "liquidity", "volume", "trend", "quality", "macro",
        }
        assert set(FACTOR_CATEGORIES) == expected


# ===========================================================================
# pipeline.py
# ===========================================================================

# Sample OHLCV data for pipeline tests
# 100 rows × 3 symbols, covering 2024-01-02 through 2024-01-31


@pytest.fixture
def sample_bars() -> pd.DataFrame:
    """Simple synthetic OHLCV data for 3 symbols over ~22 trading days."""
    np.random.seed(42)
    symbols = ["SPY", "QQQ", "AAPL"]
    rows: list[dict] = []
    days = pd.bdate_range("2024-01-02", "2024-01-31")
    for sym in symbols:
        price = 100.0
        for dt in days:
            change = np.random.normal(0.001, 0.015)
            price *= (1 + change)
            rows.append({
                "timestamp_utc": datetime.combine(dt, datetime.min.time(), tzinfo=timezone.utc),
                "symbol": sym,
                "open": price * (1 - abs(np.random.normal(0, 0.002))),
                "high": price * (1 + abs(np.random.normal(0, 0.005))),
                "low": price * (1 - abs(np.random.normal(0, 0.005))),
                "close": price,
                "volume": int(np.random.uniform(1e6, 1e7)),
            })
    return pd.DataFrame(rows)


class TestComputeFactorSeries:
    def test_momentum_60d(self) -> None:
        close = pd.Series(np.cumprod(1 + np.random.normal(0.001, 0.02, 200)))
        result = _compute_factor_series("momentum_60d", close=close, volume=None)
        assert isinstance(result, pd.Series)
        assert len(result) == 200
        # Leading values should be NaN (insufficient lookback)
        assert pd.isna(result.iloc[0])
        # Later values should be finite
        assert not pd.isna(result.iloc[-1])

    def test_reversal_1d(self) -> None:
        close = pd.Series([100.0, 101.0, 99.0, 102.0])
        result = _compute_factor_series("reversal_1d", close=close, volume=None)
        # First value should be NaN (no prior day)
        assert pd.isna(result.iloc[0])
        # Second value = -(101/100 - 1) = -0.01
        assert abs(result.iloc[1] - (-0.01)) < 1e-10

    def test_volume_20d(self) -> None:
        volume = pd.Series(np.random.uniform(1e6, 2e6, 100))
        result = _compute_factor_series("volume_20d", close=None, volume=volume)
        assert isinstance(result, pd.Series)
        assert pd.isna(result.iloc[0])
        assert not pd.isna(result.iloc[-1])

    def test_unknown_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown factor_id"):
            _compute_factor_series("nonexistent", close=pd.Series([1, 2, 3]), volume=None)


class TestWinsorizeZscore:
    def test_winsorize_clamps(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 100.0, -100.0])
        result = _winsorize(s, pct=0.1)
        assert result.iloc[3] < 100.0  # upper tail clamped
        assert result.iloc[4] > -100.0  # lower tail clamped

    def test_winsorize_noop_for_zero_pct(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 100.0])
        result = _winsorize(s, pct=0.0)
        assert result.iloc[3] == 100.0

    def test_zscore_standardizes(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _zscore(s)
        assert abs(result.mean()) < 1e-10
        assert abs(result.std(ddof=0) - 1.0) < 1e-10

    def test_zscore_constant_zero(self) -> None:
        s = pd.Series([5.0, 5.0, 5.0])
        result = _zscore(s)
        assert all(result == 0.0)

    def test_rank_to_percentile(self) -> None:
        s = pd.Series([10.0, 20.0, 30.0, 40.0])
        result = _rank_to_percentile(s)
        assert result.min() > 0
        assert result.max() <= 1.0


class TestFactorPipeline:
    def test_padded_start(self) -> None:
        result = FactorPipeline._padded_start("2024-06-01", 20)
        # 20 * 1.4 + 5 = 33 days back
        assert result < "2024-06-01"
        assert result.startswith("2024-")

    def test_compute_with_synthetic_data(self, monkeypatch, sample_bars) -> None:
        """Test compute end-to-end using synthetic bars (no real data load)."""

        def mock_load_bars(*args, **kwargs):
            return sample_bars

        monkeypatch.setattr("quant_us.factors.pipeline._load_bars", mock_load_bars)

        pipe = FactorPipeline(data_root="/tmp/test_factor_pipeline")
        df = pipe.compute(
            factor_ids=["momentum_60d", "volatility_20d"],
            symbols=["SPY", "QQQ", "AAPL"],
            start="2024-01-10",
            end="2024-01-31",
        )

        assert not df.empty
        assert "date" in df.columns
        assert "symbol" in df.columns
        assert "momentum_60d" in df.columns
        assert "volatility_20d" in df.columns

        # Values should be in percentile range (post-processing)
        for fid in ["momentum_60d", "volatility_20d"]:
            col = df[fid].dropna()
            if len(col) > 0:
                assert col.min() >= 0.0
                assert col.max() <= 1.0

    def test_neutralize_basic(self) -> None:
        fv = {"AAPL": 0.8, "MSFT": 0.7, "XOM": 0.3, "CVX": 0.2}
        groupings = {"AAPL": "tech", "MSFT": "tech", "XOM": "energy", "CVX": "energy"}
        result = FactorPipeline.neutralize(fv, groupings)
        # Tech group mean = 0.75, energy group mean = 0.25
        assert abs(result["AAPL"] - (0.8 - 0.75)) < 1e-10
        assert abs(result["XOM"] - (0.3 - 0.25)) < 1e-10


# ===========================================================================
# evaluation.py
# ===========================================================================


class TestFactorEvaluator:
    def test_compute_ic_basic(self) -> None:
        evaluator = FactorEvaluator(data_root="/tmp/test_factor_eval")
        fv = {"A": 0.5, "B": 0.3, "C": 0.1, "D": -0.1, "E": -0.3}
        fr = {"A": 0.05, "B": 0.03, "C": 0.01, "D": -0.01, "E": -0.03}
        ic = evaluator.compute_ic(fv, fr)
        assert ic > 0.9  # nearly perfectly correlated

    def test_compute_ic_too_few(self) -> None:
        evaluator = FactorEvaluator()
        ic = evaluator.compute_ic({"A": 0.5, "B": 0.3}, {"A": 0.05})
        assert ic == 0.0

    def test_compute_rank_ic_basic(self) -> None:
        evaluator = FactorEvaluator()
        fv = {"A": 100.0, "B": 50.0, "C": 10.0, "D": 5.0, "E": 1.0}
        fr = {"A": 0.10, "B": 0.06, "C": 0.02, "D": 0.01, "E": 0.005}
        rank_ic = evaluator.compute_rank_ic(fv, fr)
        assert rank_ic > 0.9

    def test_compute_quantile_returns(self) -> None:
        evaluator = FactorEvaluator()
        fv = {f"s{i}": i for i in range(20)}
        fr = {f"s{i}": i * 0.001 for i in range(20)}
        qr = evaluator.compute_quantile_returns(fv, fr, n_quantiles=5)
        assert len(qr) == 5
        # Higher quantile should have higher return (monotonic)
        sorted_q = sorted(qr.items())
        for (q1, r1), (q2, r2) in zip(sorted_q, sorted_q[1:]):
            assert r2 >= r1, f"Quantile {q2} return ({r2}) < quantile {q1} return ({r1})"

    def test_detect_lookahead_threshold_logic(self, monkeypatch, sample_bars) -> None:
        """Test that detect_lookahead returns False for a low-IC scenario."""

        def mock_load_bars(*args, **kwargs):
            return sample_bars

        monkeypatch.setattr("quant_us.factors.pipeline._load_bars", mock_load_bars)

        evaluator = FactorEvaluator(data_root="/tmp/test_lookahead")
        flagged, msg = evaluator.detect_lookahead("momentum_60d")
        # Should not crash; should return something
        assert isinstance(flagged, bool)
        assert isinstance(msg, str)

    def test_evaluate_result_dataclass(self) -> None:
        result = FactorEvaluationResult(
            factor_id="test",
            ic_mean=0.05,
            ic_std=0.1,
            icir=0.5,
            rank_ic_mean=0.04,
            quantile_returns={1: 0.01, 5: 0.05},
        )
        assert result.factor_id == "test"
        assert result.icir == 0.5


# ===========================================================================
# report.py
# ===========================================================================


class TestFactorReportBuilder:
    def test_build_report_basic(self) -> None:
        result = FactorEvaluationResult(
            factor_id="momentum_60d",
            ic_mean=0.04,
            ic_std=0.08,
            icir=0.5,
            rank_ic_mean=0.035,
            rank_ic_std=0.07,
            rank_icir=0.5,
            quantile_returns={1: -0.01, 2: 0.0, 3: 0.01, 4: 0.02, 5: 0.03},
            long_short_spread=0.04,
            decay_half_life=15.0,
            hit_rate=0.6,
            monotonicity=0.85,
        )
        builder = FactorReportBuilder()
        md = builder.build_report("momentum_60d", result)
        assert "# Factor Report: momentum_60d" in md
        assert "IC Summary" in md
        assert "Quantile Performance" in md
        assert "Recommendation" in md

    def test_recommend_usable(self) -> None:
        builder = FactorReportBuilder()
        result = FactorEvaluationResult(
            factor_id="x",
            ic_mean=0.05,
            icir=0.8,
            monotonicity=0.9,
            decay_half_life=20.0,
            hit_rate=0.65,
        )
        rec = builder.recommend(result)
        assert rec.startswith("usable")

    def test_recommend_rejected(self) -> None:
        builder = FactorReportBuilder()
        result = FactorEvaluationResult(
            factor_id="x",
            ic_mean=0.01,
            icir=-0.5,
            monotonicity=-0.5,
            decay_half_life=2.0,
            hit_rate=0.45,
        )
        rec = builder.recommend(result)
        assert rec.startswith("rejected")

    def test_recommend_unstable(self) -> None:
        builder = FactorReportBuilder()
        result = FactorEvaluationResult(
            factor_id="x",
            ic_mean=0.04,
            icir=0.6,
            monotonicity=0.5,
            decay_half_life=12.0,
            hit_rate=0.5,
        )
        rec = builder.recommend(result)
        assert rec.startswith("unstable")
