"""Paper runtime: orchestrates the full daily paper trading cycle.

PaperRuntime is responsible for the intraday live loop:
  bootstrap -> run market session -> session close -> shutdown

It stays separated from LiveRunner (which is for real broker execution)
and from PaperTradingLoop (which is a one-day batch processor).
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import subprocess
import time as _time
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from quant_shared.strategy_runtime import (
    JsonFileStrategyStateStore,
    StrategyDecisionCapability,
    StrategyRuntimeMode,
    StrategyStateStore,
)
from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.artifact_paths import serialize_durable_artifact_path
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.enums import OrderSide, OrderStatus, SessionName, TradingMode
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, OrderIntent, PortfolioSnapshot, Signal, TargetPosition, new_id
from quant_us.execution.fill_idempotency import (
    FillIdempotencyIndex,
    append_fill_idempotent,
)
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.ibkr_broker import (
    classify_ibkr_endpoint,
)
from quant_us.execution.ibkr_paper_execution_adapter import (
    IBKRPaperAdapterMode,
    IBKRPaperExecutionAdapter,
    IBKRPaperExecutionConfig,
)
from quant_us.live.paper_adapter_contract import (
    ALLOWED_ALPACA_PAPER_BASE_URLS,
    audit_apca_paper_credentials,
    evaluate_paper_adapter_contract,
    normalize_alpaca_base_url,
)
from quant_us.live.alpaca_paper_adapter import (
    ALPACA_PAPER_NETWORK_SUBMIT_ENV,
    AlpacaPaperBrokerAdapter,
)
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.market_data_loop import MarketDataLoop
from quant_us.live.ibkr_runtime_market_data import DEFAULT_SEMANTIC_CONTRACT_PATH
from quant_us.live.ibkr_recovery import IBKRRecoveryOrchestrator
from quant_us.live.ibkr_runtime_provider import (
    IBKRRuntimeProvider,
    RuntimeIncidentSink,
    get_ibkr_runtime_provider_registry,
)
from quant_us.live.ibkr_runtime_supervisor import IBKRRuntimeSupervisor
from quant_us.live.multi_timeframe_scheduler import MultiTimeframeDataStatus, MultiTimeframeMarketDataScheduler
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.live.session_clock import SessionClock
from quant_us.monitoring.daily_report import generate_daily_report, save_report
from quant_us.monitoring.telegram_alerts import AlertPriority, TelegramAlertService, load_telegram_config_from_env
from quant_us.portfolio.allocation import AllocationConfig, PortfolioAllocator
from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig
from quant_us.research.evidence_registry import project_saved_paper_review_evidence
from quant_us.risk.data_freshness import DataFreshnessConfig, DataFreshnessGuard
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.risk.risk_event_log import RiskEventLog
from quant_us.risk.runtime_guardian import RiskGuardian
from quant_us.strategies.base import Strategy, StrategyContext, build_strategy_context
from quant_us.strategies.decision_service import (
    AppliedStrategyDecision,
    StrategyDecisionService,
)

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
            "ibkr"/"ibkr_paper" requests an explicitly enabled, read-only
            IBKR paper adapter; the foundation never connects automatically
            and never submits or cancels orders.
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
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 4002
    ibkr_client_id: int = 1
    ibkr_adapter_mode: str = "disabled"
    ibkr_account_hash_allowlist: tuple[str, ...] = ()
    ibkr_connect_on_bootstrap: bool = False
    ibkr_market_data_start_on_bootstrap: bool = False
    ibkr_require_adjusted_warmup: bool = False
    ibkr_offline_replay: bool = False
    # Explicit opt-in for the integrated runtime supervisor/provider.  The
    # default keeps historical PaperRuntime sessions unchanged and the flag
    # is valid only for the controlled IBKR paper backend.
    ibkr_runtime_supervisor_enabled: bool = False
    ibkr_integration_receipt_path: str = ""
    ibkr_integration_ticket_id: str = "INTEGRATE-US-IBKR-REALTIME-PAPER-CLOSED-LOOP-01"
    ibkr_operator_paper_submit_authorized: bool = False
    ibkr_market_data_semantic_contract_path: str = str(DEFAULT_SEMANTIC_CONTRACT_PATH)
    bar_size: str = "1m"
    bar_sizes: list[str] = field(default_factory=list)
    multi_timeframe_require_all_fresh: bool = False
    risk_event_log_path: str = ""
    max_data_delay_seconds: float = 300.0
    promotion_manifest_id: str = ""
    paper_review_id: str = ""
    paper_review_path: str = ""
    promotion_data_root: str = "data"
    audit_log_path: str = ""
    reduce_only: bool = False
    explicit_paper_submit: bool = False
    portfolio_id: str = "portfolio"
    strategy_weights: dict[str, float] = field(default_factory=dict)
    portfolio_cash_reserve_weight: float = 0.05
    portfolio_max_symbol_weight: float = 0.10
    portfolio_max_gross_exposure: float = 0.95
    portfolio_max_daily_turnover: float = 1.0
    strategy_state_run_id: str = ""
    strategy_code_version: str = ""
    strategy_data_version: str = ""


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
_PAPER_SESSION_MANIFEST_ARTIFACT_VERSION = "paper_session_manifest_v1"
_PAPER_BROKER_STATE_RECOVERY_ARTIFACT_VERSION = "paper_broker_state_recovery_v1"


class _PaperRuntimeReconciler:
    """Adapt the existing four-way paper reconciliation service to the
    supervisor/recovery observation port without adding a second reconciler.
    """

    def __init__(self, runtime: "PaperRuntime") -> None:
        self.runtime = runtime

    def reconcile(self, snapshot: Any = None, **_: Any) -> dict[str, Any]:
        service = ReconciliationService(self.runtime.config.ledger_root, self.runtime.broker)
        report = service.reconcile_all(
            initial_cash=float(self.runtime.config.capital),
            telegram_alerts=None,
        )
        passed = str(report.status).lower() in {"clean", "pass", "passed", "ok"}
        blockers: list[str] = []
        if not passed:
            blockers.append("RECONCILIATION_FAILED")
            if report.position_diffs:
                blockers.append("POSITION_MISMATCH")
            if abs(float(report.cash_diff)) > 1e-6:
                blockers.append("CASH_MISMATCH")
            if report.order_diffs:
                blockers.append("ORDER_MISMATCH")
            if report.fill_diffs:
                blockers.append("FILL_MISMATCH")
        return {
            "status": "pass" if passed else "fail",
            "passed": passed,
            "reconciliation_status": "pass" if passed else "fail",
            "block_new_orders": not passed,
            "blockers": blockers,
            "report_path": str(report.report_path or ""),
        }


def _normalized_unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip().upper()
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return sorted(normalized)


def _normalized_unique_ids(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            normalized.append(text)
    return sorted(normalized, key=str.lower)


class PaperRuntime:
    """Orchestrates a paper trading session from bootstrap to shutdown.

    Typical usage::

        runtime = PaperRuntime(config)
        runtime.bootstrap(strategy=my_strategy)
        runtime.run_market_session()
        runtime.on_session_close()
        runtime.shutdown()
    """

    def __init__(
        self,
        config: PaperRuntimeConfig | None = None,
        *,
        ibkr_paper_client_factory: Callable[[], Any] | None = None,
        ibkr_paper_adapter_factory: Callable[[], Any] | None = None,
        ibkr_market_data_adapter_factory: Callable[[], Any] | None = None,
        runtime_head_resolver: Callable[[], str] | None = None,
        registered_main_head_resolver: Callable[[], str] | None = None,
        strategy_state_store: StrategyStateStore | None = None,
    ) -> None:
        self.config = config or PaperRuntimeConfig()
        self._ibkr_paper_client_factory = ibkr_paper_client_factory
        self._ibkr_paper_adapter_factory = ibkr_paper_adapter_factory
        self._ibkr_market_data_adapter_factory = ibkr_market_data_adapter_factory
        self._runtime_head_resolver = runtime_head_resolver or self._resolve_runtime_head
        self._registered_main_head_resolver = (
            registered_main_head_resolver or self._resolve_registered_main_head
        )
        self._strategy_code_version_cache = ""
        self.strategy_decision_service = StrategyDecisionService(
            strategy_state_store
            or JsonFileStrategyStateStore(
                Path(self.config.ledger_root) / "strategy_state_v1.json"
            )
        )
        self._bootstrapped: bool = False
        self._session_start: datetime | None = None
        self._poll_index: int = 0
        self._bars_cache: pd.DataFrame = _EMPTY_BARS_CACHE
        self._last_bar_timestamps: dict[tuple[str, str], datetime] = {}
        self.session_metrics: list[PaperSessionMetrics] = []
        self.metrics_log: list[PaperSessionMetrics] = []
        self.audit_events: list[dict[str, Any]] = []
        self._fill_index = FillIdempotencyIndex()
        self.session_id: str = new_id("paper_session")
        self._broker_state_recovery_cache: dict[str, Any] | None = None
        self._runtime_market_prices: dict[str, float] = {}
        self._broker_order_state_fingerprints: set[tuple[str, ...]] = set()
        self._last_reconciliation_summary: dict[str, Any] = {}
        self._ibkr_runtime_supervisor: IBKRRuntimeSupervisor | None = None
        self._ibkr_recovery_orchestrator: IBKRRecoveryOrchestrator | None = None
        self._ibkr_runtime_provider: IBKRRuntimeProvider | None = None
        self._ibkr_runtime_incident_manager: Any | None = None

        # Wired in bootstrap() — declared for type-checking
        self.calendar: USEquityCalendar
        self.session_clock: SessionClock
        self.kill_switch: KillSwitch
        self.risk_event_log: RiskEventLog | None = None
        self.broker: Any
        self.risk_engine: PreTradeRiskEngine
        self.oms: OrderManagementSystem
        self.ledger: JsonlLedgerStore
        self.data_loop: MarketDataLoop | MultiTimeframeMarketDataScheduler
        self.strategy: Strategy | None = None
        self.strategies: list[Strategy] = []
        self.data_freshness: DataFreshnessGuard
        self.alerts: TelegramAlertService
        self._halt_reconciliation: bool = False
        self._paper_entry_evidence_projection_cache: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def bootstrap(
        self,
        strategy: Strategy | Iterable[Strategy] | None = None,
    ) -> None:
        """Initialize every component needed for a paper trading session.

        Args:
            strategy: A ``Strategy`` instance, an iterable of strategies, or
                      ``None``.  ``None`` skips signal generation (data-
                      collection-only mode).
        """
        if self._bootstrapped:
            _logger.warning("PaperRuntime already bootstrapped; resetting.")
            self.shutdown()

        self.session_id = new_id("paper_session")
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
        self._sync_ibkr_execution_updates(stage="startup")
        self._recover_or_verify_broker_state()
        self._last_bar_timestamps = self._load_bar_watermarks()

        # Strategy
        self.strategy, self.strategies = self._normalize_strategies(strategy)
        self._validate_strategy_broker_isolation()

        # Market data loop.  IBKR runtime data is an explicitly injected,
        # SDK-neutral adapter and never falls back to Yahoo.
        bar_sizes = self._configured_bar_sizes()
        if self._ibkr_paper_requested():
            if self._ibkr_market_data_adapter_factory is None:
                raise RuntimeError("ibkr_runtime_market_data_factory_required")
            self.data_loop = self._ibkr_market_data_adapter_factory()
            if str(getattr(self.data_loop, "vendor", "")).lower() != "ibkr":
                raise RuntimeError("ibkr_runtime_market_data_source_must_be_ibkr")
            if str(getattr(self.data_loop, "bar_size", "")).lower() != bar_sizes[0]:
                raise RuntimeError("ibkr_runtime_market_data_bar_size_mismatch")
            if self.config.ibkr_market_data_start_on_bootstrap:
                starter = getattr(self.data_loop, "start", None)
                if not callable(starter):
                    raise RuntimeError("ibkr_runtime_market_data_start_surface_required")
                start_status = starter()
                if isinstance(start_status, dict) and start_status.get("blockers"):
                    raise RuntimeError(
                        "ibkr_runtime_market_data_start_blocked:"
                        + ";".join(str(value) for value in start_status["blockers"])
                    )
        elif len(bar_sizes) > 1:
            self.data_loop = MultiTimeframeMarketDataScheduler(
                symbols=self.config.symbols,
                vendor=self.config.data_vendor,
                bar_sizes=bar_sizes,
                poll_interval_seconds=self.config.poll_interval_seconds,
                data_root=self.config.data_root,
            )
        else:
            self.data_loop = MarketDataLoop(
                symbols=self.config.symbols,
                vendor=self.config.data_vendor,
                bar_size=bar_sizes[0],
                poll_interval_seconds=self.config.poll_interval_seconds,
                data_root=self.config.data_root,
            )

        if self._ibkr_paper_requested():
            self._warmup_ibkr_strategies()

        self._configure_ibkr_runtime_control_plane()

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

        manifest_path = self._write_paper_session_manifest()
        self._audit_runtime_event(
            "paper_session_manifest_written",
            {
                "artifact_path": manifest_path,
                "session_id": self.session_id,
            },
        )

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
                self._sync_ibkr_execution_updates(stage="cycle_start")
                # 1. Fetch latest bars
                data_status = self.data_loop.run_once()
                data_allows_processing = self._data_status_allows_processing(data_status)
                metrics.bars_fetched = len(data_status.symbols_updated) if data_allows_processing else 0
                metrics.bars_stale += self._stale_timeframe_count(data_status)

                # 2. Validate freshness
                if not data_allows_processing:
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

                # 4. Process new bars as one portfolio batch so strategy
                # ordering cannot change the account state before allocation.
                self._process_bars(new_bars, metrics)

                # 5. Snapshot
                account = self.broker.get_account()
                self._sync_ibkr_execution_updates(stage="cycle_end")
                snapshot = self._broker_snapshot(utc_now())
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

        self._sync_ibkr_execution_updates(stage="session_close")
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
            report_path = save_report(report, Path(self.config.ledger_root) / "daily_reports")
            attribution_path, attribution = self._write_strategy_attribution_report(today)
            self._augment_daily_report_with_attribution(
                report_path,
                attribution_path=attribution_path,
                attribution=attribution,
            )
        except Exception:
            _logger.exception("Failed to generate daily report on session close")

        if self._ibkr_paper_requested():
            self._write_ibkr_closed_loop_receipt()

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

        if self._paper_broker_backend() == "ibkr_paper":
            stop_market_data = getattr(getattr(self, "data_loop", None), "stop", None)
            if callable(stop_market_data):
                try:
                    stop_market_data()
                except Exception:
                    _logger.exception("Failed to stop injected IBKR market-data transport")
            disconnect = getattr(self.broker, "disconnect", None)
            if callable(disconnect):
                try:
                    disconnect()
                except Exception:
                    _logger.exception("Failed to disconnect injected IBKR paper adapter")

        if self._ibkr_runtime_provider is not None:
            get_ibkr_runtime_provider_registry().clear(self._ibkr_runtime_provider)
        self._ibkr_runtime_provider = None
        self._ibkr_runtime_supervisor = None
        self._ibkr_recovery_orchestrator = None
        self._ibkr_runtime_incident_manager = None

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

    def _configured_bar_sizes(self) -> list[str]:
        configured = list(self.config.bar_sizes) if self.config.bar_sizes else [self.config.bar_size]
        timeframes = self._configured_strategy_timeframes()
        configured.extend(timeframes.values())
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in configured:
            bar_size = str(raw or "").strip().lower()
            if not bar_size or bar_size in seen:
                continue
            seen.add(bar_size)
            normalized.append(bar_size)
        return normalized or ["1m"]

    def _configured_strategy_timeframes(self) -> dict[str, str]:
        timeframes: dict[str, str] = {}
        for strategy in getattr(self, "strategies", []):
            raw = getattr(strategy, "timeframes", None)
            if isinstance(raw, dict):
                for strategy_id, timeframe in raw.items():
                    value = str(timeframe or "").strip().lower()
                    if strategy_id and value:
                        timeframes[str(strategy_id)] = value
        return timeframes

    @staticmethod
    def _bar_size_rank(bar_size: str) -> int:
        raw = str(bar_size or "").lower()
        if raw.endswith("m"):
            try:
                return int(raw[:-1])
            except ValueError:
                return 10_000
        if raw.endswith("h"):
            try:
                return int(raw[:-1]) * 60
            except ValueError:
                return 10_000
        if raw.endswith("d"):
            return 1440
        return 10_000

    @staticmethod
    def _stale_timeframe_count(data_status: Any) -> int:
        if not isinstance(data_status, MultiTimeframeDataStatus):
            return 0
        return len(data_status.stale_timeframes)

    def _data_status_allows_processing(self, data_status: Any) -> bool:
        if not isinstance(data_status, MultiTimeframeDataStatus):
            return bool(data_status.fresh)
        if self.config.multi_timeframe_require_all_fresh:
            return data_status.all_fresh
        return bool(data_status.fresh_timeframes)

    def _warmup_ibkr_strategies(self) -> None:
        fetcher = getattr(self.data_loop, "fetch_warmup_bars", None)
        if not callable(fetcher):
            if self.config.ibkr_require_adjusted_warmup and self.strategies:
                raise RuntimeError("ibkr_adjusted_warmup_surface_required")
            return
        frame = fetcher()
        if not isinstance(frame, pd.DataFrame):
            frame = pd.DataFrame(frame)
        if frame.empty:
            if self.config.ibkr_require_adjusted_warmup and self.strategies:
                raise RuntimeError("ibkr_adjusted_warmup_not_ready")
            return
        required = {
            "timestamp_utc",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "adjusted",
            "semantic_parity_verified",
        }
        if not required.issubset(frame.columns):
            raise RuntimeError("ibkr_adjusted_warmup_contract_invalid")
        if not bool(frame["adjusted"].all()) or not bool(frame["semantic_parity_verified"].all()):
            raise RuntimeError("ibkr_adjusted_warmup_semantics_unverified")
        account = self.broker.get_account()
        discarded_signals = 0
        warmup_count = 0
        for _, row in frame.sort_values(["timestamp_utc", "symbol"]).iterrows():
            timestamp = ensure_utc(pd.Timestamp(row["timestamp_utc"]).to_pydatetime())
            bar = Bar(
                timestamp_utc=timestamp,
                symbol=str(row["symbol"]).upper(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                source=str(row.get("source", "IBKR_ADJUSTED_LAST_WARMUP")),
                bar_size="1d",
            )
            self._update_runtime_market(bar)
            prices = self._current_market_prices()
            for active_strategy in self.strategies:
                strategy_id = self._strategy_identifier(active_strategy)
                context = self._strategy_context_for_bar(
                    strategy=active_strategy,
                    bar=bar,
                    runtime_mode=StrategyRuntimeMode.WARMUP,
                    account=account,
                    market_prices=prices,
                    parameters={
                        "paper_session_id": self.session_id,
                        "strategy_id": strategy_id,
                        "warmup_source": "ibkr_adjusted_warmup",
                        "orders_forbidden": True,
                    },
                )
                decision = self._decide_strategy(
                    active_strategy,
                    MarketEvent.from_bar(bar),
                    context,
                )
                discarded_signals += len(decision.signals)
            key = self._bar_watermark_key("1d", bar.symbol)
            current = self._last_bar_timestamps.get(key)
            if current is None or timestamp > current:
                self._last_bar_timestamps[key] = timestamp
            warmup_count += 1
        self._save_bar_watermarks()
        self._audit_runtime_event(
            "ibkr_adjusted_warmup_loaded",
            {
                "bar_count": warmup_count,
                "discarded_signal_count": discarded_signals,
                "orders_forbidden": True,
                "source": "IBKR_ADJUSTED_LAST",
            },
        )

    def _fresh_timeframes_from_last_status(self) -> set[str] | None:
        status = getattr(self.data_loop, "last_status", None)
        if not isinstance(status, MultiTimeframeDataStatus):
            return None
        return set(status.fresh_timeframes)

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
        fresh_timeframes = self._fresh_timeframes_from_last_status()
        for _, row in latest_bars.iterrows():
            symbol = str(row.get("symbol", "")).upper()
            ts_raw = row.get("timestamp_utc")
            if not symbol or ts_raw is None:
                continue
            ts = ensure_utc(pd.Timestamp(ts_raw).to_pydatetime())
            bar_size = str(row.get("bar_size") or self.config.bar_size or "1m").lower()
            if fresh_timeframes is not None and bar_size not in fresh_timeframes:
                continue
            key = (bar_size, symbol)
            last_ts = self._last_bar_timestamps.get(key)
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
                    bar_size=bar_size,
                )
            )

        return sorted(new, key=lambda bar: (bar.timestamp_utc, self._bar_size_rank(bar.bar_size), bar.symbol))

    def _group_bars_by_timestamp(self, bars: list[Bar]) -> list[tuple[datetime, list[Bar]]]:
        grouped: dict[datetime, list[Bar]] = {}
        for bar in sorted(bars, key=lambda item: (item.timestamp_utc, self._bar_size_rank(item.bar_size), item.symbol)):
            grouped.setdefault(bar.timestamp_utc, []).append(bar)
        return [(timestamp, grouped[timestamp]) for timestamp in sorted(grouped)]

    def _mark_bars_processed(self, bars: list[Bar]) -> None:
        changed = False
        for bar in bars:
            key = self._bar_watermark_key(bar.bar_size, bar.symbol)
            current = self._last_bar_timestamps.get(key)
            if current is None or bar.timestamp_utc > current:
                self._last_bar_timestamps[key] = bar.timestamp_utc
                changed = True
        if changed:
            self._save_bar_watermarks()

    @staticmethod
    def _bar_watermark_key(bar_size: str, symbol: str) -> tuple[str, str]:
        return (str(bar_size or "").lower(), str(symbol or "").upper())

    def _bar_watermark_path(self) -> Path:
        return Path(self.config.ledger_root) / "audit" / "paper_bar_watermarks.json"

    def _load_bar_watermarks(self) -> dict[tuple[str, str], datetime]:
        path = self._bar_watermark_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        if not isinstance(payload, dict):
            return {}
        raw_watermarks = payload.get("watermarks", {})
        if not isinstance(raw_watermarks, dict):
            return {}
        loaded: dict[tuple[str, str], datetime] = {}
        for raw_key, raw_timestamp in raw_watermarks.items():
            parts = str(raw_key).split("|", 1)
            if len(parts) != 2:
                continue
            try:
                loaded[(parts[0].lower(), parts[1].upper())] = ensure_utc(
                    pd.Timestamp(raw_timestamp).to_pydatetime()
                )
            except (TypeError, ValueError):
                continue
        return loaded

    def _save_bar_watermarks(self) -> None:
        path = self._bar_watermark_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "artifact_type": "paper_bar_watermarks",
            "artifact_version": "paper_bar_watermarks_v1",
            "session_id": self.session_id,
            "watermarks": {
                f"{bar_size}|{symbol}": timestamp.isoformat()
                for (bar_size, symbol), timestamp in sorted(self._last_bar_timestamps.items())
            },
        }
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    def _process_bar(self, bar: Bar, metrics: PaperSessionMetrics) -> None:
        """Process one bar through the same batch path used by live cycles."""
        self._process_bars([bar], metrics)

    def _process_bars(self, bars: list[Bar], metrics: PaperSessionMetrics) -> None:
        """Process bars in as-of order without exposing future prices."""
        for timestamp, group in self._group_bars_by_timestamp(bars):
            fresh_bars: list[Bar] = []
            for bar in group:
                freshness = self.data_freshness.evaluate_bar(bar)
                if not freshness.fresh:
                    metrics.bars_stale += 1
                    self.kill_switch.check_data_staleness(freshness.delay_seconds)
                    continue
                self._update_runtime_market(bar)
                fresh_bars.append(bar)

            if not fresh_bars:
                continue

            if not self.strategies:
                self._mark_bars_processed(fresh_bars)
                continue

            try:
                prices: dict[str, float] = self._current_market_prices()
                account = self.broker.get_account()
                signals: list[Signal] = []
                for active_strategy in self.strategies:
                    strategy_id = self._strategy_identifier(active_strategy)
                    for bar in fresh_bars:
                        event = MarketEvent.from_bar(bar)
                        context = self._strategy_context_for_bar(
                            strategy=active_strategy,
                            bar=bar,
                            runtime_mode=StrategyRuntimeMode.PAPER,
                            account=account,
                            market_prices=prices,
                            parameters={
                                "paper_session_id": self.session_id,
                                "strategy_id": strategy_id,
                                "strategy_timeframes": self._configured_strategy_timeframes(),
                                "bar_sizes": self._configured_bar_sizes(),
                            },
                        )
                        decision = self._decide_strategy(
                            active_strategy,
                            event,
                            context,
                        )
                        for raw_signal in decision.signals:
                            signal = self._normalize_strategy_signal(raw_signal, strategy_id, active_strategy)
                            signals.append(signal)
                            metrics.signals_generated += 1

                reduce_only_projection = None
                if self.config.reduce_only or getattr(self.oms, "reduce_only", False):
                    reduce_only_projection = self._reduce_only_projected_positions(account)

                self._handle_signals(
                    signals,
                    account,
                    prices,
                    fresh_bars[-1],
                    metrics,
                    reduce_only_projection=reduce_only_projection,
                )
                self._mark_bars_processed(fresh_bars)
            except Exception:
                symbols = ",".join(bar.symbol for bar in fresh_bars)
                _logger.exception("Error processing portfolio bar batch %s at %s", symbols, timestamp.isoformat())
                self.kill_switch.record_order_failure()

    def _handle_signals(
        self,
        signals: list[Signal],
        account: AccountState,
        prices: dict[str, float],
        bar: Bar,
        metrics: PaperSessionMetrics,
        reduce_only_projection: dict[str, float] | None = None,
    ) -> None:
        if not signals:
            return

        sizer = PercentOfEquitySizer(
            PositionSizerConfig(
                strategy_allocations=dict(self.config.strategy_weights),
                default_strategy_weight=0.1,
            )
        )
        sized: list[TargetPosition] = []
        for signal in signals:
            sized.extend(sizer.size([signal]))
        if not sized:
            return

        allocation = self._portfolio_allocator().allocate_targets(
            sized,
            account=account,
            prices=prices,
            run_id=self._paper_run_id(self.config.portfolio_id),
        )
        for decision in allocation.target_decisions:
            if decision.reasons:
                self._audit_runtime_event(
                    "paper_portfolio_allocation_adjusted",
                    {
                        "symbol": decision.symbol,
                        "raw_weight": decision.raw_weight,
                        "final_weight": decision.final_weight,
                        "strategies": list(decision.strategies),
                        "reasons": [reason.__dict__ for reason in decision.reasons],
                    },
                )

        signal_by_id = {signal.signal_id: signal for signal in signals}
        for intent in allocation.intents:
            source_signal = signal_by_id.get(intent.signal_id)
            self._handle_intent(
                intent,
                source_signal,
                account,
                prices,
                bar,
                metrics,
                reduce_only_projection=reduce_only_projection,
            )

    def _handle_signal(
        self,
        signal: Signal,
        account: AccountState,
        prices: dict[str, float],
        bar: Bar,
        metrics: PaperSessionMetrics,
        reduce_only_projection: dict[str, float] | None = None,
    ) -> None:
        """Compatibility wrapper for tests and narrow single-signal callers."""
        self._handle_signals(
            [signal],
            account,
            prices,
            bar,
            metrics,
            reduce_only_projection=reduce_only_projection,
        )

    def _handle_intent(
        self,
        raw_intent: OrderIntent,
        signal: Signal | None,
        account: AccountState,
        prices: dict[str, float],
        bar: Bar,
        metrics: PaperSessionMetrics,
        reduce_only_projection: dict[str, float] | None = None,
    ) -> None:
        intent = self._with_paper_attribution(raw_intent, signal)
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
            return

        if self._halt_reconciliation:
            metrics.intents_rejected += 1
            self._audit_runtime_event(
                "paper_order_rejected_reconciliation_halt",
                {
                    "reason": "reconciliation_not_clean",
                    "client_order_id": intent.client_order_id,
                    "symbol": intent.symbol,
                    "side": intent.side.value,
                    "quantity": intent.quantity,
                    "halt_reconciliation": True,
                },
            )
            _logger.warning(
                "Reconciliation halt rejected intent %s for %s",
                intent.client_order_id,
                intent.symbol,
            )
            return

        if not self.config.submit_orders:
            _logger.debug(
                "submit_orders=False; skipping submission of intent %s for %s",
                intent.order_intent_id,
                intent.symbol,
            )
            return

        reduce_only_active = self.config.reduce_only or getattr(self.oms, "reduce_only", False)
        # Classify the concrete intent independently of the global OMS mode.
        # A sell that reduces an existing long (or a buy that reduces an
        # existing short) must use the reduction permission even when
        # ``reduce_only`` is false; an opening/increasing/reversing intent
        # remains a normal new-order request.
        risk_reducing_intent = False
        reduction_reason = "reduce_only_account_required"
        if reduce_only_active or self._ibkr_runtime_supervisor is not None:
            if reduce_only_projection is None:
                reduce_only_projection = self._reduce_only_projected_positions(account)
            risk_reducing_intent, reduction_reason = self._reduce_only_allows(
                intent,
                account,
                projected_positions=reduce_only_projection,
            )
        if reduce_only_active and not risk_reducing_intent:
            metrics.intents_rejected += 1
            self._audit_runtime_event(
                "paper_order_rejected_reduce_only",
                {
                    "reason": reduction_reason,
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
                reduction_reason,
            )
            return

        # The integrated IBKR control plane is the final permission provider
        # immediately before OMS order construction.  It is deliberately
        # independent of the older paper submit gate: a stale/unknown
        # supervisor observation rejects the intent and cannot be interpreted
        # as a broker cancellation or a successful reduction.
        if self._ibkr_runtime_supervisor is not None:
            permission = (
                self._ibkr_runtime_supervisor.permission_evaluator.can_reduce_position()
                if risk_reducing_intent
                else self._ibkr_runtime_supervisor.permission_evaluator.can_submit_new_order()
            )
            if not permission:
                metrics.intents_rejected += 1
                decision = (
                    self._ibkr_runtime_supervisor.permission_evaluator.reduce_position_decision()
                    if risk_reducing_intent
                    else self._ibkr_runtime_supervisor.permission_evaluator.new_order_decision()
                )
                self._audit_runtime_event(
                    "paper_order_rejected_ibkr_runtime_permission",
                    {
                        "reason": decision.reason or "ibkr_runtime_permission_blocked",
                        "blockers": list(decision.blockers),
                        "client_order_id": intent.client_order_id,
                        "symbol": intent.symbol,
                        "side": intent.side.value,
                        "quantity": intent.quantity,
                    },
                )
                return

        allowed, reason, gate_checks = self._paper_submit_gate_allows(intent)
        if not allowed:
            metrics.intents_rejected += 1
            self._audit_runtime_event(
                "paper_order_rejected_submit_gate",
                {
                    "reason": reason,
                    "checks": gate_checks,
                    "client_order_id": intent.client_order_id,
                    "symbol": intent.symbol,
                    "side": intent.side.value,
                    "quantity": intent.quantity,
                },
            )
            _logger.warning(
                "Paper submit gate rejected intent %s for %s: %s",
                intent.client_order_id,
                intent.symbol,
                reason,
            )
            return

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

        if result.order:
            self.ledger.append_order(result.order)
        for fill in result.fills:
            attributed_fill = self._fill_with_attribution(
                fill,
                order=result.order,
                intent=intent,
            )
            fill_append = append_fill_idempotent(
                self.ledger,
                attributed_fill,
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

    def _normalize_strategies(
        self,
        strategy: Strategy | Iterable[Strategy] | None,
    ) -> tuple[Strategy | None, list[Strategy]]:
        if strategy is None:
            return None, []
        if isinstance(strategy, Strategy) or hasattr(strategy, "on_bar"):
            return strategy, [strategy]
        strategies = list(strategy)
        if not strategies:
            return None, []
        for item in strategies:
            if not hasattr(item, "on_bar"):
                raise TypeError(f"PaperRuntime strategy must expose on_bar(): {type(item).__name__}")
        return strategies[0], strategies

    def _validate_strategy_broker_isolation(self) -> None:
        for active_strategy in self.strategies:
            attributes = vars(active_strategy) if hasattr(active_strategy, "__dict__") else {}
            for name, value in attributes.items():
                if value is self.broker:
                    raise TypeError(
                        "paper_runtime_strategy_broker_reference_forbidden:"
                        f"{type(active_strategy).__name__}.{name}"
                    )

    def _configured_strategy_ids(self) -> list[str]:
        ids: list[str] = []
        if self.config.strategy_id:
            ids.append(self.config.strategy_id)
        for strategy_id in self.config.strategy_weights:
            if strategy_id and strategy_id not in ids:
                ids.append(strategy_id)
        for strategy in getattr(self, "strategies", []):
            strategy_id = self._strategy_identifier(strategy)
            if strategy_id and strategy_id not in ids:
                ids.append(strategy_id)
        return ids

    def _strategy_manifest_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for strategy in getattr(self, "strategies", []):
            specs = getattr(strategy, "specs", None)
            if specs:
                for spec in specs:
                    entries.append(
                        {
                            "strategy_id": str(getattr(spec, "strategy_id", "")),
                            "version": "",
                            "class": type(strategy).__name__,
                            "weight": float(getattr(spec, "weight", 1.0)),
                            "timeframe": str(getattr(spec, "timeframe", "")),
                        }
                    )
                continue
            entries.append(
                {
                    "strategy_id": self._strategy_identifier(strategy),
                    "version": str(getattr(strategy, "version", "")),
                    "class": type(strategy).__name__,
                }
            )
        return entries

    def _strategy_identifier(self, strategy: Strategy | None) -> str:
        if strategy is None:
            return self.config.strategy_id
        return str(getattr(strategy, "strategy_id", "") or self.config.strategy_id)

    def _paper_run_id(self, strategy_id: str) -> str:
        suffix = strategy_id or "unattributed"
        return f"paper_runtime_{self.session_id}_{suffix}"

    def _strategy_state_run_id(self) -> str:
        configured = str(self.config.strategy_state_run_id or "").strip()
        if configured:
            return configured
        return f"paper_runtime_state_{self.config.portfolio_id or 'portfolio'}"

    def _strategy_code_version(self) -> str:
        configured = str(self.config.strategy_code_version or "").strip()
        if configured:
            return configured
        if self._strategy_code_version_cache:
            return self._strategy_code_version_cache
        try:
            resolved = str(self._runtime_head_resolver() or "").strip()
        except Exception:
            resolved = ""
        self._strategy_code_version_cache = resolved or "unbound_code"
        return self._strategy_code_version_cache

    def _strategy_data_version(self, bar: Bar) -> str:
        return (
            str(self.config.strategy_data_version or "").strip()
            or str(self.config.promotion_manifest_id or "").strip()
            or str(bar.source or "").strip()
            or f"runtime_vendor_{self.config.data_vendor}"
        )

    def _strategy_context_for_bar(
        self,
        *,
        strategy: Strategy,
        bar: Bar,
        runtime_mode: StrategyRuntimeMode,
        account: AccountState | None,
        market_prices: dict[str, float],
        parameters: dict[str, Any],
    ) -> StrategyContext:
        return build_strategy_context(
            run_id=self._strategy_state_run_id(),
            strategy_id=self._strategy_identifier(strategy),
            strategy_version=str(getattr(strategy, "version", "") or "unbound_strategy_version"),
            code_version=self._strategy_code_version(),
            data_version=self._strategy_data_version(bar),
            runtime_mode=runtime_mode,
            event_time=bar.timestamp_utc,
            decision_time=bar.timestamp_utc,
            available_time=bar.timestamp_utc,
            account=account,
            market_prices=market_prices,
            universe=sorted(market_prices),
            parameters={
                **parameters,
                "event_availability_semantics": "completed_bar_close",
            },
            capabilities=(StrategyDecisionCapability.SIGNAL,),
        )

    def _decide_strategy(
        self,
        strategy: Strategy,
        event: MarketEvent,
        context: StrategyContext,
    ) -> AppliedStrategyDecision:
        decision = self.strategy_decision_service.decide(strategy, event, context)
        if decision.duplicate:
            self._audit_runtime_event(
                "strategy_decision_duplicate_suppressed",
                {
                    "run_id": decision.context.identity.run_id,
                    "strategy_id": decision.context.identity.strategy_id,
                    "revision": decision.state.revision,
                    "state_digest": decision.state.digest,
                    "decision_id": decision.state.last_decision_id,
                    "runtime_mode": decision.context.clock.mode.value,
                },
            )
        elif decision.state.revision != decision.context.state.revision:
            self._audit_runtime_event(
                "strategy_state_transition_applied",
                {
                    "run_id": decision.context.identity.run_id,
                    "strategy_id": decision.context.identity.strategy_id,
                    "state_schema_version": decision.state.schema_version,
                    "previous_revision": decision.context.state.revision,
                    "revision": decision.state.revision,
                    "state_digest": decision.state.digest,
                    "runtime_mode": decision.context.clock.mode.value,
                },
            )
        return decision

    def _normalize_strategy_signal(
        self,
        signal: Signal,
        strategy_id: str,
        strategy: Strategy | None = None,
    ) -> Signal:
        if not isinstance(signal, Signal):
            raise TypeError(f"Strategy emitted non-Signal object: {type(signal).__name__}")
        if not signal.strategy_id:
            return replace(signal, strategy_id=strategy_id)
        child_ids = self._strategy_child_ids(strategy)
        if strategy_id and signal.strategy_id != strategy_id and signal.strategy_id not in child_ids:
            self._audit_runtime_event(
                "paper_strategy_signal_attribution_mismatch",
                {
                    "strategy_id": strategy_id,
                    "signal_strategy_id": signal.strategy_id,
                    "signal_id": signal.signal_id,
                    "symbol": signal.symbol,
                },
            )
        return signal

    @staticmethod
    def _strategy_child_ids(strategy: Strategy | None) -> set[str]:
        specs = getattr(strategy, "specs", None)
        if not specs:
            return set()
        return {
            str(getattr(spec, "strategy_id", ""))
            for spec in specs
            if getattr(spec, "strategy_id", "")
        }

    def _portfolio_allocator(self) -> PortfolioAllocator:
        return PortfolioAllocator(
            AllocationConfig(
                max_symbol_weight=self.config.portfolio_max_symbol_weight,
                cash_reserve_weight=self.config.portfolio_cash_reserve_weight,
                max_gross_exposure=self.config.portfolio_max_gross_exposure,
                max_daily_turnover=self.config.portfolio_max_daily_turnover,
                strategy_weights=dict(self.config.strategy_weights),
            )
        )

    def _with_paper_attribution(self, intent: Any, signal: Signal | None) -> Any:
        metadata = dict(getattr(intent, "metadata", {}) or {})
        signal_metadata = dict(getattr(signal, "metadata", {}) or {}) if signal is not None else {}
        for key in ("bar_size", "strategy_timeframe"):
            if key in signal_metadata:
                metadata.setdefault(key, signal_metadata[key])
        metadata.update(
            {
                "paper_session_id": self.session_id,
                "runtime_mode": "paper",
                "strategy_id": intent.strategy_id,
                "signal_id": signal.signal_id if signal is not None else intent.signal_id,
            }
        )
        return replace(intent, metadata=metadata)

    def _fill_with_attribution(
        self,
        fill: Any,
        *,
        order: Any | None,
        intent: Any,
    ) -> dict[str, Any]:
        if isinstance(fill, dict):
            record = dict(fill)
        elif is_dataclass(fill):
            record = asdict(fill)
        else:
            record = {
                name: getattr(fill, name)
                for name in (
                    "order_id",
                    "symbol",
                    "side",
                    "quantity",
                    "price",
                    "commission",
                    "filled_at",
                    "broker",
                    "broker_order_id",
                    "fill_id",
                )
                if hasattr(fill, name)
            }

        record.setdefault("order_id", getattr(order, "order_id", getattr(intent, "order_id", "")))
        record["strategy_id"] = str(
            record.get("strategy_id")
            or getattr(order, "strategy_id", "")
            or getattr(intent, "strategy_id", "")
        )
        record["run_id"] = str(record.get("run_id") or getattr(order, "run_id", "") or getattr(intent, "run_id", ""))
        record["signal_id"] = str(
            record.get("signal_id")
            or getattr(order, "signal_id", "")
            or getattr(intent, "signal_id", "")
        )
        record["client_order_id"] = str(
            record.get("client_order_id")
            or getattr(order, "client_order_id", "")
            or getattr(intent, "client_order_id", "")
        )
        record["order_intent_id"] = str(record.get("order_intent_id") or getattr(intent, "order_intent_id", ""))
        record["target_position_id"] = str(
            record.get("target_position_id")
            or getattr(intent, "target_position_id", "")
        )
        metadata: dict[str, Any] = {}
        raw_metadata = record.get("metadata")
        if isinstance(raw_metadata, dict):
            metadata.update(raw_metadata)
        order_metadata = getattr(order, "metadata", {}) if order is not None else {}
        if isinstance(order_metadata, dict):
            metadata.update(order_metadata)
        intent_metadata = getattr(intent, "metadata", {})
        if isinstance(intent_metadata, dict):
            metadata.update(intent_metadata)
        record["metadata"] = metadata
        record["paper_session_id"] = self.session_id
        record["runtime_mode"] = "paper"
        return record

    def _write_strategy_attribution_report(
        self,
        report_date: date,
    ) -> tuple[str, dict[str, Any]]:
        attribution = self._strategy_attribution_summary(report_date)
        report_dir = Path(self.config.ledger_root) / "daily_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"strategy_attribution_{report_date.isoformat()}.json"
        path.write_text(
            json.dumps(attribution, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        return str(path), attribution

    def _augment_daily_report_with_attribution(
        self,
        report_path: Path,
        *,
        attribution_path: str,
        attribution: dict[str, Any],
    ) -> None:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        data["strategy_attribution_path"] = attribution_path
        data["strategy_attribution"] = attribution
        report_path.write_text(
            json.dumps(data, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )

    def _strategy_attribution_summary(self, report_date: date) -> dict[str, Any]:
        orders = [
            order
            for order in self.ledger.read_records("orders.jsonl")
            if self._record_belongs_to_current_session(order)
        ]
        order_attribution = {
            str(order.get("order_id", "")): {
                "strategy_id": str(order.get("strategy_id", "")),
                "run_id": str(order.get("run_id", "")),
                "signal_id": str(order.get("signal_id", "")),
                "client_order_id": str(order.get("client_order_id", "")),
                "metadata": order.get("metadata", {}),
            }
            for order in orders
            if order.get("order_id")
        }
        fills = [
            fill
            for fill in self.ledger.read_records("fills.jsonl")
            if self._record_belongs_to_current_session(fill)
            or str(fill.get("order_id", "")) in order_attribution
        ]
        by_strategy: dict[str, dict[str, Any]] = {}

        def bucket(strategy_id: str) -> dict[str, Any]:
            key = strategy_id or "unattributed"
            if key not in by_strategy:
                by_strategy[key] = {
                    "orders": 0.0,
                    "fills": 0.0,
                    "symbols": [],
                    "filled_quantity": 0.0,
                    "filled_notional": 0.0,
                    "commission": 0.0,
                    "client_order_ids": [],
                    "signal_ids": [],
                }
            return by_strategy[key]

        for order in orders:
            strategy_id = str(order.get("strategy_id", ""))
            metadata = order.get("metadata", {})
            shares = self._strategy_attribution_shares(metadata, strategy_id)
            for child_strategy_id, share in shares:
                summary = bucket(child_strategy_id)
                summary["orders"] += share
                symbol = str(order.get("symbol", ""))
                if symbol and symbol not in summary["symbols"]:
                    summary["symbols"].append(symbol)
                client_order_id = str(order.get("client_order_id", ""))
                if client_order_id and client_order_id not in summary["client_order_ids"]:
                    summary["client_order_ids"].append(client_order_id)
                signal_id = str(order.get("signal_id", ""))
                if signal_id and signal_id not in summary["signal_ids"]:
                    summary["signal_ids"].append(signal_id)

        for fill in fills:
            fallback = order_attribution.get(str(fill.get("order_id", "")), {})
            strategy_id = str(fill.get("strategy_id") or fallback.get("strategy_id", ""))
            metadata = fill.get("metadata") or fallback.get("metadata", {})
            shares = self._strategy_attribution_shares(metadata, strategy_id)
            symbol = str(fill.get("symbol", ""))
            quantity = float(fill.get("quantity", 0.0) or 0.0)
            price = float(fill.get("price", 0.0) or 0.0)
            commission = float(fill.get("commission", 0.0) or 0.0)
            client_order_id = str(fill.get("client_order_id") or fallback.get("client_order_id", ""))
            signal_id = str(fill.get("signal_id") or fallback.get("signal_id", ""))
            for child_strategy_id, share in shares:
                summary = bucket(child_strategy_id)
                summary["fills"] += share
                if symbol and symbol not in summary["symbols"]:
                    summary["symbols"].append(symbol)
                summary["filled_quantity"] += quantity * share
                summary["filled_notional"] += abs(quantity * price) * share
                summary["commission"] += commission * share
                if client_order_id and client_order_id not in summary["client_order_ids"]:
                    summary["client_order_ids"].append(client_order_id)
                if signal_id and signal_id not in summary["signal_ids"]:
                    summary["signal_ids"].append(signal_id)

        for summary in by_strategy.values():
            summary["symbols"] = sorted(summary["symbols"])
            summary["client_order_ids"] = sorted(summary["client_order_ids"])
            summary["signal_ids"] = sorted(summary["signal_ids"])
            summary["orders"] = round(float(summary["orders"]), 8)
            summary["fills"] = round(float(summary["fills"]), 8)
            summary["filled_quantity"] = round(float(summary["filled_quantity"]), 8)
            summary["filled_notional"] = round(float(summary["filled_notional"]), 8)
            summary["commission"] = round(float(summary["commission"]), 8)

        return {
            "artifact_type": "paper_strategy_attribution_report",
            "mode": "paper",
            "runtime_mode": "paper",
            "session_id": self.session_id,
            "report_date": report_date.isoformat(),
            "strategy_ids": self._configured_strategy_ids(),
            "by_strategy": dict(sorted(by_strategy.items())),
            "totals": {
                "orders": len(orders),
                "fills": len(fills),
                "strategies": len(by_strategy),
            },
        }

    def _record_belongs_to_current_session(self, record: dict[str, Any]) -> bool:
        if str(record.get("paper_session_id", "")) == self.session_id:
            return True
        metadata = record.get("metadata", {})
        return isinstance(metadata, dict) and str(metadata.get("paper_session_id", "")) == self.session_id

    @staticmethod
    def _strategy_attribution_shares(
        metadata: Any,
        fallback_strategy_id: str,
    ) -> list[tuple[str, float]]:
        if not isinstance(metadata, dict):
            return [(fallback_strategy_id or "unattributed", 1.0)]
        contributions = metadata.get("strategy_contributions")
        if not isinstance(contributions, list) or not contributions:
            return [(fallback_strategy_id or "unattributed", 1.0)]

        weighted: list[tuple[str, float]] = []
        for row in contributions:
            if not isinstance(row, dict):
                continue
            strategy_id = str(row.get("strategy_id", "") or "")
            if not strategy_id:
                continue
            weight = abs(float(row.get("weighted_weight", row.get("raw_weight", 0.0)) or 0.0))
            weighted.append((strategy_id, weight))
        if not weighted:
            return [(fallback_strategy_id or "unattributed", 1.0)]

        total = sum(weight for _, weight in weighted)
        if total <= 0:
            equal = 1.0 / len(weighted)
            return [(strategy_id, equal) for strategy_id, _ in weighted]
        return [(strategy_id, weight / total) for strategy_id, weight in weighted]

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def _update_runtime_market(self, bar: Bar) -> None:
        self._runtime_market_prices[bar.symbol] = float(bar.close)
        updater = getattr(self.broker, "update_market", None)
        if callable(updater):
            updater(bar)

    def _current_market_prices(self) -> dict[str, float]:
        broker_prices = getattr(self.broker, "market_prices", None)
        if isinstance(broker_prices, dict):
            prices = {str(key): float(value) for key, value in broker_prices.items()}
            prices.update(self._runtime_market_prices)
            return prices
        return dict(self._runtime_market_prices)

    def _broker_snapshot(self, timestamp_utc: datetime) -> PortfolioSnapshot:
        snapshotter = getattr(self.broker, "snapshot", None)
        if callable(snapshotter):
            return snapshotter(timestamp_utc)
        account = self.broker.get_account()
        positions = self.broker.get_positions()
        gross = sum(abs(float(position.market_value)) for position in positions.values())
        net = sum(float(position.market_value) for position in positions.values())
        return PortfolioSnapshot(
            timestamp_utc=timestamp_utc,
            equity=float(account.equity),
            cash=float(account.cash),
            gross_exposure=gross,
            net_exposure=net,
        )

    def _sync_ibkr_execution_updates(self, *, stage: str) -> dict[str, int]:
        if self._paper_broker_backend() != "ibkr_paper":
            return {"orders": 0, "fills": 0, "duplicates": 0}
        counts = {"orders": 0, "fills": 0, "duplicates": 0}
        try:
            orders = list(self.broker.poll_orders())
            fills = list(self.broker.sync_fills(None))
            for order in orders:
                fingerprint = (
                    str(getattr(order, "order_id", "")),
                    str(getattr(order, "client_order_id", "")),
                    str(getattr(order, "broker_order_id", "")),
                    str(getattr(getattr(order, "status", ""), "value", getattr(order, "status", ""))),
                    str(getattr(order, "metadata", {}).get("filled_quantity", "")),
                    str(getattr(order, "metadata", {}).get("remaining_quantity", "")),
                )
                if fingerprint in self._broker_order_state_fingerprints:
                    counts["duplicates"] += 1
                    continue
                self._broker_order_state_fingerprints.add(fingerprint)
                self.ledger.append_order(order)
                client_order_id = str(getattr(order, "client_order_id", ""))
                if client_order_id:
                    self.oms._client_order_ids.add(client_order_id)
                counts["orders"] += 1
            for fill in fills:
                result = append_fill_idempotent(
                    self.ledger,
                    fill,
                    index=self._fill_index,
                    logger=_logger,
                )
                if result.conflict:
                    self._halt_reconciliation = True
                    self.oms.reduce_only = True
                    self.kill_switch.trip("ibkr_duplicate_fill_conflict")
                    raise RuntimeError("ibkr_duplicate_fill_conflict")
                if result.appended:
                    counts["fills"] += 1
                else:
                    counts["duplicates"] += 1
        except Exception as exc:
            self._halt_reconciliation = True
            self.oms.reduce_only = True
            self.kill_switch.trip("ibkr_broker_sync_failed")
            self._audit_runtime_event(
                "ibkr_broker_execution_sync_failed",
                {"stage": stage, "error": str(exc), "halt_reconciliation": True},
            )
            raise
        self._audit_runtime_event(
            "ibkr_broker_execution_sync_complete",
            {"stage": stage, **counts},
        )
        return counts

    def _reconcile_or_start(self) -> None:
        """Run reconciliation at bootstrap. Block if breaks detected and
        ``kill_on_recon_fail`` is set."""
        service = ReconciliationService(self.config.ledger_root, self.broker)
        report = service.reconcile_all(
            initial_cash=self.config.capital,
        )
        self._last_reconciliation_summary = {
            "stage": "startup",
            "status": report.status,
            "cash_diff": float(report.cash_diff),
            "position_diff_count": len(report.position_diffs),
        }
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
        self._last_reconciliation_summary = {
            "stage": "session_close",
            "status": report.status,
            "cash_diff": float(report.cash_diff),
            "position_diff_count": len(report.position_diffs),
        }
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

    def _recover_or_verify_broker_state(self) -> None:
        service = ReconciliationService(self.config.ledger_root, self.broker)
        ledger_state = service.ledger_state_snapshot(self.config.capital)
        artifact: dict[str, Any] = {
            "artifact_type": "paper_broker_state_recovery",
            "artifact_version": _PAPER_BROKER_STATE_RECOVERY_ARTIFACT_VERSION,
            "mode": "paper",
            "runtime_mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "session_id": self.session_id,
            "paper_broker": self.config.paper_broker,
            "broker_backend": self._paper_broker_backend(),
            "resume_detected": bool(ledger_state["has_state"]),
            "operationally_complete": False,
            "broker_state_restored": False,
            "broker_state_verified": False,
            "ledger_state": self._ledger_state_summary(ledger_state),
        }

        if not ledger_state["has_state"]:
            artifact["status"] = "verified"
            artifact["reason"] = "clean_start"
            artifact["operationally_complete"] = True
            artifact["broker_state_verified"] = True
            artifact["broker_state"] = self._account_positions_summary(
                self.broker.get_account(),
                self.broker.get_positions(),
            )
            artifact_path = self._write_broker_state_recovery_artifact(artifact)
            self._broker_state_recovery_cache = {
                "status": "verified",
                "artifact_path": artifact_path,
                "resume_detected": False,
                "operationally_complete": True,
                "broker_state_restored": False,
                "broker_state_verified": True,
                "reason": "clean_start",
            }
            self._audit_runtime_event(
                "paper_broker_state_recovery_complete",
                {
                    "artifact_path": artifact_path,
                    "status": "verified",
                    "resume_detected": False,
                    "reason": "clean_start",
                },
            )
            return

        try:
            if self._paper_broker_backend() == "simulated":
                service.restore_simulated_broker_state(self.config.capital)
                broker_account = self.broker.get_account()
                broker_positions = self.broker.get_positions()
                comparison = service.compare_cash_and_positions(
                    expected_cash=float(ledger_state["cash"]),
                    expected_positions=ledger_state["positions"],
                    broker_account=broker_account,
                    broker_positions=broker_positions,
                )
                if not comparison["matched"]:
                    raise RuntimeError("simulated_broker_restore_mismatch")
                artifact["status"] = "restored"
                artifact["broker_state_restored"] = True
                artifact["broker_state_verified"] = True
                artifact["comparison"] = comparison
                artifact["broker_state"] = self._account_positions_summary(
                    broker_account,
                    broker_positions,
                )
            else:
                synced_account = self._broker_sync_account()
                synced_positions = self._broker_sync_positions()
                ledger_comparison = service.compare_cash_and_positions(
                    expected_cash=float(ledger_state["cash"]),
                    expected_positions=ledger_state["positions"],
                    broker_account=synced_account,
                    broker_positions=synced_positions,
                )
                if not ledger_comparison["matched"]:
                    raise RuntimeError("broker_state_mismatch_vs_ledger")
                local_account = self.broker.get_account()
                local_positions = self.broker.get_positions()
                local_visibility = service.compare_cash_and_positions(
                    expected_cash=float(synced_account.cash),
                    expected_positions=synced_positions,
                    broker_account=local_account,
                    broker_positions=local_positions,
                )
                if not local_visibility["matched"]:
                    raise RuntimeError("broker_state_sync_not_visible_locally")
                artifact["status"] = "verified"
                artifact["broker_state_verified"] = True
                artifact["comparison"] = ledger_comparison
                artifact["local_visibility"] = local_visibility
                artifact["broker_state"] = self._account_positions_summary(
                    synced_account,
                    synced_positions,
                )
                artifact["local_broker_state"] = self._account_positions_summary(
                    local_account,
                    local_positions,
                )
            artifact["operationally_complete"] = True
        except Exception as exc:
            self._halt_reconciliation = True
            self.oms.reduce_only = True
            self.kill_switch.trip("paper_broker_state_recovery_failed")
            artifact["status"] = "failed"
            artifact["error"] = str(exc)
            artifact["error_type"] = type(exc).__name__
            artifact["operationally_complete"] = False
            artifact["reduce_only"] = True
            artifact["halt_reconciliation"] = True
            artifact["kill_switch_reason"] = "paper_broker_state_recovery_failed"
            artifact_path = self._write_broker_state_recovery_artifact(artifact)
            self._broker_state_recovery_cache = {
                "status": "failed",
                "artifact_path": artifact_path,
                "resume_detected": True,
                "operationally_complete": False,
                "broker_state_restored": bool(artifact["broker_state_restored"]),
                "broker_state_verified": bool(artifact["broker_state_verified"]),
                "reason": str(exc),
            }
            self._audit_runtime_event(
                "paper_broker_state_recovery_failed",
                {
                    "artifact_path": artifact_path,
                    "error": str(exc),
                    "reduce_only": True,
                    "halt_reconciliation": True,
                },
            )
            raise RuntimeError(f"paper_broker_state_recovery_failed: {exc}") from exc

        artifact["reduce_only"] = bool(self.oms.reduce_only)
        artifact["halt_reconciliation"] = self._halt_reconciliation
        artifact_path = self._write_broker_state_recovery_artifact(artifact)
        self._broker_state_recovery_cache = {
            "status": str(artifact["status"]),
            "artifact_path": artifact_path,
            "resume_detected": True,
            "operationally_complete": True,
            "broker_state_restored": bool(artifact["broker_state_restored"]),
            "broker_state_verified": bool(artifact["broker_state_verified"]),
        }
        self._audit_runtime_event(
            "paper_broker_state_recovery_complete",
            {
                "artifact_path": artifact_path,
                "status": artifact["status"],
                "resume_detected": True,
                "broker_state_restored": artifact["broker_state_restored"],
                "broker_state_verified": artifact["broker_state_verified"],
            },
        )

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
            "ibkr_paper_requested": self._ibkr_paper_requested(),
            "ibkr_paper_adapter_enabled": bool(
                adapter_contract.get("adapter_enabled", False)
                and self._ibkr_paper_requested()
            ),
            "ibkr_runtime_supervisor_enabled": bool(
                self.config.ibkr_runtime_supervisor_enabled
            ),
            "paper_credentials_present": True,
            "paper_review_or_promotion_evidence": True,
            "paper_review_readiness": self._paper_review_readiness_summary(),
            "paper_adapter_contract": adapter_contract,
            "paper_credential_audit": credential_audit,
        }

        def add_reason(reason: str) -> None:
            if reason and reason not in reasons:
                reasons.append(reason)

        if self.config.allow_live_orders:
            add_reason("paper_runtime_cannot_allow_live_orders")
        if self.config.ibkr_runtime_supervisor_enabled and not self._ibkr_paper_requested():
            add_reason("ibkr_runtime_supervisor_requires_ibkr_paper")

        if paper_broker not in {"simulated", "alpaca", "ibkr", "ibkr_paper"}:
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

        if self._ibkr_paper_requested():
            if str(adapter_contract.get("endpoint_kind", "")) != "paper":
                add_reason(str(adapter_contract.get("reason", "ibkr_paper_port_not_allowed")))
            if not bool(adapter_contract.get("adapter_ready", False)):
                add_reason(str(adapter_contract.get("reason", "ibkr_paper_adapter_not_ready")))
            try:
                adapter_mode = IBKRPaperAdapterMode(
                    str(self.config.ibkr_adapter_mode).lower().replace("_", "-")
                )
            except ValueError:
                adapter_mode = IBKRPaperAdapterMode.DISABLED
                add_reason("ibkr_paper_adapter_mode_not_supported")
            checks["ibkr_adapter_mode"] = adapter_mode.value
            checks["ibkr_market_data_factory_present"] = callable(
                self._ibkr_market_data_adapter_factory
            )
            checks["ibkr_runtime_source_is_ibkr"] = self.config.data_vendor.lower() == "ibkr"
            checks["ibkr_offline_replay"] = bool(self.config.ibkr_offline_replay)
            if adapter_mode is IBKRPaperAdapterMode.DISABLED:
                add_reason("ibkr_paper_adapter_disabled_fail_closed")
            if not checks["ibkr_market_data_factory_present"]:
                add_reason("ibkr_runtime_market_data_factory_required")
            if not checks["ibkr_runtime_source_is_ibkr"]:
                add_reason("ibkr_runtime_yahoo_or_non_ibkr_source_forbidden")
            if self._configured_bar_sizes() != ["1d"]:
                add_reason("ibkr_frozen_candidate_requires_1d_completed_bars")
            if (self.config.submit_orders or self.config.explicit_paper_submit) and (
                adapter_mode is not IBKRPaperAdapterMode.PAPER_SUBMIT
            ):
                add_reason("ibkr_paper_submit_mode_required")

        return {"ok": not reasons, "checks": checks, "reasons": reasons}

    def _alpaca_paper_requested(self) -> bool:
        return self.config.paper_broker.lower() == "alpaca"

    def _ibkr_paper_requested(self) -> bool:
        return self.config.paper_broker.lower() in {"ibkr", "ibkr_paper"}

    def _configure_ibkr_runtime_control_plane(self) -> None:
        """Wire the optional supervisor, recovery, guardian and read model.

        Construction is opt-in and restricted to the IBKR paper backend.  A
        real adapter is never auto-connected here; ``IBKRRuntimeSupervisor``
        consumes only the adapter's already-published observations and keeps
        all permissions fail-closed until every invariant is proven.
        """

        if not bool(self.config.ibkr_runtime_supervisor_enabled):
            return
        if not self._ibkr_paper_requested():
            raise RuntimeError("ibkr_runtime_supervisor_requires_ibkr_paper")

        from quant_us.monitoring.runtime_incidents import RuntimeIncidentManager

        incident_path = Path(self.config.ledger_root) / "runtime_incidents.jsonl"
        incident_manager = RuntimeIncidentManager(incident_path)
        incident_sink = RuntimeIncidentSink(incident_manager)
        reconciler = _PaperRuntimeReconciler(self)
        guardian = RiskGuardian()
        supervisor = IBKRRuntimeSupervisor(
            broker_adapter=self.broker,
            ledger=self.ledger,
            reconciler=reconciler,
            incident_sink=incident_sink,
            risk_guardian=guardian,
        )
        recovery = IBKRRecoveryOrchestrator(
            broker_adapter=self.broker,
            ledger=self.ledger,
            reconciler=reconciler,
            incident_sink=incident_sink,
        )
        provider = IBKRRuntimeProvider(
            supervisor,
            broker=self.broker,
            incident_store=incident_manager.store,
            market_data=getattr(self, "data_loop", None),
            oms=self.oms,
            kill_switch=self.kill_switch,
        )

        self._ibkr_runtime_incident_manager = incident_manager
        self._ibkr_runtime_supervisor = supervisor
        self._ibkr_recovery_orchestrator = recovery
        self._ibkr_runtime_provider = provider
        get_ibkr_runtime_provider_registry().register(provider)

        # This call is observation-only for a real adapter.  Offline replay
        # fixtures may connect by explicit attestation; no private/order/live
        # endpoint is reachable through the supervisor.
        supervisor.start(reason="paper_runtime_control_plane_start")

    @staticmethod
    def _alpaca_paper_adapter_enabled() -> bool:
        return True

    @staticmethod
    def _alpaca_paper_adapter_factory_present() -> bool:
        return True

    @staticmethod
    def _alpaca_paper_adapter_capabilities() -> dict[str, bool]:
        return AlpacaPaperBrokerAdapter.contract_capabilities()

    @staticmethod
    def _ibkr_paper_adapter_enabled() -> bool:
        return True

    def _ibkr_paper_adapter_factory_present(self) -> bool:
        return callable(self._ibkr_paper_adapter_factory) or callable(
            self._ibkr_paper_client_factory
        )

    @staticmethod
    def _ibkr_paper_adapter_capabilities() -> dict[str, bool]:
        return IBKRPaperExecutionAdapter.contract_capabilities()

    def _create_alpaca_paper_broker(self) -> SimulatedBroker:
        return AlpacaPaperBrokerAdapter.from_env(
            os.environ,
            network_submit_requested=bool(
                self.config.submit_orders and self.config.explicit_paper_submit
            ),
        )

    def _create_ibkr_paper_broker(self) -> IBKRPaperExecutionAdapter:
        if self._ibkr_paper_adapter_factory is not None:
            broker = self._ibkr_paper_adapter_factory()
        else:
            if self._ibkr_paper_client_factory is None:
                raise RuntimeError("ibkr_paper_client_injection_required")
            client = self._ibkr_paper_client_factory()
            broker = IBKRPaperExecutionAdapter(
                IBKRPaperExecutionConfig(
                    mode=self.config.ibkr_adapter_mode,
                    host=self.config.ibkr_host,
                    port=self.config.ibkr_port,
                    client_id=self.config.ibkr_client_id,
                    account_hash_allowlist=tuple(self.config.ibkr_account_hash_allowlist),
                ),
                client=client,
            )
        if not isinstance(broker, IBKRPaperExecutionAdapter):
            raise TypeError("ibkr_paper_execution_adapter_required")
        if broker.config.port != self.config.ibkr_port:
            raise RuntimeError("ibkr_paper_adapter_port_mismatch")
        if self.config.ibkr_connect_on_bootstrap:
            broker.connect()
        return broker

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

        if contract["effective_backend"] == "ibkr_paper":
            try:
                broker = self._create_ibkr_paper_broker()
                self._validate_paper_adapter_surface(
                    broker,
                    required=self._ibkr_paper_adapter_capabilities(),
                )
            except Exception as exc:
                self._audit_runtime_event(
                    "paper_broker_adapter_factory_failed",
                    {
                        "error": str(exc),
                        "paper_adapter_contract": contract,
                    },
                )
                raise RuntimeError(f"ibkr_paper_adapter_factory_failed: {exc}") from exc

            self._audit_runtime_event(
                "paper_broker_adapter_activated",
                {
                    "paper_adapter_contract": contract,
                    "broker_name": getattr(broker, "broker_name", type(broker).__name__),
                    "connected": bool(
                        getattr(broker, "is_connected", False)()
                        if callable(getattr(broker, "is_connected", False))
                        else getattr(broker, "is_connected", False)
                    ),
                    "readonly": bool(getattr(broker, "is_readonly", False)),
                    "submit_capable": bool(getattr(broker, "is_paper_submit", False)),
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

    def _validate_paper_adapter_surface(
        self,
        broker: Any,
        *,
        required: dict[str, bool] | None = None,
    ) -> None:
        required = required or self._alpaca_paper_adapter_capabilities()
        missing = [
            name for name, enabled in required.items()
            if enabled and not hasattr(broker, name)
        ]
        if missing:
            raise TypeError(
                "alpaca_paper_adapter_surface_missing: " + ",".join(sorted(missing))
            )

    def _run_paper_adapter_startup_sync(self) -> None:
        if self._paper_broker_backend() not in {"alpaca_paper", "ibkr_paper"}:
            self._write_simulated_startup_sync_artifact()
            return

        contract = self._paper_adapter_contract()
        startup_sync_prefix = f"{contract['effective_backend']}_startup_sync"
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
            "readiness": {},
            "no_submit_proof": {
                "allowed_operations": [
                    "readiness_report",
                    "poll_orders",
                    "sync_fills",
                    "sync_account",
                    "sync_positions",
                ],
                "submit_order_invoked": False,
                "write_method_invoked": False,
                "write_method_names": [],
                "submit_order_wrapper_invoked": False,
                "submit_order_wrapper_blocked": False,
                "submit_order_wrapper_reason": "",
                "submit_order_wrapper_order_ids": [],
                "submit_order_guard_installed": False,
                "submit_order_guard_restored": False,
                "write_guard_methods": [],
                "write_guard_restored": False,
                "submit_call_count_available": self._broker_submit_call_count() is not None,
                "submit_call_count_before": self._broker_submit_call_count(),
                "submit_call_count_after": None,
                "submit_call_count_delta": None,
            },
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

        original_write_methods: dict[str, Any] = {}
        try:
            original_write_methods = self._install_startup_sync_write_guards(artifact)
            try:
                artifact["readiness"] = self.broker.readiness_report()

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
            finally:
                if original_write_methods:
                    self._restore_startup_sync_write_guards(
                        artifact,
                        original_write_methods,
                    )
                    original_write_methods = {}

            self._finalize_startup_sync_no_submit_proof(artifact)
            if not artifact["no_submit_proof"].get("submit_call_count_available", False):
                raise RuntimeError(f"{startup_sync_prefix}_submit_counter_unavailable")
            if artifact["no_submit_proof"]["submit_order_invoked"]:
                raise RuntimeError(f"{startup_sync_prefix}_submitted_order_fail_closed")
            if artifact["no_submit_proof"].get("write_method_invoked", False):
                raise RuntimeError(f"{startup_sync_prefix}_write_method_invoked")
        except Exception as exc:
            self._finalize_startup_sync_no_submit_proof(artifact)
            self._halt_reconciliation = True
            self.oms.reduce_only = True
            failure_reason = f"{startup_sync_prefix}_failed"
            self.kill_switch.trip(failure_reason)
            artifact["status"] = "failed"
            artifact["error"] = str(exc)
            artifact["error_type"] = type(exc).__name__
            artifact["reduce_only"] = True
            artifact["halt_reconciliation"] = True
            artifact["kill_switch_reason"] = failure_reason
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
            raise RuntimeError(f"{failure_reason}: {exc}") from exc

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

    def _write_simulated_startup_sync_artifact(self) -> None:
        artifact = {
            "artifact_type": "paper_broker_adapter_startup_sync",
            "artifact_version": _PAPER_STARTUP_SYNC_ARTIFACT_VERSION,
            "mode": "paper",
            "runtime_mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "paper_broker": self.config.paper_broker,
            "backend": "simulated",
            "broker_backend": "simulated",
            "real_order_submission": False,
            "paper_order_submission": bool(self.config.submit_orders),
            "status": "ok",
            "reason": "not_required_for_simulated_paper_backend",
            "required": False,
            "reduce_only": bool(getattr(self.oms, "reduce_only", False)),
            "halt_reconciliation": False,
            "no_submit": True,
            "no_submit_proof": {
                "required": False,
                "reason": "not_required_for_simulated_paper_backend",
                "submit_call_count_available": True,
                "submit_call_count_before": 0,
                "submit_call_count_after": 0,
                "submit_call_count_delta": 0,
                "submit_order_invoked": False,
                "write_method_invoked": False,
                "write_method_names": [],
            },
            "sync": {
                "poll_orders": {
                    "required": False,
                    "call_count": 0,
                    "order_count": 0,
                    "order_ids": [],
                },
                "sync_fills": {
                    "required": False,
                    "call_count": 0,
                    "fill_count": 0,
                    "fill_ids": [],
                    "order_ids": [],
                    "requested_order_ids": [],
                },
                "sync_account": {
                    "required": False,
                    "call_count": 0,
                    "account_id": "",
                },
                "sync_positions": {
                    "required": False,
                    "call_count": 0,
                    "position_count": 0,
                    "symbols": [],
                },
            },
        }
        artifact_path = self._write_startup_sync_artifact(artifact)
        self._audit_runtime_event(
            "paper_broker_adapter_startup_sync_not_required",
            {
                "artifact_path": artifact_path,
                "broker_backend": "simulated",
                "no_submit": True,
            },
        )

    def _paper_adapter_contract(self) -> dict[str, object]:
        if self._ibkr_paper_requested():
            env_requested = (
                os.environ.get("QUANT_ENABLE_IBKR_PAPER_ADAPTER", "").lower()
                in {"1", "true", "yes"}
            )
            endpoint_kind = classify_ibkr_endpoint(self.config.ibkr_port)
            evaluated = evaluate_paper_adapter_contract(
                self.config.paper_broker,
                adapter_enabled=self._ibkr_paper_adapter_enabled(),
                adapter_factory_present=self._ibkr_paper_adapter_factory_present(),
                adapter_capabilities=self._ibkr_paper_adapter_capabilities(),
                env_requested=env_requested,
                endpoint_kind=endpoint_kind,
                base_url_valid=endpoint_kind == "paper",
                credentials_present=False,
                approved_evidence=False,
                allowed_base_urls=(),
                ibkr_host=self.config.ibkr_host,
                ibkr_port=self.config.ibkr_port,
            ).to_dict()
            try:
                mode = IBKRPaperAdapterMode(
                    str(self.config.ibkr_adapter_mode).lower().replace("_", "-")
                )
            except ValueError:
                mode = IBKRPaperAdapterMode.DISABLED
            evaluated["adapter_mode"] = mode.value
            evaluated["readonly"] = mode is IBKRPaperAdapterMode.READONLY
            evaluated["submit_capable"] = mode is IBKRPaperAdapterMode.PAPER_SUBMIT
            evaluated["cancel_capable"] = mode is IBKRPaperAdapterMode.PAPER_SUBMIT
            evaluated["offline_replay"] = bool(self.config.ibkr_offline_replay)
            evaluated["external_paper_submit_allowed"] = False
            evaluated["semantic_contract_path"] = self.config.ibkr_market_data_semantic_contract_path
            if mode is IBKRPaperAdapterMode.DISABLED:
                evaluated["adapter_ready"] = False
                evaluated["fail_closed"] = True
                evaluated["reason"] = "ibkr_paper_adapter_disabled_fail_closed"
            return evaluated

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
        if broker_name in {"ibkr", "ibkr_paper"}:
            return "ibkr_paper"
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
            self._paper_entry_evidence_projection_cache = None
            return False, "promotion_manifest_id_not_registry_source"
        cached = self._paper_entry_evidence_projection_cache
        if isinstance(cached, dict) and cached.get("allowed"):
            return True, "ok"

        try:
            evidence = self._paper_entry_evidence_projection()
        except Exception as exc:
            self._paper_entry_evidence_projection_cache = None
            return False, f"paper_review_registry_error:{exc}"
        self._paper_entry_evidence_projection_cache = dict(evidence)
        if not evidence.get("allowed"):
            return False, str(evidence.get("reason", "paper_review_evidence_missing"))
        return True, "ok"

    def _paper_submit_gate_allows(self, intent: OrderIntent) -> tuple[bool, str, dict[str, Any]]:
        """Final fail-closed gate before an Alpaca paper adapter submit call."""
        if self._paper_broker_backend() == "ibkr_paper":
            startup_sync = self._startup_sync_status()
            broker_state_recovery = self._broker_state_recovery_status()
            integration_receipt = self._ibkr_integration_receipt_status()
            market_data = self._ibkr_market_data_gate_status()
            readiness = self.broker.readiness_report()
            offline_client = self._ibkr_offline_replay_client_verified()
            offline_replay = bool(self.config.ibkr_offline_replay)
            checks = {
                "required": True,
                "broker_backend": "ibkr_paper",
                "paper_order_submission": bool(self.config.submit_orders),
                "explicit_paper_submit": bool(self.config.explicit_paper_submit),
                "allow_live_orders_false": not self.config.allow_live_orders,
                "real_order_submission": False,
                "adapter_mode": str(readiness.get("mode", "")),
                "account_verified": bool(readiness.get("account_verified", False)),
                "endpoint_kind": "paper" if self.config.ibkr_port in {4002, 7497} else "forbidden",
                "integration_receipt": integration_receipt,
                "market_data": market_data,
                "startup_sync_status": str(startup_sync.get("status", "")),
                "startup_sync_no_submit": bool(startup_sync.get("no_submit", False)),
                "broker_state_recovery_ok": bool(
                    broker_state_recovery.get("operationally_complete", False)
                ),
                "reconciliation_clean": not self._halt_reconciliation,
                "kill_switch_armed_and_clear": hasattr(self, "kill_switch")
                and not bool(getattr(self.kill_switch, "triggered", False)),
                "operator_paper_submit_authorized": bool(
                    self.config.ibkr_operator_paper_submit_authorized
                ),
                "offline_replay": offline_replay,
                "offline_replay_client_verified": offline_client,
                "external_paper_submit_allowed": False,
            }
            reasons: list[str] = []
            if not checks["paper_order_submission"]:
                reasons.append("submit_orders_false")
            if not checks["explicit_paper_submit"]:
                reasons.append("explicit_paper_submit_not_selected")
            if not checks["allow_live_orders_false"]:
                reasons.append("paper_runtime_cannot_allow_live_orders")
            if checks["adapter_mode"] != IBKRPaperAdapterMode.PAPER_SUBMIT.value:
                reasons.append("ibkr_paper_submit_mode_required")
            if not checks["account_verified"]:
                reasons.append("ibkr_paper_account_not_verified")
            if checks["endpoint_kind"] != "paper":
                reasons.append("ibkr_live_endpoint_forbidden")
            if startup_sync.get("status") != "ok" or not startup_sync.get("no_submit"):
                reasons.append("startup_sync_not_passed")
            if not checks["broker_state_recovery_ok"]:
                reasons.append("broker_state_recovery_not_ready")
            if not market_data.get("ok"):
                reasons.append(str(market_data.get("reason", "ibkr_market_data_not_ready")))
            if not checks["reconciliation_clean"]:
                reasons.append("reconciliation_not_clean")
            if not checks["kill_switch_armed_and_clear"]:
                reasons.append("kill_switch_not_armed_or_active")
            if offline_replay:
                if not offline_client:
                    reasons.append("ibkr_offline_replay_client_not_verified")
            else:
                if not integration_receipt.get("ok"):
                    reasons.append(
                        str(integration_receipt.get("reason", "ibkr_integration_receipt_missing"))
                    )
                if not checks["operator_paper_submit_authorized"]:
                    reasons.append("ibkr_operator_paper_submit_authorization_missing")
            if reasons:
                return False, ";".join(self._sorted_unique_strings(reasons)), checks
            return True, "ok_offline_replay" if offline_replay else "ok", checks
        if self._paper_broker_backend() != "alpaca_paper":
            return True, "not_required_for_simulated_paper_backend", {
                "required": False,
                "broker_backend": self._paper_broker_backend(),
            }

        startup_sync = self._startup_sync_status()
        broker_state_recovery = self._broker_state_recovery_status()
        registry_evidence = self._registry_evidence_summary()
        no_submit_proof = self._no_real_order_submission_proof(startup_sync)
        credentials_ok, credential_reason = self._has_apca_paper_credentials()
        credential_audit = self._paper_credential_audit()
        readiness = self.broker.readiness_report() if hasattr(self.broker, "readiness_report") else {}
        network_submit_confirmed = self._alpaca_paper_network_submit_confirmed()
        network_submit_enabled = bool(
            readiness.get("network_submit_enabled", network_submit_confirmed)
        )
        client_order_id = str(getattr(intent, "client_order_id", "") or "")
        recovered_ids = getattr(self.oms, "_client_order_ids", set())
        duplicate = client_order_id in recovered_ids
        reduce_only_active = bool(self.config.reduce_only or getattr(self.oms, "reduce_only", False))
        checks = {
            "required": True,
            "explicit_paper_submit": bool(self.config.explicit_paper_submit),
            "submit_orders": bool(self.config.submit_orders),
            "allow_live_orders_false": not self.config.allow_live_orders,
            "real_order_submission": False,
            "broker_backend": self._paper_broker_backend(),
            "paper_credentials_present": credentials_ok,
            "paper_credentials_reason": credential_reason,
            "paper_base_url_valid": bool(credential_audit.get("base_url_valid", False)),
            "paper_endpoint_kind": str(credential_audit.get("endpoint_kind", "unset")),
            "paper_allowed_base_urls": list(credential_audit.get("allowed_base_urls", [])),
            "paper_network_submit_confirmation": network_submit_confirmed,
            "paper_adapter_network_submit_enabled": network_submit_enabled,
            "paper_adapter_submit_blocked_reason": str(
                readiness.get("submit_blocked_reason", "")
            ),
            "registry_evidence_allowed": bool(registry_evidence.get("allowed")),
            "registry_evidence_reason": str(registry_evidence.get("reason", "")),
            "registry_evidence_id": str(registry_evidence.get("evidence_id", "")),
            "startup_sync_status": str(startup_sync.get("status", "")),
            "startup_sync_no_submit": bool(startup_sync.get("no_submit", False)),
            "startup_sync_submit_call_count_delta": startup_sync.get("submit_call_count_delta"),
            "broker_state_recovery_status": str(broker_state_recovery.get("status", "")),
            "broker_state_recovery_ok": bool(
                broker_state_recovery.get("operationally_complete", False)
            ),
            "no_real_order_submission_proof": no_submit_proof.get("status"),
            "oms_idempotency_ok": bool(client_order_id) and not duplicate,
            "reduce_only_active": reduce_only_active,
            "reduce_only_ok": True,
            "reconciliation_clean": not self._halt_reconciliation,
            "kill_switch_clear": not bool(getattr(self.kill_switch, "triggered", False)),
        }
        reasons: list[str] = []
        if not checks["explicit_paper_submit"]:
            reasons.append("explicit_paper_submit_not_selected")
        if not checks["submit_orders"]:
            reasons.append("submit_orders_false")
        if not checks["allow_live_orders_false"]:
            reasons.append("paper_runtime_cannot_allow_live_orders")
        if not credentials_ok:
            reasons.append(credential_reason)
        if not checks["paper_network_submit_confirmation"]:
            reasons.append("alpaca_paper_network_submit_confirmation_missing")
        if not checks["paper_adapter_network_submit_enabled"]:
            reasons.append(
                str(
                    readiness.get(
                        "submit_blocked_reason",
                        "alpaca_paper_network_submit_disabled_fail_closed",
                    )
                )
            )
        if not checks["registry_evidence_allowed"]:
            reasons.append(str(registry_evidence.get("reason", "paper_review_evidence_missing")))
        if startup_sync.get("status") != "ok" or not startup_sync.get("no_submit"):
            reasons.append("startup_sync_not_passed")
        if not checks["broker_state_recovery_ok"]:
            reasons.append("broker_state_recovery_not_ready")
        if no_submit_proof.get("status") != "PASS":
            reasons.append("no_real_order_submission_proof_failed")
        if not checks["oms_idempotency_ok"]:
            reasons.append("duplicate_client_order_id" if duplicate else "client_order_id_missing")
        if not checks["reconciliation_clean"]:
            reasons.append("reconciliation_not_clean")
        if not checks["kill_switch_clear"]:
            reasons.append("kill_switch_active")
        if reasons:
            return False, ";".join(reasons), checks
        return True, "ok", checks

    def _ibkr_market_data_gate_status(self) -> dict[str, Any]:
        data_loop = getattr(self, "data_loop", None)
        status = getattr(data_loop, "last_status", None)
        semantic_getter = getattr(data_loop, "semantic_gate_status", None)
        semantic = semantic_getter() if callable(semantic_getter) else {
            "ok": False,
            "blockers": ["ibkr_runtime_semantic_gate_surface_missing"],
        }
        expected_hash = ""
        contract_path = Path(self.config.ibkr_market_data_semantic_contract_path)
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            expected_hash = str(contract.get("contract_sha256", ""))
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "reason": "ibkr_semantic_contract_unreadable"}
        if status is None:
            return {
                "ok": False,
                "reason": "ibkr_market_data_status_missing",
                "semantic_contract_hash": expected_hash,
            }
        actual_hash = str(getattr(status, "semantic_contract_hash", ""))
        blockers = list(getattr(status, "blockers", []))
        blockers.extend(semantic.get("blockers", []))
        if str(getattr(status, "source", "")).lower() != "ibkr":
            blockers.append("ibkr_runtime_market_data_source_must_be_ibkr")
        if str(getattr(status, "market_data_type", "")) != "live":
            blockers.append("ibkr_runtime_market_data_type_must_be_live")
        if actual_hash != expected_hash:
            blockers.append("ibkr_market_data_semantic_contract_mismatch")
        blockers = self._sorted_unique_strings(blockers)
        ok = bool(getattr(status, "fresh", False)) and bool(semantic.get("ok")) and not blockers
        return {
            "ok": ok,
            "reason": "ok" if ok else (
                blockers[0] if blockers else "ibkr_market_data_semantic_contract_mismatch"
            ),
            "source": str(getattr(status, "source", "")),
            "market_data_type": str(getattr(status, "market_data_type", "")),
            "semantic_contract_hash": actual_hash,
            "expected_semantic_contract_hash": expected_hash,
            "blockers": blockers,
            "semantic_gate": semantic,
        }

    def _ibkr_offline_replay_client_verified(self) -> bool:
        client = getattr(self.broker, "_client", None)
        return bool(
            client is not None
            and getattr(client, "offline_replay", False) is True
            and getattr(client, "network_access", True) is False
        )

    def _ibkr_integration_receipt_status(self) -> dict[str, Any]:
        raw_path = str(self.config.ibkr_integration_receipt_path or "").strip()
        current_head = self._runtime_head_resolver()
        if not raw_path:
            return {
                "ok": False,
                "reason": "ibkr_integration_receipt_missing",
                "current_head": current_head,
            }
        repo_root = Path(__file__).resolve().parents[2]
        path = Path(raw_path).resolve()
        try:
            relative_path = path.relative_to(repo_root).as_posix()
        except ValueError:
            return {
                "ok": False,
                "reason": "ibkr_integration_receipt_outside_repo",
                "current_head": current_head,
            }
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if tracked.returncode != 0:
            return {
                "ok": False,
                "reason": "ibkr_integration_receipt_untracked",
                "current_head": current_head,
                "path": relative_path,
            }
        committed = subprocess.run(
            ["git", "show", f"{current_head}:{relative_path}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if committed.returncode != 0:
            return {
                "ok": False,
                "reason": "ibkr_integration_receipt_not_committed_at_current_head",
                "current_head": current_head,
                "path": relative_path,
            }
        worktree_diff = subprocess.run(
            ["git", "diff", "--quiet", current_head, "--", relative_path],
            cwd=repo_root,
            check=False,
        )
        if worktree_diff.returncode != 0:
            return {
                "ok": False,
                "reason": "ibkr_integration_receipt_worktree_blob_mismatch",
                "current_head": current_head,
                "path": relative_path,
            }
        try:
            payload = json.loads(committed.stdout.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {
                "ok": False,
                "reason": "ibkr_integration_receipt_unreadable",
                "current_head": current_head,
            }
        receipt_head = str(
            payload.get("integrated_head", "")
            or payload.get("integration_commit", "")
            or payload.get("deliverable_commit", "")
        )
        receipt_commit_result = subprocess.run(
            ["git", "log", "-1", "--format=%H", current_head, "--", relative_path],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        receipt_commit = (
            receipt_commit_result.stdout.strip()
            if receipt_commit_result.returncode == 0
            else ""
        )
        receipt_parent = ""
        if receipt_commit:
            receipt_parent_result = subprocess.run(
                ["git", "rev-parse", f"{receipt_commit}^1"],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if receipt_parent_result.returncode == 0:
                receipt_parent = receipt_parent_result.stdout.strip()
        head_binding_mode = self._ibkr_integration_receipt_head_binding_mode(
            receipt_head=receipt_head,
            current_head=current_head,
            receipt_commit=receipt_commit,
            receipt_parent=receipt_parent,
        )
        guardrails = payload.get("guardrails")
        reasons: list[str] = []
        if payload.get("schema_version") != "agent_handoff_envelope_v1":
            reasons.append("ibkr_integration_receipt_schema_mismatch")
        if payload.get("ticket_id") != self.config.ibkr_integration_ticket_id:
            reasons.append("ibkr_integration_receipt_ticket_mismatch")
        if payload.get("event_type") != "integrated":
            reasons.append("ibkr_integration_receipt_event_type_mismatch")
        if payload.get("producer_role") != "integrator":
            reasons.append("ibkr_integration_receipt_role_mismatch")
        if payload.get("domain") != "us_equity":
            reasons.append("ibkr_integration_receipt_domain_mismatch")
        if not head_binding_mode:
            reasons.append("ibkr_integration_receipt_head_mismatch")
        required_false = {
            "promotion_unlock_allowed",
            "paper_or_live_unlock_allowed",
            "private_endpoint_allowed",
            "order_endpoint_allowed",
            "real_order_submitted",
        }
        if not isinstance(guardrails, dict) or any(
            guardrails.get(name) is not False for name in required_false
        ):
            reasons.append("ibkr_integration_receipt_guardrails_invalid")
        reasons = self._sorted_unique_strings(reasons)
        ok = not reasons
        return {
            "ok": ok,
            "reason": "ok" if ok else reasons[0],
            "reasons": reasons,
            "path": relative_path,
            "current_head": current_head,
            "receipt_head": receipt_head,
            "receipt_commit": receipt_commit,
            "receipt_parent": receipt_parent,
            "head_binding_mode": head_binding_mode,
            "event_id": str(payload.get("event_id", "")),
            "ticket_id": str(payload.get("ticket_id", "")),
            "committed_blob_sha256": hashlib.sha256(committed.stdout).hexdigest(),
        }

    @staticmethod
    def _ibkr_integration_receipt_head_binding_mode(
        *,
        receipt_head: str,
        current_head: str,
        receipt_commit: str,
        receipt_parent: str,
    ) -> str:
        if receipt_head and receipt_head == current_head:
            return "direct_current_head"
        if (
            receipt_head
            and receipt_commit == current_head
            and receipt_parent == receipt_head
        ):
            return "current_envelope_parent"
        return ""

    @staticmethod
    def _resolve_runtime_head() -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    @staticmethod
    def _resolve_registered_main_head() -> str:
        result = subprocess.run(
            ["git", "rev-parse", "refs/heads/main"],
            cwd=Path(__file__).resolve().parents[2],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    @staticmethod
    def _alpaca_paper_network_submit_confirmed() -> bool:
        return os.environ.get(ALPACA_PAPER_NETWORK_SUBMIT_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    def _paper_entry_evidence_projection(self) -> dict[str, Any]:
        review_path = self._paper_review_path()
        projection = project_saved_paper_review_evidence(
            self.config.promotion_data_root,
            paper_review_id=self.config.paper_review_id,
            paper_review_path=str(review_path or ""),
        )
        if projection.get("allowed"):
            mismatch = self._paper_entry_evidence_config_mismatch(projection)
            if mismatch:
                projection = dict(projection)
                projection["allowed"] = False
                projection["reason"] = mismatch
        return projection

    def _paper_review_readiness_summary(
        self,
        projection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return read-only paper-review diagnostics for gate/API surfacing."""
        if not self._alpaca_paper_requested() and projection is None:
            return {
                "required": False,
                "allowed": True,
                "status": "NOT_REQUIRED",
                "manual_review_pending": False,
                "blocking_reasons": [],
                "checklist": {},
                "delisting_conditions": {},
            }

        try:
            cached = self._paper_entry_evidence_projection_cache
            evidence = (
                dict(projection)
                if projection is not None
                else dict(cached)
                if isinstance(cached, dict)
                else self._paper_entry_evidence_projection()
            )
        except Exception as exc:
            return {
                "required": True,
                "allowed": False,
                "status": "CONFLICT",
                "manual_review_pending": False,
                "blocking_reasons": [f"paper_review_registry_error:{exc}"],
                "checklist": self._paper_review_checklist("", "", {}, [f"paper_review_registry_error:{exc}"]),
                "delisting_conditions": {},
            }

        review = dict(evidence.get("review", {}))
        details = dict(review.get("details", {}))
        status = str(details.get("status") or review.get("summary") or "MISSING")
        evidence_pack_path = str(
            evidence.get("evidence_pack_path", "")
            or details.get("evidence_pack_path", "")
        )
        risk_envelope = details.get("proposed_risk_envelope", {})
        if not isinstance(risk_envelope, dict):
            risk_envelope = {}

        blocking_reasons = self._paper_review_blocking_reasons(evidence, details)
        return {
            "required": True,
            "allowed": bool(evidence.get("allowed", False)),
            "status": status,
            "manual_review_pending": status == "PENDING_HUMAN_REVIEW",
            "review_path": str(evidence.get("review_path", "") or review.get("path", "")),
            "evidence_pack_path": evidence_pack_path,
            "blocking_reasons": blocking_reasons,
            "delisting_conditions": risk_envelope.get("delisting_conditions", {}),
            "checklist": self._paper_review_checklist(
                status,
                evidence_pack_path,
                risk_envelope,
                blocking_reasons,
            ),
        }

    @staticmethod
    def _paper_review_blocking_reasons(
        evidence: dict[str, Any],
        details: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []

        def add(raw: Any) -> None:
            text = str(raw or "").strip()
            if text and text != "ok" and text not in reasons:
                reasons.append(text)

        add(evidence.get("reason", ""))
        for item in details.get("evidence_gate_blocking_reasons", []):
            add(item)
        return reasons

    def _paper_review_checklist(
        self,
        status: str,
        evidence_pack_path: str,
        risk_envelope: dict[str, Any],
        blocking_reasons: list[str],
    ) -> dict[str, Any]:
        manual_status = "PASS" if status == "APPROVED_FOR_PAPER_ONLY" else "PENDING"
        if status not in {"APPROVED_FOR_PAPER_ONLY", "PENDING_HUMAN_REVIEW"}:
            manual_status = "BLOCKED"

        pack_exists = bool(evidence_pack_path) and Path(evidence_pack_path).exists()
        return {
            "manual_review": {
                "status": manual_status,
                "required": True,
                "reason": "" if manual_status == "PASS" else f"paper_review_not_approved:{status or 'MISSING'}",
            },
            "portfolio_evidence_pack": {
                "status": "PRESENT" if pack_exists else "MISSING",
                "required": True,
                "path": evidence_pack_path,
            },
            "reconciliation": self._paper_review_required_check(
                "reconciliation",
                ("reconciliation", "ledger_reconciliation"),
                risk_envelope,
                blocking_reasons,
            ),
            "slippage": self._paper_review_required_check(
                "slippage",
                ("slippage", "slippage_bps", "max_slippage_bps", "slippage_model"),
                risk_envelope,
                blocking_reasons,
            ),
            "signal_drift": self._paper_review_required_check(
                "signal_drift",
                ("signal_drift", "signal drift", "drift"),
                risk_envelope,
                blocking_reasons,
            ),
            "delisting_conditions": self._paper_review_required_check(
                "delisting_conditions",
                ("delisting_conditions", "delisting", "downlist", "de_list"),
                risk_envelope,
                blocking_reasons,
            ),
        }

    def _paper_review_required_check(
        self,
        name: str,
        labels: tuple[str, ...],
        risk_envelope: dict[str, Any],
        blocking_reasons: list[str],
    ) -> dict[str, Any]:
        matched_blockers = [
            reason
            for reason in blocking_reasons
            if any(label in reason.lower() for label in labels)
        ]
        if matched_blockers:
            return {
                "status": "BLOCKED",
                "required": True,
                "blocking_reasons": matched_blockers,
            }
        if self._paper_review_envelope_mentions(risk_envelope, labels):
            return {
                "status": "PRESENT",
                "required": True,
                "blocking_reasons": [],
            }
        return {
            "status": "REVIEW_REQUIRED",
            "required": True,
            "blocking_reasons": [],
            "reason": f"{name}_review_item_not_recorded",
        }

    @classmethod
    def _paper_review_envelope_mentions(
        cls,
        value: Any,
        labels: tuple[str, ...],
    ) -> bool:
        if isinstance(value, dict):
            for key, nested in value.items():
                key_text = str(key).lower()
                if any(label in key_text for label in labels):
                    if nested not in ({}, [], "", None):
                        return True
                if cls._paper_review_envelope_mentions(nested, labels):
                    return True
        elif isinstance(value, list):
            return any(cls._paper_review_envelope_mentions(item, labels) for item in value)
        return False

    def _paper_entry_evidence_config_mismatch(self, projection: dict[str, Any]) -> str:
        review = dict(projection.get("review", {}))
        details = dict(review.get("details", {}))
        approved_strategy_id = str(
            review.get("strategy_manifest_id")
            or details.get("strategy_manifest_id")
            or ""
        ).strip()
        runtime_strategy_ids = _normalized_unique_ids(
            [
                self.config.strategy_id,
                *self.config.strategy_weights.keys(),
            ]
        )
        if approved_strategy_id and runtime_strategy_ids:
            approved_key = approved_strategy_id.lower()
            runtime_keys = {strategy_id.lower() for strategy_id in runtime_strategy_ids}
            if approved_key not in runtime_keys:
                return (
                    "paper_review_strategy_mismatch:"
                    f"approved={approved_strategy_id}:"
                    f"runtime={','.join(runtime_strategy_ids)}"
                )

        proposed_symbols = _normalized_unique_strings(details.get("proposed_symbols", []))
        runtime_symbols = _normalized_unique_strings(self.config.symbols)
        if proposed_symbols and runtime_symbols and proposed_symbols != runtime_symbols:
            return (
                "paper_review_symbols_mismatch:"
                f"approved={','.join(proposed_symbols)}:"
                f"runtime={','.join(runtime_symbols)}"
            )

        proposed_capital = float(details.get("proposed_capital", 0.0) or 0.0)
        if proposed_capital > 0 and float(self.config.capital) > proposed_capital + 1e-9:
            return (
                "paper_review_capital_exceeds_approved:"
                f"approved={proposed_capital:.2f}:"
                f"runtime={float(self.config.capital):.2f}"
            )

        risk_envelope = details.get("proposed_risk_envelope", {})
        if not isinstance(risk_envelope, dict):
            risk_envelope = {}
        approved_bar_sizes = _normalized_unique_strings(
            risk_envelope.get("bar_sizes", risk_envelope.get("timeframes", []))
        )
        runtime_bar_sizes = _normalized_unique_strings(
            self.config.bar_sizes or [self.config.bar_size]
        )
        if approved_bar_sizes and runtime_bar_sizes and approved_bar_sizes != runtime_bar_sizes:
            return (
                "paper_review_timeframes_mismatch:"
                f"approved={','.join(approved_bar_sizes)}:"
                f"runtime={','.join(runtime_bar_sizes)}"
            )
        return ""

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

    def _broker_state_recovery_artifact_path(self) -> Path:
        return Path(self.config.ledger_root) / "audit" / "paper_broker_state_recovery.json"

    def _paper_session_manifest_path(self) -> Path:
        return Path(self.config.ledger_root) / "audit" / "paper_session_manifest.json"

    def _paper_session_manifest_history_path(self, session_id: str | None = None) -> Path:
        session_name = session_id or self.session_id
        return (
            Path(self.config.ledger_root)
            / "audit"
            / "paper_session_manifests"
            / f"{session_name}.json"
        )

    def _ibkr_closed_loop_receipt_path(self) -> Path:
        return Path(self.config.ledger_root) / "audit" / "ibkr_paper_closed_loop_receipt.json"

    def _write_ibkr_closed_loop_receipt(self) -> str:
        current_head = self._runtime_head_resolver()
        registered_main_head = self._registered_main_head_resolver()
        market_data = self._ibkr_market_data_gate_status()
        readiness = self.broker.readiness_report()
        startup_sync = self._startup_sync_status()
        recovery = self._broker_state_recovery_status()
        integration = self._ibkr_integration_receipt_status()
        order_rows = self.ledger.read_records("orders.jsonl")
        fill_rows = self.ledger.read_records("fills.jsonl")
        broker_client = getattr(self.broker, "_client", None)
        offline_replay = bool(
            self.config.ibkr_offline_replay
            or getattr(broker_client, "offline_replay", False) is True
            or getattr(broker_client, "network_access", True) is False
        )
        broker_connected = bool(readiness.get("connected", False))
        gateway_connected = broker_connected and not offline_replay
        blockers = ["closed_loop_receipt_not_forward_observation"]
        if offline_replay:
            blockers.append("offline_fixture_never_counts_toward_forward_observation")
        if not current_head or current_head != registered_main_head:
            blockers.append("current_head_not_registered_main")
        if not integration.get("ok"):
            blockers.append(str(integration.get("reason", "independent_integration_required")))
        if not market_data.get("ok"):
            blockers.append(str(market_data.get("reason", "ibkr_market_data_not_ready")))
        if self._halt_reconciliation:
            blockers.append("reconciliation_not_clean")
        if not order_rows or not fill_rows:
            blockers.append("nonempty_paper_order_and_fill_sample_required")
        if not self.config.ibkr_operator_paper_submit_authorized:
            blockers.append("manual_paper_submit_authorization_required")
        payload: dict[str, Any] = {
            "schema_version": "us_ibkr_paper_closed_loop_receipt_v1",
            "ticket_id": "US-IBKR-REALTIME-PAPER-CLOSED-LOOP-01",
            "created_at_utc": utc_now().isoformat(),
            "current_head": current_head,
            "registered_main_head": registered_main_head,
            "current_head_fresh": bool(current_head) and current_head == registered_main_head,
            "session_id": self.session_id,
            "runtime": {
                "canonical_runtime": "PaperRuntime",
                "runtime_mode": "ibkr_paper",
                "adapter_mode": str(readiness.get("mode", "")),
                "offline_replay": offline_replay,
                "fixture": offline_replay,
                "connection_kind": (
                    "offline_replay" if offline_replay else "ibkr_gateway" if gateway_connected else "none"
                ),
                "startup_sync": startup_sync,
                "broker_state_recovery": recovery,
            },
            "market_data": market_data,
            "broker": {
                "adapter": str(readiness.get("adapter", "")),
                "account_hash": str(readiness.get("account_hash", "")),
                "connected": bool(readiness.get("connected", False)),
                "gateway_connected": gateway_connected,
                "paper_endpoint": self.config.ibkr_port in {4002, 7497},
                "submit_attempt_count": int(readiness.get("submit_attempt_count", 0)),
                "submit_call_count": int(readiness.get("submit_call_count", 0)),
                "cancel_attempt_count": int(readiness.get("cancel_attempt_count", 0)),
                "cancel_call_count": int(readiness.get("cancel_call_count", 0)),
                "global_cancel_capable": False,
            },
            "ledger": {
                "order_record_count": len(order_rows),
                "fill_record_count": len(fill_rows),
                "order_ledger_sha256": self.ledger.records_hash("orders.jsonl"),
                "fill_ledger_sha256": self.ledger.records_hash("fills.jsonl"),
                "state_derived_from_fills_cash_positions": True,
            },
            "reconciliation": dict(self._last_reconciliation_summary),
            "integration_receipt": integration,
            "counts_toward_30_day_window": False,
            "blockers": self._sorted_unique_strings(blockers),
            "safety_flags": {
                "paper_submit_allowed": False,
                "paper_cancel_allowed": False,
                "live_allowed": False,
                "promotion_allowed": False,
                "secrets_read": False,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        payload["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
        path = self._ibkr_closed_loop_receipt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, indent=2, default=str), encoding="utf-8")
        return self._durable_ledger_artifact_path(path)

    def _write_startup_sync_artifact(self, artifact: dict[str, Any]) -> str:
        artifact_path = self._startup_sync_artifact_path()
        payload = dict(artifact)
        payload["timestamp_utc"] = utc_now().isoformat()
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        return self._durable_ledger_artifact_path(artifact_path)

    def _write_broker_state_recovery_artifact(self, artifact: dict[str, Any]) -> str:
        artifact_path = self._broker_state_recovery_artifact_path()
        payload = dict(artifact)
        payload["timestamp_utc"] = utc_now().isoformat()
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        return self._durable_ledger_artifact_path(artifact_path)

    def _durable_ledger_artifact_path(self, artifact_path: Path) -> str:
        return serialize_durable_artifact_path(
            artifact_path,
            identity_root=self.config.ledger_root,
        )

    def _durable_promotion_artifact_path(self, artifact_path: str | Path) -> str:
        if not str(artifact_path or "").strip():
            return ""
        return serialize_durable_artifact_path(
            artifact_path,
            identity_root=self.config.promotion_data_root,
        )

    @staticmethod
    def _positions_summary(positions: dict[str, Any]) -> dict[str, dict[str, float]]:
        return {
            symbol: {
                "quantity": float(getattr(position, "quantity", 0.0)),
                "avg_price": float(getattr(position, "avg_price", 0.0)),
                "market_price": float(getattr(position, "market_price", 0.0)),
                "market_value": float(getattr(position, "market_value", 0.0)),
            }
            for symbol, position in sorted(positions.items())
        }

    def _ledger_state_summary(self, ledger_state: dict[str, Any]) -> dict[str, Any]:
        return {
            "has_state": bool(ledger_state.get("has_state", False)),
            "cash": float(ledger_state.get("cash", 0.0) or 0.0),
            "equity": float(ledger_state.get("equity", 0.0) or 0.0),
            "position_count": len(ledger_state.get("positions", {})),
            "positions": self._positions_summary(ledger_state.get("positions", {})),
            "order_count": int(ledger_state.get("order_count", 0) or 0),
            "fill_count": int(ledger_state.get("fill_count", 0) or 0),
            "snapshot_count": int(ledger_state.get("snapshot_count", 0) or 0),
        }

    def _account_positions_summary(
        self,
        account: AccountState,
        positions: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "cash": float(account.cash),
            "equity": float(account.equity),
            "position_count": len(positions),
            "positions": self._positions_summary(positions),
        }

    def _broker_sync_account(self) -> AccountState:
        sync_account = getattr(self.broker, "sync_account", None)
        if callable(sync_account):
            return sync_account()
        return self.broker.get_account()

    def _broker_sync_positions(self) -> dict[str, Any]:
        sync_positions = getattr(self.broker, "sync_positions", None)
        if callable(sync_positions):
            return sync_positions()
        return self.broker.get_positions()

    def _write_paper_session_manifest(self) -> str:
        manifest_path = self._paper_session_manifest_path()
        history_path = self._paper_session_manifest_history_path()
        created_at = utc_now().isoformat()
        startup_sync = self._startup_sync_status()
        broker_state_recovery = self._broker_state_recovery_status()
        registry_evidence = self._registry_evidence_summary()
        if self._alpaca_paper_requested() and not registry_evidence.get("allowed"):
            self._halt_reconciliation = True
            if hasattr(self, "oms"):
                self.oms.reduce_only = True
            if hasattr(self, "kill_switch"):
                self.kill_switch.trip("paper_session_manifest_evidence_not_allowed")
            reason = str(registry_evidence.get("reason", "paper_review_evidence_missing"))
            raise RuntimeError(f"paper_session_manifest_evidence_not_allowed:{reason}")
        no_real_order_submission_proof = self._no_real_order_submission_proof(startup_sync)
        manifest = {
            "artifact_type": "paper_session_manifest",
            "artifact_version": _PAPER_SESSION_MANIFEST_ARTIFACT_VERSION,
            "session_id": self.session_id,
            "mode": "paper",
            "runtime_mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "symbols": list(self.config.symbols),
            "strategy_id": self.config.strategy_id,
            "strategy_ids": self._configured_strategy_ids(),
            "strategies": self._strategy_manifest_entries(),
            "bar_sizes": self._configured_bar_sizes(),
            "strategy_timeframes": self._configured_strategy_timeframes(),
            "portfolio": {
                "portfolio_id": self.config.portfolio_id,
                "strategy_weights": dict(self.config.strategy_weights),
                "cash_reserve_weight": self.config.portfolio_cash_reserve_weight,
                "max_symbol_weight": self.config.portfolio_max_symbol_weight,
                "max_gross_exposure": self.config.portfolio_max_gross_exposure,
                "max_daily_turnover": self.config.portfolio_max_daily_turnover,
            },
            "paper_broker": self.config.paper_broker,
            "broker_backend": self._paper_broker_backend(),
            "submit_orders": bool(self.config.submit_orders),
            "explicit_paper_submit": bool(self.config.explicit_paper_submit),
            "allow_live_orders": bool(self.config.allow_live_orders),
            "registry_evidence_id": registry_evidence["evidence_id"],
            "registry_evidence_path": registry_evidence["path"],
            "registry_evidence": registry_evidence,
            "startup_sync_status": startup_sync,
            "broker_state_recovery_status": broker_state_recovery,
            "market_data_symbols_evidence": {
                "symbols": list(self.config.symbols),
                "source": self.config.data_vendor,
                "bar_size": self.config.bar_size,
                "bar_sizes": self._configured_bar_sizes(),
                "timeframes": self._configured_bar_sizes(),
                "strategy_timeframes": self._configured_strategy_timeframes(),
                "data_root": self.config.data_root,
                "cache_pattern": (
                    "raw/vendor={source}/asset_class=equity/"
                    "bar_size={bar_size}/symbol={symbol}/date=*.parquet"
                ),
            },
            "created_at": created_at,
            "artifact_path": self._durable_ledger_artifact_path(manifest_path),
            "history_artifact_path": self._durable_ledger_artifact_path(history_path),
            "no_real_order_submission_proof": no_real_order_submission_proof,
            "reduce_only": bool(getattr(self.oms, "reduce_only", False)),
            "halt_reconciliation": self._halt_reconciliation,
            "adapter_contract": self._paper_adapter_contract(),
        }
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(manifest, sort_keys=True, indent=2, default=str)
            history_path.write_text(
                payload,
                encoding="utf-8",
            )
            manifest_path.write_text(
                payload,
                encoding="utf-8",
            )
        except OSError as exc:
            self._halt_reconciliation = True
            if hasattr(self, "oms"):
                self.oms.reduce_only = True
            if hasattr(self, "kill_switch"):
                self.kill_switch.trip("paper_session_manifest_write_failed")
            raise RuntimeError(f"paper_session_manifest_write_failed: {exc}") from exc
        return self._durable_ledger_artifact_path(manifest_path)

    def _startup_sync_status(self) -> dict[str, Any]:
        if self._paper_broker_backend() not in {"alpaca_paper", "ibkr_paper"}:
            return {
                "status": "skipped",
                "artifact_path": "",
                "reason": "non_external_paper_backend",
                "no_submit": True,
            }

        artifact_path = self._startup_sync_artifact_path()
        if not artifact_path.exists():
            return {
                "status": "missing",
                "artifact_path": self._durable_ledger_artifact_path(artifact_path),
                "reason": "startup_sync_artifact_missing",
                "no_submit": False,
            }
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {
                "status": "conflict",
                "artifact_path": self._durable_ledger_artifact_path(artifact_path),
                "reason": f"startup_sync_artifact_unreadable:{exc}",
                "no_submit": False,
            }
        no_submit_proof = dict(artifact.get("no_submit_proof", {}))
        return {
            "status": str(artifact.get("status", "missing")),
            "artifact_path": self._durable_ledger_artifact_path(artifact_path),
            "backend": str(artifact.get("backend", "")),
            "contract_version": str(artifact.get("contract_version", "")),
            "no_submit": (
                bool(no_submit_proof.get("submit_call_count_available", False))
                and not bool(no_submit_proof.get("submit_order_invoked", True))
                and not bool(no_submit_proof.get("write_method_invoked", False))
            ),
            "submit_call_count_delta": no_submit_proof.get("submit_call_count_delta"),
            "submit_call_count_available": bool(no_submit_proof.get("submit_call_count_available", False)),
        }

    def _broker_state_recovery_status(self) -> dict[str, Any]:
        if isinstance(self._broker_state_recovery_cache, dict):
            return dict(self._broker_state_recovery_cache)

        artifact_path = self._broker_state_recovery_artifact_path()
        if not artifact_path.exists():
            return {
                "status": "missing",
                "artifact_path": self._durable_ledger_artifact_path(artifact_path),
                "resume_detected": False,
                "operationally_complete": False,
                "broker_state_restored": False,
                "broker_state_verified": False,
                "reason": "broker_state_recovery_artifact_missing",
            }

        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {
                "status": "conflict",
                "artifact_path": self._durable_ledger_artifact_path(artifact_path),
                "resume_detected": True,
                "operationally_complete": False,
                "broker_state_restored": False,
                "broker_state_verified": False,
                "reason": f"broker_state_recovery_artifact_unreadable:{exc}",
            }

        status = {
            "status": str(artifact.get("status", "missing")),
            "artifact_path": self._durable_ledger_artifact_path(artifact_path),
            "resume_detected": bool(artifact.get("resume_detected", False)),
            "operationally_complete": bool(artifact.get("operationally_complete", False)),
            "broker_state_restored": bool(artifact.get("broker_state_restored", False)),
            "broker_state_verified": bool(artifact.get("broker_state_verified", False)),
        }
        if artifact.get("error"):
            status["reason"] = str(artifact.get("error"))
        return status

    def _registry_evidence_summary(self) -> dict[str, Any]:
        registry_path = Path(self.config.promotion_data_root) / "research" / "evidence_registry.json"
        if not self._alpaca_paper_requested():
            return {
                "required": False,
                "allowed": True,
                "reason": "not_required_for_simulated_paper_backend",
                "evidence_id": "",
                "path": "",
                "evidence_pack_path": "",
                "registry_path": self._durable_promotion_artifact_path(registry_path),
                "registry_status": "not_required",
                "registry_integrity_status": "not_required",
            }

        evidence = (
            self._paper_entry_evidence_projection_cache
            if isinstance(self._paper_entry_evidence_projection_cache, dict)
            else None
        )
        if not evidence:
            evidence = self._paper_entry_evidence_projection()
        review = dict(evidence.get("review", {}))
        return {
            "required": True,
            "allowed": bool(evidence.get("allowed")),
            "reason": str(evidence.get("reason", "")),
            "evidence_id": str(
                review.get("evidence_id", "")
                or review.get("id", "")
                or self.config.paper_review_id
            ),
            "path": self._durable_promotion_artifact_path(
                evidence.get("review_path", "")
                or review.get("path", "")
                or self._paper_review_path()
                or ""
            ),
            "evidence_pack_path": self._durable_promotion_artifact_path(
                str(evidence.get("evidence_pack_path", ""))
            ),
            "registry_path": self._durable_promotion_artifact_path(registry_path),
            "registry_status": str(evidence.get("registry_status", "")),
            "registry_integrity_status": str(evidence.get("registry_integrity_status", "")),
            "registry_notes": list(evidence.get("registry_notes", [])),
            "paper_review_readiness": self._paper_review_readiness_summary(evidence),
        }

    def _no_real_order_submission_proof(self, startup_sync: dict[str, Any]) -> dict[str, Any]:
        startup_sync_no_submit = bool(startup_sync.get("no_submit", True))
        passed = (
            not bool(self.config.allow_live_orders)
            and startup_sync_no_submit
        )
        return {
            "status": "PASS" if passed else "FAIL",
            "mode": "paper",
            "canonical_runtime": "PaperRuntime",
            "allow_live_orders": bool(self.config.allow_live_orders),
            "real_order_submission": False,
            "real_broker_backend": False,
            "broker_backend": self._paper_broker_backend(),
            "startup_sync_no_submit": startup_sync_no_submit,
            "startup_sync_submit_call_count_delta": startup_sync.get("submit_call_count_delta"),
            "submit_orders": bool(self.config.submit_orders),
            "submit_order_path": "paper_only" if self.config.submit_orders else "disabled",
        }

    def _broker_submit_call_count(self) -> int | None:
        broker = getattr(self, "broker", None)
        for attr in ("submit_call_count", "submit_count"):
            value = getattr(broker, attr, None)
            if isinstance(value, int):
                return value
        return None

    def _finalize_startup_sync_no_submit_proof(self, artifact: dict[str, Any]) -> None:
        proof = dict(artifact.get("no_submit_proof", {}))
        wrapper_invoked = bool(proof.get("submit_order_wrapper_invoked", False))
        before = proof.get("submit_call_count_before")
        after = self._broker_submit_call_count()
        proof["submit_call_count_available"] = isinstance(before, int) and isinstance(after, int)
        proof["submit_call_count_after"] = after
        if isinstance(before, int) and isinstance(after, int):
            delta = after - before
            proof["submit_call_count_delta"] = delta
            proof["submit_order_invoked"] = wrapper_invoked or delta != 0
        else:
            proof["submit_call_count_delta"] = None
            proof["submit_order_invoked"] = True
        proof["write_method_invoked"] = bool(proof.get("write_method_invoked", False))
        artifact["no_submit_proof"] = proof

    def _install_startup_sync_write_guards(self, artifact: dict[str, Any]) -> dict[str, Any]:
        write_methods = (
            "submit_order",
            "cancel_order",
            "replace_order",
            "close_position",
            "close_all_positions",
        )
        original_methods: dict[str, Any] = {}
        startup_sync_prefix = f"{artifact['backend']}_startup_sync"
        submit_order = getattr(self.broker, "submit_order", None)
        if not callable(submit_order):
            raise RuntimeError(f"{startup_sync_prefix}_submit_surface_missing")

        proof = dict(artifact.get("no_submit_proof", {}))
        proof["submit_order_guard_installed"] = True
        guarded: list[str] = []
        artifact["no_submit_proof"] = proof

        def make_guard(method_name: str):
            def _guard(*args: Any, **kwargs: Any) -> Any:
                guard_proof = dict(artifact.get("no_submit_proof", {}))
                guard_proof["write_method_invoked"] = True
                method_names = list(guard_proof.get("write_method_names", []))
                method_names.append(method_name)
                guard_proof["write_method_names"] = self._sorted_unique_strings(method_names)
                guard_proof["submit_order_wrapper_blocked"] = True
                guard_proof["submit_order_wrapper_reason"] = (
                    f"{startup_sync_prefix}_write_method_blocked"
                )
                if method_name == "submit_order":
                    order = args[0] if args else None
                    guard_proof["submit_order_invoked"] = True
                    guard_proof["submit_order_wrapper_invoked"] = True
                    order_ids = list(guard_proof.get("submit_order_wrapper_order_ids", []))
                    order_id = getattr(order, "order_id", None)
                    if order_id:
                        order_ids.append(str(order_id))
                    guard_proof["submit_order_wrapper_order_ids"] = self._sorted_unique_strings(order_ids)
                    guard_proof["submit_order_wrapper_reason"] = (
                        f"{startup_sync_prefix}_submit_order_blocked"
                    )
                    artifact["no_submit_proof"] = guard_proof
                    raise RuntimeError(f"{startup_sync_prefix}_submit_order_blocked")
                artifact["no_submit_proof"] = guard_proof
                raise RuntimeError(f"{startup_sync_prefix}_write_method_blocked")

            return _guard

        for method_name in write_methods:
            method = getattr(self.broker, method_name, None)
            if not callable(method):
                continue
            original_methods[method_name] = method
            setattr(self.broker, method_name, make_guard(method_name))  # type: ignore[method-assign]
            guarded.append(method_name)

        proof = dict(artifact.get("no_submit_proof", {}))
        proof["write_guard_methods"] = guarded
        artifact["no_submit_proof"] = proof
        return original_methods

    def _restore_startup_sync_write_guards(
        self,
        artifact: dict[str, Any],
        original_methods: dict[str, Any],
    ) -> None:
        for method_name, original_method in original_methods.items():
            setattr(self.broker, method_name, original_method)  # type: ignore[method-assign]
        proof = dict(artifact.get("no_submit_proof", {}))
        proof["submit_order_guard_restored"] = True
        proof["write_guard_restored"] = True
        artifact["no_submit_proof"] = proof

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
