from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.core.exceptions import StrategyNotFoundError
from backend.app.domain.models import StrategyDescriptor, StrategySignalPack
from backend.app.domain.strategy_base import StrategyBase, bollinger, donchian, ema, macd, rsi, sma


def _flat_signal(index: pd.Index) -> pd.Series:
    return pd.Series(0.0, index=index, dtype=float)


def _confirmed_stateful_long_signal(
    index: pd.Index,
    *,
    entry_ready: pd.Series,
    exit_ready: pd.Series,
    entry_confirm_bars: int,
    exit_confirm_bars: int,
    min_hold_bars: int,
    cooldown_bars: int,
    max_hold_bars: int = 0,
) -> pd.Series:
    signal = _flat_signal(index)
    in_position = 0.0
    entry_streak = 0
    exit_streak = 0
    bars_held = 0
    cooldown_remaining = 0
    entry_confirm = max(1, int(entry_confirm_bars))
    exit_confirm = max(1, int(exit_confirm_bars))
    min_hold = max(0, int(min_hold_bars))
    max_hold = max(0, int(max_hold_bars))
    cooldown = max(0, int(cooldown_bars))

    for idx in index:
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
        force_exit = in_position == 1.0 and max_hold > 0 and bars_held >= max_hold
        if in_position == 0.0 and cooldown_remaining == 0 and entry_streak >= entry_confirm:
            in_position = 1.0
            bars_held = 0
            exit_streak = 0
        elif in_position == 1.0 and (force_exit or (bars_held >= min_hold and exit_streak >= exit_confirm)):
            in_position = 0.0
            cooldown_remaining = cooldown
            bars_held = 0
            entry_streak = 0
        if in_position == 1.0:
            bars_held += 1
        signal.loc[idx] = in_position
    return signal


BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS = {
    "regime_filter_enabled": 1.0,
    "regime_filter_window": 168,
    "regime_filter_vol_window": 168,
    "regime_filter_low_vol_quantile": 0.50,
    "regime_filter_downtrend_threshold": 0.0,
    "regime_filter_reentry_return_threshold": 0.01,
    "max_hold_bars": 720,
}


def _btc_downtrend_low_volatility_filter(
    frame: pd.DataFrame,
    config: dict[str, float],
) -> tuple[pd.Series, dict[str, pd.Series]]:
    enabled = float(config.get("regime_filter_enabled", 1.0)) > 0.0
    if not enabled or frame.empty:
        risk_off = pd.Series(False, index=frame.index, dtype=bool)
        return risk_off, {
            "regime_return": pd.Series(0.0, index=frame.index, dtype=float),
            "regime_volatility": pd.Series(0.0, index=frame.index, dtype=float),
            "regime_low_vol_threshold": pd.Series(0.0, index=frame.index, dtype=float),
            "regime_downtrend_state": pd.Series(0.0, index=frame.index, dtype=float),
            "regime_low_volatility_state": pd.Series(0.0, index=frame.index, dtype=float),
            "regime_reentry_state": pd.Series(0.0, index=frame.index, dtype=float),
            "downtrend_low_vol_trigger": pd.Series(0.0, index=frame.index, dtype=float),
            "downtrend_low_vol_risk_off": risk_off.astype(float),
        }

    close = frame["close"].astype(float)
    returns = close.pct_change()
    trend_window = max(2, int(config.get("regime_filter_window", 168)))
    vol_window = max(2, int(config.get("regime_filter_vol_window", trend_window)))
    low_vol_quantile = min(1.0, max(0.0, float(config.get("regime_filter_low_vol_quantile", 0.50))))
    downtrend_threshold = float(config.get("regime_filter_downtrend_threshold", 0.0))
    reentry_threshold = float(config.get("regime_filter_reentry_return_threshold", 0.01))
    regime_return = close.pct_change(trend_window)
    realized_vol = returns.rolling(vol_window, min_periods=vol_window).std(ddof=0)
    low_vol_threshold = realized_vol.expanding(min_periods=vol_window).quantile(low_vol_quantile)
    downtrend_state = regime_return <= downtrend_threshold
    low_volatility_state = realized_vol <= low_vol_threshold
    trigger = (downtrend_state & low_volatility_state).fillna(False)
    reentry_state = (regime_return > reentry_threshold).fillna(False)
    risk_off_values: list[bool] = []
    active = False
    for idx in frame.index:
        if bool(trigger.loc[idx]):
            active = True
        elif active and bool(reentry_state.loc[idx]):
            active = False
        risk_off_values.append(active)
    risk_off = pd.Series(risk_off_values, index=frame.index, dtype=bool)
    return risk_off.astype(bool), {
        "regime_return": regime_return.fillna(0.0),
        "regime_volatility": realized_vol.fillna(0.0),
        "regime_low_vol_threshold": low_vol_threshold.fillna(0.0),
        "regime_downtrend_state": downtrend_state.fillna(False).astype(float),
        "regime_low_volatility_state": low_volatility_state.fillna(False).astype(float),
        "regime_reentry_state": reentry_state.astype(float),
        "downtrend_low_vol_trigger": trigger.astype(float),
        "downtrend_low_vol_risk_off": risk_off.astype(float),
    }


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
            **BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS,
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

        risk_off, regime_diagnostics = _btc_downtrend_low_volatility_filter(frame, config)
        entry_ready = (
            (fast_ma > slow_ma)
            & (slow_ma > trend_ma)
            & (trend_strength >= float(config["trend_strength"]))
            & volatility.between(float(config["min_volatility"]), float(config["max_volatility"]))
            & ~risk_off
        ).fillna(False)
        exit_ready = (
            (frame["close"] < exit_ma)
            | (fast_ma < slow_ma)
            | (frame["close"] < trend_ma * (1.0 - float(config["exit_buffer"])))
            | (volatility > float(config["max_volatility"]))
            | risk_off
        ).fillna(False)

        signal = _confirmed_stateful_long_signal(
            frame.index,
            entry_ready=entry_ready,
            exit_ready=exit_ready,
            entry_confirm_bars=int(config["entry_confirm_bars"]),
            exit_confirm_bars=int(config["exit_confirm_bars"]),
            min_hold_bars=int(config["min_hold_bars"]),
            cooldown_bars=int(config["cooldown_bars"]),
            max_hold_bars=int(config.get("max_hold_bars", 0)),
        )

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
                **regime_diagnostics,
            },
        )


class BtcTrendPullbackStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="btc_trend_pullback",
        display_name="BTC Trend Pullback",
        description="BTC 大趋势向上时等待回撤后重新站上均线，只做多，控制追高和换手。",
        category="trend",
        default_weight=0.10,
        default_params={
            **BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS,
            "fast_ma": 48,
            "slow_ma": 168,
            "trend_ma": 336,
            "pullback_pct": 0.035,
            "pullback_lookback": 36,
            "pullback_rsi": 45,
            "rsi_window": 14,
            "trend_strength": 0.02,
            "exit_buffer": 0.025,
            "entry_confirm_bars": 2,
            "exit_confirm_bars": 4,
            "min_hold_bars": 48,
            "cooldown_bars": 24,
        },
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        fast_ma = sma(frame["close"], int(config["fast_ma"]))
        slow_ma = sma(frame["close"], int(config["slow_ma"]))
        trend_ma = sma(frame["close"], int(config["trend_ma"]))
        indicator = rsi(frame["close"], int(config["rsi_window"]))
        trend_strength = (frame["close"] / trend_ma.replace(0, pd.NA)) - 1.0
        trend_up = (fast_ma > slow_ma) & (slow_ma > trend_ma) & (trend_strength >= float(config["trend_strength"]))
        pullback_now = (
            (frame["close"] <= fast_ma * (1.0 - float(config["pullback_pct"])))
            | (indicator <= float(config["pullback_rsi"]))
        )
        pullback_recent = (
            pullback_now.astype(float)
            .rolling(int(config["pullback_lookback"]), min_periods=1)
            .max()
            .astype(bool)
        )
        risk_off, regime_diagnostics = _btc_downtrend_low_volatility_filter(frame, config)
        entry_ready = (trend_up & pullback_recent & (frame["close"] > fast_ma) & ~risk_off).fillna(False)
        exit_ready = (
            (frame["close"] < slow_ma * (1.0 - float(config["exit_buffer"])))
            | (fast_ma < slow_ma)
            | (frame["close"] < trend_ma)
            | risk_off
        ).fillna(False)
        signal = _confirmed_stateful_long_signal(
            frame.index,
            entry_ready=entry_ready,
            exit_ready=exit_ready,
            entry_confirm_bars=int(config["entry_confirm_bars"]),
            exit_confirm_bars=int(config["exit_confirm_bars"]),
            min_hold_bars=int(config["min_hold_bars"]),
            cooldown_bars=int(config["cooldown_bars"]),
            max_hold_bars=int(config.get("max_hold_bars", 0)),
        )
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "trend_ma": trend_ma,
                "rsi": indicator.fillna(50.0),
                "trend_strength": trend_strength.fillna(0.0),
                "pullback_recent": pullback_recent.astype(float),
                "entry_ready": entry_ready.astype(float),
                "exit_ready": exit_ready.astype(float),
                **regime_diagnostics,
            },
        )


class BtcVolBreakoutStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="btc_vol_breakout",
        display_name="BTC Volatility Breakout",
        description="BTC 波动扩张 + 通道突破策略，只做多并过滤过低/过高波动。",
        category="breakout",
        default_weight=0.10,
        default_params={
            **BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS,
            "breakout_window": 72,
            "vol_window": 48,
            "min_volatility": 0.0025,
            "max_volatility": 0.06,
            "volume_window": 48,
            "volume_mult": 1.05,
            "exit_ma": 72,
            "stop_pct": 0.06,
            "entry_confirm_bars": 1,
            "exit_confirm_bars": 3,
            "min_hold_bars": 36,
            "cooldown_bars": 18,
        },
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        breakout_level = frame["high"].shift(1).rolling(int(config["breakout_window"]), min_periods=int(config["breakout_window"])).max()
        returns = frame["close"].pct_change()
        volatility = returns.rolling(int(config["vol_window"]), min_periods=int(config["vol_window"])).std(ddof=0)
        volume_ma = frame["volume"].rolling(int(config["volume_window"]), min_periods=1).mean()
        exit_ma = sma(frame["close"], int(config["exit_ma"]))
        risk_off, regime_diagnostics = _btc_downtrend_low_volatility_filter(frame, config)
        entry_ready = (
            (frame["close"] > breakout_level)
            & volatility.between(float(config["min_volatility"]), float(config["max_volatility"]))
            & (frame["volume"] >= volume_ma * float(config["volume_mult"]))
            & ~risk_off
        ).fillna(False)
        exit_ready = (
            (frame["close"] < exit_ma)
            | (frame["close"] < breakout_level * (1.0 - float(config["stop_pct"])))
            | (volatility > float(config["max_volatility"]) * 1.35)
            | risk_off
        ).fillna(False)
        signal = _confirmed_stateful_long_signal(
            frame.index,
            entry_ready=entry_ready,
            exit_ready=exit_ready,
            entry_confirm_bars=int(config["entry_confirm_bars"]),
            exit_confirm_bars=int(config["exit_confirm_bars"]),
            min_hold_bars=int(config["min_hold_bars"]),
            cooldown_bars=int(config["cooldown_bars"]),
            max_hold_bars=int(config.get("max_hold_bars", 0)),
        )
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={
                "breakout_level": breakout_level.fillna(0.0),
                "volatility": volatility.fillna(0.0),
                "volume_ma": volume_ma,
                "exit_ma": exit_ma,
                "entry_ready": entry_ready.astype(float),
                "exit_ready": exit_ready.astype(float),
                **regime_diagnostics,
            },
        )


class BtcRegimeTrendStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="btc_regime_trend",
        display_name="BTC Regime Trend",
        description="BTC regime filter + 趋势动量策略，避开震荡和极端波动，只做多。",
        category="regime",
        default_weight=0.10,
        default_params={
            **BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS,
            "fast_ma": 72,
            "slow_ma": 240,
            "regime_ma": 720,
            "momentum_window": 168,
            "momentum_threshold": 0.04,
            "vol_window": 168,
            "max_volatility": 0.045,
            "min_trend_strength": 0.025,
            "exit_buffer": 0.03,
            "entry_confirm_bars": 3,
            "exit_confirm_bars": 6,
            "min_hold_bars": 120,
            "cooldown_bars": 48,
        },
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        fast_ma = sma(frame["close"], int(config["fast_ma"]))
        slow_ma = sma(frame["close"], int(config["slow_ma"]))
        regime_ma = sma(frame["close"], int(config["regime_ma"]))
        momentum = frame["close"].pct_change(int(config["momentum_window"]))
        volatility = frame["close"].pct_change().rolling(int(config["vol_window"]), min_periods=int(config["vol_window"])).std(ddof=0)
        trend_strength = (slow_ma / regime_ma.replace(0, pd.NA)) - 1.0
        regime_ok = (
            (fast_ma > slow_ma)
            & (slow_ma > regime_ma)
            & (trend_strength >= float(config["min_trend_strength"]))
            & (volatility <= float(config["max_volatility"]))
        )
        risk_off, regime_diagnostics = _btc_downtrend_low_volatility_filter(frame, config)
        entry_ready = (regime_ok & (momentum >= float(config["momentum_threshold"])) & ~risk_off).fillna(False)
        exit_ready = (
            (fast_ma < slow_ma)
            | (frame["close"] < slow_ma * (1.0 - float(config["exit_buffer"])))
            | (volatility > float(config["max_volatility"]) * 1.4)
            | (momentum < 0.0)
            | risk_off
        ).fillna(False)
        signal = _confirmed_stateful_long_signal(
            frame.index,
            entry_ready=entry_ready,
            exit_ready=exit_ready,
            entry_confirm_bars=int(config["entry_confirm_bars"]),
            exit_confirm_bars=int(config["exit_confirm_bars"]),
            min_hold_bars=int(config["min_hold_bars"]),
            cooldown_bars=int(config["cooldown_bars"]),
            max_hold_bars=int(config.get("max_hold_bars", 0)),
        )
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "regime_ma": regime_ma,
                "momentum": momentum.fillna(0.0),
                "volatility": volatility.fillna(0.0),
                "trend_strength": trend_strength.fillna(0.0),
                "regime_ok": regime_ok.fillna(False).astype(float),
                "entry_ready": entry_ready.astype(float),
                "exit_ready": exit_ready.astype(float),
                **regime_diagnostics,
            },
        )


class BtcLowTurnoverBreakoutStrategy(StrategyBase):
    descriptor = StrategyDescriptor(
        id="btc_low_turnover_breakout",
        display_name="BTC Low Turnover Breakout",
        description="BTC 长通道突破 + 慢速退出策略，减少反复进出，只做多。",
        category="breakout",
        default_weight=0.10,
        default_params={
            **BTC_DOWNTREND_LOW_VOL_FILTER_DEFAULTS,
            "entry_window": 240,
            "exit_window": 96,
            "trend_ma": 480,
            "vol_window": 168,
            "max_volatility": 0.055,
            "breakout_buffer": 0.005,
            "entry_confirm_bars": 2,
            "exit_confirm_bars": 4,
            "min_hold_bars": 168,
            "cooldown_bars": 72,
        },
    )

    def generate(self, frame: pd.DataFrame, params: dict[str, float] | None = None) -> StrategySignalPack:
        config = {**self.descriptor.default_params, **(params or {})}
        entry_level = frame["high"].shift(1).rolling(int(config["entry_window"]), min_periods=int(config["entry_window"])).max()
        exit_level = frame["low"].shift(1).rolling(int(config["exit_window"]), min_periods=int(config["exit_window"])).min()
        trend_ma = sma(frame["close"], int(config["trend_ma"]))
        volatility = frame["close"].pct_change().rolling(int(config["vol_window"]), min_periods=int(config["vol_window"])).std(ddof=0)
        risk_off, regime_diagnostics = _btc_downtrend_low_volatility_filter(frame, config)
        entry_ready = (
            (frame["close"] > entry_level * (1.0 + float(config["breakout_buffer"])))
            & (frame["close"] > trend_ma)
            & (volatility <= float(config["max_volatility"]))
            & ~risk_off
        ).fillna(False)
        exit_ready = ((frame["close"] < exit_level) | (frame["close"] < trend_ma) | (volatility > float(config["max_volatility"]) * 1.5) | risk_off).fillna(False)
        signal = _confirmed_stateful_long_signal(
            frame.index,
            entry_ready=entry_ready,
            exit_ready=exit_ready,
            entry_confirm_bars=int(config["entry_confirm_bars"]),
            exit_confirm_bars=int(config["exit_confirm_bars"]),
            min_hold_bars=int(config["min_hold_bars"]),
            cooldown_bars=int(config["cooldown_bars"]),
            max_hold_bars=int(config.get("max_hold_bars", 0)),
        )
        return StrategySignalPack(
            signal=signal.fillna(0.0),
            diagnostics={
                "entry_level": entry_level.fillna(0.0),
                "exit_level": exit_level.fillna(0.0),
                "trend_ma": trend_ma,
                "volatility": volatility.fillna(0.0),
                "entry_ready": entry_ready.astype(float),
                "exit_ready": exit_ready.astype(float),
                **regime_diagnostics,
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
            BtcTrendPullbackStrategy(),
            BtcVolBreakoutStrategy(),
            BtcRegimeTrendStrategy(),
            BtcLowTurnoverBreakoutStrategy(),
        ]
    }
)
