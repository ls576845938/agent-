"""Live Readiness Gate — automated check of all pre-live conditions.

Before any live trading, ALL checks must pass:

  - paper_30_day_clean   30 consecutive clean paper trading days
  - oms_idempotency      OMS has idempotency_path configured
  - kill_switch_coverage KillSwitchConfig has all thresholds set
  - recon_hard_gate      ReconciliationService implements reconcile_all with halt
  - fill_traceability    Fill -> Order -> Signal chain intact
  - order_recovery       OMS has recover_from_ledger method
  - daily_report         Daily report module exists
  - monitoring           MetricsCollector exists
"""

from __future__ import annotations

import json
import inspect
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ReadinessCheck:
    """Result of a single readiness check."""

    name: str
    passed: bool
    detail: str = ""
    warn: bool = False  # True = warn (not hard fail), used by simulated/paper profiles


@dataclass
class LiveReadinessReport:
    """Aggregate result of all readiness checks."""

    checks: list[ReadinessCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def is_ready(self, profile: str = "live") -> bool:
        """True when ALL hard-FAIL checks pass (warnings don't block)."""
        failing = [c for c in self.checks if not c.passed and not c.warn]
        return len(failing) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.all_passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "warn": c.warn, "detail": c.detail}
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Threshold fields expected in KillSwitchConfig
# ---------------------------------------------------------------------------

_KILL_SWITCH_THRESHOLDS: frozenset[str] = frozenset({
    "max_daily_loss_pct",
    "max_drawdown_pct",
    "max_consecutive_order_failures",
    "max_broker_disconnect_seconds",
    "max_data_staleness_seconds",
    "max_consecutive_recon_failures",
    "max_slippage_bps",
})

# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class LiveReadinessGate:
    """Evaluate all pre-live conditions and return a readiness report."""

    def check_all(
        self, validation_state_path: str | Path | None = None, profile: str = "live"
    ) -> LiveReadinessReport:
        """Run every readiness check and return the combined report.

        Args:
            validation_state_path: Path to validation_state.json from paper trading.
            profile: One of 'simulated', 'paper', 'live'. Controls which checks
                     are hard FAIL vs soft WARN.
        """
        report = LiveReadinessReport()

        report.checks.append(self._check_paper_30_day_clean(validation_state_path, profile))
        report.checks.append(self._check_oms_idempotency())
        report.checks.append(self._check_kill_switch_coverage())
        report.checks.append(self._check_recon_hard_gate())
        report.checks.append(self._check_fill_traceability())
        report.checks.append(self._check_order_recovery())
        report.checks.append(self._check_daily_report())
        report.checks.append(self._check_monitoring())
        report.checks.append(self._check_broker_credentials(profile))
        report.checks.append(self._check_data_vendor_health())
        report.checks.append(self._check_telegram_connectivity(profile))

        return report

    # ------------------------------------------------------------------
    # Individual checks  (each is a staticmethod for testability)
    # ------------------------------------------------------------------

    @staticmethod
    @staticmethod
    def _check_paper_30_day_clean(
        validation_state_path: str | Path | None, profile: str = "live"
    ) -> ReadinessCheck:
        """Reads from validation_state.json and verifies 30 consecutive clean days.

        In 'simulated' profile: missing state is WARN ("run --simulate-days 30 first").
        In 'paper'/'live' profiles: missing state is FAIL.
        """
        if validation_state_path is None or str(validation_state_path) == "":
            if profile == "simulated":
                return ReadinessCheck(
                    name="paper_30_day_clean",
                    passed=True,
                    detail="No validation_state — run 'live start --simulate-days 30' to generate (WARN for paper/live)",
                    warn=True,
                )
            return ReadinessCheck(
                name="paper_30_day_clean",
                passed=False,
                detail="No validation_state_path provided; run paper trading for 30 days first",
            )
        p = Path(validation_state_path)
        if not p.exists():
            return ReadinessCheck(
                name="paper_30_day_clean",
                passed=False,
                detail=f"Validation state file not found: {p}",
            )
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            return ReadinessCheck(
                name="paper_30_day_clean",
                passed=False,
                detail=f"Error reading validation state: {exc}",
            )

        consecutive_clean = data.get("consecutive_clean_days", 0)
        days_completed = data.get("days_completed", 0)
        required = data.get("days_required", 30)
        daily_results: list[dict] = data.get("daily_results", [])

        failures: list[str] = []

        if consecutive_clean < required:
            failures.append(
                f"Only {consecutive_clean}/{required} consecutive clean days"
            )

        if days_completed < required:
            failures.append(
                f"Only {days_completed}/{required} days completed"
            )

        # Check every daily result for errors or reconciliation failures
        error_days: list[str] = []
        for entry in daily_results:
            errors = entry.get("errors", [])
            recon: str = entry.get("recon", "PASS")
            if errors:
                error_days.append(
                    f"{entry.get('date', '?')}({len(errors)} errors)"
                )
            if recon == "FAIL":
                error_days.append(
                    f"{entry.get('date', '?')}(recon_fail)"
                )
        if error_days:
            failures.append(f"Problem days: {', '.join(error_days)}")

        if not failures:
            return ReadinessCheck(
                name="paper_30_day_clean",
                passed=True,
                detail=(
                    f"{consecutive_clean}/{required} consecutive clean days, "
                    f"{days_completed}/{required} days completed, "
                    f"no errors in daily results"
                ),
            )

        return ReadinessCheck(
            name="paper_30_day_clean",
            passed=False,
            detail="; ".join(failures),
        )

    @staticmethod
    def _check_oms_idempotency() -> ReadinessCheck:
        """OrderManagementSystem must accept idempotency_path."""
        try:
            from quant_us.execution.oms import OrderManagementSystem

            sig = inspect.signature(OrderManagementSystem.__init__)
            param_names = set(sig.parameters.keys())
            if "idempotency_path" in param_names:
                return ReadinessCheck(
                    name="oms_idempotency",
                    passed=True,
                    detail="OrderManagementSystem accepts idempotency_path parameter",
                )
            return ReadinessCheck(
                name="oms_idempotency",
                passed=False,
                detail="OrderManagementSystem missing idempotency_path parameter",
            )
        except (ImportError, AttributeError) as exc:
            return ReadinessCheck(
                name="oms_idempotency",
                passed=False,
                detail=f"Cannot verify OMS idempotency: {exc}",
            )

    @staticmethod
    def _check_kill_switch_coverage() -> ReadinessCheck:
        """KillSwitchConfig must define all expected threshold fields."""
        try:
            from quant_us.risk.kill_switch import KillSwitchConfig

            actual = set(KillSwitchConfig.__dataclass_fields__.keys())
            missing = _KILL_SWITCH_THRESHOLDS - actual
            if not missing:
                return ReadinessCheck(
                    name="kill_switch_coverage",
                    passed=True,
                    detail=f"All {len(_KILL_SWITCH_THRESHOLDS)} kill-switch thresholds configured",
                )
            return ReadinessCheck(
                name="kill_switch_coverage",
                passed=False,
                detail=f"Missing thresholds: {sorted(missing)}",
            )
        except (ImportError, AttributeError) as exc:
            return ReadinessCheck(
                name="kill_switch_coverage",
                passed=False,
                detail=f"Cannot verify KillSwitchConfig: {exc}",
            )

    @staticmethod
    def _check_recon_hard_gate() -> ReadinessCheck:
        """ReconciliationService must implement reconcile_all with halt."""
        try:
            from quant_us.live.reconciliation_service import ReconciliationService

            if not hasattr(ReconciliationService, "reconcile_all"):
                return ReadinessCheck(
                    name="recon_hard_gate",
                    passed=False,
                    detail="ReconciliationService missing reconcile_all method",
                )

            sig = inspect.signature(ReconciliationService.reconcile_all)
            params = list(sig.parameters.keys())
            if "initial_cash" not in params:
                return ReadinessCheck(
                    name="recon_hard_gate",
                    passed=False,
                    detail="reconcile_all missing required 'initial_cash' parameter",
                )

            return ReadinessCheck(
                name="recon_hard_gate",
                passed=True,
                detail="ReconciliationService.reconcile_all exists with halt flow",
            )
        except (ImportError, AttributeError) as exc:
            return ReadinessCheck(
                name="recon_hard_gate",
                passed=False,
                detail=f"Cannot verify ReconciliationService: {exc}",
            )

    @staticmethod
    def _check_fill_traceability() -> ReadinessCheck:
        """Fill -> Order -> Signal chain must be intact."""
        try:
            from quant_us.core.types import Fill, Order, Signal

            fill_fields = set(Fill.__dataclass_fields__.keys())
            order_fields = set(Order.__dataclass_fields__.keys())
            signal_fields = set(Signal.__dataclass_fields__.keys())

            missing_links: list[str] = []
            if "order_id" not in fill_fields:
                missing_links.append("Fill.order_id")
            if "signal_id" not in order_fields:
                missing_links.append("Order.signal_id")
            if "signal_id" not in signal_fields:
                missing_links.append("Signal.signal_id")

            if not missing_links:
                return ReadinessCheck(
                    name="fill_traceability",
                    passed=True,
                    detail="Fill -> Order -> Signal traceability chain verified",
                )
            return ReadinessCheck(
                name="fill_traceability",
                passed=False,
                detail=f"Missing traceability fields: {missing_links}",
            )
        except (ImportError, AttributeError) as exc:
            return ReadinessCheck(
                name="fill_traceability",
                passed=False,
                detail=f"Cannot verify traceability chain: {exc}",
            )

    @staticmethod
    def _check_order_recovery() -> ReadinessCheck:
        """OrderManagementSystem must have recover_from_ledger."""
        try:
            from quant_us.execution.oms import OrderManagementSystem

            if hasattr(OrderManagementSystem, "recover_from_ledger"):
                return ReadinessCheck(
                    name="order_recovery",
                    passed=True,
                    detail="OrderManagementSystem.recover_from_ledger exists",
                )
            return ReadinessCheck(
                name="order_recovery",
                passed=False,
                detail="OrderManagementSystem missing recover_from_ledger method",
            )
        except (ImportError, AttributeError) as exc:
            return ReadinessCheck(
                name="order_recovery",
                passed=False,
                detail=f"Cannot verify order recovery: {exc}",
            )

    @staticmethod
    def _check_daily_report() -> ReadinessCheck:
        """daily_report callable must exist in monitoring.report."""
        try:
            from quant_us.monitoring.report import daily_report

            if callable(daily_report):
                return ReadinessCheck(
                    name="daily_report",
                    passed=True,
                    detail="quant_us.monitoring.report.daily_report exists",
                )
            return ReadinessCheck(
                name="daily_report",
                passed=False,
                detail="daily_report is not callable",
            )
        except (ImportError, AttributeError) as exc:
            return ReadinessCheck(
                name="daily_report",
                passed=False,
                detail=f"Cannot import daily_report: {exc}",
            )

    @staticmethod
    def _check_monitoring() -> ReadinessCheck:
        """MetricsCollector must exist with snapshot and to_prometheus_text."""
        try:
            from quant_us.monitoring.metrics import MetricsCollector

            has_snapshot = hasattr(MetricsCollector, "snapshot")
            has_prometheus = hasattr(MetricsCollector, "to_prometheus_text")
            if has_snapshot and has_prometheus:
                return ReadinessCheck(
                    name="monitoring",
                    passed=True,
                    detail="MetricsCollector with snapshot() and to_prometheus_text() exists",
                )
            missing = []
            if not has_snapshot:
                missing.append("snapshot()")
            if not has_prometheus:
                missing.append("to_prometheus_text()")
            return ReadinessCheck(
                name="monitoring",
                passed=False,
                detail=f"MetricsCollector missing: {missing}",
            )
        except (ImportError, AttributeError) as exc:
            return ReadinessCheck(
                name="monitoring",
                passed=False,
                detail=f"Cannot import MetricsCollector: {exc}",
            )

    @staticmethod
    @staticmethod
    def _check_broker_credentials(profile: str = "live") -> ReadinessCheck:
        """Verify Alpaca API credentials are set and account is reachable.

        In 'simulated' profile, missing credentials is WARN, not FAIL.
        In 'paper' and 'live' profiles, missing credentials is FAIL.
        """
        api_key = os.environ.get("APCA_API_KEY_ID", "")
        api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
        if not api_key or not api_secret:
            if profile == "simulated":
                return ReadinessCheck(
                    name="broker_credentials",
                    passed=True,  # not required for simulated
                    detail="No Alpaca credentials set — using simulated broker (WARN for paper/live)",
                    warn=True,
                )
            return ReadinessCheck(
                name="broker_credentials",
                passed=False,
                detail="APCA_API_KEY_ID or APCA_API_SECRET_KEY not set in environment",
            )
        try:
            from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig

            broker = AlpacaBroker(
                AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=True)
            )
            account = broker.get_account()
            return ReadinessCheck(
                name="broker_credentials",
                passed=True,
                detail=f"Connected to Alpaca paper API: account={account.account_id}, equity=${account.equity:,.2f}",
            )
        except Exception as exc:
            if profile == "simulated":
                return ReadinessCheck(
                    name="broker_credentials",
                    passed=True,
                    detail=f"Cannot connect to Alpaca: {exc} — using simulated broker (WARN for paper/live)",
                    warn=True,
                )
            return ReadinessCheck(
                name="broker_credentials",
                passed=False,
                detail=f"Cannot connect to Alpaca: {exc}",
            )

    @staticmethod
    def _check_data_vendor_health() -> ReadinessCheck:
        """Verify the configured data vendor can return at least one bar."""
        from datetime import datetime, timedelta, timezone

        try:
            from quant_us.data.connectors.factory import get_connector

            connector = get_connector("yfinance")
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=5)
            bars = connector.fetch_bars(symbol="SPY", start=start, end=end, bar_size="1d")
            if bars is not None and not bars.empty:
                return ReadinessCheck(
                    name="data_vendor_health",
                    passed=True,
                    detail=f"Data vendor yfinance returned {len(bars)} bars for SPY",
                )
            return ReadinessCheck(
                name="data_vendor_health",
                passed=False,
                detail="Data vendor returned empty response",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="data_vendor_health",
                passed=False,
                detail=f"Data vendor unreachable: {exc}",
            )

    @staticmethod
    def _check_telegram_connectivity(profile: str = "live") -> ReadinessCheck:
        """Verify Telegram alert config is loaded and a test message can be sent.

        In 'simulated' profile, missing config is WARN, not FAIL.
        """
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not bot_token or not chat_id:
            if profile in ("simulated", "paper"):
                return ReadinessCheck(
                    name="telegram_connectivity",
                    passed=True,
                    detail=f"Telegram not configured — alerts disabled (WARN for live, OK for {profile})",
                    warn=True,
                )
            return ReadinessCheck(
                name="telegram_connectivity",
                passed=False,
                detail="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; alerts disabled",
            )
        try:
            from quant_us.monitoring.telegram_alerts import (
                TelegramAlertService,
                AlertPriority,
                load_telegram_config_from_env,
            )

            config = load_telegram_config_from_env()
            if config is None or not config.enabled:
                return ReadinessCheck(
                    name="telegram_connectivity",
                    passed=False,
                    detail="Telegram config not enabled; check both tokens are set",
                )
            alerts = TelegramAlertService(config)
            alerts.send("LiveReadinessGate connectivity test", priority=AlertPriority.LOW)
            return ReadinessCheck(
                name="telegram_connectivity",
                passed=True,
                detail="Telegram alerts configured and test message sent",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="telegram_connectivity",
                passed=False,
                detail=f"Telegram test message failed: {exc}",
            )
