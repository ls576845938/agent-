#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_manual_paper_review_approval import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PACKET_PATH,
    DEFAULT_RECORD_PATH,
    build_btc_manual_paper_review_approval,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BTC manual paper review approval record.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--approval-record", type=Path, default=DEFAULT_RECORD_PATH)
    parser.add_argument("--reviewed-packet", type=Path, default=DEFAULT_PACKET_PATH)
    parser.add_argument("--aggregation-batch-id", default="")
    args = parser.parse_args()
    report = build_btc_manual_paper_review_approval(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        approval_record_path=args.approval_record,
        reviewed_packet_path=args.reviewed_packet,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "manual_approval_recorded": report["manual_approval_recorded"],
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
