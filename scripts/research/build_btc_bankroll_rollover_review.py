from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.bankroll_rollover_review import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_REPORT_PATH,
    build_btc_bankroll_rollover_review,
)
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC bankroll rollover research-only review packet.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--source-report", type=Path, default=DEFAULT_SOURCE_REPORT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_bankroll_rollover_review(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        source_report_path=args.source_report,
        output_dir=args.output_dir,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "source_main_driver": report["source_attribution"]["summary"]["main_driver"],
                "liquidation_sensitivity_row_count": report["liquidation_sensitivity"]["row_count"],
                "cost_stress_row_count": report["funding_cost_stress"]["summary"]["row_count"],
                "rolling_start_count": report["segment_and_rolling_start"]["summary"]["rolling_start_count"],
                "path_dependent": report["segment_and_rolling_start"]["summary"]["path_dependent"],
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
