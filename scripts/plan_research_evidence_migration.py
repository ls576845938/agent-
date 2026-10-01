#!/usr/bin/env python3
"""Build a read-only migration preparation plan from research evidence audit blockers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_research_evidence import (  # noqa: E402
    audit_research_evidence,
    build_research_evidence_migration_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a read-only migration preparation plan for historical research evidence"
    )
    parser.add_argument(
        "--data-root",
        default="data",
        help="Data root containing research candidates, backtests, and manifests",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when one or more BLOCKER findings are present",
    )
    args = parser.parse_args()

    audit_report = audit_research_evidence(data_root=args.data_root)
    audit_report["strict"] = bool(args.strict)
    plan = build_research_evidence_migration_plan(audit_report)
    plan["strict"] = bool(args.strict)
    print(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False))
    return 1 if args.strict and plan["counts"]["blocker_count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
