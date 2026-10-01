#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.research.us_etf_26_candidate_freeze import build_candidate_strategy_card


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the frozen research-only 26-ETF candidate card.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default="configs/strategies/us_etf_26_candidate_freeze_v1.json")
    parser.add_argument(
        "--source-report",
        default="artifacts/us_equity_etf_26_complete_return_multitimeframe/latest/us_etf_26_complete_return_multitimeframe_report.json",
    )
    parser.add_argument(
        "--output-root",
        default="artifacts/us_equity_etf_26_candidate_freeze/latest",
    )
    args = parser.parse_args()
    card = build_candidate_strategy_card(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config),
        source_report_path=Path(args.source_report),
        output_root=Path(args.output_root),
    )
    print(
        json.dumps(
            {
                "status": card["status"],
                "decision": card["decision"],
                "candidate_id": card["candidate_id"],
                "code_commit": card["code_commit"],
                "params_hash": card["params_hash"],
                "blockers": card["blockers"],
                "guardrails": card["guardrails"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
