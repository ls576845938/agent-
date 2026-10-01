from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_freqtrade_style_leakage_cli import build_btc_freqtrade_style_leakage_cli


def test_freqtrade_style_leakage_cli_aggregates_fixed_checks_research_only(tmp_path: Path) -> None:
    repo_root, external_root, leakage_report, bar_replay_report = _make_workspace(tmp_path)

    report = build_btc_freqtrade_style_leakage_cli(
        repo_root=repo_root,
        external_references_root=external_root,
        leakage_report_path=leakage_report,
        bar_replay_report_path=bar_replay_report,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_freqtrade_style_leakage_cli_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_freqtrade_style_leakage_cli_research_only_warnings_no_paper_no_live"
    assert report["freqtrade_reference"]["license_id"] == "GPL-3.0"
    assert report["freqtrade_reference"]["source_code_copied"] is False
    assert report["command_semantics"]["source_code_copied"] is False
    assert report["command_semantics"]["aggregates_existing_artifacts_only"] is True
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False
    assert report["gate"]["third_party_runtime_dependency_added"] is False

    categories = {row["category"]: row for row in report["checklist"]}
    assert set(categories) == {
        "future_function_visibility",
        "future_sentiment_available_time",
        "same_bar_execution_boundary",
        "recursive_stateful_overlay_boundary",
        "parameter_mining_boundary",
        "return_concentration_and_path_dependency",
        "holdout_forward_window",
        "rolling_window_no_full_sample_normalization",
        "ga_timesfm_rule_boundary",
    }
    assert categories["future_function_visibility"]["status"] == "pass"
    assert categories["future_sentiment_available_time"]["status"] == "pass"
    assert categories["same_bar_execution_boundary"]["status"] == "warn"
    assert categories["parameter_mining_boundary"]["status"] == "warn"
    assert all(row["paper_gate_credit"] is False for row in report["checklist"])
    assert report["summary"]["check_count"] == 9
    assert report["summary"]["fail_count"] == 0
    assert report["summary"]["warn_count"] >= 1


def test_freqtrade_style_leakage_cli_writes_outputs_and_chinese_summary(tmp_path: Path) -> None:
    repo_root, external_root, leakage_report, bar_replay_report = _make_workspace(tmp_path)

    report = build_btc_freqtrade_style_leakage_cli(
        repo_root=repo_root,
        external_references_root=external_root,
        leakage_report_path=leakage_report,
        bar_replay_report_path=bar_replay_report,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    json_path = repo_root / report["outputs"]["json"]
    csv_path = repo_root / report["outputs"]["checklist_csv"]
    markdown_path = repo_root / report["outputs"]["summary_cn"]
    safety_path = repo_root / report["outputs"]["paper_live_safety_status"]
    assert json_path.exists()
    assert csv_path.exists()
    assert markdown_path.exists()
    assert safety_path.exists()
    summary = markdown_path.read_text(encoding="utf-8")
    assert "lookahead" in summary
    assert "recursive" in summary
    assert "未来函数" in summary
    assert "不写 paper 队列" in summary
    assert "不解锁 live" in summary
    assert "未复制其源码" in summary
    safety = json.loads(safety_path.read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_or_order_allowed"] is False


def test_freqtrade_style_leakage_cli_fail_closed_when_source_missing(tmp_path: Path) -> None:
    repo_root, external_root, leakage_report, bar_replay_report = _make_workspace(tmp_path)
    leakage_report.unlink()

    report = build_btc_freqtrade_style_leakage_cli(
        repo_root=repo_root,
        external_references_root=external_root,
        leakage_report_path=leakage_report,
        bar_replay_report_path=bar_replay_report,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked_research_only"
    assert report["decision"] == "btc_freqtrade_style_leakage_cli_blocked_missing_inputs_no_paper_no_live"
    assert "source_missing:btc_strategy_leakage_overfit_audit_report" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["checklist"][0]["status"] == "blocked"


def test_freqtrade_style_leakage_cli_flags_future_sentiment_violation(tmp_path: Path) -> None:
    repo_root, external_root, leakage_report, bar_replay_report = _make_workspace(tmp_path)
    payload = json.loads(bar_replay_report.read_text(encoding="utf-8"))
    payload["summary"]["long_short_future_sentiment_violation_count"] = 1
    bar_replay_report.write_text(json.dumps(payload), encoding="utf-8")

    report = build_btc_freqtrade_style_leakage_cli(
        repo_root=repo_root,
        external_references_root=external_root,
        leakage_report_path=leakage_report,
        bar_replay_report_path=bar_replay_report,
        generated_at_utc=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )

    by_category = {row["category"]: row for row in report["checklist"]}
    assert by_category["future_sentiment_available_time"]["status"] == "fail"
    assert report["decision"] == "btc_freqtrade_style_leakage_cli_fail_closed_no_paper_no_live"
    assert report["summary"]["lookahead_or_future_function_fail_count"] == 1
    assert report["gate"]["paper_queue_write_allowed"] is False


def _make_workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo_root = tmp_path / "agent-"
    external_root = tmp_path / "external_references"
    leakage_report = repo_root / "artifacts/btc_strategy_leakage_overfit_audit/latest/btc_strategy_leakage_overfit_audit_report.json"
    bar_replay_report = repo_root / "artifacts/btc_strategy_bar_replay_visibility/latest/btc_strategy_bar_replay_visibility_report.json"
    leakage_report.parent.mkdir(parents=True)
    bar_replay_report.parent.mkdir(parents=True)
    (external_root / "freqtrade/.git/refs/heads").mkdir(parents=True)
    (external_root / "freqtrade/.git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (external_root / "freqtrade/.git/refs/heads/main").write_text("0a5bbf61234567890", encoding="utf-8")
    (external_root / "freqtrade/README.md").write_text(
        "Freqtrade lookahead-analysis recursive-analysis",
        encoding="utf-8",
    )
    leakage_report.write_text(json.dumps(_leakage_payload()), encoding="utf-8")
    bar_replay_report.write_text(json.dumps(_bar_replay_payload()), encoding="utf-8")
    return repo_root, external_root, leakage_report, bar_replay_report


def _leakage_payload() -> dict:
    return {
        "status": "complete_research_only",
        "decision": "research_only_overfit_risk_high_no_paper_no_live",
        "generated_at": "2026-07-08T00:00:00+00:00",
        "artifact_hash": "a" * 64,
        "summary": {
            "check_fail_count": 0,
            "check_warn_count": 4,
            "long_short_future_sentiment_violation_count": 0,
            "high_octane_future_sentiment_violation_count": 0,
            "long_short_return_concentration_verdict": "trend_return_concentration_requires_forward_confirmation",
            "high_octane_return_dependency_verdict": "path_dependency_requires_rolling_start_review",
            "high_octane_parameter_mining_verdict": "strong_parameter_mining_symptoms_threshold_boundary_research_only",
            "high_octane_likely_parameter_mined_boundary_candidate": True,
            "high_octane_best_margin_over_40pct_threshold": 0.011869,
            "high_octane_capital_overlay_execution_boundary_verdict": "same_bar_execution_proxy_requires_strict_risk_stress_and_mark_index_replay",
            "forward_observe_clean_confirmation_ready": False,
            "forward_observe_only_anchor_rows_so_far": True,
        },
    }


def _bar_replay_payload() -> dict:
    return {
        "status": "complete_research_only",
        "decision": "research_only_bar_replay_passed_no_paper_no_live",
        "generated_at": "2026-07-08T00:00:00+00:00",
        "artifact_hash": "b" * 64,
        "summary": {
            "long_short_shift_violation_count": 0,
            "long_short_completed_bar_violation_count": 0,
            "long_short_future_sentiment_violation_count": 0,
            "high_octane_future_sentiment_violation_count": 0,
            "high_octane_capital_overlay_same_bar_proxy_row_count": 8,
            "high_octane_capital_overlay_execution_boundary_verdict": "same_bar_execution_proxy_requires_strict_risk_stress_and_mark_index_replay",
            "high_yield_prior_exposure_return_violation_count": 1,
            "high_yield_model_boundary_row_count": 2,
        },
    }
