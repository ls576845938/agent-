#!/usr/bin/env python3
"""Analyze BTC low-vol uptrend event-return distribution."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_low_vol_uptrend import BTC_LOW_VOL_UPTREND_RUN_ID, analyze_low_vol_uptrend_distribution


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LOW_VOL_UPTREND_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_hypothesis")
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    analyze_low_vol_uptrend_distribution(run_dir=run_dir)
    print(run_dir / "low_vol_uptrend_distribution_report.json")


if __name__ == "__main__":
    main()
