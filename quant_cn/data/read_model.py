"""Pure fail-closed CN DataReady evidence assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from quant_cn.data.contracts import ensure_sha256_checksum, require_non_empty
from quant_cn.operations.blockers import (
    CN_DATAREADY_ADJUSTMENT_VISIBILITY_MISSING,
    CN_DATAREADY_COMMON_DATE_MISSING,
    CN_DATAREADY_COMMON_DATE_STALE,
    CN_DATAREADY_CORPORATE_ACTION_VISIBILITY_MISSING,
    CN_DATAREADY_COVERAGE_DATE_MISMATCH,
    CN_DATAREADY_COVERAGE_INCOMPLETE,
    CN_DATAREADY_DELISTING_HISTORY_MISSING,
    CN_DATAREADY_IDENTITY_MISMATCH,
    CN_DATAREADY_KNOWN_GAP,
    CN_DATAREADY_LICENSE_UNVERIFIED,
    CN_DATAREADY_LISTING_HISTORY_MISSING,
    CN_DATAREADY_MANIFEST_BLOCKED,
    CN_DATAREADY_PILOT_ONLY,
    CN_DATAREADY_PIT_INCOMPLETE,
    CN_DATAREADY_QUALITY_BLOCKED,
    CN_DATAREADY_QUALITY_INCOMPLETE,
    CN_DATAREADY_READINESS_INSUFFICIENT,
    CN_DATAREADY_RISK_WARNING_HISTORY_MISSING,
    CN_DATAREADY_SCHEMA_MISMATCH,
    CN_DATAREADY_SUSPENSION_HISTORY_MISSING,
    DataReadinessBlocker,
    blocker,
    dedupe_blockers,
)


CN_DATAREADY_EVIDENCE_SCHEMA = "cn_data_readiness_evidence_v1"
CN_DATAREADY_DATA_SCHEMA = "cn_equity_dataready_bundle_v1"
CN_DATAREADY_EVIDENCE_FILE = "cn_dataready_evidence.json"
ACCEPTED_MANIFEST_READINESS = frozenset(
    {"research_ready", "backtest_ready", "promotion_evidence_ready"}
)
SAFETY_FLAGS: Mapping[str, bool] = MappingProxyType(
    {
        "promotion_eligible": False,
        "promotion_unlock_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "real_order_submitted": False,
    }
)


@dataclass(frozen=True)
class CNDataReadModel:
    status: str
    decision: str
    dataset_id: str
    dataset_version: str
    manifest_sha256: str
    common_date: str
    security_count: int
    expected_security_count: int
    coverage_ratio: float
    blockers: tuple[DataReadinessBlocker, ...]
    safety_flags: Mapping[str, bool] = SAFETY_FLAGS
    schema_version: str = "cn_data_read_model_v1"

    def __post_init__(self) -> None:
        if self.status not in {"pass", "blocked"}:
            raise ValueError("cn_data_read_model_status_invalid")
        if self.decision not in {"research_only", "blocked"}:
            raise ValueError("cn_data_read_model_decision_invalid")
        if self.status == "pass" and self.blockers:
            raise ValueError("passing_cn_data_read_model_has_blockers")
        if self.status == "pass" and self.decision != "research_only":
            raise ValueError("cn_data_read_model_cannot_promote")
        if self.manifest_sha256:
            ensure_sha256_checksum(self.manifest_sha256, "manifest_sha256")
        for field_name in ("security_count", "expected_security_count"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"non_negative_integer_required:{field_name}")
        if not isinstance(self.coverage_ratio, (int, float)) or not (
            0 <= float(self.coverage_ratio) <= 1
        ):
            raise ValueError("coverage_ratio_out_of_range")
        if any(value is not False for value in self.safety_flags.values()):
            raise ValueError("cn_data_read_model_safety_flag_enabled")

    @classmethod
    def missing(
        cls,
        blockers: Sequence[DataReadinessBlocker],
    ) -> "CNDataReadModel":
        return cls(
            status="blocked",
            decision="blocked",
            dataset_id="",
            dataset_version="",
            manifest_sha256="",
            common_date="",
            security_count=0,
            expected_security_count=0,
            coverage_ratio=0.0,
            blockers=dedupe_blockers(blockers),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "decision": self.decision,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "manifest_sha256": self.manifest_sha256,
            "common_date": self.common_date,
            "coverage": {
                "security_count": self.security_count,
                "expected_security_count": self.expected_security_count,
                "ratio": self.coverage_ratio,
            },
            "blockers": [
                {
                    "code": item.code,
                    "owner": item.owner,
                    "next_action": item.next_action,
                    "detail": item.detail,
                }
                for item in self.blockers
            ],
            "safety_flags": dict(self.safety_flags),
        }


def assess_cn_dataready(
    *,
    manifest: Mapping[str, Any],
    evidence: Mapping[str, Any],
    manifest_sha256: str,
    evaluated_at: datetime,
    maximum_common_date_age_days: int = 5,
    minimum_security_count: int = 3,
    minimum_coverage_ratio: float = 0.95,
) -> CNDataReadModel:
    """Assess validated resolver output without filesystem or network access."""

    if not isinstance(manifest, Mapping) or not isinstance(evidence, Mapping):
        raise TypeError("dataready_payload_mapping_required")
    if (
        not isinstance(maximum_common_date_age_days, int)
        or isinstance(maximum_common_date_age_days, bool)
        or maximum_common_date_age_days < 0
    ):
        raise ValueError("maximum_common_date_age_days_invalid")
    if (
        not isinstance(minimum_security_count, int)
        or isinstance(minimum_security_count, bool)
        or minimum_security_count < 3
    ):
        raise ValueError("minimum_security_count_invalid")
    if not isinstance(minimum_coverage_ratio, (int, float)) or not (
        0 < float(minimum_coverage_ratio) <= 1
    ):
        raise ValueError("minimum_coverage_ratio_invalid")
    evaluated = _aware_utc(evaluated_at, "evaluated_at")
    blockers: list[DataReadinessBlocker] = []

    dataset_id = str(manifest.get("dataset_id", "")).strip()
    dataset_version = str(manifest.get("dataset_version", "")).strip()
    if not dataset_id.lower().startswith(("cn-", "cn_", "cn.")):
        blockers.append(
            blocker(
                CN_DATAREADY_IDENTITY_MISMATCH,
                detail=f"non_cn_dataset:{dataset_id}",
            )
        )
    if manifest.get("data_schema") != CN_DATAREADY_DATA_SCHEMA:
        blockers.append(
            blocker(
                CN_DATAREADY_SCHEMA_MISMATCH,
                detail=f"manifest:{manifest.get('data_schema', '')}",
            )
        )
    if manifest.get("readiness_class") not in ACCEPTED_MANIFEST_READINESS:
        blockers.append(
            blocker(
                CN_DATAREADY_READINESS_INSUFFICIENT,
                detail=str(manifest.get("readiness_class", "")),
            )
        )
    if manifest.get("quality_status") != "pass":
        blockers.append(
            blocker(
                CN_DATAREADY_QUALITY_BLOCKED,
                detail=str(manifest.get("quality_status", "")),
            )
        )
    blockers.extend(
        blocker(CN_DATAREADY_MANIFEST_BLOCKED, detail=str(value))
        for value in manifest.get("blockers", ())
    )
    blockers.extend(
        blocker(CN_DATAREADY_KNOWN_GAP, detail=str(value))
        for value in manifest.get("known_gaps", ())
    )

    if evidence.get("schema_version") != CN_DATAREADY_EVIDENCE_SCHEMA:
        blockers.append(
            blocker(
                CN_DATAREADY_SCHEMA_MISMATCH,
                detail=f"evidence:{evidence.get('schema_version', '')}",
            )
        )
    if (
        evidence.get("dataset_id") != dataset_id
        or evidence.get("dataset_version") != dataset_version
    ):
        blockers.append(blocker(CN_DATAREADY_IDENTITY_MISMATCH))

    coverage = _mapping(evidence.get("coverage"))
    security_count = _non_negative_int(coverage.get("security_count"))
    expected_count = _non_negative_int(coverage.get("expected_security_count"))
    declared_ratio = _ratio(coverage.get("ratio"))
    calculated_ratio = (
        security_count / expected_count if expected_count > 0 else 0.0
    )
    coverage_ratio = min(declared_ratio, calculated_ratio)
    if bool(coverage.get("pilot")) or security_count < minimum_security_count:
        blockers.append(
            blocker(
                CN_DATAREADY_PILOT_ONLY,
                detail=f"security_count={security_count}",
            )
        )
    if (
        expected_count <= 0
        or security_count > expected_count
        or coverage_ratio < minimum_coverage_ratio
    ):
        blockers.append(
            blocker(
                CN_DATAREADY_COVERAGE_INCOMPLETE,
                detail=(
                    f"security_count={security_count}:"
                    f"expected={expected_count}:ratio={coverage_ratio:.6f}"
                ),
            )
        )

    common_date = str(evidence.get("common_date", "")).strip()
    parsed_common_date = _parse_date(common_date)
    manifest_coverage = _mapping(manifest.get("coverage"))
    manifest_coverage_end = str(manifest_coverage.get("end", "")).split("T", 1)[0]
    parsed_manifest_end = _parse_date(manifest_coverage_end)
    if parsed_common_date is None:
        blockers.append(blocker(CN_DATAREADY_COMMON_DATE_MISSING))
    else:
        if parsed_manifest_end != parsed_common_date:
            blockers.append(
                blocker(
                    CN_DATAREADY_COVERAGE_DATE_MISMATCH,
                    detail=(
                        f"manifest_end={manifest_coverage_end}:"
                        f"common_date={common_date}"
                    ),
                )
            )
        if (
            evaluated.date() - parsed_common_date
        ).days > maximum_common_date_age_days:
            blockers.append(
                blocker(
                    CN_DATAREADY_COMMON_DATE_STALE,
                    detail=common_date,
                )
            )
        elif parsed_common_date > evaluated.date():
            blockers.append(
                blocker(
                    CN_DATAREADY_COMMON_DATE_STALE,
                    detail=f"future:{common_date}",
                )
            )

    pit = _mapping(evidence.get("pit"))
    required_pit = {
        "event_time",
        "available_time",
        "ingested_at",
        "processed_at",
    }
    missing_pit = sorted(key for key in required_pit if pit.get(key) is not True)
    if missing_pit:
        blockers.append(
            blocker(
                CN_DATAREADY_PIT_INCOMPLETE,
                detail=",".join(missing_pit),
            )
        )

    quality = _mapping(evidence.get("quality"))
    if (
        quality.get("status") != "pass"
        or _non_negative_int(quality.get("missing_count")) != 0
        or _non_negative_int(quality.get("duplicate_count")) != 0
        or _non_negative_int(quality.get("out_of_order_count")) != 0
        or tuple(quality.get("blocking_issues", ()))
    ):
        blockers.append(blocker(CN_DATAREADY_QUALITY_INCOMPLETE))

    license_evidence = _mapping(evidence.get("license"))
    if (
        license_evidence.get("verified") is not True
        or license_evidence.get("research_backtest_allowed") is not True
    ):
        blockers.append(blocker(CN_DATAREADY_LICENSE_UNVERIFIED))

    market_state = _mapping(evidence.get("market_state"))
    for field_name, code in (
        ("listing", CN_DATAREADY_LISTING_HISTORY_MISSING),
        ("delisting", CN_DATAREADY_DELISTING_HISTORY_MISSING),
        ("risk_warning", CN_DATAREADY_RISK_WARNING_HISTORY_MISSING),
        ("suspension", CN_DATAREADY_SUSPENSION_HISTORY_MISSING),
    ):
        history_blocker = _history_blocker(market_state, field_name, code)
        if history_blocker is not None:
            blockers.append(history_blocker)

    corporate_actions = _mapping(evidence.get("corporate_actions"))
    if (
        corporate_actions.get("covered") is not True
        or corporate_actions.get("available_time") is not True
    ):
        blockers.append(
            blocker(CN_DATAREADY_CORPORATE_ACTION_VISIBILITY_MISSING)
        )
    adjustments = _mapping(evidence.get("adjustments"))
    if (
        adjustments.get("raw_price_preserved") is not True
        or adjustments.get("factor_versioned") is not True
        or adjustments.get("available_time") is not True
    ):
        blockers.append(blocker(CN_DATAREADY_ADJUSTMENT_VISIBILITY_MISSING))

    resolved_blockers = dedupe_blockers(blockers)
    return CNDataReadModel(
        status="blocked" if resolved_blockers else "pass",
        decision="blocked" if resolved_blockers else "research_only",
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        manifest_sha256=ensure_sha256_checksum(
            manifest_sha256,
            "manifest_sha256",
        ),
        common_date=common_date,
        security_count=security_count,
        expected_security_count=expected_count,
        coverage_ratio=coverage_ratio,
        blockers=resolved_blockers,
    )


def _history_blocker(
    market_state: Mapping[str, Any],
    field_name: str,
    code: str,
) -> DataReadinessBlocker | None:
    value = _mapping(market_state.get(field_name))
    if value.get("covered") is True and value.get("available_time") is True:
        return None
    return blocker(code)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _ratio(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if 0 <= parsed <= 1 else 0.0


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"timestamp_must_be_timezone_aware:{field_name}")
    return value.astimezone(timezone.utc)
