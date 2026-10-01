from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_crypto.research import btc_strategy_bar_replay_visibility as replay


def test_derivatives_visibility_frame_never_uses_future_available_time(tmp_path: Path) -> None:
    derivatives_path = tmp_path / "derivatives.json"
    _write_json(
        derivatives_path,
        {
            "rows": [
                {
                    "event_time": "2026-01-01T00:00:00+00:00",
                    "available_time": "2026-01-01T00:30:00+00:00",
                    "funding_rate": 0.1,
                },
                {
                    "event_time": "2026-01-01T02:00:00+00:00",
                    "available_time": "2026-01-01T02:30:00+00:00",
                    "funding_rate": 0.2,
                },
            ]
        },
    )
    index = pd.DatetimeIndex(
        [
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T01:00:00+00:00",
            "2026-01-01T02:00:00+00:00",
        ]
    )

    frame = replay.derivatives_visibility_frame(derivatives_path, index)

    assert bool(frame.loc[index[0], "derivatives_missing"]) is True
    assert frame.loc[index[1], "derivatives_available_time"].isoformat() == "2026-01-01T00:30:00+00:00"
    assert frame.loc[index[2], "derivatives_available_time"].isoformat() == "2026-01-01T00:30:00+00:00"
    assert frame["derivatives_available_time_violation"].sum() == 0


def test_derivatives_visibility_frame_flags_future_event_time(tmp_path: Path) -> None:
    derivatives_path = tmp_path / "derivatives.json"
    _write_json(
        derivatives_path,
        {
            "rows": [
                {
                    "event_time": "2026-01-01T03:00:00+00:00",
                    "available_time": "2026-01-01T01:00:00+00:00",
                }
            ]
        },
    )
    index = pd.DatetimeIndex(["2026-01-01T02:00:00+00:00"])

    frame = replay.derivatives_visibility_frame(derivatives_path, index)

    assert bool(frame.iloc[0]["derivatives_available_time_violation"]) is False
    assert bool(frame.iloc[0]["derivatives_event_time_violation"]) is True


def test_shift_visibility_rows_requires_current_exposure_to_be_previous_raw() -> None:
    index = pd.DatetimeIndex(
        [
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T04:00:00+00:00",
            "2026-01-01T08:00:00+00:00",
        ]
    )
    raw = pd.Series([1.0, -1.0, 0.0], index=index)
    exposure = raw.shift(1).fillna(0.0)
    returns = pd.Series([0.0, 0.01, -0.02], index=index)
    visibility = pd.DataFrame(
        {
            "derivatives_available_time": [pd.NaT, index[0], index[1]],
            "derivatives_event_time": [pd.NaT, index[0], index[1]],
            "derivatives_missing": [True, False, False],
            "derivatives_available_le_decision": [True, True, True],
            "derivatives_event_le_decision": [True, True, True],
            "derivatives_available_time_violation": [False, False, False],
            "derivatives_event_time_violation": [False, False, False],
        },
        index=index,
    )

    rows = replay.shift_visibility_rows(
        line="long_short_top5",
        candidate_id="candidate",
        rank=1,
        raw_signal=raw,
        exposure=exposure,
        returns=returns,
        derivatives_visibility=visibility,
        model_boundary_flag=False,
    )

    assert sum(1 for row in rows if row["current_shift_violation"]) == 0
    assert sum(1 for row in rows if row["next_shift_violation"]) == 0
    assert rows[1]["current_bar_exposure"] == 1.0
    assert rows[1]["raw_signal"] == -1.0

    bad_rows = replay.shift_visibility_rows(
        line="long_short_top5",
        candidate_id="candidate",
        rank=1,
        raw_signal=raw,
        exposure=pd.Series([1.0, 1.0, -1.0], index=index),
        returns=returns,
        derivatives_visibility=visibility,
        model_boundary_flag=False,
    )
    assert any(row["current_shift_violation"] for row in bad_rows)


def test_bar_replay_visibility_report_is_research_only(monkeypatch, tmp_path: Path) -> None:
    long_short_report = tmp_path / "long_short_report.json"
    long_short_csv = tmp_path / "long_short.csv"
    high_report = tmp_path / "high_report.json"
    high_watchlist = tmp_path / "high_watchlist.csv"
    high_rolling = tmp_path / "high_rolling.csv"
    high_yield_report = tmp_path / "high_yield_report.json"
    _write_json(long_short_report, {"status": "complete_research_only"})
    _write_csv(long_short_csv, [{"rank": "1", "candidate_id": "ls_top"}])
    _write_json(high_report, {"summary": {"best_scenario_id": "ho_top", "best_min_remaining_after_10pct_spike": 40.011869}})
    _write_csv(high_watchlist, [_high_watchlist_row()])
    _write_csv(high_rolling, [_high_rolling_row()])
    _write_json(high_yield_report, {"frozen_candidate": {"variant_id": "hy_top"}})

    monkeypatch.setattr(
        replay,
        "_build_long_short_replay",
        lambda **_: (
            [{"line": "long_short_top5", "current_shift_violation": False, "next_shift_violation": False, "derivatives_available_time_violation": False, "derivatives_event_time_violation": False, "derivatives_missing": False, "model_boundary_flag": False}],
            {
                "line": "long_short_donchian_top5",
                "candidate_count": 1,
                "row_count": 1,
                "current_shift_violation_count": 0,
                "next_shift_violation_count": 0,
                "derivatives_available_time_violation_count": 0,
                "derivatives_event_time_violation_count": 0,
                "future_sentiment_violation_count": 0,
                "completed_bar_violation_count": 0,
                "derivatives_missing_count": 0,
                "model_boundary_row_count": 0,
                "candidate_summaries": [],
                "missing_spec_candidate_ids": [],
                "verdict": "bar_replay_no_shift_or_visibility_violations",
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
        ),
    )
    monkeypatch.setattr(
        replay,
        "_build_high_octane_visibility_replay",
        lambda **_: (
            [{"line": "high_octane_v2", "current_shift_violation": False, "next_shift_violation": False, "derivatives_available_time_violation": False, "derivatives_event_time_violation": False, "derivatives_missing": False, "model_boundary_flag": True}],
            {
                "line": "high_octane_attack_sleeve_v2",
                "candidate_count": 1,
                "row_count": 1,
                "current_shift_violation_count": 0,
                "next_shift_violation_count": 0,
                "derivatives_available_time_violation_count": 0,
                "derivatives_event_time_violation_count": 0,
                "future_sentiment_violation_count": 0,
                "completed_bar_violation_count": 0,
                "derivatives_missing_count": 0,
                "model_boundary_row_count": 1,
                "capital_overlay_same_bar_proxy_row_count": 1,
                "direction_signal_visibility_verdict": "direction_signal_visible_no_available_time_violation",
                "capital_overlay_execution_boundary_verdict": "same_bar_execution_proxy_requires_strict_risk_stress_and_mark_index_replay",
                "best_scenario_id": "ho_top",
                "best_min_remaining_after_10pct_spike": 40.011869,
                "best_margin_over_40pct_threshold": 0.011869,
                "candidate_summaries": [],
                "missing_spec_candidate_ids": [],
                "verdict": "visibility_replay_completed_but_execution_replay_required_before_paper",
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
        ),
    )
    monkeypatch.setattr(
        replay,
        "_build_high_yield_v2_visibility_replay",
        lambda **_: (
            [
                {
                    "line": "high_yield_v2",
                    "current_shift_violation": False,
                    "next_shift_violation": False,
                    "derivatives_available_time_violation": False,
                    "derivatives_event_time_violation": False,
                    "derivatives_missing": False,
                    "model_boundary_flag": True,
                    "prior_exposure_return_violation": True,
                    "same_bar_target_return_proxy": True,
                }
            ],
            {
                "line": "high_yield_donchian_v2",
                "candidate_count": 1,
                "row_count": 1,
                "current_shift_violation_count": 0,
                "next_shift_violation_count": 0,
                "derivatives_available_time_violation_count": 0,
                "derivatives_event_time_violation_count": 0,
                "derivatives_missing_count": 0,
                "model_boundary_row_count": 1,
                "prior_exposure_return_violation_count": 1,
                "same_bar_target_return_proxy_row_count": 1,
                "candidate_summaries": [],
                "missing_spec_candidate_ids": [],
                "verdict": "bar_replay_completed_but_stateful_same_bar_execution_proxy_requires_mark_index_paper_runtime_replay",
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
        ),
    )

    report = replay.build_btc_strategy_bar_replay_visibility(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        long_short_report_path=long_short_report,
        long_short_csv_path=long_short_csv,
        high_octane_report_path=high_report,
        high_octane_watchlist_path=high_watchlist,
        high_octane_rolling_path=high_rolling,
        high_yield_followup_report_path=high_yield_report,
    )

    assert report["schema_version"] == "btc_strategy_bar_replay_visibility_v2"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "research_only_bar_replay_passed_for_long_short_high_octane_high_yield_requires_execution_replay_no_paper_no_live"
    assert report["summary"]["check_fail_count"] == 0
    assert report["summary"]["check_warn_count"] == 5
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["broker_access_allowed"] is False
    assert report["summary"]["long_short_completed_bar_violation_count"] == 0
    assert report["summary"]["long_short_future_sentiment_violation_count"] == 0
    assert report["summary"]["high_octane_capital_overlay_same_bar_proxy_row_count"] == 1
    assert report["high_octane_v2_visibility_replay"]["best_margin_over_40pct_threshold"] == 0.011869
    assert report["high_yield_v2_bar_replay"]["row_count"] == 1
    assert report["high_yield_v2_bar_replay"]["prior_exposure_return_violation_count"] == 1

    for name in [
        "btc_strategy_bar_replay_visibility_report.json",
        "btc_strategy_bar_replay_visibility_rows.csv",
        "btc_strategy_bar_replay_visibility_checks.csv",
        "btc_strategy_bar_replay_visibility_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False


def _high_watchlist_row() -> dict:
    return {
        "scenario_id": "ho_top",
        "annual_return_pct": "969.068636",
        "total_return_pct": "36627.902132",
        "min_remaining_capital_pct_after_10pct_spike": "40.011869",
        "watchlist_tier": "survive_40pct",
    }


def _high_rolling_row() -> dict:
    return {
        "scenario_id": "ho_top",
        "total_return_pct": "1435.825771",
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
