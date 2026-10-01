from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_paper_live_kill_switch_status import (  # noqa: E402
    DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT,
    DEFAULT_GATE_DASHBOARD_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT,
    DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT,
    DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT,
    DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT,
    DEFAULT_READINESS_REPORT,
    build_btc_paper_live_kill_switch_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC paper/live kill-switch status report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--readiness-report", type=Path, default=DEFAULT_READINESS_REPORT)
    parser.add_argument("--exchange-runtime-gap-report", type=Path, default=DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT)
    parser.add_argument("--paper-runtime-reconciliation-report", type=Path, default=DEFAULT_PAPER_RUNTIME_RECONCILIATION_REPORT)
    parser.add_argument("--paper-exchange-rule-preflight-report", type=Path, default=DEFAULT_PAPER_EXCHANGE_RULE_PREFLIGHT_REPORT)
    parser.add_argument(
        "--paper-risk-circuit-breaker-drill-report",
        type=Path,
        default=DEFAULT_PAPER_RISK_CIRCUIT_BREAKER_DRILL_REPORT,
    )
    parser.add_argument("--perp-execution-evidence-report", type=Path, default=DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT)
    parser.add_argument("--gate-dashboard-report", type=Path, default=DEFAULT_GATE_DASHBOARD_REPORT)
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_paper_live_kill_switch_status(
        output_dir=args.output_dir,
        readiness_report_path=args.readiness_report,
        exchange_runtime_gap_report_path=args.exchange_runtime_gap_report,
        paper_runtime_reconciliation_report_path=args.paper_runtime_reconciliation_report,
        paper_exchange_rule_preflight_report_path=args.paper_exchange_rule_preflight_report,
        paper_risk_circuit_breaker_drill_report_path=args.paper_risk_circuit_breaker_drill_report,
        perp_execution_evidence_report_path=args.perp_execution_evidence_report,
        gate_dashboard_report_path=args.gate_dashboard_report,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    summary = report.get("summary", {})
    policy = report.get("policy_state", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "kill_switch_engaged": policy.get("kill_switch_engaged"),
                "cancel_only_mode": policy.get("cancel_only_mode"),
                "paper_order_intake_allowed": policy.get("paper_order_intake_allowed"),
                "position_increase_allowed": policy.get("position_increase_allowed"),
                "micro_live_allowed": policy.get("micro_live_allowed"),
                "manual_approval_recorded": policy.get("manual_approval_recorded"),
                "blocker_count": summary.get("blocker_count"),
                "true_safety_flag_blocker_count": summary.get("true_safety_flag_blocker_count"),
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"].startswith("fail_closed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
