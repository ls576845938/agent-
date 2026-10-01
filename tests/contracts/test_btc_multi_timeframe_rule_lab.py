from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.multi_timeframe_rule_lab import (
    aggregate_ohlcv_calendar,
    align_derivatives_to_index,
    build_btc_multi_timeframe_rule_lab,
    evaluate_mtf_rule,
    multi_timeframe_rule_specs,
)
from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv, load_market_1h


def test_multi_timeframe_specs_cover_all_families_and_stepwise_variants() -> None:
    specs = multi_timeframe_rule_specs()
    families = {spec.family_id for spec in specs}

    assert families == {
        "derivatives_risk_filtered_trend",
        "multi_tf_squeeze_breakout",
        "multi_tf_trend_confirm",
        "multi_tf_turtle",
        "regime_router",
        "short_research_branch",
        "trend_pullback_reentry",
        "vote_ensemble",
    }
    assert len(specs) >= 32
    assert any(spec.params.get("use_weekly_confirm") and spec.params.get("use_monthly_confirm") for spec in specs)
    assert any(spec.params.get("use_tiered_higher_timeframe_control") for spec in specs)
    trend_tiered = [
        spec for spec in specs
        if spec.family_id == "multi_tf_trend_confirm" and spec.params.get("use_tiered_higher_timeframe_control")
    ]
    assert len(trend_tiered) >= 7
    assert {spec.variant_id for spec in trend_tiered} >= {
        "mtf_trend_tiered_htf_control",
        "mtf_trend_tiered_weekly_60_20",
        "mtf_trend_tiered_weekly_strict_cash",
        "mtf_trend_tiered_weekly_loose",
        "mtf_trend_tiered_monthly_fast_switch",
        "mtf_trend_tiered_monthly_slow_switch",
        "mtf_trend_tiered_weekly_60_fast_monthly",
    }
    for family in families:
        stages = {spec.optimization_stage for spec in specs if spec.family_id == family}
        assert "original" in stages
        assert any(stage.startswith("single_") for stage in stages)
        assert any(stage.startswith("combo_") for stage in stages)


def test_derivatives_alignment_uses_available_time_not_future_event(tmp_path: Path) -> None:
    rows_path = tmp_path / "derivatives.json"
    rows = [
        {
            "event_time": "2026-01-01T00:00:00+00:00",
            "available_time": "2026-01-01T00:05:00+00:00",
            "open_interest_usd": 100.0,
            "funding_rate": 0.01,
            "long_short_ratio": 1.1,
        },
        {
            "event_time": "2026-01-01T04:00:00+00:00",
            "available_time": "2026-01-01T04:05:00+00:00",
            "open_interest_usd": 200.0,
            "funding_rate": 0.02,
            "long_short_ratio": 1.2,
        },
    ]
    rows_path.write_text(json.dumps({"rows": rows}), encoding="utf-8")

    aligned = align_derivatives_to_index(
        rows_path,
        [
            datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 4, 5, tzinfo=timezone.utc),
        ],
    )

    assert aligned.iloc[0]["open_interest_usd"] == 100.0
    assert aligned.iloc[1]["open_interest_usd"] == 200.0


def test_multi_timeframe_lab_is_research_only_and_buckets_short_branch(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = build_btc_multi_timeframe_rule_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_multi_timeframe_rule_lab_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["real_order_submitted"] is False
    assert report["validation_design"]["candidate_family_count"] == 8
    assert report["validation_design"]["candidate_count"] == len(multi_timeframe_rule_specs())
    assert report["input"]["derived_timeframes_from_1h"] == ["4h", "1d", "1w", "1mo"]
    assert report["input"]["bar_1w_rows"] > 0
    assert report["input"]["bar_1mo_rows"] > 0
    assert report["higher_timeframe_context"]["bar_1w_rows"] == report["input"]["bar_1w_rows"]
    assert "daily_weekly_monthly_bull_alignment_pct" in report["higher_timeframe_context"]
    assert any(row["params"].get("use_tiered_higher_timeframe_control") for row in report["comparison_rows"])
    assert len(report["family_stepwise_comparison"]) == 8
    assert all(row["paper_queue_write_allowed"] is False for row in report["comparison_rows"])
    assert all(row["family_id"] != "short_research_branch" for row in report["extended_research_shortlist"])
    assert all(row["branch"] == "short_research" for row in report["short_research_rows"])
    assert (tmp_path / "out" / "btc_multi_timeframe_rule_lab_report.json").exists()
    assert (tmp_path / "out" / "btc_multi_timeframe_rule_lab_grid.csv").exists()
    markdown = (tmp_path / "out" / "btc_multi_timeframe_rule_lab_summary_cn.md").read_text(encoding="utf-8")
    assert "普通扩展研究短名单" in markdown
    assert "做空研究观察名单" in markdown


def test_timeframes_are_derived_from_completed_1h_bars(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    _write_market_db(db)

    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")

    assert len(bars_4h) == len(source_1h) // 4
    assert len(bars_1d) == len(source_1h) // 24
    assert len(bars_1w) > 0
    assert len(bars_1mo) > 0
    assert bars_4h.index.max() <= source_1h.index.max()
    assert bars_1d.index.max() <= source_1h.index.max()
    assert bars_1w.index.max() <= source_1h.index.max()
    assert bars_1mo.index.max() <= source_1h.index.max()
    assert all(open_time.weekday() == 0 for open_time in bars_1w["open_time"])
    assert all(open_time.day == 1 for open_time in bars_1mo["open_time"])


def test_one_hour_exit_signal_only_affects_next_4h_exposure(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    derivatives_4h = align_derivatives_to_index(derivatives, bars_4h.index)
    spec = next(item for item in multi_timeframe_rule_specs() if item.variant_id == "mtf_trend_1h_exit")

    evaluated = evaluate_mtf_rule(
        spec,
        bars_1h=source_1h,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        derivatives_4h=derivatives_4h,
        initial_capital=25_000.0,
        cost_bps=10.0,
    )

    expected = evaluated.raw_signal.shift(1).fillna(0.0)
    assert evaluated.exposure.equals(expected)


def test_higher_timeframe_specs_auto_derive_weekly_monthly_for_legacy_callers(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives, bars_4h.index)
    spec = next(item for item in multi_timeframe_rule_specs() if item.variant_id == "mtf_trend_weekly_monthly_confirm")

    explicit = evaluate_mtf_rule(
        spec,
        bars_1h=source_1h,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
        initial_capital=25_000.0,
        cost_bps=10.0,
    )
    legacy = evaluate_mtf_rule(
        spec,
        bars_1h=source_1h,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        derivatives_4h=derivatives_4h,
        initial_capital=25_000.0,
        cost_bps=10.0,
    )

    assert legacy.raw_signal.equals(explicit.raw_signal)
    assert legacy.metrics["total_return_pct"] == explicit.metrics["total_return_pct"]

    tiered_spec = next(item for item in multi_timeframe_rule_specs() if item.variant_id == "mtf_trend_tiered_htf_control")
    explicit_tiered = evaluate_mtf_rule(
        tiered_spec,
        bars_1h=source_1h,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
        initial_capital=25_000.0,
        cost_bps=10.0,
    )
    legacy_tiered = evaluate_mtf_rule(
        tiered_spec,
        bars_1h=source_1h,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        derivatives_4h=derivatives_4h,
        initial_capital=25_000.0,
        cost_bps=10.0,
    )

    assert legacy_tiered.raw_signal.equals(explicit_tiered.raw_signal)
    assert legacy_tiered.metrics["total_return_pct"] == explicit_tiered.metrics["total_return_pct"]


def test_fixed_input_is_reproducible(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    first = build_btc_multi_timeframe_rule_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out1",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )
    second = build_btc_multi_timeframe_rule_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out2",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert [row["candidate_id"] for row in first["comparison_rows"]] == [
        row["candidate_id"] for row in second["comparison_rows"]
    ]
    assert [row["score"] for row in first["comparison_rows"]] == [row["score"] for row in second["comparison_rows"]]


def _write_market_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        create table market_klines (
            exchange text not null,
            symbol text not null,
            interval text not null,
            open_time_ms integer not null,
            open_time text not null,
            close_time_ms integer not null,
            close_time text not null,
            open real not null,
            high real not null,
            low real not null,
            close real not null,
            volume real not null
        )
        """
    )
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(240 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        cycle = (i % 720) / 720.0
        drift = 1.00035 + 0.0012 * cycle
        if 240 * 24 * 0.55 < i < 240 * 24 * 0.68:
            drift = 0.9991
        price = max(10.0, price * drift)
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.995,
                price * 1.012,
                price * 0.988,
                price,
                100.0 + (i % 24) * 2.0,
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(240 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 120.0 + (i % 48) * 50.0,
                "funding_rate": 0.00008 + (i % 72) * 0.000001,
                "long_short_ratio": 1.0 + (i % 96) / 400.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
