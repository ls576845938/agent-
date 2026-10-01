from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quant_crypto.application.btc_demo_start_attempt import (
    StartAttemptBinding,
    account_identity_hash,
    build_effective_policy,
)


HEAD = "a" * 40
ACCOUNT = account_identity_hash("synthetic-demo-account")
NOW = datetime(2026, 8, 25, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _binding(*, profile: str = "stress_3x") -> StartAttemptBinding:
    _, digest = build_effective_policy(
        source_head=HEAD,
        runtime_identity="runtime:synthetic-01",
        risk_profile=profile,
        expected_leverage="3" if profile == "stress_3x" else "1",
        account_identity_hash_value=ACCOUNT,
        instrument_id="BTC-USDT-SWAP",
        margin_mode="isolated",
        order_contracts="0.01",
        max_net_contracts="0.01",
        max_notional_usdt="10",
        protection_policy={"policy_id": "approved", "version": "1"},
    )
    return StartAttemptBinding(
        parent_operation_id="outer-01",
        inner_operation_id="inner-01",
        attempt_id="attempt-01",
        runtime_identity="runtime:synthetic-01",
        source_head=HEAD,
        effective_policy_digest=digest,
        risk_profile=profile,
        expected_leverage="3" if profile == "stress_3x" else "1",
        account_identity_hash=ACCOUNT,
        created_at_utc=NOW,
        updated_at_utc=NOW,
    )


def test_policy_digest_is_server_bound_and_changes_with_profile() -> None:
    stress = _binding()
    baseline = _binding(profile="baseline_1x")
    assert stress.to_dict()["account_identity_hash"] == ACCOUNT
    assert stress.to_dict()["effective_policy_digest"] != baseline.to_dict()["effective_policy_digest"]


def test_missing_current_identity_projects_historical_fail_closed() -> None:
    projected = _binding().with_projection(current_identity=None)
    assert projected.current_attempt is False
    assert projected.historical is True
    assert "runtime_identity_changed" in projected.historical_reason_codes


def test_same_identity_remains_current() -> None:
    binding = _binding()
    projected = binding.with_projection(
        current_identity={
            "runtime_identity": binding.runtime_identity,
            "source_head": binding.source_head,
            "effective_policy_digest": binding.effective_policy_digest,
            "risk_profile": binding.risk_profile,
            "expected_leverage": binding.expected_leverage,
            "account_identity_hash": binding.account_identity_hash,
        }
    )
    assert projected.current_attempt is True
    assert projected.historical is False


def test_historical_and_current_flags_cannot_be_forged() -> None:
    with pytest.raises(ValueError, match="current_historical_conflict"):
        payload = _binding().to_dict()
        payload.pop("schema_version", None)
        StartAttemptBinding(
            **{
                **payload,
                "current_attempt": True,
                "historical": True,
            }
        )
