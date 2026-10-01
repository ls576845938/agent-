from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_paper_exchange_rule_preflight import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_ACCOUNT_RUNTIME_ATTESTATION_REPORT_PATH,
    DEFAULT_CURRENT_REPLAY_REPORT_PATH,
    DEFAULT_CURRENT_ROWS_PATH,
    DEFAULT_DRILL_REPORT_PATH,
    DEFAULT_DRILL_ROWS_PATH,
    DEFAULT_KILL_SWITCH_REPORT_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SERVER_TIME_PREFLIGHT_REPORT_PATH,
    build_btc_paper_exchange_rule_preflight,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC paper runtime exchange-rule preflight report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--exchange-info", type=Path, default=None)
    parser.add_argument("--current-rows", type=Path, default=DEFAULT_CURRENT_ROWS_PATH)
    parser.add_argument("--drill-rows", type=Path, default=DEFAULT_DRILL_ROWS_PATH)
    parser.add_argument("--current-replay-report", type=Path, default=DEFAULT_CURRENT_REPLAY_REPORT_PATH)
    parser.add_argument("--drill-report", type=Path, default=DEFAULT_DRILL_REPORT_PATH)
    parser.add_argument("--kill-switch-report", type=Path, default=DEFAULT_KILL_SWITCH_REPORT_PATH)
    parser.add_argument("--server-time-preflight-report", type=Path, default=DEFAULT_SERVER_TIME_PREFLIGHT_REPORT_PATH)
    parser.add_argument("--account-runtime-attestation-report", type=Path, default=DEFAULT_ACCOUNT_RUNTIME_ATTESTATION_REPORT_PATH)
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_paper_exchange_rule_preflight(
        output_dir=args.output_dir,
        config_path=args.config,
        exchange_info_path=args.exchange_info,
        current_rows_path=args.current_rows,
        drill_rows_path=args.drill_rows,
        current_replay_report_path=args.current_replay_report,
        drill_report_path=args.drill_report,
        kill_switch_report_path=args.kill_switch_report,
        server_time_preflight_report_path=args.server_time_preflight_report,
        account_runtime_attestation_report_path=args.account_runtime_attestation_report,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "current_order_count": summary.get("current_order_count"),
                "drill_order_count": summary.get("drill_order_count"),
                "order_filter_violation_count": summary.get("order_filter_violation_count"),
                "quantity_lot_violation_count": summary.get("quantity_lot_violation_count"),
                "kill_switch_reject_count": summary.get("kill_switch_reject_count"),
                "blocker_count": summary.get("blocker_count"),
                "paper_order_intake_allowed": report["gate"]["paper_order_intake_allowed"],
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
