from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Generic, Iterable, Iterator, TypeVar

from quant_us.core.clock import ensure_utc
from quant_us.core.enums import EventType
from quant_us.core.types import AccountState, Bar, Fill, Order, OrderIntent, RiskDecision, Signal, TargetPosition, new_id


@dataclass(frozen=True)
class BaseEvent:
    event_type: EventType
    timestamp_utc: datetime
    event_id: str = field(default_factory=lambda: new_id("evt"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))


@dataclass(frozen=True)
class MarketEvent(BaseEvent):
    bar: Bar = field(default=None)

    @classmethod
    def from_bar(cls, bar: Bar) -> "MarketEvent":
        return cls(event_type=EventType.MARKET, timestamp_utc=bar.timestamp_utc, bar=bar)


@dataclass(frozen=True)
class SignalEvent(BaseEvent):
    signal: Signal = field(default=None)

    @classmethod
    def from_signal(cls, signal: Signal) -> "SignalEvent":
        return cls(event_type=EventType.SIGNAL, timestamp_utc=signal.timestamp_utc, signal=signal)


@dataclass(frozen=True)
class TargetPositionEvent(BaseEvent):
    target: TargetPosition = field(default=None)

    @classmethod
    def from_target(cls, target: TargetPosition) -> "TargetPositionEvent":
        return cls(event_type=EventType.TARGET_POSITION, timestamp_utc=target.timestamp_utc, target=target)


@dataclass(frozen=True)
class OrderIntentEvent(BaseEvent):
    intent: OrderIntent = field(default=None)

    @classmethod
    def from_intent(cls, intent: OrderIntent) -> "OrderIntentEvent":
        return cls(event_type=EventType.ORDER_INTENT, timestamp_utc=intent.timestamp_utc, intent=intent)


@dataclass(frozen=True)
class RiskEvent(BaseEvent):
    decision: RiskDecision = field(default=None)

    @classmethod
    def from_decision(cls, decision: RiskDecision) -> "RiskEvent":
        return cls(event_type=EventType.RISK, timestamp_utc=decision.checked_at, decision=decision)


@dataclass(frozen=True)
class BrokerOrderEvent(BaseEvent):
    order: Order = field(default=None)

    @classmethod
    def from_order(cls, order: Order) -> "BrokerOrderEvent":
        return cls(event_type=EventType.BROKER_ORDER, timestamp_utc=order.updated_at, order=order)


@dataclass(frozen=True)
class FillEvent(BaseEvent):
    fill: Fill = field(default=None)

    @classmethod
    def from_fill(cls, fill: Fill) -> "FillEvent":
        return cls(event_type=EventType.FILL, timestamp_utc=fill.filled_at, fill=fill)


@dataclass(frozen=True)
class AccountUpdateEvent(BaseEvent):
    account: AccountState = field(default=None)

    @classmethod
    def from_account(cls, account: AccountState) -> "AccountUpdateEvent":
        return cls(event_type=EventType.ACCOUNT_UPDATE, timestamp_utc=account.timestamp_utc, account=account)


Event = BaseEvent | MarketEvent | SignalEvent | TargetPositionEvent | OrderIntentEvent | RiskEvent | BrokerOrderEvent | FillEvent | AccountUpdateEvent
TEvent = TypeVar("TEvent", bound=Event)


class EventQueue(Generic[TEvent]):
    def __init__(self, events: Iterable[TEvent] | None = None) -> None:
        self._items: Deque[TEvent] = deque(events or [])

    def push(self, event: TEvent) -> None:
        self._items.append(event)

    def pop(self) -> TEvent:
        return self._items.popleft()

    def __bool__(self) -> bool:
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[TEvent]:
        while self:
            yield self.pop()
