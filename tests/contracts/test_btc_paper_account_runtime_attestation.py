from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_paper_account_runtime_attestation import (
    INPUT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_btc_paper_account_runtime_attestation_report,
)


TS = datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_account_runtime_attestation_missing_is_fail_closed(tmp_path: Path) -> None:
    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=tmp_path,
        input_path=tmp_path / "missing.json",
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
    )

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["status"] == "blocked_fail_closed_research_only"
    assert report["account_mode_verified"] is False
    assert report["credential_permissions_verified"] is False
    assert report["manual_approval_recorded"] is False
    assert "btc_paper_account_runtime_attestation_missing" in report["blockers"]
    assert "btc_paper_account_runtime_credential_permissions_not_verified" in report["blockers"]
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["private_endpoint_used"] is False
    assert report["order_endpoint_used"] is False


def test_account_runtime_attestation_verified_manual_only_still_does_not_unlock(tmp_path: Path) -> None:
    input_path = tmp_path / "attestation.json"
    input_path.write_text(json.dumps(_valid_attestation(), ensure_ascii=False), encoding="utf-8")

    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=tmp_path,
        input_path=input_path,
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
    )

    assert report["status"] == "verified_research_only"
    assert report["blockers"] == []
    assert report["account_mode_verified"] is True
    assert report["position_mode_verified"] is True
    assert report["margin_mode_verified"] is True
    assert report["rate_limit_budget_verified"] is True
    assert report["credential_permissions_verified"] is True
    assert report["credential_separation_verified"] is True
    assert report["manual_approval_recorded"] is True
    assert report["attestation_current"] is True
    assert report["credential_permission_checks"]["withdraw_permission_enabled_false"] is True
    assert report["credential_permission_checks"]["withdraw_permission_verified_false"] is True
    assert report["manual_approval_checks"]["approval_scope_valid"] is True
    assert report["expiration_checks"]["expires_after_generated_at"] is True
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert (tmp_path / "out" / "btc_paper_account_runtime_attestation_report.json").exists()
    assert (tmp_path / "out" / "btc_paper_account_runtime_attestation_safety_status.json").exists()


def test_account_runtime_attestation_rejects_secret_like_fields(tmp_path: Path) -> None:
    payload = _valid_attestation()
    payload["api_key"] = "do-not-store"
    input_path = tmp_path / "attestation.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=tmp_path,
        input_path=input_path,
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
    )

    assert report["status"] == "blocked_fail_closed_research_only"
    assert "btc_paper_account_runtime_attestation_sensitive_fields_present" in report["blockers"]
    assert "api_key" in report["sensitive_fields_detected"]


def test_repository_attestation_template_is_non_secret_and_blocked_by_default(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "configs" / "btc" / "paper_runtime" / "account_runtime_attestation.template.json"

    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=repo_root,
        input_path=template_path,
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
    )

    assert template_path.exists()
    assert report["status"] == "blocked_fail_closed_research_only"
    assert report["sensitive_fields_detected"] == []
    assert report["credential_permissions_verified"] is False
    assert report["credential_separation_verified"] is False
    assert "btc_paper_account_runtime_credential_permissions_not_verified" in report["blockers"]
    assert "btc_paper_account_runtime_credential_separation_not_verified" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_repository_account_runtime_attestation_is_redacted_verified_and_no_unlock(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    input_path = repo_root / "configs" / "btc" / "paper_runtime" / "account_runtime_attestation.json"

    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=repo_root,
        input_path=input_path,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "verified_research_only"
    assert report["blockers"] == []
    assert report["account_mode_verified"] is True
    assert report["position_mode_verified"] is True
    assert report["margin_mode_verified"] is True
    assert report["rate_limit_budget_verified"] is True
    assert report["credential_permissions_verified"] is True
    assert report["credential_separation_verified"] is True
    assert report["manual_approval_recorded"] is True
    assert report["attestation_current"] is True
    assert report["sensitive_fields_detected"] == []
    assert report["api_key_used"] is False
    assert report["private_endpoint_used"] is False
    assert report["order_endpoint_used"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_account_runtime_attestation_rejects_expired_manual_approval(tmp_path: Path) -> None:
    payload = _valid_attestation()
    payload["expires_at_utc"] = "2026-06-30T00:00:00+00:00"
    input_path = tmp_path / "attestation.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=tmp_path,
        input_path=input_path,
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
    )

    assert report["status"] == "blocked_fail_closed_research_only"
    assert report["attestation_current"] is False
    assert report["expiration_checks"]["expires_after_generated_at"] is False
    assert "btc_paper_account_runtime_attestation_not_current" in report["blockers"]


def test_account_runtime_attestation_rejects_unseparated_or_unredacted_key_classes(tmp_path: Path) -> None:
    payload = _valid_attestation()
    payload["credential_permissions"]["withdraw_permission_enabled"] = True
    payload["credential_separation"]["live_trade_redacted_identifier"] = "paper-****0001"
    input_path = tmp_path / "attestation.json"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = build_btc_paper_account_runtime_attestation_report(
        repo_root=tmp_path,
        input_path=input_path,
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
    )

    assert report["credential_permissions_verified"] is False
    assert report["credential_separation_verified"] is False
    assert report["credential_permission_checks"]["withdraw_permission_enabled_false"] is False
    assert report["credential_separation_checks"]["data_paper_live_identifiers_unique"] is False
    assert "btc_paper_account_runtime_credential_permissions_not_verified" in report["blockers"]
    assert "btc_paper_account_runtime_credential_separation_not_verified" in report["blockers"]


def _valid_attestation() -> dict[str, object]:
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "attestation_id": "paper-runtime-approval-0001",
        "venue": "OKX",
        "instrument_id": "BTC-USDT-SWAP",
        "issued_at_utc": "2026-07-01T00:00:00+00:00",
        "expires_at_utc": "2026-08-01T00:00:00+00:00",
        "account_runtime": {
            "account_mode": "paper_trading",
            "account_mode_verified": True,
            "position_mode": "net",
            "position_mode_verified": True,
            "margin_mode": "isolated",
            "margin_mode_verified": True,
            "max_leverage_approved": 3,
        },
        "rate_limit_budget": {
            "verified": True,
            "max_orders_per_minute": 6,
            "max_requests_per_2s": 10,
        },
        "credential_permissions": {
            "credential_class": "paper_trade",
            "paper_key_redacted_identifier": "paper-****0001",
            "read_permission_verified": True,
            "trade_permission_verified": True,
            "withdraw_permission_enabled": False,
            "withdraw_permission_verified_false": True,
            "cashout_disabled_verified": True,
            "ip_allowlist_configured_verified": True,
            "live_credential_not_loaded_verified": True,
        },
        "credential_separation": {
            "recorded": True,
            "data_readonly_redacted_identifier": "data-****0001",
            "paper_trade_redacted_identifier": "paper-****0001",
            "live_trade_redacted_identifier": "live-****0001",
            "data_key_readonly_verified": True,
            "paper_key_not_live_verified": True,
            "live_key_not_loaded_in_paper_verified": True,
        },
        "manual_approval": {
            "recorded": True,
            "approval_id": "manual-paper-runtime-0001",
            "approved_by": "operator",
            "approved_at_utc": "2026-07-01T00:00:00+00:00",
            "approval_scope": "paper_account_runtime_attestation_only_no_order",
            "approval_decision": "approve_attestation_only_no_paper_no_live",
        },
    }
