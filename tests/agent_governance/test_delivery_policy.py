from __future__ import annotations

from tools.agent_governance.delivery_policy import (
    CHANGE_RISKS,
    delivery_requirements,
    infer_change_risk,
    load_delivery_policy,
)


def test_delivery_policy_is_complete_and_unclassified_is_conservative() -> None:
    policy = load_delivery_policy()

    assert set(policy["change_risks"]) == set(CHANGE_RISKS)
    assert policy["default_change_risk"] == "unclassified"
    unclassified = delivery_requirements("unclassified", policy=policy)
    assert unclassified["independent_integrator_required"] is True
    assert unclassified["promotion_artifact_rebuild_required"] is True
    assert unclassified["fast_forward_main_allowed"] is False


def test_demo_transport_hotfix_is_delivery_fastpath_not_safety_fastpath() -> None:
    requirements = delivery_requirements("demo_transport_hotfix")

    assert requirements["independent_integrator_required"] is False
    assert requirements["promotion_artifact_rebuild_required"] is False
    assert requirements["backend_restart_required"] is True
    assert requirements["fast_forward_main_allowed"] is True
    assert {
        "strategy",
        "risk",
        "order_construction",
        "private_ws_reconciliation",
        "ledger",
        "security",
        "live_permissions",
    }.issubset(requirements["forbidden_changes"])


def test_prompt_inference_prefers_demo_transport_over_negative_live_text() -> None:
    assert infer_change_risk(
        "修 Demo public tail stale seed；仍禁止实盘、转账和提现"
    ) == "demo_transport_hotfix"
    assert infer_change_risk(
        "BTC-OKX-DEMO-PUBLIC-TAIL-STALE-SEED-02："
        "公共 REST tail merge；仍禁止实盘"
    ) == "demo_transport_hotfix"
    assert infer_change_risk("先修正交付制度和治理") == "governance_control"
    assert infer_change_risk("普通缺陷，信息不足") == "unclassified"
