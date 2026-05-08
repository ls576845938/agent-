"""Tests for EmergencyStopController and RollbackPlanGenerator."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from quant_us.live.emergency_stop import (
    EmergencyStopController,
    EmergencyStopState,
    RollbackPlanGenerator,
    VALID_STOP_REASONS,
)


class TestEmergencyStopController:
    def test_initial_state_armed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            assert ctrl.is_armed
            assert not ctrl.is_triggered
            assert ctrl.new_positions_allowed
            assert not ctrl.reduce_only

    def test_trigger_with_valid_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            event = ctrl.trigger("manual_stop", "tester")
            assert event.state == EmergencyStopState.TRIGGERED
            assert ctrl.is_triggered
            assert ctrl.reduce_only
            assert not ctrl.new_positions_allowed

    def test_trigger_with_invalid_reason_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            with pytest.raises(ValueError):
                ctrl.trigger("bad_reason")

    def test_trigger_with_all_valid_reasons(self) -> None:
        for reason in sorted(VALID_STOP_REASONS):
            with tempfile.TemporaryDirectory() as tmp:
                ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
                event = ctrl.trigger(reason)
                assert event.reason == reason

    def test_acknowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            ctrl.trigger("manual_stop")
            event = ctrl.acknowledge("tester")
            assert event.state == EmergencyStopState.ACKNOWLEDGED
            assert ctrl.is_acknowledged
            assert ctrl.reduce_only

    def test_acknowledge_before_trigger_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            with pytest.raises(RuntimeError):
                ctrl.acknowledge("tester")

    def test_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            ctrl.trigger("manual_stop")
            ctrl.acknowledge("tester")
            event = ctrl.resolve()
            assert event.state == EmergencyStopState.RESOLVED
            assert ctrl.new_positions_allowed

    def test_status_returns_correct_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            status = ctrl.status()
            assert status["state"] == EmergencyStopState.ARMED
            assert status["reduce_only"] is False
            assert status["new_positions_allowed"] is True

    def test_persistence_across_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl1 = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            ctrl1.trigger("manual_stop")
            assert ctrl1.is_triggered

            ctrl2 = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            assert ctrl2.is_triggered
            status = ctrl2.status()
            assert status["state"] == EmergencyStopState.TRIGGERED

    def test_incident_file_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = EmergencyStopController(state_dir=f"{tmp}/live_pilot")
            ctrl.trigger("manual_stop")
            incident_path = Path(tmp) / "live_pilot" / "emergency_stop_incidents.jsonl"
            assert incident_path.exists()


class TestRollbackPlanGenerator:
    def test_generate_returns_plan_with_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generator = RollbackPlanGenerator(data_root=tmp)
            plan = generator.generate(reason="manual_stop")
            assert len(plan.actions) == 10
            assert plan.plan_id.startswith("rollback_")

    def test_plan_has_reduce_only_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generator = RollbackPlanGenerator(data_root=tmp)
            plan = generator.generate()
            assert len(plan.reduce_only_instructions) > 0

    def test_plan_manual_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generator = RollbackPlanGenerator(data_root=tmp)
            plan = generator.generate()
            assert plan.manual_review_required is True

    def test_plan_to_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generator = RollbackPlanGenerator(data_root=tmp)
            plan = generator.generate(reason="recon_fail")
            d = plan.to_dict()
            assert d["plan_id"].startswith("rollback_")
            assert d["stop_reason"] == "recon_fail"
            assert len(d["actions"]) == 10

    def test_plan_saved_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generator = RollbackPlanGenerator(data_root=tmp)
            plan = generator.generate()
            plans_dir = Path(tmp) / "live_pilot" / "rollback_plans"
            assert plans_dir.exists()
            plan_file = plans_dir / f"{plan.plan_id}.json"
            assert plan_file.exists()
