from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from quant_shared.core.serialization import canonical_payload_hash
from quant_shared.core.time import ensure_utc


BTC_ARTIFACT_SCHEMA_VERSION = "btc_artifact_schema_v1"
BTC_REQUIRED_ARTIFACT_FIELDS: tuple[str, ...] = (
    "status",
    "decision",
    "blockers",
    "warnings",
    "generated_at",
    "as_of_utc",
    "artifact_hash",
    "input_hashes",
)


def apply_btc_artifact_schema(
    payload: Mapping[str, Any],
    *,
    decision: str,
    generated_at_utc: datetime,
    as_of_utc: datetime,
    blockers: list[str] | None = None,
    warnings: list[str] | None = None,
    input_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.pop("artifact_hash", None)
    normalized["btc_artifact_schema_version"] = BTC_ARTIFACT_SCHEMA_VERSION
    normalized["decision"] = decision
    normalized["blockers"] = list(blockers if blockers is not None else normalized.get("blockers", []))
    normalized["warnings"] = list(warnings if warnings is not None else normalized.get("warnings", []))
    normalized["generated_at"] = ensure_utc(generated_at_utc).isoformat()
    normalized["as_of_utc"] = ensure_utc(as_of_utc).isoformat()
    normalized["input_hashes"] = dict(input_hashes if input_hashes is not None else normalized.get("input_hashes", {}))
    normalized["artifact_hash"] = stable_payload_hash(normalized)
    return normalized


def validate_btc_artifact_schema(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for field_name in BTC_REQUIRED_ARTIFACT_FIELDS:
        if field_name not in payload:
            blockers.append(f"btc_artifact_schema_field_missing:{field_name}")
    if "blockers" in payload and not isinstance(payload["blockers"], list):
        blockers.append("btc_artifact_schema_blockers_not_list")
    if "warnings" in payload and not isinstance(payload["warnings"], list):
        blockers.append("btc_artifact_schema_warnings_not_list")
    if "input_hashes" in payload and not isinstance(payload["input_hashes"], dict):
        blockers.append("btc_artifact_schema_input_hashes_not_dict")
    if "artifact_hash" in payload and not _looks_like_sha256(str(payload["artifact_hash"])):
        blockers.append("btc_artifact_schema_artifact_hash_invalid")
    for time_field in ("generated_at", "as_of_utc"):
        if time_field in payload:
            try:
                ensure_utc(datetime.fromisoformat(str(payload[time_field])))
            except ValueError:
                blockers.append(f"btc_artifact_schema_datetime_invalid:{time_field}")
    if not str(payload.get("status", "")):
        blockers.append("btc_artifact_schema_status_empty")
    if not str(payload.get("decision", "")):
        blockers.append("btc_artifact_schema_decision_empty")
    return _dedupe(blockers)


def stable_payload_hash(payload: Any) -> str:
    return canonical_payload_hash(payload)


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
