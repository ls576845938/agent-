from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from quant_shared.core import canonical_payload_hash


ARTIFACT_PATH_REFERENCE_SCHEMA_VERSION = "us_artifact_path_reference_v1"
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:/")


def serialize_durable_artifact_path(
    path: str | Path,
    *,
    identity_root: str | Path,
) -> str:
    """Return a stable root-relative POSIX path for durable JSON identity."""

    normalized_path = _without_trailing_separator(_normalized_text(path))
    normalized_root = _without_trailing_separator(_normalized_text(identity_root))
    if not normalized_path or not normalized_root:
        raise ValueError("artifact path and identity_root are required")

    if _is_absolute(normalized_path):
        comparison_path = _comparison_text(normalized_path)
        comparison_root = _comparison_text(normalized_root)
        if comparison_root == "/":
            relative = normalized_path[1:]
        else:
            prefix = f"{comparison_root}/"
            if not comparison_path.startswith(prefix):
                raise ValueError("durable artifact path is outside identity_root")
            relative = normalized_path[len(normalized_root) + 1 :]
    else:
        relative = normalized_path
    return _validated_relative_path(relative)


def serialize_durable_artifact_locator(
    locator: str | Path,
    *,
    identity_root: str | Path,
) -> str:
    """Serialize a durable path plus an optional JSON-section fragment."""

    path_text, separator, fragment = str(locator or "").partition("#")
    serialized = serialize_durable_artifact_path(path_text, identity_root=identity_root)
    if not separator:
        return serialized
    fragment = fragment.strip()
    if not fragment or "\\" in fragment:
        raise ValueError("artifact locator fragment must be non-empty POSIX text")
    return f"{serialized}#{fragment}"


def resolve_durable_artifact_path(
    path: str,
    *,
    identity_root: str | Path,
) -> Path:
    """Resolve a durable relative path without accepting an absolute identity."""

    relative = _validated_relative_path(_normalized_text(path))
    root = Path(identity_root).resolve(strict=False)
    resolved = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("durable artifact path escapes identity_root") from exc
    return resolved


def durable_artifact_path_reference(
    path: str | Path,
    *,
    identity_root: str | Path,
) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_PATH_REFERENCE_SCHEMA_VERSION,
        "path_kind": "durable_relative",
        "path": serialize_durable_artifact_path(path, identity_root=identity_root),
        "stable_identity": True,
    }


def external_artifact_path_reference(path: str | Path) -> dict[str, Any]:
    """Describe an external absolute location that is not a stable identity."""

    normalized = _normalized_text(path)
    if not _is_absolute(normalized):
        raise ValueError("external artifact path must be absolute")
    return {
        "schema_version": ARTIFACT_PATH_REFERENCE_SCHEMA_VERSION,
        "path_kind": "external_absolute",
        "path": normalized,
        "stable_identity": False,
    }


def artifact_path_identity_hash(reference: Mapping[str, Any]) -> str:
    if reference.get("path_kind") != "durable_relative":
        raise ValueError("external absolute paths cannot be stable artifact identities")
    if reference.get("stable_identity") is not True:
        raise ValueError("stable_identity must be true for artifact identity hashing")
    return canonical_payload_hash(dict(reference))


def _normalized_text(value: str | Path) -> str:
    return str(value or "").strip().replace("\\", "/")


def _without_trailing_separator(value: str) -> str:
    return value if value == "/" else value.rstrip("/")


def _is_absolute(value: str) -> bool:
    return value.startswith("/") or bool(_WINDOWS_DRIVE.match(value))


def _comparison_text(value: str) -> str:
    return value.casefold() if _WINDOWS_DRIVE.match(value) else value


def _validated_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    if not normalized or _is_absolute(normalized):
        raise ValueError("durable artifact path must be non-empty and relative")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("durable artifact path contains an invalid segment")
    if any(":" in part for part in path.parts):
        raise ValueError("durable artifact path contains a drive or URI segment")
    return path.as_posix()
