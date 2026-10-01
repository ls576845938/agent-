from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import jsonschema
import pytest

from backend.app.api.cn_equity import build_cn_equity_router
from backend.app.services import cn_equity_read_model as service_module
from backend.app.services.cn_equity_read_model import (
    CNEquityReadModelService,
    CNEquityReadModelUnavailable,
    CN_READ_MODEL_ARTIFACT_MISSING,
    CN_READ_MODEL_GENERATION_HASH_MISMATCH,
    CN_READ_MODEL_HEAD_MISMATCH,
    CN_READ_MODEL_METADATA_MISSING,
    CN_READ_MODEL_SCHEMA_MISMATCH,
)
from quant_cn.application.operations_ux import build_cn_operations_read_model
from quant_cn.operations.read_model import (
    ARTIFACT_RELATIVE_PATH,
    CNUpstreamEvidence,
    LAYER_IDS,
    RUNTIME_METADATA_SCHEMA_VERSION,
    SAFETY_FLAGS,
    SCHEMA_RELATIVE_PATH,
    cn_operator_generation_hash,
    validate_cn_operator_read_model_payload,
)
from scripts import materialize_cn_current_head_read_model as materializer
from scripts.materialize_cn_current_head_read_model import (
    CNReadModelMaterializationError,
    materialize_current_head_read_model,
)
from tools.agent_governance.team_context import build_team_context


REPO_ROOT = Path(__file__).resolve().parents[2]
HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=REPO_ROOT,
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
).stdout.strip()
NOW = datetime(2026, 7, 24, 23, 0, tzinfo=timezone.utc)


def _evidence(layer: str, index: int) -> CNUpstreamEvidence:
    classifications: tuple[str, ...] = ()
    blockers = (f"fixture_{layer}_blocker",)
    if layer == "backtest":
        classifications = (
            "classification:fixture_evidence_contract=quality_checked",
        )
    elif layer == "oms":
        classifications = (
            "classification:offline_fixture_chain=quality_checked",
        )
    return CNUpstreamEvidence(
        layer=layer,
        event_id=f"integrated-{layer}-{index}",
        ticket_id=f"CN-{layer}-{index}",
        path=f".agent/handoffs/{layer}-{index}.json",
        sha256=f"{index + 1:x}" * 64,
        deliverable_commit=f"{index + 1:x}" * 40,
        created_at=NOW - timedelta(hours=2),
        readiness_class="quality_checked",
        gate_impact="blocks_gate",
        promotion_eligible=False,
        blockers=blockers,
        classifications=classifications,
    )


def _model_payload() -> dict:
    model = build_cn_operations_read_model(
        upstream_evidence=tuple(
            _evidence(layer, index) for index, layer in enumerate(LAYER_IDS)
        ),
        current_head=HEAD,
        generated_at=NOW,
    )
    return model.to_dict()


def _materialize(output_dir: Path, *, generated_at: datetime = NOW):
    return materialize_current_head_read_model(
        repo_root=REPO_ROOT,
        output_dir=output_dir,
        generated_at=generated_at,
        current_head=HEAD,
    )


def _service(
    output_dir: Path,
    *,
    current_head: str = HEAD,
    schema_path: Path | None = None,
) -> CNEquityReadModelService:
    return CNEquityReadModelService(
        repo_root=REPO_ROOT,
        artifact_path=output_dir / materializer.LATEST_ARTIFACT_NAME,
        metadata_path=output_dir / materializer.RUNTIME_METADATA_NAME,
        schema_path=schema_path or REPO_ROOT / SCHEMA_RELATIVE_PATH,
        head_resolver=lambda: current_head,
        clock=lambda: NOW,
    )


def _tree_receipt(path: Path) -> tuple[tuple[str, int, int, str], ...]:
    return tuple(
        (
            item.relative_to(path).as_posix(),
            item.stat().st_size,
            item.stat().st_mtime_ns,
            hashlib.sha256(item.read_bytes()).hexdigest(),
        )
        for item in sorted(path.rglob("*"))
        if item.is_file()
    )


def test_domain_projection_binds_all_layers_input_and_generation_hashes() -> None:
    payload = _model_payload()
    validate_cn_operator_read_model_payload(payload, expected_head=HEAD)
    assert set(payload["layers"]) == set(LAYER_IDS)
    assert payload["generation_hash"] == cn_operator_generation_hash(
        payload["generation_inputs"]
    )
    assert payload["generation_inputs"]["input_sha256"] == payload["input_sha256"]
    assert payload["status"] == "blocked"
    assert payload["decision"] == "fail_closed"
    assert payload["paper_ready"] is False
    assert payload["live_ready"] is False
    assert all(value is False for value in payload["safety"].values())
    codes = {item["code"] for item in payload["blockers"]}
    assert "cn_backtest_fixture_only" in codes
    assert "cn_oms_offline_fixture_only" in codes
    assert "cn_replay_injected_history_only" in codes


def test_current_main_materializer_uses_validated_committed_g04_to_g08_handoffs(
    tmp_path: Path,
) -> None:
    result = _materialize(tmp_path)
    payload = json.loads(
        (tmp_path / materializer.LATEST_ARTIFACT_NAME).read_text(
            encoding="utf-8"
        )
    )
    metadata = json.loads(
        (tmp_path / materializer.RUNTIME_METADATA_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert result["code_commit"] == HEAD
    assert metadata["schema_version"] == RUNTIME_METADATA_SCHEMA_VERSION
    assert metadata["generation_hash"] == payload["generation_hash"]
    assert metadata["input_sha256"] == payload["input_sha256"]
    assert metadata["artifact_sha256"] == result["artifact_sha256"]
    assert metadata["immutable_generation"] is True
    assert metadata["runtime_builder_enabled"] is False
    assert {
        payload["layers"][layer]["source_event"] for layer in LAYER_IDS
    } >= {
        "integrated-cn-v3-dataready-consumer-01-goal4-batch-01",
        "integrated-cn-v3-market-rule-consumer-01-goal5-batch-01",
        "integrated-cn-v3-oms-ledger-replay-01-goal6-batch-01",
        "integrated-cn-v3-research-backtest-evidence-01-goal7-batch-01",
        "integrated-cn-v3-qmt-offline-contract-01-goal8-batch-01",
    }
    codes = {item["code"] for item in payload["blockers"]}
    assert "cn_dataready_current_main_manifest_missing" in codes
    assert "cn_market_rule_formal_bundle_unvalidated" in codes
    assert "real_data_backtest_evidence_not_produced" in codes
    assert "cn_oms_offline_fixture_only" in codes
    assert "cn_replay_injected_history_only" in codes
    assert "cn_broker_capability_unproven" in codes
    assert "domain_read_model_missing" not in codes


def test_runtime_service_validates_schema_metadata_and_immutable_generation(
    tmp_path: Path,
) -> None:
    _materialize(tmp_path)
    payload = _service(tmp_path).read()
    schema = json.loads(
        (REPO_ROOT / SCHEMA_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert payload["code_commit"] == HEAD
    assert payload["team_context_contract"]["discovery_path"] == (
        ARTIFACT_RELATIVE_PATH
    )


def test_old_head_missing_metadata_and_missing_artifact_fail_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(CNEquityReadModelUnavailable) as missing_metadata:
        _service(tmp_path).read()
    assert missing_metadata.value.blocker == CN_READ_MODEL_METADATA_MISSING

    _materialize(tmp_path)
    with pytest.raises(CNEquityReadModelUnavailable) as old_head:
        _service(tmp_path, current_head="0" * 40).read()
    assert old_head.value.blocker == CN_READ_MODEL_HEAD_MISMATCH

    (tmp_path / materializer.LATEST_ARTIFACT_NAME).unlink()
    with pytest.raises(CNEquityReadModelUnavailable) as missing_artifact:
        _service(tmp_path).read()
    assert missing_artifact.value.blocker == CN_READ_MODEL_ARTIFACT_MISSING


def test_bad_schema_and_generation_hash_fail_closed(tmp_path: Path) -> None:
    _materialize(tmp_path)
    bad_schema = tmp_path / "bad-schema.json"
    schema = json.loads(
        (REPO_ROOT / SCHEMA_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    schema["properties"]["domain"]["const"] = "wrong-domain"
    bad_schema.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(CNEquityReadModelUnavailable) as schema_error:
        _service(tmp_path, schema_path=bad_schema).read()
    assert schema_error.value.blocker == CN_READ_MODEL_SCHEMA_MISMATCH

    metadata_path = tmp_path / materializer.RUNTIME_METADATA_NAME
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["generation_hash"] = "f" * 64
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CNEquityReadModelUnavailable) as generation_error:
        _service(tmp_path).read()
    assert (
        generation_error.value.blocker
        == CN_READ_MODEL_GENERATION_HASH_MISMATCH
    )


def test_generation_file_is_immutable_and_idempotent(tmp_path: Path) -> None:
    first = _materialize(tmp_path)
    second = _materialize(tmp_path)
    assert first == second
    generation_path = Path(first["generation_artifact_path"])
    generation_path.write_text("conflict", encoding="utf-8")
    with pytest.raises(
        CNReadModelMaterializationError,
        match="cn_read_model_generation_immutable_conflict",
    ):
        _materialize(tmp_path)


def test_api_get_is_no_store_zero_write_and_post_is_not_registered(
    tmp_path: Path,
) -> None:
    _materialize(tmp_path)
    before = _tree_receipt(tmp_path)
    app = FastAPI()
    app.include_router(
        build_cn_equity_router(
            service=_service(tmp_path),
            verify_api_key=lambda: True,
        ),
        prefix="/api",
    )
    client = TestClient(app)
    response = client.get("/api/research/cn-equity/domain-read-model")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["status"] == "blocked"
    assert _tree_receipt(tmp_path) == before
    assert client.post("/api/research/cn-equity/domain-read-model").status_code == 405


def test_api_missing_evidence_is_explicit_503_fail_closed(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(
        build_cn_equity_router(
            service=_service(tmp_path),
            verify_api_key=lambda: True,
        ),
        prefix="/api",
    )
    response = TestClient(app).get(
        "/api/research/cn-equity/domain-read-model"
    )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["decision"] == "fail_closed"
    assert body["blockers"][0]["code"] == CN_READ_MODEL_METADATA_MISSING
    assert all(value is False for value in body["safety"].values())


def test_team_context_discovers_current_cn_read_model(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    path = tmp_path / ARTIFACT_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "code_commit": head,
                "status": "blocked",
                "owner": "a_share_developer",
                "blockers": ["cn_dataready_current_main_manifest_missing"],
                "gate": {
                    "owner": "data_steward",
                    "next_action": "publish_current_main_dataready",
                    "first_blocker": "cn_dataready_current_main_manifest_missing",
                },
            }
        ),
        encoding="utf-8",
    )
    packet = build_team_context(
        repo_root=tmp_path,
        consumer_role="a_share_developer",
        shared_data_root=tmp_path / "shared",
        now=NOW,
    )
    cn = next(
        item
        for item in packet["domain_read_models"]
        if item["domain"] == "cn_equity"
    )
    assert cn["path"] == ARTIFACT_RELATIVE_PATH
    assert cn["freshness"] == "current_head"
    assert cn["status"] == "blocked"
    assert cn["first_blocker"] == (
        "cn_dataready_current_main_manifest_missing"
    )


def test_api_and_service_do_not_import_materializer_or_define_write_routes() -> None:
    for module in (
        service_module,
        __import__("backend.app.api.cn_equity", fromlist=["dummy"]),
    ):
        tree = ast.parse(inspect.getsource(module))
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert not any("materialize_cn_current_head" in item for item in imports)
        assert calls.isdisjoint(
            {
                "mkdir",
                "open",
                "unlink",
                "write_bytes",
                "write_text",
            }
        )


def test_generation_hash_tamper_is_detected_by_domain_validator() -> None:
    payload = deepcopy(_model_payload())
    payload["generation_hash"] = "0" * 64
    with pytest.raises(
        ValueError, match="cn_operator_read_model_generation_hash_mismatch"
    ):
        validate_cn_operator_read_model_payload(payload, expected_head=HEAD)
