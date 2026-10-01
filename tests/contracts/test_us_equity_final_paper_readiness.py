from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

import quant_us.application.us_equity_final_paper_readiness as readiness


HEAD = "a" * 40


def test_complete_evidence_can_only_reach_architect_review(monkeypatch, tmp_path: Path) -> None:
    _patch_handoff_and_engineering(monkeypatch, defects=[])
    report = readiness.evaluate_us_equity_final_paper_readiness(
        current_head=HEAD,
        generated_at_utc=datetime(2026, 7, 25, tzinfo=timezone.utc),
        config=_config(tmp_path),
        evidence=_complete_evidence(),
        evidence_records=_records(),
    )

    assert report["status"] == "review_complete"
    assert report["decision"] == "promotion_evidence_ready_for_architect_review_only"
    assert report["readiness"]["promotion_evidence_ready"] is True
    assert report["blocker_taxonomy"]["root_blockers"] == []
    assert report["blocker_taxonomy"]["unclassified_blockers"] == []
    assert all(value is False for value in report["safety"].values())
    assert report["safety"]["paper_enabled"] is False
    assert report["safety"]["live_enabled"] is False


def test_missing_external_manual_and_natural_evidence_is_classified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_handoff_and_engineering(
        monkeypatch,
        defects=[
            {
                "defect_id": "paper_durable_path_assertion_drift",
                "status": "open",
                "owner": "paper_runtime",
                "evidence_path": "backend/tests/test_paper_runtime.py",
                "validator": "pytest",
                "repair_ticket": "docs/tickets/repair.md",
                "repair_ticket_exists": True,
                "next_action": "repair independently",
            }
        ],
    )
    evidence = _complete_evidence()
    evidence["production_pit"]["production_pit"] = {
        "accepted": False,
        "state": "missing",
        "validated_files": [],
        "blockers": ["production_pit_bundle_root_not_supplied"],
    }
    evidence["observation"]["windows"]["paper_review_natural_days"] = {
        "required": 30,
        "observed": 0,
        "complete": False,
    }
    evidence["observation"]["windows"][
        "independent_confirmation_trading_sessions"
    ] = {
        "required": 252,
        "observed": 0,
        "complete": False,
    }
    evidence["broker_review"] = {}
    evidence["manual_decision"] = {}

    report = readiness.evaluate_us_equity_final_paper_readiness(
        current_head=HEAD,
        generated_at_utc=datetime(2026, 7, 25, tzinfo=timezone.utc),
        config=_config(tmp_path),
        evidence=evidence,
        evidence_records=_records(),
    )

    codes = {
        item["code"] for item in report["blocker_taxonomy"]["root_blockers"]
    }
    assert report["status"] == "blocked"
    assert report["decision"] == "blocked_fail_closed_no_paper_no_live"
    assert report["readiness"]["promotion_evidence_ready"] is False
    assert "production_pit_evidence_unavailable" in codes
    assert "forward_observation_30_natural_days_incomplete" in codes
    assert "forward_observation_252_sessions_incomplete" in codes
    assert "broker_credential_review_not_valid" in codes
    assert "manual_decision_record_not_valid" in codes
    assert "paper_durable_path_assertion_drift" in codes
    assert report["blocker_taxonomy"]["unclassified_blockers"] == []


def test_unsafe_evidence_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _patch_handoff_and_engineering(monkeypatch, defects=[])
    evidence = _complete_evidence()
    evidence["oms"]["guardrails"] = {"order_endpoint_used": True}

    with pytest.raises(
        readiness.USFinalPaperReadinessError,
        match="unsafe_evidence_flag",
    ):
        readiness.evaluate_us_equity_final_paper_readiness(
            current_head=HEAD,
            generated_at_utc=datetime(2026, 7, 25, tzinfo=timezone.utc),
            config=_config(tmp_path),
            evidence=evidence,
            evidence_records=_records(),
        )


def test_unknown_original_blocker_stops_packet(monkeypatch, tmp_path: Path) -> None:
    _patch_handoff_and_engineering(monkeypatch, defects=[])
    evidence = _complete_evidence()
    evidence["producer_handoffs"] = {
        "published.json": {"blockers": ["novel_mystery_blocker"]}
    }

    with pytest.raises(
        readiness.USFinalPaperReadinessError,
        match="unsupported_blocker_taxonomy",
    ):
        readiness.evaluate_us_equity_final_paper_readiness(
            current_head=HEAD,
            generated_at_utc=datetime(2026, 7, 25, tzinfo=timezone.utc),
            config=_config(tmp_path),
            evidence=evidence,
            evidence_records=_records(),
        )


def test_schema_rejects_any_paper_unlock(monkeypatch, tmp_path: Path) -> None:
    _patch_handoff_and_engineering(monkeypatch, defects=[])
    report = readiness.evaluate_us_equity_final_paper_readiness(
        current_head=HEAD,
        generated_at_utc=datetime(2026, 7, 25, tzinfo=timezone.utc),
        config=_config(tmp_path),
        evidence=_complete_evidence(),
        evidence_records=_records(),
    )
    report["run_id"] = "us-g12-fixture"
    report["outputs"] = {
        "report": "artifacts/us/report.json",
        "manifest": "artifacts/us/manifest.json",
        "latest_pointer": "artifacts/us/latest.json",
    }
    report["artifact_identity_sha256"] = "b" * 64
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "schemas/us_equity_final_paper_readiness.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(report, schema)

    report["safety"]["paper_allowed"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report, schema)


def test_current_checkout_build_publishes_a_valid_blocked_packet(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    report = readiness.build_us_equity_final_paper_readiness(
        repo_root=root,
        current_head=head,
        output_root=tmp_path / "final-readiness",
        generated_at_utc=datetime(2026, 7, 25, 3, 0, tzinfo=timezone.utc),
        run_id="us-g12-current-checkout-contract",
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "blocked_fail_closed_no_paper_no_live"
    assert report["readiness"]["promotion_evidence_ready"] is False
    assert report["blocker_taxonomy"]["unclassified_blockers"] == []
    pointer = json.loads(
        (
            tmp_path
            / "final-readiness/latest/latest_pointer.json"
        ).read_text(encoding="utf-8")
    )
    assert pointer["source_head"] == head
    assert pointer["paper_or_live_unlock_allowed"] is False


def _patch_handoff_and_engineering(
    monkeypatch: pytest.MonkeyPatch,
    *,
    defects: list[dict[str, object]],
) -> None:
    monkeypatch.setattr(
        readiness,
        "_evaluate_handoffs",
        lambda **_: {
            "satisfied": True,
            "status": "satisfied",
            "blockers": [],
            "evidence_path": "handoffs",
        },
    )
    monkeypatch.setattr(
        readiness,
        "_evaluate_engineering_defects",
        lambda **_: {
            "satisfied": not defects,
            "status": "satisfied" if not defects else "blocked",
            "blockers": [str(item["defect_id"]) for item in defects],
            "defects": defects,
            "evidence_path": "",
        },
    )


def _config(root: Path) -> dict[str, object]:
    return {
        "_repo_root": str(root),
        "evidence_paths": {
            "integrated_handoffs": ["integrated.json"],
        },
        "engineering_defects": [],
    }


def _records() -> dict[str, dict[str, object]]:
    return {
        name: {
            "path": f"evidence/{name}.json",
            "exists": True,
            "sha256": "c" * 64,
        }
        for name in (
            "integrated_handoffs",
            "producer_handoffs",
            "production_pit",
            "canonical",
            "oms",
            "observation",
            "current_head_gate",
            "broker_review",
            "manual_decision",
        )
    }


def _complete_evidence() -> dict[str, dict[str, object]]:
    scenarios = {
        name: True
        for name in (
            "atomic_uow_rollback",
            "broker_outage",
            "cancel_pending_fail_closed",
            "crash_restart_recovery",
            "idempotency",
            "market_closed",
            "out_of_order_callback",
            "partial_fill",
            "reconciliation_break",
            "reconciliation_recovery",
            "truncated_log_fail_closed",
        )
    }
    return {
        "integrated_handoffs": {},
        "producer_handoffs": {},
        "production_pit": {
            "production_pit": {
                "accepted": True,
                "state": "accepted",
                "validated_files": [{"table": str(index)} for index in range(6)],
                "blockers": [],
            }
        },
        "canonical": {
            "engineering_checks": {
                "canonical_event_chain_complete": True,
                "deterministic_replay_passed": True,
                "ledger_reconciliation_passed": True,
                "no_lookahead_passed": True,
                "cost_stress_passed": True,
                "all_layers_version_bound": True,
            },
            "ledger_reconciliation": {
                "deterministic_replay_hash_match": True,
                "passed": True,
            },
            "blockers": [],
        },
        "observation": {
            "identity": {"source_head": HEAD},
            "windows": {
                "paper_review_natural_days": {
                    "required": 30,
                    "observed": 30,
                    "complete": True,
                },
                "independent_confirmation_trading_sessions": {
                    "required": 252,
                    "observed": 252,
                    "complete": True,
                },
            },
            "blockers": [],
        },
        "oms": {
            "lifecycle": {"complete": True},
            "scenario_results": scenarios,
            "recovery": {
                "crash_recovery_probe": {"passed": True},
                "truncated_log_probe": {"passed": True},
            },
            "blockers": [],
        },
        "broker_review": {
            "status": "broker_credentials_review_proven",
            "broker_credentials_proven": True,
            "blockers": [],
        },
        "manual_decision": {
            "status": "manual_decision_record_valid",
            "blockers": [],
        },
        "current_head_gate": {
            "schema_version": "us_equity_current_head_gate_rebuild_v1",
            "source_head": HEAD,
            "wrapper_status": "success",
            "validation_checks": {
                "all_output_schemas_valid": True,
                "all_output_hashes_verified": True,
                "all_declared_input_hashes_verified": True,
                "all_safety_flags_false": True,
            },
            "blockers": [],
        },
    }
