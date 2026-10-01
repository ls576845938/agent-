#!/usr/bin/env python3
"""Build BTC liquidation-shock event-return attribution artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_liquidation_shock_attribution import (
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT,
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID,
    SOURCE_VALIDATION_RUN_DIR,
    build_event_return_attribution,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT))
    parser.add_argument("--source-run-dir", default=str(SOURCE_VALIDATION_RUN_DIR))
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    build_event_return_attribution(run_dir=run_dir, source_run_dir=Path(args.source_run_dir))
    print(run_dir / "liquidation_shock_event_return_attribution.json")


if __name__ == "__main__":
    main()
