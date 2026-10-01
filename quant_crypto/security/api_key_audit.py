from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from quant_shared.core.time import ensure_utc

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_API_KEY_PERMISSION_AUDIT_VERSION = "btc_api_key_permission_audit_v1"
SECRET_FIELD_TOKENS = ("key", "secret", "passphrase", "signature", "token", "authorization", "auth_header")
REDACTED_RECORD_FIELDS = frozenset({
    "key_class",
    "venue",
    "mode",
    "permission_read",
    "permission_trade",
    "permission_withdraw",
    "ip_allowlist_configured",
    "environment_target",
    "account_label",
    "redacted_identifier",
    "withdraw_permission_verified_false",
    "redaction_confirmed",
    "manual_approval_id",
    "reviewed_at_utc",
    "expires_at_utc",
    "raw_metadata",
})


class BTCAPIKeyClass(str, Enum):
    DATA_READONLY = "data_readonly"
    PAPER_TRADE = "paper_trade"
    LIVE_TRADE = "live_trade"
    ADMIN_MANUAL = "admin_manual"


@dataclass(frozen=True)
class BTCAPIKeyPermissionRecord:
    key_class: BTCAPIKeyClass
    venue: str
    mode: str
    permission_read: bool
    permission_trade: bool
    permission_withdraw: bool
    ip_allowlist_configured: bool
    environment_target: str
    account_label: str = ""
    redacted_identifier: str = ""
    withdraw_permission_verified_false: bool = False
    redaction_confirmed: bool = False
    manual_approval_id: str = ""
    reviewed_at_utc: str = ""
    expires_at_utc: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.key_class, BTCAPIKeyClass):
            object.__setattr__(self, "key_class", BTCAPIKeyClass(str(self.key_class)))
        if not self.venue:
            raise ValueError("BTC API key audit venue is required.")
        if self.mode not in {"read_only", "paper", "live"}:
            raise ValueError("BTC API key audit mode must be read_only/paper/live.")

    def blockers(self, *, generated_at_utc: datetime | None = None) -> list[str]:
        blockers: list[str] = []
        if self.permission_withdraw:
            blockers.append(f"btc_api_key_withdraw_permission_enabled:{self.key_class.value}")
        if not self.withdraw_permission_verified_false:
            blockers.append(f"btc_api_key_withdraw_false_not_attested:{self.key_class.value}")
        if not self.redaction_confirmed:
            blockers.append(f"btc_api_key_redaction_not_confirmed:{self.key_class.value}")
        if not self.redacted_identifier or "****" not in self.redacted_identifier:
            blockers.append(f"btc_api_key_redacted_identifier_missing_or_not_redacted:{self.key_class.value}")
        if not str(self.manual_approval_id or "").strip():
            blockers.append(f"btc_api_key_manual_approval_id_missing:{self.key_class.value}")
        reviewed_at = _parse_utc(self.reviewed_at_utc)
        if reviewed_at is None:
            blockers.append(f"btc_api_key_reviewed_at_missing_or_invalid:{self.key_class.value}")
        expires_at = _parse_utc(self.expires_at_utc)
        if expires_at is None:
            blockers.append(f"btc_api_key_attestation_expiry_missing_or_invalid:{self.key_class.value}")
        elif generated_at_utc is not None and expires_at <= ensure_utc(generated_at_utc):
            blockers.append(f"btc_api_key_attestation_expired:{self.key_class.value}")
        if self.key_class == BTCAPIKeyClass.DATA_READONLY and self.permission_trade:
            blockers.append("btc_api_key_data_readonly_has_trade_permission")
        if self.key_class == BTCAPIKeyClass.LIVE_TRADE and not self.ip_allowlist_configured:
            blockers.append("btc_api_key_live_trade_ip_allowlist_missing")
        if self.key_class == BTCAPIKeyClass.ADMIN_MANUAL:
            blockers.append("btc_api_key_admin_manual_must_not_be_loaded_by_bot")
        expected_mode = {
            BTCAPIKeyClass.DATA_READONLY: "read_only",
            BTCAPIKeyClass.PAPER_TRADE: "paper",
            BTCAPIKeyClass.LIVE_TRADE: "live",
            BTCAPIKeyClass.ADMIN_MANUAL: "manual",
        }[self.key_class]
        if expected_mode != "manual" and self.mode != expected_mode:
            blockers.append(f"btc_api_key_mode_mismatch:{self.key_class.value}:{self.mode}")
        if expected_mode != "manual" and self.environment_target != self.mode:
            blockers.append(f"btc_api_key_environment_target_mismatch:{self.key_class.value}")
        if _contains_secret_like_value(self.raw_metadata):
            blockers.append(f"btc_api_key_audit_metadata_contains_secret_like_field:{self.key_class.value}")
        return blockers

    def to_redacted_dict(self) -> dict[str, Any]:
        return {
            "key_class": self.key_class.value,
            "venue": self.venue,
            "mode": self.mode,
            "permission_read": bool(self.permission_read),
            "permission_trade": bool(self.permission_trade),
            "permission_withdraw": bool(self.permission_withdraw),
            "ip_allowlist_configured": bool(self.ip_allowlist_configured),
            "environment_target": self.environment_target,
            "account_label": self.account_label,
            "redacted_identifier": self.redacted_identifier,
            "withdraw_permission_verified_false": bool(self.withdraw_permission_verified_false),
            "redaction_confirmed": bool(self.redaction_confirmed),
            "manual_approval_id": self.manual_approval_id,
            "reviewed_at_utc": self.reviewed_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "metadata_keys": sorted(str(key) for key in self.raw_metadata),
        }


def build_btc_api_key_permission_audit(
    *,
    records: list[BTCAPIKeyPermissionRecord],
    generated_at_utc: datetime,
    expected_venue: str = "binance_usdm_or_okx",
    preflight_blockers: list[str] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = list(preflight_blockers or [])
    if not records:
        blockers.append("btc_api_key_permission_redacted_records_missing")
    key_classes = {record.key_class for record in records}
    for required in (BTCAPIKeyClass.DATA_READONLY, BTCAPIKeyClass.PAPER_TRADE, BTCAPIKeyClass.LIVE_TRADE):
        if required not in key_classes:
            blockers.append(f"btc_api_key_class_missing:{required.value}")
    for record in records:
        blockers.extend(record.blockers(generated_at_utc=generated_at_utc))
    redacted_records = [record.to_redacted_dict() for record in records]
    keys_separated = _classes_separated(records)
    if records and not keys_separated:
        blockers.append("btc_api_key_data_paper_live_keys_not_separated")
    payload = {
        "api_key_permission_audit_version": BTC_API_KEY_PERMISSION_AUDIT_VERSION,
        "status": "complete" if not blockers else "blocked",
        "expected_venue": expected_venue,
        "records": redacted_records,
        "secret_values_inspected": False,
        "secret_values_output": False,
        "withdraw_permission_allowed": False,
        "data_paper_live_keys_separated": keys_separated,
        "manual_approval_fields_verified": _manual_approval_fields_verified(records, generated_at_utc=generated_at_utc),
        "all_records_unexpired": _all_records_unexpired(records, generated_at_utc=generated_at_utc),
        "all_records_redacted": all(record.redaction_confirmed and "****" in record.redacted_identifier for record in records),
        "live_orders_allowed": False,
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="api_key_permissions_ready_for_paper_only" if not blockers else "api_key_permissions_block_live",
        generated_at_utc=ensure_utc(generated_at_utc),
        as_of_utc=ensure_utc(generated_at_utc),
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={"permission_records": stable_payload_hash(redacted_records)},
    )


def build_btc_api_key_permission_records_template() -> dict[str, Any]:
    return {
        "repository_default_fail_closed": True,
        "all_permissions_enabled": False,
        "all_approvals_completed": False,
        "records": [
            {
                "key_class": "data_readonly",
                "venue": "okx",
                "mode": "read_only",
                "permission_read": False,
                "permission_trade": False,
                "permission_withdraw": False,
                "ip_allowlist_configured": False,
                "environment_target": "read_only",
                "account_label": "btc-data-readonly",
                "redacted_identifier": "",
                "withdraw_permission_verified_false": False,
                "redaction_confirmed": False,
                "manual_approval_id": "",
                "reviewed_at_utc": "",
                "expires_at_utc": "",
                "raw_metadata": {"note": "repository default is disabled; redacted permission facts only"},
            },
            {
                "key_class": "paper_trade",
                "venue": "okx",
                "mode": "paper",
                "permission_read": False,
                "permission_trade": False,
                "permission_withdraw": False,
                "ip_allowlist_configured": False,
                "environment_target": "paper",
                "account_label": "btc-paper-trade",
                "redacted_identifier": "",
                "withdraw_permission_verified_false": False,
                "redaction_confirmed": False,
                "manual_approval_id": "",
                "reviewed_at_utc": "",
                "expires_at_utc": "",
                "raw_metadata": {"note": "repository default is disabled; no paper permission is granted"},
            },
            {
                "key_class": "live_trade",
                "venue": "okx",
                "mode": "live",
                "permission_read": False,
                "permission_trade": False,
                "permission_withdraw": False,
                "ip_allowlist_configured": False,
                "environment_target": "live",
                "account_label": "btc-live-trade",
                "redacted_identifier": "",
                "withdraw_permission_verified_false": False,
                "redaction_confirmed": False,
                "manual_approval_id": "",
                "reviewed_at_utc": "",
                "expires_at_utc": "",
                "raw_metadata": {"note": "repository default is disabled; no live permission is granted"},
            },
        ],
        "template_rules": [
            "Repository defaults grant no read, trade, withdraw, paper, or live permission.",
            "Repository defaults contain no approval or attestation.",
            "Only enter redacted permission facts.",
            "Do not include API key, secret, passphrase, token, signature, authorization header, or private account identifiers.",
            "Keep data_readonly, paper_trade, and live_trade as separate redacted identifiers.",
            "Set withdraw_permission_verified_false=true only after confirming withdraw=false on the exchange UI.",
            "Fill manual_approval_id, reviewed_at_utc, and expires_at_utc; expired records are fail-closed.",
        ],
    }


def find_secret_like_record_fields(row: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for key, value in row.items():
        key_text = str(key)
        if key_text not in REDACTED_RECORD_FIELDS and _is_secret_field_name(key_text):
            findings.append(key_text)
        if key_text == "raw_metadata":
            findings.extend(f"raw_metadata.{path}" for path in _find_secret_like_paths(value))
    return _dedupe(findings)


def _classes_separated(records: list[BTCAPIKeyPermissionRecord]) -> bool:
    identifiers = [record.redacted_identifier for record in records if record.key_class != BTCAPIKeyClass.ADMIN_MANUAL]
    return bool(identifiers) and len(identifiers) == len(set(identifiers))


def _manual_approval_fields_verified(
    records: list[BTCAPIKeyPermissionRecord],
    *,
    generated_at_utc: datetime,
) -> bool:
    return bool(records) and all(
        bool(str(record.manual_approval_id or "").strip())
        and _parse_utc(record.reviewed_at_utc) is not None
        and (_parse_utc(record.expires_at_utc) or generated_at_utc) > ensure_utc(generated_at_utc)
        for record in records
    )


def _all_records_unexpired(records: list[BTCAPIKeyPermissionRecord], *, generated_at_utc: datetime) -> bool:
    generated = ensure_utc(generated_at_utc)
    return bool(records) and all((expires := _parse_utc(record.expires_at_utc)) is not None and expires > generated for record in records)


def _contains_secret_like_value(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if any(token in str(key).lower() for token in SECRET_FIELD_TOKENS):
                return True
            if _contains_secret_like_value(nested):
                return True
    if isinstance(value, list):
        return any(_contains_secret_like_value(item) for item in value)
    return False


def _find_secret_like_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_secret_field_name(key_text):
                findings.append(path)
            findings.extend(_find_secret_like_paths(nested, path))
    if isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            findings.extend(_find_secret_like_paths(item, path))
    return findings


def _is_secret_field_name(value: str) -> bool:
    return any(token in value.lower() for token in SECRET_FIELD_TOKENS)


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
