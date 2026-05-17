#!/usr/bin/env python3
"""Build fold-3 autopsy for BTC liquidation-shock event-ledger validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_liquidation_shock_attribution import (
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT,
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID,
    build_fold3_autopsy,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT))
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    build_fold3_autopsy(run_dir=run_dir)
    print(run_dir / "liquidation_shock_fold3_autopsy.json")


if __name__ == "__main__":
    main()
