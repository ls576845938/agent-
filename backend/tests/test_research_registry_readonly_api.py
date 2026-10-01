"""Exercise the production GET handler without starting schedulers or trading services."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

import quant_us.research.evidence_registry as registry


@pytest.fixture
def client():
    source = Path("backend/app/api/app_factory.py")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "get_research_evidence_registry"
    )
    namespace = {"router": APIRouter(), "HTTPException": HTTPException, "json": json}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), "exec"), namespace)
    app = FastAPI()
    app.include_router(namespace["router"], prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def no_rebuild(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("GET must never rebuild or persist evidence")
    monkeypatch.setattr(registry, "rebuild_evidence_registry", forbidden)


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_missing_registry_is_read_only_and_stays_missing(client, tmp_path, monkeypatch):
    no_rebuild(monkeypatch)
    response = client.get("/api/research/evidence-registry", params={"data_root": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["registry_status"] == "missing"
    assert response.json()["registry_integrity_status"] == "MISSING"
    assert snapshot(tmp_path) == {}


def test_rebuild_query_is_rejected_before_read_or_write(client, tmp_path, monkeypatch):
    no_rebuild(monkeypatch)
    monkeypatch.setattr(registry, "inspect_saved_evidence_registry", lambda *a, **k: pytest.fail("read called"))
    response = client.get("/api/research/evidence-registry", params={"data_root": str(tmp_path), "rebuild": "true"})
    assert response.status_code == 405
    assert response.json()["detail"]["code"] == "registry_rebuild_requires_post"
    assert snapshot(tmp_path) == {}


def test_valid_saved_registry_is_unchanged(client, tmp_path, monkeypatch):
    registry.rebuild_evidence_registry(tmp_path, write=True)
    before = snapshot(tmp_path)
    no_rebuild(monkeypatch)
    response = client.get("/api/research/evidence-registry", params={"data_root": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["registry_integrity_status"] == "PASS/STABLE"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("bad_bytes", [b"not json", b"\xff\xfe"])
def test_unreadable_source_returns_conflict_without_repair(client, tmp_path, monkeypatch, bad_bytes):
    registry.rebuild_evidence_registry(tmp_path, write=True)
    path = tmp_path / "manifests" / "run_broken.json"
    path.parent.mkdir()
    path.write_bytes(bad_bytes)
    before = snapshot(tmp_path)
    no_rebuild(monkeypatch)
    response = client.get("/api/research/evidence-registry", params={"data_root": str(tmp_path)})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "research_evidence_unreadable"
    assert detail["registry_integrity_status"] == "CONFLICT"
    assert detail["read_only"] is True
    assert detail["promotion_eligible"] is False
    assert str(tmp_path) not in json.dumps(detail)
    assert snapshot(tmp_path) == before


def test_corrupt_saved_registry_is_not_rebuilt(client, tmp_path, monkeypatch):
    path = tmp_path / "research" / "evidence_registry.json"
    path.parent.mkdir()
    path.write_text("broken", encoding="utf-8")
    before = snapshot(tmp_path)
    no_rebuild(monkeypatch)
    response = client.get("/api/research/evidence-registry", params={"data_root": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["registry_status"] == "conflict"
    assert response.json()["registry_integrity_status"] == "CONFLICT"
    assert snapshot(tmp_path) == before


def test_legacy_index_does_not_substitute_saved_registry(client, tmp_path, monkeypatch):
    registry.rebuild_evidence_registry(tmp_path, write=True)
    (tmp_path / "research" / "evidence_registry.json").unlink()
    before = snapshot(tmp_path)
    no_rebuild(monkeypatch)
    response = client.get("/api/research/evidence-registry", params={"data_root": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["registry_status"] == "missing"
    assert snapshot(tmp_path) == before
