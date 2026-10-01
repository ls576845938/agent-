from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_attack_strategy_continuation_shortlist import (  # noqa: E402
    DEFAULT_BANKROLL_REVIEW_PATH,
    DEFAULT_HIGH_OCTANE_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PYRAMIDING_PATH,
    DEFAULT_RISK_STRESS_PATH,
    build_btc_attack_strategy_continuation_shortlist,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC aggressive strategy continuation shortlist.")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bankroll-review", type=Path, default=DEFAULT_BANKROLL_REVIEW_PATH)
    parser.add_argument("--high-octane", type=Path, default=DEFAULT_HIGH_OCTANE_PATH)
    parser.add_argument("--pyramiding", type=Path, default=DEFAULT_PYRAMIDING_PATH)
    parser.add_argument("--risk-stress", type=Path, default=DEFAULT_RISK_STRESS_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_attack_strategy_continuation_shortlist(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        bankroll_review_path=args.bankroll_review,
        high_octane_path=args.high_octane,
        pyramiding_path=args.pyramiding,
        risk_stress_path=args.risk_stress,
    )
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "decision": report.get("decision"),
                "line_count": report.get("line_count"),
                "continued_research_strategy_count": report.get("continued_research_strategy_count"),
                "danger_reference_count": report.get("danger_reference_count"),
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
