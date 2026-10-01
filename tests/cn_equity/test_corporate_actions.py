from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from quant_cn.market.corporate_actions import (
    ACTION_NOT_AVAILABLE,
    ACTION_RESOLVED,
    BONUS_SHARE,
    CASH_DIVIDEND,
    EFFECT_EFFECTIVE,
    EFFECT_PENDING,
    FRACTIONAL_ROUND_DOWN,
    CorporateActionBook,
    CorporateActionSnapshot,
    PITCorporateAction,
)


UTC = timezone.utc
T0 = datetime(2025, 1, 2, tzinfo=UTC)
SHA = "b" * 64


def _bonus(*, version: str, available_time: datetime) -> PITCorporateAction:
    return PITCorporateAction(
        action_id="bonus-1",
        stable_security_id="CN.SECURITY.600000",
        action_type=BONUS_SHARE,
        announce_time=T0,
        available_time=available_time,
        ingested_at=available_time + timedelta(minutes=1),
        processed_at=available_time + timedelta(minutes=2),
        record_time=T0 + timedelta(days=1),
        effective_time=T0 + timedelta(days=2),
        pay_time=None,
        rights_expiry_time=None,
        cash_per_share=None,
        share_ratio=Decimal("0.1"),
        share_multiplier=None,
        subscription_price=None,
        fractional_policy=FRACTIONAL_ROUND_DOWN,
        source="exchange-disclosure",
        source_version="disclosure-schema-v1",
        effective_rule_date=T0 - timedelta(days=1),
        version=version,
        checksum=SHA,
    )


def _snapshot(actions: tuple[PITCorporateAction, ...]) -> CorporateActionSnapshot:
    return CorporateActionSnapshot(
        snapshot_id="actions-1",
        event_time=T0,
        available_time=T0,
        ingested_at=T0 + timedelta(minutes=1),
        processed_at=T0 + timedelta(minutes=2),
        source="immutable-shared-data",
        source_version="manifest-v1",
        effective_rule_date=T0 - timedelta(days=1),
        version="snapshot-v1",
        checksum=SHA,
        complete=True,
        actions=actions,
    )


def test_late_corporate_action_is_invisible_without_version_leak() -> None:
    action = _bonus(
        version="late-correction-v2",
        available_time=T0 + timedelta(days=3),
    )
    resolution = CorporateActionBook(_snapshot((action,))).resolve(
        stable_security_id="CN.SECURITY.600000",
        action_id="bonus-1",
        as_of=T0 + timedelta(days=2),
    )
    assert resolution.status == ACTION_NOT_AVAILABLE
    assert resolution.versions == ()
    assert resolution.action is None


def test_corporate_action_effect_is_pending_then_deterministic() -> None:
    action = _bonus(version="bonus-v1", available_time=T0)
    book = CorporateActionBook(_snapshot((action,)))
    pending = book.project(
        stable_security_id="CN.SECURITY.600000",
        action_id="bonus-1",
        as_of=T0 + timedelta(days=1),
        record_quantity=Decimal("105"),
    )
    effective = book.project(
        stable_security_id="CN.SECURITY.600000",
        action_id="bonus-1",
        as_of=T0 + timedelta(days=2),
        record_quantity=Decimal("105"),
    )
    assert pending.status == EFFECT_PENDING
    assert pending.position_delta == Decimal("0")
    assert effective.status == EFFECT_EFFECTIVE
    assert effective.position_delta == Decimal("10")
    assert effective.posting_key is not None
    assert len(effective.posting_key) == 64
    assert CorporateActionBook(_snapshot((action,))).resolve(
        stable_security_id="CN.SECURITY.600000",
        action_id="bonus-1",
        as_of=T0,
    ).status == ACTION_RESOLVED


def test_cash_dividend_uses_explicit_pay_time() -> None:
    action = PITCorporateAction(
        action_id="cash-1",
        stable_security_id="CN.SECURITY.600000",
        action_type=CASH_DIVIDEND,
        announce_time=T0,
        available_time=T0,
        ingested_at=T0 + timedelta(minutes=1),
        processed_at=T0 + timedelta(minutes=2),
        record_time=T0 + timedelta(days=1),
        effective_time=T0 + timedelta(days=2),
        pay_time=T0 + timedelta(days=3),
        rights_expiry_time=None,
        cash_per_share=Decimal("0.25"),
        share_ratio=None,
        share_multiplier=None,
        subscription_price=None,
        fractional_policy=None,
        source="exchange-disclosure",
        source_version="disclosure-schema-v1",
        effective_rule_date=T0 - timedelta(days=1),
        version="cash-v1",
        checksum=SHA,
    )
    book = CorporateActionBook(_snapshot((action,)))
    assert book.project(
        stable_security_id="CN.SECURITY.600000",
        action_id="cash-1",
        as_of=T0 + timedelta(days=2),
        record_quantity=Decimal("100"),
    ).status == EFFECT_PENDING
    paid = book.project(
        stable_security_id="CN.SECURITY.600000",
        action_id="cash-1",
        as_of=T0 + timedelta(days=3),
        record_quantity=Decimal("100"),
    )
    assert paid.cash_delta == Decimal("25.00")
