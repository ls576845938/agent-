from __future__ import annotations

from argparse import ArgumentParser
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.paper_broker import PaperBroker
from quant_us.live.reconciliation_service import ReconciliationService


def main() -> None:
    parser = ArgumentParser(description="Reconcile local ledger positions against a broker mirror.")
    parser.add_argument("--ledger-dir", default="data/ledger/paper")
    parser.add_argument("--broker", choices=["paper", "alpaca"], default="paper")
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args()

    if args.broker == "alpaca":
        broker = AlpacaBroker(
            AlpacaBrokerConfig(
                api_key=os.getenv("APCA_API_KEY_ID", ""),
                api_secret=os.getenv("APCA_API_SECRET_KEY", ""),
                base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            )
        )
    else:
        broker = PaperBroker()
        broker.positions = ReconciliationService(args.ledger_dir, broker).ledger.latest_positions_from_fills()

    report = ReconciliationService(args.ledger_dir, broker).reconcile_positions(tolerance=args.tolerance)
    print(report)
    if report["status"] != "clean":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
