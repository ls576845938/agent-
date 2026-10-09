"""Durable, fail-closed storage contracts for the BTC demo OMS runtime."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import zlib
import stat
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from types import MappingProxyType
from collections.abc import Iterator


class BTCRuntimeStoreError(RuntimeError):
    """Raised when durable runtime evidence cannot be trusted."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class BTCRuntimeRecovery:
    state: dict[str, Any]
    events: tuple[Mapping[str, Any], ...]
    blockers: tuple[str, ...]
    truncated_tail: bool
    last_sequence: int
    last_event_hash: str


class _VerifiedEventSnapshot:
    """Private immutable values from a verified JSON event (never a file cache)."""

    def __init__(self, event: Mapping[str, Any]) -> None:
        self.keys = tuple(event)
        self.scalars = MappingProxyType({key: value for key, value in event.items()
                                        if type(value) in (str, int, float, bool, type(None))})
        self.compounds = MappingProxyType({key: zlib.compress(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL), level=1)
                                          for key, value in event.items() if key not in self.scalars})


class _RecoveryEventView(Mapping[str, Any]):
    """Fresh read view: scalar filters never inflate old account snapshots.

    Compound values decode lazily into this view only. A caller can mutate its
    returned payload without changing the private cache or subsequent recovery.
    Public replay results materialize the selected event as an ordinary dict.
    """

    def __init__(self, snapshot: _VerifiedEventSnapshot) -> None:
        self._snapshot = snapshot
        self._decoded: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        if key in self._snapshot.scalars:
            return self._snapshot.scalars[key]
        if key not in self._decoded:
            self._decoded[key] = pickle.loads(zlib.decompress(self._snapshot.compounds[key]))
        return self._decoded[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._snapshot.keys)

    def __len__(self) -> int:
        return len(self._snapshot.keys)


class _PrefixChunks:
    """Compressed private byte copies, NOT digest/stat-based trust.

    Every cached chunk is decompressed and compared byte-for-byte on recovery.
    Compression bounds resident memory for repetitive cumulative snapshots;
    reading is still O(log bytes), not a promise of constant-time recovery.
    """

    SIZE = 1024 * 1024

    def __init__(self, chunks: tuple[tuple[int, bytes], ...] = ()) -> None:
        self.chunks = list(chunks)
        self.pending = bytearray()
        self.started = False

    def feed(self, value: bytes) -> None:
        if not self.started:
            self.started = True
            if self.chunks and self.chunks[-1][0] < self.SIZE:
                self.pending.extend(zlib.decompress(self.chunks.pop()[1]))
        self.pending.extend(value)
        while len(self.pending) >= self.SIZE:
            block = bytes(self.pending[:self.SIZE])
            del self.pending[:self.SIZE]
            self.chunks.append((len(block), zlib.compress(block, level=1)))

    def finish(self) -> tuple[tuple[int, bytes], ...]:
        if self.pending:
            self.chunks.append((len(self.pending), zlib.compress(self.pending, level=1)))
        return tuple(self.chunks)


class _OfflineJournalSession:
    """Windows-only private, non-inheritable handle denying WRITE and DELETE.

    This is not a hostile-process security boundary (e.g. DuplicateHandle).
    It excludes normal competing opens for the lifetime of this local offline
    writer. The checkpoint is separate and NEVER covered by this proof.
    """

    def __init__(self, path: Path, *, create_new: bool) -> None:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
        kernel.GetDriveTypeW.restype = wintypes.UINT
        if kernel.GetDriveTypeW(path.anchor) != 3:  # DRIVE_FIXED, not a network share
            raise BTCRuntimeStoreError("btc_offline_journal_local_fixed_drive_required")
        # OPEN_REPARSE_POINT prevents silently acquiring a different linked file.
        native = kernel.CreateFileW(str(path), 0xC0000000, 1, None,
                                    1 if create_new else 3, 0x00200080, None)
        if native == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(native, os.O_RDWR | os.O_BINARY | os.O_NOINHERIT)
        except BaseException:
            kernel.CloseHandle(native)
            raise
        try:
            os.set_inheritable(fd, False)
            self.handle = open(fd, "r+b", closefd=True)
        except BaseException:
            os.close(fd)
            raise
        self.path = path
        try:
            initial = os.fstat(self.handle.fileno())
            self.identity = (initial.st_dev, initial.st_ino)
            self.expected_size = initial.st_size
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        info = os.fstat(self.handle.fileno())
        named = self.path.stat(follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(named, "st_file_attributes", 0) & 0x400
                or (info.st_dev, info.st_ino) != self.identity
                or (named.st_dev, named.st_ino) != self.identity
                or info.st_size != self.expected_size or named.st_size != self.expected_size
                or os.get_inheritable(self.handle.fileno())):
            raise BTCRuntimeStoreError("btc_offline_journal_identity_or_length_changed")

    def write(self, raw: bytes) -> None:
        self.check()
        start = self.expected_size
        # Discard read-ahead before touching the same CRT descriptor. There are
        # no buffered writes, including on a failed/short os.write.
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() != start or os.write(self.handle.fileno(), raw) != len(raw):
            raise BTCRuntimeStoreError("btc_offline_journal_short_write")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.seek(start)
        if self.handle.read(len(raw)) != raw:
            raise BTCRuntimeStoreError("btc_offline_journal_append_readback_mismatch")
        self.expected_size += len(raw)
        self.check()

    def close(self) -> None:
        self.handle.close()


class BTCRuntimeStore:
    """Hash-chained event log plus an independently atomic checkpoint."""

    def __init__(self, root: Path, *, verified_prefix_cache: bool = False,
                 offline_journal_session: bool = False) -> None:
        self.root = Path(root).resolve()
        self.events_path = self.root / "events.jsonl"
        self.checkpoint_path = self.root / "state.json"
        self._events: list[Mapping[str, Any]] = []
        self._by_key: dict[str, Mapping[str, Any]] = {}
        self._last_hash = ""
        self._sequence = 0
        # Optional offline acceleration only. Serialized objects below are
        # generated solely in this process from successfully verified JSON;
        # pickle is NEVER loaded from a file, artifact, network or caller.
        self.verified_prefix_cache = verified_prefix_cache or offline_journal_session
        self._verified_prefix_chunks: tuple[tuple[int, bytes], ...] = ()
        self._verified_events_snapshot: tuple[_VerifiedEventSnapshot, ...] = ()
        # Non-Windows explicitly retains exact-byte prefix comparison. No
        # advisory flock/stat-only substitute for Windows sharing guarantees.
        self._offline_session_enabled = offline_journal_session and os.name == "nt"
        self._offline_session_lock = threading.RLock()
        self._journal_session: _OfflineJournalSession | None = None
        self._journal_new_root = not self.root.exists()
        self._journal_verified_size = 0
        self._journal_proof_ready = False
        self._journal_failure = ""
        self._journal_closed = False

    def _require_session(self) -> _OfflineJournalSession:
        if self._journal_failure or self._journal_closed:
            raise BTCRuntimeStoreError(self._journal_failure or "btc_offline_journal_session_closed")
        if self._journal_session is None:
            if self._journal_new_root:
                # Only an explicitly fresh directory may create a log. Recovery
                # of a pre-existing root never silently recreates a missing log.
                self.root.mkdir(parents=True, exist_ok=False)
            self._journal_session = _OfflineJournalSession(self.events_path, create_new=self._journal_new_root)
            self._journal_new_root = False
        self._journal_session.check()
        return self._journal_session

    def _invalidate_session(self, reason: str) -> None:
        self._journal_failure = reason
        self._journal_proof_ready = False
        self._verified_prefix_chunks = ()
        self._verified_events_snapshot = ()
        if self._journal_session is not None:
            self._journal_session.close()

    def close(self) -> None:
        with self._offline_session_lock:
            self._journal_closed = True
            self._journal_proof_ready = False
            self._verified_prefix_chunks = ()
            self._verified_events_snapshot = ()
            if self._journal_session is not None:
                self._journal_session.close()

    def _read_session_events(self, metadata: dict[str, Any], blockers: list[str]) -> Iterator[Mapping[str, Any]]:
        session = self._require_session()
        handle = session.handle
        if self._journal_proof_ready:
            handle.seek(self._journal_verified_size)
            metadata["verified_count"] = len(self._verified_events_snapshot)
            metadata["newline"] = True
            for snapshot in self._verified_events_snapshot:
                yield _RecoveryEventView(snapshot)
        else:
            handle.seek(0)
        for physical_line in handle:
            metadata["newline"] = physical_line.endswith(b"\n")
            lines = physical_line.splitlines(keepends=True)
            for index, line in enumerate(lines):
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    truncated = (index == len(lines) - 1 and not line.endswith((b"\n", b"\r")) and not handle.peek(1))
                    metadata["truncated"] = truncated
                    blockers.append("btc_runtime_event_log_truncated_tail" if truncated else "btc_runtime_event_log_corrupt")
                    return
        metadata["session_offset"] = handle.tell()
        session.check()

    def _read_cached_events(self, metadata: dict[str, Any], blockers: list[str]) -> Iterator[Mapping[str, Any]]:
        """One handle, exact old-prefix comparison, streaming new JSON records.

        On restart or mismatch the complete chain is parsed/verified afresh,
        one record at a time. No decoded whole-history JSON list is retained.
        """
        if not self.events_path.exists():
            return
        with self.events_path.open("rb") as handle:
            same = bool(self._verified_prefix_chunks and self._verified_events_snapshot)
            if same:
                for size, packed in self._verified_prefix_chunks:
                    if handle.read(size) != zlib.decompress(packed):
                        same = False
                        break
            if same:
                metadata["verified_count"] = len(self._verified_events_snapshot)
                metadata["newline"] = True
                chunks = _PrefixChunks(self._verified_prefix_chunks)
                for snapshot in self._verified_events_snapshot:
                    yield _RecoveryEventView(snapshot)
            else:
                handle.seek(0)
                chunks = _PrefixChunks()
            for physical_line in handle:
                chunks.feed(physical_line)
                metadata["newline"] = physical_line.endswith(b"\n")
                # Preserve the legacy splitlines treatment of CR / CRLF too.
                lines = physical_line.splitlines(keepends=True)
                for index, line in enumerate(lines):
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        truncated = (index == len(lines) - 1 and not line.endswith((b"\n", b"\r")) and not handle.peek(1))
                        metadata["truncated"] = truncated
                        blockers.append("btc_runtime_event_log_truncated_tail" if truncated else "btc_runtime_event_log_corrupt")
                        return
            metadata["chunks"] = chunks.finish()

    def recover(self) -> BTCRuntimeRecovery:
        with self._offline_session_lock if self._offline_session_enabled else nullcontext():
            try:
                result = self._recover()
                if self._offline_session_enabled and result.blockers:
                    self._invalidate_session("btc_offline_journal_recovery_blocked")
                return result
            except BaseException as exc:
                if not self._offline_session_enabled:
                    raise
                reason = "btc_offline_journal_session_invalid:" + type(exc).__name__
                self._invalidate_session(reason)
                if not isinstance(exc, (OSError, ValueError, TypeError, BTCRuntimeStoreError)):
                    raise
                return BTCRuntimeRecovery({}, (), (reason,), False, 0, "")

    def _recover(self) -> BTCRuntimeRecovery:
        blockers: list[str] = []
        truncated = False
        checkpoint_state: dict[str, Any] = {}
        checkpoint_sequence = 0
        checkpoint_hash = ""
        if self.checkpoint_path.exists():
            try:
                checkpoint = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
                supplied = checkpoint.pop("checkpoint_hash")
                if supplied != _digest(checkpoint):
                    raise ValueError("hash")
                checkpoint_state = dict(checkpoint.get("state", {}))
                checkpoint_sequence = int(checkpoint.get("last_sequence", 0))
                checkpoint_hash = str(checkpoint.get("last_event_hash", ""))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                blockers.append("btc_runtime_checkpoint_invalid")

        parsed: list[Mapping[str, Any]] = []
        verified_count = 0
        raw = b""
        metadata: dict[str, Any] = {"verified_count": 0, "newline": False, "chunks": (), "truncated": False}
        if self._offline_session_enabled:
            parsed = self._read_session_events(metadata, blockers)
        elif self.verified_prefix_cache:
            parsed = self._read_cached_events(metadata, blockers)
        elif self.events_path.exists():
            raw = self.events_path.read_bytes()
            remaining = raw
            lines = remaining.splitlines(keepends=True)
            for index, line in enumerate(lines):
                try:
                    parsed.append(json.loads(line))
                except json.JSONDecodeError:
                    if index == len(lines) - 1 and not line.endswith((b"\n", b"\r")):
                        truncated = True
                        blockers.append("btc_runtime_event_log_truncated_tail")
                        break
                    blockers.append("btc_runtime_event_log_corrupt")
                    break

        valid: list[Mapping[str, Any]] = []
        previous = ""
        seen: dict[str, str] = {}
        for expected, event in enumerate(parsed, start=1):
            verified_count = metadata["verified_count"]
            supplied = str(event.get("event_hash", ""))
            # Do not materialize verified compound fields only to discard
            # them: their exact serialized prefix was already byte-compared.
            body = ({key: value for key, value in event.items() if key != "event_hash"}
                    if expected > verified_count else None)
            key = str(event.get("idempotency_key", ""))
            semantic_hash = str(event.get("semantic_hash", ""))
            if (
                int(event.get("sequence", -1)) != expected
                or event.get("previous_event_hash", "") != previous
                or (expected > verified_count and supplied != _digest(body))
                or not key
            ):
                blockers.append("btc_runtime_event_chain_invalid")
                break
            if key in seen and seen[key] != semantic_hash:
                blockers.append("btc_runtime_idempotency_conflict")
                break
            seen[key] = semantic_hash
            valid.append(_RecoveryEventView(_VerifiedEventSnapshot(event))
                         if self.verified_prefix_cache and expected > verified_count else event)
            previous = supplied
        if self.verified_prefix_cache:
            parsed.close()
            truncated = metadata["truncated"]

        if checkpoint_sequence > len(valid):
            blockers.append("btc_runtime_checkpoint_ahead_of_event_log")
        elif checkpoint_sequence and valid[checkpoint_sequence - 1]["event_hash"] != checkpoint_hash:
            blockers.append("btc_runtime_checkpoint_event_hash_mismatch")

        state = checkpoint_state
        for event in valid[checkpoint_sequence:]:
            state = dict(event.get("state_after", state))
            if isinstance(event, _RecoveryEventView):
                event._decoded.pop("state_after", None)
        self._events = valid
        self._by_key = {str(event["idempotency_key"]): event for event in valid}
        self._sequence = len(valid)
        self._last_hash = previous
        if self._offline_session_enabled and not blockers and (metadata["newline"] or metadata.get("session_offset") == 0):
            snapshots = tuple(event._snapshot for event in valid)
            self._journal_verified_size = metadata["session_offset"]
            self._verified_events_snapshot = snapshots
            self._journal_proof_ready = True
        elif self.verified_prefix_cache and not blockers and metadata["newline"]:
            self._verified_prefix_chunks = metadata["chunks"]
            self._verified_events_snapshot = tuple(event._snapshot for event in valid)
        else:
            self._verified_prefix_chunks = ()
            self._verified_events_snapshot = ()
        return BTCRuntimeRecovery(
            state=state,
            events=tuple(valid),
            blockers=tuple(dict.fromkeys(blockers)),
            truncated_tail=truncated,
            last_sequence=self._sequence,
            last_event_hash=self._last_hash,
        )

    def append(
        self, *, event_type: str, payload: Mapping[str, Any],
        state_after: Mapping[str, Any], idempotency_key: str,
        timestamp_utc: str, run_id: str, safety: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._offline_session_lock if self._offline_session_enabled else nullcontext():
            try:
                if self._offline_session_enabled:
                    self._require_session()
                    if not self._journal_proof_ready and self.recover().blockers:
                        raise BTCRuntimeStoreError("btc_offline_journal_initial_recovery_blocked")
                    if not self._journal_proof_ready:
                        raise BTCRuntimeStoreError("btc_offline_journal_incomplete_record_boundary")
                return self._append(event_type=event_type, payload=payload, state_after=state_after,
                                    idempotency_key=idempotency_key, timestamp_utc=timestamp_utc,
                                    run_id=run_id, safety=safety)
            except BaseException as exc:
                if not self._offline_session_enabled:
                    raise
                self._invalidate_session("btc_offline_journal_append_failed")
                if isinstance(exc, BTCRuntimeStoreError) or not isinstance(exc, (OSError, ValueError, TypeError)):
                    raise
                raise BTCRuntimeStoreError("btc_offline_journal_append_failed") from exc

    def _append(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        state_after: Mapping[str, Any],
        idempotency_key: str,
        timestamp_utc: str,
        run_id: str,
        safety: Mapping[str, Any],
    ) -> dict[str, Any]:
        semantic = {
            "event_type": event_type,
            "payload": dict(payload),
            "run_id": run_id,
        }
        semantic_hash = _digest(semantic)
        existing = self._by_key.get(idempotency_key)
        if existing:
            if existing["semantic_hash"] != semantic_hash:
                raise BTCRuntimeStoreError("btc_runtime_idempotency_conflict")
            return existing if isinstance(existing, dict) else dict(existing)
        body = {
            "schema_version": "btc_demo_oms_runtime_event_v2",
            "sequence": self._sequence + 1,
            "idempotency_key": idempotency_key,
            "semantic_hash": semantic_hash,
            "previous_event_hash": self._last_hash,
            "timestamp_utc": timestamp_utc,
            "run_id": run_id,
            "event_type": event_type,
            "payload": json.loads(json.dumps(payload, default=str)),
            "safety": dict(safety),
            "state_after": json.loads(json.dumps(state_after, default=str)),
        }
        event = {**body, "event_hash": _digest(body)}
        self.root.mkdir(parents=True, exist_ok=True)
        if self._offline_session_enabled:
            self._require_session().write(_canonical(event) + b"\n")
        else:
            with self.events_path.open("ab") as handle:
                handle.write(_canonical(event) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
        self._events.append(event)
        self._by_key[idempotency_key] = event
        self._sequence += 1
        self._last_hash = event["event_hash"]
        return event

    def checkpoint(self, state: Mapping[str, Any]) -> None:
        with self._offline_session_lock if self._offline_session_enabled else nullcontext():
            try:
                if self._offline_session_enabled:
                    self._require_session()
                    if not self._journal_proof_ready and self.recover().blockers:
                        raise BTCRuntimeStoreError("btc_offline_journal_initial_recovery_blocked")
                self._checkpoint(state)
            except BaseException as exc:
                if not self._offline_session_enabled:
                    raise
                self._invalidate_session("btc_offline_journal_checkpoint_failed")
                if isinstance(exc, BTCRuntimeStoreError) or not isinstance(exc, (OSError, ValueError, TypeError)):
                    raise
                raise BTCRuntimeStoreError("btc_offline_journal_checkpoint_failed") from exc

    def _checkpoint(self, state: Mapping[str, Any]) -> None:
        body = {
            "schema_version": "btc_demo_oms_runtime_checkpoint_v2",
            "last_sequence": self._sequence,
            "last_event_hash": self._last_hash,
            "state": json.loads(json.dumps(state, default=str)),
        }
        document = {**body, "checkpoint_hash": _digest(body)}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint_path.with_suffix(".json.tmp")
        with temporary.open("wb") as handle:
            handle.write(_canonical(document))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.checkpoint_path)

    def commit_ledger_uow(
        self,
        *,
        idempotency_key: str,
        timestamp_utc: str,
        run_id: str,
        order: Mapping[str, Any],
        fills: list[Mapping[str, Any]],
        position: Mapping[str, Any],
        cash: Mapping[str, Any],
        funding: Mapping[str, Any],
        risk_context: Mapping[str, Any],
        account_drawdown_fact: Mapping[str, Any] | None = None,
        allocation_payload: Mapping[str, Any] | None = None,
        state_after: Mapping[str, Any],
        safety: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = ("mark_price", "index_price", "liquidation_buffer_bps", "venue_rules")
        missing = [field for field in required if risk_context.get(field) in (None, "", {})]
        if missing:
            raise BTCRuntimeStoreError("btc_runtime_risk_context_incomplete:" + ",".join(missing))
        if not order or not position or not cash or not funding:
            raise BTCRuntimeStoreError("btc_runtime_ledger_uow_incomplete")
        drawdown_fact = dict(account_drawdown_fact or {})
        state_fact_value = state_after.get("account_risk_facts")
        if state_fact_value is None:
            state_fact: dict[str, Any] = {}
        elif isinstance(state_fact_value, Mapping):
            state_fact = dict(state_fact_value)
        else:
            raise BTCRuntimeStoreError(
                "btc_runtime_account_drawdown_fact_state_mismatch"
            )
        # The append semantic hash covers payload, not state_after.  Require
        # exact bidirectional parity so recovery can never accept an account
        # fact that was omitted from the hashed UOW payload.  Empty on both
        # sides remains the explicit legacy path.
        if drawdown_fact != state_fact:
            raise BTCRuntimeStoreError(
                "btc_runtime_account_drawdown_fact_state_mismatch"
            )
        allocation = dict(allocation_payload or {})
        state_allocation_value = state_after.get("strategy_allocations")
        if state_allocation_value is None:
            state_allocation: dict[str, Any] = {}
        elif isinstance(state_allocation_value, Mapping):
            state_allocation = dict(state_allocation_value)
        else:
            raise BTCRuntimeStoreError(
                "btc_runtime_strategy_allocation_state_mismatch"
            )
        # Allocation facts are optional, but when present they are hashed in
        # the same UOW payload and must exactly match the recovered state in
        # both directions.  Empty legacy callers retain identical payloads and
        # therefore identical semantic hashes.
        if allocation != state_allocation:
            raise BTCRuntimeStoreError(
                "btc_runtime_strategy_allocation_state_mismatch"
            )
        payload = {
            "order_ledger": dict(order),
            "fill_ledger": [dict(fill) for fill in fills],
            "position_ledger": dict(position),
            "cash_ledger": dict(cash),
            "funding_ledger": dict(funding),
            "risk_context": dict(risk_context),
        }
        if drawdown_fact:
            # Keep legacy event hashes stable when no versioned account fact is
            # supplied, while binding fact changes to the UOW semantic hash.
            payload["account_drawdown_fact"] = drawdown_fact
        if allocation:
            payload["strategy_allocation"] = allocation
        return self.append(
            event_type="ledger_uow_committed",
            payload=payload,
            state_after=state_after,
            idempotency_key=idempotency_key,
            timestamp_utc=timestamp_utc,
            run_id=run_id,
            safety=safety,
        )


class BTCRecordedPrivateWSAdapter:
    """Fixture-only private-stream contract; it can never open an endpoint."""

    def __init__(self, recorded_events: tuple[Mapping[str, Any], ...] = ()) -> None:
        self._events = tuple(dict(event) for event in recorded_events)

    @property
    def live_connection_enabled(self) -> bool:
        return False

    def replay(self) -> tuple[dict[str, Any], ...]:
        return self._events

    def connect(self) -> None:
        raise BTCRuntimeStoreError("btc_private_ws_endpoint_not_authorized")
