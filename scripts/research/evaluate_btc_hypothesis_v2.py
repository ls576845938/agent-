#!/usr/bin/env python3
"""Run BTC Hypothesis Lab v2 lifecycle-aware evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_hypothesis_lab_v2 import (
    BTC_HYPOTHESIS_LAB_V2_ROOT,
    BTC_HYPOTHESIS_LAB_V2_RUN_ID,
    run_hypothesis_lab_v2,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_HYPOTHESIS_LAB_V2_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_HYPOTHESIS_LAB_V2_ROOT))
    args = parser.parse_args()

    run_dir = run_hypothesis_lab_v2(run_id=args.run_id, output_root=Path(args.output_root))
    print(run_dir / "lifecycle_aware_distribution_report.json")


if __name__ == "__main__":
    main()
