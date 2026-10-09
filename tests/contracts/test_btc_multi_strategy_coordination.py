from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant_crypto.application.btc_multi_strategy_offline import (
    OfflineMultiStrategyContextError,
    issue_offline_multi_strategy_context,
    validate_offline_multi_strategy_context,
)
from quant_crypto.portfolio.multi_strategy import (
    ExplicitBudgetPolicy,
    MemberDecision,
    MultiStrategyCoordinationError,
    build_two_member_cohort_plan,
)
from quant_crypto.trading_contracts import Signal, SignalDirection, TargetPosition


NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            getattr(value, "__dict__", value),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _object(
    strategy: str,
    quantity: str,
    *,
    unit: str,
    direction: str = "long",
) -> tuple[Signal, TargetPosition]:
    signal = Signal(
        timestamp_utc=NOW,
        strategy_id=strategy,
        symbol="BTC-USDT-SWAP",
        direction=(
            SignalDirection.FLAT
            if not Decimal(quantity)
            else SignalDirection.LONG
            if direction == "long"
            else SignalDirection.SHORT
        ),
        strength=1,
        horizon="fixture",
    )
    target = TargetPosition(
        timestamp_utc=NOW,
        strategy_id=strategy,
        symbol=signal.symbol,
        target_weight=0,
        target_quantity=float(Decimal(quantity)),
        signal_id=signal.signal_id,
        metadata={"quantity_unit": unit},
    )
    return signal, target


def _member(
    member_id: str,
    strategy: str,
    target: TargetPosition,
    *,
    unit: str,
    direction: str = "long",
    protection: str = "p" * 64,
) -> MemberDecision:
    return MemberDecision(
        member_id=member_id,
        strategy_id=strategy,
        strategy_version="fixture-v1",
        source_object_sha256=_digest(target),
        target_position_id=target.target_position_id,
        direction=direction,
        target_quantity=Decimal(str(target.target_quantity)),
        quantity_unit=unit,
        contract_value_btc=Decimal("0.01"),
        lot_size_contracts=Decimal("0.01"),
        protection_policy_sha256=protection,
    )


def _budgets(a: str = "20", b: str = "20") -> ExplicitBudgetPolicy:
    return ExplicitBudgetPolicy(
        member_max_notional_usdt={"don": Decimal(a), "qlib": Decimal(b)},
        member_max_loss_usdt={"don": Decimal("4"), "qlib": Decimal("4")},
        account_max_notional_usdt=Decimal("50"),
        account_max_loss_usdt=Decimal("10"),
    )


def test_contract_and_btc_quantities_share_frozen_conversion_without_scaling() -> None:
    don_signal, don_target = _object(
        "donchian-rule", "0.01", unit="contracts"
    )
    qlib_signal, qlib_target = _object(
        "qlib-learning", "0.0001", unit="btc"
    )
    don = _member("don", don_signal.strategy_id, don_target, unit="contracts")
    qlib = _member("qlib", qlib_signal.strategy_id, qlib_target, unit="btc")

    plan = build_two_member_cohort_plan(
        members=(don, qlib), budgets=_budgets(), mark_price_usdt=Decimal("60000")
    )

    assert don.signed_contracts == qlib.signed_contracts == Decimal("0.01")
    assert plan.position_after_contracts == Decimal("0.02")
    assert plan.member_delta_contracts == {
        "don": Decimal("0.01"),
        "qlib": Decimal("0.01"),
    }
    assert plan.budget_policy["account_max_notional_usdt"] == "50"

    context = issue_offline_multi_strategy_context(
        plan=plan,
        member_strategy_objects={
            "don": {"signal": don_signal, "target": don_target},
            "qlib": {"signal": qlib_signal, "target": qlib_target, "forecast": object()},
        },
        timestamp_utc=NOW,
        run_id="run-1",
        client_order_id="cohort-1",
        limit_price=Decimal("60000"),
    )
    validated = validate_offline_multi_strategy_context(
        context,
        run_id="run-1",
        order_plan={
            "client_order_id": "cohort-1",
            "position_before_contracts": "0",
            "position_after_contracts": "0.02",
            "contracts": "0.02",
            "side": "buy",
            "limit_price": "60000",
        },
        snapshot={
            "instrument": {"contract_value_btc": "0.01", "lot_size": "0.01"},
            "mark": {"mark_price": "60000"},
        },
        maximum_absolute_contracts=Decimal("0.02"),
    )
    assert validated is context
    assert context.binding["member_objects"]["don"]["forecast_present"] is False
    assert context.binding["member_objects"]["qlib"]["forecast_present"] is True


def test_opposite_members_are_rejected_instead_of_netted_to_fake_fill() -> None:
    _, long_target = _object("long-rule", "0.01", unit="contracts")
    _, short_target = _object(
        "short-learning", "0.0001", unit="btc", direction="short"
    )
    long = _member("don", "long-rule", long_target, unit="contracts")
    short = _member(
        "qlib", "short-learning", short_target, unit="btc", direction="short"
    )
    with pytest.raises(
        MultiStrategyCoordinationError,
        match="flat_entry_requires_same_direction_cohort",
    ):
        build_two_member_cohort_plan(
            members=(long, short),
            budgets=_budgets(),
            mark_price_usdt=Decimal("60000"),
        )


def test_nonflat_member_may_only_hold_or_reduce_own_fill_share() -> None:
    _, flat_target = _object("donchian-rule", "0", unit="contracts")
    _, hold_target = _object("qlib-learning", "0.0001", unit="btc")
    exiting = _member(
        "don", "donchian-rule", flat_target, unit="contracts", direction="flat"
    )
    holding = _member("qlib", "qlib-learning", hold_target, unit="btc")
    plan = build_two_member_cohort_plan(
        members=(exiting, holding),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
        current_member_contracts={"don": Decimal("0.01"), "qlib": Decimal("0.01")},
    )
    assert plan.member_delta_contracts == {
        "don": Decimal("-0.01"),
        "qlib": Decimal("0"),
    }
    assert plan.position_after_contracts == Decimal("0.01")

    _, increased_target = _object("qlib-learning", "0.0002", unit="btc")
    increased = _member("qlib", "qlib-learning", increased_target, unit="btc")
    with pytest.raises(
        MultiStrategyCoordinationError, match="nonflat_member_increase_forbidden"
    ):
        build_two_member_cohort_plan(
            members=(exiting, increased),
            budgets=_budgets(),
            mark_price_usdt=Decimal("60000"),
            current_member_contracts={
                "don": Decimal("0.01"),
                "qlib": Decimal("0.01"),
            },
        )


def test_budget_and_protection_conflicts_reject_without_target_scaling() -> None:
    _, a_target = _object("a", "0.01", unit="contracts")
    _, b_target = _object("b", "0.0001", unit="btc")
    a = _member("don", "a", a_target, unit="contracts")
    b = _member("qlib", "b", b_target, unit="btc")
    with pytest.raises(MultiStrategyCoordinationError, match="budget_insufficient"):
        build_two_member_cohort_plan(
            members=(a, b),
            budgets=_budgets(a="5"),
            mark_price_usdt=Decimal("60000"),
        )
    incompatible = _member(
        "qlib", "b", b_target, unit="btc", protection="x" * 64
    )
    with pytest.raises(
        MultiStrategyCoordinationError, match="protection_policy_incompatible"
    ):
        build_two_member_cohort_plan(
            members=(a, incompatible),
            budgets=_budgets(),
            mark_price_usdt=Decimal("60000"),
        )


def test_context_cannot_be_created_from_unbound_member_hash() -> None:
    a_signal, a_target = _object("a", "0.01", unit="contracts")
    b_signal, b_target = _object("b", "0.0001", unit="btc")
    a = _member("don", "a", a_target, unit="contracts")
    b = _member("qlib", "b", b_target, unit="btc")
    plan = build_two_member_cohort_plan(
        members=(a, b), budgets=_budgets(), mark_price_usdt=Decimal("60000")
    )
    forged = TargetPosition(
        timestamp_utc=NOW,
        strategy_id="b",
        symbol="BTC-USDT-SWAP",
        target_weight=0,
        target_quantity=0.0001,
        signal_id=b_signal.signal_id,
        target_position_id=b_target.target_position_id,
        metadata={"forged": True},
    )
    with pytest.raises(
        OfflineMultiStrategyContextError, match="member_object_binding_mismatch"
    ):
        issue_offline_multi_strategy_context(
            plan=plan,
            member_strategy_objects={
                "don": {"signal": a_signal, "target": a_target},
                "qlib": {"signal": b_signal, "target": forged},
            },
            timestamp_utc=NOW,
            run_id="run-1",
            client_order_id="cohort-1",
            limit_price=Decimal("60000"),
        )

    other_signal = replace(a_signal, symbol="ETH-USDT-SWAP")
    other_target = replace(a_target, symbol="ETH-USDT-SWAP")
    other_member = _member(
        "don", "a", other_target, unit="contracts"
    )
    other_symbol_plan = build_two_member_cohort_plan(
        members=(other_member, b),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
    )
    with pytest.raises(
        OfflineMultiStrategyContextError, match="member_object_binding_mismatch"
    ):
        issue_offline_multi_strategy_context(
            plan=other_symbol_plan,
            member_strategy_objects={
                "don": {"signal": other_signal, "target": other_target},
                "qlib": {"signal": b_signal, "target": b_target},
            },
            timestamp_utc=NOW,
            run_id="run-symbol",
            client_order_id="cohort-symbol",
            limit_price=Decimal("60000"),
        )


def test_context_rejects_quantity_unit_and_direction_not_bound_to_source_objects() -> None:
    a_signal, a_target = _object("a", "0.01", unit="contracts")
    b_signal, b_target = _object("b", "0.0001", unit="btc")
    valid_a = _member("don", "a", a_target, unit="contracts")
    valid_b = _member("qlib", "b", b_target, unit="btc")

    quantity_plan = build_two_member_cohort_plan(
        members=(replace(valid_a, target_quantity=Decimal("0.02")), valid_b),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
    )
    with pytest.raises(
        OfflineMultiStrategyContextError, match="member_object_binding_mismatch"
    ):
        issue_offline_multi_strategy_context(
            plan=quantity_plan,
            member_strategy_objects={
                "don": {"signal": a_signal, "target": a_target},
                "qlib": {"signal": b_signal, "target": b_target},
            },
            timestamp_utc=NOW,
            run_id="run-quantity",
            client_order_id="cohort-quantity",
            limit_price=Decimal("60000"),
        )

    unit_signal, unit_target = _object("a", "0.01", unit="btc")
    unit_member = _member("don", "a", unit_target, unit="contracts")
    unit_plan = build_two_member_cohort_plan(
        members=(unit_member, valid_b),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
    )
    with pytest.raises(
        OfflineMultiStrategyContextError, match="member_object_binding_mismatch"
    ):
        issue_offline_multi_strategy_context(
            plan=unit_plan,
            member_strategy_objects={
                "don": {"signal": unit_signal, "target": unit_target},
                "qlib": {"signal": b_signal, "target": b_target},
            },
            timestamp_utc=NOW,
            run_id="run-unit",
            client_order_id="cohort-unit",
            limit_price=Decimal("60000"),
        )

    short_signal, short_target = _object(
        "a", "0.01", unit="contracts", direction="short"
    )
    direction_member = _member(
        "don", "a", short_target, unit="contracts", direction="long"
    )
    direction_plan = build_two_member_cohort_plan(
        members=(direction_member, valid_b),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
    )
    with pytest.raises(
        OfflineMultiStrategyContextError, match="member_object_binding_mismatch"
    ):
        issue_offline_multi_strategy_context(
            plan=direction_plan,
            member_strategy_objects={
                "don": {"signal": short_signal, "target": short_target},
                "qlib": {"signal": b_signal, "target": b_target},
            },
            timestamp_utc=NOW,
            run_id="run-direction",
            client_order_id="cohort-direction",
            limit_price=Decimal("60000"),
        )


def test_context_revalidates_member_objects_after_issue() -> None:
    a_signal, a_target = _object("a", "0.01", unit="contracts")
    b_signal, b_target = _object("b", "0.0001", unit="btc")
    plan = build_two_member_cohort_plan(
        members=(
            _member("don", "a", a_target, unit="contracts"),
            _member("qlib", "b", b_target, unit="btc"),
        ),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
    )
    context = issue_offline_multi_strategy_context(
        plan=plan,
        member_strategy_objects={
            "don": {"signal": a_signal, "target": a_target},
            "qlib": {"signal": b_signal, "target": b_target},
        },
        timestamp_utc=NOW,
        run_id="run-mutation",
        client_order_id="cohort-mutation",
        limit_price=Decimal("60000"),
    )
    a_target.metadata["quantity_unit"] = "btc"

    with pytest.raises(
        OfflineMultiStrategyContextError, match="member_object_binding_mismatch"
    ):
        validate_offline_multi_strategy_context(
            context,
            run_id="run-mutation",
            order_plan={
                "client_order_id": "cohort-mutation",
                "position_before_contracts": "0",
                "position_after_contracts": "0.02",
                "contracts": "0.02",
                "side": "buy",
                "limit_price": "60000",
            },
            snapshot={
                "instrument": {
                    "contract_value_btc": "0.01",
                    "lot_size": "0.01",
                },
                "mark": {"mark_price": "60000"},
            },
            maximum_absolute_contracts=Decimal("0.02"),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda state: state["ownership_history"].append(
            {
                "effective_at_ms": "1",
                "fill_id": "forged-owner-event",
                "member_contracts": {"don": "0", "qlib": "0"},
            }
        ),
        lambda state: state["funding_allocations"].update(
            {
                "forged-bill": {
                    "raw_bill_sha256": "forged",
                    "raw_amount": "-1",
                    "currency": "USDT",
                    "members": {"don": "-1"},
                }
            }
        ),
    ),
)
def test_context_rejects_post_issue_prior_allocation_mutation(mutation) -> None:
    a_signal, a_target = _object("a", "0.01", unit="contracts")
    b_signal, b_target = _object("b", "0.0001", unit="btc")
    plan = build_two_member_cohort_plan(
        members=(
            _member("don", "a", a_target, unit="contracts"),
            _member("qlib", "b", b_target, unit="btc"),
        ),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
    )
    context = issue_offline_multi_strategy_context(
        plan=plan,
        member_strategy_objects={
            "don": {"signal": a_signal, "target": a_target},
            "qlib": {"signal": b_signal, "target": b_target},
        },
        timestamp_utc=NOW,
        run_id="run-prior-mutation",
        client_order_id="cohort-prior-mutation",
        limit_price=Decimal("60000"),
    )
    mutation(context.prior_allocation_state)

    with pytest.raises(
        OfflineMultiStrategyContextError,
        match="prior_allocation_binding_mismatch",
    ):
        validate_offline_multi_strategy_context(
            context,
            run_id="run-prior-mutation",
            order_plan={
                "client_order_id": "cohort-prior-mutation",
                "position_before_contracts": "0",
                "position_after_contracts": "0.02",
                "contracts": "0.02",
                "side": "buy",
                "limit_price": "60000",
            },
            snapshot={
                "instrument": {
                    "contract_value_btc": "0.01",
                    "lot_size": "0.01",
                },
                "mark": {"mark_price": "60000"},
            },
            maximum_absolute_contracts=Decimal("0.02"),
        )


@pytest.mark.parametrize(
    "tamper",
    (
        lambda plan: replace(
            plan,
            desired_member_contracts={
                "don": Decimal("0.02"),
                "qlib": Decimal("0.01"),
            },
            member_delta_contracts={
                "don": Decimal("0.02"),
                "qlib": Decimal("0.01"),
            },
            position_after_contracts=Decimal("0.03"),
            order_delta_contracts=Decimal("0.03"),
        ),
        lambda plan: replace(
            plan,
            member_delta_contracts={
                "don": Decimal("0.02"),
                "qlib": Decimal("0"),
            },
        ),
        lambda plan: replace(
            plan,
            position_before_contracts=Decimal("0.01"),
        ),
        lambda plan: replace(
            plan,
            position_after_contracts=Decimal("0.03"),
            order_delta_contracts=Decimal("0.03"),
        ),
    ),
)
def test_context_rejects_caller_constructed_plan_math(tamper) -> None:
    a_signal, a_target = _object("a", "0.01", unit="contracts")
    b_signal, b_target = _object("b", "0.0001", unit="btc")
    valid_plan = build_two_member_cohort_plan(
        members=(
            _member("don", "a", a_target, unit="contracts"),
            _member("qlib", "b", b_target, unit="btc"),
        ),
        budgets=_budgets(),
        mark_price_usdt=Decimal("60000"),
    )

    with pytest.raises(
        OfflineMultiStrategyContextError,
        match="plan_mathematics_mismatch",
    ):
        issue_offline_multi_strategy_context(
            plan=tamper(valid_plan),
            member_strategy_objects={
                "don": {"signal": a_signal, "target": a_target},
                "qlib": {"signal": b_signal, "target": b_target},
            },
            timestamp_utc=NOW,
            run_id="run-forged-plan",
            client_order_id="cohort-forged-plan",
            limit_price=Decimal("60000"),
        )
