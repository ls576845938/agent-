"""Backtest evidence contracts without execution adapters."""

from quant_shared.backtest.contracts import (
    BacktestEngine,
    BacktestEvidence,
    BacktestIdentity,
    BacktestRunInput,
    BacktestRunResult,
    validate_backtest_evidence,
)

__all__ = [
    "BacktestEngine",
    "BacktestEvidence",
    "BacktestIdentity",
    "BacktestRunInput",
    "BacktestRunResult",
    "validate_backtest_evidence",
]
