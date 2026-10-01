#!/usr/bin/env python3
"""Back up an external strategy project before system-level refactors.

The backup is intentionally outside git by default. The manifest records file
hashes and the exact backup location so future changes to external user code
remain reversible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "external_strategy_project_backup_manifest_v1"
DEFAULT_SOURCE = Path("D:/Trading/ETF轮动与数据引擎模块化代码")
DEFAULT_BACKUP_ROOT = Path("D:/Trading/_codex_backups")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/external_strategy_backup_manifest.json")
EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}


def backup_external_strategy_project(
    *,
    repo_root: Path,
    source: Path = DEFAULT_SOURCE,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    report_path: Path = DEFAULT_REPORT,
    project_id: str = "ETF轮动与数据引擎模块化代码",
    generated_at: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = repo_root.resolve()
    src = source.resolve()
    generated = generated_at or _utc_now()
    backup_dir = (backup_root / _safe_name(project_id) / generated.replace(":", "").replace("+0000", "Z")).resolve()
    report_abs = _resolve(root, report_path)

    if not src.exists() or not src.is_dir():
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "blocked",
            "project_id": project_id,
            "source": str(src),
            "backup_dir": str(backup_dir),
            "dry_run": dry_run,
            "files": [],
            "summary": {"file_count": 0, "total_bytes": 0},
            "blockers": ["external_strategy_source_missing"],
        }
        _write_json(report_abs, payload)
        return payload

    files = list(_iter_project_files(src))
    manifest_files: list[dict[str, Any]] = []
    for file_path in files:
        rel = file_path.relative_to(src)
        target = backup_dir / rel
        stat = file_path.stat()
        item = {
            "relative_path": rel.as_posix(),
            "bytes": int(stat.st_size),
            "sha256": _sha256(file_path),
            "source_path": str(file_path),
            "backup_path": str(target),
        }
        manifest_files.append(item)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, target)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "dry_run" if dry_run else "completed",
        "project_id": project_id,
        "source": str(src),
        "backup_root": str(backup_root.resolve()),
        "backup_dir": str(backup_dir),
        "dry_run": dry_run,
        "files": manifest_files,
        "summary": {
            "file_count": len(manifest_files),
            "total_bytes": sum(int(item["bytes"]) for item in manifest_files),
            "sha256_manifest": _hash_manifest(manifest_files),
        },
        "blockers": [],
    }
    _write_json(report_abs, payload)
    return payload


def _iter_project_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        yield path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_manifest(files: list[Mapping[str, Any]]) -> str:
    payload = [
        {"relative_path": item["relative_path"], "bytes": item["bytes"], "sha256": item["sha256"]}
        for item in files
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value).strip("_") or "external_strategy"


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up an external strategy project before modification.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--project-id", default="ETF轮动与数据引擎模块化代码")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = backup_external_strategy_project(
        repo_root=Path(args.repo_root),
        source=Path(args.source),
        backup_root=Path(args.backup_root),
        report_path=Path(args.report),
        project_id=args.project_id,
        dry_run=bool(args.dry_run),
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "backup_dir": payload["backup_dir"],
                "file_count": payload["summary"]["file_count"],
                "report": str(Path(args.report)),
                "blockers": payload.get("blockers", []),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
