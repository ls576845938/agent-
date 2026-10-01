from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from quant_shared.core.time import ensure_utc


BTC_PERP_LIQUIDATION_RISK_VERSION = "btc_perp_liquidation_risk_v1"


@dataclass(frozen=True)
class BTCReferencePriceState:
    observed_at_utc: datetime
    signal_price: float
    execution_price: float
    mark_price: float | None
    index_price: float | None
    current_mark_price: float | None
    primary_mid: float | None = None
    secondary_reference_mid: float | None = None
    spread_bps: float | None = None
    cross_venue_deviation_bps: float | None = None
    data_age_ms: int = 0
    order_book_depth_usd: float | None = None
    source: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))
        for field_name in ("signal_price", "execution_price"):
            value = float(getattr(self, field_name))
            if value <= 0.0:
                raise ValueError(f"{field_name} must be positive.")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "mark_price",
            "index_price",
            "current_mark_price",
            "primary_mid",
            "secondary_reference_mid",
            "spread_bps",
            "cross_venue_deviation_bps",
            "order_book_depth_usd",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, float(value))
        object.__setattr__(self, "data_age_ms", max(0, int(self.data_age_ms)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at_utc": self.observed_at_utc.isoformat(),
            "signal_price": self.signal_price,
            "execution_price": self.execution_price,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "current_mark_price": self.current_mark_price,
            "primary_mid": self.primary_mid,
            "secondary_reference_mid": self.secondary_reference_mid,
            "spread_bps": self.spread_bps,
            "cross_venue_deviation_bps": self.cross_venue_deviation_bps,
            "data_age_ms": self.data_age_ms,
            "order_book_depth_usd": self.order_book_depth_usd,
            "source": self.source,
        }


@dataclass(frozen=True)
class BTCLiquidationPolicy:
    max_leverage: float
    maintenance_margin_rate: float
    min_liquidation_buffer_bps: float
    max_reference_price_age_ms: int
    max_cross_venue_deviation_bps: float
    max_spread_bps: float
    min_order_book_depth_usd: float = 0.0

    def __post_init__(self) -> None:
        for field_name in (
            "max_leverage",
            "maintenance_margin_rate",
            "min_liquidation_buffer_bps",
            "max_reference_price_age_ms",
            "max_cross_venue_deviation_bps",
            "max_spread_bps",
            "min_order_book_depth_usd",
        ):
            value = float(getattr(self, field_name))
            if value < 0.0:
                raise ValueError(f"{field_name} must be non-negative.")
            object.__setattr__(self, field_name, value)
        if self.max_leverage <= 0.0:
            raise ValueError("max_leverage must be positive.")
        if self.maintenance_margin_rate >= 1.0:
            raise ValueError("maintenance_margin_rate must be below 1.")


@dataclass(frozen=True)
class BTCPerpPositionState:
    current_quantity: float
    proposed_quantity: float
    account_equity: float
    side: str = "long"

    def __post_init__(self) -> None:
        object.__setattr__(self, "current_quantity", float(self.current_quantity))
        object.__setattr__(self, "proposed_quantity", float(self.proposed_quantity))
        object.__setattr__(self, "account_equity", float(self.account_equity))
        if self.account_equity <= 0.0:
            raise ValueError("account_equity must be positive.")
        if self.side not in {"long", "short", "flat"}:
            raise ValueError("side must be long/short/flat.")


@dataclass(frozen=True)
class BTCPerpRiskDecision:
    approved: bool
    action: str
    blockers: list[str]
    warnings: list[str]
    liquidation_price: float | None
    liquidation_buffer_bps: float | None
    leverage: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "risk_model_version": BTC_PERP_LIQUIDATION_RISK_VERSION,
            "approved": self.approved,
            "action": self.action,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "liquidation_price": self.liquidation_price,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "leverage": self.leverage,
            **dict(self.metadata),
        }


def evaluate_btc_perp_liquidation_risk(
    *,
    reference_prices: BTCReferencePriceState,
    position: BTCPerpPositionState,
    policy: BTCLiquidationPolicy,
) -> BTCPerpRiskDecision:
    blockers: list[str] = []
    warnings: list[str] = []
    if reference_prices.mark_price is None:
        blockers.append("btc_mark_price_missing")
    if reference_prices.index_price is None:
        blockers.append("btc_index_price_missing")
    if reference_prices.current_mark_price is None:
        blockers.append("btc_current_mark_price_missing")
    if reference_prices.data_age_ms > policy.max_reference_price_age_ms:
        blockers.append("btc_reference_price_stale")
    if (
        reference_prices.cross_venue_deviation_bps is not None
        and abs(reference_prices.cross_venue_deviation_bps) > policy.max_cross_venue_deviation_bps
    ):
        blockers.append("btc_cross_venue_deviation_breach")
    if reference_prices.spread_bps is not None and reference_prices.spread_bps > policy.max_spread_bps:
        blockers.append("btc_spread_breach")
    if (
        policy.min_order_book_depth_usd > 0.0
        and reference_prices.order_book_depth_usd is not None
        and reference_prices.order_book_depth_usd < policy.min_order_book_depth_usd
    ):
        blockers.append("btc_order_book_depth_breach")

    mark_price = reference_prices.current_mark_price or reference_prices.mark_price or reference_prices.execution_price
    notional = abs(position.proposed_quantity) * mark_price
    leverage = notional / position.account_equity
    liquidation_price = None
    buffer_bps = None
    if leverage > policy.max_leverage:
        blockers.append("btc_leverage_breach")
    if position.proposed_quantity != 0.0 and mark_price > 0.0:
        liquidation_price = _estimate_liquidation_price(
            entry_price=reference_prices.execution_price,
            side="long" if position.proposed_quantity > 0.0 else "short",
            leverage=max(leverage, 1e-12),
            maintenance_margin_rate=policy.maintenance_margin_rate,
        )
        buffer_bps = _liquidation_buffer_bps(
            mark_price=mark_price,
            liquidation_price=liquidation_price,
            side="long" if position.proposed_quantity > 0.0 else "short",
        )
        if buffer_bps < policy.min_liquidation_buffer_bps:
            blockers.append("btc_liquidation_buffer_breach")

    action = "approve"
    if blockers:
        action = "hold" if position.current_quantity == position.proposed_quantity else "reduce_or_reject"
    return BTCPerpRiskDecision(
        approved=not blockers,
        action=action,
        blockers=_dedupe(blockers),
        warnings=warnings,
        liquidation_price=liquidation_price,
        liquidation_buffer_bps=buffer_bps,
        leverage=leverage,
        metadata={
            "reference_prices": reference_prices.to_dict(),
            "policy": {
                "max_leverage": policy.max_leverage,
                "maintenance_margin_rate": policy.maintenance_margin_rate,
                "min_liquidation_buffer_bps": policy.min_liquidation_buffer_bps,
                "max_reference_price_age_ms": policy.max_reference_price_age_ms,
                "max_cross_venue_deviation_bps": policy.max_cross_venue_deviation_bps,
                "max_spread_bps": policy.max_spread_bps,
                "min_order_book_depth_usd": policy.min_order_book_depth_usd,
            },
            "position": {
                "current_quantity": position.current_quantity,
                "proposed_quantity": position.proposed_quantity,
                "account_equity": position.account_equity,
                "side": position.side,
            },
        },
    )


def _estimate_liquidation_price(
    *,
    entry_price: float,
    side: str,
    leverage: float,
    maintenance_margin_rate: float,
) -> float:
    margin_fraction = 1.0 / leverage
    if side == "long":
        return max(0.0, entry_price * (1.0 - margin_fraction + maintenance_margin_rate))
    return entry_price * (1.0 + margin_fraction - maintenance_margin_rate)


def _liquidation_buffer_bps(*, mark_price: float, liquidation_price: float, side: str) -> float:
    if side == "long":
        return max(0.0, (mark_price - liquidation_price) / mark_price * 10_000.0)
    return max(0.0, (liquidation_price - mark_price) / mark_price * 10_000.0)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
