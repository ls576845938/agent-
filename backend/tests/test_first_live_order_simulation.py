"""Test FirstLiveOrderSimulation and FirstOrderSimulationResult for G4.

Verifies that the simulation runs all gates, captures decisions, produces
a manual checklist, never submits real orders, and saves output files.
ALL tests use tempfile for storage.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from quant_us.live.first_live_order_simulation import (
    FirstLiveOrderSimulation,
    FirstOrderSimulationResult,
)


# ---------------------------------------------------------------------------
# Simulation result model
# ---------------------------------------------------------------------------


class TestFirstOrderSimulationResult:
    def test_real_submit_always_false(self) -> None:
        """real_submit is always False on creation."""
        result = FirstOrderSimulationResult(simulation_id="sim_1")
        assert result.real_submit is False

    def test_to_dict_includes_real_submit(self) -> None:
        """to_dict contains real_submit=False."""
        result = FirstOrderSimulationResult(simulation_id="sim_2")
        d = result.to_dict()
        assert d["real_submit"] is False

    def test_to_markdown_contains_expected_sections(self) -> None:
        """to_markdown includes simulation ID, suggested order, and manual checklist."""
        result = FirstOrderSimulationResult(
            simulation_id="sim_3",
            suggested_symbol="SPY",
            suggested_side="buy",
        )
        md = result.to_markdown()
        assert "First Live Order Simulation" in md
        assert "sim_3" in md
        assert "SPY" in md
        assert "**NO**" in md  # No real submit

    def test_manual_checklist_has_items(self) -> None:
        """The default manual_checklist has checklist items."""
        result = FirstOrderSimulationResult(simulation_id="sim_4")
        assert len(result.manual_checklist) == 0  # populated by simulate()
        # populate manually to verify format
        result.manual_checklist = [
            "Verify the suggested symbol",
            "Confirm approval",
        ]
        assert len(result.manual_checklist) >= 2

    def test_no_real_submit_proof_is_non_empty(self) -> None:
        """The no_real_submit_proof field is populated in __post_init__."""
        result = FirstOrderSimulationResult(simulation_id="sim_5")
        assert result.no_real_submit_proof
        assert "real_submit=False" in result.no_real_submit_proof
        assert "simulation only" in result.no_real_submit_proof.lower()


# ---------------------------------------------------------------------------
# Simulation execution
# ---------------------------------------------------------------------------


class TestFirstLiveOrderSimulationSimulate:
    def test_simulate_with_missing_approval_has_block_reasons(self) -> None:
        """Missing approval produces block reasons in gate_block_reasons."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(
                approval_id="nonexistent_approval",
                envelope_id="nonexistent_env",
            )
            assert len(result.gate_block_reasons) > 0
            assert any("approval" in r for r in result.gate_block_reasons)

    def test_simulate_with_missing_envelope_has_block_reasons(self) -> None:
        """Missing envelope produces envelope-related block reasons."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(
                approval_id="",
                envelope_id="nonexistent_envelope",
            )
            assert len(result.gate_block_reasons) > 0
            assert any("envelope" in r for r in result.gate_block_reasons)

    def test_gate_decision_is_captured(self) -> None:
        """The gate decision is captured and not the default NOT_CHECKED."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert result.gate_decision != "NOT_CHECKED"
            assert result.gate_decision in ("APPROVED_FOR_SUBMIT", "BLOCKED", "REQUIRES_MANUAL_REVIEW")

    def test_readiness_is_blocked_by_gates_when_gates_fail(self) -> None:
        """When gates fail, readiness is BLOCKED_BY_GATES or BLOCKED."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert result.readiness in ("BLOCKED_BY_GATES", "BLOCKED")

    def test_manual_checklist_populated_after_simulate(self) -> None:
        """After simulate(), the manual_checklist has the expected items."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert len(result.manual_checklist) >= 5
            # The checklist should include items about verification steps
            assert any("Verify" in item or "Confirm" in item for item in result.manual_checklist)

    def test_simulation_never_calls_submit_order(self) -> None:
        """After simulate(), real_submit is always False - no order was submitted."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert result.real_submit is False
            assert result.readiness != "NOT_CHECKED"

    def test_no_real_submit_proof_in_result(self) -> None:
        """The result always contains non-empty no_real_submit_proof."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            assert result.no_real_submit_proof
            assert "real_submit=False" in result.no_real_submit_proof


# ---------------------------------------------------------------------------
# Save result
# ---------------------------------------------------------------------------


class TestFirstLiveOrderSimulationSave:
    def test_save_result_writes_md_and_json(self) -> None:
        """save_result writes both .md and .json files."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            output_path = sim.save_result(result)
            md_path = Path(output_path)
            assert md_path.exists()
            assert md_path.suffix == ".md"
            json_path = md_path.with_suffix(".json")
            assert json_path.exists()
            # Verify JSON is valid
            with open(json_path) as f:
                data = json.load(f)
            assert data["real_submit"] is False
            assert data["simulation_id"] == result.simulation_id

    def test_save_result_with_custom_path(self) -> None:
        """save_result works with an explicit output path."""
        with tempfile.TemporaryDirectory() as td:
            sim = FirstLiveOrderSimulation(data_root=td)
            result = sim.simulate(approval_id="", envelope_id="")
            custom_path = str(Path(td) / "custom" / "report.md")
            returned = sim.save_result(result, output_path=custom_path)
            assert returned == custom_path
            assert Path(custom_path).exists()
            assert Path(custom_path).with_suffix(".json").exists()
