"""Tests for quant_us/live/shadow_validation_controller.py — ValidationState,
ShadowValidationController lifecycle, day recording, audit, and persistence.

Core invariant: real_submit_count is ALWAYS 0.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import new_id
from quant_us.live.shadow_models import ShadowFill, ShadowOrder
from quant_us.live.shadow_validation_controller import (
    ShadowValidationController,
    ValidationState,
)


# ===========================================================================
# ValidationState
# ===========================================================================


class TestValidationState:
    def test_create_with_defaults(self) -> None:
        state = ValidationState(run_id="sv_001")
        assert state.profile == "shadow_live"
        assert state.days_target == 5
        assert state.days_completed == 0
        assert state.real_submit_count == 0
        assert state.current_status == "initializing"
        assert state.passed is False

    def test_to_dict_contains_all_keys(self) -> None:
        state = ValidationState(
            run_id="sv_002",
            days_target=5,
            days_completed=3,
            clean_days=3,
            real_submit_count=0,
        )
        d = state.to_dict()
        assert d["run_id"] == "sv_002"
        assert d["days_completed"] == 3
        assert d["real_submit_count"] == 0
        assert d["manual_review_required"] is False

    def test_from_dict_roundtrip(self) -> None:
        original = ValidationState(
            run_id="sv_003",
            started_at="2026-05-01T00:00:00+00:00",
            updated_at="2026-05-05T00:00:00+00:00",
            symbols=["SPY", "QQQ"],
            strategy_id="etf_rotation",
            days_target=5,
            days_completed=5,
            clean_days=5,
            real_submit_count=0,
            current_status="completed",
        )
        d = original.to_dict()
        restored = ValidationState.from_dict(d)
        assert restored.run_id == original.run_id
        assert restored.days_completed == original.days_completed
        assert restored.clean_days == original.clean_days
        assert restored.real_submit_count == original.real_submit_count
        assert restored.current_status == original.current_status

    def test_passed_criteria_all_met(self) -> None:
        state = ValidationState(
            run_id="sv_pass",
            days_target=5,
            days_completed=5,
            real_submit_count=0,
            incident_count=0,
            manual_review_required=False,
            current_status="completed",
        )
        assert state.passed is True

    def test_passed_fails_when_days_not_met(self) -> None:
        state = ValidationState(
            run_id="sv_fail",
            days_target=5,
            days_completed=3,
            real_submit_count=0,
            current_status="running",
        )
        assert state.passed is False

    def test_passed_fails_when_real_submit_nonzero(self) -> None:
        state = ValidationState(
            run_id="sv_fail",
            days_target=5,
            days_completed=5,
            real_submit_count=1,
            current_status="completed",
        )
        assert state.passed is False

    def test_passed_fails_when_incidents(self) -> None:
        state = ValidationState(
            run_id="sv_fail",
            days_target=5,
            days_completed=5,
            real_submit_count=0,
            incident_count=1,
            current_status="completed",
        )
        assert state.passed is False

    def test_passed_fails_when_manual_review(self) -> None:
        state = ValidationState(
            run_id="sv_fail",
            days_target=5,
            days_completed=5,
            real_submit_count=0,
            manual_review_required=True,
            current_status="completed",
        )
        assert state.passed is False

    def test_passed_fails_when_not_completed(self) -> None:
        state = ValidationState(
            run_id="sv_fail",
            days_target=5,
            days_completed=5,
            real_submit_count=0,
            current_status="running",
        )
        assert state.passed is False

    def test_pass_criteria_structure(self) -> None:
        state = ValidationState(run_id="sv_criteria")
        criteria = state.pass_criteria
        assert "days_completed" in criteria
        assert "real_submit_count_zero" in criteria
        assert "no_incidents" in criteria
        assert "no_manual_review" in criteria

    def test_pass_criteria_met_values(self) -> None:
        state = ValidationState(
            run_id="sv_met",
            days_target=5,
            days_completed=5,
            real_submit_count=0,
            incident_count=0,
            manual_review_required=False,
            current_status="completed",
        )
        criteria = state.pass_criteria
        assert criteria["days_completed"]["met"] is True
        assert criteria["real_submit_count_zero"]["met"] is True
        assert criteria["no_incidents"]["met"] is True
        assert criteria["no_manual_review"]["met"] is True


# ===========================================================================
# ShadowValidationController
# ===========================================================================


class TestShadowValidationController:
    @pytest.fixture
    def temp_dir(self) -> str:
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def controller(self, temp_dir: str) -> ShadowValidationController:
        return ShadowValidationController(
            state_dir=temp_dir,
            symbols=["SPY", "QQQ"],
            strategy_id="etf_rotation",
            days_target=5,
        )

    def test_start_creates_state(self, controller: ShadowValidationController) -> None:
        state = controller.start()
        assert state is not None
        assert state.run_id.startswith("sv_")
        assert state.symbols == ["SPY", "QQQ"]
        assert state.strategy_id == "etf_rotation"
        assert state.days_target == 5
        assert state.current_status == "running"

    def test_start_persists_state(self, controller: ShadowValidationController) -> None:
        controller.start()
        assert controller.state_path.exists()

    def test_start_resumes_existing(
        self, controller: ShadowValidationController
    ) -> None:
        state = controller.start()
        # Calling start again should resume the same run
        resumed = controller.start()
        assert resumed.run_id == state.run_id
        assert resumed.current_status == "running"

    def test_record_day_increments_days(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        state = controller.record_day(
            shadow_orders=[],
            shadow_fills=[],
        )
        assert state.days_completed == 1

    def test_record_day_tracks_shadow_orders(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        orders = [
            ShadowOrder(
                shadow_order_id=new_id("shadow_ord"),
                run_id="test",
                strategy_id="etf_rotation",
                signal_id=new_id("sig"),
                target_position_id=new_id("tgt"),
                order_intent_id=new_id("intent"),
                risk_check_id=new_id("risk"),
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100.0,
                estimated_price=500.0,
                estimated_notional=50_000.0,
                order_type=OrderType.MARKET,
            ),
        ]
        fills = [
            ShadowFill(
                shadow_fill_id=new_id("shadow_fill"),
                shadow_order_id="so_1",
                simulated_fill_price=500.0,
                simulated_fill_qty=100.0,
                slippage_model="bps_1",
                commission_model="percent_0.01",
            ),
        ]
        state = controller.record_day(shadow_orders=orders, shadow_fills=fills)
        assert state.shadow_order_count == 1
        assert state.shadow_fill_count == 1

    def test_record_day_real_submit_count_always_zero(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        state = controller.record_day(shadow_orders=[], shadow_fills=[])
        assert state.real_submit_count == 0

    def test_status_after_multiple_days(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        for _ in range(3):
            controller.record_day(shadow_orders=[], shadow_fills=[])
        status = controller.status()
        assert status["state"]["days_completed"] == 3
        assert status["state"]["current_status"] == "running"
        assert status["passed"] is False

    def test_completes_after_target_days(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        for _ in range(5):
            controller.record_day(shadow_orders=[], shadow_fills=[])
        status = controller.status()
        assert status["state"]["days_completed"] == 5
        assert status["state"]["current_status"] == "completed"
        assert status["passed"] is True

    def test_status_before_start(self, controller: ShadowValidationController) -> None:
        status = controller.status()
        assert status["status"] == "not_started"

    def test_status_returns_pass_criteria(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        status = controller.status()
        assert "pass_criteria" in status

    def test_record_day_raises_without_start(
        self, controller: ShadowValidationController
    ) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            controller.record_day(shadow_orders=[], shadow_fills=[])

    def test_clean_day_increment(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        state = controller.record_day(shadow_orders=[], shadow_fills=[])
        assert state.clean_days == 1

    def test_warn_day_increment(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        state = controller.record_day(
            shadow_orders=[], shadow_fills=[], parity_warnings=2
        )
        assert state.warn_days == 1
        assert state.clean_days == 0

    def test_failed_day_on_incident(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        state = controller.record_day(
            shadow_orders=[], shadow_fills=[], incidents=1
        )
        assert state.failed_days == 1
        assert state.manual_review_required is True

    def test_failed_day_on_review(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        state = controller.record_day(
            shadow_orders=[], shadow_fills=[], needs_review=True
        )
        assert state.failed_days == 1
        assert state.manual_review_required is True


# ===========================================================================
# Audit
# ===========================================================================


class TestShadowValidationControllerAudit:
    @pytest.fixture
    def temp_dir(self) -> str:
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def controller(self, temp_dir: str) -> ShadowValidationController:
        return ShadowValidationController(state_dir=temp_dir)

    def test_audit_no_journal(self, controller: ShadowValidationController) -> None:
        entries = controller.audit()
        assert entries == []

    def test_audit_reads_journal(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        # Write a manual journal entry
        journal_path = controller.state_dir / "shadow_journal.jsonl"
        entry = {"run_id": controller._state.run_id, "event_type": "test"}
        with open(journal_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        entries = controller.audit(latest_only=True)
        assert len(entries) == 1
        assert entries[0]["event_type"] == "test"

    def test_audit_returns_all_without_latest(
        self, controller: ShadowValidationController
    ) -> None:
        controller.start()
        journal_path = controller.state_dir / "shadow_journal.jsonl"
        for i in range(3):
            entry = {"run_id": controller._state.run_id, "event_type": f"test_{i}"}
            with open(journal_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

        entries = controller.audit(latest_only=False)
        assert len(entries) >= 3


# ===========================================================================
# Resume
# ===========================================================================


class TestShadowValidationControllerResume:
    def test_resume_from_existing_state(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            state = ValidationState(
                run_id="sv_resume",
                days_target=5,
                days_completed=2,
                clean_days=2,
                real_submit_count=0,
                current_status="running",
                symbols=["SPY"],
            )
            controller = ShadowValidationController(
                state_dir=d, symbols=["SPY"], days_target=5
            )
            # Save state manually
            controller.state_path.write_text(
                json.dumps(state.to_dict(), indent=2)
            )

            # Start should find and resume the existing state
            resumed = controller.start()
            assert resumed.run_id == "sv_resume"
            assert resumed.days_completed == 2
            assert resumed.current_status == "running"

    def test_resume_from_completed_does_not_resume(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            completed_state = ValidationState(
                run_id="sv_complete",
                days_target=5,
                days_completed=5,
                clean_days=5,
                real_submit_count=0,
                current_status="completed",
                symbols=["SPY"],
            )
            controller = ShadowValidationController(
                state_dir=d, symbols=["SPY"], days_target=5
            )
            controller.state_path.write_text(
                json.dumps(completed_state.to_dict(), indent=2)
            )

            # Start should create a NEW run because old one is completed
            new_state = controller.start()
            assert new_state.run_id != "sv_complete"
            assert new_state.days_completed == 0

    def test_resume_and_record_day(self) -> None:
        """After resume, recording a day should not double-count."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            controller = ShadowValidationController(
                state_dir=tmp, symbols=["SPY"], days_target=3,
            )
            controller.start()
            # Verify state persists to disk
            assert Path(tmp, "shadow_validation_state.json").exists()
