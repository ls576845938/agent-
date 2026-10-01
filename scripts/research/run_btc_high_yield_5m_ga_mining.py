#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.high_yield_5m_ga_mining import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SEED,
    run_btc_high_yield_5m_ga_mining,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run offline research-only BTC high-yield Donchian 5m genetic mining."
    )
    parser.add_argument(
        "--market-db-path",
        type=Path,
        default=None,
        help="Legacy SQLite path; must be paired with --manifest and is never a default.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Legacy manifest path; must be paired with --market-db-path and is never a default.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--population-size", type=int, default=48)
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--fold-count", type=int, default=4)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--search-round-count", type=int, default=1)
    parser.add_argument("--prior-search-population-slots", type=int, default=0)
    parser.add_argument("--prior-search-unique-evaluations", type=int, default=0)
    parser.add_argument(
        "--frozen-unseen-holdout-start",
        default="",
        help=(
            "UTC start of a statistically unseen, one-candidate confirmatory holdout. "
            "Requires --prior-research-cutoff, --max-candidates 1 and "
            "--no-prior-shared-tail-exposure."
        ),
    )
    parser.add_argument(
        "--prior-research-cutoff",
        default="",
        help="UTC last bar previously available to research; must be exactly 5m before holdout start.",
    )
    parser.add_argument("--experiment-id", default="btc-high-yield-5m-ga")
    parser.add_argument(
        "--prior-shared-tail-exposure",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated_at = (
        datetime.fromisoformat(args.generated_at.replace("Z", "+00:00"))
        if args.generated_at
        else None
    )
    frozen_unseen_holdout_start = (
        datetime.fromisoformat(
            args.frozen_unseen_holdout_start.replace("Z", "+00:00")
        )
        if args.frozen_unseen_holdout_start
        else None
    )
    prior_research_cutoff = (
        datetime.fromisoformat(args.prior_research_cutoff.replace("Z", "+00:00"))
        if args.prior_research_cutoff
        else None
    )
    report = run_btc_high_yield_5m_ga_mining(
        market_db_path=args.market_db_path,
        manifest_path=args.manifest,
        repo_root=ROOT,
        output_root=args.output_root,
        seed=args.seed,
        population_size=args.population_size,
        generations=args.generations,
        fold_count=args.fold_count,
        holdout_fraction=args.holdout_fraction,
        max_candidates=args.max_candidates,
        prior_shared_tail_exposure=args.prior_shared_tail_exposure,
        search_round_count=args.search_round_count,
        prior_search_population_slots=args.prior_search_population_slots,
        prior_search_unique_evaluations=args.prior_search_unique_evaluations,
        frozen_unseen_holdout_start_utc=frozen_unseen_holdout_start,
        prior_research_cutoff_utc=prior_research_cutoff,
        experiment_id=args.experiment_id,
        generated_at_utc=generated_at,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "retained_research_candidate_count": report[
                    "retained_research_candidate_count"
                ],
                "artifact_hash": report["artifact_hash"],
                "code_commit": report["code_commit"],
                "output_root": args.output_root.as_posix(),
                "data_consumption": report.get("data_consumption", {}),
                "public_network_called": False,
                "demo_strategy_registration_allowed": False,
                "paper": False,
                "live": False,
                "private": False,
                "order": False,
                "real_order": False,
                "transfer": False,
                "withdraw": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
