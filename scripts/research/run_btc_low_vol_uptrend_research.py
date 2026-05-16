#!/usr/bin/env python3
"""Run the BTC low-vol uptrend hypothesis research sprint."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_low_vol_uptrend import BTC_LOW_VOL_UPTREND_RUN_ID, run_low_vol_uptrend_research


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LOW_VOL_UPTREND_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_hypothesis")
    args = parser.parse_args()

    run_dir = run_low_vol_uptrend_research(run_id=args.run_id, output_root=Path(args.output_root))
    print(run_dir)


if __name__ == "__main__":
    main()
