from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.pyramiding_sleeve_lab import DEFAULT_OUTPUT_DIR, build_btc_pyramiding_sleeve_lab  # noqa: E402
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC Pyramiding Sleeve Lab v1 research-only experiment.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_pyramiding_sleeve_lab(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "scenario_count": report["research_design"]["scenario_count"],
                "watchlist_count": summary.get("watchlist_count"),
                "best_scenario_id": summary.get("best_scenario_id"),
                "best_annual_return_pct": summary.get("best_annual_return_pct"),
                "best_min_remaining_after_10pct_spike": summary.get("best_min_remaining_after_10pct_spike"),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
