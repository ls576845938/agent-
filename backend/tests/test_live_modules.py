"""Tests for live modules: runner, reconciliation_service, state_reconciler.

Covers:
  - LiveRunner construction, check_readiness, start
  - StateReconciler compare_positions and report
  - ReconciliationService reconcile_positions (clean / dirty / edge cases)
Uses MagicMock for external dependencies; no production code modified.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

from quant_us.core.enums import OrderSide
from quant_us.core.types import Position, Fill
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.live.heartbeat import Heartbeat
from quant_us.live.runner import LiveRunner, LiveRunnerConfig, LiveReadinessReport
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.live.state_reconciler import (
    ReconciliationBreak,
    ReconciliationReport,
    StateReconciler,
)
from quant_us.risk.kill_switch import KillSwitch


# ===========================================================================
# Helpers
# ===========================================================================


def _write_fill_jsonl(ledger_dir: Path, fills: list[dict]) -> None:
    """Write fills.jsonl under *ledger_dir* for ledger-backed tests."""
    path = ledger_dir / "fills.jsonl"
    with open(path, "w") as f:
        for fill in fills:
            f.write(json.dumps(fill, sort_keys=True) + "\n")


def _pos(data: dict[str, tuple[float, float]]) -> dict[str, Position]:
    """Build a dict of Position objects from {(symbol, (quantity, market_price))}."""
    return {sym: Position(symbol=sym, quantity=qty, market_price=mp) for sym, (qty, mp) in data.items()}


# ===========================================================================
# LiveRunner tests
# ===========================================================================


class TestLiveRunnerConstruction:
    """LiveRunner dataclass construction and attribute defaults."""

    def test_attributes_set(self) -> None:
        oms = MagicMock()
        hb = Heartbeat("svc")
        runner = LiveRunner(oms=oms, heartbeat=hb)
        assert runner.oms is oms
        assert runner.heartbeat is hb
        assert runner.reconciliation is None
        assert runner.kill_switch is None
        assert isinstance(runner.config, LiveRunnerConfig)
        assert runner.config.allow_live_orders is False
        assert runner.config.require_reconciliation_clean is True

    def test_all_optional_args(self) -> None:
        oms = MagicMock()
        hb = Heartbeat("svc")
        recon = MagicMock(spec=ReconciliationService)
        ks = KillSwitch()
        cfg = LiveRunnerConfig(allow_live_orders=True, require_reconciliation_clean=False)
        runner = LiveRunner(oms=oms, heartbeat=hb, reconciliation=recon, kill_switch=ks, config=cfg)
        assert runner.reconciliation is recon
        assert runner.kill_switch is ks
        assert runner.config.allow_live_orders is True
        assert runner.config.require_reconciliation_clean is False

    def test_empty_oms_and_heartbeat_are_required(self) -> None:
        """Verify that the two required fields cannot be omitted at construction."""
        with pytest.raises(TypeError):
            LiveRunner()  # type: ignore[call-arg]


class TestLiveRunnerCheckReadiness:
    """Test check_readiness() logic under various conditions."""

    @pytest.fixture
    def runner(self) -> LiveRunner:
        oms = MagicMock()
        hb = Heartbeat("svc")
        cfg = LiveRunnerConfig(allow_live_orders=True)
        return LiveRunner(oms=oms, heartbeat=hb, config=cfg)

    def test_ready_when_nothing_blocking(self, runner: LiveRunner) -> None:
        report = runner.check_readiness()
        assert report.ready is True
        assert report.status == "ready"
        assert report.errors == []

    def test_ready_when_live_orders_disabled_paper_mode(self) -> None:
        """Default LiveRunnerConfig has allow_live_orders=False, which is the
        expected paper-mode setting. It is informational only — not a blocking
        error. The live-order gate is enforced in start(), not readiness."""
        oms = MagicMock()
        hb = Heartbeat("svc")
        runner = LiveRunner(oms=oms, heartbeat=hb)
        report = runner.check_readiness()
        assert report.ready is True
        assert report.status == "ready"
        assert report.checks["live_orders_enabled"] is False

    def test_blocked_when_kill_switch_triggered(self) -> None:
        ks = KillSwitch()
        ks._trigger("test_circuit_breaker")
        cfg = LiveRunnerConfig(allow_live_orders=True)
        oms = MagicMock()
        hb = Heartbeat("svc")
        runner = LiveRunner(oms=oms, heartbeat=hb, kill_switch=ks, config=cfg)
        report = runner.check_readiness()
        assert report.ready is False
        assert any("kill_switch" in e for e in report.errors)

    def test_skip_reconciliation_when_recon_is_none(self, runner: LiveRunner) -> None:
        """If reconciliation is None the check is skipped regardless of config flag."""
        assert runner.reconciliation is None
        report = runner.check_readiness()
        assert report.ready is True  # no recon error

    def test_skip_reconciliation_when_require_flag_is_false(self) -> None:
        recon = MagicMock(spec=ReconciliationService)
        # Even if recon reports dirty, the flag being False means no check.
        recon.reconcile_positions.return_value = {"status": "breaks_detected", "break_count": 1}
        cfg = LiveRunnerConfig(allow_live_orders=True, require_reconciliation_clean=False)
        oms = MagicMock()
        hb = Heartbeat("svc")
        runner = LiveRunner(oms=oms, heartbeat=hb, reconciliation=recon, config=cfg)
        report = runner.check_readiness()
        assert report.ready is True
        recon.reconcile_positions.assert_not_called()

    def test_blocked_when_reconciliation_breaks(self) -> None:
        recon = MagicMock(spec=ReconciliationService)
        recon.reconcile_positions.return_value = {"status": "breaks_detected", "break_count": 2, "breaks": []}
        cfg = LiveRunnerConfig(allow_live_orders=True, require_reconciliation_clean=True)
        oms = MagicMock()
        hb = Heartbeat("svc")
        runner = LiveRunner(oms=oms, heartbeat=hb, reconciliation=recon, config=cfg)
        report = runner.check_readiness()
        assert report.ready is False
        assert "reconciliation_breaks_detected" in report.errors

    def test_ready_with_clean_reconciliation(self) -> None:
        recon = MagicMock(spec=ReconciliationService)
        recon.reconcile_positions.return_value = {"status": "clean", "break_count": 0, "breaks": []}
        cfg = LiveRunnerConfig(allow_live_orders=True, require_reconciliation_clean=True)
        oms = MagicMock()
        hb = Heartbeat("svc")
        runner = LiveRunner(oms=oms, heartbeat=hb, reconciliation=recon, config=cfg)
        report = runner.check_readiness()
        assert report.ready is True
        assert report.status == "ready"


class TestLiveRunnerStart:
    """Test start() dry-run vs live behaviour."""

    def test_dry_run_calls_heartbeat_and_returns_report(self) -> None:
        oms = MagicMock()
        hb = Heartbeat("svc")
        cfg = LiveRunnerConfig(allow_live_orders=True)
        runner = LiveRunner(oms=oms, heartbeat=hb, config=cfg)
        last_before = hb.last_seen
        report = runner.start(dry_run=True)
        assert hb.last_seen >= last_before  # heartbeat.beat() was called
        assert isinstance(report, LiveReadinessReport)
        assert report.ready is True

    def test_dry_run_returns_ready_for_paper_mode(self) -> None:
        """Default config has allow_live_orders=False (paper mode).
        Dry-run readiness returns ready — paper mode is the expected default."""
        oms = MagicMock()
        hb = Heartbeat("svc")
        runner = LiveRunner(oms=oms, heartbeat=hb)
        report = runner.start(dry_run=True)
        assert report.status == "ready"

    def test_live_allow_live_orders_starts_paper_mode(self) -> None:
        oms = MagicMock()
        hb = Heartbeat("svc")
        cfg = LiveRunnerConfig(allow_live_orders=True)
        runner = LiveRunner(oms=oms, heartbeat=hb, config=cfg)
        runner._start_paper_mode = MagicMock()  # type: ignore[method-assign]
        report = runner.start(dry_run=False)
        runner._start_paper_mode.assert_called_once()
        assert report.status == "ready"


class TestLiveReadinessReport:
    """LiveReadinessReport helper property."""

    def test_ready_property_true(self) -> None:
        r = LiveReadinessReport(status="ready", checks={"a": True})
        assert r.ready is True

    def test_ready_property_false(self) -> None:
        r = LiveReadinessReport(status="blocked", checks={"a": False}, errors=["err"])
        assert r.ready is False


# ===========================================================================
# StateReconciler tests
# ===========================================================================


class TestStateReconcilerComparePositions:
    """StateReconciler.compare_positions() — pure logic, no I/O."""

    def test_matching_positions_pass(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100, 150.0), "MSFT": (50, 300.0)})
        broker = _pos({"AAPL": (100, 150.0), "MSFT": (50, 300.0)})
        assert r.compare_positions(local, broker) == []

    def test_quantity_mismatch_detected(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100, 150.0)})
        broker = _pos({"AAPL": (90, 150.0)})
        breaks = r.compare_positions(local, broker)
        assert len(breaks) == 1
        b = breaks[0]
        assert b.symbol == "AAPL"
        assert b.local_quantity == 100.0
        assert b.broker_quantity == 90.0

    def test_symbol_only_in_local(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100, 150.0)})
        broker: dict[str, Position] = {}
        breaks = r.compare_positions(local, broker)
        assert len(breaks) == 1
        assert breaks[0].local_quantity == 100.0
        assert breaks[0].broker_quantity == 0.0

    def test_symbol_only_in_broker(self) -> None:
        r = StateReconciler()
        local: dict[str, Position] = {}
        broker = _pos({"MSFT": (50, 300.0)})
        breaks = r.compare_positions(local, broker)
        assert len(breaks) == 1
        assert breaks[0].local_quantity == 0.0
        assert breaks[0].broker_quantity == 50.0

    def test_empty_both_sides(self) -> None:
        r = StateReconciler()
        assert r.compare_positions({}, {}) == []

    def test_tolerance_small_diff_pass(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100.0, 150.0)})
        broker = _pos({"AAPL": (100.000_001, 150.0)})
        assert r.compare_positions(local, broker, tolerance=1e-4) == []

    def test_tolerance_exceeded_detected(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100.0, 150.0)})
        broker = _pos({"AAPL": (100.1, 150.0)})
        breaks = r.compare_positions(local, broker, tolerance=1e-4)
        assert len(breaks) == 1

    def test_market_values_in_break(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100, 150.0)})
        broker = _pos({"AAPL": (90, 155.0)})
        breaks = r.compare_positions(local, broker)
        assert len(breaks) == 1
        b = breaks[0]
        assert b.local_market_value == 100 * 150.0
        assert b.broker_market_value == 90 * 155.0

    def test_multiple_symbols_mismatched(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100, 150.0), "MSFT": (50, 300.0), "GOOG": (200, 140.0)})
        broker = _pos({"AAPL": (100, 150.0), "MSFT": (55, 300.0), "GOOG": (200, 140.0)})
        breaks = r.compare_positions(local, broker)
        assert len(breaks) == 1  # only MSFT differs
        assert breaks[0].symbol == "MSFT"


class TestStateReconcilerReport:
    """StateReconciler.report() — wraps compare_positions into a dataclass."""

    def test_clean_report(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100, 150.0)})
        broker = _pos({"AAPL": (100, 150.0)})
        report = r.report(local, broker)
        assert isinstance(report, ReconciliationReport)
        assert report.is_clean is True
        assert report.status == "clean"
        assert report.break_count == 0
        assert report.breaks == []

    def test_breaks_report(self) -> None:
        r = StateReconciler()
        local = _pos({"AAPL": (100, 150.0)})
        broker = _pos({"AAPL": (90, 150.0)})
        report = r.report(local, broker)
        assert report.is_clean is False
        assert report.status == "breaks_detected"
        assert report.break_count == 1
        assert len(report.breaks) == 1

    def test_pass_through_tolerance(self) -> None:
        """Tolerance argument is forwarded to compare_positions."""
        r = StateReconciler()
        local = _pos({"AAPL": (100.0, 150.0)})
        broker = _pos({"AAPL": (100.000_001, 150.0)})
        report = r.report(local, broker, tolerance=1e-4)
        assert report.is_clean is True


# ===========================================================================
# ReconciliationService tests
# ===========================================================================


class TestReconciliationService:
    """ReconciliationService — end-to-end with temp ledger + mock broker."""

    def test_clean_reconciliation(self, tmp_path: Path) -> None:
        """Ledger fills match broker positions -> clean."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        _write_fill_jsonl(ld, [
            {
                "order_id": "o1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.0,
                "commission": 1.0,
                "filled_at": "2026-05-01T12:00:00+00:00",
                "fill_id": "f1",
            }
        ])
        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = _pos({"AAPL": (100, 150.0)})

        svc = ReconciliationService(ld, broker)
        result = svc.reconcile_positions()
        assert result["status"] == "clean"
        assert result["break_count"] == 0

    def test_dirty_reconciliation(self, tmp_path: Path) -> None:
        """Ledger quantity differs from broker -> breaks_detected."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        _write_fill_jsonl(ld, [
            {
                "order_id": "o1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.0,
                "commission": 1.0,
                "filled_at": "2026-05-01T12:00:00+00:00",
                "fill_id": "f1",
            }
        ])
        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = _pos({"AAPL": (90, 150.0)})

        svc = ReconciliationService(ld, broker)
        result = svc.reconcile_positions()
        assert result["status"] == "breaks_detected"
        assert result["break_count"] == 1
        assert len(result["breaks"]) == 1
        b = result["breaks"][0]
        assert b["symbol"] == "AAPL"
        assert b["local_quantity"] == 100.0
        assert b["broker_quantity"] == 90.0

    def test_empty_positions_both_sides(self, tmp_path: Path) -> None:
        """No fills, no broker positions -> clean."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = {}

        svc = ReconciliationService(ld, broker)
        result = svc.reconcile_positions()
        assert result["status"] == "clean"
        assert result["break_count"] == 0

    def test_broker_extra_position(self, tmp_path: Path) -> None:
        """Broker has a position not in the ledger -> break."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        _write_fill_jsonl(ld, [
            {
                "order_id": "o1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.0,
                "commission": 1.0,
                "filled_at": "2026-05-01T12:00:00+00:00",
                "fill_id": "f1",
            }
        ])
        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = _pos({
            "AAPL": (100, 150.0),
            "MSFT": (50, 300.0),
        })

        svc = ReconciliationService(ld, broker)
        result = svc.reconcile_positions()
        assert result["status"] == "breaks_detected"
        assert result["break_count"] == 1

    def test_ledger_extra_position(self, tmp_path: Path) -> None:
        """Ledger has a position not reflected at the broker -> break."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        _write_fill_jsonl(ld, [
            {
                "order_id": "o1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.0,
                "commission": 1.0,
                "filled_at": "2026-05-01T12:00:00+00:00",
                "fill_id": "f1",
            },
            {
                "order_id": "o2",
                "symbol": "MSFT",
                "side": "buy",
                "quantity": 50,
                "price": 300.0,
                "commission": 1.0,
                "filled_at": "2026-05-01T13:00:00+00:00",
                "fill_id": "f2",
            },
        ])
        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = _pos({"AAPL": (100, 150.0)})

        svc = ReconciliationService(ld, broker)
        result = svc.reconcile_positions()
        assert result["status"] == "breaks_detected"
        assert result["break_count"] == 1

    def test_multiple_breaks_in_one_reconciliation(self, tmp_path: Path) -> None:
        """Multiple position mismatches produce multiple breaks."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        _write_fill_jsonl(ld, [
            {
                "order_id": "o1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.0,
                "commission": 1.0,
                "filled_at": "2026-05-01T12:00:00+00:00",
                "fill_id": "f1",
            },
            {
                "order_id": "o2",
                "symbol": "MSFT",
                "side": "buy",
                "quantity": 50,
                "price": 300.0,
                "commission": 1.0,
                "filled_at": "2026-05-01T13:00:00+00:00",
                "fill_id": "f2",
            },
        ])
        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = _pos({
            "AAPL": (99, 150.0),
            "MSFT": (51, 300.0),
        })

        svc = ReconciliationService(ld, broker)
        result = svc.reconcile_positions()
        assert result["status"] == "breaks_detected"
        assert result["break_count"] == 2


# ===========================================================================
# Mock broker / strategy integration behaviour
# ===========================================================================


class TestPaperBrokerIntegration:
    """LiveRunner + mock (paper) broker — no real connection needed."""

    def test_runner_with_mock_broker_and_clean_recon(self, tmp_path: Path) -> None:
        """Wire a mock broker giving positions that match the ledger -> ready."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        _write_fill_jsonl(ld, [
            {
                "order_id": "o1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 10,
                "price": 200.0,
                "commission": 0.5,
                "filled_at": "2026-05-02T10:00:00+00:00",
                "fill_id": "f1",
            }
        ])

        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = _pos({"AAPL": (10, 200.0)})

        recon = ReconciliationService(ld, broker)
        oms = MagicMock()
        oms.broker = broker
        hb = Heartbeat("paper_test")
        cfg = LiveRunnerConfig(allow_live_orders=True, require_reconciliation_clean=True)
        runner = LiveRunner(oms=oms, heartbeat=hb, reconciliation=recon, config=cfg)

        # Run dry -> should report ready
        report = runner.start(dry_run=True)
        assert report.ready is True, f"Expected ready, got {report.status}: {report.errors}"

    def test_runner_with_mock_broker_and_dirty_recon(self, tmp_path: Path) -> None:
        """Ledger mismatch with broker blocks readiness."""
        ld = tmp_path / "ledger"
        ld.mkdir()
        _write_fill_jsonl(ld, [
            {
                "order_id": "o1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 10,
                "price": 200.0,
                "commission": 0.5,
                "filled_at": "2026-05-02T10:00:00+00:00",
                "fill_id": "f1",
            }
        ])

        broker = MagicMock(spec=BrokerBase)
        broker.get_positions.return_value = _pos({"AAPL": (9, 200.0)})

        recon = ReconciliationService(ld, broker)
        oms = MagicMock()
        oms.broker = broker
        hb = Heartbeat("paper_test")
        cfg = LiveRunnerConfig(allow_live_orders=True, require_reconciliation_clean=True)
        runner = LiveRunner(oms=oms, heartbeat=hb, reconciliation=recon, config=cfg)

        report = runner.start(dry_run=True)
        assert report.ready is False
        assert "reconciliation_breaks_detected" in report.errors
