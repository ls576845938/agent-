from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from quant_shared.core.contracts import validate_contract_version
from quant_shared.core.identity import validate_id
from quant_shared.core.time import ensure_utc, isoformat_utc
from quant_shared.evidence import EvidenceReference, FreshnessAssessment


@dataclass(frozen=True)
class BlockerView:
    code: str
    owner: str
    next_action: str
    detail: str = ""
    contract_version: str = "shared_blocker_view_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", validate_id(self.code, field_name="code"))
        if not self.owner.strip() or not self.next_action.strip():
            raise ValueError("blocker owner and next_action are required")
        validate_contract_version(self.contract_version, "shared_blocker_view_v2")


@dataclass(frozen=True)
class ReadModelSnapshot:
    snapshot_id: str
    domain_id: str
    generated_at_utc: datetime
    code_commit: str
    data_version: str
    status: str
    decision: str
    freshness: FreshnessAssessment
    blockers: Sequence[BlockerView] = ()
    evidence: Sequence[EvidenceReference] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "shared_read_model_snapshot_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", validate_id(self.snapshot_id, field_name="snapshot_id"))
        object.__setattr__(self, "domain_id", validate_id(self.domain_id, field_name="domain_id"))
        object.__setattr__(self, "generated_at_utc", ensure_utc(self.generated_at_utc))
        for field_name in ("code_commit", "data_version", "status", "decision"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.status == "pass" and (self.blockers or self.freshness.status != "pass"):
            raise ValueError("passing read model requires clean blockers and freshness")
        validate_contract_version(self.contract_version, "shared_read_model_snapshot_v2")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.contract_version,
            "snapshot_id": self.snapshot_id,
            "domain_id": self.domain_id,
            "generated_at_utc": isoformat_utc(self.generated_at_utc),
            "code_commit": self.code_commit,
            "data_version": self.data_version,
            "status": self.status,
            "decision": self.decision,
            "freshness": {
                "status": self.freshness.status,
                "blockers": list(self.freshness.blockers),
                "missing_count": self.freshness.missing_count,
                "stale_count": self.freshness.stale_count,
                "future_count": self.freshness.future_count,
                "code_commit_mismatch_count": self.freshness.code_commit_mismatch_count,
                "dependency_newer_count": self.freshness.dependency_newer_count,
            },
            "blockers": [
                {
                    "code": value.code,
                    "owner": value.owner,
                    "next_action": value.next_action,
                    "detail": value.detail,
                }
                for value in self.blockers
            ],
            "evidence": [
                {
                    "evidence_id": value.evidence_id,
                    "path": value.path,
                    "sha256": value.sha256,
                    "schema_version": value.schema_version,
                    "generated_at_utc": isoformat_utc(value.generated_at_utc),
                    "code_commit": value.code_commit,
                }
                for value in self.evidence
            ],
            "metadata": dict(self.metadata),
        }


class ReadModelProjector(Protocol):
    def project(self, records: Sequence[Mapping[str, Any]]) -> ReadModelSnapshot: ...
