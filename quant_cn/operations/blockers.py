"""Stable fail-closed blocker codes for CN DataReady consumption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


CN_DATAREADY_HANDOFF_MISSING = "cn_dataready_handoff_missing"
CN_DATAREADY_HANDOFF_INVALID = "cn_dataready_handoff_invalid"
CN_DATAREADY_MANIFEST_MISSING = "cn_dataready_manifest_missing"
CN_DATAREADY_MANIFEST_RESOLVE_FAILED = "cn_dataready_manifest_resolve_failed"
CN_DATAREADY_SCHEMA_MISMATCH = "cn_dataready_schema_mismatch"
CN_DATAREADY_IDENTITY_MISMATCH = "cn_dataready_identity_mismatch"
CN_DATAREADY_READINESS_INSUFFICIENT = "cn_dataready_readiness_insufficient"
CN_DATAREADY_QUALITY_BLOCKED = "cn_dataready_quality_blocked"
CN_DATAREADY_MANIFEST_BLOCKED = "cn_dataready_manifest_blocked"
CN_DATAREADY_KNOWN_GAP = "cn_dataready_known_gap"
CN_DATAREADY_PILOT_ONLY = "cn_dataready_pilot_only"
CN_DATAREADY_COVERAGE_INCOMPLETE = "cn_dataready_coverage_incomplete"
CN_DATAREADY_COVERAGE_DATE_MISMATCH = "cn_dataready_coverage_date_mismatch"
CN_DATAREADY_COMMON_DATE_MISSING = "cn_dataready_common_date_missing"
CN_DATAREADY_COMMON_DATE_STALE = "cn_dataready_common_date_stale"
CN_DATAREADY_PIT_INCOMPLETE = "cn_dataready_pit_incomplete"
CN_DATAREADY_QUALITY_INCOMPLETE = "cn_dataready_quality_incomplete"
CN_DATAREADY_LICENSE_UNVERIFIED = "cn_dataready_license_unverified"
CN_DATAREADY_LISTING_HISTORY_MISSING = "cn_dataready_listing_history_missing"
CN_DATAREADY_DELISTING_HISTORY_MISSING = "cn_dataready_delisting_history_missing"
CN_DATAREADY_RISK_WARNING_HISTORY_MISSING = (
    "cn_dataready_risk_warning_history_missing"
)
CN_DATAREADY_SUSPENSION_HISTORY_MISSING = (
    "cn_dataready_suspension_history_missing"
)
CN_DATAREADY_CORPORATE_ACTION_VISIBILITY_MISSING = (
    "cn_dataready_corporate_action_visibility_missing"
)
CN_DATAREADY_ADJUSTMENT_VISIBILITY_MISSING = (
    "cn_dataready_adjustment_visibility_missing"
)


@dataclass(frozen=True, order=True)
class DataReadinessBlocker:
    code: str
    owner: str
    next_action: str
    detail: str = ""

    def __post_init__(self) -> None:
        for field_name in ("code", "owner", "next_action"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"non_empty_string_required:{field_name}")


def blocker(
    code: str,
    *,
    detail: str = "",
    owner: str = "data_steward",
    next_action: str = "publish_current_main_cn_dataready_evidence",
) -> DataReadinessBlocker:
    return DataReadinessBlocker(
        code=code,
        owner=owner,
        next_action=next_action,
        detail=str(detail),
    )


def dedupe_blockers(
    values: Iterable[DataReadinessBlocker],
) -> tuple[DataReadinessBlocker, ...]:
    by_identity: dict[tuple[str, str], DataReadinessBlocker] = {}
    for value in values:
        if not isinstance(value, DataReadinessBlocker):
            raise TypeError("data_readiness_blocker_type_invalid")
        by_identity.setdefault((value.code, value.detail), value)
    return tuple(
        sorted(
            by_identity.values(),
            key=lambda item: (item.code, item.detail, item.owner),
        )
    )
