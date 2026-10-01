from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_crypto.data.source_role_report import build_btc_source_role_report
from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def _row(ts: datetime, *, is_final: bool = True) -> dict[str, object]:
    return {
        "event_time": ts.isoformat(),
        "available_time": (ts + timedelta(minutes=1)).isoformat(),
        "ingested_at": (ts + timedelta(minutes=2)).isoformat(),
        "processed_at": (ts + timedelta(minutes=3)).isoformat(),
        "is_final": is_final,
        "close": 100.0,
    }


def test_btc_source_role_report_passes_for_finalized_pit_rows_without_gaps(tmp_path) -> None:
    rows = [_row(TS), _row(TS + timedelta(minutes=1)), _row(TS + timedelta(minutes=2))]
    payload = build_btc_source_role_report(
        role="klines_1m",
        source_path=tmp_path / "klines.csv",
        rows=rows,
        generated_at_utc=TS,
        decision_time_utc=TS + timedelta(minutes=5),
    )

    assert payload["status"] == "complete"
    assert payload["decision"] == "source_role_ready"
    assert payload["pit"]["present"] is True
    assert payload["finalization"]["non_final_rows"] == 0
    assert payload["gaps"]["gap_count"] == 0
    assert validate_btc_artifact_schema(payload) == []


def test_btc_source_role_report_blocks_missing_pit_and_non_final_rows(tmp_path) -> None:
    rows = [
        {
            "event_time": TS.isoformat(),
            "available_time": "",
            "ingested_at": TS.isoformat(),
            "processed_at": TS.isoformat(),
            "is_final": False,
        }
    ]
    payload = build_btc_source_role_report(
        role="klines_1m",
        source_path=tmp_path / "klines.csv",
        rows=rows,
        generated_at_utc=TS,
        decision_time_utc=TS + timedelta(minutes=5),
    )

    assert payload["status"] == "blocked"
    assert "btc_pit_contract_required_fields_missing" in payload["blockers"]
    assert "btc_source_role_non_final_rows_present" in payload["blockers"]


def test_btc_source_role_report_blocks_unrecovered_gaps_and_accepts_gapfill(tmp_path) -> None:
    rows = [_row(TS), _row(TS + timedelta(minutes=5))]
    blocked = build_btc_source_role_report(
        role="klines_1m",
        source_path=tmp_path / "klines.csv",
        rows=rows,
        generated_at_utc=TS,
        decision_time_utc=TS + timedelta(minutes=10),
    )
    recovered = build_btc_source_role_report(
        role="klines_1m",
        source_path=tmp_path / "klines.csv",
        rows=rows,
        gapfill_events=[{"stream": "klines_1m", "recovered": True, "events_backfilled": 4}],
        generated_at_utc=TS,
        decision_time_utc=TS + timedelta(minutes=10),
    )

    assert blocked["status"] == "blocked"
    assert "btc_source_role_gapfill_incomplete" in blocked["blockers"]
    assert recovered["status"] == "complete"
    assert recovered["gapfill"]["all_gaps_recovered"] is True
