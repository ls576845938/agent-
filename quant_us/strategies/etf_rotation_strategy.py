"""ETF momentum rotation strategy.

Weekly rebalance. Computes 60-day return for each ETF in the universe.
Selects top 2 by momentum, assigns equal weight (capped at 45% each).
Maintains minimum 5% cash reserve.

This strategy only emits Signals — it never calls broker or reads account.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


# Default universe: 4 major US equity ETFs
DEFAULT_ETF_UNIVERSE = ["SPY", "QQQ", "IWM", "DIA"]


@dataclass
class EtfMomentumRotationStrategy(Strategy):
    """Weekly ETF momentum rotation.

    Every Monday (or configurable weekday), compute 60-day returns for all
    ETFs. Emit LONG for the top `top_n` ETFs and FLAT for the rest.

    Configurable:
      - lookback_days: momentum window (default 60)
      - top_n: number of ETFs to hold (default 2)
      - max_single_weight: cap per ETF (default 0.45)
      - rebalance_weekday: 0=Mon .. 6=Sun (default 0)
      - universe: list of ETF symbols
    """

    strategy_id: str = "etf_rotation"
    lookback_days: int = 60
    top_n: int = 2
    max_single_weight: float = 0.45
    rebalance_weekday: int = 0  # Monday
    universe: list[str] = field(default_factory=lambda: list(DEFAULT_ETF_UNIVERSE))

    _closes: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _last_rebalance_date: object = None  # date of last rebalance

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        bar = event.bar
        symbol = bar.symbol
        raw_closes = context.state.payload.get("closes", {})
        closes_by_symbol = {
            str(key): [float(value) for value in values]
            for key, values in raw_closes.items()
        }
        last_rebalance_date = str(
            context.state.payload.get("last_rebalance_date", "") or ""
        )
        signals: list[Signal] = []
        if symbol in self.universe:
            closes = closes_by_symbol.setdefault(symbol, [])
            closes.append(float(bar.close))
            closes_by_symbol[symbol] = closes[-(self.lookback_days + 1) :]
            bar_date = bar.timestamp_utc.date()
            enough_data = all(
                len(closes_by_symbol.get(sym, [])) > self.lookback_days
                for sym in self.universe
            )
            should_rebalance = (
                bar_date.weekday() == self.rebalance_weekday
                and last_rebalance_date != bar_date.isoformat()
                and enough_data
            )
            if should_rebalance:
                scores: dict[str, float] = {}
                for sym in self.universe:
                    history = closes_by_symbol[sym]
                    previous = history[-self.lookback_days - 1]
                    current = history[-1]
                    scores[sym] = (
                        current / previous - 1.0 if previous > 0 else -999.0
                    )
                ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
                selected = {sym for sym, _ in ranked[: self.top_n]}
                for sym in self.universe:
                    rank = ranked.index((sym, scores[sym])) + 1
                    if sym in selected:
                        signals.append(Signal(
                            timestamp_utc=bar.timestamp_utc,
                            strategy_id=self.strategy_id,
                            symbol=sym,
                            direction=SignalDirection.LONG,
                            strength=min(1.0 / self.top_n, self.max_single_weight),
                            horizon="7d",
                            reason=f"etf_momentum_top{self.top_n}",
                            metadata={
                                "momentum_60d": round(scores[sym], 4),
                                "rank": rank,
                                "rebalance_date": bar_date.isoformat(),
                            },
                        ))
                    else:
                        signals.append(Signal(
                            timestamp_utc=bar.timestamp_utc,
                            strategy_id=self.strategy_id,
                            symbol=sym,
                            direction=SignalDirection.FLAT,
                            strength=0.0,
                            horizon="7d",
                            reason="etf_rotation_not_selected",
                            metadata={
                                "momentum_60d": round(scores[sym], 4),
                                "rank": rank,
                            },
                        ))
                last_rebalance_date = bar_date.isoformat()
        return StrategyDecision(
            signals=tuple(signals),
            state_transition=context.state.transition(
                {
                    "closes": closes_by_symbol,
                    "last_rebalance_date": last_rebalance_date,
                },
                reason="etf_rotation_bar_applied",
            ),
        )

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        symbol = bar.symbol

        # Only track symbols in our universe
        if symbol not in self.universe:
            return []

        closes = self._closes[symbol]
        closes.append(float(bar.close))

        # Keep only the last lookback_days + 1 closes
        if len(closes) > self.lookback_days + 1:
            self._closes[symbol] = closes[-self.lookback_days - 1:]

        bar_date = bar.timestamp_utc.date()

        # Only rebalance on configured weekday
        if bar_date.weekday() != self.rebalance_weekday:
            return []

        # Only rebalance once per day
        if self._last_rebalance_date == bar_date:
            return []

        # Check all universe symbols have enough data
        for sym in self.universe:
            if len(self._closes.get(sym, [])) <= self.lookback_days:
                return []  # not all symbols have enough data yet

        self._last_rebalance_date = bar_date

        # Compute 60-day momentum for each ETF
        scores: dict[str, float] = {}
        for sym in self.universe:
            hist = self._closes[sym]
            prev = hist[-self.lookback_days - 1]
            curr = hist[-1]
            scores[sym] = (curr / prev - 1.0) if prev > 0 else -999.0

        # Rank by momentum, pick top N
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = {sym for sym, _ in ranked[:self.top_n]}

        signals: list[Signal] = []
        for sym in self.universe:
            if sym in selected:
                # Equal weight among selected, capped at max_single_weight
                weight = min(1.0 / self.top_n, self.max_single_weight)
                signals.append(Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=sym,
                    direction=SignalDirection.LONG,
                    strength=weight,
                    horizon="7d",
                    reason=f"etf_momentum_top{self.top_n}",
                    metadata={
                        "momentum_60d": round(scores[sym], 4),
                        "rank": ranked.index((sym, scores[sym])) + 1,
                        "rebalance_date": bar_date.isoformat(),
                    },
                ))
            else:
                signals.append(Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=sym,
                    direction=SignalDirection.FLAT,
                    strength=0.0,
                    horizon="7d",
                    reason="etf_rotation_not_selected",
                    metadata={
                        "momentum_60d": round(scores[sym], 4),
                        "rank": ranked.index((sym, scores[sym])) + 1,
                    },
                ))

        return signals
