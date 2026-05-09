"""Research automation pipeline.

Automates the full research workflow:
1. Load strategy templates
2. Generate parameter grids
3. Run batch backtests
4. Run walk-forward
5. Run cost stress
6. Run regime split
7. Compute scorecards
8. Rank candidates
9. Reject overfit
10. Run promotion gate and identify paper-review-ready candidates
11. Generate dossier

NEVER auto-promotes to paper trading or live. PAPER_ELIGIBLE remains a manual
status change.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.research.automation.dossier import ResearchDossierBuilder
from quant_us.research.automation.overfit import OverfitDetector
from quant_us.research.automation.ranking import CandidateRankingEngine
from quant_us.research.lab.manifest import ExperimentManager, StrategyCandidate


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    pipeline_id: str
    experiment_ids: list[str]
    candidate_ids: list[str]
    ranked_candidates: list[tuple[str, float, dict]]
    overfit_reports: dict[str, Any]
    promotion_gate_results: dict[str, Any]
    required_stages: dict[str, Any]
    paper_review_ready: list[str]
    dossier_paths: dict[str, str]
    report_paths: dict[str, str]
    promoted: list[str]
    status: str = "completed"
    created_at: str = ""
    error: str | None = None


class ResearchAutomationPipeline:
    """Automated research pipeline orchestrating the full workflow.

    Steps:
    1. load strategy templates
    2. generate parameter grids
    3. run batch backtests
    4. run walk-forward
    5. run cost stress
    6. run regime split
    7. compute scorecards
    8. rank candidates
    9. reject overfit
    10. run promotion gate; ready candidates require human paper review
    11. generate dossier

    Never auto-promotes to paper trading or live. Max automatic action is a
    paper-review-ready list in the pipeline result; PAPER_ELIGIBLE is manual.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self._exp_mgr = ExperimentManager(data_root=str(self.data_root))
        self._ranker = CandidateRankingEngine(data_root=str(self.data_root))
        self._overfit = OverfitDetector(data_root=str(self.data_root))
        self._dossier = ResearchDossierBuilder(data_root=str(self.data_root))

    def run(self, config: dict) -> dict:
        """Run the full research automation pipeline.

        Args:
            config: Pipeline configuration dict with keys:
                - experiment_name (str)
                - strategy_id (str)
                - symbols (list[str])
                - params (dict): base parameters
                - param_grid (dict): parameter grid for sweeps
                - start_date (str)
                - end_date (str)
                - data_version (str, optional)
                - feature_version (str, optional)

        Returns:
            PipelineResult as dict.
        """
        pipeline_id = new_id("pipe")
        created_at = utc_now().isoformat()

        try:
            # Step 1-2: Create experiments from templates/grids
            experiment_ids = self._create_experiments(config)

            # Step 3: Run batch backtests
            for eid in experiment_ids:
                self._exp_mgr.run(eid)

            # Steps 4-6: Walk-forward, cost stress, regime split (modeled as
            # additional experiments with same strategy, different params)
            wf_ids = self._run_walk_forward(config)
            experiment_ids.extend(wf_ids)

            cost_ids = self._run_cost_stress(config)
            experiment_ids.extend(cost_ids)

            regime_ids = self._run_regime_split(config)
            experiment_ids.extend(regime_ids)
            required_stages = self._required_stage_status(
                {
                    "walk_forward": wf_ids,
                    "cost_stress": cost_ids,
                    "regime_split": regime_ids,
                }
            )

            # Step 7: Compute scorecards and promote completed experiments
            candidate_ids: list[str] = []
            for eid in experiment_ids:
                manifest = self._exp_mgr.load(eid)
                if manifest and manifest.status == "COMPLETED":
                    candidate = self._exp_mgr.promote_to_candidate(eid)
                    candidate_ids.append(candidate.candidate_id)

            # Step 8: Rank candidates
            ranked = self._ranker.rank(candidate_ids)

            # Step 9: Reject overfit
            overfit_reports: dict[str, Any] = {}
            clean_candidate_ids = list(candidate_ids)
            for cid in candidate_ids:
                report = self._overfit.check(cid)
                overfit_reports[cid] = asdict(report)
                if report.is_overfit:
                    # Mark as rejected — not removed from registry
                    self._mark_rejected(cid)
                    if cid in clean_candidate_ids:
                        clean_candidate_ids.remove(cid)

            # Step 10: Gate clean candidates for human paper-review readiness.
            promotion_gate_results: dict[str, Any] = {}
            for cid in clean_candidate_ids:
                promotion_gate_results[cid] = self._evaluate_promotion_gate(cid)

            # Step 11: Generate dossiers
            dossier_paths: dict[str, str] = {}
            for cid in clean_candidate_ids:
                dossier_paths[cid] = self._dossier.build(cid)

            report_paths = self._generate_promotion_reports(experiment_ids)
            required_stages["promotion_report"] = {
                "passed": bool(report_paths),
                "report_count": len(report_paths),
                "paths": report_paths,
            }

            required_stages_passed = all(
                bool(stage.get("passed")) for stage in required_stages.values()
            )
            paper_review_ready = [
                cid
                for cid, gate in promotion_gate_results.items()
                if required_stages_passed
                and gate.get("decision") == "READY_FOR_PAPER_REVIEW"
            ]

            result = PipelineResult(
                pipeline_id=pipeline_id,
                experiment_ids=experiment_ids,
                candidate_ids=candidate_ids,
                ranked_candidates=ranked,
                overfit_reports=overfit_reports,
                promotion_gate_results=promotion_gate_results,
                required_stages=required_stages,
                paper_review_ready=paper_review_ready,
                dossier_paths=dossier_paths,
                report_paths=report_paths,
                promoted=paper_review_ready,
                status="completed",
                created_at=created_at,
            )
            self._save_pipeline_result(result)
            return asdict(result)

        except Exception as exc:
            result = PipelineResult(
                pipeline_id=pipeline_id,
                experiment_ids=[],
                candidate_ids=[],
                ranked_candidates=[],
                overfit_reports={},
                promotion_gate_results={},
                required_stages={},
                paper_review_ready=[],
                dossier_paths={},
                report_paths={},
                promoted=[],
                status="failed",
                created_at=created_at,
                error=str(exc),
            )
            self._save_pipeline_result(result)
            return asdict(result)

    def step_evaluate(self, experiment_id: str) -> dict:
        """Evaluate a single experiment and return its scorecard metrics.

        Args:
            experiment_id: The experiment to evaluate.

        Returns:
            Dict of metrics from the experiment's run result.
        """
        manifest = self._exp_mgr.load(experiment_id)
        if manifest is None:
            raise ValueError(f"Experiment {experiment_id} not found")
        return dict(manifest.metrics)

    def step_rank(self) -> list:
        """Rank all current candidates and return sorted list.

        Returns:
            List of (candidate_id, total_score, breakdown) sorted by score descending.
        """
        candidates = self._exp_mgr.list_candidates()
        candidate_ids = [c.candidate_id for c in candidates]
        return self._ranker.rank(candidate_ids)

    def step_promote(
        self,
        candidate_id: str,
        *,
        manual_approval: bool = False,
    ) -> StrategyCandidate:
        """Manually promote a candidate to PAPER_ELIGIBLE.

        This is a controlled manual action. The candidate must still pass the
        canonical promotion gate, and promotion additionally requires either an
        approved paper review or an explicit manual approval flag from the
        caller.

        Args:
            candidate_id: The candidate to promote.
            manual_approval: Explicit human approval to allow the status change
                after the canonical gate passes, even if no approved paper
                review has been persisted yet.

        Returns:
            The updated StrategyCandidate.

        Raises:
            ValueError: If candidate not found or already at max status.
        """
        candidates = self._exp_mgr.list_candidates()
        target = None
        for c in candidates:
            if c.candidate_id == candidate_id:
                target = c
                break

        if target is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        if target.promotion_status == "PAPER_ELIGIBLE":
            raise ValueError(
                f"Candidate {candidate_id} is already PAPER_ELIGIBLE. "
                "Cannot promote past PAPER_ELIGIBLE via research automation."
            )

        if target.promotion_status == "REJECTED":
            raise ValueError(
                f"Candidate {candidate_id} is REJECTED and cannot be promoted."
            )

        gate_result = self._evaluate_promotion_gate(candidate_id)
        gate_decision = str(gate_result.get("decision", "BLOCKED"))
        if gate_decision != "READY_FOR_PAPER_REVIEW":
            raise ValueError(
                f"Candidate {candidate_id} did not pass the canonical promotion "
                f"gate (decision={gate_decision}). PAPER_ELIGIBLE requires "
                "READY_FOR_PAPER_REVIEW."
            )

        if not manual_approval and not self._has_approved_paper_review(candidate_id):
            raise ValueError(
                f"Candidate {candidate_id} requires an APPROVED_FOR_PAPER_ONLY "
                "paper review or explicit manual_approval=True before "
                "PAPER_ELIGIBLE promotion."
            )

        self._mark_paper_eligible(candidate_id)

        # Reload and return
        for c in self._exp_mgr.list_candidates():
            if c.candidate_id == candidate_id:
                return c

        return target

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_experiments(self, config: dict) -> list[str]:
        """Create experiments from config. Supports parameter grids."""
        experiment_ids: list[str] = []
        strategy_id = config.get("strategy_id", "unknown")
        symbols = config.get("symbols", [])
        param_grid = config.get("param_grid", {})

        # Expand parameter grid
        if param_grid:
            from itertools import product

            keys = list(param_grid)
            values = [
                v if isinstance(v, list) else [v] for v in param_grid.values()
            ]
            for items in product(*values):
                params = dict(zip(keys, items))
                manifest = self._exp_mgr.create(
                    strategy_id=strategy_id,
                    symbols=symbols,
                    params=params,
                    start_date=config.get("start_date", ""),
                    end_date=config.get("end_date", ""),
                    data_version=config.get("data_version", ""),
                    feature_version=config.get("feature_version", ""),
                    param_grid=param_grid,
                    strategy_family=config.get("experiment_name", ""),
                )
                experiment_ids.append(manifest.experiment_id)
        else:
            manifest = self._exp_mgr.create(
                strategy_id=strategy_id,
                symbols=symbols,
                params=config.get("params", {}),
                start_date=config.get("start_date", ""),
                end_date=config.get("end_date", ""),
                data_version=config.get("data_version", ""),
                feature_version=config.get("feature_version", ""),
                strategy_family=config.get("experiment_name", ""),
            )
            experiment_ids.append(manifest.experiment_id)

        return experiment_ids

    def _run_walk_forward(self, config: dict) -> list[str]:
        """Run walk-forward analysis by creating train/test period experiments."""
        ids: list[str] = []
        start = config.get("start_date", "2020-01-01")
        end = config.get("end_date", "2024-12-31")

        # Split into two periods for walk-forward
        mid = _mid_date(start, end)
        periods = [(start, mid), (mid, end)]

        for period_start, period_end in periods:
            manifest = self._exp_mgr.create(
                strategy_id=config.get("strategy_id", "unknown"),
                symbols=config.get("symbols", []),
                params=config.get("params", {}),
                start_date=period_start,
                end_date=period_end,
                data_version=config.get("data_version", ""),
                feature_version=config.get("feature_version", ""),
                strategy_family=f"walk_forward_{config.get('experiment_name', '')}",
                walk_forward_config={"fold": period_start, "period": f"{period_start}_{period_end}"},
            )
            try:
                self._exp_mgr.run(manifest.experiment_id)
                ids.append(manifest.experiment_id)
            except Exception:
                # Continue even if one fold fails
                ids.append(manifest.experiment_id)

        return ids

    def _run_cost_stress(self, config: dict) -> list[str]:
        """Run cost stress analysis — models cost sensitivity."""
        stress_configs = [
            {"cost_model": "high", "slippage_model": "high"},
            {"cost_model": "low", "slippage_model": "low"},
        ]
        ids: list[str] = []
        for stress in stress_configs:
            manifest = self._exp_mgr.create(
                strategy_id=config.get("strategy_id", "unknown"),
                symbols=config.get("symbols", []),
                params={**config.get("params", {}), **stress},
                start_date=config.get("start_date", ""),
                end_date=config.get("end_date", ""),
                data_version=config.get("data_version", ""),
                feature_version=config.get("feature_version", ""),
                strategy_family=f"cost_stress_{config.get('experiment_name', '')}",
            )
            try:
                self._exp_mgr.run(manifest.experiment_id)
                ids.append(manifest.experiment_id)
            except Exception:
                ids.append(manifest.experiment_id)
        return ids

    def _run_regime_split(self, config: dict) -> list[str]:
        """Run regime-split analysis."""
        ids: list[str] = []
        regimes = ["bull", "bear", "sideways"]
        for regime in regimes:
            manifest = self._exp_mgr.create(
                strategy_id=config.get("strategy_id", "unknown"),
                symbols=config.get("symbols", []),
                params={**config.get("params", {}), "regime_filter": regime},
                start_date=config.get("start_date", ""),
                end_date=config.get("end_date", ""),
                data_version=config.get("data_version", ""),
                feature_version=config.get("feature_version", ""),
                strategy_family=f"regime_split_{regime}_{config.get('experiment_name', '')}",
            )
            try:
                self._exp_mgr.run(manifest.experiment_id)
                ids.append(manifest.experiment_id)
            except Exception:
                ids.append(manifest.experiment_id)
        return ids

    def _mark_paper_eligible(self, candidate_id: str) -> None:
        """Mark a candidate as PAPER_ELIGIBLE in its persisted file."""
        path = (
            self.data_root / "research" / "candidates" / candidate_id / "candidate.json"
        )
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["promotion_status"] = "PAPER_ELIGIBLE"
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _has_approved_paper_review(self, candidate_id: str) -> bool:
        """Return True when the candidate has an approved human paper review."""
        linked_ids = {candidate_id}

        manifests_dir = self.data_root / "research" / "manifests"
        if manifests_dir.exists():
            for manifest_path in sorted(manifests_dir.glob("*/manifest.json")):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("source_candidate_id") != candidate_id:
                    continue
                manifest_id = str(manifest.get("strategy_candidate_id", "")).strip()
                if manifest_id:
                    linked_ids.add(manifest_id)

        reviews_dir = self.data_root / "research" / "paper_reviews"
        if not reviews_dir.exists():
            return False

        for review_path in sorted(reviews_dir.glob("*/review.json")):
            review = json.loads(review_path.read_text(encoding="utf-8"))
            if str(review.get("status", "")) != "APPROVED_FOR_PAPER_ONLY":
                continue
            strategy_manifest_id = str(review.get("strategy_manifest_id", "")).strip()
            if strategy_manifest_id in linked_ids:
                return True

        return False

    def _mark_rejected(self, candidate_id: str) -> None:
        """Mark a candidate as REJECTED due to overfit."""
        path = (
            self.data_root / "research" / "candidates" / candidate_id / "candidate.json"
        )
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["promotion_status"] = "REJECTED"
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _required_stage_status(
        self,
        stage_ids: dict[str, list[str]],
    ) -> dict[str, Any]:
        """Return pass/fail evidence for mandatory robustness stages."""
        status: dict[str, Any] = {}
        for stage, experiment_ids in stage_ids.items():
            completed: list[str] = []
            incomplete: list[str] = []
            for experiment_id in experiment_ids:
                manifest = self._exp_mgr.load(experiment_id)
                if manifest and manifest.status == "COMPLETED":
                    completed.append(experiment_id)
                else:
                    incomplete.append(experiment_id)
            status[stage] = {
                "passed": bool(experiment_ids) and not incomplete,
                "experiment_ids": experiment_ids,
                "completed": completed,
                "incomplete": incomplete,
            }
        return status

    def _evaluate_promotion_gate(self, candidate_id: str) -> dict[str, Any]:
        """Run the canonical promotion gate for one candidate."""
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        try:
            result = ResearchPromotionGate(data_root=str(self.data_root)).evaluate(
                candidate_id
            )
            return {
                "decision": result.decision,
                "reasons": result.reasons,
                "warnings": result.warnings,
                "needs_more_research": result.needs_more_research,
                "evidence": result.evidence,
            }
        except Exception as exc:
            return {
                "decision": "BLOCKED",
                "reasons": [f"promotion_gate_error: {exc}"],
                "warnings": [],
                "needs_more_research": [],
                "evidence": {},
            }

    def _generate_promotion_reports(self, experiment_ids: list[str]) -> dict[str, str]:
        """Generate v2 reports so promotion decisions are reviewable."""
        from quant_us.research.automation.report_gen import generate_v2

        reports_dir = self.data_root / "research" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {}
        for experiment_id in experiment_ids:
            try:
                content = generate_v2(experiment_id, data_root=str(self.data_root))
            except Exception:
                continue
            path = reports_dir / f"{experiment_id}_promotion_report.md"
            path.write_text(content, encoding="utf-8")
            paths[experiment_id] = str(path)
        return paths

    def _save_pipeline_result(self, result: PipelineResult) -> None:
        """Persist the pipeline result as JSON."""
        results_dir = self.data_root / "research" / "pipeline_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        path = results_dir / f"{result.pipeline_id}.json"
        path.write_text(
            json.dumps(asdict(result), indent=2, default=str), encoding="utf-8"
        )


def _mid_date(start: str, end: str) -> str:
    """Compute approximate midpoint date between two date strings."""
    try:
        s = datetime.strptime(start[:10], "%Y-%m-%d")
        e = datetime.strptime(end[:10], "%Y-%m-%d")
        mid = s + (e - s) / 2
        return mid.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "2022-06-30"
