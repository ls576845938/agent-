from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_paper_risk_circuit_breaker_drill import (  # noqa: E402
    DEFAULT_KILL_SWITCH_REPORT_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PREFLIGHT_REPORT_PATH,
    DEFAULT_PREFLIGHT_ROWS_PATH,
    build_btc_paper_risk_circuit_breaker_drill,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC paper risk circuit-breaker fault-injection drill.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--preflight-rows", type=Path, default=DEFAULT_PREFLIGHT_ROWS_PATH)
    parser.add_argument("--preflight-report", type=Path, default=DEFAULT_PREFLIGHT_REPORT_PATH)
    parser.add_argument("--kill-switch-report", type=Path, default=DEFAULT_KILL_SWITCH_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_paper_risk_circuit_breaker_drill(
        output_dir=args.output_dir,
        preflight_rows_path=args.preflight_rows,
        preflight_report_path=args.preflight_report,
        kill_switch_report_path=args.kill_switch_report,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "scenario_count": summary.get("scenario_count"),
                "order_sample_count": summary.get("order_sample_count"),
                "scenario_order_check_count": summary.get("scenario_order_check_count"),
                "unexpected_allow_count": summary.get("unexpected_allow_count"),
                "diagnostic_drill_only": summary.get("diagnostic_drill_only"),
                "blocker_count": summary.get("blocker_count"),
                "paper_order_intake_allowed": report["gate"]["paper_order_intake_allowed"],
                "position_increase_allowed": report["gate"]["position_increase_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"].startswith("incomplete") else 0


if __name__ == "__main__":
    raise SystemExit(main())
