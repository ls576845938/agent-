#!/usr/bin/env python3
"""Build PIT adjustment replay tables for Tiingo IEX minute bars.

The output is forward total-return adjusted as of each minute bar. It only uses
corporate-action events whose event date is at or before the bar date, so future
splits/dividends are not backfilled into earlier signals.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


SCHEMA_VERSION = "us_equity_tiingo_iex_minute_pit_adjustment_replay_report_v1"
DEFAULT_SYMBOLS = ("QQQ", "TQQQ")
DEFAULT_RAW_ROOT = Path("data/external/us_equity_intraday/tiingo_iex/interval=1m/kline")
DEFAULT_EOD_ROOT = Path("data/external/us_equity_eod/tiingo/kline")
DEFAULT_OUTPUT_ROOT = Path("data/external/us_equity_intraday/tiingo_iex/interval=1m_pit_adjusted")
DEFAULT_FACTOR_ROOT = Path("data/external/us_equity_corporate_actions/tiingo_pit_factor_replay")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/tiingo_iex_minute_pit_adjustment_replay_report.json")


def build_tiingo_iex_minute_pit_adjustment_replay(
    *,
    repo_root: Path,
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    raw_root: Path = DEFAULT_RAW_ROOT,
    eod_root: Path = DEFAULT_EOD_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    factor_root: Path = DEFAULT_FACTOR_ROOT,
    report_path: Path = DEFAULT_REPORT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or _utc_now()
    selected_symbols = tuple(_unique(symbols))
    raw_abs = _resolve(root, raw_root)
    eod_abs = _resolve(root, eod_root)
    output_abs = _resolve(root, output_root)
    factor_abs = _resolve(root, factor_root)
    report_abs = _resolve(root, report_path)
    kline_root = output_abs / "kline"
    kline_root.mkdir(parents=True, exist_ok=True)
    factor_abs.mkdir(parents=True, exist_ok=True)

    symbol_reports: dict[str, Any] = {}
    blockers: list[str] = []
    for symbol in selected_symbols:
        raw_path = raw_abs / f"{symbol}.parquet"
        eod_path = eod_abs / f"{symbol}.parquet"
        adjusted_path = kline_root / f"{symbol}.parquet"
        events_path = factor_abs / f"{symbol}_factor_events.parquet"
        if not raw_path.exists():
            blocker = f"{symbol.lower()}_raw_minute_missing"
            symbol_reports[symbol] = {"status": "blocked", "blockers": [blocker], "raw_path": _relpath(raw_path, root)}
            blockers.append(blocker)
            continue
        if not eod_path.exists():
            blocker = f"{symbol.lower()}_tiingo_eod_missing_for_pit_replay"
            symbol_reports[symbol] = {"status": "blocked", "blockers": [blocker], "eod_path": _relpath(eod_path, root)}
            blockers.append(blocker)
            continue

        raw = _normalize_minute(pd.read_parquet(raw_path), symbol)
        eod = _normalize_eod(pd.read_parquet(eod_path), symbol)
        if raw.empty:
            blocker = f"{symbol.lower()}_raw_minute_empty"
            symbol_reports[symbol] = {"status": "blocked", "blockers": [blocker], "raw_path": _relpath(raw_path, root)}
            blockers.append(blocker)
            continue
        if eod.empty:
            blocker = f"{symbol.lower()}_tiingo_eod_empty_for_pit_replay"
            symbol_reports[symbol] = {"status": "blocked", "blockers": [blocker], "eod_path": _relpath(eod_path, root)}
            blockers.append(blocker)
            continue

        events = _build_factor_events(eod, symbol)
        adjusted = _apply_factor_replay(raw, events)
        adjusted.to_parquet(adjusted_path, index=False)
        events.to_parquet(events_path, index=False)
        symbol_reports[symbol] = _symbol_report(
            raw=raw,
            adjusted=adjusted,
            events=events,
            symbol=symbol,
            root=root,
            raw_path=raw_path,
            adjusted_path=adjusted_path,
            events_path=events_path,
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "pass" if not blockers else "blocked",
        "provider": "tiingo_iex",
        "asset": "us_equity",
        "source_type": "minute_pit_adjustment_replay",
        "symbols": list(selected_symbols),
        "symbol_count": len(selected_symbols),
        "raw_root": _relpath(raw_abs, root),
        "eod_root": _relpath(eod_abs, root),
        "output_root": _relpath(output_abs, root),
        "factor_root": _relpath(factor_abs, root),
        "report_path": _relpath(report_abs, root),
        "adjustment_method": {
            "method_id": "pit_forward_total_return_replay_v1",
            "price_formula": "pit_adjusted_ohlc = raw_ohlc * pit_factor_asof_bar",
            "split_event_factor": "cum_factor *= splitFactor on or after event available_time",
            "dividend_event_factor": "cum_factor *= prev_raw_close / (prev_raw_close - divCash) when divCash > 0",
            "available_time_rule": "corporate action event available_time is event_date 09:30 America/New_York converted to UTC; bars before that timestamp do not receive the event factor",
            "future_factor_backfill_allowed": False,
            "raw_minute_overwrite_allowed": False,
        },
        "guardrails": _guardrails(),
        "symbol_reports": symbol_reports,
        "summary": _summary(symbol_reports),
        "blockers": _dedupe(blockers),
    }
    _write_json(report_abs, payload)
    return payload


def _build_factor_events(eod: pd.DataFrame, symbol: str) -> pd.DataFrame:
    working = eod.sort_values("datetime").copy()
    working["prev_raw_close"] = working["RawClose"].astype(float).shift(1)
    records: list[dict[str, Any]] = []
    cum_factor = 1.0
    for row in working.itertuples(index=False):
        event_date = pd.Timestamp(row.datetime).date()
        available_time = _event_available_time(event_date)
        split_factor = float(getattr(row, "SplitFactor", 1.0) or 1.0)
        div_cash = float(getattr(row, "DivCash", 0.0) or 0.0)
        prev_raw_close = float(getattr(row, "prev_raw_close", float("nan")))
        event_factor = 1.0
        event_types: list[str] = []
        if split_factor and abs(split_factor - 1.0) > 1e-12:
            event_factor *= split_factor
            event_types.append("split")
        if div_cash > 0.0 and pd.notna(prev_raw_close) and prev_raw_close > div_cash:
            event_factor *= prev_raw_close / (prev_raw_close - div_cash)
            event_types.append("cash_dividend")
        if event_factor == 1.0:
            continue
        cum_factor *= event_factor
        records.append(
            {
                "symbol": symbol,
                "event_date": event_date.isoformat(),
                "available_time": available_time,
                "event_types": ",".join(event_types),
                "split_factor": split_factor,
                "div_cash": div_cash,
                "prev_raw_close": prev_raw_close,
                "event_factor": event_factor,
                "cum_pit_factor_after_event": cum_factor,
                "factor_direction": "forward_total_return_pit",
                "future_factor_backfill_allowed": False,
            }
        )
    if not records:
        return pd.DataFrame(
            columns=[
                "symbol",
                "event_date",
                "available_time",
                "event_types",
                "split_factor",
                "div_cash",
                "prev_raw_close",
                "event_factor",
                "cum_pit_factor_after_event",
                "factor_direction",
                "future_factor_backfill_allowed",
            ]
        )
    events = pd.DataFrame(records)
    events["available_time"] = pd.to_datetime(events["available_time"], utc=True)
    return events


def _apply_factor_replay(raw: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    adjusted = raw.sort_values("datetime").copy()
    adjusted["pit_factor"] = 1.0
    if not events.empty:
        event_series = events.sort_values("available_time").set_index("available_time")[
            "cum_pit_factor_after_event"
        ].astype(float)
        factor = event_series.reindex(adjusted["datetime"], method="ffill").fillna(1.0).to_numpy()
        adjusted["pit_factor"] = factor
    for src, dst in (
        ("Open", "PitOpen"),
        ("High", "PitHigh"),
        ("Low", "PitLow"),
        ("Close", "PitClose"),
    ):
        adjusted[dst] = adjusted[src].astype(float) * adjusted["pit_factor"].astype(float)
    adjusted["pit_adjustment_method"] = "pit_forward_total_return_replay_v1"
    adjusted["future_factor_backfill_allowed"] = False
    adjusted["raw_minute_overwritten"] = False
    adjusted["source"] = "tiingo_iex_intraday_1m_pit_adjusted"
    adjusted["data_version"] = "tiingo_iex_intraday_1m_pit_adjusted_v1"
    return adjusted.reset_index(drop=True)


def _symbol_report(
    *,
    raw: pd.DataFrame,
    adjusted: pd.DataFrame,
    events: pd.DataFrame,
    symbol: str,
    root: Path,
    raw_path: Path,
    adjusted_path: Path,
    events_path: Path,
) -> dict[str, Any]:
    no_lookahead_violations = _no_lookahead_violations(adjusted, events)
    return {
        "status": "available" if no_lookahead_violations == 0 else "blocked",
        "raw_path": _relpath(raw_path, root),
        "adjusted_path": _relpath(adjusted_path, root),
        "events_path": _relpath(events_path, root),
        "raw_rows": int(len(raw)),
        "adjusted_rows": int(len(adjusted)),
        "event_count": int(len(events)),
        "start": _ts_str(raw["datetime"].min()),
        "end": _ts_str(raw["datetime"].max()),
        "first_event_available_time": _ts_str(events["available_time"].min()) if not events.empty else None,
        "last_event_available_time": _ts_str(events["available_time"].max()) if not events.empty else None,
        "final_pit_factor": _round(float(adjusted["pit_factor"].iloc[-1])),
        "no_lookahead_violations": no_lookahead_violations,
        "future_factor_backfill_allowed": False,
        "raw_minute_overwritten": False,
        "blockers": ["pit_factor_no_lookahead_violation"] if no_lookahead_violations else [],
        "sample": {
            "first_row": _sample_row(adjusted.iloc[0]),
            "last_row": _sample_row(adjusted.iloc[-1]),
        },
    }


def _no_lookahead_violations(adjusted: pd.DataFrame, events: pd.DataFrame) -> int:
    if events.empty or adjusted.empty:
        return 0
    violations = 0
    bar_times = pd.to_datetime(adjusted["datetime"], utc=True)
    previous_available_time = pd.Timestamp.min.tz_localize("UTC")
    previous_factor = 1.0
    for event in events.sort_values("available_time").itertuples(index=False):
        available_time = pd.Timestamp(event.available_time)
        window = adjusted[(bar_times >= previous_available_time) & (bar_times < available_time)]
        if window.empty:
            previous_available_time = available_time
            previous_factor = float(event.cum_pit_factor_after_event)
            continue
        if (window["pit_factor"].astype(float) - previous_factor).abs().max() > 1e-10:
            violations += 1
        previous_available_time = available_time
        previous_factor = float(event.cum_pit_factor_after_event)
    return violations


def _event_available_time(event_date: Any) -> pd.Timestamp:
    return pd.Timestamp(f"{pd.Timestamp(event_date).date()} 09:30:00", tz="America/New_York").tz_convert("UTC")


def _normalize_minute(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    working = frame.copy()
    required = ["datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in working.columns]
    if missing:
        raise ValueError(f"{symbol} raw minute missing columns: {missing}")
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    if "available_time" not in working.columns:
        working["available_time"] = working["datetime"] + pd.Timedelta(minutes=1)
    working["available_time"] = pd.to_datetime(working["available_time"], utc=True)
    for column in ("Open", "High", "Low", "Close", "Volume"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return working.dropna(subset=["datetime", "Open", "High", "Low", "Close"]).sort_values("datetime").reset_index(drop=True)


def _normalize_eod(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    working = frame.copy()
    required = ["datetime", "RawClose", "DivCash", "SplitFactor"]
    missing = [column for column in required if column not in working.columns]
    if missing:
        raise ValueError(f"{symbol} Tiingo EOD missing columns: {missing}")
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    for column in ("RawClose", "DivCash", "SplitFactor"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return working.dropna(subset=["datetime", "RawClose"]).sort_values("datetime").reset_index(drop=True)


def _summary(symbol_reports: Mapping[str, Any]) -> dict[str, Any]:
    available = [row for row in symbol_reports.values() if row.get("status") == "available"]
    rows = [int(row.get("adjusted_rows", 0) or 0) for row in symbol_reports.values()]
    return {
        "available_symbol_count": len(available),
        "min_adjusted_rows": min(rows) if rows else 0,
        "max_adjusted_rows": max(rows) if rows else 0,
        "total_event_count": sum(int(row.get("event_count", 0) or 0) for row in symbol_reports.values()),
    }


def _guardrails() -> dict[str, Any]:
    return {
        "private_endpoint_used": False,
        "broker_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "real_order_submitted": False,
        "promotion_clean_granted_by_this_report": False,
    }


def _sample_row(row: pd.Series) -> dict[str, Any]:
    return {
        "datetime": _ts_str(row.get("datetime")),
        "Close": _round(float(row.get("Close"))),
        "PitClose": _round(float(row.get("PitClose"))),
        "pit_factor": _round(float(row.get("pit_factor"))),
    }


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
    parser = argparse.ArgumentParser(description="Build Tiingo IEX minute PIT adjustment replay tables.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--eod-root", default=str(DEFAULT_EOD_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--factor-root", default=str(DEFAULT_FACTOR_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = build_tiingo_iex_minute_pit_adjustment_replay(
        repo_root=Path(args.repo_root),
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
        raw_root=Path(args.raw_root),
        eod_root=Path(args.eod_root),
        output_root=Path(args.output_root),
        factor_root=Path(args.factor_root),
        report_path=Path(args.report),
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "report": payload["report_path"],
                "blockers": payload.get("blockers", []),
                "summary": payload.get("summary", {}),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
