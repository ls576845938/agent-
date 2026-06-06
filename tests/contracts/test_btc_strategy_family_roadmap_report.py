from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_strategy_family_roadmap_report import build_btc_strategy_family_roadmap_report


SCHEMA = Path("schemas/btc_strategy_family_roadmap_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_strategy_family_roadmap_report.json")


def test_btc_strategy_family_roadmap_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_strategy_family_roadmap_selects_funding_family_but_blocks_candidate_generation() -> None:
    payload = build_btc_strategy_family_roadmap_report(generated_at="2026-06-05T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "family_design_data_blocked"
    assert payload["decision"] == "select_funding_carry_reversion_hypothesis"
    assert payload["next_required_action"] == "extend_okx_public_history_before_hypothesis_or_candidate_generation"
    assert payload["selected_next_family"]["family_id"] == "funding_carry_reversion_v0"
    assert payload["selected_next_family"]["family"] == "funding_carry_reversion"
    assert payload["next_hypothesis_status"] == "dual_trend_micro_surgery_rejected"
    assert payload["hypothesis_distribution_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["data_prerequisites"]["selected_provider"] == "okx_swap"
    assert payload["data_prerequisites"]["selected_bundle_id"] == "btc_okx_swap_btcusdt_history_365d_v1"
    assert payload["data_prerequisites"]["selected_bundle_duration_days"] == pytest.approx(94.333333)
    assert payload["data_prerequisites"]["selected_bundle_duration_days"] < (
        payload["data_prerequisites"]["min_required_history_days"]
    )
    assert payload["data_prerequisites"]["klines_1h_record_count"] == 2266
    assert payload["data_prerequisites"]["klines_1h_record_count"] < (
        payload["data_prerequisites"]["min_required_1h_bars"]
    )
    assert payload["data_prerequisites"]["funding_rate_record_count"] == 284
    assert payload["data_prerequisites"]["funding_rate_record_count"] < payload["data_prerequisites"]["min_required_funding_events"]
    assert payload["archived_or_rejected_family_count"] >= 5
    assert "btc_strategy_family_dual_trend_micro_surgery_rejected" in payload["blockers"]
    assert "btc_strategy_family_selected_okx_bundle_history_too_short" in payload["blockers"]
    assert "btc_strategy_family_selected_okx_funding_history_too_short" in payload["blockers"]
    assert "btc_strategy_family_candidate_generation_blocked_until_okx_history_extended" in payload["blockers"]


def test_btc_strategy_family_roadmap_missing_repo_stays_fail_closed(tmp_path: Path) -> None:
    payload = build_btc_strategy_family_roadmap_report(
        repo_root=tmp_path,
        generated_at="2026-06-05T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "family_design_data_blocked"
    assert payload["hypothesis_distribution_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["selected_next_family"]["family_id"] == "funding_carry_reversion_v0"
    assert "btc_strategy_family_selected_bundle_manifest_missing" in payload["blockers"]
    assert "btc_strategy_family_candidate_generation_blocked_until_okx_history_extended" in payload["blockers"]


def test_btc_strategy_family_roadmap_schema_rejects_paper_unlock() -> None:
    payload = build_btc_strategy_family_roadmap_report(generated_at="2026-06-05T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
