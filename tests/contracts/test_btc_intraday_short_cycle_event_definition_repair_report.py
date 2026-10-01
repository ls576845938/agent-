from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_intraday_short_cycle_event_definition_repair_report import (
    build_btc_intraday_short_cycle_event_definition_repair_report,
)


SCHEMA = Path("schemas/btc_intraday_short_cycle_event_definition_repair_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_definition_repair_report.json")


def test_btc_intraday_event_definition_repair_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_intraday_event_definition_repair_identifies_retest_candidate() -> None:
    payload = build_btc_intraday_short_cycle_event_definition_repair_report(
        generated_at="2026-06-20T00:00:00Z"
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "repair_candidate_identified_retest_required"
    assert payload["decision"] == "run_full_event_ledger_retest_for_repaired_definition"
    assert payload["next_required_action"] == (
        "run_research_only_event_ledger_retest_for_high_vol_non_expansion_repair_v1"
    )
    assert payload["repair_scan_completed"] is True
    assert payload["repair_screen_is_promotion_evidence"] is False
    assert payload["full_event_ledger_retest_required"] is True
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    best = payload["best_repair_variant"]
    assert best["variant_id"] == "high_vol_non_expansion_repair_v1"
    assert best["filters"]["volatility_states"] == ["high_vol"]
    assert best["filters"]["allowed_regimes"] == ["high_vol_trend", "mean_reverting_chop", "trending_up"]
    assert best["trade_count"] == 103
    assert best["profit_factor"] == pytest.approx(1.859701)
    assert best["median_net_pnl"] == pytest.approx(2.371603)
    assert best["regime_pass_rate"] == pytest.approx(1.0)
    assert best["tail_dependency_pass"] is True
    assert best["repair_screen_pass"] is True
    assert best["repair_screen_is_promotion_evidence"] is False
    assert best["full_event_ledger_retest_required"] is True
    assert best["blockers"] == []
    assert "btc_intraday_repair_full_event_ledger_retest_required" in payload["blockers"]
    assert "btc_intraday_repair_candidate_generation_locked" in payload["blockers"]
    assert "btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model" in payload["blockers"]


def test_btc_intraday_event_definition_repair_missing_repo_fails_closed(tmp_path: Path) -> None:
    payload = build_btc_intraday_short_cycle_event_definition_repair_report(
        repo_root=tmp_path,
        generated_at="2026-06-20T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "repair_scan_no_candidate"
    assert payload["decision"] == "return_to_event_definition"
    assert payload["repair_scan_completed"] is False
    assert payload["best_repair_variant"]["repair_screen_pass"] is False
    assert "btc_intraday_repair_trade_attribution_missing" in payload["blockers"]
    assert payload["candidate_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False


def test_btc_intraday_event_definition_repair_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["repair_screen_is_promotion_evidence"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["candidate_generation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["full_event_ledger_retest_required"] = False

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
