#!/usr/bin/env python3
"""Build the durable, fail-closed US PIT/DataReady consumer report."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.pit_dataready_consumer import (  # noqa: E402
    build_pit_dataready_consumption_report,
)


DEFAULT_CONFIG = Path("configs/data/us_equity_pit_dataready_consumer_v1.json")
DEFAULT_OUTPUT = Path(
    "docs/handoffs/US-V3-PIT-DATAREADY-CONSUMER-01/"
    "us_equity_pit_dataready_consumption_report.json"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a read-only US ETF26/production-PIT consumption report."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--production-bundle-root", default="")
    parser.add_argument("--pit-lite-proof", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    config = _read_json(_resolve(root, args.config))
    proof = _read_json(_resolve(root, args.pit_lite_proof)) if args.pit_lite_proof else None
    bundle_root = (
        _resolve(root, args.production_bundle_root)
        if args.production_bundle_root
        else None
    )
    report = build_pit_dataready_consumption_report(
        repo_root=root,
        config=config,
        production_bundle_root=bundle_root,
        pit_lite_proof=proof,
        generated_at=args.generated_at or None,
    )
    output = _resolve(root, args.output)
    _atomic_write(
        output,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "artifact_identity_sha256": report["artifact_identity_sha256"],
                "blockers": report["blockers"],
                "output": _display_path(output, root),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return "<external-production-bundle>"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    main()
