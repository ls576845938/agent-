from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = (
    REPO_ROOT
    / "docs"
    / "agent_playbooks"
    / "delivery_risk_policy.json"
)

CHANGE_RISKS = (
    "observe_only",
    "demo_transport_hotfix",
    "demo_execution_semantics",
    "promotion_evidence",
    "live_execution",
    "governance_control",
    "research_readonly_release",
    "unclassified",
)

_STRATEGY_V1_CONTRACT_KEY = "strategy_v1_readonly_delivery"
_STRATEGY_V1_FIXED = {
    "schema_version": "strategy_v1_readonly_delivery_contract_v1",
    "receipt_schema_version": "strategy_v1_readonly_delivery_receipt_v1",
    "ticket_id": "STRATEGY-V1-DONCHIAN-OFFLINE",
    "source_change_risk": "demo_execution_semantics",
    "deployment_profile": "research_readonly",
    "evidence_kind": "offline_execution",
    "touch_set_approval_role": "architect",
    "readiness_ceiling": "quality_checked",
    "independent_integrator_required": True,
    "promotion_artifact_rebuild_required": False,
    "backend_restart_required": True,
}
_STRATEGY_V1_REQUIRED_LISTS = {
    "allowed_phases": {"source_review", "deployment_acceptance"},
    "required_source_checks": {
        "dedicated_sparse_producer",
        "scoped_dirty",
        "scoped_clean",
        "failure_first_regression",
        "demo_safety_attestation",
        "architect_touch_set_artifact_verified",
        "source_commit_verified",
        "source_handoff_commit_verified",
        "source_review_commit_verified",
        "source_review_report_verified",
        "v0_baseline_verified",
        "original_donchian_behavior_unchanged",
        "execution_authority_chain_reused",
        "recovery_verified",
        "duplicate_event_dedup_verified",
        "duplicate_fill_dedup_verified",
        "ledger_replay_consistent",
        "deterministic_decision_evidence_linkage",
        "append_only_handoff",
        "committed_handoff_verified",
        "exact_commit_and_touch_set",
        "no_network_private_or_transport_change",
        "independent_source_review",
        "independent_integrator",
    },
    "required_deployment_checks": {
        "fresh_context_after_governance_activation",
        "source_review_receipt_verified",
        "sealed_offline_evidence_integrity",
        "exact_source_versions_and_staleness",
        "readonly_evidence_discovery",
        "offline_execution_type_verified",
        "no_similar_record_fallback",
        "research_readonly_controls_disabled",
        "committed_deployment_handoff_verified",
        "independent_deployment_review",
        "deployment_contains_reviewed_source_commit",
        "reviewed_source_files_unchanged",
        "deployment_delta_is_readonly_only",
        "deployment_handoff_verified",
        "current_main_identity",
        "canonical_browser_acceptance",
        "rollback_point_verified",
    },
    "required_false_flags": {
        "demo_control_enabled",
        "promotion",
        "paper",
        "live",
        "private",
        "order",
        "real_order",
        "transfer",
        "withdraw",
        "execution_permission",
        "runtime_worker_enabled",
        "runtime_observed",
    },
    "allowed_source_capabilities": {
        "donchian_offline_input_injection",
        "deterministic_offline_clock_injection",
        "deterministic_decision_evidence_linkage",
        "sealed_offline_execution_evidence",
        "offline_runtime_state_projection",
        "persistent_ledger_replay_verification",
        "reduce_only_signal_forecast_source_identity_binding",
        "reduce_only_runtime_action_projection",
        "documentation",
        "tests",
    },
    "forbidden_source_changes": {
        "strategy_parameters",
        "strategy_signal_economics",
        "position_economics",
        "quantity_economics",
        "exit_economics",
        "risk_semantics",
        "oms_semantics",
        "protection_semantics",
        "ledger_semantics",
        "broker_transport",
        "private_ws_reconciliation",
        "security",
        "trading_permissions",
        "automatic_runtime_worker",
        "demo_activation",
        "paper_activation",
        "live_activation",
    },
    "allowed_deployment_capabilities": {
        "offline_execution_read_models",
        "research_frontend",
        "offline_execution_evidence",
        "documentation",
        "tests",
    },
    "protected_source_path_prefixes": {
        "backend/app/core/security",
        "integrations/",
        "quant_shared/runtime/permissions",
        "scripts/start_backend_current_main",
        "scripts/start_frontend_current_main",
        "start-backend.cmd",
        "start-frontend.cmd",
        ".codex/",
        ".agents/",
        "AGENTS.md",
    },
    "allowed_source_path_prefixes": {
        "quant_crypto/application/",
        "quant_crypto/monitoring/",
        "quant_crypto/oms/",
        "quant_crypto/runtime/",
        "tests/",
        "docs/architecture/",
        "docs/operations/",
    },
    "allowed_source_paths": {
        "quant_shared/strategy_runtime/decision_envelope.py",
        "quant_crypto/portfolio/decision.py",
    },
    "protected_deployment_path_prefixes": {
        "quant_crypto/",
        "quant_shared/runtime/",
        "quant_shared/strategy_runtime/",
        "quant_us/live/",
        "quant_us/oms/",
        "quant_us/risk/",
        "quant_cn/execution/",
        "backend/app/services/btc_demo_runtime.py",
        "backend/app/core/security",
        "scripts/start_backend_current_main",
        "scripts/start_frontend_current_main",
        "start-backend.cmd",
        "start-frontend.cmd",
        ".codex/",
        ".agents/",
        "AGENTS.md",
        "tools/agent_governance/",
        "docs/agent_playbooks/",
    },
}

_DEMO_TRANSPORT_TERMS = (
    "demo parser",
    "demo transport",
    "demo candle",
    "demo public tail",
    "public rest tail",
    "stale seed",
    "模拟盘解析",
    "模拟盘传输",
    "模拟盘 k线",
    "模拟盘k线",
    "公共 tail",
    "公共tail",
    "陈旧种子",
)
_GOVERNANCE_TERMS = (
    "交付制度",
    "治理",
    "governance",
    "delivery policy",
    "context packet",
    "team context",
    "pitfall catalog",
)
_LIVE_TERMS = (
    "live execution",
    "实盘执行",
    "开启实盘",
    "live order",
)
_PROMOTION_TERMS = (
    "promotion evidence",
    "promotion gate",
    "晋级证据",
    "正式晋级",
)
_DEMO_EXECUTION_TERMS = (
    "order construction",
    "private ws reconciliation",
    "ledger semantics",
    "risk semantics",
    "订单构造",
    "私有 ws 对账",
    "账本语义",
    "风控语义",
)
_OBSERVE_TERMS = (
    "observe only",
    "observe-only",
    "只观察",
    "只读诊断",
)


def load_delivery_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("delivery_risk_policy_invalid")
    risks = payload.get("change_risks")
    if not isinstance(risks, dict) or set(risks) != set(CHANGE_RISKS):
        raise ValueError("delivery_risk_policy_change_risks_invalid")
    if payload.get("default_change_risk") != "unclassified":
        raise ValueError("delivery_risk_policy_default_must_be_unclassified")
    for name, requirements in risks.items():
        if not isinstance(requirements, dict):
            raise ValueError(f"delivery_risk_policy_entry_invalid:{name}")
        for field in (
            "independent_integrator_required",
            "promotion_artifact_rebuild_required",
            "backend_restart_required",
            "fast_forward_main_allowed",
        ):
            if not isinstance(requirements.get(field), bool):
                raise ValueError(
                    f"delivery_risk_policy_boolean_invalid:{name}:{field}"
                )
    research = risks["research_readonly_release"]
    fixed = {
        "independent_integrator_required": True,
        "promotion_artifact_rebuild_required": False,
        "backend_restart_required": True,
        "fast_forward_main_allowed": False,
        "backend_evidence_profile": "research_readonly",
        "readiness_ceiling": "quality_checked",
    }
    if any(type(research.get(key)) is not type(value) or research.get(key) != value for key, value in fixed.items()):
        raise ValueError("research_release_fixed_boundary_invalid")
    for key in ("requirements", "allowed_capabilities", "forbidden_changes", "protected_path_prefixes", "required_checks", "required_false_flags"):
        values = research.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
            raise ValueError(f"research_release_list_invalid:{key}")
    if set(research["allowed_capabilities"]) & set(research["forbidden_changes"]):
        raise ValueError("research_release_capability_boundary_invalid")
    minimum = {
        "required_checks": {
            "explicit_user_authorization", "fresh_context", "scoped_clean", "committed_handoff_verified",
            "independent_review", "execution_semantics_unchanged", "sealed_evidence_integrity",
            "exact_source_versions_and_staleness", "immutable_data_resolver", "readonly_data_discovery",
            "current_main_identity", "canonical_browser_acceptance", "rollback_point_verified",
        },
        "required_false_flags": {
            "demo_control_enabled", "promotion", "paper", "live", "private", "order",
            "real_order", "transfer", "withdraw", "execution_permission", "runtime_observed",
        },
    }
    if any(not values.issubset(research[key]) for key, values in minimum.items()):
        raise ValueError("research_release_required_evidence_incomplete")
    if not set(research["allowed_capabilities"]).issubset({"research_producers", "research_read_models", "research_frontend", "research_evidence", "documentation", "tests"}):
        raise ValueError("research_release_capability_boundary_invalid")
    _validate_strategy_v1_readonly_delivery_contract(payload)
    return payload


def _validate_strategy_v1_readonly_delivery_contract(
    payload: Mapping[str, Any],
) -> None:
    contract = payload.get(_STRATEGY_V1_CONTRACT_KEY)
    if not isinstance(contract, Mapping):
        raise ValueError("strategy_v1_readonly_delivery_contract_missing")
    if any(
        type(contract.get(key)) is not type(value) or contract.get(key) != value
        for key, value in _STRATEGY_V1_FIXED.items()
    ):
        raise ValueError("strategy_v1_readonly_delivery_fixed_boundary_invalid")
    for key, expected in _STRATEGY_V1_REQUIRED_LISTS.items():
        values = contract.get(key)
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value for value in values)
            or len(values) != len(set(values))
            or set(values) != expected
        ):
            raise ValueError(f"strategy_v1_readonly_delivery_list_invalid:{key}")
    source_policy = payload["change_risks"][contract["source_change_risk"]]
    if (
        not set(source_policy["requirements"]).issubset(
            set(contract["required_source_checks"])
        )
        or source_policy["independent_integrator_required"] is not True
    ):
        raise ValueError(
            "strategy_v1_readonly_delivery_source_requirements_not_preserved"
        )
    if contract.get("documentation") != (
        "docs/agent_playbooks/strategy_v1_readonly_delivery.md"
    ):
        raise ValueError("strategy_v1_readonly_delivery_documentation_invalid")


def strategy_v1_readonly_delivery_contract(
    *, policy: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return the explicit V1 source-review/read-only-deployment contract.

    This contract is deliberately not a change-risk category. The source diff
    remains ``demo_execution_semantics`` and therefore keeps all existing
    conditional guardrails. The deployment profile remains read-only.
    """
    selected = policy or load_delivery_policy()
    _validate_strategy_v1_readonly_delivery_contract(selected)
    return dict(selected[_STRATEGY_V1_CONTRACT_KEY])


def _canonical_relative_paths(
    value: object,
    *,
    prefix: str,
) -> tuple[list[str], list[str]]:
    if not isinstance(value, list) or not value:
        return [], [f"{prefix}_paths_missing_or_duplicate"]
    if any(not isinstance(path, str) for path in value):
        return [], [f"{prefix}_path_noncanonical"]
    if len(value) != len(set(value)):
        return [], [f"{prefix}_paths_missing_or_duplicate"]
    paths: list[str] = []
    blockers: list[str] = []
    for path in value:
        if not _is_canonical_relative_path(path):
            blockers.append(f"{prefix}_path_noncanonical")
            continue
        paths.append(path)
    return paths, blockers


def _is_canonical_relative_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and ":" not in value
        and "\\" not in value
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


def _validate_literal_checks(
    observed: object,
    required_keys: list[str],
    *,
    prefix: str,
) -> list[str]:
    if not isinstance(observed, Mapping):
        return [f"{prefix}_missing"]
    blockers = [
        f"{prefix}_invalid:{key}"
        for key in required_keys
        if observed.get(key) is not True
    ]
    if any(key not in required_keys for key in observed):
        blockers.append(f"{prefix}_unknown")
    return blockers


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def strategy_v1_readonly_delivery_blockers(
    evidence: Mapping[str, Any] | None,
) -> list[str]:
    """Validate V1 review/publication receipts without granting permissions.

    ``source_review`` proves only that the committed high-risk offline source
    diff is eligible for integration. ``deployment_acceptance`` additionally
    proves canonical current-main read-only publication and browser acceptance.
    The validator does not inspect runtime evidence or mutate state, and cannot
    launch a worker, service, broker client, or permission path.
    """
    contract = strategy_v1_readonly_delivery_contract()
    if not isinstance(evidence, Mapping):
        return ["strategy_v1_delivery_evidence_missing"]

    blockers: list[str] = []
    identity_fields = {
        "schema_version": contract["receipt_schema_version"],
        "ticket_id": contract["ticket_id"],
        "source_change_risk": contract["source_change_risk"],
        "deployment_profile": contract["deployment_profile"],
        "evidence_kind": contract["evidence_kind"],
        "touch_set_approval_role": contract["touch_set_approval_role"],
    }
    for key, expected in identity_fields.items():
        if type(evidence.get(key)) is not type(expected) or evidence.get(key) != expected:
            blockers.append(f"strategy_v1_identity_invalid:{key}")

    phase = evidence.get("phase")
    if phase not in contract["allowed_phases"]:
        blockers.append("strategy_v1_phase_invalid")

    for field, length in (
        ("source_commit", 40),
        ("v0_baseline_commit", 40),
        ("source_review_commit", 40),
        ("source_handoff_commit", 40),
        ("approved_source_touch_set_artifact_commit", 40),
        ("source_review_report_sha256", 64),
        ("source_handoff_sha256", 64),
        ("approved_source_touch_set_artifact_sha256", 64),
    ):
        if not _is_lower_hex(evidence.get(field), length):
            blockers.append(f"strategy_v1_hash_invalid:{field}")
    for field, required_prefix in (
        (
            "source_handoff_path",
            ".agent/handoffs/STRATEGY-V1-DONCHIAN-OFFLINE/",
        ),
        ("source_review_report_path", "docs/operations/"),
        ("approved_source_touch_set_artifact_path", "docs/architecture/"),
    ):
        value = evidence.get(field)
        if (
            not _is_canonical_relative_path(value)
            or not value.casefold().startswith(required_prefix.casefold())
        ):
            blockers.append(f"strategy_v1_bound_path_invalid:{field}")
    if evidence.get("source_review_commit") == evidence.get("source_commit"):
        blockers.append("strategy_v1_source_review_not_independent")
    if evidence.get("source_handoff_commit") == evidence.get("source_commit"):
        blockers.append("strategy_v1_source_handoff_not_separate_commit")

    source_paths, path_blockers = _canonical_relative_paths(
        evidence.get("source_changed_paths"),
        prefix="strategy_v1_source",
    )
    blockers.extend(path_blockers)
    approved_paths, approved_blockers = _canonical_relative_paths(
        evidence.get("approved_source_touch_set"),
        prefix="strategy_v1_approved_source",
    )
    blockers.extend(approved_blockers)
    if set(source_paths) != set(approved_paths):
        blockers.append("strategy_v1_source_touch_set_mismatch")
    if any(
        path.casefold().startswith(prefix.casefold())
        for path in source_paths
        for prefix in contract["protected_source_path_prefixes"]
    ):
        blockers.append("strategy_v1_source_protected_path")
    if any(
        path.casefold()
        not in {
            allowed.casefold() for allowed in contract["allowed_source_paths"]
        }
        and not any(
            path.casefold().startswith(prefix.casefold())
            for prefix in contract["allowed_source_path_prefixes"]
        )
        for path in source_paths
    ):
        blockers.append("strategy_v1_source_path_outside_fixed_boundary")

    source_capabilities = evidence.get("source_changed_capabilities")
    if (
        not isinstance(source_capabilities, list)
        or not source_capabilities
        or any(
            not isinstance(value, str)
            or value not in contract["allowed_source_capabilities"]
            for value in source_capabilities
        )
        or len(source_capabilities) != len(set(source_capabilities))
    ):
        blockers.append("strategy_v1_source_capability_outside_scope")
    blockers.extend(
        _validate_literal_checks(
            evidence.get("source_checks"),
            contract["required_source_checks"],
            prefix="strategy_v1_source_checks",
        )
    )

    safety_flags = evidence.get("safety_flags")
    if not isinstance(safety_flags, Mapping):
        blockers.append("strategy_v1_safety_flags_missing")
    else:
        for key in contract["required_false_flags"]:
            if safety_flags.get(key) is not False:
                blockers.append(f"strategy_v1_safety_flags_invalid:{key}")
        if any(value is not False for value in safety_flags.values()):
            blockers.append("strategy_v1_unsafe_extra_flag")

    deployment_fields = (
        "deployment_commit",
        "deployment_handoff_commit",
        "deployment_handoff_path",
        "deployment_handoff_sha256",
        "deployment_review_commit",
        "deployment_review_report_path",
        "deployment_review_report_sha256",
        "reviewed_source_commit",
        "reviewed_source_review_commit",
        "reviewed_source_touch_set_artifact_sha256",
        "deployment_changed_paths",
        "deployment_changed_capabilities",
        "deployment_checks",
    )
    if phase == "source_review":
        if any(field in evidence for field in deployment_fields):
            blockers.append("strategy_v1_source_phase_contains_deployment_claims")
    elif phase == "deployment_acceptance":
        for field, length in (
            ("deployment_commit", 40),
            ("deployment_handoff_commit", 40),
            ("deployment_review_commit", 40),
            ("deployment_review_report_sha256", 64),
            ("deployment_handoff_sha256", 64),
            ("reviewed_source_commit", 40),
            ("reviewed_source_review_commit", 40),
            ("reviewed_source_touch_set_artifact_sha256", 64),
        ):
            if not _is_lower_hex(evidence.get(field), length):
                blockers.append(f"strategy_v1_hash_invalid:{field}")
        for field, required_prefix in (
            ("deployment_handoff_path", ".agent/handoffs/"),
            ("deployment_review_report_path", "docs/operations/"),
        ):
            value = evidence.get(field)
            if (
                not _is_canonical_relative_path(value)
                or not value.casefold().startswith(required_prefix.casefold())
            ):
                blockers.append(f"strategy_v1_bound_path_invalid:{field}")
        if evidence.get("reviewed_source_commit") != evidence.get("source_commit"):
            blockers.append("strategy_v1_deployment_source_commit_mismatch")
        if evidence.get("reviewed_source_review_commit") != evidence.get(
            "source_review_commit"
        ):
            blockers.append("strategy_v1_deployment_review_commit_mismatch")
        if evidence.get("reviewed_source_touch_set_artifact_sha256") != evidence.get(
            "approved_source_touch_set_artifact_sha256"
        ):
            blockers.append("strategy_v1_deployment_touch_set_binding_mismatch")
        deployment_paths, deployment_path_blockers = _canonical_relative_paths(
            evidence.get("deployment_changed_paths"),
            prefix="strategy_v1_deployment",
        )
        blockers.extend(deployment_path_blockers)
        for path in deployment_paths:
            if any(
                path.casefold().startswith(prefix.casefold())
                for prefix in contract["protected_deployment_path_prefixes"]
            ):
                blockers.append(f"strategy_v1_deployment_protected_path:{path}")
        capabilities = evidence.get("deployment_changed_capabilities")
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or any(
                not isinstance(value, str)
                or value not in contract["allowed_deployment_capabilities"]
                for value in capabilities
            )
            or len(capabilities) != len(set(capabilities))
        ):
            blockers.append("strategy_v1_deployment_capability_outside_scope")
        blockers.extend(
            _validate_literal_checks(
                evidence.get("deployment_checks"),
                contract["required_deployment_checks"],
                prefix="strategy_v1_deployment_checks",
            )
        )
    return sorted(set(blockers))


def research_release_blockers(evidence: Mapping[str, Any] | None) -> list[str]:
    """Validate a reviewer-supplied receipt; never grant capabilities or launch.

    Checks must be backed by committed hashes/commands in the independent
    report. This is not a substitute for inspecting the real diff and listener.
    Unknown/missing data fails closed; no file, environment or runtime writes.
    """
    required = delivery_requirements("research_readonly_release")
    if not isinstance(evidence, Mapping):
        return ["research_release_evidence_missing"]
    blockers: list[str] = []
    if evidence.get("profile") != required["backend_evidence_profile"]:
        blockers.append("research_release_profile_not_readonly")
    for section, required_key, expected in (
        ("checks", "required_checks", True),
        ("safety_flags", "required_false_flags", False),
    ):
        observed = evidence.get(section)
        if not isinstance(observed, Mapping):
            blockers.append(f"research_release_{section}_missing")
            continue
        for key in required[required_key]:
            if observed.get(key) is not expected:
                blockers.append(f"research_release_{section}_invalid:{key}")
        if section == "safety_flags" and any(value is not False for value in observed.values()):
            blockers.append("research_release_unsafe_extra_flag")
    capabilities = evidence.get("changed_capabilities")
    if not isinstance(capabilities, list) or not capabilities or any(
        not isinstance(value, str) or value not in required["allowed_capabilities"] for value in capabilities
    ):
        blockers.append("research_release_capability_outside_scope")
    paths = evidence.get("changed_paths")
    if not isinstance(paths, list) or not paths:
        blockers.append("research_release_changed_paths_missing")
    else:
        for path in paths:
            if not isinstance(path, str) or not path or path.startswith("/") or ":" in path or "\\" in path or any(part in ("", ".", "..") for part in path.split("/")):
                blockers.append("research_release_changed_path_noncanonical")
                continue
            if any(path.casefold().startswith(prefix.casefold()) for prefix in required["protected_path_prefixes"]):
                blockers.append(f"research_release_protected_path:{path}")
    return sorted(set(blockers))


def canonical_change_risk(value: str | None) -> str:
    normalized = str(value or "unclassified").strip().lower().replace(
        "-", "_"
    )
    if normalized not in CHANGE_RISKS:
        raise ValueError(f"unknown_change_risk:{value}")
    return normalized


def delivery_requirements(
    change_risk: str,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected = policy or load_delivery_policy()
    risk = canonical_change_risk(change_risk)
    return dict(selected["change_risks"][risk])


def infer_change_risk(prompt: str) -> str:
    lowered = (
        prompt.casefold()
        .replace("-", " ")
        .replace("_", " ")
        .replace("/", " ")
    )
    # Explicit Demo transport intent wins over negative safety text such as
    # "禁止实盘"; prohibitions are constraints, not a live-execution request.
    if any(term in lowered for term in _DEMO_TRANSPORT_TERMS):
        return "demo_transport_hotfix"
    if any(term in lowered for term in _GOVERNANCE_TERMS):
        return "governance_control"
    if any(term in lowered for term in _LIVE_TERMS):
        return "live_execution"
    if any(term in lowered for term in _PROMOTION_TERMS):
        return "promotion_evidence"
    if any(term in lowered for term in _DEMO_EXECUTION_TERMS):
        return "demo_execution_semantics"
    if any(term in lowered for term in _OBSERVE_TERMS):
        return "observe_only"
    return "unclassified"
