#!/usr/bin/env python3
"""Build the offline US final paper-readiness evidence packet."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_us.application.us_equity_final_paper_readiness import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SCHEMA,
    build_us_equity_final_paper_readiness,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo_root.resolve()
    generated = (
        datetime.fromisoformat(args.generated_at.replace("Z", "+00:00"))
        if args.generated_at
        else None
    )
    report = build_us_equity_final_paper_readiness(
        repo_root=root,
        current_head=_git_head(root),
        config_path=args.config,
        schema_path=args.schema,
        output_root=args.output_root,
        generated_at_utc=generated,
        run_id=args.run_id or None,
    )
    print(
        json.dumps(
            {
                "wrapper_status": report["wrapper_status"],
                "status": report["status"],
                "decision": report["decision"],
                "source_head": report["source_head"],
                "run_id": report["run_id"],
                "root_blocker_count": report["blocker_taxonomy"][
                    "root_blocker_count"
                ],
                "promotion_evidence_ready": report["readiness"][
                    "promotion_evidence_ready"
                ],
                "review_stopped_by_engineering_defect": report[
                    "review_stopped_by_engineering_defect"
                ],
                "safety": report["safety"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    head = completed.stdout.strip()
    if completed.returncode != 0 or len(head) != 40:
        raise RuntimeError("us_final_readiness_git_head_unavailable")
    return head


if __name__ == "__main__":
    raise SystemExit(main())
