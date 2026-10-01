"""Validate one frozen candidate-market-policy research-readonly delivery.

The validator is read-only.  It never merges, starts services, refreshes an
identity, creates a rollback ref, or grants management/trading authority.
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
    "candidate_market_policy_readonly_delivery_20260928.json"
)
CONTRACT_HASH = "db30c2e298ffea66209c79bc68d6e4e62c884fbd6b6b31e7a2d098b5221d2340"
TICKET = "CANDIDATE-MARKET-POLICY-READONLY-DELIVERY-20260928"
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
HANDOFF_FILE_RE = re.compile(r"[A-Za-z0-9_-]+\.json")
SOURCE_CLASSIFICATIONS = frozenset(
    {
        "offline_execution_wiring",
        "research_readonly_ui",
        "read_model_performance",
        "test",
        "documentation",
        "handoff",
        "report",
        "identity_derived",
        "other_reviewed_source",
    }
)
CONTRACT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_schema_version",
        "ticket_id",
        "baseline_commit",
        "source_sealed",
        "source_commit",
        "source_change_risk",
        "deployment_profile",
        "evidence_kind",
        "readiness_ceiling",
        "independent_integrator_required",
        "promotion_artifact_rebuild_required",
        "backend_restart_required",
        "legacy_source_commit",
        "ui_integration_commit",
        "performance_integration_commit",
        "source_lineage",
        "source_files",
        "source_handoffs",
        "required_quant_crypto_application_files",
        "governance_paths",
        "review_report_paths",
        "handoff_prefixes",
        "identity_path",
        "identity_derivation_command",
        "rollback_ref",
        "allowed_phases",
        "required_source_checks",
        "required_deployment_checks",
        "required_false_flags",
        "runtime_acceptance",
        "forbidden_capabilities",
        "documentation",
    }
)
RUNTIME_FIXED_FIELDS = frozenset(
    {
        "evidence_source",
        "backend_port",
        "frontend_port",
        "backend_identity_ref",
        "frontend_identity_ref",
        "evidence_profile",
        "backend_health_status",
        "read_only",
        "controls_disabled",
        "canonical",
        "runtime_stale",
        "mock",
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


def _load_contract(root: Path = ROOT, *, require_sealed: bool = False) -> dict[str, Any]:
    value = json.loads((root / CONTRACT_PATH).read_text(encoding="utf-8"))
    if hashlib.sha256(_canonical(value)).hexdigest() != CONTRACT_HASH:
        raise ValueError("fixed_contract_changed")
    _validate_contract_shape(value)
    if require_sealed and value["source_sealed"] is not True:
        raise ValueError("source_not_sealed")
    return value


def contract(root: Path = ROOT) -> dict[str, Any]:
    """Return a defensive copy after fixed-contract validation."""
    return json.loads(json.dumps(_load_contract(root)))


def _validate_contract_shape(value: Mapping[str, Any]) -> None:
    if set(value) != CONTRACT_FIELDS:
        raise ValueError("contract_fields_missing_or_unknown")
    fixed = {
        "schema_version": "candidate_market_policy_readonly_delivery_contract_v1",
        "receipt_schema_version": "candidate_market_policy_readonly_delivery_receipt_v1",
        "ticket_id": TICKET,
        "baseline_commit": "770392bacab55596da3238b1815af4476866f0de",
        "source_change_risk": "unclassified",
        "deployment_profile": "research_readonly",
        "evidence_kind": "offline_execution",
        "readiness_ceiling": "quality_checked",
        "independent_integrator_required": True,
        "promotion_artifact_rebuild_required": False,
        "backend_restart_required": True,
        "legacy_source_commit": "8ea90775bc250ad4cfcab7592fbdc720b3df4edc",
        "ui_integration_commit": "8e120f7d4de92bcbde97edb9c5d34b34cce0a911",
        "required_quant_crypto_application_files": 4,
        "identity_path": "frontend/public/frontend-identity.json",
        "identity_derivation_command": "npm.cmd --prefix frontend run identity:refresh",
        "rollback_ref": "refs/tags/codex/candidate-market-policy-before-readonly-20260928",
        "documentation": (
            "docs/agent_playbooks/"
            "candidate_market_policy_readonly_delivery_20260928.md"
        ),
    }
    for key, expected in fixed.items():
        if value.get(key) != expected:
            raise ValueError("contract_fixed_field_mismatch:" + key)
    if value.get("source_sealed") not in (True, False):
        raise ValueError("source_sealed_not_literal_boolean")
    if value["source_sealed"] is False:
        pending = (
            value.get("source_commit") is None
            and value.get("performance_integration_commit") is None
            and value.get("source_lineage") == []
            and value.get("source_files") == {}
            and value.get("source_handoffs") == []
        )
        if not pending:
            raise ValueError("partially_sealed_contract_forbidden")
    else:
        for key in ("source_commit", "performance_integration_commit"):
            if not _is_commit(value.get(key)):
                raise ValueError("sealed_commit_invalid:" + key)
    if value.get("allowed_phases") != ["source_review", "deployment_acceptance"]:
        raise ValueError("allowed_phases_changed")
    if not isinstance(value.get("governance_paths"), list) or not value["governance_paths"]:
        raise ValueError("governance_paths_invalid")
    if any(not _safe_path(path) for path in value["governance_paths"]):
        raise ValueError("governance_path_invalid")
    reports = value.get("review_report_paths")
    if not isinstance(reports, dict) or set(reports) != {
        "source_review", "integration_review", "deployment_acceptance"
    } or any(not _safe_path(path) for path in reports.values()):
        raise ValueError("review_report_paths_invalid")
    prefixes = value.get("handoff_prefixes")
    if (
        not isinstance(prefixes, list)
        or len(prefixes) != 2
        or any(not _safe_path(prefix.rstrip("/")) or not prefix.endswith("/") for prefix in prefixes)
    ):
        raise ValueError("handoff_prefixes_invalid")
    if not isinstance(value.get("required_source_checks"), list) or not value["required_source_checks"]:
        raise ValueError("required_source_checks_invalid")
    if not isinstance(value.get("required_deployment_checks"), list) or not value["required_deployment_checks"]:
        raise ValueError("required_deployment_checks_invalid")
    if not isinstance(value.get("required_false_flags"), list) or not value["required_false_flags"]:
        raise ValueError("required_false_flags_invalid")
    if len(value["required_false_flags"]) != len(set(value["required_false_flags"])):
        raise ValueError("required_false_flags_duplicate")
    runtime = value.get("runtime_acceptance")
    expected_runtime = {
        "evidence_source": "canonical_registered_main_runtime",
        "backend_port": 8765,
        "frontend_port": 3000,
        "backend_identity_ref": "refs/heads/main",
        "frontend_identity_ref": "refs/heads/main",
        "evidence_profile": "research_readonly",
        "backend_health_status": "ok",
        "read_only": True,
        "controls_disabled": True,
        "canonical": True,
        "runtime_stale": False,
        "mock": False,
    }
    if not isinstance(runtime, dict) or set(runtime) != RUNTIME_FIXED_FIELDS or runtime != expected_runtime:
        raise ValueError("runtime_acceptance_changed")


def _tree_entry(root: Path, commit: str, path: str) -> tuple[str, str]:
    raw = _git(root, "ls-tree", commit, "--", path).decode("utf-8").rstrip("\n")
    match = re.fullmatch(r"([0-9]{6}) blob ([0-9a-f]{40})\t(.+)", raw)
    if not match or match.group(3) != path:
        raise ValueError("source_tree_entry_missing:" + path)
    return match.group(1), match.group(2)


def _verify_handoff_reference(root: Path, reference: Mapping[str, Any], source: str) -> None:
    required = {
        "path", "commit", "sha256", "schema_version", "event_id", "ticket_id",
        "deliverable_commit", "readiness_classes", "blockers", "relation",
        "delivery_chain_paths", "gate_impact", "promotion_eligible",
    }
    if not isinstance(reference, Mapping) or set(reference) != required:
        raise ValueError("source_handoff_reference_fields_invalid")
    path = reference["path"]
    commit = reference["commit"]
    if not _safe_path(path) or not path.startswith(".agent/handoffs/"):
        raise ValueError("source_handoff_path_invalid")
    if not _is_commit(commit) or not _is_commit(reference["deliverable_commit"]):
        raise ValueError("source_handoff_commit_invalid")
    if not _is_hash(reference["sha256"]):
        raise ValueError("source_handoff_digest_invalid")
    relation = reference["relation"]
    chain_paths = reference["delivery_chain_paths"]
    if not isinstance(chain_paths, list) or any(not _safe_path(item) for item in chain_paths):
        raise ValueError("source_handoff_delivery_chain_paths_invalid:" + path)
    if relation == "ancestor_dependency":
        _ancestor(root, commit, source)
        _ancestor(root, reference["deliverable_commit"], source)
        if chain_paths:
            raise ValueError("ancestor_dependency_chain_paths_forbidden:" + path)
    elif relation == "final_source_delivery":
        # The final append-only handoff is published after immutable business SOURCE.
        _ancestor(root, source, commit)
        if reference["deliverable_commit"] != source:
            raise ValueError("source_handoff_deliverable_not_frozen_source:" + path)
        if _paths(root, source, commit) != set(chain_paths):
            raise ValueError("source_handoff_delivery_chain_mismatch:" + path)
    elif relation == "post_source_integration":
        _ancestor(root, source, reference["deliverable_commit"])
        _ancestor(root, reference["deliverable_commit"], commit)
        if _paths(root, source, commit) != set(chain_paths):
            raise ValueError("source_handoff_delivery_chain_mismatch:" + path)
    else:
        raise ValueError("source_handoff_relation_invalid:" + path)
    raw = _git(root, "show", commit + ":" + path)
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("source_handoff_digest_mismatch:" + path)
    payload = json.loads(raw)
    from tools.agent_governance.handoff import (  # local import avoids CLI cycles
        validate_handoff_against_git,
    )

    errors = validate_handoff_against_git(payload, repo_root=root)
    if errors:
        raise ValueError("source_handoff_invalid:" + ";".join(errors))
    if payload.get("schema_version") != reference["schema_version"]:
        raise ValueError("source_handoff_schema_mismatch:" + path)
    for key in ("event_id", "ticket_id", "deliverable_commit"):
        if payload.get(key) != reference[key]:
            raise ValueError("source_handoff_" + key + "_mismatch:" + path)
    readiness = sorted({item["readiness_class"] for item in payload["deliverables"]})
    if readiness != reference["readiness_classes"]:
        raise ValueError("source_handoff_readiness_mismatch:" + path)
    if payload.get("blockers") != reference["blockers"]:
        raise ValueError("source_handoff_blockers_mismatch:" + path)
    if payload.get("gate_impact") != reference["gate_impact"]:
        raise ValueError("source_handoff_gate_impact_mismatch:" + path)
    if payload.get("promotion_eligible") is not reference["promotion_eligible"]:
        raise ValueError("source_handoff_promotion_eligible_mismatch:" + path)
    if reference["promotion_eligible"] is not False:
        raise ValueError("source_handoff_promotion_eligible_must_be_false:" + path)


def frozen_source(root: Path = ROOT) -> None:
    value = _load_contract(root, require_sealed=True)
    _verify_frozen_source(root, value)


def _verify_frozen_source(root: Path, value: Mapping[str, Any]) -> None:
    """Verify a sealed contract; split out so tests can use synthetic Git commits."""
    if value.get("source_sealed") is not True:
        raise ValueError("source_not_sealed")
    source = value["source_commit"]
    lineage = value["source_lineage"]
    expected_names = [
        "legacy_source", "ui_integration", "performance_integration", "final_source"
    ]
    if (
        not isinstance(lineage, list)
        or [item.get("name") for item in lineage if isinstance(item, dict)] != expected_names
        or any(not isinstance(item, dict) or set(item) != {"name", "commit"} for item in lineage)
    ):
        raise ValueError("source_lineage_invalid")
    expected_commits = [
        value["legacy_source_commit"],
        value["ui_integration_commit"],
        value["performance_integration_commit"],
        source,
    ]
    if [item["commit"] for item in lineage] != expected_commits:
        raise ValueError("source_lineage_commit_mismatch")
    chain = [value["baseline_commit"], *expected_commits]
    for before, after in zip(chain, chain[1:]):
        _ancestor(root, before, after)

    files = value["source_files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("source_files_empty")
    if set(files) != _paths(root, value["baseline_commit"], source):
        raise ValueError("source_touch_set_mismatch")
    application_paths = [path for path in files if path.startswith("quant_crypto/application/")]
    if len(application_paths) != value["required_quant_crypto_application_files"]:
        raise ValueError("quant_crypto_application_file_count_mismatch")
    for path, entry in files.items():
        if not _safe_path(path) or not isinstance(entry, list) or len(entry) != 4:
            raise ValueError("source_inventory_entry_invalid:" + str(path))
        blob_value, sha256_value, mode_value, classification = entry
        if (
            not _is_hash(sha256_value)
            or not isinstance(blob_value, str)
            or re.fullmatch(r"[0-9a-f]{40}", blob_value) is None
            or mode_value not in ("100644", "100755")
            or classification not in SOURCE_CLASSIFICATIONS
        ):
            raise ValueError("source_inventory_value_invalid:" + path)
        if path.startswith("quant_crypto/application/") and classification != "offline_execution_wiring":
            raise ValueError("quant_crypto_application_classification_invalid:" + path)
        mode, blob = _tree_entry(root, source, path)
        if mode != mode_value or blob != blob_value:
            raise ValueError("source_blob_or_mode_mismatch:" + path)
        if hashlib.sha256(_git(root, "show", source + ":" + path)).hexdigest() != sha256_value:
            raise ValueError("source_sha256_mismatch:" + path)
    handoffs = value["source_handoffs"]
    if not isinstance(handoffs, list) or not handoffs:
        raise ValueError("source_handoffs_empty")
    final_relations = {"final_source_delivery", "post_source_integration"}
    if sum(item.get("relation") in final_relations for item in handoffs if isinstance(item, dict)) != 1:
        raise ValueError("exactly_one_final_source_handoff_required")
    for reference in handoffs:
        _verify_handoff_reference(root, reference, source)


def _handoff_delta(path: str, value: Mapping[str, Any]) -> bool:
    return any(
        path.startswith(prefix)
        and HANDOFF_FILE_RE.fullmatch(path[len(prefix):]) is not None
        for prefix in value["handoff_prefixes"]
    )


def allowed_delta(path: str, value: Mapping[str, Any] | None = None) -> bool:
    if value is None:
        value = _load_contract(ROOT)
    if not _safe_path(path):
        return False
    return (
        path in value["governance_paths"]
        or path in value["review_report_paths"].values()
        or path == value["identity_path"]
        or _handoff_delta(path, value)
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


def _only_paths(
    root: Path,
    before: str,
    after: str,
    allowed: set[str],
    value: Mapping[str, Any],
    *,
    identity_allowed: bool = False,
) -> None:
    for path in _paths(root, before, after):
        if path in allowed or _handoff_delta(path, value):
            continue
        if identity_allowed and path == value["identity_path"]:
            continue
        raise ValueError("phase_delta_not_allowed:" + path)


def _verify_runtime_evidence(receipt: Mapping[str, Any], value: Mapping[str, Any]) -> None:
    runtime = receipt.get("runtime_evidence")
    expected_fields = RUNTIME_FIXED_FIELDS | {
        "main_commit", "backend_identity_commit", "frontend_identity_commit", "page_receipt"
    }
    if not isinstance(runtime, dict) or set(runtime) != expected_fields:
        raise ValueError("runtime_evidence_fields_invalid")
    for key, expected in value["runtime_acceptance"].items():
        if runtime.get(key) != expected:
            raise ValueError("runtime_evidence_mismatch:" + key)
    target = receipt["target_commit"]
    for key in ("main_commit", "backend_identity_commit", "frontend_identity_commit"):
        if runtime.get(key) != target:
            raise ValueError("runtime_identity_not_target:" + key)
    if runtime.get("page_receipt") != receipt.get("acceptance"):
        raise ValueError("runtime_page_receipt_mismatch")


def _final_source_delivery_paths(value: Mapping[str, Any]) -> set[str]:
    final_relations = {"final_source_delivery", "post_source_integration"}
    return {
        path
        for reference in value["source_handoffs"]
        if reference["relation"] in final_relations
        for path in reference["delivery_chain_paths"]
    }


def _validate_source_to_governance_delta(
    paths: set[str], value: Mapping[str, Any]
) -> None:
    allowed = set(value["governance_paths"]) | _final_source_delivery_paths(value)
    if not paths or any(
        path not in allowed and not _handoff_delta(path, value) for path in paths
    ):
        raise ValueError("governance_contains_source_or_unrelated_delta")


def _verify_receipt_evidence(root: Path, receipt: Mapping[str, Any]) -> None:
    value = _load_contract(root, require_sealed=True)
    frozen_source(root)
    source = value["source_commit"]
    governance = receipt["governance_commit"]
    target = receipt["target_commit"]
    if not _is_commit(governance) or not _is_commit(target) or governance == source:
        raise ValueError("distinct_governance_commit_required")
    _ancestor(root, source, governance)
    governance_delta = _paths(root, source, governance)
    _validate_source_to_governance_delta(governance_delta, value)

    source_review = _report(
        root, receipt["source_review"], value["review_report_paths"]["source_review"]
    )
    integration_review = _report(
        root, receipt["integration_review"], value["review_report_paths"]["integration_review"]
    )
    if len({governance, source_review, integration_review}) != 3:
        raise ValueError("independent_committed_reviews_required")
    _ancestor(root, governance, source_review)
    _only_paths(
        root, governance, source_review,
        {value["review_report_paths"]["source_review"]}, value,
    )
    _ancestor(root, source_review, integration_review)
    _only_paths(
        root, source_review, integration_review,
        {value["review_report_paths"]["integration_review"]}, value,
        identity_allowed=True,
    )
    _ancestor(root, integration_review, target)
    _only_paths(root, integration_review, target, set(), value, identity_allowed=True)

    for path in value["governance_paths"]:
        if _git(root, "show", governance + ":" + path) != _git(root, "show", target + ":" + path):
            raise ValueError("reviewed_governance_changed:" + path)
    for path in value["source_files"]:
        if _git(root, "show", source + ":" + path) != _git(root, "show", target + ":" + path):
            raise ValueError("reviewed_source_changed:" + path)

    if receipt["phase"] != "deployment_acceptance":
        return
    acceptance = _report(
        root, receipt["acceptance"], value["review_report_paths"]["deployment_acceptance"]
    )
    _ancestor(root, target, acceptance)
    _only_paths(
        root, target, acceptance,
        {value["review_report_paths"]["deployment_acceptance"]}, value,
    )
    if _git(root, "rev-parse", "refs/heads/main").decode().strip() != target:
        raise ValueError("current_main_mismatch")
    if _git(root, "rev-parse", value["rollback_ref"] + "^{commit}").decode().strip() != value["baseline_commit"]:
        raise ValueError("rollback_point_mismatch")
    _verify_runtime_evidence(receipt, value)


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
        "baseline_commit": value["baseline_commit"],
        "source_commit": value["source_commit"],
        "source_change_risk": value["source_change_risk"],
        "deployment_profile": value["deployment_profile"],
        "evidence_kind": value["evidence_kind"],
        "readiness_ceiling": value["readiness_ceiling"],
    }
    problems = [key + "_mismatch" for key, expected in fixed.items() if receipt.get(key) != expected]
    phase = receipt.get("phase")
    if phase not in value["allowed_phases"]:
        problems.append("unknown_phase")
    fields = set(fixed) | {
        "phase", "governance_commit", "target_commit", "source_review",
        "integration_review", "checks", "safety_flags",
    }
    if phase == "deployment_acceptance":
        fields.update({"acceptance", "runtime_evidence"})
    if set(receipt) != fields:
        problems.append("receipt_fields_missing_or_unknown")
    required_checks = set(value["required_source_checks"])
    if phase == "deployment_acceptance":
        required_checks.update(value["required_deployment_checks"])
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != required_checks:
        problems.append("checks_missing_or_unknown")
    elif any(item is not True for item in checks.values()):
        problems.append("checks_not_literal_true")
    flags = receipt.get("safety_flags")
    if not isinstance(flags, dict) or set(flags) != set(value["required_false_flags"]):
        problems.append("safety_flags_missing_or_unknown")
    elif any(item is not False for item in flags.values()):
        problems.append("safety_flags_not_literal_false")
    if problems:
        return sorted(set(problems))
    try:
        _verify_receipt_evidence(repo_root, receipt)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return ["evidence_invalid:" + detail]
    return []


def _emit(status: str, problems: Sequence[str], **extra: Any) -> int:
    payload = {"status": status, "blockers": list(problems), **extra}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if status == "valid" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the one-time candidate market policy read-only delivery."
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
            blockers_value = [] if status == "valid" else ["source_not_sealed"]
            return _emit(status, blockers_value, source_sealed=value["source_sealed"])
        if args.command == "validate-source":
            frozen_source(root)
            return _emit("valid", [], source_sealed=True)
        receipt = json.loads(args.input.read_text(encoding="utf-8"))
        problems = blockers(receipt, repo_root=root)
        return _emit("valid" if not problems else "blocked", problems)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return _emit("blocked", [detail])


if __name__ == "__main__":
    raise SystemExit(main())
