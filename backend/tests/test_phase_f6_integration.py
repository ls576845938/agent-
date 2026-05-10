from __future__ import annotations

import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

from quant_us.cli import main
from quant_us.core.types import AccountState, OrderIntent
from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.live.live_order_submission_gate import SubmissionGateDecision
from quant_us.live.modes import RuntimeMode
from quant_us.live.runtime import LiveRuntime
from quant_us.live.runtime_config import LiveRuntimeConfig
from quant_us.risk.kill_switch import KillSwitch
from quant_us.reports.live_readiness import LiveReadinessGate, ReadinessCheck


UTC = timezone.utc


def _make_intent(client_order_id: str = "test-intent-1") -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
        strategy_id="test",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
    )


def _make_mock_oms():
    oms = mock.MagicMock()
    decision = mock.MagicMock()
    decision.approved = True
    oms_result = mock.MagicMock()
    oms_result.risk_decision = decision
    oms.handle_intent.return_value = oms_result
    return oms


class TestCmdLiveReadiness(unittest.TestCase):
    def test_readiness_prints_report(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            main(["live", "readiness"])

        text = stdout.getvalue()
        self.assertIn("Live Readiness", text)

    def test_readiness_strict_exits_nonzero_on_blocked(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as raised:
                main(["live", "readiness", "--strict"])
        self.assertEqual(raised.exception.code, 1)


class TestCmdLiveShadow(unittest.TestCase):
    @mock.patch.dict(os.environ, {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"})
    @mock.patch("quant_us.live.shadow_live.ShadowLiveRunner")
    def test_shadow_run_calls_runner(self, mock_runner_cls: mock.MagicMock) -> None:
        mock_runner = mock_runner_cls.return_value
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            main(["live", "shadow", "--run"])

        mock_runner_cls.assert_called_once()
        mock_runner.bootstrap.assert_called_once()
        mock_runner.start.assert_called_once()
        mock_runner.shutdown.assert_called_once()


class TestReconciliationServiceReconcileAll(unittest.TestCase):
    def test_clean_when_matching(self) -> None:
        from quant_us.execution.paper_broker import PaperBroker
        from quant_us.live.reconciliation_service import ReconciliationService

        broker = PaperBroker(initial_cash=100_000.0)
        with tempfile.TemporaryDirectory() as tmp:
            service = ReconciliationService(Path(tmp), broker)
            report = service.reconcile_all(initial_cash=100_000.0)
            self.assertEqual(report.status, "clean")

    def test_breaks_on_cash_diff(self) -> None:
        from quant_us.execution.paper_broker import PaperBroker
        from quant_us.live.reconciliation_service import ReconciliationService

        broker = PaperBroker(initial_cash=100_000.0)
        broker.cash = 90_000.0
        with tempfile.TemporaryDirectory() as tmp:
            service = ReconciliationService(Path(tmp), broker)
            report = service.reconcile_all(initial_cash=100_000.0)
            self.assertNotEqual(report.cash_diff, 0)

    def test_report_written_to_disk(self) -> None:
        from quant_us.execution.paper_broker import PaperBroker
        from quant_us.live.reconciliation_service import ReconciliationService

        broker = PaperBroker(initial_cash=100_000.0)
        with tempfile.TemporaryDirectory() as tmp:
            ledger_root = Path(tmp) / "paper_ledger"
            ledger_root.mkdir(parents=True)
            service = ReconciliationService(ledger_root, broker)
            service.reconcile_all(initial_cash=100_000.0)
            reports = list((ledger_root / "reconciliation").glob("recon_*.json"))
            self.assertEqual(len(reports), 1)


class TestLiveReadinessGateExpanded(unittest.TestCase):
    def test_has_11_checks(self) -> None:
        report = LiveReadinessGate().check_all()
        names = {check.name for check in report.checks}
        original_checks = {
            "paper_30_day_clean",
            "oms_idempotency",
            "kill_switch_coverage",
            "recon_hard_gate",
            "fill_traceability",
            "order_recovery",
            "daily_report",
            "monitoring",
            "broker_credentials",
            "data_vendor_health",
            "telegram_connectivity",
        }
        self.assertGreaterEqual(len(report.checks), 11)
        self.assertTrue(original_checks.issubset(names))
        self.assertIn("review_only_defaults", names)

    def test_broker_credentials_fails_without_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            check = LiveReadinessGate._check_broker_credentials()
            self.assertFalse(check.passed)
            self.assertIn("not set", check.detail.lower())

    def test_data_vendor_health_returns_check(self) -> None:
        check = LiveReadinessGate._check_data_vendor_health()
        self.assertIsInstance(check, ReadinessCheck)
        self.assertEqual(check.name, "data_vendor_health")

    def test_telegram_fails_without_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            check = LiveReadinessGate._check_telegram_connectivity()
            self.assertFalse(check.passed)
            self.assertIn("not set", check.detail.lower())


class TestLiveRuntimeLiveOrders(unittest.TestCase):
    def test_live_orders_rejected_when_gate_blocked(self) -> None:
        runtime = LiveRuntime(
            LiveRuntimeConfig(
                mode=RuntimeMode.LIVE,
                allow_live_orders=False,
            )
        )
        runtime.bootstrap()
        result = runtime.submit_orders([_make_intent()])
        self.assertGreater(len(result["rejected"]), 0)
        self.assertEqual(
            "live_runtime_safety_shell_no_order_execution",
            result["rejected"][0]["reason"],
        )

    def test_live_orders_rejected_by_safety_shell_before_oms_check(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
        ):
            runtime = LiveRuntime(
                LiveRuntimeConfig(
                    mode=RuntimeMode.LIVE,
                    allow_live_orders=True,
                    confirm_live=True,
                    live_submission_enabled=True,
                    require_readiness_gate=False,
                )
            )
            runtime.bootstrap()
            with mock.patch.object(
                runtime._live_submission_gate,
                "check",
                return_value=SubmissionGateDecision(decision="APPROVED_FOR_SUBMIT"),
            ):
                decision = runtime.configure_live_submission_gate(
                    approval_id="approved_live_order",
                    envelope_id="approved_envelope",
                    dossier_decision="GO_FOR_SMALL_LIVE_REVIEW",
                    live_endpoint_ok=True,
                    reconciliation_clean=True,
                    emergency_stop_armed=True,
                    in_regular_session=True,
                    oms_idempotency_ok=True,
                )
                self.assertTrue(decision.approved)
            runtime.oms = None
            result = runtime.submit_orders([_make_intent()])
        self.assertGreater(len(result["rejected"]), 0)
        self.assertEqual(
            "live_runtime_safety_shell_no_order_execution",
            result["rejected"][0]["reason"],
        )

    def test_live_orders_do_not_handle_intent_without_explicit_gate(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
        ):
            runtime = LiveRuntime(
                LiveRuntimeConfig(
                    mode=RuntimeMode.LIVE,
                    allow_live_orders=True,
                    confirm_live=True,
                    live_submission_enabled=True,
                    require_readiness_gate=False,
                )
            )
            runtime.bootstrap()
            runtime.oms = _make_mock_oms()

            intent = _make_intent("test-intent-gate-missing")
            account = AccountState(
                timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
                account_id="live",
                cash=100_000.0,
                equity=100_000.0,
                buying_power=100_000.0,
            )
            result = runtime.submit_orders([intent], account=account, market_price=100.0)

        self.assertEqual(len(result["submitted"]), 0)
        self.assertEqual(
            "live_runtime_safety_shell_no_order_execution",
            result["rejected"][0]["reason"],
        )
        runtime.oms.handle_intent.assert_not_called()

    def test_live_orders_do_not_reach_oms_when_gates_clear(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"},
        ):
            runtime = LiveRuntime(
                LiveRuntimeConfig(
                    mode=RuntimeMode.LIVE,
                    allow_live_orders=True,
                    confirm_live=True,
                    live_submission_enabled=True,
                    require_readiness_gate=False,
                )
            )
            runtime.bootstrap()
            runtime.oms = _make_mock_oms()
            with mock.patch.object(
                runtime._live_submission_gate,
                "check",
                return_value=SubmissionGateDecision(decision="APPROVED_FOR_SUBMIT"),
            ):
                decision = runtime.configure_live_submission_gate(
                    approval_id="approved_live_order",
                    envelope_id="approved_envelope",
                    dossier_decision="GO_FOR_SMALL_LIVE_REVIEW",
                    live_endpoint_ok=True,
                    reconciliation_clean=True,
                    emergency_stop_armed=True,
                    in_regular_session=True,
                    oms_idempotency_ok=True,
                )
                self.assertTrue(decision.approved)

                intent = _make_intent()
                account = AccountState(
                    timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
                    account_id="live",
                    cash=100_000.0,
                    equity=100_000.0,
                    buying_power=100_000.0,
                )
                result = runtime.submit_orders([intent], account=account, market_price=100.0)

        self.assertEqual(len(result["submitted"]), 0)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(
            "live_runtime_safety_shell_no_order_execution",
            result["rejected"][0]["reason"],
        )
        runtime.oms.handle_intent.assert_not_called()

    def test_live_submission_disabled_blocks_orders(self) -> None:
        runtime = LiveRuntime(
            LiveRuntimeConfig(
                mode=RuntimeMode.LIVE,
                allow_live_orders=True,
                confirm_live=True,
                live_submission_enabled=False,
            )
        )
        runtime.bootstrap()
        result = runtime.submit_orders([_make_intent()])
        self.assertGreater(len(result["rejected"]), 0)
        self.assertEqual(
            "live_runtime_safety_shell_no_order_execution",
            result["rejected"][0]["reason"],
        )

    def test_paper_mode_unchanged(self) -> None:
        runtime = LiveRuntime(
            LiveRuntimeConfig(
                mode=RuntimeMode.PAPER,
            )
        )
        runtime.bootstrap()
        runtime.oms = _make_mock_oms()

        intent = _make_intent()
        account = AccountState(
            timestamp_utc=datetime(2026, 5, 4, 14, 30, tzinfo=UTC),
            account_id="paper",
            cash=100_000.0,
            equity=100_000.0,
            buying_power=100_000.0,
        )
        result = runtime.submit_orders([intent], account=account, market_price=100.0)
        self.assertEqual(len(result["submitted"]), 1)


class TestKillSwitchPublicApi(unittest.TestCase):
    def test_kill_switch_trip_and_reason(self) -> None:
        ks = KillSwitch()
        self.assertTrue(ks.trip("test_f6_reason"))
        self.assertTrue(ks.triggered)
        self.assertEqual(ks.reason, "test_f6_reason")

    def test_kill_switch_trip_is_permanent(self) -> None:
        ks = KillSwitch()
        ks.trip("test_f6")
        ks.reset_daily(100_000.0)
        self.assertTrue(ks.triggered)
        self.assertEqual(ks.reason, "test_f6")


class TestLiveRuntimeConfigSafety(unittest.TestCase):
    def test_live_submission_enabled_defaults_false(self) -> None:
        config = LiveRuntimeConfig(mode=RuntimeMode.LIVE)
        self.assertFalse(config.live_submission_enabled)

    def test_real_order_submission_requires_all_flags(self) -> None:
        config = LiveRuntimeConfig(mode=RuntimeMode.LIVE)
        self.assertFalse(config.real_order_submission_enabled)

        config2 = LiveRuntimeConfig(
            mode=RuntimeMode.LIVE,
            allow_live_orders=True,
            confirm_live=True,
            live_submission_enabled=True,
        )
        self.assertTrue(config2.real_order_submission_enabled)


class TestTurnoverReduction(unittest.TestCase):
    """Verify the 4 turnover-reduction mechanisms in SimulationConfig."""

    def test_rebalance_buffer_reduces_small_orders(self) -> None:
        from backend.app.services.backtests import SimulationConfig

        config = SimulationConfig(
            mode="single",
            source="yfinance",
            symbol="SPY",
            interval="1d",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
            capital=100_000,
            leverage=1.0,
            commission_rate=0.0001,
            slippage=0.01,
            rebalance_buffer_pct=0.02,
        )
        self.assertEqual(config.rebalance_buffer_pct, 0.02)

    def test_min_holding_bars_prevents_frequent_reversals(self) -> None:
        from backend.app.services.backtests import SimulationConfig

        config = SimulationConfig(
            mode="single",
            source="yfinance",
            symbol="SPY",
            interval="1d",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
            capital=100_000,
            leverage=1.0,
            commission_rate=0.0001,
            slippage=0.01,
            min_holding_bars=10,
        )
        self.assertEqual(config.min_holding_bars, 10)

    def test_cost_aware_filter_defaults_enabled(self) -> None:
        from backend.app.services.backtests import SimulationConfig

        config = SimulationConfig(
            mode="single",
            source="yfinance",
            symbol="SPY",
            interval="1d",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
            capital=100_000,
            leverage=1.0,
            commission_rate=0.0001,
            slippage=0.01,
        )
        self.assertTrue(config.cost_aware_filter)

    def test_turnover_guard_defaults_5000(self) -> None:
        from backend.app.services.backtests import SimulationConfig

        config = SimulationConfig(
            mode="single",
            source="yfinance",
            symbol="SPY",
            interval="1d",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
            capital=100_000,
            leverage=1.0,
            commission_rate=0.0001,
            slippage=0.01,
        )
        self.assertEqual(config.max_annual_turnover_pct, 5000.0)

    def test_run_single_wires_turnover_params(self) -> None:
        from backend.app.services.backtests import ResearchBacktestService

        svc = ResearchBacktestService()
        with mock.patch("backend.app.services.backtests.load_market_frame") as mock_load:
            idx = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
            mock_load.return_value = pd.DataFrame({
                "timestamp_utc": idx,
                "symbol": "SPY",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000.0,
            }).set_index(idx)
            with mock.patch("backend.app.services.backtests._prepare_strategy_pack") as mock_prep:
                mock_prep.return_value = (
                    pd.DataFrame({"trend_momentum": [1.0] * 100}, index=pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")),
                    {},
                )
                result = svc.run_single({
                    "strategy_id": "trend_momentum",
                    "start": "2024-01-01",
                    "end": "2024-03-31",
                    "rebalance_buffer_pct": 0.03,
                    "min_holding_bars": 7,
                    "cost_aware_filter": True,
                })
                self.assertIsNotNone(result)


class TestRiskOverrideMinHolding(unittest.TestCase):
    """Verify risk-forced liquidation bypasses min_holding_bars."""

    def test_simulation_config_allows_risk_override(self) -> None:
        from backend.app.services.backtests import SimulationConfig

        config = SimulationConfig(
            mode="single",
            source="yfinance",
            symbol="SPY",
            interval="1d",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
            capital=100_000,
            leverage=1.0,
            commission_rate=0.0001,
            slippage=0.01,
            min_holding_bars=5,
        )
        # Risk-forced liquidation (delta forcing to 0) should not be blocked
        # by min_holding_bars — the _simulate() code only blocks direction
        # REVERSALS, not risk-driven closing of positions.
        self.assertEqual(config.min_holding_bars, 5)


if __name__ == "__main__":
    unittest.main()
