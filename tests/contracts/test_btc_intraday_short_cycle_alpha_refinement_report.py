from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_intraday_short_cycle_alpha_refinement_report import (
    build_btc_intraday_short_cycle_alpha_refinement_report,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_alpha_refinement_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_refinement_report.json")


def test_btc_intraday_short_cycle_alpha_refinement_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_short_cycle_alpha_refinement_selects_event_ledger_research_only() -> None:
    payload = build_btc_intraday_short_cycle_alpha_refinement_report(generated_at="2026-06-20T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "refinement_completed_event_ledger_backtest_ready_candidate_blocked"
    assert payload["decision"] == "design_research_only_event_ledger_backtest_for_refined_alpha"
    assert payload["next_required_action"] == "build_event_ledger_backtest_for_best_refined_variant"
    assert payload["refinement_completed"] is True
    assert payload["robust_alpha_distribution_observed"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["sub_minute_or_tick_scalping_allowed"] is False
    assert payload["cost_context"]["round_trip_taker_cost_bps"] == pytest.approx(10.0)
    assert payload["refinement_parameters"]["variant_count"] == 8
    assert payload["refinement_parameters"]["fold_count"] == 6
    assert payload["refinement_parameters"]["min_net_median_bps"] == pytest.approx(-10.0)
    assert payload["refinement_parameters"]["min_net_positive_hit_rate"] == pytest.approx(0.45)
    best = payload["best_variant"]
    assert best["variant_id"] == "pullback_reclaim_24_dd100_4htrend100_v1"
    assert best["family_id"] == "pullback_reclaim_intraday_v0"
    assert best["status"] == "robust_distribution_observed"
    assert best["event_count"] == 558
    assert best["best_horizon"] == "60m"
    assert best["best_net_mean_bps"] == pytest.approx(5.754492)
    assert best["positive_net_fold_count"] == 4
    assert best["candidate_generation_allowed"] is False
    variants = {row["variant_id"]: row for row in payload["variant_results"]}
    selected = variants["pullback_reclaim_24_dd100_4htrend100_v1"]
    assert selected["best_net_median_bps"] == pytest.approx(-7.475294)
    assert selected["best_net_positive_hit_rate"] == pytest.approx(0.473118)
    assert selected["valid_fold_count"] == 6
    assert selected["min_fold_event_count"] == 50
    assert selected["robust_distribution_observed"] is True
    assert variants["shock_reclaim_relaxed_35bps_vol15_v1"]["status"] == "sample_too_sparse"
    assert "btc_intraday_refinement_candidate_generation_blocked_until_event_ledger_backtest" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]
    assert "btc_intraday_refinement_paper_live_locked" in payload["blockers"]


def test_btc_intraday_short_cycle_alpha_refinement_missing_repo_stays_fail_closed(tmp_path: Path) -> None:
    payload = build_btc_intraday_short_cycle_alpha_refinement_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "refinement_data_blocked"
    assert payload["decision"] == "repair_intraday_refinement_data"
    assert payload["refinement_completed"] is False
    assert payload["robust_alpha_distribution_observed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["data_context"]["db_exists"] is False
    assert payload["variant_results"] == []
    assert payload["best_variant"] is None
    assert "btc_intraday_refinement_data_not_ready" in payload["blockers"]


def test_btc_intraday_short_cycle_alpha_refinement_schema_rejects_trade_unlock() -> None:
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
