from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from backend.app.domain.models import StrategyDescriptor, StrategySignalPack


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = losses.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    indicator = 100 - (100 / (1 + rs))
    return indicator.fillna(50.0)


def bollinger(series: pd.Series, window: int, num_std: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + std * num_std
    lower = mid - std * num_std
    return upper, mid, lower


def donchian(high: pd.Series, low: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    return (
        high.rolling(window=window, min_periods=window).max(),
        low.rolling(window=window, min_periods=window).min(),
    )


def macd(series: pd.Series, fast_window: int, slow_window: int, signal_window: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast = ema(series, fast_window)
    slow = ema(series, slow_window)
    dif = fast - slow
    dea = dif.ewm(span=signal_window, adjust=False, min_periods=signal_window).mean()
    hist = dif - dea
    return dif, dea, hist


class StrategyBase(ABC):
    descriptor: StrategyDescriptor

    def __init__(self) -> None:
        self.id = self.descriptor.id

    @abstractmethod
    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        raise NotImplementedError
