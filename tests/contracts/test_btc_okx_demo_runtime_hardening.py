from __future__ import annotations

import json

import pytest

from quant_crypto.oms.runtime_store import (
    BTCRecordedPrivateWSAdapter,
    BTCRuntimeStore,
    BTCRuntimeStoreError,
)


SAFETY = {
    "demo_order_enabled": False,
    "private_endpoint_enabled": False,
    "live_enabled": False,
    "withdraw_enabled": False,
}


def _append(store: BTCRuntimeStore, key: str, status: str) -> dict:
    return store.append(
        event_type="order_lifecycle",
        payload={"status": status},
        state_after={
            "runtime": {
                "active": status not in {"cancelled", "reconciled"},
                "status": status,
            }
        },
        idempotency_key=key,
        timestamp_utc="2026-07-24T00:00:00Z",
        run_id="fixture-run",
        safety=SAFETY,
    )


def test_crash_restart_replays_events_after_atomic_checkpoint(tmp_path) -> None:
    store = BTCRuntimeStore(tmp_path)
    _append(store, "intent-1", "intent")
    store.checkpoint({"runtime": {"active": True, "status": "accepted"}})
    _append(store, "fill-1", "partial")

    recovered = BTCRuntimeStore(tmp_path).recover()

    assert recovered.blockers == ()
    assert recovered.last_sequence == 2
    assert recovered.state["runtime"]["active"] is True
    assert recovered.state["runtime"]["status"] == "partial"


def test_truncated_tail_recovers_prior_event_and_fails_closed(tmp_path) -> None:
    store = BTCRuntimeStore(tmp_path)
    first = _append(store, "intent-1", "accepted")
    with store.events_path.open("ab") as handle:
        handle.write(b'{"sequence":2')

    recovered = BTCRuntimeStore(tmp_path).recover()

    assert recovered.last_event_hash == first["event_hash"]
    assert recovered.truncated_tail is True
    assert "btc_runtime_event_log_truncated_tail" in recovered.blockers


def test_duplicate_is_idempotent_but_conflicting_duplicate_is_blocked(tmp_path) -> None:
    store = BTCRuntimeStore(tmp_path)
    first = _append(store, "ack-1", "accepted")
    assert _append(store, "ack-1", "accepted") == first
    with pytest.raises(BTCRuntimeStoreError, match="idempotency_conflict"):
        _append(store, "ack-1", "rejected")
    assert len(store.events_path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize(
    "status",
    ["intent", "accepted", "partial", "filled", "rejected", "cancelled", "unknown", "reconciled"],
)
def test_explicit_lifecycle_events_are_durable(tmp_path, status) -> None:
    event = _append(BTCRuntimeStore(tmp_path), f"event-{status}", status)
    assert event["payload"]["status"] == status


def test_out_of_order_or_mutated_chain_blocks_recovery(tmp_path) -> None:
    store = BTCRuntimeStore(tmp_path)
    _append(store, "ack-1", "accepted")
    _append(store, "fill-1", "partial")
    rows = store.events_path.read_text(encoding="utf-8").splitlines()
    store.events_path.write_text(rows[1] + "\n" + rows[0] + "\n", encoding="utf-8")
    recovered = BTCRuntimeStore(tmp_path).recover()
    assert "btc_runtime_event_chain_invalid" in recovered.blockers


def test_ledger_uow_requires_funding_mark_index_liquidation_and_venue_rules(tmp_path) -> None:
    store = BTCRuntimeStore(tmp_path)
    base = dict(
        idempotency_key="uow-1",
        timestamp_utc="2026-07-24T00:00:00Z",
        run_id="fixture-run",
        order={"client_order_id": "c1", "status": "filled"},
        fills=[{"fill_id": "f1", "size": "1"}],
        position={"contracts": "1"},
        cash={"available": "1000"},
        funding={"rate": "0.0001", "settlement_time": "2026-07-24T08:00:00Z"},
        state_after={"runtime": {"opening_allowed": False}},
        safety=SAFETY,
    )
    with pytest.raises(BTCRuntimeStoreError, match="risk_context_incomplete"):
        store.commit_ledger_uow(risk_context={"mark_price": "100"}, **base)

    event = store.commit_ledger_uow(
        risk_context={
            "mark_price": "100",
            "index_price": "99.9",
            "liquidation_buffer_bps": "250",
            "venue_rules": {"tick_size": "0.1", "lot_size": "1"},
        },
        **base,
    )
    assert event["event_type"] == "ledger_uow_committed"
    assert BTCRuntimeStore(tmp_path).recover().blockers == ()


def test_reconciliation_mismatch_and_runtime_anomalies_remain_fail_closed(tmp_path) -> None:
    store = BTCRuntimeStore(tmp_path)
    event = store.append(
        event_type="runtime_guard",
        payload={
            "public_ws_connected": False,
            "sequence_gap": True,
            "clock_drift_exceeded": True,
            "ledger_consistent": False,
            "reconciliation_match": False,
            "cancel_only": True,
            "opening_allowed": False,
        },
        state_after={"runtime": {"cancel_only": True, "opening_allowed": False}},
        idempotency_key="guard-1",
        timestamp_utc="2026-07-24T00:00:00Z",
        run_id="fixture-run",
        safety=SAFETY,
    )
    assert event["payload"]["opening_allowed"] is False
    assert event["payload"]["cancel_only"] is True


def test_private_ws_adapter_is_recorded_only_and_never_connects() -> None:
    adapter = BTCRecordedPrivateWSAdapter(({"event": "accepted"}, {"event": "partial"}))
    assert adapter.live_connection_enabled is False
    assert [row["event"] for row in adapter.replay()] == ["accepted", "partial"]
    with pytest.raises(BTCRuntimeStoreError, match="not_authorized"):
        adapter.connect()
