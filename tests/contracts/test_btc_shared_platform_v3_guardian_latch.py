from __future__ import annotations

import ast
import dataclasses
import inspect
import math
from datetime import datetime, timedelta, timezone

import pytest

from quant_crypto.application.runtime_risk_guardian import (
    FileGuardianLatchStore,
    GuardianConfig,
    GuardianConcurrentWriterError,
    GuardianLatchRecord,
    GuardianObservation,
    GuardianPersistenceError,
    GuardianRecoveryRejected,
    GuardianStaleWriterError,
    InMemoryGuardianLatchStore,
    RuntimeRiskGuardian,
    RuntimeRiskGuardianSupervisor,
)
from quant_crypto.oms.account_risk_facts import (
    ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
    ACCOUNT_DRAWDOWN_CURRENCY,
    ACCOUNT_DRAWDOWN_SCOPE,
    build_explicit_account_drawdown_baseline,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _config(**overrides: object) -> GuardianConfig:
    values: dict[str, object] = {
        "freshness_ttl_seconds": 30.0,
        "heartbeat_ttl_seconds": 30.0,
        "max_abs_exposure": 10.0,
        "max_daily_loss": 100.0,
        "max_drawdown": 0.50,
        "max_drawdown_unit": "usdt",
        "max_open_orders": 0,
    }
    values.update(overrides)
    return GuardianConfig(**values)


def _account_drawdown_fact(observed_at: datetime) -> dict:
    account_identity = "b" * 64
    account_snapshot = "c" * 64
    return build_explicit_account_drawdown_baseline(
        authority=ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
        account_identity_hash=account_identity,
        account_scope=ACCOUNT_DRAWDOWN_SCOPE,
        currency=ACCOUNT_DRAWDOWN_CURRENCY,
        snapshot_sha256=account_snapshot,
        observed_at_utc=observed_at,
        equity_usdt="1000",
        history_complete=False,
    )


def _observation(**overrides: object) -> GuardianObservation:
    account_identity = "b" * 64
    account_snapshot = "c" * 64
    values: dict[str, object] = {
        "source_head": "a" * 40,
        "account_identity": account_identity,
        "account_snapshot_sha256": account_snapshot,
        "session_id": "session-1",
        "key_namespace": "paper-key-namespace",
        "client_order_namespace": "paper-client-namespace",
        "epoch": 1,
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
        "positions": {"BTC-USDT-SWAP": 0.0},
        "cash": {"equity": 1000.0},
        "pnl": {"daily": 0.0, "drawdown": 0.0},
        "exposure": {"gross": 0.0},
        "open_orders": [],
        "protection_facts": {"consistent": True},
        "positions_consistent": True,
        "cash_consistent": True,
        "pnl_consistent": True,
        "exposure_consistent": True,
        "open_orders_consistent": True,
        "protection_consistent": True,
        "account_facts": {"account_drawdown": _account_drawdown_fact(NOW)},
        "evidence_identity": "account-snapshot-1",
    }
    values.update(overrides)
    return GuardianObservation(**values)


def _trip(supervisor: RuntimeRiskGuardianSupervisor, **overrides: object):
    return supervisor.trip(_observation(**overrides))


def _ack(supervisor: RuntimeRiskGuardianSupervisor, decision, acknowledgement_id: str = "operator-ack-1"):
    return supervisor.acknowledge(
        generation=decision.generation,
        evidence_identity=decision.evidence_identity,
        evidence_digest=decision.evidence_digest,
        acknowledgement_id=acknowledgement_id,
    )


def test_guardian_is_deterministic_explicit_and_never_execution_permission() -> None:
    guardian = RuntimeRiskGuardian(_config())
    observation = _observation()
    first = guardian.evaluate(observation)
    assert first == guardian.evaluate(observation)
    assert first.passed is True
    payload = first.to_dict()
    for key in ("execution_permission", "order_allowed", "promotion", "paper", "live", "private", "order", "real_order", "transfer", "withdraw"):
        assert payload[key] is False


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"broker_truth_fresh": None}, "broker_truth_fresh_unknown"),
        ({"reconciliation_passed": False}, "reconciliation_failed"),
        ({"observed_at_utc": NOW - timedelta(seconds=31)}, "observation_stale"),
        ({"heartbeat_at_utc": NOW - timedelta(seconds=31)}, "heartbeat_stale"),
        ({"exposure": {"gross": 11.0}}, "max_abs_exposure_breach"),
        ({"pnl": {"daily": -101.0}}, "max_daily_loss_breach"),
        ({"open_orders": [{"id": "o1"}]}, "max_open_orders_breach"),
    ],
)
def test_unknown_stale_mismatch_and_threshold_facts_trip(change: dict[str, object], expected: str) -> None:
    decision = RuntimeRiskGuardian(_config()).evaluate(_observation(**change))
    assert decision.passed is False
    assert expected in decision.reason_codes


@pytest.mark.parametrize("facts", [{"exposure": {"gross": math.nan}}, {"pnl": {"daily": math.inf}}])
def test_nonfinite_account_facts_are_unknown_and_fail_closed(facts: dict[str, object]) -> None:
    decision = RuntimeRiskGuardian(_config()).evaluate(_observation(**facts))
    assert decision.passed is False
    assert any(code.endswith("_unknown") for code in decision.reason_codes)


def test_recursive_observation_and_config_are_immutable() -> None:
    positions = {"BTC": {"qty": 0.0}}
    observation = _observation(positions=positions)
    positions["BTC"]["qty"] = 100.0
    assert observation.positions["BTC"]["qty"] == 0.0
    with pytest.raises(TypeError):
        observation.positions["BTC"]["qty"] = 1.0
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        _config().max_open_orders = 4  # type: ignore[misc]


def test_file_lease_close_reacquire_preserves_sticky_state_and_fences_old_writer(tmp_path) -> None:
    path = tmp_path / "guardian-latch.json"
    first = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), path, owner_id="a", fence_token="fa")
    tripped = _trip(first, exposure={"gross": 11.0})
    first.close()
    rebuilt = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), FileGuardianLatchStore(path), owner_id="b", fence_token="fb")
    assert rebuilt.tripped is True
    assert rebuilt.latch is not None and rebuilt.latch.generation == 1
    assert rebuilt.latch.state_revision >= 2
    with pytest.raises(GuardianRecoveryRejected, match="operator_ack_required"):
        rebuilt.clear(_observation())
    _ack(rebuilt, tripped)
    assert rebuilt.latch is not None and rebuilt.latch.acknowledged
    with pytest.raises(GuardianStaleWriterError, match="supervisor_lease_lost"):
        first.trip(_observation(exposure={"gross": 12.0}))
    rebuilt.close()


def test_same_credentials_second_supervisor_is_rejected_immediately() -> None:
    store = InMemoryGuardianLatchStore()
    first = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa")
    with pytest.raises(GuardianConcurrentWriterError, match="latch_concurrent_writer"):
        RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa")
    first.close()
    with RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa") as second:
        _trip(second, exposure={"gross": 11.0})


def test_current_pass_can_use_new_recovery_evidence_but_runtime_identity_must_match(tmp_path) -> None:
    supervisor = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), tmp_path / "guardian-latch.json", owner_id="a", fence_token="fa")
    tripped = _trip(supervisor, exposure={"gross": 11.0})
    _ack(supervisor, tripped)
    with pytest.raises(GuardianRecoveryRejected, match="current_health_observation_stale"):
        supervisor.clear(_observation(cash={"equity": 999.0}))
    fresh = NOW + timedelta(seconds=1)
    cleared = supervisor.clear(_observation(
        evidence_identity="new-recovery-evidence",
        observed_at_utc=fresh,
        reference_time_utc=fresh,
        heartbeat_at_utc=fresh,
        account_facts={"account_drawdown": _account_drawdown_fact(fresh)},
    ))
    assert cleared.cleared is True
    assert cleared.recovery_evidence_identity == "new-recovery-evidence"
    assert cleared.recovery_evidence_digest != cleared.evidence_digest
    assert supervisor.read_model()["execution_permission"] is False
    supervisor.close()


def test_clear_rejects_runtime_identity_drift(tmp_path) -> None:
    supervisor = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), tmp_path / "guardian-latch.json", owner_id="a", fence_token="fa")
    tripped = _trip(supervisor, exposure={"gross": 11.0})
    _ack(supervisor, tripped)
    fresh = NOW + timedelta(seconds=1)
    with pytest.raises(GuardianRecoveryRejected, match="current_runtime_identity_mismatch"):
        supervisor.clear(_observation(
            session_id="session-2",
            observed_at_utc=fresh,
            reference_time_utc=fresh,
            heartbeat_at_utc=fresh,
            account_facts={"account_drawdown": _account_drawdown_fact(fresh)},
        ))
    supervisor.close()


def test_fresh_pass_without_ack_does_not_restore_and_old_generation_ack_fails() -> None:
    store = InMemoryGuardianLatchStore()
    with RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa") as supervisor:
        tripped = _trip(supervisor, exposure={"gross": 11.0})
        with pytest.raises(GuardianRecoveryRejected, match="operator_ack_required"):
            supervisor.clear(_observation())
        with pytest.raises(GuardianRecoveryRejected, match="operator_ack_generation_or_evidence_mismatch"):
            supervisor.acknowledge(generation=tripped.generation - 1, evidence_identity=tripped.evidence_identity, evidence_digest=tripped.evidence_digest, acknowledgement_id="old-ack")


def test_state_revision_blocks_reload_save_race_and_increments_every_mutation() -> None:
    store = InMemoryGuardianLatchStore()
    with RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa") as supervisor:
        tripped = _trip(supervisor, exposure={"gross": 11.0})
        initial = supervisor.latch
        assert initial is not None and initial.state_revision == 1
        stale = GuardianLatchRecord.from_dict(initial.to_dict())
        acked = _ack(supervisor, tripped)
        assert acked.state_revision == initial.state_revision + 1
        with pytest.raises(GuardianStaleWriterError, match="latch_state_revision_mismatch"):
            store.save(stale, expected_generation=initial.generation, expected_revision=initial.state_revision - 1, owner_id="a", fence_token="fa", lease=supervisor._lease)  # type: ignore[arg-type]
        fresh = NOW + timedelta(seconds=1)
        cleared = supervisor.clear(_observation(
            observed_at_utc=fresh,
            reference_time_utc=fresh,
            heartbeat_at_utc=fresh,
            account_facts={"account_drawdown": _account_drawdown_fact(fresh)},
        ))
        assert cleared.state_revision == acked.state_revision + 1


def test_closed_supervisor_cannot_write_and_new_owner_can_take_over_inmemory() -> None:
    store = InMemoryGuardianLatchStore()
    first = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa")
    first.close()
    with pytest.raises(GuardianStaleWriterError, match="supervisor_lease_lost"):
        first.acknowledge(generation=1, evidence_identity="x", evidence_digest="y", acknowledgement_id="ack")
    with RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="b", fence_token="fb") as second:
        assert second.latch is None


def test_concurrent_writer_and_persistence_failure_never_expose_clear() -> None:
    store = InMemoryGuardianLatchStore()
    with RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa") as supervisor:
        tripped = _trip(supervisor, exposure={"gross": 11.0})
        store.locked = True
        with pytest.raises(GuardianConcurrentWriterError):
            _ack(supervisor, tripped)
        store.locked = False
        _ack(supervisor, tripped)
        store.fail_next_save = True
        fresh = NOW + timedelta(seconds=1)
        with pytest.raises(GuardianPersistenceError):
            supervisor.clear(_observation(
                observed_at_utc=fresh,
                reference_time_utc=fresh,
                heartbeat_at_utc=fresh,
                account_facts={"account_drawdown": _account_drawdown_fact(fresh)},
            ))
        assert supervisor.latch is not None and supervisor.latch.tripped


def test_file_store_independent_instances_hold_os_lock_for_lifecycle(tmp_path) -> None:
    path = tmp_path / "guardian-latch.json"
    first_store = FileGuardianLatchStore(path)
    second_store = FileGuardianLatchStore(path)
    first = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), first_store, owner_id="a", fence_token="fa")
    with pytest.raises(GuardianConcurrentWriterError):
        RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), second_store, owner_id="b", fence_token="fb")
    first.close()
    second = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), second_store, owner_id="b", fence_token="fb")
    second.close()


def test_corrupt_or_missing_file_is_fail_closed_and_never_clears(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    supervisor = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), missing, owner_id="a", fence_token="fa")
    with pytest.raises(GuardianRecoveryRejected, match="latch_persistence_missing"):
        supervisor.clear(_observation())
    supervisor.close()
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not-json", encoding="utf-8")
    blocked = RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), corrupt, owner_id="a", fence_token="fa")
    assert blocked.read_model()["execution_permission"] is False
    with pytest.raises(GuardianPersistenceError):
        blocked.clear(_observation())
    blocked.close()


def test_guardian_has_no_clock_environment_network_or_execution_dependency() -> None:
    source = inspect.getsource(__import__("quant_crypto.application.runtime_risk_guardian", fromlist=["x"]))
    tree = ast.parse(source)
    imports = {(node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    forbidden = {"requests", "httpx", "socket", "quant_crypto.runtime", "broker", "exchange"}
    assert not any(name == item or name.startswith(item + ".") for name in imports for item in forbidden)
    oms_imports = {name for name in imports if name.startswith("quant_crypto.oms")}
    assert oms_imports == {"quant_crypto.oms.account_risk_facts"}
    assert "utc_now" not in source
    assert "OrderIntent" not in source
    assert "PermissionEvaluator" not in source


def test_missing_limits_are_stable_fail_closed_blockers() -> None:
    decision = RuntimeRiskGuardian().evaluate(_observation())
    assert decision.passed is False
    assert decision.healthy is False
    assert set(
        (
            "max_abs_exposure_limit_missing",
            "max_daily_loss_limit_missing",
            "max_drawdown_limit_missing",
            "max_open_orders_limit_missing",
        )
    ).issubset(decision.reason_codes)


def test_config_mapping_rejects_unknown_or_misspelled_keys() -> None:
    with pytest.raises(ValueError, match="guardian_config_unknown_key"):
        GuardianConfig.from_mapping({"max_abs_exposur": 10.0})


def test_reference_time_and_policy_inputs_are_evidence_bound() -> None:
    config = _config()
    first = RuntimeRiskGuardian(config).evaluate(_observation())
    stale = RuntimeRiskGuardian(config).evaluate(_observation(reference_time_utc=NOW + timedelta(seconds=31)))
    policy_changed = RuntimeRiskGuardian(_config(max_abs_exposure=11.0)).evaluate(_observation())
    assert stale.reason_codes != first.reason_codes
    assert stale.observation_digest != first.observation_digest
    assert stale.evidence_digest != first.evidence_digest
    assert policy_changed.observation_digest != first.observation_digest
    assert policy_changed.evidence_digest != first.evidence_digest


@pytest.mark.parametrize(
    "change",
    [
        {"total_exposure": 1.0},
        {"daily_pnl": -1.0},
        {"account_facts": {}},
        {"open_order_count": 0},
        {"facts_fresh": False},
        {"positions_consistent": False},
    ],
)
def test_effective_metrics_consistency_and_freshness_are_digest_bound(change: dict[str, object]) -> None:
    first = RuntimeRiskGuardian(_config()).evaluate(_observation())
    changed = RuntimeRiskGuardian(_config()).evaluate(_observation(**change))
    assert changed.observation_digest != first.observation_digest
    assert changed.evidence_digest != first.evidence_digest


def test_unknown_pnl_mapping_does_not_abs_sum_negative_loss() -> None:
    decision = RuntimeRiskGuardian(_config()).evaluate(_observation(pnl={"unrecognized_loss": -1000.0}))
    assert decision.passed is False
    assert "pnl_unknown" in decision.reason_codes
    assert "max_daily_loss_breach" not in decision.reason_codes


@pytest.mark.parametrize("drawdown", [None, float("nan"), float("inf")])
def test_configured_drawdown_limit_rejects_missing_versioned_fact_even_with_raw_value(
    drawdown: float | None,
) -> None:
    decision = RuntimeRiskGuardian(_config()).evaluate(
        _observation(drawdown=drawdown, pnl={"daily": 0.0}, account_facts={})
    )

    assert decision.passed is False
    assert "drawdown_unknown" in decision.reason_codes


def test_versioned_zero_drawdown_is_known_and_raw_value_is_not_required() -> None:
    decision = RuntimeRiskGuardian(_config()).evaluate(
        _observation(drawdown=None, pnl={"daily": 0.0})
    )

    assert decision.passed is True
    assert "drawdown_unknown" not in decision.reason_codes


def test_health_pass_is_never_authorization() -> None:
    decision = RuntimeRiskGuardian(_config()).evaluate(_observation())
    assert decision.passed is True
    assert decision.healthy is True
    assert decision.health_passed is True
    assert decision.allowed is False
    payload = decision.to_dict()
    assert payload["health_passed"] is True
    assert payload["healthy"] is True
    assert payload["allowed"] is False
    assert payload["order_allowed"] is False
    assert payload["execution_permission"] is False


def test_standalone_generation_does_not_change_fact_or_evidence_digest() -> None:
    guardian = RuntimeRiskGuardian(_config())
    observation = _observation(exposure={"gross": 11.0})
    first = guardian.evaluate(observation, generation=0)
    later = guardian.evaluate(observation, generation=9)
    assert first.generation == 0
    assert later.generation == 9
    assert later.observation_digest == first.observation_digest
    assert later.evidence_digest == first.evidence_digest


def test_identical_tripped_repeat_is_stable_and_does_not_write() -> None:
    store = InMemoryGuardianLatchStore()
    with RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa") as supervisor:
        first = _trip(supervisor, exposure={"gross": 11.0})
        record_after_first = supervisor.latch
        assert first.generation == 1
        assert record_after_first is not None
        repeat = _trip(supervisor, exposure={"gross": 11.0})
        record_after_repeat = supervisor.latch
        assert repeat.generation == 1
        assert repeat.evidence_digest == first.evidence_digest
        assert record_after_repeat == record_after_first


def test_identical_repeat_preserves_ack_and_changed_failure_starts_one_new_incident() -> None:
    store = InMemoryGuardianLatchStore()
    with RuntimeRiskGuardianSupervisor(RuntimeRiskGuardian(_config()), store, owner_id="a", fence_token="fa") as supervisor:
        first = _trip(supervisor, exposure={"gross": 11.0})
        acked = _ack(supervisor, first)
        repeat = _trip(supervisor, exposure={"gross": 11.0})
        assert repeat.generation == 1
        assert repeat.evidence_digest == first.evidence_digest
        assert supervisor.latch is not None and supervisor.latch.state_revision == acked.state_revision
        assert supervisor.latch.acknowledged is True

        changed = _trip(supervisor, exposure={"gross": 12.0})
        assert changed.generation == 2
        assert changed.evidence_digest != first.evidence_digest
        assert supervisor.latch is not None
        assert supervisor.latch.state_revision == acked.state_revision + 1
        assert supervisor.latch.acknowledged is False
        assert supervisor.latch.acknowledgement_id == ""
        assert supervisor.latch.recovery_evidence_digest == ""
