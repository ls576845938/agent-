from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.btc_domain_read_model import build_btc_domain_read_model_router
from quant_crypto.adapters.btc_domain_read_model_repository import (
    BTCFileDomainReadModelRepository,
    PUBLISHED_GATE_PATH,
    BTCPublishedDomainReadModelRepository,
    PUBLISHED_READ_MODEL_PATH,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactReader,
    build_btc_runtime_artifact_owner_marker,
)
from quant_crypto.application.btc_domain_read_model import (
    BTCDomainReadModelService,
    BTCPublishedDomainReadModelService,
    BTCPublishedDomainReadModelUnavailable,
    LAYER_IDS,
    TEAM_CONTEXT_DISCOVERY_PATH,
    build_btc_domain_read_model,
)
from quant_crypto.application.btc_gate_snapshot import (
    POINTER_SCHEMA_VERSION,
    SCHEMA_VERSION as SNAPSHOT_SCHEMA_VERSION,
)
from quant_crypto.application.btc_next_stage_current_head_orchestrator import (
    SAFETY,
)
from quant_crypto.monitoring.artifact_schema import stable_payload_hash


HEAD = "9" * 40
NOW = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)
CANONICAL_REQUIRED_BLOCKERS = (
    "btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing",
    "btc_okx_native:effective_sample_regime_coverage_prereg_evidence_incomplete",
    "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing",
    "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime",
    "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
    "btc_okx_native:25_hour_demo_observation_window_incomplete",
    "btc_okx_native:manual_promotion_approval_missing",
)


def _sources(*, status: str = "complete_research_only", decision: str = "research_only"):
    return {
        layer: {
            "path": f"fixtures/{layer}.json",
            "status": status,
            "decision": decision,
            "readiness_class": "quality_checked",
            "sha256": layer * 8,
            "source_head": HEAD,
            "generated_at_utc": NOW.isoformat(),
            "freshness": "current",
            "blockers": [],
            "summary": {},
        }
        for layer in LAYER_IDS
    }


def test_missing_source_is_blocked_and_fail_closed() -> None:
    sources = _sources()
    sources["data"] = {}
    report = build_btc_domain_read_model(
        sources=sources, source_head=HEAD, generated_at_utc=NOW
    )
    assert report["status"] == "blocked"
    assert report["freshness"] == "blocked"
    assert report["paper_ready"] is False
    assert report["live_ready"] is False
    assert all(value is False for value in report["safety"].values())


def test_file_repository_detects_stale_wrong_head_and_hash_mismatch(tmp_path: Path) -> None:
    source_root, artifact_root, artifact_reader = _artifact_reader(tmp_path)
    path = Path("artifacts/fixtures/gate.json")
    full = artifact_root / "fixtures/gate.json"
    full.parent.mkdir(parents=True)
    payload = {
        "status": "complete_research_only",
        "decision": "research_only",
        "code_commit": "old-head",
        "generated_at_utc": (NOW - timedelta(days=3)).isoformat(),
        "blockers": [],
    }
    full.write_text(json.dumps(payload), encoding="utf-8")
    repository = BTCFileDomainReadModelRepository(
        repo_root=source_root,
        source_paths={"gate": path},
        expected_hashes={"gate": "0" * 64},
        max_age_hours=24,
        artifact_reader=artifact_reader,
    )
    row = repository.read_sources(source_head=HEAD, generated_at_utc=NOW)["gate"]
    assert row["freshness"] == "stale"
    assert any("hash_mismatch" in item for item in row["blockers"])
    assert any("wrong_head" in item for item in row["blockers"])
    assert any("stale" in item for item in row["blockers"])


def test_current_artifact_records_path_hash_and_current_head(tmp_path: Path) -> None:
    source_root, artifact_root, artifact_reader = _artifact_reader(tmp_path)
    path = Path("artifacts/fixtures/data.json")
    full = artifact_root / "fixtures/data.json"
    full.parent.mkdir(parents=True)
    payload = {
        "status": "quality_checked",
        "decision": "blocked",
        "code_commit": HEAD,
        "generated_at_utc": NOW.isoformat(),
        "blockers": ["owner:data_steward immutable_snapshot_not_published"],
    }
    raw = json.dumps(payload).encode()
    full.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    repository = BTCFileDomainReadModelRepository(
        repo_root=source_root,
        source_paths={"data": path},
        expected_hashes={"data": expected},
        artifact_reader=artifact_reader,
    )
    row = repository.read_sources(source_head=HEAD, generated_at_utc=NOW)["data"]
    assert row["freshness"] == "current"
    assert row["source_head"] == HEAD
    assert row["sha256"] == expected


def test_strategy_oms_ledger_and_replay_sources_are_bound_to_current_head(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, artifact_reader = _artifact_reader(tmp_path)
    layers = ("strategy", "oms", "ledger", "replay")
    paths = {
        layer: Path(f"artifacts/fixtures/{layer}.json") for layer in layers
    }
    expected_hashes = {}
    for layer in layers:
        full = artifact_root / f"fixtures/{layer}.json"
        full.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(
            {
                "status": "complete_research_only",
                "decision": "research_only",
                "source_head": HEAD,
                "generated_at_utc": NOW.isoformat(),
                "blockers": [],
            }
        ).encode()
        full.write_bytes(raw)
        expected_hashes[layer] = hashlib.sha256(raw).hexdigest()

    rows = BTCFileDomainReadModelRepository(
        repo_root=source_root,
        source_paths=paths,
        expected_hashes=expected_hashes,
        artifact_reader=artifact_reader,
    ).read_sources(source_head=HEAD, generated_at_utc=NOW)

    assert set(rows) == set(layers)
    for layer, row in rows.items():
        assert row["source_head"] == HEAD
        assert row["sha256"] == expected_hashes[layer]
        assert row["freshness"] == "current"
        assert row["blockers"] == []


def test_duplicate_and_self_referential_blockers_are_filtered_and_classified() -> None:
    sources = _sources()
    sources["gate"]["blockers"] = [
        "dashboard:immutable_snapshot_not_published",
        "gate:immutable_snapshot_not_published",
        "btc_domain_read_model_summary_blocked",
        "owner:integrator shared_entry_wiring_required",
        "manual_approval_missing",
        "waiting_for_natural_non_flat_sample",
        "oms_reconciliation_failed",
    ]
    report = build_btc_domain_read_model(
        sources=sources, source_head=HEAD, generated_at_utc=NOW
    )
    codes = [row["code"] for row in report["blockers"]]
    assert codes.count("immutable_snapshot_not_published") == 1
    assert not any("domain_read_model" in code for code in codes)
    assert {row["category"] for row in report["blockers"]} == {
        "data_steward",
        "integrator",
        "manual_approval",
        "natural_time",
        "engineering",
    }


def test_explicit_btc_blocker_owner_is_preserved() -> None:
    sources = _sources()
    sources["gate"]["blockers"] = [
        "owner:btc_research "
        "btc_okx_native:promotion_evidence_current_head_rebuild_required",
        "owner:btc_operations "
        "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
    ]

    report = build_btc_domain_read_model(
        sources=sources,
        source_head=HEAD,
        generated_at_utc=NOW,
    )
    owners = {row["code"]: row["owner"] for row in report["blockers"]}

    assert (
        owners[
            "btc_okx_native:promotion_evidence_current_head_rebuild_required"
        ]
        == "btc_research"
    )
    assert (
        owners[
            "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete"
        ]
        == "btc_operations"
    )


def test_native_and_next_stage_gate_aliases_collapse_to_canonical_rows() -> None:
    sources = _sources()
    sources["gate"]["blockers"] = [
        "owner:btc_operations btc_next_stage:real_funding_cashflow_evidence_missing",
        "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime",
        "owner:btc_operations btc_next_stage:real_private_ws_reconciliation_evidence_missing",
        "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
        "owner:btc_observation btc_next_stage:real_non_flat_fill_evidence_missing",
        "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing",
        "owner:architect/manual_reviewer btc_next_stage:manual_promotion_approval_missing",
        "btc_okx_native:manual_promotion_approval_missing",
    ]

    report = build_btc_domain_read_model(
        sources=sources, source_head=HEAD, generated_at_utc=NOW
    )
    codes = [row["code"] for row in report["blockers"]]

    assert codes == [
        "btc_okx_native:funding_cashflow_not_observed_in_demo_runtime",
        "btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete",
        "btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing",
        "btc_okx_native:manual_promotion_approval_missing",
    ]
    assert [row["owner"] for row in report["blockers"]] == [
        "btc_operations",
        "btc_operations",
        "btc_observation",
        "architect/manual_reviewer",
    ]


def test_flat_sample_is_waiting_not_failure_or_fill_evidence() -> None:
    sources = _sources()
    sources["replay"]["summary"] = {
        "current_non_flat_sample_capture_status": "flat_waiting_no_false_positive",
        "trade_execution_evidence_pending_reason": "waiting_for_natural_non_flat_sample",
    }
    report = build_btc_domain_read_model(
        sources=sources, source_head=HEAD, generated_at_utc=NOW
    )
    assert report["current_stage"] == "waiting_for_natural_non_flat_sample"
    assert report["ui_semantics"]["display_stage"] == "等待自然非空样本"
    assert report["promotion_evidence_ready"] is False


def test_research_only_and_blocked_never_render_as_paper_or_live_ready() -> None:
    report = build_btc_domain_read_model(
        sources=_sources(status="complete_research_only", decision="research_only"),
        source_head=HEAD,
        generated_at_utc=NOW,
    )
    assert report["readiness_class"] == "quality_checked"
    assert report["ui_semantics"]["research_only_is_paper_ready"] is False
    assert report["paper_ready"] is False
    assert report["live_ready"] is False


def test_gate_evidence_can_be_reported_without_enabling_paper_or_live() -> None:
    sources = _sources(status="complete", decision="manual_review_required")
    for row in sources.values():
        row["readiness_class"] = "promotion_evidence_ready"
    report = build_btc_domain_read_model(
        sources=sources, source_head=HEAD, generated_at_utc=NOW
    )
    assert report["readiness_class"] == "promotion_evidence_ready"
    assert report["promotion_evidence_ready"] is True
    assert report["paper_ready"] is False
    assert report["live_ready"] is False


def test_schema_contract_and_team_context_discovery_path() -> None:
    report = build_btc_domain_read_model(
        sources=_sources(), source_head=HEAD, generated_at_utc=NOW
    )
    schema = json.loads(
        Path("schemas/btc_domain_read_model.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(report, schema)
    assert (
        report["team_context_contract"]["discovery_path"]
        == TEAM_CONTEXT_DISCOVERY_PATH
    )


def test_api_is_get_only_no_store_and_has_no_builder_or_runtime_side_effect() -> None:
    calls = []

    class Service:
        def read(self):
            calls.append("read")
            return {"status": "blocked", "paper_ready": False, "live_ready": False}

    app = FastAPI()
    app.include_router(
        build_btc_domain_read_model_router(
            service=Service(), verify_api_key=lambda: True
        ),
        prefix="/api",
    )
    client = TestClient(app)
    response = client.get("/api/research/btc/domain-read-model")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert calls == ["read"]
    assert client.post("/api/research/btc/domain-read-model").status_code == 405


def test_service_uses_injected_repository_and_never_writes(tmp_path: Path) -> None:
    before = list(tmp_path.rglob("*"))

    class Repository:
        def read_sources(self, *, source_head, generated_at_utc):
            assert source_head == HEAD
            return _sources()

    service = BTCDomainReadModelService(
        repository=Repository(), head_resolver=lambda: HEAD, clock=lambda: NOW
    )
    assert service.read()["source_head"] == HEAD
    assert list(tmp_path.rglob("*")) == before


def test_published_repository_validates_lineage_and_returns_direct_contract(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, artifact_reader = _artifact_reader(tmp_path)
    payload = _published_payload()
    expected_sha = _write_published_fixture(artifact_root, payload)

    published = BTCPublishedDomainReadModelRepository(
        repo_root=Path.cwd(),
        artifact_reader=artifact_reader,
    ).read_published(source_head=HEAD)

    assert published == payload
    assert artifact_reader.sha256(PUBLISHED_READ_MODEL_PATH) == expected_sha
    assert published["blocker_count"] == len(CANONICAL_REQUIRED_BLOCKERS)
    assert published["required_blocker_count"] == len(
        CANONICAL_REQUIRED_BLOCKERS
    )
    assert published["required_blockers_sha256"] == stable_payload_hash(
        list(CANONICAL_REQUIRED_BLOCKERS)
    )
    assert len(published["safety"]) == 49
    assert all(value is False for value in published["safety"].values())


def test_published_repository_accepts_dynamic_canonical_blocker_contract(
    tmp_path: Path,
) -> None:
    _source_root, artifact_root, artifact_reader = _artifact_reader(tmp_path)
    required = (
        "btc_okx_native:25_hour_demo_observation_window_incomplete",
        "btc_okx_native:manual_promotion_approval_missing",
    )
    payload = _published_payload(required_blockers=required)
    _write_published_fixture(artifact_root, payload)

    published = BTCPublishedDomainReadModelRepository(
        repo_root=Path.cwd(),
        artifact_reader=artifact_reader,
    ).read_published(source_head=HEAD)

    assert published["required_blockers"] == list(required)
    assert published["required_blockers_sha256"] == stable_payload_hash(
        list(required)
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "missing",
        "extra_stale",
        "changed",
        "reordered",
        "duplicate",
        "sha_mismatch",
    ),
)
def test_published_repository_rejects_dynamic_required_blocker_drift(
    tmp_path: Path,
    tamper: str,
) -> None:
    _source_root, artifact_root, artifact_reader = _artifact_reader(tmp_path)
    payload = _published_payload()
    canonical = list(payload["required_blockers"])
    if tamper == "missing":
        payload["required_blockers"] = payload["required_blockers"][:-1]
        payload["blockers"] = payload["blockers"][:-1]
    elif tamper == "extra_stale":
        stale = "runtime_pointer_immutable_snapshot_not_published"
        payload["required_blockers"].append(stale)
        payload["blockers"].append(_structured_blocker(stale))
    elif tamper == "changed":
        changed = "manifest_quality_status_not_pass"
        payload["required_blockers"][0] = changed
        payload["blockers"][0] = _structured_blocker(changed)
    elif tamper == "reordered":
        payload["required_blockers"][0:2] = reversed(
            payload["required_blockers"][0:2]
        )
        payload["blockers"][0:2] = reversed(payload["blockers"][0:2])
    elif tamper == "duplicate":
        payload["required_blockers"].append(payload["required_blockers"][0])
        payload["blockers"].append(dict(payload["blockers"][0]))
    elif tamper == "sha_mismatch":
        payload["required_blockers_sha256"] = "0" * 64
    if tamper != "sha_mismatch":
        payload["required_blocker_count"] = len(payload["required_blockers"])
        payload["required_blockers_sha256"] = stable_payload_hash(
            payload["required_blockers"]
        )
        payload["blocker_count"] = len(payload["blockers"])
    _write_published_fixture(
        artifact_root,
        payload,
        canonical_blockers=canonical,
    )

    with pytest.raises(
        BTCPublishedDomainReadModelUnavailable,
        match="btc_published_domain_read_model_required_blockers_not_preserved",
    ):
        BTCPublishedDomainReadModelRepository(
            repo_root=Path.cwd(),
            artifact_reader=artifact_reader,
        ).read_published(source_head=HEAD)


def test_published_service_never_calls_legacy_source_rebuild() -> None:
    payload = _published_payload()

    class Repository:
        def read_published(self, *, source_head):
            assert source_head == HEAD
            return payload

        def read_sources(self, **_kwargs):
            raise AssertionError("legacy seven-source rebuild is forbidden")

    service = BTCPublishedDomainReadModelService(
        repository=Repository(),
        head_resolver=lambda: HEAD,
    )

    assert service.read() == payload


def test_published_repository_rejects_direct_file_hash_drift_without_fallback(
    tmp_path: Path,
) -> None:
    source_root, artifact_root, artifact_reader = _artifact_reader(tmp_path)
    payload = _published_payload()
    _write_published_fixture(artifact_root, payload)
    direct = artifact_root.joinpath(*PUBLISHED_READ_MODEL_PATH.parts[1:])
    direct.write_text('{"status":"tampered"}', encoding="utf-8")

    with pytest.raises(
        BTCPublishedDomainReadModelUnavailable,
        match="direct_file_sha256_mismatch",
    ):
        BTCPublishedDomainReadModelRepository(
            repo_root=Path.cwd(),
            artifact_reader=artifact_reader,
        ).read_published(source_head=HEAD)


def _artifact_reader(
    tmp_path: Path,
) -> tuple[Path, Path, BTCRuntimeArtifactReader]:
    source_root = tmp_path / "source-worktree"
    source_root.mkdir()
    artifact_root = tmp_path / "runtime-artifacts"
    artifact_root.mkdir()
    repository_identity = "sha256:" + "a" * 64
    (artifact_root / OWNER_MARKER_NAME).write_text(
        json.dumps(build_btc_runtime_artifact_owner_marker(repository_identity)),
        encoding="utf-8",
    )
    reader = BTCRuntimeArtifactReader.from_environment(
        source_repo_root=source_root,
        environment={ENVIRONMENT_VARIABLE: str(artifact_root)},
        repository_identity=repository_identity,
        worktree_roots=(source_root,),
    )
    return source_root, artifact_root, reader


def _published_payload(
    *,
    required_blockers: tuple[str, ...] = CANONICAL_REQUIRED_BLOCKERS,
) -> dict:
    payload = build_btc_domain_read_model(
        sources=_sources(),
        source_head=HEAD,
        generated_at_utc=NOW,
    )
    blockers = [_structured_blocker(value) for value in required_blockers]
    payload.update(
        {
            "status": "blocked",
            "decision": "blocked_fail_closed_no_paper_no_live",
            "gate_decision": "blocked_fail_closed_no_paper_no_live",
            "current_stage": "pending_next_stage_gate",
            "freshness": "current_head",
            "readiness_class": "quality_checked",
            "aggregation_batch_id": "accepted-current-head-batch",
            "promotion_evidence_ready": False,
            "paper_ready": False,
            "live_ready": False,
            "blockers": blockers,
            "blocker_count": len(blockers),
            "required_blockers": list(required_blockers),
            "required_blocker_count": len(required_blockers),
            "required_blockers_sha256": stable_payload_hash(
                list(required_blockers)
            ),
            "required_blockers_missing": [],
            "required_blockers_preserved": True,
            "safety": dict(SAFETY),
        }
    )
    return payload


def _structured_blocker(code: str) -> dict[str, str]:
    return {
        "code": code,
        "category": "engineering",
        "owner": "btc_developer",
        "next_executable_action": f"resolve_engineering_blocker:{code}",
    }


def _write_published_fixture(
    artifact_root: Path,
    payload: dict,
    *,
    canonical_blockers: list[str] | None = None,
) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    direct = artifact_root.joinpath(*PUBLISHED_READ_MODEL_PATH.parts[1:])
    direct.parent.mkdir(parents=True, exist_ok=True)
    direct.write_bytes(raw)

    batch_id = str(payload["aggregation_batch_id"])
    snapshot_logical = (
        "artifacts/btc_gate_runs/"
        f"{batch_id}/files/btc_domain_read_model/latest/"
        "btc_domain_read_model.json"
    )
    snapshot = artifact_root.joinpath(*Path(snapshot_logical).parts[1:])
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(raw)
    gate_payload = {
        "schema_version": "btc_promotion_gate_control_v1",
        "source_head": HEAD,
        "code_commit": HEAD,
        "aggregation_batch_id": batch_id,
        "blockers": list(
            canonical_blockers
            if canonical_blockers is not None
            else payload["required_blockers"]
        ),
    }
    gate_raw = json.dumps(
        gate_payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    gate_direct = artifact_root.joinpath(*PUBLISHED_GATE_PATH.parts[1:])
    gate_direct.parent.mkdir(parents=True, exist_ok=True)
    gate_direct.write_bytes(gate_raw)
    gate_snapshot_logical = (
        "artifacts/btc_gate_runs/"
        f"{batch_id}/files/btc_promotion_gate_control/latest/"
        "btc_promotion_gate_control_report.json"
    )
    gate_snapshot = artifact_root.joinpath(
        *Path(gate_snapshot_logical).parts[1:]
    )
    gate_snapshot.parent.mkdir(parents=True, exist_ok=True)
    gate_snapshot.write_bytes(gate_raw)
    manifest_logical = (
        f"artifacts/btc_gate_runs/{batch_id}/manifest.json"
    )
    manifest = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "aggregation_batch_id": batch_id,
        "status": "complete_immutable_gate_snapshot",
        "immutable": True,
        "code_commit": HEAD,
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
        "artifacts": [
            {
                "logical_path": PUBLISHED_READ_MODEL_PATH.as_posix(),
                "snapshot_path": snapshot_logical,
                "file_sha256": digest,
            },
            {
                "logical_path": PUBLISHED_GATE_PATH.as_posix(),
                "snapshot_path": gate_snapshot_logical,
                "file_sha256": hashlib.sha256(gate_raw).hexdigest(),
            }
        ],
    }
    manifest_raw = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    manifest_path = artifact_root.joinpath(
        *Path(manifest_logical).parts[1:]
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_raw)
    pointer = {
        "schema_version": POINTER_SCHEMA_VERSION,
        "aggregation_batch_id": batch_id,
        "code_commit": HEAD,
        "manifest_path": manifest_logical,
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }
    pointer_path = artifact_root / "btc_gate_runs/latest_pointer.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(
        json.dumps(pointer, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return digest
