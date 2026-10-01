#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_perpetual_paper_runtime_reconciliation import (  # noqa: E402
    DEFAULT_CURRENT_EVENT_LEDGER_PATH,
    DEFAULT_DRILL_EVENT_LEDGER_PATH,
    DEFAULT_OUTPUT_DIR,
    build_btc_perpetual_paper_runtime_reconciliation_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC perpetual paper runtime event-ledger reconciliation report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--current-event-ledger", type=Path, default=DEFAULT_CURRENT_EVENT_LEDGER_PATH)
    parser.add_argument("--drill-event-ledger", type=Path, default=DEFAULT_DRILL_EVENT_LEDGER_PATH)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = build_btc_perpetual_paper_runtime_reconciliation_report(
        output_dir=args.output_dir,
        current_event_ledger_path=args.current_event_ledger,
        drill_event_ledger_path=args.drill_event_ledger,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "event_row_count": report["summary"]["event_row_count"],
                "event_group_count": report["summary"]["event_group_count"],
                "violation_count": report["summary"]["violation_count"],
                "fill_event_count": report["summary"]["fill_event_count"],
                "funding_cashflow_event_count": report["summary"]["funding_cashflow_event_count"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "warnings": report["warnings"],
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
