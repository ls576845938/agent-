from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_intraday_short_cycle_research_candidate_definition_manifest import (
    build_btc_intraday_short_cycle_research_candidate_definition_manifest,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_research_candidate_definition_manifest.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_manifest.json")


def test_btc_intraday_short_cycle_research_candidate_definition_manifest_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_research_candidate_definition_manifest_ready_still_locks_execution() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "ready_research_candidate_definition_manifest_only"
    assert payload["decision"] == "publish_research_candidate_definition_manifest_only"
    assert payload["next_required_action"] == "review_research_candidate_definition_manifest_no_strategy_skeleton"
    assert payload["checks"]["preflight_present"] is True
    assert payload["checks"]["preflight_ready_for_definition_manifest"] is True
    assert payload["checks"]["preflight_allows_definition_manifest"] is True
    assert payload["checks"]["manual_review_packet_approved"] is True
    assert payload["checks"]["recorded_manual_review_approved"] is True
    assert payload["checks"]["candidate_generation_still_locked"] is True
    assert payload["checks"]["strategy_skeleton_still_locked"] is True
    assert payload["checks"]["paper_live_still_locked"] is True
    assert payload["checks"]["true_scalping_still_locked"] is True
    assert payload["research_candidate_definition_manifest_ready"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["remaining_blocker_summary"]["only_manual_or_external_blockers_remain"] is True
    assert payload["remaining_blocker_summary"]["automated_engineering_blockers"] == []
    assert payload["blockers"] == []
    categories = {item["category"] for item in payload["remaining_manual_or_external_blockers"]}
    assert categories == {
        "real_long_horizon_market_data",
        "execution_evidence",
        "queue_evidence",
        "paper_gate",
    }
    assert payload["evidence_requirements"]["recorded_manual_review_approval"]["satisfied"] is True
    assert payload["evidence_requirements"]["true_long_horizon_l2_tick_history"]["satisfied"] is False
    assert payload["candidate_definition"]["candidate_id"] == (
        "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1:"
        "high_vol_non_expansion_trend_guard_repair_v1:research_candidate_definition_v1"
    )
    assert payload["candidate_definition"]["strategy_may_call_broker"] is False


def test_btc_intraday_short_cycle_research_candidate_definition_manifest_ready_still_locks_execution(
    tmp_path: Path,
) -> None:
    _write_ready_preflight_fixture(tmp_path)

    payload = build_btc_intraday_short_cycle_research_candidate_definition_manifest(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "ready_research_candidate_definition_manifest_only"
    assert payload["decision"] == "publish_research_candidate_definition_manifest_only"
    assert payload["next_required_action"] == "review_research_candidate_definition_manifest_no_strategy_skeleton"
    assert payload["blockers"] == []
    assert payload["research_candidate_definition_manifest_ready"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["guardrails"]["strategy_code_generation_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["evidence_requirements"]["recorded_manual_review_approval"]["satisfied"] is True
    categories = {item["category"] for item in payload["remaining_manual_or_external_blockers"]}
    assert "manual_approval" not in categories
    assert categories == {
        "real_long_horizon_market_data",
        "execution_evidence",
        "queue_evidence",
        "paper_gate",
    }


def test_btc_intraday_short_cycle_research_candidate_definition_manifest_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["strategy_skeleton_generation_allowed"] = True

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        pass
    else:  # pragma: no cover - assertion branch.
        raise AssertionError("schema must reject strategy skeleton unlock")

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["broker_calls_allowed"] = True

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        pass
    else:  # pragma: no cover - assertion branch.
        raise AssertionError("schema must reject broker unlock")


def _write_ready_preflight_fixture(root: Path) -> None:
    latest = root / "artifacts/btc_candidate_gate/latest"
    source_reports = {
        "manual_review_packet": "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_manual_review_packet.json",
        "promotion_gate": "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json",
        "drift_guarded_event_ledger": (
            "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json"
        ),
        "canonical_backtest_report": "artifacts/btc_intraday_event_ledger/fixture/canonical_backtest_report.json",
        "cost_stress_report": "artifacts/btc_intraday_event_ledger/fixture/cost_stress_report.json",
        "walk_forward_report": "artifacts/btc_intraday_event_ledger/fixture/walk_forward_report.json",
        "regime_report": "artifacts/btc_intraday_event_ledger/fixture/regime_report.json",
        "tail_dependency_report": "artifacts/btc_intraday_event_ledger/fixture/tail_dependency_report.json",
        "run_manifest": "artifacts/btc_intraday_event_ledger/fixture/run_manifest.json",
    }
    for value in source_reports.values():
        _write_json(root / value, {"status": "fixture"})
    _write_json(
        latest / "btc_intraday_short_cycle_research_candidate_definition_preflight.json",
        {
            "status": "ready_for_research_candidate_definition_manifest",
            "decision": "allow_research_candidate_definition_manifest_only",
            "next_required_action": "create_research_candidate_definition_manifest_no_strategy_skeleton",
            "source_reports": source_reports,
            "review_subject": {
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
                "gate": {"status": "candidate_passed_internal_gate", "passed": True},
            },
            "checks": {
                "manual_review_packet_approved": True,
                "recorded_manual_review_approved": True,
                "research_candidate_definition_allowed_by_review": True,
                "broker_private_order_paths_locked": True,
            },
            "blockers": [],
            "candidate_definition_blueprint": {
                "candidate_id": (
                    "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1:"
                    "high_vol_non_expansion_trend_guard_repair_v1:research_candidate_definition_v1"
                ),
                "strategy_id": "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1",
                "variant_id": "high_vol_non_expansion_trend_guard_repair_v1",
                "definition_scope": "research_candidate_definition_only",
                "source_run_id": "fixture_run",
                "source_strategy_version": "fixture_strategy",
                "source_data_version": "fixture_data",
                "params_hash": "abc123",
                "required_next_artifact": "research_candidate_definition_manifest",
                "forbidden_outputs": [
                    "strategy_code",
                    "broker_order",
                    "paper_runtime_entry",
                    "live_runtime_entry",
                    "true_scalping_claim",
                ],
            },
            "research_candidate_definition_manifest_allowed": True,
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "true_scalping_allowed": False,
            "guardrails": {
                "broker_calls_allowed": False,
                "private_endpoints_allowed": False,
                "order_endpoints_allowed": False,
            },
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
