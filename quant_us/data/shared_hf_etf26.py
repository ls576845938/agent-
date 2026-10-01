"""Read-only adapter for the committed HF ETF26 shared-data delivery."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


@dataclass(frozen=True)
class ResolvedHfEtf26Dataset:
    root: Path
    manifest_git_spec: str
    manifest: dict[str, Any]
    manifest_sha256: str
    qqq_path: Path
    qqq_sha256: str


def resolve_hf_etf26_dataset(
    *,
    repo_root: Path,
    handoff_event: str,
    expected_event_id: str,
    manifest_git_spec: str,
    expected_dataset_id: str,
    expected_dataset_version: str,
    expected_aggregate_sha256: str,
    symbol_file: str,
) -> ResolvedHfEtf26Dataset:
    """Validate the committed handoff and resolve immutable shared data.

    This adapter never searches another worktree and never accepts a local
    uncommitted manifest.  The manifest is read from the immutable Git spec and
    the shared-data resolver performs the publication/hash checks.
    """

    root = repo_root.resolve()
    event_path = (root / handoff_event).resolve()
    _require_within(root, event_path, "handoff_event_outside_repo")
    if not event_path.is_file():
        raise ValueError("hf_etf26_committed_handoff_missing")

    validation = _run_json(
        [
            sys.executable,
            str(root / "tools/agent_governance/handoff.py"),
            "--repo-root",
            str(root),
            "validate",
            "--input",
            str(event_path),
        ],
        cwd=root,
        error_code="hf_etf26_handoff_validation_failed",
    )
    if validation.get("status") != "valid" or validation.get("event_id") != expected_event_id:
        raise ValueError("hf_etf26_handoff_not_valid")

    manifest_bytes = _git_show(root, manifest_git_spec)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    _validate_manifest(
        manifest,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version=expected_dataset_version,
        expected_aggregate_sha256=expected_aggregate_sha256,
    )
    resolved = _run_json(
        [
            sys.executable,
            str(root / "tools/agent_governance/shared_data.py"),
            "--repo-root",
            str(root),
            "resolve",
            "--manifest-git-spec",
            manifest_git_spec,
        ],
        cwd=root,
        error_code="hf_etf26_immutable_resolve_failed",
    )
    if resolved.get("status") != "resolved" or resolved.get("consumer_read_only") is not True:
        raise ValueError("hf_etf26_resolver_not_read_only")

    dataset_root = Path(str(resolved.get("path", ""))).resolve()
    qqq_path = (dataset_root / symbol_file).resolve()
    _require_within(dataset_root, qqq_path, "hf_etf26_symbol_path_escape")
    file_entry = next(
        (item for item in manifest.get("files", []) if item.get("path") == symbol_file),
        None,
    )
    if not isinstance(file_entry, dict):
        raise ValueError("hf_etf26_qqq_manifest_entry_missing")
    expected_file_hash = str(file_entry.get("sha256", ""))
    if not qqq_path.is_file():
        raise ValueError("hf_etf26_qqq_file_missing")
    actual_file_hash = _sha256_file(qqq_path)
    if actual_file_hash != expected_file_hash:
        raise ValueError("hf_etf26_qqq_file_hash_mismatch")

    return ResolvedHfEtf26Dataset(
        root=dataset_root,
        manifest_git_spec=manifest_git_spec,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        qqq_path=qqq_path,
        qqq_sha256=actual_file_hash,
    )


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    expected_dataset_id: str,
    expected_dataset_version: str,
    expected_aggregate_sha256: str,
) -> None:
    checks = {
        "schema_version": "shared_dataset_manifest_v1",
        "dataset_id": expected_dataset_id,
        "dataset_version": expected_dataset_version,
        "readiness_class": "research_ready",
        "aggregate_sha256": expected_aggregate_sha256,
    }
    for key, expected in checks.items():
        if manifest.get(key) != expected:
            raise ValueError(f"hf_etf26_manifest_{key}_mismatch")
    guardrails = manifest.get("guardrails")
    if not isinstance(guardrails, dict) or guardrails.get("consumer_read_only") is not True:
        raise ValueError("hf_etf26_manifest_consumer_read_only_missing")


def _run_json(command: list[str], *, cwd: Path, error_code: str) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ValueError(error_code)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{error_code}:invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{error_code}:not_object")
    return payload


def _git_show(repo_root: Path, git_spec: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", git_spec],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError("hf_etf26_manifest_git_spec_unreadable")
    return completed.stdout


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_within(root: Path, path: Path, error_code: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(error_code) from exc
