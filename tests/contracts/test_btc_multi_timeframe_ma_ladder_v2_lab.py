from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import multi_timeframe_ma_ladder_v2_lab as lab


def test_v2_specs_are_strong_trend_campaign_specs() -> None:
    specs = lab.ma_ladder_v2_specs()
    assert specs
    assert any(spec.optimization_stage == "original" for spec in specs)
    assert max(float(spec.params["leverage"]) for spec in specs) <= 3.0
    assert all(float(spec.params["take_profit_pct"]) > 0.0 for spec in specs)
    assert all(float(spec.params["stop_loss_pct"]) > 0.0 for spec in specs)
    assert any("single_campaign_hold" in spec.optimization_components for spec in specs)
    assert {"short_ma_pullback", "balanced_ma_pullback"}.issubset({str(spec.params["level_set"]) for spec in specs})


def test_best_neighbor_profile_is_narrow_and_includes_2x_3x() -> None:
    specs = lab.ma_ladder_v2_specs(run_profile="best_neighbor")
    assert len(specs) == 48
    assert {float(spec.params["leverage"]) for spec in specs} == {1.0, 2.0, 3.0}
    assert {float(spec.params["take_profit_pct"]) for spec in specs} == {0.06, 0.08}
    assert {int(spec.params["trend_fail_bars"]) for spec in specs} == {8, 12}
    assert {int(spec.params["entry_cooldown_bars"]) for spec in specs} == {16, 32}
    assert {float(spec.params["max_pullback_pct"]) for spec in specs} == {0.025, 0.035}
    assert {spec.params["level_set"] for spec in specs} == {"short_ma_pullback"}
    assert {spec.optimization_stage for spec in specs} == {"best_neighbor_narrow_grid"}


def test_build_v2_lab_outputs_research_only_artifacts(tmp_path: Path, monkeypatch) -> None:
    frames = _frames()
    derivatives = tmp_path / "derivatives.json"
    _write_derivatives(derivatives, frames["15m"].index)
    monkeypatch.setattr(lab, "_load_fast_timeframes", lambda _path: frames)
    monkeypatch.setattr(lab, "ma_ladder_v2_specs", lambda run_profile="smoke": _small_specs())

    report = lab.build_btc_multi_timeframe_ma_ladder_v2_lab(
        market_db_path=tmp_path / "unused.sqlite",
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_multi_timeframe_ma_ladder_v2_lab_v1"
    assert report["decision"] == "btc_multi_timeframe_ma_ladder_v2_lab_research_only_no_paper_no_live"
    assert report["research_design"]["run_profile"] == "smoke"
    assert "fixed take profit" in report["research_design"]["exit_rule"]
    assert "filled exposure is effective after fill bar close via exposure.shift(1)" in report["research_design"]["no_lookahead_policy"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["comparison_rows"]

    for row in report["comparison_rows"]:
        assert row["research_only"] is True
        assert row["paper_queue_write_allowed"] is False
        assert row["paper_candidate_created"] is False
        assert row["live_unlock_allowed"] is False
        assert float(row["leverage"]) <= 3.0
        assert float(row["take_profit_pct"]) > 0.0

    for name in [
        "btc_multi_timeframe_ma_ladder_v2_lab_report.json",
        "btc_multi_timeframe_ma_ladder_v2_lab_grid.csv",
        "btc_multi_timeframe_ma_ladder_v2_lab_events.csv",
        "btc_multi_timeframe_ma_ladder_v2_lab_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def test_campaign_entry_uses_next_bar_fill_and_shifted_pnl() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="15min", tz="UTC")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=index)
    high = pd.Series([100.2, 101.2, 102.2, 103.2, 104.2], index=index)
    low = pd.Series([99.8, 98.9, 101.0, 102.0, 103.0], index=index)
    direction = pd.Series([1.0, 1.0, 1.0, 1.0, 0.0], index=index)
    levels = pd.DataFrame({"level_0_15m_ema20_w1": [99.0, 150.0, 150.0, 150.0, 150.0]}, index=index)
    spec = _small_specs()[0]

    exposure, entry_fill, _events = lab._simulate_campaign_exposure(
        spec,
        close=close,
        high=high,
        low=low,
        direction=direction,
        levels=levels,
        collect_events=True,
    )

    assert entry_fill.iloc[1] == 1.0
    assert exposure.iloc[1] > 0.0
    assert exposure.shift(1).fillna(0.0).iloc[1] == 0.0
    assert exposure.shift(1).fillna(0.0).iloc[2] > 0.0


def test_campaign_exits_after_trend_failure_bars() -> None:
    index = pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC")
    close = pd.Series([100.0, 101.0, 101.2, 101.1, 101.0, 100.9, 100.8, 100.7], index=index)
    high = close + 0.2
    low = pd.Series([99.8, 98.9, 100.9, 100.8, 100.7, 100.6, 100.5, 100.4], index=index)
    direction = pd.Series([1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], index=index)
    levels = pd.DataFrame({"level_0_15m_ema20_w1": [99.0, 150.0, 150.0, 150.0, 150.0, 150.0, 150.0, 150.0]}, index=index)
    spec = _small_specs()[0]

    exposure, _entry_fill, events = lab._simulate_campaign_exposure(
        spec,
        close=close,
        high=high,
        low=low,
        direction=direction,
        levels=levels,
        collect_events=True,
    )

    assert exposure.iloc[1] > 0.0
    assert exposure.iloc[4] == 0.0
    assert any(event["event_type"] == "campaign_exit" and "trend_failure" in event["note"] for event in events)


def test_short_campaign_entry_is_symmetric() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC")
    close = pd.Series([100.0, 99.0, 98.0, 97.0], index=index)
    high = pd.Series([100.2, 101.2, 98.2, 97.2], index=index)
    low = pd.Series([99.8, 98.8, 97.8, 96.8], index=index)
    direction = pd.Series([-1.0, -1.0, -1.0, 0.0], index=index)
    levels = pd.DataFrame({"level_0_15m_ema20_w1": [101.0, 50.0, 50.0, 50.0]}, index=index)
    spec = _small_specs()[0]

    exposure, entry_fill, _events = lab._simulate_campaign_exposure(
        spec,
        close=close,
        high=high,
        low=low,
        direction=direction,
        levels=levels,
        collect_events=False,
    )

    assert entry_fill.iloc[1] == 1.0
    assert exposure.iloc[1] < 0.0


def _small_specs() -> list[lab.MaLadderV2Spec]:
    return [
        lab.MaLadderV2Spec(
            variant_id="contract_v2_a",
            label="contract v2 a",
            params={
                "daily_fast": 3,
                "daily_slow": 8,
                "hourly_fast": 3,
                "hourly_slow": 8,
                "four_hour_fast": 3,
                "four_hour_slow": 8,
                "weekly_fast": 2,
                "weekly_slow": 3,
                "monthly_fast": 2,
                "monthly_slow": 3,
                "trend_efficiency_window_1h": 8,
                "trend_efficiency_threshold": 0.01,
                "leverage": 2.0,
                "take_profit_pct": 0.10,
                "stop_loss_pct": 0.035,
                "trend_fail_bars": 2,
                "entry_cooldown_bars": 2,
                "max_pullback_pct": 0.05,
                "level_set": "short_ma_pullback",
            },
            optimization_stage="original",
            optimization_components=["strong_trend_filter", "ma_pullback_limit_entry", "single_campaign_hold"],
            notes=[],
        ),
        lab.MaLadderV2Spec(
            variant_id="contract_v2_b",
            label="contract v2 b",
            params={
                "daily_fast": 3,
                "daily_slow": 8,
                "hourly_fast": 3,
                "hourly_slow": 8,
                "four_hour_fast": 3,
                "four_hour_slow": 8,
                "weekly_fast": 2,
                "weekly_slow": 3,
                "monthly_fast": 2,
                "monthly_slow": 3,
                "trend_efficiency_window_1h": 8,
                "trend_efficiency_threshold": 0.01,
                "leverage": 3.0,
                "take_profit_pct": 0.14,
                "stop_loss_pct": 0.025,
                "trend_fail_bars": 2,
                "entry_cooldown_bars": 4,
                "max_pullback_pct": 0.05,
                "level_set": "balanced_ma_pullback",
            },
            optimization_stage="formal_narrow_v2_grid",
            optimization_components=["strong_trend_filter", "fixed_take_profit", "trend_failure_exit"],
            notes=[],
        ),
    ]


def _frames() -> dict[str, pd.DataFrame]:
    return {
        "15m": _ohlcv(pd.date_range("2026-01-01", periods=600, freq="15min", tz="UTC"), step=0.010),
        "30m": _ohlcv(pd.date_range("2026-01-01", periods=300, freq="30min", tz="UTC"), step=0.020),
        "1h": _ohlcv(pd.date_range("2026-01-01", periods=160, freq="1h", tz="UTC"), step=0.050),
        "4h": _ohlcv(pd.date_range("2026-01-01", periods=50, freq="4h", tz="UTC"), step=0.180),
        "1d": _ohlcv(pd.date_range("2026-01-01", periods=20, freq="1D", tz="UTC"), step=0.700),
        "1w": _ohlcv(pd.date_range("2025-12-01", periods=10, freq="7D", tz="UTC"), step=2.500),
        "1mo": _ohlcv(pd.date_range("2025-01-01", periods=12, freq="30D", tz="UTC"), step=5.000),
    }


def _ohlcv(open_index: pd.DatetimeIndex, *, step: float) -> pd.DataFrame:
    values = pd.Series([100.0 + i * step for i in range(len(open_index))], index=open_index).to_numpy()
    delta = open_index[1] - open_index[0] if len(open_index) > 1 else pd.Timedelta(minutes=15)
    return pd.DataFrame(
        {
            "open_time": open_index,
            "open": values * 0.999,
            "high": values * 1.004,
            "low": values * 0.99,
            "close": values,
            "volume": 100.0,
        },
        index=open_index + delta - timedelta(milliseconds=1),
    )


def _write_derivatives(path: Path, index: pd.DatetimeIndex) -> None:
    rows = []
    for ts in index:
        rows.append(
            {
                "event_time": ts.isoformat(),
                "available_time": ts.isoformat(),
                "open_interest_usd": 1_000_000.0,
                "funding_rate": 0.0,
                "long_short_ratio": 1.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
