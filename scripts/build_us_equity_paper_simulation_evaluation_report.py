#!/usr/bin/env python3
"""Build US equity paper-simulation evaluation report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.live.paper_simulation_evaluation import (  # noqa: E402
    DEFAULT_LEDGER_ROOT,
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_ROLL_REPORT,
    build_us_equity_paper_simulation_evaluation_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity paper simulation evaluation report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--roll-report", default=str(DEFAULT_ROLL_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_paper_simulation_evaluation_report(
        repo_root=Path(args.repo_root),
        ledger_root=Path(args.ledger_root),
        roll_report=Path(args.roll_report),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
