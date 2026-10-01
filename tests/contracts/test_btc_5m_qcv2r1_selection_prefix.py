from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tools.agent_governance.shared_data import (
    default_shared_data_root,
    resolve_manifest_file,
    sha256_file,
    validate_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT
    / ".agent/data_manifests/btc-5m-qcv2r1-selection-prefix"
    / "btc-5m-qcv2r1-selection-prefix-248270-qc2r1.json"
)
PARENT_MANIFEST_PATH = (
    ".agent/data_manifests/btc-market-data-sqlite-snapshot/"
    "btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-"
    "src40741d39-main64e20af8-qc2r1.json"
)
PARENT_DATASET_VERSION = (
    "btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-"
    "src40741d39-main64e20af8-qc2r1"
)
PARENT_MANIFEST_SHA256 = (
    "ad6981dc7c8d5124b594ff4212192e5e94ff87c965bd3e3470f247da56efa9ee"
)
PARENT_5M_SHA256 = (
    "76e8654cd11fc40b873b30d4a6fa8b2ed618256721e3b7840e180bd0f0359c08"
)
PREFIX_ROWS = 248_270
PREFIX_LAST_OPEN_TIME = "2026-05-12T01:05:00Z"
PREFIX_LAST_EVENT_TIME = "2026-05-12T01:09:59.999000Z"
PREFIX_RELATIVE_PATH = (
    "exchange=binance_spot/symbol=BTCUSDT/interval=5m/part-00000.jsonl"
)
ATTESTATION_NAME = "selection_prefix_attestation.json"


def _git_blob(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    return parsed.astimezone(timezone.utc)


def test_committed_manifest_binds_exact_parent_and_prefix_lineage() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert validate_manifest(manifest) == []
    assert manifest["dataset_id"] == "btc-5m-qcv2r1-selection-prefix"
    assert manifest["readiness_class"] == "research_ready"
    assert manifest["quality_status"] == "pass_with_research_only_warnings"
    assert manifest["coverage"] == {
        "start": "2024-01-01T00:00:00Z",
        "end": PREFIX_LAST_OPEN_TIME,
    }
    assert manifest["guardrails"] == {
        "consumer_read_only": True,
        "immutable_version": True,
        "order_endpoint_used": False,
        "paper_or_live_unlock_allowed": False,
        "private_endpoint_used": False,
        "promotion_unlock_allowed": False,
    }
    assert {item["path"] for item in manifest["files"]} == {
        PREFIX_RELATIVE_PATH,
        ATTESTATION_NAME,
    }

    parent_blob = _git_blob(PARENT_MANIFEST_PATH)
    assert hashlib.sha256(parent_blob).hexdigest() == PARENT_MANIFEST_SHA256
    parent = json.loads(parent_blob.decode("utf-8"))
    assert parent["dataset_version"] == PARENT_DATASET_VERSION
    parent_5m = next(
        item for item in parent["files"] if item["path"] == PREFIX_RELATIVE_PATH
    )
    assert parent_5m["sha256"] == PARENT_5M_SHA256


def test_resolved_prefix_is_exact_read_only_5m_payload_without_holdout_decode() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    resolved = resolve_manifest_file(
        MANIFEST_PATH,
        shared_root=default_shared_data_root(REPO_ROOT),
        verify_files=True,
    )
    attestation = json.loads(
        (resolved / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    payload = resolved / PREFIX_RELATIVE_PATH
    payload_entry = next(
        item for item in manifest["files"] if item["path"] == PREFIX_RELATIVE_PATH
    )

    assert attestation["schema_version"] == "btc_5m_selection_prefix_attestation_v1"
    assert attestation["parent"] == {
        "dataset_id": "btc-market-data-sqlite-snapshot",
        "dataset_version": PARENT_DATASET_VERSION,
        "git_manifest_sha256": PARENT_MANIFEST_SHA256,
        "full_5m_payload_sha256": PARENT_5M_SHA256,
    }
    assert attestation["selection_prefix"] == {
        "application_bytes_after_boundary": 0,
        "end_event_time": PREFIX_LAST_EVENT_TIME,
        "end_open_time": PREFIX_LAST_OPEN_TIME,
        "interval": "5m",
        "payload_bytes": payload_entry["bytes"],
        "payload_path": PREFIX_RELATIVE_PATH,
        "payload_sha256": payload_entry["sha256"],
        "row_count": PREFIX_ROWS,
    }
    assert attestation["transform"] == {
        "boundary_read_mode": "unbuffered_raw_readline_stop_after_exact_newline",
        "full_parent_partition_rehashed": False,
        "holdout_row_decoded": False,
        "parent_identity_source": "committed_git_manifest",
        "strategy_metrics_read": False,
    }
    assert attestation["guardrails"]["promotion_unlock_allowed"] is False
    assert attestation["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert attestation["guardrails"]["private_endpoint_used"] is False
    assert attestation["guardrails"]["order_endpoint_used"] is False
    assert sha256_file(payload) == payload_entry["sha256"]

    count = 0
    first_open_time = None
    last_event_time = None
    previous_event_time = None
    with payload.open("rb") as handle:
        for raw_line in handle:
            count += 1
            row = json.loads(raw_line)
            assert row["interval"] == "5m"
            assert row["exchange"] == "binance_spot"
            assert row["symbol"] == "BTCUSDT"
            assert row["is_finalized"] is True
            event_time = _parse_utc(row["event_time"])
            if previous_event_time is not None:
                assert (event_time - previous_event_time).total_seconds() == 300
            previous_event_time = event_time
            if first_open_time is None:
                first_open_time = event_time.timestamp() - 299.999
            last_event_time = row["event_time"]

    assert count == PREFIX_ROWS
    assert datetime.fromtimestamp(first_open_time, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    ) == "2024-01-01T00:00:00Z"
    assert last_event_time == PREFIX_LAST_EVENT_TIME
    with payload.open("rb", buffering=0) as handle:
        handle.seek(-1, 2)
        assert handle.read(1) == b"\n"
