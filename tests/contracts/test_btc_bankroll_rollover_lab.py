from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.bankroll_rollover_lab import (
    INITIAL_SLEEVE_COUNT,
    LEVERAGE_LEVELS,
    ROLLOVER_POLICIES,
    build_btc_bankroll_rollover_lab,
)


def test_bankroll_rollover_lab_is_research_only_and_models_sleeve_liquidation(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = build_btc_bankroll_rollover_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_bankroll_rollover_lab_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_bankroll_rollover_lab_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False

    design = report["experiment_design"]
    assert design["initial_sleeve_count"] == INITIAL_SLEEVE_COUNT
    assert set(design["leverage_levels"]) == set(LEVERAGE_LEVELS)
    assert set(design["rollover_policies"]) == set(ROLLOVER_POLICIES)
    assert design["candidate_count"] == len(LEVERAGE_LEVELS) * len(ROLLOVER_POLICIES)
    assert design["liquidation_model"]["model"] == "isolated_linear_perp_intrabar_mark_proxy"
    assert design["funding_model"]["promotion_evidence"] is False

    rows = report["candidate_rows"]
    assert len(rows) == design["candidate_count"]
    assert {float(row["leverage"]) for row in rows} == set(LEVERAGE_LEVELS)
    assert {row["rollover_policy"] for row in rows} == set(ROLLOVER_POLICIES)
    assert all(row["paper_queue_write_allowed"] is False for row in rows)
    assert all(row["live_unlock_allowed"] is False for row in rows)
    assert any(float(row["leverage"]) == 100.0 and int(row["total_liquidation_count"]) > 0 for row in rows)
    assert any(row["rollover_policy"] in {"split_2_on_double", "split_5_on_double"} for row in rows)
    assert "research_decision" in rows[0]

    stress = report["stress_summary"]
    assert stress["paper_queue_write_allowed"] is False
    assert stress["live_unlock_allowed"] is False
    assert len(stress["stress_rows"]) == 4
    assert {row["scenario_id"].split("_")[-1] for row in stress["stress_rows"]} >= {"base", "cost2x", "funding2x"}

    assert report["event_sample"]
    assert any(event["event_type"] == "liquidation" for event in report["event_sample"])
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["extreme_leverage_research_only"] is True
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    markdown = (tmp_path / "out" / "btc_bankroll_rollover_lab_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 分仓滚仓实验室" in markdown
    assert "写入 paper 队列：`False`" in markdown


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
    for i in range(260 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i < 70 * 24:
            drift = 1.00055
        elif i < 130 * 24:
            drift = 0.99935
        else:
            drift = 1.00032 + (0.0006 if i % 72 < 8 else -0.00008)
        price = max(25.0, price * drift)
        spike = 1.03 if i % 240 == 20 else 1.002
        dip = 0.97 if i % 240 == 21 else 0.998
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
                price * spike,
                price * dip,
                price,
                100.0 + (i % 24),
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(260 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 100.0,
                "funding_rate": 0.00004 + ((i % 96) - 48) * 0.0000008,
                "long_short_ratio": 1.0 + ((i % 144) - 72) / 700.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
