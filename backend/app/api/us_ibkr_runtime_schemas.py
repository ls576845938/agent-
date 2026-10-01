"""Read-only response models for the US IBKR runtime operator API.

These models intentionally describe an operator read model rather than the
runtime, broker-truth, or reconciliation domain models owned by other agents.
Unknown fields are ignored so raw broker payloads (including account numbers)
cannot accidentally become part of the public response contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _ReadOnlyModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RuntimeBlocker(_ReadOnlyModel):
    code: str
    message: str
    severity: str = "critical"
    blocks_new_orders: bool = True


class RuntimeSafetyFlags(_ReadOnlyModel):
    """Safety flags are deliberately hard-coded false for this read-only API."""

    live_ready: bool = False
    broker_access_allowed: bool = False
    private_endpoint_allowed: bool = False
    order_endpoint_allowed: bool = False


class GatewayStatus(_ReadOnlyModel):
    status: str = "unavailable"
    data_available: bool = False
    connected: bool = False
    last_heartbeat_at: datetime | None = None
    heartbeat_age_seconds: float | None = None
    client_id: int | None = None
    paper_port: int | None = None
    connection_epoch: int | None = None
    reconnect_attempts: int = 0
    last_error: str | None = None


class AccountStatus(_ReadOnlyModel):
    status: str = "unavailable"
    data_available: bool = False
    verified: bool = False
    account_hash: str | None = None


class MarketDataStatus(_ReadOnlyModel):
    status: str = "unavailable"
    data_available: bool = False
    healthy: bool = False
    last_tick_at: datetime | None = None
    last_tick_age_seconds: float | None = None
    subscription_epoch: int | None = None
    sequence_gap: bool | None = None


class BrokerTruthStatus(_ReadOnlyModel):
    status: str = "unavailable"
    data_available: bool = False
    snapshot_at: datetime | None = None
    snapshot_age_seconds: float | None = None
    fresh: bool = False
    open_orders_count: int | None = None
    executions_count: int | None = None
    positions_count: int | None = None


class ReconciliationStatus(_ReadOnlyModel):
    status: str = "unavailable"
    data_available: bool = False
    last_run_at: datetime | None = None
    unknown_orders: int | None = None
    unknown_executions: int | None = None
    position_mismatches: int | None = None
    cash_mismatch: bool | None = None
    blockers: list[RuntimeBlocker] = Field(default_factory=list)


class OMSStatus(_ReadOnlyModel):
    status: str = "unavailable"
    data_available: bool = False
    trading_mode: str = "no_transport"
    reduce_only: bool = False
    new_orders_allowed: bool = False


class KillSwitchStatus(_ReadOnlyModel):
    status: str = "unknown"
    data_available: bool = False
    tripped: bool | None = None
    reason: str | None = None


class RecoveryStatus(_ReadOnlyModel):
    status: str = "unavailable"
    data_available: bool = False
    requires_operator_ack: bool = True
    operator_acknowledged: bool = False


class IBKRRuntimeStatusResponse(_ReadOnlyModel):
    """Complete read-only IBKR runtime view consumed by the operator UI."""

    status: str = "unavailable_fail_closed"
    data_available: bool = False
    data_unavailable_reason: str | None = "provider_unavailable"
    runtime_state: str = "offline"
    trading_mode: str = "no_transport"
    block_new_orders: bool = True
    read_only: bool = True
    gateway: GatewayStatus = Field(default_factory=GatewayStatus)
    account: AccountStatus = Field(default_factory=AccountStatus)
    market_data: MarketDataStatus = Field(default_factory=MarketDataStatus)
    broker_truth: BrokerTruthStatus = Field(default_factory=BrokerTruthStatus)
    reconciliation: ReconciliationStatus = Field(default_factory=ReconciliationStatus)
    oms: OMSStatus = Field(default_factory=OMSStatus)
    kill_switch: KillSwitchStatus = Field(default_factory=KillSwitchStatus)
    recovery: RecoveryStatus = Field(default_factory=RecoveryStatus)
    blockers: list[RuntimeBlocker] = Field(default_factory=list)
    safety: RuntimeSafetyFlags = Field(default_factory=RuntimeSafetyFlags)
    # Keep the gates visible at the top level as well as under ``safety`` so a
    # caller cannot mistake the operator read model for a permission grant.
    live_ready: bool = False
    broker_access_allowed: bool = False
    private_endpoint_allowed: bool = False
    order_endpoint_allowed: bool = False
    updated_at: datetime | None = None


class IncidentRecord(_ReadOnlyModel):
    incident_id: str
    type: str
    severity: str = "warning"
    status: str = "open"
    opened_at: datetime | None = None
    last_seen_at: datetime | None = None
    resolved_at: datetime | None = None
    acknowledged_at: datetime | None = None
    message: str = ""
    # Context is already redacted by the service; it is retained for safe
    # operator diagnostics without exposing raw broker/account payloads.
    context: dict[str, Any] = Field(default_factory=dict)


class IBKRIncidentsResponse(_ReadOnlyModel):
    status: str = "unavailable_fail_closed"
    data_available: bool = False
    data_unavailable_reason: str | None = "provider_unavailable"
    read_only: bool = True
    incidents: list[IncidentRecord] = Field(default_factory=list)
    blockers: list[RuntimeBlocker] = Field(default_factory=list)


__all__ = [
    "AccountStatus",
    "BrokerTruthStatus",
    "GatewayStatus",
    "IBKRIncidentsResponse",
    "IBKRRuntimeStatusResponse",
    "IncidentRecord",
    "KillSwitchStatus",
    "MarketDataStatus",
    "OMSStatus",
    "ReconciliationStatus",
    "RecoveryStatus",
    "RuntimeBlocker",
    "RuntimeSafetyFlags",
]
