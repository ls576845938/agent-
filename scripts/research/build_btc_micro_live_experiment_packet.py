#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_micro_live_experiment_packet import (  # noqa: E402
    DEFAULT_DEPTH_SLIPPAGE_REPORT,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_FILL_MAPPING_REPORT,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RMB_USDT_RATE,
    build_btc_micro_live_experiment_packet,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC 1000 RMB observe-only micro-live experiment packet.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--depth-slippage-report", type=Path, default=DEFAULT_DEPTH_SLIPPAGE_REPORT)
    parser.add_argument("--fill-mapping-report", type=Path, default=DEFAULT_FILL_MAPPING_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--rmb-usdt-rate", type=float, default=DEFAULT_RMB_USDT_RATE)
    parser.add_argument("--record-count", type=int, default=12)
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = build_btc_micro_live_experiment_packet(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        depth_slippage_report_path=args.depth_slippage_report,
        fill_mapping_report_path=args.fill_mapping_report,
        output_dir=args.output_dir,
        rmb_usdt_rate=args.rmb_usdt_rate,
        record_count=args.record_count,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "decision": report.get("decision"),
                "summary": report.get("summary"),
                "paper_queue_write_allowed": report.get("gate", {}).get("paper_queue_write_allowed"),
                "live_unlock_allowed": report.get("gate", {}).get("live_unlock_allowed"),
                "order_endpoint_used": report.get("guardrails", {}).get("order_endpoint_used"),
                "blockers": report.get("blockers", []),
                "outputs": report.get("outputs", {}),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if str(report.get("status", "")).startswith("blocked") else 0


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
