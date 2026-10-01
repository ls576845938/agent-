from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pandas as pd

from scripts.build_us_equity_ibkr_minute_coverage_report import (
    build_us_equity_ibkr_minute_coverage_report,
)


SCHEMA = Path("schemas/ibkr_minute_coverage_report.schema.json")


def test_ibkr_minute_coverage_report_finds_next_missing_date(tmp_path: Path) -> None:
    _write_chunk(tmp_path, "QQQ", "2026-01-01", "2026-01-02", rows=2)
    _write_chunk(tmp_path, "QQQ", "2026-01-04", "2026-01-04", rows=1)

    payload = build_us_equity_ibkr_minute_coverage_report(
        repo_root=tmp_path,
        symbols=["QQQ"],
        requested_start_date="2026-01-01",
        requested_end_date="2026-01-05",
        generated_at="2026-01-06T00:00:00Z",
    )

    report = payload["symbol_reports"]["QQQ"]
    assert payload["status"] == "partial"
    assert payload["research_ready_status"] == "blocked"
    assert payload["network_called"] is False
    assert report["next_missing_date"] == "2026-01-03"
    assert report["last_covered_date"] == "2026-01-04"
    assert "qqq_ibkr_minute_pit_adjustment_replay_required" in report["blockers"]
    assert payload["next_actions"][0]["symbol"] == "QQQ"

    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_ibkr_minute_coverage_report_keeps_complete_raw_blocked_for_pit_replay(tmp_path: Path) -> None:
    _write_chunk(tmp_path, "TQQQ", "2026-01-01", "2026-01-03", rows=3)

    payload = build_us_equity_ibkr_minute_coverage_report(
        repo_root=tmp_path,
        symbols=["TQQQ"],
        requested_start_date="2026-01-01",
        requested_end_date="2026-01-03",
        generated_at="2026-01-04T00:00:00Z",
    )

    report = payload["symbol_reports"]["TQQQ"]
    assert payload["status"] == "pass"
    assert payload["research_ready_status"] == "blocked"
    assert report["raw_data_status"] == "complete"
    assert report["next_missing_date"] is None
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["data_limitations"]["research_clean_approval_granted"] is False
    assert payload["adjustment_controls"]["back_adjusted_for_signal_use_allowed"] is False

    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_ibkr_minute_coverage_report_blocks_when_chunks_missing(tmp_path: Path) -> None:
    payload = build_us_equity_ibkr_minute_coverage_report(
        repo_root=tmp_path,
        symbols=["QQQ"],
        requested_start_date="2026-01-01",
        requested_end_date="2026-01-03",
        generated_at="2026-01-04T00:00:00Z",
    )

    report = payload["symbol_reports"]["QQQ"]
    assert payload["status"] == "blocked"
    assert report["raw_data_status"] == "blocked"
    assert report["next_missing_date"] == "2026-01-01"
    assert "ibkr_qqq_minute_chunks_missing" in payload["blockers"]
    assert payload["guardrails"]["private_account_endpoint_used"] is False


def _write_chunk(root: Path, symbol: str, start: str, end: str, *, rows: int) -> None:
    path = (
        root
        / "data/external/us_equity_intraday/ibkr/interval=1m/chunks"
        / symbol
        / f"{start}_{end}.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    start_ts = pd.Timestamp(f"{start}T14:30:00Z")
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range(start_ts, periods=rows, freq="min"),
            "symbol": [symbol] * rows,
            "Open": [100.0] * rows,
            "High": [101.0] * rows,
            "Low": [99.0] * rows,
            "Close": [100.5] * rows,
            "Volume": [1000.0] * rows,
        }
    )
    frame.to_parquet(path, index=False)
