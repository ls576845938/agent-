from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

MODULE_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from tools.agent_governance.git_metadata import GitMetadataError, main_repository_root
from tools.agent_governance.disk_guard import require_disk_capacity


REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_ROLES = {"a_share_developer", "data_steward", "super_developer", "btc_developer", "integrator"}
COMMON_SPARSE_PATHS = (
    ".agent",
    ".agents",
    ".codex",
    ".github",
    "backend",
    "config",
    "configs",
    "deploy",
    "docs",
    "frontend",
    "integrations",
    "quant_shared",
    "schemas",
    "scripts",
    "tests",
    "tools",
)
ROLE_SPARSE_PATHS = {
    "a_share_developer": ("quant_cn",),
    "btc_developer": ("quant_crypto",),
    "data_steward": ("quant_cn", "quant_crypto", "quant_us"),
    "integrator": ("quant_cn", "quant_crypto", "quant_us"),
    "super_developer": ("quant_us",),
}
AUTO_SPARSE_PATHS = tuple(
    sorted({*COMMON_SPARSE_PATHS, *(path for paths in ROLE_SPARSE_PATHS.values() for path in paths)})
)
FULL_CHECKOUT_OVERRIDE_ENV = "AGENT_ALLOW_FULL_CHECKOUT"


def default_worktree_parent(repo_root: Path = REPO_ROOT) -> Path:
    try:
        return main_repository_root(repo_root).parent / "worktrees"
    except (OSError, GitMetadataError):
        return repo_root.resolve().parent / "worktrees"


DEFAULT_PARENT = default_worktree_parent()


def build_plan(
    *,
    role: str,
    task_id: str,
    base_ref: str = "HEAD",
    parent: Path = DEFAULT_PARENT,
    repo_root: Path = REPO_ROOT,
    full_checkout: bool = False,
) -> dict[str, Any]:
    if role not in WRITER_ROLES:
        raise ValueError(f"role_does_not_need_write_worktree:{role}")
    normalized_task = task_id.strip().lower().replace("_", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}", normalized_task):
        raise ValueError(f"invalid_task_id:{task_id}")

    parent_path = parent.resolve()
    target = (parent_path / f"{role}-{normalized_task}").resolve()
    if target.parent != parent_path:
        raise ValueError(f"worktree_target_outside_parent:{target}")

    sparse_paths = sorted({*COMMON_SPARSE_PATHS, *ROLE_SPARSE_PATHS[role]})
    return {
        "schema_version": "agent_worktree_plan_v2",
        "role": role,
        "task_id": normalized_task,
        "base_ref": base_ref,
        "branch": f"agent/{role}/{normalized_task}",
        "repo_root": str(repo_root.resolve()),
        "target": str(target),
        "checkout_mode": "full" if full_checkout else "sparse",
        "sparse_paths": [] if full_checkout else sparse_paths,
        "lfs_skip_smudge": True,
    }


def apply_plan(plan: dict[str, Any]) -> None:
    target = Path(plan["target"])
    if target.exists():
        raise FileExistsError(f"worktree_target_exists:{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    checkout_mode = str(plan.get("checkout_mode", "sparse"))
    require_disk_capacity(
        operation="full-worktree" if checkout_mode == "full" else "sparse-worktree",
        path=target.parent,
    )
    environment = dict(os.environ)
    environment["GIT_LFS_SKIP_SMUDGE"] = "1"
    if checkout_mode == "full":
        environment[FULL_CHECKOUT_OVERRIDE_ENV] = "1"
    repo_root = Path(plan.get("repo_root", REPO_ROOT)).resolve()
    command = ["git", "worktree", "add"]
    if checkout_mode == "sparse":
        command.append("--no-checkout")
    command.extend(["-b", plan["branch"], str(target), plan["base_ref"]])
    subprocess.run(command, cwd=repo_root, check=True, env=environment)
    if checkout_mode == "sparse":
        subprocess.run(["git", "sparse-checkout", "init", "--cone"], cwd=target, check=True, env=environment)
        subprocess.run(
            ["git", "sparse-checkout", "set", "--cone", *plan["sparse_paths"]],
            cwd=target,
            check=True,
            env=environment,
        )
        subprocess.run(["git", "checkout", plan["branch"]], cwd=target, check=True, env=environment)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or create an isolated writer-agent worktree.")
    parser.add_argument("--role", required=True, choices=sorted(WRITER_ROLES))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--parent", type=Path, default=DEFAULT_PARENT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--full-checkout", action="store_true")
    args = parser.parse_args(argv)

    plan = build_plan(
        role=args.role,
        task_id=args.task_id,
        base_ref=args.base_ref,
        parent=args.parent,
        full_checkout=args.full_checkout,
    )
    plan["applied"] = bool(args.apply)
    if args.apply:
        apply_plan(plan)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
