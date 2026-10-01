from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, ContextManager, Protocol


class FillLedger(Protocol):
    def append_fill(self, fill: Any) -> None:
        ...

    def read_records(self, name: str) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class FillIdentity:
    key: str
    fingerprint: tuple[Any, ...]


@dataclass(frozen=True)
class IdempotentFillAppendResult:
    status: str
    key: str
    conflict_existing: tuple[Any, ...] | None = None
    conflict_incoming: tuple[Any, ...] | None = None

    @property
    def appended(self) -> bool:
        return self.status == "appended"

    @property
    def duplicate(self) -> bool:
        return self.status == "duplicate"

    @property
    def conflict(self) -> bool:
        return self.status == "conflict"


class FillIdempotencyIndex:
    """In-memory index of ledger fill identities.

    The index can be prewarmed from historical ledger rows and then reused
    across a sync cycle so duplicate fills are not appended twice.
    """

    def __init__(self) -> None:
        self._fingerprints_by_key: dict[str, tuple[Any, ...]] = {}
        self._loaded = False

    @classmethod
    def from_ledger(cls, ledger: FillLedger) -> FillIdempotencyIndex:
        index = cls()
        index.load_ledger(ledger)
        return index

    def load_ledger(self, ledger: FillLedger, *, reload: bool = False) -> None:
        if self._loaded and not reload:
            return
        for record in ledger.read_records("fills.jsonl"):
            identity = fill_identity(record)
            if identity.key:
                self._fingerprints_by_key.setdefault(
                    identity.key,
                    identity.fingerprint,
                )
        self._loaded = True

    def check(self, fill: Any) -> IdempotentFillAppendResult | None:
        identity = fill_identity(fill)
        if not identity.key:
            return None

        existing = self._fingerprints_by_key.get(identity.key)
        if existing is None:
            return None
        if existing == identity.fingerprint:
            return IdempotentFillAppendResult("duplicate", identity.key)
        return IdempotentFillAppendResult(
            "conflict",
            identity.key,
            conflict_existing=existing,
            conflict_incoming=identity.fingerprint,
        )

    def remember(self, fill: Any) -> None:
        identity = fill_identity(fill)
        if identity.key:
            self._fingerprints_by_key[identity.key] = identity.fingerprint

    def __len__(self) -> int:
        return len(self._fingerprints_by_key)


def append_fill_idempotent(
    ledger: FillLedger,
    fill: Any,
    *,
    index: FillIdempotencyIndex | None = None,
    logger: logging.Logger | None = None,
) -> IdempotentFillAppendResult:
    """Append a fill unless the ledger already has an identical identity.

    Duplicate rows are skipped. Rows with the same key and different payload
    are reported as conflicts and are not appended.
    """

    with _idempotency_lock(ledger):
        active_index = index if index is not None else FillIdempotencyIndex.from_ledger(ledger)
        if index is not None:
            active_index.load_ledger(ledger, reload=True)

        checked = active_index.check(fill)
        if checked is not None:
            if checked.duplicate:
                if logger is not None:
                    logger.info("Duplicate fill skipped: key=%s", checked.key)
                return checked
            if logger is not None:
                logger.error("Conflicting fill skipped: key=%s", checked.key)
            return checked

        ledger.append_fill(fill)
        active_index.remember(fill)
        identity = fill_identity(fill)
        return IdempotentFillAppendResult("appended", identity.key)


def fill_identity(fill: Any) -> FillIdentity:
    return FillIdentity(key=fill_key(fill), fingerprint=fill_fingerprint(fill))


def fill_key(fill: Any) -> str:
    fill_id = _text(_value(fill, "fill_id"))
    if fill_id:
        return f"fill_id:{fill_id}"

    order_id = _text(_value(fill, "order_id"))
    if not order_id:
        return ""

    return (
        f"order:{order_id}"
        f"|broker_order:{_text(_value(fill, 'broker_order_id'))}"
        f"|symbol:{_symbol(_value(fill, 'symbol'))}"
        f"|side:{_side(_value(fill, 'side'))}"
        f"|filled_at:{_datetime_text(_value(fill, 'filled_at'))}"
    )


def fill_fingerprint(fill: Any) -> tuple[Any, ...]:
    return (
        _text(_value(fill, "order_id")),
        _symbol(_value(fill, "symbol")),
        _side(_value(fill, "side")),
        _number(_value(fill, "quantity")),
        _number(_value(fill, "price")),
        _number(_value(fill, "commission")),
        _datetime_text(_value(fill, "filled_at")),
        _text(_value(fill, "broker_order_id")),
        _text(_value(fill, "broker")),
    )


def _value(source: Any, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _idempotency_lock(ledger: FillLedger) -> ContextManager[Any]:
    lock_factory = getattr(ledger, "fill_idempotency_lock", None)
    if callable(lock_factory):
        return lock_factory()
    return nullcontext()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _symbol(value: Any) -> str:
    return _text(value).upper()


def _side(value: Any) -> str:
    return _text(value).lower()


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _datetime_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.isoformat()

    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text
