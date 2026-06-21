from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_us.research.btc_intraday_short_cycle_event_ledger import (
    DEFAULT_PARAMS,
    REPAIRED_ENTRY_FILTER,
    apply_repaired_entry_filter,
    build_event_objects,
    pullback_reclaim_intraday_signal,
)


RUN = Path("artifacts/btc_intraday_event_ledger/20260620T000000Z_pullback_reclaim_intraday_eventledger")
REPAIRED_RUN = Path("artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_repair_eventledger")
DRIFT_GUARDED_RUN = Path(
    "artifacts/btc_intraday_event_ledger/20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
)


def _synthetic_5m_frame(rows: int = 900) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    index = pd.date_range(start=start, periods=rows, freq="5min")
    close = pd.Series(100_000.0, index=index)
    for i in range(rows):
        close.iloc[i] = 100_000.0 + i * 12.0
    open_ = close.shift(1).fillna(close.iloc[0] - 10.0)
    high = pd.concat([open_, close], axis=1).max(axis=1) + 20.0
    low = pd.concat([open_, close], axis=1).min(axis=1) - 20.0
    volume = pd.Series(100.0, index=index)
    volume.iloc[240] = 400.0
    low.iloc[220:240] = low.iloc[220:240] - 1800.0
    close.iloc[240] = high.iloc[216:240].max() + 100.0
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


def test_pullback_reclaim_intraday_signal_no_lookahead() -> None:
    frame = _synthetic_5m_frame()
    context = frame.resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    mutated = frame.copy()
    cutoff = len(mutated) // 2
    mutated.iloc[cutoff:, mutated.columns.get_indexer(["open", "high", "low", "close"])] *= 1.35
    base_signal, base_diagnostics = pullback_reclaim_intraday_signal(frame, context, DEFAULT_PARAMS)
    mutated_signal, _ = pullback_reclaim_intraday_signal(mutated, context, DEFAULT_PARAMS)
    cutoff_ts = frame.index[cutoff - 80]

    pd.testing.assert_series_equal(
        base_signal.loc[base_signal.index <= cutoff_ts],
        mutated_signal.loc[mutated_signal.index <= cutoff_ts],
        check_names=False,
    )
    events = build_event_objects(frame=frame, diagnostics=base_diagnostics, params=DEFAULT_PARAMS)
    assert {"entry_timestamp", "trigger_state", "context_state", "label_horizon"}.issubset(events.columns)
    assert set(events["future_label_used_for_signal"].dropna().unique()).issubset({False})


def test_repaired_entry_filter_uses_past_only_state() -> None:
    frame = _synthetic_5m_frame(rows=1200)
    context = frame.resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    mutated = frame.copy()
    cutoff = len(mutated) // 2
    mutated.iloc[cutoff:, mutated.columns.get_indexer(["open", "high", "low", "close"])] *= 1.45
    base_signal, base_diagnostics = pullback_reclaim_intraday_signal(frame, context, DEFAULT_PARAMS)
    mutated_signal, mutated_diagnostics = pullback_reclaim_intraday_signal(mutated, context, DEFAULT_PARAMS)
    repaired_signal, _ = apply_repaired_entry_filter(
        frame=frame,
        signal=base_signal,
        diagnostics=base_diagnostics,
        params=DEFAULT_PARAMS,
        entry_filter=REPAIRED_ENTRY_FILTER,
    )
    mutated_repaired_signal, _ = apply_repaired_entry_filter(
        frame=mutated,
        signal=mutated_signal,
        diagnostics=mutated_diagnostics,
        params=DEFAULT_PARAMS,
        entry_filter=REPAIRED_ENTRY_FILTER,
    )
    cutoff_ts = frame.index[cutoff - 80]

    pd.testing.assert_series_equal(
        repaired_signal.loc[repaired_signal.index <= cutoff_ts],
        mutated_repaired_signal.loc[mutated_repaired_signal.index <= cutoff_ts],
        check_names=False,
    )


def test_intraday_event_ledger_artifacts_use_ledger_pnl_and_manifest() -> None:
    report = json.loads((RUN / "btc_intraday_short_cycle_event_ledger_report.json").read_text(encoding="utf-8"))
    canonical = json.loads((RUN / "canonical_backtest_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((RUN / "run_manifest.json").read_text(encoding="utf-8"))
    trades = pd.read_csv(RUN / "trade_ledger.csv")
    fill_trades = pd.read_csv(RUN / "fill_trade_ledger_diagnostic.csv")
    events = pd.read_csv(RUN / "event_objects.csv")

    assert canonical["event_ledger_status"]["status"] == "pass"
    assert canonical["event_ledger_status"]["pnl_source"] == "ledger_fills"
    assert canonical["event_ledger_status"]["ledger_equity_consistent"] is True
    assert canonical["diagnostics"]["signal_equity_diagnostic_only"] is True
    assert set(trades["attribution_source"]) == {"ledger_equity_snapshots"}
    assert len(trades) == report["metrics"]["trade_count"]
    assert len(fill_trades) > 0
    assert len(events) == report["event_definition"]["event_count"]
    assert trades["holding_bars"].min() == 12
    assert trades["holding_bars"].max() == 12
    assert manifest["data_version"] == report["manifest"]["data_version"]
    assert manifest["strategy_version"] == report["manifest"]["strategy_version"]
    assert manifest["params_hash"] == report["manifest"]["params_hash"]
    assert manifest["cost_model"] == "base_taker_10bps_round_trip_with_stress_grid_v1"
    assert manifest["slippage_model"] == "base_0bps_stress_5bps_each_fill"
    assert manifest["commit_hash"]


def test_repaired_intraday_event_ledger_artifacts_use_ledger_pnl_and_manifest() -> None:
    report = json.loads(
        (REPAIRED_RUN / "btc_intraday_short_cycle_repaired_event_ledger_report.json").read_text(encoding="utf-8")
    )
    canonical = json.loads((REPAIRED_RUN / "canonical_backtest_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((REPAIRED_RUN / "run_manifest.json").read_text(encoding="utf-8"))
    trades = pd.read_csv(REPAIRED_RUN / "trade_ledger.csv")
    events = pd.read_csv(REPAIRED_RUN / "event_objects.csv")

    assert canonical["event_ledger_status"]["status"] == "pass"
    assert canonical["event_ledger_status"]["pnl_source"] == "ledger_fills"
    assert set(trades["attribution_source"]) == {"ledger_equity_snapshots"}
    assert len(trades) == report["metrics"]["trade_count"]
    assert len(events) == report["event_definition"]["event_count"]
    assert report["tail_dependency"]["status"] == "pass"
    assert report["gate"]["passed"] is False
    assert report["failed_metrics"] == ["regime_pass_rate"]
    assert manifest["strategy_id"] == report["strategy_id"]
    assert manifest["variant_id"] == report["variant_id"]
    assert manifest["data_version"] == report["manifest"]["data_version"]
    assert manifest["strategy_version"] == report["manifest"]["strategy_version"]
    assert manifest["params_hash"] == report["manifest"]["params_hash"]
    assert manifest["cost_model"] == "base_taker_10bps_round_trip_with_stress_grid_v1"
    assert manifest["slippage_model"] == "base_0bps_stress_5bps_each_fill"
    assert manifest["commit_hash"]


def test_drift_guarded_intraday_event_ledger_passes_internal_gate_but_stays_locked() -> None:
    report = json.loads(
        (DRIFT_GUARDED_RUN / "btc_intraday_short_cycle_drift_guarded_event_ledger_report.json").read_text(
            encoding="utf-8"
        )
    )
    canonical = json.loads((DRIFT_GUARDED_RUN / "canonical_backtest_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((DRIFT_GUARDED_RUN / "run_manifest.json").read_text(encoding="utf-8"))
    trades = pd.read_csv(DRIFT_GUARDED_RUN / "trade_ledger.csv")
    events = pd.read_csv(DRIFT_GUARDED_RUN / "event_objects.csv")

    assert canonical["event_ledger_status"]["status"] == "pass"
    assert canonical["event_ledger_status"]["pnl_source"] == "ledger_fills"
    assert set(trades["attribution_source"]) == {"ledger_equity_snapshots"}
    assert len(trades) == report["metrics"]["trade_count"]
    assert len(events) == report["event_definition"]["event_count"]
    assert report["gate"]["passed"] is True
    assert report["failed_metrics"] == []
    assert report["candidate_generation_allowed"] is False
    assert report["paper_or_live_unlock_allowed"] is False
    assert manifest["strategy_id"] == report["strategy_id"]
    assert manifest["variant_id"] == report["variant_id"]
    assert manifest["data_version"] == report["manifest"]["data_version"]
    assert manifest["strategy_version"] == report["manifest"]["strategy_version"]
    assert manifest["params_hash"] == report["manifest"]["params_hash"]
    assert manifest["commit_hash"]


def test_intraday_event_ledger_cost_stress_and_gate_are_complete() -> None:
    cost = json.loads((RUN / "cost_stress_report.json").read_text(encoding="utf-8"))
    walk_forward = json.loads((RUN / "walk_forward_report.json").read_text(encoding="utf-8"))
    regime = json.loads((RUN / "regime_report.json").read_text(encoding="utf-8"))
    promotion = json.loads((RUN / "promotion_decision.json").read_text(encoding="utf-8"))

    assert cost["required_scenarios_present"] is True
    assert {
        "base_10bps",
        "double_taker",
        "conservative_slippage",
        "missed_fill",
        "delayed_entry",
    }.issubset(set(cost["required_scenarios"]))
    assert len(cost["scenarios"]) >= 5
    assert walk_forward["method"] == "rolling_event_ledger_fixed_params_intraday_5m"
    assert walk_forward["fold_count"] == 6
    assert regime["pass_rate"] < 0.75
    assert promotion["decision"] == "return_to_event_definition"
    assert promotion["paper_review"]["paper_review_queue_locked"] is True
    assert promotion["paper_queue"] == "LOCKED"
    assert promotion["live"] == "FROZEN"


def test_intraday_event_ledger_code_has_no_live_side_effects() -> None:
    combined = "\n".join(
        [
            Path("quant_us/research/btc_intraday_short_cycle_event_ledger.py").read_text(encoding="utf-8"),
            Path("scripts/build_btc_intraday_short_cycle_event_ledger_report.py").read_text(encoding="utf-8"),
            Path("scripts/build_btc_intraday_short_cycle_repaired_event_ledger_report.py").read_text(
                encoding="utf-8"
            ),
            Path("scripts/build_btc_intraday_short_cycle_drift_guarded_event_ledger_report.py").read_text(
                encoding="utf-8"
            ),
        ]
    )

    assert "quant_us.live" not in combined
    assert "submit_order" not in combined
    assert "broker.submit" not in combined
    assert "live_enabled: true" not in combined
