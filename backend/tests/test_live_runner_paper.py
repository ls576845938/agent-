"""Tests for LiveRunner paper-mode state machine.

Covers:
  - Paper mode starts without error (mocked)
  - Live mode still raises NotImplementedError
  - State transitions: BOOTSTRAPPING -> READY -> RUNNING
  - Shutdown transitions to SHUTTING_DOWN
  - Error during cycle transitions to ERROR
  - Reconcile on start blocks if breaks
  - Market data failure triggers reduce_only
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from quant_us.live.runner import (
    LiveReadinessReport,
    LiveRunner,
    LiveRunnerConfig,
    LiveRunnerState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CleanReconReport:
    """Mock ReconciliationReport with clean status."""

    status = "clean"
    cash_diff = 0.0
    position_diffs: dict = {}
    order_diffs: dict = {}
    fill_diffs: dict = {}
    halt_new_orders = False
    alert_sent = False
    report_path = ""


class _BrokenReconReport:
    """Mock ReconciliationReport with breaks."""

    status = "breaks_detected"
    cash_diff = 100.0
    position_diffs: dict = {"AAPL": {"quantity_diff": 10}}
    order_diffs: dict = {}
    fill_diffs: dict = {}
    halt_new_orders = True
    alert_sent = False
    report_path = ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_oms():
    oms = MagicMock()
    oms.reduce_only = False
    oms.load_idempotency.return_value = 0
    oms.broker.get_account.return_value = MagicMock(
        equity=100000.0,
        cash=100000.0,
        positions={},
        buying_power=200000.0,
    )
    oms.broker.get_orders.return_value = []
    oms.broker.get_fills.return_value = []
    return oms


@pytest.fixture
def mock_heartbeat():
    hb = MagicMock()
    hb.beat.return_value = MagicMock()
    return hb


@pytest.fixture
def mock_reconciliation():
    rec = MagicMock()
    # reconcile_positions() returns a dict (legacy API)
    rec.reconcile_positions.return_value = {
        "status": "clean",
        "break_count": 0,
        "breaks": [],
    }
    # reconcile_all() returns a ReconciliationReport object
    rec.reconcile_all.return_value = _CleanReconReport()
    return rec


@pytest.fixture
def mock_kill_switch():
    ks = MagicMock()
    ks.triggered = False
    ks.reason = ""
    return ks


@pytest.fixture
def paper_config():
    return LiveRunnerConfig(
        require_reconciliation_clean=True,
        allow_live_orders=False,
        market_data_symbols=["AAPL", "SPY"],
        market_data_vendor="yfinance",
        market_data_bar_size="1m",
        market_data_poll_interval=60.0,
        market_data_root="/tmp/test_runner_data",
        state_path="/tmp/test_runner_state.json",
    )


@pytest.fixture
def runner(
    mock_oms,
    mock_heartbeat,
    mock_reconciliation,
    mock_kill_switch,
    paper_config,
):
    """Build a LiveRunner with all mocks wired in.

    Caller must patch ``threading.Thread`` to avoid real concurrency.
    """
    return LiveRunner(
        oms=mock_oms,
        heartbeat=mock_heartbeat,
        reconciliation=mock_reconciliation,
        kill_switch=mock_kill_switch,
        config=paper_config,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLiveRunnerPaper:
    """LiveRunner paper-mode state machine tests."""

    # ── test 1: paper mode starts without error ───────────────────────

    @patch("quant_us.live.runner.threading.Thread")
    def test_paper_mode_starts_without_error(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """Paper mode succeeds and returns a ready report."""
        report = runner.start(dry_run=False)
        assert report.ready, f"Expected ready report, got {report}"
        assert runner.state == LiveRunnerState.RUNNING, (
            f"Expected RUNNING, got {runner.state}"
        )

    # ── test 2: live mode raises NotImplementedError ──────────────────

    @patch("quant_us.live.runner.threading.Thread")
    def test_live_mode_raises_not_implemented(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """allow_live_orders=True must raise."""
        runner.config.allow_live_orders = True
        with pytest.raises(NotImplementedError) as exc:
            runner.start(dry_run=False)
        assert "deferred" in str(exc.value).lower()

    # ── test 3: state transitions ────────────────────────────────────

    @patch("quant_us.live.runner.threading.Thread")
    def test_state_transitions(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """BOOTSTRAPPING -> READY -> RUNNING after start()."""
        # Before start
        assert runner.state == LiveRunnerState.BOOTSTRAPPING

        # After start (paper mode)
        runner.start(dry_run=False)

        # The synchronous part of _start_paper_mode should have moved
        # through READY to RUNNING.
        assert runner.state == LiveRunnerState.RUNNING, (
            f"Expected RUNNING, got {runner.state}"
        )

    # ── test 4: shutdown transition ──────────────────────────────────

    @patch("quant_us.live.runner.threading.Thread")
    def test_shutdown_transition(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """stop() sets state to SHUTTING_DOWN."""
        runner.start(dry_run=False)
        assert runner.state == LiveRunnerState.RUNNING

        runner.stop()
        assert runner.state == LiveRunnerState.SHUTTING_DOWN, (
            f"Expected SHUTTING_DOWN, got {runner.state}"
        )

    # ── test 5: error during cycle → ERROR ───────────────────────────

    @patch("quant_us.live.runner.threading.Thread")
    def test_error_during_cycle(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """Exception inside _run_strategy_cycle sets state to ERROR."""
        runner.start(dry_run=False)
        assert runner.state == LiveRunnerState.RUNNING

        # Make session_clock.should_shutdown raise => exception inside
        # _run_strategy_cycle.
        with patch.object(
            runner._session_clock, "should_shutdown",
            side_effect=RuntimeError("market-data failure"),
        ):
            runner._run_strategy_cycle()

        assert runner.state == LiveRunnerState.ERROR, (
            f"Expected ERROR, got {runner.state}"
        )

    # ── test 6: reconcile on start blocks if breaks ──────────────────

    def test_reconcile_on_start_blocks(
        self, runner: LiveRunner,
    ) -> None:
        """Reconciliation breaks during bootstrap block the start."""
        # Mock reconciliation to return breaks for reconcile_positions
        runner.reconciliation.reconcile_positions.return_value = {
            "status": "breaks_detected",
            "break_count": 3,
            "breaks": [
                {
                    "symbol": "AAPL",
                    "local_quantity": 100.0,
                    "broker_quantity": 90.0,
                },
            ],
        }

        # Method 1: start() catches via check_readiness
        report = runner.start(dry_run=False)
        assert not report.ready
        assert "reconciliation_breaks_detected" in report.errors

        # Method 2: direct bootstrap call also fails
        # Reset and call bootstrap directly
        runner_bootstrap_only = LiveRunner(
            oms=runner.oms,
            heartbeat=runner.heartbeat,
            reconciliation=runner.reconciliation,
            kill_switch=runner.kill_switch,
            config=runner.config,
        )
        runner_bootstrap_only.reconciliation.reconcile_positions.return_value = {
            "status": "breaks_detected",
            "break_count": 3,
            "breaks": [],
        }
        assert not runner_bootstrap_only.bootstrap()
        # bootstrap() returns False without setting ERROR — that's the
        # caller's job (_start_paper_mode sets ERROR when bootstrap fails).
        assert runner_bootstrap_only.state == LiveRunnerState.BOOTSTRAPPING

    # ── test 7: market data failure triggers reduce_only ────────────

    @patch("quant_us.live.runner.threading.Thread")
    def test_market_data_failure_triggers_reduce_only(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """MarketDataLoop exception sets OMS.reduce_only = True."""
        # Start paper mode first
        runner.start(dry_run=False)
        assert runner.state == LiveRunnerState.RUNNING
        assert not runner.oms.reduce_only, (
            "reduce_only should start False"
        )

        # Simulate market data loop failure in _fetch_and_check_market_data
        with patch.object(
            runner._market_data_loop,
            "fetch_latest_bars",
            side_effect=RuntimeError("API timeout"),
        ):
            runner._fetch_and_check_market_data()

        assert runner.oms.reduce_only, (
            "reduce_only should be True after market data failure"
        )

    # ------------------------------------------------------------------
    # Additional edge cases
    # ------------------------------------------------------------------

    @patch("quant_us.live.runner.threading.Thread")
    def test_dry_run_returns_without_starting_paper_mode(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """dry_run=True never transitions past READY check."""
        report = runner.start(dry_run=True)
        assert report.ready
        # State should still be initial (not touched by paper mode)
        assert runner.state == LiveRunnerState.BOOTSTRAPPING

    @patch("quant_us.live.runner.threading.Thread")
    def test_shutdown_safely_idempotent(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """Calling shutdown_safely() twice is safe."""
        runner.start(dry_run=False)
        runner.shutdown_safely()
        first_state = runner.state
        runner.shutdown_safely()  # second call — no-op
        assert runner.state == first_state

    @patch("quant_us.live.runner.threading.Thread")
    def test_reconcile_during_running_sets_reconciling_state(
        self, mock_thread: MagicMock, runner: LiveRunner,
    ) -> None:
        """reconcile() sets state to RECONCILING temporarily."""
        runner.start(dry_run=False)
        runner.reconcile()
        # After reconcile completes, state returns to RUNNING
        assert runner.state == LiveRunnerState.RUNNING

    def test_check_readiness_kill_switch_blocks(
        self, runner: LiveRunner,
    ) -> None:
        """Kill-switch triggered blocks readiness."""
        runner.kill_switch.triggered = True
        runner.kill_switch.reason = "max_daily_loss"
        report = runner.check_readiness()
        assert not report.ready
        assert any("kill_switch" in e for e in report.errors)

    def test_start_returns_blocked_when_not_ready(
        self, runner: LiveRunner,
    ) -> None:
        """start() returns blocked report when readiness fails."""
        runner.kill_switch.triggered = True
        report = runner.start(dry_run=False)
        assert not report.ready
        # State stays initial because _start_paper_mode is never called
        assert runner.state == LiveRunnerState.BOOTSTRAPPING
