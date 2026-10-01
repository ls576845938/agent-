"""Pure binding for an optional market-state entry policy attachment.

The attachment extends a frozen base strategy package/spec; it does not mutate
the package, register a candidate, or grant a runtime permission.  Consumers
must validate it against their own reconstructed base binding before use.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

from quant_shared.trend_environment.entry_policy import EntryOnlyPolicyV1, POLICY_VERSION
from quant_shared.trend_environment.model import digest
from quant_shared.trend_environment.state_v2 import (
    STATE_VERSION,
    StateDefinitionV2,
    StateSourceBinding,
)


ATTACHMENT_SCHEMA = "market_state_entry_policy_attachment_v1"
SAFETY_KEYS = (
    "demo_control_enabled", "execution_permission", "runtime_observed", "promotion", "paper", "live",
    "private", "order", "real_order", "transfer", "withdraw",
)
EVIDENCE_REF = re.compile(r"^[0-9a-f]{40}:(\.agent/market_state_evidence/[A-Za-z0-9_.-]+\.json)$")


def _hash(value: str, length: int, reason: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(reason)
    return value


@dataclass(frozen=True)
class MarketPolicyBaseBinding:
    strategy_id: str
    strategy_version: str
    source_head: str
    params_hash: str
    data_version: str
    instrument: str
    bar_size: str
    settlement_currency: str
    base_package_hash: str
    base_spec_hash: str
    cost_contract_hash: str
    time_contract_hash: str

    def __post_init__(self) -> None:
        for value in (self.strategy_id, self.strategy_version, self.data_version,
                      self.instrument, self.bar_size, self.settlement_currency):
            if not isinstance(value, str) or not value or value == "latest":
                raise ValueError("market_policy_base_identity_invalid")
        _hash(self.source_head, 40, "market_policy_base_head_invalid")
        for value in (self.params_hash, self.base_package_hash, self.base_spec_hash,
                      self.cost_contract_hash, self.time_contract_hash):
            _hash(value, 64, "market_policy_base_hash_invalid")

    @property
    def binding_hash(self) -> str:
        return digest(asdict(self))


def build_market_policy_attachment(*, base: MarketPolicyBaseBinding,
                                   definition: StateDefinitionV2,
                                   policy: EntryOnlyPolicyV1,
                                   source: StateSourceBinding,
                                   evidence_ref: str,
                                   evidence_sha256: str) -> dict[str, Any]:
    if policy.state_definition_hash != definition.definition_hash:
        raise ValueError("market_policy_definition_binding_mismatch")
    if policy.source_binding_hash != source.binding_hash or base.data_version != source.data_version:
        raise ValueError("market_policy_source_binding_mismatch")
    if policy.source_evidence_hash != evidence_sha256:
        raise ValueError("market_policy_evidence_binding_mismatch")
    match = EVIDENCE_REF.fullmatch(evidence_ref) if isinstance(evidence_ref, str) else None
    if (match is None or ".." in PurePosixPath(match.group(1)).parts
            or "\\" in evidence_ref):
        raise ValueError("market_policy_evidence_ref_invalid")
    _hash(evidence_sha256, 64, "market_policy_evidence_hash_invalid")
    payload = {
        "schema_version": ATTACHMENT_SCHEMA,
        "usage": "research_replay_entry_only",
        "base_strategy": {**asdict(base), "binding_hash": base.binding_hash},
        "market_state": {
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
        },
        "entry_policy": {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "policy_hash": policy.policy_hash,
            "enabled": policy.enabled,
            "primary_horizon": policy.primary_horizon,
            "minimum_path_efficiency": str(policy.minimum_path_efficiency),
        },
        "source": {**asdict(source), "binding_hash": source.binding_hash},
        "evidence": {"ref": evidence_ref, "sha256": evidence_sha256},
        "safety": dict.fromkeys(SAFETY_KEYS, False),
    }
    return {**payload, "attachment_hash": digest(payload)}


def validate_market_policy_attachment(attachment: Mapping[str, Any] | None, *,
                                      base: MarketPolicyBaseBinding,
                                      definition: StateDefinitionV2,
                                      policy: EntryOnlyPolicyV1,
                                      source: StateSourceBinding,
                                      attachment_required: bool = True) -> list[str]:
    if attachment is None:
        return ["market_policy_attachment_missing"] if attachment_required else []
    errors: list[str] = []
    try:
        value = dict(attachment)
        if value.get("schema_version") != ATTACHMENT_SCHEMA or value.get("usage") != "research_replay_entry_only":
            errors.append("market_policy_attachment_schema_unsupported")
        expected = build_market_policy_attachment(
            base=base,
            definition=definition,
            policy=policy,
            source=source,
            evidence_ref=str((value.get("evidence") or {}).get("ref") or ""),
            evidence_sha256=str((value.get("evidence") or {}).get("sha256") or ""),
        )
        if value.get("base_strategy") != expected["base_strategy"]:
            errors.append("market_policy_base_binding_mismatch")
        if value.get("market_state") != expected["market_state"]:
            errors.append("market_policy_definition_binding_mismatch")
        if value.get("entry_policy") != expected["entry_policy"]:
            errors.append("market_policy_contract_binding_mismatch")
        if value.get("source") != expected["source"]:
            errors.append("market_policy_source_binding_mismatch")
        if value.get("evidence") != expected["evidence"]:
            errors.append("market_policy_evidence_binding_mismatch")
        if value.get("safety") != expected["safety"]:
            errors.append("market_policy_safety_invalid")
        unsigned = dict(value)
        observed_hash = unsigned.pop("attachment_hash", None)
        if observed_hash != digest(unsigned):
            errors.append("market_policy_attachment_hash_mismatch")
        if value.get("attachment_hash") != expected["attachment_hash"]:
            errors.append("market_policy_attachment_unexpected")
        if ((value.get("market_state") or {}).get("definition_version") != STATE_VERSION
                or (value.get("entry_policy") or {}).get("policy_version") != POLICY_VERSION):
            errors.append("market_policy_version_unsupported")
    except (AttributeError, KeyError, TypeError, ValueError):
        errors.append("market_policy_attachment_malformed")
    return sorted(set(errors))
