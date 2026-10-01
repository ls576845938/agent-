"""Transactional, fail-closed rebuild of US current-HEAD gate artifacts.

The service is deliberately offline.  It serializes the legacy US report
builders behind one writer lock, validates every generated payload, rolls back
all ``latest`` files when a builder fails, and publishes one authoritative
manifest that binds the resulting artifacts to a full Git HEAD.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import jsonschema

from quant_us.application.us_equity_domain_read_model import (
    USDomainReadModelService,
)
from quant_us.live.paper_simulation_evaluation import (
    build_us_equity_paper_simulation_evaluation_report,
)
from quant_us.live.paper_simulation_readiness_report import (
    build_us_equity_paper_simulation_readiness_report,
)
from quant_us.live.paper_simulation_runner import (
    DEFAULT_LEDGER_ROOT,
    run_us_equity_paper_simulation_roll,
)
from quant_us.monitoring.completion_audit import (
    build_us_equity_completion_audit_report,
)
from quant_us.monitoring.completion_dependency import (
    build_us_equity_completion_dependency_report,
)
from quant_us.monitoring.next_action_queue import (
    build_us_equity_next_action_queue_report,
)
from quant_us.monitoring.operator_unblock_packet import (
    build_us_equity_operator_unblock_packet,
)
from quant_us.monitoring.strategy_production_line import (
    build_us_equity_strategy_production_line_report,
)
from quant_us.monitoring.us_equity_domain_read_model_repository import (
    USCommittedEvidenceRepository,
)


SCHEMA_VERSION = "us_equity_current_head_gate_rebuild_v1"
TAXONOMY_SCHEMA_VERSION = "us_equity_current_head_blocker_taxonomy_v1"
DEFAULT_CONFIG = Path(
    "configs/governance/us_v3_current_head_gate_rebuild_v1.json"
)
DEFAULT_RECEIPT = Path(
    "artifacts/us_equity_gate_rebuild/latest/"
    "us_equity_current_head_gate_rebuild.json"
)
DEFAULT_TAXONOMY = Path(
    "artifacts/us_equity_gate_rebuild/latest/"
    "us_equity_current_head_blocker_taxonomy.json"
)
DEFAULT_RUN_ROOT = Path("artifacts/us_equity_gate_rebuild/runs")
DEFAULT_LOCK = Path("artifacts/us_equity_gate_rebuild/.build.lock")

PRIMARY_STEP_ORDER = (
    "completion_dependency",
    "next_action_queue",
    "operator_unblock_packet",
    "completion_audit",
    "production_line",
    "portfolio_promotion",
    "paper_readiness",
    "paper_roll",
    "paper_evaluation",
    "live_readiness",
    "domain_read_model",
)
FINAL_CLOSURE_ORDER = (
    "completion_dependency_final",
    "next_action_queue_final",
    "operator_unblock_packet_final",
    "completion_audit_final",
)

LATEST_PATHS = {
    "completion_dependency": Path(
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_completion_dependency_report.json"
    ),
    "next_action_queue": Path(
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_next_action_queue_report.json"
    ),
    "operator_unblock_packet": Path(
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_operator_unblock_packet.json"
    ),
    "completion_audit": Path(
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_completion_audit_report.json"
    ),
    "production_line": Path(
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_strategy_production_line_report.json"
    ),
    "portfolio_promotion": Path(
        "artifacts/us_equity_portfolio/latest/"
        "portfolio_promotion_evidence_report.json"
    ),
    "paper_readiness": Path(
        "artifacts/us_equity_etf_macro_rotation/latest/"
        "us_equity_paper_simulation_readiness_report.json"
    ),
    "paper_roll": Path(
        "artifacts/us_equity_etf_macro_rotation/latest/"
        "us_equity_paper_simulation_roll_report.json"
    ),
    "paper_evaluation": Path(
        "artifacts/us_equity_etf_macro_rotation/latest/"
        "us_equity_paper_simulation_evaluation_report.json"
    ),
    "live_readiness": Path(
        "artifacts/us_equity_etf_macro_rotation/latest/"
        "us_equity_live_readiness_risk_constitution_report.json"
    ),
    "live_readiness_compat": Path(
        "artifacts/us_equity_etf_macro_rotation/latest/"
        "us_equity_live_readiness_report.json"
    ),
    "domain_read_model": Path(
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_operator_read_model.json"
    ),
}

SCHEMA_PATHS = {
    "completion_dependency": Path(
        "schemas/us_equity_completion_dependency_report.schema.json"
    ),
    "next_action_queue": Path(
        "schemas/us_equity_next_action_queue_report.schema.json"
    ),
    "operator_unblock_packet": Path(
        "schemas/us_equity_operator_unblock_packet.schema.json"
    ),
    "completion_audit": Path(
        "schemas/us_equity_completion_audit_report.schema.json"
    ),
    "production_line": Path(
        "schemas/us_equity_strategy_production_line_report.schema.json"
    ),
    "portfolio_promotion": Path(
        "schemas/us_equity_portfolio_promotion_evidence_report.schema.json"
    ),
    "paper_readiness": Path(
        "schemas/us_equity_paper_simulation_readiness_report.schema.json"
    ),
    "paper_roll": Path(
        "schemas/us_equity_paper_simulation_roll_report.schema.json"
    ),
    "paper_evaluation": Path(
        "schemas/us_equity_paper_simulation_evaluation_report.schema.json"
    ),
    "live_readiness": Path(
        "schemas/us_equity_live_readiness_risk_constitution_report.schema.json"
    ),
    "live_readiness_compat": Path(
        "schemas/us_equity_live_readiness_report.schema.json"
    ),
    "domain_read_model": Path(
        "schemas/us_equity_domain_read_model.schema.json"
    ),
}

PROHIBITED_TRUE_FIELDS = {
    "promotion_allowed",
    "promotion_evidence_ready",
    "paper_allowed",
    "paper_ready",
    "paper_runner_allowed",
    "paper_runner_started",
    "paper_queue_write_allowed",
    "paper_simulation_allowed",
    "live_allowed",
    "live_ready",
    "live_order_allowed",
    "private_endpoint_allowed",
    "private_endpoint_used",
    "order_endpoint_allowed",
    "order_endpoint_used",
    "broker_access_allowed",
    "broker_calls_used",
    "withdraw_allowed",
    "demo_allowed",
    "real_order_allowed",
    "real_order_submitted",
    "network_used",
    "secret_accessed",
}


class USCurrentHeadGateRebuildError(RuntimeError):
    """Raised when the serialized rebuild cannot publish a valid snapshot."""


@dataclass(frozen=True)
class StepContext:
    repo_root: Path
    output_path: Path
    run_root: Path
    generated_at_utc: datetime
    current_head: str
    results: Mapping[str, Mapping[str, Any]]


StepBuilder = Callable[[StepContext], Mapping[str, Any]]


def rebuild_us_equity_current_head_gate(
    *,
    repo_root: Path,
    current_head: str,
    generated_at_utc: datetime | None = None,
    run_id: str | None = None,
    builder_overrides: Mapping[str, StepBuilder] | None = None,
    before_publish: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Rebuild and publish the US gate artifacts under one transaction.

    A valid blocked snapshot is publishable.  An exception, schema error,
    wrong-HEAD payload, unsafe flag, or input-hash validation failure restores
    every pre-existing ``latest`` file.
    """

    root = repo_root.resolve()
    head = _full_head(current_head)
    generated = _as_utc(generated_at_utc or datetime.now(timezone.utc))
    batch_id = run_id or _default_run_id(generated, head)
    _validate_run_id(batch_id)
    run_root = root / DEFAULT_RUN_ROOT / batch_id
    run_root.mkdir(parents=True, exist_ok=True)
    lock_path = root / DEFAULT_LOCK
    overrides = dict(builder_overrides or {})

    managed_paths = [
        *(root / path for path in LATEST_PATHS.values()),
        root / DEFAULT_TAXONOMY,
        root / DEFAULT_RECEIPT,
    ]
    before_images: dict[Path, bytes | None] = {}
    results: dict[str, dict[str, Any]] = {}
    executed_steps: list[str] = []

    with _exclusive_writer_lock(lock_path, batch_id):
        for path in managed_paths:
            before_images[path] = path.read_bytes() if path.exists() else None
        try:
            for step_id in PRIMARY_STEP_ORDER[:4]:
                _execute_step(
                    step_id=step_id,
                    result_key=step_id,
                    root=root,
                    run_root=run_root,
                    generated=generated,
                    head=head,
                    results=results,
                    overrides=overrides,
                )
                executed_steps.append(step_id)

            taxonomy = build_root_blocker_taxonomy(
                source_payloads={
                    key: results[key] for key in PRIMARY_STEP_ORDER[:4]
                },
                source_head=head,
                generated_at_utc=generated,
                output_path=DEFAULT_TAXONOMY,
            )
            _write_json_atomic(root / DEFAULT_TAXONOMY, taxonomy)
            _validate_json_schema(
                payload=taxonomy,
                schema_path=root
                / "schemas/us_equity_current_head_blocker_taxonomy.schema.json",
            )

            for step_id in PRIMARY_STEP_ORDER[4:]:
                _execute_step(
                    step_id=step_id,
                    result_key=step_id,
                    root=root,
                    run_root=run_root,
                    generated=generated,
                    head=head,
                    results=results,
                    overrides=overrides,
                )
                executed_steps.append(step_id)

            # The completion chain consumes downstream reports.  The first pass
            # satisfies the mandated historical order; this serial closure pass
            # prevents the newly rebuilt downstream artifacts from leaving the
            # operator queue stale.
            for final_step in FINAL_CLOSURE_ORDER:
                step_id = final_step.removesuffix("_final")
                _execute_step(
                    step_id=step_id,
                    result_key=final_step,
                    root=root,
                    run_root=run_root,
                    generated=generated,
                    head=head,
                    results=results,
                    overrides=overrides,
                )
                results[step_id] = results[final_step]
                executed_steps.append(final_step)

            output_records = _output_records(
                root=root,
                head=head,
                generated=generated,
                results=results,
            )
            health = {
                key: evaluate_artifact_health(
                    record=value,
                    repo_root=root,
                    current_head=head,
                    now=generated,
                )
                for key, value in output_records.items()
            }
            if not all(row["freshness"] == "current_head" for row in health.values()):
                raise USCurrentHeadGateRebuildError(
                    "us_current_head_gate_output_health_not_current"
                )
            if before_publish is not None:
                before_publish()

            run_manifest = {
                "schema_version": "us_equity_current_head_gate_run_manifest_v1",
                "run_id": batch_id,
                "generated_at_utc": _z(generated),
                "source_head": head,
                "step_order": executed_steps,
                "outputs": output_records,
                "blocker_taxonomy": {
                    "path": DEFAULT_TAXONOMY.as_posix(),
                    "sha256": _sha256(root / DEFAULT_TAXONOMY),
                    "root_blocker_count": taxonomy["root_blocker_count"],
                    "derived_reference_count": taxonomy[
                        "derived_reference_count"
                    ],
                },
                "safety": _safety_flags(),
            }
            manifest_path = run_root / "manifest.json"
            _write_json_atomic(manifest_path, run_manifest)

            root_blockers = [
                str(row["code"]) for row in taxonomy["root_blockers"]
            ]
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "generated_at_utc": _z(generated),
                "source_head": head,
                "run_id": batch_id,
                "status": "complete_blocked"
                if root_blockers
                else "complete",
                "wrapper_status": "success",
                "decision": "blocked_fail_closed_no_paper_no_live"
                if root_blockers
                else "research_evidence_current_manual_gate_still_required",
                "step_order": executed_steps,
                "validation_checks": {
                    "single_writer_lock_held": True,
                    "required_primary_order_preserved": tuple(
                        executed_steps[: len(PRIMARY_STEP_ORDER)]
                    )
                    == PRIMARY_STEP_ORDER,
                    "final_completion_chain_refreshed": tuple(
                        executed_steps[-len(FINAL_CLOSURE_ORDER) :]
                    )
                    == FINAL_CLOSURE_ORDER,
                    "all_output_schemas_valid": True,
                    "all_outputs_current_head": True,
                    "all_output_hashes_verified": True,
                    "all_declared_input_hashes_verified": True,
                    "all_safety_flags_false": True,
                    "paper_ledger_written": False,
                    "network_or_secret_used": False,
                },
                "outputs": output_records,
                "artifact_health": health,
                "blocker_taxonomy": {
                    "path": DEFAULT_TAXONOMY.as_posix(),
                    "sha256": _sha256(root / DEFAULT_TAXONOMY),
                    "root_blockers": taxonomy["root_blockers"],
                    "derived_references": taxonomy["derived_references"],
                    "root_blocker_count": taxonomy["root_blocker_count"],
                    "derived_reference_count": taxonomy[
                        "derived_reference_count"
                    ],
                },
                "blockers": root_blockers,
                "run_manifest": {
                    "path": _repo_path(manifest_path, root),
                    "sha256": _sha256(manifest_path),
                },
                "quality_checked": True,
                "research_ready": False,
                "backtest_ready": False,
                "promotion_evidence_ready": False,
                "safety": _safety_flags(),
            }
            _validate_json_schema(
                payload=receipt,
                schema_path=root
                / "schemas/us_equity_current_head_gate_rebuild.schema.json",
            )
            _write_json_atomic(root / DEFAULT_RECEIPT, receipt)
            return receipt
        except Exception:
            _restore_before_images(before_images)
            raise


def evaluate_artifact_health(
    *,
    record: Mapping[str, Any],
    repo_root: Path,
    current_head: str,
    now: datetime,
    max_age: timedelta = timedelta(days=1),
) -> dict[str, Any]:
    """Evaluate one manifest-bound artifact without trusting wrapper success."""

    blockers: list[str] = []
    path_text = str(record.get("path") or "")
    path = repo_root / path_text
    if record.get("source_head") != current_head:
        blockers.append("artifact_commit_mismatch")
    try:
        generated = datetime.fromisoformat(
            str(record.get("generated_at_utc") or "").replace("Z", "+00:00")
        )
        generated = _as_utc(generated)
    except ValueError:
        blockers.append("artifact_generated_at_invalid")
    else:
        if _as_utc(now) - generated > max_age:
            blockers.append("artifact_expired")
    if not path.is_file():
        blockers.append("artifact_missing")
    elif _sha256(path) != str(record.get("sha256") or ""):
        blockers.append("artifact_hash_mismatch")
    for input_path, expected_hash in _mapping(
        record.get("input_hashes")
    ).items():
        input_file = repo_root / str(input_path)
        actual_hash = (
            _sha256(input_file)
            if input_file.is_file()
            else _missing_hash(str(input_path))
        )
        if actual_hash != expected_hash:
            blockers.append(f"artifact_input_hash_drift:{input_path}")
    return {
        "freshness": "current_head" if not blockers else "stale_blocked",
        "blockers": blockers,
        "decision": "consume_blocked_artifact"
        if not blockers
        else "do_not_consume_stale_artifact",
    }


def build_root_blocker_taxonomy(
    *,
    source_payloads: Mapping[str, Mapping[str, Any]],
    source_head: str,
    generated_at_utc: datetime,
    output_path: Path,
) -> dict[str, Any]:
    """Collapse derived blocker strings into stable root causes."""

    derived: list[dict[str, str]] = []
    for source_step, payload in source_payloads.items():
        for blocker in _extract_blockers(payload):
            root_code = _root_code(blocker)
            derived.append(
                {
                    "root_code": root_code,
                    "source_step": source_step,
                    "blocker": blocker,
                }
            )
    unique_derived = {
        (row["root_code"], row["source_step"], row["blocker"]): row
        for row in derived
    }
    rows = [
        unique_derived[key]
        for key in sorted(unique_derived)
    ]
    root_codes = sorted({row["root_code"] for row in rows})
    root_blockers = []
    remediation_tickets = []
    for code in root_codes:
        spec = ROOT_BLOCKER_SPECS[code]
        count = sum(1 for row in rows if row["root_code"] == code)
        root_blockers.append(
            {
                "code": code,
                "owner": spec["owner"],
                "root_cause": spec["root_cause"],
                "next_action": spec["next_action"],
                "derived_reference_count": count,
            }
        )
        remediation_tickets.append(
            {
                "ticket_id": (
                    "us_equity_remediate_"
                    f"{spec['legacy_category']}"
                ),
                "category": spec["legacy_category"],
                "owner": spec["owner"],
                "dependency_type": spec["dependency_type"],
                "status": spec["status"],
                "blocker_count": count,
                "source_reports": sorted(
                    {
                        row["source_step"]
                        for row in rows
                        if row["root_code"] == code
                    }
                ),
                "next_action": spec["next_action"],
                "acceptance_evidence": [spec["acceptance_evidence"]],
            }
        )
    return {
        "schema_version": TAXONOMY_SCHEMA_VERSION,
        "generated_at_utc": _z(generated_at_utc),
        "source_head": source_head,
        "status": "blocked" if root_blockers else "no_root_blockers",
        "decision": "continue_fail_closed_do_not_unlock_paper_or_live",
        "root_blocker_count": len(root_blockers),
        "derived_reference_count": len(rows),
        "root_blockers": root_blockers,
        "derived_references": rows,
        "remediation_tickets": remediation_tickets,
        "outputs": {"json": output_path.as_posix()},
        "safety": _safety_flags(),
    }


ROOT_BLOCKER_SPECS: dict[str, dict[str, str]] = {
    "production_pit_evidence_unavailable": {
        "owner": "data_steward",
        "legacy_category": "external_data",
        "dependency_type": "external_user_action",
        "status": "blocked_external_data",
        "root_cause": "Immutable production PIT evidence is missing or incomplete.",
        "next_action": "Wait for a validated data_steward production PIT handoff.",
        "acceptance_evidence": "A validated immutable production PIT handoff is current and hash-valid.",
    },
    "forward_observation_incomplete": {
        "owner": "researcher",
        "legacy_category": "natural_time",
        "dependency_type": "natural_time",
        "status": "blocked_natural_time",
        "root_cause": "The required natural-time forward observation is incomplete.",
        "next_action": "Continue observation without changing the frozen candidate.",
        "acceptance_evidence": "The required observation window completes on unchanged parameters.",
    },
    "manual_approval_unavailable": {
        "owner": "quant_architect",
        "legacy_category": "manual_review",
        "dependency_type": "manual_review",
        "status": "blocked_manual_gate",
        "root_cause": "Required manual review or approval is absent.",
        "next_action": "Keep automated gates closed until upstream evidence is ready.",
        "acceptance_evidence": "An explicit architect-approved manual decision is recorded.",
    },
    "paper_runtime_evidence_unavailable": {
        "owner": "paper_operations",
        "legacy_category": "paper_runtime_evidence",
        "dependency_type": "manual_review",
        "status": "blocked_paper_not_started",
        "root_cause": "Real paper runtime and ledger evidence do not exist.",
        "next_action": "Do not start paper without a separately approved ticket.",
        "acceptance_evidence": "Separately authorized paper evidence exists and reconciles.",
    },
    "execution_control_evidence_unavailable": {
        "owner": "execution_engineering",
        "legacy_category": "execution_infra",
        "dependency_type": "engineering",
        "status": "blocked_execution_control",
        "root_cause": "Execution, broker review, or reconciliation evidence is incomplete.",
        "next_action": "Use offline drills only; do not call broker or order endpoints.",
        "acceptance_evidence": "Offline execution controls and reconciliation are current and valid.",
    },
    "promotion_evidence_incomplete": {
        "owner": "super_developer",
        "legacy_category": "research_data_quality",
        "dependency_type": "engineering_after_data",
        "status": "blocked_research_evidence",
        "root_cause": "Backtest, portfolio, cost, or strategy evidence is incomplete.",
        "next_action": "Repair current-HEAD research evidence without retuning the candidate.",
        "acceptance_evidence": "Current-HEAD research evidence is complete without candidate retuning.",
    },
    "current_head_artifact_evidence_unavailable": {
        "owner": "super_developer",
        "legacy_category": "artifact_health",
        "dependency_type": "engineering",
        "status": "blocked_artifact_health",
        "root_cause": "A required artifact is missing, stale, wrong-HEAD, or hash-invalid.",
        "next_action": "Rebuild the owning artifact and validate its current-HEAD hash.",
        "acceptance_evidence": "The owning artifact is current-HEAD and hash-valid.",
    },
    "unclassified_fail_closed_evidence": {
        "owner": "quant_architect",
        "legacy_category": "other",
        "dependency_type": "manual_triage",
        "status": "blocked_manual_triage",
        "root_cause": "A blocker has no stable current taxonomy mapping.",
        "next_action": "Classify the blocker before any gate decision changes.",
        "acceptance_evidence": "The blocker has an approved stable taxonomy mapping.",
    },
}


def _execute_step(
    *,
    step_id: str,
    result_key: str,
    root: Path,
    run_root: Path,
    generated: datetime,
    head: str,
    results: dict[str, dict[str, Any]],
    overrides: Mapping[str, StepBuilder],
) -> None:
    output_path = root / LATEST_PATHS[step_id]
    context = StepContext(
        repo_root=root,
        output_path=output_path,
        run_root=run_root,
        generated_at_utc=generated,
        current_head=head,
        results=results,
    )
    builder = overrides.get(step_id) or DEFAULT_BUILDERS[step_id]
    payload = dict(builder(context))
    if not output_path.is_file():
        _write_json_atomic(output_path, payload)
    saved = _read_json(output_path)
    _validate_json_schema(
        payload=saved,
        schema_path=root / SCHEMA_PATHS[step_id],
    )
    _validate_step_contract(
        step_id=step_id,
        payload=saved,
        current_head=head,
        generated_at_utc=generated,
    )
    if step_id == "live_readiness":
        compat = root / LATEST_PATHS["live_readiness_compat"]
        compat_payload = _read_json(compat)
        _validate_json_schema(
            payload=compat_payload,
            schema_path=root / SCHEMA_PATHS["live_readiness_compat"],
        )
        _validate_step_contract(
            step_id="live_readiness_compat",
            payload=compat_payload,
            current_head=head,
            generated_at_utc=generated,
        )
    results[result_key] = saved


def _completion_dependency_builder(context: StepContext) -> Mapping[str, Any]:
    return build_us_equity_completion_dependency_report(
        repo_root=context.repo_root,
        output=context.output_path,
        markdown_output=_markdown_path(context, "completion_dependency"),
        generated_at=_z(context.generated_at_utc),
    )


def _next_action_queue_builder(context: StepContext) -> Mapping[str, Any]:
    return build_us_equity_next_action_queue_report(
        repo_root=context.repo_root,
        completion_dependency=LATEST_PATHS["completion_dependency"],
        output=context.output_path,
        markdown_output=_markdown_path(context, "next_action_queue"),
        generated_at=_z(context.generated_at_utc),
    )


def _operator_unblock_builder(context: StepContext) -> Mapping[str, Any]:
    return build_us_equity_operator_unblock_packet(
        repo_root=context.repo_root,
        next_action_queue=LATEST_PATHS["next_action_queue"],
        output=context.output_path,
        markdown_output=_markdown_path(context, "operator_unblock_packet"),
        generated_at=_z(context.generated_at_utc),
    )


def _completion_audit_builder(context: StepContext) -> Mapping[str, Any]:
    return build_us_equity_completion_audit_report(
        repo_root=context.repo_root,
        output=context.output_path,
        markdown_output=_markdown_path(context, "completion_audit"),
        report_paths={
            "completion_dependency": LATEST_PATHS["completion_dependency"],
            "operator_unblock": LATEST_PATHS["operator_unblock_packet"],
        },
        generated_at=_z(context.generated_at_utc),
    )


def _production_line_builder(context: StepContext) -> Mapping[str, Any]:
    return build_us_equity_strategy_production_line_report(
        repo_root=context.repo_root,
        output=context.output_path,
        markdown_output=_markdown_path(context, "production_line"),
        generated_at=_z(context.generated_at_utc),
    )


def _portfolio_promotion_builder(context: StepContext) -> Mapping[str, Any]:
    from scripts.build_us_equity_portfolio_promotion_evidence_report import (
        build_us_equity_portfolio_promotion_evidence_report,
        write_us_equity_portfolio_promotion_evidence_report,
    )

    payload = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=context.repo_root,
        generated_at=_z(context.generated_at_utc),
    )
    write_us_equity_portfolio_promotion_evidence_report(
        payload,
        context.output_path,
    )
    return payload


def _paper_readiness_builder(context: StepContext) -> Mapping[str, Any]:
    return build_us_equity_paper_simulation_readiness_report(
        repo_root=context.repo_root,
        output=context.output_path,
        markdown_output=_markdown_path(context, "paper_readiness"),
        blocker_taxonomy=DEFAULT_TAXONOMY,
        generated_at=_z(context.generated_at_utc),
    )


def _paper_roll_builder(context: StepContext) -> Mapping[str, Any]:
    ledger_root = context.repo_root / DEFAULT_LEDGER_ROOT
    if ledger_root.exists():
        raise USCurrentHeadGateRebuildError(
            "us_current_head_gate_paper_ledger_present_out_of_scope"
        )
    payload = run_us_equity_paper_simulation_roll(
        repo_root=context.repo_root,
        readiness_report=LATEST_PATHS["paper_readiness"],
        ledger_root=DEFAULT_LEDGER_ROOT,
        output=context.output_path,
        manual_start_approved=False,
        generated_at=_z(context.generated_at_utc),
    )
    if ledger_root.exists():
        raise USCurrentHeadGateRebuildError(
            "us_current_head_gate_paper_ledger_write_detected"
        )
    return payload


def _paper_evaluation_builder(context: StepContext) -> Mapping[str, Any]:
    return build_us_equity_paper_simulation_evaluation_report(
        repo_root=context.repo_root,
        ledger_root=DEFAULT_LEDGER_ROOT,
        roll_report=LATEST_PATHS["paper_roll"],
        output=context.output_path,
        markdown_output=_markdown_path(context, "paper_evaluation"),
        generated_at=_z(context.generated_at_utc),
    )


def _live_readiness_builder(context: StepContext) -> Mapping[str, Any]:
    from scripts.build_us_equity_live_readiness_risk_constitution import (
        build_us_equity_live_readiness_risk_constitution,
    )

    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=context.repo_root,
        output=context.output_path,
        compat_output=context.repo_root
        / LATEST_PATHS["live_readiness_compat"],
        markdown_output=_markdown_path(context, "live_readiness"),
        paper_simulation_evaluation=LATEST_PATHS["paper_evaluation"],
        production_line=LATEST_PATHS["production_line"],
        blocker_taxonomy=DEFAULT_TAXONOMY,
        max_live_principal_usd=0.0,
        manual_reviewer="",
        generated_at=_z(context.generated_at_utc),
    )
    manual_review = dict(_mapping(payload.get("manual_review")))
    for field in (
        "manual_review_can_unlock_paper_by_itself",
        "manual_review_can_unlock_live_by_itself",
    ):
        if manual_review.get(field) is True:
            raise USCurrentHeadGateRebuildError(
                f"us_current_head_gate_unsafe_flag:live_readiness:{field}"
            )
        manual_review[field] = False
    payload["manual_review"] = manual_review
    for summary_name in ("strategy_validation", "forward_observation"):
        summary = dict(_mapping(payload.get(summary_name)))
        if not str(summary.get("status") or ""):
            summary["status"] = "missing_fail_closed"
        payload[summary_name] = summary
    _write_json_atomic(context.output_path, payload)
    _write_json_atomic(
        context.repo_root / LATEST_PATHS["live_readiness_compat"],
        payload,
    )
    return payload


def _domain_read_model_builder(context: StepContext) -> Mapping[str, Any]:
    report = USDomainReadModelService(
        repository=USCommittedEvidenceRepository(repo_root=context.repo_root),
        head_resolver=lambda: context.current_head,
        clock=lambda: context.generated_at_utc,
    ).read()
    _write_json_atomic(context.output_path, report)
    return report


DEFAULT_BUILDERS: dict[str, StepBuilder] = {
    "completion_dependency": _completion_dependency_builder,
    "next_action_queue": _next_action_queue_builder,
    "operator_unblock_packet": _operator_unblock_builder,
    "completion_audit": _completion_audit_builder,
    "production_line": _production_line_builder,
    "portfolio_promotion": _portfolio_promotion_builder,
    "paper_readiness": _paper_readiness_builder,
    "paper_roll": _paper_roll_builder,
    "paper_evaluation": _paper_evaluation_builder,
    "live_readiness": _live_readiness_builder,
    "domain_read_model": _domain_read_model_builder,
}


OUTPUT_DEPENDENCIES = {
    "completion_dependency": (
        DEFAULT_CONFIG,
        LATEST_PATHS["portfolio_promotion"],
        LATEST_PATHS["paper_readiness"],
        LATEST_PATHS["paper_evaluation"],
        LATEST_PATHS["live_readiness_compat"],
        DEFAULT_TAXONOMY,
    ),
    "next_action_queue": (LATEST_PATHS["completion_dependency"],),
    "operator_unblock_packet": (LATEST_PATHS["next_action_queue"],),
    "completion_audit": (
        LATEST_PATHS["completion_dependency"],
        LATEST_PATHS["operator_unblock_packet"],
    ),
    "production_line": (
        Path("configs/strategies/us_equity_strategy_registry.json"),
        DEFAULT_CONFIG,
    ),
    "portfolio_promotion": (DEFAULT_CONFIG,),
    "paper_readiness": (DEFAULT_TAXONOMY,),
    "paper_roll": (LATEST_PATHS["paper_readiness"],),
    "paper_evaluation": (LATEST_PATHS["paper_roll"],),
    "live_readiness": (
        LATEST_PATHS["production_line"],
        LATEST_PATHS["paper_evaluation"],
        DEFAULT_TAXONOMY,
    ),
    "live_readiness_compat": (
        LATEST_PATHS["production_line"],
        LATEST_PATHS["paper_evaluation"],
        DEFAULT_TAXONOMY,
    ),
    "domain_read_model": (
        Path(
            "configs/governance/"
            "us_equity_domain_read_model_sources_v1.json"
        ),
    ),
}


def _output_records(
    *,
    root: Path,
    head: str,
    generated: datetime,
    results: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for output_id, relative in LATEST_PATHS.items():
        path = root / relative
        if not path.is_file():
            raise USCurrentHeadGateRebuildError(
                f"us_current_head_gate_output_missing:{output_id}"
            )
        payload = _read_json(path)
        dependencies = OUTPUT_DEPENDENCIES[output_id]
        input_hashes = {
            item.as_posix(): (
                _sha256(root / item)
                if (root / item).is_file()
                else _missing_hash(item.as_posix())
            )
            for item in dependencies
        }
        records[output_id] = {
            "path": relative.as_posix(),
            "sha256": _sha256(path),
            "schema_path": SCHEMA_PATHS[output_id].as_posix(),
            "source_head": head,
            "generated_at_utc": _z(generated),
            "decision": str(
                payload.get("decision")
                or payload.get("gate_decision")
                or payload.get("status")
                or "blocked_fail_closed"
            ),
            "blocker_count": len(_extract_blockers(payload)),
            "input_hashes": input_hashes,
        }
    return records


def _validate_step_contract(
    *,
    step_id: str,
    payload: Mapping[str, Any],
    current_head: str,
    generated_at_utc: datetime,
) -> None:
    timestamp = str(
        payload.get("generated_at_utc") or payload.get("generated_at") or ""
    )
    if timestamp != _z(generated_at_utc):
        raise USCurrentHeadGateRebuildError(
            f"us_current_head_gate_generated_at_mismatch:{step_id}"
        )
    commit = str(
        payload.get("source_head")
        or payload.get("code_commit")
        or payload.get("commit")
        or ""
    )
    if commit and not current_head.startswith(commit):
        raise USCurrentHeadGateRebuildError(
            f"us_current_head_gate_commit_mismatch:{step_id}"
        )
    decision = str(
        payload.get("decision")
        or payload.get("gate_decision")
        or payload.get("status")
        or ""
    )
    if not decision:
        raise USCurrentHeadGateRebuildError(
            f"us_current_head_gate_decision_missing:{step_id}"
        )
    unsafe = _unsafe_true_paths(payload)
    if unsafe:
        raise USCurrentHeadGateRebuildError(
            f"us_current_head_gate_unsafe_flag:{step_id}:{unsafe[0]}"
        )


def _extract_blockers(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []

    def collect(value: Any, key: str = "") -> None:
        if key == "blockers" and isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    code = str(item.get("code") or item.get("blocker") or "")
                    if code:
                        blockers.append(code)
                elif isinstance(item, str) and item:
                    blockers.append(item)
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                collect(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(payload)
    return list(dict.fromkeys(blockers))


def _root_code(blocker: str) -> str:
    lowered = blocker.lower()
    if any(
        token in lowered
        for token in (
            "production_pit",
            "pit_bundle",
            "corporate_action",
            "delisted",
            "survivorship",
            "data_lineage",
            "vendor_drop",
        )
    ):
        return "production_pit_evidence_unavailable"
    if any(
        token in lowered
        for token in ("forward_observation", "natural_time", "30_days")
    ):
        return "forward_observation_incomplete"
    if any(
        token in lowered
        for token in ("manual_review", "manual_approval", "manual_reviewer")
    ):
        return "manual_approval_unavailable"
    if any(
        token in lowered
        for token in (
            "paper_simulation",
            "paper_start",
            "paper_runtime",
            "event_ledger",
            "fill",
            "cash_ledger",
            "position_ledger",
        )
    ):
        return "paper_runtime_evidence_unavailable"
    if any(
        token in lowered
        for token in (
            "broker",
            "execution",
            "reconciliation",
            "order_endpoint",
            "private_endpoint",
            "kill_switch",
        )
    ):
        return "execution_control_evidence_unavailable"
    if any(
        token in lowered
        for token in (
            "portfolio",
            "backtest",
            "strategy_validation",
            "walk_forward",
            "cost_stress",
            "exposure",
            "risk",
        )
    ):
        return "promotion_evidence_incomplete"
    if any(
        token in lowered
        for token in (
            "missing",
            "stale",
            "hash",
            "wrong_head",
            "commit",
            "artifact",
            "schema",
            "source_blocked",
        )
    ):
        return "current_head_artifact_evidence_unavailable"
    return "unclassified_fail_closed_evidence"


def _unsafe_true_paths(payload: Mapping[str, Any]) -> list[str]:
    return [
        path
        for path, value in _walk(payload)
        if path.rsplit(".", 1)[-1] in PROHIBITED_TRUE_FIELDS
        and value is True
    ]


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        rows: list[tuple[str, Any]] = []
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_walk(item, path))
        return rows
    if isinstance(value, list):
        rows = []
        for index, item in enumerate(value):
            rows.extend(_walk(item, f"{prefix}.{index}"))
        return rows
    return [(prefix, value)]


def _safety_flags() -> dict[str, bool]:
    return {
        "promotion_allowed": False,
        "paper_allowed": False,
        "paper_runner_allowed": False,
        "paper_runner_started": False,
        "paper_queue_write_allowed": False,
        "live_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "broker_access_allowed": False,
        "broker_calls_used": False,
        "withdraw_allowed": False,
        "demo_allowed": False,
        "real_order_submitted": False,
        "network_used": False,
        "secret_accessed": False,
    }


def _validate_json_schema(*, payload: Any, schema_path: Path) -> None:
    schema = _read_json(schema_path)
    jsonschema.validate(payload, schema)


class _exclusive_writer_lock:
    def __init__(self, path: Path, owner: str) -> None:
        self.path = path
        self.owner = owner
        self.fd: int | None = None

    def __enter__(self) -> "_exclusive_writer_lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise USCurrentHeadGateRebuildError(
                "us_current_head_gate_writer_lock_conflict"
            ) from exc
        os.write(
            self.fd,
            json.dumps({"owner": self.owner}).encode("utf-8"),
        )
        os.fsync(self.fd)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
        self.path.unlink(missing_ok=True)


def _restore_before_images(before_images: Mapping[Path, bytes | None]) -> None:
    for path, raw in before_images.items():
        if raw is None:
            path.unlink(missing_ok=True)
        else:
            _write_bytes_atomic(path, raw)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    raw = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _write_bytes_atomic(path, raw)


def _write_bytes_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise USCurrentHeadGateRebuildError(
            f"us_current_head_gate_json_not_object:{path.as_posix()}"
        )
    return payload


def _markdown_path(context: StepContext, step_id: str) -> Path:
    return context.run_root / "markdown" / f"{step_id}.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _missing_hash(path: str) -> str:
    return hashlib.sha256(f"MISSING:{path}".encode("utf-8")).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _repo_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _full_head(value: str) -> str:
    head = value.lower()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise USCurrentHeadGateRebuildError(
            "us_current_head_gate_invalid_full_head"
        )
    return head


def _validate_run_id(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise USCurrentHeadGateRebuildError(
            "us_current_head_gate_invalid_run_id"
        )


def _default_run_id(generated: datetime, head: str) -> str:
    return (
        f"us-g10-{generated.strftime('%Y%m%dT%H%M%SZ')}-{head[:12]}"
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _z(value: datetime) -> str:
    return _as_utc(value).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


__all__ = [
    "DEFAULT_RECEIPT",
    "DEFAULT_TAXONOMY",
    "FINAL_CLOSURE_ORDER",
    "LATEST_PATHS",
    "PRIMARY_STEP_ORDER",
    "SCHEMA_VERSION",
    "TAXONOMY_SCHEMA_VERSION",
    "StepContext",
    "USCurrentHeadGateRebuildError",
    "build_root_blocker_taxonomy",
    "evaluate_artifact_health",
    "rebuild_us_equity_current_head_gate",
]
