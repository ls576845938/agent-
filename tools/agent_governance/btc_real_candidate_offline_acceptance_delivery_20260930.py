"""Read-only validator for one bounded real-candidate offline acceptance.

This tool only inspects committed Git objects and explicit receipt files.  It
does not start services, train a model, collect data, mutate a catalog/account,
create a ref, or grant candidate, Demo, paper, private, order, or live access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT_PATH = (
    "docs/agent_playbooks/"
    "btc_real_candidate_offline_acceptance_delivery_20260930.json"
)
CONTRACT_HASH = "1d478471f3c725a9f15208e99c25b6a0d1d6128b05a92166f48d32ced768f6ee"
TICKET = "BTC-REAL-CANDIDATE-OFFLINE-ACCEPTANCE-GOVERNANCE-20260930"
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
HANDOFF_FILE_RE = re.compile(r"[A-Za-z0-9_-]+\.json")
INVENTORY_FIELDS = frozenset({"blob", "sha256", "mode", "classification"})
FILE_REFERENCE_FIELDS = frozenset({"blob", "sha256", "mode"})
FINGERPRINT_FIELDS = frozenset({"inputs", "sha256"})
SOURCE_CLASSES = frozenset({"source", "test"})
EVIDENCE_REFERENCE_FIELDS = frozenset(
    {"logical_path", "revision", "sha256", "schema_version", "seal_sha256"}
)
ATTEMPT_FIELDS = frozenset(
    {"fit_index", "stage", "outcome", "evidence_sha256", "evidence_ref"}
)
ATTEMPT_OUTCOMES = frozenset({"passed", "failed", "crashed"})
RUN_FIELDS = frozenset(
    {
        "business_outcome",
        "business_passed",
        "official_run_count",
        "run_id",
        "decision_hours",
        "settlement_events",
        "requested_pause_after_event",
        "actual_checkpoint_after_event",
        "checkpoint_selection_rule",
        "checkpoint_selected_by_pnl",
        "checkpoint",
        "same_task_resumed",
        "run_seal",
        "ledger_evidence",
        "minute_sampling_only",
        "tick_path_verified",
        "exact_exchange_settlement_verified",
        "blockers",
        "not_run",
    }
)
REVIEW_FIELDS = frozenset(
    {
        "schema_version", "ticket_id", "phase", "decision",
        "reviewed_source_commit", "production_source_commit",
        "consumer_commit", "execution_commit", "blockers", "not_run",
        "production_preparation_inventory_sha256", "dependency_runtime",
    }
)
CONTRACT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_schema_version",
        "ticket_id",
        "governance_base_commit",
        "source_change_risk",
        "governance_change_risk",
        "temporary_deployment_profile",
        "final_deployment_profile",
        "temporary_auth_mode",
        "evidence_kind",
        "readiness_ceiling",
        "independent_integrator_required",
        "promotion_artifact_rebuild_required",
        "backend_restart_required",
        "allowed_phases",
        "source_sealed",
        "source_base_commit",
        "reviewed_source_commit",
        "max_source_file_count",
        "max_test_file_count",
        "allowed_source_paths",
        "allowed_test_paths",
        "source_inventory",
        "required_feature_implementation_paths",
        "reviewed_feature_inventory",
        "source_fingerprints",
        "runtime_feature_primitives",
        "required_dependency_version_keys",
        "required_dependency_versions",
        "required_python_version",
        "source_handoff",
        "source_handoff_identity",
        "allowed_production_preparation_paths",
        "allowed_production_preparation_prefixes",
        "allowed_post_source_paths",
        "campaign_evidence_path",
        "campaign_evidence_schema_version",
        "approved_external_artifact_names",
        "runtime_feature_primitives",
        "required_dependency_version_keys",
        "fixed_campaign",
        "allowed_business_outcomes",
        "pre_run_blocked_outcomes",
        "binding_names",
        "governance_paths",
        "review_report_paths",
        "handoff_prefixes",
        "rollback_ref",
        "required_source_checks",
        "required_deployment_checks",
        "required_false_flags",
        "temporary_runtime_required",
        "pre_run_blocked_runtime_required",
        "final_runtime_required",
        "documentation",
    }
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", *args], cwd=root, stderr=subprocess.PIPE, timeout=30
    )


def _is_commit(value: Any) -> bool:
    return isinstance(value, str) and COMMIT_RE.fullmatch(value) is not None


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _safe_path(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\\" not in value
        and ":" not in value
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


def _ancestor(root: Path, before: str, after: str) -> None:
    if not _is_commit(before) or not _is_commit(after):
        raise ValueError("commit_required")
    _git(root, "merge-base", "--is-ancestor", before, after)


def _paths(root: Path, before: str, after: str) -> set[str]:
    return set(
        _git(root, "diff", "--name-only", before, after, "--")
        .decode("utf-8")
        .splitlines()
    )


def _tree_entry(root: Path, commit: str, path: str) -> tuple[str, str]:
    raw = _git(root, "ls-tree", commit, "--", path).decode("utf-8").rstrip("\n")
    match = re.fullmatch(r"([0-9]{6}) blob ([0-9a-f]{40})\t(.+)", raw)
    if not match or match.group(3) != path:
        raise ValueError("source_tree_entry_missing:" + path)
    return match.group(1), match.group(2)


def _fingerprint(inventory: Mapping[str, Any], inputs: Sequence[str]) -> str:
    payload = [[path, inventory[path]["sha256"]] for path in sorted(inputs)]
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _load_contract(root: Path = ROOT, *, require_sealed: bool = False) -> dict[str, Any]:
    value = json.loads((root / CONTRACT_PATH).read_text(encoding="utf-8"))
    if hashlib.sha256(_canonical(value)).hexdigest() != CONTRACT_HASH:
        raise ValueError("fixed_contract_changed")
    _validate_contract_shape(value)
    if require_sealed and value["source_sealed"] is not True:
        raise ValueError("source_not_sealed")
    return value


def contract(root: Path = ROOT) -> dict[str, Any]:
    """Return a defensive copy of the one-time contract."""
    return json.loads(json.dumps(_load_contract(root)))


def _validate_contract_shape(value: Mapping[str, Any]) -> None:
    if set(value) != CONTRACT_FIELDS:
        raise ValueError("contract_fields_missing_or_unknown")
    fixed = {
        "schema_version": "btc_real_candidate_offline_acceptance_delivery_contract_v1",
        "receipt_schema_version": "btc_real_candidate_offline_acceptance_delivery_receipt_v1",
        "ticket_id": TICKET,
        "governance_base_commit": "ee42a967663d7bc306b4ac8b0d3c7d178f5b79cd",
        "source_change_risk": "demo_execution_semantics",
        "governance_change_risk": "governance_control",
        "temporary_deployment_profile": "candidate_management",
        "final_deployment_profile": "research_readonly",
        "temporary_auth_mode": "local_no_password",
        "evidence_kind": "real_candidate_offline_execution",
        "readiness_ceiling": "quality_checked",
        "independent_integrator_required": True,
        "promotion_artifact_rebuild_required": False,
        "backend_restart_required": True,
        "allowed_phases": ["source_review", "deployment_acceptance"],
        "max_source_file_count": 14,
        "max_test_file_count": 10,
        "documentation": (
            "docs/agent_playbooks/"
            "btc_real_candidate_offline_acceptance_delivery_20260930.md"
        ),
    }
    for key, expected in fixed.items():
        if value.get(key) != expected:
            raise ValueError("contract_fixed_field_mismatch:" + key)
    if value.get("source_sealed") not in (True, False):
        raise ValueError("source_sealed_not_literal_boolean")
    if value["source_sealed"] is False:
        if not (
            value.get("source_base_commit") is None
            and value.get("reviewed_source_commit") is None
            and value.get("source_inventory") == {}
            and value.get("reviewed_feature_inventory") == {}
            and value.get("source_fingerprints") is None
            and value.get("source_handoff") is None
        ):
            raise ValueError("partially_sealed_source_forbidden")
    else:
        if (
            not _is_commit(value.get("source_base_commit"))
            or not _is_commit(value.get("reviewed_source_commit"))
        ):
            raise ValueError("sealed_source_commit_invalid")
        if not isinstance(value.get("source_inventory"), dict) or not value["source_inventory"]:
            raise ValueError("sealed_source_inventory_empty")
        if not isinstance(value.get("source_fingerprints"), dict):
            raise ValueError("sealed_source_fingerprints_missing")
        if not isinstance(value.get("reviewed_feature_inventory"), dict):
            raise ValueError("sealed_feature_inventory_missing")
        if not isinstance(value.get("source_handoff"), dict):
            raise ValueError("sealed_source_handoff_missing")
    for key in (
        "required_source_checks",
        "required_deployment_checks",
        "required_false_flags",
        "allowed_business_outcomes",
        "pre_run_blocked_outcomes",
        "binding_names",
        "governance_paths",
        "allowed_source_paths",
        "allowed_test_paths",
        "required_feature_implementation_paths",
        "allowed_production_preparation_paths",
        "allowed_production_preparation_prefixes",
        "allowed_post_source_paths",
        "approved_external_artifact_names",
    ):
        items = value.get(key)
        if not isinstance(items, list) or not items or len(items) != len(set(items)):
            raise ValueError(key + "_invalid")
    for key in (
        "governance_paths", "allowed_source_paths", "allowed_test_paths",
        "required_feature_implementation_paths", "allowed_production_preparation_paths",
        "allowed_post_source_paths",
    ):
        if any(not _safe_path(path) for path in value[key]):
            raise ValueError(key + "_path_invalid")
    if len(value["allowed_source_paths"]) != value["max_source_file_count"]:
        raise ValueError("allowed_source_path_count_mismatch")
    if len(value["allowed_test_paths"]) != value["max_test_file_count"]:
        raise ValueError("allowed_test_path_count_mismatch")
    if not set(value["required_feature_implementation_paths"]).issubset(
        set(value["allowed_source_paths"])
    ):
        raise ValueError("feature_implementation_paths_not_source_allowlisted")
    prefixes = value["allowed_production_preparation_prefixes"]
    if any(
        not isinstance(prefix, str)
        or not prefix.endswith("/")
        or not _safe_path(prefix.rstrip("/"))
        for prefix in prefixes
    ):
        raise ValueError("allowed_production_preparation_prefixes_invalid")
    if value["runtime_feature_primitives"] != [
        "momentum_20d", "momentum_60d", "momentum_120d", "volatility_20d",
        "volatility_60d", "liquidity_20d", "reversal_1d", "volume_20d",
    ]:
        raise ValueError("runtime_feature_primitives_changed")
    if value["required_dependency_version_keys"] != ["numpy", "pandas", "lightgbm", "qlib"]:
        raise ValueError("dependency_version_keys_changed")
    if value.get("required_dependency_versions") != {
        "numpy": "2.4.6", "pandas": "3.0.4", "lightgbm": "4.7.0", "qlib": "0.9.7"
    }:
        raise ValueError("dependency_versions_changed")
    if value.get("required_python_version") != "3.11.15":
        raise ValueError("python_version_changed")
    identity = value.get("source_handoff_identity")
    if (
        not isinstance(identity, dict)
        or set(identity) != {"ticket_id", "path_prefix", "producer_role", "event_type", "domain"}
        or not identity["path_prefix"].endswith("/")
        or not _safe_path(identity["path_prefix"].rstrip("/"))
    ):
        raise ValueError("source_handoff_identity_invalid")
    if not _safe_path(value.get("campaign_evidence_path")):
        raise ValueError("campaign_evidence_path_invalid")
    if value["campaign_evidence_path"] not in value["allowed_post_source_paths"]:
        raise ValueError("campaign_evidence_path_not_allowed")
    if value.get("campaign_evidence_schema_version") != "btc_real_candidate_offline_campaign_evidence_v1":
        raise ValueError("campaign_evidence_schema_changed")
    reports = value.get("review_report_paths")
    if (
        not isinstance(reports, dict)
        or set(reports) != {
            "source_review", "integration_review", "deployment_acceptance", "blocked_deployment"
        }
        or any(not _safe_path(path) for path in reports.values())
    ):
        raise ValueError("review_report_paths_invalid")
    prefixes = value.get("handoff_prefixes")
    if (
        not isinstance(prefixes, list)
        or len(prefixes) != 2
        or any(not prefix.endswith("/") or not _safe_path(prefix.rstrip("/")) for prefix in prefixes)
    ):
        raise ValueError("handoff_prefixes_invalid")
    if not isinstance(value.get("fixed_campaign"), dict):
        raise ValueError("fixed_campaign_invalid")
    if value["fixed_campaign"].get("max_actual_fits") != 5:
        raise ValueError("fixed_campaign_fit_budget_changed")
    if value["fixed_campaign"].get("decision_hours") != 48:
        raise ValueError("fixed_campaign_window_changed")
    if value["fixed_campaign"].get("settlement_events") != 6:
        raise ValueError("fixed_campaign_settlement_count_changed")
    if value["fixed_campaign"].get("official_run_count") != 1:
        raise ValueError("fixed_campaign_run_count_changed")
    temporary_runtime_keys = {
        "stage", "profile", "auth_mode", "loopback_only",
        "candidate_management_enabled", "management_write_enabled",
        "offline_task_enabled", "offline_worker_enabled", "read_only",
    }
    restored_runtime_keys = {
        "stage", "profile", "loopback_only", "candidate_management_enabled",
        "management_write_enabled", "offline_task_enabled", "offline_worker_enabled",
        "read_only", "auth_mode_changed_for_restore", "password_step_added",
    }
    if (
        not isinstance(value.get("temporary_runtime_required"), dict)
        or set(value["temporary_runtime_required"]) != temporary_runtime_keys
    ):
        raise ValueError("temporary_runtime_required_invalid")
    for name in ("pre_run_blocked_runtime_required", "final_runtime_required"):
        if not isinstance(value.get(name), dict) or set(value[name]) != restored_runtime_keys:
            raise ValueError(name + "_invalid")


def _verify_reviewed_source(root: Path, value: Mapping[str, Any]) -> None:
    if value.get("source_sealed") is not True:
        raise ValueError("source_not_sealed")
    reviewed = value["reviewed_source_commit"]
    baseline = value["source_base_commit"]
    _ancestor(root, baseline, reviewed)
    inventory = value["source_inventory"]
    if set(inventory) != _paths(root, baseline, reviewed):
        raise ValueError("source_touch_set_mismatch")
    allowed_source = set(value["allowed_source_paths"])
    allowed_tests = set(value["allowed_test_paths"])
    if not set(inventory).issubset(allowed_source | allowed_tests):
        raise ValueError("source_outside_ticket_allowlist")
    source_count = 0
    test_count = 0
    for path, entry in inventory.items():
        if not _safe_path(path) or not isinstance(entry, dict) or set(entry) != INVENTORY_FIELDS:
            raise ValueError("source_inventory_entry_invalid:" + str(path))
        classification = entry["classification"]
        if classification not in SOURCE_CLASSES:
            raise ValueError("source_classification_invalid:" + path)
        if classification == "source" and path not in allowed_source:
            raise ValueError("source_classification_path_mismatch:" + path)
        if classification == "test" and path not in allowed_tests:
            raise ValueError("test_classification_path_mismatch:" + path)
        source_count += classification == "source"
        test_count += classification == "test"
        if (
            not _is_commit(entry["blob"])
            or not _is_hash(entry["sha256"])
            or entry["mode"] not in ("100644", "100755")
        ):
            raise ValueError("source_inventory_value_invalid:" + path)
        mode, blob = _tree_entry(root, reviewed, path)
        if mode != entry["mode"] or blob != entry["blob"]:
            raise ValueError("source_blob_or_mode_mismatch:" + path)
        raw = _git(root, "show", reviewed + ":" + path)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("source_sha256_mismatch:" + path)
    if source_count > value["max_source_file_count"] or test_count > value["max_test_file_count"]:
        raise ValueError("source_classification_count_exceeded")
    feature_inventory = value["reviewed_feature_inventory"]
    required_feature_paths = value["required_feature_implementation_paths"]
    if not isinstance(feature_inventory, dict) or set(feature_inventory) != set(required_feature_paths):
        raise ValueError("reviewed_feature_inventory_mismatch")
    for path, entry in feature_inventory.items():
        if (
            not isinstance(entry, dict)
            or set(entry) != FILE_REFERENCE_FIELDS
            or not _is_commit(entry["blob"])
            or not _is_hash(entry["sha256"])
            or entry["mode"] not in ("100644", "100755")
        ):
            raise ValueError("reviewed_feature_entry_invalid:" + path)
        mode, blob = _tree_entry(root, reviewed, path)
        if mode != entry["mode"] or blob != entry["blob"]:
            raise ValueError("reviewed_feature_blob_or_mode_mismatch:" + path)
        if hashlib.sha256(_git(root, "show", reviewed + ":" + path)).hexdigest() != entry["sha256"]:
            raise ValueError("reviewed_feature_sha256_mismatch:" + path)


def _production_preparation_allowed(path: str, value: Mapping[str, Any]) -> bool:
    return path in value["allowed_production_preparation_paths"] or any(
        path.startswith(prefix)
        and HANDOFF_FILE_RE.fullmatch(path[len(prefix):]) is not None
        for prefix in value["allowed_production_preparation_prefixes"]
    )


def _verify_production_source(
    root: Path,
    value: Mapping[str, Any],
    production: str,
    preparation_inventory: Any,
) -> None:
    reviewed = value["reviewed_source_commit"]
    _ancestor(root, reviewed, production)
    preparation_paths = _paths(root, reviewed, production)
    if any(not _production_preparation_allowed(path, value) for path in preparation_paths):
        raise ValueError("production_preparation_path_not_allowed")
    if not isinstance(preparation_inventory, dict) or set(preparation_inventory) != preparation_paths:
        raise ValueError("production_preparation_inventory_mismatch")
    for path, entry in preparation_inventory.items():
        if (
            not isinstance(entry, dict)
            or set(entry) != FILE_REFERENCE_FIELDS
            or not _is_commit(entry["blob"])
            or not _is_hash(entry["sha256"])
            or entry["mode"] not in ("100644", "100755")
        ):
            raise ValueError("production_preparation_entry_invalid:" + path)
        mode, blob = _tree_entry(root, production, path)
        if mode != entry["mode"] or blob != entry["blob"]:
            raise ValueError("production_preparation_blob_or_mode_mismatch:" + path)
        if hashlib.sha256(_git(root, "show", production + ":" + path)).hexdigest() != entry["sha256"]:
            raise ValueError("production_preparation_sha256_mismatch:" + path)
    for inventory_name in ("source_inventory", "reviewed_feature_inventory"):
        for path, entry in value[inventory_name].items():
            mode, blob = _tree_entry(root, production, path)
            if mode != entry["mode"] or blob != entry["blob"]:
                raise ValueError("reviewed_source_changed_at_production:" + path)


def _verify_frozen_source(root: Path, value: Mapping[str, Any]) -> None:
    _verify_reviewed_source(root, value)
    inventory = value["source_inventory"]
    fingerprints = value["source_fingerprints"]
    if not isinstance(fingerprints, dict) or set(fingerprints) != {
        "feature_runtime", "dependency_runtime", "combined"
    }:
        raise ValueError("source_fingerprints_invalid")
    feature = fingerprints["feature_runtime"]
    if not isinstance(feature, dict) or set(feature) != {"primitive_names", "inputs", "sha256"}:
        raise ValueError("source_fingerprint_fields_invalid:feature_runtime")
    if feature["primitive_names"] != value["runtime_feature_primitives"]:
        raise ValueError("feature_primitive_names_mismatch")
    feature_inputs = feature["inputs"]
    if (
        not isinstance(feature_inputs, list)
        or not feature_inputs
        or len(feature_inputs) != len(set(feature_inputs))
        or feature_inputs != value["required_feature_implementation_paths"]
        or not _is_hash(feature["sha256"])
    ):
        raise ValueError("source_fingerprint_inputs_invalid:feature_runtime")
    feature_payload = {
        "primitive_names": feature["primitive_names"],
        "files": [
            [path, value["reviewed_feature_inventory"][path]["sha256"]]
            for path in sorted(feature_inputs)
        ],
    }
    if hashlib.sha256(_canonical(feature_payload)).hexdigest() != feature["sha256"]:
        raise ValueError("source_fingerprint_mismatch:feature_runtime")
    dependency = fingerprints["dependency_runtime"]
    if not isinstance(dependency, dict) or set(dependency) != {"versions", "sha256"}:
        raise ValueError("source_fingerprint_fields_invalid:dependency_runtime")
    versions = dependency["versions"]
    if (
        not isinstance(versions, dict)
        or list(versions) != value["required_dependency_version_keys"]
        or versions != value["required_dependency_versions"]
        or not _is_hash(dependency["sha256"])
    ):
        raise ValueError("dependency_versions_invalid")
    if hashlib.sha256(_canonical(versions)).hexdigest() != dependency["sha256"]:
        raise ValueError("source_fingerprint_mismatch:dependency_runtime")
    combined = fingerprints["combined"]
    if not isinstance(combined, dict) or set(combined) != FINGERPRINT_FIELDS:
        raise ValueError("source_fingerprint_fields_invalid:combined")
    inputs = combined["inputs"]
    if (
        not isinstance(inputs, list)
        or not inputs
        or len(inputs) != len(set(inputs))
        or any(path not in inventory for path in inputs)
        or not _is_hash(combined["sha256"])
    ):
        raise ValueError("source_fingerprint_inputs_invalid:combined")
    if _fingerprint(inventory, inputs) != combined["sha256"]:
        raise ValueError("source_fingerprint_mismatch:combined")
    if set(fingerprints["combined"]["inputs"]) != set(inventory):
        raise ValueError("combined_fingerprint_not_full_inventory")


def _verify_source_handoff(root: Path, value: Mapping[str, Any]) -> None:
    reference = value["source_handoff"]
    required = {
        "path", "commit", "sha256", "schema_version", "event_id", "ticket_id",
        "deliverable_commit", "readiness_classes", "blockers",
    }
    if not isinstance(reference, dict) or set(reference) != required:
        raise ValueError("source_handoff_reference_fields_invalid")
    if (
        not _safe_path(reference["path"])
        or not reference["path"].startswith(value["source_handoff_identity"]["path_prefix"])
        or HANDOFF_FILE_RE.fullmatch(
            reference["path"][len(value["source_handoff_identity"]["path_prefix"]):]
        ) is None
        or not _is_commit(reference["commit"])
        or not _is_commit(reference["deliverable_commit"])
        or not _is_hash(reference["sha256"])
        or reference["deliverable_commit"] != value["reviewed_source_commit"]
    ):
        raise ValueError("source_handoff_reference_invalid")
    _ancestor(root, value["reviewed_source_commit"], reference["commit"])
    raw = _git(root, "show", reference["commit"] + ":" + reference["path"])
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("source_handoff_digest_mismatch")
    payload = json.loads(raw)
    from tools.agent_governance.handoff import validate_handoff_against_git

    errors = validate_handoff_against_git(payload, repo_root=root)
    if errors:
        raise ValueError("source_handoff_invalid:" + ";".join(errors))
    for key in ("schema_version", "event_id", "ticket_id", "deliverable_commit", "blockers"):
        if payload.get(key) != reference[key]:
            raise ValueError("source_handoff_" + key + "_mismatch")
    readiness = sorted({item["readiness_class"] for item in payload["deliverables"]})
    if readiness != reference["readiness_classes"]:
        raise ValueError("source_handoff_readiness_mismatch")
    if payload.get("promotion_eligible") is not False:
        raise ValueError("source_handoff_promotion_eligible_must_be_false")
    identity = value["source_handoff_identity"]
    for key in ("ticket_id", "producer_role", "event_type", "domain"):
        if payload.get(key) != identity[key]:
            raise ValueError("source_handoff_identity_mismatch:" + key)


def frozen_source(root: Path = ROOT) -> None:
    value = _load_contract(root, require_sealed=True)
    _verify_frozen_source(root, value)
    _verify_source_handoff(root, value)


def _verify_source_fidelity(root: Path, value: Mapping[str, Any], target: str) -> None:
    source = value["reviewed_source_commit"]
    _ancestor(root, source, target)
    for path, entry in value["source_inventory"].items():
        mode, blob = _tree_entry(root, target, path)
        if mode != entry["mode"] or blob != entry["blob"]:
            raise ValueError("reviewed_source_changed:" + path)
        if hashlib.sha256(_git(root, "show", target + ":" + path)).hexdigest() != entry["sha256"]:
            raise ValueError("reviewed_source_sha256_changed:" + path)
    for path, entry in value["reviewed_feature_inventory"].items():
        mode, blob = _tree_entry(root, target, path)
        if mode != entry["mode"] or blob != entry["blob"]:
            raise ValueError("reviewed_feature_changed:" + path)
    for name, item in value["source_fingerprints"].items():
        if name == "dependency_runtime":
            continue
        inputs = item["inputs"]
        inventory = (
            value["reviewed_feature_inventory"]
            if name == "feature_runtime"
            else value["source_inventory"]
        )
        target_inventory = {
            path: {**inventory[path], "sha256": hashlib.sha256(
                _git(root, "show", target + ":" + path)
            ).hexdigest()}
            for path in inputs
        }
        if name == "feature_runtime":
            payload = {
                "primitive_names": item["primitive_names"],
                "files": [[path, target_inventory[path]["sha256"]] for path in sorted(inputs)],
            }
            actual = hashlib.sha256(_canonical(payload)).hexdigest()
        else:
            actual = _fingerprint(target_inventory, inputs)
        if actual != item["sha256"]:
            raise ValueError("deployment_fingerprint_changed:" + name)


def _handoff_delta(path: str, value: Mapping[str, Any]) -> bool:
    return any(
        path.startswith(prefix)
        and HANDOFF_FILE_RE.fullmatch(path[len(prefix):]) is not None
        for prefix in value["handoff_prefixes"]
    )


def _post_source_handoff_delta(path: str, value: Mapping[str, Any]) -> bool:
    """Allow only the ticket-owned handoff namespaces after source freeze."""

    return _handoff_delta(path, value) or any(
        path.startswith(prefix)
        and HANDOFF_FILE_RE.fullmatch(path[len(prefix):]) is not None
        for prefix in value["allowed_production_preparation_prefixes"]
    )


def allowed_delta(path: str, value: Mapping[str, Any] | None = None) -> bool:
    if value is None:
        value = _load_contract(ROOT)
    if not _safe_path(path):
        return False
    source_handoff = value.get("source_handoff")
    return (
        path in value["governance_paths"]
        or path in value["review_report_paths"].values()
        or path in value["allowed_production_preparation_paths"]
        or _production_preparation_allowed(path, value)
        or path in value["allowed_post_source_paths"]
        or _handoff_delta(path, value)
        or (isinstance(source_handoff, dict) and path == source_handoff.get("path"))
    )


def _report(root: Path, reference: Any, expected_path: str) -> str:
    if (
        not isinstance(reference, dict)
        or set(reference) != {"commit", "path", "sha256"}
        or reference.get("path") != expected_path
        or not _is_commit(reference.get("commit"))
        or not _is_hash(reference.get("sha256"))
    ):
        raise ValueError("report_reference_invalid:" + expected_path)
    raw = _git(root, "show", reference["commit"] + ":" + expected_path)
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("report_digest_mismatch:" + expected_path)
    return reference["commit"]


def _review_report(
    root: Path,
    reference: Any,
    expected_path: str,
    *,
    phase: str,
    decision: str,
    reviewed_source_commit: str,
    production_source_commit: str,
    production_preparation_inventory: Mapping[str, Any],
    consumer_commit: str | None,
    execution_commit: str | None,
) -> str:
    commit = _report(root, reference, expected_path)
    payload = json.loads(_git(root, "show", commit + ":" + expected_path))
    if not isinstance(payload, dict) or set(payload) != REVIEW_FIELDS:
        raise ValueError("review_report_fields_invalid:" + phase)
    expected = {
        "schema_version": "btc_real_candidate_offline_review_v1",
        "ticket_id": TICKET,
        "phase": phase,
        "decision": decision,
        "reviewed_source_commit": reviewed_source_commit,
        "production_source_commit": production_source_commit,
        "consumer_commit": consumer_commit,
        "execution_commit": execution_commit,
        "production_preparation_inventory_sha256": hashlib.sha256(
            _canonical(production_preparation_inventory)
        ).hexdigest(),
        "dependency_runtime": {
            "interpreter_identity": "canonical_repo_venv_py311",
            "python_version": "3.11.15",
            "versions": {
                "numpy": "2.4.6", "pandas": "3.0.4",
                "lightgbm": "4.7.0", "qlib": "0.9.7",
            },
        },
    }
    for key, expected_value in expected.items():
        if payload.get(key) != expected_value:
            raise ValueError("review_report_mismatch:" + phase + ":" + key)
    for key in ("blockers", "not_run"):
        if not isinstance(payload[key], list) or any(not isinstance(item, str) or not item for item in payload[key]):
            raise ValueError("review_report_list_invalid:" + phase + ":" + key)
    if decision == "approved" and phase == "deployment_acceptance" and (
        payload["blockers"] or payload["not_run"]
    ):
        raise ValueError("approved_deployment_report_has_gaps")
    if decision == "blocked" and not payload["blockers"]:
        raise ValueError("blocked_report_has_no_blockers")
    return commit


def _valid_evidence_reference(reference: Any) -> bool:
    return (
        isinstance(reference, dict)
        and set(reference) == EVIDENCE_REFERENCE_FIELDS
        and _safe_path(reference.get("logical_path"))
        and isinstance(reference.get("revision"), str)
        and bool(reference["revision"])
        and _is_hash(reference.get("sha256"))
        and isinstance(reference.get("schema_version"), str)
        and bool(reference["schema_version"])
        and _is_hash(reference.get("seal_sha256"))
    )


def _campaign_evidence(
    root: Path,
    reference: Any,
    receipt: Mapping[str, Any],
    value: Mapping[str, Any],
) -> str:
    required_ref = {"commit", "path", "sha256", "schema_version"}
    if (
        not isinstance(reference, dict)
        or set(reference) != required_ref
        or reference.get("path") != value["campaign_evidence_path"]
        or reference.get("schema_version") != value["campaign_evidence_schema_version"]
        or not _is_commit(reference.get("commit"))
        or not _is_hash(reference.get("sha256"))
    ):
        raise ValueError("campaign_evidence_reference_invalid")
    raw = _git(root, "show", reference["commit"] + ":" + reference["path"])
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("campaign_evidence_digest_mismatch")
    payload = json.loads(raw)
    fields = {
        "schema_version", "ticket_id", "reviewed_source_commit",
        "production_source_commit", "consumer_commit", "execution_commit",
        "business_outcome", "campaign", "bindings", "run_evidence",
        "temporary_runtime", "final_runtime", "safety_flags", "checks",
        "source_fingerprints", "external_artifacts", "missing_external_artifacts",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("campaign_evidence_fields_invalid")
    direct = {
        "schema_version": value["campaign_evidence_schema_version"],
        "ticket_id": TICKET,
        "reviewed_source_commit": value["reviewed_source_commit"],
        "production_source_commit": receipt["production_source_commit"],
        "consumer_commit": receipt["consumer_commit"],
        "execution_commit": receipt["execution_commit"],
        "business_outcome": receipt["run_evidence"]["business_outcome"],
        "campaign": receipt["campaign"],
        "bindings": receipt["bindings"],
        "run_evidence": receipt["run_evidence"],
        "temporary_runtime": receipt["temporary_runtime"],
        "final_runtime": receipt["final_runtime"],
        "safety_flags": receipt["safety_flags"],
        "checks": receipt["checks"],
        "source_fingerprints": value["source_fingerprints"],
    }
    for key, expected in direct.items():
        if payload.get(key) != expected:
            raise ValueError("campaign_evidence_mismatch:" + key)
    artifacts = payload["external_artifacts"]
    allowed = set(value["approved_external_artifact_names"])
    missing = payload["missing_external_artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != allowed:
        raise ValueError("campaign_external_artifacts_fields_invalid")
    if not isinstance(missing, list) or len(missing) != len(set(missing)) or any(name not in allowed for name in missing):
        raise ValueError("campaign_missing_external_artifacts_invalid")
    actual_missing = []
    for name, item in artifacts.items():
        if item is None:
            actual_missing.append(name)
            continue
        if (
            not _valid_evidence_reference(item)
            or Path(item["logical_path"]).name != name
        ):
            raise ValueError("campaign_external_artifact_invalid:" + name)
    if sorted(actual_missing) != sorted(missing):
        raise ValueError("campaign_missing_external_artifacts_mismatch")
    if receipt["run_evidence"]["business_outcome"] == "passed" and actual_missing:
        raise ValueError("passed_campaign_external_artifact_missing")
    fit_budget = artifacts.get("fit_budget.json")
    for attempt in receipt["campaign"]["attempts"]:
        if fit_budget is None or attempt.get("evidence_ref") != fit_budget:
            raise ValueError("campaign_fit_budget_reference_mismatch")
    run_seal = receipt["run_evidence"].get("run_seal")
    if run_seal is not None and run_seal != artifacts.get("run_seal.json"):
        raise ValueError("campaign_run_seal_reference_mismatch")
    return reference["commit"]


def _only_allowed_delta(root: Path, before: str, after: str, value: Mapping[str, Any]) -> None:
    for path in _paths(root, before, after):
        if not allowed_delta(path, value):
            raise ValueError("phase_delta_not_allowed:" + path)


def _only_evidence_delta(root: Path, before: str, after: str, value: Mapping[str, Any]) -> None:
    allowed = set(value["allowed_post_source_paths"]) | set(value["review_report_paths"].values())
    for path in _paths(root, before, after):
        if path not in allowed and not _post_source_handoff_delta(path, value):
            raise ValueError("evidence_delta_not_allowed:" + path)


def _verify_evidence_dag(
    root: Path,
    *,
    production_source_commit: str,
    source_review_commit: str,
    consumer_commit: str | None,
    post_consumer_evidence_commits: Sequence[str],
) -> None:
    """Verify the constructible R->S->Q and S->F->A evidence topology."""
    _ancestor(root, production_source_commit, source_review_commit)
    if consumer_commit is None:
        return
    _ancestor(root, production_source_commit, consumer_commit)
    for evidence_commit in post_consumer_evidence_commits:
        _ancestor(root, consumer_commit, evidence_commit)


def _validate_bindings(receipt: Mapping[str, Any], value: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    bindings = receipt.get("bindings")
    names = set(value["binding_names"])
    if not isinstance(bindings, dict) or set(bindings) != names:
        return ["bindings_missing_or_unknown"]
    missing = receipt.get("missing_bindings")
    if not isinstance(missing, list) or len(missing) != len(set(missing)) or any(name not in names for name in missing):
        return ["missing_bindings_invalid"]
    actual_missing = []
    for name, binding in bindings.items():
        if binding is None:
            actual_missing.append(name)
            continue
        expected_fields = (
            {"version", "sha256", "source_commit", "evidence_ref"}
            if name == "candidate"
            else {"version", "sha256", "evidence_ref"}
        )
        if (
            not isinstance(binding, dict)
            or set(binding) != expected_fields
            or not isinstance(binding["version"], str)
            or not binding["version"]
            or not _is_hash(binding["sha256"])
            or not _valid_evidence_reference(binding["evidence_ref"])
            or binding["evidence_ref"]["schema_version"] != "candidate_offline_job_identity_v1"
            or Path(binding["evidence_ref"]["logical_path"]).name != "candidate_offline_job_identity.json"
        ):
            problems.append("binding_invalid:" + name)
        elif name == "candidate" and binding["source_commit"] != receipt["production_source_commit"]:
            problems.append("candidate_source_commit_mismatch")
    if sorted(missing) != sorted(actual_missing):
        problems.append("missing_bindings_mismatch")
    identity_references = {
        json.dumps(binding["evidence_ref"], sort_keys=True)
        for binding in bindings.values()
        if isinstance(binding, dict) and _valid_evidence_reference(binding.get("evidence_ref"))
    }
    if len(identity_references) > 1:
        problems.append("binding_identity_reference_mismatch")
    outcome = receipt.get("run_evidence", {}).get("business_outcome")
    if outcome == "passed" and actual_missing:
        problems.append("passed_binding_missing")
    return problems


def _validate_campaign(receipt: Mapping[str, Any], value: Mapping[str, Any]) -> list[str]:
    campaign = receipt.get("campaign")
    if not isinstance(campaign, dict) or set(campaign) != {
        "campaign_id", "attempts", "actual_fit_count", "screening_passed", "calibration_passed"
    }:
        return ["campaign_fields_invalid"]
    problems: list[str] = []
    fixed = value["fixed_campaign"]
    if campaign["campaign_id"] != fixed["campaign_id"]:
        problems.append("campaign_id_mismatch")
    attempts = campaign["attempts"]
    count = campaign["actual_fit_count"]
    if (
        not isinstance(attempts, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(attempts)
    ):
        return problems + ["fit_count_mismatch"]
    if count > fixed["max_actual_fits"]:
        problems.append("fit_budget_exceeded")
    for index, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict) or set(attempt) != ATTEMPT_FIELDS:
            problems.append("fit_attempt_fields_invalid")
            continue
        if (
            attempt["fit_index"] != index
            or attempt["stage"] not in ("screening_fold", "final_audit")
            or attempt["outcome"] not in ATTEMPT_OUTCOMES
            or not _is_hash(attempt["evidence_sha256"])
            or not _valid_evidence_reference(attempt["evidence_ref"])
            or attempt["evidence_ref"]["sha256"] != attempt["evidence_sha256"]
            or Path(attempt["evidence_ref"]["logical_path"]).name != "fit_budget.json"
            or attempt["evidence_ref"]["schema_version"] != "alpha_factory_fit_budget_v1"
        ):
            problems.append("fit_attempt_invalid")
    if any(item.get("stage") == "final_audit" for item in attempts[:-1] if isinstance(item, dict)):
        problems.append("final_audit_not_last")
    outcome = receipt.get("run_evidence", {}).get("business_outcome")
    screening = campaign["screening_passed"]
    calibration = campaign["calibration_passed"]
    if not isinstance(screening, bool) or not isinstance(calibration, bool):
        problems.append("campaign_pass_flags_not_boolean")
    elif outcome == "passed":
        if (
            count != 5
            or not screening
            or not calibration
            or attempts[-1].get("stage") != "final_audit"
            or any(item.get("outcome") != "passed" for item in attempts if isinstance(item, dict))
        ):
            problems.append("passed_campaign_incomplete")
    elif outcome == "blocked_screening":
        if screening or calibration or count > 4 or any(
            item.get("stage") == "final_audit" for item in attempts if isinstance(item, dict)
        ):
            problems.append("blocked_screening_campaign_invalid")
    elif outcome == "blocked_calibration":
        if not screening or calibration or count != 5 or attempts[-1].get("stage") != "final_audit":
            problems.append("blocked_calibration_campaign_invalid")
    return problems


def _validate_run(receipt: Mapping[str, Any], value: Mapping[str, Any]) -> list[str]:
    run = receipt.get("run_evidence")
    if not isinstance(run, dict) or set(run) != RUN_FIELDS:
        return ["run_evidence_fields_invalid"]
    problems: list[str] = []
    outcome = run["business_outcome"]
    if outcome not in value["allowed_business_outcomes"]:
        problems.append("business_outcome_invalid")
        return problems
    if not isinstance(run["business_passed"], bool) or run["business_passed"] is not (outcome == "passed"):
        problems.append("business_passed_mismatch")
    numeric_limits = {
        "official_run_count": value["fixed_campaign"]["official_run_count"],
        "decision_hours": value["fixed_campaign"]["decision_hours"],
        "settlement_events": value["fixed_campaign"]["settlement_events"],
    }
    for key, upper in numeric_limits.items():
        item = run[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0 or item > upper:
            problems.append(key + "_out_of_bounds")
    if run["official_run_count"] == 0 and run["run_id"] is not None:
        problems.append("run_id_without_official_run")
    if run["official_run_count"] == 1 and (not isinstance(run["run_id"], str) or not run["run_id"]):
        problems.append("official_run_id_missing")
    checkpoint = run["checkpoint"]
    actual_checkpoint = run["actual_checkpoint_after_event"]
    if checkpoint is None:
        if actual_checkpoint is not None or run["same_task_resumed"] is not False:
            problems.append("checkpoint_resume_pair_invalid")
    else:
        if (
            not _valid_evidence_reference(checkpoint)
            or isinstance(actual_checkpoint, bool)
            or not isinstance(actual_checkpoint, int)
            or actual_checkpoint <= 0
            or actual_checkpoint >= value["fixed_campaign"]["decision_hours"]
            or run["same_task_resumed"] is not True
        ):
            problems.append("checkpoint_resume_pair_invalid")
    for key in ("blockers", "not_run"):
        if not isinstance(run[key], list) or any(not isinstance(item, str) or not item for item in run[key]):
            problems.append(key + "_invalid")
    if run["minute_sampling_only"] is not True:
        problems.append("minute_sampling_disclosure_missing")
    if run["tick_path_verified"] is not False:
        problems.append("tick_path_must_remain_unverified")
    if run["exact_exchange_settlement_verified"] is not False:
        problems.append("exchange_settlement_must_remain_unverified")
    if run["requested_pause_after_event"] != value["fixed_campaign"]["requested_pause_after_event"]:
        problems.append("requested_pause_target_mismatch")
    if run["checkpoint_selected_by_pnl"] is not False:
        problems.append("checkpoint_must_not_be_selected_by_pnl")
    if run["checkpoint_selection_rule"] != "first_safe_boundary_at_or_after_requested_event":
        problems.append("checkpoint_selection_rule_mismatch")
    if outcome == "passed":
        fixed = value["fixed_campaign"]
        expected = {
            "official_run_count": fixed["official_run_count"],
            "decision_hours": fixed["decision_hours"],
            "settlement_events": fixed["settlement_events"],
            "requested_pause_after_event": fixed["requested_pause_after_event"],
            "same_task_resumed": True,
        }
        for key, expected_value in expected.items():
            if run[key] != expected_value:
                problems.append(key + "_mismatch")
        if not isinstance(run["run_id"], str) or not run["run_id"]:
            problems.append("run_id_missing")
        actual_checkpoint = run["actual_checkpoint_after_event"]
        if (
            isinstance(actual_checkpoint, bool)
            or not isinstance(actual_checkpoint, int)
            or actual_checkpoint < fixed["requested_pause_after_event"]
            or actual_checkpoint >= fixed["decision_hours"]
        ):
            problems.append("actual_checkpoint_not_safe_interior_boundary")
        if (
            not _valid_evidence_reference(checkpoint)
        ):
            problems.append("checkpoint_invalid")
        if run["blockers"] or run["not_run"]:
            problems.append("passed_run_has_blockers_or_not_run")
        if not _valid_evidence_reference(run["run_seal"]):
            problems.append("run_seal_reference_invalid")
        if not _valid_evidence_reference(run["ledger_evidence"]):
            problems.append("ledger_evidence_reference_invalid")
    else:
        if not run["blockers"]:
            problems.append("blocked_run_requires_blockers")
        if outcome in value["pre_run_blocked_outcomes"]:
            if (
                run["official_run_count"] != 0
                or run["run_id"] is not None
                or run["checkpoint"] is not None
                or run["actual_checkpoint_after_event"] is not None
            ):
                problems.append("pre_run_blocker_claims_run")
        if run["official_run_count"] == 0 and (
            run["run_seal"] is not None or run["ledger_evidence"] is not None
        ):
            problems.append("run_reference_without_official_run")
    return problems


def _validate_runtime(receipt: Mapping[str, Any], value: Mapping[str, Any]) -> list[str]:
    outcome = receipt.get("run_evidence", {}).get("business_outcome")
    expected_temporary = (
        value["pre_run_blocked_runtime_required"]
        if outcome in value["pre_run_blocked_outcomes"]
        else value["temporary_runtime_required"]
    )
    problems = []

    def restored_matches(actual: Any, expected: Mapping[str, Any]) -> bool:
        return (
            isinstance(actual, dict)
            and set(actual) == set(expected) | {"auth_mode"}
            and all(actual.get(key) == expected_value for key, expected_value in expected.items())
            and actual.get("auth_mode") in ("key", "local_no_password")
        )

    temporary = receipt.get("temporary_runtime")
    if outcome in value["pre_run_blocked_outcomes"]:
        if not restored_matches(temporary, expected_temporary):
            problems.append("temporary_runtime_mismatch")
    elif temporary != expected_temporary:
        problems.append("temporary_runtime_mismatch")
    if not restored_matches(receipt.get("final_runtime"), value["final_runtime_required"]):
        problems.append("final_runtime_mismatch")
    return problems


def _verify_receipt_evidence(root: Path, receipt: Mapping[str, Any], value: Mapping[str, Any]) -> None:
    _verify_frozen_source(root, value)
    _verify_source_handoff(root, value)
    governance = receipt["governance_commit"]
    source_review_commit = receipt["reviewed_commit"]
    production = receipt["production_source_commit"]
    preparation_inventory = receipt["production_preparation_inventory"]
    _ancestor(root, value["governance_base_commit"], governance)
    for path in _paths(root, value["governance_base_commit"], governance):
        if path not in value["governance_paths"] and not _handoff_delta(path, value):
            raise ValueError("governance_contains_unrelated_delta:" + path)
    _verify_production_source(root, value, production, preparation_inventory)
    _ancestor(root, governance, production)
    _ancestor(root, value["source_handoff"]["commit"], production)
    _verify_evidence_dag(
        root,
        production_source_commit=production,
        source_review_commit=source_review_commit,
        consumer_commit=None,
        post_consumer_evidence_commits=[],
    )
    source_review_report_commit = _review_report(
        root,
        receipt["source_review"],
        value["review_report_paths"]["source_review"],
        phase="source_review",
        decision="approved",
        reviewed_source_commit=value["reviewed_source_commit"],
        production_source_commit=production,
        production_preparation_inventory=preparation_inventory,
        consumer_commit=None,
        execution_commit=None,
    )
    if source_review_report_commit != source_review_commit:
        raise ValueError("source_review_commit_must_equal_reviewed_commit")
    _verify_source_fidelity(root, value, source_review_commit)
    _only_evidence_delta(root, production, source_review_commit, value)
    if receipt["phase"] == "source_review":
        return
    outcome = receipt["run_evidence"]["business_outcome"]
    campaign_commit = _campaign_evidence(
        root, receipt["campaign_evidence"], receipt, value
    )
    if outcome in value["pre_run_blocked_outcomes"]:
        _ancestor(root, source_review_commit, campaign_commit)
        _only_evidence_delta(root, source_review_commit, campaign_commit, value)
        blocked = _review_report(
            root,
            receipt["blocked_report"],
            value["review_report_paths"]["blocked_deployment"],
            phase="deployment_acceptance",
            decision="blocked",
            reviewed_source_commit=value["reviewed_source_commit"],
            production_source_commit=production,
            production_preparation_inventory=preparation_inventory,
            consumer_commit=None,
            execution_commit=None,
        )
        _ancestor(root, source_review_commit, blocked)
        _only_evidence_delta(root, source_review_commit, blocked, value)
        return
    consumer = receipt["consumer_commit"]
    if consumer != receipt["execution_commit"]:
        raise ValueError("consumer_execution_commit_mismatch")
    _verify_evidence_dag(
        root,
        production_source_commit=production,
        source_review_commit=source_review_commit,
        consumer_commit=consumer,
        post_consumer_evidence_commits=[campaign_commit],
    )
    _only_evidence_delta(root, production, consumer, value)
    _verify_source_fidelity(root, value, consumer)
    _only_evidence_delta(root, consumer, campaign_commit, value)
    integration = _review_report(
        root,
        receipt["integration_review"],
        value["review_report_paths"]["integration_review"],
        phase="integration_review",
        decision="approved",
        reviewed_source_commit=value["reviewed_source_commit"],
        production_source_commit=production,
        production_preparation_inventory=preparation_inventory,
        consumer_commit=consumer,
        execution_commit=consumer,
    )
    _ancestor(root, consumer, integration)
    _only_evidence_delta(root, consumer, integration, value)
    acceptance_decision = "approved" if outcome == "passed" else "blocked"
    acceptance = _review_report(
        root,
        receipt["acceptance"],
        value["review_report_paths"]["deployment_acceptance"],
        phase="deployment_acceptance",
        decision=acceptance_decision,
        reviewed_source_commit=value["reviewed_source_commit"],
        production_source_commit=production,
        production_preparation_inventory=preparation_inventory,
        consumer_commit=consumer,
        execution_commit=consumer,
    )
    _ancestor(root, consumer, acceptance)
    _only_evidence_delta(root, consumer, acceptance, value)
    if _git(root, "rev-parse", "refs/heads/main").decode().strip() != consumer:
        raise ValueError("current_main_mismatch")
    if _git(root, "rev-parse", value["rollback_ref"] + "^{commit}").decode().strip() != value["governance_base_commit"]:
        raise ValueError("rollback_point_mismatch")


def blockers(receipt: Any, *, repo_root: Path = ROOT) -> list[str]:
    try:
        value = _load_contract(repo_root, require_sealed=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc) if isinstance(exc, ValueError) else type(exc).__name__]
    if not isinstance(receipt, dict):
        return ["receipt_not_object"]
    fixed = {
        "schema_version": value["receipt_schema_version"],
        "ticket_id": value["ticket_id"],
        "reviewed_source_commit": value["reviewed_source_commit"],
        "source_change_risk": value["source_change_risk"],
        "readiness_ceiling": value["readiness_ceiling"],
    }
    problems = [key + "_mismatch" for key, expected in fixed.items() if receipt.get(key) != expected]
    phase = receipt.get("phase")
    if phase not in value["allowed_phases"]:
        problems.append("unknown_phase")
    fields = set(fixed) | {
        "phase", "governance_commit", "production_source_commit",
        "production_preparation_inventory", "reviewed_commit", "source_review",
        "checks", "safety_flags",
    }
    if phase == "deployment_acceptance":
        fields.update(
            {
                "consumer_commit", "execution_commit", "integration_review", "acceptance",
                "campaign", "bindings", "missing_bindings", "run_evidence",
                "temporary_runtime", "final_runtime", "blocked_report", "campaign_evidence",
            }
        )
    if set(receipt) != fields:
        problems.append("receipt_fields_missing_or_unknown")
    for key in ("governance_commit", "reviewed_commit"):
        if not _is_commit(receipt.get(key)):
            problems.append(key + "_invalid")
    if not _is_commit(receipt.get("production_source_commit")):
        problems.append("production_source_commit_invalid")
    if not isinstance(receipt.get("production_preparation_inventory"), dict):
        problems.append("production_preparation_inventory_invalid")
    if phase == "deployment_acceptance":
        outcome_hint = receipt.get("run_evidence", {}).get("business_outcome")
        if outcome_hint in value["pre_run_blocked_outcomes"]:
            for key in ("consumer_commit", "execution_commit", "integration_review", "acceptance"):
                if receipt.get(key) is not None:
                    problems.append(key + "_must_be_null_for_pre_run_blocker")
            if receipt.get("blocked_report") is None:
                problems.append("blocked_report_missing")
        else:
            for key in ("consumer_commit", "execution_commit"):
                if not _is_commit(receipt.get(key)):
                    problems.append(key + "_invalid")
            if receipt.get("blocked_report") is not None:
                problems.append("blocked_report_must_be_null_after_deployment_started")
    required_checks = set(value["required_source_checks"])
    if phase == "deployment_acceptance":
        required_checks.update(value["required_deployment_checks"])
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != required_checks:
        problems.append("checks_missing_or_unknown")
    elif any(item not in ("passed", "blocked", "not_run") for item in checks.values()):
        problems.append("checks_status_invalid")
    flags = receipt.get("safety_flags")
    if not isinstance(flags, dict) or set(flags) != set(value["required_false_flags"]):
        problems.append("safety_flags_missing_or_unknown")
    elif any(item is not False for item in flags.values()):
        problems.append("safety_flags_not_literal_false")
    outcome = None
    if phase == "deployment_acceptance":
        problems.extend(_validate_campaign(receipt, value))
        problems.extend(_validate_bindings(receipt, value))
        problems.extend(_validate_run(receipt, value))
        problems.extend(_validate_runtime(receipt, value))
        run = receipt.get("run_evidence")
        if isinstance(run, dict):
            outcome = run.get("business_outcome")
        if isinstance(checks, dict) and set(checks) == required_checks:
            if any(checks.get(name) != "passed" for name in value["required_source_checks"]):
                problems.append("source_checks_must_pass_before_deployment_report")
            deployment_statuses = [checks.get(name) for name in value["required_deployment_checks"]]
            if outcome == "passed" and any(status != "passed" for status in deployment_statuses):
                problems.append("passed_deployment_check_incomplete")
            if outcome != "passed" and all(status == "passed" for status in deployment_statuses):
                problems.append("blocked_deployment_checks_must_expose_gap")
    elif isinstance(checks, dict) and set(checks) == required_checks:
        if any(status != "passed" for status in checks.values()):
            problems.append("source_review_check_incomplete")
    if problems:
        return sorted(set(problems))
    try:
        _verify_receipt_evidence(repo_root, receipt, value)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return ["evidence_invalid:" + detail]
    if phase == "deployment_acceptance" and outcome != "passed":
        return ["business_acceptance_not_passed:" + str(outcome)]
    return []


def _emit(status: str, problems: Sequence[str], **extra: Any) -> int:
    payload = {"status": status, "blockers": list(problems), **extra}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if status == "valid" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the one-time real-candidate offline acceptance contract."
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect-contract")
    sub.add_parser("validate-source")
    receipt = sub.add_parser("validate-receipt")
    receipt.add_argument("--input", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    try:
        if args.command == "inspect-contract":
            value = contract(root)
            status = "valid" if value["source_sealed"] is True else "blocked"
            problems = [] if status == "valid" else ["source_not_sealed"]
            return _emit(status, problems, source_sealed=value["source_sealed"])
        if args.command == "validate-source":
            frozen_source(root)
            return _emit("valid", [], source_sealed=True)
        receipt = json.loads(args.input.read_text(encoding="utf-8"))
        problems = blockers(receipt, repo_root=root)
        return _emit("valid" if not problems else "blocked", problems)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return _emit("blocked", [detail])


if __name__ == "__main__":
    raise SystemExit(main())
