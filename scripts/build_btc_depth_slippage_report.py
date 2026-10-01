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

from quant_crypto.research.btc_depth_slippage import (  # noqa: E402
    DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT,
    DEFAULT_CONFIG_PATH,
    DEFAULT_CURRENT_EVENT_LEDGER,
    DEFAULT_DRILL_EVENT_LEDGER,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_STRATEGY_FILL_MAPPING_REPORT,
    build_btc_depth_slippage_report,
    build_btc_depth_slippage_fill_mapping_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC research-only depth/slippage evidence from selected perp bundle.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--binance-vision-book-depth-report", type=Path, default=DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT)
    parser.add_argument("--strategy-fill-mapping-report", type=Path, default=DEFAULT_STRATEGY_FILL_MAPPING_REPORT)
    parser.add_argument("--current-event-ledger", type=Path, default=DEFAULT_CURRENT_EVENT_LEDGER)
    parser.add_argument("--drill-event-ledger", type=Path, default=DEFAULT_DRILL_EVENT_LEDGER)
    parser.add_argument("--skip-fill-mapping-build", action="store_true")
    parser.add_argument("--generated-at-utc", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at_utc) if args.generated_at_utc else None
    if not args.skip_fill_mapping_build:
        build_btc_depth_slippage_fill_mapping_report(
            repo_root=args.repo_root,
            config_path=args.config_path,
            output_root=args.output_root,
            current_event_ledger_path=args.current_event_ledger,
            drill_event_ledger_path=args.drill_event_ledger,
            generated_at_utc=generated,
        )
    report = build_btc_depth_slippage_report(
        repo_root=args.repo_root,
        config_path=args.config_path,
        output_root=args.output_root,
        binance_vision_book_depth_report_path=args.binance_vision_book_depth_report,
        strategy_fill_mapping_report_path=args.strategy_fill_mapping_report,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "positive_slippage_floor_bps": report["positive_slippage_floor_bps"],
                "depth_aware_slippage_history_verified": report["depth_aware_slippage_history_verified"],
                "blockers": report["blockers"],
                "output": str((args.output_root / "btc_depth_slippage_report.json")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    main()
