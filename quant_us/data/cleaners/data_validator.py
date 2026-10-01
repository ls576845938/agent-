from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DataQualityReport:
    row_count: int
    duplicate_timestamps: int
    non_positive_prices: int
    invalid_ohlc: int
    missing_bars: int

    @property
    def is_usable(self) -> bool:
        return self.row_count > 0 and self.non_positive_prices == 0 and self.invalid_ohlc == 0


class BarDataValidator:
    def validate(self, frame: pd.DataFrame, expected_interval: str | None = None) -> DataQualityReport:
        if frame.empty:
            return DataQualityReport(0, 0, 0, 0, 0)

        timestamp_col = "timestamp_utc" if "timestamp_utc" in frame.columns else None
        timestamps = pd.to_datetime(frame[timestamp_col], utc=True) if timestamp_col else pd.to_datetime(frame.index, utc=True)
        duplicate_timestamps = int(timestamps.duplicated().sum())

        prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
        non_positive_prices = int((prices <= 0).any(axis=1).sum())
        invalid_ohlc = int(
            (
                (prices["high"] < prices[["open", "close", "low"]].max(axis=1))
                | (prices["low"] > prices[["open", "close", "high"]].min(axis=1))
            ).sum()
        )

        missing_bars = 0
        if expected_interval:
            freq = self._to_pandas_freq(expected_interval)
            if freq:
                ordered = pd.Series(index=pd.DatetimeIndex(timestamps).sort_values(), data=1)
                expected = pd.date_range(start=ordered.index.min(), end=ordered.index.max(), freq=freq, tz="UTC")
                missing_bars = max(0, len(expected.difference(ordered.index.unique())))

        return DataQualityReport(
            row_count=len(frame),
            duplicate_timestamps=duplicate_timestamps,
            non_positive_prices=non_positive_prices,
            invalid_ohlc=invalid_ohlc,
            missing_bars=missing_bars,
        )

    @staticmethod
    def _to_pandas_freq(interval: str) -> str:
        lookup = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1h",
            "1d": "B",
        }
        return lookup.get(interval, "")
