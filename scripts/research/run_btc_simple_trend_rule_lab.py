#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.simple_trend_rule_lab import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    build_btc_simple_trend_rule_lab,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BTC simple trend rule research lab.")
    parser.add_argument("--market-db-path", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows-path", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = build_btc_simple_trend_rule_lab(
        market_db_path=args.market_db_path,
        derivatives_rows_path=args.derivatives_rows_path,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "candidate_count": report["validation_design"]["candidate_count"],
                "shortlist_count": len(report["extended_research_shortlist"]),
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
