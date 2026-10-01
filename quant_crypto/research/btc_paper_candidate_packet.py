from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "btc_paper_candidate_packet_v1"
PACKET_SCHEMA_VERSION = "btc_paper_candidate_packet_schema_v1"
REVIEW_HASH_SCHEMA_VERSION = "btc_paper_candidate_packet_review_hash_v1"
REVIEW_HASH_METHOD = "canonical_report_content_excluding_runtime_batch_fields_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_paper_candidate_packet/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_candidate_packet_report.json"
DEFAULT_SUMMARY_CN_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_candidate_packet_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"
DEFAULT_PROMOTION_GATE_PATH = Path(
    "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"
)
DEFAULT_STRATEGY_LEDGER_PATH = Path("artifacts/btc_strategy_ledger/latest/btc_strategy_ledger_report.json")
DEFAULT_MANUAL_REVIEW_APPROVAL_PATH = Path(
    "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
)

REQUIRED_PACKET_FIELDS = (
    "strategy_version",
    "config_version",
    "data_version",
    "venue",
    "instrument",
    "evidence_artifacts",
    "known_weaknesses",
    "rollback_plan",
    "reviewer",
)

PACKET_FIELD_DESCRIPTIONS = {
    "strategy_version": "冻结后的策略 id、参数 hash、代码 commit 和策略报告来源。",
    "config_version": "paper runtime、risk policy、kill switch 和 account attestation 的配置版本。",
    "data_version": "market data、derivatives sentiment、depth/fill mapping 和 freshness batch。",
    "venue": "交易所/市场，不允许从人工表格手写覆盖。",
    "instrument": "品种和合约类型，不允许从人工表格手写覆盖。",
    "evidence_artifacts": "promotion gate 消费过且 freshness 通过的证据 artifact 列表。",
    "known_weaknesses": "root-cause、过拟合、数据等待、runtime 缺口和人工复核风险。",
    "rollback_plan": "paper intake 回滚、kill switch、cancel-only/reduce-only 和停止观察的流程。",
    "reviewer": "人工 reviewer、review 时间、批准结论；当前只能为空或 required。",
}

REVIEW_HASH_VOLATILE_FIELDS = frozenset(
    {
        "reviewed_packet_hash",
        "generated_at_utc",
        "aggregation_batch_id",
        "code_commit",
        "branch",
        "packet_id",
        "source_generated_at_utc",
        "consumer_generated_at_utc",
        "latest_report_generated_at_utc",
        "source_last_modified_utc",
        "last_modified_utc",
        "age_hours",
        "stale_age_hours",
        "source_age_hours",
        "consumer_age_hours",
        "outputs",
        "reviewer",
        "manual_review_approval_path",
        "missing_required_fields",
        "not_ready_gaps",
        "root_cause_summary",
        "root_cause_task_queue",
        "source_code_commit_current_head_match",
        "current_head_code_commit",
        "reviewed_source_code_commit",
    }
)
REVIEW_HASH_SELF_REFERENTIAL_ROOT_CAUSES = frozenset({"manual_review_approval_missing"})
REVIEW_HASH_SELF_REFERENTIAL_TEXT = (
    "manual_review_approval_missing",
    "manual_paper_review_approval",
    "manual_review:manual_approval_missing",
    "manual_review:manual_paper_review_approval",
    "paper readiness approval",
    "legacy_paper_readiness",
    "approved_paper_review",
    "current gate blocked",
)


def build_btc_paper_candidate_packet(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    promotion_gate_path: Path = DEFAULT_PROMOTION_GATE_PATH,
    strategy_ledger_path: Path = DEFAULT_STRATEGY_LEDGER_PATH,
    manual_review_approval_path: Path = DEFAULT_MANUAL_REVIEW_APPROVAL_PATH,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)

    promotion_source = _read_json(root, promotion_gate_path)
    ledger_source = _read_json(root, strategy_ledger_path)
    manual_review_source = _read_json(root, manual_review_approval_path)
    promotion = promotion_source["payload"]
    ledger = ledger_source["payload"]
    manual_review = manual_review_source["payload"]
    current_code_commit = _git(["rev-parse", "--short", "HEAD"], cwd=root)
    batch_id = aggregation_batch_id or str(promotion.get("aggregation_batch_id") or "")
    promotion_ready = _promotion_gate_packet_ready(promotion)
    packet_status = "ready_for_manual_review_packet" if promotion_ready else "not_ready"
    blockers = _packet_blockers(promotion_source=promotion_source, ledger_source=ledger_source, promotion_ready=promotion_ready)
    report_path = output / DEFAULT_REPORT_PATH.name
    summary_path = output / DEFAULT_SUMMARY_CN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name

    evidence_artifacts = _evidence_artifacts(promotion, promotion_gate_path=promotion_gate_path, strategy_ledger_path=strategy_ledger_path)
    packet = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "packet_status": packet_status,
        "packet_id": _packet_id(promotion, generated) if promotion_ready else "",
        "strategy_version": _strategy_version(ledger, promotion_ready=promotion_ready),
        "config_version": _config_version(promotion, promotion_ready=promotion_ready),
        "data_version": _data_version(promotion, promotion_ready=promotion_ready),
        "venue": _field_value("OKX", promotion_ready=promotion_ready, source="promotion_gate_control/data_gate"),
        "instrument": _field_value("BTC-USDT-SWAP", promotion_ready=promotion_ready, source="promotion_gate_control/data_gate"),
        "evidence_artifacts": evidence_artifacts,
        "known_weaknesses": _known_weaknesses(promotion),
        "rollback_plan": _rollback_plan(),
        "reviewer": _reviewer_template(
            manual_review=manual_review,
            promotion_ready=promotion_ready,
            packet_code_commit=current_code_commit,
        ),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": batch_id,
        "code_commit": current_code_commit,
        "current_head_code_commit": current_code_commit,
        "source_code_commit_current_head_match": bool(current_code_commit),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "status": "complete_research_only",
        "decision": (
            "btc_paper_candidate_packet_ready_for_manual_review_no_queue_write_no_live"
            if promotion_ready
            else "btc_paper_candidate_packet_not_ready_no_paper_queue_write_no_live"
        ),
        "scope": "read_only_promotion_gate_derived_packet_template_no_paper_no_live",
        "generation_authority": {
            "authority": "promotion_gate_control_only",
            "promotion_gate_path": _portable_path(promotion_gate_path),
            "strategy_ledger_path": _portable_path(strategy_ledger_path),
            "manual_review_approval_path": _portable_path(manual_review_approval_path),
            "promotion_gate_status": str(promotion.get("status") or ""),
            "promotion_gate_decision": str(promotion.get("decision") or ""),
            "packet_generation_allowed_by_promotion_gate": promotion_ready,
            "manual_packet_write_allowed": False,
            "handwritten_packet_allowed": False,
            "cli_strategy_override_allowed": False,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "required_packet_fields": list(REQUIRED_PACKET_FIELDS),
        "packet_field_descriptions": PACKET_FIELD_DESCRIPTIONS,
        "missing_required_fields": _missing_required_fields(packet),
        "not_ready_gaps": _not_ready_gaps(promotion, blockers),
        "root_cause_task_queue": _mapping(promotion.get("root_cause_task_queue")),
        "promotion_gate_artifact_freshness": _freshness_summary(promotion),
        "paper_candidate_packet": packet,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(summary_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    report["reviewed_packet_hash"] = _reviewed_packet_hash(report)
    _write_json(report_path, report)
    _write_text(summary_path, render_btc_paper_candidate_packet_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_paper_candidate_packet_markdown(report: Mapping[str, Any]) -> str:
    packet = _mapping(report.get("paper_candidate_packet"))
    authority = _mapping(report.get("generation_authority"))
    lines = [
        "# BTC Paper Candidate Packet 模板",
        "",
        f"- 状态：`{report.get('decision')}`",
        f"- packet 状态：`{packet.get('packet_status')}`",
        f"- 生成权威来源：`{authority.get('authority')}`",
        f"- promotion gate：`{authority.get('promotion_gate_status')}`",
        "- 边界：只读模板，不写 paper 队列，不解锁 live，不连接 broker/OMS/order。",
        "",
        "## 固定字段",
        "",
        "| 字段 | 当前值 | 来源 | 说明 |",
        "|---|---|---|---|",
    ]
    descriptions = _mapping(report.get("packet_field_descriptions"))
    for field in _list_of_strings(report.get("required_packet_fields")):
        value = packet.get(field)
        if isinstance(value, Mapping):
            cell = value.get("value") if value.get("value") not in (None, "") else value.get("status")
            source = value.get("source", "")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            cell = f"{len(value)} items"
            source = "promotion_gate_control"
        else:
            cell = value
            source = ""
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(field),
                    _md(cell),
                    _md(source),
                    _md(descriptions.get(field, "")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## 当前缺口", ""])
    gaps = _list_of_mappings(report.get("not_ready_gaps"))
    if not gaps:
        lines.append("- 无，等待人工 review。")
    else:
        for gap in gaps[:20]:
            lines.append(f"- `{gap.get('gap_id')}`：{gap.get('description_cn')}")
        if len(gaps) > 20:
            lines.append(f"- 其余 {len(gaps) - 20} 项见 JSON。")
    lines.extend(["", "## 为什么仍不能 paper", ""])
    reason_lines = _paper_block_reason_lines(report)
    if reason_lines:
        lines.extend(reason_lines)
    else:
        lines.append("- 当前 packet 只允许进入人工 review；paper 队列和 live 仍保持关闭。")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- 写 paper 队列：`{_nested(report, 'gate', 'paper_queue_write_allowed')}`",
            f"- 允许 paper：`{_nested(report, 'gate', 'paper_allowed')}`",
            f"- 解锁 live：`{_nested(report, 'gate', 'live_unlock_allowed')}`",
            f"- broker/order：`{_nested(report, 'gate', 'broker_or_order_allowed')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _paper_block_reason_lines(report: Mapping[str, Any]) -> list[str]:
    queue = _mapping(report.get("root_cause_task_queue"))
    immediate = _list_of_mappings(queue.get("immediate_development_items"))
    waits = _list_of_mappings(queue.get("data_wait_items"))
    rows: list[str] = []
    if immediate or waits:
        rows.append("- 当前不是因为 packet 模板缺字段而卡住，而是 promotion gate 仍有有效根因。")
    for item in immediate:
        rows.append(
            "- 需要处理："
            f"`{item.get('root_cause_id')}`，负责人 `{item.get('owner', '')}`，"
            f"下一步 `{item.get('next_command', '')}`。"
        )
    for item in waits:
        rows.append(
            "- 需要等待/累计："
            f"`{item.get('root_cause_id')}`，负责人 `{item.get('owner', '')}`，"
            f"下一步 `{item.get('next_command', '')}`。"
        )
    if _list_of_strings(report.get("missing_required_fields")):
        rows.append("- 当前缺失字段：" + "、".join(f"`{item}`" for item in _list_of_strings(report.get("missing_required_fields"))) + "。")
    rows.append("- 即使人工 review 后续补齐，也只能解除人工复核缺口，不能自动写 paper 队列或解锁 live。")
    return rows


def _promotion_gate_packet_ready(promotion: Mapping[str, Any]) -> bool:
    if promotion.get("status") != "complete_research_only_manual_review_required":
        return False
    if _list_of_strings(promotion.get("blockers")):
        return False
    if _list_of_strings(promotion.get("safety_violations")):
        return False
    if _nested(promotion, "gate", "paper_queue_write_allowed") is True:
        return False
    if _nested(promotion, "gate", "live_unlock_allowed") is True:
        return False
    return True


def _packet_blockers(
    *,
    promotion_source: Mapping[str, Any],
    ledger_source: Mapping[str, Any],
    promotion_ready: bool,
) -> list[str]:
    blockers: list[str] = []
    if not promotion_source["exists"]:
        blockers.append("btc_paper_candidate_packet_missing_promotion_gate_report")
    if not ledger_source["exists"]:
        blockers.append("btc_paper_candidate_packet_missing_strategy_ledger_report")
    promotion = _mapping(promotion_source.get("payload"))
    if not promotion_ready:
        blockers.append("btc_paper_candidate_packet_promotion_gate_not_complete")
    freshness = _mapping(promotion.get("artifact_freshness"))
    if freshness.get("status") not in ("", "pass"):
        blockers.append(f"btc_paper_candidate_packet_artifact_freshness:{freshness.get('status')}")
    for item in _list_of_strings(freshness.get("blockers"))[:20]:
        blockers.append(f"btc_paper_candidate_packet_freshness:{item}")
    for root in _list_of_mappings(_nested(promotion, "root_cause_dag", "root_cause_matrix"))[:12]:
        blockers.append(f"btc_paper_candidate_packet_root_cause:{root.get('root_cause_id')}")
    if _nested(promotion, "generation_authority", "handwritten_packet_allowed") is True:
        blockers.append("btc_paper_candidate_packet_handwritten_packet_allowed_true")
    return sorted(set(blockers))


def _strategy_version(ledger: Mapping[str, Any], *, promotion_ready: bool) -> dict[str, Any]:
    primary = _primary_strategy_line(ledger)
    return {
        "required": True,
        "status": "ready_for_packet_review" if promotion_ready and primary else ("derived_from_strategy_ledger_blocked" if primary else "missing_source"),
        "value": primary.get("strategy_id", "") if primary else "",
        "source": "btc_strategy_ledger",
        "display_name_cn": primary.get("display_name_cn", "") if primary else "",
        "parameter_summary": primary.get("parameter_summary", "") if primary else "",
        "latest_report_path": primary.get("latest_report_path", "") if primary else "",
        "code_commit": ledger.get("code_commit", ""),
    }


def _config_version(promotion: Mapping[str, Any], *, promotion_ready: bool) -> dict[str, Any]:
    source_paths = _mapping(promotion.get("source_paths"))
    batch_id = str(promotion.get("aggregation_batch_id") or "")
    return {
        "required": True,
        "status": "ready_for_packet_review" if promotion_ready else ("derived_from_promotion_gate_blocked" if batch_id else "missing_source"),
        "value": "btc_paper_runtime_config_from_promotion_gate" if batch_id else "",
        "aggregation_batch_id": batch_id,
        "source": "btc_promotion_gate_control",
        "components": {
            "paper_exchange_rule": source_paths.get("paper_exchange_rule", ""),
            "kill_switch": source_paths.get("kill_switch", ""),
            "account_attestation": source_paths.get("account_attestation", ""),
            "api_key_audit": source_paths.get("api_key_audit", ""),
        },
    }


def _data_version(promotion: Mapping[str, Any], *, promotion_ready: bool) -> dict[str, Any]:
    freshness = _mapping(promotion.get("artifact_freshness"))
    batch_id = str(promotion.get("aggregation_batch_id") or "")
    freshness_passed = freshness.get("status") == "pass"
    return {
        "required": True,
        "status": (
            "ready_for_packet_review"
            if promotion_ready and freshness_passed
            else ("derived_from_freshness_blocked" if batch_id and freshness_passed else "freshness_not_ready")
        ),
        "value": "btc_market_data_freshness_passed_current_sources" if freshness_passed else "",
        "aggregation_batch_id": batch_id if freshness_passed else "",
        "source": "btc_promotion_gate_control.artifact_freshness",
        "freshness_status": freshness.get("status", ""),
        "source_count": freshness.get("source_count", 0),
        "stale_source_count": freshness.get("stale_source_count", 0),
        "required_rebuild_reports": freshness.get("required_rebuild_reports", []),
    }


def _field_value(value: str, *, promotion_ready: bool, source: str) -> dict[str, Any]:
    return {
        "required": True,
        "status": "ready_for_packet_review" if promotion_ready else "derived_from_system_source_blocked",
        "value": value,
        "source": source,
    }


def _evidence_artifacts(
    promotion: Mapping[str, Any],
    *,
    promotion_gate_path: Path,
    strategy_ledger_path: Path,
) -> list[dict[str, Any]]:
    rows = [
        {
            "artifact_id": "promotion_gate_control",
            "path": _portable_path(promotion_gate_path),
            "required": True,
            "freshness_status": _nested(promotion, "artifact_freshness", "status") or "",
        },
        {
            "artifact_id": "strategy_ledger",
            "path": _portable_path(strategy_ledger_path),
            "required": True,
            "freshness_status": "source_of_packet",
        },
    ]
    freshness_rows = {
        str(row.get("source_id")): row
        for row in _list_of_mappings(_nested(promotion, "artifact_freshness", "sources"))
        if row.get("source_id")
    }
    for source_id, path in sorted(_mapping(promotion.get("source_paths")).items()):
        freshness = _mapping(freshness_rows.get(source_id))
        rows.append(
            {
                "artifact_id": source_id,
                "path": str(path),
                "required": True,
                "freshness_status": freshness.get("status", ""),
                "source_generated_at_utc": freshness.get("source_generated_at_utc", ""),
                "rebuild_command": freshness.get("rebuild_command", ""),
            }
        )
    return rows


def _known_weaknesses(promotion: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _list_of_strings(promotion.get("key_blockers_cn")):
        rows.append({"kind": "key_blocker", "description_cn": item})
    for root in _list_of_mappings(_nested(promotion, "root_cause_dag", "root_cause_matrix")):
        rows.append(
            {
                "kind": "root_cause",
                "root_cause_id": root.get("root_cause_id", ""),
                "label_cn": root.get("label_cn", ""),
                "owner": root.get("owner", ""),
                "next_command": root.get("next_command", ""),
                "acceptance_criteria": root.get("acceptance_criteria", []),
                "raw_blocker_count": root.get("raw_blocker_count", root.get("blocker_count", 0)),
            }
        )
    if not rows:
        rows.append(
            {
                "kind": "manual_review_required",
                "description_cn": "promotion gate 当前未暴露新增 root-cause blocker，但 packet 仍必须经人工 paper review；live 继续冻结。",
            }
        )
    return rows


def _rollback_plan() -> dict[str, Any]:
    return {
        "required": True,
        "status": "template_only",
        "source": "fixed_btc_paper_runtime_runbook",
        "steps": [
            "keep paper_order_intake_allowed=false until manual review approves",
            "if paper intake is ever enabled, kill switch must support immediate paper intake disable",
            "cancel-only and reduce-only states must be independently verified before any paper session",
            "on reconciliation mismatch, stop new intake, preserve ledgers, rebuild replay/reconciliation reports",
            "live remains frozen regardless of paper packet status",
        ],
    }


def _reviewer_template(
    *,
    manual_review: Mapping[str, Any],
    promotion_ready: bool,
    packet_code_commit: str = "",
) -> dict[str, Any]:
    record = _mapping(manual_review.get("approval_record"))
    review_blockers = _list_of_strings(manual_review.get("blockers"))
    recorded = manual_review.get("manual_approval_recorded") is True and not review_blockers
    reviewed_packet = _mapping(manual_review.get("reviewed_packet"))
    reviewer_id = str(record.get("reviewer", "") or "")
    reviewed_at = str(record.get("decision_date_utc", "") or "")
    decision = str(record.get("decision", "") or "")
    record_code_commit = str(record.get("reviewed_source_code_commit") or "")
    report_packet_code_commit = str(reviewed_packet.get("code_commit") or "")
    stale_code_version = (
        "btc_manual_paper_review_approval_review_only_stale_code_version" in review_blockers
        or (bool(packet_code_commit) and bool(record_code_commit) and record_code_commit != packet_code_commit)
        or (bool(packet_code_commit) and bool(report_packet_code_commit) and report_packet_code_commit != packet_code_commit)
    )
    reviewed_packet_sha256 = str(
        _nested(record, "reviewed_packet_hash", "sha256")
        or record.get("reviewed_packet_sha256")
        or ""
    )
    record_present = any([reviewer_id, reviewed_at, decision, reviewed_packet_sha256])
    if stale_code_version:
        status = "review_only_stale_code_version"
    elif recorded:
        status = "recorded_review_only"
    elif record_present:
        status = "manual_review_record_present_but_invalid_or_not_current"
    else:
        status = "required_manual_review" if promotion_ready else "manual_review_pending_until_promotion_ready"
    return {
        "required": True,
        "status": status,
        "reviewer_id": reviewer_id if record_present else "",
        "reviewed_at_utc": reviewed_at if record_present else "",
        "decision": decision if record_present else "",
        "approval_scope": str(record.get("approval_scope") or "manual_paper_review_only_no_live"),
        "reviewed_packet_sha256": reviewed_packet_sha256,
        "reviewed_source_code_commit": record_code_commit,
        "current_packet_code_commit": packet_code_commit,
        "manual_review_report_packet_code_commit": report_packet_code_commit,
        "review_only_stale_code_version": stale_code_version,
        "review_blockers": review_blockers,
        "review_record_current_and_hash_valid": recorded and not stale_code_version,
        "manual_approval_required": True,
        "source": "btc_manual_paper_review_approval",
        "manual_review_report_status": str(manual_review.get("status", "")),
    }


def _missing_required_fields(packet: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_PACKET_FIELDS:
        value = packet.get(field)
        if value in (None, "", [], {}):
            missing.append(field)
        elif field == "reviewer" and isinstance(value, Mapping) and not str(value.get("reviewer_id") or "").strip():
            missing.append(field)
        elif field == "reviewer" and isinstance(value, Mapping) and value.get("status") == "review_only_stale_code_version":
            missing.append(field)
        elif isinstance(value, Mapping) and value.get("status") in {"missing_source", "freshness_not_ready"}:
            missing.append(field)
    return missing


def _not_ready_gaps(promotion: Mapping[str, Any], blockers: Sequence[str]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if blockers:
        gaps.append(
            {
                "gap_id": "promotion_gate_not_complete",
                "description_cn": "promotion gate 仍未通过，packet 只能保持 not_ready。",
                "evidence": list(blockers[:20]),
            }
        )
    freshness = _mapping(promotion.get("artifact_freshness"))
    if freshness.get("status") not in ("", "pass"):
        gaps.append(
            {
                "gap_id": "artifact_freshness_not_pass",
                "description_cn": "source artifact freshness 未通过，需要先重建聚合链。",
                "evidence": freshness.get("required_rebuild_reports", []),
            }
        )
    for item in _list_of_mappings(_mapping(promotion.get("root_cause_task_queue")).get("immediate_development_items")):
        gaps.append(
            {
                "gap_id": f"root_cause:{item.get('root_cause_id')}",
                "description_cn": f"{item.get('label_cn') or item.get('root_cause_id')} 仍需处理。",
                "owner": item.get("owner", ""),
                "next_command": item.get("next_command", ""),
                "acceptance_criteria": item.get("acceptance_criteria", []),
            }
        )
    for item in _list_of_mappings(_mapping(promotion.get("root_cause_task_queue")).get("data_wait_items")):
        gaps.append(
            {
                "gap_id": f"data_wait:{item.get('root_cause_id')}",
                "description_cn": f"{item.get('label_cn') or item.get('root_cause_id')} 仍需等待或累计证据。",
                "owner": item.get("owner", ""),
                "next_command": item.get("next_command", ""),
                "acceptance_criteria": item.get("acceptance_criteria", []),
            }
        )
    return gaps


def _freshness_summary(promotion: Mapping[str, Any]) -> dict[str, Any]:
    freshness = _mapping(promotion.get("artifact_freshness"))
    return {
        "status": freshness.get("status", ""),
        "source_count": freshness.get("source_count", 0),
        "stale_source_count": freshness.get("stale_source_count", 0),
        "dependency_newer_than_consumer_count": freshness.get("dependency_newer_than_consumer_count", 0),
        "required_rebuild_reports": freshness.get("required_rebuild_reports", []),
    }


def _primary_strategy_line(ledger: Mapping[str, Any]) -> dict[str, Any]:
    for row in _list_of_mappings(ledger.get("strategy_lines")):
        if row.get("strategy_id") == "stable_long_short":
            return row
    rows = _list_of_mappings(ledger.get("strategy_lines"))
    return rows[0] if rows else {}


def _packet_id(promotion: Mapping[str, Any], generated: datetime) -> str:
    batch = str(promotion.get("aggregation_batch_id") or generated.strftime("%Y%m%dT%H%M%SZ"))
    return f"btc_paper_candidate_packet:{batch}"


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "read_only_report_only": True,
        "generated_from_promotion_gate_only": True,
        "manual_packet_write_allowed": False,
        "handwritten_packet_allowed": False,
        "strategy_override_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_paper_live_safety_status_v1",
        "generated_at_utc": report.get("generated_at_utc"),
        "status": "research_only",
        "source_report": report.get("outputs", {}).get("json"),
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _read_json(root: Path, path: Path) -> dict[str, Any]:
    resolved = _resolve(root, path)
    if not resolved.exists():
        return {"exists": False, "path": _portable_path(path), "payload": {}, "error": "missing"}
    try:
        return {
            "exists": True,
            "path": _portable_path(path),
            "payload": json.loads(resolved.read_text(encoding="utf-8")),
            "error": "",
        }
    except json.JSONDecodeError as exc:
        return {
            "exists": False,
            "path": _portable_path(path),
            "payload": {},
            "error": f"json_decode_error:{exc}",
        }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _portable_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _git(args: Sequence[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _reviewed_packet_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    canonical_payload = _canonical_review_payload(report)
    raw = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": REVIEW_HASH_SCHEMA_VERSION,
        "hash_method": REVIEW_HASH_METHOD,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_payload": "btc_paper_candidate_packet_report_excluding_runtime_batch_fields",
        "volatile_fields_excluded": sorted(REVIEW_HASH_VOLATILE_FIELDS),
    }


def _canonical_review_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        if _is_self_referential_review_mapping(value):
            return None
        rows: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda row: str(row[0])):
            key_text = str(key)
            if _is_review_hash_volatile_key(key_text):
                continue
            canonical_item = _canonical_review_payload(item)
            if canonical_item is None:
                continue
            rows[key_text] = canonical_item
        return rows
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        rows = []
        for item in value:
            canonical_item = _canonical_review_payload(item)
            if canonical_item is not None:
                rows.append(canonical_item)
        return rows
    if isinstance(value, str) and _is_self_referential_review_text(value):
        return None
    return value


def _is_review_hash_volatile_key(key: str) -> bool:
    if key in REVIEW_HASH_VOLATILE_FIELDS:
        return True
    return key.endswith("_generated_at_utc") or key.endswith("_age_hours")


def _is_self_referential_review_mapping(value: Mapping[str, Any]) -> bool:
    root_cause_id = str(value.get("root_cause_id", ""))
    if root_cause_id in REVIEW_HASH_SELF_REFERENTIAL_ROOT_CAUSES:
        return True
    gap_id = str(value.get("gap_id", ""))
    if any(item in gap_id for item in REVIEW_HASH_SELF_REFERENTIAL_ROOT_CAUSES):
        return True
    return any(_is_self_referential_review_text(str(item)) for item in value.values() if isinstance(item, str))


def _is_self_referential_review_text(value: str) -> bool:
    text = value.lower()
    return any(pattern in text for pattern in REVIEW_HASH_SELF_REFERENTIAL_TEXT)
