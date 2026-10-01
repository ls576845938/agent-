"""G6 Micro Pilot Final Dossier Generator for G6.

Generates complete episode review dossier at episode end, collecting all
episode data — order reviews, risk review, exit review — into a single
dossier with a final decision.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.g6_risk_monitor import CumulativeLiveRiskMonitor, CumulativeRiskState
from quant_us.live.g6_exit_plan import LivePositionExitPlanBuilder, LivePositionExitPlan

_logger = logging.getLogger("g6_final_dossier")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Micro Pilot Final Dossier
# ---------------------------------------------------------------------------

DOSSIER_DECISIONS = frozenset({
    "STOP",
    "CONTINUE_PAPER",
    "SECOND_EPISODE_REVIEW",
    "READY_FOR_G7_REVIEW",
    "BLOCKED",
})


@dataclass
class MicroPilotFinalDossier:
    dossier_id: str
    episode_id: str
    generated_at: str = ""

    # Episode summary
    episode_summary: dict[str, Any] = field(default_factory=dict)

    # Per-order reviews (list of dicts)
    order_reviews: list[dict[str, Any]] = field(default_factory=list)

    # Risk review
    risk_review: dict[str, Any] = field(default_factory=dict)

    # Exit review
    exit_review: dict[str, Any] = field(default_factory=dict)

    # Decision
    decision: str = "BLOCKED"
    decision_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = _utc_now().isoformat()
        if not self.dossier_id:
            self.dossier_id = f"dossier_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "episode_id": self.episode_id,
            "generated_at": self.generated_at,
            "episode_summary": self.episode_summary,
            "order_reviews": self.order_reviews,
            "risk_review": self.risk_review,
            "exit_review": self.exit_review,
            "decision": self.decision,
            "decision_reasons": self.decision_reasons,
        }


# ---------------------------------------------------------------------------
# Micro Pilot Final Dossier Builder
# ---------------------------------------------------------------------------


class MicroPilotFinalDossierBuilder:
    """Collects all episode data and generates the final dossier.

    Decision logic:
    - Unresolved positions exist → BLOCKED (unresolved_positions)
    - Unresolved incidents → BLOCKED (unresolved_incidents)
    - Any order missing post-trade review → BLOCKED (missing_review)
    - Cumulative loss exceeded → STOP
    - All clean → READY_FOR_G7_REVIEW
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.dossiers_dir = self.data_root / "live_pilot" / "dossiers"
        self.dossiers_dir.mkdir(parents=True, exist_ok=True)
        self.risk_monitor = CumulativeLiveRiskMonitor(data_root=str(self.data_root))

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, episode_id: str) -> MicroPilotFinalDossier:
        """Collect all episode data and generate final dossier."""
        dossier = MicroPilotFinalDossier(
            dossier_id=f"dossier_{episode_id}_{_utc_now().strftime('%Y%m%d_%H%M%S')}",
            episode_id=episode_id,
        )

        # Collect episode summary
        dossier.episode_summary = self._build_episode_summary(episode_id)

        # Collect order reviews
        dossier.order_reviews = self._build_order_reviews(episode_id)

        # Build risk review
        dossier.risk_review = self._build_risk_review(episode_id)

        # Build exit review
        dossier.exit_review = self._build_exit_review(episode_id)

        # Determine decision
        dossier.decision, dossier.decision_reasons = self._determine_decision(dossier)

        return dossier

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_episode_summary(self, episode_id: str) -> dict[str, Any]:
        risk_state = self.risk_monitor.load(episode_id)

        summary: dict[str, Any] = {
            "episode_id": episode_id,
            "cumulative_notional": 0.0,
            "cumulative_pnl": 0.0,
            "fees": 0.0,
            "slippage": 0.0,
            "order_count": 0,
            "max_order_count": 5,
            "incidents": 0,
            "recon_results": [],
        }

        if risk_state is not None:
            summary["cumulative_notional"] = risk_state.cumulative_notional
            summary["cumulative_pnl"] = risk_state.cumulative_realized_pnl
            summary["fees"] = risk_state.cumulative_fees
            summary["slippage"] = risk_state.cumulative_slippage_bps
            summary["order_count"] = risk_state.total_order_count
            summary["incidents"] = risk_state.incident_count

        # Load order tickets for symbol info
        exit_builder = LivePositionExitPlanBuilder(data_root=str(self.data_root))
        plans = exit_builder.list_plans(episode_id=episode_id)
        summary["symbols"] = list(set(p.symbol for p in plans if p.symbol))

        return summary

    def _build_order_reviews(self, episode_id: str) -> list[dict[str, Any]]:
        """Collect per-order reviews from G5 post-trade data."""
        reviews: list[dict[str, Any]] = []

        # Look for G5 post-trade files: data/live_pilot/g5_dossier_*.json
        g5_dir = self.data_root / "live_pilot"
        for f in sorted(g5_dir.glob("g5_dossier_*.json")):
            try:
                data = json.loads(f.read_text())
                ticket_id = data.get("ticket_id", "")
                if ticket_id:
                    reviews.append({
                        "ticket_id": ticket_id,
                        "confirmation": data.get("pre_trade_evidence", {}),
                        "broker_order": data.get("order_evidence", {}),
                        "fill": data.get("execution_evidence", {}),
                        "post_trade_recon": data.get("safety_evidence", {}),
                        "execution_quality": data.get("execution_evidence", {}),
                    })
            except (json.JSONDecodeError, OSError):
                continue

        # Also check freeze state for additional evidence
        freeze_path = g5_dir / "freeze_state.json"
        if freeze_path.exists() and not reviews:
            try:
                freeze_data = json.loads(freeze_path.read_text())
                reviews.append({
                    "ticket_id": freeze_data.get("ticket_id", "unknown"),
                    "freeze_state": freeze_data,
                    "note": "No G5 dossier found — using freeze state as fallback",
                })
            except (json.JSONDecodeError, OSError):
                pass

        return reviews

    def _build_risk_review(self, episode_id: str) -> dict[str, Any]:
        risk_state = self.risk_monitor.load(episode_id)
        if risk_state is None:
            return {
                "cumulative_risk": "NO_DATA",
                "loss_limits": {},
                "exposure": {},
                "drawdown": {},
                "emergency_stop_events": [],
                "note": "No risk state found for this episode",
            }

        # Check emergency stop status
        emergency_stop_events: list[dict] = []
        try:
            from quant_us.live.emergency_stop import EmergencyStopController
            ctrl = EmergencyStopController(state_dir=str(self.data_root / "live_pilot"))
            es_status = ctrl.status()
            current_event = es_status.get("current_event")
            if current_event:
                emergency_stop_events.append(current_event)
        except Exception:
            pass

        return {
            "cumulative_risk": risk_state.to_dict(),
            "loss_limits": {
                "cumulative_notional": risk_state.cumulative_notional,
                "cumulative_realized_pnl": risk_state.cumulative_realized_pnl,
                "cumulative_unrealized_pnl": risk_state.cumulative_unrealized_pnl,
                "max_drawdown": risk_state.max_drawdown_since_episode_start,
            },
            "exposure": {
                "open_positions": risk_state.live_open_position_count,
                "symbol_concentration": risk_state.symbol_concentration,
            },
            "drawdown": {
                "max_drawdown_since_episode_start": risk_state.max_drawdown_since_episode_start,
            },
            "emergency_stop_events": emergency_stop_events,
        }

    def _build_exit_review(self, episode_id: str) -> dict[str, Any]:
        exit_builder = LivePositionExitPlanBuilder(data_root=str(self.data_root))
        plans = exit_builder.list_plans(episode_id=episode_id)

        exit_plans_data: list[dict[str, Any]] = []
        reduce_only_actions: list[dict[str, Any]] = []
        unresolved_positions: list[dict[str, Any]] = []

        for plan in plans:
            plan_dict = plan.to_dict()
            exit_plans_data.append(plan_dict)

            if plan.status == "EXECUTED":
                reduce_only_actions.append({
                    "exit_plan_id": plan.exit_plan_id,
                    "symbol": plan.symbol,
                    "suggested_qty": plan.suggested_qty,
                    "suggested_side": plan.suggested_side,
                })
            if plan.status in ("DRAFT", "READY_FOR_REVIEW", "APPROVED"):
                unresolved_positions.append({
                    "exit_plan_id": plan.exit_plan_id,
                    "symbol": plan.symbol,
                    "current_qty": plan.current_qty,
                    "status": plan.status,
                })

        return {
            "open_positions": [p for p in exit_plans_data if p["current_qty"] != 0],
            "exit_plans": exit_plans_data,
            "reduce_only_actions": reduce_only_actions,
            "unresolved_positions": unresolved_positions,
        }

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    def _determine_decision(
        self, dossier: MicroPilotFinalDossier
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []

        # Check unresolved positions
        unresolved = dossier.exit_review.get("unresolved_positions", [])
        if unresolved:
            reasons.append(
                f"Unresolved positions: {len(unresolved)} exit plans not executed"
            )
            return "BLOCKED", reasons

        # Check unresolved incidents
        risk = dossier.risk_review.get("cumulative_risk", {})
        if isinstance(risk, dict) and risk.get("incident_count", 0) > 0:
            reasons.append(
                f"Unresolved incidents: {risk.get('incident_count')} incidents recorded"
            )
            return "BLOCKED", reasons

        # Check missing order reviews
        if not dossier.order_reviews:
            reasons.append("No order reviews found — missing post-trade review")
            return "BLOCKED", reasons

        # Check for orders without post-trade review data
        for review in dossier.order_reviews:
            if "freeze_state" in review and "fill" not in review:
                reasons.append(
                    f"Order {review.get('ticket_id', 'unknown')} missing post-trade review"
                )
                return "BLOCKED", reasons

        # Check cumulative loss exceeded
        episode_pnl = dossier.episode_summary.get("cumulative_notional", 0)
        if episode_pnl < -10.0:  # max cumulative loss threshold
            reasons.append(
                f"Cumulative loss exceeded: notional={episode_pnl}"
            )
            return "STOP", reasons

        # Check recon failures
        if isinstance(risk, dict):
            recon_fail = risk.get("recon_fail_count", 0)
            broker_error = risk.get("broker_error_count", 0)
            if recon_fail > 0 or broker_error > 0:
                reasons.append(
                    f"Recon failures ({recon_fail}) or broker errors ({broker_error}) detected"
                )
                return "STOP", reasons

        # Check emergency stop
        es_events = dossier.risk_review.get("emergency_stop_events", [])
        if es_events:
            reasons.append(
                f"Emergency stop events: {len(es_events)} — episode must be reviewed"
            )
            return "STOP", reasons

        # All clean
        reasons.append("All checks passed — episode completed cleanly")
        return "READY_FOR_G7_REVIEW", reasons

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_dict(self, dossier: MicroPilotFinalDossier) -> dict[str, Any]:
        return dossier.to_dict()

    def to_markdown(self, dossier: MicroPilotFinalDossier) -> str:
        d = dossier.to_dict()
        lines = [
            "# Micro Pilot Final Dossier",
            "",
            f"**Dossier ID**: `{d['dossier_id']}`",
            f"**Episode ID**: `{d['episode_id']}`",
            f"**Generated**: {d['generated_at'][:19]}",
            "",
            "---",
            "## 1. Episode Summary",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Orders | {d['episode_summary'].get('order_count', 0)} / {d['episode_summary'].get('max_order_count', 5)} |",
            f"| Cumulative Notional | ${d['episode_summary'].get('cumulative_notional', 0):,.2f} |",
            f"| Cumulative PnL | ${d['episode_summary'].get('cumulative_pnl', 0):,.2f} |",
            f"| Fees | ${d['episode_summary'].get('fees', 0):,.2f} |",
            f"| Slippage | {d['episode_summary'].get('slippage', 0):.1f} bps |",
            f"| Incidents | {d['episode_summary'].get('incidents', 0)} |",
            f"| Symbols | {', '.join(d['episode_summary'].get('symbols', [])) or 'none'} |",
            "",
            "## 2. Order Reviews",
        ]

        if not d["order_reviews"]:
            lines.append("*No order reviews recorded.*")
        else:
            for i, review in enumerate(d["order_reviews"], 1):
                lines.append(f"### Order {i}: {review.get('ticket_id', '?')}")
                lines.append(f"```json\n{json.dumps(review, indent=2)}\n```")

        lines.extend([
            "",
            "## 3. Risk Review",
        ])

        risk = d.get("risk_review", {})
        if risk:
            for key, val in risk.items():
                lines.append(f"### {key.replace('_', ' ').title()}")
                lines.append(f"```json\n{json.dumps(val, indent=2, default=str)}\n```")
        else:
            lines.append("*No risk data.*")

        lines.extend([
            "",
            "## 4. Exit Review",
        ])

        exit_r = d.get("exit_review", {})
        unresolved = exit_r.get("unresolved_positions", [])
        if unresolved:
            lines.append("### Unresolved Positions (BLOCKING)")
            for pos in unresolved:
                lines.append(
                    f"- `{pos['symbol']}` qty={pos['current_qty']} "
                    f"status={pos['status']} plan={pos['exit_plan_id']}"
                )
        else:
            lines.append("*No unresolved positions.*")

        exit_plans = exit_r.get("exit_plans", [])
        if exit_plans:
            lines.append("### Exit Plans")
            for plan in exit_plans:
                lines.append(f"```json\n{json.dumps(plan, indent=2)}\n```")

        reduce_only = exit_r.get("reduce_only_actions", [])
        if reduce_only:
            lines.append("### Reduce-Only Actions Taken")
            for action in reduce_only:
                lines.append(
                    f"- `{action['symbol']}` {action['suggested_side']} "
                    f"{action['suggested_qty']} (plan: {action['exit_plan_id']})"
                )

        lines.extend([
            "",
            "---",
            f"## 5. Decision: **{d['decision']}**",
        ])

        for r in d["decision_reasons"]:
            lines.append(f"- {r}")

        return "\n".join(lines)

    def save(self, dossier: MicroPilotFinalDossier) -> str:
        """Save dossier as both JSON and Markdown."""
        # JSON
        json_path = self.dossiers_dir / f"episode_{dossier.episode_id}.json"
        json_path.write_text(
            json.dumps(dossier.to_dict(), indent=2, default=str)
        )

        # Markdown
        md_path = self.dossiers_dir / f"episode_{dossier.episode_id}.md"
        md_path.write_text(self.to_markdown(dossier))

        _logger.info(
            "Dossier saved: episode=%s decision=%s json=%s md=%s",
            dossier.episode_id, dossier.decision, json_path, md_path,
        )
        return str(json_path)
