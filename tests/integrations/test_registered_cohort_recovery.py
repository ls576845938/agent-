"""Failure-first orchestration seams; not a real candidate or promotion test."""
from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from quant_shared.strategy_delivery.models import DeliveryError,digest
from quant_crypto.application.btc_registered_cohort import (
    COHORT_DECISION_SCHEMA,PreparedCohortDecision,RegisteredCohortReplay,cohort_data_version,
    validate_member_execution_policy)


def _runtime(*,events,position="2",algos=None,allocation=None):
    recovered=SimpleNamespace(events=events,blockers=(),truncated_tail=False)
    controller=SimpleNamespace(_runtime_store=SimpleNamespace(recover=lambda:recovered),
        _state={"strategy_allocations":allocation or {"member_list_sha256":"m"*64,
            "member_contracts":{"delivery_"+"1"*32:"1","delivery_"+"2"*32:"1"}}})
    venue=SimpleNamespace(state={"position":position,"orders":[{}],"fills":[{}],"algos":algos or []})
    return SimpleNamespace(controller=controller,venue=venue)


def _pending(client_id="cohort-order"):
    prepared={"schema_version":COHORT_DECISION_SCHEMA,"cursor":1,
        "event_time_utc":"2026-06-16T00:00:00+00:00","decision_time_utc":"2026-06-16T01:00:00+00:00",
        "allocation_plan":{"member_list_sha256":"m"*64,"allocation_plan_sha256":"p"*64,
            "desired_member_contracts":{"delivery_"+"1"*32:"1","delivery_"+"2"*32:"1"},
            "member_delta_contracts":{"delivery_"+"1"*32:"1","delivery_"+"2"*32:"1"}},"member_objects":{},
        "next_member_states":{"delivery_"+"1"*32:{"sha256":"a"*64},
            "delivery_"+"2"*32:{"sha256":"b"*64}},"common_market_facts":{"sha256":"c"*64},
        "order_plan":{"client_order_id":client_id},"execution_context_issued":True,"binding":{}}
    prepared["sha256"]=digest(prepared)
    return {"schema_version":"candidate_offline_cohort_pending_v1","job_id":"coff_"+"d"*32,
        "cursor":1,"status":"prepared","prepared":prepared}


def test_open_and_projection_recovery_share_adapter_keyed_data_version():
    assert cohort_data_version(
        donchian_input_digest="d"*64, qlib_input_digest="q"*64
    ) == digest({"donchian":"d"*64,"qlib":"q"*64})


def test_committed_ledger_repairs_projection_twice_without_new_order_or_fill():
    members={"delivery_"+"1"*32:{"signed_contracts":"1","fee":"-0.1"},
        "delivery_"+"2"*32:{"signed_contracts":"1","fee":"-0.1"}}
    allocation={"member_list_sha256":"m"*64,
        "member_contracts":{"delivery_"+"1"*32:"1","delivery_"+"2"*32:"1"},
        "fill_allocations":{"fill-1":{"allocation_plan_sha256":"p"*64,"order_id":"order-1","members":members}}}
    timestamp_ms=int(datetime(2026,6,16,1,tzinfo=timezone.utc).timestamp()*1000)+1
    event={"event_type":"ledger_uow_committed","event_hash":"e"*64,
        "payload":{"order_ledger":{"orders":[{"client_order_id":"cohort-order","order_id":"order-1"}]},
            "fill_ledger":[{"client_order_id":"cohort-order","order_id":"order-1","fill_id":"fill-1","timestamp_ms":timestamp_ms}],
            "strategy_allocation":allocation}}
    runtime=RegisteredCohortReplay.__new__(RegisteredCohortReplay);runtime.replay=_runtime(events=[event],allocation=allocation)
    before=dict(runtime.replay.venue.state)
    first=runtime.repair_committed(_pending());second=runtime.repair_committed(_pending())
    assert first==second and first["ledger_event_hash"]=="e"*64
    assert runtime.replay.venue.state==before


def test_unattributed_hosted_protection_touch_blocks_before_market_write():
    runtime=RegisteredCohortReplay.__new__(RegisteredCohortReplay)
    class Venue:
        state={"position":"1","orders":[],"fills":[],"algos":[{"state":"live","slTriggerPx":"90","tpTriggerPx":"110"}]}
        def set_market(self,**_): pytest.fail("market write must not occur")
    runtime.replay=SimpleNamespace(venue=Venue())
    now=datetime.now(timezone.utc)
    observation=SimpleNamespace(maintenance_facts=(SimpleNamespace(mark_price=89,index_price=89,observed_at_utc=now),),
        mark_price=100,index_price=100,close_price=100,funding_settlements=(),funding_cashflow_usdt=0)
    with pytest.raises(DeliveryError,match="cohort_unattributed_hosted_protection_fill"):
        runtime._apply_common_market(observation,SimpleNamespace(timestamp_utc=now))


def test_delta_zero_execute_only_projects_and_has_no_context():
    runtime=RegisteredCohortReplay.__new__(RegisteredCohortReplay)
    runtime.committed_projection=lambda prepared:{"cursor":prepared.cursor,"economic_action":"none_delta_zero"}
    prepared=PreparedCohortDecision(cursor=3,event_time_utc="event",decision_time_utc="decision",
        plan=SimpleNamespace(),member_objects={},next_member_states={},common_market_facts={},
        order_plan=None,context=None,binding={})
    assert runtime.execute(prepared)=={"cursor":3,"economic_action":"none_delta_zero"}


def test_incompatible_member_execution_policies_block_before_market_facts():
    with pytest.raises(DeliveryError,match="cohort_member_execution_policy_incompatible"):
        validate_member_execution_policy((
            {"package":{"adapter_id":"btc_donchian_history_offline_v1"}},
            {"package":{"adapter_id":"factory_lgbm_ast_v1"}},
        ))


def test_donchian_decision_only_view_uses_member_share_not_common_position():
    seen=[]
    class Cache:
        def __call__(self,frame):return frame,None
    class Controller:
        def _signal_decision(self,_identity,*,client):
            seen.append(client.state["position"])
            return {"direction":"long","target_contracts":"1","raw_signal":"1",
                "market_entry_policy":{"existing_position_contracts":client.state["position"]}}
    runtime=RegisteredCohortReplay.__new__(RegisteredCohortReplay)
    runtime.historical_input=SimpleNamespace(frame=__import__("pandas").DataFrame(
        [{"close":60000.0}],index=__import__("pandas").DatetimeIndex([datetime(2026,6,16,1,tzinfo=timezone.utc)])))
    runtime.replay=SimpleNamespace(_canonical_frame_cache=Cache(),controller=Controller(),
        spec=SimpleNamespace(identity=lambda:{"strategy_id":"don"}),venue=SimpleNamespace(state={"position":"9"}))
    runtime.don_row={"id":"delivery_"+"1"*32,"content_digest":"c"*64,
        "package":{"strategy_id":"registered-donchian"}}
    decision=datetime(2026,6,16,1,tzinfo=timezone.utc)
    flat,_=runtime._donchian_objects(decision,member_contracts=Decimal("0"),member_state={"sha256":"a"*64})
    held,_=runtime._donchian_objects(decision,member_contracts=Decimal("1"),member_state={"sha256":"b"*64})
    assert seen==["0","1"] and runtime.replay.venue.state["position"]=="9"
    assert flat["signal"].signal_id!=held["signal"].signal_id
