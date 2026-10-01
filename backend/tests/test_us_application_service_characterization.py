from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from backend.app.services.us_quant import USQuantService
from quant_us import cli
from quant_us.core.calendar import USEquityCalendar
from quant_us.data.minute_quality_gate import _expected_regular_timestamps


class RecordingCursor:
    def __init__(self, calls: list[tuple[str, str, object]]) -> None:
        self.calls = calls

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def executemany(self, sql: str, rows: list[dict[str, object]]) -> None:
        self.calls.append(("executemany", sql, rows))


class RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.commit_count = 0

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.calls)

    def commit(self) -> None:
        self.commit_count += 1


def test_calendar_api_characterization_preserves_count_and_upsert_shape() -> None:
    connection = RecordingConnection()

    count = USQuantService(db_connection=connection).populate_trading_calendar(
        2024, 2024
    )

    assert count == 366
    assert connection.commit_count == 1
    _, sql, rows = connection.calls[0]
    assert "ON CONFLICT (date) DO UPDATE" in sql
    assert len(rows) == 366
    new_year = next(row for row in rows if row["date"] == date(2024, 1, 1))
    assert new_year == {
        "date": date(2024, 1, 1),
        "is_trading_day": False,
        "session_hours": "00:00-00:00",
        "early_close_time": None,
        "holiday_name": "XNYS closed session",
        "notes": "XNYS closed session",
    }


def test_minute_quality_api_characterization_preserves_output_schema(
    tmp_path: Path,
) -> None:
    trading_day = datetime(2026, 5, 8, tzinfo=timezone.utc).date()
    timestamps = _expected_regular_timestamps(
        trading_day,
        5,
        USEquityCalendar.with_holidays(),
    )
    partition = (
        tmp_path
        / "cleaned"
        / "vendor=yfinance"
        / "asset_class=equity"
        / "bar_size=5m"
        / "symbol=AAPL"
        / f"date={trading_day.isoformat()}.parquet"
    )
    partition.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "symbol": ["AAPL"] * len(timestamps),
            "open": [100.0] * len(timestamps),
            "high": [101.0] * len(timestamps),
            "low": [99.0] * len(timestamps),
            "close": [100.5] * len(timestamps),
            "volume": [1_000] * len(timestamps),
        }
    ).to_parquet(partition, index=False)

    payload = USQuantService().data_quality_report(
        {
            "data_root": str(tmp_path),
            "symbols": ["aapl", "AAPL"],
            "bar_sizes": "5m",
            "root_subdirs": "cleaned",
            "lookback_trading_days": 1,
            "as_of": "2026-05-08T21:00:00Z",
        }
    )

    assert set(payload) >= {
        "status",
        "as_of_utc",
        "data_root",
        "requested_data_root",
        "resolved_data_root",
        "data_root_resolution",
        "audit_scope",
        "dataset_discovery",
        "dataset_statuses",
        "evidence_summary",
        "remediation_summary",
    }
    assert payload["evaluated_symbols"] == ["AAPL"]
    assert payload["bar_sizes"] == ["5m"]
    assert payload["lookback_trading_days"] == 1
    assert payload["evidence_summary"]["download_performed"] is False


def test_promotion_gate_cli_characterization_preserves_text_contract(
    monkeypatch,
    capsys,
) -> None:
    result = SimpleNamespace(
        candidate_id="candidate-1",
        decision="READY_FOR_PAPER_REVIEW",
        reasons=[],
        warnings=["fixture warning"],
        evidence={"manifest_exists": True},
    )

    class FakeGate:
        def __init__(self, data_root: str) -> None:
            assert data_root == "fixture-data"

        def evaluate(self, candidate_id: str):
            assert candidate_id == "candidate-1"
            return result

    monkeypatch.setattr(
        "quant_us.research.automation.promotion_gate.ResearchPromotionGate",
        FakeGate,
    )

    cli.cmd_research_promotion_gate(
        argparse.Namespace(
            data_root="fixture-data",
            candidate_id="candidate-1",
        )
    )

    output = capsys.readouterr().out
    assert "Research Promotion Gate Evaluation" in output
    assert "Candidate:  candidate-1" in output
    assert "Decision:   READY_FOR_PAPER_REVIEW" in output
    assert "fixture warning" in output
    assert "READY_FOR_PAPER_REVIEW does NOT enter paper trading" in output
