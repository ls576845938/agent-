from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone

import pytest

from quant_crypto.risk import (
    ActionRiskEffect,
    RiskConstitution,
    RiskAssessment,
    UnknownInputPolicy,
    assess_btc_risk,
    classify_action_risk_effect,
    evaluate_combined_loss,
    evaluate_protection_feasibility,
)
from quant_crypto.risk.liquidation import BTCReferencePriceState


def _constitution(**overrides: object) -> RiskConstitution:
    values: dict[str, object] = {
        "max_abs_position": 0.05,
        "max_quantity": 0.05,
        "max_notional": 5_000.0,
        "max_leverage": 2.0,
        "min_liquidation_buffer_bps": 100.0,
        "max_daily_loss": 100.0,
        "max_drawdown": 0.2,
        "max_combined_loss": 150.0,
        "protection_required": True,
        "unknown_input_policy": UnknownInputPolicy.REJECT,
    }
    values.update(overrides)
    return RiskConstitution(**values)


def _protection(*, position: float = 0.01, side: str = "sell", quantity: float | None = None) -> dict[str, object]:
    return {
        "present": True,
        "quantity": abs(position) if quantity is None else quantity,
        "side": side,
        "trigger_price": 95_000.0,
    }


def _prices(**overrides: object) -> BTCReferencePriceState:
    values: dict[str, object] = {
        "observed_at_utc": datetime(2026, 8, 22, tzinfo=timezone.utc),
        "signal_price": 100_000.0,
        "execution_price": 100_000.0,
        "mark_price": 100_000.0,
        "index_price": 99_990.0,
        "current_mark_price": 100_000.0,
        "spread_bps": 0.0,
        "cross_venue_deviation_bps": 0.0,
        "data_age_ms": 0,
        "order_book_depth_usd": 1_000_000.0,
        "source": "contract-fixture",
    }
    values.update(overrides)
    return BTCReferencePriceState(**values)


def test_failure_first_base_did_not_expose_t2_contract() -> None:
    # T2 is additive.  The old liquidation module has no constitution,
    # combined-loss, protection-feasibility, or action-effect classifier.
    from quant_crypto.risk import liquidation

    assert not hasattr(liquidation, "RiskConstitution")
    assert not hasattr(liquidation, "evaluate_combined_loss")
    assert not hasattr(liquidation, "evaluate_protection_feasibility")
    assert ActionRiskEffect is not None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (0.01, 0.005, ActionRiskEffect.DECREASE_ABS_EXPOSURE),
        (0.01, 0.0, ActionRiskEffect.DECREASE_ABS_EXPOSURE),
        (0.01, 0.02, ActionRiskEffect.INCREASE_ABS_EXPOSURE),
        (0.01, -0.01, ActionRiskEffect.UNKNOWN),
        (None, 0.0, ActionRiskEffect.UNKNOWN),
    ],
)
def test_action_effect_is_derived_from_signed_position(before, after, expected) -> None:
    assert classify_action_risk_effect(before, after, "caller-label", "caller-label") is expected


def test_action_effect_protection_changes_are_secondary_to_true_reduction() -> None:
    before_protection = _protection()
    assert (
        classify_action_risk_effect(0.01, 0.0, before_protection, None)
        is ActionRiskEffect.DECREASE_ABS_EXPOSURE
    )
    assert (
        classify_action_risk_effect(0.01, 0.01, None, _protection())
        is ActionRiskEffect.ADD_PROTECTION
    )
    assert (
        classify_action_risk_effect(0.01, 0.01, before_protection, None, atomic_protection_replacement=True)
        is ActionRiskEffect.REMOVE_PROTECTION
    )


def test_combined_loss_uses_signed_pnl_and_explicit_costs() -> None:
    result = evaluate_combined_loss(
        realized_pnl=20.0,
        unrealized_pnl=-50.0,
        funding_cashflow=-5.0,
        fees=2.0,
        slippage=3.0,
        impact=4.0,
        account_equity=1_000.0,
        constitution=_constitution(max_combined_loss=40.0, max_daily_loss=40.0),
    )
    assert result.net_pnl == -44.0
    assert result.loss_amount == 44.0
    assert result.loss_ratio == 0.044
    assert "combined_loss_limit_breach" in result.blockers
    assert "daily_loss_limit_breach" in result.blockers


def test_combined_loss_nonfinite_and_negative_costs_fail_closed() -> None:
    assert "nonfinite_input" in evaluate_combined_loss(float("nan"), 0.0, 0.0).blockers
    assert "cost_input_invalid" in evaluate_combined_loss(0.0, 0.0, 0.0, fees=-1.0).blockers


def test_protection_feasibility_requires_valid_opposite_side_and_trigger() -> None:
    missing = evaluate_protection_feasibility(0.0, 0.01, None, None, mark_price=100_000.0)
    assert missing.allowed is False
    assert missing.blockers == ("protection_required", "protection_missing")
    invalid = evaluate_protection_feasibility(0.0, 0.01, None, _protection(side="buy"), mark_price=100_000.0)
    assert invalid.allowed is False
    assert invalid.blockers == ("protection_invalid",)
    valid = evaluate_protection_feasibility(0.0, 0.01, None, _protection(), mark_price=100_000.0)
    assert valid.allowed is True


def test_protection_removal_requires_flat_or_atomic_replacement() -> None:
    before = _protection()
    blocked = evaluate_protection_feasibility(0.01, 0.01, before, None, mark_price=100_000.0)
    assert blocked.allowed is False
    assert blocked.blockers == ("protection_removal_not_atomic",)
    replacement = evaluate_protection_feasibility(
        0.01,
        0.01,
        before,
        _protection(),
        mark_price=100_000.0,
        atomic_protection_replacement=True,
    )
    assert replacement.allowed is True
    flat = evaluate_protection_feasibility(0.01, 0.0, before, None, mark_price=100_000.0)
    assert flat.allowed is True


@pytest.mark.parametrize(
    ("position", "side", "trigger"),
    [(0.01, "sell", 100_000.0), (-0.01, "buy", 100_000.0)],
)
def test_protection_trigger_must_be_on_the_safe_side_of_mark(position, side, trigger) -> None:
    result = evaluate_protection_feasibility(
        0.0,
        position,
        None,
        _protection(position=position, side=side, quantity=abs(position)) | {"trigger_price": trigger},
        mark_price=100_000.0,
    )
    assert result.allowed is False
    assert result.blockers == ("protection_invalid",)


@pytest.mark.parametrize("mark", [None, 0.0, -1.0, float("nan")])
def test_protection_missing_or_invalid_mark_fails_closed(mark) -> None:
    result = evaluate_protection_feasibility(0.0, 0.01, None, _protection(), mark_price=mark)
    assert result.allowed is False
    assert result.blockers[0] in {"mark_price_missing", "mark_price_invalid"}


def test_btc_assessment_uses_existing_liquidation_formula_and_never_grants_execution() -> None:
    assessment = assess_btc_risk(
        constitution=_constitution(),
        position_before=0.0,
        position_after=0.01,
        mark_price=100_000.0,
        index_price=99_990.0,
        account_equity=10_000.0,
        protection_after=_protection(),
        reference_prices=_prices(),
    )
    assert assessment.approved is True
    assert assessment.effect is ActionRiskEffect.INCREASE_ABS_EXPOSURE
    assert assessment.execution_permission is False
    assert assessment.to_dict()["execution_permission"] is False
    assert assessment.leverage == pytest.approx(0.1)
    assert assessment.liquidation_buffer_bps is not None


def test_missing_mark_index_equity_and_position_are_unknown_before_liquidation() -> None:
    assessment = assess_btc_risk(
        constitution=_constitution(),
        position_before=None,
        position_after=0.01,
        mark_price=None,
        index_price=None,
        account_equity=None,
    )
    assert assessment.approved is False
    assert assessment.status == "rejected"
    assert assessment.effect is ActionRiskEffect.UNKNOWN
    assert assessment.blockers == (
        "unknown_input_rejected",
        "position_missing",
        "mark_price_missing",
        "index_price_missing",
        "account_equity_missing",
    )


def test_unknown_policy_is_executed_not_just_serialized() -> None:
    kwargs = {
        "constitution": _constitution(unknown_input_policy=UnknownInputPolicy.UNKNOWN),
        "position_before": None,
        "position_after": 0.01,
        "mark_price": None,
        "index_price": 100_000.0,
        "account_equity": 10_000.0,
    }
    assessment = assess_btc_risk(**kwargs)
    assert assessment.approved is False
    assert assessment.execution_permission is False
    assert assessment.status == "unknown"
    assert "unknown_input_unknown" in assessment.blockers


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [(0.10, 0.08, True), (0.10, 0.04, False), (0.0, 0.08, False)],
)
def test_requires_reduction_tracks_remaining_position_not_flat_rejected_proposal(before, after, expected) -> None:
    assessment = assess_btc_risk(
        constitution=_constitution(max_abs_position=0.05, max_quantity=0.05, protection_required=False),
        position_before=before,
        position_after=after,
        mark_price=100_000.0,
        index_price=99_990.0,
        account_equity=10_000.0,
        reference_prices=_prices(),
    )
    assert assessment.requires_reduction is expected
    if before == 0.0:
        assert assessment.approved is False


def test_nonempty_position_with_loss_limit_breach_requires_reduction() -> None:
    assessment = assess_btc_risk(
        constitution=_constitution(max_combined_loss=10.0, max_daily_loss=10.0, protection_required=False),
        position_before=0.04,
        position_after=0.04,
        mark_price=100_000.0,
        index_price=99_990.0,
        account_equity=10_000.0,
        realized_pnl=-20.0,
        unrealized_pnl=0.0,
        funding_cashflow=0.0,
        reference_prices=_prices(),
    )
    assert assessment.requires_reduction is True
    assert "combined_loss_limit_breach" in assessment.blockers


def test_risk_assessment_metadata_is_recursively_immutable_and_to_dict_is_independent() -> None:
    assessment = assess_btc_risk(
        constitution=_constitution(protection_required=False),
        position_before=0.01,
        position_after=0.005,
        mark_price=100_000.0,
        index_price=99_990.0,
        account_equity=10_000.0,
        reference_prices=_prices(),
    )
    before = assessment.to_dict()
    with pytest.raises(TypeError):
        assessment.metadata["constitution"]["max_leverage"] = 99.0
    with pytest.raises(TypeError):
        assessment.metadata["protection"]["allowed"] = False
    after = assessment.to_dict()
    assert before == after
    before["metadata"]["constitution"]["max_leverage"] = 99.0
    assert assessment.to_dict() == after


def test_risk_assessment_default_metadata_is_python311_compatible_and_isolated() -> None:
    first = RiskAssessment(
        approved=False,
        status="unknown",
        effect=ActionRiskEffect.UNKNOWN,
    )
    second = RiskAssessment(
        approved=False,
        status="unknown",
        effect=ActionRiskEffect.UNKNOWN,
    )
    assert first.metadata == second.metadata == {}
    assert first.metadata is not second.metadata
    with pytest.raises(TypeError):
        first.metadata["mutated"] = True

    explicit = {"nested": {"value": 1}}
    explicit_assessment = RiskAssessment(
        approved=False,
        status="blocked",
        effect=ActionRiskEffect.NO_POSITION_EFFECT,
        metadata=explicit,
    )
    explicit["nested"]["value"] = 2
    assert explicit_assessment.metadata["nested"]["value"] == 1
    with pytest.raises(TypeError):
        explicit_assessment.metadata["nested"]["value"] = 3


def test_limits_liquidation_and_protection_are_all_fail_closed() -> None:
    assessment = assess_btc_risk(
        constitution=_constitution(max_quantity=0.005, max_abs_position=0.005, max_notional=100.0, max_leverage=0.01),
        position_before=0.01,
        position_after=0.02,
        mark_price=100_000.0,
        index_price=99_000.0,
        account_equity=100.0,
        protection_after=None,
        reference_prices=_prices(mark_price=100_000.0, index_price=99_000.0),
    )
    assert assessment.approved is False
    assert "max_quantity_breach" in assessment.blockers
    assert "max_abs_position_breach" in assessment.blockers
    assert "max_notional_breach" in assessment.blockers
    assert "max_leverage_breach" in assessment.blockers
    assert "protection_missing" in assessment.blockers
    assert assessment.requires_reduction is True
    assert assessment.max_safe_quantity is not None


def test_cross_zero_and_unknown_reference_are_not_silent_reductions() -> None:
    assessment = assess_btc_risk(
        constitution=_constitution(protection_required=False),
        position_before=0.01,
        position_after=-0.001,
        mark_price=100_000.0,
        index_price=None,
        account_equity=10_000.0,
    )
    assert assessment.effect is ActionRiskEffect.UNKNOWN
    assert "cross_zero_position" not in assessment.blockers or "index_price_missing" in assessment.blockers


def test_assessment_and_serialization_are_deterministic_and_path_free() -> None:
    kwargs = {
        "constitution": _constitution(protection_required=False),
        "position_before": 0.01,
        "position_after": 0.005,
        "mark_price": 100_000.0,
        "index_price": 99_990.0,
        "account_equity": 10_000.0,
        "reference_prices": _prices(),
    }
    first = assess_btc_risk(**kwargs)
    second = assess_btc_risk(**kwargs)
    assert first == second
    assert first.to_dict() == second.to_dict()
    assert all("\\" not in reason and "/" not in reason for reason in first.blockers)


def test_kernel_has_no_runtime_or_transport_reverse_dependency() -> None:
    tree = ast.parse(inspect.getsource(__import__("quant_crypto.risk.kernel", fromlist=["kernel"])))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    forbidden = {
        "os",
        "pathlib",
        "requests",
        "httpx",
        "backend",
        "frontend",
        "quant_crypto.oms",
        "quant_crypto.application",
        "quant_crypto.runtime",
        "quant_crypto.adapters",
        "boto3",
        "ccxt",
        "ib_insync",
    }
    assert not any(name == forbidden_name or name.startswith(f"{forbidden_name}.") for name in imports for forbidden_name in forbidden)
    assert "quant_shared.runtime" in imports
    assert "liquidation" in imports  # relative import from quant_crypto.risk
