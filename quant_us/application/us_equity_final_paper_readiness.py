"""Fail-closed final paper-readiness review for the US equity candidate.

The service is an offline evidence reader and artifact writer.  It never
starts a paper runner, writes a paper queue, reads credentials, or contacts a
broker.  A successful wrapper may publish a valid blocked packet; readiness is
determined only by the packet decision and its root blockers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema


SCHEMA_VERSION = "us_equity_final_paper_readiness_v1"
LATEST_SCHEMA_VERSION = "us_equity_final_paper_readiness_latest_v1"
MANIFEST_SCHEMA_VERSION = "us_equity_final_paper_readiness_manifest_v1"
DEFAULT_CONFIG = Path(
    "configs/governance/us_v3_final_paper_readiness_v1.json"
)
DEFAULT_SCHEMA = Path("schemas/us_equity_final_paper_readiness.schema.json")
DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_final_paper_readiness")

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PROHIBITED_TRUE_FIELDS = {
    "promotion_allowed",
    "paper_allowed",
    "paper_enabled",
    "paper_runner_allowed",
    "paper_runner_started",
    "paper_queue_write_allowed",
    "live_allowed",
    "live_enabled",
    "live_order_allowed",
    "private_endpoint_allowed",
    "private_endpoint_used",
    "order_endpoint_allowed",
    "order_endpoint_used",
    "broker_access_allowed",
    "broker_calls_used",
    "broker_endpoint_used",
    "withdraw_allowed",
    "demo_allowed",
    "real_order_allowed",
    "real_order_submitted",
    "network_used",
    "secret_accessed",
    "secret_read",
}


class USFinalPaperReadinessError(RuntimeError):
    """Raised when the final review packet cannot be trusted or published."""


def build_us_equity_final_paper_readiness(
    *,
    repo_root: Path,
    current_head: str,
    config_path: Path = DEFAULT_CONFIG,
    schema_path: Path = DEFAULT_SCHEMA,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    generated_at_utc: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Validate current evidence and atomically publish one final review."""

    root = repo_root.resolve()
    head = _full_commit(current_head)
    generated = _as_utc(generated_at_utc or datetime.now(timezone.utc))
    config_abs = _within(root, config_path)
    schema_abs = _within(root, schema_path)
    output_abs = _absolute(output_root, root)
    config = _read_object(config_abs)
    schema = _read_object(schema_abs)
    _validate_config(config)

    evidence, records = _load_evidence(root=root, config=config)
    report = evaluate_us_equity_final_paper_readiness(
        current_head=head,
        generated_at_utc=generated,
        config=config,
        evidence=evidence,
        evidence_records=records,
    )

    batch_id = run_id or (
        f"us-g12-{generated.strftime('%Y%m%dT%H%M%SZ')}-{head[:12]}"
    )
    if not re.fullmatch(r"[A-Za-z0-9._-]+", batch_id):
        raise USFinalPaperReadinessError("final_readiness_run_id_invalid")
    report_path = output_abs / "runs" / batch_id / "report.json"
    manifest_path = output_abs / "runs" / batch_id / "manifest.json"
    report["run_id"] = batch_id
    report["outputs"] = {
        "report": _repo_or_posix(report_path, root),
        "manifest": _repo_or_posix(manifest_path, root),
        "latest_pointer": _repo_or_posix(
            output_abs / "latest" / "latest_pointer.json",
            root,
        ),
    }
    report["artifact_identity_sha256"] = _canonical_hash(report)
    jsonschema.validate(report, schema)

    _publish_run(
        root=root,
        output_root=output_abs,
        report=report,
        report_path=report_path,
        manifest_path=manifest_path,
        config_path=config_abs,
        schema_path=schema_abs,
    )
    return report


def evaluate_us_equity_final_paper_readiness(
    *,
    current_head: str,
    generated_at_utc: datetime,
    config: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
    evidence_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Pure final-review evaluation used by the writer and contract tests."""

    head = _full_commit(current_head)
    generated = _as_utc(generated_at_utc)
    unsafe_paths: list[str] = []
    for evidence_id, payload in evidence.items():
        unsafe_paths.extend(
            f"{evidence_id}.{path}" for path in _unsafe_true_paths(payload)
        )
    if unsafe_paths:
        raise USFinalPaperReadinessError(
            f"unsafe_evidence_flag:{unsafe_paths[0]}"
        )

    handoff_state = _evaluate_handoffs(
        current_head=head,
        payloads=evidence,
        config=config,
    )
    pit_state = _evaluate_production_pit(
        evidence.get("production_pit", {})
    )
    canonical_state = _evaluate_canonical(
        evidence.get("canonical", {})
    )
    observation_state = _evaluate_observation(
        evidence.get("observation", {}),
        current_head=head,
    )
    oms_state = _evaluate_oms(evidence.get("oms", {}))
    broker_state = _evaluate_broker(evidence.get("broker_review", {}))
    manual_state = _evaluate_manual(
        evidence.get("manual_decision", {})
    )
    gate_state = _evaluate_current_head_gate(
        evidence.get("current_head_gate", {}),
        current_head=head,
    )
    engineering_state = _evaluate_engineering_defects(
        root=Path(str(config.get("_repo_root") or ".")),
        config=config,
    )
    handoff_state["evidence_path"] = "configured G01-G11 integrated handoffs"
    pit_state["evidence_path"] = _record_path(
        evidence_records, "production_pit"
    )
    canonical_state["evidence_path"] = _record_path(
        evidence_records, "canonical"
    )
    observation_path = _record_path(evidence_records, "observation")
    observation_state["natural_days"]["evidence_path"] = observation_path
    observation_state["sessions"]["evidence_path"] = observation_path
    oms_state["evidence_path"] = _record_path(evidence_records, "oms")
    broker_state["evidence_path"] = _record_path(
        evidence_records, "broker_review"
    )
    manual_state["evidence_path"] = _record_path(
        evidence_records, "manual_decision"
    )
    gate_state["evidence_path"] = _record_path(
        evidence_records, "current_head_gate"
    )

    prerequisites = [
        _prerequisite(
            "all_prerequisite_handoffs_integrated",
            handoff_state,
            "integrator",
            "tools/agent_governance/handoff.py validate",
            "integrate and validate every prerequisite handoff on main",
        ),
        _prerequisite(
            "production_pit_seven_file_bundle",
            pit_state,
            "data_steward",
            "quant_us.data.pit_dataready_consumer.evaluate_production_pit_bundle",
            "publish and integrate a current immutable production PIT seven-file bundle",
        ),
        _prerequisite(
            "canonical_backtest_portfolio_ledger",
            canonical_state,
            "super_developer",
            "US canonical evidence engineering-check and ledger-replay contract",
            "rebuild canonical evidence from accepted production PIT without changing the frozen candidate",
        ),
        _prerequisite(
            "forward_observation_30_natural_days",
            observation_state["natural_days"],
            "natural_time",
            "us_equity_forward_observation_receipt_v1",
            "continue one eligible receipt per natural day without backfill until 30 days complete",
        ),
        _prerequisite(
            "forward_observation_252_distinct_sessions",
            observation_state["sessions"],
            "natural_time",
            "us_equity_forward_observation_receipt_v1",
            "continue immutable finalized-session observation until 252 distinct XNYS sessions complete",
        ),
        _prerequisite(
            "oms_reconciliation_failure_drills",
            oms_state,
            "paper_operations",
            "us_v3_paper_oms_reconciliation_v1 contract",
            "repair and rerun the offline fake-adapter OMS drill suite",
        ),
        _prerequisite(
            "broker_credential_review",
            broker_state,
            "paper_operations",
            "us_equity_broker_credentials_review_v1 metadata-only validator",
            "record the metadata-only broker credential review outside source control, then rebuild its report",
        ),
        _prerequisite(
            "manual_decision_record",
            manual_state,
            "architect",
            "us_equity_manual_decision_record_report_v1 validator",
            "record an architect/manual-review decision only after every evidence prerequisite is complete",
        ),
        _prerequisite(
            "current_head_gate_structural_validation",
            gate_state,
            "super_developer",
            "us_equity_current_head_gate_rebuild_v1 schema/hash/safety validator",
            "run the serialized current-HEAD gate builder and retain its blocked decision",
        ),
        _prerequisite(
            "engineering_defect_inventory_evaluated",
            {
                "satisfied": True,
                "blockers": [],
                "evidence_path": DEFAULT_CONFIG.as_posix(),
            },
            "super_developer",
            "G12 current-main targeted regression inventory",
            "retain every open implementation defect as an independent repair ticket",
        ),
    ]
    prerequisites.extend(_engineering_prerequisites(engineering_state))

    root_blockers = _root_blockers(prerequisites)
    original_blockers = _original_blockers(
        evidence=evidence,
        config=config,
    )
    retirement = [
        _retirement_row(
            blocker=blocker,
            source_id=source_id,
            prerequisites=prerequisites,
            evidence_records=evidence_records,
        )
        for source_id, blocker in original_blockers
    ]
    unclassified = [
        row["blocker"]
        for row in retirement
        if row["category"] == "unsupported"
    ]
    if unclassified:
        raise USFinalPaperReadinessError(
            f"unsupported_blocker_taxonomy:{unclassified[0]}"
        )

    ready = not root_blockers
    decision = (
        "promotion_evidence_ready_for_architect_review_only"
        if ready
        else "blocked_fail_closed_no_paper_no_live"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": "US-V3-FINAL-PAPER-READINESS-01",
        "source_head": head,
        "generated_at_utc": _z(generated),
        "status": "review_complete" if ready else "blocked",
        "decision": decision,
        "wrapper_status": "success",
        "review_stopped_by_engineering_defect": bool(
            engineering_state["defects"]
        ),
        "readiness": {
            "packet_quality_checked": True,
            "final_review_quality_checked": not bool(
                engineering_state["defects"]
            ),
            "promotion_evidence_ready": ready,
            "paper_enabled": False,
            "live_enabled": False,
        },
        "prerequisites": prerequisites,
        "evidence": dict(evidence_records),
        "blocker_taxonomy": {
            "root_blockers": root_blockers,
            "root_blocker_count": len(root_blockers),
            "original_blocker_retirement": retirement,
            "original_blocker_count": len(retirement),
            "unclassified_blockers": [],
        },
        "engineering_defects": engineering_state["defects"],
        "validation": {
            "all_prerequisite_handoffs_valid": handoff_state["satisfied"],
            "current_head_gate_schema_hash_safety_valid": gate_state[
                "satisfied"
            ],
            "canonical_replay_valid": canonical_state["replay_valid"],
            "oms_recovery_and_reconciliation_valid": oms_state[
                "replay_valid"
            ],
            "all_evidence_safety_flags_false": True,
            "unknown_or_unclassified_blocker_count": 0,
            "wrapper_success_substitutes_for_decision": False,
        },
        "safety": _safety(),
        "run_id": "",
        "outputs": {
            "report": "pending",
            "manifest": "pending",
            "latest_pointer": "pending",
        },
        "artifact_identity_sha256": "0" * 64,
    }
    return report


def _load_evidence(
    *,
    root: Path,
    config: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    paths = _mapping(config.get("evidence_paths"))
    payloads: dict[str, dict[str, Any]] = {}
    records: dict[str, dict[str, Any]] = {}

    for evidence_id, raw in paths.items():
        if evidence_id in {"integrated_handoffs", "producer_handoffs"}:
            loaded: dict[str, Any] = {}
            item_records: list[dict[str, Any]] = []
            for item in _strings(raw):
                path = _within(root, Path(item))
                payload = _read_object(path) if path.is_file() else {}
                loaded[item] = payload
                item_records.append(_record(root, path, payload))
            payloads[evidence_id] = loaded
            records[evidence_id] = {
                "items": item_records,
                "validator": "handoff.py validate plus main-ancestor check",
            }
            continue
        path = _within(root, Path(str(raw)))
        payload = _read_object(path) if path.is_file() else {}
        if evidence_id == "observation" and payload.get(
            "schema_version"
        ) == "us_equity_forward_observation_latest_pointer_v1":
            payload, pointer_record = _resolve_observation_pointer(
                root=root,
                pointer=payload,
                pointer_path=path,
            )
            records[evidence_id] = pointer_record
        else:
            records[evidence_id] = _record(root, path, payload)
        payloads[evidence_id] = payload

    if not payloads.get("observation"):
        fallback = _within(
            root,
            Path(
                str(
                    _mapping(config.get("fallback_evidence_paths")).get(
                        "observation", ""
                    )
                )
            ),
        )
        payloads["observation"] = (
            _read_object(fallback) if fallback.is_file() else {}
        )
        records["observation"] = _record(
            root,
            fallback,
            payloads["observation"],
        )
        records["observation"]["fallback_used"] = True

    mutable = dict(config)
    mutable["_repo_root"] = str(root)
    if isinstance(config, dict):
        config["_repo_root"] = str(root)
    return payloads, records


def _evaluate_handoffs(
    *,
    current_head: str,
    payloads: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(str(config.get("_repo_root") or ".")).resolve()
    integrated = _mapping(payloads.get("integrated_handoffs"))
    required = _strings(
        _mapping(config.get("evidence_paths")).get("integrated_handoffs")
    )
    blockers: list[str] = []
    for rel in required:
        payload = _mapping(integrated.get(rel))
        if not payload:
            blockers.append(f"integrated_handoff_missing:{rel}")
            continue
        if payload.get("event_type") != "integrated":
            blockers.append(f"integrated_handoff_wrong_event_type:{rel}")
        deliverable = str(payload.get("deliverable_commit") or "")
        if not _COMMIT_RE.fullmatch(deliverable) or not _is_ancestor(
            root,
            deliverable,
            current_head,
        ):
            blockers.append(f"integrated_handoff_not_on_current_head:{rel}")
        if _handoff_tool_status(root, rel) != "valid":
            blockers.append(f"integrated_handoff_invalid:{rel}")
    return {
        "satisfied": not blockers and len(required) > 0,
        "status": "satisfied" if not blockers else "blocked",
        "blockers": blockers,
        "evidence_path": "multiple integrated handoff envelopes",
    }


def _evaluate_production_pit(payload: Mapping[str, Any]) -> dict[str, Any]:
    production = _mapping(payload.get("production_pit"))
    accepted = (
        production.get("accepted") is True
        and production.get("state") == "accepted"
        and len(_list(production.get("validated_files"))) == 6
        and not _strings(production.get("blockers"))
    )
    return {
        "satisfied": accepted,
        "status": "satisfied" if accepted else "blocked",
        "blockers": _strings(production.get("blockers"))
        or ["production_pit_seven_file_bundle_not_accepted"],
        "evidence_path": "",
    }


def _evaluate_canonical(payload: Mapping[str, Any]) -> dict[str, Any]:
    checks = _mapping(payload.get("engineering_checks"))
    ledger = _mapping(payload.get("ledger_reconciliation"))
    required = (
        "canonical_event_chain_complete",
        "deterministic_replay_passed",
        "ledger_reconciliation_passed",
        "no_lookahead_passed",
        "cost_stress_passed",
        "all_layers_version_bound",
    )
    passed = all(checks.get(item) is True for item in required)
    replay_valid = (
        checks.get("deterministic_replay_passed") is True
        and ledger.get("deterministic_replay_hash_match") is True
        and ledger.get("passed") is True
    )
    return {
        "satisfied": passed and replay_valid,
        "status": "satisfied_quality_checked_research_only"
        if passed and replay_valid
        else "blocked",
        "blockers": []
        if passed and replay_valid
        else ["canonical_backtest_portfolio_ledger_contract_incomplete"],
        "replay_valid": replay_valid,
        "evidence_path": "",
    }


def _evaluate_observation(
    payload: Mapping[str, Any],
    *,
    current_head: str,
) -> dict[str, Any]:
    windows = _mapping(payload.get("windows"))
    identity = _mapping(payload.get("identity"))
    if windows:
        natural = _mapping(windows.get("paper_review_natural_days"))
        sessions = _mapping(
            windows.get("independent_confirmation_trading_sessions")
        )
        current = identity.get("source_head") == current_head
        natural_ok = (
            current
            and natural.get("complete") is True
            and int(natural.get("observed") or 0) >= 30
        )
        sessions_ok = (
            current
            and sessions.get("complete") is True
            and int(sessions.get("observed") or 0) >= 252
        )
    else:
        state = _mapping(payload.get("observation_state"))
        natural_ok = str(
            state.get("paper_review_natural_days") or ""
        ).startswith("30_of_30")
        sessions_ok = str(
            state.get("independent_confirmation_sessions") or ""
        ).startswith("252_of_252")
        current = payload.get("source_head") == current_head
        natural_ok = natural_ok and current
        sessions_ok = sessions_ok and current
    return {
        "natural_days": {
            "satisfied": natural_ok,
            "status": "satisfied" if natural_ok else "blocked",
            "blockers": []
            if natural_ok
            else ["forward_observation_30_natural_days_incomplete"],
            "evidence_path": "",
        },
        "sessions": {
            "satisfied": sessions_ok,
            "status": "satisfied" if sessions_ok else "blocked",
            "blockers": []
            if sessions_ok
            else ["forward_observation_252_sessions_incomplete"],
            "evidence_path": "",
        },
    }


def _evaluate_oms(payload: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = _mapping(payload.get("scenario_results"))
    lifecycle = _mapping(payload.get("lifecycle"))
    recovery = _mapping(payload.get("recovery"))
    required = (
        "atomic_uow_rollback",
        "broker_outage",
        "cancel_pending_fail_closed",
        "crash_restart_recovery",
        "idempotency",
        "market_closed",
        "out_of_order_callback",
        "partial_fill",
        "reconciliation_break",
        "reconciliation_recovery",
        "truncated_log_fail_closed",
    )
    passed = (
        lifecycle.get("complete") is True
        and all(scenarios.get(item) is True for item in required)
    )
    replay_valid = (
        _mapping(recovery.get("crash_recovery_probe")).get("passed")
        is True
        and _mapping(recovery.get("truncated_log_probe")).get("passed")
        is True
    )
    return {
        "satisfied": passed and replay_valid,
        "status": "satisfied_quality_checked_fixture_drill"
        if passed and replay_valid
        else "blocked",
        "blockers": []
        if passed and replay_valid
        else ["oms_reconciliation_failure_drills_incomplete"],
        "replay_valid": replay_valid,
        "evidence_path": "",
    }


def _evaluate_broker(payload: Mapping[str, Any]) -> dict[str, Any]:
    satisfied = (
        payload.get("status") == "broker_credentials_review_proven"
        and payload.get("broker_credentials_proven") is True
        and not _strings(payload.get("blockers"))
    )
    return {
        "satisfied": satisfied,
        "status": "satisfied" if satisfied else "blocked",
        "blockers": _strings(payload.get("blockers"))
        or ["broker_credential_review_not_valid"],
        "evidence_path": "",
    }


def _evaluate_manual(payload: Mapping[str, Any]) -> dict[str, Any]:
    satisfied = (
        payload.get("status") == "manual_decision_record_valid"
        and not _strings(payload.get("blockers"))
    )
    return {
        "satisfied": satisfied,
        "status": "satisfied" if satisfied else "blocked",
        "blockers": _strings(payload.get("blockers"))
        or ["manual_decision_record_not_valid"],
        "evidence_path": "",
    }


def _evaluate_current_head_gate(
    payload: Mapping[str, Any],
    *,
    current_head: str,
) -> dict[str, Any]:
    checks = _mapping(payload.get("validation_checks"))
    satisfied = (
        payload.get("schema_version")
        == "us_equity_current_head_gate_rebuild_v1"
        and payload.get("source_head") == current_head
        and payload.get("wrapper_status") == "success"
        and checks.get("all_output_schemas_valid") is True
        and checks.get("all_output_hashes_verified") is True
        and checks.get("all_declared_input_hashes_verified") is True
        and checks.get("all_safety_flags_false") is True
    )
    return {
        "satisfied": satisfied,
        "status": "satisfied_structural_blocked_decision"
        if satisfied
        else "blocked",
        "blockers": []
        if satisfied
        else ["current_head_gate_schema_hash_safety_validation_missing"],
        "evidence_path": "",
    }


def _evaluate_engineering_defects(
    *,
    root: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    defects: list[dict[str, Any]] = []
    for item in _list(config.get("engineering_defects")):
        row = _mapping(item)
        ticket = str(row.get("ticket") or "")
        if row.get("status") != "open":
            continue
        defects.append(
            {
                "defect_id": str(row.get("defect_id") or ""),
                "status": "open",
                "owner": str(row.get("owner") or "super_developer"),
                "evidence_path": str(row.get("evidence_path") or ""),
                "validator": str(row.get("validator") or ""),
                "repair_ticket": ticket,
                "repair_ticket_exists": bool(ticket and (root / ticket).is_file()),
                "next_action": str(row.get("next_action") or ""),
            }
        )
    return {
        "satisfied": not defects,
        "status": "blocked" if defects else "satisfied",
        "blockers": [row["defect_id"] for row in defects],
        "defects": defects,
        "evidence_path": defects[0]["evidence_path"] if defects else "",
    }


def _prerequisite(
    prerequisite_id: str,
    state: Mapping[str, Any],
    owner: str,
    validator: str,
    next_action: str,
    *,
    inverse: bool = False,
) -> dict[str, Any]:
    satisfied = bool(state.get("satisfied"))
    return {
        "prerequisite_id": prerequisite_id,
        "status": "satisfied" if satisfied else "blocked",
        "satisfied": satisfied,
        "owner": owner,
        "evidence_path": str(state.get("evidence_path") or ""),
        "validator": validator,
        "blockers": _strings(state.get("blockers")),
        "retirement_decision": "retired"
        if satisfied
        else "retained_until_validator_passes",
        "next_action": next_action,
        "inverse_semantics": inverse,
    }


def _engineering_prerequisites(
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _list(state.get("defects")):
        defect = _mapping(item)
        defect_id = str(defect.get("defect_id") or "engineering_followup")
        rows.append(
            _prerequisite(
                f"open_engineering_defect:{defect_id}",
                {
                    "satisfied": False,
                    "blockers": [defect_id],
                    "evidence_path": defect.get("evidence_path"),
                },
                str(defect.get("owner") or "super_developer"),
                str(
                    defect.get("validator")
                    or "targeted current-main regression"
                ),
                str(
                    defect.get("next_action")
                    or "complete the independent repair ticket and rerun the exact regression"
                ),
                inverse=True,
            )
        )
    return rows


def _root_blockers(
    prerequisites: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for prerequisite in prerequisites:
        if prerequisite.get("satisfied") is True:
            continue
        for code in _strings(prerequisite.get("blockers")):
            root = _canonical_root(code)
            if root in seen:
                continue
            seen.add(root)
            rows.append(
                {
                    "code": root,
                    "category": _category(root),
                    "owner": str(prerequisite.get("owner") or ""),
                    "evidence_path": str(
                        prerequisite.get("evidence_path") or ""
                    ),
                    "validator": str(
                        prerequisite.get("validator") or ""
                    ),
                    "retirement_decision": "retained",
                    "next_action": str(
                        prerequisite.get("next_action") or ""
                    ),
                }
            )
    return rows


def _original_blockers(
    *,
    evidence: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    producers = _mapping(evidence.get("producer_handoffs"))
    for path, payload in producers.items():
        for blocker in _top_level_blockers(payload):
            if not blocker.startswith("classification:"):
                rows.append((path, blocker))
    for evidence_id in (
        "production_pit",
        "canonical",
        "oms",
        "observation",
        "current_head_gate",
    ):
        for blocker in _top_level_blockers(evidence.get(evidence_id, {})):
            rows.append((evidence_id, blocker))
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row not in seen:
            seen.add(row)
            unique.append(row)
    return unique


def _retirement_row(
    *,
    blocker: str,
    source_id: str,
    prerequisites: Sequence[Mapping[str, Any]],
    evidence_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    root = _canonical_root(blocker)
    category = _category(root)
    retired = _historically_retired(blocker)
    conclusion = "retired" if retired else "retained"
    if "unclassified_fail_closed_evidence" in blocker:
        root = "legacy_unmapped_gate_evidence_requires_explicit_taxonomy"
        category = "evidence_contract"
        conclusion = "retained_reclassified"
    record = _mapping(evidence_records.get(source_id))
    path = source_id if "/" in source_id else str(record.get("path") or source_id)
    return {
        "blocker": blocker,
        "source_id": source_id,
        "root_blocker": root,
        "category": category,
        "evidence_path": path,
        "validator": _validator_for(category),
        "conclusion": conclusion,
        "retirement_decision": (
            "retired_by_integrated_or_current_main_evidence"
            if retired
            else "retain_until_root_validator_passes"
        ),
    }


def _canonical_root(value: str) -> str:
    text = value.lower()
    if any(
        token in text
        for token in (
            "production_pit",
            "corporate_action",
            "delisted",
            "survivorship",
            "adjustment_visibility",
            "source_splice",
            "calendar_contract",
            "immutable_dataset",
            "expected_finalized_session_missing",
        )
    ):
        return "production_pit_evidence_unavailable"
    if "252" in text or "confirmation_session" in text or "confirmation_window" in text:
        return "forward_observation_252_sessions_incomplete"
    if any(
        token in text
        for token in (
            "forward_observation",
            "natural_day",
            "natural_time",
            "30_natural",
            "paper_review_natural_days",
        )
    ):
        return "forward_observation_30_natural_days_incomplete"
    if any(token in text for token in ("broker_credentials", "credential_review")):
        return "broker_credential_review_not_valid"
    if any(token in text for token in ("manual_approval", "manual_paper", "manual_decision")):
        return "manual_decision_record_not_valid"
    if any(token in text for token in ("durable_path", "history_artifact_path")):
        return "paper_durable_path_assertion_drift"
    if "audit_path" in text or "live_order_submission_gate" in text:
        return "live_submission_gate_audit_path_not_injected"
    if "default_template" in text:
        return "broker_credentials_default_template_import_drift"
    if any(token in text for token in ("oms", "reconciliation", "execution_control")):
        return "oms_reconciliation_failure_drills_incomplete"
    if any(
        token in text
        for token in (
            "artifact",
            "current_head",
            "promotion_evidence",
            "non_sparse",
        )
    ):
        return "current_head_evidence_contract_incomplete"
    if any(
        token in text
        for token in (
            "app_factory",
            "entrypoint_wiring",
            "router_wiring",
            "integrator_ticket",
            "shared_asset_neutral",
            "breaking_core",
        )
    ):
        return "integration_contract_followup"
    if any(
        token in text
        for token in (
            "paper_start",
            "real_paper",
            "production_event_ledger",
            "paper_runtime",
            "fixture_simulated_ledger",
            "paper_and_live",
            "promotion_paper_private",
        )
    ):
        return "pre_start_scope_guardrail"
    if any(
        token in text
        for token in (
            "calendar_provider_label",
            "builder_extraction_deferred",
        )
    ):
        return "engineering_followup"
    if "unclassified_fail_closed_evidence" in text:
        return "legacy_unmapped_gate_evidence_requires_explicit_taxonomy"
    return "unsupported"


def _category(root: str) -> str:
    if root.startswith("production_pit"):
        return "external_data"
    if root.startswith("forward_observation"):
        return "natural_time"
    if root.startswith("broker_credential"):
        return "manual_control"
    if root.startswith("manual_decision"):
        return "manual_approval"
    if (
        root.startswith("paper_durable")
        or root.startswith("live_submission_gate")
        or root.startswith("engineering")
    ):
        return "engineering"
    if root.startswith("oms_"):
        return "execution_control"
    if root.startswith("current_head"):
        return "evidence_contract"
    if root.startswith("integration_"):
        return "integration"
    if root.startswith("pre_start"):
        return "scope_guardrail"
    if root.startswith("legacy_unmapped"):
        return "evidence_contract"
    if root.startswith("broker_credentials_default"):
        return "engineering"
    return "unsupported"


def _historically_retired(blocker: str) -> bool:
    text = blocker.lower()
    return any(
        token in text
        for token in (
            "app_factory",
            "entrypoint_wiring",
            "router_wiring",
            "integrator_ticket",
            "shared_asset_neutral",
            "breaking_core",
            "current_head_promotion_evidence_not_built",
            "current_head_durable_artifacts_require_rebuild",
            "historical_us_artifact_contract_suite_requires_non_sparse",
            "default_template_import_drift",
            "three_btc_artifact_dependent_tests_unavailable",
            "paper_and_live_gates_remain_locked",
            "promotion_paper_private_order_and_live_gates_remain_locked",
            "fixture_simulated_ledger_not_production_event_ledger",
            "paper_start_not_authorized",
            "real_paper_evidence_missing",
            "production_event_ledger_missing",
        )
    )


def _validator_for(category: str) -> str:
    return {
        "external_data": "production PIT consumer and seven-file hash/visibility validator",
        "natural_time": "immutable forward-observation receipt continuity validator",
        "manual_control": "metadata-only broker credential review validator",
        "manual_approval": "manual decision record validator",
        "engineering": "independent repair ticket regression",
        "execution_control": "offline OMS recovery/reconciliation contract",
        "evidence_contract": "current-HEAD schema/hash/taxonomy validator",
        "integration": "integrated handoff validator",
        "scope_guardrail": "pre-start scope classification",
    }.get(category, "unsupported")


def _publish_run(
    *,
    root: Path,
    output_root: Path,
    report: Mapping[str, Any],
    report_path: Path,
    manifest_path: Path,
    config_path: Path,
    schema_path: Path,
) -> None:
    run_dir = report_path.parent
    if run_dir.exists():
        raise USFinalPaperReadinessError("final_readiness_run_exists")
    staging = run_dir.with_name(f".{run_dir.name}.{uuid.uuid4().hex}.staging")
    staging.mkdir(parents=True, exist_ok=False)
    try:
        staged_report = staging / "report.json"
        _write_json(staged_report, report)
        report_sha = _sha256(staged_report)
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": report["run_id"],
            "source_head": report["source_head"],
            "generated_at_utc": report["generated_at_utc"],
            "status": report["status"],
            "decision": report["decision"],
            "report_path": _repo_or_posix(report_path, root),
            "report_sha256": report_sha,
            "config_path": _repo_or_posix(config_path, root),
            "config_sha256": _sha256(config_path),
            "schema_path": _repo_or_posix(schema_path, root),
            "schema_sha256": _sha256(schema_path),
            "safety": _safety(),
        }
        _write_json(staging / "manifest.json", manifest)
        manifest_sha = _sha256(staging / "manifest.json")
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, run_dir)
        latest = {
            "schema_version": LATEST_SCHEMA_VERSION,
            "run_id": report["run_id"],
            "source_head": report["source_head"],
            "status": report["status"],
            "decision": report["decision"],
            "report_path": _repo_or_posix(report_path, root),
            "report_sha256": report_sha,
            "manifest_path": _repo_or_posix(manifest_path, root),
            "manifest_sha256": manifest_sha,
            "paper_or_live_unlock_allowed": False,
        }
        _write_json_atomic(
            output_root / "latest" / "latest_pointer.json",
            latest,
        )
    except Exception:
        if staging.exists():
            import shutil

            shutil.rmtree(staging)
        raise


def _resolve_observation_pointer(
    *,
    root: Path,
    pointer: Mapping[str, Any],
    pointer_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = _within(root, Path(str(pointer.get("report_path") or "")))
    payload = _read_object(report_path) if report_path.is_file() else {}
    valid_hash = (
        report_path.is_file()
        and _sha256(report_path) == pointer.get("receipt_sha256")
    )
    if not valid_hash:
        payload = {}
    return payload, {
        "path": _repo_or_posix(pointer_path, root),
        "exists": pointer_path.is_file(),
        "sha256": _sha256(pointer_path) if pointer_path.is_file() else "",
        "resolved_report_path": _repo_or_posix(report_path, root),
        "resolved_report_sha256": _sha256(report_path)
        if report_path.is_file()
        else "",
        "hash_verified": valid_hash,
    }


def _record(
    root: Path,
    path: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "path": _repo_or_posix(path, root),
        "exists": path.is_file(),
        "sha256": _sha256(path) if path.is_file() else "",
        "schema_version": str(payload.get("schema_version") or ""),
        "status": str(payload.get("status") or ""),
        "decision": str(payload.get("decision") or ""),
    }


def _record_path(
    records: Mapping[str, Mapping[str, Any]],
    evidence_id: str,
) -> str:
    return str(_mapping(records.get(evidence_id)).get("path") or evidence_id)


def _handoff_tool_status(root: Path, rel: str) -> str:
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "tools/agent_governance/handoff.py"),
            "validate",
            "--input",
            rel,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return "invalid"
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return "invalid"
    return str(payload.get("status") or "invalid")


def _is_ancestor(root: Path, commit: str, head: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, head],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def _validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != (
        "us_v3_final_paper_readiness_config_v1"
    ):
        raise USFinalPaperReadinessError("final_readiness_config_invalid")
    safety = _mapping(config.get("safety"))
    if any(value is not False for value in safety.values()):
        raise USFinalPaperReadinessError(
            "final_readiness_config_unsafe_flag"
        )


def _extract_blockers(payload: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if key == "blockers" and isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item:
                    rows.append(item)
                elif isinstance(item, Mapping):
                    code = str(item.get("code") or item.get("blocker") or "")
                    if code:
                        rows.append(code)
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return list(dict.fromkeys(rows))


def _top_level_blockers(payload: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in _list(payload.get("blockers")):
        if isinstance(item, str) and item:
            rows.append(item)
        elif isinstance(item, Mapping):
            code = str(item.get("code") or item.get("blocker") or "")
            if code:
                rows.append(code)
    return list(dict.fromkeys(rows))


def _unsafe_true_paths(payload: Mapping[str, Any]) -> list[str]:
    return [
        path
        for path, value in _walk(payload)
        if path.rsplit(".", 1)[-1] in _PROHIBITED_TRUE_FIELDS
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


def _safety() -> dict[str, bool]:
    return {
        "promotion_allowed": False,
        "paper_allowed": False,
        "paper_enabled": False,
        "paper_runner_allowed": False,
        "paper_runner_started": False,
        "paper_queue_write_allowed": False,
        "live_allowed": False,
        "live_enabled": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_allowed": False,
        "order_endpoint_used": False,
        "broker_access_allowed": False,
        "broker_calls_used": False,
        "withdraw_allowed": False,
        "demo_allowed": False,
        "real_order_allowed": False,
        "real_order_submitted": False,
        "network_used": False,
        "secret_accessed": False,
    }


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    material = {
        key: value
        for key, value in payload.items()
        if key != "artifact_identity_sha256"
    }
    raw = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    _write_json(temporary, payload)
    os.replace(temporary, path)


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise USFinalPaperReadinessError(
            f"final_readiness_json_not_object:{path.as_posix()}"
        )
    return dict(payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _absolute(path: Path, root: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _within(root: Path, path: Path) -> Path:
    absolute = _absolute(path, root)
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise USFinalPaperReadinessError(
            f"final_readiness_path_outside_repo:{path.as_posix()}"
        ) from exc
    return absolute


def _repo_or_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _full_commit(value: str) -> str:
    commit = str(value).lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise USFinalPaperReadinessError(
            "final_readiness_full_commit_required"
        )
    return commit


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
    "DEFAULT_CONFIG",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_SCHEMA",
    "SCHEMA_VERSION",
    "USFinalPaperReadinessError",
    "build_us_equity_final_paper_readiness",
    "evaluate_us_equity_final_paper_readiness",
]
