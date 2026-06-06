from __future__ import annotations

from quant_us.risk.promotion_contract import evaluate_risk_budget_contract


def test_risk_budget_missing_blocks_promotion_ready() -> None:
    verdict = evaluate_risk_budget_contract({})

    assert verdict.promotion_ready is False
    assert "risk_budget_missing" in verdict.blockers


def test_max_drawdown_limit_missing_blocks_promotion_ready() -> None:
    verdict = evaluate_risk_budget_contract({"position_limit": 0.10, "exposure_limit": 1.0})

    assert verdict.promotion_ready is False
    assert "max_drawdown_limit_missing" in verdict.blockers


def test_position_limit_missing_blocks_promotion_ready() -> None:
    verdict = evaluate_risk_budget_contract({"max_drawdown_limit": 0.12, "exposure_limit": 1.0})

    assert verdict.promotion_ready is False
    assert "position_limit_missing" in verdict.blockers


def test_exposure_limit_missing_blocks_promotion_ready() -> None:
    verdict = evaluate_risk_budget_contract({"max_drawdown_limit": 0.12, "position_limit": 0.10})

    assert verdict.promotion_ready is False
    assert "exposure_limit_missing" in verdict.blockers


def test_complete_risk_budget_contract_can_pass_contract_only() -> None:
    verdict = evaluate_risk_budget_contract(
        {
            "max_drawdown_limit": 0.12,
            "position_limit": 0.10,
            "exposure_limit": 1.0,
        }
    )

    assert verdict.promotion_ready is True
    assert verdict.blockers == []
