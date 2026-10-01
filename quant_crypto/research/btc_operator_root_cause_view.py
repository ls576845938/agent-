from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash


SCHEMA_VERSION = "btc_operator_root_cause_view_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_operator_root_cause_view/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_operator_root_cause_view_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_operator_root_cause_view_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_GATE_DASHBOARD_PATH = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
DEFAULT_PROMOTION_GATE_PATH = Path("artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json")
DEFAULT_MANUAL_APPROVAL_PATH = Path(
    "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
)
DEFAULT_KILL_SWITCH_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json")
DEFAULT_RUNTIME_REPLAY_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json")


@dataclass(frozen=True)
class SourceArtifact:
    source_id: str
    path: Path
    payload: Mapping[str, Any]
    exists: bool
    error: str = ""

    @property
    def generated_at_utc(self) -> str:
        return str(self.payload.get("generated_at_utc") or self.payload.get("generated_at") or "")

    @property
    def status(self) -> str:
        return str(self.payload.get("status") or "")

    @property
    def decision(self) -> str:
        return str(self.payload.get("decision") or "")


def build_btc_operator_root_cause_view(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    gate_dashboard_path: Path = DEFAULT_GATE_DASHBOARD_PATH,
    promotion_gate_path: Path = DEFAULT_PROMOTION_GATE_PATH,
    manual_approval_path: Path = DEFAULT_MANUAL_APPROVAL_PATH,
    kill_switch_path: Path = DEFAULT_KILL_SWITCH_PATH,
    runtime_replay_path: Path = DEFAULT_RUNTIME_REPLAY_PATH,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    sources = {
        "gate_dashboard": _load_source(root, "gate_dashboard", gate_dashboard_path),
        "promotion_gate_control": _load_source(root, "promotion_gate_control", promotion_gate_path),
        "manual_approval": _load_source(root, "manual_approval", manual_approval_path),
        "kill_switch": _load_source(root, "kill_switch", kill_switch_path),
        "runtime_replay": _load_source(root, "runtime_replay", runtime_replay_path),
    }
    dashboard = sources["gate_dashboard"].payload
    promotion = sources["promotion_gate_control"].payload
    manual = sources["manual_approval"].payload
    kill_switch = sources["kill_switch"].payload
    runtime = sources["runtime_replay"].payload
    task_queue = _mapping(promotion.get("root_cause_task_queue")) or _mapping(dashboard.get("root_cause_task_queue"))
    task_queue = _normalized_task_queue(task_queue=task_queue, runtime=runtime)
    root_cause_summary = _mapping(promotion.get("root_cause_summary")) or _mapping(dashboard.get("root_cause_summary"))
    root_cause_matrix = _list_of_mappings(promotion.get("root_cause_matrix")) or _list_of_mappings(
        dashboard.get("root_cause_matrix")
    )
    manual_state = _manual_review_state(manual)
    safety = _safety_bits()
    source_freshness = _source_freshness(sources, generated)
    blockers = _blockers(sources=sources, manual_state=manual_state, source_freshness=source_freshness)
    status = "blocked_research_only" if blockers or _source_blocked(sources) else "complete_research_only"
    decision = (
        "btc_operator_root_cause_view_blocked_read_only_no_paper_no_live"
        if status != "complete_research_only"
        else "btc_operator_root_cause_view_complete_read_only_no_paper_no_live"
    )
    next_action = _unique_next_action(task_queue=task_queue, manual_state=manual_state)
    report_path = output / DEFAULT_REPORT_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": status,
        "scope": "btc_operator_root_cause_view_read_only_no_paper_no_live",
        "current_stage": _current_stage(status=status, next_action=next_action, root_cause_summary=root_cause_summary),
        "root_cause_source": "promotion_gate_control" if promotion else "gate_dashboard",
        "root_cause_summary": {
            "raw_blocker_count": _int(root_cause_summary.get("raw_blocker_count")),
            "root_cause_count": _int(root_cause_summary.get("root_cause_count")) or len(root_cause_matrix),
            "dominant_root_cause_id": root_cause_summary.get("dominant_root_cause_id", ""),
        },
        "root_cause_task_queue": {
            "dashboard_should_show_root_causes_only": True,
            "data_wait_items": [_task_row(row) for row in _list_of_mappings(task_queue.get("data_wait_items"))],
            "immediate_development_items": [
                _task_row(row) for row in _list_of_mappings(task_queue.get("immediate_development_items"))
            ],
            "manual_review_items": _manual_review_items(manual_state),
            "operator_view_normalizations": _list_of_strings(task_queue.get("operator_view_normalizations")),
        },
        "top_root_causes": [_root_row(row) for row in root_cause_matrix[:5]],
        "unique_next_action": next_action,
        "forbidden_actions": _forbidden_actions(),
        "paper_live_forbidden": {
            **safety,
            "approval_is_authorization": False,
            "fixture_or_drill_can_clear_paper_gate": False,
            "reasons": _forbidden_reasons(promotion=promotion, manual_state=manual_state, runtime=runtime),
        },
        "manual_review": manual_state,
        "runtime_state": {
            "status": runtime.get("status", "missing"),
            "current_flat_heartbeat_healthy": _nested_bool(runtime, "summary", "current_flat_heartbeat_healthy"),
            "trade_execution_evidence_pending_reason": _nested(
                runtime, "summary", "trade_execution_evidence_pending_reason"
            ),
            "paper_runtime_gate_evidence": _nested_bool(runtime, "summary", "paper_runtime_gate_evidence"),
        },
        "kill_switch_state": {
            "status": kill_switch.get("status", "missing"),
            "kill_switch_engaged": _nested_bool(kill_switch, "policy_state", "kill_switch_engaged"),
            "cancel_only_mode": _nested_bool(kill_switch, "policy_state", "cancel_only_mode"),
            "paper_order_intake_allowed": False,
        },
        "source_freshness": source_freshness,
        "source_paths": {source_id: _portable_path(source.path) for source_id, source in sources.items()},
        "source_hashes": {source_id: stable_payload_hash(source.payload) for source_id, source in sources.items()},
        "raw_blocker_drilldown": {
            "raw_blockers_hidden_by_default": True,
            "raw_blocker_count": len(_list_of_strings(promotion.get("blockers"))),
            "raw_blocker_sample": [],
            "drilldown_source_path": _portable_path(promotion_gate_path),
        },
        "gate": safety,
        "guardrails": safety,
        "warnings": _warnings(manual_state=manual_state),
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    report = apply_btc_artifact_schema(
        payload,
        decision=decision,
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=blockers,
        warnings=payload["warnings"],
        input_hashes=payload["source_hashes"],
    )
    _write_json(report_path, report)
    _write_text(markdown_path, render_btc_operator_root_cause_view_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_operator_root_cause_view_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("root_cause_summary"))
    next_action = _mapping(report.get("unique_next_action"))
    manual = _mapping(report.get("manual_review"))
    lines = [
        "# BTC Operator Root-Cause View",
        "",
        f"- 当前状态：`{report.get('status')}`",
        f"- 当前阶段：`{report.get('current_stage')}`",
        f"- root cause 数：`{summary.get('root_cause_count')}`",
        f"- 原始 blocker 数：`{summary.get('raw_blocker_count')}`",
        f"- 唯一下一步：`{next_action.get('action_id')}` / `{next_action.get('owner')}`",
        f"- 推荐命令：`{next_action.get('command')}`",
        f"- 人工复核状态：`{manual.get('status')}`",
        "",
        "## 禁止动作",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("forbidden_actions", []))
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本报告只给操作员看 root cause 和下一步动作，不展示几百条 raw blocker，不写 paper 队列，不解锁 live。",
        ]
    )
    return "\n".join(lines) + "\n"


def _manual_review_state(manual: Mapping[str, Any]) -> dict[str, Any]:
    blockers = _list_of_strings(manual.get("blockers"))
    current = bool(manual.get("manual_approval_recorded")) and bool(manual.get("manual_review_missing_cleared")) and not blockers
    return {
        "status": "recorded_current_review_only" if current else "missing_or_invalid_review_only",
        "manual_approval_recorded": bool(manual.get("manual_approval_recorded")),
        "manual_review_missing_cleared": bool(manual.get("manual_review_missing_cleared")),
        "review_only_no_auto_paper_no_live": True,
        "approval_is_authorization": False,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "blockers": blockers,
        "reviewed_packet_sha256": _nested(manual, "approval_record", "reviewed_packet_sha256"),
        "reviewed_source_code_commit": _nested(manual, "approval_record", "reviewed_source_code_commit"),
        "reviewer": _nested(manual, "approval_record", "reviewer"),
        "expiry_utc": _nested(manual, "approval_record", "expiry_utc"),
    }


def _normalized_task_queue(*, task_queue: Mapping[str, Any], runtime: Mapping[str, Any]) -> dict[str, Any]:
    if not task_queue:
        return {}
    runtime_is_flat_wait = _runtime_flat_waiting_for_non_flat_sample(runtime)
    immediate_items = _list_of_mappings(task_queue.get("immediate_development_items"))
    if runtime_is_flat_wait:
        immediate_items = [
            item for item in immediate_items if str(item.get("root_cause_id") or "") != "runtime_not_connected"
        ]
    return {
        **dict(task_queue),
        "immediate_development_items": immediate_items,
        "operator_view_normalizations": [
            "runtime_not_connected_reclassified_to_waiting_non_flat_sample"
        ]
        if runtime_is_flat_wait
        else [],
    }


def _runtime_flat_waiting_for_non_flat_sample(runtime: Mapping[str, Any]) -> bool:
    summary = _mapping(runtime.get("summary"))
    pending_reason = str(summary.get("trade_execution_evidence_pending_reason") or "")
    return (
        runtime.get("blockers") in ([], None)
        and summary.get("current_flat_heartbeat_healthy") is True
        and summary.get("paper_runtime_gate_evidence") is not True
        and (
            summary.get("flat_no_gate_eligible_trade") is True
            or pending_reason == "waiting_for_current_gate_eligible_non_flat_fill"
        )
        and str(summary.get("current_observe_only_gate_evidence_state") or "pending") == "pending"
    )


def _unique_next_action(*, task_queue: Mapping[str, Any], manual_state: Mapping[str, Any]) -> dict[str, Any]:
    if manual_state.get("status") != "recorded_current_review_only":
        return {
            "action_id": "manual_review_sign_current_packet",
            "owner": "operator/manual reviewer",
            "category": "manual_review",
            "command": "py scripts/sign_btc_current_packet_approval.py --reviewer <reviewer_id> --write",
            "why": "当前 packet 的 review-only approval 缺失、旧 hash 或 stale commit；签核不会打开 paper/live。",
            "clears_only": ["manual_review_approval_missing"],
            "cannot_clear": ["data_wait", "runtime_current_non_flat_sample_gate", "paper/live authorization"],
        }
    immediate = _list_of_mappings(task_queue.get("immediate_development_items"))
    if immediate:
        first = immediate[0]
        return {
            "action_id": str(first.get("root_cause_id") or "immediate_development"),
            "owner": str(first.get("owner") or "developer"),
            "category": "immediate_development",
            "command": str(first.get("next_command") or "py scripts/build_btc_gate_aggregation_chain.py"),
            "why": str(first.get("label_cn") or "非数据工程 blocker"),
            "clears_only": _list_of_strings(first.get("acceptance_criteria")),
            "cannot_clear": ["paper/live authorization"],
        }
    data_wait = _list_of_mappings(task_queue.get("data_wait_items"))
    if data_wait:
        first = data_wait[0]
        action_id = str(first.get("root_cause_id") or "data_wait")
        return {
            "action_id": action_id,
            "owner": str(first.get("owner") or "data-runtime automation"),
            "category": "wait_only",
            "command": str(first.get("next_command") or "wait_for_automation_then_rebuild"),
            "why": _wait_only_reason(action_id=action_id, row=first),
            "clears_only": _list_of_strings(first.get("acceptance_criteria")),
            "cannot_clear": ["manual_review", "paper/live authorization"],
        }
    return {
        "action_id": "no_single_action_available",
        "owner": "operator",
        "category": "read_only",
        "command": "py scripts/build_btc_gate_aggregation_chain.py",
        "why": "未发现可执行 root-cause task，先重建聚合链。",
        "clears_only": [],
        "cannot_clear": ["paper/live authorization"],
    }


def _manual_review_items(manual_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    if manual_state.get("status") == "recorded_current_review_only":
        return []
    return [
        {
            "root_cause_id": "manual_review_approval_missing",
            "label_cn": "当前 packet 人工 review-only 签核缺失或失效",
            "owner": "operator/manual reviewer",
            "next_command": "py scripts/sign_btc_current_packet_approval.py --reviewer <reviewer_id> --write",
            "raw_blocker_count": len(_list_of_strings(manual_state.get("blockers"))) or 1,
            "affected_gates": ["manual_review_gate"],
            "acceptance_criteria": ["current packet hash and commit are signed as review-only"],
        }
    ]


def _wait_only_reason(*, action_id: str, row: Mapping[str, Any]) -> str:
    label = str(row.get("label_cn") or "")
    owner = str(row.get("owner") or "")
    if "strategy" in action_id or "策略" in label or "strategy" in owner:
        return "策略 forward/过拟合治理需要继续 observe-only，不是新增策略挖矿或绕过 gate 的开发任务。"
    if "runtime" in action_id or "非空" in label:
        return "runtime 捕获链已就绪时，等待真实 observe-only 非空样本；不能用 fixture/drill 替代 gate evidence。"
    return "数据等待不是程序员手动修代码任务。"


def _blockers(
    *,
    sources: Mapping[str, SourceArtifact],
    manual_state: Mapping[str, Any],
    source_freshness: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for source_id, source in sources.items():
        if not source.exists:
            blockers.append(f"btc_operator_root_cause_view_source_missing:{source_id}")
        if source.error:
            blockers.append(f"btc_operator_root_cause_view_source_error:{source_id}")
    if manual_state.get("status") != "recorded_current_review_only":
        blockers.append("btc_operator_root_cause_view_manual_review_not_current_review_only")
    blockers.extend(f"btc_operator_root_cause_view_source_stale:{item}" for item in source_freshness.get("stale_source_ids", []))
    return _dedupe(blockers)


def _source_freshness(sources: Mapping[str, SourceArtifact], generated: datetime) -> dict[str, Any]:
    rows = []
    stale = []
    for source_id, source in sources.items():
        source_time = _parse_time(source.generated_at_utc)
        age_hours = None
        if source_time is not None:
            age_hours = max(0.0, (generated - source_time).total_seconds() / 3600.0)
        if source.exists and source_time is None:
            stale.append(f"{source_id}:generated_at_missing")
        rows.append(
            {
                "source_id": source_id,
                "path": _portable_path(source.path),
                "exists": source.exists,
                "status": source.status,
                "generated_at_utc": source.generated_at_utc,
                "age_hours": None if age_hours is None else round(age_hours, 6),
                "payload_hash": stable_payload_hash(source.payload),
            }
        )
    return {"status": "stale_or_missing" if stale else "freshness_recorded", "stale_source_ids": stale, "sources": rows}


def _current_stage(*, status: str, next_action: Mapping[str, Any], root_cause_summary: Mapping[str, Any]) -> str:
    if status != "complete_research_only":
        return f"blocked:{next_action.get('category')}"
    dominant = str(root_cause_summary.get("dominant_root_cause_id") or "")
    return "root_cause_clear_read_only" if not dominant else f"monitoring:{dominant}"


def _source_blocked(sources: Mapping[str, SourceArtifact]) -> bool:
    for source in sources.values():
        if str(source.status).startswith(("blocked", "incomplete", "safety_violation", "missing_or_invalid")):
            return True
    return False


def _forbidden_actions() -> list[str]:
    return [
        "禁止写 paper 队列",
        "禁止解锁 live",
        "禁止连接 broker/private/order endpoint",
        "禁止把 review-only approval 当作 paper 授权",
        "禁止把 fixture/drill 当作当前 gate evidence",
        "禁止展示几百条 raw blocker 作为默认操作员视图",
    ]


def _forbidden_reasons(
    *,
    promotion: Mapping[str, Any],
    manual_state: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> list[str]:
    reasons = []
    if manual_state.get("status") != "recorded_current_review_only":
        reasons.append("manual review-only approval is missing, stale, or hash-mismatched")
    if _nested_bool(runtime, "summary", "paper_runtime_gate_evidence") is not True:
        reasons.append("current observe-only non-flat gate evidence is still pending")
    if promotion.get("blockers"):
        reasons.append("promotion gate control still has blockers")
    return reasons or ["read-only operator view never authorizes paper/live"]


def _warnings(*, manual_state: Mapping[str, Any]) -> list[str]:
    warnings = ["btc_operator_root_cause_view_read_only_no_paper_no_live"]
    if manual_state.get("status") == "recorded_current_review_only":
        warnings.append("manual_review_recorded_does_not_authorize_paper_or_live")
    return warnings


def _task_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root_cause_id": row.get("root_cause_id", ""),
        "label_cn": row.get("label_cn", ""),
        "owner": row.get("owner", ""),
        "source_reports": _list_of_strings(row.get("source_reports")),
        "next_command": row.get("next_command", ""),
        "raw_blocker_count": _int(row.get("raw_blocker_count")),
        "affected_gates": _list_of_strings(row.get("affected_gates")),
        "acceptance_criteria": _list_of_strings(row.get("acceptance_criteria")),
    }


def _root_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root_cause_id": row.get("root_cause_id", ""),
        "label_cn": row.get("label_cn", ""),
        "owner": row.get("owner", ""),
        "raw_blocker_count": _int(row.get("raw_blocker_count")),
        "affected_gates": _list_of_strings(row.get("affected_gates")),
        "next_command": row.get("next_command", ""),
    }


def _safety_bits() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_operator_root_cause_view_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        **_safety_bits(),
        "blockers": list(report.get("blockers", [])),
    }


def _load_source(root: Path, source_id: str, path: Path) -> SourceArtifact:
    resolved = _resolve(root, path)
    if not resolved.exists():
        return SourceArtifact(source_id=source_id, path=path, payload={}, exists=False)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return SourceArtifact(source_id=source_id, path=path, payload={}, exists=True, error=str(exc))
    return SourceArtifact(source_id=source_id, path=path, payload=payload if isinstance(payload, Mapping) else {}, exists=True)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        current = _mapping(current).get(key)
    return current


def _nested_bool(payload: Mapping[str, Any], *keys: str) -> bool | None:
    value = _nested(payload, *keys)
    return value if isinstance(value, bool) else None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _portable_path(path: Path) -> str:
    return path.as_posix()
