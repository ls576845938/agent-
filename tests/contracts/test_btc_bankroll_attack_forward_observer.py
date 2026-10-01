from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.bankroll_attack_forward_observer import (
    OBSERVER_ID,
    _observation_progress,
    run_btc_bankroll_attack_forward_observer,
)
from quant_crypto.research.bankroll_attack_top_confirmation_review import TOP_SCENARIO_ID


def test_attack_forward_observer_writes_daily_observe_only_row_idempotently(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "top_confirmation.json"
    ledger = tmp_path / "observations.jsonl"
    holdout_lock = tmp_path / "holdout_lock.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_confirmation(source_report, forward_allowed=True)
    _write_holdout_lock(holdout_lock)

    first = run_btc_bankroll_attack_forward_observer(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_top_confirmation_report_path=source_report,
        observation_ledger_path=ledger,
        holdout_lock_path=holdout_lock,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    second = run_btc_bankroll_attack_forward_observer(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_top_confirmation_report_path=source_report,
        observation_ledger_path=ledger,
        holdout_lock_path=holdout_lock,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, 1, tzinfo=timezone.utc),
    )

    assert first["schema_version"] == "btc_bankroll_attack_forward_observer_v1"
    assert first["status"] == "complete_research_only"
    assert first["decision"].endswith("_no_paper_no_live")
    assert first["gate"]["forward_observation_only"] is True
    assert first["gate"]["paper_queue_write_allowed"] is False
    assert first["gate"]["paper_candidate_created"] is False
    assert first["gate"]["live_unlock_allowed"] is False
    assert first["guardrails"]["order_endpoint_used"] is False
    assert first["guardrails"]["broker_access_allowed"] is False
    assert first["observer_design"]["holdout_lock_enforced"] is True
    assert first["holdout_lock"]["observe_only_violation_count"] == 0
    assert first["holdout_lock"]["selection_use_blocked_by_lock"] is True
    assert first["observation_automation"]["new_observation_written"] is True
    assert second["observation_automation"]["already_processed"] is True
    assert second["observation_automation"]["new_observation_written"] is False

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["schema_version"] == "btc_bankroll_attack_forward_observation_row_v1"
    assert row["observer_id"] == OBSERVER_ID
    assert row["top_scenario_id"] == TOP_SCENARIO_ID
    assert row["daily_signal"]["side"] in {"long", "short", "flat"}
    assert "signal_age_4h_bars" in row["daily_signal"]
    assert "exposed_sleeve_count" in row["theoretical_sleeve_exposure"]
    assert "attack_exposed_sleeve_count" in row["theoretical_sleeve_exposure"]
    assert "remaining_after_10pct_spike_pct" in row["spike_remaining_capital"]
    assert "latest_bar_funding_cost_5x_amount" in row["funding_cost_pressure"]
    assert "latest_bar_trading_cost_5x_amount" in row["funding_cost_pressure"]
    assert row["holdout_lock"]["observe_only_allowed"] is True
    assert row["holdout_lock"]["selection_use_forbidden"] is True
    assert isinstance(row["downgrade_triggered"], bool)
    assert isinstance(row["downgrade_reasons"], list)
    assert row["paper_queue_write_allowed"] is False
    assert row["paper_candidate_created"] is False
    assert row["live_unlock_allowed"] is False
    assert row["strategy_skeleton_generated"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["forward_observation_only"] is True
    assert safety["holdout_lock_enforced"] is True
    assert safety["observe_only_violation_count"] == 0
    assert safety["selection_use_blocked_by_lock"] is True
    assert safety["paper_queue_write_allowed"] is False
    assert safety["paper_candidate_created"] is False
    assert safety["live_unlock_allowed"] is False
    assert safety["broker_access_allowed"] is False
    assert (tmp_path / "out" / "btc_bankroll_attack_forward_observations_latest.csv").exists()


def test_attack_forward_observer_blocks_without_confirmation_allowance(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "top_confirmation.json"
    ledger = tmp_path / "observations.jsonl"
    holdout_lock = tmp_path / "holdout_lock.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_confirmation(source_report, forward_allowed=False)
    _write_holdout_lock(holdout_lock)

    report = run_btc_bankroll_attack_forward_observer(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_top_confirmation_report_path=source_report,
        observation_ledger_path=ledger,
        holdout_lock_path=holdout_lock,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "attack_forward_observer_blocked_no_write_no_paper_no_live"
    assert "btc_attack_forward_observer_source_not_observation_allowed" in report["blockers"]
    assert not ledger.exists()
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_attack_forward_observer_blocks_when_holdout_lock_missing(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "top_confirmation.json"
    ledger = tmp_path / "observations.jsonl"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_confirmation(source_report, forward_allowed=True)

    report = run_btc_bankroll_attack_forward_observer(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_top_confirmation_report_path=source_report,
        observation_ledger_path=ledger,
        holdout_lock_path=tmp_path / "missing_holdout_lock.json",
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked"
    assert "btc_observe_only_holdout_lock_config_missing" in report["blockers"]
    assert not ledger.exists()
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_attack_forward_observer_progress_counts_unique_observation_days_not_calendar_span() -> None:
    progress = _observation_progress(
        [
            {"decision_time": "2026-06-28T23:59:59.999000+00:00", "downgrade_triggered": False},
            {"decision_time": "2026-07-01T03:59:59.999000+00:00", "downgrade_triggered": False},
        ]
    )

    assert progress["observation_count"] == 2
    assert progress["observation_days"] == 2
    assert progress["unique_observation_days"] == 2
    assert progress["calendar_span_days"] == 3
    assert progress["minimum_30d_complete"] is False
    assert progress["minimum_60d_complete"] is False


def _write_source_confirmation(path: Path, *, forward_allowed: bool) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_bankroll_attack_top_confirmation_review_v1",
                "status": "complete_research_only",
                "decision": "eligible_for_30_60_day_forward_observation_research_only_no_paper_no_live" if forward_allowed else "not_forward_observation_ready_due_to_liquidation_funding_or_path_dependency",
                "summary": {"top_scenario_id": TOP_SCENARIO_ID},
                "forward_observation_decision": {
                    "decision": "eligible_for_30_60_day_forward_observation_research_only_no_paper_no_live" if forward_allowed else "not_forward_observation_ready_due_to_liquidation_funding_or_path_dependency",
                    "paper_queue_write_allowed": False,
                    "paper_candidate_created": False,
                    "live_unlock_allowed": False,
                    "strategy_skeleton_generated": False,
                },
                "gate": {
                    "forward_observation_research_only_allowed": forward_allowed,
                    "paper_queue_write_allowed": False,
                    "paper_candidate_created": False,
                    "live_unlock_allowed": False,
                    "broker_access_allowed": False,
                },
                "warnings": ["btc_attack_top_confirmation_research_only_no_paper_no_live"],
            }
        ),
        encoding="utf-8",
    )


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
    for i in range(260 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i < 70 * 24:
            drift = 1.00055
        elif i < 130 * 24:
            drift = 0.99935
        else:
            drift = 1.00032 + (0.0006 if i % 72 < 8 else -0.00008)
        price = max(25.0, price * drift)
        spike = 1.035 if i % 240 == 20 else 1.002
        dip = 0.965 if i % 240 == 21 else 0.998
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
                price * spike,
                price * dip,
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
    for i in range(260 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 100.0,
                "funding_rate": 0.00004 + ((i % 96) - 48) * 0.0000008,
                "long_short_ratio": 1.0 + ((i % 144) - 72) / 700.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")


def _write_holdout_lock(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_confirmatory_holdout_lock_config_v1",
                "lock_config_id": "test_btc_confirmatory_holdout_locks",
                "lock_config_hash": "test-hash",
                "latest_common_history_end": "2025-01-01T00:00:00+00:00",
                "global_policy": {
                    "parameter_search_requires_no_overlap_with_forbidden_locked_windows": True,
                    "paper_queue_write_allowed": False,
                    "live_unlock_allowed": False,
                },
                "locked_windows": [
                    {
                        "lock_id": "test_future_observe_only",
                        "line": "btc_all_current_research_lines",
                        "lock_type": "future_confirmatory_holdout_observe_only",
                        "window": {
                            "start_exclusive": "2025-01-01T00:00:00+00:00",
                            "planned_30d_end_inclusive": "2025-01-31T00:00:00+00:00",
                            "planned_60d_end_inclusive": "2026-12-31T00:00:00+00:00",
                            "end_inclusive": "2026-12-31T00:00:00+00:00",
                            "open_until_observation_complete": True,
                        },
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
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
