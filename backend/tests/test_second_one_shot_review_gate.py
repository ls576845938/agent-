"""Tests for G6 SecondOneShotReviewGate.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_us.live.g6_second_review import SecondOneShotReviewGate, SecondReviewDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOSSIER_DECISION_STOP = json.dumps({"decision": "STOP_AND_REVIEW"})


def _make_dossier(live_pilot_dir: Path, ticket_id: str, decision: str = "STOP_AND_REVIEW") -> Path:
    """Create a G5 post-trade dossier file at live_pilot dir."""
    path = live_pilot_dir / f"post_trade_dossier_{ticket_id}.json"
    path.write_text(json.dumps({"decision": decision}))
    return path


def _make_exec_quality(live_pilot_dir: Path) -> Path:
    """Create an execution quality report in the audit dir."""
    audit_dir = live_pilot_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / "exec_quality_test_123.json"
    path.write_text(json.dumps({"ticket_id": "test"}))
    return path


def _make_freeze_clean(live_pilot_dir: Path) -> Path:
    """Create a CLEAN freeze state."""
    path = live_pilot_dir / "freeze_state.json"
    path.write_text(json.dumps({"state": "FROZEN_PENDING_REVIEW", "unknown_order_state": False}))
    return path


def _make_submit_once_lock(live_pilot_dir: Path) -> Path:
    """Create a submit-once lock file."""
    path = live_pilot_dir / "submit_once_lock.json"
    path.write_text(json.dumps({"lock_id": "lock_abc123"}))
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSecondOneShotReviewGate:
    """Comprehensive tests for SecondOneShotReviewGate safety invariants."""

    def test_missing_g5_dossier_blocked(self, tmp_path: Path) -> None:
        """No dossier at all → BLOCKED with missing_g5_dossier."""
        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert result.decision in ("BLOCKED",)
        assert "missing_g5_dossier" in result.block_reasons

    def test_missing_execution_quality_blocked(self, tmp_path: Path) -> None:
        """Dossier exists but no exec quality → BLOCKED with missing_execution_quality."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert result.decision in ("BLOCKED",)
        assert "missing_execution_quality" in result.block_reasons

    def test_recon_mismatch_blocked(self, tmp_path: Path) -> None:
        """Freeze state non-clean → BLOCKED with recon_not_clean."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_submit_once_lock(live_pilot)
        freeze_path = live_pilot / "freeze_state.json"
        freeze_path.write_text(json.dumps({"state": "PENDING_REVIEW", "unknown_order_state": False}))

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert result.decision in ("BLOCKED",)
        assert "recon_not_clean" in result.block_reasons

    def test_unresolved_incident_blocked(self, tmp_path: Path) -> None:
        """Emergency stop triggered → BLOCKED with unresolved_incident."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        # Trigger emergency stop
        from quant_us.live.emergency_stop import EmergencyStopController
        ctrl = EmergencyStopController(state_dir=str(live_pilot))
        ctrl.trigger("recon_fail", triggered_by="test")

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert result.decision in ("BLOCKED",)
        assert "unresolved_incident" in result.block_reasons

    def test_second_order_detected_blocked(self, tmp_path: Path) -> None:
        """Dossier with second_order_detected=True → BLOCKED."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        path = live_pilot / "post_trade_dossier_ticket_1.json"
        path.write_text(json.dumps({
            "decision": "STOP_AND_REVIEW",
            "safety_evidence": {"second_order_detected": True},
        }))
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert result.decision in ("BLOCKED",)
        assert "second_order_detected" in result.block_reasons

    def test_manual_review_missing_blocked(self, tmp_path: Path) -> None:
        """No manual review decision → REQUIRES_MORE_REVIEW or BLOCKED."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="",
            manual_reviewer="",
        )
        assert result.decision in ("REQUIRES_MORE_REVIEW", "BLOCKED")
        assert "manual_review_missing" in result.block_reasons

    def test_manual_review_rejected_blocked(self, tmp_path: Path) -> None:
        """Manual review decision is 'reject' → BLOCKED."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="reject",
            manual_reviewer="reviewer_1",
        )
        assert result.decision in ("BLOCKED",)
        assert "manual_review_rejected" in result.block_reasons

    def test_all_conditions_met_approved(self, tmp_path: Path) -> None:
        """ALL conditions met → APPROVED_FOR_SECOND_ONE_SHOT_REVIEW."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert result.decision == "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW"
        assert "manual_review_approved" in result.passed_checks
        assert "g5_dossier_exists" in result.passed_checks
        assert "execution_quality_report_exists" in result.passed_checks

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Gate never has access to a broker — safety invariant."""
        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        assert not hasattr(gate, "submit_order")
        assert not hasattr(gate, "_broker")
        assert not hasattr(gate, "broker")
        result = gate.review(g5_ticket_id="")
        assert result.decision == "BLOCKED"
        assert "missing_g5_dossier" in result.block_reasons

    def test_g5_dossier_decision_not_stop_and_review_blocked(self, tmp_path: Path) -> None:
        """Dossier exists but decision is not STOP_AND_REVIEW → BLOCKED."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1", decision="BLOCKED")
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        expected_reasons = {"g5_dossier_decision_not_stop_and_review"}
        assert expected_reasons.issubset(set(result.block_reasons))

    def test_missing_submit_once_lock_blocked(self, tmp_path: Path) -> None:
        """No submit_once_lock.json → BLOCKED with submit_once_lock_missing."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert "submit_once_lock_missing" in result.block_reasons

    def test_unknown_broker_order_blocked(self, tmp_path: Path) -> None:
        """Freeze state with unknown_order_state=True → BLOCKED."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_submit_once_lock(live_pilot)
        freeze_path = live_pilot / "freeze_state.json"
        freeze_path.write_text(json.dumps({"state": "FROZEN_PENDING_REVIEW", "unknown_order_state": True}))

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        result = gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )
        assert "unknown_broker_order" in result.block_reasons

    def test_save_and_load_review(self, tmp_path: Path) -> None:
        """Review result can be saved and loaded back."""
        live_pilot = tmp_path / "live_pilot"
        live_pilot.mkdir(parents=True, exist_ok=True)
        _make_dossier(live_pilot, "ticket_1")
        _make_exec_quality(live_pilot)
        _make_freeze_clean(live_pilot)
        _make_submit_once_lock(live_pilot)

        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        gate.review(
            g5_ticket_id="ticket_1",
            manual_review_decision="approve",
            manual_reviewer="reviewer_1",
        )

        loaded = gate.load("ticket_1")
        assert loaded is not None
        assert loaded.decision == "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW"
        assert isinstance(loaded, SecondReviewDecision)

    def test_ticket_not_found_on_load(self, tmp_path: Path) -> None:
        """load returns None for nonexistent ticket."""
        gate = SecondOneShotReviewGate(data_root=str(tmp_path))
        assert gate.load("nonexistent") is None
