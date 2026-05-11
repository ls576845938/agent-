from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from quant_us.core.clock import ensure_utc
from quant_us.core.types import Bar


def normalize_bar_size(value: str) -> str:
    return str(value or "").strip().lower()


def bar_size_to_timedelta(value: str) -> timedelta:
    """Parse the platform's compact bar-size DSL into a duration."""
    raw = normalize_bar_size(value)
    if not raw:
        raise ValueError("bar size is required")
    unit = raw[-1]
    try:
        amount = int(raw[:-1])
    except ValueError as exc:
        raise ValueError(f"Unsupported bar size: {value!r}") from exc
    if amount <= 0:
        raise ValueError(f"Bar size must be positive: {value!r}")
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    raise ValueError(f"Unsupported bar size unit: {value!r}")


def bar_size_rank(value: str) -> int:
    duration = bar_size_to_timedelta(value)
    return int(duration.total_seconds())


@dataclass(frozen=True)
class MultiTimeframeSchedule:
    """Declarative bar-availability contract for multi-timeframe strategies.

    The default semantics are bar-close availability: a bar becomes visible to
    strategies at ``bar.timestamp_utc + availability_delay`` and remains frozen
    until a newer bar for the same ``(bar_size, symbol)`` becomes available.
    Orders produced from that bar are still executed by the engine on a later
    market bar, never at the signal bar's close.
    """

    execution: str = "1m"
    confirm: tuple[str, ...] = ()
    regime: tuple[str, ...] = ()
    availability_delay: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution", normalize_bar_size(self.execution))
        object.__setattr__(self, "confirm", tuple(normalize_bar_size(item) for item in self.confirm if item))
        object.__setattr__(self, "regime", tuple(normalize_bar_size(item) for item in self.regime if item))
        if not self.execution:
            raise ValueError("execution timeframe is required")
        for bar_size in self.all_bar_sizes:
            bar_size_to_timedelta(bar_size)
        if self.availability_delay < timedelta(0):
            raise ValueError("availability_delay must be non-negative")

    @property
    def all_bar_sizes(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for bar_size in (self.execution, *self.confirm, *self.regime):
            if bar_size and bar_size not in seen:
                seen.add(bar_size)
                ordered.append(bar_size)
        return tuple(ordered)

    @property
    def roles_by_bar_size(self) -> dict[str, tuple[str, ...]]:
        roles: dict[str, list[str]] = {}
        roles.setdefault(self.execution, []).append("execution")
        for bar_size in self.confirm:
            roles.setdefault(bar_size, []).append("confirm")
        for bar_size in self.regime:
            roles.setdefault(bar_size, []).append("regime")
        return {bar_size: tuple(values) for bar_size, values in roles.items()}

    @classmethod
    def from_dsl(cls, spec: dict[str, Any]) -> "MultiTimeframeSchedule":
        """Build a schedule from a compact DSL.

        Example::

            MultiTimeframeSchedule.from_dsl({
                "regime": "1d",
                "confirm": ["15m", "5m"],
                "execution": "1m",
            })
        """
        delay_seconds = float(spec.get("availability_delay_seconds", 0.0) or 0.0)
        return cls(
            execution=str(spec.get("execution", "1m")),
            confirm=_as_tuple(spec.get("confirm", ())),
            regime=_as_tuple(spec.get("regime", ())),
            availability_delay=timedelta(seconds=delay_seconds),
        )


@dataclass(frozen=True)
class FrozenTimeframeSnapshot:
    """Point-in-time view of bars that were available to a strategy event."""

    timestamp_utc: datetime
    current_bar_size: str
    current_symbol: str
    bars: dict[str, dict[str, Bar]] = field(default_factory=dict)
    roles_by_bar_size: dict[str, tuple[str, ...]] = field(default_factory=dict)
    available_at_utc: dict[str, dict[str, datetime]] = field(default_factory=dict)

    def bar(self, bar_size: str, symbol: str) -> Bar | None:
        return self.bars.get(normalize_bar_size(bar_size), {}).get(symbol.upper())

    def close(self, bar_size: str, symbol: str) -> float | None:
        bar = self.bar(bar_size, symbol)
        return None if bar is None else float(bar.close)

    @property
    def available_timeframes(self) -> tuple[str, ...]:
        return tuple(sorted(self.bars, key=bar_size_rank))

    @property
    def market_prices_by_timeframe(self) -> dict[str, dict[str, float]]:
        return {
            bar_size: {
                symbol: float(bar.close)
                for symbol, bar in sorted(symbol_bars.items())
            }
            for bar_size, symbol_bars in sorted(self.bars.items(), key=lambda item: bar_size_rank(item[0]))
        }

    def to_metadata(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "current_bar_size": self.current_bar_size,
            "current_symbol": self.current_symbol,
            "available_timeframes": list(self.available_timeframes),
            "roles_by_bar_size": {
                bar_size: list(roles)
                for bar_size, roles in sorted(self.roles_by_bar_size.items())
            },
            "bar_timestamps": {
                bar_size: {
                    symbol: bar.timestamp_utc.isoformat()
                    for symbol, bar in sorted(symbol_bars.items())
                }
                for bar_size, symbol_bars in sorted(self.bars.items(), key=lambda item: bar_size_rank(item[0]))
            },
        }


class MultiTimeframeBarScheduler:
    """Maintain frozen bar availability for deterministic backtests."""

    def __init__(self, schedule: MultiTimeframeSchedule | None = None) -> None:
        self.schedule = schedule
        self._latest: dict[tuple[str, str], Bar] = {}
        self._available_at: dict[tuple[str, str], datetime] = {}

    def update_available(self, bars: Iterable[Bar], timestamp_utc: datetime) -> None:
        now = ensure_utc(timestamp_utc)
        for bar in bars:
            bar_size = normalize_bar_size(bar.bar_size)
            if not bar_size:
                continue
            if self.schedule is not None and bar_size not in self.schedule.all_bar_sizes:
                continue
            available_at = ensure_utc(bar.timestamp_utc) + self._availability_delay()
            if available_at > now:
                continue
            key = (bar_size, bar.symbol.upper())
            current = self._latest.get(key)
            if current is None or bar.timestamp_utc >= current.timestamp_utc:
                self._latest[key] = bar
                self._available_at[key] = available_at

    def snapshot_for(self, bar: Bar, timestamp_utc: datetime) -> FrozenTimeframeSnapshot:
        current_time = ensure_utc(timestamp_utc)
        current_size = normalize_bar_size(bar.bar_size)
        wanted = set(self.schedule.all_bar_sizes) if self.schedule is not None else {
            bar_size for bar_size, _symbol in self._latest
        }
        if current_size:
            wanted.add(current_size)

        bars: dict[str, dict[str, Bar]] = {}
        available_at: dict[str, dict[str, datetime]] = {}
        for (bar_size, symbol), candidate in sorted(self._latest.items()):
            if bar_size not in wanted:
                continue
            candidate_available_at = self._available_at[(bar_size, symbol)]
            if candidate_available_at > current_time:
                continue
            bars.setdefault(bar_size, {})[symbol] = candidate
            available_at.setdefault(bar_size, {})[symbol] = candidate_available_at

        return FrozenTimeframeSnapshot(
            timestamp_utc=current_time,
            current_bar_size=current_size,
            current_symbol=bar.symbol.upper(),
            bars=bars,
            roles_by_bar_size=self.schedule.roles_by_bar_size if self.schedule is not None else {},
            available_at_utc=available_at,
        )

    def _availability_delay(self) -> timedelta:
        if self.schedule is None:
            return timedelta(0)
        return self.schedule.availability_delay


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)
