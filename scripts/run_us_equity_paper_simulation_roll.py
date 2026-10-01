#!/usr/bin/env python3
"""CLI entrypoint for one broker-free US equity paper-simulation roll."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.live.paper_simulation_roll import DEFAULT_SLIPPAGE_BPS  # noqa: E402
from quant_us.live.paper_simulation_runner import (  # noqa: E402
    DEFAULT_FORWARD_LEDGER_ROOT,
    DEFAULT_LEDGER_ROOT,
    DEFAULT_OUTPUT,
    DEFAULT_READINESS_REPORT,
    run_us_equity_paper_simulation_roll,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--forward-ledger-root", default=str(DEFAULT_FORWARD_LEDGER_ROOT))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--manual-start-approved", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_us_equity_paper_simulation_roll(
        repo_root=Path(args.repo_root),
        readiness_report=Path(args.readiness_report),
        forward_ledger_root=Path(args.forward_ledger_root),
        ledger_root=Path(args.ledger_root),
        output=Path(args.output),
        manual_start_approved=args.manual_start_approved,
        slippage_bps=args.slippage_bps,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
