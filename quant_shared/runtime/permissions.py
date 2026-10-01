"""Central permission evaluation for runtime trading actions.

Callers should ask this evaluator instead of re-implementing state/mode checks
in OMS or broker adapters.  The evaluator is pure and never sends an order,
cancels an order, or opens a network connection.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from quant_shared.core.time import ensure_utc, isoformat_utc, utc_now
from quant_shared.runtime.models import RuntimeSnapshot, RuntimeState, TradingMode


@dataclass(frozen=True)
class PermissionDecision:
    """Structured explanation for a permission result."""

    action: str
    allowed: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.allowed

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reasons

    @property
    def reason(self) -> str | None:
        return self.reasons[0] if self.reasons else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "blockers": list(self.reasons),
        }


class RuntimeAction(str, Enum):
    """Actions that must cross the canonical BTC execution boundary.

    The enum is intentionally transport-neutral.  A broker adapter may map
    these values to a venue-specific endpoint, but it must not invent a
    second permission decision.
    """

    SUBMIT_NEW_ORDER = "submit_new_order"
    CANCEL_ORDER = "cancel_order"
    REPLACE_ORDER = "replace_order"
    REDUCE_ONLY = "reduce_only"
    ATTACH_PROTECTION = "attach_protection"
    DEAD_MAN = "dead_man"


class RuntimeRiskEffect(str, Enum):
    """Signed effect of one concrete action on absolute exposure.

    This vocabulary is deliberately asset/venue neutral.  It is part of the
    trusted risk evidence rather than a caller supplied permission hint.
    """

    INCREASE_ABS_EXPOSURE = "INCREASE_ABS_EXPOSURE"
    DECREASE_ABS_EXPOSURE = "DECREASE_ABS_EXPOSURE"
    NO_POSITION_EFFECT = "NO_POSITION_EFFECT"
    ADD_PROTECTION = "ADD_PROTECTION"
    REMOVE_PROTECTION = "REMOVE_PROTECTION"
    UNKNOWN = "UNKNOWN"


_RUNTIME_RISK_EFFECTS = frozenset(item.value for item in RuntimeRiskEffect)


class RuntimeRiskEvidenceError(ValueError):
    """Raised when a caller attempts to forge or directly construct proof."""


def _risk_canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _risk_intent_digest(order_intent: object | Mapping[str, Any] | None) -> str:
    """Digest execution fields only; caller metadata is deliberately excluded."""

    if order_intent is None:
        return ""
    fields = {
        "order_intent_id": _read_field(order_intent, "order_intent_id", "intent_id", default=""),
        "client_order_id": _read_field(order_intent, "client_order_id", "cl_ord_id", "clOrdId", default=""),
        "symbol": _read_field(order_intent, "symbol", default=""),
        "side": _value_text(_read_field(order_intent, "side", default="")),
        "quantity": _read_field(order_intent, "quantity", "qty", default=""),
        "order_type": _value_text(_read_field(order_intent, "order_type", default="")),
        "limit_price": _read_field(order_intent, "limit_price", default=None),
        "time_in_force": _value_text(_read_field(order_intent, "time_in_force", default="")),
        "strategy_id": _read_field(order_intent, "strategy_id", default=""),
        "run_id": _read_field(order_intent, "run_id", default=""),
        "signal_id": _read_field(order_intent, "signal_id", default=""),
        "target_position_id": _read_field(order_intent, "target_position_id", default=""),
        # These fields alter order construction or risk interpretation.  Keep
        # the list explicit; arbitrary caller metadata is never trusted.
        "reduce_only": _read_semantic_field(order_intent, "reduce_only", "reduceOnly"),
        "close_position": _read_semantic_field(order_intent, "close_position", "closePosition"),
        "post_only": _read_semantic_field(order_intent, "post_only", "postOnly"),
        "position_side": _read_semantic_field(order_intent, "position_side", "positionSide", "pos_side", "posSide"),
        "order_role": _read_semantic_field(order_intent, "order_role", "orderRole", "execution_role", "executionRole", "role"),
        "trigger_type": _read_semantic_field(order_intent, "trigger_type", "triggerType", "stop_type", "stopType"),
        "trigger_price": _read_semantic_field(order_intent, "trigger_price", "triggerPrice", "trigger_px", "triggerPx"),
        "stop_price": _read_semantic_field(order_intent, "stop_price", "stopPrice", "stop_px", "stopPx"),
        "trigger_direction": _read_semantic_field(order_intent, "trigger_direction", "triggerDirection"),
        "parent_order_id": _read_semantic_field(order_intent, "parent_order_id", "parentOrderId", "parent_cl_ord_id", "parentClOrdId"),
        "protection_order_id": _read_semantic_field(
            order_intent,
            "protection_order_id",
            "protectionOrderId",
            "protection_cl_ord_id",
            "protectionClOrdId",
            "protective_cl_ord_id",
        ),
        "algo_id": _read_semantic_field(order_intent, "algo_id", "algoId", "algo_cl_ord_id", "algoClOrdId", "protection_algo_id"),
        "oco_id": _read_semantic_field(
            order_intent,
            "oco_id",
            "ocoId",
            "oco_cl_ord_id",
            "ocoClOrdId",
            "attach_algo_cl_ord_id",
            "attachAlgoClOrdId",
        ),
    }
    return hashlib.sha256(_risk_canonical(fields)).hexdigest()


def _optional_float(value: Any) -> float | None:
    if value is None or value is _MISSING or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_risk_effect(value: RuntimeRiskEffect | str | object) -> str:
    candidate = getattr(value, "value", value)
    text = str(candidate or "").strip().upper()
    return text if text in _RUNTIME_RISK_EFFECTS else RuntimeRiskEffect.UNKNOWN.value


def _normalize_proof_action(value: RuntimeAction | str | object) -> str:
    if value is None:
        return ""
    return _normalize_action(value) if str(getattr(value, "value", value)).strip() else ""


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip()
    if len(text) != 64:
        return False
    return all(char in "0123456789abcdef" for char in text)


class _RuntimeRiskIssuerCapability:
    """Per-composition issuer capability; no module-global instance exists."""

    __slots__ = ("_issuer_id", "_issuance_token", "_sealed_records")

    def __init__(self, name: str = "") -> None:
        prefix = str(name).strip() or "runtime-risk"
        self._issuer_id = f"{prefix}-{uuid4().hex}"
        self._issuance_token = object()
        # The paired verifier consults this registry in addition to the proof
        # fields.  It detects object.__setattr__ tampering even when a caller
        # recomputes the public payload hash/signature.
        self._sealed_records: dict[int, tuple[object, str, str]] = {}

    def _register(self, evidence: object, payload_digest: str, signature: str) -> None:
        self._sealed_records[id(evidence)] = (evidence, payload_digest, signature)

    def _sealed_record_matches(self, evidence: object, payload_digest: str, signature: str) -> bool:
        record = self._sealed_records.get(id(evidence))
        return bool(record and record[0] is evidence and record[1] == payload_digest and record[2] == signature)


class RuntimeRiskEvidenceAuthority:
    """Composition-root authority that can be paired with one producer/verifier.

    The authority is intentionally instance-scoped.  Creating a second
    authority creates a different issuer identity, so its proofs cannot pass
    an evaluator composed with another authority's verifier.
    """

    __slots__ = ("_capability",)

    def __init__(self, *, name: str = "") -> None:
        self._capability = _RuntimeRiskIssuerCapability(name=name)

    def bind(self) -> tuple["RuntimeRiskEvidenceProducer", "RuntimeRiskEvidenceVerifier"]:
        return RuntimeRiskEvidenceProducer(self), RuntimeRiskEvidenceVerifier(self)


@dataclass(frozen=True)
class RuntimeAuthoritativeRiskResult:
    """Risk output bound to the actual order intent consumed by a producer."""

    intent_id: str
    intent_digest: str
    approved: bool
    actual_notional: float
    venue: str
    liquidation_safe: bool
    exposure: float
    # The fields below are optional for the pre-V3 normal path.  They become
    # mandatory when a kill/pause exception is requested, so legacy US/BTC
    # callers can continue to issue ordinary evidence without inventing
    # execution proof fields.
    action: str = ""
    risk_effect: str = RuntimeRiskEffect.UNKNOWN.value
    position_before: float | None = None
    position_after: float | None = None
    quantity: float | None = None
    max_quantity: float | None = None
    max_abs_position: float | None = None
    max_notional: float | None = None
    leverage: float | None = None
    max_leverage: float | None = None
    broker_snapshot_hash: str = ""
    ledger_snapshot_hash: str = ""
    strategy_snapshot_hash: str = ""
    risk_snapshot_hash: str = ""
    atomic_protection_replacement: bool = False

    @classmethod
    def from_order_intent(
        cls,
        order_intent: object | Mapping[str, Any],
        *,
        approved: bool,
        actual_notional: float,
        venue: str,
        liquidation_safe: bool,
        exposure: float,
        action: str = "",
        risk_effect: RuntimeRiskEffect | str = RuntimeRiskEffect.UNKNOWN,
        position_before: float | None = None,
        position_after: float | None = None,
        quantity: float | None = None,
        max_quantity: float | None = None,
        max_abs_position: float | None = None,
        max_notional: float | None = None,
        leverage: float | None = None,
        max_leverage: float | None = None,
        broker_snapshot_hash: str = "",
        ledger_snapshot_hash: str = "",
        strategy_snapshot_hash: str = "",
        risk_snapshot_hash: str = "",
        atomic_protection_replacement: bool = False,
    ) -> "RuntimeAuthoritativeRiskResult":
        return cls(
            intent_id=str(_read_field(order_intent, "order_intent_id", "intent_id", default="")),
            intent_digest=_risk_intent_digest(order_intent),
            approved=bool(approved),
            actual_notional=float(actual_notional),
            venue=str(venue).strip().lower(),
            liquidation_safe=bool(liquidation_safe),
            exposure=float(exposure),
            action=_normalize_proof_action(action),
            risk_effect=_normalize_risk_effect(risk_effect),
            position_before=_optional_float(position_before),
            position_after=_optional_float(position_after),
            quantity=_optional_float(quantity),
            max_quantity=_optional_float(max_quantity),
            max_abs_position=_optional_float(max_abs_position),
            max_notional=_optional_float(max_notional),
            leverage=_optional_float(leverage),
            max_leverage=_optional_float(max_leverage),
            broker_snapshot_hash=str(broker_snapshot_hash or ""),
            ledger_snapshot_hash=str(ledger_snapshot_hash or ""),
            strategy_snapshot_hash=str(strategy_snapshot_hash or ""),
            risk_snapshot_hash=str(risk_snapshot_hash or ""),
            atomic_protection_replacement=(
                atomic_protection_replacement if type(atomic_protection_replacement) is bool else False
            ),
        )

    def verify(self, order_intent: object | Mapping[str, Any]) -> bool:
        return (
            self.intent_id == str(_read_field(order_intent, "order_intent_id", "intent_id", default=""))
            and self.intent_digest == _risk_intent_digest(order_intent)
            and bool(self.venue)
            and math.isfinite(self.actual_notional)
            and self.actual_notional > 0.0
            and math.isfinite(self.exposure)
            and self.exposure >= 0.0
        )


class RuntimeRiskEvidence:
    """Canonical, short-lived proof issued by the trusted risk producer.

    Direct construction is intentionally impossible.  Evaluator acceptance
    requires a producer-issued signature, a paired verifier identity, and all
    bindings to match the actual order intent and current runtime identity.
    """

    __slots__ = (
        "_issuer_capability",
        "_issuer_id",
        "_intent_id",
        "_intent_digest",
        "_source_head",
        "_account_identity",
        "_session_id",
        "_key_namespace",
        "_client_order_namespace",
        "_epoch",
        "_approved",
        "_actual_notional",
        "_venue",
        "_liquidation_safe",
        "_exposure",
        "_action",
        "_risk_effect",
        "_position_before",
        "_position_after",
        "_quantity",
        "_max_quantity",
        "_max_abs_position",
        "_max_notional",
        "_leverage",
        "_max_leverage",
        "_broker_snapshot_hash",
        "_ledger_snapshot_hash",
        "_strategy_snapshot_hash",
        "_risk_snapshot_hash",
        "_atomic_protection_replacement",
        "_evidence_id",
        "_issued_at",
        "_expires_at",
        "_signature",
        "_sealed",
    )

    def __init__(self, *, _capability: object | None = None, **values: Any) -> None:
        if type(_capability) is not _RuntimeRiskIssuerCapability:
            raise RuntimeRiskEvidenceError("risk_evidence_direct_construction_forbidden")
        if values.pop("_issuance_token", None) is not _capability._issuance_token:
            raise RuntimeRiskEvidenceError("risk_evidence_issuer_capability_required")
        object.__setattr__(self, "_sealed", False)
        self._issuer_capability = _capability
        self._issuer_id = str(values["issuer_id"])
        self._intent_id = str(values["intent_id"])
        self._intent_digest = str(values["intent_digest"])
        self._source_head = str(values["source_head"])
        self._account_identity = str(values["account_identity"])
        self._session_id = str(values["session_id"])
        self._key_namespace = str(values["key_namespace"])
        self._client_order_namespace = str(values["client_order_namespace"])
        self._epoch = None if values.get("epoch") is None else int(values["epoch"])
        self._approved = bool(values["approved"])
        self._actual_notional = float(values["actual_notional"])
        self._venue = str(values["venue"]).strip().lower()
        self._liquidation_safe = bool(values["liquidation_safe"])
        self._exposure = float(values["exposure"])
        self._action = _normalize_proof_action(values.get("action", ""))
        self._risk_effect = _normalize_risk_effect(values.get("risk_effect", RuntimeRiskEffect.UNKNOWN.value))
        self._position_before = _optional_float(values.get("position_before"))
        self._position_after = _optional_float(values.get("position_after"))
        self._quantity = _optional_float(values.get("quantity"))
        self._max_quantity = _optional_float(values.get("max_quantity"))
        self._max_abs_position = _optional_float(values.get("max_abs_position"))
        self._max_notional = _optional_float(values.get("max_notional"))
        self._leverage = _optional_float(values.get("leverage"))
        self._max_leverage = _optional_float(values.get("max_leverage"))
        self._broker_snapshot_hash = str(values.get("broker_snapshot_hash", "") or "")
        self._ledger_snapshot_hash = str(values.get("ledger_snapshot_hash", "") or "")
        self._strategy_snapshot_hash = str(values.get("strategy_snapshot_hash", "") or "")
        self._risk_snapshot_hash = str(values.get("risk_snapshot_hash", "") or "")
        atomic_replacement = values.get("atomic_protection_replacement", False)
        self._atomic_protection_replacement = atomic_replacement if type(atomic_replacement) is bool else False
        self._evidence_id = str(values["evidence_id"])
        self._issued_at = ensure_utc(values["issued_at"])
        self._expires_at = ensure_utc(values["expires_at"])
        self._signature = str(values["signature"])
        if self._issuer_id != _capability._issuer_id:
            raise RuntimeRiskEvidenceError("risk_evidence_issuer_identity_mismatch")
        _capability._register(self, self._payload_digest(), self._signature)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise RuntimeRiskEvidenceError("risk_evidence_sealed")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_sealed", False):
            raise RuntimeRiskEvidenceError("risk_evidence_sealed")
        object.__delattr__(self, name)

    def __copy__(self) -> "RuntimeRiskEvidence":
        raise RuntimeRiskEvidenceError("risk_evidence_copy_forbidden")

    def __deepcopy__(self, memo: dict[int, Any]) -> "RuntimeRiskEvidence":
        raise RuntimeRiskEvidenceError("risk_evidence_copy_forbidden")

    @classmethod
    def issue(cls, **values: Any) -> "RuntimeRiskEvidence":
        raise RuntimeRiskEvidenceError("public_risk_evidence_issuance_forbidden")

    issued = issue

    @property
    def issuer_id(self) -> str:
        return self._issuer_id

    @property
    def intent_id(self) -> str:
        return self._intent_id

    @property
    def order_intent_id(self) -> str:
        return self._intent_id

    @property
    def intent_digest(self) -> str:
        return self._intent_digest

    @property
    def source_head(self) -> str:
        return self._source_head

    @property
    def account_identity(self) -> str:
        return self._account_identity

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def key_namespace(self) -> str:
        return self._key_namespace

    @property
    def client_order_namespace(self) -> str:
        return self._client_order_namespace

    @property
    def epoch(self) -> int | None:
        return self._epoch

    @property
    def approved(self) -> bool:
        return self._approved

    @property
    def actual_notional(self) -> float:
        return self._actual_notional

    @property
    def venue(self) -> str:
        return self._venue

    @property
    def liquidation_safe(self) -> bool:
        return self._liquidation_safe

    @property
    def exposure(self) -> float:
        return self._exposure

    @property
    def action(self) -> str:
        return self._action

    @property
    def risk_effect(self) -> str:
        return self._risk_effect

    @property
    def position_before(self) -> float | None:
        return self._position_before

    @property
    def position_after(self) -> float | None:
        return self._position_after

    @property
    def quantity(self) -> float | None:
        return self._quantity

    @property
    def max_quantity(self) -> float | None:
        return self._max_quantity

    @property
    def max_abs_position(self) -> float | None:
        return self._max_abs_position

    @property
    def max_notional(self) -> float | None:
        return self._max_notional

    @property
    def leverage(self) -> float | None:
        return self._leverage

    @property
    def max_leverage(self) -> float | None:
        return self._max_leverage

    @property
    def broker_snapshot_hash(self) -> str:
        return self._broker_snapshot_hash

    @property
    def ledger_snapshot_hash(self) -> str:
        return self._ledger_snapshot_hash

    @property
    def strategy_snapshot_hash(self) -> str:
        return self._strategy_snapshot_hash

    @property
    def risk_snapshot_hash(self) -> str:
        return self._risk_snapshot_hash

    @property
    def atomic_protection_replacement(self) -> bool:
        return self._atomic_protection_replacement

    @property
    def evidence_id(self) -> str:
        return self._evidence_id

    @property
    def issued_at(self) -> datetime:
        return self._issued_at

    @property
    def expires_at(self) -> datetime:
        return self._expires_at

    def _signed_payload(self) -> dict[str, Any]:
        return {
            "issuer_id": self._issuer_id,
            "intent_id": self._intent_id,
            "intent_digest": self._intent_digest,
            "source_head": self._source_head,
            "account_identity": self._account_identity,
            "session_id": self._session_id,
            "key_namespace": self._key_namespace,
            "client_order_namespace": self._client_order_namespace,
            "epoch": self._epoch,
            "approved": self._approved,
            "actual_notional": self._actual_notional,
            "venue": self._venue,
            "liquidation_safe": self._liquidation_safe,
            "exposure": self._exposure,
            "action": self._action,
            "risk_effect": self._risk_effect,
            "position_before": self._position_before,
            "position_after": self._position_after,
            "quantity": self._quantity,
            "max_quantity": self._max_quantity,
            "max_abs_position": self._max_abs_position,
            "max_notional": self._max_notional,
            "leverage": self._leverage,
            "max_leverage": self._max_leverage,
            "broker_snapshot_hash": self._broker_snapshot_hash,
            "ledger_snapshot_hash": self._ledger_snapshot_hash,
            "strategy_snapshot_hash": self._strategy_snapshot_hash,
            "risk_snapshot_hash": self._risk_snapshot_hash,
            "atomic_protection_replacement": self._atomic_protection_replacement,
            "evidence_id": self._evidence_id,
            "issued_at": isoformat_utc(self._issued_at),
            "expires_at": isoformat_utc(self._expires_at),
        }

    def _payload_digest(self) -> str:
        return hashlib.sha256(_risk_canonical(self._signed_payload())).hexdigest()

    def verify(
        self,
        *,
        verifier: "RuntimeRiskEvidenceVerifier | None" = None,
        order_intent: object | Mapping[str, Any] | None,
        source_head: str,
        account_identity: str,
        session_id: str,
        key_namespace: str,
        client_order_namespace: str,
        epoch: int | None,
        now: datetime | None = None,
    ) -> bool:
        if type(verifier) is not RuntimeRiskEvidenceVerifier:
            return False
        return verifier.verify(
            self,
            order_intent=order_intent,
            source_head=source_head,
            account_identity=account_identity,
            session_id=session_id,
            key_namespace=key_namespace,
            client_order_namespace=client_order_namespace,
            epoch=epoch,
            now=now,
        )

    def _verify_payload(
        self,
        *,
        order_intent: object | Mapping[str, Any] | None,
        source_head: str,
        account_identity: str,
        session_id: str,
        key_namespace: str,
        client_order_namespace: str,
        epoch: int | None,
        now: datetime | None = None,
    ) -> bool:
        if self._sealed is not True:
            return False
        if self._issuer_id != self._issuer_capability._issuer_id:
            return False
        current = ensure_utc(now or utc_now())
        if current < self._issued_at or current >= self._expires_at:
            return False
        if self._intent_digest != _risk_intent_digest(order_intent):
            return False
        if self._intent_id != str(_read_field(order_intent, "order_intent_id", "intent_id", default="")):
            return False
        if self._source_head != str(source_head):
            return False
        if self._account_identity != str(account_identity):
            return False
        if self._session_id != str(session_id):
            return False
        if self._key_namespace != str(key_namespace):
            return False
        if self._client_order_namespace != str(client_order_namespace):
            return False
        if self._epoch != epoch:
            return False
        if not self._approved or not self._liquidation_safe:
            return False
        if not self._venue or not math.isfinite(self._actual_notional) or self._actual_notional <= 0.0:
            return False
        if not math.isfinite(self._exposure) or self._exposure < 0.0:
            return False
        expected_signature = hashlib.sha256(_risk_canonical(self._signed_payload())).hexdigest()
        if self._signature != expected_signature:
            return False
        return self._issuer_capability._sealed_record_matches(
            self,
            hashlib.sha256(_risk_canonical(self._signed_payload())).hexdigest(),
            self._signature,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self._signed_payload()
        payload["signature"] = self._signature
        payload["proof_type"] = "canonical_runtime_risk_evidence"
        return payload


class RuntimeRiskEvidenceVerifier:
    """Verifier paired to exactly one :class:`RuntimeRiskEvidenceAuthority`."""

    __slots__ = ("_capability",)

    def __init__(self, authority: RuntimeRiskEvidenceAuthority) -> None:
        if type(authority) is not RuntimeRiskEvidenceAuthority:
            raise RuntimeRiskEvidenceError("risk_evidence_verifier_requires_authority")
        self._capability = authority._capability

    def _matches(self, evidence: object) -> bool:
        return type(evidence) is RuntimeRiskEvidence and evidence._issuer_capability is self._capability

    def verify(
        self,
        evidence: object,
        *,
        order_intent: object | Mapping[str, Any] | None,
        source_head: str,
        account_identity: str,
        session_id: str,
        key_namespace: str,
        client_order_namespace: str,
        epoch: int | None,
        now: datetime | None = None,
    ) -> bool:
        if not self._matches(evidence):
            return False
        return evidence._verify_payload(
            order_intent=order_intent,
            source_head=source_head,
            account_identity=account_identity,
            session_id=session_id,
            key_namespace=key_namespace,
            client_order_namespace=client_order_namespace,
            epoch=epoch,
            now=now,
        )


class RuntimeRiskEvidenceProducer:
    """Issuer capability paired to one authority; no global producer exists."""

    __slots__ = ("_capability", "_issuer_id")

    def __init__(self, authority: RuntimeRiskEvidenceAuthority | None = None) -> None:
        if type(authority) is not RuntimeRiskEvidenceAuthority:
            raise RuntimeRiskEvidenceError("risk_evidence_producer_requires_authority")
        self._capability = authority._capability
        self._issuer_id = self._capability._issuer_id

    def issue(
        self, **_: Any
    ) -> RuntimeRiskEvidence:
        raise RuntimeRiskEvidenceError("public_risk_evidence_producer_issue_forbidden")

    def issue_from_authoritative(
        self,
        *,
        order_intent: object | Mapping[str, Any],
        authoritative_result: RuntimeAuthoritativeRiskResult,
        source_head: str,
        account_identity: str,
        session_id: str,
        key_namespace: str,
        client_order_namespace: str,
        epoch: int,
        ttl_seconds: float = 5.0,
        issued_at: datetime | None = None,
        evidence_id: str = "",
    ) -> RuntimeRiskEvidence:
        if type(authoritative_result) is not RuntimeAuthoritativeRiskResult:
            raise RuntimeRiskEvidenceError("authoritative_risk_result_required")
        if not authoritative_result.verify(order_intent):
            raise RuntimeRiskEvidenceError("authoritative_risk_result_invalid")
        issued = ensure_utc(issued_at or utc_now())
        ttl = max(0.1, min(float(ttl_seconds), 30.0))
        expires = issued + timedelta(seconds=ttl)
        digest = _risk_intent_digest(order_intent)
        intent_id = str(_read_field(order_intent, "order_intent_id", "intent_id", default=""))
        generated_id = evidence_id.strip() or hashlib.sha256(
            _risk_canonical({"intent_digest": digest, "issued_at": isoformat_utc(issued)})
        ).hexdigest()[:32]
        values = {
            "issuer_id": self._issuer_id,
            "intent_id": intent_id,
            "intent_digest": digest,
            "source_head": str(source_head),
            "account_identity": str(account_identity),
            "session_id": str(session_id),
            "key_namespace": str(key_namespace),
            "client_order_namespace": str(client_order_namespace),
            "epoch": int(epoch),
            "approved": authoritative_result.approved,
            "actual_notional": authoritative_result.actual_notional,
            "venue": authoritative_result.venue,
            "liquidation_safe": authoritative_result.liquidation_safe,
            "exposure": authoritative_result.exposure,
            "action": authoritative_result.action,
            "risk_effect": authoritative_result.risk_effect,
            "position_before": authoritative_result.position_before,
            "position_after": authoritative_result.position_after,
            "quantity": authoritative_result.quantity,
            "max_quantity": authoritative_result.max_quantity,
            "max_abs_position": authoritative_result.max_abs_position,
            "max_notional": authoritative_result.max_notional,
            "leverage": authoritative_result.leverage,
            "max_leverage": authoritative_result.max_leverage,
            "broker_snapshot_hash": authoritative_result.broker_snapshot_hash,
            "ledger_snapshot_hash": authoritative_result.ledger_snapshot_hash,
            "strategy_snapshot_hash": authoritative_result.strategy_snapshot_hash,
            "risk_snapshot_hash": authoritative_result.risk_snapshot_hash,
            "atomic_protection_replacement": authoritative_result.atomic_protection_replacement,
            "evidence_id": generated_id,
            "issued_at": issued,
            "expires_at": expires,
        }
        signed_payload = dict(values)
        signed_payload["issued_at"] = isoformat_utc(issued)
        signed_payload["expires_at"] = isoformat_utc(expires)
        values["signature"] = hashlib.sha256(_risk_canonical(signed_payload)).hexdigest()
        values["_issuance_token"] = self._capability._issuance_token
        return RuntimeRiskEvidence(_capability=self._capability, **values)


# Descriptive type alias retained for adapters that call the issued object a proof.
RuntimeRiskEvidenceProof = RuntimeRiskEvidence


@dataclass(frozen=True)
class RuntimePermissionContext:
    """Evidence supplied to the final execution permission boundary.

    The fields are deliberately typed as ``object``/mapping rather than
    importing a venue's contracts into ``quant_shared``.  This keeps the
    shared evaluator canonical while allowing BTC, US, and future adapters to
    pass their concrete ``OrderIntent``/``RiskDecision`` records.

    ``ActionAuthorizationV3`` is deliberately not a field here: it is a
    read-model decision record, never an execution capability or kill proof.
    """

    order_intent: object | None = None
    risk_decision: object | None = None
    broker_truth: object | Mapping[str, Any] | None = None
    ledger_freshness: object | Mapping[str, Any] | None = None
    endpoint_capability: object | Mapping[str, Any] | None = None
    execution_identity: object | Mapping[str, Any] | None = None
    lifecycle: object | Mapping[str, Any] | None = None
    expected_mode: str | None = None
    risk_evidence: object | Mapping[str, Any] | None = None
    current_head: str | None = None
    session_id: str | None = None
    epoch: int | None = None
    broker_snapshot_hash: str | None = None
    ledger_snapshot_hash: str | None = None
    strategy_snapshot_hash: str | None = None
    risk_snapshot_hash: str | None = None

    @classmethod
    def from_values(cls, **values: Any) -> "RuntimePermissionContext":
        allowed = {
            "order_intent",
            "risk_decision",
            "broker_truth",
            "ledger_freshness",
            "endpoint_capability",
            "execution_identity",
            "lifecycle",
            "expected_mode",
            "risk_evidence",
            "current_head",
            "session_id",
            "epoch",
            "broker_snapshot_hash",
            "ledger_snapshot_hash",
            "strategy_snapshot_hash",
            "risk_snapshot_hash",
        }
        return cls(**{key: values.get(key) for key in allowed})


class PermissionEvaluator:
    """Evaluate actions against one immutable :class:`RuntimeSnapshot`."""

    def __init__(
        self,
        snapshot: RuntimeSnapshot | Mapping[str, Any],
        *,
        risk_verifier: RuntimeRiskEvidenceVerifier | None = None,
    ) -> None:
        if isinstance(snapshot, RuntimeSnapshot):
            self.snapshot = snapshot
        else:
            # RuntimeSnapshot.from_dict performs unknown-state/mode conversion
            # and therefore keeps this boundary fail-closed.
            self.snapshot = RuntimeSnapshot.from_dict(snapshot)
        if risk_verifier is not None and type(risk_verifier) is not RuntimeRiskEvidenceVerifier:
            raise RuntimeRiskEvidenceError("runtime_risk_verifier_required")
        # Only the verifier is retained.  The issuer/producer capability never
        # crosses into or out of the evaluator composition.
        self._risk_verifier = risk_verifier

    @classmethod
    def from_snapshot(
        cls,
        snapshot: RuntimeSnapshot | Mapping[str, Any],
        *,
        risk_verifier: RuntimeRiskEvidenceVerifier | None = None,
    ) -> "PermissionEvaluator":
        return cls(snapshot, risk_verifier=risk_verifier)

    def _new_order_reasons(self) -> tuple[str, ...]:
        snapshot = self.snapshot
        reasons: list[str] = []
        if snapshot.state != RuntimeState.READY:
            reasons.append("runtime_state_not_ready")
        if snapshot.trading_mode != TradingMode.NORMAL:
            reasons.append("trading_mode_not_normal")
        if not snapshot.reconciliation_passed:
            reasons.append("reconciliation_not_passed")
        if snapshot.block_new_orders:
            reasons.append("block_new_orders")
        if not snapshot.risk_state_valid:
            reasons.append("risk_state_invalid")
        if snapshot.kill_switch_tripped:
            reasons.append("kill_switch_tripped")
        if not snapshot.broker_truth_fresh:
            reasons.append("broker_truth_not_fresh")
        if not snapshot.account_verified:
            reasons.append("account_not_verified")
        if snapshot.recovery_requires_ack and not snapshot.operator_acknowledged:
            reasons.append("recovery_operator_ack_required")
        if snapshot.blockers:
            reasons.extend(f"blocker:{item}" for item in snapshot.blockers)
        return tuple(dict.fromkeys(reasons))

    def new_order_decision(self) -> PermissionDecision:
        reasons = self._new_order_reasons()
        return PermissionDecision("submit_new_order", not reasons, reasons)

    # Explicit aliases make the public contract discoverable for adapters.
    submit_new_order_decision = new_order_decision
    evaluate_new_order = new_order_decision
    can_submit_new_order_decision = new_order_decision

    def can_submit_new_order(self) -> bool:
        return bool(self.new_order_decision())

    def reduce_position_decision(self) -> PermissionDecision:
        """Return the legacy reduction permission, fail-closed during kill.

        Older US paper callers use this boolean as their final gate.  It must
        therefore stay false while a kill is active; strict callers that have
        a canonical proof use :meth:`evaluate_action` instead.
        """

        decision = self.reduce_transport_decision()
        if self.snapshot.kill_switch_tripped:
            return PermissionDecision(
                "reduce_position",
                False,
                (*decision.reasons, "kill_switch_requires_signed_action_proof"),
            )
        return decision

    def reduce_transport_decision(self) -> PermissionDecision:
        """Report transport capability without granting an execution action."""

        snapshot = self.snapshot
        reasons: list[str] = []
        if snapshot.state not in {
            RuntimeState.READY,
            RuntimeState.DEGRADED,
            RuntimeState.RECONCILING,
            RuntimeState.RECOVERY_PENDING,
        }:
            reasons.append("runtime_state_does_not_support_reduction")
        if snapshot.trading_mode not in {TradingMode.NORMAL, TradingMode.REDUCE_ONLY}:
            reasons.append("trading_mode_does_not_support_reduction")
        if not snapshot.connected:
            reasons.append("transport_not_connected")
        if not snapshot.account_verified:
            reasons.append("account_not_verified")
        if not snapshot.broker_truth_fresh:
            reasons.append("broker_truth_not_fresh")
        if snapshot.recovery_requires_ack and not snapshot.operator_acknowledged:
            reasons.append("recovery_operator_ack_required")
        return PermissionDecision("reduce_position", not reasons, tuple(dict.fromkeys(reasons)))

    def can_reduce_transport(self) -> bool:
        return bool(self.reduce_transport_decision())

    def can_reduce_position(self) -> bool:
        return bool(self.reduce_position_decision())

    def cancel_order_decision(self) -> PermissionDecision:
        """Return the legacy cancel permission, fail-closed during kill."""

        decision = self.cancel_transport_decision()
        if self.snapshot.kill_switch_tripped:
            return PermissionDecision(
                "cancel_order",
                False,
                (*decision.reasons, "kill_switch_requires_signed_action_proof"),
            )
        return decision

    def cancel_transport_decision(self) -> PermissionDecision:
        """Report cancel transport capability without granting an action."""

        snapshot = self.snapshot
        reasons: list[str] = []
        if snapshot.state in {
            RuntimeState.OFFLINE,
            RuntimeState.RECONNECTING,
            RuntimeState.HALTED,
        }:
            reasons.append("runtime_state_does_not_support_broker_cancel")
        if snapshot.trading_mode in {TradingMode.FROZEN, TradingMode.NO_TRANSPORT}:
            reasons.append("trading_mode_does_not_support_broker_cancel")
        if not snapshot.connected:
            reasons.append("transport_not_connected")
        if not snapshot.account_verified:
            reasons.append("account_not_verified")
        return PermissionDecision("cancel_order", not reasons, tuple(dict.fromkeys(reasons)))

    def can_cancel_transport(self) -> bool:
        return bool(self.cancel_transport_decision())

    def can_cancel_order(self) -> bool:
        return bool(self.cancel_order_decision())

    def query_broker_decision(self) -> PermissionDecision:
        snapshot = self.snapshot
        reasons: list[str] = []
        if not snapshot.connected:
            reasons.append("transport_not_connected")
        if snapshot.state in {
            RuntimeState.OFFLINE,
            RuntimeState.RECONNECTING,
            RuntimeState.HALTED,
        }:
            reasons.append("runtime_state_does_not_support_query")
        return PermissionDecision("query_broker", not reasons, tuple(dict.fromkeys(reasons)))

    def can_query_broker(self) -> bool:
        return bool(self.query_broker_decision())

    def evaluate_action(
        self,
        action: RuntimeAction | str,
        context: RuntimePermissionContext | Mapping[str, Any] | None = None,
        **evidence: Any,
    ) -> PermissionDecision:
        """Evaluate one concrete execution action against actual evidence.

        This is the strict boundary used by the BTC canary.  It intentionally
        does not accept caller-provided ``ready``, ``risk`` or ``notional``
        booleans as authority.  The order intent, risk decision, broker truth,
        ledger freshness, endpoint capability, and execution identity are
        inspected independently and every missing/invalid observation blocks
        the action.

        ``context`` may be a :class:`RuntimePermissionContext`, a mapping, or
        omitted in favour of keyword evidence.  Keeping the legacy
        ``new_order_decision``/``can_submit_new_order`` methods unchanged
        avoids widening the US IBKR contract while giving BTC one canonical
        evaluator for every order-side action.
        """

        normalized = _normalize_action(action)
        if context is None:
            context_obj = RuntimePermissionContext.from_values(**evidence)
        elif isinstance(context, RuntimePermissionContext):
            if evidence:
                values = {**context.__dict__, **evidence}
                context_obj = RuntimePermissionContext.from_values(**values)
            else:
                context_obj = context
        else:
            values = {**dict(context), **evidence}
            context_obj = RuntimePermissionContext.from_values(**values)

        reasons: list[str] = []
        reasons.extend(_intent_reasons(context_obj.order_intent))
        reasons.extend(_risk_reasons(context_obj.order_intent, context_obj.risk_decision))
        reasons.extend(
            _risk_evidence_reasons(
                context_obj.order_intent,
                context_obj.risk_decision,
                context_obj.risk_evidence,
                context_obj.broker_truth,
                context_obj.execution_identity,
                self._risk_verifier,
                current_head=context_obj.current_head,
                session_id=context_obj.session_id,
                epoch=context_obj.epoch,
                action=normalized,
                kill_switch_tripped=self.snapshot.kill_switch_tripped,
                broker_snapshot_hash=context_obj.broker_snapshot_hash,
                ledger_snapshot_hash=context_obj.ledger_snapshot_hash,
                strategy_snapshot_hash=context_obj.strategy_snapshot_hash,
                risk_snapshot_hash=context_obj.risk_snapshot_hash,
            )
        )
        reasons.extend(_freshness_reasons(context_obj.broker_truth, context_obj.ledger_freshness))
        reasons.extend(_identity_reasons(context_obj.execution_identity, context_obj.expected_mode))
        reasons.extend(_capability_reasons(normalized, context_obj.endpoint_capability))
        reasons.extend(_runtime_action_reasons(self.snapshot, normalized))
        reasons.extend(_lifecycle_reasons(normalized, context_obj.lifecycle, context_obj.order_intent))

        return PermissionDecision(
            normalized,
            not _dedupe(reasons),
            tuple(_dedupe(reasons)),
        )

    # Public aliases make the final boundary discoverable to adapters without
    # permitting each adapter to grow a private copy of the policy.
    evaluate_execution_action = evaluate_action
    evaluate_order_action = evaluate_action
    authorize_action = evaluate_action
    evaluate_final_action = evaluate_action
    evaluate_btc_action = evaluate_action

    def action_decision(
        self,
        action: RuntimeAction | str,
        *,
        order_intent: object | None,
        risk_decision: object | None,
        broker_truth: object | Mapping[str, Any] | None,
        ledger_freshness: object | Mapping[str, Any] | None,
        endpoint_capability: object | Mapping[str, Any] | None,
        execution_identity: object | Mapping[str, Any] | None,
        lifecycle: object | Mapping[str, Any] | None = None,
        expected_mode: str | None = None,
        risk_evidence: object | Mapping[str, Any] | None = None,
        current_head: str | None = None,
        session_id: str | None = None,
        epoch: int | None = None,
        broker_snapshot_hash: str | None = None,
        ledger_snapshot_hash: str | None = None,
        strategy_snapshot_hash: str | None = None,
        risk_snapshot_hash: str | None = None,
    ) -> PermissionDecision:
        """Keyword-only spelling for callers that prefer an explicit API."""

        return self.evaluate_action(
            action,
            RuntimePermissionContext(
                order_intent=order_intent,
                risk_decision=risk_decision,
                broker_truth=broker_truth,
                ledger_freshness=ledger_freshness,
                endpoint_capability=endpoint_capability,
                execution_identity=execution_identity,
                lifecycle=lifecycle,
                expected_mode=expected_mode,
                risk_evidence=risk_evidence,
                current_head=current_head,
                session_id=session_id,
                epoch=epoch,
                broker_snapshot_hash=broker_snapshot_hash,
                ledger_snapshot_hash=ledger_snapshot_hash,
                strategy_snapshot_hash=strategy_snapshot_hash,
                risk_snapshot_hash=risk_snapshot_hash,
            ),
        )

    def evaluate(self) -> dict[str, PermissionDecision]:
        return {
            "submit_new_order": self.new_order_decision(),
            "reduce_position": self.reduce_position_decision(),
            "cancel_order": self.cancel_order_decision(),
            "query_broker": self.query_broker_decision(),
        }

    @property
    def permissions(self) -> dict[str, PermissionDecision]:
        return self.evaluate()


_MISSING = object()


def _normalize_action(action: RuntimeAction | str) -> str:
    value = action.value if isinstance(action, RuntimeAction) else str(action)
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "new_order": RuntimeAction.SUBMIT_NEW_ORDER.value,
        "submit_order": RuntimeAction.SUBMIT_NEW_ORDER.value,
        "order": RuntimeAction.SUBMIT_NEW_ORDER.value,
        "cancel": RuntimeAction.CANCEL_ORDER.value,
        "replace": RuntimeAction.REPLACE_ORDER.value,
        "reduce_position": RuntimeAction.REDUCE_ONLY.value,
        "reduce_only_order": RuntimeAction.REDUCE_ONLY.value,
        "protection": RuntimeAction.ATTACH_PROTECTION.value,
        "attach_stop": RuntimeAction.ATTACH_PROTECTION.value,
        "deadman": RuntimeAction.DEAD_MAN.value,
        "dead_man_switch": RuntimeAction.DEAD_MAN.value,
    }
    return aliases.get(normalized, normalized)


def _read_field(value: object | Mapping[str, Any] | None, *names: str, default: Any = _MISSING) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        try:
            candidate = getattr(value, name)
        except AttributeError:
            continue
        if callable(candidate) and name.startswith("is_"):
            try:
                candidate = candidate()
            except TypeError:
                pass
        return candidate
    return default


def _read_semantic_field(value: object | Mapping[str, Any] | None, *names: str) -> Any:
    """Read an explicit execution semantic from top-level or known metadata."""

    direct = _read_field(value, *names, default=_MISSING)
    if direct is not _MISSING and direct is not None:
        return direct
    metadata = _read_field(value, "metadata", "execution_metadata", "order_metadata", default=None)
    return _read_field(metadata, *names, default=None)


def _as_bool(value: Any) -> bool | None:
    if value is _MISSING or value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "ok", "pass", "passed", "fresh", "ready"}:
            return True
        if lowered in {"false", "no", "0", "unknown", "stale", "failed", "blocked"}:
            return False
    return bool(value)


def _value_text(value: Any, *, default: str = "") -> str:
    candidate = getattr(value, "value", value)
    if candidate is None:
        return default
    return str(candidate).strip().lower()


def _intent_reasons(order_intent: object | None) -> list[str]:
    if order_intent is None:
        return ["order_intent_missing"]
    reasons: list[str] = []
    client_id = _read_field(order_intent, "client_order_id", "cl_ord_id", "clOrdId", default="")
    intent_id = _read_field(order_intent, "order_intent_id", "intent_id", default="")
    symbol = _read_field(order_intent, "symbol", default="")
    quantity = _read_field(order_intent, "quantity", "qty", default=_MISSING)
    if not str(client_id).strip():
        reasons.append("order_intent_client_order_id_missing")
    if not str(intent_id).strip():
        reasons.append("order_intent_id_missing")
    if not str(symbol).strip():
        reasons.append("order_intent_symbol_missing")
    try:
        quantity_value = float(quantity)
    except (TypeError, ValueError):
        quantity_value = 0.0
    if quantity is _MISSING or quantity_value <= 0.0:
        reasons.append("order_intent_quantity_invalid")
    side = _read_field(order_intent, "side", default=_MISSING)
    if side is _MISSING or not str(side).strip():
        reasons.append("order_intent_side_missing")
    return reasons


def _risk_reasons(order_intent: object | None, risk_decision: object | None) -> list[str]:
    if risk_decision is None:
        return ["risk_decision_missing"]
    reasons: list[str] = []
    approved = _as_bool(_read_field(risk_decision, "approved", "risk_approved", default=_MISSING))
    if approved is not True:
        reasons.append("risk_decision_not_approved")
    intent_id = _read_field(order_intent, "order_intent_id", "intent_id", default="")
    risk_intent_id = _read_field(risk_decision, "order_intent_id", "intent_id", default="")
    if not intent_id or not risk_intent_id or str(intent_id) != str(risk_intent_id):
        reasons.append("risk_decision_order_intent_mismatch")
    reason = _read_field(risk_decision, "reason", "decision_reason", default="")
    if approved is True and not str(reason).strip():
        reasons.append("risk_decision_reason_missing")
    adjusted = _read_field(risk_decision, "adjusted_quantity", default=_MISSING)
    if adjusted is not _MISSING and adjusted is not None:
        try:
            adjusted_value = float(adjusted)
            intent_qty = float(_read_field(order_intent, "quantity", "qty", default=0.0))
            if adjusted_value <= 0.0 or adjusted_value > intent_qty:
                reasons.append("risk_decision_adjusted_quantity_invalid")
        except (TypeError, ValueError):
            reasons.append("risk_decision_adjusted_quantity_invalid")
    return reasons


def _risk_evidence_reasons(
    order_intent: object | None,
    risk_decision: object | None,
    risk_evidence: object | Mapping[str, Any] | None,
    broker_truth: object | Mapping[str, Any] | None,
    identity: object | Mapping[str, Any] | None,
    risk_verifier: RuntimeRiskEvidenceVerifier | None,
    *,
    current_head: str | None,
    session_id: str | None,
    epoch: int | None,
    action: str,
    kill_switch_tripped: bool,
    broker_snapshot_hash: str | None,
    ledger_snapshot_hash: str | None,
    strategy_snapshot_hash: str | None,
    risk_snapshot_hash: str | None,
) -> list[str]:
    """Validate the independent evidence record used by the final boundary.

    This function intentionally never reads ``order_intent.metadata`` or a
    risk/ready/notional value supplied through a caller convenience argument.
    The evidence must be independently issued and match the current runtime
    identity and source head byte-for-byte.
    """

    if risk_evidence is None:
        reasons = ["risk_evidence_missing"]
        if kill_switch_tripped:
            reasons.extend(
                _kill_exception_reasons(
                    action=action,
                    risk_evidence=None,
                    order_intent=order_intent,
                    current_head=current_head,
                    broker_snapshot_hash=broker_snapshot_hash,
                    ledger_snapshot_hash=ledger_snapshot_hash,
                    strategy_snapshot_hash=strategy_snapshot_hash,
                    risk_snapshot_hash=risk_snapshot_hash,
                )
            )
        return _dedupe(reasons)
    if type(risk_evidence) is not RuntimeRiskEvidence:
        reasons = ["risk_evidence_proof_required", "risk_evidence_untrusted_issuer"]
        if kill_switch_tripped:
            reasons.extend(
                _kill_exception_reasons(
                    action=action,
                    risk_evidence=risk_evidence,
                    order_intent=order_intent,
                    current_head=current_head,
                    broker_snapshot_hash=broker_snapshot_hash,
                    ledger_snapshot_hash=ledger_snapshot_hash,
                    strategy_snapshot_hash=strategy_snapshot_hash,
                    risk_snapshot_hash=risk_snapshot_hash,
                )
            )
        return _dedupe(reasons)
    reasons: list[str] = []
    expected_account = _read_field(
        identity,
        "account_identity",
        "account_hash",
        "account_id_hash",
        "account_id",
        default="",
    )
    expected_session = session_id or _read_field(identity, "session_id", "session", "broker_session_id", default="")
    expected_key = _read_field(identity, "key_namespace", "credential_namespace", "service_namespace", default="")
    expected_client = _read_field(
        identity,
        "client_order_namespace",
        "clord_namespace",
        "client_namespace",
        default="",
    )
    expected_epoch = epoch
    if expected_epoch is None:
        expected_epoch = _read_field(
            identity,
            "epoch",
            "connection_epoch",
            "session_epoch",
            "runtime_epoch",
            default=_MISSING,
        )
    if risk_verifier is None:
        reasons = ["risk_evidence_verifier_missing", "risk_evidence_untrusted_issuer"]
        proof_valid = False
    elif not risk_verifier._matches(risk_evidence):
        reasons = ["risk_evidence_verifier_mismatch", "risk_evidence_untrusted_issuer"]
        proof_valid = False
    else:
        try:
            proof_valid = risk_verifier.verify(
                risk_evidence,
                order_intent=order_intent,
                source_head=str(current_head or ""),
                account_identity=str(expected_account or ""),
                session_id=str(expected_session or ""),
                key_namespace=str(expected_key or ""),
                client_order_namespace=str(expected_client or ""),
                epoch=None if expected_epoch is _MISSING else expected_epoch,
            )
        except Exception:
            proof_valid = False
    if not proof_valid:
        reasons.append("risk_evidence_proof_invalid")
    evidence_approved = _as_bool(
        _read_field(risk_evidence, "approved", "risk_approved", "allowed", default=_MISSING)
    )
    if evidence_approved is not True:
        reasons.append("risk_evidence_not_approved")

    intent_id = str(_read_field(order_intent, "order_intent_id", "intent_id", default=""))
    evidence_intent_id = str(
        _read_field(
            risk_evidence,
            "intent_id",
            "intent_identity",
            "order_intent_id",
            "risk_intent_id",
            default="",
        )
    )
    if not intent_id or not evidence_intent_id or evidence_intent_id != intent_id:
        reasons.append("risk_evidence_order_intent_mismatch")

    evidence_id = str(
        _read_field(
            risk_evidence,
            "evidence_id",
            "risk_evidence_id",
            "decision_id",
            "evidence_hash",
            default="",
        )
    )
    if not evidence_id.strip():
        reasons.append("risk_evidence_id_missing")

    expected_head = str(current_head or "").strip()
    evidence_head = str(
        _read_field(
            risk_evidence,
            "source_head",
            "source_commit",
            "current_head",
            "current_main_head",
            "source_head_sha",
            default="",
        )
    ).strip()
    if not expected_head:
        reasons.append("runtime_source_head_missing")
    if not evidence_head:
        reasons.append("risk_evidence_source_head_missing")
    elif expected_head and evidence_head != expected_head:
        reasons.append("risk_evidence_source_head_mismatch")

    def _bound_text(
        expected: object,
        aliases: tuple[str, ...],
        missing_reason: str,
        mismatch_reason: str,
    ) -> None:
        expected_text = str(expected or "").strip()
        observed = str(_read_field(risk_evidence, *aliases, default="") or "").strip()
        if not expected_text:
            reasons.append(missing_reason)
        if not observed:
            reasons.append(f"risk_evidence_{missing_reason.removeprefix('execution_')}")
        elif expected_text and observed != expected_text:
            reasons.append(mismatch_reason)

    expected_account = _read_field(
        identity,
        "account_identity",
        "account_hash",
        "account_id_hash",
        "account_id",
        default="",
    )
    _bound_text(
        expected_account,
        ("account_identity", "account_hash", "account_id_hash", "account_id"),
        "execution_account_identity_missing",
        "risk_evidence_account_identity_mismatch",
    )
    expected_session = session_id or _read_field(identity, "session_id", "session", "broker_session_id", default="")
    _bound_text(
        expected_session,
        ("session_id", "session", "broker_session_id"),
        "execution_session_id_missing",
        "risk_evidence_session_id_mismatch",
    )
    expected_key = _read_field(identity, "key_namespace", "credential_namespace", "service_namespace", default="")
    _bound_text(
        expected_key,
        ("key_namespace", "credential_namespace", "service_namespace"),
        "execution_key_namespace_missing",
        "risk_evidence_key_namespace_mismatch",
    )
    expected_client = _read_field(
        identity,
        "client_order_namespace",
        "clord_namespace",
        "client_namespace",
        default="",
    )
    _bound_text(
        expected_client,
        ("client_order_namespace", "clord_namespace", "client_namespace"),
        "execution_client_order_namespace_missing",
        "risk_evidence_client_order_namespace_mismatch",
    )

    expected_epoch = epoch
    if expected_epoch is None:
        expected_epoch = _read_field(
            identity,
            "epoch",
            "connection_epoch",
            "session_epoch",
            "runtime_epoch",
            default=_MISSING,
        )
    observed_epoch = _read_field(
        risk_evidence,
        "epoch",
        "connection_epoch",
        "session_epoch",
        "runtime_epoch",
        default=_MISSING,
    )
    if expected_epoch is _MISSING or expected_epoch is None:
        reasons.append("execution_epoch_missing")
    if observed_epoch is _MISSING or observed_epoch is None:
        reasons.append("risk_evidence_epoch_missing")
    elif expected_epoch is not _MISSING and expected_epoch is not None:
        try:
            if int(observed_epoch) != int(expected_epoch):
                reasons.append("risk_evidence_epoch_mismatch")
        except (TypeError, ValueError):
            reasons.append("risk_evidence_epoch_invalid")

    actual_notional = _read_field(
        risk_evidence,
        "actual_notional",
        "computed_notional",
        "computed_risk_notional",
        "notional",
        default=_MISSING,
    )
    try:
        if actual_notional is _MISSING or float(actual_notional) <= 0.0:
            reasons.append("risk_evidence_notional_invalid")
    except (TypeError, ValueError):
        reasons.append("risk_evidence_notional_invalid")
    exposure = _read_field(risk_evidence, "exposure", "actual_exposure", "risk_exposure", default=_MISSING)
    try:
        if exposure is _MISSING or not math.isfinite(float(exposure)) or float(exposure) < 0.0:
            reasons.append("risk_evidence_exposure_invalid")
    except (TypeError, ValueError):
        reasons.append("risk_evidence_exposure_invalid")

    venue = str(
        _read_field(risk_evidence, "venue", "venue_identity", "exchange", "broker", default="") or ""
    ).strip().lower()
    if not venue:
        reasons.append("risk_evidence_venue_missing")
    observed_venue = str(_read_field(broker_truth, "venue", "exchange", "provider", default="") or "").strip().lower()
    if observed_venue and venue and venue != observed_venue:
        reasons.append("risk_evidence_venue_mismatch")

    liquidation_safe = _as_bool(
        _read_field(
            risk_evidence,
            "liquidation_safe",
            "liquidation_allowed",
            "liquidation",
            "position_safe",
            default=_MISSING,
        )
    )
    if liquidation_safe is not True:
        reasons.append("risk_evidence_liquidation_not_safe")
    if kill_switch_tripped:
        reasons.extend(
            _kill_exception_reasons(
                action=action,
                risk_evidence=risk_evidence,
                order_intent=order_intent,
                current_head=current_head,
                broker_snapshot_hash=broker_snapshot_hash,
                ledger_snapshot_hash=ledger_snapshot_hash,
                strategy_snapshot_hash=strategy_snapshot_hash,
                risk_snapshot_hash=risk_snapshot_hash,
            )
        )
    return reasons


def _kill_exception_reasons(
    *,
    action: str,
    risk_evidence: object | Mapping[str, Any] | None,
    order_intent: object | None,
    current_head: str | None,
    broker_snapshot_hash: str | None,
    ledger_snapshot_hash: str | None,
    strategy_snapshot_hash: str | None,
    risk_snapshot_hash: str | None,
) -> list[str]:
    """Validate the signed proof required for kill/pause exceptions.

    ``reduce_transport_decision`` and ``cancel_transport_decision`` are coarse
    transport checks.  Legacy ``*_position_decision``/``*_order_decision``
    remain fail-closed during kill so old US paper callers cannot treat them as
    execution authority.  This final action-level check is the only place that
    can grant a kill exception and it never trusts a caller boolean or action
    name.
    """

    increasing_or_control_actions = {
        RuntimeAction.SUBMIT_NEW_ORDER.value,
        RuntimeAction.REPLACE_ORDER.value,
        RuntimeAction.DEAD_MAN.value,
    }
    if action in increasing_or_control_actions:
        return [
            "kill_switch_blocks_new_risk"
            if action == RuntimeAction.SUBMIT_NEW_ORDER.value
            else "kill_switch_blocks_replace"
            if action == RuntimeAction.REPLACE_ORDER.value
            else "kill_switch_blocks_dead_man"
        ]
    if action not in {
        RuntimeAction.REDUCE_ONLY.value,
        RuntimeAction.CANCEL_ORDER.value,
        RuntimeAction.ATTACH_PROTECTION.value,
    }:
        return ["kill_exception_action_unknown"]

    if type(risk_evidence) is not RuntimeRiskEvidence:
        return ["kill_exception_proof_required"]

    reasons: list[str] = []
    proof_action = _normalize_proof_action(risk_evidence.action)
    if proof_action != action:
        reasons.append("kill_exception_action_mismatch")
    effect = _normalize_risk_effect(risk_evidence.risk_effect)
    if effect == RuntimeRiskEffect.UNKNOWN.value:
        reasons.append("kill_exception_effect_unknown")

    allowed_effects = {
        RuntimeAction.REDUCE_ONLY.value: {RuntimeRiskEffect.DECREASE_ABS_EXPOSURE.value},
        RuntimeAction.ATTACH_PROTECTION.value: {RuntimeRiskEffect.ADD_PROTECTION.value},
        RuntimeAction.CANCEL_ORDER.value: {
            RuntimeRiskEffect.NO_POSITION_EFFECT.value,
            RuntimeRiskEffect.DECREASE_ABS_EXPOSURE.value,
            RuntimeRiskEffect.REMOVE_PROTECTION.value,
        },
    }
    if effect not in allowed_effects[action]:
        reasons.append("kill_exception_effect_mismatch")

    positions = (risk_evidence.position_before, risk_evidence.position_after)
    if any(value is None or not math.isfinite(float(value)) for value in positions):
        reasons.append("kill_exception_position_unknown")
        return _dedupe(reasons)
    before, after = (float(value) for value in positions)
    if abs(after) > abs(before) + 1e-12:
        reasons.append("kill_exception_position_increase")
    if before != 0.0 and after != 0.0 and (before > 0.0) != (after > 0.0):
        reasons.append("kill_exception_position_cross_zero")

    max_abs_position = risk_evidence.max_abs_position
    if max_abs_position is None or not math.isfinite(float(max_abs_position)) or float(max_abs_position) < 0.0:
        reasons.append("kill_exception_limit_invalid")
    elif max(abs(before), abs(after)) > float(max_abs_position) + 1e-12:
        reasons.append("kill_exception_position_limit_exceeded")

    quantity = risk_evidence.quantity
    max_quantity = risk_evidence.max_quantity
    if quantity is None or max_quantity is None:
        reasons.append("kill_exception_quantity_limit_missing")
    else:
        try:
            if not math.isfinite(float(quantity)) or not math.isfinite(float(max_quantity)):
                raise ValueError
            if float(quantity) <= 0.0 or float(max_quantity) <= 0.0 or float(quantity) > float(max_quantity) + 1e-12:
                reasons.append("kill_exception_quantity_limit_invalid")
            intent_quantity = _read_field(order_intent, "quantity", "qty", default=_MISSING)
            if intent_quantity is _MISSING or not math.isclose(float(quantity), float(intent_quantity), rel_tol=0.0, abs_tol=1e-12):
                reasons.append("kill_exception_quantity_intent_mismatch")
        except (TypeError, ValueError):
            reasons.append("kill_exception_quantity_limit_invalid")

    if (
        risk_evidence.max_notional is None
        or not math.isfinite(float(risk_evidence.max_notional))
        or float(risk_evidence.max_notional) <= 0.0
        or not math.isfinite(float(risk_evidence.actual_notional))
        or float(risk_evidence.actual_notional) <= 0.0
        or float(risk_evidence.actual_notional) > float(risk_evidence.max_notional) + 1e-12
    ):
        reasons.append("kill_exception_notional_limit_invalid")
    if (
        risk_evidence.leverage is None
        or risk_evidence.max_leverage is None
        or not math.isfinite(float(risk_evidence.leverage))
        or not math.isfinite(float(risk_evidence.max_leverage))
        or float(risk_evidence.leverage) < 0.0
        or float(risk_evidence.max_leverage) <= 0.0
        or float(risk_evidence.leverage) > float(risk_evidence.max_leverage) + 1e-12
    ):
        reasons.append("kill_exception_leverage_limit_invalid")

    expected_hashes = {
        "broker_snapshot_hash": broker_snapshot_hash,
        "ledger_snapshot_hash": ledger_snapshot_hash,
        "strategy_snapshot_hash": strategy_snapshot_hash,
        "risk_snapshot_hash": risk_snapshot_hash,
    }
    for field_name, expected in expected_hashes.items():
        observed = str(getattr(risk_evidence, field_name, "") or "")
        if not _is_sha256(expected) or not _is_sha256(observed):
            reasons.append("kill_exception_snapshot_hash_missing")
        elif observed != str(expected):
            reasons.append("kill_exception_snapshot_hash_mismatch")

    if action == RuntimeAction.REDUCE_ONLY.value and not (abs(after) < abs(before) - 1e-12):
        reasons.append("kill_exception_reduction_not_proven")
    if action == RuntimeAction.REDUCE_ONLY.value:
        reduce_only = _read_semantic_field(order_intent, "reduce_only", "reduceOnly")
        if reduce_only is not None and _as_bool(reduce_only) is not True:
            reasons.append("kill_exception_reduce_only_required")
        side = _value_text(_read_semantic_field(order_intent, "side"))
        if side not in {"buy", "sell"}:
            reasons.append("kill_exception_side_invalid")
        else:
            try:
                reduction_quantity = float(quantity) if quantity is not None else float("nan")
                expected_after = before + reduction_quantity if side == "buy" else before - reduction_quantity
                if not math.isfinite(reduction_quantity) or reduction_quantity <= 0.0:
                    reasons.append("kill_exception_quantity_invalid")
                elif not math.isclose(after, expected_after, rel_tol=0.0, abs_tol=1e-12):
                    reasons.append("kill_exception_position_transition_mismatch")
            except (TypeError, ValueError):
                reasons.append("kill_exception_quantity_invalid")
        role = _value_text(
            _read_semantic_field(order_intent, "order_role", "orderRole", "execution_role", "executionRole", "role")
        )
        if role and role not in {"reduction", "reduce_only", "close", "close_only", "exit"}:
            reasons.append("kill_exception_order_role_mismatch")
    elif action == RuntimeAction.ATTACH_PROTECTION.value:
        if not (before == after and before != 0.0):
            reasons.append("kill_exception_protection_position_invalid")
        role = _value_text(
            _read_semantic_field(order_intent, "order_role", "orderRole", "execution_role", "executionRole", "role")
        )
        if role and role not in {"protection", "protective", "attach_protection"}:
            reasons.append("kill_exception_order_role_mismatch")
    elif action == RuntimeAction.CANCEL_ORDER.value:
        role = _value_text(
            _read_semantic_field(order_intent, "order_role", "orderRole", "execution_role", "executionRole", "role")
        )
        expected_roles = {
            RuntimeRiskEffect.REMOVE_PROTECTION.value: {"protection", "protective", "remove_protection"},
            RuntimeRiskEffect.DECREASE_ABS_EXPOSURE.value: {"reduction", "reduce_only", "close", "close_only", "exit"},
            RuntimeRiskEffect.NO_POSITION_EFFECT.value: {"opening", "entry", "new_order", "reduction", "reduce_only"},
        }
        if role and role not in expected_roles.get(effect, set()):
            reasons.append("kill_exception_order_role_mismatch")
        if effect == RuntimeRiskEffect.NO_POSITION_EFFECT.value and before != after:
            reasons.append("kill_exception_no_position_effect_invalid")
        if effect == RuntimeRiskEffect.DECREASE_ABS_EXPOSURE.value and (before != 0.0 or after != 0.0):
            reasons.append("kill_exception_reduce_cancel_not_flat")
        if effect == RuntimeRiskEffect.REMOVE_PROTECTION.value:
            if before != after or (before != 0.0 and not risk_evidence.atomic_protection_replacement):
                reasons.append("kill_exception_protection_removal_not_safe")
    return _dedupe(reasons)


def _freshness_reasons(
    broker_truth: object | Mapping[str, Any] | None,
    ledger_freshness: object | Mapping[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    broker_fresh = _as_bool(
        _read_field(broker_truth, "fresh", "broker_truth_fresh", "is_fresh", default=_MISSING)
    )
    if broker_fresh is not True:
        reasons.append("broker_truth_not_fresh")
    broker_valid = _as_bool(
        _read_field(broker_truth, "valid", "complete", "known", "is_valid", default=_MISSING)
    )
    if broker_valid is not True:
        reasons.append("broker_truth_invalid")
    broker_account_verified = _as_bool(
        _read_field(broker_truth, "account_verified", "broker_account_verified", default=_MISSING)
    )
    if broker_account_verified is not True:
        reasons.append("broker_account_not_verified")
    authoritative_account_verified = _as_bool(
        _read_field(
            broker_truth,
            "authoritative_account_verified",
            "account_verified_authoritative",
            "authoritative_account_verification",
            default=_MISSING,
        )
    )
    if authoritative_account_verified is not True:
        reasons.append("broker_account_verification_not_authoritative")
    account_source = str(
        _read_field(broker_truth, "account_verification_source", "verification_source", default="") or ""
    ).strip()
    if not account_source:
        reasons.append("broker_account_verification_source_missing")

    ledger_fresh = _as_bool(
        _read_field(ledger_freshness, "fresh", "ledger_fresh", "is_fresh", default=_MISSING)
    )
    if ledger_fresh is not True:
        reasons.append("ledger_not_fresh")
    ledger_reconciled = _as_bool(
        _read_field(ledger_freshness, "reconciled", "reconciliation_passed", "is_reconciled", default=_MISSING)
    )
    if ledger_reconciled is not True:
        reasons.append("ledger_not_reconciled")
    return reasons


def _identity_reasons(
    identity: object | Mapping[str, Any] | None,
    expected_mode: str | None,
) -> list[str]:
    if identity is None:
        return ["execution_identity_missing"]
    reasons: list[str] = []
    mode = _value_text(_read_field(identity, "mode", "trading_mode", default=""))
    if not mode:
        reasons.append("execution_mode_missing")
    if expected_mode and mode != str(expected_mode).strip().lower():
        reasons.append("execution_mode_mismatch")
    for field_name, aliases in {
        "state_directory": ("state_directory", "state_dir"),
        "account_identity": ("account_identity", "account_hash", "account_id_hash"),
        "key_namespace": ("key_namespace", "credential_namespace", "service_namespace"),
        "client_order_namespace": ("client_order_namespace", "clord_namespace", "client_namespace"),
        "session_id": ("session_id", "session", "broker_session_id"),
    }.items():
        value = _read_field(identity, *aliases, default="")
        if not str(value).strip():
            reasons.append(f"execution_{field_name}_missing")
    epoch = _read_field(identity, "epoch", "connection_epoch", "session_epoch", default=_MISSING)
    if epoch is _MISSING or epoch is None:
        reasons.append("execution_epoch_missing")

    state_dir = str(_read_field(identity, "state_directory", "state_dir", default="")).lower()
    key_namespace = str(
        _read_field(identity, "key_namespace", "credential_namespace", "service_namespace", default="")
    ).lower()
    client_namespace = str(
        _read_field(identity, "client_order_namespace", "clord_namespace", "client_namespace", default="")
    ).lower()
    if mode in {"demo", "live"}:
        opposite = "live" if mode == "demo" else "demo"
        if opposite in state_dir:
            reasons.append("execution_state_directory_mode_crossed")
        if opposite in key_namespace:
            reasons.append("execution_key_namespace_mode_crossed")
        if opposite in client_namespace:
            reasons.append("execution_client_order_namespace_mode_crossed")
        expected_key_prefix = f"quant-system.okx-{mode}."
        if key_namespace and not key_namespace.startswith(expected_key_prefix):
            reasons.append("execution_key_namespace_mode_mismatch")
        if client_namespace and opposite in client_namespace:
            reasons.append("execution_client_order_namespace_mode_mismatch")
    transport_enabled = _as_bool(
        _read_field(identity, "transport_enabled", "transport_allowed", default=_MISSING)
    )
    if transport_enabled is not True:
        reasons.append("execution_transport_disabled")
    if _as_bool(_read_field(identity, "auto_start", "automatic_start", default=False)):
        reasons.append("auto_start_forbidden")
    if _as_bool(_read_field(identity, "auto_scale", "automatic_scale", default=False)):
        reasons.append("auto_scale_forbidden")
    if mode == "live" and _as_bool(
        _read_field(identity, "live_execution_allowed", "live_allowed", default=False)
    ) is not True:
        reasons.append("live_execution_not_authorized")
    return reasons


def _capability_reasons(action: str, capability: object | Mapping[str, Any] | None) -> list[str]:
    if capability is None:
        return [f"endpoint_capability_missing:{action}"]
    aliases = {
        RuntimeAction.SUBMIT_NEW_ORDER.value: (
            "submit_new_order",
            "new_order",
            "order",
            "order_endpoint",
            "order_endpoint_allowed",
        ),
        RuntimeAction.CANCEL_ORDER.value: ("cancel_order", "cancel", "cancel_endpoint", "cancel_endpoint_allowed"),
        RuntimeAction.REPLACE_ORDER.value: ("replace_order", "replace", "replace_endpoint", "replace_endpoint_allowed"),
        RuntimeAction.REDUCE_ONLY.value: (
            "reduce_only",
            "reduce_position",
            "reduce_only_endpoint",
            "reduce_only_allowed",
        ),
        RuntimeAction.ATTACH_PROTECTION.value: (
            "attach_protection",
            "protection",
            "protection_endpoint",
            "protection_endpoint_allowed",
        ),
        RuntimeAction.DEAD_MAN.value: ("dead_man", "deadman", "dead_man_switch", "dead_man_endpoint"),
    }
    allowed = _read_field(capability, *aliases.get(action, (action,)), default=_MISSING)
    if allowed is _MISSING:
        allowed = _read_field(capability, "allowed", "enabled", default=_MISSING)
    reasons: list[str] = []
    if _as_bool(allowed) is not True:
        reasons.append(f"endpoint_capability_not_allowed:{action}")
    transport = _as_bool(_read_field(capability, "transport_enabled", "transport_allowed", default=_MISSING))
    if transport is not True:
        reasons.append(f"endpoint_transport_disabled:{action}")
    private_allowed = _as_bool(
        _read_field(capability, "private_endpoint_allowed", "private_allowed", default=_MISSING)
    )
    if private_allowed is not True:
        reasons.append(f"endpoint_private_capability_missing:{action}")
    order_allowed = _as_bool(
        _read_field(capability, "order_endpoint_allowed", "order_allowed", default=_MISSING)
    )
    if order_allowed is not True:
        reasons.append(f"endpoint_order_capability_missing:{action}")
    return reasons


def _runtime_action_reasons(snapshot: RuntimeSnapshot, action: str) -> list[str]:
    if action == RuntimeAction.SUBMIT_NEW_ORDER.value:
        return list(PermissionEvaluator(snapshot).new_order_decision().reasons)
    if action == RuntimeAction.REDUCE_ONLY.value:
        evaluator = PermissionEvaluator(snapshot)
        decision = evaluator.reduce_transport_decision() if snapshot.kill_switch_tripped else evaluator.reduce_position_decision()
        return list(decision.reasons)
    if action == RuntimeAction.CANCEL_ORDER.value:
        evaluator = PermissionEvaluator(snapshot)
        decision = evaluator.cancel_transport_decision() if snapshot.kill_switch_tripped else evaluator.cancel_order_decision()
        return list(decision.reasons)
    if action == RuntimeAction.REPLACE_ORDER.value:
        decision = PermissionEvaluator(snapshot).cancel_order_decision()
        reasons = list(decision.reasons)
        if snapshot.state != RuntimeState.READY:
            reasons.append("replace_requires_runtime_ready")
        if snapshot.trading_mode != TradingMode.NORMAL:
            reasons.append("replace_requires_normal_trading_mode")
        if not snapshot.risk_state_valid:
            reasons.append("risk_state_invalid")
        if snapshot.kill_switch_tripped:
            reasons.append("kill_switch_blocks_replace")
        return reasons
    if action == RuntimeAction.ATTACH_PROTECTION.value:
        evaluator = PermissionEvaluator(snapshot)
        decision = evaluator.reduce_transport_decision() if snapshot.kill_switch_tripped else evaluator.reduce_position_decision()
        return list(decision.reasons)
    if action == RuntimeAction.DEAD_MAN.value:
        reasons: list[str] = []
        if not snapshot.connected:
            reasons.append("transport_not_connected")
        if snapshot.state in {RuntimeState.OFFLINE, RuntimeState.RECONNECTING, RuntimeState.HALTED}:
            reasons.append("runtime_state_does_not_support_dead_man")
        if snapshot.trading_mode in {TradingMode.FROZEN, TradingMode.NO_TRANSPORT}:
            reasons.append("trading_mode_does_not_support_dead_man")
        if not snapshot.account_verified:
            reasons.append("account_not_verified")
        if snapshot.kill_switch_tripped:
            reasons.append("kill_switch_tripped")
        return reasons
    return [f"unknown_runtime_action:{action}"]


def _lifecycle_reasons(
    action: str,
    lifecycle: object | Mapping[str, Any] | None,
    order_intent: object | None,
) -> list[str]:
    if action == RuntimeAction.SUBMIT_NEW_ORDER.value and lifecycle is None:
        # The submit boundary creates the durable PREPARED record immediately
        # after this pure permission check and before invoking a transport.
        return []
    if lifecycle is None:
        return ["durable_order_lifecycle_missing"]
    intent_id = str(_read_field(order_intent, "client_order_id", "cl_ord_id", "clOrdId", default=""))
    lifecycle_id = str(_read_field(lifecycle, "client_order_id", "cl_ord_id", "clOrdId", default=""))
    reasons: list[str] = []
    if not lifecycle_id:
        reasons.append("durable_order_lifecycle_client_order_id_missing")
    elif lifecycle_id != intent_id:
        reasons.append("durable_order_lifecycle_client_order_id_mismatch")
    status = str(_read_field(lifecycle, "status", "state", default="")).lower()
    if status in {"ambiguous", "unknown", "sent", "submitted", "timeout", "timed_out"}:
        reasons.append("ambiguous_order_query_required_before_retry")
    if status in {
        "accepted",
        "partially_filled",
        "filled",
        "cancel_requested",
        "cancelled",
        "canceled",
        "rejected",
        "resolved",
    }:
        reconciled = _as_bool(
            _read_field(lifecycle, "reconciliation_complete", "reconciled", default=_MISSING)
        )
        if reconciled is not True:
            reasons.append("clord_order_fill_position_reconciliation_required")
    return reasons


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


# Naming aliases for integration code that prefers the longer role name.
RuntimePermissionEvaluator = PermissionEvaluator


def can_submit_new_order(snapshot: RuntimeSnapshot | Mapping[str, Any]) -> bool:
    return PermissionEvaluator(snapshot).can_submit_new_order()


def can_reduce_position(snapshot: RuntimeSnapshot | Mapping[str, Any]) -> bool:
    return PermissionEvaluator(snapshot).can_reduce_position()


def can_cancel_order(snapshot: RuntimeSnapshot | Mapping[str, Any]) -> bool:
    return PermissionEvaluator(snapshot).can_cancel_order()


def can_query_broker(snapshot: RuntimeSnapshot | Mapping[str, Any]) -> bool:
    return PermissionEvaluator(snapshot).can_query_broker()


__all__ = [
    "PermissionDecision",
    "PermissionEvaluator",
    "RuntimeAction",
    "RuntimeRiskEffect",
    "RuntimePermissionContext",
    "RuntimeRiskEvidence",
    "RuntimeRiskEvidenceProof",
    "RuntimeRiskEvidenceError",
    "RuntimeRiskEvidenceAuthority",
    "RuntimeRiskEvidenceVerifier",
    "RuntimeRiskEvidenceProducer",
    "RuntimeAuthoritativeRiskResult",
    "RuntimePermissionEvaluator",
    "can_cancel_order",
    "can_query_broker",
    "can_reduce_position",
    "can_submit_new_order",
]
