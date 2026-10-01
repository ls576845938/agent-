#!/usr/bin/env python3
"""Service layer for the US equity manual decision-record report.

This module assembles reviewer metadata into a fail-closed artifact. The CLI
entrypoint only parses arguments and calls this service; a valid record still
cannot unlock paper simulation or live trading by itself.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.live.manual_decision_record import (
    evaluate_manual_decision_record,
    gitignore_patterns,
    relpath as decision_relpath,
)


SCHEMA_VERSION = "us_equity_manual_decision_record_report_v1"
DEFAULT_RECORD = Path("configs/reviews/us_equity_manual_decision_record.local.json")
DEFAULT_TEMPLATE = Path("configs/reviews/us_equity_manual_decision_record.template.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 人工决策记录校验.md")


def build_us_equity_manual_decision_record_report(
    *,
    repo_root: Path | None = None,
    record_path: Path = DEFAULT_RECORD,
    template_path: Path = DEFAULT_TEMPLATE,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    record_abs = _resolve(root, record_path)
    template_abs = _resolve(root, template_path)
    record = _read_json(record_abs)
    template = _read_json(template_abs)
    evaluation = evaluate_manual_decision_record(
        record=record,
        record_path=record_abs,
        record_exists=record_abs.exists(),
        template=template,
        template_path=template_abs,
        template_exists=template_abs.exists(),
        gitignore_patterns=gitignore_patterns(root),
        repo_root=root,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": evaluation.status,
        "allowed_statuses": ["manual_decision_record_missing_or_invalid", "manual_decision_record_valid"],
        "decision": evaluation.decision,
        "record_path": _relpath(record_abs, root),
        "template_path": _relpath(template_abs, root),
        "local_record_write_policy": evaluation.local_record_write_policy,
        "record_readiness": evaluation.record_readiness,
        "record_summary": evaluation.record_summary,
        "evidence_path_details": evaluation.evidence_path_details,
        "evidence_classification": evaluation.evidence_classification,
        "operator_decision_guidance": evaluation.operator_decision_guidance,
        "paper_start_dependency": evaluation.paper_start_dependency,
        "blockers": evaluation.blockers,
        "guardrails": {
            "decision_record_validator_only": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "secrets_allowed": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    summary = _mapping(payload.get("record_summary"))
    readiness = _mapping(payload.get("record_readiness"))
    guidance = _mapping(payload.get("operator_decision_guidance"))
    traceable_count = sum(
        1
        for item in _list_of_mapping(payload.get("evidence_path_details"))
        if item.get("traceable_report_artifact") is True
    )
    lines = [
        "# US Equity 人工决策记录校验",
        "",
        f"- generated_at: `{payload.get('generated_at', '')}`",
        f"- status: `{payload.get('status', '')}`",
        f"- decision: `{summary.get('decision', '')}`",
        f"- reviewer_recorded: `{summary.get('reviewer_recorded')}`",
        f"- evidence_path_count: `{summary.get('evidence_path_count')}`",
        f"- traceable_evidence_path_count: `{traceable_count}`",
        f"- record_exists: `{readiness.get('record_exists')}`",
        f"- template_exists: `{readiness.get('template_exists')}`",
        f"- missing_required_fields: `{', '.join(_list_of_str(readiness.get('missing_required_fields')) or [])}`",
        f"- ready_for_manual_review_packet: `{readiness.get('ready_for_manual_review_packet')}`",
        "",
        "本报告只校验人工决策记录，不解锁 paper/live。",
        "",
        "## Blockers",
        "",
    ]
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Operator Next Actions", ""])
    lines.extend([f"- {item}" for item in _list_of_str(guidance.get("operator_next_actions"))] or ["- None"])
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"schema_version": "unreadable", "read_error": type(exc).__name__}
    return dict(payload) if isinstance(payload, Mapping) else {"schema_version": "unreadable"}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    return decision_relpath(path, root)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _list_of_mapping(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
