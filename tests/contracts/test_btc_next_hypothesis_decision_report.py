from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_next_hypothesis_decision_report import build_btc_next_hypothesis_decision_report


SCHEMA = Path("schemas/btc_next_hypothesis_decision_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/btc_next_hypothesis_decision_report.json")


def test_btc_next_hypothesis_decision_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_next_hypothesis_rejects_dual_trend_micro_surgery() -> None:
    payload = build_btc_next_hypothesis_decision_report(generated_at="2026-06-05T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "dual_trend_micro_surgery_rejected"
    assert payload["decision"] == "reject_same_family_micro_surgery"
    assert payload["next_required_action"] == "design_new_strategy_family_with_lifecycle_edge"
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["same_family_micro_search_allowed"] is False
    assert payload["source_bounded_retest_status"] == "completed_candidate_gate_failed"
    assert payload["baseline_candidate"]["event_profit_factor"] == pytest.approx(1.0205)
    assert payload["baseline_candidate"]["walk_forward_pass_rate"] == pytest.approx(0.5)
    assert payload["mode_count"] == 10
    assert payload["event_profit_factor_pass_count"] == 0
    assert payload["walk_forward_pass_rate_pass_count"] >= 1
    best_event = payload["best_by_event_profit_factor"]
    assert best_event["mode"] == "lifecycle_stop6_trail10_max240"
    assert best_event["event_profit_factor"] == pytest.approx(1.036973, abs=1e-6)
    assert best_event["walk_forward_pass_rate"] == pytest.approx(0.75)
    best_wf = payload["best_by_walk_forward_pass_rate"]
    assert best_wf["mode"] == "accel1p2_lifecycle"
    assert best_wf["walk_forward_pass_rate"] == pytest.approx(1.0)
    assert best_wf["event_profit_factor"] < 1.15
    assert "btc_next_hypothesis_all_probe_event_profit_factor_failed" in payload["blockers"]
    assert "btc_next_hypothesis_dual_trend_micro_surgery_rejected" in payload["blockers"]


def test_btc_next_hypothesis_missing_probe_rows_stays_fail_closed(tmp_path: Path) -> None:
    payload = build_btc_next_hypothesis_decision_report(
        repo_root=tmp_path,
        probe_run_dirs=[Path("artifacts/btc_canonical/missing_probe")],
        generated_at="2026-06-05T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "dual_trend_micro_surgery_rejected"
    assert payload["mode_count"] == 0
    assert payload["event_profit_factor_pass_count"] == 0
    assert payload["promotion_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert "btc_next_hypothesis_probe_rows_missing" in payload["blockers"]


def test_btc_next_hypothesis_schema_rejects_paper_unlock() -> None:
    payload = build_btc_next_hypothesis_decision_report(generated_at="2026-06-05T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
