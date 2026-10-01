from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import urllib.request

import pytest

import tools.agent_governance.shared_data as shared_data_module
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    WRITER_LOCK_NAME,
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactReader,
    git_worktree_roots,
    repository_identity_for_source,
)
from quant_crypto.application.btc_shared_observation_inputs import (
    APPROVED_GIT_EXECUTABLE,
    APPROVED_GIT_EXECUTABLE_SHA256,
)
from scripts.bootstrap_btc_runtime_artifact_root import (
    bootstrap_btc_runtime_artifact_root,
)
from scripts.run_btc_external_runtime_observe_job import (
    BTCExternalRuntimeObserveJobError,
    RECEIPT_LOGICAL_PATH,
    run_btc_external_runtime_observe_job,
    validate_btc_external_runtime_observe_receipt,
)
from tools.agent_governance.shared_data import publish_dataset

STATIC_BINDING = {
    "expected_source_head": "0" * 40,
    "repository_identity": "sha256:" + "0" * 64,
    "worktree_roots": (Path.cwd().resolve(),),
    "git_executable": APPROVED_GIT_EXECUTABLE,
    "git_executable_sha256": APPROVED_GIT_EXECUTABLE_SHA256,
}


def test_observe_job_writes_only_external_blocked_receipt_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    shared_before = _tree_hash(fixture["shared_root"])
    forbidden_calls: list[str] = []

    def fail_network(*_args, **_kwargs):
        forbidden_calls.append("network")
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    monkeypatch.setattr(
        shared_data_module,
        "publish_dataset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("publish forbidden")
        ),
    )

    receipt = run_btc_external_runtime_observe_job(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["public_spec"],
        l2_manifest_git_spec=fixture["l2_spec"],
        **_binding(fixture),
        environment={
            ENVIRONMENT_VARIABLE: str(fixture["artifact_root"])
        },
        generated_at="2026-07-27T00:00:00Z",
    )

    validate_btc_external_runtime_observe_receipt(receipt)
    assert receipt["status"] == "blocked_fail_closed"
    assert len(receipt["source_head"]) == 40
    assert receipt["commit"] == receipt["source_head"][:12]
    assert receipt["consumer_read_only"] is True
    assert receipt["all_files_verified"] is True
    assert receipt["inputs"]["public_swap"]["input_classification"] == (
        "research_only_input"
    )
    assert receipt["inputs"]["l2"]["input_classification"] == (
        "blocked_evidence_only"
    )
    assert all(value is False for value in receipt["safety"].values())
    assert forbidden_calls == []
    assert _tree_hash(fixture["shared_root"]) == shared_before
    assert _git(fixture["repo"], "status", "--porcelain") == ""

    reader = BTCRuntimeArtifactReader.from_environment(
        source_repo_root=fixture["repo"],
        environment={
            ENVIRONMENT_VARIABLE: str(fixture["artifact_root"])
        },
    )
    receipt_path = reader.resolve(RECEIPT_LOGICAL_PATH, require_file=True)
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    assert not (fixture["artifact_root"] / WRITER_LOCK_NAME).exists()
    assert not list(receipt_path.parent.glob(f".{receipt_path.name}.*.tmp"))
    assert not (
        fixture["repo"]
        / "artifacts/btc_external_runtime_observe_job"
    ).exists()


@pytest.mark.parametrize(
    ("repo_root", "shared_root", "expected"),
    [
        (
            Path("relative-repo"),
            Path.cwd().resolve(),
            "btc_external_runtime_observe_repo_root_must_be_absolute",
        ),
        (
            Path.cwd().resolve(),
            Path("relative-shared"),
            "btc_external_runtime_observe_shared_root_must_be_absolute",
        ),
    ],
)
def test_observe_job_requires_absolute_cli_roots(
    repo_root: Path,
    shared_root: Path,
    expected: str,
) -> None:
    with pytest.raises(
        BTCExternalRuntimeObserveJobError,
        match=expected,
    ):
        run_btc_external_runtime_observe_job(
            repo_root=repo_root,
            shared_root=shared_root,
            public_swap_manifest_git_spec="0" * 40 + ":.agent/data_manifests/public.json",
            l2_manifest_git_spec="0" * 40 + ":.agent/data_manifests/l2.json",
            **STATIC_BINDING,
            environment={},
        )


def test_invalid_manifest_spec_still_writes_external_blocked_receipt(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    receipt = run_btc_external_runtime_observe_job(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=(
            "HEAD:.agent/data_manifests/public.json"
        ),
        l2_manifest_git_spec=fixture["l2_spec"],
        **_binding(fixture),
        environment={
            ENVIRONMENT_VARIABLE: str(fixture["artifact_root"])
        },
    )

    assert receipt["status"] == "blocked_fail_closed"
    assert receipt["all_files_verified"] is False
    assert receipt["input_errors"]
    assert (
        fixture["artifact_root"]
        / "btc_external_runtime_observe_job"
        / "btc_external_runtime_observe_receipt.json"
    ).is_file()


def test_invalid_runtime_root_writes_nowhere(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, bootstrap_runtime=False)
    invalid_root = tmp_path / "invalid-runtime-root"
    invalid_root.mkdir()

    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_owner_marker_missing",
    ):
        run_btc_external_runtime_observe_job(
            repo_root=fixture["repo"],
            shared_root=fixture["shared_root"],
            public_swap_manifest_git_spec=fixture["public_spec"],
            l2_manifest_git_spec=fixture["l2_spec"],
            **_binding(fixture),
            environment={ENVIRONMENT_VARIABLE: str(invalid_root)},
        )

    assert list(invalid_root.iterdir()) == []
    assert not (
        fixture["repo"]
        / "artifacts/btc_external_runtime_observe_job"
    ).exists()


@pytest.mark.parametrize(
    "relationship",
    [
        "artifact_equals_shared",
        "artifact_inside_shared",
        "shared_inside_artifact",
    ],
)
def test_observe_job_rejects_artifact_shared_root_overlap_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relationship: str,
) -> None:
    fixture = _fixture(tmp_path / "fixture", bootstrap_runtime=False)
    if relationship == "artifact_equals_shared":
        artifact_root = tmp_path / "overlap-root"
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=fixture["repo"],
            artifact_root=artifact_root.resolve(),
        )
        shared_root = artifact_root
    elif relationship == "artifact_inside_shared":
        shared_root = tmp_path / "shared-container"
        shared_root.mkdir()
        artifact_root = shared_root / "runtime-artifacts"
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=fixture["repo"],
            artifact_root=artifact_root.resolve(),
        )
    else:
        artifact_root = tmp_path / "artifact-container"
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=fixture["repo"],
            artifact_root=artifact_root.resolve(),
        )
        shared_root = artifact_root / "shared"
        shared_root.mkdir()

    shared_before = _tree_snapshot(shared_root)
    monkeypatch.setattr(
        "scripts.run_btc_external_runtime_observe_job."
        "consume_btc_shared_observation_inputs",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("overlap must fail before input consumption")
        ),
    )

    with pytest.raises(
        BTCExternalRuntimeObserveJobError,
        match=(
            "btc_external_runtime_observe_"
            "artifact_shared_root_overlap"
        ),
    ):
        run_btc_external_runtime_observe_job(
            repo_root=fixture["repo"],
            shared_root=shared_root.resolve(),
            public_swap_manifest_git_spec=fixture["public_spec"],
            l2_manifest_git_spec=fixture["l2_spec"],
            **_binding(fixture),
            environment={
                ENVIRONMENT_VARIABLE: str(artifact_root.resolve())
            },
        )

    assert _tree_snapshot(shared_root) == shared_before
    assert not (
        artifact_root
        / "btc_external_runtime_observe_job"
        / "btc_external_runtime_observe_receipt.json"
    ).exists()
    assert not (artifact_root / WRITER_LOCK_NAME).exists()
    assert not (
        fixture["repo"]
        / "artifacts/btc_external_runtime_observe_job"
    ).exists()


def test_cli_help_and_blocked_exit_two_with_valid_receipt(
    tmp_path: Path,
) -> None:
    help_result = subprocess.run(
        [
            sys.executable,
            "scripts/run_btc_external_runtime_observe_job.py",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert help_result.returncode == 0
    assert "--public-swap-manifest-git-spec" in help_result.stdout
    assert "--l2-manifest-git-spec" in help_result.stdout
    assert "--git-executable" in help_result.stdout
    assert "--git-executable-sha256" in help_result.stdout
    assert "--fast" not in help_result.stdout

    fixture = _fixture(tmp_path / "run")
    environment = {
        ENVIRONMENT_VARIABLE: str(fixture["artifact_root"]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    binding = _binding(fixture)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_btc_external_runtime_observe_job.py",
            "--repo-root",
            str(fixture["repo"]),
            "--shared-root",
            str(fixture["shared_root"]),
            "--public-swap-manifest-git-spec",
            fixture["public_spec"],
            "--l2-manifest-git-spec",
            fixture["l2_spec"],
            "--expected-source-head",
            binding["expected_source_head"],
            "--repository-identity",
            binding["repository_identity"],
            *[
                item
                for root in binding["worktree_roots"]
                for item in ("--worktree-root", str(root))
            ],
            "--git-executable",
            str(binding["git_executable"]),
            "--git-executable-sha256",
            binding["git_executable_sha256"],
        ],
        cwd=Path.cwd(),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary["status"] == "blocked_fail_closed"
    assert all(value is False for value in summary["safety"].values())
    receipt_path = (
        fixture["artifact_root"]
        / "btc_external_runtime_observe_job"
        / "btc_external_runtime_observe_receipt.json"
    )
    validate_btc_external_runtime_observe_receipt(
        json.loads(receipt_path.read_text(encoding="utf-8"))
    )


def _fixture(
    tmp_path: Path,
    *,
    bootstrap_runtime: bool = True,
) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    _git(repo, "commit", "--allow-empty", "-m", "base")
    producer_commit = _git(repo, "rev-parse", "HEAD")
    shared_root = tmp_path / "shared"

    public_source = tmp_path / "public-source"
    (public_source / "bundle").mkdir(parents=True)
    (public_source / "bundle/public.json").write_text(
        '{"public":true}\n',
        encoding="utf-8",
    )
    public_manifest_path = (
        repo / ".agent/data_manifests/public/public-v1.json"
    )
    publish_dataset(
        source=public_source,
        shared_root=shared_root,
        dataset_id="btc-okx-public-swap-research-bundle",
        dataset_version="public-v1",
        readiness_class="quality_checked",
        quality_status="pass_with_research_only_warnings",
        producer_role="data_steward",
        producer_commit=producer_commit,
        schema_name="btc_okx_public_swap_research_bundle_v1",
        blockers=["d1_one_day_only"],
        known_gaps=["d1_history_gap"],
        manifest_output=public_manifest_path,
    )

    l2_source = tmp_path / "l2-source"
    (l2_source / "source_receipt").mkdir(parents=True)
    (l2_source / "source_receipt/l2.json").write_text(
        json.dumps(
            {
                "status": "blocked_fail_closed",
                "decision": "blocked_no_real_l2",
                "blockers": ["d2_real_l2_missing"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    l2_manifest_path = (
        repo / ".agent/data_manifests/l2/l2-blocked-v1.json"
    )
    publish_dataset(
        source=l2_source,
        shared_root=shared_root,
        dataset_id="btc-okx-timestamp-aligned-public-l2-history",
        dataset_version="l2-blocked-v1",
        readiness_class="quality_checked",
        quality_status="blocked",
        producer_role="data_steward",
        producer_commit=producer_commit,
        schema_name="btc_okx_l2_rejected_source_receipt_v1",
        blockers=["d2_real_l2_missing"],
        known_gaps=["d2_natural_history_zero_days"],
        manifest_output=l2_manifest_path,
    )
    public_relative = public_manifest_path.relative_to(repo).as_posix()
    l2_relative = l2_manifest_path.relative_to(repo).as_posix()
    _git(repo, "add", public_relative, l2_relative)
    _git(repo, "commit", "-m", "publish manifests")
    manifest_commit = _git(repo, "rev-parse", "HEAD")

    artifact_root = tmp_path / "runtime-artifacts"
    if bootstrap_runtime:
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=repo.resolve(),
            artifact_root=artifact_root.resolve(),
        )
    return {
        "repo": repo.resolve(),
        "shared_root": shared_root.resolve(),
        "artifact_root": artifact_root.resolve(),
        "source_head": manifest_commit,
        "public_spec": f"{manifest_commit}:{public_relative}",
        "l2_spec": f"{manifest_commit}:{l2_relative}",
    }


def _binding(fixture: dict[str, object]) -> dict[str, object]:
    repo = Path(fixture["repo"])
    return {
        "expected_source_head": fixture["source_head"],
        "repository_identity": repository_identity_for_source(repo),
        "worktree_roots": git_worktree_roots(repo),
        "git_executable": APPROVED_GIT_EXECUTABLE,
        "git_executable_sha256": APPROVED_GIT_EXECUTABLE_SHA256,
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            "directory" if path.is_dir() else "file",
            b"" if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(
            root.rglob("*"),
            key=lambda item: item.relative_to(root).as_posix(),
        )
    )
