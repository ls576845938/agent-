from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.factors.feature_pipeline import FeaturePipeline


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = ArgumentParser(description="Build factor values from cleaned local bars.")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for portfolio or ML research datasets.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--bar-size", default="1d")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--vendor", default="yfinance")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--universe", default="default")
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] or [args.symbol.upper()]
    data = DataLakeService(DataLakeConfig(data_root=Path(args.data_root)))
    frames = [
        data.read_cleaned_bars(
            symbol=symbol,
            start=parse_utc(args.start),
            end=parse_utc(args.end),
            bar_size=args.bar_size,
            vendor=args.vendor,
            asset_class="equity",
        )
        for symbol in symbols
    ]
    bars = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
    result = FeaturePipeline(feature_root=Path(args.data_root) / "features").build_bar_factors(
        bars,
        universe=args.universe,
        version=args.version,
    )
    print(result)
    if result.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
