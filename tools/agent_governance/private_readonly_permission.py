from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "btc_private_readonly_permission_receipt_v1"
PURPOSE_SCHEMA_VERSION = "btc_private_readonly_permission_receipt_v2"
OBSERVATION_PURPOSE = "btc_demo_observation"
ACCOUNT_FACTS_PURPOSE = "okx_demo_account_facts_once"
ACCOUNT_FACTS_RUNNER_PATH = "scripts/run_btc_account_facts_readonly.py"
LEASE_SCHEMA_VERSION = "btc_private_readonly_permission_lease_v1"
ARM_SCHEMA_VERSION = "btc_private_readonly_permission_arm_v1"
BINDING_CLAIM_SCHEMA_VERSION = "btc_private_readonly_binding_claim_v1"
RUNNER_START_SCHEMA_VERSION = "btc_private_readonly_runner_start_v1"
RUNNER_LAUNCH_SCHEMA_VERSION = "btc_private_readonly_runner_launch_v2"
RUNNER_PATH = "scripts/run_btc_demo_private_readonly_observation.py"
CANONICAL_RUNNER_COMMAND = f"py -3 {RUNNER_PATH}"
PURPOSE_RUNNERS = {
    OBSERVATION_PURPOSE: RUNNER_PATH,
    ACCOUNT_FACTS_PURPOSE: ACCOUNT_FACTS_RUNNER_PATH,
}
DEFAULT_CREDENTIAL_SERVICE = "quant-system.okx-demo.readonly"
CONFIRMATION = "BTC DEMO PRIVATE READONLY"
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 900
SIGNATURE_NAMESPACE = "quant-btc-private-readonly-v1"
SIGNER_PRINCIPAL = "btc-private-readonly-operator"
ALLOWED_SIGNERS_PATH = ".codex/hooks/private_readonly_operator_allowed_signers"
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RECEIPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
HEAD_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
SHELL_META_PATTERN = re.compile(r"[;&|><`\r\n]|\$\(")

PERMISSIONS = {
    "live": False,
    "order": False,
    "paper": False,
    "private": True,
    "promotion": False,
    "real_order": False,
    "transfer": False,
    "withdraw": False,
}

RECEIPT_FIELDS = {
    "schema_version",
    "receipt_id",
    "target_session_id",
    "source_head",
    "runner_path",
    "runner_git_blob",
    "runner_sha256",
    "issued_at",
    "expires_at",
    "ttl_seconds",
    "issuer_channel",
    "credential_storage",
    "permissions",
    "receipt_sha256",
}


class PermissionErrorCode(RuntimeError):
    pass


@dataclass(frozen=True)
class ReceiptReference:
    receipt_id: str
    path: Path
    source_head: str
    runner_git_blob: str
    runner_sha256: str
    expires_at: str
    signature_path: Path
    purpose: str = OBSERVATION_PURPOSE
    runner_path: str = RUNNER_PATH


@dataclass(frozen=True)
class CapabilityResult:
    granted: bool
    reason: str
    receipt_id: str = ""
    source_head: str = ""
    runner_git_blob: str = ""
    runner_sha256: str = ""
    expires_at: str = ""
    armed: bool = False
    purpose: str = OBSERVATION_PURPOSE
    runner_path: str = RUNNER_PATH


@dataclass(frozen=True)
class RunnerAuthorization:
    allowed: bool
    reason: str
    receipt_id: str = ""


@dataclass(frozen=True)
class RunnerProcessAuthorization:
    allowed: bool
    reason: str
    receipt_id: str = ""
    source_head: str = ""
    runner_git_blob: str = ""
    runner_sha256: str = ""
    runtime_root: Path | None = None
    run_id: str = ""
    confirmation: str = ""
    authorization_ticket_hash: str = ""
    purpose: str = OBSERVATION_PURPOSE
    runner_path: str = RUNNER_PATH


@dataclass(frozen=True)
class SignatureVerification:
    verified: bool
    reason: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_capability_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise PermissionErrorCode("private_readonly_local_app_data_unavailable")
    return Path(local_app_data) / "QuantSystem" / "private-readonly-permission-v1"


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def receipt_digest(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _session_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise PermissionErrorCode("private_readonly_git_identity_unavailable")
    return result.stdout.strip()


def _purpose_runner(purpose: str) -> str:
    if not isinstance(purpose, str) or purpose not in PURPOSE_RUNNERS:
        raise PermissionErrorCode("private_readonly_purpose_invalid")
    return PURPOSE_RUNNERS[purpose]


def _scope_fields(capability: CapabilityResult) -> dict[str, str]:
    # Preserve legacy claim bytes. New-purpose claims explicitly bind scope.
    if capability.purpose == OBSERVATION_PURPOSE:
        return {}
    return {"purpose": capability.purpose, "runner_path": capability.runner_path}


def _runner_command(capability: CapabilityResult) -> str:
    runner = _purpose_runner(capability.purpose)
    if capability.runner_path != runner:
        raise PermissionErrorCode("private_readonly_runner_path_mismatch")
    return f"py -3 {runner}"


def _identity_for_purpose(repo_root: Path, purpose: str) -> tuple[str, str, str]:
    runner = _purpose_runner(purpose)
    if purpose == OBSERVATION_PURPOSE:
        return _current_identity(repo_root)
    return _current_identity(repo_root, runner_path=runner)


def _current_identity(repo_root: Path, *, runner_path: str = RUNNER_PATH) -> tuple[str, str, str]:
    if runner_path not in PURPOSE_RUNNERS.values():
        raise PermissionErrorCode("private_readonly_runner_path_mismatch")
    source_head = _git(repo_root, "rev-parse", "refs/heads/main")
    runner_blob = _git(
        repo_root,
        "rev-parse",
        f"refs/heads/main:{runner_path}",
    )
    runner_file = (repo_root / runner_path).resolve()
    if not runner_file.is_file():
        raise PermissionErrorCode("private_readonly_runner_missing")
    try:
        worktree_check = subprocess.run(
            ["git", "diff", "--quiet", source_head, "--", runner_path],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise PermissionErrorCode("private_readonly_runner_identity_unavailable") from exc
    if worktree_check.returncode != 0:
        raise PermissionErrorCode("private_readonly_runner_worktree_mismatch")
    runner_sha256 = hashlib.sha256(runner_file.read_bytes()).hexdigest()
    return source_head, runner_blob, runner_sha256


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PermissionErrorCode("private_readonly_receipt_time_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PermissionErrorCode("private_readonly_receipt_time_invalid") from exc
    return parsed.astimezone(timezone.utc)


def _atomic_json(path: Path, payload: dict[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
                handle.write("\n")
            os.link(temporary, path)
        except Exception:
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _atomic_bytes(path: Path, payload: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)


def _audit_event(root: Path, event: str, payload: dict[str, Any], now: datetime) -> None:
    event_payload = {
        "schema_version": "btc_private_readonly_permission_event_v1",
        "event": event,
        "event_id": uuid.uuid4().hex,
        "observed_at": _iso(now),
        **payload,
    }
    filename = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{event_payload['event_id']}.json"
    _atomic_json(root / "events" / filename, event_payload, exclusive=True)


def build_unsigned_receipt(
    *,
    repo_root: Path,
    target_session_id: str,
    ttl_seconds: int,
    now: datetime | None = None,
    purpose: str = OBSERVATION_PURPOSE,
) -> dict[str, Any]:
    now = now or utc_now()
    if not SESSION_PATTERN.fullmatch(target_session_id):
        raise PermissionErrorCode("private_readonly_target_session_id_invalid")
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise PermissionErrorCode("private_readonly_ttl_out_of_range")
    runner_path = _purpose_runner(purpose)
    source_head, runner_blob, runner_sha256 = _identity_for_purpose(repo_root, purpose)
    receipt_id = uuid.uuid4().hex
    expires_at = now + timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION if purpose == OBSERVATION_PURPOSE else PURPOSE_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "target_session_id": target_session_id,
        "source_head": source_head,
        "runner_path": runner_path,
        "runner_git_blob": runner_blob,
        "runner_sha256": runner_sha256,
        "issued_at": _iso(now),
        "expires_at": _iso(expires_at),
        "ttl_seconds": ttl_seconds,
        "issuer_channel": "human_local_terminal_outside_codex",
        "credential_storage": "windows_keyring_only",
        "permissions": dict(PERMISSIONS),
    }
    if purpose != OBSERVATION_PURPOSE:
        payload["purpose"] = purpose
    payload["receipt_sha256"] = receipt_digest(payload)
    return payload


def verify_external_signature(
    payload: dict[str, Any],
    signature: bytes,
    *,
    repo_root: Path,
) -> SignatureVerification:
    source_head = str(payload.get("source_head", ""))
    if not HEAD_PATTERN.fullmatch(source_head):
        return SignatureVerification(False, "private_readonly_signature_source_head_invalid")
    if not signature or len(signature) > 16384:
        return SignatureVerification(False, "private_readonly_signature_invalid")
    try:
        allowed_blob = subprocess.run(
            ["git", "show", f"{source_head}:{ALLOWED_SIGNERS_PATH}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError:
        return SignatureVerification(False, "private_readonly_operator_signer_unavailable")
    if allowed_blob.returncode != 0:
        return SignatureVerification(False, "private_readonly_operator_signer_not_enrolled")
    allowed = allowed_blob.stdout
    enrolled = any(
        line.strip().startswith((SIGNER_PRINCIPAL + " ").encode("ascii"))
        for line in allowed.splitlines()
        if line.strip() and not line.lstrip().startswith(b"#")
    )
    if not enrolled:
        return SignatureVerification(False, "private_readonly_operator_signer_not_enrolled")
    try:
        with tempfile.TemporaryDirectory(prefix="qs-private-ro-verify-") as temp:
            temp_root = Path(temp)
            allowed_path = temp_root / "allowed_signers"
            signature_path = temp_root / "receipt.sig"
            allowed_path.write_bytes(allowed)
            signature_path.write_bytes(signature)
            result = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_path),
                    "-I",
                    SIGNER_PRINCIPAL,
                    "-n",
                    SIGNATURE_NAMESPACE,
                    "-s",
                    str(signature_path),
                ],
                input=_canonical_bytes(payload),
                check=False,
                capture_output=True,
            )
    except OSError:
        return SignatureVerification(False, "private_readonly_signature_verifier_unavailable")
    if result.returncode != 0:
        return SignatureVerification(False, "private_readonly_signature_verification_failed")
    return SignatureVerification(True, "private_readonly_signature_verified")


def install_signed_receipt(
    *,
    root: Path,
    repo_root: Path,
    receipt_path: Path,
    signature_path: Path,
    now: datetime | None = None,
) -> ReceiptReference:
    now = now or utc_now()
    payload = _read_json(receipt_path)
    try:
        signature = signature_path.read_bytes()
    except OSError as exc:
        raise PermissionErrorCode("private_readonly_signature_unreadable") from exc
    session_id = str(payload.get("target_session_id", ""))
    valid = _validate_receipt(
        payload,
        signature=signature,
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )
    if not valid.granted:
        raise PermissionErrorCode(valid.reason)
    pending = root / "pending" / _session_key(session_id)
    destination = pending / f"{valid.receipt_id}.json"
    destination_signature = pending / f"{valid.receipt_id}.sig"
    _atomic_json(destination, payload, exclusive=True)
    try:
        _atomic_bytes(destination_signature, signature, exclusive=True)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    _audit_event(
        root,
        "installed_signed_receipt",
        {
            "receipt_id": valid.receipt_id,
            "target_session_hash": _session_key(session_id),
            "source_head": valid.source_head,
            "expires_at": valid.expires_at,
            "permissions": dict(PERMISSIONS),
        },
        now,
    )
    return ReceiptReference(
        receipt_id=valid.receipt_id,
        path=destination,
        source_head=valid.source_head,
        runner_git_blob=valid.runner_git_blob,
        runner_sha256=valid.runner_sha256,
        expires_at=valid.expires_at,
        signature_path=destination_signature,
        purpose=valid.purpose,
        runner_path=valid.runner_path,
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermissionErrorCode("private_readonly_receipt_unreadable") from exc
    if not isinstance(value, dict):
        raise PermissionErrorCode("private_readonly_receipt_invalid")
    return value


def _revoked(root: Path, receipt_id: str) -> bool:
    return (root / "revoked" / f"{receipt_id}.json").is_file()


def _validate_receipt(
    payload: dict[str, Any],
    *,
    signature: bytes,
    root: Path,
    repo_root: Path,
    session_id: str,
    now: datetime,
) -> CapabilityResult:
    version = payload.get("schema_version")
    scoped = version == PURPOSE_SCHEMA_VERSION
    if set(payload) != (RECEIPT_FIELDS | {"purpose"} if scoped else RECEIPT_FIELDS):
        return CapabilityResult(False, "private_readonly_receipt_fields_invalid")
    if version not in (SCHEMA_VERSION, PURPOSE_SCHEMA_VERSION):
        return CapabilityResult(False, "private_readonly_receipt_schema_invalid")
    purpose = payload.get("purpose") if scoped else OBSERVATION_PURPOSE
    if scoped and purpose != ACCOUNT_FACTS_PURPOSE:
        return CapabilityResult(False, "private_readonly_purpose_invalid")
    runner_path = _purpose_runner(purpose)
    if payload.get("runner_path") != runner_path:
        return CapabilityResult(False, "private_readonly_runner_path_mismatch")
    receipt_id = str(payload.get("receipt_id", ""))
    if not RECEIPT_ID_PATTERN.fullmatch(receipt_id):
        return CapabilityResult(False, "private_readonly_receipt_id_invalid")
    if payload.get("receipt_sha256") != receipt_digest(payload):
        return CapabilityResult(False, "private_readonly_receipt_digest_invalid")
    if payload.get("target_session_id") != session_id:
        return CapabilityResult(False, "private_readonly_receipt_session_mismatch")
    if payload.get("issuer_channel") != "human_local_terminal_outside_codex":
        return CapabilityResult(False, "private_readonly_receipt_issuer_invalid")
    if payload.get("credential_storage") != "windows_keyring_only":
        return CapabilityResult(False, "private_readonly_credential_contract_invalid")
    if payload.get("permissions") != PERMISSIONS:
        return CapabilityResult(False, "private_readonly_permissions_not_fail_closed")
    if _revoked(root, receipt_id):
        return CapabilityResult(False, "private_readonly_receipt_revoked")
    try:
        expires_at = _parse_time(payload.get("expires_at"))
        issued_at = _parse_time(payload.get("issued_at"))
    except PermissionErrorCode as exc:
        return CapabilityResult(False, str(exc))
    ttl_seconds = payload.get("ttl_seconds")
    if not isinstance(ttl_seconds, int) or not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        return CapabilityResult(False, "private_readonly_ttl_out_of_range")
    if expires_at - issued_at != timedelta(seconds=ttl_seconds):
        return CapabilityResult(False, "private_readonly_receipt_ttl_inconsistent")
    if issued_at > now:
        return CapabilityResult(False, "private_readonly_receipt_not_yet_valid")
    if now >= expires_at:
        return CapabilityResult(False, "private_readonly_receipt_expired")
    try:
        source_head, runner_blob, runner_sha256 = _identity_for_purpose(repo_root, purpose)
    except PermissionErrorCode as exc:
        return CapabilityResult(False, str(exc))
    if payload.get("source_head") != source_head:
        return CapabilityResult(False, "private_readonly_source_head_mismatch")
    if payload.get("runner_git_blob") != runner_blob:
        return CapabilityResult(False, "private_readonly_runner_git_blob_mismatch")
    if payload.get("runner_sha256") != runner_sha256:
        return CapabilityResult(False, "private_readonly_runner_sha256_mismatch")
    signature_result = verify_external_signature(
        payload,
        signature,
        repo_root=repo_root,
    )
    if not signature_result.verified:
        return CapabilityResult(False, signature_result.reason)
    return CapabilityResult(
        True,
        "private_readonly_receipt_valid",
        receipt_id=receipt_id,
        source_head=source_head,
        runner_git_blob=runner_blob,
        runner_sha256=runner_sha256,
        expires_at=str(payload["expires_at"]),
        purpose=purpose,
        runner_path=runner_path,
    )


def _lease_path(root: Path, session_id: str) -> Path:
    return root / "active" / f"{_session_key(session_id)}.json"


def _arm_path(root: Path, session_id: str) -> Path:
    return root / "armed" / f"{_session_key(session_id)}.json"


def _binding_claim_path(root: Path, session_id: str) -> Path:
    return root / "binding_claim" / f"{_session_key(session_id)}.json"


def _claimed_receipt_path(root: Path, receipt_id: str) -> Path:
    return root / "claims" / f"{receipt_id}.json"


def _binding_claim_result(
    *,
    root: Path,
    session_id: str,
    turn_id: str,
    capability: CapabilityResult | None = None,
) -> CapabilityResult:
    path = _binding_claim_path(root, session_id)
    if not path.is_file():
        return CapabilityResult(False, "private_readonly_binding_claim_missing")
    try:
        claim = _read_json(path)
    except PermissionErrorCode:
        return CapabilityResult(
            False,
            "private_readonly_binding_claim_unreadable",
            armed=True,
        )
    required = {
        "schema_version",
        "target_session_hash",
        "turn_id",
        "receipt_id",
        "source_head",
        "runner_git_blob",
        "runner_sha256",
        "claimed_at",
        "claim_sha256",
    }
    scoped = "purpose" in claim
    if scoped:
        required |= {"purpose", "runner_path"}
        if claim.get("purpose") != ACCOUNT_FACTS_PURPOSE or claim.get("runner_path") != ACCOUNT_FACTS_RUNNER_PATH:
            return CapabilityResult(False, "private_readonly_binding_claim_invalid", armed=True)
    if set(claim) != required or claim.get("schema_version") != BINDING_CLAIM_SCHEMA_VERSION:
        return CapabilityResult(False, "private_readonly_binding_claim_invalid", armed=True)
    expected = hashlib.sha256(
        _canonical_bytes({k: v for k, v in claim.items() if k != "claim_sha256"})
    ).hexdigest()
    if claim.get("claim_sha256") != expected:
        return CapabilityResult(
            False,
            "private_readonly_binding_claim_digest_invalid",
            armed=True,
        )
    claimed_turn = str(claim.get("turn_id", ""))
    if (
        claim.get("target_session_hash") != _session_key(session_id)
        or not SESSION_PATTERN.fullmatch(claimed_turn)
        or not RECEIPT_ID_PATTERN.fullmatch(str(claim.get("receipt_id", "")))
        or not HEAD_PATTERN.fullmatch(str(claim.get("source_head", "")))
        or not HEAD_PATTERN.fullmatch(str(claim.get("runner_git_blob", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(claim.get("runner_sha256", "")))
    ):
        return CapabilityResult(False, "private_readonly_binding_claim_invalid", armed=True)
    if claimed_turn != turn_id:
        return CapabilityResult(
            False,
            "private_readonly_capability_bound_to_other_turn",
            armed=True,
        )
    if capability is not None and (
        claim.get("receipt_id") != capability.receipt_id
        or claim.get("source_head") != capability.source_head
        or claim.get("runner_git_blob") != capability.runner_git_blob
        or claim.get("runner_sha256") != capability.runner_sha256
        or claim.get("purpose", OBSERVATION_PURPOSE) != capability.purpose
        or claim.get("runner_path", RUNNER_PATH) != capability.runner_path
    ):
        return CapabilityResult(
            False,
            "private_readonly_binding_claim_capability_mismatch",
            armed=True,
        )
    return CapabilityResult(
        False,
        "private_readonly_binding_claimed",
        receipt_id=str(claim["receipt_id"]),
        source_head=str(claim["source_head"]),
        runner_git_blob=str(claim["runner_git_blob"]),
        runner_sha256=str(claim["runner_sha256"]),
        armed=True,
        purpose=claim.get("purpose", OBSERVATION_PURPOSE),
        runner_path=claim.get("runner_path", RUNNER_PATH),
    )


def _arm_capability_from_path(
    *,
    path: Path,
    root: Path,
    repo_root: Path,
    session_id: str,
    now: datetime,
) -> CapabilityResult:
    try:
        arm = _read_json(path)
    except PermissionErrorCode:
        return CapabilityResult(False, "private_readonly_arm_unreadable", armed=True)
    receipt = arm.get("receipt")
    signature_b64 = arm.get("signature_b64")
    if (
        arm.get("schema_version") != ARM_SCHEMA_VERSION
        or not isinstance(receipt, dict)
        or not isinstance(signature_b64, str)
    ):
        return CapabilityResult(False, "private_readonly_arm_invalid", armed=True)
    expected = hashlib.sha256(
        _canonical_bytes({k: v for k, v in arm.items() if k != "arm_sha256"})
    ).hexdigest()
    if arm.get("arm_sha256") != expected:
        return CapabilityResult(False, "private_readonly_arm_digest_invalid", armed=True)
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except ValueError:
        return CapabilityResult(False, "private_readonly_arm_signature_invalid", armed=True)
    valid = _validate_receipt(
        receipt,
        signature=signature,
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )
    if not valid.granted:
        return CapabilityResult(False, valid.reason, armed=True)
    return CapabilityResult(
        False,
        "private_readonly_capability_armed",
        receipt_id=valid.receipt_id,
        source_head=valid.source_head,
        runner_git_blob=valid.runner_git_blob,
        runner_sha256=valid.runner_sha256,
        expires_at=valid.expires_at,
        armed=True,
        purpose=valid.purpose,
        runner_path=valid.runner_path,
    )


def _armed_capability(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    now: datetime,
) -> CapabilityResult:
    path = _arm_path(root, session_id)
    if not path.is_file():
        return CapabilityResult(False, "private_readonly_armed_attempt_missing")
    return _arm_capability_from_path(
        path=path,
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )


def _arm_for_user_prompt(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    now: datetime,
) -> CapabilityResult:
    if _lease_path(root, session_id).is_file():
        return CapabilityResult(False, "private_readonly_active_lease_exists")
    if _binding_claim_path(root, session_id).is_file():
        return CapabilityResult(False, "private_readonly_binding_in_progress")
    arm_path = _arm_path(root, session_id)
    if arm_path.is_file():
        interrupted = (
            root
            / "interrupted"
            / f"{_session_key(session_id)}-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.json"
        )
        interrupted.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(arm_path, interrupted)
        except OSError:
            return CapabilityResult(
                False,
                "private_readonly_armed_attempt_state_race",
                armed=True,
            )
        _audit_event(
            root,
            "armed_attempt_interrupted",
            {"target_session_hash": _session_key(session_id)},
            now,
        )
        return CapabilityResult(False, "private_readonly_armed_attempt_interrupted")

    pending_dir = root / "pending" / _session_key(session_id)
    candidates = (
        sorted(
            path
            for path in pending_dir.glob("*.json")
            if not _claimed_receipt_path(root, path.stem).is_file()
        )
        if pending_dir.is_dir()
        else []
    )
    if not candidates:
        return CapabilityResult(False, "private_readonly_receipt_missing")
    if len(candidates) != 1:
        return CapabilityResult(False, "private_readonly_receipt_ambiguous")
    try:
        receipt = _read_json(candidates[0])
    except PermissionErrorCode as exc:
        return CapabilityResult(False, str(exc))
    signature_path = candidates[0].with_suffix(".sig")
    try:
        signature = signature_path.read_bytes()
    except OSError:
        return CapabilityResult(False, "private_readonly_signature_missing")
    valid = _validate_receipt(
        receipt,
        signature=signature,
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )
    if not valid.granted:
        return valid
    claim = {
        "schema_version": "btc_private_readonly_permission_prompt_claim_v1",
        "receipt_id": valid.receipt_id,
        "target_session_hash": _session_key(session_id),
        "claimed_at": _iso(now),
        "claim_channel": "user_prompt_hook",
    }
    try:
        _atomic_json(_claimed_receipt_path(root, valid.receipt_id), claim, exclusive=True)
    except FileExistsError:
        return CapabilityResult(False, "private_readonly_receipt_already_claimed")
    arm: dict[str, Any] = {
        "schema_version": ARM_SCHEMA_VERSION,
        "armed_at": _iso(now),
        "receipt": receipt,
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }
    arm["arm_sha256"] = hashlib.sha256(_canonical_bytes(arm)).hexdigest()
    try:
        _atomic_json(arm_path, arm, exclusive=True)
    except FileExistsError:
        return CapabilityResult(
            False,
            "private_readonly_armed_attempt_state_race",
            armed=True,
        )
    archived = root / "armed_sources" / f"{valid.receipt_id}.json"
    archived.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(candidates[0], archived)
        os.replace(signature_path, archived.with_suffix(".sig"))
    except OSError:
        # The immutable claim and arm are authoritative; a leftover pending
        # source is filtered by the receipt claim and cannot be armed again.
        pass
    _audit_event(
        root,
        "armed_for_exact_runner",
        {
            "receipt_id": valid.receipt_id,
            "target_session_hash": _session_key(session_id),
            "source_head": valid.source_head,
        },
        now,
    )
    return _armed_capability(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )


def _active_capability(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    turn_id: str,
    now: datetime,
) -> CapabilityResult:
    path = _lease_path(root, session_id)
    if not path.is_file():
        return CapabilityResult(False, "private_readonly_active_lease_missing")
    try:
        lease = _read_json(path)
    except PermissionErrorCode:
        return CapabilityResult(False, "private_readonly_active_lease_unreadable")
    receipt = lease.get("receipt")
    signature_b64 = lease.get("signature_b64")
    if (
        lease.get("schema_version") != LEASE_SCHEMA_VERSION
        or not isinstance(receipt, dict)
        or not isinstance(signature_b64, str)
    ):
        return CapabilityResult(False, "private_readonly_active_lease_invalid")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except ValueError:
        return CapabilityResult(False, "private_readonly_active_signature_invalid")
    if lease.get("turn_id") != turn_id:
        return CapabilityResult(
            False,
            "private_readonly_capability_bound_to_other_turn",
            armed=True,
        )
    result = _validate_receipt(
        receipt,
        signature=signature,
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )
    if not result.granted:
        return result
    expected = hashlib.sha256(
        _canonical_bytes({k: v for k, v in lease.items() if k != "lease_sha256"})
    ).hexdigest()
    if lease.get("lease_sha256") != expected:
        return CapabilityResult(False, "private_readonly_active_lease_digest_invalid")
    return CapabilityResult(
        True,
        "private_readonly_capability_active",
        receipt_id=result.receipt_id,
        source_head=result.source_head,
        runner_git_blob=result.runner_git_blob,
        runner_sha256=result.runner_sha256,
        expires_at=result.expires_at,
        purpose=result.purpose,
        runner_path=result.runner_path,
    )


def resolve_capability(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    turn_id: str,
    event_name: str,
    now: datetime | None = None,
    consume: bool,
) -> CapabilityResult:
    now = now or utc_now()
    if not session_id:
        return CapabilityResult(False, "private_readonly_session_id_missing")
    if not SESSION_PATTERN.fullmatch(session_id):
        return CapabilityResult(False, "private_readonly_session_id_invalid")
    if consume:
        if event_name != "UserPromptSubmit":
            return CapabilityResult(False, "private_readonly_root_user_prompt_required")
        return _arm_for_user_prompt(
            root=root,
            repo_root=repo_root,
            session_id=session_id,
            now=now,
        )
    armed = _armed_capability(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )
    binding_claim_exists = _binding_claim_path(root, session_id).is_file()
    if not turn_id or not SESSION_PATTERN.fullmatch(turn_id):
        return CapabilityResult(
            False,
            "private_readonly_turn_id_invalid",
            armed=armed.armed or binding_claim_exists,
        )
    active = _active_capability(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        turn_id=turn_id,
        now=now,
    )
    if active.granted or active.reason != "private_readonly_active_lease_missing":
        return active
    if binding_claim_exists:
        claim = _binding_claim_result(
            root=root,
            session_id=session_id,
            turn_id=turn_id,
        )
        if claim.reason != "private_readonly_binding_claimed":
            return claim
        if not armed.armed or armed.reason != "private_readonly_capability_armed":
            return CapabilityResult(
                False,
                "private_readonly_binding_claim_arm_unavailable",
                armed=True,
            )
        verified_claim = _binding_claim_result(
            root=root,
            session_id=session_id,
            turn_id=turn_id,
            capability=armed,
        )
        if verified_claim.reason != "private_readonly_binding_claimed":
            return verified_claim
        return armed
    return armed


def _bind_armed_capability(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    turn_id: str,
    cwd: Path,
    command: str,
    now: datetime,
) -> CapabilityResult:
    if not session_id or not SESSION_PATTERN.fullmatch(session_id):
        return CapabilityResult(False, "private_readonly_session_id_invalid")
    if not turn_id or not SESSION_PATTERN.fullmatch(turn_id):
        return CapabilityResult(False, "private_readonly_turn_id_invalid")
    active = _active_capability(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        turn_id=turn_id,
        now=now,
    )
    if active.granted or active.reason != "private_readonly_active_lease_missing":
        return active
    armed = _armed_capability(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )
    if not armed.armed or armed.reason != "private_readonly_capability_armed":
        claim = _binding_claim_result(
            root=root,
            session_id=session_id,
            turn_id=turn_id,
        )
        if claim.reason == "private_readonly_capability_bound_to_other_turn":
            return claim
        return CapabilityResult(
            False,
            "private_readonly_binding_claim_arm_unavailable",
            armed=claim.armed,
        )
    claim = _claim_binding_for_exact_runner(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        turn_id=turn_id,
        cwd=cwd,
        command=command,
        capability=armed,
        now=now,
    )
    if claim.reason != "private_readonly_binding_claimed":
        return claim
    try:
        arm_payload = _read_json(_arm_path(root, session_id))
    except PermissionErrorCode:
        active = _active_capability(
            root=root,
            repo_root=repo_root,
            session_id=session_id,
            turn_id=turn_id,
            now=now,
        )
        if active.granted or active.reason != "private_readonly_active_lease_missing":
            return active
        return CapabilityResult(
            False,
            "private_readonly_binding_claim_arm_unavailable",
            armed=True,
        )
    lease: dict[str, Any] = {
        "schema_version": LEASE_SCHEMA_VERSION,
        "turn_id": turn_id,
        "activated_at": _iso(now),
        "receipt": arm_payload["receipt"],
        "signature_b64": arm_payload["signature_b64"],
    }
    lease["lease_sha256"] = hashlib.sha256(_canonical_bytes(lease)).hexdigest()
    try:
        _atomic_json(_lease_path(root, session_id), lease, exclusive=True)
    except FileExistsError:
        return _active_capability(
            root=root,
            repo_root=repo_root,
            session_id=session_id,
            turn_id=turn_id,
            now=now,
        )
    bound = root / "bound" / f"{armed.receipt_id}.json"
    bound.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(_arm_path(root, session_id), bound)
    except OSError:
        # The immutable winner claim plus lease are authoritative. Failure to
        # archive the arm cannot let another turn acquire the capability.
        pass
    _audit_event(
        root,
        "bound_to_pretool_turn",
        {
            "receipt_id": armed.receipt_id,
            "target_session_hash": _session_key(session_id),
            "turn_hash": _session_key(turn_id),
            "source_head": armed.source_head,
        },
        now,
    )
    return _active_capability(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        turn_id=turn_id,
        now=now,
    )


def _split_strict(command: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(command)
    while index < length:
        while index < length and command[index].isspace():
            index += 1
        if index >= length:
            break
        if command[index] == '"':
            index += 1
            end = command.find('"', index)
            if end < 0:
                raise PermissionErrorCode("private_readonly_runner_quote_invalid")
            tokens.append(command[index:end])
            index = end + 1
            if index < length and not command[index].isspace():
                raise PermissionErrorCode("private_readonly_runner_quote_invalid")
            continue
        end = index
        while end < length and not command[end].isspace():
            if command[end] in "\"'":
                raise PermissionErrorCode("private_readonly_runner_quote_invalid")
            end += 1
        tokens.append(command[index:end])
        index = end
    return tokens


def _validate_runner_tokens(
    *,
    command: str,
    cwd: Path,
    repo_root: Path,
    capability: CapabilityResult,
) -> str | None:
    if SHELL_META_PATTERN.search(command):
        return "private_readonly_shell_metachar_blocked"
    try:
        tokens = _split_strict(command)
    except PermissionErrorCode as exc:
        return str(exc)
    try:
        expected_command = _runner_command(capability)
    except PermissionErrorCode as exc:
        return str(exc)
    if tokens[:3] != ["py", "-3", capability.runner_path]:
        return "private_readonly_runner_entry_invalid"
    if cwd.resolve() != repo_root.resolve():
        return "private_readonly_registered_main_cwd_required"
    if len(tokens) != 3 or command != expected_command:
        return "private_readonly_runner_argument_invalid"
    return None


def _claim_binding_for_exact_runner(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    turn_id: str,
    cwd: Path,
    command: str,
    capability: CapabilityResult,
    now: datetime,
) -> CapabilityResult:
    if not session_id or not SESSION_PATTERN.fullmatch(session_id):
        return CapabilityResult(False, "private_readonly_session_id_invalid")
    if not turn_id or not SESSION_PATTERN.fullmatch(turn_id):
        return CapabilityResult(False, "private_readonly_turn_id_invalid")
    if not capability.armed or capability.reason != "private_readonly_capability_armed":
        return CapabilityResult(False, "private_readonly_binding_claim_capability_invalid")
    invalid = _validate_runner_tokens(
        command=command,
        cwd=cwd,
        repo_root=repo_root,
        capability=capability,
    )
    if invalid:
        return CapabilityResult(False, invalid, armed=True)
    claim: dict[str, Any] = {
        "schema_version": BINDING_CLAIM_SCHEMA_VERSION,
        **_scope_fields(capability),
        "target_session_hash": _session_key(session_id),
        "turn_id": turn_id,
        "receipt_id": capability.receipt_id,
        "source_head": capability.source_head,
        "runner_git_blob": capability.runner_git_blob,
        "runner_sha256": capability.runner_sha256,
        "claimed_at": _iso(now),
    }
    claim["claim_sha256"] = hashlib.sha256(_canonical_bytes(claim)).hexdigest()
    try:
        _atomic_json(_binding_claim_path(root, session_id), claim, exclusive=True)
    except FileExistsError:
        pass
    result = _binding_claim_result(
        root=root,
        session_id=session_id,
        turn_id=turn_id,
        capability=capability,
    )
    if result.reason == "private_readonly_binding_claimed":
        _audit_event(
            root,
            "binding_claim_observed",
            {
                "receipt_id": result.receipt_id,
                "target_session_hash": _session_key(session_id),
                "turn_hash": _session_key(turn_id),
                "source_head": result.source_head,
            },
            now,
        )
    return result


def authorize_runner_command(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    turn_id: str,
    cwd: Path,
    command: str,
    now: datetime | None = None,
) -> RunnerAuthorization:
    now = now or utc_now()
    capability = resolve_capability(
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        turn_id=turn_id,
        event_name="PreToolUse",
        now=now,
        consume=False,
    )
    if not capability.granted:
        # Only the validated prompt arm may proceed to argv validation and an
        # atomic winner claim.  A claim/lease already bound to another turn,
        # or any corrupt/incomplete armed state, must preserve its precise
        # fail-closed reason instead of being reclassified by empty identity
        # fields during runner validation.
        if capability.reason != "private_readonly_capability_armed":
            return RunnerAuthorization(False, capability.reason)
    invalid = _validate_runner_tokens(
        command=command,
        cwd=cwd,
        repo_root=repo_root,
        capability=capability,
    )
    if invalid:
        return RunnerAuthorization(False, invalid)
    if capability.armed:
        capability = _bind_armed_capability(
            root=root,
            repo_root=repo_root,
            session_id=session_id,
            turn_id=turn_id,
            cwd=cwd,
            command=command,
            now=now,
        )
        if not capability.granted:
            return RunnerAuthorization(False, capability.reason)
    claim_path = root / "launches" / f"{capability.receipt_id}.json"
    claim = _build_runner_launch_claim(
        capability=capability,
        session_id=session_id,
        claim_channel="pretool_hook",
        turn_hash=_session_key(turn_id),
        now=now,
    )
    try:
        _atomic_json(claim_path, claim, exclusive=True)
    except FileExistsError:
        return RunnerAuthorization(False, "private_readonly_runner_launch_replay")
    _audit_event(
        root,
        "runner_launch_claimed",
        {
            "receipt_id": capability.receipt_id,
            "target_session_hash": _session_key(session_id),
            "turn_hash": _session_key(turn_id),
            "source_head": capability.source_head,
        },
        now,
    )
    return RunnerAuthorization(
        True,
        "private_readonly_runner_launch_authorized",
        capability.receipt_id,
    )


def _runner_start_path(root: Path, receipt_id: str) -> Path:
    return root / "runner_starts" / f"{receipt_id}.json"


def _runner_launch_path(root: Path, receipt_id: str) -> Path:
    return root / "launches" / f"{receipt_id}.json"


def _build_runner_launch_claim(
    *,
    capability: CapabilityResult,
    session_id: str,
    claim_channel: str,
    turn_hash: str,
    now: datetime,
) -> dict[str, Any]:
    claim: dict[str, Any] = {
        "schema_version": RUNNER_LAUNCH_SCHEMA_VERSION,
        **_scope_fields(capability),
        "receipt_id": capability.receipt_id,
        "target_session_hash": _session_key(session_id),
        "turn_hash": turn_hash,
        "claim_channel": claim_channel,
        "source_head": capability.source_head,
        "runner_git_blob": capability.runner_git_blob,
        "runner_sha256": capability.runner_sha256,
        "claimed_at": _iso(now),
        "permissions": dict(PERMISSIONS),
        "runner_invocation_sha256": hashlib.sha256(
            _runner_command(capability).encode("utf-8")
        ).hexdigest(),
    }
    claim["claim_sha256"] = hashlib.sha256(_canonical_bytes(claim)).hexdigest()
    return claim


def _validate_runner_launch_claim(
    claim: dict[str, Any],
    *,
    capability: CapabilityResult,
    session_id: str,
) -> str | None:
    required = {
        "schema_version",
        "receipt_id",
        "target_session_hash",
        "turn_hash",
        "claim_channel",
        "source_head",
        "runner_git_blob",
        "runner_sha256",
        "claimed_at",
        "permissions",
        "runner_invocation_sha256",
        "claim_sha256",
    }
    required |= set(_scope_fields(capability))
    if set(claim) != required or claim.get("schema_version") != RUNNER_LAUNCH_SCHEMA_VERSION:
        return "private_readonly_runner_launch_invalid"
    expected = hashlib.sha256(
        _canonical_bytes({k: v for k, v in claim.items() if k != "claim_sha256"})
    ).hexdigest()
    if claim.get("claim_sha256") != expected:
        return "private_readonly_runner_launch_digest_invalid"
    channel = claim.get("claim_channel")
    turn_hash = claim.get("turn_hash")
    if channel == "pretool_hook":
        if not isinstance(turn_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", turn_hash):
            return "private_readonly_runner_launch_turn_invalid"
    elif channel == "runner_self":
        if turn_hash != "":
            return "private_readonly_runner_launch_turn_invalid"
    else:
        return "private_readonly_runner_launch_channel_invalid"
    if (
        claim.get("receipt_id") != capability.receipt_id
        or claim.get("target_session_hash") != _session_key(session_id)
        or claim.get("source_head") != capability.source_head
        or claim.get("runner_git_blob") != capability.runner_git_blob
        or claim.get("runner_sha256") != capability.runner_sha256
        or claim.get("permissions") != PERMISSIONS
        or claim.get("purpose", OBSERVATION_PURPOSE) != capability.purpose
        or claim.get("runner_path", RUNNER_PATH) != capability.runner_path
        or claim.get("runner_invocation_sha256")
        != hashlib.sha256(_runner_command(capability).encode("utf-8")).hexdigest()
    ):
        return "private_readonly_runner_launch_capability_mismatch"
    return None


def _active_capability_for_runner_session(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    now: datetime,
) -> CapabilityResult:
    path = _lease_path(root, session_id)
    if not path.is_file():
        return CapabilityResult(False, "private_readonly_active_lease_missing")
    try:
        lease = _read_json(path)
    except PermissionErrorCode:
        return CapabilityResult(False, "private_readonly_active_lease_unreadable")
    receipt = lease.get("receipt")
    signature_b64 = lease.get("signature_b64")
    bound_turn = str(lease.get("turn_id", ""))
    if (
        lease.get("schema_version") != LEASE_SCHEMA_VERSION
        or not isinstance(receipt, dict)
        or not isinstance(signature_b64, str)
        or not SESSION_PATTERN.fullmatch(bound_turn)
    ):
        return CapabilityResult(False, "private_readonly_active_lease_invalid")
    expected = hashlib.sha256(
        _canonical_bytes({k: v for k, v in lease.items() if k != "lease_sha256"})
    ).hexdigest()
    if lease.get("lease_sha256") != expected:
        return CapabilityResult(False, "private_readonly_active_lease_digest_invalid")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except ValueError:
        return CapabilityResult(False, "private_readonly_active_signature_invalid")
    return _validate_receipt(
        receipt,
        signature=signature,
        root=root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )


def _capability_for_runner_process(
    *,
    root: Path,
    repo_root: Path,
    session_id: str,
    now: datetime,
) -> CapabilityResult:
    active_path = _lease_path(root, session_id)
    if active_path.is_file():
        active = _active_capability_for_runner_session(
            root=root,
            repo_root=repo_root,
            session_id=session_id,
            now=now,
        )
        if not active.granted:
            return active
        pending_dir = root / "pending" / _session_key(session_id)
        unclaimed = (
            [
                path
                for path in pending_dir.glob("*.json")
                if not _claimed_receipt_path(root, path.stem).is_file()
            ]
            if pending_dir.is_dir()
            else []
        )
        if unclaimed:
            return CapabilityResult(False, "private_readonly_receipt_ambiguous")
        return active
    if _binding_claim_path(root, session_id).is_file():
        return CapabilityResult(
            False,
            "private_readonly_binding_claim_arm_unavailable",
            armed=True,
        )
    armed_path = _arm_path(root, session_id)
    if armed_path.is_file():
        armed = _armed_capability(
            root=root,
            repo_root=repo_root,
            session_id=session_id,
            now=now,
        )
        if not armed.armed or armed.reason != "private_readonly_capability_armed":
            return armed
        pending_dir = root / "pending" / _session_key(session_id)
        unclaimed = (
            [
                path
                for path in pending_dir.glob("*.json")
                if not _claimed_receipt_path(root, path.stem).is_file()
            ]
            if pending_dir.is_dir()
            else []
        )
        if unclaimed:
            return CapabilityResult(False, "private_readonly_receipt_ambiguous")
        return CapabilityResult(
            True,
            "private_readonly_runner_process_receipt_valid",
            receipt_id=armed.receipt_id,
            source_head=armed.source_head,
            runner_git_blob=armed.runner_git_blob,
            runner_sha256=armed.runner_sha256,
            expires_at=armed.expires_at,
            purpose=armed.purpose,
            runner_path=armed.runner_path,
        )
    return CapabilityResult(False, "private_readonly_armed_attempt_missing")


def authorize_runner_process(
    *,
    repo_root: Path,
    cwd: Path,
    environ: Mapping[str, str],
    root: Path | None = None,
    now: datetime | None = None,
    runner_path: str = RUNNER_PATH,
) -> RunnerProcessAuthorization:
    """Authorize the actual runner process before any credential or network use.

    This is the authoritative boundary for both direct PreToolUse launches and
    hosted command channels that do not emit PreToolUse. Session identity never
    substitutes for a hook turn: authorization requires the signed receipt
    target_session_id to match CODEX_SESSION_ID. CODEX_THREAD_ID and THREAD_ID
    are not authorization identities and never stand in for a session or turn;
    the runner records a separate one-time start claim.
    """

    now = now or utc_now()
    session_id = str(environ.get("CODEX_SESSION_ID", ""))
    if not session_id:
        return RunnerProcessAuthorization(
            False, "private_readonly_process_session_id_missing"
        )
    if not SESSION_PATTERN.fullmatch(session_id):
        return RunnerProcessAuthorization(
            False, "private_readonly_process_identity_invalid"
        )
    if cwd.resolve() != repo_root.resolve():
        return RunnerProcessAuthorization(
            False, "private_readonly_registered_main_cwd_required"
        )
    try:
        if runner_path not in PURPOSE_RUNNERS.values():
            return RunnerProcessAuthorization(False, "private_readonly_runner_entry_invalid")
        if runner_path == RUNNER_PATH:
            _require_main_checkout(repo_root)
        else:
            _require_main_checkout(repo_root, runner_path=runner_path)
        capability_root = root if root is not None else default_capability_root()
    except PermissionErrorCode as exc:
        return RunnerProcessAuthorization(False, str(exc))
    capability = _capability_for_runner_process(
        root=capability_root,
        repo_root=repo_root,
        session_id=session_id,
        now=now,
    )
    if not capability.granted:
        return RunnerProcessAuthorization(False, capability.reason)
    if runner_path != capability.runner_path:
        return RunnerProcessAuthorization(False, "private_readonly_runner_purpose_mismatch")
    launch_path = _runner_launch_path(capability_root, capability.receipt_id)
    if launch_path.is_file():
        try:
            launch_claim = _read_json(launch_path)
        except PermissionErrorCode:
            return RunnerProcessAuthorization(
                False, "private_readonly_runner_launch_unreadable"
            )
    else:
        launch_claim = _build_runner_launch_claim(
            capability=capability,
            session_id=session_id,
            claim_channel="runner_self",
            turn_hash="",
            now=now,
        )
        try:
            _atomic_json(launch_path, launch_claim, exclusive=True)
        except FileExistsError:
            try:
                launch_claim = _read_json(launch_path)
            except PermissionErrorCode:
                return RunnerProcessAuthorization(
                    False, "private_readonly_runner_launch_unreadable"
                )
    invalid_launch = _validate_runner_launch_claim(
        launch_claim,
        capability=capability,
        session_id=session_id,
    )
    if invalid_launch:
        return RunnerProcessAuthorization(False, invalid_launch)
    start_claim: dict[str, Any] = {
        "schema_version": RUNNER_START_SCHEMA_VERSION,
        **_scope_fields(capability),
        "receipt_id": capability.receipt_id,
        "target_session_hash": _session_key(session_id),
        "source_head": capability.source_head,
        "runner_git_blob": capability.runner_git_blob,
        "runner_sha256": capability.runner_sha256,
        "claimed_at": _iso(now),
        "permissions": dict(PERMISSIONS),
        "launch_claim_sha256": launch_claim["claim_sha256"],
    }
    start_claim["claim_sha256"] = hashlib.sha256(
        _canonical_bytes(start_claim)
    ).hexdigest()
    try:
        _atomic_json(
            _runner_start_path(capability_root, capability.receipt_id),
            start_claim,
            exclusive=True,
        )
    except FileExistsError:
        return RunnerProcessAuthorization(
            False, "private_readonly_runner_start_replay"
        )
    _audit_event(
        capability_root,
        "runner_process_start_claimed",
        {
            "receipt_id": capability.receipt_id,
            "target_session_hash": _session_key(session_id),
            "source_head": capability.source_head,
            "permissions": dict(PERMISSIONS),
        },
        now,
    )
    prefix = "btc-demo-private-readonly" if capability.purpose == OBSERVATION_PURPOSE else "btc-account-facts-readonly"
    runtime_root = (
        repo_root.resolve().parent
        / f"runtime-data-{prefix}-{capability.receipt_id}"
    )
    run_prefix = "btc-private-readonly" if capability.purpose == OBSERVATION_PURPOSE else "btc-account-facts-readonly"
    run_id = f"{run_prefix}-{capability.receipt_id}"
    return RunnerProcessAuthorization(
        True,
        "private_readonly_runner_process_authorized",
        receipt_id=capability.receipt_id,
        source_head=capability.source_head,
        runner_git_blob=capability.runner_git_blob,
        runner_sha256=capability.runner_sha256,
        runtime_root=runtime_root,
        run_id=run_id,
        confirmation=CONFIRMATION if capability.purpose == OBSERVATION_PURPOSE else "OKX DEMO ACCOUNT FACTS READONLY ONCE",
        authorization_ticket_hash=str(start_claim["claim_sha256"]),
        purpose=capability.purpose,
        runner_path=capability.runner_path,
    )


def revoke_receipt(
    *,
    root: Path,
    receipt_id: str,
    now: datetime | None = None,
) -> Path:
    now = now or utc_now()
    if not RECEIPT_ID_PATTERN.fullmatch(receipt_id):
        raise PermissionErrorCode("private_readonly_receipt_id_invalid")
    path = root / "revoked" / f"{receipt_id}.json"
    payload = {
        "schema_version": "btc_private_readonly_permission_revocation_v1",
        "receipt_id": receipt_id,
        "revoked_at": _iso(now),
        "permissions": {
            "private": False,
            "promotion": False,
            "order": False,
            "real_order": False,
            "paper": False,
            "live": False,
            "transfer": False,
            "withdraw": False,
        },
    }
    try:
        _atomic_json(path, payload, exclusive=True)
    except FileExistsError:
        return path
    _audit_event(root, "revoked", {"receipt_id": receipt_id}, now)
    return path


def _require_main_checkout(repo_root: Path, *, runner_path: str = RUNNER_PATH) -> None:
    if runner_path not in PURPOSE_RUNNERS.values():
        raise PermissionErrorCode("private_readonly_runner_path_mismatch")
    branch = _git(repo_root, "symbolic-ref", "--short", "HEAD")
    head = _git(repo_root, "rev-parse", "HEAD")
    main = _git(repo_root, "rev-parse", "refs/heads/main")
    if branch != "main" or head != main:
        raise PermissionErrorCode("private_readonly_operator_action_requires_registered_main")
    for args in (
        ("diff", "--quiet", "--", runner_path),
        ("diff", "--cached", "--quiet", "--", runner_path),
    ):
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise PermissionErrorCode("private_readonly_runner_must_be_committed")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare, install, or revoke externally signed private-readonly receipts."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--target-session-id", required=True)
    prepare.add_argument("--ttl-seconds", type=int, default=300)
    prepare.add_argument("--purpose", choices=tuple(PURPOSE_RUNNERS), default=OBSERVATION_PURPOSE)
    prepare.add_argument("--output", type=Path, required=True)
    install = subparsers.add_parser("install")
    install.add_argument("--receipt", type=Path, required=True)
    install.add_argument("--signature", type=Path, required=True)
    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("--receipt-id", required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    root = default_capability_root()
    try:
        if args.action == "prepare":
            _require_main_checkout(repo_root, runner_path=_purpose_runner(args.purpose))
            if not sys.stdin.isatty():
                raise PermissionErrorCode("private_readonly_human_terminal_required")
            output_path = args.output.resolve()
            try:
                output_path.relative_to(repo_root.resolve())
            except ValueError:
                pass
            else:
                raise PermissionErrorCode("private_readonly_unsigned_receipt_must_stay_outside_repo")
            expected = f"PREPARE PRIVATE READONLY {args.target_session_id}"
            if args.purpose != OBSERVATION_PURPOSE:
                expected += f" {args.purpose}"
            entered = input(f"Type exactly '{expected}' to prepare: ")
            if entered != expected:
                raise PermissionErrorCode("private_readonly_human_confirmation_required")
            receipt = build_unsigned_receipt(
                repo_root=repo_root,
                target_session_id=args.target_session_id,
                ttl_seconds=args.ttl_seconds,
                purpose=args.purpose,
            )
            _atomic_bytes(output_path, _canonical_bytes(receipt), exclusive=True)
            output = {
                "status": "unsigned_receipt_prepared",
                "purpose": args.purpose,
                "runner_path": receipt["runner_path"],
                "receipt_id": receipt["receipt_id"],
                "source_head": receipt["source_head"],
                "runner_git_blob": receipt["runner_git_blob"],
                "runner_sha256": receipt["runner_sha256"],
                "expires_at": receipt["expires_at"],
                "signature_namespace": SIGNATURE_NAMESPACE,
                "signer_principal": SIGNER_PRINCIPAL,
                "private": False,
                "promotion": False,
                "order": False,
                "real_order": False,
                "paper": False,
                "live": False,
                "transfer": False,
                "withdraw": False,
            }
        elif args.action == "install":
            _require_main_checkout(repo_root)
            receipt = install_signed_receipt(
                root=root,
                repo_root=repo_root,
                receipt_path=args.receipt.resolve(),
                signature_path=args.signature.resolve(),
            )
            output = {
                "status": "signed_receipt_installed",
                "purpose": receipt.purpose,
                "runner_path": receipt.runner_path,
                "receipt_id": receipt.receipt_id,
                "source_head": receipt.source_head,
                "runner_git_blob": receipt.runner_git_blob,
                "runner_sha256": receipt.runner_sha256,
                "expires_at": receipt.expires_at,
                "private": False,
                "promotion": False,
                "order": False,
                "real_order": False,
                "paper": False,
                "live": False,
                "transfer": False,
                "withdraw": False,
            }
        else:
            path = revoke_receipt(root=root, receipt_id=args.receipt_id)
            output = {
                "status": "revoked",
                "receipt_id": args.receipt_id,
                "revocation_path": str(path),
                "private": False,
                "promotion": False,
                "order": False,
                "real_order": False,
                "paper": False,
                "live": False,
                "transfer": False,
                "withdraw": False,
            }
    except PermissionErrorCode as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
