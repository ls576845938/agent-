"""Live Pilot Risk Envelope for G3 Small Live Pilot.

Defines ultra-conservative risk boundaries for the first live pilot.
All limits are deliberately tiny and restrictive. No market orders,
no pre/post-market, no short selling, no margin, no options.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.enums import OrderSide, OrderType

_logger = logging.getLogger("live_pilot_risk_envelope")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Risk Envelope
# ---------------------------------------------------------------------------


@dataclass
class LivePilotRiskEnvelope:
    envelope_id: str
    strategy_id: str = ""
    strategy_version: str = ""
    symbols: list[str] = field(default_factory=list)
    max_total_capital: float = 1000.0
    max_order_notional: float = 100.0
    max_daily_notional: float = 300.0
    max_daily_order_count: int = 3
    max_gross_exposure_pct: float = 0.10
    max_single_symbol_exposure_pct: float = 0.05
    max_daily_loss_pct: float = 0.005
    max_drawdown_pct: float = 0.02
    max_consecutive_losses: int = 3
    allow_fractional: bool = False
    allow_market_order: bool = False
    allow_pre_post_market: bool = False
    allow_short: bool = False
    allow_margin: bool = False
    allow_options: bool = False
    allowed_order_types: list[str] = field(default_factory=lambda: ["limit"])
    allowed_sessions: list[str] = field(default_factory=lambda: ["regular"])
    reduce_only_on_warning: bool = True
    force_stop_on_recon_fail: bool = True
    force_stop_on_data_stale: bool = True
    force_stop_on_broker_error: bool = True
    created_at: str = ""
    approved_by: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbols": self.symbols,
            "max_total_capital": self.max_total_capital,
            "max_order_notional": self.max_order_notional,
            "max_daily_notional": self.max_daily_notional,
            "max_daily_order_count": self.max_daily_order_count,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "max_single_symbol_exposure_pct": self.max_single_symbol_exposure_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_consecutive_losses": self.max_consecutive_losses,
            "allow_fractional": self.allow_fractional,
            "allow_market_order": self.allow_market_order,
            "allow_pre_post_market": self.allow_pre_post_market,
            "allow_short": self.allow_short,
            "allow_margin": self.allow_margin,
            "allow_options": self.allow_options,
            "allowed_order_types": self.allowed_order_types,
            "allowed_sessions": self.allowed_sessions,
            "reduce_only_on_warning": self.reduce_only_on_warning,
            "force_stop_on_recon_fail": self.force_stop_on_recon_fail,
            "force_stop_on_data_stale": self.force_stop_on_data_stale,
            "force_stop_on_broker_error": self.force_stop_on_broker_error,
            "created_at": self.created_at,
            "approved_by": self.approved_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LivePilotRiskEnvelope":
        return cls(
            envelope_id=data.get("envelope_id", ""),
            strategy_id=data.get("strategy_id", ""),
            strategy_version=data.get("strategy_version", ""),
            symbols=data.get("symbols", []),
            max_total_capital=data.get("max_total_capital", 1000.0),
            max_order_notional=data.get("max_order_notional", 100.0),
            max_daily_notional=data.get("max_daily_notional", 300.0),
            max_daily_order_count=data.get("max_daily_order_count", 3),
            max_gross_exposure_pct=data.get("max_gross_exposure_pct", 0.10),
            max_single_symbol_exposure_pct=data.get("max_single_symbol_exposure_pct", 0.05),
            max_daily_loss_pct=data.get("max_daily_loss_pct", 0.005),
            max_drawdown_pct=data.get("max_drawdown_pct", 0.02),
            max_consecutive_losses=data.get("max_consecutive_losses", 3),
            allow_fractional=data.get("allow_fractional", False),
            allow_market_order=data.get("allow_market_order", False),
            allow_pre_post_market=data.get("allow_pre_post_market", False),
            allow_short=data.get("allow_short", False),
            allow_margin=data.get("allow_margin", False),
            allow_options=data.get("allow_options", False),
            allowed_order_types=data.get("allowed_order_types", ["limit"]),
            allowed_sessions=data.get("allowed_sessions", ["regular"]),
            reduce_only_on_warning=data.get("reduce_only_on_warning", True),
            force_stop_on_recon_fail=data.get("force_stop_on_recon_fail", True),
            force_stop_on_data_stale=data.get("force_stop_on_data_stale", True),
            force_stop_on_broker_error=data.get("force_stop_on_broker_error", True),
            created_at=data.get("created_at", ""),
            approved_by=data.get("approved_by", ""),
        )

    @classmethod
    def default_conservative(cls, envelope_id: str) -> "LivePilotRiskEnvelope":
        """Create an ultra-conservative envelope suitable for first live pilot."""
        return cls(envelope_id=envelope_id)


# ---------------------------------------------------------------------------
# Risk validators
# ---------------------------------------------------------------------------


@dataclass
class RiskCheckResult:
    passed: bool
    reason: str = ""
    checks: dict[str, bool] = field(default_factory=dict)


class CapitalLimiter:
    """Enforce max total capital limit."""

    def check(self, envelope: LivePilotRiskEnvelope, proposed_capital: float) -> RiskCheckResult:
        ok = proposed_capital <= envelope.max_total_capital
        return RiskCheckResult(
            passed=ok,
            reason=(
                f"Capital ${proposed_capital:,.2f} within limit ${envelope.max_total_capital:,.2f}"
                if ok
                else f"Capital ${proposed_capital:,.2f} exceeds limit ${envelope.max_total_capital:,.2f}"
            ),
            checks={"capital_within_limit": ok},
        )


class NotionalLimiter:
    """Enforce max order notional and daily notional limits."""

    def check(
        self,
        envelope: LivePilotRiskEnvelope,
        order_notional: float,
        daily_notional_used: float = 0.0,
    ) -> RiskCheckResult:
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        order_ok = order_notional <= envelope.max_order_notional
        checks["order_notional_within_limit"] = order_ok
        if not order_ok:
            reasons.append(
                f"Order notional ${order_notional:,.2f} exceeds limit ${envelope.max_order_notional:,.2f}"
            )

        daily_ok = (daily_notional_used + order_notional) <= envelope.max_daily_notional
        checks["daily_notional_within_limit"] = daily_ok
        if not daily_ok:
            reasons.append(
                f"Daily notional would be ${daily_notional_used + order_notional:,.2f}, exceeds ${envelope.max_daily_notional:,.2f}"
            )

        return RiskCheckResult(
            passed=order_ok and daily_ok,
            reason="; ".join(reasons) if reasons else "Notional limits OK",
            checks=checks,
        )


class ExposureLimiter:
    """Enforce gross and single-symbol exposure limits."""

    def check(
        self,
        envelope: LivePilotRiskEnvelope,
        gross_exposure_pct: float,
        max_single_exposure_pct: float = 0.0,
    ) -> RiskCheckResult:
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        gross_ok = gross_exposure_pct <= envelope.max_gross_exposure_pct
        checks["gross_exposure_within_limit"] = gross_ok
        if not gross_ok:
            reasons.append(
                f"Gross exposure {gross_exposure_pct:.2%} exceeds limit {envelope.max_gross_exposure_pct:.2%}"
            )

        single_ok = max_single_exposure_pct <= envelope.max_single_symbol_exposure_pct
        checks["single_symbol_exposure_within_limit"] = single_ok
        if not single_ok:
            reasons.append(
                f"Single symbol exposure {max_single_exposure_pct:.2%} exceeds limit {envelope.max_single_symbol_exposure_pct:.2%}"
            )

        return RiskCheckResult(
            passed=gross_ok and single_ok,
            reason="; ".join(reasons) if reasons else "Exposure limits OK",
            checks=checks,
        )


class OrderTypeValidator:
    """Enforce order type and session restrictions."""

    def check(
        self,
        envelope: LivePilotRiskEnvelope,
        order_type: OrderType,
        side: OrderSide,
        session: str = "regular",
    ) -> RiskCheckResult:
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        if not envelope.allow_market_order:
            checks["not_market_order"] = order_type != OrderType.MARKET
            if not checks["not_market_order"]:
                reasons.append("Market orders not allowed in live pilot")

        if order_type == OrderType.MARKET and envelope.allow_market_order:
            checks["order_type_allowed"] = True
        else:
            checks["order_type_allowed"] = order_type.value in envelope.allowed_order_types
            if not checks["order_type_allowed"]:
                reasons.append(f"Order type {order_type.value} not in allowed types: {envelope.allowed_order_types}")

        if not envelope.allow_pre_post_market:
            checks["session_allowed"] = session in envelope.allowed_sessions
            if not checks["session_allowed"]:
                reasons.append(f"Session '{session}' not in allowed: {envelope.allowed_sessions}")

        if not envelope.allow_short:
            checks["not_short"] = side != OrderSide.SELL
            if not checks["not_short"]:
                reasons.append("Short selling not allowed in live pilot")

        if not envelope.allow_margin:
            checks["no_margin"] = True

        if not envelope.allow_options:
            checks["no_options"] = True

        return RiskCheckResult(
            passed=all(checks.values()),
            reason="; ".join(reasons) if reasons else "Order type/session OK",
            checks=checks,
        )


class LossLimiter:
    """Enforce daily loss and drawdown limits."""

    def check(
        self,
        envelope: LivePilotRiskEnvelope,
        daily_loss_pct: float,
        current_drawdown_pct: float,
        consecutive_losses: int,
    ) -> RiskCheckResult:
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        loss_ok = daily_loss_pct <= envelope.max_daily_loss_pct
        checks["daily_loss_within_limit"] = loss_ok
        if not loss_ok:
            reasons.append(
                f"Daily loss {daily_loss_pct:.2%} exceeds limit {envelope.max_daily_loss_pct:.2%}"
            )

        dd_ok = current_drawdown_pct <= envelope.max_drawdown_pct
        checks["drawdown_within_limit"] = dd_ok
        if not dd_ok:
            reasons.append(
                f"Drawdown {current_drawdown_pct:.2%} exceeds limit {envelope.max_drawdown_pct:.2%}"
            )

        cons_ok = consecutive_losses <= envelope.max_consecutive_losses
        checks["consecutive_losses_within_limit"] = cons_ok
        if not cons_ok:
            reasons.append(
                f"Consecutive losses {consecutive_losses} exceeds limit {envelope.max_consecutive_losses}"
            )

        return RiskCheckResult(
            passed=loss_ok and dd_ok and cons_ok,
            reason="; ".join(reasons) if reasons else "Loss limits OK",
            checks=checks,
        )


# ---------------------------------------------------------------------------
# Risk Envelope Manager
# ---------------------------------------------------------------------------


class RiskEnvelopeManager:
    """CRUD and validation for risk envelopes."""

    def __init__(self, store_path: str = "data/live_pilot/envelopes") -> None:
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)

        self.capital_limiter = CapitalLimiter()
        self.notional_limiter = NotionalLimiter()
        self.exposure_limiter = ExposureLimiter()
        self.order_validator = OrderTypeValidator()
        self.loss_limiter = LossLimiter()

    def create(self, envelope: LivePilotRiskEnvelope) -> LivePilotRiskEnvelope:
        self._save(envelope)
        self._audit("envelope_created", {"envelope_id": envelope.envelope_id})
        return envelope

    def load(self, envelope_id: str) -> LivePilotRiskEnvelope | None:
        path = self.store_path / f"{envelope_id}.json"
        if not path.exists():
            return None
        try:
            return LivePilotRiskEnvelope.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            return None

    def validate(
        self,
        envelope_id: str,
        order_notional: float = 0.0,
        daily_notional_used: float = 0.0,
        gross_exposure_pct: float = 0.0,
        max_single_exposure_pct: float = 0.0,
        order_type: OrderType | None = None,
        side: OrderSide | None = None,
        session: str = "regular",
        daily_loss_pct: float = 0.0,
        current_drawdown_pct: float = 0.0,
        consecutive_losses: int = 0,
        recon_fail: bool = False,
        data_stale: bool = False,
        broker_error: bool = False,
    ) -> dict[str, Any]:
        envelope = self.load(envelope_id)
        if envelope is None:
            return {"passed": False, "reason": f"Envelope {envelope_id} not found"}

        results: dict[str, Any] = {
            "envelope_id": envelope_id,
            "passed": True,
            "checks": {},
            "reduce_only": False,
        }

        results["checks"]["capital"] = {
            "limit": envelope.max_total_capital,
            "result": "ok",
        }

        notional = self.notional_limiter.check(envelope, order_notional, daily_notional_used)
        results["checks"]["notional"] = notional.checks
        if not notional.passed:
            results["passed"] = False
            results["reason"] = notional.reason

        exposure = self.exposure_limiter.check(envelope, gross_exposure_pct, max_single_exposure_pct)
        results["checks"]["exposure"] = exposure.checks
        if not exposure.passed:
            results["passed"] = False

        if order_type and side:
            order_check = self.order_validator.check(envelope, order_type, side, session)
            results["checks"]["order_type"] = order_check.checks
            if not order_check.passed:
                results["passed"] = False

        loss_check = self.loss_limiter.check(
            envelope, daily_loss_pct, current_drawdown_pct, consecutive_losses
        )
        results["checks"]["loss"] = loss_check.checks
        if not loss_check.passed:
            results["passed"] = False

        if recon_fail and envelope.force_stop_on_recon_fail:
            results["reduce_only"] = True
            results["checks"]["recon"] = {"force_stop": True}
        if data_stale and envelope.force_stop_on_data_stale:
            results["reduce_only"] = True
            results["checks"]["data_stale"] = {"force_stop": True}
        if broker_error and envelope.force_stop_on_broker_error:
            results["reduce_only"] = True
            results["checks"]["broker_error"] = {"force_stop": True}

        return results

    def _save(self, envelope: LivePilotRiskEnvelope) -> None:
        path = self.store_path / f"{envelope.envelope_id}.json"
        path.write_text(json.dumps(envelope.to_dict(), indent=2, default=str))

    def _audit(self, event: str, data: dict[str, Any]) -> None:
        audit_path = self.store_path / "envelope_audit.jsonl"
        entry = {"timestamp": _utc_now().isoformat(), "event": event, "data": data}
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
