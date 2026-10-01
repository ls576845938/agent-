from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.backtest.runner import bars_from_frame
from quant_us.backtest.walk_forward import WalkForwardConfig, run_walk_forward
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.strategies.momentum_strategy import MomentumStrategy


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = ArgumentParser(description="Run walk-forward event-driven backtests from cleaned local bars.")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--bar-size", default="1d")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--train-bars", type=int, default=60)
    parser.add_argument("--test-bars", type=int, default=20)
    parser.add_argument("--step-bars", type=int, default=20)
    args = parser.parse_args()

    data = DataLakeService(DataLakeConfig(data_root=Path(args.data_root)))
    frame = data.read_cleaned_bars(
        symbol=args.symbol,
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        bar_size=args.bar_size,
    )
    bars = bars_from_frame(frame)
    results = run_walk_forward(
        bars,
        strategy_factory=lambda: MomentumStrategy(lookback_bars=10, entry_threshold=0.01),
        config=WalkForwardConfig(train_bars=args.train_bars, test_bars=args.test_bars, step_bars=args.step_bars),
    )
    for item in results:
        print(
            {
                "test_start": item.window.test_start.isoformat(),
                "test_end": item.window.test_end.isoformat(),
                "summary": item.result.summary,
            }
        )


if __name__ == "__main__":
    main()
