from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _minute_quality_stub() -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {
            "status": "PASS",
            "evidence_summary": {},
            "remediation_summary": {"actions": []},
        }
    )


def _paper_validation_stub(state: str = "PASS") -> SimpleNamespace:
    return SimpleNamespace(
        readiness_state=state,
        days_completed=30,
        days_required=30,
        consecutive_clean_days=30,
        paper_submit_orders="PASS",
        audit_blocker_status="PASS",
        data_strict_status="PASS",
        recovery_status="PASS",
        gaps=[],
        evidence=[],
    )


def _portfolio_stub() -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {
            "status": "PASS",
            "multi_strategy": {"status": "PASS"},
            "multi_timeframe": {"status": "PASS"},
            "pnl_attribution": {"status": "PASS"},
        }
    )


def test_system_overview_paper_review_entry_blocks_without_eligible_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from backend.app.api.app_factory import _system_overview_payload

    monkeypatch.setattr(
        "backend.app.api.app_factory._fast_saved_evidence_registry",
        lambda root: {
            "registry_status": "present",
            "registry_integrity_status": "PASS/STABLE",
            "registry_path": str(Path(root) / "research" / "evidence_registry.json"),
            "registry_notes": [],
            "evidence": {
                "strategy_manifests": [
                    {
                        "details": {
                            "strategy_manifest_id": "sm_blocked",
                            "source_candidate_id": "cand_blocked",
                            "promotion_status": "BLOCKED",
                        }
                    }
                ],
                "paper_reviews": [],
            },
        },
    )
    monkeypatch.setattr(
        "quant_us.data.minute_quality_gate.inspect_minute_data_quality_overview",
        lambda root: _minute_quality_stub(),
    )
    monkeypatch.setattr(
        "quant_us.reports.paper_validation.inspect_paper_validation_evidence",
        lambda root, **kwargs: _paper_validation_stub(),
    )
    monkeypatch.setattr(
        "quant_us.reports.portfolio_observability.inspect_portfolio_observability",
        lambda root: _portfolio_stub(),
    )
    monkeypatch.setattr(
        "quant_us.live.paper_adapter_contract.audit_apca_paper_credentials",
        lambda: {"credentials_present": True, "base_url_valid": True},
    )

    payload = _system_overview_payload(data_root=str(tmp_path))
    creation = payload["paper_review"]["creation"]

    assert creation["creation_allowed"] is False
    assert any(reason.startswith("no_eligible_manifest:") for reason in creation["why_blocked"])
    assert creation["next_command"] == "Run promotion gate until a manifest reaches READY_FOR_PORTFOLIO_SIM, then create paper-review evidence from that manifest."
    assert payload["next_actions"][-1] == creation["next_command"]


def test_system_overview_paper_review_entry_exposes_create_command_for_eligible_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from backend.app.api.app_factory import _system_overview_payload

    monkeypatch.setattr(
        "backend.app.api.app_factory._fast_saved_evidence_registry",
        lambda root: {
            "registry_status": "present",
            "registry_integrity_status": "PASS/STABLE",
            "registry_path": str(Path(root) / "research" / "evidence_registry.json"),
            "registry_notes": [],
            "evidence": {
                "strategy_manifests": [
                    {
                        "details": {
                            "strategy_manifest_id": "sm_ready",
                            "source_candidate_id": "cand_ready",
                            "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                            "paper_review_candidate_status": "READY_FOR_REVIEW",
                        }
                    }
                ],
                "paper_reviews": [],
            },
        },
    )
    monkeypatch.setattr(
        "quant_us.data.minute_quality_gate.inspect_minute_data_quality_overview",
        lambda root: _minute_quality_stub(),
    )
    monkeypatch.setattr(
        "quant_us.reports.paper_validation.inspect_paper_validation_evidence",
        lambda root, **kwargs: _paper_validation_stub(),
    )
    monkeypatch.setattr(
        "quant_us.reports.portfolio_observability.inspect_portfolio_observability",
        lambda root: _portfolio_stub(),
    )
    monkeypatch.setattr(
        "quant_us.live.paper_adapter_contract.audit_apca_paper_credentials",
        lambda: {"credentials_present": True, "base_url_valid": True},
    )

    payload = _system_overview_payload(data_root=str(tmp_path))
    creation = payload["paper_review"]["creation"]

    assert creation["creation_allowed"] is True
    assert creation["preferred_manifest_id"] == "sm_ready"
    assert creation["preferred_candidate_id"] == "cand_ready"
    assert creation["next_command"] == (
        f'POST /api/research/paper-review/create {{ "strategy_manifest_id": "sm_ready", "candidate_id": "cand_ready", "data_root": "{tmp_path}" }}'
    )
    assert creation["create_from_manifest_command"] == (
        f'POST /api/research/paper-review/create {{ "strategy_manifest_id": "sm_ready", "data_root": "{tmp_path}" }}'
    )
    assert creation["create_from_candidate_command"] == (
        f'POST /api/research/paper-review/create {{ "candidate_id": "cand_ready", "data_root": "{tmp_path}" }}'
    )
