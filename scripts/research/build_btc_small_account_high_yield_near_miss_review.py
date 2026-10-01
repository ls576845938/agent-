from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.small_account_high_yield_near_miss_review import (  # noqa: E402
    build_btc_small_account_high_yield_near_miss_review,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC high-yield near-miss research-only review package.")
    parser.add_argument("--market-db", default="data/market_data.sqlite")
    parser.add_argument("--derivatives", default="data/external/btc_derivatives_sentiment/free_sources/free_public_btcusdt_1h_latest/derivatives_sentiment_1h.json")
    parser.add_argument("--source-high-yield-report", default="artifacts/btc_small_account_high_yield_lab/latest/btc_small_account_high_yield_lab_report.json")
    parser.add_argument("--source-top5-report", default="artifacts/btc_long_short_top5_review/latest/btc_long_short_top5_review_report.json")
    parser.add_argument("--output-dir", default="artifacts/btc_small_account_high_yield_near_miss/latest")
    args = parser.parse_args()
    report = build_btc_small_account_high_yield_near_miss_review(
        market_db_path=Path(args.market_db),
        derivatives_rows_path=Path(args.derivatives),
        source_high_yield_report_path=Path(args.source_high_yield_report),
        source_top5_report_path=Path(args.source_top5_report),
        output_dir=Path(args.output_dir),
    )
    summary = report["near_miss_summary"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "top10_review_count": summary["top10_review_count"],
                "v2_candidate_count": summary["v2_candidate_count"],
                "v2_watchlist_count": summary["v2_watchlist_count"],
                "best_v2_variant_id": summary["best_v2_variant_id"],
                "best_v2_annual_return_pct": summary["best_v2_annual_return_pct"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
