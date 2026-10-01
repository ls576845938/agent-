from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.us_equity_domain_read_model import (
    build_us_equity_domain_read_model_router,
)
from quant_us.application.us_equity_domain_read_model import (
    LAYER_IDS,
    TEAM_CONTEXT_DISCOVERY_PATH,
    USDomainReadModelService,
    build_us_equity_domain_read_model,
    load_materialized_us_equity_domain_read_model,
)
from quant_us.monitoring.us_equity_domain_read_model_repository import (
    USCommittedEvidenceRepository,
)


HEAD = "a" * 40
INTEGRATION_COMMIT = "b" * 40
NOW = datetime(2026, 7, 24, 13, 30, tzinfo=timezone.utc)


def test_current_committed_sources_build_schema_valid_fail_closed_projection() -> None:
    repository = _repository()
    report = USDomainReadModelService(
        repository=repository,
        head_resolver=lambda: HEAD,
        clock=lambda: NOW,
    ).read()

    schema = json.loads(
        Path("schemas/us_equity_domain_read_model.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(report, schema)
    assert report["source_head"] == HEAD
    assert report["freshness"] == "current_head"
    assert report["status"] == "blocked"
    assert report["current_stage"] == "blocked_external_data"
    assert set(report["layers"]) == set(LAYER_IDS)
    assert report["layers"]["data"]["status"] == "missing"
    assert report["layers"]["oms"]["status"] == "fixture_lifecycle_quality_checked"
    assert report["gate"]["owner"] == "data_steward"
    assert report["promotion_evidence_ready"] is False
    assert report["paper_ready"] is False
    assert report["live_ready"] is False
    assert all(value is False for value in report["safety"].values())


def test_missing_hash_mismatch_and_wrong_head_all_fail_closed() -> None:
    missing = _repository(omit_artifact="g06")
    missing_report = USDomainReadModelService(
        repository=missing,
        head_resolver=lambda: HEAD,
        clock=lambda: NOW,
    ).read()
    assert missing_report["freshness"] == "blocked"
    assert any(
        row["code"] == "artifact_missing:g06"
        for row in missing_report["blockers"]
    )

    mismatch = _repository(hash_mismatch="g07")
    mismatch_report = USDomainReadModelService(
        repository=mismatch,
        head_resolver=lambda: HEAD,
        clock=lambda: NOW,
    ).read()
    assert any(
        row["code"] == "artifact_hash_mismatch:g07"
        for row in mismatch_report["blockers"]
    )

    wrong_head = _repository(ancestor=False)
    wrong_head_report = USDomainReadModelService(
        repository=wrong_head,
        head_resolver=lambda: HEAD,
        clock=lambda: NOW,
    ).read()
    assert any(
        row["code"] == "source_integration_commit_wrong_head:g06"
        for row in wrong_head_report["blockers"]
    )
    assert wrong_head_report["paper_ready"] is False


def test_repository_rejects_machine_private_and_windows_paths() -> None:
    repository = _repository(artifact_path=r"C:\private\report.json")
    report = USDomainReadModelService(
        repository=repository,
        head_resolver=lambda: HEAD,
        clock=lambda: NOW,
    ).read()
    assert any(
        row["code"] == "artifact_path_invalid:g06"
        for row in report["blockers"]
    )
    assert report["freshness"] == "blocked"


def test_duplicate_and_self_referential_blockers_are_filtered() -> None:
    report = USDomainReadModelService(
        repository=_repository(),
        head_resolver=lambda: HEAD,
        clock=lambda: NOW,
    ).read()
    codes = [row["code"] for row in report["blockers"]]
    assert codes.count("production_pit_bundle_root_not_supplied") == 1
    assert "domain_read_model_missing" not in codes
    assert "us_equity_domain_read_model_summary_blocked" not in codes
    duplicate = next(
        row
        for row in report["blockers"]
        if row["code"] == "production_pit_bundle_root_not_supplied"
    )
    assert duplicate["source"] == "g06,g07"


def test_service_uses_injected_clock_and_repository_without_writing(
    tmp_path: Path,
) -> None:
    before = list(tmp_path.rglob("*"))

    class Repository:
        def read_sources(self, *, source_head, generated_at_utc):
            assert source_head == HEAD
            assert generated_at_utc == NOW
            return _source_rows()

    report = USDomainReadModelService(
        repository=Repository(),
        head_resolver=lambda: HEAD,
        clock=lambda: NOW,
    ).read()
    assert report["generated_at_utc"] == "2026-07-24T13:30:00Z"
    assert list(tmp_path.rglob("*")) == before
    assert report["api_contract"]["builder_triggered"] is False
    assert report["api_contract"]["runtime_triggered"] is False


def test_materialized_loader_blocks_wrong_head_and_hash_mismatch(
    tmp_path: Path,
) -> None:
    report = build_us_equity_domain_read_model(
        sources=_source_rows(),
        source_head=HEAD,
        generated_at_utc=NOW,
    )
    path = tmp_path / TEAM_CONTEXT_DISCOVERY_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report), encoding="utf-8")

    loaded = load_materialized_us_equity_domain_read_model(
        repo_root=tmp_path,
        current_head=HEAD,
    )
    assert loaded["source_head"] == HEAD

    wrong_head = load_materialized_us_equity_domain_read_model(
        repo_root=tmp_path,
        current_head="c" * 40,
    )
    schema = json.loads(
        Path("schemas/us_equity_domain_read_model.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(wrong_head, schema)
    assert wrong_head["status"] == "blocked"
    assert any(
        row["code"] == "domain_read_model_artifact_wrong_head"
        for row in wrong_head["blockers"]
    )

    report["current_stage"] = "tampered"
    path.write_text(json.dumps(report), encoding="utf-8")
    corrupted = load_materialized_us_equity_domain_read_model(
        repo_root=tmp_path,
        current_head=HEAD,
    )
    jsonschema.validate(corrupted, schema)
    assert any(
        row["code"] == "domain_read_model_artifact_hash_mismatch"
        for row in corrupted["blockers"]
    )


def test_router_is_get_only_no_store_and_side_effect_free() -> None:
    calls: list[str] = []

    class Service:
        def read(self):
            calls.append("read")
            return {
                "status": "blocked",
                "paper_ready": False,
                "live_ready": False,
            }

    app = FastAPI()
    app.include_router(
        build_us_equity_domain_read_model_router(
            service=Service(),
            verify_api_key=lambda: True,
        ),
        prefix="/api",
    )
    client = TestClient(app)
    response = client.get("/api/research/us-equity/domain-read-model")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert calls == ["read"]
    assert client.post("/api/research/us-equity/domain-read-model").status_code == 405


def test_team_context_discovery_contract_matches_existing_candidate_path() -> None:
    report = build_us_equity_domain_read_model(
        sources=_source_rows(),
        source_head=HEAD,
        generated_at_utc=NOW,
    )
    assert (
        report["team_context_contract"]["discovery_path"]
        == TEAM_CONTEXT_DISCOVERY_PATH
    )
    assert TEAM_CONTEXT_DISCOVERY_PATH == (
        "artifacts/us_equity_strategy_production_line/latest/"
        "us_equity_operator_read_model.json"
    )


def _repository(
    *,
    omit_artifact: str = "",
    hash_mismatch: str = "",
    ancestor: bool = True,
    artifact_path: str = "",
) -> USCommittedEvidenceRepository:
    artifacts = {
        "g06": _json_bytes(
            {
                "schema_version": "g06_v1",
                "status": "blocked_external_data",
                "decision": "wait_for_data_steward",
                "production_pit": {"state": "missing"},
                "blockers": [
                    "production_pit_bundle_root_not_supplied",
                    "domain_read_model_missing",
                    "us_equity_domain_read_model_summary_blocked",
                ],
            }
        ),
        "g07": _json_bytes(
            {
                "schema_version": "g07_v1",
                "status": "complete_research_only_blocked",
                "decision": "research_only",
                "blockers": [
                    "production_pit_bundle_root_not_supplied",
                    "fixture_simulated_ledger_not_production_event_ledger",
                ],
            }
        ),
        "g08": _json_bytes(
            {
                "schema_version": "g08_v1",
                "status": "complete_quality_checked_paper_blocked",
                "decision": "fixture_execution_drill_complete_paper_not_started",
                "lifecycle": {"complete": True},
                "uow": {"implementation": "fake_uow"},
                "recovery": {"status": "quality_checked"},
                "blockers": [
                    "paper_start_not_authorized",
                    "real_paper_evidence_missing",
                    "production_event_ledger_missing",
                    "manual_paper_start_approval_missing",
                ],
            }
        ),
    }
    manifests = {key: _json_bytes({"immutable": True}) for key in artifacts}
    layer_map = {
        "g06": [("data", "research_ready")],
        "g07": [
            ("backtest", "backtest_ready"),
            ("portfolio", "backtest_ready"),
        ],
        "g08": [
            ("oms", "quality_checked"),
            ("ledger", "quality_checked"),
            ("replay", "quality_checked"),
        ],
    }
    sources = []
    blobs: dict[str, bytes] = {}
    for source_id, raw in artifacts.items():
        path = (
            artifact_path
            if source_id == "g06" and artifact_path
            else f"evidence/{source_id}/report.json"
        )
        manifest_path = f"evidence/{source_id}/manifest.json"
        expected_sha = hashlib.sha256(raw).hexdigest()
        if source_id == hash_mismatch:
            expected_sha = "0" * 64
        sources.append(
            {
                "id": source_id,
                "integration_commit": INTEGRATION_COMMIT,
                "readiness_class": layer_map[source_id][0][1],
                "layers": [
                    {"id": layer, "readiness_class": readiness}
                    for layer, readiness in layer_map[source_id]
                ],
                "artifact": {
                    "path": path,
                    "sha256": expected_sha,
                    "schema_version": f"{source_id}_v1",
                },
                "manifest": {
                    "path": manifest_path,
                    "sha256": hashlib.sha256(manifests[source_id]).hexdigest(),
                },
            }
        )
        if source_id != omit_artifact and "\\" not in path and ":" not in path:
            blobs[path] = raw
        blobs[manifest_path] = manifests[source_id]
    contract = _json_bytes(
        {
            "schema_version": "us_equity_domain_read_model_sources_v1",
            "domain": "us_equity",
            "sources": sources,
        }
    )
    blobs[
        "configs/governance/us_equity_domain_read_model_sources_v1.json"
    ] = contract

    def blob_reader(_revision: str, path: str) -> bytes:
        if path not in blobs:
            raise OSError(path)
        return blobs[path]

    return USCommittedEvidenceRepository(
        repo_root=Path.cwd(),
        blob_reader=blob_reader,
        ancestor_checker=lambda _ancestor, _descendant: ancestor,
    )


def _source_rows() -> list[dict[str, object]]:
    return list(
        _repository().read_sources(
            source_head=HEAD,
            generated_at_utc=NOW,
        )
    )


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")
