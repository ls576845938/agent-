"""Authoritative BTC Demo start-attempt identity and policy binding.

The browser may describe an intent, but it never supplies the identity that
authorizes a Demo start.  This small application-owned aggregate is shared by
the backend adapter and the paper-runtime controller so an outer operator
operation and its inner runtime operation project one immutable attempt.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


START_ATTEMPT_SCHEMA_VERSION = "btc_demo_start_attempt_v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_PROFILE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
_ACCOUNT_IDENTITY_DOMAIN = "btc-okx-demo-account-identity-v1"
_ACCOUNT_IDENTITY_HASH_SOURCE = "okx_demo_account_config_uid_main_uid"
ACCOUNT_IDENTITY_HASH_SOURCE = _ACCOUNT_IDENTITY_HASH_SOURCE


def _utc(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        return raw
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Any) -> str:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if not decimal.is_finite() or decimal <= 0:
        return ""
    return format(decimal.normalize(), "f")


def account_identity_hash(identity: str) -> str:
    """Hash an opaque account namespace; raw account/credential IDs never persist."""

    value = str(identity or "").strip()
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def authoritative_account_identity_snapshot(
    account_config: Mapping[str, Any],
    *,
    captured_at_utc: Any = "",
) -> dict[str, str]:
    """Project an OKX Demo account-config identity without retaining raw IDs.

    ``uid``/``mainUid`` are the only accepted identity inputs.  Credential
    service names, instruments, balances, permissions, and browser payloads
    are deliberately not accepted because they are namespaces or mutable
    properties rather than account identity.  The returned projection is the
    only shape allowed into runtime state, status, events, or operator read
    models.
    """

    if not isinstance(account_config, Mapping):
        return {"hash": "", "source": "", "captured_at_utc": ""}
    uid = str(account_config.get("uid") or "").strip()
    main_uid = str(account_config.get("mainUid") or account_config.get("main_uid") or "").strip()
    if not uid and not main_uid:
        return {"hash": "", "source": "", "captured_at_utc": ""}
    canonical = "|".join(
        (
            _ACCOUNT_IDENTITY_DOMAIN,
            "exchange=okx",
            "environment=demo",
            f"uid={uid}",
            f"main_uid={main_uid}",
        )
    )
    raw_timestamp = str(captured_at_utc or "")
    return {
        "hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "source": _ACCOUNT_IDENTITY_HASH_SOURCE,
        "captured_at_utc": raw_timestamp,
    }


def is_authoritative_account_identity_hash(value: Any) -> bool:
    """Return whether a value is a valid projected account identity digest."""

    return bool(_HEX64.fullmatch(str(value or "").strip().lower()))


def effective_policy_digest(policy: Mapping[str, Any]) -> str:
    """Hash only server-owned policy facts, excluding credentials and keys."""

    canonical = json.dumps(dict(policy), ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StartAttemptBinding:
    parent_operation_id: str
    inner_operation_id: str
    attempt_id: str
    runtime_identity: str
    source_head: str
    effective_policy_digest: str
    risk_profile: str
    expected_leverage: str
    account_identity_hash: str
    created_at_utc: str
    updated_at_utc: str
    state: str = "queued"
    phase: str = "requested"
    current_attempt: bool = True
    historical: bool = False
    historical_reason_codes: tuple[str, ...] = ()
    actual_long_leverage: str = ""
    actual_short_leverage: str = ""

    def __post_init__(self) -> None:
        if not self.parent_operation_id or not self.inner_operation_id or not self.attempt_id:
            raise ValueError("btc_demo_start_attempt_identity_missing")
        if not _IDENTITY.fullmatch(self.runtime_identity):
            raise ValueError("btc_demo_start_attempt_runtime_identity_invalid")
        if not _HEX40.fullmatch(self.source_head):
            raise ValueError("btc_demo_start_attempt_source_head_invalid")
        if not _HEX64.fullmatch(self.effective_policy_digest):
            raise ValueError("btc_demo_start_attempt_policy_digest_invalid")
        if not _PROFILE.fullmatch(self.risk_profile):
            raise ValueError("btc_demo_start_attempt_risk_profile_invalid")
        if not _decimal_text(self.expected_leverage):
            raise ValueError("btc_demo_start_attempt_expected_leverage_invalid")
        if not _HEX64.fullmatch(self.account_identity_hash):
            raise ValueError("btc_demo_start_attempt_account_identity_hash_invalid")
        for timestamp in (self.created_at_utc, self.updated_at_utc):
            if not _utc(timestamp) or "T" not in _utc(timestamp):
                raise ValueError("btc_demo_start_attempt_timestamp_invalid")
        if self.historical and self.current_attempt:
            raise ValueError("btc_demo_start_attempt_current_historical_conflict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": START_ATTEMPT_SCHEMA_VERSION,
            "parent_operation_id": self.parent_operation_id,
            "inner_operation_id": self.inner_operation_id,
            "attempt_id": self.attempt_id,
            "runtime_identity": self.runtime_identity,
            "source_head": self.source_head,
            "effective_policy_digest": self.effective_policy_digest,
            "risk_profile": self.risk_profile,
            "expected_leverage": self.expected_leverage,
            "account_identity_hash": self.account_identity_hash,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "state": self.state,
            "phase": self.phase,
            "current_attempt": self.current_attempt,
            "historical": self.historical,
            "historical_reason_codes": list(self.historical_reason_codes),
            "actual_long_leverage": self.actual_long_leverage or None,
            "actual_short_leverage": self.actual_short_leverage or None,
        }

    def with_projection(self, *, current_identity: Mapping[str, Any] | None) -> "StartAttemptBinding":
        """Project current/history without changing immutable policy identity."""

        identity = current_identity or {}
        expected = (
            str(identity.get("runtime_identity") or ""),
            str(identity.get("source_head") or ""),
            str(identity.get("effective_policy_digest") or ""),
            str(identity.get("risk_profile") or ""),
            _decimal_text(identity.get("expected_leverage")),
            str(identity.get("account_identity_hash") or ""),
        )
        actual = (
            self.runtime_identity,
            self.source_head,
            self.effective_policy_digest,
            self.risk_profile,
            _decimal_text(self.expected_leverage),
            self.account_identity_hash,
        )
        same = bool(all(expected)) and expected == actual
        reasons = list(self.historical_reason_codes)
        if not same:
            comparisons = (
                ("runtime_identity", "runtime_identity_changed"),
                ("source_head", "source_head_changed"),
                ("effective_policy_digest", "effective_policy_digest_changed"),
                ("risk_profile", "risk_profile_changed"),
                ("expected_leverage", "expected_leverage_changed"),
                ("account_identity", "account_identity_changed"),
            )
            indexes = {
                "runtime_identity": 0,
                "source_head": 1,
                "effective_policy_digest": 2,
                "risk_profile": 3,
                "expected_leverage": 4,
                "account_identity": 5,
            }
            for key, code in comparisons:
                index = indexes[key]
                if not expected[index] or expected[index] != actual[index]:
                    reasons.append(code)
        return replace(
            self,
            current_attempt=same and not self.historical,
            historical=self.historical or not same,
            historical_reason_codes=tuple(dict.fromkeys(reasons)),
        )


def build_effective_policy(
    *,
    source_head: str,
    runtime_identity: str,
    risk_profile: str,
    expected_leverage: Any,
    account_identity_hash_value: str,
    instrument_id: str,
    margin_mode: str,
    order_contracts: Any,
    max_net_contracts: Any,
    max_notional_usdt: Any,
    protection_policy: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    policy = {
        "source_head": source_head,
        "runtime_identity": runtime_identity,
        "risk_profile": risk_profile,
        "expected_leverage": _decimal_text(expected_leverage),
        "account_identity_hash": account_identity_hash_value,
        "instrument_id": instrument_id,
        "margin_mode": margin_mode,
        "order_contracts": _decimal_text(order_contracts),
        "max_net_contracts": _decimal_text(max_net_contracts),
        "max_notional_usdt": _decimal_text(max_notional_usdt),
        "server_side_protection_policy": dict(protection_policy),
    }
    return policy, effective_policy_digest(policy)


__all__ = [
    "START_ATTEMPT_SCHEMA_VERSION",
    "ACCOUNT_IDENTITY_HASH_SOURCE",
    "StartAttemptBinding",
    "account_identity_hash",
    "authoritative_account_identity_snapshot",
    "build_effective_policy",
    "effective_policy_digest",
    "is_authoritative_account_identity_hash",
]
