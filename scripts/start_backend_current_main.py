#!/usr/bin/env python3
"""Fail-closed launcher for the canonical current-main backend."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.adapters.btc_domain_read_model_repository import (  # noqa: E402
    BTCPublishedDomainReadModelRepository,
)
from quant_crypto.adapters.btc_runtime_artifact_store import (  # noqa: E402
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactStoreError,
)
from quant_crypto.application.btc_domain_read_model import (  # noqa: E402
    BTCPublishedDomainReadModelUnavailable,
)
from tools.agent_governance.safe_status import scoped_status  # noqa: E402


CANONICAL_BRANCH = "main"
CANONICAL_HOST = "127.0.0.1"
CANONICAL_PORT = 8765
LISTENER_IDENTITY_TIMEOUT_SECONDS = 10.0
LAUNCH_ENVIRONMENT = "QS_BACKEND_CANONICAL_LAUNCH"
LAUNCHED_HEAD_ENVIRONMENT = "QS_BACKEND_LAUNCHED_HEAD"
FIXTURE_FALLBACK_ENVIRONMENT = "QS_ALLOW_FIXTURE_FALLBACK"
EVIDENCE_PROFILE_ENVIRONMENT = "QS_BACKEND_EVIDENCE_PROFILE"
DEMO_CONTROL_ENVIRONMENT = "QS_BTC_DEMO_CONTROL_ENABLED"
PROMOTION_STRICT_PROFILE = "promotion_strict"
DEMO_QUASI_LIVE_PROFILE = "demo_quasi_live"
RESEARCH_READONLY_PROFILE = "research_readonly"
CANDIDATE_MANAGEMENT_PROFILE = "candidate_management"
EVIDENCE_PROFILES = {
    PROMOTION_STRICT_PROFILE,
    DEMO_QUASI_LIVE_PROFILE,
    RESEARCH_READONLY_PROFILE,
    CANDIDATE_MANAGEMENT_PROFILE,
}
BTC_DOMAIN_READ_MODEL_LOGICAL_PATH = (
    "artifacts/btc_domain_read_model/latest/"
    "btc_domain_read_model.json"
)
DEMO_RUNTIME_WRITER_LOCK_RELATIVE_PATH = Path(
    "quant-system/btc_demo_paper_runtime/"
    ".btc_okx_demo_fault_drill_writer.lock"
)
DIRTY_SCOPES = (
    "backend",
    "quant_crypto",
    "scripts/start_backend_current_main.py",
    "scripts/start_backend_current_main.ps1",
    "start-backend.cmd",
    "scripts/candidate_management_deployment.py",
)


class BackendCurrentMainLaunchError(RuntimeError):
    """Stable launcher failure without physical-path disclosure."""

    def __init__(self, code, *, blockers=None):
        super().__init__(code)
        self.blockers = list(blockers or [])


def inspect_backend_identity(
    repo_root: Path,
    *,
    port: int = CANONICAL_PORT,
    require_cwd: bool = True,
    check_listener: bool = True,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    if port != CANONICAL_PORT:
        raise BackendCurrentMainLaunchError(
            "backend_canonical_port_required"
        )
    if require_cwd and not _same_path(Path.cwd(), root):
        raise BackendCurrentMainLaunchError(
            "backend_launcher_cwd_not_registered_main"
        )
    sparse = _git(root, "config", "--bool", "core.sparseCheckout")
    if sparse != "true":
        raise BackendCurrentMainLaunchError("worktree_not_sparse")
    branch = _git(root, "branch", "--show-current")
    if branch != CANONICAL_BRANCH:
        raise BackendCurrentMainLaunchError(
            "backend_launcher_branch_not_main"
        )
    source_head = _git(root, "rev-parse", "HEAD")
    main_head = _git(root, "rev-parse", "refs/heads/main")
    if source_head != main_head:
        raise BackendCurrentMainLaunchError(
            "backend_launcher_main_head_mismatch"
        )
    main_worktree = _registered_main_worktree(root)
    if not _same_path(root, main_worktree):
        raise BackendCurrentMainLaunchError(
            "backend_launcher_not_registered_main_worktree"
        )
    if scoped_status(root, DIRTY_SCOPES):
        raise BackendCurrentMainLaunchError(
            "backend_launcher_scoped_sources_dirty"
        )

    values = os.environ if environment is None else environment
    if values.get(FIXTURE_FALLBACK_ENVIRONMENT) != "false":
        raise BackendCurrentMainLaunchError(
            "backend_fixture_fallback_must_be_false"
        )
    evidence_profile = (
        values.get(
            EVIDENCE_PROFILE_ENVIRONMENT,
            PROMOTION_STRICT_PROFILE,
        )
        .strip()
        .lower()
    )
    if evidence_profile not in EVIDENCE_PROFILES:
        raise BackendCurrentMainLaunchError(
            "backend_evidence_profile_invalid"
        )
    if (
        evidence_profile == DEMO_QUASI_LIVE_PROFILE
        and values.get(DEMO_CONTROL_ENVIRONMENT) != "true"
    ):
        raise BackendCurrentMainLaunchError(
            "backend_demo_control_must_be_true"
        )
    if (
        evidence_profile == RESEARCH_READONLY_PROFILE
        and values.get(DEMO_CONTROL_ENVIRONMENT) != "false"
    ):
        raise BackendCurrentMainLaunchError(
            "backend_research_readonly_control_must_be_false"
        )
    if evidence_profile == CANDIDATE_MANAGEMENT_PROFILE:
        if values.get(DEMO_CONTROL_ENVIRONMENT) != "false":
            raise BackendCurrentMainLaunchError("backend_candidate_management_control_must_be_false")
        from scripts.candidate_management_deployment import inspect_configuration
        configuration = inspect_configuration(root, values)
        if configuration["blockers"]:
            raise BackendCurrentMainLaunchError("candidate_management_configuration_blocked",
                                              blockers=configuration["blockers"])
    if evidence_profile == PROMOTION_STRICT_PROFILE:
        promotion_artifact = _inspect_strict_promotion_artifact(
            root,
            source_head=source_head,
            environment=values,
        )
    else:
        promotion_artifact = _inspect_optional_promotion_artifact(
            root,
            source_head=source_head,
            environment=values,
        )

    read_model_sha256 = str(
        promotion_artifact.get("read_model_sha256") or ""
    )
    aggregation_batch_id = str(
        promotion_artifact.get("aggregation_batch_id") or ""
    )
    artifact_root_binding_sha256 = str(
        promotion_artifact.get("artifact_root_binding_sha256") or ""
    )
    listener = (
        inspect_backend_listener(CANONICAL_HOST, port)
        if check_listener
        else {"status": "not_checked"}
    )
    if listener["status"] == "unverified":
        raise BackendCurrentMainLaunchError(
            "backend_launcher_unauthenticated_listener"
        )
    if listener["status"] == "authenticated":
        observed = listener.get("identity")
        if (
            not isinstance(observed, Mapping)
            or observed.get("canonical") is not True
            or observed.get("runtime_stale") is True
            or observed.get("source_head") != source_head
            or observed.get("evidence_profile") != evidence_profile
            or (
                evidence_profile == PROMOTION_STRICT_PROFILE
                and (
                    observed.get("read_model_sha256")
                    != read_model_sha256
                    or observed.get("aggregation_batch_id")
                    != aggregation_batch_id
                    or observed.get("artifact_root_binding_sha256")
                    != artifact_root_binding_sha256
                )
            )
        ):
            raise BackendCurrentMainLaunchError(
                "backend_launcher_listener_identity_mismatch"
            )

    return {
        "schema_version": "backend_current_main_identity_v1",
        "canonical": True,
        "runtime_stale": False,
        "source_head": source_head,
        "main_head": main_head,
        "evidence_profile": evidence_profile,
        "source": {
            "head": source_head,
            "main_head": main_head,
            "branch": CANONICAL_BRANCH,
            "profile": evidence_profile,
        },
        "promotion_artifact": promotion_artifact,
        "promotion_artifact_status": promotion_artifact["status"],
        "canonical_branch": CANONICAL_BRANCH,
        "canonical_host": CANONICAL_HOST,
        "canonical_port": CANONICAL_PORT,
        "read_model_sha256": read_model_sha256,
        "aggregation_batch_id": aggregation_batch_id,
        "artifact_root_binding_sha256": artifact_root_binding_sha256,
        "listener_status": listener["status"],
        "read_only": evidence_profile in {RESEARCH_READONLY_PROFILE, CANDIDATE_MANAGEMENT_PROFILE},
        "controls_disabled": (
            evidence_profile == RESEARCH_READONLY_PROFILE
            or values.get(DEMO_CONTROL_ENVIRONMENT) != "true"
        ),
        "research_completion_grants_trading": False,
        "paper_allowed": False,
        "live_allowed": False,
        "broker_or_order_allowed": False,
    }


def _inspect_strict_promotion_artifact(
    root: Path,
    *,
    source_head: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    try:
        reader = BTCRuntimeArtifactReader.from_environment(
            source_repo_root=root,
            environment=environment,
        )
        payload = BTCPublishedDomainReadModelRepository(
            repo_root=root,
            artifact_reader=reader,
        ).read_published(source_head=source_head)
    except (
        BTCRuntimeArtifactStoreError,
        BTCPublishedDomainReadModelUnavailable,
    ) as exc:
        code = str(exc).strip().split(":", 1)[0]
        raise BackendCurrentMainLaunchError(code) from exc
    return {
        "status": "current",
        "read_model_sha256": reader.sha256(
            BTC_DOMAIN_READ_MODEL_LOGICAL_PATH
        ),
        "aggregation_batch_id": str(
            payload.get("aggregation_batch_id") or ""
        ),
        "artifact_root_binding_sha256": _path_binding_sha256(
            reader.artifact_root
        ),
        "error": "",
    }


def _inspect_optional_promotion_artifact(
    root: Path,
    *,
    source_head: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    try:
        reader = BTCRuntimeArtifactReader.from_environment(
            source_repo_root=root,
            environment=environment,
        )
        payload = reader.read_json(BTC_DOMAIN_READ_MODEL_LOGICAL_PATH)
    except (BTCRuntimeArtifactStoreError, OSError, ValueError) as exc:
        return {
            "status": "unavailable",
            "read_model_sha256": "",
            "aggregation_batch_id": "",
            "artifact_root_binding_sha256": "",
            "error": str(exc).strip().split(":", 1)[0],
        }
    artifact_head = str(
        payload.get("source_head") or payload.get("code_commit") or ""
    )
    blockers = payload.get("blockers")
    stale = (
        artifact_head != source_head
        or (isinstance(blockers, list) and bool(blockers))
    )
    return {
        "status": "stale" if stale else "current",
        "read_model_sha256": reader.sha256(
            BTC_DOMAIN_READ_MODEL_LOGICAL_PATH
        ),
        "aggregation_batch_id": str(
            payload.get("aggregation_batch_id") or ""
        ),
        "artifact_root_binding_sha256": _path_binding_sha256(
            reader.artifact_root
        ),
        "error": (
            "promotion_artifact_not_current_head_or_blocked"
            if stale
            else ""
        ),
    }


def inspect_backend_runtime_binding(
    repo_root: Path,
    *,
    launched_head: str,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    try:
        current = inspect_backend_identity(
            repo_root,
            require_cwd=False,
            check_listener=False,
            environment=environment,
        )
    except BackendCurrentMainLaunchError as exc:
        return {
            "schema_version": "backend_current_main_identity_v1",
            "canonical": False,
            "runtime_stale": True,
            "source_head": launched_head,
            "current_main_head": "",
            "error": str(exc).split(":", 1)[0],
        }
    if current["source_head"] != launched_head:
        return {
            **current,
            "canonical": False,
            "runtime_stale": True,
            "source_head": launched_head,
            "current_main_head": current["main_head"],
            "error": "backend_runtime_main_head_drift",
        }
    return current


def inspect_backend_listener(host: str, port: int) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            pass
    except OSError:
        return {"status": "available"}
    connection = http.client.HTTPConnection(
        host,
        port,
        timeout=LISTENER_IDENTITY_TIMEOUT_SECONDS,
    )
    try:
        connection.request("GET", "/__backend_identity")
        response = connection.getresponse()
        raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "unverified"}
    finally:
        connection.close()
    if response.status not in {200, 409} or not isinstance(payload, dict):
        return {"status": "unverified"}
    return {"status": "authenticated", "identity": payload}


def inspect_demo_runtime_writer_lock() -> dict[str, Any]:
    """Probe the external Demo writer lock without mutating its marker.

    A canonical listener may legitimately own this lock.  The launcher calls
    this probe only when the canonical port is free, where a held lock proves
    that an orphaned backend/worker still owns the single-writer runtime.
    """

    path = (
        Path(tempfile.gettempdir())
        / DEMO_RUNTIME_WRITER_LOCK_RELATIVE_PATH
    )
    try:
        handle = path.open("r+b")
    except FileNotFoundError:
        return {"status": "available"}
    except OSError:
        return {"status": "unknown"}

    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            return {"status": "available"}
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            acquired = True
        except OSError:
            owner = _read_demo_runtime_writer_owner(handle)
            return {
                "status": "held",
                "owner_pid": owner.get("process_id"),
                "owner_source_head": owner.get("source_head"),
            }
        return {"status": "available"}
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _read_demo_runtime_writer_owner(handle: Any) -> dict[str, Any]:
    raw = b""
    try:
        handle.seek(0)
        raw = handle.read()
    except OSError:
        # Windows byte-range locks can make byte 0 unreadable while the rest of
        # the owner marker remains readable.  Reconstruct the opening brace;
        # invalid/partial content is diagnostic-only and never unlocks launch.
        try:
            handle.seek(1)
            raw = b"{" + handle.read()
        except OSError:
            raw = b""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    process_id = payload.get("process_id")
    source_head = str(payload.get("source_head") or "")
    return {
        "process_id": (
            process_id
            if isinstance(process_id, int) and process_id > 0
            else None
        ),
        "source_head": (
            source_head
            if len(source_head) == 40
            and all(char in "0123456789abcdef" for char in source_head.lower())
            else ""
        ),
    }


def _ensure_demo_runtime_writer_available_before_spawn(
    identity: Mapping[str, Any],
) -> None:
    if (
        identity.get("evidence_profile") != DEMO_QUASI_LIVE_PROFILE
        or identity.get("listener_status") == "authenticated"
    ):
        return
    lock = inspect_demo_runtime_writer_lock()
    if lock.get("status") == "held":
        raise BackendCurrentMainLaunchError(
            "backend_demo_runtime_writer_lock_held"
        )
    if lock.get("status") != "available":
        raise BackendCurrentMainLaunchError(
            "backend_demo_runtime_writer_lock_inspection_failed"
        )


def _registered_main_worktree(repo_root: Path) -> Path:
    output = _git(repo_root, "worktree", "list", "--porcelain")
    current = ""
    for line in output.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree ") :].strip()
        elif line == "branch refs/heads/main" and current:
            return Path(current).resolve()
    raise BackendCurrentMainLaunchError(
        "backend_launcher_registered_main_missing"
    )


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackendCurrentMainLaunchError(
            "backend_launcher_git_command_failed"
        ) from exc


def _same_path(left: Path, right: Path) -> bool:
    return str(left.resolve()).replace("\\", "/").casefold() == str(
        right.resolve()
    ).replace("\\", "/").casefold()


def _path_binding_sha256(path: Path) -> str:
    normalized = str(path.resolve()).replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the canonical current-main backend."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--host", default=CANONICAL_HOST)
    parser.add_argument("--port", type=int, default=CANONICAL_PORT)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host != CANONICAL_HOST:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": "backend_canonical_host_required",
                }
            )
        )
        return 2
    try:
        identity = inspect_backend_identity(
            args.repo_root,
            port=args.port,
        )
        _ensure_demo_runtime_writer_available_before_spawn(identity)
    except BackendCurrentMainLaunchError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(exc).split(":", 1)[0],
                    "blockers": exc.blockers,
                    "paper_allowed": False,
                    "live_allowed": False,
                    "broker_or_order_allowed": False,
                }
            )
        )
        return 2

    status = (
        "already_running"
        if identity["listener_status"] == "authenticated"
        else "passed"
    )
    if args.check or status == "already_running":
        print(json.dumps({"status": status, **identity}, sort_keys=True))
        return 0

    environment = {
        **os.environ,
        LAUNCH_ENVIRONMENT: "1",
        LAUNCHED_HEAD_ENVIRONMENT: identity["source_head"],
        EVIDENCE_PROFILE_ENVIRONMENT: identity["evidence_profile"],
    }
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.api.app_factory:create_app",
            "--factory",
            "--host",
            CANONICAL_HOST,
            "--port",
            str(CANONICAL_PORT),
        ],
        cwd=args.repo_root,
        env=environment,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
