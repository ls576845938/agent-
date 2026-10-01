from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.bankroll_rollover_review import (
    EXTRA_SHOCK_PCT,
    FEE_MULTIPLIERS,
    FUNDING_STRESS_MULTIPLIERS,
    LIQUIDATION_FEE_RATES,
    LIQUIDATION_MAINTENANCE_RATES,
    LIQUIDATION_POLICIES,
    MARK_ADVERSE_BPS,
    SLIPPAGE_MULTIPLIERS,
    build_btc_bankroll_rollover_review,
)


def test_bankroll_rollover_review_is_research_only_and_covers_declared_stress_grid(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "source_report.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_report.write_text(json.dumps({"status": "complete_research_only"}), encoding="utf-8")

    report = build_btc_bankroll_rollover_review(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_report_path=source_report,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_bankroll_rollover_review_v1"
    assert report["status"] == "complete_research_only"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["hundred_x_review_candidate_allowed"] is False

    source_rows = report["source_attribution"]["rows"]
    assert {
        "br_review_no_rollover_lev1p0",
        "br_review_no_rollover_lev3p0",
        "br_review_no_rollover_lev5p0",
        "br_review_no_rollover_lev10p0",
        "br_review_split_2_on_double_lev10p0",
        "br_review_extract_principal_roll_profit_lev10p0",
    } <= {row["scenario_id"] for row in source_rows}
    assert report["source_attribution"]["summary"]["main_driver"] in {
        "leverage_compounding_not_split",
        "rollover_policy_materially_changes_terminal_equity",
    }

    liquidation_rows = _load_csv(tmp_path / "out" / "btc_bankroll_rollover_review_liquidation_sensitivity.csv")
    assert len(liquidation_rows) == len(LIQUIDATION_POLICIES) * len(LIQUIDATION_MAINTENANCE_RATES) * len(LIQUIDATION_FEE_RATES) * len(MARK_ADVERSE_BPS) * len(EXTRA_SHOCK_PCT)
    assert {row["rollover_policy"] for row in liquidation_rows} == set(LIQUIDATION_POLICIES)
    assert {float(row["maintenance_margin_rate"]) for row in liquidation_rows} == set(LIQUIDATION_MAINTENANCE_RATES)
    assert {float(row["liquidation_fee_rate"]) for row in liquidation_rows} == set(LIQUIDATION_FEE_RATES)
    assert {float(row["mark_adverse_bps"]) for row in liquidation_rows} == set(MARK_ADVERSE_BPS)
    assert {float(row["extra_shock_pct"]) for row in liquidation_rows} == set(EXTRA_SHOCK_PCT)
    assert all(float(row["leverage"]) < 100.0 for row in liquidation_rows)
    assert any(int(row["total_liquidation_count"]) > 0 for row in liquidation_rows)

    cost_rows = _load_csv(tmp_path / "out" / "btc_bankroll_rollover_review_funding_cost_stress.csv")
    assert {float(row["funding_stress_multiplier"]) for row in cost_rows} >= set(FUNDING_STRESS_MULTIPLIERS)
    assert {float(row["fee_multiplier"]) for row in cost_rows} >= set(FEE_MULTIPLIERS)
    assert {float(row["slippage_multiplier"]) for row in cost_rows} >= set(SLIPPAGE_MULTIPLIERS)
    assert any(row["stress_case"] == "combined_max" for row in cost_rows)
    assert any(row["rollover_policy"] == "split_2_on_double" for row in cost_rows)

    segment_rows = _load_csv(tmp_path / "out" / "btc_bankroll_rollover_review_segment_rolling_start.csv")
    rolling_rows = [row for row in segment_rows if row.get("row_type") == "rolling_start"]
    assert len(rolling_rows) >= 4
    assert {"split_2_on_double", "extract_principal_roll_profit"} <= {row["rollover_policy"] for row in rolling_rows}
    assert "all_sleeves_dead" in rolling_rows[0]
    assert "total_liquidation_count" in rolling_rows[0]

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    assert safety["hundred_x_review_candidate_allowed"] is False
    markdown = (tmp_path / "out" / "btc_bankroll_rollover_review_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 分仓滚仓复核包 v1" in markdown
    assert "写入 paper 队列：`False`" in markdown


def _load_csv(path: Path) -> list[dict[str, str]]:
    import csv

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
