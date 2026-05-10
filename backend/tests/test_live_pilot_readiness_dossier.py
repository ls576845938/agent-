"""Tests for LivePilotReadinessDossier and LivePilotDossierBuilder.

Covers GO/NO-GO decision logic, markdown/json output, and safety checks.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from quant_us.live.live_pilot_dossier import (
    LivePilotDossierBuilder,
    LivePilotReadinessDossier,
    PaperSummary,
    ShadowSummary,
    StrategyFreeze,
    LiveSafety,
)


class TestLivePilotReadinessDossier:
    def test_default_creation(self) -> None:
        dossier = LivePilotReadinessDossier()
        assert dossier.go_decision == "NOT_READY"
        assert dossier.is_go is False
        assert dossier.dossier_id.startswith("dossier_")

    def test_blocked_when_real_submit_nonzero(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.shadow.real_submit_count = 1
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        result = dossier.determine_go_decision()
        assert result == "BLOCKED"

    def test_not_ready_when_paper_less_than_30(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 10
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        result = dossier.determine_go_decision()
        assert result == "NOT_READY"

    def test_not_ready_when_shadow_less_than_5(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 2
        dossier.shadow.real_submit_count = 0
        result = dossier.determine_go_decision()
        assert result == "NOT_READY"

    def test_not_ready_when_shadow_incidents(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.shadow.incidents = 2
        result = dossier.determine_go_decision()
        assert result == "NOT_READY"

    def test_not_ready_when_paper_recon_fail(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 30
        dossier.paper.recon_fail = 1
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        result = dossier.determine_go_decision()
        assert result == "NOT_READY"

    def test_go_when_all_criteria_met(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 30
        dossier.paper.recon_fail = 0
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.shadow.incidents = 0
        result = dossier.determine_go_decision()
        assert result == "GO_FOR_SMALL_LIVE_REVIEW"
        assert dossier.is_go is True

    def test_to_dict_serializable(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        dossier.determine_go_decision()
        d = dossier.to_dict()
        assert d["go_decision"] == "GO_FOR_SMALL_LIVE_REVIEW"
        assert d["paper"]["clean_days"] == 30
        assert d["shadow"]["days_completed"] == 5
        assert d["live_safety"]["endpoint_guard_active"] is True
        assert d["review_only"] is True
        assert d["submission_ready"] is False

    def test_to_markdown_has_expected_sections(self) -> None:
        dossier = LivePilotReadinessDossier()
        md = dossier.to_markdown()
        assert "# Live Pilot Readiness Dossier" in md
        assert "## 1. Paper 30-Day Summary" in md
        assert "## 2. Shadow Live 5-Day Summary" in md
        assert "## 3. Strategy Freeze" in md
        assert "## 4. Risk Limits" in md
        assert "## 5. Live Safety" in md
        assert "## 6. Decision" in md

    def test_markdown_shows_blocked(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.shadow.real_submit_count = 1
        dossier.determine_go_decision()
        md = dossier.to_markdown()
        assert "BLOCKED" in md

    def test_markdown_shows_go_conditions(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 30
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.determine_go_decision()
        md = dossier.to_markdown()
        assert "Review-Only Conditions" in md
        assert "Human review REQUIRED" in md
        assert "not a start, run, or submit surface" in md

    def test_allow_live_orders_true_blocks_dossier(self) -> None:
        dossier = LivePilotReadinessDossier()
        dossier.paper.clean_days = 30
        dossier.paper.recon_fail = 0
        dossier.shadow.days_completed = 5
        dossier.shadow.real_submit_count = 0
        dossier.live_safety.allow_live_orders = True
        result = dossier.determine_go_decision()
        assert result == "BLOCKED"


class TestLivePilotDossierBuilder:
    def test_build_creates_dossier(self) -> None:
        builder = LivePilotDossierBuilder(data_root="/nonexistent")
        dossier = builder.build()
        assert dossier.dossier_id.startswith("dossier_")
        assert dossier.go_decision == "NOT_READY"  # No data = not ready

    def test_save_dossier_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = LivePilotDossierBuilder(data_root="/nonexistent")
            dossier = builder.build()
            output = f"{tmp}/dossier.md"
            builder.save_dossier(dossier, output)

            md_path = Path(output)
            json_path = Path(output.replace(".md", ".json"))
            assert md_path.exists()
            assert json_path.exists()

            md_content = md_path.read_text()
            assert "Live Pilot Readiness Dossier" in md_content

            json_content = json.loads(json_path.read_text())
            assert "go_decision" in json_content
