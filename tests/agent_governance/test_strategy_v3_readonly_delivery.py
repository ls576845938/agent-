"""This single frozen V3 delivery must not broaden V1 or trading authority."""
from __future__ import annotations

import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    return importlib.import_module("tools.agent_governance.strategy_v3_readonly_delivery")


def _receipt():
    contract = _module().contract()
    return {
        "schema_version": "strategy_v3_readonly_receipt_v1",
        "ticket_id": contract["ticket_id"],
        "phase": "source_review",
        "source_commit": contract["source_commit"],
        "source_change_risk": "demo_execution_semantics",
        "deployment_profile": "research_readonly",
        "evidence_kind": "offline_execution",
        "checks": {name: True for name in contract["required_source_checks"]},
        "safety_flags": {name: False for name in contract["required_false_flags"]},
    }


def test_fixed_source_can_be_reviewed_without_claiming_deployment(monkeypatch):
    # Only schema/frozen-source test; not a fabricated independent approval.
    monkeypatch.setattr(_module(), "_evidence", lambda root, receipt: None)
    assert _module().blockers(_receipt(), repo_root=ROOT) == []


def test_source_booleans_do_not_replace_committed_independent_review():
    assert _module().blockers(_receipt(), repo_root=ROOT)


def test_unknown_flags_and_checks_fail_closed():
    for field in ("checks", "safety_flags"):
        receipt = _receipt()
        receipt[field]["unknown"] = False
        assert _module().blockers(receipt, repo_root=ROOT)


def test_frozen_source_and_new_governance_are_separate():
    assert _module().allowed_delta("docs/agent_playbooks/strategy_v3_readonly_delivery.md")
    assert not _module().allowed_delta(".agent/handoffs/other/event.json")
    assert not _module().allowed_delta(".agent/handoffs/V3-READONLY-DELIVERY-20260920/nested/event.json")


def test_after_review_even_allowed_governance_code_cannot_change(monkeypatch):
    monkeypatch.setattr(_module(), "_git", lambda *args: b"tools/agent_governance/strategy_v3_readonly_delivery.py\n")
    with pytest.raises(ValueError, match="reviewed_governance_or_source_changed"):
        _module()._reports_only(ROOT, "a" * 40, "b" * 40)


def test_review_report_raw_digest_is_required(monkeypatch):
    monkeypatch.setattr(_module(), "_git", lambda *args: b"actual report")
    with pytest.raises(ValueError, match="report_digest_mismatch"):
        _module()._report(ROOT, {"path": _module().REVIEW, "commit": "a" * 40,
                               "sha256": "0" * 64}, _module().REVIEW)


@pytest.mark.parametrize("field,value", [
    ("source_commit", "a" * 40), ("ticket_id", "V4"),
    ("source_change_risk", "research_readonly_release"),
    ("deployment_profile", "demo_quasi_live"), ("evidence_kind", "runtime_execution"),
])
def test_wrong_identity_or_profile_is_rejected(field, value):
    receipt = _receipt()
    receipt[field] = value
    assert _module().blockers(receipt, repo_root=ROOT)


def test_permissions_and_checks_require_literal_booleans():
    good = _receipt()
    for name in good["safety_flags"]:
        for bad in (True, 0, "false", None):
            receipt = copy.deepcopy(good)
            receipt["safety_flags"][name] = bad
            assert _module().blockers(receipt, repo_root=ROOT)
    for name in good["checks"]:
        receipt = copy.deepcopy(good)
        receipt["checks"][name] = 1
        assert _module().blockers(receipt, repo_root=ROOT)


def test_deployment_cannot_be_claimed_with_source_receipt():
    receipt = _receipt()
    receipt["phase"] = "deployment_acceptance"
    assert _module().blockers(receipt, repo_root=ROOT)


@pytest.mark.parametrize("path", [
    "quant_crypto/application/qlib_offline_replay.py", "frontend/src/App.tsx",
    "start-backend.cmd", ".codex/hooks.json", "../docs/escape.md",
])
def test_unreviewed_deployment_delta_is_rejected(path):
    assert not _module().allowed_delta(path)


def test_legacy_rules_and_v1_contract_are_unchanged():
    current = json.loads((ROOT / "docs/agent_playbooks/delivery_risk_policy.json").read_text(encoding="utf-8"))
    original = json.loads(subprocess.check_output([
        "git", "show", "aca55c90d82b327800e473774e22dbbeac69bd90:docs/agent_playbooks/delivery_risk_policy.json"
    ], cwd=ROOT))
    assert current["change_risks"] == original["change_risks"]
    assert current["strategy_v1_readonly_delivery"] == original["strategy_v1_readonly_delivery"]
    assert _module().contract()["source_commit"] == "aca55c90d82b327800e473774e22dbbeac69bd90"
