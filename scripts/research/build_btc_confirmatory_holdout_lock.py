from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_confirmatory_holdout_lock import (  # noqa: E402
    DEFAULT_BAR_REPLAY_REPORT_PATH,
    DEFAULT_HIGH_OCTANE_REPORT_PATH,
    DEFAULT_LOCK_CONFIG_PATH,
    DEFAULT_LONG_SHORT_TOP5_REPORT_PATH,
    DEFAULT_OUTPUT_DIR,
    build_btc_confirmatory_holdout_lock,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC confirmatory holdout lock manifest.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lock-config", type=Path, default=DEFAULT_LOCK_CONFIG_PATH)
    parser.add_argument("--long-short-top5-report", type=Path, default=DEFAULT_LONG_SHORT_TOP5_REPORT_PATH)
    parser.add_argument("--high-octane-report", type=Path, default=DEFAULT_HIGH_OCTANE_REPORT_PATH)
    parser.add_argument("--bar-replay-report", type=Path, default=DEFAULT_BAR_REPLAY_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_confirmatory_holdout_lock(
        output_dir=args.output_dir,
        lock_config_path=args.lock_config,
        long_short_top5_report_path=args.long_short_top5_report,
        high_octane_report_path=args.high_octane_report,
        bar_replay_report_path=args.bar_replay_report,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "lock_count": summary.get("lock_count"),
                "historical_seen_lock_count": summary.get("historical_seen_lock_count"),
                "future_observe_only_lock_count": summary.get("future_observe_only_lock_count"),
                "latest_common_history_end": summary.get("latest_common_history_end"),
                "self_check_violation_count": summary.get("self_check_violation_count"),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
