#!/usr/bin/env python3
"""Run BTC compression-expansion skeleton event-ledger validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_compression_expansion_validation import (
    BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
    DEFAULT_VALIDATION_CONFIG_PATH,
    run_compression_expansion_event_ledger_validation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID)
    parser.add_argument("--config", default=str(DEFAULT_VALIDATION_CONFIG_PATH))
    parser.add_argument("--output-root", default="artifacts/btc_candidate_validation")
    args = parser.parse_args()

    run_dir = run_compression_expansion_event_ledger_validation(
        run_id=args.run_id,
        config_path=args.config,
        output_root=Path(args.output_root),
    )
    print(run_dir)


if __name__ == "__main__":
    main()
