from __future__ import annotations

import json
import hashlib
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import quant_crypto.application.qlib_offline_replay as qlib_offline_replay

from quant_crypto.application.qlib_offline_replay import (
    CandidateMarketObservation,
    OfflineMaintenanceFact,
    QlibFixtureOfflineReplay,
    QlibFixtureReplayConfig,
    QlibOfflineReplayError,
    btc_quantity_to_okx_contracts,
    evaluate_frozen_candidate,
    load_v3_contract,
    _archive_input_paths,
)
from quant_crypto.portfolio.forecast import BTCForecast, BTCForecastQuality
from quant_crypto.trading_contracts import SignalDirection


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "tests/fixtures/strategy_v3/offline_contract.json"
FIXTURE_WHEN = datetime(2026, 7, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _deny_network_and_training(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("V3 offline acceptance forbids network and training")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    try:
        import lightgbm as lgb
    except ImportError:  # pragma: no cover
        return
    monkeypatch.setattr(lgb, "train", deny)
    monkeypatch.setattr(lgb.LGBMModel, "fit", deny)


def test_v3_contract_is_namespaced_readonly_and_fail_closed() -> None:
    contract = load_v3_contract(CONTRACT_PATH, repo_root=ROOT)
    assert contract["schema_version"] == "strategy_v3_qlib_offline_contract_v1"
    assert contract["fixture_namespace"] != contract["candidate"]["run_id"]
    assert contract["candidate"]["decision_count"] == 1392
    assert contract["candidate"]["expected_simulated_fill_count"] == 0
    assert all(value is False for value in contract["permissions"].values())


def test_frozen_candidate_1392_predictions_preserve_policy_and_zero_fills(tmp_path: Path) -> None:
    contract = load_v3_contract(CONTRACT_PATH, repo_root=ROOT)
    result = evaluate_frozen_candidate(contract, repo_root=ROOT, state_dir=tmp_path)
    assert result["decision_count"] == 1392
    assert result["approved_decision_count"] == 0
    assert result["simulated_fill_count"] == 0
    assert result["candidate_effectiveness"] == "not_proven_negative_ic_zero_fill_preserved"
    assert result["execution_permission"] is False
    assert result["runtime_observed"] is False
    evidence = Path(result["policy_evidence_path"])
    assert len(evidence.read_text(encoding="utf-8").splitlines()) == 1392
    before = evidence.read_bytes()
    assert evaluate_frozen_candidate(
        contract, repo_root=ROOT, state_dir=tmp_path
    )["policy_evidence_sha256"] == result["policy_evidence_sha256"]
    assert evidence.read_bytes() == before
    assert all(not Path(value).is_absolute() for value in result["archive_input_paths"].values())


def test_archive_inputs_ignore_legacy_absolute_paths_and_reject_archive_tamper(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    input_dir = archive / "qlib_runs/run/qlib_input"
    input_dir.mkdir(parents=True)
    file_hashes = {}
    rows = []
    for key, filename in {
        "daily_bars_parquet": "daily_bars.parquet",
        "mark": "mark.parquet",
        "premium": "premium.parquet",
        "funding": "funding.parquet",
    }.items():
        path = input_dir / filename
        path.write_bytes(("sealed:" + key).encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file_hashes[key] = digest
        rows.append({"path": path.relative_to(archive).as_posix(), "sha256": digest})
    dataset = {
        "files": {key: f"Z:/legacy/outside/{key}.parquet" for key in file_hashes},
        "file_hashes": file_hashes,
    }
    manifest_path = input_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(dataset), encoding="utf-8")
    rows.append({
        "path": manifest_path.relative_to(archive).as_posix(),
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    })
    _, _, resolved = _archive_input_paths(
        archive_root=archive,
        archive_manifest={"files": rows},
        run_id="run",
    )
    assert all(path.parent == input_dir for path in resolved.values())
    (input_dir / "mark.parquet").write_bytes(b"tampered")
    with pytest.raises(QlibOfflineReplayError, match="archive_member_sha256_mismatch"):
        _archive_input_paths(
            archive_root=archive,
            archive_manifest={"files": rows},
            run_id="run",
        )


@pytest.mark.parametrize(
    ("btc_quantity", "expected"),
    [("0", "0"), ("0.0001", "0.01"), ("-0.0001", "-0.01")],
)
def test_btc_to_contract_conversion_is_exact_and_signed(btc_quantity: str, expected: str) -> None:
    conversion = btc_quantity_to_okx_contracts(
        btc_quantity=btc_quantity,
        contract_value_btc="0.01",
        lot_size_contracts="0.01",
        min_size_contracts="0.01",
        max_abs_contracts="0.01",
    )
    assert conversion.contracts_text == expected
    assert conversion.exact is True


@pytest.mark.parametrize("btc_quantity", ["0.00011", "0.00001", "0.1"])
def test_btc_to_contract_conversion_rejects_inexact_below_minimum_or_over_cap(btc_quantity: str) -> None:
    with pytest.raises(QlibOfflineReplayError):
        btc_quantity_to_okx_contracts(
            btc_quantity=btc_quantity,
            contract_value_btc="0.01",
            lot_size_contracts="0.01",
            min_size_contracts="0.01",
            max_abs_contracts="0.01",
        )


def _fixture_config(state_dir: Path) -> QlibFixtureReplayConfig:
    return QlibFixtureReplayConfig(
        repo_root=ROOT,
        state_dir=state_dir,
        run_id="v3fixture01",
        decision_time_utc=FIXTURE_WHEN,
        strategy_id="qlib_fixture_strategy_v3",
        strategy_version="qlib_fixture_strategy_v3",
        candidate_id="strategy-v3-nonzero-fixture-only",
        model_sha256="a" * 64,
        data_version="strategy-v3-explicit-fixture-v1",
        policy_sha256="b" * 64,
    )


def _fixture_forecast(
    config: QlibFixtureReplayConfig,
    *,
    ordinal: int,
    direction: SignalDirection,
    score: float,
) -> BTCForecast:
    when = FIXTURE_WHEN + timedelta(hours=ordinal - 1)
    signal_id = f"v3-fixture-signal-{ordinal}"
    forecast_id = f"v3-fixture-forecast-{ordinal}"
    forecast = BTCForecast(
        timestamp_utc=when,
        strategy_id=config.strategy_id,
        symbol="BTC-USDT-SWAP",
        direction=direction,
        score=score,
        horizon="12h",
        unit="bps",
        expected_return_bps=(100.0 if direction == SignalDirection.LONG else -100.0),
        confidence=1.0,
        expiry_utc=when + timedelta(hours=12),
        source_signal_id=signal_id,
        quality=BTCForecastQuality(
            ic=0.05,
            hit_rate=0.55,
            sample_size=100,
            evidence_path="fixture-only",
            evidence_hash="c" * 64,
        ),
        metadata={
            "fixture_only": True,
            "model_sha256": config.model_sha256,
            "data_version": config.data_version,
        },
        forecast_id=forecast_id,
    )
    return forecast


def _observation(
    forecast: BTCForecast,
    *,
    close: float = 62_500.0,
    delayed_open: float = 62_500.0,
    funding_cashflow: float = 0.0,
    blockers: tuple[str, ...] = (),
    prior_close: float = 62_500.0,
) -> CandidateMarketObservation:
    event_time = forecast.timestamp_utc - timedelta(hours=1)
    # These are explicitly synthetic venue observations for the nonzero
    # fixture.  No sealed candidate or historical candle inherits them.
    maintenance_facts = tuple(
        OfflineMaintenanceFact(
            observed_at_utc=event_time + timedelta(seconds=offset),
            mark_price=prior_close if offset <= 3600 else close,
            index_price=prior_close if offset <= 3600 else close,
        )
        for offset in range(90, 7201, 90)
    )
    return CandidateMarketObservation(
        event_time_utc=event_time,
        close_price=close,
        mark_price=close,
        index_price=close,
        delayed_open_price=delayed_open,
        funding_rate=0.0001,
        funding_cashflow_usdt=funding_cashflow,
        blockers=blockers,
        maintenance_facts=maintenance_facts,
    )


def _single_lot_fixture_score() -> float:
    """One frozen synthetic input: 5000 * (.005 * .25) / 62500 == .0001 BTC."""

    return 0.005


def test_explicit_nonzero_fixture_uses_existing_oms_ledger_and_survives_restart(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with QlibFixtureOfflineReplay(config) as replay:
        open_forecast = _fixture_forecast(
            config, ordinal=1, direction=SignalDirection.LONG,
            score=_single_lot_fixture_score(),
        )
        opened = replay.execute(
            forecast=open_forecast,
            observation=_observation(open_forecast),
            phase="open_long",
        )
        duplicate = replay.execute(
            forecast=open_forecast,
            observation=_observation(open_forecast),
            phase="open_long",
        )
        hold_forecast = _fixture_forecast(
            config, ordinal=2, direction=SignalDirection.LONG,
            score=_single_lot_fixture_score(),
        )
        held = replay.execute(
            forecast=hold_forecast,
            observation=_observation(
                hold_forecast, blockers=("fixture_quality_blocker",)
            ),
            phase="hold_long",
        )
    assert opened == duplicate
    assert opened["position_contracts"] == "0.01"
    assert held["decision_outcome"] == "policy_rejected_no_order"
    assert held["position_contracts"] == "0.01"
    assert held["submit_count"] == 1

    with QlibFixtureOfflineReplay(config) as replay:
        # Exact retry after restart returns durable evidence and does not post.
        assert replay.execute(
            forecast=open_forecast,
            observation=_observation(open_forecast),
            phase="open_long",
        )["submit_count"] == 1
        close_forecast = _fixture_forecast(
            config, ordinal=3, direction=SignalDirection.SHORT, score=0.0048,
        )
        reversed_close = replay.execute(
            forecast=close_forecast,
            observation=_observation(close_forecast, funding_cashflow=-0.25),
            phase="reversal_close",
        )
        recovered = replay.controller._runtime_store.recover()
        ledger_events = [
            event for event in recovered.events
            if event.get("event_type") == "ledger_uow_committed"
        ]
        final_ledger = ledger_events[-1]["payload"]
        venue_state = json.loads(json.dumps(replay.venue.state))
    assert reversed_close["action"] == "close_long"
    assert Decimal(reversed_close["position_contracts"]) == 0
    assert reversed_close["submit_count"] == 2
    assert reversed_close["fill_count"] == 2
    assert reversed_close["truth_kind"] == "explicit_fixture_not_candidate_effectiveness"
    assert all(value is False for value in reversed_close["permissions"].values())
    independent_fee_total = sum(Decimal(row["fee"]) for row in venue_state["fills"])
    independent_funding = sum(Decimal(row["balChg"]) for row in venue_state["bills"])
    contract_value = Decimal("0.01")
    position_btc = Decimal("0")
    trade_cashflow = Decimal("0")
    for row in venue_state["fills"]:
        signed = Decimal(row["fillSz"]) * contract_value * (Decimal("1") if row["side"] == "buy" else Decimal("-1"))
        position_btc += signed
        trade_cashflow -= signed * Decimal(row["fillPx"])
    independent_equity = Decimal("5000") + trade_cashflow + position_btc * Decimal("62500") + independent_fee_total + independent_funding
    assert Decimal(venue_state["equity"]) == independent_equity
    assert Decimal(final_ledger["cash_ledger"]["equity_usdt"]) == independent_equity
    assert Decimal(final_ledger["position_ledger"]["signed_contracts"]) == 0
    assert Decimal(final_ledger["funding_ledger"]["cashflow"]) == independent_funding != 0
    assert final_ledger["funding_ledger"]["cashflow_reconciled"] is True
    assert final_ledger["risk_context"]["account_ledger_replay"]["status"] == "reconciled"


def test_explicit_short_fixture_uses_same_policy_and_original_hard_exit(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with QlibFixtureOfflineReplay(config) as replay:
        short_forecast = _fixture_forecast(
            config, ordinal=1, direction=SignalDirection.SHORT,
            score=_single_lot_fixture_score(),
        )
        opened = replay.execute(
            forecast=short_forecast,
            observation=_observation(short_forecast),
            phase="open_short",
        )
        exit_forecast = _fixture_forecast(
            config, ordinal=2, direction=SignalDirection.SHORT,
            score=_single_lot_fixture_score(),
        )
        exited = replay.execute(
            forecast=exit_forecast,
            observation=_observation(
                exit_forecast, close=66_000.0, delayed_open=66_000.0
            ),
            phase="hard_exit_short",
        )
    assert opened["action"] == "open_short"
    assert opened["position_contracts"] == "-0.01"
    assert exited["action"] == "close_short"
    assert Decimal(exited["position_contracts"]) == 0
    assert exited["submit_count"] == 2
    assert exited["fill_count"] == 2


def test_fixture_rejects_changed_score_target_or_forecast_source_after_seal(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with QlibFixtureOfflineReplay(config) as replay:
        forecast = _fixture_forecast(
            config, ordinal=1, direction=SignalDirection.LONG,
            score=_single_lot_fixture_score(),
        )
        replay.execute(
            forecast=forecast, observation=_observation(forecast), phase="open_long",
        )
        changed_score = BTCForecast(**{**forecast.__dict__, "score": 0.5})
        with pytest.raises(QlibOfflineReplayError, match="sealed_input_changed"):
            replay.execute(
                forecast=changed_score, observation=_observation(changed_score), phase="open_long",
            )
        with pytest.raises(QlibOfflineReplayError, match="target_contracts_cap_breached"):
            btc_quantity_to_okx_contracts(
                btc_quantity="0.0002", contract_value_btc="0.01",
                lot_size_contracts="0.01", min_size_contracts="0.01",
                max_abs_contracts="0.01",
            )


def test_ledger_commit_before_evidence_is_recovered_without_resubmit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _fixture_config(tmp_path)
    forecast = _fixture_forecast(
        config, ordinal=1, direction=SignalDirection.LONG,
        score=_single_lot_fixture_score(),
    )
    with QlibFixtureOfflineReplay(config) as replay:
        def evidence_write_interrupted(**_kwargs: object) -> None:
            raise RuntimeError("fixture_evidence_write_interrupted")

        monkeypatch.setattr(
            replay, "_append_decision_evidence", evidence_write_interrupted
        )
        with pytest.raises(RuntimeError, match="evidence_write_interrupted"):
            replay.execute(
                forecast=forecast,
                observation=_observation(forecast),
                phase="open_long",
            )
        assert replay.venue.state["submit_count"] == 1
        assert len(replay.venue.state["fills"]) == 1
        committed_events = replay.controller._runtime_store.recover().events
        order_event = next(
            event for event in committed_events
            if event.get("event_type") == "order_lifecycle"
        )
        ledger_event = next(
            event for event in committed_events
            if event.get("event_type") == "ledger_uow_committed"
            and any(
                row.get("client_order_id")
                == order_event["payload"]["oms"]["client_order_id"]
                for row in event["payload"]["order_ledger"]["orders"]
            )
        )
        original_client_order_id = order_event["payload"]["oms"][
            "client_order_id"
        ]
        original_ledger_event_id = ledger_event["idempotency_key"]
        original_ledger_event_hash = ledger_event["event_hash"]

    with QlibFixtureOfflineReplay(config) as replay:
        recovered = replay.execute(
            forecast=forecast,
            observation=_observation(forecast),
            phase="open_long",
        )
        assert recovered["recovered_without_resubmit"] is True
        assert recovered["submit_count"] == 1
        assert recovered["fill_count"] == 1
        assert recovered["client_order_id"] == original_client_order_id
        assert recovered["ledger_event_id"] == original_ledger_event_id
        assert recovered["ledger_event_hash"] == original_ledger_event_hash


def test_unknown_intent_and_untrusted_recovery_remain_fail_closed(
    tmp_path: Path,
) -> None:
    config = _fixture_config(tmp_path)
    replay = QlibFixtureOfflineReplay(config)
    state = replay.controller._state
    state["runtime"].update(
        {"active": False, "opening_allowed": False, "status": "blocked_fixture"}
    )
    state["risk_control"].update(
        {"mode": "FROZEN_UNKNOWN", "write_path_trusted": False}
    )
    state["risk_control"]["pending_order_intents"] = {
        "unknown-fixture-intent": {"status": "unknown"}
    }
    state["private_ws"].update(
        {"status": "disconnected", "connected": False, "listener_alive": False}
    )
    replay.controller._persist_state()
    replay.close()

    forecast = _fixture_forecast(
        config, ordinal=1, direction=SignalDirection.LONG,
        score=_single_lot_fixture_score(),
    )
    with QlibFixtureOfflineReplay(config) as restarted:
        with pytest.raises(
            QlibOfflineReplayError, match="recovery_not_authorized"
        ):
            restarted.execute(
                forecast=forecast,
                observation=_observation(forecast),
                phase="blocked_restart",
            )
        recovered = restarted.controller._runtime_store.recover().state
        assert recovered["runtime"]["active"] is False
        assert recovered["runtime"]["opening_allowed"] is False
        assert recovered["risk_control"]["mode"] == "FROZEN_UNKNOWN"
        assert recovered["risk_control"]["write_path_trusted"] is False
        assert recovered["private_ws"]["connected"] is False
        assert recovered["risk_control"]["pending_order_intents"][
            "unknown-fixture-intent"
        ]["status"] == "unknown"


def test_missing_funding_cashflow_is_blocked_before_order(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    with QlibFixtureOfflineReplay(config) as replay:
        before_ledger_count = sum(
            event.get("event_type") == "ledger_uow_committed"
            for event in replay.controller._runtime_store.recover().events
        )
        replay.venue.state["bills"].append(
            {
                "billId": str(int(FIXTURE_WHEN.timestamp() * 1000)),
                "instId": "BTC-USDT-SWAP",
                "type": "8",
                "subType": "173",
                "ts": str(int(FIXTURE_WHEN.timestamp() * 1000)),
                "ccy": "USDT",
            }
        )
        replay.venue._persist()
        forecast = _fixture_forecast(
            config, ordinal=1, direction=SignalDirection.LONG,
            score=_single_lot_fixture_score(),
        )
        with pytest.raises(RuntimeError, match="funding_cashflow_unknown"):
            replay.execute(
                forecast=forecast,
                observation=_observation(forecast),
                phase="missing_cashflow",
            )
        assert replay.venue.state["submit_count"] == 0
        assert replay.venue.state["fills"] == []
        after_ledger_count = sum(
            event.get("event_type") == "ledger_uow_committed"
            for event in replay.controller._runtime_store.recover().events
        )
        assert after_ledger_count == before_ledger_count


def test_execution_boundary_rejects_forged_quantity_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _fixture_config(tmp_path)
    original_step = qlib_offline_replay.evaluate_candidate_step

    def forged_step(*args: object, **kwargs: object):
        step = original_step(*args, **kwargs)
        assert step.conversion is not None
        return replace(
            step,
            conversion=replace(step.conversion, btc_quantity_text="0.0002"),
        )

    monkeypatch.setattr(
        qlib_offline_replay, "evaluate_candidate_step", forged_step
    )
    with QlibFixtureOfflineReplay(config) as replay:
        forecast = _fixture_forecast(
            config, ordinal=1, direction=SignalDirection.LONG,
            score=_single_lot_fixture_score(),
        )
        with pytest.raises(
            RuntimeError, match="okx_demo_sealed_strategy_conversion_mismatch"
        ):
            replay.execute(
                forecast=forecast,
                observation=_observation(forecast),
                phase="forged_conversion",
            )
        assert replay.venue.state["submit_count"] == 0
        assert replay.venue.state["fills"] == []
