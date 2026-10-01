"""Broker credential review domain rules for US equity readiness.

The review artifact is intentionally metadata-only. It may record reviewer,
broker name, account hash, approval ticket, and external funding-source
confirmation, but it must never record API keys, account numbers, passwords,
tokens, or raw funding details.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping


REQUIRED_INPUT_SCHEMA = "us_equity_broker_credentials_review_input_v1"
ACCOUNT_ID_HASH_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
RAW_ACCOUNT_ID_PATTERNS = (
    re.compile(r"^U\d{5,}$", re.IGNORECASE),
    re.compile(r"^DU\d{5,}$", re.IGNORECASE),
    re.compile(r"^F\d{5,}$", re.IGNORECASE),
    re.compile(r"^\d{7,12}$"),
)
ALLOWED_SECRET_WORD_FIELDS = {
    "account_id_hash",
    "api_key_present_in_repo",
    "funding_source_recorded_outside_repo",
    "order_endpoint_test_used",
    "private_endpoint_test_used",
    "secret_values_logged",
}
SECRET_LIKE_FIELD_TOKENS = (
    "api_key",
    "access_key",
    "secret",
    "token",
    "passphrase",
    "password",
    "private_key",
    "account_number",
    "funding_source",
)
REQUIRED_TEXT_FIELDS = {
    "reviewer": "broker_credentials_reviewer_missing",
    "reviewed_at": "broker_credentials_reviewed_at_missing",
    "broker_name": "broker_credentials_broker_name_missing",
    "account_id_hash": "broker_credentials_account_id_hash_missing",
    "manual_approval_ticket": "broker_credentials_manual_approval_ticket_missing",
}
REQUIRED_BOOLEAN_FIELDS = {
    "api_key_present_in_repo": False,
    "secret_values_logged": False,
    "read_only_or_live_disabled": True,
    "order_permission_enabled": False,
    "private_endpoint_test_used": False,
    "order_endpoint_test_used": False,
    "funding_source_recorded_outside_repo": True,
}


@dataclass(frozen=True)
class BrokerCredentialReviewEvaluation:
    status: str
    blockers: list[str]
    broker_credentials_proven: bool
    credential_review: dict[str, Any]
    review_metadata: dict[str, Any]
    review_summary: dict[str, Any]
    secret_scan: dict[str, Any]
    template_safety: dict[str, Any]
    local_review_write_policy: dict[str, Any]
    evidence_classification: dict[str, Any]
    operator_checklist: dict[str, Any]
    operator_review_guidance: dict[str, Any]


def evaluate_broker_credentials_review(
    *,
    review: Mapping[str, Any],
    input_path: Path,
    input_exists: bool,
    template: Mapping[str, Any],
    template_path: Path,
    template_exists: bool,
    gitignore_patterns: list[str],
    repo_root: Path,
) -> BrokerCredentialReviewEvaluation:
    template_safety = template_safety_report(template, template_exists)
    local_policy = local_review_write_policy(input_path, repo_root, gitignore_patterns)
    blockers = review_blockers(review, input_exists, template_safety, local_policy)
    status = "broker_credentials_review_proven" if not blockers else "broker_credentials_review_blocked"
    metadata = review_metadata(review, status=status)
    summary = review_summary(review)
    return BrokerCredentialReviewEvaluation(
        status=status,
        blockers=blockers,
        broker_credentials_proven=status == "broker_credentials_review_proven",
        credential_review=credential_review_contract(metadata),
        review_metadata=metadata,
        review_summary=summary,
        secret_scan=secret_scan_report(
            review=review,
            template_safety=template_safety,
            summary=summary,
        ),
        template_safety=template_safety,
        local_review_write_policy=local_policy,
        evidence_classification=evidence_classification(status),
        operator_checklist=operator_checklist(
            review=review,
            input_exists=input_exists,
            template_safety=template_safety,
            local_review_write_policy=local_policy,
        ),
        operator_review_guidance=operator_review_guidance(
            review=review,
            input_exists=input_exists,
            blockers=blockers,
            template_safety=template_safety,
            local_review_write_policy=local_policy,
        ),
    )


def review_blockers(
    review: Mapping[str, Any],
    input_exists: bool,
    template_safety: Mapping[str, Any],
    local_review_write_policy: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if local_review_write_policy.get("local_review_gitignore_present") is not True:
        blockers.append("broker_credentials_local_review_not_gitignored")
    if template_safety.get("template_exists") and not template_safety.get("safe_defaults_present"):
        blockers.append("broker_credentials_template_safe_defaults_missing")
    if template_safety.get("secret_like_fields"):
        blockers.append("broker_credentials_template_contains_secret_like_field")
    if not input_exists:
        blockers.append("broker_credentials_review_input_missing")
        return dedupe(blockers)
    if secret_like_field_paths(review):
        blockers.append("broker_credentials_review_input_contains_secret_like_field")
    if review.get("schema_version") != REQUIRED_INPUT_SCHEMA:
        blockers.append("broker_credentials_review_input_schema_mismatch")
    for key, blocker in REQUIRED_TEXT_FIELDS.items():
        if not str(review.get(key, "")).strip():
            blockers.append(blocker)
    hash_diagnostics = account_id_hash_diagnostics(review.get("account_id_hash"))
    if hash_diagnostics["raw_account_id_pattern_detected"]:
        blockers.append("broker_credentials_account_id_hash_looks_like_raw_account_id")
    if hash_diagnostics["recorded"] and not hash_diagnostics["format_ok"]:
        blockers.append("broker_credentials_account_id_hash_invalid_format")
    for key, expected in REQUIRED_BOOLEAN_FIELDS.items():
        if review.get(key) is not expected:
            blockers.append(f"broker_credentials_{key}_not_{str(expected).lower()}")
    if review.get("credential_storage") != "outside_source_control":
        blockers.append("broker_credentials_storage_not_outside_source_control")
    return dedupe(blockers)


def local_review_write_policy(input_path: Path, root: Path, gitignore_patterns: list[str]) -> dict[str, Any]:
    rel = relpath(input_path, root)
    normalized = rel.replace("\\", "/")
    gitignore_present = normalized in gitignore_patterns or "configs/execution/*.local.json" in gitignore_patterns
    return {
        "local_review_path": normalized,
        "should_not_commit_local_review": True,
        "local_review_gitignore_present": gitignore_present,
        "allowed_template_path": "configs/execution/us_equity_broker_credentials_review.template.json",
        "secret_values_must_not_be_written": True,
        "broker_calls_used": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "real_order_submitted": False,
    }


def template_safety_report(template: Mapping[str, Any], template_exists: bool) -> dict[str, Any]:
    template_schema_ok = template.get("schema_version") == REQUIRED_INPUT_SCHEMA
    read_only_default = template.get("read_only_or_live_disabled")
    order_permission_default = template.get("order_permission_enabled")
    secret_defaults_safe = (
        template.get("api_key_present_in_repo") is False
        and template.get("secret_values_logged") is False
        and template.get("private_endpoint_test_used") is False
        and template.get("order_endpoint_test_used") is False
    )
    safe_defaults_present = (
        template_exists
        and template_schema_ok
        and read_only_default is True
        and order_permission_default is False
        and secret_defaults_safe
    )
    return {
        "template_exists": template_exists,
        "template_schema_ok": template_schema_ok,
        "safe_defaults_present": safe_defaults_present,
        "read_only_or_live_disabled_default": read_only_default,
        "order_permission_enabled_default": order_permission_default,
        "secret_defaults_safe": secret_defaults_safe,
        "secret_like_fields": secret_like_field_paths(template),
    }


def review_summary(review: Mapping[str, Any]) -> dict[str, Any]:
    hash_diagnostics = account_id_hash_diagnostics(review.get("account_id_hash"))
    return {
        "reviewer_recorded": bool(str(review.get("reviewer", "")).strip()),
        "reviewed_at_recorded": bool(str(review.get("reviewed_at", "")).strip()),
        "broker_name_recorded": bool(str(review.get("broker_name", "")).strip()),
        "account_id_hash_recorded": hash_diagnostics["recorded"],
        "account_id_hash_format": hash_diagnostics["format"],
        "account_id_hash_format_ok": hash_diagnostics["format_ok"],
        "raw_account_id_pattern_detected": hash_diagnostics["raw_account_id_pattern_detected"],
        "credential_storage": review.get("credential_storage", ""),
        "api_key_present_in_repo": review.get("api_key_present_in_repo"),
        "secret_values_logged": review.get("secret_values_logged"),
        "read_only_or_live_disabled": review.get("read_only_or_live_disabled"),
        "order_permission_enabled": review.get("order_permission_enabled"),
        "private_endpoint_test_used": review.get("private_endpoint_test_used"),
        "order_endpoint_test_used": review.get("order_endpoint_test_used"),
        "funding_source_recorded_outside_repo": review.get("funding_source_recorded_outside_repo"),
        "manual_approval_ticket_recorded": bool(str(review.get("manual_approval_ticket", "")).strip()),
        "secret_like_field_count": len(secret_like_field_paths(review)),
    }


def review_metadata(review: Mapping[str, Any], *, status: str) -> dict[str, Any]:
    hash_diagnostics = account_id_hash_diagnostics(review.get("account_id_hash"))
    return {
        "metadata_only": True,
        "status": status,
        "reviewer": str(review.get("reviewer", "")).strip(),
        "reviewed_at": str(review.get("reviewed_at", "")).strip(),
        "broker_name": str(review.get("broker_name", "")).strip(),
        "account_id_hash": str(review.get("account_id_hash", "")).strip() if hash_diagnostics["format_ok"] else "",
        "account_id_hash_recorded": hash_diagnostics["format_ok"],
        "manual_approval_ticket": str(review.get("manual_approval_ticket", "")).strip(),
        "funding_source_recorded_outside_repo": review.get("funding_source_recorded_outside_repo") is True,
        "credential_storage": str(review.get("credential_storage", "")).strip(),
        "secret_values_recorded": False,
        "raw_account_id_recorded": False,
        "raw_funding_source_recorded": False,
        "can_unlock_paper_or_live": False,
    }


def credential_review_contract(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metadata_only": True,
        "broker_name": str(metadata.get("broker_name", "")),
        "account_id_hash": str(metadata.get("account_id_hash", "")),
        "account_id_hash_recorded": metadata.get("account_id_hash_recorded") is True,
        "reviewer": str(metadata.get("reviewer", "")),
        "reviewed_at": str(metadata.get("reviewed_at", "")),
        "manual_approval_ticket": str(metadata.get("manual_approval_ticket", "")),
        "funding_source_external_confirmation": metadata.get("funding_source_recorded_outside_repo") is True,
        "credential_storage": str(metadata.get("credential_storage", "")),
        "secret_values_recorded": False,
        "raw_account_id_recorded": False,
        "raw_funding_source_recorded": False,
        "can_unlock_paper_or_live": False,
    }


def secret_scan_report(
    *,
    review: Mapping[str, Any],
    template_safety: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    forbidden_paths = secret_like_field_paths(review)
    template_forbidden_paths = _list_of_str(template_safety.get("secret_like_fields"))
    return {
        "metadata_only_scan": True,
        "forbidden_field_paths": forbidden_paths,
        "template_forbidden_field_paths": template_forbidden_paths,
        "secret_like_field_count": int(summary.get("secret_like_field_count") or 0),
        "template_secret_like_field_count": len(template_forbidden_paths),
        "raw_account_id_pattern_detected": summary.get("raw_account_id_pattern_detected") is True,
        "contains_secret_values": False,
        "secret_values_exposed_in_artifact": False,
        "raw_account_id_exposed_in_artifact": False,
        "raw_funding_source_exposed_in_artifact": False,
    }


def operator_checklist(
    *,
    review: Mapping[str, Any],
    input_exists: bool,
    template_safety: Mapping[str, Any],
    local_review_write_policy: Mapping[str, Any],
) -> dict[str, Any]:
    metadata_items = [
        _checklist_item("reviewer", bool(str(review.get("reviewer", "")).strip())),
        _checklist_item("reviewed_at", bool(str(review.get("reviewed_at", "")).strip())),
        _checklist_item("broker_name", bool(str(review.get("broker_name", "")).strip())),
        _checklist_item("account_id_hash", account_id_hash_diagnostics(review.get("account_id_hash"))["format_ok"]),
        _checklist_item("manual_approval_ticket", bool(str(review.get("manual_approval_ticket", "")).strip())),
        _checklist_item("funding_source_external_confirmation", review.get("funding_source_recorded_outside_repo") is True),
    ]
    safety_items = [
        _checklist_item("local_review_file_exists", input_exists),
        _checklist_item("local_review_gitignored", local_review_write_policy.get("local_review_gitignore_present") is True),
        _checklist_item("template_safe_defaults", template_safety.get("safe_defaults_present") is True),
        _checklist_item("api_key_absent_from_repo", review.get("api_key_present_in_repo") is False),
        _checklist_item("secret_values_not_logged", review.get("secret_values_logged") is False),
        _checklist_item("read_only_or_live_disabled", review.get("read_only_or_live_disabled") is True),
        _checklist_item("order_permission_disabled", review.get("order_permission_enabled") is False),
        _checklist_item("private_endpoint_test_not_used", review.get("private_endpoint_test_used") is False),
        _checklist_item("order_endpoint_test_not_used", review.get("order_endpoint_test_used") is False),
        _checklist_item("credential_storage_outside_source_control", review.get("credential_storage") == "outside_source_control"),
    ]
    all_passed = all(item["passed"] for item in metadata_items + safety_items)
    return {
        "status": "review_checklist_complete" if all_passed else "review_checklist_incomplete",
        "metadata_items": metadata_items,
        "safety_items": safety_items,
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }


def _checklist_item(item_id: str, passed: bool) -> dict[str, Any]:
    return {"item_id": item_id, "passed": bool(passed)}


def account_id_hash_diagnostics(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    compact = re.sub(r"[\s_-]+", "", text)
    raw_detected = bool(compact and any(pattern.fullmatch(compact) for pattern in RAW_ACCOUNT_ID_PATTERNS))
    format_ok = bool(ACCOUNT_ID_HASH_PATTERN.fullmatch(text))
    if not text:
        shape = "missing"
    elif format_ok:
        shape = "sha256_hex_64"
    elif raw_detected:
        shape = "raw_account_id_like"
    else:
        shape = "invalid"
    return {
        "recorded": bool(text),
        "format": shape,
        "format_ok": format_ok,
        "raw_account_id_pattern_detected": raw_detected,
    }


def evidence_classification(status: str) -> dict[str, Any]:
    return {
        "classification": "manual_review_metadata_only",
        "status": status,
        "contains_secret_values": False,
        "contains_account_number": False,
        "contains_raw_funding_source": False,
        "broker_calls_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "can_unlock_paper_or_live": False,
    }


def operator_review_guidance(
    *,
    review: Mapping[str, Any],
    input_exists: bool,
    blockers: list[str],
    template_safety: Mapping[str, Any],
    local_review_write_policy: Mapping[str, Any],
) -> dict[str, Any]:
    missing_text = [key for key in REQUIRED_TEXT_FIELDS if not str(review.get(key, "")).strip()]
    missing_or_wrong_boolean = [
        {"field": key, "required_value": expected}
        for key, expected in REQUIRED_BOOLEAN_FIELDS.items()
        if review.get(key) is not expected
    ]
    forbidden_paths = secret_like_field_paths(review)
    hash_diagnostics = account_id_hash_diagnostics(review.get("account_id_hash"))
    actions: list[str] = []
    if not input_exists:
        actions.append("copy configs/execution/us_equity_broker_credentials_review.template.json to configs/execution/us_equity_broker_credentials_review.local.json")
    if missing_text:
        actions.append("fill reviewer, reviewed_at, broker_name, account_id_hash, and manual_approval_ticket in the local review file")
    if missing_or_wrong_boolean:
        actions.append("confirm every required boolean control in the local review file")
    if hash_diagnostics["recorded"] and not hash_diagnostics["format_ok"]:
        actions.append("replace account_id_hash with sha256:<64 hex chars>; do not record raw broker account ids")
    if forbidden_paths:
        actions.append("remove forbidden secret-like fields from the local review file")
    if local_review_write_policy.get("local_review_gitignore_present") is not True:
        actions.append("add configs/execution/us_equity_broker_credentials_review.local.json to .gitignore before recording the review")
    if template_safety.get("safe_defaults_present") is not True:
        actions.append("repair the broker credentials review template safe defaults")
    return {
        "status": "review_complete" if not blockers else "manual_review_required",
        "local_review_path": str(local_review_write_policy.get("local_review_path") or "configs/execution/us_equity_broker_credentials_review.local.json"),
        "template_path": str(local_review_write_policy.get("allowed_template_path") or "configs/execution/us_equity_broker_credentials_review.template.json"),
        "missing_required_fields": missing_text,
        "required_boolean_controls": missing_or_wrong_boolean,
        "forbidden_field_paths": forbidden_paths,
        "account_id_hash_instruction": "Use sha256:<64 hex chars>; never store raw broker account ids such as Uxxxx or DUxxxx.",
        "secret_handling_instruction": "Do not store API keys, tokens, passwords, raw account numbers, or raw funding details in this repository.",
        "operator_next_actions": actions or ["rerun broker credentials review report and keep paper/live locked"],
    }


def secret_like_field_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            lowered = key_text.lower()
            if lowered not in ALLOWED_SECRET_WORD_FIELDS and any(token in lowered for token in SECRET_LIKE_FIELD_TOKENS):
                paths.append(path)
            paths.extend(secret_like_field_paths(item, path))
        return dedupe(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(secret_like_field_paths(item, path))
        return dedupe(paths)
    return []


def normalize_gitignore_patterns(text: str) -> list[str]:
    return [
        line.strip().replace("\\", "/")
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
