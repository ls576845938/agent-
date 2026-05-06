from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from quant_us.backtest.engine import BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.backtest.ledger_pnl import LedgerEquityCurve, verify_equity_consistency
from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestResult, UnifiedBacktestRunner
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar
from quant_us.strategies.base import Strategy, StrategyContext


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


@dataclass
class UnifiedWalkForwardResult:
    """Walk-forward result with ledger verification per window."""

    window: WalkForwardWindow
    unified: UnifiedBacktestResult

    @property
    def is_trustworthy(self) -> bool:
        return self.unified.is_trustworthy

    @property
    def oos_summary(self) -> dict[str, float | int]:
        return self.unified.summary


@dataclass
class WalkForwardAggregate:
    """Aggregate out-of-sample metrics across all walk-forward windows."""

    windows: list[UnifiedWalkForwardResult] = field(default_factory=list)
    total_windows: int = 0
    windows_consistent: int = 0
    oos_total_return_pct: float = 0.0
    oos_avg_sharpe: float = 0.0
    oos_avg_max_dd: float = 0.0
    oos_win_rate: float = 0.0

    @property
    def all_trustworthy(self) -> bool:
        return self.windows_consistent == self.total_windows and self.total_windows > 0

    @property
    def consistency_pct(self) -> float:
        return (self.windows_consistent / self.total_windows * 100.0) if self.total_windows > 0 else 0.0


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
    """Original walk-forward using raw engine. Kept for backward compatibility."""
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


def run_walk_forward_unified(
    bars: list[Bar],
    strategy_factory: Callable[[], Strategy],
    wf_config: WalkForwardConfig | None = None,
    unified_config: UnifiedBacktestConfig | None = None,
) -> list[UnifiedWalkForwardResult]:
    """Walk-forward using UnifiedBacktestRunner with ledger verification per window.

    Each window:
      1. Train: warm up a fresh strategy instance on train bars (no order lifecycle).
      2. Test: run test bars through UnifiedBacktestRunner (full order lifecycle + ledger verification).
      3. Verify ledger equity matches portfolio snapshots.

    Only windows where ledger is consistent are trustworthy.
    """
    wf_cfg = wf_config or WalkForwardConfig()
    ordered = sorted(bars, key=lambda item: item.timestamp_utc)
    windows = build_walk_forward_windows(ordered, wf_cfg)
    uc = unified_config or UnifiedBacktestConfig()

    results: list[UnifiedWalkForwardResult] = []

    for window in windows:
        train_bars = [
            bar for bar in ordered
            if window.train_start <= bar.timestamp_utc <= window.train_end
        ]
        test_bars = [
            bar for bar in ordered
            if window.test_start <= bar.timestamp_utc <= window.test_end
        ]

        strategy = strategy_factory()
        if not isinstance(strategy, Strategy):
            raise TypeError("strategy_factory must return a Strategy")

        for bar in train_bars:
            strategy.on_bar(MarketEvent.from_bar(bar), StrategyContext(run_id="wf_warmup"))

        runner_config = UnifiedBacktestConfig(
            initial_cash=uc.initial_cash,
            commission_rate=uc.commission_rate,
            slippage_bps=uc.slippage_bps,
            fill_ratio=uc.fill_ratio,
            volume_participation_cap_pct=uc.volume_participation_cap_pct,
            run_id=f"{uc.run_id}_w{len(results)}",
        )
        runner = UnifiedBacktestRunner(config=runner_config)
        unified = runner.run(strategies=[strategy], frame=None, bars_override=test_bars)

        results.append(UnifiedWalkForwardResult(window=window, unified=unified))

    return results


def aggregate_walk_forward(
    results: list[UnifiedWalkForwardResult],
) -> WalkForwardAggregate:
    """Aggregate out-of-sample metrics across walk-forward windows.

    Computes OOS total return (sum of window returns), average Sharpe,
    average max drawdown, and win rate (fraction of windows with positive return).
    """
    if not results:
        return WalkForwardAggregate()

    total_return_sum = 0.0
    sharpe_sum = 0.0
    max_dd_sum = 0.0
    positive_windows = 0
    consistent = 0

    for r in results:
        s = r.unified.summary
        total_return_sum += float(s.get("total_return_pct", 0.0))
        sharpe_sum += float(s.get("sharpe_ratio", 0.0))
        max_dd_sum += float(s.get("max_drawdown_pct", 0.0))
        if float(s.get("total_return_pct", 0.0)) > 0:
            positive_windows += 1
        if r.unified.equity_consistent:
            consistent += 1

    n = len(results)
    return WalkForwardAggregate(
        windows=results,
        total_windows=n,
        windows_consistent=consistent,
        oos_total_return_pct=round(total_return_sum, 4),
        oos_avg_sharpe=round(sharpe_sum / n, 4),
        oos_avg_max_dd=round(max_dd_sum / n, 4),
        oos_win_rate=round(positive_windows / n * 100.0, 2),
    )
