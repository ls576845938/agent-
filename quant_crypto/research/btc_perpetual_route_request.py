from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "btc_perpetual_route_request_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_perpetual_route_request/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_route_request_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_route_request_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_LONG_SHORT_OBSERVER_REPORT = Path(
    "artifacts/btc_long_short_top5_forward_observer/latest/btc_long_short_top5_forward_observer_report.json"
)
DEFAULT_ATTACK_OBSERVER_REPORT = Path(
    "artifacts/btc_bankroll_attack_forward_observer/latest/btc_bankroll_attack_forward_observer_report.json"
)
DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT = Path(
    "artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_followup_report.json"
)

STRATEGY_LINE_DEFINITIONS = {
    "long_short_donchian_top5": {
        "source_kind": "long_short_observer",
        "requires_shorting": True,
        "requires_leverage": False,
        "max_research_leverage": 1.0,
        "reason": "long/short trend following needs a venue that can short BTC.",
    },
    "high_octane_attack_sleeve_v2": {
        "source_kind": "attack_observer",
        "requires_shorting": True,
        "requires_leverage": True,
        "max_research_leverage": 10.0,
        "reason": "10x attack sleeves require perpetual-like margin, mark/index, liquidation, and funding evidence.",
    },
    "high_yield_v2_frozen": {
        "source_kind": "high_yield_followup",
        "requires_shorting": True,
        "requires_leverage": True,
        "max_research_leverage": 2.5,
        "reason": "frozen high-yield v2 is a 2.5x long/short route and cannot be represented by spot-only execution.",
    },
}


def build_btc_perpetual_route_request(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    long_short_observer_report_path: Path = DEFAULT_LONG_SHORT_OBSERVER_REPORT,
    attack_observer_report_path: Path = DEFAULT_ATTACK_OBSERVER_REPORT,
    high_yield_followup_report_path: Path = DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name
    sources = {
        "long_short_observer": _read_json(long_short_observer_report_path),
        "attack_observer": _read_json(attack_observer_report_path),
        "high_yield_followup": _read_json(high_yield_followup_report_path),
    }
    paths = {
        "long_short_observer": long_short_observer_report_path,
        "attack_observer": attack_observer_report_path,
        "high_yield_followup": high_yield_followup_report_path,
    }
    lines = [
        _strategy_line(line_id=line_id, definition=definition, source=sources[definition["source_kind"]], path=paths[definition["source_kind"]])
        for line_id, definition in STRATEGY_LINE_DEFINITIONS.items()
    ]
    eligible = [line for line in lines if line["route_request_eligible"]]
    blockers: list[str] = []
    if not eligible:
        blockers.append("btc_perpetual_route_request_no_research_lines_ready")
    blockers.extend(_unsafe_source_blockers(sources))
    route_requested = bool(eligible) and not blockers
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "complete_research_only" if route_requested else "blocked",
        "decision": (
            "perpetual_route_requested_research_only_execution_evidence_required_no_paper_no_live"
            if route_requested
            else "perpetual_route_request_blocked_no_paper_no_live"
        ),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "declare_current_btc_research_lines_that_require_perpetual_execution_evidence",
        "code_commit": _git(["rev-parse", "--short", "HEAD"]),
        "perpetual_route_requested": route_requested,
        "current_strategy_uses_perpetual": route_requested,
        "perpetual_allowed_for_research_evidence_review": route_requested,
        "perpetual_allowed_for_paper": False,
        "perpetual_allowed_for_live": False,
        "strategy_line_count": len(lines),
        "eligible_strategy_line_count": len(eligible),
        "strategy_lines": lines,
        "required_evidence_before_paper": [
            "mark_price_and_index_price_visible_at_decision_time",
            "funding_rate_settlement_in_ledger",
            "fee_tier_and_positive_slippage_model",
            "depth_aware_slippage_history_or_manual_review_ready_floor",
            "exact_exchange_liquidation_formula_and_liquidation_snapshot_history",
            "exchange_runtime_or_paper_runtime_replay",
            "risk_circuit_breakers_and_kill_switch",
        ],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": _dedupe(blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC 永续路线声明",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 当前研究线是否需要永续：`{report.get('perpetual_route_requested')}`",
        f"- 可进入 paper：`{_mapping(report.get('gate')).get('paper_queue_write_allowed')}`",
        f"- 可解锁 live：`{_mapping(report.get('gate')).get('live_unlock_allowed')}`",
        "",
        "这个文件只声明研究路线的执行工具需求：做空、杠杆、资金费率、mark/index 和强平证据。它不是交易许可。",
        "",
        "## 策略线",
    ]
    for line in report.get("strategy_lines", []):
        if isinstance(line, Mapping):
            lines.append(
                f"- `{line.get('line_id')}`：eligible=`{line.get('route_request_eligible')}`，source=`{line.get('source_status')}`"
            )
    if report.get("blockers"):
        lines.extend(["", "## 阻断项"])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def _strategy_line(*, line_id: str, definition: Mapping[str, Any], source: Mapping[str, Any], path: Path) -> dict[str, Any]:
    gate = _mapping(source.get("gate"))
    guardrails = _mapping(source.get("guardrails"))
    status = str(source.get("status") or "")
    source_ok = bool(source) and status in {"complete_research_only", "complete", "active_research_only"}
    boundary_ok = (
        gate.get("paper_queue_write_allowed") is False
        and gate.get("live_unlock_allowed") is False
        and guardrails.get("broker_access_allowed", False) is False
        and guardrails.get("oms_access_allowed", False) is False
    )
    return {
        "line_id": line_id,
        "source_kind": definition["source_kind"],
        "source_path": _portable_path(path),
        "source_exists": bool(source),
        "source_status": status or "missing",
        "source_decision": source.get("decision"),
        "route_request_eligible": source_ok and boundary_ok,
        "requires_perpetual_execution_evidence": True,
        "requires_shorting": bool(definition["requires_shorting"]),
        "requires_leverage": bool(definition["requires_leverage"]),
        "max_research_leverage": float(definition["max_research_leverage"]),
        "reason": definition["reason"],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _unsafe_source_blockers(sources: Mapping[str, Mapping[str, Any]]) -> list[str]:
    unsafe_keys = {
        "paper_queue_write_allowed",
        "paper_or_live_unlock_allowed",
        "live_unlock_allowed",
        "live_order_allowed",
        "oms_access_allowed",
        "broker_access_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
        "real_orders_created",
    }
    blockers: list[str] = []
    for source_name, payload in sources.items():
        for path, value in _walk(payload):
            if value is True and path.split(".")[-1] in unsafe_keys:
                blockers.append(f"btc_perpetual_route_request_unsafe_source_flag:{source_name}.{path}")
    return _dedupe(blockers)


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_perpetual_route_request_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "perpetual_route_requested": bool(report.get("perpetual_route_requested")),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "blockers": list(report.get("blockers", [])),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            out.extend(_walk(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _portable_path(path: Path) -> str:
    return path.as_posix()


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
