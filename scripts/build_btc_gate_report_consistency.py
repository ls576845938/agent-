from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.monitoring.btc_gate_report_consistency import (  # noqa: E402
    build_btc_gate_report_consistency,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC gate report consistency artifact.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kwargs = {
        "repo_root": args.repo_root,
        "aggregation_batch_id": args.aggregation_batch_id or None,
    }
    if args.output_dir is not None:
        kwargs["output_dir"] = args.output_dir
    report = build_btc_gate_report_consistency(**kwargs)
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "summary": report["summary"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
