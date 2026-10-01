"""Offline funding cashflow replay evidence.

The result proves deterministic accounting against supplied fixtures only.  It
cannot serve as a real funding observation or promotion credential.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from quant_crypto.backtest.funding_ledger import (
    FundingFill,
    FundingRateEvent,
    calculate_funding_payments,
    replay_perpetual_fill_position_cash_ledger,
)
from quant_crypto.monitoring.artifact_schema import (
    apply_btc_artifact_schema,
    stable_payload_hash,
)
from quant_shared.core.time import ensure_utc


SCHEMA_VERSION = "btc_funding_cashflow_evidence_v2"
REAL_OBSERVATION_BLOCKER = (
    "btc_funding_cashflow:real_current_head_cashflow_observation_missing"
)


def build_offline_funding_cashflow_evidence(
    *,
    current_head: str,
    source_head: str,
    generated_at_utc: datetime,
    funding_rates: Sequence[FundingRateEvent],
    fills: Sequence[FundingFill],
    source_receipt: Mapping[str, Any],
    expected_total_payment: float | None = None,
    fixture_only: bool = True,
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc)
    funding_rows = [_funding_rate_row(row) for row in funding_rates]
    fill_rows = [_fill_row(row) for row in fills]
    rates_hash = stable_payload_hash(funding_rows)
    fills_hash = stable_payload_hash(fill_rows)
    blockers: list[str] = []
    if source_head != current_head:
        blockers.append("btc_funding_cashflow:source_head_mismatch")
    if not fixture_only:
        blockers.append("btc_funding_cashflow:offline_contract_rejects_non_fixture_input")
    if str(source_receipt.get("funding_rates_sha256") or "") != rates_hash:
        blockers.append("btc_funding_cashflow:funding_rates_hash_mismatch")
    if str(source_receipt.get("fills_sha256") or "") != fills_hash:
        blockers.append("btc_funding_cashflow:fills_hash_mismatch")
    if not str(source_receipt.get("data_version") or "").strip():
        blockers.append("btc_funding_cashflow:data_version_missing")
    if not funding_rows:
        blockers.append("btc_funding_cashflow:funding_rate_fixture_empty")
    if not fill_rows:
        blockers.append("btc_funding_cashflow:fill_fixture_empty")
    blockers.extend(_identity_blockers(funding_rows, fill_rows))

    payments = calculate_funding_payments(funding_rates=funding_rates, fills=fills)
    payment_rows = [
        {
            "event_type": "funding_cashflow",
            "funding_time": row.funding_time.isoformat(),
            "position_qty": row.position_qty,
            "mark_price": row.mark_price,
            "index_price": row.index_price,
            "funding_rate": row.funding_rate,
            "funding_payment": row.funding_payment,
            "source_record_id": row.source_record_id,
            "instrument_id": row.instrument_id,
            "settlement_asset": row.settlement_asset,
        }
        for row in payments
    ]
    total_payment = round(sum(row.funding_payment for row in payments), 12)
    if expected_total_payment is not None and abs(
        total_payment - float(expected_total_payment)
    ) > 1e-10:
        blockers.append("btc_funding_cashflow:expected_total_payment_mismatch")
    engineering_blockers = _dedupe(blockers)
    all_blockers = [*engineering_blockers, REAL_OBSERVATION_BLOCKER]
    pnl = replay_perpetual_fill_position_cash_ledger(
        fills=fills,
        funding_rates=funding_rates,
        valuation_mark_price=(
            funding_rates[-1].mark_price
            if funding_rates
            else fills[-1].price
            if fills
            else 1.0
        ),
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
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "source_head": source_head,
        "code_commit": current_head,
        "fixture_only": True,
        "offline_fixture_validated": not engineering_blockers,
        "real_observation": False,
        "funding_cashflow_observed": False,
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
        "source_receipt": {
            "data_version": str(source_receipt.get("data_version") or ""),
            "funding_rates_sha256": rates_hash,
            "fills_sha256": fills_hash,
        },
        "payments": payment_rows,
        "payment_count": len(payment_rows),
        "total_funding_payment": total_payment,
        "ledger_reconciled": not engineering_blockers,
        "ledger": {
            "entry_count": len(ledger_rows),
            "entries": ledger_rows,
            "position_qty": pnl.position_qty,
            "cash_balance": pnl.cash_balance,
            "position_value": pnl.position_value,
            "price_pnl": pnl.price_pnl,
            "funding_pnl": pnl.funding_pnl,
            "fee_pnl": pnl.fee_pnl,
            "total_pnl": pnl.total_pnl,
            "pnl_derived_from": ["fills", "positions", "cash_ledger"],
        },
        "safety": {
            "network_accessed": False,
            "private_endpoint_accessed": False,
            "order_endpoint_accessed": False,
            "paper_queue_write_enabled": False,
            "real_orders_enabled": False,
            "secrets_read": False,
        },
        "blockers": all_blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="offline_fixture_validated_real_cashflow_still_blocked"
        if not engineering_blockers
        else "offline_fixture_invalid_fail_closed",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=all_blockers,
        warnings=[],
        input_hashes={
            "funding_rates": rates_hash,
            "fills": fills_hash,
            "payments": stable_payload_hash(payment_rows),
            "ledger": stable_payload_hash(ledger_rows),
        },
    )


def _funding_rate_row(row: FundingRateEvent) -> dict[str, Any]:
    return {
        "funding_time": ensure_utc(row.funding_time).isoformat(),
        "funding_rate": float(row.funding_rate),
        "mark_price": float(row.mark_price),
        "source_record_id": row.source_record_id,
    }


def _fill_row(row: FundingFill) -> dict[str, Any]:
    return {
        "filled_at": ensure_utc(row.filled_at).isoformat(),
        "side": row.side.strip().lower(),
        "quantity": float(row.quantity),
        "price": float(row.price),
        "fill_id": row.fill_id,
    }


def _identity_blockers(
    funding_rows: Sequence[Mapping[str, Any]], fill_rows: Sequence[Mapping[str, Any]]
) -> list[str]:
    blockers: list[str] = []
    rate_ids = [str(row["source_record_id"]) for row in funding_rows]
    fill_ids = [str(row["fill_id"]) for row in fill_rows]
    if any(not value for value in rate_ids) or len(rate_ids) != len(set(rate_ids)):
        blockers.append("btc_funding_cashflow:funding_source_record_ids_invalid")
    if any(not value for value in fill_ids) or len(fill_ids) != len(set(fill_ids)):
        blockers.append("btc_funding_cashflow:fill_ids_invalid")
    if any(float(row["mark_price"]) <= 0 for row in funding_rows):
        blockers.append("btc_funding_cashflow:mark_price_non_positive")
    if any(float(row["quantity"]) <= 0 or float(row["price"]) <= 0 for row in fill_rows):
        blockers.append("btc_funding_cashflow:fill_quantity_or_price_non_positive")
    return blockers


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "REAL_OBSERVATION_BLOCKER",
    "SCHEMA_VERSION",
    "build_offline_funding_cashflow_evidence",
]
