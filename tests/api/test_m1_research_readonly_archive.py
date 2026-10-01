from dataclasses import replace
import os
from pathlib import Path
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _research_readonly_client(monkeypatch, tmp_path, *, catalog=None):
    from backend.app.api import app_factory
    from backend.app.services.task_queue import TaskQueueService

    monkeypatch.setattr(
        app_factory,
        "settings",
        replace(
            app_factory.settings,
            repo_root=REPO_ROOT,
            backend_evidence_profile="research_readonly",
            btc_demo_control_enabled=False,
            allow_fixture_fallback=False,
        ),
    )
    monkeypatch.setattr(app_factory, "QLIB_ARTIFACTS_ROOT", tmp_path / "local-qlib")
    monkeypatch.setattr(app_factory, "task_queue_service", TaskQueueService(max_workers=1))
    if catalog is not None:
        monkeypatch.setattr(
            app_factory,
            "build_m1_research_archive_catalog",
            lambda **_: catalog,
        )
    return TestClient(app_factory.create_app())


def test_m1_archive_catalog_is_server_owned_and_fixed():
    from backend.app.services.research_archive_discovery import (
        M1_FACTORY_RUN_IDS,
        M1_MANIFEST_GIT_SPEC,
        M1_QLIB_RUN_IDS,
    )

    assert M1_MANIFEST_GIT_SPEC == (
        "165a446729f8c114748e1b20bbfcf0c91e75066e:"
        ".agent/data_manifests/m1-trend-environment-acceptance/"
        "m1-okx-59f5eb861-20260911.json"
    )
    assert M1_FACTORY_RUN_IDS == ("m1-okx-factory",)
    assert M1_QLIB_RUN_IDS == (
        "m1-okx-qlib",
        "m1-okx-factory-input",
        "m1-okx-factory-t1-fold1",
        "m1-okx-factory-t1-fold2",
        "m1-okx-factory-t1-fold3",
        "m1-okx-factory-t1-fold4",
    )
    assert all("/" not in run_id and "\\" not in run_id for run_id in (*M1_QLIB_RUN_IDS, *M1_FACTORY_RUN_IDS))


def test_canonical_four_gets_discover_verified_archive_without_writes(monkeypatch, tmp_path):
    from backend.app.services.research_archive_discovery import (
        M1_FACTORY_RUN_IDS,
        M1_MANIFEST_GIT_SPEC,
        M1_QLIB_RUN_IDS,
    )
    from tools.agent_governance.shared_data import (
        default_shared_data_root,
        load_manifest_from_git,
        resolve_manifest_payload,
    )

    manifest = load_manifest_from_git(REPO_ROOT, M1_MANIFEST_GIT_SPEC)
    archive_root = resolve_manifest_payload(
        manifest,
        shared_root=default_shared_data_root(REPO_ROOT),
        verify_files=True,
    )
    before = {
        item["path"]: (
            (archive_root / item["path"]).stat().st_size,
            (archive_root / item["path"]).stat().st_mtime_ns,
        )
        for item in manifest["files"]
    }

    client = _research_readonly_client(monkeypatch, tmp_path)
    qlib_list = client.get("/api/integrations/qlib/runs")
    qlib_detail = client.get("/api/integrations/qlib/runs/m1-okx-qlib")
    factory_list = client.get("/api/research/alpha-factory")
    factory_detail = client.get("/api/research/alpha-factory/runs/m1-okx-factory")

    assert [response.status_code for response in (qlib_list, qlib_detail, factory_list, factory_detail)] == [200] * 4
    assert set(M1_QLIB_RUN_IDS).issubset({row["run_id"] for row in qlib_list.json()["runs"]})
    assert set(M1_FACTORY_RUN_IDS).issubset({row["run_id"] for row in factory_list.json()["runs"]})
    assert qlib_detail.json()["integrity_status"] == "passed"
    assert qlib_detail.json()["trend_environment"]["source_stale"] is True
    assert qlib_detail.json()["summary"]["paths"]["run_root"].startswith("shared-data://")
    assert factory_detail.json()["integrity_status"] == "passed"
    assert factory_detail.json()["decision"] == "rejected"
    assert factory_detail.json()["source_stale"] is True
    for payload in (qlib_list.json(), qlib_detail.json(), factory_list.json(), factory_detail.json()):
        rendered = str(payload)
        assert str(default_shared_data_root(REPO_ROOT)) not in rendered
        assert "private_endpoint" not in rendered or "True" not in rendered
    assert client.get("/api/integrations/qlib/runs/unknown-run").status_code == 404
    assert client.get("/api/research/alpha-factory/runs/unknown-run").status_code == 404
    assert not (tmp_path / "local-qlib").exists()
    assert not (REPO_ROOT / "artifacts" / "alpha_factory_runs").exists()
    after = {
        item["path"]: (
            (archive_root / item["path"]).stat().st_size,
            (archive_root / item["path"]).stat().st_mtime_ns,
        )
        for item in manifest["files"]
    }
    assert after == before


class _UnavailableCatalog:
    def __init__(self, reason):
        self.reason = reason

    def _fail(self):
        from backend.app.services.research_archive_discovery import ResearchArchiveUnavailable

        raise ResearchArchiveUnavailable(self.reason)

    def list_qlib_runs(self, *_):
        self._fail()

    def resolve_qlib_run(self, *_):
        self._fail()

    def list_factory_runs(self, *_):
        self._fail()

    def resolve_factory_run(self, *_):
        self._fail()


@pytest.mark.parametrize(
    "reason",
    [
        "shared_data_manifest_git_read_failed",
        "shared_data_file_hash_mismatch:state.json",
        "readonly_archive_factory_seal_invalid",
    ],
)
def test_four_gets_fail_closed_when_archive_is_missing_or_corrupt(monkeypatch, tmp_path, reason):
    client = _research_readonly_client(
        monkeypatch,
        tmp_path,
        catalog=_UnavailableCatalog(reason),
    )
    responses = (
        client.get("/api/integrations/qlib/runs"),
        client.get("/api/integrations/qlib/runs/m1-okx-qlib"),
        client.get("/api/research/alpha-factory"),
        client.get("/api/research/alpha-factory/runs/m1-okx-factory"),
    )
    assert [response.status_code for response in responses] == [503] * 4
    assert all(reason in response.text for response in responses)


def test_duplicate_local_and_archive_ids_fail_closed_on_both_catalogs(monkeypatch, tmp_path):
    from backend.app.api.alpha_factory import build_alpha_factory_router
    from backend.app.services.alpha_factory import AlphaFactoryService
    from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
    from backend.app.services.task_queue import TaskQueueService

    qlib_duplicate = tmp_path / "local-qlib" / "m1-okx-qlib"
    qlib_duplicate.mkdir(parents=True)
    client = _research_readonly_client(monkeypatch, tmp_path)
    assert client.get("/api/integrations/qlib/runs").status_code == 409
    assert client.get("/api/integrations/qlib/runs/m1-okx-qlib").status_code == 409

    factory_root = tmp_path / "local-factory"
    (factory_root / "m1-okx-factory").mkdir(parents=True)
    service = AlphaFactoryService(
        root=factory_root,
        qlib_root=tmp_path / "factory-qlib",
        queue=TaskQueueService(max_workers=1),
        readonly_archive=ResearchArchiveCatalog(repo_root=REPO_ROOT),
    )
    app = FastAPI()
    app.include_router(
        build_alpha_factory_router(service=service, verify_api_key=lambda: None),
        prefix="/api",
    )
    factory_client = TestClient(app)
    assert factory_client.get("/api/research/alpha-factory").status_code == 409
    assert factory_client.get("/api/research/alpha-factory/runs/m1-okx-factory").status_code == 409


def test_archive_path_escape_and_user_selectors_are_rejected(monkeypatch, tmp_path):
    from backend.app.services.research_archive_discovery import (
        M1_MANIFEST_GIT_SPEC,
        ResearchArchiveCatalog,
        ResearchArchiveUnavailable,
    )
    from tools.agent_governance.shared_data import load_manifest_from_git

    manifest = load_manifest_from_git(REPO_ROOT, M1_MANIFEST_GIT_SPEC)
    catalog = ResearchArchiveCatalog(
        repo_root=REPO_ROOT,
        shared_root=tmp_path / "shared",
        manifest_loader=lambda *_: manifest,
        manifest_resolver=lambda *_args, **_kwargs: tmp_path / "outside",
    )
    with pytest.raises(ResearchArchiveUnavailable, match="resolved_path_mismatch"):
        catalog.list_qlib_runs(tmp_path / "local")

    client = _research_readonly_client(monkeypatch, tmp_path / "api")
    for path in (
        "/api/integrations/qlib/runs",
        "/api/integrations/qlib/runs/m1-okx-qlib",
        "/api/research/alpha-factory",
        "/api/research/alpha-factory/runs/m1-okx-factory",
    ):
        for selector in ("manifest", "manifest_git_spec", "path", "ref", "root", "shared_root"):
            response = client.get(path, params={selector: "attacker-controlled"})
            assert response.status_code == 400, (path, selector, response.text)
            assert "server_owned" in response.text


def test_archive_location_carries_current_request_manifest_hashes(
    monkeypatch,
    tmp_path,
):
    from backend.app.services.research_archive_discovery import (
        M1_DATASET_ID,
        M1_DATASET_VERSION,
        M1_QLIB_RUN_IDS,
        ResearchArchiveCatalog,
    )

    shared_root = tmp_path / "shared"
    dataset_root = (
        shared_root / "datasets" / M1_DATASET_ID / M1_DATASET_VERSION
    )
    for run_id in M1_QLIB_RUN_IDS:
        (dataset_root / "qlib_runs" / run_id).mkdir(parents=True)
    manifest = {
        "files": [
            {
                "path": f"qlib_runs/{M1_QLIB_RUN_IDS[0]}/run_seal.json",
                "sha256": "a" * 64,
                "bytes": 123,
            },
            {
                "path": f"qlib_runs/{M1_QLIB_RUN_IDS[0]}/pipeline_result.json",
                "sha256": "b" * 64,
                "bytes": 456,
            },
        ]
    }
    verify_flags = []

    def resolve(_manifest, *, shared_root, verify_files):
        verify_flags.append(verify_files)
        return dataset_root

    monkeypatch.setattr(
        ResearchArchiveCatalog,
        "_validate_fixed_manifest",
        staticmethod(lambda _manifest: None),
    )
    catalog = ResearchArchiveCatalog(
        repo_root=REPO_ROOT,
        shared_root=shared_root,
        manifest_loader=lambda *_: manifest,
        manifest_resolver=resolve,
    )

    locations = catalog.list_qlib_runs(tmp_path / "local")
    first = next(item for item in locations if item.run_id == M1_QLIB_RUN_IDS[0])

    assert verify_flags == [True]
    assert first.verified_files == {
        "run_seal.json": {"sha256": "a" * 64, "bytes": 123},
        "pipeline_result.json": {"sha256": "b" * 64, "bytes": 456},
    }
    assert first.provenance["integrity_validation"] == (
        "shared_manifest_sha256_current_request"
    )


@pytest.mark.parametrize("case", ["parent", "absolute", "symlink"])
def test_factory_archive_mode_preserves_local_run_id_and_containment_validation(
    tmp_path,
    case,
):
    from backend.app.services.alpha_factory import AlphaFactoryService
    from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
    from backend.app.services.task_queue import TaskQueueService
    from quant_shared.alpha_factory.contracts import FactoryError

    local_root = tmp_path / "local-factory"
    local_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if case == "parent":
        run_id = ".."
    elif case == "absolute":
        run_id = str(outside.resolve())
    else:
        link = local_root / "escaped-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            if os.name != "nt":
                pytest.skip(f"directory symlink unavailable: {exc}")
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode:
                pytest.skip(
                    "directory symlink and junction unavailable: "
                    + completed.stderr.strip()
                )
        run_id = link.name

    service = AlphaFactoryService(
        root=local_root,
        qlib_root=tmp_path / "qlib",
        queue=TaskQueueService(max_workers=1),
        readonly_archive=ResearchArchiveCatalog(repo_root=REPO_ROOT),
    )
    with pytest.raises(FactoryError, match="invalid_factory_run_id|factory_path_escape"):
        service.get(run_id)


def test_archive_unavailable_responses_redact_physical_paths(monkeypatch, tmp_path):
    from backend.app.api.alpha_factory import build_alpha_factory_router
    from backend.app.services.alpha_factory import AlphaFactoryService
    from backend.app.services.research_archive_discovery import (
        M1_MANIFEST_GIT_SPEC,
        ReadonlyRunLocation,
        ResearchArchiveCatalog,
    )
    from backend.app.services.task_queue import TaskQueueService
    from tools.agent_governance.shared_data import SharedDataError, load_manifest_from_git

    sensitive_root = (tmp_path / "private-shared-data-root").resolve()
    manifest = load_manifest_from_git(REPO_ROOT, M1_MANIFEST_GIT_SPEC)
    catalog = ResearchArchiveCatalog(
        repo_root=REPO_ROOT,
        shared_root=sensitive_root,
        manifest_loader=lambda *_: manifest,
        manifest_resolver=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SharedDataError(f"hash mismatch under {sensitive_root}")
        ),
    )
    client = _research_readonly_client(monkeypatch, tmp_path / "qlib-api", catalog=catalog)
    response = client.get("/api/integrations/qlib/runs")
    assert response.status_code == 503
    assert str(sensitive_root) not in response.json()["detail"]

    malformed_root = tmp_path / "malformed-archive" / "m1-okx-factory"
    (malformed_root / "state.json").mkdir(parents=True)

    class _MalformedFactoryCatalog:
        def resolve_factory_run(self, *_):
            return ReadonlyRunLocation(
                run_id="m1-okx-factory",
                run_root=malformed_root,
                qlib_root=tmp_path / "qlib",
                logical_root="shared-data://redacted/m1-okx-factory",
                provenance={"storage": "immutable_shared_data"},
            )

    service = AlphaFactoryService(
        root=tmp_path / "local-factory",
        qlib_root=tmp_path / "qlib",
        queue=TaskQueueService(max_workers=1),
        readonly_archive=_MalformedFactoryCatalog(),
    )
    app = FastAPI()
    app.include_router(
        build_alpha_factory_router(service=service, verify_api_key=lambda: None),
        prefix="/api",
    )
    response = TestClient(app).get(
        "/api/research/alpha-factory/runs/m1-okx-factory"
    )
    assert response.status_code == 503
    assert str(malformed_root) not in response.json()["detail"]
