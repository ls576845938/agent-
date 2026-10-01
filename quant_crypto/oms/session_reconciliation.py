from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from quant_shared.core.time import ensure_utc

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash
from quant_crypto.oms.execution_quality import BTCExecutionFill, build_btc_execution_quality_report
from quant_crypto.oms.lifecycle import BTCPaperOrderLifecycle, BTCPaperOrderStatus


BTC_PAPER_OMS_SESSION_RECONCILIATION_VERSION = "btc_paper_oms_session_reconciliation_v1"


def build_btc_paper_oms_session_reconciliation(
    *,
    session_id: str,
    orders: Iterable[BTCPaperOrderLifecycle],
    fills: Iterable[BTCExecutionFill],
    ledger_hash: str,
    generated_at_utc: datetime,
    opportunity_benchmark_price: float,
) -> dict[str, Any]:
    orders_list = list(orders)
    fills_list = list(fills)
    quality = build_btc_execution_quality_report(
        orders_list,
        fills_list,
        opportunity_benchmark_price=opportunity_benchmark_price,
    ).to_dict()
    order_ids = {order.client_order_id for order in orders_list}
    fill_order_ids = {fill.client_order_id for fill in fills_list}
    blockers: list[str] = []
    if not session_id:
        blockers.append("btc_paper_oms_session_id_missing")
    if not ledger_hash:
        blockers.append("btc_paper_oms_session_ledger_hash_missing")
    if not orders_list:
        blockers.append("btc_paper_oms_session_no_orders")
    unreconciled_client_order_ids = [
        order.client_order_id for order in orders_list if order.status != BTCPaperOrderStatus.RECONCILED
    ]
    if unreconciled_client_order_ids:
        blockers.append("btc_paper_oms_session_unreconciled_order_lifecycle")
    missing_fills = [
        order.client_order_id
        for order in orders_list
        if _has_filled_event(order) and order.client_order_id not in fill_order_ids
    ]
    if missing_fills:
        blockers.append("btc_paper_oms_session_filled_orders_missing_fill_rows")
    unknown_fills = sorted(fill_order_ids - order_ids)
    if unknown_fills:
        blockers.append("btc_paper_oms_session_fill_without_order")
    blockers.extend(str(item) for item in quality.get("blocker_reasons", []) if item)
    payload = {
        "paper_oms_session_reconciliation_version": BTC_PAPER_OMS_SESSION_RECONCILIATION_VERSION,
        "status": "complete" if not blockers else "blocked",
        "session_id": session_id,
        "ledger_hash": ledger_hash,
        "order_count": len(orders_list),
        "fill_count": len(fills_list),
        "unreconciled_order_count": len(unreconciled_client_order_ids),
        "unreconciled_client_order_ids": unreconciled_client_order_ids,
        "orders": [order.to_dict() for order in orders_list],
        "fills": [fill.to_dict() for fill in fills_list],
        "execution_quality": quality,
        "missing_fill_client_order_ids": missing_fills,
        "unknown_fill_client_order_ids": unknown_fills,
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="paper_oms_session_reconciled" if not blockers else "paper_oms_session_blocked",
        generated_at_utc=ensure_utc(generated_at_utc),
        as_of_utc=ensure_utc(generated_at_utc),
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={
            "orders": stable_payload_hash(payload["orders"]),
            "fills": stable_payload_hash(payload["fills"]),
            "ledger": ledger_hash,
        },
    )


def _has_filled_event(order: BTCPaperOrderLifecycle) -> bool:
    return any(event.status == BTCPaperOrderStatus.FILLED for event in order.events)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
