from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_exchange_public_runtime_dry_probe import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PUBLIC_WS_COVERAGE_PATH,
    build_btc_exchange_public_runtime_dry_probe,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC OKX public runtime dry probe report.")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--public-ws-coverage", type=Path, default=DEFAULT_PUBLIC_WS_COVERAGE_PATH)
    parser.add_argument("--no-network", action="store_true", help="Plan requests but do not call OKX public REST.")
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_exchange_public_runtime_dry_probe(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        public_ws_coverage_path=args.public_ws_coverage,
        execute_network=not args.no_network,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "network_called": report["network_called"],
                "runtime_layer_status": report["runtime_layer"]["status"],
                "server_time_verified": report["runtime_layer"]["server_time_verified"],
                "symbol_rules_visible": report["runtime_layer"]["symbol_rules_visible"],
                "mark_price_available": report["runtime_layer"]["mark_price_available"],
                "index_price_available": report["runtime_layer"]["index_price_available"],
                "funding_available": report["runtime_layer"]["funding_available"],
                "public_ws_replay_verified": report["runtime_layer"]["public_ws_replay_verified"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
