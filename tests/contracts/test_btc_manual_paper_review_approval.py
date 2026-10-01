from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_manual_paper_review_approval import build_btc_manual_paper_review_approval


def test_manual_review_approval_record_clears_manual_missing_only(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path)
    record = _write_record(tmp_path, packet)

    report = build_btc_manual_paper_review_approval(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )

    assert report["status"] == "recorded_research_only"
    assert report["manual_approval_recorded"] is True
    assert report["manual_review_missing_cleared"] is True
    assert report["blockers"] == []
    assert report["reviewed_packet"]["hash_method"] == "canonical_report_content_excluding_runtime_batch_fields_v1"
    assert report["reviewed_packet"]["code_commit"] == "abc123"
    assert report["approval_record"]["reviewed_source_code_commit"] == "abc123"
    assert report["approval_hash_comparison"]["canonical_hash_matches"] is True
    assert report["pending_review_only_approval_record"]["reviewed_packet_hash"]["sha256"] == "a" * 64
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["approval_does_not_unlock_paper"] is True
    assert report["guardrails"]["approval_does_not_unlock_live"] is True


def test_manual_review_approval_requires_matching_packet_hash(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path)
    record = _write_record(tmp_path, packet)
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["reviewed_packet_sha256"] = "0" * 64
    record.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_manual_paper_review_approval(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )

    assert report["manual_approval_recorded"] is False
    assert "btc_manual_paper_review_approval_packet_sha256_mismatch" in report["blockers"]
    assert report["approval_hash_comparison"]["old_approval_auto_invalidated"] is True
    assert (
        report["pending_review_only_approval_record"]["status"]
        == "pending_signature_required_current_packet_hash"
    )
    assert report["pending_review_only_approval_record"]["reviewed_packet_hash"]["sha256"] == "a" * 64
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_manual_review_approval_marks_old_code_version_review_only_stale(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path)
    record = _write_record(tmp_path, packet)
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["reviewed_source_code_commit"] = "old123"
    record.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_manual_paper_review_approval(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )

    assert report["manual_approval_recorded"] is False
    assert "btc_manual_paper_review_approval_review_only_stale_code_version" in report["blockers"]
    assert report["pending_review_only_approval_record"]["reviewed_source_code_commit"] == "abc123"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_manual_review_approval_uses_stable_hash_when_file_timestamp_changes(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path)
    record = _write_record(tmp_path, packet)
    payload = json.loads(packet.read_text(encoding="utf-8"))
    payload["generated_at_utc"] = "2026-07-06T12:34:56+00:00"
    packet.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    report = build_btc_manual_paper_review_approval(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )

    assert report["manual_approval_recorded"] is True
    assert report["blockers"] == []
    assert report["reviewed_packet"]["sha256"] == "a" * 64
    assert report["reviewed_packet"]["file_sha256"] != report["reviewed_packet"]["sha256"]


def test_manual_review_approval_accepts_nested_reviewed_packet_hash(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path)
    record = _write_record(tmp_path, packet)
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload.pop("reviewed_packet_sha256")
    payload["reviewed_packet_hash"] = {
        "schema_version": "btc_paper_candidate_packet_review_hash_v1",
        "hash_method": "canonical_report_content_excluding_runtime_batch_fields_v1",
        "sha256": "a" * 64,
        "file_sha256": "",
    }
    record.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_manual_paper_review_approval(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )

    assert report["manual_approval_recorded"] is True
    assert report["approval_record"]["reviewed_packet_hash"]["sha256"] == "a" * 64
    assert report["blockers"] == []


def test_manual_review_approval_does_not_block_on_file_hash_when_canonical_hash_matches(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path)
    record = _write_record(tmp_path, packet)
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["reviewed_packet_hash"] = {
        "schema_version": "btc_paper_candidate_packet_review_hash_v1",
        "hash_method": "canonical_report_content_excluding_runtime_batch_fields_v1",
        "sha256": "a" * 64,
        "file_sha256": "0" * 64,
    }
    record.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_manual_paper_review_approval(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )

    assert report["manual_approval_recorded"] is True
    assert report["blockers"] == []
    assert report["approval_hash_comparison"]["canonical_hash_matches"] is True
    assert report["approval_hash_comparison"]["file_hash_matches"] is False
    assert "btc_manual_paper_review_approval_packet_file_sha256_changed_non_blocking" in report["warnings"]


def test_manual_review_approval_rejects_paper_or_live_flags(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path)
    record = _write_record(tmp_path, packet)
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["paper_queue_write_allowed"] = True
    payload["live_unlock_allowed"] = True
    record.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_manual_paper_review_approval(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        generated_at_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
    )

    assert "btc_manual_paper_review_approval_paper_queue_flag_not_false" in report["blockers"]
    assert "btc_manual_paper_review_approval_live_unlock_flag_not_false" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _write_packet(root: Path) -> Path:
    packet = root / "artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(
        json.dumps(
            {
                "schema_version": "btc_paper_candidate_packet_v1",
                "code_commit": "abc123",
                "status": "complete_research_only",
                "generated_at_utc": "2026-07-06T00:00:00+00:00",
                "decision": "btc_paper_candidate_packet_not_ready_no_paper_queue_write_no_live",
                "aggregation_batch_id": "batch",
                "paper_candidate_packet": {"packet_status": "not_ready"},
                "reviewed_packet_hash": {
                    "schema_version": "btc_paper_candidate_packet_review_hash_v1",
                    "hash_method": "canonical_report_content_excluding_runtime_batch_fields_v1",
                    "sha256": "a" * 64,
                },
                "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return packet


def _write_record(root: Path, packet: Path) -> Path:
    record = root / "configs/btc/paper_runtime/manual_paper_review_approval.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        json.dumps(
            {
                "schema_version": "btc_manual_paper_review_approval_record_v1",
                "reviewer": "human_operator",
                "decision_date_utc": "2026-07-06T00:00:00Z",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "expiry_utc": "2026-07-20T00:00:00Z",
                "reviewed_artifacts": [str(packet).replace("\\", "/")],
                "reviewed_packet_path": str(packet).replace("\\", "/"),
                "reviewed_packet_sha256": "a" * 64,
                "reviewed_source_code_commit": "abc123",
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approve_review_only_no_auto_paper_no_live": True,
                "paper_queue_write_allowed": False,
                "paper_order_intake_allowed": False,
                "live_unlock_allowed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return record
