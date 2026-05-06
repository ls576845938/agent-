"""Tests for small untested modules: factors, portfolio, execution, data connectors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quant_us.factors.quality import gross_margin_score
from quant_us.factors.value import earnings_yield_score
from quant_us.portfolio.optimizer import StaticStrategyAllocation
from quant_us.execution.order_lifecycle import (
    OrderLifecycleConfig,
    OrderLifecycleManager,
)
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Order
from quant_us.data.connectors.alpaca_data import AlpacaDataConfig, AlpacaDataConnector
from quant_us.data.connectors.yfinance_data import YFinanceDataConfig, YFinanceDataConnector


# ====================================================================
# factors / quality
# ====================================================================


class TestGrossMarginScore:
    """gross_margin_score ranks a series and returns percentile in [0, 1]."""

    def test_normal_input(self) -> None:
        s = pd.Series([0.1, 0.2, 0.3, 0.4])
        result = gross_margin_score(s)
        assert len(result) == 4
        assert result.min() >= 0.0
        assert result.max() <= 1.0
        # monotonic because inputs are monotonic
        assert (result.diff().dropna() >= 0).all()

    def test_empty_series(self) -> None:
        result = gross_margin_score(pd.Series([], dtype=float))
        assert result.empty

    def test_single_value(self) -> None:
        result = gross_margin_score(pd.Series([0.5]))
        assert result.iloc[0] == 1.0

    def test_all_nan(self) -> None:
        result = gross_margin_score(pd.Series([float("nan"), float("nan")]))
        assert result.isna().all()

    def test_output_range_with_extremes(self) -> None:
        s = pd.Series([-1e6, 0.0, 1e6])
        result = gross_margin_score(s)
        assert all(0.0 <= v <= 1.0 for v in result.dropna())


# ====================================================================
# factors / value
# ====================================================================


class TestEarningsYieldScore:
    """earnings_yield_score ranks a series and returns percentile in [0, 1]."""

    def test_normal_input(self) -> None:
        s = pd.Series([0.05, 0.10, 0.15])
        result = earnings_yield_score(s)
        assert len(result) == 3
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_empty_series(self) -> None:
        result = earnings_yield_score(pd.Series([], dtype=float))
        assert result.empty

    def test_single_value(self) -> None:
        result = earnings_yield_score(pd.Series([0.08]))
        assert result.iloc[0] == 1.0

    def test_mixed_with_nan(self) -> None:
        s = pd.Series([float("nan"), 0.05, 0.02, 0.15])
        result = earnings_yield_score(s)
        valid = result.dropna()
        assert all(0.0 <= v <= 1.0 for v in valid)


# ====================================================================
# portfolio / optimizer
# ====================================================================


class TestStaticStrategyAllocation:
    """StaticStrategyAllocation.normalized() clamps negatives and normalizes."""

    def test_equal_weight_three_assets(self) -> None:
        alloc = StaticStrategyAllocation(weights={"A": 1.0, "B": 1.0, "C": 1.0})
        norm = alloc.normalized()
        assert set(norm.keys()) == {"A", "B", "C"}
        for v in norm.values():
            assert abs(v - 1.0 / 3) < 1e-12

    def test_single_asset(self) -> None:
        assert StaticStrategyAllocation(weights={"A": 100.0}).normalized() == {"A": 1.0}

    def test_empty_assets(self) -> None:
        assert StaticStrategyAllocation(weights={}).normalized() == {}

    def test_negative_weight_clamped(self) -> None:
        norm = StaticStrategyAllocation(weights={"A": -50.0, "B": 50.0}).normalized()
        assert norm["A"] == 0.0
        assert norm["B"] == 1.0

    def test_all_negative_returns_zeros(self) -> None:
        norm = StaticStrategyAllocation(weights={"A": -10.0, "B": -20.0}).normalized()
        assert norm == {"A": 0.0, "B": 0.0}

    def test_mixed_positive_negative_zero(self) -> None:
        norm = StaticStrategyAllocation(weights={"A": 100.0, "B": -50.0, "C": 0.0, "D": 400.0}).normalized()
        assert norm["A"] == 0.2  # 100 / 500
        assert norm["B"] == 0.0
        assert norm["C"] == 0.0
        assert norm["D"] == 0.8  # 400 / 500

    def test_all_zero(self) -> None:
        norm = StaticStrategyAllocation(weights={"A": 0.0, "B": 0.0}).normalized()
        assert norm == {"A": 0.0, "B": 0.0}


# ====================================================================
# execution / order_lifecycle
# ====================================================================


class TestOrderLifecycleManager:
    """OrderLifecycleManager identifies and cancels stale orders."""

    @staticmethod
    def _make_order(status: OrderStatus, updated_at_delta: int = -600) -> Order:
        now = datetime.now(timezone.utc)
        return Order(
            timestamp_utc=now,
            strategy_id="s1",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="c1",
            status=status,
            created_at=now + timedelta(seconds=updated_at_delta),
            updated_at=now + timedelta(seconds=updated_at_delta),
        )

    # --- stale_orders ---

    def test_stale_submitted_order(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=60))
        now = datetime.now(timezone.utc)
        order = self._make_order(OrderStatus.SUBMITTED, updated_at_delta=-600)
        stale = mgr.stale_orders([order], now=now)
        assert len(stale) == 1
        assert stale[0][0].order_id == order.order_id
        # age should be roughly 600s
        assert abs(stale[0][1] - 600) < 2

    def test_filled_order_not_stale(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=60))
        now = datetime.now(timezone.utc)
        stale = mgr.stale_orders([self._make_order(OrderStatus.FILLED, updated_at_delta=-600)], now=now)
        assert len(stale) == 0

    def test_cancelled_order_not_stale(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=60))
        now = datetime.now(timezone.utc)
        stale = mgr.stale_orders([self._make_order(OrderStatus.CANCELLED, updated_at_delta=-600)], now=now)
        assert len(stale) == 0

    def test_rejected_order_not_stale(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=60))
        now = datetime.now(timezone.utc)
        stale = mgr.stale_orders([self._make_order(OrderStatus.REJECTED, updated_at_delta=-600)], now=now)
        assert len(stale) == 0

    def test_recent_order_not_stale(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=600))
        now = datetime.now(timezone.utc)
        stale = mgr.stale_orders([self._make_order(OrderStatus.SUBMITTED, updated_at_delta=-60)], now=now)
        assert len(stale) == 0

    def test_multiple_stale_orders(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=60))
        now = datetime.now(timezone.utc)
        o1 = self._make_order(OrderStatus.SUBMITTED, updated_at_delta=-600)
        o2 = self._make_order(OrderStatus.ACCEPTED, updated_at_delta=-300)
        o3 = self._make_order(OrderStatus.FILLED, updated_at_delta=-600)
        stale = mgr.stale_orders([o1, o2, o3], now=now)
        assert len(stale) == 2
        stale_ids = {s[0].order_id for s in stale}
        assert stale_ids == {o1.order_id, o2.order_id}

    def test_empty_order_list(self) -> None:
        mgr = OrderLifecycleManager()
        now = datetime.now(timezone.utc)
        assert mgr.stale_orders([], now=now) == []

    # --- cancel_stale_orders ---

    def test_cancel_stale_orders(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=60))
        now = datetime.now(timezone.utc)
        stale_order = self._make_order(OrderStatus.SUBMITTED, updated_at_delta=-600)
        fresh_order = self._make_order(OrderStatus.SUBMITTED, updated_at_delta=-10)
        filled_order = self._make_order(OrderStatus.FILLED, updated_at_delta=-600)

        broker = MagicMock()
        broker.get_orders.return_value = [stale_order, fresh_order, filled_order]

        actions = mgr.cancel_stale_orders(broker, now=now)
        assert len(actions) == 1
        assert actions[0].action == "cancel"
        assert actions[0].reason == "order_timeout"
        broker.cancel_order.assert_called_once_with(stale_order.order_id)

    def test_cancel_stale_no_stale_orders(self) -> None:
        mgr = OrderLifecycleManager(config=OrderLifecycleConfig(max_open_seconds=600))
        now = datetime.now(timezone.utc)
        broker = MagicMock()
        broker.get_orders.return_value = [self._make_order(OrderStatus.SUBMITTED, updated_at_delta=-60)]
        actions = mgr.cancel_stale_orders(broker, now=now)
        assert actions == []
        broker.cancel_order.assert_not_called()


# ====================================================================
# data / connectors / alpaca
# ====================================================================


class TestAlpacaDataConnector:
    def test_constructor_with_config(self) -> None:
        config = AlpacaDataConfig(api_key="test_key", api_secret="test_secret")
        connector = AlpacaDataConnector(config)
        assert connector.config.api_key == "test_key"
        assert connector.config.api_secret == "test_secret"
        assert "alpaca" in connector.config.base_url
        assert connector.vendor == "alpaca"

    def test_constructor_default_base_url(self) -> None:
        config = AlpacaDataConfig(api_key="k", api_secret="s")
        assert "alpaca" in config.base_url

    def test_fetch_bars_with_api_mocked(self) -> None:
        from unittest.mock import patch
        connector = AlpacaDataConnector(AlpacaDataConfig(api_key="k", api_secret="s"))
        with patch.object(connector, "fetch_bars", return_value=pd.DataFrame()):
            result = connector.fetch_bars("AAPL", datetime.now(timezone.utc), datetime.now(timezone.utc), "1d")
        assert result.empty


# ====================================================================
# data / connectors / yfinance
# ====================================================================


class TestYFinanceDataConnector:
    def test_default_config(self) -> None:
        connector = YFinanceDataConnector()
        assert connector.config.auto_adjust is False
        assert connector.config.prepost is True

    def test_custom_config(self) -> None:
        config = YFinanceDataConfig(auto_adjust=True, prepost=False)
        connector = YFinanceDataConnector(config)
        assert connector.config.auto_adjust is True
        assert connector.config.prepost is False

    # -- _to_yfinance_interval --

    def test_valid_bar_size_mapping(self) -> None:
        connector = YFinanceDataConnector()
        assert connector._to_yfinance_interval("1m") == "1m"
        assert connector._to_yfinance_interval("2m") == "2m"
        assert connector._to_yfinance_interval("5m") == "5m"
        assert connector._to_yfinance_interval("15m") == "15m"
        assert connector._to_yfinance_interval("30m") == "30m"
        assert connector._to_yfinance_interval("60m") == "60m"
        assert connector._to_yfinance_interval("1h") == "60m"
        assert connector._to_yfinance_interval("1d") == "1d"
        assert connector._to_yfinance_interval("1wk") == "1wk"

    def test_invalid_bar_size_raises(self) -> None:
        connector = YFinanceDataConnector()
        with pytest.raises(ValueError, match="Unsupported yfinance bar_size"):
            connector._to_yfinance_interval("1month")

    # -- fetch_bars (mocked) --

    def test_fetch_bars_empty_response(self) -> None:
        connector = YFinanceDataConnector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 10, tzinfo=timezone.utc)

        with patch("yfinance.download", return_value=pd.DataFrame()) as mock_dl:
            result = connector.fetch_bars("AAPL", start, end, "1d")

        assert isinstance(result, pd.DataFrame)
        assert result.empty
        mock_dl.assert_called_once()

    def test_fetch_bars_with_data(self) -> None:
        """Mock yfinance.download to return OHLCV data with MultiIndex columns."""
        connector = YFinanceDataConnector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 5, tzinfo=timezone.utc)

        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        mock_raw = pd.DataFrame(
            {
                ("Open", "AAPL"): [100.0, 101.0, 102.0],
                ("High", "AAPL"): [105.0, 106.0, 107.0],
                ("Low", "AAPL"): [99.0, 100.0, 101.0],
                ("Close", "AAPL"): [104.0, 105.0, 106.0],
                ("Volume", "AAPL"): [10000, 11000, 12000],
            },
            index=dates,
        )
        mock_raw.columns.names = ["Price", "Ticker"]

        with patch("yfinance.download", return_value=mock_raw) as mock_dl:
            result = connector.fetch_bars("AAPL", start, end, "1d")

        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        assert len(result) == 3
        assert "symbol" in result.columns
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
        assert "timestamp_utc" in result.columns
        assert list(result["symbol"]) == ["AAPL", "AAPL", "AAPL"]
        mock_dl.assert_called_once()

    def test_fetch_bars_with_adj_close(self) -> None:
        """When yfinance returns 'Adj Close', it appears in the output."""
        connector = YFinanceDataConnector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 3, tzinfo=timezone.utc)

        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        mock_raw = pd.DataFrame(
            {
                ("Open", "AAPL"): [100.0, 101.0],
                ("High", "AAPL"): [105.0, 106.0],
                ("Low", "AAPL"): [99.0, 100.0],
                ("Close", "AAPL"): [104.0, 105.0],
                ("Adj Close", "AAPL"): [103.8, 104.9],
                ("Volume", "AAPL"): [10000, 11000],
            },
            index=dates,
        )
        mock_raw.columns.names = ["Price", "Ticker"]

        with patch("yfinance.download", return_value=mock_raw):
            result = connector.fetch_bars("AAPL", start, end, "1d")

        assert not result.empty
        assert "adjusted_close" in result.columns
        assert result["adjusted_close"].tolist() == [103.8, 104.9]

    def test_fetch_bars_single_level_columns(self) -> None:
        """Handle yfinance returning non-MultiIndex columns (e.g., single ticker)."""
        connector = YFinanceDataConnector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 3, tzinfo=timezone.utc)

        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        mock_raw = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [105.0, 106.0],
                "Low": [99.0, 100.0],
                "Close": [104.0, 105.0],
                "Volume": [10000, 11000],
            },
            index=dates,
        )
        # Not a MultiIndex -- _flatten_columns returns as-is

        with patch("yfinance.download", return_value=mock_raw):
            result = connector.fetch_bars("AAPL", start, end, "1d")

        assert not result.empty
        assert len(result) == 2
        assert list(result["close"]) == [104.0, 105.0]

    def test_fetch_bars_raises_runtime_error_when_yfinance_missing(self) -> None:
        """When yfinance cannot be imported, fetch_bars raises RuntimeError."""
        connector = YFinanceDataConnector()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 3, tzinfo=timezone.utc)

        # Simulate yfinance not available by mocking __import__ to fail
        original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def _failing_import(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("No module named yfinance")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_failing_import):
            with pytest.raises(RuntimeError, match="yfinance is required"):
                connector.fetch_bars("AAPL", start, end, "1d")
