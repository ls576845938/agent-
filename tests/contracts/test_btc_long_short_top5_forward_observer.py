from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.long_short_top5_forward_observer import OBSERVER_ID, run_btc_long_short_top5_forward_observer
from quant_crypto.research.long_short_trend_following_lab import long_short_trend_following_specs


def test_long_short_top5_forward_observer_writes_research_only_rows_idempotently(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "top5_review.json"
    ledger = tmp_path / "observations.jsonl"
    holdout_lock = tmp_path / "holdout_lock.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_top5(source_report)
    _write_holdout_lock(holdout_lock)

    first = run_btc_long_short_top5_forward_observer(
        source_top5_review_report_path=source_report,
        market_db_path=db,
        derivatives_rows_path=derivatives,
        observation_ledger_path=ledger,
        holdout_lock_path=holdout_lock,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=3,
    )
    second = run_btc_long_short_top5_forward_observer(
        source_top5_review_report_path=source_report,
        market_db_path=db,
        derivatives_rows_path=derivatives,
        observation_ledger_path=ledger,
        holdout_lock_path=holdout_lock,
        output_dir=tmp_path / "out2",
        generated_at_utc=datetime(2026, 6, 30, 1, tzinfo=timezone.utc),
        top_n=3,
    )

    assert first["schema_version"] == "btc_long_short_top5_forward_observer_v1"
    assert first["status"] == "complete_research_only"
    assert first["decision"].endswith("_no_paper_no_live")
    assert first["gate"]["forward_observation_only"] is True
    assert first["gate"]["paper_queue_write_allowed"] is False
    assert first["gate"]["paper_candidate_created"] is False
    assert first["gate"]["live_unlock_allowed"] is False
    assert first["guardrails"]["order_endpoint_used"] is False
    assert first["observer_design"]["holdout_lock_enforced"] is True
    assert first["holdout_lock"]["observe_only_violation_count"] == 0
    assert first["holdout_lock"]["selection_use_blocked_by_lock"] is True
    assert first["observation_automation"]["new_observation_rows_written"] == 3
    assert second["observation_automation"]["new_observation_rows_written"] == 0
    assert second["observation_automation"]["already_processed_count"] == 3

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    for row in rows:
        assert row["schema_version"] == "btc_long_short_top5_forward_observation_row_v1"
        assert row["observer_id"] == OBSERVER_ID
        assert row["decision_signal"]["side"] in {"long", "short", "flat"}
        assert row["decision_signal"]["applies_next_bar"] is True
        assert row["theoretical_exposure"]["already_shifted_one_4h_bar"] is True
        assert row["holdout_lock"]["observe_only_allowed"] is True
        assert row["holdout_lock"]["selection_use_forbidden"] is True
        assert "30d" in row["recent_window_metrics"]
        assert "60d" in row["recent_window_metrics"]
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
    assert safety["live_unlock_allowed"] is False
    assert (tmp_path / "out" / "btc_long_short_top5_forward_observations_latest.csv").exists()


def test_long_short_top5_forward_observer_blocks_when_source_gate_unlocked(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "top5_review.json"
    holdout_lock = tmp_path / "holdout_lock.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_top5(source_report, paper_queue_write_allowed=True)
    _write_holdout_lock(holdout_lock)

    report = run_btc_long_short_top5_forward_observer(
        source_top5_review_report_path=source_report,
        market_db_path=db,
        derivatives_rows_path=derivatives,
        observation_ledger_path=tmp_path / "observations.jsonl",
        holdout_lock_path=holdout_lock,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=3,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "long_short_top5_forward_observer_blocked_no_write_no_paper_no_live"
    assert "btc_long_short_top5_observer_source_paper_gate_not_locked" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def test_long_short_top5_forward_observer_blocks_when_holdout_lock_missing(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "top5_review.json"
    ledger = tmp_path / "observations.jsonl"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_top5(source_report)

    report = run_btc_long_short_top5_forward_observer(
        source_top5_review_report_path=source_report,
        market_db_path=db,
        derivatives_rows_path=derivatives,
        observation_ledger_path=ledger,
        holdout_lock_path=tmp_path / "missing_holdout_lock.json",
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=3,
    )

    assert report["status"] == "blocked"
    assert "btc_observe_only_holdout_lock_config_missing" in report["blockers"]
    assert not ledger.exists()
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _write_source_top5(path: Path, *, paper_queue_write_allowed: bool = False) -> None:
    wanted = {
        "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
        "formal_donchian_w240_d50_200_atr20_cd0_fail0_risknone",
        "formal_donchian_w180_d50_200_atr20_cd12_fail0_risknone",
    }
    specs = [spec for spec in long_short_trend_following_specs(run_profile="formal_narrow") if spec.variant_id in wanted]
    rows = [
        {
            "rank": idx,
            "candidate_id": spec.candidate_id,
            "variant_id": spec.variant_id,
            "holdout_passed": True,
            "trend_profile_passed": True,
            "review_decision": "trend_following_concentration_expected_requires_forward_confirmation",
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }
        for idx, spec in enumerate(specs, 1)
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_long_short_top5_review_v1",
                "status": "complete_research_only",
                "decision": "btc_long_short_top5_review_research_only_no_paper_no_live",
                "candidate_rows": rows,
                "gate": {
                    "paper_queue_write_allowed": paper_queue_write_allowed,
                    "paper_candidate_created": False,
                    "live_unlock_allowed": False,
                    "broker_access_allowed": False,
                },
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
    for i in range(320 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        drift = 1.00055 if i < 120 * 24 else (0.9995 if i < 210 * 24 else 1.00035)
        price = max(30.0, price * drift)
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
                price * 1.004,
                price * 0.996,
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
