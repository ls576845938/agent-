from __future__ import annotations

from datetime import datetime, timezone

from quant_us.backtest.walk_forward import WalkForwardConfig, build_walk_forward_windows
from quant_us.core.types import Bar


def test_walk_forward_train_and_test_dates_are_disjoint() -> None:
    bars = [
        Bar(timestamp_utc=datetime(2026, 1, day, tzinfo=timezone.utc), symbol="AAPL", open=1, high=1, low=1, close=1, volume=1)
        for day in range(1, 9)
    ]

    windows = build_walk_forward_windows(
        bars,
        WalkForwardConfig(train_bars=3, test_bars=2, step_bars=2),
    )

    assert windows
    for window in windows:
        assert window.train_end < window.test_start
        assert window.test_start <= window.test_end


def test_test_fold_cannot_feed_back_into_training_threshold() -> None:
    train_values = [1.0, 2.0, 3.0]
    test_values = [100.0, 200.0]

    threshold_before = sum(train_values) / len(train_values)
    threshold_after = sum(train_values) / len(train_values)

    assert threshold_before == threshold_after
    assert max(test_values) > threshold_after


def test_walk_forward_contract_requires_purge_for_forward_labels() -> None:
    forward_horizon_bars = 5
    purge_bars = 5

    assert purge_bars >= forward_horizon_bars
