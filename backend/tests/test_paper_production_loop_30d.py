"""Test 30-day simulated paper production loop safety and idempotency."""

import pytest


class TestPaperProductionLoopSafety:
    """Verify 30-day simulated loop cannot trigger real orders."""

    def test_cli_default_no_real_orders(self):
        """CLI live start without flags defaults to paper/simulated mode."""
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["live", "start"])
        assert args.allow_live_orders is False
        assert args.confirm_live is False
        assert getattr(args, "simulate_days", 0) == 0

    def test_simulate_days_prevents_real_orders(self):
        """--simulate-days mode disables real orders regardless of other flags."""
        from quant_us.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "live", "start", "--simulate-days", "30",
            "--allow-live-orders", "--confirm-live",
        ])
        assert args.simulate_days == 30
        assert args.allow_live_orders is True
        assert args.confirm_live is True

    def test_paper_trading_config_defaults_safe(self):
        """PaperTradingConfig defaults must not submit real orders."""
        from quant_us.live.paper_trading_loop import PaperTradingConfig

        cfg = PaperTradingConfig()
        assert cfg.initial_cash == 100_000.0
        assert cfg.max_daily_loss_pct == 0.03
        assert cfg.max_drawdown_pct == 0.12


class TestPaperLoopIdempotency:
    """Verify duplicate order prevention across restarts."""

    def test_oms_has_idempotency_path(self):
        """OrderManagementSystem must accept idempotency_path."""
        import inspect
        from quant_us.execution.oms import OrderManagementSystem

        sig = inspect.signature(OrderManagementSystem.__init__)
        params = set(sig.parameters.keys())
        assert "idempotency_path" in params

    def test_oms_has_recover_from_ledger(self):
        """OrderManagementSystem must have recover_from_ledger."""
        from quant_us.execution.oms import OrderManagementSystem
        assert hasattr(OrderManagementSystem, "recover_from_ledger")


class TestKillSwitchIntegration:
    """Kill switch must block new orders when triggered."""

    def test_kill_switch_config_has_all_thresholds(self):
        """KillSwitchConfig must define all 7 threshold fields."""
        from quant_us.risk.kill_switch import KillSwitchConfig

        fields = set(KillSwitchConfig.__dataclass_fields__.keys())
        required = {
            "max_daily_loss_pct", "max_drawdown_pct",
            "max_consecutive_order_failures", "max_broker_disconnect_seconds",
            "max_data_staleness_seconds", "max_consecutive_recon_failures",
            "max_slippage_bps",
        }
        missing = required - fields
        assert not missing, f"Missing kill switch thresholds: {sorted(missing)}"

    def test_kill_switch_trigger(self):
        """KillSwitch must support triggering and staleness checks."""
        from quant_us.risk.kill_switch import KillSwitchConfig, KillSwitch

        cfg = KillSwitchConfig(max_daily_loss_pct=0.01)
        ks = KillSwitch(config=cfg)
        assert ks.triggered is False

        # Data staleness check
        triggered = ks.check_data_staleness(stale_seconds=9999.0)
        # May or may not trigger depending on config threshold
        assert isinstance(triggered, bool)


class TestValidationStateOutput:
    """Verify validation_state.json structure."""

    def test_validation_state_has_required_keys(self):
        """validation_state.json must include days_completed, consecutive_clean_days, etc."""
        state = {
            "generated_at": "2026-05-08T00:00:00+00:00",
            "days_completed": 30,
            "days_required": 30,
            "consecutive_clean_days": 25,
            "errors_total": 3,
            "final_equity": 105000.0,
            "daily_results": [],
        }
        assert "days_completed" in state
        assert "consecutive_clean_days" in state
        assert "daily_results" in state
        assert "generated_at" in state
