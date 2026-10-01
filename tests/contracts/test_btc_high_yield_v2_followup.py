from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.high_yield_v2_followup import build_btc_high_yield_v2_followup


def test_high_yield_v2_followup_runs_three_research_only_steps_and_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    ledger = tmp_path / "observations.jsonl"
    holdout_lock = tmp_path / "holdout_locks.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_holdout_lock(holdout_lock)

    first = build_btc_high_yield_v2_followup(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        observation_ledger_path=ledger,
        holdout_lock_path=holdout_lock,
        funding_ledger_report_path=tmp_path / "missing_funding.json",
        cost_model_report_path=tmp_path / "missing_cost.json",
        perpetual_policy_report_path=tmp_path / "missing_policy.json",
        provider_report_path=tmp_path / "missing_provider.json",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    second = build_btc_high_yield_v2_followup(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out2",
        observation_ledger_path=ledger,
        holdout_lock_path=holdout_lock,
        funding_ledger_report_path=tmp_path / "missing_funding.json",
        cost_model_report_path=tmp_path / "missing_cost.json",
        perpetual_policy_report_path=tmp_path / "missing_policy.json",
        provider_report_path=tmp_path / "missing_provider.json",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert first["schema_version"] == "btc_high_yield_v2_followup_v1"
    assert first["status"] == "complete_research_only"
    assert first["decision"] == "btc_high_yield_v2_followup_research_only_no_paper_no_live"
    assert first["gate"]["paper_queue_write_allowed"] is False
    assert first["gate"]["paper_candidate_created"] is False
    assert first["gate"]["live_unlock_allowed"] is False
    assert first["guardrails"]["order_endpoint_used"] is False

    obs = first["step_1_daily_observation_automation"]
    assert obs["new_observation_written"] is True
    assert obs["already_processed"] is False
    assert obs["observation_count"] == 1
    assert obs["paper_queue_write_allowed"] is False
    assert obs["live_unlock_allowed"] is False
    assert obs["holdout_lock_enforced"] is True
    assert obs["observe_only_violation_count"] == 0
    assert obs["selection_use_blocked_by_lock"] is True
    assert obs["holdout_lock"]["decision_time_relation_counts"] == {"future_observe_only_0_30d": 1}
    second_obs = second["step_1_daily_observation_automation"]
    assert second_obs["new_observation_written"] is False
    assert second_obs["existing_observation_upgraded"] is False
    assert second_obs["already_processed"] is True
    assert second_obs["observation_count"] == 1
    ledger_rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["observer_id"] == "btc_high_yield_v2_frozen_observe_only_v1"
    assert ledger_rows[0]["holdout_lock"]["decision_time_relation"] == "future_observe_only_0_30d"
    assert ledger_rows[0]["holdout_lock"]["selection_use_forbidden"] is True
    assert ledger_rows[0]["paper_candidate_created"] is False
    assert ledger_rows[0]["strategy_skeleton_generated"] is False

    loss = first["step_2_loss_control_v3_narrow_experiment"]
    assert loss["candidate_count"] == 48
    assert loss["expected_candidate_count"] == 48
    assert loss["entry_structure_changed"] is False
    assert {"fast_stop_base_pct", "failed_breakout_exit", "consecutive_loss_trigger_bars"} <= set(loss["searched_components"])
    assert loss["paper_queue_write_allowed"] is False
    assert loss["live_unlock_allowed"] is False
    assert (tmp_path / "out" / "btc_high_yield_v2_loss_control_v3_grid.csv").exists()

    perp = first["step_3_perpetual_execution_evidence"]
    assert perp["status"] == "incomplete_research_evidence"
    assert perp["decision"] == "perp_execution_evidence_incomplete_no_paper_no_live"
    assert "missing_mark_index_price_path" in perp["promotion_blockers"]
    assert "missing_funding_settlement_ledger" in perp["promotion_blockers"]
    assert perp["paper_live_boundary"]["paper_queue_write_allowed"] is False
    assert perp["paper_live_boundary"]["live_unlock_allowed"] is False
    assert perp["derivatives_sentiment_coverage"]["row_count"] > 0
    assert perp["derivatives_sentiment_coverage"]["usable_for_direction"] is False
    assert (tmp_path / "out" / "btc_high_yield_v2_perp_execution_evidence.json").exists()

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["forward_observation_only"] is True
    assert safety["loss_control_v3_research_only"] is True
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    markdown = (tmp_path / "out" / "btc_high_yield_v2_followup_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 高收益 v2 后续三步执行报告" in markdown
    assert "写入 paper 队列：`False`" in markdown


def _write_market_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        create table market_klines (
            exchange text not null,
            symbol text not null,
            interval text not null,
            open_time_ms integer not null,
            open_time text not null,
            close_time_ms integer not null,
            close_time text not null,
            open real not null,
            high real not null,
            low real not null,
            close real not null,
            volume real not null
        )
        """
    )
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(320 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i < 120 * 24:
            drift = 1.00045
        elif i < 210 * 24:
            drift = 0.99955
        else:
            drift = 1.00025 + (0.00045 if i % 72 < 10 else -0.00004)
        price = max(25.0, price * drift)
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                price * 0.999,
                price * 1.002,
                price * 0.998,
                price,
                100.0 + (i % 24),
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(320 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 100.0,
                "funding_rate": 0.00003 + ((i % 96) - 48) * 0.0000005,
                "long_short_ratio": 1.0 + ((i % 144) - 72) / 800.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")


def _write_holdout_lock(path: Path) -> None:
    payload = {
        "schema_version": "btc_confirmatory_holdout_lock_config_v1",
        "lock_config_id": "test_btc_confirmatory_holdout_locks",
        "lock_config_hash": "testhash",
        "latest_common_history_end": "2025-11-10T23:59:59.999000+00:00",
        "global_policy": {
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "parameter_search_requires_no_overlap_with_forbidden_locked_windows": True,
        },
        "locked_windows": [
            {
                "lock_id": "test_future_observe_only",
                "line": "btc_all_current_research_lines",
                "lock_type": "future_confirmatory_holdout_observe_only",
                "locked_before_next_search": True,
                "clean_pre_selection_holdout": True,
                "allowed_uses": ["observe_only_signal_recording", "no_order_forward_monitoring"],
                "forbidden_uses": [
                    "parameter_search",
                    "candidate_ranking",
                    "ga_fitness",
                    "threshold_tuning",
                    "watchlist_replacement",
                    "paper_promotion_evidence_as_sole_basis",
                    "paper_candidate_creation",
                    "live_unlock",
                ],
                "window": {
                    "start_exclusive": "2025-11-10T23:59:59.999000+00:00",
                    "planned_30d_end_inclusive": "2025-12-10T23:59:59.999000+00:00",
                    "planned_60d_end_inclusive": "2026-01-09T23:59:59.999000+00:00",
                    "end_inclusive": "2026-01-09T23:59:59.999000+00:00",
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
