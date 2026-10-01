from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.atr_regime_failure_analysis import (  # noqa: E402
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    DEFAULT_OUTPUT_DIR,
    build_btc_atr_regime_failure_analysis,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BTC ATR regime failure analysis research-only report.")
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_DB)
    parser.add_argument("--derivatives-rows", type=Path, default=DEFAULT_DERIVATIVES_ROWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--base-cost-bps", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_btc_atr_regime_failure_analysis(
        market_db_path=args.market_db,
        derivatives_rows_path=args.derivatives_rows,
        output_dir=args.output_dir,
        initial_capital=args.initial_capital,
        base_cost_bps=args.base_cost_bps,
    )
    failure = report["failure_summary"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "atr_baseline": report["atr_baseline"]["candidate_id"],
                "should_be_flat_calendar_segments": failure["should_be_flat_calendar_segments"],
                "should_be_flat_regimes": failure["should_be_flat_regimes"],
                "effective_regimes": failure["effective_regimes"],
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "blockers": report["blockers"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
