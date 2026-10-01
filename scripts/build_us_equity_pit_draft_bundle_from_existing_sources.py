#!/usr/bin/env python3
"""Build a research-only draft PIT CSV bundle from existing local sources.

The output is intentionally written outside the manual vendor incoming drop.
It helps the operator review what can be derived from Tiingo/FRED/local caches,
but it is not licensed production PIT evidence and must not unlock paper/live.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


SCHEMA_VERSION = "us_equity_pit_draft_bundle_report_v1"
DEFAULT_OUTPUT_DIR = Path("data/external/us_equity_lineage/draft_from_existing_sources")
DEFAULT_REPORT = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_draft_bundle_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity PIT 草稿补全报告.md")
DEFAULT_TIINGO_KLINE_ROOT = Path("data/external/us_equity_eod/tiingo/kline")
DEFAULT_FRED_MACRO = Path("D:/Trading/PythonApplication1/data_cache_lake/macro/FRED_MACRO.parquet")

HEADERS = {
    "universe_membership_events.csv": [
        "security_id",
        "ticker",
        "universe_name",
        "event_type",
        "effective_date",
        "end_date",
        "source_record_id",
    ],
    "delisted_symbols.csv": [
        "security_id",
        "ticker",
        "delisting_date",
        "delisting_reason",
        "last_trade_date",
        "delisting_return",
        "source_record_id",
    ],
    "corporate_actions.csv": [
        "security_id",
        "ticker",
        "event_type",
        "ex_date",
        "effective_date",
        "ratio",
        "cash_amount",
        "old_symbol",
        "new_symbol",
        "source_record_id",
    ],
    "symbol_mapping.csv": [
        "security_id",
        "ticker",
        "start_date",
        "end_date",
        "figi",
        "cik",
        "cusip",
        "permno",
        "exchange",
        "source_record_id",
    ],
    "adjustment_replay.csv": [
        "security_id",
        "ticker",
        "date",
        "raw_close",
        "adjusted_close",
        "split_factor",
        "dividend_adjustment",
        "total_adjustment_factor",
        "replay_adjusted_close",
        "replay_error",
        "source_record_id",
    ],
    "macro_release_calendar.csv": [
        "series_id",
        "observation_period_start",
        "observation_period_end",
        "release_date",
        "available_time_utc",
        "source_record_id",
    ],
}


def build_us_equity_pit_draft_bundle(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_output: Path = DEFAULT_REPORT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    tiingo_kline_root: Path = DEFAULT_TIINGO_KLINE_ROOT,
    fred_macro: Path = DEFAULT_FRED_MACRO,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    out_dir = _resolve(root, output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kline_root = _resolve(root, tiingo_kline_root)
    fred_path = _resolve(root, fred_macro)
    symbol_frames = _load_symbol_frames(kline_root)
    outputs = {
        "symbol_mapping.csv": _write_csv(out_dir / "symbol_mapping.csv", HEADERS["symbol_mapping.csv"], _symbol_mapping_rows(symbol_frames)),
        "universe_membership_events.csv": _write_csv(
            out_dir / "universe_membership_events.csv",
            HEADERS["universe_membership_events.csv"],
            _universe_rows(symbol_frames),
        ),
        "corporate_actions.csv": _write_csv(
            out_dir / "corporate_actions.csv",
            HEADERS["corporate_actions.csv"],
            _corporate_action_rows(symbol_frames),
        ),
        "adjustment_replay.csv": _write_csv(
            out_dir / "adjustment_replay.csv",
            HEADERS["adjustment_replay.csv"],
            _adjustment_replay_rows(symbol_frames),
        ),
        "macro_release_calendar.csv": _write_csv(
            out_dir / "macro_release_calendar.csv",
            HEADERS["macro_release_calendar.csv"],
            _macro_release_rows(fred_path),
        ),
        "delisted_symbols.csv": _write_csv(out_dir / "delisted_symbols.csv", HEADERS["delisted_symbols.csv"], []),
    }
    coverage = {
        name: {
            "path": _relpath(out_dir / name, root),
            "row_count": meta["row_count"],
            "status": _draft_status_for(name, meta["row_count"]),
        }
        for name, meta in outputs.items()
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "draft_bundle_built_research_only",
        "decision": "review_draft_do_not_copy_to_manual_vendor_drop_without_license_and_pit_review",
        "source_inputs": {
            "tiingo_kline_root": _relpath(kline_root, root),
            "fred_macro": _relpath(fred_path, root),
            "symbol_count": len(symbol_frames),
        },
        "csv_outputs": coverage,
        "production_pit_limitations": [
            "universe membership is a static ETF research pool inferred from available files, not provider PIT membership history.",
            "delisted_symbols.csv is header-only because no delisted security source is available.",
            "corporate actions are inferred only from Tiingo DivCash/SplitFactor fields.",
            "symbol mapping uses synthetic ETF:<ticker> security_id and lacks FIGI/CIK/CUSIP/PERMNO.",
            "macro release calendar uses observation dates as an approximation and does not prove true release timestamps.",
        ],
        "guardrails": {
            "draft_only": True,
            "written_to_manual_vendor_drop": False,
            "license_reviewed_by_this_script": False,
            "promotion_clean_granted": False,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, report_output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
            "draft_dir": _relpath(out_dir, root),
        },
    }
    _write_json(_resolve(root, report_output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _load_symbol_frames(kline_root: Path) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    if not kline_root.exists():
        return frames
    for path in sorted(kline_root.glob("*.parquet")):
        frame = pd.read_parquet(path)
        symbol = str(frame.get("symbol", pd.Series([path.stem])).dropna().iloc[0] if len(frame) else path.stem)
        if "datetime" not in frame.columns:
            continue
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["datetime"], utc=True).dt.date.astype(str)
        frames[symbol] = frame.sort_values("date")
    return frames


def _security_id(symbol: str) -> str:
    return f"ETF:{symbol}"


def _symbol_mapping_rows(frames: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for symbol, frame in frames.items():
        rows.append(
            {
                "security_id": _security_id(symbol),
                "ticker": symbol,
                "start_date": str(frame["date"].min()),
                "end_date": "9999-12-31",
                "figi": "",
                "cik": "",
                "cusip": "",
                "permno": "",
                "exchange": "UNKNOWN",
                "source_record_id": f"draft_symbol_mapping_{symbol}",
            }
        )
    return rows


def _universe_rows(frames: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for symbol, frame in frames.items():
        rows.append(
            {
                "security_id": _security_id(symbol),
                "ticker": symbol,
                "universe_name": "ETF_ROTATION_POOL",
                "event_type": "list",
                "effective_date": str(frame["date"].min()),
                "end_date": "9999-12-31",
                "source_record_id": f"draft_universe_{symbol}",
            }
        )
    return rows


def _corporate_action_rows(frames: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for symbol, frame in frames.items():
        if "DivCash" in frame.columns:
            dividends = frame[pd.to_numeric(frame["DivCash"], errors="coerce").fillna(0) != 0]
            for _, row in dividends.iterrows():
                rows.append(
                    {
                        "security_id": _security_id(symbol),
                        "ticker": symbol,
                        "event_type": "dividend",
                        "ex_date": row["date"],
                        "effective_date": row["date"],
                        "ratio": "",
                        "cash_amount": row.get("DivCash", ""),
                        "old_symbol": "",
                        "new_symbol": "",
                        "source_record_id": f"draft_dividend_{symbol}_{row['date']}",
                    }
                )
        if "SplitFactor" in frame.columns:
            splits = frame[pd.to_numeric(frame["SplitFactor"], errors="coerce").fillna(1) != 1]
            for _, row in splits.iterrows():
                rows.append(
                    {
                        "security_id": _security_id(symbol),
                        "ticker": symbol,
                        "event_type": "split",
                        "ex_date": row["date"],
                        "effective_date": row["date"],
                        "ratio": row.get("SplitFactor", ""),
                        "cash_amount": "",
                        "old_symbol": "",
                        "new_symbol": "",
                        "source_record_id": f"draft_split_{symbol}_{row['date']}",
                    }
                )
    return rows


def _adjustment_replay_rows(frames: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows = []
    for symbol, frame in frames.items():
        required = {"RawClose", "Close"}
        if not required <= set(frame.columns):
            continue
        for _, row in frame.iterrows():
            raw = _float(row.get("RawClose"))
            adjusted = _float(row.get("Close"))
            factor = adjusted / raw if raw else 0.0
            replay = raw * factor if raw else 0.0
            rows.append(
                {
                    "security_id": _security_id(symbol),
                    "ticker": symbol,
                    "date": row["date"],
                    "raw_close": raw,
                    "adjusted_close": adjusted,
                    "split_factor": _float(row.get("SplitFactor"), default=1.0),
                    "dividend_adjustment": _float(row.get("DivCash"), default=0.0),
                    "total_adjustment_factor": factor,
                    "replay_adjusted_close": replay,
                    "replay_error": abs(adjusted - replay),
                    "source_record_id": f"draft_adjustment_{symbol}_{row['date']}",
                }
            )
    return rows


def _macro_release_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    if "datetime" not in frame.columns:
        return []
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["datetime"], utc=True).dt.date.astype(str)
    rows = []
    series_cols = [col for col in frame.columns if col not in {"datetime", "date"}]
    for _, row in frame.iterrows():
        for series_id in series_cols:
            if pd.isna(row.get(series_id)):
                continue
            date = row["date"]
            rows.append(
                {
                    "series_id": series_id,
                    "observation_period_start": date,
                    "observation_period_end": date,
                    "release_date": date,
                    "available_time_utc": f"{date}T23:59:59Z",
                    "source_record_id": f"draft_macro_release_{series_id}_{date}",
                }
            )
    return rows


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _draft_status_for(filename: str, row_count: int) -> str:
    if filename in {"adjustment_replay.csv", "corporate_actions.csv"} and row_count > 0:
        return "draft_from_tiingo_fields"
    if filename in {"symbol_mapping.csv", "universe_membership_events.csv"} and row_count > 0:
        return "synthetic_research_pool_only"
    if filename == "macro_release_calendar.csv" and row_count > 0:
        return "approximate_release_calendar_not_pit_clean"
    return "missing_or_header_only"


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return {"path": path.as_posix(), "row_count": len(rows)}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


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


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity PIT 草稿补全报告",
        "",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- draft_dir: `{payload.get('outputs', {}).get('draft_dir')}`",
        "",
        "## CSV Outputs",
        "",
        "| file | rows | status |",
        "| --- | ---: | --- |",
    ]
    for name, meta in payload.get("csv_outputs", {}).items():
        if isinstance(meta, Mapping):
            lines.append(f"| `{name}` | `{meta.get('row_count')}` | `{meta.get('status')}` |")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in payload.get("production_pit_limitations", []))
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_us_equity_pit_draft_bundle(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        report_output=args.report_output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({"status": payload["status"], "draft_dir": payload["outputs"]["draft_dir"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
