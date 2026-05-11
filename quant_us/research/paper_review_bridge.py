"""Paper Review Bridge.

Manages the human review queue for strategy manifests that have passed
portfolio simulation. NEVER auto-enters paper trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.research.evidence_contracts import (
    validate_portfolio_paper_review_evidence,
)
from quant_us.research.evidence_registry import inspect_candidate_evidence


PAPER_REVIEW_APPROVAL_SCHEMA_VERSION = "paper_review_approval_v1"


@dataclass
class PaperReviewApproval:
    schema_version: str = PAPER_REVIEW_APPROVAL_SCHEMA_VERSION
    reviewer: str = ""
    reason: str = ""
    timestamp: str = ""
    candidate_id: str = ""
    commit_hash: str = ""
    source: str = ""
    source_sha256: str = ""
    gate_snapshot: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperReviewApproval":
        return cls(
            schema_version=str(
                data.get("schema_version", PAPER_REVIEW_APPROVAL_SCHEMA_VERSION)
            ),
            reviewer=str(data.get("reviewer", "")),
            reason=str(data.get("reason", "")),
            timestamp=str(data.get("timestamp", "")),
            candidate_id=str(data.get("candidate_id", "")),
            commit_hash=str(data.get("commit_hash", "")),
            source=str(data.get("source", "")),
            source_sha256=str(data.get("source_sha256", "")),
            gate_snapshot=dict(data.get("gate_snapshot", {})),
        )


@dataclass
class PaperReviewCandidate:
    """A candidate awaiting human review for paper trading consideration.

    This represents a strategy that has passed through:
      Experiment -> Candidate -> Manifest -> Portfolio Simulation
    and now needs a human decision on whether to proceed to paper trading.
    """

    paper_review_id: str
    strategy_manifest_id: str
    portfolio_sim_id: str = ""
    evidence_pack_path: str = ""
    source_candidate_ids: list[str] = field(default_factory=list)
    evidence_gate_status: str = ""
    evidence_gate_blocking_reasons: list[str] = field(default_factory=list)
    proposed_symbols: list[str] = field(default_factory=list)
    proposed_capital: float = 0.0
    proposed_risk_envelope: dict = field(default_factory=dict)
    status: str = "DRAFT"
    # DRAFT|PENDING_HUMAN_REVIEW|APPROVED_FOR_PAPER_ONLY|REJECTED|EXPIRED
    reviewer: str = ""
    review_notes: str = ""
    created_at: str = ""
    reviewed_at: str = ""
    approval: PaperReviewApproval | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.approval is None:
            data["approval"] = None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperReviewCandidate":
        approval = data.get("approval")
        return cls(
            paper_review_id=str(data.get("paper_review_id", "")),
            strategy_manifest_id=str(data.get("strategy_manifest_id", "")),
            portfolio_sim_id=str(data.get("portfolio_sim_id", "")),
            evidence_pack_path=str(data.get("evidence_pack_path", "")),
            source_candidate_ids=list(data.get("source_candidate_ids", [])),
            evidence_gate_status=str(data.get("evidence_gate_status", "")),
            evidence_gate_blocking_reasons=list(
                data.get("evidence_gate_blocking_reasons", [])
            ),
            proposed_symbols=list(data.get("proposed_symbols", [])),
            proposed_capital=float(data.get("proposed_capital", 0.0) or 0.0),
            proposed_risk_envelope=dict(data.get("proposed_risk_envelope", {})),
            status=str(data.get("status", "DRAFT")),
            reviewer=str(data.get("reviewer", "")),
            review_notes=str(data.get("review_notes", "")),
            created_at=str(data.get("created_at", "")),
            reviewed_at=str(data.get("reviewed_at", "")),
            approval=PaperReviewApproval.from_dict(approval)
            if isinstance(approval, dict)
            else None,
        )


class PaperReviewManager:
    """Manages the paper review queue.

    Controls the lifecycle: DRAFT -> PENDING_HUMAN_REVIEW ->
    APPROVED_FOR_PAPER_ONLY (human only) | REJECTED | EXPIRED.

    NEVER auto-enters paper trading. Approval requires explicit
    human confirmation.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.reviews_dir = self.data_root / "research" / "paper_reviews"
        self.reviews_dir.mkdir(parents=True, exist_ok=True)

    def create_review(self, sim_id: str) -> PaperReviewCandidate:
        """Create a paper review from a portfolio simulation that passed.

        Loads the portfolio simulation result and linked manifests to
        populate the review candidate with proposed symbols, capital,
        and risk envelope.

        Args:
            sim_id: The portfolio simulation ID to base the review on.

        Returns:
            The created PaperReviewCandidate (persisted to disk).

        Raises:
            ValueError: If the simulation result is not found or not passed.
        """
        from quant_us.research.portfolio_sim_bridge import PortfolioSimBridge

        bridge = PortfolioSimBridge(data_root=str(self.data_root))
        result = bridge._load_result(sim_id)
        if result is None:
            raise ValueError(f"Portfolio simulation result {sim_id} not found")

        request = bridge._load_request(sim_id)
        if request is None:
            raise ValueError(f"Portfolio simulation request {sim_id} not found")

        if result.decision != "PORTFOLIO_PASS":
            raise ValueError(
                f"Simulation {sim_id} decision is '{result.decision}'. "
                "Only PORTFOLIO_PASS can proceed to paper review."
            )

        # Load manifests to get proposed symbols and capital
        from quant_us.research.strategy_manifest import StrategyManifestManager

        manifest_mgr = StrategyManifestManager(data_root=str(self.data_root))
        all_symbols: list[str] = []
        for mid in request.strategy_manifest_ids:
            m = manifest_mgr.load(mid)
            if m is None:
                raise ValueError(f"Strategy manifest {mid} not found")
            if m.promotion_status != "READY_FOR_PORTFOLIO_SIM":
                raise ValueError(
                    f"Strategy manifest {mid} has promotion_status '{m.promotion_status}'. "
                    "Paper review requires READY_FOR_PORTFOLIO_SIM manifest evidence."
                )
            all_symbols.extend(m.symbols)

        all_symbols = list(dict.fromkeys(all_symbols))
        final_equity = result.equity_curve[-1] if result.equity_curve else request.capital

        from quant_us.research.evidence_pack import EvidencePackGenerator

        evidence_path = EvidencePackGenerator(data_root=str(self.data_root)).save_portfolio_review_pack(
            sim_id,
            portfolio_sim_id=sim_id,
            strategy_manifest_ids=request.strategy_manifest_ids,
            proposed_symbols=all_symbols,
            proposed_capital=final_equity,
            proposed_risk_envelope={
                "max_drawdown_pct": request.max_drawdown,
                "max_correlation": request.max_correlation,
                "risk_budget": request.risk_budget,
            },
            portfolio_decision=result.decision,
        )
        review = self.create_from_portfolio_evidence(sim_id)
        if str(review.evidence_pack_path or "") != evidence_path:
            review.evidence_pack_path = evidence_path
            self._save_review(review)
        return review

    def approve(
        self,
        review_id: str,
        reviewer: str,
        reason: str = "",
    ) -> PaperReviewCandidate:
        """Human approves a review for PAPER_ONLY trading consideration.

        This does NOT trigger paper trading. It only updates status to
        APPROVED_FOR_PAPER_ONLY.

        Args:
            review_id: The paper review ID to approve.
            reviewer: Name of the human reviewer.

        Returns:
            The updated PaperReviewCandidate.

        Raises:
            ValueError: If the review is not found or not in PENDING_HUMAN_REVIEW.
        """
        review = self._load_review(review_id)
        if review is None:
            raise ValueError(f"Paper review {review_id} not found")

        if review.status != "PENDING_HUMAN_REVIEW":
            raise ValueError(
                f"Paper review {review_id} has status '{review.status}'. "
                "Only PENDING_HUMAN_REVIEW can be approved."
            )

        if not reviewer:
            raise ValueError("Reviewer name is required for approval")

        approval = self._build_approval(review, reviewer=reviewer, reason=reason)
        review.status = "APPROVED_FOR_PAPER_ONLY"
        review.reviewer = reviewer
        review.review_notes = reason
        review.reviewed_at = approval.timestamp
        review.approval = approval
        self._save_review(review)
        return review

    def reject(self, review_id: str, reason: str) -> PaperReviewCandidate:
        """Reject a paper review with a reason.

        Args:
            review_id: The paper review ID to reject.
            reason: Human-readable rejection reason.

        Returns:
            The updated PaperReviewCandidate.

        Raises:
            ValueError: If the review is not found.
        """
        review = self._load_review(review_id)
        if review is None:
            raise ValueError(f"Paper review {review_id} not found")

        if review.status in ("REJECTED", "EXPIRED", "APPROVED_FOR_PAPER_ONLY"):
            raise ValueError(
                f"Cannot reject review {review_id} with terminal status '{review.status}'"
            )

        review.status = "REJECTED"
        review.review_notes = reason
        self._save_review(review)
        return review

    def list_pending(self) -> list[PaperReviewCandidate]:
        """List all reviews with status PENDING_HUMAN_REVIEW.

        Returns:
            List of pending PaperReviewCandidates sorted by created_at descending.
        """
        all_reviews = self._list_reviews()
        return [r for r in all_reviews if r.status == "PENDING_HUMAN_REVIEW"]

    def list_all(self) -> list[PaperReviewCandidate]:
        """List all paper reviews.

        Returns:
            List of all reviews sorted by created_at descending.
        """
        return self._list_reviews()

    def get_evidence_pack(self, review_id: str) -> dict:
        """Get the evidence pack associated with a review.

        Args:
            review_id: The paper review ID.

        Returns:
            Dict with evidence summary.

        Raises:
            ValueError: If the review is not found.
        """
        review = self._load_review(review_id)
        if review is None:
            raise ValueError(f"Paper review {review_id} not found")

        # Try to load the evidence pack if path exists
        if review.evidence_pack_path:
            ev_path = Path(review.evidence_pack_path)
            if ev_path.exists():
                return json.loads(ev_path.read_text(encoding="utf-8"))

        # Otherwise build a summary from the review data
        return {
            "paper_review_id": review.paper_review_id,
            "strategy_manifest_id": review.strategy_manifest_id,
            "portfolio_sim_id": review.portfolio_sim_id,
            "proposed_symbols": review.proposed_symbols,
            "proposed_capital": review.proposed_capital,
            "proposed_risk_envelope": review.proposed_risk_envelope,
            "status": review.status,
            "reviewer": review.reviewer,
            "reviewed_at": review.reviewed_at,
            "review_notes": review.review_notes,
            "approval": asdict(review.approval) if review.approval is not None else None,
            "note": "Evidence pack not yet generated. Use 'evidence-pack' command.",
        }

    def create_from_portfolio_evidence(
        self, portfolio_evidence_pack_id: str
    ) -> PaperReviewCandidate:
        """Create paper review from a portfolio evidence pack.

        Requires portfolio-level evidence collected from an EvidencePackGenerator
        that contains portfolio simulation data. This method allows creating a
        paper review directly from evidence data rather than from a simulation run.

        Args:
            portfolio_evidence_pack_id: The ID of a portfolio-level evidence pack
                                        (typically stored under
                                        data/research/evidence_packs/<id>/).

        Returns:
            The created PaperReviewCandidate (persisted to disk).

        Raises:
            ValueError: If the evidence pack is not found, or does not contain
                        portfolio-level evidence.
        """
        # Load the evidence pack
        ev_path = (
            self.data_root
            / "research"
            / "evidence_packs"
            / portfolio_evidence_pack_id
            / "evidence_pack.json"
        )
        if not ev_path.exists():
            raise ValueError(
                f"Portfolio evidence pack {portfolio_evidence_pack_id} not found "
                f"at {ev_path}"
            )

        evidence = json.loads(ev_path.read_text(encoding="utf-8"))
        sections = evidence.get("sections", {})
        evidence_validation = validate_portfolio_paper_review_evidence(
            evidence,
            root=self.data_root,
        )
        if evidence_validation.status != "READY":
            blocker_text = ", ".join(evidence_validation.blocking_reasons)
            raise ValueError(
                f"Evidence pack {portfolio_evidence_pack_id} failed portfolio evidence contract: "
                f"{blocker_text}"
            )

        # Verify portfolio-level evidence exists
        portfolio_sim = sections.get("portfolio_sim", {})
        if not portfolio_sim or portfolio_sim.get("status") in ("not_created",):
            raise ValueError(
                f"Evidence pack {portfolio_evidence_pack_id} does not contain "
                f"portfolio-level evidence. Cannot create paper review."
            )

        # Extract candidate data for proposed symbols and risk envelope
        candidate_data = sections.get("candidate_data", {})
        metrics = candidate_data.get("metrics", {})
        portfolio_candidates = sections.get("portfolio_candidates", [])
        if not isinstance(portfolio_candidates, list):
            portfolio_candidates = []
        source_candidate_ids = [
            str(row.get("candidate_id", "")).strip()
            for row in portfolio_candidates
            if isinstance(row, dict) and str(row.get("candidate_id", "")).strip()
        ]

        proposed_symbols = list(
            dict.fromkeys(
                evidence.get("proposed_symbols", [])
                or sections.get("portfolio_sim", {}).get("proposed_symbols", [])
                or candidate_data.get("symbols", [])
            )
        )

        # Extract promotion gate decision for readiness assessment.
        # READY_FOR_PAPER_REVIEW only grants entry into the human review queue.
        # It is not an approval for paper runtime.
        promotion_gate = sections.get("promotion_gate", {})
        gate_decision = promotion_gate.get("decision", "BLOCKED")

        disallowed_gate_decisions = {"WATCHLIST", "NEED_MORE_RESEARCH", "BLOCKED"}
        if gate_decision in disallowed_gate_decisions:
            raise ValueError(
                f"Evidence pack {portfolio_evidence_pack_id} has gate decision "
                f"{gate_decision}. Paper review requires READY_FOR_PAPER_REVIEW."
            )
        if gate_decision != "READY_FOR_PAPER_REVIEW":
            raise ValueError(
                f"Evidence pack {portfolio_evidence_pack_id} has gate decision "
                f"{gate_decision}. Paper review requires READY_FOR_PAPER_REVIEW."
            )

        review_candidate = sections.get("paper_review_candidate", {})
        review_candidate_status = str(
            review_candidate.get("review_candidate_status", "BLOCKED")
        )
        review_blockers = list(review_candidate.get("blocking_reasons", []))
        if review_candidate_status != "READY_FOR_REVIEW":
            blocker_text = ", ".join(str(item) for item in review_blockers) or (
                "missing_paper_review_candidate_evidence"
            )
            raise ValueError(
                f"Evidence pack {portfolio_evidence_pack_id} is not paper-review ready: "
                f"{review_candidate_status} ({blocker_text})"
            )

        review_id = new_id("prev")
        review = PaperReviewCandidate(
            paper_review_id=review_id,
            strategy_manifest_id=(
                str(portfolio_candidates[0].get("strategy_manifest_id", ""))
                if portfolio_candidates and isinstance(portfolio_candidates[0], dict)
                else candidate_data.get("candidate_id", "")
            ),
            portfolio_sim_id=portfolio_sim.get("portfolio_sim_id", ""),
            evidence_pack_path=str(ev_path),
            source_candidate_ids=source_candidate_ids,
            evidence_gate_status=review_candidate_status,
            evidence_gate_blocking_reasons=review_blockers
            + evidence_validation.blocking_reasons,
            proposed_symbols=proposed_symbols,
            proposed_capital=float(
                evidence.get("proposed_capital", portfolio_sim.get("final_equity", 100000.0))
            ),
            proposed_risk_envelope=dict(
                evidence.get("proposed_risk_envelope", {})
                or {
                    "max_drawdown_pct": abs(
                        float(metrics.get("max_drawdown_pct", 0.3))
                    ),
                    "portfolio_decision": portfolio_sim.get("decision", "WATCHLIST"),
                }
            ),
            status="PENDING_HUMAN_REVIEW",
            created_at=utc_now().isoformat(),
        )

        self._save_review(review)
        self._bind_manifest_review_state(
            review,
            portfolio_candidates=portfolio_candidates,
            review_candidate=review_candidate,
        )
        return review

    def create_from_candidate_evidence(
        self,
        *,
        candidate_id: str = "",
        strategy_manifest_id: str = "",
        portfolio_evidence_pack_id: str = "",
    ) -> PaperReviewCandidate:
        """Prepare a pending paper review from candidate/manifest evidence only.

        This path is research-only. It materializes a deterministic portfolio-style
        evidence pack under `research/evidence_packs/` and then reuses the normal
        manual review queue flow. It never approves a review and never opens any
        paper/live submit path.
        """
        from quant_us.research.evidence_pack import EvidencePackGenerator
        from quant_us.research.strategy_manifest import StrategyManifestManager

        manifest_manager = StrategyManifestManager(data_root=str(self.data_root))
        manifest = self._resolve_manifest_for_candidate_review(
            manifest_manager,
            candidate_id=candidate_id,
            strategy_manifest_id=strategy_manifest_id,
        )
        resolved_candidate_id = str(manifest.source_candidate_id or "").strip()
        if not resolved_candidate_id:
            raise ValueError(
                f"Strategy manifest {manifest.strategy_candidate_id} does not declare source_candidate_id"
            )
        if manifest.promotion_status not in {
            "READY_FOR_PORTFOLIO_SIM",
            "PAPER_REVIEW_CANDIDATE",
        }:
            raise ValueError(
                f"Strategy manifest {manifest.strategy_candidate_id} has promotion_status "
                f"'{manifest.promotion_status}'. Pending paper review requires "
                "READY_FOR_PORTFOLIO_SIM or PAPER_REVIEW_CANDIDATE."
            )

        pack_id = (
            str(portfolio_evidence_pack_id or "").strip()
            or f"pending_review_{manifest.strategy_candidate_id}"
        )
        existing = self._find_existing_review(
            strategy_manifest_id=manifest.strategy_candidate_id,
            evidence_pack_path=str(
                self.data_root / "research" / "evidence_packs" / pack_id / "evidence_pack.json"
            ),
        )
        if existing is not None:
            return existing

        candidate_payload = self._load_candidate_payload(resolved_candidate_id)
        generator = EvidencePackGenerator(data_root=str(self.data_root))
        generator.save_portfolio_review_pack(
            pack_id,
            portfolio_sim_id=pack_id,
            strategy_manifest_ids=[manifest.strategy_candidate_id],
            proposed_symbols=self._proposed_symbols(manifest, candidate_payload),
            proposed_capital=self._proposed_capital(candidate_payload),
            proposed_risk_envelope=self._proposed_risk_envelope(
                manifest,
                candidate_payload,
            ),
            portfolio_decision="READY_FOR_PAPER_REVIEW",
        )
        return self.create_from_portfolio_evidence(pack_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_review(self, review: PaperReviewCandidate) -> None:
        """Persist a review to disk."""
        path = self.reviews_dir / review.paper_review_id / "review.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(review.to_dict(), indent=2, default=str), encoding="utf-8"
        )

    def _load_review(self, review_id: str) -> PaperReviewCandidate | None:
        """Load a review from disk."""
        path = self.reviews_dir / review_id / "review.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return PaperReviewCandidate.from_dict(data)

    def _list_reviews(self) -> list[PaperReviewCandidate]:
        """List all reviews sorted by created_at descending."""
        if not self.reviews_dir.exists():
            return []

        results: list[PaperReviewCandidate] = []
        for d in sorted(self.reviews_dir.iterdir()):
            if not d.is_dir():
                continue
            rev_path = d / "review.json"
            if not rev_path.exists():
                continue
            results.append(
                PaperReviewCandidate.from_dict(
                    json.loads(rev_path.read_text(encoding="utf-8"))
                )
            )

        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    def _resolve_manifest_for_candidate_review(
        self,
        manager: Any,
        *,
        candidate_id: str,
        strategy_manifest_id: str,
    ) -> Any:
        manifest_id = str(strategy_manifest_id or "").strip()
        if manifest_id:
            manifest = manager.load(manifest_id)
            if manifest is None:
                raise ValueError(f"Strategy manifest {manifest_id} not found")
            return manifest

        resolved_candidate_id = str(candidate_id or "").strip()
        if not resolved_candidate_id:
            raise ValueError(
                "candidate_id or strategy_manifest_id is required for candidate evidence staging"
            )
        for manifest in manager.list_manifests():
            if str(manifest.source_candidate_id or "").strip() == resolved_candidate_id:
                return manifest
        raise ValueError(
            f"No strategy manifest found for candidate {resolved_candidate_id}"
        )

    def _find_existing_review(
        self,
        *,
        strategy_manifest_id: str,
        evidence_pack_path: str,
    ) -> PaperReviewCandidate | None:
        normalized_pack_path = ""
        if evidence_pack_path:
            normalized_pack_path = str(Path(evidence_pack_path).resolve(strict=False))
        for review in self._list_reviews():
            if review.status not in {
                "PENDING_HUMAN_REVIEW",
                "APPROVED_FOR_PAPER_ONLY",
            }:
                continue
            if (
                strategy_manifest_id
                and review.strategy_manifest_id == strategy_manifest_id
            ):
                return review
            review_pack_path = str(
                Path(review.evidence_pack_path).resolve(strict=False)
            ) if review.evidence_pack_path else ""
            if normalized_pack_path and review_pack_path == normalized_pack_path:
                return review
        return None

    def _load_candidate_payload(self, candidate_id: str) -> dict[str, Any]:
        candidate_path = (
            self.data_root / "research" / "candidates" / candidate_id / "candidate.json"
        )
        if not candidate_path.exists():
            raise ValueError(f"Candidate {candidate_id} not found")
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Candidate {candidate_id} payload is not a JSON object")
        return payload

    def _proposed_symbols(
        self,
        manifest: Any,
        candidate_payload: dict[str, Any],
    ) -> list[str]:
        symbols = [
            str(item).strip()
            for item in (
                list(getattr(manifest, "symbols", []) or [])
                or list(candidate_payload.get("symbols", []) or [])
            )
            if str(item).strip()
        ]
        return list(dict.fromkeys(symbols))

    def _proposed_capital(self, candidate_payload: dict[str, Any]) -> float:
        metrics = candidate_payload.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
        for key in (
            "proposed_capital",
            "initial_cash",
            "initial_capital",
            "starting_cash",
            "starting_capital",
        ):
            value = metrics.get(key, candidate_payload.get(key))
            if value not in (None, ""):
                return float(value)
        return 100_000.0

    def _proposed_risk_envelope(
        self,
        manifest: Any,
        candidate_payload: dict[str, Any],
    ) -> dict[str, Any]:
        metrics = candidate_payload.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
        envelope = {
            "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0) or 0.0),
            "exposure_limits": dict(getattr(manifest, "exposure_limits", {}) or {}),
            "failure_conditions": list(getattr(manifest, "failure_conditions", []) or []),
            "delisting_conditions": dict(getattr(manifest, "delisting_conditions", {}) or {}),
        }
        return {
            key: value
            for key, value in envelope.items()
            if value not in ({}, [], "", None)
        }

    def _build_approval(
        self,
        review: PaperReviewCandidate,
        *,
        reviewer: str,
        reason: str,
    ) -> PaperReviewApproval:
        timestamp = utc_now().isoformat()
        candidate_id = self._resolve_candidate_id(review)
        chain = (
            inspect_candidate_evidence(
                candidate_id,
                self.data_root,
                use_saved=False,
                rebuild_if_missing=True,
            )
            if candidate_id
            else None
        )
        gate_snapshot = self._gate_snapshot_from_chain(candidate_id, chain)
        source = ""
        source_sha256 = ""
        commit_hash = ""
        if chain is not None:
            source = str(chain.data_manifest.details.get("source", "") or "")
            if not source:
                source = (
                    chain.data_manifest.path
                    or chain.backtest_manifest.path
                    or review.evidence_pack_path
                )
            source_sha256 = (
                chain.backtest_manifest.sha256
                or chain.data_manifest.sha256
                or str(gate_snapshot.get("source_sha256", ""))
            )
            commit_hash = str(
                chain.backtest_manifest.details.get("commit_hash", "") or ""
            )
        if not source:
            source = review.evidence_pack_path or review.strategy_manifest_id
        return PaperReviewApproval(
            reviewer=reviewer,
            reason=reason,
            timestamp=timestamp,
            candidate_id=candidate_id,
            commit_hash=commit_hash,
            source=source,
            source_sha256=source_sha256,
            gate_snapshot=gate_snapshot,
        )

    def _bind_manifest_review_state(
        self,
        review: PaperReviewCandidate,
        *,
        portfolio_candidates: list[dict[str, Any]],
        review_candidate: dict[str, Any],
    ) -> None:
        from quant_us.research.strategy_manifest import StrategyManifestManager

        manifest_ids = [
            str(row.get("strategy_manifest_id", "")).strip()
            for row in portfolio_candidates
            if isinstance(row, dict) and str(row.get("strategy_manifest_id", "")).strip()
        ]
        if not manifest_ids and review.strategy_manifest_id:
            manifest_ids = [review.strategy_manifest_id]
        if not manifest_ids:
            return
        pack_path = str(review.evidence_pack_path or "")
        candidate_path = ""
        if pack_path:
            candidate_path = f"{pack_path}#sections.paper_review_candidate"
        manager = StrategyManifestManager(data_root=str(self.data_root))
        blocking_reasons = list(review_candidate.get("blocking_reasons", []))
        review_status = str(review_candidate.get("review_candidate_status", ""))
        for manifest_id in manifest_ids:
            if manager.load(manifest_id) is None:
                continue
            manager.bind_paper_review_evidence(
                manifest_id,
                paper_review_id=review.paper_review_id,
                evidence_pack_path=pack_path,
                review_candidate_path=candidate_path,
                review_candidate_status=review_status,
                blocking_reasons=blocking_reasons,
            )

    def _resolve_candidate_id(self, review: PaperReviewCandidate) -> str:
        manifest_path = (
            self.data_root
            / "research"
            / "manifests"
            / review.strategy_manifest_id
            / "manifest.json"
        )
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidate_id = str(manifest.get("source_candidate_id", "")).strip()
            if candidate_id:
                return candidate_id
        if review.evidence_pack_path:
            ev_path = Path(review.evidence_pack_path)
            if ev_path.exists():
                evidence = json.loads(ev_path.read_text(encoding="utf-8"))
                sections = evidence.get("sections", {})
                candidate_data = sections.get("candidate_data", {})
                candidate_id = str(
                    candidate_data.get("candidate_id", evidence.get("candidate_id", ""))
                ).strip()
                if candidate_id:
                    return candidate_id
        return ""

    def _gate_snapshot_from_chain(
        self,
        candidate_id: str,
        chain: Any,
    ) -> dict[str, Any]:
        if chain is None:
            return {
                "status": "missing",
                "candidate_id": candidate_id,
            }
        gate_results = chain.promotion_result.details.get("promotion_gate_results", {})
        candidate_gate = gate_results.get(candidate_id, {}) if isinstance(gate_results, dict) else {}
        return {
            "candidate_id": candidate_id,
            "decision": str(candidate_gate.get("decision", "")),
            "reasons": list(candidate_gate.get("reasons", []))
            if isinstance(candidate_gate.get("reasons", []), list)
            else [],
            "warnings": list(candidate_gate.get("warnings", []))
            if isinstance(candidate_gate.get("warnings", []), list)
            else [],
            "promotion_result_path": chain.promotion_result.path,
            "promotion_result_sha256": chain.promotion_result.sha256,
            "promotion_result_integrity_status": chain.promotion_result.integrity_status,
            "chain_status": chain.chain_status,
            "review_queue_entry_allowed": str(candidate_gate.get("decision", "")) == "READY_FOR_PAPER_REVIEW",
            "paper_execution_authorized": False,
            "authorization_scope": "human_review_only",
            "authorization_note": (
                "READY_FOR_PAPER_REVIEW only allows entry into manual paper review. "
                "It is not paper execution authorization."
            ),
            "notes": list(chain.notes),
        }
