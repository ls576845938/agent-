from __future__ import annotations

from datetime import datetime, timezone

from quant_us.risk.runtime_guardian import (
    GuardianStatus,
    RiskGuardian,
    RiskGuardianConfig,
    RiskGuardianObservation,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)


def _observation(**overrides: object) -> RiskGuardianObservation:
    values: dict[str, object] = {
        "observed_at": NOW,
        "equity": 10_000.0,
        "cash": 5_000.0,
        "daily_pnl": 0.0,
        "drawdown": 0.0,
        "gross_exposure": 5_000.0,
        "net_exposure": 5_000.0,
        "positions": {"AAPL": 5_000.0},
        "open_orders": 0,
        "unknown_orders": 0,
        "market_data_fresh": True,
        "market_data_age_seconds": 1.0,
        "broker_truth_fresh": True,
        "broker_truth_age_seconds": 1.0,
        "reconciliation_status": "pass",
        "heartbeat_age_seconds": 1.0,
        "heartbeat_ok": True,
        "account_verified": True,
        "position_mismatch": False,
        "cash_mismatch": False,
        "session_id": "paper-session-01",
    }
    values.update(overrides)
    return RiskGuardianObservation(**values)


def _guardian(**overrides: object) -> RiskGuardian:
    return RiskGuardian(
        RiskGuardianConfig(
            max_gross_exposure=8_000.0,
            max_net_exposure=8_000.0,
            max_position_size=6_000.0,
            max_daily_loss=500.0,
            max_drawdown=0.10,
            config_version="risk-guardian-test-v1",
            session_id="paper-session-01",
            **overrides,
        )
    )


def test_normal_account_passes_without_strategy_input() -> None:
    decision = _guardian().evaluate(_observation())

    assert decision.status is GuardianStatus.PASS
    assert decision.passed is True
    assert decision.block_new_orders is False
    assert decision.trip_kill_switch is False
    assert decision.recommended_trading_mode == "normal"
    assert decision.config_version == "risk-guardian-test-v1"
    assert decision.session_id == "paper-session-01"


def test_account_limits_trip_independent_guardian() -> None:
    decision = _guardian().evaluate(
        _observation(
            gross_exposure=9_000.0,
            net_exposure=8_500.0,
            positions={"AAPL": 7_000.0},
            daily_pnl=-600.0,
            drawdown=-0.11,
        )
    )

    rules = {violation.rule for violation in decision.violations}
    assert {"MAX_GROSS_EXPOSURE", "MAX_NET_EXPOSURE", "MAX_POSITION_SIZE", "MAX_DAILY_LOSS", "MAX_DRAWDOWN"} <= rules
    assert decision.status is GuardianStatus.TRIPPED
    assert decision.block_new_orders is True
    assert decision.trip_kill_switch is True
    assert decision.recommended_trading_mode == "frozen"


def test_unknown_order_reconciliation_and_staleness_fail_closed() -> None:
    decision = _guardian().evaluate(
        _observation(
            unknown_orders=[{"broker_order_id": "opaque"}],
            position_mismatch=True,
            cash_mismatch=True,
            market_data_fresh=False,
            broker_truth_age_seconds=301.0,
            reconciliation_status="failed",
        )
    )

    rules = {violation.rule for violation in decision.violations}
    assert {"UNKNOWN_BROKER_ORDER", "POSITION_MISMATCH", "CASH_MISMATCH", "MARKET_DATA_STALE", "BROKER_TRUTH_STALE", "RECONCILIATION_FAILED"} <= rules
    assert decision.block_new_orders is True
    assert decision.trip_kill_switch is True


def test_incomplete_or_unknown_observation_is_not_a_pass() -> None:
    decision = _guardian().evaluate(
        RiskGuardianObservation(
            observed_at=NOW,
            equity=10_000.0,
            cash=10_000.0,
            gross_exposure=0.0,
            net_exposure=0.0,
        )
    )

    assert decision.status is GuardianStatus.TRIPPED
    assert decision.block_new_orders is True
    assert "OBSERVATION_INCOMPLETE" in {violation.rule for violation in decision.violations}


def test_mapping_source_is_read_only_projection_and_config_is_audited() -> None:
    audit: list[tuple[str, dict[str, object]]] = []

    class Sink:
        def record(self, event_type: str, details: dict[str, object], timestamp=None) -> None:
            audit.append((event_type, details))

    guardian = RiskGuardian(
        RiskGuardianConfig(config_version="cfg-2026-08-07", session_id="session-a"),
        audit_sink=Sink(),
    )
    source = {
        "observed_at": NOW,
        "equity": 100.0,
        "cash": 100.0,
        "gross_exposure": 0.0,
        "net_exposure": 0.0,
        "positions": {},
        "market_data_fresh": True,
        "broker_truth_fresh": True,
        "reconciliation_status": "clean",
        "heartbeat_ok": True,
        "account_verified": True,
    }

    decision = guardian.evaluate(source)

    assert decision.status is GuardianStatus.PASS
    assert audit[0][0] == "risk_guardian_decision"
    assert audit[0][1]["config_version"] == "cfg-2026-08-07"
    assert audit[0][1]["session_id"] == "session-a"
    assert len(decision.config_hash) == 64


def test_enforce_only_trips_and_never_untrips() -> None:
    class FakeKillSwitch:
        def __init__(self) -> None:
            self.triggered = False
            self.reasons: list[str] = []

        def trip(self, reason: str) -> bool:
            self.triggered = True
            self.reasons.append(reason)
            return True

        def reset(self) -> None:  # pragma: no cover - guardian must never call it
            raise AssertionError("guardian must not reset a kill switch")

    switch = FakeKillSwitch()
    decision = _guardian().enforce(_observation(unknown_orders=1), switch)

    assert decision.trip_kill_switch is True
    assert switch.triggered is True
    assert switch.reasons == ["UNKNOWN_BROKER_ORDER"]
    assert not hasattr(RiskGuardian, "untrip")
    assert not hasattr(RiskGuardian, "reset_kill_switch")


def test_position_object_projection_uses_market_value() -> None:
    class Position:
        market_value = 9_000.0

    decision = _guardian().evaluate(_observation(positions={"AAPL": Position()}))

    assert decision.block_new_orders is True
    assert "MAX_POSITION_SIZE" in {violation.rule for violation in decision.violations}
