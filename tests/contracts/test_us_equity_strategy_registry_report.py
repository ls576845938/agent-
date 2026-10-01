from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_strategy_registry_report import build_us_equity_strategy_registry_report
from scripts.build_us_equity_strategy_production_line_report import STAGE_ORDER


SCHEMA = Path("schemas/us_equity_strategy_registry_report.schema.json")


def test_current_registry_passes_strategy_pool_contract() -> None:
    payload = build_us_equity_strategy_registry_report(
        output=Path("artifacts/tmp/us_equity_strategy_registry_report_test.json"),
        markdown_output=Path("artifacts/tmp/us_equity_strategy_registry_report_test.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "pass"
    _validate_schema(payload)
    assert payload["strategy_count"] >= 6
    assert payload["primary_candidate_count"] == 1
    assert payload["missing_required_families"] == []
    assert payload["formal_candidate_source_report_contract"]["passed"] is True
    assert payload["formal_candidate_source_report_contract"]["candidate_count"] == payload["formal_candidate_count"]
    assert payload["formal_candidate_source_report_contract"]["missing_required_keys_by_strategy"] == {}
    assert all(row["strategy_card_exists"] is True for row in payload["strategy_rows"])
    assert payload["guardrails"]["unregistered_strategy_promotion_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed_by_registry"] is False
    families = {row["family"] for row in payload["strategy_rows"]}
    assert "dual_momentum" in families
    assert "absolute_momentum" in families
    assert "topn_etf_rotation" in families
    assert "regime_overlay" in families
    assert "151_trading_strategies_migration" in families
    hypothesis_rows = [
        row
        for row in payload["strategy_rows"]
        if row["status"] == "hypothesis_registered_only"
        and row["current_stage"] == "strategy_hypothesis_registration"
    ]
    assert hypothesis_rows
    assert all(row["design_spec_exists"] is True for row in hypothesis_rows)
    assert all(row["design_spec_registry_id_matches"] is True for row in hypothesis_rows)


def test_registry_blocks_missing_strategy_contract_fields(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["strategies"] = [
        {
            "strategy_id": "bad_strategy",
            "family": "dual_momentum",
            "status": "hypothesis_registered_only",
            "current_stage": "strategy_hypothesis_registration",
            "primary_candidate": True,
            "hypothesis": {"alpha_sources": ["momentum"]},
            "source_reports": {},
            "guardrails": {"paper_ready": False, "live_ready": False},
        }
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")

    payload = build_us_equity_strategy_registry_report(
        repo_root=tmp_path,
        registry_path=path,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert "us_equity_strategy_registry_required_families_missing" in payload["blockers"]
    assert any("missing_parameter_space:bad_strategy" in item for item in payload["blockers"])
    assert any("missing_hypothesis_risk_premia_explanation:bad_strategy" in item for item in payload["blockers"])
    assert (tmp_path / "report.md").exists()


def test_registry_blocks_ready_or_live_flags(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["strategies"] = [
        {
            "strategy_id": "unsafe_strategy",
            "family": "us_etf_macro_momentum_rotation",
            "status": "hypothesis_registered_only",
            "current_stage": "strategy_hypothesis_registration",
            "primary_candidate": True,
            "hypothesis": {
                "alpha_sources": ["momentum"],
                "risk_premia_explanation": "Test only.",
                "known_risks": ["overfit"],
            },
            "parameter_space": {"lookback": [63]},
            "data_dependencies": {"prices": "EOD"},
            "cost_model": {"turnover_cost_bps": [10]},
            "failure_conditions": ["fails costs"],
            "source_reports": {},
            "guardrails": {"paper_ready": True, "live_ready": False, "backtest_allowed_without_registration": False},
        }
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")

    payload = build_us_equity_strategy_registry_report(
        repo_root=tmp_path,
        registry_path=path,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert any("forbidden_guardrail_true:unsafe_strategy.paper_ready" in item for item in payload["blockers"])
    assert payload["guardrails"]["live_order_allowed"] is False


def test_registry_blocks_hypothesis_without_design_spec_report(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["strategies"] = [
        {
            "strategy_id": "hypothesis_without_design",
            "family": "dual_momentum",
            "status": "hypothesis_registered_only",
            "current_stage": "strategy_hypothesis_registration",
            "primary_candidate": True,
            "strategy_card": "docs/card.md",
            "hypothesis": {
                "alpha_sources": ["momentum"],
                "risk_premia_explanation": "Test only.",
                "known_risks": ["overfit"],
            },
            "parameter_space": {"lookback": [63]},
            "data_dependencies": {"prices": "EOD"},
            "cost_model": {"turnover_cost_bps": [10]},
            "failure_conditions": ["fails costs"],
            "source_reports": {},
            "guardrails": {
                "paper_ready": False,
                "live_ready": False,
                "backtest_allowed_without_registration": False,
            },
        }
    ]
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/card.md").write_text("# Card", encoding="utf-8")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")

    payload = build_us_equity_strategy_registry_report(
        repo_root=tmp_path,
        registry_path=path,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert any(
        "design_spec_report_missing:hypothesis_without_design" in item
        for item in payload["blockers"]
    )


def test_registry_blocks_hypothesis_design_spec_id_mismatch(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["strategies"] = [
        {
            "strategy_id": "hypothesis_with_bad_design",
            "family": "dual_momentum",
            "status": "hypothesis_registered_only",
            "current_stage": "strategy_hypothesis_registration",
            "primary_candidate": True,
            "strategy_card": "docs/card.md",
            "design_spec_report": "artifacts/design.json",
            "hypothesis": {
                "alpha_sources": ["momentum"],
                "risk_premia_explanation": "Test only.",
                "known_risks": ["overfit"],
            },
            "parameter_space": {"lookback": [63]},
            "data_dependencies": {"prices": "EOD"},
            "cost_model": {"turnover_cost_bps": [10]},
            "failure_conditions": ["fails costs"],
            "source_reports": {},
            "guardrails": {
                "paper_ready": False,
                "live_ready": False,
                "backtest_allowed_without_registration": False,
            },
        }
    ]
    (tmp_path / "docs").mkdir()
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "docs/card.md").write_text("# Card", encoding="utf-8")
    (tmp_path / "artifacts/design.json").write_text(
        json.dumps({"registry_strategy_id": "different_id", "status": "design_spec_ready"}),
        encoding="utf-8",
    )
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")

    payload = build_us_equity_strategy_registry_report(
        repo_root=tmp_path,
        registry_path=path,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    row = payload["strategy_rows"][0]
    assert row["design_spec_exists"] is True
    assert row["design_spec_registry_id_matches"] is False
    assert any(
        "design_spec_id_mismatch:hypothesis_with_bad_design" in item
        for item in payload["blockers"]
    )


def test_registry_blocks_formal_candidate_missing_source_report_contract(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["strategies"] = [
        {
            "strategy_id": "formal_without_sources",
            "family": "us_etf_macro_momentum_rotation",
            "status": "forward_observation_only",
            "current_stage": "forward_observation",
            "primary_candidate": True,
            "strategy_card": "docs/card.md",
            "hypothesis": {
                "alpha_sources": ["momentum"],
                "risk_premia_explanation": "Test only.",
                "known_risks": ["overfit"],
            },
            "parameter_space": {"lookback": [63]},
            "data_dependencies": {"prices": "EOD"},
            "cost_model": {"turnover_cost_bps": [10]},
            "failure_conditions": ["fails costs"],
            "source_reports": {"research_backtest": "missing.json"},
            "guardrails": {
                "paper_ready": False,
                "live_ready": False,
                "backtest_allowed_without_registration": False,
            },
        }
    ]
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/card.md").write_text("# Card", encoding="utf-8")
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")

    payload = build_us_equity_strategy_registry_report(
        repo_root=tmp_path,
        registry_path=path,
        output=tmp_path / "report.json",
        markdown_output=tmp_path / "report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    row = payload["strategy_rows"][0]
    assert row["source_report_contract_passed"] is False
    assert "data_ingestion" in row["missing_required_source_report_keys"]
    assert payload["formal_candidate_source_report_contract"]["passed"] is False
    assert "formal_without_sources" in payload["formal_candidate_source_report_contract"]["missing_required_keys_by_strategy"]
    assert any(
        "formal_source_report_contract_failed:formal_without_sources" in item
        for item in payload["blockers"]
    )


def test_registry_schema_rejects_live_order_allowed() -> None:
    payload = build_us_equity_strategy_registry_report(
        output=Path("artifacts/tmp/us_equity_strategy_registry_report_test.json"),
        markdown_output=Path("artifacts/tmp/us_equity_strategy_registry_report_test.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _base_registry() -> dict[str, object]:
    return {
        "schema_version": "us_equity_strategy_registry_v1",
        "asset": "us_equity",
        "policy": {
            "unregistered_strategy_promotion_allowed": False,
            "paper_or_live_unlock_allowed_by_registry": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "live_order_allowed": False,
        },
        "production_line_order": STAGE_ORDER,
        "strategies": [],
    }


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
