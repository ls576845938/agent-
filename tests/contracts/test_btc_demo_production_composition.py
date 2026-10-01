from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant_crypto.application.btc_demo_production_composition import (
    BtcDemoProductionComposition,
    _adapt_protection_for_t2,
    _cost_inputs_from_bps,
    canonical_ledger_snapshot_sha256,
    contract_notional_usdt,
    derive_protective_capabilities,
    expected_isolated_leverage,
    validate_isolated_leverage,
)
from quant_crypto.application.runtime_risk_guardian import (
    GuardianConfig,
    GuardianLatchRecord,
    InMemoryGuardianLatchStore,
    RuntimeRiskGuardian,
    RuntimeRiskGuardianSupervisor,
)
from quant_crypto.oms.okx_demo_paper_runtime import (
    OKX_DEMO_APPROVED_PROTECTION_POLICY,
    _fault_ledger_snapshot_sha256,
)
from quant_crypto.oms.account_risk_facts import (
    ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
    ACCOUNT_DRAWDOWN_CURRENCY,
    ACCOUNT_DRAWDOWN_SCOPE,
    build_explicit_account_drawdown_baseline,
)
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    Signal,
    SignalDirection,
    TargetPosition,
)
from quant_shared.runtime.permissions import RuntimeAction


def _raw_ledger(
    *,
    exchange_snapshot: dict,
    position_count: int,
    fill_count: int,
    pending_order_count: int = 0,
    pending_algo_order_count: int = 0,
    funding_cashflow: str = "0",
    funding_bill_count: int = 0,
    drawdown: float | None = 0.0,
    snapshot_match: bool = True,
    funding_reconciled: bool = True,
    account_drawdown_fact: dict | None = None,
) -> dict:
    """Mirror the native _commit_ledger_reconciliation output exactly."""

    payload = {
        "status": "reconciled" if snapshot_match else "mismatch",
        "current_state_exchange_snapshot_match": snapshot_match,
        "exchange_snapshot_sha256": canonical_ledger_snapshot_sha256(exchange_snapshot),
        "order_count": 0,
        "pending_order_count": pending_order_count,
        "pending_algo_order_count": pending_algo_order_count,
        "fill_count": fill_count,
        "position_count": position_count,
        "funding_bill_count": funding_bill_count,
        "funding_cashflow": funding_cashflow,
        "funding_cashflow_reconciled": funding_reconciled,
        "last_funding_ledger_hash": "funding-hash",
        "fixture": False,
        "promotion_evidence_ready": False,
    }
    if drawdown is not None:
        payload["drawdown"] = drawdown
    if account_drawdown_fact is not None:
        payload["account_drawdown_fact"] = account_drawdown_fact
    return payload


def _bind_raw_ledger(status: dict, **kwargs: object) -> dict:
    status["ledger_reconciliation"] = _raw_ledger(
        exchange_snapshot=status["exchange"],
        **kwargs,
    )
    return status


def _raw_protective_status() -> dict:
    observed = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    exchange = {
        "captured_at_utc": observed.isoformat(),
        "fresh": True,
        "orders": [],
        "mark": {"mark_price": "60000"},
        "index": {"index_price": "60000"},
        "instrument": {"contract_value_btc": "0.01"},
        "balance": {"equity_usdt": "5000", "unrealized_pnl_usdt": "0", "unrealized_pnl_observed": True},
        "positions": [{
            "instrument_id": "BTC-USDT-SWAP",
            "position_side": "long",
            "contracts": "0.01",
            "unrealized_pnl": "0",
            "realized_pnl": "0",
            "unrealized_pnl_observed": True,
            "realized_pnl_observed": True,
        }],
        "fills": [{"pnl": "0", "pnl_observed": True}],
        "pending_orders": [],
        "pending_algo_orders": [],
        "bills": [],
    }
    return {
        "as_of_utc": observed.isoformat(),
        "strategy": {"strategy_id": "long_short_donchian_top5", "strategy_version": "v1"},
        "runtime": {"run_id": "run-raw-ledger", "last_heartbeat_utc": observed.isoformat()},
        "limits": {"max_net_contracts": "0.01", "max_notional_usdt": "10"},
        "exchange": exchange,
        "private_ws": {"connected": True, "listener_alive": True, "reconciled": True},
        "ledger_reconciliation": _raw_ledger(
            exchange_snapshot=exchange,
            position_count=1,
            fill_count=1,
        ),
    }


def test_profile_leverage_is_shared_and_exact() -> None:
    assert expected_isolated_leverage("baseline_1x") == Decimal("1")
    assert expected_isolated_leverage("stress_3x") == Decimal("3")
    assert validate_isolated_leverage(
        [
            {"side": "long", "margin_mode": "isolated", "leverage": "1"},
            {"side": "short", "margin_mode": "isolated", "leverage": "1"},
        ],
        Decimal("1"),
    ) == ()
    assert "leverage_mismatch" in validate_isolated_leverage(
        [{"side": "long", "margin_mode": "isolated", "leverage": "3"}],
        Decimal("1"),
    )
    assert "leverage_margin_mode_mismatch" in validate_isolated_leverage(
        [
            {"side": "long", "margin_mode": "cross", "leverage": "1"},
            {"side": "short", "margin_mode": "isolated", "leverage": "1"},
        ],
        Decimal("1"),
    )


@pytest.mark.parametrize(
    ("position_side", "expected_trigger"),
    (("long", 594.0), ("short", 606.0)),
)
def test_t2_protection_projection_always_uses_stop_loss_trigger(
    position_side: str,
    expected_trigger: float,
) -> None:
    projection = _adapt_protection_for_t2(
        {
            "attachAlgoClOrdId": "btcDP012345670099A",
            "tpTriggerPx": "58800" if position_side == "short" else "61200",
            "slTriggerPx": "60600" if position_side == "short" else "59400",
        },
        position_side=position_side,
        quantity=0.01,
        contract_value_btc=Decimal("0.01"),
    )

    assert projection["trigger_price"] == expected_trigger
    assert projection["side"] == ("sell" if position_side == "long" else "buy")


def test_production_composition_requires_explicit_t2_t3_t4_facts() -> None:
    composition = BtcDemoProductionComposition(
        source_head="a" * 40,
        max_configured_leverage=Decimal("1"),
    )
    with pytest.raises(ValueError, match="authoritative_order_objects_required"):
        composition.build_order_submission_bundle(
            signal=None,
            target_position=None,
            intent=None,
            position_before=0,
            position_after=0.01,
            action="submit_new_order",
            price="60000",
            quantity="0.01",
            venue_facts={},
            cost_facts={},
            exchange_snapshot={},
            private_ws={},
            ledger_reconciliation={},
            reference_time_utc=datetime.now(timezone.utc),
        )


def test_production_composition_does_not_accept_trusted_bool_as_guardian() -> None:
    composition = BtcDemoProductionComposition(
        source_head="a" * 40,
        max_configured_leverage=Decimal("1"),
    )
    with pytest.raises(ValueError, match="guardian_observation_required"):
        composition.build_order_submission_bundle(
            signal=None,
            target_position=None,
            intent=None,
            position_before=0,
            position_after=0.01,
            action="submit_new_order",
            price="60000",
            quantity="0.01",
            venue_facts={},
            cost_facts={},
            guardian_health={"passed": True},
            guardian_latch={"tripped": False},
        )


def test_guardian_preclassification_and_evaluation_share_normalized_protection() -> None:
    observed = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
    intent = OrderIntent(
        timestamp_utc=observed,
        strategy_id="demo",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.SELL,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        client_order_id="btcDP012345670001",
        run_id="run-protection",
    )
    raw = {
        "algo_id": "algo-long",
        "algo_client_order_id": "parent-longA",
        "parent_client_order_id": "parent-long",
        "instrument_id": "BTC-USDT-SWAP",
        "side": "sell",
        "position_side": "long",
        "size": "0.01",
        "order_type": "oco",
        "state": "live",
        "reduce_only": None,
        "reduce_only_status": "unknown",
    }
    normalized = {
        **raw,
        "owned_by_runtime": True,
        "owner_identity": "runtime-owned",
        "close_position": True,
        "reduce_only_applicability": "not_applicable_long_short_mode",
    }
    exchange = {
        "captured_at_utc": observed.isoformat(),
        "account": {"identity": {"hash": "b" * 64}},
        "balance": {
            "equity_usdt": "5000",
            "unrealized_pnl_usdt": "0",
            "unrealized_pnl_observed": True,
        },
        "instrument": {"contract_value_btc": "0.01"},
        "mark": {"mark_price": "60000"},
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0.01",
                "unrealized_pnl": "0",
                "realized_pnl": "0",
                "unrealized_pnl_observed": True,
                "realized_pnl_observed": True,
            }
        ],
        "pending_orders": [],
        "pending_algo_orders": [raw],
        "fills": [],
        "bills": [],
    }
    ledger = {
        "status": "reconciled",
        "exchange_snapshot_sha256": canonical_ledger_snapshot_sha256(exchange),
        "current_state_exchange_snapshot_match": True,
        "funding_cashflow_reconciled": True,
        "positions_consistent": True,
        "cash_consistent": True,
        "pnl_consistent": True,
        "exposure_consistent": True,
        "open_orders_consistent": True,
        "protection_consistent": True,
        "funding_cashflow": "0",
        "funding_bill_count": 0,
    }
    composition = BtcDemoProductionComposition(source_head="a" * 40)

    observation = composition._guardian_observation(
        exchange_snapshot=exchange,
        private_ws={"connected": True, "listener_alive": True},
        ledger=ledger,
        runtime={
            "run_id": "run-protection",
            "credential_namespace": "quant-system.okx-demo.trade",
            "authoritative_liveness_epoch": 1,
            "guardian_owner_identity": "runtime-owned",
            "last_heartbeat_utc": observed.isoformat(),
        },
        reference_time=observed,
        intent=intent,
        position_after=0.0,
        normalized_pending_algos=[normalized],
    )

    assert len(observation.open_orders) == 1
    assert dict(observation.open_orders[0]) == normalized
    assert len(observation.protection_facts) == 1
    assert dict(observation.protection_facts[0]) == normalized
    assert observation.risk_increasing_open_order_count == 0
    assert observation.protective_reduce_only_order_count == 1
    decision = RuntimeRiskGuardian(
        GuardianConfig(
            max_abs_exposure=10,
            max_daily_loss=10,
            max_drawdown=None,
            max_open_orders=0,
        )
    ).evaluate(observation)
    assert "protective_order_owner_missing" not in decision.reasons
    assert "protective_order_reduce_only_unknown" not in decision.reasons


def test_production_composition_builds_bound_reduction_bundle_from_facts() -> None:
    observed = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    signal = Signal(
        timestamp_utc=observed,
        strategy_id="demo",
        symbol="BTC-USDT-SWAP",
        direction=SignalDirection.LONG,
        strength=1.0,
        horizon="completed_1h_to_4h",
        reason="test",
    )
    target = TargetPosition(
        timestamp_utc=observed,
        strategy_id="demo",
        symbol="BTC-USDT-SWAP",
        target_weight=0.000001,
        target_quantity=0.005,
        signal_id=signal.signal_id,
        metadata={"order_generation_allowed": False, "forecast_id": signal.signal_id},
    )
    intent = OrderIntent(
        timestamp_utc=observed,
        strategy_id="demo",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.SELL,
        quantity=0.005,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        client_order_id="btcDP012345670001",
        run_id="run-1",
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        metadata={"position_side": "long", "action": "reduce_only"},
    )
    composition = BtcDemoProductionComposition(
        source_head="a" * 40,
        max_configured_leverage=Decimal("1"),
        max_notional=Decimal("10"),
        guardian_config={
            "max_abs_exposure": 10,
            "max_daily_loss": 10,
            "max_drawdown": 10,
            "max_open_orders": 10,
        },
    )
    exchange_snapshot = {
        "fresh": True,
        "captured_at_utc": observed.isoformat(),
        "account": {"identity": {"hash": "b" * 64}, "pnl": {"daily": 0}},
        "balance": {
            "equity_usdt": "5000",
            "unrealized_pnl_usdt": "0",
            "unrealized_pnl_observed": True,
        },
        "instrument": {"tick_size": "0.1", "contract_value_btc": "0.01"},
        "mark": {"mark_price": "60000"},
        "index": {"index_price": "60000"},
        "orders": [],
        "positions": [{
            "instrument_id": "BTC-USDT-SWAP",
            "position_side": "long",
            "contracts": "0.01",
            "unrealized_pnl": "0",
            "realized_pnl": "0",
            "unrealized_pnl_observed": True,
            "realized_pnl_observed": True,
        }],
        "fills": [{"pnl": "0", "pnl_observed": True}],
        "pending_orders": [],
        "pending_algo_orders": [],
        "bills": [],
    }
    bundle = composition.build_order_submission_bundle(
        signal=signal,
        target_position=target,
        intent=intent,
        position_before=0.01,
        position_after=0.005,
        action=RuntimeAction.REDUCE_ONLY,
        price="60000",
        quantity="0.005",
        venue_facts={
            "instrument_id": "BTC-USDT-SWAP",
            "margin_mode": "isolated",
            "position_side": "long",
            "leverage": [
                {"position_side": "long", "margin_mode": "isolated", "leverage": "1"},
                {"position_side": "short", "margin_mode": "isolated", "leverage": "1"},
            ],
        },
        cost_facts={
            "fee_bps": "5",
            "funding_bps": "0",
            "slippage_budget_bps": "2",
            "impact_bps": "1",
            "cost_model_complete": True,
        },
        exchange_snapshot=exchange_snapshot,
        private_ws={"connected": True, "listener_alive": True, "reconciled": True},
        ledger_reconciliation=_raw_ledger(
            exchange_snapshot=exchange_snapshot,
            position_count=1,
            fill_count=1,
        ),
        runtime_facts={
            "run_id": "run-1",
            "last_heartbeat_utc": observed.isoformat(),
            "authoritative_liveness_epoch": 1,
            "credential_namespace": "quant-system.okx-demo.trade",
            "client_order_namespace": intent.client_order_id[:13],
        },
        reference_time_utc=observed,
        protection_policy=OKX_DEMO_APPROVED_PROTECTION_POLICY,
    )
    assert bundle.action is RuntimeAction.REDUCE_ONLY
    assert bundle.proof_identity.evidence_status == "pending_dispatcher_authority"
    assert bundle.proof_identity.authority_verified is False
    assert bundle.portfolio_decision.reduction_plan is not None


def test_production_composition_builds_opening_bundle_from_real_snapshot_and_protection() -> None:
    observed = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    signal = Signal(
        timestamp_utc=observed,
        strategy_id="demo",
        symbol="BTC-USDT-SWAP",
        direction=SignalDirection.LONG,
        strength=1.0,
        horizon="completed_1h_to_4h",
        reason="test-opening",
    )
    target = TargetPosition(
        timestamp_utc=observed,
        strategy_id="demo",
        symbol="BTC-USDT-SWAP",
        target_weight=0.00001,
        target_quantity=0.01,
        signal_id=signal.signal_id,
        metadata={
            "order_generation_allowed": True,
            "forecast_id": signal.signal_id,
        },
    )
    intent = OrderIntent(
        timestamp_utc=observed,
        strategy_id="demo",
        symbol="BTC-USDT-SWAP",
        side=OrderSide.BUY,
        quantity=0.01,
        order_type=OrderType.LIMIT,
        limit_price=60000.0,
        client_order_id="btcDP012345670002",
        run_id="run-opening-1",
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        metadata={"position_side": "long", "action": "submit_new_order"},
    )
    latch_store = InMemoryGuardianLatchStore(
        GuardianLatchRecord(
            generation=1,
            tripped=False,
            owner_id="owner",
            fence_token="fence",
        )
    )
    supervisor = RuntimeRiskGuardianSupervisor(
        RuntimeRiskGuardian(GuardianConfig(
            max_abs_exposure=10,
            max_daily_loss=10,
            max_drawdown=10,
            max_drawdown_unit="usdt",
            max_open_orders=1,
        )),
        latch_store,
        owner_id="owner",
        fence_token="fence",
    )
    composition = BtcDemoProductionComposition(
        source_head="a" * 40,
        max_configured_leverage=Decimal("1"),
        guardian_supervisor_factory=lambda: supervisor,
    )
    try:
        exchange_snapshot = {
            "fresh": True,
            "captured_at_utc": observed.isoformat(),
            "account": {
                "identity": {"hash": "b" * 64},
                "account_level": "1",
            },
            "balance": {
                "equity_usdt": "5000",
                "unrealized_pnl_usdt": "0",
                "unrealized_pnl_observed": True,
            },
            "mark": {"mark_price": "60000"},
            "index": {"index_price": "60000"},
            "instrument": {"tick_size": "0.1", "contract_value_btc": "0.01"},
            "orders": [],
            "positions": [],
            "fills": [{"pnl": "0", "pnl_observed": True}],
            "pending_orders": [],
            "pending_algo_orders": [],
            "bills": [],
        }
        snapshot_sha256 = canonical_ledger_snapshot_sha256(exchange_snapshot)
        account_drawdown_fact = build_explicit_account_drawdown_baseline(
            authority=ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
            account_identity_hash="b" * 64,
            account_scope=ACCOUNT_DRAWDOWN_SCOPE,
            currency=ACCOUNT_DRAWDOWN_CURRENCY,
            snapshot_sha256=snapshot_sha256,
            observed_at_utc=observed,
            equity_usdt="5000",
            history_complete=False,
        )
        bundle = composition.build_order_submission_bundle(
            signal=signal,
            target_position=target,
            intent=intent,
            position_before=0.0,
            position_after=0.01,
            action=RuntimeAction.SUBMIT_NEW_ORDER,
            price="60000",
            quantity="0.01",
            venue_facts={
                "instrument_id": "BTC-USDT-SWAP",
                "margin_mode": "isolated",
                "position_side": "long",
                "leverage": [
                    {"position_side": "long", "margin_mode": "isolated", "leverage": "1"},
                    {"position_side": "short", "margin_mode": "isolated", "leverage": "1"},
                ],
            },
            cost_facts={
                "fee_bps": "5",
                "funding_bps": "0",
                "slippage_budget_bps": "2",
                "impact_bps": "1",
                "cost_model_complete": True,
            },
            exchange_snapshot=exchange_snapshot,
            private_ws={
                "connected": True,
                "listener_alive": True,
                "reconciled": True,
                "generation": 2,
                "current_generation": 2,
            },
            ledger_reconciliation=_raw_ledger(
                exchange_snapshot=exchange_snapshot,
                position_count=0,
                fill_count=1,
                account_drawdown_fact=account_drawdown_fact,
            ),
            runtime_facts={
                "run_id": "run-opening-1",
                "last_heartbeat_utc": observed.isoformat(),
                "authoritative_liveness_epoch": 2,
                "credential_namespace": "quant-system.okx-demo.trade",
                "client_order_namespace": intent.client_order_id[:13],
            },
            reference_time_utc=observed,
            protection_policy=OKX_DEMO_APPROVED_PROTECTION_POLICY,
        )
        assert bundle.action is RuntimeAction.SUBMIT_NEW_ORDER
        assert bundle.risk_assessment.approved is True
        assert bundle.protection is not None
        exchange_payload = bundle.protection.to_exchange_payload()
        assert exchange_payload["attachAlgoClOrdId"] == intent.client_order_id + "A"
        assert exchange_payload["tpTriggerPx"] and exchange_payload["slTriggerPx"]
        protection_projection = bundle.cost_facts["t2_protection_projection"]
        assert protection_projection["order_type"] == "oco"
        assert protection_projection["quantity"] == 0.01
        assert protection_projection["parent_client_order_id"] == intent.client_order_id
        assert bundle.cost_facts["fees"] == "0.00300"
        assert bundle.cost_facts["slippage"] == "0.00120"
        assert bundle.cost_facts["impact"] == "0.00060"
        assert bundle.cost_facts["prospective_funding_budget_usdt"] == "0.00000"
        reconciliation = bundle.cost_facts["reconciliation_evidence"]
        assert reconciliation["positions_consistent"] is True
        assert reconciliation["cash_consistent"] is True
        assert reconciliation["pnl_consistent"] is True
        assert reconciliation["exposure_consistent"] is True
        assert reconciliation["open_orders_consistent"] is True
        assert reconciliation["protection_consistent"] is True
        assert bundle.proof_identity.authority_verified is False
    finally:
        supervisor.close()


def test_contract_notional_uses_okx_contract_value_and_unknown_pnl_blocks() -> None:
    assert contract_notional_usdt("0.01", "60000", "0.01") == Decimal("6.00")
    costs = _cost_inputs_from_bps(
        {
            "fee_bps": "5",
            "funding_bps": "2",
            "slippage_budget_bps": "3",
            "impact_bps": "1",
            "cost_model_complete": True,
        },
        actual_notional=Decimal("6"),
        observed_funding_cashflow=Decimal("0"),
    )
    assert costs["fees"] == "0.003"
    assert costs["slippage"] == "0.0018"
    assert costs["impact"] == "0.0006"
    assert costs["prospective_funding_budget_usdt"] == "0.0012"
    with pytest.raises(ValueError, match="cost_fee_bps_missing_or_invalid"):
        _cost_inputs_from_bps(
            {"cost_model_complete": True, "funding_bps": "0", "slippage_budget_bps": "0", "impact_bps": "0"},
            actual_notional=Decimal("6"),
            observed_funding_cashflow=Decimal("0"),
        )
    with pytest.raises(ValueError, match="authoritative_pnl_facts_missing"):
        from quant_crypto.application.btc_demo_production_composition import _authoritative_pnl_facts

        _authoritative_pnl_facts(
            {
                "balance": {"equity_usdt": "5000"},
                "positions": [],
                "fills": [],
                "bills": [],
            },
            {"status": "reconciled"},
        )


def test_raw_commit_ledger_projection_is_authoritative_and_fail_closed() -> None:
    baseline = _raw_protective_status()
    baseline_capability = derive_protective_capabilities(baseline)["stop_and_flatten"]
    assert baseline_capability["allowed"] is True
    assert baseline_capability["reconciliation_evidence"]["source"] == "btc_demo_commit_ledger_reconciliation_v1"
    assert baseline_capability["reduction_cost_source"] == "risk_reduction_no_new_cost_budget"

    snapshot_mismatch = deepcopy(baseline)
    snapshot_mismatch["ledger_reconciliation"]["current_state_exchange_snapshot_match"] = False
    assert derive_protective_capabilities(snapshot_mismatch)["stop_and_flatten"]["allowed"] is False

    pnl_missing = deepcopy(baseline)
    pnl_missing["exchange"]["fills"] = []
    pnl_missing["exchange"]["positions"][0].pop("realized_pnl")
    pnl_missing["exchange"]["positions"][0].pop("realized_pnl_observed")
    capability = derive_protective_capabilities(pnl_missing)["stop_and_flatten"]
    assert capability["allowed"] is False
    assert any("authoritative_pnl_facts_missing" in blocker for blocker in capability["blockers"])

    missing_contract = deepcopy(baseline)
    missing_contract["exchange"]["instrument"].pop("contract_value_btc")
    assert derive_protective_capabilities(missing_contract)["stop_and_flatten"]["allowed"] is False

    missing_mark = deepcopy(baseline)
    missing_mark["exchange"]["mark"] = {}
    assert derive_protective_capabilities(missing_mark)["stop_and_flatten"]["allowed"] is False


def test_ledger_snapshot_hash_matches_runtime_and_binds_same_counted_facts() -> None:
    baseline = _raw_protective_status()
    assert canonical_ledger_snapshot_sha256(baseline["exchange"]) == _fault_ledger_snapshot_sha256(baseline["exchange"])
    assert baseline["ledger_reconciliation"]["exchange_snapshot_sha256"] == canonical_ledger_snapshot_sha256(baseline["exchange"])

    for field, mutate in (
        ("fills_pnl", lambda status: status["exchange"]["fills"][0].update({"pnl": "1"})),
        ("position_contracts", lambda status: status["exchange"]["positions"][0].update({"contracts": "0.009"})),
        ("position_pnl", lambda status: status["exchange"]["positions"][0].update({"realized_pnl": "1"})),
        ("balance_equity", lambda status: status["exchange"]["balance"].update({"equity_usdt": "4999"})),
    ):
        mutated = deepcopy(baseline)
        mutate(mutated)
        capability = derive_protective_capabilities(mutated)["stop_and_flatten"]
        assert capability["allowed"] is False, field
        assert "reconciliation_snapshot_hash_mismatch" in capability["blockers"], field

    for hash_value, blocker in (("", "reconciliation_snapshot_hash_missing"), ("not-a-hash", "reconciliation_snapshot_hash_invalid"), ("0" * 64, "reconciliation_snapshot_hash_mismatch")):
        mutated = deepcopy(baseline)
        mutated["ledger_reconciliation"]["exchange_snapshot_sha256"] = hash_value
        capability = derive_protective_capabilities(mutated)["stop_and_flatten"]
        assert capability["allowed"] is False
        assert blocker in capability["blockers"]


def test_snapshot_hash_binds_pending_algo_and_funding_bill_identity() -> None:
    algo_status = _raw_protective_status()
    algo_status["exchange"]["pending_algo_orders"] = [{
        "algo_id": "algo-1",
        "instrument_id": "BTC-USDT-SWAP",
        "position_side": "long",
        "state": "live",
        "order_type": "oco",
        "size": "0.01",
    }]
    algo_status = _bind_raw_ledger(algo_status, position_count=1, fill_count=1, pending_algo_order_count=1)
    assert derive_protective_capabilities(algo_status)["stop_and_flatten"]["allowed"] is True
    algo_mutation = deepcopy(algo_status)
    algo_mutation["exchange"]["pending_algo_orders"][0]["algo_id"] = "foreign-algo"
    algo_capability = derive_protective_capabilities(algo_mutation)["stop_and_flatten"]
    assert algo_capability["allowed"] is False
    assert "reconciliation_snapshot_hash_mismatch" in algo_capability["blockers"]

    funding_status = _raw_protective_status()
    funding_status["exchange"]["bills"] = [{
        "type": "8",
        "balance_change": "-0.12",
        "balance_change_observed": True,
    }]
    funding_status = _bind_raw_ledger(
        funding_status,
        position_count=1,
        fill_count=1,
        funding_bill_count=1,
        funding_cashflow="-0.12",
    )
    funding_mutation = deepcopy(funding_status)
    funding_mutation["exchange"]["bills"][0]["balance_change"] = "-0.13"
    funding_capability = derive_protective_capabilities(funding_mutation)["stop_and_flatten"]
    assert funding_capability["allowed"] is False
    assert "reconciliation_snapshot_hash_mismatch" in funding_capability["blockers"]


def test_snapshot_count_mismatches_fail_closed_even_when_hash_is_valid_for_other_facts() -> None:
    baseline = _raw_protective_status()
    fill_count = deepcopy(baseline)
    fill_count["ledger_reconciliation"]["fill_count"] = 0
    capability = derive_protective_capabilities(fill_count)["stop_and_flatten"]
    assert capability["allowed"] is False
    assert "reconciliation_fill_count_mismatch" in capability["blockers"]

    algo_count = deepcopy(baseline)
    algo_count["ledger_reconciliation"]["pending_algo_order_count"] = 1
    capability = derive_protective_capabilities(algo_count)["stop_and_flatten"]
    assert capability["allowed"] is False
    assert "reconciliation_pending_algo_order_count_mismatch" in capability["blockers"]


def test_protective_capability_projection_contains_canonical_t3_reduction_plan() -> None:
    observed = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    status = {
        "strategy": {
                "strategy_id": "long_short_donchian_top5",
                "strategy_version": "v1",
            },
        "runtime": {
                "run_id": "run-1",
                "last_heartbeat_utc": observed.isoformat(),
            },
        "limits": {"max_net_contracts": "0.01", "max_notional_usdt": "10"},
        "exchange": {
                "captured_at_utc": observed.isoformat(),
                "fresh": True,
                "mark": {"mark_price": "60000"},
                "index": {"index_price": "60000"},
                "instrument": {"contract_value_btc": "0.01"},
                "balance": {
                    "equity_usdt": "5000",
                    "unrealized_pnl_usdt": "0",
                    "unrealized_pnl_observed": True,
                },
            "orders": [],
            "positions": [{
                    "instrument_id": "BTC-USDT-SWAP",
                    "position_side": "long",
                    "contracts": "0.01",
                    "unrealized_pnl": "0",
                    "realized_pnl": "0",
                    "unrealized_pnl_observed": True,
                    "realized_pnl_observed": True,
                }],
            "fills": [{"pnl": "0", "pnl_observed": True}],
            "pending_orders": [],
            "pending_algo_orders": [],
            "bills": [],
        },
        "private_ws": {"connected": True, "listener_alive": True, "reconciled": True},
    }
    status = _bind_raw_ledger(status, position_count=1, fill_count=1)
    projection = derive_protective_capabilities(status)
    capability = projection["stop_and_flatten"]
    assert capability["allowed"] is True
    assert capability["effect"] == "decrease"
    assert capability["reduction_proof"] is True
    assert capability["reduction_plan"]["target_quantity"] == 0.0
    assert capability["reduction_plan"]["current_quantity"] == 0.01


@pytest.mark.parametrize(("side", "signed_quantity"), [("long", 0.01), ("short", -0.01)])
def test_protective_capability_is_fresh_and_signed_for_both_sides(side: str, signed_quantity: float) -> None:
    observed = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    status = {
        "as_of_utc": observed.isoformat(),
        "strategy": {"strategy_id": "long_short_donchian_top5", "strategy_version": "v1"},
        "runtime": {"run_id": "run-signed", "last_heartbeat_utc": observed.isoformat()},
        "limits": {"max_net_contracts": "0.01", "max_notional_usdt": "10"},
        "exchange": {
            "captured_at_utc": observed.isoformat(),
            "fresh": True,
            "mark": {"mark_price": "60000"},
            "index": {"index_price": "60000"},
            "instrument": {"contract_value_btc": "0.01"},
            "balance": {"equity_usdt": "5000", "unrealized_pnl_observed": True, "unrealized_pnl_usdt": "0"},
            "orders": [],
            "positions": [{
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": side,
                "contracts": "0.01",
                "unrealized_pnl": "0",
                "realized_pnl": "0",
                "unrealized_pnl_observed": True,
                "realized_pnl_observed": True,
            }],
            "fills": [{"pnl": "0", "pnl_observed": True}],
            "pending_orders": [],
            "pending_algo_orders": [],
            "bills": [],
        },
        "private_ws": {"connected": True, "listener_alive": True, "reconciled": True},
    }
    status = _bind_raw_ledger(status, position_count=1, fill_count=1)
    capability = derive_protective_capabilities(status)["stop_and_flatten"]
    assert capability["allowed"] is True
    assert capability["reduction_plan"]["current_quantity"] == signed_quantity


def test_protective_capability_rejects_snapshot_older_than_authoritative_reference() -> None:
    observed = datetime(2026, 8, 24, 11, 55, tzinfo=timezone.utc)
    status = {
        "as_of_utc": datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc).isoformat(),
        "strategy": {"strategy_id": "long_short_donchian_top5", "strategy_version": "v1"},
        "runtime": {"run_id": "run-stale", "last_heartbeat_utc": "2026-08-24T12:00:00Z"},
        "limits": {"max_net_contracts": "0.01", "max_notional_usdt": "10"},
        "exchange": {
            "captured_at_utc": observed.isoformat(),
            "fresh": True,
            "mark": {"mark_price": "60000"},
            "index": {"index_price": "60000"},
            "instrument": {"contract_value_btc": "0.01"},
            "balance": {"equity_usdt": "5000", "unrealized_pnl_observed": True, "unrealized_pnl_usdt": "0"},
            "orders": [],
            "positions": [{"instrument_id": "BTC-USDT-SWAP", "position_side": "long", "contracts": "0.01"}],
            "fills": [{"pnl": "0", "pnl_observed": True}],
            "pending_orders": [],
            "pending_algo_orders": [],
            "bills": [],
        },
        "private_ws": {"connected": True, "listener_alive": True, "reconciled": True},
    }
    status = _bind_raw_ledger(status, position_count=1, fill_count=1)
    capability = derive_protective_capabilities(status)["stop_and_flatten"]
    assert capability["allowed"] is False
    assert "protective_exchange_snapshot_stale" in capability["blockers"]


def test_existing_clear_latch_persists_trip_on_abnormal_observation() -> None:
    store = InMemoryGuardianLatchStore(
        GuardianLatchRecord(generation=1, tripped=False, owner_id="owner", fence_token="fence")
    )
    supervisor = RuntimeRiskGuardianSupervisor(
        RuntimeRiskGuardian(GuardianConfig(max_abs_exposure=1, max_daily_loss=1, max_drawdown=1, max_open_orders=0)),
        store,
        owner_id="owner",
        fence_token="fence",
    )
    try:
        decision = supervisor.trip({
            "source_head": "a" * 40,
            "account_identity": "b" * 64,
            "session_id": "run-trip",
            "key_namespace": "quant-system.okx-demo.trade",
            "client_order_namespace": "btcDP01234567",
            "epoch": 1,
            "observed_at_utc": datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
            "reference_time_utc": datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
            "heartbeat_at_utc": datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
            "heartbeat_healthy": False,
            "broker_truth_fresh": False,
            "facts_fresh": False,
            "reconciliation_passed": False,
            "ledger_reconciled": False,
            "snapshot_match": False,
            "funding_reconciled": False,
            "positions": {"total": 0, "consistent": False},
            "cash": {"equity": 0, "consistent": False},
            "pnl": {"daily": 0, "consistent": False},
            "exposure": {"total": 0, "consistent": False},
            "open_orders": {"count": 0, "consistent": False},
            "protection_facts": {"consistent": False},
            "positions_consistent": False,
            "cash_consistent": False,
            "pnl_consistent": False,
            "exposure_consistent": False,
            "open_orders_consistent": False,
            "protection_consistent": False,
            "account_equity": 0,
            "total_exposure": 0,
            "daily_pnl": 0,
            "open_order_count": 0,
            "freshness": {"captured": True},
            "evidence_identity": "test-abnormal-observation",
        })
        assert decision.tripped is True
        assert store.load_optional() is not None
        assert store.load_optional().tripped is True
    finally:
        supervisor.close()


def test_protective_capability_rejects_foreign_or_nonlive_attached_algo() -> None:
    observed = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    status = {
        "strategy": {"strategy_id": "long_short_donchian_top5", "strategy_version": "v1"},
        "runtime": {"run_id": "run-1"},
        "limits": {"max_net_contracts": "0.01", "max_notional_usdt": "10"},
        "exchange": {
            "captured_at_utc": observed.isoformat(),
            "ticker": {"mark_price": "60000", "index_price": "60000"},
            "account": {"equity_usdt": "5000"},
            "orders": [],
            "positions": [{"instrument_id": "BTC-USDT-SWAP", "position_side": "long", "contracts": "0.01"}],
            "pending_orders": [],
            "pending_algo_orders": [{
                "instrument_id": "ETH-USDT-SWAP",
                "position_side": "long",
                "state": "live",
                "order_type": "oco",
                "contracts": "0.01",
            }],
            "bills": [],
        },
        "private_ws": {"connected": True, "listener_alive": True},
    }
    status = _bind_raw_ledger(status, position_count=1, fill_count=0, pending_algo_order_count=1)
    projection = derive_protective_capabilities(status)
    assert projection["stop_and_flatten"]["allowed"] is False
    assert "protective_algo_instrument_mismatch" in projection["stop_and_flatten"]["blockers"]
