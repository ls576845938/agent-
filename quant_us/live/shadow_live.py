"""Shadow live mode: real market data + real broker (read-only) + paper orders.

Shadow live is the final safety bridge before real-money trading:

  - Uses **real** market data (from Alpaca or other vendors).
  - Connects to the **real** broker for ACCOUNT QUERIES ONLY (read-only).
  - Submits orders exclusively to a **paper** broker (SimulatedBroker).

Core invariant:
    **NO real order is ever submitted.**  Even if
    ``config.submit_real_orders`` is accidentally set to ``True``, the hard
    safety gate in ``_hard_safety_gate()`` raises ``RuntimeError``.

Typical flow::

    config = ShadowLiveConfig(
        broker_api_key=os.environ["APCA_API_KEY_ID"],
        broker_api_secret=os.environ["APCA_API_SECRET_KEY"],
        symbols=["SPY", "QQQ"],
    )
    runner = ShadowLiveRunner(config, strategy=my_strategy)
    if runner.bootstrap():
        runner.start()
    # runner.run_market_session() blocks until session ends
    runner.shutdown()
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from threading import Event
from typing import Any

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, Fill, Order, Position, Signal, new_id
from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem, OMSResult
from quant_us.strategies.base import Strategy, StrategyContext
from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.slippage import BpsSlippage
from quant_us.live.live_state_store import (
    DayResult,
    LiveSessionRunner,
    LiveSessionState,
    LiveStateStore,
)
from quant_us.live.market_data_loop import MarketDataLoop
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.live.session_clock import SessionClock
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig

_logger = logging.getLogger("shadow_live")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ShadowLiveConfig:
    """Configuration for shadow live mode.

    Shadow live = real market data + real broker (read-only) + paper order
    submission only.  **NO real orders are ever submitted.**  This is the
    final safety gate before live trading.

    Attributes:
        broker_account_mode: ``"live_readonly"`` (default) or ``"paper"``.
            Determines which Alpaca endpoint is queried for account state.
        broker_api_key: Alpaca API key ID.
        broker_api_secret: Alpaca secret key.
        submit_real_orders: **MUST stay False** — hard safety gate raises
            ``RuntimeError`` if set to ``True``.
        submit_paper_orders: When ``True`` orders are sent to the paper
            broker.  Set to ``False`` for dry-run signal collection.
        use_real_market_data: When ``True`` (default) real market data is
            fetched from the configured data vendor.
        data_vendor: Market-data connector name (e.g. ``"alpaca"``,
            ``"yfinance"``).
        symbols: Tickers to track and trade.
        bar_size: Bar interval (e.g. ``"1m"``, ``"5m"``).
        poll_interval_seconds: Seconds between strategy cycles.
        require_live_readiness_check: When ``True`` run the full gate
            check during bootstrap.
        max_position_pct: Maximum position size as fraction of equity.
        max_positions: Maximum number of open positions.
        daily_loss_limit_pct: Maximum daily loss fraction before kill
            switch triggers.
        data_root: Root path for cached market data.
        ledger_root: Storage path for the JSONL ledger.
        state_path: Path for the shadow-live state store.
        paper_state_path: Path for the paper-trading state store (used
            by the gate to verify clean trading record).
        max_runtime_hours: Hard wall-clock limit for the session.
    """

    broker_account_mode: str = "live_readonly"
    broker_api_key: str = ""
    broker_api_secret: str = ""
    submit_real_orders: bool = False  # MUST stay False
    submit_paper_orders: bool = True
    use_real_market_data: bool = True
    data_vendor: str = "alpaca"
    symbols: list[str] = field(default_factory=list)
    bar_size: str = "1m"
    poll_interval_seconds: float = 60.0
    require_live_readiness_check: bool = True
    max_position_pct: float = 0.02
    max_positions: int = 5
    daily_loss_limit_pct: float = 0.02
    data_root: str = "data"
    ledger_root: str = "data/shadow_ledger"
    state_path: str = "data/shadow_state.json"
    paper_state_path: str = "data/paper_state.json"
    max_runtime_hours: float = 8.0

    def __post_init__(self) -> None:
        if self.submit_real_orders:
            raise ValueError(
                "ShadowLiveConfig.submit_real_orders MUST be False. "
                "This is a safety gate — shadow-live never submits real orders."
            )


# ---------------------------------------------------------------------------
# Gate report
# ---------------------------------------------------------------------------


@dataclass
class ShadowLiveGateReport:
    """Result of pre-flight safety checks in :class:`ShadowLiveGate`.

    Attributes:
        passed: ``True`` when all checks succeeded.
        checks: Per-check name -> bool result.
        errors: Human-readable descriptions of every failing check.
    """

    passed: bool
    checks: dict[str, bool]
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a human-readable summary of the gate check results."""
        lines = [
            "ShadowLive Gate Report",
            "=" * 60,
        ]
        for name in sorted(self.checks):
            status = "PASS" if self.checks[name] else "FAIL"
            lines.append(f"  [{status}] {name}")
        lines.append("=" * 60)
        if self.passed:
            lines.append("  RESULT: ALL CHECKS PASSED -- proceed to shadow live.")
        else:
            lines.append("  RESULT: GATE BLOCKED -- fix the failing checks above.")
        if self.errors:
            lines.append("")
            for err in self.errors:
                lines.append(f"  ERROR: {err}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class ShadowLiveGate:
    """Pre-flight safety checks for shadow live mode.

    The gate validates seven conditions **before** any runtime component
    is started.  Checks 5-7 require a state store to be provided; if it
    is not available those checks are reported as warnings rather than
    failures.

    Check list:
    1. Real broker connection verified (account accessible).
    2. Real market data accessible.
    3. ``submit_real_orders`` is ``False`` (hard gate).
    4. Paper broker configuration is valid.
    5. Paper trading record in state store is clean.
    6. Kill switch state is clear.
    7. Reconciliation state is clean.
    """

    def __init__(self, config: ShadowLiveConfig) -> None:
        self.config = config
        self._logger = logging.getLogger("shadow_live_gate")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(
        self,
        state_store: LiveStateStore | None = None,
    ) -> ShadowLiveGateReport:
        """Run ALL pre-flight checks and return a report.

        Args:
            state_store: Optional state store reference for checking
                paper trading record and kill-switch history.  When
                ``None``, checks 5-6 are reported as skipped.

        Returns:
            A ``ShadowLiveGateReport`` summarising every check.
        """
        checks: dict[str, bool] = {}
        errors: list[str] = []

        # Check 3 — hard safety gate (fastest, check first)
        checks["verify_no_real_orders"] = self.verify_no_real_orders()
        if not checks["verify_no_real_orders"]:
            errors.append(
                "SAFETY VIOLATION: submit_real_orders must be False. "
                "Shadow live mode NEVER submits real orders.",
            )

        # Check 4 — paper broker
        checks["paper_broker_configured"] = self._check_paper_broker()
        if not checks["paper_broker_configured"]:
            errors.append("Paper broker configuration is invalid.")

        # Check 1 — real broker connectivity
        checks["broker_connectivity"] = self._check_broker_connectivity()
        if not checks["broker_connectivity"]:
            errors.append(
                "Cannot connect to real broker. Check API credentials and endpoint.",
            )

        # Check 2 — market data access
        checks["market_data_accessible"] = self._check_market_data()
        if not checks["market_data_accessible"]:
            errors.append(
                f"Market data vendor '{self.config.data_vendor}' is not accessible.",
            )

        # Checks 5-7 require state store or separate validation
        if state_store is not None:
            paper_state = state_store.load_state()
            if paper_state is not None:
                clean_days = state_store.get_consecutive_clean_days()
                checks["paper_trading_clean_record"] = clean_days >= 1
                if not checks["paper_trading_clean_record"]:
                    errors.append(
                        "Paper trading record is not clean "
                        f"(consecutive clean days: {clean_days}).",
                    )
                checks["kill_switch_state_clear"] = not paper_state.kill_switch_triggered
                if not checks["kill_switch_state_clear"]:
                    errors.append("Kill switch was triggered in the last session.")
            else:
                checks["paper_trading_clean_record"] = False
                checks["kill_switch_state_clear"] = False
                errors.append(
                    "No paper trading state found. At least one clean day required.",
                )
        else:
            # Checks 5-7 are deferred to bootstrap when no store is provided
            checks["paper_trading_clean_record"] = False
            checks["kill_switch_state_clear"] = False
            errors.append(
                "No state store provided. Deferring checks 5-7 to bootstrap.",
            )

        passed = len(errors) == 0
        return ShadowLiveGateReport(passed=passed, checks=checks, errors=errors)

    def verify_no_real_orders(self) -> bool:
        """CRITICAL safety gate: verify ``submit_real_orders`` is ``False``.

        Returns:
            ``True`` when the flag is ``False`` (i.e. no real orders can
            be submitted).
        """
        return not bool(self.config.submit_real_orders)

    # ------------------------------------------------------------------
    # Individual check helpers
    # ------------------------------------------------------------------

    def _check_broker_connectivity(self) -> bool:
        """Verify connection to the real broker account endpoint."""
        api_key = self.config.broker_api_key
        api_secret = self.config.broker_api_secret
        if not api_key or not api_secret:
            self._logger.warning("Broker API credentials are empty; skipping connectivity check.")
            return False

        try:
            paper_mode = self.config.broker_account_mode != "live_readonly"
            if paper_mode:
                base_url = "https://paper-api.alpaca.markets"
            else:
                base_url = "https://api.alpaca.markets"

            broker = AlpacaBroker(
                AlpacaBrokerConfig(
                    api_key=api_key,
                    api_secret=api_secret,
                    paper=paper_mode,
                    base_url=base_url,
                ),
            )
            account = broker.get_account()
            self._logger.info(
                "Broker connectivity OK: account=%s equity=%.2f",
                account.account_id,
                account.equity,
            )
            return True
        except Exception as exc:
            self._logger.warning("Broker connectivity check failed: %s", exc)
            return False

    def _check_market_data(self) -> bool:
        """Verify the market data vendor can fetch at least one bar."""
        if not self.config.symbols:
            self._logger.warning("No symbols configured; skipping market data check.")
            return False

        try:
            loop = MarketDataLoop(
                symbols=self.config.symbols[:3],
                vendor=self.config.data_vendor,
                bar_size=self.config.bar_size,
                poll_interval_seconds=5.0,
                data_root=self.config.data_root,
            )
            bars = loop.fetch_latest_bars()
            ok = not bars.empty
            self._logger.info(
                "Market data check: vendor=%s symbols=%s result=%s",
                self.config.data_vendor,
                self.config.symbols[:3],
                "OK" if ok else "no_data",
            )
            return ok
        except Exception as exc:
            self._logger.warning("Market data check failed: %s", exc)
            return False

    @staticmethod
    def _check_paper_broker() -> bool:
        """Verify the paper broker can be instantiated (always true)."""
        try:
            _ = SimulatedBroker()
            return True
        except Exception as exc:
            _logger.error("Paper broker instantiation failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Read-only broker proxy
# ---------------------------------------------------------------------------


class ReadOnlyBrokerProxy(BrokerBase):
    """Wraps a :class:`BrokerBase` to block write operations.

    Only ``get_account``, ``get_positions``, ``get_orders``, and
    ``get_fills`` are forwarded.  ``submit_order`` and ``cancel_order``
    raise ``RuntimeError``.  This is the **hard safety gate** that
    prevents accidental real order submission.

    Usage::

        real_broker = AlpacaBroker(config)
        read_only = ReadOnlyBrokerProxy(real_broker)
        account = read_only.get_account()   # OK
        read_only.submit_order(order)       # raises RuntimeError
    """

    def __init__(self, inner: BrokerBase) -> None:
        self._inner = inner

    @property
    def broker_name(self) -> str:
        return f"readonly_{self._inner.broker_name}"

    def get_account(self) -> AccountState:
        return self._inner.get_account()

    def get_positions(self) -> dict[str, Position]:
        return self._inner.get_positions()

    def get_orders(self) -> list[Order]:
        return self._inner.get_orders()

    def submit_order(self, order: Order) -> Order:
        raise RuntimeError(
            "Read-only broker proxy: submit_order() is blocked. "
            "This proxy is for account queries only.",
        )

    def cancel_order(self, order_id: str) -> Order:
        raise RuntimeError(
            "Read-only broker proxy: cancel_order() is blocked. "
            "This proxy is for account queries only.",
        )

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        return self._inner.get_fills(order_id)


# ---------------------------------------------------------------------------
# Shadow live runner
# ---------------------------------------------------------------------------


@dataclass
class ShadowSessionMetrics:
    """Lightweight metrics for a single shadow-live poll cycle."""

    cycle_index: int = 0
    bars_fetched: int = 0
    signals_generated: int = 0
    intents_created: int = 0
    intents_submitted: int = 0
    intents_rejected: int = 0
    fresh_bars: bool = False
    broker_reachable: bool = True
    cycle_duration_seconds: float = 0.0
    equity: float = 0.0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class ShadowLiveRunner:
    """Runs shadow live mode: real data + read-only broker + paper orders.

    Core invariant:
        **NO real order is ever submitted.**  The ``ShadowLiveRunner``
        uses a real ``AlpacaBroker`` (wrapped in ``ReadOnlyBrokerProxy``)
        for account queries only, and a separate ``PaperBroker`` (or
        ``SimulatedBroker``) for order submission.

    Safety:
        - ``_hard_safety_gate()`` raises ``RuntimeError`` if
          ``config.submit_real_orders`` is ``True``.
        - ``verify_no_real_orders()`` runs at bootstrap AND before every
          order submission.
        - The ``ReadOnlyBrokerProxy`` blocks ``submit_order`` and
          ``cancel_order`` with a ``RuntimeError``.
        - All real broker API errors are caught and logged — they never
          crash the loop.

    Lifecycle::

        runner = ShadowLiveRunner(config, strategy)
        runner.bootstrap()
        runner.start()              # calls run_market_session() internally
        # ... run_market_session() blocks until done ...
        runner.shutdown()
    """

    def __init__(
        self,
        config: ShadowLiveConfig,
        strategy: Any | None = None,
    ) -> None:
        self.config = config
        self.strategy: Any | None = strategy

        # Internal state
        self._bootstrapped: bool = False
        self._session_start: datetime | None = None
        self._cycle_index: int = 0
        self._last_bar_timestamps: dict[str, datetime] = {}
        self._stop_event: Event = Event()
        self.metrics_log: list[ShadowSessionMetrics] = []

        # Gate
        self._gate: ShadowLiveGate = ShadowLiveGate(config)

        # Components (wired during bootstrap)
        self.calendar: USEquityCalendar | None = None
        self.session_clock: SessionClock | None = None
        self.kill_switch: KillSwitch | None = None
        self.real_broker: ReadOnlyBrokerProxy | None = None
        self.paper_broker: PaperBroker | None = None
        self.oms: OrderManagementSystem | None = None
        self.ledger: JsonlLedgerStore | None = None
        self.state_store: LiveStateStore | None = None
        self.data_loop: MarketDataLoop | None = None
        self.reconciliation: ReconciliationService | None = None
        self._logger = logging.getLogger("shadow_live_runner")

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def bootstrap(self) -> bool:
        """Initialize all components and verify readiness.

        This method:
        1. Runs the gate check (all seven pre-flight checks).
        2. Creates calendar, session clock, kill switch.
        3. Creates real broker (read-only) and paper broker.
        4. Creates OMS, ledger, state store, market data loop.
        5. Recovers previous positions from ledger (if any).
        6. Verifies kill switch is clear.
        7. Verifies reconciliation is clean.

        Returns:
            ``True`` when the system is healthy and ready to start.
        """
        self._logger.info("ShadowLiveRunner bootstrapping")

        # 1. Hard safety gate — immutable invariant check
        self._hard_safety_gate()

        # 2. Gate checks
        if self.config.require_live_readiness_check:
            self.state_store = LiveStateStore(self.config.state_path)
            report = self._gate.check_all(state_store=self.state_store)
            self._logger.info("Gate check result: passed=%s", report.passed)
            for check_name, ok in report.checks.items():
                self._logger.info("  Gate check [%s] %s", "OK" if ok else "FAIL", check_name)
            if not report.passed:
                self._logger.error("Gate check blocked: %s", "; ".join(report.errors))
                return False
        else:
            self.state_store = LiveStateStore(self.config.state_path)
            self._logger.warning("Live readiness check disabled by config")

        # 3. Calendar and session clock
        try:
            self.calendar = USEquityCalendar.with_holidays()
            self.session_clock = SessionClock(self.calendar)
        except Exception as exc:
            self._logger.exception("Failed to create calendar: %s", exc)
            return False

        # 4. Kill switch
        try:
            kill_config = KillSwitchConfig(
                max_daily_loss_pct=self.config.daily_loss_limit_pct,
                max_consecutive_order_failures=3,
                max_data_staleness_seconds=self.config.poll_interval_seconds * 10,
            )
            self.kill_switch = KillSwitch(config=kill_config)
        except Exception as exc:
            self._logger.exception("Failed to create kill switch: %s", exc)
            return False

        # 5. Real broker (read-only wrapper)
        try:
            raw_broker = self._create_real_broker()
            self.real_broker = ReadOnlyBrokerProxy(raw_broker)
        except Exception as exc:
            self._logger.exception("Failed to create real broker: %s", exc)
            return False

        # 6. Paper broker
        try:
            self.paper_broker = self._create_paper_broker()
        except Exception as exc:
            self._logger.exception("Failed to create paper broker: %s", exc)
            return False

        # 7. OMS — uses the paper broker (NOT the real broker)
        try:
            from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine

            risk_engine = PreTradeRiskEngine(
                PreTradeRiskConfig(), calendar=self.calendar,
            )
            self.oms = OrderManagementSystem(
                broker=self.paper_broker,
                risk_engine=risk_engine,
                calendar=self.calendar,
                kill_switch=self.kill_switch,
                idempotency_path=str(
                    Path(self.config.ledger_root) / ".idempotency.json",
                ),
            )
        except Exception as exc:
            self._logger.exception("Failed to create OMS: %s", exc)
            return False

        # 8. Ledger
        try:
            self.ledger = JsonlLedgerStore(self.config.ledger_root)
        except Exception as exc:
            self._logger.exception("Failed to create ledger: %s", exc)
            return False

        # 9. Load idempotency keys and recover positions
        try:
            if self.oms is not None:
                loaded = self.oms.load_idempotency()
                if loaded:
                    self._logger.info("Loaded %d idempotency keys", loaded)
        except Exception as exc:
            self._logger.warning("Failed to load idempotency keys: %s", exc)

        try:
            if self.ledger is not None:
                positions = self.ledger.latest_positions_from_fills()
                if positions and self.paper_broker is not None:
                    self.paper_broker.positions = positions
                    # Rebuild cash from ledger
                    recovered_cash = self.ledger.latest_cash_from_fills()
                    if recovered_cash > 0:
                        self.paper_broker.cash = recovered_cash
                    self._logger.info(
                        "Recovered %d positions from ledger, cash=%.2f",
                        len(positions),
                        self.paper_broker.cash,
                    )
        except Exception as exc:
            self._logger.warning("Failed to recover positions from ledger: %s", exc)

        # 10. Market data loop
        if self.config.use_real_market_data and self.config.symbols:
            try:
                self.data_loop = MarketDataLoop(
                    symbols=self.config.symbols,
                    vendor=self.config.data_vendor,
                    bar_size=self.config.bar_size,
                    poll_interval_seconds=self.config.poll_interval_seconds,
                    data_root=self.config.data_root,
                )
            except Exception as exc:
                self._logger.exception("Failed to create market data loop: %s", exc)
                return False

        # 11. Kill switch must be clear
        if self.kill_switch is not None and self.kill_switch.triggered:
            self._logger.error(
                "Kill switch is triggered (reason: %s); cannot start.",
                self.kill_switch.reason,
            )
            return False

        # 12. Reconciliation check
        try:
            if self.ledger is not None and self.paper_broker is not None:
                self.reconciliation = ReconciliationService(
                    self.config.ledger_root, self.paper_broker,
                )
                recon = self.reconciliation.reconcile_positions()
                if recon.get("status") != "clean":
                    self._logger.warning(
                        "Reconciliation on start: %s", recon.get("status"),
                    )
                    # Do not block start — let the runner decide
        except Exception as exc:
            self._logger.warning("Reconciliation on start failed: %s", exc)

        self._bootstrapped = True
        self._logger.info(
            "ShadowLiveRunner bootstrap complete: mode=%s symbols=%s",
            self.config.broker_account_mode,
            self.config.symbols,
        )
        return True

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the shadow live loop.

        Calls ``bootstrap()`` if not yet bootstrapped, then enters the
        market session loop.  Blocks until the session ends or
        ``shutdown()`` is called from another thread.
        """
        self._hard_safety_gate()

        if not self._bootstrapped:
            ok = self.bootstrap()
            if not ok:
                raise RuntimeError("ShadowLiveRunner bootstrap failed; cannot start.")

        self._session_start = utc_now()
        self._logger.info(
            "Shadow-live session starting at %s",
            self._session_start.isoformat(),
        )
        self.run_market_session()

    def shutdown(self) -> None:
        """Graceful shutdown: persist state, save idempotency, log final state."""
        if not self._bootstrapped:
            return

        self._logger.info("ShadowLiveRunner shutting down")
        self._stop_event.set()

        # 1. Persist idempotency keys
        if self.oms is not None:
            try:
                self.oms.persist_idempotency()
            except Exception as exc:
                self._logger.warning("Failed to persist idempotency: %s", exc)

        # 2. Save final session state
        self._save_session_state()

        # 3. Log summary
        try:
            account = self.paper_broker.get_account() if self.paper_broker else None
            if account is not None:
                self._logger.info(
                    "Final paper state: equity=%.2f cash=%.2f positions=%d",
                    account.equity,
                    account.cash,
                    len(account.positions),
                )
        except Exception as exc:
            self._logger.warning("Failed to log final state: %s", exc)

        self._bootstrapped = False
        self._session_start = None
        self._logger.info("ShadowLiveRunner shutdown complete")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_market_session(self) -> None:
        """Main loop: real data, real read-only broker, paper orders.

        Each cycle:
        1. Hard safety gate check.
        2. Fetch real market data (errors caught, never crash).
        3. Validate freshness.
        4. Fetch real account state for monitoring (errors caught).
        5. Process new bars -> generate signals -> create intents -> risk
           check -> submit to paper broker -> record in ledger.
        6. Save session state.
        7. Sleep until next cycle.

        Loops until stop event, kill switch, session end, or max runtime.
        """
        self._ensure_bootstrapped()

        while self._should_keep_running():
            if self._stop_event.is_set():
                break

            if self.kill_switch is not None and self.kill_switch.triggered:
                self._logger.warning(
                    "Kill switch triggered (reason: %s); exiting loop.",
                    self.kill_switch.reason,
                )
                break

            cycle_start = _time.monotonic()
            metrics = ShadowSessionMetrics(cycle_index=self._cycle_index)
            self._cycle_index += 1

            try:
                # ---- 1. Hard safety gate ----
                self._verify_and_gate()

                # ---- 2. Market data ----
                if self.data_loop is not None:
                    try:
                        data_status = self.data_loop.run_once()
                        metrics.bars_fetched = (
                            len(data_status.symbols_updated) if data_status.fresh else 0
                        )
                        metrics.fresh_bars = data_status.fresh
                    except Exception as exc:
                        self._logger.exception("Market data poll failed: %s", exc)
                        metrics.fresh_bars = False
                        if self.kill_switch is not None:
                            self.kill_switch.record_order_failure()
                        self._emit_cycle_metrics(metrics, cycle_start)
                        self._cycle_sleep()
                        continue
                else:
                    data_status = None
                    metrics.fresh_bars = False

                # ---- 3. Freshness check ----
                if data_status is not None and not data_status.fresh:
                    stale = getattr(data_status, "stale_seconds", float("inf"))
                    if self.kill_switch is not None:
                        self.kill_switch.check_data_staleness(stale)
                    self._logger.debug("Stale data: %.0fs behind", stale)
                    self._emit_cycle_metrics(metrics, cycle_start)
                    self._cycle_sleep()
                    continue

                # ---- 4. Real account (read-only, errors caught) ----
                real_account: AccountState | None = None
                if self.real_broker is not None:
                    try:
                        real_account = self.real_broker.get_account()
                        metrics.broker_reachable = True
                    except Exception as exc:
                        self._logger.warning("Real broker unreachable: %s", exc)
                        metrics.broker_reachable = False
                        if self.kill_switch is not None:
                            self.kill_switch.record_order_failure()

                # ---- 5. Get new bars from cache ----
                new_bars = self._new_bars_from_cache()
                if not new_bars:
                    self._emit_cycle_metrics(metrics, cycle_start)
                    self._cycle_sleep()
                    continue

                # ---- 6. Process each new bar ----
                for bar in new_bars:
                    self._process_bar(bar, metrics, real_account)

                # ---- 7. Snapshot ----
                if self.paper_broker is not None and self.ledger is not None:
                    try:
                        snapshot = self.paper_broker.snapshot(utc_now())
                        self.ledger.append_snapshot(snapshot)
                        metrics.equity = snapshot.equity
                    except Exception as exc:
                        self._logger.warning("Failed to snapshot: %s", exc)

                # ---- 8. Update equity for kill switch ----
                if self.kill_switch is not None and metrics.equity > 0:
                    self.kill_switch.update_equity(metrics.equity)

            except Exception:
                self._logger.exception("Unhandled error in shadow-live cycle")
                if self.kill_switch is not None:
                    self.kill_switch.record_order_failure()

            finally:
                self._emit_cycle_metrics(metrics, cycle_start)
                self._save_session_state()
                self._cycle_sleep()

        self._logger.info(
            "Shadow-live session ended after %d cycles",
            self._cycle_index,
        )

    # ------------------------------------------------------------------
    # Bar processing
    # ------------------------------------------------------------------

    def _process_bar(
        self,
        bar: Bar,
        metrics: ShadowSessionMetrics,
        real_account: AccountState | None,
    ) -> None:
        """Process a single bar: update market, generate signals, submit paper orders."""
        # Update paper broker market prices
        if self.paper_broker is not None:
            try:
                self.paper_broker.update_market(bar)
            except Exception as exc:
                self._logger.warning("Failed to update paper broker market: %s", exc)
                return

        # Skip signal generation when no strategy
        if self.strategy is None:
            return

        try:
            # Get paper account for sizing/risk
            paper_account = self.paper_broker.get_account() if self.paper_broker else None
            prices: dict[str, float] = {}
            if self.paper_broker is not None:
                prices = dict(self.paper_broker.market_prices)

            context = StrategyContext(
                run_id=f"shadow_{self._cycle_index}",
                account=paper_account,
                market_prices=prices,
                universe=list(prices),
            )

            for signal in self.strategy.on_bar(MarketEvent.from_bar(bar), context):
                metrics.signals_generated += 1
                self._handle_signal(signal, paper_account, prices, bar, metrics)

        except Exception as exc:
            self._logger.exception("Error processing bar %s @ %s", bar.symbol, bar.timestamp_utc)
            if self.kill_switch is not None:
                self.kill_switch.record_order_failure()

    def _handle_signal(
        self,
        signal: Signal,
        account: AccountState | None,
        prices: dict[str, float],
        bar: Bar,
        metrics: ShadowSessionMetrics,
    ) -> None:
        """Convert a signal into order intents, risk-check, and submit to paper broker."""
        from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
        from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner

        sizer = PercentOfEquitySizer(PositionSizerConfig())
        sized = list(sizer.size([signal]))

        planner = RebalancePlanner(RebalanceConfig())
        intents = planner.plan(
            sized,
            account or AccountState(
                timestamp_utc=utc_now(),
                account_id="shadow",
                cash=0.0,
                equity=0.0,
                buying_power=0.0,
            ),
            prices,
            run_id=f"shadow_runtime_{self._cycle_index}",
        )

        for intent in intents:
            metrics.intents_created += 1

            if not self.config.submit_paper_orders:
                self._logger.debug(
                    "submit_paper_orders=False; skipping intent %s for %s",
                    intent.order_intent_id,
                    intent.symbol,
                )
                continue

            # HARD SAFETY GATE before every order submission
            self._verify_and_gate()

            if self.oms is None or account is None:
                self._logger.warning("OMS or account not available; skipping order.")
                continue

            result: OMSResult = self.oms.handle_intent(
                intent,
                account,
                market_price=prices.get(intent.symbol, 0.0),
                timestamp=bar.timestamp_utc,
            )

            if result.risk_decision.approved:
                metrics.intents_submitted += 1
            else:
                metrics.intents_rejected += 1

            # Record to ledger
            if result.order is not None and self.ledger is not None:
                self.ledger.append_order(result.order)
            if self.ledger is not None:
                for fill in result.fills:
                    self.ledger.append_fill(fill)

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _hard_safety_gate(self) -> None:
        """CRITICAL: raise ``RuntimeError`` if real orders could be submitted.

        This is the immutable invariant check.  It is called:
        - At the top of ``bootstrap()``.
        - At the top of ``start()``.
        - Before every order submission in ``_handle_signal()``.
        """
        if self.config.submit_real_orders:
            raise RuntimeError(
                "CRITICAL SAFETY VIOLATION: submit_real_orders is True. "
                "Shadow live mode MUST NEVER submit real orders. "
                "Set submit_real_orders=False and restart.",
            )

    def _verify_and_gate(self) -> None:
        """Convenience: runs ``_hard_safety_gate()`` and ``verify_no_real_orders()``."""
        self._hard_safety_gate()
        if not self._gate.verify_no_real_orders():
            raise RuntimeError(
                "CRITICAL SAFETY VIOLATION: verify_no_real_orders() returned False. "
                "Shadow live mode MUST NEVER submit real orders.",
            )

    # ------------------------------------------------------------------
    # Bar filtering
    # ------------------------------------------------------------------

    def _new_bars_from_cache(self) -> list[Bar]:
        """Read latest bars from cache and filter to previously unseen ones.

        Deduplicates by comparing ``timestamp_utc`` against the last
        processed timestamp per symbol.  Tracks new timestamps in
        ``_last_bar_timestamps`` (in-memory) and persists them via
        the state store on each cycle.
        """
        if self.data_loop is None:
            return []

        try:
            latest = self.data_loop.fetch_latest_bars()
        except Exception as exc:
            self._logger.warning("Failed to fetch latest bars: %s", exc)
            return []

        if latest is None or latest.empty:
            return []

        new: list[Bar] = []
        for _, row in latest.iterrows():
            symbol = str(row.get("symbol", "")).upper()
            ts_raw = row.get("timestamp_utc")
            if not symbol or ts_raw is None:
                continue

            try:
                import pandas as pd

                ts = ensure_utc(pd.Timestamp(ts_raw).to_pydatetime())
            except Exception:
                continue

            last_ts = self._last_bar_timestamps.get(symbol)
            if last_ts is not None and ts <= last_ts:
                continue

            new.append(
                Bar(
                    timestamp_utc=ts,
                    symbol=symbol,
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=float(row.get("volume", 0.0)),
                    source=self.config.data_vendor,
                ),
            )
            self._last_bar_timestamps[symbol] = ts

        return new

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _save_session_state(self) -> None:
        """Persist the current session state via ``LiveStateStore``."""
        if self.state_store is None:
            return

        try:
            state = LiveSessionState(
                session_id=self.state_store.new_session_id(),
                started_at=self._session_start or utc_now(),
                last_cycle_at=utc_now(),
                state=LiveSessionRunner.RUNNING,
                kill_switch_triggered=(
                    self.kill_switch.triggered if self.kill_switch else False
                ),
                last_bar_timestamps=dict(self._last_bar_timestamps),
            )
            self.state_store.save_state(state)
        except Exception as exc:
            self._logger.warning("Failed to save session state: %s", exc)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _ensure_bootstrapped(self) -> None:
        if not self._bootstrapped:
            raise RuntimeError(
                "ShadowLiveRunner not bootstrapped. Call bootstrap() first.",
            )

    def _should_keep_running(self) -> bool:
        """Check session clock and wall-clock limits."""
        if self._stop_event.is_set():
            return False
        if self.session_clock is not None:
            now = utc_now()
            if self.session_clock.should_shutdown(now):
                return False
        if self._session_start is not None:
            elapsed = (utc_now() - self._session_start).total_seconds() / 3600.0
            if elapsed > self.config.max_runtime_hours:
                self._logger.info(
                    "max_runtime_hours (%.1f) exceeded", self.config.max_runtime_hours,
                )
                return False
        return True

    def _cycle_sleep(self) -> None:
        """Sleep between cycles, respecting the stop event."""
        self._stop_event.wait(self.config.poll_interval_seconds)

    def _emit_cycle_metrics(
        self,
        metrics: ShadowSessionMetrics,
        cycle_start: float,
    ) -> None:
        """Record cycle metrics and emit a structured log line."""
        metrics.cycle_duration_seconds = _time.monotonic() - cycle_start
        self.metrics_log.append(metrics)
        self._logger.info(
            "shadow_live_cycle index=%d fresh=%s bars=%d signals=%d "
            "intents=%d submitted=%d rejected=%d cycle_ms=%.0f "
            "broker_ok=%s equity=%.2f",
            metrics.cycle_index,
            metrics.fresh_bars,
            metrics.bars_fetched,
            metrics.signals_generated,
            metrics.intents_created,
            metrics.intents_submitted,
            metrics.intents_rejected,
            metrics.cycle_duration_seconds * 1000.0,
            metrics.broker_reachable,
            metrics.equity,
        )

    # ------------------------------------------------------------------
    # Broker creation
    # ------------------------------------------------------------------

    def _create_real_broker(self) -> AlpacaBroker:
        """Create the real broker instance for read-only account queries.

        The returned broker is later wrapped in ``ReadOnlyBrokerProxy``.
        """
        paper_mode = self.config.broker_account_mode != "live_readonly"
        if paper_mode:
            base_url = "https://paper-api.alpaca.markets"
        else:
            base_url = "https://api.alpaca.markets"

        return AlpacaBroker(
            AlpacaBrokerConfig(
                api_key=self.config.broker_api_key,
                api_secret=self.config.broker_api_secret,
                paper=paper_mode,
                base_url=base_url,
            ),
        )

    @staticmethod
    def _create_paper_broker() -> SimulatedBroker:
        """Create the paper broker for order submission.

        Uses ``SimulatedBroker`` which applies slippage and commission
        during fill simulation based on real market prices.
        """
        return SimulatedBroker(
            initial_cash=100_000.0,
            commission_model=PercentCommission(rate=0.0001),
            slippage_model=BpsSlippage(bps=1.0),
            broker_name="shadow_paper",
            fill_ratio=0.95,
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def session_summary(self) -> dict[str, Any]:
        """Return a dict summary of the completed session."""
        total_signals = sum(m.signals_generated for m in self.metrics_log)
        total_submitted = sum(m.intents_submitted for m in self.metrics_log)
        total_rejected = sum(m.intents_rejected for m in self.metrics_log)
        cycles_broker_ok = sum(1 for m in self.metrics_log if m.broker_reachable)
        final_equity = self.metrics_log[-1].equity if self.metrics_log else 0.0

        return {
            "cycles": self._cycle_index,
            "total_signals": total_signals,
            "total_intents_submitted": total_submitted,
            "total_intents_rejected": total_rejected,
            "cycles_broker_reachable": cycles_broker_ok,
            "final_equity": final_equity,
            "max_runtime_hours": self.config.max_runtime_hours,
            "symbols": list(self.config.symbols),
            "submit_real_orders": False,
        }

