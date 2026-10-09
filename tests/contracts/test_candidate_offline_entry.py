"""Ticket-only offline entry and independently reported boundary regressions."""
from types import SimpleNamespace
from decimal import Decimal
from copy import deepcopy
from datetime import timedelta
import pytest

from quant_shared.strategy_delivery.models import DeliveryError, digest
from tests.contracts.test_registered_candidate_execution import prepared, cases, ROOT
from quant_crypto.application.btc_registered_candidate import (
    VerifiedRegisteredInputs, verify_registered_candidate_inputs,
    open_btc_registered_candidate_offline)


def test_review_p1_context_subclass_is_not_an_authority():
    with pytest.raises((TypeError, DeliveryError)):
        class Forged(VerifiedRegisteredInputs):
            def check(self): return {"forged":True}
            def forecast(self,index): return None


@pytest.mark.parametrize("field,value", [
    ("adapter_id", "factory_lgbm_ast_v1"),
    ("initial_equity_usdt", 4999),
    ("currency", "USD"),
])
def test_history_account_contract_mismatch_precedes_economic_state(
    tmp_path, field, value
):
    import json
    from backend.app.services.candidate_delivery_accounts import DeliveryAccounts

    output_root = tmp_path / "economic-history"
    runtime = {
        "schema_version": "delivery_offline_runtime_v2",
        "adapter_id": "btc_donchian_history_offline_v1",
        "output_root": str(output_root.resolve()),
        "run_id": "history-account-test",
        "initial_equity_usdt": 5000,
        "currency": "USDT",
        "equity_unit": "USDT",
    }
    runtime[field] = value
    catalog = tmp_path / "catalog" / "accounts.json"
    catalog.parent.mkdir()
    catalog.write_text(json.dumps({
        "schema_version": "delivery_account_catalog_v1",
        "accounts": [{
            "account_ref": "history-account-test",
            "environment": "offline",
            "revision": 1,
            "market": "crypto",
            "instruments": ["BTC-USDT-SWAP"],
            "currency": "USDT",
            "expires_at": "2027-01-01T00:00:00+00:00",
            "simulation_namespace": "history-account-test",
            "offline_runtime": runtime,
        }],
    }), encoding="utf-8")
    accounts = DeliveryAccounts(catalog, repo_root=ROOT)
    with pytest.raises(DeliveryError, match="account_catalog_invalid_or_unverified"):
        accounts.get("history-account-test")
    assert not output_root.exists()


def test_history_input_digest_or_spec_mismatch_precedes_data_load(tmp_path, monkeypatch):
    import hashlib
    import json
    import subprocess
    from backend.app.services.candidate_offline_inputs import OfflineInputs
    from quant_crypto.application.donchian_history_spec import HistorySpec

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    row = {
        "schema_version": "candidate_offline_donchian_history_v1",
        "input_revision_id": "invalid-history-input",
        "evidence_kind": "verified_historical_observations",
        "input_head": head,
        "history_spec_git": f"{head}:docs/research/donchian-long-50usdt-20260921.json",
        "history_spec_blob_sha256": "not-a-hash",
        "history_spec_digest": "1" * 64,
    }
    row["content_digest"] = digest(row)
    catalog = {
        "schema_version": "candidate_offline_catalog_v1",
        "repository_owner": digest({"repository": str(ROOT.resolve())}),
        "revision": "invalid-history-v1",
        "factory_root": "factory",
        "qlib_root": "qlib",
        "sources": [],
        "inputs": [row],
    }
    path = tmp_path / "offline-catalog.json"
    raw = json.dumps(catalog, separators=(",", ":")).encode()
    path.write_bytes(raw)
    inputs = OfflineInputs(
        path, hashlib.sha256(raw).hexdigest(), "invalid-history-v1", repo=ROOT
    )
    monkeypatch.setattr(
        HistorySpec,
        "from_git",
        classmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("heavy spec/data load reached")
        )),
    )
    with pytest.raises(DeliveryError, match="offline_donchian_input_revision_mismatch"):
        inputs.load(row["input_revision_id"], row["content_digest"])


@pytest.mark.parametrize("attack",["construct","instance_method","fake_service"])
def test_review_p1_supported_entry_rejects_context_forgery(tmp_path,cases,attack):
    service,row,kw,_=prepared(tmp_path,cases[0])
    args={k:v for k,v in kw.items() if k!="repo_root"}
    inputs=verify_registered_candidate_inputs(service,row["id"],**args)
    with pytest.raises((TypeError,AttributeError,DeliveryError)):
        if attack=="construct":
            VerifiedRegisteredInputs(service=service,row=row,bars=kw["bars"],manifest=kw["market_manifest"],
                observations=kw["observations"],predictions=inputs.predictions,state_dir=kw["state_dir"])
        elif attack=="instance_method":
            inputs.check=lambda:row
        else:
            fake=SimpleNamespace(resolve=lambda *a,**k:row)
            verify_registered_candidate_inputs(fake,row["id"],**args)
    assert not kw["state_dir"].exists()


def test_review_p1_registered_protection_matches_frozen_four_percent(tmp_path,cases):
    service,row,kw,_=prepared(tmp_path,cases[0])
    with open_btc_registered_candidate_offline(service,row["id"],**kw) as runtime:
        assert runtime.controller._protection_policy.sl_distance_bps==Decimal("400")


def short_case(case):
    """New synthetic model before sealing, not mutated evidence or new research."""
    import hashlib
    import lightgbm as lgb
    import numpy as np
    from tests.contracts.test_candidate_package_runtime import attach_test_receipt
    p, bars, features, _ = case
    p = deepcopy(p)
    model = lgb.Booster(model_str=p["model"]["text"])
    def negate(tree, node):
        if "leaf_index" in node: model.set_leaf_output(tree, node["leaf_index"], -node["leaf_value"])
        else:
            negate(tree, node["left_child"]); negate(tree, node["right_child"])
    for tree in model.dump_model()["tree_info"]: negate(tree["tree_index"], tree["tree_structure"])
    text = model.model_to_string()
    p["model"].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
    p["artifacts"]["model.txt"] = p["model"]["sha256"]
    p["source"]["candidate_id"] += "-short"
    receipt = p["evidence_receipt"]
    for rows in (receipt["fit_rows"], receipt["audit_rows"]):
        values = model.predict(np.array([[np.nan if v is None else v for v in r["features"]] for r in rows]), num_threads=1)
        for r, value in zip(rows, values): r.update(raw_score=float(value), label=float(value))
    attach_test_receipt(p, fit_rows=receipt["fit_rows"], audit_rows=receipt["audit_rows"])
    return p, bars, features, model


@pytest.mark.parametrize("direction,leg", [("long", "sl"), ("long", "tp"), ("short", "sl"), ("short", "tp")])
def test_actual_registered_protection_executes_once_and_recovers_ledger(
    tmp_path,cases,monkeypatch,direction,leg
):
    from quant_crypto.application.qlib_offline_replay import OfflineMaintenanceFact
    case = cases[0] if direction == "long" else short_case(cases[0])
    service,row,kw,_=prepared(tmp_path,case)
    interrupted = direction == "long" and leg == "sl"
    with open_btc_registered_candidate_offline(service,row["id"],**kw) as runtime:
        result=runtime.execute_registered(0)
        assert result["fill_count"]==1
        state=runtime.venue.state
        algo=deepcopy(state["algos"][0]); order=state["orders"][0]
        entry=Decimal(order["px"])
        sign=1 if direction=="long" else -1
        assert order["posSide"]==direction
        assert abs(Decimal(algo["slTriggerPx"])-entry*(1-sign*Decimal('.04')))<=Decimal('.1')
        assert abs(Decimal(algo["tpTriggerPx"])-entry*(1+sign*Decimal('.08')))<=Decimal('.1')
        policy_hash=runtime.controller._protection_policy.policy_sha256
        # A 2 percent adverse sampled move does not touch the actual 4 percent
        # OCO. This is NOT a claim that the separate 3 percent trailing rule is off.
        assert runtime._registered_protection_guard(
            runtime.venue.now+timedelta(seconds=1), entry*(1-sign*Decimal('.02')), entry
        ) is False
        at=runtime.venue.now+timedelta(seconds=90)
        mark=Decimal(algo[leg+"TriggerPx"])
        mark *= Decimal("0.999") if (direction,leg) in {("long","sl"),("short","tp")} else Decimal("1.001")
        original_commit = runtime._commit_registered_protection_receipt
        if interrupted:
            monkeypatch.setattr(
                runtime, "_commit_registered_protection_receipt",
                lambda _receipt: (_ for _ in ()).throw(RuntimeError("after_protection_fill_before_ledger")),
            )
            with pytest.raises(RuntimeError,match="after_protection_fill_before_ledger"):
                runtime._advance_offline_time(
                    target_utc=at,
                    facts=(OfflineMaintenanceFact(at,float(mark),float(mark)),),
                )
            monkeypatch.setattr(runtime,"_commit_registered_protection_receipt",original_commit)
        else:
            runtime._advance_offline_time(target_utc=at,facts=(OfflineMaintenanceFact(at,mark,mark),))
        assert state["position"]=="0" and state["algos"]==[]
        assert len(state["orders"])==2 and len(state["fills"])==2
        fill=deepcopy(state["fills"][-1])
        expected=mark*(Decimal("0.9994") if direction=="long" else Decimal("1.0006"))
        assert Decimal(fill["fillPx"])==expected
        assert Decimal(fill["fee"])<0
        assert fill["triggerKind"]==( "stop_loss" if leg=="sl" else "take_profit")
        assert fill["protectionAlgoId"]==algo["algoId"]
        assert fill["parentClOrdId"]==order["clOrdId"]
        assert fill["parentOrdId"]==order["ordId"]
        assert fill["parentFillId"]==state["fills"][0]["tradeId"]
        assert fill["observationSource"]=="verified_registered_maintenance_fact"
        assert fill["pricePolicy"]=="registered_offline_sampled_mark_protection_price_v1"
        assert len(fill["pricePolicySha256"])==64
        assert Decimal(fill["triggerThresholdPx"])==Decimal(algo[leg+"TriggerPx"])
        assert Decimal(fill["triggerReferencePx"])==mark
        assert runtime._registered_protection_guard(at,mark,mark) is False
        assert len(state["fills"])==2
    with open_btc_registered_candidate_offline(service,row["id"],**kw) as runtime:
        assert runtime.controller._protection_policy.policy_sha256==policy_hash
        for _ in range(2):
            runtime._repair_registered_protection_evidence()
        assert runtime.venue.state["algos"]==[]
        assert len(runtime.venue.state["orders"])==2
        assert len(runtime.venue.state["fills"])==2
        assert runtime.venue.state["fills"][-1]==fill
        ledger=runtime.controller._state["ledger_reconciliation"]["account_ledger_replay"]
        assert ledger["status"]=="reconciled" and ledger["reconciled"] is True
        events=runtime.controller._runtime_store.recover().events
        receipts=[e for e in events if e["event_type"]=="registered_protection_executed"]
        assert len(receipts)==1 and receipts[0]["payload"]["fill"]==fill


@pytest.mark.parametrize("field,value", [("take_profit_fraction",None),("take_profit_fraction",.6),("hard_stop_fraction",.3),
                                          ("protection",{}),("take_profit_fraction",float('nan'))])
def test_unrepresentable_protection_is_not_defaulted(cases,field,value):
    from quant_crypto.application.btc_registered_candidate import registered_protection_policy
    p=deepcopy(cases[0][0])
    p["contracts"]["exit"].update(take_profit_fraction=.08,protection={"version":"registered_offline_oco_v1","trigger":"mark",
        "reference_price":"aggressive_limit_at_order_construction","effective":"attached_after_fill"})
    p["contracts"]["exit"][field]=value
    with pytest.raises(DeliveryError,match="registered_protection_contract_unsupported"):registered_protection_policy(p)


def test_legacy_missing_tp_rejected_before_runtime_constructor(tmp_path,cases,monkeypatch):
    from quant_crypto.application.qlib_offline_replay import QlibFixtureOfflineReplay
    service,row,kw,_=prepared(tmp_path,cases[0],protection=False)
    def denied(*a,**k):raise AssertionError("economic constructor reached")
    monkeypatch.setattr(QlibFixtureOfflineReplay,"__init__",denied)
    with pytest.raises(DeliveryError,match="registered_protection_contract_unsupported"):
        open_btc_registered_candidate_offline(service,row["id"],**kw)
    assert not kw["state_dir"].exists()
