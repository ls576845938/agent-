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


class TrendMomentumStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="trend_momentum",
        display_name="Trend Momentum (US)",
        description="Price momentum over lookback window with entry threshold.",
        category="momentum",
        default_weight=0.12,
        default_params={"lookback_bars": 20, "entry_threshold": 0.03},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        lookback = int(config["lookback_bars"])
        threshold = float(config["entry_threshold"])
        momentum = frame["close"].pct_change(lookback).fillna(0.0)
        signal = _flat_signal(frame.index)
        signal[momentum >= threshold] = 1.0
        signal[momentum <= -threshold] = -1.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"momentum": momentum},
        )


class ShortReversionStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="short_reversion",
        display_name="Short Reversion (US)",
        description="Mean reversion on short-term price deviations.",
        category="mean_reversion",
        default_weight=0.1,
        default_params={"window": 10, "threshold": 0.02},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        window = int(config["window"])
        threshold = float(config["threshold"])
        mean_price = sma(frame["close"], window)
        deviation = (frame["close"] - mean_price) / mean_price.replace(0, pd.NA)
        signal = _flat_signal(frame.index)
        signal[deviation < -threshold] = 1.0
        signal[deviation > threshold] = -1.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"deviation": deviation.fillna(0.0)},
        )


class FactorRankStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="factor_rank",
        display_name="Factor Rank (US)",
        description="Cross-sectional factor ranking based on momentum and volatility.",
        category="momentum",
        default_weight=0.1,
        default_params={"momentum_window": 20, "vol_window": 20},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        mom_w = int(config["momentum_window"])
        vol_w = int(config["vol_window"])
        momentum = frame["close"].pct_change(mom_w).fillna(0.0)
        volatility = frame["close"].pct_change().rolling(vol_w).std(ddof=0).fillna(0.0)
        vol_denom = volatility.replace(0, pd.NA)
        factor_score = (momentum / vol_denom).fillna(0.0)
        signal = factor_score.clip(-1.0, 1.0)
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"momentum": momentum, "volatility": volatility},
        )


class EarningsDriftStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="earnings_drift",
        display_name="Earnings Drift (US)",
        description="Post-earnings announcement drift using price trend.",
        category="event",
        default_weight=0.1,
        default_params={"drift_window": 5, "drift_threshold": 0.01},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        window = int(config["drift_window"])
        threshold = float(config["drift_threshold"])
        drift = frame["close"].pct_change(window).fillna(0.0)
        signal = _flat_signal(frame.index)
        signal[drift > threshold] = 1.0
        signal[drift < -threshold] = -1.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"drift": drift},
        )


class ETFRotationStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="etf_rotation",
        display_name="ETF Rotation (US)",
        description="Rotate between ETFs based on relative momentum.",
        category="momentum",
        default_weight=0.1,
        default_params={"rotation_window": 20, "momentum_threshold": 0.02},
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        window = int(config["rotation_window"])
        threshold = float(config["momentum_threshold"])
        rel_momentum = frame["close"].pct_change(window).fillna(0.0)
        signal = _flat_signal(frame.index)
        signal[rel_momentum >= threshold] = 1.0
        signal[rel_momentum <= -threshold] = -1.0
        signal[(rel_momentum.abs() < threshold * 0.5) & (signal.shift(1).fillna(0.0) != 0)] = 0.0
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={"rel_momentum": rel_momentum},
        )


class BtcLowTurnoverTrendStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="btc_low_turnover_trend",
        display_name="BTC Low Turnover Trend",
        description="BTC 长周期趋势确认 + 波动率过滤的低换手 long-only 策略。",
        category="trend",
        default_weight=0.12,
        default_params={
            "fast_ma": 48,
            "slow_ma": 168,
            "trend_ma": 336,
            "vol_window": 72,
            "min_volatility": 0.003,
            "max_volatility": 0.06,
            "trend_strength": 0.04,
            "exit_buffer": 0.02,
            "entry_confirm_bars": 3,
            "exit_confirm_bars": 6,
            "min_hold_bars": 72,
            "cooldown_bars": 24,
        },
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        fast_ma = sma(frame["close"], int(config["fast_ma"]))
        slow_ma = sma(frame["close"], int(config["slow_ma"]))
        trend_ma = sma(frame["close"], int(config["trend_ma"]))
        exit_ma = sma(frame["close"], max(2, int(config["fast_ma"] // 2)))
        returns = frame["close"].pct_change()
        volatility = returns.rolling(int(config["vol_window"]), min_periods=int(config["vol_window"])).std(ddof=0)
        trend_strength = (frame["close"] / trend_ma.replace(0, pd.NA)) - 1.0

        entry_ready = (
            (fast_ma > slow_ma)
            & (slow_ma > trend_ma)
            & (trend_strength >= float(config["trend_strength"]))
            & volatility.between(float(config["min_volatility"]), float(config["max_volatility"]))
        ).fillna(False)
        exit_ready = (
            (frame["close"] < exit_ma)
            | (fast_ma < slow_ma)
            | (frame["close"] < trend_ma * (1.0 - float(config["exit_buffer"])))
            | (volatility > float(config["max_volatility"]))
        ).fillna(False)

        signal = _flat_signal(frame.index)
        in_position = 0.0
        entry_streak = 0
        exit_streak = 0
        bars_held = 0
        cooldown_remaining = 0
        entry_confirm_bars = max(1, int(config["entry_confirm_bars"]))
        exit_confirm_bars = max(1, int(config["exit_confirm_bars"]))
        min_hold_bars = max(0, int(config["min_hold_bars"]))
        cooldown_bars = max(0, int(config["cooldown_bars"]))
        for idx in frame.index:
            if cooldown_remaining > 0:
                cooldown_remaining -= 1

            if bool(entry_ready.loc[idx]):
                entry_streak += 1
            else:
                entry_streak = 0

            if bool(exit_ready.loc[idx]):
                exit_streak += 1
            else:
                exit_streak = 0

            if in_position == 0.0 and cooldown_remaining == 0 and entry_streak >= entry_confirm_bars:
                in_position = 1.0
                bars_held = 0
                exit_streak = 0
            elif in_position == 1.0 and bars_held >= min_hold_bars and exit_streak >= exit_confirm_bars:
                in_position = 0.0
                cooldown_remaining = cooldown_bars
                bars_held = 0
                entry_streak = 0
            if in_position == 1.0:
                bars_held += 1
            signal.loc[idx] = in_position

        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "trend_ma": trend_ma,
                "exit_ma": exit_ma,
                "volatility": volatility.fillna(0.0),
                "trend_strength": trend_strength.fillna(0.0),
                "entry_ready": entry_ready.astype(float),
                "exit_ready": exit_ready.astype(float),
            },
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
            TrendMomentumStrategy(),
            ShortReversionStrategy(),
            FactorRankStrategy(),
            EarningsDriftStrategy(),
            ETFRotationStrategy(),
            BtcLowTurnoverTrendStrategy(),
        ]
    }
)
