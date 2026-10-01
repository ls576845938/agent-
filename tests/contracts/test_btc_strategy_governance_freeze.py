from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_strategy_governance_freeze import build_btc_strategy_governance_freeze


def test_strategy_governance_freeze_locks_ledger_holdout_and_champion_challenger(tmp_path: Path) -> None:
    ledger_path = _write_strategy_ledger(tmp_path)
    audit_path = _write_leakage_audit(tmp_path)

    report = build_btc_strategy_governance_freeze(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        strategy_ledger_report_path=ledger_path,
        leakage_overfit_audit_report_path=audit_path,
        generated_at_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_strategy_governance_freeze_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_strategy_governance_freeze_active_no_new_mining_no_paper_no_live"
    assert report["strategy_ledger_freeze"]["freeze_active"] is True
    assert report["strategy_ledger_freeze"]["new_strategy_mining_allowed"] is False
    assert report["strategy_ledger_freeze"]["strategy_family_expansion_allowed"] is False
    assert report["strategy_ledger_freeze"]["parameter_mutation_allowed"] is False
    assert report["strategy_ledger_freeze"]["selection_after_observe_allowed"] is False
    assert report["champion_challenger"]["champion"]["strategy_id"] == "stable_long_short"
    assert report["champion_challenger"]["champion_change_allowed"] is False
    assert report["champion_challenger"]["challenger_promotion_allowed"] is False
    assert report["holdout_lock"]["selection_use_blocked_by_lock"] is True
    assert report["holdout_lock"]["clean_forward_confirmation_ready"] is False

    high_octane = report["post_selection_usage_limits"]["high_octane"]
    assert high_octane["likely_parameter_mined_boundary_candidate"] is True
    assert high_octane["post_selection_usage_allowed"] is False
    assert high_octane["paper_candidate_allowed"] is False
    assert high_octane["best_margin_over_40pct_threshold"] == 0.011869

    rows = report["strategy_ledger_freeze"]["frozen_rows"]
    assert {row["strategy_id"] for row in rows} == {
        "stable_long_short",
        "high_yield",
        "attack_sleeve",
        "raw_trend_legacy",
        "timesfm_auxiliary",
        "high_octane_attack_sleeve_v2_audit_subject",
    }
    for row in rows:
        assert row["parameter_hash"]
        assert row["parameter_mutation_allowed"] is False
        assert row["paper_allowed"] is False
        assert row["live_unlock_allowed"] is False

    assert "btc_strategy_governance_high_octane_parameter_boundary_mined" in report["promotion_blockers"]
    assert "btc_strategy_governance_holdout_selection_use_blocked" in report["promotion_blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["gate"]["broker_or_order_allowed"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["new_strategy_mining_allowed"] is False
    assert safety["parameter_mutation_allowed"] is False
    assert safety["post_selection_reuse_allowed"] is False
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False

    summary = (tmp_path / "out" / "btc_strategy_governance_freeze_summary_cn.md").read_text(encoding="utf-8")
    assert "不扩大策略挖矿" in summary
    assert "不写 paper 队列" in summary
    assert "不解锁 live" in summary
    assert "High-Octane" in summary


def test_strategy_governance_freeze_fails_closed_on_upstream_safety_true(tmp_path: Path) -> None:
    ledger_path = _write_strategy_ledger(tmp_path)
    audit_path = _write_leakage_audit(tmp_path, unsafe=True)

    report = build_btc_strategy_governance_freeze(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        strategy_ledger_report_path=ledger_path,
        leakage_overfit_audit_report_path=audit_path,
        generated_at_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked"
    assert "btc_strategy_governance_upstream_safety_violation_fail_closed" in report["artifact_blockers"]
    assert "leakage_overfit_audit.gate.paper_queue_write_allowed" in report["source_safety_violations"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["new_strategy_mining_allowed"] is False


def test_strategy_governance_freeze_missing_inputs_are_blocked(tmp_path: Path) -> None:
    report = build_btc_strategy_governance_freeze(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        strategy_ledger_report_path=tmp_path / "missing_ledger.json",
        leakage_overfit_audit_report_path=tmp_path / "missing_audit.json",
        generated_at_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked"
    assert "btc_strategy_governance_missing_strategy_ledger" in report["artifact_blockers"]
    assert "btc_strategy_governance_missing_leakage_overfit_audit" in report["artifact_blockers"]
    assert report["gate"]["paper_allowed"] is False
    assert report["strategy_ledger_freeze"]["new_strategy_mining_allowed"] is False


def _write_strategy_ledger(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "ledger.json",
        {
            "schema_version": "btc_strategy_ledger_v1",
            "status": "incomplete_research_only",
            "decision": "btc_strategy_ledger_incomplete_research_only_no_paper_no_live",
            "strategy_lines": [
                _ledger_line("stable_long_short", {"entry_window": 240, "daily_ema": "50/200"}),
                _ledger_line("high_yield", {"variant_id": "hy_v2", "max_leverage": 2.5}),
                _ledger_line("attack_sleeve", {"observer_id": "attack_observe_v1"}),
                _ledger_line("raw_trend_legacy", {"legacy": True}),
                _ledger_line("timesfm_auxiliary", {"model": "timesfm", "diagnostic_only": True}),
            ],
            "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            "blockers": [],
        },
    )


def _ledger_line(strategy_id: str, params: dict) -> dict:
    return {
        "strategy_id": strategy_id,
        "latest_report_path": f"artifacts/{strategy_id}/latest/report.json",
        "latest_report_status": "complete_research_only",
        "status": "complete_research_only",
        "parameter_summary": params,
        "paper_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "blockers": [],
    }


def _write_leakage_audit(tmp_path: Path, *, unsafe: bool = False) -> Path:
    return _write_json(
        tmp_path / "audit.json",
        {
            "schema_version": "btc_strategy_leakage_overfit_audit_v2",
            "status": "complete_research_only",
            "decision": "research_only_overfit_risk_high_no_paper_no_live",
            "summary": {
                "high_octane_overfit_verdict": "parameter_boundary_mined_research_only",
                "high_octane_parameter_mining_verdict": "strong_parameter_mining_symptoms_threshold_boundary_research_only",
                "high_octane_likely_parameter_mined_boundary_candidate": True,
                "high_octane_best_margin_over_40pct_threshold": 0.011869,
                "high_octane_threshold_margin_by_tier_pct": {
                    "survive_40pct": 0.011869,
                    "survive_50pct": -9.988131,
                    "survive_60pct": -19.988131,
                },
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
            "input": {"high_octane_report_path": "artifacts/high_octane/report.json"},
            "high_octane_v2_audit": {
                "artifact_status": "complete_research_only",
                "best_scenario_id": "ho_step0p35_core5x6_reserve5x2_attack10x2_cap2_max10_delaylate_none",
                "best_watchlist_tier": "survive_40pct",
                "best_margin_over_40pct_threshold": 0.011869,
                "overfit_verdict": "parameter_boundary_mined_research_only",
                "parameter_mining_verdict": "strong_parameter_mining_symptoms_threshold_boundary_research_only",
                "likely_parameter_mined_boundary_candidate": True,
                "threshold_margin_by_tier_pct": {
                    "survive_40pct": 0.011869,
                    "survive_50pct": -9.988131,
                    "survive_60pct": -19.988131,
                },
                "parameter_mining_audit": {
                    "scenario_grid_count": 1944,
                    "watchlist_count": 60,
                    "best_margin_over_40pct_threshold": 0.011869,
                    "likely_parameter_mined_boundary_candidate": True,
                },
            },
            "holdout_and_forward_observe_audit": {
                "holdout_lock_status": "complete_research_only",
                "holdout_lock_decision": "btc_confirmatory_holdout_locked_research_only_no_paper_no_live",
                "latest_common_history_end": "2026-06-28T23:59:59.999000+00:00",
                "future_observe_window": {
                    "start_exclusive": "2026-06-28T23:59:59.999000+00:00",
                    "planned_30d_end_inclusive": "2026-07-28T23:59:59.999000+00:00",
                    "planned_60d_end_inclusive": "2026-08-27T23:59:59.999000+00:00",
                },
                "minimum_30d_complete": False,
                "clean_forward_confirmation_ready": False,
                "selection_use_blocked_by_lock": True,
                "observe_only_violation_count": 0,
            },
            "gate": {"paper_queue_write_allowed": unsafe, "live_unlock_allowed": False},
            "guardrails": {"order_endpoint_used": False, "private_endpoint_used": False},
            "blockers": [],
        },
    )


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
