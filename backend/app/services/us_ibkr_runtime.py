"""Read-only IBKR runtime status service.

The service deliberately depends on a small provider protocol instead of
importing the runtime supervisor, broker adapter, paper loop, or
reconciliation implementations owned by other agents.  This keeps the API
usable while those components are developed independently and prevents an
internal PaperTradingLoop ``healthy`` value from being presented as IBKR
health.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import re
from typing import Any, Protocol

from pydantic import BaseModel

from backend.app.api.us_ibkr_runtime_schemas import (
    AccountStatus,
    BrokerTruthStatus,
    GatewayStatus,
    IBKRIncidentsResponse,
    IBKRRuntimeStatusResponse,
    IncidentRecord,
    KillSwitchStatus,
    MarketDataStatus,
    OMSStatus,
    ReconciliationStatus,
    RecoveryStatus,
    RuntimeBlocker,
    RuntimeSafetyFlags,
)


LIVE_PORTS = frozenset({4001, 7496})
_SENSITIVE_KEY_PARTS = (
    "account_number",
    "accountnumber",
    "account_id",
    "accountid",
    "api_key",
    "apikey",
    "secret",
    "passphrase",
    "password",
    "access_token",
    "refresh_token",
)
_ACCOUNT_TOKEN_RE = re.compile(r"(?i)\b(?:DU|DF|U|F)\d{4,}\b")


class IBKRRuntimeStatusProvider(Protocol):
    """Minimal provider contract for an injected, read-only runtime snapshot."""

    def snapshot(self) -> Mapping[str, Any] | BaseModel | None: ...


class IBKRRuntimeProviderUnavailable(RuntimeError):
    """Raised by an optional provider when no trustworthy snapshot exists."""


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return dict(value.model_dump(mode="python"))
    if is_dataclass(value):
        return dict(asdict(value))
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError:
            dumped = model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            dumped = to_dict()
        except Exception:
            return {}
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _redact_string(value: Any) -> str:
    text = str(value)
    text = _ACCOUNT_TOKEN_RE.sub("[redacted-account]", text)
    lowered = text.lower()
    if any(part in lowered for part in ("api_key", "apikey", "passphrase", "secret", "access_token")):
        return "[redacted-sensitive-value]"
    return text


def _safe_context(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = key_text.lower().replace("-", "_")
            if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                continue
            result[key_text] = _safe_context(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_context(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _redact_string(value) if isinstance(value, str) else value
    return _redact_string(value)


def _as_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on", "pass", "passed", "healthy"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "fail", "failed", "unhealthy"}:
            return False
    return default


def _as_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_count(value: Any, default: int | None = None) -> int | None:
    """Return a count from either a canonical count or a broker list."""

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    return _as_int(value, default)


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _token(value: Any, default: str) -> str:
    if value is None:
        return default
    raw = getattr(value, "value", value)
    normalized = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or default


def _first(mapping: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _section(mapping: Mapping[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, Mapping):
            return dict(value)
        converted = _as_mapping(value)
        if converted:
            return converted
    return {}


def _normalise_blockers(raw: Any) -> list[RuntimeBlocker]:
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        raw_items: list[Any] = [raw]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        raw_items = list(raw)
    else:
        raw_items = [raw]

    blockers: list[RuntimeBlocker] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, Mapping):
            code = _token(_first(item, "code", "id", "type", default="RUNTIME_BLOCKED"), "RUNTIME_BLOCKED").upper()
            message = _redact_string(_first(item, "message", "reason", "detail", default=code))
            severity = _token(_first(item, "severity", default="critical"), "critical")
            blocks = _as_bool(_first(item, "blocks_new_orders", "block_new_orders"), default=True)
        else:
            message = _redact_string(item)
            code = _token(message, "RUNTIME_BLOCKED").upper()
            severity = "critical"
            blocks = True
        if code in seen:
            continue
        seen.add(code)
        blockers.append(
            RuntimeBlocker(
                code=code,
                message=message,
                severity=severity,
                blocks_new_orders=bool(blocks),
            )
        )
    return blockers


def _add_blocker(blockers: list[RuntimeBlocker], code: str, message: str, *, severity: str = "critical") -> None:
    if any(item.code == code for item in blockers):
        return
    blockers.append(
        RuntimeBlocker(
            code=code,
            message=message,
            severity=severity,
            blocks_new_orders=True,
        )
    )


def _provider_result(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    converted = _as_mapping(value)
    return converted or None


def _read_provider(provider: Any) -> tuple[dict[str, Any] | None, str | None]:
    if provider is None:
        return None, "provider_unavailable"
    if isinstance(provider, Mapping) or isinstance(provider, BaseModel) or is_dataclass(provider):
        payload = _provider_result(provider)
        return (payload, None) if payload else (None, "provider_empty")

    for name in ("snapshot", "read", "read_status", "get_status"):
        candidate = getattr(provider, name, None)
        if candidate is None:
            continue
        try:
            value = candidate() if callable(candidate) else candidate
        except IBKRRuntimeProviderUnavailable:
            return None, "provider_unavailable"
        except Exception:
            return None, "provider_error"
        payload = _provider_result(value)
        return (payload, None) if payload else (None, "provider_empty")

    if callable(provider):
        try:
            payload = _provider_result(provider())
        except Exception:
            return None, "provider_error"
        return (payload, None) if payload else (None, "provider_empty")
    return None, "provider_unavailable"


class IBKRRuntimeStatusService:
    """Normalize an injected runtime snapshot into a fail-closed read model."""

    def __init__(self, provider: IBKRRuntimeStatusProvider | Mapping[str, Any] | Any | None = None) -> None:
        self.provider = provider

    def status_model(self) -> IBKRRuntimeStatusResponse:
        payload, reason = _read_provider(self.provider)
        if payload is None:
            return self._unavailable_model(reason or "provider_unavailable")
        return self._normalise_status(payload)

    def status(self) -> dict[str, Any]:
        return self.status_model().model_dump(mode="json")

    def read(self) -> dict[str, Any]:
        """Compatibility alias for read-model consumers; it is still read-only."""

        return self.status()

    def reconciliation(self) -> dict[str, Any]:
        return self.status_model().reconciliation.model_dump(mode="json")

    def incidents(self) -> dict[str, Any]:
        payload, reason = _read_provider(self.provider)
        if payload is None:
            return self._unavailable_incidents(reason or "provider_unavailable").model_dump(mode="json")

        raw_incidents: Any = payload.get("incidents")
        if raw_incidents is None:
            for name in ("read_incidents", "get_incidents"):
                candidate = getattr(self.provider, name, None)
                if candidate is None:
                    continue
                try:
                    raw_incidents = candidate() if callable(candidate) else candidate
                except Exception:
                    raw_incidents = None
                break

        if raw_incidents is None:
            return self._unavailable_incidents("incidents_unavailable").model_dump(mode="json")

        if isinstance(raw_incidents, Mapping):
            raw_items = [raw_incidents]
        elif isinstance(raw_incidents, Sequence) and not isinstance(raw_incidents, (str, bytes, bytearray)):
            raw_items = list(raw_incidents)
        else:
            raw_items = []

        incidents: list[IncidentRecord] = []
        for index, item in enumerate(raw_items):
            row = _as_mapping(item)
            if not row:
                continue
            incident_type = _token(_first(row, "type", "incident_type", default="runtime_incident"), "runtime_incident")
            incident_id = _redact_string(
                _first(row, "incident_id", "id", default=f"{incident_type}-{index + 1}")
            )
            incidents.append(
                IncidentRecord(
                    incident_id=incident_id,
                    type=incident_type,
                    severity=_token(_first(row, "severity", default="warning"), "warning"),
                    status=_token(_first(row, "status", default="open"), "open"),
                    opened_at=_as_datetime(_first(row, "opened_at", "created_at")),
                    last_seen_at=_as_datetime(_first(row, "last_seen_at", "updated_at")),
                    resolved_at=_as_datetime(_first(row, "resolved_at")),
                    acknowledged_at=_as_datetime(_first(row, "acknowledged_at")),
                    message=_redact_string(_first(row, "message", "reason", default="")),
                    context=_safe_context(_first(row, "context", default={})),
                )
            )
        return IBKRIncidentsResponse(
            status="available",
            data_available=True,
            data_unavailable_reason=None,
            incidents=incidents,
            blockers=[],
        ).model_dump(mode="json")

    def _unavailable_model(self, reason: str) -> IBKRRuntimeStatusResponse:
        blocker = RuntimeBlocker(
            code="IBKR_RUNTIME_UNAVAILABLE",
            message="IBKR runtime status data is unavailable; new orders remain blocked.",
            severity="critical",
            blocks_new_orders=True,
        )
        return IBKRRuntimeStatusResponse(
            status="unavailable_fail_closed",
            data_available=False,
            data_unavailable_reason=reason,
            runtime_state="offline",
            trading_mode="no_transport",
            block_new_orders=True,
            gateway=GatewayStatus(status="unavailable", data_available=False, connected=False),
            account=AccountStatus(status="unavailable", data_available=False, verified=False),
            market_data=MarketDataStatus(status="unavailable", data_available=False, healthy=False),
            broker_truth=BrokerTruthStatus(status="unavailable", data_available=False, fresh=False),
            reconciliation=ReconciliationStatus(
                status="unavailable",
                data_available=False,
                blockers=[blocker],
            ),
            oms=OMSStatus(
                status="unavailable",
                data_available=False,
                trading_mode="no_transport",
                reduce_only=False,
                new_orders_allowed=False,
            ),
            kill_switch=KillSwitchStatus(status="unknown", data_available=False, tripped=None),
            recovery=RecoveryStatus(
                status="unavailable",
                data_available=False,
                requires_operator_ack=True,
                operator_acknowledged=False,
            ),
            blockers=[blocker],
            safety=RuntimeSafetyFlags(),
        )

    def _unavailable_incidents(self, reason: str) -> IBKRIncidentsResponse:
        blocker = RuntimeBlocker(
            code="IBKR_RUNTIME_UNAVAILABLE",
            message="IBKR incident data is unavailable; runtime health is not inferred from another loop.",
            severity="critical",
            blocks_new_orders=True,
        )
        return IBKRIncidentsResponse(
            status="unavailable_fail_closed",
            data_available=False,
            data_unavailable_reason=reason,
            incidents=[],
            blockers=[blocker],
        )

    def _normalise_status(self, payload: dict[str, Any]) -> IBKRRuntimeStatusResponse:
        root = dict(payload)
        runtime = _section(root, "runtime", "runtime_status")
        for key, value in runtime.items():
            root.setdefault(key, value)

        gateway_raw = _section(root, "gateway", "ibkr", "transport")
        account_raw = _section(root, "account")
        market_raw = _section(root, "market_data", "market")
        broker_raw = _section(root, "broker_truth", "broker")
        reconciliation_value = root.get("reconciliation")
        reconciliation_raw = (
            dict(reconciliation_value)
            if isinstance(reconciliation_value, Mapping)
            else _section(root, "reconciliation_status")
        )
        oms_raw = _section(root, "oms", "order_management")
        kill_raw = _section(root, "kill_switch", "kill")
        recovery_raw = _section(root, "recovery")

        data_available_value = _as_bool(root.get("data_available"), default=None)
        data_available = bool(payload) if data_available_value is None else bool(data_available_value)
        runtime_state = _token(_first(root, "runtime_state", "state"), "offline")
        known_states = {
            "offline",
            "connecting",
            "authenticating",
            "broker_syncing",
            "reconciling",
            "ready",
            "degraded",
            "reconnecting",
            "recovery_pending",
            "halted",
        }
        if runtime_state not in known_states:
            runtime_state = "unknown"

        connected = bool(
            _as_bool(
                _first(gateway_raw, "connected", "transport_connected", default=_first(root, "connected")),
                default=False,
            )
        )
        gateway_data_available = bool(
            _as_bool(
                _first(
                    gateway_raw,
                    "data_available",
                    default=(bool(gateway_raw) or "connected" in root),
                ),
                default=False,
            )
        )
        paper_port = _as_int(_first(gateway_raw, "paper_port", "port", default=_first(root, "paper_port")))
        blockers = _normalise_blockers(_first(root, "blockers", "blocking_reasons", default=[]))
        if paper_port in LIVE_PORTS:
            paper_port = None
            connected = False
            _add_blocker(
                blockers,
                "LIVE_ENDPOINT_NOT_ALLOWED",
                "Live IBKR port was rejected by the read-only paper runtime contract.",
            )

        gateway_status = "connected" if gateway_data_available and connected else (
            "disconnected" if gateway_data_available else "unavailable"
        )
        gateway = GatewayStatus(
            status=gateway_status,
            data_available=gateway_data_available,
            connected=connected,
            last_heartbeat_at=_as_datetime(_first(gateway_raw, "last_heartbeat_at", "heartbeat_at")),
            heartbeat_age_seconds=_as_float(_first(gateway_raw, "heartbeat_age_seconds", "heartbeat_age")),
            client_id=_as_int(_first(gateway_raw, "client_id", default=_first(root, "client_id"))),
            paper_port=paper_port,
            connection_epoch=_as_int(_first(gateway_raw, "connection_epoch", "epoch")),
            reconnect_attempts=_as_int(_first(gateway_raw, "reconnect_attempts", "reconnect_count"), 0) or 0,
            last_error=(
                _redact_string(_first(gateway_raw, "last_error", "error"))
                if _first(gateway_raw, "last_error", "error") is not None
                else None
            ),
        )

        account_verified = bool(
            _as_bool(
                _first(account_raw, "verified", "account_verified", default=_first(root, "account_verified")),
                default=False,
            )
        )
        account_data_available = bool(
            _as_bool(_first(account_raw, "data_available", default=bool(account_raw)), default=False)
        )
        account_hash_value = _first(account_raw, "account_hash", default=_first(root, "account_hash"))
        account_hash = _redact_string(account_hash_value) if account_hash_value not in (None, "") else None
        account = AccountStatus(
            status="verified" if account_data_available and account_verified else (
                "unverified" if account_data_available else "unavailable"
            ),
            data_available=account_data_available,
            verified=account_verified,
            account_hash=account_hash,
        )

        market_data_available = bool(
            _as_bool(_first(market_raw, "data_available", default=bool(market_raw)), default=False)
        )
        sequence_gap = _as_bool(_first(market_raw, "sequence_gap", "has_sequence_gap"), default=None)
        market_healthy = bool(_as_bool(_first(market_raw, "healthy"), default=False))
        if sequence_gap is True:
            market_healthy = False
        market_status = "healthy" if market_data_available and market_healthy else (
            "stale" if market_data_available else "unavailable"
        )
        market_data = MarketDataStatus(
            status=market_status,
            data_available=market_data_available,
            healthy=market_healthy,
            last_tick_at=_as_datetime(_first(market_raw, "last_tick_at", "tick_at")),
            last_tick_age_seconds=_as_float(_first(market_raw, "last_tick_age_seconds", "tick_age_seconds")),
            subscription_epoch=_as_int(_first(market_raw, "subscription_epoch", "epoch")),
            sequence_gap=sequence_gap,
        )

        broker_data_available = bool(
            _as_bool(_first(broker_raw, "data_available", default=bool(broker_raw)), default=False)
        )
        broker_fresh = bool(_as_bool(_first(broker_raw, "fresh"), default=False))
        broker_truth = BrokerTruthStatus(
            status="fresh" if broker_data_available and broker_fresh else (
                "stale" if broker_data_available else "unavailable"
            ),
            data_available=broker_data_available,
            snapshot_at=_as_datetime(_first(broker_raw, "snapshot_at", "captured_at")),
            snapshot_age_seconds=_as_float(_first(broker_raw, "snapshot_age_seconds", "age_seconds")),
            fresh=broker_fresh,
            open_orders_count=_as_count(_first(broker_raw, "open_orders_count", "open_orders")),
            executions_count=_as_count(_first(broker_raw, "executions_count", "executions")),
            positions_count=_as_count(_first(broker_raw, "positions_count", "positions")),
        )

        reconciliation_status = _token(
            _first(
                reconciliation_raw,
                "status",
                "reconciliation_status",
                default=_first(root, "reconciliation_status"),
            ),
            "unavailable",
        )
        if reconciliation_status in {"passed", "success", "ok"}:
            reconciliation_status = "pass"
        elif reconciliation_status in {"failed", "error"}:
            reconciliation_status = "fail"
        if reconciliation_status not in {"pass", "fail", "stale", "incomplete", "unknown", "unavailable"}:
            reconciliation_status = "unknown"
        reconciliation_data_available = bool(
            _as_bool(
                _first(
                    reconciliation_raw,
                    "data_available",
                    default=bool(reconciliation_raw) and reconciliation_status != "unavailable",
                ),
                default=False,
            )
        )
        reconciliation_blockers = _normalise_blockers(reconciliation_raw.get("blockers", []))
        reconciliation = ReconciliationStatus(
            status=reconciliation_status,
            data_available=reconciliation_data_available,
            last_run_at=_as_datetime(_first(reconciliation_raw, "last_run_at", "completed_at")),
            unknown_orders=_as_int(_first(reconciliation_raw, "unknown_orders", "unknown_broker_orders")),
            unknown_executions=_as_int(_first(reconciliation_raw, "unknown_executions")),
            position_mismatches=_as_int(_first(reconciliation_raw, "position_mismatches", "position_mismatch_count")),
            cash_mismatch=_as_bool(_first(reconciliation_raw, "cash_mismatch"), default=None),
            blockers=reconciliation_blockers,
        )

        explicit_mode = _first(oms_raw, "trading_mode", default=_first(root, "trading_mode", "mode"))
        trading_mode = _token(explicit_mode, "")
        if not trading_mode:
            trading_mode = "no_transport" if not connected else "frozen"
        if not connected and trading_mode == "normal":
            trading_mode = "no_transport"
        if trading_mode not in {"normal", "reduce_only", "cancel_only", "frozen", "no_transport"}:
            trading_mode = "frozen"

        kill_tripped = _as_bool(
            _first(kill_raw, "tripped", "kill_switch_tripped", default=_first(root, "kill_switch_tripped")),
            default=None,
        )
        kill_switch = KillSwitchStatus(
            status=("tripped" if kill_tripped is True else "armed" if kill_tripped is False else "unknown"),
            data_available=bool(kill_raw),
            tripped=kill_tripped,
            reason=(
                _redact_string(_first(kill_raw, "reason"))
                if _first(kill_raw, "reason") is not None
                else None
            ),
        )

        recovery_requires_ack_value = _as_bool(
            _first(recovery_raw, "requires_operator_ack", "recovery_requires_ack", default=_first(root, "recovery_requires_ack")),
            default=(runtime_state == "recovery_pending" or not data_available),
        )
        operator_acknowledged = bool(
            _as_bool(
                _first(
                    recovery_raw,
                    "operator_acknowledged",
                    "acknowledged",
                    default=_first(root, "operator_acknowledged"),
                ),
                default=False,
            )
        )
        recovery_data_available = bool(
            _as_bool(_first(recovery_raw, "data_available", default=bool(recovery_raw)), default=False)
        )
        recovery_status = (
            "pending_ack"
            if recovery_requires_ack_value and not operator_acknowledged
            else "acknowledged"
            if recovery_requires_ack_value
            else "not_required"
            if recovery_data_available or runtime_state == "ready"
            else "unavailable"
        )
        recovery = RecoveryStatus(
            status=recovery_status,
            data_available=recovery_data_available,
            requires_operator_ack=bool(recovery_requires_ack_value),
            operator_acknowledged=operator_acknowledged,
        )

        if runtime_state == "offline":
            _add_blocker(blockers, "RUNTIME_OFFLINE", "IBKR runtime is offline; no transport is available.")
        elif runtime_state == "unknown":
            _add_blocker(blockers, "RUNTIME_STATE_UNKNOWN", "IBKR runtime state is unknown; fail-closed.")
        if not gateway_data_available:
            _add_blocker(blockers, "GATEWAY_STATUS_UNAVAILABLE", "IBKR Gateway status data is unavailable.")
        elif not connected:
            _add_blocker(blockers, "GATEWAY_DISCONNECTED", "IBKR Gateway transport is disconnected.")
        if not account_data_available:
            _add_blocker(blockers, "ACCOUNT_STATUS_UNAVAILABLE", "IBKR account verification data is unavailable.")
        elif not account_verified:
            _add_blocker(blockers, "ACCOUNT_UNVERIFIED", "IBKR account identity is not verified.")
        if not market_data_available:
            _add_blocker(blockers, "MARKET_DATA_UNAVAILABLE", "IBKR market-data status is unavailable.")
        elif not market_healthy:
            _add_blocker(blockers, "MARKET_DATA_NOT_HEALTHY", "IBKR market data is stale or unhealthy.")
        if not broker_data_available:
            _add_blocker(blockers, "BROKER_TRUTH_UNAVAILABLE", "Broker truth snapshot is unavailable.")
        elif not broker_fresh:
            _add_blocker(blockers, "BROKER_TRUTH_STALE", "Broker truth snapshot is stale.")
        if reconciliation_status != "pass":
            _add_blocker(
                blockers,
                "RECONCILIATION_NOT_PASS",
                f"Broker reconciliation status is {reconciliation_status}; new orders remain blocked.",
            )
        if recovery.requires_operator_ack and not recovery.operator_acknowledged:
            _add_blocker(blockers, "OPERATOR_ACK_REQUIRED", "Recovery requires explicit operator acknowledgement.")
        if kill_tripped is True:
            _add_blocker(blockers, "KILL_SWITCH_TRIPPED", "Kill switch is tripped.")

        explicit_block = _as_bool(root.get("block_new_orders"), default=None)
        safe_to_submit = (
            runtime_state == "ready"
            and trading_mode == "normal"
            and connected
            and account_verified
            and market_data.healthy
            and broker_truth.fresh
            and reconciliation.status == "pass"
            and kill_tripped is False
            and not recovery.requires_operator_ack
            and not any(item.blocks_new_orders for item in blockers)
        )
        block_new_orders = True if not safe_to_submit else bool(explicit_block)
        if block_new_orders and not any(item.code == "NEW_ORDERS_BLOCKED" for item in blockers):
            _add_blocker(blockers, "NEW_ORDERS_BLOCKED", "Runtime safety conditions do not permit new orders.")

        oms_status = "available" if bool(oms_raw) else "derived_fail_closed"
        oms = OMSStatus(
            status=oms_status,
            data_available=bool(oms_raw),
            trading_mode=trading_mode,
            reduce_only=trading_mode == "reduce_only",
            new_orders_allowed=not block_new_orders,
        )
        overall_status = (
            "unavailable_fail_closed"
            if not data_available
            else "unknown_fail_closed"
            if runtime_state == "unknown"
            else "offline"
            if runtime_state == "offline"
            else "available"
        )
        reason = (
            "provider_marked_unavailable"
            if not data_available
            else "ibkr_runtime_offline"
            if runtime_state == "offline"
            else None
        )
        return IBKRRuntimeStatusResponse(
            status=overall_status,
            data_available=data_available,
            data_unavailable_reason=reason,
            runtime_state=runtime_state,
            trading_mode=trading_mode,
            block_new_orders=block_new_orders,
            gateway=gateway,
            account=account,
            market_data=market_data,
            broker_truth=broker_truth,
            reconciliation=reconciliation,
            oms=oms,
            kill_switch=kill_switch,
            recovery=recovery,
            blockers=blockers,
            safety=RuntimeSafetyFlags(),
            live_ready=False,
            broker_access_allowed=False,
            private_endpoint_allowed=False,
            order_endpoint_allowed=False,
            updated_at=_as_datetime(_first(root, "updated_at", "captured_at")),
        )


USIBKRRuntimeStatusService = IBKRRuntimeStatusService
IBKRRuntimeReadModelService = IBKRRuntimeStatusService
USIBKRRuntimeService = IBKRRuntimeStatusService
IBKRRuntimeProvider = IBKRRuntimeStatusProvider


__all__ = [
    "IBKRRuntimeProviderUnavailable",
    "IBKRRuntimeReadModelService",
    "IBKRRuntimeStatusProvider",
    "IBKRRuntimeStatusService",
    "IBKRRuntimeProvider",
    "USIBKRRuntimeService",
    "USIBKRRuntimeStatusService",
]
