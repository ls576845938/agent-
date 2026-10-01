"""One frozen Donchian history source may be deployed read-only only after review."""
from __future__ import annotations

import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "7fef4db378aef350a45c9ee716338103ecc5031e"
BASE = "31e3e882e69e983aa88c01ccdf517236e0172e75"


def module():
    return importlib.import_module("tools.agent_governance.donchian_history_readonly_delivery")


def receipt():
    fixed = module().contract()
    return {
        "schema_version": "donchian_history_readonly_receipt_v1",
        "ticket_id": fixed["ticket_id"],
        "source_commit": SOURCE,
        "baseline_commit": BASE,
        "source_change_risk": "demo_execution_semantics",
        "deployment_profile": "research_readonly",
        "evidence_kind": "offline_historical_replay",
        "phase": "source_review",
        "governance_commit": "a" * 40,
        "review": {
            "path": "docs/operations/donchian-history-readonly-independent-review-20260922.md",
            "commit": "b" * 40,
            "sha256": "c" * 64,
        },
        "checks": {key: True for key in fixed["required_source_checks"]},
        "safety_flags": {key: False for key in fixed["required_false_flags"]},
    }


def test_frozen_source_has_exact_35_git_blobs():
    module()._frozen_source(ROOT)
    paths = subprocess.check_output(["git", "diff", "--name-only", BASE, SOURCE, "--"], cwd=ROOT).decode().splitlines()
    assert len(paths) == 35


def test_booleans_are_not_independent_review():
    assert module().blockers(receipt(), repo_root=ROOT)


def test_review_shape_can_be_checked_without_faking_review(monkeypatch):
    monkeypatch.setattr(module(), "_evidence", lambda root, item: None)
    assert module().blockers(receipt(), repo_root=ROOT) == []


@pytest.mark.parametrize("field,value", [
    ("source_commit", "a" * 40),
    ("baseline_commit", "b" * 40),
    ("ticket_id", "OTHER"),
    ("source_change_risk", "research_readonly_release"),
    ("deployment_profile", "demo_quasi_live"),
    ("evidence_kind", "runtime_execution"),
])
def test_wrong_frozen_identity_or_profile_rejected(field, value):
    item = receipt()
    item[field] = value
    assert module().blockers(item, repo_root=ROOT)


def test_all_checks_and_flags_require_exact_literal_booleans():
    good = receipt()
    for field, required in (("checks", True), ("safety_flags", False)):
        for key in good[field]:
            for bad in ((0, "true", None) if required else (1, "false", None)):
                item = copy.deepcopy(good)
                item[field][key] = bad
                assert module().blockers(item, repo_root=ROOT)
        item = copy.deepcopy(good)
        item[field]["unknown"] = required
        assert module().blockers(item, repo_root=ROOT)
        item = copy.deepcopy(good)
        del item[field][next(iter(item[field]))]
        assert module().blockers(item, repo_root=ROOT)


def test_deployment_requires_separate_evidence():
    item = receipt()
    item["phase"] = "deployment_acceptance"
    assert module().blockers(item, repo_root=ROOT)


def test_unknown_top_level_field_rejected_even_with_review_stub(monkeypatch):
    monkeypatch.setattr(module(), "_evidence", lambda root, item: None)
    item = receipt()
    item["extra"] = True
    assert "receipt_fields_missing_or_unknown" in module().blockers(item, repo_root=ROOT)


def test_modified_source_inventory_rejected_before_git(tmp_path):
    p = tmp_path / module().INVENTORY
    p.parent.mkdir(parents=True)
    inventory = json.loads((ROOT / module().INVENTORY).read_text(encoding="utf-8"))
    inventory["files"][next(iter(inventory["files"]))] = "0" * 64
    p.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen_inventory_changed"):
        module()._frozen_source(tmp_path)


def test_extra_delta_and_legacy_policy_change_are_rejected(monkeypatch):
    old = json.loads(subprocess.check_output(["git", "show", SOURCE + ":docs/agent_playbooks/delivery_risk_policy.json"], cwd=ROOT))
    changed = copy.deepcopy(old)
    changed["donchian_history_readonly_delivery"] = module().contract()
    def fake_git(root, *args):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return b""
        if args[:2] == ("diff", "--name-only"):
            return b"quant_crypto/oms/runtime_store.py\n"
        if args[0] == "show" and args[1].startswith(SOURCE):
            return json.dumps(old).encode()
        if args[0] == "show":
            return json.dumps(changed).encode()
        raise AssertionError(args)
    monkeypatch.setattr(module(), "_git", fake_git)
    with pytest.raises(ValueError, match="unreviewed_post_source_delta"):
        module()._delta(ROOT, "a" * 40)
    changed["change_risks"]["observe_only"]["backend_restart_required"] = True
    def allowed_git(root, *args):
        if args[:2] == ("diff", "--name-only"):
            return b"docs/agent_playbooks/delivery_risk_policy.json\n"
        return fake_git(root, *args)
    monkeypatch.setattr(module(), "_git", allowed_git)
    with pytest.raises(ValueError, match="legacy_policy_or_fixed_contract_changed"):
        module()._delta(ROOT, "a" * 40)


@pytest.mark.parametrize("path", [
    "quant_crypto/oms/runtime_store.py", "frontend/src/App.tsx", "start-backend.cmd",
    ".codex/hooks.json", "tools/agent_governance/delivery_policy.py",
    ".agent/handoffs/other/event.json", "../docs/escape.md",
])
def test_post_source_delta_rejects_unrelated_paths(path):
    assert not module().allowed_delta(path)


def test_old_policy_and_v1_v3_contracts_unchanged():
    current = json.loads((ROOT / "docs/agent_playbooks/delivery_risk_policy.json").read_text(encoding="utf-8"))
    old = json.loads(subprocess.check_output(["git", "show", SOURCE + ":docs/agent_playbooks/delivery_risk_policy.json"], cwd=ROOT))
    new = current.copy()
    assert new.pop("donchian_history_readonly_delivery") == module().contract()
    assert new == old


def test_report_digest_and_reviewed_governance_are_committed(monkeypatch):
    monkeypatch.setattr(module(), "_git", lambda *args: b"actual report")
    with pytest.raises(ValueError, match="report_digest_mismatch"):
        module()._report(ROOT, {"path": module().REVIEW, "commit": "a" * 40, "sha256": "0" * 64}, module().REVIEW)
    monkeypatch.setattr(module(), "_git", lambda *args: b"tools/agent_governance/donchian_history_readonly_delivery.py\n")
    with pytest.raises(ValueError, match="reviewed_governance_or_source_changed"):
        module()._reports_only(ROOT, "a" * 40, "b" * 40)
