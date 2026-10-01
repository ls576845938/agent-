from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.data.free_derivatives_sources import (
    HOUR_MS,
    normalize_binance_derivatives_sentiment_rows,
    normalize_okx_derivatives_sentiment_rows,
)
from scripts.fetch_btc_free_derivatives_sentiment_history import fetch_btc_free_derivatives_sentiment_history


TS = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)
START = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)


def test_normalize_binance_free_derivatives_rows_builds_hourly_pit_rows() -> None:
    open_interest = [
        {"timestamp": START + index * HOUR_MS, "sumOpenInterestValue": str(10_000_000 + index)}
        for index in range(30)
    ]
    long_short = [
        {"timestamp": START + index * HOUR_MS, "longShortRatio": str(1.0 + index * 0.001)}
        for index in range(30)
    ]
    funding = [
        {"fundingTime": START, "fundingRate": "0.0001"},
        {"fundingTime": START + 8 * HOUR_MS, "fundingRate": "0.0002"},
    ]
    force_orders = [
        {"time": START + 2 * HOUR_MS + 1000, "side": "SELL", "averagePrice": "100000", "origQty": "0.01"},
        {"time": START + 3 * HOUR_MS + 1000, "side": "BUY", "averagePrice": "100000", "origQty": "0.02"},
    ]

    rows = normalize_binance_derivatives_sentiment_rows(
        open_interest_hist=open_interest,
        long_short_ratio=long_short,
        funding_rates=funding,
        force_orders=force_orders,
        start_hour_ms=START,
        end_hour_ms=START + 29 * HOUR_MS,
        generated_at_utc=TS,
    )

    assert len(rows) == 30
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[0]["source_provider"] == "binance_usdm_free_public"
    assert rows[0]["available_time"] > rows[0]["event_time"]
    assert rows[10]["funding_rate"] == 0.0002
    assert rows[2]["long_liquidation_usd"] == 1000.0
    assert rows[3]["short_liquidation_usd"] == 2000.0
    assert len(rows[0]["source_raw_payload_hash"]) == 64


def test_normalize_okx_free_derivatives_rows_builds_hourly_pit_rows() -> None:
    open_interest_volume = [[str(START + index * HOUR_MS), str(20_000_000 + index), "1000"] for index in range(30)]
    long_short = [[str(START + index * HOUR_MS), str(1.5 + index * 0.001)] for index in range(30)]
    funding = [
        {"fundingTime": str(START), "fundingRate": "0.0001"},
        {"fundingTime": str(START + 8 * HOUR_MS), "fundingRate": "0.0003"},
    ]
    liquidation = [
        {"ts": str(START + 2 * HOUR_MS + 1000), "posSide": "long", "side": "sell", "bkPx": "100000", "sz": "0.01"},
        {"ts": str(START + 3 * HOUR_MS + 1000), "posSide": "short", "side": "buy", "bkPx": "100000", "sz": "0.02"},
    ]

    rows = normalize_okx_derivatives_sentiment_rows(
        open_interest_volume=open_interest_volume,
        long_short_ratio=long_short,
        funding_rates=funding,
        liquidation_orders=liquidation,
        start_hour_ms=START,
        end_hour_ms=START + 29 * HOUR_MS,
        generated_at_utc=TS,
    )

    assert len(rows) == 30
    assert rows[0]["venue"] == "okx_swap"
    assert rows[0]["source_provider"] == "okx_free_public"
    assert rows[10]["funding_rate"] == 0.0003
    assert rows[2]["long_liquidation_usd"] == 1000.0
    assert rows[3]["short_liquidation_usd"] == 2000.0
    assert rows[-1]["open_interest_usd"] == 20_000_029.0
    assert rows[-1]["long_short_ratio"] == 1.529


def test_fetch_history_dry_run_writes_planned_audit_without_network(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    rows = tmp_path / "rows.json"

    payload = fetch_btc_free_derivatives_sentiment_history(
        rows_output=rows,
        audit_output=audit,
        generated_at_utc=TS,
        execute_network=False,
    )

    assert payload["status"] == "planned"
    assert payload["network_called"] is False
    assert payload["api_key_used"] is False
    assert not rows.exists()
    assert audit.exists()
