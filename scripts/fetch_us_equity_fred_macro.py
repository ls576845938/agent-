#!/usr/bin/env python3
"""Fetch FRED macro series for the US ETF rotation system.

Uses FRED public graph CSV endpoints by default. This is market/macro data only:
no broker, private, order, paper, or live endpoint is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_fred_macro_import_report_v1"
SERIES = ("WALCL", "WTREGEN", "RRPONTSYD", "BAMLC0A0CM", "DGS10", "DGS2")
DEFAULT_OUTPUT_DATA = Path("data/external/us_equity_macro/fred_macro.csv")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json")
DEFAULT_START_DATE = "2000-01-01"
FRED_PUBLIC_USER_AGENT = "curl/8.0.0 QuantSystem-PublicData/1.0"


def fetch_us_equity_fred_macro(
    *,
    repo_root: Path | None = None,
    output_data: Path = DEFAULT_OUTPUT_DATA,
    report_path: Path = DEFAULT_REPORT,
    start_date: str = DEFAULT_START_DATE,
    offline_source_dir: Path | None = None,
    api_key: str = "",
    timeout_seconds: float = 20.0,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    data_abs = _resolve(root, output_data)
    report_abs = _resolve(root, report_path)
    frames: dict[str, pd.Series] = {}
    realtime_starts: list[pd.Series] = []
    realtime_ends: list[pd.Series] = []
    series_reports = []
    blockers: list[str] = []

    for series_id in SERIES:
        try:
            frame, source = _load_series(
                series_id,
                start_date=start_date,
                offline_source_dir=_resolve(root, offline_source_dir) if offline_source_dir else None,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
            if frame.empty:
                raise ValueError("empty series")
            value_col = series_id if series_id in frame.columns else frame.columns[-1]
            series = pd.to_numeric(frame[value_col].replace(".", pd.NA), errors="coerce")
            series.index = pd.to_datetime(frame["observation_date"], utc=True)
            series = series.sort_index().dropna()
            if series.empty:
                raise ValueError("no numeric observations")
            frames[series_id] = series.rename(series_id)
            if "realtime_start" in frame.columns:
                realtime_start = pd.to_datetime(frame["realtime_start"], utc=True, errors="coerce")
                realtime_start.index = pd.to_datetime(frame["observation_date"], utc=True)
                realtime_starts.append(realtime_start.sort_index().rename(series_id))
            if "realtime_end" in frame.columns:
                realtime_end = pd.to_datetime(frame["realtime_end"], utc=True, errors="coerce")
                realtime_end.index = pd.to_datetime(frame["observation_date"], utc=True)
                realtime_ends.append(realtime_end.sort_index().rename(series_id))
            series_reports.append(
                {
                    "series_id": series_id,
                    "status": "pass",
                    "source": source,
                    "rows": int(series.shape[0]),
                    "start": series.index.min().date().isoformat(),
                    "end": series.index.max().date().isoformat(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - report fail-closed details
            blockers.append(f"fred_series_fetch_failed:{series_id}")
            series_reports.append(
                {
                    "series_id": series_id,
                    "status": "failed",
                    "error": str(exc),
                    "source": "offline" if offline_source_dir else "fred_graph_csv",
                }
            )

    combined = pd.DataFrame(frames).sort_index()
    if not combined.empty:
        combined = combined.loc[pd.Timestamp(start_date, tz="UTC") :]
    missing_columns = [series for series in SERIES if series not in combined.columns]
    if missing_columns:
        blockers.append("fred_macro_required_columns_missing")
    latest_by_series = {
        series: combined[series].dropna().index.max().date().isoformat()
        for series in combined.columns
        if not combined[series].dropna().empty
    }
    latest_common = None
    complete = combined.dropna(how="any") if not combined.empty and not missing_columns else pd.DataFrame()
    if not complete.empty:
        latest_common = complete.index.max().date().isoformat()
    else:
        blockers.append("fred_macro_no_complete_common_rows")

    if not blockers and not combined.empty:
        out = combined.copy()
        if realtime_starts:
            starts = pd.concat(realtime_starts, axis=1, sort=True).reindex(out.index).ffill()
            out["realtime_start"] = starts.max(axis=1).dt.strftime("%Y-%m-%d")
        if realtime_ends:
            ends = pd.concat(realtime_ends, axis=1, sort=True).reindex(out.index).ffill()
            out["realtime_end"] = ends.min(axis=1).dt.strftime("%Y-%m-%d")
        out.insert(0, "timestamp_utc", out.index.strftime("%Y-%m-%dT%H:%M:%SZ"))
        data_abs.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(data_abs, index=False, encoding="utf-8")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "pass" if not blockers else "blocked",
        "provider": "FRED",
        "source_type": "offline_fixture" if offline_source_dir else ("fred_api_observations" if api_key else "public_graph_csv"),
        "series": list(SERIES),
        "series_reports": series_reports,
        "row_count": int(combined.shape[0]) if not combined.empty else 0,
        "latest_by_series": latest_by_series,
        "latest_common_date": latest_common,
        "macro_lag_days": 2,
        "publication_lag_policy": "research pipeline must shift macro data by configured macro_lag_days before signal use",
        "output_data": _relpath(data_abs, root),
        "blockers": _dedupe(blockers),
        "guardrails": {
            "macro_data_only": True,
            "api_key_required": False,
            "api_key_used_for_macro_data": bool(api_key),
            "token_written_to_artifacts": False,
            "broker_endpoint_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
            "real_order_submitted": False,
        },
    }
    _write_json(report_abs, payload)
    return payload


def _load_series(
    series_id: str,
    *,
    start_date: str,
    offline_source_dir: Path | None,
    api_key: str,
    timeout_seconds: float,
) -> tuple[pd.DataFrame, str]:
    if offline_source_dir:
        path = offline_source_dir / f"{series_id}.csv"
        frame = pd.read_csv(path)
        return _normalize_frame(series_id, frame), str(path)
    if api_key:
        params = urllib.parse.urlencode(
            {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start_date,
            }
        )
        url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"FRED API request failed: {exc}") from exc
        observations = payload.get("observations", [])
        frame = pd.DataFrame(
            {
                "observation_date": [row.get("date") for row in observations],
                series_id: [row.get("value") for row in observations],
                "realtime_start": [row.get("realtime_start") for row in observations],
                "realtime_end": [row.get("realtime_end") for row in observations],
            }
        )
        return _normalize_frame(series_id, frame), "fred_api_observations"
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}"
    request = urllib.request.Request(url, headers={"User-Agent": FRED_PUBLIC_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"FRED request failed: {exc}") from exc
    from io import BytesIO

    frame = pd.read_csv(BytesIO(data))
    return _normalize_frame(series_id, frame), url


def _normalize_frame(series_id: str, frame: pd.DataFrame) -> pd.DataFrame:
    if "observation_date" not in frame.columns:
        first = frame.columns[0]
        frame = frame.rename(columns={first: "observation_date"})
    if series_id not in frame.columns:
        value_cols = [col for col in frame.columns if col != "observation_date"]
        if value_cols:
            frame = frame.rename(columns={value_cols[-1]: series_id})
    columns = ["observation_date", series_id]
    for optional in ("realtime_start", "realtime_end"):
        if optional in frame.columns:
            columns.append(optional)
    return frame[columns]


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


def _resolve(root: Path, path: Path | None) -> Path:
    if path is None:
        raise ValueError("path is required")
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch US equity FRED macro data.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-data", default=str(DEFAULT_OUTPUT_DATA))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--offline-source-dir", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = fetch_us_equity_fred_macro(
        repo_root=Path(args.repo_root),
        output_data=Path(args.output_data),
        report_path=Path(args.report_path),
        start_date=args.start_date,
        offline_source_dir=Path(args.offline_source_dir) if args.offline_source_dir else None,
        api_key=args.api_key or os.environ.get("FRED_API_KEY", ""),
        timeout_seconds=args.timeout_seconds,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
