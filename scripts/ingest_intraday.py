from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.pipeline import DataLakeConfig, DataLakeService


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = ArgumentParser(description="Ingest intraday US equity bars into the local Parquet data lake.")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--bar-size", default="1m", choices=["1m", "2m", "5m", "15m", "30m", "1h"])
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--vendor", default="yfinance")
    args = parser.parse_args()

    service = DataLakeService(DataLakeConfig(data_root=Path(args.data_root)))
    result = service.sync_bars(
        symbol=args.symbol,
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        bar_size=args.bar_size,
        vendor=args.vendor,
        asset_class="equity",
    )
    print(result)
    if result.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
