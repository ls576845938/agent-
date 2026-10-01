"""Pure BTC Shared Platform V3 T5 OMS contracts.

The objects in this module are deliberately below the runtime/execution
boundary.  They consume explicit T1--T4 evidence and construct an immutable
OMS submission record; they never create a client, read credentials, inspect
the clock/environment/filesystem, or call a transport.  A runtime facade may
project the record to the existing broker payload and hand it to the already
composed execution dispatcher, but this module cannot grant that permission.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from quant_crypto.portfolio.decision import (
    BTCPortfolioDecision,
    RiskReductionPlan,
)
from quant_crypto.risk import ActionRiskEffect, RiskAssessment
from quant_crypto.trading_contracts import (
    OrderIntent,
    RiskDecision,
    Signal,
    TargetPosition,
)
from quant_shared.runtime.permissions import RuntimeAction, RuntimeRiskEffect


BTC_SHARED_PLATFORM_V3_T5_VERSION = "btc_shared_platform_v3_t5_oms_v2"
BTC_SHARED_PLATFORM_V3_T5_PROTECTION_VERSION = (
    "btc_shared_platform_v3_t5_attached_protection_v1"
)

_SECURITY_FLAGS = {
    "execution_permission": False,
    "order_allowed": False,
    "promotion": False,
    "paper": False,
    "live": False,
    "private": False,
    "order": False,
    "real_order": False,
    "transfer": False,
    "withdraw": False,
}

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class OMSContractError(ValueError):
    """A supplied cross-layer OMS contract is missing or inconsistent."""

    def __init__(self, *blockers: str) -> None:
        self.blockers = tuple(
            dict.fromkeys(str(item).strip() for item in blockers if str(item).strip())
        )
        super().__init__(";".join(self.blockers) or "oms_contract_invalid")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_thaw(item) for item in value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            item.name: _thaw(getattr(value, item.name))
            for item in fields(value)
        }
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _thaw(value.to_dict())
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        _thaw(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read(value: Any, *names: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        try:
            return getattr(value, name)
        except AttributeError:
            continue
    return default


def _risk_value_text(value: Any, *, default: str = "") -> str:
    candidate = getattr(value, "value", value)
    if candidate is None:
        return default
    return str(candidate).strip().lower()


def _risk_semantic_field(value: Any, *names: str) -> Any:
    """Mirror the T1 semantic-field lookup without importing its private helper."""

    direct = _read(value, *names, default=None)
    if direct is not None:
        return direct
    metadata = _read(
        value,
        "metadata",
        "execution_metadata",
        "order_metadata",
        default=None,
    )
    return _read(metadata, *names, default=None)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _action(value: RuntimeAction | str) -> RuntimeAction:
    if isinstance(value, RuntimeAction):
        return value
    aliases = {
        "new_order": RuntimeAction.SUBMIT_NEW_ORDER,
        "submit_order": RuntimeAction.SUBMIT_NEW_ORDER,
        "open": RuntimeAction.SUBMIT_NEW_ORDER,
        "reduce_position": RuntimeAction.REDUCE_ONLY,
        "reduce_only_order": RuntimeAction.REDUCE_ONLY,
        "close": RuntimeAction.REDUCE_ONLY,
    }
    raw = _text(value).lower()
    try:
        return RuntimeAction(raw)
    except ValueError:
        if raw in aliases:
            return aliases[raw]
        raise OMSContractError("action_unknown")


def _effect(value: RuntimeRiskEffect | ActionRiskEffect | str) -> RuntimeRiskEffect:
    if isinstance(value, RuntimeRiskEffect):
        return value
    if isinstance(value, ActionRiskEffect):
        return RuntimeRiskEffect(value.value)
    raw = _text(value)
    try:
        return RuntimeRiskEffect(raw)
    except ValueError:
        try:
            return RuntimeRiskEffect(raw.upper())
        except ValueError as exc:
            raise OMSContractError("risk_effect_unknown") from exc


def order_intent_execution_digest(intent: OrderIntent) -> str:
    """Digest the canonical execution fields of one immutable intent.

    T1 evidence must bind the actual execution envelope, not merely an
    intent identifier.  Only the shared T1 semantic allowlist is included;
    timestamps and unrelated metadata remain excluded.
    """

    if not isinstance(intent, OrderIntent):
        raise OMSContractError("intent_digest_intent_invalid")
    # Keep this field map byte-for-byte aligned with
    # ``quant_shared.runtime.permissions._risk_intent_digest``.  The shared
    # helper is intentionally private, so this pure T5 module mirrors its
    # explicit execution-semantic allowlist instead of importing a verifier.
    fields = {
        "order_intent_id": _read(intent, "order_intent_id", "intent_id", default=""),
        "client_order_id": _read(
            intent,
            "client_order_id",
            "cl_ord_id",
            "clOrdId",
            default="",
        ),
        "symbol": _read(intent, "symbol", default=""),
        "side": _risk_value_text(_read(intent, "side", default="")),
        "quantity": _read(intent, "quantity", "qty", default=""),
        "order_type": _risk_value_text(_read(intent, "order_type", default="")),
        "limit_price": _read(intent, "limit_price", default=None),
        "time_in_force": _risk_value_text(
            _read(intent, "time_in_force", default="")
        ),
        "strategy_id": _read(intent, "strategy_id", default=""),
        "run_id": _read(intent, "run_id", default=""),
        "signal_id": _read(intent, "signal_id", default=""),
        "target_position_id": _read(intent, "target_position_id", default=""),
        "reduce_only": _risk_semantic_field(intent, "reduce_only", "reduceOnly"),
        "close_position": _risk_semantic_field(
            intent, "close_position", "closePosition"
        ),
        "post_only": _risk_semantic_field(intent, "post_only", "postOnly"),
        "position_side": _risk_semantic_field(
            intent,
            "position_side",
            "positionSide",
            "pos_side",
            "posSide",
        ),
        "order_role": _risk_semantic_field(
            intent,
            "order_role",
            "orderRole",
            "execution_role",
            "executionRole",
            "role",
        ),
        "trigger_type": _risk_semantic_field(
            intent,
            "trigger_type",
            "triggerType",
            "stop_type",
            "stopType",
        ),
        "trigger_price": _risk_semantic_field(
            intent, "trigger_price", "triggerPrice", "trigger_px", "triggerPx"
        ),
        "stop_price": _risk_semantic_field(
            intent, "stop_price", "stopPrice", "stop_px", "stopPx"
        ),
        "trigger_direction": _risk_semantic_field(
            intent, "trigger_direction", "triggerDirection"
        ),
        "parent_order_id": _risk_semantic_field(
            intent,
            "parent_order_id",
            "parentOrderId",
            "parent_cl_ord_id",
            "parentClOrdId",
        ),
        "protection_order_id": _risk_semantic_field(
            intent,
            "protection_order_id",
            "protectionOrderId",
            "protection_cl_ord_id",
            "protectionClOrdId",
            "protective_cl_ord_id",
        ),
        "algo_id": _risk_semantic_field(
            intent,
            "algo_id",
            "algoId",
            "algo_cl_ord_id",
            "algoClOrdId",
            "protection_algo_id",
        ),
        "oco_id": _risk_semantic_field(
            intent,
            "oco_id",
            "ocoId",
            "oco_cl_ord_id",
            "ocoClOrdId",
            "attach_algo_cl_ord_id",
            "attachAlgoClOrdId",
        ),
    }
    return hashlib.sha256(
        json.dumps(
            fields,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _snapshot_signal(signal: Signal) -> Signal:
    return Signal(
        timestamp_utc=signal.timestamp_utc,
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        direction=signal.direction,
        strength=signal.strength,
        horizon=signal.horizon,
        reason=signal.reason,
        metadata=_freeze(signal.metadata),
        signal_id=signal.signal_id,
    )


def _snapshot_target(target: TargetPosition) -> TargetPosition:
    return TargetPosition(
        timestamp_utc=target.timestamp_utc,
        strategy_id=target.strategy_id,
        symbol=target.symbol,
        target_weight=target.target_weight,
        target_quantity=target.target_quantity,
        signal_id=target.signal_id,
        metadata=_freeze(target.metadata),
        target_position_id=target.target_position_id,
    )


@dataclass(frozen=True)
class OMSProofIdentity:
    """Pending binding identity; it is not dispatcher evidence or a permit."""

    source_head: str
    account_identity: str
    session_id: str
    key_namespace: str
    client_order_namespace: str
    epoch: int
    intent_digest: str
    evidence_digest: str = ""
    evidence_identity: str = "pending_dispatcher_authority"
    guardian_digest: str = ""
    authority_verified: bool = False
    evidence_status: str = "pending_dispatcher_authority"

    def __post_init__(self) -> None:
        required = (
            "source_head",
            "account_identity",
            "session_id",
            "key_namespace",
            "client_order_namespace",
            "intent_digest",
        )
        for name in required:
            value = _text(getattr(self, name))
            if not value:
                raise OMSContractError(f"proof_{name}_missing")
            object.__setattr__(self, name, value)
        if not _HEX40_RE.fullmatch(self.source_head):
            raise OMSContractError("proof_source_head_invalid")
        if not _HEX64_RE.fullmatch(self.account_identity):
            raise OMSContractError("proof_account_identity_invalid")
        if not _HEX64_RE.fullmatch(self.intent_digest):
            raise OMSContractError("proof_intent_digest_invalid")
        evidence_digest = _text(self.evidence_digest)
        if evidence_digest:
            raise OMSContractError("proof_evidence_not_issued")
        object.__setattr__(self, "evidence_digest", "")
        if type(self.epoch) is not int or self.epoch < 0:
            raise OMSContractError("proof_epoch_invalid")
        evidence_identity = _text(self.evidence_identity)
        if evidence_identity != "pending_dispatcher_authority":
            raise OMSContractError("proof_pending_authority_required")
        object.__setattr__(self, "evidence_identity", evidence_identity)
        evidence_status = _text(self.evidence_status)
        if evidence_status != "pending_dispatcher_authority":
            raise OMSContractError("proof_pending_status_required")
        object.__setattr__(self, "evidence_status", evidence_status)
        if type(self.authority_verified) is not bool or self.authority_verified:
            raise OMSContractError("proof_authority_verification_forbidden")
        object.__setattr__(self, "authority_verified", False)
        guardian_digest = _text(self.guardian_digest)
        if guardian_digest and not _HEX64_RE.fullmatch(guardian_digest):
            raise OMSContractError("proof_guardian_digest_invalid")
        object.__setattr__(self, "guardian_digest", guardian_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BTC_SHARED_PLATFORM_V3_T5_VERSION,
            "source_head": self.source_head,
            "account_identity": self.account_identity,
            "session_id": self.session_id,
            "key_namespace": self.key_namespace,
            "client_order_namespace": self.client_order_namespace,
            "epoch": self.epoch,
            "intent_digest": self.intent_digest,
            "evidence_digest": self.evidence_digest,
            "evidence_identity": self.evidence_identity,
            "authority_verified": False,
            "evidence_status": self.evidence_status,
            "guardian_digest": self.guardian_digest,
            **_SECURITY_FLAGS,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class OMSAttachedProtection(Mapping[str, Any]):
    """Immutable protection projection plus the identity it protects."""

    payload: Mapping[str, Any]
    parent_client_order_id: str
    contracts: str
    position_side: str
    policy_digest: str

    def __post_init__(self) -> None:
        payload = _freeze(self.payload)
        if not isinstance(payload, Mapping):
            raise OMSContractError("protection_payload_missing")
        object.__setattr__(self, "payload", payload)
        parent = _text(self.parent_client_order_id)
        if not parent:
            raise OMSContractError("protection_parent_identity_missing")
        object.__setattr__(self, "parent_client_order_id", parent)
        quantity = _decimal(self.contracts)
        if quantity is None or quantity <= 0:
            raise OMSContractError("protection_quantity_invalid")
        object.__setattr__(self, "contracts", format(quantity, "f"))
        side = _text(self.position_side).lower()
        if side not in {"long", "short"}:
            raise OMSContractError("protection_position_side_invalid")
        object.__setattr__(self, "position_side", side)
        digest = _text(self.policy_digest)
        if not digest:
            raise OMSContractError("protection_policy_identity_missing")
        object.__setattr__(self, "policy_digest", digest)
        payload_policy = payload.get("policy")
        if not isinstance(payload_policy, Mapping):
            raise OMSContractError("protection_policy_payload_missing")
        if _digest(payload_policy) != digest:
            raise OMSContractError("protection_policy_digest_mismatch")

        expected = {
            "attachAlgoClOrdId": f"{parent}A",
            "tpOrdPx": "-1",
            "slOrdPx": "-1",
            "tpTriggerPxType": "mark",
            "slTriggerPxType": "mark",
        }
        for key, expected_value in expected.items():
            if str(payload.get(key) or "") != expected_value:
                raise OMSContractError(f"protection_{key}_mismatch")
        if not _text(payload.get("tpTriggerPx")) or not _text(payload.get("slTriggerPx")):
            raise OMSContractError("protection_trigger_missing")

    def __getitem__(self, key: str) -> Any:
        return self.payload[key]

    def __iter__(self):
        return iter(self.payload)

    def __len__(self) -> int:
        return len(self.payload)

    def to_exchange_payload(self) -> dict[str, Any]:
        return _thaw(self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BTC_SHARED_PLATFORM_V3_T5_PROTECTION_VERSION,
            "payload": _thaw(self.payload),
            "parent_client_order_id": self.parent_client_order_id,
            "contracts": self.contracts,
            "position_side": self.position_side,
            "policy_digest": self.policy_digest,
            "remove_allowed": False,
            **_SECURITY_FLAGS,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class OMSOrderSubmissionBundle:
    """Immutable T1/T2/T3/T4-bound order construction record.

    ``execution_permission`` and ``order_allowed`` are deliberately false in
    its wire form.  A valid bundle only proves that the order is well-bound;
    the existing runtime permission evaluator and dispatcher still decide
    whether a transport callback may run.
    """

    signal: Signal
    target_position: TargetPosition
    risk_assessment: RiskAssessment
    portfolio_decision: BTCPortfolioDecision
    position_before: float
    position_after: float
    action: RuntimeAction | str
    risk_effect: RuntimeRiskEffect | ActionRiskEffect | str
    proof_identity: OMSProofIdentity
    price: str
    quantity: str
    venue_facts: Mapping[str, Any]
    cost_facts: Mapping[str, Any]
    intent: OrderIntent | None = None
    protection: OMSAttachedProtection | None = None
    guardian_health: Mapping[str, Any] = field(default_factory=dict)
    guardian_latch: Mapping[str, Any] = field(default_factory=dict)
    _validated: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signal, Signal):
            raise OMSContractError("signal_missing_or_invalid")
        if not isinstance(self.target_position, TargetPosition):
            raise OMSContractError("target_position_missing_or_invalid")
        if not isinstance(self.risk_assessment, RiskAssessment):
            raise OMSContractError("t2_risk_assessment_missing_or_invalid")
        if not isinstance(self.portfolio_decision, BTCPortfolioDecision):
            raise OMSContractError("t3_portfolio_decision_missing_or_invalid")
        if type(self.proof_identity) is not OMSProofIdentity:
            raise OMSContractError("proof_identity_missing_or_invalid")
        if (
            self.proof_identity.authority_verified is not False
            or self.proof_identity.evidence_status != "pending_dispatcher_authority"
            or self.proof_identity.evidence_digest
        ):
            raise OMSContractError("proof_dispatcher_authority_pending_required")

        signal = _snapshot_signal(self.signal)
        target = _snapshot_target(self.target_position)
        object.__setattr__(self, "signal", signal)
        object.__setattr__(self, "target_position", target)
        object.__setattr__(self, "venue_facts", _freeze(self.venue_facts))
        object.__setattr__(self, "cost_facts", _freeze(self.cost_facts))
        object.__setattr__(self, "guardian_health", _freeze(self.guardian_health))
        object.__setattr__(self, "guardian_latch", _freeze(self.guardian_latch))

        before = _finite(self.position_before)
        after = _finite(self.position_after)
        price = _decimal(self.price)
        quantity = _decimal(self.quantity)
        if before is None or after is None:
            raise OMSContractError("position_before_after_nonfinite")
        if price is None or price <= 0:
            raise OMSContractError("execution_price_invalid")
        if quantity is None or quantity <= 0:
            raise OMSContractError("order_quantity_invalid")
        object.__setattr__(self, "position_before", before)
        object.__setattr__(self, "position_after", after)
        object.__setattr__(self, "price", format(price, "f"))
        object.__setattr__(self, "quantity", format(quantity, "f"))
        action = _action(self.action)
        effect = _effect(self.risk_effect)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "risk_effect", effect)

        self._validate_bindings()
        object.__setattr__(self, "_validated", True)

    def _validate_bindings(self) -> None:
        target = self.target_position
        decision = self.portfolio_decision
        assessment = self.risk_assessment
        if decision.target_position.target_position_id != target.target_position_id:
            raise OMSContractError("t3_target_identity_mismatch")
        if decision.target_position.strategy_id != target.strategy_id or decision.target_position.symbol != target.symbol:
            raise OMSContractError("t3_target_context_mismatch")
        if decision.risk_assessment is not assessment:
            raise OMSContractError("t2_t3_risk_identity_mismatch")
        if target.signal_id != self.signal.signal_id:
            raise OMSContractError("signal_target_identity_mismatch")
        if target.strategy_id != self.signal.strategy_id or target.symbol != self.signal.symbol:
            raise OMSContractError("signal_target_context_mismatch")
        if self.position_before * self.position_after < 0:
            raise OMSContractError(
                "reduction_cross_zero"
                if self.action is RuntimeAction.REDUCE_ONLY
                else "cross_zero_position"
            )
        if assessment.execution_permission is not False or decision.execution_permission is not False:
            raise OMSContractError("risk_or_portfolio_execution_permission")
        metadata = assessment.metadata
        assessed_before = _finite(_read(metadata, "position_before"))
        assessed_after = _finite(_read(metadata, "position_after"))
        if assessed_before is None or assessed_before != self.position_before:
            raise OMSContractError("t2_position_before_mismatch")
        if assessed_after is None or assessed_after != self.position_after:
            raise OMSContractError("t2_position_after_mismatch")
        target_quantity = _finite(target.target_quantity)
        if target_quantity is None or target_quantity != self.position_after:
            raise OMSContractError("target_quantity_mismatch")
        expected_effect = (
            RuntimeRiskEffect.INCREASE_ABS_EXPOSURE
            if abs(self.position_after) > abs(self.position_before)
            else RuntimeRiskEffect.DECREASE_ABS_EXPOSURE
            if abs(self.position_after) < abs(self.position_before)
            else RuntimeRiskEffect.NO_POSITION_EFFECT
        )
        if self.position_before * self.position_after < 0:
            raise OMSContractError("cross_zero_position")
        if self.risk_effect is not expected_effect:
            raise OMSContractError("risk_effect_position_mismatch")

        if self.action is RuntimeAction.SUBMIT_NEW_ORDER:
            if self.position_before != 0.0 or not self.portfolio_decision.order_generation_allowed:
                raise OMSContractError("opening_requires_t3_approved_original_target")
            if not self.guardian_health:
                raise OMSContractError("opening_guardian_health_missing")
            if _read(self.guardian_health, "passed", "healthy", default=False) is not True:
                raise OMSContractError("opening_guardian_health_not_clear")
            if not assessment.approved or assessment.blockers or assessment.requires_reduction:
                raise OMSContractError("opening_t2_risk_not_approved")
            if _read(target.metadata, "order_generation_allowed", default=True) is False:
                raise OMSContractError("opening_target_generation_blocked")
            if self.risk_effect is not RuntimeRiskEffect.INCREASE_ABS_EXPOSURE:
                raise OMSContractError("opening_risk_effect_invalid")
            if self.protection is None:
                raise OMSContractError("opening_attached_protection_required")
        elif self.action is RuntimeAction.REDUCE_ONLY:
            plan = decision.reduction_plan
            if not isinstance(plan, RiskReductionPlan):
                raise OMSContractError("reduction_plan_missing")
            if plan.source_target_position_id != target.target_position_id:
                raise OMSContractError("reduction_plan_target_identity_mismatch")
            if plan.strategy_id != target.strategy_id or plan.symbol != target.symbol:
                raise OMSContractError("reduction_plan_target_context_mismatch")
            if plan.decision_time_utc != decision.decision_time_utc:
                raise OMSContractError("reduction_plan_decision_time_mismatch")
            target_metadata = target.metadata if isinstance(target.metadata, Mapping) else {}
            declared_source_kind = _text(target_metadata.get("source_kind")).lower()
            target_source_signal_id = _text(target_metadata.get("source_signal_id"))
            target_forecast_id = _text(target_metadata.get("forecast_id"))
            target_declared_forecast_id = _text(
                target_metadata.get("source_forecast_id")
            )
            if (
                target_forecast_id
                and target_declared_forecast_id
                and target_forecast_id != target_declared_forecast_id
            ):
                raise OMSContractError("reduction_forecast_source_conflict")
            target_source_forecast_id = (
                target_forecast_id or target_declared_forecast_id
            )
            if plan.source_kind == "signal":
                if declared_source_kind != "signal":
                    raise OMSContractError("reduction_signal_source_kind_mismatch")
                if target_source_forecast_id:
                    raise OMSContractError("reduction_source_conflict")
                if not target_source_signal_id:
                    raise OMSContractError("reduction_signal_source_missing")
                if (
                    plan.source_signal_id != self.signal.signal_id
                    or plan.source_signal_id != target.signal_id
                    or plan.source_signal_id != target_source_signal_id
                ):
                    raise OMSContractError("reduction_signal_source_mismatch")
                if plan.source_forecast_id:
                    raise OMSContractError("reduction_source_conflict")
            elif plan.source_kind == "forecast":
                if declared_source_kind and declared_source_kind != "forecast":
                    raise OMSContractError("reduction_forecast_source_kind_mismatch")
                if not target_source_forecast_id:
                    raise OMSContractError("reduction_forecast_source_missing")
                if plan.source_forecast_id != target_source_forecast_id:
                    raise OMSContractError("reduction_forecast_source_mismatch")
                if plan.source_signal_id:
                    raise OMSContractError("reduction_source_conflict")
                if target_source_signal_id and target_source_signal_id != target.signal_id:
                    raise OMSContractError("reduction_forecast_upstream_signal_mismatch")
            else:
                raise OMSContractError("reduction_source_kind_invalid")
            if self.position_before == 0.0 or abs(self.position_after) >= abs(self.position_before):
                raise OMSContractError("reduction_must_decrease_absolute_position")
            if self.position_before * self.position_after < 0:
                raise OMSContractError("reduction_cross_zero")
            if _finite(plan.current_quantity) != self.position_before or _finite(plan.target_quantity) != self.position_after:
                raise OMSContractError("reduction_plan_position_mismatch")
            if _finite(plan.reduction_quantity) != abs(self.position_before) - abs(self.position_after):
                raise OMSContractError("reduction_plan_quantity_mismatch")
            if plan.action is not ActionRiskEffect.DECREASE_ABS_EXPOSURE:
                raise OMSContractError("reduction_plan_effect_invalid")
            if self.risk_effect is not RuntimeRiskEffect.DECREASE_ABS_EXPOSURE:
                raise OMSContractError("reduction_risk_effect_invalid")
        else:
            raise OMSContractError("oms_action_not_order_submission")

        if self.intent is None:
            raise OMSContractError("order_intent_missing")
        if self.intent is not None:
            if self.intent.symbol != target.symbol or self.intent.target_position_id != target.target_position_id:
                raise OMSContractError("intent_target_identity_mismatch")
            if self.intent.signal_id != self.signal.signal_id:
                raise OMSContractError("intent_signal_identity_mismatch")
            intent_quantity = _finite(self.intent.quantity)
            intent_price = _decimal(self.intent.limit_price)
            if intent_quantity is None or intent_quantity != float(self.quantity):
                raise OMSContractError("intent_quantity_mismatch")
            if intent_price is None or intent_price != _decimal(self.price):
                raise OMSContractError("intent_price_mismatch")
            expected_intent_digest = order_intent_execution_digest(self.intent)
            if self.proof_identity.intent_digest != expected_intent_digest:
                raise OMSContractError("proof_intent_digest_mismatch")
            if self.intent.strategy_id != self.signal.strategy_id:
                raise OMSContractError("intent_strategy_identity_mismatch")
            before = Decimal(str(self.position_before))
            after = Decimal(str(self.position_after))
            expected_side = (
                "buy"
                if after > before
                else "sell"
                if after < before
                else ""
            )
            if self.intent.side.value != expected_side:
                raise OMSContractError("intent_side_position_delta_mismatch")
            if Decimal(str(self.quantity)) != abs(after - before):
                raise OMSContractError("order_quantity_position_delta_mismatch")
        instrument = _text(_read(self.venue_facts, "instrument_id", "instId"))
        margin_mode = _text(_read(self.venue_facts, "margin_mode", "tdMode")).lower()
        venue_position_side = _text(
            _read(self.venue_facts, "position_side", "posSide")
        ).lower()
        if instrument != "BTC-USDT-SWAP":
            raise OMSContractError("venue_instrument_missing_or_mismatch")
        if margin_mode != "isolated":
            raise OMSContractError("venue_margin_mode_missing_or_mismatch")
        expected_position_side = (
            "long"
            if self.position_before > 0 or self.position_after > 0
            else "short"
            if self.position_before < 0 or self.position_after < 0
            else ""
        )
        if venue_position_side != expected_position_side:
            raise OMSContractError("venue_position_side_missing_or_mismatch")
        if not self.cost_facts:
            raise OMSContractError("cost_facts_missing")
        # A tripped guardian latch is an opening blocker.  Risk-reducing
        # bundles remain admissible so the existing fail-closed recovery path
        # can flatten exposure; the latch never grants execution permission.
        if (
            self.action is RuntimeAction.SUBMIT_NEW_ORDER
            and self.guardian_latch
            and _read(self.guardian_latch, "tripped", "blocked", default=False) is True
        ):
            raise OMSContractError("guardian_latch_blocked")
        if self.action is RuntimeAction.SUBMIT_NEW_ORDER:
            protection = self.protection
            assert protection is not None
            if protection.parent_client_order_id != self.intent.client_order_id:
                raise OMSContractError("protection_parent_intent_mismatch")
            if Decimal(protection.contracts) != Decimal(self.quantity):
                raise OMSContractError("protection_quantity_intent_mismatch")
            if protection.position_side != expected_position_side:
                raise OMSContractError("protection_position_side_intent_mismatch")
            payload_size = _read(protection.payload, "sz", "size", "contracts")
            if payload_size is not None and _decimal(payload_size) != Decimal(self.quantity):
                raise OMSContractError("protection_payload_quantity_mismatch")
            payload_pos_side = _text(_read(protection.payload, "posSide", "position_side")).lower()
            if payload_pos_side and payload_pos_side != expected_position_side:
                raise OMSContractError("protection_payload_position_side_mismatch")

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": BTC_SHARED_PLATFORM_V3_T5_VERSION,
            "signal": _thaw(self.signal),
            "target_position": _thaw(self.target_position),
            "t2_risk_assessment": _thaw(self.risk_assessment),
            "t3_portfolio_decision": _thaw(self.portfolio_decision),
            "position_before": self.position_before,
            "position_after": self.position_after,
            "action": self.action.value,
            "risk_effect": self.risk_effect.value,
            "proof_identity": self.proof_identity.to_dict(),
            "price": self.price,
            "quantity": self.quantity,
            "venue_facts": _thaw(self.venue_facts),
            "cost_facts": _thaw(self.cost_facts),
            "intent": None if self.intent is None else _thaw(self.intent),
            "protection": None if self.protection is None else self.protection.to_dict(),
            "guardian_health": _thaw(self.guardian_health),
            "guardian_latch": _thaw(self.guardian_latch),
            **_SECURITY_FLAGS,
        }
        if include_digest:
            payload["oms_bundle_digest"] = _digest(payload)
        return payload

    def to_risk_decision(self, intent: OrderIntent) -> RiskDecision:
        """Project a validated bundle into the legacy dispatcher input.

        The approval here is derived only after all T1--T4 bindings have
        passed; callers cannot supply an independent approved boolean.
        """

        if not isinstance(intent, OrderIntent):
            raise OMSContractError("legacy_risk_projection_intent_invalid")
        if self.intent is not None and intent.order_intent_id != self.intent.order_intent_id:
            raise OMSContractError("legacy_risk_projection_intent_mismatch")
        expected_intent_digest = order_intent_execution_digest(intent)
        if self.proof_identity.intent_digest != expected_intent_digest:
            raise OMSContractError("proof_intent_digest_mismatch")
        metadata = {
            "oms_bundle_digest": self.digest,
            "proof_identity_digest": self.proof_identity.digest,
            "risk_effect": self.risk_effect.value,
            "position_before": self.position_before,
            "position_after": self.position_after,
            "venue_facts": _thaw(self.venue_facts),
            "cost_facts": _thaw(self.cost_facts),
            **_SECURITY_FLAGS,
        }
        return RiskDecision(
            approved=True,
            reason="btc_shared_platform_v3_t5_bound_oms_bundle",
            order_intent_id=intent.order_intent_id,
            risk_version=BTC_SHARED_PLATFORM_V3_T5_VERSION,
            rule_name="BTC-SHARED-PLATFORM-V3-T5",
            threshold=float(self.price) * float(self.quantity),
            metadata=metadata,
        )


class SharedPlatformV3OMS:
    """Pure delegate used by the BTC runtime facade."""

    def build_attached_protection(
        self,
        *,
        policy: Mapping[str, Any] | Any,
        entry_price: Any,
        tick_size: Any,
        position_side: str,
        client_order_id: str,
        contracts: Any,
    ) -> OMSAttachedProtection:
        entry = _decimal(entry_price)
        tick = _decimal(tick_size)
        size = _decimal(contracts)
        side = _text(position_side).lower()
        if entry is None or entry <= 0:
            raise OMSContractError("protection_entry_price_invalid")
        if tick is None or tick <= 0:
            raise OMSContractError("protection_tick_size_invalid")
        if size is None or size <= 0:
            raise OMSContractError("protection_quantity_invalid")
        if side not in {"long", "short"}:
            raise OMSContractError("protection_position_side_invalid")
        policy_mapping = policy.to_dict() if hasattr(policy, "to_dict") else dict(policy or {})
        policy_id = _text(policy_mapping.get("policy_id"))
        version = _text(policy_mapping.get("version"))
        trigger = _text(policy_mapping.get("trigger")).lower()
        sl_bps = _decimal(policy_mapping.get("sl_distance_bps"))
        tp_bps = _decimal(policy_mapping.get("tp_distance_bps"))
        if not policy_id or not version or trigger != "mark" or sl_bps is None or tp_bps is None:
            raise OMSContractError("protection_policy_invalid")
        if not Decimal("10") <= sl_bps <= Decimal("2500"):
            raise OMSContractError("protection_stop_distance_invalid")
        if not Decimal("10") <= tp_bps <= Decimal("5000"):
            raise OMSContractError("protection_policy_distance_invalid")
        supplied_policy_sha = _text(policy_mapping.get("policy_sha256"))
        if supplied_policy_sha:
            canonical_policy = {
                "policy_id": policy_id,
                "version": version,
                "sl_distance_bps": format(sl_bps, "f"),
                "tp_distance_bps": format(tp_bps, "f"),
                "trigger": trigger,
            }
            expected_policy_sha = hashlib.sha256(
                json.dumps(
                    canonical_policy,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if supplied_policy_sha != expected_policy_sha:
                raise OMSContractError("protection_policy_digest_mismatch")
        if side == "long":
            stop = _round_to_tick(entry * (Decimal("1") - sl_bps / Decimal("10000")), tick, ROUND_FLOOR)
            take = _round_to_tick(entry * (Decimal("1") + tp_bps / Decimal("10000")), tick, ROUND_CEILING)
        else:
            stop = _round_to_tick(entry * (Decimal("1") + sl_bps / Decimal("10000")), tick, ROUND_CEILING)
            take = _round_to_tick(entry * (Decimal("1") - tp_bps / Decimal("10000")), tick, ROUND_FLOOR)
        if stop <= 0 or take <= 0:
            raise OMSContractError("protection_trigger_invalid")
        parent = _text(client_order_id)
        if not parent:
            raise OMSContractError("protection_parent_identity_missing")
        payload = {
            "attachAlgoClOrdId": f"{parent}A",
            "tpTriggerPx": format(take, "f"),
            "tpOrdPx": "-1",
            "tpTriggerPxType": "mark",
            "slTriggerPx": format(stop, "f"),
            "slOrdPx": "-1",
            "slTriggerPxType": "mark",
            "policy": policy_mapping,
        }
        return OMSAttachedProtection(
            payload=payload,
            parent_client_order_id=parent,
            contracts=format(size, "f"),
            position_side=side,
            policy_digest=_digest(policy_mapping),
        )

    def build_order_submission_bundle(self, **kwargs: Any) -> OMSOrderSubmissionBundle:
        return OMSOrderSubmissionBundle(**kwargs)

    def build_legacy_compatibility_bundle(
        self,
        *,
        signal: Signal,
        target_position: TargetPosition,
        current_quantity: Any,
        target_quantity: Any,
        action: RuntimeAction | str,
        quantity: Any,
        price: Any,
        venue_facts: Mapping[str, Any],
        cost_facts: Mapping[str, Any],
        proof_identity: OMSProofIdentity,
        protection: OMSAttachedProtection | None = None,
        intent: OrderIntent | None = None,
        guardian_health: Mapping[str, Any] | None = None,
        guardian_latch: Mapping[str, Any] | None = None,
    ) -> OMSOrderSubmissionBundle:
        # Kept as a fail-closed compatibility symbol so older callers fail
        # loudly.  It must never fabricate T2/T3 evidence in an order path.
        raise OMSContractError("legacy_compatibility_bundle_disabled")

    def risk_decision_for(self, bundle: OMSOrderSubmissionBundle, intent: OrderIntent) -> RiskDecision:
        return bundle.to_risk_decision(intent)

    def remove_attached_protection(self, *_args: Any, **_kwargs: Any) -> None:
        """Protection removal is never an OMS construction operation."""

        raise OMSContractError("protection_removal_forbidden")


def _round_to_tick(value: Decimal, tick: Decimal, rounding: str) -> Decimal:
    steps = (value / tick).to_integral_value(rounding=rounding)
    return steps * tick


def build_order_submission_bundle(**kwargs: Any) -> OMSOrderSubmissionBundle:
    return OMSOrderSubmissionBundle(**kwargs)


def build_attached_protection(**kwargs: Any) -> OMSAttachedProtection:
    return SharedPlatformV3OMS().build_attached_protection(**kwargs)


# Descriptive aliases keep the T5 seam discoverable without introducing a
# second implementation or changing the facade's public API.
BTCSharedPlatformV3OMS = SharedPlatformV3OMS
OMSSubmissionBundle = OMSOrderSubmissionBundle
OrderSubmissionBundle = OMSOrderSubmissionBundle
AttachedProtection = OMSAttachedProtection


__all__ = [
    "BTC_SHARED_PLATFORM_V3_T5_VERSION",
    "BTC_SHARED_PLATFORM_V3_T5_PROTECTION_VERSION",
    "OMSContractError",
    "OMSProofIdentity",
    "OMSAttachedProtection",
    "OMSOrderSubmissionBundle",
    "SharedPlatformV3OMS",
    "BTCSharedPlatformV3OMS",
    "OMSSubmissionBundle",
    "OrderSubmissionBundle",
    "AttachedProtection",
    "build_order_submission_bundle",
    "build_attached_protection",
    "order_intent_execution_digest",
]
