from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_paper_candidate_packet import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_paper_candidate_packet,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC paper candidate packet template from promotion gate.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_paper_candidate_packet(repo_root=args.repo_root, output_dir=args.output_dir)
    packet = report["paper_candidate_packet"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "packet_status": packet["packet_status"],
                "packet_generation_allowed_by_promotion_gate": report["generation_authority"][
                    "packet_generation_allowed_by_promotion_gate"
                ],
                "missing_required_fields": report["missing_required_fields"],
                "blocker_count": len(report["blockers"]),
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
