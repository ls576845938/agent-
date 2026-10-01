"""Engineering-only BTC default-strategy closure without exchange transport.

The fixture deliberately proves contract wiring and accounting invariants.  It
is synthetic, previously-unseen-market claims are out of scope, and every
execution permission flag remains false.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from quant_crypto.application.btc_demo_production_composition import (
    BtcDemoProductionComposition,
    canonical_ledger_snapshot_sha256,
)
from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
from quant_crypto.backtest.funding_ledger import (
    FundingFill,
    FundingRateEvent,
    replay_perpetual_fill_position_cash_ledger,
)
from quant_crypto.monitoring.audit_dag import (
    BTC_AUDIT_NODE_ORDER,
    BTCAuditNodeType,
    artifact_ref_from_payload,
    build_btc_audit_dag,
)
from quant_crypto.oms.lifecycle import BTCPaperOMS, BTCPaperOrderStatus
from quant_crypto.portfolio.forecast import (
    BTCForecastQuality,
    BTCRiskBudget,
    BTCRiskState,
    btc_forecast_to_target_position,
    signal_to_btc_forecast,
)
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    Signal,
    SignalDirection,
)
from quant_shared.runtime.permissions import RuntimeAction


STRATEGY_ID = "long_short_donchian_top5_okx_native"
CANDIDATE_ID = (
    "okx_native_btc_ls_tf_formal_donchian_w240_d50_200_atr20_cd12_"
    "fail0_risknone_78f5f0a0e4"
)
PARAMS_HASH = "5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355"
RUN_ID = "btc-offline-safety-fixture-20260913"
DATA_VERSION = "engineering-synthetic-trend-v1"
FIXTURE_SOURCE_HEAD = "a" * 40
CONTRACTS = Decimal("0.01")
CONTRACT_VALUE_BTC = Decimal("0.01")
BTC_QUANTITY = CONTRACTS * CONTRACT_VALUE_BTC


def _completed_hourly_trend() -> pd.DataFrame:
    """Warm the real frozen Donchian formula and force a genuine breakout."""

    index = pd.date_range("2026-01-01", periods=5_200, freq="h", tz="UTC")
    close = [10_000.0 + index_value * 10.0 for index_value in range(len(index))]
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


def _exchange_snapshot(decision_time: datetime) -> dict:
    return {
        "fresh": True,
        "captured_at_utc": decision_time.isoformat(),
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
        "instrument": {
            "tick_size": "0.1",
            "contract_value_btc": str(CONTRACT_VALUE_BTC),
        },
        "orders": [],
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": str(CONTRACTS),
                "unrealized_pnl": "0",
                "realized_pnl": "0",
                "unrealized_pnl_observed": True,
                "realized_pnl_observed": True,
            }
        ],
        "fills": [{"pnl": "0", "pnl_observed": True}],
        "pending_orders": [],
        "pending_algo_orders": [],
        "bills": [],
    }


def _ledger_reconciliation(exchange_snapshot: dict) -> dict:
    return {
        "status": "reconciled",
        "current_state_exchange_snapshot_match": True,
        "exchange_snapshot_sha256": canonical_ledger_snapshot_sha256(exchange_snapshot),
        "order_count": 0,
        "pending_order_count": 0,
        "pending_algo_order_count": 0,
        "fill_count": 1,
        "position_count": 1,
        "funding_bill_count": 0,
        "funding_cashflow": "0",
        "funding_cashflow_reconciled": True,
        "last_funding_ledger_hash": "engineering-fixture-funding-hash",
        # This is an explicit synthetic fact.  Production code is not allowed
        # to manufacture zero when its authoritative source omits drawdown.
        "drawdown": 0.10,
        "fixture": True,
        "promotion_evidence_ready": False,
    }


def _audit_payloads(*, common: dict, signal: Signal, forecast_id: str, target_id: str,
                    bundle: object, lifecycle: object, fill_id: str, ledger: object) -> dict:
    return {
        BTCAuditNodeType.DATA_SNAPSHOT: {**common, "fixture": True, "bars": 5_200},
        BTCAuditNodeType.FEATURE: {**common, "feature": "registered_donchian_inputs"},
        BTCAuditNodeType.SIGNAL: {**common, "signal_id": signal.signal_id, "direction": signal.direction.value},
        BTCAuditNodeType.FORECAST: {**common, "forecast_id": forecast_id},
        BTCAuditNodeType.TARGET: {**common, "target_id": target_id, "target_quantity_contracts": 0.0},
        BTCAuditNodeType.RISK: {**common, "risk": bundle.risk_assessment.to_dict()},
        BTCAuditNodeType.ORDER: {**common, "order": lifecycle.to_dict()},
        BTCAuditNodeType.FILL: {
            **common,
            "fill_id": fill_id,
            "quantity_contracts": float(CONTRACTS),
            "quantity_btc": float(BTC_QUANTITY),
        },
        BTCAuditNodeType.LEDGER: {**common, "position_qty_btc": ledger.position_qty, "cash_usdt": ledger.cash_balance},
        BTCAuditNodeType.PNL: {**common, "total_pnl_usdt": ledger.total_pnl},
        BTCAuditNodeType.REPORT: {
            **common,
            "engineering_only": True,
            "research_only": True,
            "paper_enabled": False,
            "live_enabled": False,
        },
    }


def test_default_strategy_same_decision_reduces_through_oms_and_reconciles_ledger() -> None:
    spec = btc_strategy_registry.get(STRATEGY_ID)
    assert spec.candidate_id == CANDIDATE_ID
    assert spec.params_hash == PARAMS_HASH
    assert spec.signal_callable is not None

    frame = _completed_hourly_trend()
    raw_signal = spec.signal_callable(frame, "1h")
    decision_time = raw_signal.index[-1].to_pydatetime().astimezone(timezone.utc)
    assert raw_signal.iloc[-1] == 1.0

    signal = Signal(
        timestamp_utc=decision_time,
        strategy_id=spec.strategy_id,
        symbol=spec.instrument,
        direction=SignalDirection.LONG,
        strength=float(abs(raw_signal.iloc[-1])),
        horizon=spec.timeframe,
        reason="registered_default_strategy_engineering_fixture",
        metadata={
            "candidate_id": spec.candidate_id,
            "params_hash": spec.params_hash,
            "data_version": DATA_VERSION,
            "fixture": True,
            "engineering_only": True,
        },
        signal_id="sig-btc-offline-safety-fixture",
    )
    forecast = signal_to_btc_forecast(
        signal,
        quality=BTCForecastQuality(
            ic=0.0,
            sample_size=1,
            evidence_path="fixture://neutral-quality",
            evidence_hash="b" * 64,
        ),
        horizon=spec.timeframe,
        expiry_bars=1,
        bar_minutes=60,
    )
    target = btc_forecast_to_target_position(
        forecast,
        risk_budget=BTCRiskBudget(
            max_btc_exposure=1.0,
            strategy_risk_budget=1.0,
            target_volatility=1.0,
            current_weight=0.00012,
            estimated_round_trip_cost_bps=10.0,
            max_daily_loss_pct=0.20,
            max_drawdown_pct=0.05,
            max_abs_funding_rate=0.01,
        ),
        risk_state=BTCRiskState(
            cash_fraction=0.99,
            daily_loss_pct=0.0,
            current_drawdown_pct=0.10,
            funding_rate=0.0001,
        ),
        account_equity=5_000.0,
        mark_price=60_000.0,
    )
    assert target.target_quantity == 0.0
    assert target.metadata["order_generation_allowed"] is False
    assert target.metadata["rebalance_reason"] == "risk_drawdown_stop"
    assert target.signal_id == signal.signal_id
    assert target.metadata["forecast_id"] == forecast.forecast_id

    intent = OrderIntent(
        timestamp_utc=decision_time,
        strategy_id=spec.strategy_id,
        symbol=spec.instrument,
        side=OrderSide.SELL,
        quantity=float(CONTRACTS),
        order_type=OrderType.LIMIT,
        limit_price=60_000.0,
        run_id=RUN_ID,
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        metadata={
            "forecast_id": forecast.forecast_id,
            "position_side": "long",
            "action": "reduce_only",
            "quantity_unit": "contracts",
            "contract_value_btc": str(CONTRACT_VALUE_BTC),
            "fixture": True,
        },
        client_order_id="btcDP091300000001",
        order_intent_id="oint-btc-offline-safety-fixture",
    )
    exchange = _exchange_snapshot(decision_time)
    composition = BtcDemoProductionComposition(
        source_head=FIXTURE_SOURCE_HEAD,
        max_configured_leverage=Decimal("1"),
        max_abs_position=CONTRACTS,
        max_notional=Decimal("10"),
        guardian_config={
            "max_abs_exposure": 10,
            "max_daily_loss": 10,
            "max_drawdown": 0.20,
            "max_open_orders": 1,
        },
    )
    bundle = composition.build_order_submission_bundle(
        signal=signal,
        target_position=target,
        intent=intent,
        position_before=float(CONTRACTS),
        position_after=0.0,
        action=RuntimeAction.REDUCE_ONLY,
        price="60000",
        quantity=str(CONTRACTS),
        venue_facts={
            "instrument_id": spec.instrument,
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
        exchange_snapshot=exchange,
        private_ws={"connected": True, "listener_alive": True, "reconciled": True},
        ledger_reconciliation=_ledger_reconciliation(exchange),
        runtime_facts={
            "run_id": RUN_ID,
            "last_heartbeat_utc": decision_time.isoformat(),
            "authoritative_liveness_epoch": 1,
            "credential_namespace": "quant-system.okx-demo.trade",
            "client_order_namespace": intent.client_order_id[:13],
        },
        reference_time_utc=decision_time,
    )
    assert bundle.action is RuntimeAction.REDUCE_ONLY
    assert bundle.risk_assessment.approved is True
    assert bundle.risk_assessment.execution_permission is False
    assert bundle.portfolio_decision.execution_permission is False
    assert bundle.portfolio_decision.reduction_plan is not None
    assert bundle.portfolio_decision.reduction_plan.reduction_quantity == float(CONTRACTS)
    assert bundle.proof_identity.authority_verified is False
    assert bundle.proof_identity.evidence_status == "pending_dispatcher_authority"
    assert bundle.guardian_latch["tripped"] is True
    assert "latch_persistence_missing" in bundle.guardian_latch["reason_codes"]

    # This is an in-memory paper lifecycle only.  Its risk approval comes from
    # the bound composition output above, never from a replay-row boolean.
    oms = BTCPaperOMS()
    lifecycle = oms.create_order(intent)
    lifecycle.mark_risk_checked(
        approved=bundle.risk_assessment.approved,
        reason="bound_t2_risk_assessment",
    )
    lifecycle.mark_submitted(broker_order_id="fixture-broker-order")
    lifecycle.mark_accepted(broker_order_id="fixture-broker-order")
    fill_id = "fill-btc-offline-safety-fixture"
    lifecycle.apply_fill(
        fill_quantity=float(CONTRACTS),
        timestamp_utc=decision_time + timedelta(seconds=1),
        fill_id=fill_id,
        price=60_000.0,
    )
    lifecycle.reconcile(metadata={"fixture": True, "transport_called": False})
    assert lifecycle.status is BTCPaperOrderStatus.RECONCILED
    assert lifecycle.filled_quantity == float(CONTRACTS)

    entry_fee = float(BTC_QUANTITY * Decimal("59000") * Decimal("0.0005"))
    exit_fee = float(BTC_QUANTITY * Decimal("60000") * Decimal("0.0005"))
    ledger = replay_perpetual_fill_position_cash_ledger(
        fills=[
            FundingFill(
                filled_at=decision_time - timedelta(hours=2),
                side="buy",
                quantity=float(BTC_QUANTITY),
                price=59_000.0,
                fill_id="fixture-entry-fill",
                fee=entry_fee,
            ),
            FundingFill(
                filled_at=decision_time + timedelta(seconds=1),
                side="sell",
                quantity=float(BTC_QUANTITY),
                price=60_000.0,
                fill_id=fill_id,
                fee=exit_fee,
            ),
        ],
        funding_rates=[
            FundingRateEvent(
                funding_time=decision_time - timedelta(hours=1),
                funding_rate=0.0001,
                mark_price=59_500.0,
                source_record_id="fixture-funding-event",
            )
        ],
        valuation_mark_price=60_000.0,
    )
    assert BTC_QUANTITY == Decimal("0.0001")
    assert lifecycle.filled_quantity * float(CONTRACT_VALUE_BTC) == pytest.approx(float(BTC_QUANTITY))
    assert exit_fee == pytest.approx(0.003)
    assert ledger.position_qty == 0.0
    assert ledger.price_pnl == pytest.approx(0.1)
    assert ledger.funding_pnl == pytest.approx(-0.000595)
    assert ledger.fee_pnl == pytest.approx(-0.00595)
    assert ledger.total_pnl == pytest.approx(0.093455)
    assert ledger.cash_balance + ledger.position_value == pytest.approx(ledger.total_pnl)

    common = {
        "run_id": RUN_ID,
        "strategy_id": spec.strategy_id,
        "candidate_id": spec.candidate_id,
        "params_hash": spec.params_hash,
        "data_version": DATA_VERSION,
        "decision_time_utc": decision_time.isoformat(),
        "fixture": True,
        "engineering_only": True,
    }
    payloads = _audit_payloads(
        common=common,
        signal=signal,
        forecast_id=forecast.forecast_id,
        target_id=target.target_position_id,
        bundle=bundle,
        lifecycle=lifecycle,
        fill_id=fill_id,
        ledger=ledger,
    )
    artifacts = {}
    previous_hash = ""
    for node_type in BTC_AUDIT_NODE_ORDER:
        inputs = {} if not previous_hash else {"previous": previous_hash}
        artifact = artifact_ref_from_payload(
            path=f"fixture://{node_type.value}",
            payload=payloads[node_type],
            code_version=FIXTURE_SOURCE_HEAD,
            input_hashes=inputs,
        )
        artifacts[node_type] = artifact
        previous_hash = artifact.artifact_hash
    risk_decision_id = artifacts[BTCAuditNodeType.RISK].artifact_hash
    dag = build_btc_audit_dag(
        run_id=RUN_ID,
        strategy_id=spec.strategy_id,
        data_version=DATA_VERSION,
        decision_time_utc=decision_time,
        artifacts=artifacts,
        log_context={
            "run_id": RUN_ID,
            "strategy_id": spec.strategy_id,
            "data_version": DATA_VERSION,
            "decision_time_utc": decision_time.isoformat(),
            "signal_id": signal.signal_id,
            "forecast_id": forecast.forecast_id,
            "target_id": target.target_position_id,
            "risk_decision_id": risk_decision_id,
            "order_id": lifecycle.order_id,
            "fill_id": fill_id,
            "error_code": "",
        },
    )
    assert dag.validate() == []
    assert dag.to_dict()["status"] == "complete"
    assert all(payload["run_id"] == RUN_ID for payload in payloads.values())
    assert payloads[BTCAuditNodeType.REPORT]["paper_enabled"] is False
    assert payloads[BTCAuditNodeType.REPORT]["live_enabled"] is False
