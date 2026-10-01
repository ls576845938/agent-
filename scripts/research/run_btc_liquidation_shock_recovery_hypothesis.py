#!/usr/bin/env python3
"""Run BTC liquidation-shock recovery hypothesis research."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_liquidation_shock_recovery import (
    BTC_LIQUIDATION_SHOCK_OUTPUT_ROOT,
    BTC_LIQUIDATION_SHOCK_RUN_ID,
    DEFAULT_CONFIG_PATH,
    run_liquidation_shock_research,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_LIQUIDATION_SHOCK_OUTPUT_ROOT))
    args = parser.parse_args()

    run_dir = run_liquidation_shock_research(
        config_path=args.config,
        run_id=args.run_id,
        output_root=Path(args.output_root),
    )
    print(run_dir)


if __name__ == "__main__":
    main()
