from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.long_short_top5_review import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_REPORT_PATH,
    build_btc_long_short_top5_review,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC long/short Top 5 research-only review packet.")
    parser.add_argument("--source-report", type=Path, default=DEFAULT_SOURCE_REPORT_PATH)
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--holdout-days", type=int, default=180)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--base-cost-bps", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_long_short_top5_review(
        source_report_path=args.source_report,
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        top_n=args.top_n,
        holdout_days=args.holdout_days,
        holdout_fraction=args.holdout_fraction,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "top_n_reviewed": report["source"]["top_n_reviewed"],
                "holdout_pass_count": report["review_summary"]["holdout_pass_count"],
                "high_concentration_count": report["review_summary"]["high_concentration_count"],
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
