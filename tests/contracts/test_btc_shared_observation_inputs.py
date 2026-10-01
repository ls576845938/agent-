from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

import quant_crypto.application.btc_shared_observation_inputs as consumer_module
from quant_crypto.application.btc_shared_observation_inputs import (
    APPROVED_GIT_EXECUTABLE,
    APPROVED_GIT_EXECUTABLE_SHA256,
    L2_CAPTURE_REPORT_SCHEMA,
    L2_DATASET_ID,
    PUBLIC_SWAP_DATASET_ID,
    consume_btc_shared_observation_inputs,
)
from tools.agent_governance.shared_data import (
    MANIFEST_NAME,
    build_manifest,
    inventory_directory,
)

GIT_BINDING = {
    "git_executable": APPROVED_GIT_EXECUTABLE,
    "git_executable_sha256": APPROVED_GIT_EXECUTABLE_SHA256,
}


def test_git_argv_zero_is_exact_absolute_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _immutable_inputs(tmp_path)
    observed: list[str] = []
    real_run = subprocess.run

    def recording_run(argv, *args, **kwargs):
        observed.append(str(argv[0]))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(consumer_module.subprocess, "run", recording_run)
    result = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["public_spec"],
        l2_manifest_git_spec=fixture["l2_spec"],
        **GIT_BINDING,
    )

    assert result["all_files_verified"] is True
    assert observed
    assert all(Path(value).is_absolute() for value in observed)
    assert {
        Path(value).resolve() for value in observed
    } == {APPROVED_GIT_EXECUTABLE.resolve()}


def test_named_committed_inputs_resolve_with_full_hashes_and_preserved_blocks(
    tmp_path: Path,
) -> None:
    fixture = _immutable_inputs(tmp_path)
    before = _tree_hash(fixture["shared_root"])

    result = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["public_spec"],
        l2_manifest_git_spec=fixture["l2_spec"],
        **GIT_BINDING,
    )

    public = result["inputs"]["public_swap"]
    l2 = result["inputs"]["l2"]
    assert result["all_files_verified"] is True
    assert result["consumer_read_only"] is True
    assert public["dataset_id"] == PUBLIC_SWAP_DATASET_ID
    assert public["input_classification"] == "research_only_input"
    assert public["readiness_class"] == "quality_checked"
    assert public["manifest_commit"] == fixture["manifest_commit"]
    assert public["producer_commit"] == fixture["producer_commit"]
    assert len(public["manifest_commit"]) == 40
    assert len(public["producer_commit"]) == 40
    assert public["raw_committed_manifest_sha256"] == hashlib.sha256(
        _git_bytes(
            fixture["repo"],
            "show",
            fixture["public_spec"],
        )
    ).hexdigest()
    assert public["blockers"] == ["d1_one_day_only"]
    assert public["known_gaps"] == ["d1_history_gap"]
    assert l2["dataset_id"] == L2_DATASET_ID
    assert l2["status"] == "resolved_blocked_evidence_only"
    assert l2["quality_status"] == "blocked"
    assert l2["source_receipt"]["blocked_evidence_only"] is True
    assert l2["source_receipt"]["schema_version"] == (
        L2_CAPTURE_REPORT_SCHEMA
    )
    assert l2["source_receipt"]["status"] == "rejected"
    assert l2["source_receipt"]["decision"] == ""
    assert l2["source_receipt"]["completed_sample_count"] == 0
    assert l2["source_receipt"]["source_file_count"] == 0
    assert l2["source_receipt"]["data_samples_accepted"] is False
    assert l2["blockers"] == ["d2_real_l2_missing"]
    assert l2["known_gaps"] == ["d2_natural_history_zero_days"]
    assert "d1_one_day_only" in result["blockers"]
    assert "d2_real_l2_missing" in result["blockers"]
    assert "btc_external_runtime_observe_not_dataready" in result["blockers"]
    assert (
        "btc_external_runtime_observe_not_research_ready"
        in result["blockers"]
    )
    assert _tree_hash(fixture["shared_root"]) == before


@pytest.mark.parametrize(
    "bad_spec_factory",
    [
        lambda fixture: (
            fixture["manifest_commit"][:12]
            + ":"
            + fixture["public_path"]
        ),
        lambda fixture: "HEAD:" + fixture["public_path"],
        lambda fixture: "main:" + fixture["public_path"],
        lambda fixture: "fixture-tag:" + fixture["public_path"],
        lambda fixture: (
            fixture["manifest_commit"]
            + ":.agent/data_manifests/../escape.json"
        ),
        lambda fixture: (
            fixture["manifest_commit"]
            + r":.agent\data_manifests\escape.json"
        ),
        lambda fixture: (
            fixture["manifest_commit"]
            + ":.agent/data_manifests/public/latest.json"
        ),
        lambda fixture: (
            fixture["manifest_commit"]
            + ":.agent/data_manifests/public/runtime_pointer.json"
        ),
        lambda fixture: (
            fixture["tag_object"]
            + ":"
            + fixture["public_path"]
        ),
    ],
)
def test_git_spec_rejects_implicit_or_noncommit_selection(
    tmp_path: Path,
    bad_spec_factory,
) -> None:
    fixture = _immutable_inputs(tmp_path)
    result = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=bad_spec_factory(fixture),
        l2_manifest_git_spec=fixture["l2_spec"],
        **GIT_BINDING,
    )

    assert result["all_files_verified"] is False
    assert result["inputs"]["public_swap"]["status"] == "blocked_fail_closed"
    assert result["inputs"]["public_swap"]["consumer_read_only"] is True
    assert result["input_errors"]


def test_hash_mismatch_and_dataset_swap_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _immutable_inputs(tmp_path)
    public_file = (
        fixture["shared_root"]
        / "datasets"
        / PUBLIC_SWAP_DATASET_ID
        / "public-v1"
        / "bundle"
        / "public.json"
    )
    public_file.write_text('{"tampered":true}\n', encoding="utf-8")

    mismatched = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["public_spec"],
        l2_manifest_git_spec=fixture["l2_spec"],
        **GIT_BINDING,
    )
    assert mismatched["all_files_verified"] is False
    assert any(
        "shared_data_file_" in blocker
        for blocker in mismatched["input_errors"]
    )

    swapped = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["l2_spec"],
        l2_manifest_git_spec=fixture["public_spec"],
        **GIT_BINDING,
    )
    assert swapped["all_files_verified"] is False
    assert len(swapped["input_errors"]) == 2
    assert all(
        "btc_observe_manifest_dataset_mismatch" in blocker
        for blocker in swapped["input_errors"]
    )


def test_l2_source_receipt_must_be_blocked_evidence(
    tmp_path: Path,
) -> None:
    fixture = _immutable_inputs(
        tmp_path,
        l2_receipt={
            "status": "verified",
            "decision": "ready",
            "blockers": [],
        },
    )
    result = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["public_spec"],
        l2_manifest_git_spec=fixture["l2_spec"],
        **GIT_BINDING,
    )

    assert result["all_files_verified"] is False
    assert any(
        "btc_observe_l2_source_receipt_not_blocked_evidence"
        in blocker
        for blocker in result["input_errors"]
    )


def test_explicit_blocked_l2_source_receipt_remains_accepted(
    tmp_path: Path,
) -> None:
    fixture = _immutable_inputs(
        tmp_path,
        l2_receipt={
            "status": "blocked_fail_closed",
            "decision": "blocked_no_real_l2",
            "blockers": ["d2_real_l2_missing"],
        },
    )

    result = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["public_spec"],
        l2_manifest_git_spec=fixture["l2_spec"],
        **GIT_BINDING,
    )

    assert result["all_files_verified"] is True
    source_receipt = result["inputs"]["l2"]["source_receipt"]
    assert source_receipt["status"] == "blocked_fail_closed"
    assert source_receipt["decision"] == "blocked_no_real_l2"
    assert source_receipt["blockers"] == ["d2_real_l2_missing"]
    assert source_receipt["blocked_evidence_only"] is True
    assert source_receipt["data_samples_accepted"] is False


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"completed_sample_count": 1},
        {"files": [{"path": "captured-sample.json"}]},
        {"blockers": []},
        {"schema_version": "btc_okx_timestamp_aligned_l2_capture_report_v0"},
        {"decision": "blocked_but_rejected_contract_must_be_exact"},
    ],
)
def test_rejected_l2_source_receipt_requires_exact_empty_capture_contract(
    tmp_path: Path,
    invalid_fields: dict[str, object],
) -> None:
    rejected_receipt: dict[str, object] = {
        "schema_version": L2_CAPTURE_REPORT_SCHEMA,
        "status": "rejected",
        "blockers": ["d2_real_l2_missing"],
        "completed_sample_count": 0,
        "files": [],
    }
    rejected_receipt.update(invalid_fields)
    fixture = _immutable_inputs(
        tmp_path,
        l2_receipt=rejected_receipt,
    )

    result = consume_btc_shared_observation_inputs(
        repo_root=fixture["repo"],
        shared_root=fixture["shared_root"],
        public_swap_manifest_git_spec=fixture["public_spec"],
        l2_manifest_git_spec=fixture["l2_spec"],
        **GIT_BINDING,
    )

    assert result["all_files_verified"] is False
    assert result["inputs"]["l2"]["status"] == "blocked_fail_closed"
    assert any(
        "btc_observe_l2_source_receipt_not_blocked_evidence"
        in blocker
        for blocker in result["input_errors"]
    )


def _immutable_inputs(
    tmp_path: Path,
    *,
    l2_receipt: dict[str, object] | None = None,
) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    _git(repo, "commit", "--allow-empty", "-m", "base")
    producer_commit = _git(repo, "rev-parse", "HEAD")
    shared_root = tmp_path / "shared"

    public_manifest = _manifest(
        shared_root=shared_root,
        dataset_id=PUBLIC_SWAP_DATASET_ID,
        dataset_version="public-v1",
        producer_commit=producer_commit,
        quality_status="pass_with_research_only_warnings",
        blockers=["d1_one_day_only"],
        known_gaps=["d1_history_gap"],
        data_schema="btc_okx_public_swap_research_bundle_v1",
        files={"bundle/public.json": b'{"public":true}\n'},
    )
    l2_manifest = _manifest(
        shared_root=shared_root,
        dataset_id=L2_DATASET_ID,
        dataset_version="l2-blocked-v1",
        producer_commit=producer_commit,
        quality_status="blocked",
        blockers=["d2_real_l2_missing"],
        known_gaps=["d2_natural_history_zero_days"],
        data_schema="btc_okx_l2_rejected_source_receipt_v1",
        files={
            "source_receipt/l2.json": (
                json.dumps(
                    l2_receipt
                    if l2_receipt is not None
                    else {
                        "schema_version": L2_CAPTURE_REPORT_SCHEMA,
                        "status": "rejected",
                        "blockers": ["d2_real_l2_missing"],
                        "completed_sample_count": 0,
                        "files": [],
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        },
    )
    public_path = (
        ".agent/data_manifests/public/public-v1.json"
    )
    l2_path = ".agent/data_manifests/l2/l2-blocked-v1.json"
    _write_json(repo / public_path, public_manifest)
    _write_json(repo / l2_path, l2_manifest)
    _git(repo, "add", public_path, l2_path)
    _git(repo, "commit", "-m", "publish committed manifests")
    manifest_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "fixture-tag", "-m", "fixture tag")
    tag_object = _git(repo, "rev-parse", "fixture-tag^{tag}")
    return {
        "repo": repo.resolve(),
        "shared_root": shared_root.resolve(),
        "producer_commit": producer_commit,
        "manifest_commit": manifest_commit,
        "public_path": public_path,
        "l2_path": l2_path,
        "public_spec": f"{manifest_commit}:{public_path}",
        "l2_spec": f"{manifest_commit}:{l2_path}",
        "tag_object": tag_object,
    }


def _manifest(
    *,
    shared_root: Path,
    dataset_id: str,
    dataset_version: str,
    producer_commit: str,
    quality_status: str,
    blockers: list[str],
    known_gaps: list[str],
    data_schema: str,
    files: dict[str, bytes],
) -> dict[str, object]:
    target = (
        shared_root / "datasets" / dataset_id / dataset_version
    )
    for relative, content in files.items():
        path = target.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    inventory, aggregate, total_bytes = inventory_directory(target)
    manifest = build_manifest(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        readiness_class="quality_checked",
        quality_status=quality_status,
        files=inventory,
        aggregate_sha256=aggregate,
        total_bytes=total_bytes,
        producer_commit=producer_commit,
        blockers=blockers,
        known_gaps=known_gaps,
        schema_name=data_schema,
        published_at="2026-07-27T00:00:00Z",
    )
    _write_json(target / MANIFEST_NAME, manifest)
    return manifest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
