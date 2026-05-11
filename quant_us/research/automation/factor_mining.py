"""Automated factor mining for the research pipeline.

The miner evaluates registered factors across one or more bar sizes, ranks
them by out-of-sample proxy quality, and removes highly redundant candidates.
It does not promote strategies by itself; it emits research candidates/configs
that still need backtest, cost stress, walk-forward, and paper-review gates.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.factors.definition import FactorLibrary
from quant_us.factors.formula import GeneratedFactorLibrary


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
    generated_factor_ids: list[str] = field(default_factory=list)
    strategy_logic_paths: list[str] = field(default_factory=list)
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
        auto_generate_formulas: bool = False,
        max_generated_factors: int = 24,
    ) -> FactorMiningResult:
        """Run factor mining and persist the result."""
        from quant_us.factors.evaluation import FactorEvaluator

        normalized_symbols = [symbol.upper() for symbol in symbols if str(symbol).strip()]
        normalized_bar_sizes = _normalize_bar_sizes(bar_sizes or ["1d"])
        library = FactorLibrary()
        ids = factor_ids or library.factor_ids()
        generated_factor_ids: list[str] = []
        if auto_generate_formulas:
            generated_specs = GeneratedFactorLibrary(self.data_root).generate_and_register(
                seed_factor_ids=ids,
                max_specs=max(0, int(max_generated_factors)),
            )
            generated_factor_ids = [spec.factor_id for spec in generated_specs]
            ids = _dedupe(ids + generated_factor_ids)

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
        run_id = new_id("fmine")
        strategy_configs = self._build_strategy_configs(run_id, selected, normalized_symbols)
        strategy_logic_paths = [
            str(config["logic_path"])
            for config in strategy_configs
            if config.get("logic_path")
        ]

        selected_by_key = {(score.factor_id, score.bar_size): score for score in selected}
        final_scores = [
            score if (score.factor_id, score.bar_size) not in selected_by_key else selected_by_key[(score.factor_id, score.bar_size)]
            for score in raw_scores
        ]
        result = FactorMiningResult(
            run_id=run_id,
            generated_at=utc_now().isoformat(),
            symbols=normalized_symbols,
            start=start,
            end=end,
            bar_sizes=normalized_bar_sizes,
            factor_scores=sorted(final_scores, key=lambda item: item.score, reverse=True),
            selected_factors=selected,
            strategy_configs=strategy_configs,
            generated_factor_ids=generated_factor_ids,
            strategy_logic_paths=strategy_logic_paths,
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

    def _build_strategy_configs(
        self,
        run_id: str,
        scores: list[FactorMiningScore],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        configs: list[dict[str, Any]] = []
        grouped: dict[str, list[FactorMiningScore]] = {}
        for score in scores:
            grouped.setdefault(score.bar_size, []).append(score)

        for score in scores:
            configs.append(self._build_single_factor_strategy_config(run_id, score, symbols))

        for bar_size, bar_scores in grouped.items():
            ranked = sorted(bar_scores, key=lambda item: item.score, reverse=True)
            if len(ranked) >= 2:
                configs.append(
                    self._build_weighted_basket_strategy_config(
                        run_id=run_id,
                        bar_size=bar_size,
                        scores=ranked[: min(3, len(ranked))],
                        symbols=symbols,
                    )
                )
                configs.append(
                    self._build_consensus_strategy_config(
                        run_id=run_id,
                        bar_size=bar_size,
                        scores=ranked[: min(3, len(ranked))],
                        symbols=symbols,
                    )
                )
        return configs

    def _build_single_factor_strategy_config(
        self,
        run_id: str,
        score: FactorMiningScore,
        symbols: list[str],
    ) -> dict[str, Any]:
        top_n = min(3, max(1, len(symbols)))
        logic = {
            "logic_id": f"{run_id}:{score.bar_size}:{score.factor_id}",
            "logic_version": "factor_rank_dsl_v1",
            "template_id": "single_factor_rank",
            "strategy_id": "factor_rank",
            "factor_id": score.factor_id,
            "factor_ids": [score.factor_id],
            "bar_size": score.bar_size,
            "timeframe": score.bar_size,
            "symbols": list(symbols),
            "signal": {
                "type": "cross_sectional_factor_rank",
                "rank_order": "descending",
                "long_top_n": top_n,
                "min_symbols": top_n,
            },
            "execution_semantics": "signal_at_bar_close_order_next_bar",
            "risk_overlays": {
                "long_only": True,
                "max_symbol_weight": round(1.0 / top_n, 6),
                "requires_cost_stress": True,
                "requires_walk_forward": True,
                "requires_paper_review": True,
            },
            "research_score": round(score.score, 6),
            "rank_ic_mean": score.rank_ic_mean,
            "long_short_spread": score.long_short_spread,
            "lookahead_guard": "never uses same-bar future return; strategy config must enter backtest through research gate",
            "created_at": utc_now().isoformat(),
        }
        logic_path = self._persist_strategy_logic(
            run_id,
            f"single_{score.bar_size}_{score.factor_id}",
            logic,
        )
        return {
            "template_id": "single_factor_rank",
            "strategy_id": "factor_rank",
            "bar_size": score.bar_size,
            "timeframe": score.bar_size,
            "symbols": symbols,
            "factor_ids": [score.factor_id],
            "params": {
                "factor_name": score.factor_id,
                "top_n": top_n,
                "min_symbols": top_n,
            },
            "research_score": round(score.score, 6),
            "rank_ic_mean": score.rank_ic_mean,
            "long_short_spread": score.long_short_spread,
            "logic": logic,
            "logic_path": str(logic_path),
        }

    def _build_weighted_basket_strategy_config(
        self,
        *,
        run_id: str,
        bar_size: str,
        scores: list[FactorMiningScore],
        symbols: list[str],
    ) -> dict[str, Any]:
        top_n = min(3, max(1, len(symbols)))
        basket = self._basket_weights(scores)
        logic = {
            "logic_id": f"{run_id}:{bar_size}:basket:{len(scores)}",
            "logic_version": "factor_rank_dsl_v2",
            "template_id": "weighted_factor_basket",
            "strategy_id": "factor_basket",
            "factor_ids": [score.factor_id for score in scores],
            "bar_size": bar_size,
            "timeframe": bar_size,
            "symbols": list(symbols),
            "signal": {
                "type": "weighted_factor_basket",
                "rank_order": "descending",
                "long_top_n": top_n,
                "min_symbols": top_n,
                "components": basket,
            },
            "execution_semantics": "signal_at_bar_close_order_next_bar",
            "risk_overlays": {
                "long_only": True,
                "max_symbol_weight": round(1.0 / top_n, 6),
                "requires_cost_stress": True,
                "requires_walk_forward": True,
                "requires_paper_review": True,
                "max_strategy_turnover": round(max(score.turnover for score in scores), 6),
            },
            "research_score": round(sum(score.score for score in scores) / len(scores), 6),
            "rank_ic_mean": round(sum(score.rank_ic_mean for score in scores) / len(scores), 6),
            "long_short_spread": round(sum(score.long_short_spread for score in scores) / len(scores), 6),
            "lookahead_guard": "constituent factors are computed at bar close and blended cross-sectionally for next-bar execution only",
            "created_at": utc_now().isoformat(),
        }
        logic_path = self._persist_strategy_logic(
            run_id,
            f"basket_{bar_size}_{'_'.join(score.factor_id for score in scores)}",
            logic,
        )
        return {
            "template_id": "weighted_factor_basket",
            "strategy_id": "factor_basket",
            "bar_size": bar_size,
            "timeframe": bar_size,
            "symbols": symbols,
            "factor_ids": [score.factor_id for score in scores],
            "params": {
                "factor_basket": basket,
                "top_n": top_n,
                "min_symbols": top_n,
            },
            "research_score": logic["research_score"],
            "rank_ic_mean": logic["rank_ic_mean"],
            "long_short_spread": logic["long_short_spread"],
            "logic": logic,
            "logic_path": str(logic_path),
        }

    def _build_consensus_strategy_config(
        self,
        *,
        run_id: str,
        bar_size: str,
        scores: list[FactorMiningScore],
        symbols: list[str],
    ) -> dict[str, Any]:
        top_n = min(3, max(1, len(symbols)))
        basket = self._basket_weights(scores)
        min_agreement = min(len(scores), 2)
        logic = {
            "logic_id": f"{run_id}:{bar_size}:consensus:{len(scores)}",
            "logic_version": "factor_rank_dsl_v2",
            "template_id": "consensus_rank",
            "strategy_id": "factor_consensus",
            "factor_ids": [score.factor_id for score in scores],
            "bar_size": bar_size,
            "timeframe": bar_size,
            "symbols": list(symbols),
            "signal": {
                "type": "factor_consensus_rank",
                "rank_order": "descending",
                "long_top_n": top_n,
                "min_symbols": top_n,
                "min_agreement": min_agreement,
                "components": basket,
            },
            "execution_semantics": "signal_at_bar_close_order_next_bar",
            "risk_overlays": {
                "long_only": True,
                "max_symbol_weight": round(1.0 / top_n, 6),
                "requires_cost_stress": True,
                "requires_walk_forward": True,
                "requires_paper_review": True,
                "consensus_required": min_agreement,
            },
            "research_score": round(max(score.score for score in scores), 6),
            "rank_ic_mean": round(sum(score.rank_ic_mean for score in scores) / len(scores), 6),
            "long_short_spread": round(max(score.long_short_spread for score in scores), 6),
            "lookahead_guard": "consensus is formed from same-timestamp factor ranks and only forwarded as next-bar research intent",
            "created_at": utc_now().isoformat(),
        }
        logic_path = self._persist_strategy_logic(
            run_id,
            f"consensus_{bar_size}_{'_'.join(score.factor_id for score in scores)}",
            logic,
        )
        return {
            "template_id": "consensus_rank",
            "strategy_id": "factor_consensus",
            "bar_size": bar_size,
            "timeframe": bar_size,
            "symbols": symbols,
            "factor_ids": [score.factor_id for score in scores],
            "params": {
                "factor_basket": basket,
                "top_n": top_n,
                "min_symbols": top_n,
                "min_agreement": min_agreement,
            },
            "research_score": logic["research_score"],
            "rank_ic_mean": logic["rank_ic_mean"],
            "long_short_spread": logic["long_short_spread"],
            "logic": logic,
            "logic_path": str(logic_path),
        }

    @staticmethod
    def _basket_weights(scores: list[FactorMiningScore]) -> list[dict[str, Any]]:
        positive_total = sum(max(score.score, 0.0) for score in scores)
        fallback_equal = positive_total <= 0.0
        total = float(len(scores)) if fallback_equal else positive_total
        basket: list[dict[str, Any]] = []
        for score in scores:
            raw_weight = 1.0 if fallback_equal else max(score.score, 0.0)
            basket.append(
                {
                    "factor_id": score.factor_id,
                    "weight": round(raw_weight / total, 6),
                    "rank_ic_mean": round(score.rank_ic_mean, 6),
                }
            )
        return basket

    def _persist_strategy_logic(
        self,
        run_id: str,
        strategy_key: str,
        logic: dict[str, Any],
    ) -> Path:
        path = (
            self.data_root
            / "research"
            / "generated_strategies"
            / f"{run_id}_{_safe_name(strategy_key)}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(logic, indent=2, default=str, sort_keys=True), encoding="utf-8")
        return path

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


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value)).strip("_")[:120] or "item"


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
