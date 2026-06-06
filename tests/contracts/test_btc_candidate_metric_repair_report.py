from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_candidate_metric_repair_report import build_btc_candidate_metric_repair_report


SCHEMA = Path("schemas/btc_candidate_metric_repair_report.schema.json")
REPORT = Path("artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json")


def test_btc_candidate_metric_repair_report_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_candidate_metric_repair_report_blocks_paper_review() -> None:
    payload = build_btc_candidate_metric_repair_report(generated_at="2026-05-23T00:00:00Z")

    assert payload["status"] == "needs_metric_repair"
    assert payload["promotion_allowed"] is False
    assert payload["paper_review_pending_allowed"] is False
    assert payload["best_candidate"]["strategy_id"] == "btc_perp_dual_trend_v4_eventpf_wf"
    assert payload["failed_metrics"] == ["event_profit_factor", "walk_forward_pass_rate"]
    assert payload["fold_failure_diagnostics"]["failed_folds"] == [3, 4]
    assert payload["ablation_diagnostics"]["short_reintroduction_rejected"] is True
    action_names = [item["name"] for item in payload["recommended_repair_actions"]]
    assert action_names[0] == "run_bounded_event_pf_retest"
    assert "repair_late_walk_forward_folds" in action_names
    assert "do_not_promote_on_ordinary_profit_factor" in action_names
    assert payload["safety"]["paper_or_live_unlock_allowed"] is False
    assert payload["safety"]["ordinary_profit_factor_diagnostic_only"] is True
    assert "btc_candidate_metric_repair_event_profit_factor_failed" in payload["blockers"]


def test_btc_candidate_metric_repair_report_can_represent_passing_candidate(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json",
        {
            "status": "pass",
            "paper_review_pending_allowed": True,
            "candidate_repair_plan": {
                "stages": [
                    {"name": "perpetual_data_cost_evidence", "status": "complete", "blockers": []},
                    {"name": "internal_metric_gate", "status": "complete", "blockers": []},
                    {"name": "paper_review_queue", "status": "ready", "blockers": []},
                ]
            },
            "best_available_candidate": {
                "strategy_id": "btc_candidate_pass",
                "source_run_dir": "artifacts/btc_candidate_validation/pass",
                "status": "candidate_passed_internal_gate",
                "passed_metric_count": 8,
                "required_metric_count": 8,
                "failed_metrics": [],
                "metrics": {
                    "event_profit_factor": 1.2,
                    "walk_forward_pass_rate": 1.0,
                    "regime_pass_rate": 1.0,
                    "profit_factor": 1.4,
                    "dsr": 1.0,
                    "pbo": 0.4,
                    "max_drawdown": -4.0,
                    "trade_count": 20,
                    "fill_count": 50,
                },
                "thresholds": {
                    "event_profit_factor": 1.15,
                    "walk_forward_pass_rate": 0.8,
                    "regime_pass_rate": 0.75,
                },
            },
            "candidate_gate_thresholds": {
                "event_profit_factor": 1.15,
                "walk_forward_pass_rate": 0.8,
                "regime_pass_rate": 0.75,
                "cost_stress_required": True,
            },
            "metric_failures": [],
        },
    )
    payload = build_btc_candidate_metric_repair_report(
        repo_root=tmp_path,
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "candidate_metric_gate_passed"
    assert payload["promotion_allowed"] is True
    assert payload["paper_review_pending_allowed"] is True
    assert payload["failed_metrics"] == []
    assert payload["blockers"] == []


def test_btc_candidate_metric_repair_schema_rejects_unlock_with_metric_failures() -> None:
    payload = build_btc_candidate_metric_repair_report(generated_at="2026-05-23T00:00:00Z")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["status"] = "candidate_metric_gate_passed"
    payload["promotion_allowed"] = True
    payload["paper_review_pending_allowed"] = True
    payload["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
