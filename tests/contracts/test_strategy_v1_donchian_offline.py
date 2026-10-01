from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pandas as pd

from quant_crypto.application import donchian_offline_replay as replay_module
from quant_crypto.application.donchian_offline_replay import (
    DonchianOfflineReplay,
    DonchianOfflineReplayConfig,
    build_closeout_scenario,
)
from quant_crypto.application.runtime_risk_guardian import FileGuardianLatchStore
from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeError
from quant_shared.strategy_runtime.decision_envelope import (
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    DecisionEvidenceEnvelope,
)


FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "strategy_v1" / "offline_contract.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("V1 network access prohibited")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


SCENARIO = build_closeout_scenario(
    start=datetime.fromisoformat(FIXTURE["scenario"]["start_utc"])
)
CHECKPOINTS = FIXTURE["scenario"]["checkpoint_offsets"]


def _runner(
    tmp_path: Path,
    *,
    observation_time: datetime,
    run_id: str = "v1offline01",
    data_version: str = "v1-closeout-continuous-ohlcv-v1",
) -> DonchianOfflineReplay:
    return DonchianOfflineReplay(
        DonchianOfflineReplayConfig(
            repo_root=Path.cwd(),
            state_dir=tmp_path / "state",
            run_id=run_id,
            decision_time_utc=observation_time,
            data_version=data_version,
        )
    )


def _prefix(name: str) -> pd.DataFrame:
    return SCENARIO.iloc[: int(CHECKPOINTS[name]) + 1].copy(deep=True)


@pytest.fixture
def observation_time() -> datetime:
    # This checked-in observation clock must replay identically regardless of
    # the wall-clock date on the machine running the acceptance suite.
    return datetime.fromisoformat(FIXTURE["scenario"]["observation_time_utc"])


def _persist_recovery_boundary(
    runner: DonchianOfflineReplay,
    *,
    boundary: str,
) -> None:
    state = runner.controller._state
    if boundary == "frozen":
        state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    elif boundary == "write_path_untrusted":
        state["risk_control"]["write_path_trusted"] = False
    elif boundary == "private_ws_disconnected":
        state["private_ws"].update(
            {
                "status": "disconnected",
                "connected": False,
                "listener_alive": False,
                "opening_allowed_after_reconciliation": False,
            }
        )
    else:  # pragma: no cover - a test helper must never invent a boundary.
        raise AssertionError(f"unknown recovery boundary: {boundary}")
    runner.controller._persist_state()


def test_continuous_open_hold_reverse_reopen_exit_is_economically_replayable(
    tmp_path: Path,
    observation_time: datetime,
) -> None:
    runner = _runner(tmp_path, observation_time=observation_time)

    opened = runner.run_frame(_prefix("open_long"))
    opened_duplicate = runner.run_frame(_prefix("open_long"))
    assert opened["phase"] == "primary"
    assert opened["signal"]["direction"] == "long"
    assert opened["target_position"]["target_quantity"] == pytest.approx(0.01)
    assert opened["risk_decision"]["approved"] is True
    assert opened["order_plan"]["contracts"] == FIXTURE["target_contracts"]
    assert opened["order_plan"]["risk"]["cost_model_complete"] is True
    assert opened["position_contracts"] == "0.01"
    assert opened_duplicate["submit_count"] == 1

    runner.close()
    restarted = _runner(tmp_path, observation_time=observation_time)
    restarted_open = restarted.run_frame(_prefix("open_long"))
    assert restarted_open["submit_count"] == 1
    assert restarted_open["fill_count"] == 1
    assert restarted_open["decision_evidence_count"] == 1

    held = restarted.run_frame(_prefix("hold_long"))
    held_duplicate = restarted.run_frame(_prefix("hold_long"))
    assert held["phase"] == "hold"
    assert held["decision_outcome"] == "no_order"
    assert held["fills"] == []
    assert held["evidence"]["links"]["order_intent_id"] is None
    assert held["evidence"]["links"]["fill_ids"] == []
    assert held["evidence"]["links"]["ledger_event_id"] is None
    assert held_duplicate["submit_count"] == 1
    assert held_duplicate["decision_evidence_count"] == 2

    closed = restarted.run_frame(_prefix("reverse_to_short"))
    assert closed["phase"] == "reversal_close"
    assert closed["order_plan"]["reversal_close_only"] is True
    assert closed["position_contracts"] == "0.00"
    assert closed["submit_count"] == 2
    assert closed["fill_count"] == 2
    assert closed["cancel_algo_count"] == 1
    assert closed["ledger"]["payload"]["position_ledger"]["signed_contracts"] == "0"

    restarted.close()
    reopened_runner = _runner(tmp_path, observation_time=observation_time)
    reopened = reopened_runner.run_frame(_prefix("reverse_to_short"))
    reopened_duplicate = reopened_runner.run_frame(_prefix("reverse_to_short"))
    assert reopened["phase"] == "reversal_open"
    assert reopened["signal"]["direction"] == "short"
    assert reopened["position_contracts"] == "-0.01"
    assert reopened["submit_count"] == 3
    assert reopened_duplicate["submit_count"] == 3
    assert reopened_duplicate["fill_count"] == 3

    exited = reopened_runner.run_frame(_prefix("exit_short"))
    exited_duplicate = reopened_runner.run_frame(_prefix("exit_short"))
    reopened_runner.close()
    final = _runner(tmp_path, observation_time=observation_time).run_frame(
        _prefix("exit_short")
    )
    expected = FIXTURE["expected"]
    assert exited["phase"] == "exit"
    assert exited["position_contracts"] == expected["final_position_contracts"]
    assert exited["submit_count"] == expected["submit_count"]
    assert exited["fill_count"] == expected["fill_count"]
    assert exited["cancel_algo_count"] == expected["cancel_algo_count"]
    assert exited_duplicate["submit_count"] == expected["submit_count"]
    assert final["submit_count"] == expected["submit_count"]
    assert final["decision_evidence_count"] == 5

    fills = reopened_runner.venue.state["fills"]
    total_fees = sum(Decimal(row["fee"]) for row in fills)
    assert total_fees == Decimal(expected["total_fees_usdt"])
    assert Decimal(exited["equity_usdt"]) == Decimal(expected["final_equity_usdt"])
    replay = exited["ledger"]["payload"]["risk_context"]["account_ledger_replay"]
    assert replay["status"] == "reconciled"
    assert Decimal(replay["final_equity_usdt"]) == Decimal(
        expected["final_equity_usdt"]
    )
    funding = exited["ledger"]["payload"]["funding_ledger"]
    assert funding["bills"] == []
    assert Decimal(funding["cashflow"]) == Decimal(
        expected["actual_funding_cashflow_usdt"]
    )
    assert all(row["state"] == "canceled" for row in reopened_runner.venue.state["algo_history"])
    assert reopened_runner.venue.state["algos"] == []
    for result in (opened, held, closed, reopened, exited):
        assert result["evidence"]["schema_version"] == SCHEMA_VERSION
        assert result["evidence"]["input_digest"]
        assert result["evidence"]["evidence_kind"] == FIXTURE["evidence_kind"]
        assert result["evidence"]["runtime_observed"] is False
        assert result["safety"] == {
            "demo_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "runtime_observed": False,
            "network_accessed": False,
        }


def test_continuous_closeout_accepts_parentless_exchange_algo_readback_only_via_local_join(
    tmp_path: Path,
    observation_time: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_private_get = replay_module._OfflineVenue.private_get

    def parentless_private_get(
        venue: object,
        path: str,
        params: object = None,
    ) -> object:
        response = original_private_get(venue, path, params)
        if path not in {
            "/api/v5/trade/orders-algo-pending",
            "/api/v5/trade/order-algo",
        }:
            return response
        detached_rows = []
        for raw in response.data:
            row = dict(raw)
            row.pop("parentClOrdId", None)
            row.pop("clOrdId", None)
            detached_rows.append(row)
        return replace(response, data=tuple(detached_rows))

    monkeypatch.setattr(
        replay_module._OfflineVenue,
        "private_get",
        parentless_private_get,
    )

    # Reuse the frozen five-stage economic, duplicate, restart, ledger and
    # evidence assertions verbatim; only the exchange readback boundary differs.
    test_continuous_open_hold_reverse_reopen_exit_is_economically_replayable(
        tmp_path,
        observation_time,
    )


@pytest.mark.parametrize(
    "boundary",
    ("frozen", "write_path_untrusted", "private_ws_disconnected"),
)
def test_restart_preserves_each_persisted_opening_boundary(
    tmp_path: Path,
    observation_time: datetime,
    boundary: str,
) -> None:
    runner = _runner(
        tmp_path,
        observation_time=observation_time,
        run_id=f"v1-{boundary.replace('_', '-')}",
    )
    assert runner.venue.state["submit_count"] == 0
    assert runner.venue.state["position"] == "0"

    _persist_recovery_boundary(runner, boundary=boundary)
    runner.close()
    restarted = _runner(
        tmp_path,
        observation_time=observation_time,
        run_id=f"v1-{boundary.replace('_', '-')}",
    )
    with pytest.raises(OkxDemoPaperRuntimeError):
        restarted.run_frame(_prefix("open_long"))

    state = restarted.controller._durable_state_snapshot()
    assert restarted.venue.state["submit_count"] == 0
    assert restarted.venue.state["position"] == "0"
    if boundary == "frozen":
        assert state["risk_control"]["mode"] == "FROZEN_UNKNOWN"
    elif boundary == "write_path_untrusted":
        assert state["risk_control"]["write_path_trusted"] is False
    else:
        assert state["private_ws"]["connected"] is False
        assert state["private_ws"]["listener_alive"] is False
        assert (
            state["private_ws"]["opening_allowed_after_reconciliation"] is False
        )


def test_restart_preserves_persisted_tripped_guardian_latch(
    tmp_path: Path,
    observation_time: datetime,
) -> None:
    runner = _runner(
        tmp_path,
        observation_time=observation_time,
        run_id="v1-guardian-tripped",
    )
    assert runner.venue.state["submit_count"] == 0
    runner.close()

    store = FileGuardianLatchStore(
        (tmp_path / "state" / "guardian_latch.json").resolve()
    )
    lease = store.acquire("v1-offline", "v1-offline")
    current = store.load()
    tripped = replace(
        current,
        generation=current.generation + 1,
        state_revision=current.state_revision + 1,
        tripped=True,
        reason_codes=("v1_test_persisted_trip",),
        evidence_identity="v1_test_persisted_trip",
        evidence_digest="a" * 64,
        observation_digest="b" * 64,
        trip_reference_time_utc=observation_time,
    )
    store.save(
        tripped,
        expected_generation=current.generation,
        expected_revision=current.state_revision,
        owner_id="v1-offline",
        fence_token="v1-offline",
        lease=lease,
    )
    store.release(lease)

    restarted = _runner(
        tmp_path,
        observation_time=observation_time,
        run_id="v1-guardian-tripped",
    )
    with pytest.raises(OkxDemoPaperRuntimeError):
        restarted.run_frame(_prefix("open_long"))
    assert restarted.guardian_supervisor.tripped is True
    assert restarted.venue.state["submit_count"] == 0
    assert restarted.venue.state["position"] == "0"


def test_ledger_committed_before_evidence_is_recovered_without_resubmit(
    tmp_path: Path,
    observation_time: datetime,
) -> None:
    runner = _runner(
        tmp_path, observation_time=observation_time, run_id="v1crash01"
    )
    with pytest.raises(RuntimeError, match="injected_ledger_before_evidence_crash"):
        runner.run_frame(
            _prefix("open_long"), fail_after_ledger_before_evidence=True
        )
    recovery = runner.controller._runtime_store.recover()
    assert runner.venue.state["submit_count"] == 1
    assert len(runner.venue.state["fills"]) == 1
    assert not any(
        event["event_type"] == "strategy_decision_evidence"
        for event in recovery.events
    )

    runner.close()
    restarted = _runner(
        tmp_path, observation_time=observation_time, run_id="v1crash01"
    )
    recovered = restarted.run_frame(_prefix("open_long"))
    duplicate = restarted.run_frame(_prefix("open_long"))
    assert recovered["evidence"]["links"]["decision_outcome"] == "order_terminal"
    assert recovered["evidence"]["links"]["ledger_event_hash"] == recovered["ledger"]["event_hash"]
    assert recovered["submit_count"] == duplicate["submit_count"] == 1
    assert recovered["fill_count"] == duplicate["fill_count"] == 1
    assert recovered["decision_evidence_count"] == 1
    assert duplicate["decision_evidence_count"] == 1


def test_intent_persisted_before_post_remains_unknown_and_never_blind_retries(
    tmp_path: Path,
    observation_time: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(
        tmp_path, observation_time=observation_time, run_id="v1intent01"
    )

    def crash_before_post(_payload: object) -> None:
        raise SystemExit("injected_intent_persisted_before_post_crash")

    monkeypatch.setattr(runner.venue, "submit_order", crash_before_post)
    with pytest.raises(
        SystemExit, match="injected_intent_persisted_before_post_crash"
    ):
        runner.run_frame(_prefix("open_long"))
    recovery = runner.controller._runtime_store.recover()
    persisted = [
        event
        for event in recovery.events
        if event["event_type"] == "order_intent_persisted_before_post"
    ]
    assert len(persisted) == 1
    assert runner.venue.state["submit_count"] == 0
    assert runner.venue.state["fills"] == []

    runner.close()
    restarted = _runner(
        tmp_path, observation_time=observation_time, run_id="v1intent01"
    )
    with pytest.raises(
        OkxDemoPaperRuntimeError,
        match="okx_demo_order_submit_blocked_by_unresolved_intent",
    ):
        restarted.run_frame(_prefix("open_long"))
    pending = restarted.controller._runtime_store.recover().state[
        "risk_control"
    ]["pending_order_intents"]
    assert list(pending.values())[0]["status"] == "submit_pending"
    assert restarted.venue.state["submit_count"] == 0
    assert restarted.venue.state["fills"] == []
    assert not any(
        event["event_type"] == "strategy_decision_evidence"
        for event in restarted.controller._runtime_store.recover().events
    )


def test_identity_input_and_time_mismatches_fail_before_new_order(
    tmp_path: Path,
    observation_time: datetime,
) -> None:
    runner = _runner(tmp_path, observation_time=observation_time)
    opened = runner.run_frame(_prefix("open_long"))

    changed = _prefix("open_long")
    row = changed.index[10]
    changed.loc[row, "close"] = changed.loc[row, "close"] + 0.001
    changed.loc[row, "high"] = changed.loc[row, "high"] + 0.001
    with pytest.raises(
        OkxDemoPaperRuntimeError, match="offline_replay_same_bar_input_conflict"
    ):
        runner.run_frame(changed)
    assert runner.venue.state["submit_count"] == opened["submit_count"] == 1

    runner.run_frame(_prefix("hold_long"))
    with pytest.raises(
        OkxDemoPaperRuntimeError, match="offline_replay_event_time_regression"
    ):
        runner.run_frame(_prefix("open_long"))
    assert runner.venue.state["submit_count"] == 1

    with pytest.raises(ValueError, match="offline_replay_identity_mismatch:data_version"):
        _runner(
            tmp_path,
            observation_time=observation_time,
            data_version="changed-data-version",
        )
    assert runner.venue.state["submit_count"] == 1


def test_future_missing_and_timezone_unknown_frames_fail_closed(
    tmp_path: Path,
    observation_time: datetime,
) -> None:
    runner = _runner(tmp_path, observation_time=observation_time)
    frame = _prefix("open_long")
    base = runner.evaluate_frame(frame)
    future_index = pd.date_range(
        start=observation_time + timedelta(hours=1),
        periods=4,
        freq="h",
    )
    future = frame.iloc[-4:].copy(deep=True)
    future.index = future_index
    future["open_time"] = future.index - pd.Timedelta(hours=1)
    future[["open", "high", "low", "close"]] = 1.0
    extended = runner.evaluate_frame(
        pd.concat([frame, future]),
        visible_until=frame.index[-1].to_pydatetime(),
    )
    assert extended["raw_signal"] == base["raw_signal"]
    assert extended["target_contracts"] == base["target_contracts"]
    with pytest.raises(OkxDemoPaperRuntimeError, match="offline_replay_future_completed_bar"):
        runner.run_frame(pd.concat([frame, future]))
    with pytest.raises(OkxDemoPaperRuntimeError, match="missing:volume"):
        runner.run_frame(frame.drop(columns=["volume"]))
    naive = frame.copy(deep=True)
    naive.index = naive.index.tz_localize(None)
    naive["open_time"] = naive.index - pd.Timedelta(hours=1)
    with pytest.raises(OkxDemoPaperRuntimeError, match="index_timezone"):
        runner.run_frame(naive)
    assert runner.venue.state["submit_count"] == 0


def test_evidence_v2_binds_input_and_v1_remains_readable_but_not_v1_qualified(
    tmp_path: Path,
    observation_time: datetime,
) -> None:
    runner = _runner(tmp_path, observation_time=observation_time)
    result = runner.run_frame(_prefix("open_long"))
    envelope = DecisionEvidenceEnvelope.from_mapping(result["evidence"])
    with pytest.raises(ValueError, match="package_digest_mismatch"):
        envelope.require_binding(package_digest="0" * 64)
    with pytest.raises(ValueError, match="decision_id_mismatch"):
        envelope.require_binding(decision_id="f" * 64)
    with pytest.raises(ValueError, match="evidence_link_mismatch:signal_id"):
        envelope.require_binding(links={"signal_id": "sig_wrong"})
    with pytest.raises(ValueError, match="input_digest_mismatch"):
        envelope.require_binding(input_digest="f" * 64)

    legacy_payload = dict(result["evidence"])
    legacy_payload["schema_version"] = LEGACY_SCHEMA_VERSION
    legacy_payload.pop("input_digest")
    legacy = DecisionEvidenceEnvelope.from_mapping(legacy_payload)
    assert "input_digest" not in legacy.to_dict()
    with pytest.raises(ValueError, match="input_digest_mismatch"):
        legacy.require_binding(input_digest=envelope.input_digest)

    wrong_version = dict(result["evidence"])
    wrong_version["schema_version"] = "strategy_decision_evidence_v0"
    with pytest.raises(ValueError, match="schema_version_invalid"):
        DecisionEvidenceEnvelope.from_mapping(wrong_version)
