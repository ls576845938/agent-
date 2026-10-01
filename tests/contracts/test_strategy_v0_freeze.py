"""V0 characterization, not a new strategy or proof of execution readiness.

The original registered formula/controller/policy are the test subjects.
Fixtures are synthetic and no runtime is started. The archive check is explicit
because immutable shared data is not part of a portable source checkout.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess

import pandas as pd
import pytest

from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
from quant_crypto.research.long_short_trend_following_lab import (
    _stateful_long_short_with_atr_trail,
)

ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "tests/fixtures/strategy_v0/baseline.json"
NOW = datetime(2026, 7, 30, 12, 5, tzinfo=timezone.utc)


def _forbidden(*args, **kwargs):
    raise AssertionError("V0 forbids network, credentials, workers and transport")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)


@pytest.fixture(scope="module")
def freeze():
    return json.loads(FREEZE.read_text(encoding="utf-8"))


def _frame(kind: str) -> pd.DataFrame:
    times = pd.date_range(end=NOW.replace(minute=0), periods=5200, freq="h")
    close = {
        "long": lambda i: 10000.0 + i * 8.0,
        "short": lambda i: 90000.0 - i * 8.0,
        "flat": lambda i: 60000.0,
    }[kind]
    values = [close(i) for i in range(len(times))]
    return pd.DataFrame({"open_time": times - pd.Timedelta(hours=1),
                         "open": values, "high": [x + 1 for x in values],
                         "low": [x - 1 for x in values], "close": values,
                         "volume": 1.0}, index=times)


@pytest.fixture
def controller(tmp_path, monkeypatch):
    import quant_crypto.oms.okx_demo_paper_runtime as runtime
    monkeypatch.setattr(runtime.OkxDemoClient, "public_get", _forbidden)
    monkeypatch.setattr(runtime.OkxDemoClient, "private_get", _forbidden)
    monkeypatch.setattr(runtime.OkxDemoClient, "submit_order", _forbidden)
    ctl = runtime.OkxDemoPaperRuntimeController(
        config=runtime.OkxDemoPaperRuntimeConfig(
            repo_root=ROOT, data_db_path=tmp_path / "never-open.sqlite",
            output_dir=tmp_path / "isolated-v0", risk_profile="baseline_1x",
            max_configured_leverage=Decimal("1"), runtime_identity="v0-fixture"),
        credential_loader=_forbidden, client_factory=_forbidden,
        private_ws_factory=_forbidden, clock=lambda: NOW, start_worker=False,
        start_capability_checker=_forbidden)
    ctl._state["runtime"].update(run_id="v0freeze", active=False, order_sequence=0)
    ctl._protection_policy = runtime.ServerSideProtectionPolicy.from_mapping(
        runtime.OKX_DEMO_APPROVED_PROTECTION_POLICY)
    return ctl


def _snapshot():
    return {"ticker": {"bid": "60000", "ask": "60000.1"},
            "instrument": {"tick_size": "0.1", "lot_size": "0.01"},
            "price_limit": {"buy": "70000", "sell": "50000"},
            "book": {"bids": [["60000", "1"]], "asks": [["60000.1", "1"]]},
            "fee_schedule": {"taker_rate": "-0.0005"},
            "funding": {"funding_rate": "0.0001"}}


def test_frozen_identity_and_source_objects(freeze):
    spec = btc_strategy_registry.get(freeze["donchian"]["strategy_id"])
    for key in ("candidate_id", "strategy_version", "params_hash", "timeframe"):
        assert spec.identity()[key] == freeze["donchian"][key]
    assert dict(spec.params) == freeze["donchian"]["params"]
    # Historical objects remain addressable; this does NOT prohibit reviewed V1
    # edits forever or assert that a whole-file hash proves behavioral parity.
    for path, blob in freeze["source_blobs"].items():
        actual = subprocess.check_output(
            ["git", "rev-parse", f"{freeze['base_commit']}:{path}"], cwd=ROOT, text=True).strip()
        assert actual == blob
    assert spec.backtest_execution.target_weight == 0.98
    assert freeze["donchian"]["runtime_target_rule"] == "sign(raw_signal)*0.01_contracts"


@pytest.mark.parametrize("kind", ["long", "short", "flat"])
def test_actual_registered_signal_and_runtime_target(freeze, controller, monkeypatch, kind):
    import quant_crypto.oms.okx_demo_paper_runtime as runtime
    frame = _frame(kind)
    original = frame.copy(deep=True)
    monkeypatch.setattr(runtime, "load_completed_okx_native_hourly_frame", lambda *a, **k: frame)
    spec = btc_strategy_registry.get(freeze["donchian"]["strategy_id"])
    result = controller._signal_decision(spec.identity())
    for key, value in freeze["signals"][kind].items():
        assert result[key] == value
    assert controller._signal_decision(spec.identity()) == result
    assert controller._state["runtime"]["order_sequence"] == 0
    pd.testing.assert_frame_equal(frame, original)


def test_registered_formula_prefix_invariance_and_warmup(freeze):
    spec = btc_strategy_registry.get(freeze["donchian"]["strategy_id"])
    frame = _frame("long")
    cutoff = 5160  # Completed daily/4h boundary, with enough daily warmup.
    full = spec.signal_callable(frame, "1h")
    prefix = spec.signal_callable(frame.iloc[:cutoff].copy(), "1h")
    pd.testing.assert_series_equal(full.loc[prefix.index], prefix)
    assert (spec.signal_callable(frame.iloc[:48].copy(), "1h") == 0).all()


def test_negative_control_detects_runtime_contract_size_drift(freeze, controller, monkeypatch):
    import quant_crypto.oms.okx_demo_paper_runtime as runtime
    frame = _frame("long")
    monkeypatch.setattr(runtime, "load_completed_okx_native_hourly_frame", lambda *a, **k: frame)
    monkeypatch.setattr(runtime, "OKX_DEMO_PAPER_CONTRACTS", Decimal("0.02"))
    actual = controller._signal_decision(freeze["donchian"])
    assert actual["target_contracts"] == "0.02"
    with pytest.raises(AssertionError):
        assert actual["target_contracts"] == freeze["signals"]["long"]["target_contracts"]


@pytest.mark.parametrize("case", ["open_long", "open_short", "hold_long", "hold_short",
                                  "reverse_long", "reverse_short", "close_long", "close_short"])
def test_actual_order_plan_business_baseline(freeze, controller, case):
    expected = freeze["plans"][case]
    result = controller._build_order_plan(
        _snapshot(), current_quantity=Decimal(expected["before"]),
        target_quantity=Decimal(expected["target"]))
    if expected["result"] is None:
        assert result is None
        assert controller._sequence == 0
        return
    for key, value in expected["result"].items():
        assert result[key] == value
    for key, value in freeze["donchian"]["cost_fixture"].items():
        assert result["risk"][key] == value
    assert bool(result["attached_protection"]) == case.startswith("open_")
    assert controller._sequence == 1


@pytest.mark.parametrize("lot,target,reason", [
    ("0.03", "0.01", "order_delta_not_exact"),
    ("0.01", "0.02", "order_delta_not_exact"),
])
def test_invalid_quantity_is_rejected_before_sequence(controller, lot, target, reason):
    from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeError
    snapshot = _snapshot()
    snapshot["instrument"]["lot_size"] = lot
    with pytest.raises(OkxDemoPaperRuntimeError, match=reason):
        controller._build_order_plan(snapshot, current_quantity=Decimal("0"),
                                     target_quantity=Decimal(target))
    assert controller._sequence == 0


@pytest.mark.parametrize("reason", ["fixture_missing_data", "fixture_stale_data"])
def test_loader_failure_propagates_without_fallback(freeze, controller, monkeypatch, reason):
    import quant_crypto.oms.okx_demo_paper_runtime as runtime
    def reject(*args, **kwargs):
        raise runtime.OkxDemoPaperRuntimeError(reason)
    monkeypatch.setattr(runtime, "load_completed_okx_native_hourly_frame", reject)
    with pytest.raises(runtime.OkxDemoPaperRuntimeError, match=reason):
        controller._signal_decision(freeze["donchian"])
    assert controller._sequence == 0


@pytest.mark.parametrize("case", ["long_atr", "short_atr", "channel_exit", "reverse_exit"])
def test_original_exit_cooldown_policy(freeze, case):
    row = freeze["exits"][case]
    index = pd.date_range("2026-01-01", periods=len(row["close"]), freq="4h", tz="UTC")
    def flags(name):
        return pd.Series([i in row.get(name, []) for i in range(len(index))], index=index)
    actual = _stateful_long_short_with_atr_trail(
        flags("long_entry"), flags("long_exit"), flags("short_entry"), flags("short_exit"),
        close=pd.Series(row["close"], index=index), atr=pd.Series(1.0, index=index),
        atr_mult=2.0, cooldown_bars=12, use_failed_breakout_exit=False)
    assert actual.tolist() == row["expected"]


def test_candidate_registration_is_not_runtime_permission(freeze):
    assert freeze["scope"] == "v0_freeze_only"
    assert all(value is False for value in freeze["permissions"].values())
    assert freeze["qlib"]["execution_binding_status"] == "not_bound_research_only"
    assert freeze["release"]["v1_v3_publication_admitted"] is False
    assert freeze["contract"]["account_binding"] == "one_strategy_one_account_one_instrument"


@pytest.mark.skipif(os.environ.get("QS_V0_VERIFY_ARCHIVE") != "1",
                    reason="explicit local immutable-archive verification, no download/fallback")
def test_exact_qlib_archive_and_model_are_frozen(freeze):
    import lightgbm as lgb
    import yaml
    from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
    from integrations.qlib_adapter.research_pipeline import read_sealed_evidence
    catalog = ResearchArchiveCatalog(repo_root=ROOT)
    manifest, dataset_root = catalog._verified_dataset()
    assert manifest["aggregate_sha256"] == freeze["qlib"]["archive_aggregate_sha256"]
    run_root = dataset_root / "qlib_runs" / freeze["qlib"]["run_id"]
    for filename, expected in freeze["qlib"]["sha256"].items():
        assert hashlib.sha256((run_root / filename).read_bytes()).hexdigest() == expected
    evidence = read_sealed_evidence(run_root)
    assert evidence["integrity_status"] == "passed"
    trace = evidence["research_trace"]
    assert trace["identity"]["candidate_id"] == freeze["qlib"]["candidate_id"]
    assert trace["identity"]["code_version"] == freeze["qlib"]["source_code_version"]
    assert trace["decision_count"] == 1392 and trace["simulated_fill_count"] == 0
    assert trace["blockers"] == ["no_simulated_fills"]
    assert trace["execution_permission"] is False and trace["runtime_observed"] is False
    config = yaml.safe_load((run_root / "qlib_workflow_config.yaml").read_text(encoding="utf-8"))
    handler = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
    assert handler["data_loader"]["kwargs"]["config"]["feature"][1] == freeze["qlib"]["features_in_order"]
    assert handler["infer_processors"] == freeze["qlib"]["infer_processors"]
    for key in ("method", "intercept", "slope", "sample_size", "limitation"):
        assert trace["calibration"][key] == freeze["qlib"]["calibration"][key]
    model = lgb.Booster(model_str=(run_root / "model.txt").read_text(encoding="utf-8"))
    assert model.num_trees() == 1 and model.num_feature() == 13
    # Admission only: no fit, prediction, calibration refit or MLflow restore.
