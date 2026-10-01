"""Alpaca Markets data connector.

Notes
-----
Alpaca Paper Only accounts use IEX data, not full SIP.
For live / funded accounts Alpaca provides full SIP data.

This connector uses the Alpaca Markets REST API
(``alpaca_trade_api`` SDK) to fetch historical bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.data.connectors.base import MarketDataConnector


@dataclass(frozen=True)
class AlpacaDataConfig:
    api_key: str
    api_secret: str
    base_url: str = "https://paper-api.alpaca.markets"
    data_url: str = "https://data.alpaca.markets"


class AlpacaDataConnector(MarketDataConnector):
    """Market-data connector backed by Alpaca Markets API.

    Notes
    -----
    Alpaca Paper Only accounts use IEX data, not full SIP.
    This means bar data for paper accounts may differ from
    SIP-based feeds (e.g. yfinance).  Do not mix data sources
    in the same backtest without explicitly documenting the
    source discrepancy.
    """

    vendor = "alpaca"

    def __init__(self, config: AlpacaDataConfig) -> None:
        self.config = config
        self._client = None

    # ------------------------------------------------------------------
    # SDK lazy-init
    # ------------------------------------------------------------------
    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import alpaca_trade_api as tradeapi

            self._client = tradeapi.REST(
                key_id=self.config.api_key,
                secret_key=self.config.api_secret,
                base_url=self.config.base_url,
                data_url=self.config.data_url,
            )
        except ImportError as exc:
            raise RuntimeError(
                "alpaca_trade_api is required for AlpacaDataConnector"
            ) from exc
        return self._client

    # ------------------------------------------------------------------
    # MarketDataConnector interface
    # ------------------------------------------------------------------
    def fetch_bars(self, symbol: str, start: datetime, end: datetime, bar_size: str) -> pd.DataFrame:
        """Fetch historical bars from Alpaca.

        Returns an empty DataFrame if the API call fails or no data exists.
        """
        try:
            client = self._get_client()
            # alpaca_trade_api expects ISO-8601 strings
            start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")
            if end_str <= start_str:
                return pd.DataFrame()

            bars = client.get_bars_iter(
                symbol,
                self._to_alpaca_timeframe(bar_size),
                start=start_str,
                end=end_str,
            )
            records: list[dict[str, Any]] = []
            for bar in bars:
                records.append(
                    {
                        "timestamp_utc": pd.Timestamp(bar.t, unit="s", tz="UTC"),
                        "symbol": symbol.upper(),
                        "open": bar.o,
                        "high": bar.h,
                        "low": bar.l,
                        "close": bar.c,
                        "volume": bar.v,
                        "vwap": getattr(bar, "vw", pd.NA),
                        "trade_count": getattr(bar, "n", pd.NA),
                        "source": self.vendor,
                        "adjusted_flag": False,
                    }
                )

            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records)
            return df.dropna(subset=["open", "high", "low", "close"])

        except Exception:
            return pd.DataFrame()

    @classmethod
    def quality_metadata(
        cls,
        *,
        symbol: str,
        start: Any,
        end: Any,
        bar_size: str,
        frame: pd.DataFrame | None = None,
        data_root: str | Path = "data/cleaned",
    ) -> dict[str, Any]:
        metadata = super().quality_metadata(
            symbol=symbol,
            start=start,
            end=end,
            bar_size=bar_size,
            frame=frame,
            data_root=data_root,
        )
        metadata["cleaned_path"] = str(
            Path(data_root)
            / f"vendor={cls.vendor}"
            / "asset_class=equity"
            / f"bar_size={bar_size}"
            / f"symbol={symbol.upper()}"
        )
        metadata["source_lineage"] = "connector:alpaca:get_bars_iter"
        metadata["adjustment_policy"] = "raw"
        metadata["corporate_action_adjustment"] = "raw"
        return metadata

    def fetch_account(self) -> dict[str, Any]:
        """Fetch Alpaca account information.

        Returns dict keys: id, status, currency, cash, buying_power,
        equity, last_equity, daytrade_count, daytrading_buying_power.
        Returns an empty dict on error.
        """
        try:
            client = self._get_client()
            acct = client.get_account()
            return {
                "id": getattr(acct, "id", ""),
                "status": getattr(acct, "status", ""),
                "currency": getattr(acct, "currency", "USD"),
                "cash": float(getattr(acct, "cash", 0)),
                "buying_power": float(getattr(acct, "buying_power", 0)),
                "equity": float(getattr(acct, "equity", 0)),
                "last_equity": float(getattr(acct, "last_equity", 0)),
                "daytrade_count": int(getattr(acct, "daytrade_count", 0)),
                "daytrading_buying_power": float(getattr(acct, "daytrading_buying_power", 0)),
            }
        except Exception:
            return {}

    def supports(self, symbol: str) -> bool:
        """Alpaca supports most US-traded equities and ETFs."""
        # Basic validation: non-empty alphanumeric + potential dot/broken
        if not symbol or len(symbol) > 20:
            return False
        return symbol.replace(".", "").replace("-", "").isalnum()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_alpaca_timeframe(bar_size: str) -> str:
        """Map internal bar_size to Alpaca TimeFrame string.

        Alpaca accepts: 1Min, 5Min, 15Min, 1Hour, 1Day, 1Week, 1Month
        """
        lookup = {
            "1m": "1Min",
            "5m": "5Min",
            "15m": "15Min",
            "30m": "30Min",
            "60m": "1Hour",
            "1h": "1Hour",
            "1d": "1Day",
            "1wk": "1Week",
        }
        if bar_size not in lookup:
            raise ValueError(f"Unsupported Alpaca bar_size: {bar_size}")
        return lookup[bar_size]
