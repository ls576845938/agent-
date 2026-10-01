from __future__ import annotations

from datetime import timedelta

import pytest

from quant_cn.application.foundation_preflight import run_foundation_preflight
from quant_cn.market.calendar import InjectedCalendar
from quant_cn.market.eligibility import SafetyFlags
from quant_cn.market.rules import PRICE_LIMIT, EffectiveRuleBook

from .factories import (
    AS_OF,
    dimensions_for,
    make_calendar,
    make_record,
    make_rule,
    make_rulebook,
    make_session,
)


def _run(*, record=None, calendar=None, rulebook=None, as_of=AS_OF):
    record = record or make_record()
    dimensions = dimensions_for(record)
    return run_foundation_preflight(
        record=record,
        as_of=as_of,
        calendar=calendar or make_calendar(dimensions),
        rulebook=rulebook or make_rulebook(dimensions),
    )


def test_complete_injected_inputs_are_eligible_but_never_trade_enabled() -> None:
    result = _run()
    assert result.eligible
    assert result.blockers == ()
    assert dict(result.versions) == {
        "calendar": "calendar-fixture-v1",
        "pit": "pit-fixture-v1",
        "rule:board_lot": "board_lot-fixture-v1",
        "rule:fee_schedule": "fee_schedule-fixture-v1",
        "rule:price_limit": "price_limit-fixture-v1",
        "rule:sellability": "sellability-fixture-v1",
    }
    assert set(result.safety_flags.to_dict().values()) == {False}


def test_missing_rule_produces_exact_blocker() -> None:
    record = make_record()
    dimensions = dimensions_for(record)
    rulebook = EffectiveRuleBook(
        rule
        for rule in make_rulebook(dimensions).rules
        if rule.rule_kind != PRICE_LIMIT
    )
    result = _run(record=record, rulebook=rulebook)
    assert result.blockers == ("price_limit_rule_missing",)
    assert not result.eligible


def test_pit_lookahead_blocks_without_future_metadata_leak() -> None:
    record = make_record(
        state="suspended",
        venue="unknown",
        board="unknown",
        instrument="unknown",
        security_type="unknown",
        available_time=AS_OF + timedelta(seconds=1),
        ingested_at=AS_OF + timedelta(seconds=2),
        processed_at=AS_OF + timedelta(seconds=3),
        version="future-pit",
    )
    result = _run(
        record=record,
        calendar=InjectedCalendar(()),
        rulebook=EffectiveRuleBook(()),
    )
    assert result.blockers == ("pit_record_not_available",)
    assert result.versions == ()
    assert "future-pit" not in result.to_json()


@pytest.mark.parametrize(
    ("state", "blocker"),
    [
        ("suspended", "security_suspended"),
        ("delisted", "security_delisted"),
        ("not_listed", "security_not_listed"),
        ("vendor_mystery", "security_state_unknown"),
    ],
)
def test_security_state_is_fail_closed(state: str, blocker: str) -> None:
    result = _run(record=make_record(state=state))
    assert blocker in result.blockers
    assert not result.eligible


def test_unknown_dimensions_and_missing_inputs_never_pass() -> None:
    record = make_record(
        venue="unknown",
        board="unknown",
        instrument="unknown",
        security_type="unknown",
    )
    result = _run(
        record=record,
        calendar=InjectedCalendar(()),
        rulebook=EffectiveRuleBook(()),
    )
    assert {
        "security_venue_unknown",
        "security_board_unknown",
        "security_instrument_unknown",
        "security_type_unknown",
        "calendar_session_missing",
        "price_limit_rule_missing",
    } <= set(result.blockers)
    assert not result.eligible


def test_invisible_calendar_and_rules_do_not_leak_versions() -> None:
    record = make_record()
    dimensions = dimensions_for(record)
    calendar = InjectedCalendar(
        (
            make_session(
                dimensions,
                version="future-calendar",
                available_time=AS_OF + timedelta(seconds=1),
                ingested_at=AS_OF + timedelta(seconds=2),
                processed_at=AS_OF + timedelta(seconds=3),
            ),
        )
    )
    rules = tuple(
        make_rule(
            rule.rule_kind,
            dimensions,
            version=f"future-{rule.rule_kind}",
            available_time=AS_OF + timedelta(seconds=1),
            ingested_at=AS_OF + timedelta(seconds=2),
            processed_at=AS_OF + timedelta(seconds=3),
        )
        for rule in make_rulebook(dimensions).rules
    )
    result = _run(
        record=record,
        calendar=calendar,
        rulebook=EffectiveRuleBook(rules),
    )
    assert dict(result.versions) == {"pit": "pit-fixture-v1"}
    assert "future-" not in result.to_json()
    assert not result.eligible


def test_safety_flags_are_immutable_false_and_output_has_no_order_object() -> None:
    result = _run()
    payload = result.to_dict()
    assert set(payload) == {"eligibility", "blockers", "versions", "safety_flags"}
    assert set(payload["safety_flags"].values()) == {False}
    serialized = result.to_json().lower()
    for forbidden in ("signal", "orderintent", "\"order\":{", "fill", "ledger"):
        assert forbidden not in serialized
    with pytest.raises(TypeError):
        SafetyFlags(live=True)  # type: ignore[call-arg]
