"""Minimal asset-neutral shared kernel."""

from quant_shared.core.contracts import VersionedContract, validate_contract_version
from quant_shared.core.identity import StableIdentity, derive_identity, validate_id
from quant_shared.core.serialization import (
    canonical_json_bytes,
    canonical_json_dumps,
    canonical_payload_hash,
    sha256_hex,
)
from quant_shared.core.time import ensure_utc, isoformat_utc, utc_now

__all__ = [
    "StableIdentity",
    "VersionedContract",
    "canonical_json_bytes",
    "canonical_json_dumps",
    "canonical_payload_hash",
    "derive_identity",
    "ensure_utc",
    "isoformat_utc",
    "sha256_hex",
    "utc_now",
    "validate_contract_version",
    "validate_id",
]
