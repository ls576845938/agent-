from __future__ import annotations

from argparse import ArgumentParser
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.oms import OrderManagementSystem
from quant_us.execution.paper_broker import PaperBroker
from quant_us.live.heartbeat import Heartbeat
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.live.runner import LiveRunner, LiveRunnerConfig
from quant_us.risk.kill_switch import KillSwitch
from quant_us.risk.pre_trade import PreTradeRiskEngine


def main() -> None:
    parser = ArgumentParser(description="Run live readiness checks before enabling a broker event loop.")
    parser.add_argument("--broker", choices=["paper", "alpaca"], default="paper")
    parser.add_argument("--ledger-dir", default="data/ledger/paper")
    parser.add_argument("--allow-live-orders", action="store_true")
    parser.add_argument("--skip-reconciliation", action="store_true")
    args = parser.parse_args()

    if args.broker == "alpaca":
        api_key = os.getenv("ALPACA_API_KEY", "")
        api_secret = os.getenv("ALPACA_API_SECRET", "")
        if not api_key or not api_secret:
            print({"status": "blocked", "errors": ["missing_alpaca_credentials"]})
            raise SystemExit(1)
        broker = AlpacaBroker(
            AlpacaBrokerConfig(
                api_key=api_key,
                api_secret=api_secret,
                base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            )
        )
    else:
        broker = PaperBroker()
        ledger = ReconciliationService(args.ledger_dir, broker).ledger
        broker.positions = ledger.latest_positions_from_fills()

    reconciliation = None if args.skip_reconciliation else ReconciliationService(args.ledger_dir, broker)
    runner = LiveRunner(
        oms=OrderManagementSystem(broker, PreTradeRiskEngine(), kill_switch=KillSwitch()),
        heartbeat=Heartbeat(f"{args.broker}-live"),
        reconciliation=reconciliation,
        kill_switch=KillSwitch(),
        config=LiveRunnerConfig(
            require_reconciliation_clean=not args.skip_reconciliation,
            allow_live_orders=args.allow_live_orders,
        ),
    )
    report = runner.start(dry_run=True)
    print({"status": report.status, "checks": report.checks, "errors": report.errors})
    if not report.ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
