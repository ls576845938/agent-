"""Atomic in-memory ledger store with idempotency and rollback."""

from __future__ import annotations

from quant_cn.ledger.models import LedgerRecord


class LedgerConflictError(ValueError):
    pass


class InMemoryLedgerStore:
    def __init__(self) -> None:
        self._records: list[LedgerRecord] = []
        self._fingerprints: dict[str, str] = {}

    def append(self, record: LedgerRecord) -> bool:
        prior = self._fingerprints.get(record.record_id)
        if prior is not None:
            if prior != record.fingerprint:
                raise LedgerConflictError("ledger_record_id_conflict")
            return False
        self._records.append(record)
        self._fingerprints[record.record_id] = record.fingerprint
        return True

    def records(self) -> tuple[LedgerRecord, ...]:
        return tuple(
            sorted(self._records, key=lambda item: (item.occurred_at, item.record_id))
        )

    def unit_of_work(self) -> "LedgerUnitOfWork":
        return LedgerUnitOfWork(self)


class LedgerUnitOfWork:
    def __init__(self, store: InMemoryLedgerStore) -> None:
        self._store = store
        self._records_snapshot = list(store._records)
        self._fingerprints_snapshot = dict(store._fingerprints)
        self._committed = False

    def __enter__(self) -> "LedgerUnitOfWork":
        return self

    def append(self, record: LedgerRecord) -> bool:
        return self._store.append(record)

    def commit(self) -> None:
        self._committed = True

    def rollback(self) -> None:
        self._store._records = self._records_snapshot
        self._store._fingerprints = self._fingerprints_snapshot

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None or not self._committed:
            self.rollback()
        return False
