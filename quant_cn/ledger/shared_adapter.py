"""One-way CN ledger projection into the integrated asset-neutral contract."""

from __future__ import annotations

from quant_cn.compat.shared_adapter import build_ledger_record
from quant_cn.ledger.models import LedgerRecord
from quant_shared.ledger.contracts import LedgerRecord as SharedLedgerRecord


_SHARED_TYPES = {
    "cash": "cash",
    "fill": "fill",
    "mark": "position",
    "opening_cash": "cash",
    "position": "position",
}


def to_shared_ledger(
    records: tuple[LedgerRecord, ...],
    *,
    stream_id: str,
    evidence_ids: tuple[str, ...] = (),
) -> tuple[SharedLedgerRecord, ...]:
    """Export hashes and neutral types only; CN semantics stay in quant_cn."""

    return tuple(
        build_ledger_record(
            stream_id=stream_id,
            record_id=record.record_id,
            sequence=sequence,
            occurred_at=record.occurred_at,
            record_type=_SHARED_TYPES[record.record_type],
            domain_record={
                "cash_delta": str(record.cash_delta),
                "event_id": record.event_id,
                "fingerprint": record.fingerprint,
                "price": str(record.price) if record.price is not None else None,
                "quantity_delta": record.quantity_delta,
                "record_type": record.record_type,
                "session_sequence": record.session_sequence,
                "stable_security_id": record.stable_security_id,
            },
            evidence_ids=evidence_ids,
        )
        for sequence, record in enumerate(records, start=1)
    )
