from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_attack_strategy_continuation_shortlist import (
    build_btc_attack_strategy_continuation_shortlist,
)


def test_attack_strategy_continuation_shortlist_builds_fixed_four_lines(tmp_path: Path) -> None:
    paths = _write_fixture_reports(tmp_path)

    report = build_btc_attack_strategy_continuation_shortlist(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        bankroll_review_path=paths["bankroll"],
        high_octane_path=paths["high_octane"],
        pyramiding_path=paths["pyramiding"],
        risk_stress_path=paths["risk_stress"],
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
    )

    assert report["schema_version"] == "btc_attack_strategy_continuation_shortlist_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_attack_strategy_continuation_shortlist_complete_research_only_no_paper_no_live"
    assert report["line_count"] == 4
    assert report["continued_research_strategy_count"] == 3
    assert report["danger_reference_count"] == 1
    assert {row["strategy_id"] for row in report["strategy_lines"]} == {
        "original_10x_explosive_reference",
        "high_octane_attack_sleeve_v2",
        "defensive_5x_mixed_sleeve",
        "actual_10x_attack_limited_exposure",
    }

    original = _line(report, "original_10x_explosive_reference")
    assert original["continue_research"] is False
    assert original["research_role"] == "danger_reference"
    assert original["annual_return_pct"] == 4648.314318
    assert original["total_return_pct"] == 1510327.760228
    assert original["min_remaining_after_10pct_spike_pct"] == 0.0
    assert "danger_ceiling" in original["retention_decision"]

    high = _line(report, "high_octane_attack_sleeve_v2")
    assert high["continue_research"] is True
    assert high["annual_return_pct"] == 969.068636
    assert high["threshold_margin_over_40pct"] == 0.011869
    assert "boundary_mined" in high["retention_decision"]

    defensive = _line(report, "defensive_5x_mixed_sleeve")
    assert defensive["continue_research"] is True
    assert defensive["annual_return_pct"] == 723.527457
    assert defensive["min_remaining_after_10pct_spike_pct"] == 100.0

    actual_attack = _line(report, "actual_10x_attack_limited_exposure")
    assert actual_attack["continue_research"] is True
    assert actual_attack["min_remaining_after_10pct_spike_pct"] == 89.633863

    for row in report["strategy_lines"]:
        assert row["paper_queue_write_allowed"] is False
        assert row["paper_allowed"] is False
        assert row["live_unlock_allowed"] is False
        assert row["broker_or_order_allowed"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False

    summary = (tmp_path / "out" / "btc_attack_strategy_continuation_shortlist_summary_cn.md").read_text(
        encoding="utf-8"
    )
    assert "BTC 激进/分仓滚仓继续研究短名单" in summary
    assert "10x no_rollover / split_2_on_double 原始爆炸版" in summary
    assert "High-Octane Attack Sleeve v2" in summary
    assert "防插针 5x / mixed sleeve 版本" in summary
    assert "实际 10x attack 但限制暴露版本" in summary
    assert "不写 paper 队列" in summary


def test_attack_strategy_continuation_shortlist_marks_missing_sources_incomplete(tmp_path: Path) -> None:
    paths = _write_fixture_reports(tmp_path)
    paths["risk_stress"] = tmp_path / "missing_risk_stress.json"

    report = build_btc_attack_strategy_continuation_shortlist(
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        bankroll_review_path=paths["bankroll"],
        high_octane_path=paths["high_octane"],
        pyramiding_path=paths["pyramiding"],
        risk_stress_path=paths["risk_stress"],
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
    )

    assert report["status"] == "incomplete_research_only"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert "missing_source:attack_sleeve_risk_stress_review" in report["blockers"]


def _line(report: dict, strategy_id: str) -> dict:
    return next(row for row in report["strategy_lines"] if row["strategy_id"] == strategy_id)


def _write_fixture_reports(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "bankroll": tmp_path / "bankroll.json",
        "high_octane": tmp_path / "high_octane.json",
        "pyramiding": tmp_path / "pyramiding.json",
        "risk_stress": tmp_path / "risk_stress.json",
    }
    _write_json(
        paths["bankroll"],
        {
            "status": "complete_research_only",
            "decision": "path_dependent_not_forward_observation_ready",
            "generated_at_utc": "2026-07-01T00:00:00+00:00",
            "source_attribution": {
                "rows": [
                    {
                        "scenario_id": "br_review_no_rollover_lev5p0",
                        "annual_return_pct": 723.527457,
                        "total_return_pct": 19064.845522,
                        "max_drawdown_abs_pct": 28.093271,
                        "leverage": 5.0,
                    },
                    {
                        "scenario_id": "br_review_no_rollover_lev10p0",
                        "annual_return_pct": 4648.314318,
                        "total_return_pct": 1510327.760228,
                        "max_drawdown_abs_pct": 49.504493,
                        "leverage": 10.0,
                        "active_sleeve_count": 10,
                    },
                    {
                        "scenario_id": "br_review_split_2_on_double_lev10p0",
                        "annual_return_pct": 4648.314318,
                        "total_return_pct": 1510327.760228,
                        "max_drawdown_abs_pct": 49.504493,
                        "leverage": 10.0,
                        "active_sleeve_count": 80,
                    },
                ]
            },
        },
    )
    _write_json(
        paths["high_octane"],
        {
            "status": "complete_research_only",
            "decision": "btc_high_octane_attack_sleeve_lab_research_only_no_paper_no_live",
            "generated_at_utc": "2026-07-01T00:00:00+00:00",
            "summary": {
                "best_scenario_id": "ho_best",
                "best_annual_return_pct": 969.068636,
                "best_total_return_pct": 36627.902132,
                "best_max_drawdown_abs_pct": 27.098772,
                "best_min_remaining_after_10pct_spike": 40.011869,
                "best_rolling_median_total_return_pct": 1435.825771,
            },
            "top_watchlist": [
                {
                    "scenario_id": "ho_best",
                    "max_template_leverage": 10.0,
                    "max_concurrent_exposed_sleeves_observed": 10,
                }
            ],
        },
    )
    _write_json(
        paths["pyramiding"],
        {
            "status": "complete_research_only",
            "decision": "btc_pyramiding_sleeve_lab_research_only_no_paper_no_live",
            "generated_at_utc": "2026-07-01T00:00:00+00:00",
            "summary": {
                "best_scenario_id": "pyr_defensive",
                "best_min_remaining_after_10pct_spike": 100.0,
                "best_actual_attack_scenario_id": "pyr_attack",
                "best_actual_attack_annual_return_pct": 130.506691,
                "best_actual_attack_max_drawdown_abs_pct": 10.0,
                "best_actual_attack_min_remaining_after_10pct_spike": 89.633863,
            },
            "top_watchlist": [{"scenario_id": "pyr_defensive", "max_concurrent_exposed_sleeves_observed": 7}],
            "top_actual_attack_watchlist": [
                {
                    "scenario_id": "pyr_attack",
                    "annual_return_pct": 130.506691,
                    "total_return_pct": 1000.0,
                    "max_drawdown_abs_pct": 10.0,
                    "min_remaining_capital_pct_after_10pct_spike": 89.633863,
                    "max_concurrent_exposed_sleeves_observed": 7,
                }
            ],
        },
    )
    _write_json(
        paths["risk_stress"],
        {
            "status": "complete_research_only",
            "decision": "not_forward_observation_ready_research_only_no_paper_no_live",
            "generated_at_utc": "2026-07-01T00:00:00+00:00",
            "summary": {"not_forward_observation_ready": True, "source_best_scenario_id": "ho_best"},
        },
    )
    return paths


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
