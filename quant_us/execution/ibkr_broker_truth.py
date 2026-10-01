"""Canonical, fail-closed IBKR broker truth models.

The adapter owns the transport and the injected client.  This module owns the
immutable representation of what the broker said.  It deliberately contains
no SDK import, socket construction, credential lookup, or order side effect.
The public representation uses ``account_hash`` only; raw account identifiers
are accepted solely while deriving that hash inside the adapter boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "us_ibkr_broker_truth_v1"
DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 300.0
_HEX_HASH_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$", re.IGNORECASE)


class BrokerTruthStatus(str, Enum):
    """The semantic states a broker snapshot can expose to a gate."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    STALE = "stale"
    SEQUENCE_GAP = "sequence_gap"
    DUPLICATE = "duplicate"
    EPOCH_MISMATCH = "epoch_mismatch"


class BrokerTruthFreshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


# Short aliases are useful for callers that use ``SnapshotStatus`` wording.
SnapshotStatus = BrokerTruthStatus
BrokerSnapshotStatus = BrokerTruthStatus
FreshnessStatus = BrokerTruthFreshness


def account_id_hash(account_id: str) -> str:
    """Return a stable SHA-256 account identity without retaining the input."""

    return hashlib.sha256(str(account_id).strip().encode("utf-8")).hexdigest()


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            candidate = value[name]
        else:
            candidate = getattr(value, name, None)
        if candidate is not None:
            return candidate
    return default


def _rows(value: Any, *, mapping_keys: tuple[str, ...] = ()) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if mapping_keys and any(key in value for key in mapping_keys):
            return [value]
        return list(value.values())
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, Enum):
        return str(value.value).strip()
    return str(value).strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _integer(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _normalise_client_id(value: Any) -> str:
    return _text(value, "unknown")


def _normalise_status(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "_", _text(value, "unknown").lower()).strip("_") or "unknown"


def _normalise_side(value: Any) -> str:
    text = _text(value, "BUY").upper()
    return "SELL" if text in {"SELL", "SLD"} else "BUY"


def _safe_public_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Make nested broker data serialisable without exposing account IDs."""

    if depth > 4:
        return "<nested>"
    key_text = str(key).lower()
    if "account" in key_text and key_text not in {"account_hash", "account_hashes"}:
        return "<redacted>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): _safe_public_value(item, key=str(item_key), depth=depth + 1)
            for item_key, item in value.items()
            if "account" not in str(item_key).lower()
            or str(item_key).lower() in {"account_hash", "account_hashes"}
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_safe_public_value(item, depth=depth + 1) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _safe_public_value(value.to_dict(), depth=depth + 1)
    if hasattr(value, "__dict__"):
        return _safe_public_value(vars(value), depth=depth + 1)
    return _text(value)


@dataclass(frozen=True)
class BrokerOrderIdentity:
    """Explicit IBKR order identity components.

    ``ibkr_order_id`` is never treated as a global key by itself.  The stable
    key includes ``client_id`` and prefers ``permId`` when available.
    """

    internal_order_id: str = ""
    strategy_order_id: str = ""
    ibkr_order_id: str = ""
    ibkr_perm_id: str = ""
    client_id: str = "unknown"
    client_order_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "internal_order_id",
            "strategy_order_id",
            "ibkr_order_id",
            "ibkr_perm_id",
            "client_order_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "client_id", _normalise_client_id(self.client_id))

    @property
    def order_id(self) -> str:
        return self.ibkr_order_id

    @property
    def perm_id(self) -> str:
        return self.ibkr_perm_id

    @property
    def stable_key(self) -> str:
        if self.ibkr_perm_id:
            return f"ibkr:{self.client_id}:perm:{self.ibkr_perm_id}"
        if self.ibkr_order_id and self.client_id != "unknown":
            return f"ibkr:{self.client_id}:order:{self.ibkr_order_id}"
        return ""

    @property
    def is_stable(self) -> bool:
        return bool(self.stable_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "internal_order_id": self.internal_order_id,
            "strategy_order_id": self.strategy_order_id,
            "ibkr_order_id": self.ibkr_order_id,
            "ibkr_perm_id": self.ibkr_perm_id,
            "client_id": self.client_id,
            "client_order_id": self.client_order_id,
            "stable_key": self.stable_key,
        }


@dataclass(frozen=True)
class BrokerExecutionIdentity:
    """Explicit IBKR execution identity components."""

    internal_order_id: str = ""
    strategy_order_id: str = ""
    ibkr_order_id: str = ""
    ibkr_perm_id: str = ""
    ibkr_exec_id: str = ""
    client_id: str = "unknown"

    def __post_init__(self) -> None:
        for name in (
            "internal_order_id",
            "strategy_order_id",
            "ibkr_order_id",
            "ibkr_perm_id",
            "ibkr_exec_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "client_id", _normalise_client_id(self.client_id))

    @property
    def execution_id(self) -> str:
        return self.ibkr_exec_id

    @property
    def exec_id(self) -> str:
        return self.ibkr_exec_id

    @property
    def stable_key(self) -> str:
        if self.ibkr_exec_id:
            return f"ibkr:{self.client_id}:exec:{self.ibkr_exec_id}"
        return ""

    @property
    def is_stable(self) -> bool:
        return bool(self.stable_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "internal_order_id": self.internal_order_id,
            "strategy_order_id": self.strategy_order_id,
            "ibkr_order_id": self.ibkr_order_id,
            "ibkr_perm_id": self.ibkr_perm_id,
            "ibkr_exec_id": self.ibkr_exec_id,
            "client_id": self.client_id,
            "stable_key": self.stable_key,
        }


@dataclass(frozen=True)
class BrokerOrderTruth:
    identity: BrokerOrderIdentity = field(default_factory=BrokerOrderIdentity)
    symbol: str = ""
    side: str = "BUY"
    quantity: float = 0.0
    status: str = "unknown"
    filled_quantity: float = 0.0
    remaining_quantity: float | None = None
    sequence: int | None = None
    connection_epoch: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, BrokerOrderIdentity):
            object.__setattr__(self, "identity", BrokerOrderIdentity(**dict(self.identity)))
        object.__setattr__(self, "symbol", _text(self.symbol).upper())
        object.__setattr__(self, "side", _normalise_side(self.side))
        object.__setattr__(self, "quantity", _number(self.quantity, 0.0) or 0.0)
        object.__setattr__(self, "filled_quantity", _number(self.filled_quantity, 0.0) or 0.0)
        object.__setattr__(self, "remaining_quantity", _number(self.remaining_quantity))
        object.__setattr__(self, "status", _normalise_status(self.status))
        object.__setattr__(self, "sequence", _integer(self.sequence))
        object.__setattr__(self, "connection_epoch", _integer(self.connection_epoch))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def stable_key(self) -> str:
        return self.identity.stable_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "status": self.status,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "sequence": self.sequence,
            "connection_epoch": self.connection_epoch,
            "metadata": _safe_public_value(self.metadata),
        }


@dataclass(frozen=True)
class BrokerExecutionTruth:
    identity: BrokerExecutionIdentity = field(default_factory=BrokerExecutionIdentity)
    symbol: str = ""
    side: str = "BUY"
    quantity: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    executed_at: datetime | None = None
    sequence: int | None = None
    connection_epoch: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, BrokerExecutionIdentity):
            object.__setattr__(self, "identity", BrokerExecutionIdentity(**dict(self.identity)))
        object.__setattr__(self, "symbol", _text(self.symbol).upper())
        object.__setattr__(self, "side", _normalise_side(self.side))
        object.__setattr__(self, "quantity", _number(self.quantity, 0.0) or 0.0)
        object.__setattr__(self, "price", _number(self.price, 0.0) or 0.0)
        object.__setattr__(self, "commission", _number(self.commission, 0.0) or 0.0)
        object.__setattr__(self, "executed_at", _datetime(self.executed_at))
        object.__setattr__(self, "sequence", _integer(self.sequence))
        object.__setattr__(self, "connection_epoch", _integer(self.connection_epoch))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def stable_key(self) -> str:
        return self.identity.stable_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "commission": self.commission,
            "executed_at": _iso(self.executed_at),
            "sequence": self.sequence,
            "connection_epoch": self.connection_epoch,
            "metadata": _safe_public_value(self.metadata),
        }


@dataclass(frozen=True)
class BrokerPositionTruth:
    symbol: str = ""
    quantity: float = 0.0
    average_cost: float = 0.0
    market_price: float = 0.0
    unrealized_pnl: float = 0.0
    sequence: int | None = None
    connection_epoch: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol).upper())
        object.__setattr__(self, "quantity", _number(self.quantity, 0.0) or 0.0)
        object.__setattr__(self, "average_cost", _number(self.average_cost, 0.0) or 0.0)
        object.__setattr__(self, "market_price", _number(self.market_price, 0.0) or 0.0)
        object.__setattr__(self, "unrealized_pnl", _number(self.unrealized_pnl, 0.0) or 0.0)
        object.__setattr__(self, "sequence", _integer(self.sequence))
        object.__setattr__(self, "connection_epoch", _integer(self.connection_epoch))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def stable_key(self) -> str:
        return f"symbol:{self.symbol}" if self.symbol else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "average_cost": self.average_cost,
            "market_price": self.market_price,
            "unrealized_pnl": self.unrealized_pnl,
            "sequence": self.sequence,
            "connection_epoch": self.connection_epoch,
            "metadata": _safe_public_value(self.metadata),
        }


# Compatibility names used by reconciliation-oriented callers.
BrokerOrderSnapshot = BrokerOrderTruth
BrokerExecutionSnapshot = BrokerExecutionTruth
BrokerPositionSnapshot = BrokerPositionTruth


def map_broker_order_identity(
    raw: Any,
    *,
    client_id: Any = "unknown",
    internal_order_id: str = "",
    strategy_order_id: str = "",
) -> BrokerOrderIdentity:
    """Map an SDK-neutral or ib_insync-shaped order into stable components."""

    source = _field(raw, "order", default=raw)
    metadata = _field(raw, "metadata", default={})
    return BrokerOrderIdentity(
        internal_order_id=_first_text(
            _field(raw, "internal_order_id", "order_id", default=internal_order_id),
            _field(metadata, "internal_order_id", default=""),
        ),
        strategy_order_id=_first_text(
            _field(raw, "strategy_order_id", "strategy_id", default=strategy_order_id),
            _field(metadata, "strategy_order_id", default=""),
        ),
        ibkr_order_id=_first_text(
            _field(raw, "ibkr_order_id", "broker_order_id", default=""),
            _field(source, "orderId", "order_id", default=""),
            _field(raw, "orderId", default=""),
        ),
        ibkr_perm_id=_first_text(
            _field(raw, "ibkr_perm_id", "perm_id", default=""),
            _field(source, "permId", "perm_id", default=""),
            _field(raw, "permId", default=""),
        ),
        client_id=_field(source, "clientId", "client_id", default=_field(raw, "clientId", "client_id", default=client_id)),
        client_order_id=_first_text(
            _field(source, "orderRef", "order_ref", "client_order_id", default=""),
            _field(raw, "client_order_id", default=""),
        ),
    )


def map_broker_execution_identity(
    raw: Any,
    *,
    client_id: Any = "unknown",
    internal_order_id: str = "",
    strategy_order_id: str = "",
) -> BrokerExecutionIdentity:
    """Map an SDK-neutral or ib_insync-shaped execution into stable components."""

    source = _field(raw, "execution", default=raw)
    order = _field(raw, "order", default=None)
    metadata = _field(raw, "metadata", default={})
    return BrokerExecutionIdentity(
        internal_order_id=_first_text(
            _field(raw, "internal_order_id", "order_id", default=internal_order_id),
            _field(metadata, "internal_order_id", default=""),
        ),
        strategy_order_id=_first_text(
            _field(raw, "strategy_order_id", "strategy_id", default=strategy_order_id),
            _field(metadata, "strategy_order_id", default=""),
        ),
        ibkr_order_id=_first_text(
            _field(raw, "ibkr_order_id", "broker_order_id", default=""),
            _field(source, "orderId", "order_id", default=""),
            _field(raw, "orderId", default=""),
        ),
        ibkr_perm_id=_first_text(
            _field(raw, "ibkr_perm_id", "perm_id", default=""),
            _field(source, "permId", "perm_id", default=""),
            _field(order, "permId", "perm_id", default=""),
        ),
        ibkr_exec_id=_first_text(
            _field(raw, "ibkr_exec_id", "exec_id", "execution_id", "fill_id", default=""),
            _field(source, "execId", "exec_id", "execution_id", "fill_id", default=""),
            _field(raw, "execId", default=""),
        ),
        client_id=_field(source, "clientId", "client_id", default=_field(raw, "clientId", "client_id", default=client_id)),
    )


def _coerce_order_truth(raw: Any, *, client_id: Any, connection_epoch: int) -> BrokerOrderTruth:
    if isinstance(raw, BrokerOrderTruth):
        if raw.connection_epoch is None:
            return BrokerOrderTruth(
                identity=raw.identity,
                symbol=raw.symbol,
                side=raw.side,
                quantity=raw.quantity,
                status=raw.status,
                filled_quantity=raw.filled_quantity,
                remaining_quantity=raw.remaining_quantity,
                sequence=raw.sequence,
                connection_epoch=connection_epoch,
                metadata=raw.metadata,
            )
        return raw
    source_order = _field(raw, "order", default=raw)
    source_status = _field(raw, "orderStatus", "status", default=raw)
    identity = map_broker_order_identity(raw, client_id=client_id)
    order_type = _text(_field(source_order, "orderType", "order_type", default="MKT"))
    quantity = _field(source_order, "totalQuantity", "quantity", default=_field(raw, "quantity", default=0.0))
    filled = _field(source_status, "filled", "filledQuantity", "filled_quantity", default=_field(raw, "filled_quantity", default=0.0))
    remaining = _field(source_status, "remaining", "remainingQuantity", "remaining_quantity", default=_field(raw, "remaining_quantity", default=None))
    metadata = _field(raw, "metadata", default={})
    return BrokerOrderTruth(
        identity=identity,
        symbol=_field(_field(raw, "contract", default=raw), "symbol", default=_field(raw, "symbol", default="")),
        side=_field(source_order, "action", "side", default=_field(raw, "side", default="BUY")),
        quantity=quantity,
        status=_field(source_status, "status", default=source_status),
        filled_quantity=filled,
        remaining_quantity=remaining,
        sequence=_field(raw, "sequence", "order_sequence", default=_field(source_status, "sequence", default=None)),
        connection_epoch=_field(raw, "connection_epoch", "epoch", default=connection_epoch),
        metadata={"order_type": order_type, **dict(metadata or {})},
    )


def _coerce_execution_truth(raw: Any, *, client_id: Any, connection_epoch: int) -> BrokerExecutionTruth:
    if isinstance(raw, BrokerExecutionTruth):
        if raw.connection_epoch is None:
            return BrokerExecutionTruth(
                identity=raw.identity,
                symbol=raw.symbol,
                side=raw.side,
                quantity=raw.quantity,
                price=raw.price,
                commission=raw.commission,
                executed_at=raw.executed_at,
                sequence=raw.sequence,
                connection_epoch=connection_epoch,
                metadata=raw.metadata,
            )
        return raw
    source = _field(raw, "execution", default=raw)
    identity = map_broker_execution_identity(raw, client_id=client_id)
    commission_source = _field(raw, "commissionReport", "commission_report", default=raw)
    metadata = _field(raw, "metadata", default={})
    return BrokerExecutionTruth(
        identity=identity,
        symbol=_field(_field(raw, "contract", default=raw), "symbol", default=_field(raw, "symbol", default="")),
        side=_field(source, "side", default=_field(raw, "side", default="BUY")),
        quantity=_field(source, "shares", "quantity", default=_field(raw, "quantity", default=0.0)),
        price=_field(source, "price", default=_field(raw, "price", default=0.0)),
        commission=_field(commission_source, "commission", default=_field(raw, "commission", default=0.0)),
        executed_at=_field(source, "time", "filled_at", "executed_at", default=_field(raw, "executed_at", default=None)),
        sequence=_field(raw, "sequence", "execution_sequence", "exec_sequence", default=_field(source, "sequence", default=None)),
        connection_epoch=_field(raw, "connection_epoch", "epoch", default=connection_epoch),
        metadata=dict(metadata or {}),
    )


def _coerce_position_truth(raw: Any, *, connection_epoch: int) -> BrokerPositionTruth:
    if isinstance(raw, BrokerPositionTruth):
        if raw.connection_epoch is None:
            return BrokerPositionTruth(
                symbol=raw.symbol,
                quantity=raw.quantity,
                average_cost=raw.average_cost,
                market_price=raw.market_price,
                unrealized_pnl=raw.unrealized_pnl,
                sequence=raw.sequence,
                connection_epoch=connection_epoch,
                metadata=raw.metadata,
            )
        return raw
    contract = _field(raw, "contract", default=raw)
    return BrokerPositionTruth(
        symbol=_field(contract, "symbol", default=_field(raw, "symbol", default="")),
        quantity=_field(raw, "position", "quantity", default=0.0),
        average_cost=_field(raw, "avgCost", "avg_price", "average_cost", default=0.0),
        market_price=_field(raw, "marketPrice", "market_price", default=0.0),
        unrealized_pnl=_field(raw, "unrealizedPNL", "unrealized_pnl", default=0.0),
        sequence=_field(raw, "sequence", "position_sequence", default=None),
        connection_epoch=_field(raw, "connection_epoch", "epoch", default=connection_epoch),
        metadata=dict(_field(raw, "metadata", default={}) or {}),
    )


def _identity_duplicates(records: Sequence[Any]) -> bool:
    seen: set[str] = set()
    for record in records:
        key = getattr(record, "stable_key", "")
        if not key:
            continue
        if key in seen:
            return True
        seen.add(key)
    return False


def _sequence_gap(records: Sequence[Any], expected: int | None, watermark: int | None) -> bool:
    values = sorted({record.sequence for record in records if getattr(record, "sequence", None) is not None})
    if len(values) > 1 and any(next_value != current + 1 for current, next_value in zip(values, values[1:])):
        return True
    if expected is not None and watermark is not None and watermark != expected:
        return True
    if watermark is not None and values and max(values) > watermark:
        return True
    return False


@dataclass(frozen=True)
class BrokerTruthSnapshot:
    """Immutable canonical broker state used by reconciliation and gates."""

    snapshot_id: str = ""
    connection_epoch: int = 0
    captured_at: datetime | None = None
    broker_server_time: datetime | None = None
    client_id: int | str = 0
    account_hash: str = ""
    transport_connected: bool = False
    account_verified: bool = False
    open_orders: tuple[BrokerOrderTruth, ...] = ()
    executions: tuple[BrokerExecutionTruth, ...] = ()
    positions: tuple[BrokerPositionTruth, ...] = ()
    cash: float | None = None
    net_liquidation: float | None = None
    buying_power: float | None = None
    margin: float | None = None
    orders_snapshot_complete: bool = False
    executions_snapshot_complete: bool = False
    positions_snapshot_complete: bool = False
    account_snapshot_complete: bool = False
    sequence_watermark: int | None = None
    freshness: str = "unknown"
    expected_connection_epoch: int | None = None
    expected_sequence_watermark: int | None = None
    max_age_seconds: float = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS
    status_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        epoch = _integer(self.connection_epoch, 0) or 0
        raw_client_id = self.client_id
        if isinstance(raw_client_id, bool):
            client_id: int | str = int(raw_client_id)
        elif isinstance(raw_client_id, int):
            client_id = raw_client_id
        elif isinstance(raw_client_id, str) and raw_client_id.strip().lstrip("-").isdigit():
            client_id = int(raw_client_id.strip())
        else:
            client_id = _normalise_client_id(raw_client_id)
        captured_at = _datetime(self.captured_at)
        broker_server_time = _datetime(self.broker_server_time)
        account_hash = _text(self.account_hash).lower()
        object.__setattr__(self, "connection_epoch", epoch)
        object.__setattr__(self, "client_id", client_id)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "broker_server_time", broker_server_time)
        object.__setattr__(self, "account_hash", account_hash)
        object.__setattr__(self, "cash", _number(self.cash))
        object.__setattr__(self, "net_liquidation", _number(self.net_liquidation))
        object.__setattr__(self, "buying_power", _number(self.buying_power))
        object.__setattr__(self, "margin", _number(self.margin))
        object.__setattr__(self, "sequence_watermark", _integer(self.sequence_watermark))
        object.__setattr__(self, "expected_connection_epoch", _integer(self.expected_connection_epoch))
        object.__setattr__(self, "expected_sequence_watermark", _integer(self.expected_sequence_watermark))
        object.__setattr__(self, "max_age_seconds", max(_number(self.max_age_seconds, DEFAULT_MAX_SNAPSHOT_AGE_SECONDS) or 0.0, 0.0))

        orders = tuple(
            _coerce_order_truth(item, client_id=client_id, connection_epoch=epoch)
            for item in _rows(
                self.open_orders,
                mapping_keys=("order", "orderId", "order_id", "symbol", "client_order_id"),
            )
        )
        executions = tuple(
            _coerce_execution_truth(item, client_id=client_id, connection_epoch=epoch)
            for item in _rows(
                self.executions,
                mapping_keys=("execution", "execId", "exec_id", "execution_id", "symbol"),
            )
        )
        positions = tuple(
            _coerce_position_truth(item, connection_epoch=epoch)
            for item in _rows(
                self.positions,
                mapping_keys=("contract", "symbol", "position", "quantity"),
            )
        )
        object.__setattr__(self, "open_orders", orders)
        object.__setattr__(self, "executions", executions)
        object.__setattr__(self, "positions", positions)

        freshness = _text(self.freshness, "unknown").lower().replace("_", "-")
        if freshness in {"fresh", "ok", "current"}:
            freshness = "fresh"
        elif freshness in {"stale", "expired", "old"}:
            freshness = "stale"
        else:
            freshness = "unknown"
        if captured_at is not None:
            age = (datetime.now(timezone.utc) - captured_at).total_seconds()
            if age < 0 or age > self.max_age_seconds:
                freshness = "stale"
        object.__setattr__(self, "freshness", freshness)

        flags = {_text(flag) for flag in (self.status_flags or ())}
        if _identity_duplicates(orders) or _identity_duplicates(executions) or _identity_duplicates(positions):
            flags.add(BrokerTruthStatus.DUPLICATE.value)
        if _sequence_gap(
            tuple(orders) + tuple(executions) + tuple(positions),
            self.expected_sequence_watermark,
            self.sequence_watermark,
        ):
            flags.add(BrokerTruthStatus.SEQUENCE_GAP.value)
        if self.expected_connection_epoch is not None and self.expected_connection_epoch != epoch:
            flags.add(BrokerTruthStatus.EPOCH_MISMATCH.value)
        if any(
            record.connection_epoch is not None and record.connection_epoch != epoch
            for record in (*orders, *executions, *positions)
        ):
            flags.add(BrokerTruthStatus.EPOCH_MISMATCH.value)
        object.__setattr__(self, "status_flags", tuple(sorted(flags)))

        if not self.snapshot_id:
            fingerprint = {
                "connection_epoch": epoch,
                "broker_server_time": _iso(broker_server_time),
                "client_id": client_id,
                "account_hash": account_hash,
                "transport_connected": bool(self.transport_connected),
                "account_verified": bool(self.account_verified),
                "open_orders": [item.to_dict() for item in orders],
                "executions": [item.to_dict() for item in executions],
                "positions": [item.to_dict() for item in positions],
                "cash": self.cash,
                "net_liquidation": self.net_liquidation,
                "buying_power": self.buying_power,
                "margin": self.margin,
                "sequence_watermark": self.sequence_watermark,
            }
            canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), default=str)
            object.__setattr__(self, "snapshot_id", "ibkr-truth-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24])
        else:
            object.__setattr__(self, "snapshot_id", _text(self.snapshot_id))

    @property
    def semantic_statuses(self) -> frozenset[str]:
        statuses = set(self.status_flags)
        if not self.transport_connected or not self.account_verified:
            statuses.add(BrokerTruthStatus.INCOMPLETE.value)
        if not (
            self.orders_snapshot_complete
            and self.executions_snapshot_complete
            and self.positions_snapshot_complete
            and self.account_snapshot_complete
        ):
            statuses.add(BrokerTruthStatus.INCOMPLETE.value)
        if self.cash is None or self.net_liquidation is None or self.buying_power is None:
            statuses.add(BrokerTruthStatus.INCOMPLETE.value)
        if not self.account_hash or not _HEX_HASH_RE.fullmatch(self.account_hash):
            statuses.add(BrokerTruthStatus.INCOMPLETE.value)
        if self.freshness == "stale":
            statuses.add(BrokerTruthStatus.STALE.value)
        if not statuses:
            statuses.add(BrokerTruthStatus.COMPLETE.value)
        return frozenset(statuses)

    @property
    def statuses(self) -> frozenset[str]:
        return self.semantic_statuses

    @property
    def consistency_statuses(self) -> frozenset[str]:
        return self.semantic_statuses

    @property
    def status(self) -> str:
        statuses = self.semantic_statuses
        for candidate in (
            BrokerTruthStatus.EPOCH_MISMATCH.value,
            BrokerTruthStatus.SEQUENCE_GAP.value,
            BrokerTruthStatus.DUPLICATE.value,
            BrokerTruthStatus.STALE.value,
            BrokerTruthStatus.INCOMPLETE.value,
            BrokerTruthStatus.COMPLETE.value,
        ):
            if candidate in statuses:
                return candidate
        return BrokerTruthStatus.INCOMPLETE.value

    @property
    def complete(self) -> bool:
        return self.semantic_statuses == frozenset({BrokerTruthStatus.COMPLETE.value})

    @property
    def incomplete(self) -> bool:
        return not self.complete

    @property
    def is_complete(self) -> bool:
        return self.complete

    @property
    def is_incomplete(self) -> bool:
        return self.incomplete

    @property
    def stale(self) -> bool:
        return BrokerTruthStatus.STALE.value in self.semantic_statuses

    @property
    def is_stale(self) -> bool:
        return self.stale

    @property
    def sequence_gap(self) -> bool:
        return BrokerTruthStatus.SEQUENCE_GAP.value in self.semantic_statuses

    @property
    def duplicate(self) -> bool:
        return BrokerTruthStatus.DUPLICATE.value in self.semantic_statuses

    @property
    def epoch_mismatch(self) -> bool:
        return BrokerTruthStatus.EPOCH_MISMATCH.value in self.semantic_statuses

    @property
    def orders(self) -> tuple[BrokerOrderTruth, ...]:
        return self.open_orders

    @property
    def fills(self) -> tuple[BrokerExecutionTruth, ...]:
        return self.executions

    @property
    def fresh(self) -> bool:
        return self.freshness == "fresh" and not self.stale

    @property
    def block_new_orders(self) -> bool:
        return not self.complete

    @property
    def fail_closed(self) -> bool:
        return self.block_new_orders

    def to_dict(self) -> dict[str, Any]:
        """Return the public form; raw account identifiers cannot appear."""

        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "connection_epoch": self.connection_epoch,
            "captured_at": _iso(self.captured_at),
            "broker_server_time": _iso(self.broker_server_time),
            "client_id": self.client_id,
            "account_hash": self.account_hash,
            "transport_connected": bool(self.transport_connected),
            "account_verified": bool(self.account_verified),
            "open_orders": [item.to_dict() for item in self.open_orders],
            "executions": [item.to_dict() for item in self.executions],
            "positions": [item.to_dict() for item in self.positions],
            "cash": self.cash,
            "net_liquidation": self.net_liquidation,
            "buying_power": self.buying_power,
            "margin": self.margin,
            "orders_snapshot_complete": bool(self.orders_snapshot_complete),
            "executions_snapshot_complete": bool(self.executions_snapshot_complete),
            "positions_snapshot_complete": bool(self.positions_snapshot_complete),
            "account_snapshot_complete": bool(self.account_snapshot_complete),
            "sequence_watermark": self.sequence_watermark,
            "freshness": self.freshness,
            "statuses": sorted(self.semantic_statuses),
            "status": self.status,
            "complete": self.complete,
            "block_new_orders": self.block_new_orders,
            "fail_closed": self.fail_closed,
        }

    as_dict = to_dict
    public_dict = to_dict
    to_public_dict = to_dict


def build_broker_truth_snapshot(**kwargs: Any) -> BrokerTruthSnapshot:
    """Named builder kept intentionally thin for injected fake clients."""

    if "executions" not in kwargs and "fills" in kwargs:
        kwargs["executions"] = kwargs.pop("fills")
    if "open_orders" not in kwargs and "orders" in kwargs:
        kwargs["open_orders"] = kwargs.pop("orders")
    return BrokerTruthSnapshot(**kwargs)


def evaluate_broker_truth_snapshot(
    snapshot: BrokerTruthSnapshot,
    *,
    expected_connection_epoch: int | None = None,
    expected_sequence_watermark: int | None = None,
    now: datetime | None = None,
    max_age_seconds: float | None = None,
) -> BrokerTruthSnapshot:
    """Re-evaluate freshness/epoch/sequence semantics without mutating input."""

    if not isinstance(snapshot, BrokerTruthSnapshot):
        snapshot = BrokerTruthSnapshot(**dict(snapshot))
    reference_now = _datetime(now) or datetime.now(timezone.utc)
    freshness = snapshot.freshness
    if snapshot.captured_at is None:
        freshness = "unknown"
    elif (reference_now - snapshot.captured_at).total_seconds() > (
        snapshot.max_age_seconds if max_age_seconds is None else max_age_seconds
    ):
        freshness = "stale"
    return BrokerTruthSnapshot(
        snapshot_id=snapshot.snapshot_id,
        connection_epoch=snapshot.connection_epoch,
        captured_at=snapshot.captured_at,
        broker_server_time=snapshot.broker_server_time,
        client_id=snapshot.client_id,
        account_hash=snapshot.account_hash,
        transport_connected=snapshot.transport_connected,
        account_verified=snapshot.account_verified,
        open_orders=snapshot.open_orders,
        executions=snapshot.executions,
        positions=snapshot.positions,
        cash=snapshot.cash,
        net_liquidation=snapshot.net_liquidation,
        buying_power=snapshot.buying_power,
        margin=snapshot.margin,
        orders_snapshot_complete=snapshot.orders_snapshot_complete,
        executions_snapshot_complete=snapshot.executions_snapshot_complete,
        positions_snapshot_complete=snapshot.positions_snapshot_complete,
        account_snapshot_complete=snapshot.account_snapshot_complete,
        sequence_watermark=snapshot.sequence_watermark,
        freshness=freshness,
        expected_connection_epoch=expected_connection_epoch
        if expected_connection_epoch is not None
        else snapshot.expected_connection_epoch,
        expected_sequence_watermark=expected_sequence_watermark
        if expected_sequence_watermark is not None
        else snapshot.expected_sequence_watermark,
        max_age_seconds=snapshot.max_age_seconds if max_age_seconds is None else max_age_seconds,
        status_flags=snapshot.status_flags,
    )


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_MAX_SNAPSHOT_AGE_SECONDS",
    "BrokerTruthStatus",
    "BrokerTruthFreshness",
    "SnapshotStatus",
    "BrokerSnapshotStatus",
    "FreshnessStatus",
    "BrokerOrderIdentity",
    "BrokerExecutionIdentity",
    "BrokerOrderTruth",
    "BrokerExecutionTruth",
    "BrokerPositionTruth",
    "BrokerOrderSnapshot",
    "BrokerExecutionSnapshot",
    "BrokerPositionSnapshot",
    "BrokerTruthSnapshot",
    "account_id_hash",
    "map_broker_order_identity",
    "map_broker_execution_identity",
    "build_broker_truth_snapshot",
    "evaluate_broker_truth_snapshot",
]
