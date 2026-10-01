#!/usr/bin/env python3
"""Offline CLI for the serialized US current-HEAD gate rebuild."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_us.application.us_equity_current_head_gate_rebuild import (  # noqa: E402
    rebuild_us_equity_current_head_gate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--run-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repo_root.resolve()
    report = rebuild_us_equity_current_head_gate(
        repo_root=root,
        current_head=_git_head(root),
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
                "derived_reference_count": report["blocker_taxonomy"][
                    "derived_reference_count"
                ],
                "blockers": report["blockers"],
                "run_manifest": report["run_manifest"],
                "safety": report["safety"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    head = result.stdout.strip()
    if result.returncode != 0 or len(head) != 40:
        raise RuntimeError("us_current_head_gate_git_head_unavailable")
    return head


if __name__ == "__main__":
    raise SystemExit(main())
