from __future__ import annotations

from decimal import Decimal

import pytest

from quant_crypto.oms.strategy_allocations import (
    StrategyAllocationError,
    allocate_funding_bill,
    allocate_raw_fill,
    empty_strategy_allocation_state,
    validate_allocation_conservation,
)


PLAN = {
    "member_list_sha256": "m" * 64,
    "allocation_plan_sha256": "a" * 64,
    "member_delta_contracts": {"don": "0.01", "qlib": "0.01"},
    "order_delta_contracts": "0.02",
}


def _state() -> dict:
    return empty_strategy_allocation_state(
        member_ids=("don", "qlib"), member_list_sha256="m" * 64
    )


def test_actual_fill_fee_and_funding_are_exactly_conserved() -> None:
    state = allocate_raw_fill(
        state=_state(),
        allocation_plan=PLAN,
        raw_fill={
            "fill_id": "fill-1",
            "order_id": "order-1",
            "side": "buy",
            "size": "0.02",
            "fee": "-0.002",
            "fee_currency": "USDT",
            "ts": "100",
        },
    )
    assert state["member_contracts"] == {"don": "0.01", "qlib": "0.01"}
    assert state["fill_allocations"]["fill-1"]["members"] == {
        "don": {"signed_contracts": "0.01", "fee": "-0.001"},
        "qlib": {"signed_contracts": "0.01", "fee": "-0.001"},
    }
    funded = allocate_funding_bill(
        state=state,
        raw_bill={
            "bill_id": "bill-1",
            "balance_change": "-0.10",
            "currency": "USDT",
            "ts": "150",
        },
    )
    assert funded["funding_allocations"]["bill-1"]["members"] == {
        "don": "-0.05",
        "qlib": "-0.05",
    }
    assert validate_allocation_conservation(
        state=funded, account_signed_contracts=Decimal("0.02")
    )["reconciled"] is True


def test_partial_fill_uses_actual_raw_quantity_and_freezes_duplicate() -> None:
    fill = {
        "fill_id": "fill-partial",
        "order_id": "order-1",
        "side": "buy",
        "size": "0.01",
        "fee": "-0.001",
        "fee_currency": "USDT",
        "ts": "100",
    }
    state = allocate_raw_fill(state=_state(), allocation_plan=PLAN, raw_fill=fill)
    assert state["member_contracts"] == {"don": "0.005", "qlib": "0.005"}
    assert allocate_raw_fill(
        state=state, allocation_plan=PLAN, raw_fill=fill
    ) == state
    with pytest.raises(StrategyAllocationError, match="identity_conflict"):
        allocate_raw_fill(
            state=state,
            allocation_plan=PLAN,
            raw_fill={**fill, "fee": "-9"},
        )


def test_member_exit_consumes_only_its_attributed_lot() -> None:
    opened = allocate_raw_fill(
        state=_state(),
        allocation_plan=PLAN,
        raw_fill={
            "fill_id": "open",
            "order_id": "order-open",
            "side": "buy",
            "size": "0.02",
            "fee": "-0.002",
            "ts": "100",
        },
    )
    jointly_funded = allocate_funding_bill(
        state=opened,
        raw_bill={
            "bill_id": "bill-before-exit",
            "balance_change": "-0.10",
            "currency": "USDT",
            "ts": "150",
        },
    )
    exit_plan = {
        "member_list_sha256": "m" * 64,
        "allocation_plan_sha256": "e" * 64,
        "member_delta_contracts": {"don": "-0.01", "qlib": "0"},
        "order_delta_contracts": "-0.01",
    }
    after = allocate_raw_fill(
        state=jointly_funded,
        allocation_plan=exit_plan,
        raw_fill={
            "fill_id": "exit-don",
            "order_id": "order-exit",
            "side": "sell",
            "size": "0.01",
            "fee": "-0.0005",
            "ts": "200",
        },
    )
    assert after["member_contracts"] == {"don": "0", "qlib": "0.01"}
    residual_funded = allocate_funding_bill(
        state=after,
        raw_bill={
            "bill_id": "bill-after-exit",
            "balance_change": "-0.03",
            "currency": "USDT",
            "ts": "250",
        },
    )
    assert residual_funded["funding_allocations"]["bill-before-exit"]["members"] == {
        "don": "-0.05",
        "qlib": "-0.05",
    }
    assert residual_funded["funding_allocations"]["bill-after-exit"]["members"] == {
        "qlib": "-0.03"
    }
    assert allocate_funding_bill(
        state=residual_funded,
        raw_bill={
            "bill_id": "bill-after-exit",
            "balance_change": "-0.03",
            "currency": "USDT",
            "ts": "250",
        },
    ) == residual_funded
    assert validate_allocation_conservation(
        state=residual_funded, account_signed_contracts=Decimal("0.01")
    )["reconciled"] is True


def test_late_observed_funding_uses_proven_ownership_at_bill_time() -> None:
    opened = allocate_raw_fill(
        state=_state(),
        allocation_plan=PLAN,
        raw_fill={
            "fill_id": "open",
            "order_id": "order-open",
            "side": "buy",
            "size": "0.02",
            "fee": "-0.002",
            "ts": "100",
        },
    )
    after_exit = allocate_raw_fill(
        state=opened,
        allocation_plan={
            "member_list_sha256": "m" * 64,
            "allocation_plan_sha256": "e" * 64,
            "member_delta_contracts": {"don": "-0.01", "qlib": "0"},
            "order_delta_contracts": "-0.01",
        },
        raw_fill={
            "fill_id": "exit-don",
            "order_id": "order-exit",
            "side": "sell",
            "size": "0.01",
            "fee": "-0.0005",
            "ts": "200",
        },
    )

    late_observed = allocate_funding_bill(
        state=after_exit,
        raw_bill={
            "bill_id": "settled-before-exit",
            "balance_change": "-0.10",
            "currency": "USDT",
            "ts": "150",
        },
    )

    assert late_observed["member_contracts"] == {"don": "0", "qlib": "0.01"}
    assert late_observed["funding_allocations"]["settled-before-exit"][
        "members"
    ] == {"don": "-0.05", "qlib": "-0.05"}
    assert late_observed["funding_allocations"]["settled-before-exit"][
        "ownership_effective_at_ms"
    ] == "100"


@pytest.mark.parametrize("bill", [
    {"bill_id": "missing-time", "balance_change": "-0.01"},
    {"bill_id": "same-time", "balance_change": "-0.01", "ts": "100"},
])
def test_first_seen_funding_without_proven_later_ownership_fails_closed(
    bill: dict,
) -> None:
    opened = allocate_raw_fill(
        state=_state(),
        allocation_plan=PLAN,
        raw_fill={
            "fill_id": "open",
            "order_id": "order-open",
            "side": "buy",
            "size": "0.02",
            "fee": "-0.002",
            "ts": "100",
        },
    )
    with pytest.raises(StrategyAllocationError, match="funding_time_or_owner_unproven"):
        allocate_funding_bill(state=opened, raw_bill=bill)
