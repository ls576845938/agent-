#!/usr/bin/env python3
"""Repair external ETF kline parquet files and write a data-quality report."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


DEFAULT_DATA_LAKE = Path("D:/Trading/PythonApplication1/data_cache_lake")
DEFAULT_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/external_etf_kline_quality_report.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-lake", default=str(DEFAULT_DATA_LAKE))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--max-gap-days", type=int, default=10)
    parser.add_argument("--backup-tag", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    args = parser.parse_args()

    data_lake = Path(args.data_lake)
    report_path = Path(args.report)
    report = repair_data_lake(
        data_lake=data_lake,
        threshold=args.threshold,
        max_gap_days=args.max_gap_days,
        backup_tag=args.backup_tag,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "status": report["status"]}, indent=2, sort_keys=True))


def repair_data_lake(
    *,
    data_lake: Path,
    threshold: float,
    max_gap_days: int,
    backup_tag: str,
) -> dict[str, Any]:
    kline_root = data_lake / "kline"
    if not kline_root.exists():
        raise SystemExit(f"missing kline root: {kline_root}")

    symbols = sorted(
        path.stem
        for path in kline_root.glob("*.parquet")
        if ".backup_" not in path.name and not path.name.startswith(".")
    )
    rows: dict[str, Any] = {}
    blockers: list[str] = []
    for symbol in symbols:
        path = kline_root / f"{symbol}.parquet"
        before = _quality_stats(pd.read_parquet(path), threshold=threshold, max_gap_days=max_gap_days)
        backup = path.with_name(f"{symbol}.backup_before_quality_repair_{backup_tag}.parquet")
        if not backup.exists():
            shutil.copy2(path, backup)

        raw = _fetch_akshare_raw(symbol)
        raw_source = "akshare_raw"
        raw_stats = _quality_stats(raw, threshold=threshold, max_gap_days=max_gap_days)
        if raw_stats["long_gap_abs_ret_gt_threshold"]:
            yahoo_raw = _fetch_yahoo_chart_raw(symbol)
            yahoo_stats = _quality_stats(yahoo_raw, threshold=threshold, max_gap_days=max_gap_days)
            if _is_better_gap_source(yahoo_stats, raw_stats):
                raw = yahoo_raw
                raw_source = "yahoo_chart_raw"
                raw_stats = yahoo_stats
        repaired, split_events = _back_adjust_split_jumps(raw, threshold=threshold, max_gap_days=max_gap_days)
        after = _quality_stats(repaired, threshold=threshold, max_gap_days=max_gap_days)
        repaired.to_parquet(path, engine="pyarrow", index=False)

        symbol_status = "pass"
        symbol_blockers: list[str] = []
        if after["nonpositive_ohlc_rows"]:
            symbol_status = "blocked"
            symbol_blockers.append("nonpositive_ohlc_after_repair")
        if after["short_gap_abs_ret_gt_threshold"]:
            symbol_status = "blocked"
            symbol_blockers.append("short_gap_jump_after_repair")
        if after["long_gap_abs_ret_gt_threshold"]:
            symbol_status = "partial"
            symbol_blockers.append("long_history_gap_requires_better_source")

        rows[symbol] = {
            "status": symbol_status,
            "backup": str(backup),
            "repair_source": raw_source,
            "raw_source_quality": raw_stats,
            "before": before,
            "after": after,
            "split_adjustment_events": split_events,
            "blockers": symbol_blockers,
        }
        blockers.extend(f"{symbol}:{blocker}" for blocker in symbol_blockers)

    status = "pass" if not blockers else "partial"
    if any("nonpositive_ohlc_after_repair" in blocker or "short_gap_jump_after_repair" in blocker for blocker in blockers):
        status = "blocked"
    return {
        "schema_version": "external_etf_kline_quality_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_lake": str(data_lake),
        "threshold_abs_daily_return": threshold,
        "max_gap_days_for_split_adjustment": max_gap_days,
        "status": status,
        "promotion_clean": status == "pass",
        "symbols": rows,
        "blockers": blockers,
    }


def _fetch_akshare_raw(symbol: str) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_us_daily(symbol=symbol, adjust="")
    frame = frame.rename(
        columns={
            "date": "datetime",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    required = ["datetime", "Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{symbol} raw frame missing columns: {missing}")
    frame = frame[required].copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=["datetime", "Open", "High", "Low", "Close"])
        .sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
        .reset_index(drop=True)
    )


def _fetch_yahoo_chart_raw(symbol: str) -> pd.DataFrame:
    start = int(pd.Timestamp("2001-01-01", tz="UTC").timestamp())
    # Keep the end wide enough for current local development snapshots.
    end = int((pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=5)).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
    response = requests.get(
        url,
        params={
            "period1": start,
            "period2": end,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    error = payload.get("chart", {}).get("error")
    if error:
        raise ValueError(f"Yahoo chart error for {symbol}: {error}")
    results = payload.get("chart", {}).get("result") or []
    if not results:
        raise ValueError(f"Yahoo chart returned no result for {symbol}")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize(),
            "Open": quote.get("open"),
            "High": quote.get("high"),
            "Low": quote.get("low"),
            "Close": quote.get("close"),
            "Volume": quote.get("volume"),
        }
    )
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=["datetime", "Open", "High", "Low", "Close"])
        .sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
        .reset_index(drop=True)
    )


def _is_better_gap_source(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    return (
        int(candidate["long_gap_abs_ret_gt_threshold"]) < int(baseline["long_gap_abs_ret_gt_threshold"])
        and int(candidate["nonpositive_ohlc_rows"]) == 0
        and int(candidate["short_gap_abs_ret_gt_threshold"]) <= int(baseline["short_gap_abs_ret_gt_threshold"])
    )


def _back_adjust_split_jumps(
    frame: pd.DataFrame,
    *,
    threshold: float,
    max_gap_days: int,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    repaired = frame.copy()
    events: list[dict[str, Any]] = []
    while True:
        returns = repaired["Close"].pct_change()
        gap_days = repaired["datetime"].diff().dt.days
        mask = (returns.abs() > threshold) & (gap_days <= max_gap_days)
        if not bool(mask.any()):
            break
        idx = int(mask[mask].index[0])
        previous_close = float(repaired.loc[idx - 1, "Close"])
        current_close = float(repaired.loc[idx, "Close"])
        if previous_close <= 0 or current_close <= 0:
            break
        factor = current_close / previous_close
        repaired.loc[: idx - 1, ["Open", "High", "Low", "Close"]] *= factor
        if "Volume" in repaired.columns and factor:
            repaired.loc[: idx - 1, "Volume"] /= factor
        events.append(
            {
                "effective_date": repaired.loc[idx, "datetime"].strftime("%Y-%m-%d"),
                "previous_date": repaired.loc[idx - 1, "datetime"].strftime("%Y-%m-%d"),
                "raw_return": float(returns.loc[idx]),
                "back_adjust_factor": factor,
            }
        )
    return repaired, events


def _quality_stats(frame: pd.DataFrame, *, threshold: float, max_gap_days: int) -> dict[str, Any]:
    working = frame.copy()
    if "datetime" not in working.columns:
        working = working.rename(columns={"Date": "datetime", "date": "datetime"})
    working["datetime"] = pd.to_datetime(working["datetime"])
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.sort_values("datetime").drop_duplicates("datetime", keep="last")
    ohlc = working[["Open", "High", "Low", "Close"]]
    returns = working["Close"].pct_change()
    gap_days = working["datetime"].diff().dt.days
    jump_mask = returns.abs() > threshold
    short_gap_jump = jump_mask & (gap_days <= max_gap_days)
    long_gap_jump = jump_mask & (gap_days > max_gap_days)
    return {
        "rows": int(len(working)),
        "start": working["datetime"].min().strftime("%Y-%m-%d") if not working.empty else None,
        "end": working["datetime"].max().strftime("%Y-%m-%d") if not working.empty else None,
        "nonpositive_ohlc_rows": int((ohlc <= 0).any(axis=1).sum()),
        "abs_ret_gt_threshold": int(jump_mask.sum()),
        "short_gap_abs_ret_gt_threshold": int(short_gap_jump.sum()),
        "long_gap_abs_ret_gt_threshold": int(long_gap_jump.sum()),
        "large_calendar_gaps_gt_10d": int((gap_days > 10).sum()),
        "max_abs_return": float(returns.abs().max(skipna=True) or 0.0),
    }


if __name__ == "__main__":
    main()
