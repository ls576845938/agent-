from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA = Path("schemas/btc_intraday_short_cycle_event_ledger_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_ledger_report.json")


def test_btc_intraday_short_cycle_event_ledger_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_event_ledger_is_research_only() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["event_ledger_completed"] is True
    assert payload["strategy_id"] == "btc_pullback_reclaim_intraday_v1"
    assert payload["variant_id"] == "pullback_reclaim_24_dd100_4htrend100_v1"
    assert payload["event_definition"]["label_horizon"] == "60m"
    assert payload["event_definition"]["lookahead_used_for_signal"] is False
    assert payload["event_definition"]["future_label_used_for_signal"] is False
    assert payload["event_definition"]["simulated_order_intent_only"] is True
    assert payload["event_definition"]["event_count"] == 315
    assert payload["cost_context"]["base_taker_round_trip_bps"] == pytest.approx(10.0)
    assert payload["cost_context"]["required_scenarios_present"] is True
    assert payload["metrics"]["trade_count"] == 166
    assert payload["metrics"]["fill_count"] == 331
    assert payload["metrics"]["walk_forward_pass_rate"] == pytest.approx(1.0)
    assert payload["metrics"]["regime_pass_rate"] == pytest.approx(0.333333)
    assert payload["gate"]["passed"] is False
    assert payload["failed_metrics"] == ["regime_pass_rate"]
    assert payload["decision"] == "return_to_event_definition"
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["safety"]["paper_queue"] == "LOCKED"
    assert payload["safety"]["live"] == "FROZEN"
    assert payload["safety"]["real_broker_api_called"] is False
    assert payload["safety"]["real_orders_created"] is False
    assert "btc_intraday_event_ledger_gate_failed_regime_pass_rate" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]


def test_btc_intraday_short_cycle_event_ledger_schema_rejects_trade_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["candidate_generation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["safety"]["live"] = "READY"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
