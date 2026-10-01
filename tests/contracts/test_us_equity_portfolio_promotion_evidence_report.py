from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_portfolio_promotion_evidence_report import (
    build_us_equity_portfolio_promotion_evidence_report,
    write_us_equity_portfolio_promotion_evidence_report,
)


SCHEMA = Path("schemas/us_equity_portfolio_promotion_evidence_report.schema.json")


def test_portfolio_promotion_evidence_schema_file_exists() -> None:
    assert SCHEMA.exists()


def test_missing_inputs_fail_closed(tmp_path: Path) -> None:
    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )

    _validate_schema(report)
    assert report["status"] == "promotion_evidence_blocked"
    assert report["promotion_ready"] is False
    assert report["summary"]["promotion_ready"] is False
    assert report["summary"]["fixture_evidence_present"] is False
    assert report["summary"]["candidate_evidence_present"] is False
    assert report["summary"]["promotion_evidence_present"] is False
    assert report["summary"]["paper_queue_status"] == "locked"
    assert report["summary"]["paper_simulation_allowed"] is False
    assert report["summary"]["live_order_allowed"] is False
    assert "portfolio_event_ledger" in report["summary"]["blocked_layer_ids"]
    assert report["summary"]["next_required_evidence"]
    assert report["paper_simulation_allowed"] is False
    assert report["live_order_allowed"] is False
    gaps = report["evidence_gap_summary"]
    tiers = {item["tier_id"]: item for item in report["evidence_tiers"]}
    assert set(tiers) == {"fixture", "candidate", "promotion"}
    assert tiers["fixture"]["classification"] == "fixture_plumbing_only"
    assert tiers["fixture"]["can_promote"] is False
    assert tiers["fixture"]["can_unlock_paper_or_live"] is False
    assert tiers["candidate"]["classification"] == "strategy_candidate_research"
    assert tiers["candidate"]["can_promote"] is False
    assert tiers["candidate"]["can_unlock_paper_or_live"] is False
    assert tiers["promotion"]["classification"] == "portfolio_promotion_evidence"
    assert tiers["promotion"]["can_promote"] is False
    assert tiers["promotion"]["can_unlock_paper_or_live"] is False
    assert "portfolio_event_ledger" in tiers["promotion"]["blocked_layers"]
    assert tiers["promotion"]["next_required_evidence"]
    assert gaps["fixture_evidence"]["present"] is False
    assert gaps["fixture_evidence"]["can_promote"] is False
    assert gaps["candidate_evidence"]["present"] is False
    assert gaps["candidate_evidence"]["can_promote_without_portfolio_ledger"] is False
    assert gaps["promotion_evidence"]["ready"] is False
    assert "portfolio_event_ledger" in gaps["promotion_evidence"]["missing_promotion_layer_ids"]
    assert "portfolio_walk_forward" in gaps["promotion_evidence"]["missing_promotion_layer_ids"]
    assert "portfolio_construction" in gaps["promotion_evidence"]["missing_promotion_layer_ids"]
    assert gaps["promotion_evidence"]["next_required_evidence"]
    assert "portfolio_fixture_ledger_missing" in report["blockers"]
    assert "strategy_validation_gate_not_passed:missing" in report["blockers"]
    assert "portfolio_event_ledger_not_passed:missing" in report["blockers"]
    assert "event_driven_backtest_flow_missing" in report["blockers"]
    assert "portfolio_walk_forward_report_missing" in report["blockers"]
    matrix = {item["source_id"]: item for item in report["evidence_source_matrix"]}
    assert {"portfolio_fixture_event_ledger", "strategy_validation_gate", "portfolio_event_ledger"} <= set(matrix)
    assert matrix["portfolio_fixture_event_ledger"]["evidence_tier"] == "fixture"
    assert matrix["portfolio_fixture_event_ledger"]["required_for_promotion"] is False
    assert matrix["portfolio_fixture_event_ledger"]["promotion_eligible"] is False
    assert matrix["strategy_validation_gate"]["evidence_tier"] == "candidate"
    assert matrix["strategy_validation_gate"]["promotion_eligible"] is False
    assert matrix["portfolio_event_ledger"]["evidence_tier"] == "promotion"
    assert matrix["portfolio_event_ledger"]["passed"] is False
    assert all(row["can_unlock_paper_or_live"] is False for row in matrix.values())


def test_fixture_ledger_cannot_be_promotion_evidence(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json",
        {
            "source_type": "fixture",
            "promotion_evidence": True,
        },
    )

    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )

    layer = report["evidence_layers"]["fixture_isolation"]
    assert layer["passed"] is False
    assert layer["promotion_eligible"] is False
    assert "portfolio_fixture_ledger_wrongly_marked_promotion_evidence" in report["blockers"]
    assert report["evidence_classification"]["fixture_can_promote"] is False


def test_fixture_candidate_and_missing_portfolio_ledger_are_separate(tmp_path: Path) -> None:
    _write_default_fixture_ledger(tmp_path)
    _write_strategy_validation_gate(tmp_path, status="validation_passed_for_forward_observation")
    _write_walk_forward(tmp_path)
    _write_cost_stress(tmp_path)
    _write_json(
        tmp_path / "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        {
            "portfolio_run_id": "fixture_portfolio",
            "event_ledger_status": {"status": "missing"},
            "ledger_validation": {
                "source_type": "fixture",
                "fills_available": True,
                "ledger_pnl_available": True,
                "cost_model_available": True,
                "cash_conservation_pass": True,
                "position_conservation_pass": True,
                "event_ledger_candidate": False,
            },
            "portfolio_evidence_maturity": {
                "cost_stress_available": False,
                "exposure_report_available": False,
            },
            "blockers": ["us_equity_sector_exposure_missing"],
        },
    )

    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )

    assert report["evidence_layers"]["fixture_isolation"]["passed"] is True
    assert report["evidence_layers"]["candidate_strategy_validation"]["passed"] is True
    assert report["evidence_layers"]["portfolio_event_ledger"]["passed"] is False
    assert report["evidence_layers"]["event_driven_backtest"]["passed"] is False
    matrix = {item["source_id"]: item for item in report["evidence_source_matrix"]}
    assert matrix["portfolio_fixture_event_ledger"]["passed"] is True
    assert matrix["portfolio_fixture_event_ledger"]["promotion_eligible"] is False
    assert matrix["strategy_validation_gate"]["passed"] is True
    assert matrix["strategy_validation_gate"]["promotion_eligible"] is False
    assert matrix["portfolio_event_ledger"]["promotion_eligible"] is False
    assert "portfolio_event_ledger_source_type_not_production:fixture" in matrix["portfolio_event_ledger"]["blockers"]
    gaps = report["evidence_gap_summary"]
    assert gaps["fixture_evidence"]["present"] is True
    assert gaps["fixture_evidence"]["can_promote"] is False
    assert gaps["candidate_evidence"]["present"] is True
    assert gaps["candidate_evidence"]["can_promote_without_portfolio_ledger"] is False
    assert "portfolio_event_ledger" in gaps["promotion_evidence"]["missing_promotion_layer_ids"]
    assert "event_driven_backtest" in gaps["promotion_evidence"]["missing_promotion_layer_ids"]
    assert "portfolio_event_ledger_not_passed:missing" in report["blockers"]
    assert "portfolio_event_ledger_source_type_not_production:fixture" in report["blockers"]
    assert "event_driven_backtest_flow_missing" in report["blockers"]
    assert "portfolio_cost_stress_missing_from_portfolio_layer" in report["blockers"]
    assert "us_equity_sector_exposure_missing" in report["blockers"]
    assert report["promotion_ready"] is False


def test_missing_cost_stress_and_walk_forward_fail_closed(tmp_path: Path) -> None:
    _write_default_fixture_ledger(tmp_path)
    _write_strategy_validation_gate(tmp_path, status="validation_passed_for_forward_observation")
    _write_production_portfolio_canonical(tmp_path, cost_stress_available=False)

    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )

    assert report["evidence_layers"]["portfolio_event_ledger"]["passed"] is True
    assert report["evidence_layers"]["event_driven_backtest"]["passed"] is True
    assert report["evidence_layers"]["ledger_pnl"]["passed"] is True
    assert report["evidence_layers"]["portfolio_construction"]["passed"] is True
    assert report["evidence_layers"]["portfolio_cost_stress"]["passed"] is False
    assert report["evidence_layers"]["portfolio_walk_forward"]["passed"] is False
    assert "portfolio_cost_stress_missing_from_portfolio_layer" in report["blockers"]
    assert "strategy_cost_stress_report_missing" in report["blockers"]
    assert "portfolio_walk_forward_report_missing" in report["blockers"]
    assert report["paper_queue_status"] == "locked"
    assert report["live_status"] == "frozen"


def test_complete_synthetic_promotion_evidence_still_does_not_unlock_live(tmp_path: Path) -> None:
    _write_default_fixture_ledger(tmp_path)
    _write_strategy_validation_gate(tmp_path, status="validation_passed_for_forward_observation")
    _write_production_portfolio_canonical(tmp_path, cost_stress_available=True)
    _write_walk_forward(tmp_path)
    _write_cost_stress(tmp_path)

    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )

    _validate_schema(report)
    assert report["status"] == "promotion_evidence_ready"
    assert report["promotion_ready"] is True
    assert report["summary"]["promotion_ready"] is True
    assert report["summary"]["fixture_evidence_present"] is True
    assert report["summary"]["candidate_evidence_present"] is True
    assert report["summary"]["promotion_evidence_present"] is True
    assert report["summary"]["blocked_layer_count"] == 0
    assert report["summary"]["blocked_layer_ids"] == []
    assert report["summary"]["first_blocker"] == ""
    assert report["summary"]["next_required_evidence"] == []
    assert report["summary"]["paper_queue_status"] == "locked"
    assert report["summary"]["paper_simulation_allowed"] is False
    assert report["summary"]["live_order_allowed"] is False
    assert report["blockers"] == []
    assert report["evidence_gap_summary"]["promotion_evidence"]["ready"] is True
    assert report["evidence_gap_summary"]["promotion_evidence"]["blocked_layer_ids"] == []
    assert report["evidence_gap_summary"]["promotion_evidence"]["missing_promotion_layer_ids"] == []
    assert report["evidence_gap_summary"]["promotion_evidence"]["next_required_evidence"] == []
    tiers = {item["tier_id"]: item for item in report["evidence_tiers"]}
    assert tiers["fixture"]["can_promote"] is False
    assert tiers["candidate"]["can_promote"] is False
    assert tiers["promotion"]["can_promote"] is True
    assert tiers["promotion"]["status"] == "ready"
    assert tiers["promotion"]["blocked_layers"] == []
    assert tiers["promotion"]["can_unlock_paper_or_live"] is False
    assert tiers["promotion"]["next_required_evidence"] == ["manual review still required before any paper/live path"]
    matrix = {item["source_id"]: item for item in report["evidence_source_matrix"]}
    assert matrix["portfolio_fixture_event_ledger"]["promotion_eligible"] is False
    assert matrix["strategy_validation_gate"]["promotion_eligible"] is False
    assert matrix["portfolio_event_ledger"]["promotion_eligible"] is True
    assert matrix["promotion_gate"]["promotion_eligible"] is True
    assert all(row["can_unlock_paper_or_live"] is False for row in matrix.values())
    assert report["paper_queue_status"] == "locked"
    assert report["paper_simulation_allowed"] is False
    assert report["live_status"] == "frozen"
    assert report["live_order_allowed"] is False
    assert report["guardrails"]["fixture_or_candidate_report_cannot_unlock_live"] is True

    output = write_us_equity_portfolio_promotion_evidence_report(
        report,
        tmp_path / "artifacts/us_equity_portfolio/latest/portfolio_promotion_evidence_report.json",
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "us_equity_portfolio_promotion_evidence_report_v1"


def test_event_driven_backtest_flow_required_before_promotion(tmp_path: Path) -> None:
    _write_default_fixture_ledger(tmp_path)
    _write_strategy_validation_gate(tmp_path, status="validation_passed_for_forward_observation")
    _write_production_portfolio_canonical(tmp_path, cost_stress_available=True, include_backtest_flow=False)
    _write_walk_forward(tmp_path)
    _write_cost_stress(tmp_path)

    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )

    assert report["status"] == "promotion_evidence_blocked"
    assert report["evidence_layers"]["event_driven_backtest"]["passed"] is False
    assert "event_driven_backtest_flow_missing" in report["blockers"]
    assert "portfolio_promotion_layer_failed:event_driven_backtest" in report["blockers"]


def test_portfolio_construction_controls_required_before_promotion(tmp_path: Path) -> None:
    _write_default_fixture_ledger(tmp_path)
    _write_strategy_validation_gate(tmp_path, status="validation_passed_for_forward_observation")
    _write_production_portfolio_canonical(tmp_path, cost_stress_available=True, include_portfolio_construction=False)
    _write_walk_forward(tmp_path)
    _write_cost_stress(tmp_path)

    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )

    assert report["status"] == "promotion_evidence_blocked"
    layer = report["evidence_layers"]["portfolio_construction"]
    assert layer["passed"] is False
    assert layer["promotion_eligible"] is False
    assert "portfolio_construction_report_missing" in report["blockers"]
    assert "portfolio_construction_missing:volatility_model_available" in report["blockers"]
    assert "portfolio_construction_missing:turnover_report_available" in report["blockers"]
    assert "portfolio_construction_missing:liquidity_report_available" in report["blockers"]
    assert "portfolio_promotion_layer_failed:portfolio_construction" in report["blockers"]


def test_schema_rejects_fixture_tier_promotion_unlock(tmp_path: Path) -> None:
    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )
    report["evidence_tiers"][0]["can_promote"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted fixture tier can_promote=true")


def test_schema_rejects_fixture_source_matrix_promotion_unlock(tmp_path: Path) -> None:
    report = build_us_equity_portfolio_promotion_evidence_report(
        repo_root=tmp_path,
        generated_at="2026-07-08T00:00:00Z",
    )
    matrix = {item["source_id"]: item for item in report["evidence_source_matrix"]}
    matrix["portfolio_fixture_event_ledger"]["promotion_eligible"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(report, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted fixture evidence_source_matrix promotion_eligible=true")


def _write_default_fixture_ledger(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json",
        {
            "source_type": "fixture",
            "promotion_evidence": False,
        },
    )


def _write_strategy_validation_gate(root: Path, *, status: str) -> None:
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
        {
            "status": status,
            "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
            "candidate_variant": "min_adv_10m_to_shv + vol_target_20pct_cap1.5x",
            "paper_ready": False,
            "live_ready": False,
            "checks": {
                "cost_stress": {"passed": True},
                "walk_forward": {"passed": True},
                "parameter_stability": {"passed": True},
                "data_coverage_and_quality": {"passed": True},
            },
        },
    )


def _write_production_portfolio_canonical(
    root: Path,
    *,
    cost_stress_available: bool,
    include_backtest_flow: bool = True,
    include_portfolio_construction: bool = True,
) -> None:
    backtest_flow = {
        "status": "pass",
        "source_type": "production",
        "required_sequence": ["data", "signal", "portfolio", "risk", "order_intent", "simulated_fill", "ledger", "report"],
        "steps": {
            "data": True,
            "signal": True,
            "portfolio": True,
            "risk": True,
            "order_intent": True,
            "simulated_fill": True,
            "ledger": True,
            "report": True,
        },
        "all_steps_present": True,
        "pnl_source": "ledger_fills",
        "blockers": [],
    }
    payload = {
        "portfolio_run_id": "production_portfolio",
        "event_ledger_status": {"status": "pass"},
        "ledger_validation": {
            "source_type": "production",
            "fills_available": True,
            "ledger_pnl_available": True,
            "cost_model_available": True,
            "cash_conservation_pass": True,
            "position_conservation_pass": True,
            "event_ledger_candidate": True,
        },
        "portfolio_evidence_maturity": {
            "cost_stress_available": cost_stress_available,
            "exposure_report_available": True,
        },
        "blockers": [],
    }
    if include_backtest_flow:
        payload["backtest_flow"] = backtest_flow
    if include_portfolio_construction:
        payload["portfolio_construction"] = {
            "status": "pass",
            "source_type": "production",
            "forecast_to_target_position_available": True,
            "volatility_model_available": True,
            "turnover_report_available": True,
            "liquidity_report_available": True,
        }
    _write_json(
        root / "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        payload,
    )


def _write_walk_forward(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json",
        {
            "status": "research_only",
            "walk_forward": {
                "fold_count": 6,
                "stable_enough_for_next_research_stage": True,
            },
        },
    )


def _write_cost_stress(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_cost_stress_report.json",
        {
            "status": "research_only",
            "stress_cost_bps": [10, 25, 50],
            "best_50bps": {"survives_50bps": True},
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
