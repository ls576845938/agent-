from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from quant_shared.core.contracts import validate_contract_version
from quant_shared.core.identity import validate_id
from quant_shared.core.serialization import canonical_payload_hash
from quant_shared.core.time import ensure_utc


def _validate_sha256(value: str, *, field_name: str) -> str:
    normalized = str(value).lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field_name} must be a 64-character lowercase sha256")
    return normalized


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    path: str
    sha256: str
    schema_version: str
    generated_at_utc: datetime
    code_commit: str
    contract_version: str = "shared_evidence_reference_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", validate_id(self.evidence_id, field_name="evidence_id"))
        if not str(self.path).strip() or not str(self.schema_version).strip():
            raise ValueError("path and schema_version are required")
        object.__setattr__(self, "path", str(self.path).replace("\\", "/"))
        object.__setattr__(self, "sha256", _validate_sha256(self.sha256, field_name="sha256"))
        object.__setattr__(self, "generated_at_utc", ensure_utc(self.generated_at_utc))
        if not str(self.code_commit).strip():
            raise ValueError("code_commit is required")
        validate_contract_version(self.contract_version, "shared_evidence_reference_v2")


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    created_at_utc: datetime
    references: Sequence[EvidenceReference]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "shared_evidence_bundle_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", validate_id(self.bundle_id, field_name="bundle_id"))
        object.__setattr__(self, "created_at_utc", ensure_utc(self.created_at_utc))
        references = tuple(self.references)
        if not references:
            raise ValueError("evidence bundle requires at least one reference")
        if len({reference.evidence_id for reference in references}) != len(references):
            raise ValueError("evidence reference ids must be unique")
        object.__setattr__(self, "references", references)
        object.__setattr__(self, "metadata", dict(self.metadata))
        validate_contract_version(self.contract_version, "shared_evidence_bundle_v2")

    @property
    def fingerprint(self) -> str:
        return canonical_payload_hash(self)
