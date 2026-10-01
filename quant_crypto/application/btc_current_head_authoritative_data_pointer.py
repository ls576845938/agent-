"""Publish one fail-closed current-main BTC immutable-data evidence pointer.

The publisher is deliberately offline. It accepts one or more exact
Git-anchored shared-data manifests, rejects mutable discovery fallbacks, and
can bind committed ESS/regime and natural depth-fill evidence artifacts before
publishing an external run bundle.
The mutable pointer is replaced only after every immutable member and the
active-criteria read model have been durably written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactWriter,
)
from quant_crypto.research.btc_10s_microstructure_data_contract import (
    derive_measured_metrics,
    evaluate_readiness,
    inspect_resolved_source,
    resolve_source,
)
from quant_crypto.research.btc_okx_native_promotion_gate import (
    load_frozen_active_criteria_prereg,
)
from tools.agent_governance.shared_data import default_shared_data_root


SCHEMA_VERSION = "btc_current_head_authoritative_data_pointer_receipt_v1"
POINTER_SCHEMA_VERSION = "btc_okx_native_backtest_latest_pointer_v2"
ATTESTATION_SCHEMA_VERSION = "btc_okx_native_data_steward_attestation_v1"
ACTIVE_CRITERIA_SCHEMA_VERSION = "btc_promotion_gate_active_criteria_v1"
DEPTH_MAPPING_SCHEMA_VERSION = "btc_timestamp_aligned_depth_fill_mapping_binding_v1"

AUTHORITATIVE_MANIFEST_COMMIT = "f96473dda7e96df0adfa2a0a2f10cd936674cef1"
AUTHORITATIVE_MANIFEST_PATH = (
    ".agent/data_manifests/btc-okx-10s-microstructure-immutable-feed/"
    "btc-okx-10s-feed-00000001-20260827t111218925177z-src4e615032a6.json"
)
AUTHORITATIVE_MANIFEST_GIT_SPEC = (
    f"{AUTHORITATIVE_MANIFEST_COMMIT}:{AUTHORITATIVE_MANIFEST_PATH}"
)
EXPECTED_DATASET_ID = "btc-okx-10s-microstructure-immutable-feed"
EXPECTED_DATA_VERSION = (
    "btc-okx-10s-feed-00000001-20260827t111218925177z-src4e615032a6"
)
EXPECTED_AGGREGATE_SHA256 = (
    "2fa444de042e742e9763b6a4988205b7f05d5374d6cf66fa94d20c7efd26fd70"
)
ACTIVE_STRATEGY_FAMILY = "trade_imbalance_continuation"
ACTIVE_HORIZON = "10s"
MINIMUM_FREE_GIB = 50.0

RUNS_ROOT = Path("artifacts/btc_okx_native_backtest_evidence/runs")
LATEST_POINTER = Path("artifacts/btc_okx_native_backtest_evidence/latest_manifest.json")
ACTIVE_CRITERIA_LATEST = Path(
    "artifacts/btc_promotion_gate_active_criteria/latest/"
    "btc_promotion_gate_active_criteria.json"
)
PUBLICATION_CLEAN_PATHS = (
    ".agent/data_manifests/btc-okx-10s-microstructure-immutable-feed/"
    "btc-okx-10s-feed-00000001-20260827t111218925177z-src4e615032a6.json",
    "docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json",
    "quant_crypto/adapters/btc_runtime_artifact_store.py",
    "quant_crypto/application/btc_current_head_authoritative_data_pointer.py",
    "quant_crypto/application/btc_current_head_gate_rebuild.py",
    "quant_crypto/research/btc_10s_microstructure_data_contract.py",
    "quant_crypto/research/btc_okx_native_promotion_gate.py",
    "scripts/publish_btc_current_head_authoritative_data_pointer.py",
    "schemas/btc_current_head_authoritative_data_pointer_receipt.schema.json",
)
DEPTH_MAPPING_BLOCKER = (
    "btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing"
)
EXACT_COMMITTED_MANIFEST_GIT_SPEC = re.compile(
    r"^[0-9a-f]{40}:[.]agent/data_manifests/[A-Za-z0-9._/-]+[.]json$"
)
EXACT_COMMITTED_ARTIFACT_GIT_SPEC = re.compile(
    r"^[0-9a-f]{40}:(?:[.]agent/(?:data_manifests|handoffs)|docs/handoffs)/[A-Za-z0-9._/-]+[.]json$"
)

SAFETY_FLAGS = {
    "promotion": False,
    "paper": False,
    "live": False,
    "private": False,
    "order": False,
    "real_order": False,
    "transfer": False,
    "withdraw": False,
}


class PublicationError(RuntimeError):
    """Raised when publication cannot preserve the fail-closed contract."""


@dataclass(frozen=True)
class PublicationDependencies:
    git_state: Callable[[Path], Mapping[str, Any]] = lambda root: _git_state(root)
    resolve_source: Callable[..., Mapping[str, Any]] = resolve_source
    inspect_source: Callable[[Mapping[str, Any]], Mapping[str, Any]] = inspect_resolved_source
    derive_metrics: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any]] = derive_measured_metrics
    load_prereg: Callable[..., tuple[dict[str, Any], str]] = load_frozen_active_criteria_prereg
    disk_free_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free
    before_pointer_publish: Callable[[], None] = lambda: None
    read_git_json: Callable[[Path, str], tuple[dict[str, Any], str]] = lambda root, spec: _read_git_json(root, spec)


def publish_current_head_authoritative_data_pointer(
    *,
    repo_root: Path,
    expected_head: str,
    artifact_writer: BTCRuntimeArtifactWriter | None = None,
    shared_root: Path | None = None,
    run_id: str | None = None,
    generated_at_utc: str | datetime | None = None,
    dependencies: PublicationDependencies | None = None,
    manifest_git_specs: Sequence[str] | None = None,
    ess_artifact_git_spec: str | None = None,
    depth_fill_mapping_git_spec: str | None = None,
) -> dict[str, Any]:
    """Publish an immutable evidence bundle and update the pointer last."""

    deps = dependencies or PublicationDependencies()
    root = repo_root.resolve()
    state = dict(deps.git_state(root))
    current_head = str(state.get("head") or "")
    branch = str(state.get("branch") or "")
    dirty_paths = [str(value) for value in state.get("dirty_paths") or []]
    if branch != "main" or not _is_commit(current_head):
        raise PublicationError("publication_must_run_from_current_main")
    if not _is_commit(expected_head) or current_head != expected_head:
        raise PublicationError("publication_expected_head_mismatch")
    if dirty_paths:
        raise PublicationError("publication_git_worktree_dirty")

    generated = _utc_timestamp(generated_at_utc)
    selected_run_id = run_id or (
        "btc-current-head-data-pointer-"
        + generated.strftime("%Y%m%dT%H%M%S%fZ").lower()
        + "-"
        + current_head[:12]
    )
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", selected_run_id):
        raise PublicationError("publication_run_id_invalid")

    writer = artifact_writer or BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=root
    )
    free_gib = deps.disk_free_bytes(writer.artifact_root) / (1024.0**3)
    if free_gib < MINIMUM_FREE_GIB:
        raise PublicationError("publication_storage_below_50_gib")

    selected_manifest_specs = list(manifest_git_specs or [AUTHORITATIVE_MANIFEST_GIT_SPEC])
    if not selected_manifest_specs or len(set(selected_manifest_specs)) != len(selected_manifest_specs):
        raise PublicationError("publication_manifest_git_specs_invalid")
    for spec in selected_manifest_specs:
        _validate_exact_git_spec(spec, manifest_only=True)
    strict_multi_binding = manifest_git_specs is not None
    source_bindings: list[dict[str, Any]] = []
    inspected_sources: list[dict[str, Any]] = []
    for spec in selected_manifest_specs:
        binding = dict(
            deps.resolve_source(
                repo_root=root,
                shared_root=(shared_root or default_shared_data_root(root)).resolve(),
                manifest_git_spec=spec,
            )
        )
        _validate_authoritative_binding(
            binding,
            expected_spec=spec,
            require_data_steward=strict_multi_binding,
        )
        source_bindings.append(binding)
        inspected_sources.append(dict(deps.inspect_source(binding)))

    ess_artifact: dict[str, Any] | None = None
    ess_artifact_sha256: str | None = None
    if ess_artifact_git_spec:
        _validate_exact_git_spec(ess_artifact_git_spec, manifest_only=False)
        ess_artifact, ess_artifact_sha256 = deps.read_git_json(root, ess_artifact_git_spec)
        _validate_ess_artifact(
            ess_artifact,
            current_head=current_head,
            manifest_git_specs=selected_manifest_specs,
        )
        metrics = _sanitize(_mapping(ess_artifact.get("measured_metrics")))
    else:
        metrics = _sanitize(dict(deps.derive_metrics(inspected_sources)))
    prereg, prereg_blob_sha256 = deps.load_prereg(
        root,
        current_head=current_head,
    )
    if not prereg or not _is_sha256(prereg_blob_sha256):
        raise PublicationError("publication_frozen_prereg_unavailable")
    prereg_semantic_sha256 = _stable_hash(prereg)
    selected_readiness = _selected_readiness(prereg, metrics)
    information_decision = (
        "research_admission_ready"
        if selected_readiness.get("status") == "ready"
        else "blocked_insufficient_information"
    )

    if strict_multi_binding:
        dataset_id = "btc-okx-10s-microstructure-manifest-pool"
        data_version = "btc-okx-manifest-pool-" + _stable_hash(
            {"manifest_git_specs": selected_manifest_specs}
        )[:24]
        aggregate_sha256 = _stable_hash(
            {
                "aggregates": [str(binding["aggregate_sha256"]) for binding in source_bindings],
                "manifest_blob_sha256s": [str(binding["manifest_blob_sha256"]) for binding in source_bindings],
            }
        )
    else:
        dataset_id = EXPECTED_DATASET_ID
        data_version = EXPECTED_DATA_VERSION
        aggregate_sha256 = EXPECTED_AGGREGATE_SHA256
    identity = {
        "source_code_commit": current_head,
        "run_id": selected_run_id,
        "dataset_id": dataset_id,
        "data_version": data_version,
        "aggregate_sha256": aggregate_sha256,
    }
    manifest_identity = _stable_hash(
        {
            "source_bindings": [
                {
                    "manifest_git_spec": spec,
                    "manifest_blob_sha256": str(binding["manifest_blob_sha256"]),
                    "dataset_id": str(binding.get("dataset_id") or ""),
                    "dataset_version": str(binding.get("dataset_version") or ""),
                    "aggregate_sha256": str(binding["aggregate_sha256"]),
                }
                for spec, binding in zip(selected_manifest_specs, source_bindings, strict=True)
            ],
        }
    )
    identity["manifest_identity"] = manifest_identity
    immutable_uri = (
        f"immutable://btc-okx-native-evidence/{selected_run_id}"
    )
    run_root = RUNS_ROOT / selected_run_id
    attestation_path = run_root / "data_steward_attestation.json"
    depth_mapping_path = run_root / "timestamp_aligned_depth_fill_mapping.json"
    evidence_path = run_root / "evidence.json"
    manifest_path = run_root / "manifest.json"

    source_lineage: list[dict[str, Any]] = []
    for spec, binding in zip(selected_manifest_specs, source_bindings, strict=True):
        source_lineage.extend(
            [
                {
                    "kind": "immutable_shared_data_manifest",
                    "uri": f"git+commit://{spec}",
                    "path": spec.split(":", 1)[1],
                    "sha256": str(binding["manifest_blob_sha256"]),
                    "full_file_hash_verified": True,
                },
                {
                    "kind": "immutable_shared_data_aggregate",
                    "uri": (
                        f"immutable://shared-data/{binding.get('dataset_id')}/"
                        f"{binding.get('dataset_version')}"
                    ),
                    "path": (
                        f"datasets/{binding.get('dataset_id')}/{binding.get('dataset_version')}"
                    ),
                    "sha256": str(binding["aggregate_sha256"]),
                    "full_file_hash_verified": True,
                },
            ]
        )
    ess_ref = (
        {
            "kind": "effective_sample_regime_coverage",
            "uri": f"git+commit://{ess_artifact_git_spec}",
            "path": ess_artifact_git_spec.split(":", 1)[1],
            "sha256": ess_artifact_sha256,
            "git_spec": ess_artifact_git_spec,
        }
        if ess_artifact is not None
        else None
    )
    if ess_ref is not None:
        source_lineage.append(ess_ref)
    mapping_artifact: dict[str, Any] | None = None
    mapping_artifact_sha256: str | None = None
    if depth_fill_mapping_git_spec:
        _validate_exact_git_spec(depth_fill_mapping_git_spec, manifest_only=False)
        mapping_artifact, mapping_artifact_sha256 = deps.read_git_json(
            root, depth_fill_mapping_git_spec
        )
        _validate_depth_mapping_artifact(
            mapping_artifact,
            current_head=current_head,
            manifest_git_specs=selected_manifest_specs,
        )
    mapping_verified = mapping_artifact is not None
    depth_blockers = [] if mapping_verified else [DEPTH_MAPPING_BLOCKER]
    attestation = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "producer_role": "data_steward",
        "immutable_uri": f"{immutable_uri}/data-steward-attestation",
        **identity,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "readiness_class": "quality_checked",
        "quality_status": "pass_with_research_only_warnings",
        "source_manifests": [
            {
                "git_spec": spec,
                "blob_sha256": str(binding["manifest_blob_sha256"]),
                "aggregate_sha256": str(binding["aggregate_sha256"]),
                "full_file_hash_verified": True,
                "fallback_used": False,
            }
            for spec, binding in zip(selected_manifest_specs, source_bindings, strict=True)
        ],
        "modalities": {
            "normalized_trades": True,
            "ordered_l2": True,
            "same_connection": True,
            "trade_book_alignment_measured": True,
            "two_sided_quality_measured": True,
            "sequence_quality_measured": True,
            "natural_fill_or_queue_evidence": mapping_verified,
        },
        "input_lineage": source_lineage,
        "blockers": _dedupe(
            [
                *[str(value) for value in selected_readiness.get("blockers") or []],
                *depth_blockers,
            ]
        ),
        "safety": dict(SAFETY_FLAGS),
    }
    attestation_bytes = _json_bytes(attestation)
    attestation_ref = {
        "kind": "data_steward_attestation",
        "uri": attestation["immutable_uri"],
        "path": attestation_path.as_posix(),
        "sha256": hashlib.sha256(attestation_bytes).hexdigest(),
        "producer_role": "data_steward",
    }

    depth_mapping = (
        {
            **_sanitize(mapping_artifact),
            "source_code_commit": current_head,
            "run_id": selected_run_id,
            "source_artifact_git_spec": depth_fill_mapping_git_spec,
            "source_artifact_sha256": mapping_artifact_sha256,
            "safety": dict(SAFETY_FLAGS),
        }
        if mapping_artifact is not None
        else {
            "schema_version": DEPTH_MAPPING_SCHEMA_VERSION,
            **identity,
            "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
            "status": "blocked_fail_closed",
            "source_manifest_git_specs": selected_manifest_specs,
            "timestamp_aligned_trade_ordered_l2": True,
            "same_connection": True,
            "depth_impact_bps_is_natural_fill_evidence": False,
            "natural_fill_mapping_verified": False,
            "queue_position_verified": False,
            "partial_fill_verified": False,
            "promotion_evidence_ready": False,
            "blockers": [DEPTH_MAPPING_BLOCKER],
            "safety": dict(SAFETY_FLAGS),
        }
    )
    depth_bytes = _json_bytes(depth_mapping)
    depth_ref = {
        "kind": "timestamp_aligned_depth_fill_mapping",
        "uri": f"{immutable_uri}/timestamp-aligned-depth-fill-mapping",
        "path": depth_mapping_path.as_posix(),
        "sha256": hashlib.sha256(depth_bytes).hexdigest(),
        "git_spec": depth_fill_mapping_git_spec,
        "source_artifact_sha256": mapping_artifact_sha256,
        "natural_fill_ledger_sha256": (
            mapping_artifact.get("natural_fill_ledger_sha256")
            if mapping_artifact is not None
            else None
        ),
    }
    input_lineage = [*source_lineage, depth_ref, attestation_ref]
    data_blockers = _dedupe(
        [
            *[str(value) for value in selected_readiness.get("blockers") or []],
            *depth_blockers,
        ]
    ) or ["btc_okx_native:current_head_promotion_gate_rebuild_required"]

    evidence = {
        "schema_version": "btc_okx_native_current_head_data_evidence_v1",
        **identity,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "immutable_uri": f"{immutable_uri}/evidence",
        "active_strategy_family": ACTIVE_STRATEGY_FAMILY,
        "active_horizon": ACTIVE_HORIZON,
        "coverage": _combined_coverage(source_bindings),
        "source_manifest_git_specs": selected_manifest_specs,
        "ess_artifact": (
            {"git_spec": ess_artifact_git_spec, "sha256": ess_artifact_sha256}
            if ess_artifact is not None
            else None
        ),
        "measured_metrics": metrics,
        "selected_readiness": selected_readiness,
        "depth_fill_mapping": depth_ref,
        "input_lineage": input_lineage,
        "decision": information_decision,
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "blockers": list(data_blockers),
        "safety": dict(SAFETY_FLAGS),
    }
    evidence_bytes = _json_bytes(evidence)
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()

    manifest = {
        "schema_version": "btc_okx_native_current_head_data_manifest_v1",
        **identity,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "immutable_uri": f"{immutable_uri}/manifest",
        "immutable_version": selected_run_id,
        "source_manifest_git_specs": selected_manifest_specs,
        "source_manifest_blob_sha256s": [
            str(binding["manifest_blob_sha256"]) for binding in source_bindings
        ],
        "source_full_file_hash_verified": True,
        "input_lineage": input_lineage,
        "members": [
            {
                "kind": "evidence",
                "path": evidence_path.as_posix(),
                "sha256": evidence_sha256,
            },
            depth_ref,
            attestation_ref,
        ],
        "decision": "blocked_fail_closed_no_paper_no_live",
        "promotion_evidence_ready": False,
        "safety": dict(SAFETY_FLAGS),
    }
    manifest_bytes = _json_bytes(manifest)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    active_criteria = {
        "schema_version": ACTIVE_CRITERIA_SCHEMA_VERSION,
        **identity,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "active_strategy_family": ACTIVE_STRATEGY_FAMILY,
        "active_horizon": ACTIVE_HORIZON,
        "immutable_manifest_sha256": manifest_sha256,
        "immutable_evidence_sha256": evidence_sha256,
        "data_steward_attestation": attestation_ref,
        "prereg_semantic_sha256": prereg_semantic_sha256,
        "prereg_blob_sha256": prereg_blob_sha256,
        "preregistration": prereg,
        "measured_metrics": metrics,
        "selected_readiness": selected_readiness,
        "decision": information_decision,
        "promotion_evidence_ready": False,
        "blockers": _dedupe(
            [str(value) for value in selected_readiness.get("blockers") or []]
        ),
        "safety": dict(SAFETY_FLAGS),
    }
    active_criteria_bytes = _json_bytes(active_criteria)
    active_criteria_sha256 = hashlib.sha256(active_criteria_bytes).hexdigest()
    active_criteria_path = run_root / "active_criteria.json"

    pointer = {
        "schema_version": POINTER_SCHEMA_VERSION,
        **identity,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "immutable_uri": immutable_uri,
        "immutable_version": selected_run_id,
        "manifest": {
            "path": manifest_path.as_posix(),
            "sha256": manifest_sha256,
        },
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "evidence": {
            "path": evidence_path.as_posix(),
            "sha256": evidence_sha256,
        },
        "evidence_path": evidence_path.as_posix(),
        "evidence_sha256": evidence_sha256,
        "evidence_pack_sha256": evidence_sha256,
        "source_manifest_git_specs": selected_manifest_specs,
        "ess_artifact": (
            {"git_spec": ess_artifact_git_spec, "sha256": ess_artifact_sha256}
            if ess_artifact is not None
            else None
        ),
        "depth_fill_mapping": depth_ref,
        "input_lineage": input_lineage,
        "active_criteria": {
            "path": active_criteria_path.as_posix(),
            "sha256": active_criteria_sha256,
            "authority": "immutable_pointer_member",
        },
        "active_criteria_mirror": {
            "path": ACTIVE_CRITERIA_LATEST.as_posix(),
            "sha256": active_criteria_sha256,
            "authority": "non_authoritative_cache_only",
        },
        "decision": "blocked_fail_closed_no_paper_no_live",
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "blockers": list(data_blockers),
        "safety": dict(SAFETY_FLAGS),
    }

    with writer.exclusive() as session:
        _publish_immutable_run_bundle(
            session=session,
            run_root=run_root,
            payloads={
                "data_steward_attestation.json": attestation_bytes,
                "timestamp_aligned_depth_fill_mapping.json": depth_bytes,
                "evidence.json": evidence_bytes,
                "manifest.json": manifest_bytes,
                "active_criteria.json": active_criteria_bytes,
            },
        )
        session.write_json_atomic(ACTIVE_CRITERIA_LATEST, active_criteria)
        deps.before_pointer_publish()
        session.write_json_atomic(LATEST_POINTER, pointer)

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "published_blocked_fail_closed",
        **identity,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "manifest_git_spec": selected_manifest_specs[0],
        "manifest_blob_sha256": str(source_bindings[0]["manifest_blob_sha256"]),
        "source_full_file_hash_verified": True,
        "artifact_paths": {
            "pointer": LATEST_POINTER.as_posix(),
            "manifest": manifest_path.as_posix(),
            "evidence": evidence_path.as_posix(),
            "data_steward_attestation": attestation_path.as_posix(),
            "depth_fill_mapping": depth_mapping_path.as_posix(),
            "active_criteria": ACTIVE_CRITERIA_LATEST.as_posix(),
            "active_criteria_immutable": active_criteria_path.as_posix(),
        },
        "artifact_hashes": {
            "manifest_sha256": manifest_sha256,
            "evidence_sha256": evidence_sha256,
            "data_steward_attestation_sha256": attestation_ref["sha256"],
            "depth_fill_mapping_sha256": depth_ref["sha256"],
            "active_criteria_sha256": active_criteria_sha256,
        },
        "active_strategy_family": ACTIVE_STRATEGY_FAMILY,
        "active_horizon": ACTIVE_HORIZON,
        "eligible_labeled_windows": int(
            _mapping(metrics.get("information_by_horizon"))
            .get(ACTIVE_HORIZON, {})
            .get("eligible_labeled_windows", 0)
        ),
        "autocorrelation_adjusted_ess": float(
            _mapping(metrics.get("information_by_horizon"))
            .get(ACTIVE_HORIZON, {})
            .get("autocorrelation_adjusted_ess", 0.0)
        ),
        "decision": "blocked_insufficient_information",
        "blockers": list(pointer["blockers"]),
        "safety": dict(SAFETY_FLAGS),
    }
    _assert_no_physical_root_leak(receipt, writer.artifact_root)
    return receipt


def _publish_immutable_run_bundle(
    *,
    session: Any,
    run_root: Path,
    payloads: Mapping[str, bytes],
) -> None:
    final = session.resolve(run_root)
    if final.exists():
        raise PublicationError("publication_run_id_already_exists")
    staging_logical = run_root.parent / f".{run_root.name}.staging-{uuid.uuid4().hex}"
    staging = session.resolve(staging_logical)
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir(exist_ok=False)
    try:
        for name, payload in payloads.items():
            path = staging / name
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(staging, final)
    finally:
        if staging.exists() and _is_relative_to(staging, session.writer.artifact_root):
            shutil.rmtree(staging)


def _validate_authoritative_binding(
    binding: Mapping[str, Any],
    *,
    expected_spec: str,
    require_data_steward: bool,
) -> None:
    valid = (
        binding.get("manifest_git_spec") == expected_spec
        and bool(str(binding.get("dataset_id") or ""))
        and bool(str(binding.get("dataset_version") or ""))
        and _is_sha256(str(binding.get("aggregate_sha256") or ""))
        and binding.get("resolution_status") == "resolved_verified"
        and binding.get("full_file_hash_verified") is True
        and binding.get("fallback_used") is False
        and _is_sha256(str(binding.get("manifest_blob_sha256") or ""))
        and not binding.get("blockers")
    )
    if expected_spec == AUTHORITATIVE_MANIFEST_GIT_SPEC:
        valid = valid and (
            binding.get("dataset_id") == EXPECTED_DATASET_ID
            and binding.get("dataset_version") == EXPECTED_DATA_VERSION
            and binding.get("aggregate_sha256") == EXPECTED_AGGREGATE_SHA256
        )
    if require_data_steward:
        manifest = _mapping(binding.get("_manifest"))
        manifest_status = str(manifest.get("status") or "").lower()
        quality_status = str(manifest.get("quality_status") or "").lower()
        valid = valid and (
            manifest.get("producer_role") == "data_steward"
            and manifest.get("readiness_class") in {
                "quality_checked",
                "research_ready",
                "backtest_ready",
                "promotion_evidence_ready",
            }
            and not manifest_status.startswith(("blocked", "failed", "fail_closed"))
            and not quality_status.startswith(("blocked", "failed", "fail"))
        )
    if not valid:
        raise PublicationError("authoritative_immutable_binding_invalid")


def _selected_readiness(
    prereg: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        selected = next(
            row
            for row in evaluate_readiness(prereg, metrics)
            if row.get("family") == ACTIVE_STRATEGY_FAMILY
            and row.get("horizon") == ACTIVE_HORIZON
        )
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        raise PublicationError("publication_active_criteria_evaluation_failed") from exc
    return _sanitize(dict(selected))


def _validate_exact_git_spec(value: str, *, manifest_only: bool) -> None:
    lowered = value.lower()
    forbidden = ("latest", "staging", "*", "?", "[", ".csv", ".sqlite", ".db")
    pattern = (
        EXACT_COMMITTED_MANIFEST_GIT_SPEC
        if manifest_only
        else EXACT_COMMITTED_ARTIFACT_GIT_SPEC
    )
    if not pattern.fullmatch(value) or any(token in lowered for token in forbidden):
        raise PublicationError(f"exact_committed_manifest_git_spec_required:{value}")


def _read_git_json(repo_root: Path, git_spec: str) -> tuple[dict[str, Any], str]:
    try:
        payload = subprocess.run(
            ["git", "cat-file", "blob", git_spec],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        decoded = json.loads(payload.decode("utf-8"))
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError("committed_artifact_unavailable_or_invalid") from exc
    if not isinstance(decoded, Mapping):
        raise PublicationError("committed_artifact_unavailable_or_invalid")
    return dict(decoded), hashlib.sha256(payload).hexdigest()


def _validate_ess_artifact(
    artifact: Mapping[str, Any],
    *,
    current_head: str,
    manifest_git_specs: Sequence[str],
) -> None:
    valid = (
        artifact.get("source_head") == current_head
        and list(artifact.get("source_manifest_git_specs") or []) == list(manifest_git_specs)
        and artifact.get("full_manifest_pool_verified") is True
        and artifact.get("fallback_used") is False
        and isinstance(artifact.get("measured_metrics"), Mapping)
        and _all_safety_false(artifact.get("safety"))
    )
    if not valid:
        raise PublicationError("verified_ess_artifact_binding_invalid")


def _validate_depth_mapping_artifact(
    artifact: Mapping[str, Any],
    *,
    current_head: str,
    manifest_git_specs: Sequence[str],
) -> None:
    valid = (
        artifact.get("source_head") == current_head
        and list(artifact.get("immutable_l2_manifest_git_specs") or []) == list(manifest_git_specs)
        and artifact.get("strategy_fill_mapping_verified") is True
        and artifact.get("fill_mapping_state") == "verified"
        and artifact.get("promotion_evidence_ready") is True
        and _is_sha256(str(artifact.get("natural_fill_ledger_sha256") or ""))
        and not artifact.get("blockers")
        and _all_safety_false(artifact.get("safety"))
    )
    if not valid:
        raise PublicationError("verified_depth_fill_mapping_artifact_binding_invalid")


def _combined_coverage(bindings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    coverages = [_mapping(binding.get("coverage")) for binding in bindings]
    starts = sorted(str(row.get("start")) for row in coverages if row.get("start"))
    ends = sorted(str(row.get("end")) for row in coverages if row.get("end"))
    return {
        "start": starts[0] if starts else None,
        "end": ends[-1] if ends else None,
        "manifest_count": len(bindings),
    }


def _all_safety_false(value: Any) -> bool:
    safety = _mapping(value)
    return set(safety) == set(SAFETY_FLAGS) and all(
        safety[name] is False for name in SAFETY_FLAGS
    )


def _git_state(repo_root: Path) -> dict[str, Any]:
    try:
        head = _git_text(repo_root, "rev-parse", "HEAD")
        branch = _git_text(repo_root, "branch", "--show-current")
        tracked_dirty = _git_text(
            repo_root,
            "diff",
            "--name-only",
            "HEAD",
            "--",
            *PUBLICATION_CLEAN_PATHS,
        )
        untracked_dirty = _git_text(
            repo_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            *PUBLICATION_CLEAN_PATHS,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PublicationError("publication_git_state_unavailable") from exc
    return {
        "head": head,
        "branch": branch,
        "dirty_paths": sorted(
            {
                line.strip()
                for line in (tracked_dirty + "\n" + untracked_dirty).splitlines()
                if line.strip()
            }
        ),
    }


def _git_text(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_sanitize(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _utc_timestamp(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PublicationError("publication_generated_at_invalid") from exc
    if parsed.tzinfo is None:
        raise PublicationError("publication_generated_at_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _is_commit(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _assert_no_physical_root_leak(
    payload: Mapping[str, Any],
    artifact_root: Path,
) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    candidates = {
        str(artifact_root),
        str(artifact_root.resolve()),
        str(artifact_root).replace("\\", "/"),
    }
    if any(candidate and candidate in serialized for candidate in candidates):
        raise PublicationError("publication_physical_root_leak")


__all__ = [
    "AUTHORITATIVE_MANIFEST_GIT_SPEC",
    "PUBLICATION_CLEAN_PATHS",
    "PublicationDependencies",
    "PublicationError",
    "publish_current_head_authoritative_data_pointer",
]
