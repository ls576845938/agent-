#!/usr/bin/env python3
"""Fetch adjusted Yahoo daily bars for US equity research fallback.

This collector is market-data only. It does not require an API key and must not
be treated as a promotion-clean replacement for licensed PIT data or Tiingo.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd


SCHEMA_VERSION = "us_equity_yahoo_adjusted_eod_import_report_v1"
DEFAULT_OUTPUT_ROOT = Path("data/external/us_equity_eod/yahoo_chart_adjusted")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/yahoo_adjusted_eod_import_report.json")
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_EXTREME_RETURN_THRESHOLD = 0.45
DEFAULT_MAX_STALENESS_DAYS = 14
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

Fetcher = Callable[[str, str, str], Mapping[str, Any]]


def import_yahoo_adjusted_eod(
    *,
    repo_root: Path,
    symbols: Iterable[str],
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
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or _utc_now()
    selected_symbols = tuple(_unique(symbols))
    effective_end_date = end_date or generated[:10]
    output_abs = _resolve(root, output_root)
    report_abs = _resolve(root, report_path)
    kline_root = output_abs / "kline"

    if not execute_network:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "dry_run",
            "network_called": False,
            "writes_performed": False,
            "provider": "yahoo_chart",
            "asset": "us_equity",
            "source_type": "market_data_eod_adjusted_fallback",
            "symbols": list(selected_symbols),
            "symbol_count": len(selected_symbols),
            "start_date": start_date,
            "end_date": effective_end_date,
            "output_root": _relpath(output_abs, root),
            "report_path": _relpath(report_abs, root),
            "planned_endpoint": "https://query1.finance.yahoo.com/v8/finance/chart/<SYMBOL>",
            "guardrails": _guardrails(),
            "blockers": [],
        }
        _write_json(report_abs, payload)
        return payload

    client_fetcher = fetcher or _build_yahoo_fetcher()
    symbol_reports: dict[str, Any] = {}
    blockers: list[str] = []
    fetched_symbols: list[str] = []
    skipped_existing_symbols: list[str] = []
    kline_root.mkdir(parents=True, exist_ok=True)

    for symbol in selected_symbols:
        path = kline_root / f"{symbol}.parquet"
        if skip_existing and path.exists():
            try:
                frame = _normalize_existing_frame(pd.read_parquet(path), symbol)
                quality = _symbol_quality(
                    frame,
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
            except Exception as exc:  # noqa: BLE001
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
            response = client_fetcher(symbol, start_date, effective_end_date)
            frame = normalize_yahoo_chart_response(symbol, response)
            if frame.empty:
                blocker = f"yahoo_{symbol.lower()}_empty_response"
                symbol_reports[symbol] = {"status": "empty", "rows": 0, "blockers": [blocker]}
                blockers.append(blocker)
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
        except Exception as exc:  # noqa: BLE001
            blocker = f"yahoo_{symbol.lower()}_fetch_failed"
            symbol_reports[symbol] = {
                "status": "failed",
                "rows": 0,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "blockers": [blocker],
            }
            blockers.append(blocker)

    available_symbols = [symbol for symbol, row in symbol_reports.items() if row.get("status") == "available"]
    missing_symbols = sorted(set(selected_symbols) - set(available_symbols))
    if missing_symbols:
        blockers.append("yahoo_required_symbols_missing")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "pass" if not blockers else "partial",
        "network_called": bool(fetched_symbols),
        "writes_performed": True,
        "provider": "yahoo_chart",
        "asset": "us_equity",
        "source_type": "market_data_eod_adjusted_fallback",
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
        "symbol_reports": symbol_reports,
        "summary": _summary(symbol_reports),
        "guardrails": _guardrails(),
        "blockers": _dedupe(blockers),
    }
    _write_json(report_abs, payload)
    return payload


def normalize_yahoo_chart_response(symbol: str, response: Mapping[str, Any]) -> pd.DataFrame:
    chart = response.get("chart") if isinstance(response, Mapping) else None
    if not isinstance(chart, Mapping):
        return _empty_frame()
    result = chart.get("result")
    if not isinstance(result, list) or not result:
        return _empty_frame()
    first = result[0]
    if not isinstance(first, Mapping):
        return _empty_frame()
    timestamps = first.get("timestamp") or []
    indicators = first.get("indicators") if isinstance(first.get("indicators"), Mapping) else {}
    quotes = indicators.get("quote") if isinstance(indicators, Mapping) else []
    quote = quotes[0] if isinstance(quotes, list) and quotes else {}
    adj = indicators.get("adjclose") if isinstance(indicators, Mapping) else []
    adjclose = (adj[0] if isinstance(adj, list) and adj else {}).get("adjclose", [])

    records: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        raw_open = _at(quote.get("open"), idx)
        raw_high = _at(quote.get("high"), idx)
        raw_low = _at(quote.get("low"), idx)
        raw_close = _at(quote.get("close"), idx)
        raw_volume = _at(quote.get("volume"), idx)
        adjusted_close = _at(adjclose, idx)
        if raw_close is None or adjusted_close is None or raw_close <= 0.0 or adjusted_close <= 0.0:
            continue
        ratio = adjusted_close / raw_close
        records.append(
            {
                "datetime": pd.Timestamp(datetime.fromtimestamp(int(ts), tz=timezone.utc)).normalize(),
                "symbol": symbol.upper(),
                "Open": _adjust(raw_open, ratio),
                "High": _adjust(raw_high, ratio),
                "Low": _adjust(raw_low, ratio),
                "Close": float(adjusted_close),
                "Volume": _number_or_nan(raw_volume),
                "RawOpen": _number_or_nan(raw_open),
                "RawHigh": _number_or_nan(raw_high),
                "RawLow": _number_or_nan(raw_low),
                "RawClose": _number_or_nan(raw_close),
                "RawVolume": _number_or_nan(raw_volume),
                "AdjustmentRatio": float(ratio),
                "DivCash": float("nan"),
                "SplitFactor": float("nan"),
                "source": "yahoo_chart_adjusted",
            }
        )
    if not records:
        return _empty_frame()
    frame = pd.DataFrame(records)
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    return frame.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)


def _build_yahoo_fetcher() -> Fetcher:
    def fetch(symbol: str, start_date: str, end_date: str) -> Mapping[str, Any]:
        period1 = _epoch_seconds(start_date)
        period2 = _epoch_seconds(end_date, end_exclusive=True)
        query = urllib.parse.urlencode(
            {
                "period1": period1,
                "period2": period2,
                "interval": "1d",
                "events": "history|div|split",
                "includeAdjustedClose": "true",
            }
        )
        url = f"{YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol.upper()))}?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise RuntimeError("yahoo_response_not_object")
        return payload

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
        return {"status": "empty", "rows": 0, "blockers": [f"yahoo_{symbol.lower()}_empty_response"]}
    ohlc = frame[["Open", "High", "Low", "Close"]].astype(float)
    non_positive = int((ohlc <= 0).any(axis=1).sum())
    invalid = int(((ohlc["High"] < ohlc[["Open", "Close", "Low"]].max(axis=1)) | (ohlc["Low"] > ohlc[["Open", "Close", "High"]].min(axis=1))).sum())
    duplicates = int(frame["datetime"].duplicated().sum())
    returns = frame["Close"].astype(float).pct_change(fill_method=None).abs()
    extreme = int((returns > extreme_return_threshold).sum())
    latest = pd.Timestamp(frame["datetime"].max()).tz_convert("UTC")
    generated_ts = pd.Timestamp(generated_at)
    if generated_ts.tzinfo is None:
        generated_ts = generated_ts.tz_localize("UTC")
    staleness_days = int((generated_ts.normalize() - latest.normalize()).days)
    if non_positive:
        blockers.append(f"yahoo_{symbol.lower()}_non_positive_ohlc")
    if invalid:
        blockers.append(f"yahoo_{symbol.lower()}_invalid_ohlc")
    if duplicates:
        blockers.append(f"yahoo_{symbol.lower()}_duplicate_dates")
    if extreme:
        blockers.append(f"yahoo_{symbol.lower()}_extreme_daily_return")
    if staleness_days > max_staleness_days:
        blockers.append(f"yahoo_{symbol.lower()}_stale")
    return {
        "status": "available" if not blockers else "quality_concerns",
        "rows": int(len(frame)),
        "start": str(pd.Timestamp(frame["datetime"].min()).date()),
        "end": str(latest.date()),
        "staleness_days": staleness_days,
        "duplicate_dates": duplicates,
        "non_positive_ohlc_rows": non_positive,
        "invalid_ohlc_rows": invalid,
        "extreme_daily_return_rows": extreme,
        "latest_close": float(frame["Close"].iloc[-1]),
        "blockers": blockers,
    }


def _normalize_existing_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return _empty_frame()
    working = frame.copy()
    required = ["datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in working.columns]
    if missing:
        raise ValueError(f"existing Yahoo adjusted lake frame for {symbol} missing columns: {missing}")
    if "symbol" not in working.columns:
        working["symbol"] = symbol.upper()
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    return working.sort_values("datetime").reset_index(drop=True)


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


def _guardrails() -> dict[str, Any]:
    return {
        "api_key_used_for_market_data": False,
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
            "AdjustmentRatio",
            "DivCash",
            "SplitFactor",
            "source",
        ]
    )


def _at(values: object, idx: int) -> float | None:
    if not isinstance(values, list) or idx >= len(values):
        return None
    return _number(values[idx])


def _adjust(value: float | None, ratio: float) -> float:
    if value is None:
        return float("nan")
    return float(value) * float(ratio)


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


def _number_or_nan(value: object) -> float:
    result = _number(value)
    return float("nan") if result is None else float(result)


def _epoch_seconds(value: str, *, end_exclusive: bool = False) -> int:
    parsed = date.fromisoformat(value)
    if end_exclusive:
        parsed = parsed + pd.Timedelta(days=1)
    dt = datetime.combine(parsed, dt_time.min, tzinfo=timezone.utc)
    return int(dt.timestamp())


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Yahoo adjusted EOD bars for US equity research fallback.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--request-sleep-seconds", type=float, default=0.15)
    parser.add_argument("--max-staleness-days", type=int, default=DEFAULT_MAX_STALENESS_DAYS)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    payload = import_yahoo_adjusted_eod(
        repo_root=Path(args.repo_root),
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
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
                "blockers": payload.get("blockers", []),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
