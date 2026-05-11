from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar, Signal
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig, PaperSessionMetrics
from quant_us.strategies.base import Strategy, StrategyContext


UTC = timezone.utc
MARKET_OPEN = datetime(2026, 5, 8, 14, 30, tzinfo=UTC)


class SymbolStrategy(Strategy):
    version = "fixture"

    def __init__(self, strategy_id: str, symbol: str) -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.context_run_ids: list[str] = []

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        self.context_run_ids.append(context.run_id)
        if event.bar.symbol != self.symbol:
            return []
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=self.symbol,
                direction=SignalDirection.LONG,
                strength=1.0,
                horizon="1d",
                reason=f"{self.strategy_id}_fixture",
            )
        ]


def _bar(symbol: str, price: float) -> Bar:
    return Bar(
        timestamp_utc=MARKET_OPEN,
        symbol=symbol,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=100_000.0,
        source="test",
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_runtime_multi_strategy_keeps_order_fill_and_report_attribution(
    _mock_loop: object,
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger"
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY", "QQQ"],
            ledger_root=str(ledger_root),
            reconcile_on_start=False,
            reconcile_on_close=True,
            submit_orders=True,
            max_data_delay_seconds=60.0,
        )
    )
    strategies = [
        SymbolStrategy("mean_reversion_fixture", "SPY"),
        SymbolStrategy("momentum_fixture", "QQQ"),
    ]
    runtime.bootstrap(strategy=strategies)
    runtime.data_freshness.evaluate_bar = lambda bar, now=None: type(  # type: ignore[method-assign]
        "Freshness",
        (),
        {"fresh": True, "delay_seconds": 0.0, "stale_seconds": 0.0, "reason": "fresh"},
    )()

    handle_calls = []
    original_handle_intent = runtime.oms.handle_intent

    def tracking_handle_intent(*args, **kwargs):
        handle_calls.append(args[0])
        return original_handle_intent(*args, **kwargs)

    runtime.oms.handle_intent = tracking_handle_intent  # type: ignore[method-assign]

    metrics = PaperSessionMetrics()
    runtime._process_bar(_bar("SPY", 500.0), metrics)
    runtime._process_bar(_bar("QQQ", 400.0), metrics)
    runtime.on_session_close()

    orders = runtime.ledger.read_records("orders.jsonl")
    fills = runtime.ledger.read_records("fills.jsonl")
    manifest = _read_json(ledger_root / "audit" / "paper_session_manifest.json")
    report_files = sorted((ledger_root / "daily_reports").glob("daily_report_*.json"))
    report = _read_json(report_files[-1])
    attribution = report["strategy_attribution"]

    assert len(handle_calls) == 2
    assert {order["strategy_id"] for order in orders} == {
        "mean_reversion_fixture",
        "momentum_fixture",
    }
    assert {fill["strategy_id"] for fill in fills} == {
        "mean_reversion_fixture",
        "momentum_fixture",
    }
    assert all(fill["client_order_id"] for fill in fills)
    assert all(fill["signal_id"] for fill in fills)
    assert all(fill["paper_session_id"] == runtime.session_id for fill in fills)
    assert manifest["strategy_ids"] == [
        "mean_reversion_fixture",
        "momentum_fixture",
    ]
    assert [entry["strategy_id"] for entry in manifest["strategies"]] == [
        "mean_reversion_fixture",
        "momentum_fixture",
    ]
    assert set(attribution["by_strategy"]) == {
        "mean_reversion_fixture",
        "momentum_fixture",
    }
    assert attribution["totals"]["orders"] == 2
    assert attribution["totals"]["fills"] == 2
    assert report["strategy_attribution_path"]
    assert runtime.config.allow_live_orders is False
    assert runtime._paper_broker_backend() == "simulated"


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_runtime_nets_same_symbol_strategies_before_oms(
    _mock_loop: object,
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger"
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(ledger_root),
            reconcile_on_start=False,
            reconcile_on_close=True,
            submit_orders=True,
            max_data_delay_seconds=60.0,
        )
    )
    runtime.bootstrap(
        strategy=[
            SymbolStrategy("mean_reversion_fixture", "SPY"),
            SymbolStrategy("momentum_fixture", "SPY"),
        ]
    )
    runtime.data_freshness.evaluate_bar = lambda bar, now=None: type(  # type: ignore[method-assign]
        "Freshness",
        (),
        {"fresh": True, "delay_seconds": 0.0, "stale_seconds": 0.0, "reason": "fresh"},
    )()

    handle_calls = []
    original_handle_intent = runtime.oms.handle_intent

    def tracking_handle_intent(*args, **kwargs):
        handle_calls.append(args[0])
        return original_handle_intent(*args, **kwargs)

    runtime.oms.handle_intent = tracking_handle_intent  # type: ignore[method-assign]

    metrics = PaperSessionMetrics()
    runtime._process_bar(_bar("SPY", 500.0), metrics)
    runtime.on_session_close()

    orders = runtime.ledger.read_records("orders.jsonl")
    report_files = sorted((ledger_root / "daily_reports").glob("daily_report_*.json"))
    attribution = _read_json(report_files[-1])["strategy_attribution"]

    assert len(handle_calls) == 1
    assert len(orders) == 1
    assert orders[0]["strategy_id"] == "portfolio"
    contributions = orders[0]["metadata"]["strategy_contributions"]
    assert {row["strategy_id"] for row in contributions} == {
        "mean_reversion_fixture",
        "momentum_fixture",
    }
    assert set(attribution["by_strategy"]) == {
        "mean_reversion_fixture",
        "momentum_fixture",
    }
    assert attribution["totals"]["orders"] == 1
    assert attribution["totals"]["fills"] == 1


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_strategy_attribution_ignores_prior_session_ledger_rows(
    _mock_loop: object,
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger"
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(ledger_root),
            reconcile_on_start=False,
            reconcile_on_close=False,
            submit_orders=False,
        )
    )
    runtime.bootstrap(strategy=None)
    runtime.ledger.append_order(
        {
            "order_id": "old_order",
            "strategy_id": "old_strategy",
            "paper_session_id": "previous_session",
            "symbol": "SPY",
            "client_order_id": "old_client_order",
        }
    )
    runtime.ledger.append_fill(
        {
            "fill_id": "old_fill",
            "order_id": "old_order",
            "strategy_id": "old_strategy",
            "paper_session_id": "previous_session",
            "symbol": "SPY",
            "quantity": 10.0,
            "price": 500.0,
            "commission": 1.0,
        }
    )

    runtime.on_session_close()

    report_files = sorted((ledger_root / "daily_reports").glob("daily_report_*.json"))
    attribution = _read_json(report_files[-1])["strategy_attribution"]
    assert attribution["by_strategy"] == {}
    assert attribution["totals"]["orders"] == 0
    assert attribution["totals"]["fills"] == 0
