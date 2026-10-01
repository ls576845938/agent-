from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.btc_10s_microstructure_data_contract import (
    FAMILIES,
    HORIZONS,
    evaluate_readiness,
)


DEPTH_FILL_MAPPING_BLOCKER = "btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing"
OBSERVATION_WINDOW_BLOCKER = "btc_okx_native:25_hour_demo_observation_window_incomplete"
ACTIVE_CRITERIA_SCHEMA_VERSION = "btc_promotion_gate_active_criteria_v1"
INFORMATION_COVERAGE_BLOCKER = (
    "btc_okx_native:effective_sample_regime_coverage_prereg_evidence_incomplete"
)
ACTIVE_FAMILY_SCOPE_BLOCKER = (
    "btc_okx_native:active_strategy_family_dependency_scope_missing"
)
ACTIVE_FAMILY_CAPABILITY_BLOCKER = (
    "btc_okx_native:active_strategy_family_required_capabilities_incomplete"
)
ACTIVE_CRITERIA_LINEAGE_BLOCKER = (
    "btc_okx_native:active_criteria_pointer_lineage_mismatch"
)
OPEN_INTEREST_FAMILY_BLOCKER = (
    "btc_okx_native:open_interest_history_required_for_active_family"
)
OPEN_INTEREST_DEPENDENT_FAMILIES = frozenset(
    {"liquidation_cascade_recovery"}
)
FROZEN_PREREG_RELATIVE_PATH = Path(
    "docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json"
)
FROZEN_PREREG_BLOB_SHA256 = (
    "f32980b2514145a1feab4e40713b072b7a2317e6b83353f50e0f42dcbc2fbb7b"
)
FROZEN_PREREG_SEMANTIC_SHA256 = (
    "23a3e2b17c9c2b0b654d6ee64f6f3f522ca0a8d235b7adb42f9687467de601f2"
)
UNCHANGED_EXTERNAL_BLOCKERS = (
    "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing",
    "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime",
    "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
    OBSERVATION_WINDOW_BLOCKER,
    "btc_okx_native:manual_promotion_approval_missing",
)


def evaluate_active_criteria_contract(
    *,
    report: Mapping[str, Any],
    current_head: str,
    expected_preregistration: Mapping[str, Any] | None = None,
    expected_prereg_blob_sha256: str = "",
    pointer_validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate frozen information gates and family-scoped dependencies.

    Thresholds are consumed from a versioned preregistration embedded in the
    evidence.  This evaluator intentionally defines no sample-count, ESS, or
    regime thresholds of its own.
    """

    errors: list[str] = []
    if report.get("schema_version") != ACTIVE_CRITERIA_SCHEMA_VERSION:
        errors.append("active_criteria:schema_mismatch")
    if report.get("source_head") != current_head:
        errors.append("active_criteria:wrong_head")
    family = str(report.get("active_strategy_family") or "").strip()
    horizon = str(report.get("active_horizon") or "").strip()
    family_scope_valid = family in FAMILIES and horizon in HORIZONS
    if not family_scope_valid:
        errors.append("active_criteria:family_or_horizon_unregistered")

    prereg = _mapping(report.get("preregistration"))
    metrics = _mapping(report.get("measured_metrics"))
    semantic_sha = str(report.get("prereg_semantic_sha256") or "")
    prereg_blob_sha = str(report.get("prereg_blob_sha256") or "")
    expected_prereg = _mapping(expected_preregistration)
    expected_semantic_sha = _stable_hash(expected_prereg) if expected_prereg else ""
    prereg_valid = (
        bool(prereg)
        and bool(expected_prereg)
        and prereg == expected_prereg
        and semantic_sha == expected_semantic_sha
        and semantic_sha == FROZEN_PREREG_SEMANTIC_SHA256
        and prereg_blob_sha == expected_prereg_blob_sha256
        and prereg_blob_sha == FROZEN_PREREG_BLOB_SHA256
    )
    if not prereg_valid:
        errors.append("active_criteria:preregistration_missing_or_hash_invalid")
    elif (
        prereg.get("schema_version")
        != "btc_10s_microstructure_data_contract_prereg_v1"
        or prereg.get("purpose") != "research_admission_only"
        or not _mapping(prereg.get("information_thresholds"))
        or not _mapping(prereg.get("family_requirements"))
    ):
        prereg_valid = False
        errors.append("active_criteria:preregistration_contract_invalid")

    pointer = _mapping(pointer_validation)
    manifest_ref = _mapping(pointer.get("manifest"))
    evidence_ref = _mapping(pointer.get("evidence"))
    attestation = _mapping(report.get("data_steward_attestation"))
    verified_attestation = _mapping(
        pointer.get("verified_data_steward_attestation")
    )
    attestation_reference_fields = (
        "kind",
        "uri",
        "path",
        "sha256",
        "producer_role",
    )
    lineage_binding_valid = (
        pointer.get("status") == "valid_current_head"
        and report.get("run_id") == pointer.get("run_id")
        and report.get("data_version") == pointer.get("data_version")
        and report.get("immutable_manifest_sha256")
        == manifest_ref.get("actual_sha256")
        and report.get("immutable_evidence_sha256")
        == evidence_ref.get("actual_sha256")
        and verified_attestation.get("verified") is True
        and verified_attestation.get("producer_role") == "data_steward"
        and _is_sha256(str(verified_attestation.get("sha256") or ""))
        and all(
            str(attestation.get(key) or "")
            == str(verified_attestation.get(key) or "")
            and bool(str(verified_attestation.get(key) or ""))
            for key in attestation_reference_fields
        )
    )
    if not lineage_binding_valid:
        errors.append("active_criteria:pointer_identity_or_attestation_mismatch")

    selected: Mapping[str, Any] = {}
    if family_scope_valid and prereg_valid and metrics:
        try:
            selected = next(
                row
                for row in evaluate_readiness(prereg, metrics)
                if row.get("family") == family
                and row.get("horizon") == horizon
            )
        except (KeyError, TypeError, ValueError, StopIteration) as exc:
            errors.append(
                "active_criteria:information_evidence_invalid:"
                f"{type(exc).__name__}"
            )
    elif not metrics:
        errors.append("active_criteria:measured_metrics_missing")

    selected_blockers = [str(value) for value in selected.get("blockers") or []]
    requirements = _mapping(prereg.get("family_requirements"))
    required_fields = {
        str(value) for value in requirements.get(family) or []
    }
    field_blockers = {f"{field}_missing" for field in required_fields}
    information_blockers = [
        value for value in selected_blockers if value not in field_blockers
    ]
    information_valid = bool(selected) and not information_blockers
    family_capabilities_valid = (
        bool(selected)
        and selected.get("status") == "ready"
        and not selected_blockers
    )
    oi_required = family in OPEN_INTEREST_DEPENDENT_FAMILIES
    fields = _mapping(metrics.get("fields"))
    oi_valid = not oi_required or fields.get("time_aligned_open_interest") is True

    blockers: list[str] = []
    if not family_scope_valid:
        blockers.append(ACTIVE_FAMILY_SCOPE_BLOCKER)
    if not prereg_valid or not information_valid:
        blockers.append(INFORMATION_COVERAGE_BLOCKER)
    if family_scope_valid and information_valid and not family_capabilities_valid:
        blockers.append(ACTIVE_FAMILY_CAPABILITY_BLOCKER)
    if oi_required and not oi_valid:
        blockers.append(OPEN_INTEREST_FAMILY_BLOCKER)
    if not lineage_binding_valid:
        blockers.append(ACTIVE_CRITERIA_LINEAGE_BLOCKER)
    return {
        "schema_version": "btc_promotion_gate_active_criteria_evaluation_v1",
        "source_head": current_head,
        "active_strategy_family": family,
        "active_horizon": horizon,
        "active_family_scope_valid": family_scope_valid,
        "information_coverage_evidence_valid": information_valid,
        "family_capabilities_valid": family_capabilities_valid,
        "open_interest_required": oi_required,
        "open_interest_evidence_valid": oi_valid,
        "pointer_lineage_binding_valid": lineage_binding_valid,
        "selected_readiness": dict(selected),
        "validation_errors": _dedupe(errors),
        "promotion_blockers": _dedupe(blockers),
        "threshold_source": {
            "schema_version": str(prereg.get("schema_version") or ""),
            "ticket_id": str(prereg.get("ticket_id") or ""),
            "semantic_sha256": semantic_sha,
            "blob_sha256": prereg_blob_sha,
            "thresholds_embedded_in_evidence": True,
            "evaluator_defined_numeric_thresholds": False,
        },
    }


def load_frozen_active_criteria_prereg(
    repo_root: Path,
    *,
    current_head: str = "HEAD",
) -> tuple[dict[str, Any], str]:
    """Load the exact Git-tracked prereg bytes anchored by code constants."""

    try:
        raw = subprocess.check_output(
            [
                "git",
                "-C",
                str(repo_root),
                "show",
                f"{current_head}:{FROZEN_PREREG_RELATIVE_PATH.as_posix()}",
            ],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return {}, ""
    blob_sha = hashlib.sha256(raw).hexdigest()
    if blob_sha != FROZEN_PREREG_BLOB_SHA256:
        return {}, ""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, ""
    if not isinstance(payload, dict):
        return {}, ""
    if _stable_hash(payload) != FROZEN_PREREG_SEMANTIC_SHA256:
        return {}, ""
    return payload, blob_sha


def evaluate_btc_okx_native_promotion_blockers(
    *,
    l2_batch_report: Mapping[str, Any],
    fill_mapping_report: Mapping[str, Any],
    observation_window_report: Mapping[str, Any] | None = None,
    current_head: str,
    now_utc: datetime | None = None,
    max_age: timedelta = timedelta(hours=24),
    existing_external_blockers: Sequence[str] = UNCHANGED_EXTERNAL_BLOCKERS,
) -> dict[str, Any]:
    """Evaluate depth and the authoritative Demo window, preserving other gates."""

    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    errors: list[str] = []
    _validate_common(
        report=l2_batch_report,
        label="l2_batch",
        current_head=current_head,
        now=now,
        max_age=max_age,
        errors=errors,
    )
    _validate_common(
        report=fill_mapping_report,
        label="fill_mapping",
        current_head=current_head,
        now=now,
        max_age=max_age,
        errors=errors,
    )
    if l2_batch_report.get("schema_version") != "btc_okx_l2_depth_observation_batch_v2":
        errors.append("l2_batch:schema_mismatch")
    if fill_mapping_report.get("schema_version") != "btc_depth_slippage_fill_mapping_report_v2":
        errors.append("fill_mapping:schema_mismatch")
    if l2_batch_report.get("data_version") != fill_mapping_report.get("data_version"):
        errors.append("cross_report:data_version_mismatch")
    if l2_batch_report.get("run_id") != fill_mapping_report.get("run_id"):
        errors.append("cross_report:run_id_mismatch")
    progress = _mapping(l2_batch_report.get("depth_gate_progress_after"))
    if progress.get("gate_ready") is not True:
        errors.append("l2_batch:depth_gate_not_ready")
    if fill_mapping_report.get("strategy_fill_mapping_verified") is not True:
        errors.append("fill_mapping:strategy_fill_mapping_unverified")
    if _mapping(fill_mapping_report.get("depth_integrity")).get("valid_for_mapping") is not True:
        errors.append("fill_mapping:depth_integrity_incomplete")

    depth_evidence_valid = not errors
    observation_errors = _validate_demo_observation_window(
        report=observation_window_report or {},
        current_head=current_head,
        now=now,
        max_age=max_age,
    )
    observation_evidence_valid = not observation_errors
    blockers = [
        blocker
        for blocker in existing_external_blockers
        if blocker != OBSERVATION_WINDOW_BLOCKER or not observation_evidence_valid
    ]
    if not depth_evidence_valid:
        blockers.insert(0, DEPTH_FILL_MAPPING_BLOCKER)
    return {
        "schema_version": "btc_okx_native_promotion_blocker_evaluation_v2",
        "current_head": current_head,
        "evaluated_at_utc": now.isoformat(),
        "depth_fill_mapping_evidence_valid": depth_evidence_valid,
        "depth_fill_mapping_blocker_retired": depth_evidence_valid,
        "observation_window_evidence_valid": observation_evidence_valid,
        "observation_window_blocker_retired": observation_evidence_valid,
        "validation_errors": _dedupe(errors),
        "observation_validation_errors": observation_errors,
        "promotion_blockers": _dedupe(blockers),
        "unchanged_external_blockers": list(existing_external_blockers),
        "quality_checked": depth_evidence_valid,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "paper_allowed": False,
        "live_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "withdraw_allowed": False,
    }


def _validate_demo_observation_window(
    *,
    report: Mapping[str, Any],
    current_head: str,
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    errors: list[str] = []
    if not report:
        return ["observation_window:missing"]
    if report.get("schema_version") != "btc_demo_observation_accumulator_v3":
        errors.append("observation_window:schema_mismatch")
    if report.get("source_head") != current_head:
        errors.append("observation_window:wrong_head")
    if report.get("authority") != "authorized_okx_demo_accumulator":
        errors.append("observation_window:not_authorized_okx_demo_accumulator")
    if report.get("evidence_class") != "authorized_okx_demo_observation_window":
        errors.append("observation_window:fixture_or_research_only")
    if int(report.get("required_observation_hours") or 0) != 25:
        errors.append("observation_window:threshold_mismatch")
    if int(report.get("observation_hours") or 0) < 25:
        errors.append("observation_window:insufficient_hours")
    if report.get("window_25h_complete") is not True:
        errors.append("observation_window:window_incomplete")
    readiness = _mapping(report.get("readiness"))
    if readiness.get("observation_window_ready") is not True:
        errors.append("observation_window:not_ready")
    integrity = _mapping(report.get("ledger_integrity"))
    if integrity.get("valid") is not True:
        errors.append("observation_window:ledger_invalid")
    for field in (
        "strategy_version",
        "data_version",
        "runtime_version",
        "runtime_run_id",
    ):
        if not str(report.get(field) or "").strip():
            errors.append(f"observation_window:{field}_missing")
    version_policy = _mapping(report.get("version_policy"))
    for field in (
        "cross_head_accumulation_allowed",
        "cross_strategy_version_accumulation_allowed",
        "cross_data_version_accumulation_allowed",
        "cross_runtime_version_accumulation_allowed",
        "cross_runtime_run_accumulation_allowed",
    ):
        if version_policy.get(field) is not False:
            errors.append(f"observation_window:{field}_unsafe")
    safety = _mapping(report.get("safety"))
    if not safety or any(value is not False for value in safety.values()):
        errors.append("observation_window:safety_boundary_violation")
    if OBSERVATION_WINDOW_BLOCKER in list(report.get("blockers") or []):
        errors.append("observation_window:blocker_present")
    generated = _parse_utc(report.get("generated_at_utc"))
    if generated is None:
        errors.append("observation_window:generated_at_invalid")
    elif generated > now or now - generated > max_age:
        errors.append("observation_window:stale_or_future")
    return _dedupe(errors)


def _validate_common(
    *,
    report: Mapping[str, Any],
    label: str,
    current_head: str,
    now: datetime,
    max_age: timedelta,
    errors: list[str],
) -> None:
    if not report:
        errors.append(f"{label}:missing")
        return
    if report.get("source_head") != current_head:
        errors.append(f"{label}:wrong_head")
    if report.get("promotion_evidence_ready") is not True:
        errors.append(f"{label}:not_promotion_evidence")
    if report.get("evidence_class") != "promotion_evidence":
        errors.append(f"{label}:diagnostic_or_fixture")
    if not str(report.get("data_version") or "").strip():
        errors.append(f"{label}:data_version_missing")
    if not str(report.get("run_id") or "").strip():
        errors.append(f"{label}:run_id_missing")
    if not _is_sha256(report.get("params_hash")):
        errors.append(f"{label}:params_hash_invalid")
    if not _is_sha256(report.get("output_hash")):
        errors.append(f"{label}:output_hash_invalid")
    input_hashes = report.get("input_hashes")
    if not isinstance(input_hashes, Mapping) or not input_hashes or not all(_is_sha256(value) for value in input_hashes.values()):
        errors.append(f"{label}:input_hashes_invalid")
    generated = _parse_utc(report.get("generated_at_utc"))
    if generated is None:
        errors.append(f"{label}:generated_at_invalid")
    elif generated > now or now - generated > max_age:
        errors.append(f"{label}:stale_or_future")


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _stable_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
