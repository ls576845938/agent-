#!/usr/bin/env python3
"""Build a local coverage report for IBKR 1-minute supplemental chunks.

This builder is local-only. It scans parquet files that were already imported
by the read-only IBKR backfill script; it does not import ib_insync, connect to
TWS/Gateway, inspect account state, or touch order endpoints.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SCHEMA_VERSION = "us_equity_ibkr_minute_coverage_report_v1"
DEFAULT_SYMBOLS = ("QQQ", "TQQQ")
DEFAULT_INPUT_ROOT = Path("data/external/us_equity_intraday/ibkr/interval=1m")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/ibkr_minute_coverage_report.json")
DEFAULT_REQUESTED_START_DATE = "2017-05-31"


def build_us_equity_ibkr_minute_coverage_report(
    *,
    repo_root: Path,
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    input_root: Path = DEFAULT_INPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    requested_start_date: str = DEFAULT_REQUESTED_START_DATE,
    requested_end_date: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or _utc_now()
    end_date = requested_end_date or generated[:10]
    selected_symbols = _unique(symbols)
    input_abs = _resolve(root, input_root)
    report_abs = _resolve(root, report_path)

    symbol_reports: dict[str, Any] = {}
    blockers: list[str] = []
    for symbol in selected_symbols:
        report = _symbol_coverage(
            symbol=symbol,
            root=root,
            input_root=input_abs,
            requested_start_date=requested_start_date,
            requested_end_date=end_date,
        )
        symbol_reports[symbol] = report
        blockers.extend(str(item) for item in report.get("blockers", []))

    complete_symbols = [
        symbol for symbol, report in symbol_reports.items() if report.get("raw_data_status") == "complete"
    ]
    status = "pass" if len(complete_symbols) == len(selected_symbols) and selected_symbols else "partial"
    if not complete_symbols:
        status = "blocked" if not any(r.get("readable_chunk_count", 0) for r in symbol_reports.values()) else "partial"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "research_ready_status": "blocked",
        "asset": "us_equity",
        "provider": "ibkr",
        "source_type": "local_broker_historical_market_data_chunk_coverage",
        "symbols": selected_symbols,
        "symbol_count": len(selected_symbols),
        "requested_start_date": requested_start_date,
        "requested_end_date": end_date,
        "input_root": _relpath(input_abs, root),
        "report_path": _relpath(report_abs, root),
        "network_called": False,
        "writes_market_data": False,
        "readonly_local_scan": True,
        "guardrails": _guardrails(),
        "data_limitations": _data_limitations(),
        "adjustment_controls": _adjustment_controls(),
        "summary": _summary(symbol_reports),
        "symbol_reports": symbol_reports,
        "blockers": _dedupe(blockers),
        "next_actions": _next_actions(symbol_reports, end_date),
    }
    _write_json(report_abs, payload)
    return payload


def _symbol_coverage(
    *,
    symbol: str,
    root: Path,
    input_root: Path,
    requested_start_date: str,
    requested_end_date: str,
) -> dict[str, Any]:
    chunk_root = input_root / "chunks" / symbol
    chunk_files = sorted(chunk_root.glob("*.parquet")) if chunk_root.exists() else []
    chunk_reports = [_read_chunk(path=path, root=root) for path in chunk_files]
    readable = [item for item in chunk_reports if item.get("status") == "readable"]
    intervals = [(str(item["file_start_date"]), str(item["file_end_date"])) for item in readable]
    merged = _merge_date_intervals(intervals)
    total_requested_days = _calendar_days(requested_start_date, requested_end_date)
    covered_days = _covered_days_within(merged, requested_start_date, requested_end_date)
    next_missing_date = _next_missing_date(merged, requested_start_date, requested_end_date)
    coverage_ratio = float(covered_days / total_requested_days) if total_requested_days else 0.0
    observed_starts = [str(item.get("observed_start_timestamp")) for item in readable if item.get("observed_start_timestamp")]
    observed_ends = [str(item.get("observed_end_timestamp")) for item in readable if item.get("observed_end_timestamp")]
    row_count = sum(int(item.get("rows", 0) or 0) for item in readable)
    raw_complete = bool(merged) and next_missing_date is None

    blockers: list[str] = []
    if not readable:
        blockers.append(f"ibkr_{symbol.lower()}_minute_chunks_missing")
    if not raw_complete:
        blockers.append(f"ibkr_{symbol.lower()}_minute_coverage_incomplete")
    blockers.append(f"{symbol.lower()}_ibkr_minute_pit_adjustment_replay_required")

    return {
        "symbol": symbol,
        "raw_data_status": "complete" if raw_complete else ("partial" if readable else "blocked"),
        "research_ready_status": "blocked",
        "chunk_root": _relpath(chunk_root, root),
        "chunk_file_count": len(chunk_files),
        "readable_chunk_count": len(readable),
        "unreadable_chunk_count": len(chunk_reports) - len(readable),
        "row_count": row_count,
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
        "first_covered_date": merged[0][0] if merged else None,
        "last_covered_date": merged[-1][1] if merged else None,
        "next_missing_date": next_missing_date,
        "covered_calendar_days": covered_days,
        "requested_calendar_days": total_requested_days,
        "coverage_ratio_calendar": round(coverage_ratio, 6),
        "observed_start_timestamp": min(observed_starts) if observed_starts else None,
        "observed_end_timestamp": max(observed_ends) if observed_ends else None,
        "merged_coverage_ranges": [{"start": start, "end": end} for start, end in merged],
        "sample_unreadable_chunks": [item for item in chunk_reports if item.get("status") != "readable"][:5],
        "blockers": _dedupe(blockers),
    }


def _read_chunk(*, path: Path, root: Path) -> dict[str, Any]:
    start, end = _parse_chunk_dates(path)
    base = {
        "path": _relpath(path, root),
        "file_start_date": start,
        "file_end_date": end,
    }
    try:
        frame = pd.read_parquet(path, columns=["datetime"])
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "status": "unreadable",
            "rows": 0,
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }
    if frame.empty:
        return {**base, "status": "empty", "rows": 0}
    timestamps = pd.to_datetime(frame["datetime"], utc=True, errors="coerce").dropna()
    return {
        **base,
        "status": "readable",
        "rows": int(len(frame)),
        "observed_start_timestamp": timestamps.min().isoformat() if not timestamps.empty else None,
        "observed_end_timestamp": timestamps.max().isoformat() if not timestamps.empty else None,
    }


def _parse_chunk_dates(path: Path) -> tuple[str | None, str | None]:
    stem = path.stem
    parts = stem.split("_")
    if len(parts) != 2:
        return None, None
    try:
        date.fromisoformat(parts[0])
        date.fromisoformat(parts[1])
    except ValueError:
        return None, None
    return parts[0], parts[1]


def _merge_date_intervals(intervals: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    parsed: list[tuple[date, date]] = []
    for start_raw, end_raw in intervals:
        try:
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
        except (TypeError, ValueError):
            continue
        if end < start:
            continue
        parsed.append((start, end))
    if not parsed:
        return []
    parsed.sort()
    merged: list[tuple[date, date]] = []
    for start, end in parsed:
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return [(start.isoformat(), end.isoformat()) for start, end in merged]


def _calendar_days(start_raw: str, end_raw: str) -> int:
    start = date.fromisoformat(start_raw)
    end = date.fromisoformat(end_raw)
    if end < start:
        return 0
    return (end - start).days + 1


def _covered_days_within(intervals: list[tuple[str, str]], start_raw: str, end_raw: str) -> int:
    requested_start = date.fromisoformat(start_raw)
    requested_end = date.fromisoformat(end_raw)
    total = 0
    for interval_start_raw, interval_end_raw in intervals:
        interval_start = max(date.fromisoformat(interval_start_raw), requested_start)
        interval_end = min(date.fromisoformat(interval_end_raw), requested_end)
        if interval_end >= interval_start:
            total += (interval_end - interval_start).days + 1
    return total


def _next_missing_date(intervals: list[tuple[str, str]], start_raw: str, end_raw: str) -> str | None:
    cursor = date.fromisoformat(start_raw)
    requested_end = date.fromisoformat(end_raw)
    for interval_start_raw, interval_end_raw in intervals:
        interval_start = date.fromisoformat(interval_start_raw)
        interval_end = date.fromisoformat(interval_end_raw)
        if interval_end < cursor:
            continue
        if interval_start > cursor:
            return cursor.isoformat()
        cursor = max(cursor, interval_end + timedelta(days=1))
        if cursor > requested_end:
            return None
    return cursor.isoformat() if cursor <= requested_end else None


def _summary(symbol_reports: dict[str, Any]) -> dict[str, Any]:
    ratios = [float(report.get("coverage_ratio_calendar", 0.0) or 0.0) for report in symbol_reports.values()]
    last_dates = [str(report.get("last_covered_date")) for report in symbol_reports.values() if report.get("last_covered_date")]
    next_missing = {
        symbol: report.get("next_missing_date")
        for symbol, report in symbol_reports.items()
        if report.get("next_missing_date")
    }
    return {
        "complete_symbol_count": sum(1 for report in symbol_reports.values() if report.get("raw_data_status") == "complete"),
        "partial_symbol_count": sum(1 for report in symbol_reports.values() if report.get("raw_data_status") == "partial"),
        "blocked_symbol_count": sum(1 for report in symbol_reports.values() if report.get("raw_data_status") == "blocked"),
        "min_coverage_ratio_calendar": round(min(ratios), 6) if ratios else 0.0,
        "max_coverage_ratio_calendar": round(max(ratios), 6) if ratios else 0.0,
        "common_last_covered_date": min(last_dates) if last_dates else None,
        "latest_any_covered_date": max(last_dates) if last_dates else None,
        "next_missing_by_symbol": next_missing,
    }


def _next_actions(symbol_reports: dict[str, Any], requested_end_date: str) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for symbol, report in symbol_reports.items():
        next_missing = report.get("next_missing_date")
        if not next_missing:
            continue
        actions.append(
            {
                "symbol": symbol,
                "reason": "resume_ibkr_1d_chunk_backfill_from_next_missing_date",
                "command": (
                    "py -3 scripts/fetch_us_equity_ibkr_minute_backfill.py --repo-root . "
                    f"--symbols {symbol} --start-date {next_missing} --end-date {requested_end_date} "
                    "--host 127.0.0.1 --port 4002 --duration \"1 D\" --bar-size \"1 min\" "
                    "--what-to-show TRADES --chunk-days 1 --max-new-chunks-per-symbol 1 "
                    "--request-timeout-seconds 60 --execute-network"
                ),
            }
        )
    return actions


def _guardrails() -> dict[str, bool]:
    return {
        "network_called": False,
        "private_account_endpoint_used": False,
        "broker_order_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
        "paper_or_live_unlock_allowed": False,
        "promotion_clean_granted_by_this_report": False,
    }


def _data_limitations() -> dict[str, Any]:
    return {
        "ibkr_role": "supplemental broker historical market data, not standalone production PIT master data",
        "minute_bars_are_raw": True,
        "point_in_time_adjustment_replay_included": False,
        "research_clean_approval_granted": False,
        "account_or_order_endpoint_used": False,
    }


def _adjustment_controls() -> dict[str, Any]:
    return {
        "raw_intraday_retained": True,
        "pit_adjustment_replay_required_before_research_use": True,
        "back_adjusted_for_signal_use_allowed": False,
        "no_lookahead_rule": "Do not apply full-history future adjustment factors to historical minute signals.",
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).upper().strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item)
        if value and value not in result:
            result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local IBKR 1-minute chunk coverage report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--requested-start-date", default=DEFAULT_REQUESTED_START_DATE)
    parser.add_argument("--requested-end-date", default=None)
    args = parser.parse_args()
    payload = build_us_equity_ibkr_minute_coverage_report(
        repo_root=Path(args.repo_root),
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
        input_root=Path(args.input_root),
        report_path=Path(args.report),
        requested_start_date=args.requested_start_date,
        requested_end_date=args.requested_end_date,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "research_ready_status": payload["research_ready_status"],
                "report": payload["report_path"],
                "summary": payload["summary"],
                "blockers": payload["blockers"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
