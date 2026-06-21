from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_intraday_short_cycle_research_candidate_definition_preflight import (
    build_btc_intraday_short_cycle_research_candidate_definition_preflight,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_research_candidate_definition_preflight.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_research_candidate_definition_preflight.json")


def test_btc_intraday_short_cycle_research_candidate_definition_preflight_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_research_candidate_definition_preflight_allows_definition_manifest_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "ready_for_research_candidate_definition_manifest"
    assert payload["decision"] == "allow_research_candidate_definition_manifest_only"
    assert payload["next_required_action"] == "create_research_candidate_definition_manifest_no_strategy_skeleton"
    assert payload["checks"]["manual_review_packet_present"] is True
    assert payload["checks"]["manual_review_packet_approved"] is True
    assert payload["checks"]["recorded_manual_review_approved"] is True
    assert payload["checks"]["candidate_generation_still_locked"] is True
    assert payload["checks"]["strategy_skeleton_still_locked"] is True
    assert payload["checks"]["paper_live_still_locked"] is True
    assert payload["checks"]["true_scalping_still_locked"] is True
    assert payload["research_candidate_definition_manifest_allowed"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["blockers"] == []


def test_btc_intraday_short_cycle_research_candidate_definition_preflight_allows_definition_manifest_only(
    tmp_path: Path,
) -> None:
    _write_approved_fixture(tmp_path)

    payload = build_btc_intraday_short_cycle_research_candidate_definition_preflight(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "ready_for_research_candidate_definition_manifest"
    assert payload["decision"] == "allow_research_candidate_definition_manifest_only"
    assert payload["next_required_action"] == "create_research_candidate_definition_manifest_no_strategy_skeleton"
    assert all(payload["checks"].values())
    assert payload["blockers"] == []
    assert payload["research_candidate_definition_manifest_allowed"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["guardrails"]["strategy_code_generation_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["candidate_definition_blueprint"]["candidate_id"] == (
        "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1:"
        "high_vol_non_expansion_trend_guard_repair_v1:research_candidate_definition_v1"
    )


def test_btc_intraday_short_cycle_research_candidate_definition_preflight_schema_rejects_unlock() -> None:
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


def _write_approved_fixture(root: Path) -> None:
    latest = root / "artifacts/btc_candidate_gate/latest"
    event_root = root / "artifacts/btc_intraday_event_ledger/fixture"
    source_reports = {
        "promotion_gate": "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json",
        "drift_guarded_event_ledger": "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
        "canonical_backtest_report": "artifacts/btc_intraday_event_ledger/fixture/canonical_backtest_report.json",
        "cost_stress_report": "artifacts/btc_intraday_event_ledger/fixture/cost_stress_report.json",
        "walk_forward_report": "artifacts/btc_intraday_event_ledger/fixture/walk_forward_report.json",
        "regime_report": "artifacts/btc_intraday_event_ledger/fixture/regime_report.json",
        "tail_dependency_report": "artifacts/btc_intraday_event_ledger/fixture/tail_dependency_report.json",
        "run_manifest": "artifacts/btc_intraday_event_ledger/fixture/run_manifest.json",
    }
    for value in source_reports.values():
        path = root / value
        if path.name not in {
            "btc_intraday_short_cycle_promotion_gate_report.json",
            "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
            "run_manifest.json",
        }:
            _write_json(path, {"status": "fixture"})
    _write_json(
        latest / "btc_intraday_short_cycle_manual_review_packet.json",
        {
            "status": "approved_for_research_candidate_definition",
            "recorded_manual_review_approved": True,
            "research_candidate_definition_allowed": True,
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "promotion_allowed": False,
            "paper_review_pending_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "true_scalping_allowed": False,
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
            "guardrails": {
                "approval_scope": "research_candidate_definition_only",
                "broker_calls_allowed": False,
                "private_endpoints_allowed": False,
                "order_endpoints_allowed": False,
            },
        },
    )
    _write_json(
        latest / "btc_intraday_short_cycle_promotion_gate_report.json",
        {
            "status": "ready_for_manual_candidate_review",
            "manual_candidate_review_allowed": True,
            "candidate_generation_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "true_scalping_allowed": False,
            "guardrails": {"pnl_from_fill_ledger_required": True},
        },
    )
    _write_json(
        latest / "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
        {
            "status": "event_ledger_passed_internal_research_gate_candidate_still_locked",
            "event_ledger_completed": True,
            "gate": {"passed": True},
            "guardrails": {"pnl_from_fill_ledger_required_for_promotion": True},
        },
    )
    _write_json(
        event_root / "run_manifest.json",
        {
            "run_id": "fixture_run",
            "data_version": "fixture_data",
            "strategy_version": "fixture_strategy",
            "params": {"variant_id": "high_vol_non_expansion_trend_guard_repair_v1"},
            "params_hash": "abc123",
            "cost_model": "fixture_cost",
            "slippage_model": "fixture_slippage",
            "commit_hash": "abc123",
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
