"""Fail-closed supervised 10 USDT BTC micro-live candidate contract.

This module evaluates an already-produced ``OrderIntent`` and ``RiskDecision``.
It never calls a strategy, credential store, exchange, socket, HTTP client, or
order endpoint, and it never enables live orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from quant_crypto.monitoring.artifact_schema import (
    apply_btc_artifact_schema,
    stable_payload_hash,
)
from quant_crypto.oms.private_ws_reconciliation import BTCPrivateWSRuntimeReceipt
from quant_crypto.oms.venue_rules import BTCVenueRules, apply_btc_venue_rules
from quant_crypto.risk.liquidation import (
    BTCLiquidationPolicy,
    BTCPerpPositionState,
    BTCReferencePriceState,
    evaluate_btc_perp_liquidation_risk,
)
from quant_crypto.trading_contracts import OrderIntent, RiskDecision
from quant_shared.core.time import ensure_utc


SCHEMA_VERSION = "btc_lean_microlive_canary_v1"
INSTRUMENT_ID = "BTC-USDT-SWAP"
EXTERNAL_BLOCKERS = (
    "btc_lean_microlive:real_private_ws_observation_missing",
    "btc_lean_microlive:runtime_account_snapshot_missing",
    "btc_lean_microlive:operator_live_session_not_started",
    "btc_lean_microlive:live_order_capability_not_enabled_by_ticket",
)
FALSE_SAFETY = {
    "network_accessed": False,
    "socket_created": False,
    "http_client_created": False,
    "private_endpoint_accessed": False,
    "order_endpoint_accessed": False,
    "demo_order_submitted": False,
    "real_order_submitted": False,
    "paper_queue_written": False,
    "paper_allowed": False,
    "live_allowed": False,
    "live_ready": False,
    "live_enabled": False,
    "live_unlock_allowed": False,
    "withdraw_allowed": False,
    "secrets_read": False,
    "secrets_output": False,
}


@dataclass(frozen=True)
class MicroLiveApprovalProof:
    account_hash: str
    venue: str
    reviewer: str
    reviewed_at_utc: datetime | None
    approval_ticket: str
    permission_conclusion: str
    external_proof_id: str
    credential_namespace: str
    withdraw_permission: bool

    def __post_init__(self) -> None:
        if self.reviewed_at_utc is not None:
            object.__setattr__(
                self, "reviewed_at_utc", ensure_utc(self.reviewed_at_utc)
            )

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if len(self.account_hash) != 64 or any(
            char not in "0123456789abcdef" for char in self.account_hash
        ):
            blockers.append("btc_lean_microlive:account_hash_invalid")
        if self.venue.lower() != "okx":
            blockers.append("btc_lean_microlive:venue_must_be_okx")
        for name in (
            "reviewer",
            "approval_ticket",
            "permission_conclusion",
            "external_proof_id",
        ):
            if not str(getattr(self, name)).strip():
                blockers.append(f"btc_lean_microlive:{name}_missing")
        if self.reviewed_at_utc is None:
            blockers.append("btc_lean_microlive:reviewed_at_utc_missing")
        if not self.credential_namespace.startswith("quant-system.okx-live."):
            blockers.append(
                "btc_lean_microlive:live_credential_namespace_invalid"
            )
        if self.withdraw_permission:
            blockers.append("btc_lean_microlive:withdraw_permission_present")
        return blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_hash": self.account_hash,
            "venue": self.venue,
            "reviewer": self.reviewer,
            "reviewed_at_utc": (
                self.reviewed_at_utc.isoformat()
                if self.reviewed_at_utc is not None
                else None
            ),
            "approval_ticket": self.approval_ticket,
            "permission_conclusion": self.permission_conclusion,
            "external_proof_id": self.external_proof_id,
            "credential_namespace": self.credential_namespace,
            "withdraw_permission": self.withdraw_permission,
            "secret_fields_allowed": False,
        }


@dataclass(frozen=True)
class SupervisedMicroLiveAuthorization:
    instrument_id: str
    margin_mode: str
    leverage: float
    max_notional_usdt: float
    max_positions: int
    max_active_orders: int
    max_daily_loss_usdt: float
    max_daily_new_orders: int
    auto_start: bool
    auto_scale: bool
    single_strategy_id: str
    manual_supervision_required: bool
    proof: MicroLiveApprovalProof

    def blockers(self) -> list[str]:
        blockers = list(self.proof.blockers())
        expected = {
            "instrument_id": (self.instrument_id, INSTRUMENT_ID),
            "margin_mode": (self.margin_mode, "isolated"),
            "leverage": (float(self.leverage), 1.0),
            "max_notional_usdt": (float(self.max_notional_usdt), 10.0),
            "max_positions": (int(self.max_positions), 1),
            "max_active_orders": (int(self.max_active_orders), 1),
            "max_daily_loss_usdt": (float(self.max_daily_loss_usdt), 1.0),
            "max_daily_new_orders": (int(self.max_daily_new_orders), 2),
        }
        for name, (observed, required) in expected.items():
            if observed != required:
                blockers.append(
                    f"btc_lean_microlive:{name}_must_equal_{str(required).replace('.', 'p')}"
                )
        if not self.single_strategy_id.strip():
            blockers.append("btc_lean_microlive:single_strategy_id_missing")
        if not self.manual_supervision_required:
            blockers.append(
                "btc_lean_microlive:manual_supervision_must_be_required"
            )
        if self.auto_start:
            blockers.append("btc_lean_microlive:auto_start_forbidden")
        if self.auto_scale:
            blockers.append("btc_lean_microlive:auto_scale_forbidden")
        return blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "margin_mode": self.margin_mode,
            "leverage": self.leverage,
            "max_notional_usdt": self.max_notional_usdt,
            "max_positions": self.max_positions,
            "max_active_orders": self.max_active_orders,
            "max_daily_loss_usdt": self.max_daily_loss_usdt,
            "max_daily_new_orders": self.max_daily_new_orders,
            "auto_start": self.auto_start,
            "auto_scale": self.auto_scale,
            "single_strategy_id": self.single_strategy_id,
            "manual_supervision_required": self.manual_supervision_required,
            "proof": self.proof.to_dict(),
        }


@dataclass(frozen=True)
class FundingCashLedgerEvidence:
    bill_ids: tuple[str, ...]
    funding_cashflow_source_ids: tuple[str, ...]
    funding_bill_total_usdt: float
    funding_cash_ledger_total_usdt: float
    cash_ledger_reconciled: bool
    pnl_derived_from: tuple[str, ...]
    unexpected_funding_count: int = 0

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if not self.bill_ids:
            blockers.append("btc_lean_microlive:funding_bills_missing")
        if not self.funding_cashflow_source_ids:
            blockers.append(
                "btc_lean_microlive:funding_cash_ledger_entries_missing"
            )
        if set(self.bill_ids) != set(self.funding_cashflow_source_ids):
            blockers.append(
                "btc_lean_microlive:funding_bill_cash_ledger_identity_mismatch"
            )
        if (
            abs(
                float(self.funding_bill_total_usdt)
                - float(self.funding_cash_ledger_total_usdt)
            )
            > 1e-9
        ):
            blockers.append("btc_lean_microlive:funding_cash_ledger_total_mismatch")
        if not self.cash_ledger_reconciled:
            blockers.append("btc_lean_microlive:cash_ledger_not_reconciled")
        required = {"fills", "positions", "cash_ledger", "funding_ledger"}
        if set(self.pnl_derived_from) != required:
            blockers.append("btc_lean_microlive:pnl_provenance_invalid")
        if self.unexpected_funding_count:
            blockers.append("btc_lean_microlive:unexpected_funding_cashflow")
        return blockers


@dataclass(frozen=True)
class MicroLiveRuntimeLimits:
    position_count: int
    active_order_count: int
    daily_loss_usdt: float
    daily_new_order_count: int
    kill_switch_engaged: bool
    cancel_only: bool
    connection_state: str


def evaluate_supervised_micro_live_candidate(
    *,
    current_head: str,
    generated_at_utc: datetime,
    authorization: SupervisedMicroLiveAuthorization,
    order_intent: OrderIntent,
    risk_decision: RiskDecision,
    private_ws: BTCPrivateWSRuntimeReceipt,
    funding_ledger: FundingCashLedgerEvidence,
    runtime_limits: MicroLiveRuntimeLimits,
    reference_prices: BTCReferencePriceState,
    position: BTCPerpPositionState,
    liquidation_policy: BTCLiquidationPolicy,
    venue_rules: BTCVenueRules,
) -> dict[str, Any]:
    generated = ensure_utc(generated_at_utc)
    blockers = authorization.blockers()
    if order_intent.strategy_id != authorization.single_strategy_id:
        blockers.append("btc_lean_microlive:strategy_not_authorized")
    if order_intent.symbol != INSTRUMENT_ID:
        blockers.append("btc_lean_microlive:instrument_identity_mismatch")
    if not order_intent.signal_id or not order_intent.target_position_id:
        blockers.append("btc_lean_microlive:signal_target_lineage_missing")
    if (
        not risk_decision.approved
        or risk_decision.order_intent_id != order_intent.order_intent_id
    ):
        blockers.append("btc_lean_microlive:risk_decision_missing_or_mismatched")
    if not private_ws.opening_allowed or private_ws.cancel_only:
        blockers.extend(private_ws.blockers)
        blockers.append("btc_lean_microlive:private_state_not_opening_safe")
    blockers.extend(funding_ledger.blockers())
    if runtime_limits.position_count > authorization.max_positions:
        blockers.append("btc_lean_microlive:position_cap_breached")
    if runtime_limits.active_order_count >= authorization.max_active_orders:
        blockers.append("btc_lean_microlive:active_order_cap_reached")
    if runtime_limits.daily_loss_usdt >= authorization.max_daily_loss_usdt:
        blockers.append("btc_lean_microlive:daily_loss_limit_reached")
    if (
        runtime_limits.daily_new_order_count
        >= authorization.max_daily_new_orders
    ):
        blockers.append("btc_lean_microlive:daily_new_order_limit_reached")
    if runtime_limits.kill_switch_engaged:
        blockers.append("btc_lean_microlive:kill_switch_engaged")
    if runtime_limits.cancel_only:
        blockers.append("btc_lean_microlive:runtime_cancel_only")
    if runtime_limits.connection_state != "known_healthy":
        blockers.append("btc_lean_microlive:connection_state_unknown_or_degraded")

    liquidation = evaluate_btc_perp_liquidation_risk(
        reference_prices=reference_prices,
        position=position,
        policy=liquidation_policy,
    )
    blockers.extend(liquidation.blockers)
    venue = apply_btc_venue_rules(
        order_intent,
        venue_rules=venue_rules,
        reference_price=reference_prices.execution_price,
        decision_time_utc=order_intent.timestamp_utc,
    )
    blockers.extend(venue.blockers)
    if venue.notional > authorization.max_notional_usdt:
        blockers.append("btc_lean_microlive:notional_cap_breached")
    engineering_blockers = _dedupe(blockers)
    all_blockers = [*engineering_blockers, *EXTERNAL_BLOCKERS]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "quality_checked_candidate_external_runtime_blocked"
            if not engineering_blockers
            else "blocked_fail_closed"
        ),
        "code_commit": current_head,
        "authorization": authorization.to_dict(),
        "request_chain": {
            "strategy_output_type": "OrderIntent",
            "signal_id": order_intent.signal_id,
            "target_position_id": order_intent.target_position_id,
            "order_intent_id": order_intent.order_intent_id,
            "risk_check_id": risk_decision.risk_check_id,
            "risk_approved": risk_decision.approved,
            "oms_consumes_risk_approved_order_intent_only": True,
            "strategy_exchange_dependency": False,
        },
        "runtime_limits": {
            "position_count": runtime_limits.position_count,
            "active_order_count": runtime_limits.active_order_count,
            "daily_loss_usdt": runtime_limits.daily_loss_usdt,
            "daily_new_order_count": runtime_limits.daily_new_order_count,
            "kill_switch_engaged": runtime_limits.kill_switch_engaged,
            "cancel_only": runtime_limits.cancel_only,
            "connection_state": runtime_limits.connection_state,
        },
        "private_ws_reconciliation": private_ws.to_dict(),
        "funding_ledger": {
            "bill_ids": list(funding_ledger.bill_ids),
            "cashflow_source_ids": list(
                funding_ledger.funding_cashflow_source_ids
            ),
            "funding_bill_total_usdt": funding_ledger.funding_bill_total_usdt,
            "funding_cash_ledger_total_usdt": (
                funding_ledger.funding_cash_ledger_total_usdt
            ),
            "cash_ledger_reconciled": funding_ledger.cash_ledger_reconciled,
            "pnl_derived_from": list(funding_ledger.pnl_derived_from),
            "unexpected_funding_count": funding_ledger.unexpected_funding_count,
        },
        "opening_gate": {
            "engineering_contracts_valid": not engineering_blockers,
            "candidate_request_construction_ready": not engineering_blockers,
            "real_runtime_evidence_present": False,
            "live_order_allowed": False,
            "blockers": engineering_blockers,
        },
        "liquidation_risk": liquidation.to_metadata(),
        "venue_validation": {
            "approved": venue.approved,
            "blockers": venue.blockers,
            "notional": venue.notional,
            "metadata": venue.metadata,
        },
        "safety": dict(FALSE_SAFETY),
        "blockers": all_blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision=(
            "quality_checked_recording_only_candidate_external_runtime_blocked"
            if not engineering_blockers
            else "blocked_fail_closed_engineering_contract_invalid"
        ),
        generated_at_utc=generated,
        as_of_utc=generated,
        blockers=all_blockers,
        warnings=[
            "recording-only canary; no private, order, demo, paper, or live endpoint was accessed"
        ],
        input_hashes={
            "authorization": stable_payload_hash(authorization.to_dict()),
            "order_intent": stable_payload_hash(
                {
                    "strategy_id": order_intent.strategy_id,
                    "symbol": order_intent.symbol,
                    "side": order_intent.side.value,
                    "quantity": order_intent.quantity,
                    "order_type": order_intent.order_type.value,
                    "limit_price": order_intent.limit_price,
                    "time_in_force": order_intent.time_in_force.value,
                    "signal_id": order_intent.signal_id,
                    "target_position_id": order_intent.target_position_id,
                    "order_intent_id": order_intent.order_intent_id,
                    "client_order_id": order_intent.client_order_id,
                }
            ),
            "private_ws": stable_payload_hash(private_ws.to_dict()),
        },
    )


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


__all__ = [
    "EXTERNAL_BLOCKERS",
    "FALSE_SAFETY",
    "FundingCashLedgerEvidence",
    "INSTRUMENT_ID",
    "MicroLiveApprovalProof",
    "MicroLiveRuntimeLimits",
    "SCHEMA_VERSION",
    "SupervisedMicroLiveAuthorization",
    "evaluate_supervised_micro_live_candidate",
]
