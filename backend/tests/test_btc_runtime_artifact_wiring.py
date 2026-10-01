from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from backend.app.api import app_factory
from backend.app.core.config import load_settings
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    build_btc_runtime_artifact_owner_marker,
    repository_identity_for_source,
)
from quant_crypto.application.btc_gate_snapshot import (
    POINTER_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from quant_crypto.application.btc_domain_read_model import (
    LAYER_IDS,
    build_btc_domain_read_model,
)
from quant_crypto.application.btc_next_stage_current_head_orchestrator import (
    SAFETY,
)
from quant_crypto.monitoring.artifact_schema import stable_payload_hash


pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient


BTC_ENDPOINTS = (
    "/api/research/btc/domain-read-model",
    "/api/research/btc/control-center",
    "/api/research/btc/artifacts/promotion_gate_control",
)
CANONICAL_REQUIRED_BLOCKERS = (
    "btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing",
    "btc_okx_native:effective_sample_regime_coverage_prereg_evidence_incomplete",
    "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing",
    "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime",
    "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
    "btc_okx_native:25_hour_demo_observation_window_incomplete",
    "btc_okx_native:manual_promotion_approval_missing",
)


def test_settings_preserves_only_the_raw_btc_runtime_artifact_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = r"..\relative root\must remain raw"
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, raw)

    loaded = load_settings()

    assert loaded.btc_runtime_artifact_root == raw


@pytest.mark.parametrize(
    "root_kind",
    ("missing", "relative", "marker_mismatch"),
)
def test_invalid_runtime_root_fails_only_the_three_btc_gets_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_kind: str,
) -> None:
    if root_kind == "missing":
        configured = tmp_path / "not-created"
        raw_root = str(configured)
    elif root_kind == "relative":
        configured = None
        raw_root = "relative/runtime-artifacts"
    else:
        configured = tmp_path / "wrong-owner"
        configured.mkdir()
        _write_json(
            configured / OWNER_MARKER_NAME,
            build_btc_runtime_artifact_owner_marker("sha256:" + "f" * 64),
        )
        raw_root = str(configured)

    before = _tree_fingerprint(configured)
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            btc_runtime_artifact_root=raw_root,
        ),
    )
    client = TestClient(app_factory.create_app())

    for endpoint in BTC_ENDPOINTS:
        response = client.get(endpoint)
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["status"] == "unavailable_fail_closed"
        assert detail["error"] == "runtime_artifact_root_unavailable"
        assert detail["paper_queue_write_allowed"] is False
        assert detail["paper_allowed"] is False
        assert detail["live_unlock_allowed"] is False
        assert detail["broker_or_order_allowed"] is False
        assert raw_root not in response.text

    assert client.get("/api/health").status_code == 200
    assert (
        client.get("/api/research/us-equity/domain-read-model").status_code
        == 200
    )
    cn_response = client.get("/api/research/cn-equity/domain-read-model")
    assert cn_response.status_code in {200, 503}
    assert "runtime_artifact_root_unavailable" not in cn_response.text
    assert _tree_fingerprint(configured) == before
    if root_kind == "missing":
        assert configured is not None and not configured.exists()


def test_app_resolves_the_reader_once_and_never_reads_a_repo_local_decoy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = ""
    calls: list[dict[str, Any]] = []
    original = app_factory.BTCRuntimeArtifactReader.from_environment

    def counted_from_environment(**kwargs: Any):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(
        app_factory.BTCRuntimeArtifactReader,
        "from_environment",
        counted_from_environment,
    )
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            btc_runtime_artifact_root=raw_root,
        ),
    )

    def reject_repo_local_read(_path: Path) -> dict[str, Any]:
        raise AssertionError("repo-local BTC artifact decoy must not be read")

    monkeypatch.setattr(app_factory, "_json_file", reject_repo_local_read)
    client = TestClient(app_factory.create_app())
    for endpoint in BTC_ENDPOINTS:
        assert client.get(endpoint).status_code == 503

    assert calls == [
        {
            "source_repo_root": app_factory.settings.repo_root,
            "environment": {ENVIRONMENT_VARIABLE: raw_root},
        }
    ]


def test_valid_external_root_returns_only_logical_paths_and_remains_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "external-runtime-artifacts"
    artifact_root.mkdir()
    _write_owner_marker(app_factory.settings.repo_root, artifact_root)
    current_head = app_factory._current_repository_head(
        app_factory.settings.repo_root
    )
    logical_artifact = (
        "artifacts/btc_promotion_gate_control/latest/"
        "btc_promotion_gate_control_report.json"
    )
    payload = {
        "schema_version": "test_btc_promotion_gate_control_v1",
        "status": "blocked_research_only",
        "evidence_path": str(artifact_root / "physical-path-must-not-leak.json"),
        "guardrails": {
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
    }
    _write_snapshot_fixture(
        artifact_root,
        logical_artifact=logical_artifact,
        payload=payload,
        code_commit=current_head,
        additional_payloads={
            (
                "artifacts/btc_domain_read_model/latest/"
                "btc_domain_read_model.json"
            ): _published_domain_payload(current_head),
        },
    )
    before = _tree_fingerprint(artifact_root)
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            btc_runtime_artifact_root=str(artifact_root),
        ),
    )
    client = TestClient(app_factory.create_app())

    domain_response = client.get("/api/research/btc/domain-read-model")
    control_response = client.get("/api/research/btc/control-center")
    artifact_response = client.get(
        "/api/research/btc/artifacts/promotion_gate_control"
    )

    assert domain_response.status_code == 200, domain_response.text
    domain_payload = domain_response.json()
    assert domain_response.headers["cache-control"] == "no-store"
    assert domain_payload["source_head"] == current_head
    assert domain_payload["status"] == "blocked"
    assert domain_payload["current_stage"] == "pending_next_stage_gate"
    assert domain_payload["required_blocker_count"] == len(
        CANONICAL_REQUIRED_BLOCKERS
    )
    assert domain_payload["blocker_count"] == len(CANONICAL_REQUIRED_BLOCKERS)
    assert len(domain_payload["safety"]) == 49
    assert all(value is False for value in domain_payload["safety"].values())
    assert (
        client.post("/api/research/btc/domain-read-model").status_code
        == 405
    )
    assert control_response.status_code == 200
    assert artifact_response.status_code == 200
    assert artifact_response.json()["evidence_path"] == (
        "artifacts/physical-path-must-not-leak.json"
    )
    assert all(
        value.startswith("artifacts/")
        for value in control_response.json()["source_paths"].values()
    )
    combined = "\n".join(
        (
            domain_response.text,
            control_response.text,
            artifact_response.text,
        )
    )
    assert str(artifact_root) not in combined
    assert _tree_fingerprint(artifact_root) == before


def test_domain_read_model_rejects_direct_hash_drift_without_legacy_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "external-runtime-artifacts"
    artifact_root.mkdir()
    _write_owner_marker(app_factory.settings.repo_root, artifact_root)
    current_head = app_factory._current_repository_head(
        app_factory.settings.repo_root
    )
    logical_domain = (
        "artifacts/btc_domain_read_model/latest/"
        "btc_domain_read_model.json"
    )
    _write_snapshot_fixture(
        artifact_root,
        logical_artifact=logical_domain,
        payload=_published_domain_payload(current_head),
        code_commit=current_head,
    )
    _physical(artifact_root, logical_domain).write_text(
        '{"status":"tampered"}',
        encoding="utf-8",
    )
    before = _tree_fingerprint(artifact_root)
    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            btc_runtime_artifact_root=str(artifact_root),
        ),
    )

    response = TestClient(app_factory.create_app()).get(
        "/api/research/btc/domain-read-model"
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "direct_file_sha256_mismatch" in response.text
    assert str(artifact_root) not in response.text
    assert _tree_fingerprint(artifact_root) == before


def _write_owner_marker(repo_root: Path, artifact_root: Path) -> None:
    _write_json(
        artifact_root / OWNER_MARKER_NAME,
        build_btc_runtime_artifact_owner_marker(
            repository_identity_for_source(repo_root)
        ),
    )


def _write_snapshot_fixture(
    artifact_root: Path,
    *,
    logical_artifact: str,
    payload: dict[str, Any],
    code_commit: str = "a" * 40,
    additional_payloads: dict[str, dict[str, Any]] | None = None,
) -> None:
    batch_id = "shared-wiring-test-batch"
    manifest_logical = (
        "artifacts/btc_gate_runs/shared-wiring-test-batch/manifest.json"
    )
    payloads = {logical_artifact: payload, **(additional_payloads or {})}
    domain_logical = (
        "artifacts/btc_domain_read_model/latest/btc_domain_read_model.json"
    )
    gate_logical = (
        "artifacts/btc_promotion_gate_control/latest/"
        "btc_promotion_gate_control_report.json"
    )
    domain_payload = payloads.get(domain_logical)
    if domain_payload is not None:
        gate_payload = dict(payloads.get(gate_logical) or {})
        gate_payload.update(
            {
                "source_head": code_commit,
                "code_commit": code_commit,
                "aggregation_batch_id": batch_id,
                "blockers": list(domain_payload["required_blockers"]),
            }
        )
        payloads[gate_logical] = gate_payload
    artifacts = []
    for index, (logical_path, artifact_payload) in enumerate(payloads.items()):
        raw = json.dumps(
            artifact_payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        direct_path = _physical(artifact_root, logical_path)
        direct_path.parent.mkdir(parents=True, exist_ok=True)
        direct_path.write_bytes(raw)
        snapshot_logical = (
            "artifacts/btc_gate_runs/shared-wiring-test-batch/"
            f"snapshots/artifact-{index}.json"
        )
        snapshot_path = _physical(artifact_root, snapshot_logical)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(raw)
        artifacts.append(
            {
                "logical_path": logical_path,
                "snapshot_path": snapshot_logical,
                "file_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "aggregation_batch_id": batch_id,
        "status": "complete_immutable_gate_snapshot",
        "immutable": True,
        "code_commit": code_commit,
        "validation_checks": {"all_contracts_valid": True},
        "gate": {
            "research_only": True,
            "paper_queue_write_allowed": False,
            "paper_allowed": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "broker_or_order_allowed": False,
            "broker_access_allowed": False,
            "oms_access_allowed": False,
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
        "guardrails": {
            "immutable_snapshot_only": True,
            "atomic_latest_pointer_publish": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
        "artifacts": artifacts,
    }
    manifest_path = _physical(artifact_root, manifest_logical)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_raw = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_raw)
    _write_json(
        _physical(
            artifact_root,
            "artifacts/btc_gate_runs/latest_pointer.json",
        ),
        {
            "schema_version": POINTER_SCHEMA_VERSION,
            "aggregation_batch_id": batch_id,
            "code_commit": code_commit,
            "manifest_path": manifest_logical,
            "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "broker_or_order_allowed": False,
        },
    )


def _published_domain_payload(head: str) -> dict[str, Any]:
    generated = app_factory.datetime(2026, 7, 27, tzinfo=app_factory.timezone.utc)
    sources = {
        layer: {
            "path": f"artifacts/fixtures/{layer}.json",
            "status": "blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "readiness_class": "quality_checked",
            "sha256": hashlib.sha256(layer.encode()).hexdigest(),
            "source_head": head,
            "generated_at_utc": generated.isoformat(),
            "freshness": "current",
            "blockers": [],
            "summary": {},
        }
        for layer in LAYER_IDS
    }
    payload = build_btc_domain_read_model(
        sources=sources,
        source_head=head,
        generated_at_utc=generated,
    )
    blockers = [
        {
            "code": code,
            "category": "engineering",
            "owner": "btc_developer",
            "next_executable_action": f"resolve_engineering_blocker:{code}",
        }
        for code in CANONICAL_REQUIRED_BLOCKERS
    ]
    payload.update(
        {
            "status": "blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "gate_decision": "blocked_fail_closed_no_paper_no_live",
            "current_stage": "pending_next_stage_gate",
            "freshness": "current_head",
            "readiness_class": "quality_checked",
            "aggregation_batch_id": "shared-wiring-test-batch",
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
            "blockers": blockers,
            "blocker_count": len(blockers),
            "required_blockers": list(CANONICAL_REQUIRED_BLOCKERS),
            "required_blocker_count": len(CANONICAL_REQUIRED_BLOCKERS),
            "required_blockers_sha256": stable_payload_hash(
                list(CANONICAL_REQUIRED_BLOCKERS)
            ),
            "required_blockers_missing": [],
            "required_blockers_preserved": True,
            "safety": dict(SAFETY),
        }
    )
    return payload


def _physical(artifact_root: Path, logical_path: str) -> Path:
    parts = Path(logical_path).parts
    assert parts[0] == "artifacts"
    return artifact_root.joinpath(*parts[1:])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _tree_fingerprint(root: Path | None) -> tuple[tuple[str, str], ...]:
    if root is None or not root.exists():
        return ()
    return tuple(
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )
