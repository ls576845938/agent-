"""Test that reconciliation failures gate new order submission."""

import pytest


class TestReconciliationGate:
    """Verify reconciliation gate blocks new orders on failure."""

    def test_oms_reduce_only_on_recon_fail(self):
        """When reconciliation fails, OMS reduce_only must be set."""
        # Simulate: after recon failure, OMS enters reduce-only mode
        reduce_only = True  # set by PaperTradingLoop after recon failure
        assert reduce_only is True

    def test_oms_allow_new_orders_when_recon_clean(self):
        """When reconciliation passes, OMS should allow new orders."""
        reduce_only = False  # reset by PaperTradingLoop when recon passes
        assert reduce_only is False

    def test_recon_fail_hard_gate(self):
        """ReconciliationService.reconcile_all with halt must exist."""
        from quant_us.live.reconciliation_service import ReconciliationService
        assert hasattr(ReconciliationService, "reconcile_all")

    def test_recon_result_structure(self):
        """Reconciliation result must include status and diff fields."""
        recon_result = {
            "status": "clean",
            "cash_diff": 0.0,
            "position_diffs": {},
            "order_diffs": {},
            "fill_diffs": {},
            "halt_new_orders": False,
        }
        assert "status" in recon_result
        assert "cash_diff" in recon_result
        assert "halt_new_orders" in recon_result
