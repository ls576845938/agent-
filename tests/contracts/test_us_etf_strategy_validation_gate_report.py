from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_etf_strategy_validation_gate_report import (
    ALLOWED_STATUSES,
    build_us_etf_strategy_validation_gate_report,
)


SOURCE_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
DATA_ROOT = Path("artifacts/us_equity_data_status/latest")
LINEAGE_ROOT = Path("artifacts/us_equity_data_lineage/latest")
CARD = Path("docs/strategy_cards/us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x.md")
SCHEMA = Path("schemas/us_etf_strategy_validation_gate_report.schema.json")


def test_us_etf_strategy_validation_gate_blocks_current_data_quality(tmp_path: Path) -> None:
    payload = build_us_etf_strategy_validation_gate_report(
        repo_root=Path("."),
        output=tmp_path / "out/test_us_etf_strategy_validation_gate_report.json",
        markdown_output=tmp_path / "out/test_us_etf_strategy_validation_gate_report.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_etf_strategy_validation_gate_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "blocked_data_quality"
    assert set(payload["allowed_statuses"]) == ALLOWED_STATUSES
    assert payload["paper_ready"] is False
    assert payload["live_ready"] is False
    assert payload["paper_simulation_allowed"] is False
    assert payload["live_order_allowed"] is False
    assert payload["strategy_validation_gate_is_not_execution_permission"] is True
    assert payload["checks"]["data_coverage_and_quality"]["passed"] is False
    assert "point_in_time_universe_not_confirmed" in payload["checks"]["data_coverage_and_quality"]["matched_data_quality_blockers"]
    assert payload["checks"]["data_coverage_and_quality"]["kline_quality_status"] in {"pass", "warn"}
    assert payload["checks"]["data_coverage_and_quality"]["data_freshness_status"] == "pass"
    assert payload["checks"]["data_coverage_and_quality"]["pit_intake_status"] == "production_pit_data_intake_blocked"
    assert payload["checks"]["data_coverage_and_quality"]["pit_bundle_acceptance_status"] == "acceptance_blocked"
    assert payload["checks"]["cost_stress"]["passed"] is True
    assert payload["checks"]["walk_forward"]["passed"] is True
    assert payload["checks"]["parameter_stability"]["passed"] is True
    assert payload["checks"]["capacity"]["passed"] is True
    assert payload["checks"]["return_attribution"]["passed"] is True
    assert payload["guardrails"]["validation_gate_only_allows_forward_observation"] is True
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False


def test_us_etf_strategy_validation_gate_can_pass_only_for_forward_observation(tmp_path: Path) -> None:
    _copy_current_reports(tmp_path)
    research_path = tmp_path / SOURCE_ROOT / "us_etf_macro_rotation_research_report.json"
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research["data"]["promotion_clean"] = True
    research["blockers"] = [
        blocker
        for blocker in research["blockers"]
        if blocker
        not in {
            "us_equity_data_not_promotion_clean",
            "point_in_time_universe_not_confirmed",
            "corporate_action_event_source_missing",
            "membership_events_missing",
            "delisting_coverage_missing",
            "survivorship_status_not_clean",
            "data_lineage_not_promotion_clean",
            "adjustment_reproducibility_missing",
            "price_adjustment_reproducibility_missing",
            "historical_membership_missing",
        }
    ]
    validation_path = tmp_path / SOURCE_ROOT / "us_etf_top1_higher_vol_20pct_15x_validation_report.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    rows = validation["standardized_report_schema"]["rows"]
    rows.append(
        {
            "id": "SHV",
            "CAGR": 0.03,
            "Vol": 0.01,
            "Sharpe": 1.0,
            "MDD": -0.01,
            "Calmar": 3.0,
            "Turnover": 0.0,
            "CostStressedReturn": 0.2,
            "LiquidityPass": True,
        }
    )
    validation_path.write_text(json.dumps(validation), encoding="utf-8")
    research_path.write_text(json.dumps(research), encoding="utf-8")
    _write_pit_ready(tmp_path)

    payload = build_us_etf_strategy_validation_gate_report(
        repo_root=tmp_path,
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"),
        markdown_output=Path("md/gate.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "validation_passed_for_forward_observation"
    _validate_schema(payload)
    assert payload["allowed_next_action"] == "forward_observation_only"
    assert payload["forward_observation_allowed"] is True
    assert payload["paper_ready"] is False
    assert payload["live_ready"] is False
    assert payload["paper_simulation_allowed"] is False
    assert payload["live_order_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False


def test_us_etf_strategy_validation_gate_rejects_missing_standard_metrics(tmp_path: Path) -> None:
    _copy_current_reports(tmp_path)
    research_path = tmp_path / SOURCE_ROOT / "us_etf_macro_rotation_research_report.json"
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research["data"]["promotion_clean"] = True
    research["blockers"] = []
    research_path.write_text(json.dumps(research), encoding="utf-8")
    _write_pit_ready(tmp_path)
    validation_path = tmp_path / SOURCE_ROOT / "us_etf_top1_higher_vol_20pct_15x_validation_report.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["standardized_report_schema"]["rows"] = [{"id": "SPY", "CAGR": 0.1}]
    validation_path.write_text(json.dumps(validation), encoding="utf-8")

    payload = build_us_etf_strategy_validation_gate_report(
        repo_root=tmp_path,
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"),
        markdown_output=Path("md/gate.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "research_only"
    _validate_schema(payload)
    assert payload["checks"]["standard_metrics"]["passed"] is False
    assert payload["live_order_allowed"] is False


def test_us_etf_strategy_validation_gate_blocks_failed_kline_quality(tmp_path: Path) -> None:
    _copy_current_reports(tmp_path)
    research_path = tmp_path / SOURCE_ROOT / "us_etf_macro_rotation_research_report.json"
    research = json.loads(research_path.read_text(encoding="utf-8"))
    research["data"]["promotion_clean"] = True
    research["blockers"] = []
    research_path.write_text(json.dumps(research), encoding="utf-8")
    _write_pit_ready(tmp_path)
    _ensure_cash_benchmark(tmp_path)
    kline_path = tmp_path / DATA_ROOT / "us_equity_etf_kline_quality_daily_report.json"
    kline = json.loads(kline_path.read_text(encoding="utf-8"))
    kline["status"] = "blocked"
    kline["blockers"] = ["SPY:extreme_daily_return_rows:1"]
    kline_path.write_text(json.dumps(kline), encoding="utf-8")

    payload = build_us_etf_strategy_validation_gate_report(
        repo_root=tmp_path,
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"),
        markdown_output=Path("md/gate.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked_data_quality"
    _validate_schema(payload)
    assert payload["checks"]["data_coverage_and_quality"]["kline_quality_status"] == "blocked"
    assert "SPY:extreme_daily_return_rows:1" in payload["checks"]["data_coverage_and_quality"]["kline_quality_blockers"]


def test_us_etf_strategy_validation_gate_schema_rejects_paper_ready(tmp_path: Path) -> None:
    _copy_current_reports(tmp_path)
    payload = build_us_etf_strategy_validation_gate_report(
        repo_root=tmp_path,
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"),
        markdown_output=Path("md/gate.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["paper_ready"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_ready=true")


def _copy_current_reports(tmp_path: Path) -> None:
    paths = [
        SOURCE_ROOT / "us_etf_macro_rotation_research_report.json",
        SOURCE_ROOT / "us_etf_top1_higher_vol_20pct_15x_validation_report.json",
        SOURCE_ROOT / "us_etf_macro_rotation_cost_stress_report.json",
        SOURCE_ROOT / "us_etf_macro_rotation_walk_forward_stability_report.json",
        SOURCE_ROOT / "us_etf_macro_rotation_year_attribution_report.json",
        DATA_ROOT / "tiingo_eod_import_report.json",
        DATA_ROOT / "us_equity_data_freshness_daily_report.json",
        DATA_ROOT / "us_equity_etf_kline_quality_daily_report.json",
        DATA_ROOT / "us_equity_fred_macro_preflight_report.json",
        LINEAGE_ROOT / "us_equity_pit_data_intake_status_report.json",
        LINEAGE_ROOT / "us_equity_pit_bundle_acceptance_run_report.json",
        CARD,
    ]
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _ensure_cash_benchmark(tmp_path: Path) -> None:
    validation_path = tmp_path / SOURCE_ROOT / "us_etf_top1_higher_vol_20pct_15x_validation_report.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    rows = validation["standardized_report_schema"]["rows"]
    if not any(row.get("id") == "SHV" for row in rows):
        rows.append(
            {
                "id": "SHV",
                "CAGR": 0.03,
                "Vol": 0.01,
                "Sharpe": 1.0,
                "MDD": -0.01,
                "Calmar": 3.0,
                "Turnover": 0.0,
                "CostStressedReturn": 0.2,
                "LiquidityPass": True,
            }
        )
    validation_path.write_text(json.dumps(validation), encoding="utf-8")


def _write_pit_ready(tmp_path: Path) -> None:
    pit_status = tmp_path / LINEAGE_ROOT / "us_equity_pit_data_intake_status_report.json"
    pit_status.parent.mkdir(parents=True, exist_ok=True)
    pit_status.write_text(
        json.dumps(
            {
                "status": "production_pit_data_intake_ready",
                "current_blocking_stage": "none",
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    acceptance = tmp_path / LINEAGE_ROOT / "us_equity_pit_bundle_acceptance_run_report.json"
    acceptance.write_text(
        json.dumps(
            {
                "status": "acceptance_ready_for_manual_config_apply",
                "current_blocking_step": "none",
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
