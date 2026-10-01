#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.strategy_mining_comparison import (
    DEFAULT_DERIVATIVES_FETCH_REPORT,
    DEFAULT_DERIVATIVES_REPORT,
    DEFAULT_DERIVATIVES_STRATEGY_GATE,
    DEFAULT_GA_REPORT,
    DEFAULT_GA_REVIEW_PACKET,
    DEFAULT_INTRADAY_GATE_REPORT,
    DEFAULT_INTRADAY_REPORT,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TIMESFM_REPORT,
    write_btc_extended_strategy_mining_comparison,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build BTC research-only strategy mining comparison and extended research shortlist."
    )
    parser.add_argument("--market-db-path", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--ga-report-path", type=Path, default=DEFAULT_GA_REPORT)
    parser.add_argument("--ga-review-path", type=Path, default=DEFAULT_GA_REVIEW_PACKET)
    parser.add_argument("--derivatives-report-path", type=Path, default=DEFAULT_DERIVATIVES_REPORT)
    parser.add_argument("--derivatives-fetch-report-path", type=Path, default=DEFAULT_DERIVATIVES_FETCH_REPORT)
    parser.add_argument("--derivatives-strategy-gate-path", type=Path, default=DEFAULT_DERIVATIVES_STRATEGY_GATE)
    parser.add_argument("--timesfm-report-path", type=Path, default=DEFAULT_TIMESFM_REPORT)
    parser.add_argument("--intraday-report-path", type=Path, default=DEFAULT_INTRADAY_REPORT)
    parser.add_argument("--intraday-gate-report-path", type=Path, default=DEFAULT_INTRADAY_GATE_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = write_btc_extended_strategy_mining_comparison(
        market_db_path=args.market_db_path,
        ga_report_path=args.ga_report_path,
        ga_review_path=args.ga_review_path,
        derivatives_report_path=args.derivatives_report_path,
        derivatives_fetch_report_path=args.derivatives_fetch_report_path,
        derivatives_strategy_gate_path=args.derivatives_strategy_gate_path,
        timesfm_report_path=args.timesfm_report_path,
        intraday_report_path=args.intraday_report_path,
        intraday_gate_report_path=args.intraday_gate_report_path,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "shortlist_count": len(report["extended_research_shortlist"]),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "output_dir": str(args.output_dir).replace("\\", "/"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
