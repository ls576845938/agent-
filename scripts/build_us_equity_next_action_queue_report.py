#!/usr/bin/env python3
"""Build an ordered next-action queue from the US equity completion dashboard.

This CLI is an entrypoint only. Queue rules live in
``quant_us.monitoring.next_action_queue``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.monitoring.next_action_queue import (  # noqa: E402
    DEFAULT_COMPLETION_DEPENDENCY,
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_PIT_FILE_DISCOVERY,
    DEFAULT_VENDOR_DROP_PREFLIGHT,
    build_us_equity_next_action_queue_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--completion-dependency", type=Path, default=DEFAULT_COMPLETION_DEPENDENCY)
    parser.add_argument("--vendor-drop-preflight", type=Path, default=DEFAULT_VENDOR_DROP_PREFLIGHT)
    parser.add_argument("--pit-file-discovery", type=Path, default=DEFAULT_PIT_FILE_DISCOVERY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_us_equity_next_action_queue_report(
        repo_root=args.repo_root,
        completion_dependency=args.completion_dependency,
        vendor_drop_preflight=args.vendor_drop_preflight,
        pit_file_discovery=args.pit_file_discovery,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
