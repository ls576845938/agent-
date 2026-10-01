from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_true_scalping_execution_queue_external_evidence_contract_report import (
    build_btc_true_scalping_execution_queue_external_evidence_contract_report,
)


SCHEMA = Path("schemas/btc_true_scalping_execution_queue_external_evidence_contract_report.schema.json")
REPORT = Path(
    "artifacts/btc_scalping_readiness/latest/"
    "btc_true_scalping_execution_queue_external_evidence_contract_report.json"
)


def test_btc_true_scalping_execution_queue_external_evidence_contract_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_btc_true_scalping_execution_queue_external_evidence_contract_fails_closed() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))

    assert payload["status"] == "execution_queue_external_evidence_contract_missing_or_invalid_research_only"
    assert payload["validation"]["contract_satisfied"] is False
    assert payload["contract_satisfied"] is False
    assert payload["execution_latency_evidence_contract_satisfied"] is False
    assert payload["queue_position_evidence_contract_satisfied"] is False
    assert payload["candidate_generation_allowed"] is False
    assert payload["strategy_skeleton_generation_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["true_scalping_allowed"] is False
    assert "btc_execution_queue_evidence_import_manifest_missing" in payload["blockers"]
    assert "btc_execution_latency_observations_missing" in payload["blockers"]
    assert "btc_execution_latency_model_external_evidence_missing" in payload["blockers"]
    assert "btc_queue_position_observations_missing" in payload["blockers"]
    assert "btc_queue_position_model_external_evidence_missing" in payload["blockers"]


def test_btc_true_scalping_execution_queue_external_evidence_contract_accepts_valid_read_only_export(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data/external/btc_perpetual/okx_swap/execution_queue_evidence"
    execution_obs = root / "execution_latency.csv"
    execution_model = root / "execution_latency_model.json"
    queue_obs = root / "queue_positions.csv"
    queue_model = root / "queue_position_model.json"
    _write_text(execution_obs, "client_order_id,submitted_at,acked_at,filled_at\n")
    _write_text(execution_model, '{"model":"latency"}\n')
    _write_text(queue_obs, "client_order_id,exchange_order_id,queue_position,label\n")
    _write_text(queue_model, '{"model":"queue"}\n')
    manifest = root / "execution_queue_manifest.json"
    files = [
        ("execution_latency_observations", execution_obs, 120),
        ("execution_latency_model", execution_model, 1),
        ("queue_position_observations", queue_obs, 140),
        ("queue_position_model", queue_model, 1),
    ]
    _write_json(
        manifest,
        {
            "schema_version": "btc_true_scalping_execution_queue_external_evidence_manifest_v1",
            "manifest_id": "fixture_execution_queue",
            "source_type": "paper_exchange_order_log_export",
            "venue": "okx",
            "venue_symbol": "BTC-USDT-SWAP",
            "symbol": "BTCUSDT",
            "read_only_export": True,
            "importer_private_endpoint_used": False,
            "importer_order_endpoint_used": False,
            "broker_calls_used": False,
            "real_orders_created_for_this_import": False,
            "clock_sync_evidence": True,
            "exchange_order_ids_present": True,
            "queue_position_labels_present": True,
            "files": [
                {
                    "role": role,
                    "path": str(path.relative_to(tmp_path)),
                    "format": "csv" if path.suffix == ".csv" else "json",
                    "source_export": "manual_read_only_fixture",
                    "sample_count": sample_count,
                    "sample_start": "2026-01-01T00:00:00Z",
                    "sample_end": "2026-01-02T00:00:00Z",
                    "sha256": _sha256(path),
                }
                for role, path, sample_count in files
            ],
        },
    )

    payload = build_btc_true_scalping_execution_queue_external_evidence_contract_report(
        repo_root=tmp_path,
        generated_at="2026-06-21T00:00:00Z",
    )

    assert payload["status"] == "execution_queue_external_evidence_contract_satisfied_research_only"
    assert payload["contract_satisfied"] is True
    assert payload["execution_latency_evidence_contract_satisfied"] is True
    assert payload["queue_position_evidence_contract_satisfied"] is True
    assert payload["coverage_totals"]["execution_latency_observation_count"] == 120
    assert payload["coverage_totals"]["queue_position_observation_count"] == 140
    assert payload["coverage_totals"]["remaining_execution_latency_observations"] == 0
    assert payload["coverage_totals"]["remaining_queue_position_observations"] == 0
    assert payload["blockers"] == []
    assert payload["true_scalping_allowed"] is False
    assert payload["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["private_endpoints_allowed"] is False
    assert payload["guardrails"]["order_endpoints_allowed"] is False
    assert payload["guardrails"]["broker_calls_allowed"] is False


def test_btc_true_scalping_execution_queue_external_evidence_contract_rejects_importer_private_or_order_boundary(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "data/external/btc_perpetual/okx_swap/execution_queue_evidence/bad_manifest.json"
    _write_json(
        manifest,
        {
            "source_type": "paper_exchange_order_log_export",
            "read_only_export": True,
            "importer_private_endpoint_used": True,
            "importer_order_endpoint_used": True,
            "broker_calls_used": True,
            "real_orders_created_for_this_import": True,
            "clock_sync_evidence": True,
            "exchange_order_ids_present": True,
            "queue_position_labels_present": True,
            "files": [],
        },
    )

    payload = build_btc_true_scalping_execution_queue_external_evidence_contract_report(
        repo_root=tmp_path,
        generated_at="2026-06-21T00:00:00Z",
    )

    assert payload["contract_satisfied"] is False
    assert "btc_execution_queue_importer_private_endpoint_used" in payload["blockers"]
    assert "btc_execution_queue_importer_order_endpoint_used" in payload["blockers"]
    assert "btc_execution_queue_importer_broker_calls_used" in payload["blockers"]
    assert "btc_execution_queue_import_created_real_orders" in payload["blockers"]
    assert payload["paper_or_live_unlock_allowed"] is False


def test_btc_true_scalping_execution_queue_external_evidence_contract_schema_rejects_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["paper_or_live_unlock_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)

    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    payload["guardrails"]["broker_calls_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
