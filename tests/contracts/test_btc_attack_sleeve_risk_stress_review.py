from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import btc_attack_sleeve_risk_stress_review as stress


def test_liquidation_threshold_and_short_adverse_move_are_mark_sensitive() -> None:
    base = stress._liquidation_threshold(10.0, maintenance_margin_rate=0.005, liquidation_fee_rate=0.003, mark_adverse_offset_bps=0.0)
    marked = stress._liquidation_threshold(10.0, maintenance_margin_rate=0.005, liquidation_fee_rate=0.003, mark_adverse_offset_bps=200.0)
    assert marked < base
    assert round(stress._execution_adverse_move(high=110.0, low=99.0, entry_close=100.0, side=-1.0), 10) == 0.1
    assert round(stress._execution_adverse_move(high=101.0, low=90.0, entry_close=100.0, side=1.0), 10) == 0.1


def test_attack_sleeve_risk_stress_outputs_research_only_strict_matrix(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    high_report = tmp_path / "high_report.json"
    high_watchlist = tmp_path / "high_watchlist.csv"
    pyramiding_csv = tmp_path / "pyramiding.csv"
    _write_market_db(db)
    _write_derivatives(derivatives)
    scenario = _small_high_scenario()
    monkeypatch.setattr(stress.high_octane, "_scenario_grid", lambda: [scenario])
    monkeypatch.setattr(stress.pyramiding, "_scenario_grid", lambda: [])
    monkeypatch.setattr(stress, "_frozen_v3_direction", _always_long_direction)
    _write_json(high_report, {"summary": {"best_scenario_id": scenario.scenario_id, "best_min_remaining_after_10pct_spike": 40.011869}})
    _write_csv(
        high_watchlist,
        [
            {
                "scenario_id": scenario.scenario_id,
                "annual_return_pct": "100",
                "min_remaining_capital_pct_after_10pct_spike": "40.011869",
            }
        ],
    )
    _write_csv(pyramiding_csv, [])

    report = stress.build_btc_attack_sleeve_risk_stress_review(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        high_octane_report_path=high_report,
        high_octane_watchlist_path=high_watchlist,
        pyramiding_actual_attack_path=pyramiding_csv,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_attack_sleeve_risk_stress_review_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "not_forward_observation_ready_research_only_no_paper_no_live"
    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["policy_count"] == 10
    assert report["summary"]["matrix_row_count"] == 10
    assert report["summary"]["strict_next_bar_execution"] is True
    assert report["summary"]["same_bar_profit_allowed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    policy_ids = {row["policy_id"] for row in report["top_risk_rows"]}
    assert {"funding_2x_adverse", "funding_5x_adverse", "slippage_5x", "taker_fee_2x", "combined_adverse_5x"} <= policy_ids
    for row in report["top_risk_rows"]:
        assert float(row["max_template_leverage"]) <= 10.0
        assert int(row["max_concurrent_exposed_sleeves_observed"]) <= int(row["max_policy_exposed"])
        assert row["paper_queue_write_allowed"] is False
        assert row["live_unlock_allowed"] is False

    base = next(row for row in report["top_risk_rows"] if row["policy_id"] == "base_strict_next_bar")
    funding5 = next(row for row in report["top_risk_rows"] if row["policy_id"] == "funding_5x_adverse")
    assert float(funding5["funding_cost_amount"]) >= float(base["funding_cost_amount"])

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    for name in [
        "btc_attack_sleeve_risk_stress_review_report.json",
        "btc_attack_sleeve_risk_stress_review_matrix.csv",
        "btc_attack_sleeve_risk_stress_review_events.csv",
        "btc_attack_sleeve_risk_stress_review_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()


def test_isolated_sleeve_liquidation_preserves_extracted_reserve() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC")
    bars = pd.DataFrame(
        {
            "open": [100.0, 112.0, 112.0, 80.0],
            "high": [101.0, 113.0, 113.0, 81.0],
            "low": [99.0, 111.0, 70.0, 79.0],
            "close": [100.0, 112.0, 80.0, 80.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )
    market = {"bars_4h": bars, "derivatives_4h": pd.DataFrame({"funding_rate": [0.0, 0.0, 0.0, 0.0]}, index=index)}
    direction = pd.Series(1.0, index=index)
    candidate = stress.StressCandidate(
        source_line="unit",
        scenario_id="extract_then_liquidate",
        templates=tuple(stress.PyramidTemplate("attack", 10.0, 0, 0.0) for _ in range(10)),
        max_total_exposed=10,
        max_attack_exposed=10,
        extract_policy="extract_on_double",
        reserve_requires_pullback=False,
        atr_step=0.0,
        source_rank=1,
    )
    result = stress._simulate_strict_sleeve_stress(
        candidate,
        policy=stress.SleeveRiskPolicy("unit"),
        market=market,
        direction=direction,
        initial_capital=1_000.0,
        base_cost_bps=0.0,
        collect_events=True,
    )

    assert result.metrics["extract_count"] > 0
    assert result.metrics["normal_liquidation_count"] > 0
    assert result.metrics["reserve_cash"] > 0.0
    assert any(event["event_type"] == "normal_liquidation" for event in result.events)


def _small_high_scenario() -> stress.high_octane.HighOctaneScenario:
    return stress.high_octane.HighOctaneScenario(
        scenario_id="ho_test_step0p35_core5x5_reserve3x4_attack10x1_cap1_max7_delayearly_none",
        policy_id="high_octane_atr_pyramiding_attack_sleeve",
        sleeve_templates=(
            tuple(stress.PyramidTemplate("core", 5.0, i % 2, 0.0) for i in range(5))
            + tuple(stress.PyramidTemplate("reserve", 3.0, 2 + i, 0.0) for i in range(4))
            + (stress.PyramidTemplate("attack", 10.0, 0, 0.0),)
        ),
        max_total_exposed=7,
        max_attack_exposed=1,
        extract_policy="none",
        reserve_requires_pullback=False,
        atr_step=0.35,
        attack_delay_profile="early",
    )


def _always_long_direction(market, *, initial_capital: float, base_cost_bps: float) -> pd.Series:
    return pd.Series(1.0, index=market["bars_4h"].index, dtype=float)


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
    for i in range(120 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        price *= 1.0008
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
                price * 1.002,
                price * 0.998,
                price,
                100.0,
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(120 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "funding_rate": 0.00002,
                "open_interest_usd": 1_000_000.0,
                "long_short_ratio": 1.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
