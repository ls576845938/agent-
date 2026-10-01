from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backend.app.core.config import (
    BTC_DEMO_RISK_PROFILE_BASELINE_1X,
    BTC_DEMO_RISK_PROFILE_STRESS_3X,
    settings,
)
from backend.app.services.btc_public_market_stream import BtcPublicMarketStreamHub
from quant_crypto.application.btc_demo_runtime import BtcDemoRuntimeService as ApplicationBtcDemoRuntimeService
from quant_crypto.application.btc_demo_operator_commands import (
    RefreshAccountSnapshotCommand,
)
from quant_crypto.application.btc_demo_production_composition import (
    BtcDemoProductionComposition,
    derive_protective_capabilities,
)
from quant_crypto.application.btc_operator_contract_v2 import (
    ALLOWLISTED_OPERATOR_ACTIONS,
    OperationReadModel,
    OperatorContractError,
    authorize_operator_action as _authorize_operator_action,
    canonical_request_digest,
    project_operator_contract_v2,
    validate_idempotency_key,
)
from quant_crypto.application.btc_demo_start_attempt import (
    ACCOUNT_IDENTITY_HASH_SOURCE,
    StartAttemptBinding,
    build_effective_policy,
    is_authoritative_account_identity_hash,
)
from quant_crypto.application.runtime_risk_guardian import (
    classify_order_risk,
    FileGuardianLatchStore,
    GuardianConfig,
    GuardianObservation,
    RuntimeRiskGuardian,
    RuntimeRiskGuardianSupervisor,
)
from quant_crypto.application.runtime_ports import DemoRuntimeControllerPort
from quant_crypto.oms.account_risk_facts import (
    load_reviewed_account_facts_approval,
    reviewed_drawdown_policy_from_approval,
)
from quant_crypto.oms.okx_demo_paper_runtime import (
    OKX_DEMO_APPROVED_PROTECTION_POLICY,
    OKX_DEMO_INSTRUMENT_ID,
    OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
    OKX_DEMO_PAPER_CONFIRMATION,
    OKX_DEMO_PAPER_CONTRACTS,
    OKX_DEMO_PAPER_MAX_NET_CONTRACTS,
    OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
    OKX_DEMO_PAPER_ORDER_TAG,
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
    OkxDemoPaperStartRequest,
    collect_okx_account_cashflow_evidence,
    inspect_okx_native_demo_signal_data,
    load_btc_chart_payload,
)
from quant_crypto.oms.okx_demo import OkxDemoPublicMarketClient
from quant_crypto.runtime.control_plane import (
    BTCDemoClientCapabilityAdapter,
    BTCDemoExecutionDispatcher,
)
from tools.agent_governance.shared_data import default_shared_data_root


_DEMO_PROFILE_MAX_LEVERAGE = {
    BTC_DEMO_RISK_PROFILE_BASELINE_1X: Decimal("1"),
    BTC_DEMO_RISK_PROFILE_STRESS_3X: Decimal("3"),
}
_REAL_MONEY_MAX_LEVERAGE = Decimal("1")
_OKX_NATIVE_DEMO_MANIFEST_GIT_SPEC = (
    "455e5e9d11454fb5a25a5577fa20c58e2b24134f:"
    ".agent/data_manifests/btc-okx-public-swap-research-bundle/"
    "btc-okx-public-swap-btcusdt-demo25h-tail-20260730T1145Z-"
    "src6cea196b4-corr1.json"
)
_OKX_NATIVE_DEMO_DATASET_ID = "btc-okx-public-swap-research-bundle"
_SAFE_OPERATOR_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")


def _safe_operator_exception_blockers(exc: Exception) -> tuple[str, ...]:
    """Project only complete machine codes from a local dispatch exception.

    Free-form messages can contain paths, account data, or transport details.
    If every semicolon/comma-delimited token is a stable code, preserve the
    codes; otherwise collapse the entire exception to the generic blocker.
    """

    raw = str(exc).strip()
    if not raw or len(raw) > 1_024:
        return ("operator_action_failed",)
    parts = tuple(part.strip().lower() for part in re.split(r"[;,]", raw))
    if not parts or len(parts) > 16 or any(
        not part or _SAFE_OPERATOR_ERROR_CODE.fullmatch(part) is None
        for part in parts
    ):
        return ("operator_action_failed",)
    return tuple(sorted(set(parts)))


def _project_protective_capabilities(
    status: Mapping[str, Any],
    *,
    max_configured_leverage: Decimal,
) -> dict[str, Any]:
    """Project reduction permissions without hiding projection failures.

    Input/validation failures become an explicit denied read model.  An
    unexpected implementation error is still fail-closed, but remains
    observable through a distinct error code instead of looking like an empty
    or healthy capability map.
    """

    try:
        return derive_protective_capabilities(
            status,
            max_configured_leverage=max_configured_leverage,
        )
    except (TypeError, ValueError, KeyError, OverflowError, InvalidOperation) as exc:
        code = f"protective_capability_projection_{type(exc).__name__.lower()}"
        return {
            "stop_and_flatten": {
                "allowed": False,
                "reduction_proof": False,
                "effect": "unknown",
                "blockers": [code],
            },
            "emergency_reduce_only_exit": {
                "allowed": False,
                "reduction_proof": False,
                "effect": "unknown",
                "blockers": [code],
            },
            "projection_error_code": code,
        }
    except Exception as exc:
        code = "protective_capability_projection_unexpected_error"
        return {
            "stop_and_flatten": {
                "allowed": False,
                "reduction_proof": False,
                "effect": "unknown",
                "blockers": [code],
            },
            "emergency_reduce_only_exit": {
                "allowed": False,
                "reduction_proof": False,
                "effect": "unknown",
                "blockers": [code],
            },
            "projection_error_code": code,
            "projection_error_type": type(exc).__name__,
        }

_BENIGN_RUNTIME_REASONS = {
    "",
    "clean_stop",
    "runtime_stopped",
    "startup_complete",
    "stopped",
}
_ACCOUNT_RISK_TOKENS = (
    "ambiguous_order",
    "ledger_mismatch",
    "no_verified_protection",
    "nonflat",
    "pending_algo",
    "pending_oco",
    "pending_order",
    "position_mismatch",
    "protection_missing",
)
_NETWORK_TRANSPORT_TOKENS = (
    "connection",
    "disconnect",
    "dns",
    "private_ws_reconnect",
    "private_ws_startup_probe",
    "remote_disconnect",
    "timeout",
    "tls",
    "urlerror",
)
_TRANSIENT_PREFLIGHT_TOKENS = (
    "private_ws_startup_probe_local_disconnect",
)
_SERVICE_RESTART_TOKENS = (
    "previous_cancel_only",
    "previous_runtime_not_cleanly_stopped",
    "runtime_not_cleanly_stopped",
    "runtime_not_started",
    "unclean_restart",
    "worker_stopped",
)
_LIFECYCLE_LABELS = {
    "starting_preflight": "正在权威预检",
    "running": "策略运行中",
    "degraded_no_new_risk": "已禁止新增风险",
    "stopped_clean": "已干净停止",
    "stopped_needs_preflight": "等待重新预检",
}
_SAFE_MODE_LABELS = {
    "normal": "正常模式",
    "cancel_only": "Cancel-only",
    "frozen_unknown": "权威状态待确认",
}
_IMPACT_LABELS = {
    "none": "无运行影响",
    "demo_start": "仅阻止 Demo 启动",
    "new_risk_only": "仅禁止新增风险",
    "account_and_order_safety": "账户与订单安全",
}


def _current_repo_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = completed.stdout.strip()
    if len(value) != 40:
        raise RuntimeError("btc_demo_backend_source_head_invalid")
    return value


class _DurableOperatorOperationStore:
    """Small file-backed operation ledger for the V2 application adapter.

    It stores only hashed idempotency keys and canonical request digests.  The
    runtime output directory is the durable owner; no repository artifact or
    in-process dictionary is used as the source of truth.
    """

    LOCK_TIMEOUT_SECONDS = 1.0
    _START_ATTEMPT_IDENTITY_FIELDS = (
        ("runtime_identity", "runtime_identity_changed"),
        ("source_head", "source_head_changed"),
        ("effective_policy_digest", "effective_policy_digest_changed"),
        ("risk_profile", "risk_profile_changed"),
        ("expected_leverage", "expected_leverage_changed"),
        ("account_identity_hash", "account_identity_changed"),
    )

    def __init__(self, root: Path | None) -> None:
        self.path = (
            (Path(root) / "operator-contract-v2" / "operations.json")
            if root is not None
            else None
        )
        self._lock = threading.RLock()

    @contextmanager
    def _os_writer_lock(self):
        if self.path is None:
            raise OperatorContractError(
                "operator_operation_lock_unavailable",
                blockers=("operator_operation_lock_unavailable",),
                status_code=423,
            )
        last_error: Exception | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            deadline = time.monotonic() + self.LOCK_TIMEOUT_SECONDS
            lease = None
            while lease is None:
                try:
                    lock_store = FileGuardianLatchStore(self.path)
                    lease = lock_store.acquire(
                        owner_id=f"operator-store:{os.getpid()}:{threading.get_ident()}",
                        fence_token=uuid.uuid4().hex,
                    )
                except Exception as exc:
                    last_error = exc
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
        except Exception as exc:
            raise OperatorContractError(
                "operator_operation_lock_unavailable",
                blockers=("operator_operation_lock_unavailable",),
                status_code=423,
            ) from (last_error or exc)
        try:
            yield
        finally:
            try:
                lease.release()
            except Exception as exc:
                raise OperatorContractError(
                    "operator_operation_lock_release_failed",
                    blockers=("operator_operation_lock_release_failed",),
                    status_code=423,
                ) from exc

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _read(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.is_file():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise OperatorContractError(
                "operator_operation_store_unavailable",
                blockers=("operator_operation_store_unavailable",),
                status_code=423,
            )
        if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
            raise OperatorContractError(
                "operator_operation_store_invalid",
                blockers=("operator_operation_store_invalid",),
                status_code=423,
            )
        return [dict(row) for row in value]

    def _write(self, rows: list[dict[str, Any]]) -> None:
        if self.path is None:
            raise OperatorContractError(
                "operator_operation_store_unavailable",
                blockers=("operator_operation_store_unavailable",),
                status_code=423,
            )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            raise OperatorContractError(
                "operator_operation_store_unavailable",
                blockers=("operator_operation_store_unavailable",),
                status_code=423,
            ) from exc

    @staticmethod
    def _model(row: Mapping[str, Any], *, replayed: bool = False) -> OperationReadModel:
        # Runtime startup cleanup can append multiple stable codes with ';'.
        # Decode at the adapter boundary (including old persisted operations),
        # without changing the shared contract or rewriting terminal records.
        diagnostic_codes: set[str] = set()
        for value in row.get("blocker_codes") or ():
            for part in str(value).split(";"):
                code = part.strip()
                if not code:
                    continue
                diagnostic_codes.add(
                    code if re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", code)
                    else "operator_diagnostic_code_invalid"
                )
        return OperationReadModel(
            operation_id=str(row.get("operation_id") or ""),
            action=str(row.get("action") or ""),
            request_digest=str(row.get("request_digest") or ""),
            state=str(row.get("state") or "blocked"),
            phase=str(row.get("phase") or ""),
            blocker_codes=tuple(sorted(diagnostic_codes)),
            created_at_utc=str(row.get("created_at_utc") or ""),
            updated_at_utc=str(row.get("updated_at_utc") or ""),
            state_revision=int(row.get("state_revision") or 0),
            result_present=row.get("result_present") is True,
            retryable=row.get("retryable") is True,
            replayed=replayed,
            idempotent_replay=replayed,
            acknowledged=row.get("acknowledged") is True,
            acknowledged_at_utc=(
                str(row.get("acknowledged_at_utc"))
                if row.get("acknowledged_at_utc") not in (None, "")
                else None
            ),
            safety_flags={name: False for name in (
                "promotion_eligible", "paper", "live", "private",
                "order", "real_order", "transfer", "withdraw",
            )},
            start_attempt=(
                dict(row.get("start_attempt"))
                if isinstance(row.get("start_attempt"), Mapping)
                else {}
            ),
        )

    @classmethod
    def _safe_model(cls, row: Mapping[str, Any], *, replayed: bool = False) -> OperationReadModel:
        try:
            return cls._model(row, replayed=replayed)
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            raise OperatorContractError(
                "operator_operation_store_invalid",
                blockers=("operator_operation_store_invalid",),
                status_code=423,
            ) from exc

    def begin(
        self,
        *,
        action: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        start_attempt: Mapping[str, Any] | None = None,
    ) -> tuple[OperationReadModel, bool]:
        if action not in ALLOWLISTED_OPERATOR_ACTIONS:
            raise OperatorContractError(
                "operator_action_not_allowlisted",
                blockers=("operator_action_not_allowlisted",),
                status_code=400,
            )
        if not validate_idempotency_key(idempotency_key):
            raise OperatorContractError(
                "idempotency_key_required",
                blockers=("idempotency_key_required",),
                status_code=400,
            )
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        request_digest = canonical_request_digest(payload)
        with self._lock, self._os_writer_lock():
            rows = self._read()
            for row in rows:
                if row.get("idempotency_key_digest") != key_digest:
                    continue
                if row.get("historical") is True or (
                    isinstance(row.get("start_attempt"), Mapping)
                    and row.get("start_attempt", {}).get("historical") is True
                ):
                    raise OperatorContractError(
                        "operator_idempotency_key_bound_to_historical_start_attempt",
                        blockers=(
                            "operator_idempotency_key_bound_to_historical_start_attempt",
                        ),
                        status_code=409,
                    )
                if row.get("action") != action or row.get("request_digest") != request_digest:
                    raise OperatorContractError(
                        "idempotency_key_reuse_mismatch",
                        blockers=("idempotency_key_reuse_mismatch",),
                        status_code=409,
                    )
                return self._safe_model(row, replayed=True), True
            operation_id = hashlib.sha256(
                f"{key_digest}:{action}:{request_digest}".encode("ascii")
            ).hexdigest()[:32]
            now = self._now()
            row = {
                "operation_id": operation_id,
                "action": action,
                "idempotency_key_digest": key_digest,
                "request_digest": request_digest,
                "state": "queued",
                "phase": "authorized",
                "blocker_codes": [],
                "created_at_utc": now,
                "updated_at_utc": now,
                "state_revision": 1,
                "result_present": False,
                "retryable": False,
                "acknowledged": False,
                "acknowledged_at_utc": None,
                "start_attempt": dict(start_attempt or {}),
            }
            rows.append(row)
            self._write(rows)
            return self._safe_model(row), False

    def bind_start_attempt(
        self,
        operation_id: str,
        binding: Mapping[str, Any],
    ) -> OperationReadModel:
        """Persist the immutable outer/inner StartAttempt relationship."""

        with self._lock, self._os_writer_lock():
            rows = self._read()
            for row in rows:
                if row.get("operation_id") != operation_id:
                    continue
                existing = row.get("start_attempt")
                if isinstance(existing, Mapping) and existing:
                    if dict(existing) != dict(binding):
                        raise OperatorContractError(
                            "operator_start_attempt_binding_conflict",
                            blockers=("operator_start_attempt_binding_conflict",),
                            status_code=409,
                        )
                    return self._safe_model(row)
                row["start_attempt"] = json.loads(json.dumps(dict(binding), default=str))
                row["updated_at_utc"] = self._now()
                row["state_revision"] = int(row.get("state_revision") or 0) + 1
                self._write(rows)
                return self._safe_model(row)
        raise OperatorContractError(
            "operator_operation_not_found",
            blockers=("operator_operation_not_found",),
            status_code=404,
        )

    def find_existing(
        self,
        *,
        action: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> OperationReadModel | None:
        """Read an exact idempotent replay without claiming a new operation."""

        if (
            action not in ALLOWLISTED_OPERATOR_ACTIONS
            or not validate_idempotency_key(idempotency_key)
        ):
            return None
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        request_digest = canonical_request_digest(payload)
        with self._lock, self._os_writer_lock():
            for row in self._read():
                if row.get("historical") is True or (
                    isinstance(row.get("start_attempt"), Mapping)
                    and row.get("start_attempt", {}).get("historical") is True
                ):
                    continue
                if row.get("idempotency_key_digest") != key_digest:
                    continue
                if row.get("action") != action or row.get("request_digest") != request_digest:
                    raise OperatorContractError(
                        "idempotency_key_reuse_mismatch",
                        blockers=("idempotency_key_reuse_mismatch",),
                        status_code=409,
                    )
                return self._safe_model(row, replayed=True)
        return None

    def find_existing_legacy(
        self,
        *,
        action: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> OperationReadModel | None:
        """Read pre-binding rows only; new rows never use browser-only digests."""

        if action not in ALLOWLISTED_OPERATOR_ACTIONS or not validate_idempotency_key(idempotency_key):
            return None
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        request_digest = canonical_request_digest(payload)
        with self._lock, self._os_writer_lock():
            for row in self._read():
                if row.get("historical") is True or (
                    isinstance(row.get("start_attempt"), Mapping)
                    and row.get("start_attempt", {}).get("historical") is True
                ):
                    continue
                if row.get("idempotency_key_digest") != key_digest:
                    continue
                if row.get("start_attempt"):
                    return None
                if row.get("action") != action or row.get("request_digest") != request_digest:
                    raise OperatorContractError(
                        "idempotency_key_reuse_mismatch",
                        blockers=("idempotency_key_reuse_mismatch",),
                        status_code=409,
                    )
                return self._safe_model(row, replayed=True)
        return None

    def reconcile_start_attempt_identity(
        self,
        current_identity: Mapping[str, Any] | None,
    ) -> None:
        """Historicalize durable start rows outside the serving identity.

        Rows remain append-preserved.  Queued/running stale rows become
        interrupted; terminal rows remain auditable but are excluded from
        current operation discovery.
        """

        if current_identity is None or self.path is None:
            return
        with self._lock, self._os_writer_lock():
            rows = self._read()
            changed = False
            now = self._now()
            for row in rows:
                if row.get("action") != "authoritative_preflight_start":
                    continue
                if row.get("historical") is True:
                    continue
                attempt = row.get("start_attempt")
                reasons: list[str] = []
                if not isinstance(attempt, Mapping) or not attempt:
                    reasons.append("operator_start_attempt_identity_missing")
                elif attempt.get("historical") is True:
                    row["historical"] = True
                    continue
                else:
                    for field, reason in self._START_ATTEMPT_IDENTITY_FIELDS:
                        expected = str(current_identity.get(field) or "")
                        actual = str(attempt.get(field) or "")
                        if not expected or expected != actual:
                            reasons.append(reason)
                if not reasons:
                    continue
                reasons = list(dict.fromkeys(reasons))
                updated_attempt = dict(attempt) if isinstance(attempt, Mapping) else {}
                if updated_attempt:
                    updated_attempt.update(
                        {
                            "current_attempt": False,
                            "historical": True,
                            "historical_reason_codes": list(
                                dict.fromkeys(
                                    [
                                        *list(updated_attempt.get("historical_reason_codes") or []),
                                        *reasons,
                                    ]
                                )
                            ),
                            "updated_at_utc": now,
                        }
                    )
                    if str(row.get("state") or "") in {"queued", "running"}:
                        updated_attempt.update(
                            {
                                "state": "interrupted",
                                "phase": "historical_identity_changed",
                            }
                        )
                    row["start_attempt"] = updated_attempt
                row["historical"] = True
                row["historical_reason_codes"] = reasons
                if str(row.get("state") or "") in {"queued", "running"}:
                    row["state"] = "interrupted"
                    row["phase"] = "historical_identity_changed"
                    row["blocker_codes"] = sorted(
                        {
                            *[str(code) for code in row.get("blocker_codes") or ()],
                            "operator_start_attempt_identity_changed",
                        }
                    )
                    row["result_present"] = True
                    row["retryable"] = False
                row["state_revision"] = int(row.get("state_revision") or 0) + 1
                row["updated_at_utc"] = now
                changed = True
            if changed:
                self._write(rows)

    def transition(
        self,
        operation_id: str,
        *,
        state: str,
        phase: str,
        blockers: Sequence[str] = (),
        result_present: bool = False,
        retryable: bool = False,
    ) -> OperationReadModel:
        if state not in {
            "queued", "running", "succeeded", "failed", "blocked", "interrupted", "timed_out"
        }:
            raise OperatorContractError(
                "operator_operation_state_invalid",
                blockers=("operator_operation_state_invalid",),
                status_code=423,
            )
        with self._lock, self._os_writer_lock():
            rows = self._read()
            for row in rows:
                if row.get("operation_id") != operation_id:
                    continue
                old = str(row.get("state") or "")
                terminals = {"succeeded", "failed", "blocked", "interrupted", "timed_out"}
                if old in terminals and state != old:
                    return self._safe_model(row)
                row["state"] = state
                row["phase"] = phase
                row["blocker_codes"] = sorted({str(code).lower() for code in blockers if str(code)})
                row["result_present"] = bool(result_present)
                row["retryable"] = bool(retryable)
                row["state_revision"] = int(row.get("state_revision") or 0) + 1
                row["updated_at_utc"] = self._now()
                self._write(rows)
                return self._safe_model(row)
        raise OperatorContractError(
            "operator_operation_not_found",
            blockers=("operator_operation_not_found",),
            status_code=404,
        )

    def get(self, operation_id: str) -> OperationReadModel:
        with self._lock, self._os_writer_lock():
            for row in self._read():
                if row.get("operation_id") == operation_id:
                    return self._safe_model(row)
        raise OperatorContractError(
            "operator_operation_not_found",
            blockers=("operator_operation_not_found",),
            status_code=404,
        )

    def latest_unacknowledged(
        self,
        *,
        action: str | None = None,
    ) -> OperationReadModel | None:
        """Return the newest durable operation still owned by the operator UI.

        Older rows remain append-preserved for audit.  The reverse scan keeps
        the visible contract focused on the newest unresolved operation while
        an optional action filter lets mutation authorization remain scoped to
        that action instead of creating a global UI lock.
        """

        with self._lock, self._os_writer_lock():
            for row in reversed(self._read()):
                if row.get("historical") is True or (
                    isinstance(row.get("start_attempt"), Mapping)
                    and row.get("start_attempt", {}).get("historical") is True
                ):
                    continue
                model = self._safe_model(row)
                if model.acknowledged:
                    continue
                if action is not None and model.action != action:
                    continue
                return model
        return None

    def historical_operations(
        self,
        *,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return append-preserved historical operation projections."""

        if self.path is None:
            return []
        with self._lock, self._os_writer_lock():
            result: list[dict[str, Any]] = []
            for row in self._read():
                attempt = row.get("start_attempt")
                if not (
                    row.get("historical") is True
                    or (
                        isinstance(attempt, Mapping)
                        and attempt.get("historical") is True
                    )
                ):
                    continue
                if action is not None and row.get("action") != action:
                    continue
                projected = self._safe_model(row).to_dict()
                projected["historical"] = True
                projected["historical_reason_codes"] = list(
                    row.get("historical_reason_codes") or ()
                )
                result.append(projected)
            return result[-32:]

    def acknowledge(
        self,
        operation_id: str,
        *,
        action: str,
        expected_state_revision: int,
    ) -> OperationReadModel:
        """Persist one exact terminal acknowledgement without runtime I/O."""

        if (
            action not in ALLOWLISTED_OPERATOR_ACTIONS
            or type(expected_state_revision) is not int
        ):
            raise OperatorContractError(
                "operator_operation_acknowledgement_invalid",
                blockers=("operator_operation_acknowledgement_invalid",),
                status_code=400,
            )
        terminals = {"succeeded", "failed", "blocked", "interrupted", "timed_out"}
        with self._lock, self._os_writer_lock():
            rows = self._read()
            for row in rows:
                if row.get("operation_id") != operation_id:
                    continue
                model = self._safe_model(row)
                if model.action != action:
                    raise OperatorContractError(
                        "operator_operation_acknowledgement_conflict",
                        blockers=("operator_operation_acknowledgement_conflict",),
                        status_code=409,
                    )
                if model.state not in terminals:
                    raise OperatorContractError(
                        "operator_operation_not_terminal",
                        blockers=("operator_operation_not_terminal",),
                        status_code=423,
                    )
                if model.acknowledged:
                    if row.get("acknowledgement_source_revision") != expected_state_revision:
                        raise OperatorContractError(
                            "operator_operation_acknowledgement_conflict",
                            blockers=("operator_operation_acknowledgement_conflict",),
                            status_code=409,
                        )
                    return model
                if model.state_revision != expected_state_revision:
                    raise OperatorContractError(
                        "operator_operation_acknowledgement_conflict",
                        blockers=("operator_operation_acknowledgement_conflict",),
                        status_code=409,
                    )
                now = self._now()
                row["acknowledged"] = True
                row["acknowledged_at_utc"] = now
                row["acknowledgement_source_revision"] = expected_state_revision
                row["state_revision"] = model.state_revision + 1
                row["updated_at_utc"] = now
                self._write(rows)
                return self._safe_model(row)
        raise OperatorContractError(
            "operator_operation_not_found",
            blockers=("operator_operation_not_found",),
            status_code=404,
        )


class BtcDemoRuntimeService(ApplicationBtcDemoRuntimeService):
    """Backend dependency-composition facade for BTC Demo runtime orchestration."""

    def __init__(
        self,
        *,
        controller: DemoRuntimeControllerPort | None = None,
        risk_profile: str | None = None,
        public_market_loader: Callable[[str, int], dict[str, Any]] | None = None,
        public_market_stream: BtcPublicMarketStreamHub | None = None,
        operator_operation_root: Path | None = None,
    ) -> None:
        selected_profile = _select_demo_risk_profile(
            risk_profile or settings.btc_demo_risk_profile
        )
        self._risk_profile = selected_profile
        max_configured_leverage = _DEMO_PROFILE_MAX_LEVERAGE[selected_profile]
        shared_data_root = default_shared_data_root(settings.repo_root)
        source_head = _current_repo_head(settings.repo_root)
        approval_registry = str(
            settings.btc_demo_account_facts_approval_registry or ""
        ).strip()
        configured_approval_id = str(
            settings.btc_demo_account_facts_approval_id or ""
        ).strip()
        configured_runtime_identity = str(
            settings.btc_demo_runtime_identity or ""
        ).strip()
        if bool(approval_registry) != bool(configured_approval_id):
            raise ValueError("btc_demo_account_facts_approval_config_incomplete")
        if approval_registry and not configured_runtime_identity:
            raise ValueError("btc_demo_account_facts_runtime_identity_missing")
        account_facts_approval_resolver = None
        reviewed_drawdown_policy: Mapping[str, str] | None = None
        if approval_registry and configured_approval_id:
            def resolve_account_facts_approval(approval_id: str) -> Mapping[str, Any] | None:
                return load_reviewed_account_facts_approval(
                    registry_path=approval_registry,
                    approval_id=approval_id,
                    repo_root=settings.repo_root,
                )

            account_facts_approval_resolver = resolve_account_facts_approval
            configured_approval = resolve_account_facts_approval(
                configured_approval_id
            )
            if configured_approval is None:
                raise ValueError("btc_demo_account_facts_approval_missing")
            if configured_approval.get("source_head") != source_head:
                raise ValueError("btc_demo_account_facts_approval_source_head_mismatch")
            if (
                configured_approval.get("runtime_identity")
                != configured_runtime_identity
            ):
                raise ValueError(
                    "btc_demo_account_facts_approval_runtime_identity_mismatch"
                )
            reviewed_drawdown_policy = reviewed_drawdown_policy_from_approval(
                configured_approval
            )
        guardian_config = GuardianConfig(
            max_abs_exposure=float(OKX_DEMO_PAPER_MAX_NOTIONAL_USDT),
            max_daily_loss=float(OKX_DEMO_PAPER_MAX_NOTIONAL_USDT),
            max_drawdown=float(
                reviewed_drawdown_policy["value"]
                if reviewed_drawdown_policy is not None
                else OKX_DEMO_PAPER_MAX_NOTIONAL_USDT
            ),
            max_drawdown_unit=(
                reviewed_drawdown_policy["unit"]
                if reviewed_drawdown_policy is not None
                else "unknown"
            ),
            max_open_orders=0,
        )
        runtime_config = OkxDemoPaperRuntimeConfig(
                repo_root=settings.repo_root,
                data_db_path=Path(settings.data_db_path),
                max_configured_leverage=max_configured_leverage,
                okx_native_shared_manifest_git_spec=(
                    _OKX_NATIVE_DEMO_MANIFEST_GIT_SPEC
                ),
                okx_native_shared_data_root=shared_data_root,
                okx_native_expected_dataset_id=(
                    _OKX_NATIVE_DEMO_DATASET_ID
                ),
                risk_profile=selected_profile,
                runtime_identity=configured_runtime_identity,
                account_facts_approval_resolver=(
                    account_facts_approval_resolver
                ),
                account_facts_approval_id=configured_approval_id,
                account_cashflow_evidence_provider=(
                    collect_okx_account_cashflow_evidence
                ),
            )
        def guardian_supervisor_factory() -> RuntimeRiskGuardianSupervisor:
            latch_path = Path(runtime_config.output_dir) / "guardian_latch.json"
            guardian = RuntimeRiskGuardian(
                guardian_config
            )
            return RuntimeRiskGuardianSupervisor(
                guardian,
                FileGuardianLatchStore(latch_path),
                owner_id=f"btc-demo-production:{os.getpid()}",
                fence_token=f"{source_head}:{selected_profile}",
            )

        production_composition = BtcDemoProductionComposition(
            source_head=source_head,
            max_configured_leverage=max_configured_leverage,
            max_abs_position=Decimal("0.01"),
            max_notional=OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
            credential_service=runtime_config.credential_service,
            guardian_supervisor_factory=guardian_supervisor_factory,
            guardian_config=guardian_config,
        )
        dispatcher = BTCDemoExecutionDispatcher(
            expected_source_head=source_head,
            state_directory=(
                Path(runtime_config.output_dir) / "btc-demo-execution-boundary"
            ),
            capability_adapter=BTCDemoClientCapabilityAdapter(),
            credential_service=runtime_config.credential_service,
        )
        runtime_controller = controller or OkxDemoPaperRuntimeController(
            config=replace(
                runtime_config,
                execution_dispatcher=dispatcher,
                authoritative_oms_bundle_provider=(
                    production_composition.build_order_submission_bundle
                ),
            )
        )
        self._production_composition = production_composition
        self._public_market_client = OkxDemoPublicMarketClient()
        self._public_market_loader = public_market_loader
        self._public_market_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
        self._public_ticker_cache: tuple[float, dict[str, Any]] | None = None
        self._public_candle_cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}
        self._public_depth_cache: tuple[float, dict[str, Any]] | None = None
        self._public_market_lock = threading.Lock()
        self._public_market_refreshes: set[tuple[str, int]] = set()
        self._public_market_stream = public_market_stream or BtcPublicMarketStreamHub()
        # This is the observation identity of the current backend process, not
        # a runtime heartbeat or exchange-account freshness claim.  A cold,
        # stopped controller has no prior runtime timestamp, but the operator
        # contract still needs a stable current-process snapshot so the sole
        # bootstrap action (refresh_account_snapshot) remains reachable.
        self._operator_projection_initialized_at_utc = datetime.now(
            timezone.utc
        ).isoformat()

        def readonly_chart_loader(limit: int) -> dict:
            cached_loader = getattr(
                runtime_controller,
                "readonly_chart_payload",
                None,
            )
            if callable(cached_loader):
                cached = cached_loader(limit=limit)
                if cached is not None:
                    return cached
            return load_btc_chart_payload(
                repo_root=settings.repo_root,
                db_path=Path(settings.data_db_path),
                limit=limit,
                shared_manifest_git_spec=(
                    _OKX_NATIVE_DEMO_MANIFEST_GIT_SPEC
                ),
                shared_data_root=shared_data_root,
                expected_dataset_id=_OKX_NATIVE_DEMO_DATASET_ID,
            )

        super().__init__(
            controller=runtime_controller,
            native_demo_data_inspector=lambda: inspect_okx_native_demo_signal_data(
                settings.repo_root,
                shared_manifest_git_spec=(
                    _OKX_NATIVE_DEMO_MANIFEST_GIT_SPEC
                ),
                shared_data_root=shared_data_root,
                expected_dataset_id=_OKX_NATIVE_DEMO_DATASET_ID,
            ),
            readonly_chart_loader=readonly_chart_loader,
            readonly_market_view_loader=self._readonly_market_view,
            instrument_id=OKX_DEMO_INSTRUMENT_ID,
            authorization_ticket=OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
            confirmation_text=OKX_DEMO_PAPER_CONFIRMATION,
        )
        self._runtime_identity = str(
            getattr(runtime_controller, "_runtime_identity", "")
            or getattr(runtime_controller, "runtime_identity", "")
            or ""
        )
        self._account_identity_hash = str(
            getattr(runtime_controller, "_account_identity_hash", "") or ""
        )
        controller_config = getattr(runtime_controller, "config", None)
        durable_root = operator_operation_root
        if durable_root is None and controller_config is not None:
            configured_root = getattr(controller_config, "output_dir", None)
            if configured_root:
                durable_root = Path(configured_root)
        self._operator_operation_store = _DurableOperatorOperationStore(durable_root)

    def _readonly_market_view(self, timeframe: str, limit: int) -> dict[str, Any]:
        if timeframe not in {"1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"}:
            raise RuntimeError("okx_demo_public_market_timeframe_not_allowlisted")
        if not isinstance(limit, int) or limit < 2 or limit > 300:
            raise RuntimeError("okx_demo_public_market_limit_out_of_bounds")
        ttl_seconds = 5.0 if timeframe == "1m" else 15.0
        key = (timeframe, limit)
        now = time.monotonic()
        with self._public_market_lock:
            cached = self._public_market_cache.get(key)
            if cached is not None and now - cached[0] <= ttl_seconds:
                return {**cached[1], "cache_age_ms": int((now - cached[0]) * 1_000), "stale": False, "last_error_code": ""}
            if key in self._public_market_refreshes:
                if cached is not None:
                    return {
                        **cached[1],
                        "cache_age_ms": int((now - cached[0]) * 1_000),
                        "stale": True,
                        "last_error_code": "okx_demo_public_market_refresh_in_flight",
                    }
                raise RuntimeError("okx_demo_public_market_unavailable")
            self._public_market_refreshes.add(key)
        try:
            if self._public_market_loader is not None:
                payload = dict(self._public_market_loader(timeframe, limit))
            else:
                ticker = self._read_public_ticker(now)
                candles = self._read_public_candles(timeframe, limit, now)
                stream_snapshot = self._public_market_stream.snapshot()
                stream_depth = stream_snapshot.get("depth") if stream_snapshot.get("status") == "live" else None
                depth_source = "okx_public_ws" if isinstance(stream_depth, Mapping) else "unavailable"
                depth_error_code = ""
                depth = dict(stream_depth) if isinstance(stream_depth, Mapping) else None
                if depth is None:
                    try:
                        depth = self._read_public_depth(now)
                        depth_source = "okx_public_rest_books5"
                    except Exception as exc:
                        depth_error_code = f"okx_demo_public_books_{type(exc).__name__}"
                payload = {
                    "schema_version": "okx_public_market_view_v1",
                    "source_kind": "okx_public_market_view_v1",
                    "instrument_id": OKX_DEMO_INSTRUMENT_ID,
                    "timeframe": timeframe,
                    "read_only": True,
                    "public_only": True,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "strategy_signal_compatible": False,
                    "persisted_market_rows": False,
                    "captured_at_ms": int(time.time() * 1_000),
                    "ticker": ticker,
                    "candles": candles,
                    "depth": depth,
                    "depth_source": depth_source,
                    "depth_error_code": depth_error_code,
                }
        except Exception as exc:
            with self._public_market_lock:
                self._public_market_refreshes.discard(key)
                cached = self._public_market_cache.get(key)
            if cached is not None:
                return {
                    **cached[1],
                    "cache_age_ms": int((time.monotonic() - cached[0]) * 1_000),
                    "stale": True,
                    "last_error_code": f"okx_demo_public_market_{type(exc).__name__}",
                }
            raise RuntimeError("okx_demo_public_market_unavailable") from exc
        refreshed_at = time.monotonic()
        payload.update({"cache_age_ms": 0, "stale": False, "last_error_code": ""})
        with self._public_market_lock:
            self._public_market_cache[key] = (refreshed_at, payload)
            self._public_market_refreshes.discard(key)
        return payload

    def readonly_market_ticker(self) -> dict[str, Any]:
        """Return a small credential-free REST fallback for the forming bar.

        The full market view includes candles and depth and can take several
        seconds when the public websocket is unavailable.  This endpoint keeps
        visual price updates independent without persisting rows or exposing
        any private/order capability.
        """

        started = time.monotonic()
        try:
            ticker = self._read_public_ticker(started)
            with self._public_market_lock:
                cached = self._public_ticker_cache
            cached_at = cached[0] if cached is not None else started
            stale = False
            error_code = ""
        except Exception as exc:
            with self._public_market_lock:
                cached = self._public_ticker_cache
            if cached is None:
                raise RuntimeError("okx_demo_public_ticker_unavailable") from exc
            cached_at, cached_ticker = cached
            ticker = dict(cached_ticker)
            stale = True
            error_code = f"okx_demo_public_ticker_{type(exc).__name__}"
        return {
            "schema_version": "okx_public_market_ticker_v1",
            "source_kind": "okx_public_market_ticker_v1",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "read_only": True,
            "public_only": True,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "strategy_signal_compatible": False,
            "persisted_market_rows": False,
            "captured_at_ms": int(time.time() * 1_000),
            "cache_age_ms": max(
                0,
                int((time.monotonic() - cached_at) * 1_000),
            ),
            "stale": stale,
            "last_error_code": error_code,
            "ticker": ticker,
        }

    def public_market_stream(self) -> BtcPublicMarketStreamHub:
        """Return the lazy public-only display hub; never starts Demo runtime."""
        return self._public_market_stream

    def _read_public_ticker(self, now: float) -> dict[str, Any]:
        with self._public_market_lock:
            cached = self._public_ticker_cache
        if cached is not None and now - cached[0] <= 2.0:
            return dict(cached[1])
        ticker = dict(self._public_market_client.ticker())
        with self._public_market_lock:
            self._public_ticker_cache = (time.monotonic(), ticker)
        return ticker

    def _read_public_candles(
        self,
        timeframe: str,
        limit: int,
        now: float,
    ) -> list[dict[str, Any]]:
        key = (timeframe, limit)
        with self._public_market_lock:
            cached = self._public_candle_cache.get(key)
        ttl_seconds = 5.0 if timeframe == "1m" else 15.0
        if cached is not None and now - cached[0] <= ttl_seconds:
            return [dict(row) for row in cached[1]]
        candles = [dict(row) for row in self._public_market_client.candles(
            timeframe=timeframe,
            limit=limit,
        )]
        with self._public_market_lock:
            self._public_candle_cache[key] = (time.monotonic(), candles)
        return candles

    def _read_public_depth(self, now: float) -> dict[str, Any]:
        with self._public_market_lock:
            cached = self._public_depth_cache
        if cached is not None and now - cached[0] <= 2.0:
            return {**cached[1], "source": "okx_public_rest_books5"}
        depth = dict(self._public_market_client.books())
        if depth.get("instrument_id") != OKX_DEMO_INSTRUMENT_ID or len(depth.get("bids", [])) != 5 or len(depth.get("asks", [])) != 5:
            raise RuntimeError("okx_demo_public_books5_projection_invalid")
        depth["source"] = "okx_public_rest_books5"
        with self._public_market_lock:
            self._public_depth_cache = (time.monotonic(), depth)
        return dict(depth)

    def catalog(self) -> dict:
        payload = super().catalog()
        payload["risk_profile"] = self._risk_profile_payload()
        return payload

    def status(self) -> dict:
        payload = super().status()
        payload["risk_profile"] = self._risk_profile_payload()
        if hasattr(self, "_operator_operation_store"):
            self._operator_operation_store.reconcile_start_attempt_identity(
                self._current_start_attempt_identity(payload)
            )
            payload["historical_operator_operations"] = (
                self._operator_operation_store.historical_operations(
                    action="authoritative_preflight_start"
                )
            )
        payload["guardian"] = self._guardian_read_model(payload)
        if "protective_capabilities" not in payload:
            payload["protective_capabilities"] = _project_protective_capabilities(
                payload,
                max_configured_leverage=_DEMO_PROFILE_MAX_LEVERAGE.get(
                    self._risk_profile,
                    Decimal("1"),
                ),
            )
        projection_error = _mapping(payload.get("protective_capabilities")).get("projection_error_code")
        if projection_error:
            payload["protective_capability_blockers"] = [str(projection_error)]
        payload["operator_control"] = _operator_control_payload(payload)
        return payload

    @staticmethod
    def _parse_guardian_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    def _guardian_latch_path(self) -> Path | None:
        config = getattr(self.controller, "config", None)
        root = getattr(config, "output_dir", None)
        return Path(root) / "guardian_latch.json" if root else None

    def _guardian_read_model(self, status: Mapping[str, Any]) -> dict[str, Any]:
        """Read the durable Guardian projection without creating a latch."""

        supplied = status.get("guardian") or status.get("guardian_read_model")
        if (
            isinstance(supplied, Mapping)
            and isinstance(supplied.get("persistence_state"), str)
            and isinstance(supplied.get("reason_codes"), list)
            and type(supplied.get("generation")) is int
        ):
            public_fields = {
                "schema_version", "persistence_state", "status", "tripped", "acknowledged",
                "reason_codes", "generation", "state_revision", "evidence_identity", "evidence_digest",
                "observation_digest", "last_observation_identity", "last_observation_digest",
                "last_observation_time_utc", "position", "exposure", "pnl", "drawdown",
                "next_safe_action", "execution_permission", "order_allowed", "promotion", "paper",
                "live", "private", "order", "real_order", "transfer", "withdraw",
            }
            return {key: supplied[key] for key in public_fields if key in supplied}
        path = self._guardian_latch_path()
        record = None
        error = ""
        if path is not None:
            try:
                # GET/status is read-only: do not acquire the supervisor lease
                # or create a missing directory.  Mutations use the existing
                # composition supervisor and its CAS/lease below.
                record = FileGuardianLatchStore(path).load_optional()
            except Exception as exc:
                # Do not expose the physical latch path (or an exception's
                # filesystem detail) through the public status projection.
                # Keep the failure observable with a stable code and type;
                # mutations remain fail-closed on this read-model state.
                error = "latch_persistence_read_failed"
                persistence_error_type = type(exc).__name__
            else:
                persistence_error_type = ""
        else:
            persistence_error_type = ""
        if error:
            state = "corrupt_or_unavailable"
        elif record is None:
            state = "missing"
        elif record.tripped and record.acknowledged:
            state = "acknowledged"
        elif record.tripped:
            state = "tripped"
        else:
            state = "cleared"
        exchange = _mapping(status.get("exchange"))
        positions = _rows(exchange.get("positions"))
        nonflat = [row for row in positions if _nonzero(row.get("contracts"))]
        position_contracts: float | None = 0.0
        try:
            for row in positions:
                value = float(row.get("contracts") or 0)
                if value != value or abs(value) == float("inf"):
                    raise ValueError("position_contracts_non_finite")
                position_contracts += value
        except (TypeError, ValueError, OverflowError):
            position_contracts = None
        mark = _mapping(exchange.get("mark"))
        return {
            "schema_version": "btc_runtime_guardian_read_model_v1",
            "persistence_state": state,
            "status": "clear" if state == "cleared" else "blocked",
            "tripped": bool(record and record.tripped),
            "acknowledged": bool(record and record.acknowledged),
            "reason_codes": list(record.reason_codes) if record else [error or "latch_persistence_missing"],
            "persistence_error_code": error,
            "persistence_error_type": persistence_error_type,
            "generation": record.generation if record else 0,
            "state_revision": record.state_revision if record else 0,
            "evidence_identity": record.evidence_identity if record else "",
            "evidence_digest": record.evidence_digest if record else "",
            "observation_digest": record.observation_digest if record else "",
            "last_observation_identity": (
                record.recovery_evidence_identity or record.evidence_identity if record else ""
            ),
            "last_observation_digest": (
                record.recovery_evidence_digest or record.observation_digest if record else ""
            ),
            "last_observation_time_utc": (
                record.recovery_reference_time_utc.isoformat().replace("+00:00", "Z")
                if record and record.recovery_reference_time_utc else None
            ),
            "position": {
                "nonflat": bool(nonflat),
                "contracts": str(position_contracts) if position_contracts is not None else "",
                "side": str(nonflat[0].get("position_side") or nonflat[0].get("posSide") or "") if nonflat else "flat",
            },
            "exposure": {
                "mark_price": str(mark.get("mark_price") or ""),
                "contracts": str(sum(float(row.get("contracts") or 0) for row in nonflat)),
                "unit": "USDT",
            },
            "pnl": {
                "realized": str(_mapping(exchange.get("balance")).get("realized_pnl_usdt") or ""),
                "unrealized": str(_mapping(exchange.get("balance")).get("unrealized_pnl_usdt") or ""),
                "unit": "USDT",
            },
            "drawdown": {"value": None, "unit": "USDT", "provenance": "unavailable"},
            "next_safe_action": (
                "recover_guardian_after_fresh_preflight" if state in {"missing", "acknowledged"}
                else "acknowledge_guardian_trip" if state == "tripped"
                else "refresh_account_snapshot"
            ),
            "execution_permission": False,
            "order_allowed": False,
            "promotion": False,
            "paper": False,
            "live": False,
            "private": False,
            "order": False,
            "real_order": False,
            "transfer": False,
            "withdraw": False,
        }

    def operator_contract_v2(self) -> dict[str, Any]:
        """Return the same application projection used before each mutation."""

        status = self._operator_contract_status()
        operation = self._operator_operation_store.latest_unacknowledged()
        return project_operator_contract_v2(status, operation=operation)

    def operator_operation_v2(self, operation_id: str) -> dict[str, Any]:
        return self._operator_operation_store.get(str(operation_id)).to_dict()

    def acknowledge_operator_operation_v2(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Acknowledge one terminal UI operation without touching runtime I/O."""

        if set(payload) != {"action", "expected_state_revision"}:
            raise OperatorContractError(
                "operator_operation_acknowledgement_invalid",
                blockers=("operator_operation_acknowledgement_invalid",),
                status_code=400,
            )
        expected_revision = payload.get("expected_state_revision")
        if type(expected_revision) is not int:
            raise OperatorContractError(
                "operator_operation_acknowledgement_invalid",
                blockers=("operator_operation_acknowledgement_invalid",),
                status_code=400,
            )
        return self._operator_operation_store.acknowledge(
            str(operation_id),
            action=str(payload.get("action") or ""),
            expected_state_revision=expected_revision,
        ).to_dict()

    def _guardian_observation_from_status(self, status: Mapping[str, Any]) -> GuardianObservation | None:
        def number(value: object) -> float | None:
            try:
                candidate = float(value) if value not in (None, "") else None
            except (TypeError, ValueError, OverflowError):
                return None
            return candidate if candidate is not None and candidate == candidate and abs(candidate) != float("inf") else None

        supplied = status.get("guardian_observation")
        if isinstance(supplied, Mapping):
            try:
                return GuardianObservation.from_mapping(supplied)
            except Exception:
                return None
        runtime = _mapping(status.get("runtime"))
        exchange = _mapping(status.get("exchange"))
        ledger = _mapping(status.get("ledger_reconciliation"))
        private_ws = _mapping(status.get("private_ws"))
        captured = self._parse_guardian_datetime(exchange.get("captured_at_utc") or exchange.get("captured_at"))
        reference = self._parse_guardian_datetime(status.get("as_of_utc") or runtime.get("last_heartbeat_utc"))
        heartbeat = self._parse_guardian_datetime(private_ws.get("heartbeat_at_utc") or runtime.get("last_heartbeat_utc"))
        run_id = str(runtime.get("run_id") or runtime.get("session_id") or "").strip()
        namespace = str(runtime.get("credential_namespace") or runtime.get("key_namespace") or "").strip()
        epoch = runtime.get("authoritative_liveness_epoch")
        if not run_id or not namespace or type(epoch) is not int or captured is None or reference is None or heartbeat is None:
            return None
        positions = exchange.get("positions")
        pending_orders = exchange.get("pending_orders")
        pending_algos = exchange.get("pending_algo_orders")
        if not isinstance(positions, list) or not isinstance(pending_orders, list) or not isinstance(pending_algos, list):
            return None
        balance = _mapping(exchange.get("balance"))
        mark = _mapping(exchange.get("mark"))
        instrument = _mapping(exchange.get("instrument"))
        contract_value = number(instrument.get("contract_value_btc"))
        mark_price = number(mark.get("mark_price") or mark.get("markPx"))
        contracts = sum(abs(number(row.get("contracts") or row.get("pos") or 0) or 0.0) for row in positions if isinstance(row, Mapping))
        exposure = contracts * contract_value * mark_price if contract_value is not None and mark_price is not None else None
        pnl_values: dict[str, Any] = {}
        if balance.get("unrealized_pnl_observed") is True and balance.get("unrealized_pnl_usdt") is not None:
            pnl_values["unrealized"] = balance.get("unrealized_pnl_usdt")
        if ledger.get("realized_pnl_observed") is True and ledger.get("realized_pnl") is not None:
            pnl_values["realized"] = ledger.get("realized_pnl")
        if ledger.get("daily_pnl") is not None:
            pnl_values["daily"] = ledger.get("daily_pnl")
        elif "realized" in pnl_values and "unrealized" in pnl_values:
            pnl_values["daily"] = float(pnl_values["realized"]) + float(pnl_values["unrealized"]) + float(ledger.get("funding_cashflow") or 0)
        protection = {"consistent": True, "present": False}
        if pending_algos:
            protection = {"consistent": None, "present": True, "items": pending_algos}
        evidence = _mapping(ledger.get("reconciliation_evidence"))
        return GuardianObservation(
            source_head=str(status.get("source_head") or ""),
            account_identity=canonical_request_digest({"account": exchange.get("account"), "balance": balance}),
            session_id=run_id,
            key_namespace=namespace,
            client_order_namespace=str(runtime.get("client_order_namespace") or "").strip(),
            owner_identity=str(
                runtime.get("guardian_owner_identity")
                or runtime.get("runtime_identity")
                or run_id
            ).strip(),
            epoch=epoch,
            observed_at_utc=captured,
            reference_time_utc=reference,
            heartbeat_at_utc=heartbeat,
            heartbeat_healthy=private_ws.get("connected") is True and private_ws.get("listener_alive") is True,
            broker_truth=exchange,
            broker_truth_fresh=True,
            facts_fresh=True,
            reconciliation_passed=ledger.get("status") == "reconciled",
            ledger_reconciled=ledger.get("status") == "reconciled",
            snapshot_match=ledger.get("current_state_exchange_snapshot_match") if type(ledger.get("current_state_exchange_snapshot_match")) is bool else None,
            funding_reconciled=ledger.get("funding_cashflow_reconciled") if type(ledger.get("funding_cashflow_reconciled")) is bool else None,
            positions=positions,
            cash=balance,
            pnl=pnl_values,
            exposure={"gross": exposure} if exposure is not None else None,
            open_orders=[*pending_orders, *pending_algos],
            protection_facts=protection,
            positions_consistent=evidence.get("positions_consistent") if type(evidence.get("positions_consistent")) is bool else ledger.get("positions_consistent"),
            cash_consistent=evidence.get("cash_consistent") if type(evidence.get("cash_consistent")) is bool else ledger.get("cash_consistent"),
            pnl_consistent=evidence.get("pnl_consistent") if type(evidence.get("pnl_consistent")) is bool else ledger.get("pnl_consistent"),
            exposure_consistent=evidence.get("exposure_consistent") if type(evidence.get("exposure_consistent")) is bool else ledger.get("exposure_consistent"),
            open_orders_consistent=evidence.get("open_orders_consistent") if type(evidence.get("open_orders_consistent")) is bool else ledger.get("open_orders_consistent"),
            protection_consistent=evidence.get("protection_consistent") if type(evidence.get("protection_consistent")) is bool else ledger.get("protection_consistent"),
            account_equity=number(balance.get("equity_usdt")),
            total_exposure=exposure,
            daily_pnl=number(pnl_values.get("daily")),
            drawdown=number(ledger.get("drawdown")),
            risk_increasing_open_order_count=None,
            protective_reduce_only_order_count=None,
            evidence_identity=str(status.get("guardian_evidence_identity") or "btc_demo_runtime_guardian_observation_v1"),
        )

    def execute_operator_action_v2(
        self,
        action: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """Authorize, durably claim, and execute one allowlisted action.

        The durable claim is made before dispatch.  A replay therefore returns
        the same operation without invoking the controller again, including if
        the prior operation is still queued/running.
        """

        if not validate_idempotency_key(idempotency_key):
            raise OperatorContractError(
                "idempotency_key_required",
                blockers=("idempotency_key_required",),
                status_code=400,
            )
        current_status = self._operator_contract_status()
        self._assert_operator_snapshot_fence(payload, current_status, action=str(action))
        raw_business_payload = self._operator_business_payload(payload)
        business_payload = raw_business_payload
        if str(action) == "authoritative_preflight_start":
            # Final server policy is assembled before idempotency lookup.  A
            # browser cannot reuse a key across a policy/risk/HEAD change.
            business_payload = self._authoritative_start_request_payload(
                raw_business_payload,
                status=current_status,
            )
        elif str(action) == "refresh_account_snapshot":
            # The browser supplies only intent and the snapshot fence.  Bind
            # the durable/idempotent operation to the final server command so
            # client magic strings or environment fields cannot alter it.
            business_payload = self._refresh_account_snapshot_command_payload()
        try:
            existing = self._operator_operation_store.find_existing(
                action=str(action),
                payload=business_payload,
                idempotency_key=str(idempotency_key),
            )
        except OperatorContractError as exc:
            if exc.code != "idempotency_key_reuse_mismatch" or str(action) != "authoritative_preflight_start":
                raise
            # Compatibility migration for rows written before the binding
            # schema existed.  This path cannot match a new policy-bound row.
            existing = self._operator_operation_store.find_existing_legacy(
                action=str(action),
                payload=raw_business_payload,
                idempotency_key=str(idempotency_key),
            )
        if existing is not None:
            return existing.to_dict()
        # Authorize against the same fresh projection used by the snapshot
        # fence before taking a durable operation claim.  A stale/missing
        # fence therefore cannot create an operation row or reach a
        # controller/dispatcher.
        self.authorize_operator_action(
            str(action),
            idempotency_key=idempotency_key,
            status_projection=current_status,
        )
        operation, replayed = self._operator_operation_store.begin(
            action=str(action),
            payload=business_payload,
            idempotency_key=str(idempotency_key),
        )
        if replayed:
            return operation.to_dict()
        try:
            self._operator_operation_store.transition(
                operation.operation_id,
                state="running",
                phase="dispatching",
            )
            dispatch_payload = dict(business_payload)
            if str(action) == "authoritative_preflight_start":
                dispatch_payload["parent_operation_id"] = operation.operation_id
            result = self._dispatch_operator_action_v2(
                str(action), dispatch_payload, idempotency_key=str(idempotency_key)
            )
            if str(action) == "authoritative_preflight_start":
                completed = self._project_inner_start_operation(
                    operation,
                    result,
                    authoritative_payload=dispatch_payload,
                )
            else:
                completed = self._operator_operation_store.transition(
                    operation.operation_id,
                    state="succeeded",
                    phase="completed",
                    result_present=True,
                )
            # Return only a read model and a boolean result marker.  Raw
            # controller payloads can contain paths or transport diagnostics.
            return {
                **completed.to_dict(),
                "result_present": completed.result_present,
                "result_summary": {
                    "accepted": isinstance(result, Mapping),
                    "inner_state": str(_mapping(result).get("state") or _mapping(result).get("start_operation", {}).get("state") or "") if isinstance(result, Mapping) else "",
                    "safety_flags": {name: False for name in (
                        "promotion_eligible", "paper", "live", "private",
                        "order", "real_order", "transfer", "withdraw",
                    )},
                },
            }
        except OperatorContractError as exc:
            self._operator_operation_store.transition(
                operation.operation_id,
                state="blocked",
                phase="blocked",
                blockers=exc.blockers,
            )
            raise
        except Exception as exc:
            blockers = _safe_operator_exception_blockers(exc)
            self._operator_operation_store.transition(
                operation.operation_id,
                state="failed",
                phase="dispatch_failed",
                blockers=blockers,
                retryable=False,
            )
            raise OperatorContractError(
                blockers[0],
                blockers=blockers,
                status_code=400,
            ) from exc

    def _project_inner_start_operation(
        self,
        operation: OperationReadModel,
        result: Mapping[str, Any],
        *,
        authoritative_payload: Mapping[str, Any],
    ) -> OperationReadModel:
        inner = _mapping(result.get("start_operation")) or _mapping(result)
        inner_id = str(inner.get("operation_id") or "")
        attempt_id = str(inner.get("attempt_id") or "")
        if not inner_id or not attempt_id:
            # Legacy object-level adapters used by read-only contract tests do
            # not expose an inner operation.  They cannot claim the new
            # binding; preserve their historical result shape without
            # weakening the real service path (which always has an identity).
            if not str(authoritative_payload.get("runtime_identity") or ""):
                return self._operator_operation_store.transition(
                    operation.operation_id,
                    state="succeeded",
                    phase="completed",
                    result_present=True,
                )
            raise OperatorContractError(
                "btc_demo_start_attempt_inner_identity_missing",
                blockers=("btc_demo_start_attempt_inner_identity_missing",),
                status_code=423,
            )
        created = operation.created_at_utc
        binding = StartAttemptBinding(
            parent_operation_id=operation.operation_id,
            inner_operation_id=inner_id,
            attempt_id=attempt_id,
            runtime_identity=str(authoritative_payload.get("runtime_identity") or self._runtime_identity),
            source_head=str(authoritative_payload.get("source_head") or ""),
            effective_policy_digest=str(authoritative_payload.get("effective_policy_digest") or ""),
            risk_profile=str(authoritative_payload.get("risk_profile") or self._risk_profile),
            expected_leverage=str(authoritative_payload.get("expected_leverage") or ""),
            account_identity_hash=str(authoritative_payload.get("account_identity_hash") or ""),
            created_at_utc=created,
            updated_at_utc=str(inner.get("updated_at_utc") or created),
            state=str(inner.get("state") or "queued").replace("completed", "succeeded"),
            phase=str(inner.get("phase") or "requested"),
            current_attempt=True,
            historical=False,
        )
        model = self._operator_operation_store.bind_start_attempt(
            operation.operation_id,
            binding.to_dict(),
        )
        inner_state = str(inner.get("state") or "queued")
        state = {
            "queued": "queued",
            "running": "running",
            "completed": "succeeded",
            "succeeded": "succeeded",
            "blocked": "blocked",
            "failed": "failed",
            "interrupted": "interrupted",
            "timed_out": "timed_out",
        }.get(inner_state, "blocked")
        terminal = state in {"succeeded", "failed", "blocked", "interrupted", "timed_out"}
        return self._operator_operation_store.transition(
            model.operation_id,
            state=state,
            phase=str(inner.get("phase") or "running"),
            blockers=tuple(inner.get("blockers") or ()),
            result_present=terminal,
            retryable=False,
        )

    def _synchronize_outer_start_operation(self) -> None:
        """Project durable inner progress; acceptance never implies success."""

        if (
            not hasattr(self, "_operator_operation_store")
            or getattr(self._operator_operation_store, "path", None) is None
        ):
            return
        outer = self._operator_operation_store.latest_unacknowledged(
            action="authoritative_preflight_start"
        )
        if outer is None or not outer.start_attempt:
            return
        if outer.state in {"succeeded", "failed", "blocked", "interrupted", "timed_out"}:
            return
        try:
            controller_status = self.controller.status()
        except Exception:
            return
        inner = _mapping(controller_status.get("start_operation") or _mapping(controller_status.get("runtime")).get("start_operation"))
        binding = _mapping(outer.start_attempt)
        if str(inner.get("operation_id") or "") != str(binding.get("inner_operation_id") or ""):
            return
        state = {
            "queued": "queued",
            "running": "running",
            "completed": "succeeded",
            "succeeded": "succeeded",
            "blocked": "blocked",
            "failed": "failed",
            "interrupted": "interrupted",
            "timed_out": "timed_out",
        }.get(str(inner.get("state") or ""))
        if state is None:
            return
        self._operator_operation_store.transition(
            outer.operation_id,
            state=state,
            phase=str(inner.get("phase") or outer.phase),
            blockers=tuple(inner.get("blockers") or ()),
            result_present=state in {"succeeded", "failed", "blocked", "interrupted", "timed_out"},
        )

    @staticmethod
    def _operator_business_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Remove read-version fencing fields before controller dispatch."""

        business = dict(payload)
        for key in (
            "expected_runtime_identity",
            "expected_state_revision",
            "expected_state_digest",
            "snapshot_fence",
            "expected_guardian_generation",
            "expected_guardian_evidence_identity",
            "expected_guardian_evidence_digest",
            "expected_guardian_observation_digest",
            "guardian_evidence_fence",
        ):
            business.pop(key, None)
        return business

    @staticmethod
    def _assert_operator_snapshot_fence(
        payload: Mapping[str, Any],
        current_status: Mapping[str, Any],
        *,
        action: str = "",
    ) -> None:
        fence = _mapping(payload.get("snapshot_fence"))
        top_level = (
            payload.get("expected_runtime_identity"),
            payload.get("expected_state_revision"),
            payload.get("expected_state_digest"),
        )
        nested = (
            fence.get("runtime_identity"),
            fence.get("state_revision"),
            fence.get("state_digest"),
        )
        # A redundant nested fence is compatibility-only: when supplied it
        # must agree with the same user-visible document, never override it.
        if fence and any(
            top is not None and child is not None and top != child
            for top, child in zip(top_level, nested)
        ):
            raise OperatorContractError(
                "operator_stale_snapshot",
                blockers=("operator_stale_snapshot",),
                reasons=("snapshot_fence_duplicate_mismatch",),
                status_code=409,
            )
        expected_identity = nested[0] if nested[0] is not None else top_level[0]
        expected_revision = nested[1] if nested[1] is not None else top_level[1]
        expected_digest = nested[2] if nested[2] is not None else top_level[2]
        current_identity = str(current_status.get("runtime_identity") or "")
        current_revision = current_status.get("state_revision")
        current_digest = str(current_status.get("state_digest") or "")
        valid = (
            bool(current_identity)
            and isinstance(expected_identity, str)
            and expected_identity == current_identity
            and isinstance(expected_revision, int)
            and expected_revision == current_revision
            and isinstance(expected_digest, str)
            and expected_digest == current_digest
        )
        if not valid:
            raise OperatorContractError(
                "operator_stale_snapshot",
                blockers=("operator_stale_snapshot",),
                reasons=("snapshot_fence_missing_or_mismatch",),
                status_code=409,
            )
        if action in {"acknowledge_guardian_trip", "recover_guardian_after_fresh_preflight"}:
            guardian = _mapping(current_status.get("guardian"))
            fence = _mapping(payload.get("guardian_evidence_fence"))
            expected_generation = payload.get("expected_guardian_generation", fence.get("generation"))
            expected_identity = payload.get("expected_guardian_evidence_identity", fence.get("evidence_identity"))
            expected_digest = payload.get("expected_guardian_evidence_digest", fence.get("evidence_digest"))
            expected_observation = payload.get("expected_guardian_observation_digest", fence.get("observation_digest"))
            try:
                expected_generation = int(expected_generation)
            except (TypeError, ValueError):
                expected_generation = None
            current_generation = int(guardian.get("generation") or 0)
            current_identity = str(guardian.get("evidence_identity") or "")
            current_digest = str(guardian.get("evidence_digest") or "")
            current_observation = str(guardian.get("observation_digest") or "")
            if expected_generation != current_generation or str(expected_identity or "") != current_identity or str(expected_digest or "") != current_digest or (
                expected_observation is not None and str(expected_observation or "") != current_observation
            ):
                raise OperatorContractError(
                    "operator_stale_guardian_evidence",
                    blockers=("operator_stale_guardian_evidence",),
                    reasons=("guardian_evidence_fence_missing_or_mismatch",),
                    status_code=409,
                )

    def authorize_operator_action(
        self,
        action: str,
        *,
        idempotency_key: str | None = None,
        status_projection: Mapping[str, Any] | None = None,
    ):
        """Authorize through the enriched status used by the V2 GET route."""

        return _authorize_operator_action(
            status_projection if status_projection is not None else self._operator_contract_status(),
            action,
            idempotency_key=idempotency_key,
            operation=self._operator_operation_store.latest_unacknowledged(
                action=str(action),
            ),
        )

    def _operator_contract_status(self) -> dict[str, Any]:
        """Attach durable application identity to the controller snapshot.

        The controller remains the sole source of runtime facts.  These fields
        are an adapter projection: source HEAD is read from the repository,
        revision is the persisted event/start-operation revision, and the
        digest is a deterministic hash of the returned snapshot.  No caller
        payload can supply or override them.
        """

        status = dict(self.status())
        if hasattr(self, "_operator_operation_store"):
            self._operator_operation_store.reconcile_start_attempt_identity(
                self._current_start_attempt_identity(status)
            )
        self._synchronize_outer_start_operation()
        runtime = dict(status.get("runtime") or {})
        start_operation = dict(
            status.get("start_operation")
            or runtime.get("start_operation")
            or {}
        )
        # Persisted operations may have been created by an older checkout.
        # The V2 contract is a current-service identity, so never inherit
        # their historical source_head; bind it to the repository HEAD that
        # is actually serving this projection.
        source_head = _current_repo_head(settings.repo_root)
        events = status.get("events")
        raw_revision = status.get("state_revision")
        if raw_revision is None:
            raw_revision = runtime.get("state_revision")
        if raw_revision is None:
            raw_revision = start_operation.get("revision")
        if raw_revision is None and isinstance(events, list):
            # An explicit persisted event list is a durable revision source;
            # absence of that list remains unknown rather than becoming 0.
            raw_revision = len(events)
        try:
            revision = int(raw_revision) if raw_revision is not None else None
        except (TypeError, ValueError):
            revision = None
        runtime_identity = str(
            status.get("runtime_identity")
            or runtime.get("runtime_identity")
            or runtime.get("run_id")
            or ""
        )
        # Runtime/operation timestamps remain authoritative when present.  A
        # brand-new stopped controller has none, so bind its read model to the
        # stable initialization time of this backend process.  That timestamp
        # only identifies the projection and does not claim account freshness.
        as_of = str(
            status.get("as_of_utc")
            or runtime.get("as_of_utc")
            or status.get("captured_at_utc")
            or runtime.get("last_heartbeat_utc")
            or runtime.get("stopped_at_utc")
            or runtime.get("started_at_utc")
            or start_operation.get("updated_at_utc")
            or start_operation.get("created_at_utc")
            or getattr(self, "_operator_projection_initialized_at_utc", "")
            or ""
        )
        status.update(
            {
                "source_head": source_head,
                "state_revision": revision,
                "runtime_identity": runtime_identity,
                "as_of_utc": as_of,
            }
        )
        guardian = _mapping(status.get("guardian"))
        exchange = _mapping(status.get("exchange"))
        position_rows = _rows(exchange.get("positions"))
        position_known = "positions" in exchange and all(isinstance(row, Mapping) for row in (exchange.get("positions") or []))
        position_nonflat = any(_nonzero(row.get("contracts")) for row in position_rows)
        status["position_facts_known"] = bool(position_known)
        status["position_nonflat"] = position_nonflat if position_known else None
        persistence_state = str(guardian.get("persistence_state") or "missing")
        guardian_action_capabilities = {
            "acknowledge_guardian_trip": {
                "allowed": persistence_state == "tripped"
                and guardian.get("generation", 0) > 0
                and bool(guardian.get("evidence_identity"))
                and bool(guardian.get("evidence_digest")),
                "blockers": [] if persistence_state == "tripped" else ["guardian_trip_not_acknowledgeable"],
                "reason_codes": ["guardian_trip_requires_operator_ack"],
            },
            "recover_guardian_after_fresh_preflight": {
                "allowed": (
                    persistence_state in {"missing", "acknowledged"}
                    and not bool(_mapping(status.get("runtime")).get("active"))
                    and _mapping(status.get("runtime")).get("opening_allowed") is False
                    and _mapping(status.get("runtime")).get("cancel_only") is True
                    and isinstance(status.get("guardian_observation"), Mapping)
                ),
                "blockers": [] if persistence_state in {"missing", "acknowledged"} else ["guardian_recovery_not_ready"],
                "reason_codes": ["fresh_guardian_observation_required"],
            },
        }
        status["guardian_action_capabilities"] = guardian_action_capabilities
        guardian_observation = self._guardian_observation_from_status(status)
        if guardian_observation is not None:
            status["guardian_observation"] = guardian_observation.to_dict()
            status["guardian_action_capabilities"]["recover_guardian_after_fresh_preflight"]["allowed"] = (
                persistence_state in {"missing", "acknowledged"}
                and not bool(_mapping(status.get("runtime")).get("active"))
                and _mapping(status.get("runtime")).get("opening_allowed") is False
                and _mapping(status.get("runtime")).get("cancel_only") is True
                and not bool(guardian_observation.open_orders)
            )
        status["protective_capabilities"] = _project_protective_capabilities(
            status,
            max_configured_leverage=Decimal(
                str(
                    _DEMO_PROFILE_MAX_LEVERAGE.get(
                        getattr(
                            self,
                            "_risk_profile",
                            BTC_DEMO_RISK_PROFILE_BASELINE_1X,
                        ),
                        Decimal("1"),
                    )
                )
            ),
        )
        projection_error = _mapping(status["protective_capabilities"]).get("projection_error_code")
        if projection_error:
            status["protective_capability_blockers"] = [str(projection_error)]
        status["state_digest"] = canonical_request_digest(status)
        return status

    def _dispatch_operator_action_v2(
        self,
        action: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if action == "authoritative_preflight_start":
            start_payload = self._authoritative_start_request_payload(payload)
            request_blockers = tuple(
                OkxDemoPaperStartRequest.from_mapping(start_payload).validate()
            )
            if request_blockers:
                raise OperatorContractError(
                    request_blockers[0],
                    blockers=request_blockers,
                    reasons=("authoritative_start_request_invalid",),
                    status_code=400,
                )
            operation_method = getattr(self, "start_operation", None)
            if callable(operation_method):
                return operation_method(
                    start_payload,
                    idempotency_key=idempotency_key,
                )
            return self.start(start_payload)
        if action == "refresh_account_snapshot":
            # Compose again at the dispatch boundary so direct unit adapters
            # and future callers cannot bypass the application-owned command.
            return self.reconcile(self._refresh_account_snapshot_command_payload())
        methods = {
            "stop_keep_position": self.stop,
            "stop_and_flatten": self.stop_and_flatten,
            "enter_cancel_only": self.cancel_only,
            "emergency_reduce_only_exit": self.emergency_reduce_only_exit,
            "acknowledge_guardian_trip": self.acknowledge_guardian_trip,
            "recover_guardian_after_fresh_preflight": self.recover_guardian_after_fresh_preflight,
        }
        method = methods.get(action)
        if method is None:
            raise OperatorContractError(
                "operator_action_not_allowlisted",
                blockers=("operator_action_not_allowlisted",),
                status_code=400,
            )
        return method(payload)

    @staticmethod
    def _refresh_account_snapshot_command_payload() -> dict[str, Any]:
        return RefreshAccountSnapshotCommand(
            instrument_id=OKX_DEMO_INSTRUMENT_ID,
            confirmation_text=OKX_DEMO_PAPER_CONFIRMATION,
        ).to_controller_payload()

    def _authoritative_start_request_payload(
        self,
        payload: Mapping[str, Any],
        *,
        status: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Bind operator intent to immutable server-owned Demo safety policy.

        The browser may select a frozen strategy and record human confirmations,
        but it cannot grant authorization, choose account/order limits, alter the
        dead-man namespace, or replace the approved protection policy.
        """

        projection = status or {}
        runtime = _mapping(projection.get("runtime"))
        runtime_identity = str(
            projection.get("runtime_identity")
            or runtime.get("runtime_identity")
            or getattr(self, "_runtime_identity", "")
        )
        current_identity = self._current_start_attempt_identity(projection)
        source_head = str(
            (current_identity or {}).get("source_head")
            or projection.get("source_head")
            or _current_repo_head(settings.repo_root)
        )
        runtime_identity = str(
            (current_identity or {}).get("runtime_identity") or runtime_identity
        )
        risk_profile = str(
            (current_identity or {}).get("risk_profile")
            or getattr(self, "_risk_profile", BTC_DEMO_RISK_PROFILE_BASELINE_1X)
        )
        expected_leverage = str(
            (current_identity or {}).get("expected_leverage")
            or _DEMO_PROFILE_MAX_LEVERAGE.get(risk_profile, Decimal("1"))
        )
        account_hash = str(
            (current_identity or {}).get("account_identity_hash")
            or getattr(self, "_account_identity_hash", "")
            or ""
        )
        # A real controller exposes this method and therefore has a
        # server-owned runtime identity even when the account snapshot is not
        # yet trusted.  Refuse before durable find_existing/begin; object-level
        # contract fakes without an identity retain their read-only legacy
        # payload shape and never claim a current attempt.
        controller_has_authoritative_identity = callable(
            getattr(
                getattr(self, "controller", None),
                "current_start_attempt_identity",
                None,
            )
        )
        if controller_has_authoritative_identity and runtime_identity and not account_hash:
            raise OperatorContractError(
                "btc_demo_authoritative_account_identity_hash_missing",
                blockers=("btc_demo_authoritative_account_identity_hash_missing",),
                reasons=("authoritative_account_snapshot_required",),
                status_code=423,
            )
        payload_copy = dict(payload)
        policy, policy_digest = build_effective_policy(
            source_head=source_head,
            runtime_identity=runtime_identity,
            risk_profile=risk_profile,
            expected_leverage=expected_leverage,
            account_identity_hash_value=account_hash,
            instrument_id=OKX_DEMO_INSTRUMENT_ID,
            margin_mode="isolated",
            order_contracts=OKX_DEMO_PAPER_CONTRACTS,
            max_net_contracts=OKX_DEMO_PAPER_MAX_NET_CONTRACTS,
            max_notional_usdt=OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
            protection_policy=OKX_DEMO_APPROVED_PROTECTION_POLICY,
        )
        composed = {
            **payload_copy,
            "authorization_ticket": OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
            "margin_mode": "isolated",
            "order_contracts": OKX_DEMO_PAPER_CONTRACTS,
            "max_net_contracts": OKX_DEMO_PAPER_MAX_NET_CONTRACTS,
            "max_notional_usdt": OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
            "dead_man_tag": OKX_DEMO_PAPER_ORDER_TAG,
            "server_side_protection_policy": dict(
                OKX_DEMO_APPROVED_PROTECTION_POLICY
            ),
        }
        # A fully composed backend service has a non-empty opaque identity;
        # object-level test adapters without one retain the legacy request
        # contract and cannot accidentally claim a current attempt.
        if runtime_identity and account_hash:
            composed.update(
                {
                    "source_head": source_head,
                    "runtime_identity": runtime_identity,
                    "risk_profile": risk_profile,
                    "expected_leverage": expected_leverage,
                    "account_identity_hash": account_hash,
                    "effective_policy": policy,
                    "effective_policy_digest": policy_digest,
                }
            )
        return composed

    def _current_start_attempt_identity(
        self,
        status: Mapping[str, Any],
    ) -> dict[str, str] | None:
        """Project the serving service identity before durable lookup."""

        # Object-level compatibility fakes intentionally omit this attribute.
        # A real service always creates it, including when the value is empty;
        # an unknown identity therefore remains fail-closed.
        if not hasattr(self, "_runtime_identity"):
            return None
        controller_identity_getter = getattr(
            getattr(self, "controller", None),
            "current_start_attempt_identity",
            None,
        )
        if callable(controller_identity_getter):
            try:
                identity = dict(controller_identity_getter())
            except Exception:
                identity = {}
            if identity:
                return {
                    "runtime_identity": str(identity.get("runtime_identity") or ""),
                    "source_head": str(identity.get("source_head") or ""),
                    "effective_policy_digest": str(
                        identity.get("effective_policy_digest") or ""
                    ),
                    "risk_profile": str(identity.get("risk_profile") or ""),
                    "expected_leverage": str(identity.get("expected_leverage") or ""),
                    "account_identity_hash": str(
                        identity.get("account_identity_hash") or ""
                    ),
                }
        runtime = _mapping(status.get("runtime"))
        runtime_identity = str(
            status.get("runtime_identity")
            or runtime.get("runtime_identity")
            or getattr(self, "_runtime_identity", "")
        )
        source_head = _current_repo_head(settings.repo_root)
        risk_profile = str(
            getattr(
                self,
                "_risk_profile",
                BTC_DEMO_RISK_PROFILE_BASELINE_1X,
            )
        )
        expected_leverage = str(
            _DEMO_PROFILE_MAX_LEVERAGE.get(
                risk_profile,
                Decimal("1"),
            )
        )
        account_identity_hash = str(
            getattr(self, "_account_identity_hash", "") or ""
        )
        _, policy_digest = build_effective_policy(
            source_head=source_head,
            runtime_identity=runtime_identity,
            risk_profile=risk_profile,
            expected_leverage=expected_leverage,
            account_identity_hash_value=account_identity_hash,
            instrument_id=OKX_DEMO_INSTRUMENT_ID,
            margin_mode="isolated",
            order_contracts=OKX_DEMO_PAPER_CONTRACTS,
            max_net_contracts=OKX_DEMO_PAPER_MAX_NET_CONTRACTS,
            max_notional_usdt=OKX_DEMO_PAPER_MAX_NOTIONAL_USDT,
            protection_policy=OKX_DEMO_APPROVED_PROTECTION_POLICY,
        )
        return {
            "runtime_identity": runtime_identity,
            "source_head": source_head,
            "effective_policy_digest": policy_digest,
            "risk_profile": risk_profile,
            "expected_leverage": expected_leverage,
            "account_identity_hash": account_identity_hash,
        }

    def _guardian_supervisor_for_mutation(self) -> RuntimeRiskGuardianSupervisor:
        getter = getattr(self._production_composition, "_supervisor", None)
        try:
            supervisor = getter() if callable(getter) else None
        except Exception as exc:
            raise OperatorContractError(
                "guardian_supervisor_capability_missing",
                blockers=("guardian_supervisor_capability_missing",),
                status_code=423,
            ) from exc
        if not isinstance(supervisor, RuntimeRiskGuardianSupervisor):
            raise OperatorContractError(
                "guardian_supervisor_capability_missing",
                blockers=("guardian_supervisor_capability_missing",),
                status_code=423,
            )
        return supervisor

    def acknowledge_guardian_trip(self, payload: Mapping[str, object]) -> dict[str, Any]:
        guardian = _mapping(self._operator_contract_status().get("guardian"))
        supervisor = self._guardian_supervisor_for_mutation()
        try:
            record = supervisor.acknowledge(
                generation=int(payload.get("expected_guardian_generation") or 0),
                evidence_identity=str(payload.get("expected_guardian_evidence_identity") or ""),
                evidence_digest=str(payload.get("expected_guardian_evidence_digest") or ""),
                acknowledgement_id=str(payload.get("acknowledgement_id") or payload.get("confirmation_text") or ""),
            )
        except Exception as exc:
            raise OperatorContractError(
                "guardian_acknowledgement_rejected",
                blockers=(str(exc) or "guardian_acknowledgement_rejected",),
                status_code=423,
            ) from exc
        return {"guardian": {**guardian, "persistence_state": "acknowledged", "acknowledged": True, "state_revision": record.state_revision}, "accepted": True}

    def recover_guardian_after_fresh_preflight(self, payload: Mapping[str, object]) -> dict[str, Any]:
        status = self._operator_contract_status()
        observation = self._guardian_observation_from_status(status)
        if observation is None:
            raise OperatorContractError(
                "guardian_fresh_observation_missing",
                blockers=("guardian_fresh_observation_missing",),
                status_code=423,
            )
        supervisor = self._guardian_supervisor_for_mutation()
        try:
            recovery_generation = int(_mapping(status.get("guardian")).get("generation") or 0)
            recovery_decision = supervisor.guardian.evaluate(observation, generation=recovery_generation)
            record = supervisor.bootstrap_or_recover(
                observation,
                operator_confirmation=payload.get("confirmation_text") in {"RECOVER GUARDIAN", "BOOTSTRAP GUARDIAN"}
                or payload.get("operator_confirmation") is True,
                expected_generation=int(payload.get("expected_guardian_generation") or 0),
                expected_revision=int(_mapping(status.get("guardian")).get("state_revision") or 0),
                recovery_evidence_identity=recovery_decision.evidence_identity,
                recovery_evidence_digest=recovery_decision.evidence_digest,
            )
        except Exception as exc:
            raise OperatorContractError(
                "guardian_recovery_rejected",
                blockers=(str(exc) or "guardian_recovery_rejected",),
                status_code=423,
            ) from exc
        return {"guardian": record.to_dict(), "accepted": True}

    def emergency_reduce_only_exit(
        self,
        payload: Mapping[str, object],
    ) -> dict:
        """Forward the narrow emergency action to the canonical controller.

        The application port intentionally remains unchanged: this route is a
        stopped-state operator capability, not a normal start/order surface.
        A controller without the canonical method fails closed before any
        client, WS or exchange operation can be attempted.
        """

        method = getattr(self.controller, "emergency_reduce_only_exit", None)
        if not callable(method):
            raise RuntimeError(
                "btc_demo_emergency_reduce_only_exit_controller_capability_missing"
            )
        return method(payload)

    def stop_and_flatten(
        self,
        payload: Mapping[str, object],
    ) -> dict:
        """Forward the normal-session, one-shot reduce-only stop action."""

        method = getattr(self.controller, "stop_and_flatten", None)
        if not callable(method):
            raise RuntimeError(
                "btc_demo_stop_and_flatten_controller_capability_missing"
            )
        return method(payload)

    def _risk_profile_payload(self) -> dict[str, object]:
        return {
            "schema_version": "btc_demo_risk_profile_v1",
            "name": self._risk_profile,
            "scope": "okx_demo_only",
            "instrument_id": OKX_DEMO_INSTRUMENT_ID,
            "margin_mode": "isolated",
            "max_configured_leverage": str(
                _DEMO_PROFILE_MAX_LEVERAGE[self._risk_profile]
            ),
            "max_order_notional_usdt": str(
                OKX_DEMO_PAPER_MAX_NOTIONAL_USDT
            ),
            "real_money_max_leverage_unchanged": str(
                _REAL_MONEY_MAX_LEVERAGE
            ),
            "auto_start_on_backend_launch": False,
            "live_order_allowed": False,
            "real_money_order_allowed": False,
        }


def _select_demo_risk_profile(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _DEMO_PROFILE_MAX_LEVERAGE:
        return BTC_DEMO_RISK_PROFILE_BASELINE_1X
    return normalized


def _historical_start_operation_blockers(
    operation: Mapping[str, Any],
) -> set[str]:
    """Identify exact blocker codes owned by a historical inner attempt."""

    if not operation or operation.get("historical") is not True:
        return set()
    nested = _mapping(operation.get("start_attempt"))
    values: list[Any] = [
        *list(operation.get("blockers") or []),
        operation.get("terminal_error"),
        _mapping(operation.get("incident")).get("code"),
        *list(nested.get("blockers") or []),
        nested.get("terminal_error"),
    ]
    return {
        str(value).strip()
        for value in values
        if str(value or "").strip()
    }


def _drop_historical_start_operation_blockers(
    values: Sequence[Any],
    historical_blockers: set[str],
) -> list[str]:
    if isinstance(values, (str, bytes)):
        values = [values]
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value or "").strip()
            and str(value).strip() not in historical_blockers
        )
    )


def _authoritative_account_identity_ready(
    runtime: Mapping[str, Any],
    account: Mapping[str, Any],
) -> bool:
    """Require matching redacted identity projections in both read models."""

    runtime_identity = _mapping(runtime.get("account_identity"))
    account_identity = _mapping(account.get("identity"))
    required = ("hash", "source", "captured_at_utc")
    if not all(str(runtime_identity.get(key) or "").strip() for key in required):
        return False
    if not all(str(account_identity.get(key) or "").strip() for key in required):
        return False
    if (
        not is_authoritative_account_identity_hash(runtime_identity.get("hash"))
        or runtime_identity.get("source") != ACCOUNT_IDENTITY_HASH_SOURCE
        or not is_authoritative_account_identity_hash(account_identity.get("hash"))
        or account_identity.get("source") != ACCOUNT_IDENTITY_HASH_SOURCE
    ):
        return False
    return (
        str(runtime_identity.get("hash")) == str(account_identity.get("hash"))
        and str(runtime_identity.get("captured_at_utc"))
        == str(account_identity.get("captured_at_utc"))
    )


def _operator_control_payload(status: Mapping[str, Any]) -> dict[str, Any]:
    """Project raw runtime facts into one authoritative operator contract.

    The projection does not grant order capability.  Its start action means
    exactly one call to the existing authoritative ``/start`` preflight; that
    backend path must still refresh account, orders/OCO, ledger, Private WS,
    market truth and dead-man before it can enable new risk.
    """

    runtime = _mapping(status.get("runtime"))
    start_capability = _mapping(status.get("start_capability"))
    start_capability_blocked = (
        bool(start_capability)
        and start_capability.get("ready") is False
    )
    start_operation = _mapping(
        status.get("start_operation") or runtime.get("start_operation")
    )
    start_operation_active = str(start_operation.get("state") or "") in {
        "queued",
        "running",
    }
    start_attempt = _mapping(
        status.get("start_attempt")
        or start_operation.get("start_attempt")
        or {}
    )
    historical_start_blockers = _historical_start_operation_blockers(
        start_operation
    )
    historical_attempts = []
    for historical in status.get("historical_start_operations") or _mapping(runtime).get("start_operation_history") or []:
        if not isinstance(historical, Mapping):
            continue
        row = dict(historical)
        row["current_attempt"] = False
        row["historical"] = True
        historical_attempts.append(row)
    attempt_current = start_operation.get("current_attempt") is not False and start_attempt.get("historical") is not True
    risk = _mapping(status.get("risk_control"))
    private_ws = _mapping(status.get("private_ws"))
    ledger = _mapping(status.get("ledger_reconciliation"))
    exchange = _mapping(status.get("exchange"))
    observation = _mapping(status.get("observation"))
    account = _mapping(exchange.get("account"))
    dead_man = _mapping(risk.get("dead_man"))

    runtime_status = str(runtime.get("status") or "unknown")
    private_ws_status = str(private_ws.get("status") or "").strip().lower()
    active = runtime.get("active") is True
    opening_allowed = runtime.get("opening_allowed") is True
    cancel_only = runtime.get("cancel_only") is True
    risk_mode = str(risk.get("mode") or "")
    risk_reason = str(risk.get("reason") or "")
    current_risk_reasons = _drop_historical_start_operation_blockers(
        risk_reason.split(";"),
        historical_start_blockers,
    )
    current_runtime_blockers = _drop_historical_start_operation_blockers(
        runtime.get("blockers") or [],
        historical_start_blockers,
    )
    current_private_ws_blockers = _drop_historical_start_operation_blockers(
        private_ws.get("blockers") or [],
        historical_start_blockers,
    )
    current_last_error = str(runtime.get("last_error") or "")
    if current_last_error in historical_start_blockers:
        current_last_error = ""
    positions = _rows(exchange.get("positions"))
    pending_orders = _rows(exchange.get("pending_orders"))
    pending_algos = _rows(exchange.get("pending_algo_orders"))
    risk_order_count, protective_order_count, order_risk_blockers = classify_order_risk(
        [*pending_orders, *pending_algos],
        positions,
    )
    nonflat_positions = [
        row
        for row in positions
        if _nonzero(row.get("contracts"))
    ]

    operational_reasons = _unique_text(
        [
            *current_risk_reasons,
            current_last_error,
            *current_runtime_blockers,
            *current_private_ws_blockers,
            str(dead_man.get("last_error") or ""),
            *_text_rows(start_capability.get("blockers")),
        ],
        excluded=_BENIGN_RUNTIME_REASONS,
    )
    normalized_reasons = " ".join(operational_reasons).lower()
    # A persisted transport error is historical until this runtime exposes a
    # fresh preflight/WS attempt.  In particular, a stopped runtime with a
    # ``not_started`` Private WS has not attempted the current action; its old
    # URLError/50011 diagnostic must remain history, not a current incident.
    fresh_attempt = (
        runtime_status in {"starting", "startup_reconciling"}
        or private_ws_status in {
            "starting",
            "reconnecting",
            "blocked",
            "failed",
            "terminal_failure",
            "stopped_after_start_failure",
        }
    )
    historical_transport = (
        _contains_any(normalized_reasons, _NETWORK_TRANSPORT_TOKENS)
        and not fresh_attempt
        and private_ws_status in {"", "not_started", "stopped", "disconnected"}
    )
    ledger_mismatch = (
        str(ledger.get("status") or "") == "mismatch"
        or ledger.get("current_state_exchange_snapshot_match") is False
        and str(ledger.get("status") or "") not in {"", "not_observed"}
    )
    # A position or an exchange-hosted protection order is normal while the
    # strategy is running.  They become an operator incident only when the
    # runtime is inactive (the preflight requires a flat account), or when an
    # explicit reconciliation/protection reason says the exposure is unsafe.
    inactive_exposure = not active and bool(
        nonflat_positions or pending_orders or pending_algos
    )
    known_account_risk = bool(
        inactive_exposure
        or ledger_mismatch
        or _contains_any(normalized_reasons, _ACCOUNT_RISK_TOKENS)
    )

    authority_recovered = (
        private_ws.get("connected") is True
        and private_ws.get("listener_alive") is True
        and private_ws.get("opening_allowed_after_reconciliation") is True
        and str(ledger.get("status") or "") == "reconciled"
        and ledger.get("current_state_exchange_snapshot_match") is True
        and ledger.get("funding_cashflow_reconciled") is True
        and bool(exchange.get("captured_at_utc"))
    )
    worker_stopped = (
        "worker_stopped" in normalized_reasons
        or "authoritative_liveness_worker_stopped" in normalized_reasons
        or (
            active
            and _mapping(runtime).get("authoritative_liveness_required") is True
            and _mapping(runtime).get("worker_alive") is False
        )
    )

    transient_preflight = runtime_status == "starting" and _contains_any(
        normalized_reasons,
        _TRANSIENT_PREFLIGHT_TOKENS,
    )

    if str(start_capability.get("incident_category") or "") == "account_identity":
        incident_category = "account_identity"
    elif start_capability_blocked:
        incident_category = "local_environment"
    elif known_account_risk:
        incident_category = "account_risk"
    elif transient_preflight:
        incident_category = "preflight_progress"
    elif active and worker_stopped and authority_recovered:
        incident_category = "runtime_recovery"
    elif historical_transport:
        incident_category = "service_restart"
    elif _contains_any(normalized_reasons, _NETWORK_TRANSPORT_TOKENS):
        incident_category = "network_transport"
    elif _contains_any(normalized_reasons, _SERVICE_RESTART_TOKENS):
        incident_category = "service_restart"
    elif operational_reasons or "blocked" in runtime_status or cancel_only:
        incident_category = "runtime_fault"
    else:
        incident_category = "none"

    if start_operation_active or runtime_status == "starting":
        lifecycle = "starting_preflight"
    elif active and opening_allowed and not cancel_only:
        lifecycle = "running"
    elif active:
        lifecycle = "degraded_no_new_risk"
    elif (
        runtime_status == "stopped"
        and risk_mode in {"", "STOPPED"}
        and incident_category == "none"
    ):
        lifecycle = "stopped_clean"
    else:
        lifecycle = "stopped_needs_preflight"

    transitioning = runtime_status in {"starting", "stopping"} or start_operation_active
    preflight_available = (
        not active
        and not transitioning
        and not start_capability_blocked
    )
    strict_exit_matrix = {
        "stop_and_flatten": active and bool(nonflat_positions) and not start_operation_active,
        "emergency_reduce_only_exit": (
            not active
            and bool(nonflat_positions)
            and (
                _mapping(runtime).get("opening") is False
                or (
                    "opening" not in runtime
                    and _mapping(runtime).get("opening_allowed") is False
                )
            )
            and cancel_only
            and risk_mode in {"FROZEN", "FROZEN_UNKNOWN", "STOPPED_WITH_RISK"}
            and not start_operation_active
        ),
    }
    protective_capabilities = _mapping(status.get("protective_capabilities"))
    def reduction_proven(action: str) -> bool:
        capability = _mapping(protective_capabilities.get(action))
        return (
            capability.get("allowed") is True
            and capability.get("reduction_proof") is True
            and capability.get("effect") == "decrease"
        )
    allowed_actions = {
        "authoritative_preflight_start": preflight_available,
        "direct_start": False,
        "refresh_account_snapshot": not transitioning,
        "stop_keep_position": active,
        "stop_and_flatten": strict_exit_matrix["stop_and_flatten"] and reduction_proven("stop_and_flatten"),
        "enter_cancel_only": not cancel_only,
        "emergency_reduce_only_exit": strict_exit_matrix["emergency_reduce_only_exit"] and reduction_proven("emergency_reduce_only_exit"),
        "acknowledge_guardian_trip": _mapping(status.get("guardian_action_capabilities")).get("acknowledge_guardian_trip", {}).get("allowed") is True,
        "recover_guardian_after_fresh_preflight": _mapping(status.get("guardian_action_capabilities")).get("recover_guardian_after_fresh_preflight", {}).get("allowed") is True,
    }

    incident = _incident_payload(
        incident_category,
        active=active,
        reason_codes=operational_reasons,
        current_attempt=attempt_current and not historical_transport,
        historical_reason_codes=(
            list(start_operation.get("historical_reason_codes") or [])
            or (operational_reasons if historical_transport else [])
        ),
    )
    primary_action = _primary_action_payload(
        lifecycle,
        incident_category=incident_category,
        preflight_available=preflight_available,
    )
    stages = _preflight_stage_payloads(
        runtime=runtime,
        risk=risk,
        private_ws=private_ws,
        ledger=ledger,
        exchange=exchange,
        account=account,
        dead_man=dead_man,
        nonflat_positions=nonflat_positions,
        pending_orders=pending_orders,
        pending_algos=pending_algos,
        network_blocked=incident_category == "network_transport",
    )
    if start_operation_active:
        stages = _start_operation_stage_payloads(start_operation, stages)
    evidence_reasons = _unique_text(
        [
            *_text_rows(observation.get("blockers")),
            *_text_rows(observation.get("cumulative_blockers")),
        ]
    )
    evidence_ready = observation.get("promotion_evidence_ready") is True
    if not evidence_ready and not evidence_reasons:
        evidence_reasons = ["promotion_evidence_not_ready"]

    safe_mode = (
        "cancel_only"
        if cancel_only
        else "frozen_unknown"
        if risk_mode == "FROZEN_UNKNOWN"
        else "normal"
    )

    return {
        "schema_version": "btc_demo_operator_control_v1",
        "lifecycle": lifecycle,
        "lifecycle_label": _LIFECYCLE_LABELS[lifecycle],
        "session_active": active,
        "new_risk_allowed": active and opening_allowed and not cancel_only,
        "safe_mode": safe_mode,
        "safe_mode_label": _SAFE_MODE_LABELS[safe_mode],
        "incident": incident,
        "primary_action": primary_action,
        "allowed_actions": allowed_actions,
        "action_matrix": strict_exit_matrix,
        "order_risk": {
            "risk_increasing_open_order_count": risk_order_count,
            "protective_reduce_only_order_count": protective_order_count,
            "blocker_codes": list(order_risk_blockers),
        },
        "protective_capability_blockers": list(
            _text_rows(status.get("protective_capability_blockers"))
        ),
        "guardian": dict(_mapping(status.get("guardian"))),
        "start_operation": json.loads(json.dumps(dict(start_operation))),
        "start_attempt": json.loads(json.dumps(dict(start_attempt))),
        "historical_start_attempts": json.loads(json.dumps(historical_attempts)),
        "historical_operator_operations": json.loads(
            json.dumps(status.get("historical_operator_operations") or [])
        ),
        "start_capability": json.loads(json.dumps(dict(start_capability))),
        "preflight_stages": stages,
        "evidence": {
            "status": "ready" if evidence_ready else "incomplete",
            "impact_scope": "promotion_only",
            "blocks_demo_start": False,
            "reason_codes": evidence_reasons,
        },
        "raw_state": {
            "runtime_status": runtime_status,
            "risk_mode": risk_mode,
            "risk_reason": risk_reason,
        },
    }


def _start_operation_stage_payloads(
    operation: Mapping[str, Any],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project durable operation phases without inventing progress percentages."""

    phase = str(operation.get("phase") or "requested")
    labels = {
        "requested": "已提交启动操作",
        "local_runtime_check": "检查本机运行能力",
        "credentials_demo_identity": "验证 Demo 运行身份",
        "account_positions_orders_oco": "采集账户、仓位与挂单事实",
        "ledger": "对账账本与资金流水",
        "private_ws": "启动并重连 Private WS",
        "broker_truth": "确认最新交易所事实",
        "dead_man": "建立 dead-man 保护",
        "worker": "启动唯一运行 worker",
        "running": "运行中",
    }
    order = [
        "local_runtime_check",
        "credentials_demo_identity",
        "account_positions_orders_oco",
        "ledger",
        "private_ws",
        "broker_truth",
        "dead_man",
        "worker",
    ]
    try:
        current_index = order.index(phase)
    except ValueError:
        current_index = -1
    rows: list[dict[str, Any]] = []
    for index, key in enumerate(order):
        if index < current_index:
            state = "ready"
            detail = "已完成并持久化"
        elif index == current_index:
            state = "waiting"
            detail = "后端正在执行；状态来自持久化启动操作"
        else:
            state = "waiting"
            detail = "等待前序权威阶段完成"
        rows.append({"key": key, "label": labels[key], "state": state, "detail": detail})
    if not rows:
        return fallback
    return rows


def _incident_payload(
    category: str,
    *,
    active: bool,
    reason_codes: list[str],
    current_attempt: bool,
    historical_reason_codes: list[str],
) -> dict[str, Any]:
    definitions = {
        "none": {
            "severity": "info",
            "title": "运行控制面正常",
            "summary": "当前没有影响 Demo 运行的故障。",
            "impact_scope": "none",
        },
        "service_restart": {
            "severity": "warning",
            "title": "服务重启后需要重新预检",
            "summary": "这不是账户风险；重新完成权威预检后才会恢复新开仓能力。",
            "impact_scope": "demo_start",
        },
        "network_transport": {
            "severity": "warning",
            "title": "OKX Demo 网络链路不可用",
            "summary": "现有风险保持冻结；网络恢复后重新预检，不会盲目重发订单。",
            "impact_scope": "new_risk_only",
        },
        "runtime_recovery": {
            "severity": "warning",
            "title": "运行时恢复中",
            "summary": (
                "REST、Private WS 与账本已恢复，worker 正在恢复；"
                "期间保持 cancel-only，不会盲目重发订单。"
            ),
            "impact_scope": "new_risk_only",
        },
        "preflight_progress": {
            "severity": "info",
            "title": "正在验证 Private WS 断线重连",
            "summary": "这是权威启动预检步骤，不是网络事故；完成前不会启用新订单能力。",
            "impact_scope": "demo_start",
        },
        "account_risk": {
            "severity": "critical",
            "title": "账户或订单状态需要人工处理",
            "summary": "检测到仓位、挂单、保护单或账本不一致；禁止新增风险。",
            "impact_scope": "account_and_order_safety",
        },
        "runtime_fault": {
            "severity": "danger",
            "title": "Demo Runtime 故障",
            "summary": (
                "运行中已禁止新增风险，请检查故障步骤。"
                if active
                else "启动前安全检查未通过，请按故障步骤处理。"
            ),
            "impact_scope": "new_risk_only" if active else "demo_start",
        },
        "local_environment": {
            "severity": "danger",
            "title": "本机启动环境不可用",
            "summary": "缺少启动所需的本机运行模块或凭证后端；未执行私有连接或订单动作。",
            "impact_scope": "demo_start",
        },
        "account_identity": {
            "severity": "danger",
            "title": "权威账户身份待刷新",
            "summary": "缺少可信的 Demo 账户身份快照；请刷新权威账户快照后再预检，启动与开仓保持禁止。",
            "impact_scope": "demo_start",
        },
    }
    payload = dict(definitions[category])
    if category == "network_transport" and not active:
        payload.update(
            {
                "summary": "当前未启用订单能力；网络恢复后重新预检，不会盲目重发订单。",
                "impact_scope": "demo_start",
            }
        )
    payload["impact_label"] = _IMPACT_LABELS[str(payload["impact_scope"])]
    payload.update(
        {
            "category": category,
            "reason_codes": reason_codes,
            "current_attempt": current_attempt,
            "historical_reason_codes": historical_reason_codes,
        }
    )
    return payload


def _primary_action_payload(
    lifecycle: str,
    *,
    incident_category: str,
    preflight_available: bool,
) -> dict[str, str]:
    if lifecycle == "starting_preflight":
        return {"code": "wait_for_preflight", "label": "正在执行权威预检"}
    if lifecycle == "running":
        return {"code": "stop_keep_position", "label": "停止策略（保留仓位）"}
    if lifecycle == "degraded_no_new_risk":
        return {"code": "inspect_and_stop", "label": "检查风险并停止"}
    if preflight_available:
        label = (
            "重新核验账户（仅安全时启动）"
            if incident_category == "account_risk"
            else "重新预检并启动"
        )
        return {"code": "authoritative_preflight_start", "label": label}
    return {"code": "none", "label": "当前没有可执行操作"}


def _preflight_stage_payloads(
    *,
    runtime: Mapping[str, Any],
    risk: Mapping[str, Any],
    private_ws: Mapping[str, Any],
    ledger: Mapping[str, Any],
    exchange: Mapping[str, Any],
    account: Mapping[str, Any],
    dead_man: Mapping[str, Any],
    nonflat_positions: list[Mapping[str, Any]],
    pending_orders: list[Mapping[str, Any]],
    pending_algos: list[Mapping[str, Any]],
    network_blocked: bool,
) -> list[dict[str, str]]:
    account_identity_ready = _authoritative_account_identity_ready(runtime, account)
    account_known = (
        bool(exchange.get("captured_at_utc"))
        and bool(account.get("account_level"))
        and account_identity_ready
    )
    account_identity_blocked = not account_identity_ready
    account_blocked = (
        account.get("withdraw_permission_present") is True
        or account_identity_blocked
    )
    account_blocked_detail = (
        "缺少可信账户身份快照，请先刷新权威账户快照"
        if account_identity_blocked
        else "账户权限不满足 Demo 安全边界"
    )
    positions_known = bool(exchange.get("captured_at_utc"))
    positions_blocked = bool(nonflat_positions or pending_orders or pending_algos)
    ledger_ready = (
        ledger.get("status") == "reconciled"
        and ledger.get("current_state_exchange_snapshot_match") is True
        and ledger.get("funding_cashflow_reconciled") is True
    )
    ledger_blocked = ledger.get("status") == "mismatch"
    private_ws_ready = (
        private_ws.get("connected") is True
        and private_ws.get("listener_alive") is True
        and private_ws.get("opening_allowed_after_reconciliation") is True
    )
    private_ws_blocked = network_blocked or (
        str(private_ws.get("status") or "").lower()
        in {"blocked", "failed", "terminal_failure"}
    )
    broker_ready = (
        runtime.get("opening_allowed") is True
        and risk.get("write_path_trusted") is True
    )
    dead_man_ready = (
        dead_man.get("armed") is True
        and dead_man.get("heartbeat_thread_alive") is True
        and dead_man.get("watchdog_renews_dead_man") is True
        and not dead_man.get("last_error")
    )
    dead_man_blocked = bool(dead_man.get("last_error"))

    return [
        _stage(
            "account",
            "1. 账户",
            blocked=account_blocked,
            ready=account_known and not account_blocked,
            ready_detail="Demo 账户身份与权限快照已读取",
            blocked_detail=account_blocked_detail,
            waiting_detail="等待权威账户快照",
        ),
        _stage(
            "positions_orders_oco",
            "2. 仓位 / 挂单 / OCO",
            blocked=positions_blocked,
            ready=positions_known and not positions_blocked,
            ready_detail="账户 flat，普通挂单与 OCO 均为 0",
            blocked_detail="存在仓位、普通挂单或 OCO，需要人工处理",
            waiting_detail="等待权威仓位与订单快照",
        ),
        _stage(
            "ledger",
            "3. 账本",
            blocked=ledger_blocked,
            ready=ledger_ready,
            ready_detail="账本、交易所快照与 funding 已对账",
            blocked_detail="账本与交易所快照不一致",
            waiting_detail="等待账本对账",
        ),
        _stage(
            "private_ws",
            "4. Private WS",
            blocked=private_ws_blocked,
            ready=private_ws_ready,
            ready_detail="Private WS、重连与 REST gapfill 一致",
            blocked_detail="Private WS 网络或重连对账失败",
            waiting_detail="等待 Private WS 启动与重连对账",
        ),
        _stage(
            "broker_truth",
            "5. 行情 / Broker Truth",
            blocked=network_blocked,
            ready=broker_ready,
            ready_detail="行情、REST 与 broker truth 已满足执行边界",
            blocked_detail="公共行情或 REST 链路不可用",
            waiting_detail="等待行情与 broker truth 权威预检",
        ),
        _stage(
            "dead_man",
            "6. dead-man",
            blocked=dead_man_blocked,
            ready=dead_man_ready,
            ready_detail="dead-man 与 watchdog 续租正常",
            blocked_detail="dead-man 续租失败",
            waiting_detail="等待最后启用 dead-man",
        ),
    ]


def _stage(
    key: str,
    label: str,
    *,
    blocked: bool,
    ready: bool,
    ready_detail: str,
    blocked_detail: str,
    waiting_detail: str,
) -> dict[str, str]:
    if blocked:
        return {"key": key, "label": label, "state": "blocked", "detail": blocked_detail}
    if ready:
        return {"key": key, "label": label, "state": "ready", "detail": ready_detail}
    return {"key": key, "label": label, "state": "waiting", "detail": waiting_detail}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _text_rows(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _unique_text(
    values: list[str],
    *,
    excluded: set[str] | None = None,
) -> list[str]:
    ignored = excluded or set()
    result: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in ignored or value in result:
            continue
        result.append(value)
    return result


def _nonzero(value: object) -> bool:
    try:
        return Decimal(str(value or "0")) != 0
    except Exception:
        return True


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    return any(token in value for token in tokens)


__all__ = [
    "BtcDemoRuntimeService",
    "_operator_control_payload",
    "_OKX_NATIVE_DEMO_DATASET_ID",
    "_OKX_NATIVE_DEMO_MANIFEST_GIT_SPEC",
]
