#!/usr/bin/env python3
"""Service layer for the US equity broker credentials review report.

This module assembles metadata-only review evidence into a fail-closed report.
The CLI entrypoint must only parse arguments and call this service; it must not
contain credential validation or artifact-writing rules.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_us.live.broker_credentials_review import (
    evaluate_broker_credentials_review,
    normalize_gitignore_patterns,
    relpath as review_relpath,
)


SCHEMA_VERSION = "us_equity_broker_credentials_review_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Broker Credentials 审阅.md")
DEFAULT_REVIEW_INPUT = Path("configs/execution/us_equity_broker_credentials_review.local.json")
DEFAULT_TEMPLATE = Path("configs/execution/us_equity_broker_credentials_review.template.json")


def build_us_equity_broker_credentials_review_report(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    review_input: Path = DEFAULT_REVIEW_INPUT,
    template: Path = DEFAULT_TEMPLATE,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    input_path = _resolve(root, review_input)
    template_path = _resolve(root, template)
    review = _read_json(input_path)
    template_payload = _read_json(template_path)
    evaluation = evaluate_broker_credentials_review(
        review=review,
        input_path=input_path,
        input_exists=input_path.exists(),
        template=template_payload,
        template_path=template_path,
        template_exists=template_path.exists(),
        gitignore_patterns=_gitignore_patterns(root),
        repo_root=root,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": evaluation.status,
        "broker_credentials_proven": evaluation.broker_credentials_proven,
        "allowed_statuses": ["broker_credentials_review_blocked", "broker_credentials_review_proven"],
        "credential_review": evaluation.credential_review,
        "review_input": {
            "path": _relpath(input_path, root),
            "exists": input_path.exists(),
            "template_path": _relpath(template_path, root),
            "template_exists": template_path.exists(),
        },
        "local_review_write_policy": evaluation.local_review_write_policy,
        "template_safety": evaluation.template_safety,
        "review_metadata": evaluation.review_metadata,
        "review_summary": evaluation.review_summary,
        "secret_scan": evaluation.secret_scan,
        "operator_checklist": evaluation.operator_checklist,
        "operator_review_guidance": evaluation.operator_review_guidance,
        "evidence_classification": evaluation.evidence_classification,
        "blockers": evaluation.blockers,
        "paper_order_allowed": False,
        "live_order_allowed": False,
        "guardrails": {
            "review_only": True,
            "no_secret_values_allowed": True,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "broker_calls_used": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _gitignore_patterns(root: Path) -> list[str]:
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        return []
    return normalize_gitignore_patterns(gitignore_path.read_text(encoding="utf-8"))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"schema_version": "unreadable", "read_error": type(exc).__name__}


def _markdown(payload: Mapping[str, Any]) -> str:
    blockers = _list(payload.get("blockers"))
    summary = _mapping(payload.get("review_summary"))
    metadata = _mapping(payload.get("review_metadata"))
    credential_review = _mapping(payload.get("credential_review"))
    template = _mapping(payload.get("template_safety"))
    policy = _mapping(payload.get("local_review_write_policy"))
    guidance = _mapping(payload.get("operator_review_guidance"))
    lines = [
        "# US Equity Broker Credentials 审阅",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- broker_credentials_proven: `{payload.get('broker_credentials_proven')}`",
        f"- broker_name: `{credential_review.get('broker_name', '')}`",
        f"- reviewed_at: `{credential_review.get('reviewed_at', '')}`",
        f"- metadata_only: `{credential_review.get('metadata_only')}`",
        f"- funding_source_external_confirmation: `{credential_review.get('funding_source_external_confirmation')}`",
        f"- reviewer_recorded: `{summary.get('reviewer_recorded')}`",
        f"- template_safe_defaults_present: `{template.get('safe_defaults_present')}`",
        f"- local_review_gitignore_present: `{policy.get('local_review_gitignore_present')}`",
        f"- missing_required_fields: `{', '.join(str(item) for item in _list(guidance.get('missing_required_fields')))}`",
        f"- account_id_hash_format: `{summary.get('account_id_hash_format')}`",
        f"- raw_account_id_pattern_detected: `{summary.get('raw_account_id_pattern_detected')}`",
        f"- read_only_or_live_disabled: `{summary.get('read_only_or_live_disabled')}`",
        f"- order_permission_enabled: `{summary.get('order_permission_enabled')}`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Operator Next Actions", ""])
    lines.extend([f"- {item}" for item in _list(guidance.get("operator_next_actions"))])
    lines.extend(["", "## Guardrails", "", "- no secret values allowed", "- live_order_allowed=false", "- order_endpoint_allowed=false"])
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
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
    return review_relpath(path, root)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
