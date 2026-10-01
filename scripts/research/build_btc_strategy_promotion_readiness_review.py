from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_strategy_promotion_readiness_review import (  # noqa: E402
    DEFAULT_ATTACK_OBSERVER_REPORT,
    DEFAULT_BAR_REPLAY_REPORT,
    DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT,
    DEFAULT_GATE_DASHBOARD_REPORT,
    DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
    DEFAULT_LEAKAGE_AUDIT_REPORT,
    DEFAULT_LONG_SHORT_OBSERVER_REPORT,
    DEFAULT_OBSERVE_ONLY_HEALTH_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PAPER_RUNTIME_REPLAY_REPORT,
    DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT,
    build_btc_strategy_promotion_readiness_review,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC strategy promotion readiness review packet.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bar-replay-report", type=Path, default=DEFAULT_BAR_REPLAY_REPORT)
    parser.add_argument("--leakage-audit-report", type=Path, default=DEFAULT_LEAKAGE_AUDIT_REPORT)
    parser.add_argument("--long-short-observer-report", type=Path, default=DEFAULT_LONG_SHORT_OBSERVER_REPORT)
    parser.add_argument("--attack-observer-report", type=Path, default=DEFAULT_ATTACK_OBSERVER_REPORT)
    parser.add_argument("--high-yield-followup-report", type=Path, default=DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT)
    parser.add_argument("--observe-only-health-report", type=Path, default=DEFAULT_OBSERVE_ONLY_HEALTH_REPORT)
    parser.add_argument("--perp-execution-evidence-report", type=Path, default=DEFAULT_PERP_EXECUTION_EVIDENCE_REPORT)
    parser.add_argument("--paper-runtime-replay-report", type=Path, default=DEFAULT_PAPER_RUNTIME_REPLAY_REPORT)
    parser.add_argument("--exchange-runtime-gap-report", type=Path, default=DEFAULT_EXCHANGE_RUNTIME_GAP_REPORT)
    parser.add_argument("--gate-dashboard-report", type=Path, default=DEFAULT_GATE_DASHBOARD_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_strategy_promotion_readiness_review(
        output_dir=args.output_dir,
        bar_replay_report_path=args.bar_replay_report,
        leakage_audit_report_path=args.leakage_audit_report,
        long_short_observer_report_path=args.long_short_observer_report,
        attack_observer_report_path=args.attack_observer_report,
        high_yield_followup_report_path=args.high_yield_followup_report,
        observe_only_health_report_path=args.observe_only_health_report,
        perp_execution_evidence_report_path=args.perp_execution_evidence_report,
        paper_runtime_replay_report_path=args.paper_runtime_replay_report,
        exchange_runtime_gap_report_path=args.exchange_runtime_gap_report,
        gate_dashboard_report_path=args.gate_dashboard_report,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "strategy_line_count": summary.get("strategy_line_count"),
                "blocked_line_count": summary.get("blocked_line_count"),
                "ready_for_paper_count": summary.get("ready_for_paper_count"),
                "perp_execution_blocker_count": summary.get("perp_execution_blocker_count"),
                "paper_runtime_blocker_count": summary.get("paper_runtime_blocker_count"),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blocker_count": len(report["blockers"]),
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"].startswith("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
