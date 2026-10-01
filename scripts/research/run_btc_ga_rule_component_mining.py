from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.ga_rule_component_mining import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    GA_RUN_PROFILES,
    build_btc_ga_rule_component_mining,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC GA rule-component mining research-only lab.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=20260629)
    parser.add_argument("--run-profile", choices=sorted(GA_RUN_PROFILES), default="smoke")
    parser.add_argument("--population-size", type=int, default=None)
    parser.add_argument("--generations", type=int, default=None)
    parser.add_argument("--selected-candidate-count", type=int, default=12)
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--base-cost-bps", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_ga_rule_component_mining(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        seed=args.seed,
        run_profile=args.run_profile,
        population_size=args.population_size,
        generations=args.generations,
        selected_candidate_count=args.selected_candidate_count,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "primitive_count": len(report["primitive_catalog"]),
                "run_profile": report["ga_config"]["run_profile"],
                "population_size": report["ga_config"]["population_size"],
                "generations": report["ga_config"]["generations"],
                "trial_count": report["ga_config"]["trial_count"],
                "rejected_count": report["ga_config"]["rejected_count"],
                "seeded_genome_count": report["ga_config"]["seeded_genome_count"],
                "selected_candidate_count": report["ga_config"]["selected_candidate_count"],
                "handwritten_baseline_count": report["handwritten_rule_baseline_comparison"]["baseline_count"],
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
