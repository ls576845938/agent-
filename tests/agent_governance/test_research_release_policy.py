from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tools.agent_governance import delivery_policy as policy
from tools.agent_governance.context_packet import build_packet, load_catalog


RISK = "research_readonly_release"
ROOT = Path(__file__).resolve().parents[2]


def evidence():
    requirements = policy.delivery_requirements(RISK)
    return {
        "profile": "research_readonly",
        "changed_capabilities": ["research_read_models", "research_frontend"],
        "changed_paths": ["backend/app/api/app_factory.py", "frontend/src/workspaces/research/QlibDecisionTrace.tsx"],
        "checks": {key: True for key in requirements["required_checks"]},
        "safety_flags": {key: False for key in requirements["required_false_flags"]},
    }


def test_research_release_is_not_a_trading_or_producer_fastpath():
    requirements = policy.delivery_requirements(RISK)
    assert requirements["independent_integrator_required"] is True
    assert requirements["promotion_artifact_rebuild_required"] is False
    assert requirements["backend_restart_required"] is True
    assert requirements["fast_forward_main_allowed"] is False
    assert requirements["backend_evidence_profile"] == "research_readonly"
    assert requirements["readiness_ceiling"] == "quality_checked"
    assert {"current_main_identity", "sealed_evidence_integrity", "canonical_browser_acceptance", "independent_review", "fresh_context"} <= set(requirements["required_checks"])
    assert policy.research_release_blockers(evidence()) == []


def test_no_old_risk_policy_is_weakened():
    baseline = json.loads(subprocess.check_output([
        "git", "show", "c1d11987d28f06bb0fe89b2c289e88d07522790d:docs/agent_playbooks/delivery_risk_policy.json",
    ], cwd=ROOT))
    current = policy.load_delivery_policy()
    assert current["default_change_risk"] == baseline["default_change_risk"] == "unclassified"
    for risk, requirements in baseline["change_risks"].items():
        assert current["change_risks"][risk] == requirements


def test_all_safety_flags_require_literal_false_and_checks_literal_true():
    good = evidence()
    for key in good["safety_flags"]:
        for value in (True, None, 0, "false"):
            altered = copy.deepcopy(good)
            altered["safety_flags"][key] = value
            assert policy.research_release_blockers(altered), (key, value)
        altered = copy.deepcopy(good)
        del altered["safety_flags"][key]
        assert policy.research_release_blockers(altered), key
    for key in good["checks"]:
        altered = copy.deepcopy(good)
        altered["checks"][key] = False
        assert policy.research_release_blockers(altered), key


@pytest.mark.parametrize("path", [
    "quant_crypto/risk/engine.py", "quant_shared/runtime/permissions.py",
    "quant_shared/strategy_runtime/context.py", "quant_us/live/ibkr.py",
    "backend/app/core/security.py", "scripts/start_backend_current_main.py",
    "docs/agent_playbooks/delivery_risk_policy.json", ".codex/hooks.json",
    "../quant_crypto/oms.py", "D:/private/file.py",
    "quant_crypto\\oms\\orders.py",
])
def test_protected_or_noncanonical_path_blocks_research_category(path):
    altered = evidence()
    altered["changed_paths"] = [path]
    assert policy.research_release_blockers(altered)


@pytest.mark.parametrize("capability", ["risk", "strategy_signal", "oms", "ledger", "promotion", "security", "unknown", "governance"])
def test_non_research_or_unknown_capability_blocks(capability):
    altered = evidence()
    altered["changed_capabilities"].append(capability)
    assert policy.research_release_blockers(altered)


@pytest.mark.parametrize("payload", [None, {}, {"profile": "demo_quasi_live"}])
def test_missing_or_wrong_release_evidence_blocks(payload):
    assert policy.research_release_blockers(payload)


def test_new_category_does_not_implicitly_reclassify_prompts():
    # The category is explicit CLI/ticket selection, not a free-text shortcut.
    for prompt in ("发布研究页面", "研究只读发布", "research_readonly_release", "研究只读发布并开启实盘", "研究只读发布并修改风控语义", "研究只读发布的治理修订"):
        assert policy.infer_change_risk(prompt) != RISK


def test_context_and_cli_share_risk_choices_and_keep_safety_rules():
    from tools.agent_governance import context_packet, team_context
    assert context_packet._parser().parse_args(["--change-risk", RISK]).change_risk == RISK
    assert team_context._parser().parse_args(["--change-risk", RISK]).change_risk == RISK
    packet = build_packet(catalog=load_catalog(), role="super_developer", scopes={"shared", "research", "data", "gate"}, change_risk=RISK, repo_root=ROOT)
    ids = {rule["id"] for rule in packet["rules"]}
    assert {"GOV-OBJECTIVE-001", "GOV-ENGINEERING-CIRCUIT-001", "GOV-PITFALL-001", "GOV-HANDOFF-001", "GOV-WORKTREE-001", "QSYS-GATE-001", "QSYS-SECURITY-001"} <= ids
    assert "QSYS-ARTIFACT-001" not in ids
    data_ids = {rule["id"] for rule in context_packet.select_rules(load_catalog(), role="data_steward", scopes={"data", "btc", "us_equity"}, change_risk=RISK)}
    assert {"DATA-FRESHNESS-001", "DATA-BTC-FINAL-001", "DATA-US-PIT-001"} <= data_ids
    rendered = context_packet.render_markdown(packet, max_chars=1800)
    assert "research_release_boundary: research_readonly" in rendered
    assert "demo/promotion/paper/live/private/order/transfer/withdraw=false" in rendered
    assert len(rendered) <= 1800


@pytest.mark.parametrize("field,value", [
    ("independent_integrator_required", False),
    ("required_checks", ["scoped_clean"]),
    ("required_false_flags", ["live"]),
    ("allowed_capabilities", ["live_execution"]),
])
def test_policy_loader_rejects_research_contract_loosening(tmp_path, field, value):
    payload = policy.load_delivery_policy()
    payload["change_risks"][RISK][field] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="research_release"):
        policy.load_delivery_policy(path)
