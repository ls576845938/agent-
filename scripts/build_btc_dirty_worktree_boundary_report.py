from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.monitoring.btc_dirty_worktree_boundary import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_dirty_worktree_boundary_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only BTC dirty worktree review-boundary report.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--aggregation-batch-id", default="")
    args = parser.parse_args()
    report = build_btc_dirty_worktree_boundary_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        aggregation_batch_id=args.aggregation_batch_id,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "file_count": report["file_count"],
                "dirty_state_summary": report.get("dirty_state_summary", {}),
                "secret_scan": report.get("secret_scan", {}),
                "boundary_counts": report.get("boundary_counts", []),
                "groups": [
                    {
                        "group_id": row["group_id"],
                        "file_count": row["file_count"],
                        "modified_count": row["modified_count"],
                        "untracked_count": row["untracked_count"],
                    }
                    for row in report["groups"]
                ],
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
