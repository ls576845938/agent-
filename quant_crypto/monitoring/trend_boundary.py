from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_TREND_BOUNDARY_REPORT_VERSION = "btc_trend_boundary_report_v1"
REQUIRED_CHAIN_KEYS = (
    "signal_artifact",
    "forecast_artifact",
    "target_artifact",
    "cost_gate_artifact",
    "order_intent_artifact",
    "paper_oms_lifecycle_artifact",
)


def build_btc_trend_boundary_report(
    *,
    source_report: Mapping[str, Any],
    generated_at_utc: datetime,
    boundary_chain: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    chain = dict(boundary_chain or {})
    blockers: list[str] = []
    guardrails = _mapping(source_report.get("guardrails"))
    if guardrails.get("real_order_submitted") is not False:
        blockers.append("btc_trend_boundary_real_order_submitted_not_false")
    if guardrails.get("private_endpoint_used") is not False:
        blockers.append("btc_trend_boundary_private_endpoint_used_not_false")
    if guardrails.get("order_endpoint_used") is not False:
        blockers.append("btc_trend_boundary_order_endpoint_used_not_false")
    if guardrails.get("live_order_allowed") is not False:
        blockers.append("btc_trend_boundary_live_order_allowed_not_false")
    for key in REQUIRED_CHAIN_KEYS:
        if not chain.get(key):
            blockers.append(f"btc_trend_boundary_chain_missing:{key}")
    if chain.get("forecast_source_boundary") != "signal_to_btc_forecast":
        blockers.append("btc_trend_boundary_forecast_not_from_signal_layer")
    if chain.get("target_source_boundary") != "forecast_to_target_position_no_order_intent":
        blockers.append("btc_trend_boundary_target_not_from_forecast_layer")
    if chain.get("order_intent_source_boundary") != "cost_gate_to_order_intent_no_broker_submit":
        blockers.append("btc_trend_boundary_order_intent_not_from_cost_gate")
    if chain.get("paper_oms_source_boundary") not in {"btc_paper_oms_lifecycle", None}:
        blockers.append("btc_trend_boundary_paper_oms_boundary_invalid")
    payload = {
        "trend_boundary_report_version": BTC_TREND_BOUNDARY_REPORT_VERSION,
        "status": "complete" if not blockers else "blocked",
        "source_pipeline": source_report.get("pipeline"),
        "source_status": source_report.get("status"),
        "source_symbol": source_report.get("symbol"),
        "chain": chain,
        "guardrails": dict(guardrails),
        "allows_live_orders": False,
        "real_order_submitted": bool(guardrails.get("real_order_submitted", False)),
        "private_endpoint_used": bool(guardrails.get("private_endpoint_used", False)),
        "order_endpoint_used": bool(guardrails.get("order_endpoint_used", False)),
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="trend_boundary_chain_complete" if not blockers else "trend_boundary_chain_blocked",
        generated_at_utc=ensure_utc(generated_at_utc),
        as_of_utc=ensure_utc(generated_at_utc),
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={
            "source_report": stable_payload_hash(source_report),
            "boundary_chain": stable_payload_hash(chain),
        },
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
