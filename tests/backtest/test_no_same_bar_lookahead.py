from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar, Signal
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class FirstBarLongStrategy(Strategy):
    strategy_id: str = "first_bar_long"
    version: str = "1.0.0"
    emitted: bool = False

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        if self.emitted:
            return []
        self.emitted = True
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=1.0,
                horizon="next_bar",
                reason="test_next_bar_execution",
            )
        ]


def _bar(ts: datetime, *, open_: float, close: float) -> Bar:
    return Bar(
        timestamp_utc=ts,
        symbol="AAPL",
        open=open_,
        high=max(open_, close) + 1.0,
        low=min(open_, close) - 1.0,
        close=close,
        volume=100_000.0,
    )


def test_backtest_orders_execute_on_next_bar_open_not_signal_bar_close() -> None:
    start = datetime(2026, 5, 11, 14, 30, tzinfo=timezone.utc)
    bars = [
        _bar(start, open_=95.0, close=100.0),
        _bar(start + timedelta(minutes=1), open_=99.0, close=101.0),
    ]
    engine = EventDrivenBacktestEngine(
        strategies=[FirstBarLongStrategy()],
        config=BacktestConfig(commission_rate=0.0, slippage_bps=0.0),
    )

    result = engine.run(bars)

    assert len(result.fills) == 1
    assert result.fills[0].filled_at == bars[1].timestamp_utc
    assert result.fills[0].price == 99.0
    assert result.orders[0].timestamp_utc == bars[1].timestamp_utc
    assert result.orders[0].metadata["signal_timestamp_utc"] == bars[0].timestamp_utc.isoformat()
    assert "pending_intent_count" not in result.metadata


def test_backtest_does_not_fill_signal_when_no_next_bar_exists() -> None:
    start = datetime(2026, 5, 11, 14, 30, tzinfo=timezone.utc)
    engine = EventDrivenBacktestEngine(
        strategies=[FirstBarLongStrategy()],
        config=BacktestConfig(commission_rate=0.0, slippage_bps=0.0),
    )

    result = engine.run([_bar(start, open_=95.0, close=100.0)])

    assert result.orders == []
    assert result.fills == []
    assert result.metadata["pending_intent_count"] == 1


def test_streaming_market_events_keep_next_bar_execution_semantics() -> None:
    start = datetime(2026, 5, 11, 14, 30, tzinfo=timezone.utc)
    bars = [
        _bar(start, open_=95.0, close=100.0),
        _bar(start + timedelta(minutes=1), open_=99.0, close=101.0),
    ]
    batch_engine = EventDrivenBacktestEngine(
        strategies=[FirstBarLongStrategy()],
        config=BacktestConfig(commission_rate=0.0, slippage_bps=0.0),
    )
    stream_engine = EventDrivenBacktestEngine(
        strategies=[FirstBarLongStrategy()],
        config=BacktestConfig(commission_rate=0.0, slippage_bps=0.0),
    )

    batch_result = batch_engine.run(bars)
    stream_result = stream_engine.run_streaming(MarketEvent.from_bar(bar) for bar in bars)

    assert [fill.price for fill in stream_result.fills] == [fill.price for fill in batch_result.fills]
    assert [fill.filled_at for fill in stream_result.fills] == [
        fill.filled_at for fill in batch_result.fills
    ]
    assert stream_result.fills[0].price == 99.0
    assert stream_result.metadata["execution_semantics"] == "signal_at_bar_close_order_next_bar"
