from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import pandas as pd

from quant_crypto.research.long_short_trend_following_lab import (
    LongShortTrendSpec,
    aggregate_ohlcv,
    aggregate_ohlcv_calendar,
    long_short_trend_following_specs,
    raw_long_short_trend_signal,
)


SignalCallable = Callable[[pd.DataFrame, str], pd.Series]

STABLE_STRATEGY_LINE = "long_short_donchian_top5"
OKX_NATIVE_STRATEGY_LINE = "long_short_donchian_top5_okx_native"
HIGH_YIELD_STRATEGY_LINE = "high_yield_donchian_v2"
HIGH_OCTANE_STRATEGY_LINE = "high_octane_attack_sleeve_v2"

TOP5_VARIANT_IDS = (
    "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
    "formal_donchian_w240_d50_200_atr20_cd0_fail0_risknone",
    "formal_donchian_w240_d50_200_atr20_cd6_fail0_risknone",
    "formal_donchian_w180_d50_200_atr20_cd12_fail0_risknone",
    "formal_donchian_w180_d50_200_atr20_cd6_fail0_risknone",
)
HIGH_YIELD_CANDIDATE_ID = "hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff"
HIGH_OCTANE_CANDIDATE_ID = "ho_step0p35_core5x6_reserve5x2_attack10x2_cap2_max10_delaylate_none"
ATTACK_OBSERVER_CANDIDATE_ID = "attack_ref_core5x6_reserve5x2_attack10x2_max8_atkcap1_delaylate_noextract"


class BTCStrategyIdentityError(ValueError):
    pass


class BTCStrategyNotCanonicalError(BTCStrategyIdentityError):
    pass


@dataclass(frozen=True)
class BTCBacktestExecution:
    runner: str
    supported: bool
    position_capability: str
    params_policy: str
    target_weight: float
    execution_timing: str
    max_leverage: float | None

    @property
    def long_only(self) -> bool:
        return self.position_capability != "long_short"

    @property
    def uses_frozen_params(self) -> bool:
        return self.params_policy == "frozen_strategy_spec"

    def identity(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "supported": self.supported,
            "position_capability": self.position_capability,
            "params_policy": self.params_policy,
            "target_weight": self.target_weight,
            "execution_timing": self.execution_timing,
            "max_leverage": self.max_leverage,
        }


CANONICAL_LONG_SHORT_BACKTEST = BTCBacktestExecution(
    runner="canonical_registry_signal_event_backtest",
    supported=True,
    position_capability="long_short",
    params_policy="frozen_strategy_spec",
    target_weight=0.98,
    execution_timing="bar_close_signal_next_completed_1h_open",
    max_leverage=1.0,
)
IDENTITY_ONLY_BACKTEST = BTCBacktestExecution(
    runner="identity_only_no_single_position_adapter",
    supported=False,
    position_capability="unavailable",
    params_policy="frozen_strategy_spec",
    target_weight=0.0,
    execution_timing="unavailable",
    max_leverage=None,
)
LEGACY_DIAGNOSTIC_BACKTEST = BTCBacktestExecution(
    runner="legacy_request_defined_event_backtest",
    supported=True,
    position_capability="long_only",
    params_policy="request",
    target_weight=0.90,
    execution_timing="request_interval_signal_next_bar_open",
    max_leverage=None,
)


@dataclass(frozen=True)
class BTCStrategySpec:
    strategy_id: str
    candidate_id: str
    strategy_version: str
    params: Mapping[str, Any]
    instrument: str
    venue: str
    timeframe: str
    direction_policy: str
    promotion_eligibility: str
    promotion_credit_eligible: bool
    adapter_fidelity: str
    backtest_execution: BTCBacktestExecution
    signal_callable: SignalCallable | None = field(default=None, repr=False, compare=False)

    @property
    def params_hash(self) -> str:
        return _stable_hash(dict(self.params))

    @property
    def canonical_signal_available(self) -> bool:
        return self.signal_callable is not None

    def identity(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "candidate_id": self.candidate_id,
            "strategy_version": self.strategy_version,
            "params_hash": self.params_hash,
            "instrument": self.instrument,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "direction_policy": self.direction_policy,
            "promotion_eligibility": self.promotion_eligibility,
            "promotion_credit_eligible": self.promotion_credit_eligible,
            "adapter_fidelity": self.adapter_fidelity,
            "backtest_execution": self.backtest_execution.identity(),
            "canonical_signal_available": self.canonical_signal_available,
            "strategy_callable": self.signal_callable.__name__ if self.signal_callable is not None else "",
        }


@dataclass(frozen=True)
class BTCStrategyRegistry:
    specs: tuple[BTCStrategySpec, ...]

    def list_specs(self) -> list[BTCStrategySpec]:
        return list(self.specs)

    def get(self, strategy_id: str, candidate_id: str = "") -> BTCStrategySpec:
        matching = [spec for spec in self.specs if spec.strategy_id == strategy_id]
        if not matching:
            raise BTCStrategyIdentityError(f"unknown BTC strategy line: {strategy_id}")
        if candidate_id:
            for spec in matching:
                if spec.candidate_id == candidate_id:
                    return spec
            raise BTCStrategyIdentityError(
                f"candidate_id does not belong to strategy line: {strategy_id}/{candidate_id}"
            )
        return matching[0]

    def resolve_request(
        self,
        *,
        strategy_id: str,
        candidate_id: str = "",
        strategy_version: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> BTCStrategySpec:
        matching = [spec for spec in self.specs if spec.strategy_id == strategy_id]
        if not matching:
            if candidate_id and any(spec.candidate_id == candidate_id for spec in self.specs):
                raise BTCStrategyIdentityError("generic strategy cannot impersonate a BTC promotion candidate")
            return legacy_diagnostic_spec(
                strategy_id=strategy_id,
                params=params or {},
                strategy_version=strategy_version,
            )
        spec = self.get(strategy_id, candidate_id)
        if strategy_version and strategy_version != spec.strategy_version:
            raise BTCStrategyIdentityError(
                f"strategy_version mismatch: expected {spec.strategy_version}, got {strategy_version}"
            )
        if params and _stable_hash(dict(params)) != spec.params_hash:
            raise BTCStrategyIdentityError(
                f"frozen params mismatch for {spec.candidate_id}: expected {spec.params_hash}"
            )
        return spec


def build_btc_strategy_registry() -> BTCStrategyRegistry:
    formal_specs = {
        spec.variant_id: spec
        for spec in long_short_trend_following_specs(run_profile="formal_narrow")
    }
    specs: list[BTCStrategySpec] = []
    for variant_id in TOP5_VARIANT_IDS:
        trend_spec = formal_specs[variant_id]
        signal_callable = _top5_signal_callable(trend_spec)
        if str(trend_spec.params.get("risk_filter_mode") or "none") != "none":
            raise RuntimeError(f"Top5 canonical adapter unexpectedly requires derivatives data: {variant_id}")
        specs.append(
            BTCStrategySpec(
                strategy_id=STABLE_STRATEGY_LINE,
                candidate_id=trend_spec.candidate_id,
                strategy_version="btc_long_short_donchian_top5@1.0.0",
                params=dict(trend_spec.params),
                instrument="BTC-USDT-SWAP",
                venue="OKX",
                timeframe="completed_1h_to_4h",
                direction_policy="long_short",
                promotion_eligibility="candidate_identity_only_requires_all_promotion_gates",
                promotion_credit_eligible=True,
                adapter_fidelity="exact_frozen_signal_formula_next_bar_execution",
                backtest_execution=CANONICAL_LONG_SHORT_BACKTEST,
                signal_callable=signal_callable,
            )
        )
        specs.append(
            BTCStrategySpec(
                strategy_id=OKX_NATIVE_STRATEGY_LINE,
                candidate_id=f"okx_native_{trend_spec.candidate_id}",
                strategy_version="btc_long_short_donchian_top5_okx_native@1.0.0",
                params=dict(trend_spec.params),
                instrument="BTC-USDT-SWAP",
                venue="OKX",
                timeframe="completed_1h_to_4h",
                direction_policy="long_short",
                promotion_eligibility="candidate_identity_only_requires_okx_native_evidence_and_all_promotion_gates",
                promotion_credit_eligible=True,
                adapter_fidelity="exact_frozen_signal_formula_next_bar_execution_okx_native_data",
                backtest_execution=CANONICAL_LONG_SHORT_BACKTEST,
                signal_callable=signal_callable,
            )
        )
    specs.extend(
        [
            BTCStrategySpec(
                strategy_id=HIGH_YIELD_STRATEGY_LINE,
                candidate_id=HIGH_YIELD_CANDIDATE_ID,
                strategy_version="btc_high_yield_donchian_v2@1.0.0",
                params={
                    "base_variant": TOP5_VARIANT_IDS[0],
                    "vol_target_pct": 120.0,
                    "max_leverage": 2.5,
                    "drawdown_gate_pct": 25.0,
                    "min_liquidation_buffer_bps": 1200,
                },
                instrument="BTC-USDT-SWAP",
                venue="OKX",
                timeframe="completed_1h_to_4h",
                direction_policy="long_short_volatility_target_overlay",
                promotion_eligibility="blocked_until_perpetual_leverage_ledger_adapter_exists",
                promotion_credit_eligible=False,
                adapter_fidelity="identity_only_overlay_not_representable_by_single_position_runner",
                backtest_execution=IDENTITY_ONLY_BACKTEST,
            ),
            BTCStrategySpec(
                strategy_id=HIGH_OCTANE_STRATEGY_LINE,
                candidate_id=HIGH_OCTANE_CANDIDATE_ID,
                strategy_version="btc_high_octane_attack_sleeve_v2@1.0.0",
                params={
                    "atr_step": 0.35,
                    "core_leverage": 5.0,
                    "core_count": 6,
                    "reserve_leverage": 5.0,
                    "reserve_count": 2,
                    "attack_leverage": 10.0,
                    "attack_count": 2,
                    "attack_cap": 2,
                    "max_total_exposed": 10,
                    "attack_delay_profile": "late",
                    "extract_policy": "none",
                },
                instrument="BTC-USDT-SWAP isolated sleeves",
                venue="OKX",
                timeframe="completed_1h_to_4h",
                direction_policy="long_short_multi_sleeve_overlay",
                promotion_eligibility="research_only_boundary_mined_no_canonical_multi_sleeve_ledger",
                promotion_credit_eligible=False,
                adapter_fidelity="identity_only_multi_sleeve_overlay_not_representable_by_single_position_runner",
                backtest_execution=IDENTITY_ONLY_BACKTEST,
            ),
            BTCStrategySpec(
                strategy_id=HIGH_OCTANE_STRATEGY_LINE,
                candidate_id=ATTACK_OBSERVER_CANDIDATE_ID,
                strategy_version="btc_attack_sleeve_limited_exposure@1.0.0",
                params={
                    "core_leverage": 5.0,
                    "core_count": 6,
                    "reserve_leverage": 5.0,
                    "reserve_count": 2,
                    "attack_leverage": 10.0,
                    "attack_count": 2,
                    "attack_cap": 1,
                    "max_total_exposed": 8,
                    "attack_delay_profile": "late",
                    "extract_policy": "none",
                },
                instrument="BTC-USDT-SWAP isolated sleeves",
                venue="OKX",
                timeframe="completed_1h_to_4h",
                direction_policy="long_short_multi_sleeve_overlay",
                promotion_eligibility="observe_only_identity_no_canonical_multi_sleeve_ledger",
                promotion_credit_eligible=False,
                adapter_fidelity="identity_only_multi_sleeve_overlay_not_representable_by_single_position_runner",
                backtest_execution=IDENTITY_ONLY_BACKTEST,
            ),
        ]
    )
    return BTCStrategyRegistry(tuple(specs))


def legacy_diagnostic_spec(
    *,
    strategy_id: str,
    params: Mapping[str, Any],
    strategy_version: str = "",
) -> BTCStrategySpec:
    return BTCStrategySpec(
        strategy_id=strategy_id,
        candidate_id=f"legacy_diagnostic:{strategy_id}",
        strategy_version=strategy_version or f"{strategy_id}:legacy_registry_signal_replay_v1",
        params=dict(params),
        instrument="BTCUSDT diagnostic",
        venue="generic",
        timeframe="request_defined",
        direction_policy="legacy_registry_defined",
        promotion_eligibility="legacy_diagnostic_no_promotion_credit",
        promotion_credit_eligible=False,
        adapter_fidelity="legacy_generic_registry_signal",
        backtest_execution=LEGACY_DIAGNOSTIC_BACKTEST,
    )


def compare_strategy_identities(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for field_name in ("strategy_id", "candidate_id", "strategy_version", "params_hash"):
        expected_value = str(expected.get(field_name) or "")
        observed_value = str(observed.get(field_name) or "")
        if not expected_value or not observed_value or expected_value != observed_value:
            blockers.append(f"btc_strategy_identity_mismatch:{field_name}")
    return blockers


def _top5_signal_callable(trend_spec: LongShortTrendSpec) -> SignalCallable:
    def generate_top5_signal(frame: pd.DataFrame, interval: str) -> pd.Series:
        if interval != "1h":
            raise BTCStrategyNotCanonicalError(
                "Long/Short Donchian Top5 canonical path requires completed BTC 1h input and derives 4h bars internally"
            )
        bars_1h = _prepare_completed_hourly_frame(frame)
        bars_4h = aggregate_ohlcv(bars_1h, interval_hours=4)
        bars_1d = aggregate_ohlcv(bars_1h, interval_hours=24)
        # These four existing signal branches consume only 4h/daily bars.
        # Preserve the general fallback for any newly registered signal type.
        if trend_spec.params.get("signal_type") in {
            "symmetric_donchian", "symmetric_ema_ribbon", "hybrid_donchian_ema_atr", "symmetric_atr_channel",
        }:
            bars_1w = pd.DataFrame()
            bars_1mo = pd.DataFrame()
        else:
            bars_1w = aggregate_ohlcv_calendar(bars_1h, timeframe="1w")
            bars_1mo = aggregate_ohlcv_calendar(bars_1h, timeframe="1mo")
        derivatives = pd.DataFrame(index=bars_4h.index)
        raw = raw_long_short_trend_signal(
            trend_spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives,
        )
        # The event engine executes the emitted target on the next 1h bar open.
        return raw.reindex(bars_1h.index, method="ffill").fillna(0.0).clip(-1.0, 1.0)

    generate_top5_signal.__name__ = f"generate_{trend_spec.variant_id}"
    return generate_top5_signal


def _prepare_completed_hourly_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise BTCStrategyNotCanonicalError(f"BTC canonical 1h frame missing columns: {missing}")
    output = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(output.index, utc=True))
    output.index = index
    output = output.sort_index()
    output["open_time"] = output.index.floor("h")
    for column in required:
        output[column] = pd.to_numeric(output[column], errors="coerce")
    output = output.dropna(subset=list(required))
    return output


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


btc_strategy_registry = build_btc_strategy_registry()
