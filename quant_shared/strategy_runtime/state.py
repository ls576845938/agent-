from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from quant_shared.strategy_runtime.models import (
    STRATEGY_STATE_SCHEMA_VERSION,
    StrategyStateKey,
    StrategyStateSnapshot,
    StrategyStateTransition,
    deep_thaw,
)


STRATEGY_STATE_STORE_SCHEMA_VERSION = "strategy_state_store_v1"


class StrategyStateConflictError(RuntimeError):
    pass


class StrategyStateStoreCorruptError(RuntimeError):
    pass


class StrategyStateStore(Protocol):
    def load(self, key: StrategyStateKey) -> StrategyStateSnapshot: ...

    def apply(self, transition: StrategyStateTransition) -> StrategyStateSnapshot: ...


def _validate_transition(
    current: StrategyStateSnapshot,
    transition: StrategyStateTransition,
) -> None:
    if transition.key != current.key:
        raise StrategyStateConflictError("strategy_state_key_mismatch")
    if transition.schema_version != current.schema_version:
        raise StrategyStateConflictError("strategy_state_schema_mismatch")
    if transition.expected_revision != current.revision:
        raise StrategyStateConflictError(
            "strategy_state_revision_conflict: "
            f"expected={transition.expected_revision} current={current.revision}"
        )
    if transition.previous_digest != current.digest:
        raise StrategyStateConflictError("strategy_state_previous_digest_conflict")


class InMemoryStrategyStateStore:
    def __init__(self) -> None:
        self._states: dict[StrategyStateKey, StrategyStateSnapshot] = {}
        self._lock = RLock()

    def load(self, key: StrategyStateKey) -> StrategyStateSnapshot:
        with self._lock:
            return self._states.get(key) or StrategyStateSnapshot.empty(key)

    def apply(self, transition: StrategyStateTransition) -> StrategyStateSnapshot:
        with self._lock:
            current = self._states.get(transition.key) or StrategyStateSnapshot.empty(
                transition.key,
                schema_version=transition.schema_version,
            )
            _validate_transition(current, transition)
            applied = transition.to_snapshot()
            self._states[transition.key] = applied
            return applied


class JsonFileStrategyStateStore:
    """Single-writer CAS state store with atomic file replacement.

    The repository governance contract supplies the single writer. Every CAS
    reloads the file before comparison, and the committed document is replaced
    atomically so a restart observes either the previous or the next revision.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def load(self, key: StrategyStateKey) -> StrategyStateSnapshot:
        with self._lock:
            document = self._read_document()
            return self._snapshot_from_document(document, key)

    def apply(self, transition: StrategyStateTransition) -> StrategyStateSnapshot:
        with self._lock:
            document = self._read_document()
            current = self._snapshot_from_document(document, transition.key)
            _validate_transition(current, transition)
            applied = transition.to_snapshot()
            states = dict(document["states"])
            states[self._entry_key(transition.key)] = self._serialize_snapshot(applied)
            self._atomic_write(
                {
                    "schema_version": STRATEGY_STATE_STORE_SCHEMA_VERSION,
                    "states": states,
                }
            )
            return applied

    @staticmethod
    def _entry_key(key: StrategyStateKey) -> str:
        return f"{key.run_id}\u001f{key.strategy_id}\u001f{key.identity_digest}"

    def _read_document(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": STRATEGY_STATE_STORE_SCHEMA_VERSION,
                "states": {},
            }
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StrategyStateStoreCorruptError(
                f"strategy state store unreadable: {self.path}"
            ) from exc
        if not isinstance(raw, dict):
            raise StrategyStateStoreCorruptError("strategy state store root must be an object")
        if raw.get("schema_version") != STRATEGY_STATE_STORE_SCHEMA_VERSION:
            raise StrategyStateStoreCorruptError("strategy state store schema mismatch")
        if not isinstance(raw.get("states"), dict):
            raise StrategyStateStoreCorruptError("strategy state store states must be an object")
        return raw

    def _snapshot_from_document(
        self,
        document: dict[str, Any],
        key: StrategyStateKey,
    ) -> StrategyStateSnapshot:
        entry = document["states"].get(self._entry_key(key))
        if entry is None:
            return StrategyStateSnapshot.empty(key)
        if not isinstance(entry, dict):
            raise StrategyStateStoreCorruptError("strategy state entry must be an object")
        if (
            entry.get("run_id") != key.run_id
            or entry.get("strategy_id") != key.strategy_id
            or str(entry.get("identity_digest") or "") != key.identity_digest
        ):
            raise StrategyStateStoreCorruptError("strategy state entry identity mismatch")
        try:
            return StrategyStateSnapshot(
                key=key,
                schema_version=str(entry.get("state_schema_version") or ""),
                revision=int(entry.get("revision")),
                payload=entry.get("payload") or {},
                last_decision_id=str(entry.get("last_decision_id") or ""),
                digest=str(entry.get("digest") or ""),
            )
        except (TypeError, ValueError) as exc:
            raise StrategyStateStoreCorruptError("strategy state entry is invalid") from exc

    @staticmethod
    def _serialize_snapshot(snapshot: StrategyStateSnapshot) -> dict[str, Any]:
        return {
            "run_id": snapshot.key.run_id,
            "strategy_id": snapshot.key.strategy_id,
            "identity_digest": snapshot.key.identity_digest,
            "state_schema_version": snapshot.schema_version,
            "revision": snapshot.revision,
            "payload": deep_thaw(snapshot.payload),
            "last_decision_id": snapshot.last_decision_id,
            "digest": snapshot.digest,
        }

    def _atomic_write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
