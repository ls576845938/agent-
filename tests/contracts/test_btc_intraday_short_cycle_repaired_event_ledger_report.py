from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA = Path("schemas/btc_intraday_short_cycle_event_ledger_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_repaired_event_ledger_report.json")


def test_btc_intraday_short_cycle_repaired_event_ledger_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_repaired_event_ledger_failed_research_gate() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["event_ledger_completed"] is True
    assert payload["strategy_id"] == "btc_pullback_reclaim_intraday_high_vol_non_expansion_repair_v1"
    assert payload["variant_id"] == "high_vol_non_expansion_repair_v1"
    assert payload["source_event_definition_repair_report"] == (
        "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_definition_repair_report.json"
    )
    assert payload["event_definition"]["entry_filters"] == {
        "allowed_regimes": ["high_vol_trend", "mean_reverting_chop", "trending_up"],
        "min_trend_by_regime": {},
        "volatility_states": ["high_vol"],
    }
    assert payload["event_definition"]["event_count"] == 217
    assert payload["metrics"]["trade_count"] == 110
    assert payload["metrics"]["fill_count"] == 219
    assert payload["metrics"]["profit_factor"] == pytest.approx(1.637559)
    assert payload["metrics"]["event_profit_factor"] == pytest.approx(1.3697)
    assert payload["metrics"]["walk_forward_pass_rate"] == pytest.approx(0.833333)
    assert payload["metrics"]["regime_pass_rate"] == pytest.approx(0.5)
    assert payload["tail_dependency"]["status"] == "pass"
    assert payload["gate"]["passed"] is False
    assert payload["failed_metrics"] == ["regime_pass_rate"]
    assert payload["decision"] == "return_to_event_definition"
    assert payload["next_required_action"] == "repair_intraday_event_definition_before_candidate"
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["safety"]["paper_queue"] == "LOCKED"
    assert payload["safety"]["live"] == "FROZEN"
    assert "btc_intraday_event_ledger_gate_failed_regime_pass_rate" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]


def test_btc_intraday_short_cycle_repaired_event_ledger_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
