#!/usr/bin/env python3
"""Build failure-mode attribution for BTC compression-expansion candidate."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_compression_expansion_diagnostics import (
    BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT,
    BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
    analyze_failure_modes,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT))
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    report = analyze_failure_modes(run_dir=run_dir)
    print(run_dir / "compression_expansion_failure_mode_report.json")
    print(report["repairability_assessment"]["conclusion"])


if __name__ == "__main__":
    main()
