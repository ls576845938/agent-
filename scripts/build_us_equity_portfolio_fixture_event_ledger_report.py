#!/usr/bin/env python3
"""Build the US equity fixture-only portfolio event ledger report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.portfolio.fixture_event_ledger import (  # noqa: E402
    build_portfolio_fixture_event_ledger_report,
)


DEFAULT_OUTPUT = Path(
    "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json"
)


def write_portfolio_fixture_event_ledger_report(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_portfolio_fixture_event_ledger_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_portfolio_fixture_event_ledger_report(payload, Path(args.output)))


if __name__ == "__main__":
    main()
