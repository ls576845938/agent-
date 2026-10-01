"""M1 forbids changes to actual execution or factory selection, not just UI flags."""
import subprocess
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import uuid

import pandas as pd

from quant_crypto.application.btc_strategy_registry import btc_strategy_registry

BASE = "c1d11987d28f06bb0fe89b2c289e88d07522790d"
ROOT = Path(__file__).resolve().parents[2]
PROTECTED = ("quant_crypto", "quant_shared/strategy_runtime", "quant_shared/runtime",
             "quant_shared/alpha_factory", "quant_us/backtest", "backend/app/services/btc_demo_runtime.py",
             "configs/qlib/okx_btc_trend_1h.yaml", "configs/universe/okx_btc_perpetual_1h.yaml")
APPROVED_POST_M1_SAFETY_BLOBS = {
    "backend/app/services/btc_demo_runtime.py": "70581b116e861985d262e7e34c331dca3d646120",
    "quant_crypto/application/btc_demo_production_composition.py": "450cbae312bb1169ce2c46eb37f18d4344f5f530",
    "quant_crypto/application/runtime_risk_guardian.py": "c8e2f74751803a3a466bf6881681011a1adf6d4a",
    "quant_crypto/oms/account_risk_facts.py": "b02c4e0f0dc2e58154a0caf07068f8d13704c606",
    "quant_crypto/oms/okx_demo_paper_runtime.py": "30f0926fb515e7b3f791c11057bf60cb308482fa",
    "quant_crypto/oms/runtime_store.py": "682513576b679de934d5a18b7d29798e3a387b97",
}


def test_m1_history_stays_frozen_with_only_reviewed_post_m1_safety_fixes():
    """Bind M1 to its reviewed commit while freezing the exact safety delta.

    M1's historical invariant remains immutable.  Post-M1 execution safety
    corrections are allowed only at the reviewed blob identities below; every
    other protected path must still match the M1 commit exactly.
    """

    subprocess.check_call(["git", "cat-file", "-e", f"{BASE}^{{commit}}"], cwd=ROOT)
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", BASE, "--", *PROTECTED],
        cwd=ROOT,
        text=True,
    ).splitlines()
    assert changed == list(APPROVED_POST_M1_SAFETY_BLOBS)
    for path, expected_blob in APPROVED_POST_M1_SAFETY_BLOBS.items():
        actual_blob = subprocess.check_output(
            ["git", "hash-object", path],
            cwd=ROOT,
            text=True,
        ).strip()
        assert actual_blob == expected_blob


def test_default_btc_candidate_and_parameters_are_frozen():
    spec = next(s for s in btc_strategy_registry.list_specs() if s.strategy_id == "long_short_donchian_top5_okx_native")
    assert spec.candidate_id == "okx_native_btc_ls_tf_formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone_78f5f0a0e4"
    assert spec.params_hash == "5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355"


def test_default_signal_plans_protection_and_native_ledger_are_observer_invariant(tmp_path, monkeypatch):
    """Synthetic transport facts, real registered signal/planner/protection and ledger UoW.

    This does not start a runtime or exercise an exchange. Actual T2/T3/Guardian
    composition is separately covered by the unchanged 169-test baseline.
    """
    import quant_crypto.oms.okx_demo_paper_runtime as runtime
    from quant_shared.trend_environment import Bar, EnvironmentConfig, estimate

    now = datetime(2026, 7, 30, 12, 5, tzinfo=timezone.utc)
    times = pd.date_range(end=now.replace(minute=0), periods=5200, freq="h")
    values = [60000 + i*.1 for i in range(len(times))]
    frame = pd.DataFrame({"open_time":times-pd.Timedelta(hours=1), "open":values,
        "high":[x+1 for x in values], "low":[x-1 for x in values], "close":values, "volume":1.}, index=times)
    original_frame = frame.copy(deep=True)
    monkeypatch.setattr(runtime, "load_completed_okx_native_hourly_frame", lambda *a,**k: frame)
    monkeypatch.setattr(runtime.uuid, "uuid4", lambda: uuid.UUID(int=1))
    spec = next(s for s in btc_strategy_registry.list_specs() if s.strategy_id == "long_short_donchian_top5_okx_native")
    def forbidden(*a,**k): raise AssertionError("M1 must not access credentials or network")
    monkeypatch.setattr(runtime.OkxDemoClient, "public_get", forbidden)
    monkeypatch.setattr(runtime.OkxDemoClient, "private_get", forbidden)
    monkeypatch.setattr(runtime.OkxDemoClient, "submit_order", forbidden)
    results = []
    for mode in ("off", "on", "failure"):
        controller = runtime.OkxDemoPaperRuntimeController(config=runtime.OkxDemoPaperRuntimeConfig(
            repo_root=ROOT, data_db_path=tmp_path/"unused.sqlite", output_dir=tmp_path/mode,
            max_configured_leverage=Decimal("1"), risk_profile="baseline_1x", runtime_identity="m1-frozen-runtime"),
            credential_loader=forbidden, clock=lambda:now, start_worker=False)
        controller._state["runtime"].update(run_id="m1frozen", order_sequence=0, active=False)
        controller._protection_policy = runtime.ServerSideProtectionPolicy.from_mapping(runtime.OKX_DEMO_APPROVED_PROTECTION_POLICY)
        before = deepcopy(controller._state)
        if mode != "off":
            try:
                if mode == "failure": raise ValueError("explicit_observer_failure")
                bars = [Bar("BTC", t.to_pydatetime()-timedelta(hours=1), t.to_pydatetime(), t.to_pydatetime(), float(c))
                        for t,c in frame.close.iloc[-171:].items()]
                observations = estimate(bars, asset="BTC", decision_time=times[-1].to_pydatetime(),
                    expected_close_times=[b.close_time for b in bars], config=EnvironmentConfig((24,72,168),"UTC_24x7",8760,3600))
                assert all(row["status"] == "observed" for row in observations)
            except ValueError as exc:
                assert mode == "failure" and str(exc) == "explicit_observer_failure"
        assert controller._state == before
        pd.testing.assert_frame_equal(frame, original_frame)
        signal = controller._signal_decision(spec.identity())
        snapshot = {"ticker":{"bid":"60000","ask":"60000.1"}, "instrument":{"tick_size":"0.1","lot_size":"0.01"},
                    "price_limit":{"buy":"70000","sell":"50000"}, "book":{"bids":[["60000","1"]],"asks":[["60000.1","1"]]},
                    "fee_schedule":{"taker_rate":"-0.0005"},"funding":{"funding_rate":"0.0001"}}
        plans = [controller._build_order_plan(snapshot, current_quantity=Decimal(current), target_quantity=Decimal(target))
                 for current,target in (("0","0.01"),("0.01","0.01"),("0.01","-0.01"),("-0.01","0"))]
        assert plans[0]["attached_protection"] and plans[1] is None and plans[2]["reversal_close_only"]
        assert plans[0]["risk"]["fee_bps"] == "5"
        ledger_snapshot = {**snapshot, "captured_at_utc":now.isoformat(), "orders":[{"order_id":"order-1","state":"filled"}],
            "pending_orders":[], "fills":[{"fill_id":"fill-1","order_id":"order-1","price":"60000","size":"0.01"}],
            "positions":[], "balance":{"equity_usdt":"100","available_usdt":"99"},
            "bills":[{"bill_id":"funding-1","instrument_id":"BTC-USDT-SWAP","type":"8","sub_type":"173","balance_change":"-0.001"}],
            "mark":{"mark_price":"60000"},"index":{"index_price":"59999"}}
        with controller._lock: controller._apply_snapshot(ledger_snapshot)
        controller._commit_new_funding_if_observed(snapshot=ledger_snapshot)
        controller._commit_new_funding_if_observed(snapshot=ledger_snapshot)
        events = [json.loads(line) for line in (tmp_path/mode/"events.jsonl").read_text(encoding="utf-8").splitlines()]
        ledger = [e["payload"] for e in events if e["event_type"] == "ledger_uow_committed"]
        assert len(ledger) == 1 and ledger[0]["funding_ledger"]["cashflow"] == "-0.001"
        results.append({"signal":signal,"plans":plans,"ledger":ledger,"reconciliation":controller._state["ledger_reconciliation"]})
    assert results[0] == results[1] == results[2]
    negative = deepcopy(results[0]); negative["plans"][0]["risk"]["fee_bps"] = "6"
    assert negative != results[0]  # Non-empty baseline detects an economically material change.
