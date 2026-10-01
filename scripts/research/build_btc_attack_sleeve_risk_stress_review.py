from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_attack_sleeve_risk_stress_review import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_HIGH_OCTANE_REPORT_PATH,
    DEFAULT_HIGH_OCTANE_WATCHLIST_PATH,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PYRAMIDING_ACTUAL_ATTACK_PATH,
    build_btc_attack_sleeve_risk_stress_review,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC attack sleeve strict risk stress review.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--high-octane-report", type=Path, default=DEFAULT_HIGH_OCTANE_REPORT_PATH)
    parser.add_argument("--high-octane-watchlist", type=Path, default=DEFAULT_HIGH_OCTANE_WATCHLIST_PATH)
    parser.add_argument("--pyramiding-actual-attack", type=Path, default=DEFAULT_PYRAMIDING_ACTUAL_ATTACK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_attack_sleeve_risk_stress_review(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        high_octane_report_path=args.high_octane_report,
        high_octane_watchlist_path=args.high_octane_watchlist,
        pyramiding_actual_attack_path=args.pyramiding_actual_attack,
        output_dir=args.output_dir,
        top_n=args.top_n,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "decision": report.get("decision"),
                "candidate_count": summary.get("candidate_count"),
                "policy_count": summary.get("policy_count"),
                "matrix_row_count": summary.get("matrix_row_count"),
                "strict_survivor_count": summary.get("strict_survivor_count"),
                "normal_liquidation_row_count": summary.get("normal_liquidation_row_count"),
                "not_forward_observation_ready": summary.get("not_forward_observation_ready"),
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
