"""G8 Session Execution Bridge.

Bridges G8 session lifecycle to G5 OneShotLivePilotExecutor.
This is the ONLY bridge -- it NEVER creates new order paths.

CRITICAL RULES:
- Reuses OneShotLivePilotExecutor for all execution
- Never creates loops that auto-submit orders
- Every call = one attempt, then freezes
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.g8_session_gate import SessionGate
from quant_us.live.g8_session_state import SessionRuntimeStateManager, SessionStatus
from quant_us.live.g8_daily_cap import DailyTradingCapManager

_logger = logging.getLogger("g8_session_bridge")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SessionExecutionBridge
# ---------------------------------------------------------------------------


class SessionExecutionBridge:
    """Bridges G8 session to G5 OneShotLivePilotExecutor.

    NEVER creates new submit paths. ONLY reuses existing one-shot executor.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.state_mgr = SessionRuntimeStateManager(data_root=data_root)
        self.gate = SessionGate(data_root=data_root)
        self.cap_mgr = DailyTradingCapManager(data_root=data_root)
        self.data_root = data_root
        self.audit_path = Path(data_root) / "live_pilot" / "session" / "session_audit.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def execute_one_shot(
        self,
        session_id: str,
        ticket_id: str,
        dry_run: bool = True,  # ALWAYS default True
        manual_confirm: bool = False,
        **one_shot_kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a single one-shot order within the session.

        1. Load session state, verify ARMED/ACTIVE_MANUAL_SUPERVISION
        2. Check SessionGate
        3. Import and use OneShotLivePilotExecutor
        4. After execution: freeze session state
        5. Record against daily cap
        6. Write session audit

        NEVER loops. NEVER auto-continues. One call = one attempt.
        """
        result: dict[str, Any] = {
            "session_id": session_id,
            "ticket_id": ticket_id,
            "status": "BLOCKED",
            "real_submit_occurred": False,
            "freeze_applied": False,
            "errors": [],
        }

        # Step 1: Load session state
        state = self.state_mgr.load(session_id)
        if state is None:
            result["errors"].append("session_not_found")
            return result

        if state.status == SessionStatus.TERMINATED:
            result["errors"].append("session_terminated")
            result["status"] = "TERMINATED"
            return result

        if state.status == SessionStatus.COMPLETED:
            result["errors"].append("session_completed")
            result["status"] = "COMPLETED"
            return result

        if state.status not in (SessionStatus.ARMED, SessionStatus.ACTIVE_MANUAL_SUPERVISION):
            result["errors"].append(f"session_invalid_status:{state.status}")
            return result

        # Step 2: Check SessionGate
        from datetime import date
        gate_decision = self.gate.check(
            session_id=session_id,
            promotion_id=state.promotion_id,
            ticket_id=ticket_id,
            proposed_notional=one_shot_kwargs.get("estimated_notional", 0.0),
            manual_confirm=manual_confirm,
            dry_run=dry_run,
        )
        result["gate_decision"] = gate_decision.to_dict()

        if gate_decision.decision != "APPROVED_FOR_SESSION_ONE_SHOT":
            result["status"] = gate_decision.decision
            result["errors"].extend(gate_decision.block_reasons)
            return result

        # Step 3: Use OneShotLivePilotExecutor
        try:
            executor_result = self._run_one_shot_executor(
                ticket_id=ticket_id,
                dry_run=dry_run,
                **one_shot_kwargs,
            )
        except Exception as exc:
            result["errors"].append(f"executor_error:{exc}")
            _logger.exception("One-shot executor failed: %s", exc)
            return result

        result["executor_result"] = executor_result
        result["real_submit_occurred"] = executor_result.get("real_submit_occurred", False)

        if executor_result.get("errors"):
            result["errors"].extend(executor_result["errors"])
            return result

        # Step 4: Freeze session state after execution
        try:
            freeze_reason = "ORDER_SUBMITTED" if result["real_submit_occurred"] else "DRY_RUN_COMPLETED"
            frozen = self.state_mgr.freeze(session_id, reason=freeze_reason)
            result["freeze_applied"] = True
            result["session_status_after"] = frozen.status
        except ValueError as exc:
            result["errors"].append(f"freeze_error:{exc}")

        # Step 5: Record against daily cap
        today = date.today().isoformat()
        executed_notional = executor_result.get("executed_notional",
                                                 one_shot_kwargs.get("estimated_notional", 0.0))
        executed_pnl = executor_result.get("realized_pnl", 0.0)
        if result["real_submit_occurred"]:
            self.cap_mgr.record_order(session_id, today, executed_notional, executed_pnl)
        else:
            # Dry-run: still record the order count
            self.cap_mgr.get_or_create(session_id, today)

        # Step 6: Write session audit
        self._audit(
            action="ONE_SHOT_EXECUTED" if result["real_submit_occurred"] else "DRY_RUN",
            session_id=session_id,
            ticket_id=ticket_id,
            result=result,
        )

        if result["real_submit_occurred"]:
            result["status"] = "ONE_SHOT_SUBMITTED_FROZEN"
            _logger.warning(
                "Session one-shot executed (REAL): session=%s ticket=%s",
                session_id, ticket_id,
            )
        else:
            result["status"] = "DRY_RUN_COMPLETED"
            _logger.info(
                "Session one-shot executed (DRY-RUN): session=%s ticket=%s",
                session_id, ticket_id,
            )

        return result

    def can_submit(self, session_id: str) -> tuple[bool, str]:
        """Check if session allows a new submission.

        FROZEN/TERMINATED/COMPLETED -> False.
        ARMED/ACTIVE_MANUAL_SUPERVISION -> True.
        """
        state = self.state_mgr.load(session_id)
        if state is None:
            return False, "session_not_found"
        if state.status in (SessionStatus.FROZEN, SessionStatus.TERMINATED, SessionStatus.COMPLETED):
            return False, f"session_status:{state.status}"
        if state.status in (SessionStatus.ARMED, SessionStatus.ACTIVE_MANUAL_SUPERVISION):
            return True, "ok"
        return False, f"session_status:{state.status}"

    # ------------------------------------------------------------------
    # Internal: Run OneShotLivePilotExecutor
    # ------------------------------------------------------------------

    def _run_one_shot_executor(
        self,
        ticket_id: str,
        dry_run: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Import and run OneShotLivePilotExecutor.

        This is the ONLY place where the one-shot executor is called from G8.
        """
        # Import is inside the method to avoid circular imports at module level
        from quant_us.live.one_shot_executor import (
            OneShotExecutorConfig,
            OneShotLivePilotExecutor,
        )

        config = OneShotExecutorConfig(
            ticket_id=ticket_id,
            approve_live_id=kwargs.get("approve_live_id", ticket_id),
            envelope_id=kwargs.get("envelope_id", ""),
            symbols=kwargs.get("symbols", []),
            strategy_id=kwargs.get("strategy_id", "etf_rotation"),
            confirm_live=kwargs.get("confirm_live", False),
            execute_one_shot=kwargs.get("execute_one_shot", False),
            i_understand_real_money=kwargs.get("i_understand_real_money", False),
            confirm_ticket=kwargs.get("confirm_ticket", ""),
            is_dry_run=dry_run,
            data_root=self.data_root,
            audit_dir=f"{self.data_root}/live_pilot/audit",
            api_key=kwargs.get("api_key", ""),
            api_secret=kwargs.get("api_secret", ""),
        )

        executor = OneShotLivePilotExecutor(config)
        return executor.execute()

    def _audit(self, action: str, session_id: str, ticket_id: str, result: dict[str, Any]) -> None:
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "session_id": session_id,
            "ticket_id": ticket_id,
            "status": result.get("status", "UNKNOWN"),
            "real_submit_occurred": result.get("real_submit_occurred", False),
            "freeze_applied": result.get("freeze_applied", False),
            "errors": result.get("errors", []),
        }
        with open(self.audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
