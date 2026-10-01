from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.multiscale_trend_15m_1h_search import (  # noqa: E402
    DEFAULT_SEED,
    run_btc_multiscale_trend_search,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the preregistered selection-only BTC 15m/30m/1h trend-family search."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--population-per-stratum", type=int, default=12)
    parser.add_argument("--generations", type=int, default=4)
    parser.add_argument("--fold-count", type=int, default=4)
    args = parser.parse_args()
    report = run_btc_multiscale_trend_search(
        repo_root=REPO_ROOT,
        output_root=args.output_root.resolve(),
        seed=args.seed,
        population_per_stratum=args.population_per_stratum,
        generations=args.generations,
        fold_count=args.fold_count,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "semantic_hash": report["semantic_hash"],
                "run_unique_evaluations": report["search_protocol"]["run_unique_evaluations"],
                "output_root": args.output_root.resolve().as_posix(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
