from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


STRATEGY_DECISION_CONTEXT_SCHEMA_VERSION = "strategy_decision_context_v1"
STRATEGY_STATE_SCHEMA_VERSION = "strategy_state_v1"


class FrozenMapping(Mapping[str, Any]):
    """A recursively frozen, insertion-ordered mapping snapshot."""

    __slots__ = ("_items", "_values")

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        items: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for raw_key, raw_value in (values or {}).items():
            key = str(raw_key)
            if key in seen:
                raise ValueError(f"duplicate key after string normalization: {key!r}")
            seen.add(key)
            items.append((key, deep_freeze(raw_value)))
        self._items = tuple(items)
        self._values = dict(items)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"FrozenMapping({self._values!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return _semantic_equal(self, other)
        return False


def _semantic_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return False
        return all(_semantic_equal(left[key], right[key]) for key in left)
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _semantic_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if isinstance(left, (set, frozenset)) and isinstance(right, (set, frozenset)):
        return left == right
    return bool(left == right)


def deep_freeze(value: Any) -> Any:
    """Copy supported values into an immutable decision-time snapshot."""

    if isinstance(value, FrozenMapping):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(deep_freeze(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        params = getattr(type(value), "__dataclass_params__", None)
        if params is None or not bool(getattr(params, "frozen", False)):
            raise TypeError(
                f"mutable dataclass {type(value).__name__} cannot enter a frozen strategy context"
            )
        updates = {
            item.name: deep_freeze(getattr(value, item.name))
            for item in fields(value)
        }
        return replace(value, **updates)
    if isinstance(
        value,
        (
            str,
            bytes,
            int,
            float,
            bool,
            type(None),
            datetime,
            date,
            time,
            timedelta,
            Decimal,
            Enum,
            Path,
        ),
    ):
        return value
    raise TypeError(
        f"unsupported mutable or opaque strategy-context value: {type(value).__name__}"
    )


def deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((deep_thaw(item) for item in value), key=repr)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _freeze_state_value(value: Any, *, path: str) -> Any:
    """Freeze only values whose meaning survives a JSON restart round trip."""

    if isinstance(value, Mapping):
        return FrozenMapping(
            {
                str(key): _freeze_state_value(item, path=f"{path}.{key}")
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_state_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"strategy state {path} must be finite")
        return value
    raise TypeError(
        f"strategy state {path} must be a JSON-stable scalar, mapping, or sequence; "
        f"got {type(value).__name__}"
    )


def freeze_state_payload(payload: Mapping[str, Any]) -> FrozenMapping:
    if not isinstance(payload, Mapping):
        raise TypeError("strategy state payload must be a mapping")
    frozen = _freeze_state_value(payload, path="payload")
    if not isinstance(frozen, FrozenMapping):  # pragma: no cover - type narrowing
        raise TypeError("strategy state payload must freeze to a mapping")
    return frozen


class StrategyRuntimeMode(str, Enum):
    UNKNOWN = "unknown"
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"
    REPLAY = "replay"
    WARMUP = "warmup"


class StrategyDecisionCapability(str, Enum):
    SIGNAL = "signal"
    FORECAST = "forecast"
    TARGET_POSITION = "target_position"
    ORDER_INTENT = "order_intent"


def _aware_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class StrategyIdentity:
    run_id: str
    strategy_id: str
    strategy_version: str
    code_version: str
    data_version: str

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "strategy_id",
            "strategy_version",
            "code_version",
            "data_version",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)

    @property
    def digest(self) -> str:
        material = "\0".join(
            (
                self.run_id,
                self.strategy_id,
                self.strategy_version,
                self.code_version,
                self.data_version,
            )
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class StrategyClock:
    mode: StrategyRuntimeMode = StrategyRuntimeMode.UNKNOWN
    decision_time: datetime | None = None
    event_time: datetime | None = None
    available_time: datetime | None = None
    is_new_bar: bool = False
    is_final: bool = False

    def __post_init__(self) -> None:
        mode = self.mode
        if not isinstance(mode, StrategyRuntimeMode):
            mode = StrategyRuntimeMode(str(mode).strip().lower())
        object.__setattr__(self, "mode", mode)
        decision = _aware_utc(self.decision_time, "decision_time")
        event = _aware_utc(self.event_time, "event_time")
        available = _aware_utc(self.available_time, "available_time")
        populated = [item is not None for item in (decision, event, available)]
        if any(populated) and not all(populated):
            raise ValueError(
                "decision_time, event_time, and available_time must be supplied together"
            )
        if event is not None and available is not None and event > available:
            raise ValueError("event_time must not be later than available_time")
        if available is not None and decision is not None and available > decision:
            raise ValueError("available_time must not be later than decision_time")
        object.__setattr__(self, "decision_time", decision)
        object.__setattr__(self, "event_time", event)
        object.__setattr__(self, "available_time", available)


@dataclass(frozen=True)
class StrategyPositionView:
    symbol: str
    quantity: float
    avg_price: float
    market_price: float
    unrealized_pnl: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).upper())
        for name in ("quantity", "avg_price", "market_price", "unrealized_pnl"):
            object.__setattr__(self, name, float(getattr(self, name)))

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price


@dataclass(frozen=True)
class StrategyExposureView:
    timestamp_utc: datetime | None
    account_id: str
    cash: float
    equity: float
    buying_power: float
    gross_exposure: float
    net_exposure: float
    positions: FrozenMapping

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp_utc",
            _aware_utc(self.timestamp_utc, "exposure.timestamp_utc"),
        )
        for name in (
            "cash",
            "equity",
            "buying_power",
            "gross_exposure",
            "net_exposure",
        ):
            object.__setattr__(self, name, float(getattr(self, name)))
        object.__setattr__(self, "positions", FrozenMapping(self.positions))

    @classmethod
    def from_account(cls, account: Any | None) -> StrategyExposureView | None:
        if account is None:
            return None
        if isinstance(account, cls):
            return account
        raw_positions = getattr(account, "positions", {}) or {}
        position_views: dict[str, StrategyPositionView] = {}
        gross = 0.0
        net = 0.0
        for raw_symbol, raw_position in raw_positions.items():
            symbol = str(getattr(raw_position, "symbol", raw_symbol)).upper()
            view = StrategyPositionView(
                symbol=symbol,
                quantity=float(getattr(raw_position, "quantity", 0.0)),
                avg_price=float(getattr(raw_position, "avg_price", 0.0)),
                market_price=float(getattr(raw_position, "market_price", 0.0)),
                unrealized_pnl=float(getattr(raw_position, "unrealized_pnl", 0.0)),
            )
            position_views[symbol] = view
            gross += abs(view.market_value)
            net += view.market_value
        return cls(
            timestamp_utc=getattr(account, "timestamp_utc", None),
            account_id=str(getattr(account, "account_id", "")),
            cash=float(getattr(account, "cash", 0.0)),
            equity=float(getattr(account, "equity", 0.0)),
            buying_power=float(getattr(account, "buying_power", 0.0)),
            gross_exposure=gross,
            net_exposure=net,
            positions=FrozenMapping(position_views),
        )


@dataclass(frozen=True)
class StrategyStateKey:
    run_id: str
    strategy_id: str
    identity_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("run_id", "strategy_id"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"state {name} is required")
            object.__setattr__(self, name, value)
        digest = str(self.identity_digest or "").strip()
        if digest and (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ValueError("state identity_digest must be a lowercase sha256")
        object.__setattr__(self, "identity_digest", digest)


def _state_digest(
    *,
    key: StrategyStateKey,
    schema_version: str,
    revision: int,
    payload: Mapping[str, Any],
    last_decision_id: str,
) -> str:
    document = {
        "run_id": key.run_id,
        "strategy_id": key.strategy_id,
        "identity_digest": key.identity_digest,
        "schema_version": schema_version,
        "revision": revision,
        "payload": deep_thaw(payload),
        "last_decision_id": last_decision_id,
    }
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class StrategyStateSnapshot:
    key: StrategyStateKey
    schema_version: str = STRATEGY_STATE_SCHEMA_VERSION
    revision: int = 0
    payload: FrozenMapping = field(default_factory=FrozenMapping)
    last_decision_id: str = ""
    digest: str = ""

    def __post_init__(self) -> None:
        schema_version = str(self.schema_version or "").strip()
        if not schema_version:
            raise ValueError("state schema_version is required")
        revision = int(self.revision)
        if revision < 0:
            raise ValueError("state revision must be non-negative")
        payload = freeze_state_payload(self.payload)
        last_decision_id = str(self.last_decision_id or "").strip()
        if last_decision_id and (
            len(last_decision_id) != 64
            or any(ch not in "0123456789abcdef" for ch in last_decision_id)
        ):
            raise ValueError("last_decision_id must be a lowercase sha256")
        computed = _state_digest(
            key=self.key,
            schema_version=schema_version,
            revision=revision,
            payload=payload,
            last_decision_id=last_decision_id,
        )
        supplied = str(self.digest or "").strip()
        if supplied and supplied != computed:
            raise ValueError("strategy state digest mismatch")
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "last_decision_id", last_decision_id)
        object.__setattr__(self, "digest", computed)

    @classmethod
    def empty(
        cls,
        key: StrategyStateKey,
        *,
        schema_version: str = STRATEGY_STATE_SCHEMA_VERSION,
    ) -> StrategyStateSnapshot:
        return cls(key=key, schema_version=schema_version)

    def transition(
        self,
        payload: Mapping[str, Any],
        *,
        reason: str,
    ) -> StrategyStateTransition:
        return StrategyStateTransition(
            key=self.key,
            schema_version=self.schema_version,
            expected_revision=self.revision,
            next_revision=self.revision + 1,
            payload=FrozenMapping(payload),
            reason=reason,
            previous_digest=self.digest,
        )


@dataclass(frozen=True)
class StrategyStateTransition:
    key: StrategyStateKey
    schema_version: str
    expected_revision: int
    next_revision: int
    payload: FrozenMapping
    reason: str
    previous_digest: str
    decision_id: str = ""
    transition_id: str = ""

    def __post_init__(self) -> None:
        schema_version = str(self.schema_version or "").strip()
        reason = str(self.reason or "").strip()
        previous_digest = str(self.previous_digest or "").strip()
        decision_id = str(self.decision_id or "").strip()
        expected = int(self.expected_revision)
        next_revision = int(self.next_revision)
        if not schema_version:
            raise ValueError("transition schema_version is required")
        if not reason:
            raise ValueError("transition reason is required")
        if not previous_digest:
            raise ValueError("transition previous_digest is required")
        if decision_id and (
            len(decision_id) != 64
            or any(ch not in "0123456789abcdef" for ch in decision_id)
        ):
            raise ValueError("transition decision_id must be a lowercase sha256")
        if expected < 0 or next_revision != expected + 1:
            raise ValueError("transition next_revision must equal expected_revision + 1")
        payload = freeze_state_payload(self.payload)
        next_digest = _state_digest(
            key=self.key,
            schema_version=schema_version,
            revision=next_revision,
            payload=payload,
            last_decision_id=decision_id,
        )
        material = (
            f"{self.key.run_id}\0{self.key.strategy_id}\0{schema_version}\0"
            f"{expected}\0{next_revision}\0{previous_digest}\0{next_digest}\0"
            f"{decision_id}\0{reason}"
        ).encode("utf-8")
        computed_id = hashlib.sha256(material).hexdigest()
        supplied_id = str(self.transition_id or "").strip()
        if supplied_id and supplied_id != computed_id:
            raise ValueError("strategy transition id mismatch")
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "expected_revision", expected)
        object.__setattr__(self, "next_revision", next_revision)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "decision_id", decision_id)
        object.__setattr__(self, "transition_id", computed_id)

    def to_snapshot(self) -> StrategyStateSnapshot:
        return StrategyStateSnapshot(
            key=self.key,
            schema_version=self.schema_version,
            revision=self.next_revision,
            payload=self.payload,
            last_decision_id=self.decision_id,
        )


@dataclass(frozen=True, init=False)
class StrategyDecisionContext:
    schema_version: str
    identity: StrategyIdentity
    clock: StrategyClock
    market: FrozenMapping
    features: FrozenMapping
    universe: tuple[str, ...]
    exposure: StrategyExposureView | None
    state: StrategyStateSnapshot
    capabilities: frozenset[StrategyDecisionCapability]
    parameters: FrozenMapping

    def __init__(
        self,
        *,
        identity: StrategyIdentity | None = None,
        clock: StrategyClock | None = None,
        market: Mapping[str, Any] | None = None,
        features: Mapping[str, Any] | None = None,
        universe: list[str] | tuple[str, ...] = (),
        exposure: StrategyExposureView | None = None,
        state: StrategyStateSnapshot | None = None,
        capabilities: tuple[StrategyDecisionCapability, ...]
        | frozenset[StrategyDecisionCapability]
        | None = None,
        parameters: Mapping[str, Any] | None = None,
        run_id: str = "",
        account: Any | None = None,
        market_prices: Mapping[str, Any] | None = None,
    ) -> None:
        raw_parameters = dict(parameters or {})
        resolved_clock = clock or StrategyClock(
            mode=StrategyRuntimeMode(
                str(raw_parameters.get("runtime_mode", "unknown")).strip().lower()
            )
        )
        if identity is None:
            identity = StrategyIdentity(
                run_id=str(run_id or "legacy_run"),
                strategy_id=str(raw_parameters.get("strategy_id") or "unbound_strategy"),
                strategy_version=str(
                    raw_parameters.get("strategy_version") or "unbound_strategy_version"
                ),
                code_version=str(raw_parameters.get("code_version") or "unbound_code"),
                data_version=str(raw_parameters.get("data_version") or "unbound_data"),
            )
        raw_parameters["runtime_mode"] = resolved_clock.mode.value
        resolved_market = market if market is not None else market_prices
        resolved_exposure = exposure or StrategyExposureView.from_account(account)
        resolved_state = state or StrategyStateSnapshot.empty(
            StrategyStateKey(
                run_id=identity.run_id,
                strategy_id=identity.strategy_id,
                identity_digest=identity.digest,
            )
        )
        if resolved_state.key != StrategyStateKey(
            run_id=identity.run_id,
            strategy_id=identity.strategy_id,
            identity_digest=identity.digest,
        ):
            raise ValueError("context identity and state key must match")
        resolved_capabilities = frozenset(
            capabilities or (StrategyDecisionCapability.SIGNAL,)
        )
        if not resolved_capabilities:
            raise ValueError("at least one strategy decision capability is required")
        for capability in resolved_capabilities:
            if not isinstance(capability, StrategyDecisionCapability):
                raise TypeError("capabilities must contain StrategyDecisionCapability values")
        object.__setattr__(
            self,
            "schema_version",
            STRATEGY_DECISION_CONTEXT_SCHEMA_VERSION,
        )
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "clock", resolved_clock)
        object.__setattr__(self, "market", FrozenMapping(resolved_market or {}))
        object.__setattr__(self, "features", FrozenMapping(features or {}))
        object.__setattr__(
            self,
            "universe",
            tuple(str(symbol).upper() for symbol in universe),
        )
        object.__setattr__(self, "exposure", resolved_exposure)
        object.__setattr__(self, "state", resolved_state)
        object.__setattr__(self, "capabilities", resolved_capabilities)
        object.__setattr__(self, "parameters", FrozenMapping(raw_parameters))

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    @property
    def account(self) -> StrategyExposureView | None:
        return self.exposure

    @property
    def market_prices(self) -> FrozenMapping:
        return self.market

    def for_strategy(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        state: StrategyStateSnapshot,
        parameter_overrides: Mapping[str, Any] | None = None,
    ) -> StrategyDecisionContext:
        parameters = dict(self.parameters)
        parameters.update(parameter_overrides or {})
        parameters["strategy_id"] = strategy_id
        parameters["strategy_version"] = strategy_version
        return StrategyDecisionContext(
            identity=replace(
                self.identity,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
            ),
            clock=self.clock,
            market=self.market,
            features=self.features,
            universe=self.universe,
            exposure=self.exposure,
            state=state,
            capabilities=self.capabilities,
            parameters=parameters,
        )
