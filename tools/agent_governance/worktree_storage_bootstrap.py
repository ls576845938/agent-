from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MODULE_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from tools.agent_governance.worktree_plan import AUTO_SPARSE_PATHS, FULL_CHECKOUT_OVERRIDE_ENV


IN_PROGRESS_ENV = "AGENT_AUTO_SPARSE_IN_PROGRESS"


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=os.environ,
    )


def _absolute_git_path(repo_root: Path, selector: str) -> Path:
    value = _git(repo_root, "rev-parse", "--path-format=absolute", selector).stdout.strip()
    return Path(value).resolve()


def is_linked_worktree(repo_root: Path) -> bool:
    return _absolute_git_path(repo_root, "--git-dir") != _absolute_git_path(repo_root, "--git-common-dir")


def auto_sparse_decision(repo_root: Path, *, environ: dict[str, str] | None = None) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    if environment.get(IN_PROGRESS_ENV) == "1":
        return {"action": "skip", "reason": "bootstrap_in_progress"}
    if environment.get(FULL_CHECKOUT_OVERRIDE_ENV) == "1":
        return {"action": "skip", "reason": "explicit_full_checkout_override"}
    if not is_linked_worktree(repo_root):
        return {"action": "skip", "reason": "primary_worktree"}
    sparse = _git(repo_root, "config", "--bool", "--get", "core.sparseCheckout", check=False)
    if sparse.returncode == 0 and sparse.stdout.strip().lower() == "true":
        return {"action": "skip", "reason": "already_sparse"}
    return {"action": "apply", "reason": "linked_worktree_default"}


def enforce_default_sparse_checkout(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    decision = auto_sparse_decision(root)
    if decision["action"] != "apply":
        return {"schema_version": "worktree_storage_bootstrap_v1", **decision, "repo_root": str(root)}

    previous_in_progress = os.environ.get(IN_PROGRESS_ENV)
    previous_skip_smudge = os.environ.get("GIT_LFS_SKIP_SMUDGE")
    os.environ[IN_PROGRESS_ENV] = "1"
    os.environ["GIT_LFS_SKIP_SMUDGE"] = "1"
    try:
        _git(root, "sparse-checkout", "init", "--cone")
        _git(root, "sparse-checkout", "set", "--cone", *AUTO_SPARSE_PATHS)
    finally:
        if previous_in_progress is None:
            os.environ.pop(IN_PROGRESS_ENV, None)
        else:
            os.environ[IN_PROGRESS_ENV] = previous_in_progress
        if previous_skip_smudge is None:
            os.environ.pop("GIT_LFS_SKIP_SMUDGE", None)
        else:
            os.environ["GIT_LFS_SKIP_SMUDGE"] = previous_skip_smudge

    return {
        "schema_version": "worktree_storage_bootstrap_v1",
        "action": "applied",
        "reason": decision["reason"],
        "repo_root": str(root),
        "sparse_paths": list(AUTO_SPARSE_PATHS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the repository's safe sparse default to linked worktrees.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = enforce_default_sparse_checkout(args.repo_root)
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        result = {
            "schema_version": "worktree_storage_bootstrap_v1",
            "action": "blocked",
            "reason": f"bootstrap_error:{type(exc).__name__}:{exc}",
            "repo_root": str(args.repo_root.resolve()),
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
