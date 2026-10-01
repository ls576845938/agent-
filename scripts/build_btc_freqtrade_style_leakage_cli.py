#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_freqtrade_style_leakage_cli import (  # noqa: E402
    DEFAULT_BAR_REPLAY_REPORT_PATH,
    DEFAULT_LEAKAGE_REPORT_PATH,
    DEFAULT_OUTPUT_DIR,
    build_btc_freqtrade_style_leakage_cli,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only BTC Freqtrade-style leakage CLI report.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--external-references-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--leakage-report", type=Path, default=DEFAULT_LEAKAGE_REPORT_PATH)
    parser.add_argument("--bar-replay-report", type=Path, default=DEFAULT_BAR_REPLAY_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_freqtrade_style_leakage_cli(
        repo_root=args.repo_root,
        external_references_root=args.external_references_root,
        output_dir=args.output_dir,
        leakage_report_path=args.leakage_report,
        bar_replay_report_path=args.bar_replay_report,
    )
    summary = report.get("summary", {})
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "check_count": summary.get("check_count"),
                "fail_count": summary.get("fail_count"),
                "warn_count": summary.get("warn_count"),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "broker_or_order_allowed": report["gate"]["broker_or_order_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
