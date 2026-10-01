from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.long_short_trend_following_lab import (
    build_btc_long_short_trend_following_lab,
    evaluate_long_short_trend_rule,
    long_short_trend_following_specs,
)
from quant_crypto.research.multi_timeframe_rule_lab import aggregate_ohlcv_calendar
from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv, align_derivatives_to_index, load_market_1h


def test_long_short_specs_are_symmetric_research_only_with_references() -> None:
    specs = long_short_trend_following_specs()
    families = {spec.family_id for spec in specs}

    assert families >= {
        "symmetric_donchian",
        "symmetric_donchian_formal_narrow",
        "symmetric_ema_ribbon",
        "hybrid_donchian_ema_atr",
        "symmetric_atr_channel",
    }
    assert {spec.direction_policy for spec in specs} >= {"long_short", "long_flat_reference", "short_flat_reference"}
    assert any(spec.params.get("use_derivatives_risk_filter") for spec in specs)
    assert all(spec.params["primary_signal_source"] == "price_trend" for spec in specs)
    assert all(spec.params["derivatives_usage"] == "risk_filter_only" for spec in specs)
    assert all("live" not in spec.variant_id for spec in specs)
    formal = [spec for spec in specs if spec.family_id == "symmetric_donchian_formal_narrow"]
    assert len(formal) == 5 * 3 * 4 * 3 * 2 * 4
    assert {spec.params["entry_window"] for spec in formal} == {72, 96, 120, 180, 240}
    assert {(spec.params["daily_fast"], spec.params["daily_slow"]) for spec in formal} == {(20, 80), (34, 144), (50, 200)}
    assert {spec.params["atr_mult"] for spec in formal} == {2.0, 2.5, 3.0, 3.5}
    assert {spec.params["cooldown_bars"] for spec in formal} == {0, 6, 12}
    assert {spec.params["use_failed_breakout_exit"] for spec in formal} == {False, True}
    assert {spec.params["risk_filter_mode"] for spec in formal} == {"none", "funding", "funding_oi", "funding_oi_long_short"}


def test_long_short_lab_is_research_only_and_compares_references(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, mode="mixed")
    _write_derivatives(derivatives)

    report = build_btc_long_short_trend_following_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        run_profile="smoke",
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_long_short_trend_following_lab_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["real_order_submitted"] is False
    assert report["validation_design"]["derivatives_usage"].startswith("funding/OI/long-short ratio are risk filters only")
    assert report["validation_design"]["run_profile"] == "smoke"
    assert report["validation_design"]["candidate_count"] == len(long_short_trend_following_specs(run_profile="smoke"))
    assert report["validation_design"]["formal_grid"]["formal_donchian_grid_count"] == 5 * 3 * 4 * 3 * 2 * 4
    assert report["input"]["derived_timeframes_from_1h"] == ["4h", "1d", "1w", "1mo"]
    assert report["reference_comparison"]["best_long_flat_reference_id"]
    assert report["reference_comparison"]["best_short_flat_reference_id"]
    assert all(row["direction_policy"] == "long_short" for row in report["long_short_research_rows"])
    assert {row["direction_policy"] for row in report["same_window_reference_rows"]} == {
        "long_flat_reference",
        "short_flat_reference",
    }
    assert all(row["paper_queue_write_allowed"] is False for row in report["comparison_rows"])
    assert (tmp_path / "out" / "btc_long_short_trend_following_lab_report.json").exists()
    assert (tmp_path / "out" / "btc_long_short_trend_following_lab_grid.csv").exists()
    markdown = (tmp_path / "out" / "btc_long_short_trend_following_lab_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC Long/Short 趋势跟踪实验室" in markdown
    assert "不写 paper 队列" in markdown


def test_symmetric_fast_donchian_uses_both_long_and_short_with_next_bar_execution(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, mode="mixed")
    _write_derivatives(derivatives)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives, bars_4h.index)
    spec = next(item for item in long_short_trend_following_specs(run_profile="smoke") if item.variant_id == "ls_donchian_fast_regime")

    evaluated = evaluate_long_short_trend_rule(
        spec,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
        initial_capital=25_000.0,
        cost_bps=10.0,
    )

    assert int((evaluated.exposure > 0.0).sum()) > 0
    assert int((evaluated.exposure < 0.0).sum()) > 0
    expected = evaluated.raw_signal.shift(1).fillna(0.0)
    assert evaluated.exposure.equals(expected)


def test_sideways_market_stays_cash_for_trend_rules(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, mode="sideways")
    _write_derivatives(derivatives)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives, bars_4h.index)
    spec = next(item for item in long_short_trend_following_specs(run_profile="smoke") if item.variant_id == "ls_donchian_fast_regime")

    evaluated = evaluate_long_short_trend_rule(
        spec,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
        initial_capital=25_000.0,
        cost_bps=10.0,
    )

    assert float(evaluated.exposure.abs().max()) == 0.0


def test_derivatives_alignment_uses_available_time_before_decision(tmp_path: Path) -> None:
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


def test_fixed_input_is_reproducible(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, mode="mixed")
    _write_derivatives(derivatives)

    first = build_btc_long_short_trend_following_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out1",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        run_profile="smoke",
    )
    second = build_btc_long_short_trend_following_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out2",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        run_profile="smoke",
    )

    assert [row["candidate_id"] for row in first["comparison_rows"]] == [
        row["candidate_id"] for row in second["comparison_rows"]
    ]
    assert [row["score"] for row in first["comparison_rows"]] == [row["score"] for row in second["comparison_rows"]]


def _write_market_db(path: Path, *, mode: str) -> None:
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
    for i in range(360 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if mode == "sideways":
            drift = 1.0
            cycle = ((i % 48) - 24) / 24.0
            price = 100.0 * (1.0 + 0.0008 * cycle)
        else:
            if i < 110 * 24:
                drift = 1.00045
            elif i < 170 * 24:
                drift = 1.0 + (((i % 96) - 48) / 48.0) * 0.0003
            else:
                drift = 0.99935
            price = max(20.0, price * drift)
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.999,
                price * 1.001,
                price * 0.999,
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
    for i in range(360 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 120.0 + (i % 48) * 50.0,
                "funding_rate": 0.00005 + ((i % 72) - 36) * 0.000001,
                "long_short_ratio": 1.0 + ((i % 96) - 48) / 400.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
