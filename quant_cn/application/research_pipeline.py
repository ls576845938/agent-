"""Build complete, fail-closed CN research/backtest evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json

from quant_cn.backtest.costs import CostScenario, validate_cost_ladder
from quant_cn.backtest.engine import EventDrivenBacktest
from quant_cn.backtest.events import BacktestEvent
from quant_cn.backtest.evidence import (
    BacktestEvidenceReport,
    ScenarioEvidence,
)
from quant_cn.compat.shared_adapter import build_backtest_evidence
from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.research.validation import FoldResult, TrialRegistry, ValidationPlan
from quant_cn.strategy.contracts import ForecastModel, Strategy, TargetBuilder


@dataclass(frozen=True)
class ResearchRequest:
    run_id: str
    research_question: str
    economic_hypothesis: str
    data_source: str
    data_version: str
    data_mode: str
    data_handoff_event_id: str
    data_handoff_validated: bool
    data_manifest_hash: str
    market_rule_handoff_event_id: str
    market_rule_handoff_validated: bool
    params: tuple[tuple[str, str], ...]
    validation_plan: ValidationPlan
    trial_registry: TrialRegistry
    fold_results: tuple[FoldResult, ...]
    cost_scenarios: tuple[CostScenario, ...]
    data_blockers: tuple[str, ...]
    rule_blockers: tuple[str, ...]
    current_head: str
    code_commit: str
    generated_at: datetime
    fixed_clock: datetime
    seed: int
    initial_cash: Decimal

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "research_question",
            "economic_hypothesis",
            "data_source",
            "data_version",
            "current_head",
            "code_commit",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.data_mode not in {"fixture", "immutable_data"}:
            raise ValueError("research_data_mode_unknown")
        if self.data_mode == "fixture" and not self.data_source.startswith("fixture:"):
            raise ValueError("fixture_source_prefix_required")
        if self.data_mode == "immutable_data" and not self.data_source.startswith("immutable:"):
            raise ValueError("immutable_source_prefix_required")
        if not isinstance(self.data_handoff_validated, bool):
            raise TypeError("data_handoff_validated_must_be_bool")
        if not isinstance(self.market_rule_handoff_validated, bool):
            raise TypeError("market_rule_handoff_validated_must_be_bool")
        object.__setattr__(
            self, "generated_at", ensure_aware_timestamp(self.generated_at, "generated_at")
        )
        object.__setattr__(
            self, "fixed_clock", ensure_aware_timestamp(self.fixed_clock, "fixed_clock")
        )
        object.__setattr__(self, "params", tuple(sorted(self.params)))
        object.__setattr__(self, "data_blockers", tuple(sorted(set(self.data_blockers))))
        object.__setattr__(self, "rule_blockers", tuple(sorted(set(self.rule_blockers))))
        object.__setattr__(
            self, "fold_results", tuple(sorted(self.fold_results, key=lambda item: item.fold_id))
        )
        if (
            not isinstance(self.initial_cash, Decimal)
            or not self.initial_cash.is_finite()
            or self.initial_cash <= 0
        ):
            raise ValueError("positive_initial_cash_required")


@dataclass(frozen=True)
class ResearchPipelineResult:
    report: BacktestEvidenceReport
    shared_evidence: tuple[object, ...]


def run_research_pipeline(
    *,
    request: ResearchRequest,
    strategy: Strategy,
    forecast_model: ForecastModel,
    target_builder: TargetBuilder,
    events: tuple[BacktestEvent, ...],
) -> ResearchPipelineResult:
    blockers = [
        *request.data_blockers,
        *request.rule_blockers,
        *request.validation_plan.blockers(request.trial_registry),
        *request.validation_plan.result_blockers(
            request.fold_results,
            request.trial_registry,
        ),
        *validate_cost_ladder(request.cost_scenarios),
    ]
    if request.trial_registry.holdout_viewed_at is None:
        blockers.append("holdout_not_evaluated")
    if request.code_commit != request.current_head:
        blockers.append("current_head_mismatch")
    if request.data_mode == "immutable_data":
        if not request.data_handoff_validated or not request.data_handoff_event_id.strip():
            blockers.append("data_handoff_not_validated")
        if len(request.data_manifest_hash) != 64:
            blockers.append("data_manifest_hash_missing")
        if (
            not request.market_rule_handoff_validated
            or not request.market_rule_handoff_event_id.strip()
        ):
            blockers.append("market_rule_handoff_not_validated")
    if not events:
        raise ValueError("research_events_required")
    if any(item.data_version != request.data_version for item in events):
        blockers.append("event_data_version_mismatch")

    engine = EventDrivenBacktest(
        strategy=strategy,
        forecast_model=forecast_model,
        target_builder=target_builder,
    )
    scenario_evidence: list[ScenarioEvidence] = []
    shared_evidence: list[object] = []
    for index, scenario in enumerate(
        sorted(request.cost_scenarios, key=lambda item: item.friction_score)
    ):
        result = engine.run(
            run_id=request.run_id,
            events=events,
            initial_cash=request.initial_cash,
            scenario=scenario,
            fixed_clock=request.fixed_clock,
            seed=request.seed + index,
        )
        blockers.extend(result.blockers)
        evidence = ScenarioEvidence(
            scenario=scenario.name,
            metrics=result.metrics,
            ledger_hash=result.ledger_hash,
            replay_hash=result.replay_hash,
            ledger_reconciled=not result.reconciliation.blocks_gate,
            blockers=result.blockers,
        )
        scenario_evidence.append(evidence)
        shared_evidence.append(
            build_backtest_evidence(
                cost_model=f"cn_effective_dated_{scenario.name}:{scenario.version}",
                slippage_model=(
                    f"explicit_bps:slippage={scenario.slippage_bps}:"
                    f"impact={scenario.market_impact_bps}"
                ),
                decision_time_rule="available_time<=decision_time<order_created_time",
                execution_time_rule="order_created_time<=execution_time",
                candidate_count=request.trial_registry.candidate_count,
                trial_count=request.trial_registry.trial_count,
                walk_forward_valid=not request.validation_plan.blockers(
                    request.trial_registry
                ),
                no_lookahead_valid=all(
                    item.available_time <= item.decision_time < item.execution_time
                    for item in events
                ),
                ledger_reconciled=not result.reconciliation.blocks_gate,
                ledger_hash=result.ledger_hash,
                replay_hash=result.replay_hash,
                current_head_match=request.code_commit == request.current_head,
                blockers=result.blockers,
            )
        )
    scenario_evidence_tuple = tuple(scenario_evidence)
    if any(item.blockers for item in scenario_evidence_tuple):
        blockers.append("scenario_execution_blocked")
    if any(not item.ledger_reconciled for item in scenario_evidence_tuple):
        blockers.append("ledger_reconciliation_failed")

    canonical = tuple(sorted(set(blockers)))
    verdict = (
        "blocked"
        if canonical
        else "research_only"
        if request.data_mode == "fixture"
        else "backtest_validated"
    )
    params_hash = sha256(
        json.dumps(dict(request.params), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    report = BacktestEvidenceReport(
        schema_version="cn_backtest_evidence_v1",
        run_id=request.run_id,
        strategy_id=strategy.strategy_id,
        strategy_version=strategy.strategy_version,
        research_question=request.research_question,
        economic_hypothesis=request.economic_hypothesis,
        data_source=request.data_source,
        data_version=request.data_version,
        data_mode=request.data_mode,
        data_handoff_event_id=request.data_handoff_event_id,
        data_manifest_hash=request.data_manifest_hash,
        market_rule_handoff_event_id=request.market_rule_handoff_event_id,
        start_time=min(item.event_time for item in events),
        end_time=max(item.execution_time for item in events),
        decision_time_rule="available_time<=decision_time<order_created_time",
        execution_time_rule="order_created_time<=execution_time; no same-close shortcut",
        feature_visibility_rule="feature snapshot available_time<=decision_time",
        label_window=str(request.validation_plan.label_horizon),
        cost_model="effective-dated commission/tax with three ordered scenarios",
        slippage_model="explicit slippage and market-impact bps",
        params=request.params,
        params_hash=params_hash,
        candidate_count=request.trial_registry.candidate_count,
        trial_count=request.trial_registry.trial_count,
        selected_by="trial_registry_before_holdout",
        validation_plan_hash=request.validation_plan.fingerprint,
        walk_forward_summary=request.fold_results,
        trial_registry_summary=tuple(
            (item.trial_id, item.params_hash, item.status, item.selected)
            for item in request.trial_registry.trials
        ),
        regime_summary=tuple(
            (
                item.scenario,
                ",".join(str(year.year) for year in item.metrics.annual_attribution)
                or "no_year",
            )
            for item in scenario_evidence_tuple
        ),
        parameter_stability_summary=(
            "passed"
            if request.validation_plan.parameter_stability_passed
            else "blocked"
        ),
        cost_stress_summary=scenario_evidence_tuple,
        ledger_reconciliation=(
            "reconciled"
            if all(item.ledger_reconciled for item in scenario_evidence_tuple)
            else "blocked"
        ),
        replay_binding=(
            "bound"
            if all(len(item.replay_hash) == 64 for item in scenario_evidence_tuple)
            else "blocked"
        ),
        no_lookahead_status=(
            "pass"
            if all(item.available_time <= item.decision_time < item.execution_time for item in events)
            else "blocked"
        ),
        pit_status=(
            "fixture_explicit"
            if request.data_mode == "fixture" and not request.data_blockers
            else "pass"
            if request.data_mode == "immutable_data" and not request.data_blockers
            else "blocked"
        ),
        holdout_status=(
            "frozen_and_evaluated"
            if request.validation_plan.selected_before_holdout
            and request.trial_registry.holdout_viewed_at is not None
            else "blocked"
        ),
        promotion_decision="not_eligible",
        verdict=verdict,
        blockers=canonical,
        code_commit=request.code_commit,
        generated_at=request.generated_at,
    )
    return ResearchPipelineResult(report=report, shared_evidence=tuple(shared_evidence))
