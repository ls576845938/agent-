from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.bankroll_spike_defense_review import (
    LEVERAGE_PROFILES,
    MAX_CONCURRENT_EXPOSURES,
    ROLLOVER_POLICIES,
    STAGGER_PROFILES,
    build_btc_bankroll_spike_defense_review,
)


def test_spike_defense_review_focuses_on_capital_survival_not_paper_live(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "source_report.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_report.write_text(json.dumps({"status": "complete_research_only"}), encoding="utf-8")

    report = build_btc_bankroll_spike_defense_review(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_report_path=source_report,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_bankroll_spike_defense_review_v2"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "spike_defense_review_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["hundred_x_review_candidate_allowed"] is False

    design = report["review_design"]
    assert design["scenario_count"] == len(LEVERAGE_PROFILES) * len(STAGGER_PROFILES) * len(MAX_CONCURRENT_EXPOSURES) * len(ROLLOVER_POLICIES)
    assert design["one_off_spike_pcts"] == [3.0, 5.0, 8.0, 10.0]
    assert max(max(profile) for profile in LEVERAGE_PROFILES.values()) == 10.0

    rows = _load_csv(tmp_path / "out" / "btc_bankroll_spike_defense_review_grid.csv")
    assert len(rows) == design["scenario_count"]
    assert {row["leverage_profile_id"] for row in rows} == set(LEVERAGE_PROFILES)
    assert {row["stagger_profile_id"] for row in rows} == set(STAGGER_PROFILES)
    assert {int(row["max_concurrent_exposures"]) for row in rows} == set(MAX_CONCURRENT_EXPOSURES)
    assert {row["rollover_policy"] for row in rows} == set(ROLLOVER_POLICIES)
    assert all(float(row["max_concurrent_exposed_sleeves_observed"]) <= int(row["max_concurrent_exposures"]) for row in rows)
    assert all(row["paper_queue_write_allowed"] == "False" for row in rows)
    assert all(row["live_unlock_allowed"] == "False" for row in rows)
    assert "min_remaining_capital_pct_after_10pct_spike" in rows[0]
    assert "max_sleeves_lost_single_10pct_spike" in rows[0]

    baseline = report["baseline_all_at_once_10x"]
    best = report["top_survivors"][0]
    summary = report["summary"]
    assert baseline["leverage_profile_id"] == "all_10x"
    assert baseline["stagger_profile_id"] == "all_at_once"
    assert int(baseline["max_concurrent_exposures"]) == 10
    assert float(best["min_remaining_capital_pct_after_10pct_spike"]) >= float(baseline["min_remaining_capital_pct_after_10pct_spike"])
    assert summary["best_all_10x_scenario_id"]
    assert summary["best_mixed_scenario_id"]
    assert summary["best_limited_exposure_scenario_id"]
    assert any(float(row["min_remaining_capital_pct_after_10pct_spike"]) >= 70.0 for row in rows)
    assert any(row["stagger_profile_id"] != "all_at_once" for row in rows)
    assert any(row["leverage_profile_id"] == "mixed_3_5_10" for row in rows)
    assert any(row["rollover_policy"] == "extract_principal_on_double" and float(row["reserve_cash_pct_of_initial"]) >= 0.0 for row in rows)

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    markdown = (tmp_path / "out" / "btc_bankroll_spike_defense_review_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 分仓防插针复核包 v2" in markdown
    assert "插针后剩余本金比例" in markdown


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
