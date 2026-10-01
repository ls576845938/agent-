from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools.agent_governance.disk_guard import DiskGuardError, evaluate_disk_guard
from tools.agent_governance.repository_size_guard import (
    MAX_REPOSITORY_DATA_BYTES,
    StagedEntry,
    find_violations,
)
from tools.agent_governance.worktree_plan import AUTO_SPARSE_PATHS, apply_plan, build_plan
from tools.agent_governance.worktree_storage_bootstrap import (
    auto_sparse_decision,
    enforce_default_sparse_checkout,
)


GIB = 1024**3


def test_disk_watermarks_are_operation_specific(tmp_path: Path) -> None:
    full = evaluate_disk_guard(operation="full-worktree", path=tmp_path, free_bytes=49 * GIB)
    sparse = evaluate_disk_guard(operation="sparse-worktree", path=tmp_path, free_bytes=49 * GIB)
    data = evaluate_disk_guard(operation="data-collection", path=tmp_path, free_bytes=19 * GIB)

    assert full["status"] == "blocked_low_disk"
    assert sparse["status"] == "allowed"
    assert data["blocker"] == "disk_free_below_20gb"


def test_disk_guard_rejects_unknown_operation(tmp_path: Path) -> None:
    with pytest.raises(DiskGuardError, match="operation_invalid"):
        evaluate_disk_guard(operation="unknown", path=tmp_path, free_bytes=100 * GIB)


def test_worktree_plan_defaults_to_sparse_and_excludes_runtime_data(tmp_path: Path) -> None:
    plan = build_plan(role="btc_developer", task_id="disk-safe", parent=tmp_path)

    assert plan["checkout_mode"] == "sparse"
    assert plan["lfs_skip_smudge"] is True
    assert "quant_crypto" in plan["sparse_paths"]
    assert "data" not in plan["sparse_paths"]
    assert "artifacts" not in plan["sparse_paths"]


def test_repository_guard_blocks_mutable_db_and_large_artifact() -> None:
    violations = find_violations(
        [
            StagedEntry("data/market_data.sqlite", 10, False),
            StagedEntry("artifacts/run/full-ledger.json", MAX_REPOSITORY_DATA_BYTES + 1, True),
            StagedEntry("artifacts/run/summary.json", 1024, False),
        ]
    )

    assert [row["reason"] for row in violations] == [
        "mutable_runtime_database_forbidden",
        "large_data_or_artifact_requires_shared_data_manifest",
    ]


def test_apply_plan_creates_real_sparse_worktree_without_runtime_payloads(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "governance-test@example.invalid")
    _git(repo, "config", "user.name", "Governance Test")
    for relative in (
        "AGENTS.md",
        "quant_crypto/module.py",
        "tools/helper.py",
        "data/market_data.sqlite",
        "artifacts/full-ledger.json",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")

    plan = build_plan(
        role="btc_developer",
        task_id="sparse-integration",
        parent=tmp_path / "worktrees",
        repo_root=repo,
    )
    apply_plan(plan)
    target = Path(plan["target"])

    assert (target / "AGENTS.md").is_file()
    assert (target / "quant_crypto/module.py").is_file()
    assert (target / "tools/helper.py").is_file()
    assert not (target / "data").exists()
    assert not (target / "artifacts").exists()


def test_auto_sparse_backstop_converts_direct_linked_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "governance-test@example.invalid")
    _git(repo, "config", "user.name", "Governance Test")
    for relative in (
        "AGENTS.md",
        "quant_cn/module.py",
        "quant_crypto/module.py",
        "quant_us/module.py",
        "tools/helper.py",
        "data/market_data.sqlite",
        "artifacts/full-ledger.json",
        "mlruns/run/payload.json",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")

    target = tmp_path / "direct-worktree"
    _git(repo, "worktree", "add", "--detach", str(target), "HEAD")
    result = enforce_default_sparse_checkout(target)

    assert result["action"] == "applied"
    assert set(result["sparse_paths"]) == set(AUTO_SPARSE_PATHS)
    assert (target / "quant_cn/module.py").is_file()
    assert (target / "quant_crypto/module.py").is_file()
    assert (target / "quant_us/module.py").is_file()
    assert not (target / "data").exists()
    assert not (target / "artifacts").exists()
    assert not (target / "mlruns").exists()


def test_auto_sparse_backstop_skips_primary_and_explicit_full_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")

    assert auto_sparse_decision(repo)["reason"] == "primary_worktree"

    target = tmp_path / "full-worktree"
    (repo / "README.md").write_text("fixture", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "-m", "fixture")
    _git(repo, "worktree", "add", "--detach", str(target), "HEAD")
    decision = auto_sparse_decision(target, environ={"AGENT_ALLOW_FULL_CHECKOUT": "1"})

    assert decision == {"action": "skip", "reason": "explicit_full_checkout_override"}


def test_post_checkout_hook_runs_sparse_backstop_before_lfs() -> None:
    hook = (Path(__file__).resolve().parents[2] / ".githooks" / "post-checkout").read_text(encoding="utf-8")

    bootstrap_index = hook.index("worktree_storage_bootstrap.py")
    lfs_index = hook.index('git lfs post-checkout "$@"')
    assert bootstrap_index < lfs_index


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
