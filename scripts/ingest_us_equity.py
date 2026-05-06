#!/usr/bin/env python3
"""Ingest US equity bars and generate data manifests.

Usage:
    python scripts/ingest_us_equity.py --symbols AAPL,MSFT,NVDA --intervals 1d
    python scripts/ingest_us_equity.py --all --intervals 1d,1h
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.connectors.us_equity_ingestion import USEquityIngestionConfig, USEquityIngestionPipeline


SP500_TOP = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM",
    "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS", "BAC", "XOM", "CVX",
    "PFE", "CSCO", "ADBE", "NFLX", "CRM", "AMD", "INTC", "QCOM", "TXN", "AVGO",
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest US equity bars")
    parser.add_argument("--symbols", default="AAPL,MSFT,GOOGL", help="Comma-separated symbols")
    parser.add_argument("--intervals", default="1d", help="Comma-separated intervals (1d, 1h, 1m)")
    parser.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--source", default="yfinance", help="Data source")
    parser.add_argument("--data-root", default="data", help="Data root directory")
    parser.add_argument("--all", action="store_true", help="Use S&P 500 top symbols")
    parser.add_argument("--no-manifest", action="store_true", help="Skip manifest generation")
    args = parser.parse_args()

    symbols = SP500_TOP if args.all else [s.strip().upper() for s in args.symbols.split(",")]
    intervals = [s.strip() for s in args.intervals.split(",")]

    config = USEquityIngestionConfig(
        data_root=args.data_root,
        source=args.source,
        symbols=symbols,
        intervals=intervals,
        start=args.start,
        end=args.end,
        generate_manifest=not args.no_manifest,
    )

    pipeline = USEquityIngestionPipeline(config)
    print(f"Ingesting {len(symbols)} symbols x {len(intervals)} intervals from {args.start}")
    print(f"Source: {args.source}, Data root: {args.data_root}")
    print()

    results = pipeline.run()

    ok = sum(1 for r in results if not r.error)
    fail = sum(1 for r in results if r.error)
    total_rows = sum(r.row_count for r in results)

    print(f"\nDone. {ok} ok, {fail} failed, {total_rows} total rows ingested.")


if __name__ == "__main__":
    main()
