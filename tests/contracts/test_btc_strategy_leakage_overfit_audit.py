from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_crypto.research import btc_strategy_leakage_overfit_audit as audit


def test_strategy_leakage_overfit_audit_flags_threshold_boundary_and_research_only(tmp_path: Path) -> None:
    long_short_report = tmp_path / "long_short_report.json"
    long_short_csv = tmp_path / "long_short.csv"
    long_short_grid = tmp_path / "long_short_grid.csv"
    high_report = tmp_path / "high_report.json"
    high_grid = tmp_path / "high_grid.csv"
    high_watchlist = tmp_path / "high_watchlist.csv"
    high_rolling = tmp_path / "high_rolling.csv"
    bar_replay_report = tmp_path / "bar_replay_report.json"
    holdout_lock_report = tmp_path / "holdout_lock_report.json"
    long_short_forward_report = tmp_path / "long_short_forward_report.json"
    attack_forward_report = tmp_path / "attack_forward_report.json"
    derivatives_fetch_audit = tmp_path / "derivatives_fetch_audit.json"
    _write_json(long_short_report, _long_short_report())
    _write_csv(long_short_csv, [_long_short_row()])
    _write_csv(long_short_grid, [_long_short_grid_row(), {**_long_short_grid_row(), "candidate_id": "neighbor", "variant_id": "formal_donchian_w180_d50_200_atr20_cd6_fail0_risknone", "annual_return_pct": "28"}])
    _write_json(high_report, _high_report())
    high_grid_rows = [_high_watchlist_row()]
    high_grid_rows.extend(
        {
            **_high_watchlist_row(),
            "scenario_id": f"too_hot_{idx}",
            "annual_return_pct": str(5000 - idx),
            "min_remaining_capital_pct_after_10pct_spike": "0.5",
            "max_total_exposed": "10",
            "max_attack_exposed": "3",
            "attack_template_count": "3",
        }
        for idx in range(1000)
    )
    _write_csv(high_grid, high_grid_rows)
    _write_csv(high_watchlist, [_high_watchlist_row()])
    _write_csv(high_rolling, [_high_rolling_row("2024-01-01"), _high_rolling_row("2024-01-31", total_return="500")])
    _write_json(bar_replay_report, _bar_replay_report())
    _write_json(holdout_lock_report, _holdout_lock_report())
    _write_json(long_short_forward_report, _forward_report("long_short_top5_forward_observer_active_no_paper_no_live"))
    _write_json(attack_forward_report, _forward_report("attack_forward_observer_active_under_30d_no_paper_no_live"))
    _write_json(derivatives_fetch_audit, _derivatives_fetch_audit())

    report = audit.build_btc_strategy_leakage_overfit_audit(
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
        long_short_report_path=long_short_report,
        long_short_csv_path=long_short_csv,
        long_short_grid_path=long_short_grid,
        high_octane_report_path=high_report,
        high_octane_grid_path=high_grid,
        high_octane_watchlist_path=high_watchlist,
        high_octane_rolling_path=high_rolling,
        bar_replay_report_path=bar_replay_report,
        holdout_lock_report_path=holdout_lock_report,
        long_short_forward_report_path=long_short_forward_report,
        attack_forward_report_path=attack_forward_report,
        derivatives_fetch_audit_path=derivatives_fetch_audit,
    )

    assert report["schema_version"] == "btc_strategy_leakage_overfit_audit_v2"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "research_only_overfit_risk_high_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    high = report["high_octane_v2_audit"]
    assert high["best_margin_over_40pct_threshold"] == 0.011869
    assert high["overfit_verdict"] == "parameter_boundary_mined_research_only"
    assert high["future_leakage_static_verdict"] == "model_boundary_risk_same_bar_proxy_requires_execution_replay"
    assert high["threshold_margin_by_tier_pct"]["survive_40pct"] == 0.011869
    assert high["future_sentiment_violation_count"] == 0
    assert high["capital_overlay_execution_boundary_verdict"] == "same_bar_execution_proxy_requires_strict_risk_stress_and_mark_index_replay"
    assert high["parameter_mining_audit"]["likely_parameter_mined_boundary_candidate"] is True
    assert high["parameter_mining_audit"]["parameter_mining_verdict"] == "strong_parameter_mining_symptoms_threshold_boundary_research_only"
    assert report["summary"]["high_octane_likely_parameter_mined_boundary_candidate"] is True
    assert report["summary"]["forward_observe_clean_confirmation_ready"] is False
    assert report["summary"]["forward_observe_only_anchor_rows_so_far"] is True
    assert report["summary"]["forward_observe_selection_use_blocked_by_lock"] is True
    assert report["summary"]["data_coverage_verdict"] == "free_oi_funding_sentiment_coverage_extended_for_visibility_audit"
    assert report["summary"]["data_coverage_bar_replay_missing_count"] == 0
    assert report["summary"]["data_coverage_liquidation_one_hour_history_complete"] is False
    assert "free_source_full_1h_liquidation_history_still_missing" in report["warnings"]

    long_short = report["long_short_top5_audit"]
    assert long_short["future_leakage_static_verdict"] == "no_direct_lookahead_detected_from_static_checks"
    assert long_short["overfit_verdict"] == "no_direct_leakage_but_forward_confirmation_required"
    assert long_short["future_sentiment_violation_count"] == 0
    assert long_short["high_concentration_count"] == 1
    assert long_short["parameter_mining_audit"]["full_grid_count"] == 2
    assert long_short["bar_replay_current_shift_violation_count"] == 0

    check_ids = {row["check_id"]: row["status"] for row in report["leakage_checks"]}
    assert check_ids["same_bar_return_model_boundary"] == "warn"
    assert check_ids["current_bar_adverse_model_boundary"] == "warn"
    assert check_ids["bar_replay_no_current_or_next_shift_violation"] == "pass"
    assert check_ids["bar_replay_direction_visibility_no_shift_violation"] == "pass"
    assert check_ids["bar_replay_execution_replay_still_required"] == "warn"
    assert check_ids["confirmatory_holdout_lock_present"] == "pass"
    assert check_ids["historical_selection_windows_block_reuse"] == "pass"
    assert check_ids["observe_only_rows_have_no_selection_use"] == "pass"
    assert check_ids["thirty_sixty_day_forward_observation_complete"] == "warn"

    holdout = report["holdout_and_forward_observe_audit"]
    assert holdout["selection_use_blocked_by_lock"] is True
    assert holdout["observe_only_violation_count"] == 0
    assert holdout["only_anchor_rows_so_far"] is True
    assert holdout["verdict"] == "future_observe_only_not_yet_confirmatory"

    coverage = report["data_coverage_audit"]
    assert coverage["free_public_data_only"] is True
    assert coverage["derivatives_row_count"] == 21832
    assert coverage["bar_replay_derivatives_missing_count"] == 0
    assert coverage["liquidation_one_hour_history_complete"] is False
    assert coverage["liquidation_gate_eligible"] is False
    assert "free_source_full_1h_liquidation_history_not_available" in coverage["unfilled_free_data_gaps"]

    for name in [
        "btc_strategy_leakage_overfit_audit_report.json",
        "btc_strategy_leakage_overfit_audit_candidates.csv",
        "btc_strategy_leakage_overfit_audit_checks.csv",
        "btc_strategy_leakage_overfit_audit_summary_cn.md",
        "paper_live_safety_status.json",
    ]:
        assert (tmp_path / "out" / name).exists()
    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    summary_cn = (tmp_path / "out" / "btc_strategy_leakage_overfit_audit_summary_cn.md").read_text(encoding="utf-8")
    assert "数据覆盖" in summary_cn
    assert "1H liquidation 完整历史" in summary_cn


def _long_short_report() -> dict:
    return {
        "status": "complete_research_only",
        "decision": "btc_long_short_top5_review_research_only_no_paper_no_live",
        "input": {
            "completed_bar_rule": "1h completed bars only",
            "derivatives_available_time_rule": "derivatives rows aligned by available_time <= decision_time",
        },
        "review_design": {
            "clean_pre_selection_holdout": False,
            "clean_pre_selection_holdout_note": "post-selection confirmation",
        },
    }


def _long_short_row() -> dict:
    return {
        "rank": "1",
        "candidate_id": "ls_top",
        "variant_id": "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
        "entry_window": "240",
        "full_total_return_pct": "100",
        "full_max_drawdown_pct": "-10",
        "holdout_total_return_pct": "20",
        "holdout_passed": "True",
        "top_3_positive_trade_share": "0.70",
        "forward_30d_status": "pending_future_data",
        "forward_60d_status": "pending_future_data",
        "paper_queue_write_allowed": "False",
        "live_unlock_allowed": "False",
    }


def _long_short_grid_row() -> dict:
    return {
        "candidate_id": "ls_top",
        "variant_id": "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
        "optimization_stage": "formal_narrow_grid",
        "annual_return_pct": "35",
        "retention_decision": "retain_long_short_research_watchlist_only",
    }


def _high_report() -> dict:
    return {
        "status": "complete_research_only",
        "decision": "btc_high_octane_attack_sleeve_lab_research_only_no_paper_no_live",
        "input": {"direction_source": "existing frozen Donchian high-yield v3 direction"},
        "research_design": {"max_research_leverage": 10.0},
        "summary": {
            "best_scenario_id": "ho_top",
            "best_min_remaining_after_10pct_spike": 40.011869,
            "watchlist_tier_counts": {"survive_40pct": 1, "survive_50pct": 0, "survive_60pct": 0},
            "scenario_count": 2,
            "watchlist_count": 1,
        },
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }


def _high_watchlist_row() -> dict:
    return {
        "scenario_id": "ho_top",
        "atr_step": "0.35",
        "max_total_exposed": "10",
        "max_attack_exposed": "2",
        "attack_template_count": "2",
        "extract_policy": "none",
        "reserve_requires_pullback": "True",
        "attack_delay_profile": "late",
        "annual_return_pct": "969.068636",
        "total_return_pct": "36627.902132",
        "max_drawdown_abs_pct": "27.098772",
        "min_remaining_capital_pct_after_10pct_spike": "40.011869",
        "watchlist_tier": "survive_40pct",
        "paper_queue_write_allowed": "False",
        "paper_candidate_created": "False",
        "live_unlock_allowed": "False",
    }


def _bar_replay_report() -> dict:
    return {
        "long_short_top5_bar_replay": {
            "current_shift_violation_count": 0,
            "next_shift_violation_count": 0,
            "completed_bar_violation_count": 0,
            "derivatives_available_time_violation_count": 0,
            "future_sentiment_violation_count": 0,
            "derivatives_event_time_violation_count": 0,
            "verdict": "bar_replay_no_shift_or_visibility_violations",
        },
        "high_octane_v2_visibility_replay": {
            "current_shift_violation_count": 0,
            "next_shift_violation_count": 0,
            "completed_bar_violation_count": 0,
            "derivatives_available_time_violation_count": 0,
            "future_sentiment_violation_count": 0,
            "derivatives_event_time_violation_count": 0,
            "same_bar_return_proxy_row_count": 100,
            "same_bar_intrabar_high_low_proxy_row_count": 100,
            "capital_overlay_same_bar_proxy_row_count": 100,
            "direction_signal_visibility_verdict": "direction_signal_visible_no_available_time_violation",
            "capital_overlay_execution_boundary_verdict": "same_bar_execution_proxy_requires_strict_risk_stress_and_mark_index_replay",
            "verdict": "visibility_replay_completed_but_capital_overlay_same_bar_proxy_requires_strict_risk_stress",
        },
    }


def _holdout_lock_report() -> dict:
    return {
        "status": "complete_research_only",
        "decision": "btc_confirmatory_holdout_locked_research_only_no_paper_no_live",
        "summary": {
            "lock_count": 3,
            "historical_seen_lock_count": 2,
            "future_observe_only_lock_count": 1,
            "latest_common_history_end": "2026-06-28T23:59:59.999000+00:00",
            "self_check_violation_count": 7,
        },
        "lock_config": {
            "latest_common_history_end": "2026-06-28T23:59:59.999000+00:00",
            "locked_windows": [
                {
                    "lock_id": "future",
                    "lock_type": "future_confirmatory_holdout_observe_only",
                    "window": {
                        "start_exclusive": "2026-06-28T23:59:59.999000+00:00",
                        "planned_30d_end_inclusive": "2026-07-28T23:59:59.999000+00:00",
                        "planned_60d_end_inclusive": "2026-08-27T23:59:59.999000+00:00",
                    },
                }
            ],
        },
    }


def _forward_report(decision: str) -> dict:
    return {
        "status": "complete_research_only",
        "decision": decision,
        "holdout_lock": {
            "latest_common_history_end": "2026-06-28T23:59:59.999000+00:00",
            "latest_decision_time": "2026-06-28T23:59:59.999000+00:00",
            "decision_time_relation_counts": {"locked_history_or_anchor": 1},
            "observe_only_violation_count": 0,
            "selection_use_blocked_by_lock": True,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "observation_progress": {
            "observation_days": 1,
            "under_30d": True,
            "under_60d": True,
        },
        "gate": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _derivatives_fetch_audit() -> dict:
    return {
        "status": "complete",
        "public_market_data_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "row_count": 21832,
        "event_start": "2024-01-01T01:00:00+00:00",
        "event_end": "2026-06-30T01:00:00+00:00",
        "field_non_null_counts": {
            "open_interest_usd": 21832,
            "funding_rate": 21767,
            "long_liquidation_usd": 720,
            "short_liquidation_usd": 720,
            "long_short_ratio": 21829,
        },
        "extra_field_non_null_counts": {
            "open_interest": 21832,
            "top_trader_long_short_ratio": 21825,
            "top_trader_long_short_position_ratio": 21829,
            "taker_buy_sell_ratio": 21832,
        },
        "liquidation_policy": {
            "one_hour_history_complete": False,
            "source": "OKX 720h tail only",
            "gate_eligible": False,
        },
        "download_attempts": [
            {
                "mode": "binance_vision_funding_monthly",
                "date_or_month": "2026-06",
                "status_code": 404,
                "rows": 0,
                "error": "HTTPError:HTTP Error 404: Not Found",
            }
        ],
    }


def _high_rolling_row(start: str, *, total_return: str = "1000") -> dict:
    return {
        "scenario_id": "ho_top",
        "rolling_start_time": start,
        "total_return_pct": total_return,
        "min_remaining_capital_pct_after_10pct_spike": "45",
        "full_wipeout": "False",
        "paper_queue_write_allowed": "False",
        "live_unlock_allowed": "False",
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
