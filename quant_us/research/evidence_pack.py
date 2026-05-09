"""Evidence Pack Generator.

Collects all evidence for a strategy candidate into a comprehensive
evidence pack for paper review. NEVER triggers trading.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now


class EvidencePackGenerator:
    """Generates complete evidence packs for paper review.

    Collects: experiment manifest, candidate lineage, dedup hash,
    feature snapshots, scorecard, walk-forward, anti-overfit,
    portfolio sim report, risk notes, final decision.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def generate(self, candidate_id: str) -> dict:
        """Generate a complete evidence pack for a candidate.

        Args:
            candidate_id: The StrategyCandidate.candidate_id to collect evidence for.

        Returns:
            Dict containing all collected evidence.

        Raises:
            ValueError: If the candidate is not found.
        """
        evidence: dict[str, Any] = {
            "generated_at": utc_now().isoformat(),
            "candidate_id": candidate_id,
            "sections": {},
        }

        # Section 1: Experiment manifest
        evidence["sections"]["experiment_manifest"] = self._get_experiment_manifest(
            candidate_id
        )

        # Section 2: Candidate data
        candidate_data = self._get_candidate_data(candidate_id)
        evidence["sections"]["candidate_data"] = candidate_data

        # Section 3: Lineage
        evidence["sections"]["lineage"] = self._get_lineage(candidate_id)

        # Section 4: Dedup hash
        evidence["sections"]["dedup_hash"] = self._get_dedup_hash(candidate_id)

        # Section 5: Feature snapshots
        evidence["sections"]["feature_snapshots"] = self._get_feature_snapshots(
            candidate_id
        )

        # Section 6: Scorecard
        evidence["sections"]["scorecard"] = self._get_scorecard(candidate_id)

        # Section 7: Walk-forward
        evidence["sections"]["walk_forward"] = self._get_walk_forward(candidate_id)

        # Section 8: Anti-overfit
        evidence["sections"]["anti_overfit"] = self._get_anti_overfit(candidate_id)

        # Section 9: Promotion gate result
        evidence["sections"]["promotion_gate"] = self._get_promotion_gate(
            candidate_id
        )

        # Section 10: Portfolio sim report (if available)
        evidence["sections"]["portfolio_sim"] = self._get_portfolio_sim(candidate_id)

        # Section 11: Risk notes
        evidence["sections"]["risk_notes"] = self._get_risk_notes(candidate_id)

        # Section 12: Final decision
        evidence["sections"]["final_decision"] = self._get_final_decision(
            candidate_id
        )

        return evidence

    def save(self, candidate_id: str, output_dir: str = "") -> str:
        """Generate and save the evidence pack to disk.

        Args:
            candidate_id: The candidate ID.
            output_dir: Optional output directory. Defaults to
                        data/research/evidence_packs/<candidate_id>.

        Returns:
            The path to the saved evidence pack file.
        """
        evidence = self.generate(candidate_id)

        output_path = (
            Path(output_dir)
            if output_dir
            else self.data_root / "research" / "evidence_packs" / candidate_id
        )
        output_path.mkdir(parents=True, exist_ok=True)
        file_path = output_path / "evidence_pack.json"
        file_path.write_text(
            json.dumps(evidence, indent=2, default=str), encoding="utf-8"
        )
        return str(file_path)

    def to_markdown(self, evidence: dict) -> str:
        """Convert an evidence pack dict to a human-readable markdown string.

        Args:
            evidence: The evidence pack dict from generate().

        Returns:
            Formatted markdown string.
        """
        lines: list[str] = []
        lines.append("# Evidence Pack for Paper Review")
        lines.append("")
        lines.append(
            f"**Generated:** {evidence.get('generated_at', 'unknown')}"
        )
        lines.append(f"**Candidate ID:** {evidence.get('candidate_id', 'unknown')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        sections = evidence.get("sections", {})

        for section_key, section_data in sections.items():
            title = section_key.replace("_", " ").title()
            lines.append(f"## {title}")
            lines.append("")

            if isinstance(section_data, dict):
                for k, v in section_data.items():
                    if isinstance(v, (int, float)):
                        if isinstance(v, float):
                            lines.append(f"- **{k}:** {v:.4f}")
                        else:
                            lines.append(f"- **{k}:** {v}")
                    elif isinstance(v, str):
                        lines.append(f"- **{k}:** {v}")
                    elif isinstance(v, list):
                        lines.append(f"- **{k}:** {', '.join(str(x) for x in v[:10])}")
                        if len(v) > 10:
                            lines.append(f"  - *... and {len(v) - 10} more*")
                    elif isinstance(v, dict):
                        lines.append(f"- **{k}:**")
                        for sk, sv in v.items():
                            lines.append(f"  - {sk}: {sv}")
                    else:
                        lines.append(f"- **{k}:** {v}")
            elif isinstance(section_data, list):
                for item in section_data:
                    lines.append(f"- {item}")
            elif isinstance(section_data, str):
                lines.append(f"  {section_data}")
            else:
                lines.append(f"  {section_data}")

            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section collectors
    # ------------------------------------------------------------------

    def _get_experiment_manifest(self, candidate_id: str) -> dict:
        """Get the experiment manifest linked to a candidate."""
        candidate = self._raw_candidate(candidate_id)
        if not candidate:
            return {"error": "candidate not found"}

        experiment_id = candidate.get("experiment_id", "")
        exp_path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "manifest.json"
        )
        if exp_path.exists():
            return json.loads(exp_path.read_text(encoding="utf-8"))
        return {"experiment_id": experiment_id, "error": "manifest not found"}

    def _get_candidate_data(self, candidate_id: str) -> dict:
        """Get the raw candidate data."""
        candidate = self._raw_candidate(candidate_id)
        if candidate:
            return candidate
        return {"error": "candidate not found"}

    def _get_lineage(self, candidate_id: str) -> dict:
        """Get candidate lineage."""
        try:
            from quant_us.research.lab.manifest import ExperimentManager

            mgr = ExperimentManager(data_root=str(self.data_root))
            return mgr.get_lineage(candidate_id)
        except (ValueError, ImportError):
            return {"error": "lineage not available"}

    def _get_dedup_hash(self, candidate_id: str) -> str:
        """Get the dedup hash for a candidate."""
        candidate = self._raw_candidate(candidate_id)
        if candidate:
            return candidate.get("candidate_hash", "")
        return ""

    def _get_feature_snapshots(self, candidate_id: str) -> list[dict]:
        """Get feature snapshots linked to the candidate's experiment."""
        candidate = self._raw_candidate(candidate_id)
        if not candidate:
            return []

        experiment_id = candidate.get("experiment_id", "")
        exp_path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "manifest.json"
        )
        if not exp_path.exists():
            return []

        manifest_data = json.loads(exp_path.read_text(encoding="utf-8"))
        # Feature version is the closest proxy to feature snapshot
        feat_version = manifest_data.get("feature_version", "")
        if feat_version:
            return [{"feature_version": feat_version}]
        return []

    def _get_scorecard(self, candidate_id: str) -> dict:
        """Get the robust scorecard for a candidate."""
        sc_path = (
            self.data_root
            / "research"
            / "scorecards"
            / f"{candidate_id}.json"
        )
        if sc_path.exists():
            return json.loads(sc_path.read_text(encoding="utf-8"))
        return {"error": "scorecard not found"}

    def _get_walk_forward(self, candidate_id: str) -> dict:
        """Get walk-forward results for a candidate."""
        candidate = self._raw_candidate(candidate_id)
        if not candidate:
            return {"error": "candidate not found"}

        metrics = candidate.get("metrics", {})
        wf_pass_rate = metrics.get("walk_forward_pass_rate", -1.0)
        if wf_pass_rate < 0:
            return {"status": "not_run", "note": "Walk-forward not run for this candidate"}

        return {
            "status": "completed",
            "pass_rate": wf_pass_rate,
            "fold_sharpes": metrics.get("wf_fold_sharpes", []),
            "fold_drawdowns": metrics.get("wf_fold_drawdowns", []),
        }

    def _get_anti_overfit(self, candidate_id: str) -> dict:
        """Get anti-overfit check results."""
        try:
            from quant_us.research.automation.overfit import OverfitDetector

            detector = OverfitDetector(data_root=str(self.data_root))
            report = detector.check(candidate_id)
            return {
                "is_overfit": report.is_overfit,
                "degradation_pct": report.degradation_pct,
                "reasons": report.reasons,
            }
        except (ValueError, ImportError) as exc:
            return {"error": str(exc)}

    def _get_promotion_gate(self, candidate_id: str) -> dict:
        """Get the promotion gate evaluation result."""
        try:
            from quant_us.research.automation.promotion_gate import ResearchPromotionGate

            gate = ResearchPromotionGate(data_root=str(self.data_root))
            result = gate.evaluate(candidate_id)
            return {
                "decision": result.decision,
                "reasons": result.reasons,
                "warnings": result.warnings,
                "evidence": result.evidence,
            }
        except (ValueError, ImportError) as exc:
            return {"error": str(exc)}

    def _get_portfolio_sim(self, candidate_id: str) -> dict:
        """Get portfolio simulation results referencing this candidate.

        Checks manifests and portfolio sims linked to this candidate.
        """
        manifest_path = (
            self.data_root / "research" / "manifests"
        )
        if not manifest_path.exists():
            return {"status": "not_created"}

        for d in sorted(manifest_path.iterdir()):
            if not d.is_dir():
                continue
            mf_path = d / "manifest.json"
            if not mf_path.exists():
                continue
            data = json.loads(mf_path.read_text(encoding="utf-8"))
            if data.get("source_candidate_id") == candidate_id:
                return {
                    "status": "manifest_created",
                    "strategy_candidate_id": data.get("strategy_candidate_id"),
                    "promotion_status": data.get("promotion_status"),
                }

        return {"status": "not_created", "note": "No manifest found for this candidate"}

    def _get_risk_notes(self, candidate_id: str) -> dict:
        """Get risk-related notes and concerns."""
        candidate = self._raw_candidate(candidate_id)
        if not candidate:
            return {"error": "candidate not found"}

        metrics = candidate.get("metrics", {})
        risk_notes: dict[str, Any] = {}

        max_dd = abs(float(metrics.get("max_drawdown_pct", 0.0)))
        risk_notes["max_drawdown"] = max_dd
        if max_dd >= 0.50:
            risk_notes["drawdown_warning"] = "High drawdown risk"

        trade_count = int(metrics.get("trade_count", 0))
        risk_notes["trade_count"] = trade_count
        if trade_count <= 10:
            risk_notes["trade_count_warning"] = "Low trade count"

        return risk_notes

    def _get_final_decision(self, candidate_id: str) -> dict:
        """Get the final decision summary."""
        promotion_gate = self._get_promotion_gate(candidate_id)
        if "error" in promotion_gate:
            return {"decision": "UNKNOWN", "reason": "promotion gate unavailable"}

        return {
            "gate_decision": promotion_gate.get("decision", "UNKNOWN"),
            "overall": (
                "READY_FOR_PORTFOLIO_SIM"
                if promotion_gate.get("decision") == "READY_FOR_PAPER_REVIEW"
                else "BLOCKED"
            ),
        }

    def _raw_candidate(self, candidate_id: str) -> dict | None:
        """Load raw candidate JSON data."""
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
