from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from quant_shared.core.contracts import validate_contract_version
from quant_shared.core.identity import validate_id
from quant_shared.core.time import ensure_utc


@dataclass(frozen=True)
class FreshnessSource:
    source_id: str
    available: bool
    generated_at_utc: datetime | None
    code_commit: str = ""
    dependency_generated_at_utc: Sequence[datetime] = ()
    contract_version: str = "shared_freshness_source_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", validate_id(self.source_id, field_name="source_id"))
        if self.generated_at_utc is not None:
            object.__setattr__(self, "generated_at_utc", ensure_utc(self.generated_at_utc))
        object.__setattr__(
            self,
            "dependency_generated_at_utc",
            tuple(ensure_utc(value) for value in self.dependency_generated_at_utc),
        )
        validate_contract_version(self.contract_version, "shared_freshness_source_v2")


@dataclass(frozen=True)
class FreshnessAssessment:
    status: str
    blockers: tuple[str, ...]
    missing_count: int
    stale_count: int
    future_count: int
    code_commit_mismatch_count: int
    dependency_newer_count: int
    contract_version: str = "shared_freshness_assessment_v2"

    def __post_init__(self) -> None:
        if self.status not in {"pass", "blocked"}:
            raise ValueError("freshness status must be pass or blocked")
        for field_name in (
            "missing_count",
            "stale_count",
            "future_count",
            "code_commit_mismatch_count",
            "dependency_newer_count",
        ):
            if int(getattr(self, field_name)) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.status == "pass" and self.blockers:
            raise ValueError("passing freshness assessment cannot have blockers")
        validate_contract_version(self.contract_version, "shared_freshness_assessment_v2")


def assess_freshness(
    sources: Sequence[FreshnessSource],
    *,
    current_head: str,
    evaluated_at_utc: datetime,
    max_age: timedelta,
) -> FreshnessAssessment:
    evaluated_at = ensure_utc(evaluated_at_utc)
    blockers: list[str] = []
    missing = stale = future = mismatch = dependency_newer = 0
    for source in sources:
        if not source.available or source.generated_at_utc is None:
            missing += 1
            blockers.append(f"missing_source:{source.source_id}")
            continue
        generated_at = source.generated_at_utc
        if generated_at > evaluated_at:
            future += 1
            blockers.append(f"future_source:{source.source_id}")
        elif evaluated_at - generated_at > max_age:
            stale += 1
            blockers.append(f"stale_source:{source.source_id}")
        if source.code_commit and source.code_commit != current_head:
            mismatch += 1
            blockers.append(f"commit_mismatch:{source.source_id}")
        if any(dependency_at > generated_at for dependency_at in source.dependency_generated_at_utc):
            dependency_newer += 1
            blockers.append(f"dependency_newer:{source.source_id}")
    return FreshnessAssessment(
        status="blocked" if blockers else "pass",
        blockers=tuple(blockers),
        missing_count=missing,
        stale_count=stale,
        future_count=future,
        code_commit_mismatch_count=mismatch,
        dependency_newer_count=dependency_newer,
    )
