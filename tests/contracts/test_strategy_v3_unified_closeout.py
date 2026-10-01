"""Failure-first contracts for the bounded V3 offline closeout."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tests.contracts.test_strategy_v3_qlib_offline import (
    CONTRACT_PATH,
    ROOT,
    _fixture_config,
    _fixture_forecast,
    _observation,
    _single_lot_fixture_score,
)
from quant_crypto.application.qlib_offline_replay import (
    QlibFixtureOfflineReplay,
    QlibOfflineReplayError,
    evaluate_frozen_candidate,
    load_v3_contract,
)
from quant_crypto.trading_contracts import SignalDirection
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.application.runtime_risk_guardian import GuardianConcurrentWriterError


def test_sealed_candidate_uses_durable_common_runtime_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = {"sealed": 0}
    original_execute = QlibFixtureOfflineReplay.execute

    def counted_execute(self: QlibFixtureOfflineReplay, **kwargs: object) -> dict[str, object]:
        if self.config.truth_kind == "sealed_candidate_research_only":
            entered["sealed"] += 1
        return original_execute(self, **kwargs)

    monkeypatch.setattr(QlibFixtureOfflineReplay, "execute", counted_execute)
    contract = load_v3_contract(CONTRACT_PATH, repo_root=ROOT)
    result = evaluate_frozen_candidate(contract, repo_root=ROOT, state_dir=tmp_path)
    assert result["decision_count"] == 1392
    assert result["approved_decision_count"] == 0
    assert result["simulated_fill_count"] == 0
    assert result["runtime_policy_event_count"] == 1392
    assert result["runtime_physical_batch_event_count"] == 22
    assert entered["sealed"] == 1392
    import json
    rows = [json.loads(line) for line in Path(result["policy_evidence_path"]).read_text(encoding="utf-8").splitlines()]
    assert len({(row["runtime_batch_event_sequence"], row["runtime_batch_index"]) for row in rows}) == 1392
    assert all(row["runtime_batch_event_hash"] and row["runtime_decision_hash"] for row in rows)
    assert Path(result["runtime_state_dir"]).is_dir()


def test_sealed_batch_failure_before_append_can_resume_without_duplication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_v3_contract(CONTRACT_PATH, repo_root=ROOT)
    original_append = BTCRuntimeStore.append
    failed = False

    def fail_once(self: BTCRuntimeStore, **kwargs: object) -> dict[str, object]:
        nonlocal failed
        if kwargs.get("event_type") == "qlib_offline_rejected_batch" and not failed:
            failed = True
            raise RuntimeError("before_batch_append")
        return original_append(self, **kwargs)

    monkeypatch.setattr(BTCRuntimeStore, "append", fail_once)
    with pytest.raises(RuntimeError, match="before_batch_append"):
        evaluate_frozen_candidate(contract, repo_root=ROOT, state_dir=tmp_path)
    assert failed
    monkeypatch.setattr(BTCRuntimeStore, "append", original_append)
    result = evaluate_frozen_candidate(contract, repo_root=ROOT, state_dir=tmp_path)
    assert result["runtime_policy_event_count"] == 1392
    assert result["runtime_physical_batch_event_count"] == 22
    assert result["simulated_fill_count"] == 0


def test_torn_sealed_batch_stays_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_v3_contract(CONTRACT_PATH, repo_root=ROOT)
    original_append = BTCRuntimeStore.append

    def torn_append(self: BTCRuntimeStore, **kwargs: object) -> dict[str, object]:
        if kwargs.get("event_type") == "qlib_offline_rejected_batch":
            with self.events_path.open("ab") as stream:
                stream.write(b'{"incomplete":')
                stream.flush()
            raise RuntimeError("simulated_torn_append")
        return original_append(self, **kwargs)

    monkeypatch.setattr(BTCRuntimeStore, "append", torn_append)
    with pytest.raises(RuntimeError, match="simulated_torn_append"):
        evaluate_frozen_candidate(contract, repo_root=ROOT, state_dir=tmp_path)
    monkeypatch.setattr(BTCRuntimeStore, "append", original_append)
    with pytest.raises(QlibOfflineReplayError, match="truncated_tail"):
        evaluate_frozen_candidate(contract, repo_root=ROOT, state_dir=tmp_path)


def test_expired_dead_man_cannot_become_fresh_by_offline_clock_write(tmp_path: Path) -> None:
    with QlibFixtureOfflineReplay(_fixture_config(tmp_path)) as replay:
        before = replay.controller._state["risk_control"]["dead_man"]["last_ack_utc"]
        replay._now += timedelta(hours=1)
        replay.venue.now = replay._now
        with pytest.raises(QlibOfflineReplayError, match="maintenance|expired|stale"):
            replay._renew_verified_offline_liveness()
        assert replay.controller._state["risk_control"]["dead_man"]["last_ack_utc"] == before


def test_restart_uses_last_observed_clock_without_rewriting_ack(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    forecast = _fixture_forecast(config, ordinal=1, direction=SignalDirection.LONG, score=0.001)
    with QlibFixtureOfflineReplay(config) as replay:
        replay._advance_offline_time(
            target_utc=replay.venue.now + timedelta(minutes=1),
            facts=_observation(forecast).maintenance_facts,
        )
        last_observed = replay.venue.now
        last_ack = replay.controller._state["risk_control"]["dead_man"]["last_ack_utc"]
    with QlibFixtureOfflineReplay(config) as recovered:
        assert recovered._now == recovered.venue.now == last_observed
        assert recovered.controller._state["risk_control"]["dead_man"]["last_ack_utc"] == last_ack


def test_clean_stop_with_expired_ack_cannot_resume_as_healthy(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with QlibFixtureOfflineReplay(config) as replay:
        replay.venue.set_market(
            now=replay.venue.now + timedelta(minutes=2),
            mark_price=62_500, index_price=62_500, fill_price=62_500,
        )
        replay._now = replay.venue.now
        stale_ack = (replay._now - timedelta(minutes=2)).isoformat()
        replay.controller._state["risk_control"]["dead_man"]["last_ack_utc"] = stale_ack
        replay.controller._persist_state()
    with QlibFixtureOfflineReplay(config) as recovered:
        with pytest.raises(QlibOfflineReplayError, match="expired|stale|maintenance"):
            recovered._resume_after_verified_recovery()
        assert recovered.controller._state["risk_control"]["dead_man"]["last_ack_utc"] == stale_ack


def test_constructor_failure_releases_only_its_guardian_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    original = QlibFixtureOfflineReplay._activate_initial_state
    monkeypatch.setattr(
        QlibFixtureOfflineReplay, "_activate_initial_state",
        lambda self: (_ for _ in ()).throw(RuntimeError("construct_interrupted")),
    )
    with pytest.raises(RuntimeError, match="construct_interrupted"):
        QlibFixtureOfflineReplay(config)
    monkeypatch.setattr(QlibFixtureOfflineReplay, "_activate_initial_state", original)
    with QlibFixtureOfflineReplay(config):
        pass


def test_genuine_concurrent_guardian_writer_remains_rejected(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with QlibFixtureOfflineReplay(config):
        with pytest.raises(GuardianConcurrentWriterError, match="latch_concurrent_writer"):
            QlibFixtureOfflineReplay(config)


def test_close_failure_releases_own_guardian_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_config(tmp_path)
    replay = QlibFixtureOfflineReplay(config)
    monkeypatch.setattr(
        replay, "_record_clean_stop",
        lambda: (_ for _ in ()).throw(RuntimeError("clean_stop_interrupted")),
    )
    with pytest.raises(RuntimeError, match="clean_stop_interrupted"):
        replay.close()
    try:
        recovered = QlibFixtureOfflineReplay(config)
    except GuardianConcurrentWriterError:
        pytest.fail("the failed close leaked this instance's Guardian lease")
    except QlibOfflineReplayError:
        # A missing clean-stop receipt may still correctly block recovery.
        pass
    else:
        recovered.close()


def test_ledger_commit_before_policy_projection_recovers_exact_fill_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _fixture_config(tmp_path)
    forecast = _fixture_forecast(
        config, ordinal=1, direction=SignalDirection.LONG,
        score=_single_lot_fixture_score(),
    )
    with QlibFixtureOfflineReplay(config) as replay:
        def interrupted(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("projection_interrupted")

        monkeypatch.setattr(replay, "_persist_policy_state", interrupted)
        with pytest.raises(RuntimeError, match="projection_interrupted"):
            replay.execute(forecast=forecast, observation=_observation(forecast), phase="open_long")
        assert replay.venue.state["submit_count"] == 1
        original_fill_id = replay.venue.state["fills"][0]["tradeId"]

    with QlibFixtureOfflineReplay(config) as replay:
        result = replay.execute(
            forecast=forecast, observation=_observation(forecast), phase="open_long"
        )
        assert result["recovered_without_resubmit"] is True
        assert result["fill_ids"] == [original_fill_id]
        assert (config.state_dir / "qlib_policy_state.json").is_file()
        assert replay.venue.state["submit_count"] == 1
        assert len(replay.venue.state["fills"]) == 1
