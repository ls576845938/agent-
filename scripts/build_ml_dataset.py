from __future__ import annotations

from argparse import ArgumentParser
from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.data.storage.feature_store import ParquetFeatureStore
from quant_us.research.datasets import DatasetSpec, MLFeatureDatasetBuilder


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    parser = ArgumentParser(description="Build a leakage-aware ML dataset from cleaned bars and versioned factors.")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols already present in the local data lake.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--bar-size", default="1d")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--vendor", default="yfinance")
    parser.add_argument("--feature-names", default="momentum_score,realized_vol_20,average_dollar_volume_20")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--universe", default="default")
    parser.add_argument("--horizon-bars", type=int, default=5)
    parser.add_argument("--train-end", default="")
    parser.add_argument("--validation-end", default="")
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    feature_names = tuple(item.strip() for item in args.feature_names.split(",") if item.strip())
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

    feature_store = ParquetFeatureStore(Path(args.data_root) / "features")
    factor_frames = [feature_store.read_factor_values(name, args.version) for name in feature_names]
    factor_values = pd.concat([frame for frame in factor_frames if not frame.empty], ignore_index=True) if factor_frames else pd.DataFrame()
    spec = DatasetSpec(
        feature_names=feature_names,
        feature_version=args.version,
        universe=args.universe,
        label_horizon_bars=args.horizon_bars,
        train_end=parse_date(args.train_end),
        validation_end=parse_date(args.validation_end),
    )
    result = MLFeatureDatasetBuilder(Path(args.data_root) / "ml_datasets").build_from_bars_and_factors(bars, factor_values, spec)
    print(result)
    if result.status != "completed" or result.rows_written == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
