"""Paper runtime: orchestrates the full daily paper trading cycle.

PaperRuntime is responsible for the intraday live loop:
  bootstrap -> run market session -> session close -> shutdown

It stays separated from LiveRunner (which is for real broker execution)
and from PaperTradingLoop (which is a one-day batch processor).
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.enums import OrderStatus, SessionName, TradingMode
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, Signal, TargetPosition, new_id
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.market_data_loop import MarketDataLoop
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.live.session_clock import SessionClock
from quant_us.monitoring.daily_report import generate_daily_report, save_report
from quant_us.monitoring.telegram_alerts import AlertPriority, TelegramAlertService, load_telegram_config_from_env
from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner
from quant_us.risk.data_freshness import DataFreshnessConfig, DataFreshnessGuard
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.risk.risk_event_log import RiskEventLog
from quant_us.strategies.base import Strategy, StrategyContext

_logger = logging.getLogger("paper_runtime")


@dataclass
class PaperRuntimeConfig:
    """Configuration for a single paper runtime session.

    Attributes:
        symbols: Tickers to trade.
        strategy_id: Logical name used in metadata / reports.
        capital: Starting cash.
        commission_rate: Fractional commission (e.g. 0.0001 = 1 bps).
        slippage_bps: Fixed slippage in basis points.
        poll_interval_seconds: Seconds between market-data polling cycles.
        data_root: Root path for cached market data.
        ledger_root: Root path for the JSONL ledger.
        pg_dsn: Optional PostgreSQL DSN for dual-write.
        reconcile_on_start: Run full reconciliation before the session.
        reconcile_on_close: Run full reconciliation after the session.
        kill_on_recon_fail: Trigger kill switch on reconciliation failure.
        max_runtime_hours: Hard wall-clock limit for the session.
        submit_orders: If False, generate intents but do not submit to broker.
        allow_live_orders: Always False for paper runtime.
        data_vendor: Connector name (e.g. "yfinance", "alpaca").
        bar_size: Bar interval (e.g. "1m", "5m").
    """

    symbols: list[str] = field(default_factory=list)
    strategy_id: str = ""
    capital: float = 100_000.0
    commission_rate: float = 0.0001
    slippage_bps: float = 1.0
    poll_interval_seconds: float = 60.0
    data_root: str = "data"
    ledger_root: str = "data/paper_ledger"
    pg_dsn: str = ""
    reconcile_on_start: bool = True
    reconcile_on_close: bool = True
    kill_on_recon_fail: bool = True
    max_runtime_hours: float = 24.0
    submit_orders: bool = True
    allow_live_orders: bool = False
    data_vendor: str = "yfinance"
    bar_size: str = "1m"
    risk_event_log_path: str = ""
    max_data_delay_seconds: float = 300.0


@dataclass
class PaperSessionMetrics:
    """Lightweight metrics emitted after each poll cycle."""
    poll_index: int = 0
    bars_fetched: int = 0
    bars_stale: int = 0
    signals_generated: int = 0
    intents_created: int = 0
    intents_submitted: int = 0
    intents_rejected: int = 0
    fresh_bars: bool = False
    cycle_duration_seconds: float = 0.0
    equity: float = 0.0


_EMPTY_BARS_CACHE = pd.DataFrame()


class PaperRuntime:
    """Orchestrates a paper trading session from bootstrap to shutdown.

    Typical usage::

        runtime = PaperRuntime(config)
        runtime.bootstrap(strategy=my_strategy)
        runtime.run_market_session()
        runtime.on_session_close()
        runtime.shutdown()
    """

    def __init__(self, config: PaperRuntimeConfig | None = None) -> None:
        self.config = config or PaperRuntimeConfig()
        self._bootstrapped: bool = False
        self._session_start: datetime | None = None
        self._poll_index: int = 0
        self._bars_cache: pd.DataFrame = _EMPTY_BARS_CACHE
        self._last_bar_timestamps: dict[str, datetime] = {}
        self.session_metrics: list[PaperSessionMetrics] = []
        self.metrics_log: list[PaperSessionMetrics] = []

        # Wired in bootstrap() — declared for type-checking
        self.calendar: USEquityCalendar
        self.session_clock: SessionClock
        self.kill_switch: KillSwitch
        self.risk_event_log: RiskEventLog | None = None
        self.broker: SimulatedBroker
        self.risk_engine: PreTradeRiskEngine
        self.oms: OrderManagementSystem
        self.ledger: JsonlLedgerStore
        self.data_loop: MarketDataLoop
        self.strategy: Strategy | None = None
        self.data_freshness: DataFreshnessGuard
        self.alerts: TelegramAlertService
        self._halt_reconciliation: bool = False

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def bootstrap(
        self,
        strategy: Strategy | None = None,
    ) -> None:
        """Initialize every component needed for a paper trading session.

        Args:
            strategy: A ``Strategy`` instance.  May be ``None``, in which
                      case the runtime will skip signal generation (data-
                      collection-only mode).
        """
        if self._bootstrapped:
            _logger.warning("PaperRuntime already bootstrapped; resetting.")
            self.shutdown()

        self.calendar = USEquityCalendar.with_holidays()
        self.session_clock = SessionClock(self.calendar)

        # Risk event log
        self.risk_event_log = None
        if self.config.risk_event_log_path:
            self.risk_event_log = RiskEventLog(self.config.risk_event_log_path)

        # Kill switch
        kill_config = KillSwitchConfig(
            max_consecutive_order_failures=3,
            max_data_staleness_seconds=self.config.max_data_delay_seconds * 3,
        )
        self.kill_switch = KillSwitch(
            config=kill_config,
            risk_event_log=self.risk_event_log,
        )

        # Data freshness
        self.data_freshness = DataFreshnessGuard(
            DataFreshnessConfig(max_delay_seconds=self.config.max_data_delay_seconds),
        )

        # Broker
        self.broker = SimulatedBroker(
            initial_cash=self.config.capital,
            commission_model=PercentCommission(rate=self.config.commission_rate),
            slippage_model=BpsSlippage(bps=self.config.slippage_bps),
            broker_name="paper_runtime",
            fill_ratio=0.95,
        )

        # Risk engine
        risk_config = PreTradeRiskConfig()
        self.risk_engine = PreTradeRiskEngine(risk_config, calendar=self.calendar)

        # OMS
        self.oms = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            calendar=self.calendar,
            kill_switch=self.kill_switch,
            risk_event_log=self.risk_event_log,
            idempotency_path=str(Path(self.config.ledger_root) / ".idempotency.json"),
        )

        # Ledger
        self.ledger = JsonlLedgerStore(self.config.ledger_root)

        # Market data loop
        self.data_loop = MarketDataLoop(
            symbols=self.config.symbols,
            vendor=self.config.data_vendor,
            bar_size=self.config.bar_size,
            poll_interval_seconds=self.config.poll_interval_seconds,
            data_root=self.config.data_root,
        )

        # Strategy
        self.strategy = strategy

        # Alerts
        env_config = load_telegram_config_from_env()
        if env_config is not None:
            self.alerts = TelegramAlertService(env_config)
        else:
            self.alerts = TelegramAlertService()

        # Optional reconcile on start
        if self.config.reconcile_on_start:
            self._reconcile_or_start()
        else:
            self._halt_reconciliation = False

        self._bootstrapped = True
        _logger.info(
            "PaperRuntime bootstrapped: symbols=%s strategy=%s capital=%.2f",
            self.config.symbols,
            self.config.strategy_id,
            self.config.capital,
        )

    # ------------------------------------------------------------------
    # Market session loop
    # ------------------------------------------------------------------

    def run_market_session(self) -> None:
        """Run the main loop while ``SessionClock.should_be_running()``.

        Each cycle: fetch data -> validate freshness -> generate signals ->
        create intents -> risk check -> submit (if allowed) -> poll fills ->
        update ledger -> emit metrics -> sleep.
        """
        self._ensure_bootstrapped()
        self._session_start = utc_now()
        _logger.info("PaperRuntime market session starting at %s", self._session_start.isoformat())

        while self._should_keep_running():
            if self.kill_switch.triggered:
                _logger.warning("Kill switch triggered; exiting market session.")
                break

            cycle_start = _time.monotonic()
            metrics = PaperSessionMetrics(poll_index=self._poll_index)
            self._poll_index += 1

            try:
                # 1. Fetch latest bars
                data_status = self.data_loop.run_once()
                metrics.bars_fetched = len(data_status.symbols_updated) if data_status.fresh else 0

                # 2. Validate freshness
                if not data_status.fresh:
                    metrics.bars_stale = metrics.bars_fetched
                    metrics.fresh_bars = False
                    self.kill_switch.check_data_staleness(data_status.stale_seconds)
                    _logger.debug("Stale data: %.0fs behind", data_status.stale_seconds)
                    self._emit_cycle_metrics(metrics)
                    self._sleep()
                    continue

                metrics.fresh_bars = True

                # 3. Load bars from cache, filter to new bars
                new_bars = self._new_bars_from_cache()
                if not new_bars:
                    self._emit_cycle_metrics(metrics)
                    self._sleep()
                    continue

                # 4. Process each new bar
                for bar in new_bars:
                    self._process_bar(bar, metrics)

                # 5. Snapshot
                account = self.broker.get_account()
                snapshot = self.broker.snapshot(utc_now())
                self.ledger.append_snapshot(snapshot)
                metrics.equity = account.equity

            except Exception:
                _logger.exception("Unhandled error in market session cycle")
                self.kill_switch.record_order_failure()
            finally:
                cycle_duration = _time.monotonic() - cycle_start
                metrics.cycle_duration_seconds = cycle_duration
                self._emit_cycle_metrics(metrics)
                self._sleep()

        _logger.info("PaperRuntime market session ended after %d cycles", self._poll_index)

    # ------------------------------------------------------------------
    # Session close (end-of-day)
    # ------------------------------------------------------------------

    def on_session_close(self) -> None:
        """End-of-day activities: reconcile, generate daily report, save state.

        This is called after the market session ends (market closed or
        max_runtime_hours exceeded).
        """
        self._ensure_bootstrapped()

        today = self._trading_date()
        _logger.info("PaperRuntime on_session_close for %s", today.isoformat())

        account = self.broker.get_account()
        self.kill_switch.update_equity(account.equity)

        # Reconcile on close
        if self.config.reconcile_on_close:
            if self._reconcile_or_close():
                _logger.info("Reconciliation passed for %s", today.isoformat())
            else:
                _logger.error("Reconciliation FAILED for %s", today.isoformat())

        # Generate and persist daily trading report
        try:
            report = generate_daily_report(today, self.ledger, self.broker, self.kill_switch)
            report.reconciliation_status = "clean" if not self._halt_reconciliation else "breaks_detected"
            save_report(report, Path(self.config.ledger_root) / "daily_reports")
        except Exception:
            _logger.exception("Failed to generate daily report on session close")

        _logger.info(
            "on_session_close complete: equity=%.2f cash=%.2f positions=%d",
            account.equity,
            account.cash,
            len(account.positions),
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Graceful stop: persist idempotency, log final metrics."""
        if not self._bootstrapped:
            return

        _logger.info("PaperRuntime shutting down after %d poll cycles", self._poll_index)

        try:
            self.oms.persist_idempotency()
        except Exception:
            _logger.exception("Failed to persist idempotency during shutdown")

        try:
            account = self.broker.get_account()
            _logger.info(
                "Final state: equity=%.2f cash=%.2f positions=%d kill_switch=%s",
                account.equity,
                account.cash,
                len(account.positions),
                self.kill_switch.triggered,
            )
        except Exception:
            _logger.exception("Failed to log final account state")

        self._bootstrapped = False
        self._session_start = None
        _logger.info("PaperRuntime shutdown complete")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Return True when the runtime can continue trading."""
        if not self._bootstrapped:
            return False
        if self.kill_switch.triggered:
            return False
        if self._halt_reconciliation:
            return False
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_bootstrapped(self) -> None:
        if not self._bootstrapped:
            raise RuntimeError("PaperRuntime not bootstrapped; call bootstrap() first.")

    def _now(self) -> datetime:
        """Hook for sub-second precision; overridable in tests."""
        return utc_now()

    def _sleep(self) -> None:
        """Sleep between poll cycles."""
        self._time_sleep(self.config.poll_interval_seconds)

    @staticmethod
    def _time_sleep(seconds: float) -> None:
        _time.sleep(seconds)

    def _trading_date(self) -> date:
        """Return the current trading date in ET."""
        return self._now().astimezone(PaperRuntime._et()).date()

    @staticmethod
    def _et():
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")

    def _should_keep_running(self) -> bool:
        """Check session-clock and wall-clock limits."""
        if not self.session_clock.should_be_running(self._now()):
            return False
        if self._session_start is not None:
            elapsed = (utc_now() - self._session_start).total_seconds() / 3600.0
            if elapsed > self.config.max_runtime_hours:
                _logger.info("max_runtime_hours (%.1f) exceeded", self.config.max_runtime_hours)
                return False
        return True

    # ------------------------------------------------------------------
    # Bar processing
    # ------------------------------------------------------------------

    def _new_bars_from_cache(self) -> list[Bar]:
        """Read latest bars from the parquet cache and filter to new ones.

        Returns a list of ``Bar`` objects that are newer than the last
        processed timestamp per symbol.
        """
        try:
            latest_bars = self.data_loop.fetch_latest_bars()
        except Exception:
            _logger.exception("Failed to fetch latest bars from cache")
            return []

        if latest_bars.empty:
            return []

        new: list[Bar] = []
        for _, row in latest_bars.iterrows():
            symbol = str(row.get("symbol", "")).upper()
            ts_raw = row.get("timestamp_utc")
            if not symbol or ts_raw is None:
                continue
            ts = ensure_utc(pd.Timestamp(ts_raw).to_pydatetime())
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
                )
            )
            self._last_bar_timestamps[symbol] = ts

        return new

    def _process_bar(self, bar: Bar, metrics: PaperSessionMetrics) -> None:
        """Process a single bar: update market, generate signals, create intents."""
        # Data freshness check
        freshness = self.data_freshness.evaluate_bar(bar)
        if not freshness.fresh:
            metrics.bars_stale += 1
            self.kill_switch.check_data_staleness(freshness.delay_seconds)
            return

        # Update broker market state
        self.broker.update_market(bar)

        # Skip signal generation when no strategy is loaded
        if self.strategy is None:
            return

        try:
            prices: dict[str, float] = self.broker.market_prices.copy()
            account = self.broker.get_account()

            context = StrategyContext(
                run_id=f"paper_{_time.strftime('%Y%m%d')}",
                account=account,
                market_prices=prices,
                universe=list(prices),
            )

            for signal in self.strategy.on_bar(MarketEvent.from_bar(bar), context):
                metrics.signals_generated += 1
                self._handle_signal(signal, account, prices, bar, metrics)

        except Exception:
            _logger.exception("Error processing bar %s @ %s", bar.symbol, bar.timestamp_utc.isoformat())
            self.kill_switch.record_order_failure()

    def _handle_signal(
        self,
        signal: Signal,
        account: AccountState,
        prices: dict[str, float],
        bar: Bar,
        metrics: PaperSessionMetrics,
    ) -> None:
        """Convert a signal into order intents, run risk checks, and submit."""
        sizer = PercentOfEquitySizer(PositionSizerConfig())
        sized = list(sizer.size([signal]))

        planner = RebalancePlanner(RebalanceConfig())
        intents = planner.plan(
            sized,
            account,
            prices,
            run_id=f"paper_runtime_{self.config.strategy_id}",
        )

        for intent in intents:
            metrics.intents_created += 1

            if not self.config.submit_orders:
                # Intent generated but not submitted — useful for dry-run
                _logger.debug(
                    "submit_orders=False; skipping submission of intent %s for %s",
                    intent.order_intent_id,
                    intent.symbol,
                )
                continue

            result = self.oms.handle_intent(
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
            if result.order:
                self.ledger.append_order(result.order)
            for fill in result.fills:
                self.ledger.append_fill(fill)

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def _reconcile_or_start(self) -> None:
        """Run reconciliation at bootstrap. Block if breaks detected and
        ``kill_on_recon_fail`` is set."""
        service = ReconciliationService(self.config.ledger_root, self.broker)
        report = service.reconcile_all(
            initial_cash=self.config.capital,
        )
        if report.status == "breaks_detected":
            _logger.error("Reconciliation on start FAILED: cash_diff=%.2f pos_diffs=%d",
                          report.cash_diff, len(report.position_diffs))
            if self.config.kill_on_recon_fail:
                self.kill_switch.trip("reconciliation_start_failure")
            self._halt_reconciliation = True

    def _reconcile_or_close(self) -> bool:
        """Run reconciliation at session close. Triggers kill switch if configured."""
        service = ReconciliationService(self.config.ledger_root, self.broker)
        report = service.reconcile_all(
            initial_cash=self.config.capital,
        )
        passed = report.status == "clean"
        if not passed:
            _logger.error("Reconciliation on close FAILED: cash_diff=%.2f pos_diffs=%d",
                          report.cash_diff, len(report.position_diffs))
            self._halt_reconciliation = True
            if self.config.kill_on_recon_fail:
                self.kill_switch.record_recon_failure()
        return passed

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _emit_cycle_metrics(self, metrics: PaperSessionMetrics) -> None:
        """Record cycle metrics and emit a structured log line."""
        self.metrics_log.append(metrics)
        _logger.debug(
            "paper_runtime_cycle index=%d fresh=%s bars=%d stale=%d signals=%d "
            "intents=%d submitted=%d rejected=%d cycle_ms=%.0f equity=%.2f",
            metrics.poll_index,
            metrics.fresh_bars,
            metrics.bars_fetched,
            metrics.bars_stale,
            metrics.signals_generated,
            metrics.intents_created,
            metrics.intents_submitted,
            metrics.intents_rejected,
            metrics.cycle_duration_seconds * 1000.0,
            metrics.equity,
        )
