from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_etf_strategy_validation_evidence_audit import (
    build_us_etf_strategy_validation_evidence_audit,
)


SCHEMA = Path("schemas/us_etf_strategy_validation_evidence_audit.schema.json")


def test_validation_evidence_audit_maps_current_data_quality_blocker(tmp_path: Path) -> None:
    payload = build_us_etf_strategy_validation_evidence_audit(
        repo_root=Path("."),
        output=tmp_path / "out/audit.json",
        markdown_output=tmp_path / "out/audit.md",
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "validation_evidence_audit_blocked_data_quality"
    assert payload["gate_status"] == "blocked_data_quality"
    assert payload["summary"]["requirement_count"] == 12
    assert payload["summary"]["paper_or_live_unlock_allowed"] is False
    assert payload["summary"]["live_order_allowed"] is False
    requirements = {item["requirement_id"]: item for item in payload["requirements"]}
    assert requirements["data_quality_pit"]["status"] == "blocked"
    assert requirements["data_quality_pit"]["gate_check_key"] == "data_coverage_and_quality"
    assert requirements["cost_stress"]["status"] == "complete"
    assert requirements["execution_guardrails"]["status"] == "complete"
    assert payload["guardrails"]["audit_only"] is True
    assert payload["guardrails"]["live_order_allowed"] is False


def test_validation_evidence_audit_ready_when_gate_passes_all_requirements(tmp_path: Path) -> None:
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(_gate_payload(status="validation_passed_for_forward_observation")), encoding="utf-8")

    payload = build_us_etf_strategy_validation_evidence_audit(
        repo_root=tmp_path,
        validation_gate_report=gate_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "validation_evidence_audit_ready_for_forward_observation"
    assert payload["summary"]["complete_count"] == 12
    assert payload["incomplete_requirements"] == []
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_validation_evidence_audit_incomplete_when_gate_check_missing(tmp_path: Path) -> None:
    gate = _gate_payload(status="research_only")
    del gate["checks"]["cost_stress"]
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")

    payload = build_us_etf_strategy_validation_evidence_audit(
        repo_root=tmp_path,
        validation_gate_report=gate_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "validation_evidence_audit_incomplete"
    requirements = {item["requirement_id"]: item for item in payload["requirements"]}
    assert requirements["cost_stress"]["status"] == "incomplete"
    assert requirements["cost_stress"]["blocker"] == "validation_gate_check_missing:cost_stress"


def test_validation_evidence_audit_schema_rejects_live_unlock(tmp_path: Path) -> None:
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(_gate_payload(status="validation_passed_for_forward_observation")), encoding="utf-8")
    payload = build_us_etf_strategy_validation_evidence_audit(
        repo_root=tmp_path,
        validation_gate_report=gate_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _gate_payload(*, status: str) -> dict:
    checks = {
        "data_coverage_and_quality": {"passed": True},
        "no_future_function": {"passed": True},
        "original_strategy_semantics": {"passed": True},
        "benchmark_coverage": {"passed": True},
        "standard_metrics": {"passed": True},
        "cost_stress": {"passed": True},
        "walk_forward": {"passed": True},
        "parameter_stability": {"passed": True},
        "capacity": {"passed": True},
        "return_attribution": {"passed": True},
        "strategy_card": {"passed": True},
        "guardrails": {"passed": True},
    }
    source_reports = {
        "research_report": "research.json",
        "top_validation_report": "validation.json",
        "cost_stress_report": "cost.json",
        "walk_forward_report": "walk.json",
        "year_attribution_report": "years.json",
        "data_freshness_report": "freshness.json",
        "kline_quality_report": "kline.json",
        "fred_preflight_report": "fred.json",
        "pit_intake_status_report": "pit.json",
        "pit_bundle_acceptance_report": "acceptance.json",
        "strategy_card": "card.md",
    }
    return {
        "status": status,
        "decision": "allow_or_continue_forward_observation_only",
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "checks": checks,
        "source_reports": source_reports,
        "blockers": [],
    }


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
