from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.research.intraday_ga_strategy_mining import (
    COST_SCENARIOS,
    FEATURE_NAMES,
    IntradayGAMiningError,
    IntradayGenome,
    build_feature_frame,
    load_data_manifest,
    load_manifest_bounded_market_frame,
    run_btc_intraday_ga_strategy_mining,
    run_intraday_ga_interval,
    signal_from_genome,
    simulate_next_open_execution,
)


UTC = timezone.utc


def test_manifest_bounded_loader_is_read_only_and_rejects_row_count_drift(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    frame = _market_frame("5m", 600)
    _write_market_db(db, {"5m": frame})
    manifest_path = _write_manifest(tmp_path / "5m.json", "5m", frame)
    before = db.stat().st_mtime_ns

    manifest = load_data_manifest(manifest_path)
    loaded, provenance = load_manifest_bounded_market_frame(db_path=db, manifest=manifest)

    assert len(loaded) == 600
    assert provenance["physical_access_mode"] == "sqlite_uri_mode_ro_query_only"
    assert provenance["irregular_step_count"] == 0
    assert db.stat().st_mtime_ns == before

    manifest["row_count"] = 601
    with pytest.raises(IntradayGAMiningError, match="manifest_bounded_row_count_mismatch"):
        load_manifest_bounded_market_frame(db_path=db, manifest=manifest)


def test_features_and_signal_do_not_change_when_only_future_rows_change() -> None:
    frame = _market_frame("5m", 900)
    genome = _trend_genome()
    base_features = build_feature_frame(frame)
    base_signal = signal_from_genome(genome, base_features)
    cutoff = 650
    mutated = frame.copy()
    mutated.iloc[cutoff + 1 :, mutated.columns.get_loc("close")] *= 1.25
    mutated.iloc[cutoff + 1 :, mutated.columns.get_loc("high")] *= 1.25
    mutated.iloc[cutoff + 1 :, mutated.columns.get_loc("low")] *= 1.25
    mutated_features = build_feature_frame(mutated)
    mutated_signal = signal_from_genome(genome, mutated_features)

    pd.testing.assert_frame_equal(base_features.iloc[: cutoff + 1], mutated_features.iloc[: cutoff + 1])
    pd.testing.assert_series_equal(base_signal.iloc[: cutoff + 1], mutated_signal.iloc[: cutoff + 1])


def test_execution_is_next_open_and_pnl_reconciles_from_fill_position_cash_ledgers() -> None:
    index = pd.date_range("2026-01-01", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time_ms": [int(item.timestamp() * 1000) for item in index],
            "open": [100.0, 100.0, 110.0, 110.0, 110.0, 110.0],
            "high": [101.0, 101.0, 111.0, 111.0, 111.0, 111.0],
            "low": [99.0, 99.0, 109.0, 109.0, 109.0, 109.0],
            "close": [100.0, 100.0, 110.0, 110.0, 110.0, 110.0],
            "volume": [1.0] * 6,
        },
        index=index,
    )
    target = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 0.0], index=index)

    metrics, ledger = simulate_next_open_execution(
        frame=frame,
        target_at_close=target,
        interval="5m",
        cost_config=COST_SCENARIOS["base"],
    )

    assert ledger["pnl_derived_from_fills_positions_cash"] is True
    assert ledger["reconciled"] is True
    assert ledger["fill_samples_first"][0]["execution_time"] == index[1].isoformat()
    assert ledger["fill_samples_first"][0]["side"] == "BUY"
    assert ledger["fill_samples_first"][-1]["side"] == "SELL"
    assert metrics.total_return > 0.09
    assert metrics.trade_count == 1


def test_fixed_seed_ga_is_reproducible_and_holdout_is_not_used_for_selection() -> None:
    frame = _market_frame("15m", 6_400)
    provenance = _provenance("15m", frame)

    first = run_intraday_ga_interval(
        interval="15m",
        frame=frame,
        provenance=provenance,
        seed=17,
        population_size=10,
        generations=3,
        max_candidates=4,
    )
    second = run_intraday_ga_interval(
        interval="15m",
        frame=frame,
        provenance=provenance,
        seed=17,
        population_size=10,
        generations=3,
        max_candidates=4,
    )

    assert [row["genome_hash"] for row in first["top_candidates"]] == [
        row["genome_hash"] for row in second["top_candidates"]
    ]
    assert first["split_policy"]["confirmatory_holdout_used_for_selection"] is False
    assert all(
        row["confirmatory_holdout"]["selection_used_holdout"] is False for row in first["top_candidates"]
    )
    assert first["ga_config"]["trial_count"] == 30


def test_combined_5m_15m_report_remains_research_only_and_fail_closed(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    frames = {"5m": _market_frame("5m", 6_400), "15m": _market_frame("15m", 6_400)}
    _write_market_db(db, frames)
    manifests = {
        interval: _write_manifest(tmp_path / f"{interval}.json", interval, frame)
        for interval, frame in frames.items()
    }

    report = run_btc_intraday_ga_strategy_mining(
        market_db_path=db,
        manifest_paths=manifests,
        output_root=tmp_path / "out",
        population_size=8,
        generations=2,
        max_candidates=3,
        seed=29,
        search_round_count=3,
        holdout_viewed_during_engine_refinement=True,
        generated_at_utc=datetime(2026, 8, 26, tzinfo=UTC),
    )

    assert validate_btc_artifact_schema(report) == []
    assert set(report["interval_results"]) == {"5m", "15m"}
    assert report["decision"] == "research_only_genetic_candidates_require_independent_review"
    assert report["promotion"]["demo_strategy_registration_allowed"] is False
    assert report["promotion"]["paper_candidate_generated"] is False
    assert report["promotion"]["live_enabled"] is False
    assert report["safety"]["public_network_called"] is False
    assert report["safety"]["private_endpoints_allowed"] is False
    assert report["safety"]["order_endpoints_allowed"] is False
    assert report["safety"]["real_orders_created"] is False
    assert report["search_protocol"]["search_round_count"] == 3
    assert report["search_protocol"]["tail_holdout_viewed_during_engine_refinement"] is True
    assert "btc_intraday_ga_tail_holdout_viewed_during_engine_refinement" in report["blockers"]
    assert (tmp_path / "out" / "btc_intraday_ga_strategy_mining_report.json").exists()
    assert (tmp_path / "out" / "btc_intraday_ga_candidate_definitions.json").exists()
    assert (tmp_path / "out" / "btc_intraday_ga_strategy_mining_summary_cn.md").exists()


def _trend_genome() -> IntradayGenome:
    weights = tuple(
        2 if name == "ema_spread_13_55" else 1 if name == "momentum_12" else 0
        for name in FEATURE_NAMES
    )
    return IntradayGenome(weights=weights, entry_threshold=0.15, smoothing_bars=2)


def _market_frame(interval: str, rows: int) -> pd.DataFrame:
    minutes = 5 if interval == "5m" else 15
    index = pd.date_range("2024-01-01", periods=rows, freq=f"{minutes}min", tz="UTC")
    x = np.arange(rows, dtype=float)
    cyclical = np.sin(x / 41.0) * 180.0 + np.sin(x / 211.0) * 420.0
    drift = x * (0.12 if interval == "5m" else 0.35)
    close = 42_000.0 + drift + cyclical
    open_ = close - np.sin(x / 13.0) * 22.0
    high = np.maximum(open_, close) + 35.0 + np.abs(np.sin(x / 17.0)) * 20.0
    low = np.minimum(open_, close) - 35.0 - np.abs(np.cos(x / 17.0)) * 20.0
    volume = 100.0 + (np.sin(x / 19.0) + 1.5) * 25.0
    return pd.DataFrame(
        {
            "open_time_ms": [int(item.timestamp() * 1000) for item in index],
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


def _write_market_db(path: Path, frames: dict[str, pd.DataFrame]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE market_klines (
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time_ms INTEGER NOT NULL,
                open_time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL
            )
            """
        )
        rows = []
        for interval, frame in frames.items():
            rows.extend(
                (
                    "binance_spot",
                    "BTCUSDT",
                    interval,
                    int(row.open_time_ms),
                    timestamp.isoformat(),
                    float(row.open),
                    float(row.high),
                    float(row.low),
                    float(row.close),
                    float(row.volume),
                )
                for timestamp, row in frame.iterrows()
            )
        connection.executemany("INSERT INTO market_klines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.commit()


def _write_manifest(path: Path, interval: str, frame: pd.DataFrame) -> Path:
    payload = {
        "data_version": f"fixture-BTCUSDT-{interval}-{len(frame)}",
        "symbol": "BTCUSDT",
        "interval": interval,
        "start": frame.index[0].isoformat(),
        "end": frame.index[-1].isoformat(),
        "row_count": len(frame),
        "checksum": ("a" if interval == "5m" else "b") * 64,
        "source": "fixture",
        "universe_id": "binance_spot:BTCUSDT",
        "timezone": "UTC",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _provenance(interval: str, frame: pd.DataFrame) -> dict[str, object]:
    return {
        "data_version": f"fixture-{interval}",
        "manifest_checksum": "a" * 64,
        "manifest_interval": interval,
        "manifest_start": frame.index[0].isoformat(),
        "manifest_end": frame.index[-1].isoformat(),
        "manifest_row_count": len(frame),
        "resolved_row_count": len(frame),
        "irregular_step_count": 0,
        "invalid_ohlcv_row_count": 0,
        "resolved_slice_sha256": "b" * 64,
    }
