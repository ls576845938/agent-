"""Bounded projection built only by an authoritative worker after each commit."""
from decimal import Decimal
from quant_shared.strategy_delivery.models import digest
from quant_shared.strategy_delivery.offline_contract import safety, identity_fields, require_job_identity


def projection(job, runtime, receipt):
    custom=getattr(runtime,"offline_projection",None)
    if callable(custom): return custom(job,receipt)
    state = runtime.venue.state
    controller = runtime.controller._state
    registered = runtime.registered_inputs
    value = {"schema_version": "candidate_offline_result_v2", **safety(),
        **identity_fields(require_job_identity(job, job["id"])), "run_id": runtime.config.run_id,
        "adapter_id": registered.package["adapter_id"],
        "verified_through_event": receipt.get("decision_time_utc") or receipt.get("event_time_utc") or job.get("last_completed_event"),
        "decision_receipt": receipt, "decision_receipt_sha256": digest(receipt),
        "position_contracts": state["position"], "order_count": len(state["orders"]),
        "fill_count": len(state["fills"]), "orders": state["orders"][-20:], "fills": state["fills"][-20:],
        "protection": state["algos"],
        "ledger": controller.get("ledger_reconciliation", {}).get("account_ledger_replay"),
        "limitations": ["simulated_not_real_fills", "sampled_mark_protection_only",
                         "intrainterval_mark_path_not_inferred", "bounded_last_20_orders_and_fills"]}
    value["sha256"] = digest(value)
    return value


def cohort_projection(job, runtime, committed):
    from quant_shared.strategy_delivery.offline_contract import cohort_identity_fields,require_cohort_job_identity
    authority=require_cohort_job_identity(job,job["id"])
    allocation=committed.get("strategy_allocations") or {}
    members=allocation.get("member_contracts") or {}
    expected={row["registration_id"] for row in authority["members"]}
    conserved=(set(members)==expected and sum(Decimal(str(value)) for value in members.values())
        == Decimal(str(committed.get("position_contracts") or 0)))
    value={"schema_version":"candidate_offline_cohort_result_v1",**safety(),
        **cohort_identity_fields(authority),"run_id":authority["run_id"],
        "adapter_id":"btc_registered_two_member_cohort_v1",
        "support_scope":"compatible_exact2_long_only" if conserved else "blocked_before_economics",
        "verified_through_event":committed.get("decision_time_utc") or job.get("last_completed_event"),
        "decision_receipt":committed,"decision_receipt_sha256":digest(committed),
        "position_contracts":committed.get("position_contracts"),"order_count":committed.get("order_count",0),
        "fill_count":committed.get("fill_count",0),"member_ownership":members,
        "member_ownership_conserved":conserved,"common_account_ref":authority["account_ref"],
        "source_accounts":{row["registration_id"]:row["source_account_ref"] for row in authority["members"]},
        "limitations":["simulated_not_real_fills","exact2_only","long_hold_reduce_only",
            "compatible_protection_policy_required","source_accounts_are_not_economic_authority",
            "sampled_mark_protection_only","intrainterval_mark_path_not_inferred"]}
    value["sha256"]=digest(value)
    return value
