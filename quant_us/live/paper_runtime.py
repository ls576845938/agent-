"""Paper runtime: orchestrates the full daily paper trading cycle.

PaperRuntime is responsible for the intraday live loop:
  bootstrap -> run market session -> session close -> shutdown

It stays separated from LiveRunner (which is for real broker execution)
and from PaperTradingLoop (which is a one-day batch processor).
"""

from __future__ import annotations

import json
import logging
import os
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
from quant_us.core.enums import OrderSide, OrderStatus, SessionName, TradingMode
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, Signal, TargetPosition, new_id
from quant_us.execution.fill_idempotency import (
    FillIdempotencyIndex,
    append_fill_idempotent,
)
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.live.paper_adapter_contract import (
    ALLOWED_ALPACA_PAPER_BASE_URLS,
    audit_apca_paper_credentials,
    evaluate_paper_adapter_contract,
    normalize_alpaca_base_url,
    paper_adapter_capability_defaults,
)
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.market_data_loop import MarketDataLoop
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.live.session_clock import SessionClock
from quant_us.monitoring.daily_report import generate_daily_report, save_report
from quant_us.monitoring.telegram_alerts import AlertPriority, TelegramAlertService, load_telegram_config_from_env
from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner
from quant_us.research.evidence_registry import project_saved_paper_review_evidence
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
        paper_broker: Broker profile. "simulated" is the local simulated
            broker. "alpaca" requests an Alpaca paper broker and is blocked
            unless a real Alpaca paper adapter is wired and all paper gates pass.
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
    submit_orders: bool = False
    allow_live_orders: bool = False
    data_vendor: str = "yfinance"
    paper_broker: str = "simulated"
    bar_size: str = "1m"
    risk_event_log_path: str = ""
    max_data_delay_seconds: float = 300.0
    promotion_manifest_id: str = ""
    paper_review_id: str = ""
    paper_review_path: str = ""
    promotion_data_root: str = "data"
    audit_log_path: str = ""
    reduce_only: bool = False


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
_ALLOWED_ALPACA_PAPER_BASE_URLS = ALLOWED_ALPACA_PAPER_BASE_URLS
_PAPER_STARTUP_SYNC_ARTIFACT_VERSION = "paper_broker_adapter_startup_sync_v1"


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
        self.audit_events: list[dict[str, Any]] = []
        self._fill_index = FillIdempotencyIndex()

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

        entry_gate = self._check_runtime_entry_gate()
        self._audit_runtime_event("paper_runtime_entry_gate", entry_gate)
        if not entry_gate["ok"]:
            reason = "; ".join(entry_gate["reasons"])
            _logger.error("PaperRuntime entry gate blocked: %s", reason)
            raise RuntimeError(f"PaperRuntime entry gate blocked: {reason}")

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
        self.broker = self._build_paper_broker()

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
        self.oms.reduce_only = self.config.reduce_only

        # Ledger
        self.ledger = JsonlLedgerStore(self.config.ledger_root)
        self._fill_index = FillIdempotencyIndex.from_ledger(self.ledger)
        self._recover_oms_idempotency()
        self._run_paper_adapter_startup_sync()

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

            reduce_only_projection = None
            if self.config.reduce_only or getattr(self.oms, "reduce_only", False):
                reduce_only_projection = self._reduce_only_projected_positions(account)

            for signal in self.strategy.on_bar(MarketEvent.from_bar(bar), context):
                metrics.signals_generated += 1
                self._handle_signal(
                    signal,
                    account,
                    prices,
                    bar,
                    metrics,
                    reduce_only_projection=reduce_only_projection,
                )

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
        reduce_only_projection: dict[str, float] | None = None,
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

            kill_switch = getattr(self, "kill_switch", None)
            if kill_switch is not None and kill_switch.triggered:
                metrics.intents_rejected += 1
                self._audit_runtime_event(
                    "paper_order_rejected_kill_switch",
                    {
                        "reason": kill_switch.reason or "kill_switch_active",
                        "client_order_id": intent.client_order_id,
                        "symbol": intent.symbol,
                        "side": intent.side.value,
                        "quantity": intent.quantity,
                    },
                )
                _logger.warning(
                    "Kill switch rejected intent %s for %s",
                    intent.client_order_id,
                    intent.symbol,
                )
                continue

            if not self.config.submit_orders:
                # Intent generated but not submitted — useful for dry-run
                _logger.debug(
                    "submit_orders=False; skipping submission of intent %s for %s",
                    intent.order_intent_id,
                    intent.symbol,
                )
                continue

            reduce_only_active = self.config.reduce_only or getattr(self.oms, "reduce_only", False)
            if reduce_only_active:
                if reduce_only_projection is None:
                    reduce_only_projection = self._reduce_only_projected_positions(account)
                allowed, reason = self._reduce_only_allows(
                    intent,
                    account,
                    projected_positions=reduce_only_projection,
                )
                if not allowed:
                    metrics.intents_rejected += 1
                    self._audit_runtime_event(
                        "paper_order_rejected_reduce_only",
                        {
                            "reason": reason,
                            "client_order_id": intent.client_order_id,
                            "symbol": intent.symbol,
                            "side": intent.side.value,
                            "quantity": intent.quantity,
                        },
                    )
                    _logger.warning(
                        "Reduce-only rejected intent %s for %s: %s",
                        intent.client_order_id,
                        intent.symbol,
                        reason,
                    )
                    continue

            result = self.oms.handle_intent(
                intent,
                account,
                market_price=prices.get(intent.symbol, 0.0),
                timestamp=bar.timestamp_utc,
            )

            if result.risk_decision.approved:
                self._apply_reduce_only_projection(intent, reduce_only_projection)
                metrics.intents_submitted += 1
            else:
                metrics.intents_rejected += 1

            # Record to ledger
            if result.order:
                self.ledger.append_order(result.order)
            for fill in result.fills:
                fill_append = append_fill_idempotent(
                    self.ledger,
                    fill,
                    index=self._fill_index,
                    logger=_logger,
                )
                if fill_append.conflict:
                    self._audit_runtime_event(
                        "paper_fill_conflict_skipped",
                        {
                            "key": fill_append.key,
                            "client_order_id": intent.client_order_id,
                            "symbol": intent.symbol,
                        },
                    )

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
            self.oms.reduce_only = True
            self._halt_reconciliation = True
            self._audit_runtime_event(
                "paper_reconciliation_start_failed",
                {
                    "cash_diff": report.cash_diff,
                    "position_diff_count": len(report.position_diffs),
                    "reduce_only": True,
                    "halt_reconciliation": True,
                },
            )

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
            self.oms.reduce_only = True
            if self.config.kill_on_recon_fail:
                self.kill_switch.record_recon_failure()
            self._audit_runtime_event(
                "paper_reconciliation_close_failed",
                {
                    "cash_diff": report.cash_diff,
                    "position_diff_count": len(report.position_diffs),
                    "reduce_only": True,
                    "halt_reconciliation": True,
                },
            )
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

    # ------------------------------------------------------------------
    # Safety gates / audit
    # ------------------------------------------------------------------

    def _recover_oms_idempotency(self) -> None:
        try:
            loaded_count = self.oms.load_idempotency()
            self._validate_order_ledger_for_recovery()
            ledger_count = self.oms.recover_from_ledger(self.config.ledger_root)
        except Exception as exc:
            self.oms.reduce_only = True
            self._halt_reconciliation = True
            self._audit_runtime_event(
                "paper_oms_idempotency_recovery_failed",
                {
                    "error": str(exc),
                    "reduce_only": True,
                    "halt_reconciliation": True,
                },
            )
            raise RuntimeError(f"paper_oms_idempotency_recovery_failed: {exc}") from exc

        self._audit_runtime_event(
            "paper_oms_idempotency_recovered",
            {
                "idempotency_loaded_count": loaded_count,
                "ledger_recovered_count": ledger_count,
                "client_order_id_count": len(self.oms._client_order_ids),
            },
        )

    def _validate_order_ledger_for_recovery(self) -> None:
        orders_file = Path(self.config.ledger_root) / "orders.jsonl"
        if not orders_file.exists():
            return

        lines = orders_file.read_text(encoding="utf-8").splitlines()
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"orders.jsonl line {line_no} is not valid JSON") from exc
            if not isinstance(record, dict):
                raise ValueError(f"orders.jsonl line {line_no} is not an object")
            if not record.get("client_order_id"):
                raise ValueError(f"orders.jsonl line {line_no} missing client_order_id")

    def _check_runtime_entry_gate(self) -> dict[str, Any]:
        """Block unsafe paper runtime configurations before any broker is created."""
        reasons: list[str] = []
        paper_broker = self.config.paper_broker.lower()
        adapter_contract = self._paper_adapter_contract()
        broker_backend = str(adapter_contract["effective_backend"])
        credential_audit = self._paper_credential_audit()
        checks = {
            "mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "allow_live_orders_false": not self.config.allow_live_orders,
            "real_live_orders_disabled": True,
            "real_order_submission": False,
            "paper_order_submission": bool(self.config.submit_orders),
            "paper_broker": paper_broker,
            "broker_backend": broker_backend,
            "alpaca_paper_requested": self._alpaca_paper_requested(),
            "alpaca_paper_adapter_enabled": bool(adapter_contract["adapter_enabled"]),
            "paper_credentials_present": True,
            "paper_review_or_promotion_evidence": True,
            "paper_adapter_contract": adapter_contract,
            "paper_credential_audit": credential_audit,
        }

        def add_reason(reason: str) -> None:
            if reason and reason not in reasons:
                reasons.append(reason)

        if self.config.allow_live_orders:
            add_reason("paper_runtime_cannot_allow_live_orders")

        if paper_broker not in {"simulated", "alpaca"}:
            add_reason(f"unsupported_paper_broker: {self.config.paper_broker}")

        if self._alpaca_paper_requested():
            credentials_ok, credential_reason = self._has_apca_paper_credentials()
            checks["paper_credentials_present"] = credentials_ok
            if not credentials_ok:
                add_reason(credential_reason)

            evidence_ok, evidence_reason = self._has_paper_entry_evidence()
            checks["paper_review_or_promotion_evidence"] = evidence_ok
            if not evidence_ok:
                add_reason(evidence_reason)

            if bool(adapter_contract["fail_closed"]):
                add_reason(str(adapter_contract["reason"]))

        return {"ok": not reasons, "checks": checks, "reasons": reasons}

    def _alpaca_paper_requested(self) -> bool:
        return self.config.paper_broker.lower() == "alpaca"

    @staticmethod
    def _alpaca_paper_adapter_enabled() -> bool:
        return False

    @staticmethod
    def _alpaca_paper_adapter_factory_present() -> bool:
        return False

    @staticmethod
    def _alpaca_paper_adapter_capabilities() -> dict[str, bool]:
        return paper_adapter_capability_defaults()

    def _create_alpaca_paper_broker(self) -> SimulatedBroker:
        raise RuntimeError("alpaca_paper_adapter_factory_missing")

    def _build_paper_broker(self) -> SimulatedBroker:
        contract = self._paper_adapter_contract()
        if contract["effective_backend"] == "alpaca_paper":
            try:
                broker = self._create_alpaca_paper_broker()
                self._validate_paper_adapter_surface(broker)
            except Exception as exc:
                self._audit_runtime_event(
                    "paper_broker_adapter_factory_failed",
                    {
                        "error": str(exc),
                        "paper_adapter_contract": contract,
                    },
                )
                raise RuntimeError(f"alpaca_paper_adapter_factory_failed: {exc}") from exc

            self._audit_runtime_event(
                "paper_broker_adapter_activated",
                {
                    "paper_adapter_contract": contract,
                    "broker_name": getattr(broker, "broker_name", type(broker).__name__),
                },
            )
            return broker

        return SimulatedBroker(
            initial_cash=self.config.capital,
            commission_model=PercentCommission(rate=self.config.commission_rate),
            slippage_model=BpsSlippage(bps=self.config.slippage_bps),
            broker_name="paper_runtime",
            fill_ratio=0.95,
        )

    def _validate_paper_adapter_surface(self, broker: Any) -> None:
        required = self._alpaca_paper_adapter_capabilities()
        missing = [
            name for name, enabled in required.items()
            if enabled and not hasattr(broker, name)
        ]
        if missing:
            raise TypeError(
                "alpaca_paper_adapter_surface_missing: " + ",".join(sorted(missing))
            )

    def _run_paper_adapter_startup_sync(self) -> None:
        if self._paper_broker_backend() != "alpaca_paper":
            return

        contract = self._paper_adapter_contract()
        artifact = {
            "artifact_type": "paper_broker_adapter_startup_sync",
            "artifact_version": _PAPER_STARTUP_SYNC_ARTIFACT_VERSION,
            "mode": "paper",
            "runtime_mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "paper_broker": self.config.paper_broker,
            "backend": str(contract["effective_backend"]),
            "broker_backend": str(contract["effective_backend"]),
            "real_order_submission": False,
            "paper_order_submission": bool(self.config.submit_orders),
            "adapter_contract": contract,
            "contract_version": str(contract.get("contract_version", "")),
            "status": "in_progress",
            "reduce_only": False,
            "halt_reconciliation": False,
            "sync": {
                "poll_orders": {
                    "call_count": 0,
                    "order_count": 0,
                    "order_ids": [],
                },
                "sync_fills": {
                    "call_count": 0,
                    "fill_count": 0,
                    "fill_ids": [],
                    "order_ids": [],
                    "requested_order_ids": [],
                },
                "sync_account": {
                    "call_count": 0,
                    "account_id": "",
                },
                "sync_positions": {
                    "call_count": 0,
                    "position_count": 0,
                    "symbols": [],
                },
            },
        }

        try:
            artifact["sync"]["poll_orders"]["call_count"] = 1
            polled_orders = list(self.broker.poll_orders())
            polled_order_ids = self._sorted_unique_strings(
                getattr(order, "order_id", "") for order in polled_orders
            )
            artifact["sync"]["poll_orders"]["order_count"] = len(polled_orders)
            artifact["sync"]["poll_orders"]["order_ids"] = polled_order_ids

            synced_fills: list[Any] = []
            requested_fill_order_ids: list[str] = []
            if polled_orders:
                artifact["sync"]["sync_fills"]["call_count"] = len(polled_orders)
                for order in polled_orders:
                    order_id = getattr(order, "order_id", None)
                    if order_id:
                        requested_fill_order_ids.append(str(order_id))
                    synced_fills.extend(self.broker.sync_fills(order_id))
            else:
                artifact["sync"]["sync_fills"]["call_count"] = 1
                synced_fills = list(self.broker.sync_fills(None))

            artifact["sync"]["sync_fills"]["fill_count"] = len(synced_fills)
            artifact["sync"]["sync_fills"]["fill_ids"] = self._sorted_unique_strings(
                getattr(fill, "fill_id", "") for fill in synced_fills
            )
            artifact["sync"]["sync_fills"]["order_ids"] = self._sorted_unique_strings(
                getattr(fill, "order_id", "") for fill in synced_fills
            )
            artifact["sync"]["sync_fills"]["requested_order_ids"] = self._sorted_unique_strings(
                requested_fill_order_ids
            )

            artifact["sync"]["sync_account"]["call_count"] = 1
            account = self.broker.sync_account()
            artifact["sync"]["sync_account"]["account_id"] = str(account.account_id)

            artifact["sync"]["sync_positions"]["call_count"] = 1
            positions = self.broker.sync_positions()
            artifact["sync"]["sync_positions"]["position_count"] = len(positions)
            artifact["sync"]["sync_positions"]["symbols"] = self._sorted_unique_strings(
                positions.keys()
            )
        except Exception as exc:
            self._halt_reconciliation = True
            self.oms.reduce_only = True
            self.kill_switch.trip("alpaca_paper_startup_sync_failed")
            artifact["status"] = "failed"
            artifact["error"] = str(exc)
            artifact["error_type"] = type(exc).__name__
            artifact["reduce_only"] = True
            artifact["halt_reconciliation"] = True
            artifact["kill_switch_reason"] = "alpaca_paper_startup_sync_failed"
            artifact_path = self._write_startup_sync_artifact(artifact)
            self._audit_runtime_event(
                "paper_broker_adapter_startup_sync_failed",
                {
                    "error": str(exc),
                    "artifact_path": artifact_path,
                    "paper_adapter_contract": contract,
                    "reduce_only": True,
                    "halt_reconciliation": True,
                },
            )
            raise RuntimeError(f"alpaca_paper_startup_sync_failed: {exc}") from exc

        artifact["status"] = "ok"
        artifact["reduce_only"] = bool(self.oms.reduce_only)
        artifact["halt_reconciliation"] = self._halt_reconciliation
        artifact_path = self._write_startup_sync_artifact(artifact)
        self._audit_runtime_event(
            "paper_broker_adapter_startup_sync_complete",
            {
                "artifact_path": artifact_path,
                "paper_adapter_contract": contract,
                "poll_order_count": len(polled_orders),
                "sync_fill_count": len(synced_fills),
                "synced_order_ids": polled_order_ids,
                "account_id": account.account_id,
                "position_count": len(positions),
                "position_symbols": artifact["sync"]["sync_positions"]["symbols"],
            },
        )

    def _paper_adapter_contract(self) -> dict[str, object]:
        env_requested = (
            os.environ.get("QUANT_ENABLE_ALPACA_PAPER_ADAPTER", "").lower()
            in {"1", "true", "yes"}
        )
        credential_audit = self._paper_credential_audit()
        if self._alpaca_paper_requested():
            credentials_present, credential_reason = self._has_apca_paper_credentials()
            approved_evidence, evidence_reason = self._has_paper_entry_evidence()
        else:
            credentials_present = True
            credential_reason = "ok"
            approved_evidence = True
            evidence_reason = "ok"
        return evaluate_paper_adapter_contract(
            self.config.paper_broker,
            adapter_enabled=self._alpaca_paper_adapter_enabled(),
            adapter_factory_present=self._alpaca_paper_adapter_factory_present(),
            adapter_capabilities=self._alpaca_paper_adapter_capabilities(),
            env_requested=env_requested,
            endpoint_kind=str(credential_audit["endpoint_kind"]),
            base_url_valid=bool(credential_audit["base_url_valid"]),
            credentials_present=credentials_present,
            credential_reason=credential_reason,
            approved_evidence=approved_evidence,
            evidence_reason=evidence_reason,
            allowed_base_urls=tuple(credential_audit["allowed_base_urls"]),
        ).to_dict()

    def _paper_broker_backend(self) -> str:
        broker = getattr(self, "broker", None)
        broker_name = str(getattr(broker, "broker_name", ""))
        if broker_name.startswith("alpaca_paper"):
            return "alpaca_paper"
        return str(self._paper_adapter_contract()["effective_backend"])

    @staticmethod
    def _normalize_alpaca_base_url(base_url: str) -> str:
        return normalize_alpaca_base_url(base_url)

    @classmethod
    def _paper_endpoint_audit(cls) -> dict[str, Any]:
        return audit_apca_paper_credentials()

    @classmethod
    def _has_apca_paper_credentials(cls) -> tuple[bool, str]:
        if not (os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY")):
            return False, "apca_paper_credentials_missing"

        endpoint_audit = cls._paper_endpoint_audit()
        if not endpoint_audit["base_url"]:
            return False, "apca_base_url_missing"
        if not endpoint_audit["base_url_valid"]:
            return False, "apca_base_url_not_allowed"

        return True, "ok"

    @classmethod
    def _paper_credential_audit(cls) -> dict[str, Any]:
        return cls._paper_endpoint_audit()

    def _has_paper_entry_evidence(self) -> tuple[bool, str]:
        if self.config.promotion_manifest_id:
            return False, "promotion_manifest_id_not_registry_source"

        review_path = self._paper_review_path()
        try:
            evidence = project_saved_paper_review_evidence(
                self.config.promotion_data_root,
                paper_review_id=self.config.paper_review_id,
                paper_review_path=str(review_path or ""),
            )
        except Exception as exc:
            return False, f"paper_review_registry_error:{exc}"
        if not evidence.get("allowed"):
            return False, str(evidence.get("reason", "paper_review_evidence_missing"))
        return True, "ok"

    def _paper_review_path(self) -> Path | None:
        if self.config.paper_review_path:
            return Path(self.config.paper_review_path)
        if not self.config.paper_review_id:
            return None
        return (
            Path(self.config.promotion_data_root)
            / "research"
            / "paper_reviews"
            / self.config.paper_review_id
            / "review.json"
        )

    @staticmethod
    def _reduce_only_projected_positions(account: AccountState | None) -> dict[str, float] | None:
        if account is None:
            return None
        return {
            symbol: float(position.quantity)
            for symbol, position in account.positions.items()
        }

    @staticmethod
    def _intent_quantity_delta(intent: OrderIntent) -> float:
        return intent.quantity if intent.side == OrderSide.BUY else -intent.quantity

    @classmethod
    def _apply_reduce_only_projection(
        cls,
        intent: OrderIntent,
        projected_positions: dict[str, float] | None,
    ) -> None:
        if projected_positions is None:
            return
        projected_qty = projected_positions.get(intent.symbol, 0.0) + cls._intent_quantity_delta(intent)
        if abs(projected_qty) <= 1e-9:
            projected_positions.pop(intent.symbol, None)
        else:
            projected_positions[intent.symbol] = projected_qty

    @classmethod
    def _reduce_only_allows(
        cls,
        intent: OrderIntent,
        account: AccountState | None,
        *,
        projected_positions: dict[str, float] | None = None,
    ) -> tuple[bool, str]:
        if account is None and projected_positions is None:
            return False, "reduce_only_account_required"
        if projected_positions is not None:
            current_qty = projected_positions.get(intent.symbol, 0.0)
        else:
            position = account.positions.get(intent.symbol) if account is not None else None
            current_qty = position.quantity if position else 0.0
        delta = cls._intent_quantity_delta(intent)
        projected_qty = current_qty + delta

        if abs(current_qty) <= 1e-9:
            return False, "reduce_only_no_existing_position"
        if current_qty > 0 and (projected_qty < -1e-9 or projected_qty > current_qty + 1e-9):
            return False, "reduce_only_would_increase_or_reverse_long"
        if current_qty < 0 and (projected_qty > 1e-9 or projected_qty < current_qty - 1e-9):
            return False, "reduce_only_would_increase_or_reverse_short"
        return True, "ok"

    @staticmethod
    def _sorted_unique_strings(values: Any) -> list[str]:
        result: set[str] = set()
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                result.add(text)
        return sorted(result)

    def _startup_sync_artifact_path(self) -> Path:
        return Path(self.config.ledger_root) / "audit" / "paper_broker_adapter_startup_sync.json"

    def _write_startup_sync_artifact(self, artifact: dict[str, Any]) -> str:
        artifact_path = self._startup_sync_artifact_path()
        payload = dict(artifact)
        payload["timestamp_utc"] = utc_now().isoformat()
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        return str(artifact_path)

    def _audit_runtime_event(self, event: str, details: dict[str, Any]) -> None:
        adapter_contract = self._paper_adapter_contract()
        broker_backend = self._paper_broker_backend()
        entry = {
            "timestamp_utc": utc_now().isoformat(),
            "event": event,
            "mode": "paper",
            "runtime_mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "paper_broker": self.config.paper_broker,
            "broker_backend": broker_backend,
            "real_order_submission": False,
            "paper_order_submission": bool(self.config.submit_orders),
            "adapter_contract": adapter_contract,
            "strategy_id": self.config.strategy_id,
            "details": details,
        }
        self.audit_events.append(entry)

        audit_path = Path(self.config.audit_log_path) if self.config.audit_log_path else (
            Path(self.config.ledger_root) / "paper_runtime_audit.jsonl"
        )
        try:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            _logger.exception("Failed to write PaperRuntime audit event %s", event)
