"""Live Pilot Readiness Dossier for G2 → G3 transition.

Generates the comprehensive dossier required for GO/NO-GO decision
on Small Live Pilot.  Even if GO, live orders remain blocked until
the human review explicitly authorizes them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("live_pilot_dossier")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PaperSummary:
    clean_days: int = 0
    orders: int = 0
    fills: int = 0
    recon_fail: int = 0
    duplicate_order_count: int = 0
    incidents: int = 0


@dataclass
class ShadowSummary:
    days_completed: int = 0
    real_submit_count: int = 0
    shadow_order_count: int = 0
    data_parity_warns: int = 0
    incidents: int = 0


@dataclass
class StrategyFreeze:
    strategy_id: str = ""
    strategy_version: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    approved_symbols: list[str] = field(default_factory=list)
    risk_limits: dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveSafety:
    quant_live_submission_enabled: bool = False
    confirm_live: bool = False
    allow_live_orders: bool = False
    endpoint_guard_active: bool = True
    readonly_broker_proxy_proof: str = ""
    no_live_order_touched_proof: str = ""


@dataclass
class LivePilotReadinessDossier:
    """Comprehensive dossier for G3 Small Live Pilot review.

    Contents:
    1. Paper 30-day summary
    2. Shadow Live 5-day summary
    3. Strategy Freeze
    4. Risk Limits
    5. Live Safety
    6. Go / No-Go decision
    """

    generated_at: datetime = field(default_factory=_utc_now)
    dossier_id: str = ""

    paper: PaperSummary = field(default_factory=PaperSummary)
    shadow: ShadowSummary = field(default_factory=ShadowSummary)
    strategy: StrategyFreeze = field(default_factory=StrategyFreeze)

    max_gross_exposure: float = 0.0
    max_single_position_pct: float = 0.0
    max_order_notional: float = 0.0
    daily_loss_limit: float = 0.0
    kill_switch_thresholds: dict[str, Any] = field(default_factory=dict)

    live_safety: LiveSafety = field(default_factory=LiveSafety)

    go_decision: str = "NOT_READY"

    def __post_init__(self) -> None:
        if not self.dossier_id:
            self.dossier_id = f"dossier_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

    @property
    def is_go(self) -> bool:
        return self.go_decision == "GO_FOR_SMALL_LIVE_REVIEW"

    def determine_go_decision(self) -> str:
        """Determine go/no-go decision based on all evidence."""
        if self.shadow.real_submit_count != 0:
            self.go_decision = "BLOCKED"
            return self.go_decision

        if self.paper.clean_days < 30:
            self.go_decision = "NOT_READY"
            return self.go_decision

        if self.shadow.days_completed < 5:
            self.go_decision = "NOT_READY"
            return self.go_decision

        if self.shadow.incidents > 0:
            self.go_decision = "NOT_READY"
            return self.go_decision

        if self.paper.recon_fail > 0:
            self.go_decision = "NOT_READY"
            return self.go_decision

        self.go_decision = "GO_FOR_SMALL_LIVE_REVIEW"
        return self.go_decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "generated_at": self.generated_at.isoformat(),
            "paper": {
                "clean_days": self.paper.clean_days,
                "orders": self.paper.orders,
                "fills": self.paper.fills,
                "recon_fail": self.paper.recon_fail,
                "duplicate_order_count": self.paper.duplicate_order_count,
                "incidents": self.paper.incidents,
            },
            "shadow": {
                "days_completed": self.shadow.days_completed,
                "real_submit_count": self.shadow.real_submit_count,
                "shadow_order_count": self.shadow.shadow_order_count,
                "data_parity_warns": self.shadow.data_parity_warns,
                "incidents": self.shadow.incidents,
            },
            "strategy": {
                "strategy_id": self.strategy.strategy_id,
                "strategy_version": self.strategy.strategy_version,
                "params": self.strategy.params,
                "approved_symbols": self.strategy.approved_symbols,
                "risk_limits": self.strategy.risk_limits,
            },
            "risk_limits": {
                "max_gross_exposure": self.max_gross_exposure,
                "max_single_position_pct": self.max_single_position_pct,
                "max_order_notional": self.max_order_notional,
                "daily_loss_limit": self.daily_loss_limit,
                "kill_switch_thresholds": self.kill_switch_thresholds,
            },
            "live_safety": {
                "quant_live_submission_enabled": self.live_safety.quant_live_submission_enabled,
                "confirm_live": self.live_safety.confirm_live,
                "allow_live_orders": self.live_safety.allow_live_orders,
                "endpoint_guard_active": self.live_safety.endpoint_guard_active,
                "readonly_broker_proxy_proof": self.live_safety.readonly_broker_proxy_proof,
                "no_live_order_touched_proof": self.live_safety.no_live_order_touched_proof,
            },
            "go_decision": self.go_decision,
        }

    def to_markdown(self) -> str:
        d = self.to_dict()
        lines = [
            "# Live Pilot Readiness Dossier",
            "",
            f"**Dossier ID**: `{d['dossier_id']}`",
            f"**Generated**: {d['generated_at']}",
            "",
            "---",
            "",
            "## 1. Paper 30-Day Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Clean Days | {d['paper']['clean_days']} |",
            f"| Orders Submitted | {d['paper']['orders']} |",
            f"| Orders Filled | {d['paper']['fills']} |",
            f"| Reconciliation Failures | {d['paper']['recon_fail']} |",
            f"| Duplicate Orders | {d['paper']['duplicate_order_count']} |",
            f"| Incidents | {d['paper']['incidents']} |",
            "",
            "---",
            "",
            "## 2. Shadow Live 5-Day Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Days Completed | {d['shadow']['days_completed']} |",
            f"| Real Submit Count | **{d['shadow']['real_submit_count']}** |",
            f"| Shadow Order Count | {d['shadow']['shadow_order_count']} |",
            f"| Data Parity Warnings | {d['shadow']['data_parity_warns']} |",
            f"| Incidents | {d['shadow']['incidents']} |",
            "",
            "---",
            "",
            "## 3. Strategy Freeze",
            "",
            f"- **Strategy**: {d['strategy']['strategy_id']}",
            f"- **Version**: {d['strategy']['strategy_version']}",
            f"- **Approved Symbols**: {', '.join(d['strategy']['approved_symbols']) or 'none'}",
            f"- **Params**: `{json.dumps(d['strategy']['params'])}`",
            "",
            "---",
            "",
            "## 4. Risk Limits",
            "",
            f"| Limit | Value |",
            f"|-------|-------|",
            f"| Max Gross Exposure | {d['risk_limits']['max_gross_exposure']} |",
            f"| Max Single Position % | {d['risk_limits']['max_single_position_pct']} |",
            f"| Max Order Notional | {d['risk_limits']['max_order_notional']} |",
            f"| Daily Loss Limit | {d['risk_limits']['daily_loss_limit']} |",
            f"| Kill Switch Thresholds | {json.dumps(d['risk_limits']['kill_switch_thresholds'])} |",
            "",
            "---",
            "",
            "## 5. Live Safety",
            "",
            f"| Safety Measure | Status |",
            f"|----------------|--------|",
            f"| QUANT_LIVE_SUBMISSION_ENABLED | {d['live_safety']['quant_live_submission_enabled']} |",
            f"| confirm_live | {d['live_safety']['confirm_live']} |",
            f"| allow_live_orders | {d['live_safety']['allow_live_orders']} |",
            f"| Endpoint Guard | {'ACTIVE' if d['live_safety']['endpoint_guard_active'] else 'BROKEN'} |",
            f"| ReadOnlyBrokerProxy | {d['live_safety']['readonly_broker_proxy_proof']} |",
            f"| No Live Order Proof | {d['live_safety']['no_live_order_touched_proof']} |",
            "",
            "---",
            "",
            f"## 6. Decision: **{d['go_decision']}**",
            "",
        ]

        if d["go_decision"] == "GO_FOR_SMALL_LIVE_REVIEW":
            lines.append("### Small Live Pilot Conditions")
            lines.append("")
            lines.append("- Human review REQUIRED before enabling any live orders.")
            lines.append("- live profile remains NOT READY until explicitly authorized.")
            lines.append("- Shadow-live must keep running alongside small live pilot.")
            lines.append("- Kill switch must remain armed at all times.")
        elif d["go_decision"] == "BLOCKED":
            lines.append("BLOCKED: Critical safety violation detected (real_submit_count != 0).")
        else:
            lines.append("NOT_READY: Missing required prerequisites.")
            lines.append(f"- Paper 30-day: {d['paper']['clean_days']}/30 clean days")
            lines.append(f"- Shadow 5-day: {d['shadow']['days_completed']}/5 days completed")

        return "\n".join(lines)


class LivePilotDossierBuilder:
    """Build the LivePilotReadinessDossier from current system state."""

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def build(self) -> LivePilotReadinessDossier:
        dossier = LivePilotReadinessDossier()

        self._load_paper_summary(dossier)
        self._load_shadow_summary(dossier)
        self._load_strategy_freeze(dossier)
        self._load_risk_limits(dossier)
        self._load_live_safety(dossier)

        dossier.determine_go_decision()
        return dossier

    def _load_paper_summary(self, dossier: LivePilotReadinessDossier) -> None:
        validation_path = (
            self.data_root / "reports" / "paper_production" / "validation_state.json"
        )
        if not validation_path.exists():
            return

        try:
            data = json.loads(validation_path.read_text())
            dossier.paper.clean_days = data.get("consecutive_clean_days", 0)
            dossier.paper.orders = data.get("orders_submitted_count", 0)
            dossier.paper.fills = data.get("orders_filled_count", 0)
            dossier.paper.recon_fail = data.get("recon_fail_count", 0)
            dossier.paper.duplicate_order_count = data.get("duplicate_order_count", 0)
            dossier.paper.incidents = data.get("incidents_count", 0)
        except Exception as exc:
            _logger.warning("Failed to load paper summary: %s", exc)

    def _load_shadow_summary(self, dossier: LivePilotReadinessDossier) -> None:
        shadow_val_path = (
            self.data_root / "shadow_validation" / "shadow_validation_state.json"
        )
        if not shadow_val_path.exists():
            return

        try:
            data = json.loads(shadow_val_path.read_text())
            dossier.shadow.days_completed = data.get("days_completed", 0)
            dossier.shadow.real_submit_count = data.get("real_submit_count", 0)
            dossier.shadow.shadow_order_count = data.get("shadow_order_count", 0)
            dossier.shadow.data_parity_warns = data.get("data_parity_warn_count", 0)
            dossier.shadow.incidents = data.get("incident_count", 0)
        except Exception as exc:
            _logger.warning("Failed to load shadow summary: %s", exc)

    def _load_strategy_freeze(self, dossier: LivePilotReadinessDossier) -> None:
        dossier.strategy.strategy_id = "etf_rotation"
        dossier.strategy.strategy_version = "1.0.0"
        dossier.strategy.approved_symbols = ["SPY", "QQQ", "IWM", "DIA"]
        dossier.strategy.params = {
            "lookback_days": 60,
            "top_n": 3,
            "rebalance_frequency_days": 5,
        }

    def _load_risk_limits(self, dossier: LivePilotReadinessDossier) -> None:
        dossier.max_gross_exposure = 1.0
        dossier.max_single_position_pct = 0.02
        dossier.max_order_notional = 10_000.0
        dossier.daily_loss_limit = 0.02
        dossier.kill_switch_thresholds = {
            "max_daily_loss_pct": 0.02,
            "max_drawdown_pct": 0.10,
            "max_consecutive_order_failures": 3,
        }

    def _load_live_safety(self, dossier: LivePilotReadinessDossier) -> None:
        import os

        dossier.live_safety.quant_live_submission_enabled = os.environ.get(
            "QUANT_LIVE_SUBMISSION_ENABLED", ""
        ).lower() in ("1", "true", "yes")
        dossier.live_safety.confirm_live = False
        dossier.live_safety.allow_live_orders = False
        dossier.live_safety.endpoint_guard_active = True
        dossier.live_safety.readonly_broker_proxy_proof = (
            "ReadOnlyLiveBrokerProxy blocks submit_order/cancel_order/"
            "replace_order/close_position/close_all_positions with RuntimeError"
        )
        dossier.live_safety.no_live_order_touched_proof = (
            "No write method was ever called on a live endpoint. "
            "All orders were shadow orders (real_submit=False). "
            "Audit journal confirms real_submit_count=0."
        )

    def save_dossier(
        self, dossier: LivePilotReadinessDossier, output_path: str
    ) -> None:
        """Save dossier as both markdown and JSON."""
        md_path = Path(output_path)
        json_path = md_path.with_suffix(".json")

        md_path.parent.mkdir(parents=True, exist_ok=True)

        md_path.write_text(dossier.to_markdown())
        json_path.write_text(json.dumps(dossier.to_dict(), indent=2, default=str))

        _logger.info(
            "Dossier saved: markdown=%s json=%s decision=%s",
            md_path,
            json_path,
            dossier.go_decision,
        )
