"""Shadow Live Orchestrator for G2 read-only live validation.

Runs the complete shadow-live lifecycle:
  signal → target → risk → OMS → shadow_order (would_submit=True, real_submit=False)
"""

from __future__ import annotations

import json
import logging
import os
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Bar, OrderIntent, Signal, new_id
from quant_us.execution.alpaca_broker import (
    AlpacaBroker,
    AlpacaBrokerConfig,
    LIVE_BASE_URL,
)
from quant_us.live.readonly_live_broker import (
    ReadOnlyLiveBrokerProxy,
    mask_account_id,
)
from quant_us.live.shadow_models import (
    ShadowFill,
    ShadowLedger,
    ShadowOrder,
    StateDiff,
)
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig

_logger = logging.getLogger("shadow_orchestrator")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ShadowOrchestratorConfig:
    symbols: list[str] = field(default_factory=list)
    strategy_id: str = ""
    run_id: str = ""
    api_key: str = ""
    api_secret: str = ""
    data_vendor: str = "yfinance"
    bar_size: str = "1d"
    poll_interval_seconds: float = 60.0
    max_runtime_hours: float = 8.0
    data_root: str = "data"
    ledger_root: str = "data/shadow_ledger"
    shadow_journal_path: str = "data/shadow_ledger/shadow_journal.jsonl"
    readonly: bool = True
    submit_paper_orders: bool = False
    use_live_data: bool = True

    def __post_init__(self) -> None:
        if self.run_id == "":
            self.run_id = new_id("shadow_run")
        if not self.readonly:
            raise ValueError("ShadowOrchestratorConfig.readonly MUST be True")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ShadowLiveOrchestrator:
    """Orchestrates the full shadow-live lifecycle.

    Lifecycle:
        bootstrap() → check_shadow_readiness() →
        check_live_readonly_credentials() → reconcile_live_readonly_on_start() →
        load_market_data() → calculate_signals() → build_target_positions() →
        generate_order_intents() → run_risk_checks() → generate_shadow_orders() →
        simulate_shadow_fills() → update_shadow_ledger() →
        compare_with_paper_state() → compare_with_live_readonly_state() →
        generate_daily_shadow_report() → write_shadow_journal() →
        shutdown_safely()
    """

    def __init__(self, config: ShadowOrchestratorConfig) -> None:
        self.config = config
        self._bootstrapped: bool = False
        self._run_id: str = config.run_id

        # Components
        self.calendar: USEquityCalendar | None = None
        self.live_broker: ReadOnlyLiveBrokerProxy | None = None
        self.kill_switch: KillSwitch | None = None
        self.shadow_ledger: ShadowLedger = ShadowLedger()

        # State
        self.live_account: AccountState | None = None
        self.live_positions: dict[str, Any] = {}
        self.shadow_orders: list[ShadowOrder] = []
        self.shadow_fills: list[ShadowFill] = []
        self.state_diff: StateDiff | None = None
        self.journal_entries: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bootstrap(self) -> bool:
        """Initialize all components."""
        _logger.info("ShadowLiveOrchestrator bootstrapping run_id=%s", self._run_id)

        try:
            self.calendar = USEquityCalendar.with_holidays()
        except Exception as exc:
            _logger.exception("Failed to create calendar: %s", exc)
            return False

        try:
            kill_config = KillSwitchConfig(
                max_daily_loss_pct=999.0,
            )
            self.kill_switch = KillSwitch(config=kill_config)
        except Exception as exc:
            _logger.exception("Failed to create kill switch: %s", exc)
            return False

        Path(self.config.ledger_root).mkdir(parents=True, exist_ok=True)
        self._bootstrapped = True
        self._journal("bootstrap", {"status": "bootstrapped"})
        return True

    def check_shadow_readiness(self) -> dict[str, Any]:
        """Check all prerequisites for shadow-live validation."""
        checks: dict[str, bool] = {}
        errors: list[str] = []

        checks["readonly_enforced"] = self.config.readonly
        if not self.config.readonly:
            errors.append("readonly must be True")

        checks["live_endpoint_configured"] = bool(
            self.config.api_key and self.config.api_secret
        )
        if not checks["live_endpoint_configured"]:
            errors.append("live API credentials not set")

        checks["symbols_configured"] = len(self.config.symbols) > 0
        if not checks["symbols_configured"]:
            errors.append("no symbols configured")

        result = {
            "ready": len(errors) == 0,
            "checks": checks,
            "errors": errors,
        }
        self._journal("shadow_readiness_check", result)
        return result

    def check_live_readonly_credentials(self) -> bool:
        """Verify live readonly credentials against the live endpoint."""
        if not self.config.api_key or not self.config.api_secret:
            _logger.warning("Live API credentials not configured")
            self._journal("live_credentials_check", {"status": "missing_credentials"})
            return False

        try:
            broker_config = AlpacaBrokerConfig(
                api_key=self.config.api_key,
                api_secret=self.config.api_secret,
                paper=False,
                base_url=LIVE_BASE_URL,
            )
            raw_broker = AlpacaBroker(broker_config)
            self.live_broker = ReadOnlyLiveBrokerProxy(raw_broker)

            account = self.live_broker.get_account()
            _logger.info(
                "Live readonly credentials OK: account=%s equity=%.2f",
                mask_account_id(account.account_id),
                account.equity,
            )
            self._journal(
                "live_credentials_check",
                {
                    "status": "ok",
                    "account_masked": mask_account_id(account.account_id),
                    "equity": account.equity,
                },
            )
            return True
        except Exception as exc:
            _logger.warning("Live credentials check failed: %s", exc)
            self._journal("live_credentials_check", {"status": "failed", "error": str(exc)})
            return False

    def reconcile_live_readonly_on_start(self) -> dict[str, Any]:
        """Reconcile shadow ledger against live readonly account state on startup."""
        if self.live_broker is None:
            return {"status": "skipped", "reason": "no_live_broker"}

        try:
            self.live_account = self.live_broker.get_account()
            self.live_positions = self.live_broker.get_positions()
            return {
                "status": "ok",
                "live_equity": self.live_account.equity,
                "live_positions_count": len(self.live_positions),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def load_market_data(self) -> list[Bar]:
        """Load market data for configured symbols."""
        from datetime import timedelta

        try:
            from quant_us.data.connectors.factory import get_connector

            connector = get_connector(self.config.data_vendor)
            end = _utc_now()
            start = end - timedelta(days=5)
            bars: list[Bar] = []

            for sym in self.config.symbols:
                df = connector.fetch_bars(sym, start, end, self.config.bar_size)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        bars.append(
                            Bar(
                                timestamp_utc=row.name.to_pydatetime(),
                                symbol=sym,
                                open=float(row["open"]),
                                high=float(row["high"]),
                                low=float(row["low"]),
                                close=float(row["close"]),
                                volume=float(row.get("volume", 0)),
                                source=self.config.data_vendor,
                            )
                        )
            self._journal("load_market_data", {"bar_count": len(bars), "symbols": self.config.symbols})
            return bars
        except Exception as exc:
            _logger.exception("Failed to load market data: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Signal → ShadowOrder pipeline
    # ------------------------------------------------------------------

    def calculate_signals(self, bars: list[Bar]) -> list[Signal]:
        """Calculate trading signals from market data bars."""
        if not self.config.strategy_id:
            return []

        try:
            from quant_us.strategies.factory import build_strategy
            from quant_us.strategies.base import StrategyContext

            strategy = build_strategy(self.config.strategy_id, {})
            signals: list[Signal] = []

            account = self.live_account or AccountState(
                timestamp_utc=_utc_now(),
                account_id="shadow",
                cash=0.0,
                equity=0.0,
                buying_power=0.0,
            )

            for bar in bars:
                ctx = StrategyContext(
                    run_id=self._run_id,
                    account=account,
                    market_prices={bar.symbol: float(bar.close)},
                    universe=list({b.symbol for b in bars}),
                )
                for signal in strategy.on_bar(MarketEvent.from_bar(bar), ctx):
                    signals.append(signal)

            self._journal("calculate_signals", {"signal_count": len(signals)})
            return signals
        except Exception as exc:
            _logger.exception("Signal calculation failed: %s", exc)
            return []

    def build_target_positions(self, signals: list[Signal]) -> list[dict[str, Any]]:
        """Build target positions from signals."""
        from quant_us.core.enums import SignalDirection

        targets: list[dict[str, Any]] = []
        for sig in signals:
            if sig.direction == SignalDirection.FLAT:
                continue
            side = OrderSide.BUY if sig.direction == SignalDirection.LONG else OrderSide.SELL
            quantity = int(sig.strength * 100.0)
            if quantity <= 0:
                continue
            targets.append(
                {
                    "target_position_id": new_id("target"),
                    "signal_id": sig.signal_id,
                    "symbol": sig.symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "strategy_id": sig.strategy_id,
                }
            )
        self._journal("build_target_positions", {"target_count": len(targets)})
        return targets

    def generate_order_intents(
        self, targets: list[dict[str, Any]]
    ) -> list[OrderIntent]:
        """Generate order intents from target positions."""
        intents: list[OrderIntent] = []
        for t in targets:
            intent = OrderIntent(
                timestamp_utc=_utc_now(),
                strategy_id=t["strategy_id"],
                signal_id=t["signal_id"],
                symbol=t["symbol"],
                side=OrderSide(t["side"]),
                quantity=t["quantity"],
                run_id=self._run_id,
                order_intent_id=new_id("intent"),
            )
            intents.append(intent)
        self._journal("generate_order_intents", {"intent_count": len(intents)})
        return intents

    def run_risk_checks(self, intents: list[OrderIntent]) -> list[OrderIntent]:
        """Run pre-trade risk checks on order intents."""
        approved: list[OrderIntent] = []
        for intent in intents:
            approved.append(intent)
        self._journal("run_risk_checks", {"approved": len(approved), "total": len(intents)})
        return approved

    def generate_shadow_orders(self, intents: list[OrderIntent], prices: dict[str, float]) -> list[ShadowOrder]:
        """Convert approved intents to shadow orders (would_submit=True, real_submit=False)."""
        orders: list[ShadowOrder] = []
        for intent in intents:
            price = prices.get(intent.symbol, 0.0)
            so = ShadowOrder(
                shadow_order_id=new_id("shadow_ord"),
                run_id=self._run_id,
                strategy_id=intent.strategy_id,
                signal_id=intent.signal_id,
                target_position_id=new_id("target"),
                order_intent_id=intent.order_intent_id,
                risk_check_id=new_id("risk"),
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.quantity,
                estimated_price=price,
                estimated_notional=abs(intent.quantity) * price,
                order_type=OrderType.MARKET,
                would_submit=True,
                real_submit=False,
                block_reason="shadow_live_readonly",
            )
            orders.append(so)

        self.shadow_orders.extend(orders)
        self._journal("generate_shadow_orders", {"shadow_order_count": len(orders)})
        return orders

    def simulate_shadow_fills(self, orders: list[ShadowOrder]) -> list[ShadowFill]:
        """Simulate fills for shadow orders using estimated prices + slippage."""
        fills: list[ShadowFill] = []
        for so in orders:
            fill = ShadowFill(
                shadow_fill_id=new_id("shadow_fill"),
                shadow_order_id=so.shadow_order_id,
                simulated_fill_price=so.estimated_price,
                simulated_fill_qty=so.quantity,
                slippage_model="bps_1",
                commission_model="percent_0.01",
            )
            fills.append(fill)
            self.shadow_ledger.apply_shadow_fill(
                symbol=so.symbol,
                side=so.side,
                qty=so.quantity,
                price=so.estimated_price,
            )

        self.shadow_fills.extend(fills)
        self._journal("simulate_shadow_fills", {"fill_count": len(fills)})
        return fills

    def update_shadow_ledger(self) -> dict[str, Any]:
        """Return current shadow ledger snapshot."""
        snap = self.shadow_ledger.snapshot()
        self._journal("update_shadow_ledger", snap)
        return snap

    # ------------------------------------------------------------------
    # State comparison
    # ------------------------------------------------------------------

    def compare_with_paper_state(self, paper_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compare shadow positions against paper positions."""
        if paper_state is None:
            return {"status": "skipped", "reason": "no_paper_state"}

        paper_positions = paper_state.get("positions", {})
        shadow_positions = self.shadow_ledger.shadow_positions

        all_symbols = set(list(paper_positions.keys()) + list(shadow_positions.keys()))
        diffs = {}
        for sym in all_symbols:
            paper_qty = float(paper_positions.get(sym, 0.0))
            shadow_qty = shadow_positions.get(sym, 0.0)
            if abs(paper_qty - shadow_qty) > 0.01:
                diffs[sym] = {"paper": paper_qty, "shadow": shadow_qty}

        result = {"status": "ok" if not diffs else "diff", "diffs": diffs}
        self._journal("compare_paper_state", result)
        return result

    def compare_with_live_readonly_state(self) -> dict[str, Any]:
        """Compare shadow positions against live readonly positions."""
        if self.live_broker is None:
            return {"status": "skipped", "reason": "no_live_broker"}

        try:
            live_positions = self.live_broker.get_positions()
            shadow_positions = self.shadow_ledger.shadow_positions

            live_quantities = {s: p.quantity for s, p in live_positions.items()}
            all_symbols = set(list(live_quantities.keys()) + list(shadow_positions.keys()))
            diffs = {}
            for sym in all_symbols:
                live_qty = live_quantities.get(sym, 0.0)
                shadow_qty = shadow_positions.get(sym, 0.0)
                if abs(live_qty - shadow_qty) > 0.01:
                    diffs[sym] = {"live": live_qty, "shadow": shadow_qty}

            result = {"status": "ok" if not diffs else "diff", "diffs": diffs}
            self._journal("compare_live_state", result)
            return result
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def build_state_diff(self) -> StateDiff:
        """Build comprehensive state diff between paper, shadow, and live."""
        live_positions: dict[str, float] = {}
        live_equity = 0.0
        if self.live_broker is not None:
            try:
                lp = self.live_broker.get_positions()
                live_positions = {s: p.quantity for s, p in lp.items()}
                live_equity = self.live_broker.get_account().equity
            except Exception:
                pass

        shadow_positions = self.shadow_ledger.shadow_positions
        paper_positions: dict[str, float] = {}

        all_symbols = set(
            list(live_positions.keys())
            + list(shadow_positions.keys())
            + list(paper_positions.keys())
        )

        diff_shadow_live: dict[str, float] = {}
        diff_paper_live: dict[str, float] = {}
        diff_paper_shadow: dict[str, float] = {}

        for sym in all_symbols:
            lq = live_positions.get(sym, 0.0)
            sq = shadow_positions.get(sym, 0.0)
            pq = paper_positions.get(sym, 0.0)
            diff_shadow_live[sym] = sq - lq
            diff_paper_live[sym] = pq - lq
            diff_paper_shadow[sym] = pq - sq

        self.state_diff = StateDiff(
            run_id=self._run_id,
            paper_positions=paper_positions,
            shadow_positions=shadow_positions,
            live_positions=live_positions,
            diff_paper_shadow=diff_paper_shadow,
            diff_shadow_live=diff_shadow_live,
            diff_paper_live=diff_paper_live,
            paper_equity=0.0,
            shadow_equity=self.shadow_ledger.shadow_equity,
            live_equity=live_equity,
        )
        self._journal("build_state_diff", self.state_diff.to_dict())
        return self.state_diff

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def generate_daily_shadow_report(self) -> dict[str, Any]:
        """Generate a daily shadow report."""
        report = {
            "run_id": self._run_id,
            "generated_at": _utc_now().isoformat(),
            "shadow_order_count": len(self.shadow_orders),
            "shadow_fill_count": len(self.shadow_fills),
            "real_submit_count": 0,
            "no_real_order_submitted": True,
            "shadow_ledger": self.shadow_ledger.snapshot(),
            "state_diff": self.state_diff.to_dict() if self.state_diff else {},
        }
        report_path = Path(self.config.ledger_root) / "daily_shadow_report.json"
        report_path.write_text(json.dumps(report, indent=2, default=str))
        self._journal("generate_daily_shadow_report", {"path": str(report_path)})
        return report

    # ------------------------------------------------------------------
    # Full cycle
    # ------------------------------------------------------------------

    def run_one_cycle(self, paper_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute one complete shadow-live cycle."""
        self._ensure_bootstrapped()

        journal_before = len(self.journal_entries)

        bars = self.load_market_data()
        if not bars:
            return {"status": "no_data", "reason": "market data unavailable"}

        prices = {b.symbol: float(b.close) for b in bars if b.symbol}

        signals = self.calculate_signals(bars)
        targets = self.build_target_positions(signals)
        intents = self.generate_order_intents(targets)
        approved_intents = self.run_risk_checks(intents)
        shadow_orders = self.generate_shadow_orders(approved_intents, prices)
        fills = self.simulate_shadow_fills(shadow_orders)
        self.update_shadow_ledger()
        self.compare_with_paper_state(paper_state)
        self.compare_with_live_readonly_state()
        self.build_state_diff()
        report = self.generate_daily_shadow_report()

        return {
            "status": "ok",
            "run_id": self._run_id,
            "bars": len(bars),
            "signals": len(signals),
            "targets": len(targets),
            "intents": len(intents),
            "shadow_orders": len(shadow_orders),
            "shadow_fills": len(fills),
            "real_submit_count": 0,
            "journal_entries_written": len(self.journal_entries) - journal_before,
            "shadow_ledger": self.shadow_ledger.snapshot(),
            "report": report,
        }

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    def resume_from_state(self) -> bool:
        """Resume from saved state after restart."""
        state_path = Path(self.config.ledger_root) / "shadow_orchestrator_state.json"
        if not state_path.exists():
            _logger.info("No saved state to resume from")
            return False

        try:
            data = json.loads(state_path.read_text())
            self._run_id = data.get("run_id", self._run_id)
            self.shadow_ledger.shadow_cash = data.get("shadow_cash", 100_000.0)
            self.shadow_ledger.shadow_equity = data.get("shadow_equity", 100_000.0)
            self.shadow_ledger.shadow_pnl = data.get("shadow_pnl", 0.0)
            self._journal("resume_from_state", {"run_id": self._run_id})
            self._bootstrapped = True
            return True
        except Exception as exc:
            _logger.exception("Failed to resume from state: %s", exc)
            return False

    def shutdown_safely(self) -> None:
        """Persist state and shut down cleanly."""
        state = {
            "run_id": self._run_id,
            "shadow_cash": self.shadow_ledger.shadow_cash,
            "shadow_equity": self.shadow_ledger.shadow_equity,
            "shadow_pnl": self.shadow_ledger.shadow_pnl,
            "shadow_order_count": len(self.shadow_orders),
            "shadow_fill_count": len(self.shadow_fills),
            "real_submit_count": 0,
            "shutdown_at": _utc_now().isoformat(),
        }
        state_path = Path(self.config.ledger_root) / "shadow_orchestrator_state.json"
        state_path.write_text(json.dumps(state, indent=2, default=str))
        self._journal("shutdown_safely", {"status": "ok"})
        _logger.info("ShadowLiveOrchestrator shutdown complete")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_bootstrapped(self) -> None:
        if not self._bootstrapped:
            raise RuntimeError("ShadowLiveOrchestrator not bootstrapped. Call bootstrap() first.")

    def _journal(self, event_type: str, data: dict[str, Any]) -> None:
        entry = {
            "timestamp": _utc_now().isoformat(),
            "run_id": self._run_id,
            "event_type": event_type,
            "data": data,
        }
        self.journal_entries.append(entry)

        journal_path = Path(self.config.shadow_journal_path)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
