"""Authorized offline 50 USDT exposure, unchanged 10 USDT loss budgets."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import socket
import json

import pytest

from quant_crypto.application.donchian_history_spec import HistorySpec, legacy_spec
from quant_crypto.application.donchian_offline_replay import DonchianOfflineReplay, DonchianOfflineReplayConfig
from quant_crypto.application.btc_demo_production_composition import BtcDemoProductionComposition
from quant_crypto.oms.okx_demo_paper_runtime import OKX_DEMO_PAPER_MAX_NOTIONAL_USDT


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("offline network prohibited")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def config(tmp_path, **kwargs):
    return DonchianOfflineReplayConfig(repo_root=Path.cwd(), state_dir=tmp_path/"state",
        run_id="offline-budget-check", decision_time_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        data_version="explicit-test-only", **kwargs)


def spec50():
    payload = legacy_spec().payload
    payload["schema_version"] = "btc_donchian_history_spec_v2"
    payload["execution"]["max_notional_usdt"] = "50"
    payload["execution"]["max_loss_usdt"] = "10"
    return payload


def test_legacy_spec_and_default_production_limits_unchanged(tmp_path):
    assert legacy_spec().payload["schema_version"] == "btc_donchian_history_spec_v1"
    assert "max_notional_usdt" not in legacy_spec().payload["execution"]
    assert OKX_DEMO_PAPER_MAX_NOTIONAL_USDT == Decimal("10")
    assert config(tmp_path).max_notional_usdt == Decimal("10")
    composition = BtcDemoProductionComposition(source_head="a"*40)
    assert composition.max_notional == Decimal("10")
    assert composition.loss_limit_usdt == Decimal("10")


def test_explicit_spec_preserves_everything_except_envelope():
    new = HistorySpec.from_payload(spec50())
    assert new.digest != legacy_spec().digest
    assert new.payload["strategy"] == legacy_spec().payload["strategy"]
    assert new.payload["budget"] == legacy_spec().payload["budget"]
    for key, value in legacy_spec().payload["execution"].items():
        assert new.payload["execution"][key] == value


@pytest.mark.parametrize("key,value", [("max_notional_usdt", "51"), ("max_loss_usdt", "50"), ("order_contracts", ".02")])
def test_unauthorized_spec_limits_fail_closed(key, value):
    payload = spec50()
    payload["execution"][key] = value
    with pytest.raises(ValueError): HistorySpec.from_payload(payload)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("0"), Decimal("51"), "50", True])
def test_bad_offline_limit_rejected_without_state(tmp_path, value):
    with pytest.raises(ValueError): config(tmp_path, max_notional_usdt=value)
    assert not (tmp_path/"state").exists()


def test_fifty_limit_reaches_runtime_and_composition_not_losses(tmp_path):
    runner = DonchianOfflineReplay(config(tmp_path, max_notional_usdt=Decimal("50")))
    try:
        assert runner.controller._configured_limits() == (Decimal(".01"), Decimal(".01"), Decimal("50"))
        assert runner.composition.max_notional == Decimal("50")
        assert runner.composition.loss_limit_usdt == Decimal("10")
        guardian = runner.guardian_supervisor.guardian.config
        assert guardian.max_abs_exposure == 50
        assert guardian.max_daily_loss == guardian.max_drawdown == 10
        assert runner.identity["offline_budget"] == {"max_notional_usdt": "50", "max_loss_usdt": "10"}
        snapshot = runner.controller._collect_exchange_snapshot(runner.venue)
        snapshot["ticker"] = {**snapshot["ticker"], "bid": "108160.99168", "ask": "108171.80832"}
        assert "okx_demo_paper_minimum_order_exceeds_10_usdt" not in runner.controller._preflight_blockers(snapshot, require_flat=True)
        snapshot["ticker"] = {**snapshot["ticker"], "bid": "500099", "ask": "500100"}
        assert "okx_demo_paper_minimum_order_exceeds_10_usdt" in runner.controller._preflight_blockers(snapshot, require_flat=True)
    finally:
        runner.close()


def test_changing_budget_cannot_resume_old_state(tmp_path):
    original = config(tmp_path)
    runner = DonchianOfflineReplay(original)
    runner.close()
    identity_path = tmp_path/"state"/"offline_replay_identity.json"
    before = identity_path.read_bytes()
    with pytest.raises(ValueError, match="identity_mismatch"):
        DonchianOfflineReplay(replace(original, max_notional_usdt=Decimal("50")))
    assert identity_path.read_bytes() == before


@pytest.mark.parametrize("value", ["0", "NaN", "-1", "Infinity"])
def test_invalid_explicit_composition_loss_budget_rejected(value):
    with pytest.raises(ValueError, match="loss"):
        BtcDemoProductionComposition(source_head="a"*40, max_loss_usdt=Decimal(value))


def test_composition_legacy_custom_notional_keeps_previous_loss_fallback():
    c = BtcDemoProductionComposition(source_head="a"*40, max_notional=Decimal("25"))
    assert c.loss_limit_usdt == Decimal("25")


def test_actual_order_risk_uses_separate_loss_budget(tmp_path, monkeypatch):
    from quant_crypto.application import btc_demo_production_composition as composition_module
    from quant_crypto.application.donchian_offline_replay import build_closeout_scenario
    fixture = json.loads((Path(__file__).parents[1]/"fixtures/strategy_v1/offline_contract.json").read_text())
    scenario = build_closeout_scenario(start=datetime.fromisoformat(fixture["scenario"]["start_utc"]))
    captured = []
    original = composition_module.assess_btc_risk

    def observe(*args, **kwargs):
        captured.append(kwargs["constitution"])
        return original(*args, **kwargs)

    monkeypatch.setattr(composition_module, "assess_btc_risk", observe)
    runner = DonchianOfflineReplay(replace(config(tmp_path, max_notional_usdt=Decimal("50")),
        decision_time_utc=datetime.fromisoformat(fixture["scenario"]["observation_time_utc"])))
    try:
        opened = runner.run_frame(scenario.iloc[:fixture["scenario"]["checkpoint_offsets"]["open_long"]+1])
        assert opened["fill_count"] == 1
        assert captured
        for policy in captured:
            assert policy.max_notional == 50
            assert policy.max_daily_loss == policy.max_drawdown == policy.max_combined_loss == 10
    finally:
        runner.close()
