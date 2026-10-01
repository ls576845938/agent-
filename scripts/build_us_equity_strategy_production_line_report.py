#!/usr/bin/env python3
"""CLI entrypoint for the US equity strategy production-line report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_us.monitoring.strategy_production_line import (  # noqa: E402
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_REGISTRY,
    STAGE_ORDER,
    build_us_equity_strategy_production_line_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_equity_strategy_production_line_report(
        repo_root=args.repo_root,
        registry_path=args.registry,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
