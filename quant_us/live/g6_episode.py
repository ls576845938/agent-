"""G6 Micro-Pilot Episode Manager.

An episode groups one-shot orders under cumulative limits (order count,
notional, and P&L). The manager provides lifecycle control from DRAFT
through ACTIVE_REVIEW_ONLY, WAITING_NEXT_ONE_SHOT_REVIEW, and
FROZEN_AFTER_ORDER to TERMINATED or COMPLETED.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g6_episode")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# MicroPilotEpisode
# ---------------------------------------------------------------------------


@dataclass
class MicroPilotEpisode:
    episode_id: str
    strategy_id: str = ""
    strategy_version: str = ""
    symbols: list[str] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    status: str = "DRAFT"
    max_order_count: int = 3
    completed_order_count: int = 0
    max_cumulative_notional: float = 300.0
    used_cumulative_notional: float = 0.0
    max_cumulative_loss: float = 10.0
    current_cumulative_pnl: float = 0.0
    max_clean_order_required: int = 3
    incident_count: int = 0
    recon_fail_count: int = 0
    manual_review_required: bool = True
    latest_ticket_id: str = ""
    latest_dossier_path: str = ""
    ticket_ids: list[str] = field(default_factory=list)
    termination_reason: str = ""
    terminated_at: str = ""
    max_order_notional: float = 100.0
    max_one_open_position: int = 1
    max_orders_per_day: int = 1
    last_order_date: str = ""

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = _utc_now().isoformat()
        if not self.updated_at:
            self.updated_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbols": self.symbols,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "max_order_count": self.max_order_count,
            "completed_order_count": self.completed_order_count,
            "max_cumulative_notional": self.max_cumulative_notional,
            "used_cumulative_notional": self.used_cumulative_notional,
            "max_cumulative_loss": self.max_cumulative_loss,
            "current_cumulative_pnl": self.current_cumulative_pnl,
            "max_clean_order_required": self.max_clean_order_required,
            "incident_count": self.incident_count,
            "recon_fail_count": self.recon_fail_count,
            "manual_review_required": self.manual_review_required,
            "latest_ticket_id": self.latest_ticket_id,
            "latest_dossier_path": self.latest_dossier_path,
            "ticket_ids": self.ticket_ids,
            "termination_reason": self.termination_reason,
            "terminated_at": self.terminated_at,
            "max_order_notional": self.max_order_notional,
            "max_one_open_position": self.max_one_open_position,
            "max_orders_per_day": self.max_orders_per_day,
            "last_order_date": self.last_order_date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MicroPilotEpisode:
        return cls(
            episode_id=data.get("episode_id", ""),
            strategy_id=data.get("strategy_id", ""),
            strategy_version=data.get("strategy_version", ""),
            symbols=data.get("symbols", []),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
            status=data.get("status", "DRAFT"),
            max_order_count=data.get("max_order_count", 3),
            completed_order_count=data.get("completed_order_count", 0),
            max_cumulative_notional=data.get("max_cumulative_notional", 300.0),
            used_cumulative_notional=data.get("used_cumulative_notional", 0.0),
            max_cumulative_loss=data.get("max_cumulative_loss", 10.0),
            current_cumulative_pnl=data.get("current_cumulative_pnl", 0.0),
            max_clean_order_required=data.get("max_clean_order_required", 3),
            incident_count=data.get("incident_count", 0),
            recon_fail_count=data.get("recon_fail_count", 0),
            manual_review_required=data.get("manual_review_required", True),
            latest_ticket_id=data.get("latest_ticket_id", ""),
            latest_dossier_path=data.get("latest_dossier_path", ""),
            ticket_ids=data.get("ticket_ids", []),
            termination_reason=data.get("termination_reason", ""),
            terminated_at=data.get("terminated_at", ""),
            max_order_notional=data.get("max_order_notional", 100.0),
            max_one_open_position=data.get("max_one_open_position", 1),
            max_orders_per_day=data.get("max_orders_per_day", 1),
            last_order_date=data.get("last_order_date", ""),
        )


# ---------------------------------------------------------------------------
# MicroPilotEpisodeManager
# ---------------------------------------------------------------------------


class MicroPilotEpisodeManager:
    """Manages micro-pilot episode lifecycle and persistence."""

    def __init__(self, data_root: str = "data") -> None:
        self.episode_dir = Path(data_root) / "live_pilot" / "episodes"
        self.episode_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        strategy_id: str,
        symbols: list[str],
        episode_id: str = "",
        strategy_version: str = "1.0.0",
        max_order_count: int = 3,
        max_cumulative_notional: float = 300.0,
        max_cumulative_loss: float = 10.0,
        max_order_notional: float = 100.0,
        max_orders_per_day: int = 1,
    ) -> MicroPilotEpisode:
        """Create a new episode in DRAFT status."""
        if not episode_id:
            episode_id = f"ep_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

        episode = MicroPilotEpisode(
            episode_id=episode_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            symbols=symbols,
            status="DRAFT",
            max_order_count=max_order_count,
            max_cumulative_notional=max_cumulative_notional,
            max_cumulative_loss=max_cumulative_loss,
            max_order_notional=max_order_notional,
            max_orders_per_day=max_orders_per_day,
        )

        self.save(episode)
        self._audit("CREATE", episode)
        _logger.info(
            "Episode created: %s strategy=%s symbols=%s",
            episode_id,
            strategy_id,
            symbols,
        )
        return episode

    def load(self, episode_id: str) -> MicroPilotEpisode | None:
        """Load an episode by ID."""
        path = self._path(episode_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return MicroPilotEpisode.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            _logger.error("Failed to load episode %s: %s", episode_id, exc)
            return None

    def save(self, episode: MicroPilotEpisode) -> None:
        """Save an episode to disk."""
        episode.updated_at = _utc_now().isoformat()
        path = self._path(episode.episode_id)
        path.write_text(json.dumps(episode.to_dict(), indent=2, default=str))

    def can_add_next_order(
        self, episode_id: str, new_notional: float = 0.0
    ) -> tuple[bool, str]:
        """Check if the next order can be added to this episode.

        Returns (True, "") if allowed, or (False, reason_string) if blocked.
        Does NOT modify the episode.
        """
        episode = self.load(episode_id)
        if episode is None:
            return False, f"episode_not_found:{episode_id}"

        # Check 1: episode not TERMINATED or COMPLETED
        if episode.status in ("TERMINATED", "COMPLETED"):
            return False, f"episode_{episode.status.lower()}:{episode_id}"

        # Check 2: completed_order_count < max_order_count
        if episode.completed_order_count >= episode.max_order_count:
            return False, f"max_order_count_reached:{episode.completed_order_count}/{episode.max_order_count}"

        # Check 3: used_cumulative_notional + new_notional <= max_cumulative_notional
        if new_notional > 0:
            projected = episode.used_cumulative_notional + new_notional
            if projected > episode.max_cumulative_notional:
                return (
                    False,
                    f"cumulative_notional_exceeded:{projected:.2f}/{episode.max_cumulative_notional:.2f}",
                )

        # Check 4: no unresolved incidents
        if episode.incident_count > 0:
            return False, f"unresolved_incidents:{episode.incident_count}"

        # Check 5: previous order post-trade review complete
        if episode.latest_ticket_id:
            dossier_found = self._check_dossier_complete(episode.latest_ticket_id)
            if not dossier_found:
                return (
                    False,
                    f"previous_order_review_incomplete:{episode.latest_ticket_id}",
                )

        # Check 6: not same day as last order
        if episode.last_order_date:
            today = _utc_now().strftime("%Y-%m-%d")
            if episode.last_order_date == today:
                return (
                    False,
                    f"same_day_order_blocked:last_order={episode.last_order_date}",
                )

        # Check 7: episode in WAITING_NEXT_ONE_SHOT_REVIEW or ACTIVE_REVIEW_ONLY
        allowed_statuses = {"WAITING_NEXT_ONE_SHOT_REVIEW", "ACTIVE_REVIEW_ONLY"}
        if episode.status not in allowed_statuses:
            return False, f"episode_status_not_ready:{episode.status}"

        return True, ""

    def add_ticket(
        self, episode_id: str, ticket_id: str, notional: float
    ) -> MicroPilotEpisode:
        """Record a ticket assignment to this episode. Does NOT submit orders."""
        episode = self.load(episode_id)
        if episode is None:
            raise ValueError(f"Episode not found: {episode_id}")

        if ticket_id not in episode.ticket_ids:
            episode.ticket_ids.append(ticket_id)
        episode.latest_ticket_id = ticket_id
        episode.completed_order_count += 1
        episode.used_cumulative_notional += notional
        episode.last_order_date = _utc_now().strftime("%Y-%m-%d")

        if episode.completed_order_count >= episode.max_order_count:
            episode.status = "COMPLETED"
        else:
            episode.status = "WAITING_NEXT_ONE_SHOT_REVIEW"

        self.save(episode)
        self._audit("ADD_TICKET", episode, extra={"ticket_id": ticket_id, "notional": notional})
        _logger.info(
            "Episode %s: added ticket %s (notional=%.2f, count=%d/%d)",
            episode_id,
            ticket_id,
            notional,
            episode.completed_order_count,
            episode.max_order_count,
        )
        return episode

    def terminate(self, episode_id: str, reason: str) -> MicroPilotEpisode:
        """Terminate an episode with a reason."""
        episode = self.load(episode_id)
        if episode is None:
            raise ValueError(f"Episode not found: {episode_id}")

        episode.status = "TERMINATED"
        episode.termination_reason = reason
        episode.terminated_at = _utc_now().isoformat()
        self.save(episode)
        self._audit("TERMINATE", episode, extra={"reason": reason})
        _logger.warning(
            "Episode %s TERMINATED: %s", episode_id, reason
        )
        return episode

    def status(self, episode_id: str) -> dict[str, Any]:
        """Return status summary for an episode."""
        episode = self.load(episode_id)
        if episode is None:
            return {"episode_id": episode_id, "status": "NOT_FOUND"}

        return {
            "episode_id": episode.episode_id,
            "status": episode.status,
            "strategy_id": episode.strategy_id,
            "symbols": episode.symbols,
            "completed_order_count": episode.completed_order_count,
            "max_order_count": episode.max_order_count,
            "used_cumulative_notional": episode.used_cumulative_notional,
            "max_cumulative_notional": episode.max_cumulative_notional,
            "current_cumulative_pnl": episode.current_cumulative_pnl,
            "incident_count": episode.incident_count,
            "recon_fail_count": episode.recon_fail_count,
            "latest_ticket_id": episode.latest_ticket_id,
            "last_order_date": episode.last_order_date,
            "termination_reason": episode.termination_reason,
            "ticket_ids": episode.ticket_ids,
        }

    def list_episodes(self) -> list[dict[str, Any]]:
        """List all episodes."""
        episodes: list[dict[str, Any]] = []
        for path in sorted(self.episode_dir.glob("*.json")):
            try:
                ep = self.load(path.stem)
                if ep:
                    episodes.append(self.status(ep.episode_id))
            except Exception:
                continue
        return episodes

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path(self, episode_id: str) -> Path:
        return self.episode_dir / f"{episode_id}.json"

    def _check_dossier_complete(self, ticket_id: str) -> bool:
        """Check if post-trade review dossier exists for a ticket."""
        base = self.episode_dir.parent  # live_pilot dir
        patterns = [
            base / f"post_trade_dossier_{ticket_id}.json",
            base / f"g5_dossier_{ticket_id}.json",
            base / f"second_review_{ticket_id}.json",
        ]
        for p in patterns:
            if p.exists():
                return True
        return False

    def _audit(
        self,
        action: str,
        episode: MicroPilotEpisode,
        extra: dict[str, Any] | None = None,
    ) -> None:
        audit_path = self.episode_dir.parent / "episode_audit.jsonl"
        entry: dict[str, Any] = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "episode_id": episode.episode_id,
            "status": episode.status,
        }
        if extra:
            entry.update(extra)
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
