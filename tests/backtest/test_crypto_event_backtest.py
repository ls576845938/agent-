from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pandas as pd

from backend.app.services import backtests as backtest_service_module
from backend.app.services.backtests import ResearchBacktestService
from quant_us.backtest.crypto_event import (
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
    assert stress["survival_rate_pct"] == 100.0
    assert stress["ledger_consistency_pct"] == 100.0
    assert stress["baseline"]["summary"] == baseline.summary
    assert stress["baseline"]["execution"]["pnl_source"] == "ledger_fills"
    assert stress["baseline"]["execution_config"] == {
        "target_weight": 0.9,
        "risk_limit": 0.9,
        "cash_reserve_weight": 0.1,
        "min_cash_buffer_pct": 0.1,
        "min_trade_notional": 25.0,
        "long_only": True,
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
