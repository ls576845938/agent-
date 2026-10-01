from __future__ import annotations

import numpy as np
import pandas as pd

from quant_us.research.us_etf_26_complete_return_multitimeframe import (
    REQUESTED_TIMEFRAMES,
    _simulate_danger_reference,
    summarize_matrix,
)
from scripts.build_us_etf_26_complete_return_multitimeframe_report import (
    _markdown,
    _research_sample_contract,
)


def test_requested_timeframes_match_user_contract() -> None:
    assert REQUESTED_TIMEFRAMES == (
        "1min",
        "5min",
        "15min",
        "30min",
        "1H",
        "4H",
        "1D",
    )


def test_three_x_danger_reference_fails_closed_on_margin_event() -> None:
    index = pd.date_range("2024-01-02 14:30:00", periods=4, freq="1h", tz="UTC")
    market = pd.DataFrame(
        {
            "effective_signal": [1.0, 1.0, 1.0, 1.0],
            "tqqq_open_to_next_open_return": [0.01, -0.02, 0.01, 0.01],
            "tqqq_adverse_open_low_or_gap_return": [-0.01, -0.20, -0.01, -0.01],
        },
        index=index,
    )

    result = _simulate_danger_reference(
        market,
        multiplier=3.0,
        cost_bps=10.0,
        periods_per_year=252 * 7,
    )

    assert result.metrics["portfolio_zero"] is True
    assert result.metrics["margin_call_count"] == 1
    assert result.metrics["final_equity"] == 0.0


def test_matrix_summary_excludes_zero_portfolios_from_best_result() -> None:
    rows = [
        {
            "symbol": "QQQ",
            "timeframe": "1H",
            "three_x_portfolio_zero": True,
            "three_x_margin_call_count": 1,
            "three_x_total_return_pct": -100.0,
            "three_x_annual_return_pct": -100.0,
            "three_x_sharpe": -1.0,
            "three_x_max_drawdown_abs_pct": 100.0,
        },
        {
            "symbol": "GLD",
            "timeframe": "1D",
            "three_x_portfolio_zero": False,
            "three_x_margin_call_count": 0,
            "three_x_total_return_pct": 500.0,
            "three_x_annual_return_pct": 25.0,
            "three_x_sharpe": 0.8,
            "three_x_max_drawdown_abs_pct": 45.0,
        },
    ]

    summary = summarize_matrix(rows)

    assert summary["combination_count"] == 2
    assert summary["portfolio_zero_count"] == 1
    assert summary["best_surviving_by_total_return"]["symbol"] == "GLD"
    assert np.isfinite(summary["best_surviving_by_sharpe"]["sharpe"])


def test_seen_selection_sample_is_not_labeled_clean_holdout() -> None:
    contract = _research_sample_contract()
    report = {
        "status": "complete_research_only",
        "data": {"data_version": "version"},
        "summary": {"combination_count": 182, "portfolio_zero_count": 0},
        "matrix_rows": [],
        "promotion_blockers": [
            "historical_2018_2026_sample_used_for_candidate_selection_not_clean_holdout"
        ],
    }

    markdown = _markdown(report)

    assert contract["sample_role"] == "exploratory_selection_sample"
    assert contract["selection_sample_reused"] is True
    assert contract["holdout_reused_for_selection"] is True
    assert contract["clean_holdout"] is False
    assert contract["new_independent_confirmation_window_required"] is True
    assert "不能解锁 paper/live" in markdown
    assert "not_clean_holdout" in markdown
