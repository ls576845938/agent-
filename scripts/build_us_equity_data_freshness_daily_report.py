#!/usr/bin/env python3
"""Build daily US equity data freshness gate report."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_data_freshness_daily_report_v1"
DEFAULT_TIINGO_REPORT = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_DATA_STATUS = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 数据新鲜度日更报告.md")
FRED_CANDIDATES = [
    Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json"),
    Path("artifacts/us_equity_data_status/latest/fred_macro_freshness_report.json"),
    Path("data/external/us_equity_macro/fred_macro.csv"),
    Path("data/fred/fred_macro.parquet"),
    Path("data/external/fred/fred_macro.parquet"),
]


def build_us_equity_data_freshness_daily_report(
    *,
    repo_root: Path | None = None,
    tiingo_report: Path = DEFAULT_TIINGO_REPORT,
    data_status: Path = DEFAULT_DATA_STATUS,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    as_of_date: str | None = None,
    max_price_stale_calendar_days: int = 5,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    as_of = _parse_date(as_of_date) if as_of_date else datetime.now(timezone.utc).date()
    tiingo_path = _resolve(root, tiingo_report)
    data_status_path = _resolve(root, data_status)
    tiingo = _read_json(tiingo_path)
    status_report = _read_json(data_status_path)
    latest_common = str(_nested(tiingo, "summary.latest_common_date", "") or tiingo.get("end_date") or "")
    latest_date = _parse_date(latest_common)
    stale_days = (as_of - latest_date).days if latest_date else None
    missing_symbols = _list(tiingo.get("missing_symbols"))
    blockers: list[str] = []
    warnings: list[str] = []

    if not tiingo:
        blockers.append("us_equity_freshness_tiingo_report_missing")
    if str(tiingo.get("status", "")) != "pass":
        blockers.append("us_equity_freshness_tiingo_import_not_pass")
    if missing_symbols:
        blockers.append("us_equity_freshness_missing_price_symbols")
    if stale_days is None:
        blockers.append("us_equity_freshness_latest_price_date_missing")
    elif stale_days < 0:
        blockers.append("us_equity_freshness_latest_price_date_after_as_of")
    elif stale_days > max_price_stale_calendar_days:
        blockers.append("us_equity_freshness_prices_stale")

    fred = _detect_fred(root)
    if fred["status"] == "missing":
        blockers.append("us_equity_freshness_fred_macro_data_missing")
    elif fred["status"] == "stale":
        blockers.append("us_equity_freshness_fred_macro_data_stale")
    elif fred["status"] == "unknown":
        warnings.append("us_equity_freshness_fred_macro_date_unknown")
    if fred["status"] == "present" and fred.get("source_status") == "fallback_after_blocked_import":
        warnings.append("us_equity_freshness_fred_import_blocked_using_local_csv_snapshot")

    unsafe_flags = _unsafe_flags({"tiingo": tiingo, "data_status": status_report, "fred": fred})
    blockers.extend([f"us_equity_freshness_unsafe_flag:{item}" for item in unsafe_flags])
    status = "pass" if not blockers else "blocked"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "as_of_date": as_of.isoformat(),
        "status": status,
        "asset": "us_equity",
        "price_freshness": {
            "provider": tiingo.get("provider"),
            "import_status": tiingo.get("status"),
            "symbol_count": tiingo.get("symbol_count"),
            "missing_symbols": missing_symbols,
            "latest_common_date": latest_common,
            "stale_calendar_days": stale_days,
            "max_stale_calendar_days": max_price_stale_calendar_days,
            "passed": bool(tiingo) and str(tiingo.get("status", "")) == "pass" and not missing_symbols and stale_days is not None and 0 <= stale_days <= max_price_stale_calendar_days,
        },
        "macro_freshness": fred,
        "data_status": {
            "status": status_report.get("status"),
            "promotion_clean": status_report.get("promotion_clean"),
            "data_lineage_grade": status_report.get("data_lineage_grade"),
            "blockers": _list(status_report.get("blockers")),
        },
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "guardrails": {
            "freshness_gate_only": True,
            "forward_runner_must_block_on_status_blocked": True,
            "macro_missing_must_not_be_silently_assumed_neutral": True,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "source_reports": {
            "tiingo_report": _relpath(tiingo_path, root),
            "data_status": _relpath(data_status_path, root),
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _detect_fred(root: Path) -> dict[str, Any]:
    blocked_import: dict[str, Any] | None = None
    for candidate in FRED_CANDIDATES:
        path = _resolve(root, candidate)
        if path.exists():
            latest = ""
            status = "unknown"
            blockers: list[str] = []
            if path.suffix.lower() == ".json":
                payload = _read_json(path)
                latest = str(payload.get("latest_common_date") or payload.get("end_date") or _nested(payload, "summary.latest_common_date", ""))
                status = str(payload.get("status", "")) or "unknown"
                blockers = [str(item) for item in _list(payload.get("blockers"))]
                if status == "blocked":
                    blocked_import = {
                        "source": _relpath(path, root),
                        "latest_common_date": latest or None,
                        "source_status": status,
                        "blockers": blockers,
                    }
                    if latest:
                        return {
                            "status": "stale",
                            "source": _relpath(path, root),
                            "latest_common_date": latest,
                            "passed": False,
                            "source_status": status,
                            "blockers": blockers,
                        }
                    continue
            elif path.suffix.lower() == ".csv":
                latest = _latest_timestamp_from_csv(path)
                if latest:
                    return {
                        "status": "present",
                        "source": _relpath(path, root),
                        "latest_common_date": latest,
                        "passed": True,
                        "source_status": "fallback_after_blocked_import" if blocked_import else "csv_snapshot",
                        "blockers": [str(item) for item in _list((blocked_import or {}).get("blockers"))],
                    }
            return {
                "status": "unknown" if not latest else "present",
                "source": _relpath(path, root),
                "latest_common_date": latest or None,
                "passed": bool(latest),
                "source_status": status,
                "blockers": blockers,
            }
    if blocked_import:
        return {
            "status": "missing",
            "source": blocked_import.get("source"),
            "latest_common_date": None,
            "passed": False,
            "source_status": blocked_import.get("source_status"),
            "blockers": [str(item) for item in _list(blocked_import.get("blockers"))],
        }
    return {
        "status": "missing",
        "source": None,
        "latest_common_date": None,
        "passed": False,
    }


def _latest_timestamp_from_csv(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            latest = None
            for row in reader:
                value = str(row.get("timestamp_utc") or "").strip()
                if value:
                    latest = value
            return latest
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def _unsafe_flags(reports: Mapping[str, Any]) -> list[str]:
    keys = {"live_order_allowed", "private_endpoint_used", "order_endpoint_used", "real_order_submitted", "real_orders_created"}
    out = []
    for name, payload in reports.items():
        for path, value in _walk(payload):
            if path.split(".")[-1] in keys and value is True:
                out.append(f"{name}.{path}=true")
    return out


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _markdown(payload: Mapping[str, Any]) -> str:
    price = _mapping(payload.get("price_freshness"))
    macro = _mapping(payload.get("macro_freshness"))
    lines = [
        "# US Equity 数据新鲜度日更报告",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"as-of：`{payload.get('as_of_date', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- ETF 最新共同日期：`{price.get('latest_common_date', '')}`，stale days：`{price.get('stale_calendar_days', '')}`",
        f"- FRED 宏观状态：`{macro.get('status', '')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = _list(payload.get("blockers"))
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- 无")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity data freshness daily report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--tiingo-report", default=str(DEFAULT_TIINGO_REPORT))
    parser.add_argument("--data-status", default=str(DEFAULT_DATA_STATUS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--max-price-stale-calendar-days", type=int, default=5)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_data_freshness_daily_report(
        repo_root=Path(args.repo_root),
        tiingo_report=Path(args.tiingo_report),
        data_status=Path(args.data_status),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        as_of_date=args.as_of_date or None,
        max_price_stale_calendar_days=args.max_price_stale_calendar_days,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
