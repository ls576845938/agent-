from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tools.agent_governance import delivery_policy as policy


ROOT = Path(__file__).resolve().parents[2]
TICKET_ID = "STRATEGY-V1-DONCHIAN-OFFLINE"


def _source_review_receipt() -> dict[str, object]:
    contract = policy.strategy_v1_readonly_delivery_contract()
    source_paths = [
        "quant_crypto/application/donchian_offline_adapter.py",
        "tests/contracts/test_donchian_offline_vertical_slice.py",
    ]
    return {
        "schema_version": contract["receipt_schema_version"],
        "ticket_id": TICKET_ID,
        "phase": "source_review",
        "source_change_risk": "demo_execution_semantics",
        "deployment_profile": "research_readonly",
        "evidence_kind": "offline_execution",
        "touch_set_approval_role": "architect",
        "source_commit": "a" * 40,
        "v0_baseline_commit": "b" * 40,
        "source_review_commit": "d" * 40,
        "source_handoff_commit": "e" * 40,
        "source_handoff_path": (
            ".agent/handoffs/STRATEGY-V1-DONCHIAN-OFFLINE/"
            "published-strategy-v1-donchian-offline.json"
        ),
        "source_handoff_sha256": "f" * 64,
        "source_review_report_path": (
            "docs/operations/strategy-v1-donchian-offline-review.md"
        ),
        "source_review_report_sha256": "c" * 64,
        "approved_source_touch_set_artifact_commit": "1" * 40,
        "approved_source_touch_set_artifact_path": (
            "docs/architecture/strategy-v1-donchian-offline-touch-set.json"
        ),
        "approved_source_touch_set_artifact_sha256": "2" * 64,
        "approved_source_touch_set": source_paths,
        "source_changed_paths": list(source_paths),
        "source_changed_capabilities": [
            "donchian_offline_input_injection",
            "deterministic_decision_evidence_linkage",
            "tests",
        ],
        "source_checks": {
            key: True for key in contract["required_source_checks"]
        },
        "safety_flags": {
            key: False for key in contract["required_false_flags"]
        },
    }


def _deployment_receipt() -> dict[str, object]:
    contract = policy.strategy_v1_readonly_delivery_contract()
    receipt = _source_review_receipt()
    receipt.update(
        {
            "phase": "deployment_acceptance",
            "deployment_commit": "3" * 40,
            "deployment_handoff_commit": "4" * 40,
            "deployment_handoff_path": (
                ".agent/handoffs/INTEGRATE-STRATEGY-V1-DONCHIAN-OFFLINE/"
                "integrated-strategy-v1-donchian-offline.json"
            ),
            "deployment_handoff_sha256": "5" * 64,
            "deployment_review_commit": "6" * 40,
            "deployment_review_report_path": (
                "docs/operations/strategy-v1-donchian-offline-deployment-review.md"
            ),
            "deployment_review_report_sha256": "7" * 64,
            "reviewed_source_commit": "a" * 40,
            "reviewed_source_review_commit": "d" * 40,
            "reviewed_source_touch_set_artifact_sha256": "2" * 64,
            "deployment_changed_paths": [
                "backend/app/api/offline_execution_evidence.py",
                "frontend/src/workspaces/research/OfflineDecisionTrace.tsx",
            ],
            "deployment_changed_capabilities": [
                "offline_execution_read_models",
                "research_frontend",
            ],
            "deployment_checks": {
                key: True for key in contract["required_deployment_checks"]
            },
        }
    )
    return receipt


def test_contract_is_separate_from_change_risks_and_preserves_old_entries() -> None:
    baseline = json.loads(
        subprocess.check_output(
            [
                "git",
                "show",
                "b920d131e41ecbfe7f76f0709affbe22c8b35f5e:docs/agent_playbooks/delivery_risk_policy.json",
            ],
            cwd=ROOT,
        )
    )
    loaded = policy.load_delivery_policy()

    assert set(loaded["change_risks"]) == set(policy.CHANGE_RISKS)
    assert loaded["change_risks"] == baseline["change_risks"]
    assert loaded["default_change_risk"] == "unclassified"
    assert "strategy_v1_readonly_delivery" not in policy.CHANGE_RISKS
    assert policy.infer_change_risk("V1 Donchian 离线只读发布") == "unclassified"


@pytest.mark.parametrize("payload", [None, {}, {"phase": "source_review"}])
def test_missing_receipt_fails_closed(payload: object) -> None:
    assert policy.strategy_v1_readonly_delivery_blockers(payload)


def test_contract_keeps_high_risk_source_review_and_readonly_deployment_distinct() -> None:
    contract = policy.strategy_v1_readonly_delivery_contract()

    assert contract["ticket_id"] == TICKET_ID
    assert contract["source_change_risk"] == "demo_execution_semantics"
    assert contract["deployment_profile"] == "research_readonly"
    assert contract["evidence_kind"] == "offline_execution"
    assert contract["independent_integrator_required"] is True
    assert contract["promotion_artifact_rebuild_required"] is False
    assert contract["readiness_ceiling"] == "quality_checked"
    assert set(
        policy.delivery_requirements("demo_execution_semantics")["requirements"]
    ) <= set(contract["required_source_checks"])
    assert {
        "v0_baseline_verified",
        "failure_first_regression",
        "recovery_verified",
        "duplicate_fill_dedup_verified",
        "ledger_replay_consistent",
        "independent_source_review",
        "independent_integrator",
    } <= set(contract["required_source_checks"])
    assert {
        "fresh_context_after_governance_activation",
        "source_review_receipt_verified",
        "offline_execution_type_verified",
        "no_similar_record_fallback",
        "independent_deployment_review",
        "current_main_identity",
        "canonical_browser_acceptance",
        "rollback_point_verified",
    } <= set(contract["required_deployment_checks"])


def test_source_review_can_complete_without_claiming_page_publication() -> None:
    receipt = _source_review_receipt()

    assert "deployment_checks" not in receipt
    assert policy.strategy_v1_readonly_delivery_blockers(receipt) == []

    altered = copy.deepcopy(receipt)
    altered["deployment_checks"] = {}
    assert "strategy_v1_source_phase_contains_deployment_claims" in (
        policy.strategy_v1_readonly_delivery_blockers(altered)
    )


def test_deployment_acceptance_requires_source_review_and_browser_evidence() -> None:
    receipt = _deployment_receipt()
    assert policy.strategy_v1_readonly_delivery_blockers(receipt) == []

    altered = copy.deepcopy(receipt)
    del altered["deployment_checks"]["canonical_browser_acceptance"]
    assert (
        "strategy_v1_deployment_checks_invalid:canonical_browser_acceptance"
        in policy.strategy_v1_readonly_delivery_blockers(altered)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("ticket_id", "STRATEGY-V1-OTHER"),
        ("source_change_risk", "research_readonly_release"),
        ("deployment_profile", "demo_quasi_live"),
        ("evidence_kind", "runtime_execution"),
        ("touch_set_approval_role", "producer"),
        ("phase", "published"),
    ],
)
def test_identity_boundary_mismatch_fails_closed(field: str, value: object) -> None:
    receipt = _source_review_receipt()
    receipt[field] = value
    assert policy.strategy_v1_readonly_delivery_blockers(receipt)


def test_source_checks_require_literal_true() -> None:
    receipt = _source_review_receipt()
    for key in list(receipt["source_checks"]):
        for value in (False, None, 1, "true"):
            altered = copy.deepcopy(receipt)
            altered["source_checks"][key] = value
            assert policy.strategy_v1_readonly_delivery_blockers(altered), (
                key,
                value,
            )


def test_all_safety_flags_require_literal_false_in_both_phases() -> None:
    for good in (_source_review_receipt(), _deployment_receipt()):
        for key in list(good["safety_flags"]):
            for value in (True, None, 0, "false"):
                altered = copy.deepcopy(good)
                altered["safety_flags"][key] = value
                assert policy.strategy_v1_readonly_delivery_blockers(altered), (
                    key,
                    value,
                )
        altered = copy.deepcopy(good)
        altered["safety_flags"]["unexpected_flag"] = True
        assert "strategy_v1_unsafe_extra_flag" in (
            policy.strategy_v1_readonly_delivery_blockers(altered)
        )


@pytest.mark.parametrize(
    "path",
    [
        "../quant_crypto/oms.py",
        "D:/private/file.py",
        "quant_crypto\\oms\\orders.py",
        "/absolute/file.py",
        "scripts/start_backend_current_main.ps1",
        "backend/app/core/security.py",
        ".codex/hooks.json",
    ],
)
def test_source_path_is_exactly_reviewed_canonical_and_not_protected(path: str) -> None:
    receipt = _source_review_receipt()
    receipt["source_changed_paths"] = [path]
    receipt["approved_source_touch_set"] = [path]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt)


def test_source_diff_must_equal_the_independently_approved_touch_set() -> None:
    receipt = _source_review_receipt()
    receipt["source_changed_paths"].append("quant_crypto/oms/hidden.py")
    assert "strategy_v1_source_touch_set_mismatch" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )


def test_source_paths_must_remain_inside_fixed_v1_boundaries() -> None:
    receipt = _source_review_receipt()
    receipt["source_changed_paths"] = ["README.md"]
    receipt["approved_source_touch_set"] = ["README.md"]
    assert "strategy_v1_source_path_outside_fixed_boundary" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )


def test_only_the_exact_shared_decision_envelope_is_admitted() -> None:
    receipt = _source_review_receipt()
    exact_path = "quant_shared/strategy_runtime/decision_envelope.py"
    receipt["source_changed_paths"] = [exact_path]
    receipt["approved_source_touch_set"] = [exact_path]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt) == []


@pytest.mark.parametrize(
    "path",
    [
        "quant_shared/strategy_runtime/models.py",
        "quant_shared/strategy_runtime/decision_envelope_extra.py",
        "quant_shared/runtime/permissions.py",
    ],
)
def test_adjacent_shared_runtime_paths_remain_rejected(path: str) -> None:
    receipt = _source_review_receipt()
    receipt["source_changed_paths"] = [path]
    receipt["approved_source_touch_set"] = [path]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt)


def test_only_exact_portfolio_decision_path_and_reduce_source_binding_are_admitted() -> None:
    receipt = _source_review_receipt()
    exact_path = "quant_crypto/portfolio/decision.py"
    receipt["source_changed_paths"] = [exact_path]
    receipt["approved_source_touch_set"] = [exact_path]
    receipt["source_changed_capabilities"] = [
        "reduce_only_signal_forecast_source_identity_binding"
    ]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt) == []


@pytest.mark.parametrize(
    "path",
    [
        "quant_crypto/portfolio/forecast.py",
        "quant_crypto/portfolio/order_intent.py",
        "quant_crypto/portfolio/decision_extra.py",
        "quant_crypto/risk/kernel.py",
        "quant_shared/runtime/permissions.py",
    ],
)
def test_adjacent_portfolio_risk_and_permissions_paths_remain_rejected(
    path: str,
) -> None:
    receipt = _source_review_receipt()
    receipt["source_changed_paths"] = [path]
    receipt["approved_source_touch_set"] = [path]
    receipt["source_changed_capabilities"] = [
        "reduce_only_signal_forecast_source_identity_binding"
    ]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt)


def test_control_plane_admits_only_reduce_only_runtime_action_projection() -> None:
    receipt = _source_review_receipt()
    path = "quant_crypto/runtime/control_plane.py"
    receipt["source_changed_paths"] = [path]
    receipt["approved_source_touch_set"] = [path]
    receipt["source_changed_capabilities"] = [
        "reduce_only_runtime_action_projection"
    ]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt) == []


@pytest.mark.parametrize(
    "capability",
    [
        "cancel_only_semantics",
        "shared_permission_evaluator",
        "account_gate",
        "risk_gate",
        "connection_gate",
        "ledger_gate",
        "runtime_permissions",
    ],
)
def test_control_plane_exception_does_not_admit_other_runtime_semantics(
    capability: str,
) -> None:
    receipt = _source_review_receipt()
    path = "quant_crypto/runtime/control_plane.py"
    receipt["source_changed_paths"] = [path]
    receipt["approved_source_touch_set"] = [path]
    receipt["source_changed_capabilities"] = [capability]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt)


def test_source_review_binds_distinct_commits_handoff_and_touch_set_artifact() -> None:
    receipt = _source_review_receipt()
    receipt["source_review_commit"] = receipt["source_commit"]
    assert "strategy_v1_source_review_not_independent" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )

    for field in (
        "source_handoff_commit",
        "source_handoff_path",
        "source_handoff_sha256",
        "approved_source_touch_set_artifact_commit",
        "approved_source_touch_set_artifact_path",
        "approved_source_touch_set_artifact_sha256",
        "source_review_report_path",
        "source_review_report_sha256",
    ):
        altered = copy.deepcopy(_source_review_receipt())
        del altered[field]
        assert policy.strategy_v1_readonly_delivery_blockers(altered), field


@pytest.mark.parametrize(
    "capability",
    [
        "strategy_signal",
        "position",
        "exit",
        "risk",
        "oms",
        "protection",
        "ledger_semantics",
        "broker_transport",
        "private_ws_reconciliation",
        "trading_permissions",
        "automatic_runtime_worker",
        "unknown",
    ],
)
def test_source_capability_outside_offline_injection_scope_is_rejected(
    capability: str,
) -> None:
    receipt = _source_review_receipt()
    receipt["source_changed_capabilities"].append(capability)
    assert "strategy_v1_source_capability_outside_scope" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )


@pytest.mark.parametrize(
    "path",
    [
        "quant_crypto/application/runtime.py",
        "quant_shared/runtime/permissions.py",
        "tools/agent_governance/delivery_policy.py",
        "scripts/start_frontend_current_main.ps1",
    ],
)
def test_deployment_paths_cannot_reopen_execution_or_governance(path: str) -> None:
    receipt = _deployment_receipt()
    receipt["deployment_changed_paths"] = [path]
    assert policy.strategy_v1_readonly_delivery_blockers(receipt)


@pytest.mark.parametrize(
    "capability",
    ["risk", "oms", "ledger", "promotion", "runtime_worker", "unknown"],
)
def test_deployment_capabilities_are_readonly_only(capability: str) -> None:
    receipt = _deployment_receipt()
    receipt["deployment_changed_capabilities"].append(capability)
    assert "strategy_v1_deployment_capability_outside_scope" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )


def test_deployment_is_bound_to_the_reviewed_source_and_separate_delta() -> None:
    receipt = _deployment_receipt()
    receipt["reviewed_source_commit"] = "8" * 40
    assert "strategy_v1_deployment_source_commit_mismatch" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )

    receipt = _deployment_receipt()
    receipt["reviewed_source_review_commit"] = "8" * 40
    assert "strategy_v1_deployment_review_commit_mismatch" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )

    receipt = _deployment_receipt()
    receipt["reviewed_source_touch_set_artifact_sha256"] = "8" * 64
    assert "strategy_v1_deployment_touch_set_binding_mismatch" in (
        policy.strategy_v1_readonly_delivery_blockers(receipt)
    )

    for field in (
        "deployment_handoff_commit",
        "deployment_handoff_path",
        "deployment_handoff_sha256",
        "deployment_review_commit",
        "deployment_review_report_path",
        "deployment_review_report_sha256",
    ):
        altered = copy.deepcopy(_deployment_receipt())
        del altered[field]
        assert policy.strategy_v1_readonly_delivery_blockers(altered), field


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_change_risk", "research_readonly_release"),
        ("deployment_profile", "demo_quasi_live"),
        ("ticket_id", "STRATEGY-V1-OTHER"),
        ("required_false_flags", ["live"]),
        ("allowed_source_capabilities", ["risk"]),
        ("allowed_source_path_prefixes", ["README.md"]),
        ("allowed_source_paths", ["quant_shared/strategy_runtime/models.py"]),
        ("protected_source_path_prefixes", ["README.md"]),
        ("protected_deployment_path_prefixes", ["README.md"]),
    ],
)
def test_loader_rejects_contract_loosening(
    tmp_path: Path, field: str, value: object
) -> None:
    payload = policy.load_delivery_policy()
    payload["strategy_v1_readonly_delivery"][field] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="strategy_v1_readonly_delivery"):
        policy.load_delivery_policy(path)
