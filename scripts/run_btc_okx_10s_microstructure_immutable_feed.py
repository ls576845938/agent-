#!/usr/bin/env python3
"""Run durable public-only OKX trades+books immutable feed slices."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_crypto.data.immutable_okx_10s_microstructure_export import (  # noqa: E402
    ATTESTATION_NAME,
    DATASET_ID,
    MicrostructureExportBlocked,
    MicrostructureSegmentSource,
    export_immutable_okx_10s_microstructure,
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
from scripts.run_btc_okx_public_l2_immutable_observer import (  # noqa: E402
    PROXY_URL,
    WriterConflict,
    approved_process_proxy,
    exclusive_writer_lock,
)
from tools.agent_governance.shared_data import (  # noqa: E402
    SharedDataError,
    default_shared_data_root,
    publish_dataset,
    resolve_manifest_payload,
)


SCHEMA_VERSION = "btc_okx_10s_microstructure_immutable_feed_runner_v1"
STATE_SCHEMA_VERSION = "btc_okx_10s_microstructure_immutable_feed_state_v1"
OWNER_SCHEMA_VERSION = "btc_okx_10s_microstructure_immutable_feed_owner_v1"
TICKET_ID = "BTC-10S-MICROSTRUCTURE-IMMUTABLE-FEED-01"
PRODUCER_ROLE = "data_steward"
MINIMUM_FREE_GIB = 20.0
EXACT_CHANNELS = ["trades", "books"]
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
    "transfer_used": False,
    "real_order_submitted": False,
    "paper_queue_written": False,
}
EXIT_CODES = {
    "published_quality_checked": 0,
    "blocked_writer_conflict": 20,
    "blocked_owner_conflict": 21,
    "blocked_storage": 22,
    "blocked_clock": 23,
    "blocked_public_network": 24,
    "blocked_export": 25,
    "blocked_publication": 26,
    "blocked_runtime_prune": 27,
}
RECOVERABLE_STATUSES = {
    "blocked_clock",
    "blocked_public_network",
    "blocked_publication",
}
TERMINAL_STATUSES = {
    "blocked_writer_conflict",
    "blocked_owner_conflict",
    "blocked_storage",
    "blocked_export",
    "blocked_runtime_prune",
}
PUBLIC_SNAPSHOT_RESYNC_EXPORT_BLOCKERS = frozenset(
    {
        "l2_clock_lag_exceeds_limit",
        "l2_update_requires_new_snapshot",
    }
)


@dataclass(frozen=True)
class FeedConfig:
    repo_root: Path
    runtime_root: Path
    shared_data_root: Path
    duration_seconds: float = 90.0
    max_messages: int = 500_000
    clock_samples: int = 11
    forced_reconnect_after_messages: int = 0
    execute_network: bool = False
    minimum_free_gib: float = MINIMUM_FREE_GIB
    public_ws_url: str = OKX_L2_PUBLIC_WS_URL
    proxy_url: str = PROXY_URL
    source_head: str = ""
    taker_fee_bps: float = 5.0
    prune_published_runtime_payload: bool | None = None

    @property
    def lock_path(self) -> Path:
        return self.runtime_root / "writer.lock"


@dataclass
class FeedDependencies:
    clock: Callable[..., dict[str, Any]] = build_btc_okx_server_time_preflight_report
    capture: Callable[..., dict[str, Any]] = capture_okx_public_ws_l2_raw_data
    export: Callable[..., dict[str, Any]] = export_immutable_okx_10s_microstructure
    publish: Callable[..., dict[str, Any]] = publish_dataset
    now: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(timezone.utc))
    disk_free_bytes: Callable[[Path], int] = field(default_factory=lambda: lambda path: shutil.disk_usage(path).free)
    lock: Callable[[Path], Any] = exclusive_writer_lock
    proxy: Callable[[str], Any] = approved_process_proxy
    resolve_published: Callable[..., Path] = resolve_manifest_payload
    remove_tree: Callable[[Path], None] = field(
        default_factory=lambda: lambda path: shutil.rmtree(path)
    )


class RuntimePruneBlocked(RuntimeError):
    def __init__(self, blocker: str, receipt_path: Path | None = None):
        self.blocker = blocker
        self.receipt_path = receipt_path
        super().__init__(blocker)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


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


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(
            (
                json.dumps(
                    dict(payload),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        )
        handle.flush()
        os.fsync(handle.fileno())


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SharedDataError(f"feed_json_object_required:{path.name}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _tree_bytes(path: Path) -> int:
    total = 0
    for root, _, names in os.walk(path):
        directory = Path(root)
        total += sum((directory / name).stat().st_size for name in names)
    return total


def _prune_failure(
    config: FeedConfig,
    deps: FeedDependencies,
    inflight: Mapping[str, Any],
    blocker: str,
) -> RuntimePruneBlocked:
    receipt_path: Path | None = None
    try:
        receipt_path = (
            config.runtime_root
            / "prune_receipts"
            / (
                f"{inflight['slice_id']}-failed-"
                f"{deps.now().strftime('%Y%m%dT%H%M%S%fZ').lower()}-"
                f"{time.time_ns()}.json"
            )
        )
        _write_json_exclusive(
            receipt_path,
            {
                "schema_version": "btc_okx_10s_microstructure_prune_receipt_v1",
                "ticket_id": TICKET_ID,
                "status": "failed",
                "slice_id": inflight["slice_id"],
                "dataset_id": DATASET_ID,
                "dataset_version": inflight["dataset_version"],
                "checked_at_utc": _utc_text(deps.now()),
                "blockers": [blocker],
                "shared_data_deleted": False,
                "safety_flags": SAFETY_FLAGS,
            },
        )
    except Exception:
        receipt_path = None
    return RuntimePruneBlocked(blocker, receipt_path)


def _prune_completed_slice(
    config: FeedConfig,
    deps: FeedDependencies,
    inflight: Mapping[str, Any],
) -> dict[str, Any]:
    slice_id = str(inflight.get("slice_id", ""))
    dataset_version = str(inflight.get("dataset_version", ""))
    if not re.fullmatch(r"slice-[0-9]{8}-[0-9a-z]+", slice_id):
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_slice_identity_invalid"
        )
    slices_root = (config.runtime_root / "slices").resolve()
    slice_root = (slices_root / slice_id).resolve()
    if slice_root.parent != slices_root or slice_root.name != slice_id:
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_slice_path_escape"
        )
    completed_path = (
        config.runtime_root / "completed_inflight" / f"{slice_id}.json"
    )
    if not completed_path.is_file() or _read_json(completed_path) != dict(inflight):
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_completed_inflight_missing"
        )
    event_path = (
        config.runtime_root
        / "events"
        / f"{slice_id}-published_quality_checked.json"
    )
    if not event_path.is_file():
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_published_event_missing"
        )
    event = _read_json(event_path)
    if (
        event.get("status") != "published_quality_checked"
        or event.get("dataset_version") != dataset_version
    ):
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_published_event_invalid"
        )
    durable_state = _load_state(config)
    event_state = event.get("state_after")
    if (
        not isinstance(event_state, Mapping)
        or int(durable_state.get("published_slice_count", 0))
        < int(event_state.get("published_slice_count", 0))
    ):
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_latest_pointer_not_finalized"
        )
    publication_path = slice_root / "publication_result.json"
    manifest_path = config.runtime_root / "manifests" / f"{dataset_version}.json"
    if not publication_path.is_file() or not manifest_path.is_file():
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_publication_evidence_missing"
        )
    publication = _read_json(publication_path)
    manifest = _read_json(manifest_path)
    if (
        publication.get("status") not in {"published", "already_published"}
        or publication.get("manifest") != manifest
        or manifest.get("dataset_id") != DATASET_ID
        or manifest.get("dataset_version") != dataset_version
    ):
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_publication_evidence_invalid"
        )
    try:
        shared_target = deps.resolve_published(
            manifest,
            shared_root=config.shared_data_root,
            verify_files=True,
        ).resolve()
    except Exception as exc:
        raise _prune_failure(
            config,
            deps,
            inflight,
            f"runtime_prune_shared_full_hash_unverified:{type(exc).__name__}:{exc}",
        ) from exc
    expected_target = (
        config.shared_data_root / str(manifest["storage_relative_path"])
    ).resolve()
    if shared_target != expected_target or _is_relative_to(
        shared_target, config.runtime_root
    ):
        raise _prune_failure(
            config, deps, inflight, "runtime_prune_shared_target_identity_invalid"
        )
    success_receipt = (
        config.runtime_root / "prune_receipts" / f"{slice_id}-pruned.json"
    )
    if success_receipt.is_file():
        receipt = _read_json(success_receipt)
        if (
            receipt.get("status") != "pruned"
            or receipt.get("dataset_version") != dataset_version
            or receipt.get("aggregate_sha256") != manifest.get("aggregate_sha256")
        ):
            raise _prune_failure(
                config, deps, inflight, "runtime_prune_receipt_identity_invalid"
            )
        return receipt
    exact_targets = [slice_root / "capture", slice_root / "immutable_export"]
    for target in exact_targets:
        resolved = target.resolve()
        if (
            resolved.parent != slice_root
            or resolved.name not in {"capture", "immutable_export"}
            or _is_relative_to(shared_target, resolved)
            or _is_relative_to(resolved, shared_target)
        ):
            raise _prune_failure(
                config, deps, inflight, "runtime_prune_target_identity_invalid"
            )
    expected_removed_bytes = sum(
        int(item.get("bytes", 0))
        for item in manifest.get("files", [])
        if str(item.get("path", "")).startswith(("capture/", "immutable_export/"))
    )
    removed_this_attempt = 0
    try:
        for target in exact_targets:
            if target.is_dir():
                removed_this_attempt += _tree_bytes(target)
                deps.remove_tree(target)
            elif target.exists():
                raise RuntimeError(f"runtime_prune_target_not_directory:{target.name}")
    except Exception as exc:
        raise _prune_failure(
            config,
            deps,
            inflight,
            f"runtime_prune_delete_failed:{type(exc).__name__}:{exc}",
        ) from exc
    receipt = {
        "schema_version": "btc_okx_10s_microstructure_prune_receipt_v1",
        "ticket_id": TICKET_ID,
        "status": "pruned",
        "slice_id": slice_id,
        "dataset_id": DATASET_ID,
        "dataset_version": dataset_version,
        "aggregate_sha256": manifest["aggregate_sha256"],
        "manifest_sha256": _sha256_file(manifest_path),
        "shared_target": manifest["storage_relative_path"],
        "shared_full_hash_verified": True,
        "removed_paths": [
            f"slices/{slice_id}/capture",
            f"slices/{slice_id}/immutable_export",
        ],
        "removed_bytes": expected_removed_bytes,
        "removed_bytes_this_attempt": removed_this_attempt,
        "completed_at_utc": _utc_text(deps.now()),
        "shared_data_deleted": False,
        "safety_flags": SAFETY_FLAGS,
    }
    try:
        _write_json_exclusive(success_receipt, receipt)
    except Exception as exc:
        raise _prune_failure(
            config,
            deps,
            inflight,
            f"runtime_prune_receipt_write_failed:{type(exc).__name__}:{exc}",
        ) from exc
    return receipt


def _recover_pending_prunes(
    config: FeedConfig,
    deps: FeedDependencies,
) -> list[dict[str, Any]]:
    completed_root = config.runtime_root / "completed_inflight"
    if not completed_root.is_dir():
        return []
    receipts: list[dict[str, Any]] = []
    for path in sorted(completed_root.iterdir(), key=lambda item: item.name):
        if not path.is_file() or not re.fullmatch(
            r"slice-[0-9]{8}-[0-9a-z]+\.json", path.name
        ):
            continue
        inflight = _read_json(path)
        published_event = (
            config.runtime_root
            / "events"
            / f"{inflight.get('slice_id', '')}-published_quality_checked.json"
        )
        if not published_event.is_file():
            continue
        receipts.append(_prune_completed_slice(config, deps, inflight))
    return receipts


def _git_head(root: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _validated(config: FeedConfig) -> FeedConfig:
    repo = config.repo_root.resolve()
    runtime = config.runtime_root.resolve()
    shared = config.shared_data_root.resolve()
    if runtime == shared:
        raise ValueError("feed_runtime_and_shared_roots_must_differ")
    for path, code in ((runtime, "runtime"), (shared, "shared")):
        try:
            path.relative_to(repo)
        except ValueError:
            pass
        else:
            raise ValueError(f"feed_{code}_root_must_be_outside_repo")
    if config.public_ws_url != OKX_L2_PUBLIC_WS_URL:
        raise ValueError("feed_public_ws_url_not_allowlisted")
    if config.proxy_url != PROXY_URL:
        raise ValueError("feed_proxy_not_approved")
    if not 60 <= config.duration_seconds <= 600:
        raise ValueError("feed_duration_must_be_60_to_600_seconds")
    if config.max_messages <= 0 or config.clock_samples < 9:
        raise ValueError("feed_capture_limits_invalid")
    if config.minimum_free_gib < MINIMUM_FREE_GIB:
        raise ValueError("feed_storage_guard_below_contract")
    return FeedConfig(**{**config.__dict__, "repo_root": repo, "runtime_root": runtime, "shared_data_root": shared})


def _owner(config: FeedConfig) -> dict[str, Any]:
    return {
        "schema_version": OWNER_SCHEMA_VERSION,
        "ticket_id": TICKET_ID,
        "dataset_id": DATASET_ID,
        "repository_root": str(config.repo_root),
        "source_head": config.source_head,
        "single_writer": True,
    }


def _ensure_owner(config: FeedConfig) -> None:
    path = config.runtime_root / "owner.json"
    expected = _owner(config)
    if path.exists():
        if _read_json(path) != expected:
            raise WriterConflict("feed_runtime_owner_conflict")
        return
    _write_json_exclusive(path, expected)


def _load_state(config: FeedConfig) -> dict[str, Any]:
    pointer_path = config.runtime_root / "latest_pointer.json"
    if not pointer_path.exists():
        return {"schema_version": STATE_SCHEMA_VERSION, "attempt_count": 0, "published_slice_count": 0}
    pointer = _read_json(pointer_path)
    event_path = config.runtime_root / str(pointer.get("event_path", ""))
    if not event_path.is_file() or _sha256_file(event_path) != pointer.get("event_sha256"):
        raise SharedDataError("feed_latest_event_missing_or_hash_mismatch")
    state = _read_json(event_path).get("state_after")
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise SharedDataError("feed_latest_state_invalid")
    return dict(state)


def _inflight(config: FeedConfig, state: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    path = config.runtime_root / "inflight.json"
    if path.exists():
        value = _read_json(path)
        if value.get("ticket_id") != TICKET_ID or value.get("source_head") != config.source_head:
            raise SharedDataError("feed_inflight_identity_conflict")
        return value
    index = int(state.get("attempt_count", 0)) + 1
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ").lower()
    value = {
        "schema_version": "btc_okx_10s_microstructure_inflight_v1",
        "ticket_id": TICKET_ID,
        "source_head": config.source_head,
        "slice_id": f"slice-{index:08d}-{stamp}",
        "dataset_version": f"btc-okx-10s-feed-{index:08d}-{stamp}-src{config.source_head[:10]}",
        "started_at_utc": _utc_text(now),
    }
    _write_json_atomic(path, value)
    return value


def _capture_or_read(config: FeedConfig, deps: FeedDependencies, slice_root: Path) -> dict[str, Any]:
    capture_dir = slice_root / "capture"
    report_path = slice_root / "capture_report.json"
    if (
        report_path.is_file()
        and (capture_dir / OKX_L2_RAW_MESSAGES_FILE).is_file()
        and (capture_dir / OKX_L2_RAW_MANIFEST_FILE).is_file()
    ):
        report = _read_json(report_path)
        if report.get("status") == "verified_preflight" and report.get("channels") == EXACT_CHANNELS:
            return report
    capture_dir.mkdir(parents=True, exist_ok=True)
    return deps.capture(
        repo_root=config.repo_root,
        bundle_dir=capture_dir,
        capture_report_path=report_path,
        execute_network=config.execute_network,
        duration_seconds=config.duration_seconds,
        max_messages=config.max_messages,
        channels=list(EXACT_CHANNELS),
        recv_timeout_seconds=5.0,
        forced_reconnect_after_messages=config.forced_reconnect_after_messages,
        public_ws_url=config.public_ws_url,
    )


def _export_or_read(config: FeedConfig, deps: FeedDependencies, slice_root: Path, version: str, now: datetime) -> dict[str, Any]:
    output = slice_root / "immutable_export"
    attestation = output / ATTESTATION_NAME
    if attestation.is_file():
        return {"status": "quality_checked", "attestation_path": str(attestation), **_read_json(attestation)}
    capture = slice_root / "capture"
    raw = capture / OKX_L2_RAW_MESSAGES_FILE
    manifest = capture / OKX_L2_RAW_MANIFEST_FILE
    return deps.export(
        segments=(MicrostructureSegmentSource(capture, _sha256_file(raw), _sha256_file(manifest)),),
        output_dir=output,
        dataset_version=version,
        source_head=config.source_head,
        now=now,
        producer_role=PRODUCER_ROLE,
        taker_fee_bps=config.taker_fee_bps,
    )


def _is_public_snapshot_resync_export_failure(
    exc: MicrostructureExportBlocked,
) -> bool:
    """Recognize only the frozen recoverable public snapshot-resync failure."""

    return frozenset(exc.blockers) == PUBLIC_SNAPSHOT_RESYNC_EXPORT_BLOCKERS


def _finalize(
    config: FeedConfig,
    *,
    inflight: Mapping[str, Any],
    state: Mapping[str, Any],
    status: str,
    now: datetime,
    evidence: Mapping[str, Any],
    keep_inflight: bool,
) -> dict[str, Any]:
    event_id = f"{inflight['slice_id']}-{status}"
    health_path = config.runtime_root / "health" / f"{event_id}.json"
    health = {
        "schema_version": "btc_okx_10s_microstructure_feed_health_v1",
        "event_id": event_id,
        "status": status,
        "checked_at_utc": _utc_text(now),
        "source_head": config.source_head,
        "evidence": dict(evidence),
        "safety_flags": SAFETY_FLAGS,
    }
    if not health_path.exists():
        _write_json_exclusive(health_path, health)
    event_path = config.runtime_root / "events" / f"{event_id}.json"
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "ticket_id": TICKET_ID,
        "status": status,
        "dataset_version": inflight["dataset_version"],
        "created_at_utc": _utc_text(now),
        "health_path": health_path.relative_to(config.runtime_root).as_posix(),
        "health_sha256": _sha256_file(health_path),
        "state_after": dict(state),
        "safety_flags": SAFETY_FLAGS,
    }
    if not event_path.exists():
        _write_json_exclusive(event_path, event)
    pointer = {
        "schema_version": "btc_okx_10s_microstructure_feed_latest_pointer_v1",
        "event_id": event_id,
        "event_path": event_path.relative_to(config.runtime_root).as_posix(),
        "event_sha256": _sha256_file(event_path),
        "updated_at_utc": _utc_text(now),
        "latest_pointer_updated_last": True,
    }
    _write_json_atomic(config.runtime_root / "latest_pointer.json", pointer)
    if not keep_inflight:
        path = config.runtime_root / "inflight.json"
        if path.exists():
            completed = config.runtime_root / "completed_inflight" / f"{inflight['slice_id']}.json"
            completed.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, completed)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "exit_code": EXIT_CODES[status],
        "event_id": event_id,
        "event_path": str(event_path),
        "health_path": str(health_path),
        "dataset_version": inflight["dataset_version"],
        "state": dict(state),
        "retryable": status == "blocked_clock"
        or (status == "blocked_public_network" and config.execute_network)
        or (status == "blocked_publication" and keep_inflight),
        "safety_flags": SAFETY_FLAGS,
    }


def _runtime_prune_result(
    exc: RuntimePruneBlocked,
    *,
    published_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked_runtime_prune",
        "exit_code": EXIT_CODES["blocked_runtime_prune"],
        "blockers": [exc.blocker],
        "prune_failure_receipt": (
            str(exc.receipt_path) if exc.receipt_path is not None else ""
        ),
        "publication_committed": True,
        "published_this_attempt": published_result is not None,
        "published_result": dict(published_result) if published_result else None,
        "retryable": False,
        "safety_flags": SAFETY_FLAGS,
    }


def run_feed_slice(config: FeedConfig, *, dependencies: FeedDependencies | None = None) -> dict[str, Any]:
    config = _validated(config)
    deps = dependencies or FeedDependencies()
    if not config.source_head:
        config = FeedConfig(**{**config.__dict__, "source_head": _git_head(config.repo_root)})
    checked_at = deps.now()
    try:
        with deps.lock(config.lock_path):
            try:
                _ensure_owner(config)
            except WriterConflict as exc:
                return {"schema_version": SCHEMA_VERSION, "status": "blocked_owner_conflict", "exit_code": EXIT_CODES["blocked_owner_conflict"], "blockers": [str(exc)], "retryable": False, "safety_flags": SAFETY_FLAGS}
            if config.prune_published_runtime_payload is True:
                try:
                    _recover_pending_prunes(config, deps)
                except RuntimePruneBlocked as exc:
                    return _runtime_prune_result(exc)
            state = _load_state(config)
            inflight = _inflight(config, state, checked_at)
            state_after = dict(state)
            state_after["attempt_count"] = max(int(state.get("attempt_count", 0)), int(str(inflight["slice_id"]).split("-")[1]))
            probe = config.runtime_root.parent
            free_gib = deps.disk_free_bytes(probe) / (1024.0**3)
            if free_gib < config.minimum_free_gib:
                return _finalize(config, inflight=inflight, state=state_after, status="blocked_storage", now=checked_at, evidence={"free_gib": free_gib, "blockers": ["feed_storage_below_20_gib"]}, keep_inflight=False)
            slice_root = config.runtime_root / "slices" / str(inflight["slice_id"])
            slice_root.mkdir(parents=True, exist_ok=True)
            with deps.proxy(config.proxy_url):
                clock_dir = slice_root / "clock"
                clock_path = clock_dir / "btc_okx_server_time_preflight_report.json"
                clock = _read_json(clock_path) if clock_path.exists() else deps.clock(
                    repo_root=config.repo_root,
                    output_dir=clock_dir,
                    execute_network=config.execute_network,
                    generated_at_utc=checked_at,
                    max_abs_offset_ms=2_000.0,
                    max_round_trip_ms=5_000.0,
                    sample_count=config.clock_samples,
                )
                if clock.get("server_time_offset_verified") is not True:
                    return _finalize(config, inflight=inflight, state=state_after, status="blocked_clock", now=deps.now(), evidence={"clock": clock, "blockers": list(clock.get("blockers", []))}, keep_inflight=False)
                if not config.execute_network:
                    return _finalize(config, inflight=inflight, state=state_after, status="blocked_public_network", now=deps.now(), evidence={"blockers": ["feed_network_execution_not_enabled"]}, keep_inflight=False)
                capture = _capture_or_read(config, deps, slice_root)
                if capture.get("status") != "verified_preflight" or tuple(capture.get("channels", [])) != tuple(EXACT_CHANNELS):
                    return _finalize(config, inflight=inflight, state=state_after, status="blocked_public_network", now=deps.now(), evidence={"capture": capture, "blockers": list(capture.get("blockers", []))}, keep_inflight=False)
                try:
                    export = _export_or_read(config, deps, slice_root, str(inflight["dataset_version"]), deps.now())
                except MicrostructureExportBlocked as exc:
                    blockers = list(exc.blockers)
                    if _is_public_snapshot_resync_export_failure(exc):
                        return _finalize(
                            config,
                            inflight=inflight,
                            state=state_after,
                            status="blocked_public_network",
                            now=deps.now(),
                            evidence={
                                "blockers": blockers,
                                "recovery_action": (
                                    "new_slice_new_connection_wait_for_snapshot"
                                ),
                                "failed_slice_publishable": False,
                                "raw_capture_preserved": True,
                            },
                            keep_inflight=False,
                        )
                    return _finalize(
                        config,
                        inflight=inflight,
                        state=state_after,
                        status="blocked_export",
                        now=deps.now(),
                        evidence={
                            "blockers": [
                                "feed_export_exception:"
                                f"{type(exc).__name__}:{exc}"
                            ],
                            "export_blockers": blockers,
                        },
                        keep_inflight=False,
                    )
                except Exception as exc:  # fail-closed evidence; exact blocker is retained
                    return _finalize(config, inflight=inflight, state=state_after, status="blocked_export", now=deps.now(), evidence={"blockers": [f"feed_export_exception:{type(exc).__name__}:{exc}"]}, keep_inflight=False)
                attestation = _read_json(slice_root / "immutable_export" / ATTESTATION_NAME)
                metadata = slice_root / "feed_slice_metadata.json"
                if not metadata.exists():
                    _write_json_exclusive(metadata, {"schema_version": "btc_okx_10s_microstructure_feed_slice_metadata_v1", "ticket_id": TICKET_ID, "dataset_version": inflight["dataset_version"], "source_head": config.source_head, "clock": clock, "channels": EXACT_CHANNELS, "safety_flags": SAFETY_FLAGS})
                manifest_path = config.runtime_root / "manifests" / f"{inflight['dataset_version']}.json"
                publication_result = slice_root / "publication_result.json"
                try:
                    publication = _read_json(publication_result) if publication_result.exists() else deps.publish(
                        source=slice_root,
                        shared_root=config.shared_data_root,
                        dataset_id=DATASET_ID,
                        dataset_version=str(inflight["dataset_version"]),
                        readiness_class="quality_checked",
                        quality_status="pass_with_research_only_warnings",
                        producer_role=PRODUCER_ROLE,
                        producer_commit=config.source_head,
                        schema_name=str(attestation["schema_version"]),
                        blockers=["btc_10s_research_admission_not_yet_rebuilt_from_this_manifest"],
                        known_gaps=[],
                        coverage_start=str(attestation["coverage_start"]),
                        coverage_end=str(attestation["coverage_end"]),
                        manifest_output=manifest_path,
                    )
                    if not publication_result.exists():
                        _write_json_atomic(publication_result, publication)
                except Exception as exc:
                    return _finalize(config, inflight=inflight, state=state_after, status="blocked_publication", now=deps.now(), evidence={"export": export, "blockers": [f"feed_publication_exception:{type(exc).__name__}:{exc}"], "resume_same_slice": True}, keep_inflight=True)
            state_after["published_slice_count"] = int(state.get("published_slice_count", 0)) + 1
            state_after["latest_dataset_version"] = inflight["dataset_version"]
            published_result = _finalize(config, inflight=inflight, state=state_after, status="published_quality_checked", now=deps.now(), evidence={"capture": {"message_count": capture.get("message_count"), "channel_counts": capture.get("channel_counts")}, "export": export, "publication": publication}, keep_inflight=False)
            if config.prune_published_runtime_payload is True:
                try:
                    published_result["prune_receipt"] = _prune_completed_slice(
                        config, deps, inflight
                    )
                except RuntimePruneBlocked as exc:
                    return _runtime_prune_result(
                        exc, published_result=published_result
                    )
            return published_result
    except WriterConflict as exc:
        return {"schema_version": SCHEMA_VERSION, "status": "blocked_writer_conflict", "exit_code": EXIT_CODES["blocked_writer_conflict"], "blockers": [str(exc)], "retryable": False, "safety_flags": SAFETY_FLAGS}
    except SharedDataError as exc:
        return {"schema_version": SCHEMA_VERSION, "status": "blocked_publication", "exit_code": EXIT_CODES["blocked_publication"], "blockers": [str(exc)], "retryable": False, "safety_flags": SAFETY_FLAGS}


def run_feed_continuously(
    config: FeedConfig,
    *,
    dependencies: FeedDependencies | None = None,
    max_slices: int = 0,
    stop_sentinel: Path | None = None,
    initial_backoff_seconds: float = 5.0,
    max_backoff_seconds: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run sequential immutable slices until stopped or terminally blocked."""
    config = _validated(config)
    if not config.source_head:
        config = FeedConfig(
            **{**config.__dict__, "source_head": _git_head(config.repo_root)}
        )
    if config.prune_published_runtime_payload is None:
        config = FeedConfig(
            **{
                **config.__dict__,
                "prune_published_runtime_payload": True,
            }
        )
    if max_slices < 0:
        raise ValueError("feed_continuous_max_slices_invalid")
    if initial_backoff_seconds < 0 or max_backoff_seconds < initial_backoff_seconds:
        raise ValueError("feed_continuous_backoff_invalid")
    sentinel = (stop_sentinel or (config.runtime_root / "STOP")).resolve()
    try:
        sentinel.relative_to(config.runtime_root)
    except ValueError as exc:
        raise ValueError("feed_stop_sentinel_must_be_inside_runtime_root") from exc
    deps = dependencies or FeedDependencies()
    locked_deps = FeedDependencies(
        clock=deps.clock,
        capture=deps.capture,
        export=deps.export,
        publish=deps.publish,
        now=deps.now,
        disk_free_bytes=deps.disk_free_bytes,
        lock=lambda _: nullcontext(),
        proxy=deps.proxy,
        resolve_published=deps.resolve_published,
        remove_tree=deps.remove_tree,
    )
    audit_path = config.runtime_root / "continuous_attempts.jsonl"
    attempts = 0
    published = 0
    backoff = initial_backoff_seconds
    last_result: dict[str, Any] | None = None

    def summary(status: str, exit_code: int) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "exit_code": exit_code,
            "attempt_count": attempts,
            "published_slice_count": published,
            "last_result": last_result,
            "audit_path": str(audit_path),
            "stop_sentinel": str(sentinel),
            "safety_flags": SAFETY_FLAGS,
        }

    try:
        with deps.lock(config.lock_path):
            try:
                _ensure_owner(config)
            except WriterConflict as exc:
                last_result = {
                    "status": "blocked_owner_conflict",
                    "exit_code": EXIT_CODES["blocked_owner_conflict"],
                    "blockers": [str(exc)],
                    "retryable": False,
                    "safety_flags": SAFETY_FLAGS,
                }
                return summary(
                    "continuous_terminal_blocked",
                    EXIT_CODES["blocked_owner_conflict"],
                )
            while True:
                if sentinel.exists():
                    return summary("continuous_stopped_by_sentinel", 0)
                if max_slices and published >= max_slices:
                    return summary("continuous_max_slices_reached", 0)
                result = run_feed_slice(config, dependencies=locked_deps)
                attempts += 1
                last_result = result
                _append_jsonl(
                    audit_path,
                    {
                        "attempt": attempts,
                        "observed_at_utc": _utc_text(deps.now()),
                        "result": result,
                    },
                )
                status = str(result.get("status", ""))
                if status == "published_quality_checked":
                    published += 1
                    backoff = initial_backoff_seconds
                    continue
                if result.get("published_this_attempt") is True:
                    published += 1
                if status in TERMINAL_STATUSES or result.get("retryable") is not True:
                    return summary("continuous_terminal_blocked", int(result.get("exit_code", 1)))
                if status not in RECOVERABLE_STATUSES:
                    return summary("continuous_terminal_blocked", int(result.get("exit_code", 1)))
                sleep(backoff)
                backoff = min(max_backoff_seconds, max(initial_backoff_seconds, backoff * 2.0))
    except KeyboardInterrupt:
        return summary("continuous_stopped_by_interrupt", 0)
    except WriterConflict as exc:
        last_result = {
            "status": "blocked_writer_conflict",
            "exit_code": EXIT_CODES["blocked_writer_conflict"],
            "blockers": [str(exc)],
            "retryable": False,
            "safety_flags": SAFETY_FLAGS,
        }
        return summary(
            "continuous_terminal_blocked", EXIT_CODES["blocked_writer_conflict"]
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--duration-seconds", type=float, default=90.0)
    parser.add_argument("--max-messages", type=int, default=500_000)
    parser.add_argument("--clock-samples", type=int, default=11)
    parser.add_argument("--forced-reconnect-after-messages", type=int, default=0)
    parser.add_argument("--minimum-free-gib", type=float, default=MINIMUM_FREE_GIB)
    parser.add_argument("--proxy-url", default=PROXY_URL)
    parser.add_argument("--public-ws-url", default=OKX_L2_PUBLIC_WS_URL)
    parser.add_argument("--taker-fee-bps", type=float, default=5.0)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument(
        "--prune-published-runtime-payload",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "After durable publication, full-hash verify shared-data and prune "
            "only the exact runtime capture/ and immutable_export/ directories; "
            "defaults on in --continuous mode."
        ),
    )
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--max-slices", type=int, default=0)
    parser.add_argument("--stop-sentinel", type=Path)
    parser.add_argument("--initial-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--max-backoff-seconds", type=float, default=60.0)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    config = FeedConfig(
        repo_root=root,
        runtime_root=args.runtime_root,
        shared_data_root=(args.shared_data_root or default_shared_data_root(root)),
        duration_seconds=args.duration_seconds,
        max_messages=args.max_messages,
        clock_samples=args.clock_samples,
        forced_reconnect_after_messages=args.forced_reconnect_after_messages,
        execute_network=args.execute_network,
        minimum_free_gib=args.minimum_free_gib,
        proxy_url=args.proxy_url,
        public_ws_url=args.public_ws_url,
        taker_fee_bps=args.taker_fee_bps,
        prune_published_runtime_payload=args.prune_published_runtime_payload,
    )
    if args.continuous:
        result = run_feed_continuously(
            config,
            max_slices=args.max_slices,
            stop_sentinel=args.stop_sentinel,
            initial_backoff_seconds=args.initial_backoff_seconds,
            max_backoff_seconds=args.max_backoff_seconds,
        )
    else:
        result = run_feed_slice(config)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
