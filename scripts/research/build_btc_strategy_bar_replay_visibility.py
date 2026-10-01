from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_strategy_bar_replay_visibility import (  # noqa: E402
    DEFAULT_HIGH_OCTANE_REPORT_PATH,
    DEFAULT_HIGH_OCTANE_ROLLING_PATH,
    DEFAULT_HIGH_OCTANE_WATCHLIST_PATH,
    DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT_PATH,
    DEFAULT_LONG_SHORT_CSV_PATH,
    DEFAULT_LONG_SHORT_REPORT_PATH,
    DEFAULT_OUTPUT_DIR,
    build_btc_strategy_bar_replay_visibility,
)
from quant_crypto.research.simple_trend_rule_lab import (  # noqa: E402
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC bar-replay and field-visibility audit packet.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--long-short-report", type=Path, default=DEFAULT_LONG_SHORT_REPORT_PATH)
    parser.add_argument("--long-short-csv", type=Path, default=DEFAULT_LONG_SHORT_CSV_PATH)
    parser.add_argument("--high-octane-report", type=Path, default=DEFAULT_HIGH_OCTANE_REPORT_PATH)
    parser.add_argument("--high-octane-watchlist", type=Path, default=DEFAULT_HIGH_OCTANE_WATCHLIST_PATH)
    parser.add_argument("--high-octane-rolling", type=Path, default=DEFAULT_HIGH_OCTANE_ROLLING_PATH)
    parser.add_argument("--high-yield-followup-report", type=Path, default=DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT_PATH)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_strategy_bar_replay_visibility(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        long_short_report_path=args.long_short_report,
        long_short_csv_path=args.long_short_csv,
        high_octane_report_path=args.high_octane_report,
        high_octane_watchlist_path=args.high_octane_watchlist,
        high_octane_rolling_path=args.high_octane_rolling,
        high_yield_followup_report_path=args.high_yield_followup_report,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    summary = report.get("summary", {})
    long_short = report.get("long_short_top5_bar_replay", {})
    high_octane = report.get("high_octane_v2_visibility_replay", {})
    high_yield = report.get("high_yield_v2_bar_replay", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "check_fail_count": summary.get("check_fail_count"),
                "check_warn_count": summary.get("check_warn_count"),
                "long_short_row_count": summary.get("long_short_row_count"),
                "long_short_shift_violation_count": summary.get("long_short_shift_violation_count"),
                "long_short_derivatives_visibility_violation_count": summary.get("long_short_derivatives_visibility_violation_count"),
                "high_octane_best_scenario_id": high_octane.get("best_scenario_id"),
                "high_octane_best_margin_over_40pct_threshold": high_octane.get("best_margin_over_40pct_threshold"),
                "high_octane_model_boundary_row_count": summary.get("high_octane_model_boundary_row_count"),
                "high_yield_row_count": summary.get("high_yield_row_count"),
                "high_yield_model_boundary_row_count": summary.get("high_yield_model_boundary_row_count"),
                "high_yield_prior_exposure_return_violation_count": summary.get("high_yield_prior_exposure_return_violation_count"),
                "long_short_verdict": long_short.get("verdict"),
                "high_octane_verdict": high_octane.get("verdict"),
                "high_yield_verdict": high_yield.get("verdict"),
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
