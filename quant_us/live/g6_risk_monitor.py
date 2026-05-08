"""G6 Cumulative Live Risk Monitor for Micro Pilot Episodes.

Tracks cumulative risk across all orders in a micro pilot episode and
provides go/no-go decisions based on pre-configured limits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g6_risk_monitor")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Risk Status Constants
# ---------------------------------------------------------------------------

RISK_STATUSES = frozenset({
    "PASS",
    "WARN",
    "BLOCK_NEW_ORDER",
    "TERMINATE_EPISODE",
    "REDUCE_ONLY_REQUIRED",
})


# ---------------------------------------------------------------------------
# Cumulative Risk State
# ---------------------------------------------------------------------------


@dataclass
class CumulativeRiskState:
    episode_id: str
    cumulative_notional: float = 0.0
    cumulative_realized_pnl: float = 0.0
    cumulative_unrealized_pnl: float = 0.0
    cumulative_fees: float = 0.0
    cumulative_slippage_bps: float = 0.0
    max_drawdown_since_episode_start: float = 0.0
    daily_order_count: int = 0
    total_order_count: int = 0
    live_open_position_count: int = 0
    symbol_concentration: dict[str, float] = field(default_factory=dict)
    incident_count: int = 0
    recon_fail_count: int = 0
    broker_error_count: int = 0
    last_updated: str = ""
    status: str = "PASS"  # PASS|WARN|BLOCK_NEW_ORDER|TERMINATE_EPISODE|REDUCE_ONLY_REQUIRED

    def __post_init__(self) -> None:
        if not self.last_updated:
            self.last_updated = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "cumulative_notional": self.cumulative_notional,
            "cumulative_realized_pnl": self.cumulative_realized_pnl,
            "cumulative_unrealized_pnl": self.cumulative_unrealized_pnl,
            "cumulative_fees": self.cumulative_fees,
            "cumulative_slippage_bps": self.cumulative_slippage_bps,
            "max_drawdown_since_episode_start": self.max_drawdown_since_episode_start,
            "daily_order_count": self.daily_order_count,
            "total_order_count": self.total_order_count,
            "live_open_position_count": self.live_open_position_count,
            "symbol_concentration": self.symbol_concentration,
            "incident_count": self.incident_count,
            "recon_fail_count": self.recon_fail_count,
            "broker_error_count": self.broker_error_count,
            "last_updated": self.last_updated,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Cumulative Live Risk Monitor
# ---------------------------------------------------------------------------


class CumulativeLiveRiskMonitor:
    """Tracks cumulative risk across all orders in a micro pilot episode.

    Evaluates decision rules on every call and persists state so that
    risk is tracked across process restarts.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.risk_dir = Path(data_root) / "live_pilot" / "risk"
        self.risk_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        episode_id: str,
        max_cumulative_notional: float = 300.0,
        max_cumulative_loss: float = 10.0,
        max_open_positions: int = 1,
        max_orders_per_day: int = 1,
        max_total_orders: int = 5,
    ) -> CumulativeRiskState:
        """Evaluate cumulative risk and return decision.

        Loads current risk state, applies decision rules, sets status,
        persists updated state, and returns it.
        """
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)

        reasons: list[str] = []

        # Rule 1: Cumulative notional
        if state.cumulative_notional > max_cumulative_notional:
            state.status = "BLOCK_NEW_ORDER"
            reasons.append(f"cumulative_notional {state.cumulative_notional} > {max_cumulative_notional}")

        # Rule 2: Cumulative realized loss
        elif state.cumulative_realized_pnl < -max_cumulative_loss:
            state.status = "TERMINATE_EPISODE"
            reasons.append(f"cumulative_realized_pnl {state.cumulative_realized_pnl} < -{max_cumulative_loss}")

        # Rule 3: Open position count
        elif state.live_open_position_count > max_open_positions:
            state.status = "BLOCK_NEW_ORDER"
            reasons.append(f"live_open_position_count {state.live_open_position_count} > {max_open_positions}")

        # Rule 4: Daily order count
        elif state.daily_order_count > max_orders_per_day:
            state.status = "BLOCK_NEW_ORDER"
            reasons.append(f"daily_order_count {state.daily_order_count} > {max_orders_per_day}")

        # Rule 5: Total order count
        elif state.total_order_count > max_total_orders:
            state.status = "BLOCK_NEW_ORDER"
            reasons.append(f"total_order_count {state.total_order_count} > {max_total_orders}")

        # Rule 6: Recon failures
        elif state.recon_fail_count > 0:
            state.status = "BLOCK_NEW_ORDER"
            reasons.append(f"recon_fail_count {state.recon_fail_count} > 0")

        # Rule 7: Broker errors
        elif state.broker_error_count > 0:
            state.status = "BLOCK_NEW_ORDER"
            reasons.append(f"broker_error_count {state.broker_error_count} > 0")

        # Rule 8: Incidents (WARN only)
        elif state.incident_count > 0:
            state.status = "WARN"
            reasons.append(f"incident_count {state.incident_count} > 0 — manual review required")

        # Rule 9: Emergency stop check
        if state.status in ("PASS", "WARN"):
            if self._is_emergency_stop_triggered():
                state.status = "REDUCE_ONLY_REQUIRED"
                reasons.append("Emergency stop triggered — reduce-only required")

        # Rule 10: All pass
        if not reasons:
            state.status = "PASS"

        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("EVALUATE", state, reasons)
        return state

    # ------------------------------------------------------------------
    # Recording methods
    # ------------------------------------------------------------------

    def record_order(
        self,
        episode_id: str,
        notional: float,
        commission: float = 0.0,
        slippage_bps: float = 0.0,
        symbol: str = "",
    ) -> CumulativeRiskState:
        """Record a completed order for cumulative tracking."""
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)

        state.cumulative_notional += notional
        state.cumulative_fees += commission
        state.cumulative_slippage_bps = round(
            (state.cumulative_slippage_bps * state.total_order_count + slippage_bps)
            / (state.total_order_count + 1),
            2,
        )
        state.total_order_count += 1
        if symbol:
            current = state.symbol_concentration.get(symbol, 0.0)
            state.symbol_concentration[symbol] = current + notional

        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("RECORD_ORDER", state, [f"notional={notional}, symbol={symbol}"])
        return state

    def record_incident(self, episode_id: str) -> CumulativeRiskState:
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)
        state.incident_count += 1
        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("INCIDENT", state, [f"incident_count={state.incident_count}"])
        return state

    def record_recon_fail(self, episode_id: str) -> CumulativeRiskState:
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)
        state.recon_fail_count += 1
        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("RECON_FAIL", state, [f"recon_fail_count={state.recon_fail_count}"])
        return state

    def record_broker_error(self, episode_id: str) -> CumulativeRiskState:
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)
        state.broker_error_count += 1
        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("BROKER_ERROR", state, [f"broker_error_count={state.broker_error_count}"])
        return state

    def update_position_count(self, episode_id: str, count: int) -> CumulativeRiskState:
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)
        state.live_open_position_count = max(0, count)
        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("UPDATE_POSITION_COUNT", state, [f"count={count}"])
        return state

    def update_daily_order_count(self, episode_id: str) -> CumulativeRiskState:
        """Reset daily order count (call at start of each trading day)."""
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)
        state.daily_order_count += 1
        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("DAILY_ORDER_COUNT", state, [f"daily_count={state.daily_order_count}"])
        return state

    def update_pnl(
        self,
        episode_id: str,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
    ) -> CumulativeRiskState:
        state = self.load(episode_id)
        if state is None:
            state = CumulativeRiskState(episode_id=episode_id)
        state.cumulative_realized_pnl += realized_pnl
        state.cumulative_unrealized_pnl += unrealized_pnl
        total_pnl = state.cumulative_realized_pnl + state.cumulative_unrealized_pnl
        if total_pnl < -state.max_drawdown_since_episode_start:
            state.max_drawdown_since_episode_start = -total_pnl
        state.last_updated = _utc_now().isoformat()
        self._save(state)
        self._audit("UPDATE_PNL", state, [f"realized={realized_pnl}, unrealized={unrealized_pnl}"])
        return state

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, episode_id: str) -> CumulativeRiskState | None:
        path = self._path(episode_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return CumulativeRiskState(
                episode_id=data.get("episode_id", episode_id),
                cumulative_notional=data.get("cumulative_notional", 0.0),
                cumulative_realized_pnl=data.get("cumulative_realized_pnl", 0.0),
                cumulative_unrealized_pnl=data.get("cumulative_unrealized_pnl", 0.0),
                cumulative_fees=data.get("cumulative_fees", 0.0),
                cumulative_slippage_bps=data.get("cumulative_slippage_bps", 0.0),
                max_drawdown_since_episode_start=data.get("max_drawdown_since_episode_start", 0.0),
                daily_order_count=data.get("daily_order_count", 0),
                total_order_count=data.get("total_order_count", 0),
                live_open_position_count=data.get("live_open_position_count", 0),
                symbol_concentration=data.get("symbol_concentration", {}),
                incident_count=data.get("incident_count", 0),
                recon_fail_count=data.get("recon_fail_count", 0),
                broker_error_count=data.get("broker_error_count", 0),
                last_updated=data.get("last_updated", ""),
                status=data.get("status", "PASS"),
            )
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load risk state for %s: %s", episode_id, exc)
            return None

    def _save(self, state: CumulativeRiskState) -> None:
        path = self._path(state.episode_id)
        path.write_text(json.dumps(state.to_dict(), indent=2, default=str))

    def _path(self, episode_id: str) -> Path:
        return self.risk_dir / f"cumulative_{episode_id}.json"

    def _audit(self, action: str, state: CumulativeRiskState, reasons: list[str]) -> None:
        audit_path = self.risk_dir / "risk_monitor_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "episode_id": state.episode_id,
            "status": state.status,
            "reasons": reasons,
            "total_order_count": state.total_order_count,
            "cumulative_notional": state.cumulative_notional,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def _is_emergency_stop_triggered(self) -> bool:
        try:
            from quant_us.live.emergency_stop import EmergencyStopController
            # Use the same live_pilot state dir that matches data_root
            state_dir = str(self.risk_dir.parent)
            ctrl = EmergencyStopController(state_dir=state_dir)
            return ctrl.is_triggered
        except Exception:
            return False
