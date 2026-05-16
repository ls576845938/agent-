"""Research promotion gate for evaluating candidate readiness.

Determines whether a strategy candidate is ready to proceed to
human paper-review evaluation. This is the final automated research
arbiter before paper review; it NEVER triggers paper trading or live
trading.

Decision outcomes:
- BLOCKED: Missing required evidence or fatal risk.
- WATCHLIST: Some checks passed but needs more data or analysis.
- NEED_MORE_RESEARCH: Additional research required before promotion
  (e.g., high correlation redundancy).
- READY_FOR_PAPER_REVIEW: All checks pass. Candidate enters
  the human review pool for paper trading consideration.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from quant_us.data.storage.data_manifest import (
    DataManifest,
    DataManifestStore,
    validate_manifest_for_promotion,
)
from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash
from quant_us.research.evidence_contracts import summarize_strategy_manifest_contract
from quant_us.research.validation import summarize_candidate_validation


ALLOWED_DATA_SOURCES = {"yfinance", "alpaca", "sqlite"}
ALLOWED_ASSET_CLASSES = {"equity", "crypto"}
CRYPTO_SYMBOL_SUFFIXES = ("USDT", "USD", "BTC", "ETH")
DATA_MANIFEST_ADVISORY_WARNINGS = {
    "universe_id_missing",
    "universe_source_missing",
    "survivorship_bias_risk_unmarked",
}


@dataclass
class PromotionGateResult:
    """Result of a promotion gate evaluation.

    Attributes:
        candidate_id: The evaluated candidate.
        decision: BLOCKED | WATCHLIST | NEED_MORE_RESEARCH | READY_FOR_PAPER_REVIEW.
        reasons: Blocking reasons (fatal issues).
        warnings: Non-blocking concerns.
        needs_more_research: Items requiring additional research before promotion.
        evidence: Dict of evidence collected during evaluation, e.g.
            {"manifest_exists": True, "scorecard_exists": True, ...}.
    """

    candidate_id: str
    decision: str = "BLOCKED"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_more_research: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


class ResearchPromotionGate:
    """Evaluate candidates for promotion from research to paper review.

    The gate checks REQUIRED evidence:
    - ExperimentManifest exists
    - RobustScorecard exists
    - Canonical backtest manifest evidence exists
    - OverfitDetector report (no overfit)
    - WalkForward result (must be run)
    - Trade count > 10
    - Cost stress passed
    - Max drawdown < 50%
    - Monte Carlo survival rate > 80%  (R6)
    - Alpha decay half-life > 5 days   (R6)
    - Param stability score > 0.5      (R6)
    - Correlation redundancy < 0.70    (R7)
    - Stress survival rate > 70%       (R8)

    READY_FOR_PAPER_REVIEW means the candidate is ready for HUMAN REVIEW
    only. It does NOT enter paper trading automatically.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def evaluate(self, candidate_id: str) -> PromotionGateResult:
        """Evaluate a candidate for promotion readiness."""
        reasons: list[str] = []
        warnings: list[str] = []
        evidence: dict[str, Any] = {}
        needs_more_research: list[str] = []

        candidate_data = self._load_candidate(candidate_id)
        manifest_exists = candidate_data is not None
        evidence["manifest_exists"] = manifest_exists
        if not manifest_exists:
            reasons.append("missing_manifest: candidate file not found")
            return PromotionGateResult(
                candidate_id=candidate_id,
                decision="BLOCKED",
                reasons=reasons,
                warnings=warnings,
                needs_more_research=needs_more_research,
                evidence=evidence,
            )

        metrics = candidate_data.get("metrics", {}) or {}
        stored_status = str(candidate_data.get("promotion_status", "RESEARCH_ONLY"))
        evidence["stored_promotion_status"] = stored_status

        experiment_id = candidate_data.get("experiment_id", "")
        experiment_path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "manifest.json"
        )
        manifest_ok = experiment_path.exists()
        evidence["experiment_manifest_exists"] = manifest_ok
        experiment_data: dict[str, Any] = {}
        if not manifest_ok:
            reasons.append("missing_manifest: experiment manifest not found")
        else:
            experiment_data = json.loads(experiment_path.read_text(encoding="utf-8"))

        backtest_manifest = self._load_backtest_manifest(
            candidate_id=candidate_id,
            candidate_data=candidate_data,
            metrics=metrics,
            evidence=evidence,
            reasons=reasons,
        )
        self._evaluate_data_scope(
            candidate_data=candidate_data,
            experiment_data=experiment_data,
            backtest_manifest=backtest_manifest,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
        )

        scorecard_path = (
            self.data_root
            / "research"
            / "scorecards"
            / f"{candidate_id}.json"
        )
        scorecard_exists = scorecard_path.exists()
        evidence["scorecard_exists"] = scorecard_exists
        evidence["scorecard_path"] = str(scorecard_path)
        if not scorecard_exists:
            reasons.append("missing_scorecard: robust scorecard not found")

        self._evaluate_strategy_manifest(
            candidate_id=candidate_id,
            evidence=evidence,
            reasons=reasons,
        )

        walk_forward_artifact = self._load_canonical_research_artifact(
            candidate_id=candidate_id,
            artifact_name="walk_forward",
            candidate_data=candidate_data,
            metrics=metrics,
            evidence=evidence,
            reasons=reasons,
        )
        cost_stress_artifact = self._load_canonical_research_artifact(
            candidate_id=candidate_id,
            artifact_name="cost_stress",
            candidate_data=candidate_data,
            metrics=metrics,
            evidence=evidence,
            reasons=reasons,
        )

        from quant_us.research.automation.overfit import OverfitDetector

        detector = OverfitDetector(data_root=str(self.data_root))
        try:
            report = detector.check(candidate_id)
            evidence["overfit_report"] = {
                "is_overfit": report.is_overfit,
                "degradation_pct": report.degradation_pct,
                "reason_count": len(report.reasons),
                "lookahead_risk": bool(getattr(report, "lookahead_risk", False)),
                "lookahead_description": str(getattr(report, "lookahead_description", "")),
            }
            if report.is_overfit:
                reasons.append("overfit_risk_high: " + "; ".join(report.reasons))
        except ValueError:
            evidence["overfit_report"] = {"error": "candidate_not_found"}
            reasons.append("missing_data: cannot run overfit check")

        self._evaluate_event_ledger_evidence(
            metrics=metrics,
            backtest_manifest=backtest_manifest,
            evidence=evidence,
            reasons=reasons,
        )
        self._record_unified_backtest_report_evidence(
            backtest_manifest=backtest_manifest,
            evidence=evidence,
            reasons=reasons,
        )
        self._evaluate_validation_statistics(
            candidate_id=candidate_id,
            metrics=metrics,
            experiment_data=experiment_data,
            walk_forward_artifact=walk_forward_artifact,
            cost_stress_artifact=cost_stress_artifact,
            evidence=evidence,
            reasons=reasons,
            warnings=warnings,
        )

        wf_pass_rate = self._artifact_metric(
            walk_forward_artifact,
            metric_names=("walk_forward_pass_rate", "pass_rate"),
            nested=("stability", "pass_rate_pct"),
            default=metrics.get("walk_forward_pass_rate", -1.0),
        )
        wf_run = wf_pass_rate >= 0.0
        evidence["walk_forward_run"] = wf_run
        evidence["walk_forward_pass_rate"] = wf_pass_rate
        if not wf_run:
            reasons.append(
                "missing_walk_forward_result: persisted canonical walk-forward artifact must include a pass rate"
            )

        trade_count = int(metrics.get("trade_count", 0))
        evidence["trade_count"] = trade_count
        if trade_count <= 0:
            reasons.append("trade_count_zero: paper-review candidates must have at least one completed trade")
        if trade_count <= 10:
            warnings.append(
                f"trade_count_too_low: only {trade_count} trades "
                f"(need > 10 for statistical significance)"
            )

        cost_sensitivity = self._artifact_metric(
            cost_stress_artifact,
            metric_names=("cost_sensitivity",),
            nested=(),
            default=metrics.get("cost_sensitivity", 0.0),
        )
        evidence["cost_sensitivity"] = cost_sensitivity
        if cost_sensitivity > 0.5:
            reasons.append(
                f"cost_impact_too_high: cost_sensitivity={cost_sensitivity:.3f} "
                "(> 0.5 threshold)"
            )

        max_dd = abs(float(metrics.get("max_drawdown_pct", 0.0)))
        evidence["max_drawdown"] = max_dd
        if max_dd >= 0.50:
            reasons.append(
                f"max_drawdown_too_high: {max_dd:.1%} "
                "(>= 50% threshold)"
            )

        monte_carlo_present, monte_carlo_survival = self._metric_value(
            metrics, "monte_carlo_survival_rate"
        )
        evidence["monte_carlo_survival_rate"] = monte_carlo_survival
        evidence["monte_carlo_survival_rate_present"] = monte_carlo_present
        if not monte_carlo_present:
            reasons.append(
                "missing_monte_carlo_survival_rate: promotion requires Monte Carlo survival evidence"
            )
        elif monte_carlo_survival <= 0.80:
            reasons.append(
                f"monte_carlo_survival_low: survival_rate={monte_carlo_survival:.3f} "
                "(<= 0.80 threshold)"
            )

        alpha_decay_half_life = float(metrics.get("alpha_decay_half_life_days", 0.0))
        alpha_decay_present, alpha_decay_half_life = self._metric_value(
            metrics, "alpha_decay_half_life_days"
        )
        evidence["alpha_decay_half_life_days"] = alpha_decay_half_life
        evidence["alpha_decay_half_life_days_present"] = alpha_decay_present
        if not alpha_decay_present:
            warnings.append(
                "missing_alpha_decay_half_life_days: promotion evidence is missing alpha decay half-life metadata"
            )
        elif alpha_decay_half_life <= 5.0:
            warnings.append(
                f"rapid_alpha_decay: half_life={alpha_decay_half_life:.1f} days "
                "(<= 5 days threshold)"
            )

        param_stability_present, param_stability = self._metric_value(
            metrics, "param_stability_score"
        )
        evidence["param_stability_score"] = param_stability
        evidence["param_stability_score_present"] = param_stability_present
        if not param_stability_present:
            reasons.append(
                "missing_param_stability_score: promotion requires parameter stability evidence"
            )
        elif param_stability <= 0.5:
            reasons.append(
                f"param_unstable: stability_score={param_stability:.3f} "
                "(<= 0.5 threshold)"
            )

        correlation_redundancy = float(metrics.get("correlation_redundancy", 0.0))
        evidence["correlation_redundancy"] = correlation_redundancy
        if correlation_redundancy >= 0.70:
            needs_more_research.append(
                f"high_redundancy: correlation_redundancy={correlation_redundancy:.3f} "
                "(>= 0.70 threshold)"
            )

        stress_survival_present, stress_survival_rate = self._artifact_metric_value(
            cost_stress_artifact,
            metric_names=("stress_survival_rate", "survival_rate"),
            nested=("stability", "survival_rate_pct"),
        )
        if not stress_survival_present:
            stress_survival_present, stress_survival_rate = self._metric_value(
                metrics, "stress_survival_rate"
            )
        if stress_survival_rate > 1.0:
            stress_survival_rate = stress_survival_rate / 100.0
        evidence["stress_survival_rate"] = stress_survival_rate
        evidence["stress_survival_rate_present"] = stress_survival_present
        if not stress_survival_present:
            reasons.append(
                "missing_stress_survival_rate: promotion requires persisted cost-stress survival evidence"
            )
        elif stress_survival_rate <= 0.70:
            reasons.append(
                f"stress_survival_low: survival_rate={stress_survival_rate:.3f} "
                "(<= 0.70 threshold)"
            )

        if stored_status == "PAPER_ELIGIBLE" and (
            reasons or warnings or needs_more_research
        ):
            reasons.append(
                "promotion_status_inconsistent: stored PAPER_ELIGIBLE but "
                "current gate evidence is not clean"
            )

        evidence["machine_readable_blockers"] = list(reasons)
        evidence["machine_readable_blocker_details"] = self._build_blocker_details(
            candidate_id=candidate_id,
            candidate_data=candidate_data,
            experiment_data=experiment_data,
            evidence=evidence,
            reasons=reasons,
        )
        evidence["machine_readable_warnings"] = list(warnings)
        evidence["machine_readable_needs_more_research"] = list(needs_more_research)
        evidence["next_commands"] = self._build_next_commands(
            candidate_id=candidate_id,
            candidate_data=candidate_data,
            experiment_data=experiment_data,
            blocker_details=evidence["machine_readable_blocker_details"],
            reasons=reasons,
            warnings=warnings,
        )

        if reasons:
            decision = "BLOCKED"
        elif needs_more_research:
            decision = "NEED_MORE_RESEARCH"
        elif warnings:
            decision = "WATCHLIST"
        else:
            decision = "READY_FOR_PAPER_REVIEW"

        if decision == "READY_FOR_PAPER_REVIEW":
            persisted_path = self._persist_promotion_result(
                candidate_id=candidate_id,
                decision=decision,
                reasons=reasons,
                warnings=warnings,
                needs_more_research=needs_more_research,
                evidence=evidence,
            )
            if persisted_path:
                evidence["promotion_result_exists"] = True
                evidence["promotion_result_path"] = str(persisted_path)
                evidence["promotion_result_sha256"] = self._file_sha256(persisted_path)
            else:
                evidence["promotion_result_exists"] = False
                reasons.append(
                    "missing_persisted_promotion_result: READY_FOR_PAPER_REVIEW requires persisted gate evidence"
                )
                decision = "BLOCKED"
        else:
            evidence["promotion_result_exists"] = False

        return PromotionGateResult(
            candidate_id=candidate_id,
            decision=decision,
            reasons=reasons,
            warnings=warnings,
            needs_more_research=needs_more_research,
            evidence=evidence,
        )

    def _load_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        path = (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _evaluate_strategy_manifest(
        self,
        *,
        candidate_id: str,
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> None:
        manifests_dir = self.data_root / "research" / "manifests"
        matches: list[tuple[Path, dict[str, Any]]] = []
        if manifests_dir.exists():
            for manifest_path in sorted(manifests_dir.glob("*/manifest.json")):
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if payload.get("source_candidate_id") == candidate_id:
                    matches.append((manifest_path, payload))

        evidence["strategy_manifest_exists"] = bool(matches)
        evidence["strategy_manifest_count"] = len(matches)
        evidence["strategy_manifest_paths"] = [str(path) for path, _ in matches]
        if not matches:
            reasons.append(
                "missing_strategy_manifest: canonical strategy manifest not found for candidate"
            )
            return
        if len(matches) > 1:
            reasons.append(
                "strategy_manifest_conflict: multiple strategy manifests reference candidate"
            )
            return

        manifest_path, payload = matches[0]
        evidence["strategy_manifest_path"] = str(manifest_path)
        evidence["strategy_manifest_id"] = str(
            payload.get("strategy_candidate_id", manifest_path.parent.name)
        )
        evidence["strategy_manifest_status"] = str(payload.get("promotion_status", ""))
        contract_summary = summarize_strategy_manifest_contract(payload)
        evidence["strategy_manifest_contract"] = contract_summary
        evidence["strategy_manifest_contract_complete"] = bool(
            contract_summary.get("contract_complete", False)
        )
        if not contract_summary.get("contract_documented", False):
            undocumented_missing_fields = list(
                contract_summary.get("undocumented_missing_fields", [])
            )
            reasons.append(
                "strategy_manifest_contract_missing_reasons:"
                f"{evidence['strategy_manifest_id']}:{','.join(undocumented_missing_fields)}"
            )
        if not contract_summary.get("contract_complete", False):
            missing_fields = list(contract_summary.get("missing_fields", []))
            reasons.append(
                "strategy_manifest_contract_incomplete:"
                f"{evidence['strategy_manifest_id']}:{','.join(missing_fields)}"
            )

    def _load_canonical_research_artifact(
        self,
        *,
        candidate_id: str,
        artifact_name: str,
        candidate_data: dict[str, Any],
        metrics: dict[str, Any],
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any] | None:
        canonical_path = self._canonical_research_artifact_path(
            candidate_id, artifact_name
        )
        canonical_path_text = str(canonical_path.relative_to(self.data_root))
        path_key = f"{artifact_name}_result_path"
        raw_path = candidate_data.get(path_key) or metrics.get(path_key) or ""
        inline_artifact = (
            candidate_data.get(artifact_name)
            or candidate_data.get(f"{artifact_name}_result")
            or metrics.get(artifact_name)
            or metrics.get(f"{artifact_name}_result")
        )

        evidence[f"{artifact_name}_artifact_expected_path"] = canonical_path_text
        evidence[f"{artifact_name}_artifact_path"] = str(raw_path or "")
        evidence[f"{artifact_name}_artifact_inline"] = isinstance(inline_artifact, dict)
        evidence[f"{artifact_name}_artifact_exists"] = False

        if not raw_path:
            if isinstance(inline_artifact, dict):
                reasons.append(
                    f"inline_{artifact_name}_artifact_not_allowed: promotion requires persisted canonical {artifact_name} evidence"
                )
            reasons.append(
                f"missing_{artifact_name}_artifact: READY_FOR_PAPER_REVIEW requires persisted canonical {artifact_name} evidence at {canonical_path_text}"
            )
            return None

        artifact_path = self._resolve_research_artifact_path(raw_path)
        evidence[f"{artifact_name}_artifact_resolved_path"] = str(artifact_path)
        if not self._same_path(artifact_path, canonical_path):
            reasons.append(
                f"non_canonical_{artifact_name}_artifact_path: promotion only accepts {canonical_path_text}"
            )
            return None
        if not artifact_path.exists():
            reasons.append(
                f"{artifact_name}_artifact_path_missing: artifact not found at {artifact_path}"
            )
            return None

        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reasons.append(f"{artifact_name}_artifact_unreadable: {artifact_path}: {exc}")
            return None
        if not isinstance(artifact, dict):
            reasons.append(f"{artifact_name}_artifact_invalid: expected JSON object")
            return None

        evidence[f"{artifact_name}_artifact_exists"] = True
        evidence[f"{artifact_name}_artifact_sha256"] = self._file_sha256(artifact_path)
        status = str(artifact.get("status", "completed") or "completed").lower()
        evidence[f"{artifact_name}_artifact_status"] = status
        if status not in {"completed", "pass", "passed", "ok"}:
            reasons.append(
                f"{artifact_name}_artifact_not_completed: status={status or 'unknown'}"
            )
        return artifact

    def _canonical_research_artifact_path(
        self,
        candidate_id: str,
        artifact_name: str,
    ) -> Path:
        return (
            self.data_root
            / "research"
            / artifact_name
            / candidate_id
            / "result.json"
        )

    def _resolve_research_artifact_path(self, raw_path: Any) -> Path:
        candidate = Path(str(raw_path))
        if candidate.exists() or candidate.is_absolute():
            return candidate
        data_relative = self.data_root / candidate
        if data_relative.exists():
            return data_relative
        if candidate.parts and self.data_root.name and candidate.parts[0] == self.data_root.name:
            return candidate
        return data_relative

    def _persist_promotion_result(
        self,
        *,
        candidate_id: str,
        decision: str,
        reasons: list[str],
        warnings: list[str],
        needs_more_research: list[str],
        evidence: dict[str, Any],
    ) -> Path | None:
        path = (
            self.data_root
            / "research"
            / "pipeline_results"
            / f"promotion_gate_{candidate_id}.json"
        )
        payload = {
            "pipeline_id": f"promotion_gate_{candidate_id}",
            "created_at": self._now_iso(),
            "status": "completed",
            "paper_review_ready": [candidate_id],
            "promotion_gate_results": {
                candidate_id: {
                    "decision": decision,
                    "reasons": list(reasons),
                    "warnings": list(warnings),
                    "needs_more_research": list(needs_more_research),
                    "evidence": dict(evidence),
                }
            },
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, indent=2, default=str, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            return None
        return path

    @staticmethod
    def _artifact_metric(
        artifact: dict[str, Any] | None,
        *,
        metric_names: tuple[str, ...],
        nested: tuple[str, ...],
        default: Any,
    ) -> float:
        present, value = ResearchPromotionGate._artifact_metric_value(
            artifact,
            metric_names=metric_names,
            nested=nested,
        )
        if not present:
            value = default
        return float(value)

    @staticmethod
    def _artifact_metric_value(
        artifact: dict[str, Any] | None,
        *,
        metric_names: tuple[str, ...],
        nested: tuple[str, ...],
    ) -> tuple[bool, float]:
        if isinstance(artifact, dict):
            metrics = artifact.get("metrics", {})
            if not isinstance(metrics, dict):
                metrics = {}
            for name in metric_names:
                value = artifact.get(name)
                if value not in (None, ""):
                    return True, float(value)
                value = metrics.get(name)
                if value not in (None, ""):
                    return True, float(value)
            if nested:
                container = artifact.get(nested[0], {})
                if isinstance(container, dict):
                    value = container.get(nested[1])
                    if value not in (None, ""):
                        return True, float(value)
        return False, 0.0

    @staticmethod
    def _metric_value(metrics: dict[str, Any], key: str) -> tuple[bool, float]:
        value = metrics.get(key)
        if value in (None, ""):
            return False, 0.0
        return True, float(value)

    def _evaluate_validation_statistics(
        self,
        *,
        candidate_id: str,
        metrics: dict[str, Any],
        experiment_data: dict[str, Any],
        walk_forward_artifact: dict[str, Any] | None,
        cost_stress_artifact: dict[str, Any] | None,
        evidence: dict[str, Any],
        reasons: list[str],
        warnings: list[str],
    ) -> None:
        summary = summarize_candidate_validation(
            candidate_id=candidate_id,
            metrics=metrics,
            walk_forward_artifact=walk_forward_artifact,
            cost_stress_artifact=cost_stress_artifact,
            experiment_data=experiment_data,
        )
        evidence["validation_stats"] = summary
        evidence["validation_status"] = str(summary.get("status", "partial"))

        cv_summary = summary.get("cv_summary", {})
        if not isinstance(cv_summary, dict):
            cv_summary = {}
        trial_counting = summary.get("trial_counting", {})
        if not isinstance(trial_counting, dict):
            trial_counting = {}
        dsr_summary = summary.get("deflated_sharpe_ratio", {})
        if not isinstance(dsr_summary, dict):
            dsr_summary = {}
        pbo_summary = summary.get("pbo", {})
        if not isinstance(pbo_summary, dict):
            pbo_summary = {}
        multiple_testing = summary.get("multiple_testing", {})
        if not isinstance(multiple_testing, dict):
            multiple_testing = {}
        lookahead_controls = summary.get("lookahead_controls", {})
        if not isinstance(lookahead_controls, dict):
            lookahead_controls = {}
        cost_before_after = summary.get("cost_before_after", {})
        if not isinstance(cost_before_after, dict):
            cost_before_after = {}
        promotion_contract = summary.get("promotion_gate_contract", {})
        if not isinstance(promotion_contract, dict):
            promotion_contract = {}
        contract_checks = promotion_contract.get("checks", {})
        if not isinstance(contract_checks, dict):
            contract_checks = {}

        evidence["validation_cv_method"] = str(cv_summary.get("method", "unknown"))
        evidence["validation_effective_trial_count"] = int(
            trial_counting.get("effective_trial_count", 0) or 0
        )
        evidence["validation_independent_trial_count"] = int(
            trial_counting.get("independent_trial_count", 0) or 0
        )
        evidence["deflated_sharpe_ratio"] = dsr_summary.get("dsr")
        evidence["probability_of_backtest_overfitting"] = pbo_summary.get("pbo")
        evidence["validation_cost_mode"] = str(cost_before_after.get("mode", "unavailable"))
        evidence["validation_multiple_testing"] = multiple_testing
        evidence["validation_lookahead_controls"] = lookahead_controls
        evidence["validation_contract_status"] = str(promotion_contract.get("status", "unknown"))
        evidence["validation_promotion_contract"] = promotion_contract

        if evidence["validation_cv_method"] == "unknown":
            warnings.append(
                "validation_cv_summary_missing: walk-forward evidence should declare purged/embargoed CV or CPCV metadata"
            )
        if summary.get("status") != "complete":
            warnings.append(
                "validation_statistics_partial: promotion evidence is missing one or more validation statistics"
            )

        dsr_value = dsr_summary.get("dsr")
        if not contract_checks.get("dsr_available", dsr_value is not None):
            reasons.append(
                "missing_deflated_sharpe_ratio: promotion requires DSR evidence after trial counting"
            )
        if dsr_value is not None and float(dsr_value) < 0.10:
            reasons.append(
                f"deflated_sharpe_too_low: dsr={float(dsr_value):.3f} (< 0.10 threshold)"
            )

        pbo_value = pbo_summary.get("pbo")
        if not contract_checks.get("pbo_available", pbo_value is not None):
            reasons.append(
                "missing_pbo_evidence: promotion requires CPCV/PBO path statistics, not a single best-path summary"
            )
        if pbo_value is not None:
            pbo_value = float(pbo_value)
            if pbo_value > 0.50:
                reasons.append(
                    f"pbo_too_high: pbo={pbo_value:.3f} (> 0.50 threshold)"
                )
            elif pbo_value > 0.20:
                warnings.append(
                    f"pbo_watchlist: pbo={pbo_value:.3f} (> 0.20 advisory)"
                )

        if not contract_checks.get("cv_method_allowed", False):
            reasons.append(
                f"validation_cv_method_not_allowed: method={evidence['validation_cv_method']} "
                "(need cpcv, purged_kfold, or embargoed_walk_forward)"
            )
        if not contract_checks.get("cpcv_available", False):
            reasons.append(
                "missing_cpcv_evidence: promotion requires CPCV metadata with at least 2 persisted validation paths"
            )
        if (
            not contract_checks.get("purged_or_embargoed", False)
            or not contract_checks.get("purge_embargo_recorded", False)
        ):
            reasons.append(
                "validation_purge_embargo_missing: promotion requires recorded purge and embargo parameters for out-of-sample validation"
            )
        if not contract_checks.get("multi_path_validation", False):
            reasons.append(
                "single_path_validation_not_allowed: candidate cannot promote on a single validation path even with high Sharpe"
            )
        if not contract_checks.get("trial_count_sufficient", False):
            reasons.append(
                "insufficient_effective_trials: promotion requires at least 2 effective and independent trials"
            )
        if not contract_checks.get("multiple_testing_complete", False):
            reasons.append(
                "multiple_testing_missing: promotion requires family-wise multiple-testing statistics"
            )
        elif not contract_checks.get("multiple_testing_passed", False):
            reasons.append(
                "multiple_testing_rejected: observed Sharpe does not survive family-wise multiple-testing control"
            )
        if not contract_checks.get("lookahead_guard_recorded", False):
            reasons.append(
                "lookahead_guard_missing: promotion requires recorded no-lookahead feature/label timing controls"
            )
        elif not contract_checks.get("lookahead_guard_passed", False):
            reasons.append(
                "lookahead_guard_failed: validation evidence reports possible future-data leakage"
            )

    @staticmethod
    def _file_sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _now_iso() -> str:
        from quant_us.core.clock import utc_now

        return utc_now().isoformat()

    def _load_backtest_manifest(
        self,
        *,
        candidate_id: str,
        candidate_data: dict[str, Any],
        metrics: dict[str, Any],
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any] | None:
        raw_path = candidate_data.get("backtest_manifest_path") or ""
        metrics_path = metrics.get("backtest_manifest_path") or ""
        inline_manifest = (
            candidate_data.get("backtest_manifest")
            or metrics.get("backtest_manifest")
        )
        canonical_path = self._canonical_backtest_manifest_path(candidate_id)
        canonical_path_text = str(canonical_path.relative_to(self.data_root))

        evidence["backtest_manifest_path"] = str(raw_path or "")
        evidence["backtest_manifest_metrics_path"] = str(metrics_path or "")
        evidence["backtest_manifest_expected_path"] = canonical_path_text
        evidence["backtest_manifest_inline"] = isinstance(inline_manifest, dict)
        evidence["backtest_manifest_present"] = False

        if metrics_path and str(metrics_path) != str(raw_path):
            reasons.append(
                "non_canonical_backtest_manifest_reference: promotion ignores "
                "metrics-level backtest_manifest_path and only trusts the "
                "candidate's persisted canonical backtest_manifest_path"
            )

        if not raw_path:
            evidence["backtest_manifest_source"] = (
                "inline_untrusted" if isinstance(inline_manifest, dict) else "missing"
            )
            reasons.append(
                "missing_canonical_backtest_manifest_path: candidate must persist "
                f"backtest_manifest_path={canonical_path_text}"
            )
            if isinstance(inline_manifest, dict):
                reasons.append(
                    "inline_backtest_manifest_not_allowed: promotion requires a "
                    "persisted canonical backtest_manifest_path"
                )
            reasons.append(
                "missing_backtest_manifest_evidence: READY_FOR_PAPER_REVIEW requires canonical backtest manifest evidence"
            )
            return None

        manifest_path = self._resolve_backtest_manifest_path(raw_path)
        evidence["backtest_manifest_resolved_path"] = (
            str(manifest_path) if manifest_path is not None else ""
        )
        if manifest_path is None or not self._same_path(manifest_path, canonical_path):
            evidence["backtest_manifest_source"] = "non_canonical_path"
            reasons.append(
                "non_canonical_backtest_manifest_path: promotion only accepts "
                f"{canonical_path_text}"
            )
            if isinstance(inline_manifest, dict):
                reasons.append(
                    "inline_backtest_manifest_not_allowed: promotion requires a "
                    "persisted canonical backtest_manifest_path"
                )
            reasons.append(
                "missing_backtest_manifest_evidence: READY_FOR_PAPER_REVIEW requires canonical backtest manifest evidence"
            )
            return None

        if not manifest_path.exists():
            evidence["backtest_manifest_source"] = "missing"
            reasons.append(
                f"backtest_manifest_path_missing: manifest not found at {manifest_path}"
            )
            if isinstance(inline_manifest, dict):
                reasons.append(
                    "inline_backtest_manifest_not_allowed: inline manifest cannot "
                    "replace a missing persisted backtest manifest"
                )
            reasons.append(
                "missing_backtest_manifest_evidence: READY_FOR_PAPER_REVIEW requires canonical backtest manifest evidence"
            )
            return None

        evidence["backtest_manifest_present"] = True
        evidence["backtest_manifest_source"] = "path"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        evidence["backtest_manifest_engine"] = str(manifest.get("engine", ""))
        evidence["backtest_manifest_canonical_for_promotion"] = bool(
            manifest.get("canonical_for_promotion", False)
        )
        return manifest

    def _canonical_backtest_manifest_path(self, candidate_id: str) -> Path:
        return (
            self.data_root
            / "research"
            / "backtests"
            / candidate_id
            / "run_manifest.json"
        )

    def _resolve_backtest_manifest_path(self, raw_path: Any) -> Path | None:
        if not raw_path:
            return None
        candidate = Path(str(raw_path))
        if candidate.exists() or candidate.is_absolute():
            return candidate
        data_relative = self.data_root / candidate
        if data_relative.exists():
            return data_relative
        return candidate

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        return left.resolve(strict=False) == right.resolve(strict=False)

    def _evaluate_data_scope(
        self,
        candidate_data: dict[str, Any],
        experiment_data: dict[str, Any],
        backtest_manifest: dict[str, Any] | None,
        evidence: dict[str, Any],
        reasons: list[str],
        warnings: list[str],
    ) -> None:
        metrics = candidate_data.get("metrics", {}) or {}
        manifest_evidence = (
            backtest_manifest.get("evidence", {}) if isinstance(backtest_manifest, dict) else {}
        )
        manifest_scope = manifest_evidence.get("data_scope", {}) or {}
        embedded_data_manifest = self._embedded_data_manifest(backtest_manifest)

        symbols = (
            candidate_data.get("symbols")
            or experiment_data.get("symbols")
            or metrics.get("symbols")
            or []
        )
        if isinstance(symbols, str):
            symbols = [symbols]
        normalized_symbols = [str(symbol).upper() for symbol in symbols]
        data_version = str(
            (backtest_manifest or {}).get("data_version", "")
            or candidate_data.get("data_version")
            or experiment_data.get("data_version")
            or metrics.get("data_version")
            or ""
        )
        data_source = str(
            getattr(embedded_data_manifest, "source", "")
            or candidate_data.get("data_source")
            or candidate_data.get("data_vendor")
            or candidate_data.get("source")
            or experiment_data.get("data_source")
            or experiment_data.get("data_vendor")
            or experiment_data.get("source")
            or metrics.get("data_source")
            or metrics.get("data_vendor")
            or metrics.get("source")
            or self._source_from_data_version(data_version)
            or ""
        ).lower()
        asset_class = str(
            getattr(embedded_data_manifest, "asset_class", "")
            or candidate_data.get("asset_class")
            or experiment_data.get("asset_class")
            or metrics.get("asset_class")
            or self._asset_class(normalized_symbols)
        ).lower()
        fixture_used = bool(manifest_scope.get("fixture_like_data_version", False)) or (
            data_source == "fixture" or "fixture" in data_version.lower()
        )
        scope_rejections = [
            str(item) for item in manifest_scope.get("scope_rejections", []) or []
        ]

        evidence["symbols"] = normalized_symbols
        evidence["data_version"] = data_version
        evidence["data_source"] = data_source
        evidence["asset_class"] = asset_class
        evidence["fixture_used"] = fixture_used
        evidence["backtest_manifest_scope_ok"] = bool(
            manifest_scope.get("promotion_scope_ok", True)
        )
        if scope_rejections:
            evidence["backtest_manifest_scope_rejections"] = scope_rejections

        if not normalized_symbols:
            reasons.append("missing_symbols: promotion requires explicit US equity symbols")
        if not data_version:
            reasons.append("missing_data_version: promotion requires governed data_version evidence")
        if fixture_used:
            reasons.append("fixture_data_not_allowed: fixture evidence cannot enter paper review")
        if scope_rejections:
            reasons.extend(
                f"backtest_manifest_scope_rejection:{rejection}"
                for rejection in scope_rejections
            )
        if (
            isinstance(backtest_manifest, dict)
            and manifest_scope
            and not bool(manifest_scope.get("promotion_scope_ok", False))
            and not scope_rejections
        ):
            reasons.append(
                "backtest_manifest_scope_invalid: manifest marks evidence out of promotion scope"
            )
        if data_source not in ALLOWED_DATA_SOURCES:
            reasons.append(
                f"unsupported_data_source: data_source={data_source or 'unknown'} "
                f"(allowed={sorted(ALLOWED_DATA_SOURCES)})"
            )
        if asset_class not in ALLOWED_ASSET_CLASSES:
            reasons.append(
                f"asset_class_not_allowed: asset_class={asset_class or 'unknown'} "
                f"must be one of {sorted(ALLOWED_ASSET_CLASSES)}"
            )
        if asset_class == "crypto" and data_source != "sqlite":
            reasons.append(
                f"crypto_requires_sqlite_data_source: data_source={data_source or 'unknown'} "
                "must be sqlite for BTC/crypto paper-review candidates"
            )
        if data_version:
            self._evaluate_data_manifest(
                data_version=data_version,
                data_source=data_source,
                asset_class=asset_class,
                symbols=normalized_symbols,
                embedded_manifest=embedded_data_manifest,
                evidence=evidence,
                reasons=reasons,
                warnings=warnings,
            )

    def _evaluate_event_ledger_evidence(
        self,
        *,
        metrics: dict[str, Any],
        backtest_manifest: dict[str, Any] | None,
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> None:
        manifest_evidence = (
            backtest_manifest.get("evidence", {}) if isinstance(backtest_manifest, dict) else {}
        )
        manifest_orders = manifest_evidence.get("orders", {}) or {}
        manifest_fills = manifest_evidence.get("fills", {}) or {}
        manifest_equity = manifest_evidence.get("equity", {}) or {}
        manifest_completeness = manifest_evidence.get("completeness", {}) or {}

        engine = str(
            (backtest_manifest or {}).get("engine", "")
            or metrics.get("engine")
            or metrics.get("canonical_engine")
            or metrics.get("backtest_engine")
            or ""
        )
        canonical_for_promotion = bool(
            (backtest_manifest or {}).get("canonical_for_promotion", False)
        ) if isinstance(backtest_manifest, dict) else False
        ledger_consistency_pct = (
            100.0
            if bool(manifest_equity.get("consistent", False))
            else self._as_pct(
                metrics.get(
                    "ledger_consistency_pct",
                    metrics.get("ledger_equity_consistency_pct", -1.0),
                )
            )
        )
        fill_count = int(
            manifest_fills.get(
                "count",
                metrics.get("total_fill_count", metrics.get("fill_count", 0)),
            )
            or 0
        )
        order_count = int(
            manifest_orders.get(
                "count",
                metrics.get("total_order_count", metrics.get("order_count", 0)),
            )
            or 0
        )
        baseline_fill_count = int(metrics.get("baseline_fill_count", fill_count) or 0)
        baseline_order_count = int(metrics.get("baseline_order_count", order_count) or 0)
        has_trade_metadata = all(
            value > 0
            for value in (fill_count, order_count, baseline_fill_count, baseline_order_count)
        )
        ledger_artifact_ok = self._evaluate_ledger_reconciliation_artifact(
            backtest_manifest=backtest_manifest,
            manifest_evidence=manifest_evidence,
            manifest_orders=manifest_orders,
            manifest_fills=manifest_fills,
            fill_count=fill_count,
            order_count=order_count,
            evidence=evidence,
            reasons=reasons,
        )

        evidence["engine"] = engine
        evidence["canonical_for_promotion"] = canonical_for_promotion
        evidence["ledger_consistency_pct"] = ledger_consistency_pct
        evidence["total_fill_count"] = fill_count
        evidence["total_order_count"] = order_count
        evidence["baseline_fill_count"] = baseline_fill_count
        evidence["baseline_order_count"] = baseline_order_count
        evidence["has_ledger_trade_metadata"] = has_trade_metadata

        if isinstance(backtest_manifest, dict):
            orders_have_risk = bool(
                manifest_orders.get("all_orders_have_risk_check_id", False)
            )
            fills_match_orders = bool(
                manifest_fills.get("all_fills_match_orders", False)
            )
            promotion_evidence_complete = bool(
                manifest_completeness.get("promotion_evidence_complete", False)
            )
            evidence["backtest_manifest_used_for_promotion"] = True
            evidence["orders_have_risk_check_id"] = orders_have_risk
            evidence["fills_match_orders"] = fills_match_orders
            evidence["promotion_evidence_complete"] = promotion_evidence_complete
            evidence["ledger_artifact_required"] = True
            evidence["ledger_artifact_ok"] = ledger_artifact_ok
        else:
            orders_have_risk = None
            fills_match_orders = None
            promotion_evidence_complete = None

        if engine != "event_driven":
            reasons.append("event_driven_required: promotion requires event_driven backtest evidence")
        if isinstance(backtest_manifest, dict) and not canonical_for_promotion:
            reasons.append(
                "canonical_backtest_manifest_required: backtest manifest must be canonical_for_promotion"
            )
        if ledger_consistency_pct < 100.0:
            reasons.append(
                f"ledger_consistency_failed: ledger_consistency_pct={ledger_consistency_pct:.2f} "
                "(need 100.0)"
            )
        if not has_trade_metadata:
            reasons.append("missing_ledger_trade_metadata: fills and orders must be present")
        if isinstance(backtest_manifest, dict) and not promotion_evidence_complete:
            reasons.append(
                "promotion_evidence_incomplete: backtest manifest completeness.promotion_evidence_complete must be true"
            )
        if isinstance(backtest_manifest, dict) and not orders_have_risk:
            reasons.append(
                "missing_order_risk_metadata: manifest must prove all orders have risk check ids"
            )
        if isinstance(backtest_manifest, dict) and not fills_match_orders:
            reasons.append(
                "missing_fill_order_linkage: manifest must prove all fills map to orders"
            )
        if isinstance(backtest_manifest, dict) and not ledger_artifact_ok:
            reasons.append(
                "ledger_reconciliation_artifact_invalid: promotion requires consistent ledger reconciliation artifact evidence"
            )

    def _evaluate_ledger_reconciliation_artifact(
        self,
        *,
        backtest_manifest: dict[str, Any] | None,
        manifest_evidence: dict[str, Any],
        manifest_orders: dict[str, Any],
        manifest_fills: dict[str, Any],
        fill_count: int,
        order_count: int,
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> bool:
        if not isinstance(backtest_manifest, dict):
            evidence["ledger_artifact_present"] = False
            return False

        raw_artifact = manifest_evidence.get("ledger_artifact")
        if not isinstance(raw_artifact, dict):
            raw_artifact = backtest_manifest.get("ledger_artifact")
        artifact = raw_artifact if isinstance(raw_artifact, dict) else {}

        artifact_hash = str(artifact.get("artifact_hash", "") or "")
        generated_at = str(artifact.get("generated_at", "") or "")
        as_of_utc = str(artifact.get("as_of_utc", "") or "")
        hashes = artifact.get("hashes", {})
        if not isinstance(hashes, dict):
            hashes = {}
        artifact_fills_hash = str(hashes.get("fills_hash", "") or "")
        artifact_ledger_hash = str(hashes.get("ledger_hash", "") or "")
        artifact_orders_hash = str(hashes.get("orders_hash", "") or "")
        artifact_snapshots_hash = str(hashes.get("portfolio_snapshots_hash", "") or "")

        evidence["ledger_artifact_present"] = bool(artifact)
        evidence["ledger_artifact_hash"] = artifact_hash
        evidence["ledger_artifact_generated_at"] = generated_at
        evidence["ledger_artifact_as_of_utc"] = as_of_utc
        evidence["ledger_hash"] = artifact_ledger_hash
        evidence["fills_hash"] = artifact_fills_hash
        evidence["orders_hash"] = artifact_orders_hash
        evidence["portfolio_snapshots_hash"] = artifact_snapshots_hash

        if not artifact:
            reasons.append(
                "missing_ledger_reconciliation_artifact: promotion requires ledger reconciliation artifact evidence"
            )
            return False

        raw_artifact_path = str(
            backtest_manifest.get("ledger_artifact_path")
            or manifest_evidence.get("ledger_artifact_path")
            or ""
        )
        evidence["ledger_artifact_path"] = raw_artifact_path
        artifact_file_ok = self._validate_standalone_ledger_artifact(
            raw_artifact_path=raw_artifact_path,
            embedded_artifact=artifact,
            embedded_artifact_hash=artifact_hash,
            reasons=reasons,
            evidence=evidence,
        )

        required_bindings = {
            "artifact_hash": str(
                backtest_manifest.get("ledger_artifact_hash")
                or manifest_evidence.get("ledger_artifact_hash")
                or ""
            ),
            "ledger_hash": str(
                backtest_manifest.get("ledger_hash")
                or manifest_evidence.get("ledger_hash")
                or ""
            ),
            "fills_hash": str(
                backtest_manifest.get("fills_hash")
                or manifest_evidence.get("fills_hash")
                or manifest_fills.get("fills_hash")
                or ""
            ),
        }
        manifest_reconciliation = manifest_evidence.get("reconciliation", {})
        if not isinstance(manifest_reconciliation, dict):
            manifest_reconciliation = {}
        manifest_summary = manifest_reconciliation.get("summary", {})
        if not isinstance(manifest_summary, dict) or not manifest_summary:
            top_level_summary = backtest_manifest.get("reconciliation", {})
            manifest_summary = dict(top_level_summary) if isinstance(top_level_summary, dict) else {}

        artifact_reconciliation = artifact.get("reconciliation", {})
        if not isinstance(artifact_reconciliation, dict):
            artifact_reconciliation = {}
        artifact_summary = artifact_reconciliation.get("summary", {})
        if not isinstance(artifact_summary, dict):
            artifact_summary = {}

        artifact_orders = artifact.get("orders", {})
        if not isinstance(artifact_orders, dict):
            artifact_orders = {}
        artifact_fills = artifact.get("fills", {})
        if not isinstance(artifact_fills, dict):
            artifact_fills = {}
        artifact_pnl = artifact.get("pnl", {})
        if not isinstance(artifact_pnl, dict):
            artifact_pnl = {}
        manifest_pnl = manifest_evidence.get("pnl", {})
        if not isinstance(manifest_pnl, dict):
            manifest_pnl = {}
        artifact_integrity = artifact.get("integrity", {})
        if not isinstance(artifact_integrity, dict):
            artifact_integrity = {}

        expected_hash = compute_ledger_reconciliation_artifact_hash(artifact)
        bindings_present = all(required_bindings.values())
        bindings_match = (
            required_bindings["artifact_hash"] == artifact_hash
            and required_bindings["ledger_hash"] == artifact_ledger_hash
            and required_bindings["fills_hash"] == artifact_fills_hash
        )
        summary_present = bool(artifact_summary) and bool(manifest_summary)
        summary_match = summary_present and artifact_summary == manifest_summary
        count_match = (
            int(artifact_orders.get("total_orders", -1) or -1) == order_count
            and int(artifact_fills.get("effective_fill_count", -1) or -1) == fill_count
        )
        manifest_pnl_value = manifest_pnl.get(
            "net_pnl",
            manifest_pnl.get("final_pnl"),
        )
        pnl_match = (
            bool(manifest_pnl)
            and str(artifact_pnl.get("source", "")) == "ledger_fills"
            and str(manifest_pnl.get("source", "")) == "ledger_fills"
            and self._numbers_close(
                artifact_pnl.get("final_equity"),
                manifest_pnl.get("final_equity"),
            )
            and self._numbers_close(artifact_pnl.get("net_pnl"), manifest_pnl_value)
        )
        hashes_present = all(
            [
                artifact_hash,
                generated_at,
                as_of_utc,
                artifact_fills_hash,
                artifact_ledger_hash,
                artifact_orders_hash,
                artifact_snapshots_hash,
            ]
        )
        integrity_passed = bool(artifact_integrity.get("passed", False))

        if not hashes_present:
            reasons.append(
                "ledger_reconciliation_artifact_fields_missing: artifact must include artifact_hash, generated_at, as_of_utc, ledger_hash, fills_hash, orders_hash, portfolio_snapshots_hash"
            )
        if artifact_hash != expected_hash:
            reasons.append(
                "ledger_reconciliation_artifact_hash_mismatch: artifact_hash does not match artifact payload"
            )
        if not bindings_present:
            reasons.append(
                "ledger_reconciliation_artifact_binding_missing: manifest must bind ledger_artifact_hash, ledger_hash, and fills_hash"
            )
        elif not bindings_match:
            reasons.append(
                "ledger_reconciliation_artifact_binding_mismatch: manifest hash bindings do not match artifact hashes"
            )
        if not summary_present:
            reasons.append(
                "ledger_reconciliation_summary_missing: manifest and artifact must both include reconciliation summary"
            )
        elif not summary_match:
            reasons.append(
                "ledger_reconciliation_summary_mismatch: artifact reconciliation summary differs from manifest reconciliation summary"
            )
        if not count_match:
            reasons.append(
                "ledger_reconciliation_trade_count_mismatch: artifact counts differ from manifest order/fill counts"
            )
        if not pnl_match:
            reasons.append(
                "ledger_reconciliation_pnl_mismatch: artifact PnL must match manifest ledger-backed PnL"
            )
        if not integrity_passed:
            reasons.append(
                "ledger_reconciliation_integrity_failed: artifact integrity.passed must be true"
            )

        return (
            hashes_present
            and artifact_hash == expected_hash
            and bindings_present
            and bindings_match
            and summary_present
            and summary_match
            and count_match
            and pnl_match
            and integrity_passed
            and artifact_file_ok
        )

    def _validate_standalone_ledger_artifact(
        self,
        *,
        raw_artifact_path: str,
        embedded_artifact: dict[str, Any],
        embedded_artifact_hash: str,
        reasons: list[str],
        evidence: dict[str, Any],
    ) -> bool:
        artifact_path = self._resolve_ledger_artifact_path(raw_artifact_path)
        evidence["ledger_artifact_file_present"] = False
        evidence["ledger_artifact_file_hash_match"] = False
        evidence["ledger_artifact_file_payload_match"] = False
        evidence["ledger_artifact_resolved_path"] = str(artifact_path) if artifact_path else ""

        if artifact_path is None:
            reasons.append(
                "ledger_reconciliation_artifact_path_missing: manifest must bind a standalone ledger artifact file path"
            )
            return False
        if not artifact_path.exists():
            reasons.append(
                f"ledger_reconciliation_artifact_path_not_found: {artifact_path}"
            )
            return False

        try:
            file_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reasons.append(
                f"ledger_reconciliation_artifact_file_unreadable: {artifact_path}: {exc}"
            )
            return False
        if not isinstance(file_artifact, dict):
            reasons.append(
                f"ledger_reconciliation_artifact_file_invalid: {artifact_path}"
            )
            return False

        evidence["ledger_artifact_file_present"] = True
        file_artifact_hash = str(file_artifact.get("artifact_hash", "") or "")
        file_expected_hash = compute_ledger_reconciliation_artifact_hash(file_artifact)
        hash_match = (
            bool(file_artifact_hash)
            and file_artifact_hash == file_expected_hash
            and file_artifact_hash == embedded_artifact_hash
        )
        payload_match = file_artifact == embedded_artifact
        evidence["ledger_artifact_file_hash"] = file_artifact_hash
        evidence["ledger_artifact_file_hash_match"] = hash_match
        evidence["ledger_artifact_file_payload_match"] = payload_match
        if not hash_match:
            reasons.append(
                "ledger_reconciliation_artifact_file_hash_mismatch: standalone artifact hash does not match manifest artifact"
            )
        if not payload_match:
            reasons.append(
                "ledger_reconciliation_artifact_file_payload_mismatch: standalone artifact payload differs from manifest artifact"
            )
        return hash_match and payload_match

    def _resolve_ledger_artifact_path(self, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        candidate = Path(str(raw_path))
        if candidate.exists() or candidate.is_absolute():
            return candidate
        data_relative = self.data_root / candidate
        if data_relative.exists():
            return data_relative
        return candidate

    def _record_unified_backtest_report_evidence(
        self,
        *,
        backtest_manifest: dict[str, Any] | None,
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> None:
        manifest_evidence = (
            backtest_manifest.get("evidence", {}) if isinstance(backtest_manifest, dict) else {}
        )
        if not isinstance(manifest_evidence, dict):
            manifest_evidence = {}

        reconciliation = manifest_evidence.get("reconciliation", {})
        if not isinstance(reconciliation, dict):
            reconciliation = {}
        reconciliation_summary = reconciliation.get("summary", {})
        if not isinstance(reconciliation_summary, dict):
            reconciliation_summary = {}
        reconciliation_snapshots = reconciliation.get("snapshots", [])
        if not isinstance(reconciliation_snapshots, list):
            reconciliation_snapshots = []
        adjustment_cross_check = reconciliation.get("adjustment_cross_check", {})
        if adjustment_cross_check is not None and not isinstance(adjustment_cross_check, dict):
            adjustment_cross_check = {}

        if not reconciliation_summary and isinstance(backtest_manifest, dict):
            top_level_summary = backtest_manifest.get("reconciliation", {})
            if isinstance(top_level_summary, dict):
                reconciliation_summary = dict(top_level_summary)

        has_reconciliation_evidence = bool(reconciliation_summary) or bool(reconciliation_snapshots)
        if not has_reconciliation_evidence:
            reconciliation_summary = {
                "snapshot_count": 0,
                "tolerance_pct": 0.0,
                "absolute_tolerance": 0.0,
                "max_abs_diff": 0.0,
                "max_pct_diff": 0.0,
                "passed": None,
                "message": "reconciliation evidence unavailable",
            }

        summary_passed_raw = reconciliation_summary.get("passed")
        summary_passed = (
            self._evidence_bool(summary_passed_raw)
            if summary_passed_raw is not None
            else None
        )
        failed_snapshots = [
            snapshot for snapshot in reconciliation_snapshots
            if not self._evidence_bool(snapshot.get("passed", False))
        ]

        evidence["reconciliation"] = {
            "summary": reconciliation_summary,
            "snapshots": reconciliation_snapshots,
            "adjustment_cross_check": adjustment_cross_check,
        }
        evidence["reconciliation_summary"] = reconciliation_summary
        evidence["reconciliation_passed"] = summary_passed
        evidence["reconciliation_max_abs_diff"] = float(
            reconciliation_summary.get("max_abs_diff", 0.0) or 0.0
        )
        evidence["reconciliation_max_pct_diff"] = float(
            reconciliation_summary.get("max_pct_diff", 0.0) or 0.0
        )
        evidence["reconciliation_failed_snapshot_count"] = len(failed_snapshots)
        evidence["reconciliation_failed_snapshot_summary"] = (
            self._summarize_failed_reconciliation_snapshots(failed_snapshots)
        )
        if adjustment_cross_check:
            evidence["reconciliation_adjustment_cross_check"] = adjustment_cross_check
        evidence["corporate_actions"] = {
            "digest": self._resolve_corporate_actions_digest(backtest_manifest, manifest_evidence),
        }
        evidence["corporate_actions_digest"] = evidence["corporate_actions"]["digest"]

        if has_reconciliation_evidence and summary_passed is False:
            reasons.append(
                "reconciliation_failed: backtest reconciliation summary.passed is false"
            )

    def _resolve_corporate_actions_digest(
        self,
        backtest_manifest: dict[str, Any] | None,
        manifest_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        digest: dict[str, Any] = {}
        if isinstance(backtest_manifest, dict):
            top_level = backtest_manifest.get("corporate_actions", {})
            if isinstance(top_level, dict):
                digest = dict(top_level)
        if not digest:
            nested = manifest_evidence.get("corporate_actions", {})
            if isinstance(nested, dict):
                nested_digest = nested.get("digest", {})
                if isinstance(nested_digest, dict):
                    digest = dict(nested_digest)
        return digest

    @staticmethod
    def _summarize_failed_reconciliation_snapshots(
        snapshots: list[dict[str, Any]],
    ) -> str:
        if not snapshots:
            return "none"

        first = snapshots[0]
        timestamp = str(first.get("timestamp_utc", "unknown"))
        diff = first.get("diff", {})
        if not isinstance(diff, dict):
            diff = {}
        cash_diff = first.get("cash_diff", diff.get("cash", "unknown"))
        equity_diff = first.get("equity_diff", diff.get("equity", "unknown"))
        max_abs_diff = first.get("max_abs_diff", "unknown")
        max_pct_diff = first.get("max_pct_diff", "unknown")
        return (
            f"count={len(snapshots)}; first={timestamp}; "
            f"cash_diff={ResearchPromotionGate._format_summary_number(cash_diff)}; "
            f"equity_diff={ResearchPromotionGate._format_summary_number(equity_diff)}; "
            f"max_abs_diff={ResearchPromotionGate._format_summary_number(max_abs_diff)}; "
            f"max_pct_diff={ResearchPromotionGate._format_summary_number(max_pct_diff)}"
        )

    @staticmethod
    def _format_summary_number(value: Any) -> str:
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _evidence_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "passed", "pass"}
        return bool(value)

    @staticmethod
    def _numbers_close(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
        if left is None or right is None:
            return False
        try:
            return abs(float(left) - float(right)) <= tolerance
        except (TypeError, ValueError):
            return False

    def _evaluate_data_manifest(
        self,
        *,
        data_version: str,
        data_source: str,
        asset_class: str,
        symbols: list[str],
        embedded_manifest: DataManifest | None,
        evidence: dict[str, Any],
        reasons: list[str],
        warnings: list[str],
    ) -> None:
        canonical_path = self.data_root / "manifests" / f"{data_version}.json"
        manifest_rows = self._find_matching_data_manifests(data_version)
        canonical_rows = [
            row for row in manifest_rows if self._same_path(row["path"], canonical_path)
        ]

        evidence["data_manifest_expected_path"] = str(canonical_path)
        evidence["data_manifest_candidate_count"] = len(manifest_rows)
        evidence["data_manifest_candidate_paths"] = [
            str(row["path"]) for row in manifest_rows
        ]
        evidence["data_manifest_embedded"] = embedded_manifest is not None
        evidence["data_manifest_store_exists"] = canonical_path.exists()
        evidence["data_manifest_exists"] = canonical_path.exists()
        if not canonical_path.exists():
            reasons.append(
                "missing_canonical_data_manifest: governed data manifest not found "
                f"at {canonical_path}"
            )
            return
        if len(canonical_rows) != 1:
            reasons.append(
                "data_manifest_conflict: canonical data manifest path does not "
                "resolve to exactly one persisted manifest row"
            )
            return
        if len(manifest_rows) != 1:
            reasons.append(
                "data_manifest_conflict: multiple persisted manifests found for "
                f"data_version={data_version}"
            )

        store_manifest = DataManifestStore(self.data_root / "manifests").read(data_version)
        if store_manifest is None:
            reasons.append(
                "invalid_canonical_data_manifest: canonical data manifest file is "
                "missing required fields or unreadable as DataManifest"
            )
            return

        manifest = store_manifest
        validation = validate_manifest_for_promotion(
            manifest,
            allow_asset_classes=ALLOWED_ASSET_CLASSES,
        )
        evidence["data_manifest_id"] = manifest.manifest_id
        evidence["data_manifest_checksum"] = manifest.effective_checksum
        evidence["data_manifest_fingerprint"] = manifest.fingerprint
        evidence["data_manifest_source"] = "manifest_store"
        evidence["data_manifest_binding_state"] = "missing"
        evidence["data_manifest_validation"] = {
            "ok": validation.ok,
            "reasons": validation.reasons,
            "warnings": validation.warnings,
            "metrics": validation.metrics,
        }

        if embedded_manifest is None:
            reasons.append(
                "stale_data_manifest_binding_missing: backtest manifest must embed "
                "the canonical persisted data manifest binding"
            )
        else:
            evidence["data_manifest_embedded_id"] = embedded_manifest.manifest_id
            evidence["data_manifest_embedded_checksum"] = (
                embedded_manifest.effective_checksum
            )
            evidence["data_manifest_embedded_fingerprint"] = (
                embedded_manifest.fingerprint
            )
            binding_mismatches = self._compare_embedded_data_manifest(
                embedded=embedded_manifest,
                governed=manifest,
            )
            if binding_mismatches:
                evidence["data_manifest_binding_state"] = "stale"
                reasons.append(
                    "stale_data_manifest_binding: embedded backtest data manifest "
                    "differs from the canonical persisted data manifest"
                )
                reasons.extend(binding_mismatches)
            else:
                evidence["data_manifest_binding_state"] = "bound"

        manifest_symbol = manifest.symbol.upper()
        if symbols and manifest_symbol not in symbols:
            reasons.append(
                f"data_manifest_symbol_mismatch: manifest={manifest_symbol} "
                f"candidate={symbols}"
            )
        if manifest.source.lower() != data_source:
            reasons.append(
                f"data_manifest_source_mismatch: manifest={manifest.source.lower()} "
                f"candidate={data_source}"
            )
        if manifest.asset_class.lower() != asset_class:
            reasons.append(
                f"data_manifest_asset_class_mismatch: manifest={manifest.asset_class.lower()} "
                f"candidate={asset_class}"
            )
        reasons.extend(f"data_manifest_invalid:{reason}" for reason in validation.reasons)
        warnings.extend(
            f"data_manifest_warning:{warning}"
            for warning in validation.warnings
            if warning not in DATA_MANIFEST_ADVISORY_WARNINGS
        )

    def _compare_embedded_data_manifest(
        self,
        *,
        embedded: DataManifest,
        governed: DataManifest,
    ) -> list[str]:
        mismatches: list[str] = []
        if embedded.data_version != governed.data_version:
            mismatches.append(
                "data_manifest_version_mismatch: "
                f"embedded={embedded.data_version} governed={governed.data_version}"
            )
        if embedded.effective_checksum != governed.effective_checksum:
            mismatches.append(
                "data_manifest_checksum_mismatch: "
                f"embedded={embedded.effective_checksum} "
                f"governed={governed.effective_checksum}"
            )
        if embedded.fingerprint != governed.fingerprint:
            mismatches.append(
                "data_manifest_fingerprint_mismatch: "
                f"embedded={embedded.fingerprint} governed={governed.fingerprint}"
            )
        return mismatches

    def _find_matching_data_manifests(
        self,
        data_version: str,
    ) -> list[dict[str, Any]]:
        manifests_root = self.data_root / "manifests"
        matches: list[dict[str, Any]] = []
        if not manifests_root.exists():
            return matches
        for path in sorted(manifests_root.glob("*.json")):
            if path.stem.startswith("run_"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("data_version", "") or "") != data_version:
                continue
            if not all(payload.get(key) for key in ("data_version", "source", "symbol", "interval")):
                continue
            matches.append({"path": path, "payload": payload})
        return matches

    def _embedded_data_manifest(
        self,
        backtest_manifest: dict[str, Any] | None,
    ) -> DataManifest | None:
        if not isinstance(backtest_manifest, dict):
            return None
        raw = backtest_manifest.get("data_manifest")
        if not isinstance(raw, dict):
            return None

        valid_fields = {item.name for item in fields(DataManifest)}
        payload = {
            key: value
            for key, value in raw.items()
            if key in valid_fields
        }
        required = {"data_version", "source", "symbol", "interval"}
        if not required.issubset(payload):
            return None
        return DataManifest(**payload)

    def _build_next_commands(
        self,
        *,
        candidate_id: str,
        candidate_data: dict[str, Any],
        experiment_data: dict[str, Any],
        blocker_details: list[dict[str, Any]],
        reasons: list[str],
        warnings: list[str],
    ) -> list[str]:
        commands: list[str] = []
        materialization_command = self._build_materialization_command(candidate_id)
        if materialization_command:
            commands.append(materialization_command)
        for blocker in blocker_details:
            cli_next_command = str(blocker.get("cli_next_command", "") or "")
            if cli_next_command:
                commands.append(cli_next_command)
        reason_text = " ".join([*reasons, *warnings])

        symbols = candidate_data.get("symbols") or experiment_data.get("symbols") or []
        symbol = str(symbols[0]) if symbols else ""
        start = str(experiment_data.get("start_date", "") or "")
        end = str(experiment_data.get("end_date", "") or "")
        timeframe = str(experiment_data.get("timeframe", "1d") or "1d")
        strategy_id = str(
            experiment_data.get("strategy_id")
            or candidate_data.get("strategy_id")
            or "trend_momentum"
        )
        params = experiment_data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        vendor = str(
            experiment_data.get("data_source")
            or experiment_data.get("source")
            or candidate_data.get("data_source")
            or "yfinance"
        )
        experiment_id = str(experiment_data.get("experiment_id", "") or "")

        walk_forward_cli = self._build_walk_forward_cli_command(experiment_id)
        if walk_forward_cli and any(
            token in reason_text
            for token in (
                "missing_deflated_sharpe_ratio",
                "missing_pbo_evidence",
                "missing_cpcv_evidence",
                "lookahead_guard_",
                "validation_cv_",
                "single_path_validation_not_allowed",
                "insufficient_effective_trials",
                "multiple_testing_missing",
            )
        ):
            commands.append(walk_forward_cli)

        if symbol and start and end and any(
            token in reason_text
            for token in (
                "missing_deflated_sharpe_ratio",
                "missing_pbo_evidence",
                "missing_cpcv_evidence",
                "lookahead_guard_",
                "validation_cv_",
                "single_path_validation_not_allowed",
                "insufficient_effective_trials",
                "multiple_testing_missing",
            )
        ):
            commands.append(
                self._shell_join(
                    "PYTHONPATH=.",
                    self._python_executable(),
                    "scripts/run_walk_forward.py",
                    "--symbol",
                    symbol,
                    "--start",
                    start,
                    "--end",
                    end,
                    "--bar-size",
                    timeframe,
                    "--data-root",
                    str(self.data_root),
                )
            )

        rerun_command = self._build_research_rerun_command(
            symbol=symbol,
            start=start,
            end=end,
            timeframe=timeframe,
            strategy_id=strategy_id,
            params=params,
            vendor=vendor,
            experiment_id=experiment_id,
        )
        if rerun_command:
            commands.append(rerun_command)
        return list(dict.fromkeys(commands))

    def _build_blocker_details(
        self,
        *,
        candidate_id: str,
        candidate_data: dict[str, Any],
        experiment_data: dict[str, Any],
        evidence: dict[str, Any],
        reasons: list[str],
    ) -> list[dict[str, Any]]:
        validation_stats = dict(evidence.get("validation_stats", {}) or {})
        cv_summary = dict(validation_stats.get("cv_summary", {}) or {})
        trial_counting = dict(validation_stats.get("trial_counting", {}) or {})
        dsr_summary = dict(validation_stats.get("deflated_sharpe_ratio", {}) or {})
        pbo_summary = dict(validation_stats.get("pbo", {}) or {})
        multiple_testing = dict(validation_stats.get("multiple_testing", {}) or {})
        contract = dict(evidence.get("validation_promotion_contract", {}) or {})
        required = dict(contract.get("required", {}) or {})
        metrics = candidate_data.get("metrics", {}) or {}
        if not isinstance(metrics, dict):
            metrics = {}

        catalog = self._build_command_catalog(
            candidate_id=candidate_id,
            candidate_data=candidate_data,
            experiment_data=experiment_data,
        )
        materialization_note = (
            "Materialization syncs canonical research artifacts from persisted candidate "
            "evidence only; it does not fabricate missing validation or robustness metrics."
        )
        real_trade_returns = self._series_length(metrics.get("trade_returns"))
        real_daily_returns = self._series_length(metrics.get("daily_returns"))
        param_grid = experiment_data.get("param_grid", {})
        param_grid_trial_count = 0
        if isinstance(param_grid, dict):
            for value in param_grid.values():
                if isinstance(value, list):
                    param_grid_trial_count = max(param_grid_trial_count, len(value))

        details: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for reason in reasons:
            code = self._reason_code(reason)
            if code in seen_codes:
                continue
            seen_codes.add(code)

            detail: dict[str, Any] = {
                "code": code,
                "severity": "blocking",
                "message": reason,
                "category": "promotion_gate",
                "materialization": {
                    "supported": bool(catalog.get("materialize")),
                    "command": catalog.get("materialize", ""),
                    "note": materialization_note,
                },
                "cli_next_command": "",
                "diagnostic_cli_command": "",
                "observed": {},
                "required": {},
            }

            if code == "missing_deflated_sharpe_ratio":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script")
                        or catalog.get("research_rerun", ""),
                        "observed": {
                            "validation_status": evidence.get("validation_status", ""),
                            "observed_sharpe": dsr_summary.get("observed_sharpe"),
                            "returns_count": dsr_summary.get("returns_count"),
                            "trial_count": dsr_summary.get("trial_count"),
                            "effective_trial_count": trial_counting.get("effective_trial_count"),
                            "independent_trial_count": trial_counting.get("independent_trial_count"),
                        },
                        "required": {
                            "min_dsr": required.get("min_dsr", 0.10),
                            "min_effective_trial_count": required.get(
                                "min_effective_trial_count", 2
                            ),
                            "min_independent_trial_count": required.get(
                                "min_independent_trial_count", 2
                            ),
                            "requires_real_return_series": True,
                        },
                    }
                )
            elif code == "missing_pbo_evidence":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script")
                        or catalog.get("research_rerun", ""),
                        "observed": {
                            "cv_method": cv_summary.get("method"),
                            "pbo_mode": pbo_summary.get("mode"),
                            "group_count": pbo_summary.get("group_count"),
                            "path_count": cv_summary.get("path_count"),
                            "fold_count": cv_summary.get("fold_count"),
                            "pbo_split_count": trial_counting.get("pbo_split_count"),
                        },
                        "required": {
                            "max_pbo": required.get("max_pbo", 0.50),
                            "min_validation_paths": required.get(
                                "min_validation_paths", 2
                            ),
                            "requires_grouped_out_of_sample_trials": True,
                        },
                    }
                )
            elif code == "validation_cv_method_not_allowed":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script")
                        or catalog.get("research_rerun", ""),
                        "observed": {
                            "cv_method": evidence.get("validation_cv_method", "unknown"),
                            "fold_count": cv_summary.get("fold_count"),
                            "path_count": cv_summary.get("path_count"),
                        },
                        "required": {
                            "allowed_cv_methods": required.get(
                                "allowed_cv_methods",
                                ["cpcv", "purged_kfold", "embargoed_walk_forward"],
                            ),
                        },
                    }
                )
            elif code == "validation_purge_embargo_missing":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script")
                        or catalog.get("research_rerun", ""),
                        "observed": {
                            "cv_method": evidence.get("validation_cv_method", "unknown"),
                            "purged": cv_summary.get("purged"),
                            "purge_recorded": cv_summary.get("purge_recorded"),
                            "purge_steps": cv_summary.get("purge_steps"),
                            "embargoed": cv_summary.get("embargoed"),
                            "embargo_recorded": cv_summary.get("embargo_recorded"),
                            "embargo_steps": cv_summary.get("embargo_steps"),
                        },
                        "required": {
                            "purged": True,
                            "embargoed": True,
                            "purge_embargo_recorded": True,
                            "allowed_cv_methods": required.get(
                                "allowed_cv_methods",
                                ["cpcv", "purged_kfold", "embargoed_walk_forward"],
                            ),
                        },
                    }
                )
            elif code == "missing_cpcv_evidence":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script")
                        or catalog.get("research_rerun", ""),
                        "observed": {
                            "cv_method": evidence.get("validation_cv_method", "unknown"),
                            "fold_count": cv_summary.get("fold_count"),
                            "path_count": cv_summary.get("path_count"),
                        },
                        "required": {
                            "required_cv_method": required.get("required_cv_method", "cpcv"),
                            "min_validation_paths": required.get(
                                "min_validation_paths", 2
                            ),
                        },
                    }
                )
            elif code == "single_path_validation_not_allowed":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script")
                        or catalog.get("research_rerun", ""),
                        "observed": {
                            "validation_paths": max(
                                int(cv_summary.get("path_count", 0) or 0),
                                int(cv_summary.get("fold_count", 0) or 0),
                            ),
                            "fold_count": cv_summary.get("fold_count"),
                            "path_count": cv_summary.get("path_count"),
                        },
                        "required": {
                            "min_validation_paths": required.get(
                                "min_validation_paths", 2
                            ),
                        },
                    }
                )
            elif code == "insufficient_effective_trials":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("research_rerun")
                        or catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script", ""),
                        "observed": {
                            "effective_trial_count": trial_counting.get("effective_trial_count"),
                            "independent_trial_count": trial_counting.get(
                                "independent_trial_count"
                            ),
                            "param_grid_trial_count": trial_counting.get(
                                "param_grid_trial_count"
                            ),
                            "trial_sharpe_count": trial_counting.get("trial_sharpe_count"),
                        },
                        "required": {
                            "min_effective_trial_count": required.get(
                                "min_effective_trial_count", 2
                            ),
                            "min_independent_trial_count": required.get(
                                "min_independent_trial_count", 2
                            ),
                        },
                    }
                )
            elif code == "multiple_testing_missing":
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("research_rerun")
                        or catalog.get("walk_forward_cli")
                        or catalog.get("walk_forward_script", ""),
                        "observed": {
                            "multiple_testing_mode": multiple_testing.get("mode"),
                            "effective_trial_count": multiple_testing.get(
                                "effective_trial_count"
                            ),
                            "independent_trial_count": multiple_testing.get(
                                "independent_trial_count"
                            ),
                            "raw_p_value": multiple_testing.get("raw_p_value"),
                        },
                        "required": {
                            "familywise_alpha": required.get("familywise_alpha", 0.05),
                            "requires_familywise_error_control": True,
                        },
                    }
                )
            elif code in {"lookahead_guard_missing", "lookahead_guard_failed"}:
                lookahead_controls = dict(
                    validation_stats.get("lookahead_controls", {}) or {}
                )
                detail.update(
                    {
                        "category": "validation",
                        "cli_next_command": catalog.get("research_rerun")
                        or catalog.get("walk_forward_cli")
                        or catalog.get("promotion_gate_cli", ""),
                        "observed": {
                            "recorded": lookahead_controls.get("recorded"),
                            "guard": lookahead_controls.get("guard"),
                            "violations": lookahead_controls.get("violations"),
                        },
                        "required": {
                            "lookahead_guard_recorded": True,
                            "violations": [],
                        },
                    }
                )
            elif code == "missing_monte_carlo_survival_rate":
                real_returns_ready = real_trade_returns >= 10 and real_daily_returns >= 10
                detail.update(
                    {
                        "category": "robustness",
                        "cli_next_command": (
                            catalog.get("robustness_run")
                            if real_returns_ready
                            else (
                                catalog.get("research_rerun")
                                or catalog.get("walk_forward_cli")
                                or catalog.get("promotion_gate_cli", "")
                            )
                        ),
                        "diagnostic_cli_command": catalog.get("robustness_run", ""),
                        "observed": {
                            "metric_present": evidence.get(
                                "monte_carlo_survival_rate_present", False
                            ),
                            "trade_return_count": real_trade_returns,
                            "daily_return_count": real_daily_returns,
                            "validation_status": evidence.get("validation_status", ""),
                        },
                        "required": {
                            "min_survival_rate": 0.80,
                            "requires_real_trade_returns": True,
                            "requires_real_daily_returns": True,
                        },
                        "materialization": {
                            "supported": bool(catalog.get("materialize")),
                            "command": catalog.get("materialize", ""),
                            "note": (
                                materialization_note
                                + " Current robustness CLI must not be used to pass the gate "
                                "when it would fall back to synthetic returns."
                            ),
                        },
                    }
                )
            elif code == "missing_param_stability_score":
                has_real_grid = param_grid_trial_count >= 2
                detail.update(
                    {
                        "category": "robustness",
                        "cli_next_command": (
                            (
                                catalog.get("research_rerun")
                                or catalog.get("param_stability_cli")
                            )
                            if has_real_grid
                            else (
                                catalog.get("param_stability_cli")
                                or catalog.get("promotion_gate_cli", "")
                            )
                        ),
                        "diagnostic_cli_command": catalog.get("param_stability_cli", ""),
                        "observed": {
                            "metric_present": evidence.get(
                                "param_stability_score_present", False
                            ),
                            "param_grid_trial_count": trial_counting.get(
                                "param_grid_trial_count"
                            ),
                            "base_param_count": len(
                                experiment_data.get("params", {})
                                if isinstance(experiment_data.get("params", {}), dict)
                                else {}
                            ),
                        },
                        "required": {
                            "min_stability_score": 0.50,
                            "requires_real_param_neighborhood": True,
                        },
                        "materialization": {
                            "supported": bool(catalog.get("materialize")),
                            "command": catalog.get("materialize", ""),
                            "note": (
                                materialization_note
                                + " Diagnostic param-stability CLI perturbs stored params; it "
                                "cannot by itself satisfy the promotion gate without real sweep evidence."
                            ),
                        },
                    }
                )
            else:
                detail["cli_next_command"] = (
                    catalog.get("promotion_gate_cli")
                    or catalog.get("research_rerun")
                    or ""
                )

            details.append(detail)
        return details

    def _build_command_catalog(
        self,
        *,
        candidate_id: str,
        candidate_data: dict[str, Any],
        experiment_data: dict[str, Any],
    ) -> dict[str, str]:
        symbols = candidate_data.get("symbols") or experiment_data.get("symbols") or []
        symbol = str(symbols[0]) if symbols else ""
        start = str(experiment_data.get("start_date", "") or "")
        end = str(experiment_data.get("end_date", "") or "")
        timeframe = str(experiment_data.get("timeframe", "1d") or "1d")
        strategy_id = str(
            experiment_data.get("strategy_id")
            or candidate_data.get("strategy_id")
            or "trend_momentum"
        )
        params = experiment_data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        vendor = str(
            experiment_data.get("data_source")
            or experiment_data.get("source")
            or candidate_data.get("data_source")
            or "yfinance"
        )
        experiment_id = str(experiment_data.get("experiment_id", "") or "")
        return {
            "materialize": self._build_materialization_command(candidate_id),
            "promotion_gate_cli": self._build_promotion_gate_cli_command(candidate_id),
            "walk_forward_cli": self._build_walk_forward_cli_command(experiment_id),
            "walk_forward_script": self._build_walk_forward_script_command(
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
            ),
            "research_rerun": self._build_research_rerun_command(
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
                strategy_id=strategy_id,
                params=params,
                vendor=vendor,
                experiment_id=experiment_id,
            )
            or "",
            "robustness_run": self._build_robustness_run_command(candidate_id),
            "param_stability_cli": self._build_param_stability_command(candidate_id),
        }

    def _build_materialization_command(self, candidate_id: str) -> str:
        python_snippet = (
            "from quant_us.research.automation.evidence_materializer import "
            "ResearchEvidenceMaterializer; "
            f"ResearchEvidenceMaterializer({json.dumps(str(self.data_root))})."
            f"materialize_candidate({json.dumps(candidate_id)})"
        )
        return self._shell_join(
            "PYTHONPATH=.",
            self._python_executable(),
            "-c",
            python_snippet,
        )

    def _build_promotion_gate_cli_command(self, candidate_id: str) -> str:
        return self._shell_join(
            "PYTHONPATH=.",
            self._python_executable(),
            "-m",
            "quant_us.cli",
            "research",
            "promotion-gate",
            "--candidate-id",
            candidate_id,
            "--data-root",
            str(self.data_root),
        )

    def _build_walk_forward_cli_command(self, experiment_id: str) -> str:
        if not experiment_id:
            return ""
        return self._shell_join(
            "PYTHONPATH=.",
            self._python_executable(),
            "-m",
            "quant_us.cli",
            "research",
            "walk-forward",
            "--experiment-id",
            experiment_id,
            "--data-root",
            str(self.data_root),
        )

    def _build_walk_forward_script_command(
        self,
        *,
        symbol: str,
        start: str,
        end: str,
        timeframe: str,
    ) -> str:
        if not all((symbol, start, end)):
            return ""
        return self._shell_join(
            "PYTHONPATH=.",
            self._python_executable(),
            "scripts/run_walk_forward.py",
            "--symbol",
            symbol,
            "--start",
            start,
            "--end",
            end,
            "--bar-size",
            timeframe,
            "--data-root",
            str(self.data_root),
        )

    def _build_research_rerun_command(
        self,
        *,
        symbol: str,
        start: str,
        end: str,
        timeframe: str,
        strategy_id: str,
        params: dict[str, Any],
        vendor: str,
        experiment_id: str,
    ) -> str:
        if not all((symbol, start, end, experiment_id)):
            return ""
        return self._shell_join(
            "PYTHONPATH=.",
            self._python_executable(),
            "scripts/run_research_experiment.py",
            "--experiment-name",
            f"rerun-{experiment_id}",
            "--symbols",
            symbol,
            "--start",
            start,
            "--end",
            end,
            "--strategy-id",
            strategy_id,
            "--strategy-params-json",
            json.dumps(params, sort_keys=True),
            "--bar-size",
            timeframe,
            "--data-root",
            str(self.data_root),
            "--vendor",
            vendor,
        )

    def _build_robustness_run_command(self, candidate_id: str) -> str:
        return self._shell_join(
            "PYTHONPATH=.",
            self._python_executable(),
            "-m",
            "quant_us.cli",
            "research",
            "robustness-run",
            "--strategy-manifest",
            candidate_id,
            "--n-simulations",
            "500",
            "--data-root",
            str(self.data_root),
        )

    def _build_param_stability_command(self, candidate_id: str) -> str:
        return self._shell_join(
            "PYTHONPATH=.",
            self._python_executable(),
            "-m",
            "quant_us.cli",
            "research",
            "param-stability",
            "--strategy-manifest",
            candidate_id,
            "--data-root",
            str(self.data_root),
        )

    @staticmethod
    def _reason_code(reason: str) -> str:
        return str(reason).split(":", 1)[0]

    @staticmethod
    def _series_length(raw: Any) -> int:
        if not isinstance(raw, list):
            return 0
        return sum(1 for item in raw if isinstance(item, (int, float)))

    @staticmethod
    def _shell_join(*parts: str) -> str:
        rendered: list[str] = []
        for index, part in enumerate(parts):
            text = str(part)
            if not text:
                continue
            if index == 0 and "=" in text and " " not in text:
                rendered.append(text)
            else:
                rendered.append(shlex.quote(text))
        return " ".join(rendered)

    @staticmethod
    def _python_executable() -> str:
        venv_python = Path("venv/bin/python")
        return str(venv_python) if venv_python.exists() else "python"

    @staticmethod
    def _source_from_data_version(data_version: str) -> str:
        normalized = data_version.lower()
        for source in (*ALLOWED_DATA_SOURCES, "fixture"):
            if source in normalized:
                return source
        return ""

    @staticmethod
    def _asset_class(symbols: list[str]) -> str:
        if any(symbol.endswith(CRYPTO_SYMBOL_SUFFIXES) for symbol in symbols):
            return "crypto"
        return "equity"

    @staticmethod
    def _as_pct(value: Any) -> float:
        pct = float(value)
        if 0.0 <= pct <= 1.0:
            return pct * 100.0
        return pct
