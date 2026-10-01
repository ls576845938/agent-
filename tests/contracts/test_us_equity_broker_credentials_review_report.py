from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_broker_credentials_review_report import (
    build_us_equity_broker_credentials_review_report,
)


SCHEMA = Path("schemas/us_equity_broker_credentials_review_report.schema.json")


def test_broker_credentials_review_report_rules_live_in_live_service() -> None:
    assert build_us_equity_broker_credentials_review_report.__module__ == "quant_us.live.broker_credentials_review_report"


def test_broker_credentials_review_blocks_without_manual_input(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert payload["broker_credentials_proven"] is False
    assert payload["paper_order_allowed"] is False
    assert payload["live_order_allowed"] is False
    assert payload["review_input"]["exists"] is False
    assert payload["local_review_write_policy"]["should_not_commit_local_review"] is True
    assert payload["local_review_write_policy"]["local_review_gitignore_present"] is True
    assert "broker_credentials_review_input_missing" in payload["blockers"]
    assert payload["credential_review"]["metadata_only"] is True
    assert payload["credential_review"]["can_unlock_paper_or_live"] is False
    assert payload["secret_scan"]["secret_values_exposed_in_artifact"] is False
    assert payload["secret_scan"]["raw_account_id_exposed_in_artifact"] is False
    assert payload["operator_checklist"]["status"] == "review_checklist_incomplete"
    assert payload["operator_checklist"]["paper_or_live_unlock_allowed"] is False
    assert payload["operator_review_guidance"]["status"] == "manual_review_required"
    assert payload["operator_review_guidance"]["missing_required_fields"] == [
        "reviewer",
        "reviewed_at",
        "broker_name",
        "account_id_hash",
        "manual_approval_ticket",
    ]
    assert {
        item["field"]: item["required_value"]
        for item in payload["operator_review_guidance"]["required_boolean_controls"]
    } == {
        "api_key_present_in_repo": False,
        "secret_values_logged": False,
        "read_only_or_live_disabled": True,
        "order_permission_enabled": False,
        "private_endpoint_test_used": False,
        "order_endpoint_test_used": False,
        "funding_source_recorded_outside_repo": True,
    }
    assert payload["operator_review_guidance"]["local_review_path"] == "configs/execution/us_equity_broker_credentials_review.local.json"
    assert "copy configs/execution/us_equity_broker_credentials_review.template.json" in payload["operator_review_guidance"]["operator_next_actions"][0]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert payload["guardrails"]["broker_calls_used"] is False


def test_broker_credentials_review_proven_with_complete_manual_input(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", _valid_input())
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_proven"
    assert payload["broker_credentials_proven"] is True
    assert payload["paper_order_allowed"] is False
    assert payload["live_order_allowed"] is False
    assert payload["blockers"] == []
    assert payload["credential_review"] == {
        "metadata_only": True,
        "broker_name": "manual_broker_name",
        "account_id_hash": "sha256:" + ("a" * 64),
        "account_id_hash_recorded": True,
        "reviewer": "manual_reviewer",
        "reviewed_at": "2026-06-27T00:00:00Z",
        "manual_approval_ticket": "manual-ticket-001",
        "funding_source_external_confirmation": True,
        "credential_storage": "outside_source_control",
        "secret_values_recorded": False,
        "raw_account_id_recorded": False,
        "raw_funding_source_recorded": False,
        "can_unlock_paper_or_live": False,
    }
    assert payload["review_metadata"] == {
        "metadata_only": True,
        "status": "broker_credentials_review_proven",
        "reviewer": "manual_reviewer",
        "reviewed_at": "2026-06-27T00:00:00Z",
        "broker_name": "manual_broker_name",
        "account_id_hash": "sha256:" + ("a" * 64),
        "account_id_hash_recorded": True,
        "manual_approval_ticket": "manual-ticket-001",
        "funding_source_recorded_outside_repo": True,
        "credential_storage": "outside_source_control",
        "secret_values_recorded": False,
        "raw_account_id_recorded": False,
        "raw_funding_source_recorded": False,
        "can_unlock_paper_or_live": False,
    }
    assert payload["review_summary"]["read_only_or_live_disabled"] is True
    assert payload["review_summary"]["order_permission_enabled"] is False
    assert payload["review_summary"]["api_key_present_in_repo"] is False
    assert payload["review_summary"]["secret_like_field_count"] == 0
    assert payload["review_summary"]["account_id_hash_format"] == "sha256_hex_64"
    assert payload["review_summary"]["account_id_hash_format_ok"] is True
    assert payload["review_summary"]["raw_account_id_pattern_detected"] is False
    assert payload["local_review_write_policy"]["local_review_path"] == "configs/execution/us_equity_broker_credentials_review.local.json"
    assert payload["local_review_write_policy"]["local_review_gitignore_present"] is True
    assert payload["template_safety"]["safe_defaults_present"] is True
    assert payload["secret_scan"]["metadata_only_scan"] is True
    assert payload["secret_scan"]["forbidden_field_paths"] == []
    assert payload["secret_scan"]["contains_secret_values"] is False
    assert payload["secret_scan"]["secret_values_exposed_in_artifact"] is False
    assert payload["operator_checklist"]["status"] == "review_checklist_complete"
    assert all(item["passed"] for item in payload["operator_checklist"]["metadata_items"])
    assert all(item["passed"] for item in payload["operator_checklist"]["safety_items"])
    assert payload["operator_checklist"]["paper_or_live_unlock_allowed"] is False
    assert payload["operator_checklist"]["live_order_allowed"] is False
    assert payload["operator_review_guidance"]["status"] == "review_complete"
    assert payload["operator_review_guidance"]["missing_required_fields"] == []
    assert payload["operator_review_guidance"]["required_boolean_controls"] == []
    assert payload["operator_review_guidance"]["forbidden_field_paths"] == []
    assert payload["evidence_classification"]["classification"] == "manual_review_metadata_only"
    assert payload["evidence_classification"]["contains_secret_values"] is False
    assert payload["evidence_classification"]["contains_account_number"] is False
    assert payload["evidence_classification"]["contains_raw_funding_source"] is False
    assert payload["evidence_classification"]["can_unlock_paper_or_live"] is False


def test_broker_credentials_review_blocks_order_permission_enabled(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    bad = _valid_input()
    bad["order_permission_enabled"] = True
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", bad)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert "broker_credentials_order_permission_enabled_not_false" in payload["blockers"]


def test_broker_credentials_review_blocks_raw_account_id_instead_of_hash(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    bad = _valid_input()
    bad["account_id_hash"] = "U1234567"
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", bad)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert "broker_credentials_account_id_hash_looks_like_raw_account_id" in payload["blockers"]
    assert "broker_credentials_account_id_hash_invalid_format" in payload["blockers"]
    assert payload["review_summary"]["account_id_hash_format"] == "raw_account_id_like"
    assert payload["review_summary"]["account_id_hash_format_ok"] is False
    assert payload["review_summary"]["raw_account_id_pattern_detected"] is True
    assert payload["review_metadata"]["account_id_hash"] == ""
    assert payload["review_metadata"]["account_id_hash_recorded"] is False
    assert payload["review_metadata"]["raw_account_id_recorded"] is False
    artifact = (tmp_path / "out/broker_review.json").read_text(encoding="utf-8")
    assert "U1234567" not in artifact


def test_broker_credentials_review_blocks_invalid_account_hash_shape(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    bad = _valid_input()
    bad["account_id_hash"] = "sha256:examplehash"
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", bad)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert "broker_credentials_account_id_hash_invalid_format" in payload["blockers"]
    assert payload["review_summary"]["account_id_hash_format"] == "invalid"
    assert payload["review_summary"]["account_id_hash_format_ok"] is False
    assert payload["review_summary"]["raw_account_id_pattern_detected"] is False


def test_broker_credentials_review_blocks_secret_like_extra_fields_without_leaking_values(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    bad = _valid_input()
    bad["api_key"] = "SHOULD_NOT_APPEAR_IN_ARTIFACT"
    bad["raw_metadata"] = {"api_secret": "ALSO_SHOULD_NOT_APPEAR"}
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", bad)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert "broker_credentials_review_input_contains_secret_like_field" in payload["blockers"]
    assert payload["review_summary"]["secret_like_field_count"] == 2
    assert payload["secret_scan"]["forbidden_field_paths"] == ["api_key", "raw_metadata.api_secret"]
    assert payload["secret_scan"]["secret_like_field_count"] == 2
    assert payload["secret_scan"]["contains_secret_values"] is False
    assert payload["secret_scan"]["secret_values_exposed_in_artifact"] is False
    assert payload["operator_review_guidance"]["forbidden_field_paths"] == ["api_key", "raw_metadata.api_secret"]
    assert "remove forbidden secret-like fields from the local review file" in payload["operator_review_guidance"]["operator_next_actions"]
    artifact = (tmp_path / "out/broker_review.json").read_text(encoding="utf-8")
    markdown = (tmp_path / "out/broker_review.md").read_text(encoding="utf-8")
    assert "SHOULD_NOT_APPEAR_IN_ARTIFACT" not in artifact
    assert "ALSO_SHOULD_NOT_APPEAR" not in artifact
    assert "SHOULD_NOT_APPEAR_IN_ARTIFACT" not in markdown
    assert "ALSO_SHOULD_NOT_APPEAR" not in markdown


def test_broker_credentials_review_blocks_unsafe_template_defaults(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", _valid_input())
    unsafe_template = _template_input()
    unsafe_template["read_only_or_live_disabled"] = False
    unsafe_template["order_permission_enabled"] = True
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", unsafe_template)

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert payload["template_safety"]["safe_defaults_present"] is False
    assert "broker_credentials_template_safe_defaults_missing" in payload["blockers"]


def test_broker_credentials_review_blocks_secret_like_template_fields(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", _valid_input())
    unsafe_template = _template_input()
    unsafe_template["raw_token"] = "template-value-must-not-matter"
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", unsafe_template)

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert payload["template_safety"]["secret_like_fields"] == ["raw_token"]
    assert "broker_credentials_template_contains_secret_like_field" in payload["blockers"]


def test_broker_credentials_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_broker_credentials_schema_rejects_top_level_trade_unlocks(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["paper_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_order_allowed=true")


def test_broker_credentials_schema_rejects_blocked_status_marked_proven(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["broker_credentials_proven"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted blocked status with broker_credentials_proven=true")


def test_broker_credentials_review_blocks_missing_local_gitignore(tmp_path: Path) -> None:
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", _valid_input())
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())

    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_review_blocked"
    assert payload["local_review_write_policy"]["local_review_gitignore_present"] is False
    assert "broker_credentials_local_review_not_gitignored" in payload["blockers"]


def test_broker_credentials_schema_rejects_committable_local_review(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["local_review_write_policy"]["should_not_commit_local_review"] = False

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted should_not_commit_local_review=false")


def test_broker_credentials_schema_rejects_review_that_unlocks_paper_or_live(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", _valid_input())
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["evidence_classification"]["can_unlock_paper_or_live"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted can_unlock_paper_or_live=true")


def test_broker_credentials_schema_rejects_metadata_unlock(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", _valid_input())
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["review_metadata"]["can_unlock_paper_or_live"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted review_metadata.can_unlock_paper_or_live=true")


def test_broker_credentials_schema_rejects_credential_review_unlock(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", _valid_input())
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", _template_input())
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["credential_review"]["can_unlock_paper_or_live"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted credential_review.can_unlock_paper_or_live=true")


def test_broker_credentials_schema_rejects_secret_scan_leak_flag(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    payload = build_us_equity_broker_credentials_review_report(
        repo_root=tmp_path,
        output=Path("out/broker_review.json"),
        markdown_output=Path("out/broker_review.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["secret_scan"]["secret_values_exposed_in_artifact"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted secret_scan.secret_values_exposed_in_artifact=true")


def _valid_input() -> dict[str, object]:
    return {
        "schema_version": "us_equity_broker_credentials_review_input_v1",
        "reviewer": "manual_reviewer",
        "reviewed_at": "2026-06-27T00:00:00Z",
        "broker_name": "manual_broker_name",
        "account_id_hash": "sha256:" + ("a" * 64),
        "credential_storage": "outside_source_control",
        "api_key_present_in_repo": False,
        "secret_values_logged": False,
        "read_only_or_live_disabled": True,
        "order_permission_enabled": False,
        "private_endpoint_test_used": False,
        "order_endpoint_test_used": False,
        "funding_source_recorded_outside_repo": True,
        "manual_approval_ticket": "manual-ticket-001",
    }


def _template_input() -> dict[str, object]:
    template = _valid_input()
    template["reviewer"] = ""
    template["reviewed_at"] = ""
    template["broker_name"] = ""
    template["account_id_hash"] = ""
    template["manual_approval_ticket"] = ""
    return template


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_gitignore(root: Path) -> None:
    (root / ".gitignore").write_text(
        "configs/execution/us_equity_broker_credentials_review.local.json\n",
        encoding="utf-8",
    )


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
