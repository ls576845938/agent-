from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_intraday_short_cycle_alpha_plan_report import (
    build_btc_intraday_short_cycle_alpha_plan_report,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_alpha_plan_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_plan_report.json")


def test_btc_intraday_short_cycle_alpha_plan_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_alpha_plan_allows_research_only_distribution() -> None:
    payload = build_btc_intraday_short_cycle_alpha_plan_report(generated_at="2026-06-20T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "research_distribution_ready_candidate_blocked"
    assert payload["decision"] == "start_intraday_short_cycle_alpha_distribution"
    assert payload["next_required_action"] == "run_research_only_intraday_short_cycle_distribution_probe"
    assert payload["selected_research_style"]["style_id"] == "intraday_short_cycle_alpha_v0"
    assert payload["selected_research_style"]["primary_timeframes"] == ["5m", "15m"]
    assert payload["intraday_research_distribution_allowed"] is True
    assert payload["short_cycle_probe_allowed"] is True
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["sub_minute_or_tick_scalping_allowed"] is False
    assert payload["guardrails"]["maker_queue_assumption_without_orderbook_allowed"] is False
    prerequisites = payload["data_prerequisites"]
    assert prerequisites["required_intervals"] == ["5m", "15m"]
    assert prerequisites["sample_days"] == pytest.approx(862.0)
    assert prerequisites["intervals"]["5m"]["bar_count"] == 248257
    assert prerequisites["intervals"]["15m"]["bar_count"] == 82753
    assert prerequisites["intervals"]["5m"]["completeness_ratio"] == pytest.approx(1.0)
    assert prerequisites["intervals"]["15m"]["completeness_ratio"] == pytest.approx(1.0)
    assert prerequisites["intervals"]["5m"]["missing_bar_count"] == 0
    assert prerequisites["intervals"]["15m"]["duplicate_bar_count"] == 0
    assert payload["cost_context"]["fee_tier_verified"] is True
    assert payload["cost_context"]["maker_fee_bps"] == pytest.approx(2.0)
    assert payload["cost_context"]["taker_fee_bps"] == pytest.approx(5.0)
    assert "volatility_compression_reclaim_intraday_v0" in {
        family["family_id"] for family in payload["candidate_families"]
    }
    assert "btc_intraday_candidate_generation_blocked_until_distribution_probe_passes" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]
    assert "btc_intraday_paper_live_locked" in payload["blockers"]
    assert "btc_intraday_existing_candidate_gate_not_pass" in payload["blockers"]


def test_btc_intraday_short_cycle_alpha_plan_missing_repo_stays_fail_closed(tmp_path: Path) -> None:
    payload = build_btc_intraday_short_cycle_alpha_plan_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "intraday_data_blocked"
    assert payload["decision"] == "extend_intraday_public_history_before_distribution"
    assert payload["intraday_research_distribution_allowed"] is False
    assert payload["short_cycle_probe_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["data_prerequisites"]["intervals"]["5m"]["bar_count"] == 0
    assert "btc_intraday_data_status_report_missing" in payload["blockers"]
    assert "btc_intraday_5m_bars_too_short" in payload["blockers"]
    assert "btc_intraday_15m_bars_too_short" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]


def test_btc_intraday_short_cycle_alpha_plan_schema_rejects_scalping_or_trade_unlock() -> None:
    payload = build_btc_intraday_short_cycle_alpha_plan_report(generated_at="2026-06-20T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["true_scalping_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = build_btc_intraday_short_cycle_alpha_plan_report(generated_at="2026-06-20T00:00:00Z")
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = build_btc_intraday_short_cycle_alpha_plan_report(generated_at="2026-06-20T00:00:00Z")
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
