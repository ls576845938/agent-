"""Lightweight candidate scoring adapter for research automation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CandidateScorer:
    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def score(self, experiment_id: str) -> list[dict[str, Any]]:
        candidates_path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "candidates.json"
        )
        if not candidates_path.exists():
            return []
        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
        scores: list[dict[str, Any]] = []
        for candidate in candidates:
            metrics = dict(candidate.get("metrics", {}) or {})
            score = float(metrics.get("sharpe_ratio", metrics.get("sharpe", 0.0)))
            scores.append(
                {
                    "candidate_id": candidate.get("candidate_id", ""),
                    "score": score,
                    "metrics": metrics,
                }
            )
        return scores


__all__ = ["CandidateScorer"]
