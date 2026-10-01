from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import app_factory
from quant_crypto.application.btc_domain_read_model import (
    BTCPublishedDomainReadModelUnavailable,
)
from scripts import start_backend_current_main as launcher


HEAD = "a" * 40
READ_MODEL_SHA256 = "b" * 64
AGGREGATION_BATCH_ID = "accepted-batch"
VALID_ENVIRONMENT = {
    "QS_BTC_RUNTIME_ARTIFACT_ROOT": "fixture",
    "QS_ALLOW_FIXTURE_FALLBACK": "false",
}
DEMO_ENVIRONMENT = {
    "QS_ALLOW_FIXTURE_FALLBACK": "false",
    "QS_BACKEND_EVIDENCE_PROFILE": "demo_quasi_live",
    "QS_BTC_DEMO_CONTROL_ENABLED": "true",
}
READONLY_ENVIRONMENT = {
    "QS_ALLOW_FIXTURE_FALLBACK": "false",
    "QS_BACKEND_EVIDENCE_PROFILE": "research_readonly",
    "QS_BTC_DEMO_CONTROL_ENABLED": "false",
}
MANAGEMENT_ENVIRONMENT = {
    "QS_ALLOW_FIXTURE_FALLBACK": "false",
    "QS_BACKEND_EVIDENCE_PROFILE": "candidate_management",
    "QS_BTC_DEMO_CONTROL_ENABLED": "false",
}


def test_candidate_management_reaches_configuration_guard(tmp_path, monkeypatch):
    _configure_success(monkeypatch, tmp_path)
    with pytest.raises(launcher.BackendCurrentMainLaunchError, match="candidate_management_configuration_blocked"):
        launcher.inspect_backend_identity(tmp_path, require_cwd=False, environment=MANAGEMENT_ENVIRONMENT)


@pytest.mark.parametrize("demo,fixture,expected", [
    ("false", "false", 0), ("true", "false", 1), ("", "false", 1), ("false", "true", 1)])
def test_candidate_management_powershell_profile_guard(demo, fixture, expected):
    powershell = Path("scripts/start_backend_current_main.ps1").read_text(encoding="utf-8")
    block = powershell[powershell.index("if ($env:QS_ALLOW_FIXTURE_FALLBACK"):
                       powershell.index("$guard = Join-Path")]
    script = ("$ErrorActionPreference='Stop';"
              "$env:QS_BACKEND_EVIDENCE_PROFILE='candidate_management';"
              f"$env:QS_ALLOW_FIXTURE_FALLBACK='{fixture}';$env:QS_BTC_DEMO_CONTROL_ENABLED='{demo}';"
              + block)
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], capture_output=True, text=True)
    assert (result.returncode == 0) == (expected == 0), result.stderr


def _candidate_configuration(tmp_path, monkeypatch):
    from scripts import candidate_management_deployment as deploy
    from quant_crypto.adapters import btc_runtime_artifact_store as roots
    repo = tmp_path / "checkout"; repo.mkdir()
    monkeypatch.setattr(roots, "git_worktree_roots", lambda _: [repo])
    target = tmp_path / "external-management"
    prepared = deploy.prepare(repo, target, "test-operator", "empty-v1")
    env = deploy.load_configuration(Path(prepared["configuration"]))
    env["QS_WEB_API_KEY"] = "isolated-test-only"
    return deploy, repo, target, env


def test_candidate_management_empty_prepare_check_and_get_never_write(tmp_path, monkeypatch):
    deploy, repo, target, env = _candidate_configuration(tmp_path, monkeypatch)
    before = {str(p): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert deploy.prepare(repo, target, "test-operator", "empty-v1")["status"] == "prepared_empty"
    checked = deploy.inspect_configuration(repo, env)
    assert checked["status"] == "configuration_checked"
    assert checked["inventory"] == {"accounts": 0, "sources": 0, "inputs": 0}
    assert checked["candidate_runnable"] is False and checked["offline_enabled"] is False
    from types import SimpleNamespace
    from backend.app.services.candidate_delivery_bootstrap import build_delivery_service, build_offline_service
    from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
    from backend.app.api.candidate_offline import build_candidate_offline_router
    from tools.agent_governance import git_metadata
    from fastapi import FastAPI
    monkeypatch.setattr(git_metadata, "current_branch_head", lambda _: ("main", HEAD))
    settings = SimpleNamespace(repo_root=repo, candidate_delivery_root=str(target),
        candidate_delivery_operator="test-operator", web_api_key=env["QS_WEB_API_KEY"],
        candidate_offline_catalog=env["QS_CANDIDATE_OFFLINE_CATALOG"],
        candidate_offline_catalog_sha256=env["QS_CANDIDATE_OFFLINE_CATALOG_SHA256"],
        candidate_offline_catalog_revision="empty-v1", candidate_offline_enabled=False,
        backend_evidence_profile="candidate_management", btc_demo_account_facts_approval_registry="")
    delivery = build_delivery_service(settings, archive=ResearchArchiveCatalog(repo_root=repo),
                                      qlib_root=target / "qlib", head=HEAD)
    offline = build_offline_service(settings, delivery)
    assert delivery.accounts.list() == []
    app = FastAPI(); app.include_router(build_candidate_offline_router(offline), prefix="/api")
    client = TestClient(app, headers={"X-API-Key": "isolated-test-only"})
    assert client.get("/api/candidate-offline/catalog").status_code == 200
    assert client.get("/api/candidate-offline/jobs").json()["jobs"] == []
    assert client.post("/api/candidate-offline/jobs", json={}).status_code == 423
    assert before == {str(p): p.read_bytes() for p in target.rglob("*") if p.is_file()}


@pytest.mark.parametrize("key", [
    "QS_CANDIDATE_DELIVERY_ROOT", "QS_CANDIDATE_DELIVERY_OPERATOR",
    "QS_CANDIDATE_OFFLINE_CATALOG", "QS_CANDIDATE_OFFLINE_CATALOG_SHA256",
    "QS_CANDIDATE_OFFLINE_CATALOG_REVISION", "QS_CANDIDATE_OFFLINE_ENABLED", "QS_WEB_API_KEY"])
def test_candidate_management_reports_exact_missing_fields(tmp_path, monkeypatch, key):
    deploy, repo, _, env = _candidate_configuration(tmp_path, monkeypatch)
    del env[key]
    result = deploy.inspect_configuration(repo, env)
    assert result["status"] == "blocked"
    assert ("candidate_management_authentication_missing" if key == "QS_WEB_API_KEY" else "missing:" + key) in result["blockers"]
    assert "isolated-test-only" not in json.dumps(result)


@pytest.mark.parametrize("change,expected", [
    ("hash", "offline_input_hash_mismatch"), ("revision", "offline_catalog_identity_mismatch"),
    ("owner", "candidate_management_owner_mismatch"), ("missing", "candidate_management_catalog_missing"),
    ("accounts", "candidate_management_accounts_missing")])
def test_candidate_management_external_configuration_tamper(tmp_path, monkeypatch, change, expected):
    deploy, repo, root, env = _candidate_configuration(tmp_path, monkeypatch)
    if change == "hash": env["QS_CANDIDATE_OFFLINE_CATALOG_SHA256"] = "0" * 64
    elif change == "revision": env["QS_CANDIDATE_OFFLINE_CATALOG_REVISION"] = "wrong-revision"
    elif change == "owner": (root / deploy.OWNER_FILE).write_text("{}")
    elif change == "missing": (root / "offline-catalog.json").unlink()
    else: (root / "accounts.json").unlink()
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert expected in deploy.inspect_configuration(repo, env)["blockers"]
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_candidate_management_create_only_and_secret_free_launcher(tmp_path, monkeypatch, capsys):
    deploy, repo, root, env = _candidate_configuration(tmp_path, monkeypatch)
    from quant_shared.strategy_delivery.models import DeliveryError
    changed = root / "accounts.json"; changed.write_text('{"existing":"preserve"}')
    with pytest.raises(DeliveryError, match="existing_file_conflict"): deploy.prepare(repo, root, "test-operator", "empty-v1")
    assert changed.read_text() == '{"existing":"preserve"}'
    with pytest.raises(DeliveryError, match="external_absolute"): deploy.prepare(repo, repo / "nested", "test-operator", "empty-v1")
    monkeypatch.setattr(launcher, "_registered_main_worktree", lambda _: repo)
    monkeypatch.setattr(deploy, "inspect_configuration", lambda *_: {"blockers": []})
    seen = []
    def capture(command, **kwargs):
        seen.append((command, kwargs))
        return type("Completed", (), {"returncode": 0})()
    monkeypatch.setattr(deploy.subprocess, "run", capture)
    monkeypatch.setenv("QS_WEB_API_KEY", "isolated-test-only")
    assert deploy.main(["check", "--config", str(root / "deployment.json")]) == 0
    command, kwargs = seen[0]
    assert "start_backend_current_main.ps1" in " ".join(command) and "-Check" in command
    assert kwargs["cwd"] == repo and kwargs["env"]["QS_WEB_API_KEY"] == "isolated-test-only"
    assert "isolated-test-only" not in " ".join(command) + capsys.readouterr().out
    assert "QS_WEB_API_KEY" not in (root / "deployment.json").read_text()


def test_candidate_management_python_accepts_configured_and_rejects_demo(tmp_path, monkeypatch):
    deploy, repo, _, env = _candidate_configuration(tmp_path, monkeypatch)
    _configure_success(monkeypatch, repo)
    monkeypatch.setattr(launcher, "_inspect_optional_promotion_artifact",
                        lambda *a, **k: {"status": "unavailable"})
    current = launcher.inspect_backend_identity(repo, require_cwd=False, environment=env)
    assert current["evidence_profile"] == "candidate_management"
    assert current["read_only"] is True and current["controls_disabled"] is True
    assert current["broker_or_order_allowed"] is False
    for key, value, error in [("QS_BTC_DEMO_CONTROL_ENABLED", "true", "control_must_be_false"),
                              ("QS_ALLOW_FIXTURE_FALLBACK", "true", "fixture_fallback_must_be_false")]:
        with pytest.raises(launcher.BackendCurrentMainLaunchError, match=error):
            launcher.inspect_backend_identity(repo, require_cwd=False, environment={**env, key: value})


def test_candidate_local_mode_without_password_preserves_metadata_guards(tmp_path, monkeypatch):
    deploy, repo, root, env = _candidate_configuration(tmp_path, monkeypatch)
    env.pop("QS_WEB_API_KEY")
    env["QS_CANDIDATE_AUTH_MODE"] = "local_no_password"
    assert deploy.inspect_configuration(repo, env)["status"] == "configuration_checked"
    assert deploy.inspect_configuration(repo, env)["offline_enabled"] is False
    for changed, expected in [
        ({"QS_CANDIDATE_AUTH_MODE":"anything"}, "auth_mode_invalid"),
        ({"QS_BACKEND_EVIDENCE_PROFILE":"research_readonly"}, "profile_required"),
        ({"QS_CANDIDATE_OFFLINE_CATALOG_SHA256":"0"*64}, "hash_mismatch"),
        ({"QS_CANDIDATE_OFFLINE_CATALOG_REVISION":"other"}, "identity_mismatch")]:
        assert any(expected in b for b in deploy.inspect_configuration(repo,{**env,**changed})["blockers"])
    monkeypatch.setattr(launcher, "_registered_main_worktree", lambda _: repo)
    monkeypatch.delenv("QS_WEB_API_KEY", raising=False)
    seen=[]
    def capture(command, **kwargs):
        seen.append((command,kwargs))
        return type("Completed",(),{"returncode":0})()
    monkeypatch.setattr(deploy.subprocess,"run",capture)
    before=(root/"deployment.json").read_bytes()
    assert deploy.main(["check","--config",str(root/"deployment.json"),"--auth-mode","local_no_password"])==0
    assert seen[0][1]["env"]["QS_CANDIDATE_AUTH_MODE"]=="local_no_password"
    assert not seen[0][1]["env"].get("QS_WEB_API_KEY")
    assert seen[0][1]["env"]["QS_CANDIDATE_OFFLINE_ENABLED"]=="false"
    assert before==(root/"deployment.json").read_bytes()
    source=Path("scripts/candidate_management_deployment.py").read_text()
    assert "getpass" not in source and "--prompt-auth" not in source


class _Reader:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root

    def sha256(self, _path: str) -> str:
        return READ_MODEL_SHA256


def _configure_success(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> None:
    def fake_git(_root: Path, *args: str) -> str:
        values = {
            ("config", "--bool", "core.sparseCheckout"): "true",
            ("branch", "--show-current"): "main",
            ("rev-parse", "HEAD"): HEAD,
            ("rev-parse", "refs/heads/main"): HEAD,
        }
        return values[args]

    monkeypatch.setattr(launcher, "_git", fake_git)
    monkeypatch.setattr(
        launcher,
        "_registered_main_worktree",
        lambda _root: root,
    )
    monkeypatch.setattr(launcher, "scoped_status", lambda *_args: [])
    monkeypatch.setattr(
        launcher.BTCRuntimeArtifactReader,
        "from_environment",
        lambda **_kwargs: _Reader(root / "runtime-a"),
    )
    monkeypatch.setattr(
        launcher.BTCPublishedDomainReadModelRepository,
        "read_published",
        lambda self, *, source_head: {
            "aggregation_batch_id": AGGREGATION_BATCH_ID,
            "source_head": source_head,
        },
    )
    monkeypatch.setattr(
        launcher,
        "inspect_backend_listener",
        lambda *_args: {"status": "available"},
    )


def test_launcher_accepts_only_registered_clean_sparse_current_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)

    identity = launcher.inspect_backend_identity(
        tmp_path,
        require_cwd=False,
        environment=VALID_ENVIRONMENT,
    )

    assert identity["canonical"] is True
    assert identity["source_head"] == HEAD
    assert identity["canonical_host"] == "127.0.0.1"
    assert identity["canonical_port"] == 8765
    assert identity["read_model_sha256"] == READ_MODEL_SHA256
    assert identity["aggregation_batch_id"] == AGGREGATION_BATCH_ID
    assert identity["artifact_root_binding_sha256"] == (
        launcher._path_binding_sha256(tmp_path / "runtime-a")
    )
    assert identity["evidence_profile"] == "promotion_strict"
    assert identity["promotion_artifact_status"] == "current"
    assert identity["paper_allowed"] is False
    assert identity["live_allowed"] is False


def test_launcher_rejects_noncanonical_port_before_inspection(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_canonical_port_required",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            port=8766,
            require_cwd=False,
        )


@pytest.mark.parametrize(
    ("git_args", "value", "error"),
    (
        (
            ("config", "--bool", "core.sparseCheckout"),
            "false",
            "worktree_not_sparse",
        ),
        (
            ("branch", "--show-current"),
            "agent/btc_developer/ticket",
            "backend_launcher_branch_not_main",
        ),
        (
            ("rev-parse", "HEAD"),
            "c" * 40,
            "backend_launcher_main_head_mismatch",
        ),
    ),
)
def test_launcher_rejects_sparse_branch_and_head_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    git_args: tuple[str, ...],
    value: str,
    error: str,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    original = launcher._git

    def changed(root: Path, *args: str) -> str:
        if args == git_args:
            return value
        return original(root, *args)

    monkeypatch.setattr(launcher, "_git", changed)

    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match=error,
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=VALID_ENVIRONMENT,
        )


def test_launcher_rejects_wrong_registered_root_and_dirty_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(
        launcher,
        "_registered_main_worktree",
        lambda _root: other,
    )
    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_launcher_not_registered_main_worktree",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=VALID_ENVIRONMENT,
        )

    monkeypatch.setattr(
        launcher,
        "_registered_main_worktree",
        lambda _root: tmp_path,
    )
    monkeypatch.setattr(
        launcher,
        "scoped_status",
        lambda *_args: [" M backend/app/api/app_factory.py"],
    )
    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_launcher_scoped_sources_dirty",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=VALID_ENVIRONMENT,
        )


def test_launcher_rejects_invalid_published_artifact_and_listener(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)

    def reject(self, *, source_head: str):
        raise BTCPublishedDomainReadModelUnavailable(
            "btc_published_domain_read_model_manifest_sha256_mismatch"
        )

    monkeypatch.setattr(
        launcher.BTCPublishedDomainReadModelRepository,
        "read_published",
        reject,
    )
    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="manifest_sha256_mismatch",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=VALID_ENVIRONMENT,
        )

    _configure_success(monkeypatch, tmp_path)
    monkeypatch.setattr(
        launcher,
        "inspect_backend_listener",
        lambda *_args: {"status": "unverified"},
    )
    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_launcher_unauthenticated_listener",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=VALID_ENVIRONMENT,
        )


def test_runtime_binding_latches_main_head_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    current = "d" * 40
    original = launcher._git

    def changed(root: Path, *args: str) -> str:
        if args in {
            ("rev-parse", "HEAD"),
            ("rev-parse", "refs/heads/main"),
        }:
            return current
        return original(root, *args)

    monkeypatch.setattr(launcher, "_git", changed)

    binding = launcher.inspect_backend_runtime_binding(
        tmp_path,
        launched_head=HEAD,
        environment=VALID_ENVIRONMENT,
    )

    assert binding["canonical"] is False
    assert binding["runtime_stale"] is True
    assert binding["error"] == "backend_runtime_main_head_drift"


def test_windows_launcher_chain_is_fixed_to_loopback_and_8765() -> None:
    cmd = Path("start-backend.cmd").read_text(encoding="utf-8")
    powershell = Path("scripts/start_backend_current_main.ps1").read_text(
        encoding="utf-8"
    )

    assert "start_backend_current_main.ps1" in cmd
    assert "start_backend_current_main.py" in powershell
    assert "'127.0.0.1'" in powershell
    assert "'8765'" in powershell
    assert "QS_BTC_RUNTIME_ARTIFACT_ROOT" in powershell
    assert "QS_ALLOW_FIXTURE_FALLBACK -cne 'false'" in powershell
    assert "QS_BACKEND_EVIDENCE_PROFILE" in powershell
    assert "demo_quasi_live" in powershell
    assert "QS_BTC_DEMO_CONTROL_ENABLED" in powershell
    assert "QS_CANONICAL_PYTHON" in powershell
    assert "backend_launcher_canonical_interpreter_missing" in powershell
    assert "backend_launcher_canonical_interpreter_outside_registered_main" in powershell
    assert "& $canonicalPython @arguments" in powershell


def test_windows_launcher_keeps_single_interpreter_candidate_as_full_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "launcher_candidate_fixture"
    single_candidate = root / ".venv" / "Scripts" / "python.exe"
    second_candidate = root / "venv" / "Scripts" / "python.exe"
    single_candidate.parent.mkdir(parents=True)
    single_candidate.write_bytes(b"")

    powershell = Path("scripts/start_backend_current_main.ps1").read_text(
        encoding="utf-8"
    )
    assert "@(\n    @(\n        $env:QS_CANONICAL_PYTHON" in powershell

    block_start = powershell.index("$pythonCandidates = @(")
    block_end = powershell.index(
        "$env:QS_CANONICAL_PYTHON = $canonicalPython", block_start
    )
    candidate_block = powershell[block_start:block_end]

    def run_candidate_selection(expected_count: int, expected_path: Path) -> None:
        root_literal = str(root).replace("'", "''")
        expected_literal = str(expected_path).replace("'", "''")
        script = f"""
$mainWorktree = '{root_literal}'
$env:QS_CANONICAL_PYTHON = $null
{candidate_block}
$expected = (Resolve-Path -LiteralPath '{expected_literal}').Path
if ($pythonCandidates.Count -ne {expected_count} -or $pythonCandidates[0] -ne $expected -or $canonicalPython -ne $expected) {{
    throw \"candidate selection was not full-path safe: count=$($pythonCandidates.Count), first=$($pythonCandidates[0]), canonical=$canonicalPython\"
}}
"""
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

    run_candidate_selection(1, single_candidate)
    second_candidate.parent.mkdir(parents=True)
    second_candidate.write_bytes(b"")
    run_candidate_selection(2, single_candidate)


def test_demo_launcher_rejects_orphan_writer_lock_before_spawning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spawned = False

    monkeypatch.setattr(
        launcher,
        "inspect_backend_identity",
        lambda *_args, **_kwargs: {
            "listener_status": "available",
            "evidence_profile": launcher.DEMO_QUASI_LIVE_PROFILE,
            "source_head": HEAD,
        },
    )
    monkeypatch.setattr(
        launcher,
        "inspect_demo_runtime_writer_lock",
        lambda: {
            "status": "held",
            "owner_pid": 4242,
            "owner_source_head": "c" * 40,
        },
        raising=False,
    )

    def reject_spawn(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("uvicorn must not start over a live writer lock")

    monkeypatch.setattr(launcher.subprocess, "run", reject_spawn)

    result = launcher.main(["--repo-root", str(tmp_path)])

    assert result == 2
    assert spawned is False
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "backend_demo_runtime_writer_lock_held"
    assert payload["paper_allowed"] is False
    assert payload["live_allowed"] is False
    assert payload["broker_or_order_allowed"] is False


def test_demo_launcher_allows_an_unlocked_stale_writer_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        launcher,
        "inspect_backend_identity",
        lambda *_args, **_kwargs: {
            "listener_status": "available",
            "evidence_profile": launcher.DEMO_QUASI_LIVE_PROFILE,
            "source_head": HEAD,
            "canonical": True,
        },
    )
    monkeypatch.setattr(
        launcher,
        "inspect_demo_runtime_writer_lock",
        lambda: {"status": "available"},
        raising=False,
    )

    result = launcher.main(
        ["--repo-root", str(tmp_path), "--check"]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


@pytest.mark.parametrize(
    "environment",
    (
        {"QS_BTC_RUNTIME_ARTIFACT_ROOT": "fixture"},
        {
            "QS_BTC_RUNTIME_ARTIFACT_ROOT": "fixture",
            "QS_ALLOW_FIXTURE_FALLBACK": "true",
        },
        {
            "QS_BTC_RUNTIME_ARTIFACT_ROOT": "fixture",
            "QS_ALLOW_FIXTURE_FALLBACK": "False",
        },
    ),
)
def test_launcher_requires_fixture_fallback_exactly_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
) -> None:
    _configure_success(monkeypatch, tmp_path)

    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_fixture_fallback_must_be_false",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=environment,
        )


def _listener_identity(root: Path) -> dict[str, object]:
    return {
        "canonical": True,
        "runtime_stale": False,
        "source_head": HEAD,
        "evidence_profile": "promotion_strict",
        "read_model_sha256": READ_MODEL_SHA256,
        "aggregation_batch_id": AGGREGATION_BATCH_ID,
        "artifact_root_binding_sha256": launcher._path_binding_sha256(
            root / "runtime-a"
        ),
    }


def test_demo_quasi_live_starts_without_promotion_artifact_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    monkeypatch.setattr(
        launcher.BTCRuntimeArtifactReader,
        "from_environment",
        lambda **_kwargs: (_ for _ in ()).throw(
            launcher.BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_env_missing"
            )
        ),
    )
    monkeypatch.setattr(
        launcher.BTCPublishedDomainReadModelRepository,
        "read_published",
        lambda *_args, **_kwargs: pytest.fail(
            "strict repository must not run in demo_quasi_live"
        ),
    )

    identity = launcher.inspect_backend_identity(
        tmp_path,
        require_cwd=False,
        environment=DEMO_ENVIRONMENT,
    )

    assert identity["canonical"] is True
    assert identity["runtime_stale"] is False
    assert identity["evidence_profile"] == "demo_quasi_live"
    assert identity["promotion_artifact_status"] == "unavailable"
    assert identity["source"] == {
        "head": HEAD,
        "main_head": HEAD,
        "branch": "main",
        "profile": "demo_quasi_live",
    }
    assert identity["paper_allowed"] is False
    assert identity["live_allowed"] is False
    assert identity["broker_or_order_allowed"] is False


def test_research_readonly_starts_without_promotion_artifact_or_demo_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    monkeypatch.setattr(
        launcher.BTCRuntimeArtifactReader,
        "from_environment",
        lambda **_kwargs: (_ for _ in ()).throw(
            launcher.BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_env_missing"
            )
        ),
    )

    identity = launcher.inspect_backend_identity(
        tmp_path,
        require_cwd=False,
        environment=READONLY_ENVIRONMENT,
    )

    assert identity["evidence_profile"] == "research_readonly"
    assert identity["promotion_artifact_status"] == "unavailable"
    assert identity["read_only"] is True
    assert identity["controls_disabled"] is True
    assert identity["paper_allowed"] is False
    assert identity["live_allowed"] is False
    assert identity["broker_or_order_allowed"] is False


def test_research_readonly_rejects_demo_control_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)

    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_research_readonly_control_must_be_false",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment={
                **READONLY_ENVIRONMENT,
                "QS_BTC_DEMO_CONTROL_ENABLED": "true",
            },
        )


def test_demo_quasi_live_records_stale_artifact_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)

    class DemoReader(_Reader):
        def read_json(self, _path: str) -> dict[str, object]:
            return {
                "source_head": "c" * 40,
                "aggregation_batch_id": "legacy",
                "blockers": ["legacy_promotion_blocker"],
            }

    monkeypatch.setattr(
        launcher.BTCRuntimeArtifactReader,
        "from_environment",
        lambda **_kwargs: DemoReader(tmp_path / "legacy-runtime"),
    )

    identity = launcher.inspect_backend_identity(
        tmp_path,
        require_cwd=False,
        environment=DEMO_ENVIRONMENT,
    )

    assert identity["canonical"] is True
    assert identity["promotion_artifact_status"] == "stale"
    assert identity["promotion_artifact"]["error"] == (
        "promotion_artifact_not_current_head_or_blocked"
    )


def test_demo_quasi_live_requires_control_and_listener_profile_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    without_control = {
        **DEMO_ENVIRONMENT,
        "QS_BTC_DEMO_CONTROL_ENABLED": "false",
    }
    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_demo_control_must_be_true",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=without_control,
        )

    monkeypatch.setattr(
        launcher.BTCRuntimeArtifactReader,
        "from_environment",
        lambda **_kwargs: (_ for _ in ()).throw(
            launcher.BTCRuntimeArtifactStoreError(
                "btc_runtime_artifact_root_env_missing"
            )
        ),
    )
    observed = _listener_identity(tmp_path)
    monkeypatch.setattr(
        launcher,
        "inspect_backend_listener",
        lambda *_args: {
            "status": "authenticated",
            "identity": observed,
        },
    )
    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_launcher_listener_identity_mismatch",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=DEMO_ENVIRONMENT,
        )


def test_backend_identity_route_is_query_free_and_launcher_accepts_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _listener_identity(tmp_path)
    monkeypatch.setenv("QS_BACKEND_CANONICAL_LAUNCH", "1")
    monkeypatch.setenv("QS_BACKEND_LAUNCHED_HEAD", HEAD)
    monkeypatch.setattr(
        launcher,
        "inspect_backend_runtime_binding",
        lambda *_args, **_kwargs: expected,
    )
    monkeypatch.setattr(
        app_factory,
        "current_branch_head",
        lambda _root: ("main", HEAD),
    )

    app = app_factory.create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", "") == "/__backend_identity"
    )
    assert all(
        parameter.name != "response"
        for parameter in route.dependant.query_params
    )

    response = TestClient(app).get("/__backend_identity")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == expected

    _configure_success(monkeypatch, tmp_path)
    monkeypatch.setattr(
        launcher,
        "inspect_backend_listener",
        lambda *_args: {
            "status": "authenticated",
            "identity": response.json(),
        },
    )

    identity = launcher.inspect_backend_identity(
        tmp_path,
        require_cwd=False,
        environment=VALID_ENVIRONMENT,
    )

    assert identity["listener_status"] == "authenticated"


def test_backend_runtime_guard_latches_full_inspection_and_uses_cheap_head_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _listener_identity(tmp_path)
    inspection_calls = 0
    head_reads = 0

    def inspect_once(*_args, **_kwargs):
        nonlocal inspection_calls
        inspection_calls += 1
        return expected

    def read_head(_root: Path) -> tuple[str, str]:
        nonlocal head_reads
        head_reads += 1
        return "main", HEAD

    monkeypatch.setenv("QS_BACKEND_CANONICAL_LAUNCH", "1")
    monkeypatch.setenv("QS_BACKEND_LAUNCHED_HEAD", HEAD)
    monkeypatch.setattr(launcher, "inspect_backend_runtime_binding", inspect_once)
    monkeypatch.setattr(app_factory, "current_branch_head", read_head)

    app = app_factory.create_app()
    assert inspection_calls == 1

    paths = ["/api/health", "/__backend_identity"] * 4
    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(client.get, paths))

    assert [response.status_code for response in responses] == [200] * len(paths)
    assert inspection_calls == 1
    assert head_reads == len(paths)


@pytest.mark.parametrize("failure_mode", ["head_changed", "head_read_failed"])
def test_backend_runtime_guard_latches_cheap_head_drift_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    expected = _listener_identity(tmp_path)
    inspection_calls = 0

    def inspect_once(*_args, **_kwargs):
        nonlocal inspection_calls
        inspection_calls += 1
        return expected

    def read_head(_root: Path) -> tuple[str, str]:
        if failure_mode == "head_read_failed":
            raise app_factory.GitMetadataError("synthetic_head_read_failure")
        return "main", "c" * 40

    monkeypatch.setenv("QS_BACKEND_CANONICAL_LAUNCH", "1")
    monkeypatch.setenv("QS_BACKEND_LAUNCHED_HEAD", HEAD)
    monkeypatch.setattr(launcher, "inspect_backend_runtime_binding", inspect_once)
    monkeypatch.setattr(app_factory, "current_branch_head", read_head)

    client = TestClient(app_factory.create_app())
    response = client.get("/api/health")

    assert response.status_code == 409
    payload = response.json()
    assert payload["paper_allowed"] is False
    assert payload["live_allowed"] is False
    assert payload["broker_or_order_allowed"] is False
    assert payload["identity"]["runtime_stale"] is True
    assert payload["identity"]["canonical"] is False
    assert payload["identity"]["error"] == (
        "backend_runtime_main_head_drift"
        if failure_mode == "head_changed"
        else "backend_runtime_main_head_read_failed"
    )
    assert inspection_calls == 1


def test_backend_identity_route_preserves_main_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_identity = {
        "schema_version": "backend_current_main_identity_v1",
        "canonical": False,
        "runtime_stale": True,
        "source_head": HEAD,
        "error": "backend_runtime_main_head_drift",
    }
    monkeypatch.setenv("QS_BACKEND_CANONICAL_LAUNCH", "1")
    monkeypatch.setenv("QS_BACKEND_LAUNCHED_HEAD", HEAD)
    monkeypatch.setattr(
        launcher,
        "inspect_backend_runtime_binding",
        lambda *_args, **_kwargs: stale_identity,
    )

    response = TestClient(app_factory.create_app()).get("/__backend_identity")

    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "status": "blocked",
        "error": "backend_runtime_main_drift",
        "identity": stale_identity,
        "paper_allowed": False,
        "live_allowed": False,
        "broker_or_order_allowed": False,
    }


def test_launcher_accepts_authenticated_listener_with_exact_root_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    monkeypatch.setattr(
        launcher,
        "inspect_backend_listener",
        lambda *_args: {
            "status": "authenticated",
            "identity": _listener_identity(tmp_path),
        },
    )

    identity = launcher.inspect_backend_identity(
        tmp_path,
        require_cwd=False,
        environment=VALID_ENVIRONMENT,
    )

    assert identity["listener_status"] == "authenticated"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("read_model_sha256", "c" * 64),
        ("aggregation_batch_id", "different-batch"),
        ("artifact_root_binding_sha256", "d" * 64),
    ),
)
def test_launcher_rejects_listener_with_different_accepted_root_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    _configure_success(monkeypatch, tmp_path)
    observed = _listener_identity(tmp_path)
    observed[field] = value
    monkeypatch.setattr(
        launcher,
        "inspect_backend_listener",
        lambda *_args: {
            "status": "authenticated",
            "identity": observed,
        },
    )

    with pytest.raises(
        launcher.BackendCurrentMainLaunchError,
        match="backend_launcher_listener_identity_mismatch",
    ):
        launcher.inspect_backend_identity(
            tmp_path,
            require_cwd=False,
            environment=VALID_ENVIRONMENT,
        )
