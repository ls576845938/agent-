#!/usr/bin/env python3
"""V1 closed-loop pipeline: ingest → duckdb → features → backtest.

Stages:
  1. Ingest  — yfinance → raw parquet (with source, ingested_at, data_version, session)
  2. DuckDB   — structured query over cleaned parquet files
  3. Features — momentum, volatility, ADV from cleaned bars
  4. Backtest — event-driven engine with ledger verification

Usage:
  python scripts/run_closed_loop.py                          # all 10 symbols
  python scripts/run_closed_loop.py --symbols AAPL,MSFT      # subset
  python scripts/run_closed_loop.py --mode ingest            # stage 1 only
  python scripts/run_closed_loop.py --mode backtest          # stages 2-4 (skip ingest)
  python scripts/run_closed_loop.py --quality-report         # output data quality JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from config.v1_universe import V1_INTERVALS, V1_SOURCE, V1_SYMBOLS, V1_START
from quant_us.backtest.data_bridge import bars_from_dataframe
from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestRunner
from quant_us.core.calendar import USEquityCalendar
from quant_us.data.connectors.us_equity_ingestion import USEquityIngestionConfig, USEquityIngestionPipeline
from quant_us.data.storage.duckdb_store import DuckDBBarReader, DuckDBQuery
from quant_us.factors.feature_pipeline import FeaturePipeline
from quant_us.strategies.factory import build_strategy


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="V1 closed-loop pipeline")
    p.add_argument("--symbols", default=",".join(V1_SYMBOLS),
                   help="Comma-separated symbols (default: V1 universe)")
    p.add_argument("--start", default=V1_START, help="Start date YYYY-MM-DD")
    p.add_argument("--end", default=date.today().isoformat(), help="End date")
    p.add_argument("--data-root", default="data", help="Data lake root")
    p.add_argument("--capital", type=float, default=100_000.0, help="Initial capital")
    p.add_argument("--strategy", default="trend_momentum", help="Strategy ID")
    p.add_argument("--mode", choices=["full", "ingest", "backtest"], default="full")
    p.add_argument("--quality-report", action="store_true", help="Output quality JSON and exit")
    p.add_argument("--source", default=V1_SOURCE)
    p.add_argument("--interval", default="1d")
    return p.parse_args()


def stage_ingest(symbols: list[str], start: str, end: str, data_root: str, source: str) -> list[dict]:
    """Stage 1: Ingest raw bars, clean, tag sessions, write parquet with metadata."""
    config = USEquityIngestionConfig(
        data_root=data_root,
        source=source,
        symbols=symbols,
        intervals=["1d"],
        start=start,
        end=end,
        generate_manifest=True,
    )
    pipeline = USEquityIngestionPipeline(config)
    results = pipeline.run()
    return [
        {
            "symbol": r.symbol,
            "rows": r.row_count,
            "data_version": r.data_version,
            "manifest": r.manifest_path,
            "error": r.error,
        }
        for r in results
    ]


def stage_duckdb_query(symbols: list[str], start: str, end: str, data_root: str, source: str) -> dict[str, list]:
    """Stage 2: Query cleaned bars via DuckDB. Returns bars grouped by symbol."""
    reader = DuckDBBarReader(Path(data_root) / "raw")
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)

    bars_by_symbol: dict[str, list] = {}
    for symbol in symbols:
        query = DuckDBQuery(
            vendor=source, asset_class="equity", bar_size="1d",
            symbol=symbol, start=start_dt, end=end_dt,
        )
        df = reader.query_bars(query)
        if df.empty:
            print(f"  {symbol}: 0 bars from DuckDB")
            continue
        bars = bars_from_dataframe(df)
        bars_by_symbol[symbol] = bars
        print(f"  {symbol}: {len(bars)} bars ({df['timestamp_utc'].min()} → {df['timestamp_utc'].max()})")
    return bars_by_symbol


def stage_features(bars_by_symbol: dict[str, list]) -> dict:
    """Stage 3: Build factor features from cleaned bars."""
    import pandas as pd

    pipeline = FeaturePipeline()
    all_features: list[dict] = []
    for symbol, bars in bars_by_symbol.items():
        if not bars:
            continue
        rows = [{"timestamp_utc": b.timestamp_utc, "symbol": b.symbol,
                 "open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume} for b in bars]
        frame = pd.DataFrame(rows)
        result = pipeline.build_bar_factors(frame, universe="v1")
        all_features.append({
            "symbol": symbol,
            "rows_written": result.rows_written,
            "status": result.status,
        })
    return {"features": all_features}


def stage_backtest(bars_by_symbol: dict[str, list], strategy_id: str, capital: float) -> dict:
    """Stage 4: Run event-driven backtest with ledger verification."""
    strategy = build_strategy(strategy_id)
    config = UnifiedBacktestConfig(initial_cash=capital, run_id=f"closed_loop_{strategy_id}")
    runner = UnifiedBacktestRunner(config)

    result = runner.run(
        strategies=[strategy],
        bars_override=[b for bars in bars_by_symbol.values() for b in bars],
    )

    return {
        "run_id": result.run_id,
        "equity_consistent": result.equity_consistent,
        "sharpe_ratio": result.summary.get("sharpe_ratio", 0),
        "total_return_pct": result.summary.get("total_return_pct", 0),
        "max_drawdown_pct": result.summary.get("max_drawdown_pct", 0),
        "trade_count": result.summary.get("trade_count", 0),
        "turnover_rate": result.turnover_report.total_turnover if result.turnover_report else 0,
        "is_trustworthy": result.is_trustworthy,
    }


def stage_quality_report(symbols: list[str], data_root: str, source: str) -> list[dict]:
    """Generate data quality report for all symbols."""
    from quant_us.data.storage.data_manifest import DataManifestStore

    reports: list[dict] = []
    store = DataManifestStore(Path(data_root) / "manifests")
    for symbol in symbols:
        manifest = store.read_latest(source=source, symbol=symbol, interval="1d")
        if manifest is None:
            reports.append({"symbol": symbol, "status": "no_manifest"})
            continue
        reports.append({
            "symbol": symbol,
            "data_version": manifest.data_version,
            "coverage_pct": manifest.coverage_pct,
            "quality_score": manifest.quality_score,
            "row_count": manifest.row_count,
            "start": manifest.start,
            "end": manifest.end,
            "is_usable": manifest.is_usable,
            "issues": manifest.issues,
            "cleaning": manifest.cleaning,
        })
    return reports


def main() -> None:
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    print(f"V1 Closed Loop: {len(symbols)} symbols, {args.start} → {args.end}")
    print(f"Mode: {args.mode}, Strategy: {args.strategy}\n")

    result: dict = {"symbols": symbols, "mode": args.mode}

    if args.quality_report:
        result["quality"] = stage_quality_report(symbols, args.data_root, args.source)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.mode in ("full", "ingest"):
        print("── Stage 1: Ingest ──")
        result["ingest"] = stage_ingest(symbols, args.start, args.end, args.data_root, args.source)
        errors = [r for r in result["ingest"] if r["error"]]
        if errors:
            print(f"  {len(errors)} symbol(s) had ingestion errors")

    if args.mode in ("full", "backtest"):
        print("\n── Stage 2: DuckDB Query ──")
        bars_by_symbol = stage_duckdb_query(symbols, args.start, args.end, args.data_root, args.source)

        print("\n── Stage 3: Features ──")
        result["features"] = stage_features(bars_by_symbol)

        print("\n── Stage 4: Backtest ──")
        result["backtest"] = stage_backtest(bars_by_symbol, args.strategy, args.capital)
        bt = result["backtest"]
        print(f"  Sharpe: {bt['sharpe_ratio']:.2f} | Return: {bt['total_return_pct']:.1f}% | "
              f"Drawdown: {bt['max_drawdown_pct']:.1f}% | Trades: {bt['trade_count']}")
        print(f"  Ledger consistent: {bt['equity_consistent']} | Trustworthy: {bt['is_trustworthy']}")

    print(f"\nDone. {args.mode} completed.")

    # Always output quality on full runs
    if args.mode == "full":
        result["quality"] = stage_quality_report(symbols, args.data_root, args.source)


if __name__ == "__main__":
    main()
