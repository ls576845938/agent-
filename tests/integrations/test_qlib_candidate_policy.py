from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from integrations.qlib_adapter.candidate_policy import (
    CandidateExitObservation,
    CandidateExitPolicy,
    CandidateExitState,
    CandidatePolicyFacts,
    CandidatePolicyVersions,
    evaluate_candidate_policy,
)
from quant_crypto.portfolio.forecast import (
    BTCForecast,
    BTCForecastQuality,
    BTCRiskBudget,
    BTCRiskState,
)
from quant_crypto.portfolio.order_intent import BTCExecutionCostEstimate
from quant_crypto.risk import RiskConstitution, evaluate_combined_loss
from quant_crypto.risk.liquidation import BTCReferencePriceState
from quant_crypto.trading_contracts import SignalDirection


WHEN = datetime(2026, 7, 1, 1, tzinfo=timezone.utc)


def _forecast(expected_bps: float = 50.0) -> BTCForecast:
    return BTCForecast(
        timestamp_utc=WHEN,
        strategy_id="qlib_fixture_strategy_v3",
        symbol="BTC-USDT-SWAP",
        direction=(SignalDirection.LONG if expected_bps > 0 else SignalDirection.SHORT),
        score=min(1.0, abs(expected_bps) / 100.0),
        horizon="12h",
        unit="bps",
        expected_return_bps=expected_bps,
        confidence=1.0,
        expiry_utc=WHEN + timedelta(hours=12),
        source_signal_id="v3-fixture-signal",
        forecast_id="v3-fixture-forecast",
        quality=BTCForecastQuality(
            ic=0.05,
            hit_rate=0.55,
            sample_size=100,
            evidence_path="fixture-only",
            evidence_hash="a" * 64,
        ),
        metadata={"fixture_only": True},
    )


def _facts(*, current_quantity: float = 0.0, blockers: tuple[str, ...] = ()) -> CandidatePolicyFacts:
    target_price = 60_000.0
    equity = 5_000.0
    constitution = RiskConstitution(
        max_abs_position=equity / target_price,
        max_quantity=equity / target_price,
        max_notional=equity * 0.25,
        max_leverage=1.0,
        min_liquidation_buffer_bps=1_000,
        max_daily_loss=equity * 0.03,
        max_drawdown=0.12,
        max_combined_loss=equity * 0.12,
        protection_required=True,
    )
    return CandidatePolicyFacts(
        decision_id="v3-fixture-decision",
        forecast=_forecast(),
        expected_source_signal_id="v3-fixture-signal",
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.25,
            strategy_risk_budget=0.25,
            target_volatility=0.20,
            current_weight=current_quantity * target_price / equity,
            min_cash_fraction=0.75,
            max_turnover=0.25,
            max_daily_loss_pct=0.03,
            max_drawdown_pct=0.12,
            max_abs_funding_rate=1.0,
            require_funding_rate=True,
        ),
        risk_state=BTCRiskState(
            cash_fraction=1.0,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.0,
            funding_rate=0.0001,
            data_anomaly=bool(blockers),
        ),
        account_equity=equity,
        mark_price=target_price,
        current_quantity=current_quantity,
        reference_prices=BTCReferencePriceState(
            observed_at_utc=WHEN,
            signal_price=target_price,
            execution_price=target_price * 1.0006,
            mark_price=target_price,
            index_price=target_price,
            current_mark_price=target_price,
            primary_mid=target_price,
            spread_bps=2.0,
            data_age_ms=0,
            source="v3_fixture",
        ),
        constitution=constitution,
        combined_loss=evaluate_combined_loss(
            0, 0, 0, 0, 0, 0,
            account_equity=equity,
            constitution=constitution,
            daily_loss=0,
            drawdown=0,
        ),
        protection_before=None,
        protection_after=lambda quantity: None if abs(quantity) < 1e-12 else {
            "present": True,
            "quantity": abs(quantity),
            "side": "sell" if quantity > 0 else "buy",
            "trigger_price": target_price * (0.96 if quantity > 0 else 1.04),
        },
        cost_estimate=BTCExecutionCostEstimate(
            fee_bps=10.0,
            spread_bps=2.0,
            slippage_bps=6.0,
            impact_bps=4.0,
            funding_bps=2.0,
            source="v3_fixture_frozen_cost",
        ),
        min_quantity=0.00001,
        blockers=blockers,
        exit_state=CandidateExitState(
            quantity=current_quantity,
            average_price=(target_price if current_quantity else 0.0),
            favorable_price=(target_price if current_quantity else None),
            holding_bars=0,
        ),
        exit_observation=CandidateExitObservation(
            close_price=target_price,
            calibrated_prediction=0.005,
            has_score=True,
            end_of_window=False,
        ),
        exit_policy=CandidateExitPolicy(
            hard_stop_fraction=0.04,
            trailing_stop_fraction=0.06,
            maximum_holding_bars=72,
        ),
        versions=CandidatePolicyVersions(
            policy_version="qlib_candidate_policy_v1",
            position_policy_sha256="b" * 64,
            exit_policy_sha256="c" * 64,
            cost_policy_sha256="d" * 64,
        ),
    )


def test_candidate_policy_preserves_forecast_target_and_cost_lineage() -> None:
    result = evaluate_candidate_policy(_facts())
    assert result.forecast.forecast_id == "v3-fixture-forecast"
    assert result.target.signal_id == result.forecast.source_signal_id
    assert result.target.metadata["forecast_id"] == result.forecast.forecast_id
    assert result.target.metadata["source_kind"] == "forecast"
    assert result.target.metadata["volatility_target_applied"] is False
    assert result.cost_decision.metadata["alpha_cost_gate"]["total_cost_bps"] == 24.0
    assert result.policy_versions.policy_version == "qlib_candidate_policy_v1"
    assert result.execution_permission is False


def test_candidate_quality_blocker_keeps_flat_and_never_approves_order() -> None:
    facts = _facts(blockers=("validation_calibration_quality_failed",))
    result = evaluate_candidate_policy(facts)
    assert result.target.target_quantity == pytest.approx(0.0)
    assert result.approved is False
    assert "validation_calibration_quality_failed" in result.reasons


def test_candidate_exit_flattens_without_crossing_zero() -> None:
    facts = _facts(current_quantity=0.01)
    facts = CandidatePolicyFacts(**{
        **facts.__dict__,
        "exit_observation": CandidateExitObservation(
            close_price=60_000.0,
            calibrated_prediction=-0.005,
            has_score=True,
            end_of_window=False,
        ),
    })
    result = evaluate_candidate_policy(facts)
    assert result.target.target_quantity == 0.0
    assert result.target.metadata["order_generation_allowed"] is True
    assert result.exit_reasons == ("forecast_reversal_flat_first",)
    assert result.execution_permission is False


@pytest.mark.parametrize(
    ("quantity", "average", "favorable", "close", "calibrated", "expected"),
    [
        (1.0, 100.0, 100.0, 95.0, 0.01, ("close_observed_hard_stop",)),
        (-1.0, 100.0, 100.0, 105.0, -0.01, ("close_observed_hard_stop",)),
        (1.0, 100.0, 120.0, 112.0, 0.01, ("close_observed_trailing_stop",)),
        (-1.0, 100.0, 80.0, 85.0, -0.01, ("close_observed_trailing_stop",)),
    ],
)
def test_original_exit_policy_long_short_hard_and_trailing(
    quantity: float,
    average: float,
    favorable: float,
    close: float,
    calibrated: float,
    expected: tuple[str, ...],
) -> None:
    facts = _facts(current_quantity=quantity)
    facts = CandidatePolicyFacts(**{
        **facts.__dict__,
        "exit_state": CandidateExitState(quantity, average, favorable, 0),
        "exit_observation": CandidateExitObservation(close, calibrated, True, False),
    })
    assert evaluate_candidate_policy(facts).exit_reasons == expected


def test_original_exit_policy_no_score_does_not_advance_holding() -> None:
    facts = _facts(current_quantity=1.0)
    facts = CandidatePolicyFacts(**{
        **facts.__dict__,
        "exit_state": CandidateExitState(1.0, 100.0, 120.0, 71),
        "exit_observation": CandidateExitObservation(90.0, -0.01, False, True),
    })
    result = evaluate_candidate_policy(facts)
    assert result.exit_reasons == ()
    assert result.exit_state == facts.exit_state


def test_original_exit_policy_accumulates_reasons_in_frozen_order() -> None:
    facts = _facts(current_quantity=1.0)
    facts = CandidatePolicyFacts(**{
        **facts.__dict__,
        "exit_state": CandidateExitState(1.0, 100.0, 120.0, 71),
        "exit_observation": CandidateExitObservation(90.0, 0.0, True, True),
    })
    result = evaluate_candidate_policy(facts)
    assert result.exit_reasons == (
        "close_observed_hard_stop",
        "close_observed_trailing_stop",
        "maximum_holding_period",
        "forecast_reversal_flat_first",
        "end_of_research_window",
    )
    assert result.exit_state.holding_bars == 72


def test_candidate_policy_rejects_forecast_source_mutation() -> None:
    facts = _facts()
    changed = BTCForecast(**{**facts.forecast.__dict__, "source_signal_id": "wrong-signal"})
    facts = CandidatePolicyFacts(**{**facts.__dict__, "forecast": changed})
    with pytest.raises(ValueError, match="candidate_forecast_source_signal_mismatch"):
        evaluate_candidate_policy(facts)
