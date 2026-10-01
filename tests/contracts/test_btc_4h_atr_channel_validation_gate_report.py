from __future__ import annotations

import csv
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.build_btc_4h_atr_channel_validation_gate_report import (
    DEFAULT_PARAMS,
    FAMILY_ID,
    INTERVAL,
    VARIANT_ID,
    CandidateSpec,
    build_btc_4h_atr_channel_validation_gate_report,
)


def test_4h_atr_validation_gate_passes_research_only_with_fixed_candidate(tmp_path: Path) -> None:
    db_path = _write_4h_sqlite(tmp_path, rows=5200)
    candidate_id = CandidateSpec(INTERVAL, FAMILY_ID, VARIANT_ID, "4h ATR channel breakout", dict(DEFAULT_PARAMS)).candidate_id
    report = _write_intraday_report(tmp_path, candidate_id=candidate_id)
    ledger = _write_ledger(tmp_path, candidate_id=candidate_id, lookahead_pass=True)

    payload = build_btc_4h_atr_channel_validation_gate_report(
        repo_root=tmp_path,
        intraday_report=report,
        db_path=db_path,
        ledger_path=ledger,
        output=tmp_path / "gate.json",
        walk_forward_output=tmp_path / "walk.csv",
        regime_output=tmp_path / "regime.csv",
        parameter_output=tmp_path / "params.csv",
        markdown_output=tmp_path / "gate.md",
        generated_at="2026-06-24T00:00:00Z",
    )

    assert payload["status"] == "research_validation_passed_manual_review_required"
    assert payload["candidate_id"] == candidate_id
    assert payload["validation_checks"]["selected_candidate_fixed"] is True
    assert payload["validation_checks"]["ledger_t_plus_one_pass"] is True
    assert payload["guardrails"]["paper_runner_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["walk_forward"]["row_count"] == 4
    assert payload["parameter_stability"]["row_count"] == 36
    assert {float(row["cost_bps"]) for row in payload["cost_stress"]} == {5.0, 10.0, 25.0, 50.0, 100.0}
    assert (tmp_path / "gate.md").exists()


def test_4h_atr_validation_gate_blocks_candidate_mismatch(tmp_path: Path) -> None:
    db_path = _write_4h_sqlite(tmp_path, rows=1200)
    report = _write_intraday_report(tmp_path, candidate_id="wrong_candidate")
    ledger = _write_ledger(tmp_path, candidate_id="wrong_candidate", lookahead_pass=True)

    payload = build_btc_4h_atr_channel_validation_gate_report(
        repo_root=tmp_path,
        intraday_report=report,
        db_path=db_path,
        ledger_path=ledger,
        output=tmp_path / "gate.json",
        walk_forward_output=tmp_path / "walk.csv",
        regime_output=tmp_path / "regime.csv",
        parameter_output=tmp_path / "params.csv",
        markdown_output=tmp_path / "gate.md",
        generated_at="2026-06-24T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert "btc_4h_atr_selected_candidate_mismatch" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_4h_atr_validation_gate_blocks_lookahead_ledger(tmp_path: Path) -> None:
    db_path = _write_4h_sqlite(tmp_path, rows=1200)
    candidate_id = CandidateSpec(INTERVAL, FAMILY_ID, VARIANT_ID, "4h ATR channel breakout", dict(DEFAULT_PARAMS)).candidate_id
    report = _write_intraday_report(tmp_path, candidate_id=candidate_id)
    ledger = _write_ledger(tmp_path, candidate_id=candidate_id, lookahead_pass=False)

    payload = build_btc_4h_atr_channel_validation_gate_report(
        repo_root=tmp_path,
        intraday_report=report,
        db_path=db_path,
        ledger_path=ledger,
        output=tmp_path / "gate.json",
        walk_forward_output=tmp_path / "walk.csv",
        regime_output=tmp_path / "regime.csv",
        parameter_output=tmp_path / "params.csv",
        markdown_output=tmp_path / "gate.md",
        generated_at="2026-06-24T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert "btc_4h_atr_position_ledger_lookahead_failed" in payload["blockers"]


def _write_intraday_report(tmp_path: Path, *, candidate_id: str) -> Path:
    path = tmp_path / "intraday.json"
    path.write_text(
        json.dumps(
            {
                "status": "research_only_intraday_trend_v1_complete",
                "selected_candidates": [{"interval": "4h", "candidate_id": candidate_id}],
                "guardrails": {
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "live_order_allowed": False,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_ledger(tmp_path: Path, *, candidate_id: str, lookahead_pass: bool) -> Path:
    path = tmp_path / "ledger.csv"
    rows = [
        {
            "timestamp": "2024-01-01T04:00:00Z",
            "candidate_id": candidate_id,
            "signal_timestamp": "2024-01-01T00:00:00Z" if lookahead_pass else "2024-01-01T04:00:00Z",
            "effective_timestamp": "2024-01-01T04:00:00Z",
            "turnover": "1.0",
            "reason": "exposure_changed_from_prior_effective_signal",
        }
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_4h_sqlite(tmp_path: Path, *, rows: int) -> Path:
    db_path = tmp_path / "market_data.sqlite"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            create table market_klines (
                exchange text,
                symbol text,
                interval text,
                open_time_ms integer,
                open_time text,
                close_time_ms integer,
                close_time text,
                open real,
                high real,
                low real,
                close real,
                volume real,
                quote_volume real,
                trade_count integer
            )
            """
        )
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        batch = []
        for i in range(rows):
            ts = start + timedelta(hours=4 * i)
            close = 40_000 + i * 15 + 800 * math.sin(i / 30)
            open_ = close * 0.999
            high = close * 1.004
            low = close * 0.996
            close_ts = ts + timedelta(hours=4)
            batch.append(
                (
                    "binance_spot",
                    "BTCUSDT",
                    "4h",
                    int(ts.timestamp() * 1000),
                    ts.isoformat().replace("+00:00", "Z"),
                    int(close_ts.timestamp() * 1000),
                    close_ts.isoformat().replace("+00:00", "Z"),
                    open_,
                    high,
                    low,
                    close,
                    100 + i % 13,
                    close * (100 + i % 13),
                    100,
                )
            )
        con.executemany(
            """
            insert into market_klines (
                exchange, symbol, interval, open_time_ms, open_time, close_time_ms,
                close_time, open, high, low, close, volume, quote_volume, trade_count
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
    return db_path
