"""G8 Session Report.

Generates a complete report for a Supervised Micro Live Session.
Includes order counts, fills, incidents, risk status, reconciliation status,
and a recommendation decision for next steps.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.g8_session_state import SessionRuntimeStateManager, SessionStatus

_logger = logging.getLogger("g8_session_report")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SessionReport
# ---------------------------------------------------------------------------


@dataclass
class SessionReport:
    report_id: str
    session_id: str
    promotion_id: str
    episode_id: str = ""
    strategy_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    total_orders: int = 0
    real_submits: int = 0
    fills: list[dict] = field(default_factory=list)
    incidents: list[dict] = field(default_factory=list)
    risk_status: str = ""
    reconciliation_status: str = ""
    session_pnl: float = 0.0
    session_fees: float = 0.0
    session_slippage_bps: float = 0.0
    decision: str = "TERMINATE"  # CONTINUE_SESSION_REVIEW|PAUSE|TERMINATE|READY_FOR_G9_OPS_REVIEW
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "session_id": self.session_id,
            "promotion_id": self.promotion_id,
            "episode_id": self.episode_id,
            "strategy_id": self.strategy_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_orders": self.total_orders,
            "real_submits": self.real_submits,
            "fills": self.fills,
            "incidents": self.incidents,
            "risk_status": self.risk_status,
            "reconciliation_status": self.reconciliation_status,
            "session_pnl": self.session_pnl,
            "session_fees": self.session_fees,
            "session_slippage_bps": self.session_slippage_bps,
            "decision": self.decision,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionReport":
        return cls(
            report_id=data.get("report_id", ""),
            session_id=data.get("session_id", ""),
            promotion_id=data.get("promotion_id", ""),
            episode_id=data.get("episode_id", ""),
            strategy_id=data.get("strategy_id", ""),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            total_orders=data.get("total_orders", 0),
            real_submits=data.get("real_submits", 0),
            fills=data.get("fills", []),
            incidents=data.get("incidents", []),
            risk_status=data.get("risk_status", ""),
            reconciliation_status=data.get("reconciliation_status", ""),
            session_pnl=data.get("session_pnl", 0.0),
            session_fees=data.get("session_fees", 0.0),
            session_slippage_bps=data.get("session_slippage_bps", 0.0),
            decision=data.get("decision", "TERMINATE"),
            generated_at=data.get("generated_at", ""),
        )


# ---------------------------------------------------------------------------
# SessionReportBuilder
# ---------------------------------------------------------------------------


class SessionReportBuilder:
    """Builds a comprehensive session report from session state and audit data.

    Reports are saved at:
        data/live_pilot/session/reports/{report_id}.json
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = data_root
        self.state_mgr = SessionRuntimeStateManager(data_root=data_root)
        self.report_dir = Path(data_root) / "live_pilot" / "session" / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = Path(data_root) / "live_pilot" / "session" / "session_audit.jsonl"

    def build(self, session_id: str) -> SessionReport:
        """Build a session report from persisted state and audit data."""
        from quant_us.core.types import new_id

        state = self.state_mgr.load(session_id)

        report = SessionReport(
            report_id=new_id("g8_report"),
            session_id=session_id,
            promotion_id=state.promotion_id if state else "",
        )

        if state is None:
            report.decision = "TERMINATE"
            return report

        report.episode_id = ""
        report.strategy_id = state.strategy_id
        report.started_at = state.started_at
        report.total_orders = state.submitted_order_count
        report.real_submits = state.real_submit_count
        report.incidents = self._load_incidents(session_id)

        # Risk status
        if state.emergency_stop_count > 0:
            report.risk_status = "EMERGENCY_STOP_TRIGGERED"
        elif state.incident_count > 0:
            report.risk_status = "INCIDENTS_PRESENT"
        else:
            report.risk_status = "PASS"

        # Reconciliation status
        if state.recon_fail_count > 0:
            report.reconciliation_status = "DIRTY"
        else:
            report.reconciliation_status = "CLEAN"

        # Session PnL (placeholder — real PnL requires fill data from broker)
        report.session_pnl = state.realized_pnl if hasattr(state, 'realized_pnl') else 0.0
        report.session_fees = 0.0
        report.session_slippage_bps = 0.0

        # Decision logic
        if state.status == SessionStatus.COMPLETED:
            report.decision = "READY_FOR_G9_OPS_REVIEW"
        elif state.status == SessionStatus.TERMINATED:
            report.decision = "TERMINATE"
        elif state.status == SessionStatus.FROZEN:
            report.decision = "CONTINUE_SESSION_REVIEW"
        elif state.status == SessionStatus.PAUSED:
            report.decision = "PAUSE"
        elif state.status in (SessionStatus.DRAFT, SessionStatus.ARMED):
            report.decision = "CONTINUE_SESSION_REVIEW"
        else:
            report.decision = "CONTINUE_SESSION_REVIEW"

        report.ended_at = state.updated_at

        # Load fills from audit
        report.fills = self._load_fills(session_id)

        return report

    def save(self, report: SessionReport) -> str:
        """Save a session report to disk.

        Returns the file path.
        """
        path = self.report_dir / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, default=str))
        _logger.info("Session report saved: %s", path)
        return str(path)

    def to_markdown(self, report: SessionReport) -> str:
        """Render a session report as markdown."""
        lines = [
            f"# Session Report: {report.session_id}",
            "",
            f"- **Report ID**: {report.report_id}",
            f"- **Promotion**: {report.promotion_id}",
            f"- **Strategy**: {report.strategy_id}",
            f"- **Started**: {report.started_at[:19] if report.started_at else 'N/A'}",
            f"- **Ended**: {report.ended_at[:19] if report.ended_at else 'N/A'}",
            f"- **Generated**: {report.generated_at[:19]}",
            "",
            "## Summary",
            "",
            f"- **Total Orders**: {report.total_orders}",
            f"- **Real Submits**: {report.real_submits}",
            f"- **Session PnL**: ${report.session_pnl:,.2f}",
            f"- **Session Fees**: ${report.session_fees:,.2f}",
            f"- **Session Slippage**: {report.session_slippage_bps:.1f} bps",
            "",
            "## Risk",
            "",
            f"- **Risk Status**: {report.risk_status}",
            f"- **Reconciliation**: {report.reconciliation_status}",
            "",
            "## Incidents",
            "",
        ]
        if report.incidents:
            for inc in report.incidents:
                lines.append(f"- {inc.get('description', 'unknown')} ({inc.get('timestamp', '')})")
        else:
            lines.append("No incidents recorded.")
        lines += [
            "",
            "## Fills",
            "",
        ]
        if report.fills:
            for fill in report.fills:
                lines.append(
                    f"- {fill.get('symbol', '?')} {fill.get('side', '?')} "
                    f"qty={fill.get('quantity', 0)} "
                    f"price=${fill.get('price', 0):,.2f}"
                )
        else:
            lines.append("No fills recorded.")
        lines += [
            "",
            "## Decision",
            "",
            f"**{report.decision}**",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_incidents(self, session_id: str) -> list[dict]:
        """Load incidents from session audit log."""
        incidents: list[dict] = []
        if not self.audit_path.exists():
            return incidents
        try:
            with open(self.audit_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("session_id") == session_id:
                        incidents.append(entry)
        except OSError:
            pass
        return incidents[:20]  # limit to 20

    def _load_fills(self, session_id: str) -> list[dict]:
        """Load fills from session audit log (placeholder)."""
        fills: list[dict] = []
        if not self.audit_path.exists():
            return fills
        try:
            with open(self.audit_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (entry.get("session_id") == session_id
                            and entry.get("action") == "ONE_SHOT_EXECUTED"
                            and entry.get("real_submit_occurred")):
                        fills.append({
                            "timestamp": entry.get("timestamp", ""),
                            "ticket_id": entry.get("ticket_id", ""),
                            "status": entry.get("status", ""),
                        })
        except OSError:
            pass
        return fills
