#!/usr/bin/env python3
"""Fetch Yahoo 1-minute bars for US equity research fallback.

Minute bars are stored raw. The report checks whether the current window needs
split/dividend adjustment, but it does not backfill future adjustment factors
into historical minute signals.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd


SCHEMA_VERSION = "us_equity_yahoo_minute_import_report_v1"
DEFAULT_OUTPUT_ROOT = Path("data/external/us_equity_intraday/yahoo_chart/interval=1m")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/yahoo_minute_import_report.json")
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_STALENESS_DAYS = 7
DEFAULT_EXTREME_RETURN_THRESHOLD = 0.12
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

Fetcher = Callable[[str, str, str], Mapping[str, Any]]


def import_yahoo_minute_bars(
    *,
    repo_root: Path,
    symbols: Iterable[str],
    start_date: str | None = None,
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
    effective_start_date = start_date or _default_start_date(effective_end_date)
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
            "source_type": "market_data_intraday_1m_research_fallback",
            "symbols": list(selected_symbols),
            "symbol_count": len(selected_symbols),
            "interval_requested": "1m",
            "start_date": effective_start_date,
            "end_date": effective_end_date,
            "output_root": _relpath(output_abs, root),
            "report_path": _relpath(report_abs, root),
            "guardrails": _guardrails(),
            "blockers": [],
        }
        _write_json(report_abs, payload)
        return payload

    client_fetcher = fetcher or _build_yahoo_fetcher()
    kline_root.mkdir(parents=True, exist_ok=True)
    symbol_reports: dict[str, Any] = {}
    blockers: list[str] = []
    fetched_symbols: list[str] = []
    skipped_existing_symbols: list[str] = []

    for symbol in selected_symbols:
        path = kline_root / f"{symbol}.parquet"
        if skip_existing and path.exists():
            try:
                frame = _normalize_existing_frame(pd.read_parquet(path), symbol)
                quality = _symbol_quality(
                    frame,
                    symbol=symbol,
                    root=root,
                    path=path,
                    generated_at=generated,
                    max_staleness_days=max_staleness_days,
                    extreme_return_threshold=extreme_return_threshold,
                )
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
            response = client_fetcher(symbol, effective_start_date, effective_end_date)
            raw_frame = normalize_yahoo_minute_response(symbol, response)
            frame, incomplete_count = _drop_incomplete_bars(raw_frame, generated)
            if frame.empty:
                blocker = f"yahoo_{symbol.lower()}_minute_empty_response"
                symbol_reports[symbol] = {"status": "empty", "rows": 0, "blockers": [blocker]}
                blockers.append(blocker)
                continue
            frame.to_parquet(path, index=False)
            quality = _symbol_quality(
                frame,
                symbol=symbol,
                root=root,
                path=path,
                generated_at=generated,
                max_staleness_days=max_staleness_days,
                extreme_return_threshold=extreme_return_threshold,
            )
            quality["write_mode"] = "fetched"
            quality["dropped_incomplete_1m_bars"] = incomplete_count
            symbol_reports[symbol] = quality
            fetched_symbols.append(symbol)
            blockers.extend(str(item) for item in quality.get("blockers", []))
        except Exception as exc:  # noqa: BLE001
            blocker = f"yahoo_{symbol.lower()}_minute_fetch_failed"
            symbol_reports[symbol] = {
                "status": "failed",
                "rows": 0,
                "path": _relpath(path, root),
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "blockers": [blocker],
            }
            blockers.append(blocker)

    available_symbols = [symbol for symbol, row in symbol_reports.items() if row.get("status") == "available"]
    missing_symbols = sorted(set(selected_symbols) - set(available_symbols))
    if missing_symbols:
        blockers.append("yahoo_minute_required_symbols_missing")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "pass" if not blockers else "partial",
        "network_called": bool(fetched_symbols),
        "writes_performed": True,
        "provider": "yahoo_chart",
        "asset": "us_equity",
        "source_type": "market_data_intraday_1m_research_fallback",
        "symbols": list(selected_symbols),
        "symbol_count": len(selected_symbols),
        "available_symbols": available_symbols,
        "missing_symbols": missing_symbols,
        "fetched_symbols": fetched_symbols,
        "skipped_existing_symbols": skipped_existing_symbols,
        "skip_existing": skip_existing,
        "interval_requested": "1m",
        "start_date": effective_start_date,
        "end_date": effective_end_date,
        "output_root": _relpath(output_abs, root),
        "kline_root": _relpath(kline_root, root),
        "report_path": _relpath(report_abs, root),
        "symbol_reports": symbol_reports,
        "summary": _summary(symbol_reports),
        "adjustment_controls": {
            "raw_intraday_retained": True,
            "front_adjusted_output_written": False,
            "back_adjusted_output_written": False,
            "no_lookahead_rule": "Do not apply full-history future adjustment factors to historical minute signals.",
            "allowed_adjustment_rule": "Only ex-date-known split/dividend factors with available_time <= decision_time may be applied in a separate PIT-clean derived table.",
            "current_report_check": "Compares local EOD AdjustmentRatio over the minute window; non-constant ratios block research use until PIT factor replay exists.",
        },
        "guardrails": _guardrails(),
        "blockers": _dedupe(blockers),
    }
    _write_json(report_abs, payload)
    return payload


def normalize_yahoo_minute_response(symbol: str, response: Mapping[str, Any]) -> pd.DataFrame:
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

    records: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        raw_open = _number(_at(quote.get("open"), idx))
        raw_high = _number(_at(quote.get("high"), idx))
        raw_low = _number(_at(quote.get("low"), idx))
        raw_close = _number(_at(quote.get("close"), idx))
        raw_volume = _number(_at(quote.get("volume"), idx))
        if raw_open is None or raw_high is None or raw_low is None or raw_close is None:
            continue
        if min(raw_open, raw_high, raw_low, raw_close) <= 0.0:
            continue
        start = pd.Timestamp(datetime.fromtimestamp(int(ts), tz=timezone.utc))
        end = start + pd.Timedelta(minutes=1)
        records.append(
            {
                "datetime": start,
                "bar_start_utc": start,
                "bar_end_utc": end,
                "available_time": end,
                "symbol": symbol.upper(),
                "Open": float(raw_open),
                "High": float(raw_high),
                "Low": float(raw_low),
                "Close": float(raw_close),
                "Volume": 0.0 if raw_volume is None else float(raw_volume),
                "source": "yahoo_chart_intraday_1m",
                "interval": "1m",
                "data_version": "yahoo_chart_intraday_1m_research_fallback_v1",
                "adjustment_policy": "raw_intraday_unadjusted",
                "quality_flags": "",
            }
        )
    if not records:
        return _empty_frame()
    frame = pd.DataFrame(records)
    for column in ("datetime", "bar_start_utc", "bar_end_utc", "available_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)


def _build_yahoo_fetcher() -> Fetcher:
    def fetch(symbol: str, start_date: str, end_date: str) -> Mapping[str, Any]:
        period1 = _epoch_seconds(start_date)
        period2 = _epoch_seconds(end_date, end_exclusive=True)
        query = urllib.parse.urlencode(
            {
                "period1": period1,
                "period2": period2,
                "interval": "1m",
                "events": "history|div|split",
                "includePrePost": "false",
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
    root: Path,
    path: Path,
    generated_at: str,
    max_staleness_days: int,
    extreme_return_threshold: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    if frame.empty:
        return {"status": "empty", "rows": 0, "blockers": [f"yahoo_{symbol.lower()}_minute_empty_response"]}
    ohlc = frame[["Open", "High", "Low", "Close"]].astype(float)
    non_positive = int((ohlc <= 0).any(axis=1).sum())
    invalid = int(
        (
            (ohlc["High"] < ohlc[["Open", "Close", "Low"]].max(axis=1))
            | (ohlc["Low"] > ohlc[["Open", "Close", "High"]].min(axis=1))
        ).sum()
    )
    duplicates = int(frame["datetime"].duplicated().sum())
    max_abs_return = float(frame["Close"].pct_change(fill_method=None).abs().max())
    latest = pd.Timestamp(frame["datetime"].max()).tz_convert("UTC")
    generated_ts = pd.Timestamp(generated_at)
    if generated_ts.tzinfo is None:
        generated_ts = generated_ts.tz_localize("UTC")
    else:
        generated_ts = generated_ts.tz_convert("UTC")
    staleness_days = int((generated_ts.normalize() - latest.normalize()).days)
    if non_positive:
        blockers.append(f"yahoo_{symbol.lower()}_minute_non_positive_ohlc")
    if invalid:
        blockers.append(f"yahoo_{symbol.lower()}_minute_invalid_ohlc")
    if duplicates:
        blockers.append(f"yahoo_{symbol.lower()}_minute_duplicate_timestamps")
    if max_abs_return > extreme_return_threshold:
        blockers.append(f"yahoo_{symbol.lower()}_minute_extreme_return")
    if staleness_days > max_staleness_days:
        blockers.append(f"yahoo_{symbol.lower()}_minute_stale")
    adjustment = _adjustment_ratio_check(root, symbol, frame)
    if adjustment.get("status") == "ratio_not_constant_requires_pit_factor_replay":
        blockers.append(f"{symbol.lower()}_minute_adjustment_ratio_not_constant")
    return {
        "status": "available" if not blockers else "quality_concerns",
        "path": _relpath(path, root),
        "rows": int(len(frame)),
        "start": _ts_str(frame["datetime"].min()),
        "end": _ts_str(frame["datetime"].max()),
        "staleness_days": staleness_days,
        "max_abs_1m_return": _round(max_abs_return),
        "latest_close": _round(float(frame["Close"].iloc[-1])),
        "duplicate_timestamps": duplicates,
        "invalid_ohlc_rows": invalid,
        "non_positive_ohlc_rows": non_positive,
        "adjustment_ratio_check": adjustment,
        "blockers": blockers,
    }


def _adjustment_ratio_check(root: Path, symbol: str, frame: pd.DataFrame) -> dict[str, Any]:
    paths = [
        root / "data/external/us_equity_eod/yahoo_chart_adjusted/kline" / f"{symbol}.parquet",
        root / "data/external/us_equity_eod/tiingo/kline" / f"{symbol}.parquet",
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
        elif {"adjClose", "close"} <= set(window.columns):
            ratio = pd.to_numeric(window["adjClose"], errors="coerce") / pd.to_numeric(window["close"], errors="coerce")
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
            "no_lookahead_note": "Current minute table stays raw; adjusted variants require PIT factor replay.",
        }
    return {
        "status": "eod_adjustment_ratio_unavailable",
        "window_start": start_date,
        "window_end": end_date,
        "front_adjusted_written": False,
        "back_adjusted_written": False,
        "no_lookahead_note": "Raw minute table is usable for same-window research only after explicit adjustment review.",
    }


def _normalize_existing_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return _empty_frame()
    working = frame.copy()
    required = ["datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in working.columns]
    if missing:
        raise ValueError(f"existing Yahoo minute lake frame for {symbol} missing columns: {missing}")
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
    return working.dropna(subset=["datetime", "Open", "High", "Low", "Close"]).sort_values("datetime").reset_index(drop=True)


def _drop_incomplete_bars(frame: pd.DataFrame, generated_at: str) -> tuple[pd.DataFrame, int]:
    if frame.empty:
        return frame, 0
    generated_ts = pd.Timestamp(generated_at)
    if generated_ts.tzinfo is None:
        generated_ts = generated_ts.tz_localize("UTC")
    else:
        generated_ts = generated_ts.tz_convert("UTC")
    completed = frame[pd.to_datetime(frame["bar_end_utc"], utc=True) <= generated_ts].copy()
    return completed.reset_index(drop=True), int(len(frame) - len(completed))


def _summary(symbol_reports: Mapping[str, Any]) -> dict[str, Any]:
    available = [row for row in symbol_reports.values() if row.get("status") == "available"]
    rows = [int(row.get("rows", 0) or 0) for row in symbol_reports.values()]
    latest_dates = [str(row.get("end")) for row in symbol_reports.values() if row.get("end")]
    return {
        "available_symbol_count": len(available),
        "min_rows": min(rows) if rows else 0,
        "max_rows": max(rows) if rows else 0,
        "latest_common_timestamp": min(latest_dates) if latest_dates else None,
        "latest_any_timestamp": max(latest_dates) if latest_dates else None,
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
            "bar_start_utc",
            "bar_end_utc",
            "available_time",
            "symbol",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "source",
            "interval",
            "data_version",
            "adjustment_policy",
            "quality_flags",
        ]
    )


def _at(values: object, idx: int) -> object:
    if not isinstance(values, list) or idx >= len(values):
        return None
    return values[idx]


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


def _default_start_date(end_date: str) -> str:
    parsed = date.fromisoformat(end_date)
    return (parsed - pd.Timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()


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
    parser = argparse.ArgumentParser(description="Fetch Yahoo 1-minute bars for US equity research fallback.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols.")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--request-sleep-seconds", type=float, default=0.15)
    parser.add_argument("--max-staleness-days", type=int, default=DEFAULT_MAX_STALENESS_DAYS)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    payload = import_yahoo_minute_bars(
        repo_root=Path(args.repo_root),
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
        start_date=args.start_date or None,
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
