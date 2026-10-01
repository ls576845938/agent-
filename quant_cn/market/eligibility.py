"""Fail-closed eligibility results and stable blocker serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable

from quant_cn.data.contracts import PIT_RECORD_NOT_AVAILABLE
from quant_cn.market.calendar import (
    CALENDAR_PHASE_AMBIGUOUS,
    CALENDAR_PHASE_CLOSED,
    CALENDAR_PHASE_MISSING,
    CALENDAR_SESSION_AMBIGUOUS,
    CALENDAR_SESSION_CLOSED,
    CALENDAR_SESSION_MISSING,
    CALENDAR_SESSION_NOT_AVAILABLE,
)
from quant_cn.market.rules import (
    BOARD_LOT,
    FEE_SCHEDULE,
    PRICE_LIMIT,
    RULE_AMBIGUOUS,
    RULE_EXPIRED,
    RULE_MISSING,
    RULE_NOT_AVAILABLE,
    RULE_NOT_YET_EFFECTIVE,
    RULE_OVERLAP,
    RULE_UNKNOWN,
    SELLABILITY,
)


SECURITY_STATE_UNKNOWN = "security_state_unknown"
SECURITY_NOT_LISTED = "security_not_listed"
SECURITY_SUSPENDED = "security_suspended"
SECURITY_DELISTED = "security_delisted"
SECURITY_VENUE_UNKNOWN = "security_venue_unknown"
SECURITY_BOARD_UNKNOWN = "security_board_unknown"
SECURITY_INSTRUMENT_UNKNOWN = "security_instrument_unknown"
SECURITY_TYPE_UNKNOWN = "security_type_unknown"

CALENDAR_BLOCKERS = {
    CALENDAR_SESSION_MISSING: "calendar_session_missing",
    CALENDAR_SESSION_NOT_AVAILABLE: "calendar_session_not_available",
    CALENDAR_SESSION_AMBIGUOUS: "calendar_session_ambiguous",
    CALENDAR_SESSION_CLOSED: "calendar_session_closed",
    CALENDAR_PHASE_MISSING: "calendar_phase_missing",
    CALENDAR_PHASE_AMBIGUOUS: "calendar_phase_ambiguous",
    CALENDAR_PHASE_CLOSED: "calendar_phase_closed",
}

RULE_BLOCKERS = {
    rule_kind: {
        RULE_MISSING: f"{rule_kind}_rule_missing",
        RULE_NOT_AVAILABLE: f"{rule_kind}_rule_not_available",
        RULE_NOT_YET_EFFECTIVE: f"{rule_kind}_rule_not_yet_effective",
        RULE_EXPIRED: f"{rule_kind}_rule_expired",
        RULE_OVERLAP: f"{rule_kind}_rule_overlap",
        RULE_AMBIGUOUS: f"{rule_kind}_rule_ambiguous",
        RULE_UNKNOWN: "rule_kind_unknown",
    }
    for rule_kind in (PRICE_LIMIT, BOARD_LOT, SELLABILITY, FEE_SCHEDULE)
}

BLOCKER_CATALOG = tuple(
    sorted(
        {
            PIT_RECORD_NOT_AVAILABLE,
            SECURITY_STATE_UNKNOWN,
            SECURITY_NOT_LISTED,
            SECURITY_SUSPENDED,
            SECURITY_DELISTED,
            SECURITY_VENUE_UNKNOWN,
            SECURITY_BOARD_UNKNOWN,
            SECURITY_INSTRUMENT_UNKNOWN,
            SECURITY_TYPE_UNKNOWN,
            *CALENDAR_BLOCKERS.values(),
            *(value for mapping in RULE_BLOCKERS.values() for value in mapping.values()),
        }
    )
)


def canonical_blockers(values: Iterable[str]) -> tuple[str, ...]:
    blockers = tuple(sorted(set(values)))
    unknown = tuple(item for item in blockers if item not in BLOCKER_CATALOG)
    if unknown:
        raise ValueError(f"blocker_not_in_catalog:{','.join(unknown)}")
    return blockers


@dataclass(frozen=True, init=False)
class SafetyFlags:
    """Non-configurable safety flags for this foundation-only surface."""

    promotion: bool = False
    paper: bool = False
    live: bool = False
    private: bool = False
    order: bool = False
    real_order: bool = False
    broker: bool = False
    network: bool = False
    withdraw: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "broker": self.broker,
            "live": self.live,
            "network": self.network,
            "order": self.order,
            "paper": self.paper,
            "private": self.private,
            "promotion": self.promotion,
            "real_order": self.real_order,
            "withdraw": self.withdraw,
        }


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    blockers: tuple[str, ...]
    versions: tuple[tuple[str, str], ...]
    safety_flags: SafetyFlags = field(default_factory=SafetyFlags, init=False)

    def __post_init__(self) -> None:
        blockers = canonical_blockers(self.blockers)
        versions = tuple(sorted((str(key), str(value)) for key, value in self.versions))
        if self.eligible != (len(blockers) == 0):
            raise ValueError("eligibility_must_match_blockers")
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "versions", versions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockers": list(self.blockers),
            "eligibility": {"eligible": self.eligible},
            "safety_flags": self.safety_flags.to_dict(),
            "versions": {key: value for key, value in self.versions},
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def blocker_for_rule(rule_kind: str, status: str) -> str:
    try:
        return RULE_BLOCKERS[rule_kind][status]
    except KeyError:
        return "rule_kind_unknown"
