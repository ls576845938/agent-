from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.high_yield_v2_confirmation import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_TOP5_REVIEW_PATH,
    build_btc_high_yield_v2_confirmation,
)
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL  # noqa: E402
from quant_crypto.research.small_account_high_yield_near_miss_review import DEFAULT_REPORT_PATH as DEFAULT_NEAR_MISS_REPORT_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC high-yield v2 frozen candidate confirmation packet.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--source-near-miss-report", type=Path, default=DEFAULT_NEAR_MISS_REPORT_PATH)
    parser.add_argument("--source-top5-review", type=Path, default=DEFAULT_SOURCE_TOP5_REVIEW_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--holdout-days", type=int, default=180)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_high_yield_v2_confirmation(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        source_near_miss_report_path=args.source_near_miss_report,
        source_top5_review_path=args.source_top5_review,
        output_dir=args.output_dir,
        holdout_days=args.holdout_days,
        holdout_fraction=args.holdout_fraction,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    summary = report["confirmation_summary"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "frozen_variant_id": report["frozen_candidate"]["variant_id"],
                "annual_return_pct": summary["annual_return_pct"],
                "max_drawdown_abs_pct": summary["max_drawdown_abs_pct"],
                "profit_factor": summary["profit_factor"],
                "holdout_passed": summary["holdout_passed"],
                "costs_2x_survives": summary["costs_2x_survives"],
                "costs_5x_survives": summary["costs_5x_survives"],
                "forward_observation_rows": report["forward_observation"]["daily_plan_row_count"],
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
