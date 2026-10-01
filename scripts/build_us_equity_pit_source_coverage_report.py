#!/usr/bin/env python3
"""Assess whether available local sources can satisfy US equity PIT CSV gates."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_pit_source_coverage_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_source_coverage_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据源覆盖评估.md")
DEFAULT_TIINGO_KLINE_ROOT = Path("data/external/us_equity_eod/tiingo/kline")
DEFAULT_EXTERNAL_KLINE_ROOT = Path("D:/Trading/PythonApplication1/data_cache_lake/kline")
DEFAULT_EXTERNAL_MACRO = Path("D:/Trading/PythonApplication1/data_cache_lake/macro/FRED_MACRO.parquet")
DEFAULT_AKSHARE_CACHE_ROOT = Path("D:/Trading/PythonApplication1/data_cache")
REQUIRED_PIT_FILES = {
    "universe_membership_events.csv": {
        "required_role": "point_in_time_universe_membership",
        "can_be_derived_from_ohlcv": False,
        "reason": "OHLCV files do not prove historical universe add/remove events or survivorship-clean membership.",
    },
    "delisted_symbols.csv": {
        "required_role": "delisted_security_coverage",
        "can_be_derived_from_ohlcv": False,
        "reason": "Current ETF/price caches do not contain complete delisted-symbol coverage.",
    },
    "corporate_actions.csv": {
        "required_role": "corporate_action_event_source",
        "can_be_derived_from_ohlcv": False,
        "reason": "Adjusted bars alone do not provide event-level split/dividend/symbol-change lineage.",
    },
    "symbol_mapping.csv": {
        "required_role": "identifier_mapping",
        "can_be_derived_from_ohlcv": False,
        "reason": "Ticker-only bars do not provide stable security_id, FIGI, CIK, CUSIP, PERMNO, or mapping intervals.",
    },
    "adjustment_replay.csv": {
        "required_role": "raw_to_adjusted_replay",
        "can_be_derived_from_ohlcv": "partial",
        "reason": "Raw and adjusted closes can support a replay only if the source preserves both and the adjustment factors are licensed and reproducible.",
    },
    "macro_release_calendar.csv": {
        "required_role": "macro_publication_timing",
        "can_be_derived_from_ohlcv": False,
        "reason": "FRED value history is not enough; the gate needs release/available timestamps for point-in-time macro use.",
    },
}


def build_us_equity_pit_source_coverage_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    tiingo_kline_root: Path = DEFAULT_TIINGO_KLINE_ROOT,
    external_kline_root: Path = DEFAULT_EXTERNAL_KLINE_ROOT,
    external_macro: Path = DEFAULT_EXTERNAL_MACRO,
    akshare_cache_root: Path = DEFAULT_AKSHARE_CACHE_ROOT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    sources = [
        _source_profile("tiingo_eod_parquet", _resolve(root, tiingo_kline_root), source_type="kline_parquet_dir"),
        _source_profile("external_local_kline_parquet", _resolve(root, external_kline_root), source_type="kline_parquet_dir"),
        _source_profile("external_fred_macro_parquet", _resolve(root, external_macro), source_type="macro_parquet_file"),
        _source_profile("akshare_csv_cache", _resolve(root, akshare_cache_root), source_type="csv_cache_dir"),
        _source_profile("ibkr_market_data", Path("not_configured"), source_type="broker_market_data"),
    ]
    coverage = [_pit_file_coverage(filename, spec, sources) for filename, spec in REQUIRED_PIT_FILES.items()]
    satisfied = [row for row in coverage if row["coverage_status"] == "satisfied"]
    partial = [row for row in coverage if row["coverage_status"] == "partial"]
    missing = [row for row in coverage if row["coverage_status"] == "missing"]
    status = "source_coverage_pit_ready" if len(satisfied) == len(coverage) else "source_coverage_partial_not_pit_clean"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "decision": "do_not_mark_production_pit_clean_from_price_or_macro_cache_only",
        "summary": {
            "required_file_count": len(coverage),
            "satisfied_count": len(satisfied),
            "partial_count": len(partial),
            "missing_count": len(missing),
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
        "sources": sources,
        "pit_file_coverage": coverage,
        "usable_now": [
            "Use Tiingo/AkShare/local parquet as research price and macro value inputs after freshness and quality gates pass.",
            "Use these sources to help build adjustment_replay only if raw and adjusted closes plus factors are explicitly available and licensed.",
        ],
        "still_required": [
            "Licensed PIT universe membership history.",
            "Delisted-symbol coverage.",
            "Event-level corporate actions.",
            "Stable identifier mapping.",
            "Macro release calendar with available_time_utc.",
        ],
        "guardrails": {
            "assessment_only": True,
            "files_copied": False,
            "vendor_data_imported": False,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _pit_file_coverage(filename: str, spec: Mapping[str, Any], sources: list[Mapping[str, Any]]) -> dict[str, Any]:
    if filename == "adjustment_replay.csv":
        has_price_source = any(source["exists"] and source["source_type"] in {"kline_parquet_dir", "csv_cache_dir"} for source in sources)
        return {
            "filename": filename,
            "required_role": spec["required_role"],
            "coverage_status": "partial" if has_price_source else "missing",
            "candidate_sources": [source["source_id"] for source in sources if source["exists"] and source["source_type"] in {"kline_parquet_dir", "csv_cache_dir"}],
            "reason": spec["reason"],
            "promotion_clean_satisfied": False,
        }
    if filename == "macro_release_calendar.csv":
        has_macro_values = any(source["exists"] and source["source_type"] == "macro_parquet_file" for source in sources)
        return {
            "filename": filename,
            "required_role": spec["required_role"],
            "coverage_status": "partial" if has_macro_values else "missing",
            "candidate_sources": [source["source_id"] for source in sources if source["exists"] and source["source_type"] == "macro_parquet_file"],
            "reason": spec["reason"],
            "promotion_clean_satisfied": False,
        }
    return {
        "filename": filename,
        "required_role": spec["required_role"],
        "coverage_status": "missing",
        "candidate_sources": [],
        "reason": spec["reason"],
        "promotion_clean_satisfied": False,
    }


def _source_profile(source_id: str, path: Path, *, source_type: str) -> dict[str, Any]:
    exists = path.exists()
    files = []
    columns: list[str] = []
    if exists and path.is_dir():
        candidates = sorted([item for item in path.iterdir() if item.is_file() and item.suffix.lower() in {".parquet", ".csv"}])
        files = [item.name for item in candidates[:10]]
        if candidates:
            columns = _columns(candidates[0])
    elif exists and path.is_file():
        files = [path.name]
        columns = _columns(path)
    return {
        "source_id": source_id,
        "source_type": source_type,
        "path": path.as_posix(),
        "exists": exists,
        "sample_files": files,
        "sample_columns": columns,
    }


def _columns(path: Path) -> list[str]:
    try:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                return [str(item) for item in next(csv.reader(handle), [])]
        if path.suffix.lower() == ".parquet":
            import pandas as pd

            return [str(item) for item in pd.read_parquet(path).columns]
    except Exception:
        return []
    return []


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity PIT 数据源覆盖评估",
        "",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- satisfied: `{payload.get('summary', {}).get('satisfied_count')}` / `{payload.get('summary', {}).get('required_file_count')}`",
        f"- partial: `{payload.get('summary', {}).get('partial_count')}`",
        f"- missing: `{payload.get('summary', {}).get('missing_count')}`",
        "",
        "## Coverage",
        "",
        "| file | status | candidate sources | reason |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload.get("pit_file_coverage", []):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"| `{row.get('filename')}` | `{row.get('coverage_status')}` | `{', '.join(row.get('candidate_sources', []))}` | {row.get('reason')} |"
        )
    lines.extend(["", "## Guardrails", "", "- assessment only", "- no files copied", "- live_order_allowed=false"])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_us_equity_pit_source_coverage_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
