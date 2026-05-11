from __future__ import annotations

import json
from pathlib import Path

from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig
from quant_us.research.evidence_registry import rebuild_evidence_registry


def _write_approved_review(
    data_root: Path,
    *,
    review_id: str,
    symbols: list[str],
    capital: float = 100_000.0,
    bar_sizes: list[str] | None = None,
) -> Path:
    review_path = data_root / "research" / "paper_reviews" / review_id / "review.json"
    evidence_pack_path = data_root / "research" / "evidence_packs" / review_id / "evidence_pack.json"
    evidence_pack_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_pack_path.write_text(json.dumps({"paper_review_id": review_id}), encoding="utf-8")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(
            {
                "paper_review_id": review_id,
                "strategy_manifest_id": "candidate_for_paper",
                "status": "APPROVED_FOR_PAPER_ONLY",
                "reviewer": "human-risk-reviewer",
                "evidence_pack_path": str(evidence_pack_path),
                "proposed_symbols": symbols,
                "proposed_capital": capital,
                "proposed_risk_envelope": {"bar_sizes": bar_sizes or ["1m", "5m", "15m"]},
            }
        ),
        encoding="utf-8",
    )
    rebuild_evidence_registry(data_root)
    return review_path


def test_paper_review_evidence_must_match_runtime_symbols_and_timeframes(tmp_path: Path) -> None:
    review_path = _write_approved_review(
        tmp_path,
        review_id="paper_review_symbol_mismatch",
        symbols=["AAPL"],
        bar_sizes=["1m", "5m", "15m"],
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            bar_sizes=["1m", "5m", "15m"],
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=str(tmp_path),
        )
    )

    ok, reason = runtime._has_paper_entry_evidence()

    assert ok is False
    assert reason.startswith("paper_review_symbols_mismatch")


def test_paper_review_evidence_must_not_exceed_approved_capital(tmp_path: Path) -> None:
    review_path = _write_approved_review(
        tmp_path,
        review_id="paper_review_capital_mismatch",
        symbols=["SPY"],
        capital=25_000.0,
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            capital=50_000.0,
            bar_sizes=["1m", "5m", "15m"],
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=str(tmp_path),
        )
    )

    ok, reason = runtime._has_paper_entry_evidence()

    assert ok is False
    assert reason.startswith("paper_review_capital_exceeds_approved")
