from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_broker_credentials_operator_handoff import (
    build_us_equity_broker_credentials_operator_handoff,
)


SCHEMA = Path("schemas/us_equity_broker_credentials_operator_handoff.schema.json")


def test_broker_credentials_handoff_blocks_until_local_review_exists(tmp_path: Path) -> None:
    _write_template(tmp_path)
    _write_review(tmp_path, status="broker_credentials_review_blocked", blockers=["broker_credentials_review_input_missing"])

    payload = build_us_equity_broker_credentials_operator_handoff(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_handoff_blocked"
    assert payload["operator_files"]["template_exists"] is True
    assert payload["operator_files"]["local_review_exists"] is False
    assert payload["manual_review_readiness"]["review_report_exists"] is True
    assert payload["manual_review_readiness"]["review_report_status"] == "broker_credentials_review_blocked"
    assert payload["manual_review_readiness"]["template_exists"] is True
    assert payload["manual_review_readiness"]["local_review_exists"] is False
    assert payload["manual_review_readiness"]["local_review_gitignored"] is False
    assert payload["manual_review_readiness"]["ready_for_manual_review"] is False
    assert payload["manual_review_readiness"]["review_proven"] is False
    assert payload["manual_review_readiness"]["paper_or_live_unlock_allowed"] is False
    assert payload["manual_review_readiness"]["live_order_allowed"] is False
    assert payload["broker_connectivity_evidence"]["operator_interpretation"]["can_satisfy_credential_review"] is False
    assert payload["broker_connectivity_evidence"]["operator_interpretation"]["can_unlock_paper_or_live"] is False
    assert "broker_credentials_local_review_missing" in payload["blockers"]
    assert "broker_credentials_review_input_missing" in payload["blockers"]
    assert payload["guardrails"]["contains_secret_values"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False


def test_broker_credentials_handoff_ready_when_manual_review_proven(tmp_path: Path) -> None:
    _write_template(tmp_path)
    _write_local_review(tmp_path)
    _write_review(tmp_path, status="broker_credentials_review_proven", blockers=[])

    payload = build_us_equity_broker_credentials_operator_handoff(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "broker_credentials_handoff_ready_for_manual_review"
    assert payload["blockers"] == []
    assert payload["operator_files"]["local_review_should_not_be_committed"] is True
    assert payload["manual_review_readiness"]["ready_for_manual_review"] is True
    assert payload["manual_review_readiness"]["review_proven"] is True
    assert payload["manual_review_readiness"]["missing_manual_fields"] == []
    assert payload["manual_review_readiness"]["unsafe_boolean_fields"] == []


def test_broker_credentials_handoff_surfaces_readonly_ibkr_probe_without_unlocking_review(tmp_path: Path) -> None:
    _write_template(tmp_path)
    _write_review(tmp_path, status="broker_credentials_review_blocked", blockers=["broker_credentials_reviewer_missing"])
    _write_ibkr_probe(tmp_path)
    _write_ibkr_coverage(tmp_path)

    payload = build_us_equity_broker_credentials_operator_handoff(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    evidence = payload["broker_connectivity_evidence"]
    assert evidence["evidence_role"] == "read_only_ibkr_market_data_connectivity_only"
    assert evidence["probe_report"]["status"] == "pass"
    assert evidence["probe_report"]["port"] == 4002
    assert evidence["probe_report"]["readonly_connection_requested"] is True
    assert evidence["coverage_report"]["status"] == "partial"
    assert evidence["coverage_report"]["summary"]["next_missing_by_symbol"]["TQQQ"] == "2022-02-09"
    assert evidence["operator_interpretation"]["connection_proven"] is True
    assert evidence["operator_interpretation"]["minute_coverage_complete"] is False
    assert evidence["operator_interpretation"]["minute_data_research_ready"] is False
    assert evidence["operator_interpretation"]["can_satisfy_credential_review"] is False
    assert evidence["operator_interpretation"]["manual_review_still_required"] is True
    assert evidence["guardrails"]["market_data_probe_only"] is True
    assert evidence["guardrails"]["private_account_endpoint_used"] is False
    assert evidence["guardrails"]["order_endpoint_used"] is False
    assert evidence["guardrails"]["real_order_submitted"] is False
    assert payload["status"] == "broker_credentials_handoff_blocked"
    assert "broker_credentials_reviewer_missing" in payload["blockers"]


def test_broker_credentials_handoff_schema_rejects_live_flag(tmp_path: Path) -> None:
    _write_template(tmp_path)
    _write_review(tmp_path, status="broker_credentials_review_blocked", blockers=["broker_credentials_review_input_missing"])
    payload = build_us_equity_broker_credentials_operator_handoff(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_broker_credentials_handoff_schema_rejects_readiness_live_unlock(tmp_path: Path) -> None:
    _write_template(tmp_path)
    _write_review(tmp_path, status="broker_credentials_review_blocked", blockers=["broker_credentials_review_input_missing"])
    payload = build_us_equity_broker_credentials_operator_handoff(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["manual_review_readiness"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted manual_review_readiness.live_order_allowed=true")


def _write_template(tmp_path: Path) -> None:
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json", {"template": True})


def _write_local_review(tmp_path: Path) -> None:
    _write_json(tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json", {"local": True})


def _write_review(tmp_path: Path, *, status: str, blockers: list[str]) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json",
        {
            "status": status,
            "blockers": blockers,
            "review_summary": _valid_summary() if status == "broker_credentials_review_proven" else {},
            "template_safety": {"safe_defaults_present": status == "broker_credentials_review_proven"},
            "local_review_write_policy": {"local_review_gitignore_present": status == "broker_credentials_review_proven"},
            "guardrails": {"live_order_allowed": False},
        },
    )


def _write_ibkr_probe(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/ibkr_historical_bars_probe_report.json",
        {
            "status": "pass",
            "host": "127.0.0.1",
            "port": 4002,
            "client_id": 71,
            "readonly_connection_requested": True,
            "symbols": ["QQQ", "TQQQ"],
            "summary": {"available_symbol_count": 2},
            "blockers": [],
            "guardrails": {
                "private_account_endpoint_used": False,
                "order_endpoint_used": False,
                "broker_order_endpoint_used": False,
                "real_order_submitted": False,
            },
        },
    )


def _write_ibkr_coverage(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/ibkr_minute_coverage_report.json",
        {
            "status": "partial",
            "research_ready_status": "blocked",
            "summary": {
                "next_missing_by_symbol": {"QQQ": "2023-07-19", "TQQQ": "2022-02-09"},
            },
            "blockers": ["ibkr_tqqq_minute_coverage_incomplete"],
            "guardrails": {"network_called": False},
        },
    )


def _valid_summary() -> dict[str, object]:
    return {
        "reviewer_recorded": True,
        "reviewed_at_recorded": True,
        "broker_name_recorded": True,
        "account_id_hash_recorded": True,
        "manual_approval_ticket_recorded": True,
        "api_key_present_in_repo": False,
        "secret_values_logged": False,
        "read_only_or_live_disabled": True,
        "order_permission_enabled": False,
        "private_endpoint_test_used": False,
        "order_endpoint_test_used": False,
        "funding_source_recorded_outside_repo": True,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
