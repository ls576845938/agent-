from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.monitoring.btc_dirty_worktree_boundary import build_btc_dirty_worktree_boundary_report


def test_btc_dirty_worktree_boundary_groups_status_lines_without_unlocking(tmp_path: Path) -> None:
    (tmp_path / "configs/btc/paper_runtime").mkdir(parents=True)
    (tmp_path / "configs/btc/paper_runtime/account_runtime_attestation.template.json").write_text(
        json.dumps({"api_key_name": "REDACTED", "passphrase": "REDACTED"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "configs/btc/paper_runtime/account_runtime_attestation.json").write_text(
        json.dumps({"api_key_name": "local-paper-key", "passphrase": "REDACTED"}, ensure_ascii=False),
        encoding="utf-8",
    )
    report = build_btc_dirty_worktree_boundary_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
        status_lines=[
            " M quant_crypto/research/btc_perpetual_paper_runtime_replay.py",
            " M quant_crypto/security/api_key_audit.py",
            " M quant_crypto/research/btc_promotion_gate_control.py",
            "?? frontend/src/workspaces/crypto/BtcControlCenter.tsx",
            "?? quant_crypto/research/high_octane_10u_discipline_overlay_lab.py",
            " M artifacts/btc_cost_model/latest/btc_cost_model_report.json",
            " M data/market_data.sqlite",
            " M data/paper_ledger/audit/paper_broker_state_recovery.json",
            " M data/external/btc_perpetual/okx_swap/liquidation_snapshots/okx_liquidation_orders_observe_only.csv",
            " M configs/btc/paper_runtime/account_runtime_attestation.template.json",
            "?? configs/btc/paper_runtime/account_runtime_attestation.json",
        ],
    )

    groups = {row["group_id"]: row for row in report["groups"]}
    assert report["schema_version"] == "btc_dirty_worktree_boundary_v1"
    assert report["status"] == "dirty_worktree_present"
    assert groups["runtime_replay"]["file_count"] == 1
    assert groups["security_attestation"]["file_count"] == 3
    assert groups["gate_root_cause"]["file_count"] == 1
    assert groups["frontend_control_center"]["file_count"] == 1
    assert groups["research_labs"]["file_count"] == 1
    assert groups["generated_artifacts_data"]["file_count"] == 4
    assert groups["security_attestation"]["never_commit_count"] == 1
    assert groups["generated_artifacts_data"]["never_commit_count"] == 3
    assert report["review_boundary_policy"]["split_commits_by_review_group"] is True
    assert report["review_boundary_policy"]["real_local_attestation_never_committed"] is True
    assert report["dirty_state_summary"]["never_commit_count"] == 4
    assert "data/market_data.sqlite" in report["dirty_state_summary"]["never_commit_paths"]
    assert "data/paper_ledger/audit/paper_broker_state_recovery.json" in report["dirty_state_summary"]["never_commit_paths"]
    assert (
        "data/external/btc_perpetual/okx_swap/liquidation_snapshots/okx_liquidation_orders_observe_only.csv"
        in report["dirty_state_summary"]["never_commit_paths"]
    )
    assert report["dirty_state_summary"]["only_generated_or_never_commit_dirty"] is False
    assert any(row["commit_boundary"] == "committable_redacted_template" for row in report["files"])
    assert any(row["commit_boundary"] == "never_commit" for row in report["files"])
    assert report["secret_scan"]["secret_like_field_count"] >= 3
    assert report["secret_scan"]["unredacted_secret_like_count"] == 1
    local_row = next(row for row in report["files"] if row["path"].endswith("account_runtime_attestation.json"))
    assert local_row["commit_policy"] == "do_not_commit_real_local_secret_or_data"
    assert local_row["secret_scan"]["secret_like_fields"][0]["value_disclosed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert (tmp_path / "out/btc_dirty_worktree_boundary_report.json").exists()
    assert (tmp_path / "out/btc_dirty_worktree_boundary_files.csv").exists()
    safety = json.loads((tmp_path / "out/paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["file_revert_used"] is False
    assert safety["git_commit_created"] is False
    assert safety["redaction_boundary_passed"] is False


def test_btc_dirty_worktree_boundary_marks_generated_and_local_data_only(tmp_path: Path) -> None:
    report = build_btc_dirty_worktree_boundary_report(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
        status_lines=[
            " M artifacts/btc_cost_model/latest/btc_cost_model_report.json",
            " M data/market_data.sqlite",
            " M data/paper_ledger/audit/paper_broker_state_recovery.json",
            " M data/external/btc_perpetual/okx_swap/liquidation_snapshots/okx_liquidation_orders_observe_only.csv",
        ],
    )

    summary = report["dirty_state_summary"]
    assert summary["committable_source_or_test_count"] == 0
    assert summary["generated_artifact_count"] == 1
    assert summary["never_commit_count"] == 3
    assert summary["only_generated_or_never_commit_dirty"] is True
    assert "data/market_data.sqlite" in summary["never_commit_paths"]
