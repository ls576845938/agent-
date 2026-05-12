from __future__ import annotations

from quant_us.research.portfolio_research import assess_candidate_quality


def test_candidate_quality_prefers_balanced_low_turnover_candidates() -> None:
    result = assess_candidate_quality(
        style_exposure={
            "betas": {"MKT": 0.55, "SMB_PROXY": 0.2},
            "r_squared": 0.32,
        },
        capacity_profile={"estimated_capacity_usd": 1_400_000.0},
        turnover_profile={"turnover": 0.08, "annual_turnover_pct": 20.0},
        max_abs_correlation=0.22,
    )

    assert result.eligible is True
    assert result.quality_score > 0.8
    assert result.warnings == []


def test_candidate_quality_flags_execution_and_style_pressure() -> None:
    result = assess_candidate_quality(
        style_exposure={
            "betas": {"MKT": 6.5},
            "r_squared": 0.97,
        },
        capacity_profile={"estimated_capacity_usd": 150_000.0},
        turnover_profile={"turnover": 0.6, "annual_turnover_pct": 600.0},
        max_abs_correlation=0.9,
    )

    assert result.eligible is False
    assert result.quality_score < 0.4
    assert "turnover_too_high" in result.rejection_reasons
    assert "capacity_too_low" in result.rejection_reasons
    assert "style_exposure_too_concentrated" in result.rejection_reasons
