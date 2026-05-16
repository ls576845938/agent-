#!/usr/bin/env python3
"""Evaluate the BTC low-vol uptrend hypothesis gate."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_low_vol_uptrend import (
    BTC_LOW_VOL_UPTREND_RUN_ID,
    evaluate_low_vol_uptrend_hypothesis,
    read_json,
    write_low_vol_uptrend_safety_status,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LOW_VOL_UPTREND_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_hypothesis")
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    decision = evaluate_low_vol_uptrend_hypothesis(
        run_dir=run_dir,
        distribution_report=read_json(run_dir / "low_vol_uptrend_distribution_report.json"),
    )
    write_low_vol_uptrend_safety_status(run_dir=run_dir, decision=decision)
    print(run_dir / "low_vol_uptrend_hypothesis_decision.json")


if __name__ == "__main__":
    main()
