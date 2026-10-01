from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactReader,
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriteSession,
    BTCRuntimeArtifactWriter,
)


SCHEMA_VERSION = "btc_gate_run_snapshot_v1"
POINTER_SCHEMA_VERSION = "btc_gate_latest_pointer_v1"
DEFAULT_RUNS_ROOT = Path("artifacts/btc_gate_runs")
DEFAULT_POINTER_PATH = DEFAULT_RUNS_ROOT / "latest_pointer.json"
DEFAULT_BUILD_LOCK_PATH = DEFAULT_RUNS_ROOT / ".build.lock"
DEFAULT_POINTER_LOCK_TIMEOUT_SECONDS = 30.0
DEFAULT_GATE_STATUS_PATHS: tuple[str, ...] = (
    "quant_crypto",
    "scripts",
    "tests",
    "configs/btc",
    "backend/app/api/btc_domain_read_model.py",
    "schemas",
)


BTC_CONTROL_CENTER_ARTIFACTS: dict[str, str] = {
    "strategy_ledger": "artifacts/btc_strategy_ledger/latest/btc_strategy_ledger_report.json",
    "promotion_gate_control": "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json",
    "gate_dashboard": "artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json",
    "leakage_overfit_audit": "artifacts/btc_strategy_leakage_overfit_audit/latest/btc_strategy_leakage_overfit_audit_report.json",
    "attack_sleeve_risk_stress": "artifacts/btc_attack_sleeve_risk_stress_review/latest/btc_attack_sleeve_risk_stress_review_report.json",
    "attack_strategy_continuation_shortlist": "artifacts/btc_attack_strategy_continuation_shortlist/latest/btc_attack_strategy_continuation_shortlist_report.json",
    "attack_followup_review": "artifacts/btc_attack_followup_review/latest/btc_attack_followup_review_report.json",
    "micro_live_experiment_packet": "artifacts/btc_micro_live_experiment_packet/latest/btc_micro_live_experiment_packet_report.json",
    "data_status": "artifacts/btc_data_status/latest/btc_data_status_report.json",
    "paper_account_attestation": "artifacts/btc_exchange_runtime/latest/btc_paper_account_runtime_attestation_report.json",
    "exchange_runtime_local_probe": "artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_local_probe_report.json",
    "exchange_runtime_gap": "artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_replay_gap_report.json",
    "kill_switch": "artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json",
    "micro_live_preflight": "artifacts/btc_micro_live_preflight/latest/btc_micro_live_preflight_report.json",
    "paper_runtime_replay": "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json",
}


@dataclass(frozen=True)
class GateBuildState:
    code_commit: str
    dirty_status_hash: str
    dirty_paths: tuple[str, ...]
    source_input_hash: str
    watched_input_hash: str
    input_snapshot_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code_commit": self.code_commit,
            "dirty_status_hash": self.dirty_status_hash,
            "dirty_path_count": len(self.dirty_paths),
            "dirty_paths": list(self.dirty_paths),
            "source_input_hash": self.source_input_hash,
            "watched_input_hash": self.watched_input_hash,
            "input_snapshot_hash": self.input_snapshot_hash,
        }


@dataclass(frozen=True)
class GateArtifactResolution:
    path: Path | None
    source: str
    aggregation_batch_id: str
    error: str


class GateBuildLockTimeout(RuntimeError):
    pass


_ACTIVE_WRITE_SESSION: ContextVar[
    BTCRuntimeArtifactWriteSession | None
] = ContextVar("btc_gate_active_write_session", default=None)


def capture_gate_build_state(
    repo_root: Path,
    *,
    status_paths: Sequence[str] = DEFAULT_GATE_STATUS_PATHS,
) -> GateBuildState:
    root = repo_root.resolve()
    scoped_paths = tuple(
        path.replace("\\", "/").strip("/")
        for path in status_paths
        if path and not _is_generated_or_data_path(path)
    )
    if not scoped_paths:
        raise ValueError("BTC gate build state requires at least one explicit source pathspec")
    status_raw = _git_bytes(
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *scoped_paths,
        ],
        cwd=root,
    )
    dirty_paths = tuple(sorted(set(_parse_porcelain_paths(status_raw))))
    source_entries = [
        _path_fingerprint(root, path, content_hash=not _is_sensitive_security_path(path))
        for path in dirty_paths
        if _is_gate_source_input_path(path)
    ]
    watched_entries = _watched_input_fingerprints(root)
    source_input_hash = _json_hash(source_entries)
    watched_input_hash = _json_hash(watched_entries)
    return GateBuildState(
        code_commit=_git_text(["rev-parse", "HEAD"], cwd=root),
        dirty_status_hash=hashlib.sha256(status_raw).hexdigest(),
        dirty_paths=dirty_paths,
        source_input_hash=source_input_hash,
        watched_input_hash=watched_input_hash,
        input_snapshot_hash=_json_hash(
            {
                "source_input_hash": source_input_hash,
                "watched_input_hash": watched_input_hash,
            }
        ),
    )


def gate_build_state_is_stable(start: GateBuildState, end: GateBuildState) -> bool:
    return (
        bool(start.code_commit)
        and start.code_commit == end.code_commit
        and start.input_snapshot_hash == end.input_snapshot_hash
    )


@contextmanager
def gate_build_lock(
    repo_root: Path,
    *,
    lock_path: Path = DEFAULT_BUILD_LOCK_PATH,
    timeout_seconds: float = 600.0,
    poll_seconds: float = 0.05,
    artifact_writer: BTCRuntimeArtifactWriter | None = None,
) -> Iterator[BTCRuntimeArtifactWriteSession]:
    del lock_path, timeout_seconds, poll_seconds
    writer = artifact_writer or BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=repo_root.resolve()
    )
    with writer.exclusive() as session:
        token = _ACTIVE_WRITE_SESSION.set(session)
        try:
            yield session
        finally:
            _ACTIVE_WRITE_SESSION.reset(token)


@contextmanager
def _gate_write_session(
    *,
    repo_root: Path,
    artifact_writer: BTCRuntimeArtifactWriter | None,
    write_session: BTCRuntimeArtifactWriteSession | None,
) -> Iterator[BTCRuntimeArtifactWriteSession]:
    session = write_session or _ACTIVE_WRITE_SESSION.get()
    if session is not None:
        yield session
        return
    writer = artifact_writer or BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=repo_root.resolve()
    )
    with writer.exclusive() as owned_session:
        yield owned_session


def publish_gate_run_snapshot(
    *,
    repo_root: Path,
    aggregation_batch_id: str,
    generated_at_utc: datetime,
    start_state: GateBuildState,
    end_state: GateBuildState,
    step_order: Sequence[str],
    source_paths: Iterable[Path | str],
    required_paths: Iterable[Path | str],
    validation_checks: Mapping[str, bool],
    runs_root: Path = DEFAULT_RUNS_ROOT,
    pointer_path: Path = DEFAULT_POINTER_PATH,
    artifact_reader: BTCRuntimeArtifactReader | None = None,
    artifact_writer: BTCRuntimeArtifactWriter | None = None,
    write_session: BTCRuntimeArtifactWriteSession | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    with _gate_write_session(
        repo_root=root,
        artifact_writer=artifact_writer,
        write_session=write_session,
    ) as session:
        reader = artifact_reader or session.writer
        run_root = reader.resolve(runs_root)
        final_dir = run_root / aggregation_batch_id
        if final_dir.exists():
            raise FileExistsError(
                f"immutable BTC gate run already exists: {final_dir}"
            )

        staging_dir = (
            run_root / f".{aggregation_batch_id}.staging.{uuid.uuid4().hex}"
        )
        files_dir = staging_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=False)
        required = {_portable_path(Path(path)) for path in required_paths}
        logical_paths = sorted(
            {_portable_path(Path(path)) for path in source_paths} | required
        )
        artifacts: list[dict[str, Any]] = []
        missing_paths: list[str] = []

        try:
            for logical_path in logical_paths:
                source = reader.resolve(logical_path)
                if not source.is_file():
                    if logical_path in required:
                        missing_paths.append(logical_path)
                    continue
                relative = Path(*Path(logical_path).parts[1:])
                destination = files_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                entry = _snapshot_artifact_entry(
                    source, destination, logical_path
                )
                entry["snapshot_path"] = reader.logical_path(
                    final_dir / "files" / relative
                ).as_posix()
                artifacts.append(entry)

            checks = dict(validation_checks)
            checks.update(
                {
                    "code_commit_stable": bool(start_state.code_commit)
                    and start_state.code_commit == end_state.code_commit,
                    "input_snapshot_stable": (
                        start_state.input_snapshot_hash
                        == end_state.input_snapshot_hash
                    ),
                    "required_snapshot_artifacts_present": not missing_paths,
                }
            )
            publishable = all(checks.values())
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "generated_at_utc": _ensure_utc(generated_at_utc).isoformat(),
                "aggregation_batch_id": aggregation_batch_id,
                "status": (
                    "complete_immutable_gate_snapshot"
                    if publishable
                    else "rejected_fail_closed_snapshot"
                ),
                "decision": (
                    "btc_gate_snapshot_validated_for_atomic_pointer_publish"
                    if publishable
                    else "btc_gate_snapshot_rejected_no_latest_pointer_update"
                ),
                "immutable": True,
                "code_commit": start_state.code_commit,
                "build_state_start": start_state.as_dict(),
                "build_state_end": end_state.as_dict(),
                "step_order": list(step_order),
                "validation_checks": checks,
                "missing_required_paths": missing_paths,
                "artifact_count": len(artifacts),
                "artifacts": artifacts,
                "gate": _gate(),
                "guardrails": _guardrails(),
            }
            manifest_path = staging_dir / "manifest.json"
            _write_json_fsync(manifest_path, manifest)
            run_root.mkdir(parents=True, exist_ok=True)
            os.replace(staging_dir, final_dir)

            final_manifest = final_dir / "manifest.json"
            manifest_sha256 = _file_sha256(final_manifest)
            publication = {
                "status": "rejected_fail_closed",
                "published": False,
                "aggregation_batch_id": aggregation_batch_id,
                "run_manifest_path": reader.logical_path(
                    final_manifest
                ).as_posix(),
                "run_manifest_sha256": manifest_sha256,
                "latest_pointer_path": _portable_path(pointer_path),
                "validation_checks": checks,
                "missing_required_paths": missing_paths,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
                "broker_or_order_allowed": False,
            }
            if not publishable:
                return publication

            pointer = {
                "schema_version": POINTER_SCHEMA_VERSION,
                "published_at_utc": datetime.now(timezone.utc).isoformat(),
                "aggregation_batch_id": aggregation_batch_id,
                "code_commit": start_state.code_commit,
                "manifest_path": publication["run_manifest_path"],
                "manifest_sha256": manifest_sha256,
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
                "broker_or_order_allowed": False,
            }
            session.write_json_atomic(pointer_path, pointer)
            publication["status"] = "published_immutable_snapshot"
            publication["published"] = True
            return publication
        except Exception:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            raise


def load_latest_gate_snapshot(
    repo_root: Path,
    *,
    pointer_path: Path = DEFAULT_POINTER_PATH,
    expected_head: str = "",
    artifact_reader: BTCRuntimeArtifactReader | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    reader = artifact_reader or BTCRuntimeArtifactReader.from_environment(
        source_repo_root=root
    )
    pointer_file = reader.resolve(pointer_path)
    pointer = _read_json(pointer_file)
    if not pointer:
        return {"status": "missing", "error": "btc_gate_latest_pointer_missing_or_invalid"}
    if pointer.get("schema_version") != POINTER_SCHEMA_VERSION:
        return {"status": "invalid", "error": "btc_gate_latest_pointer_schema_mismatch"}
    pointer_head = str(pointer.get("code_commit") or "")
    if expected_head and pointer_head != expected_head:
        return {"status": "invalid", "error": "btc_gate_latest_pointer_wrong_head"}
    manifest_value = str(pointer.get("manifest_path") or "")
    manifest_path = _safe_artifact_path(reader, manifest_value)
    if manifest_path is None or not manifest_path.is_file():
        return {"status": "invalid", "error": "btc_gate_latest_pointer_manifest_missing"}
    expected_sha = str(pointer.get("manifest_sha256") or "")
    if not expected_sha or _file_sha256(manifest_path) != expected_sha:
        return {"status": "invalid", "error": "btc_gate_latest_pointer_manifest_sha256_mismatch"}
    manifest = _read_json(manifest_path)
    if not manifest or manifest.get("aggregation_batch_id") != pointer.get("aggregation_batch_id"):
        return {"status": "invalid", "error": "btc_gate_latest_pointer_batch_mismatch"}
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return {"status": "invalid", "error": "btc_gate_latest_pointer_run_schema_mismatch"}
    if manifest.get("immutable") is not True:
        return {"status": "invalid", "error": "btc_gate_latest_pointer_run_not_immutable"}
    if str(manifest.get("code_commit") or "") != pointer_head:
        return {"status": "invalid", "error": "btc_gate_latest_pointer_run_head_mismatch"}
    for row in _list_of_mappings(manifest.get("artifacts")):
        artifact_path = _safe_artifact_path(
            reader, str(row.get("snapshot_path") or "")
        )
        if artifact_path is None or not artifact_path.is_file():
            return {"status": "invalid", "error": "btc_gate_latest_pointer_artifact_missing"}
        expected_artifact_sha = str(row.get("file_sha256") or "")
        if not expected_artifact_sha or _file_sha256(artifact_path) != expected_artifact_sha:
            return {"status": "invalid", "error": "btc_gate_latest_pointer_artifact_sha256_mismatch"}
    return {
        "status": "valid",
        "error": "",
        "pointer": pointer,
        "manifest": manifest,
        "manifest_path": manifest_path,
    }


def resolve_latest_gate_artifact(
    repo_root: Path,
    logical_path: Path | str,
    *,
    artifact_reader: BTCRuntimeArtifactReader | None = None,
) -> GateArtifactResolution:
    root = repo_root.resolve()
    reader = artifact_reader or BTCRuntimeArtifactReader.from_environment(
        source_repo_root=root
    )
    logical = _portable_path(Path(logical_path))
    snapshot = load_latest_gate_snapshot(root, artifact_reader=reader)
    if snapshot.get("status") != "valid":
        return GateArtifactResolution(None, "snapshot_pointer_fail_closed", "", str(snapshot.get("error") or ""))
    manifest = _mapping(snapshot.get("manifest"))
    batch_id = str(manifest.get("aggregation_batch_id") or "")
    for row in _list_of_mappings(manifest.get("artifacts")):
        if str(row.get("logical_path") or "") != logical:
            continue
        snapshot_value = str(row.get("snapshot_path") or "")
        path = _safe_artifact_path(reader, snapshot_value)
        if path is None or not path.is_file():
            return GateArtifactResolution(None, "snapshot_pointer_fail_closed", batch_id, "snapshot_artifact_missing")
        expected_sha = str(row.get("file_sha256") or "")
        if not expected_sha or _file_sha256(path) != expected_sha:
            return GateArtifactResolution(None, "snapshot_pointer_fail_closed", batch_id, "snapshot_artifact_sha256_mismatch")
        return GateArtifactResolution(path, "immutable_gate_snapshot", batch_id, "")
    return GateArtifactResolution(None, "snapshot_pointer_fail_closed", batch_id, "logical_artifact_not_in_snapshot")


def resolve_gate_artifact_from_batch(
    repo_root: Path,
    aggregation_batch_id: str,
    logical_path: Path | str,
    *,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    artifact_reader: BTCRuntimeArtifactReader | None = None,
) -> GateArtifactResolution:
    root = repo_root.resolve()
    reader = artifact_reader or BTCRuntimeArtifactReader.from_environment(
        source_repo_root=root
    )
    manifest_path = reader.resolve(runs_root) / aggregation_batch_id / "manifest.json"
    manifest = _read_json(manifest_path)
    if not manifest:
        return GateArtifactResolution(None, "historical_snapshot", aggregation_batch_id, "historical_manifest_missing")
    logical = _portable_path(Path(logical_path))
    for row in _list_of_mappings(manifest.get("artifacts")):
        if str(row.get("logical_path") or "") == logical:
            path = _safe_artifact_path(
                reader, str(row.get("snapshot_path") or "")
            )
            if path is not None and path.is_file() and _file_sha256(path) == str(row.get("file_sha256") or ""):
                return GateArtifactResolution(path, "historical_snapshot", aggregation_batch_id, "")
            return GateArtifactResolution(None, "historical_snapshot", aggregation_batch_id, "historical_artifact_invalid")
    return GateArtifactResolution(None, "historical_snapshot", aggregation_batch_id, "logical_artifact_not_in_snapshot")


def _snapshot_artifact_entry(
    source: Path,
    destination: Path,
    logical_path: str,
) -> dict[str, Any]:
    payload = _read_json(destination) if destination.suffix.lower() == ".json" else {}
    return {
        "logical_path": logical_path,
        "snapshot_path": "",
        "file_sha256": _file_sha256(destination),
        "file_size_bytes": destination.stat().st_size,
        "stable_payload_hash": stable_payload_hash(payload) if payload else "",
        "aggregation_batch_id": str(payload.get("aggregation_batch_id") or ""),
        "code_commit": str(payload.get("code_commit") or payload.get("commit_hash") or ""),
        "source_file_mtime_ns": source.stat().st_mtime_ns,
    }


def _watched_input_fingerprints(root: Path) -> list[dict[str, Any]]:
    paths: set[Path] = set()
    config_root = root / "configs" / "btc"
    if config_root.is_dir():
        paths.update(path for path in config_root.rglob("*") if path.is_file())
    for relative in (
        Path("data/market_data.sqlite"),
        Path("data/external/btc_derivatives_sentiment/free_sources/free_public_btcusdt_1h_latest/derivatives_sentiment_1h.json"),
    ):
        candidate = root / relative
        if candidate.exists():
            paths.add(candidate)
    entries: list[dict[str, Any]] = []
    for path in sorted(paths, key=lambda item: _portable_path(item.relative_to(root))):
        relative = _portable_path(path.relative_to(root))
        entries.append(_path_fingerprint(root, relative, content_hash=not _is_sensitive_security_path(relative)))
    return entries


def _path_fingerprint(root: Path, relative_path: str, *, content_hash: bool) -> dict[str, Any]:
    path = root / relative_path
    if not path.exists():
        return {"path": relative_path, "exists": False}
    stat = path.stat()
    row: dict[str, Any] = {
        "path": relative_path,
        "exists": True,
        "file_size_bytes": stat.st_size,
        "file_mtime_ns": stat.st_mtime_ns,
    }
    if content_hash and path.is_file() and stat.st_size <= 16 * 1024 * 1024:
        row["file_sha256"] = _file_sha256(path)
    return row


def _parse_porcelain_paths(raw: bytes) -> list[str]:
    parts = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(parts):
        record = parts[index]
        index += 1
        if not record:
            continue
        text = record.decode("utf-8", errors="surrogateescape")
        if len(text) < 4:
            continue
        status = text[:2]
        paths.append(text[3:].replace("\\", "/"))
        if "R" in status or "C" in status:
            if index < len(parts) and parts[index]:
                paths.append(parts[index].decode("utf-8", errors="surrogateescape").replace("\\", "/"))
                index += 1
    return paths


def _is_generated_or_data_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(("artifacts/", "data/", "downloads/", ".tmp/", ".venv/", "automation_run_"))


def _is_gate_source_input_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if _is_generated_or_data_path(normalized):
        return False
    if normalized.startswith(("quant_crypto/", "configs/btc/")):
        return True
    if normalized.startswith("scripts/"):
        return "btc" in Path(normalized).name.lower()
    if normalized.startswith("tests/"):
        return "btc" in Path(normalized).name.lower()
    if normalized.startswith("frontend/"):
        lowered = normalized.lower()
        return "btc" in lowered or "crypto" in lowered or lowered.endswith("research-api.ts")
    if normalized == "backend/app/api/app_factory.py":
        return True
    return normalized in {"pyproject.toml", "requirements.txt", "requirements-dev.txt"}


def _is_sensitive_security_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith("configs/btc/security/")


def _safe_artifact_path(
    reader: BTCRuntimeArtifactReader,
    value: str,
) -> Path | None:
    try:
        return reader.resolve(value)
    except BTCRuntimeArtifactStoreError:
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _portable_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_bytes(args: Sequence[str], *, cwd: Path) -> bytes:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True)
    except OSError:
        return b""
    return result.stdout if result.returncode == 0 else b""


def _git_text(args: Sequence[str], *, cwd: Path) -> str:
    return _git_bytes(args, cwd=cwd).decode("utf-8", errors="replace").strip()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_fsync(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "immutable_snapshot_only": True,
        "atomic_latest_pointer_publish": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }
