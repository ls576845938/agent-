from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.app.api import app_factory
from backend.app.api.app_factory import (
    BTC_RESEARCH_CONTROL_ARTIFACTS,
    _btc_research_control_center_payload,
)
from backend.app.api.btc_outbound_path_redaction import REDACTED_PHYSICAL_PATH
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactWriter,
    build_btc_runtime_artifact_owner_marker,
)
from quant_crypto.application.btc_gate_snapshot import (
    GateBuildState,
    publish_gate_run_snapshot,
)


TS = datetime(2026, 7, 5, 9, 30, tzinfo=timezone.utc).isoformat()

try:
    from fastapi.testclient import TestClient

    TESTCLIENT_AVAILABLE = True
except (ImportError, RuntimeError):
    TESTCLIENT_AVAILABLE = False


def test_btc_control_center_operator_summary_schema_and_fail_closed_flags(tmp_path: Path) -> None:
    _write_control_center_fixtures(tmp_path)
    source_root, reader = _publish_control_center_snapshot(tmp_path)

    payload = _btc_research_control_center_payload(
        source_root,
        artifact_reader=reader,
    )

    assert payload["schema_version"] == "btc_research_control_center_frontend_v1"
    assert payload["status"] == "complete_research_only"
    assert payload["missing_sources"] == []
    assert payload["decision"] == "btc_research_control_center_read_only_no_paper_no_live"
    assert payload["guardrails"]["paper_queue_write_allowed"] is False
    assert payload["guardrails"]["paper_allowed"] is False
    assert payload["guardrails"]["live_unlock_allowed"] is False
    assert payload["guardrails"]["broker_or_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["real_order_submitted"] is False

    assert set(BTC_RESEARCH_CONTROL_ARTIFACTS).issubset(payload["reports"])
    assert set(BTC_RESEARCH_CONTROL_ARTIFACTS).issubset(payload["source_paths"])

    operator = payload["operator_summary"]
    assert set(operator) == {
        "attestation",
        "kill_switch",
        "paper_live_forbidden",
        "root_blockers",
        "runtime_freshness",
    }
    assert operator["root_blockers"]["raw_blocker_count"] == 508
    assert operator["root_blockers"]["root_cause_count"] == 5
    assert operator["root_blockers"]["dominant_root_cause_id"] == "runtime_not_connected"
    assert len(operator["root_blockers"]["top_root_causes"]) == 5
    assert operator["kill_switch"]["kill_switch_engaged"] is True
    assert operator["kill_switch"]["cancel_only_mode"] is True
    assert operator["kill_switch"]["reduce_only_mode"] is True
    assert operator["kill_switch"]["paper_order_intake_allowed"] is False
    assert operator["attestation"]["paper_key_redacted_identifier"] == "paper-****0001"
    assert operator["attestation"]["credential_permissions_verified"] is False
    assert operator["runtime_freshness"]["server_time_offset_ms"] == 350
    assert operator["runtime_freshness"]["private_ws_status"] == "disconnected"
    assert operator["runtime_freshness"]["paper_runtime_replay_ready"] is False
    assert operator["runtime_freshness"]["liquidation_buffer_visible_in_replay"] is False
    assert operator["paper_live_forbidden"]["paper_queue_write_allowed"] is False
    assert operator["paper_live_forbidden"]["paper_allowed"] is False
    assert operator["paper_live_forbidden"]["live_unlock_allowed"] is False
    assert operator["paper_live_forbidden"]["broker_or_order_allowed"] is False
    assert "OKX depth missing" in operator["paper_live_forbidden"]["reasons"]
    assert payload["summary"]["operator_root_cause_count"] == 5
    assert payload["summary"]["operator_raw_blocker_count"] == 508
    assert payload["summary"]["operator_kill_switch_engaged"] is True
    strategy = payload["reports"]["strategy_ledger"]
    assert strategy["source_head"] == "a" * 40
    assert strategy["outputs"]["repo_report"] == "reports/strategy-ledger.json"
    assert (
        strategy["outputs"]["artifact_report"]
        == "artifacts/runs/strategy-ledger.json"
    )
    assert strategy["outputs"]["outside_report"] == REDACTED_PHYSICAL_PATH
    assert strategy["source_report_path"] == REDACTED_PHYSICAL_PATH
    assert strategy["current_sqlite_coverage"]["db_path"] == REDACTED_PHYSICAL_PATH
    assert strategy["selected_bundle_dir"] == REDACTED_PHYSICAL_PATH
    assert strategy["error_context"] == f"failed to read {REDACTED_PHYSICAL_PATH}"
    assert (
        strategy["file_uri_context"]
        == f"failed to read {REDACTED_PHYSICAL_PATH}"
    )
    assert strategy["reference_url"] == "https://example.com/public-evidence"
    assert strategy["strategy_label"] == "Signal -> Forecast -> TargetPosition / risk"


def test_btc_control_center_fails_closed_on_runtime_artifact_safety_violation(tmp_path: Path) -> None:
    _write_control_center_fixtures(tmp_path)
    path = tmp_path / BTC_RESEARCH_CONTROL_ARTIFACTS["kill_switch"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["guardrails"]["order_endpoint_used"] = True
    _write_json(path, payload)
    source_root, reader = _publish_control_center_snapshot(tmp_path)

    control = _btc_research_control_center_payload(
        source_root,
        artifact_reader=reader,
    )

    assert control["status"] == "safety_violation_fail_closed"
    assert "kill_switch:order_endpoint_used" in control["safety_violations"]
    assert control["guardrails"]["paper_queue_write_allowed"] is False
    assert control["guardrails"]["paper_allowed"] is False
    assert control["guardrails"]["live_unlock_allowed"] is False
    assert control["guardrails"]["broker_or_order_allowed"] is False
    assert control["operator_summary"]["paper_live_forbidden"]["order_endpoint_used"] is False
    assert control["operator_summary"]["paper_live_forbidden"]["private_endpoint_used"] is False


@pytest.mark.skipif(
    not TESTCLIENT_AVAILABLE,
    reason="FastAPI TestClient dependencies are unavailable",
)
def test_btc_control_center_endpoint_redacts_physical_paths_and_preserves_gate_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_control_center_fixtures(tmp_path)
    source_root, reader = _publish_control_center_snapshot(tmp_path)
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            repo_root=source_root,
            web_api_key="",
        ),
    )
    monkeypatch.setattr(
        app_factory.BTCRuntimeArtifactReader,
        "from_environment",
        classmethod(lambda cls, **kwargs: reader),
    )

    response = TestClient(app_factory.create_app()).get(
        "/api/research/btc/control-center"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete_research_only"
    assert (
        payload["decision"]
        == "btc_research_control_center_read_only_no_paper_no_live"
    )
    assert payload["missing_sources"] == []
    assert payload["guardrails"]["paper_queue_write_allowed"] is False
    assert payload["guardrails"]["paper_allowed"] is False
    assert payload["guardrails"]["live_unlock_allowed"] is False
    assert payload["guardrails"]["broker_or_order_allowed"] is False
    strategy = payload["reports"]["strategy_ledger"]
    assert strategy["status"] == "complete_research_only"
    assert (
        strategy["decision"]
        == "strategy_ledger_fixture_research_only_no_paper_no_live"
    )
    assert strategy["blockers"] == []
    assert strategy["source_head"] == "a" * 40
    assert strategy["guardrails"]["paper_allowed"] is False
    assert strategy["outputs"]["repo_report"] == "reports/strategy-ledger.json"
    assert (
        strategy["outputs"]["artifact_report"]
        == "artifacts/runs/strategy-ledger.json"
    )
    assert strategy["outputs"]["outside_report"] == REDACTED_PHYSICAL_PATH
    assert strategy["source_report_path"] == REDACTED_PHYSICAL_PATH
    assert strategy["current_sqlite_coverage"]["db_path"] == REDACTED_PHYSICAL_PATH
    assert strategy["selected_bundle_dir"] == REDACTED_PHYSICAL_PATH
    assert strategy["error_context"] == f"failed to read {REDACTED_PHYSICAL_PATH}"
    assert (
        strategy["file_uri_context"]
        == f"failed to read {REDACTED_PHYSICAL_PATH}"
    )
    assert strategy["reference_url"] == "https://example.com/public-evidence"
    assert strategy["strategy_label"] == "Signal -> Forecast -> TargetPosition / risk"


@pytest.mark.skipif(
    not TESTCLIENT_AVAILABLE,
    reason="FastAPI TestClient dependencies are unavailable",
)
def test_btc_control_center_endpoint_keeps_missing_paths_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source-worktree"
    source_root.mkdir()
    artifact_root = tmp_path / "artifacts"
    repository_identity = "sha256:" + "f" * 64
    _write_json(
        artifact_root / OWNER_MARKER_NAME,
        build_btc_runtime_artifact_owner_marker(repository_identity),
    )
    reader = BTCRuntimeArtifactReader.from_environment(
        source_repo_root=source_root,
        environment={ENVIRONMENT_VARIABLE: str(artifact_root)},
        repository_identity=repository_identity,
        worktree_roots=(source_root,),
    )
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            repo_root=source_root,
            web_api_key="",
        ),
    )
    monkeypatch.setattr(
        app_factory.BTCRuntimeArtifactReader,
        "from_environment",
        classmethod(lambda cls, **kwargs: reader),
    )

    response = TestClient(app_factory.create_app()).get(
        "/api/research/btc/control-center"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial_missing_sources"
    assert payload["missing_sources"]
    assert payload["guardrails"]["paper_queue_write_allowed"] is False
    assert payload["guardrails"]["paper_allowed"] is False
    assert payload["guardrails"]["live_unlock_allowed"] is False
    assert payload["guardrails"]["broker_or_order_allowed"] is False
    assert all(
        report["status"] == "missing_fail_closed"
        and report["missing"] is True
        for report in payload["reports"].values()
    )


def _write_control_center_fixtures(root: Path) -> None:
    for artifact_id in BTC_RESEARCH_CONTROL_ARTIFACTS:
        _write_artifact(root, artifact_id, _base_report(artifact_id))

    _write_artifact(
        root,
        "strategy_ledger",
        {
            **_base_report("strategy_ledger"),
            "line_count": 5,
            "fixed_strategy_line_count": 5,
            "source_head": "a" * 40,
            "outputs": {
                "repo_report": str(
                    root / "source-worktree" / "reports" / "strategy-ledger.json"
                ),
                "artifact_report": str(
                    root / "artifacts" / "runs" / "strategy-ledger.json"
                ),
                "outside_report": r"D:\private\strategy-ledger.json",
            },
            "source_report_path": r"\\server\share\strategy-ledger.json",
            "current_sqlite_coverage": {
                "db_path": "D:/private/market_data.sqlite",
            },
            "selected_bundle_dir": "/srv/private/btc-bundle",
            "error_context": r"failed to read \\server\share\strategy-ledger.json",
            "file_uri_context": "failed to read file:///srv/private/ledger.json",
            "reference_url": "https://example.com/public-evidence",
            "strategy_label": "Signal -> Forecast -> TargetPosition / risk",
        },
    )
    _write_artifact(
        root,
        "promotion_gate_control",
        {
            **_base_report("promotion_gate_control"),
            "blocked_gate_count": 8,
            "gate_count": 8,
            "key_blockers_cn": [
                "OKX depth missing",
                "gate fill zero",
                "manual approval missing",
            ],
            "root_cause_summary": {
                "raw_blocker_count": 508,
                "unique_blocker_count": 357,
                "root_cause_count": 5,
                "compression_ratio_raw_to_root": 101.6,
                "dominant_root_cause_id": "runtime_not_connected",
            },
            "root_cause_matrix": [
                {"root_cause_id": "runtime_not_connected", "raw_blocker_count": 375},
                {"root_cause_id": "strategy_overfit_or_forward_gap", "raw_blocker_count": 75},
                {"root_cause_id": "manual_review_approval_missing", "raw_blocker_count": 51},
                {"root_cause_id": "data_wait", "raw_blocker_count": 4},
                {"root_cause_id": "safety_fail_closed", "raw_blocker_count": 3},
            ],
            "gate_matrix": [
                {
                    "gate_id": "data_gate",
                    "status": "blocked",
                    "blockers": ["depth missing"],
                    "checks": {"gate_fill_count": 0},
                },
                {
                    "gate_id": "execution_gate",
                    "status": "blocked",
                    "blockers": ["paper runtime not ready"],
                    "checks": {"paper_runtime_replay_ready": False, "simulated_fill_count": 0},
                },
                {
                    "gate_id": "kill_switch_gate",
                    "status": "blocked",
                    "blockers": ["kill switch engaged"],
                    "checks": {
                        "kill_switch_engaged": True,
                        "cancel_only_mode": True,
                        "reduce_only_mode": True,
                        "paper_order_intake_allowed": False,
                    },
                },
                {
                    "gate_id": "manual_review_gate",
                    "status": "blocked",
                    "blockers": ["manual approval missing"],
                    "checks": {"manual_approval_recorded": False},
                },
            ],
        },
    )
    _write_artifact(
        root,
        "kill_switch",
        {
            **_base_report("kill_switch"),
            "status": "fail_closed_research_only",
            "decision": "btc_paper_live_kill_switch_engaged_fail_closed_no_paper_no_live",
            "summary": {
                "kill_switch_engaged": True,
                "cancel_only_mode": True,
                "paper_order_intake_allowed": False,
                "manual_approval_recorded": False,
            },
            "policy_state": {
                "kill_switch_engaged": True,
                "cancel_only_mode": True,
                "reduce_only_mode": True,
                "paper_order_intake_allowed": False,
                "manual_approval_recorded": False,
            },
            "blockers": ["manual approval missing"],
        },
    )
    _write_artifact(
        root,
        "paper_account_attestation",
        {
            **_base_report("paper_account_attestation"),
            "status": "blocked_fail_closed_research_only",
            "decision": "btc_paper_account_runtime_attestation_missing_or_incomplete_fail_closed_no_paper_no_live",
            "attestation_current": False,
            "account_mode_verified": False,
            "margin_mode_verified": False,
            "position_mode_verified": False,
            "credential_permissions_verified": False,
            "credential_separation_verified": False,
            "manual_approval_recorded": False,
            "attestation_summary": {
                "paper_key_redacted_identifier": "paper-****0001",
                "withdraw_permission_enabled": False,
                "withdraw_permission_verified_false": False,
            },
            "credential_permission_checks": {"live_credential_not_loaded_verified": False},
            "credential_separation_checks": {"data_paper_live_identifiers_unique": True},
            "manual_approval_checks": {"approval_id_present": False},
            "blockers": ["btc_paper_account_runtime_manual_approval_not_recorded"],
        },
    )
    _write_artifact(
        root,
        "exchange_runtime_local_probe",
        {
            **_base_report("exchange_runtime_local_probe"),
            "status": "blocked_research_only",
            "decision": "exchange_runtime_local_probe_fail_closed_no_paper_no_live",
            "runtime_snapshot": {
                "as_of_utc": TS,
                "last_market_data_time_utc": TS,
                "last_private_event_time_utc": None,
                "server_time_offset_ms": 350,
                "public_ws_status": "connected",
                "private_ws_status": "disconnected",
                "metadata_version": "okx_btc_usdt_swap_local_probe_v1",
                "order_rate_budget_remaining": 0,
                "cancel_only": True,
            },
            "server_time_offset_diagnostics": {"offset_ms": 350, "within_threshold": True},
            "ws_sequence_gapfill_replay": {"gap_detected": True, "recovered": True},
            "metadata_version_diagnostics": {"metadata_version": "okx_btc_usdt_swap_local_probe_v1"},
            "rate_limit_budget_explanation": {
                "order_entry_budget": {"status": "blocked"},
                "public_rest_or_ws_budget": {"status": "ok"},
            },
            "blockers": ["btc_exchange_private_ws_not_connected:disconnected"],
        },
    )
    _write_artifact(
        root,
        "exchange_runtime_gap",
        {
            **_base_report("exchange_runtime_gap"),
            "status": "incomplete_research_only",
            "summary": {
                "paper_runtime_replay_ready": False,
                "paper_runtime_drill_simulated_fill_count": 24,
            },
            "blockers": ["btc_paper_runtime_replay_not_ready"],
        },
    )
    _write_artifact(
        root,
        "paper_runtime_replay",
        {
            **_base_report("paper_runtime_replay"),
            "status": "incomplete_research_only",
            "summary": {
                "paper_runtime_replay_ready": False,
                "simulated_fill_count": 0,
                "liquidation_buffer_visible_in_replay": False,
            },
            "blockers": ["btc_perpetual_paper_runtime_replay_no_simulated_fills"],
        },
    )


def _base_report(artifact_id: str) -> dict[str, Any]:
    return {
        "schema_version": f"{artifact_id}_fixture_v1",
        "generated_at_utc": TS,
        "status": "complete_research_only",
        "decision": f"{artifact_id}_fixture_research_only_no_paper_no_live",
        "blockers": [],
        "warnings": [],
        "summary": {},
        "gate": _safe_flags(),
        "guardrails": _safe_flags(),
    }


def _safe_flags() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "broker_or_order_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
        "strategy_skeleton_generated": False,
    }


def _publish_control_center_snapshot(
    root: Path,
) -> tuple[Path, BTCRuntimeArtifactReader]:
    source_root = root / "source-worktree"
    source_root.mkdir()
    artifact_root = root / "artifacts"
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
    reader = BTCRuntimeArtifactReader.from_environment(**kwargs)
    writer = BTCRuntimeArtifactWriter.from_environment(**kwargs)
    state = GateBuildState(
        code_commit="a" * 40,
        dirty_status_hash="b" * 64,
        dirty_paths=(),
        source_input_hash="c" * 64,
        watched_input_hash="d" * 64,
        input_snapshot_hash="e" * 64,
    )
    logical_paths = [
        Path(path) for path in BTC_RESEARCH_CONTROL_ARTIFACTS.values()
    ]
    publication = publish_gate_run_snapshot(
        repo_root=source_root,
        aggregation_batch_id="control-center-contract",
        generated_at_utc=datetime(2026, 7, 5, 9, 30, tzinfo=timezone.utc),
        start_state=state,
        end_state=state,
        step_order=list(BTC_RESEARCH_CONTROL_ARTIFACTS),
        source_paths=logical_paths,
        required_paths=logical_paths,
        validation_checks={"chain_valid": True},
        artifact_reader=reader,
        artifact_writer=writer,
    )
    assert publication["published"] is True
    return source_root, reader


def _write_artifact(root: Path, artifact_id: str, payload: dict[str, Any]) -> None:
    _write_json(root / BTC_RESEARCH_CONTROL_ARTIFACTS[artifact_id], payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(copy.deepcopy(payload), sort_keys=True), encoding="utf-8")
