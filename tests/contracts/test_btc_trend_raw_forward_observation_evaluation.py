from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.build_btc_trend_raw_forward_observation_evaluation import (
    build_btc_trend_raw_forward_observation_evaluation,
)
from scripts.run_btc_trend_raw_forward_observation_roll import run_btc_trend_raw_forward_observation_roll


def test_raw_forward_evaluation_under_30_days_observing_not_live_ready(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    ledger = _build_forward_ledger(tmp_path, bundle=bundle, days=1)

    payload = build_btc_trend_raw_forward_observation_evaluation(
        repo_root=tmp_path,
        ledger_root=ledger,
        bundle_dir=bundle,
        output=tmp_path / "eval.json",
        markdown_output=tmp_path / "eval.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "raw_forward_observing"
    assert payload["metrics"]["observation_days"] == 1
    assert payload["ledger_consistency"]["passed"] is True
    assert payload["signal_consistency"]["passed"] is True
    assert payload["guardrails"]["live_ready"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert "不输出 live-ready" in (tmp_path / "eval.md").read_text(encoding="utf-8")


def test_raw_forward_evaluation_30_days_complete_for_manual_review_not_live_ready(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=430)
    ledger = _build_forward_ledger(tmp_path, bundle=bundle, days=30)

    payload = build_btc_trend_raw_forward_observation_evaluation(
        repo_root=tmp_path,
        ledger_root=ledger,
        bundle_dir=bundle,
        output=tmp_path / "eval.json",
        markdown_output=tmp_path / "eval.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "raw_forward_complete_for_manual_review"
    assert payload["metrics"]["observation_days"] == 30
    assert payload["metrics"]["milestone_progress"]["30"] is True
    assert payload["guardrails"]["live_ready"] is False
    assert payload["guardrails"]["evaluation_does_not_output_live_ready"] is True


def test_raw_forward_evaluation_blocks_failed_ledger_recompute(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    ledger = _build_forward_ledger(tmp_path, bundle=bundle, days=1)
    snapshots_path = ledger / "portfolio_snapshots.jsonl"
    snapshot = json.loads(snapshots_path.read_text(encoding="utf-8").splitlines()[0])
    snapshot["equity"] = snapshot["equity"] + 100.0
    snapshots_path.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")

    payload = build_btc_trend_raw_forward_observation_evaluation(
        repo_root=tmp_path,
        ledger_root=ledger,
        bundle_dir=bundle,
        output=tmp_path / "eval.json",
        markdown_output=tmp_path / "eval.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "raw_forward_blocked"
    assert "btc_trend_raw_forward_ledger_reconciliation_failed" in payload["blockers"]


def test_raw_forward_evaluation_blocks_signal_mismatch_or_lookahead(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    ledger = _build_forward_ledger(tmp_path, bundle=bundle, days=1)
    targets_path = ledger / "target_positions.jsonl"
    target = json.loads(targets_path.read_text(encoding="utf-8").splitlines()[0])
    target["signal_timestamp"] = target["effective_timestamp"]
    targets_path.write_text(json.dumps(target, sort_keys=True) + "\n", encoding="utf-8")

    payload = build_btc_trend_raw_forward_observation_evaluation(
        repo_root=tmp_path,
        ledger_root=ledger,
        bundle_dir=bundle,
        output=tmp_path / "eval.json",
        markdown_output=tmp_path / "eval.md",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "raw_forward_blocked"
    assert "btc_trend_raw_forward_signal_consistency_failed" in payload["blockers"]


def _build_forward_ledger(tmp_path: Path, *, bundle: Path, days: int) -> Path:
    top, plan, vol, freeze = _write_reports(tmp_path)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"
    start = datetime(2021, 1, 4, tzinfo=timezone.utc)
    for offset in range(days):
        as_of = (start + timedelta(days=offset)).isoformat().replace("+00:00", "Z")
        payload = run_btc_trend_raw_forward_observation_roll(
            repo_root=tmp_path,
            bundle_dir=bundle,
            ledger_root=ledger,
            top_validation_report=top,
            raw_plan_report=plan,
            volatility_freeze_report=vol,
            five_minute_freeze_report=freeze,
            readiness_report=tmp_path / "readiness.json",
            output=tmp_path / "roll.json",
            as_of=as_of,
            initial_capital=10_000.0,
            fee_bps=5.0,
            generated_at="2026-06-23T00:00:00Z",
        )
        assert payload["status"] == "PASS"
    return ledger


def _write_daily_bundle(tmp_path: Path, *, rows: int) -> Path:
    bundle = tmp_path / "daily"
    bundle.mkdir()
    path = bundle / "klines_1d.csv"
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close"])
        writer.writeheader()
        for day in range(rows):
            ts = start + timedelta(days=day)
            close = 10_000 + day * 10
            writer.writerow({"timestamp": ts.isoformat().replace("+00:00", "Z"), "open": close, "high": close + 1, "low": close - 1, "close": close})
    return bundle


def _write_reports(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    top = tmp_path / "top.json"
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    top.write_text(
        json.dumps(
            {
                "status": "top_strategy_validation_research_only",
                "candidate_summaries": [
                    {
                        "family_id": "t01_twelve_month_momentum",
                        "candidate_id": "t01_momentum_binary_8e09e94c36",
                        "validation_status": "research_validation_passed",
                    }
                ],
                "guardrails": {"private_endpoint_used": False, "order_endpoint_used": False, "live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    plan.write_text(
        json.dumps(
            {
                "status": "raw_trend_forward_observation_plan_ready",
                "primary_candidate": {
                    "family_id": "t01_twelve_month_momentum",
                    "candidate_id": "t01_momentum_binary_8e09e94c36",
                },
                "forward_observation": {
                    "volatility_position_branch_allowed": False,
                    "paper_runner_start_allowed_by_this_report": False,
                },
                "guardrails": {
                    "volatility_position_branch_frozen": True,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    vol.write_text(
        json.dumps(
            {
                "status": "frozen_deferred_not_primary",
                "guardrails": {
                    "parameter_tuning_allowed": False,
                    "paper_observation_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    freeze.write_text(
        json.dumps({"status": "frozen_rejected_as_high_frequency", "guardrails": {"parameter_tuning_allowed": False}}),
        encoding="utf-8",
    )
    return top, plan, vol, freeze
