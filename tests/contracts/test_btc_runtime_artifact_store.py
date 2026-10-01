from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import quant_crypto.adapters.btc_runtime_artifact_store as store_module
import scripts.bootstrap_btc_runtime_artifact_root as bootstrap_module
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactWriter,
    build_btc_runtime_artifact_owner_marker,
    repository_identity_for_source,
)
from scripts.bootstrap_btc_runtime_artifact_root import (
    BTCRuntimeArtifactBootstrapError,
    bootstrap_btc_runtime_artifact_root,
)


REPOSITORY_IDENTITY = "sha256:" + "a" * 64


def test_bootstrap_creates_exact_owner_marker_for_repository_identity(
    tmp_path: Path,
) -> None:
    source_root = Path.cwd().resolve()
    artifact_root = tmp_path / "new-runtime-artifacts"

    result = bootstrap_btc_runtime_artifact_root(
        source_repo_root=source_root,
        artifact_root=artifact_root,
    )

    identity = repository_identity_for_source(source_root)
    assert result == {
        "status": "created",
        "artifact_root": str(artifact_root.resolve()),
        "owner_marker": str(
            (artifact_root / OWNER_MARKER_NAME).resolve()
        ),
        "repository_identity": identity,
    }
    assert json.loads(
        (artifact_root / OWNER_MARKER_NAME).read_text(encoding="utf-8")
    ) == build_btc_runtime_artifact_owner_marker(identity)
    assert list(artifact_root.iterdir()) == [
        artifact_root / OWNER_MARKER_NAME
    ]


def test_bootstrap_accepts_existing_strictly_empty_directory(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "empty-runtime-artifacts"
    artifact_root.mkdir()

    bootstrap_btc_runtime_artifact_root(
        source_repo_root=Path.cwd().resolve(),
        artifact_root=artifact_root,
    )

    assert [path.name for path in artifact_root.iterdir()] == [
        OWNER_MARKER_NAME
    ]


def test_bootstrap_cli_requires_explicit_roots_and_creates_marker(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "cli-runtime-artifacts"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/bootstrap_btc_runtime_artifact_root.py",
            "--source-repo-root",
            str(Path.cwd().resolve()),
            "--artifact-root",
            str(artifact_root.resolve()),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "created"
    assert Path(payload["artifact_root"]) == artifact_root.resolve()
    assert (artifact_root / OWNER_MARKER_NAME).is_file()


def test_bootstrap_marker_creation_failure_rolls_back_created_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact_root = tmp_path / "failed-runtime-artifacts"
    real_open = bootstrap_module.os.open

    def fail_marker_open(path, flags, mode=0o777):
        if Path(path).name == OWNER_MARKER_NAME:
            raise OSError("injected_marker_creation_failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(bootstrap_module.os, "open", fail_marker_open)

    with pytest.raises(
        BTCRuntimeArtifactBootstrapError,
        match="btc_runtime_artifact_bootstrap_filesystem_failure",
    ):
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=Path.cwd().resolve(),
            artifact_root=artifact_root,
        )

    assert not artifact_root.exists()


@pytest.mark.parametrize(
    ("source_root", "artifact_root", "expected"),
    [
        (
            Path("."),
            Path("relative-runtime-artifacts"),
            "btc_runtime_artifact_bootstrap_source_root_must_be_absolute",
        ),
        (
            Path.cwd().resolve(),
            Path("relative-runtime-artifacts"),
            "btc_runtime_artifact_bootstrap_artifact_root_must_be_absolute",
        ),
        (
            Path.cwd().resolve(),
            Path.cwd().resolve() / "artifacts/bootstrap-must-not-create",
            "btc_runtime_artifact_bootstrap_root_overlaps_git_worktree",
        ),
    ],
)
def test_bootstrap_rejects_relative_or_worktree_paths(
    source_root: Path,
    artifact_root: Path,
    expected: str,
) -> None:
    with pytest.raises(BTCRuntimeArtifactBootstrapError, match=expected):
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=source_root,
            artifact_root=artifact_root,
        )


def test_bootstrap_rejects_nonempty_and_second_bootstrap(
    tmp_path: Path,
) -> None:
    source_root = Path.cwd().resolve()
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    sentinel = nonempty / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(
        BTCRuntimeArtifactBootstrapError,
        match="btc_runtime_artifact_bootstrap_root_not_empty",
    ):
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=source_root,
            artifact_root=nonempty,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve"

    artifact_root = tmp_path / "second-bootstrap"
    bootstrap_btc_runtime_artifact_root(
        source_repo_root=source_root,
        artifact_root=artifact_root,
    )
    before = (artifact_root / OWNER_MARKER_NAME).read_bytes()
    with pytest.raises(
        BTCRuntimeArtifactBootstrapError,
        match="btc_runtime_artifact_bootstrap_root_not_empty",
    ):
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=source_root,
            artifact_root=artifact_root,
        )
    assert (artifact_root / OWNER_MARKER_NAME).read_bytes() == before


def test_bootstrap_rejects_symlink_junction_or_reparse_root(
    tmp_path: Path,
) -> None:
    source_root = Path.cwd().resolve()
    target = tmp_path / "reparse-target"
    target.mkdir()
    link = tmp_path / "reparse-root"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    with pytest.raises(
        BTCRuntimeArtifactBootstrapError,
        match="btc_runtime_artifact_bootstrap_reparse_path_rejected",
    ):
        bootstrap_btc_runtime_artifact_root(
            source_repo_root=source_root,
            artifact_root=link,
        )
    assert not list(target.iterdir())


def test_reader_maps_artifacts_prefix_to_external_root_without_writes(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "worktrees" / "source"
    source_root.mkdir(parents=True)
    artifact_root = tmp_path / "runtime-artifacts"
    _write_marker(artifact_root)
    payload_path = artifact_root / "btc_gate_dashboard/latest/report.json"
    _write_json(payload_path, {"status": "blocked"})
    before = _tree_hash(artifact_root)

    reader = BTCRuntimeArtifactReader.from_environment(
        source_repo_root=source_root,
        environment={ENVIRONMENT_VARIABLE: str(artifact_root)},
        repository_identity=REPOSITORY_IDENTITY,
        worktree_roots=(source_root,),
    )

    assert reader.resolve("artifacts/btc_gate_dashboard/latest/report.json") == (
        payload_path.resolve()
    )
    assert reader.read_json(
        "artifacts/btc_gate_dashboard/latest/report.json"
    ) == {"status": "blocked"}
    assert _tree_hash(artifact_root) == before


def test_configuration_rejects_missing_relative_and_worktree_local_root(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "worktrees" / "source"
    source_root.mkdir(parents=True)
    local_root = source_root / "artifacts"
    _write_marker(local_root)

    cases = (
        ({}, "btc_runtime_artifact_root_env_missing"),
        (
            {ENVIRONMENT_VARIABLE: "relative/artifacts"},
            "btc_runtime_artifact_root_must_be_absolute",
        ),
        (
            {ENVIRONMENT_VARIABLE: str(local_root)},
            "btc_runtime_artifact_root_inside_git_worktree",
        ),
    )
    for environment, expected in cases:
        with pytest.raises(BTCRuntimeArtifactStoreError, match=expected):
            BTCRuntimeArtifactReader.from_environment(
                source_repo_root=source_root,
                environment=environment,
                repository_identity=REPOSITORY_IDENTITY,
                worktree_roots=(source_root,),
            )


def test_configuration_rejects_artifact_root_that_contains_a_worktree(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "runtime-artifacts"
    source_root = artifact_root / "nested-worktree"
    source_root.mkdir(parents=True)
    _write_marker(artifact_root)

    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_root_inside_git_worktree",
    ):
        BTCRuntimeArtifactReader.from_environment(
            source_repo_root=source_root,
            environment={ENVIRONMENT_VARIABLE: str(artifact_root)},
            repository_identity=REPOSITORY_IDENTITY,
            worktree_roots=(source_root,),
        )


def test_configuration_rejects_reparse_root_chain(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "worktree"
    source_root.mkdir()
    target = tmp_path / "runtime-target"
    _write_marker(target)
    link = tmp_path / "runtime-link"
    _make_directory_link(link, target)

    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_reparse_path_rejected",
    ):
        BTCRuntimeArtifactReader.from_environment(
            source_repo_root=source_root,
            environment={ENVIRONMENT_VARIABLE: str(link)},
            repository_identity=REPOSITORY_IDENTITY,
            worktree_roots=(source_root,),
        )


def test_configuration_rejects_missing_or_mismatched_owner_marker(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "worktree"
    source_root.mkdir()
    artifact_root = tmp_path / "runtime-artifacts"
    artifact_root.mkdir()
    environment = {ENVIRONMENT_VARIABLE: str(artifact_root)}

    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_owner_marker_missing",
    ):
        BTCRuntimeArtifactReader.from_environment(
            source_repo_root=source_root,
            environment=environment,
            repository_identity=REPOSITORY_IDENTITY,
            worktree_roots=(source_root,),
        )

    marker = build_btc_runtime_artifact_owner_marker(REPOSITORY_IDENTITY)
    marker["repository_identity"] = "sha256:" + "b" * 64
    _write_json(artifact_root / OWNER_MARKER_NAME, marker)
    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_owner_marker_repository_mismatch",
    ):
        BTCRuntimeArtifactReader.from_environment(
            source_repo_root=source_root,
            environment=environment,
            repository_identity=REPOSITORY_IDENTITY,
            worktree_roots=(source_root,),
        )

    marker = build_btc_runtime_artifact_owner_marker(REPOSITORY_IDENTITY)
    marker["unexpected"] = True
    _write_json(artifact_root / OWNER_MARKER_NAME, marker)
    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_owner_marker_schema_invalid",
    ):
        BTCRuntimeArtifactReader.from_environment(
            source_repo_root=source_root,
            environment=environment,
            repository_identity=REPOSITORY_IDENTITY,
            worktree_roots=(source_root,),
        )


def test_reader_revalidates_owner_marker_on_each_access(
    tmp_path: Path,
) -> None:
    reader = _reader(tmp_path)
    (reader.artifact_root / OWNER_MARKER_NAME).unlink()

    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_owner_marker_missing",
    ):
        reader.resolve("artifacts/report.json")


def test_logical_path_contract_rejects_unsafe_or_nonartifact_paths(
    tmp_path: Path,
) -> None:
    reader = _reader(tmp_path)
    invalid = (
        "/artifacts/absolute.json",
        "C:/artifacts/absolute.json",
        r"artifacts\backslash.json",
        "artifacts/../escape.json",
        "artifacts",
        "data/not-an-artifact.json",
        "artifacts//double.json",
    )
    for logical_path in invalid:
        with pytest.raises(
            BTCRuntimeArtifactStoreError,
            match="btc_runtime_artifact_logical_path_invalid",
        ):
            reader.resolve(logical_path)


def test_resolver_rejects_symlink_escape(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = reader.artifact_root / "escape"
    _make_directory_link(link, outside)

    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_reparse_path_rejected",
    ):
        reader.resolve("artifacts/escape/payload.json")


def test_reader_rejects_reparse_component_even_when_target_stays_inside_root(
    tmp_path: Path,
) -> None:
    reader = _reader(tmp_path)
    target = reader.artifact_root / "real"
    _write_json(target / "payload.json", {"status": "blocked"})
    link = reader.artifact_root / "alias"
    _make_directory_link(link, target)

    with pytest.raises(
        BTCRuntimeArtifactStoreError,
        match="btc_runtime_artifact_reparse_path_rejected",
    ):
        reader.read_json("artifacts/alias/payload.json")


def test_second_writer_fails_and_lock_is_released(tmp_path: Path) -> None:
    writer_one = _writer(tmp_path)
    writer_two = BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=writer_one.source_repo_root,
        environment={ENVIRONMENT_VARIABLE: str(writer_one.artifact_root)},
        repository_identity=REPOSITORY_IDENTITY,
        worktree_roots=(writer_one.source_repo_root,),
    )

    with writer_one.exclusive() as session:
        with pytest.raises(
            BTCRuntimeArtifactStoreError,
            match="btc_runtime_artifact_writer_lock_held",
        ):
            with writer_two.exclusive():
                pass
        session.write_json_atomic(
            "artifacts/btc_gate_runs/latest_pointer.json",
            {"generation": 1},
        )

    with writer_two.exclusive() as session:
        session.write_json_atomic(
            "artifacts/btc_gate_runs/latest_pointer.json",
            {"generation": 2},
        )
    assert writer_one.read_json(
        "artifacts/btc_gate_runs/latest_pointer.json"
    ) == {"generation": 2}


def test_atomic_exception_does_not_switch_latest_pointer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    writer = _writer(tmp_path)
    pointer = writer.resolve("artifacts/btc_gate_runs/latest_pointer.json")
    _write_json(pointer, {"generation": 1})
    before = hashlib.sha256(pointer.read_bytes()).hexdigest()

    with writer.exclusive() as session:
        monkeypatch.setattr(
            store_module.os,
            "replace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected_replace_failure")
            ),
        )
        with pytest.raises(OSError, match="injected_replace_failure"):
            session.write_json_atomic(
                "artifacts/btc_gate_runs/latest_pointer.json",
                {"generation": 2},
            )

    assert hashlib.sha256(pointer.read_bytes()).hexdigest() == before
    assert json.loads(pointer.read_text(encoding="utf-8")) == {"generation": 1}
    assert not list(pointer.parent.glob(f".{pointer.name}.*.tmp"))


def _reader(tmp_path: Path) -> BTCRuntimeArtifactReader:
    source_root = tmp_path / "worktree"
    source_root.mkdir(exist_ok=True)
    artifact_root = tmp_path / "runtime-artifacts"
    _write_marker(artifact_root)
    return BTCRuntimeArtifactReader.from_environment(
        source_repo_root=source_root,
        environment={ENVIRONMENT_VARIABLE: str(artifact_root)},
        repository_identity=REPOSITORY_IDENTITY,
        worktree_roots=(source_root,),
    )


def _writer(tmp_path: Path) -> BTCRuntimeArtifactWriter:
    reader = _reader(tmp_path)
    return BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=reader.source_repo_root,
        environment={ENVIRONMENT_VARIABLE: str(reader.artifact_root)},
        repository_identity=REPOSITORY_IDENTITY,
        worktree_roots=(reader.source_repo_root,),
    )


def _write_marker(artifact_root: Path) -> None:
    artifact_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact_root / OWNER_MARKER_NAME,
        build_btc_runtime_artifact_owner_marker(REPOSITORY_IDENTITY),
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _make_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()
