#!/usr/bin/env python3
"""Run the BTC Event-PF/WF stabilization sprint artifact build."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from quant_us.research.btc_eventpf_wf import (
        BTC_EVENTPF_WF_RUN_ID,
        BTC_EVENTPF_WF_SOURCE_RUN_DIR,
        run_stabilization_sprint,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from quant_us.research.btc_eventpf_wf import (
        BTC_EVENTPF_WF_RUN_ID,
        BTC_EVENTPF_WF_SOURCE_RUN_DIR,
        run_stabilization_sprint,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTPF_WF_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    parser.add_argument("--source-run-dir", default=str(BTC_EVENTPF_WF_SOURCE_RUN_DIR))
    args = parser.parse_args()

    run_dir = run_stabilization_sprint(
        run_id=args.run_id,
        output_root=Path(args.output_root),
        source_run_dir=Path(args.source_run_dir),
    )
    print(run_dir)


if __name__ == "__main__":
    main()
