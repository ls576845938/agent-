#!/usr/bin/env python3
"""Thin CLI for the frozen ETF26 natural-time observation service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.application.us_equity_forward_observation import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    run_current_day_forward_observation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one fail-closed US ETF26 natural-time observation review."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--output-root", default="")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_current_day_forward_observation(
        repo_root=Path(args.repo_root),
        config_path=Path(args.config),
        output_root=Path(args.output_root) if args.output_root else None,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
