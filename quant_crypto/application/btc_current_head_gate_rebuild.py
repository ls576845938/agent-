"""Transactional, current-HEAD BTC gate reconstruction.

This module is deliberately offline.  It consumes only local, immutable
evidence references, derives blockers from the evidence that is actually
present, and publishes the immutable gate snapshot pointer last.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactWriteSession,
    BTCRuntimeArtifactWriter,
)
from quant_crypto.application.btc_domain_read_model import (
    LAYER_IDS,
    build_btc_domain_read_model,
)
from quant_crypto.application.btc_gate_snapshot import (
    DEFAULT_GATE_STATUS_PATHS,
    DEFAULT_POINTER_PATH as DEFAULT_GATE_SNAPSHOT_POINTER_PATH,
    DEFAULT_RUNS_ROOT as DEFAULT_GATE_RUNS_ROOT,
    GateBuildState,
    SCHEMA_VERSION as GATE_SNAPSHOT_SCHEMA_VERSION,
    _gate as _gate_snapshot_gate,
    _guardrails as _gate_snapshot_guardrails,
    capture_gate_build_state,
    gate_build_lock,
    load_latest_gate_snapshot,
    publish_gate_run_snapshot,
)
from quant_crypto.monitoring.artifact_schema import (
    apply_btc_artifact_schema,
    stable_payload_hash,
    validate_btc_artifact_schema,
)
from quant_crypto.research.btc_okx_native_promotion_gate import (
    ACTIVE_CRITERIA_LINEAGE_BLOCKER,
    ACTIVE_FAMILY_CAPABILITY_BLOCKER,
    ACTIVE_FAMILY_SCOPE_BLOCKER,
    DEPTH_FILL_MAPPING_BLOCKER,
    INFORMATION_COVERAGE_BLOCKER,
    OPEN_INTEREST_FAMILY_BLOCKER,
    evaluate_active_criteria_contract,
    evaluate_btc_okx_native_promotion_blockers,
    load_frozen_active_criteria_prereg,
)


SCHEMA_VERSION = "btc_current_head_gate_rebuild_v1"
OKX_POINTER_SCHEMA_VERSION = "btc_okx_native_backtest_latest_pointer_v2"
OKX_DATA_STEWARD_ATTESTATION_SCHEMA_VERSION = (
    "btc_okx_native_data_steward_attestation_v1"
)
OKX_DATA_STEWARD_ATTESTATION_KIND = "data_steward_attestation"
DEFAULT_OKX_POINTER_PATH = Path(
    "artifacts/btc_okx_native_backtest_evidence/latest_manifest.json"
)
DEFAULT_REBUILD_ROOT = Path("artifacts/btc_current_head_gate_rebuild")
DEFAULT_REBUILD_REPORT_PATH = (
    DEFAULT_REBUILD_ROOT / "latest" / "btc_current_head_gate_rebuild_report.json"
)
DEFAULT_GATE_PATH = Path(
    "artifacts/btc_promotion_gate_control/latest/"
    "btc_promotion_gate_control_report.json"
)
DEFAULT_DASHBOARD_PATH = Path(
    "artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"
)
DEFAULT_READ_MODEL_PATH = Path(
    "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
)
DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_PATH = Path(
    "artifacts/btc_perpetual_execution_evidence/latest/"
    "btc_perpetual_execution_evidence_report.json"
)
DEFAULT_MANUAL_APPROVAL_PATH = Path(
    "artifacts/btc_manual_paper_review_approval/latest/"
    "btc_manual_paper_review_approval_report.json"
)
DEFAULT_PAPER_CANDIDATE_PACKET_PATH = Path(
    "artifacts/btc_paper_candidate_packet/latest/"
    "btc_paper_candidate_packet_report.json"
)
DEFAULT_PAPER_READINESS_PATH = Path(
    "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"
)
DEFAULT_GATE_CONSISTENCY_PATH = Path(
    "artifacts/btc_gate_report_consistency/latest/"
    "btc_gate_report_consistency_report.json"
)
DEFAULT_EVIDENCE_PATHS: dict[str, Path] = {
    "active_criteria": Path(
        "artifacts/btc_promotion_gate_active_criteria/latest/"
        "btc_promotion_gate_active_criteria.json"
    ),
    "l2_batch": Path(
        "artifacts/btc_l2_depth_observation/latest/"
        "btc_okx_l2_depth_observation_batch_report.json"
    ),
    "fill_mapping": Path(
        "artifacts/btc_cost_model/latest/"
        "btc_depth_slippage_fill_mapping_report.json"
    ),
    "nonflat": Path(
        "artifacts/btc_nonflat_evidence/latest/"
        "btc_nonflat_evidence_autocapture.json"
    ),
    "observation_window": Path(
        "artifacts/btc_demo_observation_accumulator/latest/"
        "btc_demo_observation_accumulator_report.json"
    ),
    "manual_approval": DEFAULT_MANUAL_APPROVAL_PATH,
}

PROMOTION_REBUILD_BLOCKER = (
    "btc_okx_native:promotion_evidence_current_head_rebuild_required"
)
NATURAL_SAMPLE_BLOCKER = (
    "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing"
)
FUNDING_OBSERVATION_BLOCKER = (
    "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime"
)
PRIVATE_WS_BLOCKER = (
    "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete"
)
OBSERVATION_WINDOW_BLOCKER = (
    "btc_okx_native:25_hour_demo_observation_window_incomplete"
)
MANUAL_APPROVAL_BLOCKER = "btc_okx_native:manual_promotion_approval_missing"
GATE_STEP_ORDER = (
    "validate_authoritative_okx_pointer",
    "evaluate_current_head_evidence",
    "build_current_head_gate",
    "build_blocked_perpetual_execution_evidence",
    "build_manual_approval_state",
    "build_blocked_paper_candidate_packet",
    "build_blocked_paper_readiness",
    "build_gate_dashboard",
    "build_gate_report_consistency",
    "build_domain_read_model",
    "validate_outputs",
    "publish_latest_outputs",
    "build_validate_publish_rebuild_report",
    "publish_immutable_gate_snapshot",
)

SAFETY_FLAGS = {
    "promotion_allowed": False,
    "demo_allowed": False,
    "paper_allowed": False,
    "paper_queue_write_allowed": False,
    "paper_order_intake_allowed": False,
    "live_allowed": False,
    "live_unlock_allowed": False,
    "private_endpoint_allowed": False,
    "private_endpoint_used": False,
    "order_endpoint_allowed": False,
    "order_endpoint_used": False,
    "broker_access_allowed": False,
    "oms_access_allowed": False,
    "real_order_submitted": False,
    "withdraw_allowed": False,
}


class CurrentHeadGateRebuildError(RuntimeError):
    """Raised when a structural rebuild invariant fails."""


@dataclass(frozen=True)
class CurrentHeadGatePaths:
    okx_pointer: Path = DEFAULT_OKX_POINTER_PATH
    gate: Path = DEFAULT_GATE_PATH
    dashboard: Path = DEFAULT_DASHBOARD_PATH
    read_model: Path = DEFAULT_READ_MODEL_PATH
    perpetual_execution_evidence: Path = (
        DEFAULT_PERPETUAL_EXECUTION_EVIDENCE_PATH
    )
    manual_approval: Path = DEFAULT_MANUAL_APPROVAL_PATH
    paper_candidate_packet: Path = DEFAULT_PAPER_CANDIDATE_PACKET_PATH
    paper_readiness: Path = DEFAULT_PAPER_READINESS_PATH
    gate_consistency: Path = DEFAULT_GATE_CONSISTENCY_PATH
    rebuild_report: Path = DEFAULT_REBUILD_REPORT_PATH
    rebuild_root: Path = DEFAULT_REBUILD_ROOT
    evidence_paths: Mapping[str, Path] | None = None

    def evidence(self) -> Mapping[str, Path]:
        return self.evidence_paths or DEFAULT_EVIDENCE_PATHS


def rebuild_btc_current_head_gate(
    *,
    repo_root: Path,
    current_head: str,
    generated_at_utc: datetime | None = None,
    run_id: str | None = None,
    paths: CurrentHeadGatePaths | None = None,
    state_provider: Callable[[Path, Sequence[Path]], GateBuildState] | None = None,
    before_publish: Callable[[], None] | None = None,
    artifact_reader: BTCRuntimeArtifactReader | None = None,
    artifact_writer: BTCRuntimeArtifactWriter | None = None,
) -> dict[str, Any]:
    """Rebuild and atomically publish a structurally valid gate decision.

    A blocked decision is a successful structural rebuild.  The immutable gate
    snapshot pointer is published only after every output passes its contract.
    """

    root = repo_root.resolve()
    selected = paths or CurrentHeadGatePaths()
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    batch_id = run_id or (
        "btc_current_head_gate_" + generated.strftime("%Y%m%dT%H%M%S%fZ")
    )
    _validate_identity(current_head=current_head, run_id=batch_id)
    writer = artifact_writer or BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=root
    )
    reader = artifact_reader or writer
    _validate_artifact_store_pair(reader=reader, writer=writer)
    input_paths = [selected.okx_pointer, *selected.evidence().values()]
    capture = state_provider or (
        lambda value, inputs: _capture_rebuild_state(
            value,
            current_head=current_head,
            input_paths=inputs,
            artifact_reader=reader,
        )
    )

    with gate_build_lock(
        root,
        timeout_seconds=0.0,
        artifact_writer=writer,
    ) as write_session:
        start_state = capture(root, input_paths)
        if start_state.code_commit != current_head:
            raise CurrentHeadGateRebuildError(
                "btc_current_head_gate_source_head_mismatch"
            )

        pointer_validation = validate_authoritative_okx_pointer(
            repo_root=root,
            pointer_path=selected.okx_pointer,
            current_head=current_head,
            artifact_reader=reader,
        )
        evidence = _load_evidence(reader, selected.evidence())
        frozen_prereg, frozen_prereg_blob_sha256 = (
            load_frozen_active_criteria_prereg(
                root,
                current_head=current_head,
            )
        )
        evaluation = evaluate_current_head_gate_evidence(
            current_head=current_head,
            generated_at_utc=generated,
            pointer_validation=pointer_validation,
            evidence=evidence,
            frozen_preregistration=frozen_prereg,
            frozen_prereg_blob_sha256=frozen_prereg_blob_sha256,
        )
        gate_report = _build_gate_report(
            current_head=current_head,
            generated=generated,
            run_id=batch_id,
            pointer_validation=pointer_validation,
            evaluation=evaluation,
            evidence=evidence,
        )
        supporting = _build_supporting_artifacts(
            current_head=current_head,
            generated=generated,
            run_id=batch_id,
            evaluation=evaluation,
            existing_manual=evidence.get("manual_approval", {}),
        )
        dashboard = _build_dashboard(
            current_head=current_head,
            generated=generated,
            run_id=batch_id,
            gate_report=gate_report,
            perpetual_execution_evidence=supporting[
                "perpetual_execution_evidence"
            ],
        )
        consistency = _build_consistency_report(
            current_head=current_head,
            generated=generated,
            run_id=batch_id,
            dashboard=dashboard,
            perpetual_execution_evidence=supporting[
                "perpetual_execution_evidence"
            ],
        )
        read_model = _build_read_model(
            current_head=current_head,
            generated=generated,
            aggregation_batch_id=batch_id,
            pointer_validation=pointer_validation,
            evaluation=evaluation,
            gate_report=gate_report,
            dashboard=dashboard,
        )
        outputs = {
            "gate": (selected.gate, gate_report),
            "perpetual_execution_evidence": (
                selected.perpetual_execution_evidence,
                supporting["perpetual_execution_evidence"],
            ),
            "manual_approval": (
                selected.manual_approval,
                supporting["manual_approval"],
            ),
            "paper_candidate_packet": (
                selected.paper_candidate_packet,
                supporting["paper_candidate_packet"],
            ),
            "paper_readiness": (
                selected.paper_readiness,
                supporting["paper_readiness"],
            ),
            "dashboard": (selected.dashboard, dashboard),
            "gate_consistency": (
                selected.gate_consistency,
                consistency,
            ),
            "read_model": (selected.read_model, read_model),
        }
        validation_checks = _validate_outputs(
            outputs=outputs,
            current_head=current_head,
            run_id=batch_id,
        )
        if not all(validation_checks.values()):
            raise CurrentHeadGateRebuildError(
                "btc_current_head_gate_output_validation_failed:"
                + ",".join(
                    key for key, passed in validation_checks.items() if not passed
                )
            )

        staging = reader.resolve(selected.rebuild_root) / (
            f".{batch_id}.staging.{uuid.uuid4().hex}"
        )
        report_path = reader.resolve(selected.rebuild_report)
        previous_report = (
            report_path.read_bytes() if report_path.is_file() else None
        )
        try:
            staged_files = _stage_outputs(staging=staging, outputs=outputs)
            if before_publish is not None:
                before_publish()
            end_state = capture(root, input_paths)
            for name in outputs:
                write_session.write_bytes_atomic(
                    outputs[name][0],
                    staged_files[name].read_bytes(),
                )

            planned_publication = _planned_snapshot_publication(
                artifact_reader=reader,
                aggregation_batch_id=batch_id,
                generated_at_utc=generated,
                start_state=start_state,
                end_state=end_state,
                step_order=GATE_STEP_ORDER,
                source_paths=[value[0] for value in outputs.values()],
                required_paths=[value[0] for value in outputs.values()],
                validation_checks=validation_checks,
            )
            report = _build_rebuild_report(
                root=root,
                current_head=current_head,
                generated=generated,
                run_id=batch_id,
                pointer_validation=pointer_validation,
                evaluation=evaluation,
                outputs=outputs,
                publication=planned_publication,
                validation_checks=validation_checks,
                artifact_reader=reader,
            )
            _validate_rebuild_report_for_publish(
                report=report,
                current_head=current_head,
                run_id=batch_id,
                artifact_reader=reader,
                outputs=outputs,
            )
            write_session.write_json_atomic(
                selected.rebuild_report,
                report,
            )

            try:
                publication = publish_gate_run_snapshot(
                    repo_root=root,
                    aggregation_batch_id=batch_id,
                    generated_at_utc=generated,
                    start_state=start_state,
                    end_state=end_state,
                    step_order=GATE_STEP_ORDER,
                    source_paths=[value[0] for value in outputs.values()],
                    required_paths=[value[0] for value in outputs.values()],
                    validation_checks=validation_checks,
                    artifact_reader=reader,
                    artifact_writer=writer,
                    write_session=write_session,
                )
            except Exception:
                _restore_rebuild_report(
                    write_session=write_session,
                    logical_path=selected.rebuild_report,
                    physical_path=report_path,
                    previous_payload=previous_report,
                )
                raise
            if not _publication_matches_plan(
                publication=publication,
                planned=planned_publication,
            ):
                raise CurrentHeadGateRebuildError(
                    "btc_current_head_gate_snapshot_publication_plan_mismatch"
                )
            if publication.get("published") is not True:
                _restore_rebuild_report(
                    write_session=write_session,
                    logical_path=selected.rebuild_report,
                    physical_path=report_path,
                    previous_payload=previous_report,
                )
                raise CurrentHeadGateRebuildError(
                    "btc_current_head_gate_snapshot_not_published:"
                    + str(publication.get("status") or "unknown")
                )
            latest = load_latest_gate_snapshot(
                root,
                expected_head=current_head,
                artifact_reader=reader,
            )
            if latest.get("status") != "valid":
                raise CurrentHeadGateRebuildError(
                    "btc_current_head_gate_latest_snapshot_invalid:"
                    + str(latest.get("error") or "unknown")
                )
            if (
                latest.get("pointer", {}).get("manifest_sha256")
                != planned_publication["run_manifest_sha256"]
            ):
                raise CurrentHeadGateRebuildError(
                    "btc_current_head_gate_latest_snapshot_hash_mismatch"
                )
            return report
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def validate_authoritative_okx_pointer(
    *,
    repo_root: Path,
    pointer_path: Path = DEFAULT_OKX_POINTER_PATH,
    current_head: str,
    artifact_reader: BTCRuntimeArtifactReader | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    reader = artifact_reader or BTCRuntimeArtifactReader.from_environment(
        source_repo_root=root
    )
    absolute_pointer = reader.resolve(pointer_path)
    errors: list[str] = []
    pointer, pointer_sha = _read_json_with_hash(absolute_pointer)
    if not pointer:
        errors.append("pointer:missing_or_invalid")
        return _pointer_result(
            pointer_path=pointer_path,
            pointer_sha256=pointer_sha,
            current_head=current_head,
            errors=errors,
        )
    if pointer.get("schema_version") != OKX_POINTER_SCHEMA_VERSION:
        errors.append("pointer:schema_mismatch")

    manifest_ref = _artifact_ref(
        pointer,
        nested_key="manifest",
        path_keys=("manifest_path",),
        hash_keys=("manifest_sha256",),
    )
    if not manifest_ref["path"]:
        bundle = str(pointer.get("data_bundle_dir") or "")
        if bundle:
            manifest_ref["path"] = (
                Path(bundle) / "manifest.json"
            ).as_posix()
    manifest, manifest_actual_sha = _read_referenced_json(
        artifact_reader=reader,
        reference=manifest_ref,
        label="manifest",
        errors=errors,
    )

    evidence_ref = _artifact_ref(
        pointer,
        nested_key="evidence",
        path_keys=("evidence_path",),
        hash_keys=("evidence_sha256",),
    )
    evidence, evidence_actual_sha = _read_referenced_json(
        artifact_reader=reader,
        reference=evidence_ref,
        label="evidence",
        errors=errors,
    )

    source_head = _first_text(
        pointer,
        "source_code_commit",
        "source_head",
        "code_commit",
    ) or _first_text(manifest, "source_code_commit", "source_head", "code_commit")
    run_id = _first_text(pointer, "run_id") or _first_text(manifest, "run_id")
    data_version = _first_text(pointer, "data_version") or _first_text(
        manifest, "data_version"
    )
    immutable_uri = _first_text(
        pointer, "immutable_uri", "artifact_uri"
    ) or _first_text(manifest, "immutable_uri", "artifact_uri")
    immutable_version = _first_text(
        pointer, "immutable_version"
    ) or _first_text(manifest, "immutable_version") or data_version
    lineage = pointer.get("input_lineage")

    if not source_head:
        errors.append("pointer:source_code_commit_missing")
    elif source_head != current_head:
        errors.append("pointer:source_code_commit_wrong_head")
    if not run_id:
        errors.append("pointer:run_id_missing")
    if not data_version:
        errors.append("pointer:data_version_missing")
    if not immutable_uri or "latest" in immutable_uri.lower():
        errors.append("pointer:immutable_uri_missing_or_mutable")
    if not immutable_version:
        errors.append("pointer:immutable_version_missing")
    if not _lineage_valid(lineage):
        errors.append("pointer:input_lineage_invalid")
    _check_cross_document_identity(
        label="manifest",
        payload=manifest,
        source_head=source_head,
        run_id=run_id,
        data_version=data_version,
        errors=errors,
    )
    _check_cross_document_identity(
        label="evidence",
        payload=evidence,
        source_head=source_head,
        run_id=run_id,
        data_version=data_version,
        errors=errors,
    )
    data_identity = _cross_document_data_identity(
        pointer=pointer,
        manifest=manifest,
        evidence=evidence,
        errors=errors,
    )
    verified_attestation = _verify_data_steward_attestation(
        artifact_reader=reader,
        pointer=pointer,
        manifest=manifest,
        evidence=evidence,
        source_head=source_head,
        run_id=run_id,
        data_version=data_version,
        data_identity=data_identity,
        errors=errors,
    )
    return _pointer_result(
        pointer_path=pointer_path,
        pointer_sha256=pointer_sha,
        current_head=current_head,
        errors=errors,
        source_head=source_head,
        run_id=run_id,
        data_version=data_version,
        immutable_uri=immutable_uri,
        immutable_version=immutable_version,
        manifest_ref=manifest_ref,
        manifest_sha256=manifest_actual_sha,
        evidence_ref=evidence_ref,
        evidence_sha256=evidence_actual_sha,
        input_lineage=lineage,
        verified_data_steward_attestation=verified_attestation,
    )


def evaluate_current_head_gate_evidence(
    *,
    current_head: str,
    generated_at_utc: datetime,
    pointer_validation: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    frozen_preregistration: Mapping[str, Any] | None = None,
    frozen_prereg_blob_sha256: str = "",
) -> dict[str, Any]:
    generated = _ensure_utc(generated_at_utc)
    depth = evaluate_btc_okx_native_promotion_blockers(
        l2_batch_report=evidence.get("l2_batch", {}),
        fill_mapping_report=evidence.get("fill_mapping", {}),
        observation_window_report=evidence.get("observation_window", {}),
        current_head=current_head,
        now_utc=generated,
        existing_external_blockers=(),
    )
    active = evaluate_active_criteria_contract(
        report=evidence.get("active_criteria", {}),
        current_head=current_head,
        expected_preregistration=frozen_preregistration,
        expected_prereg_blob_sha256=frozen_prereg_blob_sha256,
        pointer_validation=pointer_validation,
    )
    nonflat = evidence.get("nonflat", {})
    observation = evidence.get("observation_window", {})
    manual = evidence.get("manual_approval", {})

    checks = {
        "authoritative_okx_pointer_current_head": (
            pointer_validation.get("status") == "valid_current_head"
        ),
        "depth_fill_mapping_current_head": (
            depth.get("depth_fill_mapping_evidence_valid") is True
        ),
        "active_strategy_family_scope_current_head": (
            active.get("active_family_scope_valid") is True
        ),
        "information_coverage_prereg_current_head": (
            active.get("information_coverage_evidence_valid") is True
        ),
        "active_strategy_family_capabilities_current_head": (
            active.get("active_family_scope_valid") is not True
            or active.get("information_coverage_evidence_valid") is not True
            or active.get("family_capabilities_valid") is True
        ),
        "open_interest_for_active_family_current_head": (
            active.get("open_interest_evidence_valid") is True
        ),
        "active_criteria_pointer_lineage_current_head": (
            active.get("pointer_lineage_binding_valid") is True
        ),
        "natural_non_flat_sample_current_head": (
            _promotion_evidence_current(nonflat, current_head=current_head)
            and str(nonflat.get("sample_origin") or "")
            == "current_natural_observation"
            and bool(nonflat.get("nodes"))
            and _mapping(nonflat.get("audit_dag")).get("valid") is True
        ),
        "funding_cashflow_observed_current_head": (
            _promotion_evidence_current(nonflat, current_head=current_head)
            and _truthy_path(
                nonflat,
                "funding_cashflow_observed",
                "summary.funding_cashflow_observed",
            )
        ),
        "private_ws_reconciliation_observed_current_head": (
            _promotion_evidence_current(nonflat, current_head=current_head)
            and _truthy_path(
                nonflat,
                "private_ws_observed",
                "summary.private_ws_observed",
            )
        ),
        "observation_window_25h_authorized_okx_demo_current_head": (
            depth.get("observation_window_evidence_valid") is True
        ),
        "manual_approval_current_head": (
            _current_head_payload(manual, current_head=current_head)
            and manual.get("manual_approval_recorded") is True
            and not manual.get("blockers")
        ),
    }
    blocker_by_check = {
        "authoritative_okx_pointer_current_head": PROMOTION_REBUILD_BLOCKER,
        "depth_fill_mapping_current_head": DEPTH_FILL_MAPPING_BLOCKER,
        "active_strategy_family_scope_current_head": ACTIVE_FAMILY_SCOPE_BLOCKER,
        "information_coverage_prereg_current_head": INFORMATION_COVERAGE_BLOCKER,
        "active_strategy_family_capabilities_current_head": (
            ACTIVE_FAMILY_CAPABILITY_BLOCKER
        ),
        "open_interest_for_active_family_current_head": (
            OPEN_INTEREST_FAMILY_BLOCKER
        ),
        "active_criteria_pointer_lineage_current_head": (
            ACTIVE_CRITERIA_LINEAGE_BLOCKER
        ),
        "natural_non_flat_sample_current_head": NATURAL_SAMPLE_BLOCKER,
        "funding_cashflow_observed_current_head": FUNDING_OBSERVATION_BLOCKER,
        "private_ws_reconciliation_observed_current_head": PRIVATE_WS_BLOCKER,
        "observation_window_25h_authorized_okx_demo_current_head": (
            OBSERVATION_WINDOW_BLOCKER
        ),
        "manual_approval_current_head": MANUAL_APPROVAL_BLOCKER,
    }
    blockers = [
        blocker_by_check[check_id]
        for check_id, passed in checks.items()
        if not passed
    ]
    blocker_details = [
        {
            "code": blocker,
            **_blocker_owner(blocker),
        }
        for blocker in blockers
    ]
    research_ready = (
        checks["authoritative_okx_pointer_current_head"]
        and checks["active_strategy_family_scope_current_head"]
        and checks["information_coverage_prereg_current_head"]
        and checks["active_criteria_pointer_lineage_current_head"]
    )
    backtest_ready = (
        research_ready
        and checks["depth_fill_mapping_current_head"]
        and checks["active_strategy_family_capabilities_current_head"]
        and checks["open_interest_for_active_family_current_head"]
    )
    promotion_evidence_ready = all(checks.values())
    return {
        "schema_version": "btc_current_head_gate_evaluation_v1",
        "source_head": current_head,
        "generated_at_utc": generated.isoformat(),
        "checks": checks,
        "blockers": blockers,
        "blocker_details": blocker_details,
        "validation_errors": {
            "okx_pointer": list(pointer_validation.get("validation_errors") or []),
            "active_criteria": list(active.get("validation_errors") or []),
            "depth_fill_mapping": list(depth.get("validation_errors") or []),
            "observation_window": list(
                depth.get("observation_validation_errors") or []
            ),
        },
        "quality_checked": True,
        "research_ready": research_ready,
        "backtest_ready": backtest_ready,
        "promotion_evidence_ready": promotion_evidence_ready,
        "safety": dict(SAFETY_FLAGS),
    }


def _build_gate_report(
    *,
    current_head: str,
    generated: datetime,
    run_id: str,
    pointer_validation: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    blockers = list(evaluation.get("blockers") or [])
    blocker_details = list(evaluation.get("blocker_details") or [])
    root_cause_matrix = [
        {
            "root_cause_id": _root_cause_id(str(row.get("code") or "")),
            "blocker": str(row.get("code") or ""),
            "category": str(row.get("category") or ""),
            "owner": str(row.get("owner") or ""),
            "next_command": str(
                row.get("next_executable_action") or ""
            ),
            "acceptance_criteria": (
                f"current_head_evidence_clears:{row.get('code')}"
            ),
        }
        for row in blocker_details
        if isinstance(row, Mapping)
    ]
    input_hashes = {
        "authoritative_okx_pointer": str(
            pointer_validation.get("pointer_sha256") or ""
        ),
        **{
            key: str(value.get("_file_sha256") or "")
            for key, value in evidence.items()
        },
    }
    readiness_class = "quality_checked"
    if evaluation.get("research_ready") is True:
        readiness_class = "research_ready"
    if evaluation.get("backtest_ready") is True:
        readiness_class = "backtest_ready"
    if evaluation.get("promotion_evidence_ready") is True:
        readiness_class = "promotion_evidence_ready"
    payload = {
        "schema_version": "btc_current_head_gate_decision_v1",
        "status": "blocked" if blockers else "complete_current_head",
        "source_head": current_head,
        "code_commit": current_head,
        "aggregation_batch_id": run_id,
        "run_id": run_id,
        "data_version": str(pointer_validation.get("data_version") or ""),
        "readiness_class": readiness_class,
        "quality_checked": True,
        "research_ready": evaluation.get("research_ready") is True,
        "backtest_ready": evaluation.get("backtest_ready") is True,
        "promotion_evidence_ready": (
            evaluation.get("promotion_evidence_ready") is True
        ),
        "authoritative_okx_pointer": dict(pointer_validation),
        "evidence_evaluation": dict(evaluation),
        "blocker_details": blocker_details,
        "root_cause_matrix": root_cause_matrix,
        "root_cause_task_queue": {
            "dashboard_should_show_root_causes_only": True,
            "immediate_development_items": root_cause_matrix,
        },
        "required_rebuild_reports": [
            str(row.get("next_executable_action") or "")
            for row in blocker_details
            if isinstance(row, Mapping)
        ],
        "artifact_freshness": {
            "status": "fail" if blockers else "pass",
            "dependency_newer_than_consumer_count": 0,
            "source_timeline_consistent": True,
        },
        "safety": dict(SAFETY_FLAGS),
    }
    return apply_btc_artifact_schema(
        payload,
        decision=(
            "blocked_fail_closed_no_paper_no_live"
            if blockers
            else "promotion_evidence_ready_manual_review_only_no_paper_no_live"
        ),
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=[],
        input_hashes=input_hashes,
    )


def _build_dashboard(
    *,
    current_head: str,
    generated: datetime,
    run_id: str,
    gate_report: Mapping[str, Any],
    perpetual_execution_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = list(gate_report.get("blockers") or [])
    root_cause_matrix = list(gate_report.get("root_cause_matrix") or [])
    root_cause_task_queue = dict(
        gate_report.get("root_cause_task_queue") or {}
    )
    payload = {
        "schema_version": "btc_current_head_gate_dashboard_v1",
        "gate_dashboard_version": "btc_gate_dashboard_v1",
        "status": "blocked" if blockers else "complete",
        "source_head": current_head,
        "code_commit": current_head,
        "aggregation_batch_id": run_id,
        "run_id": run_id,
        "current_stage": (
            "waiting_for_natural_non_flat_sample"
            if NATURAL_SAMPLE_BLOCKER in blockers
            else ("blocked" if blockers else "manual_gate_review")
        ),
        "gate_source": {
            "path": DEFAULT_GATE_PATH.as_posix(),
            "artifact_hash": str(gate_report.get("artifact_hash") or ""),
            "source_head": current_head,
        },
        "artifacts": {
            "perpetual_execution_evidence": {
                "status": str(
                    perpetual_execution_evidence.get("status") or ""
                ),
                "artifact_hash": str(
                    perpetual_execution_evidence.get("artifact_hash") or ""
                ),
                "blockers": list(
                    perpetual_execution_evidence.get("blockers") or []
                ),
            }
        },
        "root_cause_source": "promotion_gate_control",
        "root_cause_matrix": root_cause_matrix,
        "root_cause_task_queue": root_cause_task_queue,
        "readiness_class": str(gate_report.get("readiness_class") or ""),
        "quality_checked": True,
        "research_ready": gate_report.get("research_ready") is True,
        "backtest_ready": gate_report.get("backtest_ready") is True,
        "promotion_evidence_ready": (
            gate_report.get("promotion_evidence_ready") is True
        ),
        "safety": dict(SAFETY_FLAGS),
    }
    return apply_btc_artifact_schema(
        payload,
        decision=str(gate_report.get("decision") or ""),
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=[],
        input_hashes={
            "gate_artifact_hash": str(gate_report.get("artifact_hash") or ""),
            "perpetual_execution_evidence": str(
                perpetual_execution_evidence.get("artifact_hash") or ""
            ),
        },
    )


def _build_supporting_artifacts(
    *,
    current_head: str,
    generated: datetime,
    run_id: str,
    evaluation: Mapping[str, Any],
    existing_manual: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    blockers = list(evaluation.get("blockers") or [])
    execution_blockers = [
        item
        for item in blockers
        if item
        in {
            DEPTH_FILL_MAPPING_BLOCKER,
            NATURAL_SAMPLE_BLOCKER,
            FUNDING_OBSERVATION_BLOCKER,
            PRIVATE_WS_BLOCKER,
        }
    ]
    execution = apply_btc_artifact_schema(
        {
            "schema_version": "btc_perpetual_execution_evidence_v1",
            "status": "incomplete_research_only",
            "source_head": current_head,
            "code_commit": current_head,
            "aggregation_batch_id": run_id,
            "run_id": run_id,
            "quality_checked": True,
            "promotion_evidence_ready": False,
            "gate": dict(SAFETY_FLAGS),
            "safety": dict(SAFETY_FLAGS),
        },
        decision="blocked_fail_closed_no_paper_no_live",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=execution_blockers,
        warnings=[],
        input_hashes={},
    )

    packet_hash = stable_payload_hash(
        {"source_head": current_head, "run_id": run_id}
    )
    packet = apply_btc_artifact_schema(
        {
            "schema_version": "btc_paper_candidate_packet_v1",
            "status": "not_ready",
            "source_head": current_head,
            "code_commit": current_head,
            "current_head_code_commit": current_head,
            "source_code_commit_current_head_match": True,
            "aggregation_batch_id": run_id,
            "run_id": run_id,
            "reviewed_packet_hash": {"sha256": packet_hash},
            "paper_candidate_packet": {
                "packet_status": "not_ready",
                "reviewer": {
                    "status": "missing",
                    "review_record_current_and_hash_valid": False,
                },
            },
            "quality_checked": True,
            "promotion_evidence_ready": False,
            "safety": dict(SAFETY_FLAGS),
        },
        decision="blocked_fail_closed_no_paper_no_live",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=[],
        input_hashes={},
    )

    manual_valid = (
        _current_head_payload(existing_manual, current_head=current_head)
        and existing_manual.get("manual_approval_recorded") is True
        and not existing_manual.get("blockers")
    )
    manual_payload = apply_btc_artifact_schema(
        {
            "schema_version": "btc_manual_paper_review_approval_report_v1",
            "status": (
                "recorded_research_only"
                if manual_valid
                else "missing_or_invalid_research_only"
            ),
            "source_head": current_head,
            "code_commit": current_head,
            "aggregation_batch_id": run_id,
            "run_id": run_id,
            "manual_approval_recorded": manual_valid,
            "manual_review_missing_cleared": manual_valid,
            "reviewed_packet_sha256": str(
                existing_manual.get("reviewed_packet_sha256") or ""
            ),
            "approval_record": dict(
                _mapping(existing_manual.get("approval_record"))
            ),
            "approval_hash_comparison": dict(
                _mapping(existing_manual.get("approval_hash_comparison"))
            )
            or {"canonical_hash_matches": False},
            "quality_checked": True,
            "promotion_evidence_ready": False,
            "safety": dict(SAFETY_FLAGS),
        },
        decision=(
            "manual_review_recorded_review_only_no_auto_paper_no_live"
            if manual_valid
            else "blocked_fail_closed_no_paper_no_live"
        ),
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=(
            []
            if manual_valid
            else [
                "btc_manual_paper_review_approval_packet_sha256_mismatch",
                MANUAL_APPROVAL_BLOCKER,
            ]
        ),
        warnings=[],
        input_hashes={
            "paper_candidate_packet": str(packet.get("artifact_hash") or "")
        },
    )

    readiness = apply_btc_artifact_schema(
        {
            "schema_version": "btc_paper_readiness_report_v1",
            "status": "blocked",
            "commit": current_head,
            "branch": "current_head_gate_rebuild",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "source_head": current_head,
            "code_commit": current_head,
            "aggregation_batch_id": run_id,
            "run_id": run_id,
            "paper_queue_status": "locked",
            "paper_start_allowed": False,
            "paper_execution_authorized": False,
            "live_status": "frozen",
            "next_required_action": "complete_btc_manual_paper_gate_inputs",
            "paper_gate_manual_inputs_complete": False,
            "required_manual_inputs": [
                {
                    "name": name,
                    "required_for": "btc_paper_readiness",
                    "status": "awaiting_capture",
                    "action": action,
                    "blockers": [f"btc_paper_readiness_{name}_missing"],
                }
                for name, action in (
                    ("exchange_info", "manual_capture_from_allowed_network"),
                    ("funding_info", "manual_capture_from_allowed_network"),
                    ("fee_tier_overlay", "capture_public_fee_schedule_and_import"),
                )
            ],
            "fee_tier_status": {
                "cost_model_report": None,
                "cost_model_status": "missing",
                "fee_tier_verified": False,
                "manual_capture_required": True,
                "maker_fee_bps": None,
                "taker_fee_bps": None,
                "fee_tier_import_report_verified": False,
                "fee_blockers": ["btc_paper_readiness_fee_tier_cost_model_not_verified"],
            },
            "approved_paper_review": {
                "approved": False,
                "paper_review_id": "",
                "status": "CURRENT_PACKET_UNAPPROVED",
                "path": "",
                "strategy_manifest_id": "",
                "proposed_symbols": [],
                "proposed_capital": 0.0,
                "evidence_pack_path": "",
                "evidence_pack_exists": False,
                "current_packet_present": bool(packet),
                "current_packet_hash": str(packet.get("artifact_hash") or ""),
                "approval_record_packet_hash": "",
                "approval_current_packet_hash_match": False,
                "approval": {
                    "valid": False,
                    "schema_version": "",
                    "reviewer": "",
                    "reason": "",
                    "timestamp": "",
                    "candidate_id": "",
                    "commit_hash": "",
                    "source": "",
                    "source_sha256": "",
                    "recorded_source_sha256": "",
                    "gate_snapshot": {},
                    "blockers": ["btc_paper_readiness_approved_paper_review_missing"],
                },
            },
            "requirements": {
                name: {
                    "status": "blocked",
                    "checks": {},
                    "blockers": [blocker],
                    "evidence": {},
                }
                for name, blocker in (
                    ("manual_input_gate", "btc_paper_readiness_manual_inputs_incomplete"),
                    ("data_source_gate", "btc_paper_readiness_provider_not_ready"),
                    ("cost_ledger_gate", "btc_paper_readiness_cost_ledger_incomplete"),
                    ("candidate_gate", "btc_paper_readiness_candidate_gate_not_pass"),
                    ("paper_review_gate", "btc_paper_readiness_approved_paper_review_missing"),
                    ("runtime_boundary_gate", "btc_paper_readiness_runtime_boundary_locked"),
                )
            },
            "manual_inputs_status": "awaiting_manual_inputs",
            "evidence": {
                "paper_candidate_packet": str(packet.get("artifact_hash") or "") or None,
                "manual_approval": str(manual_payload.get("artifact_hash") or "") or None,
            },
            "quality_checked": True,
            "promotion_evidence_ready": False,
            "safety": dict(SAFETY_FLAGS),
        },
        decision="blocked_fail_closed_no_paper_no_live",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=[
            "btc_paper_readiness_manual_inputs_incomplete",
            "btc_paper_readiness_approved_paper_review_missing",
            "btc_paper_readiness_current_packet_unapproved",
            *blockers,
        ],
        warnings=[],
        input_hashes={
            "paper_candidate_packet": str(packet.get("artifact_hash") or ""),
            "manual_approval": str(manual_payload.get("artifact_hash") or ""),
        },
    )
    return {
        "perpetual_execution_evidence": execution,
        "manual_approval": manual_payload,
        "paper_candidate_packet": packet,
        "paper_readiness": readiness,
    }


def _build_consistency_report(
    *,
    current_head: str,
    generated: datetime,
    run_id: str,
    dashboard: Mapping[str, Any],
    perpetual_execution_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    dashboard_hash = str(
        _mapping(
            _mapping(dashboard.get("artifacts")).get(
                "perpetual_execution_evidence"
            )
        ).get("artifact_hash")
        or ""
    )
    evidence_hash = str(
        perpetual_execution_evidence.get("artifact_hash") or ""
    )
    blockers = []
    if not dashboard_hash or dashboard_hash != evidence_hash:
        blockers.append(
            "btc_gate_report_consistency:"
            "dashboard_perpetual_execution_evidence_hash_matches_current_artifact"
        )
    return apply_btc_artifact_schema(
        {
            "schema_version": "btc_gate_report_consistency_v1",
            "status": "pass" if not blockers else "blocked_research_only",
            "source_head": current_head,
            "code_commit": current_head,
            "aggregation_batch_id": run_id,
            "run_id": run_id,
            "summary": {
                "dashboard_hash_matches_current_evidence": not blockers
            },
            "source_fingerprints": {},
            "quality_checked": True,
            "promotion_evidence_ready": False,
            "gate": dict(SAFETY_FLAGS),
            "safety": dict(SAFETY_FLAGS),
        },
        decision=(
            "btc_gate_report_consistency_passed_research_only_no_paper_no_live"
            if not blockers
            else "btc_gate_report_consistency_blocked_fail_closed_no_paper_no_live"
        ),
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=[],
        input_hashes={
            "dashboard": str(dashboard.get("artifact_hash") or ""),
            "perpetual_execution_evidence": evidence_hash,
        },
    )


def _build_read_model(
    *,
    current_head: str,
    generated: datetime,
    aggregation_batch_id: str,
    pointer_validation: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    gate_report: Mapping[str, Any],
    dashboard: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = list(evaluation.get("blockers") or [])
    published_safety = _published_read_model_safety()
    owner_by_code = {
        str(row.get("code") or ""): str(row.get("owner") or "")
        for row in evaluation.get("blocker_details", [])
        if isinstance(row, Mapping)
    }
    source_hashes = {
        "pointer": stable_payload_hash(pointer_validation),
        "evaluation": stable_payload_hash(evaluation),
        "gate": str(gate_report.get("artifact_hash") or ""),
        "dashboard": str(dashboard.get("artifact_hash") or ""),
    }
    sources: dict[str, dict[str, Any]] = {}
    for layer in LAYER_IDS:
        relevant = blockers
        if layer == "data":
            relevant = [
                item
                for item in blockers
                if item in {PROMOTION_REBUILD_BLOCKER, DEPTH_FILL_MAPPING_BLOCKER}
            ]
        elif layer in {"oms", "ledger", "replay"}:
            relevant = [
                item
                for item in blockers
                if item
                in {
                    NATURAL_SAMPLE_BLOCKER,
                    FUNDING_OBSERVATION_BLOCKER,
                    PRIVATE_WS_BLOCKER,
                }
            ]
        sources[layer] = {
            "path": (
                DEFAULT_OKX_POINTER_PATH.as_posix()
                if layer == "data"
                else DEFAULT_GATE_PATH.as_posix()
            ),
            "status": "blocked" if relevant else "complete",
            "decision": str(gate_report.get("decision") or ""),
            "readiness_class": str(
                gate_report.get("readiness_class") or "quality_checked"
            ),
            "sha256": source_hashes["pointer" if layer == "data" else "gate"],
            "source_head": current_head,
            "generated_at_utc": generated.isoformat(),
            "freshness": "current",
            "blockers": [
                (
                    f"owner:{owner_by_code[item]} {item}"
                    if owner_by_code.get(item)
                    else item
                )
                for item in relevant
            ],
            "summary": (
                {
                    "current_non_flat_sample_capture_status": (
                        "waiting_for_natural_non_flat_sample"
                        if NATURAL_SAMPLE_BLOCKER in blockers
                        else "observed"
                    )
                }
                if layer == "replay"
                else {}
            ),
        }
    read_model = build_btc_domain_read_model(
        sources=sources,
        source_head=current_head,
        generated_at_utc=generated,
    )
    blocker_codes = [
        str(row.get("code") or "")
        for row in read_model.get("blockers", [])
        if isinstance(row, Mapping)
    ]
    required_blockers = tuple(blocker_codes)
    read_model.update(
        {
            "status": "blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "gate_decision": "blocked_fail_closed_no_paper_no_live",
            "current_stage": "pending_next_stage_gate",
            "freshness": "current_head",
            "readiness_class": "quality_checked",
            "aggregation_batch_id": aggregation_batch_id,
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
            "required_blockers": list(required_blockers),
            "required_blocker_count": len(required_blockers),
            "required_blockers_sha256": stable_payload_hash(
                list(required_blockers)
            ),
            "required_blockers_missing": [],
            "required_blockers_preserved": True,
            "safety": published_safety,
        }
    )
    return read_model


def _published_read_model_safety() -> dict[str, bool]:
    from quant_crypto.application.btc_next_stage_current_head_orchestrator import (
        SAFETY,
    )

    return dict(SAFETY)


def _published_read_model_contract_valid(
    read_model: Mapping[str, Any],
    *,
    current_head: str,
    run_id: str,
    canonical_blockers: Sequence[str],
) -> bool:
    published_safety = _published_read_model_safety()
    blocker_rows = read_model.get("blockers")
    required_blockers = read_model.get("required_blockers")
    canonical = list(canonical_blockers)
    if (
        not isinstance(blocker_rows, list)
        or not isinstance(required_blockers, list)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in required_blockers
        )
        or len(required_blockers) != len(set(required_blockers))
        or any(
            not isinstance(value, str) or not value.strip()
            for value in canonical
        )
        or len(canonical) != len(set(canonical))
    ):
        return False
    if any(
        not isinstance(row, Mapping)
        or not all(
            str(row.get(key) or "").strip()
            for key in ("code", "category", "owner", "next_executable_action")
        )
        for row in blocker_rows
    ):
        return False
    blocker_codes = [
        str(row.get("code") or "").strip()
        for row in blocker_rows
        if isinstance(row, Mapping)
    ]
    if len(blocker_codes) != len(set(blocker_codes)):
        return False
    api_contract = _mapping(read_model.get("api_contract"))
    return (
        read_model.get("schema_version") == "btc_domain_read_model_v1"
        and read_model.get("domain") == "btc"
        and read_model.get("source_head") == current_head
        and read_model.get("code_commit") == current_head
        and read_model.get("freshness") == "current_head"
        and read_model.get("status") == "blocked"
        and read_model.get("current_stage") == "pending_next_stage_gate"
        and read_model.get("decision")
        == "blocked_fail_closed_no_paper_no_live"
        and read_model.get("readiness_class") == "quality_checked"
        and read_model.get("aggregation_batch_id") == run_id
        and read_model.get("promotion_evidence_ready") is False
        and read_model.get("paper_ready") is False
        and read_model.get("live_ready") is False
        and read_model.get("safety") == published_safety
        and len(published_safety) == 49
        and all(value is False for value in published_safety.values())
        and required_blockers == canonical
        and blocker_codes == canonical
        and read_model.get("required_blocker_count") == len(required_blockers)
        and read_model.get("required_blockers_sha256")
        == stable_payload_hash(list(required_blockers))
        and read_model.get("required_blockers_missing") == []
        and read_model.get("required_blockers_preserved") is True
        and read_model.get("blocker_count") == len(blocker_rows)
        and api_contract.get("method") == "GET"
        and api_contract.get("path")
        == "/api/research/btc/domain-read-model"
        and api_contract.get("cache_control") == "no-store"
        and api_contract.get("read_only") is True
        and api_contract.get("side_effects") is False
    )


def _validate_outputs(
    *,
    outputs: Mapping[str, tuple[Path, Mapping[str, Any]]],
    current_head: str,
    run_id: str,
) -> dict[str, bool]:
    gate = outputs["gate"][1]
    dashboard = outputs["dashboard"][1]
    read_model = outputs["read_model"][1]
    safety_containers = [
        gate.get("safety"),
        dashboard.get("safety"),
        read_model.get("safety"),
    ]
    return {
        "gate_artifact_schema_valid": not validate_btc_artifact_schema(gate),
        "dashboard_artifact_schema_valid": not validate_btc_artifact_schema(
            dashboard
        ),
        "supporting_artifact_schemas_valid": all(
            not validate_btc_artifact_schema(payload)
            for name, (_, payload) in outputs.items()
            if name != "read_model"
        ),
        "all_outputs_current_head": all(
            str(payload.get("source_head") or "") == current_head
            for _, payload in outputs.values()
        ),
        "all_batch_ids_match": (
            gate.get("aggregation_batch_id") == run_id
            and dashboard.get("aggregation_batch_id") == run_id
            and read_model.get("aggregation_batch_id") == run_id
        ),
        "read_model_contract_valid": _published_read_model_contract_valid(
            read_model,
            current_head=current_head,
            run_id=run_id,
            canonical_blockers=list(gate.get("blockers") or []),
        ),
        "all_safety_flags_fail_closed": all(
            isinstance(container, Mapping)
            and all(value is False for value in container.values())
            for container in safety_containers
        ),
        "blocked_decision_is_structurally_publishable": (
            bool(gate.get("decision"))
            and isinstance(gate.get("blockers"), list)
            and isinstance(dashboard.get("blockers"), list)
        ),
    }


def _build_rebuild_report(
    *,
    root: Path,
    current_head: str,
    generated: datetime,
    run_id: str,
    pointer_validation: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    outputs: Mapping[str, tuple[Path, Mapping[str, Any]]],
    publication: Mapping[str, Any],
    validation_checks: Mapping[str, bool],
    artifact_reader: BTCRuntimeArtifactReader,
) -> dict[str, Any]:
    output_rows = {
        name: {
            "path": path.as_posix(),
            "sha256": _file_sha256(artifact_reader.resolve(path)),
            "artifact_hash": str(payload.get("artifact_hash") or ""),
            "source_head": str(payload.get("source_head") or ""),
        }
        for name, (path, payload) in outputs.items()
    }
    blockers = list(evaluation.get("blockers") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "source_head": current_head,
        "code_commit": current_head,
        "run_id": run_id,
        "data_version": str(pointer_validation.get("data_version") or ""),
        "status": "complete_blocked" if blockers else "complete",
        "decision": (
            "blocked_fail_closed_no_paper_no_live"
            if blockers
            else "promotion_evidence_ready_manual_review_only_no_paper_no_live"
        ),
        "step_order": list(GATE_STEP_ORDER),
        "authoritative_pointer": dict(pointer_validation),
        "validation_checks": dict(validation_checks),
        "blockers": blockers,
        "blocker_details": list(evaluation.get("blocker_details") or []),
        "outputs": output_rows,
        "snapshot_publication": dict(publication),
        "quality_checked": True,
        "research_ready": evaluation.get("research_ready") is True,
        "backtest_ready": evaluation.get("backtest_ready") is True,
        "promotion_evidence_ready": (
            evaluation.get("promotion_evidence_ready") is True
        ),
        "safety": dict(SAFETY_FLAGS),
        "network_collection_used": False,
        "secret_read_used": False,
        "private_or_order_endpoint_used": False,
    }


def _planned_snapshot_publication(
    *,
    artifact_reader: BTCRuntimeArtifactReader,
    aggregation_batch_id: str,
    generated_at_utc: datetime,
    start_state: GateBuildState,
    end_state: GateBuildState,
    step_order: Sequence[str],
    source_paths: Iterable[Path | str],
    required_paths: Iterable[Path | str],
    validation_checks: Mapping[str, bool],
) -> dict[str, Any]:
    final_dir = (
        artifact_reader.resolve(DEFAULT_GATE_RUNS_ROOT)
        / aggregation_batch_id
    )
    required = {Path(path).as_posix() for path in required_paths}
    logical_paths = sorted(
        {Path(path).as_posix() for path in source_paths} | required
    )
    artifacts: list[dict[str, Any]] = []
    missing_paths: list[str] = []
    for logical_path in logical_paths:
        source = artifact_reader.resolve(logical_path)
        if not source.is_file():
            if logical_path in required:
                missing_paths.append(logical_path)
            continue
        raw = source.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, Mapping):
            payload = {}
        relative = Path(*Path(logical_path).parts[1:])
        snapshot_path = artifact_reader.logical_path(
            final_dir / "files" / relative
        ).as_posix()
        artifacts.append(
            {
                "logical_path": logical_path,
                "snapshot_path": snapshot_path,
                "file_sha256": hashlib.sha256(raw).hexdigest(),
                "file_size_bytes": len(raw),
                "stable_payload_hash": (
                    stable_payload_hash(payload) if payload else ""
                ),
                "aggregation_batch_id": str(
                    payload.get("aggregation_batch_id") or ""
                ),
                "code_commit": str(
                    payload.get("code_commit")
                    or payload.get("commit_hash")
                    or ""
                ),
                "source_file_mtime_ns": source.stat().st_mtime_ns,
            }
        )

    checks = dict(validation_checks)
    checks.update(
        {
            "code_commit_stable": bool(start_state.code_commit)
            and start_state.code_commit == end_state.code_commit,
            "input_snapshot_stable": (
                start_state.input_snapshot_hash
                == end_state.input_snapshot_hash
            ),
            "required_snapshot_artifacts_present": not missing_paths,
        }
    )
    if missing_paths or not all(checks.values()):
        raise CurrentHeadGateRebuildError(
            "btc_current_head_gate_snapshot_plan_not_publishable"
        )
    manifest = {
        "schema_version": GATE_SNAPSHOT_SCHEMA_VERSION,
        "generated_at_utc": _ensure_utc(generated_at_utc).isoformat(),
        "aggregation_batch_id": aggregation_batch_id,
        "status": "complete_immutable_gate_snapshot",
        "decision": (
            "btc_gate_snapshot_validated_for_atomic_pointer_publish"
        ),
        "immutable": True,
        "code_commit": start_state.code_commit,
        "build_state_start": start_state.as_dict(),
        "build_state_end": end_state.as_dict(),
        "step_order": list(step_order),
        "validation_checks": checks,
        "missing_required_paths": missing_paths,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "gate": _gate_snapshot_gate(),
        "guardrails": _gate_snapshot_guardrails(),
    }
    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return {
        "status": "published_immutable_snapshot",
        "published": True,
        "aggregation_batch_id": aggregation_batch_id,
        "run_manifest_path": artifact_reader.logical_path(
            final_dir / "manifest.json"
        ).as_posix(),
        "run_manifest_sha256": hashlib.sha256(
            manifest_bytes
        ).hexdigest(),
        "latest_pointer_path": DEFAULT_GATE_SNAPSHOT_POINTER_PATH.as_posix(),
        "validation_checks": checks,
        "missing_required_paths": missing_paths,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }


def _validate_rebuild_report_for_publish(
    *,
    report: Mapping[str, Any],
    current_head: str,
    run_id: str,
    artifact_reader: BTCRuntimeArtifactReader,
    outputs: Mapping[str, tuple[Path, Mapping[str, Any]]],
) -> None:
    publication = _mapping(report.get("snapshot_publication"))
    if (
        report.get("schema_version") != SCHEMA_VERSION
        or report.get("source_head") != current_head
        or report.get("code_commit") != current_head
        or report.get("run_id") != run_id
        or report.get("quality_checked") is not True
        or publication.get("published") is not True
        or not _is_sha256(publication.get("run_manifest_sha256"))
        or not str(publication.get("run_manifest_path") or "").startswith(
            "artifacts/btc_gate_runs/"
        )
        or any(value is not False for value in report["safety"].values())
    ):
        raise CurrentHeadGateRebuildError(
            "btc_current_head_gate_rebuild_report_validation_failed"
        )
    rows = _mapping(report.get("outputs"))
    for name, (logical_path, _) in outputs.items():
        row = _mapping(rows.get(name))
        physical = artifact_reader.resolve(logical_path)
        if (
            row.get("path") != logical_path.as_posix()
            or not physical.is_file()
            or row.get("sha256") != _file_sha256(physical)
            or row.get("source_head") != current_head
        ):
            raise CurrentHeadGateRebuildError(
                "btc_current_head_gate_rebuild_report_validation_failed:"
                + name
            )


def _publication_matches_plan(
    *,
    publication: Mapping[str, Any],
    planned: Mapping[str, Any],
) -> bool:
    keys = (
        "published",
        "aggregation_batch_id",
        "run_manifest_path",
        "run_manifest_sha256",
        "latest_pointer_path",
        "validation_checks",
        "missing_required_paths",
    )
    return all(publication.get(key) == planned.get(key) for key in keys)


def _restore_rebuild_report(
    *,
    write_session: BTCRuntimeArtifactWriteSession,
    logical_path: Path,
    physical_path: Path,
    previous_payload: bytes | None,
) -> None:
    if previous_payload is None:
        physical_path.unlink(missing_ok=True)
        return
    write_session.write_bytes_atomic(logical_path, previous_payload)


def _validate_artifact_store_pair(
    *,
    reader: BTCRuntimeArtifactReader,
    writer: BTCRuntimeArtifactWriter,
) -> None:
    if (
        reader.artifact_root.resolve(strict=False)
        != writer.artifact_root.resolve(strict=False)
        or reader.repository_identity != writer.repository_identity
    ):
        raise CurrentHeadGateRebuildError(
            "btc_current_head_gate_artifact_store_mismatch"
        )


def _capture_rebuild_state(
    root: Path,
    *,
    current_head: str,
    input_paths: Sequence[Path],
    artifact_reader: BTCRuntimeArtifactReader,
) -> GateBuildState:
    base = capture_gate_build_state(
        root,
        status_paths=DEFAULT_GATE_STATUS_PATHS,
    )
    if base.code_commit != current_head:
        return base
    evidence_hash = stable_payload_hash(
        [_file_fingerprint(artifact_reader, path) for path in input_paths]
    )
    return GateBuildState(
        code_commit=base.code_commit,
        dirty_status_hash=base.dirty_status_hash,
        dirty_paths=base.dirty_paths,
        source_input_hash=base.source_input_hash,
        watched_input_hash=evidence_hash,
        input_snapshot_hash=stable_payload_hash(
            {
                "source_input_hash": base.source_input_hash,
                "evidence_input_hash": evidence_hash,
            }
        ),
    )


def _load_evidence(
    artifact_reader: BTCRuntimeArtifactReader,
    paths: Mapping[str, Path],
) -> dict[str, dict[str, Any]]:
    return {
        name: _payload_with_file_metadata(artifact_reader, path)
        for name, path in paths.items()
    }


def _payload_with_file_metadata(
    artifact_reader: BTCRuntimeArtifactReader,
    path: Path,
) -> dict[str, Any]:
    absolute = artifact_reader.resolve(path)
    payload, digest = _read_json_with_hash(absolute)
    result = dict(payload)
    result["_path"] = path.as_posix()
    result["_file_sha256"] = digest
    result["_file_status"] = "present" if payload else "missing_or_invalid"
    return result


def _stage_outputs(
    *,
    staging: Path,
    outputs: Mapping[str, tuple[Path, Mapping[str, Any]]],
) -> dict[str, Path]:
    if staging.exists():
        raise CurrentHeadGateRebuildError("btc_current_head_gate_staging_exists")
    staging.mkdir(parents=True, exist_ok=False)
    staged: dict[str, Path] = {}
    for name, (_, payload) in outputs.items():
        path = staging / f"{name}.json"
        _write_json_fsync(path, payload)
        staged[name] = path
    return staged


def _read_referenced_json(
    *,
    artifact_reader: BTCRuntimeArtifactReader,
    reference: Mapping[str, str],
    label: str,
    errors: list[str],
) -> tuple[dict[str, Any], str]:
    path_text = str(reference.get("path") or "")
    expected_sha = str(reference.get("sha256") or "")
    if not path_text:
        errors.append(f"{label}:path_missing")
        return {}, ""
    try:
        path = artifact_reader.resolve(path_text)
    except RuntimeError:
        errors.append(f"{label}:path_outside_artifact_root")
        return {}, ""
    payload, actual_sha = _read_json_with_hash(path)
    if not payload:
        errors.append(f"{label}:missing_or_invalid")
    if not _is_sha256(expected_sha):
        errors.append(f"{label}:sha256_missing_or_invalid")
    elif expected_sha != actual_sha:
        errors.append(f"{label}:sha256_mismatch")
    return payload, actual_sha


def _artifact_ref(
    payload: Mapping[str, Any],
    *,
    nested_key: str,
    path_keys: Sequence[str],
    hash_keys: Sequence[str],
) -> dict[str, str]:
    nested = _mapping(payload.get(nested_key))
    return {
        "path": _first_text(nested, "path", *path_keys)
        or _first_text(payload, *path_keys),
        "sha256": _first_text(nested, "sha256", *hash_keys)
        or _first_text(payload, *hash_keys),
    }


def _check_cross_document_identity(
    *,
    label: str,
    payload: Mapping[str, Any],
    source_head: str,
    run_id: str,
    data_version: str,
    errors: list[str],
) -> None:
    if not payload:
        return
    checks = {
        "source_code_commit": (
            _first_text(payload, "source_code_commit", "source_head", "code_commit"),
            source_head,
        ),
        "run_id": (_first_text(payload, "run_id"), run_id),
        "data_version": (_first_text(payload, "data_version"), data_version),
    }
    for field, (observed, expected) in checks.items():
        if not observed:
            errors.append(f"{label}:{field}_missing")
        elif observed != expected:
            errors.append(f"{label}:{field}_mismatch")


def _cross_document_data_identity(
    *,
    pointer: Mapping[str, Any],
    manifest: Mapping[str, Any],
    evidence: Mapping[str, Any],
    errors: list[str],
) -> dict[str, str]:
    fields = ("dataset_id", "aggregate_sha256", "manifest_identity")
    identity = {field: str(pointer.get(field) or "") for field in fields}
    for field, value in identity.items():
        if not value:
            errors.append(f"pointer:{field}_missing")
        elif field == "aggregate_sha256" and not _is_sha256(value):
            errors.append("pointer:aggregate_sha256_invalid")
    for label, payload in (("manifest", manifest), ("evidence", evidence)):
        if not payload:
            continue
        for field, expected in identity.items():
            observed = str(payload.get(field) or "")
            if not observed:
                errors.append(f"{label}:{field}_missing")
            elif observed != expected:
                errors.append(f"{label}:{field}_mismatch")
    return identity


def _verify_data_steward_attestation(
    *,
    artifact_reader: BTCRuntimeArtifactReader,
    pointer: Mapping[str, Any],
    manifest: Mapping[str, Any],
    evidence: Mapping[str, Any],
    source_head: str,
    run_id: str,
    data_version: str,
    data_identity: Mapping[str, str],
    errors: list[str],
) -> dict[str, Any]:
    pointer_rows = _lineage_rows(pointer.get("input_lineage"))
    candidates = [
        row
        for row in pointer_rows
        if str(row.get("kind") or "") == OKX_DATA_STEWARD_ATTESTATION_KIND
    ]
    if len(candidates) != 1:
        errors.append("attestation:lineage_reference_not_unique")
        return {}
    reference = dict(candidates[0])
    required_reference = {
        "kind": OKX_DATA_STEWARD_ATTESTATION_KIND,
        "uri": str(reference.get("uri") or ""),
        "path": str(reference.get("path") or ""),
        "sha256": str(reference.get("sha256") or ""),
        "producer_role": "data_steward",
    }
    if (
        reference.get("producer_role") != "data_steward"
        or not required_reference["uri"]
        or not required_reference["path"]
        or not _is_sha256(required_reference["sha256"])
    ):
        errors.append("attestation:lineage_reference_invalid")
        return {}
    for label, payload in (("manifest", manifest), ("evidence", evidence)):
        if not any(
            all(
                str(row.get(key) or "") == expected
                for key, expected in required_reference.items()
            )
            for row in _lineage_rows(payload.get("input_lineage"))
        ):
            errors.append(f"attestation:{label}_membership_mismatch")

    attestation, actual_sha = _read_referenced_json(
        artifact_reader=artifact_reader,
        reference=reference,
        label="attestation",
        errors=errors,
    )
    checks = {
        "schema_version": OKX_DATA_STEWARD_ATTESTATION_SCHEMA_VERSION,
        "producer_role": "data_steward",
        "immutable_uri": required_reference["uri"],
        "source_code_commit": source_head,
        "run_id": run_id,
        "data_version": data_version,
        **dict(data_identity),
    }
    for field, expected in checks.items():
        observed = (
            _first_text(attestation, "source_code_commit", "source_head")
            if field == "source_code_commit"
            else str(attestation.get(field) or "")
        )
        if not observed:
            errors.append(f"attestation:{field}_missing")
        elif observed != expected:
            errors.append(f"attestation:{field}_mismatch")
    if any(error.startswith("attestation:") for error in errors):
        return {}
    return {
        **required_reference,
        "actual_sha256": actual_sha,
        "dataset_id": data_identity.get("dataset_id", ""),
        "aggregate_sha256": data_identity.get("aggregate_sha256", ""),
        "manifest_identity": data_identity.get("manifest_identity", ""),
        "run_id": run_id,
        "data_version": data_version,
        "verified": True,
    }


def _pointer_result(
    *,
    pointer_path: Path,
    pointer_sha256: str,
    current_head: str,
    errors: Sequence[str],
    source_head: str = "",
    run_id: str = "",
    data_version: str = "",
    immutable_uri: str = "",
    immutable_version: str = "",
    manifest_ref: Mapping[str, str] | None = None,
    manifest_sha256: str = "",
    evidence_ref: Mapping[str, str] | None = None,
    evidence_sha256: str = "",
    input_lineage: Any = None,
    verified_data_steward_attestation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    unique_errors = _dedupe(errors)
    return {
        "schema_version": "btc_okx_native_pointer_validation_v1",
        "status": (
            "valid_current_head" if not unique_errors else "blocked_fail_closed"
        ),
        "pointer_path": pointer_path.as_posix(),
        "pointer_sha256": pointer_sha256,
        "expected_head": current_head,
        "source_code_commit": source_head,
        "run_id": run_id,
        "data_version": data_version,
        "immutable_uri": immutable_uri,
        "immutable_version": immutable_version,
        "manifest": {
            **dict(manifest_ref or {}),
            "actual_sha256": manifest_sha256,
        },
        "evidence": {
            **dict(evidence_ref or {}),
            "actual_sha256": evidence_sha256,
        },
        "input_lineage": input_lineage if input_lineage is not None else [],
        "verified_data_steward_attestation": dict(
            verified_data_steward_attestation or {}
        ),
        "validation_errors": unique_errors,
        "quality_checked": True,
        "promotion_evidence_ready": not unique_errors,
        "safety": dict(SAFETY_FLAGS),
    }


def _lineage_valid(value: Any) -> bool:
    rows: list[Any]
    if isinstance(value, Mapping):
        rows = list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        rows = list(value)
    else:
        return False
    if not rows:
        return False
    for row in rows:
        if isinstance(row, Mapping):
            digest = _first_text(row, "sha256", "hash")
            identity = _first_text(
                row, "uri", "path", "data_version", "immutable_version"
            )
            if not identity or not _is_sha256(digest):
                return False
        elif not _is_sha256(str(row or "")):
            return False
    return True


def _lineage_rows(value: Any) -> list[dict[str, Any]]:
    rows: Sequence[Any]
    if isinstance(value, Mapping):
        rows = list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        rows = list(value)
    else:
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _blocker_owner(blocker: str) -> dict[str, str]:
    mapping = {
        PROMOTION_REBUILD_BLOCKER: {
            "category": "engineering",
            "owner": "btc_research",
            "next_executable_action": (
                "publish_current_head_immutable_okx_backtest_manifest_and_evidence"
            ),
        },
        DEPTH_FILL_MAPPING_BLOCKER: {
            "category": "data_steward",
            "owner": "data_steward",
            "next_executable_action": (
                "publish_timestamp_aligned_immutable_l2_manifest_then_rebuild"
            ),
        },
        NATURAL_SAMPLE_BLOCKER: {
            "category": "natural_time",
            "owner": "btc_observation",
            "next_executable_action": (
                "continue_observe_only_without_signal_or_threshold_changes"
            ),
        },
        FUNDING_OBSERVATION_BLOCKER: {
            "category": "natural_time",
            "owner": "btc_operations",
            "next_executable_action": (
                "observe_natural_funding_cashflow_without_order_authorization"
            ),
        },
        PRIVATE_WS_BLOCKER: {
            "category": "manual_approval",
            "owner": "btc_operations",
            "next_executable_action": (
                "obtain_separate_private_ws_observation_authorization"
            ),
        },
        OBSERVATION_WINDOW_BLOCKER: {
            "category": "natural_time",
            "owner": "btc_observation",
            "next_executable_action": (
                "continue_authorized_okx_demo_until_25_consecutive_real_hours"
            ),
        },
        MANUAL_APPROVAL_BLOCKER: {
            "category": "manual_approval",
            "owner": "architect/manual_reviewer",
            "next_executable_action": "review_current_head_packet_manually",
        },
    }
    return dict(
        mapping.get(
            blocker,
            {
                "category": "engineering",
                "owner": "btc_developer",
                "next_executable_action": (
                    f"resolve_engineering_blocker:{blocker}"
                ),
            },
        )
    )


def _root_cause_id(blocker: str) -> str:
    if blocker == NATURAL_SAMPLE_BLOCKER:
        return "runtime_ready_waiting_non_flat_sample"
    suffix = blocker.partition(":")[2] or blocker
    normalized = "".join(
        char if char.isalnum() else "_" for char in suffix.lower()
    ).strip("_")
    return normalized or "btc_gate_blocked"


def _promotion_evidence_current(
    payload: Mapping[str, Any],
    *,
    current_head: str,
) -> bool:
    return (
        _current_head_payload(payload, current_head=current_head)
        and payload.get("promotion_evidence_ready") is True
        and payload.get("evidence_class") == "promotion_evidence"
    )


def _current_head_payload(
    payload: Mapping[str, Any],
    *,
    current_head: str,
) -> bool:
    return (
        bool(payload)
        and _first_text(
            payload,
            "source_head",
            "source_code_commit",
            "code_commit",
            "commit",
        )
        == current_head
    )


def _truthy_path(payload: Mapping[str, Any], *paths: str) -> bool:
    return any(_nested(payload, path) is True for path in paths)


def _integer_path(payload: Mapping[str, Any], *paths: str) -> int:
    for path in paths:
        try:
            value = int(_nested(payload, path) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return value
    return 0


def _nested(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _file_fingerprint(
    artifact_reader: BTCRuntimeArtifactReader,
    path: Path,
) -> dict[str, Any]:
    absolute = artifact_reader.resolve(path)
    if not absolute.is_file():
        return {"path": path.as_posix(), "status": "missing"}
    return {
        "path": path.as_posix(),
        "status": "present",
        "sha256": _file_sha256(absolute),
        "size_bytes": absolute.stat().st_size,
    }


def _validate_identity(*, current_head: str, run_id: str) -> None:
    if len(current_head) != 40 or not all(
        char in "0123456789abcdef" for char in current_head.lower()
    ):
        raise CurrentHeadGateRebuildError(
            "btc_current_head_gate_invalid_full_head"
        )
    if not run_id or any(char in run_id for char in ("/", "\\", "..")):
        raise CurrentHeadGateRebuildError("btc_current_head_gate_invalid_run_id")


def _read_json_with_hash(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        return {}, ""
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, ""
    return (
        (dict(payload), hashlib.sha256(raw).hexdigest())
        if isinstance(payload, Mapping)
        else ({}, "")
    )


def _write_json_fsync(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        char in "0123456789abcdef" for char in text.lower()
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


__all__ = [
    "CurrentHeadGatePaths",
    "CurrentHeadGateRebuildError",
    "DEFAULT_OKX_POINTER_PATH",
    "DEFAULT_REBUILD_REPORT_PATH",
    "GATE_STEP_ORDER",
    "OKX_POINTER_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "evaluate_current_head_gate_evidence",
    "rebuild_btc_current_head_gate",
    "validate_authoritative_okx_pointer",
]
