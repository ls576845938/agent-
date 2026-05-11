"""Automated factor mining for the research pipeline.

The miner evaluates registered factors across one or more bar sizes, ranks
them by out-of-sample proxy quality, and removes highly redundant candidates.
It does not promote strategies by itself; it emits research candidates/configs
that still need backtest, cost stress, walk-forward, and paper-review gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.factors.definition import FactorLibrary


@dataclass(frozen=True)
class FactorMiningScore:
    factor_id: str
    bar_size: str
    score: float
    rank_ic_mean: float
    ic_mean: float
    icir: float
    long_short_spread: float
    hit_rate: float
    turnover: float
    n_observations: int
    selected: bool = False
    reject_reason: str = ""
    max_abs_correlation_to_selected: float = 0.0


@dataclass(frozen=True)
class FactorMiningResult:
    run_id: str
    generated_at: str
    symbols: list[str]
    start: str
    end: str
    bar_sizes: list[str]
    factor_scores: list[FactorMiningScore] = field(default_factory=list)
    selected_factors: list[FactorMiningScore] = field(default_factory=list)
    strategy_configs: list[dict[str, Any]] = field(default_factory=list)
    output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


class FactorMiningEngine:
    """Batch-evaluate and de-correlate registered factor candidates."""

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def mine(
        self,
        *,
        symbols: list[str],
        start: str,
        end: str,
        bar_sizes: list[str] | None = None,
        factor_ids: list[str] | None = None,
        forward_period: int = 5,
        min_abs_rank_ic: float = 0.01,
        min_observations: int = 20,
        max_abs_correlation: float = 0.90,
        max_selected: int = 8,
    ) -> FactorMiningResult:
        """Run factor mining and persist the result."""
        from quant_us.factors.evaluation import FactorEvaluator

        normalized_symbols = [symbol.upper() for symbol in symbols if str(symbol).strip()]
        normalized_bar_sizes = _normalize_bar_sizes(bar_sizes or ["1d"])
        library = FactorLibrary()
        ids = factor_ids or library.factor_ids()

        raw_scores: list[FactorMiningScore] = []
        evaluator = FactorEvaluator(data_root=str(self.data_root))
        for bar_size in normalized_bar_sizes:
            for factor_id in ids:
                try:
                    result = evaluator.evaluate(
                        factor_id=factor_id,
                        symbols=normalized_symbols,
                        start=start,
                        end=end,
                        forward_period=forward_period,
                        bar_size=bar_size,
                        timeframe=bar_size,
                    )
                except Exception as exc:
                    raw_scores.append(
                        FactorMiningScore(
                            factor_id=factor_id,
                            bar_size=bar_size,
                            score=0.0,
                            rank_ic_mean=0.0,
                            ic_mean=0.0,
                            icir=0.0,
                            long_short_spread=0.0,
                            hit_rate=0.0,
                            turnover=0.0,
                            n_observations=0,
                            reject_reason=f"evaluation_error:{type(exc).__name__}",
                        )
                    )
                    continue
                score = _score_factor_result(result)
                reject_reason = ""
                if int(result.n_observations or 0) < min_observations:
                    reject_reason = "insufficient_observations"
                elif abs(float(result.rank_ic_mean or result.ic_mean or 0.0)) < min_abs_rank_ic:
                    reject_reason = "weak_rank_ic"
                raw_scores.append(
                    FactorMiningScore(
                        factor_id=factor_id,
                        bar_size=bar_size,
                        score=score,
                        rank_ic_mean=float(result.rank_ic_mean or 0.0),
                        ic_mean=float(result.ic_mean or 0.0),
                        icir=float(result.icir or 0.0),
                        long_short_spread=float(result.long_short_spread or 0.0),
                        hit_rate=float(result.hit_rate or 0.0),
                        turnover=float(result.turnover or 0.0),
                        n_observations=int(result.n_observations or 0),
                        reject_reason=reject_reason,
                    )
                )

        selected = self._select_low_redundancy(
            scores=raw_scores,
            symbols=normalized_symbols,
            start=start,
            end=end,
            max_abs_correlation=max_abs_correlation,
            max_selected=max_selected,
        )
        strategy_configs = [
            {
                "strategy_id": "factor_rank",
                "bar_size": score.bar_size,
                "timeframe": score.bar_size,
                "symbols": normalized_symbols,
                "params": {
                    "factor_name": score.factor_id,
                    "top_n": min(3, max(1, len(normalized_symbols))),
                    "min_symbols": min(3, max(1, len(normalized_symbols))),
                },
                "research_score": round(score.score, 6),
                "rank_ic_mean": score.rank_ic_mean,
                "long_short_spread": score.long_short_spread,
            }
            for score in selected
        ]

        selected_by_key = {(score.factor_id, score.bar_size): score for score in selected}
        final_scores = [
            score if (score.factor_id, score.bar_size) not in selected_by_key else selected_by_key[(score.factor_id, score.bar_size)]
            for score in raw_scores
        ]
        result = FactorMiningResult(
            run_id=new_id("fmine"),
            generated_at=utc_now().isoformat(),
            symbols=normalized_symbols,
            start=start,
            end=end,
            bar_sizes=normalized_bar_sizes,
            factor_scores=sorted(final_scores, key=lambda item: item.score, reverse=True),
            selected_factors=selected,
            strategy_configs=strategy_configs,
        )
        output_path = self._persist(result)
        return replace(result, output_path=str(output_path))

    def _select_low_redundancy(
        self,
        *,
        scores: list[FactorMiningScore],
        symbols: list[str],
        start: str,
        end: str,
        max_abs_correlation: float,
        max_selected: int,
    ) -> list[FactorMiningScore]:
        from quant_us.factors.pipeline import FactorPipeline

        selected: list[FactorMiningScore] = []
        eligible = [
            score for score in sorted(scores, key=lambda item: item.score, reverse=True)
            if not score.reject_reason
        ]
        by_bar_size: dict[str, pd.DataFrame] = {}
        pipeline = FactorPipeline(data_root=str(self.data_root))

        for score in eligible:
            if len(selected) >= max_selected:
                break
            same_timeframe = [item for item in selected if item.bar_size == score.bar_size]
            max_corr = 0.0
            if same_timeframe:
                frame = by_bar_size.get(score.bar_size)
                factor_ids = sorted(
                    {item.factor_id for item in same_timeframe} | {score.factor_id}
                )
                if frame is None or any(factor_id not in frame.columns for factor_id in factor_ids):
                    try:
                        frame = pipeline.compute(
                            factor_ids=factor_ids,
                            symbols=symbols,
                            start=start,
                            end=end,
                            bar_size=score.bar_size,
                            timeframe=score.bar_size,
                        )
                    except Exception:
                        frame = pd.DataFrame()
                    by_bar_size[score.bar_size] = frame
                max_corr = _max_abs_correlation(frame, score.factor_id, [item.factor_id for item in same_timeframe])
            if max_corr > max_abs_correlation:
                continue
            selected.append(_replace_score(score, selected=True, max_abs_correlation_to_selected=max_corr))
        return selected

    def _persist(self, result: FactorMiningResult) -> Path:
        path = self.data_root / "research" / "factor_mining" / f"{result.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result.to_dict(), indent=2, default=str, sort_keys=True),
            encoding="utf-8",
        )
        return path


def _score_factor_result(result: Any) -> float:
    rank_ic = abs(float(getattr(result, "rank_ic_mean", 0.0) or getattr(result, "ic_mean", 0.0) or 0.0))
    spread = abs(float(getattr(result, "long_short_spread", 0.0) or 0.0))
    icir = abs(float(getattr(result, "icir", 0.0) or 0.0))
    hit_rate = max(0.0, float(getattr(result, "hit_rate", 0.0) or 0.0))
    turnover = max(0.0, float(getattr(result, "turnover", 0.0) or 0.0))
    return round(rank_ic * 100.0 + spread * 50.0 + min(icir, 5.0) * 2.0 + hit_rate * 5.0 - turnover, 6)


def _max_abs_correlation(frame: pd.DataFrame, factor_id: str, selected_factor_ids: list[str]) -> float:
    if frame.empty or factor_id not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame[factor_id], errors="coerce")
    max_corr = 0.0
    for selected_id in selected_factor_ids:
        if selected_id not in frame.columns:
            continue
        other = pd.to_numeric(frame[selected_id], errors="coerce")
        pair = pd.concat([values, other], axis=1).dropna()
        if len(pair) < 3:
            continue
        corr = abs(float(pair.iloc[:, 0].corr(pair.iloc[:, 1]) or 0.0))
        max_corr = max(max_corr, corr)
    return max_corr


def _normalize_bar_sizes(bar_sizes: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in bar_sizes:
        bar_size = str(raw or "").strip().lower()
        if not bar_size or bar_size in seen:
            continue
        seen.add(bar_size)
        normalized.append(bar_size)
    return normalized


def _replace_score(
    score: FactorMiningScore,
    *,
    selected: bool | None = None,
    max_abs_correlation_to_selected: float | None = None,
) -> FactorMiningScore:
    payload = asdict(score)
    if selected is not None:
        payload["selected"] = selected
    if max_abs_correlation_to_selected is not None:
        payload["max_abs_correlation_to_selected"] = max_abs_correlation_to_selected
    return FactorMiningScore(**payload)
