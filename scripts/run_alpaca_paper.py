#!/usr/bin/env python3
"""Alpaca Paper Trading daily runner.

Minimum viable paper trading loop:
  live_runner
      ↓
  load latest bars (from data lake)
      ↓
  calculate signal (ETF rotation strategy)
      ↓
  portfolio target
      ↓
  risk check
      ↓
  OMS submit
      ↓
  Alpaca Paper API
      ↓
  poll order status
      ↓
  write fills (to ledger)
      ↓
  update ledger
      ↓
  daily reconciliation

30-trading-day acceptance criteria:
  1. Local positions match Alpaca positions daily
  2. All orders have client_order_id
  3. All fills trace to strategy_id / signal_id / risk_check_id
  4. Broker disconnect does not duplicate orders
  5. Restart does not lose state
  6. Daily trade report generated automatically

Data note: Alpaca Paper Only accounts typically only have IEX data,
not full SIP. This means quote quality may differ from production.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.backtest.commission import PercentCommission
from quant_us.backtest.data_bridge import bars_from_dataframe
from quant_us.backtest.slippage import BpsSlippage
from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderStatus
from quant_us.core.types import new_id
from quant_us.data.storage.duckdb_store import DuckDBBarReader, DuckDBQuery
from quant_us.data.storage.postgres_store import PostgresConfig, PostgresStateStore
from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.monitoring.daily_report import generate_daily_report, save_report
from quant_us.monitoring.telegram_alerts import AlertPriority, TelegramAlertService, load_telegram_config_from_env
from quant_us.portfolio.allocation import AllocationCombiner, AllocationConfig
from quant_us.portfolio.position_sizer import PercentOfEquitySizer, PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig, RebalancePlanner
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
from quant_us.strategies.etf_rotation_strategy import EtfMomentumRotationStrategy
from quant_us.strategies.base import StrategyContext
from quant_us.core.events import MarketEvent

logger = logging.getLogger("alpaca_paper")


@dataclass
class AlpacaPaperConfig:
    """Configuration for Alpaca Paper trading daily run."""
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA"])
    capital: float = 100_000.0
    commission_rate: float = 0.0  # Alpaca commission-free
    slippage_bps: float = 1.0
    max_daily_loss_pct: float = 0.03
    max_consecutive_failures: int = 3
    data_root: str = "data"
    ledger_root: str = "data/alpaca_paper_ledger"
    poll_interval_seconds: float = 2.0
    poll_timeout_seconds: float = 30.0
    alerts_enabled: bool = False
    pg_dsn: str = ""  # PostgreSQL connection string; empty = no dual-write


class AlpacaPaperRunner:
    """Daily paper trading loop against Alpaca Paper API.

    Data note: Alpaca Paper Only accounts use IEX data, not full SIP.
    This runner does NOT subscribe to Alpaca's market data stream.
    Bars are loaded from local data lake (yfinance source).
    """

    def __init__(
        self,
        broker_config: AlpacaBrokerConfig,
        runner_config: AlpacaPaperConfig | None = None,
    ) -> None:
        self.runner_config = runner_config or AlpacaPaperConfig()
        self.calendar = USEquityCalendar.with_holidays()

        self.broker = AlpacaBroker(broker_config)
        self.kill_switch = KillSwitch(KillSwitchConfig(
            max_daily_loss_pct=self.runner_config.max_daily_loss_pct,
            max_consecutive_order_failures=self.runner_config.max_consecutive_failures,
        ))
        risk_config = PreTradeRiskConfig()
        self.risk_engine = PreTradeRiskEngine(risk_config, calendar=self.calendar)
        self.oms = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            calendar=self.calendar,
            kill_switch=self.kill_switch,
        )
        self.ledger = JsonlLedgerStore(self.runner_config.ledger_root)

        # Optional PostgreSQL dual-write store
        self.pg_store: PostgresStateStore | None = None
        if self.runner_config.pg_dsn:
            try:
                self.pg_store = PostgresStateStore(PostgresConfig(dsn=self.runner_config.pg_dsn))
            except Exception:
                logger.warning("Failed to initialize PostgresStateStore; PG dual-write disabled")
                self.pg_store = None

        self.strategy = EtfMomentumRotationStrategy()
        self.bar_reader = DuckDBBarReader(Path(self.runner_config.data_root) / "raw")

        self.alerts = TelegramAlertService()
        env_cfg = load_telegram_config_from_env()
        if env_cfg is not None:
            self.alerts = TelegramAlertService(env_cfg)
            self.runner_config.alerts_enabled = env_cfg.enabled

        self.daily_reports: list[dict] = []
        self._pending_order_ids: set[str] = set()

    # ── State persistence ────────────────────────────────────────────

    def _state_path(self) -> Path:
        return Path(self.runner_config.ledger_root) / "alpaca_paper_state.json"

    def save_state(self) -> None:
        state = {
            "last_run_date": utc_now().isoformat(),
            "daily_reports": self.daily_reports[-30:],  # keep last 30
            "pending_order_ids": list(self._pending_order_ids),
        }
        self._state_path().parent.mkdir(parents=True, exist_ok=True)
        self._state_path().write_text(json.dumps(state, indent=2, default=str))

    def load_state(self) -> dict | None:
        path = self._state_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        self._pending_order_ids = set(data.get("pending_order_ids", []))
        return data

    # ── Daily run ────────────────────────────────────────────────────

    def run_day(self, target_date: date | None = None) -> dict:
        """Run one trading day of Alpaca Paper trading."""
        today = target_date or date.today()

        if not self.calendar.is_trading_day(today):
            return {"date": today.isoformat(), "status": "non_trading_day"}

        logger.info("── Alpaca Paper: %s ──", today.isoformat())
        self.alerts.send(f"Alpaca Paper starting: {today.isoformat()}", AlertPriority.LOW)

        # 1. Load latest bars from data lake
        start_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - __import__("datetime").timedelta(days=90)
        end_dt = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc)

        all_bars = []
        for symbol in self.runner_config.symbols:
            query = DuckDBQuery(
                vendor="yfinance", asset_class="equity", bar_size="1d",
                symbol=symbol, start=start_dt, end=end_dt,
            )
            df = self.bar_reader.query_bars(query)
            if df.empty:
                logger.warning("No bars for %s in range %s → %s", symbol, start_dt, end_dt)
                continue
            all_bars.extend(bars_from_dataframe(df))

        if not all_bars:
            self.alerts.send(f"No bars available for {today.isoformat()}", AlertPriority.HIGH)
            return {"date": today.isoformat(), "status": "no_data"}

        # 2-3. Strategy → Signal → TargetPosition → OrderIntent
        account = self.broker.get_account()
        self.kill_switch.reset_daily(account.equity)
        prices = {s: p.market_price for s, p in account.positions.items()}

        submitted = 0
        filled = 0
        rejected = 0
        errors: list[str] = []

        # Group bars by timestamp for event-driven processing
        bar_groups: dict[datetime, list] = {}
        for b in all_bars:
            bar_groups.setdefault(b.timestamp_utc, []).append(b)

        for ts in sorted(bar_groups):
            bars_at_ts = bar_groups[ts]
            for bar in bars_at_ts:
                # Update prices from latest bar
                prices[bar.symbol] = float(bar.close)

            # Run strategy for each bar
            all_signals = []
            for bar in bars_at_ts:
                context = StrategyContext(
                    run_id=new_id("alpaca"),
                    account=self.broker.get_account(),
                    market_prices=prices,
                    universe=self.runner_config.symbols,
                )
                for sig in self.strategy.on_bar(MarketEvent.from_bar(bar), context):
                    all_signals.append(sig)

            if not all_signals:
                continue

            # 4. Portfolio sizing → TargetPosition → OrderIntent
            sizer = PercentOfEquitySizer(PositionSizerConfig())
            allocator = AllocationCombiner(AllocationConfig())
            planner = RebalancePlanner(RebalanceConfig())

            targets = allocator.combine(sizer.size(all_signals))
            account = self.broker.get_account()
            intents = planner.plan(targets, account, prices, new_id("alpaca"))

            # 5. Risk check → OMS submit
            for intent in intents:
                if self.kill_switch.triggered:
                    errors.append("kill_switch_triggered")
                    break

                # 6. Submit to Alpaca Paper
                result = self.oms.handle_intent(
                    intent, self.broker.get_account(),
                    market_price=prices.get(intent.symbol, 0.0),
                    timestamp=ts,
                )
                submitted += 1
                if result.order:
                    self.ledger.append_order(result.order)
                    self._pg_write_orders([result.order])
                    self._pending_order_ids.add(result.order.order_id)

                    if result.order.status in (OrderStatus.REJECTED, OrderStatus.ERROR):
                        rejected += 1
                    else:
                        # 7. Poll order status
                        filled_order = self._poll_order(result.order.order_id)
                        if filled_order and filled_order.status == OrderStatus.FILLED:
                            filled += 1
                            fills = self.broker.get_fills(order_id=filled_order.order_id)
                            for fill in fills:
                                self.ledger.append_fill(fill)
                                self._pg_write_fills([fill])
                            self._pending_order_ids.discard(filled_order.order_id)

        # 8. Daily reconciliation
        report = self._reconcile()
        self.daily_reports.append(report)

        # 9. Save state
        self.save_state()

        result = {
            "date": today.isoformat(),
            "status": "completed",
            "orders_submitted": submitted,
            "orders_filled": filled,
            "orders_rejected": rejected,
            "reconciliation": report,
            "errors": errors,
        }

        # 10. Daily trading report (acceptance criterion 6)
        try:
            daily_rep = generate_daily_report(today, self.ledger, self.broker, self.kill_switch)
            daily_rep.orders_submitted = submitted
            daily_rep.orders_filled = filled
            daily_rep.orders_rejected = rejected
            daily_rep.errors = errors
            if result.get("reconciliation"):
                daily_rep.reconciliation_status = result["reconciliation"].get("status", "unknown")
                daily_rep.reconciliation_diff_count = len(result["reconciliation"].get("differences", {}))
            save_report(daily_rep, Path(self.runner_config.ledger_root) / "daily_reports")
        except Exception as exc:
            logger.warning("Failed to generate daily report: %s", exc)

        # Legacy alerting (rejected orders, recon failures) — replaces _daily_report logic
        if rejected > 0:
            self.alerts.send(
                f"{today.isoformat()}: {rejected} rejected orders",
                AlertPriority.HIGH,
            )
        if result.get("reconciliation", {}).get("status") != "clean":
            self.alerts.send(
                f"{today.isoformat()}: Reconciliation FAILED — {result['reconciliation']['differences']}",
                AlertPriority.HIGH,
            )
        if errors:
            self.alerts.send(
                f"{today.isoformat()}: Errors: {errors}",
                AlertPriority.HIGH,
            )

        logger.info("Alpaca Paper %s: %d submitted, %d filled, %d rejected, recon=%s",
                     today.isoformat(), submitted, filled, rejected, report.get("status", "?"))
        return result

    def _poll_order(self, order_id: str) -> Any:
        """Poll Alpaca for order status until filled/expired/rejected."""
        deadline = _time.monotonic() + self.runner_config.poll_timeout_seconds
        while _time.monotonic() < deadline:
            try:
                order = self.broker.get_orders()  # TODO: get single order by ID
                for o in order:
                    if o.order_id == order_id:
                        if o.status in (OrderStatus.FILLED, OrderStatus.CANCELLED,
                                        OrderStatus.REJECTED, OrderStatus.EXPIRED):
                            return o
            except Exception:
                pass
            _time.sleep(self.runner_config.poll_interval_seconds)
        return None

    def _reconcile(self) -> dict:
        """Compare local ledger positions against Alpaca positions."""
        broker_positions = self.broker.get_positions()
        ledger_positions = self.ledger.latest_positions_from_fills()

        all_symbols = set(broker_positions) | set(ledger_positions)
        diffs: dict[str, dict] = {}
        for sym in all_symbols:
            bq = broker_positions.get(sym).quantity if sym in broker_positions else 0.0
            lq = ledger_positions.get(sym).quantity if sym in ledger_positions else 0.0
            if abs(bq - lq) > 1e-6:
                diffs[sym] = {"broker_qty": bq, "ledger_qty": lq, "diff": bq - lq}

        return {
            "status": "clean" if not diffs else "breaks_detected",
            "differences": diffs,
            "broker_symbols": list(broker_positions),
            "ledger_symbols": list(ledger_positions),
        }

    def _daily_report(self, result: dict) -> None:
        """Generate daily trade report (acceptance criterion 6)."""
        report_path = Path(self.runner_config.ledger_root) / f"report_{result['date']}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2, default=str))

        # Alert on issues
        if result["orders_rejected"] > 0:
            self.alerts.send(
                f"{result['date']}: {result['orders_rejected']} rejected orders",
                AlertPriority.HIGH,
            )
        if result["reconciliation"]["status"] != "clean":
            self.alerts.send(
                f"{result['date']}: Reconciliation FAILED — {result['reconciliation']['differences']}",
                AlertPriority.HIGH,
            )
        if result["errors"]:
            self.alerts.send(
                f"{result['date']}: Errors: {result['errors']}",
                AlertPriority.HIGH,
            )


    # ── PostgreSQL dual-write helpers (graceful degradation) ──────────

    def _pg_write_orders(self, orders: list[Any]) -> None:
        if self.pg_store is None:
            return
        try:
            self.pg_store.write_orders(orders)
        except Exception:
            logger.exception("PG write_orders failed (degraded)")

    def _pg_write_fills(self, fills: list[Any]) -> None:
        if self.pg_store is None:
            return
        try:
            self.pg_store.write_fills(fills)
        except Exception:
            logger.exception("PG write_fills failed (degraded)")

    def _pg_write_snapshots(self, snapshots: list[Any]) -> None:
        if self.pg_store is None:
            return
        try:
            self.pg_store.write_snapshots(snapshots)
        except Exception:
            logger.exception("PG write_snapshots failed (degraded)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Alpaca Paper Trading Daily Runner")
    p.add_argument("--api-key", default=os.environ.get("APCA_API_KEY_ID", ""))
    p.add_argument("--api-secret", default=os.environ.get("APCA_API_SECRET_KEY", ""))
    p.add_argument("--paper", type=bool, default=True)
    p.add_argument("--symbols", default="SPY,QQQ,IWM,DIA")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--data-root", default="data")
    p.add_argument("--ledger-root", default="data/alpaca_paper_ledger")
    p.add_argument("--pg-dsn", default=os.environ.get("PG_DSN", ""), help="PostgreSQL connection string for state store dual-write")
    p.add_argument("--date", help="Override trading date (YYYY-MM-DD)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.api_key or not args.api_secret:
        print("ERROR: Set APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables")
        print("Get free Paper Trading keys at: https://app.alpaca.markets/paper/dashboard/overview")
        sys.exit(1)

    broker_cfg = AlpacaBrokerConfig(
        api_key=args.api_key,
        api_secret=args.api_secret,
        paper=args.paper,
    )
    runner_cfg = AlpacaPaperConfig(
        symbols=[s.strip().upper() for s in args.symbols.split(",")],
        capital=args.capital,
        data_root=args.data_root,
        ledger_root=args.ledger_root,
        pg_dsn=args.pg_dsn,
    )

    runner = AlpacaPaperRunner(broker_cfg, runner_cfg)
    runner.load_state()

    target_date = date.fromisoformat(args.date) if args.date else None
    result = runner.run_day(target_date)

    print(json.dumps(result, indent=2, default=str))

    if result.get("reconciliation", {}).get("status") != "clean":
        sys.exit(1)


if __name__ == "__main__":
    main()
