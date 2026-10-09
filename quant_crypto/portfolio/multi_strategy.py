"""Fail-closed two-member BTC offline coordination policy.

This module coordinates already-produced strategy targets.  It does not
change either strategy and it deliberately has no optimizer or implicit
budget split.  Quantities are normalized only after their unit and the exact
instrument conversion facts have been proved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


MULTI_STRATEGY_POLICY_VERSION = "btc_multi_strategy_policy_v1"
QUANTITY_CONTRACTS = "contracts"
QUANTITY_BTC = "btc"


class MultiStrategyCoordinationError(ValueError):
    """The requested cohort cannot safely share one account order."""


def _decimal(value: Any, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise MultiStrategyCoordinationError(f"multi_strategy_{field}_invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MultiStrategyCoordinationError(
            f"multi_strategy_{field}_invalid"
        ) from exc
    if not result.is_finite():
        raise MultiStrategyCoordinationError(f"multi_strategy_{field}_invalid")
    return result


def _text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MemberDecision:
    member_id: str
    strategy_id: str
    strategy_version: str
    source_object_sha256: str
    target_position_id: str
    direction: str
    target_quantity: Decimal
    quantity_unit: str
    contract_value_btc: Decimal
    lot_size_contracts: Decimal
    protection_policy_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "member_id",
            "strategy_id",
            "strategy_version",
            "source_object_sha256",
            "target_position_id",
            "protection_policy_sha256",
        ):
            if not str(getattr(self, field) or ""):
                raise MultiStrategyCoordinationError(
                    f"multi_strategy_member_{field}_required"
                )
        direction = str(self.direction).lower()
        if direction not in {"long", "short", "flat"}:
            raise MultiStrategyCoordinationError(
                "multi_strategy_member_direction_invalid"
            )
        unit = str(self.quantity_unit).lower()
        if unit not in {QUANTITY_CONTRACTS, QUANTITY_BTC}:
            raise MultiStrategyCoordinationError(
                "multi_strategy_quantity_unit_invalid"
            )
        quantity = _decimal(self.target_quantity, "target_quantity")
        ct_val = _decimal(self.contract_value_btc, "contract_value_btc")
        lot = _decimal(self.lot_size_contracts, "lot_size_contracts")
        if quantity < 0 or ct_val <= 0 or lot <= 0:
            raise MultiStrategyCoordinationError(
                "multi_strategy_quantity_conversion_invalid"
            )
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "quantity_unit", unit)
        object.__setattr__(self, "target_quantity", quantity)
        object.__setattr__(self, "contract_value_btc", ct_val)
        object.__setattr__(self, "lot_size_contracts", lot)

    @property
    def signed_contracts(self) -> Decimal:
        contracts = (
            self.target_quantity
            if self.quantity_unit == QUANTITY_CONTRACTS
            else self.target_quantity / self.contract_value_btc
        )
        if contracts and contracts % self.lot_size_contracts:
            raise MultiStrategyCoordinationError(
                "multi_strategy_quantity_not_on_frozen_lot"
            )
        if self.direction == "flat":
            if contracts:
                raise MultiStrategyCoordinationError(
                    "multi_strategy_flat_member_quantity_nonzero"
                )
            return Decimal("0")
        if contracts <= 0:
            raise MultiStrategyCoordinationError(
                "multi_strategy_directional_member_quantity_invalid"
            )
        return contracts if self.direction == "long" else -contracts

    def evidence(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "source_object_sha256": self.source_object_sha256,
            "target_position_id": self.target_position_id,
            "direction": self.direction,
            "target_quantity": _text(self.target_quantity),
            "quantity_unit": self.quantity_unit,
            "contract_value_btc": _text(self.contract_value_btc),
            "lot_size_contracts": _text(self.lot_size_contracts),
            "normalized_signed_contracts": _text(self.signed_contracts),
            "protection_policy_sha256": self.protection_policy_sha256,
        }


@dataclass(frozen=True)
class ExplicitBudgetPolicy:
    member_max_notional_usdt: Mapping[str, Decimal]
    member_max_loss_usdt: Mapping[str, Decimal]
    account_max_notional_usdt: Decimal = Decimal("50")
    account_max_loss_usdt: Decimal = Decimal("10")

    def normalized(self, member_ids: tuple[str, ...]) -> dict[str, Any]:
        if set(self.member_max_notional_usdt) != set(member_ids) or set(
            self.member_max_loss_usdt
        ) != set(member_ids):
            raise MultiStrategyCoordinationError(
                "multi_strategy_explicit_member_budgets_required"
            )
        account_notional = _decimal(
            self.account_max_notional_usdt, "account_max_notional_usdt"
        )
        account_loss = _decimal(
            self.account_max_loss_usdt, "account_max_loss_usdt"
        )
        if account_notional <= 0 or account_notional > Decimal("50"):
            raise MultiStrategyCoordinationError(
                "multi_strategy_account_notional_budget_invalid"
            )
        if account_loss <= 0 or account_loss > Decimal("10"):
            raise MultiStrategyCoordinationError(
                "multi_strategy_account_loss_budget_invalid"
            )
        notionals = {
            member: _decimal(
                self.member_max_notional_usdt[member],
                f"member_{member}_max_notional_usdt",
            )
            for member in member_ids
        }
        losses = {
            member: _decimal(
                self.member_max_loss_usdt[member],
                f"member_{member}_max_loss_usdt",
            )
            for member in member_ids
        }
        if any(value <= 0 for value in (*notionals.values(), *losses.values())):
            raise MultiStrategyCoordinationError(
                "multi_strategy_member_budget_invalid"
            )
        if sum(notionals.values()) > account_notional:
            raise MultiStrategyCoordinationError(
                "multi_strategy_member_notional_budgets_exceed_account"
            )
        if sum(losses.values()) > account_loss:
            raise MultiStrategyCoordinationError(
                "multi_strategy_member_loss_budgets_exceed_account"
            )
        return {
            "schema_version": "btc_multi_strategy_explicit_budget_v1",
            "member_max_notional_usdt": {
                key: _text(notionals[key]) for key in member_ids
            },
            "member_max_loss_usdt": {
                key: _text(losses[key]) for key in member_ids
            },
            "account_max_notional_usdt": _text(account_notional),
            "account_max_loss_usdt": _text(account_loss),
        }


@dataclass(frozen=True)
class CohortAllocationPlan:
    members: tuple[MemberDecision, ...]
    current_member_contracts: Mapping[str, Decimal]
    desired_member_contracts: Mapping[str, Decimal]
    member_delta_contracts: Mapping[str, Decimal]
    position_before_contracts: Decimal
    position_after_contracts: Decimal
    order_delta_contracts: Decimal
    mark_price_usdt: Decimal
    budget_policy: Mapping[str, Any]
    member_list_sha256: str
    budget_policy_sha256: str
    allocation_plan_sha256: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": MULTI_STRATEGY_POLICY_VERSION,
            "execution_scope": "btc_two_member_offline_shared_account",
            "members": [member.evidence() for member in self.members],
            "current_member_contracts": {
                key: _text(value)
                for key, value in self.current_member_contracts.items()
            },
            "desired_member_contracts": {
                key: _text(value)
                for key, value in self.desired_member_contracts.items()
            },
            "member_delta_contracts": {
                key: _text(value)
                for key, value in self.member_delta_contracts.items()
            },
            "position_before_contracts": _text(self.position_before_contracts),
            "position_after_contracts": _text(self.position_after_contracts),
            "order_delta_contracts": _text(self.order_delta_contracts),
            "mark_price_usdt": _text(self.mark_price_usdt),
            "budget_policy": dict(self.budget_policy),
            "member_list_sha256": self.member_list_sha256,
            "budget_policy_sha256": self.budget_policy_sha256,
            "allocation_plan_sha256": self.allocation_plan_sha256,
        }


def build_two_member_cohort_plan(
    *,
    members: tuple[MemberDecision, MemberDecision],
    budgets: ExplicitBudgetPolicy,
    mark_price_usdt: Decimal,
    current_member_contracts: Mapping[str, Decimal] | None = None,
) -> CohortAllocationPlan:
    """Build a two-member account target or reject without scaling either member."""

    if len(members) != 2 or len({member.member_id for member in members}) != 2:
        raise MultiStrategyCoordinationError(
            "multi_strategy_exactly_two_distinct_members_required"
        )
    ordered = tuple(sorted(members, key=lambda member: member.member_id))
    member_ids = tuple(member.member_id for member in ordered)
    if len({member.contract_value_btc for member in ordered}) != 1 or len(
        {member.lot_size_contracts for member in ordered}
    ) != 1:
        raise MultiStrategyCoordinationError(
            "multi_strategy_frozen_conversion_facts_mismatch"
        )
    mark = _decimal(mark_price_usdt, "mark_price_usdt")
    if mark <= 0:
        raise MultiStrategyCoordinationError("multi_strategy_mark_price_invalid")
    budget = budgets.normalized(member_ids)
    current_source = current_member_contracts or {}
    if set(current_source) - set(member_ids):
        raise MultiStrategyCoordinationError(
            "multi_strategy_unknown_current_allocation_member"
        )
    current = {
        member: _decimal(current_source.get(member, 0), f"current_{member}")
        for member in member_ids
    }
    desired = {member.member_id: member.signed_contracts for member in ordered}
    before = sum(current.values())
    after = sum(desired.values())
    if before == 0:
        directions = {1 if value > 0 else -1 for value in desired.values() if value}
        # Explicitly reject opposite members even when the account net would be zero.
        if len(directions) != 1 or not directions:
            raise MultiStrategyCoordinationError(
                "multi_strategy_flat_entry_requires_same_direction_cohort"
            )
        if any(value == 0 for value in desired.values()):
            raise MultiStrategyCoordinationError(
                "multi_strategy_flat_entry_requires_both_members"
            )
        protection = {
            member.protection_policy_sha256 for member in ordered if member.signed_contracts
        }
        if len(protection) != 1:
            raise MultiStrategyCoordinationError(
                "multi_strategy_cohort_protection_policy_incompatible"
            )
    else:
        if any(value and (value > 0) != (before > 0) for value in current.values()):
            raise MultiStrategyCoordinationError(
                "multi_strategy_current_allocation_direction_conflict"
            )
        for member in member_ids:
            old, new = current[member], desired[member]
            if old == 0 and new != 0:
                raise MultiStrategyCoordinationError(
                    "multi_strategy_nonflat_new_member_risk_forbidden"
                )
            if old and new and (old > 0) != (new > 0):
                raise MultiStrategyCoordinationError(
                    "multi_strategy_nonflat_member_reversal_forbidden"
                )
            if abs(new) > abs(old):
                raise MultiStrategyCoordinationError(
                    "multi_strategy_nonflat_member_increase_forbidden"
                )
        if after and (after > 0) != (before > 0):
            raise MultiStrategyCoordinationError(
                "multi_strategy_account_reversal_forbidden"
            )
        remaining_policies = {
            member.protection_policy_sha256
            for member in ordered
            if desired[member.member_id]
        }
        if len(remaining_policies) > 1:
            raise MultiStrategyCoordinationError(
                "multi_strategy_residual_protection_policy_incompatible"
            )

    ct_val = ordered[0].contract_value_btc
    member_budget = budget["member_max_notional_usdt"]
    for member in member_ids:
        desired_notional = abs(desired[member]) * ct_val * mark
        if desired_notional > Decimal(member_budget[member]):
            raise MultiStrategyCoordinationError(
                f"multi_strategy_member_budget_insufficient:{member}"
            )
    gross_notional = sum(abs(value) for value in desired.values()) * ct_val * mark
    if gross_notional > Decimal(budget["account_max_notional_usdt"]):
        raise MultiStrategyCoordinationError(
            "multi_strategy_account_notional_budget_exceeded"
        )
    delta = {member: desired[member] - current[member] for member in member_ids}
    order_delta = after - before
    member_evidence = [member.evidence() for member in ordered]
    member_digest = _digest(
        [
            {
                "member_id": member.member_id,
                "strategy_id": member.strategy_id,
                "strategy_version": member.strategy_version,
                "quantity_unit": member.quantity_unit,
                "contract_value_btc": _text(member.contract_value_btc),
                "lot_size_contracts": _text(member.lot_size_contracts),
                "protection_policy_sha256": member.protection_policy_sha256,
            }
            for member in ordered
        ]
    )
    budget_digest = _digest(budget)
    plan_body = {
        "members": member_evidence,
        "current": {key: _text(value) for key, value in current.items()},
        "desired": {key: _text(value) for key, value in desired.items()},
        "delta": {key: _text(value) for key, value in delta.items()},
        "before": _text(before),
        "after": _text(after),
        "order_delta": _text(order_delta),
        "mark_price_usdt": _text(mark),
        "member_list_sha256": member_digest,
        "budget_policy_sha256": budget_digest,
    }
    return CohortAllocationPlan(
        members=ordered,
        current_member_contracts=current,
        desired_member_contracts=desired,
        member_delta_contracts=delta,
        position_before_contracts=before,
        position_after_contracts=after,
        order_delta_contracts=order_delta,
        mark_price_usdt=mark,
        budget_policy=budget,
        member_list_sha256=member_digest,
        budget_policy_sha256=budget_digest,
        allocation_plan_sha256=_digest(plan_body),
    )


__all__ = [
    "CohortAllocationPlan",
    "ExplicitBudgetPolicy",
    "MemberDecision",
    "MultiStrategyCoordinationError",
    "MULTI_STRATEGY_POLICY_VERSION",
    "QUANTITY_BTC",
    "QUANTITY_CONTRACTS",
    "build_two_member_cohort_plan",
]
