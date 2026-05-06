"""Tests for the data vendor abstraction layer (T-074).

Covers:
  - Registry / factory
  - ABC guard
  - YFinanceDataConnector vendor tag
  - AlpacaDataConnector vendor tag + IEX note + fetch_bars + fetch_account + error handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quant_us.data.connectors.alpaca_data import AlpacaDataConfig, AlpacaDataConnector
from quant_us.data.connectors.base import MarketDataConnector
from quant_us.data.connectors.factory import (
    DATA_VENDOR_REGISTRY,
    available_vendors,
    get_connector,
)
from quant_us.data.connectors.yfinance_data import (
    YFinanceDataConfig,
    YFinanceDataConnector,
)


# ---------------------------------------------------------------------------
# ABC guard
# ---------------------------------------------------------------------------
def test_abc_cannot_be_instantiated():
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        MarketDataConnector()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
class TestFactory:
    def test_get_connector_yfinance(self):
        conn = get_connector("yfinance")
        assert isinstance(conn, YFinanceDataConnector)
        assert conn.vendor == "yfinance"

    def test_get_connector_alpaca(self):
        """get_connector returns AlpacaDataConnector; constructor needs config."""
        conn = get_connector(
            "alpaca",
            config=AlpacaDataConfig(api_key="k", api_secret="s"),
        )
        assert isinstance(conn, AlpacaDataConnector)
        assert conn.vendor == "alpaca"

    def test_get_connector_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown data vendor"):
            get_connector("bloomberg")

    def test_available_vendors(self):
        vendors = available_vendors()
        assert "yfinance" in vendors
        assert "alpaca" in vendors

    def test_registry_contains_both(self):
        assert "yfinance" in DATA_VENDOR_REGISTRY
        assert "alpaca" in DATA_VENDOR_REGISTRY
        assert DATA_VENDOR_REGISTRY["yfinance"] is YFinanceDataConnector
        assert DATA_VENDOR_REGISTRY["alpaca"] is AlpacaDataConnector


# ---------------------------------------------------------------------------
# YFinanceDataConnector
# ---------------------------------------------------------------------------
class TestYFinanceConnector:
    def test_vendor_tag(self):
        assert YFinanceDataConnector.vendor == "yfinance"

    def test_connector_default_supports(self):
        """yfinance supports() returns True (no restriction)."""
        conn = YFinanceDataConnector()
        assert conn.supports("AAPL") is True
        assert conn.supports("") is True

    def test_fetch_account_returns_empty(self):
        conn = YFinanceDataConnector()
        assert conn.fetch_account() == {}


# ---------------------------------------------------------------------------
# AlpacaDataConnector
# ---------------------------------------------------------------------------
class TestAlpacaConnector:
    def test_vendor_tag(self):
        assert AlpacaDataConnector.vendor == "alpaca"

    def test_iex_note_in_docstring(self):
        """IEX data limitation must be documented in class docstring."""
        doc = AlpacaDataConnector.__doc__ or AlpacaDataConnector.__init__.__doc__ or ""
        assert "IEX" in doc, "Alpaca docstring must mention IEX data limitation"

    def test_supports_valid(self):
        conn = AlpacaDataConnector(config=AlpacaDataConfig(api_key="k", api_secret="s"))
        assert conn.supports("AAPL") is True
        assert conn.supports("BRK.B") is True
        assert conn.supports("SPY") is True

    def test_supports_invalid(self):
        conn = AlpacaDataConnector(config=AlpacaDataConfig(api_key="k", api_secret="s"))
        assert conn.supports("") is False
        assert conn.supports("A" * 21) is False

    # ------------------------------------------------------------------
    # Mocked fetch_bars tests
    # ------------------------------------------------------------------
    def test_fetch_bars_returns_dataframe(self):
        """Mock the alpaca SDK and verify DataFrame shape."""
        mock_bar = MagicMock()
        mock_bar.t = 1640995200  # 2022-01-01 00:00:00 UTC
        mock_bar.o = 100.0
        mock_bar.h = 101.0
        mock_bar.l = 99.0
        mock_bar.c = 100.5
        mock_bar.v = 10000
        mock_bar.vw = 100.25
        mock_bar.n = 500

        mock_client = MagicMock()
        mock_client.get_bars_iter.return_value = [mock_bar]

        config = AlpacaDataConfig(api_key="test_key", api_secret="test_secret")
        conn = AlpacaDataConnector(config)
        conn._client = mock_client

        import datetime

        start = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2022, 1, 10, tzinfo=datetime.timezone.utc)

        df = conn.fetch_bars("AAPL", start, end, "1d")

        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == [
            "timestamp_utc",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "vwap",
            "trade_count",
            "source",
            "adjusted_flag",
        ]
        assert df.iloc[0]["symbol"] == "AAPL"
        assert df.iloc[0]["open"] == 100.0
        assert df.iloc[0]["source"] == "alpaca"

    def test_fetch_bars_empty_on_api_error(self):
        """Alpaca should return empty DataFrame on API error."""
        mock_client = MagicMock()
        mock_client.get_bars_iter.side_effect = Exception("API error")

        config = AlpacaDataConfig(api_key="test_key", api_secret="test_secret")
        conn = AlpacaDataConnector(config)
        conn._client = mock_client

        import datetime

        start = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2022, 1, 10, tzinfo=datetime.timezone.utc)

        df = conn.fetch_bars("AAPL", start, end, "1d")
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_fetch_bars_empty_when_end_before_start(self):
        config = AlpacaDataConfig(api_key="k", api_secret="s")
        conn = AlpacaDataConnector(config)

        import datetime

        start = datetime.datetime(2022, 2, 1, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc)

        df = conn.fetch_bars("AAPL", start, end, "1d")
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    # ------------------------------------------------------------------
    # Mocked fetch_account tests
    # ------------------------------------------------------------------
    def test_fetch_account_returns_dict(self):
        """Mock the alpaca SDK account call."""
        mock_acct = MagicMock()
        mock_acct.id = "test123"
        mock_acct.status = "ACTIVE"
        mock_acct.currency = "USD"
        mock_acct.cash = "100000.0"
        mock_acct.buying_power = "200000.0"
        mock_acct.equity = "150000.0"
        mock_acct.last_equity = "145000.0"
        mock_acct.daytrade_count = 0
        mock_acct.daytrading_buying_power = "200000.0"

        mock_client = MagicMock()
        mock_client.get_account.return_value = mock_acct

        config = AlpacaDataConfig(api_key="test_key", api_secret="test_secret")
        conn = AlpacaDataConnector(config)
        conn._client = mock_client

        acct = conn.fetch_account()
        assert isinstance(acct, dict)
        assert acct["id"] == "test123"
        assert acct["status"] == "ACTIVE"
        assert acct["cash"] == 100000.0
        assert acct["buying_power"] == 200000.0

    def test_fetch_account_returns_empty_on_error(self):
        mock_client = MagicMock()
        mock_client.get_account.side_effect = Exception("Auth error")

        config = AlpacaDataConfig(api_key="bad_key", api_secret="bad_secret")
        conn = AlpacaDataConnector(config)
        conn._client = mock_client

        acct = conn.fetch_account()
        assert isinstance(acct, dict)
        assert acct == {}

    # ------------------------------------------------------------------
    # bar_size mapping
    # ------------------------------------------------------------------
    def test_to_alpaca_timeframe(self):
        assert AlpacaDataConnector._to_alpaca_timeframe("1m") == "1Min"
        assert AlpacaDataConnector._to_alpaca_timeframe("5m") == "5Min"
        assert AlpacaDataConnector._to_alpaca_timeframe("1d") == "1Day"
        assert AlpacaDataConnector._to_alpaca_timeframe("1wk") == "1Week"

    def test_to_alpaca_timeframe_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported Alpaca bar_size"):
            AlpacaDataConnector._to_alpaca_timeframe("1y")


# ---------------------------------------------------------------------------
# Integration: factory + connector wiring
# ---------------------------------------------------------------------------
class TestFactoryIntegration:
    def test_yfinance_created_via_factory(self):
        conn = get_connector("yfinance")
        assert conn.vendor == "yfinance"
        assert isinstance(conn, YFinanceDataConnector)

    def test_alpaca_created_via_factory(self):
        conn = get_connector(
            "alpaca",
            config=AlpacaDataConfig(api_key="k", api_secret="s"),
        )
        assert conn.vendor == "alpaca"
        assert isinstance(conn, AlpacaDataConnector)
