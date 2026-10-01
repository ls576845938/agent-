"""Strict read-only consumption of immutable BTC observation inputs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any, Mapping

from tools.agent_governance.shared_data import (
    SharedDataError,
    resolve_manifest_payload,
)


PUBLIC_SWAP_DATASET_ID = "btc-okx-public-swap-research-bundle"
L2_DATASET_ID = "btc-okx-timestamp-aligned-public-l2-history"
L2_BLOCKED_RECEIPT_SCHEMA = "btc_okx_l2_rejected_source_receipt_v1"
L2_CAPTURE_REPORT_SCHEMA = (
    "btc_okx_timestamp_aligned_l2_capture_report_v1"
)
GIT_SPEC_PATTERN = re.compile(
    r"^([0-9a-f]{40}):(\.agent/data_manifests/.+\.json)$"
)
GIT_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
APPROVED_GIT_EXECUTABLE = Path(r"C:\Program Files\Git\cmd\git.exe")
APPROVED_GIT_EXECUTABLE_SHA256 = (
    "da240fe9bc24895b3e04150a4990b8a6ff329ecabcd8f19684c2cc310da5ef3f"
)


class BTCSharedObservationInputsError(RuntimeError):
    """Raised when a committed immutable input cannot be consumed safely."""


def consume_btc_shared_observation_inputs(
    *,
    repo_root: Path,
    shared_root: Path,
    public_swap_manifest_git_spec: str,
    l2_manifest_git_spec: str,
    git_executable: Path,
    git_executable_sha256: str,
) -> dict[str, Any]:
    """Resolve both named manifests with full hashes and preserve all blockers."""

    if not repo_root.is_absolute():
        raise BTCSharedObservationInputsError(
            "btc_observe_repo_root_must_be_absolute"
        )
    if not shared_root.is_absolute():
        raise BTCSharedObservationInputsError(
            "btc_observe_shared_root_must_be_absolute"
        )
    validated_git = validate_btc_observe_git_executable(
        git_executable,
        expected_sha256=git_executable_sha256,
    )

    inputs: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    preserved_blockers: list[str] = []
    preserved_known_gaps: list[str] = []

    specifications = (
        (
            "public_swap",
            public_swap_manifest_git_spec,
            PUBLIC_SWAP_DATASET_ID,
            "research_only_input",
        ),
        (
            "l2",
            l2_manifest_git_spec,
            L2_DATASET_ID,
            "blocked_evidence_only",
        ),
    )
    for label, git_spec, expected_dataset_id, input_classification in specifications:
        try:
            consumed = _consume_one(
                repo_root=repo_root,
                shared_root=shared_root,
                git_spec=git_spec,
                expected_dataset_id=expected_dataset_id,
                input_classification=input_classification,
                require_blocked_receipt=label == "l2",
                git_executable=validated_git,
                git_executable_sha256=git_executable_sha256,
            )
        except (BTCSharedObservationInputsError, SharedDataError) as exc:
            inputs[label] = {
                "status": "blocked_fail_closed",
                "manifest_git_spec": git_spec,
                "expected_dataset_id": expected_dataset_id,
                "input_classification": input_classification,
                "consumer_read_only": True,
                "error": str(exc),
            }
            errors.append(f"{label}:{exc}")
            continue
        inputs[label] = consumed
        preserved_blockers.extend(consumed["blockers"])
        preserved_known_gaps.extend(consumed["known_gaps"])

    policy_blockers = [
        "btc_external_runtime_observe_consumer_always_blocked",
        "btc_external_runtime_observe_not_dataready",
        "btc_external_runtime_observe_not_research_ready",
        "btc_external_runtime_observe_not_backtest_ready",
        "btc_external_runtime_observe_not_promotion_evidence",
        "btc_l2_input_blocked_evidence_only",
    ]
    return {
        "inputs": inputs,
        "input_errors": _dedupe(errors),
        "preserved_input_blockers": _dedupe(preserved_blockers),
        "preserved_known_gaps": _dedupe(preserved_known_gaps),
        "blockers": _dedupe(
            [
                *errors,
                *preserved_blockers,
                *preserved_known_gaps,
                *policy_blockers,
            ]
        ),
        "consumer_read_only": True,
        "all_files_verified": not errors and len(inputs) == 2,
    }


def _consume_one(
    *,
    repo_root: Path,
    shared_root: Path,
    git_spec: str,
    expected_dataset_id: str,
    input_classification: str,
    require_blocked_receipt: bool,
    git_executable: Path,
    git_executable_sha256: str,
) -> dict[str, Any]:
    manifest_commit, manifest_path, raw, manifest = _load_committed_manifest(
        repo_root=repo_root,
        git_spec=git_spec,
        git_executable=git_executable,
        git_executable_sha256=git_executable_sha256,
    )
    dataset_id = str(manifest.get("dataset_id", ""))
    if dataset_id != expected_dataset_id:
        raise BTCSharedObservationInputsError(
            "btc_observe_manifest_dataset_mismatch:"
            f"expected={expected_dataset_id}:observed={dataset_id}"
        )
    if manifest.get("readiness_class") != "quality_checked":
        raise BTCSharedObservationInputsError(
            "btc_observe_manifest_readiness_must_be_quality_checked"
        )
    if require_blocked_receipt:
        _validate_l2_manifest_contract(manifest)

    resolved_root = resolve_manifest_payload(
        manifest,
        shared_root=shared_root,
        verify_files=True,
    )
    source_receipt = (
        _validate_l2_source_receipt(
            manifest=manifest,
            resolved_root=resolved_root,
        )
        if require_blocked_receipt
        else None
    )
    return {
        "status": (
            "resolved_blocked_evidence_only"
            if require_blocked_receipt
            else "resolved_research_only_input"
        ),
        "manifest_git_spec": git_spec,
        "manifest_commit": manifest_commit,
        "manifest_path": manifest_path,
        "producer_commit": str(manifest["producer_commit"]),
        "dataset_id": dataset_id,
        "dataset_version": str(manifest["dataset_version"]),
        "raw_committed_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "aggregate_sha256": str(manifest["aggregate_sha256"]),
        "readiness_class": str(manifest["readiness_class"]),
        "quality_status": str(manifest["quality_status"]),
        "input_classification": input_classification,
        "blockers": list(manifest["blockers"]),
        "known_gaps": list(manifest["known_gaps"]),
        "coverage": dict(manifest["coverage"]),
        "file_count": int(manifest["file_count"]),
        "files_verified": True,
        "source_receipt": source_receipt,
        "consumer_read_only": True,
    }


def _load_committed_manifest(
    *,
    repo_root: Path,
    git_spec: str,
    git_executable: Path,
    git_executable_sha256: str,
) -> tuple[str, str, bytes, dict[str, Any]]:
    match = GIT_SPEC_PATTERN.fullmatch(git_spec)
    if match is None:
        raise BTCSharedObservationInputsError(
            f"btc_observe_manifest_git_spec_invalid:{git_spec}"
        )
    manifest_commit, manifest_path = match.groups()
    pure_path = PurePosixPath(manifest_path)
    if (
        pure_path.as_posix() != manifest_path
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or any(
            "latest" in part.casefold()
            or "pointer" in part.casefold()
            for part in pure_path.parts
        )
    ):
        raise BTCSharedObservationInputsError(
            f"btc_observe_manifest_git_spec_invalid:{git_spec}"
        )

    object_type = _git_bytes(
        git_executable,
        git_executable_sha256,
        repo_root,
        "cat-file",
        "-t",
        manifest_commit,
        error="btc_observe_manifest_commit_unavailable",
    ).decode("ascii", errors="replace").strip()
    if object_type != "commit":
        raise BTCSharedObservationInputsError(
            "btc_observe_manifest_commit_not_commit"
        )
    raw = _git_bytes(
        git_executable,
        git_executable_sha256,
        repo_root,
        "show",
        f"{manifest_commit}:{manifest_path}",
        error="btc_observe_manifest_git_read_failed",
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCSharedObservationInputsError(
            "btc_observe_manifest_json_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise BTCSharedObservationInputsError(
            "btc_observe_manifest_not_object"
        )
    return manifest_commit, manifest_path, raw, payload


def _validate_l2_manifest_contract(manifest: Mapping[str, Any]) -> None:
    if manifest.get("quality_status") != "blocked":
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_manifest_must_be_blocked"
        )
    if manifest.get("data_schema") != L2_BLOCKED_RECEIPT_SCHEMA:
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_manifest_schema_invalid"
        )
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 1:
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_manifest_single_source_receipt_required"
        )
    relative = str(files[0].get("path", "")) if isinstance(files[0], Mapping) else ""
    if (
        not relative.startswith("source_receipt/")
        or not relative.endswith(".json")
    ):
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_manifest_source_receipt_path_invalid"
        )
    blockers = manifest.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_manifest_blockers_required"
        )


def _validate_l2_source_receipt(
    *,
    manifest: Mapping[str, Any],
    resolved_root: Path,
) -> dict[str, Any]:
    file_entry = manifest["files"][0]
    relative = str(file_entry["path"])
    path = resolved_root.joinpath(*PurePosixPath(relative).parts)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_source_receipt_unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_source_receipt_not_object"
        )
    status = str(payload.get("status", ""))
    decision = str(payload.get("decision", ""))
    receipt_blockers = payload.get("blockers")
    blockers_valid = (
        isinstance(receipt_blockers, list)
        and bool(receipt_blockers)
        and all(
            isinstance(item, str) and bool(item.strip())
            for item in receipt_blockers
        )
    )
    rejected_empty_capture = status == "rejected"
    if rejected_empty_capture:
        completed_sample_count = payload.get("completed_sample_count")
        files = payload.get("files")
        rejected_contract_valid = (
            payload.get("schema_version") == L2_CAPTURE_REPORT_SCHEMA
            and "decision" not in payload
            and blockers_valid
            and type(completed_sample_count) is int
            and completed_sample_count == 0
            and isinstance(files, list)
            and not files
        )
        if not rejected_contract_valid:
            raise BTCSharedObservationInputsError(
                "btc_observe_l2_source_receipt_not_blocked_evidence"
            )
    elif (
        "blocked" not in f"{status} {decision}".casefold()
        or not blockers_valid
    ):
        raise BTCSharedObservationInputsError(
            "btc_observe_l2_source_receipt_not_blocked_evidence"
        )
    return {
        "relative_path": relative,
        "sha256": str(file_entry["sha256"]),
        "schema_version": str(payload.get("schema_version", "")),
        "status": status,
        "decision": decision,
        "blockers": list(receipt_blockers),
        "completed_sample_count": (
            0 if rejected_empty_capture else None
        ),
        "source_file_count": (
            0 if rejected_empty_capture else None
        ),
        "data_samples_accepted": False,
        "blocked_evidence_only": True,
    }


def validate_btc_observe_git_executable(
    path: Path,
    *,
    expected_sha256: str,
) -> Path:
    """Bind Git execution to one absolute, non-reparse, hashed executable."""

    if not path.is_absolute():
        raise BTCSharedObservationInputsError(
            "btc_observe_git_executable_must_be_absolute"
        )
    if GIT_SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise BTCSharedObservationInputsError(
            "btc_observe_git_executable_sha256_invalid"
        )
    if expected_sha256 != APPROVED_GIT_EXECUTABLE_SHA256:
        raise BTCSharedObservationInputsError(
            "btc_observe_git_executable_sha256_not_approved"
        )
    _reject_reparse_chain(path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BTCSharedObservationInputsError(
            "btc_observe_git_executable_invalid"
        ) from exc
    _reject_reparse_chain(resolved)
    lexical = Path(os.path.abspath(path))
    if (
        os.path.normcase(str(lexical)) != os.path.normcase(str(resolved))
        or os.path.normcase(str(resolved))
        != os.path.normcase(str(APPROVED_GIT_EXECUTABLE))
        or not resolved.is_file()
        or resolved.name.casefold() != "git.exe"
    ):
        raise BTCSharedObservationInputsError(
            "btc_observe_git_executable_invalid"
        )
    try:
        observed_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise BTCSharedObservationInputsError(
            "btc_observe_git_executable_unreadable"
        ) from exc
    if observed_sha256 != expected_sha256:
        raise BTCSharedObservationInputsError(
            "btc_observe_git_executable_sha256_mismatch"
        )
    return resolved


def _reject_reparse_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if not os.path.lexists(current):
            continue
        try:
            details = os.lstat(current)
        except OSError as exc:
            raise BTCSharedObservationInputsError(
                "btc_observe_git_executable_unreadable"
            ) from exc
        attributes = int(getattr(details, "st_file_attributes", 0))
        if current.is_symlink() or bool(
            attributes
            & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
        ):
            raise BTCSharedObservationInputsError(
                "btc_observe_git_executable_reparse_rejected"
            )


def _git_bytes(
    git_executable: Path,
    git_executable_sha256: str,
    repo_root: Path,
    *args: str,
    error: str,
) -> bytes:
    validated_git = validate_btc_observe_git_executable(
        git_executable,
        expected_sha256=git_executable_sha256,
    )
    try:
        completed = subprocess.run(
            [str(validated_git), *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise BTCSharedObservationInputsError(error) from exc
    if completed.returncode != 0:
        raise BTCSharedObservationInputsError(error)
    return completed.stdout


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "BTCSharedObservationInputsError",
    "APPROVED_GIT_EXECUTABLE",
    "APPROVED_GIT_EXECUTABLE_SHA256",
    "GIT_SPEC_PATTERN",
    "L2_CAPTURE_REPORT_SCHEMA",
    "L2_DATASET_ID",
    "PUBLIC_SWAP_DATASET_ID",
    "consume_btc_shared_observation_inputs",
    "validate_btc_observe_git_executable",
]
