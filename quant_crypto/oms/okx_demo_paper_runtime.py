"""Fail-closed OKX Demo runtime owned by the BTC OMS boundary."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import tempfile
import uuid
from contextlib import closing
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from quant_crypto.application.btc_strategy_registry import (
    OKX_NATIVE_STRATEGY_LINE,
    STABLE_STRATEGY_LINE,
    btc_strategy_registry,
)
from quant_crypto.application.btc_demo_start_attempt import (
    ACCOUNT_IDENTITY_HASH_SOURCE,
    START_ATTEMPT_SCHEMA_VERSION,
    StartAttemptBinding,
    authoritative_account_identity_snapshot,
    build_effective_policy,
    is_authoritative_account_identity_hash,
)
from quant_crypto.application.btc_demo_production_composition import (
    canonical_ledger_snapshot_sha256,
    leverage_blocker_code,
    validate_isolated_leverage,
)
from quant_crypto.oms.okx_demo import (
    OKX_DEMO_INSTRUMENT_ID,
    OKX_DEMO_RECOVERABLE_READ_CODES,
    OkxDemoClient,
    OkxDemoClientConfig,
    OkxDemoResponse,
    OkxDemoSafetyError,
    OkxDemoTransportError,
    load_windows_keyring_credentials,
)
from quant_crypto.oms.lifecycle import BTCPaperOMS, BTCPaperOrderStatus
from quant_crypto.oms.account_risk_facts import (
    ACCOUNT_FACTS_BASELINE_FRESHNESS_TTL_SECONDS,
    ACCOUNT_DRAWDOWN_SCOPE,
    AccountRiskFactError,
    advance_account_drawdown_fact,
    build_explicit_account_drawdown_baseline,
    build_okx_account_cashflow_evidence,
    build_unknown_account_drawdown_fact,
    replay_account_ledger_uows,
    validate_account_cashflow_evidence,
    validate_reviewed_account_facts_approval,
)
from quant_crypto.oms.shared_platform_v3 import (
    OMSAttachedProtection,
    OMSContractError,
    OMSOrderSubmissionBundle,
    SharedPlatformV3OMS,
)
from quant_crypto.oms.okx_demo_private_ws import (
    OkxDemoPrivateWS,
    _project_reconciliation_blocker_evidence,
    _safe_diagnostic_code as _safe_probe_code,
    _safe_diagnostic_text as _strict_probe_text,
    _safe_protocol_code as _safe_probe_protocol_code,
    _safe_subscription_channels as _safe_probe_channels,
)
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.portfolio.forecast import BTCForecast
from quant_crypto.runtime.control_plane import (
    BTCExecutionDispatchFacts,
    BTCExecutionResult,
)
from quant_shared.runtime.permissions import RuntimeAction
from quant_crypto.research.btc_demo_observation_accumulator import (
    append_hourly_observation_receipt,
    build_hourly_observation_receipt,
    build_observation_window_report,
    load_observation_receipt_ledger,
)
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    Signal,
    SignalDirection,
    TargetPosition,
    TimeInForce,
)
from tools.agent_governance.shared_data import (
    SharedDataError,
    load_manifest_from_git,
    resolve_manifest_payload,
)


OKX_DEMO_PAPER_RUNTIME_VERSION = "okx_demo_paper_runtime_v1"
OKX_DEMO_PAPER_AUTHORIZATION_TICKET = "BTC-OKX-DEMO-PAPER-01"
OKX_DEMO_PAPER_CREDENTIAL_SERVICE = "quant-system.okx-demo.trade"
OKX_DEMO_PAPER_CONFIRMATION = "BTC DEMO"
OKX_DEMO_STOP_AND_FLATTEN_CONFIRMATION = "STOP AND FLATTEN"
OKX_DEMO_INSTRUMENT_FAMILY = "BTC-USDT"
OKX_DEMO_PAPER_CONTRACTS = Decimal("0.01")
OKX_DEMO_PAPER_MAX_NET_CONTRACTS = Decimal("0.01")
OKX_DEMO_PAPER_MAX_NOTIONAL_USDT = Decimal("10")
OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS = Decimal("0.03")
OKX_DEMO_PARTIAL_FILL_DRILL_MAX_NOTIONAL_USDT = Decimal("25")
OKX_DEMO_PARTIAL_FILL_AUTHORITY_VERSION = "okx_demo_partial_fill_authority_v1"
OKX_DEMO_PARTIAL_FILL_RUNTIME_BOUNDARY = (
    "OkxDemoPaperRuntimeController.run_fault_drill_scenario"
)
OKX_DEMO_PARTIAL_FILL_ATTESTATION_VERSION = (
    "okx_demo_partial_runtime_attestation_v1"
)
OKX_DEMO_PAPER_CONTRACT_VALUE_BTC = Decimal("0.01")
OKX_DEMO_PAPER_MAX_CLOCK_OFFSET_MS = 15_000
OKX_DEMO_PAPER_ORDER_TAG = "btcP0Demo"
OKX_DEMO_FAULT_DRILL_ALGO_CANCEL_READBACK_ATTEMPTS = 8
OKX_DEMO_FAULT_DRILL_ALGO_CANCEL_READBACK_DELAY_SECONDS = 0.25
_FRESH_STATE_EMERGENCY_FIXED_IDENTITY = {
    "environment": "OKX Demo",
    "instrument_id": OKX_DEMO_INSTRUMENT_ID,
    "margin_mode": "isolated",
    "position_side": "long",
    "entry_cl_ord_id": "btcDP20a8d1650001",
    "entry_ord_id": "3816659792351170560",
    "oco_algo_cl_ord_id": "btcDP20a8d1650001A",
    "oco_algo_id": "3816659794069377024",
    "contracts": "0.01",
}
_FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION = (
    "btc_okx_demo_flat_hosted_exit_binding_v1"
)
_FLAT_HOSTED_EXIT_BINDING_SOURCE = "immutable_flat_hosted_exit_receipt_bundle"
_OKX_DEMO_APPROVED_PROTECTION_POLICY_CANONICAL = {
    "policy_id": "btc_demo_p0_exchange_guard",
    "version": "1",
    "sl_distance_bps": "100",
    "tp_distance_bps": "200",
    "trigger": "mark",
}
OKX_DEMO_APPROVED_PROTECTION_POLICY = {
    **_OKX_DEMO_APPROVED_PROTECTION_POLICY_CANONICAL,
    "policy_sha256": hashlib.sha256(
        json.dumps(
            _OKX_DEMO_APPROVED_PROTECTION_POLICY_CANONICAL,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest(),
}
OKX_DEMO_RISK_MODE_STARTUP = "STARTUP_RECONCILING"
OKX_DEMO_RISK_MODE_RUNNING = "RUNNING"
OKX_DEMO_RISK_MODE_REDUCING = "RISK_REDUCING"
OKX_DEMO_RISK_MODE_FROZEN = "FROZEN_UNKNOWN"
OKX_DEMO_UNRESOLVED_INTENT_STATUSES = frozenset(
    {"submit_pending", "unknown", "accepted", "reconciled_open"}
)
OKX_DEMO_TERMINAL_INTENT_STATUSES = frozenset(
    {"terminal", "rejected", "canceled", "cancelled", "reconciled_terminal"}
)
COMPLETED_ONE_HOUR_MS = 3_600_000
OKX_DEMO_PUBLIC_CANDLE_PAGE_LIMIT = 100
OKX_DEMO_PUBLIC_CANDLE_MAX_PAGES = 12
# New-risk RuntimeSnapshot projections remain strictly limited to 30 seconds.
# Protective CAA renewal has a separately bounded, control-plane verified
# authority window and therefore must not wait behind a full network refresh.
OKX_DEMO_BOUNDARY_SNAPSHOT_TTL_SECONDS = 30
OKX_DEMO_BOUNDARY_SNAPSHOT_REFRESH_MARGIN_SECONDS = 5
# A completed worker cycle can legitimately include REST, Private WS and
# ledger work that exceeds the exchange CAA TTL.  Progress freshness is kept
# bounded, but thread liveness remains an independent mandatory check.
OKX_DEMO_WORKER_PROGRESS_TTL_SECONDS = 120
# Transient recovery is protective-only.  A short, bounded backoff prevents a
# dead-man/worker incident from turning into a tight retry loop while still
# allowing a recovered venue to re-establish one authoritative generation.
OKX_DEMO_TRANSIENT_RECOVERY_BACKOFF_SECONDS = (0.25, 1.0, 2.0)
OKX_DEMO_TRANSIENT_RECOVERY_MAX_ATTEMPTS = len(
    OKX_DEMO_TRANSIENT_RECOVERY_BACKOFF_SECONDS
)
OKX_NATIVE_DEMO_POINTER_PATH = Path("artifacts/btc_okx_native_backtest_evidence/latest_manifest.json")
OKX_NATIVE_SHARED_DATA_SCHEMA = "btc_okx_public_swap_research_bundle_v1"
OKX_NATIVE_LEGACY_SHARED_DATA_SCHEMA = "btc_okx_native_research_data_manifest_v1"
OKX_GENERIC_PUBLIC_SWAP_MANIFEST = "btc_perpetual_bundle_manifest.json"
OKX_GENERIC_PUBLIC_SWAP_CANDLES = "klines_1h.csv"
OKX_GENERIC_PUBLIC_SWAP_REQUIRED_FILES = {
    "klines_1h": OKX_GENERIC_PUBLIC_SWAP_CANDLES,
    "mark_price_klines_1h": "mark_price_klines_1h.csv",
    "premium_index_klines_1h": "premium_index_klines_1h.csv",
    "funding_rate": "funding_rate.csv",
}
OKX_GENERIC_PUBLIC_SWAP_DIAGNOSTIC_WARNINGS = {
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "btc_liquidation_snapshots_missing_diagnostic_only",
}
OKX_NATIVE_DEMO_REQUIRED_CHECKS = (
    "completed_1h_only",
    "hourly_unique",
    "hourly_contiguous",
    "public_rest_only",
    "api_key_not_used",
    "private_endpoint_not_used",
    "order_endpoint_not_used",
)
OKX_NATIVE_DEMO_FALSE_SAFETY_FLAGS = (
    "paper_start",
    "private_endpoint_used",
    "order_endpoint_used",
    "real_order_submitted",
)
MIB = 1024 * 1024
GIB = 1024 * MIB


class OkxDemoPaperRuntimeError(RuntimeError):
    pass


def _writer_nonce_from_call(
    default_nonce: str,
    kwargs: Mapping[str, Any],
    nonce_argument: str,
) -> str:
    if not nonce_argument:
        return default_nonce
    payload = kwargs.get(nonce_argument)
    if isinstance(payload, Mapping):
        nonce = str(payload.get("worker_nonce") or "")
        if nonce:
            return nonce
    return default_nonce


def _runtime_writer_session(*, nonce_argument: str = ""):
    """Hold a newly acquired writer lock until stop; release on failure."""

    def decorate(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            nonce = _writer_nonce_from_call(
                self._default_writer_lock_nonce,
                kwargs,
                nonce_argument,
            )
            writer_context = kwargs.get("authorization")
            canonical_context = (
                writer_context
                if isinstance(writer_context, Mapping)
                and self._is_canonical_incident_recovery_authorization(
                    writer_context
                )
                else None
            )
            preflight: Mapping[str, Any] | None = None
            acquired_here = False
            try:
                if canonical_context is not None:
                    preflight = self._preflight_incident_recovery_binding(
                        canonical_context
                    )
                    self._fault_drill_recovery_preflight = dict(preflight)
                    self._fault_drill_recovery_admission_passed = False
                acquired_here = self._ensure_runtime_writer_lock(
                    nonce=nonce,
                    writer_context=(
                        writer_context
                        if isinstance(writer_context, Mapping)
                        else None
                    ),
                    preflight=preflight,
                )
                return method(self, *args, **kwargs)
            except BaseException:
                if acquired_here:
                    self.release_fault_drill_process_lock()
                elif canonical_context is not None:
                    self._fault_drill_recovery_preflight = None
                    self._fault_drill_owner_marker_preflight = None
                    self._fault_drill_owner_marker_session = None
                    self._fault_drill_recovery_admission_passed = False
                raise

        return wrapped

    return decorate


def _runtime_writer_operation(method):
    """Protect a bounded mutation, preserving an existing runtime session lock."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        acquired_here = self._ensure_runtime_writer_lock(
            nonce=self._default_writer_lock_nonce
        )
        try:
            return method(self, *args, **kwargs)
        finally:
            if acquired_here:
                self.release_fault_drill_process_lock()

    return wrapped


def _runtime_writer_fresh_emergency_operation(method):
    """Validate the narrow operator envelope before acquiring the writer lock."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        payload = kwargs.get("payload")
        if payload is None and args:
            payload = args[0]
        normalized = self._validate_fresh_state_emergency_operator_payload(
            payload
        )
        with self._lock:
            marker = _mapping(
                _mapping(self._state.get("runtime")).get(
                    "fresh_state_emergency_exit"
                )
            )
            if str(marker.get("status") or "not_attempted") != "not_attempted":
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_already_attempted"
                )
        owner_marker_audit = self._fresh_state_emergency_owner_marker_preflight()
        acquired_here = self._ensure_runtime_writer_lock(
            nonce=self._default_writer_lock_nonce
        )
        self._fresh_state_emergency_owner_marker_audit = owner_marker_audit
        call_kwargs = {
            key: value for key, value in kwargs.items() if key != "payload"
        }
        try:
            return method(self, normalized, **call_kwargs)
        finally:
            self._fresh_state_emergency_owner_marker_audit = None
            if acquired_here:
                self.release_fault_drill_process_lock()

    return wrapped


def _runtime_writer_stop(method):
    """Stop owns the writer lock and releases it on every terminal path."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        self._ensure_runtime_writer_lock(nonce=self._default_writer_lock_nonce)
        try:
            return method(self, *args, **kwargs)
        finally:
            self.release_fault_drill_process_lock()

    return wrapped


@dataclass(frozen=True)
class BTCDemoRuntimeDataBudget:
    market_ring_window_minutes: int = 15
    market_ring_hard_cap_bytes: int = 256 * MIB
    l2_disk_persistence_enabled: bool = False
    sampled_event_types: tuple[str, ...] = ("signal", "order", "error")
    sampled_event_rolling_hard_cap_bytes: int = 1 * GIB
    runtime_warning_bytes: int = 4 * GIB
    runtime_stop_raw_market_writes_bytes: int = 5 * GIB

    def __post_init__(self) -> None:
        if not 10 <= int(self.market_ring_window_minutes) <= 15:
            raise OkxDemoSafetyError(
                "okx_demo_market_ring_window_must_be_10_to_15_minutes"
            )
        if not 0 < int(self.market_ring_hard_cap_bytes) <= 256 * MIB:
            raise OkxDemoSafetyError("okx_demo_market_ring_cap_exceeds_256mib")
        if self.l2_disk_persistence_enabled:
            raise OkxDemoSafetyError(
                "okx_demo_l2_disk_persistence_must_default_disabled"
            )
        if set(self.sampled_event_types) - {"signal", "order", "error"}:
            raise OkxDemoSafetyError(
                "okx_demo_sampled_event_type_not_allowlisted"
            )
        if not 0 < int(self.sampled_event_rolling_hard_cap_bytes) <= GIB:
            raise OkxDemoSafetyError(
                "okx_demo_sampled_event_cap_exceeds_1gib"
            )
        if int(self.runtime_warning_bytes) != 4 * GIB:
            raise OkxDemoSafetyError("okx_demo_runtime_warning_must_equal_4gib")
        if int(self.runtime_stop_raw_market_writes_bytes) != 5 * GIB:
            raise OkxDemoSafetyError(
                "okx_demo_runtime_stop_must_equal_5gib"
            )

    def evaluate(self, *, runtime_data_bytes: int) -> dict[str, Any]:
        used = max(0, int(runtime_data_bytes))
        stop = used >= self.runtime_stop_raw_market_writes_bytes
        return {
            "runtime_data_bytes": used,
            "warning": used >= self.runtime_warning_bytes,
            "raw_market_writes_allowed": not stop,
            "cancel_only_required": stop,
            "protected_state_retention_required": True,
            "protected_state": [
                "order",
                "fill",
                "position",
                "cash",
                "funding",
                "ledger",
                "audit",
                "error",
                "checkpoint",
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_ring_window_minutes": self.market_ring_window_minutes,
            "market_ring_hard_cap_bytes": self.market_ring_hard_cap_bytes,
            "l2_disk_persistence_enabled": self.l2_disk_persistence_enabled,
            "sampled_event_types": list(self.sampled_event_types),
            "sampled_event_rolling_hard_cap_bytes": (
                self.sampled_event_rolling_hard_cap_bytes
            ),
            "runtime_warning_bytes": self.runtime_warning_bytes,
            "runtime_stop_raw_market_writes_bytes": (
                self.runtime_stop_raw_market_writes_bytes
            ),
        }


class BTCBoundedEphemeralMarketDataRing:
    """Time- and byte-bounded public market snapshots; never persisted."""

    def __init__(self, budget: BTCDemoRuntimeDataBudget) -> None:
        self.budget = budget
        self._rows: deque[tuple[datetime, dict[str, Any], int]] = deque()
        self._bytes = 0

    def append(
        self, payload: Mapping[str, Any], *, observed_at_utc: datetime
    ) -> None:
        observed = observed_at_utc.astimezone(timezone.utc)
        normalized = json.loads(json.dumps(dict(payload), default=str))
        encoded_size = len(
            json.dumps(
                normalized, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        if encoded_size > self.budget.market_ring_hard_cap_bytes:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_market_snapshot_exceeds_ring_hard_cap"
            )
        self._rows.append((observed, normalized, encoded_size))
        self._bytes += encoded_size
        cutoff = observed - timedelta(
            minutes=self.budget.market_ring_window_minutes
        )
        while self._rows and (
            self._rows[0][0] < cutoff
            or self._bytes > self.budget.market_ring_hard_cap_bytes
        ):
            _, _, removed = self._rows.popleft()
            self._bytes -= removed

    def summary(self) -> dict[str, Any]:
        return {
            "window_minutes": self.budget.market_ring_window_minutes,
            "hard_cap_bytes": self.budget.market_ring_hard_cap_bytes,
            "row_count": len(self._rows),
            "bytes": self._bytes,
            "persisted": False,
            "l2_disk_persistence_enabled": False,
        }


def collect_okx_account_cashflow_evidence(
    *,
    client: OkxDemoClient,
    account_identity_hash: str,
    snapshot_sha256: str,
    coverage_start_utc: Any,
    coverage_end_utc: Any,
    reference_time_utc: Any,
    max_pages: int = 128,
) -> dict[str, Any]:
    """Collect one bounded, complete OKX trading-account bills interval.

    OKX returns newest first and ``after`` moves to older bill IDs.  Queries
    intentionally omit instrument/type filters so transfer rows cannot be
    hidden by the BTC-only reconciliation view.  The caller controls whether
    this private GET capability exists; this function never creates a client.
    """

    start = _parse_utc(coverage_start_utc)
    end = _parse_utc(coverage_end_utc)
    reference = _parse_utc(reference_time_utc)
    if start is None or end is None or reference is None:
        return build_okx_account_cashflow_evidence(
            pages=[],
            account_identity_hash=account_identity_hash,
            snapshot_sha256=snapshot_sha256,
            coverage_start_utc=coverage_start_utc,
            coverage_end_utc=coverage_end_utc,
            reference_time_utc=reference_time_utc,
        )
    begin_ms = str(int(start.timestamp() * 1000))
    end_ms = str(int(end.timestamp() * 1000))
    if end - start > timedelta(days=7):
        return build_okx_account_cashflow_evidence(
            pages=[
                {
                    "request": {
                        "begin": begin_ms,
                        "end": end_ms,
                        "limit": "100",
                    },
                    "rows": [],
                }
            ],
            account_identity_hash=account_identity_hash,
            snapshot_sha256=snapshot_sha256,
            coverage_start_utc=start,
            coverage_end_utc=end,
            reference_time_utc=reference,
        )
    pages: list[dict[str, Any]] = []
    after = ""
    seen_cursors: set[str] = set()
    bounded_pages = max(1, min(int(max_pages), 128))
    for _ in range(bounded_pages):
        params = {"begin": begin_ms, "end": end_ms, "limit": "100"}
        if after:
            params["after"] = after
        response = _require(
            client.private_get("/api/v5/account/bills", params),
            "account_cashflow_bills",
            require_data=False,
        )
        rows = [dict(row) for row in response.data if isinstance(row, Mapping)]
        pages.append({"request": params, "rows": rows})
        if len(rows) < 100:
            break
        next_after = str(rows[-1].get("billId") or "")
        if not next_after or next_after in seen_cursors:
            break
        seen_cursors.add(next_after)
        after = next_after
    return build_okx_account_cashflow_evidence(
        pages=pages,
        account_identity_hash=account_identity_hash,
        snapshot_sha256=snapshot_sha256,
        coverage_start_utc=start,
        coverage_end_utc=end,
        reference_time_utc=reference,
    )


@dataclass(frozen=True)
class OkxDemoPaperRuntimeConfig:
    repo_root: Path
    data_db_path: Path
    credential_service: str = OKX_DEMO_PAPER_CREDENTIAL_SERVICE
    poll_interval_seconds: float = 30.0
    order_poll_interval_seconds: float = 0.5
    order_poll_attempts: int = 8
    aggressive_limit_bps: Decimal = Decimal("5")
    max_spread_bps: Decimal = Decimal("20")
    max_funding_abs_bps: Decimal = Decimal("100")
    max_clock_offset_ms: int = OKX_DEMO_PAPER_MAX_CLOCK_OFFSET_MS
    max_configured_leverage: Decimal = Decimal("3")
    dead_man_timeout_seconds: int = 30
    dead_man_heartbeat_seconds: float = 1.0
    output_dir: Path | None = None
    okx_native_shared_manifest_git_spec: str = ""
    okx_native_shared_data_root: Path | None = None
    okx_native_expected_dataset_id: str = ""
    runtime_data_budget: BTCDemoRuntimeDataBudget = BTCDemoRuntimeDataBudget()
    # Explicit, identity-only restore input.  An empty archive root is the
    # compatibility/default path and never causes an external directory scan.
    owned_id_restore_archive_root: Path | None = None
    owned_id_restore_current_head: str = ""
    owned_id_restore_source_head: str = ""
    owned_id_restore_account_identity: str = ""
    owned_id_restore_credential_identity: str = ""
    owned_id_restore_client_order_namespace: str = ""
    execution_dispatcher: Any | None = None
    # The composition root may inject an already-authorized T1/T2/T3/T4
    # bundle.  The runtime never fabricates one from an order-plan mapping.
    authoritative_oms_bundle_provider: Callable[..., OMSOrderSubmissionBundle] | None = None
    # Server-owned StartAttempt identity.  Account identity is supplied only
    # as a digest; raw account/credential identifiers never enter durable state.
    risk_profile: str = "baseline_1x"
    runtime_identity: str = ""
    # These fields are accepted only for a previously persisted, explicitly
    # attested account-config projection.  The controller never derives them
    # from credential service/instrument names.
    account_identity_hash: str = ""
    account_identity_hash_source: str = ""
    account_identity_captured_at_utc: str = ""
    # Both are server-owned composition seams.  They are never populated from
    # an HTTP/body payload.  Missing configuration keeps account facts unknown.
    account_facts_approval_resolver: Callable[[str], Mapping[str, Any] | None] | None = None
    account_facts_approval_id: str = ""
    account_cashflow_evidence_provider: Callable[..., Mapping[str, Any]] | None = None

    # V1 offline replay may inject an already-completed, immutable frame.
    # The default remains the existing manifest/SQLite loader path.
    offline_completed_frame_provider: Callable[[], pd.DataFrame] | None = None

    def __post_init__(self) -> None:
        if (
            self.offline_completed_frame_provider is not None
            and not callable(self.offline_completed_frame_provider)
        ):
            raise OkxDemoSafetyError("offline_completed_frame_provider_invalid")
        root = Path(self.repo_root).resolve()
        output = Path(
            self.output_dir
            or Path(tempfile.gettempdir()) / "quant-system" / "btc_demo_paper_runtime"
        ).resolve()
        if (root / ".git").exists() and (output == root or root in output.parents):
            raise OkxDemoSafetyError("okx_demo_paper_output_must_remain_outside_git")
        object.__setattr__(self, "repo_root", root)
        object.__setattr__(self, "data_db_path", Path(self.data_db_path).resolve())
        object.__setattr__(self, "output_dir", output)
        if self.okx_native_shared_data_root is not None:
            object.__setattr__(
                self,
                "okx_native_shared_data_root",
                Path(self.okx_native_shared_data_root).resolve(),
            )
        if self.owned_id_restore_archive_root is not None:
            archive_root = Path(self.owned_id_restore_archive_root).resolve()
            object.__setattr__(self, "owned_id_restore_archive_root", archive_root)
            if archive_root == root or root in archive_root.parents:
                raise OkxDemoSafetyError("okx_demo_owned_id_restore_must_remain_external")
            restore_values = (
                self.owned_id_restore_current_head,
                self.owned_id_restore_source_head,
                self.owned_id_restore_account_identity,
                self.owned_id_restore_credential_identity,
                self.owned_id_restore_client_order_namespace,
            )
            if not all(str(value).strip() for value in restore_values):
                raise OkxDemoSafetyError("okx_demo_owned_id_restore_identity_incomplete")
        elif any(
            str(value).strip()
            for value in (
                self.owned_id_restore_current_head,
                self.owned_id_restore_source_head,
                self.owned_id_restore_account_identity,
                self.owned_id_restore_credential_identity,
                self.owned_id_restore_client_order_namespace,
            )
        ):
            raise OkxDemoSafetyError("okx_demo_owned_id_restore_archive_root_missing")
        if self.okx_native_shared_manifest_git_spec:
            if self.okx_native_shared_data_root is None:
                raise OkxDemoSafetyError(
                    "okx_demo_paper_shared_data_root_missing"
                )
            if not self.okx_native_expected_dataset_id:
                raise OkxDemoSafetyError(
                    "okx_demo_paper_expected_dataset_id_missing"
                )
        if self.account_identity_hash:
            raise OkxDemoSafetyError(
                "btc_demo_authoritative_account_identity_must_come_from_snapshot"
            )
        if self.poll_interval_seconds < 1:
            raise OkxDemoSafetyError("okx_demo_paper_poll_interval_too_short")
        if self.order_poll_interval_seconds <= 0 or self.order_poll_attempts < 1:
            raise OkxDemoSafetyError("okx_demo_paper_order_poll_policy_invalid")
        if not 10 <= int(self.dead_man_timeout_seconds) <= 120:
            raise OkxDemoSafetyError("okx_demo_dead_man_timeout_out_of_bounds")
        if not 0.25 <= float(self.dead_man_heartbeat_seconds) <= 5.0:
            raise OkxDemoSafetyError("okx_demo_dead_man_heartbeat_out_of_bounds")


@dataclass(frozen=True)
class ServerSideProtectionPolicy:
    policy_id: str
    version: str
    policy_sha256: str
    sl_distance_bps: Decimal
    tp_distance_bps: Decimal
    trigger: str

    @classmethod
    def from_mapping(cls, payload: Any) -> "ServerSideProtectionPolicy":
        row = payload if isinstance(payload, Mapping) else {}
        return cls(
            policy_id=str(row.get("policy_id") or ""),
            version=str(row.get("version") or ""),
            policy_sha256=str(row.get("policy_sha256") or ""),
            sl_distance_bps=_decimal(row.get("sl_distance_bps")),
            tp_distance_bps=_decimal(row.get("tp_distance_bps")),
            trigger=str(row.get("trigger") or ""),
        )

    def canonical_payload(self) -> dict[str, str]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "sl_distance_bps": _text(self.sl_distance_bps),
            "tp_distance_bps": _text(self.tp_distance_bps),
            "trigger": self.trigger,
        }

    def expected_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.canonical_payload(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def validate(self) -> list[str]:
        blockers: list[str] = []
        if not self.policy_id or len(self.policy_id) > 64:
            blockers.append("okx_demo_server_side_protection_policy_id_invalid")
        if not self.version or len(self.version) > 32:
            blockers.append("okx_demo_server_side_protection_policy_version_invalid")
        if self.trigger != "mark":
            blockers.append("okx_demo_server_side_protection_trigger_must_be_mark")
        if not Decimal("10") <= self.sl_distance_bps <= Decimal("2500"):
            blockers.append("okx_demo_server_side_stop_distance_out_of_bounds")
        if not Decimal("10") <= self.tp_distance_bps <= Decimal("5000"):
            blockers.append("okx_demo_server_side_take_profit_distance_out_of_bounds")
        if (
            len(self.policy_sha256) != 64
            or not self.policy_sha256.isascii()
            or any(character not in "0123456789abcdef" for character in self.policy_sha256)
            or self.policy_sha256 != self.expected_sha256()
        ):
            blockers.append("okx_demo_server_side_protection_policy_hash_mismatch")
        return blockers

    def to_dict(self) -> dict[str, str]:
        return {**self.canonical_payload(), "policy_sha256": self.policy_sha256}


@dataclass(frozen=True)
class OkxDemoPaperStartRequest:
    authorization_ticket: str
    strategy_id: str
    candidate_id: str
    strategy_version: str
    instrument_id: str
    margin_mode: str
    order_contracts: Decimal
    max_net_contracts: Decimal
    max_notional_usdt: Decimal
    confirmation_text: str
    confirm_demo_only: bool
    confirm_automatic_orders: bool
    confirm_risk_limits: bool
    confirm_cancel_only_on_error: bool
    confirm_dedicated_demo_account: bool
    dead_man_tag: str
    server_side_protection_policy: ServerSideProtectionPolicy
    fault_drill_scenario: str = ""
    owned_id_restore_archive_root: Path | None = None
    owned_id_restore_current_head: str = ""
    owned_id_restore_source_head: str = ""
    owned_id_restore_account_identity: str = ""
    owned_id_restore_credential_identity: str = ""
    owned_id_restore_client_order_namespace: str = ""
    parent_operation_id: str = ""
    runtime_identity: str = ""
    source_head: str = ""
    effective_policy_digest: str = ""
    risk_profile: str = ""
    expected_leverage: str = ""
    account_identity_hash: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "OkxDemoPaperStartRequest":
        restore = payload.get("owned_id_restore")
        restore_mapping = restore if isinstance(restore, Mapping) else {}

        def restore_value(name: str) -> Any:
            value = payload.get(name)
            return restore_mapping.get(name, value)

        restore_root = restore_value("owned_id_restore_archive_root")
        return cls(
            authorization_ticket=str(payload.get("authorization_ticket") or ""),
            strategy_id=str(payload.get("strategy_id") or ""),
            candidate_id=str(payload.get("candidate_id") or ""),
            strategy_version=str(payload.get("strategy_version") or ""),
            instrument_id=str(payload.get("instrument_id") or ""),
            margin_mode=str(payload.get("margin_mode") or ""),
            order_contracts=_decimal(payload.get("order_contracts")),
            max_net_contracts=_decimal(payload.get("max_net_contracts")),
            max_notional_usdt=_decimal(payload.get("max_notional_usdt")),
            confirmation_text=str(payload.get("confirmation_text") or ""),
            confirm_demo_only=payload.get("confirm_demo_only") is True,
            confirm_automatic_orders=payload.get("confirm_automatic_orders") is True,
            confirm_risk_limits=payload.get("confirm_risk_limits") is True,
            confirm_cancel_only_on_error=payload.get("confirm_cancel_only_on_error") is True,
            confirm_dedicated_demo_account=(
                payload.get("confirm_dedicated_demo_account") is True
            ),
            dead_man_tag=str(payload.get("dead_man_tag") or ""),
            server_side_protection_policy=ServerSideProtectionPolicy.from_mapping(
                payload.get("server_side_protection_policy")
            ),
            fault_drill_scenario=str(payload.get("fault_drill_scenario") or ""),
            owned_id_restore_archive_root=(
                Path(str(restore_root)).resolve()
                if restore_root not in (None, "")
                else None
            ),
            owned_id_restore_current_head=str(
                restore_value("owned_id_restore_current_head") or ""
            ),
            owned_id_restore_source_head=str(
                restore_value("owned_id_restore_source_head") or ""
            ),
            owned_id_restore_account_identity=str(
                restore_value("owned_id_restore_account_identity") or ""
            ),
            owned_id_restore_credential_identity=str(
                restore_value("owned_id_restore_credential_identity") or ""
            ),
            owned_id_restore_client_order_namespace=str(
                restore_value("owned_id_restore_client_order_namespace") or ""
            ),
            parent_operation_id=str(payload.get("parent_operation_id") or ""),
            runtime_identity=str(payload.get("runtime_identity") or ""),
            source_head=str(payload.get("source_head") or ""),
            effective_policy_digest=str(payload.get("effective_policy_digest") or ""),
            risk_profile=str(payload.get("risk_profile") or ""),
            expected_leverage=str(payload.get("expected_leverage") or ""),
            account_identity_hash=str(payload.get("account_identity_hash") or ""),
        )

    def validate(self) -> list[str]:
        blockers: list[str] = []
        if self.authorization_ticket != OKX_DEMO_PAPER_AUTHORIZATION_TICKET:
            blockers.append("okx_demo_paper_authorization_ticket_invalid")
        if self.strategy_id not in {STABLE_STRATEGY_LINE, OKX_NATIVE_STRATEGY_LINE}:
            blockers.append("okx_demo_paper_strategy_not_allowlisted")
        try:
            spec = btc_strategy_registry.get(self.strategy_id, self.candidate_id)
        except ValueError:
            spec = None
            blockers.append("okx_demo_paper_candidate_not_frozen")
        if spec is not None:
            if self.strategy_version != spec.strategy_version:
                blockers.append("okx_demo_paper_strategy_version_mismatch")
            if not spec.canonical_signal_available:
                blockers.append("okx_demo_paper_canonical_signal_unavailable")
        if self.instrument_id != OKX_DEMO_INSTRUMENT_ID:
            blockers.append("okx_demo_paper_instrument_not_allowlisted")
        if self.margin_mode != "isolated":
            blockers.append("okx_demo_paper_margin_mode_must_be_isolated")
        if self.fault_drill_scenario not in {"", "partial_fill_disconnect"}:
            blockers.append("okx_demo_fault_drill_start_scenario_not_allowlisted")
        restore_values = (
            self.owned_id_restore_current_head,
            self.owned_id_restore_source_head,
            self.owned_id_restore_account_identity,
            self.owned_id_restore_credential_identity,
            self.owned_id_restore_client_order_namespace,
        )
        if self.owned_id_restore_archive_root is None:
            if any(str(value).strip() for value in restore_values):
                blockers.append("okx_demo_owned_id_restore_archive_root_missing")
        elif not all(str(value).strip() for value in restore_values):
            blockers.append("okx_demo_owned_id_restore_identity_incomplete")
        else:
            for field, value in (
                ("current_head", self.owned_id_restore_current_head),
                ("source_head", self.owned_id_restore_source_head),
            ):
                if not re.fullmatch(r"[0-9a-fA-F]{40}", str(value)):
                    blockers.append(f"okx_demo_owned_id_restore_{field}_invalid")
            if not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,64}",
                self.owned_id_restore_client_order_namespace,
            ):
                blockers.append("okx_demo_owned_id_restore_namespace_invalid")
        if self.fault_drill_scenario == "partial_fill_disconnect":
            if self.order_contracts != OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS:
                blockers.append("okx_demo_partial_fill_order_size_must_equal_0p03")
            if self.max_net_contracts != OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS:
                blockers.append("okx_demo_partial_fill_max_net_must_equal_0p03")
            if (
                self.max_notional_usdt <= 0
                or self.max_notional_usdt > OKX_DEMO_PARTIAL_FILL_DRILL_MAX_NOTIONAL_USDT
            ):
                blockers.append("okx_demo_partial_fill_notional_cap_exceeds_25_usdt")
        else:
            if self.order_contracts != OKX_DEMO_PAPER_CONTRACTS:
                blockers.append("okx_demo_paper_order_size_must_equal_0p01")
            if self.max_net_contracts != OKX_DEMO_PAPER_MAX_NET_CONTRACTS:
                blockers.append("okx_demo_paper_max_net_must_equal_0p01")
            if self.max_notional_usdt <= 0 or self.max_notional_usdt > OKX_DEMO_PAPER_MAX_NOTIONAL_USDT:
                blockers.append("okx_demo_paper_notional_cap_exceeds_authorization")
        if self.confirmation_text != OKX_DEMO_PAPER_CONFIRMATION:
            blockers.append("okx_demo_paper_confirmation_text_invalid")
        if not self.confirm_demo_only:
            blockers.append("okx_demo_paper_demo_only_not_confirmed")
        if not self.confirm_automatic_orders:
            blockers.append("okx_demo_paper_automatic_orders_not_confirmed")
        if not self.confirm_risk_limits:
            blockers.append("okx_demo_paper_risk_limits_not_confirmed")
        if not self.confirm_cancel_only_on_error:
            blockers.append("okx_demo_paper_cancel_only_not_confirmed")
        if not self.confirm_dedicated_demo_account:
            blockers.append("okx_demo_dead_man_requires_dedicated_demo_account")
        if self.dead_man_tag != OKX_DEMO_PAPER_ORDER_TAG:
            blockers.append("okx_demo_dead_man_tag_namespace_invalid")
        protection = self.server_side_protection_policy
        if (
            not protection.policy_id
            and not protection.version
            and not protection.policy_sha256
            and protection.sl_distance_bps == 0
            and protection.tp_distance_bps == 0
            and not protection.trigger
        ):
            blockers.append("okx_demo_server_side_protection_policy_missing")
        else:
            policy_blockers = protection.validate()
            blockers.extend(policy_blockers)
            if (
                not policy_blockers
                and protection.to_dict()
                != OKX_DEMO_APPROVED_PROTECTION_POLICY
            ):
                blockers.append(
                    "okx_demo_server_side_protection_policy_not_approved"
                )
        binding_values = (
            self.parent_operation_id,
            self.runtime_identity,
            self.source_head,
            self.effective_policy_digest,
            self.risk_profile,
            self.expected_leverage,
            self.account_identity_hash,
        )
        if any(str(value).strip() for value in binding_values[1:]):
            if not self.parent_operation_id:
                blockers.append("btc_demo_start_attempt_parent_operation_id_missing")
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", self.runtime_identity):
                blockers.append("btc_demo_start_attempt_runtime_identity_invalid")
            if not re.fullmatch(r"[0-9a-fA-F]{40}", self.source_head):
                blockers.append("btc_demo_start_attempt_source_head_invalid")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", self.effective_policy_digest):
                blockers.append("btc_demo_start_attempt_policy_digest_invalid")
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,63}", self.risk_profile):
                blockers.append("btc_demo_start_attempt_risk_profile_invalid")
            try:
                if Decimal(self.expected_leverage) <= 0:
                    raise ValueError
            except (InvalidOperation, TypeError, ValueError):
                blockers.append("btc_demo_start_attempt_expected_leverage_invalid")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", self.account_identity_hash):
                blockers.append("btc_demo_start_attempt_account_identity_hash_invalid")
        return _dedupe(blockers)


class OkxDemoPaperRuntimeController:
    def __init__(
        self,
        *,
        config: OkxDemoPaperRuntimeConfig,
        credential_loader: Callable[[str], Any] = load_windows_keyring_credentials,
        client_factory: Callable[[OkxDemoClientConfig, Any], OkxDemoClient] | None = None,
        private_ws_factory: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        start_worker: bool = True,
        start_capability_checker: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._runtime_identity = str(config.runtime_identity or f"btc-demo-runtime:{uuid.uuid4().hex}")
        self._risk_profile = str(
            config.risk_profile
            or ("stress_3x" if Decimal(config.max_configured_leverage) == Decimal("3") else "baseline_1x")
        )
        self._expected_leverage = (
            "1"
            if self._risk_profile == "baseline_1x"
            else format(Decimal(config.max_configured_leverage).normalize(), "f")
        )
        # Account identity is unknown until an authoritative account-config
        # snapshot is reconciled.  Never fall back to a credential-service /
        # instrument namespace: it cannot distinguish two real accounts.
        self._account_identity_hash = ""
        self._account_identity_source = ""
        self._account_identity_captured_at_utc = ""
        self._credential_loader = credential_loader
        self._client_factory = client_factory or (lambda client_config, credentials: OkxDemoClient(config=client_config, credentials=credentials))
        self._private_ws_factory = private_ws_factory or OkxDemoPrivateWS
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._start_worker = start_worker
        self._start_capability_checker = (
            start_capability_checker or self._local_start_capability
        )
        self._lock = threading.RLock()
        self._execution_lock = threading.Lock()
        self._transient_recovery_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._dead_man_thread: threading.Thread | None = None
        self._start_operation_thread: threading.Thread | None = None
        self._start_operation_internal_id = ""
        self._client: OkxDemoClient | None = None
        self._private_ws: Any | None = None
        self._oms = BTCPaperOMS()
        # T5 is a pure construction delegate.  It never owns transport or
        # permission state; the existing dispatcher remains the only I/O
        # boundary below this facade.
        self._shared_platform_v3_oms = SharedPlatformV3OMS()
        self._market_ring = BTCBoundedEphemeralMarketDataRing(
            self.config.runtime_data_budget
        )
        self._owned_client_order_ids: set[str] = set()
        self._protection_policy: ServerSideProtectionPolicy | None = None
        self._sequence = 0
        self._fault_drill_lock_handle: Any | None = None
        self._fault_drill_lock_nonce = ""
        self._fault_drill_recovery_preflight: dict[str, Any] | None = None
        self._fault_drill_owner_marker_preflight: dict[str, Any] | None = None
        self._fault_drill_owner_marker_session: dict[str, Any] | None = None
        self._fault_drill_recovery_admission_passed = False
        self._default_writer_lock_nonce = uuid.uuid4().hex
        self._private_ws_generation = 0
        self._runtime_completed_chart_frame: pd.DataFrame | None = None
        self._runtime_completed_chart_evidence: dict[str, Any] = {}
        self._fresh_state_emergency_owner_marker_audit: dict[str, Any] | None = None
        # A fresh-state emergency exit is deliberately a one-shot capability.
        # It is populated only by the public emergency entry point after all
        # offline/fresh-state gates pass; direct callers cannot opt into the
        # frozen-mode submit exception by passing a flag to _submit_order_plan.
        self._fresh_state_emergency_exit_authorization: dict[str, str] | None = None
        self._state = self._initial_state()
        self._runtime_store = self._create_runtime_store()
        self._recover_previous_state()
        self._recover_start_operation_after_restart()
        # Rehydrate the operator-facing observation projection from the
        # append-only receipt ledger.  A restart must not make valid prior
        # Demo hours disappear from the cumulative counter.
        self._refresh_observation_projection_from_ledger()

    def _create_runtime_store(self) -> BTCRuntimeStore:
        """Production keeps the existing uncached recovery by default."""
        return BTCRuntimeStore(Path(self.config.output_dir))

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._durable_state_snapshot()
            events: list[dict[str, Any]] = []
            seen_event_ids: set[str] = set()
            for event in self._state.get("events", []):
                projected = self._status_event_projection(event)
                event_id = str(projected["event_id"])
                if event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)
                events.append(projected)
            state["events"] = events
            state["start_operation"] = json.loads(
                json.dumps(
                    _mapping(state.get("runtime", {}).get("start_operation"))
                )
            )
            state["historical_start_operations"] = json.loads(
                json.dumps(
                    list(state.get("runtime", {}).get("start_operation_history") or [])
                )
            )
            thread = self._thread
            private_ws = self._private_ws
        state["runtime"]["worker_alive"] = bool(
            thread is not None and thread.is_alive()
        )
        try:
            capability = dict(self._start_capability_checker())
        except Exception as exc:
            capability = {
                "ready": False,
                "incident_category": "local_environment",
                "blockers": [_safe_error(exc)],
            }
        if (
            not is_authoritative_account_identity_hash(self._account_identity_hash)
            or self._account_identity_source != ACCOUNT_IDENTITY_HASH_SOURCE
        ):
            capability["ready"] = False
            capability["incident_category"] = "account_identity"
            capability["blockers"] = _dedupe(
                [
                    *list(capability.get("blockers") or []),
                    "btc_demo_authoritative_account_identity_hash_missing",
                ]
            )
        state["start_capability"] = capability
        dead_man_thread = self._dead_man_thread
        state["risk_control"]["dead_man"]["heartbeat_thread_alive"] = bool(
            dead_man_thread is not None and dead_man_thread.is_alive()
        )
        self._apply_authoritative_liveness_to_status(state)
        if private_ws is not None and hasattr(private_ws, "status"):
            current_ws = private_ws.status()
            if isinstance(current_ws, Mapping):
                state["private_ws"].update(
                    json.loads(json.dumps(dict(current_ws)))
                )
        return state

    def current_start_attempt_identity(self) -> dict[str, str]:
        """Return the serving process's current server-owned StartAttempt identity.

        The account component is refreshed from the latest authoritative
        account-config projection.  It is intentionally empty before a
        trusted snapshot exists so callers can fail closed before durable
        lookup/begin rather than binding a guessed namespace.
        """

        source_head = _repo_head(self.config.repo_root)
        account_hash = self._account_identity_hash
        _, policy_digest = build_effective_policy(
            source_head=source_head,
            runtime_identity=self._runtime_identity,
            risk_profile=self._risk_profile,
            expected_leverage=self._expected_leverage,
            account_identity_hash_value=account_hash,
            instrument_id=OKX_DEMO_INSTRUMENT_ID,
            margin_mode="isolated",
            order_contracts=OKX_DEMO_PAPER_CONTRACTS,
            max_net_contracts=OKX_DEMO_PAPER_MAX_NET_CONTRACTS,
            max_notional_usdt=OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
            protection_policy=OKX_DEMO_APPROVED_PROTECTION_POLICY,
        )
        return {
            "runtime_identity": self._runtime_identity,
            "source_head": source_head,
            "effective_policy_digest": policy_digest,
            "risk_profile": self._risk_profile,
            "expected_leverage": self._expected_leverage,
            "account_identity_hash": account_hash,
        }

    def account_identity_projection(self) -> dict[str, str]:
        """Expose only the redacted account identity provenance."""

        return {
            "hash": str(self._account_identity_hash or ""),
            "source": str(self._account_identity_source or ""),
            "captured_at_utc": str(self._account_identity_captured_at_utc or ""),
        }

    def _set_authoritative_account_identity(
        self,
        projection: Mapping[str, Any] | None,
        *,
        clear_on_missing: bool = True,
    ) -> None:
        """Install a validated account-config identity projection only."""

        candidate = _mapping(projection)
        digest = str(candidate.get("hash") or "").strip().lower()
        source = str(candidate.get("source") or "").strip()
        captured = str(candidate.get("captured_at_utc") or "").strip()
        valid = (
            is_authoritative_account_identity_hash(digest)
            and source == ACCOUNT_IDENTITY_HASH_SOURCE
            and bool(captured)
        )
        if valid:
            self._account_identity_hash = digest
            self._account_identity_source = source
            self._account_identity_captured_at_utc = captured
        elif clear_on_missing:
            self._account_identity_hash = ""
            self._account_identity_source = ""
            self._account_identity_captured_at_utc = ""

    def _require_authoritative_account_identity(self) -> str:
        if not is_authoritative_account_identity_hash(self._account_identity_hash):
            raise OkxDemoPaperRuntimeError(
                "btc_demo_authoritative_account_identity_hash_missing"
            )
        if self._account_identity_source != ACCOUNT_IDENTITY_HASH_SOURCE:
            raise OkxDemoPaperRuntimeError(
                "btc_demo_authoritative_account_identity_hash_missing"
            )
        return self._account_identity_hash

    def _source_head_for_account_facts(self) -> str:
        return _repo_head(self.config.repo_root)

    @_runtime_writer_operation
    def register_reviewed_account_drawdown_baseline(
        self,
        *,
        approval_id: str,
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one externally reviewed, account-wide flat baseline.

        This is an offline local operation.  It neither creates a private
        client nor starts Demo execution, and it cannot accept approval fields
        embedded in the supplied snapshot.
        """

        resolver = self.config.account_facts_approval_resolver
        if resolver is None:
            raise AccountRiskFactError("approval_resolver_missing")
        if not self.config.account_facts_approval_id:
            raise AccountRiskFactError("approval_id_not_server_configured")
        if str(approval_id or "") != self.config.account_facts_approval_id:
            raise AccountRiskFactError("approval_id_mismatch")
        if not isinstance(snapshot, Mapping):
            raise AccountRiskFactError("baseline_snapshot_invalid")
        forbidden = {
            "authority",
            "approved",
            "approval",
            "review_receipt",
            "complete",
        }
        if forbidden.intersection(str(key) for key in snapshot):
            raise AccountRiskFactError("snapshot_self_approval_forbidden")
        resolved = resolver(str(approval_id or ""))
        if not isinstance(resolved, Mapping):
            raise AccountRiskFactError("approval_not_found_or_ambiguous")
        approval = validate_reviewed_account_facts_approval(resolved)
        if approval.get("approval_id") != str(approval_id or ""):
            raise AccountRiskFactError("approval_id_mismatch")

        source_head = self._source_head_for_account_facts()
        if approval.get("source_head") != source_head:
            raise AccountRiskFactError("approval_source_head_mismatch")
        if approval.get("runtime_identity") != self._runtime_identity:
            raise AccountRiskFactError("approval_runtime_identity_mismatch")
        snapshot_hash = canonical_ledger_snapshot_sha256(snapshot)
        if approval.get("snapshot_sha256") != snapshot_hash:
            raise AccountRiskFactError("approval_snapshot_sha256_mismatch")
        captured_at = str(snapshot.get("captured_at_utc") or "")
        captured_time = _parse_utc(captured_at)
        approved_time = _parse_utc(approval.get("observed_at_utc"))
        if captured_time is None or approved_time is None:
            raise AccountRiskFactError("approval_observed_at_utc_mismatch")
        captured_iso = _iso(captured_time)
        approved_iso = _iso(approved_time)
        if approved_iso != captured_iso:
            raise AccountRiskFactError("approval_observed_at_utc_mismatch")
        reference_time = self._clock().astimezone(timezone.utc)
        observation_age_seconds = (reference_time - captured_time).total_seconds()
        if observation_age_seconds < 0:
            raise AccountRiskFactError("baseline_observation_from_future")
        if observation_age_seconds > ACCOUNT_FACTS_BASELINE_FRESHNESS_TTL_SECONDS:
            raise AccountRiskFactError("baseline_observation_stale")
        reviewed_time = _parse_utc(approval.get("reviewed_at_utc"))
        if reviewed_time is None or reviewed_time < captured_time:
            raise AccountRiskFactError("approval_reviewed_at_utc_invalid")
        if reviewed_time > reference_time:
            raise AccountRiskFactError("approval_reviewed_at_utc_from_future")
        account = _mapping(snapshot.get("account"))
        identity = _mapping(account.get("identity"))
        account_hash = str(identity.get("hash") or "").lower()
        if (
            account_hash != approval.get("account_identity_hash")
            or identity.get("source") != ACCOUNT_IDENTITY_HASH_SOURCE
        ):
            raise AccountRiskFactError("approval_account_identity_hash_mismatch")
        if approval.get("account_scope") != ACCOUNT_DRAWDOWN_SCOPE:
            raise AccountRiskFactError("approval_account_scope_mismatch")
        if approval.get("currency") != "USDT":
            raise AccountRiskFactError("approval_currency_mismatch")
        balance = _mapping(snapshot.get("balance"))
        try:
            snapshot_equity = Decimal(str(balance.get("equity_usdt")))
            approved_equity = Decimal(str(approval.get("equity_usdt")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AccountRiskFactError("approval_equity_usdt_mismatch") from exc
        if (
            not snapshot_equity.is_finite()
            or snapshot_equity <= 0
            or snapshot_equity != approved_equity
        ):
            raise AccountRiskFactError("approval_equity_usdt_mismatch")

        positions = snapshot.get("positions")
        if not isinstance(positions, Sequence) or isinstance(positions, (str, bytes)):
            raise AccountRiskFactError("baseline_positions_invalid")
        for value in positions:
            if not isinstance(value, Mapping):
                raise AccountRiskFactError("baseline_positions_invalid")
            raw = value.get("contracts") if "contracts" in value else value.get("pos")
            try:
                contracts = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise AccountRiskFactError("baseline_positions_invalid") from exc
            if not contracts.is_finite() or contracts != 0:
                raise AccountRiskFactError("baseline_account_not_flat")
        for field, error in (
            ("pending_orders", "baseline_pending_orders_present"),
            ("pending_algo_orders", "baseline_pending_algo_orders_present"),
        ):
            rows = snapshot.get(field)
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                raise AccountRiskFactError(f"{field}_invalid")
            if rows:
                raise AccountRiskFactError(error)
        pending_intents = _mapping(
            _mapping(self._state.get("risk_control")).get("pending_order_intents")
        )
        if pending_intents:
            raise AccountRiskFactError("baseline_pending_order_intents_present")
        runtime = _mapping(self._state.get("runtime"))
        if runtime.get("active") is True or (
            self._thread is not None and self._thread.is_alive()
        ):
            raise AccountRiskFactError("baseline_registration_requires_stopped_runtime")

        existing_fact = _mapping(self._state.get("account_risk_facts"))
        existing_approval = _mapping(self._state.get("account_facts_approval"))
        if existing_fact.get("risk_eligible") is True:
            if (
                existing_approval.get("approval_digest")
                == approval.get("approval_digest")
                and existing_fact.get("snapshot_sha256") == snapshot_hash
            ):
                return {
                    "status": "already_registered",
                    "account_drawdown_fact": dict(existing_fact),
                    "reviewed_approval": dict(existing_approval),
                    "safety_flags_changed": False,
                }
            raise AccountRiskFactError("baseline_already_registered")

        recovery = self._runtime_store.recover()
        if recovery.blockers:
            raise AccountRiskFactError(
                "baseline_runtime_recovery_blocked:" + ",".join(recovery.blockers)
            )
        baseline = build_explicit_account_drawdown_baseline(
            authority=approval.get("baseline_authority"),
            account_identity_hash=account_hash,
            account_scope=approval.get("account_scope"),
            currency=approval.get("currency"),
            snapshot_sha256=snapshot_hash,
            observed_at_utc=captured_iso,
            equity_usdt=str(snapshot_equity),
            history_complete=False,
            baseline_event_sequence=recovery.last_sequence + 1,
        )
        persisted_approval = {
            key: json.loads(json.dumps(value, default=str))
            for key, value in approval.items()
        }
        state_after = self._durable_state_snapshot()
        state_after["account_risk_facts"] = dict(baseline)
        state_after["account_risk_last_valid_fact"] = dict(baseline)
        state_after["account_facts_approval"] = dict(persisted_approval)
        state_after["reviewed_drawdown_policy"] = dict(
            approval["drawdown_policy"]
        )
        event = self._runtime_store.append(
            event_type="account_drawdown_baseline_registered",
            payload={
                "account_drawdown_fact": dict(baseline),
                "reviewed_approval": dict(persisted_approval),
                "history_scope": "since_reviewed_baseline_not_full_account_history",
                "account_wide_flatness_reviewed": True,
                "trading_permission_changed": False,
            },
            state_after=state_after,
            idempotency_key=(
                f"account-baseline:{approval['approval_id']}:{snapshot_hash}"
            ),
            timestamp_utc=_iso(self._clock()),
            run_id=str(runtime.get("run_id") or ""),
            safety=dict(self._state["safety"]),
        )
        self._state["account_risk_facts"] = dict(baseline)
        self._state["account_risk_last_valid_fact"] = dict(baseline)
        self._state["account_facts_approval"] = dict(persisted_approval)
        self._state["reviewed_drawdown_policy"] = dict(
            approval["drawdown_policy"]
        )
        self._state["events"] = [event, *self._state["events"]][:100]
        self._persist_state()
        return {
            "status": "registered_since_reviewed_baseline",
            "account_drawdown_fact": dict(baseline),
            "reviewed_approval": dict(persisted_approval),
            "safety_flags_changed": False,
        }

    def _historicalize_current_start_operation_if_identity_changed(self) -> None:
        """Keep account changes out of the current inner attempt projection."""

        runtime = self._state.get("runtime", {})
        operation = _mapping(runtime.get("start_operation"))
        if not operation.get("operation_id"):
            return
        current = self.current_start_attempt_identity()
        actual = (
            str(operation.get("runtime_identity") or ""),
            str(operation.get("source_head") or ""),
            str(operation.get("effective_policy_digest") or ""),
            str(operation.get("risk_profile") or ""),
            str(operation.get("expected_leverage") or ""),
            str(operation.get("account_identity_hash") or ""),
        )
        expected = (
            current["runtime_identity"],
            current["source_head"],
            current["effective_policy_digest"],
            current["risk_profile"],
            current["expected_leverage"],
            current["account_identity_hash"],
        )
        if actual == expected and not operation.get("historical"):
            return
        reasons = list(operation.get("historical_reason_codes") or [])
        labels = (
            "runtime_identity_changed",
            "source_head_changed",
            "effective_policy_digest_changed",
            "risk_profile_changed",
            "expected_leverage_changed",
            "account_identity_changed",
        )
        for left, right, label in zip(actual, expected, labels):
            if left != right:
                reasons.append(label)
        historical = json.loads(json.dumps(dict(operation)))
        historical["current_attempt"] = False
        historical["historical"] = True
        historical["historical_reason_codes"] = list(dict.fromkeys(reasons))
        nested = dict(_mapping(historical.get("start_attempt")))
        if nested:
            nested.update(
                {
                    "current_attempt": False,
                    "historical": True,
                    "historical_reason_codes": historical["historical_reason_codes"],
                }
            )
            historical["start_attempt"] = nested
        history = list(runtime.get("start_operation_history") or [])
        if not any(
            str(row.get("operation_id") or "") == str(historical.get("operation_id") or "")
            for row in history
            if isinstance(row, Mapping)
        ):
            history.append(historical)
        runtime["start_operation_history"] = history[-32:]
        runtime["start_operation"] = historical

    def _filter_recovered_policy_blockers(
        self,
        blockers: Sequence[Any],
    ) -> list[str]:
        """Do not project a prior policy's exact-leverage failure as current.

        The generic restart/cancel-only blocker is intentionally retained.  A
        leverage-specific blocker is current only when it names the serving
        profile's configured isolated leverage.
        """

        if isinstance(blockers, (str, bytes)):
            blockers = [blockers]
        current_code = leverage_blocker_code(
            self.config.max_configured_leverage,
            prefix="okx_demo_paper",
        )
        filtered: list[str] = []
        for value in blockers:
            code = str(value or "")
            if (
                code == "btc_demo_authoritative_account_identity_hash_missing"
                and is_authoritative_account_identity_hash(self._account_identity_hash)
            ):
                continue
            if (
                code.startswith("okx_demo_paper_exact_isolated_")
                and code.endswith("_leverage_required")
                and code != current_code
            ):
                continue
            if code:
                filtered.append(code)
        return list(dict.fromkeys(filtered))

    @staticmethod
    def _historical_start_operation_blockers(
        operation: Mapping[str, Any],
    ) -> set[str]:
        """Return only blockers durably owned by a prior start operation.

        Restart recovery must not erase independent account/ledger/safety
        facts.  The exact operation blocker, terminal error, and incident code
        are the only values that can be proven to belong to the historical
        start attempt and therefore may be removed from serving projections.
        """

        if not operation:
            return set()
        values: list[Any] = [
            *list(operation.get("blockers") or []),
            operation.get("terminal_error"),
            _mapping(operation.get("incident")).get("code"),
            *list(_mapping(operation.get("start_attempt")).get("blockers") or []),
            _mapping(operation.get("start_attempt")).get("terminal_error"),
        ]
        return {
            str(value).strip()
            for value in values
            if str(value or "").strip()
        }

    @staticmethod
    def _drop_historical_start_operation_blockers(
        blockers: Sequence[Any],
        historical_blockers: set[str],
    ) -> list[str]:
        if isinstance(blockers, (str, bytes)):
            blockers = [blockers]
        return list(
            dict.fromkeys(
                str(value).strip()
                for value in blockers
                if str(value or "").strip()
                and str(value).strip() not in historical_blockers
            )
        )

    @staticmethod
    def _local_start_capability() -> Mapping[str, Any]:
        """Check only local runtime modules; never reads credentials or secrets."""

        if importlib.util.find_spec("keyring") is None:
            return {
                "ready": False,
                "incident_category": "local_environment",
                "blockers": ["python_keyring_not_installed"],
            }
        try:
            import keyring  # type: ignore[import-not-found]

            backend = keyring.get_keyring()
            backend_type = type(backend)
            backend_identity = f"{backend_type.__module__}.{backend_type.__name__}"
        except Exception:
            return {
                "ready": False,
                "incident_category": "local_environment",
                "blockers": ["windows_keyring_backend_unavailable"],
            }
        if os.name == "nt" and not backend_identity.startswith("keyring.backends.Windows."):
            return {
                "ready": False,
                "incident_category": "local_environment",
                "blockers": ["windows_keyring_backend_required"],
            }
        return {
            "ready": True,
            "incident_category": "none",
            "blockers": [],
        }

    @staticmethod
    def _start_operation_is_active(operation: Mapping[str, Any]) -> bool:
        return str(operation.get("state") or "") in {"queued", "running"}

    @_runtime_writer_operation
    def _start_operation_phase(
        self,
        phase: str,
        *,
        state: str | None = None,
        blockers: Sequence[str] | None = None,
        incident_category: str | None = None,
        terminal_error: str = "",
    ) -> None:
        """Persist a monotonic start-operation phase before exposing it."""

        with self._lock:
            operation = _mapping(
                self._state.get("runtime", {}).get("start_operation")
            )
            if not operation.get("operation_id"):
                return
            current_state = str(operation.get("state") or "")
            if current_state in {"completed", "blocked", "interrupted", "timed_out"}:
                return
            deadline_text = str(operation.get("deadline_utc") or "")
            try:
                deadline = datetime.fromisoformat(deadline_text)
            except (TypeError, ValueError):
                deadline = None
            if deadline is not None and self._clock() >= deadline:
                phase = "timed_out"
                state = "timed_out"
                terminal_error = terminal_error or "okx_demo_start_operation_deadline_exceeded"
                blockers = list(blockers or []) or [terminal_error]
                incident_category = incident_category or "runtime_fault"
            phase_order = {
                "requested": 0,
                "local_runtime_check": 1,
                "credentials_demo_identity": 2,
                "account_positions_orders_oco": 3,
                "ledger": 4,
                "private_ws": 5,
                "broker_truth": 6,
                "dead_man": 7,
                "worker": 8,
                "running": 9,
            }
            current_phase = str(operation.get("phase") or "requested")
            if (
                current_phase in phase_order
                and phase in phase_order
                and phase_order[phase] < phase_order[current_phase]
            ):
                return
            previous_revision = int(operation.get("revision") or 0)
            operation = dict(operation)
            operation["phase"] = phase
            operation["state"] = state or (
                "running" if phase not in {"completed", "blocked", "interrupted", "timed_out"} else phase
            )
            operation["revision"] = previous_revision + 1
            operation["updated_at_utc"] = _iso(self._clock())
            if blockers is not None:
                operation["blockers"] = list(dict.fromkeys(str(item) for item in blockers if str(item)))
            if incident_category is not None:
                operation["incident"] = {
                    "category": incident_category,
                    "code": terminal_error or (operation.get("incident") or {}).get("code", ""),
                }
            if terminal_error:
                operation["terminal_error"] = terminal_error
            operation["worker_generation"] = int(
                self._state.get("runtime", {}).get("worker_generation") or 0
            )
            operation["current_attempt"] = not bool(operation.get("historical"))
            operation["historical"] = bool(operation.get("historical"))
            operation["start_attempt"] = {
                **_mapping(operation.get("start_attempt")),
                "state": operation["state"],
                "phase": operation["phase"],
                "updated_at_utc": operation["updated_at_utc"],
                "current_attempt": operation["current_attempt"],
                "historical": operation["historical"],
                "historical_reason_codes": list(operation.get("historical_reason_codes") or []),
            }
            self._state["runtime"]["start_operation"] = operation
            if operation["state"] in {"blocked", "interrupted", "timed_out"}:
                blocker_rows = list(operation.get("blockers") or [])
                terminal_reason = str(
                    operation.get("terminal_error")
                    or (blocker_rows[0] if blocker_rows else "okx_demo_start_operation_failed")
                )
                self._state["runtime"].update(
                    {
                        "active": False,
                        "opening_allowed": False,
                        "cancel_only": True,
                        "status": "unclean_restart_fail_closed"
                        if operation["state"] == "interrupted"
                        else "start_blocked_fail_closed",
                        "worker_alive": False,
                        "last_error": terminal_reason,
                        "blockers": blocker_rows,
                    }
                )
                self._set_risk_mode(OKX_DEMO_RISK_MODE_FROZEN, terminal_reason)
            self._append_event(
                "start_operation_phase",
                {
                    "operation_id": operation["operation_id"],
                    "attempt_id": operation["attempt_id"],
                    "phase": operation["phase"],
                    "state": operation["state"],
                    "revision": operation["revision"],
                    "blockers": operation.get("blockers", []),
                    "incident": operation.get("incident", {}),
                    "terminal_error": operation.get("terminal_error", ""),
                },
            )
            self._persist_state()

    def _recover_start_operation_after_restart(self) -> None:
        with self._lock:
            operation = _mapping(
                self._state.get("runtime", {}).get("start_operation")
            )
            if not self._start_operation_is_active(operation):
                return
        acquired_here = self._ensure_runtime_writer_lock(
            nonce=self._default_writer_lock_nonce
        )
        with self._lock:
            operation = _mapping(
                self._state.get("runtime", {}).get("start_operation")
            )
            if not self._start_operation_is_active(operation):
                if acquired_here:
                    self.release_fault_drill_process_lock()
                return
            try:
                operation_id = str(operation.get("operation_id") or "")
                self._state["runtime"]["start_operation"] = {
                    **dict(operation),
                    "state": "interrupted",
                    "phase": "interrupted_fail_closed",
                    "revision": int(operation.get("revision") or 0) + 1,
                    "updated_at_utc": _iso(self._clock()),
                    "incident": {
                        "category": "local_environment",
                        "code": "okx_demo_start_operation_interrupted_on_restart",
                    },
                    "blockers": ["okx_demo_start_operation_interrupted_on_restart"],
                    "terminal_error": "okx_demo_start_operation_interrupted_on_restart",
                    "current_attempt": False,
                    "historical": True,
                    "historical_reason_codes": list(
                        dict.fromkeys(
                            [
                                *list(operation.get("historical_reason_codes") or []),
                                "runtime_identity_changed",
                                "owner_pid_changed",
                                *(
                                    ["source_head_changed"]
                                    if str(operation.get("source_head") or "")
                                    and str(operation.get("source_head") or "") != _repo_head(self.config.repo_root)
                                    else []
                                ),
                            ]
                        )
                    ),
                }
                self._state["runtime"]["start_operation"]["start_attempt"] = {
                    **_mapping(operation.get("start_attempt")),
                    "state": "interrupted",
                    "phase": "interrupted_fail_closed",
                    "updated_at_utc": _iso(self._clock()),
                    "current_attempt": False,
                    "historical": True,
                    "historical_reason_codes": self._state["runtime"]["start_operation"]["historical_reason_codes"],
                }
                history = list(
                    self._state["runtime"].get("start_operation_history") or []
                )
                for index, historical in enumerate(history):
                    if str(historical.get("operation_id") or "") != operation_id:
                        continue
                    history[index] = {
                        **dict(historical),
                        "state": "interrupted",
                        "phase": "interrupted_fail_closed",
                        "updated_at_utc": self._state["runtime"]["start_operation"]["updated_at_utc"],
                        "current_attempt": False,
                        "historical": True,
                        "historical_reason_codes": self._state["runtime"]["start_operation"]["historical_reason_codes"],
                        "start_attempt": {
                            **_mapping(historical.get("start_attempt")),
                            "state": "interrupted",
                            "phase": "interrupted_fail_closed",
                            "updated_at_utc": self._state["runtime"]["start_operation"]["updated_at_utc"],
                            "current_attempt": False,
                            "historical": True,
                            "historical_reason_codes": self._state["runtime"]["start_operation"]["historical_reason_codes"],
                        },
                    }
                    break
                self._state["runtime"]["start_operation_history"] = history[-32:]
                self._state["runtime"].update(
                    {
                        "active": False,
                        "opening_allowed": False,
                        "cancel_only": True,
                        "status": "unclean_restart_fail_closed",
                        "worker_alive": False,
                    }
                )
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_FROZEN,
                    "okx_demo_start_operation_interrupted_on_restart",
                )
                self._append_event(
                    "start_operation_interrupted",
                    {
                        "operation_id": operation_id,
                        "attempt_id": operation.get("attempt_id", ""),
                        "reason": "process_restart",
                    },
                )
                self._persist_state()
            finally:
                if acquired_here:
                    self.release_fault_drill_process_lock()

    @_runtime_writer_operation
    def _create_start_operation(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        with self._lock:
            runtime = self._state["runtime"]
            existing = _mapping(runtime.get("start_operation"))
            if existing.get("operation_id"):
                same_key = str(existing.get("idempotency_key") or "") == idempotency_key
                if same_key:
                    if (
                        str(existing.get("request_fingerprint") or "")
                        and str(existing.get("request_fingerprint")) != request_fingerprint
                    ):
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_start_operation_idempotency_key_reuse_mismatch"
                        )
                    return json.loads(json.dumps(dict(existing)))
                if self._start_operation_is_active(existing) or runtime.get("active") is True:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_start_operation_conflict"
                    )
            if runtime.get("active") is True:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_runtime_already_active"
                )
            now = _iso(self._clock())
            operation = {
                "schema_version": START_ATTEMPT_SCHEMA_VERSION,
                "operation_id": uuid.uuid4().hex,
                "attempt_id": uuid.uuid4().hex,
                "parent_operation_id": str(payload.get("parent_operation_id") or "direct-start"),
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "state": "queued",
                "phase": "requested",
                "revision": 1,
                "started_at_utc": now,
                "updated_at_utc": now,
                "deadline_utc": _iso(self._clock() + timedelta(seconds=300)),
                "source_head": _repo_head(self.config.repo_root),
                "runtime_identity": self._runtime_identity,
                "effective_policy_digest": str(payload.get("effective_policy_digest") or ""),
                "risk_profile": str(payload.get("risk_profile") or self._risk_profile),
                "expected_leverage": str(payload.get("expected_leverage") or self._expected_leverage),
                "account_identity_hash": str(payload.get("account_identity_hash") or self._account_identity_hash),
                "current_attempt": True,
                "historical": False,
                "historical_reason_codes": [],
                "actual_long_leverage": None,
                "actual_short_leverage": None,
                "owner": {
                    "pid": os.getpid(),
                    "nonce": uuid.uuid4().hex,
                    "create_time_utc": now,
                },
                "worker_generation": int(runtime.get("worker_generation") or 0),
                "incident": {"category": "none", "code": ""},
                "blockers": [],
                "terminal_error": "",
                "post_counts": {"orders": 0, "cancels": 0, "dead_man": 0},
            }
            if existing.get("operation_id"):
                historical = dict(existing)
                historical["current_attempt"] = False
                historical["historical"] = True
                historical["historical_reason_codes"] = list(
                    dict.fromkeys(
                        [
                            *list(existing.get("historical_reason_codes") or []),
                            "superseded_by_new_attempt",
                        ]
                    )
                )
                history = list(runtime.get("start_operation_history") or [])
                if not any(
                    str(row.get("operation_id") or "")
                    == str(historical.get("operation_id") or "")
                    for row in history
                    if isinstance(row, Mapping)
                ):
                    history.append(historical)
                runtime["start_operation_history"] = history[-32:]
            operation["start_attempt"] = {
                "schema_version": START_ATTEMPT_SCHEMA_VERSION,
                "parent_operation_id": operation["parent_operation_id"],
                "inner_operation_id": operation["operation_id"],
                "attempt_id": operation["attempt_id"],
                "runtime_identity": operation["runtime_identity"],
                "source_head": operation["source_head"],
                "effective_policy_digest": operation["effective_policy_digest"],
                "risk_profile": operation["risk_profile"],
                "expected_leverage": operation["expected_leverage"],
                "account_identity_hash": operation["account_identity_hash"],
                "created_at_utc": now,
                "updated_at_utc": now,
                "state": "queued",
                "phase": "requested",
                "current_attempt": True,
                "historical": False,
                "historical_reason_codes": [],
                "actual_long_leverage": None,
                "actual_short_leverage": None,
            }
            StartAttemptBinding(
                parent_operation_id=operation["parent_operation_id"],
                inner_operation_id=operation["operation_id"],
                attempt_id=operation["attempt_id"],
                runtime_identity=operation["runtime_identity"],
                source_head=operation["source_head"],
                effective_policy_digest=operation["effective_policy_digest"],
                risk_profile=operation["risk_profile"],
                expected_leverage=operation["expected_leverage"],
                account_identity_hash=operation["account_identity_hash"],
                created_at_utc=now,
                updated_at_utc=now,
            )
            runtime["start_operation"] = operation
            self._append_event(
                "start_operation_requested",
                {
                    "operation_id": operation["operation_id"],
                    "attempt_id": operation["attempt_id"],
                    "idempotency_key": idempotency_key,
                    "request_fingerprint": request_fingerprint,
                    "source_head": operation["source_head"],
                    "parent_operation_id": operation["parent_operation_id"],
                    "runtime_identity": operation["runtime_identity"],
                    "effective_policy_digest": operation["effective_policy_digest"],
                    "risk_profile": operation["risk_profile"],
                    "expected_leverage": operation["expected_leverage"],
                    "account_identity_hash": operation["account_identity_hash"],
                    "owner": operation["owner"],
                },
            )
            self._persist_state()
            return json.loads(json.dumps(operation))

    def _authoritative_start_payload(
        self,
        payload: Mapping[str, Any],
        *,
        parent_operation_id: str,
    ) -> dict[str, Any]:
        """Replace browser policy fields with the serving controller's facts."""

        account_hash = self._require_authoritative_account_identity()
        normalized = json.loads(json.dumps(dict(payload), default=str))
        normalized["parent_operation_id"] = str(parent_operation_id or "direct-start")
        normalized["runtime_identity"] = self._runtime_identity
        normalized["source_head"] = _repo_head(self.config.repo_root)
        normalized["risk_profile"] = self._risk_profile
        normalized["expected_leverage"] = self._expected_leverage
        normalized["account_identity_hash"] = account_hash
        policy, digest = build_effective_policy(
            source_head=normalized["source_head"],
            runtime_identity=self._runtime_identity,
            risk_profile=self._risk_profile,
            expected_leverage=self._expected_leverage,
            account_identity_hash_value=account_hash,
            instrument_id=str(normalized.get("instrument_id") or OKX_DEMO_INSTRUMENT_ID),
            margin_mode="isolated",
            order_contracts=normalized.get("order_contracts"),
            max_net_contracts=normalized.get("max_net_contracts"),
            max_notional_usdt=normalized.get("max_notional_usdt"),
            protection_policy=_mapping(normalized.get("server_side_protection_policy")),
        )
        normalized["effective_policy_digest"] = digest
        normalized["effective_policy"] = policy
        return normalized

    def _start_attempt_snapshot_binding_blockers(
        self,
        snapshot: Mapping[str, Any],
        request: OkxDemoPaperStartRequest,
    ) -> list[str]:
        """Reject fresh account/policy drift before enabling startup I/O."""

        expected_account_hash = str(request.account_identity_hash or "").strip().lower()
        expected_policy_digest = str(request.effective_policy_digest or "").strip().lower()
        if not expected_account_hash and not expected_policy_digest:
            # Direct legacy start calls have no immutable StartAttempt binding;
            # they remain governed by the ordinary structural preflight.
            return []

        account = _mapping(snapshot.get("account"))
        identity = _mapping(account.get("identity"))
        fresh_account_hash = str(identity.get("hash") or "").strip().lower()
        blockers: list[str] = []
        if fresh_account_hash != expected_account_hash:
            blockers.append(
                "btc_demo_start_attempt_account_identity_changed_during_preflight"
            )

        if expected_policy_digest and is_authoritative_account_identity_hash(
            fresh_account_hash
        ):
            try:
                _, current_policy_digest = build_effective_policy(
                    source_head=_repo_head(self.config.repo_root),
                    runtime_identity=self._runtime_identity,
                    risk_profile=self._risk_profile,
                    expected_leverage=self._expected_leverage,
                    account_identity_hash_value=fresh_account_hash,
                    instrument_id=OKX_DEMO_INSTRUMENT_ID,
                    margin_mode="isolated",
                    order_contracts=request.order_contracts,
                    max_net_contracts=request.max_net_contracts,
                    max_notional_usdt=request.max_notional_usdt,
                    protection_policy=request.server_side_protection_policy.to_dict(),
                )
            except Exception:
                current_policy_digest = ""
            if current_policy_digest != expected_policy_digest:
                blockers.append(
                    "btc_demo_start_attempt_effective_policy_changed_during_preflight"
                )
        elif expected_policy_digest:
            blockers.append(
                "btc_demo_start_attempt_effective_policy_changed_during_preflight"
            )
        return _dedupe(blockers)

    def start_operation(
        self,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        authoritative_payload = self._authoritative_start_payload(
            payload,
            parent_operation_id=str(payload.get("parent_operation_id") or "direct-start"),
        )
        request = OkxDemoPaperStartRequest.from_mapping(authoritative_payload)
        blockers = request.validate()
        if blockers:
            raise OkxDemoPaperRuntimeError(";".join(blockers))
        normalized_payload = authoritative_payload
        fingerprint = hashlib.sha256(
            json.dumps(normalized_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        operation = self._create_start_operation(
            normalized_payload,
            idempotency_key=str(idempotency_key or fingerprint),
            request_fingerprint=fingerprint,
        )
        if self._start_operation_is_active(operation) and operation.get("revision") == 1:
            capability = dict(self._start_capability_checker())
            if capability.get("ready") is not True:
                self._start_operation_phase(
                    "blocked",
                    state="blocked",
                    blockers=capability.get("blockers") or ["btc_demo_local_capability_unavailable"],
                    incident_category=str(capability.get("incident_category") or "local_environment"),
                    terminal_error=str((capability.get("blockers") or ["btc_demo_local_capability_unavailable"])[0]),
                )
            else:
                self._start_operation_phase("local_runtime_check")
                self._start_operation_thread = threading.Thread(
                    target=self._run_start_operation,
                    args=(normalized_payload, operation["operation_id"]),
                    name="btc-demo-start-operation",
                    daemon=True,
                )
                self._start_operation_thread.start()
        with self._lock:
            operation = json.loads(
                json.dumps(
                    _mapping(self._state.get("runtime", {}).get("start_operation"))
                )
            )
        return {
            "schema_version": "btc_demo_start_operation_v1",
            "accepted": True,
            "operation_id": operation["operation_id"],
            "attempt_id": operation["attempt_id"],
            "state": operation["state"],
            "phase": operation["phase"],
            "revision": operation["revision"],
            "status_url": "/api/research/btc/demo-paper/status",
            "start_operation": operation,
        }

    def _run_start_operation(
        self,
        payload: Mapping[str, Any],
        operation_id: str,
    ) -> None:
        self._start_operation_internal_id = operation_id
        try:
            self._start_operation_phase("local_runtime_check")
            self.start(payload)
            self._start_operation_phase("completed", state="completed")
        except Exception as exc:
            reason = _safe_error(exc)
            self._start_operation_phase(
                "blocked",
                state="blocked",
                blockers=[reason],
                incident_category=(
                    "local_environment"
                    if "python_keyring" in reason
                    else "runtime_fault"
                ),
                terminal_error=reason,
            )
        finally:
            self._start_operation_internal_id = ""

    def _cache_runtime_completed_chart_frame(
        self,
        frame: pd.DataFrame,
        *,
        evidence: Mapping[str, Any],
    ) -> None:
        required = {"open_time", "open", "high", "low", "close", "volume"}
        if frame.empty or not required.issubset(frame.columns):
            raise OkxDemoPaperRuntimeError(
                "btc_chart_runtime_completed_frame_invalid"
            )
        cached = frame[list(required)].copy().sort_index()
        if not isinstance(cached.index, pd.DatetimeIndex):
            raise OkxDemoPaperRuntimeError(
                "btc_chart_runtime_completed_frame_index_invalid"
            )
        if cached.index.tz is None:
            cached.index = cached.index.tz_localize("UTC")
        else:
            cached.index = cached.index.tz_convert("UTC")
        cutoff = pd.Timestamp(self._clock().astimezone(timezone.utc))
        if bool((cached.index > cutoff).any()):
            raise OkxDemoPaperRuntimeError(
                "btc_chart_runtime_unconfirmed_frame_rejected"
            )
        with self._lock:
            self._runtime_completed_chart_frame = cached
            self._runtime_completed_chart_evidence = json.loads(
                json.dumps(dict(evidence))
            )

    def readonly_chart_payload(
        self,
        *,
        limit: int = 1_000,
    ) -> dict[str, Any] | None:
        """Return only the in-memory confirmed 1h frame used by runtime."""

        with self._lock:
            frame = self._runtime_completed_chart_frame
            evidence = dict(self._runtime_completed_chart_evidence)
            if frame is None:
                return None
            copied = frame.copy()
        return _completed_okx_frame_chart_payload(
            copied,
            limit=limit,
            source_kind="okx_runtime_confirmed_completed_swap_1h",
            source_sha256=str(evidence.get("tail_sha256") or ""),
            tail_evidence=evidence,
        )

    @staticmethod
    def _is_canonical_incident_recovery_authorization(
        authorization: Mapping[str, Any],
    ) -> bool:
        """Identify the opaque binding path without widening legacy recovery."""

        return any(
            str(authorization.get(field) or "").strip()
            for field in (
                "recovery_binding_path",
                "recovery_binding_sha256",
                "recovery_runtime_root",
            )
        )

    def _incident_recovery_authorization_valid(
        self,
        authorization: Mapping[str, Any],
        *,
        already_flat: bool = False,
    ) -> bool:
        auth = {
            str(key): str(value or "") for key, value in authorization.items()
        }
        canonical_binding = self._is_canonical_incident_recovery_authorization(
            auth
        )
        try:
            current_head = _repo_head(self.config.repo_root)
        except Exception:
            return False
        canonical_heads_valid = (
            not canonical_binding
            or (
                not auth.get("incident_source_head")
                and not auth.get("recovery_code_head")
            )
            or (
                auth.get("recovery_code_head") == current_head
                and auth.get("incident_source_head")
                == auth.get("failed_receipt_source_head")
            )
        )
        head_valid = (
            auth.get("runtime_source_head") == current_head
            and canonical_heads_valid
        )
        identity_fields = (
            "failed_receipt_sha256",
            "failed_receipt_source_head",
            "failed_receipt_scenario",
            "failed_receipt_run_id",
            "opening_cl_ord_id",
            "opening_order_id",
            "opening_fill_id",
            "algo_cl_ord_id",
            "algo_id",
            "expected_close_cl_ord_id",
        )
        if (
            auth.get("authorization_ticket")
            != "BTC-OKX-DEMO-INCIDENT-RECOVERY-AND-RECEIPT-05"
            or not head_valid
            or not re.fullmatch(
                r"[0-9a-f]{64}", auth.get("failed_receipt_sha256", "")
            )
            or not re.fullmatch(
                r"[0-9a-f]{40}", auth.get("failed_receipt_source_head", "")
            )
            or any(not auth.get(field) for field in identity_fields)
        ):
            return False
        if already_flat:
            return (
                auth.get("recovery_mode") == "already_flat"
                and bool(
                    re.fullmatch(
                        r"[0-9a-f]{64}", auth.get("flat_identity_sha256", "")
                    )
                )
            )
        return True

    @staticmethod
    def _is_flat_hosted_exit_binding_authorization(
        authorization: Mapping[str, Any],
    ) -> bool:
        """Identify the separate immutable receipt-bundle admission only."""

        return (
            str(authorization.get("recovery_binding_schema_version") or "")
            == _FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION
            and str(authorization.get("recovery_binding_source") or "")
            == _FLAT_HOSTED_EXIT_BINDING_SOURCE
        )

    @staticmethod
    def _owner_marker_snapshot(raw: bytes) -> dict[str, Any]:
        marker: Mapping[str, Any] = {}
        valid = False
        try:
            decoded = json.loads(raw.decode("utf-8"))
            if isinstance(decoded, Mapping):
                marker = dict(decoded)
                valid = True
        except (UnicodeError, json.JSONDecodeError):
            marker = {}
        return {
            "raw": bytes(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "marker": dict(marker),
            "valid": valid,
        }

    def _capture_incident_recovery_preflight_snapshot(
        self,
        authorization: Mapping[str, Any],
    ) -> dict[str, Any]:
        root = Path(self.config.output_dir).resolve()
        binding_path = Path(
            str(authorization.get("recovery_binding_path") or "")
        ).resolve()
        lock_path = root / ".btc_okx_demo_fault_drill_writer.lock"
        state_path = root / "state.json"
        events_path = root / "events.jsonl"

        owner_raw = b""
        if lock_path.is_file():
            try:
                owner_raw = lock_path.read_bytes()
            except OSError:
                owner_raw = b""

        def file_sha(path: Path) -> str:
            try:
                return hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                return ""

        return {
            "root": str(root),
            "owner_marker_path": str(lock_path),
            "owner_marker": self._owner_marker_snapshot(owner_raw),
            "binding_path": str(binding_path),
            "binding_sha256": file_sha(binding_path),
            "state_sha256": file_sha(state_path),
            "events_sha256": file_sha(events_path),
            "events_file_missing": not events_path.exists(),
        }

    def _preflight_incident_recovery_binding(
        self,
        authorization: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate immutable evidence before acquiring or rewriting the lock."""

        auth = {
            str(key): str(value or "") for key, value in authorization.items()
        }
        if not self._incident_recovery_authorization_valid(
            auth,
            already_flat=auth.get("recovery_mode") == "already_flat",
        ):
            error = (
                "okx_demo_incident_recovery_flat_authorization_invalid"
                if auth.get("recovery_mode") == "already_flat"
                else "okx_demo_incident_recovery_authorization_invalid"
            )
            raise OkxDemoPaperRuntimeError(error)
        snapshot = self._capture_incident_recovery_preflight_snapshot(auth)
        blockers = self._incident_recovery_binding_blockers(
            auth,
            owner_marker_snapshot=snapshot["owner_marker"],
        )
        if blockers:
            raise OkxDemoPaperRuntimeError(";".join(blockers))
        if not (
            auth.get("recovery_mode") == "already_flat"
            and self._is_flat_hosted_exit_binding_authorization(auth)
        ):
            durable_blockers = (
                self._incident_recovery_flat_durable_identity_blockers(auth)
                if auth.get("recovery_mode") == "already_flat"
                else self._incident_recovery_durable_identity_blockers(auth)
            )
            if durable_blockers:
                raise OkxDemoPaperRuntimeError(";".join(durable_blockers))
        # Re-capture the byte hashes immediately before the OS lock.  The
        # locked path is compared byte-for-byte again by acquire().
        return self._capture_incident_recovery_preflight_snapshot(auth)

    def acquire_fault_drill_process_lock(
        self,
        *,
        nonce: str,
        writer_context: Mapping[str, Any] | None = None,
        preflight: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not nonce or len(nonce) > 96 or not nonce.isalnum():
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_lock_nonce_invalid"
            )
        flat_hosted_exit_binding = self._is_flat_hosted_exit_binding_authorization(
            _mapping(writer_context)
        )
        if self._fault_drill_lock_handle is not None:
            if self._fault_drill_lock_nonce != nonce:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_lock_already_held"
                )
            incident_source_head = str(
                _mapping(writer_context).get("incident_source_head") or ""
            )
            if incident_source_head:
                root = Path(self.config.output_dir).resolve()
                try:
                    self._fault_drill_lock_handle.seek(0)
                    existing = self._owner_marker_snapshot(
                        self._fault_drill_lock_handle.read()
                    )["marker"]
                    recovery_code_head = _repo_head(self.config.repo_root)
                except Exception as exc:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fault_drill_runtime_root_writer_lock_source_invalid"
                    ) from exc
                if not flat_hosted_exit_binding and (
                    not isinstance(existing, Mapping)
                    or existing.get("source_head") != incident_source_head
                    or existing.get("recovery_code_head")
                    not in {None, "", recovery_code_head}
                    or existing.get("runtime_root_sha256")
                    != _canonical_sha256(str(root))
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fault_drill_runtime_root_writer_lock_source_mismatch"
                    )
            return {
                "acquired": True,
                "nonce": nonce,
                "process_id": os.getpid(),
            }
        root = Path(self.config.output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        path = root / ".btc_okx_demo_fault_drill_writer.lock"
        handle = path.open("a+b")
        lock_placeholder_seeded_by_this_acquire = False
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
                lock_placeholder_seeded_by_this_acquire = True
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            incident_source_head = str(
                _mapping(writer_context).get("incident_source_head") or ""
            )
            try:
                recovery_code_head = _repo_head(self.config.repo_root)
            except Exception as exc:
                if incident_source_head:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fault_drill_runtime_recovery_head_unavailable"
                    ) from exc
                recovery_code_head = ""
            owner_marker_before_write: Mapping[str, Any] = {}
            owner_marker_before_write_raw = b""
            if incident_source_head:
                try:
                    handle.seek(0)
                    owner_marker_before_write_raw = handle.read()
                    owner_snapshot = self._owner_marker_snapshot(
                        owner_marker_before_write_raw
                    )
                    existing = _mapping(owner_snapshot["marker"])
                    owner_marker_before_write = dict(existing)
                except (UnicodeError, json.JSONDecodeError, OSError) as exc:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fault_drill_runtime_root_writer_lock_source_invalid"
                    ) from exc
                expected_owner = _mapping(
                    _mapping(preflight).get("owner_marker")
                ).get("marker")
                expected_owner_raw = _mapping(
                    _mapping(preflight).get("owner_marker")
                ).get("raw")
                flat_hosted_exit_empty_lock_bootstrap = (
                    flat_hosted_exit_binding
                    and preflight is not None
                    and lock_placeholder_seeded_by_this_acquire
                    and isinstance(expected_owner_raw, (bytes, bytearray))
                    and bytes(expected_owner_raw) == b""
                    and owner_marker_before_write_raw == b"\0"
                    and isinstance(expected_owner, Mapping)
                )
                retained_invalid_lock_placeholder = (
                    flat_hosted_exit_binding
                    and not lock_placeholder_seeded_by_this_acquire
                    and owner_marker_before_write_raw == b"\0"
                )
                if retained_invalid_lock_placeholder:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fault_drill_runtime_root_writer_lock_preflight_changed"
                    )
                if preflight is not None and (
                    not isinstance(expected_owner_raw, (bytes, bytearray))
                    or bytes(expected_owner_raw) != owner_marker_before_write_raw
                    or not isinstance(expected_owner, Mapping)
                ) and not flat_hosted_exit_empty_lock_bootstrap:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fault_drill_runtime_root_writer_lock_preflight_changed"
                    )
                if not flat_hosted_exit_binding and (
                    not isinstance(existing, Mapping)
                    or existing.get("source_head") != incident_source_head
                    or existing.get("runtime_root_sha256")
                    != _canonical_sha256(str(root))
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fault_drill_runtime_root_writer_lock_source_mismatch"
                    )
                if preflight is not None:
                    for field, filename in (
                        ("binding_sha256", str(_mapping(preflight).get("binding_path") or "")),
                        ("state_sha256", str(root / "state.json")),
                        ("events_sha256", str(root / "events.jsonl")),
                    ):
                        expected_hash = str(_mapping(preflight).get(field) or "")
                        actual_hash = (
                            hashlib.sha256(Path(filename).read_bytes()).hexdigest()
                            if Path(filename).is_file()
                            else ""
                        )
                        flat_hosted_exit_empty_state_bootstrap = (
                            field == "state_sha256"
                            and flat_hosted_exit_binding
                            and expected_hash == ""
                            and actual_hash == ""
                            and not Path(filename).exists()
                        )
                        if flat_hosted_exit_empty_state_bootstrap:
                            try:
                                recovered = BTCRuntimeStore(root).recover()
                            except Exception:
                                recovered = None
                            flat_hosted_exit_empty_state_bootstrap = bool(
                                recovered is not None
                                and not recovered.blockers
                                and not recovered.truncated_tail
                                and recovered.last_sequence == 0
                                and recovered.last_event_hash == ""
                            )
                        flat_hosted_exit_empty_event_chain_bootstrap = (
                            field == "events_sha256"
                            and flat_hosted_exit_binding
                            and preflight.get("events_file_missing") is True
                            and expected_hash == ""
                            and actual_hash == ""
                            and not Path(filename).exists()
                        )
                        if flat_hosted_exit_empty_event_chain_bootstrap:
                            try:
                                recovered = BTCRuntimeStore(root).recover()
                            except Exception:
                                recovered = None
                            flat_hosted_exit_empty_event_chain_bootstrap = bool(
                                recovered is not None
                                and not recovered.blockers
                                and not recovered.truncated_tail
                                and recovered.last_sequence == 0
                                and recovered.last_event_hash == ""
                        )
                        if (
                            not expected_hash or actual_hash != expected_hash
                        ) and not (
                            flat_hosted_exit_empty_state_bootstrap
                            or flat_hosted_exit_empty_event_chain_bootstrap
                        ):
                            raise OkxDemoPaperRuntimeError(
                                "okx_demo_fault_drill_runtime_root_writer_lock_preflight_changed"
                            )
                source_head = incident_source_head
            else:
                source_head = recovery_code_head
            metadata_values: dict[str, Any] = {
                "nonce": nonce,
                "process_id": os.getpid(),
                "process_create_time": (
                    _canonical_windows_process_create_time(os.getpid()) or ""
                ),
                "source_head": source_head,
                "recovery_code_head": recovery_code_head,
                "runtime_root_sha256": _canonical_sha256(str(root)),
            }
            if incident_source_head and owner_marker_before_write_raw:
                original_marker = dict(owner_marker_before_write)
                metadata_values["original_owner_marker_sha256"] = hashlib.sha256(
                    owner_marker_before_write_raw
                ).hexdigest()
                metadata_values["original_owner_marker"] = {
                    key: original_marker.get(key)
                    for key in (
                        "nonce",
                        "process_id",
                        "process_create_time",
                        "source_head",
                        "recovery_code_head",
                        "runtime_root_sha256",
                    )
                    if key in original_marker
                }
                metadata_values["original_owner_marker_source_head"] = str(
                    original_marker.get("source_head") or ""
                )
                metadata_values["original_owner_marker_recovery_code_head"] = str(
                    original_marker.get("recovery_code_head") or ""
                )
                metadata_values["original_owner_marker_runtime_root_sha256"] = str(
                    original_marker.get("runtime_root_sha256") or ""
                )
            metadata = json.dumps(
                metadata_values,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            handle.seek(0)
            handle.truncate()
            handle.write(metadata)
            handle.flush()
            os.fsync(handle.fileno())
        except OkxDemoPaperRuntimeError:
            handle.close()
            raise
        except Exception as exc:
            handle.close()
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_runtime_root_writer_lock_unavailable"
            ) from exc
        self._fault_drill_lock_handle = handle
        self._fault_drill_lock_nonce = nonce
        if preflight is not None:
            self._fault_drill_recovery_preflight = dict(preflight)
        if incident_source_head:
            self._fault_drill_owner_marker_session = {
                "raw": bytes(metadata),
                "sha256": hashlib.sha256(metadata).hexdigest(),
                "marker": dict(metadata_values),
            }
            if preflight is not None:
                self._fault_drill_owner_marker_preflight = dict(
                    _mapping(preflight).get("owner_marker") or {}
                )
        return {
            "acquired": True,
            "nonce": nonce,
            "process_id": os.getpid(),
            "process_create_time": str(
                metadata_values.get("process_create_time") or ""
            ),
            "runtime_root_sha256": _canonical_sha256(str(root)),
        }

    def _ensure_runtime_writer_lock(
        self,
        *,
        nonce: str,
        writer_context: Mapping[str, Any] | None = None,
        preflight: Mapping[str, Any] | None = None,
    ) -> bool:
        if self._fault_drill_lock_handle is not None:
            return False
        self.acquire_fault_drill_process_lock(
            nonce=nonce,
            writer_context=writer_context,
            preflight=preflight,
        )
        return True

    def release_fault_drill_process_lock(self) -> None:
        handle = self._fault_drill_lock_handle
        if handle is None:
            return
        try:
            preflight = self._fault_drill_recovery_preflight
            if (
                preflight is not None
                and not self._fault_drill_recovery_admission_passed
            ):
                owner = _mapping(preflight.get("owner_marker"))
                original_raw = owner.get("raw")
                if isinstance(original_raw, (bytes, bytearray)):
                    handle.seek(0)
                    handle.truncate()
                    handle.write(bytes(original_raw))
                    handle.flush()
                    os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._fault_drill_lock_handle = None
            self._fault_drill_lock_nonce = ""
            self._fault_drill_recovery_preflight = None
            self._fault_drill_owner_marker_preflight = None
            self._fault_drill_owner_marker_session = None
            self._fault_drill_recovery_admission_passed = False

    def _durable_state_snapshot(self) -> dict[str, Any]:
        durable = {
            key: value
            for key, value in self._state.items()
            if key != "events"
        }
        return json.loads(json.dumps(durable, default=str))

    @staticmethod
    def _status_event_projection(event: Mapping[str, Any]) -> dict[str, Any]:
        timestamp_utc = str(event.get("timestamp_utc") or "")
        event_type = str(event.get("event_type") or "")
        payload = json.loads(json.dumps(event.get("payload", {}), default=str))
        event_id = str(event.get("event_id") or event.get("event_hash") or "")
        if not event_id:
            stable_identity = {
                "sequence": event.get("sequence"),
                "idempotency_key": event.get("idempotency_key"),
                "run_id": event.get("run_id"),
                "timestamp_utc": timestamp_utc,
                "event_type": event_type,
                "payload": payload,
            }
            event_id = hashlib.sha256(
                json.dumps(
                    stable_identity,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
        return {
            "event_id": event_id,
            "timestamp_utc": timestamp_utc,
            "event_type": event_type,
            "payload": payload,
        }

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            operation = _mapping(
                self._state.get("runtime", {}).get("start_operation")
            )
            if (
                self._start_operation_is_active(operation)
                and str(operation.get("operation_id") or "")
                != self._start_operation_internal_id
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_start_operation_conflict"
                )
        request = OkxDemoPaperStartRequest.from_mapping(payload)
        blockers = request.validate()
        if blockers:
            raise OkxDemoPaperRuntimeError(";".join(blockers))
        return self._start_with_writer_lock(request)

    @_runtime_writer_session()
    def _start_with_writer_lock(
        self,
        request: OkxDemoPaperStartRequest,
    ) -> dict[str, Any]:
        with self._lock:
            if self._state["runtime"]["active"]:
                raise OkxDemoPaperRuntimeError("okx_demo_paper_runtime_already_active")
            active_operation = _mapping(
                self._state.get("runtime", {}).get("start_operation")
            )
            if (
                self._start_operation_is_active(active_operation)
                and str(active_operation.get("operation_id") or "")
                != self._start_operation_internal_id
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_start_operation_conflict"
                )
            if any(
                str(row.get("status") or "")
                in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
                for row in _mapping(
                    self._state.get("risk_control", {}).get(
                        "pending_order_intents"
                    )
                ).values()
                if isinstance(row, Mapping)
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_previous_ambiguous_order_requires_clordid_reconciliation"
                )
            self._stop_event.clear()
            run_id = uuid.uuid4().hex
            spec = btc_strategy_registry.get(request.strategy_id, request.candidate_id)
            previous_ledger_reconciliation = json.loads(
                json.dumps(self._state["ledger_reconciliation"])
            )
            previous_start_operation = json.loads(
                json.dumps(
                    _mapping(self._state["runtime"].get("start_operation"))
                )
            )
            self._state = self._initial_state()
            self._state["ledger_reconciliation"] = (
                previous_ledger_reconciliation
            )
            if previous_start_operation.get("operation_id"):
                self._state["runtime"]["start_operation"] = previous_start_operation
            self._state["runtime"].update(
                {
                    "run_id": run_id,
                    "status": "starting",
                    "started_at_utc": _iso(self._clock()),
                    "authorization_ticket": OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
                    "fault_drill_scenario": request.fault_drill_scenario,
                }
            )
            self._state["strategy"] = spec.identity()
            self._state["limits"].update(
                {
                    "order_contracts": _text(request.order_contracts),
                    "max_net_contracts": _text(request.max_net_contracts),
                    "max_notional_usdt": _text(request.max_notional_usdt),
                }
            )
            self._refresh_observation_projection_from_ledger()
            self._protection_policy = request.server_side_protection_policy
            self._state["risk_control"]["protection_policy"] = (
                request.server_side_protection_policy.to_dict()
            )
            self._state["risk_control"]["dead_man"]["tag"] = (
                request.dead_man_tag
            )
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_STARTUP,
                "startup_reconciliation_required",
            )
            self._append_event("start_requested", {"strategy": spec.identity(), "limits": dict(self._state["limits"])})
        self._start_operation_phase("local_runtime_check")
        client: OkxDemoClient | None = None
        private_ws: Any | None = None
        credentials: OkxDemoCredentials | None = None
        probe_diagnostics: list[dict[str, Any]] = []
        try:
            # This is deliberately before credential/client construction.  The
            # restore path is an offline evidence import only; invalid input
            # therefore cannot trigger even a read endpoint, and it never
            # changes any opening/order capability flag.
            self._apply_owned_id_restore(request)
            if spec.strategy_id == OKX_NATIVE_STRATEGY_LINE:
                load_completed_okx_native_hourly_frame(
                    self.config.repo_root,
                    now=self._clock(),
                    shared_manifest_git_spec=(
                        self.config.okx_native_shared_manifest_git_spec
                    ),
                    shared_data_root=self.config.okx_native_shared_data_root,
                    expected_dataset_id=(
                        self.config.okx_native_expected_dataset_id
                    ),
                    allow_stale_baseline=True,
                )
                with self._lock:
                    self._append_event(
                        "okx_native_signal_seed_validated",
                        {
                            "signal_emitted": False,
                            "public_tail_required": True,
                            "opening_allowed": False,
                        },
                    )
            elif spec.strategy_id != STABLE_STRATEGY_LINE:
                initial_signal = self._signal_decision(spec.identity())
                with self._lock:
                    self._state["signal"] = initial_signal
            client_config = OkxDemoClientConfig(
                credential_service=self.config.credential_service,
                allow_private_read=True,
                allow_demo_orders=True,
                allow_demo_cancels=True,
                authorization_ticket=(
                    "BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01"
                    if request.fault_drill_scenario == "partial_fill_disconnect"
                    else OKX_DEMO_PAPER_AUTHORIZATION_TICKET
                ),
                max_order_contracts=request.order_contracts,
                max_notional_usdt=request.max_notional_usdt,
                contract_value_btc=OKX_DEMO_PAPER_CONTRACT_VALUE_BTC,
                allow_partial_fill_opening=(
                    request.fault_drill_scenario == "partial_fill_disconnect"
                ),
            )
            self._start_operation_phase("credentials_demo_identity")
            credentials = self._credential_loader(self.config.credential_service)
            client = self._client_factory(client_config, credentials)
            # Demo starts must establish their confirmed completed-1h signal
            # data from the public OKX tail before *any* private account
            # snapshot.  The stable and native lines share the frozen signal
            # formula; the stable line must not fall back to the stale/local
            # Binance-era 1h source on the executable start path.
            if spec.strategy_id in {
                STABLE_STRATEGY_LINE,
                OKX_NATIVE_STRATEGY_LINE,
            }:
                initial_signal = self._signal_decision(
                    spec.identity(),
                    client=client,
                )
            self._start_operation_phase("account_positions_orders_oco")
            snapshot = self._collect_exchange_snapshot(client)
            blockers = self._preflight_blockers(snapshot, require_flat=True)
            binding_blockers = self._start_attempt_snapshot_binding_blockers(
                snapshot,
                request,
            )
            if binding_blockers:
                # Absorb the fresh snapshot before terminating the attempt so
                # the serving controller projects the new account identity and
                # historicalizes the old attempt.  No later ledger, Private
                # WS, dead-man, worker, or order capability is reached.
                with self._lock:
                    self._state["signal"] = initial_signal
                    self._apply_snapshot(snapshot)
                raise OkxDemoPaperRuntimeError(
                    ";".join(_dedupe([*binding_blockers, *blockers]))
                )
            if blockers:
                raise OkxDemoPaperRuntimeError(";".join(blockers))
            if spec.strategy_id not in {
                STABLE_STRATEGY_LINE,
                OKX_NATIVE_STRATEGY_LINE,
            }:
                initial_signal = self._signal_decision(
                    spec.identity(),
                    client=client,
                )
            with self._lock:
                self._state["signal"] = initial_signal
                self._apply_snapshot(snapshot)
                if (
                    self._state["runtime"].get("last_error")
                    == "okx_demo_runtime_data_budget_stop_reached"
                ):
                    raise OkxDemoPaperRuntimeError(
                        self._state["runtime"]["last_error"]
                        or "okx_demo_paper_start_snapshot_not_openable"
                    )
            self._start_operation_phase("ledger")
            self._commit_ledger_reconciliation(
                snapshot=snapshot,
                trigger="startup_reconciliation",
            )
            with self._lock:
                ledger_reconciliation = self._state[
                    "ledger_reconciliation"
                ]
                if (
                    ledger_reconciliation.get("status") != "reconciled"
                    or ledger_reconciliation.get(
                        "current_state_exchange_snapshot_match"
                    )
                    is not True
                    or ledger_reconciliation.get(
                        "funding_cashflow_reconciled"
                    )
                    is not True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_ledger_current_state_exchange_snapshot_mismatch"
                    )
            self._start_operation_phase("private_ws")
            private_ws = self._private_ws_factory(
                credentials=credentials,
                source_head=_repo_head(self.config.repo_root),
                runtime_version=OKX_DEMO_PAPER_RUNTIME_VERSION,
                snapshot_loader=lambda: self._collect_exchange_snapshot(client),
                owned_client_order_ids=lambda: tuple(
                    sorted(self._owned_client_order_ids)
                ),
                on_disconnect=self._on_private_ws_disconnect,
                on_reconciled=self._on_private_ws_reconciled,
                clock=self._clock,
            )
            private_ws_probe = private_ws.run_startup_reconnect_probe()
            raw_probe_diagnostics = private_ws_probe.get("probe_diagnostics")
            if isinstance(raw_probe_diagnostics, Sequence) and not isinstance(
                raw_probe_diagnostics,
                (str, bytes),
            ):
                raw_probe_diagnostics = [
                    {
                        **dict(row),
                        "reconciliation_blocker_codes": private_ws_probe.get(
                            "blockers"
                        ),
                    }
                    for row in raw_probe_diagnostics
                    if isinstance(row, Mapping)
                ]
            probe_diagnostics = _project_probe_diagnostics(
                raw_probe_diagnostics,
                credentials=credentials,
            )
            with self._lock:
                self._state["private_ws"]["probe_diagnostics"] = json.loads(
                    json.dumps(probe_diagnostics)
                )
                self._state["runtime"]["probe_diagnostics"] = json.loads(
                    json.dumps(probe_diagnostics)
                )
            if (
                private_ws_probe.get("opening_allowed_after_reconciliation")
                is not True
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_startup_reconnect_probe_failed"
                )
            with self._lock:
                self._client = client
                self._private_ws = private_ws
            private_ws.start_monitoring()

            # The reconnect probe may legitimately consume longer than the
            # execution boundary's 30-second observation window.  It also
            # proves a connected socket, but not a live listener.  Keep the
            # write path closed, start and verify the listener, then bind a
            # fresh REST snapshot and ledger UOW before the first permissioned
            # control action (dead-man).  Reusing the pre-probe snapshot here
            # makes a healthy slow startup deterministically fail closed.
            self._start_operation_phase("broker_truth")
            post_probe_snapshot = self._collect_exchange_snapshot(client)
            post_probe_blockers = self._preflight_blockers(
                post_probe_snapshot,
                require_flat=True,
            )
            if post_probe_blockers:
                raise OkxDemoPaperRuntimeError(
                    ";".join(post_probe_blockers)
                )
            self._commit_ledger_reconciliation(
                snapshot=post_probe_snapshot,
                trigger="startup_post_private_ws_reconciliation",
                apply_snapshot=True,
            )
            with self._lock:
                private_ws_generation = self._private_ws_generation
            if not hasattr(private_ws, "status"):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_monitoring_status_not_trusted"
                )
            current_private_ws = private_ws.status()
            with self._lock:
                if (
                    self._private_ws_generation != private_ws_generation
                    or not isinstance(current_private_ws, Mapping)
                    or current_private_ws.get("connected") is not True
                    or current_private_ws.get("listener_alive") is not True
                    or current_private_ws.get(
                        "opening_allowed_after_reconciliation"
                    )
                    is not True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_private_ws_monitoring_status_not_trusted"
                    )
                durable_private_ws = dict(private_ws_probe)
                durable_private_ws.update(dict(current_private_ws))
                durable_private_ws["controller_generation"] = (
                    self._private_ws_generation
                )
                self._state["private_ws"] = json.loads(
                    json.dumps(durable_private_ws)
                )
                ledger_reconciliation = self._state[
                    "ledger_reconciliation"
                ]
                if (
                    ledger_reconciliation.get("status") != "reconciled"
                    or ledger_reconciliation.get(
                        "current_state_exchange_snapshot_match"
                    )
                    is not True
                    or ledger_reconciliation.get(
                        "funding_cashflow_reconciled"
                    )
                    is not True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_ledger_startup_reconciliation_not_current"
                    )
                runtime = self._state["runtime"]
                runtime["authoritative_liveness_required"] = True
                runtime["authoritative_liveness_worker_required"] = bool(
                    self._start_worker
                )
                runtime["authoritative_liveness_epoch"] = (
                    int(runtime.get("authoritative_liveness_epoch") or 0) + 1
                )
                runtime["last_heartbeat_utc"] = _iso(self._clock())
            self._start_operation_phase("dead_man")
            self._arm_dead_man(client, trigger="startup")
            with self._lock:
                self._state["runtime"].update(
                    {
                        "active": True,
                        "status": "starting",
                        "opening_allowed": False,
                        "cancel_only": True,
                        "last_heartbeat_utc": _iso(self._clock()),
                        "last_error": "",
                    }
                )
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_RUNNING,
                    "startup_complete",
                )
                self._state["safety"]["okx_demo_private_read_enabled"] = True
                self._state["safety"]["okx_demo_order_capability_enabled"] = True
                self._state["safety"]["okx_demo_cancel_capability_enabled"] = True
                self._append_event(
                    "runtime_started",
                    {
                        "exchange": "OKX Demo",
                        "instrument": OKX_DEMO_INSTRUMENT_ID,
                    },
                )
                self._append_event(
                    "private_ws_startup_reconnect_probe",
                    private_ws_probe,
                )
                self._persist_state()
            self._start_operation_phase("worker")
            if self._start_worker and request.fault_drill_scenario != "partial_fill_disconnect":
                self._start_worker_thread(reason="startup")
            self._dead_man_thread = threading.Thread(
                target=self._dead_man_loop,
                name="btc-okx-demo-dead-man",
                daemon=True,
            )
            self._dead_man_thread.start()
            with self._lock:
                dead_man = self._state["risk_control"]["dead_man"]
                dead_man["heartbeat_thread_alive"] = bool(
                    self._dead_man_thread is not None
                    and self._dead_man_thread.is_alive()
                )
                dead_man["watchdog_renews_dead_man"] = True
                if not self._write_path_is_trusted():
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_authoritative_liveness_startup_untrusted"
                    )
                self._state["runtime"].update(
                    {
                        "status": "running",
                        "opening_allowed": True,
                        "cancel_only": False,
                    }
                )
                self._persist_state()
            self._start_operation_phase("running", state="completed")
            return self.status()
        except Exception as exc:
            cleanup_blockers = self._cleanup_failed_startup(
                client=client,
                private_ws=private_ws,
                credentials=credentials,
            )
            cleanup_blockers = [
                _safe_probe_text(
                    blocker,
                    credentials=credentials,
                    max_length=500,
                )
                for blocker in cleanup_blockers
            ]
            reason = _safe_error(exc, credentials=credentials)
            if cleanup_blockers:
                reason += ";" + ";".join(cleanup_blockers)
            if not probe_diagnostics:
                probe_diagnostics = _project_probe_diagnostics(
                    [
                        {
                            "stage": "connect",
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                            "protocol": {},
                            "subscription_progress": {},
                        }
                    ],
                    credentials=credentials,
                )
            with self._lock:
                self._client = None
                self._private_ws = None
                self._enter_cancel_only(reason, active=False)
                self._state["runtime"]["status"] = "start_blocked_fail_closed"
                self._state["private_ws"].update(
                    {
                        "status": "stopped_after_start_failure",
                        "connected": False,
                        "listener_alive": False,
                        "opening_allowed_after_reconciliation": False,
                        "probe_diagnostics": json.loads(
                            json.dumps(probe_diagnostics)
                        ),
                    }
                )
                self._state["runtime"]["probe_diagnostics"] = json.loads(
                    json.dumps(probe_diagnostics)
                )
                self._append_event(
                    "start_blocked",
                    {
                        "error": reason,
                        "probe_diagnostics": json.loads(
                            json.dumps(probe_diagnostics)
                        ),
                    },
                )
                self._persist_state()
            raise OkxDemoPaperRuntimeError(reason) from exc

    def _cleanup_failed_startup(
        self,
        *,
        client: OkxDemoClient | None,
        private_ws: Any | None,
        credentials: Any = None,
    ) -> list[str]:
        blockers: list[str] = []
        self._stop_event.set()
        if private_ws is not None:
            try:
                private_ws.stop()
            except Exception as exc:
                blockers.append(
                    "okx_demo_startup_private_ws_stop_failed:"
                    + _safe_error(exc, credentials=credentials)
                )
        for name, thread in (
            ("worker", self._thread),
            ("dead_man", self._dead_man_thread),
        ):
            if thread is None or thread is threading.current_thread():
                continue
            thread.join(5.0)
            if thread.is_alive():
                blockers.append(
                    f"okx_demo_startup_{name}_thread_join_timed_out"
                )
        with self._lock:
            armed = (
                self._state["risk_control"]["dead_man"].get("armed")
                is True
            )
        if armed:
            blockers.extend(
                self._disarm_dead_man_if_safe(
                    client,
                    stop_query_current=True,
                )
            )
        with self._lock:
            self._state["runtime"].update(
                {"active": False, "opening_allowed": False}
            )
            self._state["risk_control"]["dead_man"][
                "watchdog_renews_dead_man"
            ] = False
            self._state["safety"]["okx_demo_private_read_enabled"] = False
            self._state["safety"]["okx_demo_order_capability_enabled"] = False
            self._state["safety"]["okx_demo_cancel_capability_enabled"] = False
            self._thread = None
            self._dead_man_thread = None
        return _dedupe(blockers)

    def stop(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        confirmation = str((payload or {}).get("confirmation_text") or "")
        if confirmation != OKX_DEMO_PAPER_CONFIRMATION:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_confirmation_text_invalid")
        return self._stop_with_writer_lock()

    @_runtime_writer_stop
    def _stop_with_writer_lock(self) -> dict[str, Any]:
        self._stop_event.set()
        with self._lock:
            private_ws = self._private_ws
            worker_thread = self._thread
            dead_man_thread = self._dead_man_thread
        lifecycle_blockers: list[str] = []
        if private_ws is not None:
            try:
                stop_receipt = private_ws.stop()
                if (
                    isinstance(stop_receipt, Mapping)
                    and stop_receipt.get("listener_joined") is not True
                ):
                    lifecycle_blockers.append(
                        "okx_demo_private_ws_listener_not_joined"
                    )
            except Exception as exc:
                lifecycle_blockers.append(
                    "okx_demo_private_ws_stop_unknown:" + _safe_error(exc)
                )
        for name, thread in (
            ("worker", worker_thread),
            ("dead_man", dead_man_thread),
        ):
            if thread is None or thread is threading.current_thread():
                continue
            thread.join(5.0)
            if thread.is_alive():
                lifecycle_blockers.append(
                    f"okx_demo_{name}_thread_join_timed_out"
                )
        with self._execution_lock:
            with self._lock:
                client = self._client
                self._state["runtime"].update(
                    {
                        "active": False,
                        "opening_allowed": False,
                        "status": "stopping",
                        "stopped_at_utc": _iso(self._clock()),
                    }
                )
            cancelled, blockers = self._cancel_owned_pending(client)
            blockers.extend(lifecycle_blockers)
            stop_query_current = False
            if client is not None:
                try:
                    stop_snapshot = self._collect_exchange_snapshot(client)
                    if _gross_position_contracts(
                        stop_snapshot.get("positions", [])
                    ) == 0:
                        stop_snapshot, _ = self._cleanup_owned_flat_algos(
                            client,
                            snapshot=stop_snapshot,
                        )
                    with self._lock:
                        self._apply_snapshot(stop_snapshot)
                    self._commit_ledger_reconciliation(
                        snapshot=stop_snapshot,
                        trigger="runtime_stop_query_current",
                    )
                    stop_query_current = True
                except Exception as exc:
                    blockers.append(
                        "okx_demo_stop_query_current_unknown:"
                        f"{_safe_error(exc)}"
                    )
            blockers.extend(
                self._disarm_dead_man_if_safe(
                    client,
                    stop_query_current=stop_query_current,
                )
            )
            with self._lock:
                self._state["runtime"]["status"] = (
                    "stopped"
                    if not blockers
                    else "frozen_unknown_stop_incomplete"
                )
                self._state["runtime"]["blockers"] = _dedupe([*self._state["runtime"]["blockers"], *blockers])
                if blockers:
                    self._set_risk_mode(
                        OKX_DEMO_RISK_MODE_FROZEN,
                        "runtime_stop_not_proven_safe",
                    )
                self._state["safety"]["okx_demo_private_read_enabled"] = False
                self._state["safety"]["okx_demo_order_capability_enabled"] = False
                self._state["safety"]["okx_demo_cancel_capability_enabled"] = False
                self._state["risk_control"]["dead_man"][
                    "watchdog_renews_dead_man"
                ] = False
                self._state["private_ws"].update(
                    {
                        "status": "stopped",
                        "connected": False,
                        "listener_alive": False,
                        "opening_allowed_after_reconciliation": False,
                    }
                )
                self._append_event(
                    "runtime_stopped",
                    {
                        "position_policy": "positions_are_not_auto_closed_by_stop",
                        "cancelled_owned_orders": cancelled,
                        "blockers": blockers,
                        "clean_stop": not blockers,
                        "query_current_verified": stop_query_current,
                    },
                )
                self._client = None
                self._private_ws = None
                self._thread = None
                self._dead_man_thread = None
                self._persist_state()
                return self.status()

    @_runtime_writer_operation
    def stop_and_flatten(
        self,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Stop opening and perform one normal, evidence-bound flatten.

        This is deliberately separate from ``stop`` and from the frozen-state
        emergency exit.  It only operates on an already active, authenticated
        runtime session so the ordinary RuntimeSnapshot -> permission -> OMS
        boundary remains in force.  A second invocation is rejected after the
        durable one-shot marker is created, including an ambiguous first try.
        """

        confirmation = str((payload or {}).get("confirmation_text") or "")
        if confirmation != OKX_DEMO_STOP_AND_FLATTEN_CONFIRMATION:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_stop_and_flatten_confirmation_text_invalid"
            )
        with self._lock:
            runtime = _mapping(self._state.get("runtime"))
            marker = _mapping(runtime.get("stop_and_flatten"))
            if str(marker.get("status") or "not_attempted") != "not_attempted":
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_stop_and_flatten_already_attempted"
                )
            client = self._client
            private_ws = self._private_ws
            active = runtime.get("active") is True
            strategy = dict(self._state.get("strategy", {}))
            orders_before = int(runtime.get("orders_submitted") or 0)
            if not active or client is None or private_ws is None:
                reason = "okx_demo_stop_and_flatten_runtime_session_unavailable"
                marker.update(
                    {
                        "status": "blocked",
                        "last_error": reason,
                        "final_flat": False,
                        "completed_at_utc": _iso(self._clock()),
                    }
                )
                self._state["runtime"]["stop_and_flatten"] = dict(marker)
                self._enter_cancel_only(reason, active=active)
                self._append_safety_alert(reason)
                self._append_event(
                    "stop_and_flatten_blocked",
                    {"error": reason, "orders_posted": 0},
                )
                self._persist_state()
                raise OkxDemoPaperRuntimeError(reason)
            marker.update(
                {
                    "status": "preflight",
                    "started_at_utc": _iso(self._clock()),
                    "post_attempts": 0,
                    "client_order_id": "",
                    "final_flat": False,
                    "authority": "broker_rest_private_ws_ledger",
                    "opening_allowed": False,
                    "confirmation_verified": True,
                }
            )
            self._state["runtime"]["stop_and_flatten"] = dict(marker)
            self._state["runtime"].update(
                {"opening_allowed": False, "cancel_only": True}
            )
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_REDUCING,
                "operator_stop_and_flatten_preflight",
            )
            self._append_event(
                "stop_and_flatten_requested",
                {
                    "opening_allowed": False,
                    "cancel_only": True,
                    "position_policy": "one_equal_reduce_only_exit_after_fresh_reconciliation",
                    "retry_without_query_allowed": False,
                },
            )
            self._persist_state()

        try:
            # The normal reduction cycle owns fresh REST snapshot, ledger UOW,
            # dead-man and boundary-authorized reduce-only submission.  It is
            # intentionally invoked without emergency_exit so frozen-mode
            # bypasses are impossible here.
            self._run_risk_reduction_cycle(
                client,
                strategy=strategy,
                emergency_exit=False,
            )
            final_snapshot = self._collect_exchange_snapshot(client)
            if _gross_position_contracts(final_snapshot.get("positions", [])) != 0:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_stop_and_flatten_position_not_flat"
                )
            if final_snapshot.get("pending_orders"):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_stop_and_flatten_pending_order_present"
                )
            # Protection remains in place until the broker truth proves flat.
            final_snapshot, algo_cleanup = self._cleanup_owned_flat_algos(
                client,
                snapshot=final_snapshot,
            )
            with self._lock:
                self._apply_snapshot(final_snapshot)
            self._commit_ledger_reconciliation(
                snapshot=final_snapshot,
                trigger="stop_and_flatten_final_reconciliation",
            )
            with self._lock:
                ledger = _mapping(self._state.get("ledger_reconciliation"))
                if not (
                    ledger.get("status") == "reconciled"
                    and ledger.get("current_state_exchange_snapshot_match") is True
                    and ledger.get("funding_cashflow_reconciled") is True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_stop_and_flatten_ledger_not_current"
                    )

            disarm_blockers = self._disarm_dead_man_if_safe(
                client,
                stop_query_current=True,
            )
            if disarm_blockers:
                raise OkxDemoPaperRuntimeError(";".join(disarm_blockers))
            self._stop_event.set()
            stop_receipt = private_ws.stop()
            if isinstance(stop_receipt, Mapping) and stop_receipt.get(
                "listener_joined"
            ) is False:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_stop_and_flatten_private_ws_stop_failed"
                )
            for name, thread in (
                ("worker", self._thread),
                ("dead_man", self._dead_man_thread),
            ):
                if thread is None or thread is threading.current_thread():
                    continue
                thread.join(5.0)
                if thread.is_alive():
                    raise OkxDemoPaperRuntimeError(
                        f"okx_demo_stop_and_flatten_{name}_thread_join_timed_out"
                    )
            with self._lock:
                runtime = self._state["runtime"]
                marker = runtime["stop_and_flatten"]
                close_client_order_id = str(marker.get("client_order_id") or "")
                orders_after = int(runtime.get("orders_submitted") or 0)
                marker.update(
                    {
                        "status": "completed",
                        "final_flat": True,
                        "orders_posted": max(0, orders_after - orders_before),
                        "algo_cleanup": dict(algo_cleanup),
                        "ledger_reconciled": True,
                        "private_ws_reconciled": True,
                        "private_ws_stopped": True,
                        "completed_at_utc": _iso(self._clock()),
                    }
                )
                runtime.update(
                    {
                        "active": False,
                        "opening_allowed": False,
                        "cancel_only": True,
                        "status": "stopped_and_flattened",
                        "stopped_at_utc": _iso(self._clock()),
                        "last_error": "",
                    }
                )
                self._state["risk_control"]["write_path_trusted"] = False
                self._state["risk_control"]["dead_man"].update(
                    {"armed": False, "watchdog_renews_dead_man": False}
                )
                self._state["private_ws"].update(
                    {
                        "status": "stopped_after_stop_and_flatten",
                        "connected": False,
                        "listener_alive": False,
                        "opening_allowed_after_reconciliation": False,
                    }
                )
                self._state["safety"].update(
                    {
                        "okx_demo_private_read_enabled": False,
                        "okx_demo_order_capability_enabled": False,
                        "okx_demo_cancel_capability_enabled": False,
                    }
                )
                self._append_event(
                    "stop_and_flatten_completed",
                    {
                        "client_order_id": close_client_order_id,
                        "orders_posted": marker["orders_posted"],
                        "final_flat": True,
                        "algo_cleanup": dict(algo_cleanup),
                        "opening_allowed": False,
                        "live_allowed": False,
                    },
                )
                self._client = None
                self._private_ws = None
                self._thread = None
                self._dead_man_thread = None
                self._persist_state()
                return self.status()
        except Exception as exc:
            reason = _safe_error(exc)
            with self._lock:
                marker = self._state["runtime"].setdefault(
                    "stop_and_flatten", {}
                )
                marker.update(
                    {
                        "status": "blocked",
                        "last_error": reason,
                        "final_flat": False,
                        "completed_at_utc": _iso(self._clock()),
                        "orders_posted": int(marker.get("post_attempts") or 0),
                        "blind_retry_allowed": False,
                    }
                )
                self._enter_cancel_only(reason, active=True)
                self._append_safety_alert(reason)
                self._append_event(
                    "stop_and_flatten_blocked",
                    {
                        "error": reason,
                        "orders_posted": int(marker.get("post_attempts") or 0),
                        "blind_retry_allowed": False,
                        "opening_allowed": False,
                        "cancel_only": True,
                    },
                )
                self._persist_state()
            raise OkxDemoPaperRuntimeError(reason) from exc

    @_runtime_writer_operation
    def reconcile(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        confirmation = str((payload or {}).get("confirmation_text") or "")
        if confirmation != OKX_DEMO_PAPER_CONFIRMATION:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_confirmation_text_invalid")
        with self._lock:
            active_client = self._client
        try:
            client = active_client or self._read_only_client()
            snapshot = self._collect_exchange_snapshot(client)
            intent_blockers = self._reconcile_ambiguous_order_intents(
                client,
                snapshot,
            )
            blockers = _dedupe(
                [
                    *self._preflight_blockers(snapshot, require_flat=False),
                    *intent_blockers,
                ]
            )
            with self._lock:
                self._apply_snapshot(snapshot)
                if blockers:
                    self._enter_cancel_only(";".join(blockers), active=self._state["runtime"]["active"])
                self._append_event("manual_reconciliation", {"blockers": blockers})
                self._persist_state()
            self._commit_ledger_reconciliation(
                snapshot=snapshot,
                trigger="manual_reconciliation",
            )
            self._capture_completed_hour_receipt(
                snapshot=snapshot,
                decision=self._state.get("signal", {}),
            )
            return self.status()
        except Exception as exc:
            with self._lock:
                self._enter_cancel_only(_safe_error(exc), active=self._state["runtime"]["active"])
                self._append_event("manual_reconciliation_failed", {"error": _safe_error(exc)})
                self._persist_state()
            raise OkxDemoPaperRuntimeError(_safe_error(exc)) from exc

    @_runtime_writer_operation
    def enter_cancel_only(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        confirmation = str((payload or {}).get("confirmation_text") or "")
        if confirmation != "CANCEL ONLY":
            raise OkxDemoPaperRuntimeError("okx_demo_paper_cancel_only_confirmation_invalid")
        with self._lock:
            self._enter_cancel_only("operator_emergency_cancel_only", active=self._state["runtime"]["active"])
            client = self._client
        with self._execution_lock:
            cancelled, blockers = self._cancel_owned_pending(client)
        with self._lock:
            self._state["runtime"]["blockers"] = _dedupe([*self._state["runtime"]["blockers"], *blockers])
            self._append_event("cancel_only_applied", {"cancelled_owned_orders": cancelled, "blockers": blockers})
            self._persist_state()
            return self.status()

    def fault_drill_snapshot(self) -> dict[str, Any]:
        """Return the existing sanitized runtime/OMS/ledger state for a drill."""

        return self.status()

    def fault_drill_runtime_provenance(self) -> dict[str, Any]:
        """Expose a read-only controller attestation for the application boundary."""

        with self._lock:
            runtime = _mapping(self._state.get("runtime"))
            runtime_run_id = str(runtime.get("run_id") or "")
            authoritative_receipt = _mapping(
                runtime.get("fault_drill_authoritative_receipt")
            )
            authoritative_projection = _mapping(
                authoritative_receipt.get("identity_projection")
            )
            authoritative_source_head = str(
                authoritative_receipt.get("source_head") or ""
            )
        return {
            "runtime_boundary": OKX_DEMO_PARTIAL_FILL_RUNTIME_BOUNDARY,
            "runtime_version": OKX_DEMO_PAPER_RUNTIME_VERSION,
            "attestation_version": OKX_DEMO_PARTIAL_FILL_ATTESTATION_VERSION,
            "controller_type": "OkxDemoPaperRuntimeController",
            "environment": "OKX Demo",
            "source": "exchange_snapshot",
            "source_head": authoritative_source_head
            or _repo_head(self.config.repo_root),
            "runtime_run_id": runtime_run_id,
            "identity_namespace": str(
                authoritative_receipt.get("identity_namespace") or ""
            ),
            "authority_version": str(
                authoritative_receipt.get("authority_version") or ""
            ),
            "authoritative_receipt_sha256": str(
                authoritative_receipt.get("receipt_sha256") or ""
            ),
            "authoritative_identity_projection": _safe_json(
                authoritative_projection
            ),
        }

    def _bind_fault_drill_authoritative_receipt(
        self,
        projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one immutable identity receipt for the current drill run."""

        normalized_projection = _safe_json(projection)
        receipt = {
            "authority_version": OKX_DEMO_PARTIAL_FILL_AUTHORITY_VERSION,
            "runtime_boundary": OKX_DEMO_PARTIAL_FILL_RUNTIME_BOUNDARY,
            "runtime_version": OKX_DEMO_PAPER_RUNTIME_VERSION,
            "controller_type": "OkxDemoPaperRuntimeController",
            "source_head": str(normalized_projection.get("source_head") or ""),
            "runtime_run_id": str(
                normalized_projection.get("runtime_run_id") or ""
            ),
            "identity_namespace": str(
                normalized_projection.get("identity_namespace") or ""
            ),
            "identity_projection": normalized_projection,
            "receipt_sha256": _partial_authoritative_receipt_sha256(
                normalized_projection
            ),
        }
        with self._lock:
            runtime = self._state["runtime"]
            existing = _mapping(runtime.get("fault_drill_authoritative_receipt"))
            if existing:
                if _safe_json(existing) != receipt:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_partial_fill_authoritative_receipt_immutable_conflict"
                    )
                return _safe_json(existing)
            runtime["fault_drill_authoritative_receipt"] = _safe_json(receipt)
            self._append_event(
                "partial_fill_authoritative_receipt_bound",
                {
                    "authority_version": receipt["authority_version"],
                    "runtime_boundary": receipt["runtime_boundary"],
                    "runtime_run_id": receipt["runtime_run_id"],
                    "identity_namespace": receipt["identity_namespace"],
                    "receipt_sha256": receipt["receipt_sha256"],
                    "identity_projection": receipt["identity_projection"],
                },
            )
            self._persist_state()
        return _safe_json(receipt)

    @_runtime_writer_operation
    def freeze_fault_drill(self, reason: str) -> None:
        """Freeze opening after a drill without cancelling or flattening blindly."""

        safe_reason = str(reason or "fault_drill_fail_closed")[:160]
        with self._lock:
            self._enter_cancel_only(
                safe_reason,
                active=self._state.get("runtime", {}).get("active") is True,
            )
            self._append_event(
                "fault_drill_frozen",
                {
                    "reason": safe_reason,
                    "opening_allowed": False,
                    "blind_order_append_allowed": False,
                },
            )
            self._persist_state()

    @_runtime_writer_operation
    def run_fault_drill_scenario(
        self,
        scenario: str,
        *,
        fault_injector: Any,
        authorization: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one explicitly authorized Demo drill through Risk/OMS/Ledger.

        This method is intentionally not a generic order API.  It accepts only
        the ticket's six scenario names, uses the current runtime client/state,
        and leaves opening fail-closed when the scenario finishes.
        """

        scenarios = {
            "held_position_disconnect",
            "post_response_loss",
            "partial_fill_disconnect",
            "protection_creation_failure",
            "worker_kill",
            "reconnect_full_reconciliation",
        }
        if scenario not in scenarios:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_scenario_not_allowlisted"
            )
        authorization_row = _mapping(authorization)
        scenario_order_contracts = (
            OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS
            if scenario == "partial_fill_disconnect"
            else OKX_DEMO_PAPER_CONTRACTS
        )
        scenario_max_notional_usdt = (
            OKX_DEMO_PARTIAL_FILL_DRILL_MAX_NOTIONAL_USDT
            if scenario == "partial_fill_disconnect"
            else OKX_DEMO_PAPER_MAX_NOTIONAL_USDT
        )
        authorization_checks = {
            "authorization_ticket": (
                authorization_row.get("authorization_ticket")
                == "BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01"
            ),
            "source_head": (
                str(authorization_row.get("source_head") or "")
                == _repo_head(self.config.repo_root)
            ),
            "scenario": authorization_row.get("scenario") == scenario,
            "environment": authorization_row.get("environment") == "OKX Demo",
            "instrument_id": (
                authorization_row.get("instrument_id")
                == OKX_DEMO_INSTRUMENT_ID
            ),
            "margin_mode": authorization_row.get("margin_mode") == "isolated",
            "leverage": _decimal(authorization_row.get("leverage")) == Decimal("3"),
            "order_contracts": (
                _decimal(authorization_row.get("order_contracts"))
                == scenario_order_contracts
            ),
            "max_notional_usdt": (
                Decimal("0")
                < _decimal(authorization_row.get("max_notional_usdt"))
                <= scenario_max_notional_usdt
            ),
            "dedicated_demo_account": (
                authorization_row.get("confirm_dedicated_demo_account") is True
            ),
            "execute_demo": authorization_row.get("execute_demo") is True,
            "evidence_class": (
                authorization_row.get("evidence_class")
                == "demo_fault_drill_evidence"
            ),
        }
        failed_authorization = [
            key for key, passed in authorization_checks.items() if not passed
        ]
        if failed_authorization:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_authorization_invalid:"
                + ",".join(failed_authorization)
            )
        if scenario == "worker_kill":
            worker_nonce = str(authorization_row.get("worker_nonce") or "")
            process_create_time = str(
                authorization_row.get("process_create_time") or ""
            )
            if (
                not worker_nonce
                or len(worker_nonce) > 96
                or not worker_nonce.isalnum()
                or not process_create_time.isdigit()
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_worker_identity_invalid"
                )
        with self._lock:
            if self._state.get("runtime", {}).get("active") is not True:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_runtime_not_active"
                )
            if self._state.get("risk_control", {}).get("mode") != OKX_DEMO_RISK_MODE_RUNNING:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_runtime_not_running"
                )
            client = self._client
            private_ws = self._private_ws
            strategy = dict(self._state.get("strategy", {}))
            orders_before = int(
                self._state.get("runtime", {}).get("orders_submitted") or 0
            )
        if client is None:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_client_missing"
            )
        injector_record = getattr(fault_injector, "record", lambda *args, **kwargs: None)

        initial = self._collect_exchange_snapshot(client)
        blockers = self._preflight_blockers(initial, require_flat=True)
        if blockers:
            raise OkxDemoPaperRuntimeError(";".join(blockers))
        with self._lock:
            unresolved = [
                str(key)
                for key, row in _mapping(
                    self._state.get("risk_control", {}).get(
                        "pending_order_intents"
                    )
                ).items()
                if isinstance(row, Mapping)
                and str(row.get("status") or "")
                in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
            ]
            if unresolved:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_unresolved_intent"
                )

        if scenario == "partial_fill_disconnect":
            # The S2 entry guard must compare the durable ledger against the
            # very same fresh REST snapshot that passed the flat preflight.
            # In particular, balance provenance can advance while the account
            # remains flat; retaining the startup snapshot would make that
            # harmless change look like stale ledger truth.
            try:
                self._commit_ledger_reconciliation(
                    snapshot=initial,
                    trigger="fault_drill_partial_fill_preflight",
                    apply_snapshot=True,
                )
            except Exception as exc:
                self.freeze_fault_drill(
                    "okx_demo_partial_fill_preflight_ledger_refresh_failed"
                )
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_partial_fill_preflight_ledger_refresh_failed"
                ) from exc
            return self._run_partial_fill_disconnect(
                client=client,
                private_ws=private_ws,
                strategy=strategy,
                initial=initial,
                orders_before=orders_before,
                fault_injector=fault_injector,
                authorization=authorization_row,
            )

        wrapped_client = (
            fault_injector.wrap_client(client)
            if hasattr(fault_injector, "wrap_client")
            else fault_injector(client)
            if callable(fault_injector)
            else client
        )
        decision = {
            "strategy_id": str(strategy.get("strategy_id") or ""),
            "candidate_id": str(strategy.get("candidate_id") or ""),
            "strategy_version": str(strategy.get("strategy_version") or ""),
            "params_hash": str(strategy.get("params_hash") or ""),
            "source": "btc_okx_demo_fault_drill_runtime_boundary",
            "raw_signal": "1",
            "direction": "long",
            "target_contracts": _text(OKX_DEMO_PAPER_CONTRACTS),
            "decision_bar_close_utc": _iso(self._clock()),
            "effective_rule": "explicit_demo_fault_drill_only",
            "no_future_function": True,
        }
        order_plan = self._build_order_plan(
            initial,
            current_quantity=Decimal("0"),
            target_quantity=OKX_DEMO_PAPER_CONTRACTS,
        )
        if order_plan is None or order_plan.get("risk_reducing_only") is True:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_open_plan_invalid"
            )
        client_order_id = str(order_plan.get("client_order_id") or "")
        algo_client_order_id = str(
            _mapping(order_plan.get("attached_protection")).get(
                "attachAlgoClOrdId"
            )
            or ""
        )
        opening_error = ""
        injector_record(
            "risk_oms_opening_path_entered",
            clOrdId=client_order_id,
            algoClOrdId=algo_client_order_id,
        )
        try:
            with self._execution_lock:
                self._submit_order_plan(
                    wrapped_client,
                    snapshot=initial,
                    decision=decision,
                    order_plan=order_plan,
                )
        except Exception as exc:
            opening_error = _safe_error(exc)
            injector_record(
                "opening_path_fault_observed",
                error=opening_error,
            )

        current = self._collect_exchange_snapshot(client)
        held_facts = _fault_reconciliation_facts(current)
        held_hash = _canonical_sha256(held_facts)
        current_quantity = _signed_position(current.get("positions", []))
        gross_quantity = _gross_position_contracts(current.get("positions", []))
        order_observed = any(
            str(row.get("client_order_id") or "") == client_order_id
            for row in current.get("orders", [])
            if isinstance(row, Mapping)
        )
        fill_observed = any(
            str(row.get("client_order_id") or "") == client_order_id
            for row in current.get("fills", [])
            if isinstance(row, Mapping)
        )
        matching_protection = next(
            (
                row
                for row in current.get("pending_algo_orders", [])
                if isinstance(row, Mapping)
                and str(row.get("algo_client_order_id") or "")
                == algo_client_order_id
            ),
            None,
        )
        position_observed = gross_quantity == OKX_DEMO_PAPER_CONTRACTS
        protection_verified = matching_protection is not None
        if scenario != "protection_creation_failure":
            protection_verified = protection_verified and not (
                self._exchange_hosted_protection_blockers(current)
            )
        if not order_observed or not fill_observed or not position_observed:
            self.freeze_fault_drill(
                "okx_demo_fault_drill_real_held_position_evidence_missing"
            )
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_real_order_fill_position_missing"
            )
        if not protection_verified:
            self.freeze_fault_drill(
                "okx_demo_fault_drill_verified_protection_missing"
            )
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_verified_protection_missing"
            )
        injector_record(
            "real_demo_position_and_protection_verified",
            clOrdId=client_order_id,
            algoClOrdId=algo_client_order_id,
            gross_contracts=_text(gross_quantity),
        )

        if scenario == "held_position_disconnect":
            if private_ws is None or not hasattr(
                private_ws,
                "disconnect_for_reconnect",
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_private_ws_missing"
                )
            injector_record("private_ws_connection_close_requested", real_close=True)
            private_ws.disconnect_for_reconnect(
                "fault_drill_held_position_disconnect"
            )
            self._recover_transient_cycle(resume_opening=False)

        if scenario == "worker_kill":
            ledger = _mapping(self._state.get("ledger_reconciliation"))
            current_ledger_snapshot_hash = _fault_ledger_snapshot_sha256(
                current
            )
            if not (
                ledger.get("status") == "reconciled"
                and ledger.get("current_state_exchange_snapshot_match") is True
                and str(ledger.get("exchange_snapshot_sha256") or "")
                == current_ledger_snapshot_hash
            ):
                self.freeze_fault_drill(
                    "okx_demo_fault_drill_worker_ledger_not_current"
                )
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_worker_ledger_not_current"
                )
            previous_event = (
                self._status_event_projection(self._state["events"][0])
                if self._state.get("events")
                else {}
            )
            marker = {
                "schema_version": "btc_okx_demo_worker_ready_v1",
                "scenario": scenario,
                "process_id": os.getpid(),
                "process_create_time": process_create_time,
                "worker_nonce": worker_nonce,
                "source_head": _repo_head(self.config.repo_root),
                "runtime_root_sha256": _canonical_sha256(
                    str(Path(self.config.output_dir).resolve())
                ),
                "run_id": str(self._state.get("runtime", {}).get("run_id") or ""),
                "order_sequence": int(
                    self._state.get("runtime", {}).get("order_sequence") or 0
                ),
                "clOrdId": client_order_id,
                "algoClOrdId": algo_client_order_id,
                "algoId": str(_mapping(matching_protection).get("algo_id") or ""),
                "held_reconciliation_sha256": held_hash,
                "ledger_snapshot_sha256": current_ledger_snapshot_hash,
                "committed_ledger_snapshot_sha256": str(
                    ledger.get("exchange_snapshot_sha256") or ""
                ),
                "runtime_state_sha256": _canonical_sha256(
                    self._durable_state_snapshot()
                ),
                "previous_event_hash": str(
                    previous_event.get("event_id") or ""
                ),
                "position_observed": True,
                "protection_verified": True,
                "persisted_at_utc": _iso(self._clock()),
            }
            marker["marker_sha256"] = _canonical_sha256(marker)
            with self._lock:
                self._state["runtime"]["fault_drill_worker_ready"] = marker
                self._append_event("fault_drill_worker_ready", marker)
                self._persist_state()
            injector_record(
                "worker_ready_marker_persisted",
                process_id=os.getpid(),
                marker_sha256=marker["marker_sha256"],
            )
            return {
                "decision": "worker_ready_for_external_termination",
                "simulation_only": False,
                "orders_posted": max(
                    0,
                    int(self._state["runtime"].get("orders_submitted") or 0)
                    - orders_before,
                ),
                "clOrdId": client_order_id,
                "algoClOrdId": algo_client_order_id,
                "process_id": os.getpid(),
                "worker_ready_marker_persisted": True,
                "position_observed": True,
                "protection_verified": True,
                "pre_reconciliation_sha256": held_hash,
                "post_reconciliation_sha256": held_hash,
                "fault_origin": "external_worker_process_termination_pending",
                "evidence_mode": "real_demo_held_position",
            }

        reconnect_match = True
        post_reconnect_hash = held_hash
        if scenario == "reconnect_full_reconciliation":
            if private_ws is None or not hasattr(
                private_ws,
                "disconnect_for_reconnect",
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_private_ws_missing"
                )
            injector_record("private_ws_connection_close_requested", real_close=True)
            private_ws.disconnect_for_reconnect(
                "fault_drill_reconnect_full_reconciliation"
            )
            self._recover_transient_cycle(resume_opening=False)
            reconnected = self._collect_exchange_snapshot(client)
            post_reconnect_hash = _canonical_sha256(
                _fault_reconciliation_facts(reconnected)
            )
            reconnect_match = post_reconnect_hash == held_hash
            if not reconnect_match:
                self.freeze_fault_drill(
                    "okx_demo_fault_drill_reconnect_evidence_mismatch"
                )
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_reconnect_evidence_mismatch"
                )
            current = reconnected
            current_quantity = _signed_position(current.get("positions", []))
            gross_quantity = _gross_position_contracts(current.get("positions", []))
            injector_record(
                "private_ws_reconnected_full_reconciliation_match",
                pre_reconciliation_sha256=held_hash,
                post_reconciliation_sha256=post_reconnect_hash,
            )
        if gross_quantity > 0:
            with self._lock:
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_REDUCING,
                    "fault_drill_mandatory_flatten",
                )
            injector_record(
                "risk_reduction_path_entered",
                current_contracts=_text(current_quantity),
            )
            self._run_risk_reduction_cycle(client, strategy=strategy)

        final_snapshot = self._collect_exchange_snapshot(client)
        final_snapshot, algo_cleanup = self._cleanup_owned_flat_algos(
            client,
            snapshot=final_snapshot,
        )
        with self._lock:
            self._apply_snapshot(final_snapshot)
        self._commit_ledger_reconciliation(
            snapshot=final_snapshot,
            trigger="fault_drill_postflight",
        )
        final_quantity = _gross_position_contracts(
            final_snapshot.get("positions", [])
        )
        if final_quantity != 0:
            self.freeze_fault_drill("fault_drill_postflight_position_not_flat")
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_postflight_position_not_flat"
            )
        postflight_blockers = self._fault_drill_postflight_blockers(
            final_snapshot
        )
        if postflight_blockers:
            self.freeze_fault_drill(";".join(postflight_blockers))
            raise OkxDemoPaperRuntimeError(";".join(postflight_blockers))
        self.freeze_fault_drill("fault_drill_completed_requires_review")
        with self._lock:
            orders_after = int(
                self._state.get("runtime", {}).get("orders_submitted") or 0
            )
            close_client_order_ids = sorted(
                str(key)
                for key, row in _mapping(
                    self._state.get("risk_control", {}).get(
                        "pending_order_intents"
                    )
                ).items()
                if isinstance(row, Mapping)
                and row.get("risk_reducing_only") is True
            )
            self._append_event(
                "fault_drill_completed_flat",
                {
                    "scenario": scenario,
                    "clOrdId": client_order_id,
                    "algoClOrdId": algo_client_order_id,
                    "opening_error": opening_error,
                    "opening_allowed": False,
                },
            )
            self._persist_state()
        shared_terminal_projection = self._fault_drill_terminal_projection(
            final_snapshot,
            opening_cl_ord_id=client_order_id,
            close_cl_ord_id=(
                close_client_order_ids[-1] if close_client_order_ids else ""
            ),
            algo_cl_ord_id=algo_client_order_id,
        )
        return {
            "decision": "completed_flat_fail_closed",
            "simulation_only": False,
            "orders_posted": max(0, orders_after - orders_before),
            "clOrdId": client_order_id,
            "closeClOrdId": (
                close_client_order_ids[-1] if close_client_order_ids else ""
            ),
            "algoClOrdId": algo_client_order_id,
            "opening_error": opening_error,
            "position_observed": position_observed,
            "protection_verified": protection_verified,
            "pre_reconciliation_sha256": held_hash,
            "post_reconciliation_sha256": post_reconnect_hash,
            "reconciliation_comparison_match": reconnect_match,
            "disconnect_observed": scenario in {
                "held_position_disconnect",
                "reconnect_full_reconciliation",
            },
            "post_response_loss_reconciled": (
                scenario == "post_response_loss"
                and _fault_drill_post_response_loss_reconciled(
                    fault_injector,
                    opening_error=opening_error,
                    client_order_id=client_order_id,
                    order_observed=order_observed,
                    fill_observed=fill_observed,
                )
            ),
            "injected_protection_verification_failure_observed": (
                scenario == "protection_creation_failure"
                and "okx_demo_exchange_hosted_protection_unconfirmed"
                in opening_error
            ),
            "algo_cleanup": algo_cleanup,
            "fault_origin": (
                "local_injected_protection_verification_readback_failure"
                if scenario == "protection_creation_failure"
                else "real_demo_private_transport_fault"
            ),
            "evidence_mode": (
                "hybrid_real_position_injected_verification_failure"
                if scenario == "protection_creation_failure"
                else "real_demo_order_fill_position_protection"
            ),
            "process_id": os.getpid(),
            "child_termination": {},
            **shared_terminal_projection,
        }

    def _run_partial_fill_disconnect(
        self,
        *,
        client: Any,
        private_ws: Any,
        strategy: Mapping[str, Any],
        initial: Mapping[str, Any],
        orders_before: int,
        fault_injector: Any,
        authorization: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Run the one-shot real-Demo partial-fill recovery drill.

        The entry is an explicitly opt-in IOC order so the venue, rather than
        a fake, determines whether the drill is partial, empty, or full.  A
        partial observation is the only branch that disconnects the private
        stream.  Every branch remains reducing/frozen and never re-enables an
        opening path automatically.
        """

        requested_contracts = OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS
        with self._lock:
            runtime_run_id = str(
                self._state.get("runtime", {}).get("run_id") or ""
            )
            dead_man_armed = (
                _mapping(self._state.get("risk_control").get("dead_man"))
                .get("armed")
                is True
            )
            ledger = dict(self._state.get("ledger_reconciliation") or {})
            private_ws_state = dict(self._state.get("private_ws") or {})
        if not dead_man_armed:
            self.freeze_fault_drill("okx_demo_partial_fill_preflight_dead_man_not_armed")
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_preflight_dead_man_not_armed"
            )
        if not (
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
            and str(ledger.get("exchange_snapshot_sha256") or "")
            == _fault_ledger_snapshot_sha256(initial)
        ):
            self.freeze_fault_drill("okx_demo_partial_fill_preflight_ledger_not_current")
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_preflight_ledger_not_current"
            )
        if not (
            private_ws_state.get("connected") is True
            and private_ws_state.get("listener_alive") is True
            and private_ws_state.get("opening_allowed_after_reconciliation")
            is True
        ):
            self.freeze_fault_drill("okx_demo_partial_fill_preflight_private_ws_not_reconciled")
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_preflight_private_ws_not_reconciled"
            )
        injector_record = getattr(
            fault_injector,
            "record",
            lambda *args, **kwargs: None,
        )
        decision = {
            "strategy_id": str(strategy.get("strategy_id") or ""),
            "candidate_id": str(strategy.get("candidate_id") or ""),
            "strategy_version": str(strategy.get("strategy_version") or ""),
            "params_hash": str(strategy.get("params_hash") or ""),
            "source": "btc_okx_demo_partial_fill_fault_drill",
            "raw_signal": "1",
            "direction": "long",
            "target_contracts": _text(requested_contracts),
            "decision_bar_close_utc": _iso(self._clock()),
            "effective_rule": "single_authorized_ioc_entry_then_reduce_only_recovery",
            "no_future_function": True,
        }
        order_plan = self._build_order_plan(
            initial,
            current_quantity=Decimal("0"),
            target_quantity=requested_contracts,
        )
        if not order_plan or order_plan.get("partial_fill_recovery") is not True:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_entry_plan_not_authorized"
            )
        client_order_id = str(order_plan.get("client_order_id") or "")
        algo_client_order_id = str(
            _mapping(order_plan.get("attached_protection")).get(
                "attachAlgoClOrdId"
            )
            or ""
        )
        injector_record(
            "partial_fill_single_entry_attempt_authorized",
            clOrdId=client_order_id,
            algoClOrdId=algo_client_order_id,
            order_contracts=_text(requested_contracts),
            max_notional_usdt="25",
            entry_order_type="ioc",
            entry_attempt=1,
            retry_without_query_allowed=False,
        )
        with self._lock:
            self._state["runtime"]["fault_drill_entry_authorized"] = True
            self._persist_state()
        try:
            with self._execution_lock:
                submit_result = dict(
                    self._submit_order_plan(
                        client,
                        snapshot=initial,
                        decision=decision,
                        order_plan=order_plan,
                    )
                    or {}
                )
        finally:
            with self._lock:
                self._state["runtime"]["fault_drill_entry_authorized"] = False
                self._persist_state()
        entry_snapshot = self._collect_exchange_snapshot(client)
        broker_truth = _partial_entry_truth(
            entry_snapshot,
            client_order_id=client_order_id,
            algo_client_order_id=algo_client_order_id,
            requested_contracts=requested_contracts,
        )
        injector_record("broker_truth_observed", **broker_truth)
        classification = str(broker_truth.get("classification") or "")
        if classification == "broker_truth_discrepancy":
            self.freeze_fault_drill(
                "okx_demo_partial_fill_broker_truth_discrepancy"
            )
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_broker_truth_discrepancy"
            )

        reconnect_receipt: Mapping[str, Any] = {}
        reconciliation: dict[str, Any] = {
            "order_sync": True,
            "fill_sync": True,
            "position_sync": True,
            "oco_sync": True,
            "ledger_sync": True,
            "private_ws_sync": True,
            "match": True,
            "classification": classification,
        }
        if classification == "partial_fill":
            if private_ws is None or not hasattr(
                private_ws,
                "disconnect_for_reconnect",
            ):
                self.freeze_fault_drill(
                    "okx_demo_partial_fill_private_ws_missing"
                )
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_partial_fill_private_ws_missing"
                )
            with self._lock:
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_REDUCING,
                    "partial_fill_disconnect_blocked_opening",
                )
                self._state["runtime"].update(
                    {
                        "status": "cancel_only",
                        "opening_allowed": False,
                        "cancel_only": True,
                        "fault_drill_recovery_state": "BLOCKED_DISCONNECT",
                    }
                )
                self._append_event(
                    "partial_fill_disconnect_blocked_opening",
                    {
                        "clOrdId": client_order_id,
                        "filled_contracts": broker_truth["filled_contracts"],
                        "opening_allowed": False,
                        "retry_without_query_allowed": False,
                    },
                )
                self._persist_state()
            injector_record(
                "private_ws_connection_close_requested",
                real_close=True,
                reason="partial_fill_disconnect",
            )
            reconnect_receipt = private_ws.disconnect_for_reconnect(
                "fault_drill_partial_fill_disconnect"
            )
            injector_record(
                "bounded_reconnect_completed",
                reconnect_receipt=_safe_json(reconnect_receipt),
                bounded=True,
            )
            self._recover_transient_cycle(resume_opening=False)
            reconnect_snapshot = self._collect_exchange_snapshot(client)
            reconciliation = _partial_reconciliation(
                before=entry_snapshot,
                after=reconnect_snapshot,
                client_order_id=client_order_id,
                algo_client_order_id=algo_client_order_id,
                expected_filled_contracts=_decimal(
                    broker_truth["filled_contracts"]
                ),
                ledger=self._state.get("ledger_reconciliation", {}),
                private_ws=(
                    private_ws.status()
                    if hasattr(private_ws, "status")
                    else {}
                ),
            )
            injector_record("four_way_reconciliation_completed", **reconciliation)
            if reconciliation.get("match") is not True:
                self.freeze_fault_drill(
                    "okx_demo_partial_fill_reconciliation_discrepancy"
                )
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_partial_fill_reconciliation_discrepancy"
                )
            self._run_risk_reduction_cycle(client, strategy=strategy)
        elif classification == "full_fill":
            injector_record(
                "full_fill_observed_no_partial_disconnect",
                clOrdId=client_order_id,
                retry_without_query_allowed=False,
            )
            with self._lock:
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_REDUCING,
                    "full_fill_not_partial_reduce_only_required",
                )
                self._state["runtime"].update(
                    {
                        "status": "risk_reducing_only",
                        "opening_allowed": False,
                        "cancel_only": True,
                        "fault_drill_recovery_state": "FULL_FILL_REDUCING",
                    }
                )
                self._persist_state()
            self._run_risk_reduction_cycle(client, strategy=strategy)
        else:
            injector_record(
                "zero_fill_observed_no_partial_disconnect",
                clOrdId=client_order_id,
                retry_without_query_allowed=False,
            )
            reconnect_snapshot = entry_snapshot

        final_snapshot = self._collect_exchange_snapshot(client)
        final_snapshot, algo_cleanup = self._cleanup_owned_flat_algos(
            client,
            snapshot=final_snapshot,
        )
        with self._lock:
            self._apply_snapshot(final_snapshot)
        self._commit_ledger_reconciliation(
            snapshot=final_snapshot,
            trigger="partial_fill_fault_drill_postflight",
        )
        final_quantity = _gross_position_contracts(
            final_snapshot.get("positions", [])
        )
        if final_quantity != 0:
            self.freeze_fault_drill(
                "okx_demo_partial_fill_postflight_position_not_flat"
            )
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_postflight_position_not_flat"
            )
        postflight_blockers = self._fault_drill_postflight_blockers(
            final_snapshot
        )
        if postflight_blockers:
            self.freeze_fault_drill(";".join(postflight_blockers))
            raise OkxDemoPaperRuntimeError(";".join(postflight_blockers))
        with self._lock:
            final_private_ws_state = dict(self._state.get("private_ws") or {})
            final_ledger_state = dict(
                self._state.get("ledger_reconciliation") or {}
            )
        final_private_ws_reconciled = bool(
            final_private_ws_state.get("connected") is True
            and final_private_ws_state.get("listener_alive") is True
            and final_private_ws_state.get("opening_allowed_after_reconciliation")
            is True
        )
        final_ledger_reconciled = bool(
            final_ledger_state.get("status") == "reconciled"
            and final_ledger_state.get("current_state_exchange_snapshot_match")
            is True
            and str(final_ledger_state.get("exchange_snapshot_sha256") or "")
            == _fault_ledger_snapshot_sha256(final_snapshot)
        )
        if not final_private_ws_reconciled:
            self.freeze_fault_drill(
                "okx_demo_partial_fill_postflight_private_ws_not_reconciled"
            )
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_postflight_private_ws_not_reconciled"
            )
        if not final_ledger_reconciled:
            self.freeze_fault_drill(
                "okx_demo_partial_fill_postflight_ledger_not_current"
            )
            raise OkxDemoPaperRuntimeError(
                "okx_demo_partial_fill_postflight_ledger_not_current"
            )

        operator_acknowledged = authorization.get("operator_ack") is True
        with self._lock:
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_FROZEN,
                "partial_fill_recovery_pending_operator_ack",
            )
            self._state["runtime"].update(
                {
                    "status": "recovery_pending",
                    "opening_allowed": False,
                    "cancel_only": True,
                    "fault_drill_recovery_state": "RECOVERY_PENDING",
                    "fault_drill_operator_acknowledged": operator_acknowledged,
                }
            )
            self._append_event(
                "partial_fill_recovery_pending_operator_ack",
                {
                    "classification": classification,
                    "clOrdId": client_order_id,
                    "operator_acknowledged": operator_acknowledged,
                    "opening_allowed": False,
                    "global_cancel_issued": False,
                },
            )
            if operator_acknowledged:
                self._append_event(
                    "partial_fill_recovery_operator_acknowledged",
                    {
                        "clOrdId": client_order_id,
                        "opening_allowed": False,
                    },
                )
            self._persist_state()
            orders_after = int(
                self._state.get("runtime", {}).get("orders_submitted") or 0
            )
            close_client_order_id = next(
                (
                    str(
                        _mapping(record.get("order_plan")).get(
                            "client_order_id"
                        )
                        or ""
                    )
                    for record in self._state.get("audit", [])
                    if isinstance(record, Mapping)
                    and _mapping(record.get("order_plan")).get(
                        "risk_reducing_only"
                    )
                    is True
                    and str(
                        _mapping(record.get("order_plan")).get(
                            "client_order_id"
                        )
                        or ""
                    )
                    != client_order_id
                ),
                "",
            )
        close_truth: dict[str, Any] = {}
        if classification == "partial_fill":
            close_truth = _partial_close_truth(
                final_snapshot,
                client_order_id=close_client_order_id,
                expected_contracts=_decimal(broker_truth["filled_contracts"]),
                entry_order_id=str(broker_truth.get("exchange_order_id") or ""),
                entry_fill_ids=tuple(broker_truth.get("fill_ids") or ()),
            )
            if close_truth.get("classification") != "close_filled":
                self.freeze_fault_drill(
                    "okx_demo_partial_fill_close_broker_truth_discrepancy"
                )
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_partial_fill_close_broker_truth_discrepancy"
                )
        final_no_unresolved_intents = not any(
            isinstance(row, Mapping)
            and str(row.get("status") or "")
            in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
            for row in _mapping(
                self._state.get("risk_control", {}).get(
                    "pending_order_intents"
                )
            ).values()
        )
        source_head = _repo_head(self.config.repo_root)
        pre_reconciliation_sha256 = _canonical_sha256(
            _fault_reconciliation_facts(entry_snapshot)
        )
        post_reconciliation_sha256 = _canonical_sha256(
            _fault_reconciliation_facts(final_snapshot)
        )
        final_flat = final_quantity == 0
        final_no_pending_orders = not bool(final_snapshot.get("pending_orders"))
        final_no_pending_algo_orders = not bool(
            final_snapshot.get("pending_algo_orders")
        )
        authoritative_identity_projection: dict[str, Any] = {}
        authoritative_receipt: dict[str, Any] = {}
        if classification == "partial_fill":
            authoritative_identity_projection = (
                _partial_authoritative_identity_projection(
                    runtime_run_id=runtime_run_id,
                    source_head=source_head,
                    opening_clord_id=client_order_id,
                    close_clord_id=close_client_order_id,
                    algo_clord_id=algo_client_order_id,
                    entry_order_id=str(
                        broker_truth.get("exchange_order_id") or ""
                    ),
                    close_order_id=str(close_truth.get("order_id") or ""),
                    entry_fill_ids=tuple(
                        broker_truth.get("fill_ids") or ()
                    ),
                    close_fill_ids=tuple(close_truth.get("fill_ids") or ()),
                    entry_fill_order_ids=tuple(
                        broker_truth.get("fill_order_ids") or ()
                    ),
                    close_fill_order_ids=tuple(
                        close_truth.get("fill_order_ids") or ()
                    ),
                    entry_fill_client_order_ids=tuple(
                        broker_truth.get("fill_client_order_ids") or ()
                    ),
                    close_fill_client_order_ids=tuple(
                        close_truth.get("fill_client_order_ids") or ()
                    ),
                    algo_id=str(broker_truth.get("algo_id") or ""),
                    algo_parent_clord_id=str(
                        broker_truth.get("algo_parent_client_order_id") or ""
                    ),
                    entry_fill_contracts=str(
                        broker_truth.get("filled_contracts") or ""
                    ),
                    close_fill_contracts=str(
                        close_truth.get("filled_contracts") or ""
                    ),
                    pre_reconciliation_sha256=pre_reconciliation_sha256,
                    post_reconciliation_sha256=post_reconciliation_sha256,
                    final_flat=final_flat,
                    final_no_pending_orders=final_no_pending_orders,
                    final_no_pending_algo_orders=final_no_pending_algo_orders,
                    final_ledger_reconciled=final_ledger_reconciled,
                    final_private_ws_reconciled=final_private_ws_reconciled,
                )
            )
            authoritative_receipt = (
                self._bind_fault_drill_authoritative_receipt(
                    authoritative_identity_projection
                )
            )
        authoritative_receipt_sha256 = str(
            authoritative_receipt.get("receipt_sha256") or ""
        )
        provenance = {
            "runtime_boundary": OKX_DEMO_PARTIAL_FILL_RUNTIME_BOUNDARY,
            "runtime_version": OKX_DEMO_PAPER_RUNTIME_VERSION,
            "attestation_version": OKX_DEMO_PARTIAL_FILL_ATTESTATION_VERSION,
            "controller_type": "OkxDemoPaperRuntimeController",
            "environment": "OKX Demo",
            "source": "exchange_snapshot",
            "source_head": source_head,
            "real_exchange_observation": True,
            "fixture": False,
            "simulation": False,
            "synthetic": False,
            "simulation_only": False,
            "runtime_run_id": runtime_run_id,
            "authority_version": str(
                authoritative_receipt.get("authority_version") or ""
            ),
            "identity_namespace": str(
                authoritative_receipt.get("identity_namespace") or ""
            ),
            "authoritative_receipt_sha256": authoritative_receipt_sha256,
            "authoritative_identity_projection": _safe_json(
                authoritative_identity_projection
            ),
        }
        legacy_runtime_receipt_sha256 = _canonical_sha256(
            {
                "scenario": "partial_fill_disconnect",
                "runtime_run_id": runtime_run_id,
                "entry_order_id": broker_truth.get("exchange_order_id"),
                "entry_fill_ids": broker_truth.get("fill_ids"),
                "close_order_id": close_truth.get("order_id"),
                "close_fill_ids": close_truth.get("fill_ids"),
                "algo_id": broker_truth.get("algo_id"),
                "pre_reconciliation_sha256": _canonical_sha256(
                    _fault_reconciliation_facts(entry_snapshot)
                ),
                "post_reconciliation_sha256": _canonical_sha256(
                    _fault_reconciliation_facts(final_snapshot)
                ),
            }
        )
        runtime_receipt_sha256 = (
            authoritative_receipt_sha256 or legacy_runtime_receipt_sha256
        )
        return {
            "decision": (
                "completed_flat_fail_closed"
                if operator_acknowledged and classification == "partial_fill"
                else "recovery_pending_operator_ack"
            ),
            "simulation_only": False,
            "orders_posted": max(0, orders_after - orders_before),
            "entry_attempts": 1,
            "entry_retry_count": 0,
            "clOrdId": client_order_id,
            "closeClOrdId": (
                close_client_order_id
            ),
            "algoClOrdId": algo_client_order_id,
            "entry_order_id": broker_truth.get("exchange_order_id", ""),
            "close_order_id": close_truth.get("order_id", ""),
            "entry_fill_ids": list(broker_truth.get("fill_ids") or []),
            "close_fill_ids": list(close_truth.get("fill_ids") or []),
            "entry_fill_order_ids": list(
                broker_truth.get("fill_order_ids") or []
            ),
            "close_fill_order_ids": list(
                close_truth.get("fill_order_ids") or []
            ),
            "entry_fill_client_order_ids": list(
                broker_truth.get("fill_client_order_ids") or []
            ),
            "close_fill_client_order_ids": list(
                close_truth.get("fill_client_order_ids") or []
            ),
            "entry_order_client_order_id": broker_truth.get(
                "order_client_order_id", ""
            ),
            "close_order_client_order_id": close_client_order_id,
            "algo_id": broker_truth.get("algo_id", ""),
            "algo_parent_cl_ord_id": broker_truth.get(
                "algo_parent_client_order_id", ""
            ),
            "entry_order_type": "ioc",
            "requested_contracts": _text(requested_contracts),
            "entry_fill_contracts": broker_truth["filled_contracts"],
            "entry_order_filled_contracts": broker_truth[
                "order_filled_contracts"
            ],
            "entry_fill_sum_contracts": broker_truth["filled_contracts"],
            "entry_position_contracts": broker_truth["position_contracts"],
            "close_fill_contracts": close_truth.get("filled_contracts", ""),
            "close_order_filled_contracts": close_truth.get(
                "order_filled_contracts", ""
            ),
            "entry_fill_classification": classification,
            "discrepancy_classification": (
                "expected_partial_fill_recovery"
                if classification == "partial_fill"
                else "full_fill_not_partial"
                if classification == "full_fill"
                else "zero_fill_not_partial"
            ),
            "broker_truth_verified": True,
            "synthetic": False,
            "fixture": False,
            "simulation": False,
            "real_exchange_observation": True,
            "runtime_receipt_sha256": runtime_receipt_sha256,
            "authoritative_receipt_sha256": authoritative_receipt_sha256,
            "identity_namespace": str(
                authoritative_receipt.get("identity_namespace") or ""
            ),
            "authoritative_identity_projection": _safe_json(
                authoritative_identity_projection
            ),
            "provenance": provenance,
            "disconnect_observed": classification == "partial_fill",
            "reconnect_bounded": classification == "partial_fill",
            "reconnect_receipt": _safe_json(reconnect_receipt),
            "four_way_reconciliation": _safe_json(reconciliation),
            "pre_reconciliation_sha256": _canonical_sha256(
                _fault_reconciliation_facts(entry_snapshot)
            ),
            "post_reconciliation_sha256": _canonical_sha256(
                _fault_reconciliation_facts(final_snapshot)
            ),
            "protection_verified": submit_result.get(
                "protection_verified"
            ) is True,
            "algo_cleanup": algo_cleanup,
            "operator_ack_required": True,
            "operator_acknowledged": operator_acknowledged,
            "recovery_state": "RECOVERY_PENDING",
            "opening_allowed": False,
            "final_flat": final_flat,
            "final_no_pending_orders": final_no_pending_orders,
            "final_no_pending_algo_orders": final_no_pending_algo_orders,
            "final_no_unresolved_intents": final_no_unresolved_intents,
            "final_ledger_reconciled": final_ledger_reconciled,
            "final_private_ws_reconciled": final_private_ws_reconciled,
            "ledger_reconciled": final_ledger_reconciled,
            "private_ws_reconciled": final_private_ws_reconciled,
            "fault_origin": "real_demo_private_transport_fault"
            if classification == "partial_fill"
            else "real_demo_entry_outcome_not_partial",
            "evidence_mode": "real_demo_partial_fill_disconnect"
            if classification == "partial_fill"
            else "real_demo_non_partial_entry_outcome",
        }

    @_runtime_writer_operation
    def run_cycle(self) -> dict[str, Any]:
        with self._lock:
            if not self._state["runtime"]["active"]:
                raise OkxDemoPaperRuntimeError("okx_demo_paper_runtime_not_active")
            risk_mode = str(self._state["risk_control"].get("mode") or "")
            fault_drill_scenario = str(
                self._state["runtime"].get("fault_drill_scenario") or ""
            )
            if (
                fault_drill_scenario == "partial_fill_disconnect"
                and risk_mode == OKX_DEMO_RISK_MODE_RUNNING
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_partial_fill_runtime_requires_explicit_fault_drill"
                )
            if risk_mode in {
                OKX_DEMO_RISK_MODE_STARTUP,
                OKX_DEMO_RISK_MODE_FROZEN,
            }:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_runtime_frozen_unknown"
                )
            client = self._client
            strategy = dict(self._state["strategy"])
        if client is None:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_client_missing")
        if risk_mode == OKX_DEMO_RISK_MODE_REDUCING:
            return self._run_risk_reduction_cycle(client, strategy=strategy)
        try:
            snapshot = self._collect_exchange_snapshot(client)
            blockers = self._preflight_blockers(snapshot, require_flat=False)
            if blockers:
                raise OkxDemoPaperRuntimeError(";".join(blockers))
            decision = self._signal_decision(strategy, client=client)
            with self._lock:
                self._apply_snapshot(snapshot)
                self._state["signal"] = decision
                self._state["runtime"]["last_heartbeat_utc"] = _iso(self._clock())
            self._commit_new_funding_if_observed(snapshot=snapshot)
            self._capture_completed_hour_receipt(
                snapshot=snapshot,
                decision=decision,
            )
            if decision["decision_bar_close_utc"] == self._state["runtime"].get("last_processed_bar_close_utc"):
                return self.status()
            current_quantity = _signed_position(snapshot["positions"])
            target_quantity = Decimal(str(decision["target_contracts"]))
            order_plan = self._build_order_plan(snapshot, current_quantity=current_quantity, target_quantity=target_quantity)
            if order_plan is None:
                with self._lock:
                    self._state["runtime"]["last_processed_bar_close_utc"] = decision["decision_bar_close_utc"]
                    self._append_event("signal_no_order", {"signal": decision, "current_contracts": _text(current_quantity)})
                    self._persist_state()
                return self.status()
            with self._execution_lock:
                with self._lock:
                    if (
                        self._stop_event.is_set()
                        or not self._state["runtime"]["active"]
                        or self._state["risk_control"].get("mode")
                        != OKX_DEMO_RISK_MODE_RUNNING
                    ):
                        raise OkxDemoPaperRuntimeError("okx_demo_paper_order_blocked_by_runtime_stop")
                self._submit_order_plan(client, snapshot=snapshot, decision=decision, order_plan=order_plan)
            with self._lock:
                if not order_plan["reversal_close_only"]:
                    self._state["runtime"]["last_processed_bar_close_utc"] = decision["decision_bar_close_utc"]
                self._state["runtime"]["last_heartbeat_utc"] = _iso(self._clock())
                self._persist_state()
            return self.status()
        except Exception as exc:
            reason = _safe_error(exc)
            with self._lock:
                if _is_recoverable_cycle_error(exc):
                    reason = f"okx_demo_transient:{reason}"
                self._degrade_after_cycle_error(reason, recoverable=_is_recoverable_cycle_error(exc))
                self._append_event("runtime_cycle_failed", {"error": _safe_error(exc)})
                self._persist_state()
            raise OkxDemoPaperRuntimeError(reason) from exc

    @staticmethod
    def _validate_fresh_state_emergency_operator_payload(
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        expected_keys = {
            "operator_action",
            "confirmation_text",
            "expected_environment",
            "expected_instrument_id",
            "expected_margin_mode",
            "expected_position_side",
            "expected_entry_cl_ord_id",
            "expected_entry_ord_id",
            "expected_oco_algo_cl_ord_id",
            "expected_oco_algo_id",
            "expected_position_contracts",
            "max_position_contracts",
        }
        if not isinstance(payload, Mapping):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_operator_payload_invalid"
            )
        if set(payload) != expected_keys:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_operator_payload_fields_invalid"
            )
        exact = {
            "operator_action": "fresh_state_emergency_reduce_only_exit",
            "confirmation_text": OKX_DEMO_PAPER_CONFIRMATION,
            "expected_environment": "OKX Demo",
            "expected_instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "expected_margin_mode": "isolated",
            "expected_position_side": "long",
        }
        for key, expected in exact.items():
            if payload.get(key) != expected:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_operator_payload_value_invalid:" + key
                )
        entry_cl_ord_id = payload.get("expected_entry_cl_ord_id")
        entry_ord_id = payload.get("expected_entry_ord_id")
        oco_algo_cl_ord_id = payload.get("expected_oco_algo_cl_ord_id")
        oco_algo_id = payload.get("expected_oco_algo_id")
        if not isinstance(entry_cl_ord_id, str) or not re.fullmatch(
            r"btcDP[0-9a-f]{8}[0-9]{4}", entry_cl_ord_id
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_operator_payload_entry_identity_invalid"
            )
        if not isinstance(oco_algo_cl_ord_id, str) or (
            oco_algo_cl_ord_id != entry_cl_ord_id + "A"
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_operator_payload_oco_relation_invalid"
            )
        for key, value in (
            ("expected_entry_ord_id", entry_ord_id),
            ("expected_oco_algo_id", oco_algo_id),
        ):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{10,}", value):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_operator_payload_numeric_identity_invalid:"
                    + key
                )
        for key in ("expected_position_contracts", "max_position_contracts"):
            value = _decimal(payload.get(key))
            if not value.is_finite() or value != OKX_DEMO_PAPER_CONTRACTS:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_operator_payload_contracts_invalid:" + key
                )
        return {str(key): payload[key] for key in expected_keys}

    def _fresh_state_emergency_owner_marker_preflight(self) -> dict[str, Any]:
        """Audit a prior writer marker before the standard OS lock is acquired."""

        path = Path(self.config.output_dir).resolve() / (
            ".btc_okx_demo_fault_drill_writer.lock"
        )
        if not path.exists():
            return {"present": False, "ownership_input": False}
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_owner_marker_unreadable"
            ) from exc
        snapshot = self._owner_marker_snapshot(raw)
        marker = _mapping(snapshot.get("marker"))
        if not snapshot.get("valid") or not marker:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_owner_marker_invalid"
            )
        try:
            process_id = int(marker.get("process_id") or 0)
        except (TypeError, ValueError):
            process_id = 0
        if process_id <= 0:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_owner_marker_process_invalid"
            )
        if not re.fullmatch(r"[0-9a-f]{40}", str(marker.get("source_head") or "")):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_owner_marker_source_invalid"
            )
        if not re.fullmatch(
            r"[0-9a-f]{64}", str(marker.get("runtime_root_sha256") or "")
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_owner_marker_root_invalid"
            )
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            process_alive = False
        except PermissionError as exc:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_owner_marker_liveness_unknown"
            ) from exc
        except OSError as exc:
            if (
                os.name == "nt"
                and getattr(exc, "winerror", None) == 87
                and getattr(exc, "errno", None) == 22
            ):
                second_probe = _canonical_windows_process_liveness(process_id)
                if second_probe is False:
                    process_alive = False
                elif second_probe is True:
                    process_alive = True
                else:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fresh_state_owner_marker_liveness_unknown"
                    ) from exc
            else:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_owner_marker_liveness_unknown"
                ) from exc
        else:
            process_alive = True
        marker_process_create_time = str(
            marker.get("process_create_time") or ""
        ).strip()
        if process_alive and marker_process_create_time and os.name == "nt":
            observed_process_create_time = _canonical_windows_process_create_time(
                process_id
            )
            if observed_process_create_time is None:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_owner_marker_liveness_unknown"
                )
            if observed_process_create_time != marker_process_create_time:
                process_alive = False
        if process_alive:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_owner_marker_active"
            )
        return {
            "present": True,
            "stale": True,
            "ownership_input": False,
            "marker_sha256": str(snapshot.get("sha256") or ""),
            "process_id": process_id,
            "process_create_time": marker_process_create_time,
            "source_head": str(marker.get("source_head") or ""),
            "recovery_code_head": str(marker.get("recovery_code_head") or ""),
            "runtime_root_sha256": str(marker.get("runtime_root_sha256") or ""),
        }

    def _fresh_state_emergency_identity_projection(
        self,
        snapshot: Mapping[str, Any],
        operator_payload: Mapping[str, Any],
    ) -> tuple[list[str], dict[str, Any] | None]:
        """Prove the current emergency entry/OCO identity from fresh truth.

        The operator envelope is an exact, current-main contract.  It is not
        an ownership claim: the claim is formed only by the unique exchange
        order/fill/position/algo intersection.  OKX Demo may omit
        ``parentClOrdId``.  A missing exchange parent is accepted only when a
        unique durable ``owned_attached_algos`` row independently binds the
        exact fresh OCO to this entry.  The historical fixed incident remains
        available only through its existing fixed projection; the dynamic
        path never treats a payload field as an ownership claim.
        """

        operator = self._validate_fresh_state_emergency_operator_payload(
            operator_payload
        )
        expected_entry_cl = str(operator["expected_entry_cl_ord_id"])
        expected_entry_order = str(operator["expected_entry_ord_id"])
        expected_algo_cl = str(operator["expected_oco_algo_cl_ord_id"])
        expected_algo = str(operator["expected_oco_algo_id"])
        fixed_identity = (
            expected_entry_cl
            == str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["entry_cl_ord_id"])
            and expected_entry_order
            == str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["entry_ord_id"])
            and expected_algo_cl
            == str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_cl_ord_id"])
            and expected_algo
            == str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_id"])
        )
        blockers: list[str] = []

        orders = snapshot.get("orders")
        if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes)):
            return ["okx_demo_fresh_state_entry_history_invalid"], None
        entry_rows = [
            row
            for row in orders
            if isinstance(row, Mapping)
            and str(row.get("client_order_id") or "") == expected_entry_cl
        ]
        if len(entry_rows) != 1:
            return ["okx_demo_fresh_state_entry_identity_missing_or_ambiguous"], None
        entry = entry_rows[0]
        if str(entry.get("order_id") or "") != expected_entry_order:
            blockers.append("okx_demo_fresh_state_entry_identity_mismatch")
        if str(entry.get("instrument_id") or "") != OKX_DEMO_INSTRUMENT_ID:
            blockers.append("okx_demo_fresh_state_entry_instrument_mismatch")
        if str(entry.get("side") or "") != "buy":
            blockers.append("okx_demo_fresh_state_entry_side_mismatch")
        if str(entry.get("position_side") or "") != "long":
            blockers.append("okx_demo_fresh_state_entry_position_side_mismatch")
        if str(entry.get("state") or "") != "filled":
            blockers.append("okx_demo_fresh_state_entry_not_filled")
        if _decimal(entry.get("size")) != OKX_DEMO_PAPER_CONTRACTS or _decimal(
            entry.get("filled_size")
        ) != OKX_DEMO_PAPER_CONTRACTS:
            blockers.append("okx_demo_fresh_state_entry_size_mismatch")

        fills = snapshot.get("fills")
        if not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
            return ["okx_demo_fresh_state_fill_history_invalid"], None
        entry_fill_rows = [
            row
            for row in fills
            if isinstance(row, Mapping)
            and (
                str(row.get("client_order_id") or "") == expected_entry_cl
                or str(row.get("order_id") or "") == expected_entry_order
            )
        ]
        if len(entry_fill_rows) != 1:
            return ["okx_demo_fresh_state_entry_fill_missing_or_ambiguous"], None
        entry_fill = entry_fill_rows[0]
        if not str(entry_fill.get("fill_id") or ""):
            blockers.append("okx_demo_fresh_state_entry_fill_identity_invalid")
        if str(entry_fill.get("order_id") or "") != expected_entry_order:
            blockers.append("okx_demo_fresh_state_entry_fill_order_mismatch")
        if str(entry_fill.get("client_order_id") or "") != expected_entry_cl:
            blockers.append("okx_demo_fresh_state_entry_fill_client_mismatch")
        if str(entry_fill.get("instrument_id") or "") != OKX_DEMO_INSTRUMENT_ID:
            blockers.append("okx_demo_fresh_state_entry_fill_instrument_mismatch")
        if str(entry_fill.get("side") or "") != "buy":
            blockers.append("okx_demo_fresh_state_entry_fill_side_mismatch")
        if str(entry_fill.get("position_side") or "") != "long":
            blockers.append("okx_demo_fresh_state_entry_fill_position_side_mismatch")
        if _decimal(entry_fill.get("size")) != OKX_DEMO_PAPER_CONTRACTS:
            blockers.append("okx_demo_fresh_state_entry_fill_size_mismatch")

        pending_algos = snapshot.get("pending_algo_orders")
        if not isinstance(pending_algos, Sequence) or isinstance(
            pending_algos, (str, bytes)
        ):
            return ["okx_demo_fresh_state_oco_history_invalid"], None
        matching = [
            row
            for row in pending_algos
            if isinstance(row, Mapping)
            and str(row.get("algo_client_order_id") or "") == expected_algo_cl
            and str(row.get("algo_id") or "") == expected_algo
        ]
        if len(matching) != 1:
            return ["okx_demo_fresh_state_oco_identity_missing_or_ambiguous"], None
        if len(pending_algos) != 1:
            return ["okx_demo_fresh_state_foreign_algo_present"], None
        algo = matching[0]
        observed_parent = str(algo.get("parent_client_order_id") or "")
        owner_binding: dict[str, Any] = {}
        if observed_parent:
            if observed_parent != expected_entry_cl:
                blockers.append("okx_demo_fresh_state_oco_parent_mismatch")
            parent_binding = "exchange_parent_client_order_id"
            owner_binding = {
                "source": "exchange_parent_client_order_id",
                "parent_client_order_id": observed_parent,
            }
        else:
            owners = _mapping(
                _mapping(self._state.get("risk_control")).get(
                    "owned_attached_algos"
                )
            )
            owner_candidates = [
                _mapping(row)
                for key, row in owners.items()
                if isinstance(row, Mapping)
                and str(row.get("algo_client_order_id") or key or "")
                == expected_algo_cl
            ]
            if fixed_identity and not owners:
                parent_binding = "current_main_fixed_incident_identity_projection"
                owner_binding = {
                    "source": "current_main_fixed_incident_identity_projection",
                    "parent_client_order_id": expected_entry_cl,
                }
            elif len(owner_candidates) != 1:
                blockers.append("okx_demo_fresh_state_oco_parent_binding_mismatch")
                parent_binding = "durable_owned_attached_algo"
            else:
                owner = owner_candidates[0]
                if (
                    str(owner.get("parent_client_order_id") or "")
                    != expected_entry_cl
                    or str(owner.get("instrument_id") or "")
                    != OKX_DEMO_INSTRUMENT_ID
                    or owner.get("opening_intent") is not True
                    or str(owner.get("status") or "")
                    not in (
                        {"active"}
                        if fixed_identity
                        else {"submit_pending", "active"}
                    )
                ):
                    blockers.append("okx_demo_fresh_state_oco_parent_binding_mismatch")
                owner_algo_id = str(owner.get("algo_id") or "")
                if owner_algo_id and owner_algo_id != expected_algo:
                    blockers.append("okx_demo_fresh_state_oco_parent_binding_mismatch")
                parent_binding = (
                    "current_main_fixed_incident_identity_projection"
                    if fixed_identity
                    else "durable_owned_attached_algo"
                )
                owner_binding = {
                    "source": "durable_owned_attached_algo",
                    "algo_client_order_id": expected_algo_cl,
                    "algo_id": owner_algo_id,
                    "parent_client_order_id": str(
                        owner.get("parent_client_order_id") or ""
                    ),
                    "instrument_id": str(owner.get("instrument_id") or ""),
                    "opening_intent": owner.get("opening_intent") is True,
                    "status": str(owner.get("status") or ""),
                }

        if str(algo.get("instrument_id") or "") != OKX_DEMO_INSTRUMENT_ID:
            blockers.append("okx_demo_fresh_state_oco_instrument_mismatch")
        if str(algo.get("position_side") or "") != "long":
            blockers.append("okx_demo_fresh_state_oco_position_side_mismatch")
        if _decimal(algo.get("size")) != OKX_DEMO_PAPER_CONTRACTS:
            blockers.append("okx_demo_fresh_state_oco_size_mismatch")
        if str(algo.get("order_type") or "") != "oco":
            blockers.append("okx_demo_fresh_state_oco_type_mismatch")
        if str(algo.get("state") or "") not in {
            "live",
            "effective",
            "partially_effective",
        }:
            blockers.append("okx_demo_fresh_state_oco_not_active")
        if (
            str(algo.get("take_profit_order_price") or "") != "-1"
            or str(algo.get("stop_loss_order_price") or "") != "-1"
        ):
            blockers.append("okx_demo_fresh_state_oco_not_reduce_only")
        if "reduce_only" in algo and algo.get("reduce_only") is not True:
            blockers.append("okx_demo_fresh_state_oco_not_reduce_only")

        positions = snapshot.get("positions")
        position_rows = [
            row
            for row in positions
            if isinstance(row, Mapping)
            and _decimal(row.get("contracts")) > 0
        ] if isinstance(positions, Sequence) and not isinstance(positions, (str, bytes)) else []
        if len(position_rows) != 1:
            blockers.append("okx_demo_fresh_state_position_identity_ambiguous")
            position = {}
        else:
            position = position_rows[0]
            if (
                str(position.get("instrument_id") or "") != OKX_DEMO_INSTRUMENT_ID
                or str(position.get("margin_mode") or "") != "isolated"
                or str(position.get("position_side") or "") != "long"
                or _decimal(position.get("contracts")) != OKX_DEMO_PAPER_CONTRACTS
            ):
                blockers.append("okx_demo_fresh_state_position_identity_mismatch")

        if blockers:
            return _dedupe(blockers), None

        proof: dict[str, Any] = {
            "schema_version": (
                "okx_demo_fresh_state_oco_ownership_proof_v1"
                if fixed_identity
                else "okx_demo_fresh_state_oco_ownership_proof_v2"
            ),
            "binding_source": (
                "current_main_fixed_incident_identity_projection"
                if fixed_identity
                else "fresh_state_dynamic_identity_projection"
            ),
            "parent_binding": parent_binding,
            "owner_binding": owner_binding,
            "operator_contract": {
                "operator_action": str(operator["operator_action"]),
                "environment": str(operator["expected_environment"]),
                "instrument_id": str(operator["expected_instrument_id"]),
                "margin_mode": str(operator["expected_margin_mode"]),
                "position_side": str(operator["expected_position_side"]),
                "entry_cl_ord_id": expected_entry_cl,
                "entry_ord_id": expected_entry_order,
                "oco_algo_cl_ord_id": expected_algo_cl,
                "oco_algo_id": expected_algo,
                "contracts": str(operator["expected_position_contracts"]),
            },
            "entry": {
                "client_order_id": expected_entry_cl,
                "order_id": str(entry.get("order_id") or ""),
                "instrument_id": str(entry.get("instrument_id") or ""),
                "side": str(entry.get("side") or ""),
                "position_side": str(entry.get("position_side") or ""),
                "state": str(entry.get("state") or ""),
                "size": str(entry.get("size") or ""),
                "filled_size": str(entry.get("filled_size") or ""),
            },
            "entry_fill": {
                "fill_id": str(entry_fill.get("fill_id") or ""),
                "order_id": str(entry_fill.get("order_id") or ""),
                "client_order_id": str(entry_fill.get("client_order_id") or ""),
                "instrument_id": str(entry_fill.get("instrument_id") or ""),
                "side": str(entry_fill.get("side") or ""),
                "position_side": str(entry_fill.get("position_side") or ""),
                "size": str(entry_fill.get("size") or ""),
            },
            "position": {
                "instrument_id": str(position.get("instrument_id") or ""),
                "margin_mode": str(position.get("margin_mode") or ""),
                "position_side": str(position.get("position_side") or ""),
                "contracts": str(position.get("contracts") or ""),
            },
            "oco": {
                "algo_id": str(algo.get("algo_id") or ""),
                "algo_client_order_id": str(
                    algo.get("algo_client_order_id") or ""
                ),
                "parent_client_order_id": observed_parent,
                "instrument_id": str(algo.get("instrument_id") or ""),
                "position_side": str(algo.get("position_side") or ""),
                "size": str(algo.get("size") or ""),
                "order_type": str(algo.get("order_type") or ""),
                "state": str(algo.get("state") or ""),
                "reduce_only": algo.get("reduce_only", True) is True,
                "take_profit_order_price": str(
                    algo.get("take_profit_order_price") or ""
                ),
                "stop_loss_order_price": str(
                    algo.get("stop_loss_order_price") or ""
                ),
            },
            "uniqueness": {
                "entry_order_rows": len(entry_rows),
                "entry_fill_rows": len(entry_fill_rows),
                "matching_oco_rows": len(matching),
                "position_rows": len(position_rows),
                "pending_order_rows": len(snapshot.get("pending_orders", [])),
                "pending_algo_rows": len(pending_algos),
            },
        }
        proof["identity_digest_sha256"] = _canonical_sha256(proof)
        return [], proof

    def _fresh_state_emergency_operator_identity_blockers(
        self,
        snapshot: Mapping[str, Any],
        operator_payload: Mapping[str, Any],
    ) -> list[str]:
        blockers, _ = self._fresh_state_emergency_identity_projection(
            snapshot,
            operator_payload,
        )
        return blockers

    @staticmethod
    def _fresh_state_emergency_verified_projection_pair(
        proof: Mapping[str, Any] | None,
    ) -> tuple[str, str] | None:
        """Return only a digest-bound dynamic OCO pair for emergency cleanup."""

        proof_map = _mapping(proof)
        supplied_digest = str(proof_map.get("identity_digest_sha256") or "")
        without_digest = dict(proof_map)
        without_digest.pop("identity_digest_sha256", None)
        operator = _mapping(proof_map.get("operator_contract"))
        entry = _mapping(proof_map.get("entry"))
        oco = _mapping(proof_map.get("oco"))
        pair = (
            str(oco.get("algo_id") or ""),
            str(oco.get("algo_client_order_id") or ""),
        )
        if not (
            proof_map.get("schema_version")
            == "okx_demo_fresh_state_oco_ownership_proof_v2"
            and proof_map.get("binding_source")
            == "fresh_state_dynamic_identity_projection"
            and re.fullmatch(r"[0-9a-f]{64}", supplied_digest)
            and _canonical_sha256(without_digest) == supplied_digest
            and all(pair)
            and str(entry.get("client_order_id") or "")
            == str(operator.get("entry_cl_ord_id") or "")
            and str(entry.get("order_id") or "")
            == str(operator.get("entry_ord_id") or "")
            and pair[0] == str(operator.get("oco_algo_id") or "")
            and pair[1] == str(operator.get("oco_algo_cl_ord_id") or "")
            and pair[1]
            == str(operator.get("entry_cl_ord_id") or "") + "A"
        ):
            return None
        return pair

    def _persist_private_ws_probe_diagnostics(
        self,
        diagnostics: Sequence[Mapping[str, Any]],
    ) -> None:
        normalized = json.loads(
            json.dumps([dict(row) for row in diagnostics if isinstance(row, Mapping)])
        )
        with self._lock:
            self._state["private_ws"]["probe_diagnostics"] = normalized
            self._state["runtime"]["probe_diagnostics"] = normalized
            self._state["runtime"]["last_error_detail"] = {
                "probe_diagnostics": normalized,
                "credentials_redacted": True,
            }

    def _record_incident_recovery_private_ws_probe_failure(
        self,
        probe: Any,
    ) -> None:
        """Persist the failed probe before recovery cleanup can hide it."""

        current_head = _repo_head(self.config.repo_root)
        diagnostics = _build_runtime_probe_diagnostics(
            error_code="okx_demo_private_ws_startup_reconnect_probe_failed",
            probe=probe if isinstance(probe, Mapping) else None,
            current_head=current_head,
            generation_after=(
                probe.get("probe_generation", self._private_ws_generation)
                if isinstance(probe, Mapping)
                else self._private_ws_generation
            ),
            receipt_valid=False,
        )
        self._persist_private_ws_probe_diagnostics(diagnostics)
        with self._lock:
            runtime = self._state["runtime"]
            runtime["last_error"] = (
                "okx_demo_private_ws_startup_reconnect_probe_failed"
            )
            runtime["blockers"] = _dedupe(
                [
                    *runtime.get("blockers", []),
                    "okx_demo_private_ws_startup_reconnect_probe_failed",
                ]
            )
            self._state["private_ws"].update(
                {
                    "opening_allowed_after_reconciliation": False,
                    "probe_failure": (
                        "okx_demo_private_ws_startup_reconnect_probe_failed"
                    ),
                }
            )
            self._append_event(
                "private_ws_startup_reconnect_probe_failed",
                {
                    "error_code": (
                        "okx_demo_private_ws_startup_reconnect_probe_failed"
                    ),
                    "probe_diagnostics": json.loads(json.dumps(diagnostics)),
                    "credentials_redacted": True,
                },
            )
            self._persist_state()

    def _bootstrap_fresh_state_emergency_session(
        self,
        *,
        operator_payload: Mapping[str, Any],
        owner_marker_audit: Mapping[str, Any],
    ) -> None:
        credentials: Any = None
        client: OkxDemoClient | None = None
        private_ws: Any | None = None
        probe_diagnostics: list[dict[str, Any]] = []
        probe_generation_before = self._private_ws_generation
        if self.config.credential_service != OKX_DEMO_PAPER_CREDENTIAL_SERVICE:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fresh_state_credential_namespace_invalid"
            )
        current_head = _repo_head(self.config.repo_root)
        try:
            credentials = self._credential_loader(
                OKX_DEMO_PAPER_CREDENTIAL_SERVICE
            )
            client_config = OkxDemoClientConfig(
                credential_service=OKX_DEMO_PAPER_CREDENTIAL_SERVICE,
                allow_private_read=True,
                allow_demo_orders=True,
                allow_demo_cancels=True,
                authorization_ticket=OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
                max_order_contracts=OKX_DEMO_PAPER_CONTRACTS,
                max_notional_usdt=OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
                contract_value_btc=OKX_DEMO_PAPER_CONTRACT_VALUE_BTC,
                allow_partial_fill_opening=False,
            )
            client = self._client_factory(client_config, credentials)
            snapshot = self._collect_exchange_snapshot(client)
            identity_blockers, ownership_proof = (
                self._fresh_state_emergency_identity_projection(
                    snapshot,
                    operator_payload,
                )
            )
            blockers = [
                *self._fresh_state_emergency_snapshot_blockers(
                    snapshot,
                    verified_ownership_proof=ownership_proof,
                ),
                *identity_blockers,
            ]
            if blockers:
                raise OkxDemoPaperRuntimeError(";".join(_dedupe(blockers)))
            with self._lock:
                self._apply_snapshot(snapshot)
            self._commit_ledger_reconciliation(
                snapshot=snapshot,
                trigger="fresh_state_emergency_bootstrap",
            )
            with self._lock:
                ledger = _mapping(self._state.get("ledger_reconciliation"))
                if not (
                    ledger.get("status") == "reconciled"
                    and ledger.get("current_state_exchange_snapshot_match") is True
                    and ledger.get("funding_cashflow_reconciled") is True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fresh_state_bootstrap_ledger_not_current"
                    )
            private_ws = self._private_ws_factory(
                credentials=credentials,
                source_head=current_head,
                runtime_version=OKX_DEMO_PAPER_RUNTIME_VERSION,
                snapshot_loader=lambda: self._collect_exchange_snapshot(client),
                owned_client_order_ids=lambda: tuple(
                    sorted(self._owned_client_order_ids)
                ),
                on_disconnect=self._on_private_ws_disconnect,
                on_reconciled=self._on_private_ws_reconciled,
                clock=self._clock,
            )
            try:
                probe = private_ws.run_startup_reconnect_probe()
            except Exception as exc:
                probe_diagnostics = _build_runtime_probe_diagnostics(
                    exception=exc,
                    error_code="okx_demo_private_ws_probe_exception",
                    credentials=credentials,
                    current_head=current_head,
                    generation_before=probe_generation_before,
                    generation_after=self._private_ws_generation,
                    receipt_valid=False,
                )
                self._persist_private_ws_probe_diagnostics(probe_diagnostics)
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_bootstrap_private_ws_probe_failed"
                ) from None
            probe_generation_after = self._private_ws_generation
            if not isinstance(probe, Mapping):
                probe_diagnostics = _build_runtime_probe_diagnostics(
                    error_code="okx_demo_private_ws_probe_receipt_invalid",
                    message="okx_demo_private_ws_probe_receipt_invalid",
                    credentials=credentials,
                    current_head=current_head,
                    generation_before=probe_generation_before,
                    generation_after=probe_generation_after,
                    receipt_valid=False,
                )
                self._persist_private_ws_probe_diagnostics(probe_diagnostics)
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_bootstrap_private_ws_receipt_invalid"
                )
            probe_diagnostics = _project_probe_diagnostics(
                probe.get("probe_diagnostics"),
                credentials=credentials,
            )
            probe_receipt_valid = _private_ws_probe_receipt_valid(
                probe,
                current_head=current_head,
            )
            if probe.get("opening_allowed_after_reconciliation") is not True:
                probe_diagnostics = _build_runtime_probe_diagnostics(
                    probe=probe,
                    error_code="okx_demo_private_ws_probe_not_opening",
                    credentials=credentials,
                    current_head=current_head,
                    generation_before=probe_generation_before,
                    generation_after=probe_generation_after,
                    receipt_valid=probe_receipt_valid,
                )
                self._persist_private_ws_probe_diagnostics(probe_diagnostics)
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_bootstrap_private_ws_probe_failed"
                )
            if not probe_receipt_valid:
                probe_diagnostics = _build_runtime_probe_diagnostics(
                    probe=probe,
                    error_code="okx_demo_private_ws_probe_receipt_invalid",
                    credentials=credentials,
                    current_head=current_head,
                    generation_before=probe_generation_before,
                    generation_after=probe_generation_after,
                    receipt_valid=False,
                )
                self._persist_private_ws_probe_diagnostics(probe_diagnostics)
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_bootstrap_private_ws_receipt_invalid"
                )
            if hasattr(private_ws, "start_monitoring"):
                private_ws.start_monitoring()
            current_ws = private_ws.reconcile_current()
            current_generation = self._private_ws_generation
            if current_generation != probe_generation_after:
                probe_diagnostics = _build_runtime_probe_diagnostics(
                    probe=current_ws if isinstance(current_ws, Mapping) else probe,
                    error_code="okx_demo_private_ws_generation_mismatch",
                    message="okx_demo_private_ws_generation_mismatch",
                    credentials=credentials,
                    current_head=current_head,
                    generation_before=probe_generation_after,
                    generation_after=current_generation,
                    receipt_valid=False,
                )
                self._persist_private_ws_probe_diagnostics(probe_diagnostics)
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_bootstrap_private_ws_generation_mismatch"
                )
            if not isinstance(current_ws, Mapping) or not _private_ws_current_receipt_valid(
                current_ws,
                current_head=current_head,
            ):
                probe_diagnostics = _build_runtime_probe_diagnostics(
                    probe=current_ws if isinstance(current_ws, Mapping) else probe,
                    error_code="okx_demo_private_ws_current_reconciliation_receipt_invalid",
                    message="okx_demo_private_ws_current_reconciliation_receipt_invalid",
                    credentials=credentials,
                    current_head=current_head,
                    generation_before=probe_generation_after,
                    generation_after=current_generation,
                    receipt_valid=False,
                )
                self._persist_private_ws_probe_diagnostics(probe_diagnostics)
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_bootstrap_private_ws_receipt_invalid"
                )
            with self._lock:
                self._client = client
                self._private_ws = private_ws
                self._state["private_ws"] = json.loads(
                    json.dumps(
                        {
                            **dict(probe),
                            **dict(current_ws),
                            "controller_generation": current_generation,
                            "probe_diagnostics": probe_diagnostics,
                        }
                    )
                )
                self._state["safety"][
                    "okx_demo_private_read_enabled"
                ] = True
                self._state["safety"][
                    "okx_demo_order_capability_enabled"
                ] = False
                self._state["safety"][
                    "okx_demo_cancel_capability_enabled"
                ] = False
        except Exception:
            if probe_diagnostics:
                self._persist_private_ws_probe_diagnostics(probe_diagnostics)
            if private_ws is not None:
                try:
                    private_ws.stop()
                except Exception:
                    pass
            self._client = None
            self._private_ws = None
            raise

    def _record_fresh_state_emergency_projection(
        self,
        *,
        snapshot: Mapping[str, Any],
        operator_payload: Mapping[str, Any],
        prior_run_id: str,
        run_id: str,
        owner_marker_audit: Mapping[str, Any],
    ) -> None:
        """Persist the one-shot fresh-truth projection before any POST.

        The projection is an audit fence only: it records the current process,
        HEAD, fresh snapshot hash and exact operator-owned IDs.  It never
        imports a prior run or grants ordinary opening/order capability.
        """

        identity_blockers, ownership_proof = (
            self._fresh_state_emergency_identity_projection(
                snapshot,
                operator_payload,
            )
        )
        if identity_blockers or ownership_proof is None:
            raise OkxDemoPaperRuntimeError(";".join(identity_blockers))

        projection: dict[str, Any] = {
            "process_id": os.getpid(),
            "current_head": _repo_head(self.config.repo_root),
            "run_id": run_id,
            "client_order_namespace": f"btcDP{run_id[:8]}",
            "prior_runtime_run_id": prior_run_id,
            "fresh_snapshot_sha256": _canonical_sha256(snapshot),
            "expected_entry_cl_ord_id": str(
                operator_payload["expected_entry_cl_ord_id"]
            ),
            "expected_entry_ord_id": str(operator_payload["expected_entry_ord_id"]),
            "expected_oco_algo_cl_ord_id": str(
                operator_payload["expected_oco_algo_cl_ord_id"]
            ),
            "expected_oco_algo_id": str(operator_payload["expected_oco_algo_id"]),
            "oco_ownership_proof": ownership_proof,
            "oco_ownership_digest_sha256": str(
                ownership_proof["identity_digest_sha256"]
            ),
            "binding_source": str(ownership_proof["binding_source"]),
            "environment": "OKX Demo",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "margin_mode": "isolated",
            "position_side": "long",
            "identity_only": True,
            "opening_allowed": False,
            "paper_allowed": False,
            "promotion_evidence_ready": False,
            "live_allowed": False,
            "owner_marker_audit": json.loads(
                json.dumps(dict(owner_marker_audit), sort_keys=True, default=str)
            ),
            "credential_material_persisted": False,
        }
        projection["projection_sha256"] = _canonical_sha256(projection)
        with self._lock:
            marker = self._state["runtime"].setdefault(
                "fresh_state_emergency_exit", {}
            )
            marker["projection"] = projection
            marker["owner_marker_audit"] = dict(owner_marker_audit)
            self._append_event(
                "fresh_state_emergency_identity_projection_bound",
                {
                    "identity_digest_sha256": str(
                        ownership_proof["identity_digest_sha256"]
                    ),
                    "parent_binding": str(ownership_proof["parent_binding"]),
                    "binding_source": str(ownership_proof["binding_source"]),
                    "entry_cl_ord_id": str(
                        operator_payload["expected_entry_cl_ord_id"]
                    ),
                    "entry_ord_id": str(operator_payload["expected_entry_ord_id"]),
                    "oco_algo_cl_ord_id": str(
                        operator_payload["expected_oco_algo_cl_ord_id"]
                    ),
                    "oco_algo_id": str(operator_payload["expected_oco_algo_id"]),
                    "identity_only": True,
                    "opening_allowed": False,
                    "paper_allowed": False,
                    "promotion_evidence_ready": False,
                    "live_allowed": False,
                },
            )
            self._persist_state()

    def _fresh_state_emergency_snapshot_blockers(
        self,
        snapshot: Mapping[str, Any],
        *,
        verified_ownership_proof: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Validate a fresh, single-position emergency-exit truth snapshot.

        This is intentionally narrower than the normal opening preflight: a
        frozen runtime may only prove one owned long position and may never
        turn this path into an opening/reversal/scale capability.
        """

        blockers: list[str] = []
        if not isinstance(snapshot, Mapping):
            return ["okx_demo_fresh_state_emergency_exit_snapshot_invalid"]
        account = _mapping(snapshot.get("account"))
        if account.get("account_level") != "2":
            blockers.append("okx_demo_fresh_state_account_mode_invalid")
        if account.get("position_mode") != "long_short_mode":
            blockers.append("okx_demo_fresh_state_position_mode_invalid")
        permissions = account.get("permissions")
        if not isinstance(permissions, Sequence) or isinstance(
            permissions, (str, bytes)
        ):
            blockers.append("okx_demo_fresh_state_account_permissions_invalid")
        else:
            permission_set = {str(value) for value in permissions}
            if "trade" not in permission_set:
                blockers.append("okx_demo_fresh_state_trade_permission_missing")
            if "withdraw" in permission_set or account.get(
                "withdraw_permission_present"
            ) is not False:
                blockers.append("okx_demo_fresh_state_withdraw_permission_present")

        instrument = _mapping(snapshot.get("instrument"))
        if (
            instrument.get("instrument_id") != OKX_DEMO_INSTRUMENT_ID
            or instrument.get("state") != "live"
            or _decimal(instrument.get("contract_value_btc"))
            != OKX_DEMO_PAPER_CONTRACT_VALUE_BTC
            or _decimal(instrument.get("lot_size")) != OKX_DEMO_PAPER_CONTRACTS
            or _decimal(instrument.get("minimum_size"))
            != OKX_DEMO_PAPER_CONTRACTS
            or _decimal(instrument.get("tick_size")) <= 0
        ):
            blockers.append("okx_demo_fresh_state_instrument_invalid")

        positions_value = snapshot.get("positions")
        positions = (
            list(positions_value)
            if isinstance(positions_value, Sequence)
            and not isinstance(positions_value, (str, bytes))
            else []
        )
        if not positions and positions_value not in ([], ()):
            blockers.append("okx_demo_fresh_state_positions_invalid")
        nonzero_positions: list[Mapping[str, Any]] = []
        for row in positions:
            if not isinstance(row, Mapping):
                blockers.append("okx_demo_fresh_state_position_row_invalid")
                continue
            if str(row.get("instrument_id") or "") != OKX_DEMO_INSTRUMENT_ID:
                blockers.append("okx_demo_fresh_state_position_instrument_mismatch")
            if str(row.get("margin_mode") or "") != "isolated":
                blockers.append("okx_demo_fresh_state_position_margin_mode_invalid")
            try:
                quantity = _strict_position_quantity(row)
            except OkxDemoPaperRuntimeError as exc:
                blockers.append(_safe_error(exc))
                continue
            if quantity > 0:
                nonzero_positions.append(row)
                if str(row.get("position_side") or "") != "long":
                    blockers.append("okx_demo_fresh_state_position_must_be_single_long")
                if _decimal(row.get("liquidation_price")) <= 0:
                    blockers.append("okx_demo_fresh_state_liquidation_price_missing")
        try:
            signed = _signed_position(positions)
            gross = _gross_position_contracts(positions)
        except OkxDemoPaperRuntimeError as exc:
            signed = Decimal("NaN")
            gross = Decimal("NaN")
            blockers.append(_safe_error(exc))
        else:
            _, configured_max_net, _ = self._configured_limits()
            if len(nonzero_positions) != 1 or signed <= 0 or gross <= 0:
                blockers.append("okx_demo_fresh_state_single_long_required")
            if gross > OKX_DEMO_PAPER_MAX_NET_CONTRACTS or gross > configured_max_net:
                blockers.append("okx_demo_fresh_state_position_exceeds_cap")
            if gross != signed:
                blockers.append("okx_demo_fresh_state_position_shape_invalid")
            if gross % OKX_DEMO_PAPER_CONTRACTS != 0:
                blockers.append("okx_demo_fresh_state_position_lot_invalid")

        pending_orders = snapshot.get("pending_orders")
        if not isinstance(pending_orders, Sequence) or isinstance(
            pending_orders, (str, bytes)
        ):
            blockers.append("okx_demo_fresh_state_pending_orders_invalid")
        elif pending_orders:
            blockers.append("okx_demo_fresh_state_pending_order_present")

        for field in ("orders", "fills", "bills"):
            rows = snapshot.get(field)
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                blockers.append(f"okx_demo_fresh_state_{field}_invalid")

        pending_algos = snapshot.get("pending_algo_orders")
        if not isinstance(pending_algos, Sequence) or isinstance(
            pending_algos, (str, bytes)
        ):
            blockers.append("okx_demo_fresh_state_pending_algos_invalid")
            pending_algos = []
        owned_pairs = self._owned_algo_pairs()
        owners = _mapping(
            _mapping(self._state.get("risk_control")).get(
                "owned_attached_algos"
            )
        )
        fixed_algo_pair = (
            str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_id"]),
            str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_cl_ord_id"]),
        )
        dynamic_projection_pair = self._fresh_state_emergency_verified_projection_pair(
            verified_ownership_proof
        )
        for row in pending_algos:
            if not isinstance(row, Mapping):
                blockers.append("okx_demo_fresh_state_algo_row_invalid")
                continue
            pair = (
                str(row.get("algo_id") or ""),
                str(row.get("algo_client_order_id") or ""),
            )
            observed_parent = str(row.get("parent_client_order_id") or "")
            fixed_parentless_projection = (
                pair == fixed_algo_pair
                and not observed_parent
                and not owners
            )
            dynamic_projection = pair == dynamic_projection_pair
            if not all(pair) or (
                pair not in owned_pairs
                and not fixed_parentless_projection
                and not dynamic_projection
            ):
                blockers.append("okx_demo_fresh_state_foreign_algo_present")
                continue
            owner = _mapping(owners.get(pair[1]))
            if not fixed_parentless_projection and not dynamic_projection and not owner:
                blockers.append("okx_demo_fresh_state_algo_owner_missing")
                continue
            if owner and (
                owner.get("opening_intent") is not True
                or str(owner.get("instrument_id") or "")
                != OKX_DEMO_INSTRUMENT_ID
            ):
                blockers.append("okx_demo_fresh_state_algo_owner_invalid")
            if observed_parent not in {
                "",
                str(owner.get("parent_client_order_id") or ""),
            }:
                blockers.append("okx_demo_fresh_state_algo_parent_mismatch")
            if str(row.get("position_side") or "") != "long":
                blockers.append("okx_demo_fresh_state_algo_position_side_invalid")
            if "order_type" in row and str(row.get("order_type") or "") != "oco":
                blockers.append("okx_demo_fresh_state_algo_type_invalid")
            if _decimal(row.get("size")) != gross or gross <= 0:
                blockers.append("okx_demo_fresh_state_algo_size_mismatch")
            if str(row.get("state") or "") not in {
                "live",
                "effective",
                "partially_effective",
            }:
                blockers.append("okx_demo_fresh_state_algo_not_active")
            if str(row.get("take_profit_order_price") or "") != "-1" or str(
                row.get("stop_loss_order_price") or ""
            ) != "-1":
                blockers.append("okx_demo_fresh_state_algo_not_reduce_only")
            if "reduce_only" in row and row.get("reduce_only") is not True:
                blockers.append("okx_demo_fresh_state_algo_not_reduce_only")

        pending_intents = _mapping(
            _mapping(self._state.get("risk_control")).get(
                "pending_order_intents"
            )
        )
        for client_order_id, intent in pending_intents.items():
            if not isinstance(intent, Mapping) or str(
                intent.get("status") or ""
            ) not in OKX_DEMO_TERMINAL_INTENT_STATUSES:
                blockers.append(
                    "okx_demo_fresh_state_unresolved_intent:" + str(client_order_id)
                )
        if _mapping(
            _mapping(self._state.get("risk_control")).get(
                "incident_recovery_intents"
            )
        ):
            blockers.append("okx_demo_fresh_state_historical_binding_forbidden")

        # Reuse the normal market/account freshness checks, but do not make
        # the emergency path depend on a pre-existing protection projection;
        # ownership and market-exit semantics above are checked from the fresh
        # algo rows and durable owner records instead.
        try:
            normal_blockers = self._preflight_blockers(snapshot, require_flat=False)
        except Exception as exc:
            normal_blockers = [_safe_error(exc)]
        protection_only_prefixes = (
            "okx_demo_nonflat_position_has_no_verified_protection",
            "okx_demo_verified_protection_missing_from_exchange_pending",
            "okx_demo_exchange_protection_",
        )
        blockers.extend(
            blocker
            for blocker in normal_blockers
            if not str(blocker).startswith(protection_only_prefixes)
        )
        return _dedupe(blockers)

    def _fresh_state_emergency_private_ws_blockers(self) -> list[str]:
        private_ws = self._private_ws
        if private_ws is None:
            return ["okx_demo_fresh_state_private_ws_missing"]
        if not hasattr(private_ws, "reconcile_current") or not hasattr(
            private_ws, "status"
        ):
            return ["okx_demo_fresh_state_private_ws_reconciliation_unavailable"]
        try:
            receipt = private_ws.reconcile_current()
            status = private_ws.status()
        except Exception as exc:
            return [
                "okx_demo_fresh_state_private_ws_reconciliation_failed:"
                + _safe_error(exc)
            ]
        if not isinstance(receipt, Mapping) or not isinstance(status, Mapping):
            return ["okx_demo_fresh_state_private_ws_receipt_invalid"]
        required = (
            "connected",
            "listener_alive",
            "reconnect_login_observed",
            "reconnect_resubscribed",
            "reconnect_rest_reconciled",
            "opening_allowed_after_reconciliation",
        )
        blockers = [
            "okx_demo_fresh_state_private_ws_not_current:" + field
            for field in required
            if receipt.get(field) is not True or status.get(field) is not True
        ]
        source_head = str(receipt.get("source_head") or "")
        if source_head and source_head != _repo_head(self.config.repo_root):
            blockers.append("okx_demo_fresh_state_private_ws_source_head_mismatch")
        return _dedupe(blockers)

    def _run_risk_reduction_cycle(
        self,
        client: OkxDemoClient,
        *,
        strategy: Mapping[str, Any],
        emergency_exit: bool = False,
        emergency_operator_payload: Mapping[str, Any] | None = None,
        emergency_prior_run_id: str = "",
        emergency_run_id: str = "",
        emergency_owner_marker_audit: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            snapshot = self._collect_exchange_snapshot(client)
            if emergency_exit:
                intent_blockers: list[str] = []
                identity_blockers: list[str] = []
                ownership_proof: dict[str, Any] | None = None
                if emergency_operator_payload is not None:
                    identity_blockers, ownership_proof = (
                        self._fresh_state_emergency_identity_projection(
                            snapshot,
                            emergency_operator_payload,
                        )
                    )
                snapshot_blockers = self._fresh_state_emergency_snapshot_blockers(
                    snapshot,
                    verified_ownership_proof=ownership_proof,
                )
                if snapshot_blockers:
                    raise OkxDemoPaperRuntimeError(";".join(snapshot_blockers))
                if identity_blockers:
                    raise OkxDemoPaperRuntimeError(";".join(identity_blockers))
                private_ws_blockers = self._fresh_state_emergency_private_ws_blockers()
                if private_ws_blockers:
                    raise OkxDemoPaperRuntimeError(";".join(private_ws_blockers))
                authorization = self._fresh_state_emergency_exit_authorization
                if isinstance(authorization, dict):
                    authorization["private_ws_generation"] = str(
                        self._private_ws_generation
                    )
            else:
                intent_blockers = self._reconcile_ambiguous_order_intents(
                    client,
                    snapshot,
                )
                if (
                    not intent_blockers
                    and str(
                        _mapping(self._state.get("runtime")).get(
                            "stop_and_flatten", {}
                        ).get("status")
                        or ""
                    )
                    == "preflight"
                ):
                    intent_blockers = self._stop_and_flatten_snapshot_blockers(
                        snapshot
                    )
            if intent_blockers:
                raise OkxDemoPaperRuntimeError(";".join(intent_blockers))
            positions = snapshot.get("positions", [])
            current_quantity = _signed_position(positions)
            gross_quantity = _gross_position_contracts(positions)
            _, max_net_contracts, _ = self._configured_limits()
            unknown_pending = [
                row
                for row in snapshot.get("pending_orders", [])
                if str(row.get("client_order_id") or "")
                not in self._owned_client_order_ids
            ]
            if gross_quantity > max_net_contracts:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_gross_position_exceeds_cap"
                )
            if gross_quantity > abs(current_quantity):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_hedged_position_shape_unsupported"
                )
            if unknown_pending:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_unknown_pending_order_present"
                )
            with self._lock:
                self._apply_snapshot(snapshot)
            self._commit_ledger_reconciliation(
                snapshot=snapshot,
                trigger="risk_reduction_preflight",
            )
            if emergency_exit:
                with self._lock:
                    ledger = _mapping(self._state.get("ledger_reconciliation"))
                if not (
                    ledger.get("status") == "reconciled"
                    and ledger.get("current_state_exchange_snapshot_match") is True
                    and ledger.get("funding_cashflow_reconciled") is True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fresh_state_ledger_not_current"
                    )
            if emergency_exit and emergency_operator_payload is not None:
                self._record_fresh_state_emergency_projection(
                    snapshot=snapshot,
                    operator_payload=emergency_operator_payload,
                    prior_run_id=emergency_prior_run_id,
                    run_id=emergency_run_id
                    or str(self._state.get("runtime", {}).get("run_id") or ""),
                    owner_marker_audit=emergency_owner_marker_audit or {},
                )
            self._arm_dead_man(client, trigger="risk_reduction_preflight")
            if not self._write_path_is_trusted():
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_risk_reduction_write_path_not_trusted"
                )
            if gross_quantity == 0:
                with self._lock:
                    self._append_event(
                        "risk_reduction_flat_no_order",
                        {"opening_allowed": False},
                    )
                    self._persist_state()
                return self.status()
            order_plan = self._build_order_plan(
                snapshot,
                current_quantity=current_quantity,
                target_quantity=Decimal("0"),
            )
            if (
                order_plan is None
                or order_plan.get("risk_reducing_only") is not True
                or not str(order_plan.get("action") or "").startswith("close_")
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_risk_reduction_plan_not_close_only"
                )
            decision = {
                **dict(self._state.get("signal", {})),
                "strategy_id": str(strategy.get("strategy_id") or ""),
                "direction": "flat",
                "raw_signal": 0,
                "target_contracts": "0",
                "decision_bar_close_utc": _iso(self._clock()),
            }
            if emergency_exit:
                authorization = self._fresh_state_emergency_exit_authorization
                if not isinstance(authorization, dict) or not authorization.get(
                    "nonce"
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fresh_state_emergency_exit_authorization_missing"
                    )
                authorization["client_order_id"] = str(
                    order_plan.get("client_order_id") or ""
                )
                with self._lock:
                    emergency_marker = self._state["runtime"].setdefault(
                        "fresh_state_emergency_exit", {}
                    )
                    emergency_marker.update(
                        {
                            "status": "post_authorized",
                            "post_attempts": 1,
                            "client_order_id": authorization["client_order_id"],
                        }
                    )
                    self._persist_state()
            with self._execution_lock:
                submit_result = self._submit_order_plan(
                    client,
                    snapshot=snapshot,
                    decision=decision,
                    order_plan=order_plan,
                    emergency_exit=emergency_exit,
                )
            return submit_result if emergency_exit else self.status()
        except Exception as exc:
            reason = _safe_error(exc)
            with self._lock:
                requires_frozen_unknown = reason in {
                    "okx_demo_paper_gross_position_exceeds_cap",
                    "okx_demo_paper_hedged_position_shape_unsupported",
                    "okx_demo_paper_position_contracts_invalid",
                    "okx_demo_paper_position_side_unknown",
                    "okx_demo_paper_unknown_pending_order_present",
                } or reason.startswith(
                    "okx_demo_ambiguous_"
                ) or "unresolved_intent" in reason
                if emergency_exit:
                    self._enter_cancel_only(reason, active=False)
                elif self._write_path_is_trusted() and not requires_frozen_unknown:
                    self._set_risk_mode(OKX_DEMO_RISK_MODE_REDUCING, reason)
                else:
                    self._set_risk_mode(OKX_DEMO_RISK_MODE_FROZEN, reason)
                self._append_safety_alert(reason)
                self._append_event(
                    "risk_reduction_cycle_failed",
                    {"error": reason},
                )
                self._persist_state()
            raise OkxDemoPaperRuntimeError(reason) from exc

    @_runtime_writer_fresh_emergency_operation
    def emergency_reduce_only_exit(
        self,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one explicitly confirmed fresh-state Demo flattening.

        This is the only public path that may submit a reduce-only order while
        the runtime is ``active=False``/``FROZEN_UNKNOWN``.  It requires an
        already authenticated client and private-WS session, performs fresh
        REST/WS/ledger checks, and never starts a worker or restores opening
        capability.  A second invocation is rejected after the durable
        one-shot marker is created, regardless of whether the first attempt
        succeeded or became ambiguous.
        """

        operator_payload = self._validate_fresh_state_emergency_operator_payload(
            payload
        )
        if (
            str(operator_payload.get("confirmation_text") or "")
            != OKX_DEMO_PAPER_CONFIRMATION
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_confirmation_text_invalid"
            )

        with self._lock:
            runtime = self._state.get("runtime", {})
            risk = self._state.get("risk_control", {})
            marker = _mapping(runtime.get("fresh_state_emergency_exit"))
            if str(marker.get("status") or "not_attempted") != "not_attempted":
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_already_attempted"
                )
            state_blockers: list[str] = []
            if runtime.get("active") is not False:
                state_blockers.append("okx_demo_fresh_state_runtime_must_be_inactive")
            if runtime.get("opening_allowed") is not False:
                state_blockers.append("okx_demo_fresh_state_opening_must_remain_blocked")
            if runtime.get("cancel_only") is not True:
                state_blockers.append("okx_demo_fresh_state_cancel_only_required")
            if risk.get("mode") != OKX_DEMO_RISK_MODE_FROZEN:
                state_blockers.append("okx_demo_fresh_state_frozen_unknown_required")
            safety = _mapping(self._state.get("safety"))
            if safety.get("okx_demo_order_capability_enabled") is True:
                state_blockers.append(
                    "okx_demo_fresh_state_order_capability_must_be_disabled"
                )
            if any(
                safety.get(field) is True
                for field in (
                    "live_order_allowed",
                    "real_money_order_allowed",
                    "transfer_allowed",
                    "withdraw_allowed",
                )
            ):
                state_blockers.append("okx_demo_fresh_state_unsafe_capability_present")
            if self._stop_event.is_set():
                state_blockers.append("okx_demo_fresh_state_runtime_stop_set")
            if self._thread is not None and self._thread.is_alive():
                state_blockers.append("okx_demo_fresh_state_worker_must_not_be_alive")
            if self._dead_man_thread is not None and self._dead_man_thread.is_alive():
                state_blockers.append("okx_demo_fresh_state_dead_man_worker_must_not_be_alive")
            client = self._client
            private_ws = self._private_ws
            strategy = dict(self._state.get("strategy", {}))
            prior_run_id = str(runtime.get("run_id") or "")
            owned_restore = _mapping(risk.get("owned_id_restore"))
            if owned_restore.get("enabled") is True or owned_restore.get(
                "owned_triples"
            ):
                state_blockers.append("okx_demo_fresh_state_historical_binding_forbidden")
            if state_blockers:
                raise OkxDemoPaperRuntimeError(";".join(_dedupe(state_blockers)))
            run_id = uuid.uuid4().hex
            self._sequence = 0
            self._state["runtime"]["run_id"] = run_id
            self._state["runtime"]["order_sequence"] = 0
            if not strategy:
                strategy = {"strategy_id": OKX_NATIVE_STRATEGY_LINE}
            owner_marker_audit = dict(
                self._fresh_state_emergency_owner_marker_audit or {}
            )
            self._state["runtime"]["fresh_state_emergency_exit"] = {
                "status": "preflight",
                "post_attempts": 0,
                "client_order_id": "",
                "final_flat": False,
                "started_at_utc": _iso(self._clock()),
                "run_id": run_id,
                "identity_only": True,
                "opening_allowed": False,
                "paper_allowed": False,
                "promotion_evidence_ready": False,
                "live_allowed": False,
                "owner_marker_audit": owner_marker_audit,
                "projection": {},
            }
            self._persist_state()
            self._fresh_state_emergency_exit_authorization = {
                "nonce": uuid.uuid4().hex,
                "client_order_id": "",
                "private_ws_generation": str(self._private_ws_generation),
            }

        try:
            if client is None or private_ws is None:
                self._bootstrap_fresh_state_emergency_session(
                    operator_payload=operator_payload,
                    owner_marker_audit=owner_marker_audit,
                )
                client = self._client
                private_ws = self._private_ws
            if client is None or private_ws is None:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_bootstrap_session_missing"
                )
            # _run_risk_reduction_cycle owns the same fresh REST snapshot,
            # private-WS reconciliation, dead-man arm and durable submit path
            # used by normal risk reduction.  The emergency flag only changes
            # the final frozen-mode permission fence.
            submit_result = self._run_risk_reduction_cycle(
                client,
                strategy=strategy,
                emergency_exit=True,
                emergency_operator_payload=operator_payload,
                emergency_prior_run_id=prior_run_id,
                emergency_run_id=run_id,
                emergency_owner_marker_audit=owner_marker_audit,
            )
            if not isinstance(submit_result, Mapping) or int(
                submit_result.get("orders_posted") or 0
            ) != 1:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_order_attempt_missing"
                )

            final_snapshot = self._collect_exchange_snapshot(client)
            final_snapshot, algo_cleanup = self._cleanup_owned_flat_algos(
                client,
                snapshot=final_snapshot,
            )
            ws_blockers = self._fresh_state_emergency_private_ws_blockers()
            if ws_blockers:
                raise OkxDemoPaperRuntimeError(";".join(ws_blockers))
            final_snapshot = self._collect_exchange_snapshot(client)
            try:
                final_gross = _gross_position_contracts(
                    final_snapshot.get("positions", [])
                )
            except OkxDemoPaperRuntimeError as exc:
                raise OkxDemoPaperRuntimeError(_safe_error(exc)) from exc
            if final_gross != 0:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_position_not_flat"
                )
            if final_snapshot.get("pending_orders"):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_pending_order_present"
                )
            if final_snapshot.get("pending_algo_orders"):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_pending_algo_present"
                )
            with self._lock:
                self._apply_snapshot(final_snapshot)
            self._commit_ledger_reconciliation(
                snapshot=final_snapshot,
                trigger="fresh_state_emergency_exit_final_reconciliation",
            )
            with self._lock:
                ledger = _mapping(self._state.get("ledger_reconciliation"))
                if not (
                    ledger.get("status") == "reconciled"
                    and ledger.get("current_state_exchange_snapshot_match") is True
                    and ledger.get("funding_cashflow_reconciled") is True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_fresh_state_emergency_exit_ledger_not_current"
                    )
                postflight_blockers = self._fault_drill_postflight_blockers(
                    final_snapshot
                )
            if postflight_blockers:
                raise OkxDemoPaperRuntimeError(";".join(postflight_blockers))

            disarm_blockers = self._disarm_dead_man_if_safe(
                client,
                stop_query_current=True,
            )
            if disarm_blockers:
                raise OkxDemoPaperRuntimeError(";".join(disarm_blockers))
            stop_receipt = private_ws.stop()
            stopped_status = private_ws.status() if hasattr(private_ws, "status") else {}
            if isinstance(stop_receipt, Mapping) and stop_receipt.get(
                "listener_joined"
            ) is False:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_private_ws_stop_failed"
                )
            if not isinstance(stopped_status, Mapping) or not (
                stopped_status.get("connected") is False
                and stopped_status.get("listener_alive") is False
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fresh_state_emergency_exit_private_ws_still_alive"
                )

            close_client_order_id = str(
                submit_result.get("client_order_id")
                or submit_result.get("clOrdId")
                or ""
            )
            with self._lock:
                emergency_marker = self._state["runtime"][
                    "fresh_state_emergency_exit"
                ]
                emergency_marker.update(
                    {
                        "status": "completed",
                        "post_attempts": 1,
                        "client_order_id": close_client_order_id,
                        "exchange_order_id": str(
                            submit_result.get("exchange_order_id") or ""
                        ),
                        "final_flat": True,
                        "algo_cleanup": dict(algo_cleanup),
                        "private_ws_reconciled": True,
                        "private_ws_stopped": True,
                        "ledger_reconciled": True,
                        "completed_at_utc": _iso(self._clock()),
                    }
                )
                self._state["runtime"].update(
                    {
                        "active": False,
                        "opening_allowed": False,
                        "cancel_only": True,
                        "status": "fresh_state_emergency_exit_completed",
                        "last_error": "",
                    }
                )
                self._state["risk_control"]["write_path_trusted"] = False
                self._state["risk_control"]["dead_man"].update(
                    {"armed": False, "watchdog_renews_dead_man": False}
                )
                self._state["private_ws"].update(
                    {
                        "status": "stopped_after_fresh_state_emergency_exit",
                        "connected": False,
                        "listener_alive": False,
                        "opening_allowed_after_reconciliation": False,
                    }
                )
                self._state["safety"].update(
                    {
                        "okx_demo_private_read_enabled": False,
                        "okx_demo_order_capability_enabled": False,
                        "okx_demo_cancel_capability_enabled": False,
                    }
                )
                self._append_event(
                    "fresh_state_emergency_reduce_only_exit_completed",
                    {
                        "client_order_id": close_client_order_id,
                        "orders_posted": 1,
                        "final_flat": True,
                        "private_ws_stopped": True,
                        "ledger_reconciled": True,
                        "opening_allowed": False,
                        "live_allowed": False,
                    },
                )
                self._persist_state()
            return {
                "decision": "fresh_state_emergency_reduce_only_exit_completed",
                **dict(submit_result),
                "orders_posted": 1,
                "final_flat": True,
                "final_no_pending_orders": True,
                "final_no_pending_algo_orders": True,
                "algo_cleanup": dict(algo_cleanup),
                "private_ws_reconciled": True,
                "private_ws_stopped": True,
                "ledger_reconciled": True,
                "opening_allowed": False,
                "cancel_only": True,
                "risk_mode": OKX_DEMO_RISK_MODE_FROZEN,
                "live_allowed": False,
                "simulation_only": False,
            }
        except Exception as exc:
            reason = _safe_error(exc)
            with self._lock:
                probe_diagnostics = _project_probe_diagnostics(
                    self._state.get("runtime", {}).get("probe_diagnostics")
                )
                self._enter_cancel_only(reason, active=False)
                marker = self._state["runtime"].setdefault(
                    "fresh_state_emergency_exit", {}
                )
                marker.update(
                    {
                        "status": "blocked",
                        "final_flat": False,
                        "last_error": reason,
                        "probe_diagnostics": json.loads(
                            json.dumps(probe_diagnostics)
                        ),
                    }
                )
                self._append_safety_alert(reason)
                if probe_diagnostics:
                    self._state["runtime"]["last_error_detail"] = {
                        "error": reason,
                        "probe_diagnostics": json.loads(
                            json.dumps(probe_diagnostics)
                        ),
                        "credentials_redacted": True,
                    }
                    self._state["risk_control"]["alerts"][0][
                        "probe_diagnostics"
                    ] = json.loads(json.dumps(probe_diagnostics))
                self._append_event(
                    "fresh_state_emergency_reduce_only_exit_blocked",
                    {
                        "error": reason,
                        "orders_posted": int(marker.get("post_attempts") or 0),
                        "blind_retry_allowed": False,
                        "opening_allowed": False,
                        "cancel_only": True,
                        "probe_diagnostics": json.loads(
                            json.dumps(probe_diagnostics)
                        ),
                    },
                )
                self._persist_state()
            raise OkxDemoPaperRuntimeError(reason) from exc
        finally:
            self._fresh_state_emergency_exit_authorization = None

    def _degrade_after_cycle_error(self, reason: str, *, recoverable: bool) -> None:
        ledger_ok = (
            self._state.get("ledger_reconciliation", {}).get("status")
            == "reconciled"
            and self._state.get("ledger_reconciliation", {}).get(
                "current_state_exchange_snapshot_match"
            )
            is True
        )
        unresolved_intent = any(
            isinstance(row, Mapping)
            and str(row.get("status") or "")
            in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
            for row in _mapping(
                self._state.get("risk_control", {}).get(
                    "pending_order_intents"
                )
            ).values()
        )
        if self._write_path_is_trusted() and ledger_ok and not unresolved_intent:
            mode = OKX_DEMO_RISK_MODE_REDUCING
        else:
            mode = OKX_DEMO_RISK_MODE_FROZEN
        self._set_risk_mode(mode, reason)
        self._state["runtime"]["last_error"] = reason
        self._state["runtime"]["blockers"] = _dedupe(
            [*self._state["runtime"].get("blockers", []), reason]
        )
        if not recoverable or mode == OKX_DEMO_RISK_MODE_FROZEN:
            self._append_safety_alert(reason)

    def _start_worker_thread(self, *, reason: str) -> bool:
        """Start at most one authoritative worker generation.

        This helper is used by both startup and the transient recovery
        supervisor.  The generation is persisted before the thread is
        started, so a restart cannot silently create two workers or lose the
        ownership boundary during a process race.
        """

        with self._lock:
            runtime = self._state["runtime"]
            current = self._thread
            if (
                self._stop_event.is_set()
                or not self._start_worker
                or str(runtime.get("fault_drill_scenario") or "")
                == "partial_fill_disconnect"
                or runtime.get("active") is not True
                or (current is not None and current.is_alive())
            ):
                return False
            generation = int(runtime.get("worker_generation") or 0) + 1
            runtime["worker_generation"] = generation
            runtime["worker_recovery"] = {
                **_mapping(runtime.get("worker_recovery")),
                "status": "starting" if reason == "startup" else "restarting",
                "worker_generation": generation,
                "last_error": "",
            }
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"btc-okx-demo-paper-{generation}",
                daemon=True,
            )
            self._thread = thread
        try:
            thread.start()
        except Exception as exc:
            with self._lock:
                runtime = self._state["runtime"]
                runtime["worker_recovery"] = {
                    **_mapping(runtime.get("worker_recovery")),
                    "status": "failed",
                    "last_error": _safe_error(exc),
                }
                self._thread = None
                self._persist_state()
            raise OkxDemoPaperRuntimeError(
                "okx_demo_authoritative_liveness_worker_start_failed:"
                + _safe_error(exc)
            ) from exc
        return True

    def _mark_transient_recovery(
        self,
        *,
        status: str,
        fault: str = "",
        error: str = "",
    ) -> None:
        with self._lock:
            runtime = self._state["runtime"]
            recovery = {
                **_mapping(runtime.get("worker_recovery")),
                "status": status,
            }
            if fault:
                recovery["last_fault"] = fault[:500]
            if error:
                recovery["last_error"] = error[:500]
            elif status == "recovered":
                recovery["attempts"] = 0
                recovery["last_error"] = ""
                recovery["last_fault"] = ""
                recovery["last_recovered_at_utc"] = _iso(self._clock())
            runtime["worker_recovery"] = recovery

    def _attempt_transient_recovery(
        self,
        *,
        fault: str,
    ) -> bool:
        """Run one bounded, read/reconcile/dead-man recovery attempt."""

        with self._lock:
            runtime = self._state["runtime"]
            recovery = {
                **_mapping(runtime.get("worker_recovery")),
            }
            attempts = int(recovery.get("attempts") or 0)
            if attempts >= OKX_DEMO_TRANSIENT_RECOVERY_MAX_ATTEMPTS:
                recovery["status"] = "exhausted"
                recovery["last_error"] = "okx_demo_transient_recovery_attempts_exhausted"
                runtime["worker_recovery"] = recovery
                self._persist_state()
                return False
            delay = OKX_DEMO_TRANSIENT_RECOVERY_BACKOFF_SECONDS[attempts]
            recovery.update(
                {
                    "status": "retrying",
                    "attempts": attempts + 1,
                    "last_fault": fault[:500],
                    "last_error": "",
                }
            )
            runtime["worker_recovery"] = recovery
            self._persist_state()
        if self._stop_event.wait(delay):
            return False
        try:
            self._recover_transient_cycle(resume_opening=True)
        except Exception as exc:
            self._mark_transient_recovery(
                status="pending",
                fault=fault,
                error=_safe_error(exc),
            )
            return False
        self._mark_transient_recovery(status="recovered")
        return True

    def _recover_transient_cycle(self, *, resume_opening: bool = True) -> None:
        if not self._transient_recovery_lock.acquire(blocking=False):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_transient:recovery_already_in_progress"
            )
        try:
            self._recover_transient_cycle_impl(resume_opening=resume_opening)
        finally:
            self._transient_recovery_lock.release()

    def _worker_loop(self) -> None:
        with self._lock:
            self._state["runtime"]["worker_alive"] = True
            self._state["runtime"]["last_heartbeat_utc"] = _iso(
                self._clock()
            )
            recovery = _mapping(self._state["runtime"].get("worker_recovery"))
            if recovery.get("status") == "starting":
                self._state["runtime"]["worker_recovery"] = {
                    **recovery,
                    "status": "healthy",
                }
            self._persist_state()
        try:
            while not self._stop_event.is_set():
                try:
                    with self._lock:
                        risk_mode_before = str(
                            self._state["risk_control"].get("mode") or ""
                        )
                    if risk_mode_before == OKX_DEMO_RISK_MODE_FROZEN:
                        self._recover_transient_cycle()
                    else:
                        self.run_cycle()
                except OkxDemoPaperRuntimeError as exc:
                    with self._lock:
                        self._state["runtime"]["last_error"] = _safe_error(exc)
                        risk_mode_after = str(
                            self._state["risk_control"].get("mode") or ""
                        )
                    newly_degraded_to_risk_reducing = (
                        risk_mode_before == OKX_DEMO_RISK_MODE_RUNNING
                        and risk_mode_after == OKX_DEMO_RISK_MODE_REDUCING
                    )
                    if (
                        not newly_degraded_to_risk_reducing
                        and not _is_recoverable_cycle_error(exc)
                    ):
                        return
                with self._lock:
                    self._state["runtime"]["last_heartbeat_utc"] = _iso(
                        self._clock()
                    )
                    self._persist_state()
                if self._stop_event.wait(self.config.poll_interval_seconds):
                    return
        finally:
            with self._lock:
                self._state["runtime"]["worker_alive"] = False
                if (
                    self._state["runtime"].get("active") is True
                    and self._state["runtime"].get(
                        "authoritative_liveness_required"
                    ) is True
                    and not self._stop_event.is_set()
                ):
                    reason = "okx_demo_authoritative_liveness_worker_stopped"
                    self._state["risk_control"][
                        "write_path_trusted"
                    ] = False
                    self._state["runtime"]["worker_recovery"] = {
                        **_mapping(self._state["runtime"].get("worker_recovery")),
                        "status": "pending",
                        "last_fault": reason,
                    }
                    self._enter_cancel_only(reason, active=True)
                    self._append_event(
                        "authoritative_liveness_worker_stopped",
                        {"error": reason},
                    )
                self._persist_state()

    def _recover_transient_cycle_impl(self, *, resume_opening: bool = True) -> None:
        with self._lock:
            client = self._client
            private_ws = self._private_ws
            active = self._state["runtime"]["active"] is True
        if not active or client is None or private_ws is None:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_transient:recovery_dependencies_missing"
            )
        try:
            snapshot = self._collect_exchange_snapshot(client)
            blockers = [
                *self._reconcile_ambiguous_order_intents(client, snapshot),
                *self._preflight_blockers(snapshot, require_flat=False),
            ]
            if blockers:
                raise OkxDemoPaperRuntimeError(";".join(blockers))
            if not hasattr(private_ws, "reconcile_current"):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_current_reconciliation_unavailable"
                )
            with self._lock:
                private_ws_generation = self._private_ws_generation
            receipt = private_ws.reconcile_current()
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("connected") is not True
                or receipt.get("listener_alive") is not True
                or receipt.get("opening_allowed_after_reconciliation") is not True
            ):
                receipt_blockers = (
                    [str(row) for row in receipt.get("blockers") or []]
                    if isinstance(receipt, Mapping)
                    else []
                )
                blocker_suffix = (
                    f":{','.join(receipt_blockers)}" if receipt_blockers else ""
                )
                if _private_ws_reconciliation_receipt_is_transient(receipt):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_transient:"
                        "okx_demo_private_ws_current_reconciliation_failed"
                        f"{blocker_suffix}"
                    )
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_current_reconciliation_failed"
                    f"{blocker_suffix}"
                )
            if not hasattr(private_ws, "status"):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_current_status_unavailable"
                )
            prearm_private_ws = private_ws.status()
            if not isinstance(prearm_private_ws, Mapping) or not (
                prearm_private_ws.get("connected") is True
                and prearm_private_ws.get("listener_alive") is True
                and prearm_private_ws.get(
                    "opening_allowed_after_reconciliation"
                )
                is True
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_changed_after_reconciliation"
                )
            with self._lock:
                if (
                    self._client is not client
                    or self._private_ws is not private_ws
                    or self._private_ws_generation != private_ws_generation
                    or self._state["runtime"].get("active") is not True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_private_ws_generation_changed_during_recovery"
                    )
                refreshed_private_ws = dict(receipt)
                refreshed_private_ws.update(dict(prearm_private_ws))
                refreshed_private_ws["controller_generation"] = (
                    self._private_ws_generation
                )
                self._state["private_ws"] = json.loads(
                    json.dumps(refreshed_private_ws)
                )
                self._apply_snapshot(snapshot)
            self._commit_ledger_reconciliation(
                snapshot=snapshot,
                trigger="frozen_state_reconciliation",
            )
            self._arm_dead_man(client, trigger="frozen_state_reconciliation")
            # The exchange/WS/ledger/dead-man gates are now authoritative.  A
            # stopped worker is recreated exactly once at this point; no
            # opening permission is projected before the thread is alive.
            with self._lock:
                worker_required = (
                    self._state["runtime"].get(
                        "authoritative_liveness_worker_required"
                    )
                    is True
                )
                worker_missing = worker_required and not (
                    self._thread is not None and self._thread.is_alive()
                )
            if resume_opening and worker_missing:
                if not self._start_worker_thread(reason="transient_recovery"):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_authoritative_liveness_worker_restart_unavailable"
                    )
            if (
                resume_opening
                and self.config.execution_dispatcher is not None
            ):
                if self._boundary_snapshot_requires_refresh(snapshot):
                    snapshot = self._collect_exchange_snapshot(client)
                    opening_blockers = [
                        *self._reconcile_ambiguous_order_intents(
                            client,
                            snapshot,
                        ),
                        *self._preflight_blockers(
                            snapshot,
                            require_flat=False,
                        ),
                    ]
                    if opening_blockers:
                        raise OkxDemoPaperRuntimeError(
                            ";".join(opening_blockers)
                        )
                    self._commit_ledger_reconciliation(
                        snapshot=snapshot,
                        trigger="frozen_state_opening_snapshot_refresh",
                        apply_snapshot=True,
                    )
                if self._boundary_snapshot_requires_refresh(snapshot):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_transient:"
                        "okx_demo_authoritative_opening_snapshot_stale"
                    )
            with self._lock:
                if self._private_ws_generation != private_ws_generation:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_private_ws_generation_changed_during_recovery"
                    )
                current_private_ws = private_ws.status()
                if not isinstance(current_private_ws, Mapping) or not (
                    current_private_ws.get("connected") is True
                    and current_private_ws.get("listener_alive") is True
                    and current_private_ws.get(
                        "opening_allowed_after_reconciliation"
                    )
                    is True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_private_ws_changed_after_reconciliation"
                    )
                if resume_opening and not self._write_path_is_trusted():
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_authoritative_liveness_recovery_untrusted"
                    )
                retained = [
                    blocker
                    for blocker in self._state["runtime"].get("blockers", [])
                    if not str(blocker).startswith("okx_demo_transient:")
                    and not str(blocker).startswith("okx_demo_private_ws:")
                    and not _is_transient_liveness_message(str(blocker))
                    and str(blocker)
                    != "okx_demo_private_ws_reconciled_full_reconciliation_pending"
                ]
                recovered_mode = (
                    OKX_DEMO_RISK_MODE_RUNNING
                    if resume_opening and not retained
                    else OKX_DEMO_RISK_MODE_REDUCING
                    if not retained
                    else OKX_DEMO_RISK_MODE_FROZEN
                )
                self._state["runtime"].update(
                    {
                        "blockers": retained,
                        "status": (
                            "running"
                            if recovered_mode == OKX_DEMO_RISK_MODE_RUNNING
                            else "risk_reducing_only"
                            if recovered_mode == OKX_DEMO_RISK_MODE_REDUCING
                            else "cancel_only"
                        ),
                        "cancel_only": (
                            recovered_mode != OKX_DEMO_RISK_MODE_RUNNING
                        ),
                        "opening_allowed": (
                            recovered_mode == OKX_DEMO_RISK_MODE_RUNNING
                        ),
                        "last_error": "" if not retained else self._state["runtime"].get("last_error", ""),
                        "last_heartbeat_utc": _iso(self._clock()),
                    }
                )
                self._set_risk_mode(
                    recovered_mode,
                    (
                        "orders_fills_positions_protection_ledger_private_ws_reconciled"
                        if not retained
                        else ";".join(str(row) for row in retained)
                    ),
                )
                refreshed_private_ws = dict(receipt)
                refreshed_private_ws.update(dict(current_private_ws))
                refreshed_private_ws["controller_generation"] = (
                    self._private_ws_generation
                )
                self._state["private_ws"] = json.loads(
                    json.dumps(refreshed_private_ws)
                )
                self._state["runtime"]["worker_recovery"] = {
                    **_mapping(self._state["runtime"].get("worker_recovery")),
                    "status": "recovered",
                    "attempts": 0,
                    "last_error": "",
                    "last_fault": "",
                    "last_recovered_at_utc": _iso(self._clock()),
                    "worker_generation": int(
                        self._state["runtime"].get("worker_generation") or 0
                    ),
                }
                self._append_event(
                    "runtime_transient_recovered",
                    {
                        "snapshot_reconciled": True,
                        "private_ws_reconciled": True,
                        "worker_restarted": bool(worker_missing and resume_opening),
                        "worker_generation": int(
                            self._state["runtime"].get("worker_generation") or 0
                        ),
                        "opening_allowed": (
                            recovered_mode == OKX_DEMO_RISK_MODE_RUNNING
                        ),
                        "risk_reducing_only": (
                            recovered_mode == OKX_DEMO_RISK_MODE_REDUCING
                        ),
                    },
                )
                self._persist_state()
        except Exception as exc:
            reason = _safe_error(exc)
            with self._lock:
                if _is_recoverable_cycle_error(exc) and not reason.startswith(
                    "okx_demo_transient:"
                ):
                    reason = f"okx_demo_transient:{reason}"
                self._enter_cancel_only(reason, active=True)
                self._append_event(
                    "runtime_transient_recovery_failed",
                    {"error": _safe_error(exc)},
                )
                self._persist_state()
            raise OkxDemoPaperRuntimeError(reason) from exc

    def _reconcile_ambiguous_order_intents(
        self,
        client: OkxDemoClient,
        snapshot: Mapping[str, Any],
    ) -> list[str]:
        with self._lock:
            ambiguous = {
                str(client_order_id): dict(row)
                for client_order_id, row in _mapping(
                    self._state.get("risk_control", {}).get(
                        "pending_order_intents"
                    )
                ).items()
                if isinstance(row, Mapping)
                and str(row.get("status") or "")
                in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
            }
        if not ambiguous:
            return []
        blockers: list[str] = []
        resolutions: list[dict[str, Any]] = []
        snapshot_orders = [
            row
            for row in [
                *_sequence_mappings(snapshot.get("orders")),
                *_sequence_mappings(snapshot.get("pending_orders")),
            ]
        ]
        snapshot_fills = _sequence_mappings(snapshot.get("fills"))
        gross_position = _gross_position_contracts(
            snapshot.get("positions", [])
        )
        for client_order_id, pending in ambiguous.items():
            try:
                order = self._query_order_by_client_id(
                    client,
                    client_order_id,
                    allow_missing=True,
                )
            except Exception as exc:
                blockers.append(
                    "okx_demo_ambiguous_order_query_failed:"
                    f"{client_order_id}:{_safe_error(exc)}"
                )
                continue
            related_orders = [
                row
                for row in snapshot_orders
                if _client_order_id(row) == client_order_id
            ]
            order_id = str(order.get("ordId") or order.get("order_id") or "")
            related_fills = [
                row
                for row in snapshot_fills
                if _client_order_id(row) == client_order_id
                or (
                    order_id
                    and str(row.get("ordId") or row.get("order_id") or "")
                    == order_id
                )
            ]
            if order:
                state = str(order.get("state") or "")
                filled_size = _decimal(
                    order.get("accFillSz") or order.get("filled_size")
                )
                if filled_size > 0 and not related_fills:
                    blockers.append(
                        "okx_demo_ambiguous_order_fill_evidence_missing:"
                        f"{client_order_id}"
                    )
                    continue
                if state not in {
                    "live",
                    "partially_filled",
                    "filled",
                    "canceled",
                    "mmp_canceled",
                }:
                    blockers.append(
                        "okx_demo_ambiguous_order_state_unknown:"
                        f"{client_order_id}"
                    )
                    continue
                resolution_status = (
                    "reconciled_terminal"
                    if state in {"filled", "canceled", "mmp_canceled"}
                    else "reconciled_open"
                )
                resolutions.append(
                    {
                        "client_order_id": client_order_id,
                        "status": resolution_status,
                        "exchange_order_id": order_id,
                        "exchange_state": state,
                        "resolution": "direct_clordid_query_plus_snapshot",
                    }
                )
                if resolution_status == "reconciled_open":
                    blockers.append(
                        "okx_demo_ambiguous_order_still_open:"
                        f"{client_order_id}:{state}"
                    )
                continue
            if related_orders or related_fills:
                blockers.append(
                    "okx_demo_ambiguous_order_direct_query_snapshot_conflict:"
                    f"{client_order_id}"
                )
                continue
            blockers.append(
                "okx_demo_ambiguous_order_absence_unproven:"
                f"{client_order_id}:gross={_text(gross_position)}"
            )
            continue
        with self._lock:
            pending_intents = self._state["risk_control"][
                "pending_order_intents"
            ]
            for resolution in resolutions:
                row = pending_intents.get(resolution["client_order_id"])
                if not isinstance(row, dict):
                    continue
                row.update(
                    {
                        **resolution,
                        "reconciled_at_utc": _iso(self._clock()),
                        "retry_without_query_allowed": False,
                    }
                )
            self._append_event(
                "ambiguous_order_intents_reconciled",
                {
                    "resolutions": resolutions,
                    "blockers": blockers,
                    "blind_retry_allowed": False,
                },
            )
            self._persist_state()
        return blockers

    def _read_only_client(self) -> OkxDemoClient:
        credentials = self._credential_loader(self.config.credential_service)
        config = OkxDemoClientConfig(
            credential_service=self.config.credential_service,
            allow_private_read=True,
            allow_demo_orders=False,
            allow_demo_cancels=False,
        )
        return self._client_factory(config, credentials)

    def _collect_exchange_snapshot(self, client: OkxDemoClient) -> dict[str, Any]:
        account = _first(client.private_get("/api/v5/account/config"), "account_config")
        captured_at_utc = _iso(self._clock())
        account_identity = authoritative_account_identity_snapshot(
            account,
            captured_at_utc=captured_at_utc,
        )
        balance = _first(client.private_get("/api/v5/account/balance", {"ccy": "USDT"}), "balance")
        positions = _require(client.private_get(
            "/api/v5/account/positions", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID}
        ), "positions", require_data=False)
        pending = _require(client.private_get(
            "/api/v5/trade/orders-pending", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID}
        ), "pending_orders", require_data=False)
        pending_algos = _require(
            client.private_get(
                "/api/v5/trade/orders-algo-pending",
                {"instId": OKX_DEMO_INSTRUMENT_ID, "ordType": "oco"},
            ),
            "pending_algo_orders",
            require_data=False,
        )
        history = _require(client.private_get(
            "/api/v5/trade/orders-history", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID, "limit": "100"}
        ), "order_history", require_data=False)
        fills = _require(client.private_get(
            "/api/v5/trade/fills", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID, "limit": "100"}
        ), "fills", require_data=False)
        bills = _require(client.private_get(
            "/api/v5/account/bills", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID, "limit": "100"}
        ), "bills", require_data=False)
        fee = _first(client.private_get(
            "/api/v5/account/trade-fee", {"instType": "SWAP", "instFamily": OKX_DEMO_INSTRUMENT_FAMILY}
        ), "trade_fee")
        leverage = _require(client.private_get(
            "/api/v5/account/leverage-info", {"instId": OKX_DEMO_INSTRUMENT_ID, "mgnMode": "isolated"}
        ), "leverage", require_data=False)
        instrument = _first(client.public_get(
            "/api/v5/public/instruments", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID}
        ), "instrument")
        ticker = _first(client.public_get("/api/v5/market/ticker", {"instId": OKX_DEMO_INSTRUMENT_ID}), "ticker")
        mark = _first(client.public_get(
            "/api/v5/public/mark-price", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID}
        ), "mark")
        index = _first(client.public_get(
            "/api/v5/market/index-tickers", {"instId": "BTC-USDT"}
        ), "index")
        price_limit = _first(client.public_get(
            "/api/v5/public/price-limit", {"instId": OKX_DEMO_INSTRUMENT_ID}
        ), "price_limit")
        book = _first(client.public_get(
            "/api/v5/market/books", {"instId": OKX_DEMO_INSTRUMENT_ID, "sz": "20"}
        ), "book")
        server_time_request_started_at = self._clock().astimezone(timezone.utc)
        server_time = _first(client.public_get("/api/v5/public/time"), "server_time")
        server_time_response_received_at = self._clock().astimezone(timezone.utc)
        server_time_request_started_ms = int(
            server_time_request_started_at.timestamp() * 1000
        )
        server_time_response_received_ms = int(
            server_time_response_received_at.timestamp() * 1000
        )
        server_time_local_midpoint_ms = (
            server_time_request_started_ms + server_time_response_received_ms
        ) // 2
        server_time_round_trip_ms = (
            server_time_response_received_ms - server_time_request_started_ms
        )
        funding = _first(client.public_get(
            "/api/v5/public/funding-rate", {"instId": OKX_DEMO_INSTRUMENT_ID}
        ), "funding_rate", allow_empty=True)
        snapshot = {
            "captured_at_utc": captured_at_utc,
            "account": _sanitize_account(account, identity=account_identity),
            "balance": _sanitize_balance(balance),
            "positions": [_sanitize_position(row) for row in positions.data],
            "pending_orders": [_sanitize_order(row) for row in pending.data],
            "pending_algo_orders": [
                _sanitize_algo_order(row) for row in pending_algos.data
            ],
            "orders": [_sanitize_order(row) for row in history.data],
            "fills": [_sanitize_fill(row) for row in fills.data],
            "bills": [_sanitize_bill(row) for row in bills.data],
            "fee_schedule": _sanitize_fee(fee),
            "leverage": [_sanitize_leverage(row) for row in leverage.data],
            "instrument": _sanitize_instrument(instrument),
            "ticker": _sanitize_ticker(ticker),
            "mark": {"mark_price": str(mark.get("markPx") or ""), "timestamp_ms": str(mark.get("ts") or "")},
            "index": {"index_price": str(index.get("idxPx") or ""), "timestamp_ms": str(index.get("ts") or "")},
            "price_limit": {"buy": str(price_limit.get("buyLmt") or ""), "sell": str(price_limit.get("sellLmt") or "")},
            "book": _sanitize_book(book),
            "funding": _sanitize_funding(funding),
            "server_time_ms": str(server_time.get("ts") or ""),
            "server_time_request_started_at_utc": _iso(
                server_time_request_started_at
            ),
            "server_time_response_received_at_utc": _iso(
                server_time_response_received_at
            ),
            "server_time_local_midpoint_ms": str(server_time_local_midpoint_ms),
            "server_time_round_trip_ms": str(server_time_round_trip_ms),
        }
        previous_fact = _mapping(
            self._state.get("account_risk_facts")
            if _mapping(self._state.get("account_risk_facts")).get(
                "risk_eligible"
            )
            is True
            else self._state.get("account_risk_last_valid_fact")
        )
        provider = self.config.account_cashflow_evidence_provider
        snapshot_hash = canonical_ledger_snapshot_sha256(snapshot)
        cashflow_evidence: dict[str, Any]
        if provider is None or previous_fact.get("risk_eligible") is not True:
            cashflow_evidence = {
                "schema_version": "btc_account_cashflow_evidence_v1",
                "status": "unknown",
                "complete": False,
                "account_identity_hash": account_identity.get("hash", ""),
                "account_scope": ACCOUNT_DRAWDOWN_SCOPE,
                "currency": "USDT",
                "snapshot_sha256": snapshot_hash,
                "coverage_start_utc": str(
                    previous_fact.get("observed_at_utc") or ""
                ),
                "coverage_end_utc": captured_at_utc,
                "amount_usdt": None,
                "blockers": [
                    (
                        "account_cashflow_provider_missing"
                        if provider is None
                        else "explicit_baseline_required"
                    )
                ],
            }
        else:
            try:
                supplied = provider(
                    client=client,
                    account_identity_hash=str(account_identity.get("hash") or ""),
                    snapshot_sha256=snapshot_hash,
                    coverage_start_utc=previous_fact.get("observed_at_utc"),
                    coverage_end_utc=captured_at_utc,
                    reference_time_utc=self._clock(),
                )
                cashflow_evidence = validate_account_cashflow_evidence(
                    supplied,
                    expected_account_identity_hash=str(
                        account_identity.get("hash") or ""
                    ),
                    expected_snapshot_sha256=snapshot_hash,
                    expected_coverage_start_utc=previous_fact.get(
                        "observed_at_utc"
                    ),
                    expected_coverage_end_utc=captured_at_utc,
                )
            except Exception as exc:
                cashflow_evidence = {
                    "schema_version": "btc_account_cashflow_evidence_v1",
                    "status": "unknown",
                    "complete": False,
                    "account_identity_hash": str(
                        account_identity.get("hash") or ""
                    ),
                    "account_scope": ACCOUNT_DRAWDOWN_SCOPE,
                    "currency": "USDT",
                    "snapshot_sha256": snapshot_hash,
                    "coverage_start_utc": str(
                        previous_fact.get("observed_at_utc") or ""
                    ),
                    "coverage_end_utc": captured_at_utc,
                    "amount_usdt": None,
                    "blockers": [
                        "account_cashflow_evidence_unavailable:" + _safe_error(exc)
                    ],
                }
        snapshot["account_cashflow_evidence"] = cashflow_evidence
        return snapshot

    def _configured_limits(self) -> tuple[Decimal, Decimal, Decimal]:
        limits = _mapping(self._state.get("limits"))
        order_contracts = _decimal(limits.get("order_contracts"))
        max_net_contracts = _decimal(limits.get("max_net_contracts"))
        max_notional_usdt = _decimal(limits.get("max_notional_usdt"))
        if not order_contracts.is_finite() or order_contracts <= 0:
            order_contracts = OKX_DEMO_PAPER_CONTRACTS
        if not max_net_contracts.is_finite() or max_net_contracts <= 0:
            max_net_contracts = OKX_DEMO_PAPER_MAX_NET_CONTRACTS
        if not max_notional_usdt.is_finite() or max_notional_usdt <= 0:
            max_notional_usdt = OKX_DEMO_PAPER_MAX_NOTIONAL_USDT
        return order_contracts, max_net_contracts, max_notional_usdt

    def _preflight_blockers(self, snapshot: Mapping[str, Any], *, require_flat: bool) -> list[str]:
        blockers: list[str] = []
        _, max_net_contracts, max_notional_usdt = self._configured_limits()
        account = snapshot.get("account", {})
        permissions = set(account.get("permissions", []))
        # Only snapshots produced by _collect_exchange_snapshot carry the
        # redacted identity projection.  Synthetic unit snapshots without it
        # retain their historical structural checks; a real account-config
        # snapshot with a missing UID is explicitly blocked.
        if "identity" in account:
            identity = _mapping(account.get("identity"))
            if not (
                is_authoritative_account_identity_hash(identity.get("hash"))
                and identity.get("source") == ACCOUNT_IDENTITY_HASH_SOURCE
            ):
                blockers.append(
                    "btc_demo_authoritative_account_identity_hash_missing"
                )
        if account.get("account_level") != "2":
            blockers.append("okx_demo_paper_account_not_contract_mode")
        if account.get("position_mode") != "long_short_mode":
            blockers.append("okx_demo_paper_requires_long_short_mode")
        if "trade" not in permissions:
            blockers.append("okx_demo_paper_trade_permission_missing")
        if "withdraw" in permissions:
            blockers.append("okx_demo_paper_withdraw_permission_present")
        instrument = snapshot.get("instrument", {})
        if instrument.get("instrument_id") != OKX_DEMO_INSTRUMENT_ID or instrument.get("state") != "live":
            blockers.append("okx_demo_paper_instrument_unavailable")
        if _decimal(instrument.get("contract_value_btc")) != OKX_DEMO_PAPER_CONTRACT_VALUE_BTC:
            blockers.append("okx_demo_paper_contract_value_changed")
        if _decimal(instrument.get("lot_size")) != OKX_DEMO_PAPER_CONTRACTS or _decimal(instrument.get("minimum_size")) != OKX_DEMO_PAPER_CONTRACTS:
            blockers.append("okx_demo_paper_minimum_size_changed")
        positions = snapshot.get("positions", [])
        try:
            signed = _signed_position(positions)
            gross = _gross_position_contracts(positions)
        except OkxDemoPaperRuntimeError:
            signed = Decimal("0")
            gross = Decimal("0")
            blockers.append("okx_demo_paper_position_evidence_invalid")
        else:
            if abs(signed) > max_net_contracts:
                blockers.append("okx_demo_paper_position_exceeds_cap")
            if gross > max_net_contracts:
                blockers.append("okx_demo_paper_gross_position_exceeds_cap")
            if gross > abs(signed):
                blockers.append(
                    "okx_demo_paper_hedged_position_shape_unsupported"
                )
            if require_flat and gross != 0:
                blockers.append("okx_demo_paper_start_requires_flat_account")
        pending = list(snapshot.get("pending_orders", []))
        unknown_pending = [row for row in pending if str(row.get("client_order_id") or "") not in self._owned_client_order_ids]
        if unknown_pending:
            blockers.append("okx_demo_paper_unknown_pending_order_present")
        if require_flat and pending:
            blockers.append("okx_demo_paper_start_requires_no_pending_orders")
        if require_flat and snapshot.get("pending_algo_orders"):
            blockers.append("okx_demo_paper_start_requires_no_pending_algo_orders")
        bid = _decimal(snapshot.get("ticker", {}).get("bid"))
        ask = _decimal(snapshot.get("ticker", {}).get("ask"))
        if bid <= 0 or ask <= bid:
            blockers.append("okx_demo_paper_ticker_invalid")
        spread_bps = _ratio_bps(ask - bid, (ask + bid) / Decimal("2")) if ask > bid > 0 else Decimal("999999")
        if spread_bps > self.config.max_spread_bps:
            blockers.append("okx_demo_paper_spread_cap_breached")
        order_contracts, _, _ = self._configured_limits()
        notional = ask * OKX_DEMO_PAPER_CONTRACT_VALUE_BTC * order_contracts
        if notional > max_notional_usdt:
            blockers.append(
                "okx_demo_partial_fill_order_exceeds_25_usdt"
                if order_contracts == OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS
                else "okx_demo_paper_minimum_order_exceeds_10_usdt"
            )
        if _decimal(snapshot.get("balance", {}).get("equity_usdt")) < notional:
            blockers.append("okx_demo_paper_insufficient_usdt_equity")
        if not _book_two_sided(snapshot.get("book", {})):
            blockers.append("okx_demo_paper_order_book_not_two_sided")
        funding_bps = abs(_decimal(snapshot.get("funding", {}).get("funding_rate"))) * Decimal("10000")
        if funding_bps > self.config.max_funding_abs_bps:
            blockers.append("okx_demo_paper_funding_cap_breached")
        server_ms = _decimal(snapshot.get("server_time_ms"))
        midpoint_text = str(
            snapshot.get("server_time_local_midpoint_ms") or ""
        ).strip()
        round_trip_text = str(
            snapshot.get("server_time_round_trip_ms") or ""
        ).strip()
        clock_sample_valid = True
        clock_uncertainty_ms = Decimal("0")
        if midpoint_text:
            local_ms = _decimal(midpoint_text)
            round_trip_ms = _decimal(round_trip_text)
            clock_sample_valid = (
                bool(round_trip_text)
                and local_ms.is_finite()
                and local_ms > 0
                and round_trip_ms.is_finite()
                and round_trip_ms >= 0
            )
            if clock_sample_valid:
                clock_uncertainty_ms = round_trip_ms / Decimal("2")
        else:
            # Legacy snapshots do not carry an adjacent /public/time sample.
            # Preserve their conservative collection-start anchor instead of
            # comparing with a later worker-cycle clock.
            captured_at = _parse_utc(snapshot.get("captured_at_utc"))
            local_ms = Decimal(
                int((captured_at or self._clock()).timestamp() * 1000)
            )
        if (
            not server_ms.is_finite()
            or server_ms <= 0
            or not clock_sample_valid
            or abs(server_ms - local_ms) + clock_uncertainty_ms
            > Decimal(self.config.max_clock_offset_ms)
        ):
            blockers.append("okx_demo_paper_clock_offset_breached")
        leverage_rows = list(snapshot.get("leverage", []))
        if not leverage_rows:
            blockers.append("okx_demo_paper_leverage_evidence_missing")
        leverage_blockers = validate_isolated_leverage(
            leverage_rows,
            self.config.max_configured_leverage,
        )
        if leverage_blockers:
            blockers.append(
                leverage_blocker_code(
                    self.config.max_configured_leverage,
                    prefix="okx_demo_paper",
                )
            )
        blockers.extend(self._exchange_hosted_protection_blockers(snapshot))
        return _dedupe(blockers)

    def _stop_and_flatten_snapshot_blockers(
        self,
        snapshot: Mapping[str, Any],
    ) -> list[str]:
        """Require one fresh, owned protection projection before a close POST."""

        blockers = self._preflight_blockers(snapshot, require_flat=False)
        if snapshot.get("pending_orders"):
            blockers.append("okx_demo_stop_and_flatten_pending_order_present")

        pending_algos = snapshot.get("pending_algo_orders")
        if not isinstance(pending_algos, Sequence) or isinstance(
            pending_algos, (str, bytes)
        ):
            return _dedupe(
                [*blockers, "okx_demo_stop_and_flatten_pending_algos_invalid"]
            )

        risk = _mapping(self._state.get("risk_control"))
        owners = _mapping(risk.get("owned_attached_algos"))
        pending_intents = _mapping(risk.get("pending_order_intents"))
        seen: set[tuple[str, str]] = set()
        for raw_row in pending_algos:
            if not isinstance(raw_row, Mapping):
                blockers.append("okx_demo_stop_and_flatten_algo_row_invalid")
                continue
            row = dict(raw_row)
            pair = (
                str(row.get("algo_id") or ""),
                str(row.get("algo_client_order_id") or ""),
            )
            if not all(pair) or pair in seen:
                blockers.append("okx_demo_stop_and_flatten_foreign_algo_present")
                continue
            seen.add(pair)
            owner = _mapping(owners.get(pair[1]))
            parent = str(owner.get("parent_client_order_id") or "")
            if not owner:
                blockers.append("okx_demo_stop_and_flatten_algo_owner_missing")
                continue
            if (
                owner.get("opening_intent") is not True
                or str(owner.get("instrument_id") or "")
                != OKX_DEMO_INSTRUMENT_ID
                or not parent
                or parent not in pending_intents
                or str(owner.get("algo_client_order_id") or pair[1])
                != pair[1]
                or (
                    str(owner.get("algo_id") or "")
                    and str(owner.get("algo_id") or "") != pair[0]
                )
                or str(owner.get("status") or "")
                not in {"submit_pending", "active"}
            ):
                blockers.append("okx_demo_stop_and_flatten_algo_owner_mismatch")
            if (
                str(row.get("instrument_id") or "") != OKX_DEMO_INSTRUMENT_ID
                or str(row.get("order_type") or "") != "oco"
                or str(row.get("state") or "")
                not in {"live", "effective", "partially_effective"}
                or _decimal(row.get("size")) != OKX_DEMO_PAPER_CONTRACTS
                or str(row.get("position_side") or "") not in {"long", "short"}
            ):
                blockers.append("okx_demo_stop_and_flatten_algo_identity_mismatch")

        return _dedupe(blockers)

    def _exchange_hosted_protection_blockers(
        self,
        snapshot: Mapping[str, Any],
    ) -> list[str]:
        positions = snapshot.get("positions", [])
        try:
            signed = _signed_position(positions)
            gross = _gross_position_contracts(positions)
        except OkxDemoPaperRuntimeError:
            return ["okx_demo_paper_position_evidence_invalid"]
        if gross == 0:
            return []
        if gross > abs(signed):
            return ["okx_demo_paper_hedged_position_shape_unsupported"]
        expected_position_side = "long" if signed > 0 else "short"
        active = _mapping(
            self._state.get("risk_control", {}).get("active_protection")
        )
        if active.get("status") != "exchange_accepted":
            return ["okx_demo_nonflat_position_has_no_verified_protection"]
        if str(active.get("position_side") or "") != expected_position_side:
            return [
                "okx_demo_exchange_protection_position_side_mismatch"
            ]
        if (
            str(active.get("instrument_id") or "")
            != OKX_DEMO_INSTRUMENT_ID
            or _decimal(active.get("contracts")) != gross
        ):
            return ["okx_demo_exchange_protection_contract_mismatch"]
        if active.get("market_exit") is not True:
            return [
                "okx_demo_exchange_protection_market_exit_unconfirmed"
            ]
        algo_client_id = str(active.get("algo_client_order_id") or "")
        pending_algos = [
            row
            for row in snapshot.get("pending_algo_orders", [])
            if isinstance(row, Mapping)
        ]
        matching = next(
            (
                row
                for row in pending_algos
                if str(row.get("algo_client_order_id") or "")
                == algo_client_id
            ),
            None,
        )
        if matching is None:
            return ["okx_demo_verified_protection_missing_from_exchange_pending"]
        blockers: list[str] = []
        if (
            str(matching.get("position_side") or "")
            != expected_position_side
        ):
            blockers.append(
                "okx_demo_exchange_protection_position_side_mismatch"
            )
        if (
            str(matching.get("instrument_id") or "")
            != OKX_DEMO_INSTRUMENT_ID
            or _decimal(matching.get("size")) != gross
        ):
            blockers.append("okx_demo_exchange_protection_contract_mismatch")
        if (
            str(matching.get("take_profit_order_price") or "") != "-1"
            or str(matching.get("stop_loss_order_price") or "") != "-1"
        ):
            blockers.append(
                "okx_demo_exchange_protection_market_exit_unconfirmed"
            )
        if str(matching.get("state") or "") not in {
            "live",
            "effective",
            "partially_effective",
        }:
            blockers.append("okx_demo_exchange_protection_not_active")
        if (
            str(matching.get("take_profit_trigger") or "")
            != str(active.get("tp_trigger_px") or "")
            or str(matching.get("stop_loss_trigger") or "")
            != str(active.get("sl_trigger_px") or "")
            or str(matching.get("take_profit_trigger_type") or "") != "mark"
            or str(matching.get("stop_loss_trigger_type") or "") != "mark"
        ):
            blockers.append("okx_demo_exchange_protection_snapshot_mismatch")
        return blockers

    def _signal_decision(
        self,
        strategy: Mapping[str, Any],
        *,
        client: OkxDemoClient | None = None,
    ) -> dict[str, Any]:
        spec = btc_strategy_registry.get(str(strategy.get("strategy_id") or ""), str(strategy.get("candidate_id") or ""))
        tail_evidence: dict[str, Any] = {}
        offline_provider = self.config.offline_completed_frame_provider
        if offline_provider is not None:
            supplied = offline_provider()
            if not isinstance(supplied, pd.DataFrame):
                raise OkxDemoPaperRuntimeError("offline_completed_frame_invalid")
            frame = supplied.copy(deep=True)
            required_columns = {"open", "high", "low", "close", "volume"}
            if (
                frame.empty
                or not isinstance(frame.index, pd.DatetimeIndex)
                or frame.index.tz is None
                or not frame.index.is_monotonic_increasing
                or not frame.index.is_unique
                or not required_columns.issubset(frame.columns)
                or frame.index[-1] > pd.Timestamp(self._clock()).floor("h")
            ):
                raise OkxDemoPaperRuntimeError("offline_completed_frame_invalid")
            source = "injected_offline_completed_frame"
        elif spec.strategy_id == OKX_NATIVE_STRATEGY_LINE or (
            spec.strategy_id == STABLE_STRATEGY_LINE and client is not None
        ):
            frame = load_completed_okx_native_hourly_frame(
                self.config.repo_root,
                now=self._clock(),
                shared_manifest_git_spec=(
                    self.config.okx_native_shared_manifest_git_spec
                ),
                shared_data_root=self.config.okx_native_shared_data_root,
                expected_dataset_id=self.config.okx_native_expected_dataset_id,
                allow_stale_baseline=client is not None,
            )
            if client is not None:
                frame, tail_evidence = _merge_okx_native_public_candle_tail(
                    baseline=frame,
                    client=client,
                    now=self._clock(),
                )
                self._cache_runtime_completed_chart_frame(
                    frame,
                    evidence=tail_evidence,
                )
            source = "local_okx_native_completed_swap_1h_manifest_verified"
        else:
            frame = load_completed_btc_hourly_frame(self.config.data_db_path, now=self._clock())
            source = "local_sqlite_completed_1h_canonical_signal_callable"
        if spec.signal_callable is None:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_signal_callable_missing")
        series = spec.signal_callable(frame, "1h")
        if series.empty:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_signal_series_empty")
        signal_value = Decimal(str(float(series.iloc[-1]))).quantize(Decimal("0.000001"))
        normalized = Decimal("1") if signal_value > 0 else Decimal("-1") if signal_value < 0 else Decimal("0")
        decision_bar_close = pd.Timestamp(frame.index[-1]).to_pydatetime().astimezone(timezone.utc)
        target_contracts = normalized * OKX_DEMO_PAPER_CONTRACTS
        return {
            "strategy_id": spec.strategy_id,
            "candidate_id": spec.candidate_id,
            "strategy_version": spec.strategy_version,
            "params_hash": spec.params_hash,
            "source": source,
            "raw_signal": _text(signal_value),
            "direction": "long" if normalized > 0 else "short" if normalized < 0 else "flat",
            "target_contracts": _text(target_contracts),
            "decision_bar_close_utc": _iso(decision_bar_close),
            "effective_rule": "signal_from_latest_completed_bar_applies_after_bar_close",
            "no_future_function": True,
            "runtime_public_candle_tail": tail_evidence,
        }

    def _build_order_plan(
        self,
        snapshot: Mapping[str, Any],
        *,
        current_quantity: Decimal,
        target_quantity: Decimal,
    ) -> dict[str, Any] | None:
        configured_contracts, configured_max_net, configured_max_notional = (
            self._configured_limits()
        )
        if current_quantity == target_quantity:
            return None
        reversal = current_quantity != 0 and target_quantity != 0 and ((current_quantity > 0) != (target_quantity > 0))
        desired = Decimal("0") if reversal else target_quantity
        delta = desired - current_quantity
        lot_size = _decimal(snapshot.get("instrument", {}).get("lot_size"))
        if (
            not delta
            or abs(delta) > configured_contracts
            or (
                lot_size > 0
                and (abs(delta) % lot_size) != 0
            )
        ):
            raise OkxDemoPaperRuntimeError("okx_demo_paper_order_delta_not_exact_0p01")
        if current_quantity > 0:
            side, position_side, action = "sell", "long", "close_long"
        elif current_quantity < 0:
            side, position_side, action = "buy", "short", "close_short"
        elif target_quantity > 0:
            side, position_side, action = "buy", "long", "open_long"
        else:
            side, position_side, action = "sell", "short", "open_short"
        ticker = snapshot.get("ticker", {})
        instrument = snapshot.get("instrument", {})
        price_limits = snapshot.get("price_limit", {})
        tick = _decimal(instrument.get("tick_size"))
        if side == "buy":
            arrival = _decimal(ticker.get("ask"))
            raw = arrival * (Decimal("1") + self.config.aggressive_limit_bps / Decimal("10000"))
            buy_limit = _decimal(price_limits.get("buy"))
            if buy_limit > 0:
                raw = min(raw, buy_limit)
            price = _round_to_tick(raw, tick, ROUND_CEILING)
        else:
            arrival = _decimal(ticker.get("bid"))
            raw = arrival * (Decimal("1") - self.config.aggressive_limit_bps / Decimal("10000"))
            sell_limit = _decimal(price_limits.get("sell"))
            if sell_limit > 0:
                raw = max(raw, sell_limit)
            price = _round_to_tick(raw, tick, ROUND_FLOOR)
        contracts = abs(delta)
        notional = price * OKX_DEMO_PAPER_CONTRACT_VALUE_BTC * contracts
        if price <= 0 or notional > configured_max_notional:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_order_notional_cap_breached")
        spread_bps = _ratio_bps(
            _decimal(ticker.get("ask")) - _decimal(ticker.get("bid")),
            (_decimal(ticker.get("ask")) + _decimal(ticker.get("bid"))) / Decimal("2"),
        )
        depth = _depth_cost(snapshot.get("book", {}), side=side, contracts=contracts)
        if depth["fully_mapped"] is not True:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_depth_mapping_incomplete")
        self._sequence += 1
        self._state["runtime"]["order_sequence"] = self._sequence
        run_id = str(self._state["runtime"].get("run_id") or "")
        client_order_id = f"btcDP{run_id[:8]}{self._sequence:04d}"
        fee_rate = abs(_decimal(snapshot.get("fee_schedule", {}).get("taker_rate")))
        funding_rate = abs(_decimal(snapshot.get("funding", {}).get("funding_rate")))
        is_opening = action.startswith("open_")
        protection = (
            self._build_attached_protection(
                entry_price=price,
                tick_size=tick,
                position_side=position_side,
                client_order_id=client_order_id,
                contracts=contracts,
            )
            if is_opening
            else None
        )
        return {
            "action": action,
            "side": side,
            "position_side": position_side,
            "contracts": _text(contracts),
            "arrival_price": _text(arrival),
            "limit_price": _text(price),
            "estimated_notional_usdt": _text(notional),
            "client_order_id": client_order_id,
            "reversal_close_only": reversal,
            # Explicit position binding consumed by the pure T5 delegate.
            # ``desired`` is zero for a reversal close and therefore reflects
            # the actual order effect rather than the next signal target.
            "position_before_contracts": _text(current_quantity),
            "position_after_contracts": _text(desired),
            "risk_reducing_only": not is_opening,
            "entry_order_type": (
                "ioc"
                if is_opening and configured_contracts == OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS
                else "fok"
            ),
            "partial_fill_recovery": (
                is_opening
                and configured_contracts == OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS
            ),
            "attached_protection": protection,
            "risk": {
                "order_contracts": _text(contracts),
                "max_net_contracts": _text(configured_max_net),
                "max_notional_usdt": _text(configured_max_notional),
                "spread_bps": _text(spread_bps),
                "fee_bps": _text(fee_rate * Decimal("10000")),
                "funding_bps": _text(funding_rate * Decimal("10000")),
                "slippage_budget_bps": _text(self.config.aggressive_limit_bps),
                "impact_bps": depth["impact_bps"],
                "depth_mapping": depth,
                "cost_model_complete": True,
            },
        }

    def _build_attached_protection(
        self,
        *,
        entry_price: Decimal,
        tick_size: Decimal,
        position_side: str,
        client_order_id: str,
        contracts: Decimal | None = None,
    ) -> dict[str, Any]:
        policy = self._protection_policy
        if policy is None or policy.validate():
            raise OkxDemoPaperRuntimeError(
                "okx_demo_server_side_protection_policy_unavailable"
            )
        try:
            protection = self._shared_platform_v3_oms.build_attached_protection(
                policy=policy.to_dict(),
                entry_price=entry_price,
                tick_size=tick_size,
                position_side=position_side,
                client_order_id=client_order_id,
                contracts=(
                    OKX_DEMO_PAPER_CONTRACTS
                    if contracts is None
                    else contracts
                ),
            )
        except OMSContractError as exc:
            blocker = str(exc)
            if "position_side" in blocker:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_server_side_protection_position_side_invalid"
                ) from exc
            if "trigger" in blocker or "price" in blocker:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_server_side_protection_price_invalid"
                ) from exc
            raise OkxDemoPaperRuntimeError(
                "okx_demo_server_side_protection_policy_unavailable"
            ) from exc
        # Keep the legacy exchange payload shape byte-for-byte compatible;
        # the immutable T5 record retains size/parent/policy identity beside
        # this projection for the pure contract and audit path.
        return protection.to_exchange_payload()

    def _dispatch_execution_action(
        self,
        *,
        action: RuntimeAction,
        client: OkxDemoClient,
        intent: OrderIntent,
        risk: RiskDecision,
        snapshot: Mapping[str, Any],
        attached_protection: Mapping[str, Any] | None = None,
        callback: Callable[[OrderIntent], object],
    ) -> object:
        """Use the backend-composed boundary when this is a production run.

        Direct controller construction remains an offline contract-test seam.
        Backend composition always injects the dispatcher; this method never
        manufactures authority, capabilities, or a runtime projection.
        """

        dispatcher = self.config.execution_dispatcher
        if dispatcher is None:
            # `OkxDemoClient` is the real transport.  A controller created
            # outside the backend/fault-drill composition root has no permit
            # issuer and must never acquire a direct transport side path.
            # Narrow test doubles remain usable for offline OMS contracts.
            if isinstance(client, OkxDemoClient):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_execution_boundary_dispatcher_required"
                )
            return callback(intent)
        runtime = _mapping(self._state.get("runtime"))
        try:
            facts = BTCExecutionDispatchFacts(
                exchange_snapshot=dict(snapshot),
                private_ws=dict(_mapping(self._state.get("private_ws"))),
                ledger_reconciliation=dict(
                    _mapping(self._state.get("ledger_reconciliation"))
                ),
                credential_service=self.config.credential_service,
                runtime_run_id=str(runtime.get("run_id") or ""),
                source_head=_repo_head(self.config.repo_root),
                epoch=int(runtime.get("authoritative_liveness_epoch") or 0),
                runtime_active=runtime.get("active") is True,
                opening_allowed=runtime.get("opening_allowed") is True,
                cancel_only=runtime.get("cancel_only") is True,
                risk_mode=str(
                    _mapping(self._state.get("risk_control")).get("mode")
                    or ""
                ),
                attached_protection=dict(attached_protection or {}),
            )
            result = dispatcher.dispatch(
                action=action,
                order_intent=intent,
                risk_decision=risk,
                facts=facts,
                transport_context=client,
                callback=callback,
            )
        except Exception as exc:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_execution_boundary_dispatch_failed:"
                + _safe_error(exc)
            ) from exc
        if not isinstance(result, BTCExecutionResult):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_execution_boundary_dispatch_result_invalid"
            )
        if not result.decision.allowed or not result.transport_called:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_execution_boundary_dispatch_denied:"
                + ",".join(result.blockers or result.decision.reasons)
            )
        return result.receipt

    def _dispatch_control_action(
        self,
        *,
        action: RuntimeAction,
        client: OkxDemoClient,
        snapshot: Mapping[str, Any],
        control_key: str,
        callback: Callable[[OrderIntent], object],
    ) -> object:
        """Route cancellation/dead-man writes through the same boundary.

        The generated client id is a local lifecycle handle only: callbacks
        ignore it and receive the exact persisted cancellation/dead-man target
        from their closure. It cannot become a broker opening id.
        """

        runtime = _mapping(self._state.get("runtime"))
        run_id = str(runtime.get("run_id") or "")
        if self.config.execution_dispatcher is not None and len(run_id) < 8:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_execution_boundary_control_run_id_missing"
            )
        ticker = _mapping(snapshot.get("ticker"))
        limit_price = _decimal(ticker.get("bid"))
        if (
            self.config.execution_dispatcher is not None
            and (not limit_price.is_finite() or limit_price <= 0)
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_execution_boundary_control_price_missing"
            )
        if not limit_price.is_finite() or limit_price <= 0:
            # Explicit offline fake-client seam. The callback ignores this
            # lifecycle-only value; a real Demo client cannot take this path
            # because _dispatch_execution_action requires a dispatcher.
            limit_price = Decimal("1")
        intent = OrderIntent(
            timestamp_utc=self._clock(),
            strategy_id="btc_okx_demo_runtime_control",
            symbol=OKX_DEMO_INSTRUMENT_ID,
            side=OrderSide.SELL,
            quantity=float(OKX_DEMO_PAPER_CONTRACTS),
            order_type=OrderType.LIMIT,
            limit_price=float(limit_price),
            time_in_force=TimeInForce.IOC,
            run_id=run_id,
            client_order_id=f"btcDP{run_id[:8]}{uuid.uuid4().hex[:12]}",
            metadata={
                "demo_only": True,
                "boundary_control_action": action.value,
                "control_key_sha256": hashlib.sha256(
                    control_key.encode("utf-8")
                ).hexdigest(),
            },
        )
        _, _, max_notional = self._configured_limits()
        # Compatibility lifecycle handle only: this control action is not an
        # order-construction path.  It still must cross the existing
        # dispatcher and never grants a broker capability on its own.
        risk = RiskDecision(
            approved=True,
            reason="okx_demo_boundary_control_action",
            order_intent_id=intent.order_intent_id,
            risk_version="btc_okx_demo_paper_risk_v1",
            rule_name="BTC-OKX-DEMO-PAPER-01",
            threshold=float(max_notional),
            metadata={"demo_only": True, "action": action.value},
        )
        return self._dispatch_execution_action(
            action=action,
            client=client,
            intent=intent,
            risk=risk,
            snapshot=snapshot,
            callback=callback,
        )

    def _hosted_protection_fact_binding(
        self, snapshot: Mapping[str, Any]
    ) -> dict[str, Any]:
        runtime = _mapping(self._state.get("runtime"))
        strategy = _mapping(self._state.get("strategy"))
        account_identity = _mapping(_mapping(snapshot.get("account")).get("identity"))
        return {
            "runtime_identity": self._runtime_identity,
            "run_id": str(runtime.get("run_id") or ""),
            "source_head": str(runtime.get("source_head") or "").lower(),
            "account_identity_hash": str(account_identity.get("hash") or "").lower(),
            "liveness_epoch": runtime.get("authoritative_liveness_epoch"),
            "strategy_id": str(strategy.get("strategy_id") or ""),
            "strategy_version": str(strategy.get("strategy_version") or ""),
        }

    def _hosted_protection_fact_projection(
        self, snapshot: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return a redacted copy of current local protection ownership."""

        risk = _mapping(self._state.get("risk_control"))
        owners = _mapping(risk.get("owned_attached_algos"))
        active = _mapping(risk.get("active_protection"))
        intents = _mapping(risk.get("pending_order_intents"))
        parent_ids = {
            str(_mapping(row).get("parent_client_order_id") or "")
            for row in owners.values()
            if isinstance(row, Mapping)
        }
        active_parent = str(active.get("parent_client_order_id") or "")
        if active_parent:
            parent_ids.add(active_parent)
        owner_fields = {
            "algo_id",
            "algo_client_order_id",
            "parent_client_order_id",
            "instrument_id",
            "opening_intent",
            "status",
            "fact_binding",
        }
        receipt_fields = {
            "status",
            "parent_client_order_id",
            "algo_id",
            "algo_client_order_id",
            "instrument_id",
            "position_side",
            "contracts",
            "fact_binding",
        }
        intent_fields = {
            "status",
            "client_order_id",
            "risk_reducing_only",
            "order",
            "fact_binding",
        }
        return {
            "schema_version": "btc_hosted_protection_facts_v1",
            "snapshot_sha256": canonical_ledger_snapshot_sha256(snapshot),
            "fact_binding": self._hosted_protection_fact_binding(snapshot),
            "owned_attached_algos": {
                str(key): {
                    field: json.loads(json.dumps(value, default=str))
                    for field, value in _mapping(row).items()
                    if field in owner_fields
                }
                for key, row in owners.items()
                if isinstance(row, Mapping)
            },
            "active_protection": {
                field: json.loads(json.dumps(value, default=str))
                for field, value in active.items()
                if field in receipt_fields
            },
            "parent_order_intents": {
                parent_id: {
                    field: json.loads(json.dumps(value, default=str))
                    for field, value in _mapping(intents.get(parent_id)).items()
                    if field in intent_fields
                }
                for parent_id in sorted(parent_ids)
                if parent_id and isinstance(intents.get(parent_id), Mapping)
            },
        }

    def _submit_order_plan(
        self,
        client: OkxDemoClient,
        *,
        snapshot: Mapping[str, Any],
        decision: Mapping[str, Any],
        order_plan: Mapping[str, Any],
        incident_recovery_receipt_sha256: str = "",
        emergency_exit: bool = False,
        sealed_strategy_objects: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = self._clock()
        is_opening = order_plan.get("risk_reducing_only") is not True
        partial_fill_recovery = order_plan.get("partial_fill_recovery") is True
        _, configured_max_net, configured_max_notional = self._configured_limits()
        if validate_isolated_leverage(
            snapshot.get("leverage", []),
            self.config.max_configured_leverage,
        ):
            raise OkxDemoPaperRuntimeError(
                leverage_blocker_code(
                    self.config.max_configured_leverage,
                    prefix="okx_demo_paper",
                )
            )
        self._assert_order_submit_path(
            is_opening=is_opening,
            exclude_client_order_id=str(order_plan.get("client_order_id") or ""),
            incident_recovery_receipt_sha256=(
                incident_recovery_receipt_sha256
            ),
            emergency_exit=emergency_exit,
        )
        position_before_contracts = order_plan.get("position_before_contracts")
        position_after_contracts = order_plan.get("position_after_contracts")
        if position_before_contracts is None or position_after_contracts is None:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_t5_authoritative_position_binding_required"
            )
        sealed_forecast: BTCForecast | None = None
        sealed_candidate_target: TargetPosition | None = None
        sealed_binding: Mapping[str, Any] = {}
        if sealed_strategy_objects is None:
            direction = SignalDirection.LONG if decision["direction"] == "long" else SignalDirection.SHORT if decision["direction"] == "short" else SignalDirection.FLAT
            signal = Signal(
                timestamp_utc=timestamp,
                strategy_id=str(decision["strategy_id"]),
                symbol=OKX_DEMO_INSTRUMENT_ID,
                direction=direction,
                strength=abs(float(decision["raw_signal"])),
                horizon="completed_1h_to_4h",
                reason="frozen_long_short_donchian_top5_completed_bar",
                metadata=dict(decision),
            )
            target = TargetPosition(
                timestamp_utc=timestamp,
                strategy_id=signal.strategy_id,
                symbol=OKX_DEMO_INSTRUMENT_ID,
                target_weight=float(Decimal(str(position_after_contracts)) / configured_max_net),
                target_quantity=float(Decimal(str(position_after_contracts))),
                signal_id=signal.signal_id,
                metadata={
                    "risk": dict(order_plan["risk"]),
                    "demo_only": True,
                    "order_generation_allowed": is_opening,
                    "source_kind": "signal",
                    "source_signal_id": signal.signal_id,
                },
            )
            intent = OrderIntent(
                timestamp_utc=timestamp,
                strategy_id=signal.strategy_id,
                symbol=OKX_DEMO_INSTRUMENT_ID,
                side=OrderSide.BUY if order_plan["side"] == "buy" else OrderSide.SELL,
                quantity=float(Decimal(str(order_plan["contracts"]))),
                order_type=OrderType.LIMIT,
                limit_price=float(Decimal(str(order_plan["limit_price"]))),
                time_in_force=(TimeInForce.IOC if order_plan.get("risk_reducing_only") is True or order_plan.get("entry_order_type") == "ioc" else TimeInForce.FOK),
                run_id=str(self._state["runtime"].get("run_id") or ""),
                signal_id=signal.signal_id,
                target_position_id=target.target_position_id,
                client_order_id=str(order_plan["client_order_id"]),
                metadata={"position_side": order_plan["position_side"], "action": order_plan["action"], "demo_only": True},
            )
        else:
            if (
                self.config.offline_completed_frame_provider is None
                or self.config.credential_service != "quant-system.okx-demo.offline"
                or isinstance(client, OkxDemoClient)
            ):
                raise OkxDemoPaperRuntimeError("okx_demo_sealed_strategy_objects_offline_only")
            signal = sealed_strategy_objects.get("signal")
            sealed_forecast = sealed_strategy_objects.get("forecast")
            sealed_candidate_target = sealed_strategy_objects.get("candidate_target")
            target = sealed_strategy_objects.get("execution_target")
            intent = sealed_strategy_objects.get("intent")
            sealed_binding = _mapping(sealed_strategy_objects.get("binding"))
            if not (
                isinstance(signal, Signal)
                and isinstance(sealed_forecast, BTCForecast)
                and isinstance(sealed_candidate_target, TargetPosition)
                and isinstance(target, TargetPosition)
                and isinstance(intent, OrderIntent)
            ):
                raise OkxDemoPaperRuntimeError("okx_demo_sealed_strategy_objects_invalid")
            instrument = _mapping(snapshot.get("instrument"))
            conversion = _mapping(sealed_binding.get("conversion"))
            contract_value = _decimal(instrument.get("contract_value_btc"))
            lot_size = _decimal(instrument.get("lot_size"))
            minimum_size = _decimal(instrument.get("minimum_size"))
            candidate_btc = _decimal(sealed_candidate_target.target_quantity or 0)
            if contract_value <= 0 or lot_size <= 0 or minimum_size <= 0:
                raise OkxDemoPaperRuntimeError("okx_demo_sealed_strategy_venue_filter_invalid")
            expected_contracts = candidate_btc / contract_value
            if (
                (expected_contracts != 0 and abs(expected_contracts) < minimum_size)
                or expected_contracts % lot_size != 0
                or abs(expected_contracts) > configured_max_net
                or expected_contracts != _decimal(position_after_contracts)
                or str(conversion.get("btc_quantity_text") or "") != _text(candidate_btc)
                or str(conversion.get("contract_value_btc_text") or "") != _text(contract_value)
                or str(conversion.get("contracts_text") or "") != _text(expected_contracts)
                or str(conversion.get("lot_size_contracts_text") or "") != _text(lot_size)
                or str(conversion.get("minimum_size_contracts_text") or "") != _text(minimum_size)
                or str(conversion.get("maximum_absolute_contracts_text") or "") != _text(configured_max_net)
            ):
                raise OkxDemoPaperRuntimeError("okx_demo_sealed_strategy_conversion_mismatch")
            runtime_run_id = str(self._state["runtime"].get("run_id") or "")
            expected_side = OrderSide.BUY if order_plan["side"] == "buy" else OrderSide.SELL
            expected_tif = TimeInForce.IOC if order_plan.get("risk_reducing_only") is True or order_plan.get("entry_order_type") == "ioc" else TimeInForce.FOK
            if not (
                signal.signal_id == sealed_forecast.source_signal_id
                == sealed_candidate_target.signal_id == target.signal_id == intent.signal_id
                and signal.strategy_id == sealed_forecast.strategy_id
                == sealed_candidate_target.strategy_id == target.strategy_id == intent.strategy_id
                and signal.symbol == sealed_forecast.symbol
                == sealed_candidate_target.symbol == target.symbol == intent.symbol
                == OKX_DEMO_INSTRUMENT_ID
                and target.metadata.get("source_forecast_id") == sealed_forecast.forecast_id
                and sealed_candidate_target.metadata.get("source_forecast_id") == sealed_forecast.forecast_id
                and target.metadata.get("candidate_target_position_id") == sealed_candidate_target.target_position_id
                and intent.target_position_id == target.target_position_id
                and intent.run_id == runtime_run_id
                and intent.client_order_id == str(order_plan["client_order_id"])
                and intent.side == expected_side
                and intent.order_type == OrderType.LIMIT
                and intent.time_in_force == expected_tif
                and Decimal(str(intent.quantity)) == Decimal(str(order_plan["contracts"]))
                and Decimal(str(intent.limit_price)) == Decimal(str(order_plan["limit_price"]))
                and Decimal(str(target.target_quantity)) == Decimal(str(position_after_contracts))
                and sealed_forecast.timestamp_utc <= timestamp < sealed_forecast.expiry_utc
                and sealed_binding.get("run_id") == runtime_run_id
                and sealed_binding.get("signal_sha256") == _canonical_sha256({
                    **signal.__dict__,
                    "timestamp_utc": _iso(signal.timestamp_utc),
                })
                and sealed_binding.get("candidate_target_sha256") == _canonical_sha256({
                    **sealed_candidate_target.__dict__,
                    "timestamp_utc": _iso(sealed_candidate_target.timestamp_utc),
                })
                and sealed_binding.get("execution_target_sha256") == _canonical_sha256({
                    **target.__dict__, "timestamp_utc": _iso(target.timestamp_utc)
                })
                and sealed_binding.get("forecast_sha256") == _canonical_sha256({
                    **sealed_forecast.__dict__,
                    "timestamp_utc": _iso(sealed_forecast.timestamp_utc),
                    "expiry_utc": _iso(sealed_forecast.expiry_utc),
                })
                and sealed_binding.get("intent_sha256") == _canonical_sha256({
                    **intent.__dict__, "timestamp_utc": _iso(intent.timestamp_utc)
                })
            ):
                raise OkxDemoPaperRuntimeError("okx_demo_sealed_strategy_binding_mismatch")
        venue_facts = {
            "venue": "okx_demo",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "margin_mode": "isolated",
            "position_side": order_plan["position_side"],
            "leverage": snapshot.get("leverage", []),
            "tick_size": _mapping(snapshot.get("instrument")).get("tick_size"),
            "max_abs_position": str(configured_max_net),
            "max_quantity": str(configured_max_net),
            "max_notional": str(configured_max_notional),
        }
        cost_facts = dict(order_plan["risk"])
        bundle_provider = self.config.authoritative_oms_bundle_provider
        if not callable(bundle_provider):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_t5_authoritative_oms_bundle_required"
            )
        strategy_facts = _mapping(self._state.get("strategy"))
        runtime_facts = {
            **dict(_mapping(self._state.get("runtime"))),
            "strategy_id": str(strategy_facts.get("strategy_id") or ""),
            "strategy_version": str(strategy_facts.get("strategy_version") or ""),
        }
        try:
            bundle = bundle_provider(
                signal=signal,
                target_position=target,
                intent=intent,
                position_before=float(position_before_contracts),
                position_after=float(position_after_contracts),
                action=(
                    RuntimeAction.SUBMIT_NEW_ORDER
                    if is_opening
                    else RuntimeAction.REDUCE_ONLY
                ),
                price=order_plan["limit_price"],
                quantity=order_plan["contracts"],
                venue_facts=venue_facts,
                cost_facts=cost_facts,
                # These legacy keyword names remain an empty compatibility
                # seam for older test providers.  Production composition must
                # ignore them and derive T4 solely from explicit facts below.
                guardian_health={},
                guardian_latch={},
                exchange_snapshot=dict(snapshot),
                private_ws=dict(self._state.get("private_ws") or {}),
                ledger_reconciliation=dict(
                    self._state.get("ledger_reconciliation") or {}
                ),
                runtime_facts=runtime_facts,
                hosted_protection_facts=self._hosted_protection_fact_projection(
                    snapshot
                ),
                source_head=str(self._state.get("runtime", {}).get("source_head") or ""),
                reference_time_utc=timestamp,
                protection_policy=(
                    self._protection_policy.to_dict()
                    if self._protection_policy is not None
                    else {}
                ),
            )
            if not isinstance(bundle, OMSOrderSubmissionBundle):
                raise OMSContractError("authoritative_oms_bundle_invalid")
            if bundle.intent is None or bundle.intent != intent:
                raise OMSContractError("authoritative_oms_intent_mismatch")
            risk = self._shared_platform_v3_oms.risk_decision_for(
                bundle, intent
            )
        except (OMSContractError, ValueError) as exc:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_t5_oms_contract:" + ";".join(exc.blockers)
                if isinstance(exc, OMSContractError)
                else "okx_demo_t5_oms_contract:" + str(exc)
            ) from exc
        lifecycle = self._oms.create_order(intent)
        lifecycle.mark_risk_checked(approved=risk.approved, reason=risk.reason)
        order: dict[str, Any] = {
            "instId": OKX_DEMO_INSTRUMENT_ID,
            "tdMode": "isolated",
            "side": order_plan["side"],
            "posSide": order_plan["position_side"],
            "ordType": (
                str(order_plan.get("entry_order_type") or "fok")
                if is_opening
                else "ioc"
            ),
            "px": order_plan["limit_price"],
            "sz": order_plan["contracts"],
            "clOrdId": order_plan["client_order_id"],
            "tag": OKX_DEMO_PAPER_ORDER_TAG,
        }
        if is_opening:
            if bundle.protection is None:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_t5_authoritative_protection_required"
                )
            protection = bundle.protection.to_exchange_payload()
            order["attachAlgoOrds"] = [
                {
                    key: value
                    for key, value in protection.items()
                    if key != "policy"
                }
            ]
        with self._lock:
            self._owned_client_order_ids.add(intent.client_order_id)
            protection = (
                bundle.protection.to_exchange_payload()
                if bundle.protection is not None
                else {}
            )
            attached_algo_client_id = str(
                protection.get("attachAlgoClOrdId") or ""
            )
            if is_opening:
                if not attached_algo_client_id:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_attached_algo_client_id_missing_before_post"
                    )
                self._state["risk_control"]["owned_attached_algos"][
                    attached_algo_client_id
                ] = {
                    "algo_client_order_id": attached_algo_client_id,
                    "parent_client_order_id": intent.client_order_id,
                    "instrument_id": OKX_DEMO_INSTRUMENT_ID,
                    "opening_intent": True,
                    "status": "submit_pending",
                    "fact_binding": self._hosted_protection_fact_binding(snapshot),
                }
            self._state["risk_control"]["pending_order_intents"][
                intent.client_order_id
            ] = {
                "status": "submit_pending",
                "persisted_before_post": True,
                "client_order_id": intent.client_order_id,
                "action": order_plan["action"],
                "risk_reducing_only": not is_opening,
                "created_at_utc": _iso(timestamp),
                "fact_binding": self._hosted_protection_fact_binding(snapshot),
                "order": {
                    "instId": OKX_DEMO_INSTRUMENT_ID,
                    "side": order_plan["side"],
                    "posSide": order_plan["position_side"],
                    "ordType": order["ordType"],
                    "sz": order_plan["contracts"],
                    "clOrdId": intent.client_order_id,
                    "tag": OKX_DEMO_PAPER_ORDER_TAG,
                },
            }
            stop_flatten_marker = _mapping(
                self._state["runtime"].get("stop_and_flatten")
            )
            if (
                not is_opening
                and str(stop_flatten_marker.get("status") or "") == "preflight"
            ):
                stop_flatten_marker.update(
                    {
                        "client_order_id": intent.client_order_id,
                        "post_attempts": 0,
                        "close_intent_persisted": True,
                        "close_intent_persisted_at_utc": _iso(timestamp),
                    }
                )
                self._state["runtime"]["stop_and_flatten"] = dict(
                    stop_flatten_marker
                )
                self._append_event(
                    "stop_and_flatten_close_intent_persisted_before_post",
                    {
                        "client_order_id": intent.client_order_id,
                        "retry_without_query_allowed": False,
                    },
                )
            self._append_event(
                "order_intent_persisted_before_post",
                {
                    "client_order_id": intent.client_order_id,
                    "action": order_plan["action"],
                    "retry_without_query_allowed": False,
                },
            )
            self._persist_state()
        final_order: Mapping[str, Any] = {}
        response: OkxDemoResponse | None = None
        post_attempted = False
        try:
            def submit_callback(_boundary_intent: OrderIntent) -> object:
                nonlocal post_attempted
                with self._lock:
                    authorization_fence = self._order_submit_authorization_fence()
                    self._assert_order_submit_path(
                        is_opening=is_opening,
                        exclude_client_order_id=intent.client_order_id,
                        incident_recovery_receipt_sha256=(
                            incident_recovery_receipt_sha256
                        ),
                        emergency_exit=emergency_exit,
                    )
                    lifecycle.mark_submitted(
                        unknown_outcome=True,
                        reason=(
                            "authorized_okx_demo_submit_attempted_after_"
                            "durable_intent"
                        ),
                    )
                    if (
                        self._order_submit_authorization_fence()
                        != authorization_fence
                    ):
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_order_submit_authorization_fence_changed"
                        )
                    if incident_recovery_receipt_sha256:
                        recovery = _mapping(
                            self._state["risk_control"].get(
                                "incident_recovery_intents"
                            )
                        ).get(incident_recovery_receipt_sha256)
                        if not isinstance(recovery, dict):
                            raise OkxDemoPaperRuntimeError(
                                "okx_demo_incident_recovery_intent_missing_before_post"
                            )
                        recovery["post_attempted"] = True
                        recovery["post_attempted_at_utc"] = _iso(self._clock())
                        self._persist_state()
                    post_attempted = True
                    stop_flatten_marker = _mapping(
                        self._state["runtime"].get("stop_and_flatten")
                    )
                    if (
                        not is_opening
                        and str(stop_flatten_marker.get("status") or "")
                        == "preflight"
                    ):
                        stop_flatten_marker.update(
                            {
                                "post_attempts": 1,
                                "post_attempted_at_utc": _iso(self._clock()),
                            }
                        )
                        self._state["runtime"]["stop_and_flatten"] = dict(
                            stop_flatten_marker
                        )
                        self._persist_state()
                return client.submit_order(order)

            dispatched = self._dispatch_execution_action(
                action=(
                    RuntimeAction.REDUCE_ONLY
                    if order_plan.get("risk_reducing_only") is True
                    else RuntimeAction.SUBMIT_NEW_ORDER
                ),
                client=client,
                intent=intent,
                risk=risk,
                snapshot=snapshot,
                attached_protection=(
                    protection if is_opening else None
                ),
                callback=submit_callback,
            )
            if not isinstance(dispatched, OkxDemoResponse):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_execution_boundary_submit_receipt_invalid"
                )
            response = dispatched
        except Exception as exc:
            if not post_attempted:
                with self._lock:
                    self._state["risk_control"]["pending_order_intents"][
                        intent.client_order_id
                    ].update(
                        {
                            "status": "blocked_before_post",
                            "retry_without_query_allowed": False,
                            "last_error": _safe_error(exc),
                        }
                    )
                    self._append_event(
                        "order_submit_blocked_after_durable_intent",
                        {
                            "client_order_id": intent.client_order_id,
                            "opening_order": is_opening,
                            "error": _safe_error(exc),
                            "post_attempted": False,
                        },
                    )
                    self._persist_state()
                raise
            final_order = self._query_submit_outcome_by_client_id(
                client,
                intent.client_order_id,
                expected_order=order,
                require_matching_fill=bool(
                    incident_recovery_receipt_sha256
                ),
            )
            if not final_order:
                self._freeze_ambiguous_submit(intent.client_order_id, exc)
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_submit_outcome_unknown_no_retry"
                ) from exc
        if response is not None and (not response.action_ok or not response.data):
            if response.ok and not response.data:
                final_order = self._query_submit_outcome_by_client_id(
                    client,
                    intent.client_order_id,
                    expected_order=order,
                    require_matching_fill=bool(
                        incident_recovery_receipt_sha256
                    ),
                )
                if not final_order:
                    self._freeze_ambiguous_submit(
                        intent.client_order_id,
                        OkxDemoPaperRuntimeError(
                            "okx_demo_submit_ack_missing"
                        ),
                    )
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_submit_outcome_unknown_no_retry"
                    )
            else:
                with self._lock:
                    self._state["risk_control"]["pending_order_intents"][
                        intent.client_order_id
                    ]["status"] = "rejected"
                    self._persist_state()
                lifecycle.reject(
                    reject_code="okx_demo_submit_rejected",
                    reject_reason=";".join(response.action_errors) or response.message or response.code,
                    risk_state=dict(order_plan["risk"]),
                    exchange_response=response.to_audit_dict(),
                )
                lifecycle.reconcile(reason="submit_rejection_reconciled")
                raise OkxDemoPaperRuntimeError("okx_demo_paper_submit_rejected")
        if response is not None and response.data:
            acknowledgement = response.data[0]
        else:
            acknowledgement = final_order
        order_id = str(acknowledgement.get("ordId") or "")
        if not order_id:
            self._freeze_ambiguous_submit(
                intent.client_order_id,
                OkxDemoPaperRuntimeError("okx_demo_paper_order_id_missing"),
            )
            raise OkxDemoPaperRuntimeError("okx_demo_paper_order_id_missing")
        lifecycle.mark_accepted(broker_order_id=order_id)
        with self._lock:
            self._state["risk_control"]["pending_order_intents"][
                intent.client_order_id
            ].update({"status": "accepted", "exchange_order_id": order_id})
            self._persist_state()
        for _ in range(self.config.order_poll_attempts):
            final_order = self._query_order_by_client_id(
                client,
                intent.client_order_id,
                allow_missing=False,
            )
            if str(final_order.get("state") or "") in {"filled", "canceled", "mmp_canceled"}:
                break
            time.sleep(self.config.order_poll_interval_seconds)
        fills_response = _require(client.private_get(
            "/api/v5/trade/fills", {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID, "ordId": order_id}
        ), "submitted_order_fills", require_data=False)
        fills = [_sanitize_fill(row) for row in fills_response.data]
        filled = sum((_decimal(row.get("size")) for row in fills), Decimal("0"))
        if filled <= 0:
            filled = _decimal(final_order.get("accFillSz"))
        if filled > 0:
            lifecycle.apply_fill(
                fill_quantity=float(filled),
                fill_id=str(fills[0].get("fill_id") if fills else final_order.get("tradeId") or ""),
                price=float(_decimal(fills[0].get("price") if fills else final_order.get("avgPx"))),
            )
        state = str(final_order.get("state") or "")
        safety_error = ""
        protection_receipt: dict[str, Any] = {}
        entry_fill_classification = ""
        bound_order_plan = {
            **dict(order_plan),
            "attached_protection": dict(protection),
        }
        if lifecycle.status == BTCPaperOrderStatus.PARTIALLY_FILLED:
            lifecycle.expire(
                reason=(
                    "partial_fill_entry_recovery_pending"
                    if partial_fill_recovery
                    else "fok_partial_fill_exchange_semantics_violation"
                    if is_opening
                    else "ioc_partial_fill_remainder_cancelled"
                )
            )
            lifecycle.reconcile(reason="partial_fill_reconciled")
            if partial_fill_recovery:
                entry_fill_classification = "partial_fill"
                try:
                    protection_receipt = self._verify_attached_protection(
                        client,
                        final_order=final_order,
                        order_plan={
                            **bound_order_plan,
                            "protection_contracts": _text(filled),
                        },
                    )
                except Exception as exc:
                    safety_error = (
                        "okx_demo_exchange_hosted_protection_unconfirmed:"
                        f"{_safe_error(exc)}"
                    )
            else:
                safety_error = (
                    "okx_demo_fok_partial_fill_requires_risk_reduction"
                    if is_opening
                    else "okx_demo_reduce_only_exit_partially_filled"
                )
        elif lifecycle.status == BTCPaperOrderStatus.FILLED:
            lifecycle.reconcile(reason="fill_reconciled")
            if partial_fill_recovery:
                entry_fill_classification = "full_fill"
            if is_opening:
                try:
                    protection_receipt = self._verify_attached_protection(
                        client,
                        final_order=final_order,
                        order_plan=(
                            {
                                **bound_order_plan,
                                "protection_contracts": _text(filled),
                            }
                            if partial_fill_recovery
                            else bound_order_plan
                        ),
                    )
                except Exception as exc:
                    safety_error = (
                        "okx_demo_exchange_hosted_protection_unconfirmed:"
                        f"{_safe_error(exc)}"
                    )
        elif state in {"canceled", "mmp_canceled"}:
            lifecycle.confirm_cancelled(reason="ioc_unfilled_cancelled")
            lifecycle.reconcile(reason="cancel_reconciled")
            if partial_fill_recovery:
                entry_fill_classification = "zero_fill"
        else:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_order_terminal_state_missing")
        order_record = {
            "signal": signal.__dict__ | {"direction": signal.direction.value, "timestamp_utc": _iso(signal.timestamp_utc)},
            "forecast": (
                None
                if sealed_forecast is None
                else {
                    **sealed_forecast.__dict__,
                    "direction": sealed_forecast.direction.value,
                    "timestamp_utc": _iso(sealed_forecast.timestamp_utc),
                    "expiry_utc": _iso(sealed_forecast.expiry_utc),
                    "quality": sealed_forecast.quality.__dict__,
                }
            ),
            "candidate_target_position": (
                None
                if sealed_candidate_target is None
                else sealed_candidate_target.__dict__
                | {"timestamp_utc": _iso(sealed_candidate_target.timestamp_utc)}
            ),
            "sealed_strategy_binding": dict(sealed_binding),
            "target_position": target.__dict__ | {"timestamp_utc": _iso(target.timestamp_utc)},
            "risk_decision": risk.__dict__ | {"checked_at": _iso(risk.checked_at)},
            "order_plan": bound_order_plan,
            "oms": lifecycle.to_dict(),
            "exchange_order_id": order_id,
            "exchange_state": state,
            "fills": fills,
            "exchange_hosted_protection": protection_receipt,
        }
        with self._lock:
            self._state["runtime"]["orders_submitted"] += 1
            self._state["runtime"]["fills_observed"] += len(fills)
            self._state["audit"] = [order_record, *self._state["audit"]][:100]
            pending_intent = self._state["risk_control"][
                "pending_order_intents"
            ][intent.client_order_id]
            pending_intent["status"] = "terminal"
            pending_intent["exchange_state"] = state
            if protection_receipt:
                owned = self._state["risk_control"][
                    "owned_attached_algos"
                ].get(
                    str(protection_receipt["algo_client_order_id"]),
                    {},
                )
                owned.update(
                    {
                        "algo_id": str(protection_receipt["algo_id"]),
                        "status": "active",
                    }
                )
                protection_receipt = {
                    **dict(protection_receipt),
                    "fact_binding": dict(_mapping(owned.get("fact_binding"))),
                }
                self._state["risk_control"]["active_protection"] = (
                    protection_receipt
                )
            self._append_event("order_lifecycle", order_record)
            if safety_error:
                self._set_risk_mode(OKX_DEMO_RISK_MODE_REDUCING, safety_error)
                self._append_safety_alert(safety_error)
                self._append_event(
                    "position_safety_degraded",
                    {
                        "error": safety_error,
                        "opening_allowed": False,
                        "risk_reducing_only": True,
                    },
                )
            self._persist_state()
        followup = self._collect_exchange_snapshot(client)
        followup_blockers = self._preflight_blockers(followup, require_flat=False)
        if safety_error:
            tolerated_protection_blockers = {
                "okx_demo_nonflat_position_has_no_verified_protection",
                "okx_demo_verified_protection_missing_from_exchange_pending",
                "okx_demo_exchange_protection_not_active",
                "okx_demo_exchange_protection_contract_mismatch",
            }
            followup_blockers = [
                blocker
                for blocker in followup_blockers
                if blocker not in tolerated_protection_blockers
            ]
        if followup_blockers:
            raise OkxDemoPaperRuntimeError(";".join(followup_blockers))
        with self._lock:
            self._apply_snapshot(followup)
        self._commit_ledger_reconciliation(
            snapshot=followup,
            trigger="order_terminal_followup",
            order_record=order_record,
        )
        with self._lock:
            if _gross_position_contracts(followup.get("positions", [])) == 0:
                self._state["risk_control"]["active_protection"] = {}
            self._persist_state()
        if safety_error and not partial_fill_recovery:
            raise OkxDemoPaperRuntimeError(safety_error)
        return {
            "client_order_id": intent.client_order_id,
            "exchange_order_id": order_id,
            "filled_contracts": _text(filled),
            "entry_fill_classification": entry_fill_classification,
            "protection_verified": bool(protection_receipt),
            "opening_error": safety_error,
            "orders_posted": 1,
        }

    def _assert_order_submit_path(
        self,
        *,
        is_opening: bool,
        exclude_client_order_id: str = "",
        incident_recovery_receipt_sha256: str = "",
        emergency_exit: bool = False,
    ) -> None:
        with self._lock:
            mode = str(
                self._state.get("risk_control", {}).get("mode") or ""
            )
            emergency_authorization = self._fresh_state_emergency_exit_authorization
            emergency_override = (
                emergency_exit
                and not is_opening
                and isinstance(emergency_authorization, Mapping)
                and bool(emergency_authorization.get("nonce"))
                and str(emergency_authorization.get("client_order_id") or "")
                == exclude_client_order_id
                and self._state.get("runtime", {}).get("active") is False
                and self._state.get("runtime", {}).get("opening_allowed") is False
                and self._state.get("runtime", {}).get("cancel_only") is True
                and mode == OKX_DEMO_RISK_MODE_FROZEN
                and str(
                    emergency_authorization.get("private_ws_generation") or ""
                )
                == str(self._private_ws_generation)
            )
            if (
                self._stop_event.is_set()
                or (
                    self._state.get("runtime", {}).get("active") is not True
                    and not emergency_override
                )
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_order_submit_runtime_inactive"
                )
            allowed_modes = (
                {OKX_DEMO_RISK_MODE_RUNNING}
                if is_opening
                else {
                    OKX_DEMO_RISK_MODE_RUNNING,
                    OKX_DEMO_RISK_MODE_REDUCING,
                    *(  # Emergency exit is the only frozen-mode exception.
                        (OKX_DEMO_RISK_MODE_FROZEN,)
                        if emergency_override
                        else ()
                    ),
                }
            )
            if mode not in allowed_modes:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_order_submit_mode_not_allowed:" + mode
                )
            if (
                is_opening
                and self._state.get("runtime", {}).get("opening_allowed")
                is not True
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_opening_submit_not_allowed"
                )
            if (
                is_opening
                and self._state.get("runtime", {}).get(
                    "fault_drill_scenario"
                )
                == "partial_fill_disconnect"
                and self._state.get("runtime", {}).get(
                    "fault_drill_entry_authorized"
                )
                is not True
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_partial_fill_opening_requires_explicit_fault_drill"
                )
            if is_opening and self._state.get("runtime", {}).get(
                "cancel_only"
            ) is not False:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_opening_submit_cancel_only_active"
                )
            if is_opening:
                private_ws = _mapping(self._state.get("private_ws"))
                if not (
                    private_ws.get("connected") is True
                    and private_ws.get("listener_alive") is True
                    and private_ws.get(
                        "opening_allowed_after_reconciliation"
                    )
                    is True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_opening_submit_private_ws_not_reconciled"
                    )
                if _mapping(
                    self._state.get("risk_control", {}).get("dead_man")
                ).get("armed") is not True:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_opening_submit_dead_man_not_armed"
                    )
            if not self._write_path_is_trusted() and not (
                emergency_override
                or (
                    not is_opening
                    and self._incident_recovery_close_authorized(
                        receipt_sha256=incident_recovery_receipt_sha256,
                        close_client_order_id=exclude_client_order_id,
                    )
                )
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_order_submit_write_path_not_trusted"
                )
            ledger = self._state.get("ledger_reconciliation", {})
            if not (
                ledger.get("status") == "reconciled"
                and ledger.get("current_state_exchange_snapshot_match")
                is True
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_order_submit_ledger_not_current"
                )
            unresolved = [
                str(client_order_id)
                for client_order_id, row in _mapping(
                    self._state.get("risk_control", {}).get(
                        "pending_order_intents"
                    )
                ).items()
                if str(client_order_id) != exclude_client_order_id
                and isinstance(row, Mapping)
                and str(row.get("status") or "")
                in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
            ]
            if unresolved:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_order_submit_blocked_by_unresolved_intent:"
                    + ",".join(sorted(unresolved))
                )

    def _order_submit_authorization_fence(self) -> tuple[Any, ...]:
        runtime = _mapping(self._state.get("runtime"))
        risk = _mapping(self._state.get("risk_control"))
        ledger = _mapping(self._state.get("ledger_reconciliation"))
        private_ws = _mapping(self._state.get("private_ws"))
        unresolved = tuple(
            sorted(
                (
                    str(client_order_id),
                    str(row.get("status") or ""),
                )
                for client_order_id, row in _mapping(
                    risk.get("pending_order_intents")
                ).items()
                if isinstance(row, Mapping)
                and str(row.get("status") or "")
                in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
            )
        )
        return (
            self._stop_event.is_set(),
            runtime.get("active") is True,
            runtime.get("opening_allowed") is True,
            runtime.get("cancel_only") is True,
            runtime.get("fault_drill_entry_authorized") is True,
            str(risk.get("mode") or ""),
            risk.get("write_path_trusted") is True,
            _mapping(risk.get("dead_man")).get("armed") is True,
            str(_mapping(risk.get("dead_man")).get("last_ack_utc") or ""),
            ledger.get("status") == "reconciled",
            ledger.get("current_state_exchange_snapshot_match") is True,
            private_ws.get("connected") is True,
            private_ws.get("listener_alive") is True,
            private_ws.get("opening_allowed_after_reconciliation") is True,
            self._private_ws_generation,
            unresolved,
        )

    def _incident_recovery_close_authorized(
        self,
        *,
        receipt_sha256: str,
        close_client_order_id: str,
    ) -> bool:
        record = _mapping(
            _mapping(self._state.get("risk_control"))
            .get("incident_recovery_intents", {})
        ).get(receipt_sha256)
        private_ws = _mapping(self._state.get("private_ws"))
        return bool(
            isinstance(record, Mapping)
            and record.get("status") == "intent_persisted"
            and record.get("failed_receipt_sha256") == receipt_sha256
            and record.get("close_cl_ord_id") == close_client_order_id
            and record.get("retry_allowed") is False
            and private_ws.get("connected") is True
            and private_ws.get("listener_alive") is True
            and private_ws.get("opening_allowed_after_reconciliation") is True
        )

    def _query_order_by_client_id(
        self,
        client: OkxDemoClient,
        client_order_id: str,
        *,
        allow_missing: bool,
    ) -> Mapping[str, Any]:
        response = client.private_get(
            "/api/v5/trade/order",
            {
                "instId": OKX_DEMO_INSTRUMENT_ID,
                "clOrdId": client_order_id,
            },
        )
        if not response.ok:
            raise OkxDemoPaperRuntimeError(
                f"okx_demo_paper_submitted_order_failed:{response.code}"
            )
        if not response.data:
            if allow_missing:
                return {}
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_submitted_order_empty"
            )
        row = response.data[0]
        if str(row.get("clOrdId") or "") != client_order_id:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_order_query_client_id_mismatch"
            )
        return row

    def _query_submit_outcome_by_client_id(
        self,
        client: OkxDemoClient,
        client_order_id: str,
        *,
        expected_order: Mapping[str, Any],
        require_matching_fill: bool = False,
    ) -> Mapping[str, Any]:
        read_errors: list[str] = []
        try:
            order = self._query_order_by_client_id(
                client,
                client_order_id,
                allow_missing=True,
            )
        except Exception as exc:
            read_errors.append(
                "/api/v5/trade/order:" + _safe_error(exc)
            )
            order = {}
        query_specs = (
            (
                "/api/v5/trade/orders-pending",
                {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
                "orders",
            ),
            (
                "/api/v5/trade/orders-history",
                {
                    "instType": "SWAP",
                    "instId": OKX_DEMO_INSTRUMENT_ID,
                    "limit": "100",
                },
                "orders",
            ),
            (
                "/api/v5/trade/fills",
                {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
                "fills",
            ),
            (
                "/api/v5/account/positions",
                {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
                "positions",
            ),
        )
        rows_by_kind: dict[str, list[Mapping[str, Any]]] = {
            "orders": [order] if order else [],
            "fills": [],
            "positions": [],
        }
        for path, params, kind in query_specs:
            try:
                response = client.private_get(path, params)
                checked = _require(
                    response,
                    "submit_outcome_" + path.rsplit("/", 1)[-1],
                    require_data=False,
                )
                rows_by_kind[kind].extend(
                    row for row in checked.data if isinstance(row, Mapping)
                )
            except Exception as exc:
                read_errors.append(f"{path}:{_safe_error(exc)}")
        matching_orders = [
            row
            for row in rows_by_kind["orders"]
            if _client_order_id(row) == client_order_id
        ]
        exact_matching_orders = [
            row
            for row in matching_orders
            if _queried_order_matches_expected(row, expected_order)
        ]
        unique_exact_orders = {
            str(row.get("ordId") or ""): row
            for row in exact_matching_orders
            if str(row.get("ordId") or "")
        }
        matching_order = (
            next(iter(unique_exact_orders.values()))
            if len(unique_exact_orders) == 1
            and len(exact_matching_orders) == len(matching_orders)
            else None
        )
        matching_fills = [
            row
            for row in rows_by_kind["fills"]
            if _client_order_id(row) == client_order_id
        ]
        exact_matching_fills = [
            row
            for row in matching_fills
            if str(row.get("ordId") or "") in unique_exact_orders
            and str(row.get("instId") or "")
            == str(expected_order.get("instId") or "")
            and str(row.get("side") or "")
            == str(expected_order.get("side") or "")
            and str(row.get("posSide") or "")
            == str(expected_order.get("posSide") or "")
        ]
        matching_fill_quantity = sum(
            (_decimal(row.get("fillSz")) for row in exact_matching_fills),
            Decimal("0"),
        )
        if require_matching_fill and not (
            matching_order is not None
            and exact_matching_fills
            and matching_fill_quantity == _decimal(expected_order.get("sz"))
        ):
            matching_order = None
        sanitized_positions = [
            _sanitize_position(row) for row in rows_by_kind["positions"]
        ]
        position_evidence_valid = True
        try:
            signed_position = _signed_position(sanitized_positions)
            gross_position = _gross_position_contracts(sanitized_positions)
        except OkxDemoPaperRuntimeError as exc:
            position_evidence_valid = False
            signed_position = Decimal("NaN")
            gross_position = Decimal("NaN")
            read_errors.append(
                "/api/v5/account/positions:" + _safe_error(exc)
            )
        with self._lock:
            pending = self._state["risk_control"][
                "pending_order_intents"
            ].setdefault(
                client_order_id,
                {"client_order_id": client_order_id},
            )
            pending["outcome_probe"] = {
                "queried_by_client_order_id": True,
                "direct_order_match": bool(order),
                "order_matches": len(matching_orders),
                "unique_exact_order_matches": len(unique_exact_orders),
                "exact_order_identity_match": matching_order is not None,
                "fill_matches": len(matching_fills),
                "exact_fill_matches": len(exact_matching_fills),
                "exact_fill_quantity": _text(matching_fill_quantity),
                "signed_position_contracts": (
                    _text(signed_position)
                    if position_evidence_valid
                    else "invalid"
                ),
                "gross_position_contracts": (
                    _text(gross_position)
                    if position_evidence_valid
                    else "invalid"
                ),
                "position_evidence_valid": position_evidence_valid,
                "read_errors": read_errors,
                "blind_retry_allowed": False,
                "queried_at_utc": _iso(self._clock()),
            }
            self._append_event(
                "submit_outcome_orders_fills_positions_probed",
                {
                    "client_order_id": client_order_id,
                    **pending["outcome_probe"],
                },
            )
            self._persist_state()
        return (matching_order or {}) if position_evidence_valid else {}

    def _freeze_ambiguous_submit(
        self,
        client_order_id: str,
        exc: Exception,
    ) -> None:
        reason = f"okx_demo_submit_outcome_unknown:{_safe_error(exc)}"
        with self._lock:
            pending = self._state["risk_control"]["pending_order_intents"].setdefault(
                client_order_id,
                {"client_order_id": client_order_id},
            )
            pending.update(
                {
                    "status": "unknown",
                    "retry_without_query_allowed": False,
                    "last_error": reason,
                }
            )
            self._state["risk_control"]["write_path_trusted"] = False
            self._set_risk_mode(OKX_DEMO_RISK_MODE_FROZEN, reason)
            self._append_safety_alert(reason)
            self._append_event(
                "submit_outcome_unknown_query_before_retry",
                {
                    "client_order_id": client_order_id,
                    "blind_retry_allowed": False,
                },
            )
            self._persist_state()

    def _verify_attached_protection(
        self,
        client: OkxDemoClient,
        *,
        final_order: Mapping[str, Any],
        order_plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected = _mapping(order_plan.get("attached_protection"))
        expected_client_id = str(expected.get("attachAlgoClOrdId") or "")
        expected_parent_client_id = str(
            order_plan.get("client_order_id") or ""
        )
        observed_parent_client_id = str(final_order.get("clOrdId") or "")
        attached = final_order.get("attachAlgoOrds")
        rows = attached if isinstance(attached, list) else []
        matching_parent_rows = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("attachAlgoClOrdId") or "")
            == expected_client_id
        ]
        parent_row = (
            matching_parent_rows[0] if matching_parent_rows else None
        )
        if parent_row is None:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_attached_algo_missing_from_parent_order"
            )
        parent_fail_code = parent_row.get("failCode")
        parent_fail_reason = parent_row.get("failReason")
        parent_acknowledged = (
            parent_fail_code == "0"
            and (
                parent_fail_reason is None
                or parent_fail_reason == ""
            )
        ) or (
            parent_fail_code == ""
            and "failReason" in parent_row
            and parent_fail_reason == ""
        )
        parent_conflict_reconciled = (
            isinstance(parent_fail_code, str)
            and bool(parent_fail_code)
            and parent_fail_code != "0"
        )
        if parent_conflict_reconciled and len(matching_parent_rows) != 1:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_attached_algo_parent_reports_failure"
            )
        if not parent_acknowledged and not parent_conflict_reconciled:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_attached_algo_parent_reports_failure"
            )
        algo_id = "" if parent_conflict_reconciled else str(
            parent_row.get("attachAlgoId")
            or parent_row.get("algoId")
            or ""
        )
        query = (
            {"algoClOrdId": expected_client_id}
            if parent_conflict_reconciled
            else (
                {"algoId": algo_id}
                if algo_id
                else {"algoClOrdId": expected_client_id}
            )
        )
        response = client.private_get("/api/v5/trade/order-algo", query)
        query_only_readback_attempts = 1
        readback_source = "order_algo"
        if parent_conflict_reconciled:
            if (
                response.http_status == 200
                and isinstance(response.code, str)
                and response.code == "51603"
            ):
                if (
                    not expected_parent_client_id
                    or observed_parent_client_id != expected_parent_client_id
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_attached_algo_parent_order_identity_mismatch"
                    )
                readback_source = (
                    "orders_algo_pending_after_order_algo_51603"
                )
                algo: Mapping[str, Any] | None = None
                for attempt in range(self.config.order_poll_attempts):
                    if self._stop_event.is_set():
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_attached_algo_pending_readback_stopped"
                        )
                    pending = _require(
                        client.private_get(
                            "/api/v5/trade/orders-algo-pending",
                            {
                                "instId": OKX_DEMO_INSTRUMENT_ID,
                                "ordType": "oco",
                            },
                        ),
                        "attached_protection_pending_readback",
                        require_data=False,
                    )
                    query_only_readback_attempts += 1
                    if self._stop_event.is_set():
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_attached_algo_pending_readback_stopped"
                        )
                    matching_pending_rows = [
                        row
                        for row in pending.data
                        if isinstance(row, Mapping)
                        and str(row.get("algoClOrdId") or "")
                        == expected_client_id
                    ]
                    if len(matching_pending_rows) > 1:
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_attached_algo_pending_readback_ambiguous"
                        )
                    if not matching_pending_rows:
                        if attempt + 1 >= self.config.order_poll_attempts:
                            raise OkxDemoPaperRuntimeError(
                                "okx_demo_attached_algo_pending_readback_empty"
                            )
                        if self._stop_event.wait(
                            self.config.order_poll_interval_seconds
                        ):
                            raise OkxDemoPaperRuntimeError(
                                "okx_demo_attached_algo_pending_readback_stopped"
                            )
                        continue
                    if len(pending.data) != 1:
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_attached_algo_pending_readback_ambiguous"
                        )
                    candidate = matching_pending_rows[0]
                    if str(
                        candidate.get("ordType")
                        or candidate.get("order_type")
                        or ""
                    ) != "oco":
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_attached_algo_pending_readback_type_mismatch"
                        )
                    pending_parent_client_id = str(
                        candidate.get("parentClOrdId")
                        or candidate.get("parent_client_order_id")
                        or candidate.get("clOrdId")
                        or ""
                    )
                    if (
                        pending_parent_client_id
                        and pending_parent_client_id != expected_parent_client_id
                    ):
                        raise OkxDemoPaperRuntimeError(
                            "okx_demo_attached_algo_pending_readback_parent_mismatch"
                        )
                    algo = candidate
                    break
                if algo is None:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_attached_algo_pending_readback_empty"
                    )
            else:
                checked = _require(response, "attached_protection")
                if len(checked.data) != 1:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_attached_algo_readback_ambiguous"
                    )
                algo = checked.data[0]
                if not isinstance(algo, Mapping):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_attached_algo_readback_ambiguous"
                    )
        else:
            algo = _first(response, "attached_protection")
        active_states = (
            {"live"}
            if parent_conflict_reconciled
            else {"live", "effective", "partially_effective"}
        )
        if str(algo.get("state") or "") not in active_states:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_attached_algo_not_active"
            )
        protection_contracts = _decimal(
            order_plan.get("protection_contracts")
            or order_plan.get("contracts")
        )
        checks = {
            "algo_client_order_id": (
                str(algo.get("algoClOrdId") or "")
                == expected_client_id
            ),
            "algo_id": (
                bool(str(algo.get("algoId") or ""))
                and (
                    parent_conflict_reconciled
                    or not algo_id
                    or str(algo.get("algoId") or "") == algo_id
                )
            ),
            "instrument_id": (
                str(algo.get("instId") or "")
                == OKX_DEMO_INSTRUMENT_ID
            ),
            "contracts": (
                _decimal(algo.get("sz"))
                == protection_contracts
                and protection_contracts > 0
            ),
            "take_profit_trigger": (
                str(algo.get("tpTriggerPx") or "")
                == str(expected.get("tpTriggerPx") or "")
            ),
            "stop_loss_trigger": (
                str(algo.get("slTriggerPx") or "")
                == str(expected.get("slTriggerPx") or "")
            ),
            "take_profit_trigger_type": (
                str(algo.get("tpTriggerPxType") or "") == "mark"
            ),
            "stop_loss_trigger_type": (
                str(algo.get("slTriggerPxType") or "") == "mark"
            ),
            "take_profit_market_exit": (
                str(algo.get("tpOrdPx") or "") == "-1"
            ),
            "stop_loss_market_exit": (
                str(algo.get("slOrdPx") or "") == "-1"
            ),
            "position_side": (
                str(algo.get("posSide") or "")
                == str(order_plan.get("position_side") or "")
            ),
        }
        if not all(checks.values()):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_attached_algo_contract_mismatch"
            )
        return {
            "status": "exchange_accepted",
            "verified_at_utc": _iso(self._clock()),
            "parent_acknowledged": parent_acknowledged,
            "parent_conflict_reconciled": parent_conflict_reconciled,
            "parent_fail_code": (
                parent_fail_code if parent_conflict_reconciled else ""
            ),
            "query_first": True,
            "readback_source": readback_source,
            "query_only_readback_attempts": query_only_readback_attempts,
            "parent_client_order_id": str(order_plan.get("client_order_id") or ""),
            "algo_id": algo_id or str(algo.get("algoId") or ""),
            "algo_client_order_id": expected_client_id,
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "position_side": str(order_plan.get("position_side") or ""),
            "contracts": str(
                order_plan.get("protection_contracts")
                or order_plan.get("contracts")
                or ""
            ),
            "tp_trigger_px": str(expected.get("tpTriggerPx") or ""),
            "sl_trigger_px": str(expected.get("slTriggerPx") or ""),
            "trigger_type": "mark",
            "market_exit": True,
            "policy": dict(_mapping(expected.get("policy"))),
            "checks": checks,
        }

    def _apply_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        self._state["exchange"] = json.loads(json.dumps(snapshot))
        account = _mapping(snapshot.get("account"))
        if "identity" in account:
            self._set_authoritative_account_identity(account.get("identity"))
            self._state["runtime"]["account_identity"] = self.account_identity_projection()
            self._historicalize_current_start_operation_if_identity_changed()
        operation = self._state.get("runtime", {}).get("start_operation")
        if isinstance(operation, Mapping) and operation.get("operation_id"):
            leverage_rows = [row for row in snapshot.get("leverage", []) if isinstance(row, Mapping)]
            actual = {
                str(row.get("position_side") or ""): str(row.get("leverage") or "")
                for row in leverage_rows
            }
            operation = dict(operation)
            operation["actual_long_leverage"] = actual.get("long") or None
            operation["actual_short_leverage"] = actual.get("short") or None
            nested = dict(_mapping(operation.get("start_attempt")))
            nested.update(
                {
                    "actual_long_leverage": operation["actual_long_leverage"],
                    "actual_short_leverage": operation["actual_short_leverage"],
                }
            )
            operation["start_attempt"] = nested
            self._state["runtime"]["start_operation"] = operation
        self._state["runtime"]["last_reconciled_at_utc"] = str(snapshot.get("captured_at_utc") or "")
        budget_state = self.config.runtime_data_budget.evaluate(
            runtime_data_bytes=_directory_size_bytes(
                Path(self.config.output_dir)
            )
        )
        self._state["runtime_data_budget"]["state"] = budget_state
        if budget_state["cancel_only_required"]:
            self._enter_cancel_only(
                "okx_demo_runtime_data_budget_stop_reached", active=True
            )
        else:
            self._market_ring.append(
                {
                    "ticker": snapshot.get("ticker", {}),
                    "book": snapshot.get("book", {}),
                    "mark": snapshot.get("mark", {}),
                    "funding": snapshot.get("funding", {}),
                },
                observed_at_utc=self._clock(),
            )
        self._state["market_data_ring"] = self._market_ring.summary()

    def _capture_completed_hour_receipt(
        self,
        *,
        snapshot: Mapping[str, Any],
        decision: Mapping[str, Any],
    ) -> None:
        now = self._clock().astimezone(timezone.utc)
        completed_hour = now.replace(minute=0, second=0, microsecond=0)
        with self._lock:
            runtime = dict(self._state.get("runtime", {}))
            private_ws = dict(self._state.get("private_ws", {}))
            strategy = dict(self._state.get("strategy", {}))
        started = _parse_utc(runtime.get("started_at_utc"))
        if (
            started is None
            or started > completed_hour - timedelta(hours=1)
        ):
            return
        ledger_path = (
            Path(self.config.output_dir)
            / "observation"
            / "hourly_observation_receipts.jsonl"
        )
        receipts = load_observation_receipt_ledger(ledger_path)
        completed_key = completed_hour.isoformat()
        if any(
            str(row.get("observation_hour_utc") or "") == completed_key
            for row in receipts
        ):
            return
        reconciliation_ok = (
            runtime.get("active") is True
            and runtime.get("cancel_only") is False
            and runtime.get("opening_allowed") is True
            and private_ws.get("opening_allowed_after_reconciliation") is True
        )
        gap_flags: list[str] = []
        tail = decision.get("runtime_public_candle_tail")
        if strategy.get("strategy_id") in {
            STABLE_STRATEGY_LINE,
            OKX_NATIVE_STRATEGY_LINE,
        } and not isinstance(tail, Mapping):
            gap_flags.append("runtime_public_candle_tail_missing")
        if not private_ws.get("reconnect_rest_reconciled", True):
            gap_flags.append("private_ws_reconnect_reconciliation_missing")
        bills = [
            row
            for row in snapshot.get("bills", [])
            if isinstance(row, Mapping)
            and (
                str(row.get("type") or "") == "8"
                or str(row.get("sub_type") or "") == "173"
            )
        ]
        funding_cashflow = _observed_decimal_total(
            bills,
            field="balance_change",
            observed_flag="balance_change_observed",
            error_code="okx_demo_funding_cashflow_unknown",
        )
        previous_hash = (
            str(receipts[-1].get("receipt_sha256") or "")
            if receipts
            else None
        )
        source_head = _repo_head(self.config.repo_root)
        strategy_version = str(
            strategy.get("strategy_version")
            or decision.get("strategy_version")
            or ""
        )
        data_version = str(
            decision.get("runtime_data_version")
            or (
                "okx_public_candles_1h_v1"
                if strategy.get("strategy_id") in {
                    STABLE_STRATEGY_LINE,
                    OKX_NATIVE_STRATEGY_LINE,
                }
                else "btc_completed_1h_runtime_data_v1"
            )
        )
        receipt = build_hourly_observation_receipt(
            source_head=source_head,
            strategy_version=strategy_version,
            data_version=data_version,
            runtime_version=OKX_DEMO_PAPER_RUNTIME_VERSION,
            observed_at_utc=completed_hour,
            heartbeat_status="healthy" if reconciliation_ok else "degraded",
            natural_sample_count=1,
            fill_count=len(
                [
                    row
                    for row in snapshot.get("fills", [])
                    if isinstance(row, Mapping)
                ]
            ),
            funding_observation_count=len(bills),
            funding_cashflow=float(funding_cashflow),
            reconciliation_status=(
                "reconciled" if reconciliation_ok else "mismatch"
            ),
            outage_count=0 if reconciliation_ok else 1,
            gap_flags=gap_flags,
            previous_receipt_sha256=previous_hash,
            authorized_runtime_observed=runtime.get("active") is True,
            runtime_run_id=str(runtime.get("run_id") or ""),
        )
        append_hourly_observation_receipt(
            ledger_path=ledger_path,
            receipt=receipt,
        )
        receipts = load_observation_receipt_ledger(ledger_path)
        report = build_observation_window_report(
            receipts=receipts,
            current_head=source_head,
            current_strategy_version=strategy_version,
            current_data_version=data_version,
            current_runtime_version=OKX_DEMO_PAPER_RUNTIME_VERSION,
            run_id=str(runtime.get("run_id") or ""),
            generated_at_utc=now,
        )
        with self._lock:
            self._state["observation"] = {
                "observation_receipt_count": len(receipts),
                "consecutive_hours": report["observation_hours"],
                "window_complete": report["window_25h_complete"],
                "cumulative_observation_hours": report[
                    "cumulative_observation_hours"
                ],
                "cumulative_window_25h_complete": report[
                    "cumulative_window_25h_complete"
                ],
                "cumulative_blockers": list(
                    report["cumulative_blockers"]
                ),
                "ledger_hash": report["ledger_integrity"]["ledger_sha256"],
                "last_receipt_sha256": report["ledger_integrity"][
                    "last_receipt_sha256"
                ],
                "last_observation_hour_utc": completed_key,
                "blockers": list(report["blockers"]),
                "promotion_evidence_ready": False,
            }
            self._persist_state()

    def _commit_new_funding_if_observed(
        self,
        *,
        snapshot: Mapping[str, Any],
    ) -> None:
        bills = [
            dict(row)
            for row in snapshot.get("bills", [])
            if isinstance(row, Mapping)
            and (
                str(row.get("type") or "") == "8"
                or str(row.get("sub_type") or "") == "173"
            )
        ]
        if not bills:
            return
        funding_hash = hashlib.sha256(
            json.dumps(
                bills,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self._lock:
            if (
                self._state.get("ledger_reconciliation", {}).get(
                    "last_funding_ledger_hash"
                )
                == funding_hash
            ):
                return
        self._commit_ledger_reconciliation(
            snapshot=snapshot,
            trigger="funding_cashflow_observed",
        )

    def _replay_reconciled_ledger(
        self, *, recovery: Any, baseline_sequence: int, account_identity: str,
        candidate_uow: Mapping[str, Any], **options: Any,
    ) -> dict[str, Any]:
        """Default authority path, unchanged; offline subclasses may compact verified inputs."""
        prior_uows = [event["payload"] for event in recovery.events
                      if event.get("event_type") == "ledger_uow_committed"
                      and int(event.get("sequence") or 0) > baseline_sequence]
        return replay_account_ledger_uows(uow_payloads=[*prior_uows, candidate_uow], **options)

    def _commit_ledger_reconciliation(
        self,
        *,
        snapshot: Mapping[str, Any],
        trigger: str,
        order_record: Mapping[str, Any] | None = None,
        apply_snapshot: bool = False,
    ) -> None:
        positions = [
            dict(row)
            for row in snapshot.get("positions", [])
            if isinstance(row, Mapping)
        ]
        fills = [
            dict(row)
            for row in snapshot.get("fills", [])
            if isinstance(row, Mapping)
        ]
        orders = [
            dict(row)
            for row in snapshot.get("orders", [])
            if isinstance(row, Mapping)
        ]
        pending = [
            dict(row)
            for row in snapshot.get("pending_orders", [])
            if isinstance(row, Mapping)
        ]
        pending_algos = [
            dict(row)
            for row in snapshot.get("pending_algo_orders", [])
            if isinstance(row, Mapping)
        ]
        bills = [
            dict(row)
            for row in snapshot.get("bills", [])
            if isinstance(row, Mapping)
        ]
        balance = snapshot.get("balance")
        if not isinstance(balance, Mapping) or not balance:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_ledger_balance_snapshot_missing"
            )
        mark_price = str(_mapping(snapshot.get("mark")).get("mark_price") or "")
        index_price = str(
            _mapping(snapshot.get("index")).get("index_price") or ""
        )
        instrument = _mapping(snapshot.get("instrument"))
        if not mark_price or not index_price or not instrument:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_ledger_risk_context_snapshot_incomplete"
            )
        funding_rows = [
            row
            for row in bills
            if str(row.get("type") or "") == "8"
            or str(row.get("sub_type") or "") == "173"
        ]
        funding_cashflow = _observed_decimal_total(
            funding_rows,
            field="balance_change",
            observed_flag="balance_change_observed",
            error_code="okx_demo_funding_cashflow_unknown",
        )
        # Keep the durable UOW producer on the same canonical bytes consumed by
        # the production-composition evidence projection.  The helper preserves
        # the exact seven containers and filters funding bills to type 8/173.
        snapshot_hash = _fault_ledger_snapshot_sha256(snapshot)
        risk_context = {
            "mark_price": mark_price,
            "index_price": index_price,
            "liquidation_buffer_bps": _liquidation_buffer_bps(
                positions=positions,
                mark_price=_decimal(mark_price),
            ),
            "venue_rules": {
                "instrument_id": instrument.get("instrument_id"),
                "contract_value_btc": instrument.get("contract_value_btc"),
                "tick_size": instrument.get("tick_size"),
                "lot_size": instrument.get("lot_size"),
                "minimum_size": instrument.get("minimum_size"),
            },
            "reconciliation_match": True,
            "exchange_hosted_protection": pending_algos,
        }
        with self._lock:
            if apply_snapshot:
                # Keep the exchange state and the ledger UOW bound to one
                # snapshot.  This is used only by the S2 pre-entry refresh;
                # all existing callers retain their current state semantics.
                self._apply_snapshot(snapshot)
            current_state_exchange = self._state.get("exchange", {})
            current_exchange = {
                "orders": list(current_state_exchange.get("orders") or []),
                "pending_orders": list(
                    current_state_exchange.get("pending_orders") or []
                ),
                "pending_algo_orders": list(
                    current_state_exchange.get("pending_algo_orders") or []
                ),
                "fills": list(current_state_exchange.get("fills") or []),
                "positions": list(
                    current_state_exchange.get("positions") or []
                ),
                "balance": dict(
                    _mapping(current_state_exchange.get("balance"))
                ),
                "bills": list(current_state_exchange.get("bills") or []),
            }
            current_hash = hashlib.sha256(
                json.dumps(
                    current_exchange,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            reconciliation_match = current_hash == hashlib.sha256(
                json.dumps(
                    {
                        "orders": orders,
                        "pending_orders": pending,
                        "pending_algo_orders": pending_algos,
                        "fills": fills,
                        "positions": positions,
                        "balance": dict(balance),
                        "bills": bills,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            funding_hash = hashlib.sha256(
                json.dumps(
                    funding_rows,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            account = _mapping(snapshot.get("account"))
            account_identity = _mapping(account.get("identity"))
            account_identity_hash = str(account_identity.get("hash") or "")
            captured_at_utc = str(snapshot.get("captured_at_utc") or "")
            equity_usdt = _mapping(balance).get("equity_usdt")
            current_drawdown_fact = _mapping(
                self._state.get("account_risk_facts")
            )
            previous_drawdown_fact = (
                current_drawdown_fact
                if current_drawdown_fact.get("risk_eligible") is True
                else _mapping(self._state.get("account_risk_last_valid_fact"))
            )
            cashflow_evidence = _mapping(
                snapshot.get("account_cashflow_evidence")
            )
            exact_observation_retry = (
                current_drawdown_fact.get("risk_eligible") is True
                and current_drawdown_fact.get("account_identity_hash")
                == account_identity_hash
                and current_drawdown_fact.get("snapshot_sha256")
                == snapshot_hash
                and current_drawdown_fact.get("observed_at_utc")
                == captured_at_utc.replace("+00:00", "Z")
                and _decimal(current_drawdown_fact.get("equity_usdt"))
                == _decimal(equity_usdt)
            )
            if exact_observation_retry:
                # A retry of the exact persisted observation must replay the
                # same UOW bytes.  It is not a new observation and therefore
                # must not demand a second coverage interval starting at
                # itself.  Later timestamps still take the normal validated
                # cashflow path below.
                account_drawdown_fact = dict(current_drawdown_fact)
            elif previous_drawdown_fact.get("risk_eligible") is True:
                try:
                    verified_cashflow_evidence = validate_account_cashflow_evidence(
                        cashflow_evidence,
                        expected_account_identity_hash=account_identity_hash,
                        expected_snapshot_sha256=snapshot_hash,
                        expected_coverage_start_utc=previous_drawdown_fact.get(
                            "observed_at_utc"
                        ),
                        expected_coverage_end_utc=captured_at_utc,
                    )
                except AccountRiskFactError:
                    verified_cashflow_evidence = {}
                account_drawdown_fact = advance_account_drawdown_fact(
                    previous=previous_drawdown_fact,
                    account_identity_hash=account_identity_hash,
                    account_scope="dedicated_demo_account",
                    currency="USDT",
                    snapshot_sha256=snapshot_hash,
                    observed_at_utc=captured_at_utc,
                    reference_time_utc=self._clock(),
                    equity_usdt=equity_usdt,
                    external_cashflow_complete=(
                        verified_cashflow_evidence.get("complete") is True
                        and verified_cashflow_evidence.get("account_identity_hash")
                        == account_identity_hash
                        and verified_cashflow_evidence.get("snapshot_sha256")
                        == snapshot_hash
                    ),
                    external_cashflow_usdt=verified_cashflow_evidence.get(
                        "amount_usdt"
                    ),
                )
            else:
                account_drawdown_fact = build_unknown_account_drawdown_fact(
                    account_identity_hash=account_identity_hash,
                    account_scope="dedicated_demo_account",
                    currency="USDT",
                    snapshot_sha256=snapshot_hash,
                    observed_at_utc=captured_at_utc,
                    equity_usdt=equity_usdt,
                    blockers=(
                        "explicit_baseline_required",
                        "external_cashflow_unknown",
                    ),
                )
            order_ledger = {
                "record_type": (
                    "terminal_order_followup"
                    if order_record
                    else "exchange_order_snapshot"
                ),
                "terminal_order": dict(order_record or {}),
                "orders": orders,
                "pending_orders": pending,
                "pending_algo_orders": pending_algos,
            }
            position_ledger = {
                "positions": positions,
                "signed_contracts": _text(_signed_position(positions)),
                "reconciliation_match": reconciliation_match,
            }
            cash_ledger = {
                **dict(balance),
                "reconciliation_match": reconciliation_match,
            }
            funding_ledger = {
                "bills": funding_rows,
                "observation_count": len(funding_rows),
                "cashflow": _text(funding_cashflow),
                "cashflow_reconciled": True,
                "fixture": False,
            }
            account_ledger_replay: dict[str, Any] = {
                "status": "unknown",
                "reconciled": False,
                "blockers": ["explicit_baseline_required"],
            }
            if previous_drawdown_fact.get("risk_eligible") is True:
                try:
                    recovered_ledger = self._runtime_store.recover()
                    if recovered_ledger.blockers:
                        raise AccountRiskFactError(
                            "runtime_event_recovery_blocked:"
                            + ",".join(recovered_ledger.blockers)
                        )
                    baseline_sequence = int(
                        previous_drawdown_fact.get("baseline_event_sequence")
                        or 0
                    )
                    candidate_uow = {
                        "order_ledger": order_ledger,
                        "fill_ledger": fills,
                        "position_ledger": position_ledger,
                        "cash_ledger": cash_ledger,
                        "funding_ledger": funding_ledger,
                        "risk_context": risk_context,
                    }
                    account_ledger_replay = self._replay_reconciled_ledger(
                        recovery=recovered_ledger,
                        baseline_sequence=baseline_sequence,
                        account_identity=account_identity_hash,
                        candidate_uow=candidate_uow,
                        baseline_equity_usdt=previous_drawdown_fact.get(
                            "baseline_equity_usdt"
                        ),
                        baseline_observed_at_utc=previous_drawdown_fact.get(
                            "coverage_start_utc"
                        ),
                        final_observed_at_utc=captured_at_utc,
                        final_exchange_snapshot=snapshot,
                        currency="USDT",
                    )
                    account_ledger_replay["status"] = "reconciled"
                    account_ledger_replay["blockers"] = []
                except (AccountRiskFactError, TypeError, ValueError) as exc:
                    replay_blocker = "account_ledger_replay_failed:" + str(exc)
                    account_ledger_replay = {
                        "status": "mismatch",
                        "reconciled": False,
                        "blockers": [replay_blocker],
                    }
                    account_drawdown_fact = build_unknown_account_drawdown_fact(
                        account_identity_hash=account_identity_hash,
                        account_scope="dedicated_demo_account",
                        currency="USDT",
                        snapshot_sha256=snapshot_hash,
                        observed_at_utc=captured_at_utc,
                        equity_usdt=equity_usdt,
                        blockers=(replay_blocker,),
                    )
                    reconciliation_match = False
            position_ledger["reconciliation_match"] = reconciliation_match
            cash_ledger["reconciliation_match"] = reconciliation_match
            ledger_reconciliation = {
                "status": (
                    "reconciled" if reconciliation_match else "mismatch"
                ),
                "trigger": trigger,
                "current_state_exchange_snapshot_match": reconciliation_match,
                "exchange_snapshot_sha256": snapshot_hash,
                "order_count": len(orders),
                "pending_order_count": len(pending),
                "pending_algo_order_count": len(pending_algos),
                "fill_count": len(fills),
                "position_count": len(positions),
                "funding_bill_count": len(funding_rows),
                "funding_cashflow": _text(funding_cashflow),
                "funding_cashflow_reconciled": True,
                "last_funding_ledger_hash": funding_hash,
                "account_drawdown_fact": account_drawdown_fact,
                "account_ledger_replay": account_ledger_replay,
                "fixture": False,
                "promotion_evidence_ready": False,
            }
            if not reconciliation_match:
                self._enter_cancel_only(
                    (
                        "okx_demo_account_ledger_replay_mismatch"
                        if account_ledger_replay.get("status") == "mismatch"
                        else "okx_demo_ledger_current_state_exchange_snapshot_mismatch"
                    ),
                    active=self._state["runtime"]["active"],
                )
            state_after = self._durable_state_snapshot()
            state_after["ledger_reconciliation"] = json.loads(
                json.dumps(ledger_reconciliation)
            )
            state_after["account_risk_facts"] = json.loads(
                json.dumps(account_drawdown_fact)
            )
            if account_drawdown_fact.get("risk_eligible") is True:
                state_after["account_risk_last_valid_fact"] = json.loads(
                    json.dumps(account_drawdown_fact)
                )
            safety = dict(self._state["safety"])
            run_id = str(self._state["runtime"].get("run_id") or "")
        risk_context["reconciliation_match"] = reconciliation_match
        risk_context["account_ledger_replay"] = account_ledger_replay
        parsed_capture = _parse_utc(captured_at_utc)
        capture_identity = (
            _iso(parsed_capture) if parsed_capture is not None else captured_at_utc
        )
        observation_identity = hashlib.sha256(
            f"{snapshot_hash}|{capture_identity}".encode("utf-8")
        ).hexdigest()
        event = self._runtime_store.commit_ledger_uow(
            idempotency_key=(
                f"ledger:{run_id}:{snapshot_hash}:{observation_identity}"
            ),
            timestamp_utc=_iso(self._clock()),
            run_id=run_id,
            order=order_ledger,
            fills=fills,
            position=position_ledger,
            cash=cash_ledger,
            funding=funding_ledger,
            risk_context=risk_context,
            account_drawdown_fact=account_drawdown_fact,
            state_after=state_after,
            safety=safety,
        )
        with self._lock:
            self._state["ledger_reconciliation"] = ledger_reconciliation
            self._state["account_risk_facts"] = account_drawdown_fact
            if account_drawdown_fact.get("risk_eligible") is True:
                self._state["account_risk_last_valid_fact"] = account_drawdown_fact
            self._state["events"] = [event, *self._state["events"]][:100]
            self._persist_state()

    def _cancel_owned_pending(self, client: OkxDemoClient | None) -> tuple[list[str], list[str]]:
        cancelled: list[str] = []
        blockers: list[str] = []
        if client is None:
            return cancelled, blockers
        try:
            snapshot = self._collect_exchange_snapshot(client)
            pending = _require(
                client.private_get(
                    "/api/v5/trade/orders-pending",
                    {"instType": "SWAP", "instId": OKX_DEMO_INSTRUMENT_ID},
                ),
                "cancel_owned_pending",
                require_data=False,
            )
            for row in pending.data:
                client_order_id = str(row.get("clOrdId") or "")
                order_id = str(row.get("ordId") or "")
                if client_order_id not in self._owned_client_order_ids:
                    if order_id:
                        blockers.append(f"unknown_open_order_not_cancelled:{order_id}")
                    continue
                response = self._dispatch_control_action(
                    action=RuntimeAction.CANCEL_ORDER,
                    client=client,
                    snapshot=snapshot,
                    control_key=f"{order_id}:{client_order_id}",
                    callback=lambda _intent, order_id=order_id, client_order_id=client_order_id: (
                        client.cancel_order(
                            order_id=order_id,
                            client_order_id=client_order_id,
                        )
                    ),
                )
                if not isinstance(response, OkxDemoResponse):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_execution_boundary_cancel_receipt_invalid"
                    )
                if response.action_ok:
                    cancelled.append(order_id or client_order_id)
                else:
                    blockers.append(f"owned_order_cancel_failed:{order_id or client_order_id}")
        except Exception as exc:
            blockers.append(_safe_error(exc))
        return cancelled, blockers

    def _owned_algo_pairs(self) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        risk = _mapping(self._state.get("risk_control"))
        pending_intents = _mapping(risk.get("pending_order_intents"))
        for algo_client_id, record in _mapping(
            risk.get("owned_attached_algos")
        ).items():
            if not isinstance(record, Mapping):
                continue
            pair = (
                str(record.get("algo_id") or ""),
                str(record.get("algo_client_order_id") or algo_client_id),
            )
            parent_client_order_id = str(
                record.get("parent_client_order_id") or ""
            )
            if (
                all(pair)
                and record.get("opening_intent") is True
                and str(record.get("instrument_id") or "")
                == OKX_DEMO_INSTRUMENT_ID
                and parent_client_order_id in pending_intents
            ):
                pairs.add(pair)
        return pairs

    def _cleanup_owned_flat_algos(
        self,
        client: Any,
        *,
        snapshot: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Cancel only ticket-owned orphan protection after strict flat proof."""

        if _gross_position_contracts(snapshot.get("positions", [])) != 0:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_nonflat_protection_cancel_forbidden"
            )
        pending = [
            dict(row)
            for row in snapshot.get("pending_algo_orders", [])
            if isinstance(row, Mapping)
        ]
        if not pending:
            # A partial entry may have been flattened by a reduce-only order
            # whose exchange-hosted protection was already terminal.  Keep
            # the durable projection truthful even when there is no pending
            # OCO row left to cancel; never clear this projection while the
            # exchange still reports a position.
            with self._lock:
                self._state["risk_control"]["active_protection"] = {}
                self._persist_state()
            return dict(snapshot), {
                "attempted": False,
                "cancelled_algo_ids": [],
                "pending_readback_empty": True,
                "history_terminal_verified": True,
            }
        owned_pairs = self._owned_algo_pairs()
        # A parentless OCO from the fixed current-main incident has no
        # exchange parent and may have no durable owner-map row.  It is
        # cancelable here only after the pre-POST projection was persisted and
        # its proof digest still verifies against the exact fixed identity.
        fixed_projection_pairs: set[tuple[str, str]] = set()
        fresh_marker = _mapping(
            _mapping(self._state.get("runtime")).get(
                "fresh_state_emergency_exit"
            )
        )
        projection = _mapping(fresh_marker.get("projection"))
        fresh_projection_present = bool(projection)
        proof = _mapping(projection.get("oco_ownership_proof"))
        proof_digest = str(proof.get("identity_digest_sha256") or "")
        proof_without_digest = dict(proof)
        proof_without_digest.pop("identity_digest_sha256", None)
        projection_pair = self._fresh_state_emergency_verified_projection_pair(proof)
        if (
            projection_pair is not None
            and str(projection.get("oco_ownership_digest_sha256") or "")
            == proof_digest
        ):
            fixed_projection_pairs.add(projection_pair)
        if (
            str(proof.get("binding_source") or "")
            == "current_main_fixed_incident_identity_projection"
            and str(projection.get("oco_ownership_digest_sha256") or "")
            == proof_digest
            and proof_digest
            and _canonical_sha256(proof_without_digest) == proof_digest
            and str(proof.get("oco", {}).get("algo_id") or "")
            == str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_id"])
            and str(proof.get("oco", {}).get("algo_client_order_id") or "")
            == str(
                _FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_cl_ord_id"]
            )
        ):
            fixed_projection_pairs.add(
                (
                    str(_FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_id"]),
                    str(
                        _FRESH_STATE_EMERGENCY_FIXED_IDENTITY[
                            "oco_algo_cl_ord_id"
                        ]
                    ),
                )
            )
        requested: list[dict[str, str]] = []
        for row in pending:
            pair = (
                str(row.get("algo_id") or ""),
                str(row.get("algo_client_order_id") or ""),
            )
            if not all(pair) or (
                pair not in fixed_projection_pairs
                if fresh_projection_present
                else pair not in owned_pairs
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_unknown_algo_not_cancelled"
                )
            if str(row.get("instrument_id") or "") != OKX_DEMO_INSTRUMENT_ID:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_fault_drill_algo_instrument_mismatch"
                )
            requested.append(
                {"algoId": pair[0], "instId": OKX_DEMO_INSTRUMENT_ID}
            )
        response = self._dispatch_control_action(
            action=RuntimeAction.CANCEL_ORDER,
            client=client,
            snapshot=snapshot,
            control_key=",".join(sorted(row["algoId"] for row in requested)),
            callback=lambda _intent: client.cancel_algo_orders(requested),
        )
        if not isinstance(response, OkxDemoResponse):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_execution_boundary_cancel_receipt_invalid"
            )
        if (
            not response.ok
            or len(response.data) != len(requested)
            or any(
                not isinstance(row, Mapping)
                or str(row.get("sCode") or "") != "0"
                for row in response.data
            )
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_cancel_algos_ack_incomplete"
            )
        acknowledged = {
            str(row.get("algoId") or "")
            for row in response.data
            if isinstance(row, Mapping)
        }
        requested_ids = {row["algoId"] for row in requested}
        if acknowledged != requested_ids:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_cancel_algos_ack_identity_mismatch"
            )
        readback_attempts = 0
        readback_verified = False
        for readback_attempts in range(
            1,
            OKX_DEMO_FAULT_DRILL_ALGO_CANCEL_READBACK_ATTEMPTS + 1,
        ):
            pending_readback = _require(
                client.private_get(
                    "/api/v5/trade/orders-algo-pending",
                    {"instId": OKX_DEMO_INSTRUMENT_ID, "ordType": "oco"},
                ),
                "fault_drill_cancel_algos_pending_readback",
                require_data=False,
            )
            history_by_id: dict[str, str] = {}
            for algo_id in requested_ids:
                history = _require(
                    client.private_get(
                        "/api/v5/trade/orders-algo-history",
                        {
                            "instId": OKX_DEMO_INSTRUMENT_ID,
                            "ordType": "oco",
                            "algoId": algo_id,
                        },
                    ),
                    "fault_drill_cancel_algos_history_readback",
                    require_data=False,
                )
                matching_history = [
                    row
                    for row in history.data
                    if isinstance(row, Mapping)
                    and str(row.get("algoId") or "") == algo_id
                ]
                if len(matching_history) == 1:
                    history_by_id[algo_id] = str(
                        matching_history[0].get("state") or ""
                    )
            if not pending_readback.data and all(
                history_by_id.get(algo_id) in {"canceled", "cancelled"}
                for algo_id in requested_ids
            ):
                readback_verified = True
                break
            if (
                readback_attempts
                < OKX_DEMO_FAULT_DRILL_ALGO_CANCEL_READBACK_ATTEMPTS
            ):
                time.sleep(
                    OKX_DEMO_FAULT_DRILL_ALGO_CANCEL_READBACK_DELAY_SECONDS
                )
        if not readback_verified:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_cancel_algos_readback_timeout_unknown"
            )
        refreshed = self._collect_exchange_snapshot(client)
        if refreshed.get("pending_algo_orders"):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_cancel_algos_final_snapshot_not_empty"
            )
        with self._lock:
            self._state["risk_control"]["active_protection"] = {}
            owned = self._state["risk_control"].get(
                "owned_attached_algos",
                {},
            )
            if isinstance(owned, dict):
                for record in owned.values():
                    if (
                        isinstance(record, dict)
                        and str(record.get("algo_id") or "")
                        in requested_ids
                    ):
                        record["status"] = "cancelled_terminal"
            self._append_event(
                "fault_drill_owned_flat_algos_cancelled",
                {
                    "algo_ids": sorted(requested_ids),
                    "strict_flat_before_cancel": True,
                    "unknown_algo_cancelled": False,
                    "pending_readback_empty": True,
                    "history_terminal_verified": True,
                    "query_only_readback_attempts": readback_attempts,
                },
            )
            self._persist_state()
        return refreshed, {
            "attempted": True,
            "cancelled_algo_ids": sorted(requested_ids),
            "pending_readback_empty": True,
            "history_terminal_verified": True,
            "query_only_readback_attempts": readback_attempts,
        }

    def _fault_drill_postflight_blockers(
        self,
        snapshot: Mapping[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        if _gross_position_contracts(snapshot.get("positions", [])) != 0:
            blockers.append("okx_demo_fault_drill_postflight_position_not_flat")
        if snapshot.get("pending_orders"):
            blockers.append("okx_demo_fault_drill_postflight_pending_orders")
        if snapshot.get("pending_algo_orders"):
            blockers.append("okx_demo_fault_drill_postflight_pending_algos")
        intents = _mapping(
            self._state.get("risk_control", {}).get("pending_order_intents")
        )
        if any(
            not isinstance(row, Mapping)
            or str(row.get("status") or "")
            not in OKX_DEMO_TERMINAL_INTENT_STATUSES
            for row in intents.values()
        ):
            blockers.append("okx_demo_fault_drill_postflight_intent_not_terminal")
        if _mapping(
            self._state.get("risk_control", {}).get("active_protection")
        ):
            blockers.append(
                "okx_demo_fault_drill_postflight_active_protection_present"
            )
        ledger = _mapping(self._state.get("ledger_reconciliation"))
        if not (
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
        ):
            blockers.append("okx_demo_fault_drill_postflight_ledger_not_current")
        return _dedupe(blockers)

    def _fault_drill_terminal_projection(
        self,
        snapshot: Mapping[str, Any],
        *,
        opening_cl_ord_id: str,
        close_cl_ord_id: str,
        algo_cl_ord_id: str,
    ) -> dict[str, Any]:
        """Project only one durable entry/exit/OCO identity from final truth."""

        risk = _mapping(self._state.get("risk_control"))
        intents = _mapping(risk.get("pending_order_intents"))
        owned_algos = _mapping(risk.get("owned_attached_algos"))
        orders = [
            row for row in snapshot.get("orders", []) if isinstance(row, Mapping)
        ]
        fills = [
            row for row in snapshot.get("fills", []) if isinstance(row, Mapping)
        ]
        entry_intent = _mapping(intents.get(opening_cl_ord_id))
        close_intent = _mapping(intents.get(close_cl_ord_id))
        entry_orders = [
            row
            for row in orders
            if row.get("client_order_id") == opening_cl_ord_id
            and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and row.get("side") == "buy"
            and row.get("position_side") == "long"
            and row.get("state") == "filled"
            and _decimal(row.get("size")) > 0
        ]
        close_orders = [
            row
            for row in orders
            if row.get("client_order_id") == close_cl_ord_id
            and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and row.get("side") == "sell"
            and row.get("position_side") == "long"
            and row.get("state") == "filled"
            and _decimal(row.get("size")) > 0
        ]
        entry_fills = [
            row
            for row in fills
            if len(entry_orders) == 1
            and row.get("order_id") == entry_orders[0].get("order_id")
            and row.get("client_order_id") == opening_cl_ord_id
            and _decimal(row.get("size")) > 0
            and str(row.get("fill_id") or "")
        ]
        close_fills = [
            row
            for row in fills
            if len(close_orders) == 1
            and row.get("order_id") == close_orders[0].get("order_id")
            and row.get("client_order_id") == close_cl_ord_id
            and _decimal(row.get("size")) > 0
            and str(row.get("fill_id") or "")
        ]
        entry_proven = (
            len(entry_orders) == 1
            and len(entry_fills) == 1
            and entry_intent.get("risk_reducing_only") is False
        )
        close_proven = (
            len(close_orders) == 1
            and len(close_fills) == 1
            and close_intent.get("risk_reducing_only") is True
        )
        owned = _mapping(owned_algos.get(algo_cl_ord_id))
        algo_proven = bool(
            owned.get("algo_client_order_id") == algo_cl_ord_id
            and owned.get("parent_client_order_id") == opening_cl_ord_id
            and str(owned.get("algo_id") or "")
        )
        ledger = _mapping(self._state.get("ledger_reconciliation"))
        ledger_reconciled = (
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
        )
        terminal_intents = all(
            isinstance(intent, Mapping)
            and str(intent.get("status") or "")
            in OKX_DEMO_TERMINAL_INTENT_STATUSES
            for intent in intents.values()
        )
        private_ws = _mapping(self._state.get("private_ws"))
        private_ws_reconciled = (
            private_ws.get("opening_allowed_after_reconciliation") is True
            and private_ws.get("connected") is True
            and private_ws.get("listener_alive") is True
        )
        return {
            "final_flat": _gross_position_contracts(snapshot.get("positions", []))
            == 0,
            "final_no_pending_orders": not snapshot.get("pending_orders"),
            "final_no_pending_algo_orders": not snapshot.get("pending_algo_orders"),
            "final_no_unresolved_intents": terminal_intents,
            "final_ledger_reconciled": ledger_reconciled,
            "final_private_ws_reconciled": private_ws_reconciled,
            "ledger_reconciled": ledger_reconciled,
            "private_ws_reconciled": private_ws_reconciled,
            "entry_order_id": str(entry_orders[0].get("order_id") or "")
            if entry_proven
            else "",
            "entry_order_client_order_id": opening_cl_ord_id if entry_proven else "",
            "entry_fill_ids": [str(entry_fills[0].get("fill_id") or "")]
            if entry_proven
            else [],
            "entry_fill_order_ids": [str(entry_orders[0].get("order_id") or "")]
            if entry_proven
            else [],
            "entry_fill_client_order_ids": [opening_cl_ord_id]
            if entry_proven
            else [],
            "entry_order_type": str(entry_orders[0].get("order_type") or "")
            if entry_proven
            else "",
            "entry_fill_contracts": str(entry_fills[0].get("size") or "")
            if entry_proven
            else "",
            "entry_order_filled_contracts": str(entry_orders[0].get("size") or "")
            if entry_proven
            else "",
            "entry_fill_sum_contracts": str(entry_fills[0].get("size") or "")
            if entry_proven
            else "",
            "entry_position_contracts": str(entry_fills[0].get("size") or "")
            if entry_proven
            else "",
            "close_order_id": str(close_orders[0].get("order_id") or "")
            if close_proven
            else "",
            "close_order_client_order_id": close_cl_ord_id if close_proven else "",
            "close_fill_ids": [str(close_fills[0].get("fill_id") or "")]
            if close_proven
            else [],
            "close_fill_order_ids": [str(close_orders[0].get("order_id") or "")]
            if close_proven
            else [],
            "close_fill_client_order_ids": [close_cl_ord_id]
            if close_proven
            else [],
            "close_fill_contracts": str(close_fills[0].get("size") or "")
            if close_proven
            else "",
            "close_order_filled_contracts": str(close_orders[0].get("size") or "")
            if close_proven
            else "",
            "requested_contracts": str(entry_orders[0].get("size") or "")
            if entry_proven
            else "",
            "algo_id": str(owned.get("algo_id") or "") if algo_proven else "",
            "algo_parent_cl_ord_id": opening_cl_ord_id if algo_proven else "",
        }

    def verify_fault_drill_worker_ready(
        self,
        marker: Mapping[str, Any],
        *,
        expected_nonce: str,
        expected_process_id: int,
        expected_process_create_time: str,
    ) -> dict[str, Any]:
        """Independently re-read exchange and durable facts before parent kill."""

        normalized = dict(marker)
        marker_hash = str(normalized.pop("marker_sha256", "") or "")
        expected_head = _repo_head(self.config.repo_root)
        expected_root_hash = _canonical_sha256(
            str(Path(self.config.output_dir).resolve())
        )
        if (
            marker_hash != _canonical_sha256(normalized)
            or marker.get("worker_nonce") != expected_nonce
            or marker.get("process_id") != expected_process_id
            or str(marker.get("process_create_time") or "")
            != expected_process_create_time
            or marker.get("source_head") != expected_head
            or marker.get("runtime_root_sha256") != expected_root_hash
            or marker.get("position_observed") is not True
            or marker.get("protection_verified") is not True
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_marker_identity_mismatch"
            )
        recovered = self._runtime_store.recover()
        recovered_state = json.loads(json.dumps(recovered.state))
        recovered_runtime = _mapping(recovered_state.get("runtime"))
        recovered_marker = _mapping(
            recovered_runtime.get("fault_drill_worker_ready")
        )
        if recovered_marker != marker:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_marker_not_durable"
            )
        runtime_without_marker = dict(recovered_runtime)
        runtime_without_marker.pop("fault_drill_worker_ready", None)
        recovered_state["runtime"] = runtime_without_marker
        if _canonical_sha256(recovered_state) != str(
            marker.get("runtime_state_sha256") or ""
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_runtime_hash_mismatch"
            )
        events = list(recovered.events)
        if not events or str(events[-1].get("event_type") or "") != (
            "fault_drill_worker_ready"
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_event_missing"
            )
        previous_event_hash = (
            str(self._status_event_projection(events[-2]).get("event_id") or "")
            if len(events) >= 2
            else ""
        )
        if previous_event_hash != str(marker.get("previous_event_hash") or ""):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_event_hash_mismatch"
            )

        client = self._read_only_client()
        snapshot = self._collect_exchange_snapshot(client)
        reconciliation_hash = _canonical_sha256(
            _fault_reconciliation_facts(snapshot)
        )
        ledger_hash = _fault_ledger_snapshot_sha256(snapshot)
        cl_ord_id = str(marker.get("clOrdId") or "")
        algo_client_id = str(marker.get("algoClOrdId") or "")
        algo_id = str(marker.get("algoId") or "")
        order_found = any(
            str(row.get("client_order_id") or "") == cl_ord_id
            for row in snapshot.get("orders", [])
            if isinstance(row, Mapping)
        )
        fill_found = any(
            str(row.get("client_order_id") or "") == cl_ord_id
            for row in snapshot.get("fills", [])
            if isinstance(row, Mapping)
        )
        protection_found = any(
            str(row.get("algo_id") or "") == algo_id
            and str(row.get("algo_client_order_id") or "") == algo_client_id
            for row in snapshot.get("pending_algo_orders", [])
            if isinstance(row, Mapping)
        )
        if not (
            reconciliation_hash
            == str(marker.get("held_reconciliation_sha256") or "")
            and ledger_hash == str(marker.get("ledger_snapshot_sha256") or "")
            and ledger_hash
            == str(marker.get("committed_ledger_snapshot_sha256") or "")
            and order_found
            and fill_found
            and protection_found
            and _gross_position_contracts(snapshot.get("positions", []))
            == OKX_DEMO_PAPER_CONTRACTS
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_parent_readback_mismatch"
            )
        return {
            "verified": True,
            "source_head": expected_head,
            "runtime_root_sha256": expected_root_hash,
            "reconciliation_sha256": reconciliation_hash,
            "ledger_snapshot_sha256": ledger_hash,
            "order_found": True,
            "fill_found": True,
            "position_found": True,
            "protection_found": True,
            "methods": ["GET"],
        }

    @_runtime_writer_session()
    def recover_fault_drill_incident(
        self,
        *,
        authorization: Mapping[str, Any],
    ) -> dict[str, Any]:
        """One-shot recovery for one immutable failed drill receipt only."""

        try:
            if str(authorization.get("recovery_mode") or "") == "already_flat":
                return self._recover_fault_drill_incident_already_flat_with_writer_lock(
                    authorization=authorization,
                )
            return self._recover_fault_drill_incident_with_writer_lock(
                authorization=authorization,
            )
        except BaseException:
            canonical = self._is_canonical_incident_recovery_authorization(
                authorization
            )
            if not canonical or self._fault_drill_recovery_admission_passed:
                self._cleanup_failed_incident_recovery()
            raise

    @_runtime_writer_operation
    def finalize_incident_recovery_local(self) -> dict[str, Any]:
        """Terminate a completed incident session without any exchange POST."""

        with self._lock:
            private_ws = self._private_ws
            self._private_ws = None
            self._client = None
        stop_error = ""
        if private_ws is not None:
            try:
                stop_receipt = private_ws.stop()
                if not (
                    isinstance(stop_receipt, Mapping)
                    and stop_receipt.get("listener_joined") is True
                ):
                    stop_error = "private_ws_listener_join_not_proven"
            except Exception as exc:
                stop_error = _safe_error(exc)
        with self._lock:
            dead_man = self._state["risk_control"]["dead_man"]
            exchange = _mapping(self._state.get("exchange"))
            ledger = _mapping(self._state.get("ledger_reconciliation"))
            private_ws_state = _mapping(self._state.get("private_ws"))
            final_snapshot_sha256 = _fault_ledger_snapshot_sha256(exchange)
            last_ack = _parse_utc(dead_man.get("last_ack_utc"))
            timeout_seconds = int(dead_man.get("timeout_seconds") or 0)
            try:
                observed_server_time = datetime.fromtimestamp(
                    int(exchange.get("server_time_ms") or 0) / 1000,
                    tz=timezone.utc,
                )
            except (TypeError, ValueError, OSError):
                observed_server_time = None
            expiry_time = (
                last_ack + timedelta(seconds=timeout_seconds)
                if last_ack is not None and timeout_seconds > 0
                else None
            )
            readonly_terminal = (
                _gross_position_contracts(exchange.get("positions", [])) == 0
                and not exchange.get("pending_orders")
                and not exchange.get("pending_algo_orders")
                and ledger.get("status") == "reconciled"
                and ledger.get("current_state_exchange_snapshot_match") is True
                and ledger.get("exchange_snapshot_sha256")
                == final_snapshot_sha256
                and private_ws_state.get("incident_final_snapshot_sha256")
                == final_snapshot_sha256
            )
            timeout_expired = bool(
                observed_server_time is not None
                and expiry_time is not None
                and observed_server_time >= expiry_time
            )
            dead_man_terminal = dead_man.get("armed") is not True
            if dead_man.get("armed") is True and readonly_terminal and timeout_expired:
                dead_man.update(
                    {
                        "armed": False,
                        "prior_armed_state": True,
                        "mode": "expired_timeout_readonly_evidence",
                        "disarm_mode": "expired_timeout_readonly_evidence",
                        "disarm_post_sent": False,
                        "caa_post_count": 0,
                        "readonly_terminal_snapshot_evidence": True,
                        "last_ack_utc": _iso(last_ack),
                        "timeout_seconds": timeout_seconds,
                        "expiry_utc": _iso(expiry_time),
                        "observed_server_time_utc": _iso(observed_server_time),
                        "elapsed_after_expiry_seconds": str(
                            int((observed_server_time - expiry_time).total_seconds())
                        ),
                        "final_flat": True,
                        "final_pending_order_count": 0,
                        "final_pending_algo_order_count": 0,
                        "exchange_snapshot_sha256": final_snapshot_sha256,
                        "ledger_snapshot_sha256": str(
                            ledger.get("exchange_snapshot_sha256") or ""
                        ),
                        "private_ws_snapshot_sha256": str(
                            private_ws_state.get(
                                "incident_final_snapshot_sha256"
                            )
                            or ""
                        ),
                        "proof_method": (
                            "exchange_server_time_plus_final_rest_ws_ledger_fingerprint"
                        ),
                    }
                )
                dead_man_terminal = True
            cleanup_complete = not stop_error and dead_man_terminal
            self._state["runtime"].update(
                {
                    "active": False,
                    "opening_allowed": False,
                    "cancel_only": True,
                    "status": (
                        "incident_recovery_local_cleanup_complete"
                        if cleanup_complete
                        else "incident_recovery_local_cleanup_unproven"
                    ),
                }
            )
            self._state["risk_control"]["write_path_trusted"] = False
            self._state["private_ws"].update(
                {
                    "connected": False,
                    "listener_alive": False,
                    "opening_allowed_after_reconciliation": False,
                    "cleanup_complete": cleanup_complete,
                    "cleanup_error": (
                        stop_error
                        or (
                            "dead_man_expiry_not_readonly_proven"
                            if not dead_man_terminal
                            else ""
                        )
                    ),
                }
            )
            self._state["safety"]["okx_demo_private_read_enabled"] = False
            self._state["safety"]["okx_demo_order_capability_enabled"] = False
            self._state["safety"]["okx_demo_cancel_capability_enabled"] = False
            flat_verified = _mapping(
                self._state["risk_control"].get(
                    "incident_recovery_flat_verified"
                )
            )
            if cleanup_complete and flat_verified.get("receipt_sha256"):
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_FROZEN,
                    "incident_recovery_already_flat_safe_stopped",
                )
                self._state["runtime"]["status"] = (
                    "incident_recovery_flat_verified"
                )
                self._state["runtime"]["active"] = False
                self._state["runtime"]["opening_allowed"] = False
                self._state["runtime"]["cancel_only"] = True
            else:
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_FROZEN,
                    "incident_recovery_completed_requires_review",
                )
            self._persist_state()
        if not cleanup_complete:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_local_cleanup_unproven:"
                + str(
                    self._state["private_ws"].get("cleanup_error") or "unknown"
                )
            )
        return self.status()

    def _cleanup_failed_incident_recovery(self) -> None:
        """Stop local resources without issuing any exchange POST."""

        with self._lock:
            private_ws = self._private_ws
            self._private_ws = None
            self._client = None
        stop_error = ""
        if private_ws is not None:
            try:
                stop_receipt = private_ws.stop()
                if not (
                    isinstance(stop_receipt, Mapping)
                    and stop_receipt.get("listener_joined") is True
                ):
                    stop_error = "private_ws_listener_join_not_proven"
            except Exception as exc:
                stop_error = _safe_error(exc)
        with self._lock:
            self._state["runtime"].update(
                {
                    "active": False,
                    "opening_allowed": False,
                    "cancel_only": True,
                    "status": "incident_recovery_blocked_fail_closed",
                }
            )
            self._state["risk_control"]["write_path_trusted"] = False
            self._state["private_ws"].update(
                {
                    "connected": False,
                    "listener_alive": False,
                    "opening_allowed_after_reconciliation": False,
                    "cleanup_complete": not stop_error,
                    "cleanup_error": stop_error,
                }
            )
            if stop_error:
                self._state["runtime"]["blockers"] = _dedupe(
                    [
                        *self._state["runtime"].get("blockers", []),
                        "okx_demo_incident_recovery_private_ws_stop_failed:"
                        + stop_error,
                    ]
                )
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_FROZEN,
                "incident_recovery_failed_no_automatic_post_cleanup",
            )
            self._persist_state()

    def _recover_fault_drill_incident_with_writer_lock(
        self,
        *,
        authorization: Mapping[str, Any],
    ) -> dict[str, Any]:
        auth = {str(key): str(value or "") for key, value in authorization.items()}
        identity_fields = (
            "failed_receipt_sha256",
            "failed_receipt_source_head",
            "failed_receipt_scenario",
            "failed_receipt_run_id",
            "opening_cl_ord_id",
            "opening_order_id",
            "opening_fill_id",
            "algo_cl_ord_id",
            "algo_id",
            "expected_close_cl_ord_id",
        )
        current_head = _repo_head(self.config.repo_root)
        canonical_binding = bool(auth.get("recovery_binding_path"))
        canonical_heads_valid = (
            not canonical_binding
            or (
                not auth.get("incident_source_head")
                and not auth.get("recovery_code_head")
            )
            or (
                auth.get("recovery_code_head") == current_head
                and auth.get("incident_source_head")
                == auth.get("failed_receipt_source_head")
            )
        )
        head_valid = (
            auth.get("runtime_source_head") == current_head
            and canonical_heads_valid
        )
        if (
            auth.get("authorization_ticket")
            != "BTC-OKX-DEMO-INCIDENT-RECOVERY-AND-RECEIPT-05"
            or not head_valid
            or not re.fullmatch(
                r"[0-9a-f]{64}", auth.get("failed_receipt_sha256", "")
            )
            or not re.fullmatch(
                r"[0-9a-f]{40}", auth.get("failed_receipt_source_head", "")
            )
            or any(not auth.get(field) for field in identity_fields)
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_authorization_invalid"
            )
        binding_blockers = self._incident_recovery_binding_blockers(auth)
        if binding_blockers:
            raise OkxDemoPaperRuntimeError(";".join(binding_blockers))
        receipt_sha256 = auth["failed_receipt_sha256"]
        recoveries = self._state["risk_control"].setdefault(
            "incident_recovery_intents", {}
        )
        if receipt_sha256 in recoveries:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_already_consumed"
            )
        durable_blockers = self._incident_recovery_durable_identity_blockers(auth)
        if durable_blockers:
            raise OkxDemoPaperRuntimeError(";".join(durable_blockers))
        self._fault_drill_recovery_admission_passed = True

        # Query-only client and private-WS reconciliation are completed before
        # the controller creates any CAA/order/cancel capability.
        read_client = self._read_only_client()
        snapshot = self._collect_exchange_snapshot(read_client)
        protection_policy = _mapping(
            self._state["risk_control"].get("protection_policy")
        )
        snapshot_blockers = _incident_recovery_snapshot_blockers(
            snapshot,
            auth,
            protection_policy=protection_policy,
            expected_leverage=self.config.max_configured_leverage,
        )
        if snapshot_blockers:
            raise OkxDemoPaperRuntimeError(";".join(snapshot_blockers))
        with self._lock:
            opening_intent = self._state["risk_control"][
                "pending_order_intents"
            ][auth["opening_cl_ord_id"]]
            opening_intent.update(
                {
                    "status": "reconciled_terminal",
                    "exchange_state": "filled",
                    "retry_without_query_allowed": False,
                }
            )
            self._apply_snapshot(snapshot)
            self._persist_state()
        self._commit_ledger_reconciliation(
            snapshot=snapshot,
            trigger="incident_recovery_query_only_preflight",
        )
        self._require_incident_recovery_ledger_current(snapshot)

        credentials = self._credential_loader(self.config.credential_service)
        recovery_owned_client_order_ids = tuple(
            sorted(
                {
                    *self._owned_client_order_ids,
                    auth["opening_cl_ord_id"],
                    auth["expected_close_cl_ord_id"],
                }
            )
        )
        snapshot_fingerprint = _incident_recovery_identity_sha256(
            snapshot,
            owned_client_order_ids=recovery_owned_client_order_ids,
        )
        private_ws_snapshot_fingerprints: list[str] = []

        def private_ws_snapshot_loader() -> Mapping[str, Any]:
            current = self._collect_exchange_snapshot(read_client)
            private_ws_snapshot_fingerprints.append(
                _incident_recovery_identity_sha256(
                    current,
                    owned_client_order_ids=recovery_owned_client_order_ids,
                )
            )
            return current

        private_ws = self._private_ws_factory(
            credentials=credentials,
            source_head=_repo_head(self.config.repo_root),
            runtime_version=OKX_DEMO_PAPER_RUNTIME_VERSION,
            snapshot_loader=private_ws_snapshot_loader,
            owned_client_order_ids=lambda: tuple(
                sorted(self._owned_client_order_ids)
            ),
            on_disconnect=self._on_private_ws_disconnect,
            on_reconciled=self._on_private_ws_reconciled,
            clock=self._clock,
        )
        with self._lock:
            self._private_ws = private_ws
        probe = private_ws.run_startup_reconnect_probe()
        if not (
            isinstance(probe, Mapping)
            and probe.get("opening_allowed_after_reconciliation") is True
        ):
            self._record_incident_recovery_private_ws_probe_failure(probe)
            try:
                private_ws.stop()
            finally:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_startup_reconnect_probe_failed"
                )
        private_ws.start_monitoring()
        current_ws = private_ws.status() if hasattr(private_ws, "status") else {}
        if not (
            isinstance(probe, Mapping)
            and probe.get("opening_allowed_after_reconciliation") is True
            and isinstance(current_ws, Mapping)
            and current_ws.get("connected") is True
            and current_ws.get("listener_alive") is True
            and current_ws.get("opening_allowed_after_reconciliation") is True
        ):
            try:
                private_ws.stop()
            finally:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_incident_recovery_private_ws_not_reconciled"
                )
        verified_snapshot = self._collect_exchange_snapshot(read_client)
        verified_blockers = _incident_recovery_snapshot_blockers(
            verified_snapshot,
            auth,
            protection_policy=protection_policy,
            expected_leverage=self.config.max_configured_leverage,
        )
        if (
            verified_blockers
            or not private_ws_snapshot_fingerprints
            or any(
                fingerprint != snapshot_fingerprint
                for fingerprint in private_ws_snapshot_fingerprints
            )
            or _incident_recovery_identity_sha256(
                verified_snapshot,
                owned_client_order_ids=recovery_owned_client_order_ids,
            )
            != snapshot_fingerprint
        ):
            private_ws.stop()
            raise OkxDemoPaperRuntimeError(
                ";".join(
                    verified_blockers
                    or ["okx_demo_incident_recovery_snapshot_changed"]
                )
            )
        with self._lock:
            self._apply_snapshot(verified_snapshot)
            self._state["private_ws"] = json.loads(
                json.dumps({**dict(probe), **dict(current_ws)})
            )
        self._commit_ledger_reconciliation(
            snapshot=verified_snapshot,
            trigger="incident_recovery_private_ws_verified",
        )
        self._require_incident_recovery_ledger_current(verified_snapshot)

        close_plan = self._build_order_plan(
            verified_snapshot,
            current_quantity=OKX_DEMO_PAPER_CONTRACTS,
            target_quantity=Decimal("0"),
        )
        if not (
            isinstance(close_plan, Mapping)
            and close_plan.get("client_order_id")
            == auth["expected_close_cl_ord_id"]
            and close_plan.get("side") == "sell"
            and close_plan.get("position_side") == "long"
            and close_plan.get("action") == "close_long"
            and close_plan.get("contracts") == "0.01"
            and close_plan.get("risk_reducing_only") is True
        ):
            private_ws.stop()
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_close_identity_mismatch"
            )
        with self._lock:
            recoveries[receipt_sha256] = {
                "status": "intent_persisted",
                "persisted_before_any_post": True,
                "failed_receipt_sha256": receipt_sha256,
                "failed_receipt_source_head": auth["failed_receipt_source_head"],
                "incident_source_head": auth.get("incident_source_head", ""),
                "recovery_code_head": auth.get("recovery_code_head", ""),
                "failed_receipt_scenario": auth["failed_receipt_scenario"],
                "failed_receipt_run_id": auth["failed_receipt_run_id"],
                "opening_cl_ord_id": auth["opening_cl_ord_id"],
                "algo_cl_ord_id": auth["algo_cl_ord_id"],
                "algo_id": auth["algo_id"],
                "close_cl_ord_id": auth["expected_close_cl_ord_id"],
                "recovery_binding_sha256": auth.get("recovery_binding_sha256", ""),
                "runtime_root_sha256": auth.get("recovery_runtime_root_sha256", ""),
                "runtime_state_sha256": auth.get(
                    "recovery_runtime_state_sha256", ""
                ),
                "runtime_events_sha256": auth.get(
                    "recovery_runtime_events_sha256", ""
                ),
                "runtime_run_id": auth.get("recovery_runtime_run_id", ""),
                "account_identity": auth.get("recovery_account_identity", ""),
                "credential_identity": auth.get("recovery_credential_identity", ""),
                "client_order_namespace": auth.get("recovery_client_order_namespace", ""),
                "retry_allowed": False,
                "post_attempted": False,
                "persisted_at_utc": _iso(self._clock()),
            }
            self._append_event(
                "incident_recovery_intent_persisted_before_post",
                dict(recoveries[receipt_sha256]),
            )
            self._persist_state()

        write_client = self._client_factory(
            OkxDemoClientConfig(
                credential_service=self.config.credential_service,
                allow_private_read=True,
                allow_demo_orders=True,
                allow_demo_cancels=True,
                authorization_ticket=OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
                max_order_contracts=OKX_DEMO_PAPER_CONTRACTS,
                max_notional_usdt=OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
                contract_value_btc=OKX_DEMO_PAPER_CONTRACT_VALUE_BTC,
            ),
            credentials,
        )
        with self._lock:
            self._client = write_client
            self._private_ws = private_ws
            self._state["runtime"].update(
                {
                    "active": True,
                    "opening_allowed": False,
                    "cancel_only": True,
                    "status": "incident_recovery_reducing",
                }
            )
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_REDUCING,
                "immutable_failed_receipt_incident_recovery",
            )
            self._persist_state()
        decision = {
            "strategy_id": "btc_okx_demo_incident_risk_reduction",
            "direction": "flat",
            "raw_signal": "0",
            "target_contracts": "0",
            "decision_bar_close_utc": _iso(self._clock()),
            "source": "immutable_failed_receipt_incident_recovery",
            "failed_receipt_sha256": receipt_sha256,
        }
        with self._execution_lock:
            self._submit_order_plan(
                write_client,
                snapshot=verified_snapshot,
                decision=decision,
                order_plan=close_plan,
                incident_recovery_receipt_sha256=receipt_sha256,
            )
        flat_snapshot = self._collect_exchange_snapshot(write_client)
        flat_blockers = _incident_recovery_flat_close_blockers(
            flat_snapshot,
            auth,
        )
        if flat_blockers:
            raise OkxDemoPaperRuntimeError(";".join(flat_blockers))
        with self._lock:
            self._apply_snapshot(flat_snapshot)
        self._commit_ledger_reconciliation(
            snapshot=flat_snapshot,
            trigger="incident_recovery_flat_before_algo_cancel",
        )
        self._require_incident_recovery_ledger_current(flat_snapshot)
        fingerprint_count = len(private_ws_snapshot_fingerprints)
        flat_ws_receipt = private_ws.reconcile_current()
        if not (
            isinstance(flat_ws_receipt, Mapping)
            and flat_ws_receipt.get("connected") is True
            and flat_ws_receipt.get("listener_alive") is True
            and flat_ws_receipt.get("opening_allowed_after_reconciliation") is True
            and len(private_ws_snapshot_fingerprints) == fingerprint_count + 1
            and private_ws_snapshot_fingerprints[-1]
            == _incident_recovery_identity_sha256(
                flat_snapshot,
                owned_client_order_ids=recovery_owned_client_order_ids,
            )
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_flat_private_ws_not_current"
            )
        cancel_receipt = self._cancel_exact_incident_algo_once(
            write_client,
            snapshot=flat_snapshot,
            algo_id=auth["algo_id"],
            algo_client_order_id=auth["algo_cl_ord_id"],
        )
        final_snapshot = self._collect_exchange_snapshot(write_client)
        if (
            _gross_position_contracts(final_snapshot.get("positions", [])) != 0
            or final_snapshot.get("pending_orders")
            or final_snapshot.get("pending_algo_orders")
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_postflight_not_flat_clean"
            )
        with self._lock:
            self._apply_snapshot(final_snapshot)
        self._commit_ledger_reconciliation(
            snapshot=final_snapshot,
            trigger="incident_recovery_postflight",
        )
        self._require_incident_recovery_ledger_current(final_snapshot)
        fingerprint_count = len(private_ws_snapshot_fingerprints)
        final_ws_receipt = private_ws.reconcile_current()
        if not (
            isinstance(final_ws_receipt, Mapping)
            and final_ws_receipt.get("connected") is True
            and final_ws_receipt.get("listener_alive") is True
            and final_ws_receipt.get("opening_allowed_after_reconciliation") is True
            and len(private_ws_snapshot_fingerprints) == fingerprint_count + 1
            and private_ws_snapshot_fingerprints[-1]
            == _incident_recovery_identity_sha256(
                final_snapshot,
                owned_client_order_ids=recovery_owned_client_order_ids,
            )
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_final_private_ws_not_current"
            )
        with self._lock:
            self._state["private_ws"].update(dict(final_ws_receipt))
            self._state["private_ws"]["incident_final_snapshot_sha256"] = (
                _fault_ledger_snapshot_sha256(final_snapshot)
            )
        with self._lock:
            recoveries[receipt_sha256].update(
                {
                    "status": "completed_flat",
                    "completed_at_utc": _iso(self._clock()),
                }
            )
            self._append_event(
                "incident_recovery_completed_flat",
                {
                    **dict(recoveries[receipt_sha256]),
                    "cancel_receipt": cancel_receipt,
                },
            )
            self._persist_state()
        self.freeze_fault_drill("incident_recovery_completed_requires_review")
        return {
            "decision": "incident_recovery_completed_safe_flat",
            "orders_posted": 1,
            "close_post_attempted": True,
            "cancel_post_attempted": True,
            "clOrdId": auth["opening_cl_ord_id"],
            "closeClOrdId": auth["expected_close_cl_ord_id"],
            "algoClOrdId": auth["algo_cl_ord_id"],
            "algoId": auth["algo_id"],
            "failed_receipt_sha256": receipt_sha256,
            "position_observed": True,
            "protection_verified": True,
            "cancel_receipt": cancel_receipt,
            **self._incident_recovery_terminal_projection(
                final_snapshot,
                authorization=auth,
                private_ws_reconciled=True,
            ),
            "simulation_only": False,
        }

    def _recover_fault_drill_incident_already_flat_with_writer_lock(
        self,
        *,
        authorization: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Verify a superseding flat receipt without any exchange write."""

        auth = {
            str(key): str(value or "")
            for key, value in authorization.items()
        }
        identity_fields = (
            "failed_receipt_sha256",
            "failed_receipt_source_head",
            "failed_receipt_scenario",
            "failed_receipt_run_id",
            "opening_cl_ord_id",
            "opening_order_id",
            "opening_fill_id",
            "algo_cl_ord_id",
            "algo_id",
            "expected_close_cl_ord_id",
        )
        current_head = _repo_head(self.config.repo_root)
        canonical_binding = bool(auth.get("recovery_binding_path"))
        flat_hosted_exit_binding = (
            self._is_flat_hosted_exit_binding_authorization(auth)
        )
        canonical_heads_valid = (
            not canonical_binding
            or (
                not auth.get("incident_source_head")
                and not auth.get("recovery_code_head")
            )
            or (
                auth.get("recovery_code_head") == current_head
                and auth.get("incident_source_head")
                == auth.get("failed_receipt_source_head")
            )
        )
        head_valid = (
            auth.get("runtime_source_head") == current_head
            and canonical_heads_valid
        )
        if (
            auth.get("authorization_ticket")
            != "BTC-OKX-DEMO-INCIDENT-RECOVERY-AND-RECEIPT-05"
            or not head_valid
            or auth.get("recovery_mode") != "already_flat"
            or not re.fullmatch(
                r"[0-9a-f]{64}", auth.get("failed_receipt_sha256", "")
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", auth.get("flat_identity_sha256", "")
            )
            or not re.fullmatch(
                r"[0-9a-f]{40}", auth.get("failed_receipt_source_head", "")
            )
            or any(not auth.get(field) for field in identity_fields)
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_flat_authorization_invalid"
            )

        binding_blockers = self._incident_recovery_binding_blockers(auth)
        if binding_blockers:
            raise OkxDemoPaperRuntimeError(";".join(binding_blockers))

        receipt_sha256 = auth["failed_receipt_sha256"]
        recoveries = self._state["risk_control"].setdefault(
            "incident_recovery_intents", {}
        )
        if receipt_sha256 in recoveries:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_already_consumed"
            )
        # The receipt bundle is the deliberately narrow alternative to the
        # mixed/obsolete runtime-root chain.  It still must pass the binding
        # verifier above and all fresh broker/WS/ledger checks below; it simply
        # cannot require the overwritten historical local ownership maps.
        if not flat_hosted_exit_binding:
            durable_blockers = self._incident_recovery_flat_durable_identity_blockers(
                auth
            )
            if durable_blockers:
                raise OkxDemoPaperRuntimeError(";".join(durable_blockers))
        self._fault_drill_recovery_admission_passed = True

        hosted_exit_candidate = auth["expected_close_cl_ord_id"].startswith("O")
        if hosted_exit_candidate and (
            not canonical_binding
            or self._state["risk_control"].get("mode")
            != OKX_DEMO_RISK_MODE_FROZEN
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_hosted_oco_exit_binding_not_admitted"
            )
        read_client = self._read_only_client()
        snapshot = self._collect_exchange_snapshot(read_client)
        hosted_exit_projection: Mapping[str, Any] | None = None
        if hosted_exit_candidate:
            hosted_exit_projection, hosted_exit_blockers = (
                _hosted_oco_terminal_exit_projection(
                    snapshot,
                    authorization=auth,
                    current_head=current_head,
                )
            )
            if hosted_exit_blockers or hosted_exit_projection is None:
                raise OkxDemoPaperRuntimeError(
                    ";".join(hosted_exit_blockers)
                    or "okx_demo_hosted_oco_exit_projection_invalid"
                )
        snapshot_blockers = self._incident_recovery_flat_snapshot_blockers(
            snapshot,
            auth,
            hosted_exit_projection=hosted_exit_projection,
            require_authorization_fingerprint=not flat_hosted_exit_binding,
        )
        if snapshot_blockers:
            raise OkxDemoPaperRuntimeError(";".join(snapshot_blockers))
        with self._lock:
            self._apply_snapshot(snapshot)
            self._persist_state()
        self._commit_ledger_reconciliation(
            snapshot=snapshot,
            trigger="incident_recovery_flat_query_only_preflight",
        )
        self._require_incident_recovery_ledger_current(snapshot)

        credentials = self._credential_loader(self.config.credential_service)
        owned_client_order_ids = (
            auth["opening_cl_ord_id"],
            auth["expected_close_cl_ord_id"],
        )
        snapshot_fingerprint = _incident_recovery_flat_identity_sha256(
            snapshot,
            owned_client_order_ids=owned_client_order_ids,
        )
        expected_snapshot_fingerprint = (
            snapshot_fingerprint
            if flat_hosted_exit_binding
            else auth["flat_identity_sha256"]
        )
        if snapshot_fingerprint != expected_snapshot_fingerprint:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_flat_snapshot_changed"
            )
        if hosted_exit_projection is not None:
            # A flat-hosted-exit bundle is the sole alternative to the
            # historical lifecycle root.  Its projection already verified the
            # exact entry <-> OCO <-> terminal exit tuple from immutable
            # evidence and fresh broker truth.  The websocket reconciler sees
            # fills, so it must receive both ends of that verified tuple;
            # restoring only the O-prefixed exit makes the entry fill look
            # foreign and incorrectly freezes before reconciliation.
            if flat_hosted_exit_binding:
                entry_identity = _mapping(hosted_exit_projection.get("entry"))
                exit_identity = _mapping(hosted_exit_projection.get("exit"))
                entry_client_order_id = str(
                    entry_identity.get("client_order_id") or ""
                )
                exit_client_order_id = str(
                    exit_identity.get("client_order_id") or ""
                )
                if (
                    entry_client_order_id != auth["opening_cl_ord_id"]
                    or exit_client_order_id
                    != auth["expected_close_cl_ord_id"]
                ):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_hosted_oco_exit_projection_identity_mismatch"
                    )
                with self._lock:
                    self._owned_client_order_ids.update(
                        (entry_client_order_id, exit_client_order_id)
                    )
            self._persist_hosted_oco_terminal_exit_projection(
                hosted_exit_projection
            )
        private_ws_snapshot_fingerprints: list[str] = []

        def private_ws_snapshot_loader() -> Mapping[str, Any]:
            current = self._collect_exchange_snapshot(read_client)
            private_ws_snapshot_fingerprints.append(
                _incident_recovery_flat_identity_sha256(
                current,
                owned_client_order_ids=owned_client_order_ids,
                )
            )
            return current

        private_ws = self._private_ws_factory(
            credentials=credentials,
            source_head=_repo_head(self.config.repo_root),
            runtime_version=OKX_DEMO_PAPER_RUNTIME_VERSION,
            snapshot_loader=private_ws_snapshot_loader,
            owned_client_order_ids=lambda: tuple(
                sorted(self._owned_client_order_ids)
            ),
            on_disconnect=self._on_private_ws_disconnect,
            on_reconciled=self._on_private_ws_reconciled,
            clock=self._clock,
        )
        with self._lock:
            self._private_ws = private_ws
        probe = private_ws.run_startup_reconnect_probe()
        if not (
            isinstance(probe, Mapping)
            and probe.get("opening_allowed_after_reconciliation") is True
        ):
            self._record_incident_recovery_private_ws_probe_failure(probe)
            try:
                private_ws.stop()
            finally:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_private_ws_startup_reconnect_probe_failed"
                )
        private_ws.start_monitoring()
        current_ws = private_ws.status() if hasattr(private_ws, "status") else {}
        if not (
            isinstance(probe, Mapping)
            and probe.get("opening_allowed_after_reconciliation") is True
            and isinstance(current_ws, Mapping)
            and current_ws.get("connected") is True
            and current_ws.get("listener_alive") is True
            and current_ws.get("opening_allowed_after_reconciliation") is True
        ):
            try:
                private_ws.stop()
            finally:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_incident_recovery_flat_private_ws_not_reconciled"
                )

        verified_snapshot = self._collect_exchange_snapshot(read_client)
        verified_hosted_exit_projection: Mapping[str, Any] | None = None
        if hosted_exit_projection is not None:
            verified_hosted_exit_projection, verified_hosted_exit_blockers = (
                _hosted_oco_terminal_exit_projection(
                    verified_snapshot,
                    authorization=auth,
                    current_head=current_head,
                )
            )
            if (
                verified_hosted_exit_blockers
                or verified_hosted_exit_projection is None
                or verified_hosted_exit_projection.get("identity_digest_sha256")
                != hosted_exit_projection.get("identity_digest_sha256")
            ):
                private_ws.stop()
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_hosted_oco_exit_snapshot_changed"
                )
        verified_blockers = self._incident_recovery_flat_snapshot_blockers(
            verified_snapshot,
            auth,
            hosted_exit_projection=verified_hosted_exit_projection,
            require_authorization_fingerprint=not flat_hosted_exit_binding,
        )
        if verified_blockers:
            private_ws.stop()
            raise OkxDemoPaperRuntimeError(";".join(verified_blockers))
        verified_fingerprint = _incident_recovery_flat_identity_sha256(
            verified_snapshot,
            owned_client_order_ids=owned_client_order_ids,
        )
        if (
            verified_fingerprint != expected_snapshot_fingerprint
            or not private_ws_snapshot_fingerprints
            or any(
                fingerprint != expected_snapshot_fingerprint
                for fingerprint in private_ws_snapshot_fingerprints
            )
        ):
            private_ws.stop()
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_flat_snapshot_changed"
            )
        flat_ws_receipt = private_ws.reconcile_current()
        if not (
            isinstance(flat_ws_receipt, Mapping)
            and flat_ws_receipt.get("connected") is True
            and flat_ws_receipt.get("listener_alive") is True
            and flat_ws_receipt.get("opening_allowed_after_reconciliation")
            is True
            and private_ws_snapshot_fingerprints
            and private_ws_snapshot_fingerprints[-1]
            == expected_snapshot_fingerprint
        ):
            private_ws.stop()
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_flat_private_ws_not_current"
            )
        with self._lock:
            self._apply_snapshot(verified_snapshot)
            self._persist_state()
        self._commit_ledger_reconciliation(
            snapshot=verified_snapshot,
            trigger="incident_recovery_flat_private_ws_verified",
        )
        self._require_incident_recovery_ledger_current(verified_snapshot)

        with self._lock:
            pending_intents = self._state["risk_control"].setdefault(
                "pending_order_intents", {}
            )
            if flat_hosted_exit_binding:
                opening_intent = pending_intents.setdefault(
                    auth["opening_cl_ord_id"],
                    {
                        "client_order_id": auth["opening_cl_ord_id"],
                        "risk_reducing_only": False,
                        "action": "open_long",
                        "order": {
                            "instId": OKX_DEMO_INSTRUMENT_ID,
                            "side": "buy",
                            "posSide": "long",
                            "ordType": "fok",
                            "sz": "0.01",
                            "clOrdId": auth["opening_cl_ord_id"],
                            "tag": OKX_DEMO_PAPER_ORDER_TAG,
                        },
                        "binding_source": _FLAT_HOSTED_EXIT_BINDING_SOURCE,
                    },
                )
            else:
                opening_intent = pending_intents[auth["opening_cl_ord_id"]]
            opening_intent.update(
                {
                    "status": "terminal",
                    "exchange_state": "filled",
                    "retry_without_query_allowed": False,
                    "flat_receipt_verified": True,
                }
            )
            owned = self._state["risk_control"].setdefault(
                "owned_attached_algos", {}
            ).setdefault(auth["algo_cl_ord_id"], {})
            owned.update(
                {
                    "algo_id": auth["algo_id"],
                    "algo_client_order_id": auth["algo_cl_ord_id"],
                    "parent_client_order_id": auth["opening_cl_ord_id"],
                    "instrument_id": OKX_DEMO_INSTRUMENT_ID,
                    "opening_intent": True,
                    "status": "cancelled_terminal",
                    "flat_receipt_verified": True,
                }
            )
            self._state["risk_control"]["active_protection"] = {}
            recoveries[receipt_sha256] = {
                "status": "flat_verified",
                "persisted_before_any_post": True,
                "post_attempted": False,
                "cancel_post_attempted": False,
                "retry_allowed": False,
                "failed_receipt_sha256": receipt_sha256,
                "failed_receipt_source_head": auth[
                    "failed_receipt_source_head"
                ],
                "failed_receipt_scenario": auth["failed_receipt_scenario"],
                "failed_receipt_run_id": auth["failed_receipt_run_id"],
                "opening_cl_ord_id": auth["opening_cl_ord_id"],
                "algo_cl_ord_id": auth["algo_cl_ord_id"],
                "algo_id": auth["algo_id"],
                "close_cl_ord_id": auth["expected_close_cl_ord_id"],
                "flat_identity_sha256": expected_snapshot_fingerprint,
                "private_ws_reconciled": True,
                "ledger_reconciled": True,
                "persisted_at_utc": _iso(self._clock()),
            }
            self._state["risk_control"]["incident_recovery_flat_verified"] = {
                "receipt_sha256": receipt_sha256,
                "flat_identity_sha256": expected_snapshot_fingerprint,
                "private_ws_reconciled": True,
                "ledger_reconciled": True,
                "no_order_or_cancel_post": True,
                "verified_at_utc": _iso(self._clock()),
            }
            self._state["private_ws"] = json.loads(
                json.dumps({
                    **dict(probe),
                    **dict(current_ws),
                    **dict(flat_ws_receipt),
                    "incident_final_snapshot_sha256": _fault_ledger_snapshot_sha256(
                        verified_snapshot
                    ),
                    "flat_identity_sha256": expected_snapshot_fingerprint,
                })
            )
            self._state["runtime"].update(
                {
                    "active": True,
                    "opening_allowed": False,
                    "cancel_only": True,
                    "status": "incident_recovery_flat_verified",
                    "last_error": "",
                    "blockers": [],
                }
            )
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_STARTUP,
                "incident_recovery_already_flat_verified",
            )
            self._state["runtime"]["status"] = "incident_recovery_flat_verified"
            self._state["safety"]["okx_demo_private_read_enabled"] = True
            self._state["safety"]["okx_demo_order_capability_enabled"] = False
            self._state["safety"]["okx_demo_cancel_capability_enabled"] = False
            self._persist_state()
        return {
            "decision": "incident_recovery_completed_safe_flat",
            "orders_posted": 0,
            "close_post_attempted": False,
            "cancel_post_attempted": False,
            "clOrdId": auth["opening_cl_ord_id"],
            "closeClOrdId": auth["expected_close_cl_ord_id"],
            "algoClOrdId": auth["algo_cl_ord_id"],
            "algoId": auth["algo_id"],
            "failed_receipt_sha256": receipt_sha256,
            "position_observed": True,
            "protection_verified": True,
            "private_ws_reconciled": True,
            "ledger_reconciled": True,
            "no_order_or_cancel_post": True,
            # Cleanup runs after this result is consumed by the immutable
            # receipt builder, so it must not erase the verified WS proof.
            **self._incident_recovery_terminal_projection(
                verified_snapshot,
                authorization=auth,
                private_ws_reconciled=True,
            ),
            "simulation_only": False,
        }

    def _incident_recovery_flat_durable_identity_blockers(
        self,
        authorization: Mapping[str, str],
    ) -> list[str]:
        risk = _mapping(self._state.get("risk_control"))
        intents = _mapping(risk.get("pending_order_intents"))
        opening = _mapping(intents.get(authorization["opening_cl_ord_id"]))
        owned_algos = _mapping(risk.get("owned_attached_algos"))
        owned = _mapping(owned_algos.get(authorization["algo_cl_ord_id"]))
        policy = ServerSideProtectionPolicy.from_mapping(
            risk.get("protection_policy")
        )
        blockers: list[str] = []
        if not (
            opening.get("client_order_id") == authorization["opening_cl_ord_id"]
            and opening.get("risk_reducing_only") is False
            and str(opening.get("action") or "") == "open_long"
            and _mapping(opening.get("order"))
            == {
                "instId": OKX_DEMO_INSTRUMENT_ID,
                "side": "buy",
                "posSide": "long",
                "ordType": "fok",
                "sz": "0.01",
                "clOrdId": authorization["opening_cl_ord_id"],
                "tag": OKX_DEMO_PAPER_ORDER_TAG,
            }
            and str(opening.get("status") or "")
            in {"submit_pending", "reconciled_terminal", "terminal"}
        ):
            blockers.append("okx_demo_incident_recovery_flat_opening_intent_mismatch")
        owned_identity_ok = (
            owned.get("algo_id") == authorization["algo_id"]
            or (
                not owned.get("algo_id")
                and str(owned.get("status") or "") == "submit_pending"
            )
        )
        if not (
            len(owned_algos) == 1
            and owned_identity_ok
            and owned.get("algo_client_order_id")
            == authorization["algo_cl_ord_id"]
            and owned.get("parent_client_order_id")
            == authorization["opening_cl_ord_id"]
            and owned.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and owned.get("opening_intent") is True
            and str(owned.get("status") or "")
            in {"submit_pending", "cancelled_terminal", "terminal"}
        ):
            blockers.append("okx_demo_incident_recovery_flat_owned_oco_mismatch")
        if risk.get("active_protection"):
            blockers.append("okx_demo_incident_recovery_flat_active_oco_present")
        if (
            policy.validate()
            or policy.to_dict() != OKX_DEMO_APPROVED_PROTECTION_POLICY
        ):
            blockers.append("okx_demo_incident_recovery_protection_policy_mismatch")
        return blockers

    def _incident_recovery_flat_snapshot_blockers(
        self,
        snapshot: Mapping[str, Any],
        authorization: Mapping[str, str],
        *,
        hosted_exit_projection: Mapping[str, Any] | None = None,
        require_authorization_fingerprint: bool = True,
    ) -> list[str]:
        blockers = list(self._preflight_blockers(snapshot, require_flat=True))
        if snapshot.get("pending_orders"):
            blockers.append("okx_demo_incident_recovery_flat_pending_order_present")
        if snapshot.get("pending_algo_orders"):
            blockers.append("okx_demo_incident_recovery_flat_pending_oco_present")
        if _gross_position_contracts(snapshot.get("positions", [])) != 0:
            blockers.append("okx_demo_incident_recovery_flat_position_not_flat")
        orders = [
            row
            for row in snapshot.get("orders", [])
            if isinstance(row, Mapping)
        ]
        fills = [
            row
            for row in snapshot.get("fills", [])
            if isinstance(row, Mapping)
        ]
        identities = [(authorization["opening_cl_ord_id"], "buy", "fok")]
        if hosted_exit_projection is None:
            identities.append(
                (authorization["expected_close_cl_ord_id"], "sell", "ioc")
            )
        for client_order_id, side, order_type in identities:
            matching_order = [
                row
                for row in orders
                if _client_order_id(row) == client_order_id
                and str(row.get("state") or "") == "filled"
                and str(row.get("instrument_id") or "")
                == OKX_DEMO_INSTRUMENT_ID
                and str(row.get("side") or "") == side
                and str(row.get("position_side") or "") == "long"
                and str(row.get("order_type") or "") == order_type
                and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
            ]
            matching_fill = [
                row
                for row in fills
                if _client_order_id(row) == client_order_id
                and str(row.get("instrument_id") or "")
                == OKX_DEMO_INSTRUMENT_ID
                and str(row.get("side") or "") == side
                and str(row.get("position_side") or "") == "long"
                and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
            ]
            if len(matching_order) != 1 or len(matching_fill) != 1:
                blockers.append(
                    "okx_demo_incident_recovery_flat_history_identity_mismatch"
                )
        if require_authorization_fingerprint and (
            _incident_recovery_flat_identity_sha256(
                snapshot,
                owned_client_order_ids=(
                    authorization["opening_cl_ord_id"],
                    authorization["expected_close_cl_ord_id"],
                ),
            )
            != authorization["flat_identity_sha256"]
        ):
            blockers.append("okx_demo_incident_recovery_flat_snapshot_changed")
        return _dedupe(blockers)

    def _incident_recovery_terminal_projection(
        self,
        snapshot: Mapping[str, Any],
        *,
        authorization: Mapping[str, str],
        private_ws_reconciled: bool,
    ) -> dict[str, Any]:
        """Project only terminal facts proved by this recovery's final snapshot.

        The fault-drill receipt serializer intentionally defaults absent fields
        to false or empty values.  Recovery must therefore carry the exact
        same-snapshot order/fill evidence through its result, while leaving any
        missing or ambiguous identity empty and every final proof false.
        """

        orders = [
            row for row in snapshot.get("orders", []) if isinstance(row, Mapping)
        ]
        fills = [
            row for row in snapshot.get("fills", []) if isinstance(row, Mapping)
        ]
        opening_cl_ord_id = str(authorization.get("opening_cl_ord_id") or "")
        opening_order_id = str(authorization.get("opening_order_id") or "")
        opening_fill_id = str(authorization.get("opening_fill_id") or "")
        close_cl_ord_id = str(authorization.get("expected_close_cl_ord_id") or "")

        entry_orders = [
            row
            for row in orders
            if row.get("order_id") == opening_order_id
            and row.get("client_order_id") == opening_cl_ord_id
            and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and row.get("side") == "buy"
            and row.get("position_side") == "long"
            and row.get("state") == "filled"
            and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
        ]
        entry_fills = [
            row
            for row in fills
            if row.get("fill_id") == opening_fill_id
            and row.get("order_id") == opening_order_id
            and row.get("client_order_id") == opening_cl_ord_id
            and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and row.get("side") == "buy"
            and row.get("position_side") == "long"
            and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
        ]
        close_orders = [
            row
            for row in orders
            if row.get("client_order_id") == close_cl_ord_id
            and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and row.get("side") == "sell"
            and row.get("position_side") == "long"
            and row.get("state") == "filled"
            and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
            and str(row.get("order_id") or "")
        ]
        close_fills = [
            row
            for row in fills
            if len(close_orders) == 1
            and row.get("order_id") == close_orders[0].get("order_id")
            and row.get("client_order_id") == close_cl_ord_id
            and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and row.get("side") == "sell"
            and row.get("position_side") == "long"
            and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
            and str(row.get("fill_id") or "")
        ]
        entry_proven = len(entry_orders) == 1 and len(entry_fills) == 1
        close_proven = len(close_orders) == 1 and len(close_fills) == 1
        ledger = _mapping(self._state.get("ledger_reconciliation"))
        ledger_reconciled = (
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
        )
        intents = _mapping(
            _mapping(self._state.get("risk_control")).get(
                "pending_order_intents"
            )
        )
        owned_algos = _mapping(
            _mapping(self._state.get("risk_control")).get(
                "owned_attached_algos"
            )
        )
        algo_cl_ord_id = str(authorization.get("algo_cl_ord_id") or "")
        algo_id = str(authorization.get("algo_id") or "")
        matching_owned_algos = [
            row
            for row in owned_algos.values()
            if isinstance(row, Mapping)
            and row.get("algo_client_order_id") == algo_cl_ord_id
            and row.get("algo_id") == algo_id
            and row.get("parent_client_order_id") == opening_cl_ord_id
        ]
        algo_proven = len(matching_owned_algos) == 1
        terminal_intents = all(
            isinstance(intent, Mapping)
            and str(intent.get("status") or "")
            in OKX_DEMO_TERMINAL_INTENT_STATUSES
            for intent in intents.values()
        )

        projection: dict[str, Any] = {
            "final_flat": _gross_position_contracts(snapshot.get("positions", []))
            == 0,
            "final_no_pending_orders": not snapshot.get("pending_orders"),
            "final_no_pending_algo_orders": not snapshot.get("pending_algo_orders"),
            "final_no_unresolved_intents": terminal_intents,
            "final_ledger_reconciled": ledger_reconciled,
            "final_private_ws_reconciled": private_ws_reconciled is True,
            "ledger_reconciled": ledger_reconciled,
            "private_ws_reconciled": private_ws_reconciled is True,
            "entry_order_id": opening_order_id if entry_proven else "",
            "entry_order_client_order_id": opening_cl_ord_id if entry_proven else "",
            "entry_fill_ids": [opening_fill_id] if entry_proven else [],
            "entry_fill_order_ids": [opening_order_id] if entry_proven else [],
            "entry_fill_client_order_ids": [opening_cl_ord_id]
            if entry_proven
            else [],
            "entry_fill_contracts": "0.01" if entry_proven else "",
            "entry_order_filled_contracts": "0.01" if entry_proven else "",
            "entry_fill_sum_contracts": "0.01" if entry_proven else "",
            "entry_position_contracts": "0.01" if entry_proven else "",
            "entry_order_type": str(entry_orders[0].get("order_type") or "")
            if entry_proven
            else "",
            "close_order_id": str(close_orders[0].get("order_id") or "")
            if close_proven
            else "",
            "close_order_client_order_id": close_cl_ord_id if close_proven else "",
            "close_fill_ids": [str(close_fills[0].get("fill_id") or "")]
            if close_proven
            else [],
            "close_fill_order_ids": [str(close_orders[0].get("order_id") or "")]
            if close_proven
            else [],
            "close_fill_client_order_ids": [close_cl_ord_id]
            if close_proven
            else [],
            "close_fill_contracts": "0.01" if close_proven else "",
            "close_order_filled_contracts": "0.01" if close_proven else "",
            "requested_contracts": "0.01" if entry_proven else "",
            "algo_id": algo_id if algo_proven else "",
            "algo_parent_cl_ord_id": opening_cl_ord_id if algo_proven else "",
        }
        return projection

    def _persist_hosted_oco_terminal_exit_projection(
        self,
        projection: Mapping[str, Any],
    ) -> None:
        """Persist the only hosted-OCO exit identity admissible to WS ownership.

        The projection is built from a verified canonical binding (including
        the narrow immutable flat-hosted-exit bundle) and a complete flat
        broker snapshot.  It is deliberately narrower than lifecycle/ledger
        ownership: a private stream may only use this exact terminal exit while
        the immutable event proof remains intact.
        """

        exit_identity = _mapping(projection.get("exit"))
        exit_client_order_id = str(exit_identity.get("client_order_id") or "")
        if not exit_client_order_id:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_hosted_oco_exit_projection_invalid"
            )
        with self._lock:
            self._owned_client_order_ids.add(exit_client_order_id)
            self._state["risk_control"][
                "hosted_oco_terminal_exit_projection"
            ] = json.loads(json.dumps(dict(projection)))
            self._append_event(
                "hosted_oco_terminal_exit_ownership_projection",
                dict(projection),
            )
            self._persist_state()

    def _incident_recovery_binding_blockers(
        self,
        authorization: Mapping[str, str],
        *,
        owner_marker_snapshot: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Verify the immutable offline recovery binding before any GET/WS/POST."""

        schema = str(authorization.get("recovery_binding_schema_version") or "")
        source = str(authorization.get("recovery_binding_source") or "")
        if (
            schema == _FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION
            or source == _FLAT_HOSTED_EXIT_BINDING_SOURCE
        ):
            return self._flat_hosted_exit_binding_blockers(authorization)

        path_text = str(authorization.get("recovery_binding_path") or "")
        binding_sha = str(authorization.get("recovery_binding_sha256") or "")
        runtime_root_text = str(authorization.get("recovery_runtime_root") or "")
        if not any(
            str(authorization.get(key) or "").strip()
            for key in (
                "recovery_binding_path",
                "recovery_binding_sha256",
                "recovery_runtime_root",
            )
        ):
            # Compatibility/manual incident recovery remains available for
            # existing callers; the canonical CLI always supplies the opaque
            # binding fields and therefore takes the strict path below.
            return []
        required = (
            path_text,
            binding_sha,
            runtime_root_text,
            str(authorization.get("recovery_binding_schema_version") or ""),
            str(authorization.get("recovery_runtime_root_sha256") or ""),
            str(authorization.get("recovery_runtime_run_id") or ""),
            str(authorization.get("recovery_runtime_state_sha256") or ""),
            str(authorization.get("recovery_runtime_events_sha256") or ""),
            str(authorization.get("recovery_runtime_last_event_hash") or ""),
            str(authorization.get("recovery_client_order_namespace") or ""),
            str(authorization.get("recovery_account_identity") or ""),
            str(authorization.get("recovery_credential_identity") or ""),
            str(authorization.get("incident_source_head") or ""),
            str(authorization.get("recovery_code_head") or ""),
            str(authorization.get("recovery_ancestry_proof") or ""),
            str(authorization.get("recovery_original_owner_marker_sha256") or ""),
            str(authorization.get("recovery_original_owner_marker_source_head") or ""),
            str(authorization.get("recovery_original_owner_marker_recovery_code_head") or ""),
            str(authorization.get("recovery_original_owner_marker_runtime_root_sha256") or ""),
            str(authorization.get("recovery_runtime_ledger_sha256") or ""),
        )
        if (
            not all(required)
            or authorization.get("recovery_binding_schema_version")
            != "btc_okx_demo_recovery_binding_v2"
            or not re.fullmatch(r"[0-9a-f]{64}", binding_sha)
            or not re.fullmatch(
                r"[0-9a-f]{40}", authorization.get("incident_source_head", "")
            )
            or not re.fullmatch(
                r"[0-9a-f]{40}", authorization.get("recovery_code_head", "")
            )
        ):
            return ["okx_demo_incident_recovery_binding_missing"]
        path = Path(path_text).resolve()
        runtime_root = Path(runtime_root_text).resolve()
        if runtime_root != Path(self.config.output_dir).resolve():
            return ["okx_demo_incident_recovery_runtime_root_mismatch"]
        if not path.is_file():
            return ["okx_demo_incident_recovery_binding_file_missing"]
        try:
            if _owned_restore_file_sha256(path) != binding_sha:
                return ["okx_demo_incident_recovery_binding_sha256_mismatch"]
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ["okx_demo_incident_recovery_binding_document_invalid"]
        if not isinstance(document, Mapping):
            return ["okx_demo_incident_recovery_binding_document_invalid"]
        content = dict(document)
        supplied_content_hash = str(content.pop("content_sha256", ""))
        try:
            authorization_ancestry = json.loads(
                authorization.get("recovery_ancestry_proof", "")
            )
        except (TypeError, json.JSONDecodeError):
            return ["okx_demo_incident_recovery_ancestry_invalid"]
        if (
            document.get("schema_version") != "btc_okx_demo_recovery_binding_v2"
            or not re.fullmatch(r"[0-9a-f]{64}", supplied_content_hash)
            or supplied_content_hash != _canonical_sha256(content)
        ):
            return ["okx_demo_incident_recovery_binding_content_hash_invalid"]
        current_head = _repo_head(self.config.repo_root)
        identity = _mapping(document.get("identity"))
        runtime_doc = _mapping(document.get("runtime_root"))
        failed_doc = _mapping(document.get("failed_receipt"))
        original_marker_doc = _mapping(document.get("owner_marker"))
        if (
            document.get("source_head")
            != authorization.get("incident_source_head")
            or document.get("incident_source_head")
            != authorization.get("incident_source_head")
            or document.get("recovery_code_head") != current_head
            or document.get("recovery_code_head")
            != authorization.get("recovery_code_head")
            or document.get("ancestry_proof") != authorization_ancestry
            or runtime_doc.get("path") != str(runtime_root)
            or runtime_doc.get("sha256") != authorization.get("recovery_runtime_root_sha256")
            or runtime_doc.get("source_head")
            != authorization.get("incident_source_head")
            or runtime_doc.get("recovery_code_head") != current_head
            or runtime_doc.get("run_id") != authorization.get("recovery_runtime_run_id")
            or runtime_doc.get("state_sha256") != authorization.get("recovery_runtime_state_sha256")
            or runtime_doc.get("events_sha256") != authorization.get("recovery_runtime_events_sha256")
            or runtime_doc.get("ledger_sha256") != authorization.get("recovery_runtime_ledger_sha256")
            or runtime_doc.get("last_event_hash") != authorization.get("recovery_runtime_last_event_hash")
            or str(runtime_doc.get("last_sequence") or "") != str(authorization.get("recovery_runtime_last_sequence") or "")
            or failed_doc.get("sha256") != authorization.get("failed_receipt_sha256")
            or failed_doc.get("source_head")
            != authorization.get("incident_source_head")
            or authorization.get("failed_receipt_source_head")
            != authorization.get("incident_source_head")
            or failed_doc.get("scenario") != authorization.get("failed_receipt_scenario")
            or failed_doc.get("run_id") != authorization.get("failed_receipt_run_id")
            or identity.get("opening_cl_ord_id") != authorization.get("opening_cl_ord_id")
            or identity.get("opening_order_id") != authorization.get("opening_order_id")
            or identity.get("opening_fill_id") != authorization.get("opening_fill_id")
            or identity.get("algo_cl_ord_id") != authorization.get("algo_cl_ord_id")
            or identity.get("algo_id") != authorization.get("algo_id")
            or identity.get("expected_close_cl_ord_id") != authorization.get("expected_close_cl_ord_id")
            or identity.get("client_order_namespace") != authorization.get("recovery_client_order_namespace")
            or identity.get("account_identity") != authorization.get("recovery_account_identity")
            or identity.get("credential_identity") != authorization.get("recovery_credential_identity")
            or original_marker_doc.get("sha256")
            != authorization.get("recovery_original_owner_marker_sha256")
            or original_marker_doc.get("source_head")
            != authorization.get("recovery_original_owner_marker_source_head")
            or original_marker_doc.get("recovery_code_head")
            != authorization.get("recovery_original_owner_marker_recovery_code_head")
            or original_marker_doc.get("runtime_root_sha256")
            != authorization.get("recovery_original_owner_marker_runtime_root_sha256")
        ):
            return ["okx_demo_incident_recovery_binding_identity_mismatch"]
        ancestry_valid = _incident_recovery_ancestry_proof_is_valid(
            repo_root=Path(self.config.repo_root).resolve(),
            incident_source_head=str(authorization.get("incident_source_head") or ""),
            marker_recovery_code_head=str(
                authorization.get(
                    "recovery_original_owner_marker_recovery_code_head"
                )
                or ""
            ),
            current_head=current_head,
            proof=authorization_ancestry,
        )
        if not ancestry_valid:
            return ["okx_demo_incident_recovery_ancestry_invalid"]
        lock_path = runtime_root / ".btc_okx_demo_fault_drill_writer.lock"
        state_path = runtime_root / "state.json"
        events_path = runtime_root / "events.jsonl"
        if not lock_path.is_file() or not state_path.is_file() or not events_path.is_file():
            return ["okx_demo_incident_recovery_runtime_root_files_missing"]
        lock_snapshot: Mapping[str, Any]
        if owner_marker_snapshot is not None:
            if owner_marker_snapshot.get("valid") is not True:
                return ["okx_demo_incident_recovery_owner_marker_invalid"]
            lock_snapshot = owner_marker_snapshot
            lock = _mapping(owner_marker_snapshot.get("marker"))
        elif self._fault_drill_owner_marker_session is not None:
            session = self._fault_drill_owner_marker_session
            handle = self._fault_drill_lock_handle
            if handle is not None:
                try:
                    handle.seek(0)
                    locked_snapshot = self._owner_marker_snapshot(handle.read())
                except (OSError, UnicodeError, json.JSONDecodeError):
                    return ["okx_demo_incident_recovery_owner_marker_invalid"]
                if locked_snapshot.get("valid") is not True:
                    return ["okx_demo_incident_recovery_owner_marker_invalid"]
                if locked_snapshot.get("raw") != session.get("raw"):
                    return ["okx_demo_incident_recovery_owner_marker_mismatch"]
                lock_snapshot = locked_snapshot
                lock = _mapping(locked_snapshot.get("marker"))
            else:
                lock_snapshot = self._owner_marker_snapshot(
                    bytes(session.get("raw") or b"")
                )
                lock = _mapping(session.get("marker"))
        else:
            try:
                path_snapshot = self._owner_marker_snapshot(lock_path.read_bytes())
                if path_snapshot.get("valid") is not True:
                    return ["okx_demo_incident_recovery_owner_marker_invalid"]
                lock_snapshot = path_snapshot
                lock = _mapping(path_snapshot.get("marker"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return ["okx_demo_incident_recovery_owner_marker_invalid"]
        marker_recovery_head = str(lock.get("recovery_code_head") or "")
        incident_head = str(authorization.get("incident_source_head") or "")
        same_head_marker = (
            incident_head == current_head and marker_recovery_head in {"", current_head}
        )
        cross_head_original_marker = (
            incident_head != current_head and marker_recovery_head == incident_head
        )
        cross_head_multihop_marker = (
            incident_head != current_head
            and marker_recovery_head
            == str(
                authorization.get(
                    "recovery_original_owner_marker_recovery_code_head"
                )
                or ""
            )
            and marker_recovery_head not in {incident_head, current_head}
            and ancestry_valid
        )
        session_current_marker = (
            self._fault_drill_owner_marker_session is not None
            and marker_recovery_head == current_head
        )
        if (
            not isinstance(lock, Mapping)
            or not str(lock.get("nonce") or "")
            or not isinstance(lock.get("process_id"), int)
            or lock.get("process_id") <= 0
            or lock.get("source_head") != incident_head
            or not (
                same_head_marker
                or cross_head_original_marker
                or cross_head_multihop_marker
                or session_current_marker
            )
            or lock.get("runtime_root_sha256") != authorization.get("recovery_runtime_root_sha256")
        ):
            return ["okx_demo_incident_recovery_owner_marker_mismatch"]
        if self._fault_drill_owner_marker_session is None and (
            lock_snapshot.get("sha256")
            != authorization.get("recovery_original_owner_marker_sha256")
            or lock.get("source_head")
            != authorization.get("recovery_original_owner_marker_source_head")
            or marker_recovery_head
            != authorization.get("recovery_original_owner_marker_recovery_code_head")
            or lock.get("runtime_root_sha256")
            != authorization.get("recovery_original_owner_marker_runtime_root_sha256")
        ):
            return ["okx_demo_incident_recovery_owner_marker_mismatch"]
        if (
            self._fault_drill_owner_marker_session is not None
            and self._fault_drill_owner_marker_preflight is not None
        ):
            original = _mapping(
                self._fault_drill_owner_marker_session.get("marker")
            )
            preflight_owner = _mapping(
                self._fault_drill_owner_marker_preflight
            )
            original_hash = str(original.get("original_owner_marker_sha256") or "")
            expected_hash = str(preflight_owner.get("sha256") or "")
            expected_marker = _mapping(preflight_owner.get("marker"))
            if (
                not expected_hash
                or original_hash != expected_hash
                or original.get("original_owner_marker_source_head")
                != str(expected_marker.get("source_head") or "")
                or original.get("original_owner_marker_recovery_code_head")
                != str(expected_marker.get("recovery_code_head") or "")
                or original.get("original_owner_marker_runtime_root_sha256")
                != str(expected_marker.get("runtime_root_sha256") or "")
                or original_hash
                != authorization.get("recovery_original_owner_marker_sha256")
                or original.get("original_owner_marker_source_head")
                != authorization.get("recovery_original_owner_marker_source_head")
                or original.get("original_owner_marker_recovery_code_head")
                != authorization.get("recovery_original_owner_marker_recovery_code_head")
                or original.get("original_owner_marker_runtime_root_sha256")
                != authorization.get("recovery_original_owner_marker_runtime_root_sha256")
            ):
                return [
                    "okx_demo_incident_recovery_owner_marker_provenance_mismatch"
                ]
        if (
            _owned_restore_file_sha256(state_path) != authorization.get("recovery_runtime_state_sha256")
            or _owned_restore_file_sha256(events_path) != authorization.get("recovery_runtime_events_sha256")
        ):
            return ["okx_demo_incident_recovery_runtime_file_hash_mismatch"]
        recovered = BTCRuntimeStore(runtime_root).recover()
        if recovered.blockers or recovered.truncated_tail:
            return ["okx_demo_incident_recovery_runtime_chain_invalid"]
        if _canonical_sha256(
            [
                _mapping(event.get("payload"))
                for event in recovered.events
                if event.get("event_type") == "ledger_uow_committed"
                and event.get("run_id")
                == authorization.get("recovery_runtime_run_id")
            ]
        ) != authorization.get("recovery_runtime_ledger_sha256"):
            return ["okx_demo_incident_recovery_runtime_ledger_hash_mismatch"]
        runtime = _mapping(recovered.state.get("runtime"))
        documented_runtime_source_head = str(
            document.get("runtime_source_head") or ""
        )
        authorized_runtime_source_head = str(
            authorization.get("runtime_source_head") or ""
        )
        if (
            not re.fullmatch(
                r"[0-9a-f]{40}",
                documented_runtime_source_head,
            )
            or (
                documented_runtime_source_head
                and authorized_runtime_source_head
                and authorized_runtime_source_head
                != documented_runtime_source_head
            )
        ):
            return ["okx_demo_incident_recovery_runtime_source_mismatch"]
        runtime_source_chain_valid = _incident_recovery_runtime_source_chain_is_valid(
            state=recovered.state,
            events=recovered.events,
            incident_head=str(authorization.get("incident_source_head") or ""),
            recovery_head=documented_runtime_source_head,
            runtime_run_id=str(
                authorization.get("recovery_runtime_run_id") or ""
            ),
            repo_root=Path(self.config.repo_root).resolve(),
        )
        if not runtime_source_chain_valid:
            return ["okx_demo_incident_recovery_runtime_source_mismatch"]
        if (
            runtime.get("run_id") != authorization.get("recovery_runtime_run_id")
            or recovered.last_event_hash != authorization.get("recovery_runtime_last_event_hash")
            or str(recovered.last_sequence) != str(authorization.get("recovery_runtime_last_sequence") or "")
            or not str(runtime.get("run_id") or "").startswith(authorization.get("recovery_runtime_run_id")[:8])
        ):
            return ["okx_demo_incident_recovery_runtime_chain_identity_mismatch"]
        namespace = str(authorization.get("recovery_client_order_namespace") or "")
        expected_namespace = f"btcDP{str(runtime.get('run_id') or '')[:8]}"
        if namespace != expected_namespace:
            return ["okx_demo_incident_recovery_namespace_not_current_runtime"]
        if not all(
            str(authorization.get(field) or "").startswith(namespace)
            for field in ("opening_cl_ord_id", "algo_cl_ord_id", "expected_close_cl_ord_id")
        ):
            return ["okx_demo_incident_recovery_namespace_identity_mismatch"]
        if _mapping(document.get("safety")).get("opening_allowed") is not False or _mapping(document.get("safety")).get("live_allowed") is not False:
            return ["okx_demo_incident_recovery_binding_safety_invalid"]
        return []

    def _flat_hosted_exit_binding_blockers(
        self,
        authorization: Mapping[str, str],
    ) -> list[str]:
        """Verify the receipt bundle without falling back to runtime-root v2.

        The document and its archived copies are re-hashed before the runtime
        constructs even a read-only client.  This narrow verifier deliberately
        does not inspect the mixed historical runtime root.
        """

        required = (
            "recovery_binding_path",
            "recovery_binding_sha256",
            "incident_source_head",
            "recovery_code_head",
            "recovery_ancestry_proof",
            "failed_receipt_sha256",
            "failed_receipt_source_head",
            "flat_identity_sha256",
            "opening_cl_ord_id",
            "opening_order_id",
            "opening_fill_id",
            "algo_cl_ord_id",
            "algo_id",
            "expected_close_cl_ord_id",
        )
        if (
            any(not str(authorization.get(key) or "") for key in required)
            or authorization.get("recovery_binding_schema_version")
            != _FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION
            or authorization.get("recovery_binding_source")
            != _FLAT_HOSTED_EXIT_BINDING_SOURCE
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(authorization.get("recovery_binding_sha256") or ""),
            )
        ):
            return ["okx_demo_flat_hosted_exit_binding_missing"]
        path = Path(str(authorization["recovery_binding_path"])).resolve()
        if not path.is_file():
            return ["okx_demo_flat_hosted_exit_binding_file_missing"]
        try:
            if _owned_restore_file_sha256(path) != authorization["recovery_binding_sha256"]:
                return ["okx_demo_flat_hosted_exit_binding_sha256_mismatch"]
            document = json.loads(path.read_text(encoding="utf-8"))
            completed = json.loads((path.parent / "COMPLETED").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ["okx_demo_flat_hosted_exit_binding_document_invalid"]
        if not isinstance(document, Mapping) or not isinstance(completed, Mapping):
            return ["okx_demo_flat_hosted_exit_binding_document_invalid"]
        try:
            authorization_ancestry = json.loads(
                str(authorization.get("recovery_ancestry_proof") or "")
            )
        except (TypeError, json.JSONDecodeError):
            return ["okx_demo_flat_hosted_exit_binding_ancestry_invalid"]
        if not isinstance(authorization_ancestry, Mapping):
            return ["okx_demo_flat_hosted_exit_binding_ancestry_invalid"]
        content = dict(document)
        content_sha256 = str(content.pop("content_sha256", ""))
        identity = _mapping(document.get("identity"))
        if (
            document.get("schema_version") != _FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION
            or document.get("binding_type") != _FLAT_HOSTED_EXIT_BINDING_SOURCE
            or document.get("binding_source") != _FLAT_HOSTED_EXIT_BINDING_SOURCE
            or content_sha256 != _canonical_sha256(content)
            or authorization.get("flat_identity_sha256") != content_sha256
            or completed.get("binding_sha256") != authorization.get("recovery_binding_sha256")
            or completed.get("content_sha256") != content_sha256
        ):
            return ["okx_demo_flat_hosted_exit_binding_content_invalid"]
        current_head = _repo_head(self.config.repo_root)
        if (
            document.get("incident_source_head")
            != authorization.get("incident_source_head")
            or document.get("incident_source_head")
            != authorization.get("failed_receipt_source_head")
            or document.get("recovery_code_head") != current_head
            or document.get("recovery_code_head")
            != authorization.get("recovery_code_head")
            or document.get("ancestry_proof")
            != authorization_ancestry
            or any(
                identity.get(document_key) != authorization.get(auth_key)
                for document_key, auth_key in (
                    ("opening_cl_ord_id", "opening_cl_ord_id"),
                    ("opening_order_id", "opening_order_id"),
                    ("opening_fill_id", "opening_fill_id"),
                    ("algo_cl_ord_id", "algo_cl_ord_id"),
                    ("algo_id", "algo_id"),
                    ("expected_close_cl_ord_id", "expected_close_cl_ord_id"),
                )
            )
        ):
            return ["okx_demo_flat_hosted_exit_binding_identity_mismatch"]
        try:
            ancestor = subprocess.run(
                [
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    str(document.get("incident_source_head") or ""),
                    current_head,
                ],
                cwd=Path(self.config.repo_root).resolve(),
                capture_output=True,
                text=True,
            )
        except OSError:
            return ["okx_demo_flat_hosted_exit_binding_ancestry_unavailable"]
        if ancestor.returncode != 0:
            return ["okx_demo_flat_hosted_exit_binding_ancestry_invalid"]

        sources: dict[str, Mapping[str, Any]] = {}
        for key, filename in (
            ("failed_receipt", "failed_incident.json"),
            ("fresh_truth", "fresh_truth.json"),
            ("fill_diagnostic", "fill_diagnostic.json"),
            ("exit_order", "exit_order.json"),
        ):
            descriptor = _mapping(document.get(key))
            source_path = path.parent / "sources" / filename
            if descriptor.get("source_file") != f"sources/{filename}" or not source_path.is_file():
                return ["okx_demo_flat_hosted_exit_binding_source_missing"]
            try:
                if _owned_restore_file_sha256(source_path) != descriptor.get("sha256"):
                    return ["okx_demo_flat_hosted_exit_binding_source_hash_mismatch"]
                decoded = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return ["okx_demo_flat_hosted_exit_binding_source_invalid"]
            if not isinstance(decoded, Mapping):
                return ["okx_demo_flat_hosted_exit_binding_source_invalid"]
            sources[key] = decoded
        failed = sources["failed_receipt"]
        fresh = sources["fresh_truth"]
        diagnostic = sources["fill_diagnostic"]
        order = sources["exit_order"]
        exit_order = _mapping(order.get("order"))
        raw_exit_fills = diagnostic.get("fills")
        exit_fills = (
            [row for row in raw_exit_fills if isinstance(row, Mapping)]
            if isinstance(raw_exit_fills, Sequence)
            and not isinstance(raw_exit_fills, (str, bytes))
            else []
        )
        expected = _FRESH_STATE_EMERGENCY_FIXED_IDENTITY
        bundle_identity_ok = (
            failed.get("schema_version") == "btc_okx_demo_fault_drill_receipt_v1"
            and failed.get("orders_posted") == 1
            and str(failed.get("source_head") or "")
            == authorization.get("incident_source_head")
            and fresh.get("schema_version") == "btc_okx_demo_fresh_broker_truth_receipt_v2"
            and diagnostic.get("schema_version") == "btc_okx_demo_fill_identity_diagnostic_v1"
            and order.get("schema_version") == "btc_okx_demo_unknown_fill_exact_order_receipt_v1"
            and str(_mapping(_mapping(fresh.get("rest")).get("known_identity")).get("entry_cl_ord_id") or "") == expected["entry_cl_ord_id"]
            and str(_mapping(_mapping(fresh.get("rest")).get("known_identity")).get("entry_ord_id") or "") == expected["entry_ord_id"]
            and str(exit_order.get("clOrdId") or "") == authorization.get("expected_close_cl_ord_id")
            and str(exit_order.get("algoId") or "") == expected["oco_algo_id"]
            and str(exit_order.get("algoClOrdId") or "") == expected["oco_algo_cl_ord_id"]
            and str(exit_order.get("state") or "") == "filled"
            and str(exit_order.get("ordType") or "") == "market"
            and str(exit_order.get("reduceOnly") or "") == "true"
            and str(exit_order.get("side") or "") == "sell"
            and str(exit_order.get("posSide") or "") == "long"
            and _decimal(exit_order.get("sz")) == OKX_DEMO_PAPER_CONTRACTS
            and len([row for row in exit_fills if str(row.get("clOrdId") or "") == authorization.get("expected_close_cl_ord_id") and str(row.get("ordId") or "") == str(exit_order.get("ordId") or "") and str(row.get("fillId") or "") == ""]) == 1
        )
        if not bundle_identity_ok:
            return ["okx_demo_flat_hosted_exit_binding_source_identity_mismatch"]
        safety = _mapping(document.get("safety"))
        if any(safety.get(key) is not False for key in ("opening_allowed", "paper_promotion_allowed", "promotion_eligible", "live_allowed", "private_allowed", "order_allowed", "transfer_allowed", "withdraw_allowed")):
            return ["okx_demo_flat_hosted_exit_binding_safety_invalid"]
        return []

    def _incident_recovery_durable_identity_blockers(
        self,
        authorization: Mapping[str, str],
    ) -> list[str]:
        risk = _mapping(self._state.get("risk_control"))
        pending_intents = _mapping(risk.get("pending_order_intents"))
        opening = _mapping(pending_intents.get(authorization["opening_cl_ord_id"]))
        owned_algos = _mapping(risk.get("owned_attached_algos"))
        owned = _mapping(owned_algos.get(authorization["algo_cl_ord_id"]))
        active = _mapping(risk.get("active_protection"))
        policy = ServerSideProtectionPolicy.from_mapping(
            risk.get("protection_policy")
        )
        blockers: list[str] = []
        if not (
            opening.get("client_order_id") == authorization["opening_cl_ord_id"]
            and opening.get("risk_reducing_only") is False
            and str(opening.get("action") or "") == "open_long"
            and _mapping(opening.get("order"))
            == {
                "instId": OKX_DEMO_INSTRUMENT_ID,
                "side": "buy",
                "posSide": "long",
                "ordType": "fok",
                "sz": "0.01",
                "clOrdId": authorization["opening_cl_ord_id"],
                "tag": OKX_DEMO_PAPER_ORDER_TAG,
            }
        ):
            blockers.append("okx_demo_incident_recovery_opening_intent_mismatch")
        normal_owned = (
            len(owned_algos) == 1
            and owned.get("algo_id") == authorization["algo_id"]
            and owned.get("algo_client_order_id")
            == authorization["algo_cl_ord_id"]
            and owned.get("parent_client_order_id")
            == authorization["opening_cl_ord_id"]
            and owned.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and owned.get("opening_intent") is True
            and owned.get("status") == "active"
        )
        legacy_owned = (
            len(owned_algos) == 1
            and not active
            and dict(owned)
            == {
                "algo_client_order_id": authorization["algo_cl_ord_id"],
                "parent_client_order_id": authorization["opening_cl_ord_id"],
                "instrument_id": OKX_DEMO_INSTRUMENT_ID,
                "opening_intent": True,
                "status": "submit_pending",
            }
        )
        if not (normal_owned or legacy_owned):
            blockers.append("okx_demo_incident_recovery_owned_oco_mismatch")
        normal_active = (
            active.get("algo_id") == authorization["algo_id"]
            and active.get("algo_client_order_id")
            == authorization["algo_cl_ord_id"]
            and active.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
            and active.get("position_side") == "long"
            and _decimal(active.get("contracts")) == OKX_DEMO_PAPER_CONTRACTS
            and active.get("status") == "exchange_accepted"
        )
        if not (normal_active or legacy_owned):
            blockers.append("okx_demo_incident_recovery_active_oco_mismatch")
        if (
            policy.validate()
            or policy.to_dict() != OKX_DEMO_APPROVED_PROTECTION_POLICY
        ):
            blockers.append("okx_demo_incident_recovery_protection_policy_mismatch")
        return blockers

    def _require_incident_recovery_ledger_current(
        self,
        snapshot: Mapping[str, Any],
    ) -> None:
        ledger = _mapping(self._state.get("ledger_reconciliation"))
        if not (
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
            and ledger.get("exchange_snapshot_sha256")
            == _fault_ledger_snapshot_sha256(snapshot)
            and int(ledger.get("order_count") or 0)
            == len(snapshot.get("orders", []))
            and int(ledger.get("pending_order_count") or 0)
            == len(snapshot.get("pending_orders", []))
            and int(ledger.get("pending_algo_order_count") or 0)
            == len(snapshot.get("pending_algo_orders", []))
            and int(ledger.get("fill_count") or 0)
            == len(snapshot.get("fills", []))
            and int(ledger.get("position_count") or 0)
            == len(snapshot.get("positions", []))
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_ledger_not_current"
            )

    def _cancel_exact_incident_algo_once(
        self,
        client: Any,
        *,
        snapshot: Mapping[str, Any],
        algo_id: str,
        algo_client_order_id: str,
    ) -> dict[str, Any]:
        """At most one cancel POST; every outcome gets one query-only readback."""

        if _gross_position_contracts(snapshot.get("positions", [])) != 0:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_cancel_requires_flat"
            )
        pending_algos = [
            dict(row)
            for row in snapshot.get("pending_algo_orders", [])
            if isinstance(row, Mapping)
        ]
        matching = [
            row
            for row in pending_algos
            if str(row.get("algo_id") or "") == algo_id
            and str(row.get("algo_client_order_id") or "")
            == algo_client_order_id
            and str(row.get("instrument_id") or "")
            == OKX_DEMO_INSTRUMENT_ID
            and str(row.get("position_side") or "") == "long"
            and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
            and str(row.get("order_type") or "") == "oco"
            and str(row.get("state") or "") == "live"
        ]
        if len(pending_algos) not in {0, 1} or (
            pending_algos and len(matching) != 1
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_cancel_identity_mismatch"
            )
        cancel_attempted = False
        cancel_error = ""
        response: OkxDemoResponse | None = None
        if matching:
            with self._lock:
                cancel_intents = self._state["risk_control"].setdefault(
                    "incident_algo_cancel_intents", {}
                )
                if algo_client_order_id in cancel_intents:
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_incident_recovery_cancel_already_consumed"
                    )
                cancel_intents[algo_client_order_id] = {
                    "status": "intent_persisted",
                    "persisted_before_post": True,
                    "algo_id": algo_id,
                    "algo_client_order_id": algo_client_order_id,
                    "instrument_id": OKX_DEMO_INSTRUMENT_ID,
                    "post_attempted": False,
                    "retry_allowed": False,
                    "persisted_at_utc": _iso(self._clock()),
                }
                self._append_event(
                    "incident_algo_cancel_intent_persisted_before_post",
                    dict(cancel_intents[algo_client_order_id]),
                )
                self._persist_state()
            cancel_attempted = True
            with self._lock:
                cancel_intents[algo_client_order_id]["post_attempted"] = True
                self._persist_state()
            try:
                response = self._dispatch_control_action(
                    action=RuntimeAction.CANCEL_ORDER,
                    client=client,
                    snapshot=snapshot,
                    control_key=f"{algo_id}:{algo_client_order_id}",
                    callback=lambda _intent: client.cancel_algo_orders(
                        [{"algoId": algo_id, "instId": OKX_DEMO_INSTRUMENT_ID}]
                    ),
                )
                if not isinstance(response, OkxDemoResponse):
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_execution_boundary_cancel_receipt_invalid"
                    )
            except Exception as exc:
                cancel_error = _safe_error(exc)
        pending_response = client.private_get(
            "/api/v5/trade/orders-algo-pending",
            {"instId": OKX_DEMO_INSTRUMENT_ID, "ordType": "oco"},
        )
        history_response = client.private_get(
            "/api/v5/trade/orders-algo-history",
            {
                "instId": OKX_DEMO_INSTRUMENT_ID,
                "ordType": "oco",
                "algoId": algo_id,
            },
        )
        pending_rows = [
            row for row in _require(
                pending_response,
                "incident_recovery_algo_pending_readback",
                require_data=False,
            ).data
            if isinstance(row, Mapping)
        ]
        history_rows = [
            row for row in _require(
                history_response,
                "incident_recovery_algo_history_readback",
                require_data=False,
            ).data
            if isinstance(row, Mapping)
        ]
        exact_history = [
            row
            for row in history_rows
            if str(row.get("algoId") or "") == algo_id
            and str(row.get("algoClOrdId") or "") == algo_client_order_id
            and str(row.get("instId") or "") == OKX_DEMO_INSTRUMENT_ID
            and str(row.get("ordType") or "") == "oco"
            and str(row.get("state") or "") in {"canceled", "cancelled"}
        ]
        exact_pending = [
            row
            for row in pending_rows
            if str(row.get("algoId") or "") == algo_id
            and str(row.get("algoClOrdId") or "") == algo_client_order_id
        ]
        ack_ok = bool(
            response is not None
            and response.action_ok
            and len(response.data) == 1
            and str(response.data[0].get("algoId") or "") == algo_id
            and str(response.data[0].get("sCode") or "") == "0"
        )
        readback_terminal = (
            not pending_rows
            and not exact_pending
            and len(exact_history) == 1
        )
        ack_recovered_by_readback = bool(
            cancel_attempted and not ack_ok and readback_terminal
        )
        if cancel_error and not ack_recovered_by_readback:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_cancel_ambiguous_frozen:"
                + cancel_error
            )
        if cancel_attempted and not ack_ok and not ack_recovered_by_readback:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_cancel_ack_invalid_frozen"
            )
        if not readback_terminal:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_incident_recovery_cancel_readback_not_terminal"
            )
        if matching:
            with self._lock:
                cancel_intents[algo_client_order_id]["status"] = (
                    "terminal_verified"
                )
                cancel_intents[algo_client_order_id]["completed_at_utc"] = (
                    _iso(self._clock())
                )
                owned = self._state["risk_control"].get(
                    "owned_attached_algos", {}
                )
                owned_record = (
                    owned.get(algo_client_order_id)
                    if isinstance(owned, dict)
                    else None
                )
                if isinstance(owned_record, dict):
                    owned_record.update(
                        {
                            "algo_id": algo_id,
                            "status": "cancelled_terminal",
                        }
                    )
                self._state["risk_control"]["active_protection"] = {}
                self._persist_state()
        return {
            "cancel_attempted": cancel_attempted,
            "cancel_post_count": 1 if cancel_attempted else 0,
            "pending_readback_empty": True,
            "history_terminal_verified": True,
            "ack_recovered_by_readback": ack_recovered_by_readback,
            "algo_id": algo_id,
            "algo_client_order_id": algo_client_order_id,
        }

    def recover_fault_drill_after_worker_kill(
        self,
        *,
        authorization: Mapping[str, Any],
        child_termination: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Reconstruct from durable state after an independently killed worker."""

        return self._recover_fault_drill_after_worker_kill_with_writer_lock(
            authorization=authorization,
            child_termination=child_termination,
        )

    @_runtime_writer_session(nonce_argument="authorization")
    def _recover_fault_drill_after_worker_kill_with_writer_lock(
        self,
        *,
        authorization: Mapping[str, Any],
        child_termination: Mapping[str, Any],
    ) -> dict[str, Any]:

        marker = _mapping(
            self._state.get("runtime", {}).get("fault_drill_worker_ready")
        )
        termination_evidence = dict(child_termination)
        termination_evidence["lock_reacquired_after_child_exit"] = True
        child_pid = termination_evidence.get("process_id")
        current_head = _repo_head(self.config.repo_root)
        runtime_root_hash = _canonical_sha256(
            str(Path(self.config.output_dir).resolve())
        )
        if (
            authorization.get("scenario") != "worker_kill"
            or authorization.get("execute_demo") is not True
            or authorization.get("authorization_ticket")
            != "BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01"
            or not isinstance(child_pid, int)
            or child_pid <= 0
            or child_pid == os.getpid()
            or marker.get("process_id") != child_pid
            or marker.get("worker_nonce")
            != str(authorization.get("worker_nonce") or "")
            or str(marker.get("process_create_time") or "")
            != str(authorization.get("process_create_time") or "")
            or marker.get("source_head") != current_head
            or marker.get("runtime_root_sha256") != runtime_root_hash
            or marker.get("position_observed") is not True
            or marker.get("protection_verified") is not True
            or termination_evidence.get("external") is not True
            or termination_evidence.get("terminated") is not True
            or termination_evidence.get("wait_confirmed") is not True
            or termination_evidence.get("parent_readback_verified") is not True
            or termination_evidence.get("lock_reacquired_after_child_exit") is not True
            or self._fault_drill_lock_handle is None
            or self._fault_drill_lock_nonce
            != str(authorization.get("worker_nonce") or "")
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_termination_evidence_invalid"
            )
        expected_marker_hash = str(marker.get("marker_sha256") or "")
        marker_without_hash = dict(marker)
        marker_without_hash.pop("marker_sha256", None)
        if expected_marker_hash != _canonical_sha256(marker_without_hash):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_ready_marker_hash_invalid"
            )
        if (
            str(self._state.get("runtime", {}).get("run_id") or "")
            != str(marker.get("run_id") or "")
            or self._sequence != int(marker.get("order_sequence") or -1)
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_runtime_identity_not_restored"
            )
        expected_close_client_order_id = (
            f"btcDP{str(marker.get('run_id') or '')[:8]}"
            f"{self._sequence + 1:04d}"
        )

        # The first exchange operation of the reconstructed controller is a
        # read-only full snapshot; no order capability exists until it matches.
        read_client = self._read_only_client()
        recovered_snapshot = self._collect_exchange_snapshot(read_client)
        recovered_hash = _canonical_sha256(
            _fault_reconciliation_facts(recovered_snapshot)
        )
        if recovered_hash != str(marker.get("held_reconciliation_sha256") or ""):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_reconstruction_mismatch"
            )
        if (
            str(termination_evidence.get("parent_reconciliation_sha256") or "")
            != recovered_hash
            or str(termination_evidence.get("parent_ledger_snapshot_sha256") or "")
            != _fault_ledger_snapshot_sha256(recovered_snapshot)
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_parent_verification_not_reproduced"
            )
        gross = _gross_position_contracts(recovered_snapshot.get("positions", []))
        matching = next(
            (
                row
                for row in recovered_snapshot.get("pending_algo_orders", [])
                if isinstance(row, Mapping)
                and str(row.get("algo_id") or "") == str(marker.get("algoId") or "")
                and str(row.get("algo_client_order_id") or "")
                == str(marker.get("algoClOrdId") or "")
            ),
            None,
        )
        if gross != OKX_DEMO_PAPER_CONTRACTS or matching is None:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_recovered_protection_missing"
            )

        credentials = self._credential_loader(self.config.credential_service)
        write_client = self._client_factory(
            OkxDemoClientConfig(
                credential_service=self.config.credential_service,
                allow_private_read=True,
                allow_demo_orders=True,
                allow_demo_cancels=True,
                authorization_ticket=OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
                max_order_contracts=OKX_DEMO_PAPER_CONTRACTS,
                max_notional_usdt=OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
                contract_value_btc=OKX_DEMO_PAPER_CONTRACT_VALUE_BTC,
            ),
            credentials,
        )
        with self._lock:
            self._client = write_client
            self._state["runtime"].update(
                {
                    "active": True,
                    "opening_allowed": False,
                    "cancel_only": True,
                    "recovery_state": "RECOVERY_REDUCING",
                }
            )
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_REDUCING,
                "fault_drill_worker_reconstructed",
            )
            self._apply_snapshot(recovered_snapshot)
        self._commit_ledger_reconciliation(
            snapshot=recovered_snapshot,
            trigger="fault_drill_worker_first_read_reconciliation",
        )
        self._arm_dead_man(write_client, trigger="fault_drill_worker_recovery")
        strategy = _mapping(
            _mapping((self._state.get("audit") or [{}])[0]).get("signal")
        )
        self._run_risk_reduction_cycle(write_client, strategy=strategy)
        close_intent = _mapping(
            _mapping(self._state.get("risk_control")).get(
                "pending_order_intents"
            )
        ).get(expected_close_client_order_id)
        if not (
            isinstance(close_intent, Mapping)
            and close_intent.get("risk_reducing_only") is True
            and str(close_intent.get("status") or "") == "terminal"
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_fault_drill_worker_stable_close_intent_missing"
            )
        final_snapshot = self._collect_exchange_snapshot(write_client)
        final_snapshot, algo_cleanup = self._cleanup_owned_flat_algos(
            write_client,
            snapshot=final_snapshot,
        )
        with self._lock:
            self._apply_snapshot(final_snapshot)
        self._commit_ledger_reconciliation(
            snapshot=final_snapshot,
            trigger="fault_drill_worker_postflight",
        )
        blockers = self._fault_drill_postflight_blockers(final_snapshot)
        if blockers:
            self.freeze_fault_drill(";".join(blockers))
            raise OkxDemoPaperRuntimeError(";".join(blockers))
        self.freeze_fault_drill("fault_drill_completed_requires_review")
        shared_terminal_projection = self._fault_drill_terminal_projection(
            final_snapshot,
            opening_cl_ord_id=str(marker.get("clOrdId") or ""),
            close_cl_ord_id=expected_close_client_order_id,
            algo_cl_ord_id=str(marker.get("algoClOrdId") or ""),
        )
        return {
            "decision": "worker_kill_recovered_completed_flat",
            "simulation_only": False,
            "orders_posted": 2,
            "clOrdId": str(marker.get("clOrdId") or ""),
            "closeClOrdId": expected_close_client_order_id,
            "algoClOrdId": str(marker.get("algoClOrdId") or ""),
            "process_id": child_pid,
            "reconstructed_process_id": os.getpid(),
            "child_termination": termination_evidence,
            "worker_ready_marker_persisted": True,
            "position_observed": True,
            "protection_verified": True,
            "same_position_after_reconstruction": True,
            "same_protection_after_reconstruction": True,
            "pre_reconciliation_sha256": str(
                marker.get("held_reconciliation_sha256") or ""
            ),
            "post_reconciliation_sha256": recovered_hash,
            "reconciliation_comparison_match": True,
            "algo_cleanup": algo_cleanup,
            "fault_origin": "external_worker_process_termination",
            "evidence_mode": "real_demo_independent_worker_process",
            **shared_terminal_projection,
        }

    def _set_risk_mode(self, mode: str, reason: str) -> None:
        if mode not in {
            OKX_DEMO_RISK_MODE_STARTUP,
            OKX_DEMO_RISK_MODE_RUNNING,
            OKX_DEMO_RISK_MODE_REDUCING,
            OKX_DEMO_RISK_MODE_FROZEN,
        }:
            raise OkxDemoPaperRuntimeError("okx_demo_risk_mode_invalid")
        self._state["risk_control"].update(
            {
                "mode": mode,
                "reason": str(reason)[:500],
            }
        )
        self._state["runtime"]["opening_allowed"] = (
            mode == OKX_DEMO_RISK_MODE_RUNNING
        )
        self._state["runtime"]["cancel_only"] = (
            mode != OKX_DEMO_RISK_MODE_RUNNING
        )
        if self._state["runtime"].get("active"):
            self._state["runtime"]["status"] = {
                OKX_DEMO_RISK_MODE_RUNNING: "running",
                OKX_DEMO_RISK_MODE_REDUCING: "risk_reducing_only",
                OKX_DEMO_RISK_MODE_FROZEN: "frozen_unknown",
                OKX_DEMO_RISK_MODE_STARTUP: "startup_reconciling",
            }[mode]

    def _append_safety_alert(self, code: str, *, severity: str = "critical") -> None:
        alerts = self._state["risk_control"].setdefault("alerts", [])
        alerts.insert(
            0,
            {
                "code": str(code)[:240],
                "severity": severity,
                "timestamp_utc": _iso(self._clock()),
                "acknowledged": False,
            },
        )
        del alerts[100:]

    def _arm_dead_man(
        self,
        client: OkxDemoClient,
        *,
        trigger: str,
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        if snapshot is None:
            with self._lock:
                snapshot = dict(_mapping(self._state.get("exchange")))
        else:
            snapshot = dict(snapshot)
        response = self._dispatch_control_action(
            action=RuntimeAction.DEAD_MAN,
            client=client,
            snapshot=snapshot,
            control_key=f"arm:{trigger}",
            callback=lambda _intent: client.cancel_all_after(
                timeout_seconds=int(self.config.dead_man_timeout_seconds),
                tag=OKX_DEMO_PAPER_ORDER_TAG,
            ),
        )
        if not isinstance(response, OkxDemoResponse):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_execution_boundary_dead_man_receipt_invalid"
            )
        self._require_dead_man_ack(
            response,
            timeout_seconds=int(self.config.dead_man_timeout_seconds),
        )
        with self._lock:
            dead_man = self._state["risk_control"]["dead_man"]
            runtime = self._state["runtime"]
            epoch = int(runtime.get("authoritative_liveness_epoch") or 0)
            dead_man.update(
                {
                    "armed": True,
                    "last_ack_utc": _iso(self._clock()),
                    "last_error": "",
                    "renewal_owner": self._authoritative_renewal_owner(
                        epoch=epoch
                    ),
                }
            )
            # An exchange ACK is not authority until its matching event and
            # checkpoint are durable.  The pending phase deliberately leaves
            # the write path closed if either persistence step fails.
            self._state["risk_control"]["write_path_trusted"] = False
            try:
                self._append_event(
                    "dead_man_heartbeat_acknowledged",
                    {
                        "trigger": trigger,
                        "tag": OKX_DEMO_PAPER_ORDER_TAG,
                        "timeout_seconds": self.config.dead_man_timeout_seconds,
                        "account_scope": "dedicated_demo_account",
                        "pending_orders_only": True,
                        "positions_are_not_closed": True,
                    },
                )
                self._persist_state()
                self._state["risk_control"]["write_path_trusted"] = True
                self._persist_state()
            except Exception as exc:
                reason = "okx_demo_dead_man_ack_persistence_failed"
                self._state["risk_control"]["write_path_trusted"] = False
                self._state["risk_control"]["dead_man"]["last_error"] = reason
                self._enter_cancel_only(reason, active=runtime.get("active") is True)
                try:
                    self._append_event(
                        "dead_man_ack_persistence_failed",
                        {"error": _safe_error(exc)},
                    )
                except Exception:
                    pass
                try:
                    self._persist_state()
                except Exception:
                    pass
                raise OkxDemoPaperRuntimeError(reason) from exc

    def _boundary_snapshot_requires_refresh(
        self,
        snapshot: Mapping[str, Any],
    ) -> bool:
        observed = _parse_utc(snapshot.get("captured_at_utc"))
        if observed is None:
            return True
        age = self._clock().astimezone(timezone.utc) - observed
        refresh_after = timedelta(
            seconds=(
                OKX_DEMO_BOUNDARY_SNAPSHOT_TTL_SECONDS
                - OKX_DEMO_BOUNDARY_SNAPSHOT_REFRESH_MARGIN_SECONDS
            )
        )
        return age < timedelta(0) or age >= refresh_after

    def _refresh_dead_man_authoritative_snapshot(
        self,
        client: OkxDemoClient,
    ) -> dict[str, Any]:
        """Refresh REST/WS/ledger truth before any renewal POST.

        All network work runs without the controller state lock.  The private
        WS object and generation are captured first and rechecked before the
        refreshed snapshot becomes durable.  Any uncertainty raises before
        the caller can reach cancel-all-after.
        """

        with self._lock:
            private_ws = self._private_ws
            generation = self._private_ws_generation
            active_client = self._client
            active = self._state["runtime"].get("active") is True
        if (
            not active
            or active_client is not client
            or private_ws is None
            or not hasattr(private_ws, "reconcile_current")
            or not hasattr(private_ws, "status")
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_dead_man_authoritative_snapshot_refresh_failed:"
                "private_ws_authority_unavailable"
            )
        try:
            refreshed = self._collect_exchange_snapshot(client)
            blockers = self._preflight_blockers(
                refreshed,
                require_flat=False,
            )
            if blockers:
                raise OkxDemoPaperRuntimeError(";".join(blockers))
            current_ws = private_ws.reconcile_current()
            current_status = private_ws.status()
            current_head = _repo_head(self.config.repo_root)
            if (
                not isinstance(current_ws, Mapping)
                or not _private_ws_current_receipt_valid(
                    current_ws,
                    current_head=current_head,
                )
                or not isinstance(current_status, Mapping)
                or current_status.get("connected") is not True
                or current_status.get("listener_alive") is not True
                or current_status.get(
                    "opening_allowed_after_reconciliation"
                )
                is not True
            ):
                raise OkxDemoPaperRuntimeError(
                    "private_ws_current_reconciliation_untrusted"
                )
            with self._lock:
                if (
                    self._client is not client
                    or self._private_ws is not private_ws
                    or self._private_ws_generation != generation
                    or self._state["runtime"].get("active") is not True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "private_ws_generation_changed"
                    )
                durable_ws = dict(_mapping(self._state.get("private_ws")))
                durable_ws.update(dict(current_ws))
                durable_ws.update(dict(current_status))
                durable_ws["controller_generation"] = generation
                self._state["private_ws"] = json.loads(
                    json.dumps(durable_ws)
                )
            self._commit_ledger_reconciliation(
                snapshot=refreshed,
                trigger="dead_man_authoritative_snapshot_refresh",
                apply_snapshot=True,
            )
            with self._lock:
                ledger = _mapping(self._state.get("ledger_reconciliation"))
                if (
                    ledger.get("status") != "reconciled"
                    or ledger.get("current_state_exchange_snapshot_match")
                    is not True
                    or ledger.get("funding_cashflow_reconciled") is not True
                ):
                    raise OkxDemoPaperRuntimeError(
                        "ledger_reconciliation_not_current"
                    )
                return json.loads(
                    json.dumps(dict(_mapping(self._state.get("exchange"))))
                )
        except Exception as exc:
            code = _safe_error(exc)
            if code.startswith(
                "okx_demo_dead_man_authoritative_snapshot_refresh_failed:"
            ):
                raise
            raise OkxDemoPaperRuntimeError(
                "okx_demo_dead_man_authoritative_snapshot_refresh_failed:"
                + code
            ) from exc

    def _renew_dead_man_once(self, client: OkxDemoClient) -> None:
        """Renew CAA from the bounded durable protective projection.

        The dispatcher independently proves that the original exchange
        snapshot is no older than its 120-second protective ceiling and that
        account identity, Private WS and ledger authority are all complete.
        This path never rewrites ``captured_at_utc`` and never waits for a slow
        REST/WS/ledger refresh.  New orders and attached protection continue to
        use the dispatcher's strict 30-second snapshot contract.
        """

        with self._execution_lock:
            with self._lock:
                snapshot = dict(_mapping(self._state.get("exchange")))
            self._arm_dead_man(
                client,
                trigger="heartbeat",
                snapshot=snapshot,
            )

    @staticmethod
    def _require_dead_man_ack(
        response: OkxDemoResponse,
        *,
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        if not response.action_ok or len(response.data) != 1:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_dead_man_heartbeat_rejected:"
                + (
                    ";".join(response.action_errors)
                    or response.code
                    or response.message
                    or "ack_missing"
                )
            )
        row = response.data[0]
        if not isinstance(row, Mapping):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_dead_man_ack_schema_invalid"
            )
        trigger_time = str(row.get("triggerTime") or "")
        received_time = str(row.get("ts") or "")
        tag = str(row.get("tag") or "")
        if (
            not trigger_time.isdigit()
            or not received_time.isdigit()
            or tag != OKX_DEMO_PAPER_ORDER_TAG
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_dead_man_ack_schema_invalid"
            )
        if timeout_seconds == 0:
            if trigger_time != "0":
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_dead_man_disarm_not_confirmed"
                )
        elif trigger_time == "0":
            raise OkxDemoPaperRuntimeError(
                "okx_demo_dead_man_arm_not_confirmed"
            )
        return row

    def _dead_man_loop(self) -> None:
        try:
            while not self._stop_event.wait(self.config.dead_man_heartbeat_seconds):
                with self._lock:
                    client = self._client
                    runtime = self._state["runtime"]
                    active = runtime.get("active") is True
                    worker_required = (
                        runtime.get("authoritative_liveness_worker_required")
                        is True
                    )
                    worker_missing = worker_required and not (
                        self._thread is not None and self._thread.is_alive()
                    )
                    recovery = _mapping(runtime.get("worker_recovery"))
                    attempts = int(recovery.get("attempts") or 0)
                    recovery_pending = (
                        str(recovery.get("status") or "")
                        in {"pending", "retrying", "restarting"}
                        and attempts < OKX_DEMO_TRANSIENT_RECOVERY_MAX_ATTEMPTS
                    )
                if not active or client is None:
                    return
                should_recover = False
                recovery_fault = ""
                with self._lock:
                    dead_man = _mapping(
                        self._state["risk_control"].get("dead_man")
                    )
                    expired = (
                        dead_man.get("armed") is True
                        and not self._write_path_is_trusted()
                    )
                    if worker_missing or recovery_pending:
                        should_recover = True
                        recovery_fault = str(
                            dead_man.get("last_error")
                            or "okx_demo_authoritative_liveness_worker_stopped"
                        )
                    elif expired:
                        reason = "okx_demo_dead_man_expired_before_renewal"
                        self._state["risk_control"]["write_path_trusted"] = False
                        self._state["risk_control"]["dead_man"][
                            "last_error"
                        ] = reason
                        self._enter_cancel_only(reason, active=True)
                        self._append_safety_alert(reason)
                        self._append_event(
                            "dead_man_expired",
                            {"error": reason, "renewal_attempted": False},
                        )
                        self._persist_state()
                        return
                if should_recover:
                    if self._attempt_transient_recovery(fault=recovery_fault):
                        continue
                    with self._lock:
                        attempts = int(
                            _mapping(
                                self._state["runtime"].get("worker_recovery")
                            ).get("attempts")
                            or 0
                        )
                    if attempts < OKX_DEMO_TRANSIENT_RECOVERY_MAX_ATTEMPTS:
                        continue
                    return
                try:
                    self._renew_dead_man_once(client)
                except Exception as exc:
                    with self._lock:
                        reason = (
                            "okx_demo_dead_man_heartbeat_unknown:"
                            f"{_safe_error(exc)}"
                        )
                        self._state["risk_control"]["write_path_trusted"] = False
                        self._state["risk_control"]["dead_man"]["last_error"] = reason
                        self._enter_cancel_only(reason, active=True)
                        self._append_safety_alert(reason)
                        self._append_event("dead_man_heartbeat_failed", {"error": reason})
                        self._persist_state()
                    if _is_transient_liveness_error(exc):
                        if self._attempt_transient_recovery(fault=reason):
                            continue
                        with self._lock:
                            attempts = int(
                                _mapping(
                                    self._state["runtime"].get("worker_recovery")
                                ).get("attempts")
                                or 0
                            )
                        if attempts < OKX_DEMO_TRANSIENT_RECOVERY_MAX_ATTEMPTS:
                            continue
                    return
        finally:
            # The normal stop path has already made the runtime inactive.  Any
            # other exit loses renewal authority and therefore cannot retain a
            # previously cached opening permission.
            with self._lock:
                dead_man = self._state["risk_control"]["dead_man"]
                dead_man["heartbeat_thread_alive"] = False
                dead_man["watchdog_renews_dead_man"] = False
                if (
                    self._state["runtime"].get("active") is True
                    and self._state["runtime"].get(
                        "authoritative_liveness_required"
                    ) is True
                    and not self._stop_event.is_set()
                    and (
                        self._state["runtime"].get("opening_allowed") is True
                        or self._state["risk_control"].get("write_path_trusted")
                        is True
                    )
                ):
                    reason = "okx_demo_authoritative_liveness_dead_man_stopped"
                    self._state["risk_control"]["write_path_trusted"] = False
                    dead_man["last_error"] = reason
                    self._enter_cancel_only(reason, active=True)
                    self._append_event(
                        "authoritative_liveness_dead_man_stopped",
                        {"error": reason},
                    )
                self._persist_state()

    def _write_path_is_trusted(self) -> bool:
        risk = self._state.get("risk_control", {})
        if risk.get("write_path_trusted") is not True:
            return False
        last_ack = _parse_utc(
            _mapping(risk.get("dead_man")).get("last_ack_utc")
        )
        if last_ack is None:
            return False
        if self._clock().astimezone(timezone.utc) - last_ack > timedelta(
            seconds=self.config.dead_man_timeout_seconds
        ):
            return False
        return not self._authoritative_liveness_blockers(
            self._state,
            worker_alive=(
                self._thread is not None and self._thread.is_alive()
            ),
            dead_man_thread_alive=(
                self._dead_man_thread is not None
                and self._dead_man_thread.is_alive()
            ),
        )

    def _authoritative_renewal_owner(self, *, epoch: int) -> dict[str, Any]:
        return {
            "nonce": self._fault_drill_lock_nonce,
            "process_id": os.getpid(),
            "process_create_time": (
                _canonical_windows_process_create_time(os.getpid()) or ""
            ),
            "epoch": int(epoch),
        }

    def _authoritative_liveness_blockers(
        self,
        state: Mapping[str, Any],
        *,
        worker_alive: bool | None = None,
        dead_man_thread_alive: bool | None = None,
    ) -> list[str]:
        runtime = _mapping(state.get("runtime"))
        if (
            runtime.get("active") is not True
            or runtime.get("authoritative_liveness_required") is not True
        ):
            return []
        dead_man = _mapping(_mapping(state.get("risk_control")).get("dead_man"))
        blockers: list[str] = []
        now = self._clock().astimezone(timezone.utc)
        dead_man_timeout = timedelta(
            seconds=self.config.dead_man_timeout_seconds
        )
        worker_progress_timeout = timedelta(
            seconds=OKX_DEMO_WORKER_PROGRESS_TTL_SECONDS
        )
        worker_required = (
            runtime.get("authoritative_liveness_worker_required") is True
        )
        if worker_required:
            heartbeat = _parse_utc(runtime.get("last_heartbeat_utc"))
            if (
                heartbeat is None
                or now - heartbeat > worker_progress_timeout
            ):
                blockers.append(
                    "okx_demo_authoritative_liveness_worker_heartbeat_stale"
                )
        ack = _parse_utc(dead_man.get("last_ack_utc"))
        if ack is None or now - ack > dead_man_timeout:
            blockers.append("okx_demo_authoritative_liveness_dead_man_ack_stale")
        if dead_man.get("armed") is not True:
            blockers.append("okx_demo_authoritative_liveness_dead_man_unarmed")
        if dead_man.get("watchdog_renews_dead_man") is not True:
            blockers.append("okx_demo_authoritative_liveness_renewal_disabled")
        observed_dead_man_alive = (
            dead_man.get("heartbeat_thread_alive")
            if dead_man_thread_alive is None
            else dead_man_thread_alive
        )
        if observed_dead_man_alive is not True:
            blockers.append("okx_demo_authoritative_liveness_renewal_thread_dead")
        if worker_required:
            observed_worker_alive = (
                runtime.get("worker_alive")
                if worker_alive is None
                else worker_alive
            )
            if observed_worker_alive is not True:
                blockers.append("okx_demo_authoritative_liveness_worker_dead")
        owner = _mapping(dead_man.get("renewal_owner"))
        epoch = runtime.get("authoritative_liveness_epoch")
        expected = self._authoritative_renewal_owner(
            epoch=int(epoch) if isinstance(epoch, int) else -1
        )
        if (
            not owner
            or owner.get("nonce") != expected["nonce"]
            or owner.get("process_id") != expected["process_id"]
            or owner.get("epoch") != expected["epoch"]
            or (
                expected["process_create_time"]
                and owner.get("process_create_time")
                != expected["process_create_time"]
            )
        ):
            blockers.append("okx_demo_authoritative_liveness_renewal_owner_mismatch")
        return _dedupe(blockers)

    def _apply_authoritative_liveness_to_status(
        self,
        state: dict[str, Any],
    ) -> None:
        blockers = self._authoritative_liveness_blockers(state)
        if not blockers:
            return
        runtime = _mapping(state.get("runtime"))
        risk = _mapping(state.get("risk_control"))
        if runtime.get("active") is not True:
            return
        state["runtime"].update(
            {
                "opening_allowed": False,
                "cancel_only": True,
                "status": "cancel_only",
                "last_error": blockers[0],
                "blockers": _dedupe(
                    [*runtime.get("blockers", []), *blockers]
                ),
            }
        )
        state["risk_control"]["mode"] = OKX_DEMO_RISK_MODE_FROZEN
        state["risk_control"]["write_path_trusted"] = False
        state["risk_control"]["reason"] = blockers[0]
        state["risk_control"]["dead_man"]["last_error"] = blockers[0]

    def _disarm_dead_man_if_safe(
        self,
        client: OkxDemoClient | None,
        *,
        stop_query_current: bool = False,
    ) -> list[str]:
        if client is None:
            return ["okx_demo_dead_man_disarm_client_missing"]
        exchange = self._state.get("exchange", {})
        durable_intents = _mapping(
            self._state.get("risk_control", {}).get("pending_order_intents")
        )
        durable_intents_terminal = all(
            isinstance(row, Mapping)
            and str(row.get("status") or "")
            in OKX_DEMO_TERMINAL_INTENT_STATUSES
            for row in durable_intents.values()
        )
        safe = (
            _gross_position_contracts(exchange.get("positions", [])) == 0
            and not exchange.get("pending_orders", [])
            and not exchange.get("pending_algo_orders", [])
            and not _mapping(
                self._state.get("risk_control", {}).get("active_protection")
            )
            and durable_intents_terminal
            and self._state.get("ledger_reconciliation", {}).get("status")
            == "reconciled"
            and self._state.get("ledger_reconciliation", {}).get(
                "current_state_exchange_snapshot_match"
            )
            is True
            and stop_query_current
        )
        if not safe:
            return ["okx_demo_dead_man_remains_armed_stop_state_not_proven_safe"]
        try:
            response = self._dispatch_control_action(
                action=RuntimeAction.DEAD_MAN,
                client=client,
                snapshot=dict(_mapping(exchange)),
                control_key="disarm",
                callback=lambda _intent: client.cancel_all_after(
                    timeout_seconds=0,
                    tag=OKX_DEMO_PAPER_ORDER_TAG,
                ),
            )
            if not isinstance(response, OkxDemoResponse):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_execution_boundary_dead_man_receipt_invalid"
                )
            self._require_dead_man_ack(response, timeout_seconds=0)
        except Exception as exc:
            return [f"okx_demo_dead_man_disarm_unknown:{_safe_error(exc)}"]
        self._state["risk_control"]["dead_man"]["armed"] = False
        self._state["risk_control"]["write_path_trusted"] = False
        return []

    def _enter_cancel_only(self, reason: str, *, active: bool) -> None:
        self._state["runtime"].update(
            {
                "active": active,
                "opening_allowed": False,
                "cancel_only": True,
                "status": "cancel_only" if active else "blocked_fail_closed",
                "last_error": reason,
                "blockers": _dedupe([*self._state["runtime"].get("blockers", []), reason]),
            }
        )
        if "risk_control" in self._state:
            self._set_risk_mode(OKX_DEMO_RISK_MODE_FROZEN, reason)

    def _on_private_ws_disconnect(self, reason: str) -> None:
        safe_reason = f"okx_demo_private_ws:{str(reason)[:160]}"
        with self._lock:
            self._private_ws_generation += 1
            ledger_ok = (
                self._state.get("ledger_reconciliation", {}).get("status")
                == "reconciled"
                and self._state.get("ledger_reconciliation", {}).get(
                    "current_state_exchange_snapshot_match"
                )
                is True
            )
            unresolved_intent = any(
                isinstance(row, Mapping)
                and str(row.get("status") or "")
                in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
                for row in _mapping(
                    self._state.get("risk_control", {}).get(
                        "pending_order_intents"
                    )
                ).values()
            )
            mode = (
                OKX_DEMO_RISK_MODE_REDUCING
                if self._write_path_is_trusted()
                and ledger_ok
                and not unresolved_intent
                else OKX_DEMO_RISK_MODE_FROZEN
            )
            self._set_risk_mode(mode, safe_reason)
            self._state["runtime"]["last_error"] = safe_reason
            self._state["runtime"]["blockers"] = _dedupe(
                [*self._state["runtime"].get("blockers", []), safe_reason]
            )
            self._state["private_ws"].update(
                {
                    "status": "disconnected",
                    "connected": False,
                    "listener_alive": False,
                    "opening_allowed_after_reconciliation": False,
                    "controller_generation": self._private_ws_generation,
                    "blockers": _dedupe(
                        [
                            *self._state["private_ws"].get("blockers", []),
                            safe_reason,
                        ]
                    ),
                }
            )
            self._append_event(
                "private_ws_disconnected_risk_degraded",
                {
                    "reason": safe_reason,
                    "opening_allowed": False,
                    "cancel_only": True,
                    "risk_mode": mode,
                },
            )
            self._persist_state()

    def _on_private_ws_reconciled(self, receipt: Mapping[str, Any]) -> None:
        with self._lock:
            self._private_ws_generation += 1
            retained = [
                blocker
                for blocker in self._state["runtime"].get("blockers", [])
                if not str(blocker).startswith("okx_demo_private_ws:")
            ]
            self._state["runtime"]["blockers"] = retained
            refreshed_receipt = dict(receipt)
            refreshed_receipt["controller_generation"] = (
                self._private_ws_generation
            )
            self._state["private_ws"] = json.loads(
                json.dumps(refreshed_receipt)
            )
            if self._state["runtime"]["active"]:
                pending_reason = (
                    "okx_demo_private_ws_reconciled_full_reconciliation_pending"
                )
                self._state["runtime"]["blockers"] = _dedupe(
                    [*retained, pending_reason]
                )
                self._set_risk_mode(
                    OKX_DEMO_RISK_MODE_FROZEN,
                    pending_reason,
                )
            self._append_event(
                "private_ws_reconciled",
                {
                    "source_head": receipt.get("source_head"),
                    "runtime_version": receipt.get("runtime_version"),
                    "opening_allowed_after_reconciliation": receipt.get(
                        "opening_allowed_after_reconciliation"
                    )
                    is True,
                    "credentials_redacted": True,
                    "promotion_evidence_ready": False,
                },
            )
            self._persist_state()

    def _append_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        normalized = json.loads(json.dumps(payload, default=str))
        run_id = self._state["runtime"].get("run_id", "")
        key = hashlib.sha256(
            json.dumps([run_id, event_type, normalized], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        event = self._runtime_store.append(
            event_type=event_type,
            payload=normalized,
            state_after=self._durable_state_snapshot(),
            idempotency_key=key,
            timestamp_utc=_iso(self._clock()),
            run_id=run_id,
            safety=self._state["safety"],
        )
        event_id = str(
            event.get("event_id")
            or event.get("event_hash")
            or event.get("idempotency_key")
            or ""
        )
        if not any(
            str(
                _mapping(row).get("event_id")
                or _mapping(row).get("event_hash")
                or _mapping(row).get("idempotency_key")
                or ""
            )
            == event_id
            for row in self._state["events"]
        ):
            self._state["events"] = [event, *self._state["events"]][:100]

    def _persist_state(self) -> None:
        self._runtime_store.checkpoint(self._durable_state_snapshot())

    def _apply_owned_id_restore(
        self,
        request: OkxDemoPaperStartRequest,
    ) -> None:
        configured_values = (
            self.config.owned_id_restore_archive_root,
            self.config.owned_id_restore_current_head,
            self.config.owned_id_restore_source_head,
            self.config.owned_id_restore_account_identity,
            self.config.owned_id_restore_credential_identity,
            self.config.owned_id_restore_client_order_namespace,
        )
        requested_values = (
            request.owned_id_restore_archive_root,
            request.owned_id_restore_current_head,
            request.owned_id_restore_source_head,
            request.owned_id_restore_account_identity,
            request.owned_id_restore_credential_identity,
            request.owned_id_restore_client_order_namespace,
        )
        if configured_values[0] is not None and requested_values[0] is not None:
            if any(
                str(configured) != str(requested)
                for configured, requested in zip(configured_values, requested_values)
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_owned_id_restore_request_config_mismatch"
                )
        effective_values = tuple(
            requested if str(requested).strip() else configured
            for requested, configured in zip(requested_values, configured_values)
        )
        archive_root = effective_values[0]
        if archive_root is None:
            return
        current_head = _repo_head(self.config.repo_root)
        effective_current_head = str(effective_values[1] or "")
        effective_source_head = str(effective_values[2] or "")
        effective_account_identity = str(effective_values[3] or "")
        effective_credential_identity = str(effective_values[4] or "")
        effective_namespace = str(effective_values[5] or "")
        if effective_current_head != current_head:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_current_head_mismatch"
            )
        projection = _build_owned_id_restore_projection(
            archive_root=archive_root,
            repo_root=self.config.repo_root,
            current_head=current_head,
            source_head=effective_source_head,
            account_identity=effective_account_identity,
            credential_identity=effective_credential_identity,
            client_order_namespace=effective_namespace,
            credential_service=self.config.credential_service,
        )
        with self._lock:
            self._owned_client_order_ids.update(
                str(value)
                for value in projection.get("owned_client_order_ids", [])
                if str(value)
            )
            self._state["risk_control"]["owned_id_restore"] = json.loads(
                json.dumps(projection, default=str)
            )
            self._append_event(
                "owned_id_restore_applied",
                {
                    "archive_id": projection["archive_id"],
                    "archive_manifest_sha256": projection[
                        "archive_manifest_sha256"
                    ],
                    "archive_verification_sha256": projection[
                        "archive_verification_sha256"
                    ],
                    "source_snapshot_sha256": projection[
                        "source_snapshot_sha256"
                    ],
                    "source_head": projection["source_head"],
                    "current_head": projection["current_head"],
                    "environment": projection["environment"],
                    "instrument_id": projection["instrument_id"],
                    "account_identity": projection["account_identity"],
                    "credential_identity": projection["credential_identity"],
                    "client_order_namespace": projection[
                        "client_order_namespace"
                    ],
                    "owned_triples": projection["owned_triples"],
                    "identity_only": True,
                    "opening_allowed": False,
                    "position_restored": False,
                    "order_capability_restored": False,
                },
            )
            self._persist_state()

    @staticmethod
    def _owned_client_order_ids_from_recovered_events(
        events: Sequence[Mapping[str, Any]],
    ) -> set[str]:
        """Recover only order identities proven by the append-only OMS ledger.

        A persisted intent is not enough to trust a private-stream fill after a
        restart: it may have been written before the exchange POST and therefore
        may never have existed at the venue.  Require both the lifecycle event
        and a committed ledger UOW to mention the same client order id.  The
        runtime store has already verified the hash chain before this helper is
        called, so this restores known local evidence without widening the
        unknown-fill fail-closed guard.
        """
        lifecycle_ids_by_run: dict[str, set[str]] = {}
        ledger_ids_by_run: dict[str, set[str]] = {}
        for event in events:
            event_type = str(event.get("event_type") or "")
            run_id = str(event.get("run_id") or "")
            payload = _mapping(event.get("payload"))
            if event_type == "order_lifecycle":
                lifecycle_ids = lifecycle_ids_by_run.setdefault(run_id, set())
                oms = _mapping(payload.get("oms"))
                client_order_id = str(oms.get("client_order_id") or "")
                if client_order_id:
                    lifecycle_ids.add(client_order_id)
                fills = payload.get("fills")
                if isinstance(fills, Sequence) and not isinstance(fills, (str, bytes)):
                    for fill in fills:
                        fill_id = str(_mapping(fill).get("client_order_id") or "")
                        if fill_id:
                            lifecycle_ids.add(fill_id)
            elif event_type == "ledger_uow_committed":
                ledger_ids = ledger_ids_by_run.setdefault(run_id, set())
                order_ledger = _mapping(payload.get("order_ledger"))
                orders = order_ledger.get("orders")
                if isinstance(orders, Sequence) and not isinstance(orders, (str, bytes)):
                    for order in orders:
                        order_id = str(_mapping(order).get("client_order_id") or "")
                        if order_id:
                            ledger_ids.add(order_id)
                fills = payload.get("fill_ledger")
                if isinstance(fills, Sequence) and not isinstance(fills, (str, bytes)):
                    for fill in fills:
                        fill_id = str(_mapping(fill).get("client_order_id") or "")
                        if fill_id:
                            ledger_ids.add(fill_id)
        owned: set[str] = set()
        for run_id, lifecycle_ids in lifecycle_ids_by_run.items():
            owned.update(lifecycle_ids & ledger_ids_by_run.get(run_id, set()))
        return owned

    @staticmethod
    def _hosted_oco_terminal_exit_ids_from_recovered_events(
        events: Sequence[Mapping[str, Any]],
        *,
        current_head: str,
        repo_root: Path | None = None,
    ) -> set[str]:
        """Restore only a hash-chained hosted-OCO projection on verified ancestry."""

        owned: set[str] = set()
        resolved_repo_root = Path(repo_root or Path.cwd()).resolve()
        for event in events:
            if str(event.get("event_type") or "") != (
                "hosted_oco_terminal_exit_ownership_projection"
            ):
                continue
            payload = _mapping(event.get("payload"))
            supplied_digest = str(payload.get("identity_digest_sha256") or "")
            entry = _mapping(payload.get("entry"))
            oco = _mapping(payload.get("oco"))
            exit_identity = _mapping(payload.get("exit"))
            if not (
                set(payload)
                == {
                    "schema_version",
                    "binding_source",
                    "incident_source_head",
                    "recovery_code_head",
                    "failed_receipt_sha256",
                    "flat_identity_sha256",
                    "snapshot_sha256",
                    "entry",
                    "oco",
                    "exit",
                    "identity_digest_sha256",
                }
                and
                payload.get("schema_version")
                == "okx_demo_hosted_oco_terminal_exit_ownership_v1"
                and payload.get("binding_source")
                in {
                    "canonical_incident_recovery_binding",
                    "immutable_flat_hosted_exit_receipt_bundle",
                }
                and re.fullmatch(
                    r"[0-9a-f]{40}",
                    str(payload.get("recovery_code_head") or ""),
                )
                and re.fullmatch(
                    r"[0-9a-f]{40}",
                    str(payload.get("incident_source_head") or ""),
                )
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(payload.get("failed_receipt_sha256") or ""),
                )
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(payload.get("flat_identity_sha256") or ""),
                )
                and re.fullmatch(r"[0-9a-f]{64}", str(payload.get("snapshot_sha256") or ""))
                and re.fullmatch(r"[0-9a-f]{64}", supplied_digest)
                and _hosted_oco_terminal_exit_identity_digest(payload)
                == supplied_digest
                and entry
                == {
                    "client_order_id": _FRESH_STATE_EMERGENCY_FIXED_IDENTITY[
                        "entry_cl_ord_id"
                    ],
                    "order_id": _FRESH_STATE_EMERGENCY_FIXED_IDENTITY[
                        "entry_ord_id"
                    ],
                    "fill_id": str(entry.get("fill_id") or ""),
                }
                and str(entry.get("fill_id") or "")
                and oco
                == {
                    "algo_id": _FRESH_STATE_EMERGENCY_FIXED_IDENTITY["oco_algo_id"],
                    "algo_client_order_id": _FRESH_STATE_EMERGENCY_FIXED_IDENTITY[
                        "oco_algo_cl_ord_id"
                    ],
                    "reduce_only": True,
                    "side": "sell",
                    "position_side": "long",
                    "size": "0.01",
                }
                and re.fullmatch(
                    r"O[0-9]{10,}",
                    str(exit_identity.get("client_order_id") or ""),
                )
                and exit_identity.get("state") == "filled"
                and exit_identity.get("order_type") == "market"
                and exit_identity.get("reduce_only") is True
                and exit_identity.get("side") == "sell"
                and exit_identity.get("position_side") == "long"
                and exit_identity.get("size") == "0.01"
                and str(exit_identity.get("order_id") or "")
                and str(exit_identity.get("fill_id") or "")
            ):
                continue
            event_recovery_head = str(payload.get("recovery_code_head") or "")
            incident_source_head = str(payload.get("incident_source_head") or "")
            if not (
                _bounded_git_is_ancestor(
                    resolved_repo_root,
                    incident_source_head,
                    event_recovery_head,
                )
                and (
                    event_recovery_head == current_head
                    or _bounded_git_is_ancestor(
                        resolved_repo_root,
                        event_recovery_head,
                        current_head,
                    )
                )
            ):
                continue
            owned.add(str(entry["client_order_id"]))
            owned.add(str(exit_identity["client_order_id"]))
        return owned

    def _recover_previous_state(self) -> None:
        recovered = self._runtime_store.recover()
        if not recovered.state and not recovered.blockers:
            return
        previous = recovered.state
        previous_runtime = _mapping(previous.get("runtime"))
        persisted_identity = _mapping(
            previous_runtime.get("account_identity")
            or _mapping(
                _mapping(previous.get("exchange")).get("account")
            ).get("identity")
        )
        # A persisted hash is reusable only when its provenance is the
        # account-config projection introduced by this contract.  Legacy
        # records without provenance remain unknown and require refresh.
        if (
            is_authoritative_account_identity_hash(persisted_identity.get("hash"))
            and persisted_identity.get("source") == ACCOUNT_IDENTITY_HASH_SOURCE
            and str(persisted_identity.get("captured_at_utc") or "").strip()
        ):
            self._set_authoritative_account_identity(persisted_identity)
            self._state["runtime"]["account_identity"] = self.account_identity_projection()
        previous_run_id = str(previous_runtime.get("run_id") or "")
        if previous_run_id:
            self._state["runtime"]["run_id"] = previous_run_id
        try:
            previous_sequence = int(previous_runtime.get("order_sequence") or 0)
        except (TypeError, ValueError):
            previous_sequence = 0
        self._sequence = max(0, previous_sequence)
        self._state["runtime"]["order_sequence"] = self._sequence
        previous_start_operation = _mapping(previous_runtime.get("start_operation"))
        historical_start_blockers = self._historical_start_operation_blockers(
            previous_start_operation
        )
        recovered_historical_start_operation: dict[str, Any] | None = None
        if previous_start_operation:
            historical_reasons = [
                *list(previous_start_operation.get("historical_reason_codes") or []),
                "runtime_identity_changed",
            ]
            try:
                if str(previous_start_operation.get("source_head") or "") != _repo_head(self.config.repo_root):
                    historical_reasons.append("source_head_changed")
            except Exception:
                historical_reasons.append("source_head_unknown")
            if str(previous_start_operation.get("risk_profile") or "") != self._risk_profile:
                historical_reasons.append("risk_profile_changed")
            if str(previous_start_operation.get("expected_leverage") or "") != self._expected_leverage:
                historical_reasons.append("expected_leverage_changed")
            if str(previous_start_operation.get("account_identity_hash") or "") != self._account_identity_hash:
                historical_reasons.append("account_identity_changed")
            self._state["runtime"]["start_operation"] = json.loads(
                json.dumps(dict(previous_start_operation))
            )
            self._state["runtime"]["start_operation"].update(
                {
                    "current_attempt": False,
                    "historical": True,
                    "historical_reason_codes": list(dict.fromkeys(historical_reasons)),
                }
            )
            recovered_historical_start_operation = json.loads(
                json.dumps(dict(self._state["runtime"]["start_operation"]))
            )
            nested_attempt = dict(
                _mapping(self._state["runtime"]["start_operation"].get("start_attempt"))
            )
            if nested_attempt:
                nested_attempt.update(
                    {
                        "current_attempt": False,
                        "historical": True,
                        "historical_reason_codes": list(dict.fromkeys(historical_reasons)),
                    }
                )
                self._state["runtime"]["start_operation"]["start_attempt"] = nested_attempt
        previous_history = previous_runtime.get("start_operation_history")
        history_rows: list[dict[str, Any]] = []
        if isinstance(previous_history, Sequence) and not isinstance(previous_history, (str, bytes)):
            history_rows = [
                json.loads(json.dumps(dict(row)))
                for row in previous_history
                if isinstance(row, Mapping)
            ]
        if recovered_historical_start_operation:
            operation_id = str(recovered_historical_start_operation.get("operation_id") or "")
            if operation_id and not any(
                str(row.get("operation_id") or "") == operation_id
                for row in history_rows
            ):
                history_rows.append(recovered_historical_start_operation)
        self._state["runtime"]["start_operation_history"] = history_rows[-32:]
        # The serving process owns a fresh opaque identity.  Persisted runtime
        # facts are retained as history but can never become current merely by
        # being reloaded from disk.
        self._state["runtime"]["runtime_identity"] = self._runtime_identity
        worker_ready = _mapping(
            previous_runtime.get("fault_drill_worker_ready")
        )
        if worker_ready:
            self._state["runtime"]["fault_drill_worker_ready"] = json.loads(
                json.dumps(dict(worker_ready))
            )
        self._state["exchange"] = previous.get("exchange", self._state["exchange"])
        self._state["ledger_reconciliation"] = previous.get(
            "ledger_reconciliation",
            self._state["ledger_reconciliation"],
        )
        self._state["account_risk_facts"] = previous.get(
            "account_risk_facts",
            self._state["account_risk_facts"],
        )
        self._state["account_risk_last_valid_fact"] = previous.get(
            "account_risk_last_valid_fact",
            self._state["account_risk_last_valid_fact"],
        )
        self._state["account_facts_approval"] = previous.get(
            "account_facts_approval",
            self._state["account_facts_approval"],
        )
        self._state["reviewed_drawdown_policy"] = previous.get(
            "reviewed_drawdown_policy",
            self._state["reviewed_drawdown_policy"],
        )
        self._state["observation"] = previous.get(
            "observation",
            self._state["observation"],
        )
        previous_risk = previous.get("risk_control")
        if isinstance(previous_risk, Mapping):
            self._state["risk_control"] = json.loads(
                json.dumps(dict(previous_risk))
            )
            risk_control = self._state["risk_control"]
            previous_risk_reason = str(risk_control.get("reason") or "")
            filtered_risk_reasons = self._filter_recovered_policy_blockers(
                previous_risk_reason.split(";")
            )
            filtered_risk_reasons = self._drop_historical_start_operation_blockers(
                filtered_risk_reasons,
                historical_start_blockers,
            )
            if previous_risk_reason and not filtered_risk_reasons:
                filtered_risk_reasons = [
                    "okx_demo_previous_policy_state_historical"
                ]
            if previous_risk_reason:
                risk_control["reason"] = ";".join(filtered_risk_reasons)
            risk_control["blockers"] = self._filter_recovered_policy_blockers(
                risk_control.get("blockers") or []
            )
            risk_control["blockers"] = self._drop_historical_start_operation_blockers(
                risk_control.get("blockers") or [],
                historical_start_blockers,
            )
            pending_intents = _mapping(previous_risk.get("pending_order_intents"))
            self._owned_client_order_ids.update(str(key) for key in pending_intents)
            policy_payload = previous_risk.get("protection_policy")
            policy = ServerSideProtectionPolicy.from_mapping(policy_payload)
            if not policy.validate():
                self._protection_policy = policy
        self._state["audit"] = list(previous.get("audit", []))[:100]
        self._state["events"] = list(reversed(recovered.events[-100:]))
        self._owned_client_order_ids.update(
            self._owned_client_order_ids_from_recovered_events(recovered.events)
        )
        if any(
            str(event.get("event_type") or "")
            == "hosted_oco_terminal_exit_ownership_projection"
            for event in recovered.events
        ):
            self._owned_client_order_ids.update(
                self._hosted_oco_terminal_exit_ids_from_recovered_events(
                    recovered.events,
                    current_head=_repo_head(self.config.repo_root),
                    repo_root=self.config.repo_root,
                )
            )
        previous_active_raw = previous_runtime.get("active")
        previous_opening_allowed_raw = previous_runtime.get("opening_allowed")
        previous_cancel_only_raw = previous_runtime.get("cancel_only")
        previous_runtime_flags_strict = all(
            isinstance(value, bool)
            for value in (
                previous_active_raw,
                previous_opening_allowed_raw,
                previous_cancel_only_raw,
            )
        )
        previous_active = previous_active_raw is True
        previous_opening_allowed = previous_opening_allowed_raw is True
        previous_cancel_only = previous_cancel_only_raw is True
        previous_risk_mode = str(
            _mapping(previous.get("risk_control")).get("mode") or ""
        )
        previous_safe_cancel_only = (
            not previous_active
            and not previous_opening_allowed
            and previous_cancel_only
            and previous_risk_mode == OKX_DEMO_RISK_MODE_FROZEN
        )
        previous_clean_stopped = (
            not previous_active
            and not previous_opening_allowed
            and not previous_cancel_only
            and previous_risk_mode == OKX_DEMO_RISK_MODE_FROZEN
        )
        previous_runtime_blockers_value = previous_runtime.get("blockers")
        previous_runtime_blockers = (
            [
                str(value)
                for value in previous_runtime_blockers_value
                if str(value)
            ]
            if isinstance(previous_runtime_blockers_value, Sequence)
            and not isinstance(previous_runtime_blockers_value, (str, bytes))
            else []
        )
        previous_runtime_blockers = self._filter_recovered_policy_blockers(
            previous_runtime_blockers
        )
        previous_runtime_blockers = self._drop_historical_start_operation_blockers(
            previous_runtime_blockers,
            historical_start_blockers,
        )
        recovery_blockers = list(recovered.blockers)
        if not previous_runtime_flags_strict:
            recovery_blockers.append(
                "okx_demo_previous_runtime_flags_not_strict_boolean"
            )
        if previous_active:
            recovery_blockers.append("okx_demo_paper_previous_runtime_not_cleanly_stopped")
        if previous_opening_allowed and not previous_active:
            recovery_blockers.append(
                "okx_demo_previous_runtime_opening_allowed_on_restart"
            )
        if previous_cancel_only and not previous_safe_cancel_only:
            recovery_blockers.append("okx_demo_previous_cancel_only_state_invalid")
        if previous_risk_mode != OKX_DEMO_RISK_MODE_FROZEN and not previous_clean_stopped:
            recovery_blockers.append("okx_demo_previous_runtime_risk_mode_not_frozen")
        if any(
            str(row.get("status") or "")
            in OKX_DEMO_UNRESOLVED_INTENT_STATUSES
            for row in _mapping(
                self._state.get("risk_control", {}).get(
                    "pending_order_intents"
                )
            ).values()
            if isinstance(row, Mapping)
        ):
            recovery_blockers.append(
                "okx_demo_previous_ambiguous_order_requires_clordid_reconciliation"
            )
        if previous_safe_cancel_only and not recovery_blockers:
            restore_reason = "okx_demo_previous_cancel_only_state_restored"
            restored_blockers = list(
                dict.fromkeys([*previous_runtime_blockers, restore_reason])
            )
            self._state["runtime"].update(
                {
                    "active": False,
                    "opening_allowed": False,
                    "cancel_only": True,
                    "status": "blocked_fail_closed",
                    "worker_alive": False,
                    "last_error": restore_reason,
                    "blockers": restored_blockers,
                }
            )
            self._set_risk_mode(OKX_DEMO_RISK_MODE_FROZEN, restore_reason)
            self._state["risk_control"]["write_path_trusted"] = False
            self._state["risk_control"].setdefault("dead_man", {}).update(
                {
                    "armed": False,
                    "heartbeat_thread_alive": False,
                    "watchdog_renews_dead_man": False,
                }
            )
            self._state["safety"].update(
                {
                    "formal_paper_runtime_started": False,
                    "live_order_allowed": False,
                    "real_money_order_allowed": False,
                    "transfer_allowed": False,
                    "withdraw_allowed": False,
                    "permission_upgrade_allowed": False,
                    "okx_demo_private_read_enabled": False,
                    "okx_demo_order_capability_enabled": False,
                    "okx_demo_cancel_capability_enabled": False,
                    "auto_start_on_backend_launch": False,
                }
            )
            return
        if recovery_blockers:
            self._state["risk_control"]["write_path_trusted"] = False
            self._state["risk_control"].setdefault("dead_man", {}).update(
                {
                    "armed": False,
                    "heartbeat_thread_alive": False,
                    "watchdog_renews_dead_man": False,
                }
            )
            self._state["runtime"].update(
                {
                    "status": "unclean_restart_fail_closed",
                    "cancel_only": True,
                    "opening_allowed": False,
                    "worker_alive": False,
                    "blockers": list(
                        dict.fromkeys(
                            [*previous_runtime_blockers, *recovery_blockers]
                        )
                    ),
                }
            )
            self._set_risk_mode(
                OKX_DEMO_RISK_MODE_FROZEN,
                ";".join(recovery_blockers),
            )

    def _refresh_observation_projection_from_ledger(self) -> None:
        """Restore cumulative/strict counters without appending evidence.

        The receipt ledger is the source of truth for completed Demo hours.
        This projection is deliberately read-only with respect to that
        ledger: it never backfills, rewrites, or marks a receipt successful.
        Strict latest-segment fields remain separate from the cumulative
        operator progress and continue to drive promotion gates.
        """
        ledger_path = (
            Path(self.config.output_dir)
            / "observation"
            / "hourly_observation_receipts.jsonl"
        )
        try:
            receipts = load_observation_receipt_ledger(ledger_path)
        except Exception as exc:
            with self._lock:
                observation = self._state["observation"]
                observation.update(
                    {
                        "cumulative_observation_hours": 0,
                        "cumulative_window_25h_complete": False,
                        "cumulative_blockers": [
                            "btc_demo_observation_receipt_ledger_unavailable"
                        ],
                    }
                )
                observation["blockers"] = list(
                    dict.fromkeys(
                        [
                            *list(observation.get("blockers") or []),
                            "btc_demo_observation_receipt_ledger_unavailable",
                        ]
                    )
                )
                self._state["runtime"]["last_error"] = _safe_error(exc)
            return
        if not receipts:
            return
        with self._lock:
            strategy = _mapping(self._state.get("strategy"))
            runtime = _mapping(self._state.get("runtime"))
        latest = receipts[-1]
        strategy_version = str(
            strategy.get("strategy_version")
            or latest.get("strategy_version")
            or ""
        )
        data_version = str(latest.get("data_version") or "")
        try:
            source_head = _repo_head(self.config.repo_root)
        except Exception:
            source_head = str(latest.get("source_head") or "")
        report = build_observation_window_report(
            receipts=receipts,
            current_head=source_head,
            current_strategy_version=strategy_version,
            current_data_version=data_version or None,
            current_runtime_version=OKX_DEMO_PAPER_RUNTIME_VERSION,
            run_id=str(runtime.get("run_id") or latest.get("runtime_run_id") or ""),
            generated_at_utc=self._clock(),
        )
        projection = {
            "observation_receipt_count": len(receipts),
            "consecutive_hours": report["observation_hours"],
            "window_complete": report["window_25h_complete"],
            "cumulative_observation_hours": report[
                "cumulative_observation_hours"
            ],
            "cumulative_window_25h_complete": report[
                "cumulative_window_25h_complete"
            ],
            "cumulative_blockers": list(report["cumulative_blockers"]),
            "ledger_hash": report["ledger_integrity"]["ledger_sha256"],
            "last_receipt_sha256": report["ledger_integrity"][
                "last_receipt_sha256"
            ],
            "last_observation_hour_utc": str(
                latest.get("observation_hour_utc") or ""
            ),
            "blockers": list(report["blockers"]),
            "promotion_evidence_ready": False,
        }
        with self._lock:
            self._state["observation"].update(projection)
            self._persist_state()

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": "okx_demo_paper_runtime_status_v1",
            "runtime_version": OKX_DEMO_PAPER_RUNTIME_VERSION,
            "environment": "OKX Demo",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "runtime": {
                "run_id": "",
                "runtime_identity": self._runtime_identity,
                "status": "stopped",
                "active": False,
                "opening_allowed": False,
                "cancel_only": False,
                "started_at_utc": "",
                "stopped_at_utc": "",
                "last_heartbeat_utc": "",
                "last_reconciled_at_utc": "",
                "last_processed_bar_close_utc": "",
                "last_error": "",
                "last_error_detail": {},
                "blockers": [],
                "worker_alive": False,
                "worker_generation": 0,
                "worker_recovery": {
                    "status": "not_required",
                    "attempts": 0,
                    "last_fault": "",
                    "last_error": "",
                    "last_recovered_at_utc": "",
                    "worker_generation": 0,
                },
                "authoritative_liveness_required": False,
                "authoritative_liveness_worker_required": False,
                "authoritative_liveness_epoch": 0,
                "orders_submitted": 0,
                "fills_observed": 0,
                "authorization_ticket": "",
                "order_sequence": 0,
                "account_identity": {
                    "hash": self._account_identity_hash,
                    "source": self._account_identity_source,
                    "captured_at_utc": self._account_identity_captured_at_utc,
                },
                "fault_drill_scenario": "",
                "fault_drill_entry_authorized": False,
                "fault_drill_recovery_state": "",
                "fault_drill_operator_acknowledged": False,
                "fault_drill_authoritative_receipt": {},
                "probe_diagnostics": [],
                "start_operation": {
                    "schema_version": START_ATTEMPT_SCHEMA_VERSION,
                    "operation_id": "",
                    "attempt_id": "",
                    "parent_operation_id": "",
                    "idempotency_key": "",
                    "request_fingerprint": "",
                    "state": "idle",
                    "phase": "idle",
                    "revision": 0,
                    "started_at_utc": "",
                    "updated_at_utc": "",
                    "deadline_utc": "",
                    "source_head": "",
                    "runtime_identity": self._runtime_identity,
                    "effective_policy_digest": "",
                    "risk_profile": self._risk_profile,
                    "expected_leverage": self._expected_leverage,
                    "account_identity_hash": self._account_identity_hash,
                    "current_attempt": False,
                    "historical": False,
                    "historical_reason_codes": [],
                    "actual_long_leverage": None,
                    "actual_short_leverage": None,
                    "owner": {"pid": 0, "nonce": "", "create_time_utc": ""},
                    "worker_generation": 0,
                    "incident": {"category": "none", "code": ""},
                    "blockers": [],
                    "terminal_error": "",
                    "post_counts": {"orders": 0, "cancels": 0, "dead_man": 0},
                },
                "start_operation_history": [],
                "fresh_state_emergency_exit": {
                    "status": "not_attempted",
                    "post_attempts": 0,
                    "client_order_id": "",
                    "final_flat": False,
                    "projection": {},
                    "owner_marker_audit": {},
                },
                "stop_and_flatten": {
                    "status": "not_attempted",
                    "post_attempts": 0,
                    "client_order_id": "",
                    "exchange_order_id": "",
                    "final_flat": False,
                    "algo_cleanup": {},
                    "authority": "broker_rest_private_ws_ledger",
                },
            },
            "risk_control": {
                "mode": OKX_DEMO_RISK_MODE_FROZEN,
                "reason": "runtime_not_started",
                "write_path_trusted": False,
                "protection_policy": {},
                "active_protection": {},
                "owned_attached_algos": {},
                "pending_order_intents": {},
                "incident_recovery_intents": {},
                "incident_algo_cancel_intents": {},
                "owned_id_restore": {
                    "enabled": False,
                    "identity_only": True,
                    "opening_allowed": False,
                    "position_restored": False,
                    "order_capability_restored": False,
                    "owned_triples": [],
                },
                "alerts": [],
                "dead_man": {
                    "tag": OKX_DEMO_PAPER_ORDER_TAG,
                    "timeout_seconds": self.config.dead_man_timeout_seconds,
                    "last_ack_utc": "",
                    "last_error": "",
                    "armed": False,
                    "heartbeat_thread_alive": False,
                    "watchdog_renews_dead_man": False,
                    "renewal_owner": {},
                },
            },
            "strategy": {},
            "session_contract": {
                "mode": "demo_first_continuous_session",
                "continuous_runner_supported": True,
                "startup_snapshot_reconciliation_required": True,
                "reconnect_snapshot_reconciliation_required": True,
                "shared_frozen_signal_interface": True,
                "second_strategy_implementation_created": False,
                "live_transport_connection_allowed": False,
                "full_30d_l2_persistence_required": False,
            },
            "limits": {
                "margin_mode": "isolated",
                "order_contracts": _text(OKX_DEMO_PAPER_CONTRACTS),
                "max_net_contracts": _text(OKX_DEMO_PAPER_MAX_NET_CONTRACTS),
                "max_notional_usdt": _text(OKX_DEMO_PAPER_MAX_NOTIONAL_USDT),
                "max_configured_leverage": _text(self.config.max_configured_leverage),
            },
            "signal": {},
            "market_data_ring": self._market_ring.summary(),
            "runtime_data_budget": {
                "policy": self.config.runtime_data_budget.to_dict(),
                "state": self.config.runtime_data_budget.evaluate(
                    runtime_data_bytes=0
                ),
                "quota_can_delete_protected_state": False,
            },
            "exchange": {
                "captured_at_utc": "",
                "account": {},
                "balance": {},
                "positions": [],
                "pending_orders": [],
                "pending_algo_orders": [],
                "orders": [],
                "fills": [],
                "bills": [],
                "fee_schedule": {},
                "funding": {},
                "ticker": {},
                "mark": {},
            },
            "audit": [],
            "events": [],
            "private_ws": {
                "status": "not_started",
                "connected": False,
                "listener_alive": False,
                "opening_allowed_after_reconciliation": False,
                "credentials_redacted": True,
                "promotion_evidence_ready": False,
                "probe_diagnostics": [],
            },
            "observation": {
                "observation_receipt_count": 0,
                "consecutive_hours": 0,
                "window_complete": False,
                "cumulative_observation_hours": 0,
                "cumulative_window_25h_complete": False,
                "cumulative_blockers": [
                    "btc_okx_native:25_hour_demo_observation_window_incomplete"
                ],
                "ledger_hash": "",
                "last_receipt_sha256": "",
                "last_observation_hour_utc": "",
                "blockers": [
                    "btc_okx_native:25_hour_demo_observation_window_incomplete"
                ],
                "promotion_evidence_ready": False,
            },
            "ledger_reconciliation": {
                "status": "not_observed",
                "current_state_exchange_snapshot_match": False,
                "funding_cashflow_reconciled": False,
                "last_funding_ledger_hash": "",
                "fixture": False,
                "promotion_evidence_ready": False,
            },
            "account_risk_facts": {
                "schema_version": "btc_account_drawdown_fact_v1",
                "status": "not_observed",
                "risk_eligible": False,
                "blockers": [
                    "explicit_baseline_required",
                    "external_cashflow_unknown",
                ],
            },
            "account_risk_last_valid_fact": {},
            "account_facts_approval": {},
            "reviewed_drawdown_policy": {},
            "safety": {
                "demo_environment_only": True,
                "formal_paper_runtime_started": False,
                "live_order_allowed": False,
                "real_money_order_allowed": False,
                "transfer_allowed": False,
                "withdraw_allowed": False,
                "permission_upgrade_allowed": False,
                "okx_demo_private_read_enabled": False,
                "okx_demo_order_capability_enabled": False,
                "okx_demo_cancel_capability_enabled": False,
                "auto_start_on_backend_launch": False,
            },
        }


def load_completed_btc_hourly_frame(db_path: Path, *, now: datetime) -> pd.DataFrame:
    path = Path(db_path).resolve()
    if not path.exists():
        raise OkxDemoPaperRuntimeError("okx_demo_paper_market_data_missing")
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as connection:
            rows = connection.execute(
                """
                SELECT open_time, close_time, open, high, low, close, volume
                FROM market_klines
                WHERE exchange = 'binance_spot'
                  AND upper(symbol) = 'BTCUSDT'
                  AND interval = '1h'
                ORDER BY open_time_ms
                """
            ).fetchall()
    except sqlite3.Error as exc:
        raise OkxDemoPaperRuntimeError(f"okx_demo_paper_market_data_read_failed:{type(exc).__name__}") from exc
    if not rows:
        raise OkxDemoPaperRuntimeError("okx_demo_paper_completed_1h_rows_missing")
    frame = pd.DataFrame(rows, columns=["open_time", "close_time", "open", "high", "low", "close", "volume"])
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    cutoff = pd.Timestamp(now.astimezone(timezone.utc))
    frame = frame.dropna().loc[lambda value: value["close_time"] <= cutoff].sort_values("close_time")
    if len(frame) < 4_800:
        raise OkxDemoPaperRuntimeError("okx_demo_paper_completed_1h_history_insufficient")
    frame = frame.set_index("close_time")
    latest_close = pd.Timestamp(frame.index[-1]).to_pydatetime().astimezone(timezone.utc)
    if now.astimezone(timezone.utc) - latest_close > timedelta(hours=2):
        raise OkxDemoPaperRuntimeError("okx_demo_paper_completed_1h_signal_data_stale")
    return frame[["open_time", "open", "high", "low", "close", "volume"]]


def inspect_okx_native_demo_signal_data(
    repo_root: Path,
    *,
    now: datetime | None = None,
    shared_manifest_git_spec: str = "",
    shared_data_root: Path | None = None,
    expected_dataset_id: str = "",
    allow_stale_baseline: bool = False,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        bundle, pointer, manifest, candle_path = _resolve_okx_native_demo_bundle(
            repo_root,
            shared_manifest_git_spec=shared_manifest_git_spec,
            shared_data_root=shared_data_root,
            expected_dataset_id=expected_dataset_id,
        )
        layout_schema = str(
            manifest.get("layout_schema")
            or manifest.get("schema_version")
            or ""
        )
        if layout_schema == OKX_NATIVE_SHARED_DATA_SCHEMA:
            frame = _load_generic_public_swap_hourly_frame(candle_path)
            observed_sample_end = pd.Timestamp(
                frame.index[-1]
            ).to_pydatetime().astimezone(timezone.utc)
            expected_sample_end = pd.to_datetime(
                manifest.get("sample_end_utc"),
                utc=True,
                errors="coerce",
            )
            if (
                pd.isna(expected_sample_end)
                or observed_sample_end
                != pd.Timestamp(expected_sample_end).to_pydatetime().astimezone(
                    timezone.utc
                )
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_generic_bundle_sample_end_mismatch"
                )
    except OkxDemoPaperRuntimeError as exc:
        return {
            "eligible": False,
            "integrity_passed": False,
            "freshness_status": "fail",
            "sample_end_utc": "",
            "data_version": "",
            "bundle_dir": "",
            "source_sha256": "",
            "logical_data_id": "",
            "readiness_class": "",
            "quality_status": "",
            "known_gaps": [],
            "warnings": [],
            "layout_schema": "",
            "validation": {},
            "promotion_evidence_ready": False,
            "physical_root_redacted": True,
            "blockers": [str(exc)],
            "promotion_current_head_required": False,
        }

    blockers: list[str] = []
    sample_end = pd.to_datetime(manifest.get("sample_end_utc"), utc=True, errors="coerce")
    if pd.isna(sample_end):
        blockers.append("okx_demo_paper_okx_native_sample_end_invalid")
        sample_end_utc = ""
    else:
        sample_end_at = pd.Timestamp(sample_end).to_pydatetime().astimezone(timezone.utc)
        sample_end_utc = sample_end_at.isoformat()
        if sample_end_at > current + timedelta(minutes=5):
            blockers.append("okx_demo_paper_okx_native_sample_end_in_future")
        elif (
            current - sample_end_at > timedelta(hours=2)
            and not allow_stale_baseline
        ):
            blockers.append("okx_demo_paper_okx_native_completed_1h_stale")
    return {
        "eligible": not blockers,
        "integrity_passed": True,
        "freshness_status": "pass" if not blockers else "stale",
        "sample_end_utc": sample_end_utc,
        "data_version": str(manifest.get("data_version") or pointer.get("data_version") or ""),
        "bundle_dir": "" if shared_manifest_git_spec else str(bundle),
        "source_sha256": str(dict(dict(manifest.get("files") or {}).get(candle_path.name) or {}).get("sha256") or ""),
        "logical_data_id": str(pointer.get("logical_data_id") or ""),
        "readiness_class": str(pointer.get("readiness_class") or ""),
        "quality_status": str(pointer.get("quality_status") or ""),
        "known_gaps": list(pointer.get("known_gaps") or []),
        "warnings": list(pointer.get("warnings") or []),
        "layout_schema": str(
            manifest.get("layout_schema")
            or manifest.get("schema_version")
            or ""
        ),
        "validation": dict(manifest.get("validation") or {}),
        "promotion_evidence_ready": False,
        "physical_root_redacted": bool(shared_manifest_git_spec),
        "blockers": blockers,
        "promotion_current_head_required": False,
    }


def _merge_okx_native_public_candle_tail(
    *,
    baseline: pd.DataFrame,
    client: OkxDemoClient,
    now: datetime,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    baseline_end = pd.Timestamp(baseline.index[-1])
    baseline_boundary = baseline_end + pd.Timedelta(hours=1)
    rows: list[dict[str, Any]] = []
    unconfirmed_count = 0
    after: str | None = None
    previous_oldest_open_ms: int | None = None
    overlap_reached = False
    page_count = 0
    for _ in range(OKX_DEMO_PUBLIC_CANDLE_MAX_PAGES):
        params = {
            "instId": OKX_DEMO_INSTRUMENT_ID,
            "bar": "1H",
            "limit": str(OKX_DEMO_PUBLIC_CANDLE_PAGE_LIMIT),
        }
        if after is not None:
            params["after"] = after
        response = _require(
            client.public_get("/api/v5/market/candles", params),
            "okx_demo_public_candle_tail",
            require_data=False,
        )
        page_count += 1
        page_open_times_ms: list[int] = []
        page_confirmed_closes: list[pd.Timestamp] = []
        for raw in response.data:
            values = (
                list(raw)
                if isinstance(raw, Sequence)
                and not isinstance(raw, (str, bytes, Mapping))
                else []
            )
            if len(values) < 9:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_public_candle_tail_row_invalid"
                )
            try:
                open_time_ms = int(str(values[0]))
            except ValueError as exc:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_public_candle_tail_time_invalid"
                ) from exc
            open_time = pd.to_datetime(
                open_time_ms,
                unit="ms",
                utc=True,
                errors="coerce",
            )
            if pd.isna(open_time):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_public_candle_tail_time_invalid"
                )
            page_open_times_ms.append(open_time_ms)
            if str(values[8]) != "1":
                unconfirmed_count += 1
                continue
            close_time = pd.Timestamp(open_time) + pd.Timedelta(hours=1)
            page_confirmed_closes.append(close_time)
            rows.append(
                {
                    "open_time": pd.Timestamp(open_time),
                    "close_time": close_time,
                    "open": values[1],
                    "high": values[2],
                    "low": values[3],
                    "close": values[4],
                    "volume": values[5],
                }
            )
        if not rows and page_count == 1 and page_open_times_ms:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_public_candle_tail_confirmed_rows_missing"
            )
        if not page_open_times_ms:
            break
        oldest_open_ms = min(page_open_times_ms)
        if (
            previous_oldest_open_ms is not None
            and oldest_open_ms >= previous_oldest_open_ms
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_public_candle_tail_pagination_no_progress"
            )
        if any(close_time <= baseline_boundary for close_time in page_confirmed_closes):
            overlap_reached = True
            break
        previous_oldest_open_ms = oldest_open_ms
        after = str(oldest_open_ms)
    else:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_pagination_limit_reached"
        )
    if not rows:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_confirmed_rows_missing"
        )
    if not overlap_reached:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_baseline_gap"
        )
    tail = pd.DataFrame(rows)
    cutoff = pd.Timestamp(now.astimezone(timezone.utc))
    if bool((tail["close_time"] > cutoff).any()):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_future_or_unconfirmed"
        )
    for column in ("open", "high", "low", "close", "volume"):
        tail[column] = pd.to_numeric(tail[column], errors="coerce")
    if tail[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_numeric_invalid"
        )
    duplicate_rows = tail[tail["close_time"].duplicated(keep=False)]
    compared_columns = ("open_time", "open", "high", "low", "close", "volume")
    for _, duplicate_group in duplicate_rows.groupby("close_time"):
        if len(duplicate_group.drop_duplicates(subset=list(compared_columns))) > 1:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_public_candle_tail_duplicate_hour_conflict"
            )
    tail = (
        tail.drop_duplicates(subset=["close_time"], keep="first")
        .sort_values("close_time")
        .set_index("close_time")
    )
    tail = tail.loc[tail.index >= baseline_end]
    if tail.empty:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_baseline_gap"
        )
    tail_start = pd.Timestamp(tail.index[0])
    if tail_start > baseline_end + pd.Timedelta(hours=1):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_baseline_gap"
        )
    if len(tail) > 1 and not bool(
        tail.index.to_series().diff().dropna().eq(pd.Timedelta(hours=1)).all()
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_gap"
        )
    combined = pd.concat([baseline, tail]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    recent = combined.loc[combined.index >= baseline_end]
    if len(recent) > 1 and not bool(
        recent.index.to_series().diff().dropna().eq(pd.Timedelta(hours=1)).all()
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_combined_gap"
        )
    latest_close = pd.Timestamp(combined.index[-1]).to_pydatetime().astimezone(
        timezone.utc
    )
    if now.astimezone(timezone.utc) - latest_close > timedelta(hours=2):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_public_candle_tail_stale"
        )
    bounded = tail.tail(100)
    tail_payload = [
        {
            "close_time_utc": pd.Timestamp(index).isoformat(),
            "open": _text(_decimal(row["open"])),
            "high": _text(_decimal(row["high"])),
            "low": _text(_decimal(row["low"])),
            "close": _text(_decimal(row["close"])),
            "volume": _text(_decimal(row["volume"])),
        }
        for index, row in bounded.iterrows()
    ]
    evidence = {
        "source": "okx_public_rest_market_candles",
        "instrument_id": OKX_DEMO_INSTRUMENT_ID,
        "bar": "1H",
        "page_count": page_count,
        "max_pages": OKX_DEMO_PUBLIC_CANDLE_MAX_PAGES,
        "baseline_overlap_reached": overlap_reached,
        "bounded_row_count": len(tail_payload),
        "unconfirmed_rows_excluded": unconfirmed_count,
        "sample_end_utc": _iso(latest_close),
        "tail_sha256": hashlib.sha256(
            json.dumps(
                tail_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "api_key_used": False,
        "private_endpoint_used": False,
        "persisted_market_rows": False,
    }
    return combined, evidence


def load_completed_okx_native_hourly_frame(
    repo_root: Path,
    *,
    now: datetime,
    shared_manifest_git_spec: str = "",
    shared_data_root: Path | None = None,
    expected_dataset_id: str = "",
    allow_stale_baseline: bool = False,
) -> pd.DataFrame:
    root = Path(repo_root).resolve()
    readiness = inspect_okx_native_demo_signal_data(
        root,
        now=now,
        shared_manifest_git_spec=shared_manifest_git_spec,
        shared_data_root=shared_data_root,
        expected_dataset_id=expected_dataset_id,
        allow_stale_baseline=allow_stale_baseline,
    )
    if readiness.get("eligible") is not True:
        blockers = [str(item) for item in readiness.get("blockers", []) if str(item)]
        raise OkxDemoPaperRuntimeError(";".join(blockers or ["okx_demo_paper_okx_native_signal_data_not_eligible"]))
    _, _, manifest, path = _resolve_okx_native_demo_bundle(
        root,
        shared_manifest_git_spec=shared_manifest_git_spec,
        shared_data_root=shared_data_root,
        expected_dataset_id=expected_dataset_id,
    )
    layout_schema = str(
        manifest.get("layout_schema")
        or manifest.get("schema_version")
        or ""
    )
    if layout_schema == OKX_NATIVE_SHARED_DATA_SCHEMA:
        frame = _load_generic_public_swap_hourly_frame(path)
        latest_close = pd.Timestamp(
            frame.index[-1]
        ).to_pydatetime().astimezone(timezone.utc)
        if (
            now.astimezone(timezone.utc) - latest_close > timedelta(hours=2)
            and not allow_stale_baseline
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_okx_native_completed_1h_stale"
            )
        return frame[["open_time", "open", "high", "low", "close", "volume"]]
    frame = pd.read_csv(path)
    if frame.empty or "confirm" not in frame or not frame["confirm"].astype(str).eq("1").all():
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_completed_1h_contains_unconfirmed_bar")
    frame["open_time"] = pd.to_datetime(frame["open_time_utc"], utc=True, errors="coerce")
    frame["close_time"] = pd.to_datetime(frame["close_time_utc"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close", "volume_base"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["volume"] = frame["volume_base"]
    cutoff = pd.Timestamp(now.astimezone(timezone.utc))
    frame = frame.dropna(subset=["open_time", "close_time", "open", "high", "low", "close", "volume"])
    frame = frame.loc[frame["close_time"] <= cutoff].sort_values("close_time")
    if len(frame) < 4_800:
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_completed_1h_history_insufficient")
    frame = frame.set_index("close_time")
    latest_close = pd.Timestamp(frame.index[-1]).to_pydatetime().astimezone(timezone.utc)
    if (
        now.astimezone(timezone.utc) - latest_close > timedelta(hours=2)
        and not allow_stale_baseline
    ):
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_completed_1h_stale")
    return frame[["open_time", "open", "high", "low", "close", "volume"]]


def load_btc_klines_readonly(db_path: Path, *, limit: int = 1_000) -> list[dict[str, Any]]:
    path = Path(db_path).resolve()
    if not path.exists():
        raise OkxDemoPaperRuntimeError("btc_kline_database_missing")
    bounded_limit = max(1, min(int(limit), 2_000))
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT exchange, symbol, interval, open_time_ms, open_time,
                       open, high, low, close, volume, quote_volume, trade_count
                FROM market_klines
                WHERE exchange = 'binance_spot'
                  AND upper(symbol) = 'BTCUSDT'
                  AND interval = '1h'
                ORDER BY open_time_ms DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise OkxDemoPaperRuntimeError(f"btc_kline_readonly_query_failed:{type(exc).__name__}") from exc
    return [
        {
            "exchange": str(row["exchange"]),
            "symbol": str(row["symbol"]),
            "interval": str(row["interval"]),
            "time": str(row["open_time"]),
            "open_time_ms": int(row["open_time_ms"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "quote_volume": float(row["quote_volume"]),
            "trade_count": int(row["trade_count"]),
        }
        for row in rows
    ]


def _completed_okx_frame_chart_payload(
    frame: pd.DataFrame,
    *,
    limit: int,
    source_kind: str,
    source_sha256: str,
    tail_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if frame.empty:
        raise OkxDemoPaperRuntimeError(
            "btc_chart_okx_completed_1h_rows_missing"
        )
    bounded_limit = max(1, min(int(limit), 2_000))
    selected = frame.sort_index().tail(bounded_limit)
    rows: list[dict[str, Any]] = []
    for close_time, row in selected.iterrows():
        close_at = pd.Timestamp(close_time)
        if close_at.tzinfo is None:
            close_at = close_at.tz_localize("UTC")
        else:
            close_at = close_at.tz_convert("UTC")
        raw_open_time = row.get("open_time")
        open_at = pd.Timestamp(raw_open_time)
        if pd.isna(open_at):
            open_at = close_at - pd.Timedelta(hours=1)
        elif open_at.tzinfo is None:
            open_at = open_at.tz_localize("UTC")
        else:
            open_at = open_at.tz_convert("UTC")
        rows.append(
            {
                "exchange": "okx_swap",
                "symbol": OKX_DEMO_INSTRUMENT_ID,
                "interval": "1h",
                "time": open_at.isoformat(),
                "open_time_ms": int(open_at.timestamp() * 1000),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "quote_volume": 0.0,
                "trade_count": 0,
            }
        )
    latest_close = pd.Timestamp(selected.index[-1])
    if latest_close.tzinfo is None:
        latest_close = latest_close.tz_localize("UTC")
    else:
        latest_close = latest_close.tz_convert("UTC")
    latest_close_ms = int(latest_close.timestamp() * 1000)
    return {
        "db_path": "",
        "rows": rows,
        "read_only": True,
        "schema_maintenance_performed": False,
        "source_kind": source_kind,
        "source_sha256": source_sha256,
        "strategy_signal_compatible": True,
        "sample_end": latest_close.isoformat(),
        "freshness_status": _chart_freshness(latest_close_ms),
        "completed_only": True,
        "tick_realtime": False,
        "runtime_public_candle_tail": dict(tail_evidence or {}),
    }


def load_btc_chart_payload(
    *,
    repo_root: Path,
    db_path: Path,
    limit: int = 1_000,
    shared_manifest_git_spec: str = "",
    shared_data_root: Path | None = None,
    expected_dataset_id: str = "",
) -> dict[str, Any]:
    if shared_manifest_git_spec:
        frame = load_completed_okx_native_hourly_frame(
            Path(repo_root).resolve(),
            now=datetime.now(timezone.utc),
            shared_manifest_git_spec=shared_manifest_git_spec,
            shared_data_root=shared_data_root,
            expected_dataset_id=expected_dataset_id,
            allow_stale_baseline=True,
        )
        return _completed_okx_frame_chart_payload(
            frame,
            limit=limit,
            source_kind=(
                "okx_shared_manifest_verified_completed_swap_1h"
            ),
            source_sha256="",
        )
    native = _load_okx_native_chart_payload(
        Path(repo_root).resolve(),
        limit=limit,
    )
    if native is not None:
        return native
    try:
        return _load_manifest_verified_mark_klines(
            Path(repo_root).resolve(),
            limit=limit,
        )
    except OkxDemoPaperRuntimeError as exc:
        # A BTC-USDT chart must never silently turn into a Binance spot chart
        # merely because the OKX pointer is absent.  Keep the old db argument
        # for API compatibility, but do not query it on this route.
        raise OkxDemoPaperRuntimeError(
            "btc_chart_okx_completed_1h_unavailable:"
            + _safe_error(exc)
        ) from exc


def _load_okx_native_chart_payload(repo_root: Path, *, limit: int) -> dict[str, Any] | None:
    pointer_path = repo_root / OKX_NATIVE_DEMO_POINTER_PATH
    if not pointer_path.is_file():
        return None
    readiness = inspect_okx_native_demo_signal_data(repo_root)
    if readiness.get("integrity_passed") is not True:
        blockers = [str(item) for item in readiness.get("blockers", []) if str(item)]
        raise OkxDemoPaperRuntimeError(";".join(blockers or ["okx_demo_paper_okx_native_signal_data_invalid"]))
    bundle = Path(str(readiness["bundle_dir"]))
    path = bundle / "completed_swap_klines_1h.csv"
    bounded_limit = max(1, min(int(limit), 2_000))
    selected: deque[dict[str, Any]] = deque(maxlen=bounded_limit)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            selected.append({
                "exchange": "okx_swap",
                "symbol": "BTC-USDT-SWAP",
                "interval": "1h",
                "time": str(row.get("open_time_utc") or ""),
                "open_time_ms": int(row.get("open_time_ms") or 0),
                "open": float(row.get("open") or 0),
                "high": float(row.get("high") or 0),
                "low": float(row.get("low") or 0),
                "close": float(row.get("close") or 0),
                "volume": float(row.get("volume_base") or 0),
                "quote_volume": float(row.get("volume_quote") or 0),
                "trade_count": 0,
            })
    rows = list(selected)
    if not rows:
        return None
    latest_ms = max(int(row["open_time_ms"]) for row in rows)
    latest_close_ms = latest_ms + COMPLETED_ONE_HOUR_MS
    return {
        "db_path": "",
        "rows": rows,
        "read_only": True,
        "schema_maintenance_performed": False,
        "source_kind": "okx_native_manifest_verified_completed_swap_1h",
        "source_sha256": str(readiness["source_sha256"]),
        "strategy_signal_compatible": True,
        "sample_end": datetime.fromtimestamp(latest_close_ms / 1000, tz=timezone.utc).isoformat(),
        "freshness_status": _chart_freshness(latest_close_ms),
        "demo_data_readiness": readiness,
    }


def _resolve_okx_native_demo_bundle(
    repo_root: Path,
    *,
    shared_manifest_git_spec: str = "",
    shared_data_root: Path | None = None,
    expected_dataset_id: str = "",
) -> tuple[Path, Mapping[str, Any], Mapping[str, Any], Path]:
    root = Path(repo_root).resolve()
    layout_schema = OKX_NATIVE_LEGACY_SHARED_DATA_SCHEMA
    shared_manifest: Mapping[str, Any] = {}
    if shared_manifest_git_spec:
        if shared_data_root is None or not expected_dataset_id:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_shared_data_resolver_config_incomplete"
            )
        try:
            shared_manifest = load_manifest_from_git(
                root, shared_manifest_git_spec
            )
            if shared_manifest.get("dataset_id") != expected_dataset_id:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_shared_dataset_identity_mismatch"
                )
            layout_schema = str(shared_manifest.get("data_schema") or "")
            if layout_schema not in {
                OKX_NATIVE_SHARED_DATA_SCHEMA,
                OKX_NATIVE_LEGACY_SHARED_DATA_SCHEMA,
            }:
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_shared_dataset_schema_mismatch"
                )
            if (
                shared_manifest.get("readiness_class") != "quality_checked"
                or shared_manifest.get("quality_status")
                not in {"pass", "pass_with_research_only_warnings"}
                or shared_manifest.get("blockers")
            ):
                raise OkxDemoPaperRuntimeError(
                    "okx_demo_paper_shared_dataset_not_quality_clean"
                )
            bundle = resolve_manifest_payload(
                shared_manifest,
                shared_root=Path(shared_data_root).resolve(),
                verify_files=True,
            )
        except SharedDataError as exc:
            error_code = str(exc).partition(":")[0]
            raise OkxDemoPaperRuntimeError(
                f"okx_demo_paper_shared_data_resolve_failed:{error_code}"
            ) from exc
        warnings = list(shared_manifest.get("known_gaps") or [])
        pointer: Mapping[str, Any] = {
            "data_version": str(shared_manifest.get("dataset_version") or ""),
            "logical_data_id": str(shared_manifest.get("dataset_id") or ""),
            "readiness_class": str(
                shared_manifest.get("readiness_class") or ""
            ),
            "quality_status": str(shared_manifest.get("quality_status") or ""),
            "known_gaps": warnings,
            "warnings": warnings,
        }
    else:
        pointer_path = root / OKX_NATIVE_DEMO_POINTER_PATH
        if not pointer_path.is_file():
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_okx_native_pointer_missing"
            )
        pointer = _read_json_file(
            pointer_path, "okx_demo_paper_okx_native_pointer"
        )
        bundle_value = str(pointer.get("data_bundle_dir") or "")
        if not bundle_value:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_okx_native_bundle_missing"
            )
        bundle = Path(bundle_value)
        bundle = (
            bundle.resolve()
            if bundle.is_absolute()
            else (root / bundle).resolve()
        )
        try:
            bundle.relative_to(root)
        except ValueError as exc:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_okx_native_bundle_outside_worktree"
            ) from exc
    if not bundle.is_dir():
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_bundle_missing")
    if layout_schema == OKX_NATIVE_SHARED_DATA_SCHEMA:
        try:
            return _resolve_generic_public_swap_bundle(
                bundle=bundle,
                pointer=pointer,
                shared_manifest=shared_manifest,
            )
        except (TypeError, ValueError) as exc:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_generic_bundle_manifest_invalid"
            ) from exc
    manifest = _read_json_file(bundle / "manifest.json", "okx_demo_paper_okx_native_data_manifest")
    checks = dict(manifest.get("checks") or {})
    safety = dict(manifest.get("safety") or {})
    if (
        manifest.get("schema_version") != "btc_okx_native_research_data_manifest_v1"
        or manifest.get("status") != "verified"
        or manifest.get("blockers")
        or manifest.get("source") != "OKX public REST"
        or manifest.get("instrument_id") != OKX_DEMO_INSTRUMENT_ID
        or manifest.get("signal_timeframe") != "completed_1h"
        or not all(checks.get(key) is True for key in OKX_NATIVE_DEMO_REQUIRED_CHECKS)
        or not all(safety.get(flag) is False for flag in OKX_NATIVE_DEMO_FALSE_SAFETY_FLAGS)
    ):
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_data_manifest_not_verified")
    if int(manifest.get("row_count") or 0) < 4_800:
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_completed_1h_history_insufficient")
    pointer_version = str(pointer.get("data_version") or "")
    manifest_version = str(manifest.get("data_version") or "")
    if not pointer_version or pointer_version != manifest_version:
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_data_version_mismatch")
    candle_path = bundle / "completed_swap_klines_1h.csv"
    file_record = dict(dict(manifest.get("files") or {}).get(candle_path.name) or {})
    expected_sha = str(file_record.get("sha256") or "")
    expected_size = int(file_record.get("size_bytes") or 0)
    if (
        not candle_path.is_file()
        or not expected_sha
        or candle_path.stat().st_size != expected_size
        or _file_sha256(candle_path) != expected_sha
    ):
        raise OkxDemoPaperRuntimeError("okx_demo_paper_okx_native_completed_1h_hash_mismatch")
    normalized_manifest = {
        **manifest,
        "layout_schema": OKX_NATIVE_LEGACY_SHARED_DATA_SCHEMA,
    }
    return bundle, pointer, normalized_manifest, candle_path


def _resolve_generic_public_swap_bundle(
    *,
    bundle: Path,
    pointer: Mapping[str, Any],
    shared_manifest: Mapping[str, Any],
) -> tuple[Path, Mapping[str, Any], Mapping[str, Any], Path]:
    manifest = _read_json_file(
        bundle / OKX_GENERIC_PUBLIC_SWAP_MANIFEST,
        "okx_demo_paper_generic_public_swap_manifest",
    )
    if (
        manifest.get("source_provider") != "okx_swap"
        or manifest.get("source_type") != "production"
        or manifest.get("exchange") != "okx"
        or manifest.get("symbol") != "BTCUSDT"
        or manifest.get("market_type") != "usds_m_perpetual"
        or manifest.get("promotion_clean_allowed") is not False
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_bundle_identity_invalid"
        )
    inner_blockers = [
        str(value)
        for value in manifest.get("blockers", [])
        if str(value)
    ]
    if set(inner_blockers) - OKX_GENERIC_PUBLIC_SWAP_DIAGNOSTIC_WARNINGS:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_bundle_has_signal_blockers"
        )
    file_rows = manifest.get("files")
    if not isinstance(file_rows, list):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_bundle_files_invalid"
        )
    rows_by_role: dict[str, Mapping[str, Any]] = {}
    observed_paths: set[str] = set()
    for item in file_rows:
        if not isinstance(item, Mapping):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_generic_bundle_file_record_invalid"
            )
        role = str(item.get("role") or "")
        relative = str(item.get("path") or "")
        if (
            not role
            or not relative
            or role in rows_by_role
            or relative in observed_paths
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_generic_bundle_file_identity_duplicate"
            )
        rows_by_role[role] = item
        observed_paths.add(relative)
    outer_files = {
        str(item.get("path") or ""): item
        for item in shared_manifest.get("files", [])
        if isinstance(item, Mapping)
    }
    for role, expected_path in OKX_GENERIC_PUBLIC_SWAP_REQUIRED_FILES.items():
        item = rows_by_role.get(role)
        if item is None or str(item.get("path") or "") != expected_path:
            raise OkxDemoPaperRuntimeError(
                f"okx_demo_paper_generic_bundle_required_file_missing:{role}"
            )
        outer = outer_files.get(expected_path)
        if (
            outer is None
            or str(item.get("sha256") or "") != str(outer.get("sha256") or "")
            or not (bundle / expected_path).is_file()
        ):
            raise OkxDemoPaperRuntimeError(
                f"okx_demo_paper_generic_bundle_file_hash_mismatch:{role}"
            )
        if item.get("blockers"):
            raise OkxDemoPaperRuntimeError(
                f"okx_demo_paper_generic_bundle_file_blocked:{role}"
            )
    candle_record = rows_by_role["klines_1h"]
    if (
        candle_record.get("interval") != "1h"
        or int(candle_record.get("record_count") or 0) < 4_800
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_okx_native_completed_1h_history_insufficient"
        )
    pit = candle_record.get("pit_contract")
    if (
        not isinstance(pit, Mapping)
        or pit.get("present") is not True
        or pit.get("required") is not True
        or pit.get("missing_fields")
        or pit.get("invalid_time_fields")
        or int(pit.get("available_time_order_violation_count") or 0) != 0
        or pit.get("blockers")
        or int(pit.get("row_count_checked") or 0)
        != int(candle_record.get("record_count") or 0)
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_bundle_pit_contract_invalid"
        )
    for role in (
        "mark_price_klines_1h",
        "premium_index_klines_1h",
        "funding_rate",
    ):
        if int(rows_by_role[role].get("record_count") or 0) < 1:
            raise OkxDemoPaperRuntimeError(
                f"okx_demo_paper_generic_bundle_required_file_empty:{role}"
            )
    sample_end = str(candle_record.get("available_end") or "")
    if not sample_end or sample_end != str(manifest.get("sample_end") or ""):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_bundle_sample_end_mismatch"
        )
    warnings = list(
        dict.fromkeys(
            [
                *[str(value) for value in pointer.get("warnings", [])],
                *inner_blockers,
            ]
        )
    )
    normalized_pointer = {
        **pointer,
        "warnings": warnings,
    }
    validation = {
        "full_shared_data_hash_verified": True,
        "bundle_manifest_verified": True,
        "completed_1h_row_count": int(
            candle_record.get("record_count") or 0
        ),
        "confirmed_only": True,
        "duplicate_count": 0,
        "gap_count": 0,
        "mark_price_present": True,
        "index_price_present": True,
        "funding_present": True,
    }
    normalized_manifest = {
        "schema_version": OKX_NATIVE_SHARED_DATA_SCHEMA,
        "layout_schema": OKX_NATIVE_SHARED_DATA_SCHEMA,
        "data_version": str(pointer.get("data_version") or ""),
        "sample_end_utc": sample_end,
        "row_count": int(candle_record.get("record_count") or 0),
        "files": {
            OKX_GENERIC_PUBLIC_SWAP_CANDLES: {
                "sha256": str(candle_record.get("sha256") or ""),
                "size_bytes": int(
                    outer_files[OKX_GENERIC_PUBLIC_SWAP_CANDLES].get("bytes")
                    or 0
                ),
            }
        },
        "warnings": warnings,
        "validation": validation,
    }
    return (
        bundle,
        normalized_pointer,
        normalized_manifest,
        bundle / OKX_GENERIC_PUBLIC_SWAP_CANDLES,
    )


def _load_generic_public_swap_hourly_frame(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError) as exc:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_completed_1h_unreadable"
        ) from exc
    required = {
        "timestamp",
        "event_time",
        "available_time",
        "ingested_at",
        "processed_at",
        "open_time",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume_base",
        "confirm",
    }
    if frame.empty or not required.issubset(frame.columns):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_completed_1h_columns_invalid"
        )
    if not frame["confirm"].astype(str).eq("1").all():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_okx_native_completed_1h_contains_unconfirmed_bar"
        )
    if not frame["symbol"].astype(str).eq("BTCUSDT").all():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_completed_1h_symbol_invalid"
        )
    frame["open_time"] = pd.to_datetime(
        pd.to_numeric(frame["open_time"], errors="coerce"),
        unit="ms",
        utc=True,
        errors="coerce",
    )
    frame["close_time"] = pd.to_datetime(
        frame["available_time"],
        utc=True,
        errors="coerce",
    )
    for column in ("open", "high", "low", "close", "volume_base"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    required_values = [
        "open_time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume_base",
    ]
    if frame[required_values].isna().any().any():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_completed_1h_values_invalid"
        )
    frame = frame.sort_values("open_time")
    if len(frame) < 4_800:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_okx_native_completed_1h_history_insufficient"
        )
    if (
        frame["open_time"].duplicated().any()
        or frame["close_time"].duplicated().any()
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_completed_1h_duplicate"
        )
    if not (
        frame["close_time"] - frame["open_time"]
    ).eq(pd.Timedelta(hours=1)).all():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_completed_1h_close_time_invalid"
        )
    gaps = frame["open_time"].diff().dropna()
    if not gaps.eq(pd.Timedelta(hours=1)).all():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_generic_completed_1h_gap"
        )
    frame["volume"] = frame["volume_base"]
    frame = frame.set_index("close_time")
    return frame[["open_time", "open", "high", "low", "close", "volume"]]


def _load_manifest_verified_mark_klines(repo_root: Path, *, limit: int) -> dict[str, Any]:
    latest_path = repo_root / "artifacts" / "btc_strategy_backtest_runs" / "latest_manifest.json"
    latest = _read_json_file(latest_path, "btc_chart_latest_manifest")
    canonical_path = Path(str(latest.get("canonical_manifest", {}).get("path") or ""))
    if not canonical_path.is_absolute():
        canonical_path = repo_root / canonical_path
    run_manifest = _read_json_file(canonical_path, "btc_chart_run_manifest")
    source_manifest_path = Path(str(run_manifest.get("outputs", {}).get("source_data_manifest") or ""))
    if not source_manifest_path.is_absolute():
        source_manifest_path = repo_root / source_manifest_path
    data_manifest = _read_json_file(source_manifest_path, "btc_chart_data_manifest")
    execution = data_manifest.get("execution_cost_proxy", {})
    mark_path = Path(str(execution.get("mark_price_path") or ""))
    expected_sha = str(execution.get("mark_price_sha256") or "")
    if not mark_path.is_file() or not expected_sha:
        raise OkxDemoPaperRuntimeError("btc_chart_manifest_verified_mark_source_missing")
    observed_sha = _file_sha256(mark_path)
    if observed_sha != expected_sha:
        raise OkxDemoPaperRuntimeError("btc_chart_mark_source_sha256_mismatch")
    bounded_limit = max(1, min(int(limit), 2_000))
    selected: deque[dict[str, Any]] = deque(maxlen=bounded_limit)
    with mark_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            selected.append(
                {
                    "exchange": "binance_usdm_mark",
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "time": str(row.get("timestamp") or ""),
                    "open_time_ms": int(row.get("open_time_ms") or 0),
                    "open": float(row.get("open") or 0),
                    "high": float(row.get("high") or 0),
                    "low": float(row.get("low") or 0),
                    "close": float(row.get("close") or 0),
                    "volume": float(row.get("volume") or 0),
                    "quote_volume": 0.0,
                    "trade_count": 0,
                }
            )
    rows = list(selected)
    if not rows:
        raise OkxDemoPaperRuntimeError("btc_chart_manifest_verified_mark_rows_missing")
    latest_ms = max(int(row["open_time_ms"]) for row in rows)
    latest_close_ms = latest_ms + COMPLETED_ONE_HOUR_MS
    return {
        "db_path": "",
        "rows": rows,
        "read_only": True,
        "schema_maintenance_performed": False,
        "source_kind": "canonical_manifest_verified_mark_price_1h",
        "source_sha256": observed_sha,
        "strategy_signal_compatible": False,
        "sample_end": datetime.fromtimestamp(latest_close_ms / 1000, tz=timezone.utc).isoformat(),
        "freshness_status": _chart_freshness(latest_close_ms),
    }


def _read_json_file(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OkxDemoPaperRuntimeError(f"{label}_unavailable:{type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise OkxDemoPaperRuntimeError(f"{label}_invalid")
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size_bytes(root: Path) -> int:
    if not root.is_dir():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _chart_freshness(latest_completed_close_ms: int) -> str:
    latest = datetime.fromtimestamp(latest_completed_close_ms / 1000, tz=timezone.utc)
    return "pass" if datetime.now(timezone.utc) - latest <= timedelta(hours=2) else "stale"


def _require(response: OkxDemoResponse, label: str, *, require_data: bool = True) -> OkxDemoResponse:
    if not response.ok:
        raise OkxDemoPaperRuntimeError(f"okx_demo_paper_{label}_failed:{response.code}")
    if require_data and not response.data:
        raise OkxDemoPaperRuntimeError(f"okx_demo_paper_{label}_empty")
    return response


def _first(response: OkxDemoResponse, label: str, *, allow_empty: bool = False) -> Mapping[str, Any]:
    checked = _require(response, label, require_data=not allow_empty)
    return checked.data[0] if checked.data else {}


def _signed_position(rows: Sequence[Mapping[str, Any]]) -> Decimal:
    signed = Decimal("0")
    for row in rows:
        quantity = _strict_position_quantity(row)
        if row.get("position_side") == "long":
            signed += quantity
        elif row.get("position_side") == "short":
            signed -= quantity
        elif quantity:
            raise OkxDemoPaperRuntimeError("okx_demo_paper_position_side_unknown")
    return signed


def _gross_position_contracts(
    rows: Sequence[Mapping[str, Any]],
) -> Decimal:
    gross = Decimal("0")
    for row in rows:
        quantity = _strict_position_quantity(row)
        if quantity and row.get("position_side") not in {"long", "short"}:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_paper_position_side_unknown"
            )
        gross += quantity
    return gross


def _strict_position_quantity(row: Mapping[str, Any]) -> Decimal:
    if "contracts" not in row:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_position_contracts_invalid"
        )
    raw = row.get("contracts")
    if raw is None or not str(raw).strip():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_position_contracts_invalid"
        )
    try:
        quantity = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_position_contracts_invalid"
        ) from exc
    if not quantity.is_finite():
        raise OkxDemoPaperRuntimeError(
            "okx_demo_paper_position_contracts_invalid"
        )
    return abs(quantity)


def _sanitize_account(
    row: Mapping[str, Any],
    *,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    permissions = sorted(item.strip() for item in str(row.get("perm") or "").split(",") if item.strip())
    return {
        "account_level": str(row.get("acctLv") or ""),
        "position_mode": str(row.get("posMode") or ""),
        "permissions": permissions,
        "withdraw_permission_present": "withdraw" in permissions,
        "identity": {
            "hash": str(_mapping(identity).get("hash") or ""),
            "source": str(_mapping(identity).get("source") or ""),
            "captured_at_utc": str(_mapping(identity).get("captured_at_utc") or ""),
        },
    }


def _sanitize_balance(row: Mapping[str, Any]) -> dict[str, Any]:
    details = row.get("details") if isinstance(row.get("details"), list) else []
    usdt = next((item for item in details if str(item.get("ccy") or "") == "USDT"), {})
    observed_upl = "upl" in usdt and usdt.get("upl") not in (None, "")
    return {
        "equity_usdt": str(usdt.get("eq") or row.get("totalEq") or "0"),
        "available_usdt": str(usdt.get("availEq") or usdt.get("availBal") or "0"),
        "unrealized_pnl_usdt": str(usdt.get("upl")) if observed_upl else "",
        "unrealized_pnl_observed": observed_upl,
        "timestamp_ms": str(row.get("uTime") or ""),
    }


def _sanitize_position(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_contracts = row.get("pos") if "pos" in row else None
    observed_upl = "upl" in row and row.get("upl") not in (None, "")
    observed_realized = "realizedPnl" in row and row.get("realizedPnl") not in (None, "")
    return {
        "instrument_id": str(row.get("instId") or ""),
        "position_side": str(row.get("posSide") or ""),
        "margin_mode": str(row.get("mgnMode") or ""),
        "contracts": "" if raw_contracts is None else str(raw_contracts),
        "average_price": str(row.get("avgPx") or ""),
        "mark_price": str(row.get("markPx") or ""),
        "liquidation_price": str(row.get("liqPx") or ""),
        "unrealized_pnl": str(row.get("upl")) if observed_upl else "",
        "unrealized_pnl_observed": observed_upl,
        "realized_pnl": str(row.get("realizedPnl")) if observed_realized else "",
        "realized_pnl_observed": observed_realized,
        "leverage": str(row.get("lever") or ""),
        "updated_at_ms": str(row.get("uTime") or ""),
    }


def _sanitize_order(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": str(row.get("ordId") or ""),
        "client_order_id": str(row.get("clOrdId") or ""),
        "algo_id": str(row.get("algoId") or ""),
        "algo_client_order_id": str(row.get("algoClOrdId") or ""),
        "instrument_id": str(row.get("instId") or ""),
        "side": str(row.get("side") or ""),
        "position_side": str(row.get("posSide") or ""),
        "order_type": str(row.get("ordType") or ""),
        "state": str(row.get("state") or ""),
        "reduce_only": str(row.get("reduceOnly") or "").lower() == "true",
        "price": str(row.get("px") or ""),
        "average_price": str(row.get("avgPx") or ""),
        "size": str(row.get("sz") or "0"),
        "filled_size": str(row.get("accFillSz") or "0"),
        "fee": str(row.get("fee") or "0"),
        "pnl": str(row.get("pnl") or "0"),
        "created_at_ms": str(row.get("cTime") or ""),
        "updated_at_ms": str(row.get("uTime") or ""),
    }


def _sanitize_algo_order(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_reduce_only = row.get("reduceOnly") if "reduceOnly" in row else None
    reduce_only_status = (
        "true"
        if str(raw_reduce_only).lower() == "true"
        else "false"
        if str(raw_reduce_only).lower() == "false"
        else "unknown"
    )
    return {
        "algo_id": str(row.get("algoId") or row.get("attachAlgoId") or ""),
        "algo_client_order_id": str(
            row.get("algoClOrdId") or row.get("attachAlgoClOrdId") or ""
        ),
        "parent_client_order_id": str(
            row.get("parentClOrdId") or row.get("clOrdId") or ""
        ),
        "instrument_id": str(row.get("instId") or ""),
        "side": str(row.get("side") or ""),
        "position_side": str(row.get("posSide") or ""),
        "reduce_only": (
            True
            if reduce_only_status == "true"
            else False
            if reduce_only_status == "false"
            else None
        ),
        "reduce_only_status": reduce_only_status,
        "size": str(row.get("sz") if row.get("sz") is not None else ""),
        "order_type": str(row.get("ordType") or ""),
        "state": str(row.get("state") or ""),
        "take_profit_trigger": str(row.get("tpTriggerPx") or ""),
        "take_profit_trigger_type": str(row.get("tpTriggerPxType") or ""),
        "take_profit_order_price": str(row.get("tpOrdPx") or ""),
        "stop_loss_trigger": str(row.get("slTriggerPx") or ""),
        "stop_loss_trigger_type": str(row.get("slTriggerPxType") or ""),
        "stop_loss_order_price": str(row.get("slOrdPx") or ""),
        "updated_at_ms": str(row.get("uTime") or ""),
    }


def _sanitize_fill(row: Mapping[str, Any]) -> dict[str, Any]:
    pnl_key = "fillPnl" if "fillPnl" in row else "pnl"
    observed_pnl = pnl_key in row and row.get(pnl_key) not in (None, "")
    return {
        "fill_id": str(row.get("tradeId") or ""),
        "order_id": str(row.get("ordId") or ""),
        "client_order_id": str(row.get("clOrdId") or ""),
        "instrument_id": str(row.get("instId") or ""),
        "side": str(row.get("side") or ""),
        "position_side": str(row.get("posSide") or ""),
        "price": str(row.get("fillPx") or ""),
        "size": str(row.get("fillSz") or "0"),
        "fee": str(row.get("fee") or "0"),
        "fee_currency": str(row.get("feeCcy") or ""),
        "pnl": str(row.get(pnl_key)) if observed_pnl else "",
        "pnl_observed": observed_pnl,
        "execution_type": str(row.get("execType") or ""),
        "timestamp_ms": str(row.get("ts") or ""),
    }


def _sanitize_bill(row: Mapping[str, Any]) -> dict[str, Any]:
    observed_balance_change = "balChg" in row and row.get("balChg") not in (None, "")
    observed_pnl = "pnl" in row and row.get("pnl") not in (None, "")
    return {
        "bill_id": str(row.get("billId") or ""),
        "instrument_id": str(row.get("instId") or ""),
        "currency": str(row.get("ccy") or ""),
        "type": str(row.get("type") or ""),
        "sub_type": str(row.get("subType") or ""),
        "balance_change": str(row.get("balChg")) if observed_balance_change else "",
        "balance_change_observed": observed_balance_change,
        "fee": str(row.get("fee") or "0"),
        "pnl": str(row.get("pnl")) if observed_pnl else "",
        "pnl_observed": observed_pnl,
        "timestamp_ms": str(row.get("ts") or ""),
    }


def _observed_decimal_total(
    rows: Sequence[Mapping[str, Any]],
    *,
    field: str,
    observed_flag: str,
    error_code: str,
) -> Decimal:
    """Sum a numeric ledger field only when every row carries a value.

    Missing funding/PnL facts are unknown, never an implicit zero.  A caller
    must handle the explicit runtime error as a fail-closed reconciliation.
    """

    total = Decimal("0")
    for row in rows:
        if row.get(observed_flag) is False or row.get(field) in (None, ""):
            raise OkxDemoPaperRuntimeError(error_code)
        value = _decimal(row.get(field))
        if value is None:
            raise OkxDemoPaperRuntimeError(error_code)
        total += value
    return total


def _sanitize_fee(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "level": str(row.get("level") or ""),
        "maker_rate": str(row.get("makerU") or row.get("maker") or ""),
        "taker_rate": str(row.get("takerU") or row.get("taker") or ""),
        "rule_type": str(row.get("ruleType") or ""),
        "timestamp_ms": str(row.get("ts") or ""),
    }


def _sanitize_leverage(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "instrument_id": str(row.get("instId") or ""),
        "position_side": str(row.get("posSide") or ""),
        "margin_mode": str(row.get("mgnMode") or ""),
        "leverage": str(row.get("lever") or ""),
    }


def _exact_isolated_three_x_leverage(value: Any) -> bool:
    rows = [row for row in value or [] if isinstance(row, Mapping)]
    if len(rows) != 2:
        return False
    observed_sides: set[str] = set()
    for row in rows:
        position_side = str(row.get("position_side") or "")
        if not (
            str(row.get("instrument_id") or "")
            == OKX_DEMO_INSTRUMENT_ID
            and position_side in {"long", "short"}
            and row.get("margin_mode") == "isolated"
            and _decimal(row.get("leverage")) == Decimal("3")
        ):
            return False
        observed_sides.add(position_side)
    return observed_sides == {"long", "short"}


def _sanitize_instrument(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "instrument_id": str(row.get("instId") or ""),
        "state": str(row.get("state") or ""),
        "contract_type": str(row.get("ctType") or ""),
        "contract_value_btc": str(row.get("ctVal") or ""),
        "contract_value_currency": str(row.get("ctValCcy") or ""),
        "settle_currency": str(row.get("settleCcy") or ""),
        "tick_size": str(row.get("tickSz") or ""),
        "lot_size": str(row.get("lotSz") or ""),
        "minimum_size": str(row.get("minSz") or ""),
    }


def _sanitize_ticker(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "bid": str(row.get("bidPx") or ""),
        "ask": str(row.get("askPx") or ""),
        "last": str(row.get("last") or ""),
        "timestamp_ms": str(row.get("ts") or ""),
    }


def _sanitize_book(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "bids": [[str(value) for value in level[:4]] for level in row.get("bids", []) if isinstance(level, list)],
        "asks": [[str(value) for value in level[:4]] for level in row.get("asks", []) if isinstance(level, list)],
        "timestamp_ms": str(row.get("ts") or ""),
    }


def _sanitize_funding(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "funding_rate": str(row.get("fundingRate") or "0"),
        "next_funding_rate": str(row.get("nextFundingRate") or ""),
        "funding_time_ms": str(row.get("fundingTime") or ""),
        "next_funding_time_ms": str(row.get("nextFundingTime") or ""),
    }


def _book_two_sided(book: Mapping[str, Any]) -> bool:
    return bool(book.get("bids")) and bool(book.get("asks")) and _decimal(book["bids"][0][0]) > 0 and _decimal(book["asks"][0][0]) > 0


def _depth_cost(book: Mapping[str, Any], *, side: str, contracts: Decimal) -> dict[str, Any]:
    levels = book.get("asks" if side == "buy" else "bids", [])
    remaining = contracts
    weighted = Decimal("0")
    mapped = Decimal("0")
    best = _decimal(levels[0][0]) if levels else Decimal("0")
    for level in levels:
        if not isinstance(level, list) or len(level) < 2:
            continue
        price = _decimal(level[0])
        size = _decimal(level[1])
        take = min(remaining, size)
        if take <= 0:
            continue
        weighted += take * price
        mapped += take
        remaining -= take
        if remaining <= 0:
            break
    average = weighted / mapped if mapped > 0 else Decimal("0")
    impact = _ratio_bps(abs(average - best), best) if best > 0 and average > 0 else Decimal("0")
    return {
        "side": side,
        "requested_contracts": _text(contracts),
        "mapped_contracts": _text(mapped),
        "fully_mapped": remaining <= 0,
        "best_price": _text(best),
        "weighted_average_price": _text(average),
        "impact_bps": _text(impact),
        "book_timestamp_ms": str(book.get("timestamp_ms") or ""),
    }


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_windows_process_liveness(process_id: int) -> bool | None:
    """Use the existing native process-time probe after Windows kill ambiguity."""

    if os.name != "nt":
        return None
    try:
        from scripts.run_btc_okx_demo_fault_drill import _process_create_time
    except Exception:
        return None
    try:
        _process_create_time(process_id)
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        errno_value = getattr(exc, "errno", None)
        if (winerror == 87 and errno_value in {22, 87}) or (
            winerror is None and errno_value == 87
        ):
            return False
        return None
    except Exception:
        return None
    return True


def _canonical_windows_process_create_time(process_id: int) -> str | None:
    """Return the native process birth token used to reject PID reuse."""

    if os.name != "nt":
        return None
    try:
        from scripts.run_btc_okx_demo_fault_drill import _process_create_time
    except Exception:
        return None
    try:
        value = str(_process_create_time(process_id) or "")
    except Exception:
        return None
    return value if value.isdigit() else None


def _owned_restore_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _owned_restore_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_json_invalid"
        ) from exc
    if not isinstance(value, Mapping):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_json_invalid"
        )
    return value


def _owned_restore_safe_path(root: Path, relative: str) -> Path:
    candidate = Path(str(relative))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_path_invalid"
        )
    resolved = (root / candidate).resolve()
    if resolved == root or root not in resolved.parents:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_path_invalid"
        )
    return resolved


def _owned_restore_identity_mapping(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    # Ownership may only be established by the archive's authoritative
    # execution identity document.  Public/runtime summary fields are not an
    # authority and must never become a fallback when this document is absent.
    value = manifest.get("execution_identity")
    return value if isinstance(value, Mapping) else {}


def _owned_restore_run_id(value: Any) -> str:
    run_id = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", run_id):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_run_id_invalid"
        )
    return run_id


def _owned_restore_event_chain(
    events_path: Path,
    checkpoint: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
    try:
        raw_lines = events_path.read_bytes().splitlines()
    except OSError as exc:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_runtime_events_unreadable"
        ) from exc
    events: list[Mapping[str, Any]] = []
    previous_hash = ""
    for expected_sequence, line in enumerate(raw_lines, start=1):
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_event_chain_invalid"
            ) from exc
        if not isinstance(value, Mapping):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_event_chain_invalid"
            )
        body = dict(value)
        supplied_hash = str(body.pop("event_hash", "") or "")
        semantic = {
            "event_type": body.get("event_type"),
            "payload": body.get("payload"),
            "run_id": body.get("run_id"),
        }
        try:
            sequence = int(body.get("sequence", -1))
        except (TypeError, ValueError):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_event_chain_invalid"
            )
        if (
            sequence != expected_sequence
            or str(body.get("previous_event_hash", "") or "") != previous_hash
            or not str(body.get("idempotency_key", "") or "")
            or supplied_hash != _canonical_sha256(body)
            or str(body.get("semantic_hash", "") or "")
            != _canonical_sha256(semantic)
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_event_chain_invalid"
            )
        events.append(dict(value))
        previous_hash = supplied_hash
    checkpoint_body = dict(checkpoint)
    checkpoint_hash = str(checkpoint_body.pop("checkpoint_hash", "") or "")
    try:
        checkpoint_sequence = int(checkpoint_body.get("last_sequence", -1))
    except (TypeError, ValueError):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_checkpoint_invalid"
        )
    if (
        checkpoint_hash != _canonical_sha256(checkpoint_body)
        or checkpoint_sequence != len(events)
        or str(checkpoint_body.get("last_event_hash", "") or "") != previous_hash
        or not isinstance(checkpoint_body.get("state"), Mapping)
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_checkpoint_invalid"
        )
    return events, checkpoint_body["state"]


def _owned_restore_record_id(row: Mapping[str, Any], field: str, *aliases: str) -> str:
    for key in (field, *aliases):
        value = str(row.get(key) or "")
        if value:
            return value
    return ""


def _build_owned_id_restore_projection(
    *,
    archive_root: Path,
    repo_root: Path,
    current_head: str,
    source_head: str,
    account_identity: str,
    credential_identity: str,
    client_order_namespace: str,
    credential_service: str,
) -> dict[str, Any]:
    """Validate an immutable archive and return identity-only order ownership.

    This function intentionally consumes only archived files.  It never
    constructs a client, reads credentials, or performs a network operation.
    Counts in a receipt or an exchange snapshot are not sufficient: every
    returned tuple must be present in the same-run lifecycle + committed UOW
    event intersection and in the archived order/fill snapshot.
    """

    root = Path(archive_root).resolve()
    repo = Path(repo_root).resolve()
    if not root.is_dir() or root == repo or repo in root.parents:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_root_invalid"
        )
    try:
        observed_head = _repo_head(repo)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_current_head_unavailable"
        ) from exc
    if str(current_head) != observed_head:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_current_head_mismatch"
        )
    manifest_path = root / "manifest.json"
    verification_path = root / "verification.json"
    completed_path = root / "COMPLETED.json"
    manifest = _owned_restore_json(manifest_path)
    verification = _owned_restore_json(verification_path)
    completed = _owned_restore_json(completed_path)
    archive_id = str(manifest.get("archive_id") or "")
    claimed_manifest_hash = str(manifest.get("manifest_hash") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", claimed_manifest_hash):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_manifest_hash_missing"
        )
    if not archive_id or any(
        str(document.get("archive_id") or "") not in {"", archive_id}
        for document in (verification, completed)
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_identity_invalid"
        )
    manifest_sha = _owned_restore_file_sha256(manifest_path)
    verification_sha = _owned_restore_file_sha256(verification_path)
    expected_manifest_sha = str(
        completed.get("manifest_sha256")
        or manifest.get("manifest_sha256")
        or manifest.get("archive_manifest_sha256")
        or ""
    )
    expected_verification_sha = str(
        completed.get("verification_sha256")
        or manifest.get("verification_sha256")
        or ""
    )
    if (
        not expected_manifest_sha
        or expected_manifest_sha != manifest_sha
        or not expected_verification_sha
        or expected_verification_sha != verification_sha
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_hash_invalid"
        )
    if (
        manifest.get("immutable") is not True
        or manifest.get("unique_directory_no_overwrite") is not True
        or completed.get("immutable_after_write") is not True
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_not_immutable"
        )
    owner = manifest.get("owner_marker")
    if not isinstance(owner, Mapping) or owner.get("immutable_archives_only") is not True:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_owner_marker_invalid"
        )
    owner_path = Path(str(owner.get("path") or ""))
    if not owner_path.is_absolute():
        owner_path = (root / owner_path).resolve()
    else:
        owner_path = owner_path.resolve()
    if (
        not owner_path.is_file()
        or owner_path == root
        or root in owner_path.parents
        or owner_path == repo
        or repo in owner_path.parents
        or _owned_restore_file_sha256(owner_path)
        != str(owner.get("sha256") or "")
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_owner_marker_invalid"
        )
    owner_document = _owned_restore_json(owner_path)
    if (
        not str(owner_document.get("repository_owner_identity") or "")
        or str(owner_document.get("repository_owner_identity"))
        != str(owner.get("repository_owner_identity") or "")
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_owner_marker_invalid"
        )
    manifest_head = str(manifest.get("current_head") or "")
    verification_head = str(
        verification.get("source_head")
        or verification.get("current_head")
        or ""
    )
    if not source_head or manifest_head != source_head or verification_head != source_head:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_source_head_mismatch"
        )
    if not re.fullmatch(r"[0-9a-fA-F]{40}", str(current_head)):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_current_head_invalid"
        )
    files = manifest.get("files")
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_manifest_files_missing"
        )
    file_hashes: dict[str, str] = {}
    required_kinds = {"runtime_events", "runtime_state", "receipt_ledger"}
    kinds_seen: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_manifest_files_invalid"
            )
        relative = str(item.get("archive_relative_path") or "")
        path = _owned_restore_safe_path(root, relative)
        try:
            expected_size = int(item.get("size_bytes", -1))
        except (TypeError, ValueError):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_source_snapshot_invalid"
            )
        if not path.is_file() or expected_size != path.stat().st_size:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_source_snapshot_invalid"
            )
        actual_sha = _owned_restore_file_sha256(path)
        if actual_sha != str(item.get("sha256") or ""):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_source_snapshot_invalid"
            )
        kind = str(item.get("kind") or "")
        if kind in required_kinds:
            kinds_seen.add(kind)
            file_hashes[kind] = actual_sha
    if kinds_seen != required_kinds:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_source_snapshot_missing"
        )
    events_path = _owned_restore_safe_path(root, "source_snapshots/runtime_events.jsonl")
    state_path = _owned_restore_safe_path(root, "source_snapshots/runtime_state.json")
    receipt_path = _owned_restore_safe_path(root, "source_snapshots/receipt_ledger.jsonl")
    checkpoint = _owned_restore_json(state_path)
    events, state = _owned_restore_event_chain(events_path, checkpoint)
    archive_run_ids: set[str] = set()
    for event in events:
        raw_run_id = str(event.get("run_id") or "")
        if raw_run_id:
            archive_run_ids.add(_owned_restore_run_id(raw_run_id))
    if len(archive_run_ids) > 1:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_run_id_ambiguous"
        )
    event_chain = manifest.get("event_chain")
    if not isinstance(event_chain, Mapping):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_event_chain_invalid"
        )
    try:
        manifest_event_count = int(event_chain.get("event_count", -1))
    except (TypeError, ValueError):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_event_chain_invalid"
        )
    if (
        event_chain.get("hash_chain_valid") is not True
        or manifest_event_count != len(events)
        or str(event_chain.get("last_event_hash") or "")
        != str(checkpoint.get("last_event_hash") or "")
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_event_chain_invalid"
        )
    if (
        verification.get("status") not in {"blocked_fail_closed", "verified_fail_closed"}
        or manifest.get("status") not in {"blocked_fail_closed", "verified_fail_closed"}
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_archive_status_invalid"
        )
    for safety_document in (manifest.get("safety"), verification.get("safety")):
        if not isinstance(safety_document, Mapping) or any(
            bool(value) for value in safety_document.values()
        ):
            raise OkxDemoPaperRuntimeError(
                "okx_demo_owned_id_restore_archive_safety_invalid"
            )

    exchange = state.get("exchange")
    if not isinstance(exchange, Mapping):
        raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_snapshot_invalid")
    environment = str(state.get("environment") or "")
    instrument = str(state.get("instrument_id") or "")
    limits = state.get("limits")
    limits_mapping = limits if isinstance(limits, Mapping) else {}
    account = exchange.get("account")
    account_mapping = account if isinstance(account, Mapping) else {}
    positions = exchange.get("positions")
    pending_orders = exchange.get("pending_orders")
    pending_algo_orders = exchange.get("pending_algo_orders")
    if (
        environment != "OKX Demo"
        or instrument != OKX_DEMO_INSTRUMENT_ID
        or str(limits_mapping.get("margin_mode") or "") != "isolated"
        or account_mapping.get("withdraw_permission_present") is not False
        or not isinstance(positions, Sequence)
        or isinstance(positions, (str, bytes))
        or positions
        or not isinstance(pending_orders, Sequence)
        or isinstance(pending_orders, (str, bytes))
        or pending_orders
        or not isinstance(pending_algo_orders, Sequence)
        or isinstance(pending_algo_orders, (str, bytes))
        or pending_algo_orders
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_exchange_identity_invalid"
        )
    identity = _owned_restore_identity_mapping(manifest)
    archived_account_identity = str(identity.get("account_identity") or "").strip()
    archived_credential_identity = str(
        identity.get("credential_identity") or ""
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", archived_account_identity):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_account_identity_invalid"
        )
    if (
        not re.fullmatch(
            r"quant-system\.okx-demo\.[A-Za-z0-9_.:-]{1,127}",
            archived_credential_identity,
        )
        or any(
            token in archived_credential_identity.lower()
            for token in ("secret", "passphrase", "token", "api_key")
        )
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_credential_identity_invalid"
        )
    expected_account_identity = archived_account_identity
    if str(account_identity).strip() != expected_account_identity:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_account_identity_mismatch"
        )
    expected_credential_identity = archived_credential_identity
    if str(credential_identity).strip() != expected_credential_identity:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_credential_identity_mismatch"
        )

    orders = exchange.get("orders")
    fills = exchange.get("fills")
    if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes)):
        raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_snapshot_invalid")
    if not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
        raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_snapshot_invalid")
    exchange_orders: dict[str, tuple[str, str]] = {}
    exchange_fills: dict[str, tuple[str, str]] = {}
    for row in orders:
        if not isinstance(row, Mapping):
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_snapshot_invalid")
        client_id = _owned_restore_record_id(row, "client_order_id", "clOrdId")
        order_id = _owned_restore_record_id(row, "order_id", "ordId")
        if not client_id or not order_id or str(row.get("instrument_id") or row.get("instId") or "") != instrument:
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_mapping_invalid")
        if str(row.get("state") or "") not in {
            "filled",
            "partially_filled",
        }:
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_mapping_invalid")
        pair = (order_id, instrument)
        if client_id in exchange_orders and exchange_orders[client_id] != pair:
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_mapping_conflict")
        exchange_orders[client_id] = pair
    for row in fills:
        if not isinstance(row, Mapping):
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_snapshot_invalid")
        client_id = _owned_restore_record_id(row, "client_order_id", "clOrdId")
        order_id = _owned_restore_record_id(row, "order_id", "ordId")
        fill_id = _owned_restore_record_id(row, "fill_id", "tradeId")
        if (
            not client_id
            or not order_id
            or not fill_id
            or str(row.get("instrument_id") or row.get("instId") or "") != instrument
        ):
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_mapping_invalid")
        pair = (order_id, fill_id)
        if client_id in exchange_fills and exchange_fills[client_id] != pair:
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_exchange_mapping_conflict")
        exchange_fills[client_id] = pair

    lifecycle_by_client: dict[str, tuple[str, str, str]] = {}
    evidence_run_ids: set[str] = set()
    for event in events:
        if str(event.get("event_type") or "") != "order_lifecycle":
            continue
        run_id = _owned_restore_run_id(event.get("run_id"))
        evidence_run_ids.add(run_id)
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_lifecycle_invalid")
        oms = payload.get("oms")
        fills_payload = payload.get("fills")
        if not isinstance(oms, Mapping) or not isinstance(fills_payload, Sequence) or isinstance(fills_payload, (str, bytes)):
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_lifecycle_invalid")
        client_id = _owned_restore_record_id(oms, "client_order_id", "clOrdId")
        order_id = _owned_restore_record_id(payload, "exchange_order_id", "order_id", "ordId") or _owned_restore_record_id(oms, "broker_order_id", "order_id")
        matching_fills = [
            row for row in fills_payload
            if isinstance(row, Mapping)
            and _owned_restore_record_id(row, "client_order_id", "clOrdId") == client_id
        ]
        if not client_id or not order_id or len(matching_fills) != 1:
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_lifecycle_invalid")
        fill = matching_fills[0]
        fill_id = _owned_restore_record_id(fill, "fill_id", "tradeId")
        if (
            not fill_id
            or str(fill.get("instrument_id") or fill.get("instId") or "") != instrument
            or str(payload.get("exchange_state") or "") != "filled"
            or str(oms.get("status") or "") not in {"filled", "reconciled"}
        ):
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_lifecycle_invalid")
        triple = (order_id, fill_id, run_id)
        previous = lifecycle_by_client.get(client_id)
        if previous is not None and previous != triple:
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_lifecycle_conflict")
        lifecycle_by_client[client_id] = triple
    if not lifecycle_by_client:
        raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_lifecycle_missing")

    ledger_by_run: dict[str, set[tuple[str, str, str]]] = {}
    for event in events:
        if str(event.get("event_type") or "") != "ledger_uow_committed":
            continue
        run_id = _owned_restore_run_id(event.get("run_id"))
        evidence_run_ids.add(run_id)
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        order_ledger = payload.get("order_ledger")
        fills_ledger = payload.get("fill_ledger")
        if not isinstance(order_ledger, Mapping) or not isinstance(fills_ledger, Sequence) or isinstance(fills_ledger, (str, bytes)):
            continue
        order_rows = order_ledger.get("orders")
        if not isinstance(order_rows, Sequence) or isinstance(order_rows, (str, bytes)):
            continue
        orders_by_client = {
            _owned_restore_record_id(row, "client_order_id", "clOrdId"): _owned_restore_record_id(row, "order_id", "ordId")
            for row in order_rows
            if isinstance(row, Mapping)
            and _owned_restore_record_id(row, "client_order_id", "clOrdId")
        }
        triples = ledger_by_run.setdefault(run_id, set())
        for fill in fills_ledger:
            if not isinstance(fill, Mapping):
                continue
            client_id = _owned_restore_record_id(fill, "client_order_id", "clOrdId")
            fill_id = _owned_restore_record_id(fill, "fill_id", "tradeId")
            order_id = _owned_restore_record_id(fill, "order_id", "ordId") or orders_by_client.get(client_id, "")
            if client_id and order_id and fill_id:
                triples.add((client_id, order_id, fill_id))
    if len(evidence_run_ids) != 1:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_run_id_ambiguous"
        )
    authoritative_run_id = next(iter(evidence_run_ids))
    authoritative_namespace = _partial_identity_namespace(authoritative_run_id)
    if str(client_order_namespace) != authoritative_namespace:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_client_order_namespace_mismatch"
        )
    if any(
        not client_id.startswith(authoritative_namespace)
        for client_id in lifecycle_by_client
    ):
        raise OkxDemoPaperRuntimeError(
            "okx_demo_owned_id_restore_client_order_namespace_mismatch"
        )
    projection_rows: list[dict[str, str]] = []
    for client_id, (order_id, fill_id, run_id) in sorted(lifecycle_by_client.items()):
        triple = (client_id, order_id, fill_id)
        if (
            not run_id
            or triple not in ledger_by_run.get(run_id, set())
            or exchange_orders.get(client_id) != (order_id, instrument)
            or exchange_fills.get(client_id) != (order_id, fill_id)
        ):
            raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_three_way_intersection_invalid")
        projection_rows.append(
            {
                "client_order_id": client_id,
                "order_id": order_id,
                "fill_id": fill_id,
                "run_id": run_id,
            }
        )
    all_order_ids = [row["order_id"] for row in projection_rows]
    all_fill_ids = [row["fill_id"] for row in projection_rows]
    if len(set(all_order_ids)) != len(all_order_ids) or len(set(all_fill_ids)) != len(all_fill_ids):
        raise OkxDemoPaperRuntimeError("okx_demo_owned_id_restore_identity_conflict")
    source_snapshot_hash = _canonical_sha256(
        {
            "runtime_events": file_hashes["runtime_events"],
            "runtime_state": file_hashes["runtime_state"],
            "receipt_ledger": file_hashes["receipt_ledger"],
        }
    )
    return {
        "enabled": True,
        "identity_only": True,
        "archive_id": archive_id,
        "archive_manifest_sha256": manifest_sha,
        "archive_claimed_manifest_hash": claimed_manifest_hash,
        "archive_verification_sha256": verification_sha,
        "source_snapshot_sha256": source_snapshot_hash,
        "source_head": source_head,
        "current_head": current_head,
        "environment": environment,
        "instrument_id": instrument,
        "margin_mode": "isolated",
        "account_identity": expected_account_identity,
        "credential_identity": expected_credential_identity,
        "client_order_namespace": authoritative_namespace,
        "owned_client_order_ids": [row["client_order_id"] for row in projection_rows],
        "owned_triples": projection_rows,
        "opening_allowed": False,
        "position_restored": False,
        "order_capability_restored": False,
        "paper_unlock": False,
        "promotion_unlock": False,
        "live_unlock": False,
        "receipt_ledger_not_used_as_ownership_proof": True,
        "exchange_snapshot_not_used_as_ownership_proof": True,
    }


def _safe_json(value: Any) -> Any:
    """Return a JSON-shaped copy for durable receipts without secrets."""

    return json.loads(
        json.dumps(value, ensure_ascii=False, default=str)
    )


def _safe_probe_text(
    value: Any,
    *,
    credentials: Any = None,
    max_length: int = 256,
) -> str:
    return _strict_probe_text(
        value,
        credentials=credentials,
        max_length=max_length,
    )


def _project_probe_diagnostics(
    value: Any,
    *,
    credentials: Any = None,
) -> list[dict[str, Any]]:
    rows = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
    projected: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        protocol = raw.get("protocol")
        protocol = protocol if isinstance(protocol, Mapping) else {}
        progress = raw.get("subscription_progress")
        progress = progress if isinstance(progress, Mapping) else {}
        stage = str(raw.get("stage") or "unknown")
        if stage not in {
            "connect",
            "login",
            "subscribe",
            "startup_snapshot",
            "reconnect",
            "reconciliation",
        }:
            stage = "unknown"
        projected_row: dict[str, Any] = {
            "stage": stage,
            "exception_type": _safe_probe_code(raw.get("exception_type")) or "ProbeFailure",
            "message": _safe_probe_text(raw.get("message"), credentials=credentials),
            "protocol": {
                "sCode": _safe_probe_protocol_code(protocol.get("sCode")),
                "msg": _safe_probe_text(protocol.get("msg"), credentials=credentials),
            },
            "subscription_progress": {
                "observed_channels": _safe_probe_channels(
                    progress.get("observed_channels")
                ),
                "expected_channels": _safe_probe_channels(
                    progress.get("expected_channels")
                ),
                "complete": progress.get("complete") is True,
            },
        }
        if raw.get("error_code") is not None:
            projected_row["error_code"] = (
                _safe_probe_code(raw.get("error_code")) or "probe_failed"
            )
        reconciliation = raw.get("reconciliation_progress")
        if isinstance(reconciliation, Mapping):
            projected_row["reconciliation_progress"] = {
                str(key): value is True
                for key, value in reconciliation.items()
                if str(key)
                in {
                    "startup_reconciled",
                    "disconnect_cancel_only_observed",
                    "reconnect_login_observed",
                    "reconnect_resubscribed",
                    "reconnect_rest_reconciled",
                    "opening_allowed_after_reconciliation",
                }
            }
        generation = raw.get("generation")
        if isinstance(generation, Mapping):
            projected_row["generation"] = {
                "before": str(generation.get("before") or ""),
                "after": str(generation.get("after") or ""),
                "match": generation.get("match") is True,
            }
        verification = raw.get("receipt_verification")
        if isinstance(verification, Mapping):
            projected_row["receipt_verification"] = {
                "mapping": verification.get("mapping") is True,
                "source_head_present": verification.get(
                    "source_head_present"
                )
                is True,
                "source_head_match": verification.get("source_head_match")
                is True,
                "opening_allowed": verification.get("opening_allowed") is True,
                "valid": verification.get("valid") is True,
            }
        if raw.get("blocker_count") is not None:
            try:
                projected_row["blocker_count"] = max(0, int(raw["blocker_count"]))
            except (TypeError, ValueError):
                projected_row["blocker_count"] = 0
        raw_blocker_codes = raw.get("reconciliation_blocker_codes")
        if isinstance(raw_blocker_codes, Sequence) and not isinstance(
            raw_blocker_codes,
            (str, bytes),
        ):
            projected_row.update(
                _project_reconciliation_blocker_evidence(raw_blocker_codes)
            )
        projected.append(projected_row)
    return projected


_PRIVATE_WS_PROBE_REQUIRED_FIELDS = (
    "startup_reconciled",
    "disconnect_cancel_only_observed",
    "reconnect_login_observed",
    "reconnect_resubscribed",
    "reconnect_rest_reconciled",
    "opening_allowed_after_reconciliation",
)


def _private_ws_probe_receipt_valid(
    value: Mapping[str, Any],
    *,
    current_head: str,
) -> bool:
    source_head = str(value.get("source_head") or "")
    return (
        bool(source_head)
        and source_head == str(current_head)
        and value.get("credentials_redacted") is True
        and all(value.get(field) is True for field in _PRIVATE_WS_PROBE_REQUIRED_FIELDS)
    )


def _private_ws_current_receipt_valid(
    value: Mapping[str, Any],
    *,
    current_head: str,
) -> bool:
    source_head = str(value.get("source_head") or "")
    required = (
        "connected",
        "listener_alive",
        "reconnect_login_observed",
        "reconnect_resubscribed",
        "reconnect_rest_reconciled",
        "opening_allowed_after_reconciliation",
    )
    return (
        bool(source_head)
        and source_head == str(current_head)
        and all(value.get(field) is True for field in required)
    )


def _diagnostic_mapping_from_exception(exc: BaseException) -> Mapping[str, Any]:
    try:
        parsed = json.loads(str(exc))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _build_runtime_probe_diagnostics(
    *,
    error_code: str,
    credentials: Any = None,
    exception: BaseException | None = None,
    message: str = "",
    probe: Mapping[str, Any] | None = None,
    current_head: str = "",
    generation_before: Any = "",
    generation_after: Any = "",
    receipt_valid: bool = False,
) -> list[dict[str, Any]]:
    parsed_exception = _diagnostic_mapping_from_exception(exception) if exception else {}
    source = dict(probe or {})
    if parsed_exception:
        source = {**parsed_exception, **source}
    raw_probe_diagnostics = source.get("probe_diagnostics")
    if isinstance(raw_probe_diagnostics, Sequence) and not isinstance(
        raw_probe_diagnostics,
        (str, bytes),
    ):
        first_probe_diagnostic = next(
            (
                row
                for row in raw_probe_diagnostics
                if isinstance(row, Mapping)
            ),
            None,
        )
        if first_probe_diagnostic is not None:
            source = {**source, **dict(first_probe_diagnostic)}
    stage = str(source.get("stage") or "reconciliation")
    if stage not in {
        "connect",
        "login",
        "subscribe",
        "startup_snapshot",
        "reconnect",
        "reconciliation",
    }:
        stage = "reconciliation"
    exception_type = str(
        source.get("exception_type")
        or (type(exception).__name__ if exception is not None else "ProbeFailure")
    )
    diagnostic_message = source.get("message") or message or error_code
    protocol = source.get("protocol")
    protocol = protocol if isinstance(protocol, Mapping) else {}
    subscription_progress = source.get("subscription_progress")
    subscription_progress = (
        subscription_progress
        if isinstance(subscription_progress, Mapping)
        else {}
    )
    reconciliation_progress = {
        field: source.get(field) is True
        for field in _PRIVATE_WS_PROBE_REQUIRED_FIELDS
    }
    generation_before_text = str(generation_before or "")
    generation_after_text = str(generation_after or "")
    raw = {
        "stage": stage,
        "exception_type": exception_type,
        "message": diagnostic_message,
        "error_code": error_code,
        "protocol": protocol,
        "subscription_progress": subscription_progress,
        "reconciliation_progress": reconciliation_progress,
        "generation": {
            "before": generation_before_text,
            "after": generation_after_text,
            "match": generation_before_text == generation_after_text,
        },
        "receipt_verification": {
            "mapping": bool(probe is not None or parsed_exception),
            "source_head_present": bool(source.get("source_head")),
            "source_head_match": bool(
                source.get("source_head")
                and current_head
                and str(source.get("source_head")) == str(current_head)
            ),
            "opening_allowed": source.get(
                "opening_allowed_after_reconciliation"
            )
            is True,
            "valid": receipt_valid,
        },
        "reconciliation_blocker_codes": source.get(
            "reconciliation_blocker_codes"
        )
        if source.get("reconciliation_blocker_codes") is not None
        else source.get("blockers"),
    }
    return _project_probe_diagnostics([raw], credentials=credentials)


def _partial_identity_namespace(runtime_run_id: str) -> str:
    return f"btcDP{str(runtime_run_id)[:8]}"


def _partial_authoritative_identity_projection(
    *,
    runtime_run_id: str,
    source_head: str,
    opening_clord_id: str,
    close_clord_id: str,
    algo_clord_id: str,
    entry_order_id: str,
    close_order_id: str,
    entry_fill_ids: Sequence[str],
    close_fill_ids: Sequence[str],
    entry_fill_order_ids: Sequence[str],
    close_fill_order_ids: Sequence[str],
    entry_fill_client_order_ids: Sequence[str],
    close_fill_client_order_ids: Sequence[str],
    algo_id: str,
    algo_parent_clord_id: str,
    entry_fill_contracts: str,
    close_fill_contracts: str,
    pre_reconciliation_sha256: str,
    post_reconciliation_sha256: str,
    final_flat: bool,
    final_no_pending_orders: bool,
    final_no_pending_algo_orders: bool,
    final_ledger_reconciled: bool,
    final_private_ws_reconciled: bool,
) -> dict[str, Any]:
    """Build the immutable identity projection owned by one runtime run.

    Venue IDs are intentionally not trusted merely because they match a
    printable format.  This projection is committed to the runtime's
    append-only event/state store and later returned as controller attestation
    so the application receipt can compare every identity to the same run,
    controller boundary, source head, and client-order namespace.
    """

    return {
        "authority_version": OKX_DEMO_PARTIAL_FILL_AUTHORITY_VERSION,
        "runtime_boundary": OKX_DEMO_PARTIAL_FILL_RUNTIME_BOUNDARY,
        "runtime_version": OKX_DEMO_PAPER_RUNTIME_VERSION,
        "controller_type": "OkxDemoPaperRuntimeController",
        "source_head": str(source_head),
        "runtime_run_id": str(runtime_run_id),
        "identity_namespace": _partial_identity_namespace(runtime_run_id),
        "clOrdId": str(opening_clord_id),
        "closeClOrdId": str(close_clord_id),
        "algoClOrdId": str(algo_clord_id),
        "entry_order_id": str(entry_order_id),
        "close_order_id": str(close_order_id),
        "entry_fill_ids": [str(value) for value in entry_fill_ids],
        "close_fill_ids": [str(value) for value in close_fill_ids],
        "entry_fill_order_ids": [
            str(value) for value in entry_fill_order_ids
        ],
        "close_fill_order_ids": [
            str(value) for value in close_fill_order_ids
        ],
        "entry_fill_client_order_ids": [
            str(value) for value in entry_fill_client_order_ids
        ],
        "close_fill_client_order_ids": [
            str(value) for value in close_fill_client_order_ids
        ],
        "entry_order_client_order_id": str(opening_clord_id),
        "close_order_client_order_id": str(close_clord_id),
        "algo_id": str(algo_id),
        "algo_parent_cl_ord_id": str(algo_parent_clord_id),
        "entry_fill_contracts": str(entry_fill_contracts),
        "close_fill_contracts": str(close_fill_contracts),
        "pre_reconciliation_sha256": str(pre_reconciliation_sha256),
        "post_reconciliation_sha256": str(post_reconciliation_sha256),
        "final_flat": bool(final_flat),
        "final_no_pending_orders": bool(final_no_pending_orders),
        "final_no_pending_algo_orders": bool(final_no_pending_algo_orders),
        "final_ledger_reconciled": bool(final_ledger_reconciled),
        "final_private_ws_reconciled": bool(final_private_ws_reconciled),
    }


def _partial_authoritative_receipt_sha256(
    projection: Mapping[str, Any],
) -> str:
    return _canonical_sha256(
        {
            "authority_version": OKX_DEMO_PARTIAL_FILL_AUTHORITY_VERSION,
            "identity_projection": _safe_json(projection),
        }
    )


def _partial_entry_truth(
    snapshot: Mapping[str, Any],
    *,
    client_order_id: str,
    algo_client_order_id: str,
    requested_contracts: Decimal,
) -> dict[str, Any]:
    """Classify one venue-observed IOC entry without manufacturing a fill.

    The order, fills, position, and attached OCO must all agree.  A missing
    identity, a pending remainder, or any quantity disagreement is a broker
    truth discrepancy rather than a partial-fill success.
    """

    def value(row: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            raw = row.get(key)
            if raw is not None and str(raw) != "":
                return str(raw)
        return ""

    def strict_decimal(value_raw: Any) -> Decimal | None:
        if isinstance(value_raw, bool) or value_raw is None:
            return None
        try:
            parsed = Decimal(str(value_raw))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    def valid_identity(value_raw: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value_raw))

    order_rows = [
        row
        for row in [
            *_sequence_mappings(snapshot.get("orders")),
            *_sequence_mappings(snapshot.get("pending_orders")),
        ]
        if _client_order_id(row) == client_order_id
    ]
    raw_order_ids = [value(row, "order_id", "ordId") for row in order_rows]
    duplicate_order_identity = bool(
        any(not order_id for order_id in raw_order_ids)
        or len(raw_order_ids) != len(set(raw_order_ids))
    )
    order = order_rows[0] if len(order_rows) == 1 else {}
    order_id = value(order, "order_id", "ordId")
    order_client_order_id = _client_order_id(order)
    order_instrument_id = value(order, "instrument_id", "instId")
    order_type = value(order, "order_type", "ordType")
    order_size = strict_decimal(value(order, "size", "sz"))
    order_quantity = strict_decimal(
        value(order, "filled_size", "accFillSz")
    )
    order_state = value(order, "state")
    pending_order = any(
        _client_order_id(row) == client_order_id
        for row in _sequence_mappings(snapshot.get("pending_orders"))
    )
    fill_rows = [
        row
        for row in _sequence_mappings(snapshot.get("fills"))
        if (
            _client_order_id(row) == client_order_id
            or (order_id and value(row, "order_id", "ordId") == order_id)
        )
    ]
    raw_fill_ids = [value(row, "fill_id", "tradeId") for row in fill_rows]
    duplicate_fill_identity = bool(
        any(not fill_id for fill_id in raw_fill_ids)
        or len(raw_fill_ids) != len(set(raw_fill_ids))
    )
    fill_order_ids = [value(row, "order_id", "ordId") for row in fill_rows]
    fill_client_order_ids = [_client_order_id(row) for row in fill_rows]
    fill_sizes: list[Decimal] = []
    fill_sizes_valid = True
    for row in fill_rows:
        size = strict_decimal(value(row, "size", "fillSz"))
        if size is None or size <= 0:
            fill_sizes_valid = False
            continue
        fill_sizes.append(size)
    fill_quantity = sum(fill_sizes, Decimal("0"))
    gross_position = _gross_position_contracts(
        snapshot.get("positions", [])
    )
    positions = _sequence_mappings(snapshot.get("positions"))
    position_rows = [
        row
        for row in positions
        if value(row, "instrument_id", "instId") == OKX_DEMO_INSTRUMENT_ID
    ]
    position_identity_valid = bool(
        fill_quantity == 0
        or (
            len(position_rows) == 1
            and value(position_rows[0], "position_side", "posSide") == "long"
            and strict_decimal(value(position_rows[0], "contracts", "pos"))
            == fill_quantity
        )
    )
    matching_algos = [
        row
        for row in _sequence_mappings(snapshot.get("pending_algo_orders"))
        if value(row, "algo_client_order_id", "algoClOrdId")
        == algo_client_order_id
        or value(row, "parent_client_order_id", "parentClOrdId")
        == client_order_id
    ]
    protection = (
        matching_algos[0]
        if len(matching_algos) == 1
        and value(matching_algos[0], "algo_client_order_id", "algoClOrdId")
        == algo_client_order_id
        else {}
    )
    algo_id = value(protection, "algo_id", "algoId", "attachAlgoId")
    algo_parent_client_order_id = value(
        protection,
        "parent_client_order_id",
        "parentClOrdId",
    )
    protection_verified = bool(
        protection
        and valid_identity(algo_id)
        and algo_parent_client_order_id == client_order_id
        and value(protection, "instrument_id", "instId")
        == OKX_DEMO_INSTRUMENT_ID
        and value(protection, "position_side", "posSide") == "long"
        and strict_decimal(value(protection, "size", "sz")) == fill_quantity
        and value(protection, "state")
        in {"live", "effective", "partially_effective"}
        and value(protection, "take_profit_order_price", "tpOrdPx") == "-1"
        and value(protection, "stop_loss_order_price", "slOrdPx") == "-1"
    )
    identity_complete = bool(
        len(order_rows) == 1
        and not duplicate_order_identity
        and valid_identity(order_id)
        and order_client_order_id == client_order_id
        and order_instrument_id == OKX_DEMO_INSTRUMENT_ID
        and order_type == "ioc"
        and order_size == requested_contracts
        and order_state
        and order_quantity is not None
        and not duplicate_fill_identity
        and all(
            valid_identity(fill_id)
            and fill_order_id == order_id
            and fill_client_order_id == client_order_id
            and value(row, "instrument_id", "instId") == OKX_DEMO_INSTRUMENT_ID
            for row, fill_id, fill_order_id, fill_client_order_id in zip(
                fill_rows,
                raw_fill_ids,
                fill_order_ids,
                fill_client_order_ids,
            )
        )
        and fill_sizes_valid
        and position_identity_valid
        and (fill_quantity == 0 or protection_verified)
    )
    quantity_consistent = bool(
        order_quantity is not None
        and order_quantity == fill_quantity
        and fill_quantity >= 0
        and fill_quantity <= requested_contracts
    )
    classification = "broker_truth_discrepancy"
    if (
        identity_complete
        and quantity_consistent
        and not pending_order
        and fill_quantity == 0
        and gross_position == 0
        and not fill_rows
        and order_state in {"canceled", "cancelled", "mmp_canceled", "rejected"}
    ):
        classification = "zero_fill"
    elif (
        identity_complete
        and quantity_consistent
        and not pending_order
        and fill_quantity == requested_contracts
        and gross_position == requested_contracts
        and bool(fill_rows)
    ):
        classification = "full_fill"
    elif (
        identity_complete
        and quantity_consistent
        and not pending_order
        and Decimal("0") < fill_quantity < requested_contracts
        and gross_position == fill_quantity
        and bool(fill_rows)
    ):
        classification = "partial_fill"
    fill_ids = sorted(raw_fill_ids)
    return {
        "classification": classification,
        "synthetic": False,
        "client_order_id": client_order_id,
        "exchange_order_id": order_id,
        "order_state": order_state,
        "requested_contracts": _text(requested_contracts),
        "filled_contracts": _text(fill_quantity),
        "order_filled_contracts": _text(order_quantity or Decimal("0")),
        "position_contracts": _text(gross_position),
        "fill_ids": fill_ids,
        "fill_order_ids": fill_order_ids,
        "fill_client_order_ids": fill_client_order_ids,
        "order_client_order_id": order_client_order_id,
        "order_type": order_type,
        "order_observed": len(order_rows) == 1,
        "fill_observed": bool(fill_rows),
        "position_observed": position_identity_valid,
        "pending_order_observed": pending_order,
        "protection_verified": protection_verified,
        "algo_client_order_id": algo_client_order_id,
        "algo_id": algo_id,
        "algo_parent_client_order_id": algo_parent_client_order_id,
        "duplicate_order_identity": duplicate_order_identity,
        "duplicate_fill_identity": duplicate_fill_identity,
        "identity_discrepancy": bool(
            duplicate_order_identity
            or duplicate_fill_identity
            or not identity_complete
        ),
    }


def _partial_close_truth(
    snapshot: Mapping[str, Any],
    *,
    client_order_id: str,
    expected_contracts: Decimal,
    entry_order_id: str,
    entry_fill_ids: Sequence[str],
) -> dict[str, Any]:
    """Require one owned, fully filled reduce-only close identity."""

    def value(row: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            raw = row.get(key)
            if raw is not None and str(raw) != "":
                return str(raw)
        return ""

    def strict_decimal(value_raw: Any) -> Decimal | None:
        if isinstance(value_raw, bool) or value_raw is None:
            return None
        try:
            parsed = Decimal(str(value_raw))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    def valid_identity(value_raw: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value_raw))

    order_rows = [
        row
        for row in [
            *_sequence_mappings(snapshot.get("orders")),
            *_sequence_mappings(snapshot.get("pending_orders")),
        ]
        if _client_order_id(row) == client_order_id
    ]
    order_ids = [value(row, "order_id", "ordId") for row in order_rows]
    duplicate_order_identity = bool(
        any(not order_id for order_id in order_ids)
        or len(order_ids) != len(set(order_ids))
    )
    order = order_rows[0] if len(order_rows) == 1 else {}
    order_id = value(order, "order_id", "ordId")
    order_quantity = strict_decimal(value(order, "filled_size", "accFillSz"))
    order_state = value(order, "state")
    order_side = value(order, "side")
    order_position_side = value(order, "position_side", "posSide")
    pending_order = any(
        _client_order_id(row) == client_order_id
        for row in _sequence_mappings(snapshot.get("pending_orders"))
    )
    fill_rows = [
        row
        for row in _sequence_mappings(snapshot.get("fills"))
        if (
            _client_order_id(row) == client_order_id
            or (order_id and value(row, "order_id", "ordId") == order_id)
        )
    ]
    fill_ids = [value(row, "fill_id", "tradeId") for row in fill_rows]
    fill_order_ids = [value(row, "order_id", "ordId") for row in fill_rows]
    fill_client_order_ids = [_client_order_id(row) for row in fill_rows]
    fill_quantity = Decimal("0")
    fill_sizes_valid = True
    for row in fill_rows:
        size = strict_decimal(value(row, "size", "fillSz"))
        if size is None or size <= 0:
            fill_sizes_valid = False
            continue
        fill_quantity += size
    duplicate_fill_identity = bool(
        any(not fill_id for fill_id in fill_ids)
        or len(fill_ids) != len(set(fill_ids))
    )
    identity_complete = bool(
        len(order_rows) == 1
        and not duplicate_order_identity
        and valid_identity(order_id)
        and _client_order_id(order) == client_order_id
        and order_state == "filled"
        and order_side == "sell"
        and order_position_side == "long"
        and order_quantity == expected_contracts
        and fill_rows
        and not duplicate_fill_identity
        and fill_sizes_valid
        and all(
            valid_identity(fill_id)
            and fill_order_id == order_id
            and fill_client_order_id == client_order_id
            and value(row, "instrument_id", "instId")
            == OKX_DEMO_INSTRUMENT_ID
            for row, fill_id, fill_order_id, fill_client_order_id in zip(
                fill_rows,
                fill_ids,
                fill_order_ids,
                fill_client_order_ids,
            )
        )
        and fill_quantity == expected_contracts
        and not pending_order
        and order_id != entry_order_id
        and not set(fill_ids) & set(entry_fill_ids)
    )
    return {
        "classification": (
            "close_filled"
            if identity_complete
            else "broker_truth_discrepancy"
        ),
        "order_id": order_id,
        "order_state": order_state,
        "filled_contracts": _text(fill_quantity),
        "order_filled_contracts": _text(order_quantity or Decimal("0")),
        "fill_ids": sorted(fill_ids),
        "fill_order_ids": fill_order_ids,
        "fill_client_order_ids": fill_client_order_ids,
        "duplicate_order_identity": duplicate_order_identity,
        "duplicate_fill_identity": duplicate_fill_identity,
        "identity_discrepancy": not identity_complete,
    }


def _partial_reconciliation(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    client_order_id: str,
    algo_client_order_id: str,
    expected_filled_contracts: Decimal,
    ledger: Mapping[str, Any],
    private_ws: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare venue truth across the bounded private-stream reconnect."""

    before_truth = _partial_entry_truth(
        before,
        client_order_id=client_order_id,
        algo_client_order_id=algo_client_order_id,
        requested_contracts=OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS,
    )
    after_truth = _partial_entry_truth(
        after,
        client_order_id=client_order_id,
        algo_client_order_id=algo_client_order_id,
        requested_contracts=OKX_DEMO_PARTIAL_FILL_DRILL_CONTRACTS,
    )
    before_order = str(before_truth.get("exchange_order_id") or "")
    after_order = str(after_truth.get("exchange_order_id") or "")
    before_fill_ids = tuple(before_truth.get("fill_ids") or [])
    after_fill_ids = tuple(after_truth.get("fill_ids") or [])
    expected = _text(expected_filled_contracts)
    identity_sync = bool(
        before_truth.get("identity_discrepancy") is False
        and after_truth.get("identity_discrepancy") is False
        and before_truth.get("classification") == "partial_fill"
        and after_truth.get("classification") == "partial_fill"
    )
    order_sync = bool(
        before_order
        and before_order == after_order == str(after_truth.get("exchange_order_id") or "")
        and after_truth.get("order_observed") is True
        and after_truth.get("pending_order_observed") is False
    )
    fill_sync = bool(
        before_fill_ids
        and before_fill_ids == after_fill_ids
        and str(after_truth.get("filled_contracts") or "") == expected
        and after_truth.get("fill_observed") is True
    )
    position_sync = bool(
        str(after_truth.get("position_contracts") or "") == expected
        and after_truth.get("classification") == "partial_fill"
    )
    oco_sync = bool(
        after_truth.get("protection_verified") is True
        and str(after_truth.get("algo_client_order_id") or "")
        == algo_client_order_id
    )
    ledger_sync = bool(
        ledger.get("status") == "reconciled"
        and ledger.get("current_state_exchange_snapshot_match") is True
        and str(ledger.get("exchange_snapshot_sha256") or "")
        == _fault_ledger_snapshot_sha256(after)
    )
    private_ws_sync = bool(
        private_ws.get("connected") is True
        and private_ws.get("listener_alive") is True
        and private_ws.get("opening_allowed_after_reconciliation") is True
        and private_ws.get("reconnect_rest_reconciled") is True
    )
    return {
        "order_sync": order_sync,
        "fill_sync": fill_sync,
        "position_sync": position_sync,
        "oco_sync": oco_sync,
        "ledger_sync": ledger_sync,
        "private_ws_sync": private_ws_sync,
        "identity_sync": identity_sync,
        "match": all(
            (
                identity_sync,
                order_sync,
                fill_sync,
                position_sync,
                oco_sync,
                ledger_sync,
                private_ws_sync,
            )
        ),
        "expected_filled_contracts": expected,
        "before": _safe_json(before_truth),
        "after": _safe_json(after_truth),
        "synthetic": False,
    }


def _fault_reconciliation_facts(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Stable order/fill/position/protection evidence across a reconnect."""

    field_sets = {
        "orders": (
            "order_id",
            "client_order_id",
            "instrument_id",
            "side",
            "position_side",
            "state",
            "size",
            "filled_size",
        ),
        "fills": (
            "fill_id",
            "order_id",
            "client_order_id",
            "instrument_id",
            "side",
            "position_side",
            "price",
            "size",
        ),
        "positions": (
            "instrument_id",
            "position_side",
            "contracts",
            "average_price",
            "mark_price",
            "liquidation_price",
        ),
        "pending_algo_orders": (
            "algo_id",
            "algo_client_order_id",
            "parent_client_order_id",
            "instrument_id",
            "position_side",
            "size",
            "order_type",
            "state",
            "take_profit_trigger",
            "take_profit_trigger_type",
            "take_profit_order_price",
            "stop_loss_trigger",
            "stop_loss_trigger_type",
            "stop_loss_order_price",
        ),
    }
    result: dict[str, Any] = {}
    for name, fields in field_sets.items():
        rows = [
            {field: str(row.get(field) or "") for field in fields}
            for row in snapshot.get(name, [])
            if isinstance(row, Mapping)
        ]
        result[name] = sorted(
            rows,
            key=lambda row: json.dumps(
                row, sort_keys=True, separators=(",", ":")
            ),
        )
    return result


def _incident_recovery_identity_projection(
    snapshot: Mapping[str, Any],
    *,
    owned_client_order_ids: Sequence[str],
) -> dict[str, Any]:
    """Strict durable identity used across incident-recovery reconnects.

    Exchange valuation fields are expected to move while the query-only
    preflight and private-WS probe run.  They are deliberately excluded here;
    order/fill lifecycle, position cost basis, pending identities, exact OCO
    protection, and funding-ledger economics remain fail-closed.
    """

    owned_ids = {str(value) for value in owned_client_order_ids if str(value)}
    field_sets = {
        "owned_orders": (
            "order_id",
            "client_order_id",
            "instrument_id",
            "side",
            "position_side",
            "order_type",
            "state",
            "price",
            "average_price",
            "size",
            "filled_size",
            "fee",
            "pnl",
        ),
        "owned_fills": (
            "fill_id",
            "order_id",
            "client_order_id",
            "instrument_id",
            "side",
            "position_side",
            "state",
            "price",
            "size",
            "fee",
            "fee_currency",
            "pnl",
            "execution_type",
            "timestamp_ms",
        ),
        "positions": (
            "instrument_id",
            "position_side",
            "margin_mode",
            "contracts",
            "average_price",
            "leverage",
        ),
        "pending_orders": (
            "order_id",
            "client_order_id",
            "instrument_id",
            "side",
            "position_side",
            "order_type",
            "state",
            "price",
            "average_price",
            "size",
            "filled_size",
        ),
        "pending_algo_orders": (
            "algo_id",
            "algo_client_order_id",
            "parent_client_order_id",
            "instrument_id",
            "position_side",
            "size",
            "order_type",
            "state",
            "take_profit_trigger",
            "take_profit_trigger_type",
            "take_profit_order_price",
            "stop_loss_trigger",
            "stop_loss_trigger_type",
            "stop_loss_order_price",
        ),
        "funding_bills": (
            "bill_id",
            "instrument_id",
            "currency",
            "type",
            "sub_type",
            "balance_change",
            "fee",
            "pnl",
            "timestamp_ms",
        ),
    }
    source_names = {
        "owned_orders": "orders",
        "owned_fills": "fills",
        "positions": "positions",
        "pending_orders": "pending_orders",
        "pending_algo_orders": "pending_algo_orders",
        "funding_bills": "bills",
    }
    result: dict[str, Any] = {}
    for projection_name, fields in field_sets.items():
        source_name = source_names[projection_name]
        rows = []
        for row in snapshot.get(source_name, []):
            if not isinstance(row, Mapping):
                continue
            if projection_name in {"owned_orders", "owned_fills"} and str(
                row.get("client_order_id") or ""
            ) not in owned_ids:
                continue
            if projection_name == "funding_bills" and not (
                str(row.get("type") or "") == "8"
                or str(row.get("sub_type") or "") == "173"
            ):
                continue
            rows.append(
                {
                    field: (
                        "" if row.get(field) is None else str(row.get(field))
                    )
                    for field in fields
                }
            )
        result[projection_name] = sorted(
            rows,
            key=lambda row: json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return result


def _incident_recovery_identity_sha256(
    snapshot: Mapping[str, Any],
    *,
    owned_client_order_ids: Sequence[str],
) -> str:
    return _canonical_sha256(
        _incident_recovery_identity_projection(
            snapshot,
            owned_client_order_ids=owned_client_order_ids,
        )
    )


def _hosted_oco_terminal_exit_projection(
    snapshot: Mapping[str, Any],
    *,
    authorization: Mapping[str, str],
    current_head: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Bind one exchange-hosted OCO terminal exit without widening unknown-fill.

    This admission is intentionally limited to the fixed current-main incident.
    The caller has already authenticated an immutable recovery binding; this
    helper derives all exchange identity from the normalized read-only snapshot
    and never treats an ``O`` prefix, a timestamp, or a price as ownership.
    """

    expected = _FRESH_STATE_EMERGENCY_FIXED_IDENTITY
    blockers: list[str] = []
    if not re.fullmatch(r"[0-9a-f]{40}", current_head):
        blockers.append("okx_demo_hosted_oco_exit_head_invalid")
    if not (
        re.fullmatch(
            r"[0-9a-f]{40}",
            str(authorization.get("failed_receipt_source_head") or ""),
        )
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(authorization.get("failed_receipt_sha256") or ""),
        )
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(authorization.get("flat_identity_sha256") or ""),
        )
    ):
        blockers.append("okx_demo_hosted_oco_exit_binding_identity_invalid")
    for field, expected_value in (
        ("opening_cl_ord_id", expected["entry_cl_ord_id"]),
        ("opening_order_id", expected["entry_ord_id"]),
        ("algo_cl_ord_id", expected["oco_algo_cl_ord_id"]),
        ("algo_id", expected["oco_algo_id"]),
    ):
        if str(authorization.get(field) or "") != expected_value:
            blockers.append("okx_demo_hosted_oco_exit_fixed_identity_mismatch")
            break
    exit_client_order_id = str(authorization.get("expected_close_cl_ord_id") or "")
    if not re.fullmatch(r"O[0-9]{10,}", exit_client_order_id):
        blockers.append("okx_demo_hosted_oco_exit_client_order_id_invalid")

    positions = snapshot.get("positions")
    if not isinstance(positions, Sequence) or isinstance(positions, (str, bytes)):
        blockers.append("okx_demo_hosted_oco_exit_positions_invalid")
    elif _gross_position_contracts(positions) != 0:
        blockers.append("okx_demo_hosted_oco_exit_position_not_flat")
    for name, blocker in (
        ("pending_orders", "okx_demo_hosted_oco_exit_pending_order_present"),
        ("pending_algo_orders", "okx_demo_hosted_oco_exit_pending_oco_present"),
    ):
        rows = snapshot.get(name)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            blockers.append(blocker.replace("_present", "_invalid"))
        elif rows:
            blockers.append(blocker)

    orders = snapshot.get("orders")
    fills = snapshot.get("fills")
    if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes)):
        blockers.append("okx_demo_hosted_oco_exit_orders_invalid")
        orders = ()
    if not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
        blockers.append("okx_demo_hosted_oco_exit_fills_invalid")
        fills = ()
    order_rows = [row for row in orders if isinstance(row, Mapping)]
    fill_rows = [row for row in fills if isinstance(row, Mapping)]
    if len(order_rows) != len(orders) or len(fill_rows) != len(fills):
        blockers.append("okx_demo_hosted_oco_exit_history_row_invalid")

    entry_rows = [
        row
        for row in order_rows
        if str(row.get("client_order_id") or "") == expected["entry_cl_ord_id"]
        and str(row.get("order_id") or "") == expected["entry_ord_id"]
        and str(row.get("instrument_id") or "") == OKX_DEMO_INSTRUMENT_ID
        and str(row.get("side") or "") == "buy"
        and str(row.get("position_side") or "") == "long"
        and str(row.get("order_type") or "") == "fok"
        and str(row.get("state") or "") == "filled"
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
        and _decimal(row.get("filled_size")) == OKX_DEMO_PAPER_CONTRACTS
    ]
    if len(entry_rows) != 1:
        blockers.append("okx_demo_hosted_oco_exit_entry_order_mismatch")
    entry_fill_rows = [
        row
        for row in fill_rows
        if str(row.get("client_order_id") or "") == expected["entry_cl_ord_id"]
        and str(row.get("order_id") or "") == expected["entry_ord_id"]
        and str(row.get("instrument_id") or "") == OKX_DEMO_INSTRUMENT_ID
        and str(row.get("side") or "") == "buy"
        and str(row.get("position_side") or "") == "long"
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
    ]
    if len(entry_fill_rows) != 1:
        blockers.append("okx_demo_hosted_oco_exit_entry_fill_mismatch")
    elif str(entry_fill_rows[0].get("fill_id") or "") != str(
        authorization.get("opening_fill_id") or ""
    ):
        blockers.append("okx_demo_hosted_oco_exit_entry_fill_identity_mismatch")

    exit_rows = [
        row
        for row in order_rows
        if str(row.get("client_order_id") or "") == exit_client_order_id
        and str(row.get("instrument_id") or "") == OKX_DEMO_INSTRUMENT_ID
        and str(row.get("side") or "") == "sell"
        and str(row.get("position_side") or "") == "long"
        and str(row.get("order_type") or "") == "market"
        and str(row.get("state") or "") == "filled"
        and row.get("reduce_only") is True
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
        and _decimal(row.get("filled_size")) == OKX_DEMO_PAPER_CONTRACTS
    ]
    if len(exit_rows) != 1:
        blockers.append("okx_demo_hosted_oco_exit_order_mismatch")
        exit_order: Mapping[str, Any] = {}
    else:
        exit_order = exit_rows[0]
        if (
            str(exit_order.get("algo_id") or "") != expected["oco_algo_id"]
            or str(exit_order.get("algo_client_order_id") or "")
            != expected["oco_algo_cl_ord_id"]
        ):
            blockers.append("okx_demo_hosted_oco_exit_algo_link_mismatch")
    exit_fill_rows = [
        row
        for row in fill_rows
        if str(row.get("client_order_id") or "") == exit_client_order_id
        and str(row.get("order_id") or "")
        == str(exit_order.get("order_id") or "")
        and str(row.get("instrument_id") or "") == OKX_DEMO_INSTRUMENT_ID
        and str(row.get("side") or "") == "sell"
        and str(row.get("position_side") or "") == "long"
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
    ]
    if len(exit_fill_rows) != 1:
        blockers.append("okx_demo_hosted_oco_exit_fill_mismatch")

    allowed_fill_clients = {expected["entry_cl_ord_id"], exit_client_order_id}
    if any(
        str(row.get("client_order_id") or "") not in allowed_fill_clients
        for row in fill_rows
    ) or len(fill_rows) != 2:
        blockers.append("okx_demo_hosted_oco_exit_foreign_or_duplicate_fill")
    if entry_rows and exit_rows:
        try:
            entry_time = int(str(entry_rows[0].get("updated_at_ms") or ""))
            exit_time = int(str(exit_order.get("created_at_ms") or ""))
        except ValueError:
            blockers.append("okx_demo_hosted_oco_exit_time_invalid")
        else:
            if exit_time < entry_time:
                blockers.append("okx_demo_hosted_oco_exit_time_order_invalid")
    if entry_fill_rows and exit_fill_rows:
        try:
            entry_fill_time = int(str(entry_fill_rows[0].get("timestamp_ms") or ""))
            exit_fill_time = int(str(exit_fill_rows[0].get("timestamp_ms") or ""))
        except ValueError:
            blockers.append("okx_demo_hosted_oco_exit_fill_time_invalid")
        else:
            if exit_fill_time < entry_fill_time:
                blockers.append("okx_demo_hosted_oco_exit_fill_time_order_invalid")
    if blockers:
        return None, _dedupe(blockers)

    projection: dict[str, Any] = {
        "schema_version": "okx_demo_hosted_oco_terminal_exit_ownership_v1",
        "binding_source": str(
            authorization.get("recovery_binding_source")
            or "canonical_incident_recovery_binding"
        ),
        "incident_source_head": str(
            authorization.get("failed_receipt_source_head") or ""
        ),
        "recovery_code_head": current_head,
        "failed_receipt_sha256": str(
            authorization.get("failed_receipt_sha256") or ""
        ),
        "flat_identity_sha256": str(
            authorization.get("flat_identity_sha256") or ""
        ),
        "snapshot_sha256": _fault_ledger_snapshot_sha256(snapshot),
        "entry": {
            "client_order_id": expected["entry_cl_ord_id"],
            "order_id": expected["entry_ord_id"],
            "fill_id": str(entry_fill_rows[0].get("fill_id") or ""),
        },
        "oco": {
            "algo_id": expected["oco_algo_id"],
            "algo_client_order_id": expected["oco_algo_cl_ord_id"],
            "reduce_only": True,
            "side": "sell",
            "position_side": "long",
            "size": "0.01",
        },
        "exit": {
            "client_order_id": exit_client_order_id,
            "order_id": str(exit_order.get("order_id") or ""),
            "fill_id": str(exit_fill_rows[0].get("fill_id") or ""),
            "state": "filled",
            "order_type": "market",
            "reduce_only": True,
            "side": "sell",
            "position_side": "long",
            "size": "0.01",
        },
    }
    projection["identity_digest_sha256"] = _hosted_oco_terminal_exit_identity_digest(
        projection
    )
    return projection, []


def _hosted_oco_terminal_exit_identity_digest(
    projection: Mapping[str, Any],
) -> str:
    """Hash only stable hosted-exit binding and exchange identity fields.

    ``snapshot_sha256`` remains a required audit field, but is deliberately
    excluded: each read-only fresh snapshot contains non-identity account
    values (for example balance timestamps) that must not change ownership.
    """

    return _canonical_sha256(
        {
            field: projection.get(field)
            for field in (
                "schema_version",
                "binding_source",
                "incident_source_head",
                "recovery_code_head",
                "failed_receipt_sha256",
                "flat_identity_sha256",
                "entry",
                "oco",
                "exit",
            )
        }
    )


def _incident_recovery_flat_identity_projection(
    snapshot: Mapping[str, Any],
    *,
    owned_client_order_ids: Sequence[str],
) -> dict[str, list[dict[str, str]]]:
    """Normalize stable flat identity, including legacy fill order identity."""

    owned_ids = {str(value) for value in owned_client_order_ids if str(value)}
    aliases = {
        "client_order_id": "clOrdId",
        "algo_client_order_id": "algoClOrdId",
        "parent_client_order_id": "parentClOrdId",
        "order_id": "ordId",
        "fill_id": "tradeId",
    }

    def field_value(row: Mapping[str, Any], field: str) -> str:
        return str(
            row.get(field)
            or row.get(aliases.get(field, field))
            or ""
        )

    order_ids_by_client_order_id: dict[str, set[str]] = {}
    for row in snapshot.get("orders", []):
        if not isinstance(row, Mapping):
            continue
        client_order_id = field_value(row, "client_order_id")
        order_id = field_value(row, "order_id")
        if client_order_id in owned_ids and order_id:
            order_ids_by_client_order_id.setdefault(
                client_order_id, set()
            ).add(order_id)

    def rows(
        name: str,
        fields: tuple[str, ...],
        *,
        owned: bool = False,
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for row in snapshot.get(name, []):
            if not isinstance(row, Mapping):
                continue
            client_order_id = field_value(row, "client_order_id")
            if owned and client_order_id not in owned_ids:
                continue
            projected = {field: field_value(row, field) for field in fields}
            if name == "fills" and owned and not projected["order_id"]:
                candidates = order_ids_by_client_order_id.get(
                    client_order_id, set()
                )
                if len(candidates) != 1:
                    reason = "missing" if not candidates else "ambiguous"
                    raise OkxDemoPaperRuntimeError(
                        "okx_demo_flat_fill_order_id_mapping_"
                        f"{reason}:{client_order_id}"
                    )
                projected["order_id"] = next(iter(candidates))
            result.append(projected)
        return sorted(
            result,
            key=lambda row: json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    return {
        "orders": rows(
            "orders",
            ("order_id", "client_order_id", "state"),
            owned=True,
        ),
        "fills": rows(
            "fills",
            ("fill_id", "order_id", "client_order_id", "size"),
            owned=True,
        ),
        "positions": rows(
            "positions",
            ("instrument_id", "position_side", "contracts"),
        ),
        "pending_orders": rows(
            "pending_orders",
            ("order_id", "client_order_id", "state"),
        ),
        "pending_algo_orders": rows(
            "pending_algo_orders",
            (
                "algo_id",
                "algo_client_order_id",
                "parent_client_order_id",
                "instrument_id",
                "position_side",
                "size",
                "order_type",
                "state",
            ),
        ),
    }


def _incident_recovery_flat_identity_sha256(
    snapshot: Mapping[str, Any],
    *,
    owned_client_order_ids: Sequence[str],
) -> str:
    """Hash stable order/fill/position/OCO identity for a flat receipt."""

    return _canonical_sha256(
        _incident_recovery_flat_identity_projection(
            snapshot,
            owned_client_order_ids=owned_client_order_ids,
        )
    )


def _fault_ledger_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
    # Keep every runtime caller on the same canonicalization used by the
    # production composition evidence projection and ledger UOW contract.
    return canonical_ledger_snapshot_sha256(snapshot)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _source_head_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "source_head" and isinstance(nested, str):
                values.append(nested)
            values.extend(_source_head_values(nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            values.extend(_source_head_values(nested))
    return values


def _source_head_entries(value: Any) -> list[Any]:
    """Collect runtime-code source heads, excluding archive-only provenance."""

    entries: list[Any] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            # owned_id_restore and owner_marker_audit are immutable provenance,
            # not the code identity of the runtime event that persisted them.
            if key in {"owned_id_restore", "owner_marker_audit"}:
                continue
            if key == "source_head":
                entries.append(nested)
            entries.extend(_source_head_entries(nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            entries.extend(_source_head_entries(nested))
    return entries


def _incident_recovery_event_source_head(event: Mapping[str, Any]) -> str | None:
    """Return one strict source head, no head, or ``None`` for malformed data."""

    if str(event.get("event_type") or "") == "owned_id_restore_applied":
        # This event records immutable owned-ID archive provenance, not runtime
        # code provenance. Its archive source is independently verified.
        return ""
    entries = _source_head_entries(event)
    if not entries:
        return ""
    values = [value for value in entries if value is not None and value != ""]
    if not values:
        return None
    if any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None
        for value in values
    ) or len(set(values)) != 1:
        return None
    return str(values[0])


def _incident_recovery_runtime_source_chain_is_valid(
    *,
    state: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    incident_head: str,
    runtime_run_id: str,
    repo_root: Path,
    recovery_head: str = "",
) -> bool:
    """Consume only a complete monotonic source chain in the ancestry interval."""

    runtime_value = state.get("runtime")
    if not isinstance(runtime_value, Mapping):
        return False
    recovery_head = recovery_head or incident_head
    if (
        re.fullmatch(r"[0-9a-f]{40}", incident_head) is None
        or re.fullmatch(r"[0-9a-f]{40}", recovery_head) is None
        or not runtime_run_id
        or _bounded_git_ancestry_probe(repo_root, incident_head, recovery_head)
        is None
    ):
        return False
    state_source_head_missing = "source_head" not in runtime_value
    state_source_head = runtime_value.get("source_head")

    event_heads: list[tuple[Mapping[str, Any], str]] = []
    for event in events:
        if not isinstance(event, Mapping):
            return False
        event_head = _incident_recovery_event_source_head(event)
        if event_head is None:
            return False
        if event_head:
            event_heads.append((event, event_head))
    if not event_heads:
        return False

    ordered_heads: list[str] = []
    for _, event_head in event_heads:
        if not ordered_heads or ordered_heads[-1] != event_head:
            ordered_heads.append(event_head)
    terminal_head = ordered_heads[-1]
    if (
        _bounded_git_ancestry_probe(repo_root, incident_head, terminal_head)
        is None
        or _bounded_git_ancestry_probe(repo_root, terminal_head, recovery_head)
        is None
    ):
        return False
    if not state_source_head_missing and (
        not isinstance(state_source_head, str)
        or re.fullmatch(r"[0-9a-f]{40}", state_source_head) is None
        or state_source_head != terminal_head
    ):
        return False
    for ancestor, descendant in zip(ordered_heads, ordered_heads[1:]):
        if _bounded_git_ancestry_probe(repo_root, ancestor, descendant) is None:
            return False
    return any(
        str(event.get("run_id") or "") == runtime_run_id
        and event_head == incident_head
        for event, event_head in event_heads
    )


def _sequence_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _client_order_id(row: Mapping[str, Any]) -> str:
    return str(row.get("clOrdId") or row.get("client_order_id") or "")


def _liquidation_buffer_bps(
    *,
    positions: Sequence[Mapping[str, Any]],
    mark_price: Decimal,
) -> str:
    if not positions or _gross_position_contracts(positions) == 0:
        return "not_applicable_flat_position"
    if mark_price <= 0:
        raise OkxDemoPaperRuntimeError(
            "okx_demo_ledger_mark_price_invalid"
        )
    buffers: list[Decimal] = []
    for row in positions:
        liquidation = _decimal(row.get("liquidation_price"))
        if liquidation <= 0:
            raise OkxDemoPaperRuntimeError(
                "okx_demo_ledger_liquidation_price_missing"
            )
        buffers.append(
            abs(mark_price - liquidation) / mark_price * Decimal("10000")
        )
    return _text(min(buffers))


def _round_to_tick(value: Decimal, tick: Decimal, rounding: str) -> Decimal:
    if tick <= 0:
        raise OkxDemoPaperRuntimeError("okx_demo_paper_tick_size_invalid")
    return (value / tick).to_integral_value(rounding=rounding) * tick


def _ratio_bps(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("999999")
    return numerator / denominator * Decimal("10000")


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _iso(value: datetime) -> str:
    timestamp = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_error(exc: Exception, *, credentials: Any = None) -> str:
    message = _safe_probe_text(
        str(exc),
        credentials=credentials,
        max_length=500,
    )
    if message:
        return message[:500]
    return _safe_probe_code(type(exc).__name__) or "runtime_error"


def _is_recoverable_cycle_error(exc: Exception) -> bool:
    if isinstance(exc, OkxDemoTransportError):
        return True
    message = _safe_error(exc)
    if message.startswith("okx_demo_transient:"):
        return True
    if message.startswith(
        "okx_demo_private_ws_current_reconciliation_failed"
    ):
        return False
    return any(
        message == code or f":{code}" in message
        for code in OKX_DEMO_RECOVERABLE_READ_CODES
    )


def _is_transient_liveness_message(message: str) -> bool:
    normalized = str(message or "").lower()
    return any(
        token in normalized
        for token in (
            "50011",
            "urlerror",
            "remote_disconnected",
            "connection reset",
            "connection refused",
            "timeout",
            "tls",
            "dns",
        )
    )


def _is_transient_liveness_error(exc: Exception) -> bool:
    return isinstance(exc, OkxDemoTransportError) or _is_transient_liveness_message(
        _safe_error(exc)
    )


def _incident_recovery_snapshot_blockers(
    snapshot: Mapping[str, Any],
    authorization: Mapping[str, str],
    *,
    protection_policy: Mapping[str, Any],
    expected_leverage: Decimal = Decimal("1"),
) -> list[str]:
    blockers: list[str] = []
    positions = [
        row
        for row in snapshot.get("positions", [])
        if isinstance(row, Mapping) and _decimal(row.get("contracts")) != 0
    ]
    if not (
        len(positions) == 1
        and positions[0].get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
        and positions[0].get("position_side") == "long"
        and positions[0].get("margin_mode") == "isolated"
        and _decimal(positions[0].get("leverage")) == _decimal(expected_leverage)
        and _decimal(positions[0].get("contracts"))
        == OKX_DEMO_PAPER_CONTRACTS
    ):
        blockers.append("okx_demo_incident_recovery_position_mismatch")
    if snapshot.get("pending_orders"):
        blockers.append("okx_demo_incident_recovery_extra_pending_order")
    opening_orders = [
        row
        for row in snapshot.get("orders", [])
        if isinstance(row, Mapping)
        and row.get("order_id") == authorization.get("opening_order_id")
        and row.get("client_order_id") == authorization.get("opening_cl_ord_id")
        and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
        and row.get("side") == "buy"
        and row.get("position_side") == "long"
        and row.get("order_type") == "fok"
        and _decimal(row.get("price")) > 0
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
        and row.get("state") == "filled"
    ]
    opening_fills = [
        row
        for row in snapshot.get("fills", [])
        if isinstance(row, Mapping)
        and row.get("fill_id") == authorization.get("opening_fill_id")
        and row.get("order_id") == authorization.get("opening_order_id")
        and row.get("client_order_id") == authorization.get("opening_cl_ord_id")
        and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
        and row.get("side") == "buy"
        and row.get("position_side") == "long"
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
    ]
    if len(opening_orders) != 1 or len(opening_fills) != 1:
        blockers.append("okx_demo_incident_recovery_opening_fill_mismatch")
    entry_price = (
        _decimal(opening_orders[0].get("price"))
        if len(opening_orders) == 1
        else Decimal("0")
    )
    pending_algos = [
        row
        for row in snapshot.get("pending_algo_orders", [])
        if isinstance(row, Mapping)
    ]
    policy = ServerSideProtectionPolicy.from_mapping(protection_policy)
    instruments = [
        row
        for row in (snapshot.get("instrument"),)
        if isinstance(row, Mapping)
        and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
    ]
    tick_size = (
        _decimal(instruments[0].get("tick_size"))
        if len(instruments) == 1
        else Decimal("0")
    )
    expected_stop_loss = Decimal("0")
    expected_take_profit = Decimal("0")
    if (
        not policy.validate()
        and policy.to_dict() == OKX_DEMO_APPROVED_PROTECTION_POLICY
        and tick_size > 0
        and entry_price > 0
    ):
        expected_stop_loss = _round_to_tick(
            entry_price
            * (Decimal("1") - policy.sl_distance_bps / Decimal("10000")),
            tick_size,
            ROUND_FLOOR,
        )
        expected_take_profit = _round_to_tick(
            entry_price
            * (Decimal("1") + policy.tp_distance_bps / Decimal("10000")),
            tick_size,
            ROUND_CEILING,
        )
    pending_parent = (
        str(pending_algos[0].get("parent_client_order_id") or "")
        if len(pending_algos) == 1
        else ""
    )
    if not (
        len(pending_algos) == 1
        and pending_algos[0].get("algo_id") == authorization.get("algo_id")
        and pending_algos[0].get("algo_client_order_id")
        == authorization.get("algo_cl_ord_id")
        and pending_algos[0].get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
        and pending_algos[0].get("position_side") == "long"
        and _decimal(pending_algos[0].get("size"))
        == OKX_DEMO_PAPER_CONTRACTS
        and pending_algos[0].get("order_type") == "oco"
        and pending_algos[0].get("state") == "live"
        and _decimal(pending_algos[0].get("take_profit_trigger"))
        == expected_take_profit
        and pending_algos[0].get("take_profit_trigger_type") == "mark"
        and pending_algos[0].get("take_profit_order_price") == "-1"
        and _decimal(pending_algos[0].get("stop_loss_trigger"))
        == expected_stop_loss
        and pending_algos[0].get("stop_loss_trigger_type") == "mark"
        and pending_algos[0].get("stop_loss_order_price") == "-1"
        and (
            not pending_parent
            or pending_parent == authorization.get("opening_cl_ord_id")
        )
    ):
        blockers.append("okx_demo_incident_recovery_pending_oco_mismatch")
    if validate_isolated_leverage(
        snapshot.get("leverage", []),
        expected_leverage,
    ):
        blockers.append("okx_demo_incident_recovery_leverage_mismatch")
    return _dedupe(blockers)


def _incident_recovery_flat_close_blockers(
    snapshot: Mapping[str, Any],
    authorization: Mapping[str, str],
) -> list[str]:
    blockers: list[str] = []
    if (
        _gross_position_contracts(snapshot.get("positions", [])) != 0
        or snapshot.get("pending_orders")
    ):
        blockers.append("okx_demo_incident_recovery_close_not_flat_clean")
    close_orders = [
        row
        for row in snapshot.get("orders", [])
        if isinstance(row, Mapping)
        and row.get("client_order_id")
        == authorization.get("expected_close_cl_ord_id")
        and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
        and row.get("side") == "sell"
        and row.get("position_side") == "long"
        and row.get("order_type") == "ioc"
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
        and row.get("state") == "filled"
        and str(row.get("order_id") or "")
    ]
    close_fills = [
        row
        for row in snapshot.get("fills", [])
        if isinstance(row, Mapping)
        and len(close_orders) == 1
        and row.get("order_id") == close_orders[0].get("order_id")
        and row.get("client_order_id")
        == authorization.get("expected_close_cl_ord_id")
        and row.get("instrument_id") == OKX_DEMO_INSTRUMENT_ID
        and row.get("side") == "sell"
        and row.get("position_side") == "long"
        and _decimal(row.get("size")) == OKX_DEMO_PAPER_CONTRACTS
        and str(row.get("fill_id") or "")
    ]
    if len(close_orders) != 1 or len(close_fills) != 1:
        blockers.append("okx_demo_incident_recovery_close_fill_mismatch")
    return _dedupe(blockers)


def _fault_drill_post_response_loss_reconciled(
    fault_injector: Any,
    *,
    opening_error: str,
    client_order_id: str,
    order_observed: bool,
    fill_observed: bool,
) -> bool:
    """Require both the injected loss identity and query-derived exchange facts."""

    timeline = getattr(fault_injector, "timeline", ())
    injected_for_order = any(
        isinstance(event, Mapping)
        and str(event.get("event") or "")
        == "post_response_lost_after_exchange_response"
        and str(event.get("clOrdId") or "") == client_order_id
        for event in timeline
    )
    legacy_error_observed = (
        "okx_demo_fault_injected_post_response_loss" in str(opening_error or "")
    )
    return bool(
        client_order_id
        and order_observed
        and fill_observed
        and (injected_for_order or legacy_error_observed)
    )


def _queried_order_matches_expected(
    row: Mapping[str, Any],
    expected_order: Mapping[str, Any],
) -> bool:
    """Validate a durable-clOrdId readback before accepting an unknown POST."""

    exact_fields = {
        "instId": "instId",
        "side": "side",
        "posSide": "posSide",
        "ordType": "ordType",
        "sz": "sz",
        "tag": "tag",
        "clOrdId": "clOrdId",
    }
    return bool(str(row.get("ordId") or "")) and all(
        str(row.get(query_field) or "")
        == str(expected_order.get(expected_field) or "")
        for query_field, expected_field in exact_fields.items()
    )


def _private_ws_reconciliation_receipt_is_transient(receipt: Any) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    raw_blockers = receipt.get("blockers")
    if not isinstance(raw_blockers, Sequence) or isinstance(
        raw_blockers, (str, bytes)
    ):
        return False
    blockers = [str(row) for row in raw_blockers if str(row)]
    if not blockers:
        return False
    legacy_prefix = "btc_okx_demo_private_ws:"
    legacy_transient_reasons = {
        "not_connected",
        "OkxDemoTransportError",
        "URLError",
        *OKX_DEMO_RECOVERABLE_READ_CODES,
    }
    snapshot_transport_prefix = "btc_private_ws:snapshot_transport_failed:"
    snapshot_transport_reasons = {
        "OkxDemoTransportError",
        *OKX_DEMO_RECOVERABLE_READ_CODES,
    }
    return all(
        (
            blocker.startswith(legacy_prefix)
            and blocker.removeprefix(legacy_prefix) in legacy_transient_reasons
        )
        or (
            blocker.startswith(snapshot_transport_prefix)
            and blocker.removeprefix(snapshot_transport_prefix)
            in snapshot_transport_reasons
        )
        for blocker in blockers
    )


def _repo_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _bounded_git_is_ancestor(
    repo_root: Path,
    ancestor: str,
    descendant: str,
) -> bool:
    """Fail closed when the recovery ancestry proof is unavailable or slow."""

    if not (
        re.fullmatch(r"[0-9a-f]{40}", ancestor)
        and re.fullmatch(r"[0-9a-f]{40}", descendant)
    ):
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _bounded_git_ancestry_probe(
    repo_root: Path,
    ancestor: str,
    descendant: str,
) -> str | None:
    """Return a bounded, independently verified merge base or fail closed."""

    if not (
        re.fullmatch(r"[0-9a-f]{40}", ancestor)
        and re.fullmatch(r"[0-9a-f]{40}", descendant)
    ):
        return None
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", ancestor, descendant],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5.0,
        )
        is_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = merge_base.stdout.strip()
    if is_ancestor.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", value):
        return None
    return value


def _incident_recovery_ancestry_proof_is_valid(
    *,
    repo_root: Path,
    incident_source_head: str,
    marker_recovery_code_head: str,
    current_head: str,
    proof: Any,
) -> bool:
    """Consume Ticket24's strict same-, single-, or multi-hop marker proof."""

    if not isinstance(proof, Mapping):
        return False
    direct_merge_base = _bounded_git_ancestry_probe(
        repo_root, incident_source_head, current_head
    )
    if direct_merge_base is None:
        return False
    expected: dict[str, Any] = {
        "method": "git merge-base and git merge-base --is-ancestor",
        "incident_source_head": incident_source_head,
        "recovery_code_head": current_head,
        "merge_base": direct_merge_base,
        "incident_is_ancestor": True,
        "recovery_is_ancestor_of_incident": incident_source_head == current_head,
    }
    if marker_recovery_code_head not in {incident_source_head, current_head}:
        incident_to_marker = _bounded_git_ancestry_probe(
            repo_root, incident_source_head, marker_recovery_code_head
        )
        marker_to_current = _bounded_git_ancestry_probe(
            repo_root, marker_recovery_code_head, current_head
        )
        if incident_to_marker is None or marker_to_current is None:
            return False
        expected["owner_marker_multihop"] = {
            "method": "git merge-base and git merge-base --is-ancestor",
            "incident_source_head": incident_source_head,
            "marker_recovery_code_head": marker_recovery_code_head,
            "recovery_code_head": current_head,
            "incident_to_marker_merge_base": incident_to_marker,
            "marker_to_recovery_merge_base": marker_to_current,
            "incident_is_marker_ancestor": True,
            "marker_is_recovery_ancestor": True,
        }
    return dict(proof) == expected


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
