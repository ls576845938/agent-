from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from quant_shared.core.serialization import canonical_json_bytes, sha256_hex


@dataclass(frozen=True)
class PublishedEvidence:
    path: str
    sha256: str
    already_present: bool
    contract_version: str = "shared_published_evidence_v2"


class ImmutableEvidenceRepository(Protocol):
    def publish(self, path: Path | str, payload: Mapping[str, Any]) -> PublishedEvidence: ...

    def read(self, path: Path | str) -> bytes: ...

    def fingerprint(self, path: Path | str) -> str: ...


class FileEvidenceRepository:
    """Filesystem adapter that only permits idempotent immutable publication."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def publish(self, path: Path | str, payload: Mapping[str, Any]) -> PublishedEvidence:
        resolved = self._resolve(path)
        encoded = canonical_json_bytes(dict(payload)) + b"\n"
        digest = sha256_hex(encoded)
        if resolved.exists():
            if resolved.read_bytes() != encoded:
                raise FileExistsError(f"immutable evidence already exists with different bytes: {path}")
            return PublishedEvidence(self._relative(resolved), digest, True)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = resolved.with_name(f".{resolved.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, resolved)
        finally:
            temporary.unlink(missing_ok=True)
        return PublishedEvidence(self._relative(resolved), digest, False)

    def read(self, path: Path | str) -> bytes:
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise FileNotFoundError(path)
        return resolved.read_bytes()

    def fingerprint(self, path: Path | str) -> str:
        return sha256_hex(self.read(path))

    def _resolve(self, path: Path | str) -> Path:
        candidate = Path(path)
        resolved = candidate.resolve() if candidate.is_absolute() else (self._root / candidate).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(f"evidence path escapes repository root: {path}") from exc
        return resolved

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()
