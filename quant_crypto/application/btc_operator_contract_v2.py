"""Application-owned operator contract for the BTC Demo runtime.

This module deliberately contains no transport, broker, OMS, backend, clock,
or persistence dependency.  It turns an already authoritative runtime status
snapshot into immutable, machine-readable action authorizations.  A missing or
malformed identity is never inferred from a caller supplied boolean.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Sequence


OPERATOR_CONTRACT_SCHEMA_VERSION = "btc_demo_operator_contract_v2"
OPERATION_READ_MODEL_SCHEMA_VERSION = "btc_demo_operation_read_model_v2"

ALLOWLISTED_OPERATOR_ACTIONS: tuple[str, ...] = (
    "authoritative_preflight_start",
    "refresh_account_snapshot",
    "stop_keep_position",
    "stop_and_flatten",
    "enter_cancel_only",
    "emergency_reduce_only_exit",
    "acknowledge_guardian_trip",
    "recover_guardian_after_fresh_preflight",
)
MUTATING_OPERATOR_ACTIONS = frozenset(ALLOWLISTED_OPERATOR_ACTIONS)
OPERATION_STATES = frozenset(
    {"queued", "running", "succeeded", "failed", "blocked", "interrupted", "timed_out"}
)
TERMINAL_OPERATION_STATES = frozenset(
    {"succeeded", "failed", "blocked", "interrupted", "timed_out"}
)
SAFETY_FLAGS: tuple[str, ...] = (
    "promotion_eligible",
    "paper",
    "live",
    "private",
    "order",
    "real_order",
    "transfer",
    "withdraw",
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
_REDACT_KEYS = {
    "api_key",
    "apikey",
    "api_secret",
    "authorization",
    "access_token",
    "client_secret",
    "credential",
    "credentials",
    "idempotency_key",
    "passphrase",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "secret_key",
    "token",
}


class OperatorContractError(ValueError):
    """Stable error raised before an operator mutation is dispatched."""

    def __init__(
        self,
        code: str,
        *,
        blockers: Sequence[str] = (),
        reasons: Sequence[str] = (),
        status_code: int = 400,
    ) -> None:
        self.code = _stable_code(code) or "operator_contract_invalid"
        self.blockers = _stable_codes((*blockers, self.code))
        self.reasons = _stable_codes(reasons)
        self.status_code = status_code
        super().__init__(self.code)


def _stable_code(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.lower()
    if raw != normalized:
        return ""
    return normalized if _CODE.fullmatch(normalized) else ""


def _stable_codes(values: Sequence[Any]) -> tuple[str, ...]:
    codes = {_stable_code(value) for value in values}
    return tuple(sorted(code for code in codes if code))


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(nested) for key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def _deep_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_copy(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_copy(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_deep_copy(item) for item in value]
    return value


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _normalize_utc_timestamp(value: Any) -> str:
    """Normalize an authoritative offset-aware timestamp without using wall clock."""

    if not isinstance(value, str) or not value.strip():
        return str(value or "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _valid_source_head(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX40.fullmatch(value))


def _valid_state_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text_codes(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return _stable_codes((value,)) or (("blocker_code_invalid",) if value.strip() else ())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        raw = tuple(value)
        normalized = _stable_codes(raw)
        invalid = any(_stable_code(item) == "" and str(item or "").strip() for item in raw)
        return _stable_codes((*normalized, "blocker_code_invalid" if invalid else ""))
    return ()


def validate_idempotency_key(value: Any) -> bool:
    """Return true only for a non-empty allowlisted key shape."""

    return isinstance(value, str) and bool(_IDEMPOTENCY.fullmatch(value.strip()))


def _canonical_value(value: Any, *, key: str = "") -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for original_name, nested in sorted(value.items(), key=lambda item: str(item[0])):
            name = str(original_name)
            if name.lower() in _REDACT_KEYS:
                continue
            result[name] = _canonical_value(nested, key=name)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical_value(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_request_digest(payload: Mapping[str, Any] | None) -> str:
    """Hash canonical payload facts, excluding credentials and idempotency keys."""

    normalized = _canonical_value(payload or {})
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _status_identity(
    status: Mapping[str, Any],
) -> tuple[str, str, str, int | None, str, tuple[str, ...]]:
    runtime = _mapping(status.get("runtime"))
    start_operation = _mapping(status.get("start_operation") or runtime.get("start_operation"))
    # A persisted start operation records historical provenance, not the code
    # identity of the service currently projecting this contract.  The
    # backend adapter must bind the top-level source_head to its current repo
    # HEAD; accepting this nested field here would let an old restart attempt
    # masquerade as the current runtime.
    source_head = str(
        status.get("source_head")
        or runtime.get("source_head")
        or ""
    )
    state_digest = str(
        status.get("state_digest")
        or runtime.get("state_digest")
        or status.get("runtime_state_digest")
        or ""
    )
    runtime_identity = str(
        status.get("runtime_identity")
        or runtime.get("runtime_identity")
        or runtime.get("run_id")
        or ""
    ).strip()
    raw_revision = status.get("state_revision", runtime.get("state_revision"))
    if raw_revision is None:
        raw_revision = status.get("revision")
    try:
        state_revision = int(raw_revision)
    except (TypeError, ValueError):
        state_revision = None
    raw_as_of = str(
        status.get("as_of_utc")
        or runtime.get("as_of_utc")
        or status.get("captured_at_utc")
        or runtime.get("last_heartbeat_utc")
        or runtime.get("stopped_at_utc")
        or runtime.get("started_at_utc")
        or start_operation.get("updated_at_utc")
        or start_operation.get("created_at_utc")
        or ""
    )
    as_of = _normalize_utc_timestamp(raw_as_of)
    # Runtime/risk/WS/ledger blockers are action facts, not identity facts.
    # They must be classified per action below; folding them into this tuple
    # would incorrectly disable recovery and risk-reduction actions.
    return source_head, state_digest, runtime_identity, state_revision, as_of, ()


@dataclass(frozen=True, slots=True)
class OperatorAuthorizationRecord:
    action: str
    allowed: bool
    blocker_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source: str
    runtime_identity: str
    state_revision: int | None
    state_digest: str
    as_of_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocker_codes", _stable_codes(self.blocker_codes))
        object.__setattr__(self, "reason_codes", _stable_codes(self.reason_codes))

    @property
    def execution_permission(self) -> bool:
        return bool(self.allowed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "allowed": self.allowed,
            "execution_permission": self.execution_permission,
            "blocker_codes": list(self.blocker_codes),
            "reason_codes": list(self.reason_codes),
            "source": self.source,
            "runtime_identity": self.runtime_identity,
            "state_revision": self.state_revision,
            "state_digest": self.state_digest,
            "as_of_utc": self.as_of_utc,
        }


@dataclass(frozen=True, slots=True)
class OperationReadModel:
    operation_id: str
    action: str
    request_digest: str
    state: str
    phase: str
    blocker_codes: tuple[str, ...]
    created_at_utc: str
    updated_at_utc: str
    state_revision: int
    result_present: bool = False
    retryable: bool = False
    replayed: bool = False
    idempotent_replay: bool = False
    acknowledged: bool = False
    acknowledged_at_utc: str | None = None
    safety_flags: Mapping[str, bool] = field(
        default_factory=lambda: {name: False for name in SAFETY_FLAGS}
    )
    start_attempt: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in MUTATING_OPERATOR_ACTIONS or not self.operation_id:
            raise ValueError("operator_operation_identity_invalid")
        if self.state not in OPERATION_STATES:
            raise ValueError("operator_operation_state_invalid")
        if not _valid_state_digest(self.request_digest):
            raise ValueError("operator_operation_request_digest_invalid")
        if not _valid_utc_timestamp(self.created_at_utc) or not _valid_utc_timestamp(self.updated_at_utc):
            raise ValueError("operator_operation_timestamp_invalid")
        if self.state_revision < 0:
            raise ValueError("operator_operation_revision_invalid")
        if type(self.acknowledged) is not bool:
            raise ValueError("operator_operation_acknowledgement_invalid")
        if self.acknowledged:
            if not _valid_utc_timestamp(self.acknowledged_at_utc):
                raise ValueError("operator_operation_acknowledgement_timestamp_invalid")
        elif self.acknowledged_at_utc is not None:
            raise ValueError("operator_operation_acknowledgement_timestamp_invalid")
        flags = {name: bool(_mapping(self.safety_flags).get(name, False)) for name in SAFETY_FLAGS}
        if any(flags.values()):
            raise ValueError("operator_operation_safety_flag_enabled")
        attempt = _mapping(self.start_attempt)
        if self.action != "authoritative_preflight_start" and attempt:
            raise ValueError("operator_non_start_attempt_binding_invalid")
        if attempt:
            required_attempt = (
                "parent_operation_id", "inner_operation_id", "attempt_id",
                "runtime_identity", "source_head", "effective_policy_digest",
                "risk_profile", "expected_leverage", "account_identity_hash",
                "created_at_utc", "updated_at_utc",
            )
            if any(not str(attempt.get(name) or "").strip() for name in required_attempt):
                raise ValueError("operator_start_attempt_binding_invalid")
            if not _valid_source_head(attempt.get("source_head")) or not _valid_state_digest(attempt.get("effective_policy_digest")) or not _valid_state_digest(attempt.get("account_identity_hash")):
                raise ValueError("operator_start_attempt_binding_invalid")
            if not _valid_utc_timestamp(attempt.get("created_at_utc")) or not _valid_utc_timestamp(attempt.get("updated_at_utc")):
                raise ValueError("operator_start_attempt_binding_invalid")
            if attempt.get("current_attempt") is not True and attempt.get("current_attempt") is not False:
                raise ValueError("operator_start_attempt_binding_invalid")
            if attempt.get("historical") is not True and attempt.get("historical") is not False:
                raise ValueError("operator_start_attempt_binding_invalid")
            if attempt.get("historical") is True and attempt.get("current_attempt") is True:
                raise ValueError("operator_start_attempt_binding_invalid")
        object.__setattr__(self, "blocker_codes", _stable_codes(self.blocker_codes))
        if self.state in TERMINAL_OPERATION_STATES:
            object.__setattr__(self, "result_present", True)
        object.__setattr__(self, "safety_flags", _deep_freeze(flags))
        object.__setattr__(self, "start_attempt", _deep_freeze(self.start_attempt))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OPERATION_READ_MODEL_SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "action": self.action,
            "request_digest": self.request_digest,
            "state": self.state,
            "phase": self.phase,
            "blocker_codes": list(self.blocker_codes),
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "state_revision": self.state_revision,
            "result_present": self.result_present,
            "retryable": self.retryable,
            "replayed": self.replayed,
            "idempotent_replay": self.idempotent_replay,
            "acknowledged": self.acknowledged,
            "acknowledged_at_utc": self.acknowledged_at_utc,
            "safety_flags": _deep_copy(self.safety_flags),
            # Empty objects are not an optional-value encoding.  Non-start
            # actions have no StartAttempt aggregate, so serialize JSON null;
            # a populated start binding remains strictly validated above.
            "start_attempt": _deep_copy(self.start_attempt) if self.start_attempt else None,
        }


@dataclass(frozen=True, slots=True)
class BtcOperatorContractV2:
    schema_version: str
    source: str
    runtime_identity: str
    source_head: str
    state_revision: int
    state_digest: str
    as_of_utc: str
    actions: tuple[OperatorAuthorizationRecord, ...]
    operation: OperationReadModel | None = None
    guardian: Mapping[str, Any] = field(default_factory=dict)
    safety_flags: Mapping[str, bool] = field(
        default_factory=lambda: {name: False for name in SAFETY_FLAGS}
    )

    def __post_init__(self) -> None:
        if self.schema_version != OPERATOR_CONTRACT_SCHEMA_VERSION:
            raise ValueError("operator_contract_schema_invalid")
        if not _valid_source_head(self.source_head):
            raise ValueError("operator_contract_source_head_invalid")
        if not _valid_state_digest(self.state_digest):
            raise ValueError("operator_contract_state_digest_invalid")
        if self.state_revision < 0 or not self.runtime_identity or not _valid_utc_timestamp(self.as_of_utc):
            raise ValueError("operator_contract_identity_invalid")
        action_names = tuple(row.action for row in self.actions)
        if action_names != ALLOWLISTED_OPERATOR_ACTIONS:
            raise ValueError("operator_contract_action_set_invalid")
        flags = {name: bool(_mapping(self.safety_flags).get(name, False)) for name in SAFETY_FLAGS}
        if any(flags.values()):
            raise ValueError("operator_contract_safety_flag_enabled")
        object.__setattr__(self, "safety_flags", _deep_freeze(flags))
        object.__setattr__(self, "guardian", _deep_freeze(self.guardian))

    @property
    def action_map(self) -> Mapping[str, OperatorAuthorizationRecord]:
        return MappingProxyType({row.action: row for row in self.actions})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "runtime_identity": self.runtime_identity,
            "source_head": self.source_head,
            "state_revision": self.state_revision,
            "state_digest": self.state_digest,
            "as_of_utc": self.as_of_utc,
            "actions": [row.to_dict() for row in self.actions],
            "operation": self.operation.to_dict() if self.operation else None,
            "guardian": _deep_copy(self.guardian),
            "safety_flags": _deep_copy(self.safety_flags),
        }


# Short aliases make the contract convenient for service/API consumers while
# retaining the explicit schema names above.
OperatorAuthorization = OperatorAuthorizationRecord
OperatorContract = BtcOperatorContractV2


def _invalid_records(
    *,
    source: str,
    runtime_identity: str,
    state_revision: int | None,
    state_digest: str,
    as_of_utc: str,
    blockers: Sequence[str],
) -> tuple[OperatorAuthorizationRecord, ...]:
    stable = _stable_codes(blockers)
    return tuple(
        OperatorAuthorizationRecord(
            action=action,
            allowed=False,
            blocker_codes=stable,
            reason_codes=("state_unavailable",),
            source=source,
            runtime_identity=runtime_identity,
            state_revision=state_revision,
            state_digest=state_digest,
            as_of_utc=as_of_utc,
        )
        for action in ALLOWLISTED_OPERATOR_ACTIONS
    )


def _action_record(
    action: str,
    *,
    allowed: bool,
    blockers: Sequence[str],
    reasons: Sequence[str],
    source: str,
    runtime_identity: str,
    state_revision: int | None,
    state_digest: str,
    as_of_utc: str,
) -> OperatorAuthorizationRecord:
    return OperatorAuthorizationRecord(
        action=action,
        allowed=allowed,
        blocker_codes=tuple(blockers),
        reason_codes=tuple(reasons),
        source=source,
        runtime_identity=runtime_identity,
        state_revision=state_revision,
        state_digest=state_digest,
        as_of_utc=as_of_utc,
    )


def _runtime_blocker_codes(status: Mapping[str, Any]) -> tuple[str, ...]:
    """Collect status blockers for the opening-risk action only.

    Risk, ledger, and WS incidents are intentionally not a global veto for
    read-only refresh or already-proven protective actions.
    """

    runtime = _mapping(status.get("runtime"))
    start_capability = _mapping(status.get("start_capability"))
    risk = _mapping(status.get("risk_control"))
    private_ws = _mapping(status.get("private_ws"))
    ledger = _mapping(status.get("ledger_reconciliation"))
    values: list[Any] = [
        status.get("blockers"),
        runtime.get("blockers"),
        start_capability.get("blockers"),
        risk.get("blockers"),
        private_ws.get("blockers"),
        ledger.get("blockers"),
    ]
    result: list[str] = []
    for value in values:
        result.extend(_text_codes(value))
    return _stable_codes(result)


def _action_capability(
    status: Mapping[str, Any],
    action: str,
) -> tuple[bool | None, bool, tuple[str, ...], tuple[str, ...]]:
    """Read an explicit application/controller capability fact.

    ``None`` means no explicit fact was supplied.  It is only acceptable for
    refresh/stop-keep/cancel-only, whose authority is directly established by
    the runtime state.  Flatten/emergency require an explicit reduction proof.
    """

    containers = (
        status.get("operator_capabilities"),
        status.get("protective_capabilities"),
        status.get("action_capabilities"),
        status.get("action_authority"),
    )
    row: Mapping[str, Any] = {}
    for container in containers:
        candidate = _mapping(container).get(action)
        if isinstance(candidate, Mapping):
            row = candidate
            break
    if not row:
        allowed_name = f"{action}_allowed"
        if allowed_name in status:
            row = {
                "allowed": status.get(allowed_name),
                "reduction_proof": status.get(f"{action}_reduction_proof")
                or status.get("reduction_proof"),
                "effect": status.get(f"{action}_effect")
                or status.get("reduction_effect"),
                "blockers": status.get(f"{action}_blockers"),
            }
    if not row:
        return None, False, (), ()
    allowed = row.get("allowed") is True or row.get("authorized") is True
    blockers = list(_text_codes(row.get("blocker_codes") or row.get("blockers")))
    reasons = list(_text_codes(row.get("reason_codes") or row.get("reasons")))
    if row.get("runtime_allowed") is False:
        blockers.append("runtime_capability_denied")
    if row.get("position_authority") is False:
        blockers.append("position_authority_denied")
    proof = (
        row.get("reduction_proof") is True
        or row.get("protection_proof") is True
        or row.get("t1_t3_reduction_proof") is True
        or _mapping(row.get("reduction_plan")).get("approved") is True
    )
    effect = row.get("effect") or row.get("position_effect")
    if action in {"stop_and_flatten", "emergency_reduce_only_exit"}:
        if not allowed:
            blockers.append("protective_capability_denied")
        if effect not in {"decrease", "reduce", "reduction"}:
            blockers.append("reduction_effect_unknown")
        if not proof:
            blockers.append("reduction_proof_missing")
    elif not allowed:
        blockers.append("action_capability_denied")
    return allowed, proof, _stable_codes(blockers), _stable_codes(reasons)


def _position_state(status: Mapping[str, Any]) -> tuple[bool | None, bool | None]:
    """Return (facts_known, nonflat) without trusting a capability Boolean."""

    if "position_facts_known" in status and type(status.get("position_facts_known")) is bool:
        known = bool(status.get("position_facts_known"))
        raw_nonflat = status.get("position_nonflat", status.get("nonflat"))
        return known, bool(raw_nonflat) if type(raw_nonflat) is bool else None
    raw_exchange = _mapping(status.get("exchange"))
    if "positions" not in raw_exchange:
        return None, None
    rows = raw_exchange.get("positions")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return False, None
    nonflat = False
    for row in rows:
        if not isinstance(row, Mapping):
            return False, None
        value = row.get("contracts", row.get("pos", row.get("quantity")))
        try:
            if value is not None and float(value) != 0.0:
                nonflat = True
        except (TypeError, ValueError):
            return False, None
    return True, nonflat


def _guardian_action_capability(
    status: Mapping[str, Any],
    action: str,
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    guardian = _mapping(status.get("guardian"))
    explicit = _mapping(status.get("guardian_action_capabilities"))
    row = _mapping(explicit.get(action))
    if not row:
        row = _mapping(guardian.get("action_capabilities")).get(action, {})
    if not row:
        return False, ("guardian_action_capability_missing",), ()
    allowed = row.get("allowed") is True
    blockers = list(_text_codes(row.get("blocker_codes") or row.get("blockers")))
    reasons = list(_text_codes(row.get("reason_codes") or row.get("reasons")))
    if not allowed:
        blockers.append("guardian_action_capability_denied")
    return allowed, _stable_codes(blockers), _stable_codes(reasons)


def build_operator_contract_v2(
    status: Mapping[str, Any],
    *,
    operation: OperationReadModel | None = None,
    source: str = "btc_demo_runtime",
) -> BtcOperatorContractV2 | None:
    """Build an immutable projection, returning ``None`` for invalid identity.

    The API serializes the structured invalid records through
    :func:`project_operator_contract_v2` when the snapshot cannot form a full
    contract.  No caller-provided ``allowed_actions`` map is treated as an
    authority.
    """

    status_mapping = _mapping(status)
    (
        source_head,
        state_digest,
        runtime_identity,
        revision,
        as_of_utc,
        identity_blockers,
    ) = _status_identity(status_mapping)
    blockers = list(identity_blockers)
    if not _valid_source_head(source_head):
        blockers.append("source_head_invalid")
    if not _valid_state_digest(state_digest):
        blockers.append("state_digest_invalid")
    if not runtime_identity:
        blockers.append("runtime_identity_missing")
    if revision is None or revision < 0:
        blockers.append("state_revision_invalid")
    if not _valid_utc_timestamp(as_of_utc):
        blockers.append("as_of_utc_invalid")
    if blockers:
        return None

    runtime = _mapping(status_mapping.get("runtime"))
    start_capability = _mapping(status_mapping.get("start_capability"))
    start_operation = _mapping(status_mapping.get("start_operation") or runtime.get("start_operation"))
    active = runtime.get("active") is True
    cancel_only = runtime.get("cancel_only") is True
    transitioning = str(runtime.get("status") or "") in {"starting", "stopping"} or str(start_operation.get("state") or "") in {"queued", "running"}
    source_blockers = list(_runtime_blocker_codes(status_mapping))
    safe = status_mapping.get("safety")
    if isinstance(safe, Mapping) and any(bool(safe.get(name)) for name in SAFETY_FLAGS):
        source_blockers.append("safety_flag_enabled")
    if any(bool(status_mapping.get(name)) for name in SAFETY_FLAGS):
        source_blockers.append("safety_flag_enabled")
    start_blockers = _stable_codes(source_blockers)

    refresh_allowed, _, refresh_capability_blockers, _ = _action_capability(
        status_mapping, "refresh_account_snapshot"
    )
    stop_keep_allowed, _, stop_keep_blockers, _ = _action_capability(
        status_mapping, "stop_keep_position"
    )
    flatten_allowed, _, flatten_blockers, _ = _action_capability(
        status_mapping, "stop_and_flatten"
    )
    emergency_allowed, _, emergency_blockers, _ = _action_capability(
        status_mapping, "emergency_reduce_only_exit"
    )
    acknowledge_allowed, acknowledge_blockers, acknowledge_reasons = _guardian_action_capability(
        status_mapping, "acknowledge_guardian_trip"
    )
    recover_allowed, recover_blockers, recover_reasons = _guardian_action_capability(
        status_mapping, "recover_guardian_after_fresh_preflight"
    )
    position_known, nonflat = _position_state(status_mapping)
    strict_exit_matrix = position_known is not None
    if strict_exit_matrix:
        flatten_state_ok = position_known is True and nonflat is True and active and not transitioning
        emergency_state_ok = (
            position_known is True
            and nonflat is True
            and not active
            and (
                _mapping(runtime).get("opening") is False
                or (
                    "opening" not in runtime
                    and _mapping(runtime).get("opening_allowed") is False
                )
            )
            and cancel_only
            and str(_mapping(status_mapping.get("risk_control")).get("mode") or "")
            in {"FROZEN", "FROZEN_UNKNOWN", "STOPPED_WITH_RISK"}
            and not transitioning
        )
        if not flatten_state_ok:
            flatten_blockers = (*flatten_blockers, "stop_and_flatten_runtime_state_mismatch")
        if not emergency_state_ok:
            emergency_blockers = (*emergency_blockers, "emergency_exit_runtime_state_mismatch")
    # ``authoritative_preflight_start`` is an admission into the existing
    # controller's fresh verification chain.  It is deliberately not an
    # opening/new-risk permission.  Historical runtime/risk/Private WS/ledger
    # blockers must remain visible in the status snapshot for that chain to
    # re-check, but cannot form a deadlock that prevents the re-check itself.
    preflight_blockers: list[str] = []
    capability_blockers = start_capability.get("blockers")
    if capability_blockers is not None and capability_blockers not in ("", [], ()):
        normalized_capability_blockers = _text_codes(capability_blockers)
        preflight_blockers.extend(normalized_capability_blockers or ("blocker_code_invalid",))
    if start_capability.get("ready") is not True:
        preflight_blockers.append("preflight_not_ready")
    if "safety_flag_enabled" in start_blockers:
        preflight_blockers.append("safety_flag_enabled")
    preflight_extra = _stable_codes(preflight_blockers)

    def row(action: str, allowed: bool, reasons: Sequence[str], extra: Sequence[str] = ()) -> OperatorAuthorizationRecord:
        action_blockers = list(extra)
        action_reasons = list(reasons)
        if operation is not None and operation.action == action and not operation.acknowledged:
            if operation.state in {"queued", "running"}:
                action_blockers.append("operator_operation_in_progress")
                action_reasons.append("existing_operation_requires_observation")
            else:
                action_blockers.append("operator_terminal_operation_unacknowledged")
                action_reasons.append("terminal_operation_acknowledgement_required")
        return _action_record(
            action,
            allowed=allowed and not action_blockers,
            blockers=action_blockers,
            reasons=action_reasons,
            source=source,
            runtime_identity=runtime_identity,
            state_revision=revision,
            state_digest=state_digest,
            as_of_utc=as_of_utc,
        )

    records = (
        row(
            "authoritative_preflight_start",
            not active and not transitioning and start_capability.get("ready") is True and not preflight_blockers,
            ("preflight_available",) if not active and not transitioning else ("runtime_active",),
            preflight_extra,
        ),
        row(
            "refresh_account_snapshot",
            refresh_allowed is not False and not transitioning,
            ("snapshot_refresh_available",) if not transitioning else ("runtime_transitioning",),
            (*refresh_capability_blockers,),
        ),
        row(
            "stop_keep_position",
            stop_keep_allowed is not False and active and not transitioning,
            ("runtime_active",) if active else ("runtime_inactive",),
            (*stop_keep_blockers,),
        ),
        row(
            "stop_and_flatten",
            flatten_allowed is True and (flatten_state_ok if strict_exit_matrix else not transitioning),
            ("protective_reduction_authorized",) if flatten_allowed is True else ("protective_capability_missing",),
            (*flatten_blockers,),
        ),
        row(
            "enter_cancel_only",
            active and not transitioning,
            ("runtime_active",) if active else ("runtime_inactive",),
            ("already_cancel_only",) if cancel_only else (),
        ),
        row(
            "emergency_reduce_only_exit",
            emergency_allowed is True and (emergency_state_ok if strict_exit_matrix else not transitioning),
            ("emergency_exit_authorized",) if emergency_allowed is True else ("emergency_exit_not_authorized",),
            (*emergency_blockers,),
        ),
        row(
            "acknowledge_guardian_trip",
            acknowledge_allowed and not transitioning,
            ("guardian_trip_acknowledgement_required",) if acknowledge_allowed else ("guardian_trip_not_acknowledgeable",),
            (*acknowledge_blockers,),
        ),
        row(
            "recover_guardian_after_fresh_preflight",
            recover_allowed and not transitioning,
            ("fresh_guardian_observation_required",) if recover_allowed else ("guardian_recovery_not_ready",),
            (*recover_blockers,),
        ),
    )
    try:
        return BtcOperatorContractV2(
            schema_version=OPERATOR_CONTRACT_SCHEMA_VERSION,
            source=source,
            runtime_identity=runtime_identity,
            source_head=source_head,
            state_revision=revision if revision is not None else 0,
            state_digest=state_digest,
            as_of_utc=as_of_utc,
            actions=records,
            operation=operation,
            guardian=_mapping(status_mapping.get("guardian")),
        )
    except ValueError:
        return None


def project_operator_contract_v2(
    status: Mapping[str, Any],
    *,
    operation: OperationReadModel | None = None,
    source: str = "btc_demo_runtime",
) -> dict[str, Any]:
    """Return a serializable projection even when authoritative state is invalid."""

    contract = build_operator_contract_v2(status, operation=operation, source=source)
    if contract is not None:
        return contract.to_dict()
    status_mapping = _mapping(status)
    (
        source_head,
        state_digest,
        runtime_identity,
        revision,
        as_of,
        identity_blockers,
    ) = _status_identity(status_mapping)
    blockers = list(identity_blockers)
    if not _valid_source_head(source_head):
        blockers.append("source_head_invalid")
    if not _valid_state_digest(state_digest):
        blockers.append("state_digest_invalid")
    if not runtime_identity:
        blockers.append("runtime_identity_missing")
    if revision is None or revision < 0:
        blockers.append("state_revision_invalid")
    if not _valid_utc_timestamp(as_of):
        blockers.append("as_of_utc_invalid")
    rows = _invalid_records(
        source=source,
        runtime_identity=runtime_identity,
        state_revision=revision,
        state_digest=state_digest,
        as_of_utc=as_of,
        blockers=blockers,
    )
    return {
        "schema_version": OPERATOR_CONTRACT_SCHEMA_VERSION,
        "source": source,
        "runtime_identity": runtime_identity,
        "source_head": source_head,
        "state_revision": revision,
        "state_digest": state_digest,
        "as_of_utc": as_of,
        "actions": [row.to_dict() for row in rows],
        "operation": operation.to_dict() if operation else None,
        "guardian": _deep_copy(_mapping(status_mapping.get("guardian"))),
        "safety_flags": {name: False for name in SAFETY_FLAGS},
        "allowed": False,
        "execution_permission": False,
        "blockers": list(_stable_codes(blockers)),
    }


def authorize_operator_action(
    status: Mapping[str, Any],
    action: str,
    *,
    idempotency_key: str | None = None,
    operation: OperationReadModel | None = None,
) -> OperatorAuthorizationRecord:
    """Authorize one action from the same immutable projection used by GET."""

    normalized = str(action or "").strip()
    if normalized not in MUTATING_OPERATOR_ACTIONS:
        raise OperatorContractError(
            "operator_action_not_allowlisted",
            blockers=("operator_action_not_allowlisted",),
            status_code=400,
        )
    if not validate_idempotency_key(idempotency_key):
        raise OperatorContractError(
            "idempotency_key_required",
            blockers=("idempotency_key_required",),
            status_code=400,
        )
    contract = build_operator_contract_v2(status, operation=operation)
    if contract is None:
        projection = project_operator_contract_v2(status, operation=operation)
        raise OperatorContractError(
            "operator_state_unavailable",
            blockers=tuple(projection.get("blockers") or ("operator_state_unavailable",)),
            status_code=423,
        )
    record = contract.action_map[normalized]
    if not record.allowed:
        raise OperatorContractError(
            "operator_action_blocked",
            blockers=record.blocker_codes or ("operator_action_blocked",),
            reasons=record.reason_codes,
            status_code=423,
        )
    return record


__all__ = [
    "ALLOWLISTED_OPERATOR_ACTIONS",
    "MUTATING_OPERATOR_ACTIONS",
    "OPERATION_READ_MODEL_SCHEMA_VERSION",
    "OPERATION_STATES",
    "OPERATOR_CONTRACT_SCHEMA_VERSION",
    "OperationReadModel",
    "OperatorAuthorization",
    "OperatorAuthorizationRecord",
    "OperatorContract",
    "OperatorContractError",
    "BtcOperatorContractV2",
    "authorize_operator_action",
    "build_operator_contract_v2",
    "canonical_request_digest",
    "project_operator_contract_v2",
    "validate_idempotency_key",
]
