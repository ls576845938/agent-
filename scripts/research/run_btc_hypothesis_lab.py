#!/usr/bin/env python3
"""Run a config-driven BTC hypothesis lab research job."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_hypothesis_lab import (
    BTC_HYPOTHESIS_LAB_RUN_ID,
    DEFAULT_CONFIG_PATH,
    run_hypothesis_lab,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--run-id", default=BTC_HYPOTHESIS_LAB_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_hypothesis")
    args = parser.parse_args()

    run_dir = run_hypothesis_lab(config_path=args.config, run_id=args.run_id, output_root=Path(args.output_root))
    print(run_dir)


if __name__ == "__main__":
    main()
