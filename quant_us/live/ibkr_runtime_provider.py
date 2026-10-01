"""Paper-only runtime provider and registry used by the read-only API.

The registry is deliberately inert until ``PaperRuntime`` explicitly enables
the control plane.  API readers consume the supervisor's last observations;
they never connect, poll, submit, cancel, or discover credentials.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from quant_us.monitoring.runtime_incidents import RuntimeIncidentManager


LIVE_PORTS = frozenset({4001, 7496})


def _read(value: Any, *names: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        for name in names:
            if name in value and value[name] is not None:
                return value[name]
        return default
    for name in names:
        try:
            candidate = getattr(value, name)
        except Exception:
            continue
        if candidate is not None:
            return candidate
    return default


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    for name in ("to_dict", "model_dump"):
        method = getattr(value, name, None)
        if callable(method):
            try:
                payload = method(mode="python") if name == "model_dump" else method()
            except TypeError:
                payload = method()
            except Exception:
                return {}
            return dict(payload) if isinstance(payload, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _enum_text(value: Any, default: str = "") -> str:
    raw = getattr(value, "value", value)
    text = str(raw or default).strip().lower().replace("-", "_").replace(" ", "_")
    return text or default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "pass", "passed", "ok"}


class RuntimeIncidentSink:
    """Adapt supervisor incident events to the append-only incident manager."""

    def __init__(self, manager: RuntimeIncidentManager) -> None:
        self.manager = manager

    def emit(self, event: Mapping[str, Any] | Any) -> Any:
        row = _mapping(event)
        incident_type = str(row.get("type") or row.get("incident_type") or row.get("event") or "RUNTIME_HALTED")
        context = row.get("context") if isinstance(row.get("context"), Mapping) else {}
        return self.manager.open(
            incident_type=incident_type,
            source=str(row.get("source") or "ibkr_runtime_supervisor"),
            message=str(row.get("message") or row.get("reason") or incident_type),
            context=dict(context),
            identity_key=str(row.get("identity_key") or row.get("reason") or incident_type),
        )

    record = emit


class IBKRRuntimeProviderRegistry:
    """Single-writer registry for the optional PaperRuntime provider."""

    def __init__(self) -> None:
        self._provider: IBKRRuntimeProvider | None = None

    def register(self, provider: "IBKRRuntimeProvider") -> None:
        if not isinstance(provider, IBKRRuntimeProvider):
            raise TypeError("ibkr_runtime_provider_required")
        self._provider = provider

    def clear(self, provider: "IBKRRuntimeProvider | None" = None) -> None:
        if provider is None or provider is self._provider:
            self._provider = None

    @property
    def provider(self) -> "IBKRRuntimeProvider | None":
        return self._provider

    def snapshot(self) -> Mapping[str, Any] | None:
        provider = self._provider
        return None if provider is None else provider.snapshot()

    def read_incidents(self) -> list[Mapping[str, Any]] | None:
        provider = self._provider
        return None if provider is None else provider.read_incidents()


_REGISTRY = IBKRRuntimeProviderRegistry()


def get_ibkr_runtime_provider_registry() -> IBKRRuntimeProviderRegistry:
    return _REGISTRY


class IBKRRuntimeProvider:
    """Project canonical supervisor observations into the backend read model."""

    def __init__(
        self,
        supervisor: Any,
        *,
        broker: Any,
        incident_store: Any | None = None,
        market_data: Any | None = None,
        oms: Any | None = None,
        kill_switch: Any | None = None,
    ) -> None:
        self.supervisor = supervisor
        self.broker = broker
        self.incident_store = incident_store
        self.market_data = market_data
        self.oms = oms
        self.kill_switch = kill_switch

    def _runtime_snapshot(self) -> Any:
        value = _read(self.supervisor, "snapshot", "runtime_snapshot", default=None)
        if callable(value):
            try:
                value = value()
            except Exception:
                return None
        return value

    def _truth_snapshot(self) -> Any:
        # Only consume cached observations.  Calling an adapter truth method
        # here could perform broker I/O from an API request.
        value = _read(self.supervisor, "_last_truth_snapshot", default=None)
        if value is not None:
            return value
        return _read(self.broker, "last_broker_truth", "broker_truth_snapshot", default=None)

    def snapshot(self) -> Mapping[str, Any]:
        runtime = _mapping(self._runtime_snapshot())
        truth = _mapping(self._truth_snapshot())
        broker_config = _read(self.broker, "config", default=None)
        port = _read(broker_config, "port", default=_read(self.broker, "port", default=None))
        connected = _as_bool(runtime.get("connected"), default=False)
        account_verified = _as_bool(runtime.get("account_verified"), default=False)
        state = _enum_text(runtime.get("state") or runtime.get("runtime_state"), "offline")
        truth_fresh = _as_bool(runtime.get("broker_truth_fresh"), default=False)
        blockers = [str(item) for item in (runtime.get("blockers") or []) if str(item)]
        if not truth:
            blockers.append("broker_truth_unavailable")
        if port in LIVE_PORTS:
            connected = False
            blockers.append("LIVE_ENDPOINT_NOT_ALLOWED")
        blockers = list(dict.fromkeys(blockers))

        reconciliation = _mapping(_read(self.supervisor, "_last_reconciliation_result", default=None))
        recon_status = _enum_text(
            reconciliation.get("status") or reconciliation.get("reconciliation_status")
            or runtime.get("reconciliation_status"),
            "unavailable",
        )
        if recon_status in {"passed", "clean", "ok", "success"}:
            recon_status = "pass"
        elif recon_status in {"failed", "error"}:
            recon_status = "fail"
        recon_blockers = [str(item) for item in (reconciliation.get("blockers") or []) if str(item)]

        permissions = {}
        try:
            permissions = getattr(self.supervisor, "permissions", {}) or {}
        except Exception:
            permissions = {}
        new_order = permissions.get("submit_new_order")
        new_orders_allowed = bool(new_order) if new_order is not None else False

        market = _mapping(self.market_data)
        kill = self.kill_switch or _read(self.supervisor, "kill_switch", default=None)
        kill_tripped = _read(kill, "triggered", "tripped", "kill_switch_tripped", default=runtime.get("kill_switch_tripped"))

        return {
            "status": "available",
            "data_available": True,
            "data_unavailable_reason": None,
            "runtime_state": state,
            "trading_mode": _enum_text(runtime.get("trading_mode"), "no_transport"),
            "block_new_orders": bool(runtime.get("block_new_orders", True)) or not new_orders_allowed,
            "read_only": True,
            "gateway": {
                "status": "connected" if connected else "disconnected",
                "data_available": True,
                "connected": connected,
                "client_id": _read(broker_config, "client_id", default=_read(self.broker, "client_id", default=None)),
                "paper_port": None if port in LIVE_PORTS else port,
                "connection_epoch": runtime.get("connection_epoch"),
                "reconnect_attempts": runtime.get("reconnect_attempts", 0),
            },
            "account": {
                "status": "verified" if account_verified else "unverified",
                "data_available": True,
                "verified": account_verified,
                "account_hash": truth.get("account_hash"),
            },
            "market_data": {
                "status": "healthy" if _as_bool(market.get("healthy"), default=False) else "unavailable",
                "data_available": bool(market),
                "healthy": _as_bool(market.get("healthy"), default=False),
                "last_tick_at": market.get("last_tick_at"),
                "last_tick_age_seconds": market.get("last_tick_age_seconds"),
                "sequence_gap": market.get("sequence_gap"),
            },
            "broker_truth": {
                "status": "fresh" if truth_fresh else "stale" if truth else "unavailable",
                "data_available": bool(truth),
                "snapshot_at": truth.get("captured_at"),
                "fresh": truth_fresh,
                "open_orders_count": len(truth.get("open_orders", ()) or ()) if truth else None,
                "executions_count": len(truth.get("executions", ()) or ()) if truth else None,
                "positions_count": len(truth.get("positions", ()) or ()) if truth else None,
            },
            "reconciliation": {
                "status": recon_status,
                "data_available": bool(reconciliation),
                "blockers": recon_blockers,
            },
            "oms": {
                "status": "available",
                "data_available": True,
                "trading_mode": _enum_text(runtime.get("trading_mode"), "no_transport"),
                "reduce_only": bool(_read(self.oms, "reduce_only", default=False)),
                "new_orders_allowed": new_orders_allowed,
            },
            "kill_switch": {
                "status": "tripped" if kill_tripped is True else "armed" if kill_tripped is False else "unknown",
                "data_available": kill_tripped is not None,
                "tripped": kill_tripped,
                "reason": _read(kill, "reason", default=None),
            },
            "recovery": {
                "status": "pending_ack" if state == "recovery_pending" else "not_required" if state == "ready" else "unavailable",
                "data_available": state in {"ready", "recovery_pending"},
                "requires_operator_ack": bool(runtime.get("recovery_requires_ack", state == "recovery_pending")),
                "operator_acknowledged": bool(runtime.get("operator_acknowledged", False)),
            },
            "blockers": list(dict.fromkeys([*blockers, *recon_blockers])),
            "safety": {
                "live_ready": False,
                "broker_access_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
            "live_ready": False,
            "broker_access_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "updated_at": runtime.get("last_transition_at"),
        }

    def read_incidents(self) -> list[Mapping[str, Any]]:
        store = self.incident_store
        if store is None:
            return []
        candidate = getattr(store, "list", None) or getattr(store, "list_incidents", None)
        if not callable(candidate):
            return []
        try:
            values = candidate(include_resolved=True)
        except TypeError:
            values = candidate()
        return [_mapping(item) for item in (values or ())]


__all__ = [
    "IBKRRuntimeProvider",
    "IBKRRuntimeProviderRegistry",
    "RuntimeIncidentSink",
    "get_ibkr_runtime_provider_registry",
]
