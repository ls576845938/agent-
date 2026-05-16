from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from backend.app.services import backtests as backtest_service_module
from backend.app.services.backtests import ResearchBacktestService
from quant_us.backtest.crypto_event import (
    CryptoEventBacktestArtifacts,
    CRYPTO_VALIDATION_INTERVALS,
    default_crypto_cost_stress_scenarios,
    qualify_crypto_candidates,
    run_crypto_event_backtest,
    summarize_crypto_interval_validation,
)
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar


UTC = timezone.utc


def _btc_frame() -> pd.DataFrame:
    start = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    rows = []
    prices = [
        (100.0, 100.0),
        (100.0, 101.0),
        (102.0, 103.0),
        (103.0, 103.0),
        (104.0, 104.0),
    ]
    for offset, (open_, close) in enumerate(prices):
        rows.append(
            {
                "timestamp": start + timedelta(hours=offset),
                "symbol": "BTCUSD",
                "open": open_,
                "high": max(open_, close) + 1.0,
                "low": min(open_, close) - 1.0,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return pd.DataFrame(rows).set_index("timestamp")


def _loader(**kwargs) -> pd.DataFrame:
    assert kwargs["source"] == "sqlite"
    assert kwargs["symbol"] == "BTCUSD"
    assert kwargs["interval"] == "1h"
    assert kwargs["db_path"] == "/tmp/btc.sqlite"
    return _btc_frame()


def _entry_exit_signal(frame: pd.DataFrame, strategy_id: str, params: dict) -> pd.Series:
    assert strategy_id == "btc_replay"
    assert params == {"threshold": 1.0}
    return pd.Series([1.0, 1.0, 1.0, 0.0, 0.0], index=frame.index)


def test_crypto_event_backtest_uses_fills_ledger_manifest_and_consistent_equity(tmp_path) -> None:
    start = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    result = run_crypto_event_backtest(
        source="sqlite",
        sqlite_path="/tmp/btc.sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=start,
        end=start + timedelta(hours=5),
        strategy_id="btc_replay",
        params={"threshold": 1.0},
        capital=100_000.0,
        cost=0.0,
        slippage=0.0,
        data_version="btc-sqlite-1h-test",
        manifest_root=tmp_path,
        market_loader=_loader,
        signal_provider=_entry_exit_signal,
        run_id="crypto_event_btc_fixture",
    )

    assert result.mode == "crypto_event"
    assert result.summary["trade_count"] == len(result.unified.fills) == 2
    assert len(result.unified.orders) == 2
    assert result.unified.equity_consistent is True
    assert result.diagnostics["pnl_source"] == "ledger_fills"
    assert result.diagnostics["ledger_equity_consistent"] is True
    assert result.diagnostics["manifest_path"] == str(tmp_path / "run_crypto_event_btc_fixture.json")
    assert Path(result.diagnostics["manifest_path"]).exists()
    manifest = json.loads(Path(result.diagnostics["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["strategy_params"][0]["params"]["params"] == {"threshold": 1.0}
    assert manifest["cost_model"]["commission_rate"] == 0.0
    assert manifest["slippage_model"]["bps"] == 0.0
    assert manifest["commit_hash"]
    assert result.unified.evidence["pnl"]["source"] == "ledger_fills"
    assert result.unified.evidence["fills"]["count"] == 2
    assert result.unified.evidence["orders"]["all_orders_have_risk_check_id"] is True
    assert result.chart["markers"][0]["time"] == int((start + timedelta(hours=1)).timestamp())
    assert result.chart["markers"][1]["time"] == int((start + timedelta(hours=4)).timestamp())
    assert result.chart["equity"][-1]["value"] == result.diagnostics["ledger_final_equity"]
    assert result.summary["total_return_pct"] == 3.6
    assert result.diagnostics["sample"]["bar_count"] == 5
    assert result.diagnostics["sample"]["long_sample_pass"] is False
    assert result.diagnostics["regime_split"]["regimes"]


def test_crypto_event_backtest_does_not_use_same_bar_signal_price(tmp_path) -> None:
    start = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    bars = [
        Bar(
            timestamp_utc=start,
            symbol="BTCUSD",
            open=75.0,
            high=110.0,
            low=70.0,
            close=100.0,
            volume=10_000.0,
        ),
        Bar(
            timestamp_utc=start + timedelta(hours=1),
            symbol="BTCUSD",
            open=90.0,
            high=95.0,
            low=85.0,
            close=92.0,
            volume=10_000.0,
        ),
    ]

    def signal(frame: pd.DataFrame, strategy_id: str, params: dict) -> pd.Series:
        return pd.Series([1.0, 1.0], index=frame.index)

    result = run_crypto_event_backtest(
        source="sqlite",
        sqlite_path="/tmp/btc.sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=start,
        end=start + timedelta(hours=2),
        strategy_id="btc_replay",
        capital=100_000.0,
        cost=0.0,
        slippage=0.0,
        target_weight=0.80,
        min_cash_buffer_pct=0.10,
        manifest_root=tmp_path,
        market_events=[MarketEvent.from_bar(bar) for bar in bars],
        signal_provider=signal,
        run_id="crypto_event_no_lookahead",
    )

    assert len(result.unified.fills) == 1
    assert result.unified.fills[0].filled_at == bars[1].timestamp_utc
    assert result.unified.fills[0].price == 90.0
    assert result.unified.orders[0].metadata["signal_timestamp_utc"] == bars[0].timestamp_utc.isoformat()
    assert result.unified.event_driven.metadata["execution_semantics"] == "signal_at_bar_close_order_next_bar"


def test_crypto_event_backtest_does_not_fill_terminal_bar_signal_same_bar(tmp_path) -> None:
    start = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    bars = [
        Bar(
            timestamp_utc=start,
            symbol="BTCUSD",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=10_000.0,
        ),
        Bar(
            timestamp_utc=start + timedelta(hours=1),
            symbol="BTCUSD",
            open=50.0,
            high=150.0,
            low=45.0,
            close=140.0,
            volume=10_000.0,
        ),
    ]

    def terminal_signal(frame: pd.DataFrame, strategy_id: str, params: dict) -> pd.Series:
        return pd.Series([0.0, 1.0], index=frame.index)

    result = run_crypto_event_backtest(
        source="sqlite",
        sqlite_path="/tmp/btc.sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=start,
        end=start + timedelta(hours=2),
        strategy_id="btc_replay",
        capital=100_000.0,
        cost=0.0,
        slippage=0.0,
        target_weight=0.85,
        min_cash_buffer_pct=0.10,
        manifest_root=tmp_path,
        market_events=[MarketEvent.from_bar(bar) for bar in bars],
        signal_provider=terminal_signal,
        run_id="crypto_event_terminal_signal_no_same_bar",
    )

    assert result.unified.fills == []
    assert result.unified.orders == []
    assert result.unified.event_driven.metadata["execution_semantics"] == "signal_at_bar_close_order_next_bar"


def test_crypto_event_replay_does_not_rebalance_repeated_same_direction_signal(tmp_path) -> None:
    start = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    bars = [
        Bar(
            timestamp_utc=start + timedelta(hours=offset),
            symbol="BTCUSD",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=10_000.0,
        )
        for offset in range(6)
    ]

    def persistent_long(frame: pd.DataFrame, strategy_id: str, params: dict) -> pd.Series:
        return pd.Series([1.0] * len(frame), index=frame.index)

    result = run_crypto_event_backtest(
        source="sqlite",
        sqlite_path="/tmp/btc.sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=start,
        end=start + timedelta(hours=6),
        strategy_id="btc_replay",
        capital=100_000.0,
        cost=0.0,
        slippage=0.0,
        target_weight=0.80,
        min_cash_buffer_pct=0.10,
        manifest_root=tmp_path,
        market_events=[MarketEvent.from_bar(bar) for bar in bars],
        signal_provider=persistent_long,
        run_id="crypto_event_persistent_long_no_rebalance",
    )

    assert len(result.unified.fills) == 1
    assert len(result.unified.orders) == 1
    assert result.diagnostics["execution_config"]["rebalance_buffer_pct"] == 0.05


def test_btc_strategy_registry_does_not_import_live_execution_or_submit_orders() -> None:
    strategy_source = Path("backend/app/domain/strategy_registry.py")
    tree = ast.parse(strategy_source.read_text(encoding="utf-8"), filename=str(strategy_source))
    forbidden_imports = ("quant_us.execution", "quant_us.live")
    forbidden_order_calls = {
        "handle_intent",
        "place_order",
        "submit_order",
        "submit_orders",
        "cancel_order",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
            assert not any(name.startswith(forbidden_imports) for name in imported)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith(forbidden_imports)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_order_calls


def test_btc_cost_stress_reuses_crypto_event_execution_config(monkeypatch) -> None:
    start = datetime(2026, 5, 9, 0, 0, tzinfo=UTC)
    frame = _btc_frame()

    def load_market_frame(**kwargs) -> pd.DataFrame:
        assert kwargs["symbol"] == "BTCUSD"
        return frame.copy()

    def prepare_strategy_pack(loaded_frame: pd.DataFrame, strategy_ids: list[str], params_map=None):
        assert strategy_ids == ["btc_replay"]
        return {
            "btc_replay": _entry_exit_signal(loaded_frame, "btc_replay", {"threshold": 1.0})
        }, {}

    monkeypatch.setattr(backtest_service_module, "load_market_frame", load_market_frame)
    monkeypatch.setattr(backtest_service_module, "_prepare_strategy_pack", prepare_strategy_pack)

    baseline = run_crypto_event_backtest(
        source="sqlite",
        sqlite_path="/tmp/btc.sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=start,
        end=start + timedelta(hours=5),
        strategy_id="btc_replay",
        params={"threshold": 1.0},
        capital=100_000.0,
        commission_rate=0.0,
        slippage_bps=0.0,
        market_loader=_loader,
        signal_provider=_entry_exit_signal,
        target_weight=0.90,
        min_cash_buffer_pct=0.10,
        min_trade_notional=25.0,
        long_only=True,
        run_id="crypto_event_btc_cost_baseline",
    )

    stress = ResearchBacktestService().run_event_driven_cost_stress(
        {
            "asset_class": "crypto",
            "source": "sqlite",
            "symbol": "BTCUSD",
            "interval": "1h",
            "start": start,
            "end": start + timedelta(hours=5),
            "strategy_id": "btc_replay",
            "strategy_params": {"threshold": 1.0},
            "capital": 100_000.0,
            "commission_rate": 0.0,
            "slippage": 0.0,
            "target_weight": 0.90,
            "min_cash_buffer_pct": 0.10,
            "min_trade_notional": 25.0,
            "long_only": False,
            "data_db_path": "/tmp/btc.sqlite",
            "max_scenarios": 1,
        }
    )

    assert stress["asset_class"] == "crypto"
    assert stress["data_version"] == ""
    assert stress["survival_rate_pct"] == 100.0
    assert stress["ledger_consistency_pct"] == 100.0
    assert stress["scenario_names"] == ["base"]
    assert stress["scenario_manifests_complete"] is True
    assert stress["baseline"]["summary"] == baseline.summary
    assert stress["baseline"]["execution"]["pnl_source"] == "ledger_fills"
    assert stress["baseline"]["manifest_path"]
    assert stress["baseline"]["run_id"].endswith("_base")
    assert stress["baseline"]["execution_config"] == {
        "target_weight": 0.9,
        "risk_limit": 1.0,
        "cash_reserve_weight": 0.1,
        "min_cash_buffer_pct": 0.1,
        "min_trade_notional": 25.0,
        "rebalance_buffer_pct": 0.05,
        "long_only": False,
    }


def test_research_backtest_service_forwards_crypto_event_audit_fields(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    expected = CryptoEventBacktestArtifacts(
        mode="crypto_event",
        summary={"trade_count": 0},
        chart={},
        strategy_details=[],
        latest_weights=[],
        diagnostics={"manifest_path": str(tmp_path / "run_test.json")},
        unified=object(),  # type: ignore[arg-type]
    )

    def fake_run_crypto_event_backtest(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr("quant_us.backtest.crypto_event.run_crypto_event_backtest", fake_run_crypto_event_backtest)

    result = ResearchBacktestService().run_crypto_event(
        {
            "source": "sqlite",
            "symbol": "BTCUSD",
            "interval": "1h",
            "start": datetime(2026, 5, 9, 0, 0, tzinfo=UTC),
            "end": datetime(2026, 5, 9, 5, 0, tzinfo=UTC),
            "strategy_id": "btc_replay",
            "strategy_params": {"threshold": 1.0},
            "data_version": "qs-sqlite-BTCUSD-1h-test",
            "strategy_version": "btc_replay:registry_signal_replay_v1",
            "manifest_root": str(tmp_path),
            "run_id": "btc_closure_test_event",
        }
    )

    assert captured["data_version"] == "qs-sqlite-BTCUSD-1h-test"
    assert captured["strategy_version"] == "btc_replay:registry_signal_replay_v1"
    assert captured["manifest_root"] == str(tmp_path)
    assert captured["run_id"] == "btc_closure_test_event"
    assert result.diagnostics["manifest_path"] == str(tmp_path / "run_test.json")


def test_crypto_walk_forward_forwards_rebalance_buffer_to_execution_config(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(hours=offset),
                "symbol": "BTCUSDT",
                "open": 100.0 + offset * 0.1,
                "high": 101.0 + offset * 0.1,
                "low": 99.0 + offset * 0.1,
                "close": 100.5 + offset * 0.1,
                "volume": 1_000_000.0,
            }
            for offset in range(80)
        ]
    ).set_index("timestamp")

    def fake_run_walk_forward_unified(*, bars, strategy_factory, wf_config, unified_config):
        captured["min_weight_change"] = unified_config.rebalance.min_weight_change
        captured["min_trade_notional"] = unified_config.rebalance.min_trade_notional
        captured["cash_reserve"] = round(float(unified_config.risk.min_cash_buffer_pct), 8)
        window = SimpleNamespace(
            train_start=bars[0].timestamp_utc,
            train_end=bars[50].timestamp_utc,
            test_start=bars[51].timestamp_utc,
            test_end=bars[-1].timestamp_utc,
        )
        unified = SimpleNamespace(
            summary={
                "total_return_pct": 1.0,
                "sharpe_ratio": 0.5,
                "max_drawdown_pct": -2.0,
            },
            equity_consistent=True,
            manifest_path=str(tmp_path / "fold.json"),
        )
        return [SimpleNamespace(window=window, unified=unified)]

    monkeypatch.setattr(backtest_service_module, "load_market_frame", lambda **kwargs: frame)
    monkeypatch.setattr(backtest_service_module, "_build_regime_slices", lambda **kwargs: [])

    import quant_us.backtest.walk_forward as walk_forward_module

    monkeypatch.setattr(walk_forward_module, "run_walk_forward_unified", fake_run_walk_forward_unified)

    result = ResearchBacktestService().run_walk_forward(
        {
            "source": "sqlite",
            "asset_class": "crypto",
            "symbol": "BTCUSDT",
            "symbols": ["BTCUSDT"],
            "interval": "1h",
            "start": start,
            "end": start + timedelta(hours=80),
            "strategy_id": "trend_macd",
            "strategy_params": {},
            "capital": 100_000.0,
            "commission_rate": 0.0004,
            "slippage": 4.0,
            "leverage": 1.0,
            "target_weight": 0.85,
            "min_cash_buffer_pct": 0.15,
            "min_trade_notional": 50.0,
            "rebalance_buffer_pct": 0.07,
            "windows": 2,
            "data_root": str(tmp_path),
        }
    )

    assert result["status"] == "completed"
    assert captured == {
        "min_weight_change": 0.07,
        "min_trade_notional": 50.0,
        "cash_reserve": 0.15,
    }


def test_crypto_interval_validation_requires_all_btc_closure_timeframes_and_long_sample() -> None:
    min_bars = {"5m": 10, "15m": 10, "1h": 10, "4h": 10, "1d": 10}
    quality_results = [
        {
            "interval": interval,
            "row_count": 12,
            "coverage_pct": 100.0,
            "quality_score": 100.0,
            "is_usable": True,
            "data_version": f"dv-{interval}",
            "fingerprint": f"fp-{interval}",
        }
        for interval in CRYPTO_VALIDATION_INTERVALS
    ]
    resample_results = [
        {
            "target_interval": interval,
            "rows_written": 12,
            "coverage_pct": 100.0,
            "quality_score": 100.0,
            "data_version": f"resampled-{interval}",
            "fingerprint": f"resample-fp-{interval}",
        }
        for interval in CRYPTO_VALIDATION_INTERVALS
    ]

    passed = summarize_crypto_interval_validation(
        quality_results=quality_results,
        resample_results=resample_results,
        min_bars_by_interval=min_bars,
    )

    assert passed["status"] == "pass"
    assert passed["target_intervals"] == list(CRYPTO_VALIDATION_INTERVALS)

    failed = summarize_crypto_interval_validation(
        quality_results=[row for row in quality_results if row["interval"] != "4h"],
        resample_results=resample_results,
        min_bars_by_interval={**min_bars, "1d": 20},
    )

    assert failed["status"] == "fail"
    assert any("4h: missing quality result" in blocker for blocker in failed["blockers"])
    assert any("1d: row_count 12 < long_sample_min_bars 20" in blocker for blocker in failed["blockers"])


def test_default_crypto_cost_stress_scenarios_include_tail_shocks() -> None:
    scenarios = default_crypto_cost_stress_scenarios()

    assert len(scenarios) == 8
    assert scenarios[0]["name"] == "base"
    assert scenarios[-1] == {
        "name": "tail_10x",
        "label": "Tail cost shock 10x",
        "commission_multiplier": 10.0,
        "slippage_multiplier": 10.0,
    }
    assert default_crypto_cost_stress_scenarios(max_scenarios=3) == scenarios[:3]


def test_qualify_crypto_candidates_selects_only_durable_gate_passes() -> None:
    candidates = [
        {
            "strategy_id": "donchian_breakout",
            "parameters": {"window": 20},
            "score": 3.0,
            "validation": {
                "total_return_pct": 12.0,
                "sharpe_ratio": 1.4,
                "profit_factor": 1.8,
                "max_drawdown_pct": -6.0,
                "trade_count": 22,
            },
        },
        {
            "strategy_id": "trend_macd",
            "parameters": {},
            "score": 2.0,
            "validation": {
                "total_return_pct": 8.0,
                "sharpe_ratio": 1.2,
                "profit_factor": 1.4,
                "max_drawdown_pct": -8.0,
                "trade_count": 18,
            },
        },
        {
            "strategy_id": "reversion_rsi",
            "parameters": {},
            "score": 1.8,
            "validation": {
                "total_return_pct": 7.0,
                "sharpe_ratio": 1.3,
                "profit_factor": 1.5,
                "max_drawdown_pct": -5.0,
                "trade_count": 16,
            },
        },
    ]
    event_ok = {
        "diagnostics": {
            "engine": "event_driven",
            "pnl_source": "ledger_fills",
            "ledger_equity_consistent": True,
        }
    }
    cost_ok = {
        "engine": "event_driven",
        "survival_rate_pct": 100.0,
        "ledger_consistency_pct": 100.0,
    }
    walk_ok = {
        "stability": {
            "fold_pass_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "regime_pass_rate_pct": 100.0,
        }
    }

    result = qualify_crypto_candidates(
        candidates,
        cost_stress_by_candidate={
            "donchian_breakout|window=20": cost_ok,
            "trend_macd": {**cost_ok, "survival_rate_pct": 75.0},
            "reversion_rsi": cost_ok,
        },
        walk_forward_by_candidate={
            "donchian_breakout|window=20": walk_ok,
            "trend_macd": walk_ok,
            "reversion_rsi": walk_ok,
        },
        event_backtest_by_candidate={
            "donchian_breakout|window=20": event_ok,
            "trend_macd": event_ok,
            "reversion_rsi": {"diagnostics": {"engine": "vectorized", "pnl_source": "signal_returns"}},
        },
        max_selected=2,
    )

    assert result["qualified_count"] == 1
    assert result["selected_count"] == 1
    assert result["selected_candidates"][0]["strategy_id"] == "donchian_breakout"
    trend = next(row for row in result["candidates"] if row["strategy_id"] == "trend_macd")
    reversion = next(row for row in result["candidates"] if row["strategy_id"] == "reversion_rsi")
    assert trend["selected"] is False
    assert any("cost survival_rate" in blocker for blocker in trend["qualification_blockers"])
    assert reversion["qualified"] is False
    assert any("event backtest is not event_driven" in blocker for blocker in reversion["qualification_blockers"])


def test_qualify_crypto_candidates_selects_highest_ranked_qualified_candidate_stably() -> None:
    candidates = [
        {
            "strategy_id": "lower_ranked",
            "score": 1.0,
            "rank": 2,
            "validation": {
                "total_return_pct": 5.0,
                "sharpe_ratio": 1.2,
                "profit_factor": 1.4,
                "max_drawdown_pct": -6.0,
                "trade_count": 15,
            },
        },
        {
            "strategy_id": "higher_ranked",
            "score": 3.0,
            "rank": 1,
            "validation": {
                "total_return_pct": 7.0,
                "sharpe_ratio": 1.5,
                "profit_factor": 1.7,
                "max_drawdown_pct": -5.0,
                "trade_count": 18,
            },
        },
    ]
    event_ok = {"diagnostics": {"engine": "event_driven", "pnl_source": "ledger_fills", "ledger_equity_consistent": True}}
    cost_ok = {"engine": "event_driven", "survival_rate_pct": 100.0, "ledger_consistency_pct": 100.0}
    walk_ok = {
        "stability": {
            "fold_pass_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "regime_pass_rate_pct": 100.0,
        }
    }

    result = qualify_crypto_candidates(
        candidates,
        cost_stress_by_candidate={"lower_ranked": cost_ok, "higher_ranked": cost_ok},
        walk_forward_by_candidate={"lower_ranked": walk_ok, "higher_ranked": walk_ok},
        event_backtest_by_candidate={"lower_ranked": event_ok, "higher_ranked": event_ok},
        max_selected=1,
    )

    assert [row["strategy_id"] for row in result["candidates"]] == ["higher_ranked", "lower_ranked"]
    assert result["selected_candidates"][0]["strategy_id"] == "higher_ranked"


def test_qualify_crypto_candidates_requires_event_ledger_summary_edge() -> None:
    candidate = {
        "strategy_id": "btc_orderflow_pressure",
        "score": 3.0,
        "validation": {
            "total_return_pct": 9.0,
            "sharpe_ratio": 1.4,
            "profit_factor": 1.5,
            "max_drawdown_pct": -5.0,
            "trade_count": 20,
        },
    }
    event_weak = {
        "summary": {
            "total_return_pct": 8.0,
            "sharpe_ratio": 1.1,
            "profit_factor": 1.04,
            "max_drawdown_pct": -4.0,
            "trade_count": 18,
        },
        "diagnostics": {
            "engine": "event_driven",
            "pnl_source": "ledger_fills",
            "ledger_equity_consistent": True,
        },
    }
    cost_ok = {"engine": "event_driven", "survival_rate_pct": 100.0, "ledger_consistency_pct": 100.0}
    walk_ok = {
        "stability": {
            "fold_pass_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "regime_pass_rate_pct": 100.0,
        }
    }

    result = qualify_crypto_candidates(
        [candidate],
        cost_stress_by_candidate={"btc_orderflow_pressure": cost_ok},
        walk_forward_by_candidate={"btc_orderflow_pressure": walk_ok},
        event_backtest_by_candidate={"btc_orderflow_pressure": event_weak},
        max_selected=1,
    )

    row = result["candidates"][0]
    assert row["qualified"] is False
    assert row["selected"] is False
    assert result["selected_count"] == 0
    assert "event backtest profit_factor < 1.15" in row["qualification_blockers"]


def test_qualify_crypto_candidates_applies_runtime_turnover_holding_and_cost_filters() -> None:
    candidate = {
        "strategy_id": "macro_trend",
        "score": 3.0,
        "validation": {
            "total_return_pct": 11.0,
            "sharpe_ratio": 1.5,
            "profit_factor": 1.8,
            "max_drawdown_pct": -6.0,
            "trade_count": 18,
        },
        "research_metadata": {
            "runtime_hints": {
                "cost_aware_filter": True,
                "max_annual_turnover_pct": 365.0,
                "min_holding_bars": 24,
            }
        },
    }
    event_ok = {"diagnostics": {"engine": "event_driven", "pnl_source": "ledger_fills", "ledger_equity_consistent": True}}
    cost_stress = {
        "engine": "event_driven",
        "survival_rate_pct": 100.0,
        "ledger_consistency_pct": 100.0,
        "cost_sensitivity": 0.62,
    }
    walk_forward = {
        "stability": {
            "fold_pass_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "regime_pass_rate_pct": 100.0,
            "oos_avg_turnover_pct": 480.0,
            "oos_avg_holding_bars": 12.0,
        }
    }

    result = qualify_crypto_candidates(
        [candidate],
        cost_stress_by_candidate={"macro_trend": cost_stress},
        walk_forward_by_candidate={"macro_trend": walk_forward},
        event_backtest_by_candidate={"macro_trend": event_ok},
        max_selected=1,
    )

    row = result["candidates"][0]
    assert row["qualified"] is False
    assert row["selected"] is False
    assert row["screening_metrics"] == {
        "annual_turnover_pct": 480.0,
        "avg_holding_bars": 12.0,
        "cost_sensitivity": 0.62,
    }
    assert "annual turnover > 365.0%" in row["qualification_blockers"]
    assert "avg holding bars < 24.0" in row["qualification_blockers"]
    assert "cost sensitivity > 0.5" in row["qualification_blockers"]


def test_qualify_crypto_candidates_prefers_lower_turnover_and_cost_sensitive_candidates() -> None:
    candidates = [
        {
            "strategy_id": "fast_trend",
            "score": 3.5,
            "validation": {
                "total_return_pct": 12.0,
                "sharpe_ratio": 1.4,
                "profit_factor": 1.6,
                "max_drawdown_pct": -6.0,
                "trade_count": 20,
            },
            "research_metadata": {"runtime_hints": {"cost_aware_filter": True}},
        },
        {
            "strategy_id": "slow_trend",
            "score": 3.0,
            "validation": {
                "total_return_pct": 11.5,
                "sharpe_ratio": 1.35,
                "profit_factor": 1.6,
                "max_drawdown_pct": -6.0,
                "trade_count": 20,
            },
            "research_metadata": {"runtime_hints": {"cost_aware_filter": True}},
        },
    ]
    event_ok = {"diagnostics": {"engine": "event_driven", "pnl_source": "ledger_fills", "ledger_equity_consistent": True}}
    walk_forward = {
        "stability": {
            "fold_pass_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "regime_pass_rate_pct": 100.0,
        }
    }

    result = qualify_crypto_candidates(
        candidates,
        cost_stress_by_candidate={
            "fast_trend": {
                "engine": "event_driven",
                "survival_rate_pct": 100.0,
                "ledger_consistency_pct": 100.0,
                "cost_sensitivity": 0.30,
            },
            "slow_trend": {
                "engine": "event_driven",
                "survival_rate_pct": 100.0,
                "ledger_consistency_pct": 100.0,
                "cost_sensitivity": 0.08,
            },
        },
        walk_forward_by_candidate={
            "fast_trend": {**walk_forward, "stability": {**walk_forward["stability"], "oos_avg_turnover_pct": 540.0}},
            "slow_trend": {**walk_forward, "stability": {**walk_forward["stability"], "oos_avg_turnover_pct": 180.0}},
        },
        event_backtest_by_candidate={"fast_trend": event_ok, "slow_trend": event_ok},
        max_selected=1,
    )

    assert [row["strategy_id"] for row in result["candidates"]] == ["slow_trend", "fast_trend"]
    assert result["selected_candidates"][0]["strategy_id"] == "slow_trend"
