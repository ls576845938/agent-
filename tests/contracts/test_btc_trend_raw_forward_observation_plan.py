from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.build_btc_trend_raw_forward_observation_plan import (
    build_btc_trend_raw_forward_observation_plan,
)


def test_raw_forward_observation_plan_blocks_missing_top_report(tmp_path: Path) -> None:
    vol = tmp_path / "vol.json"
    _write_vol_report(vol)

    payload = build_btc_trend_raw_forward_observation_plan(
        repo_root=tmp_path,
        top_validation_report=tmp_path / "missing.json",
        volatility_position_report=vol,
        output=tmp_path / "plan.json",
        candidate_output=tmp_path / "candidates.csv",
        volatility_freeze_output=tmp_path / "freeze.json",
        markdown_output=tmp_path / "plan.md",
        volatility_freeze_markdown=tmp_path / "freeze.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "raw_forward_observation_plan_blocked"
    assert "btc_trend_top_strategy_validation_report_missing_or_unexpected_status" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "freeze.json").exists()
    assert json.loads((tmp_path / "freeze.json").read_text(encoding="utf-8"))["status"] == "frozen_deferred_not_primary"
    assert (tmp_path / "candidates.csv").read_text(encoding="utf-8").startswith("priority_rank,family_id")


def test_raw_forward_observation_plan_ranks_raw_candidates_and_freezes_vol_branch(tmp_path: Path) -> None:
    top = tmp_path / "top.json"
    vol = tmp_path / "vol.json"
    _write_top_report(top)
    _write_vol_report(vol)

    payload = build_btc_trend_raw_forward_observation_plan(
        repo_root=tmp_path,
        top_validation_report=top,
        volatility_position_report=vol,
        output=tmp_path / "plan.json",
        candidate_output=tmp_path / "candidates.csv",
        volatility_freeze_output=tmp_path / "freeze.json",
        markdown_output=tmp_path / "plan.md",
        volatility_freeze_markdown=tmp_path / "freeze.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "raw_trend_forward_observation_plan_ready"
    assert payload["decision"] == "observe_raw_trend_candidates_only_volatility_position_frozen"
    assert payload["primary_candidate"]["family_id"] == "t01_twelve_month_momentum"
    assert payload["forward_observation"]["volatility_position_branch_allowed"] is False
    assert payload["forward_observation"]["paper_runner_start_allowed_by_this_report"] is False
    assert payload["guardrails"]["volatility_position_branch_frozen"] is True
    assert payload["guardrails"]["live_order_allowed"] is False

    ranked = payload["candidate_ranking"]
    assert [row["family_id"] for row in ranked[:4]] == [
        "t01_twelve_month_momentum",
        "t06_atr_channel_breakout",
        "oth_t02_ewmac_acceleration",
        "t07_bollinger_breakout",
    ]
    excluded = next(row for row in ranked if row["family_id"] == "t02_long_ma_trend")
    assert excluded["forward_observation_allowed"] is False

    freeze = json.loads((tmp_path / "freeze.json").read_text(encoding="utf-8"))
    assert freeze["status"] == "frozen_deferred_not_primary"
    assert freeze["guardrails"]["parameter_tuning_allowed"] is False
    assert freeze["guardrails"]["paper_observation_allowed"] is False
    assert freeze["guardrails"]["live_order_allowed"] is False

    csv_rows = list(csv.DictReader((tmp_path / "candidates.csv").open("r", encoding="utf-8")))
    assert csv_rows
    assert csv_rows[0]["family_id"] == "t01_twelve_month_momentum"
    assert (tmp_path / "plan.md").read_text(encoding="utf-8").startswith("# BTC 趋势原始策略前向观察计划")
    assert (tmp_path / "freeze.md").read_text(encoding="utf-8").startswith("# BTC 趋势波动率仓位冻结记录")


def test_raw_forward_observation_plan_requires_allowed_candidates(tmp_path: Path) -> None:
    top = tmp_path / "top.json"
    vol = tmp_path / "vol.json"
    _write_top_report(top, all_failed=True)
    _write_vol_report(vol)

    payload = build_btc_trend_raw_forward_observation_plan(
        repo_root=tmp_path,
        top_validation_report=top,
        volatility_position_report=vol,
        output=tmp_path / "plan.json",
        candidate_output=tmp_path / "candidates.csv",
        volatility_freeze_output=tmp_path / "freeze.json",
        markdown_output=tmp_path / "plan.md",
        volatility_freeze_markdown=tmp_path / "freeze.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "raw_forward_observation_plan_blocked"
    assert "btc_trend_raw_forward_observation_no_allowed_candidates" in payload["blockers"]


def _write_top_report(path: Path, *, all_failed: bool = False) -> None:
    families = [
        ("t06_atr_channel_breakout", "t06", 31.0, 288.0, 34.0, 28.0, 0.95, 2, 2, 4, 108),
        ("t01_twelve_month_momentum", "t01", 28.0, 253.0, 32.0, 28.0, 0.94, 4, 2, 4, 30),
        ("t07_bollinger_breakout", "t07", 27.0, 236.0, 33.0, 28.0, 0.89, 2, 2, 4, 18),
        ("oth_t02_ewmac_acceleration", "oth", 26.0, 118.0, 17.0, 17.0, 0.97, 101, 2, 4, 48),
        ("t02_long_ma_trend", "t02", 24.0, 252.0, 33.0, 30.0, 0.91, 12, 0, 4, 200),
    ]
    candidate_summaries = []
    wf = {}
    param = {}
    extreme = {}
    for family_id, cid, score, ret, vol, dd, sharpe, changes, positive, folds, param_rows in families:
        passed = not all_failed and family_id != "t02_long_ma_trend"
        candidate_summaries.append(
            {
                "family_id": family_id,
                "candidate_id": cid,
                "variant_id": cid,
                "validation_status": "research_validation_passed" if passed else "research_validation_not_passed",
                "score": score,
                "metrics": {
                    "total_return_pct": ret,
                    "annual_return_pct": ret / 5.0,
                    "annual_volatility_pct": vol,
                    "max_drawdown_abs_pct": dd,
                    "sharpe_ratio": sharpe,
                    "average_exposure": 0.5,
                    "exposure_change_count": changes,
                },
                "checks": {
                    "walk_forward": passed,
                    "regime_validation": passed,
                    "parameter_stability": passed,
                    "cost_stress": passed,
                    "extreme_year_contribution": passed,
                },
            }
        )
        wf[family_id] = {"fold_count": folds, "positive_fold_count": positive, "pass": passed}
        param[family_id] = {"row_count": param_rows, "selected_score_percentile": 1.0}
        extreme[family_id] = {"top_positive_year_share": 0.60}
    path.write_text(
        json.dumps(
            {
                "status": "top_strategy_validation_research_only",
                "candidate_summaries": candidate_summaries,
                "walk_forward": {"summary": {"family_summary": wf}},
                "parameter_stability": {"summary": param},
                "extreme_year_contribution": {"summary": extreme},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_vol_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "volatility_position_research_only",
                "family_summaries": [
                    {
                        "family_id": "t01_twelve_month_momentum",
                        "selected_variant": {
                            "return_diff_vs_baseline_pct": -190.0,
                            "sharpe_diff_vs_baseline": -0.02,
                        },
                    },
                    {
                        "family_id": "oth_t02_ewmac_acceleration",
                        "selected_variant": {
                            "return_diff_vs_baseline_pct": -82.0,
                            "sharpe_diff_vs_baseline": 0.04,
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
