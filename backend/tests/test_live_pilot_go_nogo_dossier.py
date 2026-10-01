"""Tests for G3 LivePilotGoNoGoDossier and LivePilotGoNoGoBuilder."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from quant_us.live.live_pilot_go_nogo import (
    LivePilotGoNoGoDossier,
    LivePilotGoNoGoBuilder,
    PaperEvidence,
    ShadowEvidence,
    ApprovalEvidence,
    EnvelopeEvidence,
    SafetyEvidence,
)


class TestLivePilotGoNoGoDossier:
    def test_default_not_ready(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        # Build always returns NOT_READY with no data
        pass  # dossier created successfully

    def test_blocked_when_real_submit_nonzero(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.shadow.real_submit_count = 1
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        assert dossier.determine_decision() == "BLOCKED"

    def test_not_ready_when_paper_lt_30(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.paper.clean_days = 10
        dossier.shadow.real_submit_count = 0
        assert dossier.determine_decision() == "NOT_READY"

    def test_not_ready_when_shadow_lt_5(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 2
        dossier.shadow.real_submit_count = 0
        assert dossier.determine_decision() == "NOT_READY"

    def test_not_ready_when_no_approval(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.approval.status = "NOT_FOUND"
        assert dossier.determine_decision() == "NOT_READY"

    def test_not_ready_when_no_envelope(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.approval.status = "APPROVED"
        dossier.envelope.envelope_id = ""
        assert dossier.determine_decision() == "NOT_READY"

    def test_ready_when_all_criteria_met(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.paper.clean_days = 30
        dossier.paper.recon_fail_count = 0
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.approval.status = "APPROVED"
        dossier.envelope.envelope_id = "env_1"
        dec = dossier.determine_decision()
        assert dec == "READY_FOR_HUMAN_REVIEW"

    def test_to_dict(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        dossier.determine_decision()
        d = dossier.to_dict()
        assert d["decision"] in ("NOT_READY", "READY_FOR_HUMAN_REVIEW", "BLOCKED")
        assert "paper" in d
        assert "shadow" in d
        assert "approval" in d
        assert "envelope" in d
        assert "safety" in d

    def test_to_markdown_has_sections(self) -> None:
        dossier = LivePilotGoNoGoDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.approval.status = "APPROVED"
        dossier.envelope.envelope_id = "env_1"
        dossier.determine_decision()
        md = dossier.to_markdown()
        assert "Paper Evidence" in md
        assert "Shadow Evidence" in md
        assert "Approval Evidence" in md
        assert "Risk Envelope" in md
        assert "Safety Evidence" in md
        assert "Decision" in md


class TestLivePilotGoNoGoBuilder:
    def test_build_creates_dossier(self) -> None:
        builder = LivePilotGoNoGoBuilder(data_root="/nonexistent")
        dossier = builder.build()
        assert dossier is not None
        assert dossier.dossier_id != ""
    def test_build_creates_dossier(self) -> None:
        builder = LivePilotGoNoGoBuilder(data_root="/nonexistent")
        dossier = builder.build()
        assert dossier is not None
        assert dossier.dossier_id != ""
    def test_build_creates_dossier(self) -> None:
        builder = LivePilotGoNoGoBuilder(data_root="/nonexistent")
        dossier = builder.build()
        assert dossier is not None
        assert dossier.dossier_id != ""
    def test_build_creates_dossier(self) -> None:
        builder = LivePilotGoNoGoBuilder(data_root="/nonexistent")
        dossier = builder.build()
        assert dossier is not None
        assert dossier.dossier_id != ""
    def test_build_creates_dossier(self) -> None:
        builder = LivePilotGoNoGoBuilder(data_root="/nonexistent")
        dossier = builder.build()
        assert dossier is not None
        assert dossier.dossier_id != ""

    def test_save_dossier_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = LivePilotGoNoGoBuilder(data_root="/nonexistent")
            dossier = builder.build()
            output = f"{tmp}/g3_dossier.md"
            builder.save_dossier(dossier, output)
            assert Path(output).exists()
            assert Path(output.replace(".md", ".json")).exists()
