"""Tests for Live Pilot Risk Envelope (G3).

Tests LivePilotRiskEnvelope, all limiters, and RiskEnvelopeManager.
"""

from __future__ import annotations

import json
import tempfile

import pytest

from quant_us.core.enums import OrderSide, OrderType
from quant_us.live.live_pilot_risk_envelope import (
    CapitalLimiter,
    ExposureLimiter,
    LivePilotRiskEnvelope,
    LossLimiter,
    NotionalLimiter,
    OrderTypeValidator,
    RiskEnvelopeManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store_path() -> str:
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def env() -> LivePilotRiskEnvelope:
    return LivePilotRiskEnvelope(envelope_id="env_test")


@pytest.fixture
def manager(store_path: str) -> RiskEnvelopeManager:
    return RiskEnvelopeManager(store_path=store_path)


# ---------------------------------------------------------------------------
# LivePilotRiskEnvelope
# ---------------------------------------------------------------------------


class TestLivePilotRiskEnvelope:
    def test_default_conservative(self) -> None:
        env = LivePilotRiskEnvelope.default_conservative(envelope_id="g3_live_001")
        assert env.envelope_id == "g3_live_001"
        assert env.max_total_capital == 1000.0
        assert env.max_order_notional == 100.0
        assert env.max_daily_notional == 300.0
        assert env.max_daily_order_count == 3
        assert env.max_gross_exposure_pct == 0.10
        assert env.max_single_symbol_exposure_pct == 0.05
        assert env.max_daily_loss_pct == 0.005
        assert env.max_drawdown_pct == 0.02
        assert env.max_consecutive_losses == 3

    def test_default_conservative_restrictions(self) -> None:
        env = LivePilotRiskEnvelope.default_conservative(envelope_id="g3_001")
        assert env.allow_fractional is False
        assert env.allow_market_order is False
        assert env.allow_pre_post_market is False
        assert env.allow_short is False
        assert env.allow_margin is False
        assert env.allow_options is False
        assert env.allowed_order_types == ["limit"]
        assert env.allowed_sessions == ["regular"]

    def test_default_conservative_force_stop(self) -> None:
        env = LivePilotRiskEnvelope.default_conservative(envelope_id="g3_001")
        assert env.reduce_only_on_warning is True
        assert env.force_stop_on_recon_fail is True
        assert env.force_stop_on_data_stale is True
        assert env.force_stop_on_broker_error is True

    def test_to_dict(self) -> None:
        env = LivePilotRiskEnvelope(envelope_id="e1", strategy_id="s1")
        d = env.to_dict()
        assert d["envelope_id"] == "e1"
        assert d["strategy_id"] == "s1"
        assert d["max_total_capital"] == 1000.0
        assert d["allow_market_order"] is False
        assert d["created_at"] != ""

    def test_from_dict_roundtrip(self) -> None:
        original = LivePilotRiskEnvelope(
            envelope_id="e_rt",
            strategy_id="momentum",
            max_total_capital=5000.0,
            allow_market_order=True,
        )
        data = original.to_dict()
        restored = LivePilotRiskEnvelope.from_dict(data)
        assert restored.envelope_id == original.envelope_id
        assert restored.strategy_id == original.strategy_id
        assert restored.max_total_capital == original.max_total_capital
        assert restored.allow_market_order == original.allow_market_order

    def test_from_dict_empty(self) -> None:
        restored = LivePilotRiskEnvelope.from_dict({})
        assert restored.envelope_id == ""


# ---------------------------------------------------------------------------
# CapitalLimiter
# ---------------------------------------------------------------------------


class TestCapitalLimiter:
    def test_under_limit_passes(self) -> None:
        limiter = CapitalLimiter()
        env = LivePilotRiskEnvelope(envelope_id="e1", max_total_capital=1000.0)
        result = limiter.check(env, proposed_capital=500.0)
        assert result.passed
        assert result.checks["capital_within_limit"] is True

    def test_at_limit_passes(self) -> None:
        limiter = CapitalLimiter()
        env = LivePilotRiskEnvelope(envelope_id="e1", max_total_capital=1000.0)
        result = limiter.check(env, proposed_capital=1000.0)
        assert result.passed

    def test_over_limit_fails(self) -> None:
        limiter = CapitalLimiter()
        env = LivePilotRiskEnvelope(envelope_id="e1", max_total_capital=1000.0)
        result = limiter.check(env, proposed_capital=1500.0)
        assert not result.passed
        assert "exceeds" in result.reason
        assert result.checks["capital_within_limit"] is False

    def test_zero_capital(self) -> None:
        limiter = CapitalLimiter()
        env = LivePilotRiskEnvelope(envelope_id="e1", max_total_capital=1000.0)
        result = limiter.check(env, proposed_capital=0.0)
        assert result.passed


# ---------------------------------------------------------------------------
# NotionalLimiter
# ---------------------------------------------------------------------------


class TestNotionalLimiter:
    def test_within_limits_passes(self) -> None:
        limiter = NotionalLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1",
            max_order_notional=100.0,
            max_daily_notional=300.0,
        )
        result = limiter.check(env, order_notional=50.0, daily_notional_used=100.0)
        assert result.passed
        assert result.checks["order_notional_within_limit"] is True
        assert result.checks["daily_notional_within_limit"] is True

    def test_exceeds_order_notional_fails(self) -> None:
        limiter = NotionalLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_order_notional=100.0, max_daily_notional=300.0
        )
        result = limiter.check(env, order_notional=150.0, daily_notional_used=0.0)
        assert not result.passed
        assert result.checks["order_notional_within_limit"] is False

    def test_exceeds_daily_notional_fails(self) -> None:
        limiter = NotionalLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_order_notional=100.0, max_daily_notional=300.0
        )
        result = limiter.check(env, order_notional=100.0, daily_notional_used=250.0)
        assert not result.passed
        assert result.checks["daily_notional_within_limit"] is False

    def test_exactly_at_daily_limit_passes(self) -> None:
        limiter = NotionalLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_order_notional=100.0, max_daily_notional=300.0
        )
        result = limiter.check(env, order_notional=100.0, daily_notional_used=200.0)
        assert result.passed

    def test_zero_notional(self) -> None:
        limiter = NotionalLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_order_notional=100.0, max_daily_notional=300.0
        )
        result = limiter.check(env, order_notional=0.0, daily_notional_used=0.0)
        assert result.passed


# ---------------------------------------------------------------------------
# ExposureLimiter
# ---------------------------------------------------------------------------


class TestExposureLimiter:
    def test_within_limits_passes(self) -> None:
        limiter = ExposureLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1",
            max_gross_exposure_pct=0.10,
            max_single_symbol_exposure_pct=0.05,
        )
        result = limiter.check(env, gross_exposure_pct=0.05, max_single_exposure_pct=0.03)
        assert result.passed
        assert result.checks["gross_exposure_within_limit"] is True
        assert result.checks["single_symbol_exposure_within_limit"] is True

    def test_exceeds_gross_fails(self) -> None:
        limiter = ExposureLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1",
            max_gross_exposure_pct=0.10,
            max_single_symbol_exposure_pct=0.05,
        )
        result = limiter.check(env, gross_exposure_pct=0.15, max_single_exposure_pct=0.03)
        assert not result.passed
        assert result.checks["gross_exposure_within_limit"] is False

    def test_exceeds_single_symbol_fails(self) -> None:
        limiter = ExposureLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1",
            max_gross_exposure_pct=0.10,
            max_single_symbol_exposure_pct=0.05,
        )
        result = limiter.check(env, gross_exposure_pct=0.05, max_single_exposure_pct=0.08)
        assert not result.passed
        assert result.checks["single_symbol_exposure_within_limit"] is False

    def test_at_exact_limits_passes(self) -> None:
        limiter = ExposureLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1",
            max_gross_exposure_pct=0.10,
            max_single_symbol_exposure_pct=0.05,
        )
        result = limiter.check(env, gross_exposure_pct=0.10, max_single_exposure_pct=0.05)
        assert result.passed


# ---------------------------------------------------------------------------
# OrderTypeValidator
# ---------------------------------------------------------------------------


class TestOrderTypeValidator:
    def test_limit_order_buy_regular_passes(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(envelope_id="e1")
        result = validator.check(
            env,
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            session="regular",
        )
        assert result.passed

    def test_market_order_blocked(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(envelope_id="e1", allow_market_order=False)
        result = validator.check(
            env,
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            session="regular",
        )
        assert not result.passed
        assert "Market orders not allowed" in result.reason

    def test_market_order_allowed_when_enabled(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(envelope_id="e1", allow_market_order=True)
        result = validator.check(
            env,
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            session="regular",
        )
        assert result.passed

    def test_short_sell_blocked(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(envelope_id="e1", allow_short=False)
        result = validator.check(
            env,
            order_type=OrderType.LIMIT,
            side=OrderSide.SELL,
            session="regular",
        )
        assert not result.passed
        assert "Short selling not allowed" in result.reason

    def test_short_allowed_when_enabled(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(envelope_id="e1", allow_short=True)
        result = validator.check(
            env,
            order_type=OrderType.LIMIT,
            side=OrderSide.SELL,
            session="regular",
        )
        assert result.passed

    def test_pre_post_market_blocked(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(envelope_id="e1", allow_pre_post_market=False)
        result = validator.check(
            env,
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            session="pre",
        )
        assert not result.passed
        assert "pre" in result.reason

    def test_pre_post_market_allowed(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", allow_pre_post_market=True, allowed_sessions=["regular", "pre", "post"]
        )
        result = validator.check(
            env,
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            session="post",
        )
        assert result.passed

    def test_stop_order_not_in_allowed_types(self) -> None:
        validator = OrderTypeValidator()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", allowed_order_types=["limit"]
        )
        result = validator.check(
            env,
            order_type=OrderType.STOP,
            side=OrderSide.BUY,
            session="regular",
        )
        assert not result.passed
        assert "not in allowed types" in result.reason


# ---------------------------------------------------------------------------
# LossLimiter
# ---------------------------------------------------------------------------


class TestLossLimiter:
    def test_within_limits_passes(self) -> None:
        limiter = LossLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1",
            max_daily_loss_pct=0.005,
            max_drawdown_pct=0.02,
            max_consecutive_losses=3,
        )
        result = limiter.check(
            env,
            daily_loss_pct=0.002,
            current_drawdown_pct=0.01,
            consecutive_losses=1,
        )
        assert result.passed

    def test_exceeds_daily_loss_fails(self) -> None:
        limiter = LossLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_daily_loss_pct=0.005, max_drawdown_pct=0.02, max_consecutive_losses=3
        )
        result = limiter.check(
            env,
            daily_loss_pct=0.01,
            current_drawdown_pct=0.01,
            consecutive_losses=1,
        )
        assert not result.passed
        assert result.checks["daily_loss_within_limit"] is False

    def test_exceeds_drawdown_fails(self) -> None:
        limiter = LossLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_daily_loss_pct=0.005, max_drawdown_pct=0.02, max_consecutive_losses=3
        )
        result = limiter.check(
            env,
            daily_loss_pct=0.001,
            current_drawdown_pct=0.05,
            consecutive_losses=1,
        )
        assert not result.passed
        assert result.checks["drawdown_within_limit"] is False

    def test_exceeds_consecutive_losses_fails(self) -> None:
        limiter = LossLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_daily_loss_pct=0.005, max_drawdown_pct=0.02, max_consecutive_losses=3
        )
        result = limiter.check(
            env,
            daily_loss_pct=0.001,
            current_drawdown_pct=0.01,
            consecutive_losses=5,
        )
        assert not result.passed
        assert result.checks["consecutive_losses_within_limit"] is False

    def test_at_exact_limits_passes(self) -> None:
        limiter = LossLimiter()
        env = LivePilotRiskEnvelope(
            envelope_id="e1", max_daily_loss_pct=0.005, max_drawdown_pct=0.02, max_consecutive_losses=3
        )
        result = limiter.check(
            env,
            daily_loss_pct=0.005,
            current_drawdown_pct=0.02,
            consecutive_losses=3,
        )
        assert result.passed


# ---------------------------------------------------------------------------
# RiskEnvelopeManager
# ---------------------------------------------------------------------------


class TestRiskEnvelopeManager:
    def test_create_and_load_roundtrip(self, manager: RiskEnvelopeManager) -> None:
        env = LivePilotRiskEnvelope(
            envelope_id="e_rt",
            strategy_id="etf_rotation",
            max_total_capital=2000.0,
        )
        manager.create(env)
        loaded = manager.load("e_rt")
        assert loaded is not None
        assert loaded.envelope_id == "e_rt"
        assert loaded.strategy_id == "etf_rotation"
        assert loaded.max_total_capital == 2000.0

    def test_load_nonexistent_returns_none(self, manager: RiskEnvelopeManager) -> None:
        assert manager.load("does_not_exist") is None

    def test_create_persists_to_disk(
        self, manager: RiskEnvelopeManager, store_path: str
    ) -> None:
        env = LivePilotRiskEnvelope(envelope_id="disk_test")
        manager.create(env)
        path = manager.store_path / "disk_test.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["envelope_id"] == "disk_test"

    def test_validate_passes_when_all_clean(
        self, manager: RiskEnvelopeManager
    ) -> None:
        env = LivePilotRiskEnvelope(envelope_id="clean_test")
        manager.create(env)
        result = manager.validate(
            envelope_id="clean_test",
            order_notional=50.0,
            daily_notional_used=100.0,
            gross_exposure_pct=0.05,
            max_single_exposure_pct=0.03,
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            session="regular",
            daily_loss_pct=0.001,
            current_drawdown_pct=0.01,
            consecutive_losses=0,
        )
        assert result["passed"] is True
        assert result["reduce_only"] is False

    def test_validate_envelope_not_found(
        self, manager: RiskEnvelopeManager
    ) -> None:
        result = manager.validate(envelope_id="ghost")
        assert result["passed"] is False
        assert "not found" in result["reason"]

    def test_validate_reduce_only_on_recon_fail(
        self, manager: RiskEnvelopeManager
    ) -> None:
        env = LivePilotRiskEnvelope(envelope_id="recon_test", force_stop_on_recon_fail=True)
        manager.create(env)
        result = manager.validate(
            envelope_id="recon_test",
            recon_fail=True,
        )
        assert result["reduce_only"] is True
        assert result["checks"].get("recon", {}).get("force_stop") is True

    def test_validate_reduce_only_on_data_stale(
        self, manager: RiskEnvelopeManager
    ) -> None:
        env = LivePilotRiskEnvelope(envelope_id="stale_test", force_stop_on_data_stale=True)
        manager.create(env)
        result = manager.validate(
            envelope_id="stale_test",
            data_stale=True,
        )
        assert result["reduce_only"] is True
        assert result["checks"].get("data_stale", {}).get("force_stop") is True

    def test_validate_reduce_only_on_broker_error(
        self, manager: RiskEnvelopeManager
    ) -> None:
        env = LivePilotRiskEnvelope(envelope_id="broker_test", force_stop_on_broker_error=True)
        manager.create(env)
        result = manager.validate(
            envelope_id="broker_test",
            broker_error=True,
        )
        assert result["reduce_only"] is True
        assert result["checks"].get("broker_error", {}).get("force_stop") is True

    def test_validate_no_reduce_only_when_flag_off(
        self, manager: RiskEnvelopeManager
    ) -> None:
        env = LivePilotRiskEnvelope(
            envelope_id="no_force",
            force_stop_on_recon_fail=False,
            force_stop_on_data_stale=False,
            force_stop_on_broker_error=False,
        )
        manager.create(env)
        result = manager.validate(
            envelope_id="no_force",
            recon_fail=True,
            data_stale=True,
            broker_error=True,
        )
        assert result["reduce_only"] is False

    def test_validate_notional_fail(
        self, manager: RiskEnvelopeManager
    ) -> None:
        env = LivePilotRiskEnvelope(
            envelope_id="notional_fail",
            max_order_notional=100.0,
            max_daily_notional=300.0,
        )
        manager.create(env)
        result = manager.validate(
            envelope_id="notional_fail",
            order_notional=500.0,
        )
        assert result["passed"] is False

    def test_validate_multiple_failures(
        self, manager: RiskEnvelopeManager
    ) -> None:
        env = LivePilotRiskEnvelope(
            envelope_id="multi_fail",
            max_order_notional=100.0,
            max_daily_loss_pct=0.005,
            force_stop_on_broker_error=True,
        )
        manager.create(env)
        result = manager.validate(
            envelope_id="multi_fail",
            order_notional=200.0,
            daily_loss_pct=0.01,
            broker_error=True,
        )
        assert result["passed"] is False
        assert result["reduce_only"] is True

    def test_audit_written_on_create(
        self, manager: RiskEnvelopeManager, store_path: str
    ) -> None:
        env = LivePilotRiskEnvelope(envelope_id="audit_test")
        manager.create(env)
        audit_path = manager.store_path / "envelope_audit.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["event"] == "envelope_created"
