"""Pure entry-only conditional policy; no position, risk, OMS or broker imports."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .model import digest
from .state_v2 import MarketStateV2, STATE_VERSION


POLICY_VERSION = "entry_path_efficiency_72h_v1"


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("entry_policy_target_invalid") from exc
    if not result.is_finite():
        raise ValueError("entry_policy_target_invalid")
    return result


@dataclass(frozen=True)
class EntryOnlyPolicyV1:
    state_definition_hash: str
    source_binding_hash: str
    source_evidence_hash: str
    enabled: bool = False
    policy_id: str = "market_state_entry_admission"
    policy_version: str = POLICY_VERSION
    state_definition_version: str = STATE_VERSION
    primary_horizon: int = 72
    minimum_path_efficiency: Decimal = Decimal("0.20")

    def __post_init__(self) -> None:
        if (self.policy_id != "market_state_entry_admission" or self.policy_version != POLICY_VERSION
                or self.state_definition_version != STATE_VERSION
                or type(self.primary_horizon) is not int or self.primary_horizon != 72
                or not isinstance(self.enabled, bool)):
            raise ValueError("entry_policy_contract_invalid")
        for value in (self.state_definition_hash, self.source_binding_hash, self.source_evidence_hash):
            if (not isinstance(value, str) or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)):
                raise ValueError("entry_policy_hash_invalid")
        threshold = _decimal(self.minimum_path_efficiency)
        if threshold != Decimal("0.20"):
            raise ValueError("entry_policy_threshold_not_precommitted")
        object.__setattr__(self, "minimum_path_efficiency", threshold)

    @property
    def policy_hash(self) -> str:
        payload = asdict(self)
        payload["minimum_path_efficiency"] = str(self.minimum_path_efficiency)
        return digest(payload)


@dataclass(frozen=True)
class EntryPolicyDecision:
    original_target: Decimal
    effective_target: Decimal
    applied: bool
    reason: str
    policy_id: str
    policy_version: str
    policy_hash: str
    state_content_hash: str


def evaluate_entry_policy(*, policy: EntryOnlyPolicyV1, state: MarketStateV2,
                          current_position: Decimal, original_target: Decimal) -> EntryPolicyDecision:
    current = _decimal(current_position)
    original = _decimal(original_target)

    def result(target: Decimal, applied: bool, reason: str) -> EntryPolicyDecision:
        return EntryPolicyDecision(original, target, applied, reason, policy.policy_id,
                                   policy.policy_version, policy.policy_hash, state.content_hash)

    if not policy.enabled:
        return result(original, False, "policy_disabled")
    # This branch is intentionally before every state/binding check.  The policy
    # cannot obstruct reductions, exits, reversal-to-close, or protection work.
    if current != 0:
        return result(original, False, "existing_position_not_entry")
    if original == 0:
        return result(original, False, "no_new_entry")
    if state.definition_version != policy.state_definition_version or state.definition_hash != policy.state_definition_hash:
        return result(Decimal("0"), True, "state_definition_mismatch")
    if state.source_binding_hash != policy.source_binding_hash:
        return result(Decimal("0"), True, "state_source_binding_mismatch")
    if state.status != "observed":
        return result(Decimal("0"), True, "state_unknown")
    efficiency = state.path_efficiency_by_horizon.get(str(policy.primary_horizon))
    if efficiency is None:
        return result(Decimal("0"), True, "primary_horizon_missing")
    if _decimal(efficiency) < policy.minimum_path_efficiency:
        return result(Decimal("0"), True, "path_efficiency_below_threshold")
    return result(original, False, "entry_allowed")
