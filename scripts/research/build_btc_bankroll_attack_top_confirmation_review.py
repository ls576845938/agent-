from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.bankroll_attack_refinement_review import DEFAULT_REPORT_PATH as DEFAULT_ATTACK_REFINEMENT_REPORT_PATH  # noqa: E402
from quant_crypto.research.bankroll_attack_top_confirmation_review import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_bankroll_attack_top_confirmation_review,
)
from quant_crypto.research.simple_trend_rule_lab import BASE_COST_BPS, DEFAULT_DERIVATIVES_ROWS, DEFAULT_MARKET_DB, INITIAL_CAPITAL  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC 10x attack top scheme confirmation research-only review packet.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--source-attack-refinement-report", type=Path, default=DEFAULT_ATTACK_REFINEMENT_REPORT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--base-cost-bps", type=float, default=BASE_COST_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_bankroll_attack_top_confirmation_review(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        source_attack_refinement_report_path=args.source_attack_refinement_report,
        output_dir=args.output_dir,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    summary = report["summary"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "top_scenario_id": summary["top_scenario_id"],
                "base_total_return_pct": summary["base_total_return_pct"],
                "base_min_remaining_capital_pct_after_10pct_spike": summary["base_min_remaining_capital_pct_after_10pct_spike"],
                "canonical_10pct_stress_min_remaining_capital_pct": summary["canonical_10pct_stress_min_remaining_capital_pct"],
                "funding_cost_worst_total_return_pct": summary["funding_cost_worst_total_return_pct"],
                "rolling_start_count": summary["rolling_start_count"],
                "rolling_start_survive_80_rate": summary["rolling_start_survive_80_rate"],
                "forward_observation_research_only_allowed": report["gate"]["forward_observation_research_only_allowed"],
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
