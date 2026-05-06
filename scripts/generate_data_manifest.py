#!/usr/bin/env python3
"""Generate data_manifest.json for one or more datasets.

Usage:
    python scripts/generate_data_manifest.py --source sqlite --symbol AAPL --interval 1d --start 2024-01-01 --end 2026-04-30
    python scripts/generate_data_manifest.py --source sqlite --symbol AAPL --interval 1d --start 2024-01-01 --end 2026-04-30 --interval 1h
    python scripts/generate_data_manifest.py --all --source sqlite  # generate for all symbols/intervals in DB
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.market_data import inspect_market_data_quality
from quant_us.data.storage.data_manifest import DataManifestStore, build_manifest_from_quality


def get_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def generate_one(
    source: str,
    symbol: str,
    interval: str,
    start: str,
    end: str,
    db_path: str = "",
    store: DataManifestStore | None = None,
) -> str:
    quality = inspect_market_data_quality(
        source=source,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        db_path=db_path,
    )
    manifest = build_manifest_from_quality(
        quality=quality,
        source=source,
        symbol=symbol,
        interval=interval,
        asset_class="equity" if not symbol.upper().endswith(("USDT", "BTC", "ETH")) else "crypto",
        git_commit=get_git_commit(),
    )
    store = store or DataManifestStore()
    path = store.write(manifest)
    print(f"  {manifest.data_version}")
    print(f"    coverage: {manifest.coverage_pct:.2f}%  quality: {manifest.quality_score:.1f}  rows: {manifest.row_count}")
    print(f"    written to {path}")
    return manifest.data_version


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate data manifests for datasets")
    parser.add_argument("--source", default="sqlite", help="Data source (sqlite, fixture, auto)")
    parser.add_argument("--symbol", default="AAPL", help="Ticker symbol")
    parser.add_argument("--interval", default="1d", help="Bar interval (1m, 5m, 1h, 1d)")
    parser.add_argument("--start", default="2024-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2026-04-30", help="End date YYYY-MM-DD")
    parser.add_argument("--db-path", default="", help="Path to SQLite database")
    parser.add_argument("--all", action="store_true", help="Generate for all known combinations")
    parser.add_argument("--list", action="store_true", help="List existing manifests")
    args = parser.parse_args()

    store = DataManifestStore()

    if args.list:
        manifests = store.list_manifests()
        if not manifests:
            print("No manifests found.")
            return
        print(f"{'data_version':<50} {'symbol':<8} {'interval':<6} {'coverage':>8} {'quality':>8} {'rows':>6}")
        print("-" * 90)
        for m in manifests:
            print(f"{m.data_version:<50} {m.symbol:<8} {m.interval:<6} {m.coverage_pct:>7.2f}% {m.quality_score:>7.1f} {m.row_count:>6}")
        return

    print(f"Generating manifests (source={args.source}, interval={args.interval})")
    print(f"Date range: {args.start} → {args.end}")
    print()

    if args.all:
        intervals = ["1d", "1h", "1m"]
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SPY", "QQQ"]
        for interval in intervals:
            for symbol in symbols:
                try:
                    generate_one(
                        source=args.source,
                        symbol=symbol,
                        interval=interval,
                        start=args.start,
                        end=args.end,
                        db_path=args.db_path,
                        store=store,
                    )
                except Exception as exc:
                    print(f"  SKIP {symbol} {interval}: {exc}")
    else:
        generate_one(
            source=args.source,
            symbol=args.symbol,
            interval=args.interval,
            start=args.start,
            end=args.end,
            db_path=args.db_path,
            store=store,
        )

    print(f"\nDone. {len(store.list_manifests())} manifests in {store.root}")


if __name__ == "__main__":
    main()
