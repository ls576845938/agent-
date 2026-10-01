from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant_shared.trend_environment.entry_policy import (
    EntryOnlyPolicyV1,
    evaluate_entry_policy,
)
from quant_shared.trend_environment.state_v2 import MarketStateV2


def state(*, status="observed", efficiency=.3, definition_hash="d" * 64,
          source_binding_hash="a" * 64) -> MarketStateV2:
    payload = dict(
        asset="BTC-USDT-SWAP", decision_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        cutoff_time=datetime(2025, 1, 1, tzinfo=timezone.utc), status=status,
        reasons=() if status == "observed" else ("warmup",), direction_score=.2,
        direction_label="up", normalized_trend_strength=.4,
        path_efficiency_by_horizon={"24": .25, "72": efficiency, "168": .2},
        multi_scale_agreement=2 / 3, bar_volatility=.01,
        annualized_volatility=.2, volatility_relative_position=.4,
        volatility_expansion_ratio=1.0, volatility_regime="stable",
        shock_score=.5, direction_persistence=.8, switching_frequency=.1,
        optional_inputs={"funding":{"status":"missing","value":None},
                         "open_interest":{"status":"missing","value":None},
                         "depth":{"status":"missing","value":None}},
        definition_version="market_state_descriptive_v2", definition_hash=definition_hash,
        source_binding_hash=source_binding_hash, input_hash="i" * 64,
        cache_key="c" * 64, content_hash="h" * 64,
    )
    return MarketStateV2(**payload)


def policy(*, enabled=True, definition_hash="d" * 64,
           source_binding_hash="a" * 64) -> EntryOnlyPolicyV1:
    return EntryOnlyPolicyV1(
        enabled=enabled, state_definition_hash=definition_hash,
        source_binding_hash=source_binding_hash, source_evidence_hash="e" * 64,
    )


def test_default_disabled_and_existing_position_never_change_target():
    untouched = evaluate_entry_policy(policy=policy(enabled=False), state=state(efficiency=.01),
                                      current_position=Decimal("0"), original_target=Decimal("1"))
    assert untouched.effective_target == Decimal("1")
    assert untouched.applied is False
    for target in (Decimal("0"), Decimal(".5"), Decimal("-1")):
        decision = evaluate_entry_policy(policy=policy(), state=state(status="unknown"),
                                         current_position=Decimal("1"), original_target=target)
        assert decision.effective_target == target
        assert decision.applied is False
        assert decision.reason == "existing_position_not_entry"


def test_only_flat_new_entry_is_rejected_for_low_or_unknown_state():
    low = evaluate_entry_policy(policy=policy(), state=state(efficiency=.1999),
                                current_position=Decimal("0"), original_target=Decimal("1"))
    unknown = evaluate_entry_policy(policy=policy(), state=state(status="unknown"),
                                    current_position=Decimal("0"), original_target=Decimal("-1"))
    allowed = evaluate_entry_policy(policy=policy(), state=state(efficiency=.2),
                                    current_position=Decimal("0"), original_target=Decimal("1"))
    assert (low.effective_target, low.applied, low.reason) == (Decimal("0"), True, "path_efficiency_below_threshold")
    assert (unknown.effective_target, unknown.applied, unknown.reason) == (Decimal("0"), True, "state_unknown")
    assert (allowed.effective_target, allowed.applied, allowed.reason) == (Decimal("1"), False, "entry_allowed")


def test_binding_mismatch_fails_closed_only_for_new_entry():
    mismatch = evaluate_entry_policy(policy=policy(), state=state(definition_hash="x" * 64),
                                     current_position=Decimal("0"), original_target=Decimal("1"))
    assert mismatch.effective_target == 0
    assert mismatch.reason == "state_definition_mismatch"
    exit_decision = evaluate_entry_policy(policy=policy(), state=state(definition_hash="x" * 64),
                                          current_position=Decimal("1"), original_target=Decimal("0"))
    assert exit_decision.effective_target == 0
    assert exit_decision.reason == "existing_position_not_entry"


def test_frozen_policy_version_cannot_silently_change_horizon_or_hash_type():
    with pytest.raises(ValueError, match="entry_policy_contract_invalid"):
        EntryOnlyPolicyV1(enabled=True, primary_horizon=24,
                          state_definition_hash="d" * 64,
                          source_binding_hash="a" * 64,
                          source_evidence_hash="e" * 64)
    with pytest.raises(ValueError, match="entry_policy_hash_invalid"):
        EntryOnlyPolicyV1(enabled=True, state_definition_hash=None,
                          source_binding_hash="a" * 64,
                          source_evidence_hash="e" * 64)
