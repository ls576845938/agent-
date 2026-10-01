#!/usr/bin/env python3
"""Build the research-only BTC intraday repaired event-ledger report."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from quant_us.research.btc_intraday_short_cycle_event_ledger import (
        BTC_INTRADAY_EVENT_LEDGER_LATEST,
        BTC_INTRADAY_EVENT_LEDGER_ROOT,
        BTC_INTRADAY_REPAIRED_EVENT_LEDGER_RUN_ID,
        run_btc_intraday_short_cycle_repaired_event_ledger,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_us.research.btc_intraday_short_cycle_event_ledger import (
        BTC_INTRADAY_EVENT_LEDGER_LATEST,
        BTC_INTRADAY_EVENT_LEDGER_ROOT,
        BTC_INTRADAY_REPAIRED_EVENT_LEDGER_RUN_ID,
        run_btc_intraday_short_cycle_repaired_event_ledger,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--run-id", default=BTC_INTRADAY_REPAIRED_EVENT_LEDGER_RUN_ID)
    parser.add_argument("--output-root", default=str(BTC_INTRADAY_EVENT_LEDGER_ROOT))
    parser.add_argument("--latest-root", default=str(BTC_INTRADAY_EVENT_LEDGER_LATEST))
    args = parser.parse_args()
    run_dir = run_btc_intraday_short_cycle_repaired_event_ledger(
        run_id=args.run_id,
        output_root=Path(args.output_root),
        latest_root=Path(args.latest_root),
        repo_root=Path(args.repo_root),
    )
    print(run_dir / "btc_intraday_short_cycle_repaired_event_ledger_report.json")


if __name__ == "__main__":
    main()
