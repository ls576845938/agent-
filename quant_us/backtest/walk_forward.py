from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quant_us.backtest.engine import BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar
from quant_us.strategies.base import Strategy
from quant_us.strategies.base import StrategyContext


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int = 252
    test_bars: int = 63
    step_bars: int = 63


@dataclass(frozen=True)
class WalkForwardResult:
    window: WalkForwardWindow
    result: BacktestResult


def build_walk_forward_windows(bars: list[Bar], config: WalkForwardConfig) -> list[WalkForwardWindow]:
    ordered = sorted(bars, key=lambda item: item.timestamp_utc)
    windows: list[WalkForwardWindow] = []
    start = 0
    while start + config.train_bars + config.test_bars <= len(ordered):
        train_slice = ordered[start : start + config.train_bars]
        test_slice = ordered[start + config.train_bars : start + config.train_bars + config.test_bars]
        windows.append(
            WalkForwardWindow(
                train_start=train_slice[0].timestamp_utc,
                train_end=train_slice[-1].timestamp_utc,
                test_start=test_slice[0].timestamp_utc,
                test_end=test_slice[-1].timestamp_utc,
            )
        )
        start += config.step_bars
    return windows


def run_walk_forward(
    bars: list[Bar],
    strategy_factory,
    config: WalkForwardConfig | None = None,
    backtest_config: BacktestConfig | None = None,
) -> list[WalkForwardResult]:
    wf_config = config or WalkForwardConfig()
    ordered = sorted(bars, key=lambda item: item.timestamp_utc)
    windows = build_walk_forward_windows(ordered, wf_config)
    results: list[WalkForwardResult] = []
    for window in windows:
        train_bars = [
            bar
            for bar in ordered
            if window.train_start <= bar.timestamp_utc <= window.train_end
        ]
        test_bars = [
            bar
            for bar in ordered
            if window.test_start <= bar.timestamp_utc <= window.test_end
        ]
        strategy = strategy_factory()
        if not isinstance(strategy, Strategy):
            raise TypeError("strategy_factory must return a Strategy")
        for bar in train_bars:
            strategy.on_bar(MarketEvent.from_bar(bar), StrategyContext(run_id="walk_forward_warmup"))
        engine = EventDrivenBacktestEngine([strategy], config=backtest_config)
        results.append(WalkForwardResult(window=window, result=engine.run(test_bars)))
    return results
