from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.weak_regime_short_lab import (
    build_btc_weak_regime_short_lab,
    weak_regime_short_specs,
)


def test_weak_regime_short_specs_are_research_only_buckets() -> None:
    specs = weak_regime_short_specs()
    assert {spec.direction_policy for spec in specs} >= {"short_flat", "long_short", "long_flat"}
    assert any(spec.instrument_assumption == "simulated_usdt_perpetual_research_only" for spec in specs)
    assert any(spec.instrument_assumption == "spot_research_only" for spec in specs)
    assert all("live" not in spec.variant_id for spec in specs)


def test_weak_regime_short_lab_is_research_only(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, mode="mixed")
    _write_derivatives(derivatives)

    report = build_btc_weak_regime_short_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_weak_regime_short_lab_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["private_exchange_endpoint_used"] is False
    assert report["validation_design"]["funding_model"]["research_approximation"] is True
    assert report["validation_design"]["candidate_count"] == len(weak_regime_short_specs())
    assert all(row["paper_queue_write_allowed"] is False for row in report["comparison_rows"])
    assert all(row["branch"] == "short_research" for row in report["short_research_rows"])
    assert all(row["branch"] == "spot_defensive_research" for row in report["spot_defensive_rows"])
    assert (tmp_path / "out" / "btc_weak_regime_short_lab_report.json").exists()
    assert (tmp_path / "out" / "btc_weak_regime_short_lab_grid.csv").exists()
    assert (tmp_path / "out" / "btc_weak_regime_short_lab_summary_cn.md").exists()


def test_downtrend_short_research_can_profit_while_buy_hold_loses(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, mode="downtrend")
    _write_derivatives(derivatives)

    report = build_btc_weak_regime_short_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    buy_hold_return = report["baselines"]["buy_hold_spot"]["total_return_pct"]
    best_short_return = max(row["total_return_pct"] for row in report["short_research_rows"])
    assert buy_hold_return < 0.0
    assert best_short_return > 0.0
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_short_report_contains_squeeze_and_liquidation_diagnostics(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    _write_market_db(db, mode="mixed")
    _write_derivatives(derivatives)

    report = build_btc_weak_regime_short_lab(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    row = report["short_research_rows"][0]
    diagnostics = row["short_squeeze_liquidation_diagnostics"]
    assert "max_short_intrabar_adverse_pct" in diagnostics
    assert "hypothetical_liquidation_checks" in diagnostics
    assert diagnostics["research_approximation"] is True


def _write_market_db(path: Path, *, mode: str) -> None:
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
        if mode == "downtrend":
            drift = 0.99945
        else:
            drift = 1.00025 if i < 80 * 24 else (0.99935 if i < 190 * 24 else 1.00005)
        cycle = ((i % 48) - 24) / 24.0
        price = max(10.0, price * drift * (1.0 + 0.0007 * cycle))
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.996,
                price * 1.014,
                price * 0.986,
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
    for i in range(240 * 6):
        event_time = start + timedelta(hours=4 * i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000_000.0 + i * 1_000_000.0,
                "funding_rate": 0.00005 if i % 5 else -0.00003,
                "long_short_ratio": 1.0 + ((i % 20) - 10) * 0.01,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
