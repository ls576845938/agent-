from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_crypto.oms.execution_quality import BTCExecutionFill
from quant_crypto.oms.lifecycle import BTCPaperOMS, BTCPaperOrderStatus
from quant_crypto.oms.session_reconciliation import build_btc_paper_oms_session_reconciliation
from quant_crypto.trading_contracts import OrderIntent, OrderSide, OrderType, TimeInForce


def build_btc_paper_runtime_replay_oms_session(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    session_id: str,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    oms = BTCPaperOMS()
    orders = []
    fills = []
    for row in replay_rows:
        if not row.get("theoretical_order_created"):
            continue
        intent = _order_intent_from_replay_row(row, session_id=session_id)
        order = oms.create_order(intent)
        _apply_replay_row_to_lifecycle(order, row)
        orders.append(order)
        if row.get("simulated_fill_created"):
            fills.append(_execution_fill_from_replay_row(row, order.client_order_id))
    ledger_hash = stable_payload_hash(
        {
            "session_id": session_id,
            "event_rows": list(event_rows),
            "order_client_ids": [order.client_order_id for order in orders],
            "fill_ids": [fill.fill_id for fill in fills],
        }
    )
    reconciliation = build_btc_paper_oms_session_reconciliation(
        session_id=session_id,
        orders=orders,
        fills=fills,
        ledger_hash=ledger_hash,
        generated_at_utc=generated_at_utc,
        opportunity_benchmark_price=_opportunity_benchmark_price(replay_rows),
    )
    orders_by_client_id = {order.client_order_id: order for order in orders}
    order_records = [_order_ledger_record(order, session_id=session_id) for order in orders]
    fill_records = [_fill_ledger_record(fill, session_id=session_id, order=orders_by_client_id.get(fill.client_order_id)) for fill in fills]
    return {
        "session_id": session_id,
        "ledger_hash": ledger_hash,
        "orders": orders,
        "fills": fills,
        "order_records": order_records,
        "fill_records": fill_records,
        "reconciliation_report": reconciliation,
        "unreconciled_count": sum(1 for order in orders if order.status != BTCPaperOrderStatus.RECONCILED),
    }


def _order_intent_from_replay_row(row: Mapping[str, Any], *, session_id: str) -> OrderIntent:
    decision_time = _timestamp_or_none(row.get("decision_time")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    side = OrderSide.SELL if str(row.get("side")) == "short" else OrderSide.BUY
    quantity = abs(_float(row.get("quantity_btc")))
    if quantity <= 0.0:
        quantity = abs(_float(row.get("requested_quantity_btc")))
    client_order_id = _client_order_id(row, session_id=session_id)
    return OrderIntent(
        timestamp_utc=decision_time,
        strategy_id=str(row.get("strategy_line") or "btc_replay"),
        symbol="BTCUSDT",
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        run_id=session_id,
        metadata={
            "arrival_price": _float(row.get("execution_price")) or _float(row.get("mark_price")),
            "benchmark_price": _float(row.get("index_price")) or _float(row.get("execution_price")),
            "venue": row.get("venue") or "OKX",
            "venue_symbol": row.get("venue_symbol") or row.get("instrument_id") or "BTC-USDT-SWAP",
            "instrument_id": row.get("instrument_id") or row.get("venue_symbol") or "BTC-USDT-SWAP",
            "instrument_type": row.get("instrument_type") or "SWAP",
            "account_id": row.get("account_id") or "observe_only_no_private_account",
            "account_mode": row.get("account_mode") or "unknown_or_unattested",
            "position_mode": row.get("position_mode") or "unknown_or_unattested",
            "margin_mode": row.get("margin_mode") or "unknown_or_unattested",
            "margin_asset": row.get("margin_asset") or "USDT",
            "exchange_metadata_version": row.get("exchange_metadata_version") or "",
            "order_type": row.get("order_type") or "market",
            "time_in_force": row.get("time_in_force") or "ioc",
            "reduce_only": bool(row.get("reduce_only")),
            "post_only": bool(row.get("post_only")),
            "cancel_only_mode": bool(row.get("cancel_only_mode")),
            "fee_side": row.get("fee_side") or "taker",
            "modeled_slippage_bps": _float(row.get("modeled_slippage_bps")),
            "candidate_id": row.get("candidate_id"),
            "replay_session_id": session_id,
            "diagnostic_drill_only": bool(row.get("diagnostic_drill_only")),
            "paper_runtime_gate_eligible": bool(row.get("paper_runtime_gate_eligible", False)),
            "mark_price": _float(row.get("mark_price")),
            "index_price": _float(row.get("index_price")),
            "liquidation_price": row.get("liquidation_price"),
            "liquidation_buffer_bps": row.get("liquidation_buffer_bps"),
            "risk_decision": row.get("risk_decision"),
        },
        client_order_id=client_order_id,
    )


def _apply_replay_row_to_lifecycle(order: Any, row: Mapping[str, Any]) -> None:
    decision_time = _timestamp_or_none(row.get("decision_time")) or order.order_intent.timestamp_utc
    fill_time = _timestamp_or_none(row.get("fill_time")) or decision_time
    broker_order_id = f"simulated:{order.client_order_id}"
    scenario = str(row.get("fixture_lifecycle_scenario") or "full_fill")
    if not row.get("risk_approved"):
        risk_blockers = row.get("risk_blockers") if isinstance(row.get("risk_blockers"), list) else []
        order.transition(
            BTCPaperOrderStatus.REJECTED,
            reason=str(row.get("risk_action") or "risk_rejected"),
            timestamp_utc=decision_time,
            metadata={
                "risk_approved": False,
                "risk_decision": row.get("risk_decision"),
                "risk_blockers": list(risk_blockers),
                "mark_price": row.get("mark_price"),
                "index_price": row.get("index_price"),
                "liquidation_price": row.get("liquidation_price"),
                "liquidation_buffer_bps": row.get("liquidation_buffer_bps"),
            },
        )
        order.reconcile(reason="reconciled_replay_rejected_order", metadata={"source": "paper_runtime_replay"})
        return
    order.transition(
        BTCPaperOrderStatus.RISK_CHECKED,
        reason=str(row.get("risk_action") or "risk_checked"),
        timestamp_utc=decision_time,
        metadata={
            "risk_approved": True,
            "risk_decision": row.get("risk_decision"),
            "mark_price": row.get("mark_price"),
            "index_price": row.get("index_price"),
            "liquidation_price": row.get("liquidation_price"),
            "liquidation_buffer_bps": row.get("liquidation_buffer_bps"),
        },
    )
    order.broker_order_id = broker_order_id
    order.transition(
        BTCPaperOrderStatus.SUBMITTED,
        reason="simulated_submit_from_replay",
        timestamp_utc=decision_time,
        metadata={"broker_order_id": broker_order_id, "order_endpoint_used": False},
    )
    order.transition(
        BTCPaperOrderStatus.ACCEPTED,
        reason="simulated_accept_from_replay",
        timestamp_utc=decision_time,
        metadata={
            "broker_order_id": broker_order_id,
            "reduce_only": bool(row.get("reduce_only")),
            "cancel_only_mode": bool(row.get("cancel_only_mode")),
            "ws_sequence_gap_detected": bool(row.get("ws_sequence_gap_detected")),
        },
    )
    if scenario == "exchange_reject":
        order.reject(
            reject_code="simulated_exchange_reject",
            reject_reason="simulated_exchange_reject_from_fixture",
            risk_state={"risk_decision": row.get("risk_decision"), "risk_approved": row.get("risk_approved")},
            exchange_response={"source": "deterministic_fixture", "order_endpoint_used": False},
            next_action="do_not_retry_without_reconciliation",
        )
        order.reconcile(reason="reconciled_fixture_exchange_reject", metadata={"source": "paper_runtime_replay"})
        return
    if scenario == "submit_unknown_retry_fill":
        order.transition(
            BTCPaperOrderStatus.UNKNOWN,
            reason="simulated_submit_outcome_unknown_query_before_retry",
            timestamp_utc=decision_time,
            metadata={
                "retry_required": True,
                "retry_allowed_without_status_query": False,
                "order_endpoint_used": False,
            },
        )
        order.transition(
            BTCPaperOrderStatus.ACCEPTED,
            reason="simulated_status_query_recovered_before_retry",
            timestamp_utc=fill_time,
            metadata={"retry_suppressed_after_status_query": True},
        )
    if row.get("simulated_fill_created"):
        fill_quantity = _filled_quantity(row)
        order.apply_fill(
            fill_quantity=fill_quantity,
            fill_id=_fill_id(row),
            price=_float(row.get("execution_price")),
            timestamp_utc=fill_time,
        )
        if scenario == "partial_cancel":
            order.request_cancel(reason="simulated_cancel_remaining_after_partial_fill")
            order.confirm_cancelled(reason="simulated_cancel_confirmed_after_partial_fill")
    else:
        order.expire(reason="simulated_replay_no_fill_expired")
    order.reconcile(reason="reconciled_from_replay_session", metadata={"source": "paper_runtime_replay"})


def _execution_fill_from_replay_row(row: Mapping[str, Any], client_order_id: str) -> BTCExecutionFill:
    decision_time = _timestamp_or_none(row.get("decision_time")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    fill_time = _timestamp_or_none(row.get("fill_time")) or decision_time
    execution_price = _float(row.get("execution_price"))
    return BTCExecutionFill(
        client_order_id=client_order_id,
        fill_id=_fill_id(row),
        filled_quantity=_filled_quantity(row),
        arrival_price=execution_price,
        fill_price=execution_price,
        benchmark_price=_float(row.get("index_price")) or execution_price,
        submitted_at_utc=decision_time,
        filled_at_utc=fill_time,
        fee=abs(_float(row.get("fee_amount_usdt"))),
    )


def _order_ledger_record(order: Any, *, session_id: str) -> dict[str, Any]:
    payload = order.to_dict()
    metadata = order.order_intent.metadata
    return {
        "session_id": session_id,
        "lifecycle_version": payload.get("lifecycle_version"),
        "order_id": payload.get("order_id"),
        "order_intent_id": payload.get("order_intent_id"),
        "client_order_id": payload.get("client_order_id"),
        "broker_order_id": payload.get("broker_order_id"),
        "venue": metadata.get("venue"),
        "venue_symbol": metadata.get("venue_symbol"),
        "instrument_id": metadata.get("instrument_id"),
        "instrument_type": metadata.get("instrument_type"),
        "account_id": metadata.get("account_id"),
        "account_mode": metadata.get("account_mode"),
        "position_mode": metadata.get("position_mode"),
        "margin_mode": metadata.get("margin_mode"),
        "margin_asset": metadata.get("margin_asset"),
        "exchange_metadata_version": metadata.get("exchange_metadata_version"),
        "strategy_id": payload.get("strategy_id"),
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "quantity": payload.get("quantity"),
        "order_type": metadata.get("order_type"),
        "time_in_force": metadata.get("time_in_force"),
        "reduce_only": bool(metadata.get("reduce_only")),
        "post_only": bool(metadata.get("post_only")),
        "cancel_only_mode": bool(metadata.get("cancel_only_mode")),
        "fee_side": metadata.get("fee_side"),
        "arrival_price": metadata.get("arrival_price"),
        "benchmark_price": metadata.get("benchmark_price"),
        "mark_price": metadata.get("mark_price"),
        "index_price": metadata.get("index_price"),
        "liquidation_price": metadata.get("liquidation_price"),
        "liquidation_buffer_bps": metadata.get("liquidation_buffer_bps"),
        "risk_decision": metadata.get("risk_decision"),
        "paper_runtime_gate_eligible": bool(metadata.get("paper_runtime_gate_eligible", False)),
        "status": payload.get("status"),
        "filled_quantity": payload.get("filled_quantity"),
        "remaining_quantity": payload.get("remaining_quantity"),
        "event_count": len(payload.get("events", [])),
        "events": payload.get("events", []),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _fill_ledger_record(fill: BTCExecutionFill, *, session_id: str, order: Any | None = None) -> dict[str, Any]:
    payload = fill.to_dict()
    metadata = order.order_intent.metadata if order is not None else {}
    side = order.order_intent.side.value if order is not None else ""
    return {
        "session_id": session_id,
        "venue": metadata.get("venue"),
        "venue_symbol": metadata.get("venue_symbol"),
        "instrument_id": metadata.get("instrument_id"),
        "instrument_type": metadata.get("instrument_type"),
        "account_id": metadata.get("account_id"),
        "account_mode": metadata.get("account_mode"),
        "position_mode": metadata.get("position_mode"),
        "margin_mode": metadata.get("margin_mode"),
        "margin_asset": metadata.get("margin_asset"),
        "strategy_id": order.order_intent.strategy_id if order is not None else "",
        "symbol": order.order_intent.symbol if order is not None else "",
        "side": side,
        **payload,
        "slippage_bps": _slippage_bps(
            side=side,
            arrival_price=payload.get("arrival_price"),
            fill_price=payload.get("fill_price"),
        ),
        "fee_side": metadata.get("fee_side"),
        "mark_price": metadata.get("mark_price"),
        "index_price": metadata.get("index_price"),
        "liquidation_price": metadata.get("liquidation_price"),
        "liquidation_buffer_bps": metadata.get("liquidation_buffer_bps"),
        "risk_decision": metadata.get("risk_decision"),
        "paper_runtime_gate_eligible": bool(metadata.get("paper_runtime_gate_eligible", False)),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _client_order_id(row: Mapping[str, Any], *, session_id: str) -> str:
    raw = "|".join([session_id, str(row.get("strategy_line")), str(row.get("candidate_id")), str(row.get("decision_time"))])
    return f"coid_{stable_payload_hash({'client_order': raw})[:20]}"


def _fill_id(row: Mapping[str, Any]) -> str:
    raw = "|".join([str(row.get("strategy_line")), str(row.get("candidate_id")), str(row.get("decision_time")), "fill"])
    return f"fill_{stable_payload_hash({'fill': raw})[:20]}"


def _filled_quantity(row: Mapping[str, Any]) -> float:
    explicit = abs(_float(row.get("simulated_filled_quantity_btc")))
    if explicit > 0.0:
        return explicit
    if str(row.get("fixture_lifecycle_scenario") or "") == "partial_cancel":
        return round(abs(_float(row.get("quantity_btc"))) * 0.5, 12)
    return abs(_float(row.get("quantity_btc")))


def _slippage_bps(*, side: str, arrival_price: Any, fill_price: Any) -> float:
    arrival = _float(arrival_price)
    fill = _float(fill_price)
    if arrival <= 0.0 or fill <= 0.0:
        return 0.0
    raw = (fill - arrival) / arrival * 10_000.0
    if side == "sell":
        raw = -raw
    return round(raw, 8)


def _opportunity_benchmark_price(rows: Sequence[Mapping[str, Any]]) -> float:
    for row in rows:
        for field in ("index_price", "mark_price", "execution_price"):
            value = _float(row.get(field))
            if value > 0.0:
                return value
    return 0.0


def _timestamp_or_none(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
