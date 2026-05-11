"""Materialize canonical research evidence for strategy candidates.

This module links the research lab's candidate JSON to the promotion gate's
canonical file layout. It only persists evidence that can be derived from
existing experiment/candidate artifacts; it does not make a weak candidate pass.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now


@dataclass
class CandidateEvidenceMaterializationResult:
    """Outcome of materializing one candidate's promotion evidence."""

    candidate_id: str
    backtest_manifest_path: str = ""
    scorecard_path: str = ""
    walk_forward_result_path: str = ""
    cost_stress_result_path: str = ""
    strategy_manifest_id: str = ""
    strategy_manifest_status: str = ""
    promotion_gate_decision: str = "NOT_RUN"
    promotion_gate_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    paths_written: list[str] = field(default_factory=list)

    @property
    def passed_basic_materialization(self) -> bool:
        return bool(self.backtest_manifest_path and self.scorecard_path)


class ResearchEvidenceMaterializer:
    """Create canonical candidate evidence files for promotion review.

    Promotion gates require stable files under:
        data/research/backtests/<candidate_id>/run_manifest.json
        data/research/scorecards/<candidate_id>.json
        data/research/walk_forward/<candidate_id>/result.json
        data/research/cost_stress/<candidate_id>/result.json

    Missing walk-forward or cost-stress metrics remain missing; the materializer
    records a warning instead of inventing a positive result.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def materialize_candidate(
        self,
        candidate_id: str,
        *,
        create_strategy_manifest: bool = True,
        run_promotion_gate: bool = True,
    ) -> CandidateEvidenceMaterializationResult:
        """Materialize all available evidence for one candidate."""
        result = CandidateEvidenceMaterializationResult(candidate_id=candidate_id)
        candidate = self._load_candidate(candidate_id)
        metrics = candidate.get("metrics", {}) if isinstance(candidate, dict) else {}
        if not isinstance(metrics, dict):
            metrics = {}

        backtest_path = self._materialize_backtest_manifest(
            candidate_id=candidate_id,
            candidate=candidate,
            result=result,
        )
        if backtest_path:
            result.backtest_manifest_path = backtest_path

        scorecard_path = self._materialize_scorecard(candidate_id, result)
        if scorecard_path:
            result.scorecard_path = scorecard_path

        walk_forward_path = self._materialize_walk_forward(
            candidate_id=candidate_id,
            metrics=metrics,
            result=result,
        )
        if walk_forward_path:
            result.walk_forward_result_path = walk_forward_path

        cost_stress_path = self._materialize_cost_stress(
            candidate_id=candidate_id,
            metrics=metrics,
            result=result,
        )
        if cost_stress_path:
            result.cost_stress_result_path = cost_stress_path

        self._update_candidate(candidate_id, result)

        if create_strategy_manifest:
            self._ensure_strategy_manifest(candidate_id, result)

        if run_promotion_gate:
            self._run_promotion_gate(candidate_id, result)

        self._persist_result(result)
        return result

    def materialize_many(
        self,
        candidate_ids: list[str],
        *,
        create_strategy_manifest: bool = True,
        run_promotion_gate: bool = True,
    ) -> dict[str, CandidateEvidenceMaterializationResult]:
        """Materialize evidence for several candidates."""
        return {
            candidate_id: self.materialize_candidate(
                candidate_id,
                create_strategy_manifest=create_strategy_manifest,
                run_promotion_gate=run_promotion_gate,
            )
            for candidate_id in candidate_ids
        }

    def _materialize_backtest_manifest(
        self,
        *,
        candidate_id: str,
        candidate: dict[str, Any],
        result: CandidateEvidenceMaterializationResult,
    ) -> str:
        canonical_path = self._canonical_backtest_manifest_path(candidate_id)
        existing_raw = str(candidate.get("backtest_manifest_path", "") or "")
        existing_path = self._resolve_path(existing_raw)
        if existing_path is not None and self._same_path(existing_path, canonical_path):
            if existing_path.exists():
                return str(canonical_path)
            result.warnings.append(
                f"backtest_manifest_missing: canonical path does not exist: {canonical_path}"
            )

        source_path = self._first_existing_path(
            [
                existing_raw,
                str((candidate.get("metrics", {}) or {}).get("backtest_manifest_path", "") or ""),
                str((candidate.get("metrics", {}) or {}).get("source_backtest_manifest_path", "") or ""),
            ]
        )
        if source_path is None:
            result.warnings.append("backtest_manifest_source_missing")
            return ""

        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            result.warnings.append("backtest_manifest_source_invalid")
            return ""

        payload.update(
            {
                "candidate_id": candidate_id,
                "experiment_id": str(candidate.get("experiment_id", "")),
                "strategy_id": str(candidate.get("strategy_id", "")),
                "source_run_manifest_path": str(source_path),
                "canonical_backtest_manifest_path": str(canonical_path),
            }
        )
        payload.setdefault("canonical_for_promotion", True)

        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        result.paths_written.append(str(canonical_path))
        return str(canonical_path)

    def _materialize_scorecard(
        self,
        candidate_id: str,
        result: CandidateEvidenceMaterializationResult,
    ) -> str:
        try:
            from quant_us.research.lab.scorecard import ResearchScorecardBuilder

            scorecard = ResearchScorecardBuilder(data_root=str(self.data_root)).build(
                candidate_id
            )
        except Exception as exc:
            result.warnings.append(f"scorecard_build_failed: {exc}")
            return ""
        path = self.data_root / "research" / "scorecards" / f"{candidate_id}.json"
        if path.exists():
            result.paths_written.append(str(path))
        self._merge_candidate_metrics(
            candidate_id,
            {
                "robustness_score": float(scorecard.robustness_score),
                "walk_forward_pass_rate": float(scorecard.walk_forward_pass_rate),
                "cost_sensitivity": float(scorecard.cost_sensitivity),
                "scorecard_path": str(path),
            },
        )
        return str(path)

    def _materialize_walk_forward(
        self,
        *,
        candidate_id: str,
        metrics: dict[str, Any],
        result: CandidateEvidenceMaterializationResult,
    ) -> str:
        if "walk_forward_pass_rate" not in metrics:
            result.warnings.append("walk_forward_metrics_missing")
            return ""

        pass_rate = float(metrics.get("walk_forward_pass_rate", 0.0))
        payload = {
            "schema_version": "research_walk_forward_result_v1",
            "candidate_id": candidate_id,
            "status": "completed",
            "generated_at": utc_now().isoformat(),
            "walk_forward_pass_rate": pass_rate,
            "pass_rate": pass_rate,
            "fold_sharpes": list(metrics.get("wf_fold_sharpes", []) or []),
            "fold_drawdowns": list(metrics.get("wf_fold_drawdowns", []) or []),
            "metrics": {
                "walk_forward_pass_rate": pass_rate,
                "oos_degradation": float(metrics.get("oos_degradation", 0.0) or 0.0),
            },
        }
        path = self._canonical_research_artifact_path(candidate_id, "walk_forward")
        self._write_json(path, payload)
        result.paths_written.append(str(path))
        return str(path)

    def _materialize_cost_stress(
        self,
        *,
        candidate_id: str,
        metrics: dict[str, Any],
        result: CandidateEvidenceMaterializationResult,
    ) -> str:
        has_stress_evidence = any(
            key in metrics
            for key in (
                "stress_survival_rate",
                "cost_stress_levels",
                "cost_stress_result",
                "cost_stress",
            )
        )
        if not has_stress_evidence:
            result.warnings.append("cost_stress_metrics_missing")
            return ""

        stress_survival_rate = float(metrics.get("stress_survival_rate", 0.0) or 0.0)
        cost_sensitivity = float(metrics.get("cost_sensitivity", 0.0) or 0.0)
        payload = {
            "schema_version": "research_cost_stress_result_v1",
            "candidate_id": candidate_id,
            "status": "completed",
            "generated_at": utc_now().isoformat(),
            "stress_survival_rate": stress_survival_rate,
            "survival_rate": stress_survival_rate,
            "cost_sensitivity": cost_sensitivity,
            "levels": list(metrics.get("cost_stress_levels", []) or []),
            "metrics": {
                "stress_survival_rate": stress_survival_rate,
                "cost_sensitivity": cost_sensitivity,
            },
        }
        path = self._canonical_research_artifact_path(candidate_id, "cost_stress")
        self._write_json(path, payload)
        result.paths_written.append(str(path))
        return str(path)

    def _ensure_strategy_manifest(
        self,
        candidate_id: str,
        result: CandidateEvidenceMaterializationResult,
    ) -> None:
        try:
            from quant_us.research.strategy_manifest import StrategyManifestManager

            manager = StrategyManifestManager(data_root=str(self.data_root))
            manifest = manager.create_from_candidate(candidate_id)
            result.strategy_manifest_id = manifest.strategy_candidate_id
            result.strategy_manifest_status = manifest.promotion_status
            return
        except Exception as exc:
            result.warnings.append(f"strategy_manifest_blocked: {exc}")

        manifest = self._find_strategy_manifest(candidate_id)
        if manifest is not None:
            result.strategy_manifest_id = str(manifest.get("strategy_candidate_id", ""))
            result.strategy_manifest_status = str(manifest.get("promotion_status", ""))

    def _run_promotion_gate(
        self,
        candidate_id: str,
        result: CandidateEvidenceMaterializationResult,
    ) -> None:
        try:
            from quant_us.research.automation.promotion_gate import ResearchPromotionGate

            gate_result = ResearchPromotionGate(data_root=str(self.data_root)).evaluate(
                candidate_id
            )
        except Exception as exc:
            result.promotion_gate_decision = "BLOCKED"
            result.promotion_gate_reasons.append(f"promotion_gate_error: {exc}")
            return

        result.promotion_gate_decision = gate_result.decision
        result.promotion_gate_reasons = list(gate_result.reasons)
        result.warnings.extend(gate_result.warnings)

    def _update_candidate(
        self,
        candidate_id: str,
        result: CandidateEvidenceMaterializationResult,
    ) -> None:
        path = self._candidate_path(candidate_id)
        if not path.exists():
            return
        candidate = json.loads(path.read_text(encoding="utf-8"))
        metrics = candidate.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}

        updates = {
            "backtest_manifest_path": result.backtest_manifest_path,
            "scorecard_path": result.scorecard_path,
            "walk_forward_result_path": result.walk_forward_result_path,
            "cost_stress_result_path": result.cost_stress_result_path,
        }
        for key, value in updates.items():
            if value:
                candidate[key] = value
                metrics[key] = value
        candidate["metrics"] = metrics
        path.write_text(json.dumps(candidate, indent=2, default=str), encoding="utf-8")

    def _merge_candidate_metrics(
        self,
        candidate_id: str,
        values: dict[str, Any],
    ) -> None:
        path = self._candidate_path(candidate_id)
        if not path.exists():
            return
        candidate = json.loads(path.read_text(encoding="utf-8"))
        metrics = candidate.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
        metrics.update(values)
        candidate["metrics"] = metrics
        for key in ("robustness_score", "scorecard_path"):
            if key in values:
                candidate[key] = values[key]
        path.write_text(json.dumps(candidate, indent=2, default=str), encoding="utf-8")

    def _persist_result(
        self,
        result: CandidateEvidenceMaterializationResult,
    ) -> None:
        path = (
            self.data_root
            / "research"
            / "evidence_materialization"
            / result.candidate_id
            / "result.json"
        )
        self._write_json(path, asdict(result))

    def _load_candidate(self, candidate_id: str) -> dict[str, Any]:
        path = self._candidate_path(candidate_id)
        if not path.exists():
            raise ValueError(f"Candidate {candidate_id} not found")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Candidate {candidate_id} JSON is not an object")
        return payload

    def _find_strategy_manifest(self, candidate_id: str) -> dict[str, Any] | None:
        manifests_dir = self.data_root / "research" / "manifests"
        if not manifests_dir.exists():
            return None
        for path in sorted(manifests_dir.glob("*/manifest.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("source_candidate_id") == candidate_id:
                return payload
        return None

    def _first_existing_path(self, candidates: list[str]) -> Path | None:
        for raw_path in candidates:
            path = self._resolve_path(raw_path)
            if path is not None and path.exists():
                return path
        return None

    def _resolve_path(self, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.data_root / path

    def _candidate_path(self, candidate_id: str) -> Path:
        return (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )

    def _canonical_backtest_manifest_path(self, candidate_id: str) -> Path:
        return (
            self.data_root
            / "research"
            / "backtests"
            / candidate_id
            / "run_manifest.json"
        )

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

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        return left.resolve(strict=False) == right.resolve(strict=False)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
