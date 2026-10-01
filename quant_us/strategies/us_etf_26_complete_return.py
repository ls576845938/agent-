"""Pure frozen strategy used by the ETF26 canonical research backtest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
from typing import Any, Mapping

import pandas as pd

from quant_us.core.enums import SignalDirection
from quant_us.core.types import Signal, TargetPosition


@dataclass(frozen=True)
class Forecast:
    timestamp_utc: datetime
    strategy_id: str
    symbol: str
    horizon: str
    value: float
    unit: str
    confidence: float
    signal_id: str
    reason: str
    forecast_id: str


@dataclass(frozen=True)
class FrozenStrategyDecision:
    signal: Signal
    forecast: Forecast
    target: TargetPosition


class FrozenEtf26CompleteReturnStrategy:
    """No-I/O implementation of the Goal 1 frozen daily signal.

    Input is an already validated sequence of completed daily bars.  The class
    has no repository, database, broker, clock, execution adapter, or ledger
    dependency and emits only Signal, Forecast and TargetPosition objects.
    """

    def __init__(
        self,
        *,
        candidate_id: str,
        strategy_version: str,
        symbol: str,
        exposure_multiplier: float,
        params: Mapping[str, Any],
    ) -> None:
        self.candidate_id = candidate_id
        self.strategy_version = strategy_version
        self.strategy_id = f"{candidate_id}:{strategy_version}"
        self.symbol = symbol.upper()
        self.exposure_multiplier = float(exposure_multiplier)
        self.params = dict(params)
        if self.exposure_multiplier <= 0:
            raise ValueError("frozen_exposure_multiplier_invalid")

    def generate(self, completed_daily_bars: pd.DataFrame) -> list[FrozenStrategyDecision]:
        required = {"decision_time_utc", "High", "Low", "Close"}
        missing = sorted(required - set(completed_daily_bars.columns))
        if missing:
            raise ValueError(f"frozen_strategy_input_missing:{','.join(missing)}")
        frame = completed_daily_bars.reset_index(drop=True).copy()
        close = frame["Close"].astype(float)
        high = frame["High"].astype(float)
        low = frame["Low"].astype(float)
        fast = close.ewm(span=int(self.params["ema_fast_days"]), adjust=False).mean().shift(1)
        slow = close.ewm(span=int(self.params["ema_slow_days"]), adjust=False).mean().shift(1)
        trend = (fast > slow) & (close > slow)
        prior_high = high.shift(1).rolling(
            int(self.params["entry_window"]),
            min_periods=int(self.params["entry_window"]),
        ).max()
        prior_low = low.shift(1).rolling(
            int(self.params["exit_window"]),
            min_periods=int(self.params["exit_window"]),
        ).min()
        atr = _atr(high, low, close, int(self.params["atr_window"]))

        state = 0.0
        cooldown = 0
        stop: float | None = None
        entry_pos: int | None = None
        entry_line: float | None = None
        decisions: list[FrozenStrategyDecision] = []
        for pos in range(len(frame)):
            price = float(close.iloc[pos])
            atr_value = float(atr.iloc[pos])
            if cooldown > 0:
                cooldown -= 1
            if state > 0 and math.isfinite(atr_value):
                candidate = price - float(self.params["atr_mult"]) * atr_value
                stop = max(stop if stop is not None else candidate, candidate)
            failed = (
                state > 0
                and entry_pos is not None
                and entry_line is not None
                and pos - entry_pos <= int(self.params["failure_exit_window"])
                and price < entry_line
            )
            atr_exit = state > 0 and stop is not None and price < stop
            exit_rule = not bool(trend.iloc[pos]) or (
                pd.notna(prior_low.iloc[pos]) and price < float(prior_low.iloc[pos])
            )
            entry_rule = (
                bool(trend.iloc[pos])
                and pd.notna(prior_high.iloc[pos])
                and price > float(prior_high.iloc[pos])
            )
            if state <= 0 and cooldown <= 0 and entry_rule:
                state = 1.0
                stop = price - float(self.params["atr_mult"]) * atr_value if math.isfinite(atr_value) else None
                entry_pos = pos
                entry_line = float(prior_high.iloc[pos])
                reason = "entry:qqq_fixed_donchian"
            elif state > 0 and (exit_rule or atr_exit or failed):
                state = 0.0
                cooldown = int(self.params["cooldown_bars"])
                stop = None
                entry_pos = None
                entry_line = None
                reason = "exit:fixed_rule"
            else:
                reason = "hold_long" if state > 0 else "hold_cash"
            decisions.append(self._decision(frame.iloc[pos], pos, state, reason))
        return decisions

    def _decision(
        self,
        row: pd.Series,
        position: int,
        state: float,
        reason: str,
    ) -> FrozenStrategyDecision:
        timestamp = pd.Timestamp(row["decision_time_utc"]).to_pydatetime()
        signal_id = _stable_id("sig", self.strategy_id, timestamp.isoformat(), position, state)
        forecast_id = _stable_id("fcst", signal_id, state)
        target_id = _stable_id("tgt", forecast_id, self.exposure_multiplier)
        direction = SignalDirection.LONG if state > 0 else SignalDirection.FLAT
        signal = Signal(
            timestamp_utc=timestamp,
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            direction=direction,
            strength=float(state),
            horizon="next_session_open_to_open",
            reason=reason,
            metadata={"strategy_version": self.strategy_version, "frozen": True},
            signal_id=signal_id,
        )
        forecast = Forecast(
            timestamp_utc=timestamp,
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            horizon="next_session_open_to_open",
            value=float(state),
            unit="binary_long_state_not_expected_return",
            confidence=1.0,
            signal_id=signal_id,
            reason=reason,
            forecast_id=forecast_id,
        )
        target = TargetPosition(
            timestamp_utc=timestamp,
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            target_weight=float(state) * self.exposure_multiplier,
            signal_id=signal_id,
            metadata={
                "forecast_id": forecast_id,
                "long_only": True,
                "frozen_exposure_multiplier": self.exposure_multiplier,
            },
            target_position_id=target_id,
        )
        return FrozenStrategyDecision(signal=signal, forecast=forecast, target=target)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - previous).abs(), (low - previous).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window, min_periods=window).mean()


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"
