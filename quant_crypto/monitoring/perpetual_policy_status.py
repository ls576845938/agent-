from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_PERPETUAL_POLICY_STATUS_VERSION = "btc_perpetual_policy_status_v1"

CRITICAL_DISABLED_PATH_SOURCES = (
    "latest_target",
    "paper_validation_replay",
    "live_readiness",
)

UNSAFE_TRUE_KEYS = {
    "live_order_allowed",
    "private_endpoint_used",
    "order_endpoint_used",
    "real_order_submitted",
    "real_orders_created",
    "paper_queue_write_allowed",
    "paper_or_live_unlock_allowed",
    "live_unlock_allowed",
    "oms_access_allowed",
    "broker_access_allowed",
}


def build_btc_perpetual_policy_status(
    *,
    generated_at_utc: datetime,
    sources: Mapping[str, Mapping[str, Any] | None],
    source_paths: Mapping[str, str] | None = None,
    report_paths: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc)
    paths = dict(source_paths or {})
    blockers: list[str] = []
    warnings: list[str] = []

    for name in CRITICAL_DISABLED_PATH_SOURCES:
        if not sources.get(name):
            blockers.append(f"btc_perpetual_policy_source_missing:{name}")

    target = _mapping(sources.get("latest_target"))
    target_payload = _mapping(target.get("target"))
    target_metadata = _mapping(target_payload.get("metadata"))
    target_policy = _mapping(target_metadata.get("perpetual_risk_policy"))
    target_risk_state = _mapping(target_metadata.get("risk_state"))

    replay = _mapping(sources.get("paper_validation_replay"))
    replay_metadata = _mapping(replay.get("metadata"))
    replay_policy = _mapping(replay_metadata.get("perpetual_risk_policy") or replay.get("perpetual_risk_policy"))

    live_readiness = _mapping(sources.get("live_readiness"))
    live_constitution = _mapping(live_readiness.get("risk_constitution"))
    instrument_limits = _mapping(live_constitution.get("instrument_limits"))
    route_request = _mapping(sources.get("perpetual_route_request"))

    funding_ledger = _mapping(sources.get("funding_ledger"))
    cost_model = _mapping(sources.get("cost_model"))
    liquidation_contract = _mapping(sources.get("liquidation_risk_contract"))

    target_disabled = _target_perpetual_disabled(target_policy, target_risk_state)
    replay_disabled = _policy_disabled(replay_policy)
    live_disabled = _live_constitution_disables_perp(instrument_limits)
    route_requested = _route_request_enabled(route_request)
    any_perp_enabled = _any_policy_enables_perp(target_policy, replay_policy, instrument_limits) or route_requested

    if not target_policy:
        blockers.append("btc_perpetual_policy_target_policy_missing")
    elif not target_disabled and not any_perp_enabled:
        blockers.append("btc_perpetual_policy_target_policy_not_explicitly_disabled")
    if not replay_policy:
        blockers.append("btc_perpetual_policy_replay_policy_missing")
    elif not replay_disabled and not any_perp_enabled:
        blockers.append("btc_perpetual_policy_replay_policy_not_explicitly_disabled")
    if not instrument_limits:
        blockers.append("btc_perpetual_policy_live_constitution_instrument_limits_missing")
    elif not live_disabled and not any_perp_enabled:
        blockers.append("btc_perpetual_policy_live_constitution_not_explicitly_disabled")

    if any_perp_enabled:
        blockers.extend(_perpetual_enabled_evidence_blockers(cost_model=cost_model, funding_ledger=funding_ledger))
        if not _liquidation_contract_complete(liquidation_contract):
            blockers.append("btc_perpetual_policy_liquidation_contract_not_complete_for_enabled_perp")

    unsafe_flags = _unsafe_flags({name: payload for name, payload in sources.items() if payload})
    blockers.extend(f"btc_perpetual_policy_unsafe_flag:{flag}" for flag in unsafe_flags)

    current_route = (
        "perpetual_requires_full_risk_evidence"
        if any_perp_enabled
        else "spot_or_unlevered_path_perpetual_disabled"
    )
    status = "blocked" if blockers else "complete"
    policy_decision = (
        "perpetual_enabled_evidence_incomplete"
        if any_perp_enabled and blockers
        else (
            "perpetual_enabled_evidence_review"
            if any_perp_enabled
            else "perpetual_path_disabled_for_current_strategy"
        )
    )
    payload = {
        "perpetual_policy_status_version": BTC_PERPETUAL_POLICY_STATUS_VERSION,
        "status": status,
        "scope": "btc_perpetual_path_policy_status",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "read_only": True,
        "current_route": current_route,
        "policy_decision": policy_decision,
        "current_strategy_uses_perpetual": bool(any_perp_enabled),
        "perpetual_route_request": _route_request_summary(route_request),
        "target_policy": {
            "strategy_id": target_payload.get("strategy_id"),
            "timestamp_utc": target_payload.get("timestamp_utc"),
            "perpetual_allowed": target_policy.get("perpetual_allowed"),
            "liquidation_risk_required": target_policy.get("liquidation_risk_required"),
            "funding_rate_required": target_policy.get("funding_rate_required"),
            "status": target_policy.get("status"),
            "reason": target_policy.get("reason"),
            "risk_state_perp_decision_status": target_risk_state.get("perp_risk_decision_status"),
            "risk_state_perp_decision_present": target_risk_state.get("perp_risk_decision") is not None,
        },
        "paper_replay_policy": {
            "status": replay_policy.get("status"),
            "perpetual_allowed": replay_policy.get("perpetual_allowed"),
            "liquidation_risk_required": replay_policy.get("liquidation_risk_required"),
            "perp_risk_decision_status": replay_policy.get("perp_risk_decision_status"),
            "reason": replay_policy.get("reason"),
            "replay_status": replay.get("status"),
            "current_realtime_data_accessed": replay_metadata.get("current_realtime_data_accessed"),
        },
        "live_constitution_policy": {
            "perpetual_allowed": instrument_limits.get("perpetual_allowed"),
            "leverage_cap": _float_or_none(instrument_limits.get("leverage_cap")),
            "shorting_allowed": instrument_limits.get("shorting_allowed"),
            "btc_spot_allowed_for_future_pilot": instrument_limits.get("btc_spot_allowed_for_future_pilot"),
            "live_readiness_status": live_readiness.get("status"),
        },
        "perpetual_evidence": {
            "funding": _funding_summary(funding_ledger),
            "mark_index": _mark_index_summary(cost_model),
            "liquidation": _liquidation_summary(cost_model, liquidation_contract),
            "evidence_required_for_current_route": bool(any_perp_enabled),
            "diagnostic_only_when_perpetual_disabled": not any_perp_enabled,
        },
        "gate": {
            "perpetual_allowed": bool(any_perp_enabled),
            "perpetual_policy_participates_in_promotion": bool(any_perp_enabled),
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "reason": (
                "current BTC strategy path explicitly disables perpetual leverage"
                if not any_perp_enabled
                else "perpetual research route is declared; paper/live remain locked until all execution evidence gates pass"
            ),
        },
        "guardrails": {
            "live_order_allowed": False,
            "private_endpoint_used": _any_true(sources, "private_endpoint_used"),
            "order_endpoint_used": _any_true(sources, "order_endpoint_used"),
            "real_order_submitted": _any_true(sources, "real_order_submitted"),
            "paper_queue_write_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
        },
        "source_report_details": {
            name: _source_summary(name, payload, paths.get(name, ""))
            for name, payload in sources.items()
        },
        "report_paths": dict(report_paths or {}),
    }
    return apply_btc_artifact_schema(
        payload,
        decision=f"btc_{policy_decision}" if not blockers else "btc_perpetual_policy_status_blocked",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=_dedupe(blockers),
        warnings=_dedupe(warnings),
        input_hashes={
            "sources": stable_payload_hash({name: payload or {} for name, payload in sources.items()}),
            "source_paths": stable_payload_hash(paths),
        },
    )


def render_btc_perpetual_policy_status_markdown(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    target = _mapping(report.get("target_policy"))
    replay = _mapping(report.get("paper_replay_policy"))
    live = _mapping(report.get("live_constitution_policy"))
    evidence = _mapping(report.get("perpetual_evidence"))
    return "\n".join(
        [
            "# BTC 永续路径策略状态",
            "",
            f"- 状态：`{report.get('status')}`",
            f"- 决策：`{report.get('decision')}`",
            f"- 当前路线：`{report.get('current_route')}`",
            f"- 当前策略使用永续：`{report.get('current_strategy_uses_perpetual')}`",
            f"- Gate 允许永续：`{gate.get('perpetual_allowed')}`",
            f"- 写 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
            f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
            "",
            "## 三处一致性",
            "",
            f"- Target：perpetual_allowed=`{target.get('perpetual_allowed')}`，perp_risk_decision_status=`{target.get('risk_state_perp_decision_status')}`",
            f"- Replay：perpetual_allowed=`{replay.get('perpetual_allowed')}`，status=`{replay.get('status')}`",
            f"- Live constitution：perpetual_allowed=`{live.get('perpetual_allowed')}`，leverage_cap=`{live.get('leverage_cap')}`，shorting_allowed=`{live.get('shorting_allowed')}`",
            "",
            "## 永续证据",
            "",
            f"- 当前路线是否要求永续证据：`{evidence.get('evidence_required_for_current_route')}`",
            f"- 永续禁用时仅作诊断：`{evidence.get('diagnostic_only_when_perpetual_disabled')}`",
            f"- Funding：`{_mapping(evidence.get('funding'))}`",
            f"- Mark/Index：`{_mapping(evidence.get('mark_index'))}`",
            f"- Liquidation：`{_mapping(evidence.get('liquidation'))}`",
            "",
            "说明：本报告只做永续路径 policy/evidence 状态审计，不写 paper 队列，不解锁 live，不触达 OMS/broker。",
            "",
        ]
    )


def _target_perpetual_disabled(policy: Mapping[str, Any], risk_state: Mapping[str, Any]) -> bool:
    return (
        policy.get("perpetual_allowed") is False
        and policy.get("liquidation_risk_required") is False
        and str(policy.get("status") or "") == "not_applicable_spot_or_unlevered_path"
        and str(risk_state.get("perp_risk_decision_status") or "") == "not_required_spot_or_unlevered_path"
    )


def _policy_disabled(policy: Mapping[str, Any]) -> bool:
    return (
        policy.get("perpetual_allowed") is False
        and policy.get("liquidation_risk_required") is False
        and str(policy.get("status") or "") == "not_applicable_spot_or_unlevered_path"
    )


def _live_constitution_disables_perp(instrument_limits: Mapping[str, Any]) -> bool:
    leverage_cap = _float_or_none(instrument_limits.get("leverage_cap"))
    return (
        instrument_limits.get("perpetual_allowed") is False
        and instrument_limits.get("shorting_allowed") is False
        and leverage_cap is not None
        and leverage_cap <= 1.0
    )


def _any_policy_enables_perp(
    target_policy: Mapping[str, Any],
    replay_policy: Mapping[str, Any],
    instrument_limits: Mapping[str, Any],
) -> bool:
    return any(
        item.get("perpetual_allowed") is True or item.get("liquidation_risk_required") is True
        for item in (target_policy, replay_policy, instrument_limits)
    )


def _route_request_enabled(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("perpetual_route_requested") is True
        and payload.get("current_strategy_uses_perpetual") is True
        and _mapping(payload.get("gate")).get("paper_queue_write_allowed") is False
        and _mapping(payload.get("gate")).get("live_unlock_allowed") is False
    )


def _route_request_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(payload),
        "status": payload.get("status"),
        "decision": payload.get("decision"),
        "perpetual_route_requested": payload.get("perpetual_route_requested"),
        "eligible_strategy_line_count": payload.get("eligible_strategy_line_count"),
        "strategy_line_count": payload.get("strategy_line_count"),
        "paper_queue_write_allowed": _mapping(payload.get("gate")).get("paper_queue_write_allowed"),
        "live_unlock_allowed": _mapping(payload.get("gate")).get("live_unlock_allowed"),
        "blockers": [str(item) for item in payload.get("blockers", []) if item],
    }


def _perpetual_enabled_evidence_blockers(
    *,
    cost_model: Mapping[str, Any],
    funding_ledger: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    funding = _mapping(cost_model.get("funding_model"))
    mark = _mapping(cost_model.get("mark_price_model"))
    if str(cost_model.get("status") or "") != "pass":
        blockers.append("btc_perpetual_policy_cost_model_not_pass")
    if funding_ledger.get("funding_payment_in_ledger") is not True:
        blockers.append("btc_perpetual_policy_funding_payment_not_in_ledger")
    if funding.get("funding_rate_available") is not True:
        blockers.append("btc_perpetual_policy_funding_rate_missing")
    if mark.get("mark_price_available") is not True:
        blockers.append("btc_perpetual_policy_mark_price_missing")
    if mark.get("premium_index_available") is not True:
        blockers.append("btc_perpetual_policy_index_or_premium_missing")
    return blockers


def _liquidation_contract_complete(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    status = str(payload.get("status") or payload.get("decision") or "")
    if status in {"complete", "pass", "approved"} and not payload.get("blockers"):
        return True
    return bool(payload.get("approved") is True and not payload.get("blockers"))


def _funding_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(payload),
        "funding_info_available": payload.get("funding_info_available"),
        "funding_rate_available": payload.get("funding_rate_available"),
        "funding_payment_in_ledger": payload.get("funding_payment_in_ledger"),
        "funding_adjusted_net_pnl_reconciled": payload.get("funding_adjusted_net_pnl_reconciled"),
        "funding_events_count": _int_value(payload.get("funding_events_count")),
        "promotion_evidence": payload.get("promotion_evidence"),
        "blockers": [str(item) for item in payload.get("blockers", []) if item],
    }


def _mark_index_summary(cost_model: Mapping[str, Any]) -> dict[str, Any]:
    mark = _mapping(cost_model.get("mark_price_model"))
    return {
        "present": bool(mark),
        "mark_price_available": mark.get("mark_price_available"),
        "mark_price_klines_available": mark.get("mark_price_klines_available"),
        "mark_price_current_available": mark.get("mark_price_current_available"),
        "premium_index_available": mark.get("premium_index_available"),
        "mark_price_used_for_liquidation_risk": mark.get("mark_price_used_for_liquidation_risk"),
        "blockers": [str(item) for item in mark.get("mark_price_blockers", []) if item],
    }


def _liquidation_summary(cost_model: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(cost_model.get("liquidation_data"))
    return {
        "cost_model_liquidation_data": data,
        "contract_present": bool(contract),
        "contract_status": contract.get("status"),
        "contract_decision": contract.get("decision"),
        "contract_complete": _liquidation_contract_complete(contract),
        "contract_blockers": [str(item) for item in contract.get("blockers", []) if item],
    }


def _source_summary(name: str, payload: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
    data = _mapping(payload)
    return {
        "source_name": name,
        "path": path,
        "present": bool(data),
        "status": _summary_status(data),
        "decision": str(data.get("decision") or ""),
        "generated_at": str(data.get("generated_at") or data.get("generated_at_utc") or ""),
        "as_of_utc": str(data.get("as_of_utc") or ""),
        "artifact_hash": str(data.get("artifact_hash") or stable_payload_hash(data)) if data else "",
        "blockers": [str(item) for item in data.get("blockers", []) if item],
    }


def _summary_status(payload: Mapping[str, Any]) -> str:
    if not payload:
        return "missing"
    for key in ("status", "decision", "policy_decision"):
        if payload.get(key):
            return str(payload[key])
    return "present"


def _unsafe_flags(sources: Mapping[str, Mapping[str, Any]]) -> list[str]:
    flags: list[str] = []
    for source_name, payload in sources.items():
        for path, value in _walk(payload):
            if value is True and path.split(".")[-1] in UNSAFE_TRUE_KEYS:
                flags.append(f"{source_name}.{path}=true")
    return _dedupe(flags)


def _any_true(sources: Mapping[str, Mapping[str, Any] | None], key: str) -> bool:
    return any(path.endswith(key) and value is True for payload in sources.values() for path, value in _walk(payload or {}))


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
