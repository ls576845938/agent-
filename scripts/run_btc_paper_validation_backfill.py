#!/usr/bin/env python3
"""Run guarded BTC paper-validation cycles over historical windows."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_btc_paper_validation_readiness import (
    DEFAULT_DATA_ROOT,
    DEFAULT_INTERVAL,
    DEFAULT_LEDGER_ROOT,
    DEFAULT_READINESS_REPORT,
    DEFAULT_START_REPORT,
    MARKET_TYPE,
    SYMBOL,
    check_btc_paper_validation_readiness,
)
from scripts.run_btc_paper_validation import (
    DEFAULT_CYCLE_HOURS,
    DEFAULT_DAYS_REQUIRED,
    _load_bundle_frame,
    run_btc_paper_validation,
)


SCHEMA_VERSION = "btc_paper_validation_backfill_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_backfill_report.json")


def run_btc_paper_validation_backfill(
    *,
    repo_root: Path | None = None,
    symbols: list[str] | None = None,
    market_type: str = MARKET_TYPE,
    interval: str = DEFAULT_INTERVAL,
    ledger_root: Path | None = None,
    data_root: Path | None = None,
    readiness_report: Path | None = None,
    start_report: Path | None = None,
    output: Path | None = None,
    days_required: int = DEFAULT_DAYS_REQUIRED,
    cycle_hours: int = DEFAULT_CYCLE_HOURS,
    start: datetime | None = None,
    end: datetime | None = None,
    max_cycles: int = 30,
    require_start_report_ready: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    ledger = _resolve(root, ledger_root or DEFAULT_LEDGER_ROOT)
    data = _resolve(root, data_root or DEFAULT_DATA_ROOT)
    readiness_path = _resolve(root, readiness_report or DEFAULT_READINESS_REPORT)
    start_path = _resolve(root, start_report or DEFAULT_START_REPORT)
    output_path = _resolve(root, output or DEFAULT_OUTPUT)
    generated = generated_at or _utc_z_now()

    preflight = check_btc_paper_validation_readiness(
        repo_root=root,
        symbols=symbols or [SYMBOL],
        market_type=market_type,
        interval=interval,
        ledger_root=ledger,
        data_root=data,
        readiness_report=readiness_path,
        start_report=start_path,
        require_start_report_ready=bool(require_start_report_ready),
        generated_at=generated,
    )
    if preflight.get("status") != "PASS":
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "BLOCKED",
            "reason": "btc_paper_validation_backfill_preflight_blocked",
            "asset": "btc",
            "symbol": SYMBOL,
            "market_type": MARKET_TYPE,
            "interval": interval,
            "ledger_root": _path_text(ledger),
            "cycles_requested": 0,
            "cycles_completed": 0,
            "cycles_skipped": 0,
            "cycles_blocked": 0,
            "cycle_results": [],
            "preflight": preflight,
            "blockers": list(preflight.get("blocking_reasons", [])),
        }
        _write_json(output_path, payload)
        return payload

    bundle_dir = _resolve(root, Path(str(_mapping(preflight.get("inputs")).get("bundle_dir", ""))))
    frame = _load_bundle_frame(bundle_dir, interval=interval)
    windows = _cycle_windows(
        frame=frame,
        start=start,
        end=end,
        cycle_hours=cycle_hours,
        max_cycles=max_cycles,
    )

    cycle_results: list[dict[str, Any]] = []
    hard_blockers: list[str] = []
    for index, (window_start, window_end) in enumerate(windows, start=1):
        resume = (ledger / "validation_state.json").exists()
        result = run_btc_paper_validation(
            repo_root=root,
            symbols=symbols or [SYMBOL],
            market_type=market_type,
            interval=interval,
            ledger_root=ledger,
            data_root=data,
            readiness_report=readiness_path,
            start_report=start_path,
            days_required=days_required,
            cycle_hours=cycle_hours,
            start=window_start,
            end=window_end,
            resume=resume,
            require_start_report_ready=bool(require_start_report_ready),
            generated_at=generated,
        )
        status = str(result.get("status", ""))
        reason = str(result.get("reason", ""))
        if status == "BLOCKED" and reason == "btc_paper_validation_cycle_already_completed":
            cycle_results.append(_cycle_result(index, window_start, window_end, "SKIPPED", result))
            continue
        if status == "BLOCKED":
            hard_blockers.append(reason or "btc_paper_validation_cycle_blocked")
            cycle_results.append(_cycle_result(index, window_start, window_end, "BLOCKED", result))
            break
        cycle_results.append(_cycle_result(index, window_start, window_end, status, result))

    completed = [row for row in cycle_results if row["status"] in {"IN_PROGRESS", "PASS"}]
    skipped = [row for row in cycle_results if row["status"] == "SKIPPED"]
    blocked = [row for row in cycle_results if row["status"] == "BLOCKED"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "BLOCKED" if blocked else "PASS",
        "asset": "btc",
        "symbol": SYMBOL,
        "market_type": MARKET_TYPE,
        "interval": interval,
        "ledger_root": _path_text(ledger),
        "cycles_requested": len(windows),
        "cycles_completed": len(completed),
        "cycles_skipped": len(skipped),
        "cycles_blocked": len(blocked),
        "cycle_results": cycle_results,
        "monitoring_summary": _monitoring_summary(cycle_results),
        "blockers": _dedupe(hard_blockers),
    }
    _write_json(output_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BTC paper validation over historical windows.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", default=SYMBOL)
    parser.add_argument("--market-type", default=MARKET_TYPE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--start-report", default=str(DEFAULT_START_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--days-required", type=int, default=DEFAULT_DAYS_REQUIRED)
    parser.add_argument("--cycle-hours", type=int, default=DEFAULT_CYCLE_HOURS)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--max-cycles", type=int, default=30)
    parser.add_argument("--no-start-report-ready-required", action="store_true")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_btc_paper_validation_backfill(
        repo_root=Path(args.repo_root),
        symbols=_parse_symbols(args.symbols),
        market_type=args.market_type,
        interval=args.interval,
        ledger_root=Path(args.ledger_root),
        data_root=Path(args.data_root),
        readiness_report=Path(args.readiness_report),
        start_report=Path(args.start_report),
        output=Path(args.output),
        days_required=args.days_required,
        cycle_hours=args.cycle_hours,
        start=_parse_optional_utc(args.start),
        end=_parse_optional_utc(args.end),
        max_cycles=args.max_cycles,
        require_start_report_ready=not args.no_start_report_ready_required,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(f"BTC paper validation backfill status: {payload['status']}")
        print(f"cycles_completed: {payload['cycles_completed']}")
        print(f"cycles_skipped: {payload['cycles_skipped']}")
        print(f"cycles_blocked: {payload['cycles_blocked']}")
    raise SystemExit(0 if payload.get("status") == "PASS" else 2)


def _cycle_windows(
    *,
    frame: pd.DataFrame,
    start: datetime | None,
    end: datetime | None,
    cycle_hours: int,
    max_cycles: int,
) -> list[tuple[datetime, datetime]]:
    latest = pd.Timestamp(end) if end else pd.Timestamp(frame.index.max())
    if latest.tzinfo is None:
        latest = latest.tz_localize("UTC")
    else:
        latest = latest.tz_convert("UTC")
    hours = max(1, int(cycle_hours))
    limit = max(1, int(max_cycles))
    earliest = pd.Timestamp(start) if start else latest - pd.Timedelta(hours=hours * limit)
    if earliest.tzinfo is None:
        earliest = earliest.tz_localize("UTC")
    else:
        earliest = earliest.tz_convert("UTC")
    windows: list[tuple[datetime, datetime]] = []
    cursor = earliest
    while cursor < latest and len(windows) < limit:
        window_end = min(cursor + pd.Timedelta(hours=hours), latest)
        windows.append((cursor.to_pydatetime(), window_end.to_pydatetime()))
        cursor = window_end
    return windows


def _cycle_result(
    index: int,
    window_start: datetime,
    window_end: datetime,
    status: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    monitoring = _mapping(result.get("monitoring"))
    return {
        "index": index,
        "start": window_start.isoformat().replace("+00:00", "Z"),
        "end": window_end.isoformat().replace("+00:00", "Z"),
        "status": status,
        "reason": str(result.get("reason", "")),
        "run_id": str(result.get("run_id", "")),
        "monitoring_report_path": str(result.get("monitoring_report_path", "")),
        "signal_count": int(monitoring.get("signal_count", 0) or 0),
        "order_count": int(monitoring.get("order_count", 0) or 0),
        "fill_count": int(monitoring.get("fill_count", 0) or 0),
        "rejected_count": int(monitoring.get("rejected_count", 0) or 0),
        "total_fees": float(monitoring.get("total_fees", 0.0) or 0.0),
        "slippage_bps": float(monitoring.get("slippage_bps", 0.0) or 0.0),
        "equity_consistent": bool(monitoring.get("equity_consistent", False)),
        "reconciliation_passed": bool(monitoring.get("reconciliation_passed", False)),
        "has_trade_sample": bool(monitoring.get("has_trade_sample", False)),
    }


def _monitoring_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if str(row.get("status", "")) in {"IN_PROGRESS", "PASS"}]
    return {
        "completed_cycle_count": len(completed),
        "cycles_with_signals": sum(1 for row in completed if int(row.get("signal_count", 0) or 0) > 0),
        "cycles_with_orders": sum(1 for row in completed if int(row.get("order_count", 0) or 0) > 0),
        "cycles_with_fills": sum(1 for row in completed if int(row.get("fill_count", 0) or 0) > 0),
        "total_signals": sum(int(row.get("signal_count", 0) or 0) for row in completed),
        "total_orders": sum(int(row.get("order_count", 0) or 0) for row in completed),
        "total_fills": sum(int(row.get("fill_count", 0) or 0) for row in completed),
        "total_rejected": sum(int(row.get("rejected_count", 0) or 0) for row in completed),
        "total_fees": sum(float(row.get("total_fees", 0.0) or 0.0) for row in completed),
        "all_equity_consistent": all(bool(row.get("equity_consistent", False)) for row in completed) if completed else False,
        "all_reconciliation_passed": all(bool(row.get("reconciliation_passed", False)) for row in completed) if completed else False,
    }


def _parse_symbols(raw: str) -> list[str]:
    return sorted({item.strip().upper() for item in raw.split(",") if item.strip()})


def _parse_optional_utc(raw: str) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), indent=2, sort_keys=True, default=str))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _path_text(path: Path | None) -> str:
    return "" if path is None else str(path).replace("\\", "/")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


if __name__ == "__main__":
    main()
