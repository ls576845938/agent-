from __future__ import annotations

from copy import deepcopy
from typing import Any

from scripts.build_us_equity_factor_evidence_pack import (
    evaluate_us_equity_factor_evidence_row,
)


def test_placeholder_evidence_fails() -> None:
    row = _complete_row()
    row["is_placeholder"] = True

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "factor_evidence_placeholder" in verdict["blocker_reasons"]
    assert verdict["allowed_next_action"] == "research_only"


def test_missing_data_version_fails() -> None:
    row = _complete_row()
    row["data_version"] = ""
    row["data_lineage"]["data_version"] = ""

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "data_version_missing" in verdict["blocker_reasons"]


def test_missing_universe_version_fails() -> None:
    row = _complete_row()
    row["universe_version"] = ""
    row["data_lineage"]["universe_version"] = ""

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "universe_version_missing" in verdict["blocker_reasons"]


def test_missing_manifest_hash_fails() -> None:
    row = _complete_row()
    row["manifest_hash"] = ""
    row["data_lineage"]["manifest_hash"] = ""

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "manifest_hash_missing" in verdict["blocker_reasons"]


def test_missing_ic_fails() -> None:
    row = _complete_row()
    row["metrics"].pop("IC_mean")

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "IC_mean_missing" in verdict["blocker_reasons"]


def test_missing_rank_ic_fails() -> None:
    row = _complete_row()
    row["metrics"].pop("Rank_IC_mean")

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "Rank_IC_mean_missing" in verdict["blocker_reasons"]


def test_missing_turnover_fails() -> None:
    row = _complete_row()
    row["metrics"].pop("turnover")

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "turnover_missing" in verdict["blocker_reasons"]


def test_missing_cost_adjusted_spread_fails() -> None:
    row = _complete_row()
    row["metrics"].pop("cost_adjusted_spread")

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "cost_adjusted_spread_missing" in verdict["blocker_reasons"]


def test_missing_walk_forward_stability_fails() -> None:
    row = _complete_row()
    row["stability"].pop("walk_forward_pass_rate")

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "fail"
    assert "walk_forward_pass_rate_missing" in verdict["blocker_reasons"]


def test_complete_evidence_can_enter_portfolio_review_but_not_paper() -> None:
    row = _complete_row()

    verdict = evaluate_us_equity_factor_evidence_row(row)

    assert verdict["overall_status"] == "pass"
    assert verdict["allowed_next_action"] == "portfolio_candidate_review"
    assert "paper" not in verdict["allowed_next_action"]


def _complete_row() -> dict[str, Any]:
    row: dict[str, Any] = {
        "factor_name": "momentum_20d",
        "factor_version": "v1",
        "factor_family": "momentum",
        "evidence_source": "real_us_equity_factor_run_v1",
        "is_placeholder": False,
        "is_data_dependent": True,
        "data_version": "us_equity_1d_data_versions_sha256:abc",
        "universe_version": "us_equity_manifest_universe_v1",
        "manifest_hash": "hash",
        "universe_name": "us_equity_manifest_universe_v1",
        "sample_start": "2020-01-02",
        "sample_end": "2025-12-30",
        "data_lineage": {
            "data_version": "us_equity_1d_data_versions_sha256:abc",
            "universe_version": "us_equity_manifest_universe_v1",
            "manifest_hash": "hash",
        },
        "metrics": {
            "IC_mean": 0.03,
            "Rank_IC_mean": 0.04,
            "IC_decay": {"1d": 0.03, "5d": 0.04, "20d": 0.02},
            "turnover": 0.25,
            "cost_adjusted_spread": 0.01,
        },
        "stability": {
            "walk_forward_pass_rate": 1.0,
        },
        "gates": {
            "data_lineage_pass": True,
            "IC_pass": True,
            "rank_IC_pass": True,
            "turnover_pass": True,
            "cost_adjusted_pass": True,
            "walk_forward_pass": True,
        },
        "blocker_reasons": [],
        "allowed_next_action": "portfolio_candidate_review",
    }
    return deepcopy(row)
