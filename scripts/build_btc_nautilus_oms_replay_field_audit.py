#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_nautilus_oms_replay_field_audit import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_nautilus_oms_replay_field_audit,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only BTC Nautilus-style OMS/replay field audit.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--external-references-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_nautilus_oms_replay_field_audit(
        repo_root=args.repo_root,
        external_references_root=args.external_references_root,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "summary": report["summary"],
                "followup_ticket_count": len(report["required_followup_tickets"]),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "broker_or_order_allowed": report["gate"]["broker_or_order_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
