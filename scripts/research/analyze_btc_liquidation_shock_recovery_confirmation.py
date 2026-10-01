#!/usr/bin/env python3
"""Analyze recovery confirmation variants for BTC liquidation-shock recovery."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_liquidation_shock_attribution import (
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT,
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID,
    analyze_recovery_confirmation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT))
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    analyze_recovery_confirmation(run_dir=run_dir)
    print(run_dir / "liquidation_shock_recovery_confirmation_report.json")


if __name__ == "__main__":
    main()
