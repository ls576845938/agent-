#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_paper_session_dry_run_manifest import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_paper_session_dry_run_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC paper session dry-run start manifest.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--freshness-sla-hours", type=float, default=24.0)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/paper_ledger/btc_paper_session_dry_run"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_paper_session_dry_run_manifest(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        generated_at_utc=datetime.now(timezone.utc),
        freshness_sla_hours=args.freshness_sla_hours,
        ledger_root=args.ledger_root,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "paper_start_checklist_passed": report["paper_start_checklist_passed"],
                "first_failed_check": report["operator_summary"]["first_failed_check"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "broker_or_order_allowed": report["gate"]["broker_or_order_allowed"],
                "blocker_count": len(report["blockers"]),
                "blockers": report["blockers"][:20],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
