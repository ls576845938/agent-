#!/usr/bin/env python3
"""Build a daily ETF EOD kline quality report for the US equity system."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_etf_kline_quality_daily_report_v1"
DEFAULT_KLINE_ROOT = Path("data/external/us_equity_eod/tiingo/kline")
DEFAULT_TIINGO_IMPORT_REPORT = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity ETF Kline 日更质量报告.md")
DEFAULT_REQUIRED_SYMBOLS = (
    "BITO",
    "DBMF",
    "GLD",
    "IEF",
    "IGV",
    "MTUM",
    "PDBC",
    "QMOM",
    "QQQ",
    "SHV",
    "SOXX",
    "SPY",
    "USO",
    "VOO",
    "XBI",
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
)
KEY_BENCHMARKS = {"SPY", "QQQ"}
ALLOWED_STATUSES = {"pass", "warn", "blocked"}


def build_us_equity_etf_kline_quality_daily_report(
    *,
    repo_root: Path | None = None,
    kline_root: Path = DEFAULT_KLINE_ROOT,
    tiingo_import_report: Path = DEFAULT_TIINGO_IMPORT_REPORT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    required_symbols: tuple[str, ...] = DEFAULT_REQUIRED_SYMBOLS,
    generated_at: str | None = None,
    max_staleness_days: int = 5,
    extreme_abs_return_threshold: float = 0.40,
    key_benchmark_abs_return_threshold: float = 0.25,
    max_calendar_gap_days: int = 10,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    kline_abs = _resolve(root, kline_root)
    import_path = _resolve(root, tiingo_import_report)
    import_payload = _read_json(import_path)
    symbols = tuple(dict.fromkeys([*(str(s).upper() for s in _list(import_payload.get("symbols"))), *required_symbols]))

    symbol_reports: dict[str, Any] = {}
    blockers: list[str] = []
    warnings: list[str] = []
    latest_dates: dict[str, str] = {}
    starts: dict[str, str] = {}
    row_counts: dict[str, int] = {}

    for symbol in symbols:
        report = _inspect_symbol(
            symbol,
            kline_abs / f"{symbol}.parquet",
            generated_at=generated,
            max_staleness_days=max_staleness_days,
            extreme_abs_return_threshold=extreme_abs_return_threshold,
            key_benchmark_abs_return_threshold=key_benchmark_abs_return_threshold,
            max_calendar_gap_days=max_calendar_gap_days,
        )
        symbol_reports[symbol] = report
        if report["status"] in {"blocked", "missing"}:
            blockers.extend(f"{symbol}:{item}" for item in _list_of_str(report.get("blockers")))
        elif report["status"] == "warn":
            warnings.extend(f"{symbol}:{item}" for item in _list_of_str(report.get("warnings")))
        if report.get("end"):
            latest_dates[symbol] = str(report["end"])
        if report.get("start"):
            starts[symbol] = str(report["start"])
        row_counts[symbol] = int(report.get("rows", 0) or 0)

    import_guardrails = _mapping(import_payload.get("guardrails"))
    if import_payload and str(import_payload.get("status", "")) != "pass":
        blockers.extend(_list_of_str(import_payload.get("blockers")) or ["tiingo_import_report_not_pass"])
    if import_guardrails.get("token_written_to_artifacts") is True:
        blockers.append("tiingo_import_token_written_to_artifacts")
    if _unsafe_true({"tiingo_import": import_payload}):
        blockers.append("etf_kline_quality_unsafe_flag_detected")

    latest_common_date = min(latest_dates.values()) if latest_dates else None
    status = "blocked" if blockers else ("warn" if warnings else "pass")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "provider": "tiingo",
        "source_type": "local_tiingo_eod_parquet",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "promotion_clean": status == "pass",
        "symbol_count": len(symbols),
        "available_symbol_count": sum(1 for row in symbol_reports.values() if row.get("status") != "missing"),
        "missing_symbols": [symbol for symbol, row in symbol_reports.items() if row.get("status") == "missing"],
        "summary": {
            "latest_common_date": latest_common_date,
            "latest_any_date": max(latest_dates.values()) if latest_dates else None,
            "earliest_start": min(starts.values()) if starts else None,
            "min_rows": min(row_counts.values()) if row_counts else 0,
            "max_rows": max(row_counts.values()) if row_counts else 0,
            "blocked_symbol_count": sum(1 for row in symbol_reports.values() if row.get("status") == "blocked"),
            "warn_symbol_count": sum(1 for row in symbol_reports.values() if row.get("status") == "warn"),
        },
        "thresholds": {
            "max_staleness_days": max_staleness_days,
            "extreme_abs_return_threshold": extreme_abs_return_threshold,
            "key_benchmark_abs_return_threshold": key_benchmark_abs_return_threshold,
            "max_calendar_gap_days": max_calendar_gap_days,
        },
        "symbol_reports": symbol_reports,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "guardrails": {
            "kline_quality_gate_only": True,
            "api_key_value_recorded": False,
            "token_written_to_artifacts": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "source_files": {
            "kline_root": _relpath(kline_abs, root),
            "tiingo_import_report": _relpath(import_path, root),
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _inspect_symbol(
    symbol: str,
    path: Path,
    *,
    generated_at: str,
    max_staleness_days: int,
    extreme_abs_return_threshold: float,
    key_benchmark_abs_return_threshold: float,
    max_calendar_gap_days: int,
) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path).replace("\\", "/"), "rows": 0, "blockers": ["kline_file_missing"], "warnings": []}
    blockers: list[str] = []
    warnings: list[str] = []
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001 - fail closed with evidence
        return {"status": "blocked", "path": str(path).replace("\\", "/"), "rows": 0, "blockers": [f"kline_file_read_failed:{exc}"], "warnings": []}
    normalized = _normalize_frame(frame)
    if normalized.empty:
        return {"status": "blocked", "path": str(path).replace("\\", "/"), "rows": 0, "blockers": ["kline_frame_empty"], "warnings": []}
    duplicate_dates = int(normalized["timestamp_utc"].duplicated().sum())
    non_positive = int((normalized[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    invalid_ohlc = int(
        (
            (normalized["high"] < normalized[["open", "close", "low"]].max(axis=1))
            | (normalized["low"] > normalized[["open", "close", "high"]].min(axis=1))
        ).sum()
    )
    zero_or_negative_volume = int((normalized["volume"].fillna(0.0) <= 0).sum())
    returns = normalized["close"].pct_change(fill_method=None)
    threshold = key_benchmark_abs_return_threshold if symbol in KEY_BENCHMARKS else extreme_abs_return_threshold
    extreme_returns = normalized.loc[returns.abs() > threshold, ["timestamp_utc", "close"]].copy()
    gap_days = normalized["timestamp_utc"].diff().dt.days.fillna(0).astype(int)
    large_gaps = normalized.loc[gap_days > max_calendar_gap_days, ["timestamp_utc"]].copy()
    start = normalized["timestamp_utc"].min().date().isoformat()
    end = normalized["timestamp_utc"].max().date().isoformat()
    generated_date = _parse_utc(generated_at).date()
    staleness_days = max(0, (generated_date - normalized["timestamp_utc"].max().date()).days)

    if duplicate_dates:
        blockers.append(f"duplicate_dates:{duplicate_dates}")
    if non_positive:
        blockers.append(f"non_positive_ohlc_rows:{non_positive}")
    if invalid_ohlc:
        blockers.append(f"invalid_ohlc_rows:{invalid_ohlc}")
    if int(len(extreme_returns)):
        blockers.append(f"extreme_daily_return_rows:{int(len(extreme_returns))}")
    if staleness_days > max_staleness_days:
        blockers.append(f"stale_data_days:{staleness_days}")
    if int(len(large_gaps)):
        warnings.append(f"large_calendar_gaps_gt_{max_calendar_gap_days}d:{int(len(large_gaps))}")
    if zero_or_negative_volume:
        warnings.append(f"zero_or_negative_volume_rows:{zero_or_negative_volume}")
    status = "blocked" if blockers else ("warn" if warnings else "pass")
    return {
        "status": status,
        "path": str(path).replace("\\", "/"),
        "rows": int(len(normalized)),
        "start": start,
        "end": end,
        "staleness_days": staleness_days,
        "latest_close": round(float(normalized["close"].iloc[-1]), 6),
        "duplicate_dates": duplicate_dates,
        "non_positive_ohlc_rows": non_positive,
        "invalid_ohlc_rows": invalid_ohlc,
        "zero_or_negative_volume_rows": zero_or_negative_volume,
        "extreme_daily_return_rows": int(len(extreme_returns)),
        "max_abs_return": round(float(returns.abs().max(skipna=True) or 0.0), 10),
        "large_calendar_gap_rows": int(len(large_gaps)),
        "sample_extreme_return_dates": [str(ts.date()) for ts in extreme_returns["timestamp_utc"].head(5)],
        "sample_large_gap_dates": [str(ts.date()) for ts in large_gaps["timestamp_utc"].head(5)],
        "blockers": blockers,
        "warnings": warnings,
    }


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    column_map = {column.lower(): column for column in frame.columns}
    required = {
        "datetime": "timestamp_utc",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    out = pd.DataFrame()
    for lower, target in required.items():
        if lower not in column_map:
            return pd.DataFrame(columns=list(required.values()))
        out[target] = frame[column_map[lower]]
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.dropna(subset=["timestamp_utc", "open", "high", "low", "close"]).sort_values("timestamp_utc").reset_index(drop=True)


def _markdown(payload: Mapping[str, Any]) -> str:
    summary = _mapping(payload.get("summary"))
    lines = [
        "# US Equity ETF Kline 日更质量报告",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- promotion_clean: `{payload.get('promotion_clean')}`",
        f"- symbol_count: `{payload.get('symbol_count')}`",
        f"- available_symbol_count: `{payload.get('available_symbol_count')}`",
        f"- latest_common_date: `{summary.get('latest_common_date')}`",
        f"- latest_any_date: `{summary.get('latest_any_date')}`",
        f"- blocked_symbol_count: `{summary.get('blocked_symbol_count')}`",
        f"- warn_symbol_count: `{summary.get('warn_symbol_count')}`",
        "",
        "## Symbol Status",
        "",
        "| Symbol | Status | Rows | Start | End | Stale Days | Main Issue |",
        "|---|---:|---:|---|---|---:|---|",
    ]
    for symbol, report in sorted(_mapping(payload.get("symbol_reports")).items()):
        row = _mapping(report)
        issues = _list_of_str(row.get("blockers")) or _list_of_str(row.get("warnings"))
        lines.append(
            f"| `{symbol}` | `{row.get('status')}` | `{row.get('rows')}` | `{row.get('start')}` | `{row.get('end')}` | `{row.get('staleness_days')}` | `{issues[0] if issues else ''}` |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Warnings", ""])
    warnings = _list_of_str(payload.get("warnings"))
    lines.extend([f"- `{item}`" for item in warnings] if warnings else ["- None"])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report validates local ETF EOD kline data only.",
            "- It does not repair data, validate alpha, or unlock paper/live trading.",
            "- Any blocked symbol must stop promotion until repaired and rescanned.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _unsafe_true(payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    unsafe = []
    unsafe_keys = {"live_order_allowed", "paper_simulation_allowed", "private_endpoint_used", "private_endpoint_allowed", "order_endpoint_used", "order_endpoint_allowed", "real_order_submitted", "token_written_to_artifacts"}
    for root_name, payload in payloads.items():
        for path, value in _walk(payload):
            if path.split(".")[-1] in unsafe_keys and value is True:
                unsafe.append(f"{root_name}.{path}=true")
    return unsafe


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


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


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _git(args: list[str], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    value = result.stdout.strip()
    return value or None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--kline-root", type=Path, default=DEFAULT_KLINE_ROOT)
    parser.add_argument("--tiingo-import-report", type=Path, default=DEFAULT_TIINGO_IMPORT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--max-staleness-days", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_equity_etf_kline_quality_daily_report(
        repo_root=args.repo_root,
        kline_root=args.kline_root,
        tiingo_import_report=args.tiingo_import_report,
        output=args.output,
        markdown_output=args.markdown_output,
        max_staleness_days=args.max_staleness_days,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
