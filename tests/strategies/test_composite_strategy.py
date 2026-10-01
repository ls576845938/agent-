from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, Signal
from quant_us.strategies.base import Strategy, StrategyContext
from quant_us.strategies.composite import CompositeStrategy, StrategySpec
from quant_us.strategies.factory import build_composite_strategy, build_strategy


@dataclass
class FixedSignalStrategy(Strategy):
    strategy_id: str
    symbol: str

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=self.symbol,
                direction=SignalDirection.LONG,
                strength=0.5,
                horizon="1d",
            )
        ]


def _context() -> StrategyContext:
    return StrategyContext(
        run_id="multi_strategy_test",
        account=AccountState(
            timestamp_utc=datetime(2026, 5, 10, tzinfo=timezone.utc),
            account_id="paper",
            cash=50_000.0,
            equity=50_000.0,
            buying_power=50_000.0,
        ),
        market_prices={"SPY": 500.0, "QQQ": 450.0},
        universe=["SPY", "QQQ"],
    )


def _event() -> MarketEvent:
    bar = Bar(
        timestamp_utc=datetime(2026, 5, 10, 14, 30, tzinfo=timezone.utc),
        symbol="SPY",
        open=500.0,
        high=501.0,
        low=499.0,
        close=500.0,
        volume=100_000.0,
    )
    return MarketEvent.from_bar(bar)


def _event_for_timeframe(bar_size: str) -> MarketEvent:
    bar = Bar(
        timestamp_utc=datetime(2026, 5, 10, 14, 30, tzinfo=timezone.utc),
        symbol="SPY",
        open=500.0,
        high=501.0,
        low=499.0,
        close=500.0,
        volume=100_000.0,
        bar_size=bar_size,
    )
    return MarketEvent.from_bar(bar)


def test_composite_strategy_preserves_child_strategy_ids() -> None:
    composite = CompositeStrategy(
        strategies=[
            FixedSignalStrategy(strategy_id="trend_momentum", symbol="SPY"),
            FixedSignalStrategy(strategy_id="reversion_rsi", symbol="QQQ"),
        ],
        specs=[
            StrategySpec("trend_momentum", weight=0.6, timeframe="1d"),
            StrategySpec("reversion_rsi", weight=0.4, timeframe="15m"),
        ],
    )

    signals = list(composite.on_bar(_event(), _context()))

    assert [signal.strategy_id for signal in signals] == ["trend_momentum", "reversion_rsi"]
    assert [signal.symbol for signal in signals] == ["SPY", "QQQ"]
    assert composite.strategy_weights == {"trend_momentum": 0.6, "reversion_rsi": 0.4}
    assert composite.timeframes == {"trend_momentum": "1d", "reversion_rsi": "15m"}


def test_composite_strategy_routes_by_bar_size() -> None:
    composite = CompositeStrategy(
        strategies=[
            FixedSignalStrategy(strategy_id="trend_momentum", symbol="SPY"),
            FixedSignalStrategy(strategy_id="reversion_rsi", symbol="SPY"),
        ],
        specs=[
            StrategySpec("reversion_rsi", weight=0.4, timeframe="15m"),
            StrategySpec("trend_momentum", weight=0.6, timeframe="1m"),
        ],
    )

    signals = list(composite.on_bar(_event_for_timeframe("1m"), _context()))

    assert [signal.strategy_id for signal in signals] == ["trend_momentum"]
    assert signals[0].metadata["bar_size"] == "1m"
    assert signals[0].metadata["strategy_timeframe"] == "1m"


def test_build_composite_strategy_validates_child_strategy_parameters() -> None:
    composite = build_composite_strategy(
        [
            StrategySpec(
                strategy_id="trend_momentum",
                parameters={"lookback_bars": 3, "entry_threshold": 0.01},
                weight=0.5,
            ),
            StrategySpec(
                strategy_id="trend_macd",
                parameters={"fast_window": 3, "slow_window": 5},
                weight=0.5,
            ),
        ]
    )

    assert composite.strategy_id == "multi_strategy"
    assert [strategy.strategy_id for strategy in composite.strategies] == ["trend_momentum", "trend_macd"]


def test_portfolio_strategy_id_builds_default_multi_strategy() -> None:
    portfolio = build_strategy("portfolio", {})

    assert isinstance(portfolio, CompositeStrategy)
    assert [strategy.strategy_id for strategy in portfolio.strategies] == [
        "trend_momentum",
        "trend_macd",
        "short_reversion",
        "volatility_squeeze",
    ]
    assert portfolio.strategy_weights == {
        "trend_momentum": 0.35,
        "trend_macd": 0.25,
        "short_reversion": 0.20,
        "volatility_squeeze": 0.20,
    }
    assert portfolio.timeframes == {
        "trend_momentum": "1m",
        "trend_macd": "5m",
        "short_reversion": "1m",
        "volatility_squeeze": "15m",
    }
