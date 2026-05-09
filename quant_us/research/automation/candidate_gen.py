"""Deterministic research candidate generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CandidateConfig:
    strategy_family: str
    strategy_ids: list[str]
    param_grid: dict[str, list[Any]]
    symbols: list[str]
    max_candidates: int = 100
    data_version: str = "qs-yfinance-SPY-1d-generated"
    data_source: str = "yfinance"
    asset_class: str = "equity"


class CandidateGenerator:
    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def generate(self, config: CandidateConfig) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for strategy_id in config.strategy_ids:
            for params in self._param_product(config.param_grid):
                payload = {
                    "strategy_family": config.strategy_family,
                    "strategy_id": strategy_id,
                    "params": params,
                    "symbols": list(config.symbols),
                    "data_version": config.data_version,
                    "data_source": config.data_source,
                    "asset_class": config.asset_class,
                }
                candidate_id = f"cand_{self._fingerprint(payload)[:16]}"
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        **payload,
                        "promotion_status": "RESEARCH_ONLY",
                    }
                )
                if len(candidates) >= config.max_candidates:
                    return candidates
        return candidates

    def save_candidates(self, experiment_id: str, candidates: list[dict[str, Any]]) -> None:
        exp_dir = self.data_root / "research" / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "experiment_id": experiment_id,
            "strategy_id": candidates[0]["strategy_id"] if candidates else "",
            "strategy_family": candidates[0]["strategy_family"] if candidates else "",
            "symbols": candidates[0]["symbols"] if candidates else [],
            "data_version": candidates[0].get("data_version", "") if candidates else "",
            "candidate_count": len(candidates),
        }
        (exp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (exp_dir / "candidates.json").write_text(json.dumps(candidates, indent=2), encoding="utf-8")

        for candidate in candidates:
            candidate_dir = self.data_root / "research" / "candidates" / str(candidate["candidate_id"])
            candidate_dir.mkdir(parents=True, exist_ok=True)
            candidate_record = {
                **candidate,
                "experiment_id": experiment_id,
                "metrics": candidate.get("metrics", {}),
            }
            (candidate_dir / "candidate.json").write_text(
                json.dumps(candidate_record, indent=2),
                encoding="utf-8",
            )

    @staticmethod
    def _param_product(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
        if not param_grid:
            return [{}]
        keys = sorted(param_grid)
        values = [param_grid[key] for key in keys]
        return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*values)]

    @staticmethod
    def _fingerprint(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["CandidateConfig", "CandidateGenerator"]
