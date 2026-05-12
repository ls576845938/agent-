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
from quant_us.research.automation.factor_evidence import (
    build_factor_correlation_matrix,
    estimate_candidate_style_exposure,
)
from quant_us.research.automation.strategy_compiler import ResearchStrategyCompiler
from quant_us.research.portfolio_research import assess_candidate_quality


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
    candidate_rank: int = 0
    stability_score: float = 0.0
    stability_components: dict[str, float] = field(default_factory=dict)
    score_components: dict[str, float] = field(default_factory=dict)
    style_exposure: dict[str, Any] = field(default_factory=dict)
    capacity_profile: dict[str, Any] = field(default_factory=dict)
    turnover_profile: dict[str, Any] = field(default_factory=dict)
    generation_family: str = ""
    complexity_score: int = 0
    formula_signature: str = ""
    quality_score: float = 0.0
    quality_profile: dict[str, Any] = field(default_factory=dict)
    selected: bool = False
    reject_reason: str = ""
    max_abs_correlation_to_selected: float = 0.0
    redundant_with_factor_id: str = ""


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
    candidate_ranking: list[dict[str, Any]] = field(default_factory=list)
    generated_factor_ids: list[str] = field(default_factory=list)
    strategy_logic_paths: list[str] = field(default_factory=list)
    correlation_report: dict[str, Any] = field(default_factory=dict)
    correlation_report_path: str = ""
    manifest_evidence: dict[str, Any] = field(default_factory=dict)
    output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


class FactorMiningEngine:
    """Batch-evaluate and de-correlate registered factor candidates."""

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self._strategy_compiler = ResearchStrategyCompiler(data_root=str(self.data_root))

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
        max_formula_complexity: int = 6,
    ) -> FactorMiningResult:
        """Run factor mining and persist the result."""
        from quant_us.factors.evaluation import FactorEvaluator

        run_id = new_id("fmine")
        normalized_symbols = [symbol.upper() for symbol in symbols if str(symbol).strip()]
        normalized_bar_sizes = _normalize_bar_sizes(bar_sizes or ["1d"])
        library = FactorLibrary()
        ids = factor_ids or library.factor_ids()
        generated_factor_ids: list[str] = []
        if auto_generate_formulas:
            generated_specs = GeneratedFactorLibrary(self.data_root).generate_and_register(
                seed_factor_ids=ids,
                max_specs=max(0, int(max_generated_factors)),
                max_complexity=max(1, int(max_formula_complexity)),
            )
            generated_factor_ids = [spec.factor_id for spec in generated_specs]
            ids = _dedupe(ids + generated_factor_ids)

        generated_library = GeneratedFactorLibrary(self.data_root)
        generated_metadata = {
            spec.factor_id: {
                "generation_family": spec.generation_family,
                "complexity_score": int(spec.complexity_score),
                "formula_signature": spec.signature,
            }
            for spec in generated_library.list_specs()
        }

        raw_scores: list[FactorMiningScore] = []
        evaluator = FactorEvaluator(data_root=str(self.data_root))
        for bar_size in normalized_bar_sizes:
            for factor_id in ids:
                metadata = generated_metadata.get(str(factor_id), {})
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
                            generation_family=str(metadata.get("generation_family", "")),
                            complexity_score=int(metadata.get("complexity_score", 0) or 0),
                            formula_signature=str(metadata.get("formula_signature", "")),
                            reject_reason=f"evaluation_error:{type(exc).__name__}",
                        )
                    )
                    continue
                stability_components = _stability_components(result)
                stability_score = _stability_score(stability_components)
                score_components = _score_components(
                    result,
                    stability_score=stability_score,
                    complexity_score=int(metadata.get("complexity_score", 0) or 0),
                )
                reject_reason = ""
                if int(result.n_observations or 0) < min_observations:
                    reject_reason = "insufficient_observations"
                elif abs(float(result.rank_ic_mean or result.ic_mean or 0.0)) < min_abs_rank_ic:
                    reject_reason = "weak_rank_ic"
                raw_scores.append(
                    FactorMiningScore(
                        factor_id=factor_id,
                        bar_size=bar_size,
                        score=round(sum(score_components.values()), 6),
                        rank_ic_mean=float(result.rank_ic_mean or 0.0),
                        ic_mean=float(result.ic_mean or 0.0),
                        icir=float(result.icir or 0.0),
                        long_short_spread=float(result.long_short_spread or 0.0),
                        hit_rate=float(result.hit_rate or 0.0),
                        turnover=float(result.turnover or 0.0),
                        n_observations=int(result.n_observations or 0),
                        stability_score=stability_score,
                        stability_components=stability_components,
                        score_components=score_components,
                        generation_family=str(metadata.get("generation_family", "")),
                        complexity_score=int(metadata.get("complexity_score", 0) or 0),
                        formula_signature=str(metadata.get("formula_signature", "")),
                        reject_reason=reject_reason,
                    )
                )

        ranked_scores, frames_by_bar_size, bars_by_bar_size = self._rank_scores(
            scores=raw_scores,
            symbols=normalized_symbols,
            start=start,
            end=end,
        )
        selected, redundant_rejections = self._select_low_redundancy(
            scores=ranked_scores,
            symbols=normalized_symbols,
            start=start,
            end=end,
            max_abs_correlation=max_abs_correlation,
            max_selected=max_selected,
            correlation_matrices={
                bar_size: build_factor_correlation_matrix(
                    frame,
                    [
                        score.factor_id
                        for score in ranked_scores
                        if score.bar_size == bar_size and not score.reject_reason
                    ],
                )
                for bar_size, frame in frames_by_bar_size.items()
            },
        )
        correlation_report = self._build_correlation_report(
            run_id=run_id,
            scores=ranked_scores,
            selected=selected,
            redundant_rejections=redundant_rejections,
            frames_by_bar_size=frames_by_bar_size,
            max_abs_correlation=max_abs_correlation,
        )
        correlation_report_path = self._persist_correlation_report(run_id, correlation_report)
        strategy_configs = self._dedupe_strategy_configs(
            self._build_strategy_configs(run_id, selected, normalized_symbols)
        )
        strategy_logic_paths = [
            str(config["logic_path"])
            for config in strategy_configs
            if config.get("logic_path")
        ]

        selected_by_key = {(score.factor_id, score.bar_size): score for score in selected}
        redundant_by_key = {
            key: value for key, value in redundant_rejections.items()
        }
        final_scores = [
            self._finalize_score(
                score=score,
                selected_by_key=selected_by_key,
                redundant_by_key=redundant_by_key,
            )
            for score in ranked_scores
        ]
        candidate_ranking = [
            {
                "candidate_rank": score.candidate_rank,
                "factor_id": score.factor_id,
                "bar_size": score.bar_size,
                "score": round(score.score, 6),
                "quality_score": round(score.quality_score, 6),
                "stability_score": round(score.stability_score, 6),
                "selected": score.selected,
                "reject_reason": score.reject_reason,
                "quality_warnings": list(score.quality_profile.get("warnings", []) or []),
                "generation_family": score.generation_family,
                "complexity_score": score.complexity_score,
            }
            for score in sorted(final_scores, key=lambda item: item.candidate_rank or 10**9)
        ]
        manifest_evidence = self._build_manifest_evidence(
            final_scores=final_scores,
            selected=selected,
            correlation_report_path=correlation_report_path,
            bars_by_bar_size=bars_by_bar_size,
            strategy_config_count=len(strategy_configs),
        )
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
            candidate_ranking=candidate_ranking,
            generated_factor_ids=generated_factor_ids,
            strategy_logic_paths=strategy_logic_paths,
            correlation_report=correlation_report,
            correlation_report_path=str(correlation_report_path),
            manifest_evidence=manifest_evidence,
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
        correlation_matrices: dict[str, pd.DataFrame] | None = None,
    ) -> tuple[list[FactorMiningScore], dict[tuple[str, str], dict[str, Any]]]:
        from quant_us.factors.pipeline import FactorPipeline

        selected: list[FactorMiningScore] = []
        redundant_rejections: dict[tuple[str, str], dict[str, Any]] = {}
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
            redundant_with_factor_id = ""
            if same_timeframe:
                matrix = (correlation_matrices or {}).get(score.bar_size)
                if matrix is not None and not matrix.empty and score.factor_id in matrix.index:
                    correlation_row = matrix.loc[score.factor_id]
                    comparisons = [
                        (
                            item.factor_id,
                            float(correlation_row.get(item.factor_id, 0.0) or 0.0),
                        )
                        for item in same_timeframe
                    ]
                    if comparisons:
                        redundant_with_factor_id, max_corr = max(
                            comparisons,
                            key=lambda item: item[1],
                        )
                else:
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
                    max_corr, redundant_with_factor_id = _max_abs_correlation(
                        frame,
                        score.factor_id,
                        [item.factor_id for item in same_timeframe],
                    )
            if max_corr > max_abs_correlation:
                redundant_rejections[(score.factor_id, score.bar_size)] = {
                    "reject_reason": "high_correlation_to_selected",
                    "max_abs_correlation_to_selected": round(max_corr, 6),
                    "redundant_with_factor_id": redundant_with_factor_id,
                }
                continue
            selected.append(
                _replace_score(
                    score,
                    selected=True,
                    max_abs_correlation_to_selected=max_corr,
                )
            )
        return selected, redundant_rejections

    def _rank_scores(
        self,
        *,
        scores: list[FactorMiningScore],
        symbols: list[str],
        start: str,
        end: str,
    ) -> tuple[list[FactorMiningScore], dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
        from quant_us.factors.pipeline import FactorPipeline, _load_bars

        by_key = {(score.factor_id, score.bar_size): score for score in scores}
        frames_by_bar_size: dict[str, pd.DataFrame] = {}
        bars_by_bar_size: dict[str, pd.DataFrame] = {}
        pipeline = FactorPipeline(data_root=str(self.data_root))

        for bar_size in sorted({score.bar_size for score in scores}):
            factor_ids = sorted(
                {
                    score.factor_id
                    for score in scores
                    if score.bar_size == bar_size and not str(score.reject_reason).startswith("evaluation_error:")
                }
            )
            if not factor_ids:
                continue
            try:
                frames_by_bar_size[bar_size] = pipeline.compute(
                    factor_ids=factor_ids,
                    symbols=symbols,
                    start=start,
                    end=end,
                    bar_size=bar_size,
                    timeframe=bar_size,
                )
            except Exception:
                frames_by_bar_size[bar_size] = pd.DataFrame()
            try:
                bars_by_bar_size[bar_size] = _load_bars(
                    str(self.data_root),
                    symbols,
                    start,
                    end,
                    bar_size=bar_size,
                    vendor=pipeline.data_vendor,
                    asset_class=pipeline.asset_class,
                )
            except Exception:
                bars_by_bar_size[bar_size] = pd.DataFrame()

        enriched: list[FactorMiningScore] = []
        for score in scores:
            style_exposure = {"missing_reason": "style_exposure_inputs_unavailable"}
            capacity_profile = {"missing_reason": "capacity_inputs_unavailable"}
            turnover_profile = _estimate_turnover_profile(
                turnover=score.turnover,
                bar_size=score.bar_size,
            )
            frame = frames_by_bar_size.get(score.bar_size)
            bars = bars_by_bar_size.get(score.bar_size)
            if frame is not None and bars is not None and not frame.empty and not bars.empty:
                style_exposure = estimate_candidate_style_exposure(
                    frame,
                    bars,
                    score.factor_id,
                )
                capacity_profile = _estimate_capacity_profile(
                    bars=bars,
                    turnover=score.turnover,
                    bar_size=score.bar_size,
                )
            quality_profile = assess_candidate_quality(
                style_exposure=style_exposure,
                capacity_profile=capacity_profile,
                turnover_profile=turnover_profile,
            ).to_dict()
            reject_reason = score.reject_reason
            if not reject_reason and not quality_profile.get("eligible", True):
                rejection_reasons = list(quality_profile.get("rejection_reasons", []) or [])
                reject_reason = (
                    f"quality_filter:{rejection_reasons[0]}"
                    if rejection_reasons
                    else "quality_filter"
                )
            enriched.append(
                _replace_score(
                    score,
                    style_exposure=style_exposure,
                    capacity_profile=capacity_profile,
                    turnover_profile=turnover_profile,
                    quality_score=float(quality_profile.get("quality_score", 0.0) or 0.0),
                    quality_profile=quality_profile,
                    reject_reason=reject_reason,
                )
            )

        ranked = sorted(
            enriched,
            key=lambda item: (
                bool(item.reject_reason),
                -(item.score + item.quality_score * 5.0),
                -item.quality_score,
                -item.stability_score,
                item.complexity_score,
                item.factor_id,
            ),
        )
        ranked_with_order = [
            _replace_score(score, candidate_rank=rank)
            for rank, score in enumerate(ranked, start=1)
        ]
        return ranked_with_order, frames_by_bar_size, bars_by_bar_size

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
            ranked = sorted(
                bar_scores,
                key=lambda item: (item.score + item.quality_score * 5.0, item.quality_score),
                reverse=True,
            )
            if len(ranked) >= 2:
                basket_config = self._build_weighted_basket_strategy_config(
                    run_id=run_id,
                    bar_size=bar_size,
                    scores=ranked[: min(3, len(ranked))],
                    symbols=symbols,
                )
                if basket_config["candidate_evidence"].get("candidate_quality", {}).get(
                    "eligible", False
                ):
                    configs.append(basket_config)
                consensus_config = self._build_consensus_strategy_config(
                    run_id=run_id,
                    bar_size=bar_size,
                    scores=ranked[: min(3, len(ranked))],
                    symbols=symbols,
                )
                if consensus_config["candidate_evidence"].get("candidate_quality", {}).get(
                    "eligible", False
                ):
                    configs.append(consensus_config)
        return configs

    def _build_single_factor_strategy_config(
        self,
        run_id: str,
        score: FactorMiningScore,
        symbols: list[str],
    ) -> dict[str, Any]:
        top_n = min(3, max(1, len(symbols)))
        candidate_evidence = _single_candidate_evidence(score)
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
            "candidate_rank": score.candidate_rank,
            "stability_score": round(score.stability_score, 6),
            "rank_ic_mean": score.rank_ic_mean,
            "long_short_spread": score.long_short_spread,
            "candidate_evidence": candidate_evidence,
            "lookahead_guard": "never uses same-bar future return; strategy config must enter backtest through research gate",
            "created_at": utc_now().isoformat(),
        }
        config = {
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
            "candidate_rank": score.candidate_rank,
            "stability_score": round(score.stability_score, 6),
            "rank_ic_mean": score.rank_ic_mean,
            "long_short_spread": score.long_short_spread,
            "candidate_evidence": candidate_evidence,
        }
        logic_path = self._persist_strategy_logic(
            run_id,
            f"single_{score.bar_size}_{score.factor_id}",
            logic,
            config=config,
            candidate_evidence=candidate_evidence,
        )
        return {
            **config,
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
        candidate_evidence = _aggregate_candidate_evidence(scores, basket)
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
            "candidate_rank": min(score.candidate_rank for score in scores),
            "stability_score": round(sum(score.stability_score for score in scores) / len(scores), 6),
            "rank_ic_mean": round(sum(score.rank_ic_mean for score in scores) / len(scores), 6),
            "long_short_spread": round(sum(score.long_short_spread for score in scores) / len(scores), 6),
            "candidate_evidence": candidate_evidence,
            "lookahead_guard": "constituent factors are computed at bar close and blended cross-sectionally for next-bar execution only",
            "created_at": utc_now().isoformat(),
        }
        config = {
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
            "candidate_rank": logic["candidate_rank"],
            "stability_score": logic["stability_score"],
            "rank_ic_mean": logic["rank_ic_mean"],
            "long_short_spread": logic["long_short_spread"],
            "candidate_evidence": candidate_evidence,
        }
        logic_path = self._persist_strategy_logic(
            run_id,
            f"basket_{bar_size}_{'_'.join(score.factor_id for score in scores)}",
            logic,
            config=config,
            candidate_evidence=candidate_evidence,
        )
        return {**config, "logic": logic, "logic_path": str(logic_path)}

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
        candidate_evidence = _aggregate_candidate_evidence(scores, basket)
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
            "candidate_rank": min(score.candidate_rank for score in scores),
            "stability_score": round(sum(score.stability_score for score in scores) / len(scores), 6),
            "rank_ic_mean": round(sum(score.rank_ic_mean for score in scores) / len(scores), 6),
            "long_short_spread": round(max(score.long_short_spread for score in scores), 6),
            "candidate_evidence": candidate_evidence,
            "lookahead_guard": "consensus is formed from same-timestamp factor ranks and only forwarded as next-bar research intent",
            "created_at": utc_now().isoformat(),
        }
        config = {
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
            "candidate_rank": logic["candidate_rank"],
            "stability_score": logic["stability_score"],
            "rank_ic_mean": logic["rank_ic_mean"],
            "long_short_spread": logic["long_short_spread"],
            "candidate_evidence": candidate_evidence,
        }
        logic_path = self._persist_strategy_logic(
            run_id,
            f"consensus_{bar_size}_{'_'.join(score.factor_id for score in scores)}",
            logic,
            config=config,
            candidate_evidence=candidate_evidence,
        )
        return {**config, "logic": logic, "logic_path": str(logic_path)}

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
        *,
        config: dict[str, Any],
        candidate_evidence: dict[str, Any],
    ) -> Path:
        _, path = self._strategy_compiler.compile(
            run_id=run_id,
            strategy_key=strategy_key,
            logic=logic,
            config=config,
            candidate_evidence=candidate_evidence,
        )
        return path

    def _persist(self, result: FactorMiningResult) -> Path:
        path = self.data_root / "research" / "factor_mining" / f"{result.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result.to_dict(), indent=2, default=str, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def _persist_correlation_report(self, run_id: str, report: dict[str, Any]) -> Path:
        path = self.data_root / "research" / "factor_mining" / f"{run_id}_correlation.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, default=str, sort_keys=True),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _dedupe_strategy_configs(
        configs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        deduped: list[dict[str, Any]] = []
        for config in configs:
            key = (
                str(config.get("strategy_id", "")),
                str(config.get("bar_size", "")),
                tuple(str(item) for item in config.get("factor_ids", []) or []),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(config)
        return deduped

    @staticmethod
    def _finalize_score(
        *,
        score: FactorMiningScore,
        selected_by_key: dict[tuple[str, str], FactorMiningScore],
        redundant_by_key: dict[tuple[str, str], dict[str, Any]],
    ) -> FactorMiningScore:
        key = (score.factor_id, score.bar_size)
        if key in selected_by_key:
            return selected_by_key[key]
        payload = redundant_by_key.get(key, {})
        if not payload:
            return score
        return _replace_score(
            score,
            reject_reason=str(payload.get("reject_reason", score.reject_reason)),
            max_abs_correlation_to_selected=float(
                payload.get(
                    "max_abs_correlation_to_selected",
                    score.max_abs_correlation_to_selected,
                )
                or 0.0
            ),
            redundant_with_factor_id=str(
                payload.get("redundant_with_factor_id", score.redundant_with_factor_id)
            ),
        )

    @staticmethod
    def _build_manifest_evidence(
        *,
        final_scores: list[FactorMiningScore],
        selected: list[FactorMiningScore],
        correlation_report_path: Path,
        bars_by_bar_size: dict[str, pd.DataFrame],
        strategy_config_count: int,
    ) -> dict[str, Any]:
        covered = [
            score for score in final_scores if score.style_exposure and not score.style_exposure.get("missing_reason")
        ]
        capacity_covered = [
            score
            for score in final_scores
            if score.capacity_profile and not score.capacity_profile.get("missing_reason")
        ]
        turnover_covered = [
            score
            for score in final_scores
            if score.turnover_profile and not score.turnover_profile.get("missing_reason")
        ]
        return {
            "schema_version": "factor_mining_manifest_evidence_v1",
            "candidate_count": len(final_scores),
            "selected_count": len(selected),
            "selected_factor_ids": [score.factor_id for score in selected],
            "compiled_strategy_count": int(strategy_config_count),
            "quality_filter": {
                "eligible_candidates": sum(
                    1
                    for score in final_scores
                    if score.quality_profile.get("eligible", False)
                ),
                "rejected_candidates": sum(
                    1
                    for score in final_scores
                    if str(score.reject_reason).startswith("quality_filter:")
                ),
                "mean_quality_score": round(
                    sum(score.quality_score for score in final_scores) / max(len(final_scores), 1),
                    6,
                ),
                "selected_mean_quality_score": round(
                    sum(score.quality_score for score in selected) / max(len(selected), 1),
                    6,
                ),
            },
            "style_exposure_coverage": {
                "covered_candidates": len(covered),
                "missing_candidates": len(final_scores) - len(covered),
            },
            "capacity_coverage": {
                "covered_candidates": len(capacity_covered),
                "missing_candidates": len(final_scores) - len(capacity_covered),
            },
            "turnover_coverage": {
                "covered_candidates": len(turnover_covered),
                "missing_candidates": len(final_scores) - len(turnover_covered),
            },
            "bar_samples_available": {
                bar_size: not frame.empty for bar_size, frame in bars_by_bar_size.items()
            },
            "generation_family_counts": {
                family: sum(1 for score in final_scores if score.generation_family == family)
                for family in sorted(
                    {
                        str(score.generation_family)
                        for score in final_scores
                        if str(score.generation_family).strip()
                    }
                )
            },
            "correlation_report_path": str(correlation_report_path),
            "lookahead_guard": "ranking, de-correlation, and style exposure use factor[t] with next-bar returns only",
        }

    @staticmethod
    def _build_correlation_report(
        *,
        run_id: str,
        scores: list[FactorMiningScore],
        selected: list[FactorMiningScore],
        redundant_rejections: dict[tuple[str, str], dict[str, Any]],
        frames_by_bar_size: dict[str, pd.DataFrame],
        max_abs_correlation: float,
    ) -> dict[str, Any]:
        report_rows: list[dict[str, Any]] = []
        selected_by_bar_size: dict[str, list[str]] = {}
        for score in selected:
            selected_by_bar_size.setdefault(score.bar_size, []).append(score.factor_id)

        for bar_size, frame in sorted(frames_by_bar_size.items()):
            factor_ids = [
                score.factor_id
                for score in scores
                if score.bar_size == bar_size and score.factor_id in frame.columns and not score.reject_reason.startswith("evaluation_error:")
            ]
            matrix = build_factor_correlation_matrix(frame, factor_ids)
            high_pairs: list[dict[str, Any]] = []
            for left_idx, left in enumerate(factor_ids):
                for right in factor_ids[left_idx + 1 :]:
                    corr = float(matrix.loc[left, right] or 0.0) if not matrix.empty else 0.0
                    if corr >= max_abs_correlation:
                        high_pairs.append(
                            {
                                "left_factor_id": left,
                                "right_factor_id": right,
                                "abs_correlation": round(corr, 6),
                            }
                        )
            redundant = [
                {
                    "factor_id": factor_id,
                    **payload,
                }
                for (factor_id, reject_bar_size), payload in redundant_rejections.items()
                if reject_bar_size == bar_size
            ]
            report_rows.append(
                {
                    "bar_size": bar_size,
                    "factor_ids": factor_ids,
                    "selected_factor_ids": sorted(selected_by_bar_size.get(bar_size, [])),
                    "redundant_candidates": sorted(
                        redundant,
                        key=lambda item: (
                            -float(item.get("max_abs_correlation_to_selected", 0.0)),
                            str(item.get("factor_id", "")),
                        ),
                    ),
                    "high_correlation_pairs": sorted(
                        high_pairs,
                        key=lambda item: (-float(item["abs_correlation"]), item["left_factor_id"], item["right_factor_id"]),
                    ),
                    "matrix": {
                        factor_id: {
                            other_id: round(float(matrix.loc[factor_id, other_id] or 0.0), 6)
                            for other_id in factor_ids
                        }
                        for factor_id in factor_ids
                    }
                    if not matrix.empty
                    else {},
                }
            )
        return {
            "schema_version": "factor_mining_correlation_report_v1",
            "run_id": run_id,
            "generated_at": utc_now().isoformat(),
            "max_abs_correlation_threshold": max_abs_correlation,
            "bar_sizes": report_rows,
        }
def _stability_components(result: Any) -> dict[str, float]:
    rank_icir = abs(
        float(getattr(result, "rank_icir", 0.0) or getattr(result, "icir", 0.0) or 0.0)
    )
    rank_ic_std = abs(float(getattr(result, "rank_ic_std", 0.0) or 0.0))
    hit_rate = max(0.0, float(getattr(result, "hit_rate", 0.0) or 0.0))
    monotonicity = abs(float(getattr(result, "monotonicity", 0.0) or 0.0))
    n_dates = int(getattr(result, "n_dates", 0) or 0)
    if n_dates <= 0:
        n_dates = max(int(getattr(result, "n_observations", 0) or 0) // 20, 0)
    return {
        "ic_consistency": round(min(rank_icir / 2.0, 1.0), 6),
        "ic_dispersion": round(max(1.0 - min(rank_ic_std / 0.25, 1.0), 0.0), 6),
        "breadth": round(min(n_dates / 60.0, 1.0), 6),
        "hit_rate_edge": round(min(abs(hit_rate - 0.5) * 2.0, 1.0), 6),
        "monotonicity": round(min(monotonicity, 1.0), 6),
    }


def _stability_score(components: dict[str, float]) -> float:
    return round(
        0.30 * float(components.get("ic_consistency", 0.0))
        + 0.20 * float(components.get("ic_dispersion", 0.0))
        + 0.20 * float(components.get("breadth", 0.0))
        + 0.15 * float(components.get("hit_rate_edge", 0.0))
        + 0.15 * float(components.get("monotonicity", 0.0)),
        6,
    )


def _score_components(
    result: Any,
    *,
    stability_score: float,
    complexity_score: int,
) -> dict[str, float]:
    rank_ic = abs(
        float(getattr(result, "rank_ic_mean", 0.0) or getattr(result, "ic_mean", 0.0) or 0.0)
    )
    spread = abs(float(getattr(result, "long_short_spread", 0.0) or 0.0))
    icir = abs(float(getattr(result, "icir", 0.0) or 0.0))
    hit_rate = max(0.0, float(getattr(result, "hit_rate", 0.0) or 0.0))
    turnover = max(0.0, float(getattr(result, "turnover", 0.0) or 0.0))
    return {
        "rank_ic_score": round(rank_ic * 100.0, 6),
        "spread_score": round(spread * 50.0, 6),
        "icir_score": round(min(icir, 5.0) * 2.0, 6),
        "hit_rate_score": round(hit_rate * 5.0, 6),
        "stability_bonus": round(stability_score * 15.0, 6),
        "turnover_penalty": round(-turnover, 6),
        "complexity_penalty": round(-min(max(int(complexity_score), 0), 10) * 0.75, 6),
    }


def _max_abs_correlation(
    frame: pd.DataFrame,
    factor_id: str,
    selected_factor_ids: list[str],
) -> tuple[float, str]:
    if frame.empty or factor_id not in frame.columns:
        return 0.0, ""
    values = pd.to_numeric(frame[factor_id], errors="coerce")
    max_corr = 0.0
    redundant_with_factor_id = ""
    for selected_id in selected_factor_ids:
        if selected_id not in frame.columns:
            continue
        other = pd.to_numeric(frame[selected_id], errors="coerce")
        pair = pd.concat([values, other], axis=1).dropna()
        if len(pair) < 3:
            continue
        corr = abs(float(pair.iloc[:, 0].corr(pair.iloc[:, 1]) or 0.0))
        if corr > max_corr:
            max_corr = corr
            redundant_with_factor_id = selected_id
    return max_corr, redundant_with_factor_id


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
    candidate_rank: int | None = None,
    stability_score: float | None = None,
    stability_components: dict[str, float] | None = None,
    score_components: dict[str, float] | None = None,
    style_exposure: dict[str, Any] | None = None,
    capacity_profile: dict[str, Any] | None = None,
    turnover_profile: dict[str, Any] | None = None,
    quality_score: float | None = None,
    quality_profile: dict[str, Any] | None = None,
    selected: bool | None = None,
    reject_reason: str | None = None,
    max_abs_correlation_to_selected: float | None = None,
    redundant_with_factor_id: str | None = None,
) -> FactorMiningScore:
    payload = asdict(score)
    if candidate_rank is not None:
        payload["candidate_rank"] = candidate_rank
    if stability_score is not None:
        payload["stability_score"] = stability_score
    if stability_components is not None:
        payload["stability_components"] = dict(stability_components)
    if score_components is not None:
        payload["score_components"] = dict(score_components)
    if style_exposure is not None:
        payload["style_exposure"] = dict(style_exposure)
    if capacity_profile is not None:
        payload["capacity_profile"] = dict(capacity_profile)
    if turnover_profile is not None:
        payload["turnover_profile"] = dict(turnover_profile)
    if quality_score is not None:
        payload["quality_score"] = quality_score
    if quality_profile is not None:
        payload["quality_profile"] = dict(quality_profile)
    if selected is not None:
        payload["selected"] = selected
    if reject_reason is not None:
        payload["reject_reason"] = reject_reason
    if max_abs_correlation_to_selected is not None:
        payload["max_abs_correlation_to_selected"] = max_abs_correlation_to_selected
    if redundant_with_factor_id is not None:
        payload["redundant_with_factor_id"] = redundant_with_factor_id
    return FactorMiningScore(**payload)


def _single_candidate_evidence(score: FactorMiningScore) -> dict[str, Any]:
    return {
        "schema_version": "factor_mining_candidate_evidence_v1",
        "factor_id": score.factor_id,
        "bar_size": score.bar_size,
        "candidate_rank": score.candidate_rank,
        "stability_score": round(score.stability_score, 6),
        "stability_components": dict(score.stability_components),
        "score_components": dict(score.score_components),
        "style_exposure": dict(score.style_exposure),
        "capacity": dict(score.capacity_profile),
        "turnover": dict(score.turnover_profile),
        "candidate_quality": dict(score.quality_profile),
        "generation_family": score.generation_family,
        "complexity_score": score.complexity_score,
        "formula_signature": score.formula_signature,
        "max_abs_correlation_to_selected": round(score.max_abs_correlation_to_selected, 6),
        "redundant_with_factor_id": score.redundant_with_factor_id,
    }


def _aggregate_candidate_evidence(
    scores: list[FactorMiningScore],
    basket: list[dict[str, Any]],
) -> dict[str, Any]:
    weights = {
        str(item.get("factor_id", "")): float(item.get("weight", 0.0) or 0.0)
        for item in basket
    }
    style_exposure = _aggregate_style_exposure(scores, weights)
    capacity = _aggregate_capacity_profiles(scores, weights)
    turnover = _aggregate_turnover_profiles(scores, weights)
    max_component_correlation = max(
        (float(score.max_abs_correlation_to_selected or 0.0) for score in scores),
        default=0.0,
    )
    quality = assess_candidate_quality(
        style_exposure=style_exposure,
        capacity_profile=capacity,
        turnover_profile=turnover,
        max_abs_correlation=max_component_correlation,
    ).to_dict()
    return {
        "schema_version": "factor_mining_candidate_evidence_v1",
        "factor_ids": [score.factor_id for score in scores],
        "candidate_rank": min(score.candidate_rank for score in scores),
        "candidate_quality": quality,
        "stability_score": round(
            sum(score.stability_score for score in scores) / len(scores),
            6,
        ),
        "stability_components": {
            name: round(
                sum(component.get(name, 0.0) for component in [score.stability_components for score in scores])
                / len(scores),
                6,
            )
            for name in ("ic_consistency", "ic_dispersion", "breadth", "hit_rate_edge", "monotonicity")
        },
        "component_weights": weights,
        "style_exposure": style_exposure,
        "capacity": capacity,
        "turnover": turnover,
        "generation_families": {
            score.factor_id: score.generation_family for score in scores if score.generation_family
        },
        "component_complexity": {
            score.factor_id: int(score.complexity_score) for score in scores
        },
        "component_formula_signatures": {
            score.factor_id: score.formula_signature
            for score in scores
            if str(score.formula_signature).strip()
        },
        "component_quality_scores": {
            score.factor_id: round(float(score.quality_score or 0.0), 6)
            for score in scores
        },
        "max_component_correlation": round(max_component_correlation, 6),
    }


def _aggregate_style_exposure(
    scores: list[FactorMiningScore],
    weights: dict[str, float],
) -> dict[str, Any]:
    usable = [
        score
        for score in scores
        if score.style_exposure and not score.style_exposure.get("missing_reason")
    ]
    if not usable:
        return {
            "missing_reason": "style_exposure_inputs_unavailable",
            "source_factor_ids": [score.factor_id for score in scores],
        }

    total_weight = sum(abs(weights.get(score.factor_id, 0.0)) for score in usable) or float(len(usable))
    benchmark_columns: set[str] = set()
    beta_names: set[str] = set()
    observations = 0.0
    r_squared = 0.0
    alpha_period = 0.0
    residual_vol = 0.0
    betas: dict[str, float] = {}
    warnings: list[str] = []

    for score in usable:
        weight = abs(weights.get(score.factor_id, 0.0)) or (1.0 / float(len(usable)))
        normalized_weight = weight / total_weight
        payload = score.style_exposure
        benchmark_columns.update(str(item) for item in payload.get("benchmark_columns", []))
        beta_names.update(str(item) for item in dict(payload.get("betas", {})).keys())
        observations += normalized_weight * float(payload.get("observations", 0) or 0.0)
        r_squared += normalized_weight * float(payload.get("r_squared", 0.0) or 0.0)
        alpha_period += normalized_weight * float(payload.get("alpha_period", 0.0) or 0.0)
        residual_vol += normalized_weight * float(
            payload.get("residual_volatility_annualized", 0.0) or 0.0
        )
        warnings.extend(str(item) for item in payload.get("warnings", []) or [])

    for beta_name in sorted(beta_names):
        betas[beta_name] = round(
            sum(
                (
                    abs(weights.get(score.factor_id, 0.0)) or (1.0 / float(len(usable)))
                )
                / total_weight
                * float(dict(score.style_exposure.get("betas", {})).get(beta_name, 0.0) or 0.0)
                for score in usable
            ),
            6,
        )

    return {
        "observations": int(round(observations)),
        "alpha_period": round(alpha_period, 6),
        "betas": betas,
        "r_squared": round(r_squared, 6),
        "residual_volatility_annualized": round(residual_vol, 6),
        "benchmark_columns": sorted(benchmark_columns),
        "warnings": sorted(set(warnings)),
        "source_factor_ids": [score.factor_id for score in usable],
        "lookahead_guard": "factor[t] is paired with next_return[t->t+1] only",
    }


def _estimate_turnover_profile(*, turnover: float, bar_size: str) -> dict[str, Any]:
    normalized_turnover = max(0.0, float(turnover or 0.0))
    periods_per_year = _periods_per_year(bar_size)
    annual_turnover_pct = normalized_turnover * periods_per_year * 100.0
    holding_period_bars = 0.0
    if normalized_turnover > 1e-9:
        holding_period_bars = 1.0 / normalized_turnover
    return {
        "turnover": round(normalized_turnover, 6),
        "annual_turnover_pct": round(annual_turnover_pct, 3),
        "estimated_holding_period_bars": round(holding_period_bars, 3),
        "bar_size": bar_size,
        "turnover_band": _turnover_band(annual_turnover_pct),
        "lookahead_guard": "turnover is annualized from realized factor evaluation metrics only",
    }


def _estimate_capacity_profile(
    *,
    bars: pd.DataFrame,
    turnover: float,
    bar_size: str,
) -> dict[str, Any]:
    if bars.empty or "close" not in bars.columns or "volume" not in bars.columns:
        return {"missing_reason": "capacity_inputs_unavailable"}
    frame = bars.copy()
    frame["close"] = pd.to_numeric(frame.get("close"), errors="coerce")
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["close", "volume", "timestamp_utc"])
    if frame.empty:
        return {"missing_reason": "capacity_inputs_unavailable"}
    frame["dollar_volume"] = frame["close"] * frame["volume"]
    timestamp_liquidity = (
        frame.groupby("timestamp_utc", sort=True)["dollar_volume"].median().dropna()
    )
    if timestamp_liquidity.empty:
        return {"missing_reason": "capacity_inputs_unavailable"}
    median_dollar_volume = float(timestamp_liquidity.median())
    liquidity_floor = float(timestamp_liquidity.quantile(0.25))
    usable_turnover = max(float(turnover or 0.0), 0.05)
    participation_rate = 0.02
    estimated_capacity_usd = liquidity_floor * participation_rate / usable_turnover
    return {
        "estimated_capacity_usd": round(estimated_capacity_usd, 2),
        "liquidity_floor_usd": round(liquidity_floor, 2),
        "median_dollar_volume_usd": round(median_dollar_volume, 2),
        "participation_rate_assumption": participation_rate,
        "capacity_warning": _capacity_warning(estimated_capacity_usd),
        "bar_size": bar_size,
        "lookahead_guard": (
            "capacity uses historical bar close*volume observations inside the "
            "research window only"
        ),
    }


def _aggregate_capacity_profiles(
    scores: list[FactorMiningScore],
    weights: dict[str, float],
) -> dict[str, Any]:
    usable = [
        score
        for score in scores
        if score.capacity_profile and not score.capacity_profile.get("missing_reason")
    ]
    if not usable:
        return {
            "missing_reason": "capacity_inputs_unavailable",
            "source_factor_ids": [score.factor_id for score in scores],
        }
    total_weight = sum(abs(weights.get(score.factor_id, 0.0)) for score in usable) or float(len(usable))
    weighted_capacity = 0.0
    weighted_liquidity_floor = 0.0
    warnings: set[str] = set()
    for score in usable:
        weight = abs(weights.get(score.factor_id, 0.0)) or (1.0 / float(len(usable)))
        normalized_weight = weight / total_weight
        weighted_capacity += normalized_weight * float(
            score.capacity_profile.get("estimated_capacity_usd", 0.0) or 0.0
        )
        weighted_liquidity_floor += normalized_weight * float(
            score.capacity_profile.get("liquidity_floor_usd", 0.0) or 0.0
        )
        warning = str(score.capacity_profile.get("capacity_warning", "") or "").strip()
        if warning:
            warnings.add(warning)
    return {
        "estimated_capacity_usd": round(weighted_capacity, 2),
        "liquidity_floor_usd": round(weighted_liquidity_floor, 2),
        "capacity_warning": _capacity_warning(weighted_capacity),
        "component_warnings": sorted(warnings),
        "source_factor_ids": [score.factor_id for score in usable],
        "lookahead_guard": (
            "capacity uses historical bar close*volume observations inside the "
            "research window only"
        ),
    }


def _aggregate_turnover_profiles(
    scores: list[FactorMiningScore],
    weights: dict[str, float],
) -> dict[str, Any]:
    usable = [
        score
        for score in scores
        if score.turnover_profile and not score.turnover_profile.get("missing_reason")
    ]
    if not usable:
        return {
            "missing_reason": "turnover_inputs_unavailable",
            "source_factor_ids": [score.factor_id for score in scores],
        }
    total_weight = sum(abs(weights.get(score.factor_id, 0.0)) for score in usable) or float(len(usable))
    annual_turnover_pct = 0.0
    raw_turnover = 0.0
    holding_period_bars = 0.0
    for score in usable:
        weight = abs(weights.get(score.factor_id, 0.0)) or (1.0 / float(len(usable)))
        normalized_weight = weight / total_weight
        raw_turnover += normalized_weight * float(
            score.turnover_profile.get("turnover", 0.0) or 0.0
        )
        annual_turnover_pct += normalized_weight * float(
            score.turnover_profile.get("annual_turnover_pct", 0.0) or 0.0
        )
        holding_period_bars += normalized_weight * float(
            score.turnover_profile.get("estimated_holding_period_bars", 0.0) or 0.0
        )
    return {
        "turnover": round(raw_turnover, 6),
        "annual_turnover_pct": round(annual_turnover_pct, 3),
        "estimated_holding_period_bars": round(holding_period_bars, 3),
        "turnover_band": _turnover_band(annual_turnover_pct),
        "source_factor_ids": [score.factor_id for score in usable],
        "lookahead_guard": "turnover is annualized from realized factor evaluation metrics only",
    }


def _periods_per_year(bar_size: str) -> float:
    normalized = str(bar_size or "").strip().lower()
    mapping = {
        "1d": 252.0,
        "1h": 252.0 * 6.5,
        "60m": 252.0 * 6.5,
        "30m": 252.0 * 13.0,
        "15m": 252.0 * 26.0,
        "5m": 252.0 * 78.0,
        "1m": 252.0 * 390.0,
    }
    return mapping.get(normalized, 252.0)


def _turnover_band(annual_turnover_pct: float) -> str:
    value = float(annual_turnover_pct or 0.0)
    if value <= 100.0:
        return "low"
    if value <= 400.0:
        return "medium"
    return "high"


def _capacity_warning(estimated_capacity_usd: float) -> str:
    value = float(estimated_capacity_usd or 0.0)
    if value <= 250_000.0:
        return "LOW"
    if value <= 1_000_000.0:
        return "MEDIUM"
    return "OK"
