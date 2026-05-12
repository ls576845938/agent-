"""Strategy Candidate Manifest.

Freezes a research candidate's params after it passes the ResearchPromotionGate.
Creates a sealed manifest that can feed into portfolio simulation and paper review.
NEVER triggers trading of any kind.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.research.validation import summarize_candidate_validation


@dataclass
class StrategyCandidateManifest:
    """A sealed manifest created from a research candidate that passed the promotion gate.

    Once created, params are frozen (params_frozen=True). This manifest is the
    authoritative reference for portfolio simulation and paper review.
    """

    strategy_candidate_id: str  # maps to StrategyCandidate.candidate_id
    source_candidate_id: str
    source_experiment_id: str
    lineage_id: str = ""
    feature_snapshot_ids: list[str] = field(default_factory=list)
    strategy_template: str = ""  # e.g. "momentum", "etf_rotation"
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "1d"
    expected_holding_period: str = ""
    scorecard: dict = field(default_factory=dict)
    robustness_score: float = 0.0
    walk_forward_score: float = 0.0
    overfit_risk: str = "UNKNOWN"
    promotion_status: str = "DRAFT"
    # DRAFT|READY_FOR_PORTFOLIO_SIM|BLOCKED|PAPER_REVIEW_CANDIDATE|REJECTED
    data_version: str = ""
    data_manifest_path: str = ""
    backtest_manifest_path: str = ""
    scorecard_path: str = ""
    walk_forward_result_path: str = ""
    cost_stress_result_path: str = ""
    sample_window: dict[str, Any] = field(default_factory=dict)
    purge_embargo: dict[str, Any] = field(default_factory=dict)
    trial_id: str = ""
    trial_count: int = 0
    pbo: float | None = None
    dsr: float | None = None
    cpcv: dict[str, Any] = field(default_factory=dict)
    cost_stress: dict[str, Any] = field(default_factory=dict)
    style_exposure: dict[str, Any] = field(default_factory=dict)
    cost_model: dict[str, Any] = field(default_factory=dict)
    slippage_model: dict[str, Any] = field(default_factory=dict)
    capacity: dict[str, Any] = field(default_factory=dict)
    turnover: dict[str, Any] = field(default_factory=dict)
    holding_period: dict[str, Any] = field(default_factory=dict)
    exposure_limits: dict[str, Any] = field(default_factory=dict)
    failure_conditions: list[str] = field(default_factory=list)
    delisting_conditions: dict[str, Any] = field(default_factory=dict)
    contract_missing_reasons: dict[str, str] = field(default_factory=dict)
    promotion_result_path: str = ""
    promotion_gate_decision: str = ""
    promotion_gate_blocking_reasons: list[str] = field(default_factory=list)
    promotion_gate_blocker_details: list[dict[str, Any]] = field(default_factory=list)
    promotion_gate_warning_reasons: list[str] = field(default_factory=list)
    promotion_gate_needs_more_research: list[str] = field(default_factory=list)
    promotion_gate_next_commands: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    paper_review_evidence_required: bool = True
    portfolio_evidence_pack_id: str = ""
    portfolio_evidence_pack_path: str = ""
    paper_review_gate_status: str = ""
    paper_review_evidence_pack_path: str = ""
    paper_review_candidate_path: str = ""
    paper_review_candidate_status: str = ""
    paper_review_blocking_reasons: list[str] = field(default_factory=list)
    paper_review_id: str = ""
    created_at: str = ""
    params_frozen: bool = False  # True once manifest is created, params locked


class StrategyManifestManager:
    """Manages the lifecycle of StrategyCandidateManifests.

    Persists manifests as JSON under: data/research/manifests/<manifest_id>/manifest.json
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.manifests_dir = self.data_root / "research" / "manifests"
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def create_from_candidate(self, candidate_id: str) -> StrategyCandidateManifest:
        """Create a strategy manifest from a candidate that passed ResearchPromotionGate.

        Steps:
          1. Load the candidate via ExperimentManager.
          2. Verify the candidate exists.
          3. Evaluate the PromotionGate to ensure READY_FOR_PAPER_REVIEW.
          4. Build and persist the manifest with frozen params.

        Args:
            candidate_id: The StrategyCandidate.candidate_id to manifest.

        Returns:
            The newly created StrategyCandidateManifest.

        Raises:
            ValueError: If candidate not found, or gate did not pass,
                        or manifest already exists for this candidate.
        """
        candidate_data = self._load_raw_candidate(candidate_id)
        if candidate_data is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        # Check if manifest already exists for this candidate.
        existing = self._find_by_source_candidate(candidate_id)
        if existing is not None and existing.promotion_status not in {"DRAFT", "BLOCKED"}:
            raise ValueError(
                f"Manifest already exists for candidate {candidate_id}: "
                f"{existing.strategy_candidate_id}"
            )

        # Build lineage info
        experiment_id = str(candidate_data.get("experiment_id", ""))
        experiment = self._load_raw_experiment(experiment_id)
        source_candidate_id_for_lineage = str(
            candidate_data.get("parent_candidate_id", "") or ""
        )

        manifest = existing or StrategyCandidateManifest(
            strategy_candidate_id=new_id("sman"),
            source_candidate_id=candidate_id,
            source_experiment_id=experiment_id,
            lineage_id=source_candidate_id_for_lineage,
            strategy_template=(
                str(experiment.get("strategy_family", ""))
                if experiment and experiment.get("strategy_family", "")
                else ""
            ),
            params=dict(candidate_data.get("metrics", {}) or {}),
            symbols=list(experiment.get("symbols", [])) if experiment else [],
            timeframe=str(experiment.get("timeframe", "1d")) if experiment else "1d",
            params_frozen=True,
            promotion_status="DRAFT",
            created_at=utc_now().isoformat(),
        )
        self._bind_candidate_evidence(manifest, candidate_id)
        self._save_manifest(manifest)

        # Evaluate promotion gate after the draft manifest exists; the gate is
        # the final authority and requires this manifest as canonical evidence.
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        gate = ResearchPromotionGate(data_root=str(self.data_root))
        gate_result = gate.evaluate(candidate_id)

        manifest.promotion_result_path = str(
            gate_result.evidence.get("promotion_result_path", "")
        )
        self._bind_gate_evidence(manifest, gate_result, candidate_data)
        if gate_result.decision != "READY_FOR_PAPER_REVIEW":
            manifest.promotion_status = "BLOCKED"
            self._save_manifest(manifest)
            raise ValueError(
                f"Candidate {candidate_id} did not pass promotion gate "
                f"(decision={gate_result.decision}). "
                f"Reasons: {gate_result.reasons}. "
                f"Warnings: {gate_result.warnings}. "
                f"Manifest creation requires READY_FOR_PAPER_REVIEW."
            )

        manifest.promotion_status = "READY_FOR_PORTFOLIO_SIM"
        self._save_manifest(manifest)
        return manifest

    def freeze_params(self, manifest_id: str) -> None:
        """Mark params as frozen for a given manifest.

        Args:
            manifest_id: The manifest to freeze.

        Raises:
            ValueError: If the manifest is not found.
        """
        manifest = self.load(manifest_id)
        if manifest is None:
            raise ValueError(f"Manifest {manifest_id} not found")
        manifest.params_frozen = True
        self._save_manifest(manifest)

    def load(self, manifest_id: str) -> StrategyCandidateManifest | None:
        """Load a manifest from disk by ID.

        Args:
            manifest_id: The manifest ID to load.

        Returns:
            The manifest, or None if not found.
        """
        path = self.manifests_dir / manifest_id / "manifest.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return StrategyCandidateManifest(**data)

    def list_manifests(self, status: str = "") -> list[StrategyCandidateManifest]:
        """List all manifests, optionally filtered by promotion_status.

        Args:
            status: Optional status filter (e.g. "READY_FOR_PORTFOLIO_SIM").

        Returns:
            List of manifests sorted by created_at descending.
        """
        if not self.manifests_dir.exists():
            return []

        results: list[StrategyCandidateManifest] = []
        for d in sorted(self.manifests_dir.iterdir()):
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = StrategyCandidateManifest(
                **json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            if not status or manifest.promotion_status == status:
                results.append(manifest)

        results.sort(key=lambda m: m.created_at, reverse=True)
        return results

    def update_status(
        self, manifest_id: str, new_status: str
    ) -> StrategyCandidateManifest:
        """Update the promotion_status of a manifest.

        Args:
            manifest_id: The manifest to update.
            new_status: New status value.

        Returns:
            The updated manifest.

        Raises:
            ValueError: If the manifest is not found.
        """
        allowed = {
            "DRAFT",
            "READY_FOR_PORTFOLIO_SIM",
            "BLOCKED",
            "PAPER_REVIEW_CANDIDATE",
            "REJECTED",
        }
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status '{new_status}'. Must be one of {sorted(allowed)}"
            )

        manifest = self.load(manifest_id)
        if manifest is None:
            raise ValueError(f"Manifest {manifest_id} not found")
        manifest.promotion_status = new_status
        self._save_manifest(manifest)
        return manifest

    def bind_paper_review_evidence(
        self,
        manifest_id: str,
        *,
        paper_review_id: str,
        evidence_pack_path: str,
        review_candidate_path: str,
        review_candidate_status: str,
        blocking_reasons: list[str] | None = None,
    ) -> StrategyCandidateManifest:
        """Attach persisted paper-review evidence to a manifest."""
        manifest = self.load(manifest_id)
        if manifest is None:
            raise ValueError(f"Manifest {manifest_id} not found")
        manifest.paper_review_id = str(paper_review_id or "")
        manifest.portfolio_evidence_pack_path = str(evidence_pack_path or "")
        manifest.portfolio_evidence_pack_id = self._extract_evidence_pack_id(
            manifest.portfolio_evidence_pack_path
        )
        manifest.paper_review_gate_status = str(review_candidate_status or "")
        manifest.paper_review_evidence_pack_path = str(evidence_pack_path or "")
        manifest.paper_review_candidate_path = str(review_candidate_path or "")
        manifest.paper_review_candidate_status = str(review_candidate_status or "")
        manifest.paper_review_blocking_reasons = list(blocking_reasons or [])
        manifest.promotion_status = "PAPER_REVIEW_CANDIDATE"
        self._save_manifest(manifest)
        return manifest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_manifest(self, manifest: StrategyCandidateManifest) -> None:
        """Persist a manifest to disk."""
        path = self.manifests_dir / manifest.strategy_candidate_id / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(manifest), indent=2, default=str), encoding="utf-8"
        )

    def _bind_candidate_evidence(
        self,
        manifest: StrategyCandidateManifest,
        candidate_id: str,
    ) -> None:
        candidate_path = (
            self.data_root / "research" / "candidates" / candidate_id / "candidate.json"
        )
        candidate_data: dict[str, Any] = {}
        if candidate_path.exists():
            candidate_data = json.loads(candidate_path.read_text(encoding="utf-8"))
        data_version = str(candidate_data.get("data_version", "") or "")
        manifest.data_version = data_version
        manifest.data_manifest_path = (
            str(self.data_root / "manifests" / f"{data_version}.json")
            if data_version
            else ""
        )
        manifest.backtest_manifest_path = str(
            candidate_data.get(
                "backtest_manifest_path",
                f"research/backtests/{candidate_id}/run_manifest.json",
            )
            or ""
        )
        manifest.scorecard_path = str(
            self.data_root / "research" / "scorecards" / f"{candidate_id}.json"
        )
        manifest.walk_forward_result_path = str(
            candidate_data.get(
                "walk_forward_result_path",
                f"research/walk_forward/{candidate_id}/result.json",
            )
            or ""
        )
        manifest.cost_stress_result_path = str(
            candidate_data.get(
                "cost_stress_result_path",
                f"research/cost_stress/{candidate_id}/result.json",
            )
            or ""
        )
        experiment = self._load_raw_experiment(manifest.source_experiment_id) or {}
        self._refresh_contract_fields(
            manifest=manifest,
            candidate_data=candidate_data,
            experiment=experiment,
        )

    def _bind_gate_evidence(
        self,
        manifest: StrategyCandidateManifest,
        gate_result: Any,
        candidate_data: dict[str, Any],
    ) -> None:
        validation_stats = dict(gate_result.evidence.get("validation_stats", {}) or {})
        trial_counting = validation_stats.get("trial_counting", {})
        if not isinstance(trial_counting, dict):
            trial_counting = {}
        cv_summary = validation_stats.get("cv_summary", {})
        if not isinstance(cv_summary, dict):
            cv_summary = {}
        cost_before_after = validation_stats.get("cost_before_after", {})
        if not isinstance(cost_before_after, dict):
            cost_before_after = {}
        dsr_summary = validation_stats.get("deflated_sharpe_ratio", {})
        if not isinstance(dsr_summary, dict):
            dsr_summary = {}
        pbo_summary = validation_stats.get("pbo", {})
        if not isinstance(pbo_summary, dict):
            pbo_summary = {}

        effective_trial_count = int(trial_counting.get("effective_trial_count", 0) or 0)
        if effective_trial_count > 0:
            manifest.trial_count = effective_trial_count
        pbo = gate_result.evidence.get(
            "probability_of_backtest_overfitting",
            pbo_summary.get("pbo"),
        )
        if pbo is not None:
            manifest.pbo = pbo
        dsr = gate_result.evidence.get(
            "deflated_sharpe_ratio",
            dsr_summary.get("dsr"),
        )
        if dsr is not None:
            manifest.dsr = dsr
        gate_purge_embargo = {
            "method": str(cv_summary.get("method", "unknown")),
            "purged": bool(cv_summary.get("purged", False)),
            "embargoed": bool(cv_summary.get("embargoed", False)),
            "embargo_steps": int(cv_summary.get("embargo_steps", 0) or 0),
            "fold_count": int(cv_summary.get("fold_count", 0) or 0),
            "path_count": int(cv_summary.get("path_count", 0) or 0),
        }
        gate_has_contract_signal = bool(validation_stats) and any(
            [
                gate_purge_embargo["method"] != "unknown",
                gate_purge_embargo["purged"],
                gate_purge_embargo["embargoed"],
                gate_purge_embargo["embargo_steps"] > 0,
                gate_purge_embargo["fold_count"] > 0,
                gate_purge_embargo["path_count"] > 0,
            ]
        )
        if gate_has_contract_signal:
            manifest.purge_embargo = {
                **dict(manifest.purge_embargo),
                **{k: v for k, v in gate_purge_embargo.items() if v not in ("", None)},
            }
        manifest.cost_model = {
            **dict(manifest.cost_model),
            "validation_summary": cost_before_after,
        }
        manifest.promotion_gate_decision = str(gate_result.decision or "")
        manifest.promotion_gate_blocking_reasons = list(gate_result.reasons)
        manifest.promotion_gate_blocker_details = list(
            dict(gate_result.evidence or {}).get("machine_readable_blocker_details", [])
            or []
        )
        manifest.promotion_gate_warning_reasons = list(gate_result.warnings)
        manifest.promotion_gate_needs_more_research = list(
            getattr(gate_result, "needs_more_research", []) or []
        )
        manifest.promotion_gate_next_commands = list(
            dict(gate_result.evidence or {}).get("next_commands", []) or []
        )
        existing_evidence = dict(getattr(manifest, "evidence", {}) or {})
        existing_evidence["promotion_gate"] = {
            "candidate_id": str(
                getattr(gate_result, "candidate_id", manifest.source_candidate_id) or ""
            ),
            "decision": gate_result.decision,
            "reasons": list(gate_result.reasons),
            "blocker_details": list(
                dict(gate_result.evidence or {}).get("machine_readable_blocker_details", [])
                or []
            ),
            "warnings": list(gate_result.warnings),
            "needs_more_research": list(
                getattr(gate_result, "needs_more_research", []) or []
            ),
            "promotion_result_path": manifest.promotion_result_path,
            "validation_stats": validation_stats,
            "next_commands": list(
                dict(gate_result.evidence or {}).get("next_commands", []) or []
            ),
        }
        manifest.evidence = existing_evidence
        experiment = self._load_raw_experiment(manifest.source_experiment_id) or {}
        self._refresh_contract_fields(
            manifest=manifest,
            candidate_data=candidate_data,
            experiment=experiment,
        )

    def _load_raw_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        path = (
            self.data_root / "research" / "candidates" / candidate_id / "candidate.json"
        )
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_raw_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        path = self.data_root / "research" / "experiments" / experiment_id / "manifest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _find_by_source_candidate(
        self, candidate_id: str
    ) -> StrategyCandidateManifest | None:
        """Find a manifest by its source_candidate_id."""
        for d in sorted(self.manifests_dir.iterdir()):
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            if not manifest_path.exists():
                continue
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if data.get("source_candidate_id") == candidate_id:
                return StrategyCandidateManifest(**data)
        return None

    def _refresh_contract_fields(
        self,
        *,
        manifest: StrategyCandidateManifest,
        candidate_data: dict[str, Any],
        experiment: dict[str, Any],
    ) -> None:
        backtest = self._read_json_dict(manifest.backtest_manifest_path)
        scorecard = self._read_json_dict(manifest.scorecard_path)
        walk_forward = self._read_json_dict(manifest.walk_forward_result_path)
        cost_stress = self._read_json_dict(manifest.cost_stress_result_path)
        data_manifest = self._read_json_dict(manifest.data_manifest_path)
        candidate_metrics = dict(candidate_data.get("metrics", {}))
        promotion_gate_evidence = dict(
            dict(manifest.evidence or {}).get("promotion_gate", {}) or {}
        )
        validation_stats = dict(promotion_gate_evidence.get("validation_stats", {}) or {})
        if not validation_stats:
            validation_stats = summarize_candidate_validation(
                candidate_id=manifest.source_candidate_id,
                metrics=candidate_metrics,
                walk_forward_artifact=walk_forward,
                cost_stress_artifact=cost_stress,
                experiment_data=experiment,
            )

        manifest.data_version = str(
            manifest.data_version
            or candidate_data.get("data_version", "")
            or experiment.get("data_version", "")
            or backtest.get("data_version", "")
            or ""
        )
        manifest.sample_window = self._build_sample_window(
            manifest=manifest,
            candidate_data=candidate_data,
            experiment=experiment,
            backtest=backtest,
            walk_forward=walk_forward,
            data_manifest=data_manifest,
        )
        built_purge_embargo = self._build_purge_embargo(
            candidate_data=candidate_data,
            experiment=experiment,
            walk_forward=walk_forward,
        )
        manifest.purge_embargo = {
            **dict(manifest.purge_embargo),
            **{
                key: value
                for key, value in built_purge_embargo.items()
                if value not in ("", None, 0, False, [])
            },
        }
        manifest.trial_id = str(
            candidate_data.get("trial_id")
            or candidate_metrics.get("trial_id")
            or candidate_data.get("candidate_id")
            or manifest.source_candidate_id
            or manifest.strategy_candidate_id
        )
        resolved_trial_count = self._resolve_trial_count(candidate_data, experiment)
        validation_trial_count = self._first_int(
            dict(validation_stats.get("trial_counting", {}) or {}),
            keys=("effective_trial_count",),
        )
        if validation_trial_count is not None:
            resolved_trial_count = max(resolved_trial_count, validation_trial_count)
        if resolved_trial_count > 0:
            manifest.trial_count = resolved_trial_count
        resolved_pbo = self._first_float(
            candidate_metrics,
            scorecard,
            walk_forward,
            cost_stress,
            dict(validation_stats.get("pbo", {}) or {}),
            keys=("pbo", "PBO", "probability_of_backtest_overfitting"),
        )
        if resolved_pbo is not None:
            manifest.pbo = resolved_pbo
        resolved_dsr = self._first_float(
            candidate_metrics,
            scorecard,
            walk_forward,
            cost_stress,
            dict(validation_stats.get("deflated_sharpe_ratio", {}) or {}),
            keys=("dsr", "DSR", "deflated_sharpe_ratio"),
        )
        if resolved_dsr is not None:
            manifest.dsr = resolved_dsr
        manifest.cpcv = self._build_cpcv(
            candidate_metrics=candidate_metrics,
            walk_forward=walk_forward,
            validation_stats=validation_stats,
        )
        manifest.cost_stress = self._build_cost_stress(
            candidate_metrics=candidate_metrics,
            cost_stress=cost_stress,
            validation_stats=validation_stats,
        )
        manifest.cost_model = self._build_cost_model(
            experiment=experiment,
            backtest=backtest,
            candidate_metrics=candidate_metrics,
            cost_stress=cost_stress,
        )
        manifest.slippage_model = self._build_slippage_model(
            experiment=experiment,
            backtest=backtest,
            candidate_metrics=candidate_metrics,
            cost_stress=cost_stress,
        )
        manifest.capacity = self._build_capacity(
            candidate_metrics=candidate_metrics,
            cost_stress=cost_stress,
            scorecard=scorecard,
        )
        manifest.turnover = self._build_turnover(
            candidate_metrics=candidate_metrics,
            backtest=backtest,
            scorecard=scorecard,
        )
        manifest.holding_period = self._build_holding_period(
            manifest=manifest,
            candidate_metrics=candidate_metrics,
            scorecard=scorecard,
            walk_forward=walk_forward,
        )
        if not manifest.expected_holding_period:
            manifest.expected_holding_period = str(
                manifest.holding_period.get("expected", "") or ""
            )
        manifest.exposure_limits = self._build_exposure_limits(
            candidate_metrics=candidate_metrics,
            backtest=backtest,
            scorecard=scorecard,
        )
        manifest.style_exposure = self._build_style_exposure(
            candidate_data=candidate_data,
            candidate_metrics=candidate_metrics,
            scorecard=scorecard,
            backtest=backtest,
        )
        manifest.failure_conditions = self._build_failure_conditions(
            candidate_data=candidate_data,
            experiment=experiment,
            candidate_metrics=candidate_metrics,
        )
        manifest.delisting_conditions = self._build_delisting_conditions(
            candidate_data=candidate_data,
            experiment=experiment,
            data_manifest=data_manifest,
        )
        manifest.contract_missing_reasons = self._build_contract_missing_reasons(
            manifest=manifest
        )

    def _read_json_dict(self, raw_path: str) -> dict[str, Any]:
        path = self._resolve_artifact_path(raw_path)
        if path is None or not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _resolve_artifact_path(self, raw_path: str) -> Path | None:
        cleaned = str(raw_path or "").strip()
        if not cleaned:
            return None
        path = Path(cleaned)
        if path.is_absolute():
            return path
        if path.exists():
            return path
        data_relative = self.data_root / path
        if data_relative.exists():
            return data_relative
        if path.parts and self.data_root.name and path.parts[0] == self.data_root.name:
            return path
        return data_relative

    def _build_sample_window(
        self,
        *,
        manifest: StrategyCandidateManifest,
        candidate_data: dict[str, Any],
        experiment: dict[str, Any],
        backtest: dict[str, Any],
        walk_forward: dict[str, Any],
        data_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        existing = candidate_data.get("sample_window", {})
        if isinstance(existing, dict) and existing:
            sample_window = dict(existing)
        else:
            sample_window = {
                "start": str(
                    candidate_data.get("start_date")
                    or experiment.get("start_date")
                    or backtest.get("start")
                    or data_manifest.get("start")
                    or ""
                ),
                "end": str(
                    candidate_data.get("end_date")
                    or experiment.get("end_date")
                    or backtest.get("end")
                    or data_manifest.get("end")
                    or ""
                ),
                "train_period": str(
                    candidate_data.get("train_period")
                    or experiment.get("train_period")
                    or walk_forward.get("train_period")
                    or ""
                ),
                "test_period": str(
                    candidate_data.get("test_period")
                    or experiment.get("test_period")
                    or walk_forward.get("test_period")
                    or ""
                ),
                "timeframe": str(manifest.timeframe or experiment.get("timeframe", "1d")),
            }
        return {k: v for k, v in sample_window.items() if v not in ("", None, [], {})}

    def _build_purge_embargo(
        self,
        *,
        candidate_data: dict[str, Any],
        experiment: dict[str, Any],
        walk_forward: dict[str, Any],
    ) -> dict[str, Any]:
        config_sources = [
            candidate_data,
            dict(candidate_data.get("metrics", {})),
            experiment,
            dict(experiment.get("params", {})),
            dict(experiment.get("walk_forward_config", {})),
            walk_forward,
        ]
        payload = {
            "purge_bars": self._first_int(*config_sources, keys=("purge_bars",)),
            "purge_days": self._first_int(*config_sources, keys=("purge_days",)),
            "embargo_bars": self._first_int(*config_sources, keys=("embargo_bars",)),
            "embargo_days": self._first_int(*config_sources, keys=("embargo_days",)),
        }
        return {k: v for k, v in payload.items() if v is not None}

    def _resolve_trial_count(
        self, candidate_data: dict[str, Any], experiment: dict[str, Any]
    ) -> int:
        metrics = dict(candidate_data.get("metrics", {}))
        for source in (candidate_data, metrics, experiment):
            value = source.get("trial_count")
            if value is not None and int(value or 0) > 0:
                return int(value)
        param_grid = experiment.get("param_grid", {})
        if isinstance(param_grid, dict) and param_grid:
            total = 1
            for value in param_grid.values():
                if isinstance(value, list) and value:
                    total *= len(value)
            if total > 0:
                return total
        return 1

    def _build_cost_model(
        self,
        *,
        experiment: dict[str, Any],
        backtest: dict[str, Any],
        candidate_metrics: dict[str, Any],
        cost_stress: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "name": str(
                experiment.get("cost_model")
                or candidate_metrics.get("cost_model")
                or backtest.get("cost_model")
                or "default"
            ),
            "commission_model": str(backtest.get("commission_model", "") or ""),
            "commission_rate": self._first_float(
                backtest, candidate_metrics, cost_stress, keys=("commission_rate",)
            ),
            "stress_result_path": str(self._resolve_artifact_path(cost_stress.get("path", "")) or ""),
        }
        return {k: v for k, v in payload.items() if v not in ("", None)}

    def _build_cpcv(
        self,
        *,
        candidate_metrics: dict[str, Any],
        walk_forward: dict[str, Any],
        validation_stats: dict[str, Any],
    ) -> dict[str, Any]:
        cv_summary = validation_stats.get("cv_summary", {})
        if not isinstance(cv_summary, dict):
            cv_summary = {}
        fold_records = walk_forward.get("folds")
        fold_sharpes = walk_forward.get("fold_sharpes")
        payload = {
            "method": str(
                cv_summary.get("method")
                or walk_forward.get("validation_method")
                or walk_forward.get("cv_method")
                or candidate_metrics.get("validation_method")
                or candidate_metrics.get("cv_method")
                or ""
            ).strip().lower(),
            "purged": bool(cv_summary.get("purged", walk_forward.get("purged", False))),
            "embargoed": bool(
                cv_summary.get(
                    "embargoed",
                    bool((walk_forward.get("embargo_bars") or 0) > 0),
                )
            ),
            "embargo_steps": int(
                cv_summary.get("embargo_steps", walk_forward.get("embargo_bars", 0) or 0)
                or 0
            ),
            "fold_count": int(
                cv_summary.get(
                    "fold_count",
                    len(fold_records) if isinstance(fold_records, list) else len(fold_sharpes or []),
                )
                or 0
            ),
            "path_count": int(
                cv_summary.get("path_count", walk_forward.get("combination_count", 0) or 0)
                or 0
            ),
            "pass_rate": self._first_float(
                cv_summary,
                walk_forward,
                candidate_metrics,
                keys=("pass_rate", "walk_forward_pass_rate"),
            ),
        }
        if payload["method"] != "cpcv":
            payload["missing_reason"] = (
                f"validation_method_not_cpcv:{payload['method'] or 'unknown'}"
            )
        elif payload["path_count"] <= 0 and payload["fold_count"] <= 0:
            payload["missing_reason"] = "cpcv_path_metadata_missing"
        return {k: v for k, v in payload.items() if v not in ("", None)}

    def _build_slippage_model(
        self,
        *,
        experiment: dict[str, Any],
        backtest: dict[str, Any],
        candidate_metrics: dict[str, Any],
        cost_stress: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "name": str(
                experiment.get("slippage_model")
                or candidate_metrics.get("slippage_model")
                or backtest.get("slippage_model")
                or "default"
            ),
            "slippage_bps": self._first_float(
                backtest, candidate_metrics, cost_stress, keys=("slippage_bps", "slippage")
            ),
        }
        return {k: v for k, v in payload.items() if v not in ("", None)}

    def _build_cost_stress(
        self,
        *,
        candidate_metrics: dict[str, Any],
        cost_stress: dict[str, Any],
        validation_stats: dict[str, Any],
    ) -> dict[str, Any]:
        summary = validation_stats.get("cost_before_after", {})
        if not isinstance(summary, dict):
            summary = {}
        raw_levels = cost_stress.get("levels", [])
        levels = raw_levels if isinstance(raw_levels, list) else []
        payload = {
            "status": str(cost_stress.get("status", "") or ""),
            "stress_survival_rate": self._first_float(
                cost_stress,
                candidate_metrics,
                keys=("stress_survival_rate", "survival_rate"),
            ),
            "cost_sensitivity": self._first_float(
                cost_stress,
                candidate_metrics,
                keys=("cost_sensitivity",),
            ),
            "level_count": len(levels),
            "surviving_levels": self._first_int(summary, keys=("surviving_levels",)),
            "baseline_multiplier": self._first_float(
                summary,
                keys=("baseline_multiplier",),
            ),
            "worst_multiplier": self._first_float(
                summary,
                keys=("worst_multiplier",),
            ),
            "worst_return": self._first_float(summary, keys=("worst_return",)),
            "worst_sharpe": self._first_float(summary, keys=("worst_sharpe",)),
        }
        if (
            payload["stress_survival_rate"] is None
            and payload["cost_sensitivity"] is None
            and payload["level_count"] <= 0
        ):
            payload["missing_reason"] = "canonical_cost_stress_artifact_missing_or_empty"
        return {k: v for k, v in payload.items() if v not in ("", None)}

    def _build_capacity(
        self,
        *,
        candidate_metrics: dict[str, Any],
        cost_stress: dict[str, Any],
        scorecard: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "estimated_capacity_usd": self._first_float(
                candidate_metrics,
                cost_stress,
                scorecard,
                keys=("estimated_capacity_usd", "capacity_usd"),
            ),
            "capacity_warning": str(
                candidate_metrics.get("capacity_warning")
                or cost_stress.get("capacity_warning")
                or "UNKNOWN"
            ),
            "fragility_score": self._first_float(
                candidate_metrics, cost_stress, keys=("fragility_score",)
            ),
        }
        return {k: v for k, v in payload.items() if v not in ("", None)}

    def _build_turnover(
        self,
        *,
        candidate_metrics: dict[str, Any],
        backtest: dict[str, Any],
        scorecard: dict[str, Any],
    ) -> dict[str, Any]:
        execution = dict(backtest.get("execution", {}))
        payload = {
            "turnover": self._first_float(
                candidate_metrics, scorecard, backtest, keys=("turnover", "turnover_pct")
            ),
            "annual_turnover_pct": self._first_float(
                execution,
                candidate_metrics,
                backtest,
                keys=("annual_turnover_pct",),
            ),
            "trade_count": self._first_int(
                candidate_metrics, scorecard, backtest, keys=("trade_count",)
            ),
        }
        return {k: v for k, v in payload.items() if v is not None}

    def _build_holding_period(
        self,
        *,
        manifest: StrategyCandidateManifest,
        candidate_metrics: dict[str, Any],
        scorecard: dict[str, Any],
        walk_forward: dict[str, Any],
    ) -> dict[str, Any]:
        expected = str(
            manifest.expected_holding_period
            or candidate_metrics.get("expected_holding_period")
            or walk_forward.get("recommended_holding_period")
            or ""
        )
        payload = {
            "expected": expected,
            "avg_holding_period": self._first_float(
                candidate_metrics, scorecard, keys=("avg_holding_period",)
            ),
        }
        return {k: v for k, v in payload.items() if v not in ("", None)}

    def _build_exposure_limits(
        self,
        *,
        candidate_metrics: dict[str, Any],
        backtest: dict[str, Any],
        scorecard: dict[str, Any],
    ) -> dict[str, Any]:
        exposure = dict(backtest.get("exposure", {}))
        payload = {
            "avg_exposure": self._first_float(
                candidate_metrics, scorecard, exposure, keys=("avg_exposure", "avg_gross_exposure_pct")
            ),
            "max_gross_exposure_pct": self._first_float(
                exposure, candidate_metrics, keys=("max_gross_exposure_pct",)
            ),
            "max_single_symbol_exposure_pct": self._first_float(
                candidate_metrics, keys=("max_single_symbol_exposure_pct",)
            ),
            "sector_exposures": dict(scorecard.get("sector_exposures", {})),
        }
        return {k: v for k, v in payload.items() if v not in ("", None, {}, [])}

    def _build_style_exposure(
        self,
        *,
        candidate_data: dict[str, Any],
        candidate_metrics: dict[str, Any],
        scorecard: dict[str, Any],
        backtest: dict[str, Any],
    ) -> dict[str, Any]:
        raw_payload: dict[str, Any] = {}
        for source in (candidate_data, candidate_metrics, scorecard, backtest):
            for key in (
                "style_exposure",
                "style_exposures",
                "benchmark_style_exposure",
            ):
                value = source.get(key)
                if isinstance(value, dict) and value:
                    raw_payload = dict(value)
                    break
            if raw_payload:
                break

        if not raw_payload:
            return {"missing_reason": "style_exposure_benchmark_regression_missing"}

        betas = raw_payload.get("betas")
        if not isinstance(betas, dict):
            factor_betas = raw_payload.get("factor_betas")
            if isinstance(factor_betas, dict):
                betas = factor_betas
            else:
                betas = {
                    str(key): float(value)
                    for key, value in raw_payload.items()
                    if key
                    not in {
                        "observations",
                        "alpha_period",
                        "alpha_annualized",
                        "r_squared",
                        "residual_volatility_annualized",
                        "benchmark_columns",
                        "warnings",
                        "status",
                        "missing_reason",
                    }
                    and isinstance(value, (int, float))
                }
        warnings = raw_payload.get("warnings", [])
        payload = {
            "observations": self._first_int(raw_payload, keys=("observations",)),
            "alpha_period": self._first_float(raw_payload, keys=("alpha_period",)),
            "alpha_annualized": self._first_float(
                raw_payload, keys=("alpha_annualized",)
            ),
            "betas": {
                str(key): float(value)
                for key, value in (betas or {}).items()
                if value is not None
            },
            "r_squared": self._first_float(raw_payload, keys=("r_squared",)),
            "residual_volatility_annualized": self._first_float(
                raw_payload,
                keys=("residual_volatility_annualized",),
            ),
            "benchmark_columns": list(raw_payload.get("benchmark_columns", []) or []),
            "warnings": list(warnings) if isinstance(warnings, list) else [],
        }
        if not payload["betas"] and not payload["benchmark_columns"]:
            payload["missing_reason"] = str(
                raw_payload.get("missing_reason") or "style_exposure_betas_missing"
            )
        return {k: v for k, v in payload.items() if v not in ("", None, {}, [])}

    def _build_failure_conditions(
        self,
        *,
        candidate_data: dict[str, Any],
        experiment: dict[str, Any],
        candidate_metrics: dict[str, Any],
    ) -> list[str]:
        raw_values: list[Any] = []
        for key in ("failure_conditions", "invalidation_conditions", "delist_conditions"):
            value = candidate_data.get(key)
            if isinstance(value, list):
                raw_values.extend(value)
        params = experiment.get("params", {})
        if isinstance(params, dict):
            for key in ("failure_conditions", "invalidation_conditions"):
                value = params.get(key)
                if isinstance(value, list):
                    raw_values.extend(value)
        if candidate_data.get("reject_reason"):
            raw_values.append(candidate_data["reject_reason"])
        metric_failure = candidate_metrics.get("failure_conditions")
        if isinstance(metric_failure, list):
            raw_values.extend(metric_failure)
        return list(dict.fromkeys(str(item).strip() for item in raw_values if str(item).strip()))

    def _build_delisting_conditions(
        self,
        *,
        candidate_data: dict[str, Any],
        experiment: dict[str, Any],
        data_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        policy = (
            candidate_data.get("delisting_policy")
            or experiment.get("delisting_policy")
            or "manual_review_required"
        )
        return {
            "policy": str(policy),
            "survivorship_bias_risk": str(
                data_manifest.get("survivorship_bias_risk", "unknown") or "unknown"
            ),
            "universe_id": str(data_manifest.get("universe_id", "") or ""),
            "universe_source": str(data_manifest.get("universe_source", "") or ""),
        }

    def _build_contract_missing_reasons(
        self,
        *,
        manifest: StrategyCandidateManifest,
    ) -> dict[str, str]:
        reasons: dict[str, str] = {}
        if not manifest.data_version:
            reasons["data_version"] = "data_version_missing_from_candidate_or_experiment"
        if not manifest.sample_window:
            reasons["sample_window"] = "sample_window_missing_from_experiment_or_data_manifest"
        if not manifest.purge_embargo:
            reasons["purge_embargo"] = "purge_embargo_metadata_missing_from_validation"
        if not manifest.trial_id:
            reasons["trial_id"] = "trial_id_missing_from_candidate"
        if int(manifest.trial_count or 0) <= 0:
            reasons["trial_count"] = "effective_trial_count_missing_from_validation"
        if manifest.pbo is None:
            reasons["pbo"] = "pbo_missing_from_validation"
        if manifest.dsr is None:
            reasons["dsr"] = "deflated_sharpe_ratio_missing_from_validation"
        if not self._cpcv_complete(manifest.cpcv):
            reasons["cpcv"] = str(
                manifest.cpcv.get("missing_reason") or "cpcv_validation_metadata_missing"
            )
        if not manifest.cost_model:
            reasons["cost_model"] = "cost_model_missing_from_experiment_or_backtest"
        if not manifest.slippage_model:
            reasons["slippage_model"] = "slippage_model_missing_from_experiment_or_backtest"
        if not self._cost_stress_complete(manifest.cost_stress):
            reasons["cost_stress"] = str(
                manifest.cost_stress.get("missing_reason")
                or "cost_stress_summary_missing"
            )
        if not self._capacity_complete(manifest.capacity):
            reasons["capacity"] = "capacity_estimate_missing_from_cost_stress_or_metrics"
        if not self._turnover_complete(manifest.turnover):
            reasons["turnover"] = "turnover_evidence_missing_from_scorecard_or_backtest"
        if not manifest.holding_period:
            reasons["holding_period"] = "holding_period_missing_from_walk_forward_or_scorecard"
        if not manifest.exposure_limits:
            reasons["exposure_limits"] = "exposure_limits_missing_from_backtest"
        if not manifest.failure_conditions:
            reasons["failure_conditions"] = "failure_conditions_missing_from_candidate_or_experiment"
        if not manifest.delisting_conditions:
            reasons["delisting_conditions"] = "delisting_conditions_missing_from_candidate_or_data_manifest"
        if not self._style_exposure_complete(manifest.style_exposure):
            reasons["style_exposure"] = str(
                manifest.style_exposure.get("missing_reason")
                or "style_exposure_benchmark_regression_missing"
            )
        return reasons

    @staticmethod
    def _cpcv_complete(payload: dict[str, Any]) -> bool:
        return bool(payload) and str(payload.get("method", "")).lower() == "cpcv" and (
            int(payload.get("path_count", 0) or 0) > 0
            or int(payload.get("fold_count", 0) or 0) > 0
        )

    @staticmethod
    def _cost_stress_complete(payload: dict[str, Any]) -> bool:
        return bool(payload) and (
            payload.get("stress_survival_rate") is not None
            or payload.get("cost_sensitivity") is not None
            or int(payload.get("level_count", 0) or 0) > 0
        )

    @staticmethod
    def _style_exposure_complete(payload: dict[str, Any]) -> bool:
        return bool(payload) and (
            bool(payload.get("betas")) or bool(payload.get("benchmark_columns"))
        )

    @staticmethod
    def _capacity_complete(payload: dict[str, Any]) -> bool:
        return bool(payload) and any(
            payload.get(key) is not None
            for key in ("estimated_capacity_usd", "fragility_score")
        )

    @staticmethod
    def _turnover_complete(payload: dict[str, Any]) -> bool:
        return bool(payload) and any(
            payload.get(key) is not None
            for key in ("turnover", "annual_turnover_pct", "trade_count")
        )

    def _first_float(
        self, *sources: dict[str, Any], keys: tuple[str, ...]
    ) -> float | None:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if value is None or value == "":
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    def _first_int(self, *sources: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if value is None or value == "":
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return None

    def _extract_evidence_pack_id(self, evidence_pack_path: str) -> str:
        path = Path(str(evidence_pack_path or ""))
        if not path.name:
            return ""
        if path.name == "evidence_pack.json":
            return path.parent.name
        return path.name
