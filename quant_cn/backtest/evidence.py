"""Complete, serializable CN backtest evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.execution.models import SAFETY_FLAGS
from quant_cn.research.validation import FoldResult


@dataclass(frozen=True)
class AnnualAttribution:
    year: int
    pnl: Decimal
    return_fraction: Decimal
    contribution_share: Decimal


@dataclass(frozen=True)
class ScenarioMetrics:
    total_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    sharpe: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    average_holding_sessions: Decimal
    exposure_ratio: Decimal
    number_of_bets: int
    fee_paid: Decimal
    slippage_paid: Decimal
    market_impact_paid: Decimal
    best_year_contribution_share: Decimal
    worst_year: int | None
    capacity_proxy: Decimal
    annual_attribution: tuple[AnnualAttribution, ...]


@dataclass(frozen=True)
class ScenarioEvidence:
    scenario: str
    metrics: ScenarioMetrics
    ledger_hash: str
    replay_hash: str
    ledger_reconciled: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.scenario not in {"base", "conservative", "stress"}:
            raise ValueError("scenario_evidence_name_unknown")
        for name in ("ledger_hash", "replay_hash"):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name}_must_be_sha256")
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))


@dataclass(frozen=True)
class BacktestEvidenceReport:
    schema_version: str
    run_id: str
    strategy_id: str
    strategy_version: str
    research_question: str
    economic_hypothesis: str
    data_source: str
    data_version: str
    data_mode: str
    data_handoff_event_id: str
    data_manifest_hash: str
    market_rule_handoff_event_id: str
    start_time: datetime
    end_time: datetime
    decision_time_rule: str
    execution_time_rule: str
    feature_visibility_rule: str
    label_window: str
    cost_model: str
    slippage_model: str
    params: tuple[tuple[str, str], ...]
    params_hash: str
    candidate_count: int
    trial_count: int
    selected_by: str
    validation_plan_hash: str
    walk_forward_summary: tuple[FoldResult, ...]
    trial_registry_summary: tuple[tuple[str, str, str, bool], ...]
    regime_summary: tuple[tuple[str, str], ...]
    parameter_stability_summary: str
    cost_stress_summary: tuple[ScenarioEvidence, ...]
    ledger_reconciliation: str
    replay_binding: str
    no_lookahead_status: str
    pit_status: str
    holdout_status: str
    promotion_decision: str
    verdict: str
    blockers: tuple[str, ...]
    code_commit: str
    generated_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "schema_version",
            "run_id",
            "strategy_id",
            "strategy_version",
            "research_question",
            "economic_hypothesis",
            "data_source",
            "data_version",
            "decision_time_rule",
            "execution_time_rule",
            "feature_visibility_rule",
            "label_window",
            "cost_model",
            "slippage_model",
            "params_hash",
            "selected_by",
            "validation_plan_hash",
            "parameter_stability_summary",
            "ledger_reconciliation",
            "replay_binding",
            "no_lookahead_status",
            "pit_status",
            "holdout_status",
            "promotion_decision",
            "verdict",
            "code_commit",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.data_mode not in {"fixture", "immutable_data"}:
            raise ValueError("backtest_data_mode_unknown")
        for name in ("start_time", "end_time", "generated_at"):
            object.__setattr__(
                self, name, ensure_aware_timestamp(getattr(self, name), name)
            )
        if self.start_time > self.end_time:
            raise ValueError("backtest_evidence_window_invalid")
        if self.candidate_count <= 0 or self.trial_count <= 0:
            raise ValueError("candidate_and_trial_count_must_be_positive")
        if self.trial_count > self.candidate_count:
            raise ValueError("trial_count_exceeds_candidate_count")
        if len(self.params_hash) != 64 or len(self.validation_plan_hash) != 64:
            raise ValueError("evidence_hash_invalid")
        scenarios = tuple(sorted(self.cost_stress_summary, key=lambda item: item.scenario))
        if {item.scenario for item in scenarios} != {"base", "conservative", "stress"}:
            raise ValueError("complete_cost_stress_evidence_required")
        object.__setattr__(self, "cost_stress_summary", scenarios)
        blockers = tuple(sorted(set(self.blockers)))
        object.__setattr__(self, "blockers", blockers)
        if not self.walk_forward_summary:
            raise ValueError("walk_forward_summary_required")
        if not self.trial_registry_summary:
            raise ValueError("trial_registry_summary_required")
        if blockers and self.verdict != "blocked":
            raise ValueError("evidence_with_blockers_must_be_blocked")
        if self.data_mode == "fixture" and self.verdict not in {"research_only", "blocked"}:
            raise ValueError("fixture_cannot_be_backtest_validated")
        if self.promotion_decision != "not_eligible":
            raise ValueError("promotion_must_remain_not_eligible")

    @property
    def safety_flags(self) -> dict[str, bool]:
        return dict(SAFETY_FLAGS)

    def to_dict(self) -> dict[str, Any]:
        def metric_dict(metrics: ScenarioMetrics) -> dict[str, Any]:
            return {
                "annual_attribution": [
                    {
                        "contribution_share": str(item.contribution_share),
                        "pnl": str(item.pnl),
                        "return_fraction": str(item.return_fraction),
                        "year": item.year,
                    }
                    for item in metrics.annual_attribution
                ],
                **{
                    name: str(getattr(metrics, name))
                    for name in (
                        "annualized_return",
                        "annualized_volatility",
                        "average_holding_sessions",
                        "best_year_contribution_share",
                        "capacity_proxy",
                        "exposure_ratio",
                        "fee_paid",
                        "market_impact_paid",
                        "max_drawdown",
                        "sharpe",
                        "slippage_paid",
                        "total_return",
                        "turnover",
                    )
                },
                "number_of_bets": metrics.number_of_bets,
                "worst_year": metrics.worst_year,
            }

        return {
            "blockers": list(self.blockers),
            "candidate_count": self.candidate_count,
            "code_commit": self.code_commit,
            "cost_model": self.cost_model,
            "cost_stress_summary": [
                {
                    "blockers": list(item.blockers),
                    "ledger_hash": item.ledger_hash,
                    "ledger_reconciled": item.ledger_reconciled,
                    "metrics": metric_dict(item.metrics),
                    "replay_hash": item.replay_hash,
                    "scenario": item.scenario,
                }
                for item in self.cost_stress_summary
            ],
            "data_mode": self.data_mode,
            "data_handoff_event_id": self.data_handoff_event_id,
            "data_manifest_hash": self.data_manifest_hash,
            "market_rule_handoff_event_id": self.market_rule_handoff_event_id,
            "data_source": self.data_source,
            "data_version": self.data_version,
            "decision_time_rule": self.decision_time_rule,
            "economic_hypothesis": self.economic_hypothesis,
            "end_time": self.end_time.isoformat(),
            "execution_time_rule": self.execution_time_rule,
            "feature_visibility_rule": self.feature_visibility_rule,
            "generated_at": self.generated_at.isoformat(),
            "holdout_status": self.holdout_status,
            "label_window": self.label_window,
            "ledger_reconciliation": self.ledger_reconciliation,
            "no_lookahead_status": self.no_lookahead_status,
            "parameter_stability_summary": self.parameter_stability_summary,
            "params": dict(self.params),
            "params_hash": self.params_hash,
            "pit_status": self.pit_status,
            "promotion_decision": self.promotion_decision,
            "regime_summary": dict(self.regime_summary),
            "replay_binding": self.replay_binding,
            "research_question": self.research_question,
            "run_id": self.run_id,
            "safety_flags": self.safety_flags,
            "schema_version": self.schema_version,
            "selected_by": self.selected_by,
            "slippage_model": self.slippage_model,
            "start_time": self.start_time.isoformat(),
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "trial_count": self.trial_count,
            "trial_registry_summary": [
                {
                    "params_hash": params_hash,
                    "selected": selected,
                    "status": status,
                    "trial_id": trial_id,
                }
                for trial_id, params_hash, status, selected in self.trial_registry_summary
            ],
            "validation_plan_hash": self.validation_plan_hash,
            "verdict": self.verdict,
            "walk_forward_summary": [
                {
                    "acceptable": item.acceptable,
                    "exposure_ratio": item.exposure_ratio,
                    "fold_id": item.fold_id,
                    "max_drawdown": item.max_drawdown,
                    "params_hash": item.params_hash,
                    "positive": item.positive,
                    "total_return": item.total_return,
                    "turnover": item.turnover,
                }
                for item in self.walk_forward_summary
            ],
        }

    @property
    def fingerprint(self) -> str:
        return sha256(
            json.dumps(
                self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
