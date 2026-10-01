"""Deployable, read-only supervision for an OKX Demo worker on another host."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from quant_crypto.application.btc_okx_demo_fault_drill import (
    OKX_DOCS_REVIEW_METADATA,
)
from quant_crypto.monitoring.okx_demo_execution_watchdog import (
    evaluate_okx_demo_execution_state,
)
from quant_crypto.oms.okx_demo import OkxDemoResponse


REMOTE_SUPERVISOR_SCHEMA_VERSION = "btc_okx_demo_remote_supervisor_receipt_v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9._-]{1,96}")
_READ_PATHS = (
    "/api/v5/account/config",
    "/api/v5/account/balance",
    "/api/v5/account/positions",
    "/api/v5/trade/orders-pending",
    "/api/v5/trade/orders-algo-pending",
)


class OkxDemoRemoteSupervisorError(RuntimeError):
    pass


class OkxDemoExchangeReader(Protocol):
    def private_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> OkxDemoResponse: ...


@dataclass(frozen=True)
class OkxDemoRemoteSupervisorConfig:
    deployment_id: str
    expected_worker_id: str
    heartbeat_url: str
    heartbeat_allowlist: tuple[str, ...]
    receipt_external_root: Path
    supervisor_host_id: str = ""
    worker_heartbeat_stale_seconds: float = 90.0
    reconcile_stale_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.deployment_id):
            raise OkxDemoRemoteSupervisorError(
                "okx_demo_remote_supervisor_deployment_id_invalid"
            )
        if not _IDENTIFIER.fullmatch(self.expected_worker_id):
            raise OkxDemoRemoteSupervisorError(
                "okx_demo_remote_supervisor_expected_worker_id_invalid"
            )
        parsed = urllib.parse.urlsplit(self.heartbeat_url)
        if parsed.scheme != "https":
            raise OkxDemoRemoteSupervisorError(
                "okx_demo_remote_supervisor_heartbeat_https_required"
            )
        if parsed.username or parsed.password or not parsed.hostname:
            raise OkxDemoRemoteSupervisorError(
                "okx_demo_remote_supervisor_heartbeat_url_invalid"
            )
        allowlist = tuple(
            sorted({str(host).strip().lower() for host in self.heartbeat_allowlist if str(host).strip()})
        )
        if parsed.hostname.lower() not in allowlist:
            raise OkxDemoRemoteSupervisorError(
                "okx_demo_remote_supervisor_heartbeat_host_not_allowlisted"
            )
        if self.worker_heartbeat_stale_seconds <= 0 or self.reconcile_stale_seconds <= 0:
            raise OkxDemoRemoteSupervisorError(
                "okx_demo_remote_supervisor_stale_threshold_invalid"
            )
        requested_receipt_root = Path(self.receipt_external_root)
        if not requested_receipt_root.is_absolute():
            raise OkxDemoRemoteSupervisorError(
                "okx_demo_remote_supervisor_receipt_root_must_be_absolute"
            )
        receipt_root = requested_receipt_root.resolve()
        object.__setattr__(self, "heartbeat_allowlist", allowlist)
        object.__setattr__(self, "receipt_external_root", receipt_root)


class OkxDemoRemoteSupervisor:
    def __init__(
        self,
        config: OkxDemoRemoteSupervisorConfig,
        *,
        exchange_reader: OkxDemoExchangeReader,
        heartbeat_fetcher: Callable[[str], Mapping[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._exchange_reader = exchange_reader
        self._heartbeat_fetcher = heartbeat_fetcher or _fetch_heartbeat
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run_once(self) -> dict[str, Any]:
        observed_at = _ensure_utc(self._clock())
        alerts: list[dict[str, Any]] = []
        try:
            heartbeat = _mapping(
                self._heartbeat_fetcher(self.config.heartbeat_url)
            )
        except Exception as exc:
            heartbeat = {}
            alerts.append(
                _alert(
                    "okx_demo_remote_supervisor_heartbeat_fetch_failed",
                    "critical",
                    error=_safe_error(exc),
                )
            )

        worker_id = str(heartbeat.get("worker_id") or "")
        worker_host_id = str(heartbeat.get("worker_host_id") or "")
        if worker_id != self.config.expected_worker_id:
            alerts.append(
                _alert(
                    "okx_demo_remote_supervisor_worker_identity_mismatch",
                    "critical",
                    expected_worker_id=self.config.expected_worker_id,
                    observed_worker_id=worker_id,
                )
            )

        independent_host_verified = bool(
            self.config.supervisor_host_id
            and worker_host_id
            and self.config.supervisor_host_id != worker_host_id
        )
        if not independent_host_verified:
            alerts.append(
                _alert(
                    "okx_demo_remote_supervisor_same_host_not_independent",
                    "high",
                    supervisor_host_id=self.config.supervisor_host_id,
                    worker_host_id=worker_host_id,
                )
            )

        rows: dict[str, list[Mapping[str, Any]]] = {}
        for path in _READ_PATHS:
            try:
                response = self._exchange_reader.private_get(
                    path,
                    _query_for(path),
                )
                if response.method != "GET" or not response.ok:
                    raise OkxDemoRemoteSupervisorError(
                        f"read_failed:{path}:{response.code}"
                    )
                rows[path] = [row for row in response.data if isinstance(row, Mapping)]
            except Exception as exc:
                rows[path] = []
                alerts.append(
                    _alert(
                        "okx_demo_remote_supervisor_exchange_read_failed",
                        "critical",
                        path=path,
                        error=_safe_error(exc),
                    )
                )

        state = _watchdog_state(heartbeat, rows)
        watchdog = evaluate_okx_demo_execution_state(
            state,
            observed_at_utc=observed_at,
            worker_heartbeat_stale_seconds=(
                self.config.worker_heartbeat_stale_seconds
            ),
            reconcile_stale_seconds=self.config.reconcile_stale_seconds,
            detect_unknown_orders=True,
        )
        alerts.extend(list(watchdog.get("alerts") or []))
        for row in list(watchdog.get("alerts") or []):
            if row.get("code") == "okx_demo_watchdog_reconciliation_stale":
                alerts.append(
                    _alert(
                        "okx_demo_remote_supervisor_reconcile_stale",
                        "critical",
                        **dict(_mapping(row.get("details"))),
                    )
                )
            if row.get("code") == "okx_demo_watchdog_unknown_exchange_order":
                alerts.append(
                    _alert(
                        "okx_demo_remote_supervisor_unknown_order",
                        "critical",
                        **dict(_mapping(row.get("details"))),
                    )
                )

        alerts = _dedupe_alerts(alerts)
        status = (
            "critical"
            if any(row.get("severity") == "critical" for row in alerts)
            else "degraded"
            if alerts
            else "healthy"
        )
        receipt = {
            "schema_version": REMOTE_SUPERVISOR_SCHEMA_VERSION,
            "observed_at_utc": observed_at.isoformat(),
            "deployment_id": self.config.deployment_id,
            "expected_worker_id": self.config.expected_worker_id,
            "observed_worker_id": worker_id,
            "source_head": str(heartbeat.get("source_head") or ""),
            "status": status,
            "alerts": alerts,
            "worker": {
                "worker_host_id": worker_host_id,
                "run_id": str(_mapping(heartbeat.get("runtime")).get("run_id") or ""),
            },
            "exchange": _public_exchange_summary(rows),
            "watchdog": {
                key: watchdog.get(key)
                for key in (
                    "worker_heartbeat_age_seconds",
                    "reconciliation_age_seconds",
                    "signed_contracts",
                    "gross_contracts",
                    "exchange_protection_verified",
                )
            },
            "official_semantics": dict(OKX_DOCS_REVIEW_METADATA),
            "capabilities": {
                "independent_host_verified": independent_host_verified,
                "same_host_does_not_count": True,
                "heartbeat_https": True,
                "heartbeat_host_allowlisted": True,
                "exchange_methods": ["GET"],
                "order_method_registered": False,
                "cancel_method_registered": False,
                "post_method_registered": False,
                "transfer_method_registered": False,
                "withdraw_method_registered": False,
            },
            "credentials_redacted": True,
            "promotion_eligible": False,
            "paper_promotion_allowed": False,
            "live_allowed": False,
        }
        path = _append_receipt(self.config, receipt)
        return {**receipt, "receipt_path": str(path)}


def _watchdog_state(
    heartbeat: Mapping[str, Any],
    rows: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    risk = dict(_mapping(heartbeat.get("risk_control")))
    risk["owned_client_order_ids"] = list(
        risk.get("owned_client_order_ids") or []
    )
    return {
        "runtime": dict(_mapping(heartbeat.get("runtime"))),
        "risk_control": risk,
        "private_ws": dict(_mapping(heartbeat.get("private_ws"))),
        "ledger_reconciliation": dict(
            _mapping(heartbeat.get("ledger_reconciliation"))
        ),
        "safety": dict(_mapping(heartbeat.get("safety"))),
        "exchange": {
            "positions": [
                {
                    "instrument_id": str(row.get("instId") or ""),
                    "position_side": str(row.get("posSide") or ""),
                    "contracts": str(row.get("pos") or "0"),
                }
                for row in rows.get("/api/v5/account/positions", [])
                if str(row.get("instId") or "") == "BTC-USDT-SWAP"
            ],
            "pending_orders": [
                {
                    "client_order_id": str(row.get("clOrdId") or ""),
                    "state": str(row.get("state") or ""),
                }
                for row in rows.get("/api/v5/trade/orders-pending", [])
                if str(row.get("instId") or "BTC-USDT-SWAP")
                == "BTC-USDT-SWAP"
            ],
            "pending_algo_orders": [
                {
                    "algo_client_order_id": str(row.get("algoClOrdId") or ""),
                    "instrument_id": str(row.get("instId") or ""),
                    "position_side": str(row.get("posSide") or ""),
                    "size": str(row.get("sz") or "0"),
                    "state": str(row.get("state") or ""),
                    "take_profit_trigger": str(row.get("tpTriggerPx") or ""),
                    "take_profit_trigger_type": str(row.get("tpTriggerPxType") or ""),
                    "take_profit_order_price": str(row.get("tpOrdPx") or ""),
                    "stop_loss_trigger": str(row.get("slTriggerPx") or ""),
                    "stop_loss_trigger_type": str(row.get("slTriggerPxType") or ""),
                    "stop_loss_order_price": str(row.get("slOrdPx") or ""),
                }
                for row in rows.get("/api/v5/trade/orders-algo-pending", [])
                if str(row.get("instId") or "BTC-USDT-SWAP")
                == "BTC-USDT-SWAP"
            ],
        },
    }


def _public_exchange_summary(
    rows: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    return {
        "account_rows": len(rows.get("/api/v5/account/config", [])),
        "balance_rows": len(rows.get("/api/v5/account/balance", [])),
        "positions": [
            {
                "instrument_id": str(row.get("instId") or ""),
                "position_side": str(row.get("posSide") or ""),
                "contracts": str(row.get("pos") or "0"),
            }
            for row in rows.get("/api/v5/account/positions", [])
        ],
        "pending_orders": [
            {
                "clOrdId": str(row.get("clOrdId") or ""),
                "state": str(row.get("state") or ""),
            }
            for row in rows.get("/api/v5/trade/orders-pending", [])
        ],
        "pending_protection": [
            {
                "algoClOrdId": str(row.get("algoClOrdId") or ""),
                "state": str(row.get("state") or ""),
            }
            for row in rows.get("/api/v5/trade/orders-algo-pending", [])
        ],
    }


def _fetch_heartbeat(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "quant-system-okx-demo-remote-supervisor/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10.0) as response:
        payload = response.read(1_048_577)
    if len(payload) > 1_048_576:
        raise OkxDemoRemoteSupervisorError(
            "okx_demo_remote_supervisor_heartbeat_too_large"
        )
    decoded = json.loads(payload)
    if not isinstance(decoded, Mapping):
        raise OkxDemoRemoteSupervisorError(
            "okx_demo_remote_supervisor_heartbeat_invalid"
        )
    return decoded


def _query_for(path: str) -> dict[str, str]:
    if path == "/api/v5/account/config" or path == "/api/v5/account/balance":
        return {}
    if path == "/api/v5/account/positions":
        return {"instType": "SWAP", "instId": "BTC-USDT-SWAP"}
    return {"instType": "SWAP", "instId": "BTC-USDT-SWAP"}


def _append_receipt(
    config: OkxDemoRemoteSupervisorConfig,
    receipt: Mapping[str, Any],
) -> Path:
    directory = (
        config.receipt_external_root
        / "btc_okx_demo_remote_supervisor"
        / config.deployment_id
    )
    directory.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    stamp = str(receipt.get("observed_at_utc") or "").replace(":", "-")
    path = directory / f"{stamp}_{fingerprint[:16]}_{uuid.uuid4().hex[:8]}.json"
    temporary = path.with_name(f".{path.name}.tmp")
    encoded = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8") + b"\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _alert(code: str, severity: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "details": json.loads(json.dumps(details, default=str))}


def _dedupe_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alert in alerts:
        key = json.dumps(alert, sort_keys=True, separators=(",", ":"), default=str)
        if key not in seen:
            seen.add(key)
            result.append(alert)
    return result


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise OkxDemoRemoteSupervisorError(
            "okx_demo_remote_supervisor_clock_must_be_timezone_aware"
        )
    return value.astimezone(timezone.utc)


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}:{str(exc)[:200]}"
