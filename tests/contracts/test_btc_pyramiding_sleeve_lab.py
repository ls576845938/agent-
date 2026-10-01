from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research import pyramiding_sleeve_lab as lab


def test_pyramiding_sleeve_lab_outputs_research_only_artifacts_and_spike_metrics(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    monkeypatch.setattr(lab, "_scenario_grid", _small_scenario_grid)

    report = lab.build_btc_pyramiding_sleeve_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_pyramiding_sleeve_lab_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_pyramiding_sleeve_lab_research_only_no_paper_no_live"
    assert report["research_design"]["scenario_count"] == 2
    assert report["research_design"]["max_leverage_allowed"] == 10.0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    assert report["baseline_no_pyramid"]["scenario_id"] == "baseline_no_pyramid_core5x_max5_extract"
    assert "min_remaining_capital_pct_after_10pct_spike" in report["baseline_no_pyramid"]
    assert report["summary"]["watchlist_count"] >= 0
    assert "actual_attack_watchlist_count" in report["summary"]
    assert "top_actual_attack_watchlist" in report
    for row in report["grid_rows_sample"]:
        assert float(row["max_template_leverage"]) <= 10.0
        assert row["paper_queue_write_allowed"] is False
        assert row["paper_candidate_created"] is False
        assert row["live_unlock_allowed"] is False
        assert "pyramid_entry_count" in row
        assert "min_remaining_capital_pct_after_10pct_spike" in row

    grid_csv = tmp_path / "out" / "btc_pyramiding_sleeve_lab_grid.csv"
    events_csv = tmp_path / "out" / "btc_pyramiding_sleeve_lab_events.csv"
    attack_csv = tmp_path / "out" / "btc_pyramiding_sleeve_lab_actual_attack_watchlist.csv"
    safety_path = tmp_path / "out" / "paper_live_safety_status.json"
    assert grid_csv.exists()
    assert events_csv.exists()
    assert attack_csv.exists()
    safety = json.loads(safety_path.read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def _small_scenario_grid() -> list[lab.PyramidScenario]:
    return [
        lab.PyramidScenario(
            scenario_id="baseline_no_pyramid_core5x_max5_extract",
            policy_id="baseline_no_pyramid",
            sleeve_templates=tuple(lab.PyramidTemplate("core", 5.0, i % 3, 0.0) for i in range(lab.INITIAL_SLEEVE_COUNT)),
            max_total_exposed=5,
            max_attack_exposed=0,
            extract_on_double=True,
            reserve_requires_pullback=False,
            pyramid_step_atr=0.0,
        ),
        lab.PyramidScenario(
            scenario_id="pyr_contract_core3x4_reserve3x4_attack10x2_max5_extract",
            policy_id="atr_favorable_pyramiding_sleeve_defense",
            sleeve_templates=(
                tuple(lab.PyramidTemplate("core", 3.0, i % 2, 0.0) for i in range(4))
                + tuple(lab.PyramidTemplate("reserve", 3.0, 3 + i, 0.1) for i in range(4))
                + tuple(lab.PyramidTemplate("attack", 10.0, 6 + i, 0.2) for i in range(2))
            ),
            max_total_exposed=5,
            max_attack_exposed=1,
            extract_on_double=True,
            reserve_requires_pullback=False,
            pyramid_step_atr=0.1,
        ),
    ]


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
    for i in range(320 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i < 130 * 24:
            drift = 1.0007
        elif i < 210 * 24:
            drift = 0.9994
        else:
            drift = 1.00045 if i % 72 < 48 else 0.9998
        price = max(30.0, price * drift)
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
                price * 1.003,
                price * 0.997,
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
    for i in range(320 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 50.0,
                "funding_rate": 0.00002 + ((i % 96) - 48) * 0.0000004,
                "long_short_ratio": 1.0 + ((i % 144) - 72) / 900.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
