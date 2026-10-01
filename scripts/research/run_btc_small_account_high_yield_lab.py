from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.small_account_high_yield_lab import build_btc_small_account_high_yield_lab


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BTC small-account high-yield research-only lab.")
    parser.add_argument("--market-db", default="data/market_data.sqlite")
    parser.add_argument("--derivatives", default="data/external/btc_derivatives_sentiment/free_sources/free_public_btcusdt_1h_latest/derivatives_sentiment_1h.json")
    parser.add_argument("--source-top5-report", default="artifacts/btc_long_short_top5_review/latest/btc_long_short_top5_review_report.json")
    parser.add_argument("--data-refresh-report", default="artifacts/btc_short_interval_data_refresh/latest/btc_short_interval_data_refresh_report.json")
    parser.add_argument("--output-dir", default="artifacts/btc_small_account_high_yield_lab/latest")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()
    report = build_btc_small_account_high_yield_lab(
        market_db_path=Path(args.market_db),
        derivatives_rows_path=Path(args.derivatives),
        source_top5_report_path=Path(args.source_top5_report),
        data_refresh_report_path=Path(args.data_refresh_report),
        output_dir=Path(args.output_dir),
        top_n=int(args.top_n),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "candidate_count": report["summary"]["candidate_count"],
                "watchlist_count": report["summary"]["watchlist_count"],
                "best_variant_id": report["summary"]["best_variant_id"],
                "best_annual_return_pct": report["summary"]["best_annual_return_pct"],
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
