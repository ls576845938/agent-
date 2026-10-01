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

from quant_crypto.research.btc_exchange_paper_runtime_replay import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PAPER_EVALUATION,
    DEFAULT_PAPER_REPLAY,
    DEFAULT_PAPER_RUNTIME,
    DEFAULT_PAPER_START,
    DEFAULT_ROUTE_REQUEST,
    build_btc_exchange_paper_runtime_replay_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build BTC exchange paper runtime replay applicability report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--route-request", type=Path, default=DEFAULT_ROUTE_REQUEST)
    parser.add_argument("--paper-start", type=Path, default=DEFAULT_PAPER_START)
    parser.add_argument("--paper-runtime", type=Path, default=DEFAULT_PAPER_RUNTIME)
    parser.add_argument("--paper-evaluation", type=Path, default=DEFAULT_PAPER_EVALUATION)
    parser.add_argument("--paper-replay", type=Path, default=DEFAULT_PAPER_REPLAY)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated = _parse_utc(args.generated_at) if args.generated_at else None
    report = build_btc_exchange_paper_runtime_replay_report(
        output_dir=args.output_dir,
        route_request_path=args.route_request,
        paper_start_path=args.paper_start,
        paper_runtime_path=args.paper_runtime,
        paper_evaluation_path=args.paper_evaluation,
        paper_replay_path=args.paper_replay,
        generated_at_utc=generated,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "legacy_ready": report["legacy_paper_runtime"]["ready"],
                "current_perpetual_ready": report["current_route_applicability"][
                    "current_perpetual_paper_runtime_replay_ready"
                ],
                "blockers": report["blockers"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
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
