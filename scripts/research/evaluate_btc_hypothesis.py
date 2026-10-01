#!/usr/bin/env python3
"""Evaluate a BTC hypothesis lab distribution report."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_us.research.btc_hypothesis_lab import (
    BTC_HYPOTHESIS_LAB_RUN_ID,
    DEFAULT_CONFIG_PATH,
    evaluate_hypothesis,
    load_hypothesis_config,
    read_json,
    write_safety_status,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--run-id", default=BTC_HYPOTHESIS_LAB_RUN_ID)
    parser.add_argument("--output-root", default="artifacts/btc_hypothesis")
    args = parser.parse_args()

    config = load_hypothesis_config(args.config)
    run_dir = Path(args.output_root) / args.run_id
    decision = evaluate_hypothesis(
        run_dir=run_dir,
        config=config,
        distribution_report=read_json(run_dir / "distribution_report.json"),
    )
    write_safety_status(run_dir=run_dir, config=config, decision=decision)
    print(run_dir / "hypothesis_decision.json")


if __name__ == "__main__":
    main()
