"""Paper trading main loop with daily reconciliation.

Core loop: poll market data → run strategy → OMS + risk → paper broker →
daily reconciliation → alerts.

This is the gate between backtest and live trading. Must run 30 consecutive
days without state errors before any live trading.
"""

from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.gap_session import GapConfig, detect_gap, is_extreme_gap
from quant_us.backtest.liquidity_slippage import LiquiditySlippage
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderStatus
from quant_us.core.types import new_id
from quant_us.execution.fill_idempotency import (
    FillIdempotencyIndex,
    append_fill_idempotent,
)
from quant_us.data.storage.postgres_store import PostgresConfig, PostgresStateStore
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.monitoring.daily_report import generate_daily_report, save_report
from quant_us.monitoring.telegram_alerts import AlertPriority, TelegramAlertService, load_telegram_config_from_env
from quant_us.risk.data_freshness import DataFreshnessConfig, DataFreshnessGuard
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.risk.risk_event_log import RiskEventLog


@dataclass
class PaperTradingConfig:
    initial_cash: float = 100_000.0
    commission_rate: float = 0.0001
    slippage_bps: float = 1.0
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.12
    max_consecutive_failures: int = 3
    reconciliation_time_et: time = field(default_factory=lambda: time(16, 5))
    ledger_root: str = "data/paper_ledger"
    use_liquidity_slippage: bool = False
    gap_config: GapConfig | None = None
    alerts_enabled: bool = False
    max_data_delay_seconds: float = 300.0
    max_data_staleness_seconds: float = 600.0  # for kill switch data staleness check
    risk_event_log_path: str = ""
    pg_dsn: str = ""  # PostgreSQL connection string; empty = no dual-write


@dataclass
class PaperTradingDayResult:
    date: date
    starting_equity: float
    ending_equity: float
    daily_pnl: float
    daily_return_pct: float
    orders_submitted: int
    orders_filled: int
    orders_rejected: int
    orders_cancelled: int
    kill_switch_triggered: bool
    reconciliation_passed: bool
    reconciliation_diff: dict[str, Any] = field(default_factory=dict)
    stale_bars: int = 0
    errors: list[str] = field(default_factory=list)


class PaperTradingLoop:
    """Run paper trading with full order lifecycle and daily reconciliation.

    Strategy → TargetPosition → OrderIntent → Risk Check → Paper Broker →
    Fill → Ledger → Daily Reconciliation → Alert.
    """

    def __init__(
        self,
        config: PaperTradingConfig | None = None,
        calendar: USEquityCalendar | None = None,
        alerts: TelegramAlertService | None = None,
    ) -> None:
        self.config = config or PaperTradingConfig()
        self.calendar = calendar or USEquityCalendar.with_holidays()

        kill_config = KillSwitchConfig(
            max_daily_loss_pct=self.config.max_daily_loss_pct,
            max_drawdown_pct=self.config.max_drawdown_pct,
            max_consecutive_order_failures=self.config.max_consecutive_failures,
            max_data_staleness_seconds=self.config.max_data_staleness_seconds,
        )

        # Risk event log
        self.risk_event_log: RiskEventLog | None = None
        if self.config.risk_event_log_path:
            self.risk_event_log = RiskEventLog(self.config.risk_event_log_path)

        self.kill_switch = KillSwitch(
            config=kill_config,
            risk_event_log=self.risk_event_log,
        )

        self.broker = SimulatedBroker(
            initial_cash=self.config.initial_cash,
            commission_model=PercentCommission(rate=self.config.commission_rate),
            slippage_model=BpsSlippage(bps=self.config.slippage_bps),
            liquidity_slippage_model=LiquiditySlippage() if self.config.use_liquidity_slippage else None,
            broker_name="paper",
            fill_ratio=0.95,
        )

        risk_config = PreTradeRiskConfig()
        self.risk_engine = PreTradeRiskEngine(risk_config, calendar=self.calendar)
        self.oms = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            calendar=self.calendar,
            kill_switch=self.kill_switch,
            risk_event_log=self.risk_event_log,
        )

        self.ledger = JsonlLedgerStore(self.config.ledger_root)
        self._fill_index = FillIdempotencyIndex.from_ledger(self.ledger)

        # Optional PostgreSQL dual-write store
        self.pg_store: PostgresStateStore | None = None
        if self.config.pg_dsn:
            try:
                self.pg_store = PostgresStateStore(PostgresConfig(dsn=self.config.pg_dsn))
            except Exception:
                _logger = logging.getLogger("paper_trading")
                _logger.warning("Failed to initialize PostgresStateStore; PG dual-write disabled")
                self.pg_store = None

        if alerts is not None:
            self.alerts = alerts
        else:
            env_config = load_telegram_config_from_env()
            if env_config is not None:
                self.alerts = TelegramAlertService(env_config)
                if env_config.enabled:
                    self.config.alerts_enabled = True
            else:
                self.alerts = TelegramAlertService()
        self.data_freshness = DataFreshnessGuard(
            DataFreshnessConfig(max_delay_seconds=self.config.max_data_delay_seconds)
        )
        self._halt_reconciliation: bool = False
        self.daily_results: list[PaperTradingDayResult] = []

    def _apply_gap_protection(self, bar: Any, prev_close: float | None) -> None:
        """Detect and handle price gaps for the given bar.

        Updates the broker's gap_overrides to reject or adjust fill prices
        based on the configured GapConfig. No-op when gap_config is None.
        """
        if self.config.gap_config is None:
            return
        self.broker.gap_overrides.pop(bar.symbol, None)
        if prev_close is not None and prev_close > 0 and bar.open > 0:
            gap_pct = (bar.open / prev_close - 1.0) * 100.0
            if is_extreme_gap(gap_pct, self.config.gap_config) and self.config.gap_config.reject_on_extreme_gap:
                self.broker.gap_overrides[bar.symbol] = None
            elif self.config.gap_config.limit_fill_on_gap and abs(gap_pct) > self.config.gap_config.max_gap_pct * 0.5:
                self.broker.gap_overrides[bar.symbol] = float(bar.open)

    def run_day(
        self,
        bars: list[Any],
        strategies: list[Any],
        market_prices: dict[str, float] | None = None,
    ) -> PaperTradingDayResult:
        """Run one trading day of paper trading.

        Args:
            bars: Market data bars for the day, sorted by timestamp.
            strategies: List of Strategy instances.
            market_prices: Current market prices for reconciliation.
        """
        today = bars[0].timestamp_utc.date() if bars else date.today()

        # Gate: skip non-trading days
        if not self.calendar.is_trading_day(today):
            return PaperTradingDayResult(
                date=today, starting_equity=0.0, ending_equity=0.0, daily_pnl=0.0,
                daily_return_pct=0.0, orders_submitted=0, orders_filled=0,
                orders_rejected=0, orders_cancelled=0, kill_switch_triggered=False,
                reconciliation_passed=True, errors=["non_trading_day"],
            )

        # Gate: do not trade if unhealthy
        if not self.is_healthy():
            return PaperTradingDayResult(
                date=today, starting_equity=0.0, ending_equity=0.0, daily_pnl=0.0,
                daily_return_pct=0.0, orders_submitted=0, orders_filled=0,
                orders_rejected=0, orders_cancelled=0, kill_switch_triggered=self.kill_switch.triggered,
                reconciliation_passed=False, errors=["system_unhealthy"],
            )

        # Alert on zero bars
        if not bars:
            self.alerts.send(f"No bars received for {today.isoformat()}", AlertPriority.HIGH)
            return PaperTradingDayResult(
                date=today, starting_equity=0.0, ending_equity=0.0, daily_pnl=0.0,
                daily_return_pct=0.0, orders_submitted=0, orders_filled=0,
                orders_rejected=0, orders_cancelled=0, kill_switch_triggered=False,
                reconciliation_passed=False, errors=["zero_bars_received"],
            )

        # Reset daily loss window at start of each trading day
        account = self.broker.get_account()
        self.kill_switch.reset_daily(account.equity)
        start_equity = account.equity

        # Gate: block new orders if data is too stale
        freshness_blocked_this_run = self.data_freshness.block_new_orders
        if freshness_blocked_this_run:
            self.oms.reduce_only = True
            logging.getLogger("paper_trading").warning(
                "Data freshness block: reduce_only=True (last_fresh=%s)",
                self.data_freshness.last_fresh_timestamp,
            )
        else:
            self.oms.reduce_only = False

        submitted = 0
        filled = 0
        rejected = 0
        cancelled = 0
        stale = 0
        errors: list[str] = []

        for bar in bars:
            freshness = self.data_freshness.evaluate_bar(bar)
            if not freshness.fresh:
                freshness_blocked_this_run = True
                stale += 1
                self.kill_switch.check_data_staleness(freshness.delay_seconds)
                continue  # skip stale bars, do not trade on them

            # Save prev_close for gap detection before update_market overwrites it
            prev_close = self.broker.market_prices.get(bar.symbol, None)
            self.broker.update_market(bar)

            # Apply gap protection if configured
            self._apply_gap_protection(bar, prev_close)

            prices = market_prices or {bar.symbol: float(bar.close)}
            for strategy in strategies:
                if self.kill_switch.triggered:
                    break

                try:
                    from quant_us.core.events import MarketEvent
                    from quant_us.strategies.base import StrategyContext

                    context = StrategyContext(
                        run_id=new_id("paper"),
                        account=self.broker.get_account(),
                        market_prices=prices,
                        universe=list(prices),
                    )
                    for signal in strategy.on_bar(MarketEvent.from_bar(bar), context):
                        from quant_us.backtest.engine import BacktestConfig
                        from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
                        from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner
                        from quant_us.core.types import TargetPosition

                        target = TargetPosition(
                            timestamp_utc=bar.timestamp_utc,
                            strategy_id=signal.strategy_id,
                            symbol=signal.symbol,
                            target_weight=signal.strength,
                            signal_id=signal.signal_id,
                        )
                        sizer = PercentOfEquitySizer(PositionSizerConfig())
                        sized = list(sizer.size([signal]))
                        planner = RebalancePlanner(RebalanceConfig())
                        intents = planner.plan(sized, self.broker.get_account(), prices, "paper")

                        for intent in intents:
                            result = self.oms.handle_intent(
                                intent,
                                self.broker.get_account(),
                                market_price=prices.get(intent.symbol, 0.0),
                                timestamp=bar.timestamp_utc,
                            )
                            submitted += 1
                            if result.order:
                                if result.order.status == OrderStatus.FILLED:
                                    filled += 1
                                elif result.order.status == OrderStatus.PARTIALLY_FILLED:
                                    filled += 1
                                elif result.order.status in (OrderStatus.REJECTED, OrderStatus.ERROR):
                                    rejected += 1
                                self.ledger.append_order(result.order)
                                self._pg_write_orders([result.order])
                            for fill in result.fills:
                                fill_append = append_fill_idempotent(
                                    self.ledger,
                                    fill,
                                    index=self._fill_index,
                                    logger=logging.getLogger(__name__),
                                )
                                if fill_append.appended:
                                    self._pg_write_fills([fill])
                                elif fill_append.conflict:
                                    errors.append(f"fill_conflict({fill_append.key})")
                except Exception as exc:
                    errors.append(f"{bar.symbol} @ {bar.timestamp_utc}: {exc}")
                    self.kill_switch.record_order_failure()

        account = self.broker.get_account()
        end_equity = account.equity

        snapshot = self.broker.snapshot(utc_now())
        self.ledger.append_snapshot(snapshot)
        self._pg_write_snapshots([snapshot])

        recon_result = self._reconcile()
        if freshness_blocked_this_run or self.data_freshness.block_new_orders:
            self.oms.reduce_only = True
        self.kill_switch.update_equity(end_equity)

        daily_pnl = end_equity - start_equity
        daily_return = daily_pnl / start_equity if start_equity > 0 else 0.0

        # Accounting assertion: cash + market value must equal equity
        total_market_value = sum(p.market_value for p in account.positions.values())
        if abs(account.cash + total_market_value - account.equity) > 1e-6:
            errors.append(
                f"accounting_mismatch: cash={account.cash:.2f} + mkt_val={total_market_value:.2f} "
                f"!= equity={account.equity:.2f}"
            )

        # Always emit a local structured log line, even when alerts disabled
        _logger = logging.getLogger("paper_trading")
        _logger.info(
            "paper_trading_day date=%s pnl=%.2f return=%.4f%% recon=%s healthy=%s errors=%d",
            today.isoformat(), daily_pnl, daily_return * 100.0,
            recon_result.get("passed", False), self.is_healthy(), len(errors),
        )

        result = PaperTradingDayResult(
            date=today,
            starting_equity=start_equity,
            ending_equity=end_equity,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_return * 100.0,
            orders_submitted=submitted,
            orders_filled=filled,
            orders_rejected=rejected,
            orders_cancelled=cancelled,
            kill_switch_triggered=self.kill_switch.triggered,
            reconciliation_passed=recon_result.get("passed", True),
            reconciliation_diff=recon_result,
            stale_bars=stale,
            errors=errors,
        )
        self.daily_results.append(result)

        # Generate and persist daily trading report
        try:
            daily_rep = generate_daily_report(today, self.ledger, self.broker, self.kill_switch)
            daily_rep.stale_bars = stale
            daily_rep.reconciliation_status = "clean" if recon_result.get("passed", True) else "breaks_detected"
            daily_rep.reconciliation_diff_count = recon_result.get("difference_count", 0)
            daily_rep.reconciliation_halt = self._halt_reconciliation
            daily_rep.errors = errors
            save_report(daily_rep, Path(self.config.ledger_root) / "daily_reports")
        except Exception as exc:
            _logger.warning("Failed to generate daily report: %s", exc)

        self._send_alerts(result)
        return result

    def _reconcile(self) -> dict[str, Any]:
        """Reconcile ALL FOUR dimensions using ReconciliationService.

        Returns a dict with the same keys as the legacy method for backward
        compatibility with _send_alerts and PaperTradingDayResult.
        """
        service = ReconciliationService(self.ledger.root, self.broker)
        report = service.reconcile_all(
            initial_cash=self.config.initial_cash,
            telegram_alerts=self.alerts if self.config.alerts_enabled else None,
        )

        if report.status == "breaks_detected":
            self._halt_reconciliation = True
            self.oms.reduce_only = True
            self.kill_switch.record_recon_failure()
            logging.getLogger("paper_trading").error(
                "Reconciliation FAILED: cash_diff=%.2f  position_diffs=%d  "
                "order_diffs=%d  fill_diffs=%d  report=%s",
                report.cash_diff,
                len(report.position_diffs),
                len(report.order_diffs),
                len(report.fill_diffs),
                report.report_path,
            )
        else:
            self._halt_reconciliation = False
            self.oms.reduce_only = False
            self.kill_switch.record_recon_success()

        # Build backward-compatible dict (position diffs only, for alerts)
        diffs_by_symbol: dict[str, dict[str, float]] = {}
        for sym, d in report.position_diffs.items():
            diffs_by_symbol[sym] = {
                "broker_quantity": d["broker_quantity"],
                "ledger_quantity": d["local_quantity"],
                "quantity_diff": d["quantity_diff"],
                "broker_value": d["broker_market_value"],
                "ledger_value": d["local_market_value"],
            }

        broker_positions = self.broker.get_positions()
        ledger_positions = self.ledger.latest_positions_from_fills()
        all_symbols = set(broker_positions) | set(ledger_positions)

        return {
            "passed": report.status == "clean",
            "broker_positions": {s: p.quantity for s, p in broker_positions.items()},
            "ledger_positions": {
                s: ledger_positions.get(s).quantity if s in ledger_positions else 0.0
                for s in all_symbols
            },
            "differences": diffs_by_symbol,
            "difference_count": len(diffs_by_symbol),
        }

    def _send_alerts(self, result: PaperTradingDayResult) -> None:
        if not self.config.alerts_enabled:
            return

        self.alerts.daily_report(
            date_str=result.date.isoformat(),
            equity=result.ending_equity,
            daily_pnl=result.daily_pnl,
            daily_return_pct=result.daily_return_pct,
            positions=len(self.broker.get_positions()),
            orders=result.orders_submitted,
        )

        if result.stale_bars > 0:
            self.alerts.send(
                f"{result.stale_bars} stale bars on {result.date.isoformat()}",
                priority=AlertPriority.HIGH,
            )

        if result.kill_switch_triggered:
            equity = result.ending_equity
            dd = (self.broker.high_water_equity - equity) / self.broker.high_water_equity * 100.0 if self.broker.high_water_equity > 0 else 0.0
            self.alerts.kill_switch_triggered(
                reason=self.kill_switch.reason,
                equity=equity,
                drawdown_pct=dd,
            )

        if not result.reconciliation_passed:
            for symbol, diff in result.reconciliation_diff.get("differences", {}).items():
                self.alerts.reconciliation_mismatch(
                    symbol=symbol,
                    local_qty=float(diff["ledger_quantity"]),
                    broker_qty=float(diff["broker_quantity"]),
                    diff=float(diff["quantity_diff"]),
                )

    # ── PostgreSQL dual-write helpers (graceful degradation) ──────────

    def _pg_write_orders(self, orders: list[Any]) -> None:
        """Write orders to PG if store is configured. Failure is logged, not fatal."""
        if self.pg_store is None:
            return
        try:
            self.pg_store.write_orders(orders)
        except Exception:
            logging.getLogger("paper_trading").exception("PG write_orders failed (degraded)")

    def _pg_write_fills(self, fills: list[Any]) -> None:
        """Write fills to PG if store is configured. Failure is logged, not fatal."""
        if self.pg_store is None:
            return
        try:
            self.pg_store.write_fills(fills)
        except Exception:
            logging.getLogger("paper_trading").exception("PG write_fills failed (degraded)")

    def _pg_write_snapshots(self, snapshots: list[Any]) -> None:
        """Write snapshots to PG if store is configured. Failure is logged, not fatal."""
        if self.pg_store is None:
            return
        try:
            self.pg_store.write_snapshots(snapshots)
        except Exception:
            logging.getLogger("paper_trading").exception("PG write_snapshots failed (degraded)")

    def is_healthy(self) -> bool:
        """Check if paper trading can continue.

        Returns False when any of these hold:
        - kill switch triggered
        - reconciliation halt active
        - last trading day had reconciliation failure
        """
        if self.kill_switch.triggered:
            return False
        if self._halt_reconciliation:
            return False
        if self.daily_results:
            last = self.daily_results[-1]
            if not last.reconciliation_passed:
                return False
        return True

    def status_summary(self) -> dict[str, Any]:
        account = self.broker.get_account()
        return {
            "account": {
                "equity": account.equity,
                "cash": account.cash,
                "buying_power": account.buying_power,
            },
            "positions": len(account.positions),
            "kill_switch": {
                "triggered": self.kill_switch.triggered,
                "reason": self.kill_switch.reason,
            },
            "days_traded": len(self.daily_results),
            "healthy": self.is_healthy(),
            "data_stale_bars": self.daily_results[-1].stale_bars if self.daily_results else 0,
            "last_reconciliation": (
                self.daily_results[-1].reconciliation_passed if self.daily_results else None
            ),
        }
