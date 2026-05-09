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
    proposed_symbols: list[str] = field(default_factory=list)
    proposed_capital: float = 0.0
    proposed_risk_envelope: dict = field(default_factory=dict)
    status: str = "DRAFT"
    # DRAFT|PENDING_HUMAN_REVIEW|APPROVED_FOR_PAPER_ONLY|REJECTED|EXPIRED
    reviewer: str = ""
    review_notes: str = ""
    created_at: str = ""


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

        if result.decision not in ("PORTFOLIO_PASS", "WATCHLIST"):
            raise ValueError(
                f"Simulation {sim_id} decision is '{result.decision}'. "
                "Only PORTFOLIO_PASS or WATCHLIST can proceed to paper review."
            )

        # Load manifests to get proposed symbols and capital
        from quant_us.research.strategy_manifest import StrategyManifestManager

        manifest_mgr = StrategyManifestManager(data_root=str(self.data_root))
        all_symbols: list[str] = []
        for mid in request.strategy_manifest_ids:
            m = manifest_mgr.load(mid)
            if m is not None:
                all_symbols.extend(m.symbols)

        all_symbols = list(dict.fromkeys(all_symbols))
        final_equity = result.equity_curve[-1] if result.equity_curve else request.capital

        review_id = new_id("prev")
        review = PaperReviewCandidate(
            paper_review_id=review_id,
            strategy_manifest_id=request.strategy_manifest_ids[0]
            if request.strategy_manifest_ids
            else "",
            portfolio_sim_id=sim_id,
            proposed_symbols=all_symbols,
            proposed_capital=final_equity,
            proposed_risk_envelope={
                "max_drawdown_pct": request.max_drawdown,
                "max_correlation": request.max_correlation,
                "risk_budget": request.risk_budget,
            },
            status="PENDING_HUMAN_REVIEW",
            created_at=utc_now().isoformat(),
        )

        self._save_review(review)
        return review

    def approve(self, review_id: str, reviewer: str) -> PaperReviewCandidate:
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

        review.status = "APPROVED_FOR_PAPER_ONLY"
        review.reviewer = reviewer
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

        proposed_symbols = list(
            dict.fromkeys(candidate_data.get("symbols", []))
        )

        # Extract promotion gate decision for readiness assessment
        promotion_gate = sections.get("promotion_gate", {})
        gate_decision = promotion_gate.get("decision", "BLOCKED")

        # Only allow creation from evidence packs that passed the gate
        if gate_decision == "BLOCKED":
            raise ValueError(
                f"Evidence pack {portfolio_evidence_pack_id} has gate decision "
                f"BLOCKED. Cannot create paper review from blocked candidate."
            )

        review_id = new_id("prev")
        review = PaperReviewCandidate(
            paper_review_id=review_id,
            strategy_manifest_id=candidate_data.get("candidate_id", ""),
            portfolio_sim_id=portfolio_sim.get("portfolio_sim_id", ""),
            evidence_pack_path=str(ev_path),
            proposed_symbols=proposed_symbols,
            proposed_capital=float(portfolio_sim.get("final_equity", 100000.0)),
            proposed_risk_envelope={
                "max_drawdown_pct": abs(
                    float(metrics.get("max_drawdown_pct", 0.3))
                ),
                "portfolio_decision": portfolio_sim.get("decision", "WATCHLIST"),
            },
            status="PENDING_HUMAN_REVIEW",
            created_at=utc_now().isoformat(),
        )

        self._save_review(review)
        return review

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_review(self, review: PaperReviewCandidate) -> None:
        """Persist a review to disk."""
        path = self.reviews_dir / review.paper_review_id / "review.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(review), indent=2, default=str), encoding="utf-8"
        )

    def _load_review(self, review_id: str) -> PaperReviewCandidate | None:
        """Load a review from disk."""
        path = self.reviews_dir / review_id / "review.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return PaperReviewCandidate(**data)

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
                PaperReviewCandidate(
                    **json.loads(rev_path.read_text(encoding="utf-8"))
                )
            )

        results.sort(key=lambda r: r.created_at, reverse=True)
        return results
