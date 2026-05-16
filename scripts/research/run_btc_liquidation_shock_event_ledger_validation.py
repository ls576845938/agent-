#!/usr/bin/env python3
"""Run event-ledger candidate validation for BTC liquidation-shock recovery."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_liquidation_shock_validation import (
    BTC_LIQUIDATION_SHOCK_VALIDATION_ROOT,
    BTC_LIQUIDATION_SHOCK_VALIDATION_RUN_ID,
    DEFAULT_VALIDATION_CONFIG_PATH,
    run_liquidation_shock_event_ledger_validation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_VALIDATION_CONFIG_PATH))
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_VALIDATION_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_LIQUIDATION_SHOCK_VALIDATION_ROOT))
    args = parser.parse_args()

    run_dir = run_liquidation_shock_event_ledger_validation(
        run_id=args.run_id,
        config_path=args.config,
        output_root=Path(args.output_root),
    )
    print(run_dir)


if __name__ == "__main__":
    main()
