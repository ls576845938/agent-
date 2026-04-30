from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.backtest.configuration import build_backtest_config
from quant_us.backtest.engine import EventDrivenBacktestEngine
from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.core.enums import SessionName
from quant_us.core.types import Bar
from quant_us.strategies.factory import build_strategy


def synthetic_daily_bars(symbol: str = "AAPL", count: int = 80) -> list[Bar]:
    start = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    price = 100.0
    day = start
    while len(bars) < count:
        if day.weekday() < 5:
            price *= 1.003
            bars.append(
                Bar(
                    timestamp_utc=day,
                    symbol=symbol,
                    open=price * 0.99,
                    high=price * 1.01,
                    low=price * 0.98,
                    close=price,
                    volume=10_000_000,
                    source="synthetic",
                    session=SessionName.REGULAR.value,
                )
            )
        day += timedelta(days=1)
    return bars


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = ArgumentParser(description="Run a quant_us event-driven backtest.")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols for portfolio-level local data-lake backtests.")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--bar-size", default="1d")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--strategy-id", default="trend_momentum")
    parser.add_argument("--strategy-params-json", default="{}")
    parser.add_argument("--feature-names", default="")
    parser.add_argument("--feature-version", default="v1")
    parser.add_argument("--feature-universe", default="default")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--backtest-params-json", default="{}")
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    backtest_params = json.loads(args.backtest_params_json)
    config = build_backtest_config(capital=args.capital, parameters=backtest_params)
    strategy_params = json.loads(args.strategy_params_json)
    if not args.synthetic and args.start and args.end:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] or [args.symbol.upper()]
        result = run_event_backtest_from_lake(
            data_root=args.data_root,
            symbol=args.symbol,
            symbols=symbols,
            start=parse_utc(args.start),
            end=parse_utc(args.end),
            bar_size=args.bar_size,
            strategy_id=args.strategy_id,
            strategy_params=strategy_params,
            feature_names=[item.strip() for item in args.feature_names.split(",") if item.strip()],
            feature_version=args.feature_version,
            feature_universe=args.feature_universe,
            config=config,
        )
        print(result.summary)
        return

    default_params = {"lookback_bars": 10, "entry_threshold": 0.01} if args.strategy_id == "trend_momentum" else {}
    engine = EventDrivenBacktestEngine([build_strategy(args.strategy_id, strategy_params or default_params)], config=config)
    result = engine.run(synthetic_daily_bars(args.symbol))
    print(result.summary)


if __name__ == "__main__":
    main()
