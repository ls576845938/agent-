"""Deterministic research candidate generation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any


DEFAULT_GATE_REQUIREMENTS: dict[str, Any] = {
    "requires_walk_forward": True,
    "requires_cost_stress": True,
    "requires_regime_evidence": True,
    "requires_event_driven_ledger": True,
    "requires_promotion_gate": True,
}


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
    timeframe: str = ""
    research_metadata: dict[str, Any] = field(default_factory=dict)
    gate_requirements: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyFamilySpec:
    family_id: str
    family_class: str
    strategy_id: str
    param_grid: dict[str, list[Any]]
    regime_profiles: list[dict[str, Any]] = field(default_factory=list)
    filter_profiles: list[dict[str, Any]] = field(default_factory=list)
    turnover_profiles: list[dict[str, Any]] = field(default_factory=list)
    candidate_cap: int | None = None
    thesis: str = ""
    tags: list[str] = field(default_factory=list)
    research_metadata: dict[str, Any] = field(default_factory=dict)
    gate_requirements: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyFamilySweepConfig:
    strategy_family: str
    family_specs: list[StrategyFamilySpec]
    symbols: list[str]
    max_candidates: int = 48
    data_version: str = "qs-sqlite-BTCUSDT-1h-generated"
    data_source: str = "sqlite"
    asset_class: str = "crypto"
    timeframe: str = "1h"
    research_metadata: dict[str, Any] = field(default_factory=dict)
    gate_requirements: dict[str, Any] = field(default_factory=dict)


class CandidateGenerator:
    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def generate(self, config: CandidateConfig) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for strategy_id in config.strategy_ids:
            for params in self._param_product(config.param_grid):
                candidates.append(
                    self._build_candidate(
                        strategy_family=config.strategy_family,
                        strategy_id=strategy_id,
                        params=params,
                        symbols=config.symbols,
                        data_version=config.data_version,
                        data_source=config.data_source,
                        asset_class=config.asset_class,
                        timeframe=config.timeframe,
                        research_metadata=config.research_metadata,
                        gate_requirements=config.gate_requirements,
                    )
                )
                if len(candidates) >= config.max_candidates:
                    return candidates
        return candidates

    def generate_family_sweep(self, config: StrategyFamilySweepConfig) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for family in config.family_specs:
            family_candidates = 0
            regime_profiles = family.regime_profiles or [{}]
            filter_profiles = family.filter_profiles or [{}]
            turnover_profiles = family.turnover_profiles or [{}]
            family_cap = family.candidate_cap if family.candidate_cap is not None else config.max_candidates

            for params in self._param_product(family.param_grid):
                for regime in regime_profiles:
                    for filters in filter_profiles:
                        for turnover in turnover_profiles:
                            research_metadata = {
                                **dict(config.research_metadata),
                                **dict(family.research_metadata),
                                "candidate_origin": "btc_strategy_family_sweep",
                                "family_id": family.family_id,
                                "family_class": family.family_class,
                                "thesis": family.thesis,
                                "tags": list(family.tags),
                                "regime": dict(regime),
                                "filters": dict(filters),
                                "turnover_aware": dict(turnover),
                                "runtime_hints": self._runtime_hints(turnover),
                            }
                            gate_requirements = {
                                **dict(config.gate_requirements),
                                **dict(family.gate_requirements),
                            }
                            candidates.append(
                                self._build_candidate(
                                    strategy_family=config.strategy_family,
                                    strategy_id=family.strategy_id,
                                    params=params,
                                    symbols=config.symbols,
                                    data_version=config.data_version,
                                    data_source=config.data_source,
                                    asset_class=config.asset_class,
                                    timeframe=config.timeframe,
                                    research_metadata=research_metadata,
                                    gate_requirements=gate_requirements,
                                    strategy_family_variant=family.family_id,
                                    strategy_family_class=family.family_class,
                                )
                            )
                            family_candidates += 1
                            if family_candidates >= family_cap:
                                break
                            if len(candidates) >= config.max_candidates:
                                return candidates
                        if family_candidates >= family_cap or len(candidates) >= config.max_candidates:
                            break
                    if family_candidates >= family_cap or len(candidates) >= config.max_candidates:
                        break
                if family_candidates >= family_cap or len(candidates) >= config.max_candidates:
                    break
        return candidates

    def save_candidates(self, experiment_id: str, candidates: list[dict[str, Any]]) -> None:
        exp_dir = self.data_root / "research" / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        strategy_ids = sorted(
            {str(candidate.get("strategy_id", "")) for candidate in candidates if candidate.get("strategy_id")}
        )
        strategy_families = sorted(
            {
                str(candidate.get("strategy_family", ""))
                for candidate in candidates
                if candidate.get("strategy_family")
            }
        )
        manifest = {
            "experiment_id": experiment_id,
            "strategy_id": candidates[0]["strategy_id"] if candidates else "",
            "strategy_family": candidates[0]["strategy_family"] if candidates else "",
            "strategy_ids": strategy_ids,
            "strategy_families": strategy_families,
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
            candidate_quality = candidate.get("candidate_quality")
            if isinstance(candidate_quality, dict):
                candidate_record["candidate_quality"] = dict(candidate_quality)
                candidate_record["metrics"] = {
                    **candidate_record["metrics"],
                    "candidate_quality_score": candidate_quality.get("quality_score"),
                    "candidate_quality_eligible": candidate_quality.get("eligible"),
                }
            selection_metadata = candidate.get("selection_metadata")
            if isinstance(selection_metadata, dict):
                candidate_record["selection_metadata"] = dict(selection_metadata)
            (candidate_dir / "candidate.json").write_text(
                json.dumps(candidate_record, indent=2),
                encoding="utf-8",
            )

    def _build_candidate(
        self,
        *,
        strategy_family: str,
        strategy_id: str,
        params: dict[str, Any],
        symbols: list[str],
        data_version: str,
        data_source: str,
        asset_class: str,
        timeframe: str = "",
        research_metadata: dict[str, Any] | None = None,
        gate_requirements: dict[str, Any] | None = None,
        strategy_family_variant: str = "",
        strategy_family_class: str = "",
    ) -> dict[str, Any]:
        payload = {
            "strategy_family": strategy_family,
            "strategy_family_variant": strategy_family_variant,
            "strategy_family_class": strategy_family_class,
            "strategy_id": strategy_id,
            "params": dict(params),
            "symbols": list(symbols),
            "data_version": data_version,
            "data_source": data_source,
            "asset_class": asset_class,
            "timeframe": timeframe,
            "research_metadata": dict(research_metadata or {}),
            "gate_requirements": self._merged_gate_requirements(
                asset_class=asset_class,
                overrides=gate_requirements,
            ),
        }
        candidate_id = f"cand_{self._fingerprint(payload)[:16]}"
        return {
            "candidate_id": candidate_id,
            **payload,
            "promotion_status": "RESEARCH_ONLY",
        }

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

    @staticmethod
    def _merged_gate_requirements(
        *,
        asset_class: str,
        overrides: dict[str, Any] | None,
    ) -> dict[str, Any]:
        requirements = dict(DEFAULT_GATE_REQUIREMENTS)
        if str(asset_class).lower() == "crypto":
            requirements["requires_sqlite_data_source"] = True
        if overrides:
            requirements.update(dict(overrides))
        return requirements

    @staticmethod
    def _runtime_hints(turnover_profile: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(turnover_profile, dict):
            return {}
        runtime_keys = (
            "cost_aware_filter",
            "max_annual_turnover_pct",
            "min_holding_bars",
            "rebalance_buffer_pct",
        )
        return {
            key: turnover_profile[key]
            for key in runtime_keys
            if key in turnover_profile and turnover_profile[key] not in (None, "")
        }


def conservative_btc_strategy_family_sweep_config(
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    data_version: str = "qs-sqlite-BTCUSDT-1h-generated",
    max_candidates: int = 24,
) -> StrategyFamilySweepConfig:
    trend_turnover = {
        "profile": "medium_turnover",
        "cost_aware_filter": True,
        "max_annual_turnover_pct": 730.0,
        "min_holding_bars": 12,
        "rebalance_buffer_pct": 0.02,
    }
    slow_turnover = {
        "profile": "low_turnover",
        "cost_aware_filter": True,
        "max_annual_turnover_pct": 365.0,
        "min_holding_bars": 24,
        "rebalance_buffer_pct": 0.03,
    }
    mean_reversion_turnover = {
        "profile": "bounded_reversion",
        "cost_aware_filter": True,
        "max_annual_turnover_pct": 540.0,
        "min_holding_bars": 8,
        "rebalance_buffer_pct": 0.025,
    }
    family_specs = [
        StrategyFamilySpec(
            family_id="btc_trend_macd",
            family_class="trend",
            strategy_id="trend_macd",
            param_grid={
                "fast_window": [12, 20],
                "slow_window": [48],
                "signal_window": [9, 12],
            },
            regime_profiles=[
                {"mode": "aligned", "allowed_regimes": ["bull_trend", "recovery"]},
                {"mode": "defensive", "allowed_regimes": ["bull_trend", "sideways"]},
            ],
            filter_profiles=[
                {
                    "volatility_filter": "atr_band_cap",
                    "trend_strength_filter": "adx_confirmation",
                }
            ],
            turnover_profiles=[trend_turnover],
            candidate_cap=8,
            thesis="Follow persistent BTC trend only when the regime engine and volatility guard agree.",
            tags=["btc", "trend", "regime_filtered"],
        ),
        StrategyFamilySpec(
            family_id="btc_macro_trend",
            family_class="trend",
            strategy_id="macro_trend",
            param_grid={
                "short_ma": [20],
                "medium_ma": [60],
                "long_ma": [180, 240],
            },
            regime_profiles=[
                {"mode": "macro_aligned", "allowed_regimes": ["bull_trend", "recovery"]},
                {"mode": "pullback_resume", "allowed_regimes": ["recovery", "sideways"]},
            ],
            filter_profiles=[
                {
                    "volatility_filter": "realized_vol_below_tail",
                    "structure_filter": "higher_highs_required",
                }
            ],
            turnover_profiles=[slow_turnover],
            candidate_cap=4,
            thesis="Favor slower BTC trend templates that should survive cost stress better than reactive entries.",
            tags=["btc", "macro_trend", "lower_turnover"],
        ),
        StrategyFamilySpec(
            family_id="btc_donchian_breakout",
            family_class="breakout",
            strategy_id="donchian_breakout",
            param_grid={"channel_window": [20, 55]},
            regime_profiles=[
                {"mode": "breakout_follow", "allowed_regimes": ["bull_trend", "recovery"]},
                {"mode": "range_escape", "allowed_regimes": ["sideways", "recovery"]},
            ],
            filter_profiles=[
                {
                    "breakout_filter": "close_above_channel",
                    "volume_filter": "relative_volume_confirmation",
                }
            ],
            turnover_profiles=[trend_turnover],
            candidate_cap=4,
            thesis="Keep breakout variants only where a regime label can explain why the channel should matter.",
            tags=["btc", "breakout", "trend_continuation"],
        ),
        StrategyFamilySpec(
            family_id="btc_reversion_rsi",
            family_class="reversion",
            strategy_id="reversion_rsi",
            param_grid={
                "rsi_window": [14],
                "boll_window": [20],
                "boll_dev": [2.0],
                "rsi_long": [25, 30],
                "rsi_short": [70],
                "rsi_exit_low": [45],
                "rsi_exit_high": [55],
            },
            regime_profiles=[
                {"mode": "reversion_only", "allowed_regimes": ["sideways"]},
                {"mode": "pullback_only", "allowed_regimes": ["recovery"]},
            ],
            filter_profiles=[
                {
                    "volatility_filter": "funding_and_volatility_cooldown",
                    "entry_filter": "oversold_then_reclaim",
                }
            ],
            turnover_profiles=[mean_reversion_turnover],
            candidate_cap=4,
            thesis="Bound BTC mean-reversion research to regimes where over-trading can be explained and audited.",
            tags=["btc", "reversion", "bounded_turnover"],
        ),
        StrategyFamilySpec(
            family_id="btc_volatility_squeeze",
            family_class="volatility",
            strategy_id="volatility_squeeze",
            param_grid={
                "boll_window": [20, 30],
                "boll_dev": [2.0],
                "width_threshold": [0.03],
            },
            regime_profiles=[
                {"mode": "compression_breakout", "allowed_regimes": ["sideways", "recovery"]},
                {"mode": "trend_pause_resume", "allowed_regimes": ["bull_trend", "recovery"]},
            ],
            filter_profiles=[
                {
                    "compression_filter": "bb_width_contracting",
                    "trend_filter": "higher_timeframe_bias_required",
                }
            ],
            turnover_profiles=[trend_turnover],
            candidate_cap=4,
            thesis="Treat volatility compression as a regime-conditioned entry, not a standalone pass-through.",
            tags=["btc", "volatility", "compression"],
        ),
    ]
    return StrategyFamilySweepConfig(
        strategy_family="btc_conservative_family_sweep",
        family_specs=family_specs,
        symbols=[symbol.upper()],
        max_candidates=max_candidates,
        data_version=data_version,
        data_source="sqlite",
        asset_class="crypto",
        timeframe=interval,
        research_metadata={
            "market": "btc",
            "sweep_profile": "conservative",
            "generation_mode": "family_parameter_sweep",
        },
    )


__all__ = [
    "CandidateConfig",
    "CandidateGenerator",
    "DEFAULT_GATE_REQUIREMENTS",
    "StrategyFamilySpec",
    "StrategyFamilySweepConfig",
    "conservative_btc_strategy_family_sweep_config",
]
