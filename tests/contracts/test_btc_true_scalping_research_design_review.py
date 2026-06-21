from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_research_design_review import (
    build_btc_true_scalping_research_design_review,
)


SCHEMA = Path("schemas/btc_true_scalping_research_design_review.schema.json")
REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_research_design_review.json")


def test_btc_true_scalping_research_design_review_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_research_design_review_allows_design_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "research_only_scalping_design_review_passed"
    assert payload["decision"] == "allow_research_only_true_scalping_design"
    assert payload["next_required_action"] == "build_research_only_true_scalping_design_report"
    assert payload["blockers"] == []
    assert all(payload["checks"].values())
    assert payload["research_only_scalping_design_allowed"] is True
    assert payload["research_only_event_definition_allowed"] is True
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False


def test_btc_true_scalping_research_design_review_passes_fixture_only_for_research_design(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json",
        _readiness_payload(strategy_skeleton_generation_allowed=False),
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_model_report.json",
        {"status": "pass"},
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_okx_microstructure_capture_report.json",
        {
            "status": "verified",
            "latency_samples": [
                {"endpoint": "/api/v5/market/history-trades", "network_called": True, "duration_ms": 100.0},
                {"endpoint": "/api/v5/market/books", "network_called": True, "duration_ms": 90.0},
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
        _event_ledger_payload(candidate_generation_allowed=False, paper_or_live_unlock_allowed=False),
    )

    payload = build_btc_true_scalping_research_design_review(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "research_only_scalping_design_review_passed"
    assert payload["research_only_scalping_design_allowed"] is True
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_btc_true_scalping_research_design_review_blocks_if_skeleton_unlocked(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json",
        _readiness_payload(strategy_skeleton_generation_allowed=True),
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_model_report.json",
        {"status": "pass"},
    )
    _write_json(
        tmp_path / "artifacts/btc_scalping_readiness/latest/btc_okx_microstructure_capture_report.json",
        {
            "status": "verified",
            "latency_samples": [
                {"endpoint": "/api/v5/market/history-trades", "network_called": True, "duration_ms": 100.0},
                {"endpoint": "/api/v5/market/books", "network_called": True, "duration_ms": 90.0},
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
        _event_ledger_payload(candidate_generation_allowed=False, paper_or_live_unlock_allowed=False),
    )

    payload = build_btc_true_scalping_research_design_review(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "research_only_scalping_design_review_blocked"
    assert payload["research_only_scalping_design_allowed"] is False
    assert "btc_scalping_review_readiness_strategy_skeleton_still_locked_failed" in payload["blockers"]


def test_btc_true_scalping_research_design_review_schema_rejects_execution_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["true_scalping_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _readiness_payload(*, strategy_skeleton_generation_allowed: bool) -> dict[str, object]:
    return {
        "status": "microstructure_evidence_ready_research_only",
        "true_scalping_allowed": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": strategy_skeleton_generation_allowed,
        "guardrails": {
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
        },
        "evidence": {
            "one_minute_klines": {"status": "pass"},
            "tick_or_agg_trade_history": {"status": "pass"},
            "order_book_depth_history": {"status": "pass"},
            "spread_model": {"status": "pass"},
            "latency_model": {"status": "pass"},
            "queue_position_model": {"status": "pass"},
        },
    }


def _event_ledger_payload(*, candidate_generation_allowed: bool, paper_or_live_unlock_allowed: bool) -> dict[str, object]:
    return {
        "gate": {"passed": True},
        "candidate_generation_allowed": candidate_generation_allowed,
        "paper_or_live_unlock_allowed": paper_or_live_unlock_allowed,
        "guardrails": {
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
