from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from quant_crypto.data.pit_contract import evaluate_pit_contract, parse_utc
from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_SOURCE_ROLE_REPORT_VERSION = "btc_source_role_report_v1"
ROLE_INTERVALS = {
    "klines_1m": timedelta(minutes=1),
    "klines_5m": timedelta(minutes=5),
    "klines_15m": timedelta(minutes=15),
    "klines_1h": timedelta(hours=1),
    "klines_4h": timedelta(hours=4),
    "klines_1d": timedelta(days=1),
    "mark_price_klines_1h": timedelta(hours=1),
    "premium_index_klines_1h": timedelta(hours=1),
    "open_interest_1h": timedelta(hours=1),
    "liquidation_1h": timedelta(hours=1),
    "long_short_ratio_1h": timedelta(hours=1),
    "derivatives_sentiment_1h": timedelta(hours=1),
}


def build_btc_source_role_report(
    *,
    role: str,
    source_path: Path,
    generated_at_utc: datetime,
    decision_time_utc: datetime,
    rows: list[Mapping[str, Any]] | None = None,
    gapfill_events: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    loaded_rows = list(rows) if rows is not None else _read_rows_for_report(source_path)
    pit = evaluate_pit_contract(source_path, role=role) if rows is None else _evaluate_rows(role, loaded_rows)
    finalization = _finalization_status(loaded_rows)
    gaps = _gap_status(role, loaded_rows)
    gapfill = _gapfill_status(gapfill_events or [], gaps["gap_count"])
    blockers = []
    blockers.extend(str(item) for item in pit.get("blockers", []) if item)
    if not finalization["finalization_field_present"]:
        blockers.append("btc_source_role_finalization_field_missing")
    if finalization["non_final_rows"] > 0:
        blockers.append("btc_source_role_non_final_rows_present")
    if gaps["gap_count"] > 0 and not gapfill["all_gaps_recovered"]:
        blockers.append("btc_source_role_gapfill_incomplete")
    payload = {
        "source_role_report_version": BTC_SOURCE_ROLE_REPORT_VERSION,
        "status": "complete" if not blockers else "blocked",
        "role": role,
        "source_path": str(source_path).replace("\\", "/"),
        "decision_time_utc": ensure_utc(decision_time_utc).isoformat(),
        "row_count": len(loaded_rows),
        "pit": pit,
        "finalization": finalization,
        "gaps": gaps,
        "gapfill": gapfill,
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="source_role_ready" if not blockers else "source_role_blocked",
        generated_at_utc=generated_at_utc,
        as_of_utc=decision_time_utc,
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={"source_rows": stable_payload_hash({"rows": loaded_rows}), "gapfill_events": stable_payload_hash(gapfill_events or [])},
    )


def _evaluate_rows(role: str, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    missing_fields = []
    invalid_time_fields = []
    available_violations = 0
    for field in ("event_time", "available_time", "ingested_at", "processed_at"):
        if any(row.get(field) in {None, ""} for row in rows):
            missing_fields.append(field)
        for row in rows:
            if row.get(field) in {None, ""}:
                continue
            try:
                parse_utc(row.get(field))
            except ValueError:
                invalid_time_fields.append(field)
                break
    for row in rows:
        try:
            if parse_utc(row.get("available_time")) < parse_utc(row.get("event_time")):
                available_violations += 1
        except ValueError:
            continue
    blockers = []
    if missing_fields:
        blockers.append("btc_pit_contract_required_fields_missing")
    if invalid_time_fields:
        blockers.append("btc_pit_contract_invalid_time_fields")
    if available_violations:
        blockers.append("btc_pit_contract_available_time_before_event_time_violation")
    return {
        "required": True,
        "required_fields": ["event_time", "available_time", "ingested_at", "processed_at"],
        "present": bool(rows and not missing_fields and not invalid_time_fields),
        "row_count_checked": len(rows),
        "missing_fields": _dedupe(missing_fields),
        "invalid_time_fields": _dedupe(invalid_time_fields),
        "available_time_order_violation_count": available_violations,
        "blockers": blockers,
    }


def _finalization_status(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    final_fields = ("is_final", "finalized", "bar_final")
    present_field = next((field for field in final_fields if any(field in row for row in rows)), "")
    if not present_field:
        return {"finalization_field_present": False, "finalization_field": "", "non_final_rows": len(rows)}
    non_final = 0
    for row in rows:
        value = row.get(present_field)
        if str(value).lower() not in {"true", "1", "yes"} and value is not True:
            non_final += 1
    return {"finalization_field_present": True, "finalization_field": present_field, "non_final_rows": non_final}


def _gap_status(role: str, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    interval = ROLE_INTERVALS.get(role)
    if interval is None or len(rows) < 2:
        return {"gap_check_supported": interval is not None, "gap_count": 0, "max_gap_seconds": 0}
    times = sorted(parse_utc(row.get("event_time")) for row in rows if row.get("event_time") not in {None, ""})
    gaps = []
    expected_seconds = interval.total_seconds()
    for prev, current in zip(times, times[1:]):
        actual = (current - prev).total_seconds()
        if actual > expected_seconds * 1.5:
            gaps.append(actual)
    return {
        "gap_check_supported": True,
        "expected_interval_seconds": int(expected_seconds),
        "gap_count": len(gaps),
        "max_gap_seconds": int(max(gaps) if gaps else 0),
    }


def _gapfill_status(events: list[Mapping[str, Any]], gap_count: int) -> dict[str, Any]:
    recovered = sum(1 for event in events if event.get("recovered") is True)
    return {
        "gapfill_event_count": len(events),
        "recovered_gap_count": recovered,
        "all_gaps_recovered": gap_count == 0 or recovered >= gap_count,
        "events": [dict(event) for event in events],
    }


def _read_rows_for_report(path: Path) -> list[Mapping[str, Any]]:
    import csv
    import json

    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        return [row for row in payload["rows"] if isinstance(row, Mapping)]
    return []


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
