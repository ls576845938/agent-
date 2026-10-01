from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


class FileClosureEvidenceUnitOfWork:
    """Stage immutable BTC closure evidence and publish it atomically on commit."""

    def __init__(self, data_root: str) -> None:
        self._data_root = Path(data_root)
        self._pending: dict[Path, bytes] = {}
        self._temporary_paths: list[Path] = []
        self._committed = False

    def stage_candidate_evidence(self, *, run_id_prefix: str, payload: dict[str, Any]) -> str:
        if self._committed:
            raise RuntimeError("closure evidence unit of work is already committed")
        target = (
            self._data_root
            / "research"
            / "btc_closure_runs"
            / f"{run_id_prefix}_strict_evidence.json"
        )
        if target.exists():
            return str(target)
        serialized = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
        ).encode("utf-8")
        existing = self._pending.get(target)
        if existing is not None and existing != serialized:
            raise ValueError(f"conflicting staged BTC closure evidence: {target}")
        self._pending[target] = serialized
        return str(target)

    def commit(self) -> None:
        if self._committed:
            return

        installed: list[Path] = []
        try:
            staged: list[tuple[Path, Path]] = []
            for target, content in self._pending.items():
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    dir=target.parent,
                )
                temporary_path = Path(temporary_name)
                self._temporary_paths.append(temporary_path)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                staged.append((temporary_path, target))

            for temporary_path, target in staged:
                os.replace(temporary_path, target)
                installed.append(target)
                self._temporary_paths.remove(temporary_path)
        except Exception:
            for target in installed:
                target.unlink(missing_ok=True)
            self.rollback()
            raise

        self._committed = True
        self._pending.clear()

    def rollback(self) -> None:
        for temporary_path in self._temporary_paths:
            temporary_path.unlink(missing_ok=True)
        self._temporary_paths.clear()
        self._pending.clear()


def file_closure_evidence_uow_factory(data_root: str) -> FileClosureEvidenceUnitOfWork:
    return FileClosureEvidenceUnitOfWork(data_root)
