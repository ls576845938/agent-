from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_attack_followup_review import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_HIGH_OCTANE_REPORT_PATH,
    DEFAULT_HIGH_OCTANE_ROLLING_PATH,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PYRAMIDING_REPORT_PATH,
    DEFAULT_RISK_STRESS_MATRIX_PATH,
    DEFAULT_RISK_STRESS_REPORT_PATH,
    build_btc_attack_followup_review,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC High-Octane strict follow-up and 5x/10x comparison review.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--high-octane-report", type=Path, default=DEFAULT_HIGH_OCTANE_REPORT_PATH)
    parser.add_argument("--high-octane-rolling", type=Path, default=DEFAULT_HIGH_OCTANE_ROLLING_PATH)
    parser.add_argument("--risk-stress-matrix", type=Path, default=DEFAULT_RISK_STRESS_MATRIX_PATH)
    parser.add_argument("--risk-stress-report", type=Path, default=DEFAULT_RISK_STRESS_REPORT_PATH)
    parser.add_argument("--pyramiding-report", type=Path, default=DEFAULT_PYRAMIDING_REPORT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_attack_followup_review(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        high_octane_report_path=args.high_octane_report,
        high_octane_rolling_path=args.high_octane_rolling,
        risk_stress_matrix_path=args.risk_stress_matrix,
        risk_stress_report_path=args.risk_stress_report,
        pyramiding_report_path=args.pyramiding_report,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "decision": report.get("decision"),
                "summary": report.get("summary"),
                "paper_queue_write_allowed": report.get("gate", {}).get("paper_queue_write_allowed"),
                "live_unlock_allowed": report.get("gate", {}).get("live_unlock_allowed"),
                "blockers": report.get("blockers", []),
                "outputs": report.get("outputs", {}),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
