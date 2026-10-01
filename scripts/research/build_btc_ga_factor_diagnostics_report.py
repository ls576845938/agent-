#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.ga_factor_mining import (
    DEFAULT_GA_FACTOR_DIAGNOSTICS_REPORT,
    DEFAULT_GA_FACTOR_MINING_REPORT,
    write_btc_ga_factor_diagnostics_report,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report-path", type=Path, default=DEFAULT_GA_FACTOR_MINING_REPORT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_GA_FACTOR_DIAGNOSTICS_REPORT)
    args = parser.parse_args()

    report = write_btc_ga_factor_diagnostics_report(
        source_report_path=args.source_report_path,
        output_path=args.output_path,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "current_ga_batch_decision": report["gate"]["current_ga_batch_decision"],
                "failure_reasons": report["diagnostic_summary"]["failure_reasons"],
                "blockers": report["blockers"],
                "output_path": str(args.output_path).replace("\\", "/"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
