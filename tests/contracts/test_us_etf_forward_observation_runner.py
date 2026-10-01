from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.run_us_etf_rotation_forward_observation import run_us_etf_rotation_forward_observation


SOURCE_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json")
SCHEMA = Path("schemas/us_etf_forward_observation_roll_report.schema.json")


def _copy_report(tmp_path: Path) -> Path:
    target = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SOURCE_REPORT.read_text(encoding="utf-8"), encoding="utf-8")
    _write_data_gate_reports(tmp_path)
    return target


def test_us_etf_forward_observation_writes_simulated_ledger(tmp_path: Path) -> None:
    report = _copy_report(tmp_path)
    payload = run_us_etf_rotation_forward_observation(
        repo_root=tmp_path,
        validation_report=report.relative_to(tmp_path),
        ledger_root=Path("data/forward_observation/us_etf_rotation_v1"),
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "PASS"
    _validate_schema(payload)
    assert payload["cycle_status"] == "COMPLETED"
    assert payload["strategy_id"] == "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"
    assert payload["candidate_variant"] == "min_adv_10m_to_shv"
    assert payload["account_equity"] == 10_000.0
    assert payload["guardrails"]["simulated_only"] is True
    assert payload["guardrails"]["forward_observation_is_not_alpha_validation"] is True
    assert payload["guardrails"]["long_term_positive_expectancy_proven"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["observation_scope"]["scope"] == "operational_quality_only"
    assert payload["observation_scope"]["not_alpha_validation"] is True
    assert payload["observation_scope"]["cannot_prove_long_term_positive_expectancy"] is True
    assert payload["alpha_validation"]["status"] == "not_evaluated"
    assert payload["alpha_validation"]["alpha_validated"] is False
    assert payload["alpha_validation"]["long_term_positive_expectancy_proven"] is False
    assert payload["alpha_validation"]["unlock_effect"] == "none"
    assert payload["operational_checks"]["status"] == "PASS"
    checks = payload["operational_checks"]["checks"]
    assert checks["target_position_generation"]["passed"] is True
    assert checks["data_freshness"]["passed"] is True
    assert checks["ledger_recalculation"]["passed"] is True
    assert checks["rebalance_rule_no_future_timestamp"]["passed"] is True
    assert checks["cost_and_financing_estimate_consistency"]["passed"] is True
    assert checks["target_change_explainability"]["passed"] is True
    assert payload["target_position"]["target_count"] >= 1
    assert payload["rebalance"]["estimated_trade_notional"] > 0.0
    assert payload["rebalance"]["estimated_slippage"] > 0.0
    assert payload["reconciliation"]["passed"] is True

    ledger_root = tmp_path / "data/forward_observation/us_etf_rotation_v1"
    assert (ledger_root / "target_positions.jsonl").exists()
    assert (ledger_root / "fills.jsonl").exists()
    assert (ledger_root / "portfolio_snapshots.jsonl").exists()
    state = json.loads((ledger_root / "validation_state.json").read_text(encoding="utf-8"))
    assert state["days_completed"] == 1
    assert state["live_order_allowed"] is False


def test_us_etf_forward_observation_is_idempotent(tmp_path: Path) -> None:
    report = _copy_report(tmp_path)
    kwargs = {
        "repo_root": tmp_path,
        "validation_report": report.relative_to(tmp_path),
        "ledger_root": Path("data/forward_observation/us_etf_rotation_v1"),
        "output": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
        "generated_at": "2026-06-25T00:00:00Z",
    }
    first = run_us_etf_rotation_forward_observation(**kwargs)
    second = run_us_etf_rotation_forward_observation(**kwargs)

    assert first["cycle_status"] == "COMPLETED"
    assert second["cycle_status"] == "SKIPPED_ALREADY_COMPLETED"
    _validate_schema(second)
    assert second["operational_checks"]["status"] == "PASS"
    assert second["alpha_validation"]["alpha_validated"] is False
    ledger_root = tmp_path / "data/forward_observation/us_etf_rotation_v1"
    assert len((ledger_root / "target_positions.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_us_etf_forward_observation_blocks_paper_or_live_ledger_root(tmp_path: Path) -> None:
    report = _copy_report(tmp_path)
    payload = run_us_etf_rotation_forward_observation(
        repo_root=tmp_path,
        validation_report=report.relative_to(tmp_path),
        ledger_root=Path("data/paper_ledger/us_etf_rotation_v1"),
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    _validate_schema(payload)
    assert "us_etf_forward_ledger_root_forbidden" in payload["blockers"]
    assert not (tmp_path / "data/paper_ledger/us_etf_rotation_v1/fills.jsonl").exists()


def test_us_etf_forward_observation_blocks_stale_target_without_writing_fills(tmp_path: Path) -> None:
    report = _copy_report(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["small_account_10k_profile"]["constrained_latest_target"]["date"] = "2026-01-01"
    report.write_text(json.dumps(payload), encoding="utf-8")

    result = run_us_etf_rotation_forward_observation(
        repo_root=tmp_path,
        validation_report=report.relative_to(tmp_path),
        ledger_root=Path("data/forward_observation/us_etf_rotation_v1"),
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert result["status"] == "BLOCKED"
    _validate_schema(result)
    assert result["cycle_status"] == "OPERATIONAL_CHECK_FAILED"
    assert result["operational_checks"]["scope"] == "operational_quality_only"
    assert result["operational_checks"]["not_alpha_validation"] is True
    assert result["operational_checks"]["checks"]["data_freshness"]["passed"] is False
    assert "us_etf_forward_observation_data_freshness_failed" in result["blockers"]
    assert result["alpha_validation"]["long_term_positive_expectancy_proven"] is False
    assert not (tmp_path / "data/forward_observation/us_etf_rotation_v1/fills.jsonl").exists()


def test_us_etf_forward_observation_blocks_failed_data_gate_before_writing_ledger(tmp_path: Path) -> None:
    report = _copy_report(tmp_path)
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json",
        {
            "status": "blocked",
            "blockers": ["us_equity_freshness_price_data_stale"],
            "guardrails": {
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )

    result = run_us_etf_rotation_forward_observation(
        repo_root=tmp_path,
        validation_report=report.relative_to(tmp_path),
        ledger_root=Path("data/forward_observation/us_etf_rotation_v1"),
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert result["status"] == "BLOCKED"
    _validate_schema(result)
    assert result["cycle_status"] == "NOT_RUN"
    assert result["readiness"]["data_gate"]["status"] == "BLOCKED"
    assert "us_equity_freshness_price_data_stale" in result["blockers"]
    assert not (tmp_path / "data/forward_observation/us_etf_rotation_v1/target_positions.jsonl").exists()


def test_us_etf_forward_observation_roll_schema_rejects_live_unlock(tmp_path: Path) -> None:
    report = _copy_report(tmp_path)
    payload = run_us_etf_rotation_forward_observation(
        repo_root=tmp_path,
        validation_report=report.relative_to(tmp_path),
        ledger_root=Path("data/forward_observation/us_etf_rotation_v1"),
        output=Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_data_gate_reports(root: Path) -> None:
    latest = root / "artifacts/us_equity_data_status/latest"
    latest.mkdir(parents=True, exist_ok=True)
    _write_json(
        latest / "us_equity_data_freshness_daily_report.json",
        {
            "status": "pass",
            "blockers": [],
            "guardrails": {
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        latest / "us_equity_etf_kline_quality_daily_report.json",
        {
            "status": "warn",
            "summary": {
                "latest_common_date": "2026-06-24",
                "warn_symbol_count": 1,
                "blocked_symbol_count": 0,
            },
            "warnings": ["DBMF:zero_or_negative_volume_rows:26"],
            "blockers": [],
            "guardrails": {
                "kline_quality_gate_only": True,
                "token_written_to_artifacts": False,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        latest / "us_equity_fred_macro_preflight_report.json",
        {
            "status": "fred_macro_preflight_warn",
            "warnings": ["fred_release_calendar_missing"],
            "blockers": [],
            "guardrails": {
                "macro_preflight_only": True,
                "token_written_to_artifacts": False,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
