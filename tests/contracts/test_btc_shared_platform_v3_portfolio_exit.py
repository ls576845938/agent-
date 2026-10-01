from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone

import pytest

from quant_crypto.portfolio.decision import (
    BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION,
    BTC_RISK_REDUCTION_PLAN_VERSION,
    BTCPortfolioDecision,
    RiskReductionPlan,
    build_btc_portfolio_decision,
    build_risk_reduction_plan,
)
from quant_crypto.portfolio.forecast import (
    BTCRiskBudget,
    BTCRiskState,
    BTCForecastQuality,
    btc_forecast_to_target_position,
    signal_to_btc_forecast,
)
from quant_crypto.portfolio.order_intent import (
    BTCExecutionCostEstimate,
    btc_target_to_cost_aware_order_intent,
)
from quant_crypto.risk import ActionRiskEffect, RiskAssessment
from quant_crypto.trading_contracts import Signal, SignalDirection, TargetPosition


DECISION_TIME = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)


def _target(
    quantity: float,
    *,
    order_generation_allowed: bool = True,
    constraints: tuple[str, ...] = (),
    strategy_id: str = "btc_t3_strategy",
    symbol: str = "BTC-USDT-SWAP",
) -> TargetPosition:
    return TargetPosition(
        timestamp_utc=DECISION_TIME,
        strategy_id=strategy_id,
        symbol=symbol,
        target_weight=quantity,
        target_quantity=quantity,
        signal_id="sig_t3",
        metadata={
            "forecast_id": "fcst_t3",
            "order_generation_allowed": order_generation_allowed,
            "constraint_violations": list(constraints),
        },
    )


def _signal_target(quantity: float, *, signal_id: str = "sig_t3") -> TargetPosition:
    return TargetPosition(
        timestamp_utc=DECISION_TIME,
        strategy_id="btc_t3_strategy",
        symbol="BTC-USDT-SWAP",
        target_weight=quantity,
        target_quantity=quantity,
        signal_id=signal_id,
        metadata={
            "source_kind": "signal",
            "source_signal_id": signal_id,
            "order_generation_allowed": False,
        },
    )


def _assessment(
    *,
    approved: bool = False,
    requires_reduction: bool = True,
    max_safe_quantity: float | None = 0.005,
    blockers: tuple[str, ...] = ("daily_loss_limit_breach",),
    effect: ActionRiskEffect = ActionRiskEffect.DECREASE_ABS_EXPOSURE,
    position_before: float | None = None,
    position_after: float | None = None,
    metadata: dict[str, object] | None = None,
) -> RiskAssessment:
    assessment_metadata = dict(metadata or {})
    if position_before is not None:
        assessment_metadata["position_before"] = position_before
    if position_after is not None:
        assessment_metadata["position_after"] = position_after
    return RiskAssessment(
        approved=approved,
        status="approved" if approved else "blocked",
        effect=effect,
        blockers=blockers,
        reasons=blockers,
        requires_reduction=requires_reduction,
        max_safe_quantity=max_safe_quantity,
        metadata=assessment_metadata,
    )


def _assessment_for(
    target: TargetPosition,
    current_quantity: float,
    **kwargs: object,
) -> RiskAssessment:
    return _assessment(
        position_before=current_quantity,
        position_after=target.target_quantity,
        **kwargs,
    )


def _complete_cost() -> BTCExecutionCostEstimate:
    return BTCExecutionCostEstimate(
        fee_bps=4.0,
        spread_bps=2.0,
        slippage_bps=3.0,
        funding_bps=1.0,
        impact_bps=2.0,
        source="t3_contract",
    )


def _forecast_target(*, daily_loss: float = 0.0) -> TargetPosition:
    signal = Signal(
        timestamp_utc=DECISION_TIME,
        strategy_id="btc_t3_strategy",
        symbol="BTC-USDT-SWAP",
        direction=SignalDirection.LONG,
        strength=1.0,
        horizon="60m",
        reason="T3 contract",
    )
    forecast = signal_to_btc_forecast(
        signal,
        quality=BTCForecastQuality(ic=0.20, sample_size=200),
        horizon="60m",
    )
    return btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=0.50,
            strategy_risk_budget=0.50,
            target_volatility=0.20,
            current_weight=0.20,
            max_turnover=1.0,
            max_daily_loss_pct=0.03,
            max_drawdown_pct=0.12,
        ),
        risk_state=BTCRiskState(
            cash_fraction=0.8,
            daily_loss_pct=daily_loss,
            current_drawdown_pct=0.0,
            funding_rate=0.0001,
        ),
        account_equity=25_000.0,
        mark_price=50_000.0,
    )


def test_failure_first_daily_loss_keeps_blocked_target_but_exposes_reduction_plan() -> None:
    target = _forecast_target(daily_loss=0.031)
    assert target.target_quantity == 0.0
    assert target.metadata["order_generation_allowed"] is False

    assessment = _assessment_for(
        target,
        0.01,
        approved=False,
        requires_reduction=True,
        max_safe_quantity=0.0,
        blockers=("daily_loss_limit_breach",),
    )
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=assessment,
        decision_time_utc=DECISION_TIME,
    )

    assert decision.target_position is not target
    assert decision.target_position.target_position_id == target.target_position_id
    assert decision.approved is False
    assert decision.order_generation_allowed is False
    assert decision.reduction_plan is not None
    assert decision.reduction_plan.target_quantity == 0.0
    assert decision.reduction_plan.action is ActionRiskEffect.DECREASE_ABS_EXPOSURE
    assert "daily_loss_limit_breach" in decision.reduction_plan.reason_codes
    assert "target_blocks_order_generation" in decision.reduction_plan.reason_codes


def test_risk_stop_keeps_cost_aware_order_rejection_and_adds_independent_plan() -> None:
    target = _forecast_target(daily_loss=0.031)
    assessment = _assessment_for(
        target,
        0.01,
        approved=False,
        requires_reduction=True,
        max_safe_quantity=0.0,
        blockers=("daily_loss_limit_breach",),
    )
    cost_decision = btc_target_to_cost_aware_order_intent(
        target,
        current_quantity=0.01,
        cost_estimate=_complete_cost(),
        min_quantity=0.001,
    )
    assert cost_decision.approved is False
    assert cost_decision.order_intent is None
    assert "target_blocks_order_generation" in cost_decision.blockers

    portfolio_decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=assessment,
        decision_time_utc=DECISION_TIME,
    )
    assert portfolio_decision.reduction_plan is not None
    assert portfolio_decision.reduction_plan.target_quantity == 0.0


def test_failure_first_drawdown_keeps_old_order_rejection_semantics() -> None:
    target = _forecast_target(daily_loss=0.0)
    target = TargetPosition(
        timestamp_utc=target.timestamp_utc,
        strategy_id=target.strategy_id,
        symbol=target.symbol,
        target_weight=0.0,
        target_quantity=0.0,
        signal_id=target.signal_id,
        metadata={
            **target.metadata,
            "order_generation_allowed": False,
            "constraint_violations": ["drawdown_stop"],
        },
    )
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=-0.01,
        risk_assessment=_assessment_for(
            target,
            -0.01,
            max_safe_quantity=0.0,
            blockers=("drawdown_limit_breach",),
        ),
        decision_time_utc=DECISION_TIME,
    )
    assert decision.reduction_plan is not None
    assert decision.reduction_plan.target_quantity == 0.0
    assert "drawdown_stop" in decision.reason_codes
    assert decision.order_generation_allowed is False


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [(0.01, 0.0, 0.01), (-0.01, 0.0, 0.01), (0.01, 0.005, 0.005), (-0.01, -0.005, 0.005)],
)
def test_long_short_full_and_partial_reductions_are_signed_safely(current, target, expected) -> None:
    proposal = _target(target, order_generation_allowed=False)
    plan = build_risk_reduction_plan(
        proposal,
        current,
        _assessment_for(proposal, current, max_safe_quantity=0.02),
        DECISION_TIME,
    )
    assert plan is not None
    assert plan.reduction_quantity == pytest.approx(expected)
    assert plan.action is ActionRiskEffect.DECREASE_ABS_EXPOSURE
    assert plan.target_quantity == pytest.approx(target)


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [(0.01, 0.0, 0.01), (-0.01, 0.0, 0.01), (0.01, 0.005, 0.005)],
)
def test_explicit_signal_source_supports_full_and_partial_reduction(
    current: float,
    target: float,
    expected: float,
) -> None:
    proposal = _signal_target(target)
    plan = build_risk_reduction_plan(
        proposal,
        current,
        _assessment_for(proposal, current, max_safe_quantity=abs(target)),
        DECISION_TIME,
    )

    assert plan is not None
    assert plan.source_kind == "signal"
    assert plan.plan_version == BTC_RISK_REDUCTION_PLAN_VERSION
    assert plan.source_signal_id == proposal.signal_id
    assert plan.source_forecast_id == ""
    assert plan.reduction_quantity == pytest.approx(expected)
    assert plan.to_dict()["source_kind"] == "signal"


def test_signal_source_requires_explicit_single_identity_and_rejects_conflicts() -> None:
    base = _signal_target(0.0)
    missing = TargetPosition(
        timestamp_utc=base.timestamp_utc,
        strategy_id=base.strategy_id,
        symbol=base.symbol,
        target_weight=0.0,
        target_quantity=0.0,
        signal_id=base.signal_id,
        metadata={"source_kind": "signal", "order_generation_allowed": False},
    )
    conflict = TargetPosition(
        timestamp_utc=base.timestamp_utc,
        strategy_id=base.strategy_id,
        symbol=base.symbol,
        target_weight=0.0,
        target_quantity=0.0,
        signal_id=base.signal_id,
        metadata={
            "source_kind": "signal",
            "source_signal_id": base.signal_id,
            "forecast_id": "fcst_conflict",
            "order_generation_allowed": False,
        },
    )
    wrong = _signal_target(0.0, signal_id="sig_other")
    wrong.metadata["source_signal_id"] = "sig_t3"

    for proposal in (missing, conflict, wrong):
        assert (
            build_risk_reduction_plan(
                proposal,
                0.01,
                _assessment_for(proposal, 0.01, max_safe_quantity=0.0),
                DECISION_TIME,
            )
            is None
        )


def test_forecast_source_remains_backward_compatible_and_never_downgrades_to_signal() -> None:
    proposal = _target(0.0, order_generation_allowed=False)
    plan = build_risk_reduction_plan(
        proposal,
        0.01,
        _assessment_for(proposal, 0.01, max_safe_quantity=0.0),
        DECISION_TIME,
    )
    assert plan is not None
    assert plan.source_kind == "forecast"
    assert plan.plan_version == BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
    assert plan.source_forecast_id == "fcst_t3"
    assert plan.source_signal_id == ""

    no_source = TargetPosition(
        timestamp_utc=proposal.timestamp_utc,
        strategy_id=proposal.strategy_id,
        symbol=proposal.symbol,
        target_weight=0.0,
        target_quantity=0.0,
        signal_id=proposal.signal_id,
        metadata={"order_generation_allowed": False},
    )
    assert (
        build_risk_reduction_plan(
            no_source,
            0.01,
            _assessment_for(no_source, 0.01, max_safe_quantity=0.0),
            DECISION_TIME,
        )
        is None
    )

    conflicting_forecasts = TargetPosition(
        timestamp_utc=proposal.timestamp_utc,
        strategy_id=proposal.strategy_id,
        symbol=proposal.symbol,
        target_weight=0.0,
        target_quantity=0.0,
        signal_id=proposal.signal_id,
        metadata={
            "forecast_id": "fcst_one",
            "source_forecast_id": "fcst_two",
            "order_generation_allowed": False,
        },
    )
    assert (
        build_risk_reduction_plan(
            conflicting_forecasts,
            0.01,
            _assessment_for(
                conflicting_forecasts,
                0.01,
                max_safe_quantity=0.0,
            ),
            DECISION_TIME,
        )
        is None
    )


def test_legacy_forecast_plan_wire_shape_remains_available() -> None:
    plan = RiskReductionPlan(
        symbol="BTC-USDT-SWAP",
        strategy_id="btc_t3_strategy",
        decision_time_utc=DECISION_TIME,
        source_forecast_id="fcst_legacy",
        source_target_position_id="target_legacy",
        current_quantity=0.01,
        target_quantity=0.0,
        reduction_quantity=0.01,
        max_safe_quantity=0.0,
        reason_codes=("risk_reduction_required",),
        plan_version=BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION,
    )
    payload = plan.to_dict()
    assert payload["schema_version"] == BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
    assert "source_kind" not in payload
    assert "source_signal_id" not in payload
    assert payload["source_forecast_id"] == "fcst_legacy"


def test_default_forecast_constructor_keeps_legacy_wire_schema() -> None:
    plan = RiskReductionPlan(
        symbol="BTC-USDT-SWAP",
        strategy_id="btc_t3_strategy",
        decision_time_utc=DECISION_TIME,
        source_forecast_id="fcst_default",
        source_target_position_id="target_default",
        current_quantity=0.01,
        target_quantity=0.0,
        reduction_quantity=0.01,
        max_safe_quantity=0.0,
        reason_codes=("risk_reduction_required",),
    )
    payload = plan.to_dict()
    assert plan.plan_version == BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
    assert payload["schema_version"] == BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
    assert "source_kind" not in payload
    assert "source_signal_id" not in payload


def test_existing_positional_plan_action_and_version_arguments_remain_compatible() -> None:
    plan = RiskReductionPlan(
        "BTC-USDT-SWAP",
        "btc_t3_strategy",
        DECISION_TIME,
        "fcst_legacy",
        "target_legacy",
        0.01,
        0.0,
        0.01,
        0.0,
        ("risk_reduction_required",),
        ActionRiskEffect.DECREASE_ABS_EXPOSURE,
        BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION,
    )
    assert plan.action is ActionRiskEffect.DECREASE_ABS_EXPOSURE
    assert plan.plan_version == BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
    assert plan.source_kind == "forecast"


def test_plan_constructor_rejects_empty_dual_or_wrong_source_kind() -> None:
    common = {
        "symbol": "BTC-USDT-SWAP",
        "strategy_id": "btc_t3_strategy",
        "decision_time_utc": DECISION_TIME,
        "source_target_position_id": "target_t3",
        "current_quantity": 0.01,
        "target_quantity": 0.0,
        "reduction_quantity": 0.01,
        "max_safe_quantity": 0.0,
        "reason_codes": ("risk_reduction_required",),
        "plan_version": BTC_RISK_REDUCTION_PLAN_VERSION,
    }
    with pytest.raises(ValueError, match="signal source requires"):
        RiskReductionPlan(
            **common,
            source_kind="signal",
            source_signal_id="",
            source_forecast_id="",
        )
    with pytest.raises(ValueError, match="signal source requires"):
        RiskReductionPlan(
            **common,
            source_kind="signal",
            source_signal_id="sig_t3",
            source_forecast_id="fcst_t3",
        )
    with pytest.raises(ValueError, match="source kind is invalid"):
        RiskReductionPlan(
            **common,
            source_kind="score",
            source_signal_id="",
            source_forecast_id="fcst_t3",
        )


def test_progressive_reduction_caps_target_to_t2_safe_quantity() -> None:
    proposal = _target(0.008, order_generation_allowed=False)
    plan = build_risk_reduction_plan(
        proposal,
        0.01,
        _assessment_for(proposal, 0.01, max_safe_quantity=0.005),
        DECISION_TIME,
    )
    assert plan is not None
    assert plan.target_quantity == pytest.approx(0.005)
    assert plan.reduction_quantity == pytest.approx(0.005)
    assert "max_safe_quantity_cap" in plan.reason_codes


@pytest.mark.parametrize("target", [-0.001, 0.02])
def test_cross_zero_or_increase_never_becomes_a_reduction_plan(target) -> None:
    proposal = _target(target, order_generation_allowed=False)
    plan = build_risk_reduction_plan(
        proposal,
        0.01,
        _assessment_for(proposal, 0.01, max_safe_quantity=0.005),
        DECISION_TIME,
    )
    assert plan is None


@pytest.mark.parametrize("current", [0.0, None, float("nan"), float("inf")])
def test_flat_or_unknown_current_position_fails_closed(current) -> None:
    proposal = _target(0.0, order_generation_allowed=False)
    assert (
        build_risk_reduction_plan(
            proposal,
            current,
            _assessment_for(proposal, current, max_safe_quantity=0.0),
            DECISION_TIME,
        )
        is None
    )


def test_missing_assessment_or_safe_cap_fails_closed() -> None:
    target = _target(0.0, order_generation_allowed=False)
    assert build_risk_reduction_plan(target, 0.01, None, DECISION_TIME) is None
    assert (
        build_risk_reduction_plan(
            target,
            0.01,
            _assessment_for(target, 0.01, max_safe_quantity=None),
            DECISION_TIME,
        )
        is None
    )


def test_assessment_metadata_binding_missing_fails_closed() -> None:
    target = _target(0.0, order_generation_allowed=False)
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=_assessment(max_safe_quantity=0.0),
        decision_time_utc=DECISION_TIME,
    )
    assert decision.reduction_plan is None
    assert decision.order_generation_allowed is False
    assert "assessment_position_before_missing" in decision.reason_codes
    assert "assessment_position_after_missing" in decision.reason_codes


@pytest.mark.parametrize(
    ("assessment_factory", "expected_reason"),
    [
        (
            lambda target: _assessment_for(target, 0.02, max_safe_quantity=0.0),
            "assessment_position_before_mismatch",
        ),
        (
            lambda target: _assessment(
                max_safe_quantity=0.0,
                position_before=0.01,
                position_after=0.005,
            ),
            "assessment_position_after_mismatch",
        ),
        (
            lambda target: _assessment_for(
                target,
                0.01,
                max_safe_quantity=0.0,
                effect=ActionRiskEffect.INCREASE_ABS_EXPOSURE,
            ),
            "assessment_effect_mismatch",
        ),
    ],
)
def test_assessment_reuse_target_or_effect_mismatch_fails_closed(assessment_factory, expected_reason) -> None:
    target = _target(0.0, order_generation_allowed=False)
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=assessment_factory(target),
        decision_time_utc=DECISION_TIME,
    )
    assert decision.reduction_plan is None
    assert decision.order_generation_allowed is False
    assert expected_reason in decision.reason_codes


def test_approved_assessment_conflicts_and_nonempty_reasons_fail_closed() -> None:
    target = _target(0.005, order_generation_allowed=True)
    conflict = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=_assessment_for(
            target,
            0.01,
            approved=True,
            requires_reduction=True,
            max_safe_quantity=0.002,
            blockers=(),
            effect=ActionRiskEffect.DECREASE_ABS_EXPOSURE,
        ),
        decision_time_utc=DECISION_TIME,
    )
    assert conflict.reduction_plan is None
    assert conflict.approved is False
    assert "assessment_approved_requires_reduction_conflict" in conflict.reason_codes

    with_blockers = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=_assessment_for(
            target,
            0.01,
            approved=True,
            requires_reduction=False,
            max_safe_quantity=0.02,
            blockers=("unexpected_blocker",),
            effect=ActionRiskEffect.DECREASE_ABS_EXPOSURE,
        ),
        decision_time_utc=DECISION_TIME,
    )
    assert with_blockers.reduction_plan is None
    assert with_blockers.approved is False
    assert "assessment_approved_with_blockers" in with_blockers.reason_codes


@pytest.mark.parametrize("safe_quantity", [float("nan"), float("inf"), -0.001])
def test_invalid_max_safe_quantity_fails_closed(safe_quantity) -> None:
    target = _target(0.0, order_generation_allowed=False)
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=_assessment_for(
            target,
            0.01,
            max_safe_quantity=safe_quantity,
        ),
        decision_time_utc=DECISION_TIME,
    )
    assert decision.reduction_plan is None
    assert decision.order_generation_allowed is False
    assert "max_safe_quantity_invalid" in decision.reason_codes


def test_normal_unblocked_forecast_path_keeps_original_target_without_plan() -> None:
    target = _target(0.005, order_generation_allowed=True)
    assessment = _assessment_for(
        target,
        0.01,
        approved=True,
        requires_reduction=False,
        max_safe_quantity=0.02,
        blockers=(),
        effect=ActionRiskEffect.DECREASE_ABS_EXPOSURE,
    )
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=assessment,
        decision_time_utc=DECISION_TIME,
    )
    assert decision.target_position is not target
    assert decision.target_position.target_quantity == target.target_quantity
    assert decision.reduction_plan is None
    assert decision.approved is True
    assert decision.execution_permission is False


def test_requires_reduction_never_allows_the_original_target_order() -> None:
    target = _target(0.004, order_generation_allowed=True)
    assessment = _assessment_for(
        target,
        0.01,
        approved=True,
        requires_reduction=True,
        max_safe_quantity=0.002,
        blockers=(),
        effect=ActionRiskEffect.DECREASE_ABS_EXPOSURE,
    )
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=assessment,
        decision_time_utc=DECISION_TIME,
    )
    assert decision.reduction_plan is None
    assert decision.order_generation_allowed is False
    assert decision.approved is False
    assert "assessment_approved_requires_reduction_conflict" in decision.reason_codes


def test_research_and_runtime_use_identical_core_contract() -> None:
    target = _target(0.0, order_generation_allowed=False, constraints=("daily_loss_stop",))
    assessment = _assessment_for(target, 0.01, max_safe_quantity=0.0)
    research = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=assessment,
        decision_time_utc=DECISION_TIME,
        source="research",
    )
    runtime = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=assessment,
        decision_time_utc=DECISION_TIME,
        source="runtime",
    )
    assert research.source == "research"
    assert runtime.source == "runtime"
    assert research.reduction_plan == runtime.reduction_plan
    assert research.reason_codes == runtime.reason_codes
    assert research.reduction_plan is not None
    assert research.reduction_plan.to_dict() == runtime.reduction_plan.to_dict()


def test_plan_is_recursively_immutable_and_to_dict_is_detached() -> None:
    target = _target(0.0, order_generation_allowed=False)
    plan = build_risk_reduction_plan(
        target,
        0.01,
        _assessment_for(target, 0.01, max_safe_quantity=0.0),
        DECISION_TIME,
    )
    assert plan is not None
    assert plan.plan_version == BTC_RISK_REDUCTION_PLAN_LEGACY_VERSION
    assert isinstance(plan.reason_codes, tuple)
    payload = plan.to_dict()
    payload["reason_codes"].append("tampered")
    payload["target_quantity"] = 99.0
    assert "tampered" not in plan.reason_codes
    assert plan.target_quantity == 0.0


def test_decision_to_dict_detaches_target_metadata() -> None:
    target = _target(0.0, order_generation_allowed=False)
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=_assessment_for(target, 0.01, max_safe_quantity=0.0),
        decision_time_utc=DECISION_TIME,
    )
    payload = decision.to_dict()
    payload["target_position"]["metadata"]["forecast_id"] = "tampered"
    assert target.metadata["forecast_id"] == "fcst_t3"


def test_decision_target_snapshot_is_recursive_read_only_and_external_mutations_do_not_leak() -> None:
    target = _target(0.0, order_generation_allowed=False)
    target.metadata["nested"] = {"level": {"value": 1}}
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=_assessment_for(target, 0.01, max_safe_quantity=0.0),
        decision_time_utc=DECISION_TIME,
    )

    target.metadata["nested"]["level"]["value"] = 99
    assert decision.target_position.metadata["nested"]["level"]["value"] == 1
    with pytest.raises(TypeError):
        decision.target_position.metadata["forecast_id"] = "tampered"
    with pytest.raises(TypeError):
        decision.target_position.metadata["nested"]["level"]["value"] = 2

    payload = decision.to_dict()
    payload["target_position"]["metadata"]["nested"]["level"]["value"] = 7
    assert decision.target_position.metadata["nested"]["level"]["value"] == 1


def test_decision_has_no_execution_or_transport_dependency() -> None:
    import quant_crypto.portfolio.decision as module

    tree = ast.parse(inspect.getsource(module))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = {
        "os",
        "pathlib",
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "httpx",
        "backend",
        "frontend",
        "quant_crypto.oms",
        "quant_crypto.application",
        "quant_crypto.runtime",
        "quant_crypto.adapters",
        "quant_crypto.portfolio.order_intent",
        "boto3",
        "ccxt",
        "ib_insync",
    }
    assert not any(
        name == forbidden_name or name.startswith(f"{forbidden_name}.")
        for name in imports
        for forbidden_name in forbidden
    )
    assert "quant_crypto.risk" in imports
    assert "classify_action_risk_effect" in inspect.getsource(module)


def test_plan_construction_is_deterministic_for_same_explicit_inputs() -> None:
    target = _target(0.008, order_generation_allowed=False)
    kwargs = {
        "target_position": target,
        "current_quantity": 0.01,
        "risk_assessment": _assessment_for(target, 0.01, max_safe_quantity=0.005),
        "decision_time_utc": DECISION_TIME,
    }
    first = build_risk_reduction_plan(**kwargs)
    second = build_risk_reduction_plan(**kwargs)
    assert first == second
    assert first is not None
    assert first.to_dict() == second.to_dict()


def test_bundle_type_is_public_and_never_an_order_intent() -> None:
    target = _target(0.0, order_generation_allowed=False)
    decision = build_btc_portfolio_decision(
        target,
        current_quantity=0.01,
        risk_assessment=_assessment_for(target, 0.01, max_safe_quantity=0.0),
        decision_time_utc=DECISION_TIME,
        source="runtime",
    )
    assert isinstance(decision, BTCPortfolioDecision)
    assert decision.execution_permission is False
    assert decision.to_dict()["execution_permission"] is False
    assert "order_intent" not in decision.to_dict()
