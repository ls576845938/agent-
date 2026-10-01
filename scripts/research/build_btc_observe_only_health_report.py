from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_observe_only_health_report import (  # noqa: E402
    DEFAULT_ATTACK_REPORT,
    DEFAULT_ATTACK_ROWS,
    DEFAULT_HIGH_YIELD_REPORT,
    DEFAULT_HIGH_YIELD_ROWS,
    DEFAULT_LONG_SHORT_REPORT,
    DEFAULT_LONG_SHORT_ROWS,
    DEFAULT_OUTPUT_DIR,
    build_btc_observe_only_health_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC observe-only 30/60 day continuity and safety health report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--long-short-report", type=Path, default=DEFAULT_LONG_SHORT_REPORT)
    parser.add_argument("--long-short-rows", type=Path, default=DEFAULT_LONG_SHORT_ROWS)
    parser.add_argument("--attack-report", type=Path, default=DEFAULT_ATTACK_REPORT)
    parser.add_argument("--attack-rows", type=Path, default=DEFAULT_ATTACK_ROWS)
    parser.add_argument("--high-yield-report", type=Path, default=DEFAULT_HIGH_YIELD_REPORT)
    parser.add_argument("--high-yield-rows", type=Path, default=DEFAULT_HIGH_YIELD_ROWS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_observe_only_health_report(
        output_dir=args.output_dir,
        long_short_report_path=args.long_short_report,
        long_short_rows_path=args.long_short_rows,
        attack_report_path=args.attack_report,
        attack_rows_path=args.attack_rows,
        high_yield_report_path=args.high_yield_report,
        high_yield_rows_path=args.high_yield_rows,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "line_count": summary.get("line_count"),
                "minimum_30d_complete_count": summary.get("minimum_30d_complete_count"),
                "target_60d_complete_count": summary.get("target_60d_complete_count"),
                "continuity_passed_count": summary.get("continuity_passed_count"),
                "safety_violation_count": summary.get("safety_violation_count"),
                "blocker_count": summary.get("blocker_count"),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"].startswith("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
