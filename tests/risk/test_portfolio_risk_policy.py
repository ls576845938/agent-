from __future__ import annotations

from quant_us.risk.pre_trade import PortfolioRiskPolicy


def test_gross_cap_respects_cash_reserve_and_explicit_cap() -> None:
    policy = PortfolioRiskPolicy(
        cash_reserve_weight=0.15,
        max_symbol_weight=0.20,
        max_gross_exposure=0.90,
        max_daily_turnover=1.0,
    )

    assert policy.gross_cap() == 0.85
    assert policy.clamp_symbol_weight(0.25) == 0.20
    assert policy.clamp_symbol_weight(-0.25) == -0.20


def test_scale_target_weights_for_turnover_caps_net_weight_change() -> None:
    policy = PortfolioRiskPolicy(
        cash_reserve_weight=0.05,
        max_symbol_weight=0.25,
        max_gross_exposure=0.95,
        max_daily_turnover=0.20,
    )

    scaled, scale = policy.scale_target_weights_for_turnover(
        current_weights={"AAPL": 0.10, "MSFT": 0.00},
        target_weights={"AAPL": 0.40, "MSFT": 0.10},
    )

    assert round(scale, 4) == 0.5
    assert scaled["AAPL"] == 0.25
    assert scaled["MSFT"] == 0.05
