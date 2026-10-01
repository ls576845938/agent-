"""Bounded projection built only by an authoritative worker after each commit."""
from quant_shared.strategy_delivery.models import digest
from quant_shared.strategy_delivery.offline_contract import safety, identity_fields, require_job_identity


def projection(job, runtime, receipt):
    state = runtime.venue.state
    controller = runtime.controller._state
    value = {"schema_version": "candidate_offline_result_v2", **safety(),
        **identity_fields(require_job_identity(job, job["id"])), "run_id": runtime.config.run_id,
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
