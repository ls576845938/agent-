from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.run_btc_trend_raw_forward_observation_roll import run_btc_trend_raw_forward_observation_roll


def test_raw_forward_roll_blocks_without_ready_gate_and_writes_no_fills(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_plan(plan)
    _write_vol_freeze(vol)
    _write_5m_freeze(freeze)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"

    payload = run_btc_trend_raw_forward_observation_roll(
        repo_root=tmp_path,
        bundle_dir=bundle,
        ledger_root=ledger,
        top_validation_report=tmp_path / "missing_top.json",
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        readiness_report=tmp_path / "readiness.json",
        output=tmp_path / "roll.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert payload["cycle_status"] == "NOT_RUN"
    assert not (ledger / "fills.jsonl").exists()


def test_raw_forward_roll_first_run_writes_target_snapshot_state_and_t_plus_one(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top, plan, vol, freeze = _write_reports(tmp_path)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"

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
        as_of="2021-01-04T00:00:00Z",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "PASS"
    assert payload["cycle_status"] == "COMPLETED"
    assert payload["strategy_id"] == "btc_trend_raw_t01_twelve_month_momentum"
    assert payload["cycle"]["signal_timestamp"] < payload["cycle"]["effective_timestamp"]
    assert payload["target_exposure"] == 1.0
    assert payload["turnover"] == 1.0
    assert payload["simulated_fee"] == 5.0
    assert payload["fill"]["reason"]
    assert payload["fill"]["broker_order_id"] == ""
    assert payload["guardrails"]["private_endpoint_used"] is False
    chain = payload["forecast_target_order_chain"]
    assert chain["forecast_source_boundary"] == "signal_to_btc_forecast"
    assert chain["target_source_boundary"] == "forecast_to_target_position_no_order_intent"
    assert chain["order_intent_source_boundary"] == "cost_gate_to_order_intent_no_broker_submit"
    assert chain["paper_oms_source_boundary"] == "btc_paper_oms_lifecycle"
    assert chain["real_order_submitted"] is False
    for key in [
        "signal_artifact",
        "forecast_artifact",
        "target_artifact",
        "cost_gate_artifact",
        "order_intent_artifact",
        "paper_oms_lifecycle_artifact",
    ]:
        assert (tmp_path / chain[key]).exists()
    assert (ledger / "target_positions.jsonl").exists()
    assert (ledger / "portfolio_snapshots.jsonl").exists()
    assert (ledger / "validation_state.json").exists()


def test_raw_forward_roll_same_timestamp_is_idempotent(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top, plan, vol, freeze = _write_reports(tmp_path)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"
    kwargs = dict(
        repo_root=tmp_path,
        bundle_dir=bundle,
        ledger_root=ledger,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        readiness_report=tmp_path / "readiness.json",
        output=tmp_path / "roll.json",
        as_of="2021-01-04T00:00:00Z",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    first = run_btc_trend_raw_forward_observation_roll(**kwargs)
    second = run_btc_trend_raw_forward_observation_roll(**kwargs)

    assert first["cycle_status"] == "COMPLETED"
    assert second["cycle_status"] == "SKIPPED_ALREADY_COMPLETED"
    assert second["forecast_target_order_chain"]["target_source_boundary"] == "forecast_to_target_position_no_order_intent"
    assert _line_count(ledger / "target_positions.jsonl") == 1
    assert _line_count(ledger / "portfolio_snapshots.jsonl") == 1
    assert _line_count(ledger / "fills.jsonl") == 1


def test_raw_forward_roll_no_exposure_change_writes_no_fill_but_target_and_snapshot(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=372)
    top, plan, vol, freeze = _write_reports(tmp_path)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"
    base = dict(
        repo_root=tmp_path,
        bundle_dir=bundle,
        ledger_root=ledger,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        readiness_report=tmp_path / "readiness.json",
        output=tmp_path / "roll.json",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    run_btc_trend_raw_forward_observation_roll(**base, as_of="2021-01-04T00:00:00Z")
    payload = run_btc_trend_raw_forward_observation_roll(**base, as_of="2021-01-05T00:00:00Z")

    assert payload["status"] == "PASS"
    assert payload["turnover"] == 0.0
    assert payload["fill"] is None
    assert _line_count(ledger / "target_positions.jsonl") == 2
    assert _line_count(ledger / "portfolio_snapshots.jsonl") == 2
    assert _line_count(ledger / "fills.jsonl") == 1


def test_raw_forward_roll_exposure_change_writes_reason_turnover_and_fee(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370, increasing=False)
    top, plan, vol, freeze = _write_reports(tmp_path)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"
    ledger.mkdir(parents=True)
    (ledger / "validation_state.json").write_text(
        json.dumps(
            {
                "schema_version": "btc_trend_raw_forward_observation_state_v1",
                "strategy_id": "btc_trend_raw_t01_twelve_month_momentum",
                "current_equity": 10_000.0,
                "current_exposure": 1.0,
                "days_completed": 0,
                "target_position_count": 0,
                "fill_count": 0,
            }
        ),
        encoding="utf-8",
    )

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
        as_of="2021-01-04T00:00:00Z",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "PASS"
    assert payload["target_exposure"] == 0.0
    assert payload["turnover"] == 1.0
    assert payload["simulated_fee"] == 5.0
    assert payload["fill"]["side"] == "sell"
    assert payload["fill"]["reason"] == "t01_365d_momentum_non_positive_t_plus_1"


def _write_daily_bundle(tmp_path: Path, *, rows: int, increasing: bool = True) -> Path:
    bundle = tmp_path / ("daily_up" if increasing else "daily_down")
    bundle.mkdir()
    path = bundle / "klines_1d.csv"
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close"])
        writer.writeheader()
        for day in range(rows):
            ts = start + timedelta(days=day)
            close = 10_000 + day * 10 if increasing else 20_000 - day * 10
            writer.writerow({"timestamp": ts.isoformat().replace("+00:00", "Z"), "open": close, "high": close + 1, "low": close - 1, "close": close})
    return bundle


def _write_reports(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    top = tmp_path / "top.json"
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_top(top)
    _write_plan(plan)
    _write_vol_freeze(vol)
    _write_5m_freeze(freeze)
    return top, plan, vol, freeze


def _write_top(path: Path) -> None:
    path.write_text(
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


def _write_plan(path: Path) -> None:
    path.write_text(
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


def _write_vol_freeze(path: Path) -> None:
    path.write_text(
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


def _write_5m_freeze(path: Path) -> None:
    path.write_text(
        json.dumps({"status": "frozen_rejected_as_high_frequency", "guardrails": {"parameter_tuning_allowed": False}}),
        encoding="utf-8",
    )


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.exists() else 0
