from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PIT_TIME_FIELDS = ("event_time", "available_time", "ingested_at", "processed_at")
PIT_REQUIRED_ROLES = {
    "klines_1m",
    "klines_5m",
    "klines_15m",
    "klines_1h",
    "klines_4h",
    "klines_1d",
    "mark_price_klines_1h",
    "premium_index_klines_1h",
    "funding_rate",
    "funding_info",
    "open_interest_1h",
    "liquidation_1h",
    "long_short_ratio_1h",
    "derivatives_sentiment_1h",
    "exchange_info",
}


def evaluate_pit_contract(path: Path, *, role: str) -> dict[str, Any]:
    required = role in PIT_REQUIRED_ROLES
    rows = _read_rows(path)
    missing_fields = _missing_fields(rows)
    invalid_time_fields = _invalid_time_fields(rows)
    availability_violations = _availability_order_violations(rows)
    blockers: list[str] = []
    if required and not rows:
        blockers.append("btc_pit_contract_no_rows")
    if required and missing_fields:
        blockers.append("btc_pit_contract_required_fields_missing")
    if invalid_time_fields:
        blockers.append("btc_pit_contract_invalid_time_fields")
    if availability_violations:
        blockers.append("btc_pit_contract_available_time_before_event_time_violation")
    return {
        "required": required,
        "required_fields": list(PIT_TIME_FIELDS),
        "present": bool(rows and not missing_fields and not invalid_time_fields),
        "row_count_checked": len(rows),
        "missing_fields": missing_fields,
        "invalid_time_fields": invalid_time_fields,
        "available_time_order_violation_count": availability_violations,
        "blockers": _dedupe(blockers),
    }


def filter_rows_available_at(rows: list[Mapping[str, Any]], *, decision_time: str | datetime) -> list[dict[str, Any]]:
    decision = parse_utc(decision_time)
    visible: list[dict[str, Any]] = []
    for row in rows:
        available = parse_utc(row.get("available_time"))
        if available <= decision:
            visible.append(dict(row))
    return visible


def parse_utc(value: object) -> datetime:
    if value in {None, ""}:
        raise ValueError("missing UTC timestamp")
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.isdigit():
            number = int(text)
            if number > 10_000_000_000:
                number = number / 1000
            return datetime.fromtimestamp(float(number), tz=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _read_rows(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        if isinstance(payload.get("rows"), list):
            return [row for row in payload["rows"] if isinstance(row, Mapping)]
        return [payload]
    return []


def _missing_fields(rows: list[Mapping[str, Any]]) -> list[str]:
    missing: list[str] = []
    for field in PIT_TIME_FIELDS:
        if any(row.get(field) in {None, ""} for row in rows):
            missing.append(field)
    return missing


def _invalid_time_fields(rows: list[Mapping[str, Any]]) -> list[str]:
    invalid: list[str] = []
    for field in PIT_TIME_FIELDS:
        for row in rows:
            if row.get(field) in {None, ""}:
                continue
            try:
                parse_utc(row.get(field))
            except ValueError:
                invalid.append(field)
                break
    return invalid


def _availability_order_violations(rows: list[Mapping[str, Any]]) -> int:
    count = 0
    for row in rows:
        try:
            event = parse_utc(row.get("event_time"))
            available = parse_utc(row.get("available_time"))
        except ValueError:
            continue
        if available < event:
            count += 1
    return count


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
