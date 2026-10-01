from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import pandas as pd
import pytest

from quant_us.backtest.us_etf_26_canonical import (
    _cost_components,
    _no_lookahead_check,
    _simulate,
)
from quant_us.data import shared_hf_etf26
from quant_us.research.tqqq_multitimeframe_walk_forward import _fixed_signal
from quant_us.strategies.us_etf_26_complete_return import FrozenEtf26CompleteReturnStrategy


PARAMS = {
    "atr_mult": 3.0,
    "atr_window": 10,
    "bars_per_session": 1,
    "cooldown_bars": 6,
    "ema_fast_days": 50,
    "ema_slow_days": 200,
    "entry_window": 120,
    "exit_window": 60,
    "failure_exit_window": 3,
}


def _strategy() -> FrozenEtf26CompleteReturnStrategy:
    return FrozenEtf26CompleteReturnStrategy(
        candidate_id="us-etf26-complete-return-qqq-1d-v1",
        strategy_version="us_etf_complete_return_fixed_signal_v1",
        symbol="QQQ",
        exposure_multiplier=3.0,
        params=PARAMS,
    )


def _daily(count: int = 330) -> pd.DataFrame:
    sessions = pd.bdate_range("2020-01-02", periods=count)
    close = pd.Series([100.0 + index * 0.2 for index in range(count)])
    return pd.DataFrame(
        {
            "session": sessions.strftime("%Y-%m-%d"),
            "open_time_utc": [
                datetime.combine(value.date(), time(14, 30), tzinfo=timezone.utc)
                for value in sessions
            ],
            "decision_time_utc": [
                datetime.combine(value.date(), time(21, 0), tzinfo=timezone.utc)
                for value in sessions
            ],
            "Open": close - 0.05,
            "High": close + 0.1,
            "Low": close - 0.1,
            "Close": close,
            "Volume": [1_000_000.0] * count,
            "early_close": [False] * count,
        }
    )


def test_frozen_strategy_is_pure_and_matches_goal1_signal_math() -> None:
    module_path = Path("quant_us/strategies/us_etf_26_complete_return.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not ({"subprocess", "sqlite3", "requests", "httpx"} & imported_roots)

    daily = _daily()
    decisions = _strategy().generate(daily)
    market = pd.DataFrame(
        {
            "qqq_close": daily["Close"].to_numpy(),
            "qqq_high": daily["High"].to_numpy(),
            "qqq_low": daily["Low"].to_numpy(),
        },
        index=pd.DatetimeIndex(daily["decision_time_utc"]),
    )
    expected = _fixed_signal(market, PARAMS)["raw_signal"].tolist()
    actual = [decision.forecast.value for decision in decisions]
    assert actual == expected
    assert all(decision.target.target_weight in {0.0, 3.0} for decision in decisions)


def test_event_driven_run_fills_only_after_decision_and_reconciles() -> None:
    daily = _daily()
    strategy = _strategy()
    decisions = strategy.generate(daily)
    costs = {
        "commission_bps": 1.0,
        "spread_bps": 2.0,
        "slippage_bps": 3.0,
        "impact_bps": 4.0,
        "margin_interest_annual": 0.06,
    }
    result = _simulate(
        daily=daily,
        decisions=decisions,
        run_id="test-run",
        strategy_id=strategy.strategy_id,
        data_version="fixture-research-only",
        initial_cash=25_000.0,
        risk={
            "long_only": True,
            "max_target_weight": 3.0,
            "maintenance_margin_rate": 0.25,
            "terminal_on_margin_call": True,
            "max_volume_participation_pct": 1.0,
        },
        execution={
            "order_type": "market",
            "time_in_force": "day",
            "fractional_quantity_precision": 8,
            "cancel_unfilled_at_session_close": True,
        },
        costs=costs,
    )
    assert result.fills
    assert result.reconciliation["passed"] is True
    assert abs(result.reconciliation["cash_delta"]) <= 0.000001
    assert abs(result.reconciliation["quantity_delta"]) <= 0.00000001
    assert abs(result.reconciliation["equity_delta"]) <= 0.000001
    assert all(
        datetime.fromisoformat(fill["decision_time"]) < datetime.fromisoformat(fill["filled_at"])
        for fill in result.fills
    )
    assert all(
        fill["signal_id"] and fill["forecast_id"] and fill["target_position_id"]
        and fill["risk_check_id"] and fill["order_intent_id"] and fill["order_id"]
        for fill in result.fills
    )
    required = {
        "run_id", "strategy_id", "data_version", "decision_time", "signal",
        "forecast", "target_position", "risk_decision", "order_id", "fill_id", "error_code",
    }
    assert all(required <= set(event) for event in result.events)
    assert result.metrics["pnl_from_ledger_only"] is True


def test_partial_fill_cancels_remainder_and_is_replayable() -> None:
    daily = _daily()
    daily.loc[:, "Volume"] = 0.01
    strategy = _strategy()
    decisions = strategy.generate(daily)
    result = _simulate(
        daily=daily,
        decisions=decisions,
        run_id="partial-run",
        strategy_id=strategy.strategy_id,
        data_version="fixture-research-only",
        initial_cash=25_000.0,
        risk={
            "long_only": True,
            "max_target_weight": 3.0,
            "maintenance_margin_rate": 0.25,
            "terminal_on_margin_call": True,
            "max_volume_participation_pct": 1.0,
        },
        execution={
            "order_type": "market",
            "time_in_force": "day",
            "fractional_quantity_precision": 8,
            "cancel_unfilled_at_session_close": True,
        },
        costs={
            "commission_bps": 1.0,
            "spread_bps": 2.0,
            "slippage_bps": 3.0,
            "impact_bps": 4.0,
            "margin_interest_annual": 0.06,
        },
    )
    assert result.lifecycle["partially_filled"] > 0
    assert result.lifecycle["cancelled"] > 0
    assert any(order["status"] == "cancelled_after_partial_fill" for order in result.orders)
    assert result.reconciliation["passed"] is True


def test_zero_volume_rejects_without_fill() -> None:
    daily = _daily()
    daily.loc[:, "Volume"] = 0.0
    strategy = _strategy()
    result = _simulate(
        daily=daily,
        decisions=strategy.generate(daily),
        run_id="reject-run",
        strategy_id=strategy.strategy_id,
        data_version="fixture-research-only",
        initial_cash=25_000.0,
        risk={"long_only": True, "max_target_weight": 3.0, "maintenance_margin_rate": 0.25, "terminal_on_margin_call": True, "max_volume_participation_pct": 1.0},
        execution={"order_type": "market", "time_in_force": "day", "fractional_quantity_precision": 8, "cancel_unfilled_at_session_close": True},
        costs={"commission_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 3.0, "impact_bps": 4.0, "margin_interest_annual": 0.06},
    )
    assert result.lifecycle["rejected"] > 0
    assert not result.fills
    assert all(order["error_code"] == "market_open_or_volume_unavailable" for order in result.orders)
    assert result.reconciliation["passed"] is True


def test_no_lookahead_truncation_and_timestamp_contract() -> None:
    daily = _daily()
    strategy = _strategy()
    decisions = strategy.generate(daily)
    result = _simulate(
        daily=daily,
        decisions=decisions,
        run_id="lookahead-run",
        strategy_id=strategy.strategy_id,
        data_version="fixture-research-only",
        initial_cash=25_000.0,
        risk={"long_only": True, "max_target_weight": 3.0, "maintenance_margin_rate": 0.25, "terminal_on_margin_call": True, "max_volume_participation_pct": 1.0},
        execution={"order_type": "market", "time_in_force": "day", "fractional_quantity_precision": 8, "cancel_unfilled_at_session_close": True},
        costs={"commission_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 3.0, "impact_bps": 4.0, "margin_interest_annual": 0.06},
    )
    check = _no_lookahead_check(strategy, daily, decisions, result.fills)
    assert check["decision_before_fill_passed"] is True
    assert check["same_bar_fill_count"] == 0
    assert check["truncation_invariance_passed"] is True
    assert check["available_time_field_present"] is False


def test_cost_components_preserve_frozen_total() -> None:
    model = {
        "base_total_bps": 10.0,
        "commission_bps": 1.0,
        "spread_bps": 2.0,
        "slippage_bps": 3.0,
        "impact_bps": 4.0,
        "margin_interest_annual": 0.06,
    }
    components = _cost_components(model, 25.0)
    assert sum(components[key] for key in ("commission_bps", "spread_bps", "slippage_bps", "impact_bps")) == 25.0
    assert components["margin_interest_annual"] == 0.06


def test_shared_dataset_adapter_requires_valid_handoff_and_exact_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    event = repo / ".agent/handoffs/ticket/event.json"
    event.parent.mkdir(parents=True)
    event.write_text("{}", encoding="utf-8")
    dataset_root = tmp_path / "shared" / "version"
    qqq = dataset_root / "symbol=QQQ/QQQ_clean_1min.parquet"
    qqq.parent.mkdir(parents=True)
    qqq.write_bytes(b"immutable-fixture")
    qqq_hash = hashlib.sha256(qqq.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "shared_dataset_manifest_v1",
        "dataset_id": "us-equity-hf-etf26-1min",
        "dataset_version": "hf-data-library-etf26-clean-1min-6d6b07e77962",
        "readiness_class": "research_ready",
        "aggregate_sha256": "a" * 64,
        "guardrails": {"consumer_read_only": True},
        "files": [{"path": "symbol=QQQ/QQQ_clean_1min.parquet", "sha256": qqq_hash}],
    }
    monkeypatch.setattr(shared_hf_etf26, "_git_show", lambda *_: json.dumps(manifest).encode())
    responses = iter(
        [
            {"status": "valid", "event_id": "data-ready-hf-etf26-1min-6d6b07e77962"},
            {"status": "resolved", "path": str(dataset_root), "consumer_read_only": True},
        ]
    )
    monkeypatch.setattr(shared_hf_etf26, "_run_json", lambda *_, **__: next(responses))
    resolved = shared_hf_etf26.resolve_hf_etf26_dataset(
        repo_root=repo,
        handoff_event=".agent/handoffs/ticket/event.json",
        expected_event_id="data-ready-hf-etf26-1min-6d6b07e77962",
        manifest_git_spec="commit:manifest.json",
        expected_dataset_id="us-equity-hf-etf26-1min",
        expected_dataset_version="hf-data-library-etf26-clean-1min-6d6b07e77962",
        expected_aggregate_sha256="a" * 64,
        symbol_file="symbol=QQQ/QQQ_clean_1min.parquet",
    )
    assert resolved.qqq_sha256 == qqq_hash
    assert resolved.manifest["readiness_class"] == "research_ready"


def test_schema_rejects_any_promotion_credit() -> None:
    schema = json.loads(Path("schemas/us_etf_26_canonical_backtest_report.schema.json").read_text(encoding="utf-8"))
    report = {
        "schema_version": "us_etf_26_canonical_backtest_report_v1",
        "status": "complete_research_only_blocked",
        "decision": "canonical_research_evidence_complete_promotion_credit_disallowed_confirmation_incomplete",
        "generated_at": "2026-07-13T00:00:00Z",
        "code_commit": "a" * 40,
        "code_tree_hash": "b" * 40,
        "run_id": "us-etf26-canonical-" + "c" * 16,
        "candidate": {"candidate_id": "us-etf26-complete-return-qqq-1d-v1", "strategy_version": "us_etf_complete_return_fixed_signal_v1", "params": {}, "params_hash": "d" * 64, "symbol": "QQQ", "timeframe": "1D", "parameter_tuning_performed": False, "symbol_or_timeframe_reselection_performed": False},
        "data": {"data_version": "hf-data-library-etf26-clean-1min-6d6b07e77962", "readiness_class": "research_ready", "manifest_git_spec": "x", "manifest_sha256": "e" * 64, "aggregate_sha256": "f" * 64, "qqq_sha256": "1" * 64, "consumer_read_only": True, "quality": {}},
        "event_chain": {"sequence": ["MarketData", "Signal", "Forecast", "TargetPosition", "RiskDecision", "OrderIntent", "SimulatedFill", "PositionCashLedger", "Report"], "strategy_has_io_dependency": False, "strategy_has_broker_dependency": False, "strategy_has_database_dependency": False, "audit_required_fields_present": True, "deterministic_replay_hash_match": True},
        "execution": {}, "cost_model": {}, "performance": {},
        "ledger_reconciliation": {"status": "pass", "passed": True, "cash_delta": 0.0, "quantity_delta": 0.0, "equity_delta": 0.0, "orphan_fill_count": 0, "price_series_nav_substitution_used": False},
        "no_lookahead": {}, "walk_forward": {}, "cost_stress": {},
        "independent_confirmation": {"status": "incomplete", "evaluation_performed": False, "evaluation_allowed": False, "parameters_changed": False, "selection_or_ranking_performed": False},
        "corporate_actions": {"status": "blocked_external_data", "adjustment_available_time_replay": False, "pnl_adjustment_total": 0.0},
        "dependencies": {"goal2_status": "blocked_external_data", "goal2_blockers": []},
        "hashes": {"data_aggregate_sha256": "0" * 64, "data_manifest_sha256": "1" * 64, "qqq_file_sha256": "2" * 64, "strategy_config_sha256": "3" * 64, "strategy_source_sha256": "4" * 64, "params_hash": "5" * 64, "cost_model_hash": "6" * 64, "slippage_model_hash": "7" * 64, "run_inputs_hash": "8" * 64, "code_tree_hash": "9" * 40},
        "blockers": ["production_pit_intake_blocked_external_data"],
        "guardrails": {"research_only": True, "promotion_credit_allowed": False, "promotion_unlock_allowed": False, "paper_or_live_unlock_allowed": False, "paper_order_allowed": False, "live_order_allowed": False, "paper_queue_write_allowed": False, "private_endpoint_used": False, "order_endpoint_used": False, "broker_endpoint_used": False, "network_used": False, "secret_read": False, "real_order_submitted": False, "source_data_modified": False},
        "artifacts": {}
    }
    jsonschema.validate(report, schema)
    report["guardrails"]["promotion_credit_allowed"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report, schema)


def test_builder_direct_script_help_imports_quant_us() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/build_us_etf_26_canonical_backtest.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert "--artifact-root" in completed.stdout
