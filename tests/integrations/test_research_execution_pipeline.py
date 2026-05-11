from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_us.research.orchestration.research_execution_pipeline import (
    ResearchExecutionPipelineConfig,
    run_research_execution_pipeline,
)
from tests.integrations.helpers import (
    make_bar_frame,
    run_module_main,
    write_cleaned_bars,
    write_portfolio_config,
    write_qlib_run_inputs,
)


def _write_pipeline_market_data(data_root: Path) -> None:
    write_cleaned_bars(
        data_root,
        "AAPL",
        make_bar_frame(
            "AAPL",
            [98.0, 99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0],
            start="2025-12-30",
        ),
    )
    write_cleaned_bars(
        data_root,
        "MSFT",
        make_bar_frame(
            "MSFT",
            [198.0, 199.0, 200.0, 202.0, 201.0, 203.0, 204.0, 206.0, 205.0, 207.0, 208.0],
            start="2025-12-30",
        ),
    )


def _write_pipeline_scores() -> pd.DataFrame:
    dates = pd.bdate_range(start="2026-01-05", periods=6, tz="UTC")
    rows: list[dict[str, object]] = []
    for timestamp, aapl_score, msft_score in zip(
        dates,
        [0.45, 0.30, 0.25, 0.40, 0.35, 0.20],
        [0.20, 0.35, 0.40, 0.10, 0.25, 0.45],
        strict=True,
    ):
        rows.append(
            {
                "datetime": timestamp,
                "instrument": "AAPL",
                "symbol": "AAPL",
                "score": aapl_score,
            }
        )
        rows.append(
            {
                "datetime": timestamp,
                "instrument": "MSFT",
                "symbol": "MSFT",
                "score": msft_score,
            }
        )
    return pd.DataFrame(rows)


def _write_qlib_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "mode: research_only",
                "model:",
                "  name: lgbm_daily",
                "  strategy_version: qlib_exec_v1",
                "  params:",
                "    alpha: 42",
                "lineage:",
                "  strategy_version: qlib_exec_v1",
                "  cost_model:",
                "    name: baseline_cost",
                "  slippage_model:",
                "    name: baseline_slippage",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_pipeline_generates_manifest_and_evidence_pack_from_small_artifacts(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    artifacts_root = tmp_path / "artifacts"
    _write_pipeline_market_data(data_root)
    scores = _write_pipeline_scores()
    write_qlib_run_inputs(artifacts_root, "qlib_exec_success", scores)
    qlib_config_path = _write_qlib_config(tmp_path / "configs" / "qlib_exec.yaml")
    portfolio_config_path = write_portfolio_config(
        tmp_path / "configs" / "portfolio_exec.yaml",
        data_root=data_root,
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id="portfolio_exec_success",
    )

    result = run_research_execution_pipeline(
        ResearchExecutionPipelineConfig(
            qlib_run_id="qlib_exec_success",
            qlib_config_path=qlib_config_path,
            portfolio_config_path=portfolio_config_path,
            pipeline_run_id="pipe_exec_success",
            qlib_runs_root=artifacts_root / "qlib_runs",
            portfolio_runs_root=artifacts_root / "portfolio_runs",
            pipeline_runs_root=artifacts_root / "research_execution_runs",
            risk_max_order_notional_pct=0.60,
            walk_forward_train_bars=2,
            walk_forward_test_bars=2,
            walk_forward_step_bars=2,
        )
    )

    assert result.status == "completed"

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    evidence_pack = json.loads(Path(result.evidence_pack_path).read_text(encoding="utf-8"))

    assert manifest["status"] == "completed"
    assert manifest["fail_closed"] is True
    assert manifest["lineage"]["strategy_version"] == "qlib_exec_v1"
    assert manifest["lineage"]["data_versions"] == [
        "qs-yfinance-AAPL-1d-test",
        "qs-yfinance-MSFT-1d-test",
    ]
    assert Path(manifest["artifacts"]["target_positions_parquet_path"]).exists()
    assert Path(manifest["artifacts"]["target_weights_path"]).exists()
    assert Path(manifest["artifacts"]["backtest_manifest_path"]).exists()

    assert evidence_pack["status"] == "completed"
    assert evidence_pack["risk_gate"]["enforced"] is True
    assert evidence_pack["risk_gate"]["risk_check_count"] > 0
    assert evidence_pack["risk_gate"]["rejected"] == 0
    assert evidence_pack["risk_gate"]["all_orders_have_risk_check_id"] is True
    assert evidence_pack["risk_gate"]["external_target_positions_consumed"] == evidence_pack["risk_gate"]["external_target_position_count"]
    assert evidence_pack["gate_blockers"] == []

    backtest_stage = evidence_pack["stage_status"]["event_driven_backtest"]
    assert backtest_stage["status"] == "completed"
    assert backtest_stage["details"]["evidence"]["orders"]["all_orders_have_risk_check_id"] is True
    assert backtest_stage["details"]["evidence"]["risk"]["rejected"] == 0

    cost_stage = evidence_pack["stage_status"]["cost_stress"]
    assert cost_stage["status"] == "completed"
    assert len(cost_stage["details"]["levels"]) == 4

    walk_forward_stage = evidence_pack["stage_status"]["walk_forward"]
    assert walk_forward_stage["status"] == "completed"
    assert walk_forward_stage["details"]["aggregate"]["total_windows"] >= 1


def test_pipeline_cli_fails_closed_when_risk_gate_rejects_targets(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    artifacts_root = tmp_path / "artifacts"
    _write_pipeline_market_data(data_root)
    scores = _write_pipeline_scores()
    write_qlib_run_inputs(artifacts_root, "qlib_exec_fail_closed", scores)
    qlib_config_path = _write_qlib_config(tmp_path / "configs" / "qlib_exec_fail.yaml")
    portfolio_config_path = write_portfolio_config(
        tmp_path / "configs" / "portfolio_exec_fail.yaml",
        data_root=data_root,
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id="portfolio_exec_fail",
    )

    module_result = run_module_main(
        "quant_us.research.orchestration.research_execution_pipeline",
        [
            "--qlib-run-id",
            "qlib_exec_fail_closed",
            "--qlib-config",
            str(qlib_config_path),
            "--portfolio-config",
            str(portfolio_config_path),
            "--pipeline-run-id",
            "pipe_exec_fail",
            "--qlib-runs-root",
            str(artifacts_root / "qlib_runs"),
            "--portfolio-runs-root",
            str(artifacts_root / "portfolio_runs"),
            "--pipeline-runs-root",
            str(artifacts_root / "research_execution_runs"),
            "--risk-max-order-notional-pct",
            "0.01",
            "--wf-train-bars",
            "2",
            "--wf-test-bars",
            "2",
            "--wf-step-bars",
            "2",
        ],
    )

    assert module_result.exit_code == 1
    payload = json.loads(module_result.stdout.strip())
    evidence_pack = json.loads(Path(payload["evidence_pack_path"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))

    assert payload["status"] == "failed"
    assert manifest["status"] == "failed"
    assert evidence_pack["status"] == "failed"
    assert evidence_pack["risk_gate"]["rejected"] > 0
    assert any(str(item).startswith("risk_gate_rejections:") for item in evidence_pack["gate_blockers"])
    assert evidence_pack["fail_closed"] is True
