#!/usr/bin/env python3
"""Build the BTC low-vol uptrend hypothesis feature/event profile."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_low_vol_uptrend import (
    BTC_LOW_VOL_UPTREND_RUN_ID,
    build_low_vol_uptrend_feature_profile,
    load_btc_1h_frame,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LOW_VOL_UPTREND_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_hypothesis")
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    build_low_vol_uptrend_feature_profile(run_dir=run_dir, frame=frame)
    print(run_dir / "low_vol_uptrend_feature_profile.json")


if __name__ == "__main__":
    main()
