from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import quant_crypto.adapters.okx_public_ws as okx_public_ws

from quant_crypto.adapters.okx_public_ws import (
    OKXPublicWSContractError,
    OKXPublicWSL2Adapter,
    okx_l2_checksum,
    public_websocket_dependency_receipt,
)
from quant_crypto.application.btc_ws_l2_funding_reconciliation_closure import (
    EXTERNAL_BLOCKERS,
    build_offline_engineering_closure,
)
from quant_crypto.backtest.funding_ledger import (
    FundingFill,
    FundingRateEvent,
    replay_perpetual_fill_position_cash_ledger,
)
from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_crypto.oms.private_ws_reconciliation import (
    BTCPrivateWSEventKind,
    BTCPrivateWSFixtureEvent,
    reconcile_private_ws_offline_fixture,
)


NOW = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
HEAD = "a" * 40


def _fake_websocket_module() -> SimpleNamespace:
    return SimpleNamespace(
        __name__="websocket",
        __version__="1.8.0-fixture",
        create_connection=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hermetic test must not construct a socket")
        ),
    )


def test_public_websocket_dependency_is_installable_and_import_only() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'btc-public-ws = [' in pyproject
    assert '"websocket-client>=1.8,<2"' in pyproject
    project_dependencies = pyproject.split(
        "[project.optional-dependencies]", 1
    )[0]
    assert '"websocket-client>=1.8,<2"' in project_dependencies

    receipt = public_websocket_dependency_receipt(_fake_websocket_module)

    assert receipt["import_safe"] is True
    assert receipt["public_only"] is True
    assert receipt["network_accessed"] is False
    assert receipt["private_endpoint_accessed"] is False
    assert receipt["order_endpoint_accessed"] is False
    assert receipt["blockers"] == []


def test_canonical_public_websocket_dependency_identity_is_allowlisted() -> None:
    receipt = public_websocket_dependency_receipt()

    assert receipt["distribution_name"] == "websocket-client"
    assert receipt["distribution_version"] == receipt["module_version"]
    assert receipt["module_name"] == "websocket"
    assert len(receipt["module_sha256"]) == 64
    assert len(receipt["package_sha256"]) == 64
    assert receipt["allowlist_valid"] is True
    assert receipt["user_site_consumed"] is False
    assert receipt["import_safe"] is True
    assert receipt["network_accessed"] is False
    assert receipt["blockers"] == []
    expected_roots = {
        str((Path(prefix) / "Lib" / "site-packages").resolve())
        for prefix in (sys.prefix, sys.base_prefix)
    }
    assert set(receipt["allowlist_roots"]) == expected_roots


def test_public_websocket_dependency_rejects_user_site_or_arbitrary_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(okx_public_ws.sys, "prefix", str(tmp_path / "active"))
    monkeypatch.setattr(okx_public_ws.sys, "base_prefix", str(tmp_path / "base"))

    receipt = public_websocket_dependency_receipt()

    assert receipt["allowlist_valid"] is False
    assert receipt["user_site_consumed"] is True
    assert receipt["import_safe"] is False
    assert receipt["network_accessed"] is False
    assert receipt["private_endpoint_accessed"] is False
    assert receipt["order_endpoint_accessed"] is False
    assert receipt["blockers"] == [
        "btc_okx_websocket_client_dependency_not_allowlisted"
    ]


def test_public_l2_adapter_emits_normalized_market_event_only() -> None:
    adapter = OKXPublicWSL2Adapter(instrument_id="BTC-USDT-SWAP")
    adapter.on_connected()
    bids = {"100000": "1"}
    asks = {"100010": "1"}
    payload = {
        "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
        "action": "snapshot",
        "data": [
            {
                "bids": [["100000", "1", "0", "1"]],
                "asks": [["100010", "1", "0", "1"]],
                "ts": str(int(NOW.timestamp() * 1000)),
                "seqId": 10,
                "prevSeqId": -1,
                "checksum": okx_l2_checksum(bids, asks),
            }
        ],
    }

    events = adapter.ingest(payload, received_time_utc=NOW)

    assert len(events) == 1
    event = events[0].to_dict()
    assert event["event_type"] == "normalized_market_l2"
    assert event["venue"] == "OKX"
    assert event["sequence"] == 10
    assert "signal" not in event
    assert "order_intent" not in event
    assert "risk_decision" not in event
    assert adapter.recovery_receipt()["market_event_only"] is True


@pytest.mark.parametrize(
    ("previous_sequence", "checksum_delta", "timestamp_delta", "expected"),
    [
        (8, 0, 100, "btc_okx_l2_sequence_gap"),
        (10, 1, 100, "btc_okx_l2_checksum_mismatch"),
        (10, 0, 10_000, "btc_okx_l2_timestamp_gap"),
    ],
)
def test_l2_integrity_failures_enter_cancel_only(
    previous_sequence: int,
    checksum_delta: int,
    timestamp_delta: int,
    expected: str,
) -> None:
    adapter = OKXPublicWSL2Adapter(
        instrument_id="BTC-USDT-SWAP", max_timestamp_gap_ms=1_000
    )
    adapter.on_connected()
    bids = {"100000": "1"}
    asks = {"100010": "1"}
    base = {
        "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
        "action": "snapshot",
        "data": [
            {
                "bids": [["100000", "1", "0", "1"]],
                "asks": [["100010", "1", "0", "1"]],
                "ts": str(int(NOW.timestamp() * 1000)),
                "seqId": 10,
                "prevSeqId": -1,
                "checksum": okx_l2_checksum(bids, asks),
            }
        ],
    }
    adapter.ingest(base, received_time_utc=NOW)
    update = {
        **base,
        "action": "update",
        "data": [
            {
                "bids": [],
                "asks": [],
                "ts": str(int(NOW.timestamp() * 1000) + timestamp_delta),
                "seqId": 11,
                "prevSeqId": previous_sequence,
                "checksum": okx_l2_checksum(bids, asks) + checksum_delta,
            }
        ],
    }

    with pytest.raises(OKXPublicWSContractError, match=expected):
        adapter.ingest(update, received_time_utc=NOW)

    assert adapter.cancel_only is True
    assert adapter.recovery_receipt()["new_risk_allowed"] is False


def test_funding_pnl_is_derived_from_fill_position_and_cash_ledgers() -> None:
    fills = [
        FundingFill(
            filled_at=NOW,
            side="buy",
            quantity=0.02,
            price=100_000,
            fill_id="fill-1",
            fee=0.2,
        )
    ]
    funding = [
        FundingRateEvent(
            funding_time=datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc),
            funding_rate=0.0001,
            mark_price=100_500,
            index_price=100_450,
            source_record_id="funding-1",
        )
    ]

    pnl = replay_perpetual_fill_position_cash_ledger(
        fills=fills,
        funding_rates=funding,
        valuation_mark_price=100_500,
    )

    assert pnl.position_qty == pytest.approx(0.02)
    assert pnl.price_pnl == pytest.approx(10.0)
    assert pnl.funding_pnl == pytest.approx(-0.201)
    assert pnl.fee_pnl == pytest.approx(-0.2)
    assert pnl.total_pnl == pytest.approx(9.599)
    assert pnl.cash_balance + pnl.position_value == pytest.approx(
        pnl.total_pnl
    )
    assert {row.event_type for row in pnl.ledger_entries} == {
        "fill_cashflow",
        "fee_cashflow",
        "funding_cashflow",
    }


def test_private_ws_fixture_rejects_conflicting_idempotency() -> None:
    events = [
        BTCPrivateWSFixtureEvent(
            1,
            "event-1",
            BTCPrivateWSEventKind.ORDER_ACK,
            "order-1",
            idempotency_key="wrong-key",
        )
    ]
    rows = [
        {
            "sequence": 1,
            "event_id": "event-1",
            "kind": "order_ack",
            "client_order_id": "order-1",
            "fill_id": "",
            "filled_quantity": 0.0,
            "fill_price": 0.0,
            "remaining_quantity": 0.0,
            "order_status": "",
            "idempotency_key": "wrong-key",
            "error_code": "",
        }
    ]
    result = reconcile_private_ws_offline_fixture(
        current_head=HEAD,
        source_head=HEAD,
        generated_at_utc=NOW,
        events=events,
        expected_order_ids=["order-1"],
        expected_idempotency_keys={"order-1": "expected-key"},
        source_receipt={
            "fixture_version": "fixture-v1",
            "events_sha256": stable_payload_hash(rows),
        },
    )

    assert result["offline_fixture_validated"] is False
    assert "btc_private_ws:idempotency_key_mismatch" in result["blockers"]
    assert result["private_ws_observed"] is False
    assert (
        result["schema_version"]
        == "btc_private_ws_offline_reconciliation_v2"
    )


def test_full_offline_closure_drill_is_quality_checked_but_not_real_evidence() -> None:
    result = build_offline_engineering_closure(
        current_head=HEAD,
        generated_at_utc=NOW,
        websocket_loader=_fake_websocket_module,
    )

    assert result["status"] == "complete_research_only"
    assert result["readiness_class"] == "quality_checked"
    assert result["engineering_contracts_valid"] is True
    assert all(
        value != "blocked"
        for value in result["engineering_items"].values()
    )
    assert result["l2_recovery_drill"]["engineering_blockers"] == []
    assert (
        result["private_ws_reconciliation"]["offline_fixture_validated"]
        is True
    )
    assert all(
        result["private_ws_reconciliation"]["lifecycle_coverage"][key]
        is True
        for key in (
            "partial",
            "fill",
            "reject",
            "cancel",
            "outage",
            "cancel_only",
            "idempotency",
        )
    )
    drill = result["non_flat_execution_drill"]
    assert drill["engineering_blockers"] == []
    assert drill["risk"]["approved"] is True
    assert drill["oms_lifecycle"]["status"] == "reconciled"
    assert drill["fills"]["fill_count"] == 2
    assert drill["audit_dag"]["status"] == "complete"
    assert drill["pnl"]["derived_from"] == [
        "fills",
        "positions",
        "cash_ledger",
    ]
    assert result["blockers"] == list(EXTERNAL_BLOCKERS)
    assert result["real_observation"] is False
    assert result["promotion_evidence_ready"] is False
    assert result["paper_ready"] is False
    assert result["live_ready"] is False
    assert all(value is False for value in result["safety"].values())
    assert result["public_ws_dependency"]["network_accessed"] is False
    assert (
        result["private_ws_reconciliation"]["schema_version"]
        == "btc_private_ws_offline_reconciliation_v2"
    )
