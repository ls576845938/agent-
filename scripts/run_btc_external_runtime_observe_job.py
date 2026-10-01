#!/usr/bin/env python3
"""Consume named immutable BTC inputs and emit one blocked external receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.adapters.btc_runtime_artifact_store import (  # noqa: E402
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriter,
)
from quant_crypto.application.btc_shared_observation_inputs import (  # noqa: E402
    BTCSharedObservationInputsError,
    consume_btc_shared_observation_inputs,
    validate_btc_observe_git_executable,
)
from quant_crypto.monitoring.btc_artifact_source_identity import (  # noqa: E402
    BTCArtifactSourceIdentityError,
    validate_btc_artifact_source_identity,
)


RECEIPT_SCHEMA_VERSION = "btc_external_runtime_observe_receipt_v1"
RECEIPT_VERSION = 1
RECEIPT_LOGICAL_PATH = Path(
    "artifacts/btc_external_runtime_observe_job/"
    "btc_external_runtime_observe_receipt.json"
)
_FULL_HEAD = re.compile(r"^[0-9a-f]{40}$")
_SHORT_COMMIT = re.compile(r"^[0-9a-f]{12}$")
_SAFETY_FLAGS = {
    "network_accessed": False,
    "publish_attempted": False,
    "micro_live_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "private_endpoint_allowed": False,
    "order_endpoint_allowed": False,
    "broker_calls_allowed": False,
    "oms_calls_allowed": False,
    "real_order_submitted": False,
    "secret_accessed": False,
    "repo_write_allowed": False,
    "shared_data_write_allowed": False,
}


class BTCExternalRuntimeObserveJobError(RuntimeError):
    """Raised when the observe job cannot emit its external receipt."""


def run_btc_external_runtime_observe_job(
    *,
    repo_root: Path,
    shared_root: Path,
    public_swap_manifest_git_spec: str,
    l2_manifest_git_spec: str,
    expected_source_head: str,
    repository_identity: str,
    worktree_roots: tuple[Path, ...],
    git_executable: Path,
    git_executable_sha256: str,
    environment: Mapping[str, str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run offline, write exactly one external blocked receipt, and return it."""

    _validate_absolute_roots(
        repo_root=repo_root,
        shared_root=shared_root,
    )
    source_root = repo_root.resolve(strict=True)
    shared = shared_root.resolve(strict=True)
    if _FULL_HEAD.fullmatch(expected_source_head) is None:
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_expected_source_head_invalid"
        )
    if not worktree_roots or any(
        not root.is_absolute() for root in worktree_roots
    ):
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_worktree_roots_invalid"
        )
    resolved_worktree_roots = tuple(
        root.resolve(strict=True) for root in worktree_roots
    )
    validated_git = validate_btc_observe_git_executable(
        git_executable,
        expected_sha256=git_executable_sha256,
    )
    writer = BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=source_root,
        environment=environment,
        repository_identity=repository_identity,
        worktree_roots=resolved_worktree_roots,
    )
    _reject_artifact_shared_root_overlap(
        artifact_root=writer.artifact_root,
        shared_root=shared,
    )
    source_identity = {
        "source_head": expected_source_head,
        "commit": expected_source_head[:12],
    }
    validate_btc_artifact_source_identity(
        source_identity,
        expected_current_head=expected_source_head,
    )

    try:
        consumed = consume_btc_shared_observation_inputs(
            repo_root=source_root,
            shared_root=shared,
            public_swap_manifest_git_spec=public_swap_manifest_git_spec,
            l2_manifest_git_spec=l2_manifest_git_spec,
            git_executable=validated_git,
            git_executable_sha256=git_executable_sha256,
        )
    except Exception as exc:
        consumed = {
            "inputs": {},
            "input_errors": [
                "btc_external_runtime_observe_input_consumption_failed:"
                f"{type(exc).__name__}"
            ],
            "preserved_input_blockers": [],
            "preserved_known_gaps": [],
            "blockers": [
                "btc_external_runtime_observe_input_consumption_failed:"
                f"{type(exc).__name__}"
            ],
            "consumer_read_only": True,
            "all_files_verified": False,
        }

    receipt = _build_receipt(
        source_identity=source_identity,
        public_swap_manifest_git_spec=public_swap_manifest_git_spec,
        l2_manifest_git_spec=l2_manifest_git_spec,
        consumed=consumed,
        generated_at=generated_at,
    )
    validate_btc_external_runtime_observe_receipt(receipt)
    with writer.exclusive() as session:
        session.write_json_atomic(RECEIPT_LOGICAL_PATH, receipt)
    committed_receipt = writer.read_json(RECEIPT_LOGICAL_PATH)
    validate_btc_external_runtime_observe_receipt(committed_receipt)
    if committed_receipt != receipt:
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_readback_mismatch"
        )
    return receipt


def validate_btc_external_runtime_observe_receipt(
    receipt: Mapping[str, Any],
) -> None:
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_schema_invalid"
        )
    if receipt.get("receipt_version") != RECEIPT_VERSION:
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_version_invalid"
        )
    source_head = str(receipt.get("source_head", ""))
    commit = str(receipt.get("commit", ""))
    if (
        _FULL_HEAD.fullmatch(source_head) is None
        or _SHORT_COMMIT.fullmatch(commit) is None
        or commit != source_head[:12]
    ):
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_source_identity_invalid"
        )
    validate_btc_artifact_source_identity(
        receipt,
        expected_current_head=source_head,
    )
    if receipt.get("status") != "blocked_fail_closed":
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_status_invalid"
        )
    if receipt.get("consumer_read_only") is not True:
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_consumer_mode_invalid"
        )
    blockers = receipt.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_blockers_required"
        )
    safety = receipt.get("safety")
    if (
        not isinstance(safety, Mapping)
        or set(safety) != set(_SAFETY_FLAGS)
        or any(safety.get(key) is not False for key in _SAFETY_FLAGS)
    ):
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_safety_invalid"
        )
    inputs = receipt.get("inputs")
    if not isinstance(inputs, Mapping):
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_receipt_inputs_invalid"
        )
    serialized = json.dumps(dict(receipt), sort_keys=True)
    for forbidden in (
        '"dataready"',
        '"research_ready"',
        '"backtest_ready"',
        '"promotion_evidence_ready"',
    ):
        if forbidden in serialized.casefold():
            raise BTCExternalRuntimeObserveJobError(
                "btc_external_runtime_observe_receipt_readiness_escalation"
            )


def _build_receipt(
    *,
    source_identity: Mapping[str, str],
    public_swap_manifest_git_spec: str,
    l2_manifest_git_spec: str,
    consumed: Mapping[str, Any],
    generated_at: str | None,
) -> dict[str, Any]:
    blockers = _dedupe(
        [
            *[
                str(item)
                for item in consumed.get("blockers", [])
                if str(item)
            ],
            "btc_external_runtime_observe_job_exit_2_required",
            "btc_external_runtime_observe_job_not_task_registered",
            "btc_external_runtime_observe_job_no_micro_live_inputs",
            "btc_external_runtime_observe_job_current_head_gate_not_rebuilt",
            "btc_external_runtime_observe_job_promotion_paper_live_locked",
        ]
    )
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_version": RECEIPT_VERSION,
        "generated_at": generated_at or _utc_now(),
        **dict(source_identity),
        "status": "blocked_fail_closed",
        "decision": "observe_inputs_only_no_dataready_no_research_no_backtest_no_promotion_no_paper_no_live",
        "manifest_git_specs": {
            "public_swap": public_swap_manifest_git_spec,
            "l2": l2_manifest_git_spec,
        },
        "inputs": dict(consumed.get("inputs", {})),
        "input_errors": list(consumed.get("input_errors", [])),
        "preserved_input_blockers": list(
            consumed.get("preserved_input_blockers", [])
        ),
        "preserved_known_gaps": list(
            consumed.get("preserved_known_gaps", [])
        ),
        "all_files_verified": bool(
            consumed.get("all_files_verified", False)
        ),
        "consumer_read_only": True,
        "blockers": blockers,
        "safety": dict(_SAFETY_FLAGS),
    }


def _validate_absolute_roots(
    *,
    repo_root: Path,
    shared_root: Path,
) -> None:
    if not repo_root.is_absolute():
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_repo_root_must_be_absolute"
        )
    if not shared_root.is_absolute():
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_shared_root_must_be_absolute"
        )
    if not repo_root.is_dir():
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_repo_root_invalid"
        )
    if not shared_root.is_dir():
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_shared_root_invalid"
        )


def _reject_artifact_shared_root_overlap(
    *,
    artifact_root: Path,
    shared_root: Path,
) -> None:
    if (
        artifact_root == shared_root
        or artifact_root.is_relative_to(shared_root)
        or shared_root.is_relative_to(artifact_root)
    ):
        raise BTCExternalRuntimeObserveJobError(
            "btc_external_runtime_observe_artifact_shared_root_overlap"
        )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")


def _blocked_stderr(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "blocked_fail_closed",
        "receipt_written": False,
        "error": str(error),
        "consumer_read_only": True,
        "safety": dict(_SAFETY_FLAGS),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read two explicitly committed BTC manifests, verify immutable "
            "shared data offline, and write one blocked external receipt."
        )
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument(
        "--public-swap-manifest-git-spec",
        required=True,
    )
    parser.add_argument(
        "--l2-manifest-git-spec",
        required=True,
    )
    parser.add_argument("--expected-source-head", required=True)
    parser.add_argument("--repository-identity", required=True)
    parser.add_argument(
        "--worktree-root",
        action="append",
        type=Path,
        required=True,
    )
    parser.add_argument("--git-executable", type=Path, required=True)
    parser.add_argument("--git-executable-sha256", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = run_btc_external_runtime_observe_job(
            repo_root=args.repo_root,
            shared_root=args.shared_root,
            public_swap_manifest_git_spec=(
                args.public_swap_manifest_git_spec
            ),
            l2_manifest_git_spec=args.l2_manifest_git_spec,
            expected_source_head=args.expected_source_head,
            repository_identity=args.repository_identity,
            worktree_roots=tuple(args.worktree_root),
            git_executable=args.git_executable,
            git_executable_sha256=args.git_executable_sha256,
            environment=os.environ,
        )
    except (
        BTCArtifactSourceIdentityError,
        BTCExternalRuntimeObserveJobError,
        BTCSharedObservationInputsError,
        BTCRuntimeArtifactStoreError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                _blocked_stderr(exc),
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "status": receipt["status"],
                "receipt_logical_path": RECEIPT_LOGICAL_PATH.as_posix(),
                "source_head": receipt["source_head"],
                "commit": receipt["commit"],
                "consumer_read_only": True,
                "safety": receipt["safety"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RECEIPT_LOGICAL_PATH",
    "RECEIPT_SCHEMA_VERSION",
    "run_btc_external_runtime_observe_job",
    "validate_btc_external_runtime_observe_receipt",
]
