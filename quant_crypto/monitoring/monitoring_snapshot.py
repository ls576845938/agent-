from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_MONITORING_SNAPSHOT_VERSION = "btc_monitoring_snapshot_v1"

CRITICAL_SOURCES = {
    "current_status",
    "gate_dashboard",
    "daily_observation",
    "funding_ledger",
    "live_readiness",
    "paper_validation_runtime",
    "paper_validation_replay",
    "incident_replay_drill",
    "latest_target",
    "latest_paper_oms_lifecycle",
}


def build_btc_monitoring_snapshot(
    *,
    generated_at_utc: datetime,
    market_1h_status: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any] | None],
    source_paths: Mapping[str, str] | None = None,
    report_paths: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc)
    blockers: list[str] = []
    warnings: list[str] = []
    paths = dict(source_paths or {})
    source_summary = {
        name: _source_summary(name, payload, paths.get(name, ""))
        for name, payload in sources.items()
    }

    for name in sorted(CRITICAL_SOURCES):
        if not sources.get(name):
            blockers.append(f"btc_monitoring_snapshot_source_missing:{name}")
    if not market_1h_status:
        blockers.append("btc_monitoring_snapshot_market_1h_status_missing")

    current_status = _mapping(sources.get("current_status"))
    gate_dashboard = _mapping(sources.get("gate_dashboard"))
    daily_observation = _mapping(sources.get("daily_observation"))
    funding_ledger = _mapping(sources.get("funding_ledger"))
    live_readiness = _mapping(sources.get("live_readiness"))
    paper_runtime = _mapping(sources.get("paper_validation_runtime"))
    paper_replay = _mapping(sources.get("paper_validation_replay"))
    incident_drill = _mapping(sources.get("incident_replay_drill"))
    latest_target_artifact = _mapping(sources.get("latest_target"))
    order_intent_artifact = _mapping(sources.get("latest_order_intent"))
    paper_oms_lifecycle = _mapping(sources.get("latest_paper_oms_lifecycle"))
    paper_oms_session = _mapping(sources.get("paper_oms_session_contract"))
    data_status = _mapping(sources.get("data_status"))

    live_status = str(current_status.get("live_status") or "")
    current_state = str(current_status.get("status") or current_status.get("current_status") or "")
    if current_state and current_state != "paper_observing":
        blockers.append("btc_monitoring_snapshot_current_status_not_paper_observing")
    if live_status and live_status != "frozen":
        blockers.append("btc_monitoring_snapshot_live_status_not_frozen")

    unsafe_flags = _unsafe_flags({"market_1h_status": market_1h_status, **{k: v for k, v in sources.items() if v}})
    blockers.extend(f"btc_monitoring_snapshot_unsafe_flag:{flag}" for flag in unsafe_flags)

    latest_market_close = str(market_1h_status.get("latest_close_time_utc") or "")
    data_status_end = _data_status_current_1h_end(data_status)
    legacy_data_status_end = str(_mapping(data_status.get("coverage")).get("sample_end") or "")
    if latest_market_close and data_status_end and latest_market_close > data_status_end:
        warnings.append("btc_monitoring_data_status_artifact_older_than_market_1h")

    target = _mapping(latest_target_artifact.get("target"))
    target_metadata = _mapping(target.get("metadata"))
    replay_metadata = _mapping(paper_replay.get("metadata"))
    funding_status = _funding_status(funding_ledger)
    risk_blockers = _dedupe(
        [str(item) for item in live_readiness.get("blockers", []) if item]
        + [str(item) for item in gate_dashboard.get("blockers", []) if item]
    )
    payload = {
        "monitoring_snapshot_version": BTC_MONITORING_SNAPSHOT_VERSION,
        "status": "blocked" if blockers else "complete",
        "scope": "btc_read_only_monitoring_page_snapshot",
        "asset": "btc",
        "symbol": "BTCUSDT",
        "read_only": True,
        "current_state": {
            "status": current_state,
            "live_status": live_status,
            "paper_state": _mapping(gate_dashboard.get("paper_state")),
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
        },
        "data_freshness": {
            "market_1h": {
                "status": market_1h_status.get("status", "missing"),
                "exchange": market_1h_status.get("exchange"),
                "interval": market_1h_status.get("interval"),
                "row_count": _int_value(market_1h_status.get("row_count")),
                "latest_closed_bar_time_utc": latest_market_close,
                "latest_close": _float_or_none(market_1h_status.get("latest_close")),
                "latest_volume": _float_or_none(market_1h_status.get("latest_volume")),
                "ingested_at_utc": market_1h_status.get("latest_ingested_at_utc"),
                "closed_bar_only": bool(market_1h_status.get("closed_bar_only", False)),
            },
            "daily_observation": {
                "status": daily_observation.get("status"),
                "sample_end": _mapping(daily_observation.get("data")).get("sample_end"),
                "observation_days": _nested_int(daily_observation, "forward_observation.observation_days"),
                "minimum_complete_days": _nested_int(live_readiness, "forward_observation.minimum_complete_days"),
                "public_rest_only": _mapping(daily_observation.get("data")).get("public_rest_only"),
                "simulated_only": _mapping(daily_observation.get("guardrails")).get("simulated_only"),
            },
            "data_status_artifact": {
                "status": data_status.get("status"),
                "generated_at": data_status.get("generated_at"),
                "sample_end": data_status_end,
                "legacy_lineage_sample_end": legacy_data_status_end,
                "current_sqlite_coverage_status": _mapping(data_status.get("current_sqlite_coverage")).get("status"),
                "warning_if_older_than_market_1h": "btc_monitoring_data_status_artifact_older_than_market_1h" in warnings,
            },
        },
        "funding": {
            "status": funding_status,
            "funding_info_available": bool(funding_ledger.get("funding_info_available", False)),
            "funding_rate_available": bool(funding_ledger.get("funding_rate_available", False)),
            "funding_payment_in_ledger": bool(funding_ledger.get("funding_payment_in_ledger", False)),
            "funding_adjusted_net_pnl_reconciled": bool(
                funding_ledger.get("funding_adjusted_net_pnl_reconciled", False)
            ),
            "funding_interval_hours": _float_or_none(funding_ledger.get("funding_interval_hours")),
            "funding_events_count": _int_value(funding_ledger.get("funding_events_count")),
            "promotion_evidence": bool(funding_ledger.get("promotion_evidence", False)),
        },
        "position_target": {
            "status": "present" if target else "missing",
            "strategy_id": target.get("strategy_id"),
            "target_position_id": target.get("target_position_id"),
            "timestamp_utc": target.get("timestamp_utc"),
            "target_weight": _float_or_none(target.get("target_weight")),
            "target_quantity": _float_or_none(target.get("target_quantity")),
            "target_notional": _float_or_none(target_metadata.get("target_notional")),
            "order_generation_allowed": bool(target_metadata.get("order_generation_allowed", False)),
            "perpetual_allowed": bool(_mapping(target_metadata.get("perpetual_risk_policy")).get("perpetual_allowed", False)),
            "risk_state": _mapping(target_metadata.get("risk_state")),
            "order_required": bool(paper_oms_lifecycle.get("order_required", False)),
            "order_intent_present": bool(order_intent_artifact.get("order_intent")),
        },
        "paper_fills": {
            "source": "paper_oms_session_contract_evidence",
            "runtime_status": paper_runtime.get("status"),
            "paper_oms_session_status": paper_oms_session.get("status"),
            "order_count": _int_value(paper_oms_session.get("order_count")),
            "fill_count": _int_value(paper_oms_session.get("fill_count")),
            "rejected_order_count": _nested_int(paper_oms_session, "execution_quality.rejected_order_count"),
            "fill_rate": _float_or_none(_mapping(paper_oms_session.get("execution_quality")).get("fill_rate")),
            "latest_daily_order_required": bool(paper_oms_lifecycle.get("order_required", False)),
            "latest_daily_order_reason": paper_oms_lifecycle.get("reason"),
            "latest_fill_sample": _latest_fill_sample(paper_oms_session),
        },
        "risk_blockers": {
            "live_readiness_status": live_readiness.get("status"),
            "gate_dashboard_status": gate_dashboard.get("status"),
            "blockers": risk_blockers,
            "gate_checks": _mapping(live_readiness.get("gate_checks")),
            "operational_evidence": _mapping(live_readiness.get("operational_evidence")),
        },
        "incident_replay": {
            "incident_drill_status": incident_drill.get("status"),
            "incident_scenario_count": _int_value(incident_drill.get("scenario_count")),
            "required_scenarios": [
                str(item) for item in incident_drill.get("required_scenarios", []) if str(item)
            ],
            "paper_validation_replay_status": paper_replay.get("status"),
            "paper_validation_replay_decision": paper_replay.get("decision"),
            "current_realtime_data_accessed": bool(replay_metadata.get("current_realtime_data_accessed", False)),
            "replay_diffs_changed": _replay_changed(paper_replay),
        },
        "guardrails": {
            "live_order_allowed": False,
            "private_endpoint_used": any(_true_path(item, "private_endpoint_used") for item in sources.values() if item),
            "order_endpoint_used": any(_true_path(item, "order_endpoint_used") for item in sources.values() if item),
            "real_order_submitted": any(_true_path(item, "real_order_submitted") for item in sources.values() if item),
            "paper_queue_write_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
        },
        "source_report_details": source_summary,
        "report_paths": dict(report_paths or {}),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="btc_read_only_monitoring_snapshot_complete" if not blockers else "btc_read_only_monitoring_snapshot_blocked",
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=_dedupe(blockers),
        warnings=_dedupe(warnings),
        input_hashes={
            "market_1h_status": stable_payload_hash(market_1h_status),
            "sources": stable_payload_hash({name: payload or {} for name, payload in sources.items()}),
            "source_paths": stable_payload_hash(paths),
        },
    )


def render_btc_monitoring_snapshot_markdown(snapshot: Mapping[str, Any]) -> str:
    data = _mapping(snapshot.get("data_freshness"))
    market = _mapping(data.get("market_1h"))
    daily = _mapping(data.get("daily_observation"))
    target = _mapping(snapshot.get("position_target"))
    fills = _mapping(snapshot.get("paper_fills"))
    risk = _mapping(snapshot.get("risk_blockers"))
    incident = _mapping(snapshot.get("incident_replay"))
    blockers = [str(item) for item in snapshot.get("blockers", []) if item]
    warnings = [str(item) for item in snapshot.get("warnings", []) if item]
    return "\n".join(
        [
            "# BTC 只读监控快照",
            "",
            f"- 状态：`{snapshot.get('status')}`",
            f"- 生成时间：`{snapshot.get('generated_at')}`",
            f"- 最新 1H closed bar：`{market.get('latest_closed_bar_time_utc')}`，close=`{market.get('latest_close')}`",
            f"- 前向观察：`{daily.get('observation_days')}/{daily.get('minimum_complete_days')}` 天",
            f"- Funding：`{_mapping(snapshot.get('funding')).get('status')}`",
            f"- 当前目标仓位：weight=`{target.get('target_weight')}`，quantity=`{target.get('target_quantity')}`",
            f"- Paper fills（contract 证据）：orders=`{fills.get('order_count')}`，fills=`{fills.get('fill_count')}`",
            f"- Replay：`{incident.get('paper_validation_replay_status')}`，实时数据访问=`{incident.get('current_realtime_data_accessed')}`",
            f"- Live readiness：`{risk.get('live_readiness_status')}`",
            f"- Live 下单允许：`{_mapping(snapshot.get('guardrails')).get('live_order_allowed')}`",
            "",
            "## 风险阻塞",
            "",
            *(f"- `{item}`" for item in _list_or_none(_mapping(risk).get("blockers"))),
            *(["- 无"] if not _mapping(risk).get("blockers") else []),
            "",
            "## 快照自身 blocker / warning",
            "",
            *(f"- blocker: `{item}`" for item in blockers),
            *(f"- warning: `{item}`" for item in warnings),
            *(["- 无"] if not blockers and not warnings else []),
            "",
            "说明：这是只读监控页面数据，不写 paper 队列，不解锁 live，不触达 OMS/broker。",
            "",
        ]
    )


def render_btc_monitoring_snapshot_html(snapshot: Mapping[str, Any]) -> str:
    data = _mapping(snapshot.get("data_freshness"))
    market = _mapping(data.get("market_1h"))
    daily = _mapping(data.get("daily_observation"))
    funding = _mapping(snapshot.get("funding"))
    target = _mapping(snapshot.get("position_target"))
    fills = _mapping(snapshot.get("paper_fills"))
    risk = _mapping(snapshot.get("risk_blockers"))
    incident = _mapping(snapshot.get("incident_replay"))
    guardrails = _mapping(snapshot.get("guardrails"))
    cards = [
        ("最新 1H Bar", market.get("latest_closed_bar_time_utc"), f"close {market.get('latest_close')}"),
        ("前向观察", f"{daily.get('observation_days')}/{daily.get('minimum_complete_days')} 天", daily.get("status")),
        ("Funding", funding.get("status"), f"events {funding.get('funding_events_count')}"),
        ("目标仓位", f"weight {target.get('target_weight')}", f"qty {target.get('target_quantity')}"),
        ("Paper Fills", f"{fills.get('fill_count')} fills", f"{fills.get('order_count')} orders"),
        ("Replay", incident.get("paper_validation_replay_status"), f"live data {incident.get('current_realtime_data_accessed')}"),
    ]
    blocker_items = "\n".join(f"<li><code>{escape(str(item))}</code></li>" for item in _list_or_none(risk.get("blockers")))
    if not blocker_items:
        blocker_items = "<li>无</li>"
    source_rows = "\n".join(
        "<tr>"
        f"<td>{escape(name)}</td>"
        f"<td>{escape(str(_mapping(row).get('status', '')))}</td>"
        f"<td>{escape(str(_mapping(row).get('generated_at', '')))}</td>"
        f"<td><code>{escape(str(_mapping(row).get('artifact_hash', ''))[:12])}</code></td>"
        "</tr>"
        for name, row in _mapping(snapshot.get("source_report_details")).items()
    )
    card_html = "\n".join(
        f"<section class=\"metric\"><span>{escape(str(title))}</span><strong>{escape(str(value))}</strong><small>{escape(str(note))}</small></section>"
        for title, value, note in cards
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BTC 只读监控快照</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, "Microsoft YaHei", sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #18202a; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 18px; }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    .status {{ padding: 6px 10px; border: 1px solid #c9d4df; border-radius: 6px; background: #fff; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
    .metric, .panel {{ background: #fff; border: 1px solid #dfe5eb; border-radius: 8px; padding: 14px; }}
    .metric span, .metric small {{ display: block; color: #586473; font-size: 12px; }}
    .metric strong {{ display: block; margin: 8px 0 4px; font-size: 18px; word-break: break-word; }}
    .panels {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; margin-top: 12px; }}
    h2 {{ margin: 0 0 10px; font-size: 16px; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 5px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; margin-top: 12px; border: 1px solid #dfe5eb; }}
    th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid #edf1f4; font-size: 13px; }}
    code {{ background: #eef2f6; padding: 1px 4px; border-radius: 4px; }}
    .note {{ color: #586473; margin-top: 12px; }}
    @media (max-width: 760px) {{ main {{ padding: 16px; }} header, .panels {{ display: block; }} .status {{ display: inline-block; margin-top: 10px; }} .panel {{ margin-top: 12px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>BTC 只读监控快照</h1>
      <div class="note">生成时间：<code>{escape(str(snapshot.get("generated_at")))}</code></div>
    </div>
    <div class="status">{escape(str(snapshot.get("status")))}</div>
  </header>
  <section class="grid">{card_html}</section>
  <section class="panels">
    <div class="panel">
      <h2>Risk Blockers</h2>
      <ul>{blocker_items}</ul>
    </div>
    <div class="panel">
      <h2>Guardrails</h2>
      <ul>
        <li>live_order_allowed: <code>{escape(str(guardrails.get("live_order_allowed")))}</code></li>
        <li>private_endpoint_used: <code>{escape(str(guardrails.get("private_endpoint_used")))}</code></li>
        <li>order_endpoint_used: <code>{escape(str(guardrails.get("order_endpoint_used")))}</code></li>
        <li>real_order_submitted: <code>{escape(str(guardrails.get("real_order_submitted")))}</code></li>
      </ul>
    </div>
  </section>
  <table>
    <thead><tr><th>Source</th><th>Status</th><th>Generated</th><th>Hash</th></tr></thead>
    <tbody>{source_rows}</tbody>
  </table>
  <p class="note">只读页面：不写 paper 队列，不解锁 live，不触达 OMS/broker。</p>
</main>
</body>
</html>
"""


def _source_summary(name: str, payload: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
    if not payload:
        return {
            "exists": False,
            "path": path,
            "status": "missing",
            "generated_at": "",
            "as_of_utc": "",
            "artifact_hash": "",
            "blockers": ["artifact_missing"],
        }
    blockers = [str(item) for item in payload.get("blockers", []) if item]
    return {
        "exists": True,
        "path": path,
        "status": _status_text(payload),
        "generated_at": _first_text(payload, "generated_at", "generated_at_utc"),
        "as_of_utc": _first_text(payload, "as_of_utc", "generated_at", "generated_at_utc"),
        "artifact_hash": str(payload.get("artifact_hash") or stable_payload_hash(payload)),
        "blockers": blockers,
    }


def _funding_status(payload: Mapping[str, Any]) -> str:
    if not payload:
        return "missing"
    if payload.get("funding_adjusted_net_pnl_reconciled") is True and payload.get("funding_payment_in_ledger") is True:
        return "funding_ledger_reconciled"
    if payload.get("blockers"):
        return "blocked"
    return str(payload.get("status") or "present")


def _latest_fill_sample(payload: Mapping[str, Any]) -> dict[str, Any]:
    fills = payload.get("fills")
    if not isinstance(fills, list) or not fills:
        return {}
    fill = fills[-1]
    if not isinstance(fill, Mapping):
        return {}
    return {
        "fill_id": fill.get("fill_id"),
        "client_order_id": fill.get("client_order_id"),
        "filled_at_utc": fill.get("filled_at_utc"),
        "filled_quantity": _float_or_none(fill.get("filled_quantity")),
        "fill_price": _float_or_none(fill.get("fill_price")),
    }


def _replay_changed(payload: Mapping[str, Any]) -> bool:
    diffs = payload.get("diffs")
    if not isinstance(diffs, Mapping):
        return False
    return any(_mapping(row).get("changed") is True for row in diffs.values())


def _data_status_current_1h_end(payload: Mapping[str, Any]) -> str:
    current = _mapping(payload.get("current_sqlite_coverage"))
    latest_by_interval = _mapping(_mapping(current.get("coverage")).get("latest_close_time_by_interval"))
    value = latest_by_interval.get("1h")
    if value:
        return str(value)
    latest_bar = _mapping(current.get("latest_closed_bar"))
    if latest_bar.get("close_time"):
        return str(latest_bar["close_time"])
    return str(_mapping(payload.get("coverage")).get("sample_end") or "")


def _unsafe_flags(payload: Mapping[str, Any]) -> list[str]:
    unsafe_keys = {
        "live_order_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
        "real_orders_created",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
        "oms_access_allowed",
        "broker_access_allowed",
    }
    flags: list[str] = []
    for path, value in _walk(payload):
        if value is True and path.split(".")[-1] in unsafe_keys:
            if path.endswith("guardrails.simulated_only"):
                continue
            flags.append(f"{path}=true")
    return _dedupe(flags)


def _true_path(payload: Mapping[str, Any], key: str) -> bool:
    for path, value in _walk(payload):
        if path.split(".")[-1] == key and value is True:
            return True
    return False


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


def _status_text(payload: Mapping[str, Any]) -> str:
    return str(payload.get("status") or payload.get("decision") or payload.get("current_status") or "present")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _nested_int(payload: Mapping[str, Any], path: str) -> int:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return 0
        value = value.get(part)
    return _int_value(value)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_or_none(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
