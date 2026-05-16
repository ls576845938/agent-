#!/usr/bin/env python3
"""Audit BTC terminal exposure metric policies."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_eventreturn_alpha import (
    BTC_EVENTRETURN_RUN_ID,
    BTC_EVENTRETURN_SOURCE_RUN_DIR,
    build_terminal_exposure_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTRETURN_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    parser.add_argument("--source-run-dir", default=str(BTC_EVENTRETURN_SOURCE_RUN_DIR))
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    build_terminal_exposure_audit(source_run_dir=Path(args.source_run_dir), run_dir=run_dir)
    print(run_dir / "terminal_exposure_audit.json")


if __name__ == "__main__":
    main()
