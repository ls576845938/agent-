from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.bankroll_attack_forward_observer import (  # noqa: E402
    DEFAULT_OBSERVATION_LEDGER_PATH,
    DEFAULT_OUTPUT_DIR,
    run_btc_bankroll_attack_forward_observer,
)
from quant_crypto.research.bankroll_attack_top_confirmation_review import DEFAULT_REPORT_PATH as DEFAULT_TOP_CONFIRMATION_REPORT_PATH  # noqa: E402
from quant_crypto.research.btc_confirmatory_holdout_lock import DEFAULT_LOCK_CONFIG_PATH  # noqa: E402
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC 10x attack observe-only daily forward observer.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--source-top-confirmation-report", type=Path, default=DEFAULT_TOP_CONFIRMATION_REPORT_PATH)
    parser.add_argument("--observation-ledger", type=Path, default=DEFAULT_OBSERVATION_LEDGER_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--holdout-lock", type=Path, default=DEFAULT_LOCK_CONFIG_PATH)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_btc_bankroll_attack_forward_observer(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        source_top_confirmation_report_path=args.source_top_confirmation_report,
        observation_ledger_path=args.observation_ledger,
        output_dir=args.output_dir,
        holdout_lock_path=args.holdout_lock,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    latest = report.get("latest_observation", {})
    progress = report.get("observation_progress", {})
    holdout_lock = report.get("holdout_lock", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "latest_decision_time": latest.get("decision_time"),
                "daily_signal": latest.get("daily_signal", {}),
                "theoretical_sleeve_exposure": latest.get("theoretical_sleeve_exposure", {}),
                "spike_remaining_capital": latest.get("spike_remaining_capital", {}),
                "downgrade_triggered": latest.get("downgrade_triggered"),
                "downgrade_reasons": latest.get("downgrade_reasons", []),
                "observation_count": progress.get("observation_count"),
                "observation_days": progress.get("observation_days"),
                "holdout_lock_enforced": bool(holdout_lock.get("lock_config_present")),
                "holdout_lock_latest_relation_counts": holdout_lock.get("decision_time_relation_counts"),
                "observe_only_violation_count": holdout_lock.get("observe_only_violation_count"),
                "selection_use_blocked_by_lock": holdout_lock.get("selection_use_blocked_by_lock"),
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
