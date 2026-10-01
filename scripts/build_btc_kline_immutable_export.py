from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.data.immutable_kline_export import (  # noqa: E402
    KlineExportBlocked,
    blocked_export_report,
    export_immutable_klines,
)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_partition(value: str) -> tuple[str, str, str]:
    parts = tuple(item.strip() for item in value.split(":"))
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            "--required-partition must be exchange:symbol:interval"
        )
    return parts[0], parts[1], parts[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export a proven read-only BTC K-line SQLite snapshot into "
            "partitioned immutable JSONL tables without publishing it."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--producer-role", default="data_steward")
    parser.add_argument("--now", required=True)
    parser.add_argument("--freshness-sla-hours", type=float, default=48.0)
    parser.add_argument(
        "--required-partition",
        action="append",
        help=(
            "Explicit required exchange:symbol:interval partition; repeatable. "
            "Omitting it strictly validates every source partition."
        ),
    )
    args = parser.parse_args()

    try:
        report = export_immutable_klines(
            source_sqlite=args.source,
            expected_source_sha256=args.source_sha256,
            output_dir=args.output_dir,
            dataset_version=args.dataset_version,
            source_head=args.source_head,
            now=_parse_timestamp(args.now),
            producer_role=args.producer_role,
            freshness_sla_hours=args.freshness_sla_hours,
            required_partitions=(
                tuple(_parse_partition(item) for item in args.required_partition)
                if args.required_partition is not None
                else None
            ),
        )
    except (KlineExportBlocked, ValueError) as exc:
        blockers = (
            list(exc.blockers)
            if isinstance(exc, KlineExportBlocked)
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
