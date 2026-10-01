from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from quant_shared.trend_environment import Bar, EnvironmentConfig, estimate


def sample(asset="BTC", count=10):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Bar(asset, start + timedelta(hours=i), start + timedelta(hours=i+1),
                start + timedelta(hours=i+1), 100 + i + (i % 2)*.2) for i in range(count)]


def observe(rows, **kw):
    now = kw.pop("decision_time", rows[-1].close_time)
    return estimate(rows, asset=kw.pop("asset", "BTC"), decision_time=now,
                    expected_close_times=kw.pop("schedule", [r.close_time for r in rows]),
                    config=kw.pop("config", EnvironmentConfig((3, 5), "UTC_24x7", 8760, 3600)), **kw)


def test_future_prices_and_other_assets_cannot_change_history():
    bars = sample()
    original = observe(bars[:7])
    future = [replace(b, close=float("nan")) for b in bars[7:]]
    assert observe(bars[:7] + future + sample("SPY"), decision_time=bars[6].close_time) == original


@pytest.mark.parametrize("price", [float("nan"), float("inf"), 0, -1])
def test_bad_visible_prices_are_unknown_not_normal(price):
    result = observe(sample()[:-1] + [replace(sample()[-1], close=price)])
    assert result[0]["status"] == "unknown" and result[0]["direction"] is None
    assert "invalid_price" in result[0]["reasons"]


def test_warmup_late_unfinished_missing_and_stale_are_explicit():
    assert "warmup" in observe(sample(count=2))[0]["reasons"]
    bars = sample()
    for last in (replace(bars[-1], completed=False), replace(bars[-1], available_time=bars[-1].close_time+timedelta(hours=1))):
        assert "missing_expected_bar" in observe(bars[:-1]+[last])[0]["reasons"]
    assert "missing_expected_bar" in observe(bars[:5]+bars[6:], schedule=[b.close_time for b in bars])[1]["reasons"]
    assert "stale" in observe(bars, decision_time=bars[-1].close_time+timedelta(hours=2))[0]["reasons"]


@pytest.mark.parametrize("calendar,asset", [("XNYS", "SPY"), ("XSHG", "600000")])
def test_session_calendar_is_injected_not_btc_24x7(calendar, asset):
    bars = sample(asset)
    bars = [replace(b, event_time=b.event_time+timedelta(days=i//5*2),
                    close_time=b.close_time+timedelta(days=i//5*2), available_time=b.available_time+timedelta(days=i//5*2)) for i,b in enumerate(bars)]
    config = EnvironmentConfig((3,), calendar, 252, 86400)
    result = observe(bars, asset=asset, config=config)[0]
    assert result["status"] == "observed" and result["calendar"] == calendar
    assert result["annualized_volatility"] == pytest.approx(result["bar_volatility"] * 252**.5)


def test_scores_are_descriptive_and_configuration_is_frozen():
    result = observe(sample())[0]
    assert result["direction"] == "up" and 0 <= result["trend_fit"] <= 1
    assert result["usage"] == "observation_only" and "probability" not in result
    assert result["input_hash"] != observe(sample()[:-1]+[replace(sample()[-1], close=111)])[0]["input_hash"]
    with pytest.raises(ValueError): EnvironmentConfig((3,), "", 252, 3600)
    with pytest.raises(ValueError): EnvironmentConfig((2, 2), "XNYS", 252, 3600)


def test_naive_timestamps_and_duplicate_bars_are_rejected():
    with pytest.raises(ValueError): observe([replace(sample()[0], available_time=datetime(2026,1,1))])
    assert "duplicate_or_unordered" in observe(sample()+sample()[-1:])[0]["reasons"]
