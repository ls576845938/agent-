#!/usr/bin/env python3
"""Fetch Tiingo IEX 1-minute bars for US equity research.

Tiingo IEX intraday bars are IEX-only raw bars. This script stores raw minute
data and reports whether PIT adjustment replay is required before strategy use.
It never writes API tokens to artifacts and has no broker/order side effects.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd


SCHEMA_VERSION = "us_equity_tiingo_iex_minute_import_report_v1"
DEFAULT_OUTPUT_ROOT = Path("data/external/us_equity_intraday/tiingo_iex/interval=1m")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/tiingo_iex_minute_import_report.json")
DEFAULT_START_DATE = "2016-07-06"
DEFAULT_MAX_STALENESS_DAYS = 10
DEFAULT_EXTREME_RETURN_THRESHOLD = 0.20
DEFAULT_CHUNK_MONTHS = 12
TIINGO_IEX_URL = "https://api.tiingo.com/iex/{symbol}/prices"

Fetcher = Callable[[str, str, str], list[Mapping[str, Any]]]


def import_tiingo_iex_minute_bars(
    *,
    repo_root: Path,
    symbols: Iterable[str],
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    execute_network: bool = False,
    request_sleep_seconds: float = 0.25,
    request_timeout_seconds: float = 30.0,
    chunk_hard_timeout_seconds: float = 0.0,
    max_new_chunks_per_run: int = 0,
    chunk_months: int = DEFAULT_CHUNK_MONTHS,
    skip_existing: bool = True,
    preserve_existing_kline_on_partial: bool = True,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    extreme_return_threshold: float = DEFAULT_EXTREME_RETURN_THRESHOLD,
    min_coverage_ratio: float = 0.0,
    generated_at: str | None = None,
    token: str | None = None,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or _utc_now()
    selected_symbols = tuple(_unique(symbols))
    effective_end_date = end_date or generated[:10]
    output_abs = _resolve(root, output_root)
    report_abs = _resolve(root, report_path)
    kline_root = output_abs / "kline"
    chunk_root = output_abs / "chunks"
    chunks = _date_chunks(start_date, effective_end_date, max(1, int(chunk_months)))
    local_env_token = _load_local_env_value(root, "TIINGO_API_KEY")

    if not execute_network:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "dry_run",
            "network_called": False,
            "writes_performed": False,
            "provider": "tiingo_iex",
            "asset": "us_equity",
            "source_type": "market_data_intraday_1m_iex_only_raw",
            "symbols": list(selected_symbols),
            "symbol_count": len(selected_symbols),
            "interval_requested": "1min",
            "start_date": start_date,
            "end_date": effective_end_date,
            "chunk_months": int(chunk_months),
            "request_timeout_seconds": float(request_timeout_seconds),
            "chunk_hard_timeout_seconds": float(chunk_hard_timeout_seconds),
            "max_new_chunks_per_run": int(max_new_chunks_per_run),
            "planned_chunk_count_per_symbol": len(chunks),
            "output_root": _relpath(output_abs, root),
            "chunk_root": _relpath(chunk_root, root),
            "report_path": _relpath(report_abs, root),
            "token_present": bool(token or os.environ.get("TIINGO_API_KEY") or local_env_token),
            "token_printed": False,
            "guardrails": _guardrails(api_key_used=False),
            "blockers": [],
        }
        _write_json(report_abs, payload)
        return payload

    api_token = token or os.environ.get("TIINGO_API_KEY", "") or local_env_token
    if not api_token:
        payload = _blocked_report(
            root=root,
            generated=generated,
            symbols=selected_symbols,
            start_date=start_date,
            end_date=effective_end_date,
            output_abs=output_abs,
            report_abs=report_abs,
            blockers=["tiingo_api_key_missing"],
        )
        _write_json(report_abs, payload)
        return payload

    client_fetcher = fetcher or _build_tiingo_iex_fetcher(api_token, timeout_seconds=request_timeout_seconds)
    kline_root.mkdir(parents=True, exist_ok=True)
    chunk_root.mkdir(parents=True, exist_ok=True)
    symbol_reports: dict[str, Any] = {}
    raw_data_blockers: list[str] = []
    research_blockers: list[str] = []
    runtime_blockers: list[str] = []
    fetched_symbols: list[str] = []
    skipped_existing_symbols: list[str] = []
    attempted_new_chunk_count = 0

    for symbol in selected_symbols:
        path = kline_root / f"{symbol}.parquet"
        path_exists_before = path.exists()
        if skip_existing and path.exists():
            frame = _normalize_existing_frame(pd.read_parquet(path), symbol)
            frame.to_parquet(path, index=False)
            quality = _symbol_quality(
                frame,
                symbol=symbol,
                root=root,
                path=path,
                generated_at=generated,
                max_staleness_days=max_staleness_days,
                extreme_return_threshold=extreme_return_threshold,
                requested_start_date=start_date,
                requested_end_date=effective_end_date,
                min_coverage_ratio=min_coverage_ratio,
            )
            quality["write_mode"] = "skipped_existing"
            symbol_reports[symbol] = quality
            skipped_existing_symbols.append(symbol)
            raw_data_blockers.extend(str(item) for item in quality.get("raw_data_blockers", []))
            research_blockers.extend(str(item) for item in quality.get("research_blockers", []))
            continue

        frames: list[pd.DataFrame] = []
        chunk_reports: list[dict[str, Any]] = []
        for chunk_index, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_path = chunk_root / symbol / f"{chunk_start}_{chunk_end}.parquet"
            if chunk_path.exists():
                frame = _normalize_existing_frame(pd.read_parquet(chunk_path), symbol)
                frames.append(frame)
                chunk_reports.append(
                    {
                        "start": chunk_start,
                        "end": chunk_end,
                        "status": "skipped_existing_chunk",
                        "rows": int(len(frame)),
                        "path": _relpath(chunk_path, root),
                    }
                )
                continue
            if max_new_chunks_per_run > 0 and attempted_new_chunk_count >= max_new_chunks_per_run:
                chunk_reports.append(
                    {
                        "start": chunk_start,
                        "end": chunk_end,
                        "status": "deferred_run_limit",
                        "rows": 0,
                        "path": _relpath(chunk_path, root),
                    }
                )
                continue
            if (fetched_symbols or frames or skipped_existing_symbols or chunk_index > 0) and request_sleep_seconds > 0:
                time.sleep(request_sleep_seconds)
            attempted_new_chunk_count += 1
            try:
                if fetcher is None and chunk_hard_timeout_seconds > 0:
                    chunk_result = _fetch_chunk_in_subprocess(
                        root=root,
                        symbol=symbol,
                        chunk_start=chunk_start,
                        chunk_end=chunk_end,
                        chunk_path=chunk_path,
                        api_token=api_token,
                        request_timeout_seconds=request_timeout_seconds,
                        chunk_hard_timeout_seconds=chunk_hard_timeout_seconds,
                    )
                    if chunk_result["status"] != "available":
                        raise RuntimeError(f"{chunk_result['error_type']}:{chunk_result['error']}")
                    frame = _normalize_existing_frame(pd.read_parquet(chunk_path), symbol)
                else:
                    rows = client_fetcher(symbol, chunk_start, chunk_end)
                    frame = normalize_tiingo_iex_rows(symbol, rows)
                    chunk_path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_parquet(chunk_path, index=False)
                frames.append(frame)
                chunk_reports.append(
                    {
                        "start": chunk_start,
                        "end": chunk_end,
                        "status": "available",
                        "rows": int(len(frame)),
                        "path": _relpath(chunk_path, root),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                error = str(exc)[:500]
                chunk_reports.append(
                    {
                        "start": chunk_start,
                        "end": chunk_end,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": error,
                    }
                )
                if _is_rate_limit_error(error):
                    runtime_blockers.append("tiingo_iex_rate_limited")
                    for remaining_start, remaining_end in chunks[chunk_index + 1 :]:
                        remaining_path = chunk_root / symbol / f"{remaining_start}_{remaining_end}.parquet"
                        if remaining_path.exists():
                            continue
                        chunk_reports.append(
                            {
                                "start": remaining_start,
                                "end": remaining_end,
                                "status": "deferred_rate_limited",
                                "rows": 0,
                                "path": _relpath(remaining_path, root),
                            }
                        )
                    break
        frame = _merge_frames(frames, symbol)
        if frame.empty:
            blocker = f"tiingo_iex_{symbol.lower()}_minute_empty_response"
            if preserve_existing_kline_on_partial and path_exists_before:
                retained = _normalize_existing_frame(pd.read_parquet(path), symbol)
                quality = _symbol_quality(
                    retained,
                    symbol=symbol,
                    root=root,
                    path=path,
                    generated_at=generated,
                    max_staleness_days=max_staleness_days,
                    extreme_return_threshold=extreme_return_threshold,
                    requested_start_date=start_date,
                    requested_end_date=effective_end_date,
                    min_coverage_ratio=min_coverage_ratio,
                )
                quality["write_mode"] = "empty_or_failed_chunks_existing_kline_retained"
                quality["main_kline_write_suppressed"] = True
                quality["main_kline_write_suppressed_reason"] = "empty_or_failed_chunk_backfill"
                quality["chunk_reports"] = chunk_reports
                symbol_reports[symbol] = quality
                raw_data_blockers.extend(str(item) for item in quality.get("raw_data_blockers", []))
                research_blockers.extend(str(item) for item in quality.get("research_blockers", []))
                continue
            symbol_reports[symbol] = {
                "status": "empty",
                "path": _relpath(path, root),
                "rows": 0,
                "chunk_reports": chunk_reports,
                "raw_data_blockers": [blocker],
                "research_blockers": [blocker],
            }
            raw_data_blockers.append(blocker)
            research_blockers.append(blocker)
            continue
        quality = _symbol_quality(
            frame,
            symbol=symbol,
            root=root,
            path=path,
            generated_at=generated,
            max_staleness_days=max_staleness_days,
            extreme_return_threshold=extreme_return_threshold,
            requested_start_date=start_date,
            requested_end_date=effective_end_date,
            min_coverage_ratio=min_coverage_ratio,
        )
        should_preserve_existing = (
            preserve_existing_kline_on_partial
            and path_exists_before
            and quality["raw_data_status"] != "available"
        )
        if should_preserve_existing:
            quality["write_mode"] = "partial_chunks_not_promoted_existing_kline_retained"
            quality["main_kline_write_suppressed"] = True
            quality["main_kline_write_suppressed_reason"] = "partial_backfill_or_quality_concern"
        else:
            frame.to_parquet(path, index=False)
            quality["write_mode"] = "fetched"
            quality["main_kline_write_suppressed"] = False
        quality["chunk_reports"] = chunk_reports
        symbol_reports[symbol] = quality
        fetched_symbols.append(symbol)
        raw_data_blockers.extend(str(item) for item in quality.get("raw_data_blockers", []))
        research_blockers.extend(str(item) for item in quality.get("research_blockers", []))

    available_symbols = [
        symbol for symbol, row in symbol_reports.items() if row.get("raw_data_status") == "available"
    ]
    missing_symbols = sorted(set(selected_symbols) - set(available_symbols))
    if missing_symbols:
        raw_data_blockers.append("tiingo_iex_minute_required_symbols_missing")
        research_blockers.append("tiingo_iex_minute_required_symbols_missing")
    raw_data_blockers.extend(runtime_blockers)
    research_blockers.extend(runtime_blockers)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "pass" if not raw_data_blockers else "partial",
        "research_ready_status": "pass" if not research_blockers else "blocked",
        "network_called": bool(fetched_symbols),
        "writes_performed": True,
        "provider": "tiingo_iex",
        "asset": "us_equity",
        "source_type": "market_data_intraday_1m_iex_only_raw",
        "symbols": list(selected_symbols),
        "symbol_count": len(selected_symbols),
        "available_symbols": available_symbols,
        "missing_symbols": missing_symbols,
        "fetched_symbols": fetched_symbols,
        "skipped_existing_symbols": skipped_existing_symbols,
        "skip_existing": skip_existing,
        "interval_requested": "1min",
        "requested_start_date": start_date,
        "requested_end_date": effective_end_date,
        "chunk_months": int(chunk_months),
        "request_timeout_seconds": float(request_timeout_seconds),
        "chunk_hard_timeout_seconds": float(chunk_hard_timeout_seconds),
        "max_new_chunks_per_run": int(max_new_chunks_per_run),
        "attempted_new_chunk_count": int(attempted_new_chunk_count),
        "min_coverage_ratio": float(min_coverage_ratio),
        "preserve_existing_kline_on_partial": bool(preserve_existing_kline_on_partial),
        "chunk_count_per_symbol": len(chunks),
        "output_root": _relpath(output_abs, root),
        "kline_root": _relpath(kline_root, root),
        "chunk_root": _relpath(chunk_root, root),
        "report_path": _relpath(report_abs, root),
        "token_present": True,
        "token_printed": False,
        "symbol_reports": symbol_reports,
        "summary": _summary(symbol_reports),
        "data_limitations": {
            "exchange_scope": "IEX-only historical intraday bars, not consolidated CTA/UTP tape.",
            "provider_history_note": "Tiingo product documentation says IEX intraday history starts from August 2017.",
            "requested_10y_backfill_may_start_later_than_requested": True,
            "minute_bars_are_raw": True,
        },
        "adjustment_controls": {
            "raw_intraday_retained": True,
            "front_adjusted_output_written": False,
            "back_adjusted_output_written": False,
            "back_adjusted_for_signal_use_allowed": False,
            "no_lookahead_rule": "Do not apply full-history future adjustment factors to historical minute signals.",
            "allowed_adjustment_rule": "Only ex-date-known split/dividend factors with available_time <= decision_time may be applied in a separate PIT factor replay table.",
        },
        "guardrails": _guardrails(api_key_used=True),
        "raw_data_blockers": _dedupe(raw_data_blockers),
        "research_blockers": _dedupe(research_blockers),
        "blockers": _dedupe(raw_data_blockers + research_blockers),
    }
    _write_json(report_abs, payload)
    return payload


def normalize_tiingo_iex_rows(symbol: str, rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get("date")
        if not ts:
            continue
        open_value = _number(row.get("open"))
        high_value = _number(row.get("high"))
        low_value = _number(row.get("low"))
        close_value = _number(row.get("close"))
        volume_value = _number(row.get("volume"))
        if open_value is None or high_value is None or low_value is None or close_value is None:
            continue
        if min(open_value, high_value, low_value, close_value) <= 0.0:
            continue
        start = pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).tz_localize("UTC")
        end = start + pd.Timedelta(minutes=1)
        repaired_high = max(open_value, high_value, low_value, close_value)
        repaired_low = min(open_value, high_value, low_value, close_value)
        flags = []
        if repaired_high != high_value or repaired_low != low_value:
            flags.append("ohlc_bounds_repaired_from_raw")
        records.append(
            {
                "datetime": start,
                "bar_start_utc": start,
                "bar_end_utc": end,
                "available_time": end,
                "symbol": symbol.upper(),
                "Open": float(open_value),
                "High": float(repaired_high),
                "Low": float(repaired_low),
                "Close": float(close_value),
                "Volume": 0.0 if volume_value is None else float(volume_value),
                "RawOpen": float(open_value),
                "RawHigh": float(high_value),
                "RawLow": float(low_value),
                "RawClose": float(close_value),
                "source": "tiingo_iex_intraday_1m",
                "interval": "1m",
                "data_version": "tiingo_iex_intraday_1m_raw_v1",
                "adjustment_policy": "raw_intraday_unadjusted_iex_only",
                "quality_flags": ",".join(flags),
            }
        )
    if not records:
        return _empty_frame()
    frame = pd.DataFrame(records)
    for column in ("datetime", "bar_start_utc", "bar_end_utc", "available_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)


def _build_tiingo_iex_fetcher(token: str, *, timeout_seconds: float = 30.0) -> Fetcher:
    timeout = max(1.0, float(timeout_seconds))

    def fetch(symbol: str, start_date: str, end_date: str) -> list[Mapping[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "startDate": start_date,
                "endDate": end_date,
                "resampleFreq": "1min",
                "columns": "open,high,low,close,volume",
                "token": token,
            }
        )
        url = f"{TIINGO_IEX_URL.format(symbol=urllib.parse.quote(symbol.upper()))}?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError(f"tiingo_iex_response_not_list:{str(payload)[:200]}")
        return payload

    return fetch


def _fetch_chunk_in_subprocess(
    *,
    root: Path,
    symbol: str,
    chunk_start: str,
    chunk_end: str,
    chunk_path: Path,
    api_token: str,
    request_timeout_seconds: float,
    chunk_hard_timeout_seconds: float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--repo-root",
        str(root),
        "--symbols",
        symbol,
        "--single-chunk-symbol",
        symbol,
        "--single-chunk-start",
        chunk_start,
        "--single-chunk-end",
        chunk_end,
        "--single-chunk-path",
        str(chunk_path),
        "--request-timeout-seconds",
        str(float(request_timeout_seconds)),
    ]
    env = os.environ.copy()
    env["TIINGO_API_KEY"] = api_token
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(chunk_hard_timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "error_type": "ChunkHardTimeoutExpired",
            "error": f"chunk exceeded hard timeout {chunk_hard_timeout_seconds}s",
        }
    if completed.returncode != 0:
        return {
            "status": "failed",
            "error_type": "ChunkSubprocessFailed",
            "error": (completed.stderr or completed.stdout or f"returncode={completed.returncode}")[:500],
        }
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return {
            "status": "failed",
            "error_type": "ChunkSubprocessInvalidJson",
            "error": completed.stdout[:500],
        }
    if not isinstance(payload, dict):
        return {
            "status": "failed",
            "error_type": "ChunkSubprocessInvalidPayload",
            "error": str(payload)[:500],
        }
    return payload


def _run_single_chunk_child(
    *,
    repo_root: Path,
    symbol: str,
    chunk_start: str,
    chunk_end: str,
    chunk_path: Path,
    request_timeout_seconds: float,
) -> dict[str, Any]:
    root = repo_root.resolve()
    api_token = os.environ.get("TIINGO_API_KEY", "") or _load_local_env_value(root, "TIINGO_API_KEY")
    if not api_token:
        return {
            "status": "failed",
            "error_type": "TiingoApiKeyMissing",
            "error": "tiingo_api_key_missing",
        }
    fetcher = _build_tiingo_iex_fetcher(api_token, timeout_seconds=request_timeout_seconds)
    try:
        rows = fetcher(symbol, chunk_start, chunk_end)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error_type": _network_error_type(exc),
            "error": str(exc)[:500],
        }
    frame = normalize_tiingo_iex_rows(symbol, rows)
    output_path = _resolve(root, chunk_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_path, index=False)
    return {
        "status": "available",
        "rows": int(len(frame)),
        "path": _relpath(output_path, root),
        "token_printed": False,
    }


def _network_error_type(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code is not None:
        return f"HTTPError_{code}"
    return type(exc).__name__


def _is_rate_limit_error(error: str) -> bool:
    text = str(error).lower()
    return "429" in text or "too many requests" in text or "rate_limited" in text


def _symbol_quality(
    frame: pd.DataFrame,
    *,
    symbol: str,
    root: Path,
    path: Path,
    generated_at: str,
    max_staleness_days: int,
    extreme_return_threshold: float,
    requested_start_date: str,
    requested_end_date: str,
    min_coverage_ratio: float,
) -> dict[str, Any]:
    raw_data_blockers: list[str] = []
    research_blockers: list[str] = []
    ohlc = frame[["Open", "High", "Low", "Close"]].astype(float)
    non_positive = int((ohlc <= 0).any(axis=1).sum())
    invalid = int(
        (
            (ohlc["High"] < ohlc[["Open", "Close", "Low"]].max(axis=1))
            | (ohlc["Low"] > ohlc[["Open", "Close", "High"]].min(axis=1))
        ).sum()
    )
    duplicates = int(frame["datetime"].duplicated().sum())
    minute_returns = _contiguous_minute_returns(frame)
    max_abs_return = float(minute_returns.abs().max()) if not minute_returns.empty else 0.0
    repaired_rows = int(frame.get("quality_flags", pd.Series(dtype=str)).astype(str).str.contains("ohlc_bounds_repaired").sum())
    latest = pd.Timestamp(frame["datetime"].max()).tz_convert("UTC")
    generated_ts = pd.Timestamp(generated_at)
    if generated_ts.tzinfo is None:
        generated_ts = generated_ts.tz_localize("UTC")
    else:
        generated_ts = generated_ts.tz_convert("UTC")
    staleness_days = int((generated_ts.normalize() - latest.normalize()).days)
    if non_positive:
        raw_data_blockers.append(f"tiingo_iex_{symbol.lower()}_minute_non_positive_ohlc")
    if invalid:
        raw_data_blockers.append(f"tiingo_iex_{symbol.lower()}_minute_invalid_ohlc")
    if duplicates:
        raw_data_blockers.append(f"tiingo_iex_{symbol.lower()}_minute_duplicate_timestamps")
    if max_abs_return > extreme_return_threshold:
        raw_data_blockers.append(f"tiingo_iex_{symbol.lower()}_minute_extreme_return")
    if staleness_days > max_staleness_days:
        raw_data_blockers.append(f"tiingo_iex_{symbol.lower()}_minute_stale")
    coverage = _coverage_check(frame, requested_start_date, requested_end_date)
    if min_coverage_ratio > 0.0 and float(coverage["coverage_ratio"]) < float(min_coverage_ratio):
        raw_data_blockers.append(f"tiingo_iex_{symbol.lower()}_minute_backfill_incomplete")
    adjustment = _adjustment_ratio_check(root, symbol, frame)
    if adjustment.get("status") in {
        "ratio_not_constant_requires_pit_factor_replay",
        "eod_adjustment_ratio_unavailable",
    }:
        research_blockers.append(f"{symbol.lower()}_minute_pit_adjustment_replay_required")
    return {
        "raw_data_status": "available" if not raw_data_blockers else "quality_concerns",
        "research_use_status": "pass" if not research_blockers and not raw_data_blockers else "blocked",
        "path": _relpath(path, root),
        "rows": int(len(frame)),
        "start": _ts_str(frame["datetime"].min()),
        "end": _ts_str(frame["datetime"].max()),
        "staleness_days": staleness_days,
        "max_abs_1m_return": _round(max_abs_return),
        "ohlc_bounds_repaired_rows": repaired_rows,
        "coverage_check": coverage,
        "latest_close": _round(float(frame["Close"].iloc[-1])),
        "duplicate_timestamps": duplicates,
        "invalid_ohlc_rows": invalid,
        "non_positive_ohlc_rows": non_positive,
        "adjustment_ratio_check": adjustment,
        "raw_data_blockers": raw_data_blockers,
        "research_blockers": research_blockers,
    }


def _adjustment_ratio_check(root: Path, symbol: str, frame: pd.DataFrame) -> dict[str, Any]:
    paths = [
        root / "data/external/us_equity_eod/tiingo/kline" / f"{symbol}.parquet",
        root / "data/external/us_equity_eod/yahoo_chart_adjusted/kline" / f"{symbol}.parquet",
    ]
    start_date = pd.Timestamp(frame["datetime"].min()).date().isoformat()
    end_date = pd.Timestamp(frame["datetime"].max()).date().isoformat()
    for path in paths:
        if not path.exists():
            continue
        eod = pd.read_parquet(path).copy()
        if "datetime" not in eod.columns:
            continue
        eod["datetime"] = pd.to_datetime(eod["datetime"], utc=True)
        mask = (eod["datetime"].dt.date.astype(str) >= start_date) & (eod["datetime"].dt.date.astype(str) <= end_date)
        window = eod.loc[mask].copy()
        if window.empty:
            continue
        if "AdjustmentRatio" in window.columns:
            ratio = pd.to_numeric(window["AdjustmentRatio"], errors="coerce").dropna()
        elif {"AdjClose", "Close"} <= set(window.columns):
            ratio = pd.to_numeric(window["AdjClose"], errors="coerce") / pd.to_numeric(window["Close"], errors="coerce")
            ratio = ratio.dropna()
        else:
            continue
        unique = sorted({round(float(item), 10) for item in ratio if pd.notna(item)})
        if not unique:
            continue
        return {
            "status": "ratio_constant_in_window" if len(unique) == 1 else "ratio_not_constant_requires_pit_factor_replay",
            "source_path": _relpath(path, root),
            "window_start": start_date,
            "window_end": end_date,
            "unique_ratio_count": len(unique),
            "min_ratio": _round(min(unique), 10),
            "max_ratio": _round(max(unique), 10),
            "front_adjusted_written": False,
            "back_adjusted_written": False,
            "no_lookahead_note": "Raw minute table is retained; adjusted variants require PIT factor replay.",
        }
    return {
        "status": "eod_adjustment_ratio_unavailable",
        "window_start": start_date,
        "window_end": end_date,
        "front_adjusted_written": False,
        "back_adjusted_written": False,
        "no_lookahead_note": "Raw minute table cannot be used for split-crossing signals until adjustment review exists.",
    }


def _normalize_existing_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return _empty_frame()
    working = frame.copy()
    required = ["datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in working.columns]
    if missing:
        raise ValueError(f"existing Tiingo IEX minute frame for {symbol} missing columns: {missing}")
    if "symbol" not in working.columns:
        working["symbol"] = symbol.upper()
    if "bar_start_utc" not in working.columns:
        working["bar_start_utc"] = working["datetime"]
    if "bar_end_utc" not in working.columns:
        working["bar_end_utc"] = pd.to_datetime(working["datetime"], utc=True) + pd.Timedelta(minutes=1)
    if "available_time" not in working.columns:
        working["available_time"] = working["bar_end_utc"]
    for column in ("datetime", "bar_start_utc", "bar_end_utc", "available_time"):
        working[column] = pd.to_datetime(working[column], utc=True)
    for column in ("Open", "High", "Low", "Close", "Volume"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    for raw_column, column in (
        ("RawOpen", "Open"),
        ("RawHigh", "High"),
        ("RawLow", "Low"),
        ("RawClose", "Close"),
    ):
        if raw_column not in working.columns:
            working[raw_column] = working[column]
    if "quality_flags" not in working.columns:
        working["quality_flags"] = ""
    repaired_high = working[["Open", "High", "Low", "Close"]].max(axis=1)
    repaired_low = working[["Open", "High", "Low", "Close"]].min(axis=1)
    repaired_mask = (repaired_high != working["High"]) | (repaired_low != working["Low"])
    working.loc[repaired_mask, "quality_flags"] = working.loc[repaired_mask, "quality_flags"].astype(str).where(
        working.loc[repaired_mask, "quality_flags"].astype(str) != "",
        "ohlc_bounds_repaired_from_existing",
    )
    working["High"] = repaired_high
    working["Low"] = repaired_low
    return working.dropna(subset=["datetime", "Open", "High", "Low", "Close"]).sort_values("datetime").reset_index(drop=True)


def _contiguous_minute_returns(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    working = frame.sort_values("datetime").copy()
    dt = pd.to_datetime(working["datetime"], utc=True)
    same_session = dt.dt.tz_convert("America/New_York").dt.date == dt.shift(1).dt.tz_convert("America/New_York").dt.date
    contiguous = dt.diff() <= pd.Timedelta(minutes=2)
    returns = working["Close"].astype(float).pct_change(fill_method=None)
    return returns.where(same_session & contiguous).dropna()


def _merge_frames(frames: Iterable[pd.DataFrame], symbol: str) -> pd.DataFrame:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return _empty_frame()
    merged = pd.concat(non_empty, ignore_index=True)
    merged["symbol"] = symbol.upper()
    return merged.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)


def _date_chunks(start_date: str, end_date: str, chunk_months: int) -> list[tuple[str, str]]:
    start = pd.Timestamp(date.fromisoformat(start_date))
    end = pd.Timestamp(date.fromisoformat(end_date))
    if start > end:
        return []
    chunks: list[tuple[str, str]] = []
    current = start
    while current <= end:
        chunk_end = min(current + pd.DateOffset(months=chunk_months) - pd.Timedelta(days=1), end)
        chunks.append((current.date().isoformat(), chunk_end.date().isoformat()))
        current = chunk_end + pd.Timedelta(days=1)
    return chunks


def _summary(symbol_reports: Mapping[str, Any]) -> dict[str, Any]:
    available = [row for row in symbol_reports.values() if row.get("raw_data_status") == "available"]
    rows = [int(row.get("rows", 0) or 0) for row in symbol_reports.values()]
    starts = [str(row.get("start")) for row in symbol_reports.values() if row.get("start")]
    ends = [str(row.get("end")) for row in symbol_reports.values() if row.get("end")]
    return {
        "available_symbol_count": len(available),
        "min_rows": min(rows) if rows else 0,
        "max_rows": max(rows) if rows else 0,
        "common_start_timestamp": max(starts) if starts else None,
        "common_end_timestamp": min(ends) if ends else None,
        "earliest_any_timestamp": min(starts) if starts else None,
        "latest_any_timestamp": max(ends) if ends else None,
    }


def _coverage_check(frame: pd.DataFrame, requested_start_date: str, requested_end_date: str) -> dict[str, Any]:
    sessions = pd.bdate_range(start=requested_start_date, end=requested_end_date)
    conservative_expected_rows = int(len(sessions) * 250)
    actual_rows = int(len(frame))
    coverage_ratio = actual_rows / conservative_expected_rows if conservative_expected_rows else 0.0
    return {
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
        "conservative_expected_min_rows": conservative_expected_rows,
        "actual_rows": actual_rows,
        "coverage_ratio": _round(coverage_ratio),
        "note": "Conservative lower bound assumes 250 observed IEX minute bars per US business day.",
    }


def _blocked_report(
    *,
    root: Path,
    generated: str,
    symbols: Iterable[str],
    start_date: str,
    end_date: str,
    output_abs: Path,
    report_abs: Path,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "blocked",
        "research_ready_status": "blocked",
        "network_called": False,
        "writes_performed": False,
        "provider": "tiingo_iex",
        "asset": "us_equity",
        "source_type": "market_data_intraday_1m_iex_only_raw",
        "symbols": list(symbols),
        "symbol_count": len(list(symbols)),
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "output_root": _relpath(output_abs, root),
        "report_path": _relpath(report_abs, root),
        "token_present": False,
        "token_printed": False,
        "guardrails": _guardrails(api_key_used=False),
        "raw_data_blockers": blockers,
        "research_blockers": blockers,
        "blockers": blockers,
    }


def _guardrails(*, api_key_used: bool) -> dict[str, Any]:
    return {
        "api_key_used_for_market_data": bool(api_key_used),
        "token_written_to_artifacts": False,
        "private_endpoint_used": False,
        "broker_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "real_order_submitted": False,
        "promotion_clean_granted_by_this_report": False,
    }


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "datetime",
            "bar_start_utc",
            "bar_end_utc",
            "available_time",
            "symbol",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "RawOpen",
            "RawHigh",
            "RawLow",
            "RawClose",
            "source",
            "interval",
            "data_version",
            "adjustment_policy",
            "quality_flags",
        ]
    )


def _number(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def _load_local_env_value(root: Path, key: str) -> str:
    path = root / ".env.local"
    if not path.exists():
        return ""
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
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


def _round(value: float | int | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return round(float(value), digits)


def _ts_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Tiingo IEX 1-minute bars for US equity research.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--request-sleep-seconds", type=float, default=0.25)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--chunk-hard-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--max-new-chunks-per-run", type=int, default=0)
    parser.add_argument("--chunk-months", type=int, default=DEFAULT_CHUNK_MONTHS)
    parser.add_argument("--max-staleness-days", type=int, default=DEFAULT_MAX_STALENESS_DAYS)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.0)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--allow-partial-kline-overwrite", action="store_true")
    parser.add_argument("--single-chunk-symbol", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-chunk-start", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-chunk-end", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-chunk-path", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single_chunk_symbol:
        payload = _run_single_chunk_child(
            repo_root=Path(args.repo_root),
            symbol=args.single_chunk_symbol,
            chunk_start=args.single_chunk_start,
            chunk_end=args.single_chunk_end,
            chunk_path=Path(args.single_chunk_path),
            request_timeout_seconds=float(args.request_timeout_seconds),
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        if payload["status"] != "available":
            raise SystemExit(2)
        return
    payload = import_tiingo_iex_minute_bars(
        repo_root=Path(args.repo_root),
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
        start_date=args.start_date,
        end_date=args.end_date or None,
        output_root=Path(args.output_root),
        report_path=Path(args.report),
        execute_network=bool(args.execute_network),
        request_sleep_seconds=float(args.request_sleep_seconds),
        request_timeout_seconds=float(args.request_timeout_seconds),
        chunk_hard_timeout_seconds=float(args.chunk_hard_timeout_seconds),
        max_new_chunks_per_run=int(args.max_new_chunks_per_run),
        chunk_months=int(args.chunk_months),
        skip_existing=not bool(args.force_refresh),
        preserve_existing_kline_on_partial=not bool(args.allow_partial_kline_overwrite),
        max_staleness_days=int(args.max_staleness_days),
        min_coverage_ratio=float(args.min_coverage_ratio),
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "research_ready_status": payload.get("research_ready_status"),
                "report": payload["report_path"],
                "network_called": payload["network_called"],
                "raw_data_blockers": payload.get("raw_data_blockers", []),
                "research_blockers": payload.get("research_blockers", []),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
