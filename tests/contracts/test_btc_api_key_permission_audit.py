from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.artifact_schema import validate_btc_artifact_schema
from quant_crypto.security.api_key_audit import (
    BTCAPIKeyClass,
    BTCAPIKeyPermissionRecord,
    build_btc_api_key_permission_audit,
    build_btc_api_key_permission_records_template,
    find_secret_like_record_fields,
)
from scripts.build_btc_api_key_permission_audit import (
    DEFAULT_RECORDS,
    build_btc_api_key_permission_audit_file,
    write_btc_api_key_permission_records_template,
)


TS = datetime(2026, 6, 26, 8, 0, tzinfo=timezone.utc)


def test_btc_api_key_permission_audit_accepts_redacted_separated_keys() -> None:
    payload = build_btc_api_key_permission_audit(
        records=[
            _record(
                key_class=BTCAPIKeyClass.DATA_READONLY,
                mode="read_only",
                permission_read=True,
                permission_trade=False,
                environment_target="read_only",
                redacted_identifier="data-****1111",
            ),
            _record(
                key_class=BTCAPIKeyClass.PAPER_TRADE,
                mode="paper",
                permission_read=True,
                permission_trade=True,
                environment_target="paper",
                redacted_identifier="paper-****2222",
            ),
            _record(
                key_class=BTCAPIKeyClass.LIVE_TRADE,
                mode="live",
                permission_read=True,
                permission_trade=True,
                environment_target="live",
                redacted_identifier="live-****3333",
            ),
        ],
        generated_at_utc=TS,
    )

    assert payload["status"] == "complete"
    assert payload["secret_values_inspected"] is False
    assert payload["secret_values_output"] is False
    assert payload["withdraw_permission_allowed"] is False
    assert payload["manual_approval_fields_verified"] is True
    assert payload["all_records_unexpired"] is True
    assert payload["all_records_redacted"] is True
    assert payload["live_orders_allowed"] is False
    assert validate_btc_artifact_schema(payload) == []


def test_btc_api_key_permission_audit_blocks_withdraw_mode_mismatch_and_secret_metadata() -> None:
    payload = build_btc_api_key_permission_audit(
        records=[
            _record(
                key_class=BTCAPIKeyClass.DATA_READONLY,
                venue="binance_usdm",
                mode="paper",
                permission_read=True,
                permission_trade=True,
                permission_withdraw=True,
                ip_allowlist_configured=False,
                environment_target="live",
                redacted_identifier="same",
                raw_metadata={"api_secret": "should-not-be-here"},
            ),
            _record(
                key_class=BTCAPIKeyClass.PAPER_TRADE,
                venue="binance_usdm",
                mode="paper",
                permission_read=True,
                permission_trade=True,
                permission_withdraw=False,
                ip_allowlist_configured=True,
                environment_target="paper",
                redacted_identifier="same",
            ),
        ],
        generated_at_utc=TS,
    )

    assert payload["status"] == "blocked"
    assert "btc_api_key_class_missing:live_trade" in payload["blockers"]
    assert "btc_api_key_withdraw_permission_enabled:data_readonly" in payload["blockers"]
    assert "btc_api_key_data_readonly_has_trade_permission" in payload["blockers"]
    assert "btc_api_key_mode_mismatch:data_readonly:paper" in payload["blockers"]
    assert "btc_api_key_environment_target_mismatch:data_readonly" in payload["blockers"]
    assert "btc_api_key_audit_metadata_contains_secret_like_field:data_readonly" in payload["blockers"]
    assert "btc_api_key_data_paper_live_keys_not_separated" in payload["blockers"]
    assert payload["data_paper_live_keys_separated"] is False


def test_btc_api_key_permission_audit_blocks_expired_or_unapproved_records() -> None:
    payload = build_btc_api_key_permission_audit(
        records=[
            _record(
                key_class=BTCAPIKeyClass.DATA_READONLY,
                mode="read_only",
                permission_read=True,
                permission_trade=False,
                environment_target="read_only",
                redacted_identifier="data-****1111",
                manual_approval_id="",
                expires_at_utc="2026-06-01T00:00:00+00:00",
            ),
            _record(
                key_class=BTCAPIKeyClass.PAPER_TRADE,
                mode="paper",
                permission_read=True,
                permission_trade=True,
                environment_target="paper",
                redacted_identifier="paper-****2222",
            ),
            _record(
                key_class=BTCAPIKeyClass.LIVE_TRADE,
                mode="live",
                permission_read=True,
                permission_trade=True,
                environment_target="live",
                redacted_identifier="live-****3333",
            ),
        ],
        generated_at_utc=TS,
    )

    assert payload["status"] == "blocked"
    assert "btc_api_key_manual_approval_id_missing:data_readonly" in payload["blockers"]
    assert "btc_api_key_attestation_expired:data_readonly" in payload["blockers"]
    assert payload["manual_approval_fields_verified"] is False
    assert payload["all_records_unexpired"] is False


def test_btc_api_key_permission_template_contains_only_redacted_permission_facts(tmp_path: Path) -> None:
    template_path = tmp_path / "btc_api_key_permission_records.template.json"

    write_btc_api_key_permission_records_template(template_path)
    payload = json.loads(template_path.read_text(encoding="utf-8"))

    assert payload == build_btc_api_key_permission_records_template()
    assert payload["repository_default_fail_closed"] is True
    assert payload["all_permissions_enabled"] is False
    assert payload["all_approvals_completed"] is False
    assert len(payload["records"]) == 3
    assert {row["key_class"] for row in payload["records"]} == {"data_readonly", "paper_trade", "live_trade"}
    for row in payload["records"]:
        assert sorted(find_secret_like_record_fields(row)) == []
        assert "redacted_identifier" in row
        assert "api_key" not in row
        assert "api_secret" not in row
        assert row["permission_read"] is False
        assert row["permission_trade"] is False
        assert row["permission_withdraw"] is False
        assert row["manual_approval_id"] == ""


def test_btc_api_key_permission_file_loader_accepts_redacted_records(tmp_path: Path) -> None:
    records_path = tmp_path / "records.json"
    output_path = tmp_path / "audit.json"
    records_path.write_text(json.dumps({
        "records": [
            {
                "key_class": "data_readonly",
                "venue": "okx",
                "mode": "read_only",
                "permission_read": True,
                "permission_trade": False,
                "permission_withdraw": False,
                "ip_allowlist_configured": False,
                "environment_target": "read_only",
                "redacted_identifier": "data-****1111",
                "withdraw_permission_verified_false": True,
                "redaction_confirmed": True,
                "manual_approval_id": "manual-key-audit-0001",
                "reviewed_at_utc": "2026-06-26T08:00:00+00:00",
                "expires_at_utc": "2026-08-01T00:00:00+00:00",
            },
            {
                "key_class": "paper_trade",
                "venue": "okx",
                "mode": "paper",
                "permission_read": True,
                "permission_trade": True,
                "permission_withdraw": False,
                "ip_allowlist_configured": True,
                "environment_target": "paper",
                "redacted_identifier": "paper-****2222",
                "withdraw_permission_verified_false": True,
                "redaction_confirmed": True,
                "manual_approval_id": "manual-key-audit-0001",
                "reviewed_at_utc": "2026-06-26T08:00:00+00:00",
                "expires_at_utc": "2026-08-01T00:00:00+00:00",
            },
            {
                "key_class": "live_trade",
                "venue": "okx",
                "mode": "live",
                "permission_read": True,
                "permission_trade": True,
                "permission_withdraw": False,
                "ip_allowlist_configured": True,
                "environment_target": "live",
                "redacted_identifier": "live-****3333",
                "withdraw_permission_verified_false": True,
                "redaction_confirmed": True,
                "manual_approval_id": "manual-key-audit-0001",
                "reviewed_at_utc": "2026-06-26T08:00:00+00:00",
                "expires_at_utc": "2026-08-01T00:00:00+00:00",
            },
        ],
    }), encoding="utf-8")

    payload = build_btc_api_key_permission_audit_file(
        output=output_path,
        records_path=records_path,
        generated_at_utc=TS,
    )

    assert payload["status"] == "complete"
    assert payload["blockers"] == []
    assert output_path.exists()
    assert validate_btc_artifact_schema(payload) == []


def test_btc_api_key_permission_file_loader_blocks_secret_like_fields_without_leaking_values(tmp_path: Path) -> None:
    records_path = tmp_path / "bad_records.json"
    output_path = tmp_path / "audit.json"
    records_path.write_text(json.dumps({
        "records": [
            {
                "key_class": "data_readonly",
                "venue": "okx",
                "mode": "read_only",
                "permission_read": True,
                "permission_trade": False,
                "permission_withdraw": False,
                "ip_allowlist_configured": False,
                "environment_target": "read_only",
                "redacted_identifier": "data-****1111",
                "api_secret": "do-not-leak",
            },
        ],
    }), encoding="utf-8")

    payload = build_btc_api_key_permission_audit_file(
        output=output_path,
        records_path=records_path,
        generated_at_utc=TS,
    )
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "blocked"
    assert "btc_api_key_permission_record_contains_secret_like_field:0" in payload["blockers"]
    assert "btc_api_key_permission_record_invalid:0:TypeError" in payload["blockers"]
    assert "do-not-leak" not in encoded


def test_repository_default_btc_api_key_permission_records_are_fail_closed(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    records_path = repo_root / DEFAULT_RECORDS
    raw = json.loads(records_path.read_text(encoding="utf-8"))

    for row in raw["records"]:
        assert find_secret_like_record_fields(row) == []
        assert row["permission_read"] is False
        assert row["permission_trade"] is False
        assert row["permission_withdraw"] is False
        assert row["manual_approval_id"] == ""
        assert row["redaction_confirmed"] is False

    payload = build_btc_api_key_permission_audit_file(
        output=tmp_path / "audit.json",
        records_path=records_path,
        generated_at_utc=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert raw["repository_default_fail_closed"] is True
    assert raw["all_permissions_enabled"] is False
    assert raw["all_approvals_completed"] is False
    assert payload["status"] == "blocked"
    assert "btc_api_key_manual_approval_id_missing:data_readonly" in payload["blockers"]
    assert "btc_api_key_manual_approval_id_missing:paper_trade" in payload["blockers"]
    assert "btc_api_key_manual_approval_id_missing:live_trade" in payload["blockers"]
    assert payload["manual_approval_fields_verified"] is False
    assert payload["all_records_unexpired"] is False
    assert payload["all_records_redacted"] is False
    assert payload["data_paper_live_keys_separated"] is False
    assert payload["secret_values_inspected"] is False
    assert payload["secret_values_output"] is False
    assert payload["live_orders_allowed"] is False


def _record(**overrides: object) -> BTCAPIKeyPermissionRecord:
    kwargs = {
        "venue": "okx",
        "permission_withdraw": False,
        "ip_allowlist_configured": True,
        "withdraw_permission_verified_false": True,
        "redaction_confirmed": True,
        "manual_approval_id": "manual-key-audit-0001",
        "reviewed_at_utc": "2026-06-26T08:00:00+00:00",
        "expires_at_utc": "2026-08-01T00:00:00+00:00",
    }
    kwargs.update(overrides)
    return BTCAPIKeyPermissionRecord(**kwargs)
