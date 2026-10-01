from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.check_btc_trend_raw_forward_observation_readiness import (
    check_btc_trend_raw_forward_observation_readiness,
)


def test_raw_forward_readiness_blocks_missing_top_validation_report(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_plan(plan)
    _write_vol_freeze(vol)
    _write_5m_freeze(freeze)

    payload = check_btc_trend_raw_forward_observation_readiness(
        repo_root=tmp_path,
        top_validation_report=tmp_path / "missing.json",
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        bundle_dir=bundle,
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_trend_top_strategy_validation_report_missing" in payload["blockers"]
    assert payload["guardrails"]["raw_forward_observation_is_not_strategy_validation"] is True
    assert payload["guardrails"]["live_order_allowed"] is False


def test_raw_forward_readiness_blocks_volatility_branch_not_frozen(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top = tmp_path / "top.json"
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_top(top)
    _write_plan(plan)
    _write_vol_freeze(vol, status="volatility_position_research_only")
    _write_5m_freeze(freeze)

    payload = check_btc_trend_raw_forward_observation_readiness(
        repo_root=tmp_path,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        bundle_dir=bundle,
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_trend_volatility_position_not_frozen_deferred" in payload["blockers"]


def test_raw_forward_readiness_blocks_primary_candidate_mismatch(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top = tmp_path / "top.json"
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_top(top)
    _write_plan(plan, family_id="t06_atr_channel_breakout", candidate_id="t06")
    _write_vol_freeze(vol)
    _write_5m_freeze(freeze)

    payload = check_btc_trend_raw_forward_observation_readiness(
        repo_root=tmp_path,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        bundle_dir=bundle,
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_trend_raw_forward_primary_family_mismatch" in payload["blockers"]
    assert "btc_trend_raw_forward_primary_candidate_mismatch" in payload["blockers"]


def test_raw_forward_readiness_blocks_private_order_live_flags(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top = tmp_path / "top.json"
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_top(top)
    _write_plan(plan, private_endpoint_used=True, order_endpoint_used=True, live_order_allowed=True)
    _write_vol_freeze(vol)
    _write_5m_freeze(freeze)

    payload = check_btc_trend_raw_forward_observation_readiness(
        repo_root=tmp_path,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        bundle_dir=bundle,
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert any("private_endpoint_used" in item for item in payload["blockers"])
    assert any("order_endpoint_used" in item for item in payload["blockers"])
    assert any("live_order_allowed" in item for item in payload["blockers"])


def test_raw_forward_readiness_blocks_forbidden_ledger_roots(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top = tmp_path / "top.json"
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_top(top)
    _write_plan(plan)
    _write_vol_freeze(vol)
    _write_5m_freeze(freeze)

    payload = check_btc_trend_raw_forward_observation_readiness(
        repo_root=tmp_path,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        bundle_dir=bundle,
        ledger_root=Path("data/paper_ledger/btc_trend_v0"),
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_trend_raw_forward_ledger_root_forbidden" in payload["blockers"]


def test_raw_forward_readiness_passes_locked_raw_plan(tmp_path: Path) -> None:
    bundle = _write_daily_bundle(tmp_path, rows=370)
    top = tmp_path / "top.json"
    plan = tmp_path / "plan.json"
    vol = tmp_path / "vol.json"
    freeze = tmp_path / "freeze.json"
    _write_top(top)
    _write_plan(plan)
    _write_vol_freeze(vol)
    _write_5m_freeze(freeze)

    payload = check_btc_trend_raw_forward_observation_readiness(
        repo_root=tmp_path,
        top_validation_report=top,
        raw_plan_report=plan,
        volatility_freeze_report=vol,
        five_minute_freeze_report=freeze,
        bundle_dir=bundle,
        ledger_root=Path("data/forward_observation/btc_trend_raw_v1"),
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "PASS"
    assert payload["strategy_id"] == "btc_trend_raw_t01_twelve_month_momentum"
    assert payload["checks"]["daily_history_sufficient"] is True
    assert payload["checks"]["ledger_root_isolated"] is True


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


def _write_plan(
    path: Path,
    *,
    family_id: str = "t01_twelve_month_momentum",
    candidate_id: str = "t01_momentum_binary_8e09e94c36",
    private_endpoint_used: bool = False,
    order_endpoint_used: bool = False,
    live_order_allowed: bool = False,
) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "raw_trend_forward_observation_plan_ready",
                "primary_candidate": {"family_id": family_id, "candidate_id": candidate_id},
                "forward_observation": {
                    "volatility_position_branch_allowed": False,
                    "paper_runner_start_allowed_by_this_report": False,
                },
                "guardrails": {
                    "volatility_position_branch_frozen": True,
                    "private_endpoint_used": private_endpoint_used,
                    "order_endpoint_used": order_endpoint_used,
                    "live_order_allowed": live_order_allowed,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_vol_freeze(path: Path, *, status: str = "frozen_deferred_not_primary") -> None:
    path.write_text(
        json.dumps(
            {
                "status": status,
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
