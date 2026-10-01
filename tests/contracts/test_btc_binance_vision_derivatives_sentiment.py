from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_crypto.data.binance_vision_derivatives import (
    aggregate_metrics_5m_to_1h,
    build_binance_vision_derivatives_audit,
    build_binance_vision_derivatives_sentiment_rows,
)


TS = datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_binance_vision_metrics_5m_aggregate_to_next_1h_decision_timestamp() -> None:
    rows = [_metrics_row(TS + timedelta(minutes=5 * index), index) for index in range(12)]

    hourly = aggregate_metrics_5m_to_1h(rows, generated_at_utc=TS + timedelta(hours=2))

    assert len(hourly) == 1
    row = hourly[0]
    assert row["event_time"] == "2026-06-01T01:00:00+00:00"
    assert row["available_time"] == "2026-06-01T01:05:00+00:00"
    assert row["metrics_window_start"] == "2026-06-01T00:00:00+00:00"
    assert row["metrics_window_end"] == "2026-06-01T01:00:00+00:00"
    assert row["metrics_5m_row_count"] == 12
    assert row["open_interest"] == 1011.0
    assert row["open_interest_usd"] == 2011.0
    assert row["long_short_ratio"] == 1.11
    assert row["top_trader_long_short_ratio"] == 2.11
    assert row["top_trader_long_short_position_ratio"] == 3.11
    assert row["taker_buy_sell_ratio"] == 0.61


def test_binance_vision_funding_monthly_plus_okx_tail_liquidation_merge() -> None:
    metrics = []
    for hour in range(3):
        base = TS + timedelta(hours=hour)
        metrics.extend(_metrics_row(base + timedelta(minutes=5 * index), hour * 12 + index) for index in range(12))
    funding = [
        {
            "calc_time": str(int((TS + timedelta(hours=1)).timestamp() * 1000)),
            "last_funding_rate": "0.0002",
        }
    ]
    okx_tail = [
        {
            "event_time": "2026-06-01T02:00:00+00:00",
            "available_time": "2026-06-01T02:05:00+00:00",
            "funding_rate": 0.0003,
            "long_liquidation_usd": 100.0,
            "short_liquidation_usd": 200.0,
        }
    ]

    result = build_binance_vision_derivatives_sentiment_rows(
        metrics_rows_5m=metrics,
        funding_rows=funding,
        okx_tail_rows=okx_tail,
        generated_at_utc=TS + timedelta(hours=4),
    )

    rows = {row["event_time"]: row for row in result.rows}
    assert rows["2026-06-01T01:00:00+00:00"]["funding_rate"] == 0.0002
    assert rows["2026-06-01T02:00:00+00:00"]["funding_rate"] == 0.0003
    assert rows["2026-06-01T02:00:00+00:00"]["long_liquidation_usd"] == 100.0
    assert rows["2026-06-01T02:00:00+00:00"]["short_liquidation_usd"] == 200.0
    assert rows["2026-06-01T03:00:00+00:00"]["long_liquidation_usd"] is None
    assert rows["2026-06-01T03:00:00+00:00"]["liquidation_source"] is None


def test_binance_vision_audit_never_claims_full_1h_liquidation_history() -> None:
    rows = [
        {
            "event_time": (TS + timedelta(hours=index)).isoformat(),
            "open_interest_usd": 1_000_000.0,
            "funding_rate": 0.0001,
            "long_liquidation_usd": 1.0 if index == 0 else None,
            "short_liquidation_usd": 1.0 if index == 0 else None,
            "long_short_ratio": 1.1,
            "open_interest": 100.0,
            "top_trader_long_short_ratio": 1.2,
            "top_trader_long_short_position_ratio": 1.3,
            "taker_buy_sell_ratio": 0.9,
        }
        for index in range(24 * 180)
    ]

    audit = build_binance_vision_derivatives_audit(
        rows=rows,
        generated_at_utc=TS,
        metrics_raw_count=24 * 180 * 12,
        funding_raw_count=540,
        okx_tail_raw_count=720,
        github_daily_liquidation_diagnostics={
            "source": "ErcinDedeoglu/crypto-market-data",
            "frequency": "daily",
            "gate_eligible": False,
        },
    )

    assert audit["status"] == "complete"
    assert audit["liquidation_policy"]["one_hour_history_complete"] is False
    assert audit["liquidation_policy"]["gate_eligible"] is False
    assert audit["liquidation_policy"]["do_not_claim_full_1h_liquidation_coverage"] is True
    assert audit["github_daily_liquidation_diagnostics"]["gate_eligible"] is False
    assert audit["public_market_data_only"] is True
    assert audit["private_endpoint_used"] is False
    assert audit["order_endpoint_used"] is False
    assert audit["real_order_submitted"] is False


def _metrics_row(ts: datetime, index: int) -> dict[str, str]:
    return {
        "create_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": "BTCUSDT",
        "sum_open_interest": str(1000.0 + index),
        "sum_open_interest_value": str(2000.0 + index),
        "count_toptrader_long_short_ratio": str(2.0 + index / 100.0),
        "sum_toptrader_long_short_ratio": str(3.0 + index / 100.0),
        "count_long_short_ratio": str(1.0 + index / 100.0),
        "sum_taker_long_short_vol_ratio": str(0.5 + index / 100.0),
    }
