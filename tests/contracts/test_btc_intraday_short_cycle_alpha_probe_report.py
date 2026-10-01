from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_intraday_short_cycle_alpha_probe_report import (
    build_btc_intraday_short_cycle_alpha_probe_report,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_alpha_probe_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_probe_report.json")


def test_btc_intraday_short_cycle_alpha_probe_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_alpha_probe_blocks_candidate_after_cost() -> None:
    payload = build_btc_intraday_short_cycle_alpha_probe_report(generated_at="2026-06-20T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "probe_completed_no_distribution_edge"
    assert payload["decision"] == "continue_intraday_alpha_research"
    assert payload["next_required_action"] == "refine_short_cycle_event_definitions_before_candidate"
    assert payload["distribution_probe_completed"] is True
    assert payload["alpha_distribution_observed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["sub_minute_or_tick_scalping_allowed"] is False
    assert payload["cost_context"]["taker_fee_bps"] == pytest.approx(5.0)
    assert payload["cost_context"]["round_trip_taker_cost_bps"] == pytest.approx(10.0)
    assert payload["cost_context"]["cost_is_diagnostic_not_fill_ledger_pnl"] is True
    assert payload["data_context"]["db_path"] == "data/market_data.sqlite"
    assert payload["data_context"]["db_exists"] is True
    assert payload["data_context"]["intervals"]["5m"]["row_count"] == 248270
    assert payload["data_context"]["intervals"]["15m"]["row_count"] == 82756
    families = {row["family_id"]: row for row in payload["family_results"]}
    compression = families["volatility_compression_reclaim_intraday_v0"]
    liquidation = families["liquidation_exhaustion_reclaim_intraday_v0"]
    momentum = families["orderflow_confirmed_momentum_intraday_v0"]
    funding = families["funding_premium_reversion_intraday_v0"]
    assert compression["event_count"] == 2722
    assert compression["distribution_sample_ready"] is True
    assert compression["alpha_distribution_observed"] is False
    assert compression["best_net_mean_bps"] == pytest.approx(-9.68145)
    assert liquidation["event_count"] == 4
    assert liquidation["distribution_sample_ready"] is False
    assert momentum["event_count"] == 5659
    assert momentum["distribution_sample_ready"] is True
    assert momentum["best_horizon"] == "60m"
    assert momentum["best_net_mean_bps"] == pytest.approx(-8.103324)
    assert funding["status"] == "context_blocked_missing_intraday_funding_premium"
    assert funding["event_count"] == 0
    assert payload["best_family"]["family_id"] == "orderflow_confirmed_momentum_intraday_v0"
    assert payload["best_family"]["candidate_generation_allowed"] is False
    assert "btc_intraday_probe_no_net_positive_distribution_edge" in payload["blockers"]
    assert "btc_intraday_probe_candidate_generation_blocked_until_event_ledger_backtest" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]


def test_btc_intraday_short_cycle_alpha_probe_missing_repo_stays_fail_closed(tmp_path: Path) -> None:
    payload = build_btc_intraday_short_cycle_alpha_probe_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "probe_data_blocked"
    assert payload["decision"] == "repair_intraday_probe_data"
    assert payload["distribution_probe_completed"] is False
    assert payload["alpha_distribution_observed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["data_context"]["db_exists"] is False
    assert payload["data_context"]["intervals"]["5m"]["row_count"] == 0
    assert payload["data_context"]["intervals"]["15m"]["row_count"] == 0
    assert "btc_intraday_probe_data_not_ready" in payload["blockers"]
    assert "btc_intraday_probe_5m_rows_missing" in payload["blockers"]
    assert "btc_intraday_probe_15m_rows_missing" in payload["blockers"]


def test_btc_intraday_short_cycle_alpha_probe_schema_rejects_trade_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["candidate_generation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoints_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
