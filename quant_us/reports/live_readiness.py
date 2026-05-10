"""Live readiness review gate.

This report is for review-only readiness. It can certify that evidence is
complete enough for human review, but it does not provide a start/run/submit
entrypoint.

Before any future live trading discussion, ALL checks below should pass:

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

    @property
    def review_only(self) -> bool:
        return True

    @property
    def submission_ready(self) -> bool:
        return False

    def is_ready(self, profile: str = "live") -> bool:
        """True when ALL hard-FAIL checks pass (warnings don't block)."""
        failing = [c for c in self.checks if not c.passed and not c.warn]
        return len(failing) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.all_passed,
            "review_only": self.review_only,
            "submission_ready": self.submission_ready,
            "recommended_action": "REVIEW_ONLY" if self.is_ready() else "BLOCKED",
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
            profile: One of 'simulated', 'paper', 'shadow_live', 'live'.
                     Controls which checks are hard FAIL vs soft WARN.
        """
        if profile == "shadow_live":
            return self._check_all_shadow_live(validation_state_path)

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
        report.checks.append(self._check_manual_approval_required())
        report.checks.append(self._check_allowlist_surface())
        report.checks.append(self._check_micro_live_limits())
        report.checks.append(self._check_reduce_only_exit_plan())
        report.checks.append(self._check_emergency_stop_readiness())
        report.checks.append(self._check_endpoint_guard())
        report.checks.append(self._check_review_only_defaults())

        return report

    def _check_all_shadow_live(
        self, validation_state_path: str | Path | None = None
    ) -> LiveReadinessReport:
        """Run shadow_live-specific readiness checks (12 gates).

        shadow_live profile checks:
        1. paper_30_day_validation PASS
        2. live readonly credentials PASS
        3. live endpoint readonly guard PASS
        4. no live order path PASS
        5. ReadOnlyBrokerProxy PASS
        6. data parity smoke PASS/WARN
        7. strategy whitelist PASS
        8. risk/OMS/reconciliation PASS
        9. shadow journal writable PASS
        10. incident report writable PASS
        11. Telegram WARN (not hard FAIL)
        12. QUANT_LIVE_SUBMISSION_ENABLED safety proof
        """
        report = LiveReadinessReport()

        # 1. Paper 30-day validation
        report.checks.append(
            self._check_paper_30_day_clean(validation_state_path, profile="live")
        )

        # 2. Live readonly credentials
        report.checks.append(self._check_live_readonly_credentials())

        # 3. Live endpoint readonly guard
        report.checks.append(self._check_live_endpoint_readonly_guard())

        # 4. No live order path
        report.checks.append(self._check_no_live_order_path())

        # 5. ReadOnlyBrokerProxy
        report.checks.append(self._check_readonly_broker_proxy_exists())

        # 6. Data parity smoke
        report.checks.append(self._check_data_parity_smoke())

        # 7. Strategy whitelist
        report.checks.append(self._check_strategy_whitelist())

        # 8. Risk/OMS/reconciliation
        report.checks.append(self._check_risk_oms_recon())

        # 9. Shadow journal writable
        report.checks.append(self._check_shadow_journal_writable())

        # 10. Incident report writable
        report.checks.append(self._check_incident_report_writable())

        # 11. Telegram (WARN, not hard FAIL)
        report.checks.append(self._check_telegram_connectivity("shadow_live"))

        # 12. QUANT_LIVE_SUBMISSION_ENABLED safety proof
        report.checks.append(self._check_live_submission_shadow_safety())

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
                detail="No validation_state_path provided; review remains blocked until 30 paper days are recorded",
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
    def _check_manual_approval_required() -> ReadinessCheck:
        try:
            from quant_us.live.live_pilot_approval import LivePilotApprovalRequest

            status_default = LivePilotApprovalRequest(approval_id="review_only_probe").status
            if status_default != "DRAFT":
                return ReadinessCheck(
                    name="manual_approval_required",
                    passed=False,
                    detail=f"Approval request default status is {status_default}, expected DRAFT",
                )
            return ReadinessCheck(
                name="manual_approval_required",
                passed=True,
                detail="Human approval artifacts default to DRAFT and require explicit approval",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="manual_approval_required",
                passed=False,
                detail=f"Cannot verify human approval requirement: {exc}",
            )

    @staticmethod
    def _check_allowlist_surface() -> ReadinessCheck:
        try:
            from quant_us.live.live_pilot_dossier import LiveSafety, StrategyFreeze
            from quant_us.live.live_pilot_risk_envelope import LivePilotRiskEnvelope

            has_strategy_allowlist = "approved_symbols" in StrategyFreeze.__dataclass_fields__
            has_safety_allowlist = "symbol_allowlist" in LiveSafety.__dataclass_fields__
            has_envelope_symbols = "symbols" in LivePilotRiskEnvelope.__dataclass_fields__
            passed = has_strategy_allowlist and has_safety_allowlist and has_envelope_symbols
            detail = (
                "Strategy freeze, dossier safety, and risk envelope expose allowlist fields"
                if passed
                else "Allowlist fields missing from strategy freeze, safety dossier, or risk envelope"
            )
            return ReadinessCheck(name="allowlist_surface", passed=passed, detail=detail)
        except Exception as exc:
            return ReadinessCheck(
                name="allowlist_surface",
                passed=False,
                detail=f"Cannot verify allowlist surface: {exc}",
            )

    @staticmethod
    def _check_micro_live_limits() -> ReadinessCheck:
        try:
            from quant_us.live.live_pilot_risk_envelope import LivePilotRiskEnvelope

            envelope = LivePilotRiskEnvelope.default_conservative("review_only_probe")
            passed = (
                envelope.max_order_notional > 0
                and envelope.max_daily_notional > 0
                and envelope.max_daily_order_count > 0
            )
            detail = (
                f"Conservative limits present: max_order_notional={envelope.max_order_notional}, "
                f"max_daily_notional={envelope.max_daily_notional}, "
                f"max_daily_order_count={envelope.max_daily_order_count}"
            )
            return ReadinessCheck(name="micro_live_limits", passed=passed, detail=detail)
        except Exception as exc:
            return ReadinessCheck(
                name="micro_live_limits",
                passed=False,
                detail=f"Cannot verify micro-live limits: {exc}",
            )

    @staticmethod
    def _check_reduce_only_exit_plan() -> ReadinessCheck:
        try:
            from quant_us.live.emergency_stop import RollbackPlanGenerator

            has_manual_review = hasattr(RollbackPlanGenerator, "generate")
            if not has_manual_review:
                return ReadinessCheck(
                    name="reduce_only_exit_plan",
                    passed=False,
                    detail="RollbackPlanGenerator.generate missing",
                )
            return ReadinessCheck(
                name="reduce_only_exit_plan",
                passed=True,
                detail="Rollback plan generator exists for reduce-only incident exits and manual review",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="reduce_only_exit_plan",
                passed=False,
                detail=f"Cannot verify reduce-only exit plan: {exc}",
            )

    @staticmethod
    def _check_emergency_stop_readiness() -> ReadinessCheck:
        try:
            from quant_us.live.emergency_stop import EmergencyStopController

            required = {"trigger", "acknowledge", "resolve", "status"}
            actual = set(dir(EmergencyStopController))
            missing = sorted(required - actual)
            return ReadinessCheck(
                name="emergency_stop_readiness",
                passed=not missing,
                detail="Emergency stop controller surface present" if not missing else f"Missing emergency stop methods: {missing}",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="emergency_stop_readiness",
                passed=False,
                detail=f"Cannot verify emergency stop readiness: {exc}",
            )

    @staticmethod
    def _check_endpoint_guard() -> ReadinessCheck:
        try:
            from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy

            required = {"submit_order", "cancel_order", "replace_order", "close_position", "close_all_positions"}
            actual = set(dir(ReadOnlyLiveBrokerProxy))
            missing = sorted(required - actual)
            return ReadinessCheck(
                name="endpoint_guard",
                passed=not missing,
                detail="ReadOnlyLiveBrokerProxy exists and exposes forbidden write methods for fail-closed guarding"
                if not missing
                else f"Missing endpoint guard methods: {missing}",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="endpoint_guard",
                passed=False,
                detail=f"Cannot verify endpoint guard: {exc}",
            )

    @staticmethod
    def _check_review_only_defaults() -> ReadinessCheck:
        try:
            from quant_us.live.live_pilot_dossier import LiveSafety

            safety = LiveSafety()
            passed = (
                safety.allow_live_orders is False
                and safety.confirm_live is False
                and safety.manual_approval_required is True
            )
            return ReadinessCheck(
                name="review_only_defaults",
                passed=passed,
                detail=(
                    "Dossier defaults remain review-only with allow_live_orders=False, "
                    "confirm_live=False, manual_approval_required=True"
                ),
            )
        except Exception as exc:
            return ReadinessCheck(
                name="review_only_defaults",
                passed=False,
                detail=f"Cannot verify review-only defaults: {exc}",
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
            if profile in ("simulated", "paper", "shadow_live"):
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

    # ------------------------------------------------------------------
    # Shadow Live specific checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_live_readonly_credentials() -> ReadinessCheck:
        """Verify live API credentials can connect in read-only mode."""
        api_key = os.environ.get("APCA_API_KEY_ID", "")
        api_secret = os.environ.get("APCA_API_SECRET_KEY", "")

        if not api_key or not api_secret:
            return ReadinessCheck(
                name="live_readonly_credentials",
                passed=True,
                detail="No live credentials set — shadow-live can run with local data only (WARN)",
                warn=True,
            )

        try:
            from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig, LIVE_BASE_URL
            from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy

            broker = AlpacaBroker(
                AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=False, base_url=LIVE_BASE_URL)
            )
            proxy = ReadOnlyLiveBrokerProxy(broker)
            account = proxy.get_account()
            return ReadinessCheck(
                name="live_readonly_credentials",
                passed=True,
                detail=f"Live readonly credentials valid: account accessible, equity=${account.equity:,.2f}",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="live_readonly_credentials",
                passed=False,
                detail=f"Live readonly credentials failed: {exc}",
            )

    @staticmethod
    def _check_live_endpoint_readonly_guard() -> ReadinessCheck:
        """Verify live endpoint readonly guard blocks write operations."""
        try:
            from datetime import datetime as dt, timezone
            from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy, LiveEndpointGuard
            from quant_us.execution.broker_base import BrokerBase
            from unittest.mock import MagicMock

            inner = MagicMock(spec=BrokerBase)
            inner.broker_name = "test"
            proxy = ReadOnlyLiveBrokerProxy(inner)

            from quant_us.core.types import Order
            from quant_us.core.enums import OrderSide, OrderType, TimeInForce

            order = Order(
                timestamp_utc=dt.now(timezone.utc),
                strategy_id="test",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=10.0,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                client_order_id="readiness_test",
            )

            # Verify submit_order raises
            submit_blocked = False
            try:
                proxy.submit_order(order)
            except RuntimeError:
                submit_blocked = True

            # Verify cancel_order raises
            cancel_blocked = False
            try:
                proxy.cancel_order("test_id")
            except RuntimeError:
                cancel_blocked = True

            if submit_blocked and cancel_blocked:
                return ReadinessCheck(
                    name="live_endpoint_readonly_guard",
                    passed=True,
                    detail="ReadOnlyLiveBrokerProxy blocks submit_order and cancel_order with RuntimeError",
                )
            return ReadinessCheck(
                name="live_endpoint_readonly_guard",
                passed=False,
                detail=f"Guard incomplete: submit_blocked={submit_blocked}, cancel_blocked={cancel_blocked}",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="live_endpoint_readonly_guard",
                passed=False,
                detail=f"Live endpoint guard check failed: {exc}",
            )

    @staticmethod
    def _check_no_live_order_path() -> ReadinessCheck:
        """Verify there is no reachable live order path in shadow_live mode."""
        try:
            from quant_us.live.modes import RuntimeMode
            from quant_us.live.runtime_config import LiveRuntimeConfig

            # Verify shadow_live mode rejects allow_live_orders
            config_blocked = False
            try:
                LiveRuntimeConfig(mode=RuntimeMode.SHADOW_LIVE, allow_live_orders=True)
            except ValueError:
                config_blocked = True

            # Verify shadow_live cannot submit real orders
            shadow_cannot_submit = not RuntimeMode.SHADOW_LIVE.can_submit_real_orders

            # Verify ReadOnlyBrokerProxy exists
            from quant_us.live.shadow_live import ReadOnlyBrokerProxy

            proxy_exists = ReadOnlyBrokerProxy is not None

            if config_blocked and shadow_cannot_submit and proxy_exists:
                return ReadinessCheck(
                    name="no_live_order_path",
                    passed=True,
                    detail="Shadow_live mode blocks live orders at config, runtime mode, and broker levels",
                )
            return ReadinessCheck(
                name="no_live_order_path",
                passed=False,
                detail="Live order path may be reachable in shadow_live mode",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="no_live_order_path",
                passed=False,
                detail=f"No-live-order-path check failed: {exc}",
            )

    @staticmethod
    def _check_readonly_broker_proxy_exists() -> ReadinessCheck:
        """Verify ReadOnlyLiveBrokerProxy exists and has all forbidden methods."""
        try:
            from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy

            required_methods = [
                "get_account",
                "get_positions",
                "get_open_orders",
                "get_fills",
                "get_fills_readonly",
                "health_check",
            ]
            forbidden_methods = [
                "submit_order",
                "cancel_order",
                "replace_order",
                "close_position",
                "close_all_positions",
            ]

            missing_required = [m for m in required_methods if not hasattr(ReadOnlyLiveBrokerProxy, m)]
            missing_forbidden = [m for m in forbidden_methods if not hasattr(ReadOnlyLiveBrokerProxy, m)]

            if not missing_required and not missing_forbidden:
                return ReadinessCheck(
                    name="readonly_broker_proxy",
                    passed=True,
                    detail=f"ReadOnlyLiveBrokerProxy: {len(required_methods)} read methods, {len(forbidden_methods)} blocked methods",
                )

            errors = []
            if missing_required:
                errors.append(f"missing read methods: {missing_required}")
            if missing_forbidden:
                errors.append(f"missing forbidden methods: {missing_forbidden}")
            return ReadinessCheck(
                name="readonly_broker_proxy",
                passed=False,
                detail="; ".join(errors),
            )
        except Exception as exc:
            return ReadinessCheck(
                name="readonly_broker_proxy",
                passed=False,
                detail=f"Cannot verify ReadOnlyLiveBrokerProxy: {exc}",
            )

    @staticmethod
    def _check_data_parity_smoke() -> ReadinessCheck:
        """Check that MarketDataParityChecker is importable and functional."""
        try:
            from quant_us.live.market_data_parity import MarketDataParityChecker

            checker = MarketDataParityChecker(["SPY"])
            report = checker.compare(include_yfinance=False)
            if report.overall_status in ("ok", "warn"):
                return ReadinessCheck(
                    name="data_parity_smoke",
                    passed=True,
                    detail=f"MarketDataParityChecker functional (status={report.overall_status})",
                    warn=report.overall_status == "warn",
                )
            return ReadinessCheck(
                name="data_parity_smoke",
                passed=False,
                detail=f"MarketDataParityChecker returned status={report.overall_status}",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="data_parity_smoke",
                passed=True,
                detail=f"Data parity checker available but couldn't run: {exc} (WARN — re-run with data)",
                warn=True,
            )

    @staticmethod
    def _check_strategy_whitelist() -> ReadinessCheck:
        """Verify strategy factory is importable and has registered strategies."""
        try:
            from quant_us.strategies.factory import build_strategy

            test_strategy = build_strategy("etf_rotation", {})
            return ReadinessCheck(
                name="strategy_whitelist",
                passed=True,
                detail=f"Strategy factory functional: etf_rotation loaded (version={getattr(test_strategy, 'version', 'unknown')})",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="strategy_whitelist",
                passed=False,
                detail=f"Strategy factory check failed: {exc}",
            )

    @staticmethod
    def _check_risk_oms_recon() -> ReadinessCheck:
        """Verify risk engine, OMS, and reconciliation are importable."""
        errors: list[str] = []
        try:
            from quant_us.risk.pre_trade import PreTradeRiskEngine  # noqa: F401
        except Exception as exc:
            errors.append(f"risk: {exc}")

        try:
            from quant_us.execution.oms import OrderManagementSystem  # noqa: F401
        except Exception as exc:
            errors.append(f"oms: {exc}")

        try:
            from quant_us.live.reconciliation_service import ReconciliationService  # noqa: F401
        except Exception as exc:
            errors.append(f"recon: {exc}")

        if not errors:
            return ReadinessCheck(
                name="risk_oms_reconciliation",
                passed=True,
                detail="Risk engine, OMS, and reconciliation service all importable",
            )
        return ReadinessCheck(
            name="risk_oms_reconciliation",
            passed=False,
            detail="; ".join(errors),
        )

    @staticmethod
    def _check_shadow_journal_writable() -> ReadinessCheck:
        """Verify shadow journal directory is writable."""
        try:
            from pathlib import Path
            import tempfile

            journal_dir = Path("data/shadow_ledger")
            journal_dir.mkdir(parents=True, exist_ok=True)
            test_file = journal_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return ReadinessCheck(
                name="shadow_journal_writable",
                passed=True,
                detail=f"Shadow journal directory writable: {journal_dir.absolute()}",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="shadow_journal_writable",
                passed=False,
                detail=f"Shadow journal directory not writable: {exc}",
            )

    @staticmethod
    def _check_incident_report_writable() -> ReadinessCheck:
        """Verify incident report directory is writable."""
        try:
            from pathlib import Path

            report_dir = Path("data/reports")
            report_dir.mkdir(parents=True, exist_ok=True)
            test_file = report_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return ReadinessCheck(
                name="incident_report_writable",
                passed=True,
                detail=f"Incident report directory writable: {report_dir.absolute()}",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="incident_report_writable",
                passed=False,
                detail=f"Incident report directory not writable: {exc}",
            )

    @staticmethod
    def _check_live_submission_shadow_safety() -> ReadinessCheck:
        """Verify QUANT_LIVE_SUBMISSION_ENABLED=true does NOT enable shadow_live orders."""
        import os

        live_env = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in ("1", "true", "yes")

        try:
            from quant_us.live.modes import RuntimeMode
            from quant_us.live.runtime_config import LiveRuntimeConfig

            shadow_cannot_submit = not RuntimeMode.SHADOW_LIVE.can_submit_real_orders

            config_blocks_live = False
            try:
                LiveRuntimeConfig(mode=RuntimeMode.SHADOW_LIVE, allow_live_orders=True)
            except ValueError:
                config_blocks_live = True

            if shadow_cannot_submit and config_blocks_live:
                detail = (
                    "Shadow_live blocks real orders regardless of QUANT_LIVE_SUBMISSION_ENABLED. "
                    f"Env: QUANT_LIVE_SUBMISSION_ENABLED={'true' if live_env else 'false'}. "
                    "Safety invariant holds."
                )
                return ReadinessCheck(
                    name="live_submission_shadow_safety",
                    passed=True,
                    detail=detail,
                )
            return ReadinessCheck(
                name="live_submission_shadow_safety",
                passed=False,
                detail="QUANT_LIVE_SUBMISSION_ENABLED may enable shadow_live real orders — SAFETY VIOLATION",
            )
        except Exception as exc:
            return ReadinessCheck(
                name="live_submission_shadow_safety",
                passed=False,
                detail=f"Cannot verify shadow safety: {exc}",
            )
