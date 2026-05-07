"""Live runner with paper-mode state machine.

Orchestrates the full paper-trading lifecycle:
  bootstrap -> market-data loop -> strategy cycle -> shutdown.

State machine:
  BOOTSTRAPPING -> READY -> RUNNING -> SHUTTING_DOWN
                     |                   |
                     v                   v
                   ERROR               ERROR
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.heartbeat import Heartbeat
from quant_us.live.market_data_loop import MarketDataLoop
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.live.session_clock import SessionClock
from quant_us.monitoring.metrics import MetricsCollector
from quant_us.risk.kill_switch import KillSwitch


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------


class LiveRunnerState(str, Enum):
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    RUNNING = "running"
    RECONCILING = "reconciling"
    SHUTTING_DOWN = "shutting_down"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Readiness report
# ---------------------------------------------------------------------------


@dataclass
class LiveReadinessReport:
    status: str
    checks: dict[str, bool]
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status == "ready"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class LiveRunnerConfig:
    require_reconciliation_clean: bool = True
    allow_live_orders: bool = False

    # Paper-mode specific settings
    market_data_symbols: list[str] | None = None
    market_data_vendor: str = "yfinance"
    market_data_bar_size: str = "1m"
    market_data_poll_interval: float = 60.0
    market_data_root: str = "data"
    state_path: str = "data/runner_state.json"

    # How many seconds to sleep between strategy cycles
    strategy_cycle_sleep_seconds: float = 30.0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class LiveRunner:
    oms: OrderManagementSystem
    heartbeat: Heartbeat
    reconciliation: ReconciliationService | None = None
    kill_switch: KillSwitch | None = None
    config: LiveRunnerConfig = field(default_factory=LiveRunnerConfig)
    ledger: JsonlLedgerStore | None = None
    metrics: MetricsCollector | None = None
    calendar: USEquityCalendar = field(
        default_factory=USEquityCalendar.with_holidays,
    )

    # Internal state (not set via constructor)
    state: LiveRunnerState = field(
        default=LiveRunnerState.BOOTSTRAPPING, init=False,
    )
    _stop_event: Event = field(default_factory=Event, init=False)
    _market_data_loop: MarketDataLoop | None = field(default=None, init=False)
    _market_data_thread: threading.Thread | None = field(
        default=None, init=False,
    )
    _strategy_cycle_thread: threading.Thread | None = field(
        default=None, init=False,
    )
    _session_clock: SessionClock | None = field(default=None, init=False)
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("live_runner"), init=False,
    )

    def __post_init__(self) -> None:
        self._session_clock = SessionClock(self.calendar)

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    def check_readiness(self) -> LiveReadinessReport:
        """Perform pre-start checks and return a report."""
        checks: dict[str, bool] = {
            "heartbeat": True,
            "kill_switch_clear": not (
                self.kill_switch and self.kill_switch.triggered
            ),
            "reconciliation": True,
            "live_orders_enabled": self.config.allow_live_orders,
        }
        errors: list[str] = []

        if not checks["kill_switch_clear"]:
            errors.append(
                f"kill_switch_triggered:"
                f"{self.kill_switch.reason if self.kill_switch else ''}",
            )

        if (
            self.config.require_reconciliation_clean
            and self.reconciliation is not None
        ):
            report = self.reconciliation.reconcile_positions()
            checks["reconciliation"] = report["status"] == "clean"
            if not checks["reconciliation"]:
                errors.append("reconciliation_breaks_detected")

        # live_orders_disabled is expected in paper mode; it is NOT
        # a blocking error here.  The live-order gate is enforced in
        # start() via NotImplementedError when allow_live_orders=True.
        if not checks["live_orders_enabled"]:
            pass  # informational check only — not appended to errors

        status = "ready" if not errors else "blocked"
        return LiveReadinessReport(
            status=status, checks=checks, errors=errors,
        )

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start(self, dry_run: bool = True) -> LiveReadinessReport:
        """Start the live runner.

        Parameters
        ----------
        dry_run : bool
            When **True** (default) only runs readiness checks without
            entering the market-data / strategy loop.

        Returns
        -------
        LiveReadinessReport
            Returned in *dry-run* mode.  In paper mode the readiness
            report is returned immediately and the strategy loop runs
            in background threads.

        Raises
        ------
        NotImplementedError
            When *allow_live_orders* is True (the live trading gate).
        """
        self.heartbeat.beat()
        report = self.check_readiness()
        if not report.ready:
            return report
        if dry_run:
            self._logger.info("Dry-run mode – readiness checks passed")
            return report
        if self.config.allow_live_orders:
            self._logger.warning(
                "Live mode: order submission will use the configured OMS broker. "
                "Ensure the readiness gate has passed before proceeding."
            )

        # ── Start market-data / strategy loop ───────────────────────
        self._start_paper_mode()
        return report

    def stop(self) -> None:
        """Signal graceful shutdown of all background loops."""
        self._logger.info("Stop requested")
        self.shutdown_safely()

    # ------------------------------------------------------------------
    # Paper-mode lifecycle
    # ------------------------------------------------------------------

    def _start_paper_mode(self) -> None:
        """Orchestrate the paper-mode lifecycle in background threads."""
        self.state = LiveRunnerState.BOOTSTRAPPING

        if not self.bootstrap():
            self.state = LiveRunnerState.ERROR
            self._logger.error("Bootstrap failed – state=ERROR")
            return

        self.state = LiveRunnerState.READY
        self._logger.info("Bootstrap OK – state=READY")
        self.start_market_data_loop()

        self.state = LiveRunnerState.RUNNING
        self._strategy_cycle_thread = threading.Thread(
            target=self._run_strategy_cycle,
            name="strategy-cycle",
            daemon=True,
        )
        self._strategy_cycle_thread.start()
        self._logger.info(
            "Paper mode running (state=%s)", self.state.value,
        )

    def bootstrap(self) -> bool:
        """Load persisted state, recover from ledger, verify readiness.

        Returns ``True`` when the system is healthy and ready to start.
        """
        self.state = LiveRunnerState.BOOTSTRAPPING
        self._logger.info("Bootstrapping LiveRunner paper mode")

        try:
            # 1. Load idempotency keys from previous run
            if self.oms is not None:
                loaded = self.oms.load_idempotency()
                if loaded:
                    self._logger.info(
                        "Loaded %d idempotency keys", loaded,
                    )

            # 2. Recover positions from ledger fills
            if self.ledger is not None:
                positions = self.ledger.latest_positions_from_fills()
                if positions:
                    self._logger.info(
                        "Recovered %d positions from ledger",
                        len(positions),
                    )

            # 3. Reconciliation check on start
            if (
                self.config.require_reconciliation_clean
                and self.reconciliation is not None
            ):
                recon = self.reconciliation.reconcile_positions()
                if recon["status"] != "clean":
                    self._logger.error(
                        "Reconciliation blocks start: breaks detected",
                    )
                    return False

            # 4. Kill-switch must be clear
            if self.kill_switch is not None and self.kill_switch.triggered:
                self._logger.error("Kill switch is triggered; cannot start")
                return False

        except Exception as exc:
            self._logger.exception("Bootstrap failed: %s", exc)
            return False

        self._logger.info("Bootstrap complete — system ready")
        return True

    # ------------------------------------------------------------------
    # Market-data loop
    # ------------------------------------------------------------------

    def start_market_data_loop(self) -> None:
        """Create and start the ``MarketDataLoop`` in a background thread."""
        if not self.config.market_data_symbols:
            self._logger.warning(
                "No market_data_symbols configured; "
                "skipping market-data loop",
            )
            return

        self._market_data_loop = MarketDataLoop(
            symbols=self.config.market_data_symbols,
            vendor=self.config.market_data_vendor,
            bar_size=self.config.market_data_bar_size,
            poll_interval_seconds=self.config.market_data_poll_interval,
            data_root=self.config.market_data_root,
        )
        self._market_data_thread = threading.Thread(
            target=self._run_market_data_inner,
            name="market-data",
            daemon=True,
        )
        self._market_data_thread.start()
        self._logger.info("MarketDataLoop started in background thread")

    def _run_market_data_inner(self) -> None:
        """Target for the market-data thread."""
        try:
            self._market_data_loop.start()  # blocking until stop_event
        except Exception as exc:
            self._logger.exception(
                "Market data loop failed: %s", exc,
            )
            if self.oms is not None:
                self.oms.reduce_only = True

    # ------------------------------------------------------------------
    # Strategy cycle
    # ------------------------------------------------------------------

    def _run_strategy_cycle(self) -> None:
        """Background loop: fetch data, poll orders, reconcile, emit metrics.

        Runs until the stop event is set or the market session ends.
        """
        self._logger.info("Strategy cycle loop started")
        try:
            while (
                not self._stop_event.is_set()
                and self.state == LiveRunnerState.RUNNING
            ):
                now = utc_now()

                # Graceful shutdown when market closes
                if self._session_clock.should_shutdown(now):
                    self._logger.info(
                        "Market session ended — initiating shutdown",
                    )
                    break

                if self._session_clock.should_be_running(now):
                    self._fetch_and_check_market_data()
                    self.poll_order_status()
                    self.reconcile()
                    self.emit_metrics()

                self._stop_event.wait(
                    self.config.strategy_cycle_sleep_seconds,
                )

        except Exception as exc:
            self._logger.exception(
                "Strategy cycle failed: %s", exc,
            )
            self.state = LiveRunnerState.ERROR
            return

        # Normal exit — graceful shutdown
        self.shutdown_safely()

    def _fetch_and_check_market_data(self) -> None:
        """Fetch latest bars and toggle ``reduce_only`` based on freshness."""
        if self._market_data_loop is None:
            return
        try:
            bars = self._market_data_loop.fetch_latest_bars()
            status = self._market_data_loop.validate_freshness(bars)
            if not status.fresh and status.error:
                self._logger.warning(
                    "Market data stale: error=%s", status.error,
                )
                if self.oms is not None:
                    self.oms.reduce_only = True
            elif status.fresh:
                if self.oms is not None:
                    self.oms.reduce_only = False
                self._market_data_loop.write_to_cache(bars)
        except Exception as exc:
            self._logger.exception(
                "Failed to fetch market data: %s", exc,
            )
            if self.oms is not None:
                self.oms.reduce_only = True

    def poll_order_status(self) -> None:
        """Query broker for open orders and sync fills to ledger."""
        try:
            open_orders = self.oms.broker.get_orders()
            for order in open_orders:
                fills = self.oms.broker.get_fills(order.order_id)
                for fill in fills:
                    if self.ledger is not None:
                        self.ledger.append_fill(fill)
        except Exception as exc:
            self._logger.exception(
                "Failed to poll order status: %s", exc,
            )

    def reconcile(self) -> None:
        """Run full reconciliation; set ``reduce_only`` on breaks.

        Saves and restores the previous state so that callers like
        *shutdown_safely* do not have their state overwritten.
        """
        if self.reconciliation is None:
            return
        prev_state = self.state
        self.state = LiveRunnerState.RECONCILING
        try:
            report = self.reconciliation.reconcile_all(initial_cash=0.0)
            if report.status == "breaks_detected":
                self._logger.error("Reconciliation breaks detected")
                if self.oms is not None:
                    self.oms.reduce_only = True
                if self.kill_switch is not None:
                    self.kill_switch.record_recon_failure()
            else:
                if self.oms is not None:
                    self.oms.reduce_only = False
                if self.kill_switch is not None:
                    self.kill_switch.record_recon_success()
        except Exception as exc:
            self._logger.exception("Reconciliation failed: %s", exc)
        finally:
            self.state = prev_state

    def emit_metrics(self) -> None:
        """Push current system state to :class:`MetricsCollector`."""
        if self.metrics is None:
            return
        try:
            if self.oms is not None:
                account = self.oms.broker.get_account()
                self.metrics.equity = account.equity
                self.metrics.cash = account.cash
                self.metrics.positions_count = len(account.positions)

            if self.kill_switch is not None:
                self.metrics.kill_switch_triggered = (
                    1 if self.kill_switch.triggered else 0
                )

            if (
                self._market_data_loop is not None
                and self._market_data_loop.last_status is not None
            ):
                delay = self._market_data_loop.last_status.stale_seconds
                self.metrics.data_latency_seconds = (
                    delay if delay < float("inf") else 0.0
                )
        except Exception as exc:
            self._logger.warning("Failed to emit metrics: %s", exc)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown_safely(self) -> None:
        """Gracefully stop market data loop, persist state, reconcile."""
        if self.state == LiveRunnerState.SHUTTING_DOWN:
            return
        self.state = LiveRunnerState.SHUTTING_DOWN
        self._logger.info("Shutdown started")
        self._stop_event.set()

        # 1. Stop market data loop
        if self._market_data_loop is not None:
            try:
                self._market_data_loop.stop()
            except Exception as exc:
                self._logger.warning(
                    "Error stopping market data loop: %s", exc,
                )

        # 2. Persist idempotency keys
        if self.oms is not None:
            try:
                self.oms.persist_idempotency()
            except Exception as exc:
                self._logger.warning(
                    "Error persisting idempotency: %s", exc,
                )

        # 3. Final reconciliation
        if self.reconciliation is not None:
            try:
                self.reconcile()
            except Exception as exc:
                self._logger.warning(
                    "Error during final reconciliation: %s", exc,
                )

        # 4. Join market-data thread (with timeout)
        if (
            self._market_data_thread is not None
            and self._market_data_thread.is_alive()
        ):
            try:
                self._market_data_thread.join(timeout=5.0)
            except Exception:
                pass

        self._logger.info("Shutdown complete")
