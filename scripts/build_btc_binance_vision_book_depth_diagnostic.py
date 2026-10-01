#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_binance_vision_book_depth import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    DEFAULT_OUTPUT_DIR,
    build_btc_binance_vision_book_depth_diagnostic,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC Binance Vision free bookDepth diagnostic artifact.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--sleep-seconds", type=float, default=0.02)
    parser.add_argument("--request-timeout-seconds", type=int, default=30)
    parser.add_argument("--network-route-label", default="")
    parser.add_argument("--generated-at-utc", default="")
    parser.add_argument("--no-latest-available-discovery", action="store_true")
    args = parser.parse_args()
    generated = _parse_dt(args.generated_at_utc) if args.generated_at_utc else None
    start = _parse_date(args.start_date) if args.start_date else None
    end = _parse_date(args.end_date) if args.end_date else None
    report = build_btc_binance_vision_book_depth_diagnostic(
        data_root=args.data_root,
        output_dir=args.output_dir,
        generated_at_utc=generated,
        execute_network=args.execute_network,
        start_date=start,
        end_date=end,
        lookback_days=args.lookback_days,
        sleep_seconds=args.sleep_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        network_route_label=args.network_route_label,
        use_latest_available_when_network=not args.no_latest_available_discovery,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "row_count": report["row_count"],
                "coverage_days": report["coverage"]["coverage_days"],
                "gate_eligible_for_selected_venue": report["execution_gate_interpretation"]["gate_eligible_for_selected_venue"],
                "blockers": report["blockers"],
                "output": report["outputs"]["json"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
