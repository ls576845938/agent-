from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import pandas as pd


class MarketDataConnector(ABC):
    vendor: str

    @abstractmethod
    def fetch_bars(self, symbol: str, start: datetime, end: datetime, bar_size: str) -> pd.DataFrame:
        """Fetch historical bars for a symbol.

        Returns a DataFrame with columns:
            timestamp_utc, symbol, open, high, low, close, volume, vwap, trade_count, source, adjusted_flag
        Returns empty DataFrame on error or no data.
        """
        raise NotImplementedError

    def fetch_account(self) -> dict[str, Any]:
        """Fetch account information (broker data sources only).

        Returns an empty dict by default for non-broker connectors.
        """
        return {}

    def supports(self, symbol: str) -> bool:
        """Check whether this connector can provide data for *symbol*."""
        return True
