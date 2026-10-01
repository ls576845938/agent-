from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from quant_shared.core.contracts import validate_contract_version
from quant_shared.core.serialization import canonical_payload_hash


ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def validate_id(value: str, *, field_name: str = "id") -> str:
    normalized = str(value).strip()
    if not ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must match {ID_PATTERN.pattern}")
    return normalized


@dataclass(frozen=True)
class StableIdentity:
    namespace: str
    value: str
    contract_version: str = "shared_stable_identity_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", validate_id(self.namespace, field_name="namespace"))
        object.__setattr__(self, "value", validate_id(self.value, field_name="value"))
        validate_contract_version(self.contract_version, "shared_stable_identity_v2")

    @property
    def qualified(self) -> str:
        return f"{self.namespace}:{self.value}"


def derive_identity(namespace: str, payload: Any) -> StableIdentity:
    return StableIdentity(namespace=namespace, value=canonical_payload_hash(payload))
