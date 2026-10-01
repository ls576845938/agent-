from __future__ import annotations

import json

from quant_us.research.automation.strategy_compiler import (
    ResearchStrategyCompiler,
    normalize_validation_summary,
)


def test_strategy_compiler_builds_research_only_artifact_with_pending_validation(
    tmp_path,
) -> None:
    compiler = ResearchStrategyCompiler(data_root=str(tmp_path))
    artifact, path = compiler.compile(
        run_id="fmine_001",
        strategy_key="single_1d_momentum_20d",
        logic={
            "logic_id": "fmine_001:1d:momentum_20d",
            "logic_version": "factor_rank_dsl_v1",
            "strategy_id": "factor_rank",
            "template_id": "single_factor_rank",
            "execution_semantics": "signal_at_bar_close_order_next_bar",
            "lookahead_guard": "factor[t] only",
        },
        config={
            "template_id": "single_factor_rank",
            "strategy_id": "factor_rank",
            "bar_size": "1d",
            "timeframe": "1d",
            "symbols": ["AAPL", "MSFT"],
            "factor_ids": ["momentum_20d"],
            "params": {"top_n": 2},
            "candidate_rank": 1,
            "research_score": 12.5,
        },
        candidate_evidence={
            "generation_family": "seed_factor",
            "formula_signature": "momentum_20d",
            "capacity": {"estimated_capacity_usd": 1_250_000.0},
            "turnover": {"annual_turnover_pct": 84.0},
            "style_exposure": {"betas": {"MKT": 0.95}},
            "candidate_quality": {"quality_score": 0.82, "eligible": True},
        },
    )

    assert artifact["research_controls"]["promotion_status"] == "RESEARCH_ONLY"
    assert artifact["research_controls"]["auto_paper"] is False
    assert artifact["research_controls"]["auto_live"] is False
    assert artifact["validation_summary"]["pbo"]["missing_reason"]
    assert artifact["validation_summary"]["dsr"]["missing_reason"]
    assert artifact["validation_summary"]["cpcv"]["missing_reason"]

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["reproducibility"]["formula_signature"] == "momentum_20d"
    assert persisted["reproducibility"]["candidate_quality_score"] == 0.82
    assert persisted["safeguards"]["capacity"]["estimated_capacity_usd"] == 1_250_000.0
    assert persisted["safeguards"]["candidate_quality"]["eligible"] is True


def test_strategy_compiler_normalizes_real_validation_summary() -> None:
    summary = normalize_validation_summary(
        {
            "status": "complete",
            "available_components": {
                "pbo": True,
                "deflated_sharpe_ratio": True,
            },
            "cv_summary": {
                "method": "cpcv",
                "path_count": 10,
                "fold_count": 5,
                "purged": True,
                "embargoed": True,
                "pass_rate": 0.8,
            },
            "deflated_sharpe_ratio": {
                "dsr": 0.42,
                "passed": True,
                "observed_sharpe": 1.1,
                "trial_count": 12,
            },
            "pbo": {
                "pbo": 0.14,
                "passed": True,
                "trial_count": 12,
                "overfit_path_count": 1,
            },
        }
    )

    assert summary["status"] == "complete"
    assert summary["pbo"]["pbo"] == 0.14
    assert summary["dsr"]["dsr"] == 0.42
    assert summary["cpcv"]["method"] == "cpcv"
    assert summary["cpcv"]["path_count"] == 10
    assert summary["cpcv"]["missing_reason"] is None
