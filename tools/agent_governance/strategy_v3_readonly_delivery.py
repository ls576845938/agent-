"""One frozen V3 delivery. Validation is read-only, never an authorization API."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "aca55c90d82b327800e473774e22dbbeac69bd90"
BASE = "b920d131e41ecbfe7f76f0709affbe22c8b35f5e"
INVENTORY = "docs/architecture/strategy-v3-readonly-source-20260920.json"
INVENTORY_HASH = "f87bd74bf0a992601d7d45f0affcb7d67aff578702d1ec656dc38c3aaad6bbb1"
REVIEW = "docs/operations/strategy-v3-readonly-release-independent-review-20260920.md"
ACCEPTANCE = "docs/operations/strategy-v3-readonly-deployment-acceptance-20260920.md"
ROLLBACK = "refs/tags/codex/v3-before-readonly-20260920"
FIXED = json.loads("{\"schema_version\":\"strategy_v3_readonly_delivery_contract_v1\",\"ticket_id\":\"V3-READONLY-DELIVERY-20260920\",\"source_commit\":\"aca55c90d82b327800e473774e22dbbeac69bd90\",\"baseline_commit\":\"b920d131e41ecbfe7f76f0709affbe22c8b35f5e\",\"source_change_risk\":\"demo_execution_semantics\",\"deployment_profile\":\"research_readonly\",\"evidence_kind\":\"offline_execution\",\"readiness_ceiling\":\"quality_checked\",\"independent_integrator_required\":true,\"promotion_artifact_rebuild_required\":false,\"backend_restart_required\":true,\"required_source_checks\":[\"explicit_user_authorization\",\"dedicated_sparse_producer\",\"scoped_dirty\",\"scoped_clean\",\"failure_first_regression\",\"demo_safety_attestation\",\"append_only_handoff\",\"independent_integrator\",\"upstream_reviews_verified\",\"frozen_source_inventory_verified\",\"governance_independently_reviewed\",\"no_new_execution_semantics\"],\"required_deployment_checks\":[\"fresh_reviewed_governance_context\",\"frozen_source_unchanged\",\"readonly_profile_verified\",\"current_main_identity\",\"offline_entry_run_and_resume\",\"canonical_browser_acceptance\",\"evidence_kind_and_staleness_truthful\",\"rollback_point_verified\",\"no_private_or_trading_access\"],\"required_false_flags\":[\"demo_control_enabled\",\"promotion\",\"paper\",\"live\",\"private\",\"order\",\"real_order\",\"transfer\",\"withdraw\",\"execution_permission\",\"runtime_worker_enabled\",\"runtime_observed\"],\"documentation\":\"docs/agent_playbooks/strategy_v3_readonly_delivery.md\"}")
DELTA = frozenset({
    "docs/agent_playbooks/delivery_risk_policy.json",
    "tools/agent_governance/strategy_v3_readonly_delivery.py",
    "tests/agent_governance/test_strategy_v3_readonly_delivery.py",
    "docs/agent_playbooks/strategy_v3_readonly_delivery.md",
    "docs/operations/strategy-v3-readonly-release-20260920.md",
    INVENTORY, REVIEW, ACCEPTANCE,
})
HANDOFFS = (
    ".agent/handoffs/V3-READONLY-DELIVERY-20260920/",
    ".agent/handoffs/V3-READONLY-DELIVERY-INTEGRATION-20260920/",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def contract() -> dict:
    return json.loads(json.dumps(FIXED))


def allowed_delta(path: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    if any(part in ("", ".", "..") for part in path.split("/")):
        return False
    return path in DELTA or any(
        path.startswith(prefix) and re.fullmatch(r"[A-Za-z0-9_-]+\.json", path[len(prefix):])
        for prefix in HANDOFFS
    )


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def _commit(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _ancestor(root: Path, ancestor: str, descendant: str) -> None:
    _git(root, "merge-base", "--is-ancestor", ancestor, descendant)


def _report(root: Path, ref: Any, path: str) -> str:
    if not isinstance(ref, dict) or ref.get("path") != path or not _commit(ref.get("commit")):
        raise ValueError("report_reference_invalid")
    raw = _git(root, "show", ref["commit"] + ":" + path)
    if not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))):
        raise ValueError("report_digest_invalid")
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("report_digest_mismatch")
    return ref["commit"]


def _frozen_source(root: Path) -> None:
    inventory = json.loads((root / INVENTORY).read_text(encoding="utf-8"))
    if hashlib.sha256(_canonical(inventory)).hexdigest() != INVENTORY_HASH:
        raise ValueError("frozen_inventory_changed")
    _ancestor(root, BASE, SOURCE)
    paths = set(_git(root, "diff", "--name-only", BASE, SOURCE, "--").decode().splitlines())
    if paths != set(inventory["files"]):
        raise ValueError("source_touch_set_mismatch")
    for path, digest in inventory["files"].items():
        if hashlib.sha256(_git(root, "show", SOURCE + ":" + path)).hexdigest() != digest:
            raise ValueError("frozen_source_digest_mismatch:" + path)


def _delta(root: Path, target: str) -> None:
    _ancestor(root, SOURCE, target)
    paths = _git(root, "diff", "--name-only", SOURCE, target, "--").decode().splitlines()
    if any(not allowed_delta(path) for path in paths):
        raise ValueError("unreviewed_post_source_delta")
    # Governance extends this single contract; legacy rules must remain byte-equivalent as JSON.
    before = json.loads(_git(root, "show", SOURCE + ":docs/agent_playbooks/delivery_risk_policy.json"))
    after = json.loads(_git(root, "show", target + ":docs/agent_playbooks/delivery_risk_policy.json"))
    extra = after.pop("strategy_v3_readonly_delivery", None)
    if _canonical(extra) != _canonical(FIXED) or _canonical(before) != _canonical(after):
        raise ValueError("legacy_policy_or_fixed_contract_changed")


def _evidence(root: Path, receipt: dict) -> None:
    """Verify committed references; reviewer still verifies the facts in the report."""
    review = _report(root, receipt.get("review"), REVIEW)
    governance = receipt.get("governance_commit")
    if not _commit(governance) or governance in (SOURCE, review):
        raise ValueError("distinct_governance_review_required")
    _ancestor(root, governance, review)
    _delta(root, governance)
    _delta(root, review)
    _reports_only(root, governance, review)
    if receipt["phase"] != "deployment_acceptance":
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
    _reports_only(root, deployed, acceptance)
    if _git(root, "rev-parse", "refs/heads/main").decode().strip() != deployed:
        raise ValueError("current_main_mismatch")
    if _git(root, "rev-parse", ROLLBACK + "^{commit}").decode().strip() != BASE:
        raise ValueError("rollback_point_mismatch")


def _reports_only(root: Path, start: str, end: str) -> None:
    paths = _git(root, "diff", "--name-only", start, end, "--").decode().splitlines()
    for path in paths:
        if path not in (REVIEW, ACCEPTANCE) and not (
            allowed_delta(path) and any(path.startswith(prefix) for prefix in HANDOFFS)
        ):
            raise ValueError("reviewed_governance_or_source_changed:" + path)


def blockers(receipt: Any, *, repo_root: Path = ROOT) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt_not_object"]
    expected = {
        "schema_version": "strategy_v3_readonly_receipt_v1",
        "ticket_id": FIXED["ticket_id"], "source_commit": SOURCE,
        "source_change_risk": "demo_execution_semantics",
        "deployment_profile": "research_readonly", "evidence_kind": "offline_execution",
    }
    problems = [key + "_mismatch" for key, value in expected.items() if receipt.get(key) != value]
    phase = receipt.get("phase")
    if phase not in ("source_review", "deployment_acceptance"):
        problems.append("unknown_phase")
    required = set(FIXED["required_source_checks"])
    if phase == "deployment_acceptance":
        required.update(FIXED["required_deployment_checks"])
    checks = receipt.get("checks", {})
    if not isinstance(checks, dict) or set(checks) != required:
        problems.append("checks_missing_or_unknown")
    elif any(checks[key] is not True for key in required):
        problems.append("checks_not_literal_true")
    flags = receipt.get("safety_flags", {})
    if not isinstance(flags, dict) or set(flags) != set(FIXED["required_false_flags"]):
        problems.append("safety_flags_missing_or_unknown")
    elif any(value is not False for value in flags.values()):
        problems.append("safety_flags_not_literal_false")
    if problems:
        return problems
    try:
        policy = json.loads((repo_root / "docs/agent_playbooks/delivery_risk_policy.json").read_text(encoding="utf-8"))
        if _canonical(policy.get("strategy_v3_readonly_delivery")) != _canonical(FIXED):
            return ["fixed_contract_changed"]
        _frozen_source(repo_root)
        _evidence(repo_root, receipt)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        return ["evidence_invalid:" + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__)]
    return []
