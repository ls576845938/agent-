from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.bankroll_layered_sleeve_scheduler_review import build_btc_bankroll_layered_sleeve_scheduler_review


def test_layered_sleeve_scheduler_review_keeps_attack_risk_capped_and_research_only(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "spike_defense_report.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_report.write_text(json.dumps({"status": "complete_research_only"}), encoding="utf-8")

    report = build_btc_bankroll_layered_sleeve_scheduler_review(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_spike_defense_report_path=source_report,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_bankroll_layered_sleeve_scheduler_review_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "layered_sleeve_scheduler_review_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["hundred_x_review_candidate_allowed"] is False

    design = report["review_design"]
    assert design["roles"] == ["core", "reserve", "attack"]
    assert design["max_leverage"] == 10.0
    assert design["one_off_spike_pcts"] == [3.0, 5.0, 8.0, 10.0]
    assert "previous completed 4h bar" in design["reserve_entry_rule"]

    rows = _load_csv(tmp_path / "out" / "btc_bankroll_layered_sleeve_scheduler_grid.csv")
    assert len(rows) == design["scenario_count"]
    assert any(row["scenario_id"] == "baseline_all10x_max10_no_extract" for row in rows)
    assert any(row["scenario_id"] == "baseline_all5x_max10_no_extract" for row in rows)
    layered_rows = [row for row in rows if row["policy_id"] == "layered_core_reserve_attack"]
    assert layered_rows
    assert all(int(row["core_sleeve_count"]) >= 4 for row in layered_rows)
    assert all(int(row["reserve_sleeve_count"]) >= 1 for row in layered_rows)
    assert all(int(row["attack_sleeve_count"]) in {1, 2} for row in layered_rows)
    assert all(int(row["max_concurrent_exposed_sleeves_observed"]) <= int(row["max_total_exposed"]) for row in rows)
    assert all(int(row["max_attack_exposed_sleeves_observed"]) <= int(row["max_attack_exposed"]) for row in rows)
    assert all(max(json.loads(row["sleeve_leverages"])) <= 10.0 for row in rows)
    assert all(row["paper_queue_write_allowed"] == "False" for row in rows)
    assert all(row["live_unlock_allowed"] == "False" for row in rows)
    assert "min_remaining_capital_pct_after_10pct_spike" in rows[0]
    assert "max_sleeves_lost_single_10pct_spike" in rows[0]

    summary = report["summary"]
    assert summary["best_layered_scenario_id"]
    assert summary["best_extract_scenario_id"]
    assert summary["best_10x_attack_scenario_id"]
    assert int(summary["best_10x_attack_max_attack_exposed_sleeves_observed"]) > 0
    assert summary["research_watchlist_count"] >= 0
    baseline = report["baseline_all_10x"]
    assert baseline["scenario_id"] == "baseline_all10x_max10_no_extract"
    assert float(summary["best_layered_min_remaining_capital_pct_after_10pct_spike"]) >= float(baseline["min_remaining_capital_pct_after_10pct_spike"])

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    markdown = (tmp_path / "out" / "btc_bankroll_layered_sleeve_scheduler_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 分层 sleeve 调度器复核" in markdown
    assert "不生成策略骨架，不进入 paper/live" in markdown


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


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
        spike = 1.035 if i % 240 == 20 else 1.002
        dip = 0.965 if i % 240 == 21 else 0.998
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
