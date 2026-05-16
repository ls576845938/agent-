from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from backend.app.domain.models import BacktestArtifacts
from backend.app.domain.strategy_registry import strategy_registry
from backend.app.services import backtests as backtest_service_module
from backend.app.services.backtests import ResearchBacktestService


UTC = timezone.utc


def _frame() -> pd.DataFrame:
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    rows = []
    for offset in range(12):
        price = 100.0 + offset
        rows.append(
            {
                "timestamp": start + timedelta(hours=offset),
                "symbol": "BTCUSD",
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "volume": 1_000_000.0,
            }
        )
    return pd.DataFrame(rows).set_index("timestamp")


def _artifact(
    *,
    total_return_pct: float,
    sharpe_ratio: float,
    annual_turnover_pct: float,
    avg_holding_bars: float,
    cost_drag_pct: float,
) -> BacktestArtifacts:
    return BacktestArtifacts(
        mode="optimization",
        summary={
            "total_return_pct": total_return_pct,
            "annual_return_pct": total_return_pct,
            "annual_volatility_pct": 10.0,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sharpe_ratio,
            "max_drawdown_pct": -5.0,
            "calmar_ratio": 1.2,
            "win_rate_pct": 55.0,
            "profit_factor": 1.6,
            "trade_count": 8,
        },
        chart={
            "net_units": [{"time": index, "value": 1.0} for index in range(int(avg_holding_bars))]
            + [{"time": 99, "value": 0.0}],
        },
        strategy_details=[],
        latest_weights=[],
        diagnostics={
            "execution": {
                "annual_turnover_pct": annual_turnover_pct,
                "cost_drag_pct": cost_drag_pct,
            }
        },
    )


def test_optimize_strategy_returns_runtime_metrics_hints_and_penalizes_hot_candidates(monkeypatch) -> None:
    frame = _frame()
    strategy_id = "trend_macd"
    default_params = dict(strategy_registry.get(strategy_id).descriptor.default_params)
    hot_params = {**default_params, "fast_window": 10}

    monkeypatch.setattr(backtest_service_module, "load_market_frame", lambda **_: frame.copy())
    monkeypatch.setattr(
        backtest_service_module,
        "_split_train_validation",
        lambda loaded_frame: (loaded_frame.iloc[:6].copy(), loaded_frame.iloc[6:].copy()),
    )
    monkeypatch.setattr(backtest_service_module, "_candidate_parameter_grid", lambda _: [hot_params, default_params])

    def fake_prepare_strategy_pack(loaded_frame: pd.DataFrame, strategy_ids: list[str], params_map=None):
        params = dict((params_map or {}).get(strategy_id) or {})
        marker = "hot" if params.get("fast_window") == 10 else "stable"
        return {strategy_id: pd.Series([1.0] * len(loaded_frame), index=loaded_frame.index, name=marker)}, {}

    def fake_simulate(*, signals, **_kwargs):
        profile = signals[strategy_id].name
        if profile == "hot":
            return _artifact(
                total_return_pct=14.0,
                sharpe_ratio=1.55,
                annual_turnover_pct=920.0,
                avg_holding_bars=2.0,
                cost_drag_pct=7.5,
            )
        return _artifact(
            total_return_pct=12.0,
            sharpe_ratio=1.45,
            annual_turnover_pct=160.0,
            avg_holding_bars=9.0,
            cost_drag_pct=0.8,
        )

    monkeypatch.setattr(backtest_service_module, "_prepare_strategy_pack", fake_prepare_strategy_pack)
    monkeypatch.setattr(backtest_service_module, "_simulate", fake_simulate)

    result = ResearchBacktestService().optimize_strategy(
        {
            "source": "sqlite",
            "symbol": "BTCUSD",
            "interval": "1h",
            "start": frame.index[0].to_pydatetime(),
            "end": frame.index[-1].to_pydatetime(),
            "strategy_id": strategy_id,
            "max_candidates": 2,
            "max_annual_turnover_pct": 365.0,
            "min_holding_bars": 6,
            "cost_aware_filter": True,
            "event_ledger_screen": False,
        }
    )

    stable, hot = result["candidates"]
    assert stable["parameters"] == default_params
    assert stable["metrics"] == {
        "annual_turnover_pct": 160.0,
        "avg_holding_bars": 9.0,
        "cost_sensitivity": 0.069867,
    }
    assert stable["validation"]["annual_turnover_pct"] == 160.0
    assert stable["validation"]["avg_holding_bars"] == 9.0
    assert stable["validation"]["cost_sensitivity"] == 0.069867
    assert stable["research_metadata"]["runtime_hints"] == {
        "max_annual_turnover_pct": 365.0,
        "min_holding_bars": 6,
        "cost_aware_filter": True,
    }
    assert hot["parameters"] == hot_params
    assert hot["base_score"] > stable["base_score"]
    assert stable["score"] > hot["score"]
    assert hot["metrics"]["cost_sensitivity"] > stable["metrics"]["cost_sensitivity"]


def test_btc_low_turnover_trend_has_optimizer_parameter_grid() -> None:
    grid = backtest_service_module._candidate_parameter_grid("btc_low_turnover_trend")

    assert len(grid) > 1
    assert dict(strategy_registry.get("btc_low_turnover_trend").descriptor.default_params) in grid
    assert all(row["fast_ma"] < row["slow_ma"] < row["trend_ma"] for row in grid)
    assert all(row["min_volatility"] < row["max_volatility"] for row in grid)


def test_btc_new_strategy_families_have_optimizer_parameter_grids() -> None:
    expected_keys = {
        "btc_trend_pullback": {"fast_ma", "slow_ma", "trend_ma", "pullback_pct"},
        "btc_vol_breakout": {"breakout_window", "vol_window", "max_volatility", "volume_mult"},
        "btc_regime_trend": {"fast_ma", "slow_ma", "regime_ma", "momentum_threshold"},
        "btc_low_turnover_breakout": {"entry_window", "exit_window", "trend_ma", "max_volatility"},
        "btc_compression_breakout": {"breakout_window", "compression_window", "compression_recent_bars", "volume_mult"},
        "btc_capitulation_rebound": {"drawdown_window", "pullback_pct", "entry_rsi", "recovery_ma"},
        "btc_perp_dual_trend": {"fast_ma", "slow_ma", "regime_ma", "orderflow_pressure_threshold", "bad_regime_cooldown_bars"},
        "btc_orderflow_pressure": {
            "fast_ma",
            "slow_ma",
            "buy_ratio_threshold",
            "pressure_threshold",
            "downtrend_low_vol_filter_enabled",
            "low_volatility_risk_off_enabled",
            "downtrend_risk_off_enabled",
            "rangebound_risk_off_enabled",
        },
    }

    for strategy_id, keys in expected_keys.items():
        grid = backtest_service_module._candidate_parameter_grid(strategy_id)

        assert len(grid) > 1
        assert dict(strategy_registry.get(strategy_id).descriptor.default_params) in grid
        assert all(keys <= set(row) for row in grid)


def test_btc_contextual_validation_signal_uses_train_warmup_and_resets_target_state() -> None:
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    rows = []
    for offset in range(72):
        price = 100.0 + offset * 0.6
        rows.append(
            {
                "timestamp": start + timedelta(hours=offset),
                "symbol": "BTCUSD",
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1_000_000.0,
            }
        )
    frame = pd.DataFrame(rows).set_index("timestamp")
    context_frame = frame.iloc[:56].copy()
    target_frame = frame.iloc[56:].copy()
    strategy_id = "btc_low_turnover_trend"
    params = {
        "regime_filter_enabled": 0.0,
        "fast_ma": 4,
        "slow_ma": 8,
        "trend_ma": 24,
        "vol_window": 3,
        "min_volatility": 0.0,
        "max_volatility": 1.0,
        "trend_strength": 0.0,
        "exit_buffer": 0.02,
        "entry_confirm_bars": 1,
        "exit_confirm_bars": 1,
        "min_hold_bars": 1,
        "cooldown_bars": 0,
    }

    standalone, _ = backtest_service_module._prepare_strategy_pack(
        target_frame,
        [strategy_id],
        params_map={strategy_id: params},
    )
    contextual, _ = backtest_service_module._prepare_strategy_pack_for_target_window(
        context_frame=context_frame,
        target_frame=target_frame,
        strategy_ids=[strategy_id],
        params_map={strategy_id: params},
    )

    assert standalone[strategy_id].max() == 0.0
    assert contextual[strategy_id].max() == 1.0
    assert contextual[strategy_id].index.equals(target_frame.index)


def test_optimize_strategy_event_ledger_screen_adjusts_top_candidates(monkeypatch) -> None:
    frame = _frame()
    strategy_id = "trend_macd"
    default_params = dict(strategy_registry.get(strategy_id).descriptor.default_params)
    hot_params = {**default_params, "fast_window": 10}

    monkeypatch.setattr(backtest_service_module, "load_market_frame", lambda **_: frame.copy())
    monkeypatch.setattr(
        backtest_service_module,
        "_split_train_validation",
        lambda loaded_frame: (loaded_frame.iloc[:6].copy(), loaded_frame.iloc[6:].copy()),
    )
    monkeypatch.setattr(backtest_service_module, "_candidate_parameter_grid", lambda _: [hot_params, default_params])
    monkeypatch.setattr(
        backtest_service_module,
        "_run_event_ledger_optimizer_screen",
        lambda **kwargs: {
            "summary": {
                "total_return_pct": 8.0,
                "sharpe_ratio": 1.2,
                "profit_factor": 1.4,
                "max_drawdown_pct": -3.0,
                "trade_count": 3,
            },
            "diagnostics": {
                "engine": "event_driven",
                "pnl_source": "ledger_fills",
                "orders": 3,
                "fills": 3,
                "ledger_equity_consistent": True,
                "execution_config": {},
            },
            "metrics": {
                "event_total_return_pct": 8.0,
                "event_sharpe_ratio": 1.2,
                "event_profit_factor": 1.4,
                "event_max_drawdown_pct": -3.0,
                "event_trade_count": 3,
                "event_orders": 3,
                "event_fills": 3,
                "event_ledger_equity_consistent": True,
                "event_pnl_source": "ledger_fills",
            },
        },
    )

    def fake_prepare_strategy_pack(loaded_frame: pd.DataFrame, strategy_ids: list[str], params_map=None):
        return {strategy_id: pd.Series([1.0] * len(loaded_frame), index=loaded_frame.index)}, {}

    monkeypatch.setattr(backtest_service_module, "_prepare_strategy_pack", fake_prepare_strategy_pack)

    result = ResearchBacktestService().optimize_strategy(
        {
            "source": "sqlite",
            "asset_class": "crypto",
            "symbol": "BTCUSD",
            "interval": "1h",
            "start": frame.index[0].to_pydatetime(),
            "end": frame.index[-1].to_pydatetime(),
            "strategy_id": strategy_id,
            "max_candidates": 2,
            "event_ledger_screen": True,
            "event_ledger_screen_top_n": 1,
        }
    )

    screened = [row for row in result["candidates"] if row.get("event_ledger_validation")]
    assert len(screened) == 1
    assert screened[0]["event_ledger_metrics"]["event_ledger_equity_consistent"] is True
    assert screened[0]["research_metadata"]["event_ledger_screen"]["enabled"] is True


def test_vector_simulation_does_not_create_virtual_position_when_order_filtered() -> None:
    frame = _frame()
    signal = pd.Series([1.0] * len(frame), index=frame.index)
    config = backtest_service_module.SimulationConfig(
        mode="unit",
        source="sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=frame.index[0].to_pydatetime(),
        end=frame.index[-1].to_pydatetime(),
        capital=100_000.0,
        commission_rate=0.0,
        slippage=0.0,
        leverage=1.0,
        rebalance_buffer_pct=2.0,
        min_holding_bars=0,
        cost_aware_filter=False,
        max_annual_turnover_pct=1_000_000.0,
    )

    result = backtest_service_module._simulate(
        frame=frame,
        config=config,
        weights={"trend_macd": 1.0},
        signals={"trend_macd": signal},
    )

    assert result.summary["trade_count"] == 0
    assert result.summary["total_return_pct"] == 0.0
    assert all(float(row["value"]) == 0.0 for row in result.chart["net_units"])


def test_vector_simulation_allows_initial_entry_despite_min_holding_guard() -> None:
    frame = _frame()
    signal = pd.Series([1.0] * len(frame), index=frame.index)
    config = backtest_service_module.SimulationConfig(
        mode="unit",
        source="sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=frame.index[0].to_pydatetime(),
        end=frame.index[-1].to_pydatetime(),
        capital=100_000.0,
        commission_rate=0.0,
        slippage=0.0,
        leverage=1.0,
        rebalance_buffer_pct=0.0,
        min_holding_bars=72,
        cost_aware_filter=False,
        max_annual_turnover_pct=1_000_000.0,
    )

    result = backtest_service_module._simulate(
        frame=frame,
        config=config,
        weights={"trend_macd": 1.0},
        signals={"trend_macd": signal},
    )

    assert result.summary["trade_count"] >= 1
    assert any(float(row["value"]) > 0.0 for row in result.chart["net_units"])


def test_walk_forward_regime_failure_analysis_groups_failed_windows() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(hours=idx),
                "symbol": "BTCUSD",
                "open": 100.0 + idx * 0.1,
                "high": 101.0 + idx * 0.1,
                "low": 99.0 + idx * 0.1,
                "close": 100.0 + idx * 0.1,
                "volume": 1000.0,
            }
            for idx in range(40)
        ]
    ).set_index("timestamp")
    regime = backtest_service_module._window_regime_summary(
        frame,
        start=frame.index[10].to_pydatetime(),
        end=frame.index[30].to_pydatetime(),
    )
    failed = {
        "survives": False,
        "status": "completed",
        "regime": regime,
        "failure_reasons": ["negative_oos_return", "drawdown_breach"],
    }

    analysis = backtest_service_module._build_regime_failure_analysis([failed], [])

    assert analysis["failed_window_count"] == 1
    assert analysis["by_trend_state"][regime["trend_state"]] == 1
    assert analysis["by_volatility_state"][regime["volatility_state"]] == 1
    assert analysis["by_reason"]["negative_oos_return"] == 1


def test_crypto_walk_forward_respects_request_long_only_and_keeps_default_true(monkeypatch, tmp_path) -> None:
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(hours=offset),
                "symbol": "BTCUSDT",
                "open": 100.0 + offset * 0.2,
                "high": 101.0 + offset * 0.2,
                "low": 99.0 + offset * 0.2,
                "close": 100.5 + offset * 0.2,
                "volume": 1_000_000.0,
            }
            for offset in range(80)
        ]
    ).set_index("timestamp")
    captured_long_only: list[bool] = []

    monkeypatch.setattr(backtest_service_module, "load_market_frame", lambda **kwargs: frame.copy())
    monkeypatch.setattr(backtest_service_module, "_build_regime_slices", lambda **kwargs: [])

    import quant_us.backtest.crypto_event as crypto_event_module
    import quant_us.backtest.walk_forward as walk_forward_module

    def fake_crypto_execution_settings(**kwargs):
        captured_long_only.append(bool(kwargs["long_only"]))
        return SimpleNamespace(**kwargs)

    def fake_with_crypto_execution_config(unified_config, execution_settings):
        return unified_config

    def fake_run_walk_forward_unified(*, bars, strategy_factory, wf_config, unified_config):
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

    monkeypatch.setattr(crypto_event_module, "_crypto_execution_settings", fake_crypto_execution_settings)
    monkeypatch.setattr(crypto_event_module, "_with_crypto_execution_config", fake_with_crypto_execution_config)
    monkeypatch.setattr(walk_forward_module, "run_walk_forward_unified", fake_run_walk_forward_unified)

    service = ResearchBacktestService()
    default_result = service.run_walk_forward(
        {
            "source": "sqlite",
            "asset_class": "crypto",
            "symbol": "BTCUSDT",
            "symbols": ["BTCUSDT"],
            "interval": "1h",
            "start": start,
            "end": start + timedelta(hours=80),
            "strategy_id": "btc_perp_dual_trend",
            "strategy_params": {"signal_scale": 0.0},
            "capital": 100_000.0,
            "commission_rate": 0.0004,
            "slippage": 4.0,
            "target_weight": 0.85,
            "min_cash_buffer_pct": 0.10,
            "min_trade_notional": 50.0,
            "rebalance_buffer_pct": 0.07,
            "windows": 2,
            "data_root": str(tmp_path),
        }
    )
    short_enabled_result = service.run_walk_forward(
        {
            "source": "sqlite",
            "asset_class": "crypto",
            "symbol": "BTCUSDT",
            "symbols": ["BTCUSDT"],
            "interval": "1h",
            "start": start,
            "end": start + timedelta(hours=80),
            "strategy_id": "btc_perp_dual_trend",
            "strategy_params": {"signal_scale": 0.0},
            "capital": 100_000.0,
            "commission_rate": 0.0004,
            "slippage": 4.0,
            "target_weight": 0.85,
            "min_cash_buffer_pct": 0.10,
            "min_trade_notional": 50.0,
            "rebalance_buffer_pct": 0.07,
            "long_only": False,
            "windows": 2,
            "data_root": str(tmp_path),
        }
    )

    assert default_result["status"] == "completed"
    assert short_enabled_result["status"] == "completed"
    assert captured_long_only == [True, False]


def test_vector_simulation_turnover_guard_does_not_block_initial_entry() -> None:
    frame = _frame()
    signal = pd.Series([1.0] * len(frame), index=frame.index)
    config = backtest_service_module.SimulationConfig(
        mode="unit",
        source="sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=frame.index[0].to_pydatetime(),
        end=frame.index[-1].to_pydatetime(),
        capital=100_000.0,
        commission_rate=0.0,
        slippage=0.0,
        leverage=1.0,
        rebalance_buffer_pct=0.0,
        min_holding_bars=0,
        cost_aware_filter=False,
        max_annual_turnover_pct=0.01,
    )

    result = backtest_service_module._simulate(
        frame=frame,
        config=config,
        weights={"trend_macd": 1.0},
        signals={"trend_macd": signal},
    )

    assert result.summary["trade_count"] >= 1
    assert any(float(row["value"]) > 0.0 for row in result.chart["net_units"])


def test_vector_simulation_turnover_guard_does_not_block_exit_to_flat() -> None:
    frame = _frame()
    signal = pd.Series([1.0, 1.0, 1.0] + [0.0] * (len(frame) - 3), index=frame.index)
    config = backtest_service_module.SimulationConfig(
        mode="unit",
        source="sqlite",
        symbol="BTCUSD",
        interval="1h",
        start=frame.index[0].to_pydatetime(),
        end=frame.index[-1].to_pydatetime(),
        capital=100_000.0,
        commission_rate=0.0,
        slippage=0.0,
        leverage=1.0,
        rebalance_buffer_pct=0.0,
        min_holding_bars=999,
        cost_aware_filter=False,
        max_annual_turnover_pct=0.0,
    )

    result = backtest_service_module._simulate(
        frame=frame,
        config=config,
        weights={"trend_macd": 1.0},
        signals={"trend_macd": signal},
    )

    assert result.summary["trade_count"] == 2
    assert float(result.chart["net_units"][-1]["value"]) == 0.0
