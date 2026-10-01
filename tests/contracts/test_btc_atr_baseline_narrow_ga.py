from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.atr_baseline_narrow_ga import (
    ATR_MULTIPLIER_GRID,
    EMA_MIDLINE_GRID,
    MAX_CONDITION_COUNT,
    AtrNarrowGenome,
    build_btc_atr_baseline_narrow_ga,
    evaluate_atr_genome,
)
from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv, load_market_1h


def test_atr_narrow_ga_report_is_research_only_and_locks_holdout(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = build_btc_atr_baseline_narrow_ga(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
        seed=13,
        run_profile="formal",
        population_size=10,
        generations=3,
        selected_candidate_count=5,
    )

    assert report["schema_version"] == "btc_atr_baseline_narrow_ga_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_atr_baseline_narrow_ga_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["ga_config"]["run_profile"] == "formal"
    assert report["ga_config"]["trial_count"] == 30
    assert isinstance(report["ga_config"]["rejected_count"], int)
    assert report["ga_config"]["seeded_genome_count"] > 0
    assert report["holdout_lock"]["locked_before_search"] is True
    assert report["holdout_lock"]["holdout_used_for_ga_evolution"] is False
    assert report["holdout_lock"]["holdout_used_for_candidate_ranking"] is False
    assert report["atr_handwritten_baseline_review"]["baseline_count"] == 4
    assert report["atr_handwritten_baseline_review"]["strongest_baseline"]
    assert all(row["holdout_used_for_selection"] is False for row in report["candidate_rule_genomes"])
    assert all(row["paper_queue_write_allowed"] is False for row in report["candidate_rule_genomes"])
    assert (tmp_path / "out" / "btc_atr_baseline_narrow_ga_report.json").exists()
    markdown = (tmp_path / "out" / "btc_atr_baseline_narrow_ga_summary_cn.md").read_text(encoding="utf-8")
    assert "确认性 holdout" in markdown


def test_narrow_genomes_stay_inside_predeclared_atr_space(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = build_btc_atr_baseline_narrow_ga(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        seed=21,
        population_size=8,
        generations=2,
        selected_candidate_count=8,
    )

    for row in report["candidate_rule_genomes"]:
        genome = row["genome"]
        assert genome["ma_window"] in EMA_MIDLINE_GRID
        assert genome["entry_k"] in ATR_MULTIPLIER_GRID
        assert genome["exit_k"] in ATR_MULTIPLIER_GRID
        assert genome["condition_count"] <= MAX_CONDITION_COUNT


def test_atr_genome_exposure_is_next_bar_only(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    _write_market_db(db)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    genome = AtrNarrowGenome(96, 1.5, "atr_channel", 1.5, 60, 12, 6)

    evaluated = evaluate_atr_genome(genome, bars_4h=bars_4h, bars_1d=bars_1d, initial_capital=25_000.0, cost_bps=10.0)

    assert evaluated.exposure.equals(evaluated.raw_signal.shift(1).fillna(0.0))


def test_fixed_seed_reproducible(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    first = build_btc_atr_baseline_narrow_ga(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out1",
        seed=99,
        population_size=8,
        generations=2,
        selected_candidate_count=4,
    )
    second = build_btc_atr_baseline_narrow_ga(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out2",
        seed=99,
        population_size=8,
        generations=2,
        selected_candidate_count=4,
    )

    assert [row["genome_hash"] for row in first["candidate_rule_genomes"]] == [
        row["genome_hash"] for row in second["candidate_rule_genomes"]
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
    for i in range(260 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        drift = 1.00045 + 0.0006 * ((i % 240) / 240.0)
        if 260 * 24 * 0.68 < i < 260 * 24 * 0.78:
            drift = 0.9992
        price = max(10.0, price * drift)
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.995,
                price * 1.012,
                price * 0.988,
                price,
                100.0 + (i % 24) * 2.0,
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
                "funding_rate": 0.00008 + (i % 72) * 0.000001,
                "long_short_ratio": 1.0 + (i % 96) / 400.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
