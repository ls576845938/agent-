from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.strategy_mining_comparison import (
    build_btc_extended_strategy_mining_comparison,
    write_btc_extended_strategy_mining_comparison,
)


def test_extended_strategy_mining_report_is_research_only_shortlist(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)

    report = write_btc_extended_strategy_mining_comparison(
        market_db_path=paths["db"],
        ga_report_path=paths["ga"],
        ga_review_path=paths["ga_review"],
        derivatives_report_path=paths["derivatives"],
        derivatives_fetch_report_path=paths["derivatives_fetch"],
        derivatives_strategy_gate_path=paths["derivatives_gate"],
        timesfm_report_path=paths["timesfm"],
        intraday_report_path=paths["intraday"],
        intraday_gate_report_path=paths["intraday_gate"],
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_extended_research_shortlist_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["paper_candidate_created"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["guardrails"]["broker_access_allowed"] is False

    ohlcv = report["data_context"]["ohlcv_1h"]
    assert ohlcv["coverage_at_least_90d"] is True
    assert ohlcv["coverage_at_least_180d"] is True
    sentiment = report["data_context"]["derivatives_sentiment"]
    assert sentiment["visible_row_count"] == 720
    assert sentiment["field_non_null_counts"]["funding_rate"] == 720
    assert sentiment["available_time_rule"] == "derivatives rows are visible only when available_time <= decision_time"

    shortlist_ids = {row["candidate_id"] for row in report["extended_research_shortlist"]}
    assert "btc_trend_baseline_momentum_24h_z24" in shortlist_ids
    assert "4h_it04_atr_channel_binary_78f046fffa" in shortlist_ids
    assert "timesfm_zero_shot_h24" not in shortlist_ids
    assert not any(row["source_type"] == "ga_expression_mining" for row in report["extended_research_shortlist"])

    comparison = {row["candidate_id"]: row for row in report["comparison_universe"]}
    assert comparison["btc_ga_factor_mining_current_batch"]["shortlist_decision"] == (
        "not_shortlisted_no_holdout_survivors"
    )
    assert comparison["timesfm_zero_shot_h24"]["shortlist_decision"] == (
        "risk_auxiliary_only_not_strategy_shortlist"
    )
    assert report["excluded_current_batch"][0]["candidate_id"] == "btc_ga_deadbeef_fold1"

    markdown = (tmp_path / "out" / "btc_extended_strategy_mining_comparison_summary_cn.md").read_text(
        encoding="utf-8"
    )
    assert "BTC 扩展研究短名单对比报告" in markdown
    assert "不写 paper 队列，不解锁 live" in markdown


def test_extended_strategy_mining_blocks_unsafe_source_flags(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    ga = json.loads(paths["ga"].read_text(encoding="utf-8"))
    ga["gate"] = {"live_unlock_allowed": True}
    paths["ga"].write_text(json.dumps(ga), encoding="utf-8")

    report = build_btc_extended_strategy_mining_comparison(
        market_db_path=paths["db"],
        ga_report_path=paths["ga"],
        ga_review_path=paths["ga_review"],
        derivatives_report_path=paths["derivatives"],
        derivatives_fetch_report_path=paths["derivatives_fetch"],
        derivatives_strategy_gate_path=paths["derivatives_gate"],
        timesfm_report_path=paths["timesfm"],
        intraday_report_path=paths["intraday"],
        intraday_gate_report_path=paths["intraday_gate"],
        generated_at_utc=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked"
    assert any("unsafe_flag" in blocker for blocker in report["blockers"])
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    db = tmp_path / "market_data.sqlite"
    _write_market_db(db)
    derivatives_rows = tmp_path / "derivatives_sentiment_1h.json"
    _write_derivatives_rows(derivatives_rows)

    paths = {
        "db": db,
        "ga": tmp_path / "ga_factor_mining_report.json",
        "ga_review": tmp_path / "ga_candidate_review_packet.json",
        "derivatives": tmp_path / "btc_derivatives_sentiment_report.json",
        "derivatives_fetch": tmp_path / "btc_free_derivatives_history_fetch_report.json",
        "derivatives_gate": tmp_path / "btc_derivatives_strategy_gate_report.json",
        "timesfm": tmp_path / "btc_timesfm_vs_trend_baseline_oos_report.json",
        "intraday": tmp_path / "btc_intraday_trend_v1_report.json",
        "intraday_gate": tmp_path / "btc_4h_atr_channel_validation_gate_report.json",
    }
    _write_json(paths["ga"], _ga_report())
    _write_json(paths["ga_review"], _ga_review_packet())
    _write_json(paths["derivatives"], _derivatives_report(derivatives_rows))
    _write_json(paths["derivatives_fetch"], _derivatives_fetch_report())
    _write_json(paths["derivatives_gate"], _derivatives_gate_report())
    _write_json(paths["timesfm"], _timesfm_report())
    _write_json(paths["intraday"], _intraday_report())
    _write_json(paths["intraday_gate"], _intraday_gate_report())
    return paths


def _write_market_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE market_klines (
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time_ms INTEGER NOT NULL,
            open_time TEXT NOT NULL,
            close_time_ms INTEGER NOT NULL,
            close_time TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            quote_volume REAL NOT NULL DEFAULT 0,
            trade_count INTEGER NOT NULL DEFAULT 0,
            taker_buy_base_volume REAL NOT NULL DEFAULT 0,
            taker_buy_quote_volume REAL NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'test',
            ingested_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (exchange, symbol, interval, open_time_ms)
        )
        """
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(181 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        rows.append(
            (
                "binance_spot",
                "BTCUSDT",
                "1h",
                int(open_time.timestamp() * 1000),
                open_time.isoformat(),
                int(close_time.timestamp() * 1000),
                close_time.isoformat(),
                100.0,
                101.0,
                99.0,
                100.5,
                10.0,
                1000.0,
                10,
                5.0,
                500.0,
                "test",
                open_time.isoformat(),
                open_time.isoformat(),
            )
        )
    con.executemany(
        """
        INSERT INTO market_klines VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        rows,
    )
    con.commit()
    con.close()


def _write_derivatives_rows(path: Path) -> None:
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(720):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i,
                "funding_rate": 0.0001,
                "long_liquidation_usd": 100.0,
                "short_liquidation_usd": 50.0,
                "long_short_ratio": 1.01,
                "is_final": True,
                "symbol": "BTCUSDT",
                "venue": "okx_swap",
                "source_provider": "okx_free_public",
            }
        )
    _write_json(path, {"rows": rows})


def _ga_report() -> dict:
    return {
        "status": "complete",
        "decision": "research_only_expression_review",
        "blockers": [],
        "data_coverage": {
            "merged_rows_after_lookback": 4320,
            "derivatives_feature_rows_after_lookback": 720,
            "ga_selection_rows": 4152,
            "confirmatory_holdout_rows": 168,
        },
        "ga_config": {"selected_candidate_count": 10, "trial_count": 3728},
        "confirmatory_holdout": {
            "enabled": True,
            "status": "complete",
            "shortlist_for_extended_research_only": [],
            "surviving_candidate_count": 0,
            "candidate_rows": [],
            "baseline_rows": [],
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
    }


def _ga_review_packet() -> dict:
    return {
        "status": "complete",
        "review_summary": {
            "extended_research_shortlist_count": 0,
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        },
        "candidate_reviews": [
            {
                "candidate_id": "btc_ga_deadbeef_fold1",
                "review_verdict": "reject_from_current_review",
                "review_flags": ["cost_stress_no_scenario_survives"],
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            }
        ],
        "gate": {"paper_queue_write_allowed": False, "live_unlock_allowed": False},
    }


def _derivatives_report(rows_path: Path) -> dict:
    return {
        "status": "complete",
        "source_path": str(rows_path),
        "row_count": 720,
        "features": {"visible_row_count": 720, "latest_event_time": "2026-05-30T23:00:00+00:00"},
        "quality": {
            "pit_required": True,
            "role_coverage": {
                "funding_rate": True,
                "liquidation": True,
                "long_short_ratio": True,
                "open_interest": True,
            },
        },
    }


def _derivatives_fetch_report() -> dict:
    return {
        "status": "blocked",
        "blockers": ["btc_free_derivatives_history_fetch_failed_all_public_sources"],
        "fallback_errors": ["okx rubik illegal time range"],
    }


def _derivatives_gate_report() -> dict:
    return {
        "status": "complete",
        "feature_contract": {
            "inputs": [
                "open_interest_usd",
                "funding_rate",
                "long_liquidation_usd",
                "short_liquidation_usd",
                "long_short_ratio",
            ],
            "derived_features": ["open_interest_z_24", "funding_rate_z_24"],
        },
    }


def _timesfm_report() -> dict:
    return {
        "status": "COMPLETE_RESEARCH_ONLY_DIAGNOSTIC",
        "comparison": {
            "metrics": [
                {
                    "model_id": "timesfm_zero_shot_h24",
                    "evaluation": {"profit_factor": 0.2, "total_return": -0.01, "max_drawdown": -0.02},
                },
                {
                    "model_id": "btc_trend_baseline_momentum_24h_z24",
                    "evaluation": {
                        "profit_factor": 1.5,
                        "total_return": 0.02,
                        "max_drawdown": -0.01,
                        "rank_ic": 0.3,
                    },
                },
            ]
        },
        "gate": {"paper_candidate_allowed": False, "live_allowed": False},
    }


def _intraday_report() -> dict:
    return {
        "status": "research_only_intraday_trend_v1_complete",
        "guardrails": {
            "paper_runner_allowed": False,
            "live_order_allowed": False,
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
    }


def _intraday_gate_report() -> dict:
    return {
        "status": "research_validation_passed_manual_review_required",
        "candidate_id": "4h_it04_atr_channel_binary_78f046fffa",
        "selected_metrics": {
            "total_return_pct": 120.9,
            "max_drawdown_pct": -29.1,
            "sharpe_ratio": 1.23,
        },
        "validation_checks": {"walk_forward_pass_rate": True},
        "guardrails": {
            "manual_review_required": True,
            "paper_runner_allowed": False,
            "live_order_allowed": False,
            "order_endpoint_used": False,
            "private_endpoint_used": False,
            "real_order_submitted": False,
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
