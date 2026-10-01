from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_crypto.research.ga_rule_component_mining import (
    REQUIRED_RULE_SOURCE_FAMILIES,
    RuleCondition,
    RuleGenome,
    build_btc_ga_rule_component_mining,
    build_rule_primitive_frame,
    evaluate_genome,
    rule_primitive_catalog,
    validate_genome,
)
from quant_crypto.research.simple_trend_rule_lab import aggregate_ohlcv, align_derivatives_to_index, load_market_1h


def test_rule_primitive_catalog_covers_all_mentioned_rule_families() -> None:
    catalog = rule_primitive_catalog()
    covered = set().union(*(item.source_rules for item in catalog))

    assert REQUIRED_RULE_SOURCE_FAMILIES <= covered
    assert any(item.kind == "entry_numeric" and item.threshold_grid for item in catalog)
    assert any(item.kind == "exit_signal" for item in catalog)
    assert {item.primitive_id for item in catalog} >= {
        "ema_ribbon_long_13_34_89",
        "donchian_breakout_w180",
        "atr_channel_breakout_k1p2",
        "exit_failed_breakout_12",
    }


def test_genome_rejects_unknown_primitive() -> None:
    genome = RuleGenome(
        entry_conditions=(RuleCondition("unknown_python_exec", "gt", 0.5),),
        vote_threshold=1,
        exit_conditions=(RuleCondition("exit_close_below_ema50", "gt", 0.5),),
        exit_vote_threshold=1,
    )

    with pytest.raises(ValueError, match="primitive_not_allowed"):
        validate_genome(genome)


def test_primitive_frame_contains_catalog_columns_and_uses_visible_derivatives(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    derivatives_4h = align_derivatives_to_index(derivatives, bars_4h.index)

    frame, catalog = build_rule_primitive_frame(source_1h, bars_4h, bars_1d, derivatives_4h)

    assert set(item.primitive_id for item in catalog) <= set(frame.columns)
    first_decision = derivatives_4h.index[0]
    assert first_decision <= bars_4h.index[0]


def test_genome_exposure_is_shifted_to_next_4h_bar(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    derivatives_4h = align_derivatives_to_index(derivatives, bars_4h.index)
    frame, _ = build_rule_primitive_frame(source_1h, bars_4h, bars_1d, derivatives_4h)
    genome = RuleGenome(
        entry_conditions=(
            RuleCondition("daily_ema50_gt_200", "gt", 0.5),
            RuleCondition("ema_ribbon_4h_long", "gt", 0.5),
            RuleCondition("vol_not_extreme_60", "gt", 0.5),
        ),
        vote_threshold=2,
        exit_conditions=(RuleCondition("exit_close_below_ema100", "gt", 0.5),),
        exit_vote_threshold=1,
    )

    evaluated = evaluate_genome(genome, primitive_frame=frame, bars_4h=bars_4h, initial_capital=25_000.0, cost_bps=10.0)

    assert evaluated.exposure.equals(evaluated.raw_signal.shift(1).fillna(0.0))


def test_regime_router_genome_is_valid_and_research_only(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    source_1h = load_market_1h(db)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    derivatives_4h = align_derivatives_to_index(derivatives, bars_4h.index)
    frame, catalog = build_rule_primitive_frame(source_1h, bars_4h, bars_1d, derivatives_4h)
    child = RuleGenome(
        entry_conditions=(RuleCondition("ema_ribbon_4h_long", "gt", 0.5), RuleCondition("vol_not_extreme_60", "gt", 0.5)),
        vote_threshold=1,
        exit_conditions=(RuleCondition("exit_close_below_ema100", "gt", 0.5),),
        exit_vote_threshold=1,
        cooldown_bars=6,
    )
    cash = RuleGenome(
        entry_conditions=(RuleCondition("daily_ema50_gt_200", "gt", 2.0),),
        vote_threshold=1,
        exit_conditions=(RuleCondition("exit_daily_bear", "gt", 0.5),),
        exit_vote_threshold=1,
    )
    router = RuleGenome(
        entry_conditions=(),
        vote_threshold=0,
        exit_conditions=(),
        exit_vote_threshold=0,
        genome_type="regime_router",
        regime_rules=(
            ("bull_trend", child),
            ("sideways", child),
            ("high_volatility", cash),
            ("bear_risk", cash),
        ),
    )

    validate_genome(router, primitive_catalog=catalog)
    evaluated = evaluate_genome(router, primitive_frame=frame, bars_4h=bars_4h, initial_capital=25_000.0, cost_bps=10.0)

    assert set(evaluated.raw_signal.dropna().unique()) <= {0.0, 1.0}
    assert evaluated.exposure.max() <= 1.0


def test_ga_rule_component_report_is_research_only_and_compares_baselines(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    report = build_btc_ga_rule_component_mining(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
        seed=7,
        population_size=12,
        generations=3,
        selected_candidate_count=5,
    )

    assert report["schema_version"] == "btc_ga_rule_component_mining_v2"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_ga_rule_component_mining_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["ga_config"]["run_profile"] == "smoke"
    assert report["ga_config"]["trial_count"] == 36
    assert isinstance(report["ga_config"]["rejected_count"], int)
    assert report["ga_config"]["seeded_genome_count"] > 0
    assert report["handwritten_rule_baseline_comparison"]["baseline_count"] > 50
    assert report["handwritten_rule_baseline_comparison"]["top_handwritten_baselines"]
    assert all(row["same_validation_window"] is True for row in report["handwritten_rule_baseline_comparison"]["top_handwritten_baselines"])
    assert all(row["paper_queue_write_allowed"] is False for row in report["candidate_rule_genomes"])
    assert report["position_sizing_diagnostics"]["scope"] == "diagnostic_only_not_used_for_main_shortlist"
    assert report["position_sizing_diagnostics"]["paper_queue_write_allowed"] is False
    assert (tmp_path / "out" / "ga_rule_component_mining_report.json").exists()
    assert (tmp_path / "out" / "candidate_rule_genomes.json").exists()
    markdown = (tmp_path / "out" / "ga_rule_component_mining_summary_cn.md").read_text(encoding="utf-8")
    assert "手写规则基线" in markdown
    assert "仓位缩放只用于观察风险形态" in markdown


def test_fixed_seed_reproducible(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db)
    _write_derivatives(derivatives)

    first = build_btc_ga_rule_component_mining(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out1",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
        seed=11,
        population_size=10,
        generations=2,
        selected_candidate_count=4,
    )
    second = build_btc_ga_rule_component_mining(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out2",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
        seed=11,
        population_size=10,
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
    for i in range(240 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        cycle = (i % 720) / 720.0
        drift = 1.0004 + 0.001 * cycle
        if 240 * 24 * 0.55 < i < 240 * 24 * 0.66:
            drift = 0.999
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
    for i in range(240 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 100.0 + (i % 48) * 75.0,
                "funding_rate": 0.00008 + (i % 72) * 0.000001,
                "long_short_ratio": 1.0 + (i % 96) / 400.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
