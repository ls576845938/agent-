from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.data.universe.universe_builder import UniverseBuilder, UniverseRule


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = ArgumentParser(description="Build a simple liquid US equity universe from cleaned daily bars.")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols already present in the local data lake.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-dollar-volume", type=float, default=20_000_000.0)
    parser.add_argument("--min-history-bars", type=int, default=20)
    args = parser.parse_args()

    data = DataLakeService(DataLakeConfig(data_root=Path(args.data_root)))
    frames = []
    for symbol in [item.strip().upper() for item in args.symbols.split(",") if item.strip()]:
        frame = data.read_cleaned_bars(symbol=symbol, start=parse_utc(args.start), end=parse_utc(args.end), bar_size="1d")
        if not frame.empty:
            frames.append(frame)
    if not frames:
        print([])
        return
    import pandas as pd

    universe = UniverseBuilder(
        UniverseRule(
            min_price=args.min_price,
            min_dollar_volume=args.min_dollar_volume,
            min_history_bars=args.min_history_bars,
        )
    ).from_daily_bars(pd.concat(frames, ignore_index=True))
    print(universe)


if __name__ == "__main__":
    main()
