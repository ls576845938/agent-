from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from quant_cn.market.calendar import (
    CALENDAR_OPEN,
    InjectedCalendar,
    SessionPhase,
    TradingSession,
)
from quant_cn.market.price_state import (
    BUY_BLOCKED_AT_UPPER_LOCK,
    PRICE_ABOVE_LIMIT,
    PRICE_LIMIT_POLICY_MISMATCH,
    PRICE_SNAPSHOT_NOT_AVAILABLE,
    PRICE_TICK_MISALIGNED,
    PITPriceBandSnapshot,
)
from quant_cn.market.rules import (
    ORDER_CONSTRAINTS,
    PRICE_LIMIT,
    RULE_MISSING,
    RULE_NOT_AVAILABLE,
    RULE_RESOLVED,
    AllowedOrderInstruction,
    BoardLotPolicy,
    EffectiveRule,
    EffectiveRuleBook,
    FeeComponent,
    FeePolicy,
    MarketDimensions,
    OrderConstraintPolicy,
    PhaseOrderConstraint,
    PriceLimitPolicy,
    SellabilityPolicy,
    SettlementPolicy,
    TickSizePolicy,
)
from quant_cn.market.settlement import (
    INVENTORY_POLICY_MISMATCH,
    INVENTORY_RESOLVED,
    SettlementInventory,
    SettlementInventoryLot,
    SettlementInventorySnapshot,
)
from quant_cn.market.status import (
    SECURITY_BUY_NOT_ALLOWED,
    SECURITY_SUSPENDED,
    STATUS_NOT_AVAILABLE,
    STATUS_RESOLVED,
    STATUS_RISK_WARNING,
    STATUS_SUSPENDED,
    EffectiveSecurityStatus,
    SecurityStatusBook,
)


UTC = timezone.utc
T0 = datetime(2025, 1, 2, tzinfo=UTC)
SHA = "a" * 64


def _dimensions(board: str = "main") -> MarketDimensions:
    return MarketDimensions(
        venue="XSHG",
        board=board,
        instrument="cash_equity",
        security_type="common_stock",
        security_id="CN.SECURITY.600000",
    )


def _rule(
    kind: str,
    payload,
    *,
    version: str,
    start: datetime,
    end: datetime | None,
    available: datetime,
    dimensions: MarketDimensions | None = None,
) -> EffectiveRule:
    return EffectiveRule(
        rule_kind=kind,
        rule_version=version,
        effective_from=start,
        effective_to=end,
        available_time=available,
        ingested_at=available + timedelta(minutes=1),
        processed_at=available + timedelta(minutes=2),
        dimensions=dimensions or _dimensions(),
        payload=payload,
        source="exchange-rulebook",
        checksum=SHA,
    )


def test_rules_cross_effective_date_and_unknown_board_fail_closed() -> None:
    old = _rule(
        PRICE_LIMIT,
        PriceLimitPolicy(
            True,
            Decimal("0.10"),
            Decimal("0.10"),
            "floor",
            "ceiling",
        ),
        version="rule-2024",
        start=T0 - timedelta(days=365),
        end=T0,
        available=T0 - timedelta(days=400),
    )
    new = _rule(
        PRICE_LIMIT,
        PriceLimitPolicy(
            True,
            Decimal("0.20"),
            Decimal("0.20"),
            "floor",
            "ceiling",
        ),
        version="rule-2025",
        start=T0,
        end=None,
        available=T0 - timedelta(days=1),
    )
    book = EffectiveRuleBook((old, new))
    before = book.resolve(
        PRICE_LIMIT,
        dimensions=_dimensions(),
        as_of=T0 - timedelta(microseconds=1),
    )
    after = book.resolve(PRICE_LIMIT, dimensions=_dimensions(), as_of=T0)
    assert before.status == after.status == RULE_RESOLVED
    assert before.versions == ("rule-2024",)
    assert after.versions == ("rule-2025",)
    assert book.resolve(
        PRICE_LIMIT,
        dimensions=_dimensions("unknown-board"),
        as_of=T0,
    ).status == RULE_MISSING


def test_invisible_rule_does_not_leak_future_version() -> None:
    rule = _rule(
        ORDER_CONSTRAINTS,
        OrderConstraintPolicy(
            (
                PhaseOrderConstraint(
                    "opening_auction",
                    (AllowedOrderInstruction("limit", "day", "required"),),
                ),
            )
        ),
        version="future-order-rule",
        start=T0,
        end=None,
        available=T0 + timedelta(minutes=5),
    )
    resolution = EffectiveRuleBook((rule,)).resolve(
        ORDER_CONSTRAINTS,
        dimensions=_dimensions(),
        as_of=T0,
    )
    assert resolution.status == RULE_NOT_AVAILABLE
    assert resolution.versions == ()


def test_auction_phase_and_order_constraints_are_injected_and_explicit() -> None:
    phase = SessionPhase(
        "opening_auction",
        T0,
        T0 + timedelta(minutes=15),
        True,
    )
    session = TradingSession(
        session_id="2025-01-02",
        calendar_version="calendar-2025-01",
        venue="XSHG",
        board="main",
        instrument="cash_equity",
        security_type="common_stock",
        available_time=T0 - timedelta(days=1),
        ingested_at=T0 - timedelta(hours=23),
        processed_at=T0 - timedelta(hours=22),
        source="exchange-calendar",
        checksum=SHA,
        starts_at=T0,
        ends_at=T0 + timedelta(hours=6),
        is_open=True,
        phases=(phase,),
    )
    calendar = InjectedCalendar((session,))
    result = calendar.resolve(
        as_of=T0 + timedelta(minutes=5),
        venue="XSHG",
        board="main",
        instrument="cash_equity",
        security_type="common_stock",
    )
    assert result.status == CALENDAR_OPEN
    assert result.phase_name == "opening_auction"

    policy = OrderConstraintPolicy(
        (
            PhaseOrderConstraint(
                "opening_auction",
                (AllowedOrderInstruction("limit", "day", "required"),),
            ),
        )
    )
    assert policy.for_phase("opening_auction").resolve(
        order_type="limit",
        time_in_force="day",
    ).price_requirement == "required"
    assert policy.for_phase("opening_auction").resolve(
        order_type="market",
        time_in_force="day",
    ) is None
    assert policy.for_phase("unknown") is None


def test_suspension_and_risk_warning_are_effective_dated() -> None:
    suspended = EffectiveSecurityStatus(
        stable_security_id="CN.SECURITY.600000",
        status=STATUS_SUSPENDED,
        buy_allowed=False,
        sell_allowed=False,
        event_time=T0,
        effective_from=T0,
        effective_to=T0 + timedelta(days=1),
        available_time=T0,
        ingested_at=T0 + timedelta(minutes=1),
        processed_at=T0 + timedelta(minutes=2),
        source="exchange-status",
        version="suspension-v1",
        checksum=SHA,
    )
    risk = EffectiveSecurityStatus(
        stable_security_id="CN.SECURITY.600000",
        status=STATUS_RISK_WARNING,
        buy_allowed=False,
        sell_allowed=True,
        event_time=T0 + timedelta(days=1),
        effective_from=T0 + timedelta(days=1),
        effective_to=None,
        available_time=T0 + timedelta(days=1),
        ingested_at=T0 + timedelta(days=1, minutes=1),
        processed_at=T0 + timedelta(days=1, minutes=2),
        source="exchange-status",
        version="risk-v1",
        checksum=SHA,
    )
    book = SecurityStatusBook((suspended, risk))
    first = book.resolve(
        stable_security_id="CN.SECURITY.600000",
        as_of=T0 + timedelta(hours=1),
    )
    assert first.status == STATUS_RESOLVED
    assert set(first.record.blockers_for("buy")) == {
        SECURITY_BUY_NOT_ALLOWED,
        SECURITY_SUSPENDED,
    }
    second = book.resolve(
        stable_security_id="CN.SECURITY.600000",
        as_of=T0 + timedelta(days=1, hours=1),
    )
    assert second.record.status == STATUS_RISK_WARNING
    assert second.record.blockers_for("buy") == (SECURITY_BUY_NOT_ALLOWED,)
    assert book.resolve(
        stable_security_id="CN.SECURITY.600000",
        as_of=T0 - timedelta(seconds=1),
    ).status == STATUS_NOT_AVAILABLE


def _price_snapshot(*, available_time: datetime, upper_locked: bool = False):
    return PITPriceBandSnapshot(
        stable_security_id="CN.SECURITY.600000",
        session_id="2025-01-02",
        calendar_version="calendar-v1",
        reference_price=Decimal("10.00"),
        last_price=Decimal("11.00") if upper_locked else Decimal("10.00"),
        lower_limit_price=Decimal("9.00"),
        upper_limit_price=Decimal("11.00"),
        lower_locked=False,
        upper_locked=upper_locked,
        price_limit_rule_version="limit-v1",
        tick_size_rule_version="tick-v1",
        valid_from=T0,
        valid_to=T0 + timedelta(days=1),
        event_time=T0,
        available_time=available_time,
        ingested_at=available_time + timedelta(minutes=1),
        processed_at=available_time + timedelta(minutes=2),
        source="exchange-market-data",
        version="band-v1",
        checksum=SHA,
    )


def test_price_band_tick_limits_locks_and_rule_versions_fail_closed() -> None:
    policy = PriceLimitPolicy(
        True,
        Decimal("0.10"),
        Decimal("0.10"),
        "floor",
        "ceiling",
    )
    tick = TickSizePolicy(Decimal("0.01"))
    snapshot = _price_snapshot(available_time=T0, upper_locked=True)
    blockers = snapshot.validate_price(
        side="buy",
        price=Decimal("11.001"),
        as_of=T0 + timedelta(minutes=1),
        stable_security_id="CN.SECURITY.600000",
        calendar_version="calendar-v1",
        price_limit_rule_version="limit-v1",
        tick_size_rule_version="tick-v1",
        price_limit_policy=policy,
        tick_size_policy=tick,
    )
    assert set(blockers) == {
        BUY_BLOCKED_AT_UPPER_LOCK,
        PRICE_ABOVE_LIMIT,
        PRICE_TICK_MISALIGNED,
    }
    mismatch = snapshot.validate_price(
        side="sell",
        price=Decimal("10.00"),
        as_of=T0 + timedelta(minutes=1),
        stable_security_id="CN.SECURITY.600000",
        calendar_version="calendar-v1",
        price_limit_rule_version="limit-v1",
        tick_size_rule_version="tick-v1",
        price_limit_policy=PriceLimitPolicy(
            True,
            Decimal("0.20"),
            Decimal("0.20"),
            "floor",
            "ceiling",
        ),
        tick_size_policy=tick,
    )
    assert PRICE_LIMIT_POLICY_MISMATCH in mismatch
    invisible = _price_snapshot(available_time=T0 + timedelta(minutes=2))
    assert PRICE_SNAPSHOT_NOT_AVAILABLE in invisible.validate_price(
        side="buy",
        price=Decimal("10.00"),
        as_of=T0 + timedelta(minutes=1),
        stable_security_id="CN.SECURITY.600000",
        calendar_version="calendar-v1",
        price_limit_rule_version="limit-v1",
        tick_size_rule_version="tick-v1",
        price_limit_policy=policy,
        tick_size_policy=tick,
    )


def test_board_lot_and_fee_tax_rounding_are_explicit() -> None:
    lot = BoardLotPolicy(
        100,
        100,
        True,
        odd_lot_sell_mode="full_remainder_only",
    )
    assert lot.validate_quantity(side="buy", quantity=101) == "buy_lot_invalid"
    assert (
        lot.validate_quantity(side="sell", quantity=50, current_position=50)
        == "valid"
    )
    assert (
        lot.validate_quantity(side="sell", quantity=50, current_position=150)
        == "odd_lot_sell_requires_full_remainder"
    )
    fee = FeePolicy(
        buy=(
            FeeComponent(
                "commission",
                Decimal("0.0003"),
                Decimal("5"),
                Decimal("0"),
                Decimal("0.01"),
                "ceiling",
            ),
        ),
        sell=(
            FeeComponent(
                "stamp_tax",
                Decimal("0.0005"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0.01"),
                "ceiling",
            ),
        ),
    )
    assert fee.total_charge(side="buy", notional=Decimal("1000")) == Decimal("5")
    assert fee.total_charge(side="sell", notional=Decimal("1001")) == Decimal(
        "0.51"
    )


def test_t_plus_one_sellability_and_settlement_policy_mismatch_fail_closed() -> None:
    lot = SettlementInventoryLot(
        lot_id="lot-1",
        stable_security_id="CN.SECURITY.600000",
        quantity=100,
        reserved_quantity=10,
        acquired_session_sequence=10,
        session_sequence_version="sequence-v1",
        event_time=T0,
        available_time=T0,
        ingested_at=T0 + timedelta(minutes=1),
        processed_at=T0 + timedelta(minutes=2),
        source="broker-ledger-export",
        version="lot-v1",
        checksum=SHA,
    )
    snapshot = SettlementInventorySnapshot(
        snapshot_id="inventory-1",
        event_time=T0,
        available_time=T0,
        ingested_at=T0 + timedelta(minutes=1),
        processed_at=T0 + timedelta(minutes=2),
        source="broker-ledger-export",
        version="snapshot-v1",
        checksum=SHA,
        complete=True,
        lots=(lot,),
    )
    inventory = SettlementInventory(snapshot)
    policy = SettlementPolicy(1, 0, False)
    same_day = inventory.resolve(
        stable_security_id="CN.SECURITY.600000",
        as_of=T0 + timedelta(hours=1),
        current_session_sequence=10,
        current_session_sequence_version="sequence-v1",
        sellability_policy=SellabilityPolicy(1),
        settlement_policy=policy,
    )
    assert same_day.status == INVENTORY_RESOLVED
    assert same_day.sellable_quantity == 0
    next_day = inventory.resolve(
        stable_security_id="CN.SECURITY.600000",
        as_of=T0 + timedelta(days=1),
        current_session_sequence=11,
        current_session_sequence_version="sequence-v1",
        sellability_policy=SellabilityPolicy(1),
        settlement_policy=policy,
    )
    assert next_day.sellable_quantity == 90
    mismatch = inventory.resolve(
        stable_security_id="CN.SECURITY.600000",
        as_of=T0 + timedelta(days=1),
        current_session_sequence=11,
        current_session_sequence_version="sequence-v1",
        sellability_policy=SellabilityPolicy(0),
        settlement_policy=policy,
    )
    assert mismatch.status == INVENTORY_POLICY_MISMATCH


def test_market_rule_consumer_application_surface_is_cn_only_and_read_only() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    paths = (
        root / "quant_cn" / "data" / "market_rule_consumer.py",
        root / "quant_cn" / "application" / "market_semantics_preflight.py",
    )
    forbidden_imports = (
        "quant_crypto",
        "quant_us",
        "broker",
        "requests",
        "httpx",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert not any(
            f"import {token}" in source or f"from {token}" in source
            for token in forbidden_imports
        )
        assert "submit_order" not in source
        assert "paper_start" not in source
