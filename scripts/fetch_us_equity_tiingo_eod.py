#!/usr/bin/env python3
"""Fetch Tiingo EOD bars into the local US equity research lake.

This collector is market-data only. It reads ``TIINGO_API_KEY`` from the
environment, never writes the token to artifacts, and refuses to produce any
paper/live/order side effects.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.research.us_etf_macro_momentum_rotation import UsEtfMacroMomentumRotationConfig  # noqa: E402


SCHEMA_VERSION = "us_equity_tiingo_eod_import_report_v1"
DEFAULT_OUTPUT_ROOT = Path("data/external/us_equity_eod/tiingo")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_START_DATE = "2000-01-01"
DEFAULT_EXTREME_RETURN_THRESHOLD = 0.35
DEFAULT_MAX_STALENESS_DAYS = 7
TIINGO_EOD_URL = "https://api.tiingo.com/tiingo/daily/{symbol}/prices"

Fetcher = Callable[[str, str, str], list[Mapping[str, Any]]]


def import_tiingo_eod(
    *,
    repo_root: Path,
    symbols: Iterable[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    execute_network: bool = False,
    request_sleep_seconds: float = 0.15,
    skip_existing: bool = True,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
    extreme_return_threshold: float = DEFAULT_EXTREME_RETURN_THRESHOLD,
    generated_at: str | None = None,
    token: str | None = None,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or _utc_now()
    selected_symbols = tuple(_unique(symbols or UsEtfMacroMomentumRotationConfig().required_symbols()))
    effective_end_date = end_date or generated[:10]
    output_abs = _resolve(root, output_root)
    report_abs = _resolve(root, report_path)
    kline_root = output_abs / "kline"
    local_env_token = _load_local_env_value(root, "TIINGO_API_KEY")

    if not execute_network:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "dry_run",
            "network_called": False,
            "writes_performed": False,
            "provider": "tiingo",
            "asset": "us_equity",
            "source_type": "market_data_eod",
            "symbols": list(selected_symbols),
            "symbol_count": len(selected_symbols),
            "start_date": start_date,
            "end_date": effective_end_date,
            "output_root": _relpath(output_abs, root),
            "report_path": _relpath(report_abs, root),
            "planned_endpoint": "https://api.tiingo.com/tiingo/daily/<SYMBOL>/prices",
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

    client_fetcher = fetcher or _build_tiingo_fetcher(api_token)
    symbol_reports: dict[str, Any] = {}
    blockers: list[str] = []
    fetched_symbols: list[str] = []
    skipped_existing_symbols: list[str] = []
    kline_root.mkdir(parents=True, exist_ok=True)

    for index, symbol in enumerate(selected_symbols):
        path = kline_root / f"{symbol}.parquet"
        if skip_existing and path.exists():
            try:
                frame = pd.read_parquet(path)
                quality = _symbol_quality(
                    _normalize_lake_frame(frame, symbol),
                    symbol=symbol,
                    generated_at=generated,
                    max_staleness_days=max_staleness_days,
                    extreme_return_threshold=extreme_return_threshold,
                )
                quality["path"] = _relpath(path, root)
                quality["write_mode"] = "skipped_existing"
                symbol_reports[symbol] = quality
                skipped_existing_symbols.append(symbol)
                blockers.extend(str(item) for item in quality.get("blockers", []))
                continue
            except Exception as exc:  # noqa: BLE001 - stale/corrupt local file should trigger a refresh attempt.
                symbol_reports[symbol] = {
                    "status": "existing_file_unreadable_refresh_attempted",
                    "path": _relpath(path, root),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                    "blockers": [],
                }
        if (fetched_symbols or skipped_existing_symbols) and request_sleep_seconds > 0:
            time.sleep(request_sleep_seconds)
        try:
            rows = client_fetcher(symbol, start_date, effective_end_date)
            frame = normalize_tiingo_rows(symbol, rows)
            if frame.empty:
                symbol_reports[symbol] = {
                    "status": "empty",
                    "rows": 0,
                    "blockers": [f"tiingo_{symbol.lower()}_empty_response"],
                }
                blockers.append(f"tiingo_{symbol.lower()}_empty_response")
                continue
            frame.to_parquet(path, index=False)
            quality = _symbol_quality(
                frame,
                symbol=symbol,
                generated_at=generated,
                max_staleness_days=max_staleness_days,
                extreme_return_threshold=extreme_return_threshold,
            )
            quality["path"] = _relpath(path, root)
            quality["write_mode"] = "fetched"
            symbol_reports[symbol] = quality
            fetched_symbols.append(symbol)
            blockers.extend(str(item) for item in quality.get("blockers", []))
        except Exception as exc:  # noqa: BLE001 - artifact should capture per-symbol failure.
            blocker = f"tiingo_{symbol.lower()}_fetch_failed"
            symbol_reports[symbol] = {
                "status": "failed",
                "rows": 0,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "blockers": [blocker],
            }
            blockers.append(blocker)

    available_symbols = [
        symbol
        for symbol, row in symbol_reports.items()
        if row.get("status") == "available"
    ]
    missing_symbols = sorted(set(selected_symbols) - set(available_symbols))
    if missing_symbols:
        blockers.append("tiingo_required_symbols_missing")

    status = "pass" if not blockers else "partial"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "network_called": bool(fetched_symbols),
        "writes_performed": True,
        "provider": "tiingo",
        "asset": "us_equity",
        "source_type": "market_data_eod",
        "symbols": list(selected_symbols),
        "symbol_count": len(selected_symbols),
        "available_symbols": available_symbols,
        "missing_symbols": missing_symbols,
        "fetched_symbols": fetched_symbols,
        "skipped_existing_symbols": skipped_existing_symbols,
        "skip_existing": skip_existing,
        "start_date": start_date,
        "end_date": effective_end_date,
        "output_root": _relpath(output_abs, root),
        "kline_root": _relpath(kline_root, root),
        "report_path": _relpath(report_abs, root),
        "token_present": True,
        "token_printed": False,
        "symbol_reports": symbol_reports,
        "summary": _summary(symbol_reports),
        "guardrails": _guardrails(api_key_used=True),
        "blockers": _dedupe(blockers),
    }
    _write_json(report_abs, payload)
    return payload


def normalize_tiingo_rows(symbol: str, rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in rows:
        date = row.get("date")
        if not date:
            continue
        records.append(
            {
                "datetime": pd.Timestamp(date).tz_convert("UTC") if pd.Timestamp(date).tzinfo else pd.Timestamp(date, tz="UTC"),
                "symbol": symbol.upper(),
                "Open": _number(row.get("adjOpen", row.get("open"))),
                "High": _number(row.get("adjHigh", row.get("high"))),
                "Low": _number(row.get("adjLow", row.get("low"))),
                "Close": _number(row.get("adjClose", row.get("close"))),
                "Volume": _number(row.get("adjVolume", row.get("volume"))),
                "RawOpen": _number(row.get("open")),
                "RawHigh": _number(row.get("high")),
                "RawLow": _number(row.get("low")),
                "RawClose": _number(row.get("close")),
                "RawVolume": _number(row.get("volume")),
                "DivCash": _number(row.get("divCash")),
                "SplitFactor": _number(row.get("splitFactor")),
                "source": "tiingo_eod",
            }
        )
    if not records:
        return pd.DataFrame(
            columns=[
                "datetime",
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
                "RawVolume",
                "DivCash",
                "SplitFactor",
                "source",
            ]
        )
    frame = pd.DataFrame(records)
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame = frame.sort_values("datetime").drop_duplicates("datetime", keep="last")
    return frame.reset_index(drop=True)


def _normalize_lake_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return normalize_tiingo_rows(symbol, [])
    working = frame.copy()
    rename_map = {
        "timestamp_utc": "datetime",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    working = working.rename(columns={k: v for k, v in rename_map.items() if k in working.columns})
    required = ["datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in working.columns]
    if missing:
        raise ValueError(f"existing Tiingo lake frame for {symbol} missing columns: {missing}")
    if "symbol" not in working.columns:
        working["symbol"] = symbol.upper()
    for column in ("RawOpen", "RawHigh", "RawLow", "RawClose", "RawVolume", "DivCash", "SplitFactor", "source"):
        if column not in working.columns:
            working[column] = "tiingo_eod" if column == "source" else float("nan")
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    return working[
        [
            "datetime",
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
            "RawVolume",
            "DivCash",
            "SplitFactor",
            "source",
        ]
    ].sort_values("datetime")


def _build_tiingo_fetcher(token: str) -> Fetcher:
    def fetch(symbol: str, start_date: str, end_date: str) -> list[Mapping[str, Any]]:
        params = urllib.parse.urlencode({"startDate": start_date, "endDate": end_date})
        url = f"{TIINGO_EOD_URL.format(symbol=urllib.parse.quote(symbol))}?{params}"
        request = urllib.request.Request(url, headers={"Authorization": f"Token {token}"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310 - fixed public API host.
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")[:500]
            raise RuntimeError(f"tiingo_http_{exc.code}: {body}") from exc
        if not isinstance(payload, list):
            raise RuntimeError("tiingo_response_not_list")
        return [dict(item) for item in payload if isinstance(item, Mapping)]

    return fetch


def _symbol_quality(
    frame: pd.DataFrame,
    *,
    symbol: str,
    generated_at: str,
    max_staleness_days: int,
    extreme_return_threshold: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    if frame.empty:
        return {"status": "empty", "rows": 0, "blockers": [f"tiingo_{symbol.lower()}_empty_response"]}
    ohlc = frame[["Open", "High", "Low", "Close"]].astype(float)
    non_positive = int((ohlc <= 0).any(axis=1).sum())
    invalid = int(((ohlc["High"] < ohlc[["Open", "Close", "Low"]].max(axis=1)) | (ohlc["Low"] > ohlc[["Open", "Close", "High"]].min(axis=1))).sum())
    zero_volume = int((frame["Volume"].fillna(0).astype(float) <= 0).sum())
    returns = frame["Close"].astype(float).pct_change(fill_method=None).abs()
    extreme = int((returns > extreme_return_threshold).sum())
    duplicates = int(frame["datetime"].duplicated().sum())
    latest = pd.Timestamp(frame["datetime"].max()).tz_convert("UTC")
    generated_ts = pd.Timestamp(generated_at)
    if generated_ts.tzinfo is None:
        generated_ts = generated_ts.tz_localize("UTC")
    staleness_days = int((generated_ts.normalize() - latest.normalize()).days)

    if non_positive:
        blockers.append(f"tiingo_{symbol.lower()}_non_positive_ohlc")
    if invalid:
        blockers.append(f"tiingo_{symbol.lower()}_invalid_ohlc")
    if duplicates:
        blockers.append(f"tiingo_{symbol.lower()}_duplicate_dates")
    if extreme:
        blockers.append(f"tiingo_{symbol.lower()}_extreme_daily_return")
    if staleness_days > max_staleness_days:
        blockers.append(f"tiingo_{symbol.lower()}_stale")

    return {
        "status": "available" if not blockers else "quality_concerns",
        "rows": int(len(frame)),
        "start": str(pd.Timestamp(frame["datetime"].min()).date()),
        "end": str(latest.date()),
        "staleness_days": staleness_days,
        "duplicate_dates": duplicates,
        "non_positive_ohlc_rows": non_positive,
        "invalid_ohlc_rows": invalid,
        "zero_or_negative_volume_rows": zero_volume,
        "extreme_daily_return_rows": extreme,
        "latest_close": float(frame["Close"].iloc[-1]),
        "blockers": blockers,
    }


def _summary(symbol_reports: Mapping[str, Any]) -> dict[str, Any]:
    available = [row for row in symbol_reports.values() if row.get("status") == "available"]
    rows = [int(row.get("rows", 0) or 0) for row in symbol_reports.values()]
    latest_dates = [str(row.get("end")) for row in symbol_reports.values() if row.get("end")]
    return {
        "available_symbol_count": len(available),
        "min_rows": min(rows) if rows else 0,
        "max_rows": max(rows) if rows else 0,
        "latest_common_date": min(latest_dates) if latest_dates else None,
        "latest_any_date": max(latest_dates) if latest_dates else None,
    }


def _blocked_report(
    *,
    generated: str,
    symbols: tuple[str, ...],
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
        "network_called": False,
        "writes_performed": False,
        "provider": "tiingo",
        "asset": "us_equity",
        "source_type": "market_data_eod",
        "symbols": list(symbols),
        "symbol_count": len(symbols),
        "start_date": start_date,
        "end_date": end_date,
        "output_root": str(output_abs),
        "report_path": str(report_abs),
        "token_present": False,
        "token_printed": False,
        "guardrails": _guardrails(api_key_used=False),
        "blockers": blockers,
    }


def _guardrails(*, api_key_used: bool) -> dict[str, Any]:
    return {
        "api_key_used_for_market_data": api_key_used,
        "private_endpoint_used": False,
        "broker_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "real_order_submitted": False,
        "token_written_to_artifacts": False,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).upper().strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _number(value: object) -> float:
    try:
        if value is None or value == "":
            return float("nan")
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item)
        if value and value not in result:
            result.append(value)
    return result


def _load_local_env_value(root: Path, key: str) -> str:
    path = root / ".env.local"
    if not path.exists():
        return ""
    prefix = f"{key}="
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lstrip("\ufeff")
            if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
                continue
            return stripped[len(prefix) :].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Tiingo EOD bars for the US equity research system.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols. Defaults to the current ETF rotation required universe as the first US-equity consumer.",
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--request-sleep-seconds", type=float, default=0.15)
    parser.add_argument("--max-staleness-days", type=int, default=DEFAULT_MAX_STALENESS_DAYS)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--force-refresh", action="store_true", help="Refresh existing parquet files instead of reusing them.")
    args = parser.parse_args()

    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()] if args.symbols else None
    payload = import_tiingo_eod(
        repo_root=Path(args.repo_root),
        symbols=symbols,
        start_date=args.start_date,
        end_date=args.end_date or None,
        output_root=Path(args.output_root),
        report_path=Path(args.report),
        execute_network=bool(args.execute_network),
        request_sleep_seconds=float(args.request_sleep_seconds),
        skip_existing=not bool(args.force_refresh),
        max_staleness_days=int(args.max_staleness_days),
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "report": payload["report_path"],
                "network_called": payload["network_called"],
                "token_printed": False,
                "blockers": payload.get("blockers", []),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
