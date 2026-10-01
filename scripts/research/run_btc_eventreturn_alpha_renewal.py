#!/usr/bin/env python3
"""Run BTC Event-Return Attribution and Alpha Renewal artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_eventreturn_alpha import (
    BTC_EVENTRETURN_RUN_ID,
    BTC_EVENTRETURN_SOURCE_RUN_DIR,
    run_eventreturn_alpha_renewal,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTRETURN_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    parser.add_argument("--source-run-dir", default=str(BTC_EVENTRETURN_SOURCE_RUN_DIR))
    args = parser.parse_args()

    run_dir = run_eventreturn_alpha_renewal(
        run_id=args.run_id,
        output_root=Path(args.output_root),
        source_run_dir=Path(args.source_run_dir),
    )
    print(run_dir)


if __name__ == "__main__":
    main()
