from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_micro_live_preflight import (  # noqa: E402
    DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT,
    DEFAULT_GATE_DASHBOARD_REPORT,
    DEFAULT_KILL_SWITCH_STATUS_REPORT,
    DEFAULT_OBSERVE_ONLY_HEALTH_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OPERATOR_PAPER_INTAKE_ENVELOPE_PATH,
    DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT,
    DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT,
    DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT,
    DEFAULT_PAPER_RUNTIME_REPLAY_REPORT,
    DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_REPORT,
    DEFAULT_STRATEGY_PROMOTION_READINESS_REPORT,
    build_btc_micro_live_preflight,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC micro-live fail-closed preflight report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--observe-only-health-report", type=Path, default=DEFAULT_OBSERVE_ONLY_HEALTH_REPORT)
    parser.add_argument("--strategy-promotion-readiness-report", type=Path, default=DEFAULT_STRATEGY_PROMOTION_READINESS_REPORT)
    parser.add_argument("--kill-switch-status-report", type=Path, default=DEFAULT_KILL_SWITCH_STATUS_REPORT)
    parser.add_argument("--exchange-runtime-gap-report", type=Path, default=DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT)
    parser.add_argument("--paper-runtime-replay-report", type=Path, default=DEFAULT_PAPER_RUNTIME_REPLAY_REPORT)
    parser.add_argument("--paper-runtime-reconciliation-report", type=Path, default=DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT)
    parser.add_argument("--paper-exchange-rule-preflight-report", type=Path, default=DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT)
    parser.add_argument(
        "--paper-risk-circuit-breaker-drill-report",
        type=Path,
        default=DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT,
    )
    parser.add_argument("--perpetual-execution-evidence-report", type=Path, default=DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_REPORT)
    parser.add_argument("--gate-dashboard-report", type=Path, default=DEFAULT_GATE_DASHBOARD_REPORT)
    parser.add_argument("--operator-paper-intake-envelope", type=Path, default=DEFAULT_OPERATOR_PAPER_INTAKE_ENVELOPE_PATH)
    parser.add_argument("--manual-approval-id", default="")
    parser.add_argument("--aggregation-batch-id", default="")
    parser.add_argument("--approved-initial-principal-usdt", type=float, default=0.0)
    parser.add_argument("--approved-max-order-notional-usdt", type=float, default=0.0)
    parser.add_argument("--approved-max-leverage", type=float, default=0.0)
    parser.add_argument("--approved-max-daily-orders", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_micro_live_preflight(
        output_dir=args.output_dir,
        observe_only_health_report_path=args.observe_only_health_report,
        strategy_promotion_readiness_report_path=args.strategy_promotion_readiness_report,
        kill_switch_status_report_path=args.kill_switch_status_report,
        exchange_runtime_gap_report_path=args.exchange_runtime_gap_report,
        paper_runtime_replay_report_path=args.paper_runtime_replay_report,
        paper_runtime_reconciliation_report_path=args.paper_runtime_reconciliation_report,
        paper_exchange_rule_preflight_report_path=args.paper_exchange_rule_preflight_report,
        paper_risk_circuit_breaker_drill_report_path=args.paper_risk_circuit_breaker_drill_report,
        perpetual_execution_evidence_report_path=args.perpetual_execution_evidence_report,
        gate_dashboard_report_path=args.gate_dashboard_report,
        operator_paper_intake_envelope_path=args.operator_paper_intake_envelope,
        aggregation_batch_id=args.aggregation_batch_id or None,
        manual_approval_id=args.manual_approval_id,
        approved_initial_principal_usdt=args.approved_initial_principal_usdt,
        approved_max_order_notional_usdt=args.approved_max_order_notional_usdt,
        approved_max_leverage=args.approved_max_leverage,
        approved_max_daily_orders=args.approved_max_daily_orders,
    )
    summary = report.get("summary", {})
    policy = report.get("policy_state", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "source_count": summary.get("source_count"),
                "missing_source_count": summary.get("missing_source_count"),
                "failed_source_check_count": summary.get("failed_source_check_count"),
                "upstream_blocker_count": summary.get("upstream_blocker_count"),
                "blocker_count": summary.get("blocker_count"),
                "observe_only_60d_complete": summary.get("observe_only_60d_complete"),
                "paper_runtime_current_simulated_fill_count": summary.get("paper_runtime_current_simulated_fill_count"),
                "kill_switch_engaged": summary.get("kill_switch_engaged"),
                "manual_approval_recorded": summary.get("manual_approval_recorded"),
                "micro_live_allowed": policy.get("micro_live_allowed"),
                "live_unlock_allowed": policy.get("live_unlock_allowed"),
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if str(report["status"]).startswith("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
