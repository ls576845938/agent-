"""Systematic multi-level cost stress scanner.

Runs a backtest under escalating cost scenarios:
  1x (baseline) → 2x → 5x → 10x

Reports survival rate and performance decay at each level.
Used by the promotion gate to reject strategies that only work
under unrealistically low cost assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from quant_us.backtest.engine import BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.core.types import Bar
from quant_us.strategies.base import Strategy


@dataclass
class CostStressLevel:
    label: str
    commission_multiplier: float
    slippage_multiplier: float
    commission_rate: float
    slippage_bps: float
    survives: bool = True
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    trade_count: int = 0
    return_decay_pct: float = 0.0
    sharpe_decay: float = 0.0


@dataclass
class CostStressReport:
    strategy_id: str
    symbol: str
    baseline: CostStressLevel
    levels: list[CostStressLevel] = field(default_factory=list)
    survival_rate_pct: float = 100.0
    worst_case_label: str = ""
    engine: str = "event_driven"

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "engine": self.engine,
            "survival_rate_pct": self.survival_rate_pct,
            "worst_case_label": self.worst_case_label,
            "baseline_return": self.baseline.total_return_pct,
            "levels": [
                {
                    "label": lv.label,
                    "commission_rate": lv.commission_rate,
                    "slippage_bps": lv.slippage_bps,
                    "survives": lv.survives,
                    "total_return_pct": lv.total_return_pct,
                    "sharpe_ratio": lv.sharpe_ratio,
                    "max_drawdown_pct": lv.max_drawdown_pct,
                    "return_decay_pct": lv.return_decay_pct,
                    "sharpe_decay": lv.sharpe_decay,
                }
                for lv in self.levels
            ],
        }


MULTIPLIERS = [
    (1.0, 1.0, "1x baseline"),
    (2.0, 2.0, "2x cost stress"),
    (5.0, 5.0, "5x cost stress"),
    (10.0, 10.0, "10x cost stress"),
]


def run_cost_stress(
    strategies: list[Strategy],
    bars: list[Bar],
    base_config: BacktestConfig,
    multipliers: list[tuple[float, float, str]] | None = None,
) -> CostStressReport:
    """Run cost stress analysis across multiple cost multiplier levels.

    Args:
        strategies: Strategy instances to test.
        bars: Market data bars.
        base_config: Base backtest configuration with 1x cost assumptions.
        multipliers: List of (commission_mult, slippage_mult, label) tuples.
    """
    mults = multipliers or MULTIPLIERS
    levels: list[CostStressLevel] = []
    baseline: CostStressLevel | None = None
    survived = 0

    for comm_mult, slip_mult, label in mults:
        config = BacktestConfig(
            initial_cash=base_config.initial_cash,
            commission_rate=base_config.commission_rate * comm_mult,
            slippage_bps=base_config.slippage_bps * slip_mult,
            run_id=base_config.run_id,
        )
        engine = EventDrivenBacktestEngine(strategies=strategies, config=config)
        result = engine.run(bars)

        level = CostStressLevel(
            label=label,
            commission_multiplier=comm_mult,
            slippage_multiplier=slip_mult,
            commission_rate=config.commission_rate,
            slippage_bps=config.slippage_bps,
            total_return_pct=float(result.summary.get("total_return_pct", 0.0)),
            sharpe_ratio=float(result.summary.get("sharpe_ratio", 0.0)),
            max_drawdown_pct=float(result.summary.get("max_drawdown_pct", 0.0)),
            trade_count=int(result.summary.get("trade_count", 0)),
        )

        if comm_mult == 1.0:
            baseline = level
            level.survives = True
        else:
            level.survives = level.total_return_pct > -50.0 and level.sharpe_ratio > -2.0

        if level.survives:
            survived += 1
        levels.append(level)

    if baseline is None:
        baseline = CostStressLevel(
            label="1x baseline",
            commission_multiplier=1.0,
            slippage_multiplier=1.0,
            commission_rate=base_config.commission_rate,
            slippage_bps=base_config.slippage_bps,
        )

    for lv in levels:
        if baseline.total_return_pct != 0:
            lv.return_decay_pct = round(
                (baseline.total_return_pct - lv.total_return_pct) / abs(baseline.total_return_pct) * 100.0, 2
            )
        lv.sharpe_decay = round(baseline.sharpe_ratio - lv.sharpe_ratio, 4)

    worst = levels[-1] if levels else baseline

    return CostStressReport(
        strategy_id=strategies[0].strategy_id if strategies else "unknown",
        symbol=bars[0].symbol if bars else "unknown",
        baseline=baseline,
        levels=levels,
        survival_rate_pct=round(survived / len(levels) * 100.0, 1) if levels else 100.0,
        worst_case_label=worst.label,
    )
