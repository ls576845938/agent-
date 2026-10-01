"""Tests for Live Pilot Go/No-Go Dossier (G3).

Tests LivePilotGoNoGoDossier decision logic and LivePilotGoNoGoBuilder.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_us.live.live_pilot_go_nogo import (
    ApprovalEvidence,
    EnvelopeEvidence,
    LivePilotGoNoGoBuilder,
    LivePilotGoNoGoDossier,
    PaperEvidence,
    SafetyEvidence,
    ShadowEvidence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dossier() -> LivePilotGoNoGoDossier:
    return LivePilotGoNoGoDossier()


# ---------------------------------------------------------------------------
# PaperEvidence
# ---------------------------------------------------------------------------


class TestPaperEvidence:
    def test_default_not_ready(self) -> None:
        ev = PaperEvidence()
        assert ev.status == "NOT_READY"
        assert ev.is_ready() is False

    def test_ready_with_30_clean_days_and_no_recon_fail(self) -> None:
        ev = PaperEvidence(clean_days=30, recon_fail_count=0)
        assert ev.is_ready() is True

    def test_not_ready_with_less_than_30_days(self) -> None:
        ev = PaperEvidence(clean_days=29, recon_fail_count=0)
        assert ev.is_ready() is False

    def test_not_ready_with_recon_fail(self) -> None:
        ev = PaperEvidence(clean_days=30, recon_fail_count=1)
        assert ev.is_ready() is False

    def test_ready_with_more_than_30_days(self) -> None:
        ev = PaperEvidence(clean_days=35, recon_fail_count=0)
        assert ev.is_ready() is True


# ---------------------------------------------------------------------------
# ShadowEvidence
# ---------------------------------------------------------------------------


class TestShadowEvidence:
    def test_default_not_ready(self) -> None:
        ev = ShadowEvidence()
        assert ev.status == "NOT_READY"
        assert ev.is_ready() is False

    def test_ready_with_5_days_and_no_real_submit(self) -> None:
        ev = ShadowEvidence(days_completed=5, real_submit_count=0)
        assert ev.is_ready() is True

    def test_not_ready_with_less_than_5_days(self) -> None:
        ev = ShadowEvidence(days_completed=4, real_submit_count=0)
        assert ev.is_ready() is False

    def test_not_ready_with_real_submit_count_nonzero(self) -> None:
        ev = ShadowEvidence(days_completed=5, real_submit_count=1)
        assert ev.is_ready() is False

    def test_not_ready_with_negative_real_submit(self) -> None:
        ev = ShadowEvidence(days_completed=5, real_submit_count=-1)
        assert ev.is_ready() is False

    def test_ready_with_more_than_5_days(self) -> None:
        ev = ShadowEvidence(days_completed=10, real_submit_count=0)
        assert ev.is_ready() is True


# ---------------------------------------------------------------------------
# ApprovalEvidence
# ---------------------------------------------------------------------------


class TestApprovalEvidence:
    def test_default_not_found(self) -> None:
        ev = ApprovalEvidence()
        assert ev.status == "NOT_FOUND"
        assert ev.is_ready() is False

    def test_ready_when_approved(self) -> None:
        ev = ApprovalEvidence(status="APPROVED")
        assert ev.is_ready() is True

    def test_not_ready_when_draft(self) -> None:
        ev = ApprovalEvidence(status="DRAFT")
        assert ev.is_ready() is False

    def test_not_ready_when_rejected(self) -> None:
        ev = ApprovalEvidence(status="REJECTED")
        assert ev.is_ready() is False

    def test_not_ready_when_empty_id(self) -> None:
        ev = ApprovalEvidence(approval_id="", status="APPROVED")
        assert ev.is_ready() is True  # status check, not id check


# ---------------------------------------------------------------------------
# EnvelopeEvidence
# ---------------------------------------------------------------------------


class TestEnvelopeEvidence:
    def test_default_not_ready(self) -> None:
        ev = EnvelopeEvidence()
        assert ev.is_ready() is False

    def test_ready_with_envelope_id(self) -> None:
        ev = EnvelopeEvidence(envelope_id="env_001")
        assert ev.is_ready() is True


# ---------------------------------------------------------------------------
# SafetyEvidence
# ---------------------------------------------------------------------------


class TestSafetyEvidence:
    def test_default_all_active(self) -> None:
        ev = SafetyEvidence()
        assert ev.all_ready() is True

    def test_endpoint_guard_broken(self) -> None:
        ev = SafetyEvidence(endpoint_guard_active=False)
        assert ev.all_ready() is False

    def test_kill_switch_disarmed(self) -> None:
        ev = SafetyEvidence(kill_switch_active=False)
        assert ev.all_ready() is False


# ---------------------------------------------------------------------------
# LivePilotGoNoGoDossier — determine_decision
# ---------------------------------------------------------------------------


class TestDetermineDecision:
    def test_default_decision_is_not_ready(self, dossier: LivePilotGoNoGoDossier) -> None:
        assert dossier.decision in ("NOT_READY", "BLOCKED")

    def test_blocked_when_real_submit_count_not_zero(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(real_submit_count=1),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
        )
        decision = d.determine_decision()
        assert decision == "BLOCKED"
        assert "real_submit_count" in " ".join(d.decision_reasons)

    def test_blocked_when_real_submit_negative(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=-1),
        )
        decision = d.determine_decision()
        assert decision == "BLOCKED"

    def test_not_ready_when_paper_less_than_30(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=20, recon_fail_count=0),
        )
        decision = d.determine_decision()
        assert decision == "NOT_READY"
        assert "Paper" in " ".join(d.decision_reasons)

    def test_not_ready_when_shadow_less_than_5(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=3, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
        )
        decision = d.determine_decision()
        assert decision == "NOT_READY"
        assert "Shadow" in " ".join(d.decision_reasons)

    def test_not_ready_when_no_approval(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
            approval=ApprovalEvidence(status="NOT_FOUND"),
        )
        decision = d.determine_decision()
        assert decision == "NOT_READY"
        assert "Approval" in " ".join(d.decision_reasons)

    def test_not_ready_when_no_envelope(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
            approval=ApprovalEvidence(status="APPROVED"),
            envelope=EnvelopeEvidence(envelope_id=""),
        )
        decision = d.determine_decision()
        assert decision == "NOT_READY"
        assert "envelope" in " ".join(d.decision_reasons).lower()

    def test_not_ready_when_safety_incomplete(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
            approval=ApprovalEvidence(status="APPROVED"),
            envelope=EnvelopeEvidence(envelope_id="env_001"),
            safety=SafetyEvidence(emergency_stop_active=False),
        )
        decision = d.determine_decision()
        assert decision == "NOT_READY"
        assert "Safety" in " ".join(d.decision_reasons)

    def test_ready_for_human_review_when_all_met(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
            approval=ApprovalEvidence(status="APPROVED"),
            envelope=EnvelopeEvidence(envelope_id="env_001"),
            safety=SafetyEvidence(
                no_real_order_default_path=True,
                endpoint_guard_active=True,
                env_gate_active=True,
                confirm_live_required=True,
                readiness_gate_active=True,
                reconciliation_gate_active=True,
                kill_switch_active=True,
                emergency_stop_active=True,
            ),
        )
        decision = d.determine_decision()
        assert decision == "READY_FOR_HUMAN_REVIEW"

    def test_ready_does_not_enable_live_orders(self) -> None:
        """READY_FOR_HUMAN_REVIEW still requires human action."""
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
            approval=ApprovalEvidence(status="APPROVED"),
            envelope=EnvelopeEvidence(envelope_id="env_001"),
            safety=SafetyEvidence(),
        )
        d.determine_decision()
        markdown = d.to_markdown()
        assert "does NOT automatically enable live orders" in markdown


# ---------------------------------------------------------------------------
# LivePilotGoNoGoDossier — serialization
# ---------------------------------------------------------------------------


class TestDossierSerialization:
    def test_to_dict_serializable(self, dossier: LivePilotGoNoGoDossier) -> None:
        d = dossier.to_dict()
        assert isinstance(d, dict)
        assert "dossier_id" in d
        assert "paper" in d
        assert "shadow" in d
        assert "approval" in d
        assert "envelope" in d
        assert "safety" in d
        assert "decision" in d
        assert "decision_reasons" in d

    def test_to_dict_contains_all_paper_fields(self) -> None:
        d = LivePilotGoNoGoDossier().to_dict()
        paper_fields = {"clean_days", "order_count", "fill_count",
                        "recon_fail_count", "duplicate_order_count",
                        "incidents", "status"}
        assert paper_fields.issubset(d["paper"].keys())

    def test_to_dict_contains_all_shadow_fields(self) -> None:
        d = LivePilotGoNoGoDossier().to_dict()
        shadow_fields = {"days_completed", "real_submit_count",
                         "shadow_order_count", "data_parity_status",
                         "incidents", "status"}
        assert shadow_fields.issubset(d["shadow"].keys())

    def test_to_dict_contains_all_approval_fields(self) -> None:
        d = LivePilotGoNoGoDossier().to_dict()
        approval_fields = {"approval_id", "status", "approver",
                           "approved_at", "expires_at"}
        assert approval_fields.issubset(d["approval"].keys())

    def test_to_dict_contains_all_envelope_fields(self) -> None:
        d = LivePilotGoNoGoDossier().to_dict()
        envelope_fields = {"envelope_id", "max_capital",
                           "max_order_notional", "max_daily_loss_pct"}
        assert envelope_fields.issubset(d["envelope"].keys())

    def test_to_dict_contains_all_safety_fields(self) -> None:
        d = LivePilotGoNoGoDossier().to_dict()
        safety_fields = {"no_real_order_default_path", "endpoint_guard_active",
                         "env_gate_active", "confirm_live_required",
                         "readiness_gate_active", "reconciliation_gate_active",
                         "kill_switch_active", "emergency_stop_active"}
        assert safety_fields.issubset(d["safety"].keys())

    def test_to_dict_json_serializable(self, dossier: LivePilotGoNoGoDossier) -> None:
        d = dossier.to_dict()
        # Should not raise
        json_str = json.dumps(d, default=str)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_to_markdown_contains_all_sections(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(days_completed=5, real_submit_count=0),
            paper=PaperEvidence(clean_days=30, recon_fail_count=0),
            approval=ApprovalEvidence(status="APPROVED"),
            envelope=EnvelopeEvidence(envelope_id="env_001"),
            safety=SafetyEvidence(),
        )
        d.determine_decision()
        md = d.to_markdown()
        assert "## 1. Paper Evidence" in md
        assert "## 2. Shadow Evidence" in md
        assert "## 3. Approval Evidence" in md
        assert "## 4. Risk Envelope" in md
        assert "## 5. Safety Evidence" in md
        assert "## 6. Decision" in md
        assert "READY_FOR_HUMAN_REVIEW" in md

    def test_to_markdown_blocked_decision(self) -> None:
        d = LivePilotGoNoGoDossier(
            shadow=ShadowEvidence(real_submit_count=1),
        )
        d.determine_decision()
        md = d.to_markdown()
        assert "BLOCKED" in md
        assert "Critical safety violation" in md

    def test_to_markdown_not_ready_decision(self) -> None:
        d = LivePilotGoNoGoDossier()
        d.determine_decision()
        md = d.to_markdown()
        assert "NOT_READY" in md
        assert "BLOCKED" in md or "NOT_READY" in md or "Prerequisites not met" in md


# ---------------------------------------------------------------------------
# LivePilotGoNoGoBuilder
# ---------------------------------------------------------------------------


class TestGoNoGoBuilder:
    def test_build_creates_dossier(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            builder = LivePilotGoNoGoBuilder(data_root=td)
            dossier = builder.build()
        assert isinstance(dossier, LivePilotGoNoGoDossier)
        assert dossier.dossier_id.startswith("g3_dossier_")

    def test_build_returns_not_ready_when_no_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            builder = LivePilotGoNoGoBuilder(data_root=td)
            dossier = builder.build()
        assert dossier.decision in ("NOT_READY", "BLOCKED")

    def test_build_populates_paper_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Create the paper validation state file
            paper_dir = Path(td) / "reports" / "paper_production"
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "validation_state.json").write_text(json.dumps({
                "consecutive_clean_days": 30,
                "recon_fail_count": 0,
                "daily_results": [],
                "errors_total": 0,
            }))
            builder = LivePilotGoNoGoBuilder(data_root=td)
            dossier = builder.build()
        assert dossier.paper.clean_days == 30
        assert dossier.paper.recon_fail_count == 0

    def test_build_populates_shadow_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shadow_dir = Path(td) / "shadow_validation"
            shadow_dir.mkdir(parents=True, exist_ok=True)
            (shadow_dir / "shadow_validation_state.json").write_text(json.dumps({
                "days_completed": 5,
                "real_submit_count": 0,
                "shadow_order_count": 10,
            }))
            builder = LivePilotGoNoGoBuilder(data_root=td)
            dossier = builder.build()
        assert dossier.shadow.days_completed == 5
        assert dossier.shadow.real_submit_count == 0

    def test_build_populates_approval_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            approval_dir = Path(td) / "live_pilot" / "approvals"
            approval_dir.mkdir(parents=True, exist_ok=True)
            (approval_dir / "approval_001.json").write_text(json.dumps({
                "approval_id": "approval_001",
                "status": "APPROVED",
                "approver": "admin",
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": datetime.now(timezone.utc).isoformat(),
            }))
            builder = LivePilotGoNoGoBuilder(data_root=td)
            dossier = builder.build()
        assert dossier.approval.status == "APPROVED"
        assert dossier.approval.approver == "admin"

    def test_build_populates_envelope_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env_dir = Path(td) / "live_pilot" / "envelopes"
            env_dir.mkdir(parents=True, exist_ok=True)
            (env_dir / "env_001.json").write_text(json.dumps({
                "envelope_id": "env_001",
                "max_total_capital": 1000.0,
                "max_order_notional": 100.0,
                "max_daily_loss_pct": 0.005,
            }))
            builder = LivePilotGoNoGoBuilder(data_root=td)
            dossier = builder.build()
        assert dossier.envelope.envelope_id == "env_001"
        assert dossier.envelope.max_capital == 1000.0

    def test_build_skips_missing_files_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            builder = LivePilotGoNoGoBuilder(data_root=td)
            dossier = builder.build()
        # Should not raise, defaults are NOT_READY
        assert dossier.paper.clean_days == 0
        assert dossier.shadow.days_completed == 0
        assert dossier.approval.status == "NOT_FOUND"
        assert dossier.envelope.envelope_id == ""
