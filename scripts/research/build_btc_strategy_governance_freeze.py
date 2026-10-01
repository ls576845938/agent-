#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_strategy_governance_freeze import (  # noqa: E402
    DEFAULT_LEAKAGE_OVERFIT_AUDIT_REPORT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_STRATEGY_LEDGER_REPORT,
    build_btc_strategy_governance_freeze,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC strategy governance freeze report.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--strategy-ledger-report", type=Path, default=DEFAULT_STRATEGY_LEDGER_REPORT)
    parser.add_argument("--leakage-overfit-audit-report", type=Path, default=DEFAULT_LEAKAGE_OVERFIT_AUDIT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_strategy_governance_freeze(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        strategy_ledger_report_path=args.strategy_ledger_report,
        leakage_overfit_audit_report_path=args.leakage_overfit_audit_report,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "promotion_status": report["promotion_status"],
                "new_strategy_mining_allowed": report["strategy_ledger_freeze"]["new_strategy_mining_allowed"],
                "parameter_mutation_allowed": report["strategy_ledger_freeze"]["parameter_mutation_allowed"],
                "champion": report["champion_challenger"]["champion"],
                "high_octane_verdict": report["post_selection_usage_limits"]["high_octane"]["verdict"],
                "promotion_blockers": report["promotion_blockers"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
