from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_perpetual_paper_runtime_reconciliation_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_reconciliation_report.json"
DEFAULT_VIOLATIONS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_reconciliation_violations.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_reconciliation_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_paper_runtime_reconciliation_safety_status.json"

DEFAULT_CURRENT_EVENT_LEDGER_PATH = Path(
    "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv"
)
DEFAULT_DRILL_EVENT_LEDGER_PATH = Path(
    "artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_drill_event_ledger.csv"
)

ORDER_EVENT = "order_intent_created"
RISK_EVENT = "risk_checked"
FILL_EVENT = "simulated_fill"
FEE_EVENT = "fee_cashflow"
FUNDING_EVENT = "funding_cashflow"
CIRCUIT_BREAKER_EVENT = "circuit_breaker_triggered"
FLAT_EVENT = "flat_heartbeat"


def build_btc_perpetual_paper_runtime_reconciliation_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    current_event_ledger_path: Path = DEFAULT_CURRENT_EVENT_LEDGER_PATH,
    drill_event_ledger_path: Path = DEFAULT_DRILL_EVENT_LEDGER_PATH,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    violations_path = output_dir / DEFAULT_VIOLATIONS_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    current_rows = _read_ledger(current_event_ledger_path)
    drill_rows = _read_ledger(drill_event_ledger_path)
    rows = current_rows + drill_rows
    violations = _reconcile(rows)
    summary = _summary(rows=rows, violations=violations)
    status = "complete_research_only" if not violations else "incomplete_research_only"
    decision = (
        "paper_runtime_event_ledger_reconciled_research_only_no_paper_no_live"
        if not violations
        else "paper_runtime_event_ledger_reconciliation_failed_no_paper_no_live"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": status,
        "decision": decision,
        "scope": "btc_perpetual_paper_runtime_event_ledger_reconciliation_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            "current_event_ledger_path": _portable_path(current_event_ledger_path),
            "drill_event_ledger_path": _portable_path(drill_event_ledger_path),
        },
        "summary": summary,
        "checks": _checks(summary),
        "violations": violations[:200],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "warnings": _warnings(summary),
        "outputs": {
            "json": _portable_path(report_path),
            "violations_csv": _portable_path(violations_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_violations_csv(violations_path, violations)
    _write_text(markdown_path, render_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC 永续 paper runtime 事件账本对账报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 事件行数：`{summary.get('event_row_count')}`",
        f"- 事件组数：`{summary.get('event_group_count')}`",
        f"- 违规数：`{summary.get('violation_count')}`",
        f"- 当前 observe-only 事件行：`{summary.get('current_event_row_count')}`",
        f"- 历史 drill 事件行：`{summary.get('drill_event_row_count')}`",
        f"- fill 事件数：`{summary.get('fill_event_count')}`",
        f"- funding 现金流事件数：`{summary.get('funding_cashflow_event_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 结论边界",
        "",
        "这个报告只检查本地事件账本能不能自洽：订单意图、风控、成交、手续费和资金费率是否能按同一决策点对上。",
        "它不代表当前 paper runtime 已通过，也不会消除执行证据、L2 覆盖、当前空仓和无当前模拟成交等 blocker。",
    ]
    if report.get("violations"):
        lines.extend(["", "## 违规样例", ""])
        lines.extend(f"- `{item.get('violation_code')}`: {item.get('event_group_key')}" for item in report.get("violations", [])[:20])
    return "\n".join(lines) + "\n"


def _reconcile(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for row in rows:
        event_id = str(row.get("event_id") or "")
        if not event_id:
            violations.append(_violation(row, "missing_event_id", "event_id is required"))
        elif event_id in seen_event_ids:
            violations.append(_violation(row, "duplicate_event_id", "event_id must be unique"))
        seen_event_ids.add(event_id)
        if _bool(row.get("paper_queue_write_allowed")) or _bool(row.get("live_unlock_allowed")):
            violations.append(_violation(row, "paper_or_live_flag_true", "event ledger must remain research-only"))
        if _timestamp_or_none(row.get("event_time")) is None:
            violations.append(_violation(row, "event_time_not_utc_parseable", "event_time must be parseable UTC"))
        if _timestamp_or_none(row.get("decision_time")) is None:
            violations.append(_violation(row, "decision_time_not_utc_parseable", "decision_time must be parseable UTC"))

    for key, group in _groups(rows).items():
        types = [str(row.get("event_type") or "") for row in group]
        type_set = set(types)
        flat_count = types.count(FLAT_EVENT)
        if flat_count:
            if len(group) != flat_count:
                violations.append(_violation(group[0], "flat_group_has_non_flat_events", "flat heartbeat group cannot contain order/fill events"))
            for row in group:
                if _float(row.get("amount_usdt")) != 0.0:
                    violations.append(_violation(row, "flat_event_has_amount", "flat heartbeat amount must be zero"))
            continue

        if ORDER_EVENT in type_set and RISK_EVENT not in type_set:
            violations.append(_violation(group[0], "order_missing_risk_check", "order intent must have risk check"))
        if FILL_EVENT in type_set:
            if ORDER_EVENT not in type_set:
                violations.append(_violation(group[0], "fill_missing_order_intent", "fill must have order intent"))
            if RISK_EVENT not in type_set:
                violations.append(_violation(group[0], "fill_missing_risk_check", "fill must have risk check"))
            if not any(str(row.get("event_type")) == RISK_EVENT and _bool(row.get("risk_approved")) for row in group):
                violations.append(_violation(group[0], "fill_without_approved_risk", "fill must have approved risk check"))
            for row in group:
                if str(row.get("event_type")) == FILL_EVENT:
                    if _float(row.get("notional_usdt")) <= 0.0:
                        violations.append(_violation(row, "fill_notional_not_positive", "fill notional must be positive"))
                    if _float(row.get("execution_price")) <= 0.0 or _float(row.get("mark_price")) <= 0.0 or _float(row.get("index_price")) <= 0.0:
                        violations.append(_violation(row, "fill_reference_price_missing", "fill must carry execution/mark/index price"))
                    fill_time = _timestamp_or_none(row.get("event_time"))
                    decision_time = _timestamp_or_none(row.get("decision_time"))
                    if fill_time and decision_time and fill_time < decision_time:
                        violations.append(_violation(row, "fill_before_decision_time", "fill cannot precede decision_time"))
        if (FEE_EVENT in type_set or FUNDING_EVENT in type_set) and FILL_EVENT not in type_set:
            violations.append(_violation(group[0], "cashflow_without_fill", "fee/funding cashflow requires a fill"))
        if CIRCUIT_BREAKER_EVENT in type_set and FILL_EVENT in type_set:
            violations.append(_violation(group[0], "circuit_breaker_group_has_fill", "circuit breaker group cannot also fill"))
        if any(str(row.get("event_type")) == FEE_EVENT and _float(row.get("amount_usdt")) > 0.0 for row in group):
            violations.append(_violation(group[0], "fee_cashflow_positive", "fee cashflow must be non-positive"))
    return violations


def _summary(*, rows: Sequence[Mapping[str, Any]], violations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    event_counts = _event_type_counts(rows)
    return {
        "event_row_count": len(rows),
        "event_group_count": len(_groups(rows)),
        "violation_count": len(violations),
        "event_type_counts": event_counts,
        "current_event_row_count": sum(1 for row in rows if str(row.get("ledger_scope")) == "current_observe_only_paper_runtime_replay"),
        "drill_event_row_count": sum(1 for row in rows if str(row.get("ledger_scope")) == "historical_bar_replay_execution_drill"),
        "fill_event_count": event_counts.get(FILL_EVENT, 0),
        "risk_checked_event_count": event_counts.get(RISK_EVENT, 0),
        "fee_cashflow_event_count": event_counts.get(FEE_EVENT, 0),
        "funding_cashflow_event_count": event_counts.get(FUNDING_EVENT, 0),
        "flat_heartbeat_event_count": event_counts.get(FLAT_EVENT, 0),
        "paper_or_live_flag_true_count": sum(1 for row in rows if _bool(row.get("paper_queue_write_allowed")) or _bool(row.get("live_unlock_allowed"))),
        "paper_runtime_reconciliation_passed": len(violations) == 0,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _checks(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": "event_ledger_rows_present",
            "status": "pass" if _int(summary.get("event_row_count")) > 0 else "fail",
            "value": summary.get("event_row_count"),
        },
        {
            "check_id": "event_ledger_reconciliation_passed",
            "status": "pass" if summary.get("paper_runtime_reconciliation_passed") else "fail",
            "value": summary.get("violation_count"),
        },
        {
            "check_id": "paper_live_flags_false",
            "status": "pass" if _int(summary.get("paper_or_live_flag_true_count")) == 0 else "fail",
            "value": summary.get("paper_or_live_flag_true_count"),
        },
    ]


def _groups(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = _group_key(row)
        groups.setdefault(key, []).append(row)
    return groups


def _group_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("ledger_scope") or ""),
            str(row.get("strategy_line") or ""),
            str(row.get("candidate_id") or ""),
            str(row.get("decision_time") or ""),
        ]
    )


def _violation(row: Mapping[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        "violation_code": code,
        "message": message,
        "event_group_key": _group_key(row),
        "event_id": row.get("event_id"),
        "event_type": row.get("event_type"),
        "event_time": row.get("event_time"),
    }


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
        "reason": "Ledger reconciliation is an evidence check and cannot promote paper/live by itself.",
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


def _warnings(summary: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_perpetual_paper_runtime_reconciliation_research_only_no_paper_no_live"]
    if _int(summary.get("fill_event_count")) == 0:
        warnings.append("current_event_ledger_has_no_fill_events_if_only_flat_heartbeat")
    if _int(summary.get("drill_event_row_count")) > 0:
        warnings.append("historical_drill_reconciliation_is_not_current_paper_gate_evidence")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_perpetual_paper_runtime_reconciliation_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_runtime_reconciliation_passed": _mapping(report.get("summary")).get("paper_runtime_reconciliation_passed"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "violation_count": _mapping(report.get("summary")).get("violation_count"),
    }


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_violations_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = ["violation_code", "message", "event_group_key", "event_id", "event_type", "event_time"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _timestamp_or_none(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _event_type_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        event_type = str(row.get("event_type") or "")
        if event_type:
            counts[event_type] = counts.get(event_type, 0) + 1
    return counts
