from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_crypto.application.btc_operator_contract_v2 import build_operator_contract_v2
from quant_crypto.application.runtime_risk_guardian import (
    GuardianConfig,
    GuardianRecoveryRejected,
    GuardianObservation,
    InMemoryGuardianLatchStore,
    RuntimeRiskGuardian,
    RuntimeRiskGuardianSupervisor,
)


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _observation(**overrides: object) -> GuardianObservation:
    value: dict[str, object] = {
        "source_head": "a" * 40,
        "account_identity": "account-hash",
        "session_id": "run-1",
        "key_namespace": "quant-system.okx-demo.trade",
        "client_order_namespace": "btcDP123456789",
        "owner_identity": "runtime-owner",
        "epoch": 4,
        "observed_at_utc": NOW,
        "reference_time_utc": NOW,
        "heartbeat_at_utc": NOW,
        "heartbeat_healthy": True,
        "broker_truth_fresh": True,
        "facts_fresh": True,
        "reconciliation_passed": True,
        "ledger_reconciled": True,
        "snapshot_match": True,
        "funding_reconciled": True,
        "positions": [],
        "cash": {"equity": 1000.0, "consistent": True},
        "pnl": {"daily": 0.0, "drawdown": 0.0, "consistent": True},
        "exposure": {"gross": 0.0, "consistent": True},
        "open_orders": [],
        "protection_facts": {"consistent": True, "present": False},
        "positions_consistent": True,
        "cash_consistent": True,
        "pnl_consistent": True,
        "exposure_consistent": True,
        "open_orders_consistent": True,
        "protection_consistent": True,
        "evidence_identity": "fresh-observation-1",
    }
    value.update(overrides)
    return GuardianObservation(**value)


def _guardian() -> RuntimeRiskGuardian:
    return RuntimeRiskGuardian(
        GuardianConfig(
            freshness_ttl_seconds=30,
            heartbeat_ttl_seconds=30,
            max_abs_exposure=10,
            max_daily_loss=100,
            max_drawdown=100,
            max_open_orders=0,
        )
    )


def test_missing_latch_requires_explicit_healthy_bootstrap_and_stays_non_authorizing() -> None:
    store = InMemoryGuardianLatchStore()
    with RuntimeRiskGuardianSupervisor(_guardian(), store, owner_id="owner", fence_token="fence") as supervisor:
        assert supervisor.read_model()["persistence_state"] == "missing"
        decision = supervisor.guardian.evaluate(_observation(), generation=0)
        record = supervisor.bootstrap_or_recover(
            _observation(),
            operator_confirmation=True,
            expected_generation=0,
            expected_revision=0,
            recovery_evidence_identity=decision.evidence_identity,
            recovery_evidence_digest=decision.evidence_digest,
        )
        assert record.cleared
        model = supervisor.read_model()
        assert model["persistence_state"] == "cleared"
        assert model["execution_permission"] is False
        assert model["order_allowed"] is False


def test_first_nonflat_or_any_order_initializes_sticky_trip() -> None:
    store = InMemoryGuardianLatchStore()
    observation = _observation(
        positions=[{"position_side": "long", "contracts": "1"}],
        exposure={"gross": 1.0, "consistent": True},
        open_orders=[{"order_id": "open-1", "instrument_id": "BTC-USDT-SWAP", "side": "buy"}],
    )
    with RuntimeRiskGuardianSupervisor(_guardian(), store, owner_id="owner", fence_token="fence") as supervisor:
        record = supervisor.bootstrap_or_recover(
            observation,
            operator_confirmation=True,
            expected_generation=0,
            expected_revision=0,
            recovery_evidence_identity="operator-recovery-2",
            recovery_evidence_digest="f" * 64,
        )
        assert record.tripped
        assert "max_open_orders_breach" in record.reason_codes
        assert supervisor.read_model()["next_safe_action"] == "acknowledge_guardian_trip"


def test_first_nonflat_without_orders_still_initializes_tripped() -> None:
    store = InMemoryGuardianLatchStore()
    observation = _observation(
        positions=[{"position_side": "long", "contracts": "1"}],
        exposure={"gross": 1.0, "consistent": True},
    )
    with RuntimeRiskGuardianSupervisor(_guardian(), store, owner_id="owner", fence_token="fence") as supervisor:
        record = supervisor.bootstrap_or_recover(
            observation,
            operator_confirmation=True,
            expected_generation=0,
            expected_revision=0,
            recovery_evidence_identity="bootstrap-observation",
            recovery_evidence_digest="bootstrap-digest",
        )
        assert record.tripped
        assert "initial_nonflat_position" in record.reason_codes


def test_owned_quantity_matched_oco_is_protective_not_risk_increasing() -> None:
    position = {"position_side": "long", "contracts": "1"}
    protective = {
        "owner_id": "runtime-owner",
        "parent_client_order_id": "btcDP123456789",
        "algo_client_order_id": "btcDP123456789A",
        "instrument_id": "BTC-USDT-SWAP",
        "position_side": "long",
        "state": "live",
        "order_type": "oco",
        "reduce_only": True,
        "size": "1",
    }
    decision = _guardian().evaluate(
        _observation(
            positions=[position],
            exposure={"gross": 1.0, "consistent": True},
            open_orders=[protective],
            protection_facts={"consistent": True, "present": True},
        )
    )
    assert decision.passed
    assert "max_open_orders_breach" not in decision.reason_codes


def test_foreign_or_mismatched_protection_is_risk_increasing_and_trips() -> None:
    position = {"position_side": "long", "contracts": "1"}
    foreign = {
        "owner_id": "foreign-runtime",
        "parent_client_order_id": "btcDP123456789",
        "algo_client_order_id": "btcDP123456789A",
        "instrument_id": "BTC-USDT-SWAP",
        "position_side": "long",
        "state": "live",
        "order_type": "oco",
        "reduce_only": True,
        "size": "1",
    }
    decision = _guardian().evaluate(_observation(positions=[position], open_orders=[foreign]))
    assert decision.passed is False
    assert "protective_order_owner_missing" in decision.reason_codes


def test_ack_alone_never_clears_and_recovery_requires_newer_health_observation() -> None:
    store = InMemoryGuardianLatchStore()
    with RuntimeRiskGuardianSupervisor(_guardian(), store, owner_id="owner", fence_token="fence") as supervisor:
        trip = supervisor.trip(_observation(exposure={"gross": 11.0, "consistent": True}))
        supervisor.acknowledge(
            generation=trip.generation,
            evidence_identity=trip.evidence_identity,
            evidence_digest=trip.evidence_digest,
            acknowledgement_id="ack-1",
        )
        stale_observation = _observation()
        stale_decision = supervisor.guardian.evaluate(stale_observation, generation=trip.generation)
        with pytest.raises(GuardianRecoveryRejected, match="current_health_observation_stale"):
            supervisor.bootstrap_or_recover(
                stale_observation,
                operator_confirmation=True,
                expected_generation=trip.generation,
                expected_revision=2,
                recovery_evidence_identity=stale_decision.evidence_identity,
                recovery_evidence_digest=stale_decision.evidence_digest,
            )
        healthy_observation = _observation(
            observed_at_utc=NOW + timedelta(seconds=1),
            reference_time_utc=NOW + timedelta(seconds=1),
            heartbeat_at_utc=NOW + timedelta(seconds=1),
            evidence_identity="new-health",
        )
        healthy_decision = supervisor.guardian.evaluate(healthy_observation, generation=trip.generation)
        recovered = supervisor.bootstrap_or_recover(
            healthy_observation,
            operator_confirmation=True,
            expected_generation=trip.generation,
            expected_revision=2,
            recovery_evidence_identity=healthy_decision.evidence_identity,
            recovery_evidence_digest=healthy_decision.evidence_digest,
        )
        assert recovered.cleared


def _operator_status(*, active: bool, cancel_only: bool, mode: str, contracts: str = "1") -> dict:
    return {
        "source_head": "a" * 40,
        "runtime_identity": "run-1",
        "state_revision": 4,
        "state_digest": "b" * 64,
        "as_of_utc": "2026-08-24T12:00:00Z",
        "runtime": {"status": "running" if active else "stopped", "active": active, "opening": False, "cancel_only": cancel_only},
        "risk_control": {"mode": mode},
        "exchange": {"positions": [{"position_side": "long", "contracts": contracts}]},
        "protective_capabilities": {
            "stop_and_flatten": {"allowed": True, "reduction_proof": True, "effect": "decrease"},
            "emergency_reduce_only_exit": {"allowed": True, "reduction_proof": True, "effect": "decrease"},
        },
        "position_facts_known": True,
        "position_nonflat": True,
        "safety": {name: False for name in ("promotion_eligible", "paper", "live", "private", "order", "real_order", "transfer", "withdraw")},
        "start_capability": {"ready": False, "blockers": ["runtime_not_started"]},
    }


def test_exit_actions_are_state_mutually_exclusive_and_flat_unknown_are_denied() -> None:
    running = build_operator_contract_v2(_operator_status(active=True, cancel_only=False, mode="RUNNING"))
    assert running is not None
    assert running.action_map["stop_and_flatten"].allowed is True
    assert running.action_map["emergency_reduce_only_exit"].allowed is False
    frozen = build_operator_contract_v2(_operator_status(active=False, cancel_only=True, mode="FROZEN_UNKNOWN"))
    assert frozen is not None
    assert frozen.action_map["stop_and_flatten"].allowed is False
    assert frozen.action_map["emergency_reduce_only_exit"].allowed is True
    opening = _operator_status(active=False, cancel_only=True, mode="FROZEN_UNKNOWN")
    opening["runtime"]["opening"] = True
    opening_contract = build_operator_contract_v2(opening)
    assert opening_contract is not None
    assert opening_contract.action_map["emergency_reduce_only_exit"].allowed is False
    flat = build_operator_contract_v2({**_operator_status(active=False, cancel_only=True, mode="FROZEN_UNKNOWN"), "position_nonflat": False, "exchange": {"positions": []}})
    assert flat is not None
    assert flat.action_map["stop_and_flatten"].allowed is False
    assert flat.action_map["emergency_reduce_only_exit"].allowed is False
