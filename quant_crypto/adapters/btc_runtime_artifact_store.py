"""Fail-closed external runtime-artifact storage for the BTC domain."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import uuid
from typing import Any, Iterator, Mapping, TypeVar


ENVIRONMENT_VARIABLE = "QS_BTC_RUNTIME_ARTIFACT_ROOT"
OWNER_MARKER_NAME = ".qs_btc_runtime_artifact_root_owner.json"
OWNER_MARKER_SCHEMA_VERSION = "qs_btc_runtime_artifact_root_owner_v1"
OWNER_DOMAIN = "btc"
LOGICAL_PREFIX = "artifacts"
ROOT_SEMANTICS = "physical_root_is_direct_artifacts_root_v1"
WRITER_LOCK_NAME = ".qs_btc_runtime_artifact_writer.lock"
REPOSITORY_IDENTITY_SCHEMA_VERSION = "qs_git_common_dir_identity_v1"


class BTCRuntimeArtifactStoreError(RuntimeError):
    """Raised when artifact-root configuration or access fails closed."""


ReaderT = TypeVar("ReaderT", bound="BTCRuntimeArtifactReader")


@dataclass(frozen=True)
class BTCRuntimeArtifactReader:
    """Read-only resolver for logical ``artifacts/...`` paths."""

    source_repo_root: Path
    artifact_root: Path
    repository_identity: str
    worktree_roots: tuple[Path, ...]

    @classmethod
    def from_environment(
        cls: type[ReaderT],
        *,
        source_repo_root: Path,
        environment: Mapping[str, str] | None = None,
        repository_identity: str | None = None,
        worktree_roots: tuple[Path, ...] | None = None,
    ) -> ReaderT:
        source = source_repo_root.resolve()
        values = os.environ if environment is None else environment
        raw_root = str(values.get(ENVIRONMENT_VARIABLE, "") or "").strip()
        if not raw_root:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_env_missing"
            )
        configured = Path(raw_root)
        if not configured.is_absolute():
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_must_be_absolute"
            )
        _reject_reparse_chain(configured)
        try:
            artifact_root = configured.resolve(strict=True)
        except OSError as exc:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_missing_or_unreadable"
            ) from exc
        if not artifact_root.is_dir():
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_not_directory"
            )

        identity = repository_identity or repository_identity_for_source(source)
        if not _valid_repository_identity(identity):
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_repository_identity_invalid"
            )
        roots = tuple(
            path.resolve()
            for path in (
                worktree_roots
                if worktree_roots is not None
                else git_worktree_roots(source)
            )
        )
        if not roots:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_git_worktrees_unavailable"
            )
        if any(
            _is_within(artifact_root, worktree)
            or _is_within(worktree, artifact_root)
            for worktree in roots
        ):
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_inside_git_worktree"
            )
        _validate_owner_marker(artifact_root, identity)
        return cls(
            source_repo_root=source,
            artifact_root=artifact_root,
            repository_identity=identity,
            worktree_roots=roots,
        )

    def resolve(
        self,
        logical_path: Path | str,
        *,
        require_file: bool = False,
    ) -> Path:
        _validate_owner_marker(self.artifact_root, self.repository_identity)
        path = _resolve_logical_path(self.artifact_root, logical_path)
        if require_file and not path.is_file():
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_file_missing"
            )
        return path

    def read_bytes(self, logical_path: Path | str) -> bytes:
        path = self.resolve(logical_path, require_file=True)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_file_unreadable"
            ) from exc

    def read_json(self, logical_path: Path | str) -> dict[str, Any]:
        try:
            payload = json.loads(self.read_bytes(logical_path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_json_invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_json_not_object"
            )
        return payload

    def sha256(self, logical_path: Path | str) -> str:
        return hashlib.sha256(self.read_bytes(logical_path)).hexdigest()

    def logical_path(self, physical_path: Path) -> Path:
        resolved = physical_path.resolve(strict=False)
        try:
            relative = resolved.relative_to(self.artifact_root)
        except ValueError as exc:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_physical_path_outside_root"
            ) from exc
        if not relative.parts:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_physical_path_is_root"
            )
        return Path(LOGICAL_PREFIX, *relative.parts)


@dataclass(frozen=True)
class BTCRuntimeArtifactWriter(BTCRuntimeArtifactReader):
    """Reader plus an explicit, process-wide exclusive writer session."""

    @contextmanager
    def exclusive(self) -> Iterator["BTCRuntimeArtifactWriteSession"]:
        _validate_owner_marker(self.artifact_root, self.repository_identity)
        lock_path = self.artifact_root / WRITER_LOCK_NAME
        owner_token = uuid.uuid4().hex
        owner = {
            "schema_version": "qs_btc_runtime_artifact_writer_lock_v1",
            "owner_domain": OWNER_DOMAIN,
            "repository_identity": self.repository_identity,
            "pid": os.getpid(),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "owner_token": owner_token,
        }
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_writer_lock_held"
            ) from exc
        except OSError as exc:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_writer_lock_unavailable"
            ) from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(owner, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            yield BTCRuntimeArtifactWriteSession(
                writer=self,
                owner_token=owner_token,
            )
        finally:
            try:
                current = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                current = {}
            if current.get("owner_token") == owner_token:
                lock_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class BTCRuntimeArtifactWriteSession:
    writer: BTCRuntimeArtifactWriter
    owner_token: str

    def resolve(self, logical_path: Path | str) -> Path:
        self._assert_lock_owned()
        return self.writer.resolve(logical_path)

    def write_json_atomic(
        self,
        logical_path: Path | str,
        payload: Mapping[str, Any],
    ) -> Path:
        encoded = (
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        return self.write_bytes_atomic(logical_path, encoded)

    def write_bytes_atomic(
        self,
        logical_path: Path | str,
        payload: bytes,
    ) -> Path:
        self._assert_lock_owned()
        destination = self.writer.resolve(logical_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = self.writer.resolve(logical_path)
        temporary = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _assert_lock_owned(self) -> None:
        lock_path = self.writer.artifact_root / WRITER_LOCK_NAME
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_writer_lock_lost"
            ) from exc
        if current.get("owner_token") != self.owner_token:
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_writer_lock_lost"
            )


def build_btc_runtime_artifact_owner_marker(
    repository_identity: str,
) -> dict[str, str]:
    if not _valid_repository_identity(repository_identity):
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_repository_identity_invalid"
        )
    return {
        "schema_version": OWNER_MARKER_SCHEMA_VERSION,
        "owner_domain": OWNER_DOMAIN,
        "repository_identity": repository_identity,
        "logical_prefix": f"{LOGICAL_PREFIX}/",
        "root_semantics": ROOT_SEMANTICS,
    }


def repository_identity_for_source(source_repo_root: Path) -> str:
    source = source_repo_root.resolve()
    raw = _git_text(
        source,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    if not raw:
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_repository_identity_unavailable"
        )
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = source / common_dir
    canonical = str(common_dir.resolve()).replace("\\", "/").casefold()
    digest = hashlib.sha256(
        (
            REPOSITORY_IDENTITY_SCHEMA_VERSION
            + "\0"
            + canonical
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def git_worktree_roots(source_repo_root: Path) -> tuple[Path, ...]:
    raw = _git_text(source_repo_root.resolve(), "worktree", "list", "--porcelain")
    roots: list[Path] = []
    for line in raw.splitlines():
        if line.startswith("worktree "):
            value = line[len("worktree ") :].strip()
            if value:
                roots.append(Path(value).resolve())
    return tuple(roots)


def _validate_owner_marker(
    artifact_root: Path,
    repository_identity: str,
) -> None:
    marker_path = artifact_root / OWNER_MARKER_NAME
    _reject_reparse_chain(marker_path)
    try:
        resolved_marker = marker_path.resolve(strict=True)
    except OSError as exc:
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_owner_marker_missing"
        ) from exc
    if not _is_within(resolved_marker, artifact_root):
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_owner_marker_path_escape"
        )
    try:
        payload = json.loads(resolved_marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_owner_marker_schema_invalid"
        ) from exc
    expected = build_btc_runtime_artifact_owner_marker(repository_identity)
    if not isinstance(payload, dict) or set(payload) != set(expected):
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_owner_marker_schema_invalid"
        )
    if payload.get("repository_identity") != repository_identity:
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_owner_marker_repository_mismatch"
        )
    if payload != expected:
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_owner_marker_schema_invalid"
        )


def _resolve_logical_path(
    artifact_root: Path,
    logical_path: Path | str,
) -> Path:
    _reject_reparse_chain(artifact_root)
    raw = (
        logical_path.as_posix()
        if isinstance(logical_path, Path)
        else str(logical_path)
    )
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or Path(raw).is_absolute()
        or raw.startswith("/")
        or re.match(r"^[A-Za-z]:/", raw)
    ):
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_logical_path_invalid"
        )
    pure = PurePosixPath(raw)
    if (
        pure.as_posix() != raw
        or len(pure.parts) < 2
        or pure.parts[0] != LOGICAL_PREFIX
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_logical_path_invalid"
        )
    candidate = artifact_root.joinpath(*pure.parts[1:])
    _reject_reparse_chain(candidate)
    resolved = candidate.resolve(strict=False)
    if not _is_within(resolved, artifact_root):
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_path_escape"
        )
    return resolved


def _reject_reparse_chain(path: Path) -> None:
    current = Path(os.path.abspath(str(path)))
    while True:
        if os.path.lexists(current) and _is_reparse_point(current):
            raise BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_reparse_path_rejected"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(
        attributes
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _valid_repository_identity(value: str) -> bool:
    return bool(
        re.fullmatch(r"sha256:[0-9a-f]{64}", str(value or ""))
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _git_text(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_git_metadata_unavailable"
        ) from exc
    if result.returncode != 0:
        raise BTCRuntimeArtifactStoreError(
            "btc_runtime_artifact_git_metadata_unavailable"
        )
    return result.stdout.strip()


__all__ = [
    "ENVIRONMENT_VARIABLE",
    "OWNER_MARKER_NAME",
    "OWNER_MARKER_SCHEMA_VERSION",
    "BTCRuntimeArtifactReader",
    "BTCRuntimeArtifactStoreError",
    "BTCRuntimeArtifactWriteSession",
    "BTCRuntimeArtifactWriter",
    "build_btc_runtime_artifact_owner_marker",
    "git_worktree_roots",
    "repository_identity_for_source",
]
