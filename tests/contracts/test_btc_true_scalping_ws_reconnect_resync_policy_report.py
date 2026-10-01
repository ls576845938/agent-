from __future__ import annotations

import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactWriter,
    build_btc_runtime_artifact_owner_marker,
)
from scripts.build_btc_true_scalping_ws_reconnect_resync_policy_report import (
    build_btc_true_scalping_ws_reconnect_resync_policy_report,
)


SCHEMA = Path("schemas/btc_true_scalping_ws_reconnect_resync_policy_report.schema.json")
REPOSITORY_IDENTITY = "sha256:" + "a" * 64


def test_btc_true_scalping_ws_reconnect_resync_policy_schema_valid(tmp_path: Path) -> None:
    payload = _current_payload(tmp_path)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_ws_reconnect_resync_policy_keeps_scalping_locked(tmp_path: Path) -> None:
    payload = _current_payload(tmp_path)
    validation = payload["validation"]
    policy = payload["resync_policy"]

    assert payload["status"] in {
        "ws_reconnect_resync_policy_exercised_research_only_history_latency_queue_insufficient",
        "ws_reconnect_resync_policy_documented_research_only_not_exercised_history_latency_queue_insufficient",
        "ws_reconnect_resync_policy_missing_or_replay_not_ready_research_only",
    }
    assert payload["decision"] == "extend_public_ws_l2_capture_with_resync_policy_then_measure_latency_and_queue"
    assert policy["integrity_source"] == "seqId_prevSeqId_continuity"
    assert policy["feature_emission_policy"]["never_forward_partial_book_after_gap"] is True
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False


def test_ws_reconnect_resync_policy_builder_documents_policy_but_blocks_unlock(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_replay_report(
        artifact_root,
        replay_ready=True,
        sequence_gap_count=0,
        forced_reconnect_count=0,
    )

    payload = build_btc_true_scalping_ws_reconnect_resync_policy_report(
        repo_root=source_root,
        generated_at="2026-06-20T00:00:00Z",
        artifact_reader=reader,
        artifact_writer=writer,
    )

    validation = payload["validation"]
    _assert_source_identity(payload, source_root)
    written = reader.read_json(
        "artifacts/btc_scalping_readiness/latest/"
        "btc_true_scalping_ws_reconnect_resync_policy_report.json"
    )
    _assert_source_identity(written, source_root)
    assert written == payload
    assert payload["schema_version"] == "btc_true_scalping_ws_reconnect_resync_policy_report_v2"
    assert payload["status"] == (
        "ws_reconnect_resync_policy_documented_research_only_not_exercised_history_latency_queue_insufficient"
    )
    assert payload["resync_policy_ready"] is True
    assert validation["source_replay_sequence_ready"] is True
    assert validation["sequence_gap_handling_documented"] is True
    assert validation["actual_reconnect_or_gap_exercised"] is False
    assert "btc_ws_l2_reconnect_resync_not_exercised_on_actual_disconnect_or_gap" in payload["blockers"]
    assert "btc_execution_latency_model_missing_ws_resync_receive_latency_is_not_execution_latency" in payload["blockers"]
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False


def test_ws_reconnect_resync_policy_builder_accepts_forced_reconnect_evidence(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_replay_report(
        artifact_root,
        replay_ready=True,
        sequence_gap_count=0,
        forced_reconnect_count=1,
    )

    payload = build_btc_true_scalping_ws_reconnect_resync_policy_report(
        repo_root=source_root,
        generated_at="2026-06-20T00:00:00Z",
        artifact_reader=reader,
        artifact_writer=writer,
    )

    assert payload["resync_policy_ready"] is True
    assert payload["status"] == "ws_reconnect_resync_policy_exercised_research_only_history_latency_queue_insufficient"
    assert payload["source_replay_summary"]["forced_reconnect_count"] == 1
    assert payload["validation"]["actual_reconnect_or_gap_exercised"] is True
    assert "btc_ws_l2_reconnect_resync_not_exercised_on_actual_disconnect_or_gap" not in payload["blockers"]
    assert payload["event_ledger_feature_validation_allowed"] is False


def test_ws_reconnect_resync_policy_builder_blocks_unready_replay(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_replay_report(
        artifact_root,
        replay_ready=False,
        sequence_gap_count=1,
        forced_reconnect_count=0,
    )

    payload = build_btc_true_scalping_ws_reconnect_resync_policy_report(
        repo_root=source_root,
        generated_at="2026-06-20T00:00:00Z",
        artifact_reader=reader,
        artifact_writer=writer,
    )

    assert payload["status"] == "ws_reconnect_resync_policy_missing_or_replay_not_ready_research_only"
    assert payload["resync_policy_ready"] is False
    assert "btc_ws_l2_reconnect_resync_source_replay_not_ready" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_ws_reconnect_resync_policy_schema_rejects_unlock(tmp_path: Path) -> None:
    payload = _current_payload(tmp_path)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["event_ledger_feature_validation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_ws_reconnect_resync_policy_schema_rejects_legacy_nine_character_commit(
    tmp_path: Path,
) -> None:
    payload = _current_payload(tmp_path)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["commit"] = str(payload["source_head"])[:9]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _current_payload(tmp_path: Path) -> dict[str, object]:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_replay_report(
        artifact_root,
        replay_ready=False,
        sequence_gap_count=1,
        forced_reconnect_count=0,
    )
    return build_btc_true_scalping_ws_reconnect_resync_policy_report(
        repo_root=source_root,
        generated_at="2026-06-20T00:00:00Z",
        artifact_reader=reader,
        artifact_writer=writer,
    )


def _write_replay_report(
    artifact_root: Path,
    *,
    replay_ready: bool,
    sequence_gap_count: int,
    forced_reconnect_count: int,
) -> None:
    _write_json(
        artifact_root
        / "btc_scalping_readiness/latest/btc_true_scalping_ws_order_book_replay_report.json",
        {
            "status": "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient"
            if replay_ready
            else "ws_order_book_replay_missing_or_invalid_research_only",
            "replay_sequence_ready": replay_ready,
            "replay_summary": {
                "snapshot_count": 1,
                "applied_update_count": 2 if replay_ready else 0,
                "sequence_gap_count": sequence_gap_count,
                "crossed_book_count": 0,
                "seq_id_observed_count": 3,
                "prev_seq_id_observed_count": 3,
                "connection_count": 2 if forced_reconnect_count else 1,
                "forced_reconnect_count": forced_reconnect_count,
                "transport_gap_count": forced_reconnect_count,
            },
            "validation": {
                "sequence_integrity_policy_satisfied": replay_ready,
                "public_source_boundary_satisfied": True,
                "minimum_research_capture_seconds_satisfied": False,
                "minimum_event_ledger_history_days_satisfied": False,
            },
            "blockers": ["btc_ws_l2_replay_history_missing_for_event_ledger_window"],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
    _initialize_git_repository(source_root)
    artifact_root = tmp_path / "runtime-artifacts"
    _write_json(
        artifact_root / OWNER_MARKER_NAME,
        build_btc_runtime_artifact_owner_marker(REPOSITORY_IDENTITY),
    )
    kwargs = {
        "source_repo_root": source_root,
        "environment": {ENVIRONMENT_VARIABLE: str(artifact_root)},
        "repository_identity": REPOSITORY_IDENTITY,
        "worktree_roots": (source_root,),
    }
    return (
        source_root,
        artifact_root,
        BTCRuntimeArtifactReader.from_environment(**kwargs),
        BTCRuntimeArtifactWriter.from_environment(**kwargs),
    )


def _initialize_git_repository(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    (root / ".fixture-source").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", ".fixture-source"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=BTC Contract Test",
            "-c",
            "user.email=btc-contract-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        cwd=root,
        check=True,
    )


def _assert_source_identity(payload: dict[str, object], root: Path) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert payload["source_head"] == head
    assert payload["commit"] == head[:12]
