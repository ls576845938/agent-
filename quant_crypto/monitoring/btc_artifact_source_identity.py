"""Fail-closed source identity contract for BTC runtime report artifacts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


_FULL_HEAD_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{12}$")


class BTCArtifactSourceIdentityError(RuntimeError):
    """Raised when a BTC runtime artifact cannot prove its source identity."""


def build_btc_artifact_source_identity(repo_root: Path) -> dict[str, str]:
    """Resolve the exact Git HEAD and its canonical 12-character display prefix."""

    root = repo_root.resolve()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_git_head_unavailable"
        ) from exc
    if completed.returncode != 0:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_git_head_unavailable"
        )

    source_head = completed.stdout.strip()
    if _FULL_HEAD_PATTERN.fullmatch(source_head) is None:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_source_head_invalid"
        )
    return {"source_head": source_head, "commit": source_head[:12]}


def validate_btc_artifact_source_identity(
    payload: Mapping[str, Any],
    *,
    expected_current_head: str,
) -> dict[str, str]:
    """Validate full HEAD, display prefix, and binding to the expected current HEAD."""

    if _FULL_HEAD_PATTERN.fullmatch(expected_current_head) is None:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_expected_current_head_invalid"
        )

    source_head = payload.get("source_head")
    if not isinstance(source_head, str) or _FULL_HEAD_PATTERN.fullmatch(source_head) is None:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_source_head_invalid"
        )

    commit = payload.get("commit")
    if not isinstance(commit, str) or _COMMIT_PATTERN.fullmatch(commit) is None:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_commit_invalid"
        )
    if commit != source_head[:12]:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_commit_prefix_mismatch"
        )
    if source_head != expected_current_head:
        raise BTCArtifactSourceIdentityError(
            "btc_artifact_source_identity_expected_current_head_mismatch"
        )
    return {"source_head": source_head, "commit": commit}
