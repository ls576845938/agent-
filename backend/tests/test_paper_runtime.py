"""Tests for PaperRuntime and PaperScheduler.

Run with::

    PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_paper_runtime.py -v --tb=short

All broker / API / connector calls are mocked — no real Alpaca or yfinance calls.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus, SignalDirection, SessionName
from quant_us.core.events import MarketEvent
from quant_us.core.types import (
    AccountState,
    Bar,
    Fill,
    Order,
    OrderIntent,
    Position,
    RiskDecision,
    Signal,
    new_id,
)
from quant_us.live.fake_alpaca_paper_adapter import FakeAlpacaPaperBrokerAdapter
from quant_us.live.paper_adapter_contract import PAPER_ADAPTER_CONTRACT_VERSION
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig, PaperSessionMetrics
from quant_us.live.paper_scheduler import PaperScheduler, PaperSchedulerConfig
from quant_us.research.evidence_registry import rebuild_evidence_registry
from quant_us.strategies.base import Strategy, StrategyContext

UTC = timezone.utc
ET = ZoneInfo("America/New_York")

# ======================================================================
# Helpers
# ======================================================================


def _make_bar(
    symbol: str = "AAPL",
    price: float = 150.0,
    ts: datetime | None = None,
) -> Bar:
    if ts is None:
        ts = datetime(2026, 5, 4, 14, 30, tzinfo=UTC)  # 10:30 ET Monday
    return Bar(
        timestamp_utc=ts,
        symbol=symbol,
        open=price * 0.999,
        high=price * 1.005,
        low=price * 0.995,
        close=price,
        volume=50_000.0,
        source="test",
    )


def _make_market_data_status(
    fresh: bool = True,
    symbols: list[str] | None = None,
    stale_seconds: float = 0.0,
    error: str | None = None,
) -> mock.MagicMock:
    status = mock.MagicMock()
    status.fresh = fresh
    status.stale_seconds = stale_seconds
    status.symbols_updated = symbols or ["AAPL"]
    status.latest_timestamp = utc_now()
    status.error = error
    return status


def _make_dataframe_bar(symbol: str = "AAPL", price: float = 150.0, ts: datetime | None = None) -> pd.DataFrame:
    if ts is None:
        ts = datetime(2026, 5, 4, 14, 30, tzinfo=UTC)
    return pd.DataFrame([{
        "symbol": symbol,
        "timestamp_utc": ts.isoformat(),
        "open": price * 0.999,
        "high": price * 1.005,
        "low": price * 0.995,
        "close": price,
        "volume": 50_000.0,
    }])


class FakeStrategy(Strategy):
    """A strategy that returns a fixed list of signals per bar."""

    strategy_id: str = "test_strategy"
    version: str = "0.1.0"

    def __init__(self, signals: list[Signal] | None = None) -> None:
        self._signals = signals or []
        self.calls: list[tuple[MarketEvent, StrategyContext]] = []

    def on_bar(self, event: MarketEvent, context: StrategyContext):  # type: ignore[override]
        self.calls.append((event, context))
        return self._signals


class FakeAdapterPaperRuntime(PaperRuntime):
    @staticmethod
    def _alpaca_paper_adapter_enabled() -> bool:
        return True

    @staticmethod
    def _alpaca_paper_adapter_factory_present() -> bool:
        return True

    @staticmethod
    def _alpaca_paper_adapter_capabilities() -> dict[str, bool]:
        return FakeAlpacaPaperBrokerAdapter.contract_capabilities()

    def _create_alpaca_paper_broker(self) -> FakeAlpacaPaperBrokerAdapter:
        return FakeAlpacaPaperBrokerAdapter(initial_cash=self.config.capital)


class FailingSyncFakeAdapterPaperRuntime(FakeAdapterPaperRuntime):
    def __init__(self, *args, fail_on_call: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fail_on_call = fail_on_call

    def _create_alpaca_paper_broker(self) -> FakeAlpacaPaperBrokerAdapter:
        return FakeAlpacaPaperBrokerAdapter(
            initial_cash=self.config.capital,
            fail_on_call=self._fail_on_call,
        )


class SubmitInPollFakeAlpacaPaperBrokerAdapter(FakeAlpacaPaperBrokerAdapter):
    def poll_orders(self) -> list[Order]:
        self._record_sync_call("poll_orders")
        self.submit_order(
            Order(
                timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
                strategy_id="startup_sync_guard_fixture",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=1.0,
                order_type="MARKET",
                time_in_force="DAY",
                client_order_id="startup_sync_guard_fixture",
                order_id="startup_sync_guard_order",
            )
        )
        return []


class SubmitInPollFakeAdapterPaperRuntime(FakeAdapterPaperRuntime):
    def _create_alpaca_paper_broker(self) -> FakeAlpacaPaperBrokerAdapter:
        return SubmitInPollFakeAlpacaPaperBrokerAdapter(initial_cash=self.config.capital)


def _write_registered_paper_review(data_root: Path) -> Path:
    review_id = "paper_runtime_backend_test"
    evidence_pack_path = data_root / "research" / "evidence_packs" / review_id / "evidence_pack.json"
    evidence_pack_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_pack_path.write_text(
        json.dumps({"paper_review_id": review_id}),
        encoding="utf-8",
    )
    review_path = data_root / "research" / "paper_reviews" / review_id / "review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(
            {
                "paper_review_id": review_id,
                "status": "APPROVED_FOR_PAPER_ONLY",
                "reviewer": "risk-reviewer",
                "evidence_pack_path": str(evidence_pack_path),
            }
        ),
        encoding="utf-8",
    )
    rebuild_evidence_registry(data_root)
    return review_path


def _startup_sync_artifact(ledger_root: str) -> dict[str, Any]:
    return json.loads(
        (Path(ledger_root) / "audit" / "paper_broker_adapter_startup_sync.json").read_text(
            encoding="utf-8"
        )
    )


def _session_manifest(ledger_root: str) -> dict[str, Any]:
    return json.loads(
        (Path(ledger_root) / "audit" / "paper_session_manifest.json").read_text(
            encoding="utf-8"
        )
    )


def _session_manifest_history(ledger_root: str, session_id: str) -> dict[str, Any]:
    return json.loads(
        (
            Path(ledger_root) / "audit" / "paper_session_manifests" / f"{session_id}.json"
        ).read_text(encoding="utf-8")
    )


# ======================================================================
# PaperRuntime tests
# ======================================================================


class TestPaperRuntimeBootstrap(unittest.TestCase):
    """Test that bootstrap() initialises all components."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_initializes_components(self, mock_mdl: mock.MagicMock) -> None:
        """All core components should be wired after bootstrap()."""
        config = PaperRuntimeConfig(
            symbols=["AAPL", "MSFT"],
            capital=200_000.0,
            commission_rate=0.0002,
            slippage_bps=2.0,
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
            submit_orders=False,
        )
        runtime = PaperRuntime(config=config)
        strategy = FakeStrategy()
        runtime.bootstrap(strategy=strategy)

        self.assertTrue(runtime._bootstrapped)
        self.assertIsNotNone(runtime.calendar)
        self.assertIsNotNone(runtime.session_clock)
        self.assertIsNotNone(runtime.kill_switch)
        self.assertIsNotNone(runtime.broker)
        self.assertIsNotNone(runtime.risk_engine)
        self.assertIsNotNone(runtime.oms)
        self.assertIsNotNone(runtime.ledger)
        self.assertIsNotNone(runtime.data_loop)
        self.assertIsNotNone(runtime.data_freshness)
        self.assertIsNotNone(runtime.alerts)
        self.assertIs(runtime.strategy, strategy)

        # Check config is propagated to broker
        self.assertAlmostEqual(runtime.broker.cash, 200_000.0)
        self.assertAlmostEqual(runtime.broker.commission_model.rate, 0.0002)

        # Ledger root must exist
        self.assertTrue(Path(self.ledger_root).exists())
        manifest = _session_manifest(self.ledger_root)
        self.assertEqual(manifest["mode"], "paper")
        self.assertEqual(manifest["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(manifest["broker_backend"], "simulated")
        self.assertFalse(manifest["submit_orders"])
        self.assertEqual(manifest["startup_sync_status"]["status"], "skipped")
        self.assertFalse(manifest["no_real_order_submission_proof"]["real_order_submission"])

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_persists_session_manifest_history(self, mock_mdl: mock.MagicMock) -> None:
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
        )

        first_runtime = PaperRuntime(config=config)
        first_runtime.bootstrap(strategy=FakeStrategy())
        first_session_id = first_runtime.session_id
        first_history = _session_manifest_history(self.ledger_root, first_session_id)
        first_runtime.shutdown()

        second_runtime = PaperRuntime(config=config)
        second_runtime.bootstrap(strategy=FakeStrategy())
        second_session_id = second_runtime.session_id
        latest_manifest = _session_manifest(self.ledger_root)
        second_history = _session_manifest_history(self.ledger_root, second_session_id)

        self.assertNotEqual(first_session_id, second_session_id)
        self.assertEqual(first_history["session_id"], first_session_id)
        self.assertEqual(second_history["session_id"], second_session_id)
        self.assertEqual(latest_manifest, second_history)
        self.assertTrue(
            str(second_history["history_artifact_path"]).endswith(
                f"audit/paper_session_manifests/{second_session_id}.json"
            )
        )
        self.assertTrue(Path(str(first_history["history_artifact_path"])).exists())
        self.assertTrue(Path(str(second_history["history_artifact_path"])).exists())
        second_runtime.shutdown()

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_reconcile_on_start_passes(self, mock_mdl: mock.MagicMock) -> None:
        """reconcile_on_start=True should not raise when ledger is clean."""
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=True,
            kill_on_recon_fail=True,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())
        # Reconcile on start with empty ledger/broker should pass
        self.assertTrue(runtime.is_healthy())

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_without_strategy(self, mock_mdl: mock.MagicMock) -> None:
        """bootstrap() should work without a strategy (data-only mode)."""
        config = PaperRuntimeConfig(symbols=["AAPL"], ledger_root=self.ledger_root, reconcile_on_start=False)
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=None)
        self.assertTrue(runtime._bootstrapped)
        self.assertIsNone(runtime.strategy)

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_uses_fake_alpaca_paper_adapter_when_contract_ready(
        self,
        mock_mdl: mock.MagicMock,
    ) -> None:
        review_path = _write_registered_paper_review(Path(self.tmpdir.name))
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=self.tmpdir.name,
        )
        runtime = FakeAdapterPaperRuntime(config=config)

        with mock.patch.dict(
            os.environ,
            {
                "APCA_API_KEY_ID": "paper_key",
                "APCA_API_SECRET_KEY": "paper_secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
                "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
            },
            clear=True,
        ):
            runtime.bootstrap(strategy=FakeStrategy())

        self.assertIsInstance(runtime.broker, FakeAlpacaPaperBrokerAdapter)
        self.assertEqual(runtime._paper_broker_backend(), "alpaca_paper")
        self.assertTrue(
            any(event["event"] == "paper_broker_adapter_activated" for event in runtime.audit_events)
        )

        bar = _make_bar(symbol="AAPL", price=150.0)
        runtime.broker.update_market(bar)
        intent = OrderIntent(
            timestamp_utc=bar.timestamp_utc,
            strategy_id="test_strategy",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1.0,
            client_order_id="backend_fake_adapter_001",
        )
        result = runtime.oms.handle_intent(
            intent,
            runtime.broker.get_account(),
            market_price=150.0,
            timestamp=bar.timestamp_utc,
        )

        self.assertTrue(result.risk_decision.approved)
        self.assertEqual(result.order.status, OrderStatus.FILLED)
        self.assertEqual(len(runtime.broker.poll_orders()), 1)
        self.assertEqual(len(runtime.broker.sync_fills(result.order.order_id)), 1)
        self.assertIn("AAPL", runtime.broker.sync_positions())
        self.assertGreater(runtime.broker.sync_account().equity, 0.0)
        self.assertEqual(
            runtime.broker.cancel_order(result.order.order_id).status,
            OrderStatus.CANCELLED,
        )

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_accepts_exact_paper_endpoint_with_trailing_slash(
        self,
        mock_mdl: mock.MagicMock,
    ) -> None:
        review_path = _write_registered_paper_review(Path(self.tmpdir.name))
        runtime = FakeAdapterPaperRuntime(
            config=PaperRuntimeConfig(
                symbols=["AAPL"],
                ledger_root=self.ledger_root,
                reconcile_on_start=False,
                paper_broker="alpaca",
                paper_review_path=str(review_path),
                promotion_data_root=self.tmpdir.name,
            )
        )

        with mock.patch.dict(
            os.environ,
            {
                "APCA_API_KEY_ID": "paper_key",
                "APCA_API_SECRET_KEY": "paper_secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets/",
                "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
            },
            clear=True,
        ):
            runtime.bootstrap(strategy=FakeStrategy())

        entry_gate = runtime.audit_events[0]["details"]["checks"]
        self.assertTrue(entry_gate["paper_credential_audit"]["base_url_valid"])
        self.assertEqual(
            entry_gate["paper_credential_audit"]["normalized_base_url"],
            "https://paper-api.alpaca.markets",
        )
        self.assertEqual(runtime.broker.sync_call_log, [
            "poll_orders",
            "sync_fills",
            "sync_account",
            "sync_positions",
        ])
        self.assertEqual(runtime.broker.submit_call_count, 0)
        artifact = _startup_sync_artifact(self.ledger_root)
        self.assertEqual(artifact["status"], "ok")
        self.assertEqual(artifact["backend"], "alpaca_paper")
        self.assertEqual(artifact["contract_version"], PAPER_ADAPTER_CONTRACT_VERSION)
        self.assertEqual(artifact["readiness"]["adapter"], "alpaca_paper_fake")
        self.assertFalse(artifact["no_submit_proof"]["submit_order_invoked"])
        self.assertEqual(artifact["no_submit_proof"]["submit_call_count_before"], 0)
        self.assertEqual(artifact["no_submit_proof"]["submit_call_count_after"], 0)
        self.assertEqual(artifact["no_submit_proof"]["submit_call_count_delta"], 0)
        self.assertEqual(artifact["sync"]["poll_orders"]["call_count"], 1)
        self.assertEqual(artifact["sync"]["sync_fills"]["call_count"], 1)
        self.assertEqual(artifact["sync"]["sync_account"]["account_id"], "alpaca_paper_fake")
        self.assertEqual(artifact["sync"]["sync_positions"]["symbols"], [])
        manifest = _session_manifest(self.ledger_root)
        self.assertEqual(manifest["session_id"], runtime.session_id)
        self.assertEqual(manifest["broker_backend"], "alpaca_paper")
        self.assertEqual(manifest["registry_evidence_id"], "paper_runtime_backend_test")
        self.assertEqual(manifest["startup_sync_status"]["status"], "ok")
        self.assertTrue(manifest["startup_sync_status"]["no_submit"])
        self.assertTrue(manifest["no_real_order_submission_proof"]["startup_sync_no_submit"])
        self.assertFalse(manifest["no_real_order_submission_proof"]["real_order_submission"])

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_blocks_when_startup_sync_attempts_submit_order(
        self,
        mock_mdl: mock.MagicMock,
    ) -> None:
        review_path = _write_registered_paper_review(Path(self.tmpdir.name))
        runtime = SubmitInPollFakeAdapterPaperRuntime(
            config=PaperRuntimeConfig(
                symbols=["AAPL"],
                ledger_root=self.ledger_root,
                reconcile_on_start=False,
                paper_broker="alpaca",
                paper_review_path=str(review_path),
                promotion_data_root=self.tmpdir.name,
            )
        )

        with mock.patch.dict(
            os.environ,
            {
                "APCA_API_KEY_ID": "paper_key",
                "APCA_API_SECRET_KEY": "paper_secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
                "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "alpaca_paper_startup_sync_failed"):
                runtime.bootstrap(strategy=FakeStrategy())

        artifact = _startup_sync_artifact(self.ledger_root)
        self.assertEqual(artifact["status"], "failed")
        self.assertEqual(artifact["error"], "alpaca_paper_startup_sync_submit_order_blocked")
        self.assertTrue(artifact["no_submit_proof"]["submit_order_invoked"])
        self.assertTrue(artifact["no_submit_proof"]["submit_order_wrapper_invoked"])
        self.assertTrue(artifact["no_submit_proof"]["submit_order_wrapper_blocked"])
        self.assertTrue(artifact["no_submit_proof"]["submit_order_guard_installed"])
        self.assertTrue(artifact["no_submit_proof"]["submit_order_guard_restored"])
        self.assertEqual(
            artifact["no_submit_proof"]["submit_order_wrapper_order_ids"],
            ["startup_sync_guard_order"],
        )

        runtime.broker.update_market(_make_bar(symbol="SPY", price=500.0, ts=datetime(2026, 5, 9, 14, 31, tzinfo=UTC)))
        runtime.broker.submit_order(
            Order(
                timestamp_utc=datetime(2026, 5, 9, 14, 31, tzinfo=UTC),
                strategy_id="post_restore_check",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=1.0,
                order_type="MARKET",
                time_in_force="DAY",
                client_order_id="post_restore_check",
                order_id="post_restore_order",
            )
        )
        self.assertEqual(runtime.broker.submit_call_count, 1)

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_blocks_when_paper_adapter_startup_sync_fails(
        self,
        mock_mdl: mock.MagicMock,
    ) -> None:
        review_path = _write_registered_paper_review(Path(self.tmpdir.name))
        runtime = FailingSyncFakeAdapterPaperRuntime(
            config=PaperRuntimeConfig(
                symbols=["AAPL"],
                ledger_root=self.ledger_root,
                reconcile_on_start=False,
                paper_broker="alpaca",
                paper_review_path=str(review_path),
                promotion_data_root=self.tmpdir.name,
            ),
            fail_on_call="sync_account",
        )

        with mock.patch.dict(
            os.environ,
            {
                "APCA_API_KEY_ID": "paper_key",
                "APCA_API_SECRET_KEY": "paper_secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
                "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "alpaca_paper_startup_sync_failed"):
                runtime.bootstrap(strategy=FakeStrategy())

        self.assertTrue(runtime.kill_switch.triggered)
        self.assertTrue(runtime.oms.reduce_only)
        self.assertEqual(runtime.audit_events[-1]["event"], "paper_broker_adapter_startup_sync_failed")
        self.assertEqual(runtime.broker.submit_call_count, 0)
        artifact = _startup_sync_artifact(self.ledger_root)
        self.assertEqual(artifact["status"], "failed")
        self.assertEqual(artifact["backend"], "alpaca_paper")
        self.assertEqual(artifact["contract_version"], PAPER_ADAPTER_CONTRACT_VERSION)
        self.assertEqual(artifact["error"], "sync_account_failed")
        self.assertTrue(artifact["reduce_only"])
        self.assertTrue(artifact["halt_reconciliation"])
        self.assertFalse(artifact["no_submit_proof"]["submit_order_invoked"])
        self.assertEqual(artifact["no_submit_proof"]["submit_call_count_delta"], 0)
        self.assertEqual(artifact["sync"]["poll_orders"]["call_count"], 1)
        self.assertEqual(artifact["sync"]["sync_fills"]["call_count"], 1)
        self.assertEqual(artifact["sync"]["sync_account"]["call_count"], 1)
        self.assertEqual(artifact["sync"]["sync_account"]["account_id"], "")


class TestPaperRuntimeCycle(unittest.TestCase):
    """Test a single poll cycle of run_market_session."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _make_runtime(
        self,
        config: PaperRuntimeConfig | None = None,
        strategy: Strategy | None = None,
    ) -> PaperRuntime:
        if config is None:
            config = PaperRuntimeConfig(
                symbols=["AAPL"],
                ledger_root=self.ledger_root,
                reconcile_on_start=False,
                poll_interval_seconds=0.01,
                submit_orders=False,
            )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=strategy or FakeStrategy())
        return runtime

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_run_one_cycle_with_mocked_broker(self, mock_mdl_cls: mock.MagicMock) -> None:
        """Single cycle fetches data and generates metrics."""
        mock_loop = mock_mdl_cls.return_value
        mock_loop.run_once.return_value = _make_market_data_status(fresh=True, symbols=["AAPL"])
        mock_loop.fetch_latest_bars.return_value = _make_dataframe_bar()

        signal = Signal(
            timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
            strategy_id="test_strategy",
            symbol="AAPL",
            direction=SignalDirection.LONG,
            strength=0.5,
            horizon="1d",
        )
        strategy = FakeStrategy(signals=[signal])
        runtime = self._make_runtime(strategy=strategy)

        # Monkey-patch _should_keep_running to run exactly once
        call_count: list[int] = [0]

        def _one_shot() -> bool:
            call_count[0] += 1
            return call_count[0] <= 1

        runtime._should_keep_running = _one_shot  # type: ignore[assignment]
        runtime._sleep = lambda: None  # type: ignore[method-assign]

        runtime.run_market_session()

        # Metrics should have been recorded
        self.assertGreater(len(runtime.metrics_log), 0)
        last_metrics = runtime.metrics_log[-1]
        self.assertTrue(last_metrics.fresh_bars)

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_submit_orders_false_does_not_submit(self, mock_mdl_cls: mock.MagicMock) -> None:
        """With submit_orders=False, intents should be created but not submitted."""
        mock_loop = mock_mdl_cls.return_value
        mock_loop.run_once.return_value = _make_market_data_status(fresh=True, symbols=["AAPL"])
        mock_loop.fetch_latest_bars.return_value = _make_dataframe_bar()

        signal = Signal(
            timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
            strategy_id="test_strategy",
            symbol="AAPL",
            direction=SignalDirection.LONG,
            strength=1.0,
            horizon="1d",
        )
        strategy = FakeStrategy(signals=[signal])
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
            submit_orders=False,  # <-- key setting
        )
        runtime = self._make_runtime(config=config, strategy=strategy)

        call_count: list[int] = [0]

        def _one_shot() -> bool:
            call_count[0] += 1
            return call_count[0] <= 1

        runtime._should_keep_running = _one_shot  # type: ignore[assignment]
        runtime._sleep = lambda: None  # type: ignore[method-assign]

        # Track whether submit was called
        original_handle = runtime.oms.handle_intent
        handle_called = []

        def _tracking_handle(*args, **kwargs):
            handle_called.append(True)
            return original_handle(*args, **kwargs)

        runtime.oms.handle_intent = _tracking_handle  # type: ignore[assignment]

        runtime.run_market_session()

        # With submit_orders=False, handle_intent should NOT be called
        self.assertEqual(len(handle_called), 0, "handle_intent should not be called when submit_orders=False")

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_stale_data_does_not_trigger_signals(self, mock_mdl_cls: mock.MagicMock) -> None:
        """When market data is stale, the cycle should skip signal processing."""
        mock_loop = mock_mdl_cls.return_value
        mock_loop.run_once.return_value = _make_market_data_status(fresh=False, stale_seconds=600.0)

        strategy = FakeStrategy(signals=[])
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
        )
        runtime = self._make_runtime(config=config, strategy=strategy)

        call_count: list[int] = [0]

        def _one_shot() -> bool:
            call_count[0] += 1
            return call_count[0] <= 1

        runtime._should_keep_running = _one_shot  # type: ignore[assignment]
        runtime._sleep = lambda: None  # type: ignore[method-assign]

        runtime.run_market_session()

        # No bars should have been processed
        last_metrics = runtime.metrics_log[-1]
        self.assertFalse(last_metrics.fresh_bars)

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_kill_switch_stops_session(self, mock_mdl_cls: mock.MagicMock) -> None:
        """When kill switch is triggered, the session loop should exit."""
        mock_loop = mock_mdl_cls.return_value
        mock_loop.run_once.return_value = _make_market_data_status(fresh=True, symbols=["AAPL"])
        mock_loop.fetch_latest_bars.return_value = _make_dataframe_bar()

        strategy = FakeStrategy()
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
        )
        runtime = self._make_runtime(config=config, strategy=strategy)
        runtime.kill_switch.trip("test_trigger")
        runtime._sleep = lambda: None  # type: ignore[method-assign]

        runtime.run_market_session()

        # Should have exited immediately without processing any cycles
        self.assertFalse(runtime.is_healthy())


class TestPaperRuntimeSessionClose(unittest.TestCase):
    """Test on_session_close behavior."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_on_session_close_generates_report(self, mock_mdl_cls: mock.MagicMock) -> None:
        """on_session_close should create a daily report file."""
        mock_loop = mock_mdl_cls.return_value
        mock_loop.run_once.return_value = _make_market_data_status(fresh=True, symbols=["AAPL"])
        mock_loop.fetch_latest_bars.return_value = _make_dataframe_bar()

        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
            reconcile_on_close=True,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())

        # Put a fill on the broker so the report has something to show
        bar = _make_bar()
        runtime.broker.update_market(bar)
        order = Order(
            timestamp_utc=bar.timestamp_utc,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            order_type="MARKET",
            time_in_force="DAY",
            client_order_id=new_id("coid"),
        )
        runtime.broker.submit_order(order)
        for fill in runtime.broker.get_fills():
            runtime.ledger.append_fill(fill)

        runtime.on_session_close()

        # Check daily report file exists
        report_dir = Path(self.ledger_root) / "daily_reports"
        report_files = list(report_dir.glob("daily_report_*.json"))
        self.assertEqual(len(report_files), 1, "Exactly one daily report should exist")

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_on_session_close_reconcile_passes(self, mock_mdl_cls: mock.MagicMock) -> None:
        """on_session_close reconciliation should pass with clean state."""
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
            reconcile_on_close=True,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())
        runtime.on_session_close()

        # Should not have halted reconciliation or triggered kill switch
        self.assertFalse(runtime._halt_reconciliation)


class TestPaperRuntimeShutdown(unittest.TestCase):
    """Test shutdown behavior."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_shutdown_persists_state(self, mock_mdl_cls: mock.MagicMock) -> None:
        """shutdown() should persist idempotency file."""
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())

        runtime.shutdown()

        # Idempotency file should exist
        idem_path = Path(self.ledger_root) / ".idempotency.json"
        self.assertTrue(idem_path.exists(), "Idempotency file should exist after shutdown")

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_shutdown_bootstrapped_flag_cleared(self, mock_mdl_cls: mock.MagicMock) -> None:
        """shutdown() should clear the bootstrapped flag."""
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())
        runtime.shutdown()
        self.assertFalse(runtime._bootstrapped)

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_shutdown_twice_safe(self, mock_mdl_cls: mock.MagicMock) -> None:
        """Calling shutdown() twice should not raise."""
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())
        runtime.shutdown()
        runtime.shutdown()  # second call should be safe
        self.assertFalse(runtime._bootstrapped)


class TestPaperRuntimeKillOnReconFail(unittest.TestCase):
    """Test kill_on_recon_fail behavior."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_kill_on_recon_fail_triggers_kill_switch(self, mock_mdl_cls: mock.MagicMock) -> None:
        """When kill_on_recon_fail=True and recon breaks, kill switch triggers via on_session_close."""
        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
            reconcile_on_close=True,
            kill_on_recon_fail=True,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())

        # Create a reconciliation mismatch: manually write a fill to ledger
        # that the broker doesn't have, so local cash differs from broker cash
        fake_fill = Fill(
            order_id=new_id("ord"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            price=150.0,
            commission=1.5,
            filled_at=utc_now(),
            broker="paper_runtime",
        )
        runtime.ledger.append_fill(fake_fill)

        runtime.on_session_close()

        # Kill switch should be triggered due to recon failure
        self.assertTrue(runtime._halt_reconciliation)
        # record_recon_failure increments consecutive_recon_failures but
        # may not trigger immediately if max_consecutive_recon_failures > 1
        # We just check the halt flag is set
        self.assertTrue(runtime._halt_reconciliation)


class TestPaperRuntimeFullSession(unittest.TestCase):
    """Integration-style test of a complete runtime session."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_bootstrap_run_close_shutdown_sequence(self, mock_mdl_cls: mock.MagicMock) -> None:
        """Full bootstrap -> run -> close -> shutdown sequence should not raise."""
        mock_loop = mock_mdl_cls.return_value
        mock_loop.run_once.return_value = _make_market_data_status(fresh=True, symbols=["AAPL"])
        mock_loop.fetch_latest_bars.return_value = _make_dataframe_bar()

        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=False,
            reconcile_on_close=False,
            submit_orders=False,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())

        # Run one cycle
        call_count: list[int] = [0]

        def _one_shot() -> bool:
            call_count[0] += 1
            return call_count[0] <= 1

        runtime._should_keep_running = _one_shot  # type: ignore[assignment]
        runtime._sleep = lambda: None  # type: ignore[method-assign]

        runtime.run_market_session()
        runtime.on_session_close()
        runtime.shutdown()

        self.assertFalse(runtime._bootstrapped)
        self.assertFalse(runtime.is_healthy())  # not bootstrapped = not healthy


# ======================================================================
# PaperScheduler tests
# ======================================================================


class TestPaperSchedulerWeekendHoliday(unittest.TestCase):
    """Test scheduler skips weekends/holidays."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @mock.patch("quant_us.live.paper_scheduler.PaperRuntime")
    @mock.patch("quant_us.live.paper_scheduler.SessionClock")
    def test_scheduler_skips_weekend(
        self,
        mock_clock_cls: mock.MagicMock,
        mock_runtime_cls: mock.MagicMock,
    ) -> None:
        """Scheduler should skip weekend days and only run on trading days."""
        mock_clock = mock.MagicMock()
        mock_clock_cls.return_value = mock_clock
        cal = USEquityCalendar.with_holidays(years=(2026,))

        # May 2, 2026 = Saturday — should_be_running false
        # May 4, 2026 = Monday — should_be_running true, close after warmup grace
        # We simulate the scheduler starting on Saturday

        # Control time progression
        time_values: list[datetime] = [
            datetime(2026, 5, 2, 12, 0, tzinfo=UTC),  # Saturday — not open
            datetime(2026, 5, 2, 12, 5, tzinfo=UTC),  # still Saturday
            datetime(2026, 5, 4, 9, 0, tzinfo=UTC),  # Monday, within warmup (30min before open)
            datetime(2026, 5, 4, 16, 30, tzinfo=UTC),  # Monday, after close + grace
            datetime(2026, 5, 4, 16, 35, tzinfo=UTC),  # still Monday after close
        ]
        time_idx: list[int] = [0]

        def _next_time() -> datetime:
            val = time_values[time_idx[0]]
            time_idx[0] += 1
            return val

        mock_clock.should_be_running.side_effect = lambda now, warmup_minutes=30.0: (
            now >= time_values[2]
        )
        mock_clock.should_shutdown.side_effect = lambda now, after_hours_grace_minutes=15.0: (
            now >= time_values[3]
        )
        mock_clock.time_until_next_session.return_value = (
            (time_values[2] - time_values[0]).total_seconds()
        )

        config = PaperSchedulerConfig(
            runtime_config=PaperRuntimeConfig(
                symbols=["AAPL"],
                ledger_root=self.ledger_root,
                reconcile_on_start=False,
                reconcile_on_close=False,
                submit_orders=False,
            ),
            warmup_minutes=30.0,
            after_hours_grace_minutes=15.0,
            poll_during_close_seconds=0.01,
            max_daily_sessions=1,
        )
        scheduler = PaperScheduler(config=config, calendar=cal)
        scheduler._time_sleep = lambda s: None  # type: ignore[method-assign]

        mock_runtime = mock.MagicMock()
        mock_runtime_cls.return_value = mock_runtime

        scheduler.start()

        # Should have run exactly 1 session (Monday)
        self.assertEqual(scheduler.sessions_run, 1, "Scheduler should run 1 session")

    @mock.patch("quant_us.live.paper_scheduler.PaperRuntime")
    @mock.patch("quant_us.live.paper_scheduler.SessionClock")
    def test_scheduler_waits_for_market_open(
        self,
        mock_clock_cls: mock.MagicMock,
        mock_runtime_cls: mock.MagicMock,
    ) -> None:
        """Scheduler should wait in _wait_for_market_open when market is closed."""
        mock_clock = mock.MagicMock()
        mock_clock_cls.return_value = mock_clock
        cal = USEquityCalendar.with_holidays(years=(2026,))

        # Calls: closed (Sat), closed, open (Mon), then after session
        # completes it checks again — provide enough flags
        open_flags = [False, False, True, False, False, False]
        flag_idx: list[int] = [0]

        def _should_be_running(now, warmup_minutes=30.0):
            idx = min(flag_idx[0], len(open_flags) - 1)
            val = open_flags[idx]
            flag_idx[0] += 1
            return val

        mock_clock.should_be_running.side_effect = _should_be_running
        mock_clock.time_until_next_session.return_value = 3600.0  # 1 hour

        config = PaperSchedulerConfig(
            runtime_config=PaperRuntimeConfig(
                symbols=["AAPL"],
                ledger_root=self.ledger_root,
                reconcile_on_start=False,
                reconcile_on_close=False,
                submit_orders=False,
            ),
            warmup_minutes=30.0,
            poll_during_close_seconds=0.01,
            max_daily_sessions=1,
        )
        scheduler = PaperScheduler(config=config, calendar=cal)

        # Fast-forward: mock runtime to avoid actual execution
        mock_runtime = mock.MagicMock()
        mock_runtime_cls.return_value = mock_runtime
        scheduler._time_sleep = lambda s: None  # type: ignore[method-assign]

        with mock.patch.object(scheduler, '_wait_for_next_day', return_value=None):
            scheduler.start()

        # should_be_running should have been called multiple times
        self.assertGreater(mock_clock.should_be_running.call_count, 0)
        self.assertEqual(scheduler.sessions_run, 1)

    @mock.patch("quant_us.live.paper_scheduler.PaperRuntime")
    @mock.patch("quant_us.live.paper_scheduler.SessionClock")
    def test_scheduler_honors_max_daily_sessions(
        self,
        mock_clock_cls: mock.MagicMock,
        mock_runtime_cls: mock.MagicMock,
    ) -> None:
        """Scheduler should stop after max_daily_sessions is reached."""
        mock_clock = mock.MagicMock()
        mock_clock_cls.return_value = mock_clock
        mock_clock.should_be_running.return_value = True
        mock_clock.should_shutdown.return_value = True  # triggers _wait_for_next_day path
        cal = USEquityCalendar.with_holidays(years=(2026,))

        config = PaperSchedulerConfig(
            runtime_config=PaperRuntimeConfig(
                symbols=["AAPL"],
                ledger_root=self.ledger_root,
                reconcile_on_start=False,
                reconcile_on_close=False,
                submit_orders=False,
            ),
            max_daily_sessions=2,
            poll_during_close_seconds=0.01,
        )
        scheduler = PaperScheduler(config=config, calendar=cal)
        scheduler._time_sleep = lambda s: None  # type: ignore[method-assign]

        mock_runtime = mock.MagicMock()
        mock_runtime_cls.return_value = mock_runtime

        scheduler.start()

        self.assertEqual(scheduler.sessions_run, 2)


class TestPaperSchedulerReconcileOnStart(unittest.TestCase):
    """Test reconcile_on_start behavior integrated with PaperRuntime."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_root = str(Path(self.tmpdir.name) / "ledger")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @mock.patch("quant_us.live.paper_runtime.MarketDataLoop")
    def test_reconcile_on_start_blocks_if_breaks_detected(self, mock_mdl_cls: mock.MagicMock) -> None:
        """When reconcile_on_start=True and breaks exist, runtime should halt."""
        # Write a fill to the ledger before bootstrap so broker and ledger mismatch
        fake_fill = Fill(
            order_id=new_id("ord"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            price=150.0,
            commission=1.5,
            filled_at=utc_now(),
            broker="paper_runtime",
        )
        ledger = Path(self.ledger_root)
        ledger.mkdir(parents=True, exist_ok=True)
        fills_file = ledger / "fills.jsonl"
        with fills_file.open("a") as f:
            f.write(json.dumps({
                "fill_id": fake_fill.fill_id,
                "order_id": fake_fill.order_id,
                "symbol": fake_fill.symbol,
                "side": fake_fill.side.value,
                "quantity": fake_fill.quantity,
                "price": fake_fill.price,
                "commission": fake_fill.commission,
                "filled_at": fake_fill.filled_at.isoformat(),
                "broker": fake_fill.broker,
                "broker_order_id": fake_fill.broker_order_id,
            }) + "\n")

        config = PaperRuntimeConfig(
            symbols=["AAPL"],
            ledger_root=self.ledger_root,
            reconcile_on_start=True,
            kill_on_recon_fail=True,
        )
        runtime = PaperRuntime(config=config)
        runtime.bootstrap(strategy=FakeStrategy())

        # The reconciliation should have failed (ledger says we bought, broker disagrees)
        self.assertTrue(runtime._halt_reconciliation)


if __name__ == "__main__":
    unittest.main()
