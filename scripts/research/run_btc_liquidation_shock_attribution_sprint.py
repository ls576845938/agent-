#!/usr/bin/env python3
"""Run the BTC liquidation-shock event-return attribution sprint."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_liquidation_shock_attribution import (
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT,
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID,
    SOURCE_VALIDATION_RUN_DIR,
    run_liquidation_shock_attribution_sprint,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT))
    parser.add_argument("--source-run-dir", default=str(SOURCE_VALIDATION_RUN_DIR))
    args = parser.parse_args()

    run_dir = run_liquidation_shock_attribution_sprint(
        run_id=args.run_id,
        output_root=Path(args.output_root),
        source_run_dir=Path(args.source_run_dir),
    )
    print(run_dir)


if __name__ == "__main__":
    main()
