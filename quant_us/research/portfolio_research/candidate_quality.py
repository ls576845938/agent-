"""Candidate quality helpers for research-only portfolio construction.

These helpers score style concentration, turnover burden, capacity, and
redundancy so automation can prefer a small set of higher-quality candidates.
They never relax promotion gates or enable trading paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class CandidateQualityAssessment:
    quality_score: float
    eligible: bool
    turnover_score: float
    capacity_score: float
    style_score: float
    redundancy_score: float
    dominant_style: str
    max_abs_beta: float
    estimated_capacity_usd: float
    annual_turnover_pct: float
    max_abs_correlation: float
    rejection_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_candidate_quality(
    *,
    style_exposure: Mapping[str, Any] | None = None,
    capacity_profile: Mapping[str, Any] | None = None,
    turnover_profile: Mapping[str, Any] | None = None,
    max_abs_correlation: float = 0.0,
) -> CandidateQualityAssessment:
    style_payload = dict(style_exposure or {})
    capacity_payload = dict(capacity_profile or {})
    turnover_payload = dict(turnover_profile or {})
    betas = {
        str(name): float(value or 0.0)
        for name, value in dict(style_payload.get("betas", {}) or {}).items()
    }

    dominant_style = ""
    max_abs_beta = 0.0
    if betas:
        dominant_style, max_abs_beta = max(
            ((name, abs(value)) for name, value in betas.items()),
            key=lambda item: item[1],
        )

    turnover = max(0.0, float(turnover_payload.get("turnover", 0.0) or 0.0))
    annual_turnover_pct = max(
        0.0,
        float(turnover_payload.get("annual_turnover_pct", 0.0) or 0.0),
    )
    estimated_capacity_usd = max(
        0.0,
        float(capacity_payload.get("estimated_capacity_usd", 0.0) or 0.0),
    )
    max_abs_correlation = max(0.0, float(max_abs_correlation or 0.0))

    turnover_score = _turnover_score(turnover)
    capacity_score = _capacity_score(estimated_capacity_usd)
    style_score = _style_score(max_abs_beta, float(style_payload.get("r_squared", 0.0) or 0.0))
    redundancy_score = _redundancy_score(max_abs_correlation)

    quality_score = round(
        0.35 * turnover_score
        + 0.30 * capacity_score
        + 0.20 * style_score
        + 0.15 * redundancy_score,
        6,
    )

    warnings: list[str] = []
    rejection_reasons: list[str] = []
    if turnover_score < 0.45:
        warnings.append("turnover_pressure")
    if capacity_score < 0.45:
        warnings.append("capacity_pressure")
    if style_score < 0.45:
        warnings.append("style_concentration")
    if redundancy_score < 0.45:
        warnings.append("redundancy_pressure")

    if turnover > 0.45:
        rejection_reasons.append("turnover_too_high")
    if estimated_capacity_usd > 0.0 and estimated_capacity_usd < 200_000.0:
        rejection_reasons.append("capacity_too_low")
    if max_abs_beta > 6.0 and float(style_payload.get("r_squared", 0.0) or 0.0) >= 0.95:
        rejection_reasons.append("style_exposure_too_concentrated")
    if max_abs_correlation >= 0.88:
        rejection_reasons.append("redundancy_too_high")

    return CandidateQualityAssessment(
        quality_score=quality_score,
        eligible=quality_score >= 0.55 and not rejection_reasons,
        turnover_score=round(turnover_score, 6),
        capacity_score=round(capacity_score, 6),
        style_score=round(style_score, 6),
        redundancy_score=round(redundancy_score, 6),
        dominant_style=dominant_style,
        max_abs_beta=round(max_abs_beta, 6),
        estimated_capacity_usd=round(estimated_capacity_usd, 2),
        annual_turnover_pct=round(annual_turnover_pct, 3),
        max_abs_correlation=round(max_abs_correlation, 6),
        rejection_reasons=rejection_reasons,
        warnings=warnings,
    )


def _turnover_score(turnover: float) -> float:
    if turnover <= 0.12:
        return 1.0
    if turnover <= 0.20:
        return 0.8
    if turnover <= 0.35:
        return 0.55
    if turnover <= 0.45:
        return 0.35
    return 0.1


def _capacity_score(capacity_usd: float) -> float:
    if capacity_usd <= 0.0:
        return 0.4
    if capacity_usd >= 1_000_000.0:
        return 1.0
    if capacity_usd >= 500_000.0:
        return 0.8
    if capacity_usd >= 250_000.0:
        return 0.55
    if capacity_usd >= 200_000.0:
        return 0.4
    return 0.15


def _style_score(max_abs_beta: float, r_squared: float) -> float:
    if max_abs_beta <= 0.75:
        return 1.0
    if max_abs_beta <= 1.0:
        return 0.8
    if max_abs_beta <= 1.2:
        return 0.6
    if max_abs_beta <= 1.6 or r_squared < 0.75:
        return 0.45
    return 0.2


def _redundancy_score(max_abs_correlation: float) -> float:
    if max_abs_correlation <= 0.25:
        return 1.0
    if max_abs_correlation <= 0.50:
        return 0.8
    if max_abs_correlation <= 0.70:
        return 0.6
    if max_abs_correlation <= 0.85:
        return 0.4
    return 0.15


__all__ = ["CandidateQualityAssessment", "assess_candidate_quality"]
