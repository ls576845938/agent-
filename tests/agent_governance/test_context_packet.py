from __future__ import annotations

import json
from pathlib import Path

import tools.agent_governance.context_packet as context_packet
from tools.agent_governance.context_packet import (
    REPO_ROOT,
    build_packet,
    canonical_role,
    catalog_hash,
    infer_role,
    infer_scopes,
    load_catalog,
    select_rules,
)
from tools.agent_governance.worktree_plan import build_plan, default_worktree_parent


def test_role_and_scope_inference() -> None:
    assert canonical_role("quant-architect") == "architect"
    assert canonical_role("explorer") == "all"
    assert canonical_role("integrator") == "integrator"
    assert canonical_role("cn-equity-developer") == "a_share_developer"
    assert infer_role("作为 A股程序员检查沪深回测") == "a_share_developer"
    assert infer_role("作为 BTC 程序员检查永续 OMS") == "btc_developer"
    assert {"cn_equity", "backtest"}.issubset(infer_scopes("检查 A股沪深回测"))
    assert {"btc", "execution"}.issubset(infer_scopes("检查 BTC 永续 OMS fill"))


def test_catalog_selection_is_role_and_scope_bounded() -> None:
    catalog = load_catalog()
    rules = select_rules(catalog, role="btc_developer", scopes={"btc", "execution"})
    ids = {rule["id"] for rule in rules}

    assert "BTC-PERP-001" in ids
    assert "BTC-OMS-001" in ids
    assert "ARCH-READONLY-001" not in ids
    assert "DATA-US-PIT-001" not in ids


def test_demo_transport_change_risk_excludes_promotion_incident_rules() -> None:
    catalog = load_catalog()
    rules = select_rules(
        catalog,
        role="btc_developer",
        scopes={"btc", "execution"},
        change_risk="demo_transport_hotfix",
    )
    ids = {rule["id"] for rule in rules}

    assert "QSYS-SECURITY-001" in ids
    assert "GOV-WORKTREE-001" in ids
    assert "QSYS-ARTIFACT-001" not in ids
    assert "GOV-OBJECTIVE-001" not in ids
    assert "GOV-ENGINEERING-CIRCUIT-001" not in ids


def test_context_packet_records_current_provenance() -> None:
    catalog = load_catalog()
    packet = build_packet(
        catalog=catalog,
        role="architect",
        scopes={"governance"},
        change_risk="governance_control",
        repo_root=REPO_ROOT,
    )

    assert packet["ruleset_version"] == "agent-governance-v2"
    assert packet["catalog_hash"] == catalog_hash(catalog)
    assert len(packet["catalog_hash"]) == 64
    assert packet["head"] != "unavailable"
    assert packet["dirty_count"] == -1
    assert packet["dirty_rechecked"] is False
    assert any(rule["id"] == "ARCH-READONLY-001" for rule in packet["rules"])
    assert any(rule["id"] == "GOV-STORAGE-001" for rule in packet["rules"])
    assert Path(packet["repo_root"]) == REPO_ROOT
    assert packet["change_risk"] == "governance_control"
    assert packet["delivery_requirements"][
        "independent_integrator_required"
    ] is True


def test_context_dirty_snapshot_is_explicit_and_source_scoped(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(context_packet, "current_branch_head", lambda _root: ("main", "a" * 40))
    monkeypatch.setattr(context_packet, "scoped_status", lambda _root: [" M quant_us/model.py"])

    snapshot = context_packet.git_snapshot(tmp_path, include_dirty=True)

    assert snapshot["dirty_rechecked"] is True
    assert snapshot["dirty_paths"] == ["quant_us/model.py"]


def test_writer_worktree_plan_stays_under_dedicated_parent(tmp_path: Path) -> None:
    plan = build_plan(
        role="btc_developer",
        task_id="btc-gate-42",
        base_ref="main",
        parent=tmp_path,
    )

    assert plan["branch"] == "agent/btc_developer/btc-gate-42"
    assert Path(plan["target"]).parent == tmp_path.resolve()
    assert plan["base_ref"] == "main"


def test_a_share_writer_worktree_plan_uses_role_namespace(tmp_path: Path) -> None:
    plan = build_plan(
        role="a_share_developer",
        task_id="a-share-development-v1",
        base_ref="main",
        parent=tmp_path,
    )

    assert plan["branch"] == "agent/a_share_developer/a-share-development-v1"
    assert Path(plan["target"]).name == "a_share_developer-a-share-development-v1"


def test_a_share_context_selects_cn_equity_rules() -> None:
    catalog = load_catalog()
    rules = select_rules(catalog, role="a_share_developer", scopes={"cn_equity", "backtest", "execution"})
    ids = {rule["id"] for rule in rules}

    assert {"CN-BOUNDARY-001", "CN-DATA-PIT-001", "CN-MARKET-001"}.issubset(ids)
    assert "BTC-PERP-001" not in ids
    assert "US-SERVICE-BOUNDARY-001" not in ids


def test_integrator_uses_shared_worktree_parent_from_any_worktree() -> None:
    parent = default_worktree_parent(REPO_ROOT)
    plan = build_plan(role="integrator", task_id="coordination-merge", base_ref="main", parent=parent)

    assert parent.name == "worktrees"
    assert parent.parent.name == "量化系统"
    assert Path(plan["target"]).parent == parent.resolve()
    assert plan["branch"] == "agent/integrator/coordination-merge"


def test_workflow_eval_cases_select_required_pitfalls() -> None:
    cases_path = REPO_ROOT / "tests" / "agent_governance" / "cases" / "agent_workflow_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    catalog = load_catalog()

    assert len(cases) >= 10
    for case in cases:
        selected = select_rules(
            catalog,
            role=case["role"],
            scopes=case["scopes"],
            change_risk=case.get("change_risk", "unclassified"),
        )
        selected_ids = {rule["id"] for rule in selected}
        assert set(case["required_rule_ids"]).issubset(selected_ids), case["id"]
        assert case["forbidden_capabilities"], case["id"]
