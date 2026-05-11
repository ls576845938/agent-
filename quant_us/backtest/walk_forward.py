from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
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
    symbols: list[str] = field(default_factory=list)
    strategy_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data_version: str = ""


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
    oos_avg_turnover_pct: float = 0.0
    fold_pass_rate_pct: float = 0.0
    symbol_coverage_pct: float = 0.0
    symbols_tested: list[str] = field(default_factory=list)
    insufficient_data: bool = False

    @property
    def all_trustworthy(self) -> bool:
        return self.windows_consistent == self.total_windows and self.total_windows > 0

    @property
    def consistency_pct(self) -> float:
        return (self.windows_consistent / self.total_windows * 100.0) if self.total_windows > 0 else 0.0


def build_walk_forward_windows(bars: list[Bar], config: WalkForwardConfig) -> list[WalkForwardWindow]:
    """Build walk-forward windows on unique timestamps.

    Multi-symbol datasets often contain several bars for the same market
    timestamp. Splitting on raw bar counts can place identical timestamps on
    both sides of a train/test boundary, which leaks information across folds.
    Windows therefore advance on the ordered set of unique timestamps and the
    returned boundaries are always timestamp-disjoint within a fold.
    """
    ordered = sorted(bars, key=lambda item: item.timestamp_utc)
    ordered_timestamps = sorted({bar.timestamp_utc for bar in ordered})
    windows: list[WalkForwardWindow] = []
    start = 0
    while start + config.train_bars + config.test_bars <= len(ordered_timestamps):
        train_slice = ordered_timestamps[start : start + config.train_bars]
        test_slice = ordered_timestamps[start + config.train_bars : start + config.train_bars + config.test_bars]
        windows.append(
            WalkForwardWindow(
                train_start=train_slice[0],
                train_end=train_slice[-1],
                test_start=test_slice[0],
                test_end=test_slice[-1],
            )
        )
        start += config.step_bars
    return windows


def _select_window_bars(ordered: list[Bar], window: WalkForwardWindow) -> tuple[list[Bar], list[Bar]]:
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
    return train_bars, test_bars


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
        train_bars, test_bars = _select_window_bars(ordered, window)
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
        train_bars, test_bars = _select_window_bars(ordered, window)

        strategy = strategy_factory()
        if not isinstance(strategy, Strategy):
            raise TypeError("strategy_factory must return a Strategy")

        for bar in train_bars:
            strategy.on_bar(MarketEvent.from_bar(bar), StrategyContext(run_id="wf_warmup"))

        runner_config = replace(
            uc,
            run_id=f"{uc.run_id}_w{len(results)}",
            save_replay_path=None,
        )
        runner = UnifiedBacktestRunner(config=runner_config)
        unified = runner.run(strategies=[strategy], frame=None, bars_override=test_bars)

        results.append(UnifiedWalkForwardResult(window=window, unified=unified))

    return results


def aggregate_walk_forward(
    results: list[UnifiedWalkForwardResult],
    symbols: list[str] | None = None,
    insufficient_data: bool = False,
) -> WalkForwardAggregate:
    """Aggregate out-of-sample metrics across walk-forward windows.

    Computes OOS total return (sum of window returns), average Sharpe,
    average max drawdown, average turnover, win rate, fold pass rate,
    and symbol coverage.

    Parameters
    ----------
    results : list[UnifiedWalkForwardResult]
    symbols : list[str] | None
        Symbols tested; used to compute symbol coverage.
    insufficient_data : bool
        True if any symbol had too few bars for a valid fold.
    """
    if not results:
        return WalkForwardAggregate(insufficient_data=insufficient_data)

    total_return_sum = 0.0
    sharpe_sum = 0.0
    max_dd_sum = 0.0
    turnover_sum = 0.0
    positive_windows = 0
    consistent = 0
    surviving_windows = 0

    for r in results:
        s = r.unified.summary
        total_return_sum += float(s.get("total_return_pct", 0.0))
        sharpe_sum += float(s.get("sharpe_ratio", 0.0))
        max_dd_sum += float(s.get("max_drawdown_pct", 0.0))
        turnover_sum += float(s.get("turnover_pct", 0.0))
        if float(s.get("total_return_pct", 0.0)) > 0:
            positive_windows += 1
        if r.unified.equity_consistent:
            consistent += 1
        # A fold "survives" if return >= 0, Sharpe >= 0, MDD < 18%
        if (
            float(s.get("total_return_pct", 0.0)) >= 0
            and float(s.get("sharpe_ratio", 0.0)) >= 0
            and float(s.get("max_drawdown_pct", 0.0)) > -18
        ):
            surviving_windows += 1

    n = len(results)
    sym_count = len(symbols) if symbols else 1
    return WalkForwardAggregate(
        windows=results,
        total_windows=n,
        windows_consistent=consistent,
        oos_total_return_pct=round(total_return_sum, 4),
        oos_avg_sharpe=round(sharpe_sum / n, 4) if n else 0.0,
        oos_avg_max_dd=round(max_dd_sum / n, 4) if n else 0.0,
        oos_win_rate=round(positive_windows / n * 100.0, 2) if n else 0.0,
        oos_avg_turnover_pct=round(turnover_sum / n, 4) if n else 0.0,
        fold_pass_rate_pct=round(surviving_windows / n * 100.0, 2) if n else 0.0,
        symbol_coverage_pct=round(sym_count / max(1, sym_count) * 100.0, 2),
        symbols_tested=list(symbols) if symbols else [],
        insufficient_data=insufficient_data,
    )


def save_walk_forward_manifest(
    aggregate: WalkForwardAggregate,
    manifest_dir: str | Path,
    strategy_id: str = "",
    params: dict[str, Any] | None = None,
    data_version: str = "",
) -> Path:
    """Persist walk-forward results as a JSON manifest for traceability.

    Each fold is recorded with its window, symbol, strategy, params,
    and result metrics.  The aggregate portfolio-level summary is also
    included.
    """
    import os
    from datetime import timezone

    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    folds: list[dict[str, Any]] = []
    for i, r in enumerate(aggregate.windows):
        w = r.window
        s = r.unified.summary
        folds.append({
            "fold": i,
            "train_start": w.train_start.isoformat(),
            "train_end": w.train_end.isoformat(),
            "test_start": w.test_start.isoformat(),
            "test_end": w.test_end.isoformat(),
            "strategy_id": strategy_id,
            "params": params or {},
            "data_version": data_version,
            "result": {
                "total_return_pct": float(s.get("total_return_pct", 0.0)),
                "sharpe_ratio": float(s.get("sharpe_ratio", 0.0)),
                "max_drawdown_pct": float(s.get("max_drawdown_pct", 0.0)),
                "turnover_pct": float(s.get("turnover_pct", 0.0)),
                "trade_count": int(s.get("trade_count", 0)),
            },
            "equity_consistent": r.unified.equity_consistent,
            "pass": (
                float(s.get("total_return_pct", 0.0)) >= 0
                and float(s.get("sharpe_ratio", 0.0)) >= 0
                and float(s.get("max_drawdown_pct", 0.0)) > -18
            ),
        })

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "strategy_id": strategy_id,
        "params": params or {},
        "data_version": data_version,
        "symbols_tested": aggregate.symbols_tested,
        "insufficient_data": aggregate.insufficient_data,
        "aggregate": {
            "total_windows": aggregate.total_windows,
            "windows_consistent": aggregate.windows_consistent,
            "oos_total_return_pct": aggregate.oos_total_return_pct,
            "oos_avg_sharpe": aggregate.oos_avg_sharpe,
            "oos_avg_max_dd": aggregate.oos_avg_max_dd,
            "oos_avg_turnover_pct": aggregate.oos_avg_turnover_pct,
            "oos_win_rate": aggregate.oos_win_rate,
            "fold_pass_rate_pct": aggregate.fold_pass_rate_pct,
            "symbol_coverage_pct": aggregate.symbol_coverage_pct,
        },
        "folds": folds,
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = manifest_dir / f"walk_forward_{strategy_id or 'unknown'}_{ts}.json"
    path.write_text(json.dumps(manifest, indent=2, default=str))
    return path
