#!/usr/bin/env python3
"""Build BTC SQLite, fold, and regime diagnostics status report."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_compression_expansion_diagnostics import (
    BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT,
    BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
    build_data_fold_regime_status_report,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT))
    parser.add_argument("--db-path", default="data/market_data.sqlite")
    parser.add_argument("--manifest-root", default="data/manifests")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    report = build_data_fold_regime_status_report(
        run_dir=run_dir,
        db_path=args.db_path,
        manifest_root=Path(args.manifest_root),
    )
    print(run_dir / "btc_data_fold_regime_status_report.json")
    print(report["sqlite"]["status"], report["manifest_lineage"]["status"])


if __name__ == "__main__":
    main()
