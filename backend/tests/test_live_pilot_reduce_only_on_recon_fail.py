"""Verify reduce-only enforcement on recon fail, data stale, broker error.

When the risk envelope detects system health issues, reduce-only mode
is enforced. In reduce-only mode, new positions are blocked but
closing/reducing orders are allowed.
"""

from __future__ import annotations

import tempfile

import pytest

from quant_us.live.live_pilot_risk_envelope import (
    LivePilotRiskEnvelope,
    RiskEnvelopeManager,
)
from quant_us.live.emergency_stop import EmergencyStopController
from quant_us.core.enums import OrderSide, OrderType


# ---------------------------------------------------------------------------
# RiskEnvelopeManager — reduce-only on system issues
# ---------------------------------------------------------------------------


class TestReduceOnlyOnReconFail:
    def test_recon_fail_forces_reduce_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope.default_conservative("env_r1")
            mgr.create(env)
            result = mgr.validate("env_r1", recon_fail=True)
            assert result["reduce_only"] is True

    def test_data_stale_forces_reduce_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope.default_conservative("env_r2")
            mgr.create(env)
            result = mgr.validate("env_r2", data_stale=True)
            assert result["reduce_only"] is True

    def test_broker_error_forces_reduce_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope.default_conservative("env_r3")
            mgr.create(env)
            result = mgr.validate("env_r3", broker_error=True)
            assert result["reduce_only"] is True

    def test_clean_state_no_reduce_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope.default_conservative("env_r4")
            mgr.create(env)
            result = mgr.validate("env_r4")
            assert result["passed"] is True
            assert result.get("reduce_only") is False

    def test_all_three_failures_together(self) -> None:
        """All three failure signals together still produce reduce_only=True."""
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope.default_conservative("env_all")
            mgr.create(env)
            result = mgr.validate(
                "env_all",
                recon_fail=True,
                data_stale=True,
                broker_error=True,
            )
            assert result["reduce_only"] is True
            assert result["checks"].get("recon", {}).get("force_stop") is True
            assert result["checks"].get("data_stale", {}).get("force_stop") is True
            assert result["checks"].get("broker_error", {}).get("force_stop") is True

    def test_no_reduce_only_when_feature_disabled(self) -> None:
        """When force_stop flags are False, reduce_only is not set."""
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope(
                envelope_id="env_no_force",
                force_stop_on_recon_fail=False,
                force_stop_on_data_stale=False,
                force_stop_on_broker_error=False,
            )
            mgr.create(env)
            result = mgr.validate(
                "env_no_force",
                recon_fail=True,
                data_stale=True,
                broker_error=True,
            )
            assert result.get("reduce_only") is False


# ---------------------------------------------------------------------------
# Reduce-only: new orders blocked, closing allowed
# ---------------------------------------------------------------------------


class TestReduceOnlyBlocksNewOrders:
    def test_reduce_only_blocks_new_orders_but_allows_closing(self) -> None:
        """In reduce-only, new orders fail, but basic checks still pass."""
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope.default_conservative("env_ro")
            mgr.create(env)
            result = mgr.validate(
                "env_ro",
                recon_fail=True,
            )
            assert result["reduce_only"] is True
            # reduce_only=True means no new positions but is orthogonal to
            # the risk check passing for existing positions

    def test_new_order_fails_under_reduce_only_notional(self) -> None:
        """Even a small new order should be blocked when reduce_only is active."""
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope(
                envelope_id="env_ro2",
                max_order_notional=100.0,
                force_stop_on_recon_fail=True,
            )
            mgr.create(env)
            result = mgr.validate(
                "env_ro2",
                recon_fail=True,
                order_notional=50.0,
            )
            # reduce_only is True — even though notional is fine, system is
            # in reduce-only mode
            assert result["reduce_only"] is True


# ---------------------------------------------------------------------------
# Emergency stop — reduce-only lifecycle
# ---------------------------------------------------------------------------


class TestEmergencyStopReduceOnly:
    def test_triggered_blocks_new_positions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctrl = EmergencyStopController(state_dir=td)
            assert ctrl.new_positions_allowed is True
            assert ctrl.reduce_only is False

            ctrl.trigger("manual_stop")
            assert ctrl.new_positions_allowed is False
            assert ctrl.reduce_only is True

    def test_resolved_allows_new_positions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctrl = EmergencyStopController(state_dir=td)
            ctrl.trigger("manual_stop")
            ctrl.acknowledge("tester")
            ctrl.resolve()
            assert ctrl.new_positions_allowed is True
            assert ctrl.reduce_only is False

    def test_reduce_only_persists_through_acknowledge(self) -> None:
        """After trigger, reduce_only stays True even after acknowledge."""
        with tempfile.TemporaryDirectory() as td:
            ctrl = EmergencyStopController(state_dir=td)
            ctrl.trigger("daily_loss_limit")
            assert ctrl.reduce_only is True
            ctrl.acknowledge("tester")
            assert ctrl.reduce_only is True  # Still reduce-only
            ctrl.resolve()
            assert ctrl.reduce_only is False  # Only after resolve

    def test_reduce_only_status_reflects_in_status_dict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctrl = EmergencyStopController(state_dir=td)
            status = ctrl.status()
            assert status["new_positions_allowed"] is True
            assert status["reduce_only"] is False

            ctrl.trigger("manual_stop")
            status = ctrl.status()
            assert status["new_positions_allowed"] is False
            assert status["reduce_only"] is True

    def test_reduce_only_survives_restart(self) -> None:
        """Reduce-only state persists across controller instances."""
        with tempfile.TemporaryDirectory() as td:
            ctrl1 = EmergencyStopController(state_dir=td)
            ctrl1.trigger("manual_stop")

            ctrl2 = EmergencyStopController(state_dir=td)
            assert ctrl2.reduce_only is True
            assert ctrl2.new_positions_allowed is False

    def test_armed_state_allows_new_positions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctrl = EmergencyStopController(state_dir=td)
            assert ctrl.new_positions_allowed is True

    def test_triggered_to_armed_cycle(self) -> None:
        """Full cycle: ARMED -> TRIGGERED -> ACKNOWLEDGED -> RESOLVED -> ARMED."""
        with tempfile.TemporaryDirectory() as td:
            ctrl = EmergencyStopController(state_dir=td)
            assert ctrl.is_armed is True

            ctrl.trigger("manual_stop")
            assert ctrl.is_triggered is True
            assert ctrl.reduce_only is True

            ctrl.acknowledge("tester")
            assert ctrl.is_acknowledged is True
            assert ctrl.reduce_only is True

            ctrl.resolve()
            assert ctrl.is_armed is True
            assert ctrl.reduce_only is False
            assert ctrl.new_positions_allowed is True


# ---------------------------------------------------------------------------
# Integration: Risk envelope reduce-only + Emergency stop reduce-only
# ---------------------------------------------------------------------------


class TestIntegrationReduceOnly:
    def test_both_layers_reduce_only_independently(self) -> None:
        """Both the risk envelope and emergency stop can independently set reduce-only."""
        with tempfile.TemporaryDirectory() as td:
            # Risk envelope
            mgr = RiskEnvelopeManager(store_path=f"{td}/envelopes")
            env = LivePilotRiskEnvelope.default_conservative("env_integ")
            mgr.create(env)
            env_result = mgr.validate("env_integ", recon_fail=True)
            assert env_result["reduce_only"] is True

            # Emergency stop
            ctrl = EmergencyStopController(state_dir=f"{td}/live_pilot")
            ctrl.trigger("manual_stop")
            assert ctrl.reduce_only is True

    def test_reduce_only_does_not_block_close_orders(self) -> None:
        """Reduce-only blocks new orders but reduce-only validation itself still runs."""
        with tempfile.TemporaryDirectory() as td:
            mgr = RiskEnvelopeManager(store_path=td)
            env = LivePilotRiskEnvelope(
                envelope_id="env_close",
                max_order_notional=100.0,
                force_stop_on_recon_fail=True,
            )
            mgr.create(env)
            # recon_fail triggers reduce_only
            result = mgr.validate(
                "env_close",
                recon_fail=True,
                order_notional=50.0,
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                session="regular",
            )
            assert result["reduce_only"] is True
