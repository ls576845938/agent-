from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_operator_root_cause_view import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_btc_operator_root_cause_view,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only BTC operator root-cause view.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_operator_root_cause_view(repo_root=args.repo_root, output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "decision": report.get("decision"),
                "current_stage": report.get("current_stage"),
                "unique_next_action": report.get("unique_next_action"),
                "blockers": report.get("blockers", []),
                "outputs": report.get("outputs", {}),
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
                "broker_or_order_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
