#!/usr/bin/env python3
"""Build attribution report for BTC compression-expansion event-ledger validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_compression_expansion_validation import (
    BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
    BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT,
    build_event_ledger_attribution,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT))
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    report = build_event_ledger_attribution(run_dir=run_dir)
    print(run_dir / "event_ledger_attribution_report.json")
    print(report["gate_status"], report["gate_fail_reasons"])


if __name__ == "__main__":
    main()
