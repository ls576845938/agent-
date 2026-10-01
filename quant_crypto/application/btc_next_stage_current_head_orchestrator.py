"""Current-HEAD BTC evidence orchestration on a fresh external artifact root.

The orchestrator is deliberately narrow: it normalizes legacy builder output
inside a run-owned staging area, publishes per-file ``latest`` receipts only
after all fail-closed checks pass, snapshots those receipts immutably, and
updates the formal pointer last.  It never calls a broker, exchange, private
endpoint, order endpoint, paper queue, or network collector.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import jsonschema

from quant_crypto.adapters.okx_public_ws import (
    public_websocket_dependency_receipt,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriteSession,
    BTCRuntimeArtifactWriter,
)
from quant_crypto.application.btc_current_head_gate_rebuild import (
    FUNDING_OBSERVATION_BLOCKER,
    MANUAL_APPROVAL_BLOCKER,
    NATURAL_SAMPLE_BLOCKER,
    PRIVATE_WS_BLOCKER,
    evaluate_current_head_gate_evidence,
)
from quant_crypto.application.btc_domain_read_model import (
    build_btc_domain_read_model,
)
from quant_crypto.application.btc_gate_snapshot import (
    DEFAULT_POINTER_PATH,
    DEFAULT_RUNS_ROOT,
    GateBuildState,
    capture_gate_build_state,
    gate_build_state_is_stable,
    load_latest_gate_snapshot,
    publish_gate_run_snapshot,
)
from quant_crypto.application.btc_next_stage_engineering_evidence import (
    build_btc_next_stage_engineering_evidence,
    resolve_selected_public_ws_dependency,
)
from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_crypto.research.btc_okx_native_promotion_gate import (
    ACTIVE_CRITERIA_LINEAGE_BLOCKER,
    ACTIVE_FAMILY_SCOPE_BLOCKER,
    INFORMATION_COVERAGE_BLOCKER,
    OBSERVATION_WINDOW_BLOCKER,
    load_frozen_active_criteria_prereg,
)
from quant_crypto.research.btc_perpetual_paper_runtime_replay import (
    build_btc_perpetual_paper_runtime_replay_report,
)
from quant_crypto.research.btc_promotion_gate_control import (
    DEFAULT_SOURCE_PATHS as PROMOTION_SOURCE_PATHS,
    build_btc_promotion_gate_control,
)
from quant_crypto.research.btc_strategy_promotion_readiness_review import (
    build_btc_strategy_promotion_readiness_review,
)
from scripts.bootstrap_btc_runtime_artifact_root import (
    BTCRuntimeArtifactBootstrapError,
    bootstrap_btc_runtime_artifact_root,
)
from tools.agent_governance.handoff import validate_handoff_against_git
from tools.agent_governance.shared_data import (
    default_shared_data_root,
    resolve_manifest_payload,
    validate_manifest,
)


SCHEMA_VERSION = "btc_next_stage_current_head_orchestrator_v1"
LAYER_RECEIPT_SCHEMA_VERSION = "btc_next_stage_layer_receipt_v1"
PROMOTION_EVIDENCE_SCHEMA_VERSION = "btc_next_stage_promotion_evidence_v1"
PROMOTION_GATE_SCHEMA_VERSION = "btc_next_stage_promotion_gate_v1"
DATA_TICKET_ID = "DATA-BTC-V3-IMMUTABLE-PUBLIC-MARKET-EVIDENCE-01"
DATA_INTEGRATED_EVENT_ID = (
    "integrated-data-btc-v3-immutable-public-market-evidence-01"
)
ENGINEERING_TICKET_ID = "BTC-V3-NEXT-STAGE-ENGINEERING-CLOSURE-02"
ENGINEERING_INTEGRATED_EVENT_ID = (
    "integrated-btc-v3-next-stage-engineering-closure-02"
)

STEP_ORDER = (
    "validate_head_and_source",
    "validate_manifest_and_handoffs",
    "resolve_shared_data",
    "strategy",
    "oms",
    "ledger",
    "replay",
    "domain_read_model",
    "engineering_evidence_v2",
    "promotion_evidence",
    "gate_decision",
    "validate_safety",
    "atomic_per_file_latest",
    "immutable_snapshot",
    "pointer_atomic_last",
    "reload_verify",
)

LEGACY_REQUIRED_BLOCKERS = (
    "btc_okx_websocket_client_dependency_missing",
    "real_timestamp_aligned_l2_missing",
    "btc_okx_l2_sequence_continuity_unverified",
    "l2_lt_30_natural_days",
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "btc_okx_server_time_offset_exceeds_threshold",
    "manifest_data_schema_mismatch",
    "manifest_quality_status_not_pass",
    "l2_manifest_attestation_readiness_mismatch",
    "runtime_pointer_immutable_snapshot_not_published",
    "runtime_pointer_data_steward_attestation_required",
    "not_promotion_evidence",
    "owner:btc_operations btc_next_stage:real_funding_cashflow_evidence_missing",
    "owner:btc_operations btc_next_stage:real_private_ws_reconciliation_evidence_missing",
    "owner:btc_observation btc_next_stage:real_non_flat_fill_evidence_missing",
    "owner:btc_observation btc_next_stage:natural_observation_window_30_60d_incomplete",
    "owner:architect/manual_reviewer btc_next_stage:manual_promotion_approval_missing",
)
REAL_L2_ATTESTATION_BLOCKERS = (
    "btc_okx_public_ws_primary_connection_reset_10054",
    "btc_okx_public_ws_alternate_dns_resolution_failed",
    "btc_okx_public_ws_l2_no_messages_captured",
    "btc_okx_l2_two_sided_coverage_missing",
    "btc_okx_l2_sequence_continuity_unverified",
    "btc_okx_l2_controlled_recovery_unverified",
    "btc_okx_server_time_offset_exceeds_threshold",
    "btc_okx_l2_natural_observation_30_60_days_missing",
    "btc_private_ws_evidence_missing",
    "btc_real_funding_nonflat_fill_evidence_missing",
    "btc_paper_live_manual_approval_missing",
)
QUALITY_L2_MANIFEST_STATUS = "pass_with_research_only_warnings"
QUALITY_L2_ATTESTATION_PATH = (
    "immutable-export/btc_okx_l2_dataready_attestation.json"
)
QUALITY_L2_CHECKSUM_POLICY = (
    "nonzero_crc32_validated_zero_accepted_after_okx_deprecation"
)
QUALITY_L2_MANIFEST_GUARDRAIL_BLOCKERS = (
    "btc_private_ws_evidence_missing",
    "btc_real_funding_nonflat_fill_evidence_missing",
    "btc_paper_live_manual_approval_missing",
)
QUALITY_L2_REQUIRED_BLOCKERS = (
    INFORMATION_COVERAGE_BLOCKER,
    ACTIVE_FAMILY_SCOPE_BLOCKER,
    ACTIVE_CRITERIA_LINEAGE_BLOCKER,
    "btc_execution_latency_model_missing",
    "btc_queue_model_missing",
    "btc_okx_l2_natural_execution_observation_missing",
    "btc_okx_l2_two_sided_coverage_incomplete",
    "not_promotion_evidence",
    FUNDING_OBSERVATION_BLOCKER,
    PRIVATE_WS_BLOCKER,
    NATURAL_SAMPLE_BLOCKER,
    OBSERVATION_WINDOW_BLOCKER,
    MANUAL_APPROVAL_BLOCKER,
    "btc_next_stage:ledger_positions_cash_pnl_receipts_missing",
    "btc_next_stage:replay_observe_only_offline_no_paper_queue",
)
QUALITY_L2_RESOLVED_BLOCKERS = frozenset(
    {
        "btc_okx_websocket_client_dependency_missing",
        "btc_okx_public_ws_primary_connection_reset_10054",
        "btc_okx_public_ws_primary_tls_reset_10054",
        "btc_okx_public_ws_alternate_dns_resolution_failed",
        "btc_okx_public_ws_l2_no_messages_captured",
        "real_timestamp_aligned_l2_missing",
        "btc_okx_l2_two_sided_coverage_missing",
        "btc_okx_l2_sequence_continuity_unverified",
        "btc_okx_l2_controlled_recovery_unverified",
        "btc_okx_server_time_offset_exceeds_threshold",
        "btc_okx_server_time_offset_unverified",
        "btc_okx_l2_immutable_replay_contract_blocked",
        "btc_okx_l2_checksum_zero_only_independent_validation_unavailable",
        "manifest_data_schema_mismatch",
        "manifest_quality_status_not_pass",
        "l2_manifest_attestation_readiness_mismatch",
        "runtime_pointer_data_steward_attestation_required",
    }
)
_ACTIVE_REQUIRED_BLOCKER_ALIASES = {
    "l2_lt_30_natural_days": INFORMATION_COVERAGE_BLOCKER,
    "btc_open_interest_history_not_verified_diagnostic_partial": (
        ACTIVE_FAMILY_SCOPE_BLOCKER
    ),
    "runtime_pointer_data_steward_attestation_required": (
        ACTIVE_CRITERIA_LINEAGE_BLOCKER
    ),
    "owner:btc_operations btc_next_stage:real_funding_cashflow_evidence_missing": (
        FUNDING_OBSERVATION_BLOCKER
    ),
    "owner:btc_operations btc_next_stage:real_private_ws_reconciliation_evidence_missing": (
        PRIVATE_WS_BLOCKER
    ),
    "owner:btc_observation btc_next_stage:real_non_flat_fill_evidence_missing": (
        NATURAL_SAMPLE_BLOCKER
    ),
    "owner:btc_observation btc_next_stage:natural_observation_window_30_60d_incomplete": (
        OBSERVATION_WINDOW_BLOCKER
    ),
    "owner:architect/manual_reviewer btc_next_stage:manual_promotion_approval_missing": (
        MANUAL_APPROVAL_BLOCKER
    ),
}
CURRENT_DEMO_REQUIRED_BLOCKERS = tuple(
    _ACTIVE_REQUIRED_BLOCKER_ALIASES.get(blocker, blocker)
    for blocker in LEGACY_REQUIRED_BLOCKERS
)
REQUIRED_BLOCKERS = (
    REAL_L2_ATTESTATION_BLOCKERS[0],
    *CURRENT_DEMO_REQUIRED_BLOCKERS[1:],
)
REQUIRED_BLOCKERS_SHA256 = stable_payload_hash(list(REQUIRED_BLOCKERS))

LATEST_PATHS: dict[str, Path] = {
    "strategy": Path(
        "artifacts/btc_next_stage_current_head_receipts/latest/"
        "btc_strategy_receipt.json"
    ),
    "oms": Path(
        "artifacts/btc_next_stage_current_head_receipts/latest/"
        "btc_oms_receipt.json"
    ),
    "ledger": Path(
        "artifacts/btc_next_stage_current_head_receipts/latest/"
        "btc_ledger_receipt.json"
    ),
    "replay": Path(
        "artifacts/btc_next_stage_current_head_receipts/latest/"
        "btc_replay_receipt.json"
    ),
    "domain": Path(
        "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
    ),
    "engineering": Path(
        "artifacts/btc_next_stage_engineering_evidence/latest/"
        "btc_next_stage_engineering_evidence.json"
    ),
    "promotion": Path(
        "artifacts/btc_next_stage_promotion_evidence/latest/"
        "btc_next_stage_promotion_evidence.json"
    ),
    "gate": Path(
        "artifacts/btc_next_stage_promotion_gate/latest/"
        "btc_next_stage_promotion_gate_report.json"
    ),
    "orchestrator": Path(
        "artifacts/btc_next_stage_current_head_orchestrator/latest/"
        "btc_next_stage_current_head_orchestrator_report.json"
    ),
}

SOURCE_PATHS = (
    "quant_crypto/application/btc_next_stage_current_head_orchestrator.py",
    "scripts/build_btc_next_stage_current_head_orchestrator.py",
    "schemas/btc_next_stage_current_head_orchestrator.schema.json",
    "schemas/btc_next_stage_engineering_evidence.schema.json",
    "tests/contracts/test_btc_next_stage_current_head_orchestrator.py",
)

SAFETY = {
    "api_key_permission_reviewed": False,
    "approval_granted": False,
    "broker_access_allowed": False,
    "broker_calls_used": False,
    "broker_endpoint_accessed": False,
    "broker_endpoint_allowed": False,
    "broker_or_order_allowed": False,
    "credential_permissions_verified": False,
    "demo_allowed": False,
    "demo_order_submitted": False,
    "demo_trading_enabled": False,
    "live_allowed": False,
    "paper_allowed": False,
    "live_enabled": False,
    "live_order_allowed": False,
    "live_ready": False,
    "live_unlock_allowed": False,
    "manual_approval_recorded": False,
    "micro_live_allowed": False,
    "network_accessed": False,
    "oms_access_allowed": False,
    "order_endpoint_accessed": False,
    "order_endpoint_allowed": False,
    "order_endpoint_used": False,
    "order_submission_allowed": False,
    "paper_candidate_allowed": False,
    "paper_candidate_created": False,
    "paper_execution_authorized": False,
    "paper_order_intake_allowed": False,
    "paper_order_submitted": False,
    "paper_or_live_unlock_allowed": False,
    "paper_queue_write_allowed": False,
    "paper_queue_write_enabled": False,
    "paper_ready": False,
    "paper_start_allowed": False,
    "permission_evidence_ready": False,
    "permission_granted": False,
    "position_increase_allowed": False,
    "private_endpoint_accessed": False,
    "private_endpoint_allowed": False,
    "private_endpoint_used": False,
    "promotion_allowed": False,
    "promotion_evidence_ready": False,
    "real_order_submitted": False,
    "real_orders_enabled": False,
    "secret_access_allowed": False,
    "secrets_read": False,
    "strategy_skeleton_generated": False,
    "withdraw_allowed": False,
}

SENSITIVE_TRUE_KEYS = frozenset(SAFETY)
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


class BTCNextStageOrchestratorError(RuntimeError):
    """A stable fail-closed orchestrator error code."""


@dataclass(frozen=True)
class ValidatedInputs:
    manifest: Mapping[str, Any]
    data_handoff: Mapping[str, Any]
    engineering_handoff: Mapping[str, Any]
    manifest_path: Path
    data_handoff_path: Path
    engineering_handoff_path: Path
    raw_hashes: Mapping[str, str]
    data_root: Path
    real_l2_manifest: Mapping[str, Any] | None = None
    real_l2_manifest_path: Path | None = None
    real_l2_receipt: Mapping[str, Any] | None = None
    real_l2_root: Path | None = None


@dataclass(frozen=True)
class LegacyOutputs:
    paper_report: Mapping[str, Any]
    paper_report_path: Path
    reconciliation_path: Path
    strategy_report: Mapping[str, Any]
    strategy_report_path: Path


FailureInjector = Callable[[str], None]


def run_btc_next_stage_current_head_orchestrator(
    *,
    repo_root: Path,
    expected_head: str,
    run_id: str,
    data_manifest: Path,
    data_integrated_handoff: Path,
    engineering_integrated_handoff: Path,
    real_l2_attestation_manifest: Path | None = None,
    real_l2_attestation_shared_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    failure_injector: FailureInjector | None = None,
) -> dict[str, Any]:
    """Run one fresh-root, current-HEAD, blocked evidence publication."""

    root = repo_root.resolve()
    generated = datetime.now(timezone.utc)
    completed: list[str] = []
    _validate_head_and_run(root, expected_head=expected_head, run_id=run_id)
    _complete_step(completed, STEP_ORDER[0], failure_injector)

    inputs = _validate_inputs(
        root,
        expected_head=expected_head,
        data_manifest=data_manifest,
        data_integrated_handoff=data_integrated_handoff,
        engineering_integrated_handoff=engineering_integrated_handoff,
        real_l2_attestation_manifest=real_l2_attestation_manifest,
    )
    _complete_step(completed, STEP_ORDER[1], failure_injector)

    try:
        data_root = resolve_manifest_payload(
            inputs.manifest,
            shared_root=default_shared_data_root(root),
            verify_files=True,
        )
    except Exception as exc:
        raise BTCNextStageOrchestratorError(_safe_error_code(exc)) from exc
    inputs = replace(inputs, data_root=data_root.resolve())
    if inputs.real_l2_manifest is None:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_attestation_manifest_missing"
        )
    if real_l2_attestation_shared_root is None:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_attestation_shared_root_missing"
        )
    try:
        real_l2_root = resolve_manifest_payload(
            inputs.real_l2_manifest,
            shared_root=real_l2_attestation_shared_root,
            verify_files=True,
        )
        real_l2_receipt = _load_real_l2_attestation_receipt(
            manifest=inputs.real_l2_manifest,
            data_root=real_l2_root,
        )
    except Exception as exc:
        raise BTCNextStageOrchestratorError(_safe_error_code(exc)) from exc
    receipt_sha256 = str(
        _real_l2_attestation_file_row(inputs.real_l2_manifest).get(
            "sha256"
        )
        or ""
    )
    inputs = replace(
        inputs,
        real_l2_receipt=real_l2_receipt,
        real_l2_root=real_l2_root.resolve(),
        raw_hashes={
            **inputs.raw_hashes,
            "real_l2_attestation_receipt": receipt_sha256,
        },
    )
    _complete_step(completed, STEP_ORDER[2], failure_injector)

    values = os.environ if environment is None else environment
    raw_artifact_root = str(values.get(ENVIRONMENT_VARIABLE, "") or "").strip()
    if not raw_artifact_root:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_artifact_root_env_missing"
        )
    artifact_root = Path(raw_artifact_root)
    try:
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=root,
            artifact_root=artifact_root,
        )
        writer = BTCRuntimeArtifactWriter.from_environment(
            source_repo_root=root,
            environment=values,
        )
    except Exception as exc:
        raise BTCNextStageOrchestratorError(_safe_error_code(exc)) from exc

    return _run_with_writer(
        repo_root=root,
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated,
        inputs=inputs,
        writer=writer,
        completed_steps=completed,
        failure_injector=failure_injector,
    )


def _run_with_writer(
    *,
    repo_root: Path,
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
    inputs: ValidatedInputs,
    writer: BTCRuntimeArtifactWriter,
    completed_steps: list[str] | None = None,
    failure_injector: FailureInjector | None = None,
) -> dict[str, Any]:
    completed = list(completed_steps or STEP_ORDER[:3])
    _assert_legacy_builder_api()
    try:
        with writer.exclusive() as session:
            return _execute_locked(
                repo_root=repo_root,
                expected_head=expected_head,
                run_id=run_id,
                generated_at_utc=generated_at_utc,
                inputs=inputs,
                session=session,
                completed_steps=completed,
                failure_injector=failure_injector,
            )
    except BTCNextStageOrchestratorError:
        raise
    except Exception as exc:
        raise BTCNextStageOrchestratorError(_safe_error_code(exc)) from exc


def _execute_locked(
    *,
    repo_root: Path,
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
    inputs: ValidatedInputs,
    session: BTCRuntimeArtifactWriteSession,
    completed_steps: list[str],
    failure_injector: FailureInjector | None,
) -> dict[str, Any]:
    stage_root = Path(
        "artifacts/btc_next_stage_current_head_orchestrator/staging", run_id
    )
    stage_physical = session.resolve(stage_root)
    if stage_physical.exists():
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_run_staging_exists"
        )
    stage_physical.mkdir(parents=True, exist_ok=False)
    start_state = capture_gate_build_state(
        repo_root,
        status_paths=(*SOURCE_PATHS, *_input_relative_paths(repo_root, inputs)),
    )
    if start_state.code_commit != expected_head:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_start_head_mismatch"
        )

    bundle_dir, config_path, placeholder_path, observation_paths = (
        _stage_explicit_legacy_inputs(
            session=session,
            stage_root=stage_root,
            inputs=inputs,
            expected_head=expected_head,
        )
    )
    del bundle_dir
    with _working_directory(repo_root):
        legacy = _build_strategy_and_runtime(
            repo_root=repo_root,
            stage_physical=stage_physical,
            config_path=config_path,
            placeholder_path=placeholder_path,
            observation_paths=observation_paths,
            expected_head=expected_head,
            run_id=run_id,
            generated_at_utc=generated_at_utc,
        )

    staged: dict[str, Path] = {}
    receipt_payloads: dict[str, dict[str, Any]] = {}
    strategy_receipt = _layer_receipt(
        inputs=inputs,
        layer="strategy",
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated_at_utc,
        logical_path=LATEST_PATHS["strategy"],
        legacy_payload=legacy.strategy_report,
        legacy_path=legacy.strategy_report_path,
        extra_blockers=("pending_next_stage_gate",),
        input_hashes=inputs.raw_hashes,
    )
    staged["strategy"] = _write_staged_json(
        session, stage_root / "normalized/strategy.json", strategy_receipt
    )
    receipt_payloads["strategy"] = strategy_receipt
    _complete_step(completed_steps, "strategy", failure_injector)

    oms_receipt = _layer_receipt(
        inputs=inputs,
        layer="oms",
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated_at_utc,
        logical_path=LATEST_PATHS["oms"],
        legacy_payload=legacy.paper_report,
        legacy_path=legacy.paper_report_path,
        extra_blockers=(
            "btc_next_stage:oms_offline_intent_lifecycle_reconciliation_only",
        ),
        input_hashes=inputs.raw_hashes,
    )
    staged["oms"] = _write_staged_json(
        session, stage_root / "normalized/oms.json", oms_receipt
    )
    receipt_payloads["oms"] = oms_receipt
    _complete_step(completed_steps, "oms", failure_injector)

    reconciliation = _read_json(legacy.reconciliation_path)
    ledger_receipt = _layer_receipt(
        inputs=inputs,
        layer="ledger",
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated_at_utc,
        logical_path=LATEST_PATHS["ledger"],
        legacy_payload=reconciliation,
        legacy_path=legacy.reconciliation_path,
        extra_blockers=(
            "btc_next_stage:ledger_positions_cash_pnl_receipts_missing",
        ),
        input_hashes={
            **inputs.raw_hashes,
            "oms_report": _sha256_file(legacy.paper_report_path),
        },
    )
    ledger_receipt["pnl_derived_from_fills_positions_cash"] = False
    staged["ledger"] = _write_staged_json(
        session, stage_root / "normalized/ledger.json", ledger_receipt
    )
    receipt_payloads["ledger"] = ledger_receipt
    _complete_step(completed_steps, "ledger", failure_injector)

    replay_receipt = _layer_receipt(
        inputs=inputs,
        layer="replay",
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated_at_utc,
        logical_path=LATEST_PATHS["replay"],
        legacy_payload=legacy.paper_report,
        legacy_path=legacy.paper_report_path,
        extra_blockers=(
            "btc_next_stage:replay_observe_only_offline_no_paper_queue",
        ),
        input_hashes=inputs.raw_hashes,
    )
    staged["replay"] = _write_staged_json(
        session, stage_root / "normalized/replay.json", replay_receipt
    )
    receipt_payloads["replay"] = replay_receipt
    _complete_step(completed_steps, "replay", failure_injector)

    source_map = _domain_source_map(
        repo_root=repo_root,
        inputs=inputs,
        receipts=receipt_payloads,
        staged=staged,
        expected_head=expected_head,
        generated_at_utc=generated_at_utc,
    )
    domain = build_btc_domain_read_model(
        sources=source_map,
        source_head=expected_head,
        generated_at_utc=generated_at_utc,
    )
    domain.update(
        {
            "status": "blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "current_stage": "pending_next_stage_gate",
            "aggregation_batch_id": run_id,
            "safety": dict(SAFETY),
        }
    )
    _apply_required_blocker_preservation(
        domain,
        require_in_ordinary_blockers=False,
        ordinary_required_blockers=_ordinary_required_blockers(inputs),
    )
    staged["domain"] = _write_staged_json(
        session, stage_root / "normalized/domain.json", domain
    )
    _complete_step(completed_steps, "domain_read_model", failure_injector)

    engineering = _build_engineering_evidence(
        repo_root=repo_root,
        inputs=inputs,
        receipts=receipt_payloads,
        staged=staged,
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated_at_utc,
    )
    _apply_required_blocker_preservation(
        engineering,
        ordinary_required_blockers=_ordinary_required_blockers(inputs),
        metadata_required_blockers=REQUIRED_BLOCKERS,
    )
    engineering.pop("artifact_hash", None)
    engineering["artifact_hash"] = stable_payload_hash(engineering)
    _validate_schema(
        repo_root / "schemas/btc_next_stage_engineering_evidence.schema.json",
        engineering,
    )
    staged["engineering"] = _write_staged_json(
        session, stage_root / "normalized/engineering.json", engineering
    )
    _complete_step(
        completed_steps, "engineering_evidence_v2", failure_injector
    )

    promotion = _promotion_evidence(
        inputs=inputs,
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated_at_utc,
        strategy_report=legacy.strategy_report,
        strategy_report_path=legacy.strategy_report_path,
        engineering_path=staged["engineering"],
    )
    staged["promotion"] = _write_staged_json(
        session, stage_root / "normalized/promotion.json", promotion
    )
    _complete_step(completed_steps, "promotion_evidence", failure_injector)

    with _working_directory(repo_root):
        gate = _gate_decision(
            inputs=inputs,
            repo_root=repo_root,
            stage_physical=stage_physical,
            expected_head=expected_head,
            run_id=run_id,
            generated_at_utc=generated_at_utc,
            legacy=legacy,
            placeholder_path=placeholder_path,
            promotion_path=staged["promotion"],
        )
    staged["gate"] = _write_staged_json(
        session, stage_root / "normalized/gate.json", gate
    )
    _complete_step(completed_steps, "gate_decision", failure_injector)

    _finalize_engineering_builder_chain(
        engineering=engineering,
        staged=staged,
    )
    _validate_schema(
        repo_root / "schemas/btc_next_stage_engineering_evidence.schema.json",
        engineering,
    )
    staged["engineering"] = _write_staged_json(
        session, stage_root / "normalized/engineering.json", engineering
    )

    end_state = capture_gate_build_state(
        repo_root,
        status_paths=(*SOURCE_PATHS, *_input_relative_paths(repo_root, inputs)),
    )
    if not gate_build_state_is_stable(start_state, end_state):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_head_or_source_drift"
        )
    if end_state.code_commit != expected_head:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_end_head_mismatch"
        )

    orchestrator_report = _orchestrator_report(
        expected_head=expected_head,
        run_id=run_id,
        generated_at_utc=generated_at_utc,
        inputs=inputs,
        start_state=start_state,
        end_state=end_state,
        staged=staged,
    )
    _assert_all_safety_false(
        {
            **receipt_payloads,
            "domain": domain,
            "engineering": engineering,
            "promotion": promotion,
            "gate": gate,
            "orchestrator": orchestrator_report,
        }
    )
    _validate_schema(
        repo_root / "schemas/btc_next_stage_current_head_orchestrator.schema.json",
        orchestrator_report,
    )
    staged["orchestrator"] = _write_staged_json(
        session, stage_root / "normalized/orchestrator.json", orchestrator_report
    )
    _complete_step(completed_steps, "validate_safety", failure_injector)

    for artifact_id, formal_path in LATEST_PATHS.items():
        session.write_bytes_atomic(formal_path, staged[artifact_id].read_bytes())
    _complete_step(
        completed_steps, "atomic_per_file_latest", failure_injector
    )

    validation_checks = {
        "expected_head_current": end_state.code_commit == expected_head,
        "source_and_input_stable": gate_build_state_is_stable(
            start_state, end_state
        ),
        "step_order_exact": tuple(completed_steps)
        == STEP_ORDER[: len(completed_steps)],
        "required_blockers_exact_current": _preservation_valid(
            orchestrator_report
        ),
        "all_safety_false": True,
        "engineering_schema_valid": True,
        "orchestrator_schema_valid": True,
    }
    candidate_pointer = stage_root / "candidate_latest_pointer.json"
    publication = publish_gate_run_snapshot(
        repo_root=repo_root,
        aggregation_batch_id=run_id,
        generated_at_utc=generated_at_utc,
        start_state=start_state,
        end_state=end_state,
        step_order=STEP_ORDER,
        source_paths=LATEST_PATHS.values(),
        required_paths=LATEST_PATHS.values(),
        validation_checks=validation_checks,
        runs_root=DEFAULT_RUNS_ROOT,
        pointer_path=candidate_pointer,
        artifact_reader=session.writer,
        artifact_writer=session.writer,
        write_session=session,
    )
    if publication.get("published") is not True:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_snapshot_not_publishable"
        )
    candidate_reload = load_latest_gate_snapshot(
        repo_root,
        pointer_path=candidate_pointer,
        expected_head=expected_head,
        artifact_reader=session.writer,
    )
    if candidate_reload.get("status") != "valid":
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_candidate_snapshot_reload_failed"
        )
    _complete_step(completed_steps, "immutable_snapshot", failure_injector)

    formal_pointer = session.resolve(DEFAULT_POINTER_PATH)
    previous_pointer = (
        formal_pointer.read_bytes() if formal_pointer.is_file() else None
    )
    formal_pointer_written = False
    try:
        candidate_bytes = session.writer.read_bytes(candidate_pointer)
        session.write_bytes_atomic(DEFAULT_POINTER_PATH, candidate_bytes)
        formal_pointer_written = True
        _complete_step(
            completed_steps, "pointer_atomic_last", failure_injector
        )
        reload_result = load_latest_gate_snapshot(
            repo_root,
            pointer_path=DEFAULT_POINTER_PATH,
            expected_head=expected_head,
            artifact_reader=session.writer,
        )
        if reload_result.get("status") != "valid":
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_formal_pointer_reload_failed"
            )
        _complete_step(completed_steps, "reload_verify", failure_injector)
    except Exception:
        if formal_pointer_written:
            if previous_pointer is None:
                formal_pointer.unlink(missing_ok=True)
            else:
                session.write_bytes_atomic(
                    DEFAULT_POINTER_PATH, previous_pointer
                )
        raise

    result = dict(orchestrator_report)
    result["completed_steps"] = list(completed_steps)
    result["publication_result"] = publication
    result["reload_verification"] = {
        "status": "valid",
        "pointer_path": DEFAULT_POINTER_PATH.as_posix(),
        "manifest_sha256": str(
            reload_result.get("pointer", {}).get("manifest_sha256") or ""
        ),
    }
    return result


def _validate_head_and_run(
    repo_root: Path, *, expected_head: str, run_id: str
) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_expected_head_invalid"
        )
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_run_id_invalid"
        )
    actual = _git(repo_root, "rev-parse", "HEAD")
    if actual != expected_head:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_expected_head_mismatch"
        )


def _validate_inputs(
    repo_root: Path,
    *,
    expected_head: str,
    data_manifest: Path,
    data_integrated_handoff: Path,
    engineering_integrated_handoff: Path,
    real_l2_attestation_manifest: Path | None,
) -> ValidatedInputs:
    manifest_path, manifest, manifest_raw = _load_repo_json(
        repo_root, data_manifest, required_prefix=".agent/data_manifests/"
    )
    data_path, data_event, data_raw = _load_repo_json(
        repo_root,
        data_integrated_handoff,
        required_prefix=".agent/handoffs/",
    )
    engineering_path, engineering_event, engineering_raw = _load_repo_json(
        repo_root,
        engineering_integrated_handoff,
        required_prefix=".agent/handoffs/",
    )
    if real_l2_attestation_manifest is None:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_attestation_manifest_missing"
        )
    (
        real_l2_manifest_path,
        real_l2_manifest,
        real_l2_manifest_raw,
    ) = _load_repo_json(
        repo_root,
        real_l2_attestation_manifest,
        required_prefix=".agent/data_manifests/",
    )
    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_manifest_invalid:"
            + manifest_errors[0]
        )
    real_l2_manifest_errors = validate_manifest(real_l2_manifest)
    if real_l2_manifest_errors:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_manifest_invalid:"
            + real_l2_manifest_errors[0]
        )
    _validate_real_l2_manifest_identity(real_l2_manifest)
    for label, payload in (
        ("data", data_event),
        ("engineering", engineering_event),
    ):
        errors = validate_handoff_against_git(payload, repo_root=repo_root)
        if errors:
            raise BTCNextStageOrchestratorError(
                f"btc_next_stage_orchestrator_{label}_handoff_invalid:"
                + errors[0]
            )
    if (
        data_event.get("ticket_id") != DATA_TICKET_ID
        or data_event.get("event_id") != DATA_INTEGRATED_EVENT_ID
        or data_event.get("event_type") != "integrated"
    ):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_data_handoff_identity_mismatch"
        )
    if (
        engineering_event.get("ticket_id") != ENGINEERING_TICKET_ID
        or engineering_event.get("event_id")
        != ENGINEERING_INTEGRATED_EVENT_ID
        or engineering_event.get("event_type") != "integrated"
    ):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_engineering_handoff_identity_mismatch"
        )
    if list(engineering_event.get("blockers") or []) != list(
        LEGACY_REQUIRED_BLOCKERS
    ):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_required_blockers_not_exact_17"
        )
    for event in (data_event, engineering_event):
        commit = str(event.get("deliverable_commit") or "")
        if not _git_is_ancestor(repo_root, commit, expected_head):
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_handoff_commit_not_head_ancestor"
            )
    return ValidatedInputs(
        manifest=manifest,
        data_handoff=data_event,
        engineering_handoff=engineering_event,
        manifest_path=manifest_path,
        data_handoff_path=data_path,
        engineering_handoff_path=engineering_path,
        raw_hashes={
            "data_manifest": hashlib.sha256(manifest_raw).hexdigest(),
            "data_integrated_handoff": hashlib.sha256(data_raw).hexdigest(),
            "engineering_integrated_handoff": hashlib.sha256(
                engineering_raw
            ).hexdigest(),
            "real_l2_attestation_manifest": hashlib.sha256(
                real_l2_manifest_raw
            ).hexdigest(),
            "expected_head": hashlib.sha256(
                expected_head.encode("ascii")
            ).hexdigest(),
        },
        data_root=Path(),
        real_l2_manifest=real_l2_manifest,
        real_l2_manifest_path=real_l2_manifest_path,
    )


def _load_real_l2_attestation_receipt(
    *,
    manifest: Mapping[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    row = _real_l2_attestation_file_row(manifest)
    evidence_path = data_root / str(row["path"])
    if (
        not evidence_path.is_file()
        or evidence_path.stat().st_size != int(row.get("bytes") or -1)
        or _sha256_file(evidence_path) != str(row.get("sha256") or "")
    ):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_evidence_hash_mismatch"
        )
    receipt = _read_json(evidence_path)
    if manifest.get("quality_status") == QUALITY_L2_MANIFEST_STATUS:
        return _normalize_quality_l2_attestation(
            manifest=manifest,
            attestation=receipt,
        )
    if (
        receipt.get("ticket_id") != "DATA-BTC-REAL-L2-ATTESTATION-04"
        or receipt.get("status") != "blocked"
        or list(receipt.get("blockers") or [])
        != list(REAL_L2_ATTESTATION_BLOCKERS)
    ):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_receipt_identity_mismatch"
        )
    attempts = list(receipt.get("public_ws_attempts") or [])
    sequence = dict(receipt.get("sequence") or {})
    recovery = dict(receipt.get("controlled_recovery") or {})
    clock = dict(receipt.get("server_clock") or {})
    readiness = dict(receipt.get("readiness") or {})
    safety = dict(receipt.get("safety") or {})
    if (
        len(attempts) != 2
        or attempts[0].get("message_count") != 0
        or attempts[0].get("winerror") != 10054
        or attempts[1].get("message_count") != 0
        or attempts[1].get("error") != "getaddrinfo failed"
        or sequence.get("real_message_count") != 0
        or sequence.get("two_sided") is not False
        or sequence.get("sequence_continuity_verified") is not False
        or recovery.get("executed") is not False
        or clock.get("valid_sample_count") != 9
        or clock.get("abs_offset_p50_ms") != 4829.779
        or clock.get("abs_offset_p95_ms") != 5424.47
        or clock.get("abs_offset_max_ms") != 5431.406
        or clock.get("max_allowed_abs_offset_ms") != 2000.0
        or clock.get("offset_verified") is not False
        or any(value is not False for value in readiness.values())
        or any(value is not False for value in safety.values())
    ):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_receipt_contract_mismatch"
        )
    return receipt


def _validate_real_l2_manifest_identity(
    manifest: Mapping[str, Any],
) -> None:
    if manifest.get("dataset_id") != "btc-okx-real-l2-attestation":
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_manifest_identity_mismatch"
        )
    quality_status = str(manifest.get("quality_status") or "")
    if quality_status == "blocked":
        valid = list(manifest.get("blockers") or []) == list(
            REAL_L2_ATTESTATION_BLOCKERS[:7]
        )
    elif quality_status == QUALITY_L2_MANIFEST_STATUS:
        blockers = [str(item) for item in manifest.get("blockers") or []]
        producer_commit = str(manifest.get("producer_commit") or "")
        valid = (
            manifest.get("readiness_class") == "quality_checked"
            and manifest.get("producer_role") == "data_steward"
            and re.fullmatch(r"[0-9a-f]{40}", producer_commit) is not None
            and str(manifest.get("dataset_version") or "").endswith(
                "timestamp-precision07-quality1"
            )
            and len(blockers) == len(set(blockers))
            and blockers
            and _real_l2_attestation_file_row(manifest).get("path")
            == QUALITY_L2_ATTESTATION_PATH
        )
    else:
        valid = False
    if not valid:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_manifest_identity_mismatch"
        )


def _real_l2_attestation_file_row(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    quality_status = str(manifest.get("quality_status") or "")
    if quality_status == QUALITY_L2_MANIFEST_STATUS:
        rows = [
            dict(row)
            for row in manifest.get("files", [])
            if str(row.get("path") or "") == QUALITY_L2_ATTESTATION_PATH
        ]
    else:
        rows = [
            dict(row)
            for row in manifest.get("files", [])
            if str(row.get("path") or "").endswith(
                "receipt/blocked-receipt.json"
            )
        ]
    if len(rows) != 1:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_receipt_not_unique"
        )
    return rows[0]


def _normalize_quality_l2_attestation(
    *,
    manifest: Mapping[str, Any],
    attestation: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_blockers = [
        str(item) for item in manifest.get("blockers") or []
    ]
    attestation_blockers = [
        str(item) for item in attestation.get("promotion_blockers") or []
    ]
    expected_manifest_blockers = [
        *attestation_blockers,
        *QUALITY_L2_MANIFEST_GUARDRAIL_BLOCKERS,
    ]
    readiness = dict(attestation.get("readiness") or {})
    guardrails = dict(attestation.get("guardrails") or {})
    required_guardrails = {
        "broker_call_used",
        "order_endpoint_used",
        "paper_or_live_unlock_allowed",
        "private_endpoint_used",
        "promotion_unlock_allowed",
        "real_order_submitted",
    }
    max_clock_offset = attestation.get("max_clock_offset_ms")
    max_clock_policy = attestation.get("max_clock_lag_policy_ms")
    sequence_zero_fields = (
        "sequence_gap_count",
        "duplicate_sequence_count",
        "out_of_order_sequence_count",
        "unrecovered_gap_count",
    )
    if (
        attestation.get("schema_version")
        != "btc_okx_l2_dataready_attestation_v1"
        or attestation.get("dataset_id")
        != "btc-okx-timestamp-aligned-public-l2-history"
        or attestation.get("dataset_version")
        != manifest.get("dataset_version")
        or attestation.get("producer_role")
        != manifest.get("producer_role")
        or attestation.get("source_head")
        != manifest.get("producer_commit")
        or attestation.get("venue") != "okx"
        or attestation.get("instrument_id") != "BTC-USDT-SWAP"
        or attestation.get("quality_checked") is not True
        or attestation.get("promotion_evidence_ready") is not False
        or readiness
        != {
            "backtest_ready": False,
            "promotion_evidence_ready": False,
            "quality_checked": True,
            "research_ready": False,
        }
        or attestation.get("sequence_validation_status") != "pass"
        or any(attestation.get(field) != 0 for field in sequence_zero_fields)
        or attestation.get("clock_offset_attested") is not True
        or not isinstance(max_clock_offset, (int, float))
        or not isinstance(max_clock_policy, (int, float))
        or float(max_clock_offset) > float(max_clock_policy)
        or attestation.get("checksum_policy") != QUALITY_L2_CHECKSUM_POLICY
        or int(attestation.get("checksum_observed_count") or 0) <= 0
        or not required_guardrails.issubset(guardrails)
        or any(value is not False for value in guardrails.values())
        or manifest_blockers != expected_manifest_blockers
    ):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_real_l2_quality_contract_mismatch"
        )
    book_count = int(attestation.get("book_record_count") or 0)
    two_sided_count = int(
        attestation.get("two_sided_snapshot_count") or 0
    )
    reconnect_count = int(attestation.get("reconnect_count") or 0)
    return {
        "status": "quality_checked",
        "decision": (
            "real_public_l2_timestamp_sequence_recovery_and_clock_"
            "quality_checked_research_only_no_paper_no_live"
        ),
        "public_ws_attempts": [
            {
                "message_count": book_count,
                "status": "quality_checked",
            }
        ],
        "sequence": {
            "real_message_count": book_count,
            "two_sided": book_count > 0 and two_sided_count == book_count,
            "sequence_continuity_verified": True,
            "sequence_gap_count": 0,
            "duplicate_sequence_count": 0,
            "out_of_order_sequence_count": 0,
            "validation_status": "pass",
            "checksum_policy": QUALITY_L2_CHECKSUM_POLICY,
        },
        "controlled_recovery": {
            "executed": reconnect_count > 0,
            "verified": True,
            "reconnect_count": reconnect_count,
            "unrecovered_gap_count": 0,
        },
        "server_clock": {
            "offset_verified": True,
            "abs_offset_max_ms": float(max_clock_offset),
            "max_allowed_abs_offset_ms": float(max_clock_policy),
        },
        "readiness": readiness,
        "safety": guardrails,
        "blockers": manifest_blockers,
    }


def _real_l2_attestation_summary(
    inputs: ValidatedInputs,
) -> dict[str, Any]:
    manifest = dict(inputs.real_l2_manifest or {})
    receipt = dict(inputs.real_l2_receipt or {})
    return {
        "dataset_version": str(manifest.get("dataset_version") or ""),
        "manifest_sha256": str(
            inputs.raw_hashes.get("real_l2_attestation_manifest") or ""
        ),
        "aggregate_sha256": str(manifest.get("aggregate_sha256") or ""),
        "receipt_sha256": str(
            inputs.raw_hashes.get("real_l2_attestation_receipt") or ""
        ),
        "producer_commit": str(manifest.get("producer_commit") or ""),
        "status": str(receipt.get("status") or ""),
        "decision": str(receipt.get("decision") or ""),
        "public_ws_attempts": list(receipt.get("public_ws_attempts") or []),
        "sequence": dict(receipt.get("sequence") or {}),
        "controlled_recovery": dict(
            receipt.get("controlled_recovery") or {}
        ),
        "server_clock": dict(receipt.get("server_clock") or {}),
        "readiness": dict(receipt.get("readiness") or {}),
        "safety": dict(receipt.get("safety") or {}),
        "blockers": list(receipt.get("blockers") or []),
    }


def _quality_l2_attestation_verified(inputs: ValidatedInputs) -> bool:
    receipt = dict(inputs.real_l2_receipt or {})
    sequence = dict(receipt.get("sequence") or {})
    recovery = dict(receipt.get("controlled_recovery") or {})
    clock = dict(receipt.get("server_clock") or {})
    return (
        (inputs.real_l2_manifest or {}).get("quality_status")
        == QUALITY_L2_MANIFEST_STATUS
        and receipt.get("status") == "quality_checked"
        and sequence.get("real_message_count", 0) > 0
        and sequence.get("two_sided") is True
        and sequence.get("sequence_continuity_verified") is True
        and sequence.get("validation_status") == "pass"
        and recovery.get("executed") is True
        and recovery.get("verified") is True
        and recovery.get("unrecovered_gap_count") == 0
        and clock.get("offset_verified") is True
        and float(clock.get("abs_offset_max_ms") or float("inf"))
        <= float(clock.get("max_allowed_abs_offset_ms") or 0.0)
    )


def _ordinary_required_blockers(
    inputs: ValidatedInputs,
) -> tuple[str, ...]:
    if _quality_l2_attestation_verified(inputs):
        return QUALITY_L2_REQUIRED_BLOCKERS
    return tuple(
        _ordered_superset(REQUIRED_BLOCKERS, REAL_L2_ATTESTATION_BLOCKERS)
    )


def _normalize_current_l2_blockers(
    inputs: ValidatedInputs,
    blockers: Sequence[str],
) -> list[str]:
    if not _quality_l2_attestation_verified(inputs):
        return [str(item) for item in blockers]
    return [
        str(item)
        for item in blockers
        if str(item) not in QUALITY_L2_RESOLVED_BLOCKERS
    ]


def _stage_explicit_legacy_inputs(
    *,
    session: BTCRuntimeArtifactWriteSession,
    stage_root: Path,
    inputs: ValidatedInputs,
    expected_head: str,
) -> tuple[Path, Path, Path, tuple[Path, Path, Path]]:
    bundle_dir = _stage_selected_bundle(
        session=session, stage_root=stage_root, inputs=inputs
    )
    bundle_root = bundle_dir.parent.parent
    config = (
        "selected_provider: okx\n"
        "providers:\n"
        "  okx:\n"
        "    enabled: true\n"
        f"    root: \"{bundle_root.as_posix()}\"\n"
        f"    selected_bundle_id: \"{bundle_dir.name}\"\n"
    ).encode("utf-8")
    config_path = session.write_bytes_atomic(
        stage_root / "inputs/provider.yaml", config
    )
    placeholder = _required_blocker_envelope(
        schema_version="btc_next_stage_staged_legacy_input_v1",
        source_head=expected_head,
        code_commit=expected_head,
        aggregation_batch_id="staged-input",
        generated_at_utc=datetime.now(timezone.utc),
        status="complete_blocked",
        decision="blocked_fail_closed_no_paper_no_live",
        input_hashes=inputs.raw_hashes,
        safety=SAFETY,
        blockers=_ordinary_required_blockers(inputs),
        ordinary_required_blockers=_ordinary_required_blockers(inputs),
    )
    placeholder_path = session.write_json_atomic(
        stage_root / "inputs/blocked_source.json", placeholder
    )
    observations: list[Path] = []
    for name in ("long_short.csv", "attack.csv", "high_yield.csv"):
        observations.append(
            session.write_bytes_atomic(
                stage_root / "inputs" / name, b"\n"
            )
        )
    return (
        bundle_dir,
        config_path,
        placeholder_path,
        (observations[0], observations[1], observations[2]),
    )


def _stage_selected_bundle(
    *,
    session: BTCRuntimeArtifactWriteSession,
    stage_root: Path,
    inputs: ValidatedInputs,
) -> Path:
    files = [
        dict(row)
        for row in inputs.manifest.get("files", [])
        if isinstance(row, Mapping)
    ]
    bundle_manifest = next(
        (
            str(row["path"])
            for row in files
            if str(row.get("path") or "").endswith(
                "/btc_perpetual_bundle_manifest.json"
            )
        ),
        "",
    )
    if not bundle_manifest:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_selected_bundle_manifest_missing"
        )
    source_prefix = Path(bundle_manifest).parent
    bundle_id = source_prefix.name
    target = session.resolve(
        stage_root / "inputs/bundle_root/bundles" / bundle_id
    )
    target.mkdir(parents=True, exist_ok=False)
    copied = 0
    for row in files:
        relative = Path(str(row.get("path") or ""))
        try:
            within_bundle = relative.relative_to(source_prefix)
        except ValueError:
            continue
        source = inputs.data_root / relative
        if not source.is_file():
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_manifest_file_missing"
            )
        destination = target / within_bundle
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if _sha256_file(destination) != str(row.get("sha256") or ""):
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_staged_bundle_hash_mismatch"
            )
        copied += 1
    if copied == 0:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_selected_bundle_empty"
        )
    return target


def _build_strategy_and_runtime(
    *,
    repo_root: Path,
    stage_physical: Path,
    config_path: Path,
    placeholder_path: Path,
    observation_paths: tuple[Path, Path, Path],
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
) -> LegacyOutputs:
    paper_dir = stage_physical / "legacy/paper_runtime"
    paper_report = build_btc_perpetual_paper_runtime_replay_report(
        repo_root=repo_root,
        output_dir=paper_dir,
        config_path=config_path,
        long_short_observations_path=observation_paths[0],
        attack_observations_path=observation_paths[1],
        high_yield_observations_path=observation_paths[2],
        cost_model_report_path=placeholder_path,
        perpetual_evidence_report_path=placeholder_path,
        generated_at_utc=generated_at_utc,
        aggregation_batch_id=run_id,
    )
    _validate_legacy_head(paper_report, expected_head)
    paper_report_path = (
        paper_dir / "btc_perpetual_paper_runtime_replay_report.json"
    )
    reconciliation_path = (
        paper_dir
        / "btc_perpetual_paper_runtime_replay_oms_session_reconciliation_report.json"
    )
    strategy_dir = stage_physical / "legacy/strategy"
    strategy_report = build_btc_strategy_promotion_readiness_review(
        output_dir=strategy_dir,
        generated_at_utc=generated_at_utc,
        aggregation_batch_id=run_id,
        bar_replay_report_path=placeholder_path,
        leakage_audit_report_path=placeholder_path,
        long_short_observer_report_path=placeholder_path,
        attack_observer_report_path=placeholder_path,
        high_yield_followup_report_path=placeholder_path,
        observe_only_health_report_path=placeholder_path,
        perp_execution_evidence_report_path=placeholder_path,
        paper_runtime_replay_report_path=paper_report_path,
        exchange_runtime_gap_report_path=placeholder_path,
        gate_dashboard_report_path=placeholder_path,
        canonical_backtest_manifest_path=placeholder_path,
    )
    _validate_legacy_head(strategy_report, expected_head)
    return LegacyOutputs(
        paper_report=paper_report,
        paper_report_path=paper_report_path,
        reconciliation_path=reconciliation_path,
        strategy_report=strategy_report,
        strategy_report_path=(
            strategy_dir / "btc_strategy_promotion_readiness_report.json"
        ),
    )


def _layer_receipt(
    *,
    inputs: ValidatedInputs,
    layer: str,
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
    logical_path: Path,
    legacy_payload: Mapping[str, Any],
    legacy_path: Path,
    extra_blockers: Sequence[str],
    input_hashes: Mapping[str, str],
) -> dict[str, Any]:
    blockers = _ordered_superset(
        _ordinary_required_blockers(inputs),
        _normalize_current_l2_blockers(
            inputs,
            [
                *extra_blockers,
                *[
                    str(item)
                    for item in legacy_payload.get("blockers", [])
                ],
            ],
        ),
    )
    receipt = {
        "schema_version": LAYER_RECEIPT_SCHEMA_VERSION,
        "layer": layer,
        "source_head": expected_head,
        "code_commit": expected_head,
        "legacy_code_commit": str(legacy_payload.get("code_commit") or ""),
        "aggregation_batch_id": run_id,
        "generated_at_utc": generated_at_utc.astimezone(
            timezone.utc
        ).isoformat(),
        "status": "complete_blocked",
        "decision": "blocked_fail_closed_no_paper_no_live",
        "readiness_class": "quality_checked",
        "logical_path": logical_path.as_posix(),
        "file_sha256": _sha256_file(legacy_path),
        "input_hashes": dict(input_hashes),
        "blockers": blockers,
        "safety": dict(SAFETY),
    }
    _apply_required_blocker_preservation(
        receipt,
        ordinary_required_blockers=_ordinary_required_blockers(inputs),
    )
    return receipt


def _domain_source_map(
    *,
    repo_root: Path,
    inputs: ValidatedInputs,
    receipts: Mapping[str, Mapping[str, Any]],
    staged: Mapping[str, Path],
    expected_head: str,
    generated_at_utc: datetime,
) -> dict[str, dict[str, Any]]:
    generated = generated_at_utc.astimezone(timezone.utc).isoformat()

    def receipt_row(layer: str) -> dict[str, Any]:
        receipt = receipts[layer]
        return {
            "path": LATEST_PATHS[layer].as_posix(),
            "status": receipt["status"],
            "decision": receipt["decision"],
            "readiness_class": "quality_checked",
            "sha256": _sha256_file(staged[layer]),
            "source_head": expected_head,
            "generated_at_utc": generated,
            "freshness": "current",
            "blockers": list(receipt["blockers"]),
            "summary": {},
        }

    manifest_blockers = _ordered_superset(
        _ordinary_required_blockers(inputs),
        _normalize_current_l2_blockers(
            inputs,
            [str(item) for item in inputs.manifest.get("blockers", [])],
        ),
    )
    pending_hash = stable_payload_hash(
        {
            "source_head": expected_head,
            "run_id": str(receipts["strategy"]["aggregation_batch_id"]),
            "status": "pending_next_stage_gate",
        }
    )
    return {
        "data": {
            "path": inputs.manifest_path.relative_to(repo_root).as_posix(),
            "status": "complete_blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "readiness_class": "quality_checked",
            "sha256": str(inputs.raw_hashes["data_manifest"]),
            "source_head": expected_head,
            "generated_at_utc": generated,
            "freshness": "current",
            "blockers": manifest_blockers,
            "summary": {},
        },
        "strategy": receipt_row("strategy"),
        "risk": {
            **receipt_row("strategy"),
            "path": LATEST_PATHS["strategy"].as_posix(),
            "blockers": _ordered_superset(
                _ordinary_required_blockers(inputs),
                ["pending_next_stage_gate"],
            ),
        },
        "oms": receipt_row("oms"),
        "ledger": receipt_row("ledger"),
        "replay": receipt_row("replay"),
        "gate": {
            "path": LATEST_PATHS["gate"].as_posix(),
            "status": "complete_blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "readiness_class": "quality_checked",
            "sha256": pending_hash,
            "source_head": expected_head,
            "generated_at_utc": generated,
            "freshness": "current",
            "blockers": _ordered_superset(
                _ordinary_required_blockers(inputs),
                ["pending_next_stage_gate"],
            ),
            "summary": {},
        },
    }


def _build_engineering_evidence(
    *,
    repo_root: Path,
    inputs: ValidatedInputs,
    receipts: Mapping[str, Mapping[str, Any]],
    staged: Mapping[str, Path],
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    source_evidence = {
        layer: {
            "path": LATEST_PATHS[layer].as_posix(),
            "sha256": _sha256_file(staged[layer]),
            "source_head": expected_head,
            "status": receipts[layer]["status"],
            "blockers": receipts[layer]["blockers"],
        }
        for layer in ("strategy", "oms", "ledger", "replay")
    }
    data_handoff = {
        **dict(inputs.data_handoff),
        "handoff_event_sha256": inputs.raw_hashes[
            "data_integrated_handoff"
        ],
        "readiness_class": "quality_checked",
        "data_producer_commit": str(
            inputs.manifest.get("producer_commit") or ""
        ),
    }
    manifest_sha = str(inputs.manifest.get("aggregate_sha256") or "")
    dependency_receipt = public_websocket_dependency_receipt()
    dependency = resolve_selected_public_ws_dependency(
        selected_bundle_sha256=manifest_sha,
        package_receipts=[
            {
                **dependency_receipt,
                "selected_bundle_sha256": manifest_sha,
                "package_name": str(
                    dependency_receipt.get("distribution_name") or ""
                ),
            }
        ],
    )
    if dependency.get("valid") is True:
        data_handoff["blockers"] = [
            str(item)
            for item in data_handoff.get("blockers", [])
            if str(item) != "btc_okx_websocket_client_dependency_missing"
        ]
    data_handoff["blockers"] = _normalize_current_l2_blockers(
        inputs,
        [str(item) for item in data_handoff.get("blockers", [])],
    )
    builder_chain = _declared_builder_chain(
        repo_root=repo_root,
        staged=staged,
        expected_head=expected_head,
    )
    quality_l2_verified = _quality_l2_attestation_verified(inputs)
    real_l2_manifest = dict(inputs.real_l2_manifest or {})
    real_l2_receipt = dict(inputs.real_l2_receipt or {})
    real_l2_sequence = dict(real_l2_receipt.get("sequence") or {})
    engineering = build_btc_next_stage_engineering_evidence(
        current_head=expected_head,
        generated_at_utc=generated_at_utc,
        source_evidence=source_evidence,
        public_market_handoff=data_handoff,
        public_ws_dependency=dependency,
        l2_evidence={
            "consumer_source_head": expected_head,
            "producer_commit": str(
                (
                    real_l2_manifest
                    if quality_l2_verified
                    else inputs.manifest
                ).get("producer_commit")
                or ""
            ),
            "sha256": str(
                (
                    real_l2_manifest
                    if quality_l2_verified
                    else inputs.manifest
                ).get("aggregate_sha256")
                or manifest_sha
            ),
            "sequence_contiguous": bool(
                quality_l2_verified
                and real_l2_sequence.get(
                    "sequence_continuity_verified"
                )
                is True
            ),
            "two_sided": bool(
                quality_l2_verified
                and real_l2_sequence.get("two_sided") is True
            ),
        },
        builder_chain=[
            {
                "name": row["name"],
                "source_head": row["source_head"],
                "sha256": row["output_sha256"],
                "immutable_output": row["immutable_output"],
            }
            for row in builder_chain
        ],
    )
    engineering["aggregation_batch_id"] = run_id
    engineering["generated_at_utc"] = generated_at_utc.astimezone(
        timezone.utc
    ).isoformat()
    engineering["status"] = "complete_blocked"
    engineering["decision"] = "blocked_fail_closed_no_paper_no_live"
    engineering["safety"] = dict(SAFETY)
    engineering["builder_chain"] = builder_chain
    engineering["builder_chain_phase"] = "declared_before_promotion_gate"
    engineering["builder_chain_declaration_sha256"] = stable_payload_hash(
        _builder_chain_declaration(builder_chain)
    )
    engineering["real_l2_attestation"] = _real_l2_attestation_summary(inputs)
    engineering["blockers"] = _ordered_superset(
        _ordinary_required_blockers(inputs),
        _normalize_current_l2_blockers(
            inputs,
            [str(item) for item in engineering.get("blockers", [])],
        ),
    )
    return engineering


def _declared_builder_chain(
    *,
    repo_root: Path,
    staged: Mapping[str, Path],
    expected_head: str,
) -> list[dict[str, Any]]:
    orchestrator_path = SOURCE_PATHS[0]
    rows = [
        {
            "name": "domain_read_model",
            "builder_symbol": "build_btc_domain_read_model",
            "builder_code_path": (
                "quant_crypto/application/btc_domain_read_model.py"
            ),
            "target_path": LATEST_PATHS["domain"].as_posix(),
            "target_status": "built_staged",
            "output_sha256": _sha256_file(staged["domain"]),
            "output_hash_verified": True,
            "immutable_output": True,
        },
        {
            "name": "promotion_evidence",
            "builder_symbol": "_promotion_evidence",
            "builder_code_path": orchestrator_path,
            "target_path": LATEST_PATHS["promotion"].as_posix(),
            "target_status": "declared_not_built",
            "output_sha256": "",
            "output_hash_verified": False,
            "immutable_output": False,
        },
        {
            "name": "gate_decision",
            "builder_symbol": "_gate_decision",
            "builder_code_path": orchestrator_path,
            "target_path": LATEST_PATHS["gate"].as_posix(),
            "target_status": "declared_not_built",
            "output_sha256": "",
            "output_hash_verified": False,
            "immutable_output": False,
        },
    ]
    for row in rows:
        row["source_head"] = expected_head
        row["builder_code_sha256"] = _git_blob_sha256(
            repo_root,
            expected_head,
            str(row["builder_code_path"]),
        )
    return rows


def _builder_chain_declaration(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            key: row[key]
            for key in (
                "name",
                "builder_symbol",
                "builder_code_path",
                "builder_code_sha256",
                "source_head",
                "target_path",
            )
        }
        for row in rows
    ]


def _finalize_engineering_builder_chain(
    *,
    engineering: dict[str, Any],
    staged: Mapping[str, Path],
) -> None:
    pre_gate_sha256 = _sha256_file(staged["engineering"])
    finalized: list[dict[str, Any]] = []
    for raw in engineering.get("builder_chain", []):
        row = dict(raw)
        artifact_id = {
            "domain_read_model": "domain",
            "promotion_evidence": "promotion",
            "gate_decision": "gate",
        }.get(str(row.get("name") or ""))
        if artifact_id is None or artifact_id not in staged:
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_builder_chain_target_missing"
            )
        row.update(
            {
                "target_status": "built_staged",
                "output_sha256": _sha256_file(staged[artifact_id]),
                "output_hash_verified": True,
                "immutable_output": True,
            }
        )
        finalized.append(row)
    engineering["builder_chain"] = finalized
    engineering["builder_chain_phase"] = "finalized_after_gate"
    engineering["pre_gate_engineering_evidence_sha256"] = pre_gate_sha256
    engineering.pop("artifact_hash", None)
    engineering["artifact_hash"] = stable_payload_hash(engineering)


def _promotion_evidence(
    *,
    inputs: ValidatedInputs,
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
    strategy_report: Mapping[str, Any],
    strategy_report_path: Path,
    engineering_path: Path,
) -> dict[str, Any]:
    payload = _required_blocker_envelope(
        schema_version=PROMOTION_EVIDENCE_SCHEMA_VERSION,
        source_head=expected_head,
        code_commit=expected_head,
        aggregation_batch_id=run_id,
        generated_at_utc=generated_at_utc,
        status="complete_blocked",
        decision="blocked_fail_closed_no_paper_no_live",
        input_hashes={
            "strategy_promotion_review": _sha256_file(
                strategy_report_path
            ),
            "engineering_evidence": _sha256_file(engineering_path),
        },
        safety=SAFETY,
        blockers=_ordered_superset(
            _ordinary_required_blockers(inputs),
            _normalize_current_l2_blockers(
                inputs,
                [
                    str(item)
                    for item in strategy_report.get("blockers", [])
                ],
            ),
        ),
        ordinary_required_blockers=_ordinary_required_blockers(inputs),
    )
    payload.update(
        {
            "readiness_class": "quality_checked",
            "legacy_code_commit": str(
                strategy_report.get("code_commit") or ""
            ),
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
        }
    )
    return payload


def _gate_decision(
    *,
    inputs: ValidatedInputs,
    repo_root: Path,
    stage_physical: Path,
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
    legacy: LegacyOutputs,
    placeholder_path: Path,
    promotion_path: Path,
) -> dict[str, Any]:
    source_paths = {
        source_id: placeholder_path
        for source_id in PROMOTION_SOURCE_PATHS
    }
    source_paths.update(
        {
            "strategy_readiness": legacy.strategy_report_path,
            "paper_runtime_replay": legacy.paper_report_path,
            "paper_runtime_reconciliation": legacy.reconciliation_path,
        }
    )
    gate_dir = stage_physical / "legacy/promotion_gate"
    legacy_gate = build_btc_promotion_gate_control(
        repo_root=repo_root,
        output_dir=gate_dir,
        source_paths=source_paths,
        generated_at_utc=generated_at_utc,
        aggregation_batch_id=run_id,
    )
    _validate_legacy_head(legacy_gate, expected_head)
    legacy_gate_path = gate_dir / "btc_promotion_gate_control_report.json"
    frozen_prereg, frozen_prereg_blob_sha256 = (
        load_frozen_active_criteria_prereg(
            repo_root,
            current_head=expected_head,
        )
    )
    legacy_evaluation = evaluate_current_head_gate_evidence(
        current_head=expected_head,
        generated_at_utc=generated_at_utc,
        pointer_validation={
            "status": "missing",
            "validation_errors": ["blank_external_root_no_prior_pointer"],
        },
        evidence={
            "l2_batch": {},
            "fill_mapping": {},
            "nonflat": {},
            "observation_window": {},
            "manual_approval": {},
        },
        frozen_preregistration=frozen_prereg,
        frozen_prereg_blob_sha256=frozen_prereg_blob_sha256,
    )
    payload = _required_blocker_envelope(
        schema_version=PROMOTION_GATE_SCHEMA_VERSION,
        source_head=expected_head,
        code_commit=expected_head,
        aggregation_batch_id=run_id,
        generated_at_utc=generated_at_utc,
        status="complete_blocked",
        decision="blocked_fail_closed_no_paper_no_live",
        input_hashes={
            "promotion_evidence": _sha256_file(promotion_path),
            "legacy_promotion_gate": _sha256_file(legacy_gate_path),
            "legacy_7_check": stable_payload_hash(legacy_evaluation),
        },
        safety=SAFETY,
        blockers=_ordered_superset(
            _ordinary_required_blockers(inputs),
            _normalize_current_l2_blockers(
                inputs,
                [
                    *[
                        str(item)
                        for item in legacy_gate.get("blockers", [])
                    ],
                    *[
                        str(item)
                        for item in legacy_evaluation.get("blockers", [])
                    ],
                ],
            ),
        ),
        ordinary_required_blockers=_ordinary_required_blockers(inputs),
    )
    payload.update(
        {
            "readiness_class": "quality_checked",
            "authoritative_gate": True,
            "legacy_code_commit": str(
                legacy_gate.get("code_commit") or ""
            ),
            "legacy_7_check": {
                "authoritative": False,
                "check_count": len(legacy_evaluation.get("checks", {})),
                "evaluation": legacy_evaluation,
            },
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
        }
    )
    return payload


def _orchestrator_report(
    *,
    expected_head: str,
    run_id: str,
    generated_at_utc: datetime,
    inputs: ValidatedInputs,
    start_state: GateBuildState,
    end_state: GateBuildState,
    staged: Mapping[str, Path],
) -> dict[str, Any]:
    payload = _required_blocker_envelope(
        schema_version=SCHEMA_VERSION,
        source_head=expected_head,
        code_commit=expected_head,
        aggregation_batch_id=run_id,
        generated_at_utc=generated_at_utc,
        status="complete_blocked",
        decision="blocked_fail_closed_no_paper_no_live",
        input_hashes={
            **inputs.raw_hashes,
            **{
                f"{artifact_id}_staged": _sha256_file(path)
                for artifact_id, path in staged.items()
            },
        },
        safety=SAFETY,
        blockers=_ordinary_required_blockers(inputs),
        ordinary_required_blockers=_ordinary_required_blockers(inputs),
    )
    payload.update(
        {
            "readiness_class": "quality_checked",
            "step_order": list(STEP_ORDER),
            "build_state_start": start_state.as_dict(),
            "build_state_end": end_state.as_dict(),
            "outputs": {
                key: path.as_posix() for key, path in LATEST_PATHS.items()
            },
            "snapshot": {
                "runs_root": DEFAULT_RUNS_ROOT.as_posix(),
                "manifest_path": (
                    DEFAULT_RUNS_ROOT / run_id / "manifest.json"
                ).as_posix(),
                "pointer_path": DEFAULT_POINTER_PATH.as_posix(),
                "pointer_contains_blockers": False,
            },
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
            "real_l2_attestation": _real_l2_attestation_summary(inputs),
            "domain_repository_filename_mismatch_regression": {
                "preserved": True,
                "adapter_modified": False,
                "normalized_receipt_source_map_used": True,
                "followup_ticket_required": True,
            },
        }
    )
    return payload


def _required_blocker_envelope(
    *,
    schema_version: str,
    source_head: str,
    code_commit: str,
    aggregation_batch_id: str,
    generated_at_utc: datetime,
    status: str,
    decision: str,
    input_hashes: Mapping[str, str],
    safety: Mapping[str, bool],
    blockers: Sequence[str],
    ordinary_required_blockers: Sequence[str] | None = None,
    metadata_required_blockers: Sequence[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": schema_version,
        "source_head": source_head,
        "code_commit": code_commit,
        "aggregation_batch_id": aggregation_batch_id,
        "generated_at_utc": generated_at_utc.astimezone(
            timezone.utc
        ).isoformat(),
        "status": status,
        "decision": decision,
        "input_hashes": dict(input_hashes),
        "blockers": list(blockers),
        "safety": dict(safety),
    }
    _apply_required_blocker_preservation(
        payload,
        ordinary_required_blockers=ordinary_required_blockers,
        metadata_required_blockers=metadata_required_blockers,
    )
    return payload


def _apply_required_blocker_preservation(
    payload: dict[str, Any],
    *,
    require_in_ordinary_blockers: bool = True,
    ordinary_required_blockers: Sequence[str] | None = None,
    metadata_required_blockers: Sequence[str] | None = None,
) -> None:
    if require_in_ordinary_blockers:
        required_for_ordinary = (
            tuple(ordinary_required_blockers)
            if ordinary_required_blockers is not None
            else tuple(
                _ordered_superset(
                    REQUIRED_BLOCKERS, REAL_L2_ATTESTATION_BLOCKERS
                )
            )
        )
        blockers = _ordered_superset(
            [str(item) for item in payload.get("blockers", [])],
            required_for_ordinary,
        )
        payload["blockers"] = blockers
        missing = [
            item for item in required_for_ordinary if item not in blockers
        ]
    else:
        missing = []
    ordinary_tuple = tuple(ordinary_required_blockers or ())
    if metadata_required_blockers is not None:
        metadata_required = tuple(metadata_required_blockers)
    elif ordinary_tuple == QUALITY_L2_REQUIRED_BLOCKERS:
        metadata_required = QUALITY_L2_REQUIRED_BLOCKERS
    else:
        metadata_required = REQUIRED_BLOCKERS
    payload["required_blockers"] = list(metadata_required)
    payload["required_blocker_count"] = len(metadata_required)
    payload["required_blockers_sha256"] = stable_payload_hash(
        list(metadata_required)
    )
    payload["required_blockers_missing"] = missing
    payload["required_blockers_preserved"] = not missing


def _preservation_valid(payload: Mapping[str, Any]) -> bool:
    required = tuple(payload.get("required_blockers") or [])
    return (
        required in (REQUIRED_BLOCKERS, QUALITY_L2_REQUIRED_BLOCKERS)
        and payload.get("required_blocker_count") == len(required)
        and payload.get("required_blockers_sha256")
        == stable_payload_hash(list(required))
        and payload.get("required_blockers_missing") == []
        and payload.get("required_blockers_preserved") is True
    )


def _assert_all_safety_false(payloads: Mapping[str, Mapping[str, Any]]) -> None:
    violations: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                nested_path = f"{path}.{key}" if path else str(key)
                if key in SENSITIVE_TRUE_KEYS and nested is not False:
                    violations.append(nested_path)
                visit(nested, nested_path)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, f"{path}[{index}]")

    visit(payloads, "")
    if violations:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_safety_flag_not_false:"
            + violations[0]
        )
    for payload_id, payload in payloads.items():
        if payload.get("safety") != SAFETY:
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_safety_contract_incomplete:"
                + payload_id
            )
        if not _preservation_valid(payload):
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_required_blocker_preservation_failed:"
                + payload_id
            )


def _assert_legacy_builder_api() -> None:
    required = {
        build_btc_perpetual_paper_runtime_replay_report: {
            "repo_root",
            "output_dir",
            "config_path",
            "long_short_observations_path",
            "attack_observations_path",
            "high_yield_observations_path",
            "cost_model_report_path",
            "perpetual_evidence_report_path",
        },
        build_btc_strategy_promotion_readiness_review: {
            "output_dir",
            "paper_runtime_replay_report_path",
            "gate_dashboard_report_path",
        },
        build_btc_promotion_gate_control: {
            "repo_root",
            "output_dir",
            "source_paths",
        },
    }
    for builder, fields in required.items():
        available = set(inspect.signature(builder).parameters)
        missing = sorted(fields - available)
        if missing:
            raise BTCNextStageOrchestratorError(
                "btc_next_stage_orchestrator_legacy_builder_api_gap:"
                + builder.__name__
                + ":"
                + ",".join(missing)
            )


def _validate_legacy_head(
    payload: Mapping[str, Any], expected_head: str
) -> None:
    legacy = str(payload.get("code_commit") or "")
    if len(legacy) < 7 or not expected_head.startswith(legacy):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_legacy_code_commit_mismatch"
        )


def _validate_schema(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.validate(dict(payload), schema)
    except (
        OSError,
        json.JSONDecodeError,
        jsonschema.ValidationError,
        jsonschema.SchemaError,
    ) as exc:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_schema_validation_failed"
        ) from exc


def _write_staged_json(
    session: BTCRuntimeArtifactWriteSession,
    logical_path: Path,
    payload: Mapping[str, Any],
) -> Path:
    return session.write_json_atomic(logical_path, payload)


def _complete_step(
    completed: list[str],
    step: str,
    failure_injector: FailureInjector | None,
) -> None:
    expected = STEP_ORDER[len(completed)]
    if step != expected:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_step_order_violation"
        )
    completed.append(step)
    if failure_injector is not None:
        failure_injector(step)


def _load_repo_json(
    repo_root: Path, raw_path: Path, *, required_prefix: str
) -> tuple[Path, dict[str, Any], bytes]:
    path = raw_path if raw_path.is_absolute() else repo_root / raw_path
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_input_path_escape"
        ) from exc
    if not relative.startswith(required_prefix):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_input_path_forbidden"
        )
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_input_json_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_input_json_not_object"
        )
    return resolved, payload, raw


def _input_relative_paths(
    repo_root: Path, inputs: ValidatedInputs
) -> tuple[str, ...]:
    paths = [
        inputs.manifest_path,
        inputs.data_handoff_path,
        inputs.engineering_handoff_path,
    ]
    if inputs.real_l2_manifest_path is not None:
        paths.append(inputs.real_l2_manifest_path)
    return tuple(
        path.relative_to(repo_root).as_posix()
        for path in paths
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_legacy_output_invalid"
        ) from exc
    if not isinstance(value, dict):
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_legacy_output_not_object"
        )
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _ordered_superset(
    required: Sequence[str], additional: Sequence[str]
) -> list[str]:
    return list(
        dict.fromkeys(
            [str(item) for item in required]
            + [str(item) for item in additional if str(item)]
        )
    )


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_git_command_failed"
        ) from exc


def _git_blob_sha256(
    repo_root: Path,
    commit: str,
    repo_relative_path: str,
) -> str:
    try:
        payload = subprocess.run(
            ["git", "show", f"{commit}:{repo_relative_path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BTCNextStageOrchestratorError(
            "btc_next_stage_orchestrator_builder_code_identity_unavailable"
        ) from exc
    return hashlib.sha256(payload).hexdigest()


def _git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{40}", ancestor):
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _safe_error_code(exc: Exception) -> str:
    text = str(exc).strip()
    if isinstance(exc, BTCNextStageOrchestratorError):
        return text
    if isinstance(
        exc,
        (BTCRuntimeArtifactStoreError, BTCRuntimeArtifactBootstrapError),
    ):
        return text.split(":", 1)[0]
    name = exc.__class__.__name__
    return f"btc_next_stage_orchestrator_failed_closed:{name}"


__all__ = [
    "BTCNextStageOrchestratorError",
    "LATEST_PATHS",
    "REQUIRED_BLOCKERS",
    "REQUIRED_BLOCKERS_SHA256",
    "SAFETY",
    "SCHEMA_VERSION",
    "STEP_ORDER",
    "ValidatedInputs",
    "run_btc_next_stage_current_head_orchestrator",
]
