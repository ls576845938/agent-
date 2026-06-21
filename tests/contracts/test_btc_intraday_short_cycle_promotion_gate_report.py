from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_intraday_short_cycle_promotion_gate_report import (
    build_btc_intraday_short_cycle_promotion_gate_report,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_promotion_gate_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_promotion_gate_report.json")


def test_btc_intraday_short_cycle_promotion_gate_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_promotion_gate_allows_manual_review_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "ready_for_manual_candidate_review"
    assert payload["decision"] == "continue_research_manual_review_only"
    assert payload["next_required_action"] == "manual_review_before_any_candidate_generation"
    assert payload["strategy_id"] == "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1"
    assert payload["variant_id"] == "high_vol_non_expansion_trend_guard_repair_v1"
    assert payload["blockers"] == []
    assert all(payload["checks"].values())
    assert payload["manual_candidate_review_allowed"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["metrics"]["trade_count"] == 78
    assert payload["metrics"]["fill_count"] == 156
    assert payload["metrics"]["profit_factor"] == pytest.approx(2.647434)
    assert payload["metrics"]["event_profit_factor"] == pytest.approx(1.4397)
    assert payload["metrics"]["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert payload["metrics"]["regime_pass_rate"] == pytest.approx(0.8)
    assert payload["gate"]["passed"] is True
    assert payload["gate"]["status"] == "candidate_passed_internal_gate"
    assert payload["manifest"]["params"]["variant_id"] == "high_vol_non_expansion_trend_guard_repair_v1"
    assert payload["manifest"]["params"]["entry_filter"] == {
        "allowed_regimes": ["high_vol_trend", "mean_reverting_chop", "trending_up"],
        "min_trend_by_regime": {"high_vol_trend": 0.017},
        "volatility_states": ["high_vol"],
    }
    assert payload["source_reports"]["run_manifest"] == (
        "artifacts/btc_intraday_event_ledger/"
        "20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger/run_manifest.json"
    )
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["paper_queue"] == "LOCKED"
    assert payload["guardrails"]["live"] == "FROZEN"


def test_btc_intraday_short_cycle_promotion_gate_blocks_missing_manifest_params(tmp_path: Path) -> None:
    event_path = tmp_path / "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json"
    manifest_path = tmp_path / "artifacts/btc_intraday_event_ledger/fixture/run_manifest.json"
    _write_json(event_path, _event_ledger_payload())
    _write_json(
        manifest_path,
        {
            "data_version": "fixture-data",
            "strategy_version": "fixture-strategy",
            "params_hash": "abc",
            "cost_model": "fixture-cost",
            "slippage_model": "fixture-slippage",
            "commit_hash": "abc123",
        },
    )

    payload = build_btc_intraday_short_cycle_promotion_gate_report(
        repo_root=tmp_path,
        event_ledger_path=Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json"),
        generated_at="2026-06-20T00:00:00Z",
    )

    assert payload["status"] == "blocked_promotion_gate"
    assert payload["manual_candidate_review_allowed"] is False
    assert payload["checks"]["manifest_params_present"] is False
    assert "btc_intraday_promotion_gate_manifest_params_present_failed" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_btc_intraday_short_cycle_promotion_gate_schema_rejects_execution_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["candidate_generation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["private_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _event_ledger_payload() -> dict[str, object]:
    return {
        "strategy_id": "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1",
        "variant_id": "high_vol_non_expansion_trend_guard_repair_v1",
        "family_id": "pullback_reclaim_intraday_v0",
        "event_ledger_completed": True,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "artifacts": {
            "canonical_backtest_report": "artifacts/btc_intraday_event_ledger/fixture/canonical_backtest_report.json",
            "event_objects": "artifacts/btc_intraday_event_ledger/fixture/event_objects.csv",
            "trade_ledger": "artifacts/btc_intraday_event_ledger/fixture/trade_ledger.csv",
            "cost_stress_report": "artifacts/btc_intraday_event_ledger/fixture/cost_stress_report.json",
            "walk_forward_report": "artifacts/btc_intraday_event_ledger/fixture/walk_forward_report.json",
            "regime_report": "artifacts/btc_intraday_event_ledger/fixture/regime_report.json",
            "tail_dependency_report": "artifacts/btc_intraday_event_ledger/fixture/tail_dependency_report.json",
            "run_manifest": "artifacts/btc_intraday_event_ledger/fixture/run_manifest.json",
        },
        "data_context": {"data_status": "pass"},
        "cost_context": {"cost_model_status": "pass", "required_scenarios_present": True},
        "event_definition": {
            "simulated_order_intent_only": True,
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
        },
        "metrics": {"trade_count": 1, "fill_count": 2, "profit_factor": 1.5, "event_profit_factor": 1.2, "walk_forward_pass_rate": 0.8, "regime_pass_rate": 0.75},
        "gate": {
            "status": "candidate_passed_internal_gate",
            "passed": True,
            "fail_reasons": [],
            "thresholds": {"walk_forward_pass_rate": 0.8, "regime_pass_rate": 0.75},
        },
        "cost_stress": {"base_passed": True, "harsh_survives": True},
        "tail_dependency": {"status": "pass", "blockers": []},
        "safety": {
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "real_broker_api_called": False,
            "real_orders_created": False,
        },
        "guardrails": {
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "true_scalping_allowed": False,
            "pnl_from_fill_ledger_required_for_promotion": True,
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
