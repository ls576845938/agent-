from __future__ import annotations

import json
import socket
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import quant_crypto.oms.okx_demo_paper_runtime as demo_runtime_module

from quant_crypto.application.btc_lean_microlive_canary import (
    build_micro_live_authorization_plan,
)
from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.oms.okx_mode_transport import (
    OKXCredentialReference,
    OKXModeIsolatedRequestBuilder,
    OKXRecordingTransport,
    OKXTransportMode,
)
from quant_crypto.oms.okx_demo_paper_runtime import (
    BTCBoundedEphemeralMarketDataRing,
    BTCDemoRuntimeDataBudget,
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
)
from quant_crypto.oms.private_ws_reconciliation import (
    BTCPrivateWSEventKind,
    BTCPrivateWSFixtureEvent,
    BTCPrivateWSRuntimeReconciler,
    BTCPrivateWSStartupSnapshot,
)
from quant_crypto.oms.supervised_micro_live import (
    FundingCashLedgerEvidence,
    MicroLiveApprovalProof,
    MicroLiveRuntimeLimits,
    SupervisedMicroLiveAuthorization,
    evaluate_supervised_micro_live_candidate,
)
from quant_crypto.oms.venue_rules import BTCVenueRules
from quant_crypto.risk.liquidation import (
    BTCLiquidationPolicy,
    BTCPerpPositionState,
    BTCReferencePriceState,
)
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    TimeInForce,
)


NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
HEAD = "57b523fbd0b2c094468d1104cfd3fa5ec03de3b1"


class SnapshotTransport:
    def __init__(self, snapshot: BTCPrivateWSStartupSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def fetch_startup_snapshot(self) -> BTCPrivateWSStartupSnapshot:
        self.calls += 1
        return self.snapshot


def _snapshot(**overrides: object) -> BTCPrivateWSStartupSnapshot:
    values = {
        "open_orders": (),
        "fills": (),
        "positions": (),
        "balance": {"equity_usdt": "10"},
        "funding_bills": ({"bill_id": "bill-1"},),
        "last_sequence": 0,
        "private_ws_status": "connected",
        "rest_status": "ok",
        "captured_at_utc": NOW,
    }
    values.update(overrides)
    return BTCPrivateWSStartupSnapshot(**values)


def _authorization_payload() -> dict[str, object]:
    return {
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": 1,
        "max_notional_usdt": 10,
        "max_positions": 1,
        "max_active_orders": 1,
        "max_daily_loss_usdt": 1,
        "max_daily_new_orders": 2,
        "auto_start": False,
        "auto_scale": False,
        "single_strategy_id": "btc-one-strategy",
        "manual_supervision_required": True,
        "runtime_data_budget": {
            "market_ring_window_minutes": 15,
            "market_ring_hard_cap_bytes": 256 * 1024 * 1024,
            "l2_disk_persistence_enabled": False,
            "sampled_event_types": ["signal", "order", "error"],
            "sampled_event_rolling_hard_cap_bytes": 1024**3,
            "runtime_warning_bytes": 4 * 1024**3,
            "runtime_stop_raw_market_writes_bytes": 5 * 1024**3,
        },
        "proof": {
            "account_hash": "a" * 64,
            "venue": "okx",
            "reviewer": "reviewer-1",
            "reviewed_at_utc": NOW.isoformat(),
            "approval_ticket": "APPROVAL-1",
            "permission_conclusion": "read_and_trade_no_withdraw_ip_allowlisted",
            "external_proof_id": "proof-1",
            "credential_namespace": "quant-system.okx-live.trade",
            "withdraw_permission": False,
        },
    }


def _authorization() -> SupervisedMicroLiveAuthorization:
    raw = _authorization_payload()
    proof = raw["proof"]
    assert isinstance(proof, dict)
    return SupervisedMicroLiveAuthorization(
        instrument_id=str(raw["instrument_id"]),
        margin_mode=str(raw["margin_mode"]),
        leverage=float(raw["leverage"]),
        max_notional_usdt=float(raw["max_notional_usdt"]),
        max_positions=int(raw["max_positions"]),
        max_active_orders=int(raw["max_active_orders"]),
        max_daily_loss_usdt=float(raw["max_daily_loss_usdt"]),
        max_daily_new_orders=int(raw["max_daily_new_orders"]),
        auto_start=bool(raw["auto_start"]),
        auto_scale=bool(raw["auto_scale"]),
        single_strategy_id=str(raw["single_strategy_id"]),
        manual_supervision_required=bool(raw["manual_supervision_required"]),
        proof=MicroLiveApprovalProof(
            account_hash=str(proof["account_hash"]),
            venue=str(proof["venue"]),
            reviewer=str(proof["reviewer"]),
            reviewed_at_utc=NOW,
            approval_ticket=str(proof["approval_ticket"]),
            permission_conclusion=str(proof["permission_conclusion"]),
            external_proof_id=str(proof["external_proof_id"]),
            credential_namespace=str(proof["credential_namespace"]),
            withdraw_permission=False,
        ),
    )


def _reconciled_private_ws():
    transport = SnapshotTransport(_snapshot())
    reconciler = BTCPrivateWSRuntimeReconciler(
        transport=transport, owned_client_order_ids=["coid-1"]
    )
    receipt = reconciler.startup()
    assert receipt.opening_allowed is True
    return reconciler


def test_demo_and_live_request_construction_are_strongly_isolated() -> None:
    demo_transport = OKXRecordingTransport(mode=OKXTransportMode.DEMO)
    demo = OKXModeIsolatedRequestBuilder(
        credential_reference=OKXCredentialReference(
            mode=OKXTransportMode.DEMO,
            service_namespace="quant-system.okx-demo.trade",
            account_hash="1" * 64,
        ),
        transport=demo_transport,
    )
    live_transport = OKXRecordingTransport(mode=OKXTransportMode.LIVE)
    live = OKXModeIsolatedRequestBuilder(
        credential_reference=OKXCredentialReference(
            mode=OKXTransportMode.LIVE,
            service_namespace="quant-system.okx-live.trade",
            account_hash="2" * 64,
        ),
        transport=live_transport,
    )

    demo_request = demo.record_private_request(
        method="POST", path="/api/v5/trade/order", body={"instId": "BTC-USDT-SWAP"}
    )
    live_request = live.record_private_request(
        method="POST", path="/api/v5/trade/order", body={"instId": "BTC-USDT-SWAP"}
    )

    assert demo_request.headers["x-simulated-trading"] == "1"
    assert "x-simulated-trading" not in {
        key.lower(): value for key, value in live_request.headers.items()
    }
    assert demo_transport.network_accessed is False
    assert live_transport.network_accessed is False


def test_private_ws_startup_reconnect_duplicate_partial_reject_and_cancel() -> None:
    transport = SnapshotTransport(_snapshot())
    reconciler = BTCPrivateWSRuntimeReconciler(
        transport=transport,
        owned_client_order_ids=["fill", "reject", "cancel"],
    )
    assert reconciler.startup().opening_allowed is True
    events = [
        BTCPrivateWSFixtureEvent(1, "e1", BTCPrivateWSEventKind.ORDER_ACK, "fill"),
        BTCPrivateWSFixtureEvent(
            2,
            "e2",
            BTCPrivateWSEventKind.FILL,
            "fill",
            fill_id="f1",
            filled_quantity=0.00005,
            fill_price=60_000,
            remaining_quantity=0.00005,
            order_status="partially_filled",
        ),
        BTCPrivateWSFixtureEvent(3, "e3", BTCPrivateWSEventKind.REJECT, "reject"),
        BTCPrivateWSFixtureEvent(4, "e4", BTCPrivateWSEventKind.CANCEL_ACK, "cancel"),
    ]
    for event in events:
        receipt = reconciler.consume(event)
    duplicate = reconciler.consume(events[-1])

    assert receipt.opening_allowed is True
    assert receipt.lifecycle_coverage["partial"] is True
    assert receipt.lifecycle_coverage["reject"] is True
    assert receipt.lifecycle_coverage["cancel"] is True
    assert duplicate.duplicate_event_count == 1
    reconciler.on_disconnect()
    assert reconciler.receipt().cancel_only is True
    recovered = reconciler.on_reconnect()
    assert recovered.opening_allowed is True
    assert recovered.reconnect_reconciled is True
    assert transport.calls == 2


def test_private_ws_gap_out_of_order_and_unknown_state_enter_cancel_only() -> None:
    for event, blocker in (
        (
            BTCPrivateWSFixtureEvent(
                2, "gap", BTCPrivateWSEventKind.ORDER_ACK, "owned"
            ),
            "btc_private_ws:sequence_gap",
        ),
        (
            BTCPrivateWSFixtureEvent(
                1, "unknown", BTCPrivateWSEventKind.ORDER_ACK, "other"
            ),
            "btc_private_ws:unknown_client_order_id",
        ),
    ):
        reconciler = BTCPrivateWSRuntimeReconciler(
            transport=SnapshotTransport(_snapshot()),
            owned_client_order_ids=["owned"],
        )
        reconciler.startup()
        receipt = reconciler.consume(event)
        assert receipt.cancel_only is True
        assert blocker in receipt.blockers

    reconciler = BTCPrivateWSRuntimeReconciler(
        transport=SnapshotTransport(_snapshot()),
        owned_client_order_ids=["owned"],
    )
    reconciler.startup()
    reconciler.consume(
        BTCPrivateWSFixtureEvent(
            1, "first", BTCPrivateWSEventKind.ORDER_ACK, "owned"
        )
    )
    receipt = reconciler.consume(
        BTCPrivateWSFixtureEvent(
            1, "unseen-old", BTCPrivateWSEventKind.ORDER_UPDATE, "owned"
        )
    )
    assert receipt.cancel_only is True
    assert "btc_private_ws:out_of_order_event" in receipt.blockers


def test_unknown_startup_order_or_missing_balance_blocks_opening() -> None:
    snapshot = _snapshot(
        open_orders=({"client_order_id": "not-owned"},),
        balance={},
    )
    reconciler = BTCPrivateWSRuntimeReconciler(
        transport=SnapshotTransport(snapshot),
        owned_client_order_ids=["owned"],
    )
    receipt = reconciler.startup()

    assert receipt.cancel_only is True
    assert "btc_private_ws:unknown_open_order" in receipt.blockers
    assert "btc_private_ws:balance_snapshot_missing" in receipt.blockers


def test_authorization_config_enforces_10u_caps_no_auto_start_and_no_secrets() -> None:
    report = build_micro_live_authorization_plan(_authorization_payload())
    schema = json.loads(
        Path("schemas/btc_lean_microlive_canary.schema.json").read_text(
            encoding="utf-8"
        )
    )

    jsonschema.validate(report, schema)
    assert report["status"] == "quality_checked_candidate"
    assert report["authorization"]["auto_start"] is False
    assert report["authorization"]["auto_scale"] is False
    assert report["authorization"]["proof"]["withdraw_permission"] is False
    assert report["runtime_data_budget"]["market_ring_window_minutes"] == 15
    assert report["runtime_data_budget"]["market_ring_hard_cap_bytes"] == 256 * 1024 * 1024
    assert report["runtime_data_budget"]["l2_disk_persistence_enabled"] is False
    assert report["runtime_data_budget"]["runtime_warning_bytes"] == 4 * 1024**3
    assert report["runtime_data_budget"]["runtime_stop_raw_market_writes_bytes"] == 5 * 1024**3
    assert report["runtime_data_budget"]["quota_can_delete_protected_state"] is False
    assert all(value is False for value in report["safety"].values())

    template = json.loads(
        Path(
            "configs/btc/micro_live_canary/supervised_10usdt.template.json"
        ).read_text(encoding="utf-8")
    )
    template_report = build_micro_live_authorization_plan(template)
    jsonschema.validate(template_report, schema)
    assert template_report["status"] == "blocked_fail_closed"
    assert template_report["decision"] == "authorization_envelope_blocked_fail_closed"
    assert "btc_lean_microlive:reviewed_at_utc_missing" in template_report["blockers"]
    assert "btc_lean_microlive:single_strategy_id_missing" in template_report["blockers"]

    bad = _authorization_payload()
    bad["api_secret"] = "must-not-appear"
    rejected = build_micro_live_authorization_plan(bad)
    assert rejected["status"] == "blocked_fail_closed"
    assert "must-not-appear" not in json.dumps(rejected)

    auto = _authorization_payload()
    auto["auto_start"] = True
    auto["max_notional_usdt"] = 11
    blocked = build_micro_live_authorization_plan(auto)
    assert blocked["status"] == "blocked_fail_closed"
    assert "btc_lean_microlive:auto_start_forbidden" in blocked["blockers"]
    assert any("max_notional_usdt" in value for value in blocked["blockers"])


def test_funding_ledger_missing_or_mismatched_is_fail_closed() -> None:
    missing = FundingCashLedgerEvidence(
        bill_ids=(),
        funding_cashflow_source_ids=(),
        funding_bill_total_usdt=0,
        funding_cash_ledger_total_usdt=0,
        cash_ledger_reconciled=False,
        pnl_derived_from=("fills", "positions", "cash_ledger"),
    )
    blockers = missing.blockers()

    assert "btc_lean_microlive:funding_bills_missing" in blockers
    assert "btc_lean_microlive:funding_cash_ledger_entries_missing" in blockers
    assert "btc_lean_microlive:cash_ledger_not_reconciled" in blockers
    assert "btc_lean_microlive:pnl_provenance_invalid" in blockers


def test_opening_gate_binds_risk_funding_mark_index_liquidation_and_venue_rules() -> None:
    reconciler = _reconciled_private_ws()
    intent = OrderIntent(
        timestamp_utc=NOW,
        strategy_id="btc-one-strategy",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=0.0001,
        order_type=OrderType.LIMIT,
        limit_price=60_000,
        time_in_force=TimeInForce.GTC,
        run_id="run-1",
        signal_id="sig-1",
        target_position_id="target-1",
        client_order_id="coid-1",
    )
    risk = RiskDecision(
        approved=True,
        reason="within_micro_live_limits",
        order_intent_id=intent.order_intent_id,
    )
    payload = evaluate_supervised_micro_live_candidate(
        current_head=HEAD,
        generated_at_utc=NOW,
        authorization=_authorization(),
        order_intent=intent,
        risk_decision=risk,
        private_ws=reconciler.receipt(),
        funding_ledger=FundingCashLedgerEvidence(
            bill_ids=("bill-1",),
            funding_cashflow_source_ids=("bill-1",),
            funding_bill_total_usdt=-0.001,
            funding_cash_ledger_total_usdt=-0.001,
            cash_ledger_reconciled=True,
            pnl_derived_from=(
                "fills",
                "positions",
                "cash_ledger",
                "funding_ledger",
            ),
        ),
        runtime_limits=MicroLiveRuntimeLimits(
            position_count=0,
            active_order_count=0,
            daily_loss_usdt=0,
            daily_new_order_count=0,
            kill_switch_engaged=False,
            cancel_only=False,
            connection_state="known_healthy",
        ),
        reference_prices=BTCReferencePriceState(
            observed_at_utc=NOW,
            signal_price=60_000,
            execution_price=60_000,
            mark_price=60_010,
            index_price=60_005,
            current_mark_price=60_010,
            spread_bps=1,
            cross_venue_deviation_bps=1,
            data_age_ms=100,
            order_book_depth_usd=100_000,
        ),
        position=BTCPerpPositionState(
            current_quantity=0,
            proposed_quantity=0.0001,
            account_equity=10,
        ),
        liquidation_policy=BTCLiquidationPolicy(
            max_leverage=1,
            maintenance_margin_rate=0.005,
            min_liquidation_buffer_bps=1_000,
            max_reference_price_age_ms=2_000,
            max_cross_venue_deviation_bps=20,
            max_spread_bps=20,
            min_order_book_depth_usd=100,
        ),
        venue_rules=BTCVenueRules(
            venue="okx",
            venue_symbol="BTC-USDT-SWAP",
            tick_size=0.1,
            step_size=0.0001,
            min_quantity=0.0001,
            min_notional=1,
            price_precision=1,
            quantity_precision=4,
            maker_fee_bps=2,
            taker_fee_bps=5,
            funding_interval_hours=8,
        ),
    )

    assert payload["opening_gate"]["engineering_contracts_valid"] is True
    assert payload["opening_gate"]["candidate_request_construction_ready"] is True
    assert payload["opening_gate"]["live_order_allowed"] is False
    assert payload["funding_ledger"]["cash_ledger_reconciled"] is True
    assert payload["liquidation_risk"]["approved"] is True
    assert payload["venue_validation"]["approved"] is True
    assert payload["safety"] == {
        key: False for key in payload["safety"]
    }
    assert validate_btc_artifact_schema(payload) == []


def test_zero_real_network_contract(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("real network forbidden")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    transport = OKXRecordingTransport(mode=OKXTransportMode.LIVE)
    builder = OKXModeIsolatedRequestBuilder(
        credential_reference=OKXCredentialReference(
            mode=OKXTransportMode.LIVE,
            service_namespace="quant-system.okx-live.trade",
            account_hash="f" * 64,
        ),
        transport=transport,
    )
    builder.record_private_request(
        method="GET", path="/api/v5/account/positions"
    )

    assert len(transport.requests) == 1
    assert transport.network_accessed is False


def test_demo_runtime_budget_uses_ephemeral_ring_and_stops_raw_writes_at_5gib() -> None:
    budget = BTCDemoRuntimeDataBudget(
        market_ring_window_minutes=10,
        market_ring_hard_cap_bytes=256 * 1024 * 1024,
    )
    ring = BTCBoundedEphemeralMarketDataRing(budget)
    ring.append({"ticker": {"bid": "60000"}}, observed_at_utc=NOW)

    assert ring.summary()["persisted"] is False
    assert ring.summary()["l2_disk_persistence_enabled"] is False
    assert budget.evaluate(runtime_data_bytes=4 * 1024**3)["warning"] is True
    stopped = budget.evaluate(runtime_data_bytes=5 * 1024**3)
    assert stopped["raw_market_writes_allowed"] is False
    assert stopped["cancel_only_required"] is True
    assert stopped["protected_state_retention_required"] is True
    assert {
        "order",
        "fill",
        "position",
        "cash",
        "funding",
        "ledger",
        "audit",
        "error",
        "checkpoint",
    }.issubset(set(stopped["protected_state"]))


def test_demo_controller_5gib_quota_enters_cancel_only_without_deleting_ledgers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=tmp_path,
            data_db_path=tmp_path / "missing.sqlite",
            output_dir=tmp_path.parent / f"{tmp_path.name}-runtime",
        ),
        credential_loader=lambda service: (_ for _ in ()).throw(
            AssertionError("credentials must not be loaded")
        ),
        start_worker=False,
    )
    controller._state["audit"] = [{"ledger_checkpoint": "preserve-me"}]
    monkeypatch.setattr(
        demo_runtime_module, "_directory_size_bytes", lambda root: 5 * 1024**3
    )

    controller._apply_snapshot(
        {
            "captured_at_utc": NOW.isoformat(),
            "ticker": {"bid": "60000", "ask": "60001"},
            "book": {"bids": [["60000", "1"]], "asks": [["60001", "1"]]},
            "mark": {"mark_price": "60000"},
            "funding": {"funding_rate": "0.0001"},
            "orders": [{"client_order_id": "coid-1"}],
            "fills": [{"fill_id": "fill-1"}],
            "positions": [{"quantity": "0.0001"}],
            "balance": {"equity_usdt": "10"},
            "bills": [{"bill_id": "bill-1"}],
        }
    )
    status = controller.status()

    assert status["runtime"]["opening_allowed"] is False
    assert status["runtime"]["cancel_only"] is True
    assert "okx_demo_runtime_data_budget_stop_reached" in status["runtime"]["blockers"]
    assert status["runtime_data_budget"]["state"]["raw_market_writes_allowed"] is False
    assert status["market_data_ring"]["row_count"] == 0
    assert status["audit"] == [{"ledger_checkpoint": "preserve-me"}]
    assert status["exchange"]["orders"]
    assert status["exchange"]["fills"]
    assert status["exchange"]["positions"]
    assert status["exchange"]["balance"]
    assert status["exchange"]["bills"]
