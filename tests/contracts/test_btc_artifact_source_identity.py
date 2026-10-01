from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from quant_crypto.monitoring.btc_artifact_source_identity import (
    BTCArtifactSourceIdentityError,
    build_btc_artifact_source_identity,
    validate_btc_artifact_source_identity,
)
from scripts import (
    build_btc_true_scalping_l2_aligned_capture_quality_report as l2_builder,
)
from scripts import (
    build_btc_true_scalping_ws_order_book_replay_report as replay_builder,
)
from scripts import (
    build_btc_true_scalping_ws_reconnect_resync_policy_report as reconnect_builder,
)


FULL_HEAD = "0123456789abcdef0123456789abcdef01234567"
OTHER_HEAD = "fedcba9876543210fedcba9876543210fedcba98"


def test_build_source_identity_uses_exact_full_head_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path]] = []

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs["cwd"]))
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{FULL_HEAD}\n", stderr="")

    monkeypatch.setattr(
        "quant_crypto.monitoring.btc_artifact_source_identity.subprocess.run",
        _run,
    )

    identity = build_btc_artifact_source_identity(tmp_path)

    assert identity == {"source_head": FULL_HEAD, "commit": FULL_HEAD[:12]}
    assert calls == [(["git", "rev-parse", "HEAD"], tmp_path.resolve())]


@pytest.mark.parametrize(
    "stdout",
    [
        "a" * 9,
        "a" * 11,
        "a" * 13,
        "unknown",
        "g" * 40,
        "A" * 40,
    ],
)
def test_build_source_identity_rejects_noncanonical_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdout: str,
) -> None:
    monkeypatch.setattr(
        "quant_crypto.monitoring.btc_artifact_source_identity.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=stdout,
            stderr="",
        ),
    )

    with pytest.raises(
        BTCArtifactSourceIdentityError,
        match="btc_artifact_source_identity_source_head_invalid",
    ):
        build_btc_artifact_source_identity(tmp_path)


def test_build_source_identity_fails_closed_on_git_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "quant_crypto.monitoring.btc_artifact_source_identity.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=128,
            stdout="",
            stderr="fatal",
        ),
    )

    with pytest.raises(
        BTCArtifactSourceIdentityError,
        match="btc_artifact_source_identity_git_head_unavailable",
    ):
        build_btc_artifact_source_identity(tmp_path)


def test_build_source_identity_fails_closed_when_git_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("git unavailable")

    monkeypatch.setattr(
        "quant_crypto.monitoring.btc_artifact_source_identity.subprocess.run",
        _raise,
    )

    with pytest.raises(
        BTCArtifactSourceIdentityError,
        match="btc_artifact_source_identity_git_head_unavailable",
    ):
        build_btc_artifact_source_identity(tmp_path)


def test_validate_source_identity_accepts_canonical_current_head() -> None:
    identity = {"source_head": FULL_HEAD, "commit": FULL_HEAD[:12]}

    assert validate_btc_artifact_source_identity(
        identity,
        expected_current_head=FULL_HEAD,
    ) == identity


@pytest.mark.parametrize("commit", ["a" * 9, "a" * 11, "a" * 13, "unknown", "A" * 12])
def test_validate_source_identity_rejects_noncanonical_commit(commit: str) -> None:
    with pytest.raises(
        BTCArtifactSourceIdentityError,
        match="btc_artifact_source_identity_commit_invalid",
    ):
        validate_btc_artifact_source_identity(
            {"source_head": FULL_HEAD, "commit": commit},
            expected_current_head=FULL_HEAD,
        )


def test_validate_source_identity_rejects_commit_prefix_mismatch() -> None:
    with pytest.raises(
        BTCArtifactSourceIdentityError,
        match="btc_artifact_source_identity_commit_prefix_mismatch",
    ):
        validate_btc_artifact_source_identity(
            {"source_head": FULL_HEAD, "commit": "f" * 12},
            expected_current_head=FULL_HEAD,
        )


def test_validate_source_identity_rejects_expected_current_head_mismatch() -> None:
    with pytest.raises(
        BTCArtifactSourceIdentityError,
        match="btc_artifact_source_identity_expected_current_head_mismatch",
    ):
        validate_btc_artifact_source_identity(
            {"source_head": FULL_HEAD, "commit": FULL_HEAD[:12]},
            expected_current_head=OTHER_HEAD,
        )


@pytest.mark.parametrize(
    ("module", "build"),
    [
        (
            l2_builder,
            l2_builder.build_btc_true_scalping_l2_aligned_capture_quality_report,
        ),
        (
            replay_builder,
            replay_builder.build_btc_true_scalping_ws_order_book_replay_report,
        ),
        (
            reconnect_builder,
            reconnect_builder.build_btc_true_scalping_ws_reconnect_resync_policy_report,
        ),
    ],
)
def test_builder_identity_validation_failure_does_not_lock_or_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module: Any,
    build: Callable[..., dict[str, Any]],
) -> None:
    existing_evidence = tmp_path / "existing-evidence.json"
    existing_evidence.write_text('{"sentinel":"unchanged"}', encoding="utf-8")
    writer = _LockTrackingWriter()
    reader = SimpleNamespace(resolve=lambda logical: tmp_path / "missing" / Path(logical).name)
    monkeypatch.setattr(
        module,
        "build_btc_artifact_source_identity",
        lambda root: {"source_head": FULL_HEAD, "commit": FULL_HEAD[:12]},
    )

    def _reject(*args: Any, **kwargs: Any) -> dict[str, str]:
        raise BTCArtifactSourceIdentityError("btc_artifact_source_identity_commit_prefix_mismatch")

    monkeypatch.setattr(module, "validate_btc_artifact_source_identity", _reject)

    with pytest.raises(
        BTCArtifactSourceIdentityError,
        match="btc_artifact_source_identity_commit_prefix_mismatch",
    ):
        build(
            repo_root=tmp_path,
            generated_at="2026-06-20T00:00:00Z",
            artifact_reader=reader,
            artifact_writer=writer,
        )

    assert writer.exclusive_calls == 0
    assert existing_evidence.read_text(encoding="utf-8") == '{"sentinel":"unchanged"}'


class _LockTrackingWriter:
    def __init__(self) -> None:
        self.exclusive_calls = 0

    def exclusive(self) -> Any:
        self.exclusive_calls += 1
        raise AssertionError("artifact write lock must not be acquired")
