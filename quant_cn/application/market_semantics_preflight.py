"""Application preflight for evidence-bound CN market semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from quant_cn.data.contracts import ensure_aware_timestamp
from quant_cn.data.market_rule_consumer import (
    DOMAIN_RULE_KINDS,
    MISSING_RULE_BLOCKERS,
    SESSION,
    MarketRuleConsumption,
)
from quant_cn.market.calendar import CALENDAR_OPEN
from quant_cn.market.rules import (
    RULE_RESOLVED,
    MarketDimensions,
)


@dataclass(frozen=True)
class MarketSemanticsPreflight:
    status: str
    decision: str
    blockers: tuple[str, ...]
    versions: tuple[tuple[str, str], ...]
    sources: tuple[tuple[str, str], ...]
    consumer_read_only: bool = True

    def __post_init__(self) -> None:
        blockers = tuple(sorted(set(self.blockers)))
        versions = tuple(sorted(set(self.versions)))
        sources = tuple(sorted(set(self.sources)))
        if self.consumer_read_only is not True:
            raise ValueError("market_semantics_preflight_must_be_read_only")
        if self.status not in {"blocked", "pass"}:
            raise ValueError("market_semantics_preflight_status_invalid")
        if self.decision not in {"blocked", "research_only"}:
            raise ValueError("market_semantics_preflight_decision_invalid")
        if (self.status == "blocked") != bool(blockers):
            raise ValueError("market_semantics_preflight_status_blocker_mismatch")
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "versions", versions)
        object.__setattr__(self, "sources", sources)

    @property
    def safety_flags(self) -> dict[str, bool]:
        return {
            "broker": False,
            "live": False,
            "oms": False,
            "order": False,
            "paper": False,
            "private": False,
            "promotion": False,
            "real_order": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockers": list(self.blockers),
            "consumer_read_only": self.consumer_read_only,
            "decision": self.decision,
            "safety_flags": self.safety_flags,
            "sources": dict(self.sources),
            "status": self.status,
            "versions": dict(self.versions),
        }


def run_market_semantics_preflight(
    *,
    consumption: MarketRuleConsumption,
    dimensions: MarketDimensions,
    as_of: datetime,
) -> MarketSemanticsPreflight:
    """Resolve only rules visible for the requested security and decision time."""

    if not isinstance(consumption, MarketRuleConsumption):
        raise TypeError("market_rule_consumption_type_invalid")
    if not isinstance(dimensions, MarketDimensions):
        raise TypeError("market_dimensions_type_invalid")
    timestamp = ensure_aware_timestamp(as_of, "as_of").astimezone(timezone.utc)
    blockers = [item.code for item in consumption.blockers]
    versions: list[tuple[str, str]] = []
    sources: list[tuple[str, str]] = []

    for kind in DOMAIN_RULE_KINDS:
        resolution = consumption.rulebook.resolve(
            kind,
            dimensions=dimensions,
            as_of=timestamp,
        )
        if resolution.status != RULE_RESOLVED or resolution.rule is None:
            blockers.append(MISSING_RULE_BLOCKERS[kind])
            if resolution.status != "missing":
                blockers.append(f"{kind}_rule_{resolution.status}")
            continue
        versions.append((kind, resolution.rule.rule_version))
        sources.append((kind, resolution.rule.source))

    calendar = consumption.calendar.resolve(
        as_of=timestamp,
        venue=dimensions.venue,
        board=dimensions.board,
        instrument=dimensions.instrument,
        security_type=dimensions.security_type,
    )
    if calendar.status != CALENDAR_OPEN:
        blockers.append(MISSING_RULE_BLOCKERS[SESSION])
        blockers.append(f"session_rule_{calendar.status}")
    else:
        versions.append((SESSION, str(calendar.calendar_version)))
        binding = next(
            (
                item
                for item in consumption.bindings
                if item.rule_kind == SESSION
                and item.dimensions.matches(dimensions)
                and item.effective_from <= timestamp
                and (
                    item.effective_to is None
                    or timestamp < item.effective_to
                )
            ),
            None,
        )
        if binding is None:
            blockers.append(MISSING_RULE_BLOCKERS[SESSION])
            blockers.append("session_rule_source_binding_missing")
        else:
            sources.append((SESSION, binding.source))

    canonical = tuple(sorted(set(blockers)))
    return MarketSemanticsPreflight(
        status="blocked" if canonical else "pass",
        decision="blocked" if canonical else "research_only",
        blockers=canonical,
        versions=tuple(versions),
        sources=tuple(sources),
    )
