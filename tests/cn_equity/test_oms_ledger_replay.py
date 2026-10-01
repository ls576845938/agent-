from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quant_cn.application.market_semantics_preflight import MarketSemanticsPreflight
from quant_cn.execution.models import Fill
from quant_cn.execution.oms import OMSConflictError, OMSStateError, OfflineOMS
from quant_cn.execution.simulator import SimulationSnapshot, simulate
from quant_cn.ledger import (
    InMemoryLedgerStore,
    derive_account_state,
    post_fill,
    post_mark,
    post_opening_cash,
    reconcile,
    sellable_quantity,
)
from quant_cn.ledger.shared_adapter import to_shared_ledger
from quant_cn.market.rules import BoardLotPolicy, FeeComponent, FeePolicy
from quant_cn.portfolio import (
    RiskInputs,
    TargetPosition,
    build_order_intent,
    evaluate_target,
)
from quant_cn.replay import ReplayInput, run_replay
from quant_cn.replay.shared_adapter import to_shared_replay_input


NOW = datetime(2026, 7, 24, 2, 0, tzinfo=timezone.utc)
VERSIONS = (
    ("board_lot", "cn-fixture-board-lot-v1"),
    ("fee_schedule", "cn-fixture-fee-v1"),
    ("price_limit", "cn-fixture-limit-v1"),
    ("sellability", "cn-fixture-t1-v1"),
    ("session", "cn-fixture-session-v1"),
    ("settlement", "cn-fixture-settlement-v1"),
)


def preflight(*blockers: str) -> MarketSemanticsPreflight:
    return MarketSemanticsPreflight(
        status="blocked" if blockers else "pass",
        decision="blocked" if blockers else "research_only",
        blockers=tuple(blockers),
        versions=VERSIONS,
        sources=tuple((key, f"fixture://{key}") for key, _ in VERSIONS),
    )


def board_lot() -> BoardLotPolicy:
    return BoardLotPolicy(
        buy_lot_size=100,
        sell_lot_size=100,
        odd_lot_sell_allowed=True,
        odd_lot_sell_mode="full_remainder_only",
    )


def fees() -> FeePolicy:
    component = FeeComponent(
        name="commission",
        rate=Decimal("0.001"),
        minimum_amount=Decimal("0"),
        fixed_amount=Decimal("0"),
        rounding_quantum=Decimal("0.01"),
        rounding_mode="half_up",
    )
    tax = FeeComponent(
        name="sell_tax",
        rate=Decimal("0.001"),
        minimum_amount=Decimal("0"),
        fixed_amount=Decimal("0"),
        rounding_quantum=Decimal("0.01"),
        rounding_mode="half_up",
    )
    return FeePolicy(buy=(component,), sell=(component, tax))


def risk_inputs(**overrides: object) -> RiskInputs:
    values: dict[str, object] = {
        "preflight": preflight(),
        "board_lot_policy": board_lot(),
        "rule_versions": VERSIONS,
        "limit_price": Decimal("10.00"),
        "available_cash": Decimal("100000"),
        "sellable_quantity": 1000,
        "estimated_fee": Decimal("1"),
        "max_order_notional": Decimal("50000"),
        "session_sequence": 42,
    }
    values.update(overrides)
    return RiskInputs(**values)  # type: ignore[arg-type]


def intent(*, target_quantity: int = 200, current_quantity: int = 0, suffix: str = "1"):
    target = TargetPosition(
        target_id=f"target-{suffix}",
        run_id="run-fixture",
        stable_security_id="CN:600000",
        target_quantity=target_quantity,
        current_quantity=current_quantity,
        decision_time=NOW,
        evidence_hash="a" * 64,
    )
    inputs = risk_inputs()
    decision = evaluate_target(target, inputs, decision_id=f"risk-{suffix}")
    assert decision.approved
    return build_order_intent(
        target,
        decision,
        inputs,
        order_id=f"order-{suffix}",
        client_order_id=f"client-{suffix}",
        created_at=NOW,
    )


def fill(
    *,
    fill_id: str = "fill-1",
    order_id: str = "order-1",
    quantity: int = 100,
    price: str = "10.00",
    side: str = "buy",
    occurred_at: datetime = NOW + timedelta(minutes=1),
    received_at: datetime | None = None,
    session_sequence: int = 42,
) -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id=order_id,
        stable_security_id="CN:600000",
        side=side,
        quantity=quantity,
        price=Decimal(price),
        fee_components=(("commission", Decimal("1.00")),),
        occurred_at=occurred_at,
        received_at=received_at or occurred_at,
        session_sequence=session_sequence,
    )


def snapshot(**overrides: object) -> SimulationSnapshot:
    values: dict[str, object] = {
        "snapshot_id": "snapshot-1",
        "as_of": NOW + timedelta(minutes=1),
        "phase": "continuous",
        "accepts_orders": True,
        "suspended": False,
        "lower_limit_price": Decimal("9.00"),
        "upper_limit_price": Decimal("11.00"),
        "tick_size": Decimal("0.01"),
        "available_liquidity": 100,
        "available_cash": Decimal("100000"),
        "current_position": 0,
        "sellable_quantity": 0,
        "execution_price": Decimal("10.00"),
        "rule_source_versions": VERSIONS,
    }
    values.update(overrides)
    return SimulationSnapshot(**values)  # type: ignore[arg-type]


def test_target_risk_intent_chain_and_fail_closed_rules() -> None:
    approved_intent = intent()
    assert approved_intent.quantity == 200
    assert all(value is False for value in approved_intent.safety_flags.values())

    odd = TargetPosition("odd", "run", "CN:600000", 150, 0, NOW, "b" * 64)
    odd_decision = evaluate_target(odd, risk_inputs(), decision_id="risk-odd")
    assert not odd_decision.approved
    assert odd_decision.blockers == ("buy_lot_invalid",)

    blocked = evaluate_target(
        replace(odd, target_quantity=200),
        risk_inputs(preflight=preflight("board_lot_rule_missing")),
        decision_id="risk-blocked",
    )
    assert blocked.blockers == ("board_lot_rule_missing",)
    with pytest.raises(ValueError, match="risk_decision_not_approved"):
        build_order_intent(
            replace(odd, target_quantity=200),
            blocked,
            risk_inputs(preflight=preflight("board_lot_rule_missing")),
            order_id="never",
            client_order_id="never",
            created_at=NOW,
        )


def test_t_plus_one_and_cash_limits_block_at_risk() -> None:
    sell = TargetPosition("sell", "run", "CN:600000", 0, 200, NOW, "c" * 64)
    decision = evaluate_target(
        sell,
        risk_inputs(sellable_quantity=0),
        decision_id="risk-sell",
    )
    assert decision.blockers == ("t_plus_one_sellability_blocked",)

    buy = TargetPosition("buy", "run", "CN:600000", 200, 0, NOW, "d" * 64)
    decision = evaluate_target(
        buy,
        risk_inputs(available_cash=Decimal("100")),
        decision_id="risk-cash",
    )
    assert decision.blockers == ("cash_insufficient",)


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        ({"suspended": True}, "security_suspended"),
        ({"accepts_orders": False}, "session_not_accepting_orders"),
        ({"phase": "unknown"}, "session_phase_unknown"),
        ({"upper_limit_price": Decimal("9.99")}, "price_above_limit"),
        ({"lower_limit_price": Decimal("10.01")}, "price_below_limit"),
        ({"available_cash": Decimal("1")}, "cash_insufficient"),
    ],
)
def test_simulator_rejects_market_and_cash_violations(
    changes: dict[str, object], blocker: str
) -> None:
    result = simulate(
        intent(),
        preflight=preflight(),
        snapshot=snapshot(**changes),
        board_lot_policy=board_lot(),
        fee_policy=fees(),
        fill_id="fill-sim",
        received_at=NOW + timedelta(minutes=2),
    )
    assert result.status == "rejected"
    assert blocker in result.blockers


def test_partial_fill_fee_and_oms_lifecycle() -> None:
    order = intent()
    result = simulate(
        order,
        preflight=preflight(),
        snapshot=snapshot(available_liquidity=100),
        board_lot_policy=board_lot(),
        fee_policy=fees(),
        fill_id="fill-partial",
        received_at=NOW + timedelta(minutes=2),
    )
    assert result.status == "partially_filled"
    assert result.fills[0].total_fee == Decimal("1.00")
    oms = OfflineOMS()
    oms.submit(order)
    state = oms.apply_fill(result.fills[0])
    assert state.status == "partially_filled"
    assert state.remaining_quantity == 100
    oms.request_cancel(order.order_id, requested_at=NOW + timedelta(minutes=3))
    assert oms.confirm_cancel(order.order_id, confirmed_at=NOW + timedelta(minutes=4)).status == "cancelled"
    with pytest.raises(OMSStateError, match="fill_for_terminal_order"):
        oms.apply_fill(fill(fill_id="late", quantity=100))


def test_opening_auction_is_explicitly_simulatable_offline() -> None:
    result = simulate(
        intent(),
        preflight=preflight(),
        snapshot=snapshot(phase="opening_auction", available_liquidity=200),
        board_lot_policy=board_lot(),
        fee_policy=fees(),
        fill_id="fill-auction",
        received_at=NOW + timedelta(minutes=2),
    )
    assert result.status == "filled"


def test_oms_idempotency_reject_and_expire() -> None:
    order = intent()
    oms = OfflineOMS()
    first = oms.submit(order)
    assert oms.submit(order) is first
    with pytest.raises(OMSConflictError, match="client_order_id_conflict"):
        oms.submit(replace(order, order_id="other"))

    rejected = OfflineOMS()
    rejected.submit(order)
    assert rejected.reject(order.order_id, ("venue_rejected",)).status == "rejected"

    expired = OfflineOMS()
    expired.submit(order)
    assert expired.expire(order.order_id, expired_at=NOW + timedelta(days=1)).status == "expired"


def test_ledger_is_fill_driven_uow_rolls_back_and_pnl_uses_marks() -> None:
    store = InMemoryLedgerStore()
    post_opening_cash(
        store,
        record_id="opening",
        amount=Decimal("5000"),
        occurred_at=NOW,
        source_hash="opening-fixture",
    )
    first_fill = fill()
    post_fill(store, first_fill)
    post_fill(store, first_fill)  # exact duplicate is idempotent
    state = derive_account_state(store)
    assert state.cash == Decimal("3999.00")
    assert state.positions == (("CN:600000", 100),)
    assert sellable_quantity(
        store,
        stable_security_id="CN:600000",
        current_session_sequence=42,
        settlement_sessions=1,
    ) == 0
    assert sellable_quantity(
        store,
        stable_security_id="CN:600000",
        current_session_sequence=43,
        settlement_sessions=1,
    ) == 100
    post_mark(
        store,
        record_id="mark-1",
        stable_security_id="CN:600000",
        price=Decimal("11"),
        occurred_at=NOW + timedelta(minutes=2),
        source_hash="mark-fixture",
    )
    assert derive_account_state(store).pnl == Decimal("99.00")

    insufficient = InMemoryLedgerStore()
    post_opening_cash(
        insufficient,
        record_id="opening-small",
        amount=Decimal("10"),
        occurred_at=NOW,
        source_hash="opening-small",
    )
    with pytest.raises(ValueError, match="ledger_cash_negative"):
        post_fill(insufficient, first_fill)
    assert len(insufficient.records()) == 1


def test_reconciliation_difference_blocks_gate() -> None:
    order = intent()
    oms = OfflineOMS()
    oms.submit(order)
    oms.apply_fill(fill())
    ledger = InMemoryLedgerStore()
    post_opening_cash(
        ledger,
        record_id="opening",
        amount=Decimal("5000"),
        occurred_at=NOW,
        source_hash="opening",
    )
    result = reconcile(orders=oms.states(), ledger=ledger, opening_cash=Decimal("5000"))
    assert result.blocks_gate
    assert "fill_ledger_mismatch" in result.blockers


def test_replay_sorts_out_of_order_and_deduplicates_fills() -> None:
    order = intent()
    later = fill(fill_id="fill-b", quantity=100, occurred_at=NOW + timedelta(minutes=2))
    earlier = fill(fill_id="fill-a", quantity=100, occurred_at=NOW + timedelta(minutes=1))
    replay = ReplayInput(
        replay_id="replay-1",
        source_mode="injected_history",
        source_ref="immutable-fixture-v1",
        fixed_clock=NOW + timedelta(hours=1),
        seed=7,
        opening_cash=Decimal("5000"),
        orders=(order,),
        fills=(later, earlier, earlier),
        expected_cash=Decimal("2998.00"),
        expected_positions=(("CN:600000", 200),),
    )
    first = run_replay(replay)
    second = run_replay(replace(replay, fills=(earlier, later)))
    assert first.status == "reconciled"
    assert first.replay_hash == second.replay_hash
    assert first.pnl == Decimal("-2002.00")  # no ledger mark means positions value at zero
    assert all(value is False for value in first.safety_flags.values())


def test_replay_blocks_conflicts_differences_and_external_sources() -> None:
    order = intent()
    original = fill()
    conflicting = replace(original, price=Decimal("10.01"))
    result = run_replay(
        ReplayInput(
            replay_id="conflict",
            source_mode="injected_history",
            source_ref="immutable-fixture-v1",
            fixed_clock=NOW + timedelta(hours=1),
            seed=1,
            opening_cash=Decimal("5000"),
            orders=(order,),
            fills=(original, conflicting),
            expected_cash=Decimal("0"),
        )
    )
    assert result.status == "blocked"
    assert "fill_id_conflict" in result.blockers
    assert "expected_cash_mismatch" in result.blockers

    with pytest.raises(ValueError, match="replay_external_or_mutable_source_forbidden"):
        ReplayInput(
            replay_id="bad-source",
            source_mode="injected_history",
            source_ref="artifacts/latest/live",
            fixed_clock=NOW,
            seed=1,
            opening_cash=Decimal("0"),
            orders=(),
            fills=(),
        )


def test_integrated_shared_v2_adapters_remain_asset_neutral() -> None:
    order = intent()
    one_fill = fill()
    ledger = InMemoryLedgerStore()
    post_opening_cash(
        ledger,
        record_id="opening-shared",
        amount=Decimal("5000"),
        occurred_at=NOW,
        source_hash="opening-shared",
    )
    post_fill(ledger, one_fill)
    shared_records = to_shared_ledger(
        ledger.records(),
        stream_id="fixture-stream",
        evidence_ids=("evidence-1",),
    )
    assert {record.record_type for record in shared_records} <= {
        "cash",
        "fill",
        "position",
        "reversal",
    }
    assert all("board" not in record.payload for record in shared_records)

    shared_replay = to_shared_replay_input(
        ReplayInput(
            replay_id="shared-replay",
            source_mode="injected_history",
            source_ref="immutable-fixture-v1",
            fixed_clock=NOW + timedelta(hours=1),
            seed=17,
            opening_cash=Decimal("5000"),
            orders=(order,),
            fills=(one_fill,),
        )
    )
    assert shared_replay.random_seed == 17
    assert all(event.event_type in {"order", "fill"} for event in shared_replay.events)
