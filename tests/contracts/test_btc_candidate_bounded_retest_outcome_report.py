from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_candidate_bounded_retest_outcome_report import (
    build_btc_candidate_bounded_retest_outcome_report,
)


SCHEMA = Path("schemas/btc_candidate_bounded_retest_outcome_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json")


def test_btc_candidate_bounded_retest_outcome_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_candidate_bounded_retest_outcome_locks_failed_retest() -> None:
    payload = build_btc_candidate_bounded_retest_outcome_report(generated_at="2026-06-04T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "completed_candidate_gate_failed"
    assert payload["candidate_gate_passed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["same_retest_repeat_allowed"] is False
    assert payload["next_required_action"] == "design_new_fold_specific_hypothesis_or_select_better_candidate"
    assert payload["run_id"] == "20260604T132400Z_okx_bounded_retest"
    assert payload["failed_metrics"] == ["event_profit_factor", "walk_forward_pass_rate"]
    assert payload["metrics"]["event_profit_factor"] == pytest.approx(1.0205)
    assert payload["metrics"]["walk_forward_pass_rate"] == pytest.approx(0.5)
    assert payload["metrics"]["regime_pass_rate"] == pytest.approx(1.0)
    assert payload["thresholds"]["event_profit_factor"] == pytest.approx(1.15)
    assert payload["thresholds"]["walk_forward_pass_rate"] == pytest.approx(0.8)
    assert payload["gate_checks"]["event_profit_factor"] is False
    assert payload["gate_checks"]["walk_forward_pass_rate"] is False
    assert payload["gate_checks"]["regime_pass_rate"] is True
    assert payload["safety"]["paper_queue_status"] == "LOCKED"
    assert payload["safety"]["live_status"] == "FROZEN"
    assert payload["safety"]["paper_auto_start"] is False
    assert payload["safety"]["real_broker_api_called"] is False
    assert payload["safety"]["real_orders_created"] is False
    assert "btc_candidate_bounded_retest_event_profit_factor_failed" in payload["blockers"]
    assert "btc_candidate_bounded_retest_walk_forward_pass_rate_failed" in payload["blockers"]


def test_btc_candidate_bounded_retest_outcome_missing_output_stays_fail_closed(tmp_path: Path) -> None:
    payload = build_btc_candidate_bounded_retest_outcome_report(
        repo_root=tmp_path,
        run_dir=Path("artifacts/btc_canonical/missing_retest"),
        generated_at="2026-06-04T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "missing_retest_output"
    assert payload["candidate_gate_passed"] is False
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["same_retest_repeat_allowed"] is False
    assert payload["next_required_action"] == "rerun_bounded_retest_to_completion"
    assert payload["safety"]["paper_queue_status"] == "LOCKED"
    assert payload["safety"]["live_status"] == "FROZEN"
    assert payload["blockers"] == ["btc_candidate_bounded_retest_output_missing"]


def test_btc_candidate_bounded_retest_outcome_schema_rejects_promotion_unlock() -> None:
    payload = build_btc_candidate_bounded_retest_outcome_report(generated_at="2026-06-04T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["promotion_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_candidate_bounded_retest_outcome_schema_rejects_paper_live_unlock() -> None:
    payload = build_btc_candidate_bounded_retest_outcome_report(generated_at="2026-06-04T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["safety"]["paper_queue_status"] = "PENDING_REVIEW"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
