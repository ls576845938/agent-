"""Pure BTC runtime risk guardian and durable sticky latch.

The guardian is deliberately below the execution boundary.  It consumes an
explicit, already-captured account observation and returns a deterministic
health decision.  It never reads a clock, environment variable, file,
network, broker, OMS, or order intent.  The optional supervisor is the only
writer of a durable latch; a latch can block recovery but can never grant
execution permission.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from quant_crypto.oms.account_risk_facts import (
    AccountRiskFactError,
    resolve_drawdown_metric,
)


BTC_RUNTIME_RISK_GUARDIAN_VERSION = "btc_shared_platform_v3_t4_guardian_v1"
BTC_RUNTIME_LATCH_SCHEMA_VERSION = "btc_shared_platform_v3_t4_latch_v1"


class GuardianError(RuntimeError):
    """Base error for fail-closed guardian/supervisor failures."""


class GuardianPersistenceError(GuardianError):
    """The durable latch could not be read or written safely."""


class GuardianConcurrentWriterError(GuardianPersistenceError):
    """A second writer holds the durable latch fencing lock."""


class GuardianStaleWriterError(GuardianPersistenceError):
    """The owner, fencing token, or expected generation is stale."""


class GuardianRecoveryRejected(GuardianError):
    """Recovery requirements were not all satisfied."""


class GuardianStatus(str, Enum):
    PASS = "pass"
    TRIPPED = "tripped"
    UNKNOWN = "unknown"


def _dedupe(values: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return candidate if math.isfinite(candidate) else None


def _bool_or_none(value: object) -> bool | None:
    if value is None:
        return None
    return value if type(value) is bool else None


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


def _jsonable(value: object) -> object:
    """Convert frozen observations to deterministic JSON-safe values."""

    if isinstance(value, datetime):
        resolved = _utc(value)
        return resolved.isoformat().replace("+00:00", "Z") if resolved else None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "nonfinite"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical(value: object) -> bytes:
    return json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=lambda item: repr(item)))
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _read(value: object | Mapping[str, Any] | None, *names: str, default: object = None) -> object:
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


def _metric(value: object, *names: str) -> object:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    return value


def _explicit_numeric_metric(value: object, *names: str) -> tuple[float | None, str | None]:
    """Read a scalar or an explicitly named mapping metric, never a sum guess."""

    scalar = _finite(value)
    if scalar is not None and not isinstance(value, Mapping):
        return scalar, "scalar"
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                candidate = _finite(value[name])
                return candidate, name
    return None, None


def _explicit_pnl_metric(value: object) -> tuple[float | None, str | None]:
    """Use the contract's fixed PnL priority; unknown fields never become loss."""

    return _explicit_numeric_metric(value, "daily", "daily_pnl", "realized", "total")


def _numeric_total(value: object) -> float | None:
    number = _finite(value)
    if number is not None:
        return number
    if isinstance(value, Mapping):
        candidates = []
        for key in ("gross", "gross_exposure", "absolute", "abs", "total", "notional", "value", "equity", "available", "balance", "count"):
            if key in value:
                candidate = _finite(value[key])
                if candidate is not None:
                    candidates.append(candidate)
        if candidates:
            return candidates[0]
        numeric = [
            _finite(item)
            for key, item in value.items()
            if str(key).lower() not in {"consistent", "match", "reconciled", "fresh", "freshness"}
        ]
        if numeric and all(item is not None for item in numeric):
            return float(sum(abs(item) for item in numeric if item is not None))
    if isinstance(value, (tuple, list)):
        numeric = [_finite(item) for item in value]
        if numeric and all(item is not None for item in numeric):
            return float(sum(abs(item) for item in numeric if item is not None))
        mapped = []
        for item in value:
            candidate = _metric(item, "gross", "gross_exposure", "quantity", "qty", "contracts", "pos", "total", "notional", "value")
            number = _finite(candidate)
            if number is None:
                return None
            mapped.append(number)
        if mapped:
            return float(sum(abs(item) for item in mapped))
    return None


def _count_open_orders(value: object) -> int | None:
    if isinstance(value, Mapping):
        for key in ("count", "open_order_count", "total"):
            if key in value:
                candidate = _finite(value[key])
                if candidate is None or candidate < 0 or not candidate.is_integer():
                    return None
                return int(candidate)
    if isinstance(value, (tuple, list)):
        return len(value)
    candidate = _finite(value)
    if candidate is not None and candidate >= 0 and candidate.is_integer():
        return int(candidate)
    return None


def _order_rows(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, (tuple, list)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def classify_order_risk(
    open_orders: object,
    positions: object = None,
    *,
    instrument_id: str = "BTC-USDT-SWAP",
    owner_identity: str | None = None,
) -> tuple[int, int, tuple[str, ...]]:
    """Split orders into risk-increasing and proven protective classes.

    A protective classification is deliberately strict.  The order must be
    an owned live OCO/conditional OCO, carry explicit reduce-only/close
    semantics, match the instrument, position side and non-flat quantity, and
    expose a stable owner plus algorithm/client identity.  Anything that
    cannot be proven protective is risk-increasing and contributes a stable
    blocker; this keeps ``max_open_orders`` from being bypassed by a Boolean.
    """

    position_rows = _order_rows(positions)
    malformed_positions = (
        isinstance(positions, (tuple, list))
        and any(not isinstance(row, Mapping) for row in positions)
    )
    nonflat = []
    for row in position_rows:
        quantity = _finite(row.get("contracts", row.get("pos", row.get("quantity"))))
        if quantity is not None and quantity != 0.0:
            nonflat.append((row, abs(quantity)))
    risk_count = 0
    protective_count = 0
    blockers: list[str] = []
    if malformed_positions:
        blockers.append("protective_position_shape_invalid")
    raw_orders = list(open_orders) if isinstance(open_orders, (tuple, list)) else []
    malformed_orders = sum(1 for row in raw_orders if not isinstance(row, Mapping))
    if malformed_orders:
        risk_count += malformed_orders
        blockers.append("protective_order_shape_invalid")
    for order in _order_rows(open_orders):
        instrument = str(order.get("instrument_id") or order.get("instId") or order.get("symbol") or "").strip()
        side = str(order.get("position_side") or order.get("posSide") or "").strip().lower()
        state = str(order.get("state") or order.get("status") or "").strip().lower()
        order_type = str(order.get("order_type") or order.get("ordType") or order.get("type") or "").strip().lower()
        quantity = _finite(order.get("contracts", order.get("size", order.get("sz", order.get("quantity")))))
        owner = str(
            order.get("owner_identity")
            or order.get("owner_id")
            or order.get("runtime_identity")
            or order.get("owned_by")
            or ""
        ).strip()
        owned_flag = order.get("owned") is True or order.get("owned_by_runtime") is True
        client_identity = str(
            order.get("algo_client_order_id")
            or order.get("clOrdId")
            or order.get("client_order_id")
            or order.get("algo_id")
            or ""
        ).strip()
        parent_identity = str(
            order.get("parent_client_order_id")
            or order.get("attachAlgoClOrdId")
            or order.get("parentClOrdId")
            or ""
        ).strip()
        reduce_only = order.get("reduce_only") is True or order.get("reduceOnly") is True
        close_position = order.get("close_position") is True or order.get("closePosition") is True
        owner_matches = bool(owner and owner_identity and owner == str(owner_identity).strip())
        owner_proof = owned_flag or owner_matches
        candidate = bool(
            nonflat
            and owner_proof
            and client_identity
            and instrument == instrument_id
            and side in {"long", "short"}
            and state in {"live", "effective", "open", "pending"}
            and order_type in {"oco", "conditional_oco"}
            and (reduce_only or close_position)
            and parent_identity
            and client_identity == f"{parent_identity}A"
            and quantity is not None
            and quantity > 0
            and any(
                side == str(position.get("position_side") or position.get("posSide") or "").strip().lower()
                and abs(quantity - position_quantity) <= 1e-12
                for position, position_quantity in nonflat
            )
        )
        if candidate:
            protective_count += 1
            continue
        risk_count += 1
        if not owner_proof:
            blockers.append("protective_order_owner_missing")
        if not instrument or instrument != instrument_id:
            blockers.append("protective_order_instrument_mismatch")
        if side not in {"long", "short"}:
            blockers.append("protective_order_position_side_unknown")
        if not reduce_only and not close_position:
            blockers.append("protective_order_reduce_only_unknown")
        if quantity is None or quantity <= 0:
            blockers.append("protective_order_quantity_unknown")
        elif nonflat and not any(
            side == str(position.get("position_side") or position.get("posSide") or "").strip().lower()
            and abs(quantity - position_quantity) <= 1e-12
            for position, position_quantity in nonflat
        ):
            blockers.append("protective_order_quantity_or_side_mismatch")
        if order_type not in {"oco", "conditional_oco"}:
            blockers.append("protective_order_type_unknown")
        if not client_identity:
            blockers.append("protective_order_identity_missing")
        if not parent_identity:
            blockers.append("protective_order_parent_missing")
        elif client_identity != f"{parent_identity}A":
            blockers.append("protective_order_parent_mismatch")
    return risk_count, protective_count, _dedupe(blockers)


def _consistency_or(value: bool | None, container: object, *names: str) -> bool | None:
    if value is not None:
        return value
    if isinstance(container, Mapping):
        for name in names:
            candidate = _bool_or_none(container.get(name))
            if candidate is not None:
                return candidate
    return None


@dataclass(frozen=True)
class GuardianConfig:
    """Explicit, immutable policy inputs for the pure guardian."""

    config_version: str = BTC_RUNTIME_RISK_GUARDIAN_VERSION
    freshness_ttl_seconds: float = 30.0
    heartbeat_ttl_seconds: float = 30.0
    max_abs_exposure: float | None = None
    max_exposure: float | None = None
    max_daily_loss: float | None = None
    max_drawdown: float | None = None
    max_drawdown_unit: str = "unknown"
    max_open_orders: int | None = None
    require_positions: bool = True
    require_cash: bool = True
    require_pnl: bool = True
    require_exposure: bool = True
    require_open_orders: bool = True
    require_protection: bool = True
    require_funding_reconciliation: bool = True

    def __post_init__(self) -> None:
        if not str(self.config_version).strip():
            raise ValueError("guardian_config_version_required")
        for name in ("freshness_ttl_seconds", "heartbeat_ttl_seconds"):
            value = _finite(getattr(self, name))
            if value is None or value <= 0.0:
                raise ValueError(f"{name}_invalid")
            object.__setattr__(self, name, value)
        for name in ("max_abs_exposure", "max_exposure", "max_daily_loss", "max_drawdown"):
            value = getattr(self, name)
            if value is not None:
                finite = _finite(value)
                if finite is None or finite < 0.0:
                    raise ValueError(f"{name}_invalid")
                object.__setattr__(self, name, finite)
        drawdown_unit = str(self.max_drawdown_unit or "unknown").strip().lower()
        if drawdown_unit not in {"unknown", "usdt", "ratio"}:
            raise ValueError("max_drawdown_unit_invalid")
        object.__setattr__(self, "max_drawdown_unit", drawdown_unit)
        if self.max_abs_exposure is not None and self.max_exposure is not None:
            if self.max_abs_exposure != self.max_exposure:
                raise ValueError("max_exposure_alias_mismatch")
        if self.max_abs_exposure is None and self.max_exposure is not None:
            object.__setattr__(self, "max_abs_exposure", self.max_exposure)
        if self.max_open_orders is not None:
            if type(self.max_open_orders) is not int or self.max_open_orders < 0:
                raise ValueError("max_open_orders_invalid")
        for name in (
            "require_positions",
            "require_cash",
            "require_pnl",
            "require_exposure",
            "require_open_orders",
            "require_protection",
            "require_funding_reconciliation",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name}_must_be_bool")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GuardianConfig":
        aliases = {
            "version": "config_version",
            "schema_version": "config_version",
            "ttl_seconds": "freshness_ttl_seconds",
            "max_position_exposure": "max_abs_exposure",
            "max_gross_exposure": "max_abs_exposure",
            "max_orders": "max_open_orders",
        }
        data: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = aliases.get(str(raw_key), str(raw_key))
            if key in data and data[key] != item:
                raise ValueError(f"guardian_config_duplicate_key:{key}")
            data[key] = item
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"guardian_config_unknown_key:{unknown[0]}")
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        values = {name: _jsonable(getattr(self, name)) for name in self.__dataclass_fields__}
        values["schema_version"] = self.config_version
        return values


@dataclass(frozen=True)
class GuardianObservation:
    """Explicit broker-truth/account facts consumed by :class:`RuntimeRiskGuardian`.

    All timestamps are supplied by the caller.  No default timestamp is
    generated here because a missing clock/freshness fact must trip the guard.
    """

    source_head: str = ""
    account_identity: str = ""
    account_snapshot_sha256: str = ""
    session_id: str = ""
    key_namespace: str = ""
    client_order_namespace: str = ""
    owner_identity: str = ""
    epoch: int | None = None
    observed_at_utc: datetime | None = None
    reference_time_utc: datetime | None = None
    heartbeat_at_utc: datetime | None = None
    heartbeat_healthy: bool | None = None
    heartbeat: object = None
    broker_truth: object = None
    broker_truth_fresh: bool | None = None
    facts_fresh: bool | None = None
    reconciliation: object = None
    reconciliation_passed: bool | None = None
    ledger_reconciled: bool | None = None
    snapshot_match: bool | None = None
    funding_reconciled: bool | None = None
    positions: object = None
    cash: object = None
    pnl: object = None
    exposure: object = None
    open_orders: object = None
    protection_facts: object = None
    account_facts: object = None
    positions_consistent: bool | None = None
    cash_consistent: bool | None = None
    pnl_consistent: bool | None = None
    exposure_consistent: bool | None = None
    open_orders_consistent: bool | None = None
    protection_consistent: bool | None = None
    account_equity: float | None = None
    total_exposure: float | None = None
    daily_pnl: float | None = None
    drawdown: float | None = None
    open_order_count: int | None = None
    risk_increasing_open_order_count: int | None = None
    protective_reduce_only_order_count: int | None = None
    order_risk_blockers: tuple[str, ...] = ()
    freshness: Mapping[str, Any] | None = None
    evidence_identity: str = ""

    def __post_init__(self) -> None:
        for name in (
            "source_head",
            "account_identity",
            "account_snapshot_sha256",
            "session_id",
            "key_namespace",
            "client_order_namespace",
            "owner_identity",
            "evidence_identity",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        if self.epoch is not None:
            if type(self.epoch) is not int or self.epoch < 0:
                raise ValueError("epoch_invalid")
        for name in (
            "observed_at_utc",
            "reference_time_utc",
            "heartbeat_at_utc",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, datetime):
                raise TypeError(f"{name}_must_be_datetime")
        for name in (
            "positions",
            "cash",
            "pnl",
            "exposure",
            "open_orders",
            "protection_facts",
            "heartbeat",
            "broker_truth",
            "reconciliation",
            "account_facts",
            "freshness",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        for name in (
            "heartbeat_healthy",
            "broker_truth_fresh",
            "facts_fresh",
            "reconciliation_passed",
            "ledger_reconciled",
            "snapshot_match",
            "funding_reconciled",
            "positions_consistent",
            "cash_consistent",
            "pnl_consistent",
            "exposure_consistent",
            "open_orders_consistent",
            "protection_consistent",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise TypeError(f"{name}_must_be_bool")
        for name in ("account_equity", "total_exposure", "daily_pnl", "drawdown"):
            value = getattr(self, name)
            if value is not None:
                finite = _finite(value)
                if finite is not None:
                    object.__setattr__(self, name, finite)
        for name in (
            "open_order_count",
            "risk_increasing_open_order_count",
            "protective_reduce_only_order_count",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name}_invalid")
        object.__setattr__(self, "order_risk_blockers", _dedupe(self.order_risk_blockers))
        derived_risk, derived_protective, derived_blockers = classify_order_risk(
            self.open_orders,
            self.positions,
            owner_identity=self.owner_identity,
        )
        if isinstance(self.open_orders, (tuple, list)):
            if self.risk_increasing_open_order_count is not None and self.risk_increasing_open_order_count != derived_risk:
                raise ValueError("risk_increasing_open_order_count_mismatch")
            if self.protective_reduce_only_order_count is not None and self.protective_reduce_only_order_count != derived_protective:
                raise ValueError("protective_reduce_only_order_count_mismatch")
            object.__setattr__(self, "risk_increasing_open_order_count", derived_risk)
            object.__setattr__(self, "protective_reduce_only_order_count", derived_protective)
            object.__setattr__(self, "order_risk_blockers", _dedupe((*self.order_risk_blockers, *derived_blockers)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GuardianObservation":
        aliases = {
            "current_head": "source_head",
            "code_commit": "source_head",
            "account_hash": "account_identity",
            "account_id_hash": "account_identity",
            "session": "session_id",
            "credential_namespace": "key_namespace",
            "client_namespace": "client_order_namespace",
            "runtime_owner_identity": "owner_identity",
            "connection_epoch": "epoch",
            "observed_at": "observed_at_utc",
            "reference_time": "reference_time_utc",
            "heartbeat_at": "heartbeat_at_utc",
            "heartbeat_facts": "heartbeat",
            "broker_snapshot": "broker_truth",
            "reconciliation_facts": "reconciliation",
            "broker_fresh": "broker_truth_fresh",
            "reconciled": "reconciliation_passed",
            "ledger_reconciliation": "ledger_reconciled",
            "snapshot_reconciled": "snapshot_match",
            "funding_match": "funding_reconciled",
            "position_facts": "positions",
            "cash_facts": "cash",
            "pnl_facts": "pnl",
            "exposure_facts": "exposure",
            "order_facts": "open_orders",
            "protection": "protection_facts",
            "account_snapshot": "account_facts",
            "evidence_id": "evidence_identity",
            "risk_open_order_count": "risk_increasing_open_order_count",
            "protective_order_count": "protective_reduce_only_order_count",
        }
        data = {aliases.get(str(key), str(key)): item for key, item in value.items()}
        for name in ("observed_at_utc", "reference_time_utc", "heartbeat_at_utc"):
            if name in data:
                data[name] = _parse_datetime(data[name])
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: data[key] for key in allowed if key in data})

    def to_dict(self) -> dict[str, Any]:
        values = {name: _jsonable(getattr(self, name)) for name in self.__dataclass_fields__}
        values["schema_version"] = BTC_RUNTIME_RISK_GUARDIAN_VERSION
        return values


@dataclass(frozen=True)
class GuardianDecision:
    """Deterministic health decision; it is never an execution capability."""

    status: GuardianStatus | str
    reason_codes: tuple[str, ...] = ()
    evidence_identity: str = ""
    evidence_digest: str = ""
    observation_digest: str = ""
    source_head: str = ""
    account_identity: str = ""
    session_id: str = ""
    key_namespace: str = ""
    client_order_namespace: str = ""
    epoch: int | None = None
    generation: int = 0
    reference_time_utc: datetime | None = None
    config_version: str = BTC_RUNTIME_RISK_GUARDIAN_VERSION

    def __post_init__(self) -> None:
        try:
            resolved = self.status if isinstance(self.status, GuardianStatus) else GuardianStatus(str(self.status))
        except ValueError:
            resolved = GuardianStatus.UNKNOWN
        object.__setattr__(self, "status", resolved)
        object.__setattr__(self, "reason_codes", _dedupe(self.reason_codes))
        for name in ("evidence_identity", "evidence_digest", "observation_digest", "source_head", "account_identity", "session_id", "key_namespace", "client_order_namespace", "config_version"):
            object.__setattr__(self, name, str(getattr(self, name) or ""))
        if self.generation < 0 or type(self.generation) is not int:
            raise ValueError("generation_invalid")

    @property
    def passed(self) -> bool:
        return self.status is GuardianStatus.PASS and not self.reason_codes

    @property
    def healthy(self) -> bool:
        """Health result only; this is never an execution authorization."""

        return self.passed

    @property
    def health_passed(self) -> bool:
        return self.passed

    @property
    def tripped(self) -> bool:
        return not self.passed

    @property
    def allowed(self) -> bool:
        return False

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reason_codes

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.reason_codes

    @property
    def reason(self) -> str | None:
        return self.reason_codes[0] if self.reason_codes else None

    def with_blockers(self, *blockers: str) -> "GuardianDecision":
        return replace(self, status=GuardianStatus.TRIPPED, reason_codes=_dedupe((*self.reason_codes, *blockers)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.config_version,
            "status": self.status.value,
            "passed": self.passed,
            "healthy": self.healthy,
            "health_passed": self.health_passed,
            "tripped": self.tripped,
            "allowed": False,
            "reason_codes": list(self.reason_codes),
            "blocker_codes": list(self.reason_codes),
            "evidence_identity": self.evidence_identity,
            "evidence_digest": self.evidence_digest,
            "observation_digest": self.observation_digest,
            "source_head": self.source_head,
            "account_identity": self.account_identity,
            "session_id": self.session_id,
            "key_namespace": self.key_namespace,
            "client_order_namespace": self.client_order_namespace,
            "epoch": self.epoch,
            "generation": self.generation,
            "reference_time_utc": _jsonable(self.reference_time_utc),
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


class RuntimeRiskGuardian:
    """Pure, deterministic account-level guardian."""

    def __init__(self, config: GuardianConfig | Mapping[str, Any] | None = None) -> None:
        if config is None:
            resolved = GuardianConfig()
        elif isinstance(config, GuardianConfig):
            resolved = config
        elif isinstance(config, Mapping):
            resolved = GuardianConfig.from_mapping(config)
        else:
            raise TypeError("guardian_config_required")
        self.config = resolved

    def evaluate(
        self,
        observation: GuardianObservation | Mapping[str, Any],
        *,
        generation: int = 0,
    ) -> GuardianDecision:
        obs = observation if isinstance(observation, GuardianObservation) else GuardianObservation.from_mapping(observation)
        reasons: list[str] = []
        for limit_name, limit_value in (
            ("max_abs_exposure", self.config.max_abs_exposure),
            ("max_daily_loss", self.config.max_daily_loss),
            ("max_drawdown", self.config.max_drawdown),
            ("max_open_orders", self.config.max_open_orders),
        ):
            if limit_value is None:
                reasons.append(f"{limit_name}_limit_missing")
        account_facts = obs.account_facts
        position_source = obs.positions if obs.positions is not None else _read(account_facts, "positions", "position_facts", default=None)
        cash_source = obs.cash if obs.cash is not None else _read(account_facts, "cash", "cash_facts", default=None)
        pnl_source = obs.pnl if obs.pnl is not None else _read(account_facts, "pnl", "pnl_facts", default=None)
        exposure_source = obs.exposure if obs.exposure is not None else _read(account_facts, "exposure", "exposure_facts", default=None)
        orders_source = obs.open_orders if obs.open_orders is not None else _read(account_facts, "open_orders", "orders", default=None)
        protection_source = obs.protection_facts if obs.protection_facts is not None else _read(account_facts, "protection", "protection_facts", default=None)
        broker_truth_fresh = obs.broker_truth_fresh
        if broker_truth_fresh is None:
            broker_truth_fresh = _bool_or_none(obs.broker_truth)
        if broker_truth_fresh is None:
            broker_truth_fresh = _bool_or_none(_read(obs.broker_truth, "fresh", "freshness", "broker_truth_fresh", default=None))
        facts_fresh = obs.facts_fresh
        if facts_fresh is None:
            facts_fresh = _bool_or_none(account_facts)
        if facts_fresh is None:
            facts_fresh = _bool_or_none(_read(account_facts, "fresh", "freshness", "facts_fresh", default=None))
        reconciliation_passed = obs.reconciliation_passed
        if reconciliation_passed is None:
            reconciliation_passed = _bool_or_none(obs.reconciliation)
        if reconciliation_passed is None:
            reconciliation_passed = _bool_or_none(_read(obs.reconciliation, "passed", "ok", "reconciled", default=None))
        heartbeat_at = obs.heartbeat_at_utc
        if heartbeat_at is None:
            heartbeat_at = obs.heartbeat if isinstance(obs.heartbeat, datetime) else _parse_datetime(_read(obs.heartbeat, "at_utc", "heartbeat_at_utc", "observed_at_utc", default=None))
        heartbeat_health = obs.heartbeat_healthy
        if heartbeat_health is None:
            heartbeat_health = _bool_or_none(_read(obs.heartbeat, "healthy", "alive", "heartbeat_healthy", default=None))

        if not obs.source_head:
            reasons.append("source_head_missing")
        if not obs.account_identity:
            reasons.append("account_identity_missing")
        if not obs.session_id:
            reasons.append("session_id_missing")
        if not obs.key_namespace:
            reasons.append("key_namespace_missing")
        if not obs.client_order_namespace:
            reasons.append("client_order_namespace_missing")
        if obs.epoch is None:
            reasons.append("epoch_missing")

        observed = _utc(obs.observed_at_utc)
        reference = _utc(obs.reference_time_utc)
        if obs.observed_at_utc is None:
            reasons.append("observation_timestamp_missing")
        elif observed is None:
            reasons.append("observation_timestamp_invalid")
        if obs.reference_time_utc is None:
            reasons.append("reference_time_missing")
        elif reference is None:
            reasons.append("reference_time_invalid")
        if observed is not None and reference is not None:
            age = (reference - observed).total_seconds()
            if age < 0.0:
                reasons.append("observation_from_future")
            elif age > self.config.freshness_ttl_seconds:
                reasons.append("observation_stale")

        heartbeat = _utc(heartbeat_at)
        heartbeat_healthy = _bool_or_none(heartbeat_health)
        if heartbeat is None:
            reasons.append("heartbeat_missing")
        elif reference is not None:
            heartbeat_age = (reference - heartbeat).total_seconds()
            if heartbeat_age < 0.0:
                reasons.append("heartbeat_from_future")
            elif heartbeat_age > self.config.heartbeat_ttl_seconds:
                reasons.append("heartbeat_stale")
        if heartbeat_healthy is None:
            reasons.append("heartbeat_health_unknown")
        elif not heartbeat_healthy:
            reasons.append("heartbeat_unhealthy")

        self._require_bool(reasons, broker_truth_fresh, "broker_truth_fresh")
        if broker_truth_fresh is False:
            reasons.append("broker_truth_stale")
        self._require_bool(reasons, facts_fresh, "facts_fresh")
        if facts_fresh is False:
            reasons.append("account_facts_stale")
        for name, value, unknown_code, failed_code in (
            ("reconciliation_passed", reconciliation_passed, "reconciliation_unknown", "reconciliation_failed"),
            ("ledger_reconciled", obs.ledger_reconciled, "ledger_reconciliation_unknown", "ledger_reconciliation_failed"),
            ("snapshot_match", obs.snapshot_match, "snapshot_match_unknown", "snapshot_mismatch"),
        ):
            self._require_bool(reasons, value, unknown_code)
            if value is False:
                reasons.append(failed_code)
        if self.config.require_funding_reconciliation:
            self._require_bool(reasons, obs.funding_reconciled, "funding_reconciliation_unknown")
            if obs.funding_reconciled is False:
                reasons.append("funding_reconciliation_failed")
        for key, value in (obs.freshness or {}).items():
            checked = _bool_or_none(value)
            if checked is not True:
                reasons.append(f"freshness_{str(key).strip().lower() or 'fact'}_invalid")

        consistency = (
            ("positions_consistent", _consistency_or(obs.positions_consistent, position_source, "consistent", "match", "reconciled")),
            ("cash_consistent", _consistency_or(obs.cash_consistent, cash_source, "consistent", "match", "reconciled")),
            ("pnl_consistent", _consistency_or(obs.pnl_consistent, pnl_source, "consistent", "match", "reconciled")),
            ("exposure_consistent", _consistency_or(obs.exposure_consistent, exposure_source, "consistent", "match", "reconciled")),
            ("open_orders_consistent", _consistency_or(obs.open_orders_consistent, orders_source, "consistent", "match", "reconciled")),
            ("protection_consistent", _consistency_or(obs.protection_consistent, protection_source, "consistent", "match", "reconciled")),
        )
        for name, value in consistency:
            if value is None:
                reasons.append(f"{name}_unknown")
            elif value is False:
                reasons.append(name.replace("_consistent", "_mismatch"))

        position_value = _numeric_total(position_source)
        # An authoritative, reconciled empty position container is a known
        # flat account.  Treating ``[]`` as unknown would make an explicit
        # flat broker snapshot impossible to bootstrap or recover from.  The
        # consistency fact is the proof that the container was observed and
        # reconciled; without it, the existing fail-closed unknown path stays
        # intact.
        if (
            position_value is None
            and isinstance(position_source, (tuple, list))
            and not position_source
            and obs.positions_consistent is True
        ):
            position_value = 0.0
        exposure_value, exposure_metric_source = _explicit_numeric_metric(obs.total_exposure, "total_exposure")
        if exposure_value is None:
            exposure_value, exposure_metric_name = _explicit_numeric_metric(
                exposure_source, "gross", "gross_exposure", "total", "notional", "value"
            )
            exposure_metric_source = f"exposure.{exposure_metric_name}" if exposure_metric_name else None
        else:
            exposure_metric_source = "observation.total_exposure"
        cash_value, cash_metric_source = _explicit_numeric_metric(obs.account_equity, "account_equity")
        if cash_value is None:
            cash_value, cash_metric_name = _explicit_numeric_metric(
                cash_source, "equity", "account_equity", "balance", "available", "total"
            )
            cash_metric_source = f"cash.{cash_metric_name}" if cash_metric_name else None
        else:
            cash_metric_source = "observation.account_equity"
        pnl_value, pnl_metric_source = _explicit_pnl_metric(obs.daily_pnl)
        if pnl_value is None:
            pnl_value, pnl_metric_name = _explicit_pnl_metric(pnl_source)
            pnl_metric_source = f"pnl.{pnl_metric_name}" if pnl_metric_name else None
        else:
            pnl_metric_source = "observation.daily_pnl"
        # A configured drawdown limit may consume only a versioned,
        # account/snapshot-bound fact in one explicitly selected unit.  The
        # legacy bare ``drawdown``/``drawdown_pct`` fields remain visible to
        # callers but can no longer silently choose the policy unit.
        drawdown_value: float | None = None
        drawdown_metric_source: str | None = None
        drawdown_fact = _read(account_facts, "account_drawdown", default=None)
        if self.config.max_drawdown is not None:
            if self.config.max_drawdown_unit == "unknown":
                reasons.append("max_drawdown_unit_unknown")
            else:
                try:
                    resolved_drawdown = resolve_drawdown_metric(
                        drawdown_fact if isinstance(drawdown_fact, Mapping) else {},
                        expected_account_identity_hash=obs.account_identity,
                        expected_snapshot_sha256=obs.account_snapshot_sha256,
                        expected_observed_at_utc=obs.observed_at_utc,
                        unit=self.config.max_drawdown_unit,
                    )
                except AccountRiskFactError as exc:
                    reasons.append(str(exc))
                else:
                    drawdown_value = float(resolved_drawdown)
                    drawdown_metric_source = (
                        "account_facts.account_drawdown.drawdown_amount_usdt"
                        if self.config.max_drawdown_unit == "usdt"
                        else "account_facts.account_drawdown.drawdown_ratio"
                    )
        if self.config.require_positions and position_value is None:
            reasons.append("positions_unknown")
        if self.config.require_cash and cash_value is None:
            reasons.append("cash_unknown")
        if self.config.require_pnl and pnl_value is None:
            reasons.append("pnl_unknown")
        if self.config.require_exposure and exposure_value is None:
            reasons.append("exposure_unknown")
        if self.config.max_drawdown is not None and drawdown_value is None:
            reasons.append("drawdown_unknown")
        if orders_source is None:
            derived_risk, derived_protective, derived_order_blockers = None, None, ()
        else:
            derived_risk, derived_protective, derived_order_blockers = classify_order_risk(
                orders_source,
                position_source,
                owner_identity=obs.owner_identity,
            )
        order_count = (
            obs.risk_increasing_open_order_count
            if obs.risk_increasing_open_order_count is not None
            else (
                obs.open_order_count
                if obs.open_order_count is not None
                else (derived_risk if isinstance(orders_source, (tuple, list)) else _count_open_orders(orders_source))
            )
        )
        protective_order_count = (
            obs.protective_reduce_only_order_count
            if obs.protective_reduce_only_order_count is not None
            else (derived_protective if derived_protective is not None else 0)
        )
        reasons.extend(obs.order_risk_blockers)
        reasons.extend(derived_order_blockers)
        if self.config.require_open_orders and order_count is None:
            reasons.append("open_orders_unknown")
        if self.config.require_protection and protection_source is None:
            reasons.append("protection_facts_unknown")

        if exposure_value is not None and self.config.max_abs_exposure is not None:
            if abs(exposure_value) > self.config.max_abs_exposure:
                reasons.append("max_abs_exposure_breach")
        if pnl_value is not None and self.config.max_daily_loss is not None:
            if pnl_value < -self.config.max_daily_loss:
                reasons.append("max_daily_loss_breach")
        if drawdown_value is not None and self.config.max_drawdown is not None:
            if abs(drawdown_value) > self.config.max_drawdown:
                reasons.append("max_drawdown_breach")
        if order_count is not None and self.config.max_open_orders is not None and order_count > self.config.max_open_orders:
            reasons.append("max_open_orders_breach")
        if cash_value is not None and cash_value < 0.0:
            reasons.append("cash_negative")
        if exposure_value is not None and exposure_value < 0.0:
            reasons.append("exposure_negative")

        final_reason_codes = _dedupe(reasons)
        final_status = GuardianStatus.PASS if not final_reason_codes else GuardianStatus.TRIPPED
        evidence_identity = obs.evidence_identity or "derived"
        decision_payload = {
            "policy": self.config.to_dict(),
            "config_version": self.config.config_version,
            "source_head": obs.source_head,
            "account_identity": obs.account_identity,
            "account_snapshot_sha256": obs.account_snapshot_sha256,
            "session_id": obs.session_id,
            "key_namespace": obs.key_namespace,
            "client_order_namespace": obs.client_order_namespace,
            "epoch": obs.epoch,
            "observed_at_utc": observed,
            "reference_time_utc": reference,
            "heartbeat_at_utc": heartbeat,
            "heartbeat_healthy": heartbeat_healthy,
            "broker_truth_fresh": broker_truth_fresh,
            "facts_fresh": facts_fresh,
            "reconciliation_passed": reconciliation_passed,
            "ledger_reconciled": obs.ledger_reconciled,
            "snapshot_match": obs.snapshot_match,
            "funding_reconciled": obs.funding_reconciled,
            "freshness": obs.freshness,
            "consistency": {name: value for name, value in consistency},
            "positions": position_source,
            "cash": cash_source,
            "pnl": pnl_source,
            "exposure": exposure_source,
            "open_orders": orders_source,
            "protection_facts": protection_source,
            "account_facts": account_facts,
            "account_equity": cash_value,
            "total_exposure": exposure_value,
            "daily_pnl": pnl_value,
            "drawdown": drawdown_value,
            "open_order_count": order_count,
            "risk_increasing_open_order_count": order_count,
            "protective_reduce_only_order_count": protective_order_count,
            "order_risk_blockers": _dedupe((*obs.order_risk_blockers, *derived_order_blockers)),
            "effective_metric_sources": {
                "account_equity": cash_metric_source,
                "total_exposure": exposure_metric_source,
                "daily_pnl": pnl_metric_source,
                "drawdown": drawdown_metric_source,
                "open_order_count": "observation.open_order_count" if obs.open_order_count is not None else "open_orders",
                "risk_increasing_open_order_count": (
                    "observation.risk_increasing_open_order_count"
                    if obs.risk_increasing_open_order_count is not None
                    else "open_orders"
                ),
                "protective_reduce_only_order_count": (
                    "observation.protective_reduce_only_order_count"
                    if obs.protective_reduce_only_order_count is not None
                    else "open_orders"
                ),
            },
            "evidence_identity": evidence_identity,
            "status": final_status.value,
            "reason_codes": final_reason_codes,
        }
        observation_digest = _digest(decision_payload)
        evidence_digest = _digest({
            "identity": evidence_identity,
            "observation_digest": observation_digest,
            "policy": self.config.to_dict(),
            "config_version": self.config.config_version,
            "status": final_status.value,
            "reason_codes": final_reason_codes,
        })
        return GuardianDecision(
            status=final_status,
            reason_codes=final_reason_codes,
            evidence_identity=evidence_identity,
            evidence_digest=evidence_digest,
            observation_digest=observation_digest,
            source_head=obs.source_head,
            account_identity=obs.account_identity,
            session_id=obs.session_id,
            key_namespace=obs.key_namespace,
            client_order_namespace=obs.client_order_namespace,
            epoch=obs.epoch,
            generation=generation,
            reference_time_utc=reference,
            config_version=self.config.config_version,
        )

    assess = evaluate
    decide = evaluate
    check = evaluate
    evaluate_observation = evaluate

    @staticmethod
    def _require_bool(reasons: list[str], value: bool | None, name: str) -> None:
        if value is None:
            reasons.append(name if name.endswith("_unknown") else f"{name}_unknown")
        elif type(value) is not bool:
            reasons.append(f"{name}_invalid")

    def __call__(self, observation: GuardianObservation | Mapping[str, Any], *, generation: int = 0) -> GuardianDecision:
        return self.evaluate(observation, generation=generation)


class GuardianWriterLease:
    """Opaque lifecycle lease held by exactly one supervisor/store pair."""

    __slots__ = ("owner_id", "fence_token", "_store", "_token", "_active")

    def __init__(self, store: object, owner_id: str, fence_token: str) -> None:
        self.owner_id = str(owner_id).strip()
        self.fence_token = str(fence_token).strip()
        self._store = store
        self._token = object()
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def release(self) -> None:
        if self._active:
            release = getattr(self._store, "_release_lease", None)
            if release is None:
                raise GuardianPersistenceError("latch_lease_release_unsupported")
            release(self)


@dataclass(frozen=True)
class GuardianLatchRecord:
    """Auditable sticky state; trip and recovery evidence are distinct."""

    generation: int
    tripped: bool
    owner_id: str
    fence_token: str
    state_revision: int = 1
    reason_codes: tuple[str, ...] = ()
    evidence_identity: str = ""
    evidence_digest: str = ""
    observation_digest: str = ""
    trip_reference_time_utc: datetime | None = None
    acknowledgement_id: str = ""
    acknowledgement_generation: int | None = None
    acknowledgement_evidence_identity: str = ""
    acknowledgement_evidence_digest: str = ""
    recovery_evidence_identity: str = ""
    recovery_evidence_digest: str = ""
    recovery_reference_time_utc: datetime | None = None
    cleared_reference_time_utc: datetime | None = None
    source_head: str = ""
    account_identity: str = ""
    session_id: str = ""
    key_namespace: str = ""
    client_order_namespace: str = ""
    epoch: int | None = None
    schema_version: str = BTC_RUNTIME_LATCH_SCHEMA_VERSION
    guardian_version: str = BTC_RUNTIME_RISK_GUARDIAN_VERSION

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("latch_generation_invalid")
        if type(self.state_revision) is not int or self.state_revision < 1:
            raise ValueError("latch_state_revision_invalid")
        if type(self.tripped) is not bool:
            raise TypeError("latch_tripped_must_be_bool")
        if not str(self.owner_id).strip() or not str(self.fence_token).strip():
            raise ValueError("latch_writer_identity_required")
        if self.schema_version != BTC_RUNTIME_LATCH_SCHEMA_VERSION:
            raise ValueError("latch_schema_version_invalid")
        if self.guardian_version != BTC_RUNTIME_RISK_GUARDIAN_VERSION:
            raise ValueError("latch_guardian_version_invalid")
        object.__setattr__(self, "owner_id", str(self.owner_id).strip())
        object.__setattr__(self, "fence_token", str(self.fence_token).strip())
        object.__setattr__(self, "reason_codes", _dedupe(self.reason_codes))
        for name in (
            "evidence_identity", "evidence_digest", "observation_digest",
            "acknowledgement_id", "acknowledgement_evidence_identity",
            "acknowledgement_evidence_digest", "recovery_evidence_identity",
            "recovery_evidence_digest",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        for name in ("source_head", "account_identity", "session_id", "key_namespace", "client_order_namespace"):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        if self.epoch is not None and (type(self.epoch) is not int or self.epoch < 0):
            raise ValueError("latch_epoch_invalid")
        for name in ("trip_reference_time_utc", "recovery_reference_time_utc", "cleared_reference_time_utc"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, datetime):
                raise TypeError(f"{name}_must_be_datetime")
        if self.acknowledgement_generation is not None:
            if type(self.acknowledgement_generation) is not int or self.acknowledgement_generation < 1:
                raise ValueError("acknowledgement_generation_invalid")

    @property
    def cleared(self) -> bool:
        return not self.tripped

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reason_codes

    @property
    def acknowledged(self) -> bool:
        return bool(
            self.acknowledgement_id
            and self.acknowledgement_generation == self.generation
            and self.acknowledgement_evidence_identity == self.evidence_identity
            and self.acknowledgement_evidence_digest == self.evidence_digest
        )

    @classmethod
    def from_decision(
        cls,
        decision: GuardianDecision,
        *,
        generation: int,
        owner_id: str,
        fence_token: str,
        state_revision: int = 1,
    ) -> "GuardianLatchRecord":
        return cls(
            generation=generation,
            tripped=True,
            owner_id=owner_id,
            fence_token=fence_token,
            state_revision=state_revision,
            reason_codes=decision.reason_codes,
            evidence_identity=decision.evidence_identity,
            evidence_digest=decision.evidence_digest,
            observation_digest=decision.observation_digest,
            trip_reference_time_utc=decision.reference_time_utc,
            source_head=decision.source_head,
            account_identity=decision.account_identity,
            session_id=decision.session_id,
            key_namespace=decision.key_namespace,
            client_order_namespace=decision.client_order_namespace,
            epoch=decision.epoch,
        )

    def with_owner(self, owner_id: str, fence_token: str, *, state_revision: int) -> "GuardianLatchRecord":
        return replace(self, owner_id=owner_id, fence_token=fence_token, state_revision=state_revision)

    def acknowledge(self, acknowledgement_id: str, *, state_revision: int) -> "GuardianLatchRecord":
        if not self.tripped:
            raise GuardianRecoveryRejected("latch_not_tripped")
        if not str(acknowledgement_id).strip():
            raise GuardianRecoveryRejected("operator_acknowledgement_id_missing")
        return replace(
            self,
            state_revision=state_revision,
            acknowledgement_id=str(acknowledgement_id).strip(),
            acknowledgement_generation=self.generation,
            acknowledgement_evidence_identity=self.evidence_identity,
            acknowledgement_evidence_digest=self.evidence_digest,
        )

    def clear(
        self,
        *,
        reference_time_utc: datetime | None,
        recovery_evidence_identity: str,
        recovery_evidence_digest: str,
        state_revision: int,
    ) -> "GuardianLatchRecord":
        if not self.acknowledged:
            raise GuardianRecoveryRejected("operator_ack_or_generation_mismatch")
        if not str(recovery_evidence_identity).strip() or not str(recovery_evidence_digest).strip():
            raise GuardianRecoveryRejected("recovery_evidence_missing")
        return replace(
            self,
            state_revision=state_revision,
            tripped=False,
            recovery_evidence_identity=str(recovery_evidence_identity).strip(),
            recovery_evidence_digest=str(recovery_evidence_digest).strip(),
            recovery_reference_time_utc=reference_time_utc,
            cleared_reference_time_utc=reference_time_utc,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "guardian_version": self.guardian_version,
            "generation": self.generation,
            "state_revision": self.state_revision,
            "tripped": self.tripped,
            "cleared": self.cleared,
            "owner_id": self.owner_id,
            "fence_token": self.fence_token,
            "reason_codes": list(self.reason_codes),
            "evidence_identity": self.evidence_identity,
            "evidence_digest": self.evidence_digest,
            "observation_digest": self.observation_digest,
            "source_head": self.source_head,
            "account_identity": self.account_identity,
            "session_id": self.session_id,
            "key_namespace": self.key_namespace,
            "client_order_namespace": self.client_order_namespace,
            "epoch": self.epoch,
            "trip_reference_time_utc": _jsonable(self.trip_reference_time_utc),
            "acknowledgement_id": self.acknowledgement_id,
            "acknowledgement_generation": self.acknowledgement_generation,
            "acknowledgement_evidence_identity": self.acknowledgement_evidence_identity,
            "acknowledgement_evidence_digest": self.acknowledgement_evidence_digest,
            "acknowledged": self.acknowledged,
            "recovery_evidence_identity": self.recovery_evidence_identity,
            "recovery_evidence_digest": self.recovery_evidence_digest,
            "recovery_reference_time_utc": _jsonable(self.recovery_reference_time_utc),
            "cleared_reference_time_utc": _jsonable(self.cleared_reference_time_utc),
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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GuardianLatchRecord":
        try:
            def parse_time(raw: object) -> datetime | None:
                if raw in (None, ""):
                    return None
                if not isinstance(raw, str):
                    raise ValueError("latch_timestamp_invalid")
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))

            data = dict(value)
            tripped = data["tripped"]
            if type(tripped) is not bool:
                raise ValueError("latch_tripped_must_be_bool")
            return cls(
                generation=data["generation"],
                state_revision=data.get("state_revision", 1),
                tripped=tripped,
                owner_id=data["owner_id"],
                fence_token=data["fence_token"],
                reason_codes=tuple(data.get("reason_codes", ())),
                evidence_identity=data.get("evidence_identity", ""),
                evidence_digest=data.get("evidence_digest", ""),
                observation_digest=data.get("observation_digest", ""),
                trip_reference_time_utc=parse_time(data.get("trip_reference_time_utc")),
                acknowledgement_id=data.get("acknowledgement_id", ""),
                acknowledgement_generation=data.get("acknowledgement_generation"),
                acknowledgement_evidence_identity=data.get("acknowledgement_evidence_identity", ""),
                acknowledgement_evidence_digest=data.get("acknowledgement_evidence_digest", ""),
                recovery_evidence_identity=data.get("recovery_evidence_identity", ""),
                recovery_evidence_digest=data.get("recovery_evidence_digest", ""),
                recovery_reference_time_utc=parse_time(data.get("recovery_reference_time_utc")),
                cleared_reference_time_utc=parse_time(data.get("cleared_reference_time_utc")),
                source_head=data.get("source_head", ""),
                account_identity=data.get("account_identity", ""),
                session_id=data.get("session_id", ""),
                key_namespace=data.get("key_namespace", ""),
                client_order_namespace=data.get("client_order_namespace", ""),
                epoch=data.get("epoch"),
                schema_version=data.get("schema_version", ""),
                guardian_version=data.get("guardian_version", ""),
            )
        except GuardianError:
            raise
        except Exception as exc:
            raise GuardianPersistenceError("latch_persistence_corrupt") from exc


@runtime_checkable
class GuardianLatchStore(Protocol):
    def acquire(self, owner_id: str, fence_token: str) -> GuardianWriterLease: ...
    def release(self, lease: GuardianWriterLease) -> None: ...
    def load_optional(self) -> GuardianLatchRecord | None: ...
    def save(
        self,
        record: GuardianLatchRecord,
        *,
        expected_generation: int,
        expected_revision: int,
        owner_id: str,
        fence_token: str,
        lease: GuardianWriterLease,
    ) -> None: ...
    def rebind_owner(
        self,
        record: GuardianLatchRecord,
        *,
        expected_generation: int,
        expected_revision: int,
        owner_id: str,
        fence_token: str,
        lease: GuardianWriterLease,
    ) -> None: ...


def _check_record_cas(
    existing: GuardianLatchRecord | None,
    record: GuardianLatchRecord,
    *,
    expected_generation: int,
    expected_revision: int,
    owner_id: str,
    fence_token: str,
    allow_rebind: bool = False,
) -> None:
    if record.owner_id != owner_id or record.fence_token != fence_token:
        raise GuardianStaleWriterError("latch_writer_fence_mismatch")
    if existing is None:
        if expected_generation != 0 or expected_revision != 0:
            raise GuardianStaleWriterError("latch_generation_or_revision_mismatch")
    else:
        if existing.generation != expected_generation:
            raise GuardianStaleWriterError("latch_generation_mismatch")
        if existing.state_revision != expected_revision:
            raise GuardianStaleWriterError("latch_state_revision_mismatch")
        if not allow_rebind and (existing.owner_id != owner_id or existing.fence_token != fence_token):
            raise GuardianStaleWriterError("latch_writer_fence_mismatch")
    if record.state_revision != expected_revision + 1:
        raise GuardianStaleWriterError("latch_state_revision_not_monotonic")


class InMemoryGuardianLatchStore:
    """Deterministic store with the same lifecycle lease/CAS contract as File."""

    _active_namespaces: dict[str, GuardianWriterLease] = {}

    def __init__(self, record: GuardianLatchRecord | None = None, *, namespace: str | None = None) -> None:
        self._record = record
        self._namespace = namespace or f"inmemory:{id(self)}"
        self._active_lease: GuardianWriterLease | None = None
        self.fail_next_save = False
        self.locked = False

    def acquire(self, owner_id: str, fence_token: str) -> GuardianWriterLease:
        if self.locked or self._active_lease is not None or self._namespace in self._active_namespaces:
            raise GuardianConcurrentWriterError("latch_concurrent_writer")
        lease = GuardianWriterLease(self, owner_id, fence_token)
        self._active_lease = lease
        self._active_namespaces[self._namespace] = lease
        return lease

    def _require_lease(self, lease: GuardianWriterLease, owner_id: str, fence_token: str) -> None:
        if (
            not isinstance(lease, GuardianWriterLease)
            or not lease.active
            or lease._store is not self
            or self._active_lease is not lease
            or lease.owner_id != owner_id
            or lease.fence_token != fence_token
        ):
            raise GuardianStaleWriterError("latch_writer_lease_stale")

    def _release_lease(self, lease: GuardianWriterLease) -> None:
        self._require_lease(lease, lease.owner_id, lease.fence_token)
        self._active_lease = None
        self._active_namespaces.pop(self._namespace, None)
        lease._active = False

    def release(self, lease: GuardianWriterLease) -> None:
        self._release_lease(lease)

    def load_optional(self) -> GuardianLatchRecord | None:
        return self._record

    def save(
        self,
        record: GuardianLatchRecord,
        *,
        expected_generation: int,
        expected_revision: int,
        owner_id: str,
        fence_token: str,
        lease: GuardianWriterLease,
    ) -> None:
        self._require_lease(lease, owner_id, fence_token)
        if self.locked:
            raise GuardianConcurrentWriterError("latch_concurrent_writer")
        if self.fail_next_save:
            self.fail_next_save = False
            raise GuardianPersistenceError("latch_persist_failed")
        _check_record_cas(self._record, record, expected_generation=expected_generation, expected_revision=expected_revision, owner_id=owner_id, fence_token=fence_token)
        self._record = record

    def rebind_owner(
        self,
        record: GuardianLatchRecord,
        *,
        expected_generation: int,
        expected_revision: int,
        owner_id: str,
        fence_token: str,
        lease: GuardianWriterLease,
    ) -> None:
        self._require_lease(lease, owner_id, fence_token)
        if self.locked:
            raise GuardianConcurrentWriterError("latch_concurrent_writer")
        if self.fail_next_save:
            self.fail_next_save = False
            raise GuardianPersistenceError("latch_persist_failed")
        _check_record_cas(self._record, record, expected_generation=expected_generation, expected_revision=expected_revision, owner_id=owner_id, fence_token=fence_token, allow_rebind=True)
        self._record = record


class FileGuardianLatchStore:
    """JSON store with an OS lock held for the entire supervisor lifecycle."""

    def __init__(self, path: str | Path) -> None:
        resolved = Path(path)
        if not resolved.is_absolute():
            raise ValueError("latch_store_path_must_be_absolute")
        self.path = resolved
        self.lock_path = resolved.with_name(resolved.name + ".lock")
        self._active_lease: GuardianWriterLease | None = None
        self._lock_fd: int | None = None

    @staticmethod
    def _lock_fd_exclusive(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_fd(fd: int) -> None:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)

    def acquire(self, owner_id: str, fence_token: str) -> GuardianWriterLease:
        if self._active_lease is not None:
            raise GuardianConcurrentWriterError("latch_concurrent_writer")
        parent = self.path.parent
        if not parent.exists() or not parent.is_dir():
            raise GuardianPersistenceError("latch_store_parent_missing")
        try:
            fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT)
            try:
                self._lock_fd_exclusive(fd)
            except (BlockingIOError, PermissionError, OSError) as exc:
                os.close(fd)
                raise GuardianConcurrentWriterError("latch_concurrent_writer") from exc
            self._lock_fd = fd
            lease = GuardianWriterLease(self, owner_id, fence_token)
            self._active_lease = lease
            return lease
        except GuardianError:
            raise
        except Exception as exc:
            raise GuardianPersistenceError("latch_lease_acquire_failed") from exc

    def _require_lease(self, lease: GuardianWriterLease, owner_id: str, fence_token: str) -> None:
        if (
            not isinstance(lease, GuardianWriterLease)
            or not lease.active
            or lease._store is not self
            or self._active_lease is not lease
            or lease.owner_id != owner_id
            or lease.fence_token != fence_token
            or self._lock_fd is None
        ):
            raise GuardianStaleWriterError("latch_writer_lease_stale")

    def _release_lease(self, lease: GuardianWriterLease) -> None:
        self._require_lease(lease, lease.owner_id, lease.fence_token)
        fd = self._lock_fd
        self._active_lease = None
        self._lock_fd = None
        try:
            if fd is not None:
                self._unlock_fd(fd)
                os.close(fd)
        except Exception as exc:
            raise GuardianPersistenceError("latch_lease_release_failed") from exc
        finally:
            lease._active = False

    def release(self, lease: GuardianWriterLease) -> None:
        self._release_lease(lease)

    def load_optional(self) -> GuardianLatchRecord | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("latch_payload_not_mapping")
            return GuardianLatchRecord.from_dict(payload)
        except GuardianError:
            raise
        except Exception as exc:
            raise GuardianPersistenceError("latch_persistence_corrupt") from exc

    def load(self) -> GuardianLatchRecord:
        record = self.load_optional()
        if record is None:
            raise GuardianPersistenceError("latch_persistence_missing")
        return record

    def _write(self, record: GuardianLatchRecord) -> None:
        parent = self.path.parent
        payload = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _save_checked(
        self,
        record: GuardianLatchRecord,
        *,
        expected_generation: int,
        expected_revision: int,
        owner_id: str,
        fence_token: str,
        lease: GuardianWriterLease,
        allow_rebind: bool,
    ) -> None:
        self._require_lease(lease, owner_id, fence_token)
        existing = self.load_optional()
        _check_record_cas(existing, record, expected_generation=expected_generation, expected_revision=expected_revision, owner_id=owner_id, fence_token=fence_token, allow_rebind=allow_rebind)
        try:
            self._write(record)
        except GuardianError:
            raise
        except Exception as exc:
            raise GuardianPersistenceError("latch_persist_failed") from exc

    def save(
        self,
        record: GuardianLatchRecord,
        *,
        expected_generation: int,
        expected_revision: int,
        owner_id: str,
        fence_token: str,
        lease: GuardianWriterLease,
    ) -> None:
        self._save_checked(record, expected_generation=expected_generation, expected_revision=expected_revision, owner_id=owner_id, fence_token=fence_token, lease=lease, allow_rebind=False)

    def rebind_owner(
        self,
        record: GuardianLatchRecord,
        *,
        expected_generation: int,
        expected_revision: int,
        owner_id: str,
        fence_token: str,
        lease: GuardianWriterLease,
    ) -> None:
        self._save_checked(record, expected_generation=expected_generation, expected_revision=expected_revision, owner_id=owner_id, fence_token=fence_token, lease=lease, allow_rebind=True)


DurableFileLatchStore = FileGuardianLatchStore
RuntimeRiskLatchStore = FileGuardianLatchStore


class RuntimeRiskGuardianSupervisor:
    """Single-writer supervisor around a sticky guardian latch.

    Construction acquires a lifecycle lease.  All durable mutations use the
    lease plus a monotonic generation/revision CAS; the in-memory read model
    is updated only after the durable write succeeds.
    """

    def __init__(
        self,
        guardian: RuntimeRiskGuardian,
        store: GuardianLatchStore | str | Path | None = None,
        *,
        owner_id: str,
        fence_token: str,
        latch_path: str | Path | None = None,
        storage: GuardianLatchStore | None = None,
    ) -> None:
        if not isinstance(guardian, RuntimeRiskGuardian):
            raise TypeError("guardian_required")
        if store is None:
            store = storage if storage is not None else latch_path
        if isinstance(store, (str, Path)):
            store = FileGuardianLatchStore(store)
        if not isinstance(store, GuardianLatchStore):
            raise TypeError("latch_store_required")
        if not str(owner_id).strip() or not str(fence_token).strip():
            raise ValueError("supervisor_writer_identity_required")
        self.guardian = guardian
        self.store = store
        self.owner_id = str(owner_id).strip()
        self.fence_token = str(fence_token).strip()
        self._record: GuardianLatchRecord | None = None
        self._persistence_error: str = ""
        self._closed = False
        self._lease: GuardianWriterLease | None = None
        try:
            self._lease = self.store.acquire(self.owner_id, self.fence_token)
            self._load_and_rebind()
        except GuardianPersistenceError as exc:
            # A corrupt/missing durable state is visible only as blocked.  A
            # lease-acquisition/concurrency failure remains a hard rejection.
            if isinstance(exc, GuardianConcurrentWriterError):
                raise
            self._record = None
            self._persistence_error = str(exc) or "latch_persistence_failed"

    def _require_open(self) -> GuardianWriterLease:
        if self._closed or self._lease is None or not self._lease.active:
            raise GuardianStaleWriterError("supervisor_lease_lost")
        return self._lease

    def _load_and_rebind(self) -> GuardianLatchRecord | None:
        lease = self._require_open()
        loaded = self.store.load_optional()
        if loaded is not None and (loaded.owner_id != self.owner_id or loaded.fence_token != self.fence_token):
            rebound = loaded.with_owner(self.owner_id, self.fence_token, state_revision=loaded.state_revision + 1)
            self.store.rebind_owner(
                rebound,
                expected_generation=loaded.generation,
                expected_revision=loaded.state_revision,
                owner_id=self.owner_id,
                fence_token=self.fence_token,
                lease=lease,
            )
            loaded = rebound
        self._record = loaded
        self._persistence_error = ""
        return loaded

    def reload(self) -> GuardianLatchRecord | None:
        self._require_open()
        try:
            return self._load_and_rebind()
        except GuardianStaleWriterError:
            raise
        except GuardianPersistenceError as exc:
            self._record = None
            self._persistence_error = str(exc) or "latch_persistence_failed"
            return None

    @property
    def latch(self) -> GuardianLatchRecord | None:
        return self._record

    @property
    def persistence_error(self) -> str:
        return self._persistence_error

    @property
    def tripped(self) -> bool:
        return bool(self._record and self._record.tripped)

    def evaluate(self, observation: GuardianObservation | Mapping[str, Any]) -> GuardianDecision:
        generation = self._record.generation if self._record else 0
        decision = self.guardian.evaluate(observation, generation=generation)
        if self._closed or self._lease is None or not self._lease.active:
            return decision.with_blockers("supervisor_lease_lost")
        if self._persistence_error:
            return decision.with_blockers("latch_persistence_blocked")
        if self._record is None:
            return decision.with_blockers("latch_persistence_missing")
        if self.tripped:
            return decision.with_blockers("guardian_latch_tripped")
        return decision

    assess = evaluate

    def trip(self, observation: GuardianObservation | Mapping[str, Any]) -> GuardianDecision:
        self._require_open()
        decision = self.guardian.evaluate(observation, generation=self._record.generation if self._record else 0)
        if not decision.tripped:
            return self.evaluate(observation)
        if self._persistence_error:
            raise GuardianPersistenceError(self._persistence_error)
        self.reload()
        if self._persistence_error:
            raise GuardianPersistenceError(self._persistence_error)
        current = self._record
        if current is not None and current.tripped and current.evidence_digest == decision.evidence_digest:
            return replace(decision, generation=current.generation)
        generation = (current.generation + 1) if current is not None else 1
        record = GuardianLatchRecord.from_decision(
            decision,
            generation=generation,
            owner_id=self.owner_id,
            fence_token=self.fence_token,
            state_revision=(current.state_revision + 1) if current is not None else 1,
        )
        expected_generation = current.generation if current is not None else 0
        expected_revision = current.state_revision if current is not None else 0
        try:
            self.store.save(
                record,
                expected_generation=expected_generation,
                expected_revision=expected_revision,
                owner_id=self.owner_id,
                fence_token=self.fence_token,
                lease=self._require_open(),
            )
        except GuardianPersistenceError as exc:
            self._persistence_error = str(exc) or "latch_persist_failed"
            raise
        self._record = record
        return replace(decision, generation=generation)

    observe = trip
    trip_if_needed = trip

    def acknowledge(
        self,
        *,
        generation: int,
        evidence_identity: str,
        evidence_digest: str,
        acknowledgement_id: str,
    ) -> GuardianLatchRecord:
        self._require_open()
        self.reload()
        if self._persistence_error:
            raise GuardianPersistenceError(self._persistence_error)
        record = self._record
        if record is None or not record.tripped:
            raise GuardianRecoveryRejected("latch_not_tripped")
        if generation != record.generation or evidence_identity != record.evidence_identity or evidence_digest != record.evidence_digest:
            raise GuardianRecoveryRejected("operator_ack_generation_or_evidence_mismatch")
        updated = record.acknowledge(acknowledgement_id, state_revision=record.state_revision + 1)
        try:
            self.store.save(
                updated,
                expected_generation=record.generation,
                expected_revision=record.state_revision,
                owner_id=self.owner_id,
                fence_token=self.fence_token,
                lease=self._require_open(),
            )
        except GuardianPersistenceError as exc:
            self._persistence_error = str(exc) or "latch_persist_failed"
            raise
        self._record = updated
        return updated

    ack = acknowledge
    record_operator_ack = acknowledge

    def bootstrap_or_recover(
        self,
        observation: GuardianObservation | Mapping[str, Any],
        *,
        operator_confirmation: bool,
        expected_generation: int = 0,
        expected_revision: int = 0,
        recovery_evidence_identity: str,
        recovery_evidence_digest: str,
    ) -> GuardianLatchRecord:
        """Explicitly create or clear the durable latch from fresh evidence.

        A missing latch is not a healthy default.  This method is the only
        path allowed to initialize it, and it always persists either a clear
        generation (only for a complete PASS observation) or a sticky trip.
        Existing trips still require the prior generation's acknowledgement
        and the normal newer-observation checks in :meth:`clear`.
        """

        self._require_open()
        if operator_confirmation is not True:
            raise GuardianRecoveryRejected("operator_recovery_confirmation_required")
        if not str(recovery_evidence_identity).strip() or not str(recovery_evidence_digest).strip():
            raise GuardianRecoveryRejected("recovery_evidence_missing")
        self.reload()
        if self._persistence_error:
            raise GuardianPersistenceError(self._persistence_error)
        current = self._record
        if current is not None:
            if expected_generation != current.generation or expected_revision != current.state_revision:
                raise GuardianStaleWriterError("latch_generation_or_revision_mismatch")
            if not current.tripped:
                raise GuardianRecoveryRejected("latch_already_cleared")
            # ``clear`` re-evaluates the same observation and enforces ack,
            # identity, and strictly newer reference time.
            return self.clear(
                observation,
                recovery_evidence_identity=recovery_evidence_identity,
                recovery_evidence_digest=recovery_evidence_digest,
            )
        if expected_generation != 0 or expected_revision != 0:
            raise GuardianStaleWriterError("latch_generation_or_revision_mismatch")
        normalized_observation = (
            GuardianObservation.from_mapping(observation)
            if isinstance(observation, Mapping)
            else observation
        )
        decision = self.guardian.evaluate(normalized_observation, generation=0)
        if decision.passed:
            initial_position_value = _numeric_total(normalized_observation.positions)
            if initial_position_value is not None and abs(initial_position_value) > 0.0:
                decision = decision.with_blockers("initial_nonflat_position")
            elif isinstance(normalized_observation.open_orders, (tuple, list)) and normalized_observation.open_orders:
                decision = decision.with_blockers("initial_open_order_present")
        generation = 1
        if decision.passed:
            if (
                str(recovery_evidence_identity).strip() != decision.evidence_identity
                or str(recovery_evidence_digest).strip() != decision.evidence_digest
            ):
                raise GuardianRecoveryRejected("recovery_evidence_mismatch")
            record = GuardianLatchRecord(
                generation=generation,
                tripped=False,
                owner_id=self.owner_id,
                fence_token=self.fence_token,
                state_revision=1,
                reason_codes=(),
                evidence_identity=decision.evidence_identity,
                evidence_digest=decision.evidence_digest,
                observation_digest=decision.observation_digest,
                recovery_evidence_identity=str(recovery_evidence_identity).strip(),
                recovery_evidence_digest=str(recovery_evidence_digest).strip(),
                recovery_reference_time_utc=decision.reference_time_utc,
                cleared_reference_time_utc=decision.reference_time_utc,
                source_head=decision.source_head,
                account_identity=decision.account_identity,
                session_id=decision.session_id,
                key_namespace=decision.key_namespace,
                client_order_namespace=decision.client_order_namespace,
                epoch=decision.epoch,
            )
        else:
            record = GuardianLatchRecord.from_decision(
                decision,
                generation=generation,
                owner_id=self.owner_id,
                fence_token=self.fence_token,
                state_revision=1,
            )
        try:
            self.store.save(
                record,
                expected_generation=0,
                expected_revision=0,
                owner_id=self.owner_id,
                fence_token=self.fence_token,
                lease=self._require_open(),
            )
        except GuardianPersistenceError as exc:
            self._persistence_error = str(exc) or "latch_persist_failed"
            raise
        self._record = record
        return record

    def clear(
        self,
        observation: GuardianObservation | Mapping[str, Any],
        *,
        recovery_evidence_identity: str | None = None,
        recovery_evidence_digest: str | None = None,
    ) -> GuardianLatchRecord:
        self._require_open()
        self.reload()
        if self._persistence_error:
            raise GuardianPersistenceError(self._persistence_error)
        record = self._record
        if record is None:
            raise GuardianRecoveryRejected("latch_persistence_missing")
        decision = self.guardian.evaluate(observation, generation=record.generation)
        if not decision.passed:
            raise GuardianRecoveryRejected("current_guardian_not_pass")
        if not record.tripped:
            raise GuardianRecoveryRejected("latch_already_cleared")
        if not record.acknowledged:
            raise GuardianRecoveryRejected("operator_ack_required")
        if (
            decision.source_head != record.source_head
            or decision.account_identity != record.account_identity
            or decision.session_id != record.session_id
            or decision.key_namespace != record.key_namespace
            or decision.client_order_namespace != record.client_order_namespace
            or decision.epoch != record.epoch
        ):
            raise GuardianRecoveryRejected("current_runtime_identity_mismatch")
        if (
            record.trip_reference_time_utc is not None
            and decision.reference_time_utc is not None
            and decision.reference_time_utc <= record.trip_reference_time_utc
        ):
            raise GuardianRecoveryRejected("current_health_observation_stale")
        selected_identity = str(recovery_evidence_identity or decision.evidence_identity).strip()
        selected_digest = str(recovery_evidence_digest or decision.evidence_digest).strip()
        if selected_identity != decision.evidence_identity or selected_digest != decision.evidence_digest:
            raise GuardianRecoveryRejected("recovery_evidence_mismatch")
        updated = record.clear(
            reference_time_utc=decision.reference_time_utc,
            recovery_evidence_identity=selected_identity,
            recovery_evidence_digest=selected_digest,
            state_revision=record.state_revision + 1,
        )
        try:
            self.store.save(
                updated,
                expected_generation=record.generation,
                expected_revision=record.state_revision,
                owner_id=self.owner_id,
                fence_token=self.fence_token,
                lease=self._require_open(),
            )
        except GuardianPersistenceError as exc:
            self._persistence_error = str(exc) or "latch_persist_failed"
            raise
        self._record = updated
        return updated

    clear_if_safe = clear
    recover = clear

    def close(self) -> None:
        if self._closed:
            return
        lease = self._lease
        self._closed = True
        self._lease = None
        if lease is not None and lease.active:
            try:
                self.store.release(lease)
            except GuardianPersistenceError as exc:
                self._persistence_error = str(exc) or "latch_lease_release_failed"

    def __enter__(self) -> "RuntimeRiskGuardianSupervisor":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def read_model(self) -> dict[str, Any]:
        record = self._record
        if self._closed:
            persistence_state = "lease_lost"
        elif self._persistence_error:
            persistence_state = "corrupt_or_unavailable"
        elif record is None:
            persistence_state = "missing"
        elif record.tripped and record.acknowledged:
            persistence_state = "acknowledged"
        elif record.tripped:
            persistence_state = "tripped"
        else:
            persistence_state = "cleared"
        next_action = "recover_guardian_after_fresh_preflight" if persistence_state in {"missing", "acknowledged"} else (
            "acknowledge_guardian_trip" if persistence_state == "tripped" else "refresh_account_snapshot"
        )
        return {
            "schema_version": BTC_RUNTIME_LATCH_SCHEMA_VERSION,
            "guardian_version": BTC_RUNTIME_RISK_GUARDIAN_VERSION,
            "status": "blocked" if self._closed or self._persistence_error or record is None or (record and record.tripped) else "clear",
            "persistence_state": persistence_state,
            "tripped": bool(record and record.tripped),
            "acknowledged": bool(record and record.acknowledged),
            "reason_codes": list(record.reason_codes) if record else [self._persistence_error or "latch_persistence_missing"],
            "evidence_identity": record.evidence_identity if record else "",
            "evidence_digest": record.evidence_digest if record else "",
            "observation_digest": record.observation_digest if record else "",
            "last_observation_time_utc": (
                _jsonable(record.recovery_reference_time_utc or record.trip_reference_time_utc)
                if record else None
            ),
            "next_safe_action": next_action,
            "persistence_error": self._persistence_error or ("supervisor_lease_lost" if self._closed else ("latch_persistence_missing" if record is None else None)),
            "latch": record.to_dict() if record else None,
            "generation": record.generation if record else 0,
            "state_revision": record.state_revision if record else 0,
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

    to_read_model = read_model


GuardianSupervisor = RuntimeRiskGuardianSupervisor
RuntimeGuardianSupervisor = RuntimeRiskGuardianSupervisor
RuntimeRiskGuardianConfig = GuardianConfig
RuntimeRiskGuardianObservation = GuardianObservation
RuntimeRiskGuardianDecision = GuardianDecision
StickyGuardianLatch = GuardianLatchRecord
DurableGuardianLatchStore = FileGuardianLatchStore


__all__ = [
    "BTC_RUNTIME_RISK_GUARDIAN_VERSION",
    "BTC_RUNTIME_LATCH_SCHEMA_VERSION",
    "GuardianConfig",
    "GuardianDecision",
    "GuardianError",
    "GuardianWriterLease",
    "GuardianLatchRecord",
    "GuardianLatchStore",
    "GuardianObservation",
    "classify_order_risk",
    "GuardianPersistenceError",
    "GuardianConcurrentWriterError",
    "GuardianStaleWriterError",
    "GuardianRecoveryRejected",
    "GuardianStatus",
    "RuntimeRiskGuardian",
    "RuntimeRiskGuardianSupervisor",
    "GuardianSupervisor",
    "RuntimeGuardianSupervisor",
    "FileGuardianLatchStore",
    "DurableFileLatchStore",
    "DurableGuardianLatchStore",
    "RuntimeRiskLatchStore",
    "InMemoryGuardianLatchStore",
    "RuntimeRiskGuardianConfig",
    "RuntimeRiskGuardianObservation",
    "RuntimeRiskGuardianDecision",
    "StickyGuardianLatch",
]
