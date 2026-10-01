from __future__ import annotations

import json
from pathlib import Path

from scripts.build_global_research_registry import build_global_registry
from scripts.build_us_equity_factor_evidence_pack import (
    build_us_equity_factor_evidence_pack,
    write_us_equity_factor_evidence_pack,
)


def test_us_equity_factor_evidence_pack_schema_file_exists() -> None:
    assert Path("schemas/us_equity_factor_evidence_pack.schema.json").exists()


def test_us_equity_factor_evidence_pack_summarizes_factor_mining_artifacts(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/data_status_report.json",
        {
            "schema_version": "us_equity_data_status_report_v1",
            "data_versions": ["qs-yfinance-AAPL-1d-fixture"],
            "symbols": ["AAPL", "MSFT"],
        },
    )
    _write_json(
        tmp_path / "data/research/generated_factors/factors.json",
        {"factors": [{"factor_id": "momentum_20d"}]},
    )
    _write_json(
        tmp_path / "data/research/generated_strategies/factor_rank_fixture.json",
        {"strategy_id": "factor_rank_fixture", "promotion_status": "RESEARCH_ONLY"},
    )
    _write_json(
        tmp_path / "data/research/factor_mining/fmine_fixture_correlation.json",
        {"schema_version": "factor_mining_correlation_report_v1"},
    )
    _write_json(
        tmp_path / "data/research/factor_mining/fmine_fixture.json",
        {
            "run_id": "fmine_fixture",
            "correlation_report_path": "data/research/factor_mining/fmine_fixture_correlation.json",
            "manifest_evidence": {
                "schema_version": "factor_mining_manifest_evidence_v1",
                "candidate_count": 2,
                "selected_count": 1,
                "selected_factor_ids": ["momentum_20d"],
                "compiled_strategy_count": 1,
                "quality_filter": {
                    "eligible_candidates": 1,
                    "rejected_candidates": 0,
                    "mean_quality_score": 0.8,
                    "selected_mean_quality_score": 0.9,
                },
                "style_exposure_coverage": {"covered_candidates": 2, "missing_candidates": 0},
                "capacity_coverage": {"covered_candidates": 2, "missing_candidates": 0},
                "turnover_coverage": {"covered_candidates": 2, "missing_candidates": 0},
                "bar_samples_available": {"1d": True},
                "lookahead_guard": "factor[t] is paired with next_return[t->t+1] only",
            },
            "factor_scores": [
                {
                    "factor_id": "momentum_20d",
                    "bar_size": "1d",
                    "candidate_rank": 1,
                    "selected": True,
                    "rank_ic_mean": 0.06,
                    "ic_mean": 0.05,
                    "hit_rate": 0.61,
                    "turnover": 0.08,
                    "quality_score": 0.9,
                    "stability_score": 0.7,
                    "reject_reason": "",
                }
            ],
            "selected_factors": [{"factor_id": "momentum_20d", "bar_size": "1d"}],
            "candidate_ranking": [{"factor_id": "momentum_20d", "bar_size": "1d", "candidate_rank": 1}],
            "strategy_configs": [{"strategy_id": "factor_rank", "promotion_status": "RESEARCH_ONLY"}],
        },
    )

    payload = build_us_equity_factor_evidence_pack(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_factor_evidence_pack_v1"
    assert payload["asset"] == "us_equity"
    assert payload["promotion_ready"] is False
    assert payload["paper_queue_status"] == "locked"
    assert payload["live_status"] == "frozen"
    assert payload["data_status_report"] == "artifacts/us_equity_data_status/latest/data_status_report.json"
    assert payload["latest_factor_mining_report"] == "data/research/factor_mining/fmine_fixture.json"
    assert payload["latest_correlation_report"] == "data/research/factor_mining/fmine_fixture_correlation.json"
    assert payload["factor_mining_run_count"] == 1
    assert payload["generated_factor_count"] == 1
    assert payload["selected_factor_ids"] == ["momentum_20d"]
    assert payload["compiled_strategy_count"] == 1
    assert payload["evidence_coverage"]["style_exposure"]["missing_candidates"] == 0
    assert payload["factor_rows"][0]["factor_id"] == "momentum_20d"
    assert "us_equity_factor_walk_forward_stability_required" in payload["blockers"]
    assert "us_equity_portfolio_layer_required_before_promotion" in payload["blockers"]

    output = write_us_equity_factor_evidence_pack(
        payload,
        tmp_path / "artifacts/us_equity_factor_evidence/latest",
    )
    persisted = json.loads(Path(output).read_text(encoding="utf-8"))
    assert persisted["selected_factor_count"] == 1


def test_global_registry_prefers_us_equity_factor_evidence_pack(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json",
        {
            "schema_version": "us_equity_factor_evidence_pack_v1",
            "status": "partial",
            "latest_factor_mining_report": "data/research/factor_mining/fmine_fixture.json",
            "selected_factor_count": 1,
            "selected_factor_ids": ["momentum_20d"],
            "blockers": ["us_equity_portfolio_layer_required_before_promotion"],
        },
    )
    _write_json(
        tmp_path / "data/research/generated_factors/factors.json",
        {"factors": [{"factor_id": "momentum_20d"}]},
    )

    registry = build_global_registry(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )
    factor_evidence = registry["assets"]["us_equity"]["factor_evidence"]

    assert registry["assets"]["us_equity"]["latest_factor_evidence"] == (
        "artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json"
    )
    assert factor_evidence["factor_evidence_pack"] == (
        "artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json"
    )
    assert factor_evidence["selected_factor_count"] == 1
    assert factor_evidence["selected_factor_ids"] == ["momentum_20d"]
    assert "us_equity_portfolio_layer_required_before_promotion" in factor_evidence["blockers"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
