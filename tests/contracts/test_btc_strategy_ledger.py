from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_strategy_ledger import build_btc_strategy_ledger


def test_btc_strategy_ledger_builds_fixed_five_lines_and_chinese_summary(tmp_path: Path) -> None:
    report_paths = _write_all_strategy_reports(tmp_path)
    objective = _write_json(tmp_path / "objective.json", {"status": "complete_research_only", "blockers": []})
    dashboard = _write_json(tmp_path / "dashboard.json", {"blockers": []})

    report = build_btc_strategy_ledger(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        report_paths=report_paths,
        objective_status_path=objective,
        gate_dashboard_path=dashboard,
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_strategy_ledger_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_strategy_ledger_complete_research_only_no_paper_no_live"
    assert report["line_count"] == 5
    assert {row["strategy_id"] for row in report["strategy_lines"]} == {
        "stable_long_short",
        "high_yield",
        "attack_sleeve",
        "raw_trend_legacy",
        "timesfm_auxiliary",
    }
    for row in report["strategy_lines"]:
        assert row["input_data"]
        assert row["parameter_summary"]
        assert row["latest_report_path"]
        assert row["latest_report_exists"] is True
        assert "blockers" in row
        assert row["research_only"] is True
        assert row["paper_queue_write_allowed"] is False
        assert row["paper_allowed"] is False
        assert row["live_unlock_allowed"] is False
        assert row["broker_or_order_allowed"] is False
        assert row["next_action"]
        assert row["keep_or_retire_recommendation"]

    timesfm = _line(report, "timesfm_auxiliary")
    assert timesfm["is_auxiliary_model"] is True
    assert timesfm["is_trade_strategy"] is False
    assert timesfm["latest_signal_or_exposure"]["kind"] == "auxiliary_forecast_diagnostic"

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False

    summary = (tmp_path / "out" / "btc_strategy_ledger_summary_cn.md").read_text(encoding="utf-8")
    assert "稳健线 Long/Short Donchian Top5" in summary
    assert "High-yield v2 高收益研究线" in summary
    assert "Attack sleeve 分仓滚仓线" in summary
    assert "早期 raw trend 原始趋势线" in summary
    assert "TimesFM 辅助预测/风险诊断" in summary
    assert "不写 paper 队列，不解锁 live" in summary


def test_btc_strategy_ledger_keeps_missing_report_line_fail_closed(tmp_path: Path) -> None:
    report_paths = _write_all_strategy_reports(tmp_path)
    report_paths["high_yield"] = tmp_path / "missing_high_yield.json"
    objective = _write_json(tmp_path / "objective.json", {"status": "complete_research_only", "blockers": []})
    dashboard = _write_json(tmp_path / "dashboard.json", {"blockers": []})

    report = build_btc_strategy_ledger(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        report_paths=report_paths,
        objective_status_path=objective,
        gate_dashboard_path=dashboard,
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )

    assert report["status"] == "incomplete_research_only"
    assert report["missing_report_count"] == 1
    high_yield = _line(report, "high_yield")
    assert high_yield["latest_report_exists"] is False
    assert high_yield["status"] == "missing_report"
    assert "btc_strategy_ledger_missing_report:high_yield" in high_yield["blockers"]
    assert high_yield["paper_queue_write_allowed"] is False
    assert high_yield["live_unlock_allowed"] is False


def test_btc_strategy_ledger_fails_closed_on_upstream_paper_or_live_true(tmp_path: Path) -> None:
    report_paths = _write_all_strategy_reports(tmp_path)
    _write_json(
        report_paths["attack_sleeve"],
        {
            "schema_version": "btc_bankroll_attack_forward_observer_v1",
            "status": "complete_research_only",
            "decision": "unsafe_fixture_should_not_unlock",
            "generated_at_utc": "2026-07-02T01:00:00+00:00",
            "gate": {"paper_queue_write_allowed": True, "live_unlock_allowed": True},
            "guardrails": {"order_endpoint_used": True},
            "blockers": [],
        },
    )
    objective = _write_json(tmp_path / "objective.json", {"status": "complete_research_only", "blockers": []})
    dashboard = _write_json(tmp_path / "dashboard.json", {"blockers": []})

    report = build_btc_strategy_ledger(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        report_paths=report_paths,
        objective_status_path=objective,
        gate_dashboard_path=dashboard,
        generated_at_utc=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )

    attack = _line(report, "attack_sleeve")
    assert report["status"] == "incomplete_research_only"
    assert report["unsafe_line_count"] == 1
    assert attack["status"] == "blocked_fail_closed_research_only"
    assert "gate.paper_queue_write_allowed" in attack["upstream_safety_violations"]
    assert "gate.live_unlock_allowed" in attack["upstream_safety_violations"]
    assert "guardrails.order_endpoint_used" in attack["upstream_safety_violations"]
    assert attack["paper_queue_write_allowed"] is False
    assert attack["paper_allowed"] is False
    assert attack["live_unlock_allowed"] is False
    assert attack["broker_or_order_allowed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _line(report: dict, strategy_id: str) -> dict:
    return next(row for row in report["strategy_lines"] if row["strategy_id"] == strategy_id)


def _write_all_strategy_reports(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "stable_long_short": tmp_path / "stable.json",
        "high_yield": tmp_path / "high_yield.json",
        "attack_sleeve": tmp_path / "attack.json",
        "raw_trend_legacy": tmp_path / "raw_trend.json",
        "timesfm_auxiliary": tmp_path / "timesfm.json",
    }
    _write_json(
        paths["stable_long_short"],
        {
            "schema_version": "btc_long_short_top5_forward_observer_v1",
            "status": "complete_research_only",
            "decision": "long_short_top5_forward_observer_active_no_paper_no_live",
            "generated_at_utc": "2026-07-02T01:00:00+00:00",
            "input": {
                "market_db_path": "data/market_data.sqlite",
                "derivatives_rows_path": "data/external/derivatives.json",
            },
            "observer_design": {"observer_id": "btc_long_short_donchian_top5_observe_only_v1"},
            "latest_observations": [
                {
                    "rank": 1,
                    "candidate_id": "candidate_a",
                    "decision_time": "2026-07-01T23:59:59.999000+00:00",
                    "decision_signal": {"side": "flat", "value": 0.0},
                    "theoretical_exposure": {"side": "flat", "value": 0.0},
                }
            ],
            "observation_progress": {"observation_count": 3, "observation_days": 2},
            "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            "guardrails": {"order_endpoint_used": False, "private_endpoint_used": False},
            "blockers": [],
        },
    )
    _write_json(
        paths["high_yield"],
        {
            "schema_version": "btc_high_yield_v2_followup_v1",
            "status": "complete_research_only",
            "decision": "btc_high_yield_v2_followup_research_only_no_paper_no_live",
            "generated_at_utc": "2026-07-02T01:00:00+00:00",
            "input": {"market_db_path": "data/market_data.sqlite", "derivatives_rows_path": "data/external/derivatives.json"},
            "frozen_candidate": {"candidate_id": "hy_candidate", "variant_id": "hy_variant"},
            "step_1_daily_observation_automation": {
                "new_observation_written": False,
                "already_processed": True,
                "observation_count": 2,
                "observation_days": 2,
                "holdout_lock": {"latest_decision_time": "2026-07-01T23:59:59.999000+00:00"},
            },
            "step_2_loss_control_v3_narrow_experiment": {"candidate_count": 48},
            "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            "guardrails": {"order_endpoint_used": False, "private_endpoint_used": False},
            "blockers": [],
        },
    )
    _write_json(
        paths["attack_sleeve"],
        {
            "schema_version": "btc_bankroll_attack_forward_observer_v1",
            "status": "complete_research_only",
            "decision": "attack_forward_observer_active_under_30d_no_paper_no_live",
            "generated_at_utc": "2026-07-02T01:00:00+00:00",
            "input": {"market_db_path": "data/market_data.sqlite", "derivatives_rows_path": "data/external/derivatives.json"},
            "latest_observation": {
                "decision_time": "2026-07-01T23:59:59.999000+00:00",
                "daily_signal": {"side": "short"},
                "theoretical_sleeve_exposure": {"exposed_sleeve_count": 3},
                "spike_remaining_capital": {"remaining_after_10pct_spike_pct": 52.0},
                "downgrade_triggered": False,
            },
            "observation_progress": {"observation_count": 2, "observation_days": 2},
            "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
            "guardrails": {"order_endpoint_used": False, "private_endpoint_used": False},
            "blockers": [],
        },
    )
    _write_json(
        paths["raw_trend_legacy"],
        {
            "schema_version": "btc_trend_raw_forward_observation_daily_v1",
            "status": "PASS",
            "generated_at": "2026-07-02T01:00:00Z",
            "forward_observation": {"new_observation_written": True, "observation_count": 4, "observation_days": 4},
            "guardrails": {"simulated_only": True, "real_order_submitted": False, "order_endpoint_used": False},
            "blockers": [],
        },
    )
    _write_json(
        paths["timesfm_auxiliary"],
        {
            "schema_version": "btc_timesfm_vs_trend_baseline_oos_v1",
            "status": "complete_research_only",
            "generated_at_utc": "2026-07-02T01:00:00+00:00",
            "input": {"db_path": "data/market_data.sqlite", "decision_count": 24},
            "research_decision": {"decision": "diagnostic_only"},
            "comparison": {"winner": "trend_baseline"},
            "gate": {"paper_candidate_allowed": False, "live_allowed": False},
            "safety_flags": {"order_endpoint_used": False, "private_endpoint_used": False},
            "blockers": [],
        },
    )
    return paths


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
