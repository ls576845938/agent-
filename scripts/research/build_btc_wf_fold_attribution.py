#!/usr/bin/env python3
"""Build BTC walk-forward fold attribution from the event-ledger path."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_eventpf_wf import (
    BTC_EVENTPF_WF_RUN_ID,
    BTC_V3_PARAMS,
    btc_eventpf_wf_signal,
    build_walk_forward_fold_attribution,
    load_btc_1h_frame,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTPF_WF_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    parser.add_argument("--windows", type=int, default=4)
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    build_walk_forward_fold_attribution(
        frame=frame,
        run_dir=run_dir,
        strategy_id="btc_perp_dual_trend_v3",
        params=BTC_V3_PARAMS,
        signal_builder=btc_eventpf_wf_signal,
        windows=args.windows,
    )
    print(run_dir / "walk_forward_fold_attribution.json")


if __name__ == "__main__":
    main()
