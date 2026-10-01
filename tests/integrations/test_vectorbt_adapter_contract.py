from __future__ import annotations

from pathlib import Path

import pandas as pd

from integrations.vectorbt_adapter.schemas import VectorBTScreenConfig, VectorBTAdapterError
from integrations.vectorbt_adapter.screen_parameter_grid import screen_binary_signal_grid


def test_vectorbt_screen_is_research_only_and_requires_ledger_replay(tmp_path: Path) -> None:
    close = pd.Series([100.0, 110.0, 121.0, 108.9], index=pd.date_range("2026-01-01", periods=4, tz="UTC"))
    signals = {
        "always_on": pd.Series([1, 1, 1, 1], index=close.index),
        "late_on": pd.Series([0, 0, 1, 1], index=close.index),
    }
    output = tmp_path / "vectorbt_screen.json"

    report = screen_binary_signal_grid(
        close,
        signals,
        VectorBTScreenConfig(
            run_id="vbt_case",
            strategy_family="us_etf_parameter_screen",
            timeframe="1d",
            data_source="unit_test",
            cost_bps=10.0,
        ),
        output_path=output,
    )

    payload = report.to_dict()
    assert payload["status"] == "PASS"
    assert payload["promotion_status"] == "research_screen_only"
    assert payload["must_replay_with_ledger"] is True
    assert payload["allow_paper"] is False
    assert payload["allow_live"] is False
    assert payload["diagnostics"]["pnl_source"] == "not_ledger_replay"
    assert output.exists()


def test_vectorbt_screen_uses_next_bar_exposure_and_costs() -> None:
    close = pd.Series([100.0, 110.0, 121.0], index=pd.date_range("2026-01-01", periods=3, tz="UTC"))
    signals = {"candidate": pd.Series([1, 0, 0], index=close.index)}

    report = screen_binary_signal_grid(
        close,
        signals,
        VectorBTScreenConfig(
            run_id="vbt_shift_case",
            strategy_family="shift_check",
            timeframe="1d",
            data_source="unit_test",
            cost_bps=0.0,
        ),
    )

    row = report.ranking[0]
    assert row.total_return_pct == 10.0
    assert row.turnover_pct == 200.0
    assert row.exposure_ratio_pct == 33.3333


def test_vectorbt_screen_blocks_missing_inputs() -> None:
    report = screen_binary_signal_grid(
        pd.Series(dtype="float64"),
        {},
        VectorBTScreenConfig(
            run_id="vbt_blocked",
            strategy_family="blocked",
            timeframe="1d",
            data_source="unit_test",
        ),
    )

    assert report.status == "BLOCKED"
    assert "missing_close_series" in report.blockers
    assert "missing_signal_grid" in report.blockers
    assert report.allow_live is False


def test_vectorbt_config_refuses_paper_or_live_enablement() -> None:
    try:
        VectorBTScreenConfig(
            run_id="bad",
            strategy_family="bad",
            timeframe="1d",
            data_source="unit_test",
            allow_live=True,
        )
    except VectorBTAdapterError as exc:
        assert "cannot enable paper or live" in str(exc)
    else:
        raise AssertionError("expected VectorBTAdapterError")
