from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_current_packet_approval import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_current_packet_approval_signer_report,
)
from quant_crypto.research.btc_manual_paper_review_approval import (  # noqa: E402
    DEFAULT_PACKET_PATH,
    DEFAULT_RECORD_PATH,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sign/check current BTC paper candidate packet approval record.")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--approval-record", type=Path, default=DEFAULT_RECORD_PATH)
    parser.add_argument("--reviewed-packet", type=Path, default=DEFAULT_PACKET_PATH)
    parser.add_argument("--reviewer", default="user_directed_review_only_record_2026_07_06")
    parser.add_argument("--decision-date-utc", default="")
    parser.add_argument("--expiry-days", type=int, default=14)
    parser.add_argument("--write", action="store_true", help="Write the local approval record for the current packet hash.")
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def main() -> int:
    args = parse_args()
    report = build_btc_current_packet_approval_signer_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        approval_record_path=args.approval_record,
        reviewed_packet_path=args.reviewed_packet,
        reviewer=args.reviewer,
        decision_date_utc=_parse_datetime(args.decision_date_utc),
        expiry_days=args.expiry_days,
        write_record=args.write,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "write_record_requested": report["write_record_requested"],
                "previous_record_reviewed_packet_sha256": report["previous_record_reviewed_packet_sha256"],
                "current_packet_reviewed_hash_sha256": report["current_packet_reviewed_hash_sha256"],
                "previous_record_auto_invalidated": report["previous_record_auto_invalidated"],
                "manual_approval_recorded": report["manual_approval_validation"]["manual_approval_recorded"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
