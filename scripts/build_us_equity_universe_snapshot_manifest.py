#!/usr/bin/env python3
"""Build the explicit US equity universe snapshot lineage artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_us_equity_data_status_report import (  # noqa: E402
    LINEAGE_OUTPUT_ROOT,
    build_us_equity_data_status,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(LINEAGE_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_us_equity_data_status(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )["universe_snapshot_manifest"]
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "universe_snapshot_manifest.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
