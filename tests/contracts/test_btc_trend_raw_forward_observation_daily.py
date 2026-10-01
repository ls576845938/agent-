from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.run_btc_trend_raw_forward_observation_daily import (
    run_btc_trend_raw_forward_observation_daily,
)
from quant_crypto.monitoring.trend_boundary import build_btc_trend_boundary_report


def test_raw_forward_daily_dry_run_refreshes_no_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"

    payload = run_btc_trend_raw_forward_observation_daily(
        repo_root=tmp_path,
        execute_network=False,
        ledger_root=ledger,
        output=tmp_path / "daily.json",
        capture_fn=_fake_capture("dry_run"),
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "DRY_RUN"
    assert payload["steps"]["data_refresh"]["status"] == "dry_run"
    assert payload["steps"]["readiness"]["status"] == "NOT_RUN"
    assert payload["steps"]["roll"]["status"] == "NOT_RUN"
    assert not (ledger / "target_positions.jsonl").exists()


def test_raw_forward_daily_blocks_when_data_refresh_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"

    payload = run_btc_trend_raw_forward_observation_daily(
        repo_root=tmp_path,
        execute_network=True,
        ledger_root=ledger,
        output=tmp_path / "daily.json",
        capture_fn=_fake_capture("rejected", blockers=["okx_public_daily_capture_failed"]),
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "okx_public_daily_capture_failed" in payload["blockers"]
    assert "btc_trend_raw_forward_daily_data_refresh_not_verified" in payload["blockers"]
    assert payload["steps"]["readiness"]["status"] == "NOT_RUN"
    assert not (ledger / "fills.jsonl").exists()


def test_raw_forward_daily_blocks_private_endpoint_data_refresh_flag(tmp_path: Path) -> None:
    payload = run_btc_trend_raw_forward_observation_daily(
        repo_root=tmp_path,
        execute_network=True,
        output=tmp_path / "daily.json",
        capture_fn=_fake_capture("verified", private_endpoint_used=True),
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_trend_raw_forward_daily_data_refresh_private_endpoint_used" in payload["blockers"]
    assert payload["guardrails"]["private_endpoint_used"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_raw_forward_daily_runs_refresh_readiness_roll_and_evaluation(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top, plan, vol, freeze = _write_reports(tmp_path)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"

    payload = run_btc_trend_raw_forward_observation_daily(
        repo_root=tmp_path,
        execute_network=True,
        bundle_dir=bundle,
        ledger_root=ledger,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        capture_report=tmp_path / "capture.json",
        readiness_report=tmp_path / "readiness.json",
        roll_report=tmp_path / "roll.json",
        evaluation_report=tmp_path / "eval.json",
        evaluation_markdown_report=tmp_path / "eval.md",
        output=tmp_path / "daily.json",
        capture_fn=_fake_capture("verified", daily_rows=370, bundle_dir=bundle),
        as_of="2021-01-04T00:00:00Z",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "PASS"
    assert payload["steps"]["data_refresh"]["status"] == "verified"
    assert payload["steps"]["readiness"]["status"] == "PASS"
    assert payload["steps"]["roll"]["status"] == "PASS"
    assert payload["steps"]["evaluation"]["status"] == "raw_forward_observing"
    assert payload["forward_observation"]["new_observation_written"] is True
    assert payload["forward_observation"]["observation_days"] == 1
    assert payload["guardrails"]["simulated_only"] is True
    assert payload["guardrails"]["real_order_submitted"] is False
    chain = payload["forecast_target_order_chain"]
    assert chain["forecast_source_boundary"] == "signal_to_btc_forecast"
    assert chain["order_intent_source_boundary"] == "cost_gate_to_order_intent_no_broker_submit"
    boundary = build_btc_trend_boundary_report(
        source_report=payload,
        boundary_chain=chain,
        generated_at_utc=datetime(2026, 6, 23, tzinfo=timezone.utc),
    )
    assert boundary["status"] == "complete"
    assert _line_count(ledger / "target_positions.jsonl") == 1
    assert _line_count(ledger / "portfolio_snapshots.jsonl") == 1
    assert (tmp_path / "daily.json").exists()


def test_raw_forward_daily_is_idempotent_for_same_cycle(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top, plan, vol, freeze = _write_reports(tmp_path)
    ledger = tmp_path / "data/forward_observation/btc_trend_raw_v1"
    kwargs: dict[str, Any] = dict(
        repo_root=tmp_path,
        execute_network=True,
        bundle_dir=bundle,
        ledger_root=ledger,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        capture_report=tmp_path / "capture.json",
        readiness_report=tmp_path / "readiness.json",
        roll_report=tmp_path / "roll.json",
        evaluation_report=tmp_path / "eval.json",
        evaluation_markdown_report=tmp_path / "eval.md",
        output=tmp_path / "daily.json",
        capture_fn=_fake_capture("verified", daily_rows=370, bundle_dir=bundle),
        as_of="2021-01-04T00:00:00Z",
        initial_capital=10_000.0,
        fee_bps=5.0,
        generated_at="2026-06-23T00:00:00Z",
    )

    first = run_btc_trend_raw_forward_observation_daily(**kwargs)
    second = run_btc_trend_raw_forward_observation_daily(**kwargs)

    assert first["forward_observation"]["new_observation_written"] is True
    assert second["forward_observation"]["already_processed"] is True
    assert second["steps"]["roll"]["cycle_status"] == "SKIPPED_ALREADY_COMPLETED"
    assert _line_count(ledger / "target_positions.jsonl") == 1
    assert _line_count(ledger / "portfolio_snapshots.jsonl") == 1


def _fake_capture(
    status: str,
    *,
    blockers: list[str] | None = None,
    private_endpoint_used: bool = False,
    daily_rows: int = 0,
    bundle_dir: Path | None = None,
):
    def capture(**_: Any) -> dict[str, Any]:
        return {
            "status": status,
            "bundle_id": "btc_okx_spot_btcusdt_daily_5y_v1",
            "bundle_dir": str(bundle_dir or "data/external/btc_spot/okx/bundles/btc_okx_spot_btcusdt_daily_5y_v1"),
            "daily_rows": daily_rows,
            "sample_start": "2020-01-01T00:00:00Z" if daily_rows else "",
            "sample_end": "2021-01-04T00:00:00Z" if daily_rows else "",
            "network_called": status != "dry_run",
            "public_rest_only": True,
            "api_key_used": False,
            "private_endpoint_used": private_endpoint_used,
            "order_endpoint_used": False,
            "blockers": blockers or [],
        }

    return capture


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


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.exists() else 0
