"""Offline processing order is distinct from immutable source/forecast time."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from quant_crypto.application import qlib_offline_replay as replay_module
from tests.contracts.test_strategy_v3_qlib_offline import (
    CONTRACT_PATH, ROOT, FIXTURE_WHEN, _fixture_config,
    _fixture_forecast, _observation, _single_lot_fixture_score,
    _deny_network_and_training,  # noqa: F401 -- autouse safety fixture
    test_explicit_short_fixture_uses_same_policy_and_original_hard_exit as _original_short_acceptance,
)
from quant_crypto.trading_contracts import SignalDirection


def test_boundary_fill_precedes_new_observation_without_changing_source_time() -> None:
    source_time = FIXTURE_WHEN
    last_processing_time = source_time + timedelta(milliseconds=1)
    processing_time = replay_module._decision_observation_time(
        source_time=source_time, previous_time=last_processing_time,
    )
    assert processing_time == source_time + timedelta(milliseconds=2)
    assert source_time == FIXTURE_WHEN


@pytest.mark.parametrize("previous_delta, expected_delta", [(-1000, 0), (0, 1), (2, 3)])
def test_fixed_bounded_tie_rule(previous_delta: int, expected_delta: int) -> None:
    assert replay_module._decision_observation_time(
        source_time=FIXTURE_WHEN,
        previous_time=FIXTURE_WHEN + timedelta(milliseconds=previous_delta),
    ) == FIXTURE_WHEN + timedelta(milliseconds=expected_delta)


def test_arbitrary_old_event_is_not_shifted_forward_to_become_current() -> None:
    with pytest.raises(replay_module.QlibOfflineReplayError, match="out_of_order"):
        replay_module._decision_observation_time(
            source_time=FIXTURE_WHEN,
            previous_time=FIXTURE_WHEN + timedelta(seconds=1),
        )


def test_ordering_contract_cannot_be_silently_changed(tmp_path: Path) -> None:
    contract = replay_module.load_v3_contract(CONTRACT_PATH, repo_root=ROOT)
    assert contract["offline_event_ordering"]["version"] == "qlib_offline_event_order_v1"
    # Validation rejects the changed ordering before resolving other file paths.
    contract["offline_event_ordering"]["observation_step_ms"] = 5000
    changed = tmp_path / "contract.json"
    changed.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(replay_module.QlibOfflineReplayError, match="event_order"):
        replay_module.load_v3_contract(changed, repo_root=tmp_path)


def test_observation_slot_is_persisted_and_reused_after_restart(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with replay_module.QlibFixtureOfflineReplay(config) as replay:
        first = replay._begin_decision_observation(
            event_id="decision-1", source_time=FIXTURE_WHEN, facts=(),
        )
        assert first["source_decision_time_utc"] == FIXTURE_WHEN.isoformat()
        assert first["observation_processing_time_utc"] == FIXTURE_WHEN.isoformat()
    with replay_module.QlibFixtureOfflineReplay(config) as replay:
        replay._resume_after_verified_recovery()
        again = replay._begin_decision_observation(
            event_id="decision-1", source_time=FIXTURE_WHEN, facts=(),
        )
        assert again == first
        slots = [event for event in replay.controller._runtime_store.recover().events
                 if event["event_type"] == "qlib_offline_observation_scheduled"]
        assert len(slots) == 1
        with pytest.raises(replay_module.QlibOfflineReplayError, match="source_boundary"):
            replay._begin_decision_observation(
                event_id="different-decision-same-boundary", source_time=FIXTURE_WHEN, facts=(),
            )


def test_changed_mark_boundary_retains_strict_account_facts_and_exact_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_times = []
    bound_slots = []
    original_assert = replay_module.QlibFixtureOfflineReplay._assert_ledger
    original_close = replay_module.QlibFixtureOfflineReplay.close

    def strict_assert(self, snapshot):
        original_assert(self, snapshot)
        assert self.controller._state["account_risk_facts"]["risk_eligible"] is True
        checked_times.append(self.venue.now)

    def collect_then_close(self):
        events = self.controller._runtime_store.recover().events
        bound_slots.extend(event["payload"]["offline_observation_slot"] for event in events
                           if event["event_type"] == "qlib_policy_step_bound")
        original_close(self)

    monkeypatch.setattr(replay_module.QlibFixtureOfflineReplay, "_assert_ledger", strict_assert)
    monkeypatch.setattr(replay_module.QlibFixtureOfflineReplay, "close", collect_then_close)
    # Reuse the unchanged old business acceptance, including original prices,
    # scores, quantity and hard-exit expectations, not a softened new scenario.
    _original_short_acceptance(tmp_path)
    boundary = FIXTURE_WHEN + timedelta(hours=1)
    assert boundary + timedelta(milliseconds=1) in checked_times  # prior fill
    assert boundary + timedelta(milliseconds=2) in checked_times  # new mark
    slots = {slot["event_id"]: slot for slot in bound_slots}
    assert len(slots) == 2
    second = sorted(slots.values(), key=lambda slot: slot["source_decision_time_utc"])[1]
    assert second["source_decision_time_utc"] == boundary.isoformat()
    assert second["previous_processing_time_utc"] == (boundary + timedelta(milliseconds=1)).isoformat()
    assert second["observation_processing_time_utc"] == (boundary + timedelta(milliseconds=2)).isoformat()


def test_interrupted_slot_restores_bound_market_before_account_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    first = _fixture_forecast(config, ordinal=1, direction=SignalDirection.SHORT,
                              score=_single_lot_fixture_score())
    second = _fixture_forecast(config, ordinal=2, direction=SignalDirection.SHORT,
                               score=_single_lot_fixture_score())
    observation = _observation(second, close=66_000.0, delayed_open=66_000.0)
    with replay_module.QlibFixtureOfflineReplay(config) as replay:
        replay.execute(forecast=first, observation=_observation(first), phase="open_short")
        original_begin = replay._begin_decision_observation

        def interrupt_after_slot(**kwargs):
            slot = original_begin(**kwargs)
            assert slot["source_decision_time_utc"] == second.timestamp_utc.isoformat()
            raise RuntimeError("after_slot_before_market")

        monkeypatch.setattr(replay, "_begin_decision_observation", interrupt_after_slot)
        with pytest.raises(RuntimeError, match="after_slot_before_market"):
            replay.execute(forecast=second, observation=observation, phase="hard_exit_short")
        slots_before = [event["payload"] for event in replay.controller._runtime_store.recover().events
                        if event["event_type"] == "qlib_offline_observation_scheduled"]
        assert replay.venue.state["submit_count"] == 1
    with replay_module.QlibFixtureOfflineReplay(config) as replay:
        result = replay.execute(forecast=second, observation=observation, phase="hard_exit_short")
        assert result["action"] == "close_short"
        assert float(result["position_contracts"]) == 0
        assert result["submit_count"] == result["fill_count"] == 2
        assert replay.controller._state["account_risk_facts"]["risk_eligible"] is True
        assert replay.execute(forecast=second, observation=observation, phase="hard_exit_short") == result
        slots_after = [event["payload"] for event in replay.controller._runtime_store.recover().events
                       if event["event_type"] == "qlib_offline_observation_scheduled"]
        assert slots_after == slots_before
