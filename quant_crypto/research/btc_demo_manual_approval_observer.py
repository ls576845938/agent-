from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.research.btc_demo_observation_accumulator import (
    safety_flags,
    stable_payload_hash,
)


SCHEMA_VERSION = "btc_demo_manual_approval_observer_v2"
MANIFEST_SCHEMA_VERSION = "btc_demo_manual_approval_observer_manifest_v2"
MANUAL_APPROVAL_BLOCKER = "btc_okx_native:manual_promotion_approval_missing"
_HEX_HEAD = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEY_TOKENS = (
    "api_key",
    "secret",
    "passphrase",
    "token",
    "private_key",
    "auth_header",
    "screenshot",
    "account_id",
)
_PERMISSION_FIELDS = (
    "paper_allowed",
    "live_allowed",
    "private_endpoint_allowed",
    "order_endpoint_allowed",
    "withdraw_allowed",
)


class ManualApprovalObserverError(ValueError):
    """Raised when an approval fact is not safe to record."""


def build_manual_approval_fact(
    *,
    reviewer: str,
    approval_ticket: str,
    approved_at_utc: datetime,
    account_hash_sha256: str,
    permission_conclusion: Mapping[str, bool],
    source_head: str,
    approval_decision: str = "approved",
) -> dict[str, Any]:
    """Build a hash-bound fact supplied by a reviewer; this does not approve."""

    approved_at = _ensure_utc(approved_at_utc)
    fact: dict[str, Any] = {
        "schema_version": "btc_demo_manual_approval_fact_v1",
        "reviewer": reviewer.strip(),
        "approval_ticket": approval_ticket.strip(),
        "approved_at_utc": approved_at.isoformat(),
        "account_hash_sha256": account_hash_sha256,
        "permission_conclusion": dict(permission_conclusion),
        "source_head": source_head,
        "approval_decision": approval_decision,
    }
    fact["fact_sha256"] = stable_payload_hash(fact)
    return fact


def build_btc_demo_manual_approval_observer(
    *,
    approval_fact: Mapping[str, Any] | None,
    source_head: str,
    run_id: str,
    generated_at_utc: datetime,
    max_age_seconds: int = 7 * 24 * 60 * 60,
) -> dict[str, Any]:
    """Validate an independently approved fact without granting permission."""

    generated = _ensure_utc(generated_at_utc)
    blockers: list[str] = []
    sanitized_fact: dict[str, Any] | None = None
    if approval_fact is None:
        blockers.append(MANUAL_APPROVAL_BLOCKER)
    else:
        blockers.extend(
            validate_manual_approval_fact(
                approval_fact,
                expected_source_head=source_head,
                generated_at_utc=generated,
                max_age_seconds=max_age_seconds,
            )
        )
        sanitized_fact = _sanitize_fact(approval_fact)
    recorded = approval_fact is not None and not blockers
    status = (
        "recorded_review_only"
        if recorded
        else (
            "awaiting_manual_approval"
            if approval_fact is None
            else "blocked_invalid_manual_approval_fact"
        )
    )
    decision = (
        "manual_approval_fact_recorded_no_runtime_unlock"
        if recorded
        else "blocked_fail_closed_no_demo_no_private_no_order"
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "decision": decision,
        "run_id": run_id,
        "source_head": source_head,
        "code_commit": source_head,
        "generated_at_utc": generated.isoformat(),
        "manual_approval_recorded": recorded,
        "manual_review_missing_cleared": recorded,
        "approval_record": sanitized_fact,
        "observer_contract": {
            "observer_can_approve": False,
            "observer_can_enable_runtime": False,
            "approval_may_be_inferred_from_code_completion": False,
            "secret_or_sensitive_screenshot_storage_allowed": False,
            "only_hash_bound_reviewer_fact_recorded": True,
        },
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "blockers": list(dict.fromkeys(blockers)),
        "safety": safety_flags(),
    }
    report["artifact_hash"] = stable_payload_hash(report)
    return report


def validate_manual_approval_fact(
    fact: Mapping[str, Any],
    *,
    expected_source_head: str,
    generated_at_utc: datetime,
    max_age_seconds: int,
) -> list[str]:
    blockers: list[str] = []
    if _contains_forbidden_field(fact):
        blockers.append("manual_approval_forbidden_sensitive_field_present")
    if fact.get("schema_version") != "btc_demo_manual_approval_fact_v1":
        blockers.append("manual_approval_fact_schema_mismatch")
    if not str(fact.get("reviewer") or "").strip():
        blockers.append("manual_approval_reviewer_missing")
    if not str(fact.get("approval_ticket") or "").strip():
        blockers.append("manual_approval_ticket_missing")
    source_head = str(fact.get("source_head") or "")
    if not _HEX_HEAD.fullmatch(source_head):
        blockers.append("manual_approval_source_head_invalid")
    elif source_head != expected_source_head:
        blockers.append("manual_approval_source_head_mismatch")
    account_hash = str(fact.get("account_hash_sha256") or "")
    if not _SHA256.fullmatch(account_hash):
        blockers.append("manual_approval_account_hash_invalid")
    approved_at = _parse_utc(fact.get("approved_at_utc"))
    if approved_at is None:
        blockers.append("manual_approval_time_invalid")
    else:
        age_seconds = (generated_at_utc - approved_at).total_seconds()
        if age_seconds < 0:
            blockers.append("manual_approval_time_in_future")
        elif age_seconds > max_age_seconds:
            blockers.append("manual_approval_fact_stale")
    if fact.get("approval_decision") != "approved":
        blockers.append("manual_approval_decision_not_approved")
    permissions = fact.get("permission_conclusion")
    if not isinstance(permissions, Mapping):
        blockers.append("manual_approval_permission_conclusion_missing")
    else:
        for field in _PERMISSION_FIELDS:
            if not isinstance(permissions.get(field), bool):
                blockers.append(
                    f"manual_approval_permission_boolean_required:{field}"
                )
        if permissions.get("withdraw_allowed") is not False:
            blockers.append("manual_approval_withdraw_must_remain_disabled")
    recorded_hash = str(fact.get("fact_sha256") or "")
    if not _SHA256.fullmatch(recorded_hash):
        blockers.append("manual_approval_fact_hash_invalid")
    elif (
        stable_payload_hash(fact, exclude={"fact_sha256"})
        != recorded_hash
    ):
        blockers.append("manual_approval_fact_hash_mismatch")
    return list(dict.fromkeys(blockers))


def append_manual_approval_fact(
    *,
    ledger_path: Path,
    approval_fact: Mapping[str, Any],
    expected_source_head: str,
    generated_at_utc: datetime,
    max_age_seconds: int = 7 * 24 * 60 * 60,
) -> dict[str, Any]:
    blockers = validate_manual_approval_fact(
        approval_fact,
        expected_source_head=expected_source_head,
        generated_at_utc=_ensure_utc(generated_at_utc),
        max_age_seconds=max_age_seconds,
    )
    if blockers:
        raise ManualApprovalObserverError(blockers[0])
    existing = _read_jsonl(ledger_path)
    fact_hash = str(approval_fact["fact_sha256"])
    if any(row.get("fact_sha256") == fact_hash for row in existing):
        return {
            "appended": False,
            "duplicate": True,
            "fact_sha256": fact_hash,
            "ledger_row_count": len(existing),
        }
    ticket = str(approval_fact["approval_ticket"])
    if any(str(row.get("approval_ticket")) == ticket for row in existing):
        raise ManualApprovalObserverError(
            "manual_approval_ticket_fact_conflict"
        )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                _sanitize_fact(approval_fact),
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        handle.flush()
    return {
        "appended": True,
        "duplicate": False,
        "fact_sha256": fact_hash,
        "ledger_row_count": len(existing) + 1,
    }


def write_btc_demo_manual_approval_observer_evidence(
    *,
    report: Mapping[str, Any],
    output_root: Path,
    run_id: str,
) -> dict[str, Any]:
    """Write an immutable review artifact without a latest pointer."""

    run_directory = output_root / "runs" / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    report_path = run_directory / "btc_demo_manual_approval_observer_report.json"
    report_bytes = (
        json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    report_path.write_bytes(report_bytes)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "source_head": report.get("source_head"),
        "generated_at_utc": report.get("generated_at_utc"),
        "immutable": True,
        "latest_pointer_updated": False,
        "report_path": report_path.name,
        "report_sha256": report_sha256,
        "status": report.get("status"),
        "decision": report.get("decision"),
        "manual_approval_recorded": (
            report.get("manual_approval_recorded") is True
        ),
        "promotion_evidence_ready": False,
        "blockers": list(report.get("blockers") or []),
        "safety": safety_flags(),
    }
    manifest_path = run_directory / "manifest.json"
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    return {
        "run_directory": str(run_directory),
        "report_path": str(report_path),
        "report_sha256": report_sha256,
        "manifest_path": str(manifest_path),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "latest_pointer_updated": False,
    }


def _sanitize_fact(fact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": fact.get("schema_version"),
        "reviewer": fact.get("reviewer"),
        "approval_ticket": fact.get("approval_ticket"),
        "approved_at_utc": fact.get("approved_at_utc"),
        "account_hash_sha256": fact.get("account_hash_sha256"),
        "permission_conclusion": dict(
            fact.get("permission_conclusion") or {}
        ),
        "source_head": fact.get("source_head"),
        "approval_decision": fact.get("approval_decision"),
        "fact_sha256": fact.get("fact_sha256"),
    }


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(token in normalized for token in _FORBIDDEN_KEY_TOKENS):
                return True
            if _contains_forbidden_field(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ManualApprovalObserverError(
                f"manual_approval_ledger_invalid:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ManualApprovalObserverError(
                f"manual_approval_ledger_object_required:{line_number}"
            )
        rows.append(row)
    return rows


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ManualApprovalObserverError("timezone_aware_datetime_required")
    return value.astimezone(timezone.utc)
