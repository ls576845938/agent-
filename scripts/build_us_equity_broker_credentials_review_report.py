#!/usr/bin/env python3
"""CLI entrypoint for the US equity broker credentials review report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_us.live.broker_credentials_review_report import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_REVIEW_INPUT,
    build_us_equity_broker_credentials_review_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--review-input", type=Path, default=DEFAULT_REVIEW_INPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        review_input=args.review_input,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
