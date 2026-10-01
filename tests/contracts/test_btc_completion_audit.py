from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.monitoring.completion_audit import build_btc_completion_audit
from scripts.build_btc_completion_audit import build_btc_completion_audit_file
from scripts.build_btc_completion_evidence import build_btc_completion_evidence_files
from scripts.build_btc_exchange_runtime_contract import build_btc_exchange_runtime_contract_file


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def _artifact(status: str = "complete", blockers: list[str] | None = None) -> dict[str, object]:
    return {
        "status": status,
        "decision": "fixture",
        "artifact_hash": HASH,
        "blockers": [] if blockers is None else blockers,
    }


def test_btc_exchange_runtime_contract_builder_writes_simulated_no_endpoint_artifact(tmp_path: Path) -> None:
    output = tmp_path / "runtime.json"

    payload = build_btc_exchange_runtime_contract_file(output=output, generated_at_utc=TS)

    assert output.exists()
    assert payload["status"] == "complete"
    assert payload["notes"]["evidence_type"] == "simulated_contract_probe"
    assert payload["private_endpoint_used"] is False
    assert payload["order_endpoint_used"] is False
    assert payload["real_order_submitted"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_completion_evidence_builder_writes_complete_contract_artifacts(tmp_path: Path) -> None:
    outputs = build_btc_completion_evidence_files(output_root=tmp_path, generated_at_utc=TS)

    assert set(outputs) == {
        "liquidation_risk_contract",
        "source_role_contract",
        "paper_oms_session_contract",
        "incident_replay_drill_contract",
    }
    for path_text in outputs.values():
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
        assert payload["status"] == "complete"
        assert validate_btc_artifact_schema(payload) == []


def test_btc_completion_audit_blocks_only_failed_requirement_evidence() -> None:
    artifacts = {
        "exchange_runtime_contract": _artifact(),
        "liquidation_risk_contract": _artifact(),
        "paper_validation_start": _artifact(),
        "paper_validation_runtime": _artifact(),
        "paper_validation_evaluation": _artifact(),
        "paper_validation_audit_dag": _artifact(),
        "paper_validation_replay": _artifact("replay_pass"),
        "api_key_permission_audit": _artifact("blocked", ["btc_api_key_permission_redacted_records_missing"]),
        "trend_boundary": _artifact(),
        "source_role_contract": _artifact(),
        "paper_oms_session_contract": _artifact(),
        "incident_replay_drill_contract": _artifact(),
        "gate_dashboard": _artifact("blocked", ["btc_gate_dashboard_artifact_blocked:api_key_permission_audit"]),
    }

    payload = build_btc_completion_audit(generated_at_utc=TS, artifacts=artifacts)

    assert payload["status"] == "blocked"
    assert payload["summary"] == {"total": 9, "complete": 8, "blocked": 1, "missing": 0}
    assert "btc_completion_requirement_not_complete:P0-4" in payload["blockers"]
    assert "api_key_permission_audit:btc_api_key_permission_redacted_records_missing" in payload["blockers"]
    assert payload["completion_claim_allowed"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_completion_audit_file_reports_missing_inputs(tmp_path: Path) -> None:
    output = tmp_path / "audit.json"

    payload = build_btc_completion_audit_file(output=output)

    assert output.exists()
    assert payload["status"] in {"blocked", "complete"}
    assert "requirements" in payload
