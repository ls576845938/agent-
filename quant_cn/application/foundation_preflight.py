"""Side-effect-free foundation preflight for injected CN market inputs."""

from __future__ import annotations

from datetime import datetime

from quant_cn.data.contracts import (
    PITLookaheadError,
    PITSecurityRecord,
    ensure_aware_timestamp,
)
from quant_cn.market.calendar import CALENDAR_OPEN, InjectedCalendar
from quant_cn.market.eligibility import (
    CALENDAR_BLOCKERS,
    PIT_RECORD_NOT_AVAILABLE,
    SECURITY_BOARD_UNKNOWN,
    SECURITY_DELISTED,
    SECURITY_INSTRUMENT_UNKNOWN,
    SECURITY_NOT_LISTED,
    SECURITY_STATE_UNKNOWN,
    SECURITY_SUSPENDED,
    SECURITY_TYPE_UNKNOWN,
    SECURITY_VENUE_UNKNOWN,
    EligibilityResult,
    blocker_for_rule,
)
from quant_cn.market.rules import (
    RULE_KINDS,
    RULE_RESOLVED,
    EffectiveRuleBook,
    MarketDimensions,
)


STATE_BLOCKERS = {
    "suspended": SECURITY_SUSPENDED,
    "delisted": SECURITY_DELISTED,
    "not_listed": SECURITY_NOT_LISTED,
    "unknown": SECURITY_STATE_UNKNOWN,
}

DIMENSION_BLOCKERS = {
    "venue": SECURITY_VENUE_UNKNOWN,
    "board": SECURITY_BOARD_UNKNOWN,
    "instrument": SECURITY_INSTRUMENT_UNKNOWN,
    "security_type": SECURITY_TYPE_UNKNOWN,
}


def run_foundation_preflight(
    *,
    record: PITSecurityRecord,
    as_of: datetime,
    calendar: InjectedCalendar,
    rulebook: EffectiveRuleBook,
) -> EligibilityResult:
    """Resolve eligibility without I/O, fallback defaults, or order output."""

    if not isinstance(record, PITSecurityRecord):
        raise TypeError("pit_security_record_type_invalid")
    if not isinstance(calendar, InjectedCalendar):
        raise TypeError("injected_calendar_type_invalid")
    if not isinstance(rulebook, EffectiveRuleBook):
        raise TypeError("effective_rulebook_type_invalid")

    decision_time = ensure_aware_timestamp(as_of, "as_of")
    try:
        record.assert_available(decision_time)
    except PITLookaheadError:
        return EligibilityResult(
            eligible=False,
            blockers=(PIT_RECORD_NOT_AVAILABLE,),
            versions=(),
        )

    dimensions = MarketDimensions(
        venue=record.venue,
        board=record.board,
        instrument=record.instrument,
        security_type=record.security_type,
        security_id=record.stable_security_id,
    )
    blockers: list[str] = []
    versions: list[tuple[str, str]] = [("pit", record.version)]

    if record.state != "listed":
        blockers.append(STATE_BLOCKERS.get(record.state, SECURITY_STATE_UNKNOWN))
    for field_name in dimensions.unknown_fields():
        blockers.append(DIMENSION_BLOCKERS[field_name])

    calendar_resolution = calendar.resolve(
        as_of=decision_time,
        venue=record.venue,
        board=record.board,
        instrument=record.instrument,
        security_type=record.security_type,
    )
    if calendar_resolution.status == CALENDAR_OPEN:
        if calendar_resolution.calendar_version is not None:
            versions.append(("calendar", calendar_resolution.calendar_version))
    else:
        blockers.append(CALENDAR_BLOCKERS[calendar_resolution.status])

    for rule_kind in RULE_KINDS:
        resolution = rulebook.resolve(
            rule_kind,
            dimensions=dimensions,
            as_of=decision_time,
        )
        if resolution.status == RULE_RESOLVED:
            versions.append((f"rule:{rule_kind}", resolution.versions[0]))
        else:
            blockers.append(blocker_for_rule(rule_kind, resolution.status))

    return EligibilityResult(
        eligible=not blockers,
        blockers=tuple(blockers),
        versions=tuple(versions),
    )
