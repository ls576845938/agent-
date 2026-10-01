"""Pure BTC risk contracts for Shared Platform V3 T2.

This module is deliberately a small, asset-owned calculation boundary.  It
does not grant execution permission and it has no access to runtime state,
files, clocks, environment variables, brokers, or order adapters.  Callers
must provide every fact used by an assessment; missing or non-finite facts are
represented as stable fail-closed blockers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

from quant_shared.runtime import RuntimeRiskEffect

from .liquidation import (
    BTCPerpPositionState,
    BTCReferencePriceState,
    BTCLiquidationPolicy,
    evaluate_btc_perp_liquidation_risk,
)


BTC_SHARED_PLATFORM_V3_T2_VERSION = "btc_shared_platform_v3_t2"

# T1 owns the asset-neutral vocabulary.  T2 only publishes the BTC-domain
# name so consumers cannot accidentally invent a second enum.
ActionRiskEffect = RuntimeRiskEffect


class UnknownInputPolicy(str, Enum):
    """How a pure assessment treats a missing or invalid required fact."""

    REJECT = "reject"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RiskConstitution:
    """Explicit BTC risk limits; there are no implicit venue defaults."""

    max_abs_position: float
    max_quantity: float
    max_notional: float
    max_leverage: float
    min_liquidation_buffer_bps: float
    max_daily_loss: float
    max_drawdown: float
    max_combined_loss: float
    protection_required: bool = True
    unknown_input_policy: UnknownInputPolicy | str = UnknownInputPolicy.REJECT
    maintenance_margin_rate: float = 0.005

    def __post_init__(self) -> None:
        positive = (
            "max_abs_position",
            "max_quantity",
            "max_notional",
            "max_leverage",
        )
        nonnegative = (
            "min_liquidation_buffer_bps",
            "max_daily_loss",
            "max_drawdown",
            "max_combined_loss",
            "maintenance_margin_rate",
        )
        for name in positive:
            value = float(getattr(self, name))
            if not isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be a finite positive number")
            object.__setattr__(self, name, value)
        for name in nonnegative:
            value = float(getattr(self, name))
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be a finite non-negative number")
            object.__setattr__(self, name, value)
        policy = self.unknown_input_policy
        if not isinstance(policy, UnknownInputPolicy):
            try:
                policy = UnknownInputPolicy(str(policy).lower())
            except ValueError as exc:
                raise ValueError("unknown_input_policy must be reject or unknown") from exc
        if not isinstance(self.protection_required, bool):
            raise ValueError("protection_required must be a boolean")
        object.__setattr__(self, "unknown_input_policy", policy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": BTC_SHARED_PLATFORM_V3_T2_VERSION,
            "max_abs_position": self.max_abs_position,
            "max_quantity": self.max_quantity,
            "max_notional": self.max_notional,
            "max_leverage": self.max_leverage,
            "min_liquidation_buffer_bps": self.min_liquidation_buffer_bps,
            "max_daily_loss": self.max_daily_loss,
            "max_drawdown": self.max_drawdown,
            "max_combined_loss": self.max_combined_loss,
            "protection_required": self.protection_required,
            "unknown_input_policy": self.unknown_input_policy.value,
            "maintenance_margin_rate": self.maintenance_margin_rate,
        }


BTCSharedRiskConstitution = RiskConstitution


@dataclass(frozen=True)
class CombinedLossAssessment:
    """Deterministic loss aggregation with a fixed sign convention.

    PnL and funding cashflow are signed (positive is a gain/inflow).  Fees,
    slippage, and market impact are non-negative deductions.  Consequently
    ``net_pnl = realized + unrealized + funding - costs`` and ``loss_amount``
    is the positive amount below zero.
    """

    net_pnl: float | None
    loss_amount: float | None
    loss_ratio: float | None
    blockers: tuple[str, ...] = ()
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    funding_cashflow: float | None = None
    fees: float | None = None
    slippage: float | None = None
    impact: float | None = None

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    @property
    def approved(self) -> bool:
        return not self.blocked

    @property
    def reasons(self) -> tuple[str, ...]:
        return self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "net_pnl": self.net_pnl,
            "loss_amount": self.loss_amount,
            "loss_ratio": self.loss_ratio,
            "blockers": list(self.blockers),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "funding_cashflow": self.funding_cashflow,
            "fees": self.fees,
            "slippage": self.slippage,
            "impact": self.impact,
        }


BTCCombinedLoss = CombinedLossAssessment


@dataclass(frozen=True)
class ProtectionFeasibility:
    allowed: bool
    requires_protection: bool
    removal_allowed: bool
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_protection": self.requires_protection,
            "removal_allowed": self.removal_allowed,
            "blockers": list(self.blockers),
        }


ProtectionFeasibilityResult = ProtectionFeasibility


@dataclass(frozen=True)
class RiskAssessment:
    """Pure risk result; ``execution_permission`` is always false."""

    approved: bool
    status: str
    effect: ActionRiskEffect
    blockers: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    requires_reduction: bool = False
    max_safe_quantity: float | None = None
    notional: float | None = None
    leverage: float | None = None
    liquidation_buffer_bps: float | None = None
    execution_permission: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.execution_permission is not False:
            raise ValueError("risk kernel never grants execution permission")
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @property
    def blocked(self) -> bool:
        return not self.approved

    @property
    def risk_effect(self) -> ActionRiskEffect:
        return self.effect

    @property
    def constraint_violations(self) -> tuple[str, ...]:
        return self.blockers

    @property
    def reduction_required(self) -> bool:
        return self.requires_reduction

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": BTC_SHARED_PLATFORM_V3_T2_VERSION,
            "approved": self.approved,
            "status": self.status,
            "effect": self.effect.value,
            "blockers": list(self.blockers),
            "reasons": list(self.reasons),
            "requires_reduction": self.requires_reduction,
            "max_safe_quantity": self.max_safe_quantity,
            "notional": self.notional,
            "leverage": self.leverage,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "execution_permission": False,
            "metadata": _thaw(self.metadata),
        }


BTCRiskAssessment = RiskAssessment


_BLOCKER_ORDER = (
    "unknown_input_rejected",
    "unknown_input_unknown",
    "unknown_input",
    "nonfinite_input",
    "position_missing",
    "mark_price_missing",
    "mark_price_invalid",
    "index_price_missing",
    "index_price_invalid",
    "account_equity_missing",
    "max_quantity_breach",
    "max_abs_position_breach",
    "max_notional_breach",
    "max_leverage_breach",
    "liquidation_risk_blocked",
    "combined_loss_limit_breach",
    "daily_loss_limit_breach",
    "drawdown_limit_breach",
    "protection_required",
    "protection_missing",
    "protection_invalid",
    "protection_removal_not_atomic",
    "cross_zero_position",
    "effect_unknown",
)
_BLOCKER_RANK = {value: index for index, value in enumerate(_BLOCKER_ORDER)}


def _ordered_unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return tuple(sorted(deduped, key=lambda value: (_BLOCKER_RANK.get(value, len(_BLOCKER_ORDER)), value)))


def _freeze(value: Any) -> Any:
    """Recursively freeze metadata so nested mappings cannot be mutated."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Return an independent JSON-friendly copy of frozen metadata."""

    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_thaw(item) for item in value)
    return value


def _policy_blocker(constitution: RiskConstitution) -> str:
    return (
        "unknown_input_rejected"
        if constitution.unknown_input_policy is UnknownInputPolicy.REJECT
        else "unknown_input_unknown"
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _field(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    return default


def _protection_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    present = _field(value, "present", "active", "enabled", default=None)
    return bool(present) if present is not None else True


def _protection_valid(value: Any, position: float, mark_price: float | None) -> bool:
    if not _protection_present(value):
        return False
    mark = _number(mark_price)
    if mark is None or mark <= 0.0:
        return False
    quantity = _number(_field(value, "quantity", "qty", "size", default=None))
    trigger = _number(_field(value, "trigger_price", "trigger", "price", default=None))
    side = str(_field(value, "side", "direction", default="")).lower()
    expected_side = "sell" if position > 0.0 else "buy"
    return (
        quantity is not None
        and quantity > 0.0
        and quantity >= abs(position)
        and trigger is not None
        and trigger > 0.0
        and ((position > 0.0 and trigger < mark) or (position < 0.0 and trigger > mark))
        and side == expected_side
    )


def classify_action_risk_effect(
    position_before: float | None,
    position_after: float | None,
    protection_before: Any = None,
    protection_after: Any = None,
    *,
    atomic_protection_replacement: bool = False,
) -> ActionRiskEffect:
    """Classify signed exposure from positions, never from a caller label."""

    before = _number(position_before)
    after = _number(position_after)
    if before is None or after is None:
        return ActionRiskEffect.UNKNOWN
    if before * after < 0.0:
        return ActionRiskEffect.UNKNOWN
    before_protected = _protection_present(protection_before)
    after_protected = _protection_present(protection_after)
    if abs(after) < abs(before):
        return ActionRiskEffect.DECREASE_ABS_EXPOSURE
    if abs(after) > abs(before):
        return ActionRiskEffect.INCREASE_ABS_EXPOSURE
    if before_protected and not after_protected:
        if atomic_protection_replacement:
            return ActionRiskEffect.REMOVE_PROTECTION
        return ActionRiskEffect.UNKNOWN
    if not before_protected and after_protected and abs(after) == abs(before):
        return ActionRiskEffect.ADD_PROTECTION
    return ActionRiskEffect.NO_POSITION_EFFECT


def classify_action_effect(*args: Any, **kwargs: Any) -> ActionRiskEffect:
    return classify_action_risk_effect(*args, **kwargs)


def evaluate_combined_loss(
    realized_pnl: float,
    unrealized_pnl: float,
    funding_cashflow: float,
    fees: float = 0.0,
    slippage: float = 0.0,
    impact: float = 0.0,
    *,
    account_equity: float | None = None,
    constitution: RiskConstitution | None = None,
    daily_loss: float | None = None,
    drawdown: float | None = None,
) -> CombinedLossAssessment:
    """Aggregate signed PnL/cashflow and explicit non-negative cost fields."""

    values = [realized_pnl, unrealized_pnl, funding_cashflow, fees, slippage, impact]
    numbers = [_number(value) for value in values]
    blockers: list[str] = []
    if any(value is None for value in numbers):
        blockers.append("nonfinite_input")
        return CombinedLossAssessment(None, None, None, _ordered_unique(blockers))
    realized, unrealized, funding, fee_value, slip_value, impact_value = numbers  # type: ignore[misc]
    if any(value < 0.0 for value in (fee_value, slip_value, impact_value)):
        blockers.append("cost_input_invalid")
    net = realized + unrealized + funding - fee_value - slip_value - impact_value
    equity = _number(account_equity) if account_equity is not None else None
    ratio = None
    if account_equity is not None and (equity is None or equity <= 0.0):
        blockers.append("account_equity_missing")
    elif equity is not None:
        ratio = max(0.0, -net) / equity
    loss = max(0.0, -net)
    if constitution is not None:
        if loss > constitution.max_combined_loss:
            blockers.append("combined_loss_limit_breach")
        if loss > constitution.max_daily_loss:
            blockers.append("daily_loss_limit_breach")
        if ratio is not None and ratio > constitution.max_drawdown:
            blockers.append("drawdown_limit_breach")
    if daily_loss is not None:
        daily = _number(daily_loss)
        if daily is None:
            blockers.append("nonfinite_input")
        elif constitution is not None and daily > constitution.max_daily_loss:
            blockers.append("daily_loss_limit_breach")
    if drawdown is not None:
        current_drawdown = _number(drawdown)
        if current_drawdown is None:
            blockers.append("nonfinite_input")
        elif constitution is not None and current_drawdown > constitution.max_drawdown:
            blockers.append("drawdown_limit_breach")
    return CombinedLossAssessment(
        net,
        loss,
        ratio,
        _ordered_unique(blockers),
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        funding_cashflow=funding,
        fees=fee_value,
        slippage=slip_value,
        impact=impact_value,
    )


def evaluate_btc_combined_loss(*args: Any, **kwargs: Any) -> CombinedLossAssessment:
    return evaluate_combined_loss(*args, **kwargs)


def evaluate_protection_feasibility(
    position_before: float | None,
    position_after: float | None,
    protection_before: Any = None,
    protection_after: Any = None,
    *,
    mark_price: float | None = None,
    protection_required: bool = True,
    atomic_protection_replacement: bool = False,
) -> ProtectionFeasibility:
    before = _number(position_before)
    after = _number(position_after)
    blockers: list[str] = []
    if before is None or after is None:
        return ProtectionFeasibility(False, False, False, ("nonfinite_input",))
    mark = _number(mark_price)
    if mark is None:
        return ProtectionFeasibility(False, abs(after) > 0.0, False, ("mark_price_missing",))
    if mark <= 0.0:
        return ProtectionFeasibility(False, abs(after) > 0.0, False, ("mark_price_invalid",))
    required = protection_required and abs(after) > 0.0
    after_present = _protection_present(protection_after)
    before_present = _protection_present(protection_before)
    if required:
        if not after_present:
            if before_present and not atomic_protection_replacement:
                blockers.append("protection_removal_not_atomic")
            else:
                blockers.extend(("protection_required", "protection_missing"))
        elif not _protection_valid(protection_after, after, mark):
            blockers.append("protection_invalid")
    if before_present and not after_present and abs(after) > 0.0 and not atomic_protection_replacement:
        blockers.append("protection_removal_not_atomic")
    removal_allowed = abs(after) == 0.0 or atomic_protection_replacement
    return ProtectionFeasibility(
        allowed=not blockers,
        requires_protection=required,
        removal_allowed=removal_allowed,
        blockers=_ordered_unique(blockers),
    )


def evaluate_protection(*args: Any, **kwargs: Any) -> ProtectionFeasibility:
    return evaluate_protection_feasibility(*args, **kwargs)


def _safe_quantity(*, constitution: RiskConstitution, mark: float, equity: float) -> float:
    return min(
        constitution.max_abs_position,
        constitution.max_quantity,
        constitution.max_notional / mark,
        constitution.max_leverage * equity / mark,
    )


def assess_btc_risk(
    *,
    constitution: RiskConstitution,
    position_before: float | None = None,
    position_after: float | None = None,
    current_position: float | None = None,
    proposed_position: float | None = None,
    mark_price: float | None = None,
    index_price: float | None = None,
    account_equity: float | None = None,
    protection_before: Any = None,
    protection_after: Any = None,
    protection: Any = None,
    atomic_protection_replacement: bool = False,
    reference_prices: BTCReferencePriceState | None = None,
    combined_loss: CombinedLossAssessment | None = None,
    realized_pnl: float | None = None,
    unrealized_pnl: float | None = None,
    funding_cashflow: float | None = None,
    fees: float = 0.0,
    slippage: float = 0.0,
    impact: float = 0.0,
) -> RiskAssessment:
    """Evaluate explicit BTC facts without producing an execution decision."""

    before = position_before if position_before is not None else current_position
    after = position_after if position_after is not None else proposed_position
    if protection_after is None and protection is not None:
        protection_after = protection
    before_value = _number(before)
    after_value = _number(after)
    mark = _number(mark_price if mark_price is not None else (_field(reference_prices, "mark_price", default=None)))
    index = _number(index_price if index_price is not None else (_field(reference_prices, "index_price", default=None)))
    equity = _number(account_equity)
    blockers: list[str] = []
    if before_value is None or after_value is None:
        blockers.append("position_missing")
    if mark is None:
        blockers.append("mark_price_missing")
    if index is None:
        blockers.append("index_price_missing")
    if equity is None or equity <= 0.0:
        blockers.append("account_equity_missing")
    if blockers:
        return _assessment_from_blockers(
            blockers,
            effect=ActionRiskEffect.UNKNOWN,
            position_before=before_value,
            position_after=after_value,
            constitution=constitution,
            input_unknown=True,
        )
    assert before_value is not None and after_value is not None and mark is not None and index is not None and equity is not None
    if mark <= 0.0 or index <= 0.0:
        return _assessment_from_blockers(
            [
                "mark_price_invalid"
                if mark <= 0.0
                else "index_price_invalid"
                if index <= 0.0
                else "nonfinite_input"
            ],
            effect=ActionRiskEffect.UNKNOWN,
            position_before=before_value,
            position_after=after_value,
            constitution=constitution,
            input_unknown=True,
        )
    effect = classify_action_risk_effect(
        before_value,
        after_value,
        protection_before,
        protection_after,
        atomic_protection_replacement=atomic_protection_replacement,
    )
    if effect is ActionRiskEffect.UNKNOWN:
        blockers.append("effect_unknown")
    if before_value * after_value < 0.0:
        blockers.append("cross_zero_position")
    absolute_after = abs(after_value)
    notional = absolute_after * mark
    leverage = notional / equity
    if absolute_after > constitution.max_quantity:
        blockers.append("max_quantity_breach")
    if absolute_after > constitution.max_abs_position:
        blockers.append("max_abs_position_breach")
    if notional > constitution.max_notional:
        blockers.append("max_notional_breach")
    if leverage > constitution.max_leverage:
        blockers.append("max_leverage_breach")

    if reference_prices is not None and not isinstance(reference_prices, BTCReferencePriceState):
        try:
            reference_prices = BTCReferencePriceState(
                observed_at_utc=_field(reference_prices, "observed_at_utc"),
                signal_price=_field(reference_prices, "signal_price", default=mark),
                execution_price=_field(reference_prices, "execution_price", default=mark),
                mark_price=_field(reference_prices, "mark_price"),
                index_price=_field(reference_prices, "index_price"),
                current_mark_price=_field(reference_prices, "current_mark_price"),
                primary_mid=_field(reference_prices, "primary_mid"),
                secondary_reference_mid=_field(reference_prices, "secondary_reference_mid"),
                spread_bps=_field(reference_prices, "spread_bps"),
                cross_venue_deviation_bps=_field(reference_prices, "cross_venue_deviation_bps"),
                data_age_ms=_field(reference_prices, "data_age_ms", default=0),
                order_book_depth_usd=_field(reference_prices, "order_book_depth_usd"),
                source=str(_field(reference_prices, "source", default="explicit")),
            )
        except (TypeError, ValueError, AttributeError):
            return _assessment_from_blockers(
                ["unknown_input"],
                effect=ActionRiskEffect.UNKNOWN,
                position_before=before_value,
                position_after=after_value,
                constitution=constitution,
                input_unknown=True,
            )
    if reference_prices is None:
        reference_prices = BTCReferencePriceState(
            # A fixed timestamp keeps the synthetic compatibility envelope
            # deterministic; no wall clock belongs in this pure kernel.
            observed_at_utc=datetime(1970, 1, 1, tzinfo=timezone.utc),
            signal_price=mark,
            execution_price=mark,
            mark_price=mark,
            index_price=index,
            current_mark_price=mark,
            spread_bps=0.0,
            cross_venue_deviation_bps=0.0,
            data_age_ms=0,
            order_book_depth_usd=0.0,
            source="explicit",
        )
    for reference_name in (
        "mark_price",
        "index_price",
        "current_mark_price",
        "spread_bps",
        "cross_venue_deviation_bps",
        "order_book_depth_usd",
    ):
        reference_value = getattr(reference_prices, reference_name, None)
        if reference_value is not None and _number(reference_value) is None:
            return _assessment_from_blockers(
                ["nonfinite_input"],
                effect=ActionRiskEffect.UNKNOWN,
                position_before=before_value,
                position_after=after_value,
                constitution=constitution,
                input_unknown=True,
            )
    # The existing function remains the single liquidation formula.  T2's
    # explicit mark/index checks above prevent its compatibility fallbacks
    # from turning missing facts into an approval.
    try:
        liquidation = evaluate_btc_perp_liquidation_risk(
            reference_prices=reference_prices,
            position=BTCPerpPositionState(
                current_quantity=before_value,
                proposed_quantity=after_value,
                account_equity=equity,
                side="long" if after_value > 0.0 else "short" if after_value < 0.0 else "flat",
            ),
            policy=BTCLiquidationPolicy(
                max_leverage=constitution.max_leverage,
                maintenance_margin_rate=constitution.maintenance_margin_rate,
                min_liquidation_buffer_bps=constitution.min_liquidation_buffer_bps,
                max_reference_price_age_ms=0,
                max_cross_venue_deviation_bps=1_000_000_000.0,
                max_spread_bps=1_000_000_000.0,
                min_order_book_depth_usd=0.0,
            ),
        )
    except (TypeError, ValueError, AttributeError, OverflowError):
        return _assessment_from_blockers(
            ["unknown_input"],
            effect=ActionRiskEffect.UNKNOWN,
            position_before=before_value,
            position_after=after_value,
            constitution=constitution,
            input_unknown=True,
        )
    if not liquidation.approved:
        blockers.extend("liquidation_risk_blocked" for _ in (1,))
        blockers.extend(liquidation.blockers)
    protection = evaluate_protection_feasibility(
        before_value,
        after_value,
        protection_before,
        protection_after,
        mark_price=mark,
        protection_required=constitution.protection_required,
        atomic_protection_replacement=atomic_protection_replacement,
    )
    blockers.extend(protection.blockers)
    if combined_loss is None and all(value is not None for value in (realized_pnl, unrealized_pnl, funding_cashflow)):
        combined_loss = evaluate_combined_loss(
            realized_pnl,  # type: ignore[arg-type]
            unrealized_pnl,  # type: ignore[arg-type]
            funding_cashflow,  # type: ignore[arg-type]
            fees,
            slippage,
            impact,
            account_equity=equity,
            constitution=constitution,
        )
    if combined_loss is not None:
        blockers.extend(combined_loss.blockers)
    if effect is ActionRiskEffect.UNKNOWN:
        blockers.append("effect_unknown")
    input_unknown = bool(
        set(blockers).intersection(
            {
                "unknown_input",
                "nonfinite_input",
                "position_missing",
                "mark_price_missing",
                "mark_price_invalid",
                "index_price_missing",
                "index_price_invalid",
                "account_equity_missing",
            }
        )
    )
    if input_unknown:
        blockers.append(_policy_blocker(constitution))
    ordered = _ordered_unique(blockers)
    safe_quantity = _safe_quantity(constitution=constitution, mark=mark, equity=equity)
    forced_loss = bool(
        before_value != 0.0
        and combined_loss is not None
        and set(combined_loss.blockers).intersection(
            {"combined_loss_limit_breach", "daily_loss_limit_breach", "drawdown_limit_breach"}
        )
    )
    forced_liquidation = False
    if before_value != 0.0:
        try:
            current_liquidation = evaluate_btc_perp_liquidation_risk(
                reference_prices=reference_prices,
                position=BTCPerpPositionState(
                    current_quantity=before_value,
                    proposed_quantity=before_value,
                    account_equity=equity,
                    side="long" if before_value > 0.0 else "short",
                ),
                policy=BTCLiquidationPolicy(
                    max_leverage=constitution.max_leverage,
                    maintenance_margin_rate=constitution.maintenance_margin_rate,
                    min_liquidation_buffer_bps=constitution.min_liquidation_buffer_bps,
                    max_reference_price_age_ms=0,
                    max_cross_venue_deviation_bps=1_000_000_000.0,
                    max_spread_bps=1_000_000_000.0,
                    min_order_book_depth_usd=0.0,
                ),
            )
            forced_liquidation = not current_liquidation.approved
        except (TypeError, ValueError, AttributeError, OverflowError):
            forced_liquidation = True
    requires_reduction = bool(
        before_value != 0.0
        and (
            abs(after_value) > safe_quantity
            or forced_loss
            or forced_liquidation
        )
    )
    return RiskAssessment(
        approved=not ordered,
        status=(
            "approved"
            if not ordered
            else "rejected"
            if input_unknown and constitution.unknown_input_policy is UnknownInputPolicy.REJECT
            else "unknown"
            if input_unknown
            else "blocked"
        ),
        effect=effect,
        blockers=ordered,
        reasons=ordered,
        requires_reduction=requires_reduction,
        max_safe_quantity=safe_quantity,
        notional=notional,
        leverage=leverage,
        liquidation_buffer_bps=liquidation.liquidation_buffer_bps,
        metadata=MappingProxyType(
            {
                "constitution": constitution.to_dict(),
                "position_before": before_value,
                "position_after": after_value,
                "combined_loss": combined_loss.to_dict() if combined_loss else None,
                "protection": protection.to_dict(),
                "execution_permission": False,
            }
        ),
    )


def _assessment_from_blockers(
    blockers: list[str],
    *,
    effect: ActionRiskEffect,
    position_before: float | None,
    position_after: float | None,
    constitution: RiskConstitution | None = None,
    input_unknown: bool = False,
) -> RiskAssessment:
    if input_unknown and constitution is not None:
        blockers.append(_policy_blocker(constitution))
    ordered = _ordered_unique(blockers)
    status = "blocked"
    if input_unknown and constitution is not None:
        status = "rejected" if constitution.unknown_input_policy is UnknownInputPolicy.REJECT else "unknown"
    return RiskAssessment(
        approved=False,
        status=status if input_unknown else ("unknown" if effect is ActionRiskEffect.UNKNOWN else "blocked"),
        effect=effect,
        blockers=ordered,
        reasons=ordered,
        requires_reduction=False,
        metadata=MappingProxyType(
            {
                "position_before": position_before,
                "position_after": position_after,
                "execution_permission": False,
            }
        ),
    )


evaluate_btc_risk = assess_btc_risk
evaluate_btc_perp_risk = assess_btc_risk


__all__ = [
    "BTC_SHARED_PLATFORM_V3_T2_VERSION",
    "ActionRiskEffect",
    "UnknownInputPolicy",
    "RiskConstitution",
    "BTCSharedRiskConstitution",
    "CombinedLossAssessment",
    "BTCCombinedLoss",
    "ProtectionFeasibility",
    "ProtectionFeasibilityResult",
    "RiskAssessment",
    "BTCRiskAssessment",
    "classify_action_risk_effect",
    "classify_action_effect",
    "evaluate_combined_loss",
    "evaluate_btc_combined_loss",
    "evaluate_protection_feasibility",
    "evaluate_protection",
    "assess_btc_risk",
    "evaluate_btc_risk",
    "evaluate_btc_perp_risk",
]
