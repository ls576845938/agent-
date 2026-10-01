from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.high_yield_v2_confirmation import (
    FROZEN_VARIANT_ID,
    build_btc_high_yield_v2_confirmation,
)


def test_high_yield_v2_confirmation_freezes_candidate_and_stays_research_only(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    near_miss = tmp_path / "near_miss.json"
    top5 = tmp_path / "top5.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_near_miss_report(near_miss)
    _write_top5_report(top5)

    report = build_btc_high_yield_v2_confirmation(
        market_db_path=db,
        derivatives_rows_path=derivatives,
        source_near_miss_report_path=near_miss,
        source_top5_review_path=top5,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        holdout_days=90,
    )

    assert report["schema_version"] == "btc_high_yield_v2_confirmation_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_high_yield_v2_confirmation_research_only_no_paper_no_live"
    assert report["frozen_candidate"]["variant_id"] == FROZEN_VARIANT_ID
    assert report["frozen_candidate"]["candidate_frozen_before_confirmation"] is True
    assert report["frozen_candidate"]["further_parameter_search_allowed_in_this_packet"] is False
    assert report["confirmation_design"]["holdout_locked_for_this_review"] is True
    assert report["confirmation_design"]["clean_pre_selection_holdout"] is False
    assert report["confirmation_design"]["holdout_used_for_selection"] is False

    assert "confirmation_holdout" in report
    assert "annual_attribution" in report
    assert "market_regime_attribution" in report
    assert "return_concentration" in report
    assert "max_drawdown_attribution" in report
    assert "trend_following_profile" in report
    assert "cost_stress_summary" in report
    assert "leverage_model_review" in report

    stress_rows = report["cost_stress_summary"]["stress_rows"]
    assert [row["scenario"] for row in stress_rows] == ["base", "costs_2x", "costs_5x"]
    assert all("survives_positive_return" in row for row in stress_rows)
    assert report["leverage_model_review"]["max_leverage_policy"] == 2.5
    assert report["leverage_model_review"]["paper_queue_write_allowed"] is False
    assert report["leverage_model_review"]["live_unlock_allowed"] is False
    assert "perpetual mark/index price path" in report["leverage_model_review"]["missing_before_paper"]

    forward = report["forward_observation"]
    assert forward["daily_plan_row_count"] == 60
    assert forward["policy"] == "future_30d_60d_observe_only_no_paper_no_live"
    assert forward["paper_queue_write_allowed"] is False
    assert forward["live_unlock_allowed"] is False
    plan_rows = list(csv.DictReader((tmp_path / "out" / "btc_high_yield_v2_forward_observation_plan.csv").open(encoding="utf-8")))
    assert len(plan_rows) == 60
    assert {row["status"] for row in plan_rows} == {"pending_future_data"}
    assert {row["paper_queue_write_allowed"] for row in plan_rows} == {"False"}

    comparison = report["robust_top5_same_window_comparison"]
    assert comparison["row_count"] >= 2
    assert comparison["rows"][0]["bucket"] == "high_yield_v2_frozen"
    assert any(row["bucket"] == "robust_long_short_top5" for row in comparison["rows"])
    assert comparison["paper_queue_write_allowed"] is False
    assert comparison["live_unlock_allowed"] is False

    summary = report["confirmation_summary"]
    assert summary["decision"] == "research_only_forward_observation_required_no_paper_no_live"
    assert "forward_30d_60d_observation_required" in summary["failure_or_caution_flags"]
    assert "perp_execution_evidence_required_before_paper" in summary["failure_or_caution_flags"]
    assert summary["paper_queue_write_allowed"] is False
    assert summary["live_unlock_allowed"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False

    safety = json.loads((tmp_path / "out" / "paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert safety["status"] == "research_only"
    assert safety["forward_observation_required"] is True
    assert safety["paper_queue_write_allowed"] is False
    assert safety["live_unlock_allowed"] is False
    markdown = (tmp_path / "out" / "btc_high_yield_v2_confirmation_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC 高收益 v2 冻结候选确认包" in markdown
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


def _write_near_miss_report(path: Path) -> None:
    row = {
        "variant_id": FROZEN_VARIANT_ID,
        "annual_return_pct": 66.42,
        "max_drawdown_abs_pct": 22.07,
        "profit_factor": 1.44,
        "retention_decision": "retain_high_yield_near_miss_research_watchlist_only",
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_small_account_high_yield_near_miss_review_v1",
                "high_yield_near_miss_research_watchlist": [row],
                "v2_narrow_grid_rows": [row],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_top5_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_long_short_top5_review_v1",
                "candidate_rows": [
                    {
                        "rank": 1,
                        "variant_id": "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
                        "full_total_return_pct": 116.22,
                        "full_max_drawdown_pct": -11.46,
                        "full_profit_factor": 1.44,
                        "holdout_total_return_pct": 39.70,
                        "holdout_max_drawdown_pct": -10.04,
                        "holdout_profit_factor": 1.89,
                        "review_decision": "trend_following_concentration_expected_requires_forward_confirmation",
                    }
                ],
                "candidate_reviews": [
                    {
                        "variant_id": "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
                        "full_metrics": {
                            "annual_return_pct": 36.25,
                            "calmar_ratio": 3.16,
                            "average_exposure": 0.11,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
