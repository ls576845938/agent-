from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pandas as pd

from backend.app.services import backtests as backtest_service_module
from backend.app.services.backtests import ResearchBacktestService
from quant_us.backtest.crypto_event import run_crypto_event_backtest
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
