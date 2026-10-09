"""Read-only, ticket-specific validation of the reviewed BTC offline package.

Reads Git objects and supplied committed acceptance records; never merges,
starts services, discovers accounts, creates artifacts, or grants permissions.
"""
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
from tools.agent_governance.handoff import (
    HandoffError, _git_batch_bytes, validate_handoff_against_git,
)

POLICY = "docs/agent_playbooks/btc_unified_offline_readonly_delivery_20261004.json"
CONTRACT_SHA256 = "15a23d317265f4f0bc3235983152a3a5f81755e09cd2565641f14235762ac695"
IDENTITY_LIB = "frontend/scripts/frontend-identity-lib.mjs"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def contract() -> dict[str, Any]:
    value = json.loads((ROOT / POLICY).read_text(encoding="utf-8"))
    if hashlib.sha256(_canonical(value)).hexdigest() != CONTRACT_SHA256:
        raise ValueError("fixed_contract_changed")
    return value


def _git(root: Path, *args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=root, input=input, capture_output=True,
        check=True, timeout=8,
    ).stdout


def _ancestor(root: Path, before: str, after: str) -> None:
    if not HEX40.fullmatch(before) or not HEX40.fullmatch(after):
        raise ValueError("commit_identity_invalid")
    _git(root, "merge-base", "--is-ancestor", before, after)


def _paths(root: Path, before: str, after: str) -> set[str]:
    return set(_git(root, "diff", "--name-only", "-z", before, after, "--").decode().split("\0")) - {""}


def _tree(root: Path, commit: str, paths: list[str]) -> dict[str, tuple[str, str]]:
    rows = _git(root, "ls-tree", "-r", "-z", commit, "--", *paths).decode().split("\0")
    result = {}
    for row in filter(None, rows):
        fields, path = row.split("\t", 1)
        mode, kind, blob = fields.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("non_regular_git_path:" + path)
        result[path] = (mode, blob)
    return result


def allowed_delta(path: str) -> bool:
    """Only the four sidecars, three exact reports/dirs, and derived identity."""
    c = contract()
    if not isinstance(path, str) or "\\" in path or any(
        part in {"", ".", ".."} for part in path.split("/")
    ):
        return False
    if path in c["sidecar_paths"] or path in c["reports"].values() or path == c["derived_identity_path"]:
        return True
    return any(path.startswith(prefix) and re.fullmatch(
        r"[A-Za-z0-9._-]+\.json", path[len(prefix):]
    ) for prefix in c["allowed_handoff_directories"])


def _ref(root: Path, ref: Any, expected_path: str) -> bytes:
    if not isinstance(ref, dict) or set(ref) != {"commit", "path", "sha256"}:
        raise ValueError("git_reference_fields_invalid")
    if ref["path"] != expected_path or not isinstance(ref["commit"], str) or not HEX40.fullmatch(ref["commit"]):
        raise ValueError("git_reference_identity_invalid")
    if not isinstance(ref["sha256"], str) or not HEX64.fullmatch(ref["sha256"]):
        raise ValueError("git_reference_digest_invalid")
    _git(root, "cat-file", "-e", ref["commit"] + "^{commit}")
    _tree(root, ref["commit"], [expected_path])
    raw = _git(root, "show", ref["commit"] + ":" + expected_path)
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("git_reference_digest_mismatch:" + expected_path)
    return raw


def _handoff(root: Path, ref: dict, ticket: str, deliverable: str, *, event_type: str, historical: bool = False) -> dict:
    path = ref.get("path", "") if isinstance(ref, dict) else ""
    prefix = ".agent/handoffs/" + ticket + "/"
    if not path.startswith(prefix) or not re.fullmatch(r"[A-Za-z0-9._-]+\.json", path[len(prefix):]):
        raise ValueError("handoff_path_invalid")
    payload = json.loads(_ref(root, ref, path))
    errors = validate_handoff_against_git(payload, repo_root=root)
    if errors:
        raise ValueError("handoff_invalid:" + ";".join(errors))
    if payload["ticket_id"] != ticket or payload["deliverable_commit"] != deliverable or payload["event_type"] != event_type:
        raise ValueError("handoff_identity_mismatch")
    if path != prefix + payload["event_id"] + ".json":
        raise ValueError("handoff_filename_mismatch")
    if any(item["readiness_class"] != "quality_checked" for item in payload["deliverables"]):
        raise ValueError("handoff_readiness_ceiling_exceeded")
    if payload["promotion_eligible"] is not False or payload["gate_impact"] not in ({"none", "blocks_gate"} if historical else {"none"}):
        raise ValueError("handoff_gate_impact_invalid")
    _ancestor(root, deliverable, ref["commit"])
    return payload


def verify_source(*, repo_root: Path = ROOT) -> list[str]:
    """Verify exact real Git source, the 33-file seal, and its six envelopes."""
    try:
        _verify_source(repo_root, contract())
    except (OSError, ValueError, KeyError, TypeError, HandoffError, subprocess.SubprocessError) as exc:
        return ["source_invalid:" + _reason(exc)]
    return []


def _verify_source(root: Path, c: dict) -> None:
    base, assembly, source = c["baseline_commit"], c["source_assembly_commit"], c["source_commit"]
    _ancestor(root, base, assembly)
    _ancestor(root, assembly, source)
    _ancestor(root, source, c["source_handoff_commit"])
    inventory = c["source_inventory"]
    if len(inventory) != 33 or {p for p in _paths(root, base, source) if not p.startswith(".agent/")} != set(inventory):
        raise ValueError("source_touch_set_mismatch")
    review_path = "docs/acceptance/btc-unified-entry-coordination-independent-review-20261004.md"
    if _paths(root, assembly, source) != {review_path}:
        raise ValueError("source_assembly_review_delta_mismatch")
    actual = _tree(root, source, list(inventory))
    raws = _git_batch_bytes(root, [source + ":" + p for p in inventory])
    for path, sealed in inventory.items():
        if actual.get(path) != (sealed["mode"], sealed["blob"]):
            raise ValueError("source_blob_or_mode_mismatch:" + path)
        if hashlib.sha256(raws[source + ":" + path] or b"").hexdigest() != sealed["sha256"]:
            raise ValueError("source_sha256_mismatch:" + path)
    known = {r["event_id"] for r in c["reviewed_handoffs"]}
    previous = base
    for ref in c["reviewed_handoffs"]:
        payload = _handoff(root, {k: ref[k] for k in ("commit", "path", "sha256")},
                           ref["ticket_id"], ref["deliverable_commit"],
                           event_type="integrated" if ref["commit"] == c["source_handoff_commit"] else "published", historical=True)
        if payload["event_id"] != ref["event_id"] or payload["depends_on"] != ref["depends_on"] or not set(payload["depends_on"]) <= known:
            raise ValueError("reviewed_dependency_closure_mismatch")
        integrated = ref.get("integration_commit")
        if integrated:
            _ancestor(root, previous, integrated)
            _ancestor(root, integrated, assembly)
            changed = sorted(p for p in _paths(root, payload["base_commit"], payload["deliverable_commit"]) if not p.startswith(".agent/"))
            if _tree(root, payload["deliverable_commit"], changed) != _tree(root, integrated, changed):
                raise ValueError("reviewed_dependency_blob_mismatch:" + ref["event_id"])
            previous = integrated
    if _paths(root, source, c["source_handoff_commit"]) != {c["reviewed_handoffs"][-1]["path"]}:
        raise ValueError("source_handoff_delta_mismatch")


def _report(root: Path, ref: Any, path: str, kind: str, c: dict) -> dict:
    raw = _ref(root, ref, path).decode("utf-8")
    pattern = r"<!-- " + re.escape(c["evidence_marker"]) + r"\s+(.*?)\s+-->"
    matches = re.findall(pattern, raw, flags=re.S)
    if len(matches) != 1:
        raise ValueError("report_evidence_marker_missing_or_duplicate:" + kind)
    data = json.loads(matches[0])
    expected = {
        "schema_version": "btc_unified_offline_readonly_evidence_v1", "kind": kind,
        "ticket_id": c["ticket_id"], "outcome": "approved",
        "deployment_profile": c["deployment_profile"], "readiness_ceiling": "quality_checked",
        "limitations": c["limitations"],
    }
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
        raise ValueError("report_evidence_identity_mismatch:" + kind)
    if data.get("actor_role") not in {"architect", "integrator"} or not isinstance(data.get("actor_id"), str) or not data["actor_id"]:
        raise ValueError("report_independent_actor_missing:" + kind)
    if data["actor_id"] == c["producer_actor"] or not isinstance(data.get("context_id"), str) or not data["context_id"] or data["context_id"] == c["producer_actor"]:
        raise ValueError("report_producer_self_approval:" + kind)
    return data


def _derived_identity(root: Path, target: str, c: dict) -> None:
    """Use the existing library. Baseline is an ancestor, not the served HEAD."""
    path = c["derived_identity_path"]
    supplied = json.loads(_git(root, "show", target + ":" + path))
    original = json.loads(_git(root, "show", c["source_commit"] + ":" + path))
    baseline = supplied.get("baseline_commit", "")
    _ancestor(root, baseline, target)
    for key in ("schema_version", "release_id", "canonical_branch", "canonical_port", "frontend_generation", "routes", "safety"):
        if supplied.get(key) != original.get(key):
            raise ValueError("derived_identity_protected_field_changed:" + key)
    # The read-only library must itself be the committed original, not a dirty replacement.
    checked = _git(root, "hash-object", "--path=" + IDENTITY_LIB, str(ROOT / IDENTITY_LIB)).decode().strip()
    committed = _git(root, "rev-parse", c["source_commit"] + ":" + IDENTITY_LIB).decode().strip()
    if checked != committed:
        raise ValueError("frontend_identity_library_not_committed_original")
    script = (
        "import {buildObjectIds,computeFrontendFingerprint,validateManifest} from "
        + json.dumps((ROOT / IDENTITY_LIB).as_uri()) + ";"
        + "const [root,target,baseline,raw]=process.argv.slice(1);const m=JSON.parse(raw);"
        + "validateManifest(m);const b=buildObjectIds(root,baseline),t=buildObjectIds(root,target);"
        + "if(JSON.stringify(b)!==JSON.stringify(t)||JSON.stringify(t)!==JSON.stringify(m.object_ids)"
        + "||computeFrontendFingerprint(m.release_id,t)!==m.fingerprint)process.exit(2);"
    )
    subprocess.run(["node", "--input-type=module", "-e", script, str(root), target, baseline, json.dumps(supplied)],
                   check=True, capture_output=True, timeout=15)


def _delta(root: Path, target: str, governance: str, c: dict) -> None:
    _ancestor(root, c["source_handoff_commit"], target)
    changed = _paths(root, c["source_commit"], target)
    bad = sorted(p for p in changed if not allowed_delta(p))
    if bad:
        raise ValueError("unreviewed_post_source_delta:" + ",".join(bad))
    expected = _tree(root, governance, c["sidecar_paths"])
    if len(expected) != 4 or _tree(root, target, c["sidecar_paths"]) != expected:
        raise ValueError("reviewed_governance_sidecar_drift")
    sealed_envelope = c["reviewed_handoffs"][-1]
    if hashlib.sha256(_git(root, "show", target + ":" + sealed_envelope["path"])).hexdigest() != sealed_envelope["sha256"]:
        raise ValueError("original_source_handoff_overwritten")
    if c["derived_identity_path"] in changed:
        _derived_identity(root, target, c)
    for path in changed:
        if any(path.startswith(prefix) for prefix in c["allowed_handoff_directories"]):
            raw = _git(root, "show", target + ":" + path)
            payload = json.loads(raw)
            if path != ".agent/handoffs/" + payload.get("ticket_id", "") + "/" + payload.get("event_id", "") + ".json":
                raise ValueError("delta_handoff_ticket_or_filename_mismatch")
            errors = validate_handoff_against_git(payload, repo_root=root)
            if errors or payload.get("promotion_eligible") is not False:
                raise ValueError("delta_handoff_invalid:" + path)


def _fresh(value: Any, now: datetime, c: dict) -> None:
    if not isinstance(value, str):
        raise ValueError("deployment_timestamp_missing")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("deployment_timestamp_timezone_missing")
    age = (now - stamp).total_seconds()
    if not 0 <= age <= c["maximum_deployment_evidence_age_seconds"]:
        raise ValueError("deployment_evidence_stale_or_future")


def _registered_main(root: Path) -> Path:
    records = _git(root, "worktree", "list", "--porcelain").decode().split("\n\n")
    matches = [r.splitlines()[0][len("worktree "):] for r in records if "\nbranch refs/heads/main" in r]
    if len(matches) != 1:
        raise ValueError("registered_main_worktree_missing_or_ambiguous")
    return Path(matches[0]).resolve()


def _same_path(value: Any, expected: Path) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).is_absolute() and str(Path(value).resolve()).replace("\\", "/").casefold() == str(expected).replace("\\", "/").casefold()


def _deployment(root: Path, receipt: dict, governance: str, integrated: str, c: dict) -> None:
    deployed = receipt["deployment_commit"]
    _ancestor(root, integrated, deployed)
    _delta(root, deployed, governance, c)
    if _git(root, "rev-parse", "refs/heads/main").decode().strip() != deployed:
        raise ValueError("current_main_mismatch")
    main = _registered_main(root)
    if _git(main, "rev-parse", "HEAD").decode().strip() != deployed or _git(main, "symbolic-ref", "HEAD").decode().strip() != "refs/heads/main":
        raise ValueError("registered_main_identity_mismatch")
    if _git(root, "rev-parse", c["rollback_ref"] + "^{commit}").decode().strip() != c["baseline_commit"]:
        raise ValueError("rollback_ref_mismatch")
    _derived_identity(root, deployed, c)
    manifest = json.loads(_git(root, "show", deployed + ":" + c["derived_identity_path"]))
    ref = receipt["deployment"]
    acceptance = _report(root, ref, c["reports"]["deployment"], "deployment_acceptance", c)
    _ancestor(root, deployed, ref["commit"])
    if _paths(root, deployed, ref["commit"]) - {c["reports"]["deployment"]}:
        raise ValueError("deployment_acceptance_commit_has_extra_delta")
    _deployment_records(acceptance, deployed, main, c)
    identity = acceptance["frontend"]["identity"]
    if identity.get("fingerprint") != manifest["fingerprint"] or identity.get("current_fingerprint") != manifest["fingerprint"] or identity.get("frontend_src_tree") != manifest["object_ids"]["frontend_src_tree"]:
        raise ValueError("frontend_live_identity_manifest_mismatch")


def _deployment_records(acceptance: dict, deployed: str, main: Path, c: dict) -> None:
    """Parse evidence only; this helper cannot approve a deployment without Git checks."""
    if acceptance.get("reviewed_commit") != deployed or acceptance.get("evidence_origin") != "canonical_main_live" or acceptance.get("mocked") is not False or acceptance.get("fixture") is not False:
        raise ValueError("deployment_requires_real_current_main_evidence")
    # Approval actors are distinct from the producer; deployment may be assessed by the integrator.
    _fresh(acceptance.get("observed_at_utc"), datetime.now(timezone.utc), c)
    now = datetime.now(timezone.utc)
    for kind, port, schema in (("backend", 8765, "backend_current_main_identity_v1"), ("frontend", 3000, "quant_frontend_runtime_identity_v1")):
        observed = acceptance.get(kind)
        if not isinstance(observed, dict) or observed.get("url") != f"http://127.0.0.1:{port}/__{kind}_identity" or observed.get("http_status") != 200:
            raise ValueError(kind + "_identity_response_missing")
        _fresh(observed.get("observed_at_utc"), now, c)
        listener = observed.get("listener")
        identity = observed.get("identity")
        if not isinstance(listener, dict) or listener.get("port") != port or type(listener.get("pid")) is not int or listener["pid"] <= 0 or listener.get("process_verified") is not True or not _same_path(listener.get("worktree"), main) or listener.get("source_head") != deployed:
            raise ValueError(kind + "_listener_owner_invalid")
        if not isinstance(identity, dict) or identity.get("schema_version") != schema or identity.get("canonical") is not True or identity.get("runtime_stale") is not False or identity.get("source_head") != deployed or identity.get("canonical_port") != port or identity.get("canonical_branch") != "main":
            raise ValueError(kind + "_identity_not_canonical_current_head")
        head_key = "main_head" if kind == "backend" else "current_main_head"
        if identity.get(head_key) != deployed:
            raise ValueError(kind + "_identity_main_binding_invalid")
        if kind == "backend":
            if identity.get("evidence_profile") != "research_readonly" or identity.get("read_only") is not True or identity.get("controls_disabled") is not True or any(identity.get(k) is not False for k in ("research_completion_grants_trading", "paper_allowed", "live_allowed", "broker_or_order_allowed")):
                raise ValueError("backend_readonly_identity_invalid")
            if any(key in identity and not _same_path(identity[key], main) for key in ("worktree", "repo_root")):
                raise ValueError("backend_identity_main_binding_invalid")
        elif not _same_path(identity.get("worktree"), main):
            raise ValueError("frontend_identity_main_binding_invalid")
        if kind == "frontend" and (identity.get("manifest_match") is not True or identity.get("current_source_head") != deployed or identity.get("current_dirty_paths") != []):
            raise ValueError("frontend_identity_binding_invalid")
    health = acceptance.get("health")
    if not isinstance(health, dict) or health.get("http_status") != 200 or health.get("profile") != "research_readonly" or health.get("read_only") is not True or health.get("controls_disabled") is not True or any(health.get(k) is not False for k in ("paper_allowed", "live_allowed", "broker_or_order_allowed")):
        raise ValueError("readonly_health_invalid")
    if health.get("source_head") != deployed:
        raise ValueError("readonly_health_head_mismatch")
    _fresh(health.get("observed_at_utc"), now, c)
    browser = acceptance.get("browser")
    if not isinstance(browser, dict) or browser.get("origin") != "canonical_browser" or browser.get("url") != "http://127.0.0.1:3000/research" or browser.get("source_head") != deployed or browser.get("mocked") is not False or browser.get("fixture") is not False or not HEX64.fullmatch(str(browser.get("screenshot_sha256", ""))):
        raise ValueError("real_canonical_browser_evidence_missing")
    _fresh(browser.get("observed_at_utc"), now, c)
    if not isinstance(browser.get("checks"), dict) or set(browser["checks"]) != set(c["required_browser_checks"]) or any(v is not True for v in browser["checks"].values()) or browser.get("actual_read_failures") != [] or not isinstance(browser.get("visible_states"), list) or not browser["visible_states"]:
        raise ValueError("browser_checks_missing_or_actual_read_failure")
    required = c["required_deployment_checks"]
    if not isinstance(acceptance.get("checks"), dict) or set(acceptance["checks"]) != set(required) or any(v is not True for v in acceptance["checks"].values()):
        raise ValueError("deployment_checks_missing_or_not_true")
    _false_flags(acceptance.get("safety_flags"), c)


def _false_flags(flags: Any, c: dict) -> None:
    if not isinstance(flags, dict) or set(flags) != set(c["required_false_flags"]):
        raise ValueError("safety_flags_missing_or_unknown")
    if any(value is not False for value in flags.values()):
        raise ValueError("safety_flags_not_literal_false")


def _reason(exc: Exception) -> str:
    return str(exc) if isinstance(exc, (ValueError, HandoffError)) else type(exc).__name__


def blockers(receipt: Any, *, repo_root: Path = ROOT) -> list[str]:
    """Return failures, never turn absent fields into false or approve by fixture."""
    try:
        c = contract()
        if not isinstance(receipt, dict):
            raise ValueError("receipt_not_object")
        fixed = {k: c[k] for k in (
            "ticket_id", "baseline_commit", "source_commit", "source_assembly_commit",
            "source_handoff_commit", "source_change_risk", "deployment_profile", "readiness_ceiling",
        )}
        fixed.update(schema_version=c["receipt_schema_version"], limitations=c["limitations"])
        if any(receipt.get(k) != v for k, v in fixed.items()):
            raise ValueError("receipt_fixed_identity_mismatch")
        phase = receipt.get("phase")
        if phase not in c["phases"]:
            raise ValueError("unknown_phase")
        fields = set(fixed) | {"phase", "checks", "safety_flags", "governance_commit", "governance_handoff", "governance_review", "governance_review_handoff", "integration", "integration_handoff"}
        if phase == "deployment_acceptance":
            fields |= {"deployment_commit", "deployment"}
        if set(receipt) != fields:
            raise ValueError("receipt_fields_missing_or_unknown")
        checks = receipt["checks"]
        required = set(c["required_source_checks"])
        if phase == "deployment_acceptance":
            required.update(c["required_deployment_checks"])
        if not isinstance(checks, dict) or set(checks) != required or any(v is not True for v in checks.values()):
            raise ValueError("checks_missing_unknown_or_not_literal_true")
        _false_flags(receipt["safety_flags"], c)
        _verify_source(repo_root, c)
        governance = receipt["governance_commit"]
        if not isinstance(governance, str) or not HEX40.fullmatch(governance):
            raise ValueError("governance_commit_invalid")
        _ancestor(repo_root, c["baseline_commit"], governance)
        governance_paths = _paths(repo_root, c["baseline_commit"], governance)
        if governance_paths != set(c["sidecar_paths"]) | {c["reports"]["governance"]}:
            raise ValueError("governance_producer_touch_set_mismatch")
        committed = json.loads(_git(repo_root, "show", governance + ":" + POLICY))
        if hashlib.sha256(_canonical(committed)).hexdigest() != CONTRACT_SHA256:
            raise ValueError("committed_governance_contract_changed")
        _handoff(repo_root, receipt["governance_handoff"], c["ticket_id"], governance, event_type="published")
        review_ref = receipt["governance_review"]
        review = _report(repo_root, review_ref, c["reports"]["governance_review"], "governance_review", c)
        if review.get("reviewed_commit") != governance or review_ref["commit"] == governance:
            raise ValueError("independent_governance_review_binding_invalid")
        _ancestor(repo_root, governance, review_ref["commit"])
        if _paths(repo_root, governance, review_ref["commit"]) - {c["reports"]["governance_review"]} - {
            receipt["governance_handoff"]["path"]
        }:
            raise ValueError("independent_governance_review_extra_delta")
        review_event = _handoff(repo_root, receipt["governance_review_handoff"], c["governance_review_ticket_id"], review_ref["commit"], event_type="integrated")
        if review_event["producer_role"] != "integrator" or not any(d["path"] == review_ref["path"] and d["sha256"] == review_ref["sha256"] for d in review_event["deliverables"]):
            raise ValueError("governance_review_handoff_report_binding_invalid")
        integration_ref = receipt["integration"]
        integration = _report(repo_root, integration_ref, c["reports"]["integration"], "independent_integration", c)
        if integration.get("actor_role") != "integrator" or integration["actor_id"] == review["actor_id"] or integration["context_id"] == review["context_id"]:
            raise ValueError("distinct_fresh_independent_integrator_required")
        if integration.get("reviewed_commit") != governance or integration.get("governance_review_commit") != review_ref["commit"]:
            raise ValueError("integration_review_binding_invalid")
        _delta(repo_root, integration_ref["commit"], governance, c)
        release = _handoff(repo_root, receipt["integration_handoff"], c["release_ticket_id"], integration_ref["commit"], event_type="integrated")
        if release["producer_role"] != "integrator":
            raise ValueError("release_handoff_not_independent_integrator")
        if not any(d["path"] == integration_ref["path"] and d["sha256"] == integration_ref["sha256"] for d in release["deliverables"]):
            raise ValueError("integration_handoff_report_binding_invalid")
        _delta(repo_root, receipt["integration_handoff"]["commit"], governance, c)
        if phase == "deployment_acceptance":
            _deployment(repo_root, receipt, governance, receipt["integration_handoff"]["commit"], c)
    except (OSError, ValueError, KeyError, TypeError, HandoffError, subprocess.SubprocessError) as exc:
        return ["evidence_invalid:" + _reason(exc)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--receipt", type=Path, help="Read an existing receipt; never emits or changes it.")
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify_source == bool(args.receipt):
            parser.error("choose exactly one of --verify-source and --receipt")
        errors = verify_source(repo_root=args.repo_root) if args.verify_source else blockers(
            json.loads(args.receipt.read_text(encoding="utf-8")), repo_root=args.repo_root,
        )
    except (OSError, ValueError) as exc:
        errors = ["input_invalid:" + _reason(exc)]
    print(json.dumps({"status": "valid" if not errors else "blocked", "errors": errors,
                      "readiness_ceiling": "quality_checked", "permissions_granted": False}, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
