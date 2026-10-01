#!/usr/bin/env python3
"""Durable public-only OKX L2 immutable observer.

The runner deliberately orchestrates existing clock, WebSocket capture, immutable
export, and shared-data publication contracts. It does not implement exchange or
book semantics itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

if __package__ in {None, ""}:  # pragma: no cover - exercised by CLI smoke.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_crypto.data.immutable_okx_l2_export import (  # noqa: E402
    ATTESTATION_NAME,
    DATASET_ID,
    L2ExportBlocked,
    L2SegmentSource,
    export_immutable_okx_l2,
)
from quant_crypto.data.okx_l2_capture_contract import (  # noqa: E402
    OKX_L2_PUBLIC_WS_URL,
    OKX_L2_RAW_MANIFEST_FILE,
    OKX_L2_RAW_MESSAGES_FILE,
)
from quant_crypto.research.btc_okx_server_time_preflight import (  # noqa: E402
    build_btc_okx_server_time_preflight_report,
)
from scripts.fetch_btc_okx_public_ws_l2_raw_capture import (  # noqa: E402
    capture_okx_public_ws_l2_raw_data,
)
from tools.agent_governance.shared_data import (  # noqa: E402
    SharedDataError,
    publish_dataset,
)


SCHEMA_VERSION = "btc_okx_public_l2_immutable_observer_v1"
STATE_SCHEMA_VERSION = "btc_okx_public_l2_immutable_observer_state_v1"
TICKET_ID = "DATA-BTC-L2-IMMUTABLE-1D-RUNNER-11"
PRODUCER_ROLE = "data_steward"
PROXY_URL = "http://127.0.0.1:12334"
MINIMUM_FREE_GIB = 20.0
DIRECT_CLOCK_MAX_ABS_OFFSET_MS = 2_000.0
DIRECT_CLOCK_MAX_RTT_MS = 5_000.0
MAX_SLICE_SECONDS = 3_600.0
SAFETY_FLAGS = {
    "promotion_evidence_ready": False,
    "promotion_eligible": False,
    "paper_ready": False,
    "live_ready": False,
    "private_endpoint_used": False,
    "account_endpoint_used": False,
    "order_endpoint_used": False,
    "broker_used": False,
    "secret_read": False,
    "withdraw_used": False,
    "real_order_submitted": False,
    "paper_queue_written": False,
}
EXIT_CODES = {
    "complete_quality_checked_observe_only": 0,
    "running_resumable": 10,
    "blocked_clock": 20,
    "blocked_sequence": 21,
    "blocked_storage": 22,
    "blocked_writer_conflict": 23,
    "blocked_public_network": 24,
    "blocked_publication": 25,
}


class WriterConflict(RuntimeError):
    """Raised before any network or dataset write when another writer owns the lock."""


@dataclass(frozen=True)
class ObserverConfig:
    repo_root: Path
    runtime_root: Path
    shared_data_root: Path
    duration_hours: float = 24.0
    slice_seconds: float = 3_600.0
    max_messages: int = 500_000
    clock_samples: int = 11
    forced_reconnect_after_messages: int = 20
    proxy_url: str = PROXY_URL
    public_ws_url: str = OKX_L2_PUBLIC_WS_URL
    execute_network: bool = False
    once: bool = False
    retry_sleep_seconds: float = 30.0
    minimum_free_gib: float = MINIMUM_FREE_GIB
    source_head: str = ""

    @property
    def target_seconds(self) -> float:
        return self.duration_hours * 3_600.0

    @property
    def lock_path(self) -> Path:
        return self.runtime_root / "writer.lock"


@dataclass
class ObserverDependencies:
    clock: Callable[..., dict[str, Any]] = build_btc_okx_server_time_preflight_report
    capture: Callable[..., dict[str, Any]] = capture_okx_public_ws_l2_raw_data
    export: Callable[..., dict[str, Any]] = export_immutable_okx_l2
    publish: Callable[..., dict[str, Any]] = publish_dataset
    now: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(timezone.utc))
    sleep: Callable[[float], None] = time.sleep
    disk_free_bytes: Callable[[Path], int] = field(default_factory=lambda: lambda path: shutil.disk_usage(path).free)
    w32time: Callable[[], dict[str, Any]] = field(default_factory=lambda: read_w32time_diagnostic)
    lock: Callable[[Path], Any] = field(default_factory=lambda: exclusive_writer_lock)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json_object_required:{path}")
    return payload


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(_json_bytes(payload))
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_config(config: ObserverConfig) -> ObserverConfig:
    repo_root = config.repo_root.resolve()
    runtime_root = config.runtime_root.resolve()
    shared_root = config.shared_data_root.resolve()
    if not runtime_root.is_absolute() or not shared_root.is_absolute():
        raise ValueError("observer_external_roots_must_be_absolute")
    try:
        runtime_root.relative_to(repo_root)
        raise ValueError("observer_runtime_root_must_be_outside_repo")
    except ValueError as exc:
        if str(exc) == "observer_runtime_root_must_be_outside_repo":
            raise
    try:
        shared_root.relative_to(repo_root)
        raise ValueError("observer_shared_root_must_be_outside_repo")
    except ValueError as exc:
        if str(exc) == "observer_shared_root_must_be_outside_repo":
            raise
    if runtime_root == shared_root:
        raise ValueError("observer_runtime_and_shared_roots_must_differ")
    if config.proxy_url != PROXY_URL:
        raise ValueError("observer_proxy_not_architecture_approved")
    if config.public_ws_url != OKX_L2_PUBLIC_WS_URL:
        raise ValueError("observer_ws_endpoint_not_current_official_allowlist")
    if config.duration_hours <= 0:
        raise ValueError("observer_duration_hours_invalid")
    if not 0 < config.slice_seconds <= MAX_SLICE_SECONDS:
        raise ValueError("observer_slice_seconds_invalid")
    if config.clock_samples < 9:
        raise ValueError("observer_clock_samples_below_contract")
    if config.max_messages <= 0:
        raise ValueError("observer_max_messages_invalid")
    if config.minimum_free_gib < MINIMUM_FREE_GIB:
        raise ValueError("observer_storage_guard_below_contract")
    return ObserverConfig(**{**config.__dict__, "repo_root": repo_root, "runtime_root": runtime_root, "shared_data_root": shared_root})


@contextmanager
def exclusive_writer_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - Windows is the production target.
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise WriterConflict(f"observer_writer_lock_conflict:{path}") from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


@contextmanager
def approved_process_proxy(proxy_url: str) -> Iterator[None]:
    keys = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[key] = proxy_url
        for key in ("NO_PROXY", "no_proxy"):
            os.environ[key] = "127.0.0.1,localhost"
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def read_w32time_diagnostic() -> dict[str, Any]:
    if os.name != "nt":
        return {"available": False, "degraded": True, "reason": "w32time_not_windows"}
    commands = {
        "status": ["w32tm", "/query", "/status"],
        "source": ["w32tm", "/query", "/source"],
    }
    outputs: dict[str, Any] = {}
    for name, command in commands.items():
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        outputs[name] = {
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    status_text = str(outputs["status"]["stdout"])
    leap_zero = any(token in status_text for token in ("Leap Indicator: 0", "闰跃指示符: 0", "跃变指示符: 0"))
    stratum_nonzero = not any(token in status_text for token in ("Stratum: 0", "层次: 0"))
    return {
        "available": outputs["status"]["exit_code"] == 0,
        "degraded": not (outputs["status"]["exit_code"] == 0 and leap_zero and stratum_nonzero),
        "leap_zero": leap_zero,
        "stratum_nonzero": stratum_nonzero,
        "commands": outputs,
    }


def _initial_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "qualified_start_utc": "",
        "latest_coverage_end_utc": "",
        "qualified_coverage_seconds": 0.0,
        "qualified_slice_count": 0,
        "attempt_count": 0,
        "estimated_gap_seconds": 0.0,
        "complete": False,
    }


def _owner_payload(config: ObserverConfig) -> dict[str, Any]:
    return {
        "schema_version": "btc_okx_public_l2_observer_owner_v1",
        "ticket_id": TICKET_ID,
        "repository_root": str(config.repo_root),
        "dataset_id": DATASET_ID,
        "single_writer": True,
    }


def _ensure_owner(config: ObserverConfig) -> None:
    owner_path = config.runtime_root / "owner.json"
    expected = _owner_payload(config)
    if owner_path.exists():
        if _read_json(owner_path) != expected:
            raise WriterConflict(f"observer_runtime_owner_mismatch:{owner_path}")
        return
    _write_json_exclusive(owner_path, expected)


def _load_state(config: ObserverConfig) -> dict[str, Any]:
    pointer_path = config.runtime_root / "latest_pointer.json"
    if not pointer_path.exists():
        return _initial_state()
    pointer = _read_json(pointer_path)
    event_path = config.runtime_root / str(pointer.get("event_path", ""))
    if not event_path.is_file():
        raise SharedDataError("observer_latest_event_missing")
    if _sha256_file(event_path) != pointer.get("event_sha256"):
        raise SharedDataError("observer_latest_event_hash_mismatch")
    event = _read_json(event_path)
    state = event.get("state_after")
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise SharedDataError("observer_latest_state_invalid")
    return dict(state)


def _next_slice_identity(config: ObserverConfig, state: Mapping[str, Any], now: datetime) -> tuple[str, str]:
    index = int(state.get("attempt_count", 0)) + 1
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    slice_id = f"slice-{index:08d}-{stamp}"
    dataset_version = f"btc-okx-l2-observer-1d-{index:08d}-{stamp.lower()}"
    return slice_id, dataset_version


def _inflight(config: ObserverConfig, state: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    path = config.runtime_root / "inflight.json"
    if path.exists():
        payload = _read_json(path)
        if payload.get("ticket_id") != TICKET_ID:
            raise SharedDataError("observer_inflight_owner_invalid")
        return payload
    slice_id, version = _next_slice_identity(config, state, now)
    payload = {
        "schema_version": "btc_okx_public_l2_observer_inflight_v1",
        "ticket_id": TICKET_ID,
        "slice_id": slice_id,
        "dataset_version": version,
        "started_at_utc": _utc_text(now),
    }
    _write_json_atomic(path, payload)
    return payload


def _clock_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = report.get("server_time_metrics")
    return dict(metrics) if isinstance(metrics, Mapping) else {}


def _free_gib(config: ObserverConfig, deps: ObserverDependencies) -> float:
    probe = config.runtime_root if config.runtime_root.exists() else config.runtime_root.parent
    probe.mkdir(parents=True, exist_ok=True)
    return deps.disk_free_bytes(probe) / (1024.0**3)


def _capture_files(capture_dir: Path) -> tuple[Path, Path]:
    return capture_dir / OKX_L2_RAW_MESSAGES_FILE, capture_dir / OKX_L2_RAW_MANIFEST_FILE


def _read_or_capture(
    *,
    config: ObserverConfig,
    deps: ObserverDependencies,
    slice_root: Path,
) -> dict[str, Any]:
    capture_dir = slice_root / "capture"
    capture_report_path = slice_root / "capture_report.json"
    raw_path, manifest_path = _capture_files(capture_dir)
    if capture_report_path.exists() and raw_path.exists() and manifest_path.exists():
        report = _read_json(capture_report_path)
        if report.get("status") == "verified_preflight":
            return report
    capture_dir.mkdir(parents=True, exist_ok=True)
    return deps.capture(
        repo_root=config.repo_root,
        bundle_dir=capture_dir,
        capture_report_path=capture_report_path,
        execute_network=config.execute_network,
        duration_seconds=config.slice_seconds,
        max_messages=config.max_messages,
        channels=["books"],
        recv_timeout_seconds=min(5.0, config.slice_seconds),
        forced_reconnect_after_messages=config.forced_reconnect_after_messages,
        public_ws_url=config.public_ws_url,
    )


def _read_or_export(
    *,
    config: ObserverConfig,
    deps: ObserverDependencies,
    slice_root: Path,
    dataset_version: str,
    checked_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    capture_dir = slice_root / "capture"
    raw_path, manifest_path = _capture_files(capture_dir)
    export_dir = slice_root / "immutable_export"
    attestation_path = export_dir / ATTESTATION_NAME
    if attestation_path.exists():
        return {"status": "quality_checked", "attestation_path": str(attestation_path)}, _read_json(attestation_path)
    report = deps.export(
        segments=(
            L2SegmentSource(
                segment_dir=capture_dir,
                expected_raw_sha256=_sha256_file(raw_path),
                expected_manifest_sha256=_sha256_file(manifest_path),
            ),
        ),
        output_dir=export_dir,
        dataset_version=dataset_version,
        source_head=config.source_head,
        now=checked_at,
        producer_role=PRODUCER_ROLE,
        max_clock_lag_ms=5_000.0,
        freshness_sla_minutes=15.0,
        max_inter_message_gap_seconds=5.0,
    )
    return report, _read_json(Path(str(report["attestation_path"])))


def _sequence_valid(attestation: Mapping[str, Any]) -> bool:
    return (
        attestation.get("quality_checked") is True
        and attestation.get("sequence_validation_status") == "pass"
        and int(attestation.get("unrecovered_gap_count", -1)) == 0
        and float(attestation.get("two_sided_coverage_pct", 0.0)) > 0.0
    )


def _publish(
    *,
    config: ObserverConfig,
    deps: ObserverDependencies,
    slice_root: Path,
    dataset_version: str,
    attestation: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_path = config.runtime_root / "manifests" / f"{dataset_version}.json"
    return deps.publish(
        source=slice_root,
        shared_root=config.shared_data_root,
        dataset_id=DATASET_ID,
        dataset_version=dataset_version,
        readiness_class="quality_checked",
        quality_status="pass_with_research_only_warnings",
        producer_role=PRODUCER_ROLE,
        producer_commit=config.source_head,
        schema_name=str(attestation.get("schema_version", "btc_okx_l2_dataready_attestation_v1")),
        blockers=list(attestation.get("promotion_blockers", [])),
        known_gaps=[],
        coverage_start=str(attestation.get("coverage_start", "")),
        coverage_end=str(attestation.get("coverage_end", "")),
        manifest_output=manifest_path,
    )


def _updated_state(
    state: Mapping[str, Any],
    *,
    attestation: Mapping[str, Any] | None,
    target_seconds: float,
) -> dict[str, Any]:
    updated = dict(state)
    updated["attempt_count"] = int(updated.get("attempt_count", 0)) + 1
    if attestation is None:
        return updated
    coverage_start = str(attestation["coverage_start"])
    coverage_end = str(attestation["coverage_end"])
    observed = max(0.0, float(attestation.get("observed_history_seconds", 0.0)))
    if not updated.get("qualified_start_utc"):
        updated["qualified_start_utc"] = coverage_start
    updated["latest_coverage_end_utc"] = coverage_end
    updated["qualified_coverage_seconds"] = round(float(updated.get("qualified_coverage_seconds", 0.0)) + observed, 6)
    updated["qualified_slice_count"] = int(updated.get("qualified_slice_count", 0)) + 1
    elapsed = max(
        0.0,
        (_parse_utc(coverage_end) - _parse_utc(str(updated["qualified_start_utc"]))).total_seconds(),
    )
    updated["estimated_gap_seconds"] = round(
        max(0.0, elapsed - float(updated["qualified_coverage_seconds"])),
        6,
    )
    updated["complete"] = (
        elapsed >= target_seconds
        and float(updated["qualified_coverage_seconds"]) >= target_seconds
    )
    return updated


def _finalize_event(
    *,
    config: ObserverConfig,
    inflight: Mapping[str, Any],
    state_after: Mapping[str, Any],
    status: str,
    checked_at: datetime,
    health: Mapping[str, Any],
    keep_inflight: bool,
) -> dict[str, Any]:
    event_id = f"{inflight['slice_id']}-{status}"
    health_payload = {
        "schema_version": "btc_okx_public_l2_observer_health_v1",
        "event_id": event_id,
        "status": status,
        "checked_at_utc": _utc_text(checked_at),
        "ticket_id": TICKET_ID,
        "source_head": config.source_head,
        "duration_target_hours": config.duration_hours,
        "safety_flags": SAFETY_FLAGS,
        **health,
    }
    health_path = config.runtime_root / "health" / f"{event_id}.json"
    if not health_path.exists():
        _write_json_exclusive(health_path, health_payload)
    event_payload = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": "observer_slice_result",
        "ticket_id": TICKET_ID,
        "status": status,
        "created_at_utc": _utc_text(checked_at),
        "slice_id": inflight["slice_id"],
        "dataset_version": inflight["dataset_version"],
        "health_path": health_path.relative_to(config.runtime_root).as_posix(),
        "health_sha256": _sha256_file(health_path),
        "state_after": state_after,
        "safety_flags": SAFETY_FLAGS,
    }
    event_path = config.runtime_root / "events" / f"{event_id}.json"
    if not event_path.exists():
        _write_json_exclusive(event_path, event_payload)
    pointer_payload = {
        "schema_version": "btc_okx_public_l2_observer_latest_pointer_v1",
        "event_id": event_id,
        "event_path": event_path.relative_to(config.runtime_root).as_posix(),
        "event_sha256": _sha256_file(event_path),
        "updated_at_utc": _utc_text(checked_at),
        "latest_pointer_updated_last": True,
    }
    _write_json_atomic(config.runtime_root / "latest_pointer.json", pointer_payload)
    if not keep_inflight:
        inflight_path = config.runtime_root / "inflight.json"
        if inflight_path.exists():
            completed = config.runtime_root / "completed_inflight" / f"{inflight['slice_id']}.json"
            completed.parent.mkdir(parents=True, exist_ok=True)
            os.replace(inflight_path, completed)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "exit_code": EXIT_CODES[status],
        "event_id": event_id,
        "event_path": str(event_path),
        "health_path": str(health_path),
        "state": state_after,
        "safety_flags": SAFETY_FLAGS,
    }


def _blocked_before_inflight(
    config: ObserverConfig,
    *,
    status: str,
    checked_at: datetime,
    blocker: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "exit_code": EXIT_CODES[status],
        "checked_at_utc": _utc_text(checked_at),
        "blockers": [blocker],
        "safety_flags": SAFETY_FLAGS,
    }
    if extra:
        payload.update(extra)
    return payload


def _run_slice(
    config: ObserverConfig,
    deps: ObserverDependencies,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    checked_at = deps.now()
    free_gib = _free_gib(config, deps)
    if free_gib < config.minimum_free_gib:
        inflight = _inflight(config, state, checked_at)
        state_after = _updated_state(state, attestation=None, target_seconds=config.target_seconds)
        return _finalize_event(
            config=config,
            inflight=inflight,
            state_after=state_after,
            status="blocked_storage",
            checked_at=checked_at,
            health={"free_gib": round(free_gib, 6), "blockers": ["observer_storage_below_20_gib"]},
            keep_inflight=False,
        )

    inflight = _inflight(config, state, checked_at)
    slice_root = config.runtime_root / "slices" / str(inflight["slice_id"])
    slice_root.mkdir(parents=True, exist_ok=True)
    w32 = deps.w32time()
    clock_dir = slice_root / "clock"
    clock_report_path = clock_dir / "btc_okx_server_time_preflight_report.json"
    if clock_report_path.exists():
        clock = _read_json(clock_report_path)
    else:
        clock = deps.clock(
            repo_root=config.repo_root,
            output_dir=clock_dir,
            execute_network=config.execute_network,
            generated_at_utc=checked_at,
            max_abs_offset_ms=DIRECT_CLOCK_MAX_ABS_OFFSET_MS,
            max_round_trip_ms=DIRECT_CLOCK_MAX_RTT_MS,
            sample_count=config.clock_samples,
        )
    base_health = {
        "free_gib": round(free_gib, 6),
        "w32time": w32,
        "w32time_degraded": bool(w32.get("degraded", True)),
        "direct_clock": {
            "verified": clock.get("server_time_offset_verified") is True,
            "metrics": _clock_metrics(clock),
            "sample_count_requested": clock.get("sample_count_requested"),
        },
        "proxy": {
            "url": config.proxy_url,
            "process_level_only": True,
            "tls_verification_disabled": False,
            "hostname_verification_disabled": False,
        },
    }
    if clock.get("server_time_offset_verified") is not True:
        state_after = _updated_state(state, attestation=None, target_seconds=config.target_seconds)
        return _finalize_event(
            config=config,
            inflight=inflight,
            state_after=state_after,
            status="blocked_clock",
            checked_at=checked_at,
            health={**base_health, "blockers": list(clock.get("blockers", [])) or ["observer_direct_clock_failed"]},
            keep_inflight=False,
        )
    if not config.execute_network:
        state_after = _updated_state(state, attestation=None, target_seconds=config.target_seconds)
        return _finalize_event(
            config=config,
            inflight=inflight,
            state_after=state_after,
            status="blocked_public_network",
            checked_at=checked_at,
            health={**base_health, "blockers": ["observer_network_execution_not_enabled"]},
            keep_inflight=False,
        )
    try:
        capture = _read_or_capture(config=config, deps=deps, slice_root=slice_root)
    except Exception as exc:  # noqa: BLE001 - persisted fail-closed evidence.
        capture = {"status": "partial", "blockers": [f"observer_capture_exception:{type(exc).__name__}:{exc}"]}
    if capture.get("status") != "verified_preflight" or int(capture.get("data_message_count", 0)) <= 0:
        state_after = _updated_state(state, attestation=None, target_seconds=config.target_seconds)
        return _finalize_event(
            config=config,
            inflight=inflight,
            state_after=state_after,
            status="blocked_public_network",
            checked_at=checked_at,
            health={
                **base_health,
                "capture": capture,
                "blockers": list(capture.get("blockers", [])) or ["observer_zero_public_l2_messages"],
            },
            keep_inflight=False,
        )
    try:
        export_report, attestation = _read_or_export(
            config=config,
            deps=deps,
            slice_root=slice_root,
            dataset_version=str(inflight["dataset_version"]),
            checked_at=deps.now(),
        )
    except L2ExportBlocked as exc:
        export_report, attestation = {"status": "blocked", "blockers": list(exc.blockers)}, {}
    except Exception as exc:  # noqa: BLE001
        export_report, attestation = {"status": "blocked", "blockers": [f"observer_export_exception:{type(exc).__name__}:{exc}"]}, {}
    if not _sequence_valid(attestation):
        state_after = _updated_state(state, attestation=None, target_seconds=config.target_seconds)
        return _finalize_event(
            config=config,
            inflight=inflight,
            state_after=state_after,
            status="blocked_sequence",
            checked_at=checked_at,
            health={
                **base_health,
                "capture": capture,
                "export": export_report,
                "attestation": attestation,
                "blockers": list(export_report.get("blockers", [])) or ["observer_l2_quality_or_sequence_failed"],
            },
            keep_inflight=False,
        )
    slice_metadata_path = slice_root / "observer_slice_metadata.json"
    if not slice_metadata_path.exists():
        _write_json_exclusive(
            slice_metadata_path,
            {
                "schema_version": "btc_okx_public_l2_observer_slice_metadata_v1",
                "ticket_id": TICKET_ID,
                "slice_id": inflight["slice_id"],
                "dataset_version": inflight["dataset_version"],
                "source_head": config.source_head,
                "clock": base_health["direct_clock"],
                "w32time": w32,
                "w32time_degraded": base_health["w32time_degraded"],
                "tls": {
                    "official_public_ws_url": config.public_ws_url,
                    "verification_disabled": False,
                    "hostname_verification_disabled": False,
                    "system_ca_required": True,
                },
                "proxy": base_health["proxy"],
                "safety_flags": SAFETY_FLAGS,
            },
        )
    publication_result_path = slice_root / "publication_result.json"
    try:
        if publication_result_path.exists():
            publication = _read_json(publication_result_path)
        else:
            publication = _publish(
                config=config,
                deps=deps,
                slice_root=slice_root,
                dataset_version=str(inflight["dataset_version"]),
                attestation=attestation,
            )
            _write_json_atomic(publication_result_path, publication)
    except Exception as exc:  # noqa: BLE001
        state_after = dict(state)
        return _finalize_event(
            config=config,
            inflight=inflight,
            state_after=state_after,
            status="blocked_publication",
            checked_at=checked_at,
            health={
                **base_health,
                "capture": capture,
                "export": export_report,
                "blockers": [f"observer_publication_exception:{type(exc).__name__}:{exc}"],
                "resume_same_slice": True,
            },
            keep_inflight=True,
        )
    state_after = _updated_state(state, attestation=attestation, target_seconds=config.target_seconds)
    status = "complete_quality_checked_observe_only" if state_after["complete"] else "running_resumable"
    return _finalize_event(
        config=config,
        inflight=inflight,
        state_after=state_after,
        status=status,
        checked_at=deps.now(),
        health={
            **base_health,
            "capture": {
                "message_count": capture.get("message_count"),
                "data_message_count": capture.get("data_message_count"),
                "connection_count": capture.get("connection_count"),
                "forced_reconnect_count": capture.get("forced_reconnect_count"),
                "channel_counts": capture.get("channel_counts"),
            },
            "attestation": attestation,
            "publication": publication,
            "blockers": list(attestation.get("promotion_blockers", [])),
        },
        keep_inflight=False,
    )


def run_observer(
    config: ObserverConfig,
    *,
    dependencies: ObserverDependencies | None = None,
) -> dict[str, Any]:
    config = _validate_config(config)
    deps = dependencies or ObserverDependencies()
    if not config.source_head:
        config = ObserverConfig(**{**config.__dict__, "source_head": _git_head(config.repo_root)})
    checked_at = deps.now()
    try:
        with deps.lock(config.lock_path):
            _ensure_owner(config)
            with approved_process_proxy(config.proxy_url):
                state = _load_state(config)
                if state.get("complete") is True:
                    return {
                        "schema_version": SCHEMA_VERSION,
                        "status": "complete_quality_checked_observe_only",
                        "exit_code": EXIT_CODES["complete_quality_checked_observe_only"],
                        "state": state,
                        "safety_flags": SAFETY_FLAGS,
                    }
                while True:
                    result = _run_slice(config, deps, state)
                    if config.once or result["status"] != "running_resumable":
                        return result
                    state = result["state"]
                    deps.sleep(config.retry_sleep_seconds)
    except WriterConflict as exc:
        return _blocked_before_inflight(
            config,
            status="blocked_writer_conflict",
            checked_at=checked_at,
            blocker=str(exc),
        )
    except SharedDataError as exc:
        return _blocked_before_inflight(
            config,
            status="blocked_publication",
            checked_at=checked_at,
            blocker=str(exc),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--shared-data-root", required=True)
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--slice-seconds", type=float, default=3_600.0)
    parser.add_argument("--max-messages", type=int, default=500_000)
    parser.add_argument("--clock-samples", type=int, default=11)
    parser.add_argument("--forced-reconnect-after-messages", type=int, default=20)
    parser.add_argument("--proxy-url", default=PROXY_URL)
    parser.add_argument("--public-ws-url", default=OKX_L2_PUBLIC_WS_URL)
    parser.add_argument("--retry-sleep-seconds", type=float, default=30.0)
    parser.add_argument("--minimum-free-gib", type=float, default=MINIMUM_FREE_GIB)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = ObserverConfig(
        repo_root=Path(args.repo_root),
        runtime_root=Path(args.runtime_root),
        shared_data_root=Path(args.shared_data_root),
        duration_hours=args.duration_hours,
        slice_seconds=args.slice_seconds,
        max_messages=args.max_messages,
        clock_samples=args.clock_samples,
        forced_reconnect_after_messages=args.forced_reconnect_after_messages,
        proxy_url=args.proxy_url,
        public_ws_url=args.public_ws_url,
        execute_network=args.execute_network,
        once=args.once,
        retry_sleep_seconds=args.retry_sleep_seconds,
        minimum_free_gib=args.minimum_free_gib,
    )
    result = run_observer(config)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
