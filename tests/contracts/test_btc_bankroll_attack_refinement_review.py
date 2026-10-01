from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.bankroll_attack_refinement_review import build_btc_bankroll_attack_refinement_review


def test_attack_refinement_requires_actual_10x_exposure_and_80pct_spike_survival(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "layered_report.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_report.write_text(
        json.dumps(
            {
                "schema_version": "btc_bankroll_layered_sleeve_scheduler_review_v1",
                "decision": "layered_sleeve_scheduler_review_research_only_no_paper_no_live",
                "summary": {
                    "best_10x_attack_scenario_id": "layer_core5x6_reserve5x2_attack10x2_max7_extract",
                    "best_10x_attack_total_return_pct": 689.895504,
                    "best_10x_attack_min_remaining_capital_pct_after_10pct_spike": 88.211549,
                    "best_10x_attack_max_attack_exposed_sleeves_observed": 1,
                    "best_10x_attack_average_attack_exposed_sleeves": 0.043956,
                },
            }
        ),
        encoding="utf-8",
    )

    report = build_btc_bankroll_attack_refinement_review(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_layered_report_path=source_report,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_bankroll_attack_refinement_review_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "attack_refinement_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["hundred_x_review_candidate_allowed"] is False

    design = report["review_design"]
    assert design["scenario_count"] == 432
    assert design["watchlist_requires_actual_attack_exposure"] is True
    assert design["watchlist_min_remaining_capital_pct_after_10pct_spike"] == 80.0
    assert design["max_research_leverage"] == 10.0
    assert design["attack_leverage"] == 10.0
    assert design["max_total_exposed_grid"] == [7, 8, 10]
    assert design["attack_delay_profiles"] == ["balanced", "early", "late"]
    assert "小资金" in design["small_account_risk_tolerance_note"]

    rows = _load_csv(tmp_path / "out" / "btc_bankroll_attack_refinement_grid.csv")
    assert len(rows) == design["scenario_count"]
    assert all(row["policy_id"].startswith("actual_10x_attack_refinement_") for row in rows)
    assert all(int(row["max_total_exposed"]) in {7, 8, 10} for row in rows)
    assert all(row["attack_delay_profile"] in {"early", "balanced", "late"} for row in rows)
    assert all(max(json.loads(row["sleeve_leverages"])) <= 10.0 for row in rows)
    assert all(100.0 not in json.loads(row["sleeve_leverages"]) for row in rows)
    assert all(row["paper_queue_write_allowed"] == "False" for row in rows)
    assert all(row["paper_candidate_created"] == "False" for row in rows)
    assert all(row["live_unlock_allowed"] == "False" for row in rows)
    assert any(int(row["max_attack_exposed_sleeves_observed"]) > 0 for row in rows)

    watchlist = _load_csv(tmp_path / "out" / "btc_bankroll_attack_refinement_watchlist.csv")
    assert int(report["summary"]["actual_attack_scenario_count"]) > 0
    assert int(report["summary"]["watchlist_count"]) == len(watchlist)
    assert len(watchlist) > 0
    assert all(row["watchlist_decision"] == "retain_attack_refinement_research_watchlist_only" for row in watchlist)
    assert all(int(row["max_attack_exposed_sleeves_observed"]) > 0 for row in watchlist)
    assert all(float(row["min_remaining_capital_pct_after_10pct_spike"]) >= 80.0 for row in watchlist)
    assert all(float(row["total_return_pct"]) > 0.0 for row in watchlist)
    assert all(int(row["normal_liquidation_count"]) == 0 for row in watchlist)

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_candidate_created"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    assert safety["max_research_leverage"] == 10.0
    markdown = (tmp_path / "out" / "btc_bankroll_attack_refinement_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 10x attack 分仓细化复核包" in markdown
    assert "不代表系统可以绕过 paper/live 门禁" in markdown


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
