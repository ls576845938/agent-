from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.bankroll_attack_top_confirmation_review import TOP_SCENARIO_ID, build_btc_bankroll_attack_top_confirmation_review


def test_attack_top_confirmation_reviews_liquidation_funding_and_rolling_start_research_only(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "attack_refinement_report.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_attack_refinement_report(source_report)

    report = build_btc_bankroll_attack_top_confirmation_review(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_attack_refinement_report_path=source_report,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_bankroll_attack_top_confirmation_review_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] in {
        "eligible_for_30_60_day_forward_observation_research_only_no_paper_no_live",
        "not_forward_observation_ready_due_to_liquidation_funding_or_path_dependency",
    }
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_access_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["hundred_x_review_candidate_allowed"] is False
    assert report["review_design"]["top_scenario_id"] == TOP_SCENARIO_ID
    assert report["review_design"]["max_research_leverage"] == 10.0

    summary = report["summary"]
    assert summary["top_scenario_id"] == TOP_SCENARIO_ID
    assert summary["liquidation_sensitivity_row_count"] == 216
    assert summary["funding_cost_stress_row_count"] == 9
    assert summary["rolling_start_count"] >= 3
    assert summary["base_normal_liquidation_count"] >= 0
    assert "base_min_remaining_capital_pct_after_10pct_spike" in summary

    liquidation_rows = _load_csv(tmp_path / "out" / "btc_bankroll_attack_top_confirmation_liquidation_sensitivity.csv")
    assert len(liquidation_rows) == 216
    assert {float(row["maintenance_margin_rate"]) for row in liquidation_rows} == {0.005, 0.008, 0.01}
    assert {float(row["liquidation_fee_rate"]) for row in liquidation_rows} == {0.003, 0.005, 0.01}
    assert {float(row["mark_price_adverse_offset_bps"]) for row in liquidation_rows} == {0.0, 50.0, 100.0, 200.0}
    assert {float(row["one_off_adverse_spike_pct"]) for row in liquidation_rows} == {0.0, 3.0, 5.0, 8.0, 10.0, 12.0}
    assert all(row["paper_queue_write_allowed"] == "False" for row in liquidation_rows)
    assert all(row["live_unlock_allowed"] == "False" for row in liquidation_rows)

    funding_rows = _load_csv(tmp_path / "out" / "btc_bankroll_attack_top_confirmation_funding_cost_stress.csv")
    assert len(funding_rows) == 9
    assert {float(row["funding_adverse_multiplier"]) for row in funding_rows} == {1.0, 2.0, 5.0}
    assert {float(row["cost_multiplier"]) for row in funding_rows} == {1.0, 2.0, 5.0}
    assert all(row["stress_type"] == "funding_cost_stress" for row in funding_rows)

    rolling_rows = _load_csv(tmp_path / "out" / "btc_bankroll_attack_top_confirmation_rolling_start.csv")
    assert len(rolling_rows) == summary["rolling_start_count"]
    assert all(row["stress_type"] == "rolling_start" for row in rolling_rows)
    assert all(row["scenario_id"] == TOP_SCENARIO_ID for row in rolling_rows)
    assert all(float(row["max_attack_exposed_sleeves_observed"]) <= 1.0 for row in rolling_rows)

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_candidate_created"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    assert safety["max_research_leverage"] == 10.0


def _write_source_attack_refinement_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_bankroll_attack_refinement_review_v1",
                "decision": "attack_refinement_research_only_no_paper_no_live",
                "summary": {
                    "best_return_watchlist_scenario_id": TOP_SCENARIO_ID,
                    "best_return_watchlist_total_return_pct": 9286.142323,
                    "best_return_watchlist_min_remaining_capital_pct_after_10pct_spike": 84.802195,
                },
                "top_attack_watchlist": [_top_source_row()],
            }
        ),
        encoding="utf-8",
    )


def _top_source_row() -> dict[str, object]:
    return {
        "scenario_id": TOP_SCENARIO_ID,
        "policy_id": "actual_10x_attack_refinement_late",
        "max_total_exposed": 8,
        "max_attack_exposed": 1,
        "extract_on_double": False,
        "reserve_requires_pullback": True,
        "sleeve_roles": json.dumps(["core", "core", "core", "core", "core", "core", "reserve", "reserve", "attack", "attack"]),
        "sleeve_leverages": json.dumps([5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 10.0, 10.0]),
        "sleeve_entry_delay_bars": json.dumps([0, 1, 2, 0, 1, 2, 6, 9, 6, 9]),
        "total_return_pct": 9286.142323,
        "min_remaining_capital_pct_after_10pct_spike": 84.802195,
        "max_attack_exposed_sleeves_observed": 1,
    }


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
