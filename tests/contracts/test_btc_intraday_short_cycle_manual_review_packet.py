from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_intraday_short_cycle_manual_review_packet import (
    build_btc_intraday_short_cycle_manual_review_packet,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_manual_review_packet.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_manual_review_packet.json")
PROMOTION = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json")


def test_btc_intraday_short_cycle_manual_review_packet_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_manual_review_packet_approves_definition_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "approved_for_research_candidate_definition"
    assert payload["decision"] == "allow_research_candidate_definition_only"
    assert payload["next_required_action"] == "build_research_candidate_definition_manifest"
    assert all(payload["hard_checks"].values())
    assert payload["manual_review_packet_ready"] is True
    assert payload["recorded_manual_review_approved"] is True
    assert payload["research_candidate_definition_allowed"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["approval"]["exists"] is True
    assert payload["approval"]["approved"] is True
    assert payload["approval"]["approval"]["valid"] is True
    assert payload["approval"]["approval"]["reviewer"] == "lishuonewbing"
    assert payload["approval"]["path"] == (
        "data/research/btc_intraday_candidate_reviews/btc_intraday_short_cycle_manual_review_v1/review.json"
    )
    assert payload["blockers"] == []
    assert payload["promotion_gate_sha256"] == _promotion_review_source_sha256(PROMOTION)
    assert payload["approval_template"]["write_to"] == payload["approval"]["path"]
    assert payload["approval_template"]["review"]["approval"]["source_sha256"] == _promotion_review_source_sha256(
        PROMOTION
    )
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False


def test_btc_intraday_short_cycle_manual_review_packet_approves_research_candidate_definition_only(
    tmp_path: Path,
) -> None:
    promotion_path = tmp_path / PROMOTION
    _write_json(promotion_path, _promotion_payload())
    source_sha = _promotion_review_source_sha256(promotion_path)
    approval_path = (
        tmp_path
        / "data/research/btc_intraday_candidate_reviews/btc_intraday_short_cycle_manual_review_v1/review.json"
    )
    _write_json(approval_path, _approval_review(source_sha=source_sha))

    payload = build_btc_intraday_short_cycle_manual_review_packet(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "approved_for_research_candidate_definition"
    assert payload["decision"] == "allow_research_candidate_definition_only"
    assert payload["recorded_manual_review_approved"] is True
    assert payload["research_candidate_definition_allowed"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["blockers"] == []
    assert payload["approval"]["approval"]["valid"] is True


def test_btc_intraday_short_cycle_manual_review_packet_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    promotion_path = tmp_path / PROMOTION
    _write_json(promotion_path, _promotion_payload())
    approval_path = (
        tmp_path
        / "data/research/btc_intraday_candidate_reviews/btc_intraday_short_cycle_manual_review_v1/review.json"
    )
    _write_json(approval_path, _approval_review(source_sha="0" * 64))

    payload = build_btc_intraday_short_cycle_manual_review_packet(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "awaiting_recorded_manual_review"
    assert payload["research_candidate_definition_allowed"] is False
    assert "btc_intraday_manual_review_source_sha256_mismatch" in payload["blockers"]


def test_btc_intraday_short_cycle_manual_review_packet_schema_rejects_execution_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _promotion_payload() -> dict[str, object]:
    return {
        "status": "ready_for_manual_candidate_review",
        "manual_candidate_review_allowed": True,
        "candidate_generation_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "strategy_id": "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1",
        "variant_id": "high_vol_non_expansion_trend_guard_repair_v1",
        "family_id": "pullback_reclaim_intraday_v0",
        "metrics": {
            "trade_count": 78,
            "fill_count": 156,
            "profit_factor": 2.647434,
            "event_profit_factor": 1.4397,
            "walk_forward_pass_rate": 0.833333,
            "regime_pass_rate": 0.8,
        },
        "gate": {"passed": True, "status": "candidate_passed_internal_gate"},
        "source_reports": {
            "drift_guarded_event_ledger": None,
            "canonical_backtest_report": None,
            "cost_stress_report": None,
            "walk_forward_report": None,
            "regime_report": None,
            "tail_dependency_report": None,
            "run_manifest": None,
        },
        "checks": {
            "manifest_data_version_present": True,
            "manifest_strategy_version_present": True,
            "manifest_params_present": True,
            "manifest_cost_model_present": True,
            "manifest_slippage_model_present": True,
            "manifest_commit_hash_present": True,
            "private_order_broker_paths_locked": True,
            "paper_live_still_locked": True,
            "true_scalping_still_locked": True,
        },
        "blockers": [],
    }


def _approval_review(*, source_sha: str) -> dict[str, object]:
    return {
        "schema_version": "btc_intraday_short_cycle_manual_review_v1",
        "review_id": "btc_intraday_short_cycle_manual_review_v1",
        "status": "APPROVED_FOR_RESEARCH_CANDIDATE_DEFINITION_ONLY",
        "strategy_id": "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1",
        "variant_id": "high_vol_non_expansion_trend_guard_repair_v1",
        "source_promotion_gate_report": str(PROMOTION),
        "approval": {
            "schema_version": "btc_intraday_short_cycle_manual_review_approval_v1",
            "decision": "approve_research_candidate_definition_only",
            "reviewer": "risk_reviewer",
            "reason": "research candidate definition approval only",
            "timestamp": "2026-06-20T00:00:00Z",
            "source": str(PROMOTION),
            "source_sha256": source_sha,
            "gate_snapshot": {
                "strategy_id": "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1",
                "variant_id": "high_vol_non_expansion_trend_guard_repair_v1",
                "promotion_status": "ready_for_manual_candidate_review",
                "manual_candidate_review_allowed": True,
                "candidate_generation_allowed": False,
                "paper_or_live_unlock_allowed": False,
                "true_scalping_allowed": False,
                "authorization_scope": "research_candidate_definition_only",
            },
            "blockers": [],
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _promotion_review_source_sha256(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("generated_at", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
