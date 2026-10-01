from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.data.immutable_okx_l2_export import (  # noqa: E402
    L2ExportBlocked,
    L2SegmentSource,
    blocked_export_report,
    export_immutable_okx_l2,
)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)


def _segments(args: argparse.Namespace) -> tuple[L2SegmentSource, ...]:
    directories = args.segment_dir or []
    raw_hashes = args.segment_raw_sha256 or []
    manifest_hashes = args.segment_manifest_sha256 or []
    if not directories:
        raise ValueError("at least one --segment-dir is required")
    if not (
        len(directories) == len(raw_hashes) == len(manifest_hashes)
    ):
        raise ValueError(
            "--segment-dir, --segment-raw-sha256, and "
            "--segment-manifest-sha256 counts must match"
        )
    return tuple(
        L2SegmentSource(
            segment_dir=directory,
            expected_raw_sha256=raw_hash,
            expected_manifest_sha256=manifest_hash,
        )
        for directory, raw_hash, manifest_hash in zip(
            directories,
            raw_hashes,
            manifest_hashes,
            strict=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay and export already-landed OKX public WS books segments "
            "into immutable L2 JSONL tables. This command performs no network "
            "collection and does not publish shared data."
        )
    )
    parser.add_argument("--segment-dir", type=Path, action="append")
    parser.add_argument("--segment-raw-sha256", action="append")
    parser.add_argument("--segment-manifest-sha256", action="append")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--producer-role", default="data_steward")
    parser.add_argument("--now", required=True)
    parser.add_argument("--max-clock-lag-ms", type=float, default=5_000.0)
    parser.add_argument("--freshness-sla-minutes", type=float, default=15.0)
    parser.add_argument(
        "--max-inter-message-gap-seconds",
        type=float,
        default=5.0,
    )
    args = parser.parse_args()

    try:
        report = export_immutable_okx_l2(
            segments=_segments(args),
            output_dir=args.output_dir,
            dataset_version=args.dataset_version,
            source_head=args.source_head,
            now=_parse_timestamp(args.now),
            producer_role=args.producer_role,
            max_clock_lag_ms=args.max_clock_lag_ms,
            freshness_sla_minutes=args.freshness_sla_minutes,
            max_inter_message_gap_seconds=(
                args.max_inter_message_gap_seconds
            ),
        )
    except (L2ExportBlocked, ValueError) as exc:
        blockers = (
            list(exc.blockers)
            if isinstance(exc, L2ExportBlocked)
            else [f"export_argument_invalid:{exc}"]
        )
        report = blocked_export_report(
            blockers=blockers,
            dataset_version=args.dataset_version,
        )
        exit_code = 2
    else:
        exit_code = 0

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
