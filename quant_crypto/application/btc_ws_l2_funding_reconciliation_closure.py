"""Offline BTC WS/L2/funding/reconciliation engineering closure drill.

This service accepts no path, endpoint, credential, mutable ``latest`` state,
or order adapter.  It proves fixture-only boundaries and deliberately retains
all real-observation and promotion blockers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from quant_crypto.adapters.okx_public_ws import (
    OKXPublicWSContractError,
    OKXPublicWSL2Adapter,
    okx_l2_checksum,
    public_websocket_dependency_receipt,
)
from quant_crypto.backtest.funding_ledger import (
    FundingFill,
    FundingRateEvent,
    replay_perpetual_fill_position_cash_ledger,
)
from quant_crypto.monitoring.artifact_schema import (
    apply_btc_artifact_schema,
    stable_payload_hash,
)
from quant_crypto.monitoring.audit_dag import (
    BTC_AUDIT_NODE_ORDER,
    BTCAuditNodeType,
    artifact_ref_from_payload,
    build_btc_audit_dag,
)
from quant_crypto.oms.lifecycle import BTCPaperOMS
from quant_crypto.oms.private_ws_reconciliation import (
    BTCPrivateWSEventKind,
    BTCPrivateWSFixtureEvent,
    reconcile_private_ws_offline_fixture,
)
from quant_crypto.risk.liquidation import (
    BTCLiquidationPolicy,
    BTCPerpPositionState,
    BTCReferencePriceState,
    evaluate_btc_perp_liquidation_risk,
)
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    Signal,
    SignalDirection,
    TargetPosition,
    TimeInForce,
)
from quant_shared.core.time import ensure_utc


SCHEMA_VERSION = "btc_ws_l2_funding_reconciliation_closure_v1"
EXTERNAL_BLOCKERS = (
    "btc_ws_l2_funding_closure:real_private_ws_observation_missing",
    "btc_ws_l2_funding_closure:real_non_flat_fill_observation_missing",
    "btc_ws_l2_funding_closure:real_funding_cashflow_observation_missing",
    "btc_ws_l2_funding_closure:natural_observation_window_30_day_incomplete",
    "btc_ws_l2_funding_closure:manual_promotion_approval_missing",
)
SAFETY = {
    "network_accessed": False,
    "private_endpoint_accessed": False,
    "private_endpoint_allowed": False,
    "order_endpoint_accessed": False,
    "order_endpoint_allowed": False,
    "broker_access_allowed": False,
    "paper_queue_write_enabled": False,
    "paper_queue_write_allowed": False,
    "paper_allowed": False,
    "paper_ready": False,
    "live_allowed": False,
    "live_ready": False,
    "real_orders_enabled": False,
    "real_order_submitted": False,
    "withdraw_allowed": False,
    "secrets_read": False,
    "promotion_evidence_ready": False,
}


def build_offline_engineering_closure(
    *,
    current_head: str,
    generated_at_utc: datetime,
    websocket_loader: Callable[[], Any],
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc)
    dependency = public_websocket_dependency_receipt(websocket_loader)
    l2 = _run_l2_recovery_drill(generated)
    execution = _run_non_flat_execution_drill(
        current_head=current_head, generated=generated
    )
    private_ws = _run_private_ws_reconciliation(
        current_head=current_head, generated=generated
    )
    engineering_blockers = [
        *dependency["blockers"],
        *l2["engineering_blockers"],
        *execution["engineering_blockers"],
        *[
            item
            for item in private_ws["blockers"]
            if item
            != "btc_private_ws:real_current_head_private_ws_observation_missing"
        ],
    ]
    engineering_blockers = list(dict.fromkeys(engineering_blockers))
    blockers = [*engineering_blockers, *EXTERNAL_BLOCKERS]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "complete_research_only"
            if not engineering_blockers
            else "blocked_fail_closed"
        ),
        "source_head": current_head,
        "code_commit": current_head,
        "fixture_only": True,
        "readiness_class": (
            "quality_checked" if not engineering_blockers else "blocked"
        ),
        "engineering_contracts_valid": not engineering_blockers,
        "engineering_items": {
            "btc_okx_websocket_client_dependency_missing": (
                "resolved_installable_optional_extra_and_import_contract"
                if dependency["import_safe"]
                else "blocked"
            ),
            "l2_reconnect_gapfill_sequence_checksum_timestamp": (
                "resolved_fixture_contract"
                if not l2["engineering_blockers"]
                else "blocked"
            ),
            "funding_cashflow_fill_position_cash_ledger": (
                "resolved_fixture_contract"
                if not execution["engineering_blockers"]
                else "blocked"
            ),
            "private_ws_partial_reject_cancel_outage_idempotency": (
                "resolved_fixture_contract"
                if private_ws["offline_fixture_validated"]
                else "blocked"
            ),
            "non_flat_risk_oms_fill_ledger_audit_dag": (
                "resolved_fixture_contract"
                if not execution["engineering_blockers"]
                else "blocked"
            ),
        },
        "public_ws_dependency": dependency,
        "l2_recovery_drill": l2,
        "private_ws_reconciliation": private_ws,
        "non_flat_execution_drill": execution,
        "real_observation": False,
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
        "safety": dict(SAFETY),
        "blockers": blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision=(
            "quality_checked_fixture_engineering_closed_real_evidence_blocked"
            if not engineering_blockers
            else "blocked_fail_closed_engineering_contract_invalid"
        ),
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=[
            "fixture drill is not a real private WS, funding, fill, paper, or live observation"
        ],
        input_hashes={
            "l2": stable_payload_hash(l2),
            "private_ws": str(private_ws["artifact_hash"]),
            "execution": stable_payload_hash(execution),
        },
    )


def _run_l2_recovery_drill(generated: datetime) -> dict[str, Any]:
    adapter = OKXPublicWSL2Adapter(
        instrument_id="BTC-USDT-SWAP",
        checksum_required=True,
        max_timestamp_gap_ms=1_000,
    )
    adapter.on_connected()
    bids = {"100000": "1"}
    asks = {"100010": "1"}
    snapshot = _l2_payload(
        action="snapshot",
        sequence=10,
        previous_sequence=-1,
        timestamp_ms=_epoch_ms(generated),
        bids=list(bids.items()),
        asks=list(asks.items()),
        checksum=okx_l2_checksum(bids, asks),
    )
    events = adapter.ingest(
        snapshot, received_time_utc=generated
    )
    bids["100000"] = "1.2"
    asks["100010"] = "0.8"
    update = _l2_payload(
        action="update",
        sequence=11,
        previous_sequence=10,
        timestamp_ms=_epoch_ms(generated) + 100,
        bids=[("100000", "1.2")],
        asks=[("100010", "0.8")],
        checksum=okx_l2_checksum(bids, asks),
    )
    events.extend(
        adapter.ingest(
            update, received_time_utc=generated + timedelta(milliseconds=100)
        )
    )
    adapter.on_disconnect(
        reason="fixture_public_ws_disconnect",
        occurred_at_utc=generated + timedelta(milliseconds=150),
    )
    adapter.on_connected()
    recovery_bids = {"100001": "1.1"}
    recovery_asks = {"100011": "0.9"}
    recovery = _l2_payload(
        action="snapshot",
        sequence=20,
        previous_sequence=-1,
        timestamp_ms=_epoch_ms(generated) + 200,
        bids=list(recovery_bids.items()),
        asks=list(recovery_asks.items()),
        checksum=okx_l2_checksum(recovery_bids, recovery_asks),
    )
    events.extend(
        adapter.ingest(
            recovery,
            received_time_utc=generated + timedelta(milliseconds=200),
            recovery=True,
        )
    )
    failure_injections = {
        "sequence_gap": _failure_injection(
            generated=generated, case="sequence_gap"
        ),
        "checksum_mismatch": _failure_injection(
            generated=generated, case="checksum_mismatch"
        ),
        "timestamp_gap": _failure_injection(
            generated=generated, case="timestamp_gap"
        ),
    }
    failures_valid = all(
        row["cancel_only"] is True and row["new_risk_allowed"] is False
        for row in failure_injections.values()
    )
    receipt = adapter.recovery_receipt()
    engineering_blockers: list[str] = []
    if not receipt["sequence_contiguous"]:
        engineering_blockers.append("btc_okx_l2_sequence_continuity_unverified")
    if not receipt["timestamp_contiguous"]:
        engineering_blockers.append("btc_okx_l2_timestamp_continuity_unverified")
    if not receipt["gaps"] or receipt["gaps"][-1]["recovered"] is not True:
        engineering_blockers.append("btc_okx_l2_gapfill_unverified")
    if not failures_valid:
        engineering_blockers.append("btc_okx_l2_failure_injection_not_fail_closed")
    return {
        "fixture_only": True,
        "market_event_only": True,
        "events": [event.to_dict() for event in events],
        "recovery": receipt,
        "failure_injections": failure_injections,
        "engineering_blockers": engineering_blockers,
        "network_accessed": False,
    }


def _failure_injection(
    *, generated: datetime, case: str
) -> dict[str, Any]:
    adapter = OKXPublicWSL2Adapter(
        instrument_id="BTC-USDT-SWAP",
        checksum_required=True,
        max_timestamp_gap_ms=1_000,
    )
    adapter.on_connected()
    bids = {"100000": "1"}
    asks = {"100010": "1"}
    adapter.ingest(
        _l2_payload(
            action="snapshot",
            sequence=1,
            previous_sequence=-1,
            timestamp_ms=_epoch_ms(generated),
            bids=list(bids.items()),
            asks=list(asks.items()),
            checksum=okx_l2_checksum(bids, asks),
        ),
        received_time_utc=generated,
    )
    sequence = 2
    previous = 1
    timestamp_ms = _epoch_ms(generated) + 100
    checksum = okx_l2_checksum(bids, asks)
    if case == "sequence_gap":
        previous = 0
    elif case == "checksum_mismatch":
        checksum += 1
    elif case == "timestamp_gap":
        timestamp_ms += 5_000
    error = ""
    try:
        adapter.ingest(
            _l2_payload(
                action="update",
                sequence=sequence,
                previous_sequence=previous,
                timestamp_ms=timestamp_ms,
                bids=[],
                asks=[],
                checksum=checksum,
            ),
            received_time_utc=generated + timedelta(seconds=1),
        )
    except OKXPublicWSContractError as exc:
        error = str(exc)
    return {
        "case": case,
        "error": error,
        "state": adapter.state.value,
        "cancel_only": adapter.cancel_only,
        "new_risk_allowed": False,
    }


def _run_non_flat_execution_drill(
    *, current_head: str, generated: datetime
) -> dict[str, Any]:
    signal = Signal(
        timestamp_utc=generated,
        strategy_id="btc_fixture_non_flat",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        strength=0.5,
        horizon="fixture_only",
        reason="offline_non_flat_contract_drill",
        signal_id="sig_fixture_non_flat",
    )
    forecast = {
        "forecast_id": "forecast_fixture_non_flat",
        "signal_id": signal.signal_id,
        "expected_return": 0.001,
        "horizon": "fixture_only",
    }
    target = TargetPosition(
        timestamp_utc=generated,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        target_weight=0.02,
        target_quantity=0.02,
        signal_id=signal.signal_id,
        target_position_id="target_fixture_non_flat",
        metadata={"forecast_id": forecast["forecast_id"]},
    )
    intent = OrderIntent(
        timestamp_utc=generated,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        side=OrderSide.BUY,
        quantity=0.02,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        run_id="btc_fixture_non_flat_run",
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        client_order_id="coid_fixture_non_flat",
        order_intent_id="intent_fixture_non_flat",
        metadata={
            "fixture_only": True,
            "adapter_submit_allowed": False,
            "idempotency_key": "idem_fixture_non_flat",
        },
    )
    perp_risk = evaluate_btc_perp_liquidation_risk(
        reference_prices=BTCReferencePriceState(
            observed_at_utc=generated,
            signal_price=100_000,
            execution_price=100_000,
            mark_price=100_500,
            index_price=100_450,
            current_mark_price=100_500,
            primary_mid=100_005,
            secondary_reference_mid=100_004,
            spread_bps=1.0,
            cross_venue_deviation_bps=0.1,
            data_age_ms=10,
            order_book_depth_usd=1_000_000,
            source="offline_fixture",
        ),
        position=BTCPerpPositionState(
            current_quantity=0,
            proposed_quantity=0.02,
            account_equity=100_000,
            side="long",
        ),
        policy=BTCLiquidationPolicy(
            max_leverage=1.0,
            maintenance_margin_rate=0.005,
            min_liquidation_buffer_bps=1_000,
            max_reference_price_age_ms=1_000,
            max_cross_venue_deviation_bps=50,
            max_spread_bps=20,
            min_order_book_depth_usd=100_000,
        ),
    )
    risk = RiskDecision(
        approved=perp_risk.approved,
        reason="offline_fixture_liquidation_risk_checked",
        order_intent_id=intent.order_intent_id,
        checked_at=generated,
        risk_check_id="risk_fixture_non_flat",
        adjusted_quantity=0.02,
        risk_version="btc_perp_liquidation_risk_v1",
        rule_name="mark_index_liquidation_buffer",
        metadata=perp_risk.to_metadata(),
    )
    oms = BTCPaperOMS()
    order = oms.create_order(intent)
    order.mark_risk_checked(
        approved=risk.approved, reason="offline_fixture_risk_checked"
    )
    order.mark_submitted(
        broker_order_id="fixture-no-endpoint",
        reason="offline_fixture_no_endpoint_submission",
    )
    order.mark_accepted(
        broker_order_id="fixture-no-endpoint",
        reason="offline_fixture_ack",
    )
    order.apply_fill(
        fill_quantity=0.01,
        timestamp_utc=generated + timedelta(milliseconds=10),
        fill_id="fill_fixture_1",
        price=100_000,
    )
    order.apply_fill(
        fill_quantity=0.01,
        timestamp_utc=generated + timedelta(milliseconds=20),
        fill_id="fill_fixture_2",
        price=100_050,
    )
    order.reconcile(
        reason="offline_fixture_reconciled",
        metadata={"position_reconciled": True, "cash_reconciled": True},
    )
    fills = [
        FundingFill(
            filled_at=generated + timedelta(milliseconds=10),
            side="buy",
            quantity=0.01,
            price=100_000,
            fill_id="fill_fixture_1",
            fee=0.1,
        ),
        FundingFill(
            filled_at=generated + timedelta(milliseconds=20),
            side="buy",
            quantity=0.01,
            price=100_050,
            fill_id="fill_fixture_2",
            fee=0.1,
        ),
    ]
    funding = [
        FundingRateEvent(
            funding_time=generated + timedelta(hours=8),
            funding_rate=0.0001,
            mark_price=100_500,
            index_price=100_450,
            source_record_id="funding_fixture_1",
            instrument_id="BTC-USDT-SWAP",
            settlement_asset="USDT",
        )
    ]
    pnl = replay_perpetual_fill_position_cash_ledger(
        fills=fills,
        funding_rates=funding,
        valuation_mark_price=100_500,
    )
    ledger_rows = [
        {
            "event_time": row.event_time.isoformat(),
            "event_type": row.event_type,
            "amount": row.amount,
            "asset": row.asset,
            "position_qty": row.position_qty,
            "reference_price": row.reference_price,
            "source_id": row.source_id,
        }
        for row in pnl.ledger_entries
    ]
    node_payloads: dict[BTCAuditNodeType, Mapping[str, Any]] = {
        BTCAuditNodeType.DATA_SNAPSHOT: {
            "fixture": "immutable_injected_l2_snapshot"
        },
        BTCAuditNodeType.FEATURE: {"feature": "fixture_mid_depth"},
        BTCAuditNodeType.SIGNAL: {
            "signal_id": signal.signal_id,
            "direction": signal.direction.value,
        },
        BTCAuditNodeType.FORECAST: forecast,
        BTCAuditNodeType.TARGET: {
            "target_id": target.target_position_id,
            "target_quantity": target.target_quantity,
        },
        BTCAuditNodeType.RISK: {
            "risk_decision_id": risk.risk_check_id,
            "approved": risk.approved,
            "liquidation_buffer_bps": perp_risk.liquidation_buffer_bps,
            "mark_price": 100_500,
            "index_price": 100_450,
        },
        BTCAuditNodeType.ORDER: order.to_dict(),
        BTCAuditNodeType.FILL: {
            "fill_ids": [row.fill_id for row in fills],
            "fill_count": len(fills),
        },
        BTCAuditNodeType.LEDGER: {"entries": ledger_rows},
        BTCAuditNodeType.PNL: {
            "price_pnl": pnl.price_pnl,
            "funding_pnl": pnl.funding_pnl,
            "fee_pnl": pnl.fee_pnl,
            "total_pnl": pnl.total_pnl,
            "derived_from": ["fills", "positions", "cash_ledger"],
        },
        BTCAuditNodeType.REPORT: {
            "fixture_only": True,
            "real_observation": False,
        },
    }
    artifacts = {
        node_type: artifact_ref_from_payload(
            path=f"fixture://btc-non-flat/{node_type.value}.json",
            payload=node_payloads[node_type],
            code_version=current_head,
        )
        for node_type in BTC_AUDIT_NODE_ORDER
    }
    audit = build_btc_audit_dag(
        run_id="btc_fixture_non_flat_run",
        strategy_id=signal.strategy_id,
        data_version="btc_fixture_l2_v1",
        decision_time_utc=generated,
        artifacts=artifacts,
        log_context={
            "run_id": "btc_fixture_non_flat_run",
            "strategy_id": signal.strategy_id,
            "data_version": "btc_fixture_l2_v1",
            "decision_time_utc": generated.isoformat(),
            "signal_id": signal.signal_id,
            "forecast_id": forecast["forecast_id"],
            "target_id": target.target_position_id,
            "risk_decision_id": risk.risk_check_id,
            "order_id": order.order_id,
            "fill_id": fills[-1].fill_id,
            "error_code": "",
        },
    ).to_dict()
    engineering_blockers: list[str] = []
    if not risk.approved:
        engineering_blockers.extend(perp_risk.blockers)
    if order.status.value != "reconciled" or order.filled_quantity <= 0:
        engineering_blockers.append("btc_non_flat_fixture_oms_not_reconciled")
    if not any(row["event_type"] == "funding_cashflow" for row in ledger_rows):
        engineering_blockers.append("btc_non_flat_fixture_funding_ledger_missing")
    if audit["status"] != "complete":
        engineering_blockers.extend(audit["blockers"])
    return {
        "fixture_only": True,
        "real_fill_observed": False,
        "signal": node_payloads[BTCAuditNodeType.SIGNAL],
        "forecast": forecast,
        "target": node_payloads[BTCAuditNodeType.TARGET],
        "risk": node_payloads[BTCAuditNodeType.RISK],
        "oms_lifecycle": order.to_dict(),
        "fills": node_payloads[BTCAuditNodeType.FILL],
        "ledger": {
            "entries": ledger_rows,
            "position_qty": pnl.position_qty,
            "cash_balance": pnl.cash_balance,
            "position_value": pnl.position_value,
        },
        "pnl": node_payloads[BTCAuditNodeType.PNL],
        "audit_dag": audit,
        "engineering_blockers": list(dict.fromkeys(engineering_blockers)),
        "safety": dict(SAFETY),
    }


def _run_private_ws_reconciliation(
    *, current_head: str, generated: datetime
) -> dict[str, Any]:
    events = [
        BTCPrivateWSFixtureEvent(
            1,
            "private-1",
            BTCPrivateWSEventKind.ORDER_ACK,
            "order-fill",
            idempotency_key="idem-fill",
            order_status="accepted",
        ),
        BTCPrivateWSFixtureEvent(
            2,
            "private-2",
            BTCPrivateWSEventKind.FILL,
            "order-fill",
            fill_id="private-fill-1",
            filled_quantity=0.01,
            fill_price=100_000,
            remaining_quantity=0.01,
            order_status="partially_filled",
            idempotency_key="idem-fill",
        ),
        BTCPrivateWSFixtureEvent(
            3,
            "private-3",
            BTCPrivateWSEventKind.FILL,
            "order-fill",
            fill_id="private-fill-2",
            filled_quantity=0.01,
            fill_price=100_050,
            remaining_quantity=0,
            order_status="filled",
            idempotency_key="idem-fill",
        ),
        BTCPrivateWSFixtureEvent(
            4,
            "private-4",
            BTCPrivateWSEventKind.ORDER_ACK,
            "order-reject",
            idempotency_key="idem-reject",
        ),
        BTCPrivateWSFixtureEvent(
            5,
            "private-5",
            BTCPrivateWSEventKind.REJECT,
            "order-reject",
            order_status="rejected",
            idempotency_key="idem-reject",
            error_code="FIXTURE_MIN_NOTIONAL",
        ),
        BTCPrivateWSFixtureEvent(
            6,
            "private-6",
            BTCPrivateWSEventKind.ORDER_ACK,
            "order-cancel",
            idempotency_key="idem-cancel",
        ),
        BTCPrivateWSFixtureEvent(
            7,
            "private-7",
            BTCPrivateWSEventKind.CANCEL_ACK,
            "order-cancel",
            order_status="cancelled",
            idempotency_key="idem-cancel",
        ),
        BTCPrivateWSFixtureEvent(
            8,
            "private-8",
            BTCPrivateWSEventKind.OUTAGE,
            "",
            error_code="FIXTURE_PRIVATE_WS_OUTAGE",
        ),
    ]
    event_rows = [_private_event_row(row) for row in events]
    return reconcile_private_ws_offline_fixture(
        current_head=current_head,
        source_head=current_head,
        generated_at_utc=generated,
        events=events,
        expected_order_ids=["order-fill", "order-reject", "order-cancel"],
        expected_idempotency_keys={
            "order-fill": "idem-fill",
            "order-reject": "idem-reject",
            "order-cancel": "idem-cancel",
        },
        required_scenarios=(
            "partial",
            "fill",
            "reject",
            "cancel",
            "outage",
            "cancel_only",
            "idempotency",
        ),
        source_receipt={
            "fixture_version": "btc-private-ws-closure-v1",
            "events_sha256": stable_payload_hash(event_rows),
        },
    )


def _private_event_row(row: BTCPrivateWSFixtureEvent) -> dict[str, Any]:
    payload = {
        "sequence": row.sequence,
        "event_id": row.event_id,
        "kind": row.kind.value,
        "client_order_id": row.client_order_id,
        "fill_id": row.fill_id,
        "filled_quantity": float(row.filled_quantity),
        "fill_price": float(row.fill_price),
    }
    optional = {
        "remaining_quantity": float(row.remaining_quantity),
        "order_status": row.order_status,
        "idempotency_key": row.idempotency_key,
        "error_code": row.error_code,
    }
    if any(value not in ("", 0.0) for value in optional.values()):
        payload.update(optional)
    return payload


def _l2_payload(
    *,
    action: str,
    sequence: int,
    previous_sequence: int,
    timestamp_ms: int,
    bids: Sequence[tuple[str, str]],
    asks: Sequence[tuple[str, str]],
    checksum: int,
) -> dict[str, Any]:
    return {
        "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
        "action": action,
        "data": [
            {
                "bids": [[price, size, "0", "1"] for price, size in bids],
                "asks": [[price, size, "0", "1"] for price, size in asks],
                "ts": str(timestamp_ms),
                "seqId": sequence,
                "prevSeqId": previous_sequence,
                "checksum": checksum,
            }
        ],
    }


def _epoch_ms(value: datetime) -> int:
    return int(ensure_utc(value).timestamp() * 1_000)


__all__ = [
    "EXTERNAL_BLOCKERS",
    "SAFETY",
    "SCHEMA_VERSION",
    "build_offline_engineering_closure",
]
