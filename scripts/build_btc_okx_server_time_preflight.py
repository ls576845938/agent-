from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_okx_server_time_preflight import (  # noqa: E402
    DEFAULT_MAX_ABS_OFFSET_MS,
    DEFAULT_MAX_ROUND_TRIP_MS,
    DEFAULT_REQUEST_RETRY_COUNT,
    DEFAULT_RETRY_BACKOFF_SECONDS,
    DEFAULT_OUTPUT_DIR,
    build_btc_okx_server_time_preflight_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC OKX public server-time offset preflight report.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    parser.add_argument("--max-abs-offset-ms", type=float, default=DEFAULT_MAX_ABS_OFFSET_MS)
    parser.add_argument("--max-round-trip-ms", type=float, default=DEFAULT_MAX_ROUND_TRIP_MS)
    parser.add_argument("--sample-count", type=int, default=5)
    parser.add_argument("--request-retry-count", type=int, default=DEFAULT_REQUEST_RETRY_COUNT)
    parser.add_argument("--retry-backoff-seconds", type=float, default=DEFAULT_RETRY_BACKOFF_SECONDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated = _parse_utc(args.generated_at_utc) if args.generated_at_utc else None
    report = build_btc_okx_server_time_preflight_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        execute_network=args.execute_network,
        generated_at_utc=generated,
        max_abs_offset_ms=args.max_abs_offset_ms,
        max_round_trip_ms=args.max_round_trip_ms,
        sample_count=args.sample_count,
        request_retry_count=args.request_retry_count,
        retry_backoff_seconds=args.retry_backoff_seconds,
    )
    metrics = report.get("server_time_metrics", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "server_time_offset_verified": report["server_time_offset_verified"],
                "offset_ms": metrics.get("offset_ms"),
                "round_trip_ms": metrics.get("round_trip_ms"),
                "selection_method": metrics.get("selection_method"),
                "valid_sample_count": metrics.get("valid_sample_count"),
                "retry_policy": report.get("retry_policy"),
                "offset_warning": report.get("validation", {}).get("offset_warning"),
                "local_clock_diagnostic_status": report.get("local_clock_diagnostic", {}).get("diagnostic_status"),
                "public_rest_only": report["public_rest_only"],
                "private_endpoint_used": report["private_endpoint_used"],
                "order_endpoint_used": report["order_endpoint_used"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["server_time_offset_verified"] else 1


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
