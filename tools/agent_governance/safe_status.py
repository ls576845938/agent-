from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

MODULE_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from tools.agent_governance.worktree_plan import AUTO_SPARSE_PATHS


PROTECTED_ROOTS = {
    ".git",
    ".venv",
    "artifacts",
    "data",
    "downloads",
    "mlruns",
    "node_modules",
    "venv",
}
PATH_MAGIC_RE = re.compile(r"[*?\[]|^:|^[A-Za-z]:")


def normalize_scopes(paths: Iterable[str] | None = None) -> tuple[str, ...]:
    requested = tuple(paths or AUTO_SPARSE_PATHS)
    normalized: list[str] = []
    for raw_path in requested:
        value = str(raw_path).strip().replace("\\", "/").rstrip("/")
        if not value or value == "." or value.startswith("/") or PATH_MAGIC_RE.search(value):
            raise ValueError(f"unsafe_status_scope:{raw_path}")
        parts = tuple(part for part in value.split("/") if part and part != ".")
        if not parts or ".." in parts:
            raise ValueError(f"unsafe_status_scope:{raw_path}")
        if parts[0].lower() in PROTECTED_ROOTS:
            raise ValueError(f"runtime_status_scope_forbidden:{raw_path}")
        candidate = "/".join(parts)
        if candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


def scoped_status(repo_root: Path, paths: Iterable[str] | None = None) -> list[str]:
    scopes = normalize_scopes(paths)
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=normal",
            "--no-renames",
            "--",
            *scopes,
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        env=environment,
    )
    return [
        entry.decode("utf-8", errors="surrogateescape")
        for entry in result.stdout.split(b"\0")
        if entry
    ]


def status_paths(entries: Iterable[str]) -> list[str]:
    return [entry[3:] for entry in entries if len(entry) >= 4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect dirty source paths without scanning runtime payloads.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        scopes = normalize_scopes(args.path or None)
        entries = scoped_status(args.repo_root.resolve(), scopes)
        paths = status_paths(entries)
        payload = {
            "schema_version": "safe_status_v1",
            "status": "dirty" if paths else "clean",
            "scopes": list(scopes),
            "dirty_count": len(paths),
            "dirty_paths": paths,
            "entries": entries,
        }
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        payload = {
            "schema_version": "safe_status_v1",
            "status": "blocked",
            "blocker": f"safe_status_error:{type(exc).__name__}:{exc}",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
