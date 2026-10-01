from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_manual_decision_record_report import build_us_equity_manual_decision_record_report


SCHEMA = Path("schemas/us_equity_manual_decision_record_report.schema.json")
LOCAL_RECORD = Path("configs/reviews/us_equity_manual_decision_record.local.json")


def test_manual_decision_record_report_rules_live_in_live_service() -> None:
    assert build_us_equity_manual_decision_record_report.__module__ == "quant_us.live.manual_decision_record_report"


def test_manual_decision_record_missing_is_blocked_without_unlock(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")

    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_decision_record_missing_or_invalid"
    assert payload["record_readiness"]["record_exists"] is False
    assert payload["record_readiness"]["template_exists"] is True
    assert payload["record_readiness"]["schema_version_valid"] is False
    assert payload["record_readiness"]["missing_required_fields"] == [
        "strategy_id",
        "review_id",
        "reviewed_at",
        "reviewer",
        "decision",
        "reason",
    ]
    assert payload["record_readiness"]["decision_allowed"] is False
    assert payload["record_readiness"]["ready_for_manual_review_packet"] is False
    assert payload["record_readiness"]["paper_or_live_unlock_allowed"] is False
    assert payload["record_readiness"]["live_order_allowed"] is False
    assert payload["operator_decision_guidance"]["status"] == "manual_decision_required"
    assert payload["operator_decision_guidance"]["missing_required_fields"] == [
        "strategy_id",
        "review_id",
        "reviewed_at",
        "reviewer",
        "decision",
        "reason",
    ]
    assert payload["operator_decision_guidance"]["local_record_path"] == "configs/reviews/us_equity_manual_decision_record.local.json"
    assert payload["operator_decision_guidance"]["required_evidence_path_rules"] == {
        "must_exist": True,
        "must_be_within_repo": True,
        "required_prefix": "artifacts/us_equity",
        "required_suffix": ".json",
    }
    dependency = payload["paper_start_dependency"]
    assert dependency["manual_record_valid"] is False
    assert dependency["paper_candidate_decision_recorded"] is False
    assert dependency["manual_record_can_start_paper_by_itself"] is False
    assert dependency["manual_record_can_unlock_live_by_itself"] is False
    assert dependency["paper_start_dependency_status"] == "blocked"
    assert dependency["required_next_gate_for_paper"] == "manual_review_packet_then_paper_simulation_readiness"
    assert dependency["required_runner_condition"] == "run_us_equity_paper_simulation_roll(..., manual_start_approved=True)"
    assert dependency["paper_simulation_allowed"] is False
    assert dependency["live_order_allowed"] is False
    assert "copy configs/reviews/us_equity_manual_decision_record.template.json" in payload["operator_decision_guidance"]["operator_next_actions"][0]
    assert payload["local_record_write_policy"]["should_not_commit_local_record"] is True
    assert payload["evidence_classification"]["manual_record_can_unlock_paper_by_itself"] is False
    assert "us_equity_manual_decision_record_missing" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["secrets_allowed"] is False


def test_manual_decision_record_malformed_json_fails_closed(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    record = tmp_path / LOCAL_RECORD
    record.parent.mkdir(parents=True)
    record.write_text("{not-json", encoding="utf-8")

    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_decision_record_missing_or_invalid"
    assert "us_equity_manual_decision_record_schema_version_invalid" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_manual_decision_record_validates_review_evidence_but_does_not_unlock(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    evidence = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({"status": "manual_review_ready"}), encoding="utf-8")
    _write_record(
        tmp_path / LOCAL_RECORD,
        evidence_paths=["artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json"],
    )

    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_decision_record_valid"
    assert payload["decision"] == "manual_decision_record_validated_no_unlock"
    assert payload["record_summary"]["reviewer_recorded"] is True
    assert payload["record_summary"]["evidence_path_count"] == 1
    assert payload["evidence_path_details"] == [
        {
            "path": "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
            "exists": True,
            "within_repo": True,
            "is_json_report": True,
            "is_us_equity_artifact": True,
            "traceable_report_artifact": True,
            "reported_status": "manual_review_ready",
        }
    ]
    assert payload["record_readiness"]["record_exists"] is True
    assert payload["record_readiness"]["template_exists"] is True
    assert payload["record_readiness"]["schema_version_valid"] is True
    assert payload["record_readiness"]["missing_required_fields"] == []
    assert payload["record_readiness"]["decision_allowed"] is True
    assert payload["record_readiness"]["paper_candidate_decision_recorded"] is True
    assert payload["record_readiness"]["evidence_paths_recorded"] is True
    assert payload["record_readiness"]["evidence_paths_missing_count"] == 0
    assert payload["record_readiness"]["forbidden_unlock_flags_present"] is False
    assert payload["record_readiness"]["ready_for_manual_review_packet"] is True
    assert payload["operator_decision_guidance"]["status"] == "record_complete"
    assert payload["operator_decision_guidance"]["missing_required_fields"] == []
    assert payload["operator_decision_guidance"]["missing_evidence_paths"] == []
    assert payload["operator_decision_guidance"]["non_traceable_evidence_paths"] == []
    assert payload["operator_decision_guidance"]["forbidden_unlock_flags"] == []
    assert payload["operator_decision_guidance"]["paper_or_live_unlock_allowed"] is False
    assert payload["operator_decision_guidance"]["live_order_allowed"] is False
    assert payload["local_record_write_policy"]["local_record_gitignore_present"] is True
    assert payload["evidence_classification"]["classification"] == "manual_decision_metadata_only"
    assert payload["evidence_classification"]["manual_record_can_unlock_paper_by_itself"] is False
    assert payload["evidence_classification"]["manual_record_can_unlock_live_by_itself"] is False
    assert payload["evidence_classification"]["required_next_gate_for_paper"] == "manual_review_packet_then_paper_simulation_readiness"
    dependency = payload["paper_start_dependency"]
    assert dependency["manual_record_valid"] is True
    assert dependency["paper_candidate_decision_recorded"] is True
    assert dependency["manual_record_can_start_paper_by_itself"] is False
    assert dependency["manual_record_can_unlock_live_by_itself"] is False
    assert dependency["paper_start_dependency_status"] == "ready_for_next_gate"
    assert dependency["required_next_reports"] == [
        "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
        "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
        "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_roll_report.json",
    ]
    assert dependency["required_evidence_traceability"] == "all evidence_paths must be existing JSON reports under artifacts/us_equity*"
    assert dependency["paper_simulation_allowed"] is False
    assert dependency["live_order_allowed"] is False
    assert payload["blockers"] == []
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_manual_decision_record_blocks_missing_evidence_and_forbidden_unlock(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    _write_record(
        tmp_path / LOCAL_RECORD,
        evidence_paths=["missing_evidence.json"],
        paper_simulation_allowed=True,
        live_order_allowed=True,
    )

    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_decision_record_missing_or_invalid"
    assert payload["record_readiness"]["evidence_paths_missing_count"] == 1
    assert payload["record_readiness"]["forbidden_unlock_flags_present"] is True
    assert payload["record_readiness"]["ready_for_manual_review_packet"] is False
    assert "us_equity_manual_decision_record_evidence_path_missing" in payload["blockers"]
    assert "us_equity_manual_decision_record_evidence_path_not_us_equity_report_artifact" in payload["blockers"]
    assert "us_equity_manual_decision_record_forbidden_paper_simulation_allowed" in payload["blockers"]
    assert "us_equity_manual_decision_record_forbidden_live_order_allowed" in payload["blockers"]
    assert payload["operator_decision_guidance"]["missing_evidence_paths"] == ["missing_evidence.json"]
    assert payload["operator_decision_guidance"]["non_traceable_evidence_paths"] == ["missing_evidence.json"]
    assert payload["operator_decision_guidance"]["forbidden_unlock_flags"] == [
        "paper_simulation_allowed",
        "live_order_allowed",
    ]


def test_manual_decision_record_blocks_existing_non_artifact_evidence_path(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    note = tmp_path / "docs/manual_note.json"
    note.parent.mkdir(parents=True)
    note.write_text(json.dumps({"status": "not_an_artifact"}), encoding="utf-8")
    _write_record(
        tmp_path / LOCAL_RECORD,
        evidence_paths=["docs/manual_note.json"],
    )

    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_decision_record_missing_or_invalid"
    assert "us_equity_manual_decision_record_evidence_path_not_us_equity_report_artifact" in payload["blockers"]
    assert payload["record_readiness"]["evidence_paths_missing_count"] == 0
    assert payload["evidence_path_details"][0]["exists"] is True
    assert payload["evidence_path_details"][0]["is_us_equity_artifact"] is False
    assert payload["evidence_path_details"][0]["traceable_report_artifact"] is False


def test_manual_decision_record_schema_rejects_live_unlock_guardrail(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_manual_decision_record_schema_rejects_readiness_live_unlock(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["record_readiness"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted record_readiness.live_order_allowed=true")


def test_manual_decision_record_blocks_missing_local_gitignore(tmp_path: Path) -> None:
    _write_template(tmp_path / "template.json")

    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["local_record_write_policy"]["local_record_gitignore_present"] is False
    assert "us_equity_manual_decision_local_record_not_gitignored" in payload["blockers"]


def test_manual_decision_record_schema_rejects_paper_unlock_classification(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["evidence_classification"]["manual_record_can_unlock_paper_by_itself"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted manual_record_can_unlock_paper_by_itself=true")


def test_manual_decision_record_schema_rejects_direct_paper_start_dependency(tmp_path: Path) -> None:
    _write_gitignore(tmp_path)
    _write_template(tmp_path / "template.json")
    payload = build_us_equity_manual_decision_record_report(
        repo_root=tmp_path,
        record_path=LOCAL_RECORD,
        template_path=Path("template.json"),
        output=Path("out/decision.json"),
        markdown_output=Path("out/decision.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["paper_start_dependency"]["manual_record_can_start_paper_by_itself"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted manual_record_can_start_paper_by_itself=true")


def _write_template(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "us_equity_manual_decision_record_v1",
                "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
            }
        ),
        encoding="utf-8",
    )


def _write_record(
    path: Path,
    *,
    evidence_paths: list[str],
    paper_simulation_allowed: bool = False,
    live_order_allowed: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "us_equity_manual_decision_record_v1",
                "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                "review_id": "forward_30d_manual_review",
                "reviewed_at": "2026-06-27T00:00:00Z",
                "reviewer": "manual-reviewer",
                "decision": "paper_simulation_review_candidate",
                "reason": "Evidence reviewed; paper still requires separate readiness gate.",
                "evidence_paths": evidence_paths,
                "follow_up_ticket_ids": ["ticket-1"],
                "parameter_or_strategy_id_change_required": False,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": paper_simulation_allowed,
                "live_order_allowed": live_order_allowed,
            }
        ),
        encoding="utf-8",
    )


def _write_gitignore(root: Path) -> None:
    (root / ".gitignore").write_text(
        "configs/reviews/us_equity_manual_decision_record.local.json\n",
        encoding="utf-8",
    )


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
