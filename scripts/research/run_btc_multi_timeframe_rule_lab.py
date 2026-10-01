from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.multi_timeframe_rule_lab import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    build_btc_multi_timeframe_rule_lab,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC multi-timeframe simple rule research-only lab artifacts.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--base-cost-bps", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_multi_timeframe_rule_lab(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "candidate_count": report["validation_design"]["candidate_count"],
                "long_flat_shortlist_count": len(report["extended_research_shortlist"]),
                "short_watchlist_count": len(report["short_research_watchlist"]),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
