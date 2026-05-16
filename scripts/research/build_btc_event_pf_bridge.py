#!/usr/bin/env python3
"""Build the BTC event-PF bridge report from canonical artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_eventpf_wf import (
    BTC_EVENTPF_WF_RUN_ID,
    BTC_EVENTPF_WF_SOURCE_RUN_DIR,
    build_event_pf_bridge_report,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTPF_WF_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    parser.add_argument("--source-run-dir", default=str(BTC_EVENTPF_WF_SOURCE_RUN_DIR))
    parser.add_argument("--strategy-id", default="btc_perp_dual_trend_v3")
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    build_event_pf_bridge_report(
        source_run_dir=Path(args.source_run_dir),
        run_dir=run_dir,
        strategy_id=args.strategy_id,
    )
    print(run_dir / "event_pf_bridge_report.json")


if __name__ == "__main__":
    main()
