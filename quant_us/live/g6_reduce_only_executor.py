"""G6 Reduce-Only Exit Executor for Micro Pilot Episodes.

Manages the dry-run exit execution. The ONLY path that may reach broker
(only with fake broker in tests). NEVER submits to real broker.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.g6_exit_plan import LivePositionExitPlan, LivePositionExitPlanBuilder

_logger = logging.getLogger("g6_reduce_only_executor")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Reduce-Only Exit Result
# ---------------------------------------------------------------------------


@dataclass
class ReduceOnlyExitResult:
    exit_plan_id: str
    submitted: bool  # Always False in production
    dry_run: bool  # Always True in production
    reduce_only_verified: bool = False
    position_check_passed: bool = False
    errors: list[str] = field(default_factory=list)
    audit_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_plan_id": self.exit_plan_id,
            "submitted": self.submitted,
            "dry_run": self.dry_run,
            "reduce_only_verified": self.reduce_only_verified,
            "position_check_passed": self.position_check_passed,
            "errors": self.errors,
            "audit_id": self.audit_id,
        }


# ---------------------------------------------------------------------------
# Reduce-Only Exit Executor
# ---------------------------------------------------------------------------


class ReduceOnlyExitExecutor:
    """Execute reduce-only exit plans.

    ALWAYS defaults to dry_run=True. The only path that may interact with
    a broker is through an explicit fake_broker in test environments.

    Execution checks (in order):
    1. Exit plan exists and is APPROVED
    2. Manual approval flag is True
    3. reduce_only=True verified
    4. Suggested qty <= abs(current_qty)
    5. Side is opposite of position
    6. If dry_run: return with submitted=False (SAFE)
    7. If NOT dry_run AND env_enabled AND fake_broker: submit once (TEST ONLY)
    """

    def __init__(self, data_root: str = "data", dry_run: bool = True) -> None:
        self.data_root = data_root
        self.dry_run = dry_run  # ALWAYS True unless explicitly set in test with fake broker
        self.builder = LivePositionExitPlanBuilder(data_root=data_root)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(
        self,
        exit_plan_id: str,
        manual_approval: bool = False,
        env_enabled: bool = False,
        fake_broker: Any = None,  # only for testing
    ) -> ReduceOnlyExitResult:
        """Execute an exit plan.

        Safe by default — dry_run=True means no submission ever.
        """
        audit_id = _utc_now().strftime("%Y%m%d_%H%M%S_%f")
        result = ReduceOnlyExitResult(
            exit_plan_id=exit_plan_id,
            submitted=False,
            dry_run=self.dry_run,
            audit_id=audit_id,
        )

        # Check 1: Exit plan exists and is APPROVED
        plan = self.builder.load(exit_plan_id)
        if plan is None:
            result.errors.append(f"Exit plan not found: {exit_plan_id}")
            self._audit(result, "NOT_FOUND")
            return result

        if plan.status != "APPROVED":
            result.errors.append(
                f"Exit plan status is '{plan.status}', must be 'APPROVED'"
            )
            self._audit(result, "BLOCKED_NOT_APPROVED")
            return result

        # Check 2: Manual approval flag
        if not manual_approval:
            result.errors.append("Manual approval flag not set — execution blocked")
            self._audit(result, "BLOCKED_NO_MANUAL_APPROVAL")
            return result

        # Check 3-5: Verify reduce-only
        verified, reason = self.verify_reduce_only(plan)
        result.reduce_only_verified = verified
        if not verified:
            result.errors.append(f"Reduce-only verification failed: {reason}")
            self._audit(result, "BLOCKED_REDUCE_ONLY_FAIL")
            return result
        result.position_check_passed = True

        # Check 6: Dry-run safety
        if self.dry_run:
            self._audit(result, "DRY_RUN")
            _logger.info(
                "REDUCE-ONLY EXIT DRY RUN: plan=%s symbol=%s qty=%s side=%s",
                exit_plan_id, plan.symbol, plan.suggested_qty, plan.suggested_side,
            )
            return result

        # Check 7: Test-only broker path
        if env_enabled and fake_broker is not None:
            try:
                self._submit_via_fake_broker(plan, fake_broker)
                result.submitted = True
                plan.status = "EXECUTED"
                self.builder.save(plan)
                self._audit(result, "EXECUTED_VIA_FAKE_BROKER")
            except Exception as exc:
                result.errors.append(f"Fake broker submission failed: {exc}")
                self._audit(result, "FAKE_BROKER_ERROR")
            return result

        # Real broker path is BLOCKED
        result.errors.append(
            "Real broker exit execution NOT ALLOWED. "
            "Reduce-only exits require test-only fake_broker."
        )
        self._audit(result, "BLOCKED_REAL_BROKER")
        return result

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_reduce_only(self, plan: LivePositionExitPlan) -> tuple[bool, str]:
        """Verify the exit plan is truly reduce-only.

        Returns (True, "") if valid, (False, reason) if not.
        """
        # Check 1: reduce_only flag is True
        if not plan.reduce_only:
            return False, "reduce_only flag is False"

        # Check 2: suggested_qty <= abs(current_qty) (never increases position)
        if plan.suggested_qty > abs(plan.current_qty):
            return False, (
                f"suggested_qty {plan.suggested_qty} > abs(current_qty) "
                f"{abs(plan.current_qty)} — would increase position"
            )

        # Check 3: Side is opposite of current position
        if plan.current_qty > 0 and plan.suggested_side != "sell":
            return False, (
                f"Long position (qty={plan.current_qty}) but suggested_side is "
                f"'{plan.suggested_side}', expected 'sell'"
            )
        if plan.current_qty < 0 and plan.suggested_side != "buy":
            return False, (
                f"Short position (qty={plan.current_qty}) but suggested_side is "
                f"'{plan.suggested_side}', expected 'buy'"
            )

        # Check 4: suggested_qty > 0 (must have something to exit)
        if plan.suggested_qty <= 0:
            return False, "suggested_qty <= 0 — nothing to exit"

        return True, ""

    # ------------------------------------------------------------------
    # Fake Broker Submission (test only)
    # ------------------------------------------------------------------

    def _submit_via_fake_broker(self, plan: LivePositionExitPlan, fake_broker: Any) -> dict[str, Any]:
        """Submit a reduce-only order to a fake broker (test only).

        This is the ONLY path where an order can be submitted.
        Never calls real AlpacaBroker.
        """
        try:
            result = fake_broker.submit_reduce_only(
                symbol=plan.symbol,
                side=plan.suggested_side,
                qty=plan.suggested_qty,
                order_type=plan.suggested_order_type,
                limit_price=plan.suggested_limit_price,
            )
            _logger.info(
                "FAKE BROKER submit: plan=%s symbol=%s side=%s qty=%s",
                plan.exit_plan_id, plan.symbol, plan.suggested_side, plan.suggested_qty,
            )
            return result
        except AttributeError:
            # Maybe the fake broker uses a different method signature
            result = fake_broker.submit_order(
                symbol=plan.symbol,
                side=plan.suggested_side,
                qty=plan.suggested_qty,
            )
            return result

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _audit(self, result: ReduceOnlyExitResult, action: str) -> None:
        audit_dir = Path(self.data_root) / "live_pilot" / "exit_plans"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / "reduce_only_executor_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "exit_plan_id": result.exit_plan_id,
            "submitted": result.submitted,
            "dry_run": result.dry_run,
            "reduce_only_verified": result.reduce_only_verified,
            "position_check_passed": result.position_check_passed,
            "errors": result.errors,
            "audit_id": result.audit_id,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
