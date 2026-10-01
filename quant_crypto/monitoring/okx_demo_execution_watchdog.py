"""Independent, read-only supervision for the OKX Demo execution worker.

The watchdog deliberately has no exchange client and never renews cancel-all-after.
It validates the durable runtime chain, evaluates fail-closed invariants, and may
append a sanitized alert receipt to a watchdog-owned JSONL file.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.oms.runtime_store import BTCRuntimeStore


WATCHDOG_SCHEMA_VERSION = "btc_okx_demo_execution_watchdog_v1"
UNRESOLVED_ORDER_INTENT_STATUSES = frozenset(
    {"submit_pending", "unknown", "accepted", "reconciled_open"}
)


@dataclass(frozen=True)
class OkxDemoExecutionWatchdogConfig:
    runtime_root: Path
    alert_path: Path | None = None
    worker_heartbeat_stale_seconds: float = 90.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_root", Path(self.runtime_root).resolve())
        if self.alert_path is not None:
            object.__setattr__(self, "alert_path", Path(self.alert_path).resolve())
        if self.worker_heartbeat_stale_seconds <= 0:
            raise ValueError("okx_demo_watchdog_heartbeat_threshold_invalid")


def inspect_okx_demo_execution_runtime(
    config: OkxDemoExecutionWatchdogConfig,
    *,
    now: datetime | None = None,
    write_alert: bool = True,
) -> dict[str, Any]:
    observed_at = _ensure_utc(now or datetime.now(timezone.utc))
    recovery = BTCRuntimeStore(config.runtime_root).recover()
    report = evaluate_okx_demo_execution_state(
        recovery.state,
        observed_at_utc=observed_at,
        recovery_blockers=recovery.blockers,
        worker_heartbeat_stale_seconds=config.worker_heartbeat_stale_seconds,
    )
    alert_written = False
    if (
        write_alert
        and config.alert_path is not None
        and report["status"] in {"degraded", "critical"}
    ):
        alert_written = _append_alert_receipt(config.alert_path, report)
    report["alert_evidence"] = {
        "path": str(config.alert_path) if config.alert_path is not None else "",
        "written": alert_written,
        "runtime_state_modified": False,
        "ledger_modified": False,
    }
    return report


def evaluate_okx_demo_execution_state(
    state: Mapping[str, Any] | None,
    *,
    observed_at_utc: datetime,
    recovery_blockers: Sequence[str] = (),
    worker_heartbeat_stale_seconds: float = 90.0,
    reconcile_stale_seconds: float | None = None,
    detect_unknown_orders: bool = False,
) -> dict[str, Any]:
    observed_at = _ensure_utc(observed_at_utc)
    payload = dict(state or {})
    runtime = _mapping(payload.get("runtime"))
    risk = _mapping(payload.get("risk_control"))
    dead_man = _mapping(risk.get("dead_man"))
    exchange = _mapping(payload.get("exchange"))
    ledger = _mapping(payload.get("ledger_reconciliation"))
    private_ws = _mapping(payload.get("private_ws"))
    safety = _mapping(payload.get("safety"))
    alerts: list[dict[str, Any]] = []

    def add(code: str, severity: str, **details: Any) -> None:
        alerts.append(
            {
                "code": code,
                "severity": severity,
                "details": json.loads(json.dumps(details, default=str)),
            }
        )

    for blocker in recovery_blockers:
        add("okx_demo_watchdog_runtime_evidence_invalid", "critical", blocker=str(blocker))
    if not payload:
        add("okx_demo_watchdog_runtime_state_missing", "critical")

    active = runtime.get("active") is True
    risk_mode = str(risk.get("mode") or "FROZEN_UNKNOWN")
    signed_contracts = _signed_contracts(exchange.get("positions"))
    gross_contracts = _gross_contracts(exchange.get("positions"))
    position_shape_valid = (
        signed_contracts.is_finite() and gross_contracts.is_finite()
    )
    nonflat = not position_shape_valid or gross_contracts != 0
    heartbeat_age = _age_seconds(observed_at, runtime.get("last_heartbeat_utc"))
    reconciliation_age = _age_seconds(
        observed_at,
        runtime.get("last_reconciled_at_utc"),
    )
    dead_man_age = _age_seconds(observed_at, dead_man.get("last_ack_utc"))

    unsafe_flags = [
        name
        for name in (
            "live_order_allowed",
            "real_money_order_allowed",
            "transfer_allowed",
            "withdraw_allowed",
            "permission_upgrade_allowed",
        )
        if safety.get(name) is True
    ]
    if unsafe_flags:
        add(
            "okx_demo_watchdog_live_safety_flag_enabled",
            "critical",
            flags=unsafe_flags,
        )

    if not position_shape_valid:
        add("okx_demo_watchdog_position_shape_invalid", "critical")
    elif gross_contracts > abs(signed_contracts):
        add(
            "okx_demo_watchdog_hedged_position_detected",
            "critical",
            signed_contracts=str(signed_contracts),
            gross_contracts=str(gross_contracts),
        )

    if active:
        if heartbeat_age is None:
            add("okx_demo_watchdog_worker_heartbeat_missing", "critical")
        elif heartbeat_age > worker_heartbeat_stale_seconds:
            add(
                "okx_demo_watchdog_worker_heartbeat_stale",
                "critical",
                age_seconds=round(heartbeat_age, 3),
                limit_seconds=worker_heartbeat_stale_seconds,
            )
        if dead_man.get("armed") is not True:
            add("okx_demo_watchdog_dead_man_not_armed", "critical")
        timeout_seconds = _positive_float(dead_man.get("timeout_seconds"))
        if dead_man_age is None:
            add("okx_demo_watchdog_dead_man_ack_missing", "critical")
        elif timeout_seconds is None or dead_man_age > timeout_seconds:
            add(
                "okx_demo_watchdog_dead_man_ack_stale",
                "critical",
                age_seconds=round(dead_man_age, 3),
                timeout_seconds=timeout_seconds,
            )
        if (
            private_ws.get("connected") is not True
            or private_ws.get("listener_alive") is not True
        ):
            add("okx_demo_watchdog_private_ws_not_current", "critical")
        if (
            ledger.get("status") != "reconciled"
            or ledger.get("current_state_exchange_snapshot_match") is not True
        ):
            add("okx_demo_watchdog_ledger_not_reconciled", "critical")

    ambiguous_ids = sorted(
        str(client_order_id)
        for client_order_id, row in _mapping(
            risk.get("pending_order_intents")
        ).items()
        if isinstance(row, Mapping)
        and str(row.get("status") or "")
        in UNRESOLVED_ORDER_INTENT_STATUSES
    )
    if ambiguous_ids:
        add(
            "okx_demo_watchdog_ambiguous_order_intent",
            "critical",
            client_order_ids=ambiguous_ids,
        )

    if reconcile_stale_seconds is not None:
        if reconcile_stale_seconds <= 0:
            raise ValueError("okx_demo_watchdog_reconcile_threshold_invalid")
        if reconciliation_age is None:
            add("okx_demo_watchdog_reconciliation_missing", "critical")
        elif reconciliation_age > reconcile_stale_seconds:
            add(
                "okx_demo_watchdog_reconciliation_stale",
                "critical",
                age_seconds=round(reconciliation_age, 3),
                limit_seconds=reconcile_stale_seconds,
            )

    if detect_unknown_orders:
        owned_ids = {
            str(value)
            for value in risk.get("owned_client_order_ids") or []
            if str(value)
        }
        owned_ids.update(str(value) for value in _mapping(
            risk.get("pending_order_intents")
        ))
        unknown_ids = sorted(
            client_order_id
            for row in _sequence_of_mappings(exchange.get("pending_orders"))
            if (
                client_order_id := str(
                    row.get("client_order_id") or row.get("clOrdId") or ""
                )
            )
            and client_order_id not in owned_ids
        )
        if unknown_ids:
            add(
                "okx_demo_watchdog_unknown_exchange_order",
                "critical",
                client_order_ids=unknown_ids,
            )

    protection = _mapping(risk.get("active_protection"))
    expected_position_side = (
        "long"
        if position_shape_valid
        and gross_contracts == abs(signed_contracts)
        and signed_contracts > 0
        else "short"
        if position_shape_valid
        and gross_contracts == abs(signed_contracts)
        and signed_contracts < 0
        else ""
    )
    protection_verified = _protection_is_current(
        protection,
        exchange.get("pending_algo_orders"),
        expected_position_side=expected_position_side,
        expected_contracts=gross_contracts,
    )
    if nonflat and not protection_verified:
        add(
            "okx_demo_watchdog_nonflat_without_exchange_protection",
            "critical",
            signed_contracts=str(signed_contracts),
        )
    if not active and nonflat:
        add(
            "okx_demo_watchdog_worker_inactive_with_open_position",
            "critical",
            signed_contracts=str(signed_contracts),
        )

    if risk_mode == "FROZEN_UNKNOWN":
        add(
            "okx_demo_watchdog_runtime_frozen_unknown",
            "critical" if nonflat or active else "high",
        )
    elif risk_mode == "RISK_REDUCING":
        add("okx_demo_watchdog_runtime_risk_reducing", "high")
    elif active and risk_mode != "RUNNING":
        add(
            "okx_demo_watchdog_runtime_mode_invalid",
            "critical",
            mode=risk_mode,
        )

    severities = {str(row["severity"]) for row in alerts}
    if "critical" in severities:
        status = "critical"
    elif alerts:
        status = "degraded"
    elif active:
        status = "healthy"
    else:
        status = "inactive_safe"

    fingerprint_payload = {
        "run_id": str(runtime.get("run_id") or ""),
        "status": status,
        "alerts": alerts,
        "signed_contracts": str(signed_contracts),
        "gross_contracts": str(gross_contracts),
    }
    return {
        "schema_version": WATCHDOG_SCHEMA_VERSION,
        "observed_at_utc": observed_at.isoformat(),
        "status": status,
        "run_id": str(runtime.get("run_id") or ""),
        "runtime_active": active,
        "risk_mode": risk_mode,
        "signed_contracts": str(signed_contracts),
        "gross_contracts": str(gross_contracts),
        "worker_heartbeat_age_seconds": (
            round(heartbeat_age, 3) if heartbeat_age is not None else None
        ),
        "dead_man_ack_age_seconds": (
            round(dead_man_age, 3) if dead_man_age is not None else None
        ),
        "reconciliation_age_seconds": (
            round(reconciliation_age, 3)
            if reconciliation_age is not None
            else None
        ),
        "exchange_protection_verified": protection_verified,
        "alerts": alerts,
        "alert_fingerprint": _sha256(fingerprint_payload),
        "capabilities": {
            "same_host_only": True,
            "process_isolation_only": True,
            "power_redundancy": False,
            "network_redundancy": False,
            "loads_credentials": False,
            "renews_dead_man": False,
            "calls_private_endpoint": False,
            "calls_order_endpoint": False,
            "calls_transfer_endpoint": False,
            "calls_withdraw_endpoint": False,
        },
    }


def _protection_is_current(
    active_protection: Mapping[str, Any],
    pending_algo_orders: Any,
    *,
    expected_position_side: str,
    expected_contracts: Decimal,
) -> bool:
    if active_protection.get("status") != "exchange_accepted":
        return False
    client_id = str(active_protection.get("algo_client_order_id") or "")
    if (
        not client_id
        or expected_position_side not in {"long", "short"}
        or str(active_protection.get("position_side") or "")
        != expected_position_side
        or str(active_protection.get("instrument_id") or "")
        != "BTC-USDT-SWAP"
        or _decimal(active_protection.get("contracts"))
        != expected_contracts
        or active_protection.get("market_exit") is not True
    ):
        return False
    for row in _sequence_of_mappings(pending_algo_orders):
        if str(row.get("algo_client_order_id") or "") != client_id:
            continue
        return (
            str(row.get("state") or "")
            in {"live", "effective", "partially_effective"}
            and str(row.get("take_profit_trigger") or "")
            == str(active_protection.get("tp_trigger_px") or "")
            and str(row.get("stop_loss_trigger") or "")
            == str(active_protection.get("sl_trigger_px") or "")
            and str(row.get("take_profit_trigger_type") or "") == "mark"
            and str(row.get("stop_loss_trigger_type") or "") == "mark"
            and str(row.get("position_side") or "")
            == expected_position_side
            and str(row.get("instrument_id") or "") == "BTC-USDT-SWAP"
            and _decimal(row.get("size")) == expected_contracts
            and str(row.get("take_profit_order_price") or "") == "-1"
            and str(row.get("stop_loss_order_price") or "") == "-1"
        )
    return False


def _append_alert_receipt(path: Path, report: Mapping[str, Any]) -> bool:
    fingerprint = str(report.get("alert_fingerprint") or "")
    if not fingerprint or _last_alert_fingerprint(path) == fingerprint:
        return False
    receipt = {
        "schema_version": "btc_okx_demo_execution_watchdog_alert_v1",
        "observed_at_utc": str(report.get("observed_at_utc") or ""),
        "run_id": str(report.get("run_id") or ""),
        "status": str(report.get("status") or "critical"),
        "alert_fingerprint": fingerprint,
        "alerts": list(report.get("alerts") or []),
        "capabilities": dict(_mapping(report.get("capabilities"))),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    with path.open("ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _last_alert_fingerprint(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_bytes().splitlines()
        if not lines:
            return ""
        payload = json.loads(lines[-1])
        return str(payload.get("alert_fingerprint") or "")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ""


def _signed_contracts(rows: Any) -> Decimal:
    result = Decimal("0")
    for row in _sequence_of_mappings(rows):
        quantity = _position_contracts(row)
        side = str(row.get("position_side") or "")
        if side == "long":
            result += quantity
        elif side == "short":
            result -= quantity
        elif quantity:
            return Decimal("NaN")
    return result


def _gross_contracts(rows: Any) -> Decimal:
    result = Decimal("0")
    for row in _sequence_of_mappings(rows):
        quantity = _position_contracts(row)
        side = str(row.get("position_side") or "")
        if quantity and side not in {"long", "short"}:
            return Decimal("NaN")
        result += quantity
    return result


def _position_contracts(row: Mapping[str, Any]) -> Decimal:
    if "contracts" not in row:
        return Decimal("NaN")
    raw = row.get("contracts")
    if raw is None or not str(raw).strip():
        return Decimal("NaN")
    try:
        quantity = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("NaN")
    if not quantity.is_finite():
        return Decimal("NaN")
    return abs(quantity)


def _age_seconds(now: datetime, raw: Any) -> float | None:
    parsed = _parse_utc(raw)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _parse_utc(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("okx_demo_watchdog_timestamp_must_be_timezone_aware")
    return value.astimezone(timezone.utc)


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("NaN")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
