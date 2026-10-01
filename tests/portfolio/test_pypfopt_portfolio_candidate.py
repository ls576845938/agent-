from __future__ import annotations

import pandas as pd

from quant_us.portfolio.optimizer import build_pypfopt_portfolio_candidate


def test_pypfopt_candidate_returns_research_only_weights_with_injected_optimizer() -> None:
    expected_returns = pd.Series({"VOO": 0.08, "QQQ": 0.12})
    covariance = pd.DataFrame(
        [[0.04, 0.02], [0.02, 0.09]],
        index=["VOO", "QQQ"],
        columns=["VOO", "QQQ"],
    )

    candidate = build_pypfopt_portfolio_candidate(
        expected_returns,
        covariance,
        max_weight=0.7,
        optimizer_factory=FakeEfficientFrontier,
    )

    assert candidate.status == "PASS"
    assert candidate.weights == {"VOO": 0.4, "QQQ": 0.6}
    assert candidate.promotion_allowed is False
    assert candidate.diagnostics["adapter_scope"] == "research_only_candidate_weights"


def test_pypfopt_candidate_blocks_missing_covariance_symbols() -> None:
    expected_returns = pd.Series({"VOO": 0.08, "QQQ": 0.12})
    covariance = pd.DataFrame([[0.04]], index=["VOO"], columns=["VOO"])

    candidate = build_pypfopt_portfolio_candidate(
        expected_returns,
        covariance,
        optimizer_factory=FakeEfficientFrontier,
    )

    assert candidate.status == "BLOCKED"
    assert "covariance_missing_index:QQQ" in candidate.blockers
    assert "covariance_missing_columns:QQQ" in candidate.blockers


def test_pypfopt_candidate_reports_missing_dependency_when_not_injected(monkeypatch) -> None:
    monkeypatch.setattr("quant_us.portfolio.optimizer._load_efficient_frontier", lambda: None)
    expected_returns = pd.Series({"VOO": 0.08})
    covariance = pd.DataFrame([[0.04]], index=["VOO"], columns=["VOO"])

    candidate = build_pypfopt_portfolio_candidate(expected_returns, covariance)

    assert candidate.status == "DEPENDENCY_MISSING"
    assert candidate.blockers == ["pypfopt_not_installed"]
    assert candidate.promotion_allowed is False


class FakeEfficientFrontier:
    def __init__(self, expected_returns, covariance, weight_bounds):
        self.expected_returns = expected_returns
        self.covariance = covariance
        self.weight_bounds = weight_bounds
        self.method = ""

    def max_sharpe(self) -> None:
        self.method = "max_sharpe"

    def min_volatility(self) -> None:
        self.method = "min_volatility"

    def clean_weights(self) -> dict[str, float]:
        assert self.method == "max_sharpe"
        assert self.weight_bounds == (0.0, 0.7)
        return {"VOO": 0.4, "QQQ": 0.6}
