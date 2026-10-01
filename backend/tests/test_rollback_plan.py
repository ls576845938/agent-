"""Tests for Rollback Plan Generator (G3).

Tests RollbackPlanGenerator, RollbackPlan data model.
"""

from __future__ import annotations

import json
import tempfile

import pytest

from quant_us.live.emergency_stop import RollbackPlan, RollbackPlanGenerator


# ---------------------------------------------------------------------------
# RollbackPlan data model
# ---------------------------------------------------------------------------


class TestRollbackPlan:
    def test_manual_review_required_default(self) -> None:
        plan = RollbackPlan(plan_id="plan_001")
        assert plan.manual_review_required is True

    def test_generated_at_auto_set(self) -> None:
        plan = RollbackPlan(plan_id="plan_002")
        assert plan.generated_at != ""

    def test_to_dict_contains_all_fields(self) -> None:
        plan = RollbackPlan(
            plan_id="plan_003",
            stop_reason="manual_stop",
            actions=[{"step": 1, "action": "test", "status": "recommended"}],
            reduce_only_instructions=["test instruction"],
        )
        d = plan.to_dict()
        assert d["plan_id"] == "plan_003"
        assert d["stop_reason"] == "manual_stop"
        assert d["actions"] == [{"step": 1, "action": "test", "status": "recommended"}]
        assert d["reduce_only_instructions"] == ["test instruction"]
        assert d["manual_review_required"] is True
        assert "generated_at" in d
        assert "current_positions" in d
        assert "current_orders" in d

    def test_to_dict_actions_list(self) -> None:
        plan = RollbackPlan(plan_id="plan_004", stop_reason="broker_error")
        d = plan.to_dict()
        assert isinstance(d["actions"], list)

    def test_default_actions_empty(self) -> None:
        plan = RollbackPlan(plan_id="plan_empty")
        assert plan.actions == []
        assert plan.current_positions == []
        assert plan.current_orders == []
        assert plan.reduce_only_instructions == []

    def test_incident_report_default_false(self) -> None:
        plan = RollbackPlan(plan_id="plan_005")
        assert plan.incident_report_generated is False


# ---------------------------------------------------------------------------
# RollbackPlanGenerator
# ---------------------------------------------------------------------------


class TestRollbackPlanGenerator:
    def test_generate_returns_plan_with_10_actions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        assert isinstance(plan, RollbackPlan)
        assert len(plan.actions) == 10

    def test_actions_have_correct_structure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        for action in plan.actions:
            assert "step" in action
            assert "action" in action
            assert "status" in action
            assert isinstance(action["step"], int)
            assert isinstance(action["action"], str)
            assert isinstance(action["status"], str)

    def test_actions_cover_all_rollback_steps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        actions_text = " ".join(a["action"] for a in plan.actions)
        assert "Stop strategy" in actions_text
        assert "Stop order submission" in actions_text
        assert "Query broker" in actions_text
        assert "Reconcile ledger" in actions_text
        assert "Human review" in actions_text
        assert "incident report" in actions_text
        assert "Acknowledge" in actions_text
        assert "Resolve" in actions_text

    def test_actions_have_various_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        statuses = {a["status"] for a in plan.actions}
        assert "recommended" in statuses
        assert "automatic" in statuses
        assert "manual" in statuses
        assert "required" in statuses

    def test_plan_has_reduce_only_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        assert len(plan.reduce_only_instructions) > 0
        assert all(isinstance(i, str) for i in plan.reduce_only_instructions)

    def test_reduce_only_instructions_block_new_positions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        combined = " ".join(plan.reduce_only_instructions).lower()
        assert "do not open new positions" in combined
        assert "reduce_only" in combined

    def test_manual_review_required_true(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        assert plan.manual_review_required is True

    def test_plan_has_stop_reason_set(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="broker_error")
        assert plan.stop_reason == "broker_error"

    def test_plan_has_incident_report_generated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        assert plan.incident_report_generated is True

    def test_generate_with_empty_reason(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="")
        assert plan.stop_reason == ""

    def test_save_writes_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
            # Generator saves internally; check file exists
            plan_dir = gen.data_root / "live_pilot" / "rollback_plans"
            files = list(plan_dir.glob("*.json"))
            assert len(files) == 1
            data = json.loads(files[0].read_text())
            assert data["plan_id"] == plan.plan_id
            assert data["stop_reason"] == "manual_stop"

    def test_save_writes_to_correct_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
            expected_path = (
                gen.data_root / "live_pilot" / "rollback_plans" / f"{plan.plan_id}.json"
            )
            assert expected_path.exists()

    def test_to_dict_contains_all_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        d = plan.to_dict()
        expected_fields = {
            "plan_id", "generated_at", "stop_reason", "actions",
            "current_positions", "current_orders", "reduce_only_instructions",
            "manual_review_required", "incident_report_generated",
        }
        assert set(d.keys()) == expected_fields, (
            f"Missing fields: {expected_fields - set(d.keys())}"
        )

    def test_plan_has_current_positions_and_orders(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        assert isinstance(plan.current_positions, list)
        assert isinstance(plan.current_orders, list)

    def test_plan_id_format(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            plan = gen.generate(reason="manual_stop")
        assert plan.plan_id.startswith("rollback_")

    def test_multiple_generations_create_separate_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen = RollbackPlanGenerator(data_root=td)
            p1 = gen.generate(reason="manual_stop")
            import time; time.sleep(1.2)
            p2 = gen.generate(reason="broker_error")
            assert p1.plan_id != p2.plan_id
            plan_dir = gen.data_root / "live_pilot" / "rollback_plans"
            files = list(plan_dir.glob("*.json"))
            assert len(files) == 2
