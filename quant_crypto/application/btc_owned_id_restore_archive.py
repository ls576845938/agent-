"""Canonical, identity-bound owned-ID restore archive publisher.

The publisher consumes an immutable observation archive and one injected
read-only OKX Demo snapshot.  It never submits an order and never mutates the
source archive.  The output is deliberately an identity-only restore
admission; it is not observation or promotion evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from quant_crypto.oms.okx_demo import (
    OKX_DEMO_INSTRUMENT_ID,
    OkxDemoClientConfig,
    OkxDemoCredentials,
    OkxDemoReadOnlyClient,
    OkxDemoSafetyError,
    OkxDemoResponse,
    load_windows_keyring_credentials,
)
from quant_crypto.research.btc_demo_observation_accumulator import (
    load_observation_receipt_ledger,
)


PUBLISHER_SCHEMA_VERSION = "btc_owned_id_restore_archive_v1"
DERIVED_RECEIPT_SCHEMA_VERSION = "btc_owned_id_restore_receipt_v1"
CHECKPOINT_SCHEMA_VERSION = "btc_demo_oms_runtime_checkpoint_v2"
OKX_DEMO_CREDENTIAL_PREFIX = "quant-system.okx-demo."
EXPECTED_PRIVATE_READ_PATHS = (
    "/api/v5/account/config",
    "/api/v5/account/positions",
    "/api/v5/account/leverage-info",
    "/api/v5/trade/orders-pending",
    "/api/v5/trade/orders-algo-pending",
    "/api/v5/trade/orders-history",
    "/api/v5/trade/fills",
)
EXPECTED_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
HEX40_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
HEX64_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
LOWER_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|passphrase|token|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
DENIED_PROVIDER_MEMBERS = (
    "post",
    "private_post",
    "submit_order",
    "cancel_order",
    "cancel_algo_orders",
    "cancel_all_after",
    "transfer",
    "withdraw",
    "live_post",
)


class OwnedIDRestoreArchiveError(RuntimeError):
    """A source, provider, identity, or publication contract was invalid."""


@dataclass(frozen=True)
class DemoPrivateReadCapability:
    """Opaque read-only capability required by the publisher composition root."""

    environment: str = "OKX Demo"
    methods: tuple[str, ...] = ("GET",)
    private_paths: tuple[str, ...] = EXPECTED_PRIVATE_READ_PATHS
    post_allowed: bool = False
    live_allowed: bool = False
    transfer_allowed: bool = False
    withdraw_allowed: bool = False


@dataclass(frozen=True)
class DemoPrivateReadSnapshot:
    """Normalized facts returned by an injected Demo private-read provider."""

    environment: str
    instrument_id: str
    margin_mode: str
    account: Mapping[str, Any]
    positions: Sequence[Mapping[str, Any]] = ()
    pending_orders: Sequence[Mapping[str, Any]] = ()
    pending_algo_orders: Sequence[Mapping[str, Any]] = ()
    orders: Sequence[Mapping[str, Any]] = ()
    fills: Sequence[Mapping[str, Any]] = ()
    captured_at_utc: str = ""
    fresh: bool = True
    safety: Mapping[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "instrument_id": self.instrument_id,
            "margin_mode": self.margin_mode,
            "account": dict(self.account),
            "positions": [dict(row) for row in self.positions],
            "pending_orders": [dict(row) for row in self.pending_orders],
            "pending_algo_orders": [dict(row) for row in self.pending_algo_orders],
            "orders": [dict(row) for row in self.orders],
            "fills": [dict(row) for row in self.fills],
            "captured_at_utc": self.captured_at_utc,
            "fresh": self.fresh,
            "safety": dict(self.safety),
        }


class DemoPrivateReadSnapshotProvider(Protocol):
    capability: DemoPrivateReadCapability

    def read_snapshot(self) -> DemoPrivateReadSnapshot | Mapping[str, Any]: ...


class OkxDemoPrivateReadSnapshotProvider:
    """Adapter bridge exposing only allowlisted OKX Demo private GET calls."""

    capability = DemoPrivateReadCapability()

    def __init__(self, client: OkxDemoReadOnlyClient) -> None:
        self._client = client

    def _get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        try:
            response = self._client.private_get(path, params)
        except Exception as exc:
            raise OwnedIDRestoreArchiveError(
                "owned_id_restore_private_read_failed"
            ) from exc
        if (
            not isinstance(response, OkxDemoResponse)
            or response.method != "GET"
            or response.path.split("?", 1)[0] != path
            or response.code != "0"
        ):
            raise OwnedIDRestoreArchiveError(
                "owned_id_restore_private_read_response_invalid"
            )
        return tuple(response.data)

    def read_snapshot(self) -> DemoPrivateReadSnapshot:
        account_rows = self._get("/api/v5/account/config")
        leverage_rows = self._get(
            "/api/v5/account/leverage-info",
            {"instId": OKX_DEMO_INSTRUMENT_ID, "mgnMode": "isolated"},
        )
        positions = self._get(
            "/api/v5/account/positions",
            {"instId": OKX_DEMO_INSTRUMENT_ID},
        )
        pending_orders = self._get(
            "/api/v5/trade/orders-pending",
            {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
        )
        pending_algo_orders = self._get(
            "/api/v5/trade/orders-algo-pending",
            {"instId": OKX_DEMO_INSTRUMENT_ID, "ordType": "oco"},
        )
        orders = self._get(
            "/api/v5/trade/orders-history",
            {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
        )
        fills = self._get(
            "/api/v5/trade/fills",
            {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
        )
        account_raw = dict(account_rows[0]) if account_rows else {}
        permissions = sorted(
            item.strip()
            for item in str(account_raw.get("perm") or "").split(",")
            if item.strip()
        )
        account = {
            "account_level": str(account_raw.get("acctLv") or ""),
            "permissions": permissions,
            "position_mode": str(account_raw.get("posMode") or ""),
            "withdraw_permission_present": "withdraw" in permissions,
            "account_identifier": str(
                account_raw.get("uid") or account_raw.get("acctId") or ""
            ),
        }
        leverage = dict(leverage_rows[0]) if leverage_rows else {}
        if leverage and str(leverage.get("mgnMode") or "isolated") != "isolated":
            raise OwnedIDRestoreArchiveError(
                "owned_id_restore_private_read_margin_mode_invalid"
            )
        return DemoPrivateReadSnapshot(
            environment="OKX Demo",
            instrument_id=OKX_DEMO_INSTRUMENT_ID,
            margin_mode="isolated",
            account=account,
            positions=positions,
            pending_orders=pending_orders,
            pending_algo_orders=pending_algo_orders,
            orders=orders,
            fills=fills,
            captured_at_utc=datetime.now(timezone.utc).isoformat(),
            fresh=True,
        )


@dataclass(frozen=True)
class _SourceArchiveFacts:
    root: Path
    manifest: Mapping[str, Any]
    verification: Mapping[str, Any]
    completed: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    source_state: Mapping[str, Any]
    source_orders: Mapping[str, tuple[str, str]]
    source_fills: Mapping[str, tuple[str, str]]
    source_head: str
    manifest_sha256: str
    verification_sha256: str
    completed_sha256: str
    file_hashes: Mapping[str, str]
    owner_marker: Mapping[str, Any]
    receipt_count: int


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OwnedIDRestoreArchiveError(code) from exc
    if not isinstance(value, Mapping):
        raise OwnedIDRestoreArchiveError(code)
    return value


def _safe_archive_path(root: Path, relative: str) -> Path:
    candidate = Path(str(relative))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_archive_path_invalid"
        )
    resolved = (root / candidate).resolve()
    if resolved == root or root not in resolved.parents:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_archive_path_invalid"
        )
    return resolved


def _reject_secret_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if SECRET_KEY_RE.search(str(key)):
                # ``secret_read`` is an established boolean safety attestation;
                # it is safe only when explicitly false and carries no secret.
                if not (str(key).lower() == "secret_read" and child is False):
                    raise OwnedIDRestoreArchiveError(
                        "owned_id_restore_secret_field_forbidden"
                    )
            _reject_secret_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _reject_secret_keys(child)


def _require_hex(value: Any, pattern: re.Pattern[str], code: str) -> str:
    text = str(value or "")
    if not pattern.fullmatch(text):
        raise OwnedIDRestoreArchiveError(code)
    return text


def _repo_head(repo_root: Path) -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_current_head_unavailable"
        ) from exc
    return _require_hex(
        value,
        HEX40_RE,
        "owned_id_restore_current_head_invalid",
    )


def _git_commit_exists(repo_root: Path, commit: str) -> bool:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=str(repo_root),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _owner_marker(
    manifest: Mapping[str, Any],
    *,
    archive_root: Path,
    repo_root: Path,
) -> Mapping[str, Any]:
    owner = manifest.get("owner_marker")
    if not isinstance(owner, Mapping) or owner.get("immutable_archives_only") is not True:
        raise OwnedIDRestoreArchiveError("owned_id_restore_owner_marker_invalid")
    owner_path = Path(str(owner.get("path") or ""))
    if not owner_path.is_absolute():
        owner_path = (archive_root / owner_path).resolve()
    else:
        owner_path = owner_path.resolve()
    if (
        not owner_path.is_file()
        or owner_path == archive_root
        or archive_root in owner_path.parents
        or owner_path == repo_root
        or repo_root in owner_path.parents
        or _sha256_file(owner_path) != str(owner.get("sha256") or "")
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_owner_marker_invalid")
    document = _json(owner_path, "owned_id_restore_owner_marker_invalid")
    if (
        not str(document.get("repository_owner_identity") or "")
        or str(document.get("repository_owner_identity"))
        != str(owner.get("repository_owner_identity") or "")
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_owner_marker_invalid")
    return {
        "immutable_archives_only": True,
        "path": str(owner_path),
        "repository_owner_identity": str(owner.get("repository_owner_identity")),
        "sha256": str(owner.get("sha256")),
    }


def _validate_event_chain(
    events_path: Path,
    state_path: Path,
    manifest: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
    try:
        lines = events_path.read_bytes().splitlines()
    except OSError as exc:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_source_events_unreadable"
        ) from exc
    events: list[Mapping[str, Any]] = []
    previous_hash = ""
    for expected_sequence, line in enumerate(lines, start=1):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OwnedIDRestoreArchiveError(
                "owned_id_restore_event_chain_invalid"
            ) from exc
        if not isinstance(value, Mapping):
            raise OwnedIDRestoreArchiveError("owned_id_restore_event_chain_invalid")
        body = dict(value)
        supplied_hash = str(body.pop("event_hash", "") or "")
        semantic = {
            "event_type": body.get("event_type"),
            "payload": body.get("payload"),
            "run_id": body.get("run_id"),
        }
        try:
            sequence = int(body.get("sequence", -1))
        except (TypeError, ValueError) as exc:
            raise OwnedIDRestoreArchiveError(
                "owned_id_restore_event_chain_invalid"
            ) from exc
        if (
            sequence != expected_sequence
            or str(body.get("previous_event_hash", "") or "") != previous_hash
            or not str(body.get("idempotency_key", "") or "")
            or supplied_hash != _canonical_sha256(body)
            or str(body.get("semantic_hash", "") or "")
            != _canonical_sha256(semantic)
        ):
            raise OwnedIDRestoreArchiveError("owned_id_restore_event_chain_invalid")
        events.append(dict(value))
        previous_hash = supplied_hash
    checkpoint = _json(state_path, "owned_id_restore_checkpoint_invalid")
    checkpoint_body = dict(checkpoint)
    checkpoint_hash = str(checkpoint_body.pop("checkpoint_hash", "") or "")
    try:
        checkpoint_sequence = int(checkpoint_body.get("last_sequence", -1))
    except (TypeError, ValueError) as exc:
        raise OwnedIDRestoreArchiveError("owned_id_restore_checkpoint_invalid") from exc
    if (
        checkpoint_hash != _canonical_sha256(checkpoint_body)
        or checkpoint_sequence != len(events)
        or str(checkpoint_body.get("last_event_hash", "") or "") != previous_hash
        or not isinstance(checkpoint_body.get("state"), Mapping)
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_checkpoint_invalid")
    chain = manifest.get("event_chain")
    verification_chain = verification.get("event_identity")
    if not isinstance(chain, Mapping) or not isinstance(verification_chain, Mapping):
        raise OwnedIDRestoreArchiveError("owned_id_restore_event_chain_invalid")
    actual_file_sha = _sha256_file(events_path)
    for document in (chain, verification_chain):
        try:
            event_count = int(document.get("event_count", -1))
            last_sequence = int(document.get("last_sequence", -1))
        except (TypeError, ValueError) as exc:
            raise OwnedIDRestoreArchiveError(
                "owned_id_restore_event_chain_invalid"
            ) from exc
        if (
            document.get("hash_chain_valid") is not True
            or event_count != len(events)
            or last_sequence != len(events)
            or str(document.get("last_event_hash") or "") != previous_hash
            or str(document.get("file_sha256") or "") != actual_file_sha
        ):
            raise OwnedIDRestoreArchiveError("owned_id_restore_event_chain_invalid")
    if len(events) != 198:
        raise OwnedIDRestoreArchiveError("owned_id_restore_event_count_invalid")
    return tuple(events), checkpoint_body["state"]


def _normalise_account(account: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(account, Mapping):
        raise OwnedIDRestoreArchiveError("owned_id_restore_account_invalid")
    _reject_secret_keys(account)
    raw_permissions = account.get("permissions", account.get("perm", ()))
    if isinstance(raw_permissions, str):
        permissions = sorted(
            item.strip() for item in raw_permissions.split(",") if item.strip()
        )
    elif isinstance(raw_permissions, Sequence) and not isinstance(raw_permissions, (str, bytes)):
        permissions = sorted(str(item) for item in raw_permissions if str(item))
    else:
        raise OwnedIDRestoreArchiveError("owned_id_restore_account_invalid")
    withdraw = account.get("withdraw_permission_present")
    if withdraw is None:
        withdraw = "withdraw" in permissions
    if withdraw is not False or "withdraw" in permissions:
        raise OwnedIDRestoreArchiveError("owned_id_restore_withdraw_permission_present")
    position_mode = str(account.get("position_mode", account.get("posMode", "")) or "")
    level = str(account.get("account_level", account.get("acctLv", "")) or "")
    if not level or position_mode != "long_short_mode":
        raise OwnedIDRestoreArchiveError("owned_id_restore_account_invalid")
    identifier = str(
        account.get("account_identifier")
        or account.get("account_id")
        or account.get("uid")
        or account.get("acctId")
        or ""
    )
    result: dict[str, Any] = {
        "account_level": level,
        "permissions": permissions,
        "position_mode": position_mode,
        "withdraw_permission_present": False,
    }
    if identifier:
        result["account_identifier"] = identifier
    return result


def _operational_account(account: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(account)
    value.pop("account_identifier", None)
    return value


def _record_id(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = str(row.get(name) or "")
        if value:
            return value
    return ""


def _normalise_order(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise OwnedIDRestoreArchiveError("owned_id_restore_order_identity_invalid")
    _reject_secret_keys(row)
    client_id = _record_id(row, "client_order_id", "clOrdId")
    order_id = _record_id(row, "order_id", "ordId")
    instrument = str(row.get("instrument_id") or row.get("instId") or "")
    state = str(row.get("state") or "")
    if not client_id or not order_id or instrument != OKX_DEMO_INSTRUMENT_ID:
        raise OwnedIDRestoreArchiveError("owned_id_restore_order_identity_invalid")
    if state not in {"filled", "partially_filled"}:
        raise OwnedIDRestoreArchiveError("owned_id_restore_order_state_invalid")
    return {
        "client_order_id": client_id,
        "order_id": order_id,
        "instrument_id": instrument,
        "state": state,
        **{
            key: str(row[key])
            for key in (
                "side",
                "position_side",
                "size",
                "filled_size",
                "average_price",
                "order_type",
            )
            if key in row
        },
    }


def _normalise_fill(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise OwnedIDRestoreArchiveError("owned_id_restore_fill_identity_invalid")
    _reject_secret_keys(row)
    client_id = _record_id(row, "client_order_id", "clOrdId")
    order_id = _record_id(row, "order_id", "ordId")
    fill_id = _record_id(row, "fill_id", "tradeId")
    instrument = str(row.get("instrument_id") or row.get("instId") or "")
    if (
        not client_id
        or not order_id
        or not fill_id
        or instrument != OKX_DEMO_INSTRUMENT_ID
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_fill_identity_invalid")
    return {
        "client_order_id": client_id,
        "order_id": order_id,
        "fill_id": fill_id,
        "instrument_id": instrument,
        **{
            key: str(row[key])
            for key in (
                "size",
                "price",
                "side",
                "position_side",
                "timestamp_ms",
            )
            if key in row
        },
    }


def _order_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for raw in rows:
        row = _normalise_order(raw)
        pair = (row["order_id"], row["instrument_id"])
        if row["client_order_id"] in result:
            raise OwnedIDRestoreArchiveError("owned_id_restore_order_duplicate")
        result[row["client_order_id"]] = pair
    return result


def _fill_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for raw in rows:
        row = _normalise_fill(raw)
        pair = (row["order_id"], row["fill_id"])
        if row["client_order_id"] in result:
            raise OwnedIDRestoreArchiveError("owned_id_restore_fill_duplicate")
        result[row["client_order_id"]] = pair
    return result


def _validate_source_archive(
    source_root: Path,
    *,
    repo_root: Path,
) -> _SourceArchiveFacts:
    root = Path(source_root).resolve()
    repo = Path(repo_root).resolve()
    if not root.is_dir() or root == repo or repo in root.parents:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_root_invalid")
    manifest_path = root / "manifest.json"
    verification_path = root / "verification.json"
    completed_path = root / "COMPLETED.json"
    manifest = _json(manifest_path, "owned_id_restore_source_manifest_invalid")
    verification = _json(verification_path, "owned_id_restore_source_verification_invalid")
    completed = _json(completed_path, "owned_id_restore_source_completed_invalid")
    _reject_secret_keys(manifest)
    _reject_secret_keys(verification)
    _reject_secret_keys(completed)
    archive_id = str(manifest.get("archive_id") or "")
    if not archive_id or any(
        str(document.get("archive_id") or "") not in {"", archive_id}
        for document in (verification, completed)
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_archive_identity_invalid")
    manifest_sha = _sha256_file(manifest_path)
    verification_sha = _sha256_file(verification_path)
    claimed_manifest_hash = str(manifest.get("manifest_hash") or "")
    if claimed_manifest_hash:
        if not LOWER_HEX64_RE.fullmatch(claimed_manifest_hash):
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_hash_invalid")
        manifest_body = dict(manifest)
        manifest_body.pop("manifest_hash", None)
        if _canonical_sha256(manifest_body) != claimed_manifest_hash.lower():
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_hash_invalid")
    if (
        str(completed.get("manifest_sha256") or "") != manifest_sha
        or str(completed.get("verification_sha256") or "") != verification_sha
        or str(manifest.get("verification_sha256") or "") != verification_sha
        or completed.get("immutable_after_write") is not True
        or manifest.get("immutable") is not True
        or manifest.get("unique_directory_no_overwrite") is not True
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_hash_invalid")
    owner = _owner_marker(manifest, archive_root=root, repo_root=repo)
    source_head = _require_hex(
        manifest.get("current_head"),
        HEX40_RE,
        "owned_id_restore_source_head_invalid",
    )
    verification_head = _require_hex(
        verification.get("source_head"),
        HEX40_RE,
        "owned_id_restore_source_head_invalid",
    )
    if source_head != verification_head or not _git_commit_exists(repo, source_head):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_head_invalid")
    if manifest.get("status") not in {"blocked_fail_closed", "verified_fail_closed"}:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_status_invalid")
    if verification.get("status") not in {"blocked_fail_closed", "verified_fail_closed"}:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_status_invalid")
    for document in (manifest, verification):
        safety = document.get("safety")
        if not isinstance(safety, Mapping) or any(value is not False for value in safety.values()):
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_safety_invalid")
    files = manifest.get("files")
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_files_invalid")
    file_hashes: dict[str, str] = {}
    kinds: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_files_invalid")
        relative = str(item.get("archive_relative_path") or "")
        path = _safe_archive_path(root, relative)
        try:
            size_bytes = int(item.get("size_bytes", -1))
        except (TypeError, ValueError) as exc:
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_file_invalid") from exc
        if not path.is_file() or size_bytes != path.stat().st_size:
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_file_invalid")
        digest = _sha256_file(path)
        if digest != str(item.get("sha256") or ""):
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_file_hash_invalid")
        file_hashes[relative] = digest
        kinds.add(str(item.get("kind") or ""))
    required = {
        "runtime_events",
        "runtime_state",
        "receipt_ledger",
    }
    if not required.issubset(kinds):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_files_missing")
    events_path = _safe_archive_path(root, "source_snapshots/runtime_events.jsonl")
    state_path = _safe_archive_path(root, "source_snapshots/runtime_state.json")
    receipt_path = _safe_archive_path(root, "source_snapshots/receipt_ledger.jsonl")
    events, source_state = _validate_event_chain(
        events_path,
        state_path,
        manifest,
        verification,
    )
    exchange = source_state.get("exchange")
    if not isinstance(exchange, Mapping):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_state_invalid")
    if (
        source_state.get("environment") != "OKX Demo"
        or source_state.get("instrument_id") != OKX_DEMO_INSTRUMENT_ID
        or str((source_state.get("limits") or {}).get("margin_mode") or "") != "isolated"
        or not isinstance(exchange.get("positions"), Sequence)
        or isinstance(exchange.get("positions"), (str, bytes))
        or exchange.get("positions")
        or not isinstance(exchange.get("pending_orders"), Sequence)
        or isinstance(exchange.get("pending_orders"), (str, bytes))
        or exchange.get("pending_orders")
        or not isinstance(exchange.get("pending_algo_orders"), Sequence)
        or isinstance(exchange.get("pending_algo_orders"), (str, bytes))
        or exchange.get("pending_algo_orders")
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_state_invalid")
    source_account = _normalise_account(exchange.get("account") or {})
    source_orders_raw = exchange.get("orders")
    source_fills_raw = exchange.get("fills")
    if not isinstance(source_orders_raw, Sequence) or isinstance(source_orders_raw, (str, bytes)):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_state_invalid")
    if not isinstance(source_fills_raw, Sequence) or isinstance(source_fills_raw, (str, bytes)):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_state_invalid")
    source_orders = _order_map(source_orders_raw)
    source_fills = _fill_map(source_fills_raw)
    if set(source_orders) != set(source_fills) or not source_orders:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_exchange_invalid")
    try:
        receipts = load_observation_receipt_ledger(receipt_path)
    except Exception as exc:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_source_receipt_chain_invalid"
        ) from exc
    if len(receipts) != 25:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_receipt_count_invalid")
    receipt_chain = manifest.get("receipt_chain")
    if not isinstance(receipt_chain, Mapping) or receipt_chain.get("hash_chain_valid") is not True:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_receipt_chain_invalid")
    try:
        receipt_count = int(receipt_chain.get("count", -1))
    except (TypeError, ValueError) as exc:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_source_receipt_count_invalid"
        ) from exc
    if receipt_count != 25:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_receipt_count_invalid")
    if str(receipt_chain.get("ledger_file_sha256") or "") != _sha256_file(receipt_path):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_receipt_chain_invalid")
    receipt_file_count = sum(
        1
        for item in files
        if isinstance(item, Mapping) and item.get("kind") == "hourly_observation_receipt"
    )
    if receipt_file_count != 25:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_receipt_count_invalid")
    if len(events) != 198:
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_event_count_invalid")
    _ = source_account
    return _SourceArchiveFacts(
        root=root,
        manifest=manifest,
        verification=verification,
        completed=completed,
        events=events,
        source_state=source_state,
        source_orders=source_orders,
        source_fills=source_fills,
        source_head=source_head,
        manifest_sha256=manifest_sha,
        verification_sha256=verification_sha,
        completed_sha256=_sha256_file(completed_path),
        file_hashes=file_hashes,
        owner_marker=owner,
        receipt_count=len(receipts),
    )


def _validate_provider(provider: DemoPrivateReadSnapshotProvider) -> None:
    capability = getattr(provider, "capability", None)
    if type(capability) is not DemoPrivateReadCapability or capability != DemoPrivateReadCapability():
        raise OwnedIDRestoreArchiveError("owned_id_restore_provider_capability_invalid")
    if not callable(getattr(provider, "read_snapshot", None)):
        raise OwnedIDRestoreArchiveError("owned_id_restore_provider_read_missing")
    if any(callable(getattr(provider, name, None)) for name in DENIED_PROVIDER_MEMBERS):
        raise OwnedIDRestoreArchiveError("owned_id_restore_provider_write_capability_present")


def _normalise_snapshot(raw: DemoPrivateReadSnapshot | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw, DemoPrivateReadSnapshot):
        value = raw.as_mapping()
    elif isinstance(raw, Mapping):
        value = dict(raw)
    else:
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_invalid")
    _reject_secret_keys(value)
    if (
        value.get("environment") != "OKX Demo"
        or value.get("instrument_id") != OKX_DEMO_INSTRUMENT_ID
        or value.get("margin_mode") != "isolated"
        or value.get("fresh") is not True
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_identity_invalid")
    captured = str(value.get("captured_at_utc") or "")
    try:
        datetime.fromisoformat(captured.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_freshness_invalid") from exc
    safety = value.get("safety")
    if safety is not None and (
        not isinstance(safety, Mapping) or any(item is not False for item in safety.values())
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_safety_invalid")
    account = _normalise_account(value.get("account") or {})
    for field_name in ("positions", "pending_orders", "pending_algo_orders"):
        rows = value.get(field_name)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_state_invalid")
        if rows:
            raise OwnedIDRestoreArchiveError(
                "owned_id_restore_private_snapshot_not_flat"
                if field_name == "positions"
                else "owned_id_restore_private_snapshot_pending_state"
            )
    orders = value.get("orders")
    fills = value.get("fills")
    if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes)):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_history_invalid")
    if not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_history_invalid")
    normalised_orders = [_normalise_order(row) for row in orders if isinstance(row, Mapping)]
    normalised_fills = [_normalise_fill(row) for row in fills if isinstance(row, Mapping)]
    if len(normalised_orders) != len(orders) or len(normalised_fills) != len(fills):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_history_invalid")
    return {
        "environment": "OKX Demo",
        "instrument_id": OKX_DEMO_INSTRUMENT_ID,
        "margin_mode": "isolated",
        "account": account,
        "positions": [],
        "pending_orders": [],
        "pending_algo_orders": [],
        "orders": normalised_orders,
        "fills": normalised_fills,
        "captured_at_utc": captured,
        "fresh": True,
    }


def _lifecycle_triples(events: Sequence[Mapping[str, Any]]) -> tuple[
    dict[str, set[tuple[str, str, str]]],
    dict[str, dict[str, Mapping[str, Any]]],
]:
    by_run: dict[str, set[tuple[str, str, str]]] = {}
    event_by_client: dict[str, dict[str, Mapping[str, Any]]] = {}
    for event in events:
        if event.get("event_type") != "order_lifecycle":
            continue
        run_id = str(event.get("run_id") or "")
        if not EXPECTED_RUN_ID_RE.fullmatch(run_id):
            raise OwnedIDRestoreArchiveError("owned_id_restore_run_id_invalid")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_invalid")
        oms = payload.get("oms")
        fills = payload.get("fills")
        if not isinstance(oms, Mapping) or not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_invalid")
        client_id = _record_id(oms, "client_order_id", "clOrdId")
        order_id = _record_id(payload, "exchange_order_id", "order_id", "ordId") or _record_id(oms, "broker_order_id", "order_id")
        matching = [
            row
            for row in fills
            if isinstance(row, Mapping)
            and _record_id(row, "client_order_id", "clOrdId") == client_id
        ]
        if not client_id or not order_id or len(matching) != 1:
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_invalid")
        fill = matching[0]
        fill_id = _record_id(fill, "fill_id", "tradeId")
        if (
            not fill_id
            or str(fill.get("instrument_id") or fill.get("instId") or "") != OKX_DEMO_INSTRUMENT_ID
            or str(payload.get("exchange_state") or "") != "filled"
            or str(oms.get("status") or "") not in {"filled", "reconciled"}
        ):
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_invalid")
        triple = (client_id, order_id, fill_id)
        previous = by_run.setdefault(run_id, set())
        if triple in previous and event_by_client.setdefault(run_id, {}).get(client_id) != event:
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_conflict")
        previous.add(triple)
        event_by_client.setdefault(run_id, {})[client_id] = event
    return by_run, event_by_client


def _ledger_triples(
    events: Sequence[Mapping[str, Any]],
) -> dict[
    str,
    tuple[
        set[tuple[str, str, str]],
        dict[tuple[str, str, str], Mapping[str, Any]],
    ],
]:
    """Validate every committed ledger UOW and collect stable triples.

    The source archive contains one leading, empty exchange snapshot before
    the first order.  That snapshot is accepted only in its exact shape.  All
    later UOWs must carry a non-empty, one-to-one order/fill projection; no
    malformed UOW is silently skipped.
    """

    by_run: dict[
        str,
        tuple[
            set[tuple[str, str, str]],
            dict[tuple[str, str, str], Mapping[str, Any]],
        ],
    ] = {}
    canonical_by_client: dict[tuple[str, str], tuple[str, str]] = {}
    seen_nonempty_by_run: set[str] = set()
    seen_empty_by_run: set[str] = set()

    for event in events:
        if event.get("event_type") != "ledger_uow_committed":
            continue
        run_id = str(event.get("run_id") or "")
        if not EXPECTED_RUN_ID_RE.fullmatch(run_id):
            raise OwnedIDRestoreArchiveError("owned_id_restore_run_id_invalid")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_uow_invalid")
        if "order_ledger" not in payload or "fill_ledger" not in payload:
            raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_uow_invalid")

        order_ledger = payload.get("order_ledger")
        fills = payload.get("fill_ledger")
        if not isinstance(order_ledger, Mapping):
            raise OwnedIDRestoreArchiveError("owned_id_restore_order_ledger_invalid")
        if not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
            raise OwnedIDRestoreArchiveError("owned_id_restore_fill_ledger_invalid")
        record_type = order_ledger.get("record_type")
        terminal_order = order_ledger.get("terminal_order")
        pending_orders = order_ledger.get("pending_orders")
        pending_algo_orders = order_ledger.get("pending_algo_orders")
        if (
            not isinstance(record_type, str)
            or not record_type
            or not isinstance(terminal_order, Mapping)
            or not isinstance(pending_orders, Sequence)
            or isinstance(pending_orders, (str, bytes))
            or not isinstance(pending_algo_orders, Sequence)
            or isinstance(pending_algo_orders, (str, bytes))
        ):
            raise OwnedIDRestoreArchiveError("owned_id_restore_order_ledger_invalid")

        orders = order_ledger.get("orders")
        if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes)):
            raise OwnedIDRestoreArchiveError("owned_id_restore_orders_invalid")
        if not orders and not fills:
            if (
                record_type != "exchange_order_snapshot"
                or run_id in seen_empty_by_run
                or run_id in seen_nonempty_by_run
            ):
                raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_uow_empty")
            seen_empty_by_run.add(run_id)
            continue
        if not orders or not fills:
            raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_uow_partial")
        seen_nonempty_by_run.add(run_id)

        orders_by_client: dict[str, str] = {}
        order_ids: set[str] = set()
        for raw_order in orders:
            if not isinstance(raw_order, Mapping):
                raise OwnedIDRestoreArchiveError("owned_id_restore_order_ledger_row_invalid")
            order = _normalise_order(raw_order)
            client_id = order["client_order_id"]
            order_id = order["order_id"]
            if client_id in orders_by_client or order_id in order_ids:
                raise OwnedIDRestoreArchiveError("owned_id_restore_order_ledger_duplicate")
            orders_by_client[client_id] = order_id
            order_ids.add(order_id)

        fills_by_client: dict[str, tuple[str, str]] = {}
        fill_ids: set[str] = set()
        for raw_fill in fills:
            if not isinstance(raw_fill, Mapping):
                raise OwnedIDRestoreArchiveError("owned_id_restore_fill_ledger_row_invalid")
            fill = _normalise_fill(raw_fill)
            client_id = fill["client_order_id"]
            order_id = fill["order_id"]
            fill_id = fill["fill_id"]
            if client_id in fills_by_client or fill_id in fill_ids:
                raise OwnedIDRestoreArchiveError("owned_id_restore_fill_ledger_duplicate")
            fills_by_client[client_id] = (order_id, fill_id)
            fill_ids.add(fill_id)

        if set(orders_by_client) != set(fills_by_client):
            raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_client_set_mismatch")
        triples, event_by_triple = by_run.setdefault(run_id, (set(), {}))
        for client_id, order_id in orders_by_client.items():
            fill_order_id, fill_id = fills_by_client[client_id]
            if fill_order_id != order_id:
                raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_order_mapping_conflict")
            key = (run_id, client_id)
            canonical = canonical_by_client.get(key)
            if canonical is not None and canonical != (order_id, fill_id):
                raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_history_conflict")
            canonical_by_client[key] = (order_id, fill_id)
            triple = (client_id, order_id, fill_id)
            triples.add(triple)
            event_by_triple.setdefault(triple, event)
    return by_run


def _ordered_source_triples(
    triples: Sequence[tuple[str, str, str]] | set[tuple[str, str, str]],
    lifecycle_events: Mapping[str, Mapping[str, Mapping[str, Any]]],
    run_id: str,
) -> tuple[tuple[str, str, str], ...]:
    """Order selected identities by the authoritative lifecycle sequence.

    Client/order/fill identifiers are opaque identities.  Their lexical order
    is not an execution ordering and must never become the restore ordering.
    """

    if not triples or run_id not in lifecycle_events:
        raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_order_invalid")
    by_client: dict[str, tuple[str, str, str]] = {}
    by_sequence: dict[int, tuple[str, str, str]] = {}
    for triple in triples:
        if len(triple) != 3 or any(not str(value) for value in triple):
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_order_invalid")
        client_id = str(triple[0])
        if client_id in by_client:
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_order_invalid")
        event = lifecycle_events[run_id].get(client_id)
        if not isinstance(event, Mapping) or type(event.get("sequence")) is not int:
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_order_invalid")
        sequence = int(event["sequence"])
        if sequence < 1 or sequence in by_sequence:
            raise OwnedIDRestoreArchiveError("owned_id_restore_lifecycle_order_invalid")
        value = (str(triple[0]), str(triple[1]), str(triple[2]))
        by_client[client_id] = value
        by_sequence[sequence] = value
    return tuple(by_sequence[key] for key in sorted(by_sequence))


def _select_source_run(
    facts: _SourceArchiveFacts,
) -> tuple[str, str, tuple[dict[str, str], ...], tuple[Mapping[str, Any], ...]]:
    """Select and validate the unique owned run using archive facts only."""

    lifecycle_by_run, lifecycle_events = _lifecycle_triples(facts.events)
    ledger_by_run = _ledger_triples(facts.events)
    source_triples = {
        (client_id, order_id, fill_id)
        for client_id, (order_id, _) in facts.source_orders.items()
        if client_id in facts.source_fills
        for fill_order_id, fill_id in (facts.source_fills[client_id],)
        if fill_order_id == order_id
    }
    complete: list[tuple[str, set[tuple[str, str, str]]]] = []
    for run_id, lifecycle in lifecycle_by_run.items():
        ledger = ledger_by_run.get(run_id, (set(), {}))[0]
        intersection = lifecycle & ledger & source_triples
        if intersection == lifecycle == ledger == source_triples and intersection:
            complete.append((run_id, intersection))
    if len(complete) != 1:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_run_selection_none_or_ambiguous"
        )
    run_id, triples = complete[0]
    namespace = f"btcDP{run_id[:8]}"
    for client_id, _, _ in triples:
        if not client_id.startswith(namespace):
            raise OwnedIDRestoreArchiveError("owned_id_restore_namespace_invalid")
    selected_events: dict[int, Mapping[str, Any]] = {}
    for client_id, event in lifecycle_events[run_id].items():
        if any(triple[0] == client_id for triple in triples):
            selected_events[int(event.get("sequence", -1))] = event
    ledger_events = ledger_by_run[run_id][1]
    for triple in triples:
        event = ledger_events.get(triple)
        if event is None:
            raise OwnedIDRestoreArchiveError("owned_id_restore_ledger_intersection_invalid")
        selected_events[int(event.get("sequence", -1))] = event
    if len(selected_events) < 3:
        raise OwnedIDRestoreArchiveError("owned_id_restore_selected_events_invalid")
    ordered_triples = _ordered_source_triples(triples, lifecycle_events, run_id)
    rows = tuple(
        {
            "client_order_id": client_id,
            "order_id": order_id,
            "fill_id": fill_id,
            "run_id": run_id,
        }
        for client_id, order_id, fill_id in ordered_triples
    )
    return run_id, namespace, rows, tuple(selected_events[key] for key in sorted(selected_events))


def _validate_snapshot_history(
    snapshot: Mapping[str, Any],
    triples: Sequence[Mapping[str, Any]],
) -> None:
    """Cross-check current private history as a non-empty source suffix.

    OKX history can retain all order rows while fills have aged out.  The
    current complete identities therefore must be a contiguous, non-empty
    suffix of the source lifecycle order; arbitrary subsets are not ownership
    evidence.
    """

    current_orders = _order_map(snapshot["orders"])
    current_fills = _fill_map(snapshot["fills"])
    source_ordered = tuple(
        (
            str(row.get("client_order_id") or ""),
            str(row.get("order_id") or ""),
            str(row.get("fill_id") or ""),
        )
        for row in triples
    )
    if (
        not source_ordered
        or any(any(not value for value in triple) for triple in source_ordered)
        or len(set(source_ordered)) != len(source_ordered)
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_history_mismatch")
    source_by_client = {triple[0]: triple for triple in source_ordered}
    source_clients = set(source_by_client)
    current_order_clients = set(current_orders)
    current_fill_clients = set(current_fills)
    if (
        not current_order_clients
        or not current_fill_clients
        or not current_order_clients.issubset(source_clients)
        or not current_fill_clients.issubset(source_clients)
        or not current_fill_clients.issubset(current_order_clients)
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_history_mismatch")
    for client_id, (order_id, instrument_id) in current_orders.items():
        expected = source_by_client[client_id]
        if (order_id, instrument_id) != (expected[1], OKX_DEMO_INSTRUMENT_ID):
            raise OwnedIDRestoreArchiveError("owned_id_restore_private_history_mismatch")
    for client_id, (order_id, fill_id) in current_fills.items():
        expected = source_by_client[client_id]
        if (order_id, fill_id) != (expected[1], expected[2]):
            raise OwnedIDRestoreArchiveError("owned_id_restore_private_history_mismatch")

    current_complete = tuple(
        source_by_client[client_id]
        for client_id in (triple[0] for triple in source_ordered)
        if client_id in current_fill_clients
    )
    if not current_complete:
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_history_mismatch")
    if not any(
        current_complete == source_ordered[index:]
        for index in range(len(source_ordered))
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_history_mismatch")


def _source_exchange_projection(
    facts: _SourceArchiveFacts,
    triples: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the full selected-run source rows for derived runtime state."""

    exchange = facts.source_state.get("exchange")
    if not isinstance(exchange, Mapping):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_exchange_invalid")
    raw_orders = exchange.get("orders")
    raw_fills = exchange.get("fills")
    if (
        not isinstance(raw_orders, Sequence)
        or isinstance(raw_orders, (str, bytes))
        or not isinstance(raw_fills, Sequence)
        or isinstance(raw_fills, (str, bytes))
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_exchange_invalid")
    order_rows: dict[str, dict[str, Any]] = {}
    fill_rows: dict[str, dict[str, Any]] = {}
    for raw in raw_orders:
        row = _normalise_order(raw)
        if row["client_order_id"] in order_rows:
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_exchange_invalid")
        order_rows[row["client_order_id"]] = dict(raw)
    for raw in raw_fills:
        row = _normalise_fill(raw)
        if row["client_order_id"] in fill_rows:
            raise OwnedIDRestoreArchiveError("owned_id_restore_source_exchange_invalid")
        fill_rows[row["client_order_id"]] = dict(raw)
    selected_clients = [str(row.get("client_order_id") or "") for row in triples]
    if (
        not selected_clients
        or set(selected_clients) != set(facts.source_orders)
        or set(selected_clients) != set(facts.source_fills)
        or set(order_rows) != set(selected_clients)
        or set(fill_rows) != set(selected_clients)
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_source_exchange_invalid")
    return (
        [order_rows[client_id] for client_id in selected_clients],
        [fill_rows[client_id] for client_id in selected_clients],
    )


def _select_run(
    facts: _SourceArchiveFacts,
    snapshot: Mapping[str, Any],
) -> tuple[str, str, tuple[dict[str, str], ...], tuple[Mapping[str, Any], ...]]:
    """Compatibility wrapper retaining the pre-provider source selection API."""

    run_id, namespace, triples, selected_events = _select_source_run(facts)
    _validate_snapshot_history(snapshot, triples)
    return run_id, namespace, triples, selected_events


def _rebuild_event_chain(events: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    lines: list[str] = []
    previous = ""
    for sequence, source in enumerate(events, start=1):
        body = dict(source)
        body.pop("event_hash", None)
        body.pop("semantic_hash", None)
        body["sequence"] = sequence
        body["previous_event_hash"] = previous
        body["semantic_hash"] = _canonical_sha256(
            {
                "event_type": body.get("event_type"),
                "payload": body.get("payload"),
                "run_id": body.get("run_id"),
            }
        )
        # The source contract hashes the semantic hash as part of the event
        # body; calculate event_hash only after semantic_hash is present.
        body["event_hash"] = _canonical_sha256(body)
        previous = body["event_hash"]
        lines.append(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return tuple(lines)


def _rebuild_checkpoint(state: Mapping[str, Any], event_lines: Sequence[str]) -> dict[str, Any]:
    last_event_hash = ""
    if event_lines:
        last_event_hash = str(json.loads(event_lines[-1]).get("event_hash") or "")
    body = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "last_sequence": len(event_lines),
        "last_event_hash": last_event_hash,
        "state": dict(state),
    }
    return {**body, "checkpoint_hash": _canonical_sha256(body)}


def _safe_safety() -> dict[str, bool]:
    return {
        "live_allowed": False,
        "network_used": False,
        "order_endpoint_allowed": False,
        "paper_allowed": False,
        "private_endpoint_allowed": False,
        "promotion_allowed": False,
        "runtime_latest_pointer_updated": False,
        "secret_read": False,
        "source_deleted_or_moved": False,
        "transfer_allowed": False,
        "withdraw_allowed": False,
        "real_order_submitted": False,
    }


def _validate_credential_identity(value: str) -> str:
    identity = str(value or "")
    if (
        not re.fullmatch(r"quant-system\.okx-demo\.[A-Za-z0-9_.:-]{1,127}", identity)
        or any(token in identity.lower() for token in ("secret", "passphrase", "token", "api_key"))
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_credential_identity_invalid")
    return identity


def _build_files(root: Path, entries: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for relative, kind in entries:
        path = _safe_archive_path(root, relative)
        if not path.is_file():
            raise OwnedIDRestoreArchiveError("owned_id_restore_output_file_missing")
        result.append(
            {
                "archive_relative_path": relative,
                "kind": kind,
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return result


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_bytes(value))


def _publish_directory(temp_root: Path, output_root: Path) -> None:
    try:
        os.rename(str(temp_root), str(output_root))
    except (OSError, ValueError) as exc:
        raise OwnedIDRestoreArchiveError("owned_id_restore_atomic_publish_failed") from exc


def publish_owned_id_restore_archive(
    *,
    source_archive_root: Path,
    output_root: Path,
    repo_root: Path,
    provider: DemoPrivateReadSnapshotProvider,
    credential_identity: str,
    expected_current_head: str | None = None,
    archive_id: str | None = None,
) -> dict[str, Any]:
    """Validate, select, and atomically publish one identity-bound archive."""

    repo = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    if output == repo or repo in output.parents:
        raise OwnedIDRestoreArchiveError("owned_id_restore_output_root_repo_local")
    if not output.name or not SAFE_ID_RE.fullmatch(output.name):
        raise OwnedIDRestoreArchiveError("owned_id_restore_output_archive_id_invalid")
    selected_archive_id = archive_id or output.name
    if not SAFE_ID_RE.fullmatch(str(selected_archive_id)):
        raise OwnedIDRestoreArchiveError("owned_id_restore_output_archive_id_invalid")
    if output.exists():
        raise OwnedIDRestoreArchiveError("owned_id_restore_output_exists")
    current_head = _repo_head(repo)
    if expected_current_head is not None and str(expected_current_head) != current_head:
        raise OwnedIDRestoreArchiveError("owned_id_restore_current_head_mismatch")
    credential = _validate_credential_identity(credential_identity)
    _validate_provider(provider)
    source_root = Path(source_archive_root).resolve()
    if output == source_root or source_root in output.parents:
        raise OwnedIDRestoreArchiveError("owned_id_restore_output_source_archive_local")
    facts = _validate_source_archive(source_archive_root, repo_root=repo)
    # Complete archive/lifecycle/ledger selection must finish before any
    # private GET.  A valid-looking current account cannot rescue a malformed
    # immutable source archive.
    run_id, namespace, triples, selected_events = _select_source_run(facts)
    try:
        raw_snapshot = provider.read_snapshot()
    except OwnedIDRestoreArchiveError:
        raise
    except Exception as exc:
        raise OwnedIDRestoreArchiveError("owned_id_restore_private_snapshot_failed") from exc
    snapshot = _normalise_snapshot(raw_snapshot)
    source_account = _normalise_account((facts.source_state.get("exchange") or {}).get("account") or {})
    source_account_id = str(source_account.get("account_identifier") or "")
    snapshot_account_id = str(snapshot["account"].get("account_identifier") or "")
    if (
        _operational_account(source_account) != _operational_account(snapshot["account"])
        or (source_account_id and snapshot_account_id and source_account_id != snapshot_account_id)
    ):
        raise OwnedIDRestoreArchiveError("owned_id_restore_account_identity_mismatch")
    if not snapshot_account_id:
        raise OwnedIDRestoreArchiveError("owned_id_restore_account_identity_missing")
    account_identity = hashlib.sha256(snapshot_account_id.encode("utf-8")).hexdigest()
    _validate_snapshot_history(snapshot, triples)
    source_orders_projection, source_fills_projection = _source_exchange_projection(
        facts,
        triples,
    )
    event_lines = _rebuild_event_chain(selected_events)
    state_exchange = {
        "account": _operational_account(snapshot["account"]),
        "orders": source_orders_projection,
        "fills": source_fills_projection,
        "positions": [],
        "pending_orders": [],
        "pending_algo_orders": [],
    }
    state = {
        "schema_version": PUBLISHER_SCHEMA_VERSION,
        "environment": "OKX Demo",
        "instrument_id": OKX_DEMO_INSTRUMENT_ID,
        "limits": {"margin_mode": "isolated"},
        "exchange": state_exchange,
        "runtime": {
            "run_id": run_id,
            "opening_allowed": False,
            "position_restored": False,
            "order_capability_restored": False,
            "paper_unlock": False,
            "promotion_unlock": False,
            "live_unlock": False,
        },
        "safety": _safe_safety(),
        "ledger_reconciliation": {
            "status": "reconciled",
            "final_flat": True,
            "pending_order_count": 0,
            "pending_algo_order_count": 0,
            "selected_triple_count": len(triples),
        },
    }
    checkpoint = _rebuild_checkpoint(state, event_lines)
    current_readback = {
        "schema_version": PUBLISHER_SCHEMA_VERSION,
        "environment": snapshot["environment"],
        "instrument_id": snapshot["instrument_id"],
        "margin_mode": snapshot["margin_mode"],
        "account": _operational_account(snapshot["account"]),
        "account_identity": account_identity,
        "credential_identity": credential,
        "positions": [],
        "pending_orders": [],
        "pending_algo_orders": [],
        "orders": snapshot["orders"],
        "fills": snapshot["fills"],
        "captured_at_utc": snapshot["captured_at_utc"],
        "fresh": True,
    }
    current_readback_sha = _canonical_sha256(current_readback)
    receipt_body = {
        "schema_version": DERIVED_RECEIPT_SCHEMA_VERSION,
        "receipt_kind": "identity_bound_owned_id_restore",
        "source_archive_id": str(facts.manifest.get("archive_id") or ""),
        "source_archive_manifest_sha256": facts.manifest_sha256,
        "source_archive_verification_sha256": facts.verification_sha256,
        "source_archive_head": facts.source_head,
        "current_head": current_head,
        "selected_run_id": run_id,
        "client_order_namespace": namespace,
        "account_identity": account_identity,
        "credential_identity": credential,
        "current_private_readback_sha256": current_readback_sha,
        "selected_triple_count": len(triples),
        "counts_toward_25_hour_window": False,
        "promotion_evidence_ready": False,
        "previous_receipt_sha256": None,
        "safety": _safe_safety(),
    }
    receipt = {**receipt_body, "receipt_sha256": _canonical_sha256(receipt_body)}
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = parent / f".{selected_archive_id}.publish.lock"
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        raise OwnedIDRestoreArchiveError("owned_id_restore_publish_lock_unavailable") from exc
    temp_root: Path | None = None
    published = False
    try:
        temp_root = Path(
            tempfile.mkdtemp(prefix=f".{selected_archive_id}.tmp-", dir=str(parent))
        )
        os.write(lock_fd, b"btc_owned_id_restore_archive_publisher_v1\n")
        os.close(lock_fd)
        (temp_root / "source_snapshots").mkdir()
        (temp_root / "receipts").mkdir()
        events_path = temp_root / "source_snapshots/runtime_events.jsonl"
        events_path.write_text("\n".join(event_lines) + "\n", encoding="utf-8")
        _write_json(temp_root / "source_snapshots/runtime_state.json", checkpoint)
        (temp_root / "source_snapshots/receipt_ledger.jsonl").write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        _write_json(temp_root / "source_snapshots/current_private_readback.json", current_readback)
        receipt_path = temp_root / ("receipts/0001-" + receipt["receipt_sha256"] + ".json")
        _write_json(receipt_path, receipt)
        event_hash = _sha256_file(events_path)
        state_hash = _sha256_file(temp_root / "source_snapshots/runtime_state.json")
        receipt_ledger_hash = _sha256_file(temp_root / "source_snapshots/receipt_ledger.jsonl")
        current_readback_file_hash = _sha256_file(temp_root / "source_snapshots/current_private_readback.json")
        verification = {
            "schema_version": PUBLISHER_SCHEMA_VERSION,
            "archive_id": selected_archive_id,
            "source_archive_id": str(facts.manifest.get("archive_id") or ""),
            "status": "verified_fail_closed",
            "decision": "owned_id_restore_admission_only",
            "source_head": current_head,
            "source_archive_head": facts.source_head,
            "current_head": current_head,
            "owner_marker_sha256": facts.owner_marker["sha256"],
            "execution_identity": {
                "account_identity": account_identity,
                "credential_identity": credential,
            },
            "client_order_namespace": namespace,
            "selected_run_id": run_id,
            "selected_triples": list(triples),
            "source_archive_hashes": {
                "manifest_sha256": facts.manifest_sha256,
                "verification_sha256": facts.verification_sha256,
                "completed_sha256": facts.completed_sha256,
                "runtime_events_sha256": facts.file_hashes["source_snapshots/runtime_events.jsonl"],
                "runtime_state_sha256": facts.file_hashes["source_snapshots/runtime_state.json"],
                "receipt_ledger_sha256": facts.file_hashes["source_snapshots/receipt_ledger.jsonl"],
            },
            "derived_files": {
                "runtime_events_sha256": event_hash,
                "runtime_state_sha256": state_hash,
                "receipt_ledger_sha256": receipt_ledger_hash,
                "current_private_readback_sha256": current_readback_file_hash,
            },
            "event_identity": {
                "event_count": len(event_lines),
                "last_sequence": len(event_lines),
                "last_event_hash": str(json.loads(event_lines[-1]).get("event_hash") or ""),
                "file_sha256": event_hash,
                "hash_chain_valid": True,
            },
            "receipt_identity": {
                "count": 1,
                "last_receipt_sha256": receipt["receipt_sha256"],
                "hash_chain_valid": True,
                "file_sha256": receipt_ledger_hash,
            },
            "safety": _safe_safety(),
            "promotion_evidence_ready": False,
            "identity_only": True,
        }
        _write_json(temp_root / "verification.json", verification)
        verification_sha = _sha256_file(temp_root / "verification.json")
        file_entries = _build_files(
            temp_root,
            (
                ("source_snapshots/runtime_events.jsonl", "runtime_events"),
                ("source_snapshots/runtime_state.json", "runtime_state"),
                ("source_snapshots/receipt_ledger.jsonl", "receipt_ledger"),
                ("source_snapshots/current_private_readback.json", "current_private_readback"),
                ("receipts/0001-" + receipt["receipt_sha256"] + ".json", "derived_restore_receipt"),
                ("verification.json", "verification"),
            ),
        )
        manifest = {
            "schema_version": PUBLISHER_SCHEMA_VERSION,
            "archive_id": selected_archive_id,
            "source_archive_id": str(facts.manifest.get("archive_id") or ""),
            "source_archive_manifest_sha256": facts.manifest_sha256,
            "source_archive_verification_sha256": facts.verification_sha256,
            "source_archive_completed_sha256": facts.completed_sha256,
            "source_archive_head": facts.source_head,
            "current_head": current_head,
            "status": "verified_fail_closed",
            "decision": "owned_id_restore_admission_only",
            "immutable": True,
            "unique_directory_no_overwrite": True,
            "owner_marker": facts.owner_marker,
            "verification_sha256": verification_sha,
            "execution_identity": {
                "account_identity": account_identity,
                "credential_identity": credential,
            },
            "selected_run_id": run_id,
            "client_order_namespace": namespace,
            "owned_triples": list(triples),
            "source_snapshot_hashes": {
                "runtime_events": facts.file_hashes["source_snapshots/runtime_events.jsonl"],
                "runtime_state": facts.file_hashes["source_snapshots/runtime_state.json"],
                "receipt_ledger": facts.file_hashes["source_snapshots/receipt_ledger.jsonl"],
            },
            "current_private_readback_sha256": current_readback_sha,
            "files": file_entries,
            "event_chain": verification["event_identity"],
            "receipt_chain": verification["receipt_identity"],
            "safety": _safe_safety(),
            "identity_only": True,
            "opening_allowed": False,
            "position_restored": False,
            "order_capability_restored": False,
            "paper_unlock": False,
            "promotion_unlock": False,
            "live_unlock": False,
            "promotion_evidence_ready": False,
            "quality_checked": True,
            "research_ready": False,
            "backtest_ready": False,
            "blockers": [
                "source_archive_promotion_blocked_preserved",
                "identity_bound_owned_id_restore_admission_only",
                "not_25_hour_promotion_evidence",
            ],
            "archive_write_policy": {
                "single_writer_lock": True,
                "atomic_directory_rename": True,
                "overwrite_forbidden": True,
                "source_archive_unchanged": True,
            },
            "manifest_hash": "",
        }
        manifest["manifest_hash"] = _canonical_sha256(
            {key: value for key, value in manifest.items() if key != "manifest_hash"}
        )
        _write_json(temp_root / "manifest.json", manifest)
        manifest_sha = _sha256_file(temp_root / "manifest.json")
        _write_json(
            temp_root / "COMPLETED.json",
            {
                "schema_version": "btc_owned_id_restore_archive_completion_v1",
                "archive_id": selected_archive_id,
                "manifest_sha256": manifest_sha,
                "verification_sha256": verification_sha,
                "immutable_after_write": True,
            },
        )
        if output.exists():
            raise OwnedIDRestoreArchiveError("owned_id_restore_output_exists")
        _publish_directory(temp_root, output)
        published = True
    finally:
        if lock_fd:
            try:
                os.close(lock_fd)
            except OSError:
                pass
        if not published and temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return {
        "status": "published",
        "archive_id": selected_archive_id,
        "output_root": str(output),
        "current_head": current_head,
        "source_archive_head": facts.source_head,
        "selected_run_id": run_id,
        "client_order_namespace": namespace,
        "account_identity": account_identity,
        "credential_identity": credential,
        "owned_triples": list(triples),
        "identity_only": True,
        "opening_allowed": False,
        "position_restored": False,
        "order_capability_restored": False,
        "paper_unlock": False,
        "promotion_unlock": False,
        "live_unlock": False,
    }


def build_okx_demo_private_read_provider(
    *,
    credentials: OkxDemoCredentials,
    credential_identity: str,
    base_url: str = "https://www.okx.com",
) -> OkxDemoPrivateReadSnapshotProvider:
    """Build the existing adapter's private-GET-only composition slot."""

    _validate_credential_identity(credential_identity)
    try:
        client = OkxDemoReadOnlyClient(
            config=OkxDemoClientConfig(
                base_url=base_url,
                credential_service=credential_identity,
                allow_private_read=True,
                allow_demo_orders=False,
                allow_demo_cancels=False,
            ),
            credentials=credentials,
        )
    except (OkxDemoSafetyError, TypeError, ValueError) as exc:
        raise OwnedIDRestoreArchiveError(
            "owned_id_restore_private_read_provider_unavailable"
        ) from exc
    return OkxDemoPrivateReadSnapshotProvider(client)


__all__ = [
    "DemoPrivateReadCapability",
    "DemoPrivateReadSnapshot",
    "DemoPrivateReadSnapshotProvider",
    "OkxDemoPrivateReadSnapshotProvider",
    "OwnedIDRestoreArchiveError",
    "build_okx_demo_private_read_provider",
    "publish_owned_id_restore_archive",
]
