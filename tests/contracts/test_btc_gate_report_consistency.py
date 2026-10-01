from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_crypto.monitoring.btc_gate_report_consistency import build_btc_gate_report_consistency
from quant_crypto.monitoring.btc_root_cause_dag import classify_btc_blocker_root_cause
from quant_crypto.application.btc_gate_snapshot import resolve_latest_gate_artifact


MANUAL_APPROVAL = Path(
    "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
)
PAPER_CANDIDATE_PACKET = Path("artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json")
PAPER_READINESS = Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json")
GATE_DASHBOARD = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
PERPETUAL_EXECUTION_EVIDENCE = Path(
    "artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"
)
PROMOTION_GATE_CONTROL = Path(
    "artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"
)


def test_btc_gate_report_consistency_passes_when_dashboard_embeds_current_evidence_hash(tmp_path: Path) -> None:
    evidence = {
        "status": "incomplete_research_only",
        "blockers": ["depth_wait"],
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }
    dashboard = {
        "status": "blocked",
        "artifacts": {
            "perpetual_execution_evidence": {
                "status": evidence["status"],
                "artifact_hash": stable_payload_hash(evidence),
            }
        },
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }
    dashboard_path = _write_json(tmp_path / "dashboard.json", dashboard)
    evidence_path = _write_json(tmp_path / "evidence.json", evidence)

    report = build_btc_gate_report_consistency(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        gate_dashboard_path=dashboard_path,
        perpetual_execution_evidence_path=evidence_path,
    )

    assert report["status"] == "pass"
    assert report["blockers"] == []
    assert report["summary"]["dashboard_hash_matches_current_evidence"] is True
    assert report["source_fingerprints"]["gate_dashboard"]["stable_hash"] == stable_payload_hash(dashboard)
    assert report["source_fingerprints"]["perpetual_execution_evidence"]["stable_hash"] == stable_payload_hash(evidence)
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_gate_report_consistency_fails_closed_on_dashboard_evidence_hash_mismatch(tmp_path: Path) -> None:
    evidence_path = _write_json(tmp_path / "evidence.json", {"status": "complete_research_only", "blockers": []})
    dashboard_path = _write_json(
        tmp_path / "dashboard.json",
        {
            "status": "blocked",
            "artifacts": {
                "perpetual_execution_evidence": {
                    "status": "complete_research_only",
                    "artifact_hash": "0" * 64,
                }
            },
        },
    )

    report = build_btc_gate_report_consistency(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        gate_dashboard_path=dashboard_path,
        perpetual_execution_evidence_path=evidence_path,
    )

    assert report["status"] == "blocked_research_only"
    assert "btc_gate_report_consistency:dashboard_perpetual_execution_evidence_hash_matches_current_artifact" in report["blockers"]
    assert report["summary"]["dashboard_hash_matches_current_evidence"] is False
    assert classify_btc_blocker_root_cause(report["blockers"][-1]) == "artifact_consistency_mismatch"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_btc_latest_artifacts_keep_dashboard_evidence_hash_and_root_causes_current() -> None:
    dashboard = _read_current(GATE_DASHBOARD)
    evidence = _read_current(PERPETUAL_EXECUTION_EVIDENCE)
    consistency = _read_current(Path("artifacts/btc_gate_report_consistency/latest/btc_gate_report_consistency_report.json"))
    promotion = _read_current(PROMOTION_GATE_CONTROL)

    dashboard_hash = str(
        _mapping(_mapping(dashboard.get("artifacts")).get("perpetual_execution_evidence")).get("artifact_hash")
        or ""
    )
    expected_hash = str(evidence.get("artifact_hash") or stable_payload_hash(evidence))

    assert dashboard_hash
    assert dashboard_hash == expected_hash
    for fingerprint in _mapping(consistency.get("source_fingerprints")).values():
        if isinstance(fingerprint, Mapping):
            _assert_fingerprint_matches_current_file(fingerprint)

    root_ids = _root_ids(promotion)
    assert "uncategorized_blocker" not in root_ids
    immediate_items = _list_of_mappings(_mapping(promotion.get("root_cause_task_queue")).get("immediate_development_items"))
    for item in immediate_items:
        assert item.get("root_cause_id") != "uncategorized_blocker"
        assert item.get("owner")
        assert item.get("next_command")
        assert item.get("acceptance_criteria")

    if promotion.get("required_rebuild_reports") == []:
        freshness = _mapping(promotion.get("artifact_freshness"))
        assert freshness.get("dependency_newer_than_consumer_count") == 0
        for row in _list_of_mappings(freshness.get("sources")):
            assert row.get("blockers") in ([], None)
            _assert_fingerprint_matches_current_file(
                {
                    "path": row.get("path"),
                    "stable_hash": row.get("source_file_stable_hash"),
                    "file_mtime_ns": row.get("source_file_mtime_ns"),
                    "file_size_bytes": row.get("source_file_size_bytes"),
                }
            )
            if row.get("commit_policy") == "source_code_commit_must_match_current_head":
                assert row.get("source_code_commit_matches_current_head") is not False


def test_btc_gate_reports_mark_current_packet_approval_review_only_without_unlocking() -> None:
    manual = _read_current(MANUAL_APPROVAL)
    packet = _read_current(PAPER_CANDIDATE_PACKET)
    readiness = _read_current(PAPER_READINESS)

    packet_hash = str(_mapping(packet.get("reviewed_packet_hash")).get("sha256") or "")
    record_hash = str(
        _mapping(_mapping(manual.get("approval_record")).get("reviewed_packet_hash")).get("sha256")
        or manual.get("reviewed_packet_sha256")
        or ""
    )

    assert packet_hash
    assert packet["code_commit"] == packet["current_head_code_commit"]
    assert packet["source_code_commit_current_head_match"] is True
    reviewer = _mapping(_mapping(packet.get("paper_candidate_packet")).get("reviewer"))
    approved_review = _mapping(readiness.get("approved_paper_review"))
    assert readiness["paper_start_allowed"] is False
    assert readiness["paper_execution_authorized"] is False
    if manual["status"] == "recorded_research_only":
        assert manual["manual_approval_recorded"] is True
        assert manual["manual_review_missing_cleared"] is True
        assert manual["blockers"] == []
        assert record_hash == packet_hash
        assert _mapping(manual.get("approval_hash_comparison")).get("canonical_hash_matches") is True
        assert reviewer["status"] == "recorded_review_only"
        assert reviewer["review_record_current_and_hash_valid"] is True
        assert reviewer["reviewer_id"] == "李烁"
        assert readiness["paper_queue_status"] == "current_packet_review_only_approved_promotion_blocked"
        assert approved_review.get("approved") is True
        assert _mapping(approved_review.get("approval")).get("valid") is True
        assert _mapping(approved_review.get("approval")).get("source_sha256") == packet_hash
    else:
        assert manual["status"] == "missing_or_invalid_research_only"
        assert manual["manual_approval_recorded"] is False
        assert "btc_manual_paper_review_approval_packet_sha256_mismatch" in manual["blockers"]
        if readiness["status"] == "blocked":
            assert readiness["paper_queue_status"] == "locked"
            manual_input_gate = _mapping(_mapping(readiness.get("requirements")).get("manual_input_gate"))
            if manual_input_gate.get("status") == "complete":
                assert readiness["manual_inputs_status"] == "manual_inputs_verified"
                assert "btc_paper_readiness_manual_inputs_incomplete" not in readiness["blockers"]
            else:
                assert "btc_paper_readiness_manual_inputs_incomplete" in readiness["blockers"]
            assert "btc_paper_readiness_approved_paper_review_missing" in readiness["blockers"]
            assert "btc_paper_readiness_current_packet_unapproved" in readiness["blockers"]
        else:
            assert readiness["paper_queue_status"] == "current_packet_unapproved"
        assert approved_review.get("approved") is not True


def test_btc_dashboard_displays_promotion_gate_root_cause_queue() -> None:
    dashboard = _read_current(GATE_DASHBOARD)
    promotion = _read_current(PROMOTION_GATE_CONTROL)

    dashboard_ids = _root_ids(dashboard)
    promotion_ids = _root_ids(promotion)

    assert dashboard["root_cause_source"] == "promotion_gate_control"
    assert dashboard_ids == promotion_ids
    assert "uncategorized_blocker" not in dashboard_ids
    assert "runtime_ready_waiting_non_flat_sample" in dashboard_ids
    assert dashboard["root_cause_task_queue"]["dashboard_should_show_root_causes_only"] is True


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_current(logical_path: Path) -> dict[str, Any]:
    resolution = resolve_latest_gate_artifact(Path.cwd(), logical_path)
    assert resolution.path is not None, resolution.error
    return _read_json(resolution.path)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _root_ids(report: Mapping[str, Any]) -> set[str]:
    return {str(row.get("root_cause_id")) for row in report.get("root_cause_matrix", []) if isinstance(row, Mapping)}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _assert_fingerprint_matches_current_file(fingerprint: Mapping[str, Any]) -> None:
    path_text = str(fingerprint.get("path") or "")
    assert path_text
    resolution = resolve_latest_gate_artifact(Path.cwd(), Path(path_text))
    assert resolution.path is not None, resolution.error
    path = resolution.path
    assert path.exists()
    payload = _read_json(path)
    assert fingerprint.get("stable_hash") == stable_payload_hash(payload)
    assert fingerprint.get("file_size_bytes") == path.stat().st_size
    assert fingerprint.get("file_mtime_ns") == path.stat().st_mtime_ns
