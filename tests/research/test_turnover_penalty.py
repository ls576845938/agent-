from quant_us.research.btc_alpha_hardening import hardening_objective_score


def test_hardening_objective_penalizes_turnover() -> None:
    base_metrics = {
        "profit_factor": 1.2,
        "walk_forward_pass_rate": 0.8,
        "regime_pass_rate": 0.75,
        "cost_adjusted_return_pct": 5.0,
    }

    low_turnover = hardening_objective_score({**base_metrics, "annual_turnover": 3.0})
    high_turnover = hardening_objective_score({**base_metrics, "annual_turnover": 30.0})

    assert low_turnover > high_turnover
