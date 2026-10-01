"""Validate one reviewed Donchian history source for a read-only deployment.

This module only checks committed evidence. It never merges, starts services,
replays a strategy, or grants a trading capability.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = "31e3e882e69e983aa88c01ccdf517236e0172e75"
SOURCE = "7fef4db378aef350a45c9ee716338103ecc5031e"
INVENTORY = "docs/architecture/donchian-history-readonly-touch-set-20260922.json"
INVENTORY_HASH = "ae95a6ae216b7297f37994ab5f5e062f7188c151eeecfd3313073cce2582d9b2"
REVIEW = "docs/operations/donchian-history-readonly-independent-review-20260922.md"
ACCEPTANCE = "docs/operations/donchian-history-readonly-deployment-20260922.md"
ROLLBACK = "refs/tags/codex/donchian-history-before-readonly-20260922"
POLICY = "docs/agent_playbooks/delivery_risk_policy.json"
GOVERNANCE_FILES = frozenset({
    POLICY,
    "docs/agent_playbooks/donchian_history_readonly_delivery.md",
    INVENTORY,
    "tools/agent_governance/donchian_history_readonly_delivery.py",
    "tests/agent_governance/test_donchian_history_readonly_delivery.py",
    "docs/operations/donchian-history-readonly-governance-20260922.md",
})
HANDOFFS = (
    ".agent/handoffs/DONCHIAN-HISTORY-READONLY-GOVERNANCE-20260922/",
    ".agent/handoffs/DONCHIAN-HISTORY-READONLY-INTEGRATION-20260922/",
)
FIXED = {
    "schema_version": "donchian_history_readonly_delivery_contract_v1",
    "ticket_id": "DONCHIAN-HISTORY-READONLY-GOVERNANCE-20260922",
    "source_commit": SOURCE,
    "baseline_commit": BASE,
    "source_change_risk": "demo_execution_semantics",
    "deployment_profile": "research_readonly",
    "evidence_kind": "offline_historical_replay",
    "readiness_ceiling": "quality_checked",
    "independent_integrator_required": True,
    "promotion_artifact_rebuild_required": False,
    "backend_restart_required": True,
    "required_source_checks": [
        "explicit_user_authorization",
        "dedicated_sparse_producer",
        "scoped_clean",
        "upstream_handoff_verified",
        "independent_business_integration_verified",
        "frozen_source_inventory_verified",
        "regression_316_and_existing_skip_verified",
        "historical_800_resume_and_ledger_verified",
        "legacy_800_parity_verified",
        "governance_independent_review_verified",
        "no_new_source_delta",
        "no_private_or_trading_access",
    ],
    "required_deployment_checks": [
        "fresh_governance_context",
        "frozen_source_unchanged",
        "readonly_profile_verified",
        "readonly_cli_entry_verified",
        "main_exact_deployment_commit",
        "canonical_backend_identity",
        "canonical_frontend_identity",
        "registered_listeners_and_health",
        "architecture_page_acceptance",
        "donchian_stage_page_acceptance",
        "historical_sources_truthfully_labeled",
        "rollback_point_verified",
        "no_private_or_trading_access",
    ],
    "required_false_flags": [
        "demo_control_enabled", "promotion", "paper", "live", "private",
        "order", "real_order", "transfer", "withdraw", "execution_permission",
        "runtime_worker_enabled", "runtime_observed",
    ],
    "documentation": "docs/agent_playbooks/donchian_history_readonly_delivery.md",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def contract() -> dict[str, Any]:
    return json.loads(json.dumps(FIXED))


def allowed_delta(path: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    if any(part in ("", ".", "..") for part in path.split("/")):
        return False
    if path in GOVERNANCE_FILES or path in (REVIEW, ACCEPTANCE):
        return True
    return any(
        path.startswith(prefix)
        and re.fullmatch(r"[A-Za-z0-9_-]+\.json", path[len(prefix):])
        for prefix in HANDOFFS
    )


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def _commit(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _ancestor(root: Path, ancestor: str, descendant: str) -> None:
    _git(root, "merge-base", "--is-ancestor", ancestor, descendant)


def _report(root: Path, ref: Any, path: str) -> str:
    if not isinstance(ref, dict) or set(ref) != {"path", "commit", "sha256"}:
        raise ValueError("report_reference_invalid")
    if ref["path"] != path or not _commit(ref["commit"]):
        raise ValueError("report_reference_invalid")
    if not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
        raise ValueError("report_digest_invalid")
    raw = _git(root, "show", ref["commit"] + ":" + path)
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("report_digest_mismatch")
    return ref["commit"]


def _frozen_source(root: Path) -> None:
    inventory = json.loads((root / INVENTORY).read_text(encoding="utf-8"))
    if hashlib.sha256(_canonical(inventory)).hexdigest() != INVENTORY_HASH:
        raise ValueError("frozen_inventory_changed")
    if (
        inventory.get("schema_version") != "donchian_history_readonly_source_inventory_v1"
        or inventory.get("ticket_id") != FIXED["ticket_id"]
        or inventory.get("baseline_commit") != BASE
        or inventory.get("source_commit") != SOURCE
        or not isinstance(inventory.get("files"), dict)
    ):
        raise ValueError("frozen_inventory_identity_mismatch")
    _ancestor(root, BASE, SOURCE)
    paths = set(_git(root, "diff", "--name-only", BASE, SOURCE, "--").decode().splitlines())
    if len(paths) != 35 or paths != set(inventory["files"]):
        raise ValueError("source_touch_set_mismatch")
    for path, digest in inventory["files"].items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("frozen_source_digest_invalid:" + path)
        if hashlib.sha256(_git(root, "show", SOURCE + ":" + path)).hexdigest() != digest:
            raise ValueError("frozen_source_digest_mismatch:" + path)


def _delta(root: Path, target: str) -> None:
    _ancestor(root, SOURCE, target)
    paths = _git(root, "diff", "--name-only", SOURCE, target, "--").decode().splitlines()
    if any(not allowed_delta(path) for path in paths):
        raise ValueError("unreviewed_post_source_delta")
    before = json.loads(_git(root, "show", SOURCE + ":" + POLICY))
    after = json.loads(_git(root, "show", target + ":" + POLICY))
    extra = after.pop("donchian_history_readonly_delivery", None)
    if _canonical(extra) != _canonical(FIXED) or _canonical(before) != _canonical(after):
        raise ValueError("legacy_policy_or_fixed_contract_changed")


def _reports_only(root: Path, start: str, end: str, *, acceptance: bool = False) -> None:
    paths = _git(root, "diff", "--name-only", start, end, "--").decode().splitlines()
    allowed_report = ACCEPTANCE if acceptance else REVIEW
    for path in paths:
        if path != allowed_report and not (
            allowed_delta(path) and any(path.startswith(prefix) for prefix in HANDOFFS)
        ):
            raise ValueError("reviewed_governance_or_source_changed:" + path)


def _evidence(root: Path, receipt: dict[str, Any]) -> None:
    governance = receipt.get("governance_commit")
    review = _report(root, receipt.get("review"), REVIEW)
    if not _commit(governance) or governance in (SOURCE, review):
        raise ValueError("distinct_governance_review_required")
    _ancestor(root, SOURCE, governance)
    _ancestor(root, governance, review)
    _delta(root, governance)
    _delta(root, review)
    _reports_only(root, governance, review)
    if receipt["phase"] == "source_review":
        return
    deployed = receipt.get("deployment_commit")
    if not _commit(deployed):
        raise ValueError("deployment_commit_required")
    _ancestor(root, review, deployed)
    _delta(root, deployed)
    _reports_only(root, review, deployed)
    acceptance = _report(root, receipt.get("acceptance"), ACCEPTANCE)
    _ancestor(root, deployed, acceptance)
    _delta(root, acceptance)
    _reports_only(root, deployed, acceptance, acceptance=True)
    if _git(root, "rev-parse", "refs/heads/main").decode().strip() != deployed:
        raise ValueError("current_main_mismatch")
    if _git(root, "rev-parse", ROLLBACK + "^{commit}").decode().strip() != BASE:
        raise ValueError("rollback_point_mismatch")


def blockers(receipt: Any, *, repo_root: Path = ROOT) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt_not_object"]
    expected = {
        "schema_version": "donchian_history_readonly_receipt_v1",
        "ticket_id": FIXED["ticket_id"],
        "source_commit": SOURCE,
        "baseline_commit": BASE,
        "source_change_risk": "demo_execution_semantics",
        "deployment_profile": "research_readonly",
        "evidence_kind": "offline_historical_replay",
    }
    problems = [key + "_mismatch" for key, value in expected.items() if receipt.get(key) != value]
    phase = receipt.get("phase")
    if phase not in ("source_review", "deployment_acceptance"):
        problems.append("unknown_phase")
    allowed = set(expected) | {
        "phase", "checks", "safety_flags", "governance_commit", "review",
    }
    if phase == "deployment_acceptance":
        allowed.update(("deployment_commit", "acceptance"))
    if set(receipt) != allowed:
        problems.append("receipt_fields_missing_or_unknown")
    required = set(FIXED["required_source_checks"])
    if phase == "deployment_acceptance":
        required.update(FIXED["required_deployment_checks"])
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != required:
        problems.append("checks_missing_or_unknown")
    elif any(checks[key] is not True for key in required):
        problems.append("checks_not_literal_true")
    flags = receipt.get("safety_flags")
    if not isinstance(flags, dict) or set(flags) != set(FIXED["required_false_flags"]):
        problems.append("safety_flags_missing_or_unknown")
    elif any(value is not False for value in flags.values()):
        problems.append("safety_flags_not_literal_false")
    if problems:
        return problems
    try:
        policy = json.loads((repo_root / POLICY).read_text(encoding="utf-8"))
        if _canonical(policy.get("donchian_history_readonly_delivery")) != _canonical(FIXED):
            return ["fixed_contract_changed"]
        _frozen_source(repo_root)
        _evidence(repo_root, receipt)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        return ["evidence_invalid:" + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__)]
    return []
