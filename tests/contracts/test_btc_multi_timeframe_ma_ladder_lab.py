from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import multi_timeframe_ma_ladder_lab as lab


def test_ma_ladder_specs_are_predeclared_and_leverage_capped() -> None:
    specs = lab.ma_ladder_specs()
    assert specs
    assert any(spec.optimization_stage == "original" for spec in specs)
    assert {"fast_5_15_30", "mid_5_15_30"}.issubset({spec.params["level_set"] for spec in specs})
    assert max(float(spec.params["max_leverage"]) for spec in specs) <= 5.0
    assert any("ma_ladder_limit_pullback" in spec.optimization_components for spec in specs)


def test_build_ma_ladder_lab_outputs_research_only_artifacts(tmp_path: Path, monkeypatch) -> None:
    frames = _frames()
    derivatives = tmp_path / "derivatives.json"
    _write_derivatives(derivatives, frames["15m"].index)
    monkeypatch.setattr(lab, "load_market_interval", lambda path, interval: frames["1m"])
    monkeypatch.setattr(lab, "_build_timeframes", lambda source: frames)
    monkeypatch.setattr(lab, "ma_ladder_specs", _small_specs)

    report = lab.build_btc_multi_timeframe_ma_ladder_lab(
        market_db_path=tmp_path / "unused.sqlite",
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        max_specs=2,
    )

    assert report["schema_version"] == "btc_multi_timeframe_ma_ladder_lab_v1"
    assert report["decision"] == "btc_multi_timeframe_ma_ladder_lab_research_only_no_paper_no_live"
    assert report["research_design"]["candidate_count"] == 2
    assert "order fill is checked on the next completed 15m bar" in report["research_design"]["no_lookahead_policy"]
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
        assert float(row["max_leverage"]) <= 5.0

    for name in [
        "btc_multi_timeframe_ma_ladder_lab_report.json",
        "btc_multi_timeframe_ma_ladder_lab_grid.csv",
        "btc_multi_timeframe_ma_ladder_lab_events.csv",
        "btc_multi_timeframe_ma_ladder_lab_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def test_ladder_fill_uses_previous_completed_decision_bar() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="15min", tz="UTC")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=index)
    high = pd.Series([100.2, 101.2, 102.2, 103.2, 104.2], index=index)
    low = pd.Series([99.8, 98.9, 101.0, 102.0, 103.0], index=index)
    raw_side = pd.Series([1.0, 1.0, 1.0, 0.0, 0.0], index=index)
    weekly_size = pd.Series(1.0, index=index)
    levels = pd.DataFrame({"level_0_15m_ema20_w1": [99.0, 150.0, 150.0, 150.0, 150.0]}, index=index)
    spec = _small_specs()[0]

    exposure, fill_fraction, _events = lab._simulate_ladder_exposure(
        spec,
        close=close,
        high=high,
        low=low,
        raw_side=raw_side,
        weekly_size=weekly_size,
        levels=levels,
        collect_events=True,
    )

    assert fill_fraction.iloc[1] == 1.0
    assert exposure.iloc[1] > 0.0
    assert fill_fraction.iloc[2] == 0.0
    assert exposure.shift(1).fillna(0.0).iloc[1] == 0.0
    assert exposure.shift(1).fillna(0.0).iloc[2] > 0.0


def test_aggregate_ohlcv_minutes_uses_complete_buckets_and_expected_close_time() -> None:
    source = _ohlcv(pd.date_range("2026-01-01", periods=16, freq="1min", tz="UTC"), step=0.1)
    out = lab.aggregate_ohlcv_minutes(source, minutes=5)

    assert len(out) == 3
    assert out.index[0] == pd.Timestamp("2026-01-01T00:04:59.999000+00:00")
    assert out["open"].iloc[0] == source["open"].iloc[0]
    assert out["close"].iloc[0] == source["close"].iloc[4]
    assert out["high"].iloc[0] == source["high"].iloc[:5].max()
    assert out["low"].iloc[0] == source["low"].iloc[:5].min()
    assert out["volume"].iloc[0] == source["volume"].iloc[:5].sum()


def test_short_ladder_is_symmetric() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC")
    close = pd.Series([100.0, 99.0, 98.0, 97.0], index=index)
    high = pd.Series([100.2, 101.2, 98.2, 97.2], index=index)
    low = pd.Series([99.8, 98.8, 97.8, 96.8], index=index)
    raw_side = pd.Series([-1.0, -1.0, -1.0, 0.0], index=index)
    weekly_size = pd.Series(1.0, index=index)
    levels = pd.DataFrame({"level_0_15m_ema20_w1": [101.0, 50.0, 50.0, 50.0]}, index=index)
    spec = _small_specs()[0]

    exposure, fill_fraction, _events = lab._simulate_ladder_exposure(
        spec,
        close=close,
        high=high,
        low=low,
        raw_side=raw_side,
        weekly_size=weekly_size,
        levels=levels,
        collect_events=False,
    )

    assert fill_fraction.iloc[1] == 1.0
    assert exposure.iloc[1] < 0.0


def _small_specs() -> list[lab.MaLadderSpec]:
    return [
        lab.MaLadderSpec(
            variant_id="contract_fast",
            label="contract fast",
            params={
                "daily_fast": 3,
                "daily_slow": 8,
                "hourly_fast": 3,
                "hourly_slow": 8,
                "four_hour_fast": 3,
                "four_hour_slow": 8,
                "monthly_fast": 2,
                "monthly_slow": 3,
                "weekly_fast": 2,
                "weekly_slow": 3,
                "trend_efficiency_window": 8,
                "trend_efficiency_threshold": 0.01,
                "max_leverage": 2.0,
                "level_set": "fast_5_15_30",
                "max_pullback_pct": 0.05,
                "take_profit_pct": None,
                "stop_loss_pct": 0.03,
                "cooldown_bars_after_stop": 2,
                "allow_additive_ladder": True,
            },
            optimization_stage="original",
            optimization_components=["ma_ladder_limit_pullback"],
            notes=[],
        ),
        lab.MaLadderSpec(
            variant_id="contract_mid",
            label="contract mid",
            params={
                "daily_fast": 3,
                "daily_slow": 8,
                "hourly_fast": 3,
                "hourly_slow": 8,
                "four_hour_fast": 3,
                "four_hour_slow": 8,
                "monthly_fast": 2,
                "monthly_slow": 3,
                "weekly_fast": 2,
                "weekly_slow": 3,
                "trend_efficiency_window": 8,
                "trend_efficiency_threshold": 0.01,
                "max_leverage": 3.0,
                "level_set": "mid_5_15_30",
                "max_pullback_pct": 0.05,
                "take_profit_pct": 0.08,
                "stop_loss_pct": 0.03,
                "cooldown_bars_after_stop": 2,
                "allow_additive_ladder": True,
            },
            optimization_stage="formal_narrow_ma_ladder_grid",
            optimization_components=["ma_ladder_limit_pullback", "research_leverage"],
            notes=[],
        ),
    ]


def _frames() -> dict[str, pd.DataFrame]:
    base_index = pd.date_range("2026-01-01", periods=600, freq="15min", tz="UTC")
    frames = {
        "1m": _ohlcv(pd.date_range("2026-01-01", periods=600 * 15, freq="1min", tz="UTC"), step=0.003),
        "5m": _ohlcv(pd.date_range("2026-01-01", periods=600 * 3, freq="5min", tz="UTC"), step=0.004),
        "15m": _ohlcv(base_index, step=0.01),
        "30m": _ohlcv(pd.date_range("2026-01-01", periods=300, freq="30min", tz="UTC"), step=0.02),
        "1h": _ohlcv(pd.date_range("2026-01-01", periods=150, freq="1h", tz="UTC"), step=0.04),
        "4h": _ohlcv(pd.date_range("2026-01-01", periods=40, freq="4h", tz="UTC"), step=0.16),
        "1d": _ohlcv(pd.date_range("2026-01-01", periods=12, freq="1D", tz="UTC"), step=0.6),
        "1w": _ohlcv(pd.date_range("2025-12-01", periods=8, freq="7D", tz="UTC"), step=3.0),
        "1mo": _ohlcv(pd.date_range("2025-01-01", periods=12, freq="30D", tz="UTC"), step=6.0),
    }
    return frames


def _ohlcv(open_index: pd.DatetimeIndex, *, step: float) -> pd.DataFrame:
    closes = pd.Series([100.0 + i * step for i in range(len(open_index))], index=open_index)
    values = closes.to_numpy()
    frame = pd.DataFrame(
        {
            "open_time": open_index,
            "open": values * 0.999,
            "high": values * 1.004,
            "low": values * 0.99,
            "close": values,
            "volume": 100.0,
        },
        index=open_index + (open_index[1] - open_index[0]) - timedelta(milliseconds=1) if len(open_index) > 1 else open_index,
    )
    return frame


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
