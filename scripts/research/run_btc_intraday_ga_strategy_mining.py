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

from quant_crypto.research.intraday_ga_strategy_mining import (
    DEFAULT_MANIFESTS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SEED,
    run_btc_intraday_ga_strategy_mining,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run offline research-only BTC 5m/15m genetic strategy mining."
    )
    parser.add_argument("--market-db-path", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--manifest-5m", type=Path, default=DEFAULT_MANIFESTS["5m"])
    parser.add_argument("--manifest-15m", type=Path, default=DEFAULT_MANIFESTS["15m"])
    parser.add_argument("--intervals", nargs="+", choices=("5m", "15m"), default=["5m", "15m"])
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--population-size", type=int, default=48)
    parser.add_argument("--generations", type=int, default=16)
    parser.add_argument("--fold-count", type=int, default=4)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--search-round-count", type=int, default=1)
    parser.add_argument("--tail-holdout-viewed-during-engine-refinement", action="store_true")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated_at = (
        datetime.fromisoformat(args.generated_at.replace("Z", "+00:00"))
        if args.generated_at
        else None
    )
    report = run_btc_intraday_ga_strategy_mining(
        market_db_path=args.market_db_path,
        manifest_paths={"5m": args.manifest_5m, "15m": args.manifest_15m},
        output_root=args.output_root,
        intervals=args.intervals,
        seed=args.seed,
        population_size=args.population_size,
        generations=args.generations,
        fold_count=args.fold_count,
        holdout_fraction=args.holdout_fraction,
        max_candidates=args.max_candidates,
        search_round_count=args.search_round_count,
        holdout_viewed_during_engine_refinement=args.tail_holdout_viewed_during_engine_refinement,
        generated_at_utc=generated_at,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "intervals": list(report["interval_results"]),
                "retained_research_candidate_count": report["retained_research_candidate_count"],
                "artifact_hash": report["artifact_hash"],
                "output_root": args.output_root.as_posix(),
                "demo_strategy_registration_allowed": False,
                "paper": False,
                "live": False,
                "private": False,
                "order": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
