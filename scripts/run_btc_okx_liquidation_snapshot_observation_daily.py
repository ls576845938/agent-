#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_okx_liquidation_snapshot_observer import (  # noqa: E402
    DEFAULT_DATA_PATH,
    DEFAULT_OUTPUT_DIR,
    run_btc_okx_liquidation_snapshot_observer,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one BTC OKX public liquidation snapshot observe-only pass.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = run_btc_okx_liquidation_snapshot_observer(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        data_path=args.data_path,
        execute_network=bool(args.execute_network),
        limit=args.limit,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "new_row_count": report["data"]["new_row_count"],
                "merged_row_count": report["data"]["merged_row_count"],
                "gate_eligible": report["gate_interpretation"]["liquidation_snapshot_gate_eligible"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
