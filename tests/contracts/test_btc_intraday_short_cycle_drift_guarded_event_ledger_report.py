from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA = Path("schemas/btc_intraday_short_cycle_event_ledger_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_drift_guarded_event_ledger_report.json")


def test_btc_intraday_short_cycle_drift_guarded_event_ledger_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_drift_guarded_event_ledger_passes_internal_gate_locked() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["event_ledger_completed"] is True
    assert payload["strategy_id"] == "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1"
    assert payload["variant_id"] == "high_vol_non_expansion_trend_guard_repair_v1"
    assert payload["status"] == "event_ledger_passed_internal_research_gate_candidate_still_locked"
    assert payload["decision"] == "continue_research"
    assert payload["next_required_action"] == "manual_review_before_any_candidate_generation"
    assert payload["event_definition"]["entry_filters"] == {
        "allowed_regimes": ["high_vol_trend", "mean_reverting_chop", "trending_up"],
        "min_trend_by_regime": {"high_vol_trend": 0.017},
        "volatility_states": ["high_vol"],
    }
    assert payload["event_definition"]["event_count"] == 161
    assert payload["metrics"]["trade_count"] == 78
    assert payload["metrics"]["fill_count"] == 156
    assert payload["metrics"]["profit_factor"] == pytest.approx(2.647434)
    assert payload["metrics"]["event_profit_factor"] == pytest.approx(1.4397)
    assert payload["metrics"]["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert payload["metrics"]["regime_pass_rate"] == pytest.approx(0.8)
    assert payload["tail_dependency"]["status"] == "pass"
    assert payload["gate"]["passed"] is True
    assert payload["failed_metrics"] == []
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["safety"]["paper_queue"] == "LOCKED"
    assert payload["safety"]["live"] == "FROZEN"
    assert payload["safety"]["real_broker_api_called"] is False
    assert payload["safety"]["real_orders_created"] is False
    assert "btc_regime_contract_not_pass" not in payload["blockers"]
    assert "btc_intraday_event_ledger_candidate_generation_locked_pending_review" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]


def test_btc_intraday_short_cycle_drift_guarded_event_ledger_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["candidate_generation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["private_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
