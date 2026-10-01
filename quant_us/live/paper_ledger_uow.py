"""Recoverable file unit-of-work for US equity paper ledgers.

Each paper cycle stages complete replacement bytes for every ledger file,
records a durable transaction journal, then applies the replacements. A caught
failure rolls every file back; a later process can recover PREPARED/APPLYING
transactions before accepting another cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any, Callable, Mapping, Sequence
import uuid


TRANSACTION_SCHEMA_VERSION = "us_equity_paper_ledger_transaction_v1"
PENDING_STATUSES = {"PREPARED", "APPLYING", "ROLLBACK_FAILED"}
TERMINAL_STATUSES = {"COMMITTED", "ROLLED_BACK"}
ReplaceFn = Callable[[str | bytes | os.PathLike[str] | os.PathLike[bytes], str | bytes | os.PathLike[str] | os.PathLike[bytes]], Any]


class PaperLedgerCommitError(RuntimeError):
    def __init__(self, message: str, *, transaction_id: str, journal_path: Path, rollback_succeeded: bool) -> None:
        super().__init__(message)
        self.transaction_id = transaction_id
        self.journal_path = journal_path
        self.rollback_succeeded = rollback_succeeded


@dataclass(frozen=True)
class PaperLedgerRecoveryResult:
    status: str
    recovered_transaction_ids: list[str]
    blockers: list[str]


@dataclass
class PaperLedgerTransaction:
    ledger_root: Path
    transaction_id: str
    transaction_dir: Path
    journal: dict[str, Any]

    @property
    def journal_path(self) -> Path:
        return self.transaction_dir / "transaction.json"

    def commit(self, *, apply_replace: ReplaceFn | None = None) -> dict[str, Any]:
        replace_fn = apply_replace or os.replace
        self._write_status("APPLYING")
        try:
            for operation in self.journal["operations"]:
                final_path = self.ledger_root / str(operation["relative_path"])
                staged_path = self.transaction_dir / str(operation["staged_path"])
                final_path.parent.mkdir(parents=True, exist_ok=True)
                replace_fn(staged_path, final_path)
        except BaseException as exc:
            rollback_succeeded = self.rollback()
            raise PaperLedgerCommitError(
                f"paper ledger transaction {self.transaction_id} failed: {type(exc).__name__}",
                transaction_id=self.transaction_id,
                journal_path=self.journal_path,
                rollback_succeeded=rollback_succeeded,
            ) from exc
        self._write_status("COMMITTED")
        self._cleanup_payloads()
        return self.summary()

    def rollback(self) -> bool:
        blockers: list[str] = []
        for operation in reversed(self.journal.get("operations", [])):
            final_path = self.ledger_root / str(operation.get("relative_path", ""))
            existed_before = operation.get("existed_before") is True
            backup_path = self.transaction_dir / str(operation.get("backup_path", ""))
            try:
                if existed_before:
                    if not backup_path.exists():
                        raise FileNotFoundError(str(backup_path))
                    _atomic_replace_bytes(final_path, backup_path.read_bytes())
                else:
                    final_path.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                blockers.append(f"rollback_failed:{operation.get('relative_path')}:{type(exc).__name__}")
        self.journal["rollback_blockers"] = blockers
        self._write_status("ROLLED_BACK" if not blockers else "ROLLBACK_FAILED")
        if not blockers:
            self._cleanup_payloads()
        return not blockers

    def summary(self) -> dict[str, Any]:
        return {
            "status": str(self.journal.get("status", "")),
            "transaction_id": self.transaction_id,
            "journal_path": self.journal_path.as_posix(),
            "operation_count": len(self.journal.get("operations", [])),
            "relative_paths": [str(item.get("relative_path", "")) for item in self.journal.get("operations", [])],
            "rollback_blockers": list(self.journal.get("rollback_blockers", [])),
        }

    def _write_status(self, status: str) -> None:
        self.journal["status"] = status
        _atomic_write_json(self.journal_path, self.journal)

    def _cleanup_payloads(self) -> None:
        for name in ("staged", "backup"):
            shutil.rmtree(self.transaction_dir / name, ignore_errors=True)


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def _root_lock(root: Path) -> threading.RLock:
    resolved = root.resolve()
    with _LOCKS_GUARD:
        lock = _LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[resolved] = lock
        return lock


def commit_paper_ledger_cycle(
    *,
    ledger_root: Path,
    timestamp: str,
    generated_at: str,
    jsonl_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    json_documents: Mapping[str, Mapping[str, Any]],
    apply_replace: ReplaceFn | None = None,
) -> dict[str, Any]:
    with _root_lock(ledger_root):
        recovery = recover_incomplete_paper_ledger_transactions(ledger_root)
        if recovery.blockers:
            raise PaperLedgerCommitError(
                "paper ledger recovery blocked before commit",
                transaction_id="recovery_blocked",
                journal_path=ledger_root / ".transactions",
                rollback_succeeded=False,
            )
        transaction = prepare_paper_ledger_transaction(
            ledger_root=ledger_root,
            timestamp=timestamp,
            generated_at=generated_at,
            jsonl_rows=jsonl_rows,
            json_documents=json_documents,
        )
        summary = transaction.commit(apply_replace=apply_replace)
        summary["recovery_status_before_commit"] = recovery.status
        summary["recovered_transaction_ids_before_commit"] = recovery.recovered_transaction_ids
        return summary


def prepare_paper_ledger_transaction(
    *,
    ledger_root: Path,
    timestamp: str,
    generated_at: str,
    jsonl_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    json_documents: Mapping[str, Mapping[str, Any]],
) -> PaperLedgerTransaction:
    ledger_root = ledger_root.resolve()
    safe_timestamp = re.sub(r"[^A-Za-z0-9_.-]+", "_", timestamp).strip("_") or "unknown"
    transaction_id = f"{safe_timestamp}-{uuid.uuid4().hex}"
    transaction_dir = ledger_root / ".transactions" / transaction_id
    staged_dir = transaction_dir / "staged"
    backup_dir = transaction_dir / "backup"
    staged_dir.mkdir(parents=True, exist_ok=False)
    backup_dir.mkdir(parents=True, exist_ok=False)

    after_by_path: dict[str, bytes] = {}
    for relative_path, rows in jsonl_rows.items():
        normalized = _normalized_relative_path(relative_path)
        final_path = ledger_root / normalized
        before = final_path.read_bytes() if final_path.exists() else b""
        after_by_path[normalized] = _append_jsonl_bytes(before, rows)
    for relative_path, document in json_documents.items():
        normalized = _normalized_relative_path(relative_path)
        if normalized in after_by_path:
            raise ValueError(f"duplicate paper ledger transaction path: {normalized}")
        after_by_path[normalized] = _json_bytes(document)

    operations: list[dict[str, Any]] = []
    for index, (relative_path, after_bytes) in enumerate(sorted(after_by_path.items())):
        final_path = ledger_root / relative_path
        before_bytes = final_path.read_bytes() if final_path.exists() else b""
        staged_rel = f"staged/{index:02d}.new"
        backup_rel = f"backup/{index:02d}.bak"
        (transaction_dir / staged_rel).write_bytes(after_bytes)
        (transaction_dir / backup_rel).write_bytes(before_bytes)
        operations.append(
            {
                "relative_path": relative_path,
                "existed_before": final_path.exists(),
                "before_sha256": _sha256(before_bytes),
                "after_sha256": _sha256(after_bytes),
                "before_size": len(before_bytes),
                "after_size": len(after_bytes),
                "staged_path": staged_rel,
                "backup_path": backup_rel,
            }
        )

    journal = {
        "schema_version": TRANSACTION_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "timestamp": timestamp,
        "generated_at": generated_at,
        "status": "PREPARED",
        "ledger_root": ledger_root.as_posix(),
        "operations": operations,
        "rollback_blockers": [],
    }
    transaction = PaperLedgerTransaction(
        ledger_root=ledger_root,
        transaction_id=transaction_id,
        transaction_dir=transaction_dir,
        journal=journal,
    )
    _atomic_write_json(transaction.journal_path, journal)
    return transaction


def recover_incomplete_paper_ledger_transactions(ledger_root: Path) -> PaperLedgerRecoveryResult:
    ledger_root = ledger_root.resolve()
    transactions_root = ledger_root / ".transactions"
    if not transactions_root.exists():
        return PaperLedgerRecoveryResult(status="clean", recovered_transaction_ids=[], blockers=[])
    recovered: list[str] = []
    blockers: list[str] = []
    for transaction_dir in sorted(path for path in transactions_root.iterdir() if path.is_dir()):
        journal_path = transaction_dir / "transaction.json"
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            blockers.append(f"transaction_journal_unreadable:{transaction_dir.name}:{type(exc).__name__}")
            continue
        if not isinstance(journal, Mapping) or journal.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
            blockers.append(f"transaction_journal_schema_invalid:{transaction_dir.name}")
            continue
        status = str(journal.get("status", ""))
        if status in TERMINAL_STATUSES:
            continue
        if status not in PENDING_STATUSES:
            blockers.append(f"transaction_status_invalid:{transaction_dir.name}:{status}")
            continue
        transaction = PaperLedgerTransaction(
            ledger_root=ledger_root,
            transaction_id=str(journal.get("transaction_id") or transaction_dir.name),
            transaction_dir=transaction_dir,
            journal=dict(journal),
        )
        if transaction.rollback():
            recovered.append(transaction.transaction_id)
        else:
            blockers.extend(str(item) for item in transaction.journal.get("rollback_blockers", []))
    status = "blocked" if blockers else ("recovered" if recovered else "clean")
    return PaperLedgerRecoveryResult(status=status, recovered_transaction_ids=recovered, blockers=blockers)


def _normalized_relative_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe paper ledger path: {value}")
    return path.as_posix()


def _append_jsonl_bytes(before: bytes, rows: Sequence[Mapping[str, Any]]) -> bytes:
    prefix = before
    if prefix and not prefix.endswith(b"\n"):
        prefix += b"\n"
    appended = b"".join(
        (json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        for row in rows
    )
    return prefix + appended


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_replace_bytes(path, _json_bytes(payload))


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
