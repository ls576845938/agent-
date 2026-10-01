from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_strategy_leakage_overfit_audit import (  # noqa: E402
    DEFAULT_BAR_REPLAY_REPORT_PATH,
    DEFAULT_HIGH_OCTANE_GRID_PATH,
    DEFAULT_HIGH_OCTANE_REPORT_PATH,
    DEFAULT_HIGH_OCTANE_ROLLING_PATH,
    DEFAULT_HIGH_OCTANE_WATCHLIST_PATH,
    DEFAULT_HOLDOUT_LOCK_AUDIT_REPORT_PATH,
    DEFAULT_ATTACK_FORWARD_REPORT_PATH,
    DEFAULT_DERIVATIVES_FETCH_AUDIT_PATH,
    DEFAULT_LONG_SHORT_CSV_PATH,
    DEFAULT_LONG_SHORT_FORWARD_REPORT_PATH,
    DEFAULT_LONG_SHORT_GRID_PATH,
    DEFAULT_LONG_SHORT_REPORT_PATH,
    DEFAULT_OUTPUT_DIR,
    build_btc_strategy_leakage_overfit_audit,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC future-leakage and overfit audit packet.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--long-short-report", type=Path, default=DEFAULT_LONG_SHORT_REPORT_PATH)
    parser.add_argument("--long-short-csv", type=Path, default=DEFAULT_LONG_SHORT_CSV_PATH)
    parser.add_argument("--long-short-grid", type=Path, default=DEFAULT_LONG_SHORT_GRID_PATH)
    parser.add_argument("--high-octane-report", type=Path, default=DEFAULT_HIGH_OCTANE_REPORT_PATH)
    parser.add_argument("--high-octane-grid", type=Path, default=DEFAULT_HIGH_OCTANE_GRID_PATH)
    parser.add_argument("--high-octane-watchlist", type=Path, default=DEFAULT_HIGH_OCTANE_WATCHLIST_PATH)
    parser.add_argument("--high-octane-rolling", type=Path, default=DEFAULT_HIGH_OCTANE_ROLLING_PATH)
    parser.add_argument("--bar-replay-report", type=Path, default=DEFAULT_BAR_REPLAY_REPORT_PATH)
    parser.add_argument("--holdout-lock-report", type=Path, default=DEFAULT_HOLDOUT_LOCK_AUDIT_REPORT_PATH)
    parser.add_argument("--long-short-forward-report", type=Path, default=DEFAULT_LONG_SHORT_FORWARD_REPORT_PATH)
    parser.add_argument("--attack-forward-report", type=Path, default=DEFAULT_ATTACK_FORWARD_REPORT_PATH)
    parser.add_argument("--derivatives-fetch-audit", type=Path, default=DEFAULT_DERIVATIVES_FETCH_AUDIT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_strategy_leakage_overfit_audit(
        output_dir=args.output_dir,
        long_short_report_path=args.long_short_report,
        long_short_csv_path=args.long_short_csv,
        long_short_grid_path=args.long_short_grid,
        high_octane_report_path=args.high_octane_report,
        high_octane_grid_path=args.high_octane_grid,
        high_octane_watchlist_path=args.high_octane_watchlist,
        high_octane_rolling_path=args.high_octane_rolling,
        bar_replay_report_path=args.bar_replay_report,
        holdout_lock_report_path=args.holdout_lock_report,
        long_short_forward_report_path=args.long_short_forward_report,
        attack_forward_report_path=args.attack_forward_report,
        derivatives_fetch_audit_path=args.derivatives_fetch_audit,
    )
    summary = report.get("summary", {})
    high_octane = report.get("high_octane_v2_audit", {})
    long_short = report.get("long_short_top5_audit", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "check_fail_count": summary.get("check_fail_count"),
                "check_warn_count": summary.get("check_warn_count"),
                "long_short_overfit_verdict": long_short.get("overfit_verdict"),
                "high_octane_overfit_verdict": high_octane.get("overfit_verdict"),
                "high_octane_parameter_mining_verdict": summary.get("high_octane_parameter_mining_verdict"),
                "high_octane_likely_parameter_mined_boundary_candidate": summary.get("high_octane_likely_parameter_mined_boundary_candidate"),
                "high_octane_best_margin_over_40pct_threshold": high_octane.get("best_margin_over_40pct_threshold"),
                "forward_observe_clean_confirmation_ready": summary.get("forward_observe_clean_confirmation_ready"),
                "forward_observe_only_anchor_rows_so_far": summary.get("forward_observe_only_anchor_rows_so_far"),
                "forward_observe_selection_use_blocked_by_lock": summary.get("forward_observe_selection_use_blocked_by_lock"),
                "data_coverage_verdict": summary.get("data_coverage_verdict"),
                "data_coverage_derivatives_row_count": summary.get("data_coverage_derivatives_row_count"),
                "data_coverage_bar_replay_missing_count": summary.get("data_coverage_bar_replay_missing_count"),
                "data_coverage_liquidation_one_hour_history_complete": summary.get("data_coverage_liquidation_one_hour_history_complete"),
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
