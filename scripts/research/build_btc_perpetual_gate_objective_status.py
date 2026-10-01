from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_perpetual_gate_objective_status import (  # noqa: E402
    DEFAULT_COST_MODEL_REPORT,
    DEFAULT_DASHBOARD_REPORT,
    DEFAULT_DEPTH_REPORT,
    DEFAULT_DRILL_REPORT,
    DEFAULT_EVIDENCE_REPORT,
    DEFAULT_FILL_MAPPING_REPORT,
    DEFAULT_L2_BATCH_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_REPLAY_REPORT,
    build_btc_perpetual_gate_objective_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC perpetual gate current-objective status report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--evidence-report", type=Path, default=DEFAULT_EVIDENCE_REPORT)
    parser.add_argument("--dashboard-report", type=Path, default=DEFAULT_DASHBOARD_REPORT)
    parser.add_argument("--cost-model-report", type=Path, default=DEFAULT_COST_MODEL_REPORT)
    parser.add_argument("--depth-report", type=Path, default=DEFAULT_DEPTH_REPORT)
    parser.add_argument("--fill-mapping-report", type=Path, default=DEFAULT_FILL_MAPPING_REPORT)
    parser.add_argument("--l2-batch-report", type=Path, default=DEFAULT_L2_BATCH_REPORT)
    parser.add_argument("--replay-report", type=Path, default=DEFAULT_REPLAY_REPORT)
    parser.add_argument("--drill-report", type=Path, default=DEFAULT_DRILL_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_perpetual_gate_objective_status(
        output_dir=args.output_dir,
        evidence_report_path=args.evidence_report,
        dashboard_report_path=args.dashboard_report,
        cost_model_report_path=args.cost_model_report,
        depth_report_path=args.depth_report,
        fill_mapping_report_path=args.fill_mapping_report,
        l2_batch_report_path=args.l2_batch_report,
        replay_report_path=args.replay_report,
        drill_report_path=args.drill_report,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "pass_count": report["summary"]["pass_count"],
                "fail_count": report["summary"]["fail_count"],
                "blockers": report["blockers"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
