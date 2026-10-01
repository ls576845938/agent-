#!/usr/bin/env python3
"""Fail-closed launcher for the one canonical BTC observe-only task."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence


MODULE_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from quant_crypto.adapters.btc_runtime_artifact_store import (  # noqa: E402
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    REPOSITORY_IDENTITY_SCHEMA_VERSION,
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriter,
)
from quant_crypto.application.btc_shared_observation_inputs import (  # noqa: E402
    APPROVED_GIT_EXECUTABLE,
    APPROVED_GIT_EXECUTABLE_SHA256,
    BTCSharedObservationInputsError,
    L2_DATASET_ID,
    PUBLIC_SWAP_DATASET_ID,
    validate_btc_observe_git_executable,
)
from scripts.run_btc_external_runtime_observe_job import (  # noqa: E402
    RECEIPT_LOGICAL_PATH,
    validate_btc_external_runtime_observe_receipt,
)


CANONICAL_MAIN_ROOT = Path(r"D:\vibe coding\Obsidian\量化系统\agent-")
CONTRACT_RELATIVE_PATH = Path(
    "config/btc_canonical_observe_task_contract.json"
)
CONTRACT_SCHEMA_VERSION = "btc_canonical_observe_task_contract_v1"
PROTECTED_SOURCE_PATHS = (
    "scripts/run_btc_canonical_observe_task.ps1",
    "scripts/run_btc_canonical_observe_task.py",
    "config/btc_canonical_observe_task_contract.json",
    "schemas/btc_canonical_observe_task_contract.schema.json",
    "scripts/run_btc_external_runtime_observe_job.py",
    "quant_crypto/application/btc_shared_observation_inputs.py",
    "quant_crypto/adapters/btc_runtime_artifact_store.py",
)
ALLOWED_CHILD_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUTF8": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
TASK_PATH = "\\QuantSystem\\BTC\\"
TASK_NAME = "Quant_BTC_Canonical_Observe_Only"
_FULL_HEAD = re.compile(r"^[0-9a-f]{40}$")
_FULL_HASH = re.compile(r"^[0-9a-f]{64}$")
_GIT_SPEC = re.compile(
    r"^([0-9a-f]{40}):(\.agent/data_manifests/.+\.json)$"
)
_FORBIDDEN_ENV_NAME = re.compile(
    r"(api[_-]?key|secret|token|passphrase|credential|proxy|"
    r"broker|paper|live|order|okx|binance)",
    re.IGNORECASE,
)


class BTCCanonicalObserveTaskError(RuntimeError):
    """Raised before the canonical receipt can be safely published."""


@dataclass(frozen=True)
class LaunchRequest:
    expected_main_head: str
    python_path: Path
    git_path: Path
    expected_git_sha256: str
    runtime_root: Path
    candidate_runtime_root: Path
    shared_root: Path
    retired_runtime_root: Path
    public_swap_manifest_git_spec: str
    l2_manifest_git_spec: str
    launcher_path: Path
    core_path: Path


@dataclass(frozen=True)
class MainSnapshot:
    root: Path
    head: str
    worktree_head: str
    symbolic_ref: str
    all_worktree_roots: tuple[Path, ...]
    repository_identity: str


def run_btc_canonical_observe_task(
    request: LaunchRequest,
    *,
    canonical_main_root: Path = CANONICAL_MAIN_ROOT,
    contract_path: Path | None = None,
    environment: Mapping[str, str] | None = None,
    after_inner_hook: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Run the inner observe CLI in staging and atomically publish on success."""

    values = os.environ if environment is None else environment
    _reject_sensitive_environment(values)
    _validate_expected_head(request.expected_main_head)
    git_path = _validate_git_path(
        request.git_path,
        expected_sha256=request.expected_git_sha256,
    )

    canonical = _strict_directory(
        canonical_main_root,
        "btc_canonical_observe_main_root_invalid",
    )
    first = _validate_canonical_main(
        canonical,
        request.expected_main_head,
        git_path,
        request.expected_git_sha256,
    )
    _validate_launcher_paths(
        canonical=canonical,
        launcher_path=request.launcher_path,
        core_path=request.core_path,
    )
    _validate_source_state(
        canonical,
        request.expected_main_head,
        git_path,
        request.expected_git_sha256,
    )

    effective_contract_path = (
        contract_path
        if contract_path is not None
        else canonical / CONTRACT_RELATIVE_PATH
    )
    contract = _load_and_validate_contract(
        effective_contract_path,
        canonical=canonical,
    )
    _validate_git_spec(
        canonical,
        request.public_swap_manifest_git_spec,
        git_path,
        request.expected_git_sha256,
    )
    _validate_git_spec(
        canonical,
        request.l2_manifest_git_spec,
        git_path,
        request.expected_git_sha256,
    )
    python_path = _validate_python_path(
        request.python_path,
        worktree_roots=first.all_worktree_roots,
    )

    shared = _strict_non_reparse_directory(
        request.shared_root,
        "btc_canonical_observe_shared_root_invalid",
    )
    retired = _absolute_lexical_path(
        request.retired_runtime_root,
        "btc_canonical_observe_retired_root_must_be_absolute",
    )
    if retired.exists():
        _reject_reparse_chain(retired)
    runtime = _strict_non_reparse_directory(
        request.runtime_root,
        "btc_canonical_observe_runtime_root_invalid",
    )
    candidate = _strict_non_reparse_directory(
        request.candidate_runtime_root,
        "btc_canonical_observe_candidate_root_invalid",
    )
    _validate_root_separation(
        canonical=canonical,
        runtime=runtime,
        candidate=candidate,
        shared=shared,
        retired=retired,
        worktree_roots=first.all_worktree_roots,
    )

    final_writer = BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=canonical,
        environment={ENVIRONMENT_VARIABLE: str(runtime)},
        repository_identity=first.repository_identity,
        worktree_roots=first.all_worktree_roots,
    )
    candidate_writer = BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=canonical,
        environment={ENVIRONMENT_VARIABLE: str(candidate)},
        repository_identity=first.repository_identity,
        worktree_roots=first.all_worktree_roots,
    )
    _validate_preprovisioned_receipt_parent(
        final_writer,
        require_receipt_absent=False,
    )
    _validate_preprovisioned_receipt_parent(
        candidate_writer,
        require_receipt_absent=True,
    )

    inner_script = canonical.joinpath(
        *PurePosixPath(contract["inner_contract"]["script"]).parts
    )
    child_environment = {
        ENVIRONMENT_VARIABLE: str(candidate),
        **ALLOWED_CHILD_ENVIRONMENT,
    }
    completed = subprocess.run(
        [
            str(python_path),
            str(inner_script),
            "--repo-root",
            str(canonical),
            "--shared-root",
            str(shared),
            "--public-swap-manifest-git-spec",
            request.public_swap_manifest_git_spec,
            "--l2-manifest-git-spec",
            request.l2_manifest_git_spec,
            "--expected-source-head",
            request.expected_main_head,
            "--repository-identity",
            first.repository_identity,
            *[
                item
                for root in first.all_worktree_roots
                for item in ("--worktree-root", str(root))
            ],
            "--git-executable",
            str(git_path),
            "--git-executable-sha256",
            request.expected_git_sha256,
        ],
        cwd=canonical,
        env=child_environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if completed.returncode != 2:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_inner_exit_invalid:"
            f"returncode={completed.returncode}"
        )

    candidate_receipt = candidate_writer.read_json(RECEIPT_LOGICAL_PATH)
    _validate_candidate_receipt(
        candidate_receipt,
        expected_head=request.expected_main_head,
        public_swap_manifest_git_spec=(
            request.public_swap_manifest_git_spec
        ),
        l2_manifest_git_spec=request.l2_manifest_git_spec,
    )

    if after_inner_hook is not None:
        after_inner_hook()

    second = _validate_canonical_main(
        canonical,
        request.expected_main_head,
        git_path,
        request.expected_git_sha256,
    )
    _validate_source_state(
        canonical,
        request.expected_main_head,
        git_path,
        request.expected_git_sha256,
    )
    if second != first:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_main_snapshot_drift"
        )

    with final_writer.exclusive() as session:
        third = _validate_canonical_main(
            canonical,
            request.expected_main_head,
            git_path,
            request.expected_git_sha256,
        )
        _validate_source_state(
            canonical,
            request.expected_main_head,
            git_path,
            request.expected_git_sha256,
        )
        if third != first:
            raise BTCCanonicalObserveTaskError(
                "btc_canonical_observe_main_snapshot_drift"
            )
        session.write_json_atomic(
            RECEIPT_LOGICAL_PATH,
            candidate_receipt,
        )

    published_receipt = final_writer.read_json(RECEIPT_LOGICAL_PATH)
    _validate_candidate_receipt(
        published_receipt,
        expected_head=request.expected_main_head,
        public_swap_manifest_git_spec=(
            request.public_swap_manifest_git_spec
        ),
        l2_manifest_git_spec=request.l2_manifest_git_spec,
    )
    if published_receipt != candidate_receipt:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_publish_readback_mismatch"
        )
    return {
        "schema_version": "btc_canonical_observe_task_result_v1",
        "infrastructure_status": "success",
        "gate_status": "blocked_fail_closed",
        "task_registration_performed": False,
        "source_head": request.expected_main_head,
        "manifest_git_specs": {
            "public_swap": request.public_swap_manifest_git_spec,
            "l2": request.l2_manifest_git_spec,
        },
        "all_files_verified": True,
        "consumer_read_only": True,
        "promotion_eligible": False,
        "paper_or_live_allowed": False,
        "safety": dict(published_receipt["safety"]),
    }


def _validate_expected_head(value: str) -> None:
    if _FULL_HEAD.fullmatch(value) is None:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_expected_main_head_invalid"
        )


def _validate_canonical_main(
    canonical: Path,
    expected_head: str,
    git_path: Path,
    expected_git_sha256: str,
) -> MainSnapshot:
    entries = _parse_worktrees(
        _git(
            git_path,
            expected_git_sha256,
            canonical,
            "worktree",
            "list",
            "--porcelain",
        )
    )
    main_entries = [
        entry
        for entry in entries
        if entry.get("branch") == "refs/heads/main"
    ]
    if len(main_entries) != 1:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_main_worktree_not_unique"
        )
    main_entry = main_entries[0]
    observed_root = _strict_directory(
        Path(main_entry["worktree"]),
        "btc_canonical_observe_main_worktree_invalid",
    )
    if _normalized(observed_root) != _normalized(canonical):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_main_worktree_path_mismatch"
        )
    worktree_head = str(main_entry.get("HEAD", ""))
    symbolic_ref = _git(
        git_path,
        expected_git_sha256,
        canonical,
        "symbolic-ref",
        "--quiet",
        "HEAD",
    )
    head = _git(
        git_path,
        expected_git_sha256,
        canonical,
        "rev-parse",
        "HEAD",
    )
    main_ref = _git(
        git_path,
        expected_git_sha256,
        canonical,
        "rev-parse",
        "refs/heads/main",
    )
    values = (worktree_head, head, main_ref, expected_head)
    if (
        symbolic_ref != "refs/heads/main"
        or any(_FULL_HEAD.fullmatch(item) is None for item in values)
        or len(set(values)) != 1
    ):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_main_binding_mismatch"
        )
    roots = tuple(
        _strict_directory(
            Path(entry["worktree"]),
            "btc_canonical_observe_registered_worktree_invalid",
        )
        for entry in entries
    )
    return MainSnapshot(
        root=canonical,
        head=head,
        worktree_head=worktree_head,
        symbolic_ref=symbolic_ref,
        all_worktree_roots=roots,
        repository_identity=_repository_identity(
            canonical,
            git_path,
            expected_git_sha256,
        ),
    )


def _parse_worktrees(output: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*output.splitlines(), ""]:
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, separator, value = line.partition(" ")
        current[key] = value if separator else ""
    if not entries or any("worktree" not in entry for entry in entries):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_worktree_list_invalid"
        )
    return entries


def _validate_launcher_paths(
    *,
    canonical: Path,
    launcher_path: Path,
    core_path: Path,
) -> None:
    expected_launcher = (
        canonical / "scripts/run_btc_canonical_observe_task.ps1"
    ).resolve(strict=True)
    expected_core = (
        canonical / "scripts/run_btc_canonical_observe_task.py"
    ).resolve(strict=True)
    supplied_launcher = launcher_path.resolve(strict=True)
    supplied_core = core_path.resolve(strict=True)
    if _normalized(supplied_launcher) != _normalized(expected_launcher):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_launcher_path_mismatch"
        )
    if _normalized(supplied_core) != _normalized(expected_core):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_core_path_mismatch"
        )


def _validate_source_state(
    repo_root: Path,
    expected_head: str,
    git_path: Path,
    expected_git_sha256: str,
) -> None:
    status = _git(
        git_path,
        expected_git_sha256,
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *PROTECTED_SOURCE_PATHS,
    )
    if status:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_protected_source_dirty"
        )
    for relative in PROTECTED_SOURCE_PATHS:
        working = repo_root.joinpath(
            *PurePosixPath(relative).parts
        )
        if not working.is_file():
            raise BTCCanonicalObserveTaskError(
                "btc_canonical_observe_protected_source_missing"
            )
        working_object = _git(
            git_path,
            expected_git_sha256,
            repo_root,
            "hash-object",
            "--path",
            relative,
            str(working),
        )
        committed_object = _git(
            git_path,
            expected_git_sha256,
            repo_root,
            "rev-parse",
            f"{expected_head}:{relative}",
        )
        if working_object != committed_object:
            raise BTCCanonicalObserveTaskError(
                "btc_canonical_observe_committed_blob_mismatch:"
                + relative
            )


def _load_and_validate_contract(
    path: Path,
    *,
    canonical: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_contract_unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_contract_not_object"
        )
    expected_top = {
        "schema_version",
        "canonical_main_root",
        "task_design",
        "protected_source_paths",
        "allowed_child_environment",
        "git_contract",
        "legacy_runner_names",
        "inner_contract",
    }
    task = payload.get("task_design")
    inner = payload.get("inner_contract")
    canonical_from_contract = Path(
        str(payload.get("canonical_main_root", ""))
    )
    valid = (
        set(payload) == expected_top
        and payload.get("schema_version") == CONTRACT_SCHEMA_VERSION
        and canonical_from_contract.is_absolute()
        and _normalized(canonical_from_contract)
        == _normalized(canonical)
        and payload.get("protected_source_paths")
        == list(PROTECTED_SOURCE_PATHS)
        and payload.get("allowed_child_environment")
        == {
            ENVIRONMENT_VARIABLE: "explicit_candidate_root",
            **ALLOWED_CHILD_ENVIRONMENT,
        }
        and payload.get("git_contract")
        == {
            "executable": str(APPROVED_GIT_EXECUTABLE),
            "sha256": APPROVED_GIT_EXECUTABLE_SHA256,
            "path_lookup_allowed": False,
        }
        and payload.get("legacy_runner_names")
        == ["Invoke-BtcResearchJob.ps1"]
        and isinstance(task, dict)
        and task
        == {
            "task_path": TASK_PATH,
            "task_name": TASK_NAME,
            "enabled": False,
            "registration_allowed": False,
            "action_count": 1,
            "trigger_count": 1,
            "execution_policy_bypass": False,
            "working_directory": str(canonical),
        }
        and isinstance(inner, dict)
        and inner
        == {
            "script": "scripts/run_btc_external_runtime_observe_job.py",
            "expected_exit_code": 2,
            "expected_status": "blocked_fail_closed",
            "receipt_logical_path": RECEIPT_LOGICAL_PATH.as_posix(),
            "promotion_eligible": False,
            "paper_or_live_allowed": False,
        }
    )
    if not valid:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_contract_invalid"
        )
    return payload


def _validate_git_spec(
    repo_root: Path,
    value: str,
    git_path: Path,
    expected_git_sha256: str,
) -> None:
    match = _GIT_SPEC.fullmatch(value)
    if match is None or "\\" in value:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_manifest_git_spec_invalid"
        )
    commit, relative = match.groups()
    pure = PurePosixPath(relative)
    if (
        pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(
            "latest" in part.casefold()
            or "pointer" in part.casefold()
            for part in pure.parts
        )
    ):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_manifest_git_spec_invalid"
        )
    if (
        _git(
            git_path,
            expected_git_sha256,
            repo_root,
            "cat-file",
            "-t",
            commit,
        )
        != "commit"
    ):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_manifest_commit_invalid"
        )
    _git_bytes(
        git_path,
        expected_git_sha256,
        repo_root,
        "show",
        value,
    )


def _validate_python_path(
    path: Path,
    *,
    worktree_roots: Sequence[Path],
) -> Path:
    if not path.is_absolute():
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_python_path_must_be_absolute"
        )
    _reject_reparse_chain(path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_python_path_invalid"
        ) from exc
    if (
        not resolved.is_file()
        or not resolved.name.casefold().startswith("python")
        or resolved.suffix.casefold() != ".exe"
        or any(_paths_overlap(resolved, root) for root in worktree_roots)
    ):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_python_path_invalid"
        )
    return resolved


def _validate_git_path(
    path: Path,
    *,
    expected_sha256: str,
) -> Path:
    try:
        return validate_btc_observe_git_executable(
            path,
            expected_sha256=expected_sha256,
        )
    except BTCSharedObservationInputsError as exc:
        raise BTCCanonicalObserveTaskError(str(exc)) from exc


def _repository_identity(
    repo_root: Path,
    git_path: Path,
    expected_git_sha256: str,
) -> str:
    raw = _git(
        git_path,
        expected_git_sha256,
        repo_root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = repo_root / common_dir
    canonical = str(common_dir.resolve(strict=True)).replace(
        "\\",
        "/",
    ).casefold()
    digest = hashlib.sha256(
        (
            REPOSITORY_IDENTITY_SCHEMA_VERSION
            + "\0"
            + canonical
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _validate_root_separation(
    *,
    canonical: Path,
    runtime: Path,
    candidate: Path,
    shared: Path,
    retired: Path,
    worktree_roots: Sequence[Path],
) -> None:
    comparisons = (
        (runtime, candidate),
        (runtime, shared),
        (runtime, retired),
        (runtime, canonical),
        (candidate, shared),
        (candidate, retired),
        (candidate, canonical),
    )
    if any(_paths_overlap(left, right) for left, right in comparisons):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_runtime_root_overlap"
        )
    if any(
        _paths_overlap(root, worktree)
        for root in (runtime, candidate)
        for worktree in worktree_roots
    ):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_runtime_root_overlap"
        )


def _validate_preprovisioned_receipt_parent(
    writer: BTCRuntimeArtifactWriter,
    *,
    require_receipt_absent: bool,
) -> None:
    receipt_path = writer.resolve(RECEIPT_LOGICAL_PATH)
    parent = receipt_path.parent
    _reject_reparse_chain(parent)
    if not parent.is_dir():
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_receipt_parent_not_preprovisioned"
        )
    if require_receipt_absent and receipt_path.exists():
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_candidate_receipt_not_unique"
        )
    if require_receipt_absent:
        allowed = {
            OWNER_MARKER_NAME,
            parent.relative_to(writer.artifact_root).parts[0],
        }
        observed = {item.name for item in writer.artifact_root.iterdir()}
        if observed != allowed or any(parent.iterdir()):
            raise BTCCanonicalObserveTaskError(
                "btc_canonical_observe_candidate_root_not_empty"
            )


def _validate_candidate_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_head: str,
    public_swap_manifest_git_spec: str,
    l2_manifest_git_spec: str,
) -> None:
    try:
        validate_btc_external_runtime_observe_receipt(receipt)
    except Exception as exc:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_inner_receipt_invalid"
        ) from exc
    if receipt.get("source_head") != expected_head:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_receipt_source_head_mismatch"
        )
    if receipt.get("manifest_git_specs") != {
        "public_swap": public_swap_manifest_git_spec,
        "l2": l2_manifest_git_spec,
    }:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_receipt_pins_mismatch"
        )
    if receipt.get("all_files_verified") is not True:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_receipt_files_not_verified"
        )
    inputs = receipt.get("inputs")
    public = inputs.get("public_swap") if isinstance(inputs, Mapping) else None
    l2 = inputs.get("l2") if isinstance(inputs, Mapping) else None
    if not isinstance(public, Mapping) or not isinstance(l2, Mapping):
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_receipt_inputs_invalid"
        )
    public_valid = (
        public.get("status") == "resolved_research_only_input"
        and public.get("dataset_id") == PUBLIC_SWAP_DATASET_ID
        and public.get("input_classification") == "research_only_input"
        and public.get("files_verified") is True
        and _FULL_HASH.fullmatch(
            str(public.get("raw_committed_manifest_sha256", ""))
        )
        is not None
        and _FULL_HASH.fullmatch(str(public.get("aggregate_sha256", "")))
        is not None
    )
    source_receipt = l2.get("source_receipt")
    l2_valid = (
        l2.get("status") == "resolved_blocked_evidence_only"
        and l2.get("dataset_id") == L2_DATASET_ID
        and l2.get("input_classification") == "blocked_evidence_only"
        and l2.get("quality_status") == "blocked"
        and l2.get("files_verified") is True
        and _FULL_HASH.fullmatch(
            str(l2.get("raw_committed_manifest_sha256", ""))
        )
        is not None
        and _FULL_HASH.fullmatch(str(l2.get("aggregate_sha256", "")))
        is not None
        and isinstance(source_receipt, Mapping)
        and source_receipt.get("blocked_evidence_only") is True
        and source_receipt.get("data_samples_accepted") is False
    )
    if not public_valid or not l2_valid:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_receipt_classification_invalid"
        )


def _reject_sensitive_environment(
    environment: Mapping[str, str],
) -> None:
    forbidden = sorted(
        name for name in environment if _FORBIDDEN_ENV_NAME.search(name)
    )
    if forbidden:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_forbidden_environment_present:"
            + ",".join(forbidden)
        )


def _strict_directory(path: Path, error: str) -> Path:
    if not path.is_absolute():
        raise BTCCanonicalObserveTaskError(error)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BTCCanonicalObserveTaskError(error) from exc
    if not resolved.is_dir():
        raise BTCCanonicalObserveTaskError(error)
    return resolved


def _strict_non_reparse_directory(path: Path, error: str) -> Path:
    if not path.is_absolute():
        raise BTCCanonicalObserveTaskError(error)
    _reject_reparse_chain(path)
    resolved = _strict_directory(path, error)
    _reject_reparse_chain(resolved)
    return resolved


def _absolute_lexical_path(path: Path, error: str) -> Path:
    if not path.is_absolute():
        raise BTCCanonicalObserveTaskError(error)
    return Path(os.path.abspath(path))


def _reject_reparse_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise BTCCanonicalObserveTaskError(
                "btc_canonical_observe_reparse_path_rejected"
            )


def _is_reparse_point(path: Path) -> bool:
    try:
        details = os.lstat(path)
    except OSError:
        return False
    attributes = int(getattr(details, "st_file_attributes", 0))
    return path.is_symlink() or bool(
        attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    left_value = _normalized(left)
    right_value = _normalized(right)
    separator = os.sep.casefold()
    return (
        left_value == right_value
        or left_value.startswith(right_value.rstrip(separator) + separator)
        or right_value.startswith(left_value.rstrip(separator) + separator)
    )


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path)).casefold()


def _git(
    git_path: Path,
    expected_git_sha256: str,
    repo_root: Path,
    *args: str,
) -> str:
    return _git_bytes(
        git_path,
        expected_git_sha256,
        repo_root,
        *args,
    ).decode(
        "utf-8",
        errors="replace",
    ).strip()


def _git_bytes(
    git_path: Path,
    expected_git_sha256: str,
    repo_root: Path,
    *args: str,
) -> bytes:
    validated_git = _validate_git_path(
        git_path,
        expected_sha256=expected_git_sha256,
    )
    try:
        completed = subprocess.run(
            [str(validated_git), *args],
            cwd=repo_root,
            env={
                ENVIRONMENT_VARIABLE: "",
                **ALLOWED_CHILD_ENVIRONMENT,
            },
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_git_command_failed"
        ) from exc
    if completed.returncode != 0:
        raise BTCCanonicalObserveTaskError(
            "btc_canonical_observe_git_command_failed:"
            + (args[0] if args else "unknown")
        )
    return completed.stdout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the canonical committed-main BTC observe-only task "
            "without registering or enabling Scheduled Tasks."
        )
    )
    parser.add_argument("--expected-main-head", required=True)
    parser.add_argument("--python-path", type=Path, required=True)
    parser.add_argument("--git-path", type=Path, required=True)
    parser.add_argument("--expected-git-sha256", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--candidate-runtime-root", type=Path, required=True)
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument("--retired-runtime-root", type=Path, required=True)
    parser.add_argument(
        "--public-swap-manifest-git-spec",
        required=True,
    )
    parser.add_argument("--l2-manifest-git-spec", required=True)
    parser.add_argument("--launcher-path", type=Path, required=True)
    parser.add_argument("--core-path", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = LaunchRequest(
        expected_main_head=args.expected_main_head,
        python_path=args.python_path,
        git_path=args.git_path,
        expected_git_sha256=args.expected_git_sha256,
        runtime_root=args.runtime_root,
        candidate_runtime_root=args.candidate_runtime_root,
        shared_root=args.shared_root,
        retired_runtime_root=args.retired_runtime_root,
        public_swap_manifest_git_spec=(
            args.public_swap_manifest_git_spec
        ),
        l2_manifest_git_spec=args.l2_manifest_git_spec,
        launcher_path=args.launcher_path,
        core_path=args.core_path,
    )
    try:
        if _normalized(args.core_path) != _normalized(Path(__file__)):
            raise BTCCanonicalObserveTaskError(
                "btc_canonical_observe_running_core_path_mismatch"
            )
        output = run_btc_canonical_observe_task(request)
        exit_code = 0
    except (
        BTCCanonicalObserveTaskError,
        BTCSharedObservationInputsError,
        BTCRuntimeArtifactStoreError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        output = {
            "schema_version": "btc_canonical_observe_task_result_v1",
            "infrastructure_status": "blocked_fail_closed",
            "gate_status": "blocked_fail_closed",
            "receipt_published": False,
            "error": str(exc),
            "task_registration_performed": False,
            "promotion_eligible": False,
            "paper_or_live_allowed": False,
        }
        exit_code = 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_CHILD_ENVIRONMENT",
    "APPROVED_GIT_EXECUTABLE",
    "APPROVED_GIT_EXECUTABLE_SHA256",
    "BTCCanonicalObserveTaskError",
    "CANONICAL_MAIN_ROOT",
    "CONTRACT_SCHEMA_VERSION",
    "LaunchRequest",
    "PROTECTED_SOURCE_PATHS",
    "TASK_NAME",
    "TASK_PATH",
    "run_btc_canonical_observe_task",
]
