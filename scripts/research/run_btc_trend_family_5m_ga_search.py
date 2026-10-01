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

from quant_crypto.research.trend_family_5m_ga_search import (
    DEFAULT_SEED,
    run_btc_trend_family_5m_ga_search,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline selection-only BTC 5m typed trend-family GA."
    )
    parser.add_argument("--selection-prefix-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--population-per-family", type=int, default=24)
    parser.add_argument("--generations", type=int, default=6)
    parser.add_argument("--fold-count", type=int, default=4)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated = (
        datetime.fromisoformat(args.generated_at.replace("Z", "+00:00"))
        if args.generated_at
        else None
    )
    report = run_btc_trend_family_5m_ga_search(
        selection_prefix_manifest=args.selection_prefix_manifest,
        output_root=args.output_root,
        seed=args.seed,
        population_per_family=args.population_per_family,
        generations=args.generations,
        fold_count=args.fold_count,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "artifact_hash": report["artifact_hash"],
                "output_root": args.output_root.as_posix(),
                "unseen_bytes_read": 0,
                "unseen_rows_decoded": 0,
                "promotion": False,
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
