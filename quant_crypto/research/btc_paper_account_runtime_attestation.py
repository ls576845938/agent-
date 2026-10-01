from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "btc_paper_account_runtime_attestation_report_v1"
INPUT_SCHEMA_VERSION = "btc_paper_account_runtime_attestation_input_v1"
DEFAULT_INPUT_PATH = Path("configs/btc/paper_runtime/account_runtime_attestation.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_account_runtime_attestation_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_account_runtime_attestation_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_account_runtime_attestation_safety_status.json"
REQUIRED_VENUE = "OKX"
REQUIRED_INSTRUMENT_ID = "BTC-USDT-SWAP"
SENSITIVE_KEY_TOKENS = (
    "apikey",
    "api_key",
    "secret",
    "passphrase",
    "password",
    "private_key",
    "token",
)


def build_btc_paper_account_runtime_attestation_report(
    *,
    repo_root: Path | None = None,
    input_path: Path = DEFAULT_INPUT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    output = output_dir if output_dir.is_absolute() else root / output_dir
    output.mkdir(parents=True, exist_ok=True)
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    resolved_input = input_path if input_path.is_absolute() else root / input_path
    attestation = _read_json(resolved_input)
    validation = _validate_attestation(attestation, generated_at_utc=generated)
    blockers = validation["blockers"]
    verified = not blockers
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "verified_research_only" if verified else "blocked_fail_closed_research_only",
        "decision": (
            "btc_paper_account_runtime_attestation_verified_manual_review_only_no_auto_paper_no_live"
            if verified
            else "btc_paper_account_runtime_attestation_missing_or_incomplete_fail_closed_no_paper_no_live"
        ),
        "scope": "btc_paper_account_runtime_manual_attestation_no_private_no_order",
        "input": {
            "attestation_path": _portable_path(resolved_input, root),
            "attestation_present": bool(attestation),
        },
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "attestation_summary": _attestation_summary(attestation),
        "validation": validation,
        "account_mode_verified": validation["account_mode_verified"],
        "position_mode_verified": validation["position_mode_verified"],
        "margin_mode_verified": validation["margin_mode_verified"],
        "rate_limit_budget_verified": validation["rate_limit_budget_verified"],
        "credential_permissions_verified": validation["credential_permissions_verified"],
        "credential_permission_checks": validation["credential_permission_checks"],
        "credential_separation_verified": validation["credential_separation_verified"],
        "credential_separation_checks": validation["credential_separation_checks"],
        "manual_approval_recorded": validation["manual_approval_recorded"],
        "manual_approval_checks": validation["manual_approval_checks"],
        "attestation_current": validation["attestation_current"],
        "expiration_checks": validation["expiration_checks"],
        "sensitive_fields_detected": validation["sensitive_fields_detected"],
        "public_or_manual_evidence_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(output / DEFAULT_REPORT_PATH.name, root),
            "summary_cn": _portable_path(output / DEFAULT_SUMMARY_PATH.name, root),
            "paper_live_safety_status": _portable_path(output / DEFAULT_SAFETY_PATH.name, root),
        },
    }
    _write_json(output / DEFAULT_REPORT_PATH.name, report)
    _write_text(output / DEFAULT_SUMMARY_PATH.name, render_summary_cn(report))
    _write_json(output / DEFAULT_SAFETY_PATH.name, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("attestation_summary"))
    lines = [
        "# BTC paper account runtime 人工证明",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- venue：`{summary.get('venue')}`",
        f"- instrument：`{summary.get('instrument_id')}`",
        f"- 账户模式已验证：`{report.get('account_mode_verified')}`",
        f"- 仓位模式已验证：`{report.get('position_mode_verified')}`",
        f"- 保证金模式已验证：`{report.get('margin_mode_verified')}`",
        f"- 限频预算已验证：`{report.get('rate_limit_budget_verified')}`",
        f"- paper 凭证权限已验证：`{report.get('credential_permissions_verified')}`",
        f"- data/paper/live key 分离已验证：`{report.get('credential_separation_verified')}`",
        f"- 人工批准字段已验证：`{report.get('manual_approval_recorded')}`",
        f"- 证明未过期：`{report.get('attestation_current')}`",
        f"- private/order endpoint：private=`{report.get('private_endpoint_used')}`，order=`{report.get('order_endpoint_used')}`",
        "",
        "本报告只接受人工证明文件，不读取交易所私有账户接口，不读取或输出真实 API key，不写 paper 队列，不解锁 live。",
    ]
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(["", "## 阻断项"])
        lines.extend(f"- `{item}`" for item in blockers)
    return "\n".join(lines) + "\n"


def _validate_attestation(attestation: Mapping[str, Any], *, generated_at_utc: datetime) -> dict[str, Any]:
    blockers: list[str] = []
    if not attestation:
        blockers.append("btc_paper_account_runtime_attestation_missing")
    if attestation:
        if attestation.get("schema_version") != INPUT_SCHEMA_VERSION:
            blockers.append("btc_paper_account_runtime_attestation_schema_version_invalid")
        if str(attestation.get("venue") or "").upper() != REQUIRED_VENUE:
            blockers.append("btc_paper_account_runtime_attestation_venue_not_okx")
        if str(attestation.get("instrument_id") or "") != REQUIRED_INSTRUMENT_ID:
            blockers.append("btc_paper_account_runtime_attestation_instrument_not_btc_usdt_swap")
    sensitive_paths = _sensitive_paths(attestation)
    if sensitive_paths:
        blockers.append("btc_paper_account_runtime_attestation_sensitive_fields_present")

    account_mode_verified = _mapping(attestation.get("account_runtime")).get("account_mode_verified") is True
    position_mode_verified = _mapping(attestation.get("account_runtime")).get("position_mode_verified") is True
    margin_mode_verified = _mapping(attestation.get("account_runtime")).get("margin_mode_verified") is True
    rate_limit_budget_verified = _rate_limit_budget_verified(attestation)
    credential_permission_checks = _credential_permission_checks(attestation)
    credential_permissions_verified = all(credential_permission_checks.values())
    credential_separation_checks = _credential_separation_checks(attestation)
    credential_separation_verified = all(credential_separation_checks.values())
    manual_approval_checks = _manual_approval_checks(attestation, generated_at_utc=generated_at_utc)
    manual_approval_recorded = all(manual_approval_checks.values())
    expiration_checks = _expiration_checks(attestation, generated_at_utc=generated_at_utc)
    attestation_current = all(expiration_checks.values())

    if not account_mode_verified:
        blockers.append("btc_paper_account_runtime_account_mode_not_verified")
    if not position_mode_verified:
        blockers.append("btc_paper_account_runtime_position_mode_not_verified")
    if not margin_mode_verified:
        blockers.append("btc_paper_account_runtime_margin_mode_not_verified")
    if not rate_limit_budget_verified:
        blockers.append("btc_paper_account_runtime_rate_limit_budget_not_verified")
    if not credential_permissions_verified:
        blockers.append("btc_paper_account_runtime_credential_permissions_not_verified")
    if not credential_separation_verified:
        blockers.append("btc_paper_account_runtime_credential_separation_not_verified")
    if not manual_approval_recorded:
        blockers.append("btc_paper_account_runtime_manual_approval_not_recorded")
    if not attestation_current:
        blockers.append("btc_paper_account_runtime_attestation_not_current")
    blockers = sorted(set(blockers))
    return {
        "account_mode_verified": account_mode_verified,
        "position_mode_verified": position_mode_verified,
        "margin_mode_verified": margin_mode_verified,
        "rate_limit_budget_verified": rate_limit_budget_verified,
        "credential_permissions_verified": credential_permissions_verified,
        "credential_permission_checks": credential_permission_checks,
        "credential_separation_verified": credential_separation_verified,
        "credential_separation_checks": credential_separation_checks,
        "manual_approval_recorded": manual_approval_recorded,
        "manual_approval_checks": manual_approval_checks,
        "attestation_current": attestation_current,
        "expiration_checks": expiration_checks,
        "sensitive_fields_detected": sensitive_paths,
        "blockers": blockers,
    }


def _rate_limit_budget_verified(attestation: Mapping[str, Any]) -> bool:
    budget = _mapping(attestation.get("rate_limit_budget"))
    if budget.get("verified") is not True:
        return False
    return _float(budget.get("max_orders_per_minute")) > 0 and _float(budget.get("max_requests_per_2s")) > 0


def _credential_permission_checks(attestation: Mapping[str, Any]) -> dict[str, bool]:
    permissions = _mapping(attestation.get("credential_permissions"))
    return {
        "credential_class_is_paper_trade": str(permissions.get("credential_class") or "") == "paper_trade",
        "read_permission_verified": permissions.get("read_permission_verified") is True,
        "trade_permission_verified": permissions.get("trade_permission_verified") is True,
        "withdraw_permission_enabled_false": permissions.get("withdraw_permission_enabled") is False,
        "withdraw_permission_verified_false": permissions.get("withdraw_permission_verified_false") is True,
        "cashout_disabled_verified": permissions.get("cashout_disabled_verified") is True,
        "ip_allowlist_configured_verified": permissions.get("ip_allowlist_configured_verified") is True,
        "live_credential_not_loaded_verified": permissions.get("live_credential_not_loaded_verified") is True,
        "paper_key_redacted_identifier_present": _looks_redacted(permissions.get("paper_key_redacted_identifier")),
    }


def _credential_separation_checks(attestation: Mapping[str, Any]) -> dict[str, bool]:
    separation = _mapping(attestation.get("credential_separation"))
    data_id = str(separation.get("data_readonly_redacted_identifier") or "").strip()
    paper_id = str(separation.get("paper_trade_redacted_identifier") or "").strip()
    live_id = str(separation.get("live_trade_redacted_identifier") or "").strip()
    ids = [value for value in (data_id, paper_id, live_id) if value]
    return {
        "separation_recorded": separation.get("recorded") is True,
        "data_readonly_identifier_redacted": _looks_redacted(data_id),
        "paper_trade_identifier_redacted": _looks_redacted(paper_id),
        "live_trade_identifier_redacted": _looks_redacted(live_id),
        "data_paper_live_identifiers_unique": len(ids) == 3 and len(set(ids)) == 3,
        "data_key_readonly_verified": separation.get("data_key_readonly_verified") is True,
        "paper_key_not_live_verified": separation.get("paper_key_not_live_verified") is True,
        "live_key_not_loaded_in_paper_verified": separation.get("live_key_not_loaded_in_paper_verified") is True,
    }


def _manual_approval_checks(attestation: Mapping[str, Any], *, generated_at_utc: datetime) -> dict[str, bool]:
    approval = _mapping(attestation.get("manual_approval"))
    approved_at = _parse_utc(approval.get("approved_at_utc"))
    return {
        "recorded": approval.get("recorded") is True,
        "approval_id_present": bool(str(approval.get("approval_id") or "").strip()),
        "approved_by_present": bool(str(approval.get("approved_by") or "").strip()),
        "approved_at_utc_valid": approved_at is not None,
        "approved_at_not_future": approved_at is not None and approved_at <= generated_at_utc,
        "approval_scope_valid": str(approval.get("approval_scope") or "") == "paper_account_runtime_attestation_only_no_order",
        "approval_decision_valid": str(approval.get("approval_decision") or "") == "approve_attestation_only_no_paper_no_live",
    }


def _expiration_checks(attestation: Mapping[str, Any], *, generated_at_utc: datetime) -> dict[str, bool]:
    expires = _parse_utc(attestation.get("expires_at_utc"))
    issued = _parse_utc(attestation.get("issued_at_utc"))
    return {
        "issued_at_utc_valid": issued is not None,
        "issued_at_not_future": issued is not None and issued <= generated_at_utc,
        "expires_at_utc_valid": expires is not None,
        "expires_after_generated_at": expires is not None and expires > generated_at_utc,
        "expires_after_issued_at": expires is not None and issued is not None and expires > issued,
    }


def _attestation_summary(attestation: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _mapping(attestation.get("account_runtime"))
    approval = _mapping(attestation.get("manual_approval"))
    budget = _mapping(attestation.get("rate_limit_budget"))
    permissions = _mapping(attestation.get("credential_permissions"))
    separation = _mapping(attestation.get("credential_separation"))
    return {
        "attestation_id": attestation.get("attestation_id"),
        "venue": attestation.get("venue"),
        "instrument_id": attestation.get("instrument_id"),
        "issued_at_utc": attestation.get("issued_at_utc"),
        "expires_at_utc": attestation.get("expires_at_utc"),
        "account_mode": runtime.get("account_mode"),
        "position_mode": runtime.get("position_mode"),
        "margin_mode": runtime.get("margin_mode"),
        "max_leverage_approved": runtime.get("max_leverage_approved"),
        "max_orders_per_minute": budget.get("max_orders_per_minute"),
        "max_requests_per_2s": budget.get("max_requests_per_2s"),
        "credential_class": permissions.get("credential_class"),
        "paper_key_redacted_identifier": permissions.get("paper_key_redacted_identifier"),
        "withdraw_permission_enabled": permissions.get("withdraw_permission_enabled"),
        "withdraw_permission_verified_false": permissions.get("withdraw_permission_verified_false") is True,
        "cashout_disabled_verified": permissions.get("cashout_disabled_verified") is True,
        "ip_allowlist_configured_verified": permissions.get("ip_allowlist_configured_verified") is True,
        "live_credential_not_loaded_verified": permissions.get("live_credential_not_loaded_verified") is True,
        "credential_separation_recorded": separation.get("recorded") is True,
        "data_readonly_redacted_identifier": separation.get("data_readonly_redacted_identifier"),
        "paper_trade_redacted_identifier": separation.get("paper_trade_redacted_identifier"),
        "live_trade_redacted_identifier": separation.get("live_trade_redacted_identifier"),
        "manual_approval_recorded": approval.get("recorded") is True,
        "approval_id": approval.get("approval_id"),
        "approved_at_utc": approval.get("approved_at_utc"),
        "approval_scope": approval.get("approval_scope"),
        "approval_decision": approval.get("approval_decision"),
    }


def _sensitive_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            text = str(key).lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(token in text for token in SENSITIVE_KEY_TOKENS):
                paths.append(path)
            paths.extend(_sensitive_paths(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_sensitive_paths(child, prefix=f"{prefix}[{index}]"))
    return sorted(set(paths))


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "manual_attestation_only": True,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "manual_attestation_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_paper_account_runtime_attestation_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "research_only": True,
        "manual_attestation_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "credential_separation_verified": report.get("credential_separation_verified") is True,
        "manual_approval_recorded": report.get("manual_approval_recorded") is True,
        "attestation_current": report.get("attestation_current") is True,
        "blockers": list(report.get("blockers", [])),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _looks_redacted(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and "****" in text


def _portable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"
