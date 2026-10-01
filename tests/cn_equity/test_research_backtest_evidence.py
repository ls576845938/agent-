from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quant_cn.application.market_semantics_preflight import MarketSemanticsPreflight
from quant_cn.application.research_pipeline import (
    ResearchRequest,
    run_research_pipeline,
)
from quant_cn.backtest.costs import CostScenario, validate_cost_ladder
from quant_cn.backtest.events import BacktestEvent
from quant_cn.market.rules import BoardLotPolicy
from quant_cn.research.validation import (
    FoldResult,
    Trial,
    TrialRegistry,
    ValidationPlan,
    WalkForwardFold,
)
from quant_cn.strategy.contracts import (
    DecisionSnapshot,
    Forecast,
    Signal,
    TargetPosition,
)


UTC = timezone.utc
RULE_VERSIONS = (
    ("board_lot", "fixture-board-lot-v1"),
    ("fee_schedule", "fixture-fee-v1"),
    ("price_limit", "fixture-limit-v1"),
    ("sellability", "fixture-t1-v1"),
    ("session", "fixture-session-v1"),
    ("settlement", "fixture-settlement-v1"),
)
RULE_SOURCES = tuple((name, f"fixture://{name}/v1") for name, _ in RULE_VERSIONS)


class FixtureStrategy:
    strategy_id = "cn-fixture-threshold"
    strategy_version = "strategy-v1"

    def generate_signal(self, snapshot: DecisionSnapshot) -> Signal:
        direction = "long" if snapshot.feature_value > 0 else "flat"
        return Signal(
            signal_id=f"signal-{snapshot.snapshot_id}",
            strategy_id=self.strategy_id,
            stable_security_id=snapshot.stable_security_id,
            decision_time=snapshot.decision_time,
            direction=direction,
            strength=Decimal("0.8") if direction == "long" else Decimal("0"),
            horizon_sessions=2,
            snapshot_id=snapshot.snapshot_id,
        )


class FixtureForecastModel:
    model_version = "forecast-v1"

    def forecast(self, signal: Signal, snapshot: DecisionSnapshot) -> Forecast:
        expected = Decimal("0.02") if signal.direction == "long" else Decimal("0")
        return Forecast(
            forecast_id=f"forecast-{snapshot.snapshot_id}",
            signal_id=signal.signal_id,
            strategy_id=signal.strategy_id,
            stable_security_id=signal.stable_security_id,
            decision_time=signal.decision_time,
            expected_return=expected,
            confidence=signal.strength,
            horizon_sessions=signal.horizon_sessions,
            model_version=self.model_version,
        )


class FixtureTargetBuilder:
    def build_target(
        self,
        forecast: Forecast,
        snapshot: DecisionSnapshot,
        *,
        current_quantity: int,
        capacity_quantity: int,
    ) -> TargetPosition:
        target = min(100, capacity_quantity) if forecast.expected_return > 0 else 0
        return TargetPosition(
            target_id=f"target-{snapshot.snapshot_id}",
            forecast_id=forecast.forecast_id,
            signal_id=forecast.signal_id,
            strategy_id=forecast.strategy_id,
            stable_security_id=forecast.stable_security_id,
            decision_time=forecast.decision_time,
            target_quantity=target,
            forecast_confidence=forecast.confidence,
            capacity_quantity=capacity_quantity,
            sizing_reason="fixture forecast bounded by explicit capacity",
        )


def pass_preflight() -> MarketSemanticsPreflight:
    return MarketSemanticsPreflight(
        status="pass",
        decision="research_only",
        blockers=(),
        versions=RULE_VERSIONS,
        sources=RULE_SOURCES,
    )


def event(
    index: int,
    *,
    feature: str,
    price: str,
    data_version: str = "fixture-v1",
) -> BacktestEvent:
    day = datetime(2025, 4, index + 1, 1, tzinfo=UTC)
    reference = Decimal(price)
    return BacktestEvent(
        event_id=f"event-{index}",
        stable_security_id="CN:600000",
        event_time=day,
        available_time=day + timedelta(hours=1),
        decision_time=day + timedelta(hours=2),
        order_created_time=day + timedelta(hours=2, minutes=1),
        execution_time=day + timedelta(hours=3),
        feature_value=Decimal(feature),
        reference_price=reference,
        mark_price=reference + Decimal("0.10"),
        lower_limit_price=Decimal("5.00"),
        upper_limit_price=Decimal("20.00"),
        tick_size=Decimal("0.01"),
        available_liquidity=1000,
        capacity_quantity=100,
        session_sequence=index,
        phase="continuous",
        accepts_orders=True,
        suspended=False,
        data_version=data_version,
        rule_versions=RULE_VERSIONS,
        rule_sources=RULE_SOURCES,
        preflight=pass_preflight(),
        board_lot_policy=BoardLotPolicy(
            buy_lot_size=100,
            sell_lot_size=100,
            odd_lot_sell_allowed=False,
            odd_lot_sell_mode="forbidden",
        ),
    )


def events() -> tuple[BacktestEvent, ...]:
    return (
        event(1, feature="1", price="10.00"),
        event(2, feature="1", price="10.20"),
        event(3, feature="-1", price="10.50"),
        event(4, feature="-1", price="10.40"),
    )


def scenarios() -> tuple[CostScenario, ...]:
    return (
        CostScenario(
            "base",
            Decimal("0.001"),
            Decimal("0.001"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            "cost-v1-base",
        ),
        CostScenario(
            "conservative",
            Decimal("0.002"),
            Decimal("0.002"),
            Decimal("2"),
            Decimal("3"),
            Decimal("1"),
            "cost-v1-conservative",
        ),
        CostScenario(
            "stress",
            Decimal("0.003"),
            Decimal("0.003"),
            Decimal("3"),
            Decimal("5"),
            Decimal("1"),
            "cost-v1-stress",
        ),
    )


def registry() -> TrialRegistry:
    result = TrialRegistry(candidate_count=3)
    result.register(
        Trial(
            trial_id="trial-selected",
            params_hash="a" * 64,
            registered_at=datetime(2025, 3, 1, tzinfo=UTC),
            status="accepted",
            selected=True,
        )
    )
    result.register(
        Trial(
            trial_id="trial-rejected",
            params_hash="b" * 64,
            registered_at=datetime(2025, 3, 2, tzinfo=UTC),
            status="rejected",
        )
    )
    result.mark_holdout_viewed(datetime(2025, 5, 2, tzinfo=UTC))
    return result


def validation_plan() -> ValidationPlan:
    return ValidationPlan(
        folds=(
            WalkForwardFold(
                "fold-1",
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2023, 6, 1, tzinfo=UTC),
                datetime(2023, 6, 3, tzinfo=UTC),
                datetime(2023, 8, 1, tzinfo=UTC),
                datetime(2023, 8, 4, tzinfo=UTC),
                datetime(2023, 10, 1, tzinfo=UTC),
                timedelta(days=2),
                timedelta(days=3),
            ),
            WalkForwardFold(
                "fold-2",
                datetime(2023, 4, 1, tzinfo=UTC),
                datetime(2023, 10, 1, tzinfo=UTC),
                datetime(2023, 10, 3, tzinfo=UTC),
                datetime(2023, 12, 1, tzinfo=UTC),
                datetime(2023, 12, 4, tzinfo=UTC),
                datetime(2024, 2, 1, tzinfo=UTC),
                timedelta(days=2),
                timedelta(days=3),
            ),
        ),
        label_horizon=timedelta(days=1),
        holdout_start=datetime(2025, 4, 1, tzinfo=UTC),
        holdout_end=datetime(2025, 5, 1, tzinfo=UTC),
        selected_before_holdout=True,
        parameter_stability_passed=True,
    )


def request(
    *,
    data_mode: str = "fixture",
    data_source: str = "fixture:cn-research-v1",
    data_blockers: tuple[str, ...] = (),
    rule_blockers: tuple[str, ...] = (),
    data_handoff_validated: bool | None = None,
    market_rule_handoff_validated: bool | None = None,
    code_commit: str = "6ee6c4439f6bf6e8a8209ca6a919ccd48f896624",
) -> ResearchRequest:
    immutable = data_mode == "immutable_data"
    return ResearchRequest(
        run_id="cn-g07-fixture-run",
        research_question="Does the injected PIT feature retain value after costs?",
        economic_hypothesis="Positive lagged feature forecasts positive active return.",
        data_source=data_source,
        data_version="fixture-v1",
        data_mode=data_mode,
        data_handoff_event_id=(
            "integrated-cn-dataready-fixture" if immutable else ""
        ),
        data_handoff_validated=(
            immutable if data_handoff_validated is None else data_handoff_validated
        ),
        data_manifest_hash="d" * 64 if immutable else "",
        market_rule_handoff_event_id=(
            "integrated-cn-market-rule-fixture" if immutable else ""
        ),
        market_rule_handoff_validated=(
            immutable
            if market_rule_handoff_validated is None
            else market_rule_handoff_validated
        ),
        params=(("threshold", "0"),),
        validation_plan=validation_plan(),
        trial_registry=registry(),
        fold_results=(
            FoldResult(
                "fold-1",
                "a" * 64,
                0.03,
                0.08,
                0.5,
                0.4,
                True,
                True,
            ),
            FoldResult(
                "fold-2",
                "a" * 64,
                0.01,
                0.10,
                0.6,
                0.5,
                True,
                True,
            ),
        ),
        cost_scenarios=scenarios(),
        data_blockers=data_blockers,
        rule_blockers=rule_blockers,
        current_head="6ee6c4439f6bf6e8a8209ca6a919ccd48f896624",
        code_commit=code_commit,
        generated_at=datetime(2025, 5, 2, tzinfo=UTC),
        fixed_clock=datetime(2025, 5, 3, tzinfo=UTC),
        seed=17,
        initial_cash=Decimal("100000"),
    )


def run(**request_overrides: object):
    return run_research_pipeline(
        request=request(**request_overrides),
        strategy=FixtureStrategy(),
        forecast_model=FixtureForecastModel(),
        target_builder=FixtureTargetBuilder(),
        events=events(),
    )


def test_strategy_chain_is_linked_and_has_no_trading_capability() -> None:
    result = run()
    assert result.report.strategy_id == "cn-fixture-threshold"
    assert all(value is False for value in result.report.safety_flags.values())
    assert result.report.verdict == "research_only"


def test_snapshot_and_event_fail_closed_on_lookahead() -> None:
    with pytest.raises(ValueError, match="snapshot_not_visible_at_decision"):
        DecisionSnapshot(
            "future",
            "CN:600000",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            "fixture-v1",
            Decimal("1"),
            Decimal("10"),
        )
    baseline = event(1, feature="1", price="10")
    with pytest.raises(ValueError, match="event_visibility_execution_order_invalid"):
        replace(baseline, execution_time=baseline.decision_time)


def test_trial_registry_freezes_after_holdout_is_viewed() -> None:
    trials = registry()
    with pytest.raises(ValueError, match="holdout_already_viewed_parameter_search_frozen"):
        trials.register(
            Trial(
                "post-holdout",
                "c" * 64,
                datetime(2025, 5, 1, tzinfo=UTC),
                "accepted",
            )
        )


def test_purge_and_embargo_are_enforced() -> None:
    good = validation_plan()
    assert good.blockers(registry()) == ()
    bad_fold = replace(
        good.folds[0],
        validation_start=good.folds[0].train_end,
    )
    bad = replace(good, folds=(bad_fold,))
    assert "fold-1:train_validation_purge_insufficient" in bad.blockers(registry())


def test_three_ordered_cost_scenarios_are_mandatory() -> None:
    assert validate_cost_ladder(scenarios()) == ()
    assert validate_cost_ladder(scenarios()[:2]) == ("three_cost_scenarios_required",)
    bad = (
        scenarios()[0],
        replace(scenarios()[1], commission_rate=Decimal("0.0001")),
        scenarios()[2],
    )
    assert "cost_component_order_invalid:commission_rate" in validate_cost_ladder(bad)


def test_complete_fixture_evidence_is_research_only_and_ledger_derived() -> None:
    result = run()
    report = result.report
    assert report.verdict == "research_only"
    assert report.promotion_decision == "not_eligible"
    assert report.no_lookahead_status == "pass"
    assert report.pit_status == "fixture_explicit"
    assert report.holdout_status == "frozen_and_evaluated"
    assert report.ledger_reconciliation == "reconciled"
    assert report.replay_binding == "bound"
    assert {item.scenario for item in report.cost_stress_summary} == {
        "base",
        "conservative",
        "stress",
    }
    assert all(item.ledger_reconciled for item in report.cost_stress_summary)
    assert all(len(item.ledger_hash) == 64 for item in report.cost_stress_summary)
    assert all(len(item.replay_hash) == 64 for item in report.cost_stress_summary)
    assert all(item.metrics.number_of_bets == 2 for item in report.cost_stress_summary)
    assert all(item.metrics.annual_attribution for item in report.cost_stress_summary)
    assert report.fingerprint == result.report.fingerprint
    assert all(not item.blockers for item in result.shared_evidence)
    assert len(report.walk_forward_summary) == 2
    assert len(report.trial_registry_summary) == 2


def test_cost_stress_increases_explicit_costs() -> None:
    report = run().report
    by_name = {item.scenario: item.metrics for item in report.cost_stress_summary}
    assert by_name["base"].fee_paid < by_name["conservative"].fee_paid < by_name["stress"].fee_paid
    assert by_name["base"].slippage_paid < by_name["stress"].slippage_paid
    assert by_name["base"].market_impact_paid < by_name["stress"].market_impact_paid


def test_current_missing_data_and_rules_force_blocked_verdict() -> None:
    report = run(
        data_blockers=(
            "cn_dataready_current_main_manifest_missing",
            "domain_read_model_missing",
        ),
        rule_blockers=(
            "board_lot_rule_missing",
            "fee_schedule_rule_missing",
        ),
    ).report
    assert report.verdict == "blocked"
    assert report.pit_status == "blocked"
    assert "board_lot_rule_missing" in report.blockers
    assert "domain_read_model_missing" in report.blockers
    assert all(value is False for value in report.safety_flags.values())


def test_immutable_mode_can_only_reach_backtest_validated_not_promotion() -> None:
    report = run(
        data_mode="immutable_data",
        data_source="immutable:validated-cn-data-v1",
    ).report
    assert report.verdict == "backtest_validated"
    assert report.promotion_decision == "not_eligible"
    assert report.pit_status == "pass"


def test_immutable_mode_without_validated_handoffs_is_blocked() -> None:
    report = run(
        data_mode="immutable_data",
        data_source="immutable:unvalidated-cn-data-v1",
        data_handoff_validated=False,
        market_rule_handoff_validated=False,
    ).report
    assert report.verdict == "blocked"
    assert "data_handoff_not_validated" in report.blockers
    assert "market_rule_handoff_not_validated" in report.blockers


def test_stale_code_commit_blocks_current_head_evidence() -> None:
    result = run(code_commit="stale-commit")
    assert result.report.verdict == "blocked"
    assert "current_head_mismatch" in result.report.blockers
    assert all(
        "current_head_mismatch" in item.blockers for item in result.shared_evidence
    )


def test_fixture_cannot_be_relabelled_as_validated() -> None:
    report = run().report
    with pytest.raises(ValueError, match="fixture_cannot_be_backtest_validated"):
        replace(report, verdict="backtest_validated")


def test_event_data_version_mismatch_is_explicit_blocker() -> None:
    mixed = events()[:-1] + (event(4, feature="-1", price="10.40", data_version="fixture-v2"),)
    result = run_research_pipeline(
        request=request(),
        strategy=FixtureStrategy(),
        forecast_model=FixtureForecastModel(),
        target_builder=FixtureTargetBuilder(),
        events=mixed,
    )
    assert result.report.verdict == "blocked"
    assert "event_data_version_mismatch" in result.report.blockers


def test_report_contains_full_required_metric_set() -> None:
    payload = run().report.to_dict()
    metric = payload["cost_stress_summary"][0]["metrics"]
    assert {
        "total_return",
        "annualized_return",
        "annualized_volatility",
        "sharpe",
        "max_drawdown",
        "turnover",
        "average_holding_sessions",
        "exposure_ratio",
        "number_of_bets",
        "fee_paid",
        "slippage_paid",
        "market_impact_paid",
        "best_year_contribution_share",
        "worst_year",
        "capacity_proxy",
        "annual_attribution",
    } <= set(metric)


def test_failed_walk_forward_fold_cannot_be_averaged_away() -> None:
    base = request()
    failed = replace(base.fold_results[1], acceptable=False, positive=False)
    result = run_research_pipeline(
        request=replace(base, fold_results=(base.fold_results[0], failed)),
        strategy=FixtureStrategy(),
        forecast_model=FixtureForecastModel(),
        target_builder=FixtureTargetBuilder(),
        events=events(),
    )
    assert result.report.verdict == "blocked"
    assert "walk_forward_fold_failed" in result.report.blockers
