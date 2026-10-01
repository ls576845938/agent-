#!/usr/bin/env python3
"""Build a one-page operator handoff for US equity broker credential review."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_broker_credentials_operator_handoff_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Broker Credentials 操作交接.md")
DEFAULT_REVIEW_REPORT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json")
DEFAULT_TEMPLATE = Path("configs/execution/us_equity_broker_credentials_review.template.json")
DEFAULT_LOCAL_REVIEW = Path("configs/execution/us_equity_broker_credentials_review.local.json")
DEFAULT_IBKR_PROBE_REPORT = Path("artifacts/us_equity_data_status/latest/ibkr_historical_bars_probe_report.json")
DEFAULT_IBKR_COVERAGE_REPORT = Path("artifacts/us_equity_data_status/latest/ibkr_minute_coverage_report.json")


def build_us_equity_broker_credentials_operator_handoff(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    review_report: Path = DEFAULT_REVIEW_REPORT,
    template: Path = DEFAULT_TEMPLATE,
    local_review: Path = DEFAULT_LOCAL_REVIEW,
    ibkr_probe_report: Path = DEFAULT_IBKR_PROBE_REPORT,
    ibkr_coverage_report: Path = DEFAULT_IBKR_COVERAGE_REPORT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    review_path = _resolve(root, review_report)
    template_path = _resolve(root, template)
    local_path = _resolve(root, local_review)
    probe_path = _resolve(root, ibkr_probe_report)
    coverage_path = _resolve(root, ibkr_coverage_report)
    review = _read_json(review_path)
    probe = _read_json(probe_path)
    coverage = _read_json(coverage_path)
    blockers = _blockers(review, review_path, template_path, local_path)
    status = "broker_credentials_handoff_blocked" if blockers else "broker_credentials_handoff_ready_for_manual_review"
    readiness = _manual_review_readiness(
        review=review,
        review_path=review_path,
        template_path=template_path,
        local_path=local_path,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": status,
        "allowed_statuses": [
            "broker_credentials_handoff_blocked",
            "broker_credentials_handoff_ready_for_manual_review",
        ],
        "review_report": {
            "path": _relpath(review_path, root),
            "exists": review_path.exists(),
            "status": str(review.get("status", "")),
        },
        "operator_files": {
            "template": _relpath(template_path, root),
            "template_exists": template_path.exists(),
            "local_review": _relpath(local_path, root),
            "local_review_exists": local_path.exists(),
            "local_review_should_not_be_committed": True,
        },
        "manual_review_readiness": readiness,
        "broker_connectivity_evidence": _broker_connectivity_evidence(
            root=root,
            probe=probe,
            probe_path=probe_path,
            coverage=coverage,
            coverage_path=coverage_path,
        ),
        "operator_checklist": _operator_checklist(),
        "operator_next_actions": _operator_next_actions(_relpath(local_path, root)),
        "acceptance_evidence": [
            "us_equity_broker_credentials_review_report.status == broker_credentials_review_proven",
            "review_summary.read_only_or_live_disabled == true",
            "review_summary.order_permission_enabled == false",
            "review_summary.api_key_present_in_repo == false",
            "guardrails.broker_calls_used == false",
            "guardrails.order_endpoint_allowed == false",
        ],
        "blockers": blockers,
        "guardrails": {
            "operator_handoff_only": True,
            "contains_secret_values": False,
            "secret_values_must_not_be_written": True,
            "local_review_should_not_be_committed": True,
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


def _blockers(review: Mapping[str, Any], review_path: Path, template_path: Path, local_path: Path) -> list[str]:
    blockers: list[str] = []
    if not template_path.exists():
        blockers.append("broker_credentials_template_missing")
    if not review_path.exists():
        blockers.append("broker_credentials_review_report_missing")
    if not local_path.exists():
        blockers.append("broker_credentials_local_review_missing")
    if review.get("status") != "broker_credentials_review_proven":
        blockers.extend(_list_of_str(review.get("blockers")) or ["broker_credentials_review_not_proven"])
    return _dedupe(blockers)


def _manual_review_readiness(
    *,
    review: Mapping[str, Any],
    review_path: Path,
    template_path: Path,
    local_path: Path,
) -> dict[str, Any]:
    review_summary = _mapping(review.get("review_summary"))
    template_safety = _mapping(review.get("template_safety"))
    write_policy = _mapping(review.get("local_review_write_policy"))
    required_fields = {
        "reviewer": review_summary.get("reviewer_recorded") is True,
        "reviewed_at": review_summary.get("reviewed_at_recorded") is True,
        "broker_name": review_summary.get("broker_name_recorded") is True,
        "account_id_hash": review_summary.get("account_id_hash_recorded") is True,
        "manual_approval_ticket": review_summary.get("manual_approval_ticket_recorded") is True,
    }
    safe_boolean_fields = {
        "api_key_present_in_repo_false": review_summary.get("api_key_present_in_repo") is False,
        "secret_values_logged_false": review_summary.get("secret_values_logged") is False,
        "read_only_or_live_disabled_true": review_summary.get("read_only_or_live_disabled") is True,
        "order_permission_enabled_false": review_summary.get("order_permission_enabled") is False,
        "private_endpoint_test_used_false": review_summary.get("private_endpoint_test_used") is False,
        "order_endpoint_test_used_false": review_summary.get("order_endpoint_test_used") is False,
        "funding_source_recorded_outside_repo_true": review_summary.get("funding_source_recorded_outside_repo") is True,
    }
    missing_manual_fields = [field for field, passed in required_fields.items() if not passed]
    unsafe_boolean_fields = [field for field, passed in safe_boolean_fields.items() if not passed]
    local_gitignored = write_policy.get("local_review_gitignore_present") is True
    template_safe = template_safety.get("safe_defaults_present") is True
    review_proven = str(review.get("status", "")) == "broker_credentials_review_proven"
    return {
        "review_report_exists": review_path.exists(),
        "review_report_status": str(review.get("status", "")),
        "template_exists": template_path.exists(),
        "template_safe_defaults_present": template_safe,
        "local_review_exists": local_path.exists(),
        "local_review_gitignored": local_gitignored,
        "missing_manual_fields": missing_manual_fields,
        "unsafe_boolean_fields": unsafe_boolean_fields,
        "ready_for_manual_review": bool(template_path.exists() and local_gitignored and template_safe),
        "review_proven": review_proven,
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }


def _operator_checklist() -> list[dict[str, Any]]:
    return [
        {
            "step_id": "copy_template_to_local",
            "label": "Copy the template to the local review path.",
            "expected_evidence": "configs/execution/us_equity_broker_credentials_review.local.json exists locally",
            "unlocks": "broker review script can evaluate manual evidence",
        },
        {
            "step_id": "record_reviewer_and_hash",
            "label": "Record reviewer, review time, broker name, and hashed account id only.",
            "expected_evidence": "reviewer/reviewed_at/broker_name/account_id_hash are non-empty",
            "unlocks": "manual accountability without storing account number",
        },
        {
            "step_id": "confirm_no_repo_secrets",
            "label": "Confirm no API key, secret, account number, or funding detail is stored in repo.",
            "expected_evidence": "api_key_present_in_repo=false and secret_values_logged=false",
            "unlocks": "secret hygiene gate",
        },
        {
            "step_id": "confirm_no_order_permission",
            "label": "Confirm credentials are read-only or live-disabled and order permission is off.",
            "expected_evidence": "read_only_or_live_disabled=true and order_permission_enabled=false",
            "unlocks": "execution readiness broker credential drill",
        },
        {
            "step_id": "rerun_reports",
            "label": "Rerun broker review, daily production line, and live readiness reports.",
            "expected_evidence": "execution readiness updates from 4/5 to 5/5 only if all manual fields pass",
            "unlocks": "manual review evidence only; not live trading",
        },
    ]


def _operator_next_actions(local_path: str) -> list[str]:
    return [
        "Run: python scripts/init_us_equity_broker_credentials_local_review.py",
        f"Fill {local_path} manually without API keys, account numbers, or secrets.",
        "Set read_only_or_live_disabled=true and order_permission_enabled=false before any paper/live discussion.",
        "Run: python scripts/build_us_equity_broker_credentials_review_report.py",
        "Run: python scripts/run_us_equity_daily_production_line.py",
        "Do not commit the local review file if it contains broker/account operational details.",
    ]


def _broker_connectivity_evidence(
    *,
    root: Path,
    probe: Mapping[str, Any],
    probe_path: Path,
    coverage: Mapping[str, Any],
    coverage_path: Path,
) -> dict[str, Any]:
    probe_guardrails = _mapping(probe.get("guardrails"))
    coverage_guardrails = _mapping(coverage.get("guardrails"))
    probe_readonly = probe.get("readonly_connection_requested") is True
    probe_pass = str(probe.get("status", "")) == "pass"
    connection_proven = bool(probe_path.exists() and probe_pass and probe_readonly)
    return {
        "evidence_role": "read_only_ibkr_market_data_connectivity_only",
        "probe_report": {
            "path": _relpath(probe_path, root),
            "exists": probe_path.exists(),
            "status": str(probe.get("status", "")),
            "host": str(probe.get("host", "")),
            "port": probe.get("port"),
            "client_id": probe.get("client_id"),
            "readonly_connection_requested": probe_readonly,
            "symbols": _list_of_str(probe.get("symbols")),
            "summary": _mapping(probe.get("summary")),
            "blockers": _list_of_str(probe.get("blockers")),
        },
        "coverage_report": {
            "path": _relpath(coverage_path, root),
            "exists": coverage_path.exists(),
            "status": str(coverage.get("status", "")),
            "research_ready_status": str(coverage.get("research_ready_status", "")),
            "summary": _mapping(coverage.get("summary")),
            "blockers": _list_of_str(coverage.get("blockers")),
        },
        "operator_interpretation": {
            "connection_proven": connection_proven,
            "market_data_probe_passed": probe_pass,
            "minute_coverage_complete": str(coverage.get("status", "")) == "pass",
            "minute_data_research_ready": str(coverage.get("research_ready_status", "")) == "pass",
            "can_satisfy_credential_review": False,
            "can_unlock_paper_or_live": False,
            "manual_review_still_required": True,
            "note": "IBKR socket/probe evidence can support operator context only; metadata-only credential review still requires manual fields and account hash.",
        },
        "guardrails": {
            "market_data_probe_only": True,
            "private_account_endpoint_used": bool(probe_guardrails.get("private_account_endpoint_used", False)),
            "order_endpoint_used": bool(probe_guardrails.get("order_endpoint_used", False)),
            "broker_order_endpoint_used": bool(probe_guardrails.get("broker_order_endpoint_used", False)),
            "real_order_submitted": bool(probe_guardrails.get("real_order_submitted", False)),
            "coverage_network_called": bool(coverage_guardrails.get("network_called", False)),
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreadable_report", "blockers": [f"unreadable_report:{type(exc).__name__}"]}


def _markdown(payload: Mapping[str, Any]) -> str:
    readiness = _mapping(payload.get("manual_review_readiness"))
    connectivity = _mapping(payload.get("broker_connectivity_evidence"))
    interpretation = _mapping(connectivity.get("operator_interpretation"))
    probe_report = _mapping(connectivity.get("probe_report"))
    coverage_report = _mapping(connectivity.get("coverage_report"))
    lines = [
        "# US Equity Broker Credentials 操作交接",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- local review: `{_nested(payload, 'operator_files.local_review')}`",
        f"- ready_for_manual_review: `{readiness.get('ready_for_manual_review')}`",
        f"- review_proven: `{readiness.get('review_proven')}`",
        f"- ibkr_probe_status: `{probe_report.get('status', '')}`",
        f"- ibkr_probe_port: `{probe_report.get('port', '')}`",
        f"- ibkr_connection_proven: `{interpretation.get('connection_proven')}`",
        f"- ibkr_coverage_status: `{coverage_report.get('status', '')}`",
        f"- ibkr_coverage_research_ready: `{coverage_report.get('research_ready_status', '')}`",
        f"- missing_manual_fields: `{', '.join(_list_of_str(readiness.get('missing_manual_fields')) or [])}`",
        f"- unsafe_boolean_fields: `{', '.join(_list_of_str(readiness.get('unsafe_boolean_fields')) or [])}`",
        "",
        "## Operator Checklist",
        "",
    ]
    for item in _list(payload.get("operator_checklist")):
        if isinstance(item, Mapping):
            lines.append(f"- `{item.get('step_id')}`：{item.get('label')} evidence=`{item.get('expected_evidence')}`")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {item}" for item in _list_of_str(payload.get("operator_next_actions")))
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", "", "- no secret values", "- live_order_allowed=false", "- order_endpoint_allowed=false"])
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
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_us_equity_broker_credentials_operator_handoff(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(payload["status"])


if __name__ == "__main__":
    main()
