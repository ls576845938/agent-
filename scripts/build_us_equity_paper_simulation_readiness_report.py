#!/usr/bin/env python3
"""CLI entrypoint for the US equity paper-simulation readiness report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.live.paper_simulation_readiness_report import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_PIT_BUNDLE_ACCEPTANCE,
    DEFAULT_PRODUCTION_PIT_INTAKE_STATUS,
    build_us_equity_paper_simulation_readiness_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--production-pit-intake-status", default=str(DEFAULT_PRODUCTION_PIT_INTAKE_STATUS))
    parser.add_argument("--pit-bundle-acceptance", default=str(DEFAULT_PIT_BUNDLE_ACCEPTANCE))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_paper_simulation_readiness_report(
        repo_root=Path(args.repo_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        production_pit_intake_status=Path(args.production_pit_intake_status),
        pit_bundle_acceptance=Path(args.pit_bundle_acceptance),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
