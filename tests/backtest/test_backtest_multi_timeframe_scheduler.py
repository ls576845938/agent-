from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.backtest.replay import BacktestReplay
from quant_us.backtest.timeframe_scheduler import (
    FrozenTimeframeSnapshot,
    MultiTimeframeBarScheduler,
    MultiTimeframeSchedule,
)
from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar, Signal
from quant_us.strategies.base import Strategy, StrategyContext


UTC = timezone.utc


def _bar(ts: datetime, close: float, bar_size: str, *, open_: float | None = None) -> Bar:
    open_price = close if open_ is None else open_
    return Bar(
        timestamp_utc=ts,
        symbol="SPY",
        open=open_price,
        high=max(open_price, close) + 1.0,
        low=min(open_price, close) - 1.0,
        close=close,
        volume=100_000.0,
        source="test",
        bar_size=bar_size,
    )


@dataclass
class ExecutionBarStrategy(Strategy):
    strategy_id: str = "mtf_exec"
    version: str = "1.0.0"
    emitted: bool = False
    snapshots: list[FrozenTimeframeSnapshot] = field(default_factory=list)
    context_prices: list[float] = field(default_factory=list)
    snapshot_metadata: list[dict[str, Any]] = field(default_factory=list)

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        if event.bar.bar_size != "1m" or self.emitted:
            return []
        self.emitted = True
        snapshot = context.parameters["timeframe_snapshot"]
        self.snapshots.append(snapshot)
        self.context_prices.append(context.market_prices[event.bar.symbol])
        self.snapshot_metadata.append(context.parameters["timeframe_snapshot_metadata"])
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=1.0,
                horizon="next_bar",
                reason="mtf_bar_close_signal",
            )
        ]


@dataclass
class ConfirmRequiredStrategy(Strategy):
    strategy_id: str = "mtf_confirm_required"
    version: str = "1.0.0"
    emitted: bool = False
    confirm_seen_at: list[datetime | None] = field(default_factory=list)
    signal_timestamps: list[datetime] = field(default_factory=list)

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        if event.bar.bar_size != "1m" or self.emitted:
            return []

        snapshot = context.parameters["timeframe_snapshot"]
        confirm_bar = snapshot.bar("5m", event.bar.symbol)
        self.confirm_seen_at.append(None if confirm_bar is None else confirm_bar.timestamp_utc)
        if confirm_bar is None:
            return []

        self.emitted = True
        self.signal_timestamps.append(event.timestamp_utc)
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=1.0,
                horizon="next_bar",
                reason="mtf_confirm_available",
            )
        ]


def test_multi_timeframe_snapshot_freezes_only_asof_available_bars(tmp_path: Path) -> None:
    previous_daily = _bar(datetime(2026, 5, 8, 20, 0, tzinfo=UTC), 400.0, "1d")
    fifteen = _bar(datetime(2026, 5, 11, 14, 30, tzinfo=UTC), 103.0, "15m")
    five = _bar(datetime(2026, 5, 11, 14, 35, tzinfo=UTC), 105.0, "5m")
    one = _bar(datetime(2026, 5, 11, 14, 35, tzinfo=UTC), 106.0, "1m")
    next_one = _bar(datetime(2026, 5, 11, 14, 36, tzinfo=UTC), 108.0, "1m", open_=104.0)
    future_daily = _bar(datetime(2026, 5, 11, 20, 0, tzinfo=UTC), 450.0, "1d")
    strategy = ExecutionBarStrategy()
    schedule = MultiTimeframeSchedule.from_dsl(
        {
            "regime": "1d",
            "confirm": ["15m", "5m"],
            "execution": "1m",
        }
    )
    engine = EventDrivenBacktestEngine(
        strategies=[strategy],
        config=BacktestConfig(
            commission_rate=0.0,
            slippage_bps=0.0,
            timeframe_schedule=schedule,
        ),
    )

    bars = [previous_daily, fifteen, one, five, next_one, future_daily]
    result = engine.run(bars)

    assert len(strategy.snapshots) == 1
    snapshot = strategy.snapshots[0]
    assert snapshot.close("1d", "SPY") == 400.0
    assert snapshot.bar("1d", "SPY").timestamp_utc == previous_daily.timestamp_utc
    assert snapshot.close("15m", "SPY") == 103.0
    assert snapshot.close("5m", "SPY") == 105.0
    assert snapshot.close("1m", "SPY") == 106.0
    assert strategy.context_prices == [106.0]
    assert strategy.snapshot_metadata[0]["roles_by_bar_size"] == {
        "15m": ["confirm"],
        "1d": ["regime"],
        "1m": ["execution"],
        "5m": ["confirm"],
    }
    assert len(result.fills) == 1
    assert result.fills[0].filled_at == next_one.timestamp_utc
    assert result.fills[0].price == 104.0
    assert result.metadata["execution_semantics"] == "signal_at_bar_close_order_next_bar"
    assert result.metadata["timeframe_schedule"]["execution"] == "1m"
    replay_path = BacktestReplay.from_result(result, bars, engine.config).save(
        tmp_path / "replay.json"
    )
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    assert replay_payload["config"]["timeframe_schedule"]["availability_delay"] == 0.0


def test_timeframe_scheduler_respects_availability_delay() -> None:
    schedule = MultiTimeframeSchedule(
        execution="1m",
        confirm=("5m",),
        availability_delay=timedelta(seconds=30),
    )
    scheduler = MultiTimeframeBarScheduler(schedule)
    bar = _bar(datetime(2026, 5, 11, 14, 35, tzinfo=UTC), 105.0, "5m")
    probe = _bar(datetime(2026, 5, 11, 14, 35, tzinfo=UTC), 101.0, "1m")

    scheduler.update_available([bar], bar.timestamp_utc)
    assert scheduler.snapshot_for(probe, probe.timestamp_utc).bar("5m", "SPY") is None

    available_at = bar.timestamp_utc + timedelta(seconds=30)
    scheduler.update_available([bar], available_at)
    assert scheduler.snapshot_for(probe, available_at).close("5m", "SPY") == 105.0


def test_same_timestamp_confirm_bar_visibility_still_executes_next_bar() -> None:
    start = datetime(2026, 5, 11, 14, 35, tzinfo=UTC)
    five = _bar(start, 105.0, "5m")
    one = _bar(start, 106.0, "1m")
    next_one = _bar(start + timedelta(minutes=1), 108.0, "1m", open_=104.0)
    strategy = ConfirmRequiredStrategy()
    engine = EventDrivenBacktestEngine(
        strategies=[strategy],
        config=BacktestConfig(
            commission_rate=0.0,
            slippage_bps=0.0,
            timeframe_schedule=MultiTimeframeSchedule(
                execution="1m",
                confirm=("5m",),
            ),
        ),
    )

    result = engine.run([five, one, next_one])

    assert strategy.confirm_seen_at == [start]
    assert strategy.signal_timestamps == [start]
    assert len(result.orders) == 1
    assert result.orders[0].timestamp_utc == next_one.timestamp_utc
    assert result.orders[0].metadata["signal_timestamp_utc"] == start.isoformat()
    assert result.fills[0].filled_at == next_one.timestamp_utc
    assert result.fills[0].price == 104.0


def test_availability_delay_blocks_same_bar_confirm_until_later_execution_bar() -> None:
    start = datetime(2026, 5, 11, 14, 35, tzinfo=UTC)
    five = _bar(start, 105.0, "5m")
    one = _bar(start, 106.0, "1m")
    delayed_one = _bar(start + timedelta(minutes=1), 107.0, "1m")
    execution_one = _bar(start + timedelta(minutes=2), 108.0, "1m", open_=103.0)
    strategy = ConfirmRequiredStrategy()
    engine = EventDrivenBacktestEngine(
        strategies=[strategy],
        config=BacktestConfig(
            commission_rate=0.0,
            slippage_bps=0.0,
            timeframe_schedule=MultiTimeframeSchedule(
                execution="1m",
                confirm=("5m",),
                availability_delay=timedelta(seconds=30),
            ),
        ),
    )

    result = engine.run([five, one, delayed_one, execution_one])

    assert strategy.confirm_seen_at == [None, start]
    assert strategy.signal_timestamps == [delayed_one.timestamp_utc]
    assert len(result.orders) == 1
    assert result.orders[0].timestamp_utc == execution_one.timestamp_utc
    assert result.orders[0].metadata["signal_timestamp_utc"] == delayed_one.timestamp_utc.isoformat()
    assert result.fills[0].filled_at == execution_one.timestamp_utc
    assert result.fills[0].price == 103.0
