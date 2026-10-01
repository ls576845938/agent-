#!/usr/bin/env python3
"""Build BTC event-return attribution from canonical event-ledger snapshots."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_eventreturn_alpha import (
    BTC_EVENTRETURN_RUN_ID,
    BTC_EVENTRETURN_SOURCE_RUN_DIR,
    build_event_return_attribution,
    load_btc_1h_frame,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTRETURN_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    parser.add_argument("--source-run-dir", default=str(BTC_EVENTRETURN_SOURCE_RUN_DIR))
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    build_event_return_attribution(source_run_dir=Path(args.source_run_dir), run_dir=run_dir, frame=frame)
    print(run_dir / "event_return_attribution.json")


if __name__ == "__main__":
    main()
