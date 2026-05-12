from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
