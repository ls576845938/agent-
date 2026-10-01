"""Versioned admission decision for isolated offline diagnostics.

The source package and its original research blockers remain immutable.  This
decision only says whether a new delivery record may proceed through the
management workflow for an isolated offline diagnostic.  It never grants
research promotion, runtime start, or trading permission.
"""
from typing import Iterable

from .models import digest

SCHEMA = "strategy_delivery_diagnostic_admission_v1"
MODE = "isolated_offline_diagnostic"
SOFT_RESEARCH_BLOCKERS = frozenset({"no_simulated_fills", "research_admission_not_proven"})
OFFLINE_TARGET_REQUIRED = "offline_diagnostic_target_required"


def build_diagnostic_admission(*, package_digest: str, target: str, consumer_head: str,
                               strict_blockers: Iterable[str]) -> dict:
    strict = sorted(set(strict_blockers))
    if target != "offline":
        strict = sorted({*strict, OFFLINE_TARGET_REQUIRED})
    research = sorted(reason for reason in strict
                      if target == "offline" and reason in SOFT_RESEARCH_BLOCKERS)
    blocking = sorted(reason for reason in strict if reason not in research)
    value = {
        "schema_version": SCHEMA,
        "mode": MODE,
        "target": target,
        "package_digest": package_digest,
        "consumer_head": consumer_head,
        "status": "admitted" if not blocking else "blocked",
        "strict_package_blockers": strict,
        "research_blockers": research,
        "blocking_reasons": blocking,
    }
    return {**value, "decision_digest": digest(value)}
