"""Readonly one-off validation; source approval never enables economic execution."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.agent_governance import btc_unified_offline_readonly_delivery_20261004 as support

POLICY = "docs/agent_playbooks/btc_cohort_offline_readonly_delivery_20261004.json"
CONTRACT_SHA256 = "c5aad0dbb5b110c63d7ea7b8997de971b9f0aa1804374cb25530f108ae3ce614"
SUPPORT_PATH = "tools/agent_governance/btc_unified_offline_readonly_delivery_20261004.py"
SUPPORT_BLOB = "ea531318717ecb9a649cbf61831c84d6acf08a72"
TICKET = "BTC-COHORT-OFFLINE-READONLY-DELIVERY-20261004"
BASE = "a78e5e112f564c1ceaf47c57fc3035542cd12562"
UI_BASE = "5b0ecf9050ca0d99364f7271dd5eb25916878b9c"
UI_PATHS = {"frontend/src/workspaces/research/CandidateDelivery.tsx",
            "tests/contracts/test_candidate_offline_access.py"}
FALSE_FLAGS = (
    "candidate_management", "management_write", "offline_worker", "offline_enabled",
    "account", "demo", "demo_control_enabled", "promotion", "paper", "live", "private",
    "order", "real_order", "transfer", "withdraw", "execution_permission", "runtime_observed",
    "runtime_worker_enabled", "offline_commands_enabled", "offline_start_allowed", "start_allowed",
)
ERRORS = (OSError, ValueError, KeyError, TypeError, support.HandoffError, subprocess.SubprocessError)


def contract() -> dict:
    c = json.loads((ROOT / POLICY).read_text(encoding="utf-8"))
    if hashlib.sha256(support._canonical(c)).hexdigest() != CONTRACT_SHA256:
        raise ValueError("fixed_contract_changed")
    return c


def allowed_delta(path: Any, c: dict) -> bool:
    if not isinstance(path, str) or "\\" in path or any(p in {"", ".", ".."} for p in path.split("/")):
        return False
    if path in c["sidecar_paths"] or path in c["reports"].values() or path == c["derived_identity_path"]:
        return True
    overlay = c.get("readonly_ui_overlay", {})
    if path in overlay.get("inventory", {}) or path == overlay.get("published", {}).get("path"):
        return True
    return any(path.startswith(p) and re.fullmatch(r"[A-Za-z0-9._-]+\.json", path[len(p):])
               for p in c["allowed_handoff_directories"])


def validate_false_flags(flags: Any) -> None:
    support._false_flags(flags, {"required_false_flags": FALSE_FLAGS})


def verify_support(*, repo_root: Path = ROOT) -> None:
    actual = support._git(repo_root, "hash-object", "--path=" + SUPPORT_PATH, str(ROOT / SUPPORT_PATH)).decode().strip()
    if actual != SUPPORT_BLOB or support._git(repo_root, "rev-parse", BASE + ":" + SUPPORT_PATH).decode().strip() != SUPPORT_BLOB:
        raise ValueError("readonly_support_not_committed_baseline")


def _seal(root: Path, commit: str, inventory: dict, *, sha: bool = True) -> None:
    actual = support._tree(root, commit, list(inventory))
    raws = support._git_batch_bytes(root, [commit + ":" + p for p in inventory]) if sha else {}
    for path, wanted in inventory.items():
        if actual.get(path) != (wanted["mode"], wanted["blob"]):
            raise ValueError("sealed_blob_or_mode_changed:" + path)
        if sha and hashlib.sha256(raws[commit + ":" + path] or b"").hexdigest() != wanted["sha256"]:
            raise ValueError("sealed_sha256_changed:" + path)


def _handoff(root: Path, ref: dict, ticket: str, deliverable: str, event: str) -> dict:
    payload = support._handoff(root, ref, ticket, deliverable, event_type=event, historical=True)
    if payload["gate_impact"] != "blocks_gate":
        raise ValueError("blocked_execution_gate_must_be_preserved")
    return payload


def _verify_source(root: Path, c: dict) -> None:
    verify_support(repo_root=root)
    for before, after in ((BASE, c["source_commit"]), (c["source_commit"], c["source_handoff_commit"]),
                          (c["source_handoff_commit"], c["source_review"]["commit"]),
                          (c["source_review"]["commit"], c["reviewed_release_commit"]),
                          (c["source_commit"], c["fixed_long_test"]["head"]),
                          (c["fixed_long_test"]["head"], c["source_review"]["commit"])):
        support._ancestor(root, before, after)
    paths = support._paths(root, BASE, c["source_commit"])
    if len(c["source_inventory"]) != 18 or {p for p in paths if not p.startswith(".agent/handoffs/")} != set(c["source_inventory"]):
        raise ValueError("source_touch_set_mismatch")
    _seal(root, c["source_commit"], c["source_inventory"])
    _seal(root, c["fixed_long_test"]["head"], c["source_inventory"], sha=False)
    _seal(root, c["reviewed_release_commit"], c["source_inventory"], sha=False)
    if support._paths(root, c["source_commit"], c["reviewed_release_commit"]) != set(c["reviewed_metadata_inventory"]):
        raise ValueError("reviewed_source_metadata_delta_changed")
    _seal(root, c["reviewed_release_commit"], c["reviewed_metadata_inventory"])
    published = _handoff(root, c["source_handoff"], c["source_ticket_id"], c["source_commit"], "published")
    ref = c["source_review"]
    raw = support._ref(root, ref, ref["path"])
    if c["source_commit"].encode() not in raw or b"5 passed, 3 warnings in 1208.16s" not in raw:
        raise ValueError("fixed_independent_source_review_binding_missing")
    integrated = _handoff(root, c["source_review_handoff"], c["source_ticket_id"], ref["commit"], "integrated")
    if integrated["producer_role"] != "integrator" or published["event_id"] not in integrated["depends_on"] or not any(
        d["path"] == ref["path"] and d["sha256"] == ref["sha256"] for d in integrated["deliverables"]):
        raise ValueError("independent_source_review_handoff_binding_invalid")
    for ref in c["diagnostic_handoffs"]:
        if ref["approval_basis"] is not False:
            raise ValueError("historical_diagnostic_is_not_approval")
        _handoff(root, {k: ref[k] for k in ("commit", "path", "sha256")}, c["source_ticket_id"],
                 ref["deliverable_commit"], ref["event_type"])


def verify_source(*, repo_root: Path = ROOT) -> list[str]:
    try:
        c = contract()
        _verify_source(repo_root, c)
        _verify_overlay(repo_root, c)
    except ERRORS as exc:
        return ["source_invalid:" + support._reason(exc)]
    return []


def _verify_overlay(root: Path, c: dict) -> None:
    """Exact read-only UI correction; the frozen lifecycle proof remains unchanged."""
    o = c["readonly_ui_overlay"]
    if o["baseline_commit"] != UI_BASE or set(o["inventory"]) != UI_PATHS:
        raise ValueError("readonly_ui_overlay_scope_invalid")
    for before, after in ((c["source_handoff_commit"], UI_BASE), (UI_BASE, o["source_commit"]),
                          (o["source_commit"], o["published"]["commit"]),
                          (o["published"]["commit"], o["review"]["commit"]),
                          (c["reviewed_release_commit"], o["review"]["commit"])):
        support._ancestor(root, before, after)
    _seal(root, UI_BASE, c["source_inventory"], sha=False)
    if support._paths(root, UI_BASE, o["source_commit"]) != UI_PATHS:
        raise ValueError("readonly_ui_overlay_extra_delta")
    _seal(root, o["source_commit"], {**c["source_inventory"], **o["inventory"]})
    published = _handoff(root, o["published"], c["source_ticket_id"], o["source_commit"], "published")
    if published["producer_role"] != "btc_developer" or published["base_commit"] != BASE or support._paths(root, o["source_commit"], o["published"]["commit"]) != {o["published"]["path"]}:
        raise ValueError("readonly_ui_published_binding_invalid")
    ref = o["review"]
    raw = support._ref(root, ref, c["reports"]["governance_review"]).decode("utf-8")
    matches = re.findall(r"<!-- " + re.escape(o["review_marker"]) + r"\s+(.*?)\s+-->", raw, re.S)
    if len(matches) != 1:
        raise ValueError("readonly_ui_root_review_missing")
    data = json.loads(matches[0])
    fixed = dict(schema_version=c["evidence_schema_version"], kind="readonly_ui_fix_review", ticket_id=TICKET,
                 actor_id=c["root_reviewer_actor"], actor_role="root_reviewer", source_commit=c["source_commit"],
                 reviewed_commit=o["source_commit"], outcome="approved_limited_readonly",
                 deployment_profile="research_readonly", readiness_ceiling="quality_checked",
                 gate_impact="blocks_gate", limitations=c["limitations"])
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in fixed.items()) or not isinstance(data.get("context_id"), str) or not data["context_id"] or data["context_id"] == c["producer_actor"]:
        raise ValueError("readonly_ui_root_review_binding_invalid")
    validate_false_flags(data.get("safety_flags"))
    parents = support._git(root, "rev-list", "--parents", "-n", "1", ref["commit"]).decode().split()[1:]
    if len(parents) != 1 or support._paths(root, parents[0], ref["commit"]) != {ref["path"]}:
        raise ValueError("readonly_ui_review_extra_delta")
    _seal(root, ref["commit"], {**c["source_inventory"], **o["inventory"]}, sha=False)
    _seal(root, ref["commit"], c["reviewed_metadata_inventory"], sha=False)
    if any(not allowed_delta(p, c) for p in support._paths(root, c["reviewed_release_commit"], ref["commit"])):
        raise ValueError("readonly_ui_review_unapproved_delta")


def _delta(root: Path, target: str, governance: str, c: dict) -> None:
    support._ancestor(root, c["reviewed_release_commit"], target)
    o = c["readonly_ui_overlay"]
    support._ancestor(root, o["review"]["commit"], target)
    changed = support._paths(root, c["reviewed_release_commit"], target)
    bad = sorted(p for p in changed if not allowed_delta(p, c))
    if bad:
        raise ValueError("unreviewed_post_source_delta:" + ",".join(bad))
    _seal(root, target, {**c["source_inventory"], **o["inventory"]}, sha=False)
    _seal(root, target, c["reviewed_metadata_inventory"], sha=False)
    _seal(root, target, {o["published"]["path"]: {
        "mode": "100644", "blob": support._git(root, "rev-parse", o["published"]["commit"] + ":" + o["published"]["path"]).decode().strip()}}, sha=False)
    owned = c["sidecar_paths"] + [c["reports"]["governance"]]
    expected = support._tree(root, governance, owned)
    if len(expected) != 5 or support._tree(root, target, owned) != expected:
        raise ValueError("reviewed_governance_objects_changed")
    if c["derived_identity_path"] in changed:
        support._derived_identity(root, target, c)
    for path in changed:
        if any(path.startswith(p) for p in c["allowed_handoff_directories"]):
            payload = json.loads(support._git(root, "show", target + ":" + path))
            if path != ".agent/handoffs/" + payload.get("ticket_id", "") + "/" + payload.get("event_id", "") + ".json":
                raise ValueError("delta_handoff_filename_invalid")
            if support.validate_handoff_against_git(payload, repo_root=root) or payload.get("promotion_eligible") is not False or payload.get("gate_impact") != "blocks_gate":
                raise ValueError("delta_handoff_invalid")


def _report(root: Path, ref: dict, kind: str, c: dict) -> dict:
    raw = support._ref(root, ref, c["reports"][kind]).decode("utf-8")
    matches = re.findall(r"<!-- " + re.escape(c["evidence_marker"]) + r"\s+(.*?)\s+-->", raw, re.S)
    if len(matches) != 1:
        raise ValueError("report_marker_missing_or_duplicate")
    data = json.loads(matches[0])
    fixed = dict(schema_version=c["evidence_schema_version"], kind=kind, ticket_id=TICKET,
                 outcome="approved_limited_readonly", source_commit=c["source_commit"],
                 deployment_profile="research_readonly", readiness_ceiling="quality_checked",
                 gate_impact="blocks_gate", limitations=c["limitations"])
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in fixed.items()):
        raise ValueError("report_fixed_binding_invalid")
    if not all(isinstance(data.get(k), str) and data[k] and data[k] != c["producer_actor"] for k in ("actor_id", "context_id")):
        raise ValueError("report_independent_actor_required")
    if kind in {"governance_review", "deployment"} and (data["actor_id"] != c["root_reviewer_actor"] or data.get("actor_role") != "root_reviewer"):
        raise ValueError("actual_root_governance_review_required")
    validate_false_flags(data.get("safety_flags"))
    return data


def validate_publication_records(records: dict, deployed: str, main: Path, c: dict) -> None:
    """Parse evidence, preserving pathless backend and truthful unavailable artifacts."""
    browser = records.get("browser", {})
    if not isinstance(browser, dict) or browser.get("url") not in c["allowed_browser_urls"]:
        raise ValueError("canonical_browser_url_invalid")
    parsed = {**records, "browser": {**browser, "url": "http://127.0.0.1:3000/research"}}
    support._deployment_records(parsed, deployed, main, c)
    cap = records.get("capabilities")
    if not isinstance(cap, dict) or cap.get("url") != "http://127.0.0.1:8765/api/candidate-offline/capabilities" or cap.get("http_status") != 200 or cap.get("source_head") != deployed:
        raise ValueError("public_capability_evidence_missing")
    support._fresh(cap.get("observed_at_utc"), datetime.now(timezone.utc), c)
    body = cap.get("body")
    if not isinstance(body, dict) or body.get("source_implemented") is not True or body.get("cohort_source_supported") is not True or any(body.get(k) is not False for k in c["public_capability_false_fields"]):
        raise ValueError("readonly_capability_flags_invalid")
    permissions = body.get("permissions")
    if not isinstance(permissions, dict) or set(permissions) != set(c["public_permission_false_fields"]) or any(v is not False for v in permissions.values()):
        raise ValueError("readonly_capability_permissions_invalid")
    if any(body.get(k) is True for k in ("cohort_execution_policy_compatible", "cohort_protection_policy_compatible")) or body.get("blockers") != ["candidate_offline_not_configured"]:
        raise ValueError("real_pair_or_configuration_misrepresented")
    requests = browser.get("cohort_card_api_requests")
    allowed = {"/api/health", "/api/candidate-offline/capabilities"}
    if not isinstance(requests, list) or not requests or any(not isinstance(r, dict) or r.get("method") != "GET" or r.get("path") not in allowed for r in requests) or {r["path"] for r in requests} != allowed or type(browser.get("cohort_card_post_count")) is not int or browser["cohort_card_post_count"] != 0:
        raise ValueError("cohort_card_must_use_only_public_gets")


def _deployment(root: Path, r: dict, gov: str, c: dict) -> None:
    deployed = r["deployment_commit"]
    support._ancestor(root, r["integration_handoff"]["commit"], deployed)
    _delta(root, deployed, gov, c)
    main = support._registered_main(root)
    if support._git(root, "rev-parse", "refs/heads/main").decode().strip() != deployed or support._git(main, "rev-parse", "HEAD").decode().strip() != deployed or support._git(main, "symbolic-ref", "HEAD").decode().strip() != "refs/heads/main":
        raise ValueError("actual_registered_main_head_mismatch")
    if support._git(root, "rev-parse", c["rollback_ref"] + "^{commit}").decode().strip() != BASE:
        raise ValueError("exact_rollback_ref_missing_or_wrong")
    support._derived_identity(root, deployed, c)
    ref = r["deployment"]
    data = _report(root, ref, "deployment", c)
    support._ancestor(root, deployed, ref["commit"])
    if support._paths(root, deployed, ref["commit"]) - {c["reports"]["deployment"]}:
        raise ValueError("deployment_report_must_be_independent_metadata_only")
    validate_publication_records(data, deployed, main, c)
    manifest = json.loads(support._git(root, "show", deployed + ":" + c["derived_identity_path"]))
    identity = data["frontend"]["identity"]
    if any(identity.get(k) != manifest["fingerprint"] for k in ("fingerprint", "current_fingerprint")) or identity.get("frontend_src_tree") != manifest["object_ids"]["frontend_src_tree"]:
        raise ValueError("served_frontend_fingerprint_mismatch")


def blockers(r: Any, *, repo_root: Path = ROOT) -> list[str]:
    try:
        c = contract()
        fixed = {k: c[k] for k in ("ticket_id", "baseline_commit", "source_commit", "source_handoff_commit", "reviewed_release_commit", "source_change_risk", "deployment_profile", "readiness_ceiling", "gate_impact", "limitations")}
        fixed["schema_version"] = c["receipt_schema_version"]
        if not isinstance(r, dict) or any(r.get(k) != v for k, v in fixed.items()):
            raise ValueError("receipt_fixed_binding_invalid")
        phase = r.get("phase")
        if phase not in c["phases"]:
            raise ValueError("unknown_phase")
        fields = set(fixed) | {"phase", "checks", "safety_flags", "governance_commit", "governance_handoff", "governance_review", "governance_review_handoff", "integration", "integration_handoff"}
        if phase == "deployment_acceptance":
            fields |= {"deployment_commit", "deployment"}
        required = set(c["required_source_checks"]) | (set(c["required_deployment_checks"]) if phase == "deployment_acceptance" else set())
        if set(r) != fields or not isinstance(r["checks"], dict) or set(r["checks"]) != required or any(v is not True for v in r["checks"].values()):
            raise ValueError("receipt_fields_or_checks_invalid")
        validate_false_flags(r["safety_flags"])
        _verify_source(repo_root, c)
        _verify_overlay(repo_root, c)
        gov = r["governance_commit"]
        support._ancestor(repo_root, BASE, gov)
        if support._paths(repo_root, BASE, gov) != set(c["sidecar_paths"]) | {c["reports"]["governance"]}:
            raise ValueError("governance_producer_touch_set_invalid")
        if hashlib.sha256(support._canonical(json.loads(support._git(repo_root, "show", gov + ":" + POLICY)))).hexdigest() != CONTRACT_SHA256:
            raise ValueError("committed_governance_contract_changed")
        event = _handoff(repo_root, r["governance_handoff"], TICKET, gov, "published")
        review = _report(repo_root, r["governance_review"], "governance_review", c)
        if review.get("reviewed_commit") != gov or r["governance_review"]["commit"] == gov:
            raise ValueError("root_reviewed_commit_binding_invalid")
        support._ancestor(repo_root, gov, r["governance_review"]["commit"])
        _delta(repo_root, r["governance_review"]["commit"], gov, c)
        reviewed = _handoff(repo_root, r["governance_review_handoff"], c["governance_review_ticket_id"], r["governance_review"]["commit"], "integrated")
        integration = _report(repo_root, r["integration"], "integration", c)
        if integration.get("actor_role") != "integrator" or integration["actor_id"] in {review["actor_id"], c["producer_actor"]} or integration["context_id"] == review["context_id"] or integration.get("reviewed_commit") != gov or integration.get("governance_review_commit") != r["governance_review"]["commit"]:
            raise ValueError("independent_integration_binding_invalid")
        release = _handoff(repo_root, r["integration_handoff"], c["release_ticket_id"], r["integration"]["commit"], "integrated")
        for h, ref in ((reviewed, r["governance_review"]), (release, r["integration"])):
            if h["producer_role"] != "integrator" or h["transition_for"] != event["event_id"] or not any(d["path"] == ref["path"] and d["sha256"] == ref["sha256"] for d in h["deliverables"]):
                raise ValueError("independent_handoff_report_binding_invalid")
        _delta(repo_root, r["integration"]["commit"], gov, c)
        _delta(repo_root, r["integration_handoff"]["commit"], gov, c)
        if phase == "deployment_acceptance":
            _deployment(repo_root, r, gov, c)
    except ERRORS as exc:
        return ["evidence_invalid:" + support._reason(exc)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify-source", action="store_true")
    group.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        errors = verify_source(repo_root=args.repo_root) if args.verify_source else blockers(json.loads(args.receipt.read_text(encoding="utf-8")), repo_root=args.repo_root)
    except ERRORS as exc:
        errors = ["input_invalid:" + support._reason(exc)]
    print(json.dumps(dict(status="blocked" if errors else "valid", errors=errors,
                         readiness_ceiling="quality_checked", gate_impact="blocks_gate", permissions_granted=False), ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
