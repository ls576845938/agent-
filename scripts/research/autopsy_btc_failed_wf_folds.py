#!/usr/bin/env python3
"""Build failed fold autopsy from BTC event-return attribution."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from quant_us.research.btc_eventreturn_alpha import (
    BTC_EVENTRETURN_RUN_ID,
    build_failed_fold_autopsy,
    read_json,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTRETURN_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    table_path = run_dir / "event_return_table.csv"
    terminal_path = run_dir / "terminal_exposure_audit.json"
    if not table_path.exists():
        raise FileNotFoundError(f"missing event-return table: {table_path}")
    if not terminal_path.exists():
        raise FileNotFoundError(f"missing terminal exposure audit: {terminal_path}")
    build_failed_fold_autopsy(
        run_dir=run_dir,
        event_return_table=pd.read_csv(table_path),
        terminal_audit=read_json(terminal_path),
    )
    print(run_dir / "failed_fold_autopsy.json")


if __name__ == "__main__":
    main()
