#!/usr/bin/env python3
"""Audit BTC compression-expansion fold and regime evidence contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_compression_expansion_diagnostics import (
    BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT,
    BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
    SOURCE_HYPOTHESIS_RUN_DIR,
    audit_fold_regime_contracts,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT))
    parser.add_argument("--hypothesis-run-dir", default=str(SOURCE_HYPOTHESIS_RUN_DIR))
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    report = audit_fold_regime_contracts(run_dir=run_dir, hypothesis_run_dir=Path(args.hypothesis_run_dir))
    print(run_dir / "fold_regime_contract_audit.json")
    print(report["fold_contract"]["status"], report["regime_contract"]["status"])


if __name__ == "__main__":
    main()
