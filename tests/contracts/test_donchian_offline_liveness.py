"""Historical clock liveness is simulated evidence, never trading authority."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import socket

import pytest

from quant_crypto.application import donchian_offline_replay as replay
from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeError


FRAME = replay.build_closeout_scenario(start=datetime(2023, 1, 1, tzinfo=timezone.utc))


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("offline liveness must not access network")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def runner(tmp_path):
    return replay.DonchianOfflineReplay(replay.DonchianOfflineReplayConfig(
        repo_root=Path.cwd(), state_dir=tmp_path / "state", run_id="v1-clock-contract",
        data_version="explicit-continuous-test-only", max_notional_usdt=Decimal("50"),
        decision_time_utc=FRAME.index[5160].to_pydatetime(),
        decision_time_provider=lambda event, ordinal, phase: event + timedelta(seconds=1, milliseconds=ordinal),
    ))


def step(r, offset):
    # Match the existing historical driver: market observation precedes signal.
    r.venue.now = FRAME.index[offset].to_pydatetime() + timedelta(seconds=1)
    return r.run_frame(FRAME.iloc[:offset + 1])


@pytest.mark.parametrize("restart", [False, True])
def test_long_flat_then_open_hold_and_restart_dedupe(tmp_path, restart):
    r = runner(tmp_path)
    assert step(r, 5160)["submit_count"] == 0
    assert step(r, 5198)["submit_count"] == 0
    if restart:
        r.close()
        r = runner(tmp_path)
    opened = step(r, 5207)
    assert opened["fill_count"] == 1
    assert step(r, 5207)["fill_count"] == 1
    final = step(r, 5208)
    assert final["fill_count"] == final["submit_count"] == 1
    assert Decimal(final["equity_usdt"]) == Decimal("4999.997")
    assert final["position_contracts"] == "0.01"
    assert not any(final["safety"].values())
    assert r.controller._state["ledger_reconciliation"]["status"] == "reconciled"
    r.close()
    restored = runner(tmp_path)
    assert step(restored, 5208)["fill_count"] == 1
    assert step(restored, 5209)["submit_count"] == 1
    restored.close()


@pytest.mark.parametrize("fault", ["stale", "future", "missing", "rejected", "wrong_identity", "not_offline"])
def test_bad_simulated_receipt_blocks_and_does_not_renew_or_recover(tmp_path, monkeypatch, fault):
    r = runner(tmp_path)
    step(r, 5160)
    original = r.venue.observe_offline_liveness
    def bad_receipt(**kwargs):
        receipt = dict(original(**kwargs))
        if fault == "stale":
            receipt["observed_at_utc"] = (r.venue.now - timedelta(seconds=30.001)).isoformat()
        elif fault == "future":
            receipt["observed_at_utc"] = (r.venue.now + timedelta(seconds=1)).isoformat()
        elif fault == "missing":
            receipt.pop("observed_at_utc")
        elif fault == "rejected":
            receipt["acknowledged"] = False
        elif fault == "wrong_identity":
            receipt["identity_digest"] = "wrong"
        else:
            receipt["offline_execution_only"] = False
        return receipt
    monkeypatch.setattr(r.venue, "observe_offline_liveness", bad_receipt)
    old_ack = r.controller._state["risk_control"]["dead_man"]["last_ack_utc"]
    with pytest.raises(OkxDemoPaperRuntimeError, match="offline_liveness_receipt_invalid"):
        step(r, 5207)
    assert r.controller._state["risk_control"]["dead_man"]["last_ack_utc"] == old_ack
    assert r.venue.state["submit_count"] == 0
    r.close()
    restored = runner(tmp_path)
    with pytest.raises(OkxDemoPaperRuntimeError):
        step(restored, 5207)
    assert restored.venue.state["submit_count"] == 0
    restored.close()


def test_exact_timeout_boundary_and_freshness_guard_remain_unchanged(tmp_path, monkeypatch):
    r = runner(tmp_path)
    original = r.venue.observe_offline_liveness
    def aged_receipt(**kwargs):
        receipt = dict(original(**kwargs))
        receipt["observed_at_utc"] = (r.venue.now - timedelta(seconds=30)).isoformat()
        return receipt
    monkeypatch.setattr(r.venue, "observe_offline_liveness", aged_receipt)
    assert step(r, 5160)["fill_count"] == 0
    assert r.controller.config.dead_man_timeout_seconds == 30
    assert r.controller._write_path_is_trusted() is True
    r.venue.now += timedelta(microseconds=1)
    assert r.controller._write_path_is_trusted() is False
    r.close()


@pytest.mark.parametrize("fault", ["frozen", "untrusted", "disconnected", "disarmed", "cancel_only", "guardian"])
def test_simulated_observation_does_not_repair_an_unhealthy_boundary(tmp_path, monkeypatch, fault):
    r = runner(tmp_path)
    step(r, 5160)
    state = r.controller._state
    if fault == "frozen":
        state["risk_control"]["mode"] = "FROZEN_UNKNOWN"
    elif fault == "untrusted":
        state["risk_control"]["write_path_trusted"] = False
    elif fault == "disconnected":
        state["private_ws"]["connected"] = False
    elif fault == "disarmed":
        state["risk_control"]["dead_man"]["armed"] = False
    elif fault == "cancel_only":
        state["runtime"]["cancel_only"] = True
    else:
        monkeypatch.setattr(type(r.guardian_supervisor), "tripped", property(lambda self: True))
    old_ack = state["risk_control"]["dead_man"]["last_ack_utc"]
    with pytest.raises(OkxDemoPaperRuntimeError):
        step(r, 5207)
    assert state["risk_control"]["dead_man"]["last_ack_utc"] == old_ack
    assert r.venue.state["submit_count"] == 0
    r.close()
