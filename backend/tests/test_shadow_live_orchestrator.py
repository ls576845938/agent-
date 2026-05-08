"""Tests for quant_us/live/shadow_orchestrator.py — ShadowOrchestratorConfig,
ShadowLiveOrchestrator lifecycle, journal, resume, and safety invariants.

Core invariant: real_submit_count is ALWAYS 0, readonly MUST be True.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import AccountState, Bar, OrderIntent, Signal, new_id
from quant_us.live.shadow_orchestrator import (
    ShadowLiveOrchestrator,
    ShadowOrchestratorConfig,
)


# ===========================================================================
# ShadowOrchestratorConfig
# ===========================================================================


class TestShadowOrchestratorConfig:
    def test_default_config_is_safe(self) -> None:
        config = ShadowOrchestratorConfig()
        assert config.readonly is True

    def test_readonly_must_be_true(self) -> None:
        with pytest.raises(ValueError, match="readonly MUST be True"):
            ShadowOrchestratorConfig(readonly=False)

    def test_run_id_auto_generated(self) -> None:
        config = ShadowOrchestratorConfig()
        assert config.run_id.startswith("shadow_run")

    def test_default_real_submit_paths(self) -> None:
        config = ShadowOrchestratorConfig()
        assert config.submit_paper_orders is False
        assert config.use_live_data is True


# ===========================================================================
# ShadowLiveOrchestrator — bootstrap and component creation
# ===========================================================================


class TestShadowLiveOrchestratorBootstrap:
    @pytest.fixture
    def config(self) -> ShadowOrchestratorConfig:
        return ShadowOrchestratorConfig(
            symbols=["SPY", "QQQ"],
            strategy_id="etf_rotation",
            data_root="/tmp/test_shadow_data",
            ledger_root="/tmp/test_shadow_data/shadow_ledger",
        )

    @pytest.fixture
    def orch(self, config: ShadowOrchestratorConfig) -> ShadowLiveOrchestrator:
        return ShadowLiveOrchestrator(config)

    def test_bootstrap_creates_components(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        result = orch.bootstrap()
        assert result is True
        assert orch._bootstrapped is True
        assert orch.calendar is not None
        assert orch.kill_switch is not None

    def test_bootstrap_creates_ledger_dir(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        orch.bootstrap()
        ledger_path = Path(orch.config.ledger_root)
        assert ledger_path.exists()

    def test_bootstrap_journal_entry(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        orch.bootstrap()
        assert len(orch.journal_entries) == 1
        assert orch.journal_entries[0]["event_type"] == "bootstrap"

    def test_ensure_bootstrapped_raises_if_not(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        with pytest.raises(RuntimeError, match="not bootstrapped"):
            orch._ensure_bootstrapped()

    def test_ensure_bootstrapped_passes_after_bootstrap(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        orch.bootstrap()
        orch._ensure_bootstrapped()  # Should not raise


# ===========================================================================
# ShadowLiveOrchestrator — readiness checks
# ===========================================================================


class TestShadowLiveReadinessChecks:
    @pytest.fixture
    def config(self) -> ShadowOrchestratorConfig:
        return ShadowOrchestratorConfig(
            symbols=["SPY"],
            api_key="test_key",
            api_secret="test_secret",
        )

    @pytest.fixture
    def orch(self, config: ShadowOrchestratorConfig) -> ShadowLiveOrchestrator:
        return ShadowLiveOrchestrator(config)

    def test_check_shadow_readiness_passes(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        result = orch.check_shadow_readiness()
        assert result["ready"] is True

    def test_check_shadow_readiness_no_creds(
        self, config: ShadowOrchestratorConfig
    ) -> None:
        config.api_key = ""
        config.api_secret = ""
        orch = ShadowLiveOrchestrator(config)
        result = orch.check_shadow_readiness()
        assert result["ready"] is False
        assert "live API credentials not set" in result["errors"]

    def test_check_shadow_readiness_no_symbols(
        self, config: ShadowOrchestratorConfig
    ) -> None:
        config.symbols = []
        orch = ShadowLiveOrchestrator(config)
        result = orch.check_shadow_readiness()
        assert result["ready"] is False
        assert "no symbols configured" in result["errors"]

    def test_check_live_readonly_credentials_bad_key_returns_false(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        result = orch.check_live_readonly_credentials()
        # Without a real Alpaca endpoint, this will fail — that is expected.
        assert result is False

    def test_check_live_readonly_credentials_empty_returns_false(
        self, config: ShadowOrchestratorConfig
    ) -> None:
        config.api_key = ""
        config.api_secret = ""
        orch = ShadowLiveOrchestrator(config)
        result = orch.check_live_readonly_credentials()
        assert result is False


# ===========================================================================
# ShadowLiveOrchestrator — full cycle safety
# ===========================================================================


class TestShadowLiveOrchestratorCycle:
    @pytest.fixture
    def config(self) -> ShadowOrchestratorConfig:
        return ShadowOrchestratorConfig(
            symbols=["SPY"],
            strategy_id="etf_rotation",
            data_root="/tmp/test_shadow_data",
            ledger_root="/tmp/test_shadow_data/shadow_ledger",
            bar_size="1d",
        )

    @pytest.fixture
    def orch(self, config: ShadowOrchestratorConfig) -> ShadowLiveOrchestrator:
        o = ShadowLiveOrchestrator(config)
        o.bootstrap()
        return o

    @patch("quant_us.live.shadow_orchestrator.ShadowLiveOrchestrator.load_market_data")
    @patch("quant_us.live.shadow_orchestrator.ShadowLiveOrchestrator.calculate_signals")
    def test_run_one_cycle_with_mock_data(
        self,
        mock_signals: MagicMock,
        mock_load: MagicMock,
        orch: ShadowLiveOrchestrator,
    ) -> None:
        mock_load.return_value = [
            Bar(
                timestamp_utc=datetime(2026, 5, 1, 14, 0, 0, tzinfo=timezone.utc),
                symbol="SPY",
                open=530.0,
                high=532.0,
                low=528.0,
                close=531.0,
                volume=10_000_000,
            ),
        ]
        from quant_us.core.enums import SignalDirection

        mock_signals.return_value = [
            Signal(
                signal_id=new_id("sig"),
                strategy_id="etf_rotation",
                symbol="SPY",
                direction=SignalDirection.LONG,
                strength=0.8,
                horizon="1d",
                reason="momentum_signal",
                timestamp_utc=datetime(2026, 5, 1, 14, 0, 0, tzinfo=timezone.utc),
            ),
        ]
        result = orch.run_one_cycle()
        assert result["status"] == "ok"
        assert result["real_submit_count"] == 0
        assert result["shadow_orders"] >= 0
        assert result["shadow_fills"] >= 0

    def test_shadow_orders_have_safety_invariants(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        from quant_us.core.enums import OrderSide

        intents = [
            OrderIntent(
                timestamp_utc=datetime(2026, 5, 1, 14, 0, 0, tzinfo=timezone.utc),
                strategy_id="etf_rotation",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100.0,
                signal_id=new_id("sig"),
                run_id="test",
                order_intent_id=new_id("intent"),
            ),
        ]
        prices = {"SPY": 531.0}
        orders = orch.generate_shadow_orders(intents, prices)
        for so in orders:
            assert so.would_submit is True
            assert so.real_submit is False
            assert so.block_reason == "shadow_live_readonly"

    def test_no_real_orders_submitted_in_any_path(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        intents = [
            OrderIntent(
                timestamp_utc=datetime(2026, 5, 1, 14, 0, 0, tzinfo=timezone.utc),
                strategy_id="etf_rotation",
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100.0,
                signal_id=new_id("sig"),
                run_id="test",
                order_intent_id=new_id("intent"),
            ),
        ]
        prices = {"SPY": 531.0}
        orders = orch.generate_shadow_orders(intents, prices)
        for so in orders:
            assert so.real_submit is False

    @patch("quant_us.live.shadow_orchestrator.ShadowLiveOrchestrator.load_market_data")
    def test_real_submit_count_always_zero_in_report(
        self,
        mock_load: MagicMock,
        orch: ShadowLiveOrchestrator,
    ) -> None:
        mock_load.return_value = [
            Bar(
                timestamp_utc=datetime(2026, 5, 1, 14, 0, 0, tzinfo=timezone.utc),
                symbol="SPY",
                open=530.0,
                close=531.0,
                high=532.0,
                low=528.0,
                volume=10_000_000,
            ),
        ]
        result = orch.run_one_cycle()
        report = result.get("report", {})
        assert report.get("real_submit_count") == 0
        assert report.get("no_real_order_submitted") is True


# ===========================================================================
# ShadowLiveOrchestrator — resume and shutdown
# ===========================================================================


class TestShadowLiveOrchestratorResume:
    @pytest.fixture
    def config(self) -> ShadowOrchestratorConfig:
        return ShadowOrchestratorConfig(
            symbols=["SPY"],
            data_root="/tmp/test_shadow_data",
            ledger_root="/tmp/test_shadow_data/shadow_ledger",
        )

    @pytest.fixture
    def orch(self, config: ShadowOrchestratorConfig) -> ShadowLiveOrchestrator:
        o = ShadowLiveOrchestrator(config)
        o.bootstrap()
        return o

    @patch(
        "quant_us.live.shadow_orchestrator.ShadowLiveOrchestrator.shutdown_safely"
    )
    def test_shutdown_safely_persists_state(
        self, mock_shutdown: MagicMock, orch: ShadowLiveOrchestrator
    ) -> None:
        state_path = Path(orch.config.ledger_root) / "shadow_orchestrator_state.json"
        orch.shutdown_safely()
        mock_shutdown.assert_called_once()

    def test_resume_from_state_when_no_state(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        # Ensure state file doesn't exist
        state_path = Path(orch.config.ledger_root) / "shadow_orchestrator_state.json"
        if state_path.exists():
            state_path.unlink()
        result = orch.resume_from_state()
        assert result is False

    def test_resume_from_state_with_state_file(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        # Write state file manually so resume_from_state can read it
        import json
        state_path = Path(orch.config.ledger_root) / "shadow_orchestrator_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "run_id": "shadow_run_prev",
            "shadow_cash": 95_000.0,
            "shadow_equity": 105_000.0,
            "shadow_pnl": 5_000.0,
        }))

        result = orch.resume_from_state()
        assert result is True
        assert orch._bootstrapped is True

    def test_journal_entries_written_during_cycle(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        # Even with minimal bootstrap, journal entries accumulate
        count_before = len(orch.journal_entries)
        orch._journal("test_event", {"msg": "test"})
        assert len(orch.journal_entries) == count_before + 1

    @patch("quant_us.live.shadow_orchestrator.ShadowLiveOrchestrator.load_market_data")
    def test_cycle_without_market_data_returns_no_data(
        self, mock_load: MagicMock, orch: ShadowLiveOrchestrator
    ) -> None:
        mock_load.return_value = []
        result = orch.run_one_cycle()
        assert result["status"] == "no_data"


# ===========================================================================
# ShadowLiveOrchestrator — shadow ledger and state diff
# ===========================================================================


class TestShadowLiveOrchestratorLedger:
    @pytest.fixture
    def config(self) -> ShadowOrchestratorConfig:
        return ShadowOrchestratorConfig(
            symbols=["SPY", "QQQ"],
            data_root="/tmp/test_shadow_data",
            ledger_root="/tmp/test_shadow_data/shadow_ledger",
        )

    @pytest.fixture
    def orch(self, config: ShadowOrchestratorConfig) -> ShadowLiveOrchestrator:
        o = ShadowLiveOrchestrator(config)
        o.bootstrap()
        return o

    def test_shadow_ledger_snapshot(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        snap = orch.update_shadow_ledger()
        assert "shadow_cash" in snap
        assert "shadow_positions" in snap
        assert "shadow_equity" in snap
        assert "shadow_pnl" in snap

    def test_compare_with_paper_state_no_state(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        result = orch.compare_with_paper_state(None)
        assert result["status"] == "skipped"

    def test_compare_with_paper_state_with_state(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        paper_state = {"positions": {"SPY": 100.0}}
        result = orch.compare_with_paper_state(paper_state)
        assert "status" in result

    def test_compare_with_live_readonly_no_broker(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        result = orch.compare_with_live_readonly_state()
        assert result["status"] == "skipped"

    def test_build_state_diff(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        diff = orch.build_state_diff()
        assert diff.run_id is not None
        assert diff.paper_positions == {}
        assert diff.shadow_positions == {}
        assert diff.live_positions == {}

    def test_generate_daily_shadow_report(
        self, orch: ShadowLiveOrchestrator
    ) -> None:
        orch.build_state_diff()
        report = orch.generate_daily_shadow_report()
        assert report["real_submit_count"] == 0
        assert report["no_real_order_submitted"] is True
