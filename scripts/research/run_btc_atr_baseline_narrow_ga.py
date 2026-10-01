from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.atr_baseline_narrow_ga import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    GA_RUN_PROFILES,
    build_btc_atr_baseline_narrow_ga,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC ATR baseline review and narrow formal GA research-only lab.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=20260629)
    parser.add_argument("--run-profile", choices=sorted(GA_RUN_PROFILES), default="formal")
    parser.add_argument("--population-size", type=int, default=None)
    parser.add_argument("--generations", type=int, default=None)
    parser.add_argument("--selected-candidate-count", type=int, default=12)
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--base-cost-bps", type=float, default=10.0)
    parser.add_argument("--validation-fraction", type=float, default=0.20)
    parser.add_argument("--holdout-fraction", type=float, default=0.15)
    parser.add_argument("--embargo-bars", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_atr_baseline_narrow_ga(
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
        validation_fraction=args.validation_fraction,
        holdout_fraction=args.holdout_fraction,
        embargo_bars=args.embargo_bars,
    )
    strongest = report["atr_handwritten_baseline_review"].get("strongest_baseline") or {}
    first_candidate = report["candidate_rule_genomes"][0] if report["candidate_rule_genomes"] else {}
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "run_profile": report["ga_config"]["run_profile"],
                "population_size": report["ga_config"]["population_size"],
                "generations": report["ga_config"]["generations"],
                "trial_count": report["ga_config"]["trial_count"],
                "rejected_count": report["ga_config"]["rejected_count"],
                "seeded_genome_count": report["ga_config"]["seeded_genome_count"],
                "atr_baseline_count": report["atr_handwritten_baseline_review"]["baseline_count"],
                "strongest_atr_baseline": strongest.get("candidate_id"),
                "selected_candidate_count": report["ga_config"]["selected_candidate_count"],
                "top_candidate": first_candidate.get("candidate_id"),
                "top_candidate_decision": first_candidate.get("retention_decision"),
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
