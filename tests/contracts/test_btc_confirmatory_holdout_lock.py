from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_crypto.research import btc_confirmatory_holdout_lock as lock


def test_confirmatory_holdout_lock_writes_config_and_stays_research_only(tmp_path: Path) -> None:
    long_short_report = tmp_path / "long_short_top5.json"
    high_octane_report = tmp_path / "high_octane.json"
    bar_replay_report = tmp_path / "bar_replay.json"
    lock_config_path = tmp_path / "locks.json"
    _write_json(long_short_report, _long_short_report())
    _write_json(high_octane_report, _high_octane_report())
    _write_json(bar_replay_report, _bar_replay_report())

    report = lock.build_btc_confirmatory_holdout_lock(
        output_dir=tmp_path / "out",
        lock_config_path=lock_config_path,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        long_short_top5_report_path=long_short_report,
        high_octane_report_path=high_octane_report,
        bar_replay_report_path=bar_replay_report,
    )

    assert report["schema_version"] == "btc_confirmatory_holdout_lock_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_confirmatory_holdout_locked_research_only_no_paper_no_live"
    assert report["summary"]["lock_count"] == 3
    assert report["summary"]["historical_seen_lock_count"] == 2
    assert report["summary"]["future_observe_only_lock_count"] == 1
    assert report["summary"]["latest_common_history_end"] == "2026-06-28T23:59:59.999000+00:00"
    assert report["summary"]["self_check_violation_count"] >= 3
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    written = json.loads(lock_config_path.read_text(encoding="utf-8"))
    assert written["schema_version"] == "btc_confirmatory_holdout_lock_config_v1"
    assert written["lock_config_hash"] == report["lock_config"]["lock_config_hash"]
    assert written["global_policy"]["parameter_search_requires_no_overlap_with_forbidden_locked_windows"] is True
    assert written["global_policy"]["paper_queue_write_allowed"] is False
    assert written["global_policy"]["live_unlock_allowed"] is False

    for name in [
        "btc_confirmatory_holdout_lock_report.json",
        "btc_confirmatory_holdout_lock_windows.csv",
        "btc_confirmatory_holdout_lock_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()


def test_selection_window_violations_block_parameter_search_but_allow_audit_replay(tmp_path: Path) -> None:
    config = _build_config(tmp_path)

    violations = lock.selection_window_violations(
        config,
        selection_start="2026-01-01T00:00:00+00:00",
        selection_end="2026-02-01T00:00:00+00:00",
        purpose="parameter_search",
    )

    assert violations
    assert {row["severity"] for row in violations} == {"fail"}
    assert any(row["lock_id"] == "btc_ls_top5_historical_confirmation_holdout_v1" for row in violations)

    allowed = lock.selection_window_violations(
        config,
        selection_start="2026-01-01T00:00:00+00:00",
        selection_end="2026-02-01T00:00:00+00:00",
        purpose="audit_replay",
    )
    assert allowed == []


def test_forward_observe_only_window_blocks_future_tuning(tmp_path: Path) -> None:
    config = _build_config(tmp_path)

    violations = lock.selection_window_violations(
        config,
        selection_start="2026-07-02T00:00:00+00:00",
        selection_end="2026-07-15T00:00:00+00:00",
        purpose="threshold_tuning",
    )

    assert any(row["lock_id"] == "btc_post_20260628_forward_observe_only_v1" for row in violations)


def test_selection_window_rejects_reversed_dates(tmp_path: Path) -> None:
    config = _build_config(tmp_path)

    with pytest.raises(ValueError):
        lock.selection_window_violations(
            config,
            selection_start="2026-02-01T00:00:00+00:00",
            selection_end="2026-01-01T00:00:00+00:00",
            purpose="parameter_search",
        )


def _build_config(tmp_path: Path) -> dict:
    long_short_report = tmp_path / "long_short_top5.json"
    high_octane_report = tmp_path / "high_octane.json"
    bar_replay_report = tmp_path / "bar_replay.json"
    _write_json(long_short_report, _long_short_report())
    _write_json(high_octane_report, _high_octane_report())
    _write_json(bar_replay_report, _bar_replay_report())
    report = lock.build_btc_confirmatory_holdout_lock(
        output_dir=tmp_path / "out",
        lock_config_path=tmp_path / "locks.json",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        long_short_top5_report_path=long_short_report,
        high_octane_report_path=high_octane_report,
        bar_replay_report_path=bar_replay_report,
    )
    return report["lock_config"]


def _long_short_report() -> dict:
    return {
        "status": "complete_research_only",
        "code_commit": "lscommit",
        "review_design": {
            "clean_pre_selection_holdout": False,
            "clean_pre_selection_holdout_note": "post-selection confirmation stress",
        },
        "candidate_reviews": [
            {
                "candidate_id": "ls_top",
                "confirmation_holdout": {
                    "start": "2025-12-29T03:59:59.999000+00:00",
                    "end": "2026-06-28T23:59:59.999000+00:00",
                    "row_count": 1092,
                },
            }
        ],
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }


def _high_octane_report() -> dict:
    return {
        "status": "complete_research_only",
        "code_commit": "hocommit",
        "input": {
            "market_4h_start": "2024-01-01T03:59:59.999000+00:00",
            "market_4h_end": "2026-06-28T23:59:59.999000+00:00",
            "market_4h_rows": 5460,
        },
        "summary": {"best_scenario_id": "ho_top"},
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }


def _bar_replay_report() -> dict:
    return {
        "status": "complete_research_only",
        "code_commit": "brcommit",
        "decision": "research_only_bar_replay_passed_for_long_short_high_octane_requires_execution_replay_no_paper_no_live",
        "summary": {"check_fail_count": 0},
        "long_short_top5_bar_replay": {
            "market_start": "2024-01-01T03:59:59.999000+00:00",
            "market_end": "2026-06-28T23:59:59.999000+00:00",
            "market_4h_row_count": 5460,
        },
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
