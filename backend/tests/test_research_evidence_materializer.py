"""Tests for canonical research evidence materialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_us.research.automation.evidence_materializer import (
    ResearchEvidenceMaterializer,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _candidate_payload(
    *,
    candidate_id: str,
    backtest_manifest_path: str,
    metrics: dict,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "experiment_id": "exp_001",
        "strategy_id": "trend_momentum",
        "symbols": ["AAPL"],
        "timeframe": "1d",
        "data_source": "yfinance",
        "asset_class": "equity",
        "data_version": "yfinance:equity:1d:AAPL:2024",
        "backtest_manifest_path": backtest_manifest_path,
        "metrics": metrics,
        "promotion_status": "RESEARCH_ONLY",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_materializer_writes_canonical_candidate_evidence(tmp_path: Path) -> None:
    candidate_id = "cand_materialized"
    source_manifest = tmp_path / "research" / "runs" / "source_manifest.json"
    _write_json(
        source_manifest,
        {
            "engine": "event_driven",
            "canonical_for_promotion": True,
            "data_version": "yfinance:equity:1d:AAPL:2024",
            "evidence": {},
        },
    )
    metrics = {
        "sharpe_ratio": 1.2,
        "total_return_pct": 0.18,
        "max_drawdown_pct": 0.12,
        "trade_count": 24,
        "walk_forward_pass_rate": 0.75,
        "wf_fold_sharpes": [0.7, 0.9, 1.1],
        "cost_sensitivity": 0.12,
        "stress_survival_rate": 0.9,
    }
    candidate_path = (
        tmp_path
        / "research"
        / "candidates"
        / candidate_id
        / "candidate.json"
    )
    _write_json(
        candidate_path,
        _candidate_payload(
            candidate_id=candidate_id,
            backtest_manifest_path=str(source_manifest),
            metrics=metrics,
        ),
    )

    result = ResearchEvidenceMaterializer(data_root=str(tmp_path)).materialize_candidate(
        candidate_id,
        create_strategy_manifest=False,
        run_promotion_gate=False,
    )

    canonical_backtest = (
        tmp_path / "research" / "backtests" / candidate_id / "run_manifest.json"
    )
    assert result.backtest_manifest_path == str(canonical_backtest)
    assert canonical_backtest.exists()
    assert Path(result.scorecard_path).exists()
    assert Path(result.walk_forward_result_path).exists()
    assert Path(result.cost_stress_result_path).exists()

    saved = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert saved["backtest_manifest_path"] == str(canonical_backtest)
    assert saved["metrics"]["walk_forward_result_path"] == result.walk_forward_result_path
    assert saved["metrics"]["cost_stress_result_path"] == result.cost_stress_result_path


def test_materializer_does_not_fabricate_missing_robustness_artifacts(
    tmp_path: Path,
) -> None:
    candidate_id = "cand_missing_robustness"
    source_manifest = tmp_path / "research" / "runs" / "source_manifest.json"
    _write_json(source_manifest, {"engine": "event_driven"})
    candidate_path = (
        tmp_path
        / "research"
        / "candidates"
        / candidate_id
        / "candidate.json"
    )
    _write_json(
        candidate_path,
        _candidate_payload(
            candidate_id=candidate_id,
            backtest_manifest_path=str(source_manifest),
            metrics={"sharpe_ratio": 0.8, "trade_count": 20},
        ),
    )

    result = ResearchEvidenceMaterializer(data_root=str(tmp_path)).materialize_candidate(
        candidate_id,
        create_strategy_manifest=False,
        run_promotion_gate=False,
    )

    assert result.backtest_manifest_path
    assert result.scorecard_path
    assert result.walk_forward_result_path == ""
    assert result.cost_stress_result_path == ""
    assert "walk_forward_metrics_missing" in result.warnings
    assert "cost_stress_metrics_missing" in result.warnings


def test_materializer_resolves_repo_relative_canonical_backtest_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id = "cand_repo_relative_materializer"
    data_root = tmp_path / "data"
    canonical_manifest = (
        data_root / "research" / "backtests" / candidate_id / "run_manifest.json"
    )
    _write_json(canonical_manifest, {"engine": "event_driven", "canonical_for_promotion": True})
    candidate_path = data_root / "research" / "candidates" / candidate_id / "candidate.json"
    _write_json(
        candidate_path,
        _candidate_payload(
            candidate_id=candidate_id,
            backtest_manifest_path=f"data/research/backtests/{candidate_id}/run_manifest.json",
            metrics={"trade_count": 12, "walk_forward_pass_rate": 0.5, "cost_sensitivity": 0.2},
        ),
    )

    monkeypatch.chdir(tmp_path)
    result = ResearchEvidenceMaterializer(data_root="data").materialize_candidate(
        candidate_id,
        create_strategy_manifest=False,
        run_promotion_gate=False,
    )

    assert result.backtest_manifest_path == str(canonical_manifest.relative_to(tmp_path))
    assert "backtest_manifest_missing" not in result.warnings
