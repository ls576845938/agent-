"""CN event-driven research backtest contracts."""

from quant_cn.backtest.costs import CostScenario, validate_cost_ladder
from quant_cn.backtest.engine import BacktestScenarioResult, EventDrivenBacktest
from quant_cn.backtest.events import BacktestEvent
from quant_cn.backtest.evidence import BacktestEvidenceReport, ScenarioEvidence

__all__ = [
    "BacktestEvent",
    "BacktestEvidenceReport",
    "BacktestScenarioResult",
    "CostScenario",
    "EventDrivenBacktest",
    "ScenarioEvidence",
    "validate_cost_ladder",
]
