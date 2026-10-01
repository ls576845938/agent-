from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_crypto.exchange.runtime import (
    BTC_EXCHANGE_RUNTIME_LOCAL_PROBE_VERSION,
    BTCExchangeRuntimeSnapshot,
    BTCExchangeRuntimeStatus,
    BTCGapfillState,
    BTCRestStatus,
    BTCStreamStatus,
    build_btc_exchange_runtime_local_probe_artifact,
)
from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def _healthy_snapshot(**overrides: object) -> BTCExchangeRuntimeSnapshot:
    kwargs = {
        "venue": "binance_usdm",
        "instrument_id": "BTCUSDT",
        "observed_at_utc": TS,
        "exchange_status": BTCExchangeRuntimeStatus.OK,
        "public_ws_status": BTCStreamStatus.CONNECTED,
        "private_ws_status": BTCStreamStatus.CONNECTED,
        "rest_status": BTCRestStatus.OK,
        "server_time_offset_ms": 50,
        "rate_limit_budget_remaining": 100,
        "order_rate_budget_remaining": 50,
        "last_market_data_time_utc": TS - timedelta(seconds=5),
        "last_private_event_time_utc": TS - timedelta(seconds=10),
        "last_reconciliation_time_utc": TS - timedelta(seconds=20),
        "unreconciled_order_count": 0,
        "unreconciled_fill_count": 0,
        "metadata_version": "exchange_info_hash_v1",
        "mode": "paper",
    }
    kwargs.update(overrides)
    return BTCExchangeRuntimeSnapshot(**kwargs)


def test_btc_exchange_runtime_artifact_allows_simulated_paper_only_when_healthy() -> None:
    artifact = _healthy_snapshot().to_artifact()

    assert artifact["status"] == "complete"
    assert artifact["decision"] == "runtime_tradeable_for_simulated_paper"
    assert artifact["allows_live_orders"] is False
    assert artifact["real_order_submitted"] is False
    assert artifact["private_endpoint_used"] is False
    assert artifact["order_endpoint_used"] is False
    assert artifact["blockers"] == []
    assert validate_btc_artifact_schema(artifact) == []


def test_btc_exchange_runtime_blocks_live_mode_and_private_endpoint_enablement() -> None:
    artifact = _healthy_snapshot(
        mode="live",
        private_endpoints_enabled=True,
        order_endpoints_enabled=True,
    ).to_artifact()

    assert artifact["status"] == "blocked"
    assert "btc_exchange_runtime_live_mode_not_authorized" in artifact["blockers"]

    paper_private = _healthy_snapshot(private_endpoints_enabled=True).to_artifact()
    assert "btc_exchange_runtime_non_live_private_or_order_endpoint_enabled" in paper_private["blockers"]


def test_btc_exchange_runtime_blocks_stale_data_streams_and_reconciliation() -> None:
    artifact = _healthy_snapshot(
        public_ws_status=BTCStreamStatus.STALE,
        private_ws_status=BTCStreamStatus.DISCONNECTED,
        rest_status=BTCRestStatus.DEGRADED,
        last_market_data_time_utc=TS - timedelta(minutes=5),
        last_private_event_time_utc=TS - timedelta(minutes=5),
        last_reconciliation_time_utc=TS - timedelta(minutes=10),
        unreconciled_order_count=1,
        unreconciled_fill_count=2,
    ).to_artifact()

    assert "btc_exchange_public_ws_not_connected:stale" in artifact["blockers"]
    assert "btc_exchange_private_ws_not_connected:disconnected" in artifact["blockers"]
    assert "btc_exchange_rest_not_ok:degraded" in artifact["blockers"]
    assert "btc_exchange_market_data_stale" in artifact["blockers"]
    assert "btc_exchange_private_event_stale" in artifact["blockers"]
    assert "btc_exchange_reconciliation_stale" in artifact["blockers"]
    assert "btc_exchange_unreconciled_orders" in artifact["blockers"]
    assert "btc_exchange_unreconciled_fills" in artifact["blockers"]


def test_btc_exchange_runtime_blocks_server_time_rate_budget_metadata_and_cancel_only() -> None:
    artifact = _healthy_snapshot(
        exchange_status=BTCExchangeRuntimeStatus.CANCEL_ONLY,
        cancel_only=True,
        server_time_offset_ms=5_000,
        rate_limit_budget_remaining=1,
        order_rate_budget_remaining=0,
        metadata_version="",
    ).to_artifact()

    assert "btc_exchange_cancel_only_blocks_new_orders" in artifact["blockers"]
    assert "btc_exchange_server_time_offset_exceeds_tolerance" in artifact["blockers"]
    assert "btc_exchange_rate_limit_budget_below_threshold" in artifact["blockers"]
    assert "btc_exchange_order_rate_budget_below_threshold" in artifact["blockers"]
    assert "btc_exchange_metadata_version_missing" in artifact["blockers"]


def test_btc_exchange_runtime_blocks_failed_gapfill_and_requires_trading_block() -> None:
    artifact = _healthy_snapshot(
        public_ws_gapfill=BTCGapfillState(
            stream="public_l2",
            gap_detected=True,
            recovered=False,
            recovery_method="",
            trading_blocked=False,
        ),
        private_ws_gapfill=BTCGapfillState(
            stream="private_orders",
            gap_detected=True,
            recovered=True,
            recovery_method="rest_open_orders_recent_fills",
            orders_reconciled=3,
            fills_reconciled=2,
            trading_blocked=True,
        ),
    ).to_artifact()

    assert "btc_exchange_gapfill_not_recovered:public_l2" in artifact["blockers"]
    assert "btc_exchange_gapfill_method_missing:public_l2" in artifact["blockers"]
    assert "btc_exchange_gapfill_did_not_block_trading:public_l2" in artifact["blockers"]
    assert not any("private_orders" in blocker for blocker in artifact["blockers"])


def test_btc_exchange_runtime_local_probe_explains_server_time_gapfill_cancel_only_and_budget() -> None:
    artifact = build_btc_exchange_runtime_local_probe_artifact(
        observed_at_utc=TS,
        local_receive_time_utc=TS,
        exchange_server_time_utc=TS + timedelta(milliseconds=200),
        venue="okx",
        instrument_id="BTC-USDT-SWAP",
        public_ws_sequences=(10, 11, 14, 15),
        public_gapfill_sequences=(12, 13),
        metadata_version="okx_rules_hash_v1",
        rate_limit_budget_remaining=25,
        order_rate_budget_remaining=0,
        cancel_only=True,
    )

    assert artifact["schema_version"] == BTC_EXCHANGE_RUNTIME_LOCAL_PROBE_VERSION
    assert artifact["server_time_offset_diagnostics"]["offset_ms"] == 200
    assert artifact["server_time_offset_diagnostics"]["within_threshold"] is True
    assert artifact["ws_sequence_gapfill_replay"]["gap_detected"] is True
    assert artifact["ws_sequence_gapfill_replay"]["missing_sequences"] == [12, 13]
    assert artifact["ws_sequence_gapfill_replay"]["recovered"] is True
    assert artifact["metadata_version_diagnostics"]["present"] is True
    assert artifact["cancel_only_state"]["new_orders_blocked"] is True
    assert artifact["rate_limit_budget_explanation"]["public_rest_or_ws_budget"]["status"] == "ok"
    assert artifact["rate_limit_budget_explanation"]["order_entry_budget"]["status"] == "blocked"
    assert artifact["state_machine"]["final_state"] == "fail_closed"
    assert "btc_exchange_cancel_only_blocks_new_orders" in artifact["blockers"]
    assert artifact["guardrails"]["private_endpoint_used"] is False
    assert artifact["guardrails"]["order_endpoint_used"] is False
    assert artifact["guardrails"]["live_unlock_allowed"] is False
    assert validate_btc_artifact_schema(artifact) == []


def test_btc_exchange_runtime_local_probe_blocks_unrecovered_gap_missing_metadata_and_time_offset() -> None:
    artifact = build_btc_exchange_runtime_local_probe_artifact(
        observed_at_utc=TS,
        local_receive_time_utc=TS,
        exchange_server_time_utc=TS + timedelta(seconds=3),
        venue="okx",
        instrument_id="BTC-USDT-SWAP",
        public_ws_sequences=(100, 103),
        public_gapfill_sequences=(101,),
        metadata_version="",
        rate_limit_budget_remaining=1,
        order_rate_budget_remaining=1,
        cancel_only=False,
    )

    assert artifact["ws_sequence_gapfill_replay"]["unrecovered_sequences"] == [102]
    assert "btc_exchange_gapfill_not_recovered:public_market_data" in artifact["blockers"]
    assert "btc_exchange_server_time_offset_exceeds_tolerance" in artifact["blockers"]
    assert "btc_exchange_metadata_version_missing" in artifact["blockers"]
    assert "btc_exchange_rate_limit_budget_below_threshold" in artifact["blockers"]
    assert "btc_exchange_order_rate_budget_below_threshold" in artifact["blockers"]
    assert artifact["runtime_snapshot"]["private_endpoint_used"] is False
    assert artifact["runtime_snapshot"]["order_endpoint_used"] is False
