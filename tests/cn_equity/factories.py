from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from quant_cn.data.contracts import PITSecurityRecord
from quant_cn.market.calendar import InjectedCalendar, SessionPhase, TradingSession
from quant_cn.market.rules import (
    BOARD_LOT,
    FEE_SCHEDULE,
    PRICE_LIMIT,
    SELLABILITY,
    BoardLotPolicy,
    EffectiveRule,
    EffectiveRuleBook,
    FeeComponent,
    FeePolicy,
    MarketDimensions,
    PriceLimitPolicy,
    SellabilityPolicy,
)


UTC = timezone.utc
AS_OF = datetime(2025, 1, 2, 3, 0, tzinfo=UTC)
EFFECTIVE_FROM = datetime(2025, 1, 1, tzinfo=UTC)
EFFECTIVE_TO = datetime(2026, 1, 1, tzinfo=UTC)


def make_record(**overrides: Any) -> PITSecurityRecord:
    values: dict[str, Any] = {
        "stable_security_id": "CN.SECURITY.000001",
        "venue": "XSHG",
        "instrument": "cash_equity",
        "board": "main",
        "security_type": "common_stock",
        "state": "listed",
        "event_time": AS_OF - timedelta(minutes=5),
        "available_time": AS_OF - timedelta(minutes=4),
        "ingested_at": AS_OF - timedelta(minutes=3),
        "processed_at": AS_OF - timedelta(minutes=2),
        "source": "fixture",
        "version": "pit-fixture-v1",
        "checksum": "a" * 64,
    }
    values.update(overrides)
    return PITSecurityRecord(**values)


def dimensions_for(
    record: PITSecurityRecord,
    *,
    security_id: bool = True,
) -> MarketDimensions:
    return MarketDimensions(
        venue=record.venue,
        board=record.board,
        instrument=record.instrument,
        security_type=record.security_type,
        security_id=record.stable_security_id if security_id else None,
    )


def make_session(
    dimensions: MarketDimensions,
    *,
    session_id: str = "session-fixture-1",
    version: str = "calendar-fixture-v1",
    starts_at: datetime = AS_OF - timedelta(hours=2),
    ends_at: datetime = AS_OF + timedelta(hours=2),
    is_open: bool = True,
    phases: tuple[SessionPhase, ...] | None = None,
    available_time: datetime = AS_OF - timedelta(days=1),
    ingested_at: datetime = AS_OF - timedelta(hours=12),
    processed_at: datetime = AS_OF - timedelta(hours=11),
    checksum: str = "b" * 64,
) -> TradingSession:
    if phases is None:
        phases = (
            SessionPhase(
                "continuous",
                starts_at,
                ends_at,
                True,
            ),
        )
    return TradingSession(
        session_id=session_id,
        calendar_version=version,
        venue=dimensions.venue,
        board=dimensions.board,
        instrument=dimensions.instrument,
        security_type=dimensions.security_type,
        available_time=available_time,
        ingested_at=ingested_at,
        processed_at=processed_at,
        source="fixture",
        checksum=checksum,
        starts_at=starts_at,
        ends_at=ends_at,
        is_open=is_open,
        phases=phases,
    )


def make_calendar(dimensions: MarketDimensions) -> InjectedCalendar:
    return InjectedCalendar((make_session(dimensions),))


def default_payload(rule_kind: str):
    if rule_kind == PRICE_LIMIT:
        return PriceLimitPolicy(True, Decimal("0.10"), Decimal("0.10"))
    if rule_kind == BOARD_LOT:
        return BoardLotPolicy(100, 100, True)
    if rule_kind == SELLABILITY:
        return SellabilityPolicy(1)
    if rule_kind == FEE_SCHEDULE:
        commission = FeeComponent(
            "commission",
            Decimal("0.0003"),
            Decimal("5"),
            Decimal("0"),
        )
        return FeePolicy(buy=(commission,), sell=(commission,))
    raise AssertionError(f"unknown_fixture_rule:{rule_kind}")


def make_rule(
    rule_kind: str,
    dimensions: MarketDimensions,
    *,
    version: str | None = None,
    effective_from: datetime = EFFECTIVE_FROM,
    effective_to: datetime | None = EFFECTIVE_TO,
    available_time: datetime = AS_OF - timedelta(days=2),
    ingested_at: datetime = AS_OF - timedelta(days=1, hours=2),
    processed_at: datetime = AS_OF - timedelta(days=1),
    checksum: str = "c" * 64,
    payload=None,
) -> EffectiveRule:
    return EffectiveRule(
        rule_kind=rule_kind,
        rule_version=version or f"{rule_kind}-fixture-v1",
        effective_from=effective_from,
        effective_to=effective_to,
        available_time=available_time,
        ingested_at=ingested_at,
        processed_at=processed_at,
        dimensions=dimensions,
        payload=payload if payload is not None else default_payload(rule_kind),
        source="fixture",
        checksum=checksum,
    )


def make_rulebook(dimensions: MarketDimensions) -> EffectiveRuleBook:
    return EffectiveRuleBook(
        make_rule(kind, dimensions)
        for kind in (PRICE_LIMIT, BOARD_LOT, SELLABILITY, FEE_SCHEDULE)
    )
