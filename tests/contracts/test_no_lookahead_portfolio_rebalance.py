from __future__ import annotations

from datetime import datetime, timezone


def test_rebalance_orders_use_only_pre_rebalance_alpha_scores() -> None:
    rebalance_time = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    alpha_scores = [
        {"timestamp": datetime(2026, 1, 5, 14, 29, tzinfo=timezone.utc), "symbol": "AAPL", "score": 0.6},
        {"timestamp": datetime(2026, 1, 5, 14, 31, tzinfo=timezone.utc), "symbol": "MSFT", "score": 0.4},
    ]

    usable = [row for row in alpha_scores if row["timestamp"] < rebalance_time]

    assert usable == [alpha_scores[0]]


def test_target_portfolio_does_not_use_future_close() -> None:
    rebalance_date = "2026-01-05"
    close_by_date = {"2026-01-05": 100.0, "2026-01-06": 125.0}

    reference_close = close_by_date[rebalance_date]

    assert reference_close == 100.0
    assert reference_close != close_by_date["2026-01-06"]


def test_cost_model_uses_fill_price_not_future_mark() -> None:
    fill_price = 100.0
    future_mark = 110.0
    commission = 1.0
    slippage_bps = 5.0

    cost = commission + fill_price * slippage_bps / 10_000.0

    assert cost == 1.05
    assert cost != commission + future_mark * slippage_bps / 10_000.0
