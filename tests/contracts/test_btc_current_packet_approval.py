from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_current_packet_approval import build_btc_current_packet_approval_signer_report


TS = datetime(2026, 7, 6, tzinfo=timezone.utc)


def test_current_packet_approval_signer_writes_only_current_packet_hash_without_unlocking(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path, "a" * 64)
    record = _write_old_record(tmp_path, "8" * 64)

    report = build_btc_current_packet_approval_signer_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        reviewer="human_operator",
        decision_date_utc=TS,
        expiry_days=14,
        write_record=True,
        generated_at_utc=TS,
    )

    assert report["status"] == "recorded_current_research_only"
    assert report["previous_record_auto_invalidated"] is True
    assert report["current_packet_reviewed_hash_sha256"] == "a" * 64
    assert report["manual_approval_validation"]["manual_approval_recorded"] is True
    assert report["manual_approval_validation"]["blockers"] == []
    assert report["post_approval_gate"]["status"] == "manual_review_recorded_but_promotion_gates_still_required"
    assert report["post_approval_gate"]["clears_only"] == ["manual_review_approval_missing"]
    assert "runtime_current_non_flat_sample_gate" in report["post_approval_gate"]["does_not_clear"]
    assert report["post_approval_gate"]["paper_queue_write_allowed"] is False
    assert report["post_approval_gate"]["live_unlock_allowed"] is False
    written = json.loads(record.read_text(encoding="utf-8"))
    assert written["reviewed_packet_hash"]["sha256"] == "a" * 64
    assert written["reviewed_packet_sha256"] == "a" * 64
    assert written["reviewed_source_code_commit"] == "abc123"
    assert written["paper_queue_write_allowed"] is False
    assert written["paper_order_intake_allowed"] is False
    assert written["live_unlock_allowed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_current_packet_approval_checker_dry_run_does_not_overwrite_old_record(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path, "a" * 64)
    record = _write_old_record(tmp_path, "8" * 64)

    report = build_btc_current_packet_approval_signer_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        reviewer="human_operator",
        write_record=False,
        generated_at_utc=TS,
    )

    assert report["status"] == "pending_or_invalid_research_only"
    assert "btc_manual_paper_review_approval_packet_sha256_mismatch" in report["blockers"]
    written = json.loads(record.read_text(encoding="utf-8"))
    assert written["reviewed_packet_sha256"] == "8" * 64
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_current_packet_approval_missing_reviewer_does_not_overwrite_even_when_write_requested(tmp_path: Path) -> None:
    packet = _write_packet(tmp_path, "a" * 64)
    record = _write_old_record(tmp_path, "8" * 64)
    before = json.loads(record.read_text(encoding="utf-8"))

    report = build_btc_current_packet_approval_signer_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        approval_record_path=record,
        reviewed_packet_path=packet,
        reviewer="   ",
        write_record=True,
        generated_at_utc=TS,
    )

    assert report["status"] == "pending_or_invalid_research_only"
    assert "btc_current_packet_approval_reviewer_missing" in report["blockers"]
    assert "btc_manual_paper_review_approval_packet_sha256_mismatch" in report["blockers"]
    assert report["post_approval_gate"]["status"] == "manual_review_not_current_or_not_recorded"
    assert report["post_approval_gate"]["clears_only"] == []
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    after = json.loads(record.read_text(encoding="utf-8"))
    assert after == before


def _write_packet(root: Path, sha256: str) -> Path:
    path = root / "artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_paper_candidate_packet_v1",
                "code_commit": "abc123",
                "status": "complete_research_only",
                "decision": "btc_paper_candidate_packet_not_ready_no_paper_queue_write_no_live",
                "reviewed_packet_hash": {
                    "schema_version": "btc_paper_candidate_packet_review_hash_v1",
                    "hash_method": "canonical_report_content_excluding_runtime_batch_fields_v1",
                    "sha256": sha256,
                    "file_sha256": "f" * 64,
                },
                "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_old_record(root: Path, sha256: str) -> Path:
    path = root / "configs/btc/paper_runtime/manual_paper_review_approval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_manual_paper_review_approval_record_v1",
                "reviewer": "old_operator",
                "decision_date_utc": "2026-07-05T00:00:00Z",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "expiry_utc": "2026-07-20T00:00:00Z",
                "reviewed_artifacts": ["artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"],
                "reviewed_packet_path": "artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json",
                "reviewed_packet_sha256": sha256,
                "decision": "approve_review_only_no_auto_paper_no_live",
                "approve_review_only_no_auto_paper_no_live": True,
                "paper_queue_write_allowed": False,
                "paper_order_intake_allowed": False,
                "live_unlock_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    return path
