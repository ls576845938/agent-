#!/usr/bin/env python3
"""CLI entrypoint for the US equity manual decision-record report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.live.manual_decision_record_report import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_RECORD,
    DEFAULT_TEMPLATE,
    build_us_equity_manual_decision_record_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a US equity manual decision record.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--record-path", default=str(DEFAULT_RECORD))
    parser.add_argument("--template-path", default=str(DEFAULT_TEMPLATE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_manual_decision_record_report(
        repo_root=Path(args.repo_root),
        record_path=Path(args.record_path),
        template_path=Path(args.template_path),
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
