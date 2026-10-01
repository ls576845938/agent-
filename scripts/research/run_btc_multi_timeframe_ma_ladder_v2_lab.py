from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.multi_timeframe_ma_ladder_v2_lab import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RUN_PROFILE,
    RUN_PROFILES,
    build_btc_multi_timeframe_ma_ladder_v2_lab,
)
from quant_crypto.research.simple_trend_rule_lab import (  # noqa: E402
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    INITIAL_CAPITAL,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC strong-trend MA ladder v2 research-only lab.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    parser.add_argument("--run-profile", choices=sorted(RUN_PROFILES), default=DEFAULT_RUN_PROFILE)
    parser.add_argument("--max-specs", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_multi_timeframe_ma_ladder_v2_lab(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
        run_profile=args.run_profile,
        max_specs=args.max_specs,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "run_profile": report["research_design"]["run_profile"],
                "candidate_count": summary.get("candidate_count"),
                "watchlist_count": summary.get("watchlist_count"),
                "best_variant_id": summary.get("best_variant_id"),
                "best_retention_decision": summary.get("best_retention_decision"),
                "best_annual_return_pct": summary.get("best_annual_return_pct"),
                "best_total_return_pct": summary.get("best_total_return_pct"),
                "best_max_drawdown_abs_pct": summary.get("best_max_drawdown_abs_pct"),
                "best_profit_factor": summary.get("best_profit_factor"),
                "best_campaign_entry_count": summary.get("best_campaign_entry_count"),
                "best_turnover": summary.get("best_turnover"),
                "best_liquidation_proxy_breach_count": summary.get("best_liquidation_proxy_breach_count"),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "warnings": report["warnings"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
