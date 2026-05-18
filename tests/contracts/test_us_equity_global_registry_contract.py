from __future__ import annotations

import json
from pathlib import Path

from scripts.build_global_research_registry import build_global_registry


FORBIDDEN_US_CANDIDATE_VALUES = {
    "paper_ready",
    "live_ready",
    "live_enabled",
    "APPROVED_FOR_PAPER_ONLY",
}


def test_us_equity_missing_artifacts_fail_closed_as_blockers(tmp_path: Path) -> None:
    registry = build_global_registry(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )

    us_equity = registry["assets"]["us_equity"]

    assert registry["paper_queue_status"] == "locked"
    assert registry["live_status"] == "frozen"
    assert registry["candidate_passed_internal_gate"] == 0
    assert us_equity["current_candidates"] == []
    assert "us_equity_data_status_report_missing" in us_equity["blockers"]
    assert "us_equity_data_manifest_missing" in us_equity["blockers"]
    assert "us_equity_factor_evidence_missing" in us_equity["blockers"]
    assert "us_equity_portfolio_report_missing" in us_equity["blockers"]


def test_us_equity_qlib_artifact_is_evidence_candidate_only(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json",
        {
            "data_version": "qs-yfinance-AAPL-1d-fixture",
            "source": "yfinance",
            "symbol": "AAPL",
            "interval": "1d",
            "survivorship_bias_risk": "clean",
            "adjustment_policy": "raw",
        },
    )
    _write_json(
        tmp_path / "artifacts/qlib_runs/qlib_fixture/qlib_strategy_manifest.json",
        {
            "run_id": "qlib_fixture",
            "strategy_id": "qlib_lgbm_fixture",
            "data_versions": ["qs-yfinance-AAPL-1d-fixture"],
            "status": "candidate",
            "promotion_status": "candidate",
            "mode": "research_only",
        },
    )
    _write_json(tmp_path / "data/research/generated_factors/factors.json", {"factors": []})
    _write_json(tmp_path / "data/research/generated_strategies/qlib_lgbm_fixture.json", {"status": "RESEARCH_ONLY"})
    _write_json(
        tmp_path / "artifacts/portfolio_runs/pf_fixture/run_manifest.json",
        {"status": "completed", "research_only": True, "live_enabled": False},
    )

    registry = build_global_registry(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )

    us_equity = registry["assets"]["us_equity"]
    candidate = us_equity["current_candidates"][0]

    assert us_equity["data_lineage"]["manifest_count"] == 1
    assert us_equity["factor_evidence"]["generated_strategy_count"] == 1
    assert us_equity["portfolio_evidence"]["portfolio_run_count"] == 1
    assert candidate == {
        "name": "qlib_lgbm_fixture",
        "source": "qlib",
        "status": "evidence_candidate",
        "evidence_path": "artifacts/qlib_runs/qlib_fixture/qlib_strategy_manifest.json",
        "data_versions": ["qs-yfinance-AAPL-1d-fixture"],
        "blockers": [
            "internal_event_ledger_backtest_required",
            "cost_stress_required",
            "walk_forward_required",
            "regime_report_required",
            "promotion_gate_required",
        ],
        "allowed_next_action": "internal_event_backtest_required",
    }
    candidate_text_values = {value for value in candidate.values() if isinstance(value, str)}
    assert not (FORBIDDEN_US_CANDIDATE_VALUES & candidate_text_values)


def test_us_equity_data_status_artifacts_are_wired_into_global_registry(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json",
        {
            "data_version": "qs-yfinance-AAPL-1d-fixture",
            "source": "yfinance",
            "symbol": "AAPL",
            "interval": "1d",
            "asset_class": "equity",
            "survivorship_bias_risk": "clean",
            "adjustment_policy": "raw",
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/data_status_report.json",
        {
            "schema_version": "us_equity_data_status_report_v1",
            "blockers": ["corporate_action_event_source_missing"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/universe_manifest.json",
        {
            "schema_version": "us_equity_universe_manifest_v1",
            "blockers": ["point_in_time_universe_not_confirmed"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/corporate_action_report.json",
        {
            "schema_version": "us_equity_corporate_action_report_v1",
            "blockers": ["corporate_action_event_source_missing"],
        },
    )

    registry = build_global_registry(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )

    data_lineage = registry["assets"]["us_equity"]["data_lineage"]

    assert registry["assets"]["us_equity"]["latest_data_status"] == (
        "artifacts/us_equity_data_status/latest/data_status_report.json"
    )
    assert data_lineage["data_status_report"] == "artifacts/us_equity_data_status/latest/data_status_report.json"
    assert data_lineage["universe_manifest"] == "artifacts/us_equity_data_status/latest/universe_manifest.json"
    assert data_lineage["corporate_action_report"] == (
        "artifacts/us_equity_data_status/latest/corporate_action_report.json"
    )
    assert "point_in_time_universe_not_confirmed" in data_lineage["blockers"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
