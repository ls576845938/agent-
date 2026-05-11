from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from integrations.pypfopt_adapter.schemas import load_portfolio_config

from tests.integrations.helpers import (
    invoke_adapter_callable,
    locate_single_file,
    write_imported_scores,
    write_portfolio_config,
    write_qlib_run_inputs,
)


def test_fake_pipeline_runs_cleaned_data_to_candidate_manifest(
    tmp_path: Path,
    fake_market_root: Path,
    fake_scores_frame: pd.DataFrame,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    qlib_run_id = "pipeline_qlib_run"
    portfolio_run_id = "pipeline_portfolio_run"
    pipeline_scores = fake_scores_frame[
        fake_scores_frame["datetime"] == fake_scores_frame["datetime"].max()
    ].reset_index(drop=True)
    write_qlib_run_inputs(artifacts_root, qlib_run_id, pipeline_scores)
    config_path = write_portfolio_config(
        tmp_path / "configs" / "pipeline_portfolio.yaml",
        data_root=fake_market_root,
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id=portfolio_run_id,
    )
    config = load_portfolio_config(config_path)
    qlib_config_path = tmp_path / "configs" / "qlib_workflow.yaml"
    qlib_config_path.write_text(
        "mode: research_only\nmodel:\n  name: lgbm_daily\n  strategy_version: qlib_pipeline_v1\n",
        encoding="utf-8",
    )

    invoke_adapter_callable(
        "integrations.qlib_adapter.import_pred_score",
        ("import_pred_score", "import_scores", "run"),
        run_id=qlib_run_id,
        artifacts_root=artifacts_root / "qlib_runs",
    )
    imported_scores = pd.read_parquet(locate_single_file(artifacts_root, "research_model_scores.parquet"))
    assert {"symbol", "score", "rank"}.issubset(imported_scores.columns)

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.build_expected_returns",
        ("build_expected_returns", "build", "run"),
        score_run_id=qlib_run_id,
        config=config,
    )
    expected_returns = pd.read_parquet(locate_single_file(artifacts_root, "expected_returns.parquet"))
    assert "expected_return" in expected_returns.columns

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.build_covariance",
        ("build_covariance", "build", "run"),
        score_run_id=qlib_run_id,
        config=config,
    )
    covariance = pd.read_parquet(locate_single_file(artifacts_root, "covariance.parquet"))
    assert "covariance" in covariance.columns

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.optimize_weights",
        ("optimize_weights", "optimize", "run"),
        score_run_id=qlib_run_id,
        config=config,
    )
    target_weights = pd.read_parquet(locate_single_file(artifacts_root, "target_weights.parquet"))
    assert {"symbol", "target_weight"}.issubset(target_weights.columns)
    assert (target_weights["target_weight"] >= -1e-12).all()

    invoke_adapter_callable(
        "integrations.qlib_adapter.compile_qlib_strategy_manifest",
        ("compile_qlib_strategy_manifest", "compile_manifest", "run"),
        run_id=qlib_run_id,
        config_path=qlib_config_path,
        artifacts_root=artifacts_root / "qlib_runs",
    )
    manifest_path = locate_single_file(artifacts_root, "qlib_strategy_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert str(manifest.get("promotion_status", manifest.get("status", ""))).lower() == "candidate"


def test_pipeline_can_start_from_preimported_scores(
    tmp_path: Path,
    fake_market_root: Path,
    fake_scores_frame: pd.DataFrame,
) -> None:
    artifacts_root = tmp_path / "artifacts"
    run_id = "preimported_scores"
    write_imported_scores(artifacts_root, run_id, fake_scores_frame)
    config_path = write_portfolio_config(
        tmp_path / "configs" / "preimported_portfolio.yaml",
        data_root=fake_market_root,
        score_runs_root=artifacts_root / "qlib_runs",
        portfolio_runs_root=artifacts_root / "portfolio_runs",
        portfolio_run_id="portfolio_preimported",
    )

    invoke_adapter_callable(
        "integrations.pypfopt_adapter.build_expected_returns",
        ("build_expected_returns", "build", "run"),
        score_run_id=run_id,
        config=load_portfolio_config(config_path),
    )

    expected_returns = pd.read_parquet(locate_single_file(artifacts_root, "expected_returns.parquet"))
    assert not expected_returns.empty
