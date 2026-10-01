#!/usr/bin/env python3
"""Provision an empty, repository-bound external BTC artifact root."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.adapters.btc_runtime_artifact_store import (  # noqa: E402
    OWNER_MARKER_NAME,
    build_btc_runtime_artifact_owner_marker,
    git_worktree_roots,
    repository_identity_for_source,
)


class BTCRuntimeArtifactBootstrapError(RuntimeError):
    """Raised when root provisioning cannot complete without ambiguity."""


def bootstrap_btc_runtime_artifact_root(
    *,
    source_repo_root: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    if not source_repo_root.is_absolute():
        raise BTCRuntimeArtifactBootstrapError(
            "btc_runtime_artifact_bootstrap_source_root_must_be_absolute"
        )
    if not artifact_root.is_absolute():
        raise BTCRuntimeArtifactBootstrapError(
            "btc_runtime_artifact_bootstrap_artifact_root_must_be_absolute"
        )

    source = _strict_non_reparse_directory(
        source_repo_root,
        missing_error="btc_runtime_artifact_bootstrap_source_root_invalid",
    )
    target = _absolute_lexical_path(artifact_root)
    _reject_reparse_chain(target)
    resolved_target = target.resolve(strict=False)
    if _normalized_path(resolved_target) != _normalized_path(target):
        raise BTCRuntimeArtifactBootstrapError(
            "btc_runtime_artifact_bootstrap_path_escape"
        )

    worktrees = git_worktree_roots(source)
    if not worktrees:
        raise BTCRuntimeArtifactBootstrapError(
            "btc_runtime_artifact_bootstrap_git_worktrees_unavailable"
        )
    if any(
        _is_within(resolved_target, worktree.resolve())
        or _is_within(worktree.resolve(), resolved_target)
        for worktree in worktrees
    ):
        raise BTCRuntimeArtifactBootstrapError(
            "btc_runtime_artifact_bootstrap_root_overlaps_git_worktree"
        )

    root_created = False
    marker_created = False
    marker_path = target / OWNER_MARKER_NAME
    try:
        if os.path.lexists(target):
            if not target.is_dir():
                raise BTCRuntimeArtifactBootstrapError(
                    "btc_runtime_artifact_bootstrap_root_not_directory"
                )
            if any(target.iterdir()):
                raise BTCRuntimeArtifactBootstrapError(
                    "btc_runtime_artifact_bootstrap_root_not_empty"
                )
        else:
            parent = _strict_non_reparse_directory(
                target.parent,
                missing_error=(
                    "btc_runtime_artifact_bootstrap_parent_missing_or_invalid"
                ),
            )
            if _normalized_path(parent) != _normalized_path(
                target.parent.resolve(strict=True)
            ):
                raise BTCRuntimeArtifactBootstrapError(
                    "btc_runtime_artifact_bootstrap_path_escape"
                )
            target.mkdir(mode=0o700, parents=False, exist_ok=False)
            root_created = True

        _reject_reparse_chain(target)
        if _normalized_path(target.resolve(strict=True)) != _normalized_path(
            target
        ):
            raise BTCRuntimeArtifactBootstrapError(
                "btc_runtime_artifact_bootstrap_path_escape"
            )

        repository_identity = repository_identity_for_source(source)
        marker = build_btc_runtime_artifact_owner_marker(
            repository_identity
        )
        encoded = (
            json.dumps(
                marker,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(marker_path, flags, 0o600)
        except FileExistsError as exc:
            raise BTCRuntimeArtifactBootstrapError(
                "btc_runtime_artifact_bootstrap_marker_exists"
            ) from exc
        marker_created = True
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

        entries = list(target.iterdir())
        if entries != [marker_path]:
            raise BTCRuntimeArtifactBootstrapError(
                "btc_runtime_artifact_bootstrap_root_not_empty"
            )
        return {
            "status": "created",
            "artifact_root": str(target.resolve(strict=True)),
            "owner_marker": str(marker_path.resolve(strict=True)),
            "repository_identity": repository_identity,
        }
    except BTCRuntimeArtifactBootstrapError:
        _rollback_failed_bootstrap(
            target=target,
            marker_path=marker_path,
            marker_created=marker_created,
            root_created=root_created,
        )
        raise
    except OSError as exc:
        _rollback_failed_bootstrap(
            target=target,
            marker_path=marker_path,
            marker_created=marker_created,
            root_created=root_created,
        )
        raise BTCRuntimeArtifactBootstrapError(
            "btc_runtime_artifact_bootstrap_filesystem_failure"
        ) from exc


def _strict_non_reparse_directory(
    path: Path,
    *,
    missing_error: str,
) -> Path:
    lexical = _absolute_lexical_path(path)
    if not os.path.lexists(lexical) or not lexical.is_dir():
        raise BTCRuntimeArtifactBootstrapError(missing_error)
    _reject_reparse_chain(lexical)
    resolved = lexical.resolve(strict=True)
    if _normalized_path(resolved) != _normalized_path(lexical):
        raise BTCRuntimeArtifactBootstrapError(
            "btc_runtime_artifact_bootstrap_path_escape"
        )
    return resolved


def _reject_reparse_chain(path: Path) -> None:
    current = path
    while True:
        if os.path.lexists(current) and _is_reparse_point(current):
            raise BTCRuntimeArtifactBootstrapError(
                "btc_runtime_artifact_bootstrap_reparse_path_rejected"
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


def _absolute_lexical_path(path: Path) -> Path:
    if not path.is_absolute():
        return path
    return Path(os.path.abspath(str(path)))


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _rollback_failed_bootstrap(
    *,
    target: Path,
    marker_path: Path,
    marker_created: bool,
    root_created: bool,
) -> None:
    if marker_created:
        try:
            marker_path.unlink()
        except OSError:
            pass
    if root_created:
        try:
            target.rmdir()
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an empty external BTC runtime-artifact root and its "
            "repository-bound owner marker."
        )
    )
    parser.add_argument(
        "--source-repo-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = bootstrap_btc_runtime_artifact_root(
            source_repo_root=args.source_repo_root,
            artifact_root=args.artifact_root,
        )
    except BTCRuntimeArtifactBootstrapError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked_fail_closed",
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
