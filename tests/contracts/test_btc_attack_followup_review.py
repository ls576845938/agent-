from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research.btc_attack_followup_review import build_btc_attack_followup_review


def test_btc_attack_followup_review_builds_research_only_report(tmp_path: Path) -> None:
    paths = _write_fixture_inputs(tmp_path)

    report = build_btc_attack_followup_review(
        market_db_path=tmp_path / "market.sqlite",
        derivatives_rows_path=tmp_path / "derivatives.json",
        high_octane_report_path=paths["high_report"],
        high_octane_rolling_path=paths["high_rolling"],
        risk_stress_matrix_path=paths["risk_matrix"],
        risk_stress_report_path=paths["risk_report"],
        pyramiding_report_path=paths["pyramiding"],
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        run_rolling_comparison=False,
    )

    assert report["schema_version"] == "btc_attack_followup_review_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_attack_followup_review_complete_not_forward_ready_no_paper_no_live"
    assert report["summary"]["high_octane_best_scenario_id"] == "ho_best"
    assert report["summary"]["high_octane_source_annual_return_pct"] == 969.068636
    assert report["summary"]["high_octane_strict_base_annual_return_pct"] == 275.525772
    assert report["summary"]["high_octane_strict_min_remaining_after_10pct_spike"] == 40.5
    assert report["summary"]["high_octane_rolling_median_total_return_pct"] == 150.0
    assert report["summary"]["comparison_verdict"] == "defensive_5x_dominates_same_window_return_and_spike_survival"
    assert len(report["high_octane_strict_rows"]) == 2
    assert {row["line_id"] for row in report["same_window_comparison_rows"]} == {
        "defensive_5x_spike_sleeve",
        "actual_10x_limited_attack",
    }
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False

    summary = (tmp_path / "out" / "btc_attack_followup_review_summary_cn.md").read_text(encoding="utf-8")
    assert "High-Octane v2 严格复核" in summary
    assert "5x 防插针 vs 实际 10x 限暴露" in summary
    assert "不写 paper 队列" in summary


def test_btc_attack_followup_review_blocks_missing_sources(tmp_path: Path) -> None:
    paths = _write_fixture_inputs(tmp_path)
    report = build_btc_attack_followup_review(
        high_octane_report_path=paths["high_report"],
        high_octane_rolling_path=tmp_path / "missing_rolling.csv",
        risk_stress_matrix_path=paths["risk_matrix"],
        risk_stress_report_path=paths["risk_report"],
        pyramiding_report_path=paths["pyramiding"],
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
        run_rolling_comparison=False,
    )

    assert report["status"] == "blocked"
    assert "missing_high_octane_rolling" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False


def _write_fixture_inputs(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "high_report": tmp_path / "high_report.json",
        "high_rolling": tmp_path / "high_rolling.csv",
        "risk_report": tmp_path / "risk_report.json",
        "risk_matrix": tmp_path / "risk_matrix.csv",
        "pyramiding": tmp_path / "pyramiding.json",
    }
    _write_json(
        paths["high_report"],
        {
            "summary": {
                "best_scenario_id": "ho_best",
                "best_annual_return_pct": 969.068636,
                "best_total_return_pct": 36627.902132,
                "best_max_drawdown_abs_pct": 27.098772,
                "best_min_remaining_after_10pct_spike": 40.011869,
            }
        },
    )
    _write_json(paths["risk_report"], {"summary": {"not_forward_observation_ready": True}})
    _write_csv(
        paths["risk_matrix"],
        [
            {
                "scenario_id": "ho_best",
                "policy_id": "base_strict_next_bar",
                "annual_return_pct": "275.525772",
                "total_return_pct": "2636.050787",
                "max_drawdown_abs_pct": "41.303028",
                "min_remaining_capital_pct_after_10pct_spike": "41.0",
                "normal_liquidation_count": "0",
                "spike_liquidation_max_count": "2",
                "max_concurrent_exposed_sleeves_observed": "10",
                "strict_next_bar_execution": "True",
                "same_bar_profit_allowed": "False",
                "full_wipeout": "False",
                "hard_wipeout": "False",
            },
            {
                "scenario_id": "ho_best",
                "policy_id": "combined_adverse_5x",
                "annual_return_pct": "250.0",
                "total_return_pct": "2000.0",
                "max_drawdown_abs_pct": "45.0",
                "min_remaining_capital_pct_after_10pct_spike": "40.5",
                "normal_liquidation_count": "0",
                "spike_liquidation_max_count": "2",
                "max_concurrent_exposed_sleeves_observed": "10",
                "strict_next_bar_execution": "True",
                "same_bar_profit_allowed": "False",
                "full_wipeout": "False",
                "hard_wipeout": "False",
            },
        ],
    )
    _write_csv(
        paths["high_rolling"],
        [
            {"scenario_id": "ho_best", "total_return_pct": "100.0", "annual_return_pct": "200.0", "min_remaining_capital_pct_after_10pct_spike": "50.0", "full_wipeout": "False"},
            {"scenario_id": "ho_best", "total_return_pct": "200.0", "annual_return_pct": "300.0", "min_remaining_capital_pct_after_10pct_spike": "60.0", "full_wipeout": "False"},
        ],
    )
    _write_json(
        paths["pyramiding"],
        {
            "top_watchlist": [
                {
                    "scenario_id": "pyr_defense",
                    "annual_return_pct": 596.0,
                    "total_return_pct": 12535.0,
                    "max_drawdown_abs_pct": 19.0,
                    "min_remaining_capital_pct_after_10pct_spike": 100.0,
                }
            ],
            "top_actual_attack_watchlist": [
                {
                    "scenario_id": "pyr_attack",
                    "annual_return_pct": 130.0,
                    "total_return_pct": 701.0,
                    "max_drawdown_abs_pct": 6.0,
                    "min_remaining_capital_pct_after_10pct_spike": 89.0,
                }
            ],
        },
    )
    return paths


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
