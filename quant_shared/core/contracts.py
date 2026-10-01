from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VersionedContract(Protocol):
    """Structural boundary implemented by every shared contract."""

    contract_version: str


def validate_contract_version(value: str, expected: str) -> str:
    normalized = str(value).strip()
    if normalized != expected:
        raise ValueError(f"contract_version must be {expected}")
    return normalized
