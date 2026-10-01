from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_crypto.research.long_short_top5_review import build_btc_long_short_top5_review
from quant_crypto.research.long_short_trend_following_lab import long_short_trend_following_specs


def test_long_short_top5_review_is_research_only_and_has_required_sections(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "source_report.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    _write_source_report(source_report)

    report = build_btc_long_short_top5_review(
        source_report_path=source_report,
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=2,
        holdout_days=90,
    )

    assert report["schema_version"] == "btc_long_short_top5_review_v1"
    assert report["status"] == "complete_research_only"
    assert report["decision"] == "btc_long_short_top5_review_research_only_no_paper_no_live"
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert report["guardrails"]["order_endpoint_used"] is False
    assert report["source"]["top_n_reviewed"] == 2
    assert report["review_design"]["holdout_locked_for_this_review"] is True
    assert report["review_design"]["clean_pre_selection_holdout"] is False
    assert len(report["candidate_rows"]) == 2
    assert report["review_summary"]["candidate_count"] == 2
    assert "trend_profile_pass_count" in report["review_summary"]
    assert "forward_observation_pending_count" in report["review_summary"]
    for row in report["candidate_rows"]:
        assert "trend_profile_passed" in row
        assert "large_winner_trend_passed" in row
        assert "loss_control_passed" in row
        assert "trendless_phase_passed" in row
        assert "yearly_opportunity_passed" in row
        assert row["forward_30d_status"] == "pending_future_data"
        assert row["forward_60d_status"] == "pending_future_data"
    for review in report["candidate_reviews"]:
        assert "confirmation_holdout" in review
        assert "annual_attribution" in review
        assert "market_regime_attribution" in review
        assert "return_concentration" in review
        assert "max_drawdown_attribution" in review
        assert "trend_following_profile" in review
        assert "forward_observation" in review
        assert review["trend_following_profile"]["profile_name"] == "trend_following_specific_review"
        assert review["forward_observation"]["policy"] == "future_30d_60d_observe_only_no_paper_no_live"
        assert "failure_review" in review
        assert review["failure_review"]["paper_queue_write_allowed"] is False
    assert (tmp_path / "out" / "btc_long_short_top5_review_report.json").exists()
    assert (tmp_path / "out" / "btc_long_short_top5_review_candidates.csv").exists()
    markdown = (tmp_path / "out" / "btc_long_short_top5_review_summary_cn.md").read_text(encoding="utf-8")
    assert "BTC Long/Short Top 5 复核包" in markdown
    assert "趋势跟踪专用评价口径" in markdown
    assert "不写 paper 队列" in markdown


def test_review_uses_source_watchlist_order(tmp_path: Path) -> None:
    db = tmp_path / "market.sqlite"
    derivatives = tmp_path / "derivatives.json"
    source_report = tmp_path / "source_report.json"
    _write_market_db(db)
    _write_derivatives(derivatives)
    specs = _review_specs()
    _write_source_report(source_report, specs=[specs[1], specs[0]])

    report = build_btc_long_short_top5_review(
        source_report_path=source_report,
        market_db_path=db,
        derivatives_rows_path=derivatives,
        output_dir=tmp_path / "out",
        generated_at_utc=datetime(2026, 6, 30, tzinfo=timezone.utc),
        top_n=2,
        holdout_days=90,
    )

    assert [row["candidate_id"] for row in report["candidate_rows"]] == [specs[1].candidate_id, specs[0].candidate_id]


def _review_specs() -> list:
    specs = long_short_trend_following_specs(run_profile="formal_narrow")
    wanted = [
        "formal_donchian_w120_d50_200_atr20_cd0_fail0_risknone",
        "formal_donchian_w180_d50_200_atr20_cd6_fail0_risknone",
    ]
    return [next(spec for spec in specs if spec.variant_id == variant_id) for variant_id in wanted]


def _write_source_report(path: Path, *, specs: list | None = None) -> None:
    specs = specs or _review_specs()
    rows = [
        {
            "candidate_id": spec.candidate_id,
            "variant_id": spec.variant_id,
            "params_hash": "test",
            "retention_decision": "retain_long_short_research_watchlist_only",
        }
        for spec in specs
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": "btc_long_short_trend_following_lab_v1",
                "code_commit": "test",
                "validation_design": {"candidate_count": 1452, "run_profile": "formal_narrow"},
                "long_short_research_watchlist": rows,
            },
            ensure_ascii=False,
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
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(720 * 24):
        open_time = start + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        if i < 220 * 24:
            drift = 1.00042
        elif i < 420 * 24:
            drift = 0.99945
        elif i < 560 * 24:
            drift = 1.00025 + (0.00025 if i % 96 < 10 else -0.00006)
        else:
            drift = 0.99975 + (0.0005 if i % 120 < 8 else -0.00005)
        price = max(20.0, price * drift)
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
                price * 1.001,
                price * 0.999,
                price,
                100.0 + (i % 24) * 2.0,
            )
        )
    conn.executemany("insert into market_klines values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _write_derivatives(path: Path) -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(720 * 24):
        event_time = start + timedelta(hours=i)
        rows.append(
            {
                "event_time": event_time.isoformat(),
                "available_time": (event_time + timedelta(minutes=5)).isoformat(),
                "open_interest_usd": 1_000_000.0 + i * 80.0,
                "funding_rate": 0.00005 + ((i % 72) - 36) * 0.000001,
                "long_short_ratio": 1.0 + ((i % 96) - 48) / 400.0,
                "top_trader_long_short_ratio": 1.0,
                "taker_buy_sell_ratio": 1.0,
            }
        )
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
