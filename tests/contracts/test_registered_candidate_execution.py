"""Synthetic registered packages through the original offline BTC authority chain."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import socket
import subprocess
import json
import math
import shutil
import time

import pytest

from tests.integrations.test_candidate_package_inference import cases, sealed_factory
from tests.contracts.test_strategy_delivery import command
from quant_shared.strategy_delivery.models import DeliveryError, digest
from quant_shared.strategy_delivery.service import DeliveryService
from backend.app.services.candidate_delivery_store import DeliveryStore
from backend.app.services.candidate_delivery_accounts import DeliveryAccounts
from backend.app.services.candidate_delivery_sources import ResearchDeliverySources
from quant_crypto.application.btc_registered_candidate import (
    open_btc_registered_candidate_offline, offline_simulated_account_identity,
    market_frame_digest, observation_digest)
from quant_crypto.application.qlib_offline_replay import (CandidateMarketObservation, OfflineMaintenanceFact,
    FundingSettlementFact, _QlibOfflineVenue)
from integrations.qlib_adapter.package_inference import infer_package
from integrations.qlib_adapter.factory_package import compile_factory_package

ROOT = Path(__file__).resolve().parents[2]


def verify_registered_offline_cache_equivalence(*,legacy,cached,execution_windows):
    """Pure comparison for a legacy/cache pair captured by the offline replay test."""
    import quant_crypto.application.qlib_offline_replay as replay_module
    import quant_crypto.oms.runtime_store as runtime_store_module
    import quant_crypto.oms.shared_platform_v3 as shared_platform_module

    def differences(left,right,path=""):
        if type(left) is not type(right):return [(path,type(left).__name__,type(right).__name__)]
        if isinstance(left,dict):
            keys=set(left)|set(right)
            return [item for key in sorted(keys) for item in differences(left.get(key),right.get(key),path+"/"+key)]
        if isinstance(left,list):
            if len(left)!=len(right):return [(path+"/length",len(left),len(right))]
            return [item for index,(a,b) in enumerate(zip(left,right,strict=True))
                for item in differences(a,b,path+f"/{index}")]
        return [] if left==right else [(path,left,right)]

    expected={"/first/ledger_event_hash":"event_hash","/first/order_intent_id":"order_intent",
        "/duplicate/ledger_event_hash":"event_hash","/duplicate/order_intent_id":"order_intent"}
    expected.update({
        "/capture/intent/order_intent_id":"order_intent",
        "/capture/intent_binding_digest":"intent_digest",
        "/capture/intent_execution_digest":"execution_intent_digest",
        "/capture/bundle/intent/order_intent_id":"order_intent",
        "/capture/bundle/proof_identity/intent_digest":"execution_intent_digest",
        "/capture/bundle_digest":"oms_bundle_digest",
        "/capture/proof_identity/intent_digest":"execution_intent_digest",
        "/capture/proof_identity_digest":"proof_identity_digest",
    })
    wall_roles={
        "/risk_decision/checked_at":"risk_checked_at",
        **{f"/oms/events/{index}/timestamp_utc":f"oms_event_{index}" for index in range(1,7)},
    }
    terminal_suffixes={
        "/oms/events/0/metadata/order_intent_id":"order_intent",
        **{suffix:"wall_time" for suffix in wall_roles},
        "/oms/order_id":"order", "/oms/order_intent_id":"order_intent",
        "/risk_decision/metadata/oms_bundle_digest":"oms_bundle_digest",
        "/risk_decision/metadata/proof_identity_digest":"proof_identity_digest",
        "/risk_decision/order_intent_id":"order_intent",
        "/risk_decision/risk_check_id":"risk_check",
        "/sealed_strategy_binding/intent_sha256":"intent_digest",
    }
    prefixes=("/events/286/payload","/events/286/state_after/audit/0",
        "/events/287/payload/order_ledger/terminal_order","/events/287/state_after/audit/0",
        "/events/288/state_after/audit/0","/events/289/state_after/audit/0")
    for prefix in prefixes:
        expected.update({prefix+suffix:kind for suffix,kind in terminal_suffixes.items()})
    expected.update({
        "/events/286/event_hash":"event_hash","/events/286/idempotency_key":"idempotency_key",
        "/events/286/semantic_hash":"semantic_hash","/events/287/event_hash":"event_hash",
        "/events/287/previous_event_hash":"event_hash","/events/287/semantic_hash":"semantic_hash",
        "/events/288/event_hash":"event_hash","/events/288/previous_event_hash":"event_hash",
        "/events/288/semantic_hash":"semantic_hash","/events/289/event_hash":"event_hash",
        "/events/289/previous_event_hash":"event_hash",
        "/events/288/payload/binding/intent_sha256":"intent_digest",
        "/events/288/payload/result/ledger_event_hash":"event_hash",
        "/events/288/payload/result/order_intent_id":"order_intent",
    })

    def projected(value,prefix):
        row=value
        for part in prefix.strip("/").split("/"):
            row=row[int(part)] if isinstance(row,list) else row[part]
        return row

    def assert_preimages_and_chain(value):
        capture=value["capture"]
        assert capture["bundle"]["proof_identity"]==capture["proof_identity"]
        assert capture["intent_binding_digest"]==replay_module._canonical_sha256(capture["intent"])
        assert capture["bundle"]["proof_identity"]["intent_digest"]==capture["intent_execution_digest"]
        assert capture["bundle_digest"]==shared_platform_module._digest(capture["bundle"])
        assert capture["proof_identity_digest"]==shared_platform_module._digest(capture["proof_identity"])
        previous=""
        for sequence,event in enumerate(value["events"],start=1):
            assert event["sequence"]==sequence and event["previous_event_hash"]==previous
            assert event["semantic_hash"]==runtime_store_module._digest({
                "event_type":event["event_type"],"payload":event["payload"],"run_id":event["run_id"]})
            body={key:item for key,item in event.items() if key!="event_hash"}
            assert event["event_hash"]==runtime_store_module._digest(body)
            previous=event["event_hash"]
        lifecycle=value["events"][286]
        role_id=capture["intent"]["order_intent_id"]
        assert lifecycle["event_type"]=="order_lifecycle"
        assert lifecycle["payload"]["oms"]["order_intent_id"]==role_id
        assert lifecycle["idempotency_key"]==hashlib.sha256(json.dumps([
            lifecycle["run_id"],lifecycle["event_type"],lifecycle["payload"]
        ],sort_keys=True,separators=(",",":")).encode()).hexdigest()
        for prefix in prefixes:
            audit=projected(value,prefix)
            assert audit["sealed_strategy_binding"]["intent_sha256"]==capture["intent_binding_digest"]
            assert audit["risk_decision"]["metadata"]["oms_bundle_digest"]==capture["bundle_digest"]
            assert audit["risk_decision"]["metadata"]["proof_identity_digest"]==capture["proof_identity_digest"]

    def normalize(value,window):
        mapping_kinds=("order_intent","order","risk_check","intent_digest","execution_intent_digest",
            "oms_bundle_digest","proof_identity_digest","event_hash","semantic_hash","idempotency_key")
        mappings={name:{} for name in mapping_kinds}
        execution_started=datetime.fromisoformat(window["execution_started_at_utc"].replace("Z","+00:00"))
        execution_completed=datetime.fromisoformat(window["execution_completed_at_utc"].replace("Z","+00:00"))
        assert execution_started.utcoffset() is not None and execution_completed.utcoffset() is not None
        assert execution_started<=execution_completed
        wall_role_values={}
        wall_role_occurrences={role:0 for role in wall_roles.values()}
        def mapped(kind,raw):
            rows=mappings[kind]
            if raw not in rows:rows[raw]=f"<{kind}:{len(rows)}>"
            return rows[raw]
        for event in value["events"]:
            mapped("event_hash",event["event_hash"])
            mapped("semantic_hash",event["semantic_hash"])
            mapped("idempotency_key",event["idempotency_key"])
        def wall_role(path):
            roles=[role for suffix,role in wall_roles.items() if path.endswith(suffix)]
            assert len(roles)==1
            return roles[0]
        def visit(row,path=""):
            if isinstance(row,dict):
                out={}
                for key,item in row.items():
                    child=path+"/"+key
                    if child in expected:
                        kind=expected[child]
                        assert isinstance(item,str) and item
                        if kind=="event_hash" and item not in mappings["event_hash"]:
                            raise AssertionError("unbound_event_hash_reference:"+child)
                        if kind=="order_intent":assert item.startswith("oint_")
                        if kind=="order":assert item.startswith("btc_order_")
                        if kind=="risk_check":assert item.startswith("risk_")
                        if kind=="wall_time":
                            parsed=datetime.fromisoformat(item.replace("Z","+00:00"))
                            assert parsed.utcoffset() is not None and execution_started<=parsed<=execution_completed
                            role=wall_role(child)
                            if role in wall_role_values:assert wall_role_values[role]==item
                            else:wall_role_values[role]=item
                            wall_role_occurrences[role]+=1
                            out[key]=f"<wall_time:{role}>"
                        else:
                            out[key]=mapped(kind,item)
                    else:
                        out[key]=visit(item,child)
                return out
            if isinstance(row,list):return [visit(item,path+f"/{index}") for index,item in enumerate(row)]
            return row
        normalized=visit(value)
        for prefix in prefixes:
            audit=projected(value,prefix)
            ordered=[datetime.fromisoformat(audit["risk_decision"]["checked_at"].replace("Z","+00:00"))]
            ordered.extend(datetime.fromisoformat(event["timestamp_utc"].replace("Z","+00:00"))
                for event in audit["oms"]["events"][1:7])
            assert len(ordered)==7 and all(item.utcoffset() is not None for item in ordered)
            assert all(execution_started<=item<=execution_completed for item in ordered)
            assert all(left<=right for left,right in zip(ordered,ordered[1:]))
        assert set(wall_role_values)==set(wall_roles.values())
        assert set(wall_role_occurrences.values())=={len(prefixes)}
        return normalized,{key:len(rows) for key,rows in mappings.items()},{
            "role_count":len(wall_role_values),"raw_distinct_count":len(set(wall_role_values.values()))}

    assert legacy["first"]==legacy["duplicate"]
    assert cached["first"]==cached["duplicate"]
    assert cached["venue"]==legacy["venue"]
    assert cached["ledger"]==legacy["ledger"]
    assert len(cached["events"])>=290 and len(legacy["events"])>=290
    assert cached["events"][:286]==legacy["events"][:286]
    raw_differences=differences(cached,legacy)
    assert {path for path,_left,_right in raw_differences}==set(expected)
    assert_preimages_and_chain(legacy)
    assert_preimages_and_chain(cached)
    normalized_cached,cached_cardinality,cached_wall=normalize(cached,execution_windows["cached"])
    normalized_legacy,legacy_cardinality,legacy_wall=normalize(legacy,execution_windows["legacy"])
    assert cached_cardinality==legacy_cardinality
    assert {key:cached_cardinality[key] for key in ("order_intent","order","risk_check")}=={
        "order_intent":1,"order":1,"risk_check":1}
    assert {key:cached_cardinality[key] for key in (
        "intent_digest","execution_intent_digest","oms_bundle_digest","proof_identity_digest")}=={
        "intent_digest":1,"execution_intent_digest":1,"oms_bundle_digest":1,"proof_identity_digest":1}
    actual_differences=differences(normalized_cached,normalized_legacy)
    assert not actual_differences,"\n".join(
        f"{path}|{type(left).__name__}:{left!r}|{type(right).__name__}:{right!r}"
        for path,left,right in actual_differences[:100])
    return {"schema_version":"registered_offline_cache_closed_verification_v1",
        "status":"verified_equivalent","allowed_dynamic_path_count":len(expected),
        "legacy_wall_time":legacy_wall,"cached_wall_time":cached_wall,
        "identity_cardinality":cached_cardinality}


def test_registered_v2_advance_preserves_exact_current_settlement_market_and_rejects_missing_fact():
    from datetime import datetime,timezone
    from decimal import Decimal
    from types import SimpleNamespace
    from quant_crypto.application.qlib_offline_replay import QlibFixtureOfflineReplay,QlibOfflineReplayError
    at=datetime(2026,6,16,8,tzinfo=timezone.utc)
    fact=FundingSettlementFact(event_id="funding-08",event_time_utc=at,rate=.0001,
        source_record_id="okx-08",source_dataset="okx-public-funding",source_version="bound-v1",
        source_sha256="a"*64)
    later=at+timedelta(hours=1)
    observation=SimpleNamespace(maintenance_facts=(
        OfflineMaintenanceFact(observed_at_utc=at,mark_price=200.,index_price=201.),
        OfflineMaintenanceFact(observed_at_utc=later,mark_price=210.,index_price=211.),
    ))
    runtime=object.__new__(QlibFixtureOfflineReplay)
    runtime.registered_inputs=SimpleNamespace(manifest={"schema_version":"registered_offline_market_v2"})
    runtime._registered_funding_schedule=lambda:(fact,)
    runtime.venue=SimpleNamespace(now=at,market_price=Decimal("200"),index_price=Decimal("201"))
    # The old decision mark (100), exact 08Z mark/index (200/201), and delayed
    # trade open (300) are deliberately distinct.  Only 200/201 may remain the
    # execution-time market; 300 is exclusively the later fill price.
    mark,index=runtime._market_after_registered_advance(at=at,observation=observation,
        fallback_mark=100.,fallback_index=101.,require_current_fact=True)
    assert (mark,index)==(Decimal("200"),Decimal("201"))
    execution_mark,execution_index=runtime._market_after_registered_advance(
        at=at,observation=observation,fallback_mark=300.,fallback_index=101.,
        require_current_fact=True)
    assert (execution_mark,execution_index)==(Decimal("200"),Decimal("201"))
    nonfunding_mark,nonfunding_index=runtime._market_after_registered_advance(
        at=later,observation=observation,fallback_mark=310.,fallback_index=111.,
        require_current_fact=True)
    assert (nonfunding_mark,nonfunding_index)==(Decimal("210"),Decimal("211"))
    with pytest.raises(QlibOfflineReplayError,match="missing_or_ambiguous"):
        runtime._market_after_registered_advance(at=at+timedelta(minutes=1),observation=observation,
            fallback_mark=300.,fallback_index=101.,require_current_fact=True)
    duplicate=SimpleNamespace(maintenance_facts=(observation.maintenance_facts[0],
        observation.maintenance_facts[0]))
    with pytest.raises(QlibOfflineReplayError,match="missing_or_ambiguous"):
        runtime._market_after_registered_advance(at=at,observation=duplicate,
            fallback_mark=300.,fallback_index=101.,require_current_fact=True)
    runtime._registered_funding_schedule=lambda:(fact,fact)
    with pytest.raises(QlibOfflineReplayError,match="missing_or_ambiguous"):
        runtime._market_after_registered_advance(at=at,observation=observation,
            fallback_mark=300.,fallback_index=101.,require_current_fact=True)
    runtime.registered_inputs.manifest["schema_version"]="registered_offline_market_v1"
    v1_mark,v1_index=runtime._market_after_registered_advance(at=later,observation=observation,
        fallback_mark=310.,fallback_index=111.,require_current_fact=True)
    assert (v1_mark,v1_index)==(Decimal("310"),Decimal("111"))


def test_registered_v2_bound_policy_resume_is_hash_bound_and_never_uses_pending_intent():
    from datetime import datetime,timezone
    from types import SimpleNamespace
    from quant_crypto.trading_contracts import TargetPosition
    from quant_crypto.application.qlib_offline_replay import (
        QlibFixtureOfflineReplay, btc_quantity_to_okx_contracts, _canonical_digest, _canonical_sha256)
    target=TargetPosition(timestamp_utc=datetime(2026,6,16,7,tzinfo=timezone.utc),
        strategy_id="fixture",symbol="BTC-USDT-SWAP",target_weight=0.,target_quantity=0.,
        signal_id="signal-1",metadata={"source_forecast_id":"forecast-1"},target_position_id="target-1")
    conversion=btc_quantity_to_okx_contracts(btc_quantity=0.,contract_value_btc="0.01",
        lot_size_contracts="0.01",min_size_contracts="0.01",max_abs_contracts="0.01")
    core={"schema_version":"qlib_policy_resume_v1","target":QlibFixtureOfflineReplay._object_payload(target),
        "approved":True,"policy_reasons":[],"exit_reasons":["end_of_research_window"],
        "exit_state":{"quantity":.0001,"average_price":100.,"favorable_price":101.,"holding_bars":2},
        "conversion":conversion.__dict__,"execution_blockers":[],"position_contracts":"0.01"}
    input_binding={"identity_digest":"a"*64,"forecast_id":"forecast-1"}
    binding={**input_binding,"event_id":"decision-1","candidate_target_position_id":target.target_position_id,
        "candidate_target_sha256":_canonical_sha256(QlibFixtureOfflineReplay._object_payload(target)),
        "resume_policy":{**core,"sha256":_canonical_digest(core)}}
    event={"event_type":"qlib_policy_step_bound","payload":binding}
    class Store:
        def recover(self):return SimpleNamespace(events=[event])
    runtime=object.__new__(QlibFixtureOfflineReplay)
    runtime.registered_inputs=SimpleNamespace(manifest={"schema_version":"registered_offline_market_v2"})
    runtime.controller=SimpleNamespace(_runtime_store=Store(),_state={"risk_control":{"pending_order_intents":{
        "prior-terminal":{"status":"terminal","client_order_id":"prior-terminal"}}}})
    runtime.venue=SimpleNamespace(state={"position":"0.01"})
    runtime._registered_venue_contract=lambda:{"contract_value_btc":"0.01","lot_size_contracts":"0.01",
        "minimum_size_contracts":"0.01","maximum_absolute_contracts":"0.01"}
    recovered=runtime._recover_bound_policy(event_id="decision-1",input_binding=input_binding)
    assert recovered[0].target==target and recovered[0].approved is True
    assert recovered[1]==conversion and recovered[2]==() and recovered[3]==binding
    for unresolved in ({"status":"unknown"},{"status":"accepted"},{"status":"mystery"},None):
        runtime.controller._state["risk_control"]["pending_order_intents"]={"intent":unresolved}
        with pytest.raises(RuntimeError,match="pending_intent_recovery_blocked"):
            runtime._recover_bound_policy(event_id="decision-1",input_binding=input_binding)
    runtime.controller._state["risk_control"]["pending_order_intents"]={}
    binding["resume_policy"]["sha256"]="0"*64
    with pytest.raises(RuntimeError,match="resume_hash_mismatch"):
        runtime._recover_bound_policy(event_id="decision-1",input_binding=input_binding)
    binding.pop("resume_policy")
    with pytest.raises(RuntimeError,match="policy_resume_missing"):
        runtime._recover_bound_policy(event_id="decision-1",input_binding=input_binding)


def test_registered_offline_verified_history_cache_matches_legacy_economics(tmp_path,cases,monkeypatch):
    import quant_crypto.application.qlib_offline_replay as replay_module
    from quant_crypto.application.btc_demo_production_composition import BtcDemoProductionComposition
    from quant_crypto.application.donchian_offline_history_cache import OfflineLedgerHistoryCache
    from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeController
    from quant_crypto.oms.runtime_store import BTCRuntimeStore
    from quant_crypto.oms.shared_platform_v3 import order_intent_execution_digest
    cached_controller = replay_module._QlibOfflineRuntimeController
    original_recover = BTCRuntimeStore.recover
    original_legacy_replay = OkxDemoPaperRuntimeController._replay_reconciled_ledger
    original_cached_replay = OfflineLedgerHistoryCache.replay
    original_maintenance = replay_module.QlibFixtureOfflineReplay._renew_verified_offline_liveness
    original_bundle_provider = BtcDemoProductionComposition.build_order_submission_bundle

    root=tmp_path/"same-identity";root.mkdir()
    service,row,kwargs,_=prepared(root,cases[0])
    state_dir=kwargs["state_dir"]

    def measured(controller):
        metrics={"recover_calls":0,"recover_seconds":0.,"ledger_calls":0,"ledger_seconds":0.,
            "maintenance_calls":0,"maintenance_seconds":0.}
        captures=[]
        def recover(self,*args,**kwargs):
            started=time.perf_counter()
            try:return original_recover(self,*args,**kwargs)
            finally:
                metrics["recover_calls"]+=1;metrics["recover_seconds"]+=time.perf_counter()-started
        def legacy_replay(self,*args,**kwargs):
            started=time.perf_counter()
            try:return original_legacy_replay(self,*args,**kwargs)
            finally:
                metrics["ledger_calls"]+=1;metrics["ledger_seconds"]+=time.perf_counter()-started
        def cached_replay(self,*args,**kwargs):
            started=time.perf_counter()
            try:return original_cached_replay(self,*args,**kwargs)
            finally:
                metrics["ledger_calls"]+=1;metrics["ledger_seconds"]+=time.perf_counter()-started
        def maintenance(self,*args,**kwargs):
            started=time.perf_counter()
            try:return original_maintenance(self,*args,**kwargs)
            finally:
                metrics["maintenance_calls"]+=1;metrics["maintenance_seconds"]+=time.perf_counter()-started
        def capture_bundle(self,**options):
            bundle=original_bundle_provider(self,**options)
            intent=options["intent"]
            intent_payload=replay_module.QlibFixtureOfflineReplay._object_payload(intent)
            captures.append({"intent":json.loads(json.dumps(intent_payload,default=str)),
                "intent_binding_digest":replay_module._canonical_sha256(intent_payload),
                "intent_execution_digest":order_intent_execution_digest(intent),
                "bundle":bundle.to_dict(include_digest=False),"bundle_digest":bundle.digest,
                "proof_identity":bundle.proof_identity.to_dict(),
                "proof_identity_digest":bundle.proof_identity.digest})
            return bundle
        with monkeypatch.context() as patch:
            patch.setattr(replay_module,"_QlibOfflineRuntimeController",controller)
            patch.setattr(BtcDemoProductionComposition,"build_order_submission_bundle",capture_bundle)
            patch.setattr(BTCRuntimeStore,"recover",recover)
            patch.setattr(OkxDemoPaperRuntimeController,"_replay_reconciled_ledger",legacy_replay)
            patch.setattr(OfflineLedgerHistoryCache,"replay",cached_replay)
            patch.setattr(replay_module.QlibFixtureOfflineReplay,"_renew_verified_offline_liveness",maintenance)
            started=time.perf_counter()
            with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
                metrics["cold_open_seconds"]=time.perf_counter()-started
                store=runtime.controller._runtime_store
                metrics["execution_started_at_utc"]=datetime.now(timezone.utc).isoformat()
                decision_started=time.perf_counter()
                first=runtime.execute_registered(0)
                metrics["first_decision_seconds"]=time.perf_counter()-decision_started
                metrics["execution_completed_at_utc"]=datetime.now(timezone.utc).isoformat()
                duplicate_started=time.perf_counter()
                duplicate=runtime.execute_registered(0)
                metrics["duplicate_seconds"]=time.perf_counter()-duplicate_started
                state=deepcopy(runtime.venue.state)
                ledger=deepcopy(runtime.controller._state["ledger_reconciliation"]["account_ledger_replay"])
            metrics["elapsed_seconds"]=time.perf_counter()-started
            events_path=kwargs["state_dir"]/"runtime"/"events.jsonl"
            metrics["event_bytes"]=events_path.stat().st_size
            metrics["event_count"]=sum(1 for _line in events_path.open("rb"))
            events_bytes=events_path.read_bytes()
            assert store._journal_closed is True
        assert len(captures)==1
        return {"first":first,"duplicate":duplicate,"venue":state,"ledger":ledger,"capture":captures[0],
            "events":[json.loads(line) for line in events_bytes.splitlines()]},metrics

    legacy,legacy_metrics=measured(OkxDemoPaperRuntimeController)
    legacy_state=tmp_path/"legacy-state"
    shutil.move(state_dir,legacy_state)
    cached,cached_metrics=measured(cached_controller)
    comparison_evidence=tmp_path/"legacy-cache-comparison.json"
    comparison_evidence.write_text(json.dumps({
        "schema_version":"registered_offline_cache_comparison_v1",
        "legacy":{"first":legacy["first"],"duplicate":legacy["duplicate"],
            "capture":legacy["capture"],
            "execution_started_at_utc":legacy_metrics["execution_started_at_utc"],
            "execution_completed_at_utc":legacy_metrics["execution_completed_at_utc"]},
        "cached":{"first":cached["first"],"duplicate":cached["duplicate"],
            "capture":cached["capture"],
            "execution_started_at_utc":cached_metrics["execution_started_at_utc"],
            "execution_completed_at_utc":cached_metrics["execution_completed_at_utc"]},
    },ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("OFFLINE_HISTORY_EVIDENCE="+str(comparison_evidence))
    legacy_recovery=BTCRuntimeStore(legacy_state/"runtime").recover()
    cached_recovery=BTCRuntimeStore(state_dir/"runtime").recover()
    assert not legacy_recovery.blockers and not cached_recovery.blockers
    assert not legacy_recovery.truncated_tail and not cached_recovery.truncated_tail
    assert (legacy_recovery.last_sequence,legacy_recovery.last_event_hash)==(
        len(legacy["events"]),legacy["events"][-1]["event_hash"])
    assert (cached_recovery.last_sequence,cached_recovery.last_event_hash)==(
        len(cached["events"]),cached["events"][-1]["event_hash"])
    assert cached["venue"]==legacy["venue"]
    assert cached["ledger"]==legacy["ledger"]
    assert cached["events"][:286]==legacy["events"][:286]

    verify_registered_offline_cache_equivalence(legacy=legacy,cached=cached,execution_windows={
        "legacy":{"execution_started_at_utc":legacy_metrics["execution_started_at_utc"],
            "execution_completed_at_utc":legacy_metrics["execution_completed_at_utc"]},
        "cached":{"execution_started_at_utc":cached_metrics["execution_started_at_utc"],
            "execution_completed_at_utc":cached_metrics["execution_completed_at_utc"]},
    })
    assert cached_metrics["maintenance_calls"]==legacy_metrics["maintenance_calls"]
    assert cached_metrics["recover_calls"]==legacy_metrics["recover_calls"]
    assert cached_metrics["ledger_calls"]==legacy_metrics["ledger_calls"]
    assert cached_metrics["event_count"]==legacy_metrics["event_count"]
    assert cached_metrics["event_bytes"]==legacy_metrics["event_bytes"]
    print("OFFLINE_HISTORY_PROFILE="+json.dumps({"legacy":legacy_metrics,"cached":cached_metrics},sort_keys=True))


def test_registered_offline_cache_preserves_injected_risk_proof_error_propagation_step(
    tmp_path,cases,monkeypatch,
):
    import quant_crypto.application.qlib_offline_replay as replay_module
    from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeController
    from quant_crypto.runtime.control_plane import BTCDemoExecutionDispatcher
    cached_controller=replay_module._QlibOfflineRuntimeController
    root=tmp_path/"same-risk-identity";root.mkdir()
    service,row,kwargs,_=prepared(root,cases[0])
    state_dir=kwargs["state_dir"]

    def run(controller):
        with monkeypatch.context() as patch:
            patch.setattr(replay_module,"_QlibOfflineRuntimeController",controller)
            patch.setattr(BTCDemoExecutionDispatcher,"dispatch",
                lambda *_args,**_kwargs: (_ for _ in ()).throw(RuntimeError("risk_evidence_proof_invalid")))
            with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
                before=deepcopy(runtime.venue.state)
                with pytest.raises(Exception) as caught:
                    runtime.execute_registered(0)
                chain=[];error=caught.value
                while error is not None:
                    chain.append(type(error).__name__+":"+str(error));error=error.__cause__
                after=deepcopy(runtime.venue.state)
                logical_time=runtime._now.isoformat()
            events=[json.loads(line) for line in (state_dir/"runtime"/"events.jsonl").read_bytes().splitlines()]
        assert chain[0]=="QlibOfflineReplayError:qlib_offline_maintenance_ack_failed"
        assert any("risk_evidence_proof_invalid" in item for item in chain[1:])
        assert after["submit_count"]==before["submit_count"]==0
        assert after["fills"]==before["fills"]==[]
        assert after["bills"]==before["bills"]==[]
        assert after["position"]==before["position"]=="0"
        return {"error_chain":chain,"logical_time":logical_time,"venue":after,"events":events}

    legacy=run(OkxDemoPaperRuntimeController)
    legacy_risk_state=tmp_path/"legacy-risk-state"
    shutil.move(state_dir,legacy_risk_state)
    cached=run(cached_controller)
    assert cached==legacy


def test_registered_offline_cache_excludes_concurrent_writer_and_releases_on_failure(tmp_path,cases,monkeypatch):
    import quant_crypto.application.qlib_offline_replay as replay_module
    from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeController
    from quant_crypto.oms.runtime_store import BTCRuntimeStore
    class FailedStore:
        closed=False
        def close(self):
            self.closed=True
            raise RuntimeError("injected_store_close_failure")
    failed_store=FailedStore()
    def fail_controller_init(self,**_options):
        self._runtime_store=failed_store
        raise RuntimeError("injected_controller_initialization_failure")
    with monkeypatch.context() as patch:
        patch.setattr(OkxDemoPaperRuntimeController,"__init__",fail_controller_init)
        with pytest.raises(RuntimeError,match="injected_controller_initialization_failure"):
            replay_module._QlibOfflineRuntimeController()
    assert failed_store.closed is True

    service,row,kwargs,_=prepared(tmp_path,cases[0])
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        store=runtime.controller._runtime_store
        assert store._offline_session_enabled is True
        assert runtime.controller._offline_ledger_history.__class__.__name__=="OfflineLedgerHistoryCache"
        competing=BTCRuntimeStore(kwargs["state_dir"]/"runtime",offline_journal_session=True)
        blocked=competing.recover()
        assert blocked.blockers and "btc_offline_journal_session_invalid" in blocked.blockers[0]
        competing.close()
    assert store._journal_closed is True
    successor=BTCRuntimeStore(kwargs["state_dir"]/"runtime",offline_journal_session=True)
    assert not successor.recover().blockers
    successor.close()

    created=[]
    original_init=replay_module._QlibOfflineRuntimeController.__init__
    def capture(self,**options):
        original_init(self,**options);created.append(self)
    with monkeypatch.context() as patch:
        patch.setattr(replay_module._QlibOfflineRuntimeController,"__init__",capture)
        patch.setattr(replay_module.QlibFixtureOfflineReplay,"_has_exact_clean_stop",
            lambda *_args,**_kwargs: (_ for _ in ()).throw(RuntimeError("injected_after_controller_construction")))
        with pytest.raises(RuntimeError,match="injected_after_controller_construction"):
            open_btc_registered_candidate_offline(service,row["id"],**kwargs)
    assert created and created[-1]._runtime_store._journal_closed is True

    with monkeypatch.context() as patch:
        with pytest.raises(RuntimeError,match="injected_abnormal_context"):
            with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
                abnormal_store=runtime.controller._runtime_store
                original_close=abnormal_store.close
                def close_failure():
                    original_close()
                    raise RuntimeError("injected_abnormal_store_close_failure")
                patch.setattr(abnormal_store,"close",close_failure)
                raise RuntimeError("injected_abnormal_context")
    assert abnormal_store._journal_closed is True
    recovered=BTCRuntimeStore(kwargs["state_dir"]/"runtime").recover()
    assert not recovered.blockers
    assert not any(event["event_type"]=="qlib_offline_clean_stopped"
        and event["sequence"]>store._sequence for event in recovered.events)

    events_path=kwargs["state_dir"]/"runtime"/"events.jsonl"
    checkpoint_path=kwargs["state_dir"]/"runtime"/"state.json"
    venue_path=kwargs["state_dir"]/"offline_venue.json"
    original_events=events_path.read_bytes()
    original_checkpoint=checkpoint_path.read_bytes()
    original_venue=venue_path.read_bytes()
    lines=original_events.splitlines()
    damaged=json.loads(lines[0]);damaged["event_hash"]="0"*64
    lines[0]=json.dumps(damaged,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    damaged_events=b"\n".join(lines)+b"\n"
    events_path.write_bytes(damaged_events)
    with pytest.raises(Exception,match=
        "qlib_offline_runtime_recovery_blocked:btc_offline_journal_session_invalid:BTCRuntimeStoreError"):
        open_btc_registered_candidate_offline(service,row["id"],**kwargs)
    assert venue_path.read_bytes()==original_venue
    assert events_path.read_bytes()==damaged_events
    assert checkpoint_path.read_bytes()==original_checkpoint
    session_probe=BTCRuntimeStore(kwargs["state_dir"]/"runtime",offline_journal_session=True)
    assert session_probe.recover().blockers==(
        "btc_runtime_event_chain_invalid","btc_runtime_checkpoint_ahead_of_event_log")
    session_probe.close()
    ordinary_probe=BTCRuntimeStore(kwargs["state_dir"]/"runtime")
    assert "btc_runtime_event_chain_invalid" in ordinary_probe.recover().blockers
    ordinary_probe.close()
    assert events_path.read_bytes()==damaged_events
    assert checkpoint_path.read_bytes()==original_checkpoint
    events_path.write_bytes(original_events)
    checkpoint_path.write_bytes(original_checkpoint)
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as restored:
        assert restored.venue.state["submit_count"]==json.loads(original_venue)["submit_count"]
        assert restored.venue.state["fills"]==json.loads(original_venue)["fills"]


def test_evaluate_frozen_candidate_aborts_owned_runtime_without_masking_error(monkeypatch,tmp_path):
    import quant_crypto.application.qlib_offline_replay as replay_module
    class Owned:
        aborted=False
        def abort(self):self.aborted=True
    owned=Owned()
    def fail(_contract,**options):
        options["owned"].append(owned)
        raise RuntimeError("injected_evaluate_failure")
    monkeypatch.setattr(replay_module,"_evaluate_frozen_candidate_impl",fail)
    with pytest.raises(RuntimeError,match="injected_evaluate_failure"):
        replay_module.evaluate_frozen_candidate({},repo_root=ROOT,state_dir=tmp_path)
    assert owned.aborted is True


@pytest.mark.parametrize("position,expected", [("2","-1.2"),("-2","1.2"),("0","0")])
def test_verified_funding_event_long_short_zero_and_duplicate_are_idempotent(tmp_path,position,expected):
    from datetime import datetime,timezone
    venue=_QlibOfflineVenue(tmp_path/("venue-"+position.replace("-","n")+".json"),
        now=datetime(2026,6,16,8,tzinfo=timezone.utc),initial_equity_usdt=5000)
    venue.state["position"]=position
    fact=FundingSettlementFact(event_id="funding-20260616T08Z",event_time_utc=datetime(2026,6,16,8,tzinfo=timezone.utc),
        rate=.001,source_record_id="okx-row-1",source_dataset="okx-public-funding",
        source_version="fixture-v1",source_sha256="a"*64)
    first=venue.apply_verified_funding_event(fact=fact,mark_price=60000,contract_value_btc="0.01")
    second=venue.apply_verified_funding_event(fact=fact,mark_price=99999,contract_value_btc="0.01")
    assert first==second and first["calculated_cashflow_usdt"]==expected
    assert len(venue.state["funding_settlements"])==1
    assert len(venue.state["bills"])==(0 if position=="0" else 1)
    if position=="0":assert first["cash_ledger_effect"]=="none_zero_position"


def test_registered_v2_funding_precedes_overlapping_fill_and_recovers_venue_before_ledger(tmp_path,cases,monkeypatch):
    from datetime import datetime,timezone
    service,row,kwargs,_=prepared(tmp_path,cases[0],funding_v2=True)
    settlement_time=datetime(2026,6,16,8,tzinfo=timezone.utc)
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        for index in range(6):
            opened=runtime.execute_registered(index)
        old_position=runtime.venue.state["position"]
        assert float(old_position)!=0 and opened["fill_count"]>=1
        original_commit=runtime.controller._commit_ledger_reconciliation
        crashed={"value":False}
        def crash_after_venue_funding(*,snapshot,trigger):
            if trigger=="qlib_offline_verified_funding_event" and not crashed["value"]:
                crashed["value"]=True
                raise RuntimeError("fixture_after_venue_funding_before_ledger")
            return original_commit(snapshot=snapshot,trigger=trigger)
        with monkeypatch.context() as patch:
            patch.setattr(runtime.controller,"_commit_ledger_reconciliation",crash_after_venue_funding)
            with pytest.raises(RuntimeError,match="after_venue_funding_before_ledger"):
                runtime.execute_registered(6)
        event=[value for value in runtime.venue.state["funding_settlements"]
            if value["event_time_utc"]==settlement_time.isoformat()]
        assert len(event)==1 and event[0]["position_contracts"]==old_position
        bound=[event for event in runtime.controller._runtime_store.recover().events
            if event.get("event_type")=="qlib_policy_step_bound"][-1]
        bound_hash=bound["event_hash"]
        bound_payload=deepcopy(bound["payload"])
        fault_observation=runtime.registered_inputs.observations[6]
        exact_fact=next(fact for fact in fault_observation.maintenance_facts
            if fact.observed_at_utc==settlement_time)
        assert float(event[0]["valuation_mark_price"])==exact_fact.mark_price
        assert exact_fact.mark_price not in {
            fault_observation.mark_price,fault_observation.delayed_open_price}
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        original_guard=runtime._registered_protection_guard
        observed=[]
        def funding_first(now,*args,**named):
            if now==settlement_time:
                observed.append(any(value["event_time_utc"]==settlement_time.isoformat()
                    for value in runtime.venue.state["funding_settlements"]))
            return original_guard(now,*args,**named)
        monkeypatch.setattr(runtime,"_registered_protection_guard",funding_first)
        import quant_crypto.application.qlib_offline_replay as replay_module
        with monkeypatch.context() as patch:
            patch.setattr(replay_module,"evaluate_candidate_step",
                lambda *args,**named: (_ for _ in ()).throw(AssertionError("policy_must_not_recompute")))
            recovered=runtime.execute_registered(6)
        rebound=[event for event in runtime.controller._runtime_store.recover().events
            if event.get("event_type")=="qlib_policy_step_bound"
            and event.get("payload",{}).get("event_id")==bound_payload["event_id"]]
        assert len(rebound)==1 and rebound[0]["event_hash"]==bound_hash
        assert rebound[0]["payload"]==bound_payload
        assert recovered["candidate_target_position_id"]==bound_payload["candidate_target_position_id"]
        assert float(runtime.venue.market_price)==exact_fact.mark_price
        assert float(runtime.venue.index_price)==exact_fact.index_price
        assert runtime.controller._state["ledger_reconciliation"]["status"]=="reconciled"
        for index in range(7,48):runtime.execute_registered(index)
        events=runtime.venue.state["funding_settlements"]
        assert observed and all(observed)
        assert len(events)==6 and len({value["event_id"] for value in events})==6
        assert events[-1]["event_time_utc"]=="2026-06-18T00:00:00+00:00"
        bills_before=len(runtime.venue.state["bills"])
        final=runtime.execute_registered(47)
        assert final==runtime.execute_registered(47)
        assert len(runtime.venue.state["funding_settlements"])==6
        assert len(runtime.venue.state["bills"])==bills_before


def prepared(tmp_path, case, *, protection=True, funding_v2=False):
    original,bars,_,_ = case
    p=deepcopy(original)
    if protection:
        # NEW synthetic source, explicitly frozen before its FIRST seal. This
        # is not a migration or rewrite of the preceding ticket's old package.
        p["contracts"]["exit"].update(take_profit_fraction=.08,protection={
            "version":"registered_offline_oco_v1","trigger":"mark",
            "reference_price":"aggressive_limit_at_order_construction","effective":"attached_after_fill"})
        p["evidence_receipt"]["frozen_policy"]["policies"]["exit"]=deepcopy(p["contracts"]["exit"])
    root,envelope = sealed_factory(tmp_path,p)
    p = compile_factory_package(p["source"],envelope,root)
    predictions = infer_package(p,bars,data_version=p["data_version"],visible_through=bars.decision_time.iloc[-1])["rows"]
    # Pick an explicit synthetic funded baseline yielding exactly one lot under
    # the existing float policy. Do not round/loosen the production conversion.
    for start_index in range(30):
        first=predictions.iloc[start_index+(5 if funding_v2 else 0)]
        weight=abs(float(first.prediction))*p["contracts"]["position"]["risk_budget_fraction"]
        mark=float(bars.loc[bars.event_time==first.event_time].close.iloc[0])
        initial_equity=mark*.0001/weight
        for _ in range(4):
            quantity=initial_equity*weight/mark
            if quantity==.0001: break
            initial_equity=math.nextafter(initial_equity,math.inf if quantity<.0001 else -math.inf)
        if initial_equity*weight/mark==.0001: break
    assert initial_equity*weight/mark==.0001
    if funding_v2:
        import pandas as pd
        delta=pd.Timestamp("2026-06-16T00:00:00Z")-pd.Timestamp(predictions.iloc[start_index].event_time)
        bars=bars.copy()
        for field in ("event_time","available_time","decision_time"):bars[field]=pd.to_datetime(bars[field],utc=True)+delta
        predictions=infer_package(p,bars,data_version=p["data_version"],visible_through=bars.decision_time.iloc[-1])["rows"]
    observations=[]
    funding_times=["2026-06-16T08:00:00Z","2026-06-16T16:00:00Z","2026-06-17T00:00:00Z",
        "2026-06-17T08:00:00Z","2026-06-17T16:00:00Z","2026-06-18T00:00:00Z"]
    if funding_v2:
        import pandas as pd
        funding_events={pd.Timestamp(value).to_pydatetime():FundingSettlementFact(event_id="funding-"+value,
            event_time_utc=pd.Timestamp(value).to_pydatetime(),rate=.0001,
            source_record_id="okx-"+value,source_dataset="okx-public-funding",source_version="bound-v1",
            source_sha256=(format(number,"064x"))) for number,value in enumerate(funding_times,1)}
        ordinals=range(48)
    else:
        funding_events={};ordinals=(0,2)
    for ordinal in ordinals:
        r=predictions.iloc[start_index+ordinal]
        bar=bars.loc[bars.event_time==r.event_time].iloc[0]
        delayed=bars.loc[bars.event_time==r.event_time+timedelta(hours=2)].iloc[0]
        decision=(r.event_time+timedelta(hours=1)).to_pydatetime()
        latest_rate=-0.0000130999107801
        for when,event in sorted(funding_events.items()):
            if when<=decision:latest_rate=event.rate
        maintenance=[]
        for seconds in range(90,7201,90):
            observed=(r.event_time+timedelta(seconds=seconds)).to_pydatetime()
            # Settlement-time mark/index are separate from both the old hourly
            # observation and the delayed trade open, so recovery cannot pass
            # by accidentally reusing equal synthetic prices.
            shift=(.123 if funding_v2 else 0.)+(.123 if observed in funding_events else 0.)
            maintenance.append(OfflineMaintenanceFact(observed_at_utc=observed,
                mark_price=float(bar.close)+shift,
                index_price=float(bar.close)+shift+(.111 if funding_v2 else 0.)))
        observations.append(CandidateMarketObservation(event_time_utc=r.event_time.to_pydatetime(),
            close_price=float(bar.close),mark_price=float(bar.close),index_price=float(bar.close),
            delayed_open_price=float(delayed.open),funding_rate=latest_rate,
            funding_cashflow_usdt=0. if funding_v2 or ordinal==0 else -.0001,
            # The synthetic ordinal-6 exit deterministically crosses the first
            # funding boundary with an already-open position. It exercises the
            # real exit policy; no venue position or conversion rule is forged.
            end_of_window=ordinal in ({6,47} if funding_v2 else {ordinals[-1]}),
            maintenance_facts=tuple(maintenance),
            funding_settlements=tuple([funding_events[decision]] if decision in funding_events else [])))
    state_dir=tmp_path/"economic-state"
    # Persist a synthetic factory run, then consume the real factory and archive
    # readers. No permissive source/account port substitutes in this E2E.
    import hashlib
    from backend.app.services.alpha_factory import AlphaFactoryService
    from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
    factory_root=tmp_path/"factory"/"factory-a";factory_root.mkdir(parents=True)
    contents={"state.json":{"run_id":"factory-a","status":"completed","source_head":envelope["source_head"],"event_count":0},
        "request.json":{},"profile.json":envelope["result"]["profile"],"result.json":envelope["result"]}
    for name,content in contents.items():(factory_root/name).write_text(json.dumps(content),encoding="utf-8")
    (factory_root/"events.jsonl").write_text("",encoding="utf-8")
    sealed_names=[*contents,"events.jsonl"]
    (factory_root/"seal.json").write_text(json.dumps({"schema_version":"alpha_factory_seal_v1","run_id":"factory-a",
        "files":{name:hashlib.sha256((factory_root/name).read_bytes()).hexdigest() for name in sealed_names}}),encoding="utf-8")
    archive=ResearchArchiveCatalog(repo_root=ROOT)
    factory=AlphaFactoryService(root=factory_root.parent,qlib_root=root.parent,queue=None,readonly_archive=archive)
    assert factory.get("factory-a")["integrity_status"]=="passed"
    artifact=json.loads((tmp_path/"delivery.json").read_text())
    sources=ResearchDeliverySources(ROOT,archive=archive,qlib_root=root.parent,factory_reader=factory,
        delivery_artifacts=[(tmp_path/"delivery.json",digest(artifact))])
    catalog=tmp_path/"catalog";catalog.mkdir()
    account={"account_ref":"fixture-account","environment":"offline","simulation_namespace":"registered-test",
        "revision":1,"market":"crypto","instruments":["BTC-USDT-SWAP"],"currency":"USDT","expires_at":"2027-01-01T00:00:00Z",
        "offline_runtime":{"schema_version":"delivery_offline_runtime_v1","state_directory":str(state_dir.resolve()),
            "initial_equity_usdt":initial_equity,"currency":"USDT","equity_unit":"USDT"}}
    (catalog/"accounts.json").write_text(json.dumps({"schema_version":"delivery_account_catalog_v1","accounts":[account]}),encoding="utf-8")
    accounts=DeliveryAccounts(catalog/"accounts.json",repo_root=ROOT)
    from datetime import datetime,timezone
    now=[datetime(2026,9,25,tzinfo=timezone.utc)]
    service=DeliveryService(DeliveryStore(tmp_path/"catalog","fixture-owner"),sources,accounts,
        head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),clock=lambda:now[0])
    row=service.create(p["source"],"offline",key="test-create",actor="operator")
    row=command(service,row,"bind",account_ref="fixture-account")
    row=command(service,row,"review",decision="approve",reason="synthetic offline acceptance only")
    row=command(service,row,"register")
    manifest={"schema_version":"registered_offline_market_v1",**{k:p[k] for k in ("data_version","instrument","bar_size","settlement_currency")},
        "bars_sha256":market_frame_digest(bars),"observations_sha256":observation_digest(observations),"initial_equity_usdt":initial_equity}
    if funding_v2:
        manifest.update(schema_version="registered_offline_market_v2",
            dataset_contract_sha256="a"*64,funding_events_sha256="b"*64,funding_rate_history_sha256="c"*64,
            funding_event_count=6,valuation_policy="minute_close_sampled_valuation_not_exchange_actual_settlement",
            instrument_contract={"venue":"OKX","instrument_id":"BTC-USDT-SWAP","contract_value_btc":"0.01",
                "lot_size_contracts":"0.01","minimum_size_contracts":"0.01","maximum_market_size_contracts":"35000",
                "source_record_id":"BTC-USDT-SWAP","source_version":"bound-v1",
                "source_sha256":"1a3be93ab5be07d8d0625ff37c077a461cba075876e44e8517266c9a28e336e8",
                "observed_at":"2026-07-30T11:45:48Z","available_time":"2026-07-30T11:45:48Z",
                "historical_availability_assumption":"frozen_engineering_contract_assumption_not_june_pit_proof"})
    kwargs={"content_digest":row["content_digest"],"account_identity_hash":accounts.get("fixture-account")["identity_hash"],"adapter_id":p["adapter_id"],
        "bars":bars,"market_manifest":manifest,"market_manifest_digest":digest(manifest),"observations":observations,"state_dir":state_dir,"repo_root":ROOT}
    return service,row,kwargs,now


@pytest.mark.parametrize("case_index",[0,1])
def test_registered_real_inference_fok_fill_duplicate_restart_and_ledger(tmp_path,cases,monkeypatch,case_index):
    service,row,kwargs,_=prepared(tmp_path,cases[case_index])
    def denied(*a,**k): raise AssertionError("no network or model training in registered execution")
    monkeypatch.setattr(socket.socket,"connect",denied)
    import lightgbm as lgb
    monkeypatch.setattr(lgb,"train",denied)
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        first=runtime.execute_registered(0)
        assert first["fill_count"]==1,json.dumps(first,ensure_ascii=False)
        assert first==runtime.execute_registered(0)
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        assert first==runtime.execute_registered(0)
        closed=runtime.execute_registered(1)
        assert closed["fill_count"]==2,json.dumps(closed,ensure_ascii=False)
        assert float(closed["position_contracts"])==0
        ledger=runtime.controller._state["ledger_reconciliation"]["account_ledger_replay"]
        assert ledger["status"]=="reconciled" and ledger["reconciled"] is True
        assert float(ledger["fee_cashflow_usdt"])<0 and float(ledger["funding_cashflow_usdt"])<0
        assert not any(closed["permissions"].values())


@pytest.mark.parametrize("damage",["digest","account","manifest","expired","revoked"])
def test_bad_registration_has_no_economic_side_effects(tmp_path,cases,damage):
    service,row,kwargs,now=prepared(tmp_path,cases[0])
    if damage=="digest": kwargs["content_digest"]="0"*64
    if damage=="account": kwargs["account_identity_hash"]="0"*64
    if damage=="manifest": kwargs["market_manifest"]["bar_size"]="4h"
    if damage=="expired": now[0]+=timedelta(days=2)
    if damage=="revoked": command(service,row,"revoke",reason="test withdrawal of new-risk authority")
    with pytest.raises(DeliveryError): open_btc_registered_candidate_offline(service,row["id"],**kwargs)
    assert not kwargs["state_dir"].exists()


def test_registered_ledger_crash_recovery_then_revocation_preserves_open_position(tmp_path,cases,monkeypatch):
    service,row,kwargs,_=prepared(tmp_path,cases[0])
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        def interrupted(**kw): raise RuntimeError("after_ledger_before_evidence")
        monkeypatch.setattr(runtime,"_append_decision_evidence",interrupted)
        with pytest.raises(RuntimeError,match="after_ledger_before_evidence"): runtime.execute_registered(0)
        assert len(runtime.venue.state["fills"])==1
        original_order=runtime.venue.state["orders"][0]["clOrdId"]
        events=runtime.controller._runtime_store.recover().events
        hashes={e["event_hash"] for e in events if e["event_type"]=="ledger_uow_committed"}
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        recovered=runtime.execute_registered(0)
        assert recovered["recovered_without_resubmit"] is True
        assert recovered["fill_count"]==1 and recovered["client_order_id"]==original_order
        command(service,row,"revoke",reason="test preserve position and protection")
        with pytest.raises(DeliveryError,match="registration_inactive"):runtime.execute_registered(1)
        assert len(runtime.venue.state["fills"])==1
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs,recovery_only=True) as runtime:
        receipt=runtime.reconcile_registered()
        assert receipt["position_contracts"]=="0.01" and receipt["fill_count"]==1
        assert receipt["protection_count"]==1 and receipt["new_risk_allowed"] is False
        assert receipt["account_ledger_replay"]["status"]=="reconciled"
        assert hashes.issubset({e["event_hash"] for e in runtime.controller._runtime_store.recover().events})
        with pytest.raises(RuntimeError,match="recovery_forbids_new_decisions"):runtime.execute_registered(1)


def test_registered_crash_after_durable_intent_preserves_unknown_and_never_resubmits(tmp_path,cases,monkeypatch):
    service,row,kwargs,_=prepared(tmp_path,cases[0])
    class SimulatedProcessCrash(BaseException): pass
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        def interrupted(*a,**kw): raise SimulatedProcessCrash()
        monkeypatch.setattr(runtime.venue,"submit_order",interrupted)
        with pytest.raises(SimulatedProcessCrash):runtime.execute_registered(0)
        pending=deepcopy(runtime.controller._state["risk_control"]["pending_order_intents"])
        assert len(pending)==1 and next(iter(pending.values()))["persisted_before_post"] is True
        assert runtime.venue.state["submit_count"]==0
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as runtime:
        with pytest.raises(RuntimeError):runtime.execute_registered(0)
        assert runtime.venue.state["submit_count"]==0 and len(runtime.venue.state["fills"])==0
        assert set(pending).issubset(runtime.controller._state["risk_control"]["pending_order_intents"])


def test_registered_incomplete_or_future_maintenance_rejected_before_constructor(tmp_path,cases,monkeypatch):
    from dataclasses import replace
    from quant_crypto.application.qlib_offline_replay import QlibFixtureOfflineReplay
    service,row,kwargs,_=prepared(tmp_path,cases[0])
    def denied(*a,**kw): raise AssertionError("economic_constructor_reached")
    monkeypatch.setattr(QlibFixtureOfflineReplay,"__init__",denied)
    original=kwargs["observations"][0]
    for facts in ((), original.maintenance_facts[::3],
            original.maintenance_facts+(replace(original.maintenance_facts[-1],
                observed_at_utc=original.event_time_utc+timedelta(hours=3)),)):
        changed={**kwargs,"observations":[replace(original,maintenance_facts=facts),kwargs["observations"][1]]}
        changed["market_manifest"]={**kwargs["market_manifest"],"observations_sha256":observation_digest(changed["observations"])}
        changed["market_manifest_digest"]=digest(changed["market_manifest"])
        with pytest.raises(DeliveryError,match="registered_maintenance"):
            open_btc_registered_candidate_offline(service,row["id"],**changed)
        assert not kwargs["state_dir"].exists()


def test_runtime_account_changes_and_explicit_input_mismatches_precede_economic_writes(tmp_path,cases,monkeypatch):
    from quant_crypto.application.qlib_offline_replay import QlibFixtureOfflineReplay
    service,row,kwargs,_=prepared(tmp_path,cases[0])
    def denied(*a,**kw): raise AssertionError("economic_constructor_reached")
    monkeypatch.setattr(QlibFixtureOfflineReplay,"__init__",denied)
    for key,value in (("initial_equity_usdt",1.),("settlement_currency","USD"),("instrument","ETH-USDT-SWAP")):
        changed={**kwargs,"market_manifest":{**kwargs["market_manifest"],key:value}}
        changed["market_manifest_digest"]=digest(changed["market_manifest"])
        with pytest.raises(DeliveryError):open_btc_registered_candidate_offline(service,row["id"],**changed)
    with pytest.raises(DeliveryError):
        open_btc_registered_candidate_offline(service,row["id"],**{**kwargs,"state_dir":tmp_path/"unbound"})
    catalog=service.accounts.path
    original=json.loads(catalog.read_text(encoding="utf-8"))
    for field in ("initial_equity_usdt","state_directory","missing"):
        altered=deepcopy(original);account=altered["accounts"][0]
        if field=="missing":account.pop("offline_runtime")
        elif field=="state_directory":account["offline_runtime"][field]=str(tmp_path/"changed-state")
        else:account["offline_runtime"][field]+=1
        catalog.write_text(json.dumps(altered),encoding="utf-8")
        with pytest.raises(DeliveryError):open_btc_registered_candidate_offline(service,row["id"],**kwargs)
    assert not kwargs["state_dir"].exists() and not (tmp_path/"unbound").exists()


def test_registered_writer_lease_excludes_second_constructor(tmp_path,cases):
    from quant_crypto.application.runtime_risk_guardian import GuardianPersistenceError
    service,row,kwargs,_=prepared(tmp_path,cases[0])
    with open_btc_registered_candidate_offline(service,row["id"],**kwargs) as first:
        before=deepcopy(first.venue.state)
        with pytest.raises(GuardianPersistenceError):
            open_btc_registered_candidate_offline(service,row["id"],**kwargs)
        assert first.venue.state==before
        assert first.guardian_supervisor._lease.active


def test_constructed_verified_type_does_not_bypass_input_verifier(tmp_path,cases):
    from dataclasses import replace
    from quant_crypto.application.btc_registered_candidate import verify_registered_candidate_inputs
    service,row,kwargs,_=prepared(tmp_path,cases[0])
    inputs=verify_registered_candidate_inputs(service,row["id"],**{k:v for k,v in kwargs.items() if k!="repo_root"})
    with pytest.raises(AttributeError):inputs.observations=()
    inputs.manifest["observations_sha256"]="0"*64
    with pytest.raises(DeliveryError,match="registered_verified_inputs_changed"):inputs.check()
    assert not kwargs["state_dir"].exists()
