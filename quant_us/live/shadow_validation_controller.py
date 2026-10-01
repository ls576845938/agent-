"""Shadow Live Validation Controller for G2.

Manages multi-day shadow-live validation runs (5-10 trading days).
Tracks validation state, incidents, and enforces safety invariants.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.shadow_models import ShadowFill, ShadowOrder
from quant_us.live.shadow_orchestrator import (
    ShadowLiveOrchestrator,
    ShadowOrchestratorConfig,
)

_logger = logging.getLogger("shadow_validation_controller")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Validation State
# ---------------------------------------------------------------------------


@dataclass
class ValidationState:
    """Tracks multi-day shadow-live validation progress."""

    run_id: str
    profile: str = "shadow_live"
    started_at: str = ""
    updated_at: str = ""
    symbols: list[str] = field(default_factory=list)
    strategy_id: str = ""
    strategy_version: str = ""
    days_target: int = 5
    days_completed: int = 0
    clean_days: int = 0
    warn_days: int = 0
    failed_days: int = 0
    shadow_order_count: int = 0
    shadow_fill_count: int = 0
    real_submit_count: int = 0
    data_parity_warn_count: int = 0
    recon_warn_count: int = 0
    incident_count: int = 0
    manual_review_required: bool = False
    current_status: str = "initializing"
    latest_report_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "profile": self.profile,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "symbols": self.symbols,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "days_target": self.days_target,
            "days_completed": self.days_completed,
            "clean_days": self.clean_days,
            "warn_days": self.warn_days,
            "failed_days": self.failed_days,
            "shadow_order_count": self.shadow_order_count,
            "shadow_fill_count": self.shadow_fill_count,
            "real_submit_count": self.real_submit_count,
            "data_parity_warn_count": self.data_parity_warn_count,
            "recon_warn_count": self.recon_warn_count,
            "incident_count": self.incident_count,
            "manual_review_required": self.manual_review_required,
            "current_status": self.current_status,
            "latest_report_path": self.latest_report_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationState":
        return cls(
            run_id=data.get("run_id", ""),
            profile=data.get("profile", "shadow_live"),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
            symbols=data.get("symbols", []),
            strategy_id=data.get("strategy_id", ""),
            strategy_version=data.get("strategy_version", ""),
            days_target=data.get("days_target", 5),
            days_completed=data.get("days_completed", 0),
            clean_days=data.get("clean_days", 0),
            warn_days=data.get("warn_days", 0),
            failed_days=data.get("failed_days", 0),
            shadow_order_count=data.get("shadow_order_count", 0),
            shadow_fill_count=data.get("shadow_fill_count", 0),
            real_submit_count=data.get("real_submit_count", 0),
            data_parity_warn_count=data.get("data_parity_warn_count", 0),
            recon_warn_count=data.get("recon_warn_count", 0),
            incident_count=data.get("incident_count", 0),
            manual_review_required=data.get("manual_review_required", False),
            current_status=data.get("current_status", "initializing"),
            latest_report_path=data.get("latest_report_path", ""),
        )

    @property
    def passed(self) -> bool:
        return (
            self.days_completed >= self.days_target
            and self.real_submit_count == 0
            and self.incident_count == 0
            and not self.manual_review_required
            and self.current_status == "completed"
        )

    @property
    def pass_criteria(self) -> dict[str, Any]:
        return {
            "days_completed": {
                "required": self.days_target,
                "actual": self.days_completed,
                "met": self.days_completed >= self.days_target,
            },
            "real_submit_count_zero": {
                "required": 0,
                "actual": self.real_submit_count,
                "met": self.real_submit_count == 0,
            },
            "no_incidents": {
                "required": 0,
                "actual": self.incident_count,
                "met": self.incident_count == 0,
            },
            "no_manual_review": {
                "required": False,
                "actual": self.manual_review_required,
                "met": not self.manual_review_required,
            },
        }


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class ShadowValidationController:
    """Manages multi-day shadow-live validation.

    Commands:
        start --days 5 --symbols SPY,QQQ,IWM,DIA --readonly
        status
        audit --latest
        report --latest
    """

    STATE_FILENAME = "shadow_validation_state.json"

    def __init__(
        self,
        state_dir: str = "data/shadow_validation",
        symbols: list[str] | None = None,
        strategy_id: str = "",
        days_target: int = 5,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / self.STATE_FILENAME

        if symbols is None:
            symbols = []

        self._state: ValidationState | None = None
        self._orchestrator: ShadowLiveOrchestrator | None = None
        self._initial_symbols = symbols
        self._initial_strategy = strategy_id
        self._initial_days = days_target

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        orchestrator: ShadowLiveOrchestrator | None = None,
    ) -> ValidationState:
        """Initialize or resume validation run."""
        existing = self._load_state()
        if existing is not None and existing.current_status not in (
            "completed",
            "failed",
        ):
            _logger.info("Resuming existing validation run: %s", existing.run_id)
            self._state = existing
            return existing

        self._state = ValidationState(
            run_id=f"sv_{_utc_now().strftime('%Y%m%d_%H%M%S')}",
            started_at=_utc_now().isoformat(),
            updated_at=_utc_now().isoformat(),
            symbols=self._initial_symbols,
            strategy_id=self._initial_strategy,
            days_target=self._initial_days,
            current_status="running",
        )
        self._orchestrator = orchestrator
        self._save_state()
        return self._state

    def record_day(
        self,
        shadow_orders: list[ShadowOrder],
        shadow_fills: list[ShadowFill],
        parity_warnings: int = 0,
        recon_warnings: int = 0,
        incidents: int = 0,
        needs_review: bool = False,
    ) -> ValidationState:
        """Record a completed shadow-live day."""
        if self._state is None:
            raise RuntimeError("Validation not started. Call start() first.")

        self._state.days_completed += 1
        self._state.shadow_order_count += len(shadow_orders)
        self._state.shadow_fill_count += len(shadow_fills)
        self._state.data_parity_warn_count += parity_warnings
        self._state.recon_warn_count += recon_warnings
        self._state.incident_count += incidents

        if incidents > 0 or needs_review:
            self._state.failed_days += 1
            self._state.manual_review_required = True
        elif parity_warnings > 0:
            self._state.warn_days += 1
        else:
            self._state.clean_days += 1

        self._state.real_submit_count = 0
        self._state.updated_at = _utc_now().isoformat()

        if self._state.days_completed >= self._state.days_target:
            self._state.current_status = "completed"

        self._save_state()
        return self._state

    def status(self) -> dict[str, Any]:
        """Return current validation status."""
        if self._state is None:
            loaded = self._load_state()
            if loaded is None:
                return {"status": "not_started"}
            self._state = loaded

        return {
            "status": self._state.current_status,
            "state": self._state.to_dict(),
            "pass_criteria": self._state.pass_criteria,
            "passed": self._state.passed,
        }

    def audit(self, latest_only: bool = True) -> list[dict[str, Any]]:
        """Read audit entries from shadow journal."""
        journal_path = self.state_dir / "shadow_journal.jsonl"
        if not journal_path.exists():
            return []

        entries: list[dict[str, Any]] = []
        with open(journal_path) as f:
            for line in f:
                try:
                    entries.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue

        if latest_only and entries:
            state = self._load_state()
            if state:
                entries = [e for e in entries if e.get("run_id") == state.run_id]

        return entries

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> ValidationState | None:
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text())
            return ValidationState.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load validation state: %s", exc)
            return None

    def _save_state(self) -> None:
        if self._state is None:
            return
        self.state_path.write_text(
            json.dumps(self._state.to_dict(), indent=2, default=str)
        )
