from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import quant_crypto.adapters.btc_runtime_artifact_store as store_module
import quant_crypto.application.btc_gate_snapshot as snapshot_module
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriter,
    build_btc_runtime_artifact_owner_marker,
)
from quant_crypto.application.btc_gate_snapshot import (
    GateBuildState,
    capture_gate_build_state,
    load_latest_gate_snapshot,
    publish_gate_run_snapshot,
    resolve_gate_artifact_from_batch,
    resolve_latest_gate_artifact,
    _is_gate_source_input_path,
)


TS = datetime(2026, 7, 10, 2, 0, tzinfo=timezone.utc)


def test_gate_snapshot_pointer_keeps_one_immutable_batch_and_replays_history(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    logical = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
    _write_json(reader.resolve(logical), _artifact("batch-a", marker="first"))

    publication = _publish(source_root, "batch-a", [logical], reader, writer)

    assert publication["published"] is True
    latest = load_latest_gate_snapshot(source_root, artifact_reader=reader)
    assert latest["status"] == "valid"
    assert latest["pointer"]["aggregation_batch_id"] == "batch-a"

    _write_json(reader.resolve(logical), _artifact("batch-b", marker="mutated-latest"))
    resolved = resolve_latest_gate_artifact(
        source_root, logical, artifact_reader=reader
    )
    historical = resolve_gate_artifact_from_batch(
        source_root, "batch-a", logical, artifact_reader=reader
    )
    assert resolved.source == "immutable_gate_snapshot"
    assert historical.source == "historical_snapshot"
    assert _read_json(resolved.path)["marker"] == "first"
    assert _read_json(historical.path)["marker"] == "first"

    with pytest.raises(FileExistsError):
        _publish(source_root, "batch-a", [logical], reader, writer)


def test_gate_snapshot_head_or_input_drift_preserves_previous_pointer(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    logical = Path("artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json")
    _write_json(reader.resolve(logical), _artifact("batch-a", marker="accepted"))
    assert _publish(source_root, "batch-a", [logical], reader, writer)["published"] is True

    _write_json(reader.resolve(logical), _artifact("batch-b", marker="rejected"))
    start = _state(commit="a" * 40, input_hash="1" * 64)
    end = _state(commit="b" * 40, input_hash="2" * 64)
    rejected = publish_gate_run_snapshot(
        repo_root=source_root,
        aggregation_batch_id="batch-b",
        generated_at_utc=TS,
        start_state=start,
        end_state=end,
        step_order=["promotion_gate_control"],
        source_paths=[logical],
        required_paths=[logical],
        validation_checks={"chain_valid": True},
        artifact_reader=reader,
        artifact_writer=writer,
    )

    assert rejected["published"] is False
    assert rejected["validation_checks"]["code_commit_stable"] is False
    assert rejected["validation_checks"]["input_snapshot_stable"] is False
    latest = load_latest_gate_snapshot(source_root, artifact_reader=reader)
    assert latest["pointer"]["aggregation_batch_id"] == "batch-a"
    resolved = resolve_latest_gate_artifact(
        source_root, logical, artifact_reader=reader
    )
    assert _read_json(resolved.path)["marker"] == "accepted"


def test_second_snapshot_writer_fails_without_creating_a_mixed_batch(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    logical = Path("artifacts/btc_a/latest/report.json")
    _write_json(reader.resolve(logical), _artifact("batch-a", marker="a"))

    with writer.exclusive():
        with pytest.raises(
            BTCRuntimeArtifactStoreError,
            match="btc_runtime_artifact_writer_lock_held",
        ):
            _publish(source_root, "batch-a", [logical], reader, writer)

    assert not reader.resolve("artifacts/btc_gate_runs/batch-a").exists()


def test_latest_pointer_replace_failure_preserves_previous_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    logical_a = Path("artifacts/btc_a/latest/report.json")
    logical_b = Path("artifacts/btc_b/latest/report.json")
    _write_json(reader.resolve(logical_a), _artifact("batch-a", marker="a"))
    _write_json(reader.resolve(logical_b), _artifact("batch-b", marker="b"))
    assert _publish(source_root, "batch-a", [logical_a], reader, writer)["published"] is True

    real_replace = store_module.os.replace

    def deny_pointer_replace(source, destination):
        if Path(destination).name == "latest_pointer.json":
            error = PermissionError(13, "fixture pointer lock")
            error.winerror = 5
            raise error
        return real_replace(source, destination)

    monkeypatch.setattr(store_module.os, "replace", deny_pointer_replace)

    with pytest.raises(PermissionError):
        _publish(source_root, "batch-b", [logical_b], reader, writer)

    monkeypatch.setattr(store_module.os, "replace", real_replace)
    latest = load_latest_gate_snapshot(source_root, artifact_reader=reader)
    assert latest["status"] == "valid"
    assert latest["pointer"]["aggregation_batch_id"] == "batch-a"


def test_corrupt_latest_pointer_fails_closed_instead_of_falling_back_to_mutable_latest(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    logical = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
    _write_json(reader.resolve(logical), _artifact("batch-a", marker="legacy"))
    pointer = reader.resolve("artifacts/btc_gate_runs/latest_pointer.json")
    _write_json(
        pointer,
        {
            "schema_version": "btc_gate_latest_pointer_v1",
            "aggregation_batch_id": "batch-a",
            "manifest_path": "artifacts/btc_gate_runs/batch-a/manifest.json",
            "manifest_sha256": "0" * 64,
        },
    )

    resolved = resolve_latest_gate_artifact(
        source_root, logical, artifact_reader=reader
    )

    assert resolved.path is None
    assert resolved.source == "snapshot_pointer_fail_closed"
    assert resolved.error == "btc_gate_latest_pointer_manifest_missing"


def test_missing_latest_pointer_never_falls_back_to_mutable_latest(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    logical = Path(
        "artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"
    )
    _write_json(reader.resolve(logical), _artifact("mutable", marker="mutable"))

    resolved = resolve_latest_gate_artifact(
        source_root,
        logical,
        artifact_reader=reader,
    )

    assert resolved.path is None
    assert resolved.source == "snapshot_pointer_fail_closed"
    assert resolved.error == "btc_gate_latest_pointer_missing_or_invalid"


def test_latest_snapshot_rejects_wrong_head_and_tampered_snapshot_artifact(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    logical = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
    _write_json(reader.resolve(logical), _artifact("batch-a", marker="accepted"))
    assert _publish(source_root, "batch-a", [logical], reader, writer)["published"] is True

    wrong_head = load_latest_gate_snapshot(
        source_root, expected_head="b" * 40, artifact_reader=reader
    )
    assert wrong_head["status"] == "invalid"
    assert wrong_head["error"] == "btc_gate_latest_pointer_wrong_head"

    valid = load_latest_gate_snapshot(
        source_root, expected_head="a" * 40, artifact_reader=reader
    )
    snapshot_path = Path(valid["manifest"]["artifacts"][0]["snapshot_path"])
    reader.resolve(snapshot_path).write_text("tampered", encoding="utf-8")
    tampered = load_latest_gate_snapshot(
        source_root, expected_head="a" * 40, artifact_reader=reader
    )
    assert tampered["status"] == "invalid"
    assert (
        tampered["error"]
        == "btc_gate_latest_pointer_artifact_sha256_mismatch"
    )


def test_gate_input_scope_ignores_unrelated_us_equity_agent_changes() -> None:
    assert _is_gate_source_input_path("quant_crypto/research/btc_gate.py") is True
    assert _is_gate_source_input_path("backend/app/api/app_factory.py") is True
    assert _is_gate_source_input_path("scripts/build_btc_gate.py") is True
    assert _is_gate_source_input_path("quant_us/live/manual_review_packet_report.py") is False
    assert _is_gate_source_input_path("tests/contracts/test_us_equity_manual_review_packet.py") is False
    assert _is_gate_source_input_path("docs/us_equity_development_pitfall_log.md") is False


def test_gate_build_state_always_uses_explicit_source_pathspecs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_git_bytes(args, *, cwd):
        calls.append(list(args))
        if args[:2] == ["rev-parse", "HEAD"]:
            return b"a" * 40
        return b""

    monkeypatch.setattr(snapshot_module, "_git_bytes", fake_git_bytes)

    state = capture_gate_build_state(
        tmp_path,
        status_paths=("quant_crypto", "scripts"),
    )

    status_call = next(args for args in calls if args and args[0] == "status")
    separator = status_call.index("--")
    assert status_call[separator + 1 :] == ["quant_crypto", "scripts"]
    assert state.code_commit == "a" * 40


def _publish(
    root: Path,
    batch_id: str,
    paths: list[Path],
    reader: BTCRuntimeArtifactReader,
    writer: BTCRuntimeArtifactWriter,
) -> dict:
    state = _state(commit="a" * 40, input_hash="1" * 64)
    return publish_gate_run_snapshot(
        repo_root=root,
        aggregation_batch_id=batch_id,
        generated_at_utc=TS,
        start_state=state,
        end_state=state,
        step_order=["gate_dashboard", "promotion_gate_control"],
        source_paths=paths,
        required_paths=paths,
        validation_checks={"chain_valid": True},
        artifact_reader=reader,
        artifact_writer=writer,
    )


def _state(*, commit: str, input_hash: str) -> GateBuildState:
    return GateBuildState(
        code_commit=commit,
        dirty_status_hash="d" * 64,
        dirty_paths=("AGENTS.md",),
        source_input_hash=input_hash,
        watched_input_hash=input_hash,
        input_snapshot_hash=input_hash,
    )


def _artifact(batch_id: str, *, marker: str) -> dict:
    return {
        "schema_version": "test_v1",
        "status": "blocked_research_only",
        "aggregation_batch_id": batch_id,
        "code_commit": "a" * 40,
        "marker": marker,
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path | None) -> dict:
    assert path is not None
    return json.loads(path.read_text(encoding="utf-8"))


def _stores(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactWriter,
]:
    source_root = tmp_path / "source-worktree"
    source_root.mkdir()
    artifact_root = tmp_path / "runtime-artifacts"
    artifact_root.mkdir()
    repository_identity = "sha256:" + "a" * 64
    _write_json(
        artifact_root / OWNER_MARKER_NAME,
        build_btc_runtime_artifact_owner_marker(repository_identity),
    )
    kwargs = {
        "source_repo_root": source_root,
        "environment": {ENVIRONMENT_VARIABLE: str(artifact_root)},
        "repository_identity": repository_identity,
        "worktree_roots": (source_root,),
    }
    return (
        source_root,
        artifact_root,
        BTCRuntimeArtifactReader.from_environment(**kwargs),
        BTCRuntimeArtifactWriter.from_environment(**kwargs),
    )
