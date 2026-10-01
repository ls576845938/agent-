from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.high_yield_v2_followup import (  # noqa: E402
    DEFAULT_COST_MODEL_REPORT,
    DEFAULT_FUNDING_LEDGER_REPORT,
    DEFAULT_OBSERVATION_LEDGER_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PERPETUAL_POLICY_REPORT,
    DEFAULT_PROVIDER_REPORT,
    build_btc_high_yield_v2_followup,
)
from quant_crypto.research.btc_confirmatory_holdout_lock import DEFAULT_LOCK_CONFIG_PATH  # noqa: E402
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC high-yield v2 follow-up: daily observation, loss-control v3, and perp evidence.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--observation-ledger", type=Path, default=DEFAULT_OBSERVATION_LEDGER_PATH)
    parser.add_argument("--holdout-lock", type=Path, default=DEFAULT_LOCK_CONFIG_PATH)
    parser.add_argument("--funding-ledger-report", type=Path, default=DEFAULT_FUNDING_LEDGER_REPORT)
    parser.add_argument("--cost-model-report", type=Path, default=DEFAULT_COST_MODEL_REPORT)
    parser.add_argument("--perpetual-policy-report", type=Path, default=DEFAULT_PERPETUAL_POLICY_REPORT)
    parser.add_argument("--provider-report", type=Path, default=DEFAULT_PROVIDER_REPORT)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_high_yield_v2_followup(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        observation_ledger_path=args.observation_ledger,
        holdout_lock_path=args.holdout_lock,
        funding_ledger_report_path=args.funding_ledger_report,
        cost_model_report_path=args.cost_model_report,
        perpetual_policy_report_path=args.perpetual_policy_report,
        provider_report_path=args.provider_report,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    obs = report["step_1_daily_observation_automation"]
    loss = report["step_2_loss_control_v3_narrow_experiment"]
    perp = report["step_3_perpetual_execution_evidence"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "latest_decision_time": obs["latest_decision_time"],
                "new_observation_written": obs["new_observation_written"],
                "observation_count": obs["observation_count"],
                "holdout_lock_enforced": obs.get("holdout_lock_enforced"),
                "observe_only_violation_count": obs.get("observe_only_violation_count"),
                "selection_use_blocked_by_lock": obs.get("selection_use_blocked_by_lock"),
                "loss_v3_candidate_count": loss["candidate_count"],
                "loss_v3_retained_count": loss["retained_count"],
                "perp_evidence_decision": perp["decision"],
                "perp_promotion_blockers": perp["promotion_blockers"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
