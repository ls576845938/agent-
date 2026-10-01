from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.build_btc_trend_all_strategy_backtest_report import _candidate_specs
from scripts.build_btc_trend_top_strategy_validation_report import (
    build_btc_trend_top_strategy_validation_report,
)


def test_top_strategy_validation_blocks_short_history(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=400)
    all_report = tmp_path / "all_report.json"
    _write_all_strategy_report(all_report, ["t01_twelve_month_momentum", "t02_long_ma_trend"])

    payload = build_btc_trend_top_strategy_validation_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        all_strategy_report=all_report,
        output=tmp_path / "validation.json",
        walk_forward_output=tmp_path / "wf.csv",
        regime_output=tmp_path / "regime.csv",
        parameter_output=tmp_path / "params.csv",
        markdown_output=tmp_path / "validation.md",
        minimum_daily_rows=600,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "top_strategy_validation_blocked"
    assert payload["research_validation_any_candidate_passed"] is False
    assert "btc_trend_top_strategy_validation_requires_minimum_daily_rows" in payload["blockers"]
    assert payload["candidate_summaries"] == []
    assert (tmp_path / "wf.csv").read_text(encoding="utf-8").startswith("fold_id,family_id")


def test_top_strategy_validation_runs_distinct_top_families_and_writes_outputs(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=900)
    all_report = tmp_path / "all_report.json"
    _write_all_strategy_report(all_report, ["t06_atr_channel_breakout", "t01_twelve_month_momentum"])

    payload = build_btc_trend_top_strategy_validation_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        all_strategy_report=all_report,
        output=tmp_path / "validation.json",
        walk_forward_output=tmp_path / "wf.csv",
        regime_output=tmp_path / "regime.csv",
        parameter_output=tmp_path / "params.csv",
        markdown_output=tmp_path / "validation.md",
        top_family_count=2,
        minimum_daily_rows=600,
        walk_forward_train_days=365,
        walk_forward_test_days=120,
        walk_forward_step_days=120,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "top_strategy_validation_research_only"
    assert payload["decision"] == "manual_review_required_before_any_paper_or_live_claim"
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["this_report_does_not_unlock_live_trading"] is True
    assert len(payload["selected_families"]) == 2
    assert {row["family_id"] for row in payload["selected_families"]} == {
        "t06_atr_channel_breakout",
        "t01_twelve_month_momentum",
    }

    family_summary = payload["walk_forward"]["summary"]["family_summary"]
    assert set(family_summary) == {"t06_atr_channel_breakout", "t01_twelve_month_momentum"}
    assert all(row["fold_count"] >= 3 for row in family_summary.values())
    assert len(payload["candidate_summaries"]) == 2
    for row in payload["candidate_summaries"]:
        assert set(row["checks"]) == {
            "walk_forward",
            "regime_validation",
            "parameter_stability",
            "cost_stress",
            "extreme_year_contribution",
        }

    wf_rows = list(csv.DictReader((tmp_path / "wf.csv").open("r", encoding="utf-8")))
    regime_rows = list(csv.DictReader((tmp_path / "regime.csv").open("r", encoding="utf-8")))
    param_rows = list(csv.DictReader((tmp_path / "params.csv").open("r", encoding="utf-8")))
    assert wf_rows
    assert regime_rows
    assert param_rows
    assert any(row["is_selected"] == "True" for row in param_rows)
    assert (tmp_path / "validation.md").read_text(encoding="utf-8").startswith("# BTC 趋势Top策略验证报告")


def test_top_strategy_validation_blocks_missing_all_strategy_report(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=700)

    payload = build_btc_trend_top_strategy_validation_report(
        repo_root=tmp_path,
        bundle_dir=bundle,
        all_strategy_report=tmp_path / "missing.json",
        output=tmp_path / "validation.json",
        walk_forward_output=tmp_path / "wf.csv",
        regime_output=tmp_path / "regime.csv",
        parameter_output=tmp_path / "params.csv",
        markdown_output=tmp_path / "validation.md",
        minimum_daily_rows=600,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "top_strategy_validation_blocked"
    assert "btc_trend_all_strategy_report_not_complete" in payload["blockers"]
    assert "btc_trend_top_strategy_no_selected_specs" in payload["blockers"]


def _write_all_strategy_report(path: Path, families: list[str]) -> None:
    specs = _candidate_specs()
    summaries = []
    for rank, family_id in enumerate(families, start=1):
        spec = next(item for item in specs if item.family_id == family_id)
        summaries.append(
            {
                "family_id": family_id,
                "status": "tested",
                "candidate_count": 1,
                "selected_candidate": {
                    "candidate_id": spec.candidate_id,
                    "family_id": spec.family_id,
                    "variant_id": spec.variant_id,
                    "score": 100.0 - rank,
                    "params": spec.params,
                    "metrics": {"total_return_pct": 10.0, "max_drawdown_abs_pct": 5.0},
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "status": "research_only_all_backtest_complete",
                "family_summaries": summaries,
                "guardrails": {"live_order_allowed": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_daily_bundle(tmp_path: Path, *, rows: int) -> Path:
    bundle = tmp_path / f"daily_{rows}"
    bundle.mkdir()
    path = bundle / "klines_1d.csv"
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "open_time",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "volume_contracts",
                "volume_base",
                "volume_quote",
                "confirm",
                "source_record_id",
            ],
        )
        writer.writeheader()
        for day in range(rows):
            ts = start + timedelta(days=day)
            regime = (day // 220) % 4
            trend = day * 9
            cycle = ((day % 120) - 60) * 18
            shock = -2500 if regime == 1 else 3000 if regime == 2 else 0
            close = max(1000.0, 20_000 + trend + cycle + shock)
            writer.writerow(
                {
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "open_time": int(ts.timestamp() * 1000),
                    "symbol": "BTCUSDT",
                    "open": close - 30,
                    "high": close + 120,
                    "low": max(1.0, close - 120),
                    "close": close,
                    "volume_contracts": 1,
                    "volume_base": 1,
                    "volume_quote": close,
                    "confirm": 1,
                    "source_record_id": f"fixture:{day}",
                }
            )
    return bundle
