from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.simple_trend_rule_lab import (
    align_derivatives_to_index,
    build_btc_simple_trend_rule_lab,
    simple_trend_rule_specs,
)


def test_simple_trend_rule_specs_have_original_single_and_combo_variants() -> None:
    specs = simple_trend_rule_specs()
    families = {spec.family_id for spec in specs}

    assert families == {
        "atr_channel",
        "donchian_turtle",
        "ma_ribbon",
        "oi_confirmed_atr_breakout",
        "squeeze_breakout",
        "supertrend",
    }
    assert len(specs) > 12
    for family in families:
        stages = {spec.optimization_stage for spec in specs if spec.family_id == family}
        assert "original" in stages
        assert any(stage.startswith("single_") for stage in stages)
        assert any(stage.startswith("combo_") for stage in stages)


def test_derivatives_alignment_uses_available_time_asof_only(tmp_path: Path) -> None:
    rows_path = tmp_path / "derivatives.json"
    rows = [
        {
            "event_time": "2026-01-01T00:00:00+00:00",
            "available_time": "2026-01-01T00:05:00+00:00",
            "open_interest_usd": 100.0,
            "funding_rate": 0.1,
            "long_short_ratio": 1.1,
        },
        {
            "event_time": "2026-01-01T04:00:00+00:00",
            "available_time": "2026-01-01T04:05:00+00:00",
            "open_interest_usd": 200.0,
            "funding_rate": 0.2,
            "long_short_ratio": 1.2,
        },
    ]
    rows_path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    index = [
        datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 4, 5, tzinfo=timezone.utc),
    ]

    aligned = align_derivatives_to_index(rows_path, index)

    assert aligned.iloc[0]["open_interest_usd"] == 100.0
    assert aligned.iloc[1]["open_interest_usd"] == 200.0


def test_simple_trend_rule_lab_is_research_only_and_writes_outputs(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = build_btc_simple_trend_rule_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_simple_trend_rule_lab_research_only_shortlist_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["real_order_submitted"] is False
    assert report["validation_design"]["candidate_family_count"] == 6
    assert report["validation_design"]["candidate_count"] == len(simple_trend_rule_specs())
    assert len(report["family_stepwise_comparison"]) == 6
    assert all("optimization_stage" in row for row in report["comparison_rows"])
    assert all(row["paper_queue_write_allowed"] is False for row in report["comparison_rows"])
    assert (tmp_path / "out" / "btc_simple_trend_rule_lab_report.json").exists()
    assert (tmp_path / "out" / "btc_simple_trend_rule_lab_grid.csv").exists()
    markdown = (tmp_path / "out" / "btc_simple_trend_rule_lab_summary_cn.md").read_text(encoding="utf-8")
    assert "逐步优化对比" in markdown


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
    for i in range(220 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        wave = (i % 96) / 96.0
        price = price * (1.0005 + 0.0008 * wave)
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.99,
                price * 1.01,
                price * 0.98,
                price,
                100.0 + i % 10,
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(220 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 100.0,
                "funding_rate": 0.0001,
                "long_short_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
