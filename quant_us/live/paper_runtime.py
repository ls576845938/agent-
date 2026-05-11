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
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.enums import OrderSide, OrderStatus, SessionName, TradingMode
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, OrderIntent, Signal, TargetPosition, new_id
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
)
from quant_us.live.alpaca_paper_adapter import (
    ALPACA_PAPER_NETWORK_SUBMIT_ENV,
    AlpacaPaperBrokerAdapter,
)
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.market_data_loop import MarketDataLoop
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


def _normalized_unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip().upper()
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return sorted(normalized)


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
        self._last_bar_timestamps: dict[tuple[str, str], datetime] = {}
        self.session_metrics: list[PaperSessionMetrics] = []
        self.metrics_log: list[PaperSessionMetrics] = []
        self.audit_events: list[dict[str, Any]] = []
        self._fill_index = FillIdempotencyIndex()
        self.session_id: str = new_id("paper_session")
        self._broker_state_recovery_cache: dict[str, Any] | None = None

        # Wired in bootstrap() — declared for type-checking
        self.calendar: USEquityCalendar
        self.session_clock: SessionClock
        self.kill_switch: KillSwitch
        self.risk_event_log: RiskEventLog | None = None
        self.broker: SimulatedBroker
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
        self._recover_or_verify_broker_state()
        self._last_bar_timestamps = self._load_bar_watermarks()

        # Strategy
        self.strategy, self.strategies = self._normalize_strategies(strategy)

        # Market data loop
        bar_sizes = self._configured_bar_sizes()
        if len(bar_sizes) > 1:
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
            report_path = save_report(report, Path(self.config.ledger_root) / "daily_reports")
            attribution_path, attribution = self._write_strategy_attribution_report(today)
            self._augment_daily_report_with_attribution(
                report_path,
                attribution_path=attribution_path,
                attribution=attribution,
            )
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
                self.broker.update_market(bar)
                fresh_bars.append(bar)

            if not fresh_bars:
                continue

            if not self.strategies:
                self._mark_bars_processed(fresh_bars)
                continue

            try:
                prices: dict[str, float] = self.broker.market_prices.copy()
                account = self.broker.get_account()
                signals: list[Signal] = []
                for active_strategy in self.strategies:
                    strategy_id = self._strategy_identifier(active_strategy)
                    context = StrategyContext(
                        run_id=self._paper_run_id(strategy_id),
                        account=account,
                        market_prices=prices,
                        universe=list(prices),
                        parameters={
                            "paper_session_id": self.session_id,
                            "strategy_id": strategy_id,
                            "strategy_timeframes": self._configured_strategy_timeframes(),
                            "bar_sizes": self._configured_bar_sizes(),
                            "runtime_mode": "paper",
                        },
                    )
                    for bar in fresh_bars:
                        event = MarketEvent.from_bar(bar)
                        for raw_signal in active_strategy.on_bar(event, context):
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
        return True

    @staticmethod
    def _alpaca_paper_adapter_factory_present() -> bool:
        return True

    @staticmethod
    def _alpaca_paper_adapter_capabilities() -> dict[str, bool]:
        return AlpacaPaperBrokerAdapter.contract_capabilities()

    def _create_alpaca_paper_broker(self) -> SimulatedBroker:
        return AlpacaPaperBrokerAdapter.from_env(
            os.environ,
            network_submit_requested=bool(
                self.config.submit_orders and self.config.explicit_paper_submit
            ),
        )

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
            self._write_simulated_startup_sync_artifact()
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
                raise RuntimeError("alpaca_paper_startup_sync_submit_counter_unavailable")
            if artifact["no_submit_proof"]["submit_order_invoked"]:
                raise RuntimeError("alpaca_paper_startup_sync_submitted_order_fail_closed")
            if artifact["no_submit_proof"].get("write_method_invoked", False):
                raise RuntimeError("alpaca_paper_startup_sync_write_method_invoked")
        except Exception as exc:
            self._finalize_startup_sync_no_submit_proof(artifact)
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

    def _paper_entry_evidence_config_mismatch(self, projection: dict[str, Any]) -> str:
        review = dict(projection.get("review", {}))
        details = dict(review.get("details", {}))
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

    def _write_broker_state_recovery_artifact(self, artifact: dict[str, Any]) -> str:
        artifact_path = self._broker_state_recovery_artifact_path()
        payload = dict(artifact)
        payload["timestamp_utc"] = utc_now().isoformat()
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        return str(artifact_path)

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
            "artifact_path": str(manifest_path),
            "history_artifact_path": str(history_path),
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
        return str(manifest_path)

    def _startup_sync_status(self) -> dict[str, Any]:
        if self._paper_broker_backend() != "alpaca_paper":
            return {
                "status": "skipped",
                "artifact_path": "",
                "reason": "non_alpaca_paper_backend",
                "no_submit": True,
            }

        artifact_path = self._startup_sync_artifact_path()
        if not artifact_path.exists():
            return {
                "status": "missing",
                "artifact_path": str(artifact_path),
                "reason": "startup_sync_artifact_missing",
                "no_submit": False,
            }
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {
                "status": "conflict",
                "artifact_path": str(artifact_path),
                "reason": f"startup_sync_artifact_unreadable:{exc}",
                "no_submit": False,
            }
        no_submit_proof = dict(artifact.get("no_submit_proof", {}))
        return {
            "status": str(artifact.get("status", "missing")),
            "artifact_path": str(artifact_path),
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
                "artifact_path": str(artifact_path),
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
                "artifact_path": str(artifact_path),
                "resume_detected": True,
                "operationally_complete": False,
                "broker_state_restored": False,
                "broker_state_verified": False,
                "reason": f"broker_state_recovery_artifact_unreadable:{exc}",
            }

        status = {
            "status": str(artifact.get("status", "missing")),
            "artifact_path": str(artifact_path),
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
                "registry_path": str(registry_path),
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
            "path": str(evidence.get("review_path", "") or review.get("path", "") or self._paper_review_path() or ""),
            "evidence_pack_path": str(evidence.get("evidence_pack_path", "")),
            "registry_path": str(registry_path),
            "registry_status": str(evidence.get("registry_status", "")),
            "registry_integrity_status": str(evidence.get("registry_integrity_status", "")),
            "registry_notes": list(evidence.get("registry_notes", [])),
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
        submit_order = getattr(self.broker, "submit_order", None)
        if not callable(submit_order):
            raise RuntimeError("alpaca_paper_startup_sync_submit_surface_missing")

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
                    "alpaca_paper_startup_sync_write_method_blocked"
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
                        "alpaca_paper_startup_sync_submit_order_blocked"
                    )
                    artifact["no_submit_proof"] = guard_proof
                    raise RuntimeError("alpaca_paper_startup_sync_submit_order_blocked")
                artifact["no_submit_proof"] = guard_proof
                raise RuntimeError("alpaca_paper_startup_sync_write_method_blocked")

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
