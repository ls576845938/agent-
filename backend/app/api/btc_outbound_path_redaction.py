from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import unquote, urlsplit


REDACTED_PHYSICAL_PATH = "[redacted-physical-path]"

_WINDOWS_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_UNC_ABSOLUTE = re.compile(r"^(?:\\\\|//)[^\\/]+[\\/][^\\/]+")
_FILE_URI_FULL = re.compile(r"^file://[^\r\n]+$", re.IGNORECASE)
_EMBEDDED_PATH_TOKEN = re.compile(
    r"(?P<uri>"
    r"(?<![A-Za-z0-9+._-])"
    r"[A-Za-z][A-Za-z0-9+.-]*://"
    r"[^\s,;'\"<>()[\]{}]+"
    r")"
    r"|(?P<drive>"
    r"(?<![A-Za-z0-9._~-])"
    r"[A-Za-z]:[\\/]"
    r"[^\s,;'\"<>()[\]{}]+"
    r")"
    r"|(?P<unc>"
    r"(?<![A-Za-z0-9._~/-])"
    r"(?:\\\\|//)"
    r"[^\\/\s,;'\"<>()[\]{}]+[\\/]"
    r"[^\s,;'\"<>()[\]{}]+"
    r")"
    r"|(?P<posix>"
    r"(?<![A-Za-z0-9._~/-])"
    r"/(?!/)"
    r"[^\s,;'\"<>()[\]{}]+"
    r")"
)
_PATH_KEYS = frozenset(
    {
        "dir",
        "dirs",
        "file",
        "files",
        "output",
        "outputs",
        "path",
        "paths",
        "root",
        "roots",
        "source_path",
        "source_paths",
        "source_report",
        "source_reports",
    }
)
_PATH_KEY_SUFFIXES = (
    "_dir",
    "_dirs",
    "_file",
    "_files",
    "_path",
    "_paths",
    "_root",
    "_roots",
)
_LOGICAL_ROUTE_ROOTS = ("/api", "/research")
_SAFE_NETWORK_URI_SCHEMES = frozenset(
    {"ftp", "ftps", "gs", "http", "https", "s3", "ws", "wss"}
)


class BtcOutboundPathRedactionError(RuntimeError):
    """Raised when a BTC payload cannot be sanitized without data loss."""


def sanitize_btc_outbound_payload(
    value: Any,
    *,
    repo_root: os.PathLike[str] | str,
    provenance_roots: Mapping[str, os.PathLike[str] | str] | None = None,
) -> Any:
    """Return a JSON-compatible BTC payload without physical host paths.

    Absolute paths inside ``repo_root`` become repository-relative labels.
    Explicit external roots become labels under their configured logical name.
    Other absolute paths are replaced with a fixed redaction marker.
    """

    roots = [_provenance_root("", repo_root)]
    for label, root in (provenance_roots or {}).items():
        roots.append(_provenance_root(str(label), root))
    return _sanitize(value, roots=tuple(roots), path_context=False)


def _sanitize(
    value: Any,
    *,
    roots: tuple[tuple[str, PurePath], ...],
    path_context: bool,
) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            child_path_context = path_context or (
                isinstance(key, str) and _is_path_key(key)
            )
            sanitized_key = (
                _sanitize_string(key, roots=roots, path_context=path_context)
                if isinstance(key, str)
                else key
            )
            if sanitized_key in sanitized:
                raise BtcOutboundPathRedactionError(
                    "btc_outbound_path_key_collision_fail_closed"
                )
            sanitized[sanitized_key] = _sanitize(
                item,
                roots=roots,
                path_context=child_path_context,
            )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize(item, roots=roots, path_context=path_context)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _sanitize(item, roots=roots, path_context=path_context)
            for item in value
        )
    if isinstance(value, os.PathLike):
        return _sanitize_string(
            os.fspath(value),
            roots=roots,
            path_context=True,
        )
    if isinstance(value, str):
        return _sanitize_string(
            value,
            roots=roots,
            path_context=path_context,
        )
    return value


def _sanitize_string(
    value: str,
    *,
    roots: tuple[tuple[str, PurePath], ...],
    path_context: bool,
) -> str:
    candidate = _absolute_pure_path(value)
    if candidate is None:
        redacted = _redact_embedded_physical_paths(value, roots=roots)
        if redacted != value:
            return redacted
        if path_context and "\\" in value:
            return value.replace("\\", "/")
        return value
    if (
        isinstance(candidate, PurePosixPath)
        and not path_context
        and _is_logical_route(value.strip())
    ):
        # API route labels are logical identifiers, not physical host paths.
        return value
    return _logicalize_absolute_path(candidate, roots=roots)


def _logicalize_absolute_path(
    candidate: PurePath,
    *,
    roots: tuple[tuple[str, PurePath], ...],
) -> str:
    for label, root in roots:
        if type(candidate) is not type(root):
            continue
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        relative_label = relative.as_posix()
        if relative_label == ".":
            return label or "."
        return f"{label}/{relative_label}" if label else relative_label
    return REDACTED_PHYSICAL_PATH


def _is_path_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _PATH_KEYS or normalized.endswith(_PATH_KEY_SUFFIXES)


def _provenance_root(
    label: str,
    root: os.PathLike[str] | str,
) -> tuple[str, PurePath]:
    normalized_label = label.strip().replace("\\", "/").strip("/")
    if normalized_label:
        label_path = PurePosixPath(normalized_label)
        if label_path.is_absolute() or ".." in label_path.parts:
            raise BtcOutboundPathRedactionError(
                "btc_outbound_provenance_label_invalid_fail_closed"
            )
    pure_root = _absolute_pure_path(os.fspath(root))
    if pure_root is None:
        raise BtcOutboundPathRedactionError(
            "btc_outbound_provenance_root_not_absolute_fail_closed"
        )
    return normalized_label, pure_root


def _absolute_pure_path(value: str) -> PurePath | None:
    normalized = value.strip()
    if _FILE_URI_FULL.fullmatch(normalized):
        normalized = _path_from_file_uri(normalized)
    if _WINDOWS_DRIVE_ABSOLUTE.match(normalized) or _WINDOWS_UNC_ABSOLUTE.match(
        normalized
    ):
        candidate = PureWindowsPath(normalized)
        return _lexically_normalize(candidate) if candidate.is_absolute() else None
    if normalized.startswith("/"):
        candidate = PurePosixPath(normalized)
        return _lexically_normalize(candidate) if candidate.is_absolute() else None
    return None


def _lexically_normalize(path: PurePath) -> PurePath:
    """Collapse dot segments without filesystem access or symlink resolution."""

    if not path.is_absolute():
        raise BtcOutboundPathRedactionError(
            "btc_outbound_path_not_absolute_fail_closed"
        )
    stack: list[str] = []
    for segment in path.parts[1:]:
        if segment in ("", "."):
            continue
        if segment == "..":
            if stack:
                stack.pop()
            continue
        stack.append(segment)
    return type(path)(path.anchor, *stack)


def _path_from_file_uri(value: str) -> str:
    parsed = urlsplit(value)
    authority = unquote(parsed.netloc)
    path = unquote(parsed.path)
    if authority and authority.lower() != "localhost":
        return f"//{authority}{path}"
    if re.match(r"^/[A-Za-z]:[\\/]", path):
        return path[1:]
    return path


def _redact_embedded_physical_paths(
    value: str,
    *,
    roots: tuple[tuple[str, PurePath], ...],
) -> str:
    quoted_redacted = _redact_quoted_physical_paths(value, roots=roots)
    sanitized: list[str] = []
    cursor = 0
    for match in _EMBEDDED_PATH_TOKEN.finditer(quoted_redacted):
        if match.start() < cursor:
            continue
        token = match.group(0)
        sensitive = True
        if match.lastgroup == "uri":
            scheme = token.split(":", 1)[0].lower()
            if scheme in _SAFE_NETWORK_URI_SCHEMES:
                replacement = token
                sensitive = False
            elif scheme != "file":
                replacement = (
                    f"{token.split(':', 1)[0]}:{REDACTED_PHYSICAL_PATH}"
                )
            else:
                replacement = _logicalize_path_token(token, roots=roots)
        elif match.lastgroup == "posix" and _is_logical_route(token):
            replacement = token
            sensitive = False
        else:
            replacement = _logicalize_path_token(token, roots=roots)

        sanitized.append(quoted_redacted[cursor : match.start()])
        sanitized.append(replacement)
        cursor = (
            _first_line_break_index(quoted_redacted, match.end())
            if sensitive
            else match.end()
        )
    sanitized.append(quoted_redacted[cursor:])
    return "".join(sanitized)


def _redact_quoted_physical_paths(
    value: str,
    *,
    roots: tuple[tuple[str, PurePath], ...],
) -> str:
    """Redact a complete physical path delimited by matching quotes.

    Matching quotes provide an unambiguous boundary for paths containing spaces.
    An unmatched quote followed immediately by an absolute path is fail-closed:
    the path-bearing remainder is removed because no safe closing boundary exists.
    """

    sanitized: list[str] = []
    cursor = 0
    scan_from = 0
    while scan_from < len(value):
        quote_index = _next_quote_index(value, scan_from)
        if quote_index < 0:
            break
        quote = value[quote_index]
        closing_index = _matching_quote_index(value, quote_index, quote)
        token_end = (
            closing_index
            if closing_index >= 0
            else _first_line_break_index(value, quote_index + 1)
        )
        token = value[quote_index + 1 : token_end]
        replacement = _quoted_path_replacement(token, roots=roots)
        if replacement is None:
            if closing_index < 0:
                if token_end >= len(value):
                    break
                scan_from = token_end
                continue
            scan_from = closing_index + 1
            continue

        sanitized.append(value[cursor : quote_index + 1])
        sanitized.append(replacement)
        if closing_index < 0:
            cursor = token_end
            scan_from = token_end
            continue
        sanitized.append(quote)
        cursor = closing_index + 1
        scan_from = closing_index + 1

    sanitized.append(value[cursor:])
    return "".join(sanitized)


def _quoted_path_replacement(
    token: str,
    *,
    roots: tuple[tuple[str, PurePath], ...],
) -> str | None:
    normalized = token.strip()
    if _is_logical_route(normalized):
        return None
    candidate = _absolute_pure_path(normalized)
    if candidate is None:
        return None
    return _logicalize_absolute_path(candidate, roots=roots)


def _next_quote_index(value: str, start: int) -> int:
    single_index = value.find("'", start)
    double_index = value.find('"', start)
    if single_index < 0:
        return double_index
    if double_index < 0:
        return single_index
    return min(single_index, double_index)


def _matching_quote_index(value: str, opening_index: int, quote: str) -> int:
    line_end = _first_line_break_index(value, opening_index + 1)
    cursor = opening_index + 1
    while cursor < line_end:
        cursor = value.find(quote, cursor)
        if cursor < 0 or cursor >= line_end:
            return -1
        backslashes = 0
        previous = cursor - 1
        while previous > opening_index and value[previous] == "\\":
            backslashes += 1
            previous -= 1
        if backslashes % 2 == 0:
            return cursor
        cursor += 1
    return -1


def _first_line_break_index(value: str, start: int) -> int:
    carriage_return = value.find("\r", start)
    line_feed = value.find("\n", start)
    candidates = [
        index
        for index in (carriage_return, line_feed)
        if index >= 0
    ]
    return min(candidates) if candidates else len(value)


def _logicalize_path_token(
    token: str,
    *,
    roots: tuple[tuple[str, PurePath], ...],
) -> str:
    candidate = _absolute_pure_path(token)
    if candidate is None:
        return REDACTED_PHYSICAL_PATH
    return _logicalize_absolute_path(candidate, roots=roots)


def _is_logical_route(value: str) -> bool:
    return any(
        value == root or value.startswith(f"{root}/")
        for root in _LOGICAL_ROUTE_ROOTS
    )
