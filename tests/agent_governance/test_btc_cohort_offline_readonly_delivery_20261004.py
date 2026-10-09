"""Pure failure-first checks; these fixtures never constitute deployment evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.agent_governance import btc_cohort_offline_readonly_delivery_20261004 as delivery

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def rules():
    return delivery.contract()


def records(c):
    head, stamp = delivery.BASE, datetime.now(timezone.utc).isoformat()
    value = dict(reviewed_commit=head, evidence_origin="canonical_main_live", mocked=False,
                 fixture=False, observed_at_utc=stamp,
                 checks={key: True for key in c["required_deployment_checks"]},
                 safety_flags={key: False for key in delivery.FALSE_FLAGS})
    for kind, port, schema in (("backend", 8765, "backend_current_main_identity_v1"),
                                ("frontend", 3000, "quant_frontend_runtime_identity_v1")):
        identity = dict(schema_version=schema, canonical=True, runtime_stale=False,
                        source_head=head, canonical_branch="main", canonical_port=port)
        if kind == "backend":
            identity.update(main_head=head, evidence_profile="research_readonly", read_only=True,
                            controls_disabled=True, research_completion_grants_trading=False,
                            paper_allowed=False, live_allowed=False, broker_or_order_allowed=False,
                            promotion_artifact_status="unavailable", listener_status="not_checked")
        else:
            identity.update(worktree=str(ROOT), current_main_head=head, current_source_head=head,
                            current_dirty_paths=[], manifest_match=True)
        value[kind] = dict(identity=identity, url=f"http://127.0.0.1:{port}/__{kind}_identity",
                           http_status=200, observed_at_utc=stamp,
                           listener=dict(port=port, pid=123, process_verified=True,
                                         worktree=str(ROOT), source_head=head))
    value["health"] = dict(http_status=200, profile="research_readonly", read_only=True,
                           controls_disabled=True, paper_allowed=False, live_allowed=False,
                           broker_or_order_allowed=False, source_head=head, observed_at_utc=stamp)
    value["browser"] = dict(origin="canonical_browser", url="http://127.0.0.1:3000/research",
                            source_head=head, mocked=False, fixture=False, observed_at_utc=stamp,
                            screenshot_sha256="a" * 64, actual_read_failures=[],
                            visible_states=["run: closed", "artifact: missing", "catalog: not_configured"],
                            checks={key: True for key in c["required_browser_checks"]},
                            cohort_card_post_count=0,
                            cohort_card_api_requests=[{"method": "GET", "path": p} for p in
                                ("/api/health", "/api/candidate-offline/capabilities")])
    value["capabilities"] = dict(url="http://127.0.0.1:8765/api/candidate-offline/capabilities",
                                http_status=200, source_head=head, observed_at_utc=stamp,
                                body={**{key: False for key in c["public_capability_false_fields"]},
                                      "source_implemented": True, "cohort_source_supported": True,
                                      "permissions": {key: False for key in c["public_permission_false_fields"]},
                                      "blockers": ["candidate_offline_not_configured"]})
    return value


def test_source_seal_absent_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery, "ROOT", tmp_path)
    with pytest.raises(OSError):
        delivery.contract()


@pytest.mark.parametrize("flag", delivery.FALSE_FLAGS)
def test_missing_true_and_nonboolean_flags_rejected(flag):
    flags = {key: False for key in delivery.FALSE_FLAGS}
    for value in (True, 0, None):
        changed = {**flags, flag: value}
        with pytest.raises(ValueError):
            delivery.validate_false_flags(changed)
    del flags[flag]
    with pytest.raises(ValueError):
        delivery.validate_false_flags(flags)


@pytest.mark.parametrize("path", ["docs/acceptance/arbitrary.md", ".agent/handoffs/OTHER/x.json",
                                      "backend/app/core/security.py", "quant_crypto/oms/new.py",
                                      "docs/../allowed.md", ".agent/handoffs/" + delivery.TICKET + "/nested/x.json"])
def test_extra_or_protected_path_rejected(rules, path):
    assert not delivery.allowed_delta(path, rules)


def test_pathless_backend_and_truthful_closed_missing_artifact_records_parse(rules):
    value = records(rules)
    original = copy.deepcopy(value)
    delivery.validate_publication_records(value, delivery.BASE, ROOT, rules)
    assert value == original and "worktree" not in value["backend"]["identity"]


@pytest.mark.parametrize("key", ["worktree", "repo_root"])
def test_backend_optional_path_must_match(rules, key):
    value = records(rules)
    value["backend"]["identity"][key] = str(ROOT)
    delivery.validate_publication_records(value, delivery.BASE, ROOT, rules)
    for bad in (str(ROOT.parent), "", None, "."):
        value["backend"]["identity"][key] = bad
        with pytest.raises(ValueError, match="backend_identity_main_binding_invalid"):
            delivery.validate_publication_records(value, delivery.BASE, ROOT, rules)


@pytest.mark.parametrize("kind,target,field,value", [
    ("backend", "identity", "main_head", "0" * 40),
    ("backend", "identity", "evidence_profile", "demo_quasi_live"),
    ("backend", "identity", "broker_or_order_allowed", True),
    ("backend", "listener", "worktree", "wrong-main"),
    ("backend", "listener", "process_verified", False),
    ("frontend", "identity", "worktree", None),
    ("frontend", "identity", "current_main_head", "0" * 40),
    ("frontend", "identity", "runtime_stale", True),
])
def test_wrong_identity_head_profile_listener_or_frontend_path_rejected(rules, kind, target, field, value):
    data = records(rules)
    data[kind][target][field] = value
    with pytest.raises(ValueError):
        delivery.validate_publication_records(data, delivery.BASE, ROOT, rules)


@pytest.mark.parametrize("field,value", [("mocked", True), ("fixture", True),
                                          ("actual_read_failures", ["read timeout"]),
                                          ("observed_at_utc", "2000-01-01T00:00:00Z")])
def test_browser_mock_or_actual_failure_rejected(rules, field, value):
    data = records(rules)
    data["browser"][field] = value
    with pytest.raises(ValueError):
        delivery.validate_publication_records(data, delivery.BASE, ROOT, rules)


@pytest.mark.parametrize("field,value", [("deployed_configured", True), ("start_allowed", None),
    ("offline_commands_enabled", True), ("cohort_execution_policy_compatible", True),
    ("cohort_protection_policy_compatible", True), ("blockers", [])])
def test_unconfigured_capabilities_must_not_enable_or_claim_compatibility(rules, field, value):
    data = records(rules)
    data["capabilities"]["body"][field] = value
    with pytest.raises(ValueError):
        delivery.validate_publication_records(data, delivery.BASE, ROOT, rules)


@pytest.mark.parametrize("method,path", [("POST", "/api/candidate-offline/capabilities"),
    ("GET", "/api/candidate-offline/catalog"), ("GET", "/api/candidate-offline/jobs"),
    ("GET", "/api/strategy-delivery/accounts")])
def test_cohort_card_cannot_fetch_management_or_write(rules, method, path):
    data = records(rules)
    data["browser"]["cohort_card_api_requests"].append(dict(method=method, path=path))
    with pytest.raises(ValueError, match="only_public_gets"):
        delivery.validate_publication_records(data, delivery.BASE, ROOT, rules)


def git(root, *args, input=None, env=None):
    return subprocess.run(["git", *args], cwd=root, input=input, capture_output=True,
                          check=True, env=env).stdout


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    c = delivery.contract()
    temp = tmp_path_factory.mktemp("cohort-readonly-isolated-git")
    bare = temp / "objects.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    previous = os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
    os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = git(ROOT, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
    env = dict(os.environ, GIT_INDEX_FILE=str(temp / "index"), GIT_AUTHOR_NAME="isolated-test",
               GIT_AUTHOR_EMAIL="isolated@example.invalid", GIT_COMMITTER_NAME="isolated-test",
               GIT_COMMITTER_EMAIL="isolated@example.invalid")

    def commit(parent, updates, second=None):
        git(bare, "read-tree", parent, env=env)
        for path, raw in updates.items():
            blob = git(bare, "hash-object", "-w", "--stdin", input=raw, env=env).decode().strip()
            git(bare, "update-index", "--add", "--cacheinfo", "100644," + blob + "," + path, env=env)
        tree = git(bare, "write-tree", env=env).decode().strip()
        return git(bare, "commit-tree", tree, "-p", parent, *(["-p", second] if second else []),
                   input=b"isolated fixture metadata, not deployment approval\n", env=env).decode().strip()

    def ref(head, path):
        return dict(commit=head, path=path, sha256=hashlib.sha256(git(bare, "show", head + ":" + path)).hexdigest())

    template = json.loads(git(bare, "show", c["source_review_handoff"]["commit"] + ":" + c["source_review_handoff"]["path"]))

    def handoff(parent, ticket, event, role, path, raw, event_type):
        h = copy.deepcopy(template)
        h.update(ticket_id=ticket, event_id=event, producer_role=role,
                 producer_branch="agent/" + role + "/isolated-fixture", event_type=event_type,
                 base_commit=delivery.BASE, deliverable_commit=parent, depends_on=[], supersedes=[],
                 transition_for="published-unit-governance" if event_type == "integrated" else "",
                 domain="governance", gate_impact="blocks_gate", promotion_eligible=False,
                 blockers=["unit_fixture_not_formal_deployment"],
                 deliverables=[dict(path=path, sha256=hashlib.sha256(raw).hexdigest(),
                                    schema_version=c["evidence_schema_version"], type="report", readiness_class="quality_checked")],
                 tests=[dict(command="isolated metadata fixture", result="passed", evidence_path=path)])
        hp = ".agent/handoffs/" + ticket + "/" + event + ".json"
        hc = commit(parent, {hp: json.dumps(h, indent=2).encode()})
        return ref(hc, hp)

    def report(kind, actor, context, reviewed, **extra):
        data = dict(schema_version=c["evidence_schema_version"], kind=kind, ticket_id=delivery.TICKET,
                    outcome="approved_limited_readonly", source_commit=c["source_commit"],
                    deployment_profile="research_readonly", readiness_ceiling="quality_checked",
                    gate_impact="blocks_gate", limitations=c["limitations"],
                    safety_flags={k: False for k in delivery.FALSE_FLAGS}, actor_id=actor, context_id=context,
                    actor_role="root_reviewer" if kind == "governance_review" else "integrator",
                    reviewed_commit=reviewed, **extra)
        return ("# Isolated fixture; not actual root approval\n<!-- " + c["evidence_marker"] +
                "\n" + json.dumps(data) + "\n-->\n").encode()

    owned = {p: (ROOT / p).read_bytes().replace(b"\r\n", b"\n") for p in c["sidecar_paths"]}
    producer_report = b"# Isolated producer report, not independently approved\n"
    gov = commit(delivery.BASE, {**owned, c["reports"]["governance"]: producer_report})
    gh = handoff(gov, delivery.TICKET, "published-unit-governance", "super_developer", c["reports"]["governance"], producer_report, "published")
    raw = report("governance_review", "/root", "isolated-root-context", gov)
    ui_review = c["readonly_ui_overlay"]["review"]["commit"]
    identity = json.loads(git(bare, "show", c["source_commit"] + ":" + c["derived_identity_path"]))
    script = ("import {buildObjectIds,computeFrontendFingerprint} from " +
              json.dumps((ROOT / delivery.support.IDENTITY_LIB).as_uri()) +
              ";const [root,head,release]=process.argv.slice(1);const objects=buildObjectIds(root,head);" +
              "console.log(JSON.stringify({objects,fingerprint:computeFrontendFingerprint(release,objects)}));")
    computed = json.loads(subprocess.run(["node", "--input-type=module", "-e", script, str(bare), ui_review, identity["release_id"]],
                                         check=True, capture_output=True, timeout=15).stdout)
    identity.update(baseline_commit=ui_review, object_ids=computed["objects"], fingerprint=computed["fingerprint"])
    review = commit(c["readonly_ui_overlay"]["review"]["commit"], {**owned, c["reports"]["governance"]: producer_report,
                    gh["path"]: git(bare, "show", gh["commit"] + ":" + gh["path"]),
                    c["reports"]["governance_review"]: raw,
                    c["derived_identity_path"]: json.dumps(identity).encode()}, gh["commit"])
    rh = handoff(review, c["governance_review_ticket_id"], "integrated-unit-root-review", "integrator", c["reports"]["governance_review"], raw, "integrated")
    raw = report("integration", "isolated-independent-integrator", "isolated-integrator-context", gov, governance_review_commit=review)
    integrated = commit(rh["commit"], {c["reports"]["integration"]: raw})
    ih = handoff(integrated, c["release_ticket_id"], "integrated-unit-release", "integrator", c["reports"]["integration"], raw, "integrated")
    r = {k: c[k] for k in ("ticket_id", "baseline_commit", "source_commit", "source_handoff_commit", "reviewed_release_commit", "source_change_risk", "deployment_profile", "readiness_ceiling", "gate_impact", "limitations")}
    r.update(schema_version=c["receipt_schema_version"], phase="source_review", checks={k: True for k in c["required_source_checks"]},
             safety_flags={k: False for k in delivery.FALSE_FLAGS}, governance_commit=gov, governance_handoff=gh,
             governance_review=ref(review, c["reports"]["governance_review"]), governance_review_handoff=rh,
             integration=ref(integrated, c["reports"]["integration"]), integration_handoff=ih)
    try:
        yield dict(root=bare, c=c, receipt=r, commit=commit, ref=ref, report=report, main_before=git(ROOT, "rev-parse", "refs/heads/main").decode().strip())
    finally:
        if previous is None: os.environ.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
        else: os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = previous


def test_real_git_source_and_complete_source_stage_not_deployment(evidence):
    assert delivery.verify_source(repo_root=evidence["root"]) == []
    assert delivery.blockers(evidence["receipt"], repo_root=evidence["root"]) == []
    assert evidence["receipt"]["gate_impact"] == "blocks_gate"


@pytest.fixture
def downstream(evidence, monkeypatch):
    # Actual Git source is separately verified above; negatives isolate downstream checks.
    monkeypatch.setattr(delivery, "_verify_source", lambda root, c: None)
    monkeypatch.setattr(delivery, "_verify_overlay", lambda root, c: None)
    return evidence


@pytest.mark.parametrize("field,value", [("ticket_id", "OTHER"), ("source_commit", "0" * 40),
    ("deployment_profile", "demo_quasi_live"), ("gate_impact", "none"), ("phase", "unknown")])
def test_unknown_ticket_source_profile_or_gate_rejected(downstream, field, value):
    r = copy.deepcopy(downstream["receipt"]); r[field] = value
    assert delivery.blockers(r, repo_root=downstream["root"])


@pytest.mark.parametrize("key", ["governance_review", "governance_review_handoff", "integration", "integration_handoff"])
def test_missing_or_wrong_report_and_handoff_rejected(downstream, key):
    r = copy.deepcopy(downstream["receipt"]); del r[key]
    assert delivery.blockers(r, repo_root=downstream["root"])
    r = copy.deepcopy(downstream["receipt"]); r[key]["sha256"] = "0" * 64
    assert delivery.blockers(r, repo_root=downstream["root"])


@pytest.mark.parametrize("actor,reviewed", [("producer", "actual"), ("/root", "wrong")])
def test_self_approval_and_wrong_reviewed_commit_rejected(downstream, actor, reviewed):
    f = downstream; r = copy.deepcopy(f["receipt"]); c = f["c"]
    raw = f["report"]("governance_review", c["producer_actor"] if actor == "producer" else actor,
                      "isolated-root-context", r["governance_commit"] if reviewed == "actual" else delivery.BASE)
    head = f["commit"](r["governance_review"]["commit"], {c["reports"]["governance_review"]: raw})
    r["governance_review"] = f["ref"](head, c["reports"]["governance_review"])
    assert delivery.blockers(r, repo_root=f["root"])


@pytest.mark.parametrize("path", ["quant_crypto/oms/new.py", "start-backend.cmd", "docs/acceptance/arbitrary.md"])
def test_post_source_business_and_protected_deltas_rejected(downstream, path):
    f = downstream; r = copy.deepcopy(f["receipt"])
    head = f["commit"](r["integration"]["commit"], {path: b"unreviewed delta\n"})
    r["integration"] = f["ref"](head, f["c"]["reports"]["integration"])
    assert delivery.blockers(r, repo_root=f["root"])
    if path == "quant_crypto/oms/new.py":
        # The exact two overlay paths are allowed only at their reviewed object seals.
        r = copy.deepcopy(f["receipt"])
        head = f["commit"](r["integration"]["commit"], {next(iter(delivery.UI_PATHS)): b"unreviewed UI drift\n"})
        r["integration"] = f["ref"](head, f["c"]["reports"]["integration"])
        assert delivery.blockers(r, repo_root=f["root"])


def test_source_blob_mode_sha_and_review_digest_drift_rejected(evidence):
    f = evidence; c = f["c"]
    path = next(iter(c["source_inventory"]))
    for field, value in (("blob", "0" * 40), ("mode", "100755"), ("sha256", "0" * 64)):
        changed = copy.deepcopy(c["source_inventory"]); changed[path][field] = value
        with pytest.raises(ValueError): delivery._seal(f["root"], c["source_commit"], changed)
    bad = {**c["source_review"], "sha256": "0" * 64}
    with pytest.raises(ValueError): delivery.support._ref(f["root"], bad, bad["path"])
    o = c["readonly_ui_overlay"]
    assert set(o["inventory"]) == delivery.UI_PATHS
    assert delivery.allowed_delta(o["published"]["path"], c)
    sibling = o["published"]["path"].rsplit("/", 1)[0] + "/arbitrary-unreviewed.json"
    assert not delivery.allowed_delta(sibling, c)
    bad = copy.deepcopy(c); bad["readonly_ui_overlay"]["inventory"]["frontend/src/unreviewed.tsx"] = o["inventory"][next(iter(delivery.UI_PATHS))]
    with pytest.raises(ValueError, match="overlay_scope"): delivery._verify_overlay(f["root"], bad)
    bad = {**o["review"], "sha256": "0" * 64}
    with pytest.raises(ValueError): delivery.support._ref(f["root"], bad, bad["path"])
    bad = {**o["published"], "path": sibling}
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        delivery._handoff(f["root"], bad, c["source_ticket_id"], o["source_commit"], "published")
    data = dict(schema_version=c["evidence_schema_version"], kind="readonly_ui_fix_review",
                ticket_id=delivery.TICKET, actor_id="/root", actor_role="root_reviewer",
                context_id="isolated-root-context", source_commit=c["source_commit"],
                reviewed_commit=delivery.BASE, outcome="approved_limited_readonly",
                deployment_profile="research_readonly", readiness_ceiling="quality_checked",
                gate_impact="blocks_gate", limitations=c["limitations"],
                safety_flags={key: False for key in delivery.FALSE_FLAGS})
    raw = ("<!-- " + o["review_marker"] + "\n" + json.dumps(data) + "\n-->\n").encode()
    head = f["commit"](o["review"]["commit"], {o["review"]["path"]: raw})
    bad = copy.deepcopy(c); bad["readonly_ui_overlay"]["review"] = f["ref"](head, o["review"]["path"])
    with pytest.raises(ValueError, match="root_review_binding"): delivery._verify_overlay(f["root"], bad)


def test_mock_cannot_be_formal_deployment_and_main_unchanged(downstream):
    f = downstream; r = copy.deepcopy(f["receipt"]); c = f["c"]
    r.update(phase="deployment_acceptance", deployment_commit=r["integration_handoff"]["commit"],
             deployment={"commit": r["integration"]["commit"], "path": c["reports"]["deployment"], "sha256": "0" * 64},
             checks={k: True for k in c["required_source_checks"] + c["required_deployment_checks"]})
    assert delivery.blockers(r, repo_root=f["root"])
    assert git(ROOT, "rev-parse", "refs/heads/main").decode().strip() == f["main_before"]


def test_existing_identity_derivation_and_illegal_fingerprint_rejected(evidence):
    f = evidence; c = f["c"]; parent = f["receipt"]["integration_handoff"]["commit"]
    identity = json.loads(git(f["root"], "show", c["source_commit"] + ":" + c["derived_identity_path"]))
    script = ("import {buildObjectIds,computeFrontendFingerprint} from " +
              json.dumps((ROOT / delivery.support.IDENTITY_LIB).as_uri()) +
              ";const [root,head,release]=process.argv.slice(1);const objects=buildObjectIds(root,head);" +
              "console.log(JSON.stringify({objects,fingerprint:computeFrontendFingerprint(release,objects)}));")
    computed = json.loads(subprocess.run(["node", "--input-type=module", "-e", script, str(f["root"]), parent, identity["release_id"]],
                                         check=True, capture_output=True, timeout=15).stdout)
    identity.update(baseline_commit=parent, object_ids=computed["objects"], fingerprint=computed["fingerprint"])
    derived = f["commit"](parent, {c["derived_identity_path"]: json.dumps(identity).encode()})
    metadata = f["commit"](derived, {c["reports"]["deployment"]: b"# metadata fixture, not runtime proof\n"})
    delivery.support._derived_identity(f["root"], metadata, c)
    assert identity["baseline_commit"] != metadata
    for key, value in (("fingerprint", "0" * 64), ("safety", {"live": True})):
        invalid = {**identity, key: value}
        bad = f["commit"](metadata, {c["derived_identity_path"]: json.dumps(invalid).encode()})
        with pytest.raises((ValueError, subprocess.SubprocessError)):
            delivery.support._derived_identity(f["root"], bad, c)
