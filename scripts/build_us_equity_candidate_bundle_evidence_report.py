#!/usr/bin/env python3
"""Inspect research data that could feed a US equity production PIT bundle.

This report is intentionally read-only. It inventories local Tiingo ETF bars
and FRED macro files, then explains which production-bundle requirements remain
unproven. It never promotes research data to production evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_candidate_bundle_evidence_report_v1"
DEFAULT_TIINGO_KLINE_ROOT = Path("data/external/us_equity_eod/tiingo/kline")
DEFAULT_FRED_MACRO = Path("data/external/us_equity_macro/fred_macro.csv")
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_candidate_bundle_evidence_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产数据候选证据诊断.md")


def build_us_equity_candidate_bundle_evidence_report(
    *,
    repo_root: Path | None = None,
    tiingo_kline_root: Path = DEFAULT_TIINGO_KLINE_ROOT,
    fred_macro_path: Path = DEFAULT_FRED_MACRO,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tiingo_root = _resolve(root, tiingo_kline_root)
    fred_path = _resolve(root, fred_macro_path)

    tiingo = _inspect_tiingo_klines(tiingo_root, root)
    fred = _inspect_fred_macro(fred_path, root)
    evidence = {
        "price_bars": bool(tiingo["available"]),
        "raw_and_adjusted_prices": bool(tiingo["raw_and_adjusted_prices"]),
        "volume": bool(tiingo["volume_available"]),
        "derived_split_dividend_fields": bool(tiingo["split_dividend_fields_available"]),
        "fred_macro_csv": bool(fred["available"]),
        "fred_realtime_columns": bool(fred["realtime_columns_available"]),
    }
    missing = _missing_contract_groups(evidence)
    blockers = _blockers(tiingo, fred, missing)
    status = "candidate_evidence_ready_for_manual_bundle_build" if tiingo["available"] and fred["available"] else "candidate_evidence_blocked"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "decision": "use_as_manual_bundle_build_input_only_do_not_promote",
        "source_type": "research_price_bars_and_macro",
        "tiingo_kline": tiingo,
        "fred_macro": fred,
        "evidence_available": evidence,
        "missing_production_contract_groups": missing,
        "blockers": blockers,
        "next_actions": [
            "Acquire licensed PIT universe membership, delisting, identifier mapping, corporate action event source, adjustment replay, and macro release calendar evidence.",
            "Build data/external/us_equity_lineage/bundles/<bundle_id> from licensed provider files, not from this diagnostic report.",
            "Run python scripts/build_us_equity_local_csv_bundle_manifest.py against the real bundle root.",
            "Run python scripts/build_us_equity_production_bundle_activation_report.py --bundle-id <bundle_id> --license-reviewed.",
        ],
        "guardrails": {
            "diagnostic_only": True,
            "vendor_data_written_by_this_report": False,
            "production_bundle_written_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _inspect_tiingo_klines(path: Path, repo_root: Path) -> dict[str, Any]:
    files = sorted(path.glob("*.parquet")) if path.exists() else []
    symbols: list[str] = []
    ranges: list[dict[str, Any]] = []
    required = {"datetime", "symbol", "Open", "High", "Low", "Close", "Volume", "RawClose", "RawVolume"}
    raw_adjusted = False
    volume = False
    split_dividend_fields = False
    split_event_rows = 0
    dividend_event_rows = 0
    columns_seen: set[str] = set()
    errors: list[str] = []
    for file in files:
        try:
            df = pd.read_parquet(file)
        except Exception as exc:  # noqa: BLE001 - report and continue.
            errors.append(f"{file.name}:{type(exc).__name__}")
            continue
        cols = {str(col) for col in df.columns}
        columns_seen.update(cols)
        missing = sorted(required - cols)
        symbol = str(df["symbol"].dropna().iloc[0]) if "symbol" in df.columns and not df.empty else file.stem
        symbols.append(symbol)
        date_series = pd.to_datetime(df["datetime"], utc=True, errors="coerce") if "datetime" in df.columns else pd.Series(dtype="datetime64[ns, UTC]")
        start = date_series.min()
        end = date_series.max()
        if {"Close", "RawClose"}.issubset(cols):
            raw_adjusted = True
        if {"Volume", "RawVolume"}.issubset(cols):
            volume = True
        if {"DivCash", "SplitFactor"}.issubset(cols):
            split_dividend_fields = True
            dividend_event_rows += int((pd.to_numeric(df["DivCash"], errors="coerce").fillna(0) != 0).sum())
            split_event_rows += int((pd.to_numeric(df["SplitFactor"], errors="coerce").fillna(1) != 1).sum())
        ranges.append(
            {
                "symbol": symbol,
                "path": _relpath(file, repo_root),
                "rows": int(len(df)),
                "start": start.date().isoformat() if pd.notna(start) else None,
                "end": end.date().isoformat() if pd.notna(end) else None,
                "required_columns_missing": missing,
            }
        )
    starts = sorted(str(item["start"]) for item in ranges if item.get("start"))
    ends = sorted(str(item["end"]) for item in ranges if item.get("end"))
    return {
        "available": bool(files and ranges),
        "root": _relpath(path, repo_root),
        "parquet_file_count": len(files),
        "symbol_count": len(set(symbols)),
        "symbols": sorted(set(symbols)),
        "date_range": {"start": starts[0] if starts else None, "end": ends[-1] if ends else None},
        "columns_seen": sorted(columns_seen),
        "raw_and_adjusted_prices": raw_adjusted,
        "volume_available": volume,
        "split_dividend_fields_available": split_dividend_fields,
        "derived_split_event_rows": split_event_rows,
        "derived_dividend_event_rows": dividend_event_rows,
        "sample_files": ranges[:10],
        "read_errors": errors,
    }


def _inspect_fred_macro(path: Path, repo_root: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "available": False,
            "path": _relpath(path, repo_root),
            "rows": 0,
            "columns": [],
            "date_range": {"start": None, "end": None},
            "realtime_columns_available": False,
            "series_columns": [],
            "blockers": ["fred_macro_csv_missing"],
        }
    df = pd.read_csv(path)
    date_col = "timestamp_utc" if "timestamp_utc" in df.columns else None
    dates = pd.to_datetime(df[date_col], utc=True, errors="coerce") if date_col else pd.Series(dtype="datetime64[ns, UTC]")
    realtime = {"realtime_start", "realtime_end"}.issubset(set(df.columns))
    series = [str(col) for col in df.columns if col not in {"timestamp_utc", "realtime_start", "realtime_end"}]
    blockers = []
    if not realtime:
        blockers.append("fred_realtime_columns_missing")
    return {
        "available": True,
        "path": _relpath(path, repo_root),
        "rows": int(len(df)),
        "columns": [str(col) for col in df.columns],
        "date_range": {
            "start": dates.min().date().isoformat() if len(dates) and pd.notna(dates.min()) else None,
            "end": dates.max().date().isoformat() if len(dates) and pd.notna(dates.max()) else None,
        },
        "realtime_columns_available": realtime,
        "series_columns": series,
        "blockers": blockers,
    }


def _missing_contract_groups(evidence: Mapping[str, bool]) -> list[str]:
    missing = [
        "pit_universe_membership_events",
        "delisted_symbols",
        "stable_identifier_mapping",
        "licensed_corporate_action_event_source",
        "adjustment_replay_file",
        "macro_release_calendar_with_available_time",
        "explicit_production_bundle_selection",
        "manual_license_review",
    ]
    if not evidence.get("price_bars"):
        missing.append("research_price_bars")
    if not evidence.get("fred_macro_csv"):
        missing.append("fred_macro_csv")
    return missing


def _blockers(tiingo: Mapping[str, Any], fred: Mapping[str, Any], missing: list[str]) -> list[str]:
    blockers = [f"missing:{item}" for item in missing]
    if not tiingo.get("available"):
        blockers.append("tiingo_research_price_bars_missing")
    if tiingo.get("read_errors"):
        blockers.append("tiingo_parquet_read_errors")
    if not fred.get("available"):
        blockers.append("fred_macro_csv_missing")
    blockers.extend(str(item) for item in fred.get("blockers", []) if item)
    blockers.extend(
        [
            "research_data_not_point_in_time_bundle",
            "candidate_evidence_does_not_grant_promotion_clean",
            "paper_live_must_remain_locked",
        ]
    )
    return _dedupe(blockers)


def _markdown(payload: Mapping[str, Any]) -> str:
    tiingo = dict(payload.get("tiingo_kline", {}))
    fred = dict(payload.get("fred_macro", {}))
    lines = [
        "# US Equity 生产数据候选证据诊断",
        "",
        f"生成时间：`{payload.get('generated_at')}`",
        "",
        f"- 状态：`{payload.get('status')}`",
        f"- Tiingo ETF parquet：`{tiingo.get('symbol_count')}` symbols，`{tiingo.get('date_range')}`",
        f"- FRED macro CSV：`{fred.get('rows')}` rows，`{fred.get('date_range')}`",
        "- 结论：本报告只说明现有研究数据可作为人工构建 bundle 的输入，不能证明 production PIT。",
        "",
        "## Missing Production Contract Groups",
        "",
    ]
    lines.extend(f"- `{item}`" for item in payload.get("missing_production_contract_groups", []))
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- `{item}`" for item in payload.get("blockers", []))
    lines.extend(["", "## Guardrails", "", "- 不写入 vendor bundle。", "- 不授权 paper/live。", "- 不调用 broker/private/order endpoint。", ""])
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity candidate production-bundle evidence report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--tiingo-kline-root", default=str(DEFAULT_TIINGO_KLINE_ROOT))
    parser.add_argument("--fred-macro-path", default=str(DEFAULT_FRED_MACRO))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_candidate_bundle_evidence_report(
        repo_root=Path(args.repo_root),
        tiingo_kline_root=Path(args.tiingo_kline_root),
        fred_macro_path=Path(args.fred_macro_path),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
