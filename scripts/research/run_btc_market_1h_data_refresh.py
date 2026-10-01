from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.short_interval_data_refresh import build_btc_market_1h_data_refresh


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh/audit BTCUSDT 1h research data.")
    parser.add_argument("--market-db", default="data/market_data.sqlite")
    parser.add_argument("--output-dir", default="artifacts/btc_market_1h_data_refresh/latest")
    parser.add_argument("--execute-network", action="store_true", help="Fetch missing 1h rows from Binance public spot REST.")
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--fetch-limit", type=int, default=1000)
    args = parser.parse_args()
    report = build_btc_market_1h_data_refresh(
        market_db_path=Path(args.market_db),
        output_dir=Path(args.output_dir),
        execute_network=bool(args.execute_network),
        sleep_seconds=float(args.sleep_seconds),
        fetch_limit=int(args.fetch_limit),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "blockers": report["blockers"],
                "target_last_1h_close_time": report["target"].get("target_last_1h_close_time"),
                "network_called": report["network"]["network_called"],
                "rows_written": report["network"]["rows_written"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
