"""Assembly-issued BTC two-member offline execution context.

Only objects created here are accepted by the runtime seam.  The context is
bound to the exact member targets, normalized cohort plan, run, order id and
venue conversion facts.  Rule members remain Signal/Target producers and no
Forecast is fabricated for them.
"""

from __future__ import annotations

import hashlib
import json
import weakref
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from quant_crypto.oms.strategy_allocations import (
    allocate_raw_fill,
    empty_strategy_allocation_state,
)
from quant_crypto.portfolio.multi_strategy import (
    CohortAllocationPlan,
    ExplicitBudgetPolicy,
    build_two_member_cohort_plan,
)
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    Signal,
    SignalDirection,
    TargetPosition,
    TimeInForce,
)


OFFLINE_MULTI_STRATEGY_CONTEXT_VERSION = "btc_multi_strategy_offline_context_v1"
OFFLINE_MULTI_STRATEGY_EXECUTION_SCOPE = "btc_two_member_offline_shared_account"
_ISSUED: "weakref.WeakSet[OfflineMultiStrategyContext]" = weakref.WeakSet()
_CURRENT_ALLOCATION_STATE_NOT_SUPPLIED = object()


class OfflineMultiStrategyContextError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()


def _object_digest(value: Any) -> str:
    source = getattr(value, "__dict__", value)
    return _digest(source)


def _member_object_bindings(
    *,
    plan: CohortAllocationPlan,
    member_strategy_objects: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    expected_members = tuple(member.member_id for member in plan.members)
    if set(member_strategy_objects) != set(expected_members):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_member_objects_incomplete"
        )
    bindings: dict[str, Any] = {}
    for member in plan.members:
        objects = member_strategy_objects[member.member_id]
        target = objects.get("target")
        signal = objects.get("signal")
        forecast = objects.get("forecast")
        if not isinstance(target, TargetPosition) or not isinstance(signal, Signal):
            raise OfflineMultiStrategyContextError(
                "multi_strategy_offline_member_signal_target_required"
            )
        target_metadata = getattr(target, "metadata", None)
        try:
            target_quantity = Decimal(str(target.target_quantity))
        except Exception as exc:
            raise OfflineMultiStrategyContextError(
                "multi_strategy_offline_member_object_binding_mismatch"
            ) from exc
        signal_direction = str(
            getattr(signal.direction, "value", signal.direction)
        ).lower()
        target_quantity_unit = (
            str(target_metadata.get("quantity_unit") or "").lower()
            if isinstance(target_metadata, Mapping)
            else ""
        )
        if (
            target.strategy_id != member.strategy_id
            or signal.strategy_id != member.strategy_id
            or target.symbol != "BTC-USDT-SWAP"
            or signal.symbol != "BTC-USDT-SWAP"
            or target.symbol != signal.symbol
            or target.target_position_id != member.target_position_id
            or target.signal_id != signal.signal_id
            or _object_digest(target) != member.source_object_sha256
            or target_quantity != member.target_quantity
            or target_quantity_unit != member.quantity_unit
            or signal_direction != member.direction
        ):
            raise OfflineMultiStrategyContextError(
                "multi_strategy_offline_member_object_binding_mismatch"
            )
        bindings[member.member_id] = {
            "strategy_id": member.strategy_id,
            "strategy_version": member.strategy_version,
            "signal_sha256": _object_digest(signal),
            "target_sha256": _object_digest(target),
            "forecast_sha256": (
                _object_digest(forecast) if forecast is not None else ""
            ),
            "forecast_present": forecast is not None,
            "target_quantity": str(member.target_quantity),
            "quantity_unit": member.quantity_unit,
            "direction": member.direction,
            "normalized_signed_contracts": str(member.signed_contracts),
        }
    return bindings


def _verify_plan_mathematics(plan: CohortAllocationPlan) -> None:
    try:
        member_ids = tuple(member.member_id for member in plan.members)
        budget = plan.budget_policy
        canonical = build_two_member_cohort_plan(
            members=plan.members,
            budgets=ExplicitBudgetPolicy(
                member_max_notional_usdt={
                    member_id: Decimal(
                        str(budget["member_max_notional_usdt"][member_id])
                    )
                    for member_id in member_ids
                },
                member_max_loss_usdt={
                    member_id: Decimal(
                        str(budget["member_max_loss_usdt"][member_id])
                    )
                    for member_id in member_ids
                },
                account_max_notional_usdt=Decimal(
                    str(budget["account_max_notional_usdt"])
                ),
                account_max_loss_usdt=Decimal(
                    str(budget["account_max_loss_usdt"])
                ),
            ),
            mark_price_usdt=Decimal(str(plan.mark_price_usdt)),
            current_member_contracts=plan.current_member_contracts,
        )
    except Exception as exc:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_plan_mathematics_mismatch"
        ) from exc
    if canonical.to_mapping() != plan.to_mapping():
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_plan_mathematics_mismatch"
        )


def _verify_frozen_mark(
    *, plan: CohortAllocationPlan, snapshot: Mapping[str, Any]
) -> None:
    mark = snapshot.get("mark")
    try:
        observed = (
            Decimal(str(mark.get("mark_price")))
            if isinstance(mark, Mapping)
            else None
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_frozen_mark_mismatch"
        ) from exc
    if observed != Decimal(str(plan.mark_price_usdt)):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_frozen_mark_mismatch"
        )


class OfflineMultiStrategyContext:
    def __init__(
        self,
        *,
        plan: CohortAllocationPlan,
        member_strategy_objects: Mapping[str, Mapping[str, Any]],
        signal: Signal,
        execution_target: TargetPosition,
        intent: OrderIntent,
        binding: Mapping[str, Any],
        prior_allocation_state: Mapping[str, Any],
    ) -> None:
        self.plan = plan
        self.member_strategy_objects = {
            key: dict(value) for key, value in member_strategy_objects.items()
        }
        self.signal = signal
        self.execution_target = execution_target
        self.intent = intent
        self.binding = json.loads(json.dumps(binding))
        self._issued_binding_sha256 = _digest(self.binding)
        self.prior_allocation_state = json.loads(
            json.dumps(prior_allocation_state)
        )

    def allocation_after_fills(
        self, fills: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        state = json.loads(json.dumps(self.prior_allocation_state))
        plan = self.plan.to_mapping()
        for raw_fill in fills:
            state = allocate_raw_fill(
                state=state, allocation_plan=plan, raw_fill=raw_fill
            )
        return state

    def revise_residual_protection(
        self,
        *,
        controller: Any,
        client: Any,
        order_id: str,
        fills: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not (
            self.plan.position_before_contracts
            and self.plan.position_after_contracts
            and abs(self.plan.position_after_contracts)
            < abs(self.plan.position_before_contracts)
            and len(fills) == 1
            and callable(getattr(client, "revise_residual_protection", None))
        ):
            raise OfflineMultiStrategyContextError(
                "multi_strategy_offline_residual_revision_required"
            )
        allocation = self.allocation_after_fills(fills)
        exited = [
            member
            for member, value in allocation["member_contracts"].items()
            if Decimal(str(value)) == 0
            and Decimal(str(self.prior_allocation_state["member_contracts"][member]))
            != 0
        ]
        residual = [
            member
            for member, value in allocation["member_contracts"].items()
            if Decimal(str(value)) != 0
        ]
        if len(exited) != 1 or not residual:
            raise OfflineMultiStrategyContextError(
                "multi_strategy_offline_residual_ownership_ambiguous"
            )
        fill = dict(fills[0])
        fill_id = str(fill.get("fill_id") or fill.get("tradeId") or "")
        venue_receipt = client.revise_residual_protection(
            exit_client_order_id=self.intent.client_order_id,
            exit_order_id=order_id,
            exit_fill_id=fill_id,
            residual_contracts=abs(self.plan.position_after_contracts),
            position_side=(
                "long" if self.plan.position_after_contracts > 0 else "short"
            ),
        )
        snapshot = controller._collect_exchange_snapshot(client)
        fact_binding = controller._hosted_protection_fact_binding(snapshot)
        from quant_crypto.application.hosted_protection_facts import (
            build_offline_residual_protection_revision,
        )

        proof = build_offline_residual_protection_revision(
            fact_binding=fact_binding,
            member_list_sha256=self.plan.member_list_sha256,
            allocation_plan_sha256=self.plan.allocation_plan_sha256,
            exited_member_id=exited[0],
            residual_member_ids=residual,
            allocation_state=allocation,
            exit_fill=fill,
            venue_receipt=venue_receipt,
        )
        risk = controller._state["risk_control"]
        prior_active = dict(risk.get("active_protection") or {})
        prior_client_id = str(prior_active.get("algo_client_order_id") or "")
        if prior_client_id in risk["owned_attached_algos"]:
            risk["owned_attached_algos"][prior_client_id]["status"] = (
                "replaced_for_residual_allocation"
            )
        replacement = proof["replacement_protection"]
        replacement_client_id = str(replacement["algo_client_order_id"])
        risk["owned_attached_algos"][replacement_client_id] = {
            "algo_id": str(replacement["algo_id"]),
            "algo_client_order_id": replacement_client_id,
            "parent_client_order_id": self.intent.client_order_id,
            "instrument_id": str(replacement["instrument_id"]),
            "opening_intent": False,
            "status": "active",
            "fact_binding": fact_binding,
            "offline_residual_revision_sha256": proof["revision_sha256"],
        }
        risk["active_protection"] = {
            **dict(replacement),
            "fact_binding": fact_binding,
            "offline_residual_revision_sha256": proof["revision_sha256"],
        }
        risk["offline_residual_protection_revision"] = proof
        return allocation, proof


def issue_offline_multi_strategy_context(
    *,
    plan: CohortAllocationPlan,
    member_strategy_objects: Mapping[str, Mapping[str, Any]],
    timestamp_utc: datetime,
    run_id: str,
    client_order_id: str,
    limit_price: Decimal,
    prior_allocation_state: Mapping[str, Any] | None = None,
) -> OfflineMultiStrategyContext:
    if not run_id or not client_order_id:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_runtime_binding_required"
        )
    _verify_plan_mathematics(plan)
    plan_map = plan.to_mapping()
    expected_members = tuple(member.member_id for member in plan.members)
    member_bindings = _member_object_bindings(
        plan=plan,
        member_strategy_objects=member_strategy_objects,
    )
    if plan.position_before_contracts == 0 and plan.position_after_contracts < 0:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_short_cohort_unsupported_v1"
        )
    delta = plan.order_delta_contracts
    if not delta:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_order_delta_required"
        )
    after = plan.position_after_contracts
    signal_direction = (
        SignalDirection.LONG
        if after > 0
        else SignalDirection.SHORT
        if after < 0
        else SignalDirection.FLAT
    )
    coordinator_signal = Signal(
        timestamp_utc=timestamp_utc,
        strategy_id="btc_multi_strategy_offline_coordinator_v1",
        symbol="BTC-USDT-SWAP",
        direction=signal_direction,
        strength=1.0,
        horizon="offline_cohort_execution",
        reason="two_member_targets_coordinated_without_mutating_member_objects",
        metadata={
            "execution_scope": OFFLINE_MULTI_STRATEGY_EXECUTION_SCOPE,
            "member_list_sha256": plan.member_list_sha256,
            "budget_policy_sha256": plan.budget_policy_sha256,
            "allocation_plan_sha256": plan.allocation_plan_sha256,
        },
    )
    target = TargetPosition(
        timestamp_utc=timestamp_utc,
        strategy_id=coordinator_signal.strategy_id,
        symbol=coordinator_signal.symbol,
        target_weight=0.0,
        target_quantity=float(after),
        signal_id=coordinator_signal.signal_id,
        metadata={
            "source_kind": "signal",
            "source_signal_id": coordinator_signal.signal_id,
            "quantity_unit": "contracts",
            "execution_scope": OFFLINE_MULTI_STRATEGY_EXECUTION_SCOPE,
            "order_generation_allowed": plan.position_before_contracts == 0,
            "member_list_sha256": plan.member_list_sha256,
            "allocation_plan_sha256": plan.allocation_plan_sha256,
        },
    )
    intent = OrderIntent(
        timestamp_utc=timestamp_utc,
        strategy_id=coordinator_signal.strategy_id,
        symbol=coordinator_signal.symbol,
        side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
        quantity=float(abs(delta)),
        order_type=OrderType.LIMIT,
        limit_price=float(Decimal(str(limit_price))),
        time_in_force=(
            TimeInForce.FOK
            if plan.position_before_contracts == 0
            else TimeInForce.IOC
        ),
        run_id=run_id,
        signal_id=coordinator_signal.signal_id,
        target_position_id=target.target_position_id,
        client_order_id=client_order_id,
        metadata={
            "execution_scope": OFFLINE_MULTI_STRATEGY_EXECUTION_SCOPE,
            "allocation_plan_sha256": plan.allocation_plan_sha256,
        },
    )
    state = (
        json.loads(json.dumps(prior_allocation_state))
        if prior_allocation_state is not None
        else empty_strategy_allocation_state(
            member_ids=expected_members,
            member_list_sha256=plan.member_list_sha256,
        )
    )
    expected_current = {
        key: str(value) for key, value in plan.current_member_contracts.items()
    }
    observed_current = {
        key: str(Decimal(str(value)))
        for key, value in state.get("member_contracts", {}).items()
    }
    if expected_current != observed_current:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_prior_allocation_mismatch"
        )
    binding = {
        "schema_version": OFFLINE_MULTI_STRATEGY_CONTEXT_VERSION,
        "execution_scope": OFFLINE_MULTI_STRATEGY_EXECUTION_SCOPE,
        "run_id": run_id,
        "client_order_id": client_order_id,
        "member_list_sha256": plan.member_list_sha256,
        "budget_policy_sha256": plan.budget_policy_sha256,
        "allocation_plan_sha256": plan.allocation_plan_sha256,
        "plan_sha256": _digest(plan_map),
        "prior_allocation_state_sha256": _digest(state),
        "member_objects": member_bindings,
        "coordinator_signal_sha256": _object_digest(coordinator_signal),
        "execution_target_sha256": _object_digest(target),
        "intent_sha256": _object_digest(intent),
    }
    context = OfflineMultiStrategyContext(
        plan=plan,
        member_strategy_objects=member_strategy_objects,
        signal=coordinator_signal,
        execution_target=target,
        intent=intent,
        binding=binding,
        prior_allocation_state=state,
    )
    _ISSUED.add(context)
    return context


def validate_offline_multi_strategy_context(
    context: Any,
    *,
    run_id: str,
    order_plan: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    maximum_absolute_contracts: Decimal,
    current_allocation_state: Mapping[str, Any] | None | object = (
        _CURRENT_ALLOCATION_STATE_NOT_SUPPLIED
    ),
) -> OfflineMultiStrategyContext:
    if not isinstance(context, OfflineMultiStrategyContext) or context not in _ISSUED:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_context_not_assembly_issued"
        )
    plan = context.plan
    _verify_plan_mathematics(plan)
    binding = context.binding
    if binding.get("prior_allocation_state_sha256") != _digest(
        context.prior_allocation_state
    ):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_prior_allocation_binding_mismatch"
        )
    if current_allocation_state is not _CURRENT_ALLOCATION_STATE_NOT_SUPPLIED:
        if current_allocation_state is None or (
            isinstance(current_allocation_state, Mapping)
            and not current_allocation_state
        ):
            persisted_allocation = empty_strategy_allocation_state(
                member_ids=(member.member_id for member in plan.members),
                member_list_sha256=plan.member_list_sha256,
            )
        elif isinstance(current_allocation_state, Mapping):
            persisted_allocation = json.loads(
                json.dumps(current_allocation_state)
            )
        else:
            raise OfflineMultiStrategyContextError(
                "multi_strategy_offline_prior_allocation_runtime_mismatch"
            )
        if _digest(persisted_allocation) != _digest(
            context.prior_allocation_state
        ):
            raise OfflineMultiStrategyContextError(
                "multi_strategy_offline_prior_allocation_runtime_mismatch"
            )
    observed_member_bindings = _member_object_bindings(
        plan=plan,
        member_strategy_objects=context.member_strategy_objects,
    )
    instrument = snapshot.get("instrument")
    if not isinstance(instrument, Mapping):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_instrument_facts_missing"
        )
    ct_val = Decimal(str(instrument.get("contract_value_btc")))
    lot = Decimal(str(instrument.get("lot_size")))
    _verify_frozen_mark(plan=plan, snapshot=snapshot)
    if any(member.contract_value_btc != ct_val for member in plan.members) or any(
        member.lot_size_contracts != lot for member in plan.members
    ):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_frozen_conversion_mismatch"
        )
    expected_side = "buy" if plan.order_delta_contracts > 0 else "sell"
    expected_tif = TimeInForce.FOK if plan.position_before_contracts == 0 else TimeInForce.IOC
    if not (
        binding.get("schema_version") == OFFLINE_MULTI_STRATEGY_CONTEXT_VERSION
        and _digest(binding) == context._issued_binding_sha256
        and binding.get("execution_scope") == OFFLINE_MULTI_STRATEGY_EXECUTION_SCOPE
        and binding.get("run_id") == run_id
        and binding.get("client_order_id") == str(order_plan.get("client_order_id") or "")
        and binding.get("member_list_sha256") == plan.member_list_sha256
        and binding.get("budget_policy_sha256") == plan.budget_policy_sha256
        and binding.get("allocation_plan_sha256") == plan.allocation_plan_sha256
        and binding.get("plan_sha256") == _digest(plan.to_mapping())
        and binding.get("member_objects") == observed_member_bindings
        and binding.get("coordinator_signal_sha256") == _object_digest(context.signal)
        and binding.get("execution_target_sha256") == _object_digest(context.execution_target)
        and binding.get("intent_sha256") == _object_digest(context.intent)
        and Decimal(str(order_plan.get("position_before_contracts"))) == plan.position_before_contracts
        and Decimal(str(order_plan.get("position_after_contracts"))) == plan.position_after_contracts
        and Decimal(str(order_plan.get("contracts"))) == abs(plan.order_delta_contracts)
        and str(order_plan.get("side") or "") == expected_side
        and Decimal(str(order_plan.get("limit_price"))) == Decimal(str(context.intent.limit_price))
        and context.intent.run_id == run_id
        and context.intent.time_in_force == expected_tif
        and context.intent.target_position_id == context.execution_target.target_position_id
        and context.execution_target.signal_id == context.signal.signal_id == context.intent.signal_id
        and abs(plan.position_after_contracts) <= Decimal(str(maximum_absolute_contracts))
    ):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_context_binding_mismatch"
        )
    return context


def prepare_offline_multi_strategy_order(
    *, controller: Any, snapshot: Mapping[str, Any], plan: CohortAllocationPlan
) -> dict[str, Any]:
    """Configure the explicit offline-only limits and call the original planner."""

    _verify_plan_mathematics(plan)
    _verify_frozen_mark(plan=plan, snapshot=snapshot)
    if plan.position_before_contracts == 0 and plan.position_after_contracts < 0:
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_short_cohort_unsupported_v1"
        )

    config = getattr(controller, "config", None)
    state = getattr(controller, "_state", None)
    if not (
        config is not None
        and getattr(config, "credential_service", "")
        == "quant-system.okx-demo.offline"
        and callable(getattr(config, "offline_completed_frame_provider", None))
        and isinstance(state, dict)
    ):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_controller_required"
        )
    provider = getattr(config, "authoritative_oms_bundle_provider", None)
    composition = getattr(provider, "__self__", None)
    if composition is None or not hasattr(composition, "max_abs_position"):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_authoritative_composition_required"
        )
    account_notional = Decimal(
        str(plan.budget_policy["account_max_notional_usdt"])
    )
    account_loss = Decimal(str(plan.budget_policy["account_max_loss_usdt"]))
    if account_notional > Decimal("50") or account_loss > Decimal("10"):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_account_budget_exceeded"
        )
    maximum_contracts = max(
        abs(plan.position_before_contracts), abs(plan.position_after_contracts)
    )
    # This is an instance-local offline seam.  Default production composition
    # construction and its 0.01-contract policy remain untouched.
    composition.max_abs_position = maximum_contracts
    composition.max_notional = account_notional
    composition.max_loss_usdt = account_loss
    state["limits"].update(
        {
            "order_contracts": str(abs(plan.order_delta_contracts)),
            "max_net_contracts": str(maximum_contracts),
            "max_notional_usdt": str(account_notional),
            "max_loss_usdt": str(account_loss),
        }
    )
    order_plan = controller._build_order_plan(
        snapshot,
        current_quantity=plan.position_before_contracts,
        target_quantity=plan.position_after_contracts,
    )
    if not isinstance(order_plan, Mapping):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_original_order_plan_missing"
        )
    if plan.position_before_contracts == 0 and str(
        order_plan.get("entry_order_type") or "fok"
    ) != "fok":
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_ordinary_entry_must_be_fok"
        )
    return dict(order_plan)


def execute_offline_multi_strategy_order(
    *,
    controller: Any,
    client: Any,
    snapshot: Mapping[str, Any],
    order_plan: Mapping[str, Any],
    context: OfflineMultiStrategyContext,
) -> dict[str, Any]:
    """Enter the existing Risk -> OMS -> dispatcher -> venue -> UOW path."""

    config = getattr(controller, "config", None)
    if not (
        config is not None
        and getattr(config, "credential_service", "")
        == "quant-system.okx-demo.offline"
        and callable(getattr(config, "offline_completed_frame_provider", None))
    ):
        raise OfflineMultiStrategyContextError(
            "multi_strategy_offline_controller_required"
        )
    return controller._submit_order_plan(
        client,
        snapshot=snapshot,
        decision={
            "strategy_id": "btc_multi_strategy_offline_coordinator_v1",
            "direction": (
                "long"
                if context.plan.position_after_contracts > 0
                else "short"
                if context.plan.position_after_contracts < 0
                else "flat"
            ),
            "raw_signal": "1",
        },
        order_plan=order_plan,
        offline_multi_strategy_context=context,
    )


__all__ = [
    "OFFLINE_MULTI_STRATEGY_CONTEXT_VERSION",
    "OFFLINE_MULTI_STRATEGY_EXECUTION_SCOPE",
    "OfflineMultiStrategyContext",
    "OfflineMultiStrategyContextError",
    "issue_offline_multi_strategy_context",
    "prepare_offline_multi_strategy_order",
    "execute_offline_multi_strategy_order",
    "validate_offline_multi_strategy_context",
]
