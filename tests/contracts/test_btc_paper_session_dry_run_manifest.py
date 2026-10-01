from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_paper_session_dry_run_manifest import (
    DEFAULT_PATHS,
    build_btc_paper_session_dry_run_manifest,
)


TS = datetime(2026, 7, 6, 12, tzinfo=timezone.utc)


def test_paper_session_dry_run_manifest_passes_only_checklist_without_unlocking(tmp_path: Path) -> None:
    _write_all_sources(tmp_path)

    report = build_btc_paper_session_dry_run_manifest(repo_root=tmp_path, output_dir=tmp_path / "out", generated_at_utc=TS)

    assert report["status"] == "dry_run_checklist_passed_research_only"
    assert report["paper_start_checklist_passed"] is True
    assert report["start_command_enabled"] is False
    assert report["start_command"] == ""
    assert report["ledger_output_manifest"]["order_ledger_path"].endswith("/order_ledger.csv")
    assert report["rollback_steps"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_order_intake_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False
    assert report["blockers"] == []


def test_paper_session_manifest_missing_kill_switch_blocks_fail_closed(tmp_path: Path) -> None:
    _write_all_sources(tmp_path, skip={"kill_switch"})

    report = build_btc_paper_session_dry_run_manifest(repo_root=tmp_path, output_dir=tmp_path / "out", generated_at_utc=TS)

    assert report["status"] == "blocked_fail_closed_research_only"
    assert "paper_session_manifest:kill_switch:source_artifact_missing" in report["blockers"]
    assert "paper_session_manifest_kill_switch_not_clear" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_paper_session_manifest_stale_account_attestation_blocks(tmp_path: Path) -> None:
    _write_all_sources(tmp_path)
    _write_json(
        _path(tmp_path, "account_attestation"),
        {
            "generated_at_utc": "2026-07-05T00:00:00+00:00",
            "status": "complete_research_only",
            "attestation_current": True,
            "credential_permissions_verified": True,
            "credential_separation_verified": True,
            "blockers": [],
        },
    )

    report = build_btc_paper_session_dry_run_manifest(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        generated_at_utc=TS,
        freshness_sla_hours=24.0,
    )

    assert "paper_session_manifest:account_attestation:source_artifact_stale_age_hours_gt_sla" in report["blockers"]
    assert report["paper_start_checklist_passed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False


def test_paper_session_manifest_dirty_worktree_blocks_even_when_other_gates_pass(tmp_path: Path) -> None:
    _write_all_sources(tmp_path)
    _write_json(
        _path(tmp_path, "dirty_worktree_boundary"),
        {
            "generated_at_utc": "2026-07-06T12:00:00+00:00",
            "status": "dirty_worktree_present",
            "blockers": [],
        },
    )

    report = build_btc_paper_session_dry_run_manifest(repo_root=tmp_path, output_dir=tmp_path / "out", generated_at_utc=TS)

    assert report["status"] == "blocked_fail_closed_research_only"
    assert "paper_session_manifest_dirty_worktree_not_clean" in report["blockers"]
    assert report["operator_summary"]["first_failed_check"] == "dirty_worktree_clean_or_reviewed"
    assert report["gate"]["paper_queue_write_allowed"] is False


def _write_all_sources(root: Path, *, skip: set[str] | None = None) -> None:
    skip = skip or set()
    if "paper_candidate_packet" not in skip:
        _write_json(_path(root, "paper_candidate_packet"), _base({"gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False}}))
    if "manual_paper_review_approval" not in skip:
        _write_json(
            _path(root, "manual_paper_review_approval"),
            _base(
                {
                    "manual_approval_recorded": True,
                    "manual_review_missing_cleared": True,
                    "paper_queue_write_allowed": False,
                    "live_unlock_allowed": False,
                    "blockers": [],
                }
            ),
        )
    if "paper_readiness" not in skip:
        _write_json(
            _path(root, "paper_readiness"),
            _base(
                {
                    "status": "ready_for_paper_start",
                    "paper_start_allowed": True,
                    "paper_execution_authorized": True,
                    "blockers": [],
                }
            ),
        )
    if "promotion_gate_control" not in skip:
        _write_json(_path(root, "promotion_gate_control"), _base({"status": "complete_research_only", "blockers": []}))
    if "kill_switch" not in skip:
        _write_json(_path(root, "kill_switch"), _base({"status": "complete_research_only", "engaged": False, "blockers": []}))
    if "runtime_replay" not in skip:
        _write_json(
            _path(root, "runtime_replay"),
            _base(
                {
                    "summary": {
                        "paper_runtime_gate_evidence": True,
                        "gate_eligible_current_capture_count": 1,
                    },
                    "blockers": [],
                }
            ),
        )
    if "account_attestation" not in skip:
        _write_json(
            _path(root, "account_attestation"),
            _base(
                {
                    "attestation_current": True,
                    "credential_permissions_verified": True,
                    "credential_separation_verified": True,
                    "blockers": [],
                }
            ),
        )
    if "dirty_worktree_boundary" not in skip:
        _write_json(_path(root, "dirty_worktree_boundary"), _base({"status": "clean_worktree", "blockers": []}))
    if "gate_report_consistency" not in skip:
        _write_json(_path(root, "gate_report_consistency"), _base({"source_timeline_consistent": True, "blockers": []}))


def _base(overrides: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at_utc": "2026-07-06T12:00:00+00:00",
        "status": "complete_research_only",
        "decision": "fixture",
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def _path(root: Path, key: str) -> Path:
    return root / DEFAULT_PATHS[key]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
