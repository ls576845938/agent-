from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_perpetual_execution_evidence import (  # noqa: E402
    DEFAULT_ATTACK_OBSERVER_REPORT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_COST_MODEL_REPORT,
    DEFAULT_EXCHANGE_RUNTIME_CONTRACT,
    DEFAULT_EXCHANGE_RUNTIME_REPLAY_GAP_REPORT,
    DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT,
    DEFAULT_FUNDING_LEDGER_REPORT,
    DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
    DEFAULT_LIQUIDATION_RISK_CONTRACT,
    DEFAULT_LONG_SHORT_OBSERVER_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PERPETUAL_POLICY_REPORT,
    DEFAULT_PROVIDER_REPORT,
    build_btc_perpetual_execution_evidence_pack,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC perpetual execution evidence pack.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--provider-report", type=Path, default=DEFAULT_PROVIDER_REPORT)
    parser.add_argument("--cost-model-report", type=Path, default=DEFAULT_COST_MODEL_REPORT)
    parser.add_argument("--funding-ledger-report", type=Path, default=DEFAULT_FUNDING_LEDGER_REPORT)
    parser.add_argument("--perpetual-policy-report", type=Path, default=DEFAULT_PERPETUAL_POLICY_REPORT)
    parser.add_argument("--exchange-runtime-contract", type=Path, default=DEFAULT_EXCHANGE_RUNTIME_CONTRACT)
    parser.add_argument("--exchange-runtime-replay-gap-report", type=Path, default=DEFAULT_EXCHANGE_RUNTIME_REPLAY_GAP_REPORT)
    parser.add_argument("--binance-vision-book-depth-report", type=Path, default=DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT)
    parser.add_argument("--liquidation-risk-contract", type=Path, default=DEFAULT_LIQUIDATION_RISK_CONTRACT)
    parser.add_argument("--long-short-observer-report", type=Path, default=DEFAULT_LONG_SHORT_OBSERVER_REPORT)
    parser.add_argument("--attack-observer-report", type=Path, default=DEFAULT_ATTACK_OBSERVER_REPORT)
    parser.add_argument("--high-yield-followup-report", type=Path, default=DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_perpetual_execution_evidence_pack(
        output_dir=args.output_dir,
        config_path=args.config,
        provider_report_path=args.provider_report,
        cost_model_report_path=args.cost_model_report,
        funding_ledger_report_path=args.funding_ledger_report,
        perpetual_policy_report_path=args.perpetual_policy_report,
        exchange_runtime_contract_path=args.exchange_runtime_contract,
        exchange_runtime_replay_gap_report_path=args.exchange_runtime_replay_gap_report,
        binance_vision_book_depth_report_path=args.binance_vision_book_depth_report,
        liquidation_risk_contract_path=args.liquidation_risk_contract,
        long_short_observer_report_path=args.long_short_observer_report,
        attack_observer_report_path=args.attack_observer_report,
        high_yield_followup_report_path=args.high_yield_followup_report,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "pass_count": report["summary"]["pass_count"],
                "fail_count": report["summary"]["fail_count"],
                "warn_count": report["summary"]["warn_count"],
                "blocker_count": report["summary"]["blocker_count"],
                "selected_bundle_matches_config": report["selected_bundle"]["provider_report_matches_config"],
                "latest_strategy_decision_time": report["latest_strategy_decision_time"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
                "checklist_csv": report["outputs"]["checklist_csv"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
