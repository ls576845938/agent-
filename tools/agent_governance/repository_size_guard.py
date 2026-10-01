from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


MAX_REPOSITORY_DATA_BYTES = 5 * 1024 * 1024
PROTECTED_MUTABLE_PATHS = {
    "data/market_data.sqlite",
    "data/market_data.sqlite-shm",
    "data/market_data.sqlite-wal",
}
LFS_POINTER_RE = re.compile(
    rb"\Aversion https://git-lfs\.github\.com/spec/v1\n"
    rb"oid sha256:[0-9a-f]{64}\nsize ([0-9]+)\n?\Z"
)


@dataclass(frozen=True)
class StagedEntry:
    path: str
    effective_bytes: int
    lfs_pointer: bool


def policy_violation(entry: StagedEntry) -> str | None:
    normalized = entry.path.replace("\\", "/")
    if normalized in PROTECTED_MUTABLE_PATHS:
        return "mutable_runtime_database_forbidden"
    if normalized.startswith(("data/", "artifacts/")) and entry.effective_bytes > MAX_REPOSITORY_DATA_BYTES:
        return "large_data_or_artifact_requires_shared_data_manifest"
    return None


def staged_entries(repo_root: Path) -> list[StagedEntry]:
    paths = _git(
        repo_root,
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        binary=True,
    ).split(b"\0")
    entries: list[StagedEntry] = []
    for raw_path in paths:
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        size = int(_git(repo_root, "cat-file", "-s", f":{path}").strip())
        pointer = False
        effective_size = size
        if size <= 4096:
            content = _git(repo_root, "show", f":{path}", binary=True)
            match = LFS_POINTER_RE.fullmatch(content)
            if match:
                pointer = True
                effective_size = int(match.group(1))
        entries.append(StagedEntry(path=path, effective_bytes=effective_size, lfs_pointer=pointer))
    return entries


def find_violations(entries: Iterable[StagedEntry]) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for entry in entries:
        reason = policy_violation(entry)
        if reason:
            violations.append({**asdict(entry), "reason": reason})
    return violations


def _git(repo_root: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
    )
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject mutable databases and large repository artifacts.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        entries = staged_entries(args.repo_root.resolve())
        violations = find_violations(entries)
        payload = {
            "schema_version": "repository_size_guard_v1",
            "status": "blocked" if violations else "pass",
            "staged_entry_count": len(entries),
            "violations": violations,
        }
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        payload = {
            "schema_version": "repository_size_guard_v1",
            "status": "blocked_guard_error",
            "violations": [{"reason": f"guard_error:{type(exc).__name__}:{exc}"}],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
