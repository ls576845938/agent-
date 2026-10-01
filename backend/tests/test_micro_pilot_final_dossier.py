"""Tests for G6 MicroPilotFinalDossierBuilder.

All tests use tmp_path for data isolation. No real broker calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_us.live.g6_episode import MicroPilotEpisodeManager
from quant_us.live.g6_exit_plan import LivePositionExitPlanBuilder
from quant_us.live.g6_final_dossier import (
    MicroPilotFinalDossier,
    MicroPilotFinalDossierBuilder,
)
from quant_us.live.g6_risk_monitor import CumulativeLiveRiskMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_episode(
    tmp_path: Path,
    episode_id: str = "ep_1",
    ticket_id: str = "ticket_1",
) -> None:
    """Create a complete episode with an order and dossier."""
    mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
    mgr.create(
        strategy_id="strat_a",
        symbols=["SPY"],
        episode_id=episode_id,
        max_order_count=3,
        max_cumulative_notional=300.0,
    )
    mgr.add_ticket(episode_id, ticket_id, notional=100.0)

    # Create G5 dossier
    live_pilot = tmp_path / "live_pilot"
    dossier_path = live_pilot / f"g5_dossier_{ticket_id}.json"
    dossier_path.write_text(json.dumps({
        "ticket_id": ticket_id,
        "decision": "STOP_AND_REVIEW",
        "pre_trade_evidence": {"approved": True},
        "order_evidence": {"broker_order_id": "broker_123"},
        "execution_evidence": {"execution_status": "filled", "fill_price": 501.0, "slippage_bps": 0.5},
        "safety_evidence": {"submit_once_active": True, "freeze_active": True},
    }))

    # Record risk data
    monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
    monitor.record_order(episode_id, notional=100.0, commission=0.5, symbol="SPY")
    monitor.update_pnl(episode_id, realized_pnl=5.0)


def _setup_exit_plan(
    tmp_path: Path,
    episode_id: str = "ep_1",
    ticket_id: str = "ticket_1",
    current_qty: float = 0.0,
) -> str:
    """Create and execute an exit plan, return exit_plan_id."""
    builder = LivePositionExitPlanBuilder(data_root=str(tmp_path))
    plan = builder.build(
        episode_id=episode_id,
        ticket_id=ticket_id,
        symbol="SPY",
        current_qty=current_qty,
        entry_price=500.0,
    )
    builder.save(plan)
    return plan.exit_plan_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMicroPilotFinalDossier:
    """Tests for MicroPilotFinalDossier dataclass."""

    def test_default_decision_is_blocked(self) -> None:
        dossier = MicroPilotFinalDossier(
            dossier_id="dossier_1",
            episode_id="ep_1",
        )
        assert dossier.decision == "BLOCKED"


class TestMicroPilotFinalDossierBuilder:
    """Tests for MicroPilotFinalDossierBuilder safety invariants."""

    def test_dossier_generated_with_all_sections(self, tmp_path: Path) -> None:
        """Dossier includes all required sections."""
        _setup_episode(tmp_path, episode_id="ep_all_sections")
        _setup_exit_plan(tmp_path, episode_id="ep_all_sections", current_qty=0.0)

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_all_sections")

        assert dossier.dossier_id != ""
        assert dossier.episode_id == "ep_all_sections"
        assert isinstance(dossier.episode_summary, dict)
        assert isinstance(dossier.order_reviews, list)
        assert isinstance(dossier.risk_review, dict)
        assert isinstance(dossier.exit_review, dict)
        assert dossier.decision in ("BLOCKED", "STOP", "READY_FOR_G7_REVIEW")

    def test_unresolved_positions_returns_blocked(self, tmp_path: Path) -> None:
        """Unresolved exit plans → BLOCKED."""
        _setup_episode(tmp_path, episode_id="ep_unresolved")
        # Create an exit plan with non-zero qty and DRAFT status
        _setup_exit_plan(tmp_path, episode_id="ep_unresolved", current_qty=100.0)

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_unresolved")
        assert dossier.decision == "BLOCKED"
        assert any("Unresolved positions" in r for r in dossier.decision_reasons)

    def test_unresolved_incidents_returns_blocked(self, tmp_path: Path) -> None:
        """Incidents recorded → BLOCKED."""
        _setup_episode(tmp_path, episode_id="ep_incident")
        # No exit plans needed — no positions to resolve

        # Record incident
        monitor = CumulativeLiveRiskMonitor(data_root=str(tmp_path))
        monitor.record_incident("ep_incident")

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_incident")
        assert dossier.decision == "BLOCKED"
        assert any("incidents" in r.lower() for r in dossier.decision_reasons)

    def test_all_clean_returns_ready_for_g7(self, tmp_path: Path) -> None:
        """All conditions clean → READY_FOR_G7_REVIEW."""
        _setup_episode(tmp_path, episode_id="ep_clean")
        # No exit plans needed — episode has no open positions

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_clean")

        # Episode is clean: no unresolved positions, no incidents
        assert dossier.decision == "READY_FOR_G7_REVIEW", f"Got {dossier.decision}: {dossier.decision_reasons}"
        assert any("All checks passed" in r for r in dossier.decision_reasons)

    def test_dossier_can_export_markdown(self, tmp_path: Path) -> None:
        """Dossier can be exported as markdown."""
        _setup_episode(tmp_path, episode_id="ep_md")
        _setup_exit_plan(tmp_path, episode_id="ep_md", current_qty=0.0)

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_md")
        md = builder.to_markdown(dossier)
        assert isinstance(md, str)
        assert len(md) > 100
        assert "# Micro Pilot Final Dossier" in md
        assert dossier.episode_id in md

    def test_dossier_can_export_json(self, tmp_path: Path) -> None:
        """Dossier to_dict returns serializable dict."""
        _setup_episode(tmp_path, episode_id="ep_json")
        _setup_exit_plan(tmp_path, episode_id="ep_json", current_qty=0.0)

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_json")
        d = builder.to_dict(dossier)
        assert isinstance(d, dict)
        assert d["episode_id"] == "ep_json"
        assert d["dossier_id"] != ""
        assert d["decision"] in ("BLOCKED", "STOP", "READY_FOR_G7_REVIEW")
        # Verify JSON serializable
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_never_calls_submit_order(self, tmp_path: Path) -> None:
        """Dossier builder has no submit_order capability."""
        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        assert not hasattr(builder, "submit_order")
        assert not hasattr(builder, "_broker")
        assert not hasattr(builder, "broker")

    def test_save_dossier_creates_files(self, tmp_path: Path) -> None:
        """Save creates JSON and Markdown files."""
        _setup_episode(tmp_path, episode_id="ep_save")
        # No exit plans — episode has no open positions

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_save")
        path = builder.save(dossier)

        assert Path(path).exists()
        # Check JSON contains correct data
        saved = json.loads(Path(path).read_text())
        assert saved["episode_id"] == "ep_save"
        assert saved["decision"] == "READY_FOR_G7_REVIEW"

        # Check markdown file exists
        dossiers_dir = tmp_path / "live_pilot" / "dossiers"
        md_path = dossiers_dir / f"episode_ep_save.md"
        assert md_path.exists()

    def test_no_orders_returns_blocked(self, tmp_path: Path) -> None:
        """Episode with no order reviews → BLOCKED."""
        # Create episode but don't add tickets
        mgr = MicroPilotEpisodeManager(data_root=str(tmp_path))
        mgr.create(strategy_id="strat_a", symbols=["SPY"], episode_id="ep_empty")

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_empty")
        assert dossier.decision == "BLOCKED"
        assert any("No order reviews" in r for r in dossier.decision_reasons)

    def test_risk_review_includes_emergency_stop(self, tmp_path: Path) -> None:
        """Risk review includes emergency stop events if triggered."""
        _setup_episode(tmp_path, episode_id="ep_es")
        # No exit plans needed — episode has no open positions

        # Trigger emergency stop
        from quant_us.live.emergency_stop import EmergencyStopController
        ctrl = EmergencyStopController(state_dir=str(tmp_path / "live_pilot"))
        ctrl.trigger("recon_fail", triggered_by="test")

        builder = MicroPilotFinalDossierBuilder(data_root=str(tmp_path))
        dossier = builder.build(episode_id="ep_es")
        assert len(dossier.risk_review.get("emergency_stop_events", [])) >= 1
        # Emergency stop should cause STOP decision
        assert dossier.decision in ("STOP", "BLOCKED")
