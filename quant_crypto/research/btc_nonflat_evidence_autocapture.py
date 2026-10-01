"""Fail-closed autocapture for a naturally occurring BTC non-flat sample."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "btc_nonflat_evidence_autocapture_v1"
NATURAL_ORIGIN = "current_natural_observation"
REQUIRED_NODE_TYPES = (
    "signal_forecast",
    "target_position",
    "cost_risk_decision",
    "order_intent",
    "oms_lifecycle",
    "fill",
    "position_cash_funding_ledger",
    "liquidation_buffer",
    "depth_fill_mapping",
    "reconciliation",
    "audit_dag_replay",
)
FORBIDDEN_REPLAY_PATH_TOKENS = ("latest", "current", "live")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _binding(
    *, run_id: str, strategy_version: str, data_version: str, source_head: str
) -> dict[str, str]:
    return {
        "run_id": str(run_id),
        "strategy_version": str(strategy_version),
        "data_version": str(data_version),
        "source_head": str(source_head),
    }


def _node(
    *,
    ordinal: int,
    node_type: str,
    binding: Mapping[str, str],
    payload: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    dependency_refs = [
        {"node_id": str(item["node_id"]), "node_hash": str(item["node_hash"])}
        for item in dependencies
    ]
    body = {
        "ordinal": ordinal,
        "node_id": f"{ordinal:02d}-{node_type}",
        "node_type": node_type,
        "binding": dict(binding),
        "payload": json.loads(json.dumps(payload, default=str)),
        "payload_hash": _sha256(payload),
        "dependencies": dependency_refs,
        "dependency_hash": _sha256(dependency_refs),
    }
    return {**body, "node_hash": _sha256(body)}


def build_btc_nonflat_evidence_autocapture(
    *,
    replay_rows: Sequence[Mapping[str, Any]],
    oms_session: Mapping[str, Any],
    run_id: str,
    strategy_version: str,
    data_version: str,
    source_head: str,
    sample_origin: str = NATURAL_ORIGIN,
    private_ws_observed: bool = False,
    funding_cashflow_observed: bool = False,
) -> dict[str, Any]:
    """Build an in-memory evidence envelope without reading runtime pointers."""

    binding = _binding(
        run_id=run_id,
        strategy_version=strategy_version,
        data_version=data_version,
        source_head=source_head,
    )
    binding_blockers = [
        f"btc_nonflat_binding_missing:{name}" for name, value in binding.items() if not value
    ]
    nonflat = [
        dict(row)
        for row in replay_rows
        if float(row.get("target_exposure") or 0.0) != 0.0
    ]
    if not nonflat:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "waiting_for_natural_non_flat_sample",
            "decision": "observe_only_wait_no_order_no_fill",
            "sample_origin": sample_origin,
            "binding": binding,
            "nodes": [],
            "audit_dag": _validate_dag([], binding),
            "blockers": binding_blockers,
            "quality_checked": not binding_blockers,
            "promotion_evidence_ready": False,
            "paper_queue_write_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "live_unlock_allowed": False,
        }

    row = nonflat[0]
    nodes: list[dict[str, Any]] = []

    def add(node_type: str, payload: Mapping[str, Any]) -> None:
        nodes.append(
            _node(
                ordinal=len(nodes) + 1,
                node_type=node_type,
                binding=binding,
                payload=payload,
                dependencies=nodes[-1:],
            )
        )

    signal = row.get("signal")
    forecast = row.get("forecast")
    if signal not in (None, "") and forecast not in (None, ""):
        add("signal_forecast", {"signal": signal, "forecast": forecast, "decision_time": row.get("decision_time")})
    add(
        "target_position",
        {
            "target_exposure": row.get("target_exposure"),
            "side": row.get("side"),
            "candidate_id": row.get("candidate_id"),
        },
    )
    add(
        "cost_risk_decision",
        {
            "risk_decision": row.get("risk_decision"),
            "risk_approved": row.get("risk_approved") is True,
            "risk_blockers": list(row.get("risk_blockers") or []),
            "fee_amount_usdt": row.get("fee_amount_usdt"),
            "modeled_slippage_bps": row.get("modeled_slippage_bps"),
        },
    )
    if row.get("risk_approved") is not True:
        dag = _validate_dag(nodes, binding)
        return _envelope(
            status="risk_rejected_fail_closed",
            decision="risk_rejected_no_order_intent",
            binding=binding,
            sample_origin=sample_origin,
            nodes=nodes,
            dag=dag,
            blockers=[*binding_blockers, *list(row.get("risk_blockers") or ["risk_rejected"])],
        )

    add(
        "order_intent",
        {
            "order_intent": row.get("order_intent"),
            "side": row.get("side"),
            "quantity_btc": row.get("quantity_btc"),
            "notional_usdt": row.get("notional_usdt"),
            "venue": row.get("venue"),
        },
    )
    order_records = list(oms_session.get("order_records") or [])
    add("oms_lifecycle", {"order_records": order_records})

    fill_records = list(oms_session.get("fill_records") or [])
    add(
        "fill",
        {
            "fill_records": fill_records,
            "fill_state": row.get("fill_state") or ("filled" if row.get("simulated_fill_created") else "unfilled"),
            "filled_quantity_btc": row.get("filled_quantity_btc", row.get("quantity_btc")),
        },
    )
    add(
        "position_cash_funding_ledger",
        {
            "position_ledger": row.get("position_ledger"),
            "cash_ledger": row.get("cash_ledger"),
            "funding_ledger": row.get(
                "funding_ledger",
                {
                    "funding_rate": row.get("funding_rate"),
                    "funding_amount_usdt": row.get("funding_amount_usdt"),
                },
            ),
            "funding_cashflow_observed": funding_cashflow_observed,
        },
    )
    add(
        "liquidation_buffer",
        {
            "mark_price": row.get("mark_price"),
            "index_price": row.get("index_price"),
            "liquidation_price": row.get("liquidation_price"),
            "liquidation_buffer_bps": row.get("liquidation_buffer_bps"),
        },
    )
    add(
        "depth_fill_mapping",
        {
            "depth_fill_mapping": row.get("depth_fill_mapping"),
            "paper_runtime_gate_eligible": row.get("paper_runtime_gate_eligible") is True,
        },
    )
    reconciliation = dict(oms_session.get("reconciliation_report") or {})
    add(
        "reconciliation",
        {
            "status": reconciliation.get("status"),
            "blockers": list(reconciliation.get("blockers") or []),
            "private_ws_observed": private_ws_observed,
        },
    )
    add(
        "audit_dag_replay",
        {
            "replay_source": "injected_snapshot_only",
            "source_paths": [],
            "fixed_clock_required": True,
            "fixed_seed_required": True,
        },
    )

    dag = _validate_dag(nodes, binding)
    blockers = list(binding_blockers)
    missing_types = [item for item in REQUIRED_NODE_TYPES if item not in {node["node_type"] for node in nodes}]
    blockers.extend(f"btc_nonflat_evidence_node_missing:{item}" for item in missing_types)
    if sample_origin != NATURAL_ORIGIN:
        blockers.append("btc_nonflat_sample_not_current_natural_observation")
    if not fill_records or row.get("simulated_fill_created") is not True:
        blockers.append("btc_nonflat_fill_missing")
    if not row.get("position_ledger") or not row.get("cash_ledger"):
        blockers.append("btc_nonflat_position_or_cash_ledger_missing")
    if row.get("funding_rate") in (None, "") and not row.get("funding_ledger"):
        blockers.append("btc_nonflat_funding_ledger_missing")
    if row.get("mark_price") in (None, "", 0) or row.get("index_price") in (None, "", 0):
        blockers.append("btc_nonflat_mark_or_index_price_missing")
    if row.get("liquidation_buffer_bps") in (None, ""):
        blockers.append("btc_nonflat_liquidation_buffer_missing")
    if not row.get("depth_fill_mapping"):
        blockers.append("btc_nonflat_depth_fill_mapping_missing")
    if reconciliation.get("status") != "complete" or reconciliation.get("blockers"):
        blockers.append("btc_nonflat_reconciliation_failed")
    if not private_ws_observed:
        blockers.append("btc_nonflat_private_ws_observation_not_authorized_or_missing")
    if not funding_cashflow_observed:
        blockers.append("btc_nonflat_funding_cashflow_real_observation_not_authorized_or_missing")
    if not dag["valid"]:
        blockers.extend(dag["blockers"])
    blockers = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    complete = not blockers
    status = (
        "promotion_evidence_chain_complete"
        if complete
        else (
            "partial_fill_evidence_incomplete"
            if str(row.get("fill_state") or "").lower() == "partial"
            else "nonflat_evidence_incomplete_fail_closed"
        )
    )
    return _envelope(
        status=status,
        decision="manual_gate_review_required" if complete else "blocked_no_paper_no_live",
        binding=binding,
        sample_origin=sample_origin,
        nodes=nodes,
        dag=dag,
        blockers=blockers,
        promotion_evidence_ready=complete,
    )


def replay_btc_nonflat_evidence(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an injected snapshot; never resolve latest/current/live paths."""

    source_paths = list(dict(snapshot.get("inputs") or {}).get("source_paths") or [])
    unsafe = [
        str(path)
        for path in source_paths
        if any(token in {part.lower() for part in str(path).replace("\\", "/").split("/")} for token in FORBIDDEN_REPLAY_PATH_TOKENS)
    ]
    if unsafe:
        return {
            "status": "blocked",
            "valid": False,
            "blockers": ["btc_nonflat_replay_forbidden_runtime_pointer"],
            "unsafe_source_paths": unsafe,
        }
    binding = dict(snapshot.get("binding") or {})
    dag = _validate_dag(list(snapshot.get("nodes") or []), binding)
    return {
        "status": "replay_valid" if dag["valid"] else "blocked",
        "valid": dag["valid"],
        "blockers": dag["blockers"],
        "node_count": dag["node_count"],
        "snapshot_hash": _sha256(snapshot),
    }


def _validate_dag(nodes: Sequence[Mapping[str, Any]], binding: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    previous: Mapping[str, Any] | None = None
    seen_types: list[str] = []
    for ordinal, raw in enumerate(nodes, start=1):
        node = dict(raw)
        seen_types.append(str(node.get("node_type", "")))
        body = {key: value for key, value in node.items() if key != "node_hash"}
        if node.get("ordinal") != ordinal:
            blockers.append(f"btc_nonflat_audit_dag_ordinal_invalid:{ordinal}")
        if dict(node.get("binding") or {}) != dict(binding):
            blockers.append(f"btc_nonflat_audit_dag_binding_mismatch:{ordinal}")
        if node.get("payload_hash") != _sha256(node.get("payload")):
            blockers.append(f"btc_nonflat_audit_dag_payload_hash_mismatch:{ordinal}")
        dependencies = list(node.get("dependencies") or [])
        expected_dependencies = (
            []
            if previous is None
            else [{"node_id": previous.get("node_id"), "node_hash": previous.get("node_hash")}]
        )
        if dependencies != expected_dependencies or node.get("dependency_hash") != _sha256(dependencies):
            blockers.append(f"btc_nonflat_audit_dag_dependency_invalid:{ordinal}")
        if node.get("node_hash") != _sha256(body):
            blockers.append(f"btc_nonflat_audit_dag_node_hash_mismatch:{ordinal}")
        previous = node
    expected_order = [item for item in REQUIRED_NODE_TYPES if item in seen_types]
    if seen_types != expected_order:
        blockers.append("btc_nonflat_audit_dag_node_order_invalid")
    return {
        "schema_version": "btc_nonflat_audit_dag_validation_v1",
        "valid": not blockers,
        "node_count": len(nodes),
        "node_types": seen_types,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _envelope(
    *,
    status: str,
    decision: str,
    binding: Mapping[str, Any],
    sample_origin: str,
    nodes: Sequence[Mapping[str, Any]],
    dag: Mapping[str, Any],
    blockers: Sequence[str],
    promotion_evidence_ready: bool = False,
) -> dict[str, Any]:
    diagnostic = sample_origin != NATURAL_ORIGIN
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "decision": decision,
        "sample_origin": sample_origin,
        "diagnostic_or_fixture_only": diagnostic,
        "binding": dict(binding),
        "nodes": [dict(node) for node in nodes],
        "audit_dag": dict(dag),
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item))),
        "quality_checked": bool(dag.get("valid")),
        "promotion_evidence_ready": bool(promotion_evidence_ready and not diagnostic),
        "paper_queue_write_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_unlock_allowed": False,
    }
