from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.backtest.engine import BacktestConfig
from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.data.storage.postgres_store import PostgresConfig, PostgresStateStore
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.risk.pre_trade import PreTradeRiskConfig


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = ArgumentParser(description="Run a local paper-mode simulation and persist an OMS ledger.")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--bar-size", default="1d")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--ledger-dir", default="data/ledger/paper")
    parser.add_argument("--postgres-dsn", default="")
    parser.add_argument("--strategy-id", default="trend_momentum")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--include-events", action="store_true")
    args = parser.parse_args()

    result = run_event_backtest_from_lake(
        data_root=args.data_root,
        symbol=args.symbol,
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        bar_size=args.bar_size,
        strategy_id=args.strategy_id,
        config=BacktestConfig(
            initial_cash=args.capital,
            risk=PreTradeRiskConfig(max_symbol_weight=0.10, max_order_notional_pct=0.10),
        ),
    )
    ledger = JsonlLedgerStore(args.ledger_dir)
    ledger.write_result(result, include_events=args.include_events)
    postgres_counts = None
    if args.postgres_dsn:
        postgres_counts = PostgresStateStore(PostgresConfig(dsn=args.postgres_dsn)).write_result(result, account_id="paper")
    print({"summary": result.summary, "ledger_dir": str(Path(args.ledger_dir).resolve()), "postgres": postgres_counts})


if __name__ == "__main__":
    main()
