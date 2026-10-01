#!/usr/bin/env python3
"""Prepare the empty US equity vendor-drop workspace without writing vendor data."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_us_equity_local_csv_production_bundle import DEFAULT_SOURCE_DIR


SCHEMA_VERSION = "us_equity_vendor_drop_workspace_preparation_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_workspace_preparation_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Vendor Drop Workspace 准备.md")


def prepare_us_equity_vendor_drop_workspace(
    *,
    repo_root: Path | None = None,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    source = _resolve(root, source_dir)
    source.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "vendor_drop_workspace_prepared",
        "source_dir": _relpath(source, root),
        "source_dir_exists": source.is_dir(),
        "vendor_file_count": len([path for path in source.iterdir() if path.is_file()]) if source.is_dir() else 0,
        "blockers": [] if source.is_dir() else ["source_dir_not_created"],
        "operator_next_actions": [
            "Copy the licensed PIT CSV files listed in us_equity_vendor_drop_preflight_report.required_files into source_dir.",
            "Run: python scripts/build_us_equity_vendor_drop_preflight_report.py",
            "Only after preflight is ready, run incoming readiness and import.",
        ],
        "guardrails": {
            "workspace_preparation_only": True,
            "contains_vendor_data": False,
            "source_vendor_data_modified": False,
            "production_bundle_written": False,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# US Equity Vendor Drop Workspace 准备",
            "",
            f"生成时间：`{payload.get('generated_at', '')}`",
            f"状态：`{payload.get('status', '')}`",
            f"source_dir：`{payload.get('source_dir', '')}`",
            f"vendor_file_count：`{payload.get('vendor_file_count')}`",
            "",
            "## Guardrails",
            "",
            "- workspace_preparation_only=true",
            "- contains_vendor_data=false",
            "- live_order_allowed=false",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = prepare_us_equity_vendor_drop_workspace(
        repo_root=args.repo_root,
        source_dir=args.source_dir,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
