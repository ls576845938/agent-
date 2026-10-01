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

from quant_crypto.research.ga_factor_mining import (
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SEED,
    run_btc_ga_factor_mining,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-db-path", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows-path", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--lookback-hours", type=int, default=720)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--population-size", type=int, default=64)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--confirmatory-holdout-hours", type=int, default=0)
    parser.add_argument("--decision-time", default="")
    args = parser.parse_args()
    decision_time = (
        datetime.fromisoformat(args.decision_time.replace("Z", "+00:00"))
        if args.decision_time
        else None
    )
    report = run_btc_ga_factor_mining(
        market_db_path=args.market_db_path,
        derivatives_rows_path=args.derivatives_rows_path,
        output_root=args.output_root,
        lookback_hours=args.lookback_hours,
        seed=args.seed,
        population_size=args.population_size,
        generations=args.generations,
        confirmatory_holdout_hours=args.confirmatory_holdout_hours,
        decision_time=decision_time,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "candidate_count": report["ga_config"]["selected_candidate_count"],
                "trial_count": report["ga_config"]["trial_count"],
                "blockers": report["blockers"],
                "output_root": str(args.output_root).replace("\\", "/"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
