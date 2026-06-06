from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


FUNDING_TIME_TOLERANCE_SECONDS = 300


def funding_rate_coverage_status(
    path: Path,
    *,
    sample_start: str | datetime,
    sample_end: str | datetime,
    tolerance_seconds: int = FUNDING_TIME_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    rows = read_funding_rate_rows(path)
    times = [row["funding_time"] for row in rows]
    sample_start_dt = parse_time(sample_start)
    sample_end_dt = parse_time(sample_end)
    duplicates = len(times) - len(set(times))
    monotonic = times == sorted(times)
    interval = _interval_diagnostics(times, tolerance_seconds=tolerance_seconds)
    expected = _expected_times(
        start=sample_start_dt,
        end=sample_end_dt,
        anchor=min(times) if times else sample_start_dt,
        interval_hours=interval["dominant_interval_hours"],
    )
    missing = [
        value
        for value in expected
        if not _contains_time_with_tolerance(times, value, tolerance_seconds=tolerance_seconds)
    ]
    blockers: list[str] = []
    if not rows:
        blockers.append("btc_funding_rate_missing_or_empty")
    if duplicates:
        blockers.append("btc_funding_rate_duplicate_funding_time")
    if times and not monotonic:
        blockers.append("btc_funding_rate_non_monotonic")
    if interval["interval_inference_confidence"] != "high":
        blockers.append("btc_funding_rate_interval_inference_not_high_confidence")
    if missing:
        blockers.append("btc_funding_rate_expected_events_missing")
    coverage_complete = bool(rows and not duplicates and monotonic and interval["interval_inference_confidence"] == "high" and not missing)
    return {
        "record_count": len(rows),
        "first_funding_time": iso(min(times)) if times else None,
        "last_funding_time": iso(max(times)) if times else None,
        "duplicate_funding_time_count": duplicates,
        "monotonic_time_pass": bool(monotonic),
        "observed_interval_hours_distribution": interval["observed_interval_hours_distribution"],
        "dominant_interval_hours": interval["dominant_interval_hours"],
        "interval_inference_confidence": interval["interval_inference_confidence"],
        "irregular_interval_count": interval["irregular_interval_count"],
        "expected_missing_funding_times": [iso(value) for value in missing],
        "expected_missing_funding_time_ms": [int(value.timestamp() * 1000) for value in missing],
        "missing_range_start": iso(missing[0]) if missing else None,
        "missing_range_end": iso(missing[-1]) if missing else None,
        "coverage_complete": coverage_complete,
        "blockers": _dedupe(blockers),
    }


def read_funding_rate_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            funding_time = parse_time(row.get("fundingTime") or row.get("funding_time") or row.get("timestamp"))
            if funding_time is None:
                continue
            rows.append({"funding_time": funding_time, "raw": dict(row)})
    return rows


def parse_time(value: object) -> datetime:
    if value in {None, ""}:
        raise ValueError("missing time value")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(float(number), tz=timezone.utc)
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _interval_diagnostics(times: list[datetime], *, tolerance_seconds: int) -> dict[str, Any]:
    if len(times) < 2:
        return {
            "observed_interval_hours_distribution": {},
            "dominant_interval_hours": None,
            "interval_inference_confidence": "none",
            "irregular_interval_count": 0,
        }
    ordered = sorted(times)
    deltas = [(right - left).total_seconds() for left, right in zip(ordered, ordered[1:]) if right > left]
    rounded_hour_counts = Counter(round(delta / 3600) for delta in deltas)
    if not rounded_hour_counts:
        return {
            "observed_interval_hours_distribution": {},
            "dominant_interval_hours": None,
            "interval_inference_confidence": "none",
            "irregular_interval_count": 0,
        }
    dominant_interval_hours, dominant_count = rounded_hour_counts.most_common(1)[0]
    irregular = sum(
        1
        for delta in deltas
        if abs(delta - dominant_interval_hours * 3600) > tolerance_seconds
    )
    confidence = "high" if dominant_count >= 3 and irregular == 0 and times == ordered and len(times) == len(set(times)) else "low"
    return {
        "observed_interval_hours_distribution": {
            f"{float(key):.1f}": value for key, value in sorted(rounded_hour_counts.items())
        },
        "dominant_interval_hours": float(dominant_interval_hours),
        "interval_inference_confidence": confidence,
        "irregular_interval_count": irregular,
    }


def _expected_times(
    *,
    start: datetime,
    end: datetime,
    anchor: datetime,
    interval_hours: float | None,
) -> list[datetime]:
    if not interval_hours or interval_hours <= 0:
        return []
    step = timedelta(hours=interval_hours)
    current = anchor
    while current < start:
        current += step
    out: list[datetime] = []
    while current <= end:
        out.append(current)
        current += step
    return out


def _contains_time_with_tolerance(times: list[datetime], expected: datetime, *, tolerance_seconds: int) -> bool:
    return any(abs((value - expected).total_seconds()) <= tolerance_seconds for value in times)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out
