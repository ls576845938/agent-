#!/usr/bin/env python3
"""Run BTC range-reclaim momentum lifecycle-aware hypothesis research."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_range_reclaim_lifecycle import (
    BTC_RANGE_RECLAIM_CONFIG_PATH,
    BTC_RANGE_RECLAIM_OUTPUT_ROOT,
    BTC_RANGE_RECLAIM_RUN_ID,
    run_range_reclaim_lifecycle_research,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(BTC_RANGE_RECLAIM_CONFIG_PATH))
    parser.add_argument("--run-id", default=BTC_RANGE_RECLAIM_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_RANGE_RECLAIM_OUTPUT_ROOT))
    args = parser.parse_args()

    run_dir = run_range_reclaim_lifecycle_research(
        config_path=args.config,
        run_id=args.run_id,
        output_root=Path(args.output_root),
    )
    print(run_dir / "range_reclaim_lifecycle_report.json")


if __name__ == "__main__":
    main()
