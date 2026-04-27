from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.core.exceptions import StrategyNotFoundError
from backend.app.domain.models import StrategyDescriptor, StrategySignalPack
from backend.app.domain.strategy_base import StrategyBase, bollinger, donchian, ema, macd, rsi, sma


def _flat_signal(index: pd.Index) -> pd.Series:
    return pd.Series(0.0, index=index, dtype=float)


class TrendMacdStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="trend_macd",
        display_name="Trend MACD",
        description="EMA + MACD 顺势策略，趋势确认后做多或做空。",
        category="trend",
        default_weight=0.2,
        default_params={"fast_window": 20, "slow_window": 60, "signal_window": 9},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        fast_ema = ema(frame["close"], int(config["fast_window"]))
        slow_ema = ema(frame["close"], int(config["slow_window"]))
        dif, dea, hist = macd(
            frame["close"],
            int(config["fast_window"]),
            int(config["slow_window"]),
            int(config["signal_window"]),
        )
        signal = _flat_signal(frame.index)
        signal[(fast_ema > slow_ema) & (dif > dea)] = 1.0
        signal[(fast_ema < slow_ema) & (dif < dea)] = -1.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={
                "fast_ema": fast_ema,
                "slow_ema": slow_ema,
                "macd": dif,
                "signal_line": dea,
                "histogram": hist,
            },
        )


class ReversionRsiStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="reversion_rsi",
        display_name="Reversion RSI",
        description="RSI 与布林带结合的均值回归策略。",
        category="mean_reversion",
        default_weight=0.15,
        default_params={
            "rsi_window": 14,
            "boll_window": 20,
            "boll_dev": 2.0,
            "rsi_long": 30,
            "rsi_short": 70,
            "rsi_exit_low": 45,
            "rsi_exit_high": 55,
        },
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        indicator = rsi(frame["close"], int(config["rsi_window"]))
        upper, mid, lower = bollinger(frame["close"], int(config["boll_window"]), float(config["boll_dev"]))
        signal = _flat_signal(frame.index)
        signal[(indicator < config["rsi_long"]) & (frame["close"] <= lower)] = 1.0
        signal[(indicator > config["rsi_short"]) & (frame["close"] >= upper)] = -1.0
        exit_mask_long = (signal.shift(1).fillna(0.0) > 0) & (indicator >= config["rsi_exit_high"])
        exit_mask_short = (signal.shift(1).fillna(0.0) < 0) & (indicator <= config["rsi_exit_low"])
        signal[exit_mask_long | exit_mask_short] = 0.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"rsi": indicator, "upper_band": upper, "middle_band": mid, "lower_band": lower},
        )


class BreakoutStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="donchian_breakout",
        display_name="Donchian Breakout",
        description="Donchian 通道突破策略。",
        category="breakout",
        default_weight=0.15,
        default_params={"channel_window": 20},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        upper, lower = donchian(frame["high"], frame["low"], int(config["channel_window"]))
        middle = (upper + lower) / 2
        signal = _flat_signal(frame.index)
        signal[frame["close"] > upper] = 1.0
        signal[frame["close"] < lower] = -1.0
        signal[(signal.shift(1).fillna(0.0) > 0) & (frame["close"] < middle)] = 0.0
        signal[(signal.shift(1).fillna(0.0) < 0) & (frame["close"] > middle)] = 0.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"upper_band": upper, "middle_band": middle, "lower_band": lower},
        )


class VolatilitySqueezeStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="volatility_squeeze",
        display_name="Volatility Squeeze",
        description="波动率压缩后突破的趋势启动策略。",
        category="volatility",
        default_weight=0.15,
        default_params={"boll_window": 20, "boll_dev": 2.0, "width_threshold": 0.05},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        upper, middle, lower = bollinger(frame["close"], int(config["boll_window"]), float(config["boll_dev"]))
        width = (upper - lower) / middle.replace(0, pd.NA)
        signal = _flat_signal(frame.index)
        squeeze = width < float(config["width_threshold"])
        signal[squeeze & (frame["close"] > upper)] = 1.0
        signal[squeeze & (frame["close"] < lower)] = -1.0
        expanded = width > float(config["width_threshold"]) * 1.8
        signal[expanded & (frame["close"] < middle) & (signal.shift(1).fillna(0.0) > 0)] = 0.0
        signal[expanded & (frame["close"] > middle) & (signal.shift(1).fillna(0.0) < 0)] = 0.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"upper_band": upper, "middle_band": middle, "lower_band": lower, "width": width.fillna(0.0)},
        )


class FundingSentimentStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="funding_sentiment",
        display_name="Funding Sentiment",
        description="以快慢动量背离近似资金费率情绪逆转。",
        category="sentiment",
        default_weight=0.1,
        default_params={"momentum_short": 10, "momentum_long": 60, "divergence_threshold": 0.02},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        short_window = int(config["momentum_short"])
        long_window = int(config["momentum_long"])
        mom_short = frame["close"].pct_change(short_window)
        mom_long = frame["close"].pct_change(long_window)
        divergence = mom_short - mom_long
        threshold = float(config["divergence_threshold"])
        signal = _flat_signal(frame.index)
        signal[(mom_long > threshold) & (divergence < -threshold)] = 1.0
        signal[(mom_long < -threshold) & (divergence > threshold)] = -1.0
        signal[(signal.shift(1).fillna(0.0) != 0.0) & (divergence.abs() < threshold * 0.5)] = 0.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"mom_short": mom_short.fillna(0.0), "mom_long": mom_long.fillna(0.0), "divergence": divergence.fillna(0.0)},
        )


class MacroTrendStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="macro_trend",
        display_name="Macro Trend Stack",
        description="多周期均线堆叠的宏观趋势过滤策略。",
        category="macro",
        default_weight=0.05,
        default_params={"short_ma": 20, "medium_ma": 60, "long_ma": 120},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        short_ma = sma(frame["close"], int(config["short_ma"]))
        medium_ma = sma(frame["close"], int(config["medium_ma"]))
        long_ma = sma(frame["close"], int(config["long_ma"]))
        signal = _flat_signal(frame.index)
        signal[(short_ma > medium_ma) & (medium_ma > long_ma)] = 1.0
        signal[(short_ma < medium_ma) & (medium_ma < long_ma)] = -1.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"short_ma": short_ma, "medium_ma": medium_ma, "long_ma": long_ma},
        )


class TimeWindowStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="time_window",
        display_name="Time Window Effect",
        description="利用固定周内时段效应的日历策略。",
        category="seasonality",
        default_weight=0.1,
        default_params={},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        weekdays = frame.index.weekday
        hours = frame.index.hour
        signal = _flat_signal(frame.index)
        signal[(weekdays == 0) & (hours >= 0) & (hours <= 4)] = 1.0
        signal[(weekdays == 4) & (hours >= 14) & (hours <= 20)] = -1.0
        return StrategySignalPack(signal=signal.fillna(0.0), diagnostics={})


class DynamicGridStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="dynamic_grid",
        display_name="Dynamic Grid",
        description="围绕移动均价上下波动的动态网格策略。",
        category="mean_reversion",
        default_weight=0.1,
        default_params={"center_window": 60, "band_pct": 0.02},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        center = sma(frame["close"], int(config["center_window"]))
        band_pct = float(config["band_pct"])
        upper = center * (1 + band_pct)
        lower = center * (1 - band_pct)
        signal = _flat_signal(frame.index)
        signal[frame["close"] < lower] = 1.0
        signal[frame["close"] > upper] = -1.0
        inner_upper = center * (1 + band_pct * 0.3)
        inner_lower = center * (1 - band_pct * 0.3)
        signal[(signal.shift(1).fillna(0.0) != 0.0) & frame["close"].between(inner_lower, inner_upper)] = 0.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"center": center, "upper_band": upper, "lower_band": lower},
        )


@dataclass
class StrategyRegistry:
    strategies: dict[str, StrategyBase]

    def list_descriptors(self) -> list[StrategyDescriptor]:
        return [strategy.descriptor for strategy in self.strategies.values()]

    def get(self, strategy_id: str) -> StrategyBase:
        if strategy_id not in self.strategies:
            raise StrategyNotFoundError(f"Unknown strategy: {strategy_id}")
        return self.strategies[strategy_id]


strategy_registry = StrategyRegistry(
    strategies={
        strategy.descriptor.id: strategy
        for strategy in [
            TrendMacdStrategy(),
            ReversionRsiStrategy(),
            BreakoutStrategy(),
            VolatilitySqueezeStrategy(),
            FundingSentimentStrategy(),
            MacroTrendStrategy(),
            TimeWindowStrategy(),
            DynamicGridStrategy(),
        ]
    }
)
