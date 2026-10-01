#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_perpetual_route_request import (  # noqa: E402
    DEFAULT_ATTACK_OBSERVER_REPORT,
    DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
    DEFAULT_LONG_SHORT_OBSERVER_REPORT,
    DEFAULT_OUTPUT_DIR,
    build_btc_perpetual_route_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC research-only perpetual route request.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--long-short-observer-report", type=Path, default=DEFAULT_LONG_SHORT_OBSERVER_REPORT)
    parser.add_argument("--attack-observer-report", type=Path, default=DEFAULT_ATTACK_OBSERVER_REPORT)
    parser.add_argument("--high-yield-followup-report", type=Path, default=DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = build_btc_perpetual_route_request(
        output_dir=args.output_dir,
        long_short_observer_report_path=args.long_short_observer_report,
        attack_observer_report_path=args.attack_observer_report,
        high_yield_followup_report_path=args.high_yield_followup_report,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "perpetual_route_requested": report["perpetual_route_requested"],
                "eligible_strategy_line_count": report["eligible_strategy_line_count"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


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
