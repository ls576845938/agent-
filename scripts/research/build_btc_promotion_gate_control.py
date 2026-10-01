from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_promotion_gate_control import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_promotion_gate_control,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the read-only BTC paper promotion gate control report.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_promotion_gate_control(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "gate_count": report["gate_count"],
                "aggregation_batch_id": report.get("aggregation_batch_id"),
                "blocked_gate_count": report["blocked_gate_count"],
                "missing_source_count": report["missing_source_count"],
                "safety_violation_count": report["safety_violation_count"],
                "artifact_freshness": report.get("artifact_freshness", {}),
                "required_rebuild_reports": report.get("required_rebuild_reports", []),
                "root_cause_summary": report.get("root_cause_summary", {}),
                "key_blockers_cn": report["key_blockers_cn"],
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
