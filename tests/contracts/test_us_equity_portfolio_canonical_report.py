from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.build_global_research_registry import build_global_registry
from scripts.build_us_equity_portfolio_canonical_report import (
    build_us_equity_portfolio_canonical_report,
    write_us_equity_portfolio_canonical_report,
)


def test_us_equity_portfolio_canonical_report_schema_file_exists() -> None:
    assert Path("schemas/us_equity_portfolio_canonical_report.schema.json").exists()


def test_us_equity_portfolio_canonical_report_summarizes_latest_portfolio_run(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json",
        {
            "schema_version": "us_equity_factor_evidence_pack_v1",
            "status": "partial",
            "selected_factor_ids": ["momentum_20d"],
        },
    )
    run_root = tmp_path / "artifacts/portfolio_runs/pf_fixture"
    _write_json(
        run_root / "run_manifest.json",
        {
            "portfolio_run_id": "pf_fixture",
            "source_score_run_id": "qlib_fixture",
            "generated_at": "2026-05-18T00:00:00+00:00",
            "dependency_available": False,
            "fallback_used": True,
            "config": {
                "optimizer": "max_sharpe",
                "constraints_hash": "abc123",
                "max_turnover": 0.30,
            },
            "output_files": {
                "target_weights": "artifacts/portfolio_runs/pf_fixture/target_weights.parquet",
                "target_positions": "artifacts/portfolio_runs/pf_fixture/target_positions.parquet",
            },
        },
    )
    pd.DataFrame(
        [
            {
                "portfolio_run_id": "pf_fixture",
                "source_score_run_id": "qlib_fixture",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "AAPL",
                "target_weight": 0.20,
                "turnover_from_previous": 0.20,
            },
            {
                "portfolio_run_id": "pf_fixture",
                "source_score_run_id": "qlib_fixture",
                "datetime": "2026-01-08T00:00:00+00:00",
                "symbol": "MSFT",
                "target_weight": 0.10,
                "turnover_from_previous": 0.20,
            },
            {
                "portfolio_run_id": "pf_fixture",
                "source_score_run_id": "qlib_fixture",
                "datetime": "2026-01-09T00:00:00+00:00",
                "symbol": "AAPL",
                "target_weight": 0.15,
                "turnover_from_previous": 0.10,
            },
            {
                "portfolio_run_id": "pf_fixture",
                "source_score_run_id": "qlib_fixture",
                "datetime": "2026-01-09T00:00:00+00:00",
                "symbol": "MSFT",
                "target_weight": 0.25,
                "turnover_from_previous": 0.10,
            },
        ]
    ).to_parquet(run_root / "target_weights.parquet", index=False)

    payload = build_us_equity_portfolio_canonical_report(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )
    report = payload["portfolio_canonical_report"]
    exposure_report = payload["exposure_report"]
    drift_report = payload["rebalance_drift_report"]

    assert report["schema_version"] == "us_equity_portfolio_canonical_report_v1"
    assert report["asset"] == "us_equity"
    assert report["promotion_ready"] is False
    assert report["paper_queue_status"] == "locked"
    assert report["live_status"] == "frozen"
    assert report["portfolio_run_id"] == "pf_fixture"
    assert report["source_run_manifest"] == "artifacts/portfolio_runs/pf_fixture/run_manifest.json"
    assert report["factor_evidence_pack"] == "artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json"
    assert report["target_weights_path"] == "artifacts/portfolio_runs/pf_fixture/target_weights.parquet"
    assert report["weight_summary"]["symbol_count"] == 2
    assert report["weight_summary"]["gross_weight"] == 0.40
    assert report["weight_summary"]["max_symbol_weight"] == 0.25
    assert exposure_report["gross_exposure"] == 0.40
    assert drift_report["max_observed_turnover"] == 0.20
    assert "us_equity_event_ledger_portfolio_backtest_required" in report["blockers"]
    assert "us_equity_portfolio_cost_stress_required" in report["blockers"]

    paths = write_us_equity_portfolio_canonical_report(
        payload,
        tmp_path / "artifacts/us_equity_portfolio/latest",
    )
    persisted = json.loads(Path(paths["portfolio_canonical_report"]).read_text(encoding="utf-8"))
    assert persisted["exposure_report_path"].endswith("exposure_report.json")


def test_global_registry_prefers_us_equity_portfolio_canonical_report(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        {
            "schema_version": "us_equity_portfolio_canonical_report_v1",
            "status": "partial",
            "portfolio_run_id": "pf_fixture",
            "event_ledger_status": {"status": "missing"},
            "blockers": ["us_equity_event_ledger_portfolio_backtest_required"],
        },
    )
    _write_json(
        tmp_path / "artifacts/portfolio_runs/pf_fixture/run_manifest.json",
        {"portfolio_run_id": "pf_fixture"},
    )

    registry = build_global_registry(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )
    portfolio_evidence = registry["assets"]["us_equity"]["portfolio_evidence"]

    assert registry["assets"]["us_equity"]["latest_portfolio_report"] == (
        "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json"
    )
    assert portfolio_evidence["portfolio_canonical_report"] == (
        "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json"
    )
    assert portfolio_evidence["event_ledger_status"] == "missing"
    assert "us_equity_event_ledger_portfolio_backtest_required" in portfolio_evidence["blockers"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
