from __future__ import annotations

from math import sqrt
from pathlib import Path
from typing import Any

import pandas as pd

from integrations.vectorbt_adapter.schemas import (
    VectorBTScreenConfig,
    VectorBTScreenReport,
    VectorBTScreenRow,
    write_json,
)


def screen_binary_signal_grid(
    close: pd.Series,
    signal_grid: dict[str, pd.Series],
    config: VectorBTScreenConfig,
    *,
    periods_per_year: float = 252.0,
    output_path: str | Path | None = None,
) -> VectorBTScreenReport:
    """Screen binary exposure candidates with next-bar execution semantics.

    This is an adapter entrypoint for vectorbt-style fast hypothesis screening.
    It intentionally does not produce ledger PnL, target positions, orders, or
    promotion decisions. Any surviving candidate must be replayed through the
    local event-driven ledger backtest.
    """

    blockers = _validate_screen_inputs(close, signal_grid)
    vectorbt_available = _vectorbt_available()
    if blockers:
        report = VectorBTScreenReport(
            schema_version="vectorbt_screen_report_v1",
            status="BLOCKED",
            run_id=config.run_id,
            strategy_family=config.strategy_family,
            timeframe=config.timeframe,
            data_source=config.data_source,
            vectorbt_available=vectorbt_available,
            promotion_status=config.promotion_status,
            must_replay_with_ledger=True,
            allow_paper=False,
            allow_live=False,
            decision_time_rule=config.decision_time_rule,
            execution_time_rule=config.execution_time_rule,
            cost_bps=config.cost_bps,
            candidate_count=0,
            blockers=blockers,
            diagnostics={"input_close_count": int(len(close)), "input_signal_count": len(signal_grid)},
        )
        if output_path is not None:
            write_json(output_path, report)
        return report

    returns = close.sort_index().astype("float64").pct_change().fillna(0.0)
    rows = [
        _score_candidate(
            candidate_id=candidate_id,
            signal=signal,
            returns=returns,
            close=close,
            cost_bps=config.cost_bps,
            periods_per_year=periods_per_year,
        )
        for candidate_id, signal in sorted(signal_grid.items())
    ]
    rows.sort(key=lambda row: (row.sharpe_ratio, row.total_return_pct), reverse=True)
    report = VectorBTScreenReport(
        schema_version="vectorbt_screen_report_v1",
        status="PASS",
        run_id=config.run_id,
        strategy_family=config.strategy_family,
        timeframe=config.timeframe,
        data_source=config.data_source,
        vectorbt_available=vectorbt_available,
        promotion_status=config.promotion_status,
        must_replay_with_ledger=True,
        allow_paper=False,
        allow_live=False,
        decision_time_rule=config.decision_time_rule,
        execution_time_rule=config.execution_time_rule,
        cost_bps=config.cost_bps,
        candidate_count=len(rows),
        ranking=rows,
        diagnostics={
            "metric_source": "vectorized_screen_only",
            "pnl_source": "not_ledger_replay",
            "next_required_step": "event_driven_ledger_backtest",
        },
    )
    if output_path is not None:
        write_json(output_path, report)
    return report


def _validate_screen_inputs(close: pd.Series, signal_grid: dict[str, pd.Series]) -> list[str]:
    blockers: list[str] = []
    if close.empty:
        blockers.append("missing_close_series")
    if not signal_grid:
        blockers.append("missing_signal_grid")
    if close.index.has_duplicates:
        blockers.append("duplicate_close_index")
    for candidate_id, signal in signal_grid.items():
        if signal.empty:
            blockers.append(f"empty_signal:{candidate_id}")
        if signal.index.has_duplicates:
            blockers.append(f"duplicate_signal_index:{candidate_id}")
    return blockers


def _score_candidate(
    *,
    candidate_id: str,
    signal: pd.Series,
    returns: pd.Series,
    close: pd.Series,
    cost_bps: float,
    periods_per_year: float,
) -> VectorBTScreenRow:
    raw_signal = signal.reindex(close.index).fillna(0.0).clip(lower=0.0, upper=1.0)
    exposure = raw_signal.shift(1).fillna(0.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (cost_bps / 10000.0)
    strategy_returns = exposure * returns - cost
    equity = (1.0 + strategy_returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    annual_return = float(equity.iloc[-1] ** (periods_per_year / max(1, len(equity))) - 1.0)
    annual_volatility = float(strategy_returns.std(ddof=0) * sqrt(periods_per_year))
    sharpe = float(strategy_returns.mean() / strategy_returns.std(ddof=0) * sqrt(periods_per_year)) if strategy_returns.std(ddof=0) > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    return VectorBTScreenRow(
        candidate_id=candidate_id,
        total_return_pct=round(total_return * 100.0, 4),
        annualized_return_pct=round(annual_return * 100.0, 4),
        annualized_volatility_pct=round(annual_volatility * 100.0, 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown_pct=round(float(drawdown.min()) * 100.0, 4),
        turnover_pct=round(float(turnover.sum()) * 100.0, 4),
        exposure_ratio_pct=round(float((exposure.abs() > 0).mean()) * 100.0, 4),
        observation_count=int(len(strategy_returns)),
        cost_paid_pct=round(float(cost.sum()) * 100.0, 4),
    )


def _vectorbt_available() -> bool:
    try:
        import vectorbt  # noqa: F401
    except Exception:
        return False
    return True
