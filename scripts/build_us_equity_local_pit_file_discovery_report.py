#!/usr/bin/env python3
"""Discover local PIT CSV files for the US equity manual vendor drop.

This report is an operator aid only. It never copies files, never imports a
bundle, and never treats test fixtures or templates as production evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES  # noqa: E402
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES  # noqa: E402
from scripts.import_us_equity_local_csv_production_bundle import DEFAULT_SOURCE_DIR  # noqa: E402


SCHEMA_VERSION = "us_equity_local_pit_file_discovery_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_local_pit_file_discovery_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 本地PIT文件发现报告.md")
DEFAULT_SEARCH_ROOTS = [DEFAULT_SOURCE_DIR, Path("D:/Trading")]
ALLOWED_STATUSES = {
    "pit_file_discovery_ready_for_copy",
    "pit_file_discovery_no_complete_candidate_set",
}
EXCLUDED_PATH_PARTS = {
    ".tmp",
    "__pycache__",
    "docs/us_equity_manual_vendor_drop_templates",
    "tests",
}


def build_us_equity_local_pit_file_discovery_report(
    *,
    repo_root: Path | None = None,
    search_roots: list[Path] | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    max_candidates_per_file: int = 20,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    roots = search_roots or DEFAULT_SEARCH_ROOTS
    resolved_roots = [_resolve(root, item) for item in roots]
    files = [_discover_required_file(root, resolved_roots, table, fields, max_candidates_per_file) for table, fields in REQUIRED_LOCAL_CSV_FILES.items()]
    ready_count = sum(1 for item in files if item["ready_for_copy"])
    status = (
        "pit_file_discovery_ready_for_copy"
        if ready_count == len(REQUIRED_LOCAL_CSV_FILES)
        else "pit_file_discovery_no_complete_candidate_set"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": "copy_only_after_manual_license_review" if status == "pit_file_discovery_ready_for_copy" else "acquire_missing_licensed_pit_files",
        "incoming_drop_dir": DEFAULT_SOURCE_DIR.as_posix(),
        "search_roots": [_relpath_or_abs(item, root) for item in resolved_roots],
        "required_file_count": len(REQUIRED_LOCAL_CSV_FILES),
        "ready_for_copy_count": ready_count,
        "missing_filename_count": len(REQUIRED_LOCAL_CSV_FILES) - ready_count,
        "ready_filenames": [item["filename"] for item in files if item["ready_for_copy"]],
        "missing_filenames": [item["filename"] for item in files if not item["ready_for_copy"]],
        "files": files,
        "operator_next_actions": _operator_next_actions(status),
        "guardrails": {
            "discovery_only": True,
            "files_copied": False,
            "vendor_data_imported": False,
            "configuration_mutated_by_this_report": False,
            "license_reviewed_by_this_report": False,
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
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _discover_required_file(
    repo_root: Path,
    search_roots: list[Path],
    table: str,
    fields: Iterable[str],
    max_candidates: int,
) -> dict[str, Any]:
    filename = DEFAULT_FILENAMES[table]
    required_fields = list(fields)
    ready: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in search_root.rglob(filename):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            exclusion = _exclusion_reason(resolved, repo_root)
            profile = _csv_profile(resolved, required_fields)
            row = {
                "path": _relpath_or_abs(resolved, repo_root),
                "row_count": profile["row_count"],
                "header_fields": profile["header_fields"],
                "missing_required_fields": profile["missing_required_fields"],
                "file_size_bytes": profile["file_size_bytes"],
            }
            if exclusion:
                excluded.append({**row, "reason": exclusion})
            elif profile["row_count"] <= 0:
                excluded.append({**row, "reason": "empty_or_template_file"})
            elif profile["missing_required_fields"]:
                excluded.append({**row, "reason": "required_fields_missing"})
            else:
                ready.append(row)
            if len(ready) >= max_candidates and len(excluded) >= max_candidates:
                break
    return {
        "table": table,
        "filename": filename,
        "required_fields": required_fields,
        "ready_for_copy": bool(ready),
        "ready_candidates": ready[:max_candidates],
        "excluded_candidates": excluded[:max_candidates],
        "excluded_candidate_count": len(excluded),
        "target_path": (DEFAULT_SOURCE_DIR / filename).as_posix(),
    }


def _csv_profile(path: Path, required_fields: list[str]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            row_count = sum(1 for _ in reader)
    except (OSError, UnicodeDecodeError, csv.Error):
        header = []
        row_count = 0
    return {
        "header_fields": [str(item) for item in header],
        "row_count": int(row_count),
        "missing_required_fields": [item for item in required_fields if item not in header],
        "file_size_bytes": path.stat().st_size if path.exists() else 0,
    }


def _exclusion_reason(path: Path, repo_root: Path) -> str:
    try:
        rel = path.relative_to(repo_root)
        normalized = rel.as_posix().lower()
    except ValueError:
        rel = None
        normalized = path.as_posix().lower()
    for part in EXCLUDED_PATH_PARTS:
        if part.lower() in normalized:
            return "excluded_non_production_path"
    if "template" in path.name.lower() or "template" in normalized:
        return "excluded_template_path"
    if rel and rel.parts and rel.parts[0] in {"docs", "tests"}:
        return "excluded_repo_docs_or_tests_path"
    return ""


def _operator_next_actions(status: str) -> list[str]:
    if status == "pit_file_discovery_ready_for_copy":
        return [
            "Manually verify provider license scope for each ready candidate.",
            "Copy the six reviewed CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop.",
            "Run python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed.",
        ]
    return [
        "Acquire the missing licensed PIT CSV files from the chosen vendor.",
        "Do not copy files from .tmp, tests, docs, or template directories.",
        "Rerun python scripts/build_us_equity_local_pit_file_discovery_report.py after placing candidate files in a searchable local directory.",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 本地 PIT 文件发现报告",
        "",
        f"- status: `{payload.get('status')}`",
        f"- ready_for_copy_count: `{payload.get('ready_for_copy_count')}` / `{payload.get('required_file_count')}`",
        f"- missing: `{', '.join(payload.get('missing_filenames', []))}`",
        "",
        "## 文件状态",
        "",
    ]
    for item in payload.get("files", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(f"- `{item.get('filename')}` ready: `{item.get('ready_for_copy')}` target: `{item.get('target_path')}`")
    lines.extend(["", "## 下一步", ""])
    lines.extend(f"- {item}" for item in payload.get("operator_next_actions", []))
    lines.append("")
    return "\n".join(lines)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _relpath_or_abs(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover local US equity PIT CSV files.")
    parser.add_argument("--search-root", action="append", default=[], help="Additional search root. Can be repeated.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()
    roots = [Path(item) for item in args.search_root] if args.search_root else DEFAULT_SEARCH_ROOTS
    payload = build_us_equity_local_pit_file_discovery_report(
        search_roots=roots,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(payload["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
