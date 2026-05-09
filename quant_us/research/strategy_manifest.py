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
        from quant_us.research.lab.manifest import ExperimentManager

        mgr = ExperimentManager(data_root=str(self.data_root))
        candidate = mgr._load_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        # Check if manifest already exists for this candidate
        existing = self._find_by_source_candidate(candidate_id)
        if existing is not None:
            raise ValueError(
                f"Manifest already exists for candidate {candidate_id}: "
                f"{existing.strategy_candidate_id}"
            )

        # Evaluate promotion gate
        from quant_us.research.automation.promotion_gate import ResearchPromotionGate

        gate = ResearchPromotionGate(data_root=str(self.data_root))
        gate_result = gate.evaluate(candidate_id)

        if gate_result.decision != "READY_FOR_PAPER_REVIEW":
            raise ValueError(
                f"Candidate {candidate_id} did not pass promotion gate "
                f"(decision={gate_result.decision}). "
                f"Reasons: {gate_result.reasons}. "
                f"Warnings: {gate_result.warnings}. "
                f"Manifest creation requires READY_FOR_PAPER_REVIEW."
            )

        # Build lineage info
        experiment_id = candidate.experiment_id
        experiment = mgr.load(experiment_id)
        source_candidate_id_for_lineage = candidate.parent_candidate_id or ""

        manifest = StrategyCandidateManifest(
            strategy_candidate_id=new_id("sman"),
            source_candidate_id=candidate_id,
            source_experiment_id=experiment_id,
            lineage_id=source_candidate_id_for_lineage,
            strategy_template=(
                experiment.strategy_family
                if experiment and experiment.strategy_family
                else ""
            ),
            params=dict(candidate.metrics) if candidate.metrics else {},
            symbols=list(experiment.symbols) if experiment else [],
            timeframe=getattr(experiment, "timeframe", "1d") if experiment else "1d",
            params_frozen=True,
            promotion_status="READY_FOR_PORTFOLIO_SIM",
            created_at=utc_now().isoformat(),
        )

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
