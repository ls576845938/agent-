"""Failure-first ticket tests; the positive source fixture uses real sealed Git objects.

Temporary commits model review metadata only. They are never deployment or
business acceptance evidence and never alter the registered main repository.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.agent_governance import btc_unified_offline_readonly_delivery_20261004 as delivery

ROOT = Path(__file__).resolve().parents[2]


def git(root, *args, input=None, env=None):
    return subprocess.run(["git", *args], cwd=root, input=input, capture_output=True,
                          check=True, env=env).stdout


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def source_fixture(tmp_path_factory):
    c = delivery.contract()
    temp = tmp_path_factory.mktemp("btc-unified-readonly-real-source")
    bare = temp / "objects.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    original_objects = git(ROOT, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
    old_alternates = os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
    os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = original_objects
    index = str(temp / "index")
    env = dict(os.environ, GIT_INDEX_FILE=index, GIT_AUTHOR_NAME="isolated-test",
               GIT_AUTHOR_EMAIL="isolated-test@example.invalid",
               GIT_COMMITTER_NAME="isolated-test", GIT_COMMITTER_EMAIL="isolated-test@example.invalid")

    def commit(parent, updates, *, other_parent=None):
        git(bare, "read-tree", parent, env=env)
        for path, raw in updates.items():
            blob = git(bare, "hash-object", "-w", "--stdin", input=raw, env=env).decode().strip()
            git(bare, "update-index", "--add", "--cacheinfo", "100644," + blob + "," + path, env=env)
        tree = git(bare, "write-tree", env=env).decode().strip()
        parents = ["-p", parent] + (["-p", other_parent] if other_parent else [])
        return git(bare, "commit-tree", tree, *parents, input=b"isolated review fixture\n", env=env).decode().strip()

    def reference(commit_id, path):
        return {"commit": commit_id, "path": path, "sha256": digest(git(bare, "show", commit_id + ":" + path))}

    template_ref = c["reviewed_handoffs"][-1]
    template = json.loads(git(ROOT, "show", template_ref["commit"] + ":" + template_ref["path"]))

    def handoff(parent, ticket, actor_role, event, path, raw, event_type):
        envelope = copy.deepcopy(template)
        envelope.update(ticket_id=ticket, event_id=event, event_type=event_type,
                        producer_role=actor_role, producer_branch="agent/" + actor_role + "/isolated-test",
                        base_commit=c["baseline_commit"], deliverable_commit=parent,
                        domain="governance", depends_on=[], transition_for="published-isolated-governance" if event_type == "integrated" else "",
                        deliverables=[{"path": path, "sha256": digest(raw), "schema_version": "isolated-test-v1",
                                       "type": "report", "readiness_class": "quality_checked"}],
                        tests=[{"command": "isolated metadata fixture only", "result": "passed", "evidence_path": path}],
                        blockers=["fixture_not_deployment_evidence"])
        hp = ".agent/handoffs/" + ticket + "/" + event + ".json"
        hc = commit(parent, {hp: json.dumps(envelope, indent=2).encode()})
        return reference(hc, hp)

    def report(kind, actor, reviewed, **extra):
        data = dict(schema_version="btc_unified_offline_readonly_evidence_v1",
                    kind=kind, ticket_id=c["ticket_id"], outcome="approved",
                    deployment_profile="research_readonly", readiness_ceiling="quality_checked",
                    limitations=c["limitations"], actor_role="integrator", actor_id=actor,
                    context_id=actor + "-fresh-context", reviewed_commit=reviewed, **extra)
        return ("# Isolated metadata fixture\n<!-- " + c["evidence_marker"] + "\n" +
                json.dumps(data) + "\n-->\n").encode()

    sidecars = {p: (ROOT / p).read_bytes().replace(b"\r\n", b"\n") for p in c["sidecar_paths"]}
    producer_report = b"# Producer fixture, no independent approval\n"
    governance = commit(c["baseline_commit"], {**sidecars, c["reports"]["governance"]: producer_report})
    governance_handoff = handoff(governance, c["ticket_id"], "super_developer", "published-isolated-governance",
                                 c["reports"]["governance"], producer_report, "published")
    review_raw = report("governance_review", "independent-governance-reviewer", governance)
    review = commit(governance_handoff["commit"], {c["reports"]["governance_review"]: review_raw})
    review_handoff = handoff(review, c["governance_review_ticket_id"], "integrator",
                             "integrated-isolated-governance-review", c["reports"]["governance_review"], review_raw, "integrated")
    integration_raw = report("independent_integration", "new-independent-source-integrator", governance,
                             governance_review_commit=review)
    metadata = {
        **sidecars, c["reports"]["governance"]: producer_report,
        c["reports"]["governance_review"]: review_raw, c["reports"]["integration"]: integration_raw,
        governance_handoff["path"]: git(bare, "show", governance_handoff["commit"] + ":" + governance_handoff["path"]),
        review_handoff["path"]: git(bare, "show", review_handoff["commit"] + ":" + review_handoff["path"]),
    }
    integrated = commit(c["source_handoff_commit"], metadata, other_parent=review_handoff["commit"])
    integrated_handoff = handoff(integrated, c["release_ticket_id"], "integrator",
                                 "integrated-isolated-source-review", c["reports"]["integration"], integration_raw, "integrated")
    receipt = {k: c[k] for k in (
        "ticket_id", "baseline_commit", "source_commit", "source_assembly_commit",
        "source_handoff_commit", "source_change_risk", "deployment_profile", "readiness_ceiling", "limitations"
    )}
    receipt.update(schema_version=c["receipt_schema_version"], phase="source_review",
                   checks={k: True for k in c["required_source_checks"]},
                   safety_flags={k: False for k in c["required_false_flags"]},
                   governance_commit=governance, governance_handoff=governance_handoff,
                   governance_review=reference(review, c["reports"]["governance_review"]),
                   governance_review_handoff=review_handoff,
                   integration=reference(integrated, c["reports"]["integration"]), integration_handoff=integrated_handoff)
    try:
        yield {"root": bare, "receipt": receipt, "commit": commit, "reference": reference, "report": report, "c": c,
               "registered_main_before": git(ROOT, "rev-parse", "refs/heads/main").decode().strip()}
    finally:
        if old_alternates is None:
            os.environ.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
        else:
            os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = old_alternates


def test_real_sealed_source_and_full_source_review_pass_without_deployment(source_fixture):
    f = source_fixture
    assert delivery.verify_source(repo_root=f["root"]) == []
    assert delivery.blockers(f["receipt"], repo_root=f["root"]) == []
    assert f["receipt"]["phase"] == "source_review"
    assert "deployment" not in f["receipt"]


@pytest.mark.parametrize("field,value", [
    ("ticket_id", "ANY-OTHER-TICKET"), ("source_commit", "0" * 40),
    ("source_assembly_commit", "1" * 40), ("source_handoff_commit", "2" * 40),
    ("deployment_profile", "demo_quasi_live"), ("readiness_ceiling", "promotion_evidence_ready"),
    ("phase", "approval"),
])
def test_unknown_identity_profile_and_phase_are_rejected(source_fixture, field, value):
    r = copy.deepcopy(source_fixture["receipt"])
    r[field] = value
    assert delivery.blockers(r, repo_root=source_fixture["root"])


@pytest.mark.parametrize("flag", delivery.contract()["required_false_flags"])
def test_unsafe_flag_or_absent_flag_never_defaults_false(source_fixture, flag):
    r = copy.deepcopy(source_fixture["receipt"])
    r["safety_flags"][flag] = True
    assert delivery.blockers(r, repo_root=source_fixture["root"])
    del r["safety_flags"][flag]
    assert delivery.blockers(r, repo_root=source_fixture["root"])


@pytest.mark.parametrize("value", [0, None, "false"])
def test_nonliteral_false_is_rejected(source_fixture, value):
    r = copy.deepcopy(source_fixture["receipt"])
    r["safety_flags"]["order"] = value
    assert delivery.blockers(r, repo_root=source_fixture["root"])


@pytest.fixture
def downstream(source_fixture, monkeypatch):
    # Source integrity already runs against the real Git closure in the positive test.
    # These negative cases isolate failures later in the same validation path.
    monkeypatch.setattr(delivery, "_verify_source", lambda root, c: None)
    return source_fixture


@pytest.mark.parametrize("key", ["governance_handoff", "governance_review", "governance_review_handoff",
                                  "integration", "integration_handoff"])
def test_missing_or_wrong_report_handoff_digest_rejected(downstream, key):
    r = copy.deepcopy(downstream["receipt"])
    r[key]["sha256"] = "0" * 64
    assert delivery.blockers(r, repo_root=downstream["root"])
    del r[key]
    assert delivery.blockers(r, repo_root=downstream["root"])


@pytest.mark.parametrize("path", [
    "quant_crypto/oms/unsafe_new_execution.py", "backend/app/core/security/unsafe.py",
    ".codex/hooks.json", "docs/agent_playbooks/delivery_risk_policy.json",
    "docs/unreviewed.md", ".agent/unreviewed.json",
    "frontend/scripts/update-frontend-identity.mjs",
])
def test_extra_business_protected_and_broad_metadata_paths_rejected(downstream, path):
    f = downstream
    r = copy.deepcopy(f["receipt"])
    target = f["commit"](r["integration"]["commit"], {path: b"unauthorized source delta\n"})
    r["integration"] = f["reference"](target, f["c"]["reports"]["integration"])
    assert "unreviewed_post_source_delta" in delivery.blockers(r, repo_root=f["root"])[0]


def test_source_file_and_allowed_sidecar_drift_rejected(downstream):
    f = downstream
    for path in ("quant_crypto/portfolio/multi_strategy.py", f["c"]["sidecar_paths"][1]):
        r = copy.deepcopy(f["receipt"])
        target = f["commit"](r["integration"]["commit"], {path: b"drift\n"})
        r["integration"] = f["reference"](target, f["c"]["reports"]["integration"])
        assert delivery.blockers(r, repo_root=f["root"])


def test_producer_cannot_approve_itself_and_review_binds_exact_commit(downstream):
    f = downstream
    r = copy.deepcopy(f["receipt"])
    raw = f["report"]("governance_review", f["c"]["producer_actor"], r["governance_commit"])
    review = f["commit"](r["governance_handoff"]["commit"], {f["c"]["reports"]["governance_review"]: raw})
    r["governance_review"] = f["reference"](review, f["c"]["reports"]["governance_review"])
    assert "self_approval" in delivery.blockers(r, repo_root=f["root"])[0]
    raw = f["report"]("governance_review", "independent-reviewer", f["c"]["baseline_commit"])
    review = f["commit"](r["governance_handoff"]["commit"], {f["c"]["reports"]["governance_review"]: raw})
    r["governance_review"] = f["reference"](review, f["c"]["reports"]["governance_review"])
    assert "review_binding_invalid" in delivery.blockers(r, repo_root=f["root"])[0]


@pytest.mark.parametrize("path", [
    "../docs/acceptance/a.md", "docs//acceptance/a.md", "docs/acceptance/anything.md",
    ".agent/handoffs/OTHER-TICKET/event.json", ".agent/handoffs/BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004/nested/event.json",
    "AGENTS.md", "start-frontend.cmd",
])
def test_allowlist_is_exact_and_rejects_paths(path):
    assert delivery.allowed_delta(path) is False


def test_illegal_derived_identity_is_rejected(downstream):
    f = downstream
    r = copy.deepcopy(f["receipt"])
    target = f["commit"](r["integration"]["commit"], {f["c"]["derived_identity_path"]: b'{"baseline_commit":"0"}\n'})
    r["integration"] = f["reference"](target, f["c"]["reports"]["integration"])
    assert delivery.blockers(r, repo_root=f["root"])


def test_mock_receipt_cannot_become_formal_deployment(downstream):
    f = downstream
    r = copy.deepcopy(f["receipt"])
    r["phase"] = "deployment_acceptance"
    r["checks"].update({k: True for k in f["c"]["required_deployment_checks"]})
    r["deployment_commit"] = r["integration_handoff"]["commit"]
    raw = f["report"]("deployment_acceptance", "independent-acceptance", r["deployment_commit"],
                      evidence_origin="mock", mocked=True, fixture=True)
    target = f["commit"](r["deployment_commit"], {f["c"]["reports"]["deployment"]: raw})
    r["deployment"] = f["reference"](target, f["c"]["reports"]["deployment"])
    assert delivery.blockers(r, repo_root=f["root"])
    assert git(ROOT, "rev-parse", "refs/heads/main").decode().strip() == f["registered_main_before"]


def test_browser_and_current_identity_evidence_are_mandatory(source_fixture):
    c = source_fixture["c"]
    assert "canonical_current_head_identities" in c["required_deployment_checks"]
    assert "canonical_browser_acceptance" in c["required_deployment_checks"]
    assert c["readiness_ceiling"] == "quality_checked"
    assert c["promotion_artifact_rebuild_required"] is False
    assert c["source_change_risk"] == "demo_execution_semantics"


def publication_records(c, head, main):
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()
    records = dict(reviewed_commit=head, evidence_origin="canonical_main_live", mocked=False,
                   fixture=False, observed_at_utc=stamp,
                   checks={k: True for k in c["required_deployment_checks"]},
                   safety_flags={k: False for k in c["required_false_flags"]})
    for kind, port, schema in (("backend", 8765, "backend_current_main_identity_v1"),
                                ("frontend", 3000, "quant_frontend_runtime_identity_v1")):
        if kind == "backend":
            # Existing committed backend identity intentionally excludes physical paths.
            identity = dict(schema_version=schema, canonical=True, runtime_stale=False,
                            source_head=head, main_head=head, evidence_profile="research_readonly",
                            source=dict(head=head, main_head=head, branch="main", profile="research_readonly"),
                            canonical_branch="main", canonical_host="127.0.0.1", canonical_port=port,
                            read_only=True, controls_disabled=True, research_completion_grants_trading=False,
                            paper_allowed=False, live_allowed=False, broker_or_order_allowed=False)
        else:
            identity = dict(schema_version=schema, canonical=True, runtime_stale=False,
                            source_head=head, canonical_branch="main", canonical_port=port,
                            worktree=str(main), main_head=head, current_main_head=head,
                            current_source_head=head, current_dirty_paths=[], manifest_match=True)
        records[kind] = dict(url=f"http://127.0.0.1:{port}/__{kind}_identity", http_status=200,
                             observed_at_utc=stamp, identity=identity,
                             listener=dict(port=port, pid=123, process_verified=True,
                                           worktree=str(main), source_head=head))
    records["health"] = dict(http_status=200, profile="research_readonly", read_only=True,
                             controls_disabled=True, paper_allowed=False, live_allowed=False,
                             broker_or_order_allowed=False, source_head=head, observed_at_utc=stamp)
    records["browser"] = dict(origin="canonical_browser", url="http://127.0.0.1:3000/research",
                              source_head=head, mocked=False, fixture=False, observed_at_utc=stamp,
                              screenshot_sha256="a" * 64, visible_states=["catalog: not_configured"],
                              actual_read_failures=[], checks={k: True for k in c["required_browser_checks"]})
    return records


@pytest.mark.parametrize("section,field,value,error", [
    ("health", "profile", "demo_quasi_live", "readonly_health_invalid"),
    ("health", "controls_disabled", False, "readonly_health_invalid"),
    ("health", "source_head", "0" * 40, "readonly_health_head_mismatch"),
    ("browser", "mocked", True, "real_canonical_browser_evidence_missing"),
    ("browser", "fixture", True, "real_canonical_browser_evidence_missing"),
    ("browser", "screenshot_sha256", None, "real_canonical_browser_evidence_missing"),
    ("browser", "checks", {}, "browser_checks_missing_or_actual_read_failure"),
    ("browser", "actual_read_failures", ["Qlib GET timeout"], "browser_checks_missing_or_actual_read_failure"),
    ("browser", "visible_states", [], "browser_checks_missing_or_actual_read_failure"),
    ("browser", "observed_at_utc", "2000-01-01T00:00:00Z", "deployment_evidence_stale_or_future"),
])
def test_publication_records_reject_wrong_profile_missing_browser_and_read_failure(source_fixture, section, field, value, error):
    c = source_fixture["c"]
    records = publication_records(c, c["baseline_commit"], ROOT)
    records[section][field] = value
    with pytest.raises(ValueError, match=error):
        delivery._deployment_records(records, c["baseline_commit"], ROOT, c)


@pytest.mark.parametrize("kind,field,value,error", [
    ("backend", "source_head", "0" * 40, "identity_not_canonical_current_head"),
    ("frontend", "current_main_head", "0" * 40, "identity_main_binding_invalid"),
    ("frontend", "canonical", False, "identity_not_canonical_current_head"),
    ("frontend", "runtime_stale", True, "identity_not_canonical_current_head"),
    ("frontend", "manifest_match", False, "frontend_identity_binding_invalid"),
])
def test_wrong_current_head_or_stale_identity_rejected(source_fixture, kind, field, value, error):
    c = source_fixture["c"]
    records = publication_records(c, c["baseline_commit"], ROOT)
    records[kind]["identity"][field] = value
    with pytest.raises(ValueError, match=error):
        delivery._deployment_records(records, c["baseline_commit"], ROOT, c)


def test_listener_must_have_real_positive_pid_and_registered_owner(source_fixture):
    c = source_fixture["c"]
    for field, value in (("pid", 0), ("pid", True), ("process_verified", False), ("worktree", str(ROOT.parent))):
        records = publication_records(c, c["baseline_commit"], ROOT)
        records["backend"]["listener"][field] = value
        with pytest.raises(ValueError, match="backend_listener_owner_invalid"):
            delivery._deployment_records(records, c["baseline_commit"], ROOT, c)


def test_existing_identity_derivation_accepts_ancestor_baseline_after_metadata_only_commit(source_fixture):
    f = source_fixture
    c = f["c"]
    parent = f["receipt"]["integration_handoff"]["commit"]
    identity = json.loads(git(f["root"], "show", c["source_commit"] + ":" + c["derived_identity_path"]))
    script = ("import {buildObjectIds,computeFrontendFingerprint} from " +
              json.dumps((ROOT / delivery.IDENTITY_LIB).as_uri()) +
              ";const [root,head]=process.argv.slice(1);const objects=buildObjectIds(root,head);" +
              "console.log(JSON.stringify({objects,fingerprint:computeFrontendFingerprint(" +
              json.dumps(identity["release_id"]) + ",objects)}));")
    computed = json.loads(subprocess.run(["node", "--input-type=module", "-e", script, str(f["root"]), parent],
                                         check=True, capture_output=True, timeout=15).stdout)
    identity.update(baseline_commit=parent, object_ids=computed["objects"], fingerprint=computed["fingerprint"])
    derived = f["commit"](parent, {c["derived_identity_path"]: json.dumps(identity, indent=2).encode()})
    metadata = f["commit"](derived, {c["reports"]["deployment"]: b"# metadata only, no approval\n"})
    delivery._derived_identity(f["root"], metadata, c)
    assert identity["baseline_commit"] != metadata
    identity["safety"]["order"] = True
    bad = f["commit"](metadata, {c["derived_identity_path"]: json.dumps(identity).encode()})
    with pytest.raises(ValueError, match="derived_identity_protected_field_changed:safety"):
        delivery._derived_identity(f["root"], bad, c)


def test_original_source_handoff_cannot_be_overwritten(downstream):
    f = downstream
    r = copy.deepcopy(f["receipt"])
    sealed = f["c"]["reviewed_handoffs"][-1]
    payload = json.loads(git(f["root"], "show", sealed["commit"] + ":" + sealed["path"]))
    payload["blockers"] = ["rewritten immutable source envelope"]
    target = f["commit"](r["integration"]["commit"], {sealed["path"]: json.dumps(payload).encode()})
    r["integration"] = f["reference"](target, f["c"]["reports"]["integration"])
    assert "original_source_handoff_overwritten" in delivery.blockers(r, repo_root=f["root"])[0]


def test_existing_backend_identity_without_paths_is_accepted():
    c = delivery.contract()
    records = publication_records(c, c["baseline_commit"], ROOT)
    identity = records["backend"]["identity"]
    assert "worktree" not in identity and "repo_root" not in identity
    delivery._deployment_records(records, c["baseline_commit"], ROOT, c)
    assert "worktree" not in identity and "repo_root" not in identity


@pytest.mark.parametrize("key", ["worktree", "repo_root"])
def test_backend_optional_identity_path_must_match_when_present(key):
    c = delivery.contract()
    records = publication_records(c, c["baseline_commit"], ROOT)
    records["backend"]["identity"][key] = str(ROOT)
    delivery._deployment_records(records, c["baseline_commit"], ROOT, c)
    records["backend"]["identity"][key] = str(ROOT.parent)
    with pytest.raises(ValueError, match="backend_identity_main_binding_invalid"):
        delivery._deployment_records(records, c["baseline_commit"], ROOT, c)


@pytest.mark.parametrize("value", [None, "", ".", "incorrect-main"])
def test_backend_mismatching_second_path_cannot_hide_behind_correct_worktree(value):
    c = delivery.contract()
    records = publication_records(c, c["baseline_commit"], ROOT)
    records["backend"]["identity"].update(worktree=str(ROOT), repo_root=value)
    with pytest.raises(ValueError, match="backend_identity_main_binding_invalid"):
        delivery._deployment_records(records, c["baseline_commit"], ROOT, c)


@pytest.mark.parametrize("field,value,error", [
    ("main_head", "0" * 40, "backend_identity_main_binding_invalid"),
    ("source_head", "0" * 40, "backend_identity_not_canonical_current_head"),
    ("evidence_profile", "demo_quasi_live", "backend_readonly_identity_invalid"),
    ("read_only", False, "backend_readonly_identity_invalid"),
    ("controls_disabled", False, "backend_readonly_identity_invalid"),
    ("paper_allowed", True, "backend_readonly_identity_invalid"),
])
def test_pathless_backend_identity_retains_head_and_readonly_guards(field, value, error):
    c = delivery.contract()
    records = publication_records(c, c["baseline_commit"], ROOT)
    records["backend"]["identity"][field] = value
    with pytest.raises(ValueError, match=error):
        delivery._deployment_records(records, c["baseline_commit"], ROOT, c)


def test_pathless_backend_identity_still_requires_independent_listener_owner():
    c = delivery.contract()
    records = publication_records(c, c["baseline_commit"], ROOT)
    records["backend"]["listener"]["worktree"] = str(ROOT.parent)
    with pytest.raises(ValueError, match="backend_listener_owner_invalid"):
        delivery._deployment_records(records, c["baseline_commit"], ROOT, c)


def test_frontend_requires_worktree_even_with_matching_repo_root():
    c = delivery.contract()
    records = publication_records(c, c["baseline_commit"], ROOT)
    records["frontend"]["identity"].pop("worktree")
    records["frontend"]["identity"]["repo_root"] = str(ROOT)
    with pytest.raises(ValueError, match="frontend_identity_main_binding_invalid"):
        delivery._deployment_records(records, c["baseline_commit"], ROOT, c)
