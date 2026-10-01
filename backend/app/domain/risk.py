from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class VolatilityScaler:
    target_annual_vol: float = 0.35
    min_scaler: float = 0.35
    max_scaler: float = 1.75

    def multiplier(self, returns: pd.Series, periods_per_year: float) -> float:
        sample = returns.dropna()
        if len(sample) < 2:
            return 1.0
        realized = float(sample.std(ddof=0)) * sqrt(periods_per_year)
        if realized <= 0:
            return 1.0
        return clamp(self.target_annual_vol / realized, self.min_scaler, self.max_scaler)


@dataclass
class DrawdownCircuitBreaker:
    max_drawdown_pct: float = 0.15
    cooldown_bars: int = 24
    leverage_decay: float = 0.5
    high_water_mark: float = 0.0
    cooldown_remaining: int = 0

    def update(self, equity: float) -> float:
        if equity > self.high_water_mark:
            self.high_water_mark = equity

        if self.high_water_mark <= 0:
            return 1.0

        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            return self.leverage_decay

        drawdown = (self.high_water_mark - equity) / self.high_water_mark
        if drawdown >= self.max_drawdown_pct:
            self.cooldown_remaining = self.cooldown_bars
            return self.leverage_decay
        return 1.0


@dataclass(frozen=True)
class KellySizer:
    lookback_bars: int = 96
    min_observations: int = 24
    kelly_fraction: float = 0.5
    min_multiplier: float = 0.25
    max_multiplier: float = 1.75

    def multiplier(self, returns: pd.Series) -> float:
        sample = returns.dropna().tail(self.lookback_bars)
        non_zero = sample[sample != 0]
        if len(non_zero) < self.min_observations:
            return 1.0

        wins = non_zero[non_zero > 0]
        losses = -non_zero[non_zero < 0]

        if losses.empty and not wins.empty:
            return self.max_multiplier
        if wins.empty:
            return self.min_multiplier

        win_rate = len(wins) / len(non_zero)
        avg_win = float(wins.mean())
        avg_loss = float(losses.mean())
        if avg_loss <= 0:
            return self.max_multiplier

        profit_loss_ratio = avg_win / avg_loss
        raw_kelly = win_rate - ((1.0 - win_rate) / profit_loss_ratio)
        adjusted = 1.0 + raw_kelly * 2.0 * self.kelly_fraction
        return clamp(adjusted, self.min_multiplier, self.max_multiplier)


@dataclass(frozen=True)
class OrthogonalizationEngine:
    correlation_threshold: float = 0.65
    min_history: int = 36

    def apply(
        self,
        weights: dict[str, float],
        returns_frame: pd.DataFrame,
    ) -> tuple[dict[str, float], float]:
        if returns_frame.empty or len(returns_frame) < self.min_history:
            return dict(weights), 1.0

        aligned = returns_frame.fillna(0.0)
        corr = aligned.corr().fillna(0.0).clip(-1.0, 1.0)
        adjusted = dict(weights)
        columns = list(corr.columns)

        for left_index, left_name in enumerate(columns):
            for right_name in columns[left_index + 1 :]:
                relationship = float(corr.loc[left_name, right_name])
                if relationship <= self.correlation_threshold:
                    continue
                penalty = clamp(
                    1.0 - (relationship - self.correlation_threshold) / (1.0 - self.correlation_threshold),
                    0.25,
                    1.0,
                )
                if adjusted.get(left_name, 0.0) >= adjusted.get(right_name, 0.0):
                    adjusted[right_name] = adjusted.get(right_name, 0.0) * penalty
                else:
                    adjusted[left_name] = adjusted.get(left_name, 0.0) * penalty

        eigenvalues = np.linalg.eigvalsh(corr.to_numpy(dtype=float))
        eigenvalues = np.clip(np.real(eigenvalues), 0.0, None)
        if float(eigenvalues.sum()) <= 0:
            return adjusted, 1.0

        proportions = eigenvalues / eigenvalues.sum()
        effective_rank = float(np.exp(-(proportions * np.log(np.clip(proportions, 1e-12, None))).sum()))
        diversity_ratio = effective_rank / max(1.0, float(len(columns)))
        diversity_scaler = clamp(0.6 + 0.8 * diversity_ratio, 0.6, 1.4)
        return adjusted, diversity_scaler
