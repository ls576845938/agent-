"""G7 Pilot Scorecard for Strategy Promotion Governance.

Scores a G6 micro pilot episode for promotion readiness.
NEVER auto-promotes. Only returns recommendation.
Default decision is BLOCKED.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g7_scorecard")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Pilot Scorecard
# ---------------------------------------------------------------------------


@dataclass
class PilotScorecard:
    scorecard_id: str
    episode_id: str
    strategy_id: str = ""
    strategy_version: str = ""
    order_count: int = 0
    clean_order_count: int = 0
    incident_count: int = 0
    recon_fail_count: int = 0
    duplicate_order_count: int = 0
    cumulative_pnl: float = 0.0
    cumulative_fees: float = 0.0
    slippage_bps_avg: float = 0.0
    max_drawdown: float = 0.0
    risk_limit_breach_count: int = 0
    emergency_stop_count: int = 0
    manual_review_count: int = 0
    unresolved_position_count: int = 0
    final_score: float = 0.0
    decision: str = "BLOCKED"
    decision_reasons: list[str] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = _utc_now().isoformat()
        if not self.scorecard_id:
            self.scorecard_id = f"sc_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorecard_id": self.scorecard_id,
            "episode_id": self.episode_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "order_count": self.order_count,
            "clean_order_count": self.clean_order_count,
            "incident_count": self.incident_count,
            "recon_fail_count": self.recon_fail_count,
            "duplicate_order_count": self.duplicate_order_count,
            "cumulative_pnl": self.cumulative_pnl,
            "cumulative_fees": self.cumulative_fees,
            "slippage_bps_avg": self.slippage_bps_avg,
            "max_drawdown": self.max_drawdown,
            "risk_limit_breach_count": self.risk_limit_breach_count,
            "emergency_stop_count": self.emergency_stop_count,
            "manual_review_count": self.manual_review_count,
            "unresolved_position_count": self.unresolved_position_count,
            "final_score": self.final_score,
            "decision": self.decision,
            "decision_reasons": self.decision_reasons,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PilotScorecard:
        return cls(
            scorecard_id=data.get("scorecard_id", ""),
            episode_id=data.get("episode_id", ""),
            strategy_id=data.get("strategy_id", ""),
            strategy_version=data.get("strategy_version", ""),
            order_count=data.get("order_count", 0),
            clean_order_count=data.get("clean_order_count", 0),
            incident_count=data.get("incident_count", 0),
            recon_fail_count=data.get("recon_fail_count", 0),
            duplicate_order_count=data.get("duplicate_order_count", 0),
            cumulative_pnl=data.get("cumulative_pnl", 0.0),
            cumulative_fees=data.get("cumulative_fees", 0.0),
            slippage_bps_avg=data.get("slippage_bps_avg", 0.0),
            max_drawdown=data.get("max_drawdown", 0.0),
            risk_limit_breach_count=data.get("risk_limit_breach_count", 0),
            emergency_stop_count=data.get("emergency_stop_count", 0),
            manual_review_count=data.get("manual_review_count", 0),
            unresolved_position_count=data.get("unresolved_position_count", 0),
            final_score=data.get("final_score", 0.0),
            decision=data.get("decision", "BLOCKED"),
            decision_reasons=data.get("decision_reasons", []),
            generated_at=data.get("generated_at", ""),
        )


# ---------------------------------------------------------------------------
# Pilot Scorecard Builder
# ---------------------------------------------------------------------------


class PilotScorecardBuilder:
    """Builds scorecard for a micro pilot episode.

    Scoring rules (HARD blocks -> BLOCKED):
    - duplicate_order_count > 0
    - unresolved_position_count > 0
    - recon_fail_count > 0
    - incident_count > 0 (unresolved)

    Scoring rules (soft blocks -> PAUSE):
    - emergency_stop_count > 0
    - risk_limit_breach_count > 0
    - cumulative_pnl < -10 (default max loss)

    If ALL clean (clean_order_count == order_count, no incidents, no breaches):
    -> PROMOTE_TO_SUPERVISED_SESSION_REVIEW

    NEVER auto-executes promotion. Only returns recommendation.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.scorecard_dir = self.data_root / "live_pilot" / "scorecards"
        self.scorecard_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, episode_id: str) -> PilotScorecard:
        """Build scorecard from G6 episode dossier and risk data.

        Reads:
        - data/live_pilot/episodes/{episode_id}.json
        - data/live_pilot/dossiers/episode_{episode_id}.json
        - data/live_pilot/risk/cumulative_{episode_id}.json
        """
        scorecard = PilotScorecard(
            scorecard_id="",
            episode_id=episode_id,
        )

        # Collect data from episode, dossier, risk stores
        episode_data = self._load_episode(episode_id)
        dossier_data = self._load_dossier(episode_id)
        risk_data = self._load_risk(episode_id)

        # Populate fields from episode
        if episode_data:
            scorecard.strategy_id = episode_data.get("strategy_id", "")
            scorecard.strategy_version = episode_data.get("strategy_version", "")
            scorecard.incident_count = episode_data.get("incident_count", 0)
            scorecard.recon_fail_count = episode_data.get("recon_fail_count", 0)

            # Detect duplicate ticket IDs
            ticket_ids = episode_data.get("ticket_ids", [])
            if len(ticket_ids) != len(set(ticket_ids)):
                scorecard.duplicate_order_count = len(ticket_ids) - len(set(ticket_ids))

            scorecard.order_count = episode_data.get("completed_order_count", 0)

        # Populate fields from dossier
        if dossier_data:
            # Unresolved positions from exit review
            exit_review = dossier_data.get("exit_review", {})
            unresolved = exit_review.get("unresolved_positions", [])
            scorecard.unresolved_position_count = len(unresolved)

            # Emergency stop events from risk review
            risk_review = dossier_data.get("risk_review", {})
            es_events = risk_review.get("emergency_stop_events", [])
            scorecard.emergency_stop_count = len(es_events)

            # Order reviews
            order_reviews = dossier_data.get("order_reviews", [])
            if order_reviews and scorecard.order_count == 0:
                scorecard.order_count = len(order_reviews)

            # Count manual reviews
            manual_reviews = 0
            for review in order_reviews:
                if "manual_review" in review or "second_review" in review:
                    manual_reviews += 1
            scorecard.manual_review_count = manual_reviews

        # Populate fields from risk
        if risk_data:
            scorecard.cumulative_pnl = risk_data.get("cumulative_realized_pnl", 0.0)
            scorecard.cumulative_fees = risk_data.get("cumulative_fees", 0.0)
            scorecard.slippage_bps_avg = risk_data.get("cumulative_slippage_bps", 0.0)
            scorecard.max_drawdown = risk_data.get("max_drawdown_since_episode_start", 0.0)

            # Use max of episode and risk counts
            risk_incidents = risk_data.get("incident_count", 0)
            if risk_incidents > scorecard.incident_count:
                scorecard.incident_count = risk_incidents

            risk_recons = risk_data.get("recon_fail_count", 0)
            if risk_recons > scorecard.recon_fail_count:
                scorecard.recon_fail_count = risk_recons

            if scorecard.order_count == 0:
                scorecard.order_count = risk_data.get("total_order_count", 0)

        # Calculate clean order count
        issues = (
            scorecard.incident_count
            + scorecard.recon_fail_count
            + scorecard.duplicate_order_count
        )
        scorecard.clean_order_count = max(0, scorecard.order_count - issues)

        # Calculate final score
        scorecard.final_score = self._calculate_final_score(scorecard)

        # Apply decision logic
        scorecard.decision, scorecard.decision_reasons = self._determine_decision(
            scorecard
        )

        _logger.info(
            "Scorecard built: episode=%s decision=%s score=%.1f",
            episode_id,
            scorecard.decision,
            scorecard.final_score,
        )
        return scorecard

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def _determine_decision(
        self, scorecard: PilotScorecard
    ) -> tuple[str, list[str]]:
        """Apply scoring rules and return (decision, reasons).

        HARD blocks (BLOCKED):
        - duplicate_order_count > 0
        - unresolved_position_count > 0
        - recon_fail_count > 0
        - incident_count > 0

        Soft blocks (PAUSE):
        - emergency_stop_count > 0
        - risk_limit_breach_count > 0
        - cumulative_pnl < -10.0

        ALL clean -> PROMOTE_TO_SUPERVISED_SESSION_REVIEW
        """
        reasons: list[str] = []

        # --- HARD blocks: BLOCKED ---

        if scorecard.duplicate_order_count > 0:
            reasons.append(
                f"Duplicate orders detected: {scorecard.duplicate_order_count}"
            )
            return "BLOCKED", reasons

        if scorecard.unresolved_position_count > 0:
            reasons.append(
                f"Unresolved positions: {scorecard.unresolved_position_count} "
                "positions not closed"
            )
            return "BLOCKED", reasons

        if scorecard.recon_fail_count > 0:
            reasons.append(
                f"Reconciliation failures: {scorecard.recon_fail_count}"
            )
            return "BLOCKED", reasons

        if scorecard.incident_count > 0:
            reasons.append(
                f"Unresolved incidents: {scorecard.incident_count}"
            )
            return "BLOCKED", reasons

        # --- Soft blocks: PAUSE ---

        if scorecard.emergency_stop_count > 0:
            reasons.append(
                f"Emergency stop events: {scorecard.emergency_stop_count}"
            )
            return "PAUSE", reasons

        if scorecard.risk_limit_breach_count > 0:
            reasons.append(
                f"Risk limit breaches: {scorecard.risk_limit_breach_count}"
            )
            return "PAUSE", reasons

        if scorecard.cumulative_pnl < -10.0:
            reasons.append(
                f"Cumulative PnL below threshold: ${scorecard.cumulative_pnl:.2f}"
            )
            return "PAUSE", reasons

        # --- ALL clean ---

        if (
            scorecard.clean_order_count == scorecard.order_count
            and scorecard.order_count > 0
            and scorecard.incident_count == 0
            and scorecard.emergency_stop_count == 0
            and scorecard.risk_limit_breach_count == 0
        ):
            reasons.append("All checks passed - episode completed cleanly")
            return "PROMOTE_TO_SUPERVISED_SESSION_REVIEW", reasons

        # Fallback
        reasons.append("Insufficient clean orders for promotion")
        return "CONTINUE_PAPER", reasons

    def _calculate_final_score(self, scorecard: PilotScorecard) -> float:
        """Calculate a heuristic score 0-100 based on episode health."""
        score = 100.0

        # Penalties
        score -= scorecard.incident_count * 20
        score -= scorecard.recon_fail_count * 15
        score -= scorecard.duplicate_order_count * 30
        score -= scorecard.emergency_stop_count * 25
        score -= scorecard.risk_limit_breach_count * 20
        score -= scorecard.unresolved_position_count * 25

        # PnL impact
        if scorecard.cumulative_pnl < 0:
            score -= abs(scorecard.cumulative_pnl) * 2
        else:
            score += min(scorecard.cumulative_pnl * 0.5, 10)

        return max(0.0, min(100.0, round(score, 1)))

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_episode(self, episode_id: str) -> dict[str, Any] | None:
        path = self.data_root / "live_pilot" / "episodes" / f"{episode_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _load_dossier(self, episode_id: str) -> dict[str, Any] | None:
        path = (
            self.data_root
            / "live_pilot"
            / "dossiers"
            / f"episode_{episode_id}.json"
        )
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _load_risk(self, episode_id: str) -> dict[str, Any] | None:
        path = (
            self.data_root
            / "live_pilot"
            / "risk"
            / f"cumulative_{episode_id}.json"
        )
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, scorecard: PilotScorecard) -> str:
        """Save scorecard as JSON and Markdown.

        JSON: data/live_pilot/scorecards/{scorecard_id}.json
        Markdown: data/live_pilot/scorecards/{scorecard_id}.md
        """
        json_path = self.scorecard_dir / f"{scorecard.scorecard_id}.json"
        json_path.write_text(
            json.dumps(scorecard.to_dict(), indent=2, default=str)
        )

        md_path = self.scorecard_dir / f"{scorecard.scorecard_id}.md"
        md_path.write_text(self.to_markdown(scorecard))

        _logger.info(
            "Scorecard saved: id=%s decision=%s",
            scorecard.scorecard_id,
            scorecard.decision,
        )
        return str(json_path)

    def load(self, scorecard_id: str) -> PilotScorecard | None:
        """Load a scorecard by ID."""
        path = self.scorecard_dir / f"{scorecard_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return PilotScorecard.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return None

    def to_markdown(self, scorecard: PilotScorecard) -> str:
        """Render scorecard as Markdown."""
        d = scorecard.to_dict()
        lines = [
            "# Pilot Scorecard",
            "",
            f"**Scorecard ID**: `{d['scorecard_id']}`",
            f"**Episode ID**: `{d['episode_id']}`",
            f"**Strategy**: `{d['strategy_id']}` v{d['strategy_version']}",
            f"**Generated**: {d['generated_at'][:19]}",
            "",
            "---",
            "## Metrics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Order Count | {d['order_count']} |",
            f"| Clean Orders | {d['clean_order_count']} |",
            f"| Incidents | {d['incident_count']} |",
            f"| Recon Failures | {d['recon_fail_count']} |",
            f"| Duplicate Orders | {d['duplicate_order_count']} |",
            f"| Cumulative PnL | ${d['cumulative_pnl']:,.2f} |",
            f"| Cumulative Fees | ${d['cumulative_fees']:,.2f} |",
            f"| Avg Slippage | {d['slippage_bps_avg']:.1f} bps |",
            f"| Max Drawdown | ${d['max_drawdown']:,.2f} |",
            f"| Risk Limit Breaches | {d['risk_limit_breach_count']} |",
            f"| Emergency Stops | {d['emergency_stop_count']} |",
            f"| Manual Reviews | {d['manual_review_count']} |",
            f"| Unresolved Positions | {d['unresolved_position_count']} |",
            "",
            "---",
            f"## Final Score: **{d['final_score']:.1f} / 100**",
            "",
            f"## Decision: **{d['decision']}**",
        ]
        for r in d["decision_reasons"]:
            lines.append(f"- {r}")
        return "\n".join(lines)
