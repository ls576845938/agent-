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
from scripts.build_btc_true_scalping_ws_order_book_replay_report import (
    build_btc_true_scalping_ws_order_book_replay_report,
)


SCHEMA = Path("schemas/btc_true_scalping_ws_order_book_replay_report.schema.json")
REPOSITORY_IDENTITY = "sha256:" + "a" * 64


def test_btc_true_scalping_ws_order_book_replay_schema_valid(tmp_path: Path) -> None:
    payload = _current_payload(tmp_path)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_ws_order_book_replay_keeps_scalping_locked(tmp_path: Path) -> None:
    payload = _current_payload(tmp_path)
    validation = payload["validation"]

    assert payload["status"] in {
        "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient",
        "ws_order_book_replay_missing_or_invalid_research_only",
    }
    assert (
        payload["decision"]
        == "continue_public_ws_l2_capture_with_sequence_reconnect_latency_queue_validation_before_true_scalping"
    )
    assert payload["okx_checksum_deprecation_policy"]["production_deprecation_date"] == "2026-06-23"
    assert payload["okx_checksum_deprecation_policy"]["required_integrity_check"] == "seqId_prevSeqId_continuity"
    assert payload["contract_satisfied"] is False
    assert payload["event_ledger_feature_validation_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert validation["independent_checksum_validated"] is False
    assert validation["checksum_deprecation_policy_recorded"] is True
    assert validation["execution_latency_model_ready"] is False
    assert validation["queue_model_ready"] is False
    assert payload["independent_checksum_validated"] is False
    assert "btc_ws_l2_independent_checksum_validation_missing" not in payload["blockers"]


def test_ws_order_book_replay_builder_validates_sequence_and_metrics(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_replay_fixture(
        source_root,
        artifact_root,
        prev_seq_id_for_update=10,
    )

    payload = build_btc_true_scalping_ws_order_book_replay_report(
        repo_root=source_root,
        generated_at="2026-06-20T00:00:00Z",
        artifact_reader=reader,
        artifact_writer=writer,
    )

    summary = payload["replay_summary"]
    metrics = payload["replay_metrics"]
    validation = payload["validation"]
    _assert_source_identity(payload, source_root)
    written = reader.read_json(
        "artifacts/btc_scalping_readiness/latest/"
        "btc_true_scalping_ws_order_book_replay_report.json"
    )
    _assert_source_identity(written, source_root)
    assert written == payload
    assert payload["schema_version"] == "btc_true_scalping_ws_order_book_replay_report_v2"
    assert payload["status"] == "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient"
    assert payload["replay_sequence_ready"] is True
    assert summary["snapshot_count"] == 1
    assert summary["update_count"] == 1
    assert summary["applied_update_count"] == 1
    assert summary["sequence_continuity_pass"] is True
    assert summary["sequence_gap_count"] == 0
    assert summary["crossed_book_count"] == 0
    assert summary["checksum_observed_count"] == 2
    assert summary["seq_id_observed_count"] == 2
    assert summary["prev_seq_id_observed_count"] == 2
    assert summary["connection_count"] == 1
    assert summary["forced_reconnect_count"] == 0
    assert summary["transport_gap_count"] == 0
    assert summary["final_best_bid"] == pytest.approx(99.9)
    assert summary["final_best_ask"] == pytest.approx(100.1)
    assert metrics["spread_bps"]["mean"] == pytest.approx(20.0)
    assert validation["replay_sequence_ready"] is True
    assert validation["sequence_integrity_policy_satisfied"] is True
    assert validation["checksum_deprecation_policy_recorded"] is True
    assert validation["independent_checksum_validated"] is False
    assert "btc_ws_l2_independent_checksum_validation_missing" not in payload["blockers"]
    assert payload["true_scalping_allowed"] is False


def test_ws_order_book_replay_builder_blocks_sequence_gap(tmp_path: Path) -> None:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_replay_fixture(
        source_root,
        artifact_root,
        prev_seq_id_for_update=999,
    )

    payload = build_btc_true_scalping_ws_order_book_replay_report(
        repo_root=source_root,
        generated_at="2026-06-20T00:00:00Z",
        artifact_reader=reader,
        artifact_writer=writer,
    )

    assert payload["status"] == "ws_order_book_replay_missing_or_invalid_research_only"
    assert payload["replay_sequence_ready"] is False
    assert payload["replay_summary"]["sequence_continuity_pass"] is False
    assert payload["replay_summary"]["sequence_gap_count"] == 1
    assert "btc_ws_l2_replay_sequence_continuity_failed" in payload["blockers"]
    assert "btc_ws_l2_sequence_integrity_policy_not_satisfied" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_ws_order_book_replay_schema_rejects_unlock(tmp_path: Path) -> None:
    payload = _current_payload(tmp_path)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["event_ledger_feature_validation_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_ws_order_book_replay_schema_rejects_legacy_nine_character_commit(
    tmp_path: Path,
) -> None:
    payload = _current_payload(tmp_path)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["commit"] = str(payload["source_head"])[:9]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _current_payload(tmp_path: Path) -> dict[str, object]:
    source_root, artifact_root, reader, writer = _stores(tmp_path)
    _write_replay_fixture(
        source_root,
        artifact_root,
        prev_seq_id_for_update=999,
    )
    return build_btc_true_scalping_ws_order_book_replay_report(
        repo_root=source_root,
        generated_at="2026-06-20T00:00:00Z",
        artifact_reader=reader,
        artifact_writer=writer,
    )


def _write_replay_fixture(
    root: Path,
    artifact_root: Path,
    *,
    prev_seq_id_for_update: int,
) -> None:
    bundle = root / "data/external/btc_perpetual/okx_swap/bundles/fixture"
    _write_json(
        artifact_root
        / "btc_scalping_readiness/latest/btc_okx_public_ws_l2_raw_capture_report.json",
        {
            "status": "verified_preflight",
            "selected_bundle_dir": "data/external/btc_perpetual/okx_swap/bundles/fixture",
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "blockers": [],
        },
    )
    rows = [
        {
            "capture_sequence": 1,
            "local_receive_ts": "2026-06-20T00:00:00Z",
            "monotonic_ns": 1000,
            "channel": "books",
            "raw": json.dumps(
                {
                    "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
                    "action": "snapshot",
                    "data": [
                        {
                            "bids": [["99.9", "1", "0", "1"], ["99.8", "2", "0", "1"]],
                            "asks": [["100.1", "1", "0", "1"], ["100.2", "2", "0", "1"]],
                            "ts": "1781960000000",
                            "seqId": 10,
                            "prevSeqId": -1,
                            "checksum": 123,
                        }
                    ],
                }
            ),
        },
        {
            "capture_sequence": 2,
            "local_receive_ts": "2026-06-20T00:00:01Z",
            "monotonic_ns": 2000,
            "channel": "books",
            "raw": json.dumps(
                {
                    "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
                    "action": "update",
                    "data": [
                        {
                            "bids": [["99.8", "0", "0", "0"]],
                            "asks": [["100.2", "3", "0", "1"]],
                            "ts": "1781960000100",
                            "seqId": 11,
                            "prevSeqId": prev_seq_id_for_update,
                            "checksum": 456,
                        }
                    ],
                }
            ),
        },
    ]
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "okx_public_ws_l2_raw_messages.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    _write_json(
        bundle / "okx_public_ws_l2_raw_capture_manifest.json",
        {
            "data_version": "fixture",
            "capture_start": "2026-06-20T00:00:00Z",
            "capture_end": "2026-06-20T00:00:02Z",
            "capture_duration_seconds": 2.0,
            "public_ws_url": "wss://ws.okx.com:8443/ws/v5/public",
            "public_channels": ["books"],
            "public_ws_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_calls_used": False,
            "clock_source": "system_utc_and_python_monotonic_ns",
            "checksum_or_sequence_policy": "raw_ws_capture_before_order_book_replay_sequence_validation",
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
