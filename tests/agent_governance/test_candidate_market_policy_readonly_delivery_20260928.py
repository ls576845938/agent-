"""Failure-first tests for the one-time candidate market-policy release contract."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    return importlib.import_module(
        "tools.agent_governance.candidate_market_policy_readonly_delivery_20260928"
    )


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def commit(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "--all"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=root, check=True)
    return git(root, "rev-parse", "HEAD")


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def synthetic_source(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    write(repo, "base.txt", "base\n")
    baseline = commit(repo, "baseline")
    write(repo, "legacy.txt", "legacy\n")
    legacy = commit(repo, "legacy source")
    write(repo, "ui.txt", "ui\n")
    ui = commit(repo, "ui integration")
    write(repo, "performance.txt", "bounded reader\n")
    performance = commit(repo, "performance integration")
    application_paths = [
        "quant_crypto/application/donchian_historical_replay.py",
        "quant_crypto/application/donchian_historical_venue.py",
        "quant_crypto/application/donchian_offline_replay.py",
        "quant_crypto/application/qlib_offline_replay.py",
    ]
    for index, path in enumerate(application_paths):
        write(repo, path, f"# offline wiring {index}\n")
    source = commit(repo, "offline execution wiring")

    event_path = ".agent/handoffs/FIXTURE-SOURCE/published-fixture-source.json"
    delivered_path = application_paths[-1]
    delivered_raw = subprocess.check_output(
        ["git", "show", source + ":" + delivered_path], cwd=repo
    )
    payload = {
        "schema_version": "agent_handoff_envelope_v1",
        "event_id": "published-fixture-source",
        "ticket_id": "FIXTURE-SOURCE",
        "event_type": "published",
        "producer_role": "super_developer",
        "consumer_roles": ["integrator"],
        "domain": "governance",
        "producer_branch": "agent/super_developer/fixture-source",
        "base_commit": performance,
        "deliverable_commit": source,
        "created_at": "2026-09-28T00:00:00+00:00",
        "expires_at": "",
        "depends_on": [],
        "supersedes": [],
        "transition_for": "",
        "deliverables": [{
            "type": "code",
            "path": delivered_path,
            "sha256": sha(delivered_raw),
            "schema_version": "fixture_source_v1",
            "readiness_class": "quality_checked",
        }],
        "tests": [{
            "command": "pytest fixture",
            "result": "passed",
            "evidence_path": "",
        }],
        "blockers": ["deployment_acceptance_pending"],
        "gate_impact": "none",
        "promotion_eligible": False,
        "guardrails": {
            "handoff_only": True,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
    }
    write(repo, event_path, json.dumps(payload, indent=2) + "\n")
    handoff_commit = commit(repo, "source handoff")
    event_raw = subprocess.check_output(["git", "show", handoff_commit + ":" + event_path], cwd=repo)

    files = {}
    for path in git(repo, "diff", "--name-only", baseline, source, "--").splitlines():
        mode, kind, blob, tree_path = git(repo, "ls-tree", source, "--", path).split(maxsplit=3)
        assert kind == "blob" and tree_path == path
        classification = (
            "offline_execution_wiring"
            if path.startswith("quant_crypto/application/")
            else "handoff" if path.startswith(".agent/handoffs/")
            else "other_reviewed_source"
        )
        files[path] = [
            blob,
            sha(subprocess.check_output(["git", "show", source + ":" + path], cwd=repo)),
            mode,
            classification,
        ]
    contract = {
        "source_sealed": True,
        "source_commit": source,
        "baseline_commit": baseline,
        "legacy_source_commit": legacy,
        "ui_integration_commit": ui,
        "performance_integration_commit": performance,
        "source_lineage": [
            {"name": "legacy_source", "commit": legacy},
            {"name": "ui_integration", "commit": ui},
            {"name": "performance_integration", "commit": performance},
            {"name": "final_source", "commit": source},
        ],
        "source_files": files,
        "required_quant_crypto_application_files": 4,
        "source_handoffs": [{
            "path": event_path,
            "commit": handoff_commit,
            "sha256": sha(event_raw),
            "schema_version": "agent_handoff_envelope_v1",
            "event_id": "published-fixture-source",
            "ticket_id": "FIXTURE-SOURCE",
            "deliverable_commit": source,
            "readiness_classes": ["quality_checked"],
            "blockers": ["deployment_acceptance_pending"],
            "relation": "final_source_delivery",
            "delivery_chain_paths": [event_path],
            "gate_impact": "none",
            "promotion_eligible": False,
        }],
    }
    return repo, contract


@pytest.fixture(scope="module")
def source_fixture(tmp_path_factory):
    return synthetic_source(tmp_path_factory.mktemp("candidate-market-policy-source"))


def test_real_contract_is_sealed_and_cli_validates_exact_source():
    m = module()
    value = m.contract(ROOT)
    assert value["source_sealed"] is True
    result = subprocess.run(
        [sys.executable, str(Path(m.__file__).relative_to(ROOT)),
         "--repo-root", str(ROOT), "validate-source"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "blockers": [], "source_sealed": True, "status": "valid"
    }


def test_unsealed_contract_still_fails_closed_before_git_reads():
    with pytest.raises(ValueError, match="source_not_sealed"):
        module()._verify_frozen_source(ROOT, {"source_sealed": False})


def test_synthetic_sealed_git_source_validates_exact_ancestry_blob_hash_and_handoff(source_fixture):
    repo, original = source_fixture
    value = copy.deepcopy(original)
    module()._verify_frozen_source(repo, value)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda value: value["source_lineage"].__setitem__(1, {"name": "ui_integration", "commit": "f" * 40}),
         "source_lineage_commit_mismatch"),
        (lambda value: value["source_files"].pop("legacy.txt"), "source_touch_set_mismatch"),
        (lambda value: value["source_files"]["legacy.txt"].__setitem__(0, "f" * 40),
         "source_blob_or_mode_mismatch"),
        (lambda value: value["source_files"]["legacy.txt"].__setitem__(1, "f" * 64),
         "source_sha256_mismatch"),
        (lambda value: value["source_handoffs"][0].__setitem__("readiness_classes", ["promotion_evidence_ready"]),
         "source_handoff_readiness_mismatch"),
        (lambda value: value["source_handoffs"][0].__setitem__("blockers", []),
         "source_handoff_blockers_mismatch"),
    ],
)
def test_synthetic_source_negative_fixtures_fail_closed(source_fixture, mutation, expected):
    repo, original = source_fixture
    value = copy.deepcopy(original)
    mutation(value)
    with pytest.raises((ValueError, subprocess.SubprocessError), match=expected):
        module()._verify_frozen_source(repo, value)


def sealed_shape_contract() -> dict:
    value = module().contract(ROOT)
    value.update({
        "source_sealed": True,
        "source_commit": "d" * 40,
        "performance_integration_commit": "c" * 40,
    })
    return value


def receipt(value: dict, phase: str = "source_review") -> dict:
    item = {
        "schema_version": value["receipt_schema_version"],
        "ticket_id": value["ticket_id"],
        "phase": phase,
        "baseline_commit": value["baseline_commit"],
        "source_commit": value["source_commit"],
        "source_change_risk": value["source_change_risk"],
        "deployment_profile": value["deployment_profile"],
        "evidence_kind": value["evidence_kind"],
        "readiness_ceiling": value["readiness_ceiling"],
        "governance_commit": "e" * 40,
        "target_commit": "f" * 40,
        "source_review": {"commit": "1" * 40, "path": value["review_report_paths"]["source_review"], "sha256": "1" * 64},
        "integration_review": {"commit": "2" * 40, "path": value["review_report_paths"]["integration_review"], "sha256": "2" * 64},
        "checks": {name: True for name in value["required_source_checks"]},
        "safety_flags": {name: False for name in value["required_false_flags"]},
    }
    if phase == "deployment_acceptance":
        item["checks"].update({name: True for name in value["required_deployment_checks"]})
        item["acceptance"] = {
            "commit": "3" * 40,
            "path": value["review_report_paths"]["deployment_acceptance"],
            "sha256": "3" * 64,
        }
        item["runtime_evidence"] = {
            **value["runtime_acceptance"],
            "main_commit": item["target_commit"],
            "backend_identity_commit": item["target_commit"],
            "frontend_identity_commit": item["target_commit"],
            "page_receipt": copy.deepcopy(item["acceptance"]),
        }
    return item


def test_receipt_shape_requires_literal_checks_and_false_flags(monkeypatch):
    m = module()
    value = sealed_shape_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    assert m.blockers(receipt(value), repo_root=ROOT) == []
    for section, name, bad in (
        ("checks", value["required_source_checks"][0], 1),
        ("safety_flags", value["required_false_flags"][0], 0),
        ("safety_flags", value["required_false_flags"][0], True),
    ):
        item = receipt(value)
        item[section][name] = bad
        assert m.blockers(item, repo_root=ROOT)
    item = receipt(value)
    item["unknown"] = False
    assert "receipt_fields_missing_or_unknown" in m.blockers(item, repo_root=ROOT)


def test_deployment_requires_real_registered_main_shape_not_mock(monkeypatch):
    m = module()
    value = sealed_shape_contract()
    monkeypatch.setattr(m, "_load_contract", lambda *args, **kwargs: value)
    monkeypatch.setattr(m, "_verify_receipt_evidence", lambda *args, **kwargs: None)
    item = receipt(value, "deployment_acceptance")
    assert m.blockers(item, repo_root=ROOT) == []
    item["runtime_evidence"]["evidence_profile"] = "candidate_management"
    with pytest.raises(ValueError, match="runtime_evidence_mismatch:evidence_profile"):
        m._verify_runtime_evidence(item, value)
    item = receipt(value, "deployment_acceptance")
    item["runtime_evidence"]["mock"] = True
    with pytest.raises(ValueError, match="runtime_evidence_mismatch:mock"):
        m._verify_runtime_evidence(item, value)
    item = receipt(value, "deployment_acceptance")
    del item["runtime_evidence"]
    assert "receipt_fields_missing_or_unknown" in m.blockers(item, repo_root=ROOT)


@pytest.mark.parametrize(
    "path",
    [
        "quant_crypto/application/qlib_offline_replay.py",
        "backend/app/services/candidate_offline_views.py",
        "docs/agent_playbooks/delivery_risk_policy.json",
        "start-backend.cmd",
        ".codex/hooks.json",
        "../docs/escape.md",
        ".agent/handoffs/OTHER/event.json",
    ],
)
def test_post_source_broad_or_unrelated_delta_is_rejected(path):
    assert not module().allowed_delta(path, module().contract(ROOT))


def test_only_exact_identity_report_governance_and_ticket_handoff_are_allowed():
    m = module()
    value = m.contract(ROOT)
    assert m.allowed_delta(value["identity_path"], value)
    assert m.allowed_delta(value["governance_paths"][0], value)
    assert m.allowed_delta(value["review_report_paths"]["source_review"], value)
    assert m.allowed_delta(value["handoff_prefixes"][0] + "event.json", value)
    assert not m.allowed_delta(value["handoff_prefixes"][0] + "nested/event.json", value)


def test_real_post_source_integration_topology_is_allowed_for_governance_base():
    m = module()
    value = m.contract(ROOT)
    integration = "a7a8c384dc6c67e5d1b095f616098bab3818a711"
    actual = m._paths(ROOT, value["source_commit"], integration)
    expected = {
        path
        for reference in value["source_handoffs"]
        if reference["relation"] == "post_source_integration"
        for path in reference["delivery_chain_paths"]
    }
    assert actual == expected
    m._validate_source_to_governance_delta(actual, value)


def test_unregistered_event_in_old_ticket_directory_is_rejected():
    m = module()
    value = m.contract(ROOT)
    registered = m._final_source_delivery_paths(value)
    unregistered = (
        ".agent/handoffs/INTEGRATE-CANDIDATE-OFFLINE-DIAGNOSTIC-ADMISSION-20260926/"
        "unregistered-extra-event.json"
    )
    with pytest.raises(ValueError, match="governance_contains_source_or_unrelated_delta"):
        m._validate_source_to_governance_delta(registered | {unregistered}, value)


def test_general_risk_policy_is_unchanged_from_ticket_base():
    path = "docs/agent_playbooks/delivery_risk_policy.json"
    assert json.loads((ROOT / path).read_text(encoding="utf-8")) == json.loads(
        subprocess.check_output(
            ["git", "show", "770392bacab55596da3238b1815af4476866f0de:" + path], cwd=ROOT
        )
    )
