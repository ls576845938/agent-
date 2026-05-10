from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.clock import ET, ensure_utc
from quant_us.data.connectors.base import MarketDataConnector


@dataclass(frozen=True)
class YFinanceDataConfig:
    auto_adjust: bool = False
    prepost: bool = True


class YFinanceDataConnector(MarketDataConnector):
    """Auxiliary free data connector for MVP research.

    This is deliberately marked as a helper source, not a production source.
    """

    vendor = "yfinance"

    def __init__(self, config: YFinanceDataConfig | None = None) -> None:
        self.config = config or YFinanceDataConfig()

    def fetch_bars(self, symbol: str, start: datetime, end: datetime, bar_size: str) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is required for YFinanceDataConnector") from exc

        frame = yf.download(
            tickers=symbol.upper(),
            start=ensure_utc(start).date().isoformat(),
            end=ensure_utc(end).date().isoformat(),
            interval=self._to_yfinance_interval(bar_size),
            auto_adjust=self.config.auto_adjust,
            prepost=self.config.prepost,
            progress=False,
            group_by="column",
            threads=False,
        )
        if frame.empty:
            return pd.DataFrame()

        frame = self._flatten_columns(frame)
        normalized = pd.DataFrame(
            {
                "timestamp_utc": self._normalize_index(frame.index, bar_size),
                "symbol": symbol.upper(),
                "open": frame.get("Open"),
                "high": frame.get("High"),
                "low": frame.get("Low"),
                "close": frame.get("Close"),
                "volume": frame.get("Volume", 0),
                "vwap": pd.NA,
                "trade_count": pd.NA,
                "source": self.vendor,
                "adjusted_flag": self.config.auto_adjust,
            }
        )
        if "Adj Close" in frame.columns:
            normalized["adjusted_close"] = frame["Adj Close"].to_numpy()
        return normalized.dropna(subset=["open", "high", "low", "close"])

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
        metadata["source_lineage"] = "connector:yfinance:download"
        adjustment_policy = cls._infer_adjustment_policy(frame)
        if adjustment_policy:
            metadata["adjustment_policy"] = adjustment_policy
            metadata["corporate_action_adjustment"] = adjustment_policy
        return metadata

    @staticmethod
    def _to_yfinance_interval(bar_size: str) -> str:
        lookup = {
            "1m": "1m",
            "2m": "2m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "60m": "60m",
            "1h": "60m",
            "1d": "1d",
            "1wk": "1wk",
        }
        if bar_size not in lookup:
            raise ValueError(f"Unsupported yfinance bar_size: {bar_size}")
        return lookup[bar_size]

    @staticmethod
    def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(frame.columns, pd.MultiIndex):
            return frame
        working = frame.copy()
        if "Price" in working.columns.names:
            working.columns = working.columns.get_level_values("Price")
        else:
            working.columns = working.columns.get_level_values(0)
        return working

    @staticmethod
    def _normalize_index(index: pd.Index, bar_size: str) -> pd.DatetimeIndex:
        timestamps = pd.to_datetime(index)
        if bar_size == "1d":
            close_times = [datetime.combine(item.date(), time(15, 59), tzinfo=ET) for item in timestamps]
            return pd.DatetimeIndex(close_times).tz_convert("UTC")
        if timestamps.tz is None:
            timestamps = timestamps.tz_localize(ET)
        return timestamps.tz_convert("UTC")

    @staticmethod
    def _infer_adjustment_policy(frame: pd.DataFrame | None) -> str:
        if frame is None or frame.empty:
            return ""
        if "adjusted_flag" in frame.columns:
            flags = frame["adjusted_flag"].dropna()
            if not flags.empty:
                normalized = flags.map(lambda value: str(value).strip().lower() in {"1", "true", "t", "yes"})
                if bool(normalized.all()):
                    return "split_dividend_adjusted"
                if not bool(normalized.any()):
                    return "raw"
                return "unknown"
        if "adjusted_close" in frame.columns:
            return "raw"
        return ""
