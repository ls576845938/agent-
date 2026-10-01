from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import high_octane_attack_sleeve_lab as lab
from quant_crypto.research import pyramiding_sleeve_lab as defensive_lab


def test_high_octane_grid_has_declared_attack_parameters_without_touching_defensive_v1() -> None:
    scenarios = lab._scenario_grid()
    assert defensive_lab.SCHEMA_VERSION == "btc_pyramiding_sleeve_lab_v1"
    assert str(defensive_lab.DEFAULT_OUTPUT_DIR).replace("\\", "/") == "artifacts/btc_pyramiding_sleeve_lab/latest"
    assert {scenario.atr_step for scenario in scenarios} == {0.35, 0.5, 0.75}
    assert {scenario.max_attack_exposed for scenario in scenarios} == {1, 2, 3}
    assert {sum(1 for template in scenario.sleeve_templates if template.role == "attack") for scenario in scenarios} == {1, 2, 3}
    assert {scenario.extract_policy for scenario in scenarios} == {"none", "extract_on_double", "extract_on_triple"}
    assert max(max(template.leverage for template in scenario.sleeve_templates) for scenario in scenarios) <= 10.0


def test_high_octane_lab_outputs_research_only_tiered_watchlist_and_rolling_start(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    monkeypatch.setattr(lab, "_scenario_grid", _small_scenario_grid)
    monkeypatch.setattr(lab, "ROLLING_PRELIST_LIMIT", 2)
    monkeypatch.setattr(lab, "_frozen_v3_direction", _always_long_direction)

    report = lab.build_btc_high_octane_attack_sleeve_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_high_octane_attack_sleeve_lab_v2"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_high_octane_attack_sleeve_lab_research_only_no_paper_no_live"
    assert report["research_design"]["scenario_count"] == 2
    assert report["research_design"]["watchlist_tiers"]["survive_40pct"]["max_drawdown"] == 70.0
    assert report["research_design"]["watchlist_tiers"]["survive_50pct"]["max_drawdown"] == 60.0
    assert report["research_design"]["watchlist_tiers"]["survive_60pct"]["max_drawdown"] == 50.0
    assert report["research_design"]["normal_liquidation_policy"] == "allowed_but_recorded_and_penalized_in_ranking"
    assert report["summary"]["rolling_start_row_count"] >= 2
    assert report["summary"]["watchlist_count"] >= 1
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    top = report["top_watchlist"][0]
    assert top["watchlist_decision"] == "retain_high_octane_attack_research_watchlist_only"
    assert top["watchlist_tier"] in {"survive_40pct", "survive_50pct", "survive_60pct"}
    assert top["actual_attack_used"] is True
    assert "rolling_median_total_return_pct" in top
    assert "rolling_full_wipeout_rate" in top
    assert "normal_liquidation_count" in top

    for row in report["grid_rows_sample"]:
        assert float(row["max_template_leverage"]) <= 10.0
        assert row["paper_queue_write_allowed"] is False
        assert row["paper_candidate_created"] is False
        assert row["live_unlock_allowed"] is False

    for name in [
        "btc_high_octane_attack_sleeve_lab_grid.csv",
        "btc_high_octane_attack_sleeve_lab_prelist.csv",
        "btc_high_octane_attack_sleeve_lab_rolling_start.csv",
        "btc_high_octane_attack_sleeve_lab_watchlist.csv",
        "btc_high_octane_attack_sleeve_lab_events.csv",
        "btc_high_octane_attack_sleeve_lab_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def test_high_octane_final_rank_prioritizes_return_before_drawdown() -> None:
    high_return_high_drawdown = {
        "watchlist_decision": "retain_high_octane_attack_research_watchlist_only",
        "annual_return_pct": 500.0,
        "total_return_pct": 5000.0,
        "rolling_median_total_return_pct": 800.0,
        "rolling_full_wipeout_rate": 0.0,
        "min_remaining_capital_pct_after_10pct_spike": 45.0,
        "max_drawdown_abs_pct": 65.0,
        "scenario_id": "high_return",
    }
    low_return_low_drawdown = {
        **high_return_high_drawdown,
        "annual_return_pct": 150.0,
        "total_return_pct": 700.0,
        "rolling_median_total_return_pct": 200.0,
        "min_remaining_capital_pct_after_10pct_spike": 90.0,
        "max_drawdown_abs_pct": 5.0,
        "scenario_id": "low_drawdown",
    }
    ranked = sorted([low_return_low_drawdown, high_return_high_drawdown], key=lab._final_rank_key)
    assert ranked[0]["scenario_id"] == "high_return"


def _small_scenario_grid() -> list[lab.HighOctaneScenario]:
    return [
        lab.HighOctaneScenario(
            scenario_id="ho_contract_step0p35_core5x5_reserve3x4_attack10x1_cap1_max7_delayearly_extract_on_double",
            policy_id="high_octane_atr_pyramiding_attack_sleeve",
            sleeve_templates=(
                tuple(lab.PyramidTemplate("core", 5.0, i % 2, 0.0) for i in range(5))
                + tuple(lab.PyramidTemplate("reserve", 3.0, 2 + i, 0.0) for i in range(4))
                + tuple(lab.PyramidTemplate("attack", 10.0, 0, 0.0) for _ in range(1))
            ),
            max_total_exposed=7,
            max_attack_exposed=1,
            extract_policy="extract_on_double",
            reserve_requires_pullback=False,
            atr_step=0.35,
            attack_delay_profile="early",
        ),
        lab.HighOctaneScenario(
            scenario_id="ho_contract_step0p5_core5x6_reserve5x2_attack10x2_cap2_max8_delaylate_extract_on_triple",
            policy_id="high_octane_atr_pyramiding_attack_sleeve",
            sleeve_templates=(
                tuple(lab.PyramidTemplate("core", 5.0, i % 2, 0.0) for i in range(6))
                + tuple(lab.PyramidTemplate("reserve", 5.0, 4 + i, 0.0) for i in range(2))
                + tuple(lab.PyramidTemplate("attack", 10.0, 6 + i, 0.0) for i in range(2))
            ),
            max_total_exposed=8,
            max_attack_exposed=2,
            extract_policy="extract_on_triple",
            reserve_requires_pullback=False,
            atr_step=0.5,
            attack_delay_profile="late",
        ),
    ]


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
    for i in range(240 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        price *= 1.0009
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
                100.0 + (i % 24),
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(240 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 50.0,
                "funding_rate": 0.00001,
                "long_short_ratio": 1.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
