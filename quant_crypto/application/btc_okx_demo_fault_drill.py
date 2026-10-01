"""Fail-closed OKX Demo P0 fault-drill orchestration and immutable receipts.

The application layer validates an explicit Demo envelope, but delegates every
write-capable action to the existing runtime controller.  It never constructs an
exchange order and never bypasses Signal/Target/OrderIntent/Risk/OMS/Ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from quant_crypto.oms.okx_demo import OkxDemoFaultInjectingClient
from quant_crypto.oms.runtime_store import BTCRuntimeStore


DEMO_FAULT_DRILL_SCHEMA_VERSION = "btc_okx_demo_fault_drill_receipt_v1"
DEMO_FAULT_DRILL_EVIDENCE_CLASS = "demo_fault_drill_evidence"
DEMO_FAULT_DRILL_SCENARIOS = (
    "held_position_disconnect",
    "post_response_loss",
    "partial_fill_disconnect",
    "protection_creation_failure",
    "worker_kill",
    "reconnect_full_reconciliation",
)
OKX_DOCS_REVIEW_METADATA = {
    "review_url": "https://www.okx.com/docs-v5/",
    "review_date": "2026-08-05",
    "demo_header": "x-simulated-trading: 1",
    "clOrdId_query": True,
    "attachAlgo_activation_after_fill": True,
    "cancel_all_after_scope": "pending_orders_only_not_positions",
    "cancel_algos_path": "/api/v5/trade/cancel-algos",
    "cancel_algos_batch_max": 10,
    "cancel_algos_required_fields": ["algoId", "instId"],
    "cancel_algos_each_sCode_zero_required": True,
    "cancel_algos_ack_alone_sufficient": False,
    "cancel_algos_pending_and_history_readback_required": True,
}
_HEAD_PATTERN = re.compile(r"[0-9a-f]{40}")
_UNRESOLVED = {"submit_pending", "unknown", "accepted", "reconciled_open"}
_TERMINAL_INTENT_STATUSES = {
    "filled",
    "canceled",
    "cancelled",
    "rejected",
    "expired",
    "terminal",
    "reconciled_terminal",
    "no_fill_terminal",
}
_PARTIAL_RUNTIME_BOUNDARY = (
    "OkxDemoPaperRuntimeController.run_fault_drill_scenario"
)
_PARTIAL_RUNTIME_VERSION = "okx_demo_paper_runtime_v1"
_PARTIAL_ATTESTATION_VERSION = "okx_demo_partial_runtime_attestation_v1"
_PARTIAL_AUTHORITY_VERSION = "okx_demo_partial_fill_authority_v1"
_PARTIAL_CLIENT_ID_PATTERN = re.compile(
    r"^btcDP[A-Za-z0-9._-]{1,63}$"
)
_RECOVERY_BINDING_SCHEMA_VERSION = "btc_okx_demo_recovery_binding_v2"
_FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION = (
    "btc_okx_demo_flat_hosted_exit_binding_v1"
)
_FLAT_HOSTED_EXIT_BINDING_SOURCE = "immutable_flat_hosted_exit_receipt_bundle"
_LEGACY_RECOVERY_BINDING_SCHEMA_VERSION = "btc_okx_demo_recovery_binding_v1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_IDENTITY_ARCHIVE_SCHEMA_VERSION = "btc_owned_id_restore_archive_v1"
_IDENTITY_ARCHIVE_COMPLETION_SCHEMA_VERSION = (
    "btc_owned_id_restore_archive_completion_v1"
)
_IDENTITY_ARCHIVE_REQUIRED_FILE_KINDS = {
    "runtime_events",
    "runtime_state",
    "receipt_ledger",
    "verification",
}
_RECOVERY_GIT_PROBE_TIMEOUT_SECONDS = 5.0
_PARTIAL_VENUE_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
)


class FaultDrillReceiptError(RuntimeError):
    pass


class FaultDrillRuntime(Protocol):
    def fault_drill_snapshot(self) -> Mapping[str, Any]: ...

    def fault_drill_runtime_provenance(self) -> Mapping[str, Any]: ...

    def run_fault_drill_scenario(
        self,
        scenario: str,
        *,
        fault_injector: Any,
        authorization: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def freeze_fault_drill(self, reason: str) -> None: ...


@dataclass(frozen=True)
class BtcOkxDemoFaultDrillConfig:
    repo_root: Path
    receipt_external_root: Path
    source_head: str
    scenario: str
    run_id: str
    execute_demo: bool = False
    environment: str = ""
    instrument_id: str = ""
    margin_mode: str = ""
    leverage: str = ""
    order_contracts: str = ""
    max_notional_usdt: str = ""
    partial_fill_reference_price_usdt: str = ""
    confirm_dedicated_demo_account: bool = False
    operator_ack: bool = False

    def __post_init__(self) -> None:
        repo_root = Path(self.repo_root).resolve()
        requested_receipt_root = Path(self.receipt_external_root)
        if not requested_receipt_root.is_absolute():
            raise FaultDrillReceiptError("fault_drill_receipt_root_must_be_absolute")
        receipt_root = requested_receipt_root.resolve()
        object.__setattr__(self, "repo_root", repo_root)
        object.__setattr__(self, "receipt_external_root", receipt_root)
        if receipt_root == repo_root or repo_root in receipt_root.parents:
            raise FaultDrillReceiptError("fault_drill_receipt_root_must_be_external")
        if self.scenario not in DEMO_FAULT_DRILL_SCENARIOS:
            raise FaultDrillReceiptError("fault_drill_scenario_not_allowlisted")
        if not self.run_id or not re.fullmatch(r"[A-Za-z0-9._-]{3,96}", self.run_id):
            raise FaultDrillReceiptError("fault_drill_run_id_invalid")
        if not _HEAD_PATTERN.fullmatch(self.source_head):
            raise FaultDrillReceiptError("fault_drill_source_head_invalid")

    def preflight_blockers(self) -> list[str]:
        blockers: list[str] = []
        expected = {
            "environment": (self.environment, "OKX Demo"),
            "instrument_id": (self.instrument_id, "BTC-USDT-SWAP"),
            "margin_mode": (self.margin_mode, "isolated"),
            "leverage": (_decimal_text(self.leverage), "3"),
            "order_contracts": (
                _decimal_text(self.order_contracts),
                "0.03" if self.scenario == "partial_fill_disconnect" else "0.01",
            ),
        }
        for name, (actual, required) in expected.items():
            if actual != required:
                blockers.append(f"fault_drill_{name}_mismatch")
        max_notional = _decimal(self.max_notional_usdt)
        max_notional_cap = (
            Decimal("25")
            if self.scenario == "partial_fill_disconnect"
            else Decimal("10")
        )
        if (
            not max_notional.is_finite()
            or max_notional <= 0
            or max_notional > max_notional_cap
        ):
            blockers.append("fault_drill_max_notional_usdt_exceeds_cap")
        if not self.confirm_dedicated_demo_account:
            blockers.append("fault_drill_dedicated_demo_account_not_confirmed")
        if not self.receipt_external_root.exists() or not self.receipt_external_root.is_dir():
            blockers.append("fault_drill_receipt_external_root_missing")
        return blockers

    def partial_fill_estimated_notional_usdt(self) -> Decimal:
        if self.scenario != "partial_fill_disconnect":
            return Decimal("0")
        return (
            _decimal(self.partial_fill_reference_price_usdt)
            * Decimal("0.01")
            * Decimal("0.03")
        )

    def runtime_authorization(self) -> dict[str, Any]:
        return {
            "authorization_ticket": "BTC-OKX-P0-DRILL-SUPERVISOR-FRONTEND-01",
            "source_head": self.source_head,
            "scenario": self.scenario,
            "environment": self.environment,
            "instrument_id": self.instrument_id,
            "margin_mode": self.margin_mode,
            "leverage": self.leverage,
            "order_contracts": self.order_contracts,
            "max_notional_usdt": self.max_notional_usdt,
            "confirm_dedicated_demo_account": self.confirm_dedicated_demo_account,
            "execute_demo": self.execute_demo,
            "evidence_class": DEMO_FAULT_DRILL_EVIDENCE_CLASS,
            "operator_ack": self.operator_ack,
        }


class FaultDrillInjector:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.timeline: list[dict[str, Any]] = []

    def record(self, event: str, **details: Any) -> None:
        self.timeline.append(
            {
                "sequence": len(self.timeline) + 1,
                "event": str(event),
                "details": _safe_json(details),
            }
        )

    def wrap_client(self, client: Any) -> Any:
        if self.scenario not in {
            "post_response_loss",
            "protection_creation_failure",
        }:
            return client
        return OkxDemoFaultInjectingClient(
            client,
            scenario=self.scenario,
            timeline=self.timeline,
        )


class BtcOkxDemoFaultDrillService:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        head_resolver: Callable[[Path], str] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._head_resolver = head_resolver or _repo_head

    def run(
        self,
        config: BtcOkxDemoFaultDrillConfig,
        *,
        runtime: FaultDrillRuntime | None,
    ) -> dict[str, Any]:
        receipt_path = _receipt_path(config)
        if receipt_path.exists():
            raise FaultDrillReceiptError("fault_drill_receipt_already_exists")
        blockers = list(config.preflight_blockers())
        actual_head = self._head_resolver(config.repo_root)
        if actual_head != config.source_head:
            blockers.append("fault_drill_source_head_not_current")
        injector = FaultDrillInjector(config.scenario)
        pre_snapshot: Mapping[str, Any] = {}
        post_snapshot: Mapping[str, Any] = {}
        result: Mapping[str, Any] = {}
        decision = "blocked_preflight" if blockers else "dry_run_fail_closed"
        simulation_only = (
            config.scenario == "partial_fill_disconnect"
            and not config.execute_demo
        )
        orders_posted = 0
        execution_failed = False

        if not blockers and config.execute_demo:
            if runtime is None:
                blockers.append("fault_drill_runtime_required_for_execute")
                decision = "blocked_preflight"
            else:
                pre_snapshot = _safe_json(runtime.fault_drill_snapshot())
                runtime_blockers = _snapshot_blockers(pre_snapshot, phase="preflight")
                if (
                    config.scenario == "partial_fill_disconnect"
                    and _mapping(
                        _mapping(pre_snapshot.get("risk_control")).get(
                            "dead_man"
                        )
                    ).get("armed")
                    is not True
                ):
                    runtime_blockers.append(
                        "fault_drill_preflight_dead_man_not_armed"
                    )
                blockers.extend(runtime_blockers)
                if runtime_blockers:
                    decision = "blocked_preflight"
                else:
                    try:
                        injector.record("runtime_path_entered", boundary="Risk/OMS/Ledger")
                        result = _safe_json(
                            runtime.run_fault_drill_scenario(
                                config.scenario,
                                fault_injector=injector,
                                authorization=config.runtime_authorization(),
                            )
                        )
                        orders_posted = _strict_partial_int(
                            result.get("orders_posted")
                        ) or 0
                    except Exception as exc:  # fail closed; sanitized below
                        execution_failed = True
                        blockers.append(
                            "fault_drill_execution_failed:" + _safe_error(exc)
                        )
                    post_snapshot = _safe_json(runtime.fault_drill_snapshot())
                    observed_side_effects = _derive_observed_order_side_effects(
                        pre_snapshot=pre_snapshot,
                        post_snapshot=post_snapshot,
                        result=result,
                        timeline=injector.timeline,
                    )
                    result = {
                        **dict(result),
                        "observed_order_side_effects": observed_side_effects,
                    }
                    runtime_attestation_reader = getattr(
                        runtime,
                        "fault_drill_runtime_provenance",
                        None,
                    )
                    try:
                        runtime_attestation = (
                            _safe_json(runtime_attestation_reader())
                            if callable(runtime_attestation_reader)
                            else {}
                        )
                    except Exception:
                        runtime_attestation = {}
                    result["_runtime_attestation"] = _mapping(
                        runtime_attestation
                    )
                    if execution_failed:
                        orders_posted = _strict_partial_int(
                            observed_side_effects.get("orders_posted")
                        ) or 0
                        observed_ids = list(
                            observed_side_effects.get(
                                "new_observed_client_order_ids"
                            )
                            or []
                        )
                        if observed_ids:
                            result["clOrdId"] = observed_ids[0]
                        result = {
                            **dict(result),
                            **_failure_identity_projection(
                                post_snapshot=post_snapshot,
                                opening_cl_ord_id=str(result.get("clOrdId") or ""),
                                runtime_attestation=_mapping(
                                    result.get("_runtime_attestation")
                                ),
                            ),
                        }
                    if not execution_failed:
                        observed_runtime_run_ids = (
                            str(
                                _mapping(pre_snapshot.get("runtime")).get(
                                    "run_id"
                                )
                                or ""
                            ),
                            str(
                                _mapping(post_snapshot.get("runtime")).get(
                                    "run_id"
                                )
                                or ""
                            ),
                        )
                        result_blockers = _result_blockers(
                            config.scenario,
                            result,
                            observed_runtime_run_ids=observed_runtime_run_ids,
                            expected_source_head=config.source_head,
                        )
                        blockers.extend(result_blockers)
                        if (
                            config.scenario == "partial_fill_disconnect"
                            and result_blockers
                        ):
                            # A fake, fixture, or incomplete runtime result is
                            # never allowed to cross the receipt boundary as
                            # real Demo evidence.
                            simulation_only = True
                    post_blockers = _snapshot_blockers(post_snapshot, phase="postflight")
                    blockers.extend(post_blockers)
                    if blockers:
                        runtime.freeze_fault_drill("fault_drill_postflight_not_safe")
                        decision = "failed_postflight_frozen"
                    else:
                        decision = str(
                            result.get("decision") or "completed_safe_flat"
                        )
        elif not blockers:
            injector.record("dry_run_no_runtime_capability", orders_posted=0)

        receipt = _build_receipt(
            config=config,
            generated_at=self._clock(),
            decision=decision,
            blockers=blockers,
            simulation_only=simulation_only,
            orders_posted=orders_posted,
            pre_snapshot=pre_snapshot,
            post_snapshot=post_snapshot,
            result=result,
            timeline=injector.timeline,
        )
        return {**receipt, "receipt_path": str(receipt_path)}

    def run_incident_recovery(
        self,
        config: BtcOkxDemoFaultDrillConfig,
        *,
        runtime: FaultDrillRuntime,
        binding: "BtcOkxDemoFailedReceiptBinding",
    ) -> dict[str, Any]:
        receipt_path = _receipt_path(config)
        if receipt_path.exists():
            raise FaultDrillReceiptError("fault_drill_receipt_already_exists")
        blockers = list(config.preflight_blockers())
        if not config.execute_demo:
            blockers.append("fault_drill_incident_recovery_execute_required")
        if config.scenario != binding.failed_receipt_scenario:
            blockers.append("fault_drill_incident_recovery_scenario_mismatch")
        if self._head_resolver(config.repo_root) != config.source_head:
            blockers.append("fault_drill_source_head_not_current")
        pre_snapshot = _safe_json(runtime.fault_drill_snapshot())
        post_snapshot: Mapping[str, Any] = pre_snapshot
        result: Mapping[str, Any] = {}
        if not blockers:
            try:
                result = _safe_json(
                    getattr(runtime, "recover_fault_drill_incident")(
                        authorization=binding.runtime_authorization(
                            runtime_source_head=config.source_head
                        )
                    )
                )
            except Exception as exc:
                blockers.append(
                    "fault_drill_incident_recovery_failed:" + _safe_error(exc)
                )
            post_snapshot = _safe_json(runtime.fault_drill_snapshot())
            if not blockers:
                blockers.extend(
                    _snapshot_blockers(post_snapshot, phase="postflight")
                )
        observed = _derive_observed_order_side_effects(
            pre_snapshot=pre_snapshot,
            post_snapshot=post_snapshot,
            result={
                **dict(result),
                "clOrdId": binding.opening_cl_ord_id,
                "closeClOrdId": binding.expected_close_cl_ord_id,
            },
            timeline=[],
        )
        recovery_intent = _mapping(
            _mapping(_mapping(post_snapshot.get("risk_control")).get(
                "incident_recovery_intents"
            )).get(binding.failed_receipt_sha256)
        )
        close_post_attempted = recovery_intent.get("post_attempted") is True
        cancel_intent = _mapping(
            _mapping(_mapping(post_snapshot.get("risk_control")).get(
                "incident_algo_cancel_intents"
            )).get(binding.algo_cl_ord_id)
        )
        cancel_post_attempted = cancel_intent.get("post_attempted") is True
        observed_order_delta_count = int(observed.get("orders_posted") or 0)
        # A recovery receipt describes this invocation, not historical venue
        # rows that happen to appear in a stale pre/post snapshot.  Only the
        # durable intent written by this invocation can attest a close POST.
        observed = {
            **dict(observed),
            "orders_posted": int(close_post_attempted),
        }
        if close_post_attempted and observed_order_delta_count == 0:
            observed = {
                **dict(observed),
                "bound_client_order_ids": [binding.expected_close_cl_ord_id],
                "orders_posted": 1,
                "submit_outcome_unknown": True,
            }
        normalized_result = {
            **dict(result),
            "clOrdId": binding.opening_cl_ord_id,
            "closeClOrdId": binding.expected_close_cl_ord_id,
            "algoClOrdId": binding.algo_cl_ord_id,
            "algoId": binding.algo_id,
            "failed_receipt_sha256": binding.failed_receipt_sha256,
            "close_post_attempted": close_post_attempted,
            "submit_outcome_unknown": observed.get("submit_outcome_unknown")
            is True,
            "cancel_post_attempted": cancel_post_attempted,
            "cancel_outcome_unknown": bool(
                cancel_post_attempted
                and cancel_intent.get("status") != "terminal_verified"
            ),
            "recovery_mode": binding.recovery_mode,
            "no_order_or_cancel_post": (
                result.get("no_order_or_cancel_post") is True
            ),
            "private_ws_reconciled": (
                result.get("private_ws_reconciled") is True
            ),
            "ledger_reconciled": result.get("ledger_reconciled") is True,
            "incident_recovery_intent": _safe_json(recovery_intent),
            "incident_algo_cancel_intent": _safe_json(cancel_intent),
            "observed_order_side_effects": observed,
        }
        receipt = _build_receipt(
            config=config,
            generated_at=self._clock(),
            decision=(
                "completed_safe_flat"
                if not blockers
                else "failed_postflight_frozen"
            ),
            blockers=blockers,
            simulation_only=False,
            orders_posted=int(observed.get("orders_posted") or 0),
            pre_snapshot=pre_snapshot,
            post_snapshot=post_snapshot,
            result=normalized_result,
            timeline=[],
        )
        receipt["incident_recovery"] = {
            "authorization_ticket": (
                "BTC-OKX-DEMO-INCIDENT-RECOVERY-AND-RECEIPT-05"
            ),
            "failed_receipt_sha256": binding.failed_receipt_sha256,
            "failed_receipt_source_head": binding.failed_receipt_source_head,
            "failed_receipt_scenario": binding.failed_receipt_scenario,
            "failed_receipt_run_id": binding.failed_receipt_run_id,
            "opening_cl_ord_id": binding.opening_cl_ord_id,
            "opening_order_id": binding.opening_order_id,
            "opening_fill_id": binding.opening_fill_id,
            "algo_cl_ord_id": binding.algo_cl_ord_id,
            "algo_id": binding.algo_id,
            "close_cl_ord_id": binding.expected_close_cl_ord_id,
            "one_shot": True,
            "recovery_mode": binding.recovery_mode,
            "flat_identity_sha256": binding.flat_identity_sha256,
            "binding_path": str(binding.binding_path or ""),
            "binding_sha256": binding.binding_sha256,
            "runtime_root": str(binding.runtime_root or ""),
            "runtime_root_sha256": binding.runtime_root_sha256,
            "runtime_run_id": binding.runtime_run_id,
            "client_order_namespace": binding.client_order_namespace,
            "account_identity": binding.account_identity,
            "credential_identity": binding.credential_identity,
            "orders_posted": int(close_post_attempted),
        }
        return {**receipt, "receipt_path": str(receipt_path)}

    def build_startup_failure_receipt(
        self,
        config: BtcOkxDemoFaultDrillConfig,
        *,
        error: BaseException,
        post_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _build_receipt(
            config=config,
            generated_at=self._clock(),
            decision="startup_failed_fail_closed",
            blockers=["fault_drill_startup_failed:" + _safe_error(error)],
            simulation_only=False,
            orders_posted=0,
            pre_snapshot={},
            post_snapshot=_safe_json(post_snapshot or {}),
            result={},
            timeline=[],
        )

    def publish_terminal_receipt(
        self,
        config: BtcOkxDemoFaultDrillConfig,
        receipt: Mapping[str, Any],
        *,
        lifecycle: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Write exactly one receipt after every owned resource is terminal."""

        receipt_path = _receipt_path(config)
        if receipt_path.exists():
            raise FaultDrillReceiptError("fault_drill_receipt_already_exists")
        normalized_lifecycle = {
            key: value is True
            for key, value in dict(lifecycle).items()
            if key
            in {
                "terminal",
                "postflight_complete",
                "startup_failed",
                "runtime_not_constructed",
                "runtime_clean_stop",
                "threads_joined",
                "dead_man_disarmed",
                "writer_lock_released",
                "cleanup_complete",
                "receipt_written_after_cleanup",
            }
        }
        dead_man_evidence = _safe_json(
            _mapping(lifecycle.get("dead_man_terminal_evidence"))
        )

        def evidence_int(name: str, default: int = -1) -> int:
            try:
                return int(dead_man_evidence.get(name))
            except (TypeError, ValueError):
                return default

        normalized_lifecycle["dead_man_terminal_evidence"] = dead_man_evidence
        expiry_markers = {
            "mode",
            "disarm_mode",
            "expiry_utc",
            "observed_server_time_utc",
            "elapsed_after_expiry_seconds",
            "exchange_snapshot_sha256",
            "ledger_snapshot_sha256",
            "private_ws_snapshot_sha256",
            "proof_method",
        }
        expiry_evidence_required = bool(
            dead_man_evidence.get("prior_armed_state") is True
            or any(key in dead_man_evidence for key in expiry_markers)
        )
        expiry_evidence_valid = not expiry_evidence_required or bool(
            dead_man_evidence.get("prior_armed_state") is True
            and dead_man_evidence.get("armed") is False
            and dead_man_evidence.get("mode")
            == "expired_timeout_readonly_evidence"
            and dead_man_evidence.get("disarm_mode")
            == "expired_timeout_readonly_evidence"
            and dead_man_evidence.get("disarm_post_sent") is False
            and evidence_int("caa_post_count") == 0
            and str(dead_man_evidence.get("last_ack_utc") or "")
            and evidence_int("timeout_seconds", 0) > 0
            and str(dead_man_evidence.get("expiry_utc") or "")
            and str(dead_man_evidence.get("observed_server_time_utc") or "")
            and evidence_int("elapsed_after_expiry_seconds") >= 0
            and dead_man_evidence.get("final_flat") is True
            and evidence_int("final_pending_order_count") == 0
            and evidence_int("final_pending_algo_order_count") == 0
            and str(dead_man_evidence.get("exchange_snapshot_sha256") or "")
            == str(dead_man_evidence.get("ledger_snapshot_sha256") or "")
            == str(dead_man_evidence.get("private_ws_snapshot_sha256") or "")
            and str(dead_man_evidence.get("proof_method") or "")
            == "exchange_server_time_plus_final_rest_ws_ledger_fingerprint"
        )
        expiry_evidence_valid = bool(
            expiry_evidence_valid
            and (
                not dead_man_evidence
                or dead_man_evidence.get("armed") is False
            )
        )
        if not expiry_evidence_valid:
            normalized_lifecycle["dead_man_disarmed"] = False
        phase_complete = any(
            normalized_lifecycle.get(key) is True
            for key in (
                "postflight_complete",
                "startup_failed",
                "runtime_not_constructed",
            )
        )
        required = {
            "terminal": normalized_lifecycle.get("terminal") is True,
            "phase_complete": phase_complete,
            "runtime_clean_stop": normalized_lifecycle.get(
                "runtime_clean_stop"
            )
            is True,
            "threads_joined": normalized_lifecycle.get("threads_joined")
            is True,
            "dead_man_disarmed": normalized_lifecycle.get(
                "dead_man_disarmed"
            )
            is True,
            "writer_lock_released": normalized_lifecycle.get(
                "writer_lock_released"
            )
            is True,
            "cleanup_complete": normalized_lifecycle.get(
                "cleanup_complete"
            )
            is True,
            "receipt_written_after_cleanup": normalized_lifecycle.get(
                "receipt_written_after_cleanup"
            )
            is True,
        }
        payload = _safe_json(dict(receipt))
        payload["lifecycle"] = normalized_lifecycle
        if not all(required.values()):
            payload["decision"] = "blocked_frozen_lifecycle_incomplete"
            payload["blockers"] = _dedupe(
                [
                    *[str(row) for row in payload.get("blockers") or []],
                    *[
                        f"fault_drill_lifecycle_{key}_not_proven"
                        for key, passed in required.items()
                        if not passed
                    ],
                    *(
                        ["fault_drill_lifecycle_dead_man_expiry_evidence_invalid"]
                        if not expiry_evidence_valid
                        else []
                    ),
                ]
            )
        _write_immutable_json(receipt_path, payload)
        return payload


def _build_receipt(
    *,
    config: BtcOkxDemoFaultDrillConfig,
    generated_at: datetime,
    decision: str,
    blockers: list[str],
    simulation_only: bool,
    orders_posted: int,
    pre_snapshot: Mapping[str, Any],
    post_snapshot: Mapping[str, Any],
    result: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    pre_summary = _snapshot_summary(pre_snapshot)
    post_summary = _snapshot_summary(post_snapshot)
    return {
        "schema_version": DEMO_FAULT_DRILL_SCHEMA_VERSION,
        "evidence_class": DEMO_FAULT_DRILL_EVIDENCE_CLASS,
        "generated_at_utc": _ensure_utc(generated_at).isoformat(),
        "source_head": config.source_head,
        "scenario": config.scenario,
        "run_id": config.run_id,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": _decimal_text(config.order_contracts),
        "scenario_order_contract_cap": (
            "0.03" if config.scenario == "partial_fill_disconnect" else "0.01"
        ),
        "continuous_order_contract_cap": "0.01",
        "max_notional_usdt": _decimal_text(config.max_notional_usdt),
        "dedicated_demo_account_confirmed": config.confirm_dedicated_demo_account,
        "execution_requested": config.execute_demo,
        "orders_posted": orders_posted,
        "observed_order_side_effects": _safe_json(
            _mapping(result.get("observed_order_side_effects"))
        ),
        "simulation_only": simulation_only,
        "fault_origin": str(result.get("fault_origin") or ""),
        "evidence_mode": str(result.get("evidence_mode") or ""),
        "process_id": int(result.get("process_id") or 0),
        "child_termination": _safe_json(
            _mapping(result.get("child_termination"))
        ),
        "pre_reconciliation_sha256": str(
            result.get("pre_reconciliation_sha256") or ""
        ),
        "post_reconciliation_sha256": str(
            result.get("post_reconciliation_sha256") or ""
        ),
        "pre_snapshot_sha256": _sha256(pre_summary),
        "post_snapshot_sha256": _sha256(post_summary),
        "pre_snapshot": pre_summary,
        "post_snapshot": post_summary,
        "clOrdId": str(result.get("clOrdId") or ""),
        "closeClOrdId": str(result.get("closeClOrdId") or ""),
        "algoClOrdId": str(result.get("algoClOrdId") or ""),
        "entry_order_id": str(result.get("entry_order_id") or ""),
        "close_order_id": str(result.get("close_order_id") or ""),
        "entry_fill_ids": _safe_json(result.get("entry_fill_ids") or []),
        "close_fill_ids": _safe_json(result.get("close_fill_ids") or []),
        "entry_fill_order_ids": _safe_json(
            result.get("entry_fill_order_ids") or []
        ),
        "close_fill_order_ids": _safe_json(
            result.get("close_fill_order_ids") or []
        ),
        "entry_fill_client_order_ids": _safe_json(
            result.get("entry_fill_client_order_ids") or []
        ),
        "close_fill_client_order_ids": _safe_json(
            result.get("close_fill_client_order_ids") or []
        ),
        "algo_id": str(result.get("algo_id") or ""),
        "algo_parent_cl_ord_id": str(
            result.get("algo_parent_cl_ord_id") or ""
        ),
        "entry_attempts": int(result.get("entry_attempts") or 0),
        "entry_retry_count": int(result.get("entry_retry_count") or 0),
        "entry_fill_contracts": str(result.get("entry_fill_contracts") or ""),
        "entry_order_filled_contracts": str(
            result.get("entry_order_filled_contracts") or ""
        ),
        "entry_fill_sum_contracts": str(
            result.get("entry_fill_sum_contracts") or ""
        ),
        "entry_position_contracts": str(
            result.get("entry_position_contracts") or ""
        ),
        "close_fill_contracts": str(
            result.get("close_fill_contracts") or ""
        ),
        "close_order_filled_contracts": str(
            result.get("close_order_filled_contracts") or ""
        ),
        "entry_order_type": str(result.get("entry_order_type") or ""),
        "requested_contracts": str(result.get("requested_contracts") or ""),
        "entry_fill_classification": str(
            result.get("entry_fill_classification") or ""
        ),
        "discrepancy_classification": str(
            result.get("discrepancy_classification") or ""
        ),
        "broker_truth_verified": result.get("broker_truth_verified") is True,
        "synthetic": (
            result.get("synthetic")
            if isinstance(result.get("synthetic"), bool)
            else None
        ),
        "fixture": (
            result.get("fixture")
            if isinstance(result.get("fixture"), bool)
            else None
        ),
        "simulation": (
            result.get("simulation")
            if isinstance(result.get("simulation"), bool)
            else None
        ),
        "real_exchange_observation": (
            result.get("real_exchange_observation")
            if isinstance(result.get("real_exchange_observation"), bool)
            else None
        ),
        "runtime_receipt_sha256": str(
            result.get("runtime_receipt_sha256") or ""
        ),
        "authoritative_receipt_sha256": str(
            result.get("authoritative_receipt_sha256") or ""
        ),
        "identity_namespace": str(result.get("identity_namespace") or ""),
        "authoritative_identity_projection": _safe_json(
            _mapping(result.get("authoritative_identity_projection"))
        ),
        "provenance": _safe_json(_mapping(result.get("provenance"))),
        "disconnect_observed": result.get("disconnect_observed") is True,
        "reconnect_bounded": result.get("reconnect_bounded") is True,
        "four_way_reconciliation": _safe_json(
            _mapping(result.get("four_way_reconciliation"))
        ),
        "operator_ack_required": result.get("operator_ack_required") is True,
        "operator_acknowledged": result.get("operator_acknowledged") is True,
        "recovery_state": str(result.get("recovery_state") or ""),
        "opening_allowed": result.get("opening_allowed") is True,
        "final_flat": result.get("final_flat") is True,
        "final_no_pending_orders": result.get("final_no_pending_orders") is True,
        "final_no_pending_algo_orders": result.get(
            "final_no_pending_algo_orders"
        )
        is True,
        "final_no_unresolved_intents": result.get(
            "final_no_unresolved_intents"
        )
        is True,
        "final_ledger_reconciled": result.get("final_ledger_reconciled") is True,
        "final_private_ws_reconciled": result.get(
            "final_private_ws_reconciled"
        )
        is True,
        "orders": post_summary.get("orders", []),
        "fills": post_summary.get("fills", []),
        "positions": post_summary.get("positions", []),
        "ledger_reconciliation": post_summary.get("ledger_reconciliation", {}),
        "fault_injection_timeline": _safe_json(timeline),
        "incident_recovery_outcome": {
            "close_post_attempted": result.get("close_post_attempted") is True,
            "submit_outcome_unknown": result.get("submit_outcome_unknown")
            is True,
            "cancel_post_attempted": result.get("cancel_post_attempted") is True,
            "cancel_outcome_unknown": result.get("cancel_outcome_unknown")
            is True,
            "retry_allowed": False,
            "no_order_or_cancel_post": result.get(
                "no_order_or_cancel_post"
            )
            is True,
            "private_ws_reconciled": result.get("private_ws_reconciled")
            is True,
            "ledger_reconciled": result.get("ledger_reconciled") is True,
            "incident_recovery_intent": _safe_json(
                _mapping(result.get("incident_recovery_intent"))
            ),
            "incident_algo_cancel_intent": _safe_json(
                _mapping(result.get("incident_algo_cancel_intent"))
            ),
            "cancel_receipt": _safe_json(
                _mapping(result.get("cancel_receipt"))
            ),
        },
        "decision": decision,
        "blockers": _dedupe(blockers),
        "official_semantics": dict(OKX_DOCS_REVIEW_METADATA),
        "promotion_eligible": False,
        "paper_promotion_allowed": False,
        "live_allowed": False,
        "credentials_redacted": True,
    }


def _snapshot_blockers(snapshot: Mapping[str, Any], *, phase: str) -> list[str]:
    blockers: list[str] = []
    runtime = _mapping(snapshot.get("runtime"))
    risk = _mapping(snapshot.get("risk_control"))
    private_ws = _mapping(snapshot.get("private_ws"))
    exchange = _mapping(snapshot.get("exchange"))
    ledger = _mapping(snapshot.get("ledger_reconciliation"))
    gross = sum(
        (abs(_decimal(row.get("contracts"))) for row in _rows(exchange.get("positions"))),
        Decimal("0"),
    )
    if gross != 0:
        blockers.append(f"fault_drill_{phase}_position_not_flat")
    if _rows(exchange.get("pending_orders")) or _rows(exchange.get("orders")):
        pending = [
            row
            for row in [*_rows(exchange.get("pending_orders")), *_rows(exchange.get("orders"))]
            if str(row.get("state") or row.get("status") or "")
            not in {"filled", "canceled", "cancelled", "terminal", "rejected"}
        ]
        if pending:
            blockers.append(f"fault_drill_{phase}_pending_orders_present")
    if _rows(exchange.get("pending_algo_orders")):
        blockers.append(
            f"fault_drill_{phase}_pending_algo_orders_present"
        )
    unresolved = [
        key
        for key, row in _mapping(risk.get("pending_order_intents")).items()
        if isinstance(row, Mapping) and str(row.get("status") or "") in _UNRESOLVED
    ]
    if unresolved:
        blockers.append(f"fault_drill_{phase}_unresolved_order_intent")
    if phase == "postflight":
        nonterminal = [
            str(key)
            for key, row in _mapping(risk.get("pending_order_intents")).items()
            if isinstance(row, Mapping)
            and str(row.get("status") or "") not in _TERMINAL_INTENT_STATUSES
        ]
        if nonterminal and not unresolved:
            blockers.append(
                "fault_drill_postflight_nonterminal_order_intent"
            )
        active_protection = _mapping(risk.get("active_protection"))
        if active_protection and str(active_protection.get("status") or "") not in {
            "canceled",
            "cancelled",
            "terminal",
        }:
            blockers.append("fault_drill_postflight_active_protection_present")
    if (
        ledger.get("status") != "reconciled"
        or ledger.get("current_state_exchange_snapshot_match") is not True
    ):
        blockers.append(f"fault_drill_{phase}_ledger_not_reconciled")
    if phase == "preflight" and not (
        runtime.get("active") is True
        and private_ws.get("connected") is True
        and private_ws.get("listener_alive") is True
        and private_ws.get("opening_allowed_after_reconciliation") is True
    ):
        blockers.append("fault_drill_preflight_private_ws_not_reconciled")
    return blockers


def _derive_observed_order_side_effects(
    *,
    pre_snapshot: Mapping[str, Any],
    post_snapshot: Mapping[str, Any],
    result: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind exchange deltas to IDs emitted by this receipt-owned runtime call."""

    bound_ids: list[str] = []

    def bind(value: Any) -> None:
        client_order_id = str(value or "")
        if client_order_id and client_order_id not in bound_ids:
            bound_ids.append(client_order_id)

    bind(result.get("clOrdId"))
    bind(result.get("closeClOrdId"))
    receipt_owned_events = {
        "risk_oms_opening_path_entered",
        "demo_order_post_returned",
        "post_response_lost_after_exchange_response",
    }
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or "") not in receipt_owned_events:
            continue
        details = _mapping(event.get("details"))
        bind(event.get("clOrdId") or details.get("clOrdId"))
        bind(event.get("closeClOrdId") or details.get("closeClOrdId"))

    def observed_ids(snapshot: Mapping[str, Any]) -> set[str]:
        exchange = _mapping(snapshot.get("exchange"))
        rows = [
            *_rows(exchange.get("orders")),
            *_rows(exchange.get("fills")),
        ]
        return {
            str(row.get("client_order_id") or row.get("clOrdId") or "")
            for row in rows
            if str(row.get("client_order_id") or row.get("clOrdId") or "")
        }

    new_ids = observed_ids(post_snapshot) - observed_ids(pre_snapshot)
    newly_observed_owned = [
        client_order_id
        for client_order_id in bound_ids
        if client_order_id in new_ids
    ]
    return {
        "bound_client_order_ids": bound_ids,
        "new_observed_client_order_ids": newly_observed_owned,
        "orders_posted": len(newly_observed_owned),
    }


def _failure_identity_projection(
    *,
    post_snapshot: Mapping[str, Any],
    opening_cl_ord_id: str,
    runtime_attestation: Mapping[str, Any],
) -> dict[str, Any]:
    """Retain durable opening/OCO identity on an orders_posted failure receipt."""

    if not opening_cl_ord_id:
        return {}
    exchange = _mapping(post_snapshot.get("exchange"))
    orders = _rows(exchange.get("orders") or post_snapshot.get("orders"))
    fills = _rows(exchange.get("fills") or post_snapshot.get("fills"))
    algos = _rows(
        exchange.get("pending_algo_orders")
        or post_snapshot.get("pending_algo_orders")
    )
    opening_orders = [
        row
        for row in orders
        if str(row.get("clOrdId") or row.get("client_order_id") or "")
        == opening_cl_ord_id
    ]
    opening_fills = [
        row
        for row in fills
        if str(row.get("clOrdId") or row.get("client_order_id") or "")
        == opening_cl_ord_id
    ]
    matching_algos = [
        row
        for row in algos
        if str(row.get("parentClOrdId") or row.get("parent_client_order_id") or opening_cl_ord_id)
        == opening_cl_ord_id
    ]
    result: dict[str, Any] = {
        "entry_order_id": str(
            opening_orders[0].get("order_id")
            or opening_orders[0].get("ordId")
            if len(opening_orders) == 1
            else ""
        ),
        "entry_fill_ids": [
            str(row.get("fill_id") or row.get("tradeId") or "")
            for row in opening_fills
            if str(row.get("fill_id") or row.get("tradeId") or "")
        ],
        "entry_fill_order_ids": [
            str(row.get("order_id") or row.get("ordId") or "")
            for row in opening_fills
            if str(row.get("order_id") or row.get("ordId") or "")
        ],
        "entry_fill_client_order_ids": [opening_cl_ord_id]
        if opening_fills
        else [],
    }
    if len(matching_algos) == 1:
        result.update(
            {
                "algoClOrdId": str(
                    matching_algos[0].get("algoClOrdId")
                    or matching_algos[0].get("algo_client_order_id")
                    or ""
                ),
                "algo_id": str(
                    matching_algos[0].get("algoId")
                    or matching_algos[0].get("algo_id")
                    or ""
                ),
                "algo_parent_cl_ord_id": opening_cl_ord_id,
            }
        )
    if runtime_attestation:
        projection = _mapping(runtime_attestation.get("authoritative_identity_projection"))
        result.update(
            {
                "identity_namespace": str(
                    runtime_attestation.get("identity_namespace")
                    or projection.get("identity_namespace")
                    or ""
                ),
                "authoritative_identity_projection": projection,
                "authoritative_receipt_sha256": str(
                    runtime_attestation.get("authoritative_receipt_sha256") or ""
                ),
                "provenance": {
                    **dict(runtime_attestation),
                    "source": "exchange_snapshot",
                },
            }
        )
    return result


@dataclass(frozen=True)
class BtcOkxDemoFailedReceiptBinding:
    """Immutable failed-receipt identity used only by one-shot recovery."""

    path: Path
    failed_receipt_sha256: str
    failed_receipt_source_head: str
    failed_receipt_scenario: str
    failed_receipt_run_id: str
    opening_cl_ord_id: str
    opening_order_id: str
    opening_fill_id: str
    algo_cl_ord_id: str
    algo_id: str
    expected_close_cl_ord_id: str
    recovery_mode: str = "held_position"
    flat_identity_sha256: str = ""
    # Canonical durable-runtime binding fields.  They are empty on the
    # compatibility/manual path above; the new path never accepts caller
    # supplied order/algo identities.
    runtime_root: Path | None = None
    runtime_root_sha256: str = ""
    runtime_run_id: str = ""
    runtime_state_sha256: str = ""
    runtime_events_sha256: str = ""
    runtime_last_event_hash: str = ""
    runtime_last_sequence: int = 0
    binding_path: Path | None = None
    binding_sha256: str = ""
    binding_current_head: str = ""
    account_identity: str = ""
    credential_identity: str = ""
    client_order_namespace: str = ""
    incident_source_head: str = ""
    recovery_code_head: str = ""
    ancestry_proof: dict[str, Any] = field(default_factory=dict)
    original_owner_marker_sha256: str = ""
    original_owner_marker_source_head: str = ""
    original_owner_marker_recovery_code_head: str = ""
    original_owner_marker_runtime_root_sha256: str = ""
    runtime_ledger_sha256: str = ""
    binding_schema_version: str = ""
    binding_source: str = ""

    @classmethod
    def load(
        cls,
        *,
        path: Path,
        expected_sha256: str,
        expected_opening_cl_ord_id: str = "",
        expected_algo_cl_ord_id: str = "",
        expected_algo_id: str = "",
        expected_close_cl_ord_id: str = "",
        runtime_root: Path | None = None,
        current_head: str = "",
        repo_root: Path | None = None,
        expected_incident_source_head: str = "",
        expected_recovery_code_head: str = "",
        binding_external_root: Path | None = None,
        expected_runtime_root_sha256: str = "",
        expected_runtime_state_sha256: str = "",
        expected_runtime_events_sha256: str = "",
        identity_archive_root: Path | None = None,
        worker_parent_emergency_receipt: Path | None = None,
        worker_parent_emergency_receipt_sha256: str = "",
    ) -> "BtcOkxDemoFailedReceiptBinding":
        if runtime_root is not None:
            if any(
                str(value or "").strip()
                for value in (
                    expected_opening_cl_ord_id,
                    expected_algo_cl_ord_id,
                    expected_algo_id,
                    expected_close_cl_ord_id,
                )
            ):
                raise FaultDrillReceiptError(
                    "fault_drill_recovery_binding_caller_identity_forbidden"
                )
            if repo_root is None:
                raise FaultDrillReceiptError(
                    "fault_drill_recovery_binding_repo_root_required"
                )
            return cls.load_canonical(
                path=path,
                expected_sha256=expected_sha256,
                runtime_root=runtime_root,
                current_head=current_head,
                repo_root=repo_root,
                expected_incident_source_head=expected_incident_source_head,
                expected_recovery_code_head=expected_recovery_code_head,
                binding_external_root=binding_external_root,
                expected_runtime_root_sha256=expected_runtime_root_sha256,
                expected_runtime_state_sha256=expected_runtime_state_sha256,
                expected_runtime_events_sha256=expected_runtime_events_sha256,
                identity_archive_root=identity_archive_root,
                worker_parent_emergency_receipt=worker_parent_emergency_receipt,
                worker_parent_emergency_receipt_sha256=(
                    worker_parent_emergency_receipt_sha256
                ),
            )
        if identity_archive_root is not None or worker_parent_emergency_receipt is not None or worker_parent_emergency_receipt_sha256:
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_identity_archive_canonical_only"
            )
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_file_missing"
            )
        raw = resolved.read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256 or ""))
            or actual_sha256 != expected_sha256
        ):
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_sha256_mismatch"
            )
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_json_invalid"
            ) from exc
        if not isinstance(payload, Mapping):
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_json_not_object"
            )
        exact_envelope = {
            "environment": "OKX Demo",
            "instrument_id": "BTC-USDT-SWAP",
            "margin_mode": "isolated",
            "leverage": "3",
            "order_contracts": "0.01",
        }
        mismatches = [
            name
            for name, expected in exact_envelope.items()
            if str(payload.get(name) or "") != expected
        ]
        if mismatches:
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_envelope_mismatch:"
                + ",".join(mismatches)
            )
        source_head = str(payload.get("source_head") or "")
        scenario = str(payload.get("scenario") or "")
        failed_run_id = str(payload.get("run_id") or "")
        decision = str(payload.get("decision") or "")
        if (
            payload.get("schema_version") != DEMO_FAULT_DRILL_SCHEMA_VERSION
            or not _HEAD_PATTERN.fullmatch(source_head)
            or scenario not in DEMO_FAULT_DRILL_SCENARIOS
            or not re.fullmatch(r"[A-Za-z0-9._-]{3,96}", failed_run_id)
            or payload.get("execution_requested") is not True
            or decision
            not in {
                "failed_postflight_frozen",
                "blocked_frozen_lifecycle_incomplete",
            }
        ):
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_not_recovery_eligible"
            )
        identity_values = {
            "opening_cl_ord_id": expected_opening_cl_ord_id,
            "algo_cl_ord_id": expected_algo_cl_ord_id,
            "algo_id": expected_algo_id,
            "expected_close_cl_ord_id": expected_close_cl_ord_id,
        }
        if any(
            not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(value or ""))
            for value in identity_values.values()
        ):
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_expected_identity_invalid"
            )
        post_snapshot = _mapping(payload.get("post_snapshot"))
        orders = _rows(post_snapshot.get("orders"))
        fills = _rows(post_snapshot.get("fills"))
        algos = _rows(post_snapshot.get("pending_algo_orders"))
        matching_orders = [
            row
            for row in orders
            if str(row.get("clOrdId") or row.get("client_order_id") or "")
            == expected_opening_cl_ord_id
            and str(row.get("state") or row.get("status") or "") == "filled"
        ]
        matching_fills = [
            row
            for row in fills
            if str(row.get("clOrdId") or row.get("client_order_id") or "")
            == expected_opening_cl_ord_id
            and _decimal(row.get("size") or row.get("fillSz"))
            == Decimal("0.01")
        ]
        matching_algos = [
            row
            for row in algos
            if str(row.get("algoClOrdId") or row.get("algo_client_order_id") or "")
            == expected_algo_cl_ord_id
            and str(row.get("algo_id") or row.get("algoId") or "")
            == expected_algo_id
            and str(row.get("state") or "") == "live"
        ]
        matching_close_orders = [
            row
            for row in orders
            if str(row.get("clOrdId") or row.get("client_order_id") or "")
            == expected_close_cl_ord_id
            and str(row.get("state") or row.get("status") or "") == "filled"
        ]
        matching_close_fills = [
            row
            for row in fills
            if str(row.get("clOrdId") or row.get("client_order_id") or "")
            == expected_close_cl_ord_id
            and _decimal(row.get("size") or row.get("fillSz"))
            == Decimal("0.01")
        ]
        post_positions = _rows(post_snapshot.get("positions"))
        post_pending_orders = _rows(post_snapshot.get("pending_orders"))
        post_pending_algos = _rows(post_snapshot.get("pending_algo_orders"))
        post_ledger = _mapping(post_snapshot.get("ledger_reconciliation"))
        flat_receipt = (
            bool(post_positions)
            and all(_decimal(row.get("contracts")) == 0 for row in post_positions)
            and not post_pending_orders
            and not post_pending_algos
            and post_ledger.get("status") == "reconciled"
            and post_ledger.get("current_state_exchange_snapshot_match") is True
            and len(matching_close_orders) == 1
            and len(matching_close_fills) == 1
        )
        if flat_receipt:
            expected_incident = _mapping(payload.get("incident_recovery"))
            identity_mismatches = [
                field
                for field, value in {
                    "opening_cl_ord_id": expected_opening_cl_ord_id,
                    "algo_cl_ord_id": expected_algo_cl_ord_id,
                    "algo_id": expected_algo_id,
                    "close_cl_ord_id": expected_close_cl_ord_id,
                }.items()
                if field in expected_incident
                and str(expected_incident.get(field) or "") != value
            ]
            if identity_mismatches:
                raise FaultDrillReceiptError(
                    "fault_drill_failed_receipt_flat_identity_mismatch:"
                    + ",".join(identity_mismatches)
                )
            return cls(
                path=resolved,
                failed_receipt_sha256=actual_sha256,
                failed_receipt_source_head=source_head,
                failed_receipt_scenario=scenario,
                failed_receipt_run_id=failed_run_id,
                opening_cl_ord_id=expected_opening_cl_ord_id,
                opening_order_id=str(matching_orders[0].get("order_id") or ""),
                opening_fill_id=str(matching_fills[0].get("fill_id") or ""),
                algo_cl_ord_id=expected_algo_cl_ord_id,
                algo_id=expected_algo_id,
                expected_close_cl_ord_id=expected_close_cl_ord_id,
                recovery_mode="already_flat",
                flat_identity_sha256=_flat_recovery_identity_sha256(
                    post_snapshot,
                    owned_client_order_ids=(
                        expected_opening_cl_ord_id,
                        expected_close_cl_ord_id,
                    ),
                ),
            )
        if (
            len(matching_orders) != 1
            or len(matching_fills) != 1
            or len(matching_algos) != 1
            or not str(matching_orders[0].get("order_id") or "")
            or not str(matching_fills[0].get("fill_id") or "")
        ):
            raise FaultDrillReceiptError(
                "fault_drill_failed_receipt_exact_identity_missing"
            )
        return cls(
            path=resolved,
            failed_receipt_sha256=actual_sha256,
            failed_receipt_source_head=source_head,
            failed_receipt_scenario=scenario,
            failed_receipt_run_id=failed_run_id,
            opening_cl_ord_id=expected_opening_cl_ord_id,
            opening_order_id=str(matching_orders[0]["order_id"]),
            opening_fill_id=str(matching_fills[0]["fill_id"]),
            algo_cl_ord_id=expected_algo_cl_ord_id,
            algo_id=expected_algo_id,
            expected_close_cl_ord_id=expected_close_cl_ord_id,
        )

    @classmethod
    def load_canonical(
        cls,
        *,
        path: Path,
        expected_sha256: str,
        runtime_root: Path,
        repo_root: Path,
        expected_incident_source_head: str,
        expected_recovery_code_head: str,
        current_head: str = "",
        binding_external_root: Path | None = None,
        expected_runtime_root_sha256: str = "",
        expected_runtime_state_sha256: str = "",
        expected_runtime_events_sha256: str = "",
        identity_archive_root: Path | None = None,
        worker_parent_emergency_receipt: Path | None = None,
        worker_parent_emergency_receipt_sha256: str = "",
    ) -> "BtcOkxDemoFailedReceiptBinding":
        """Build an immutable binding from the failed receipt and runtime root.

        This admission is intentionally offline.  It validates the receipt,
        checkpoint/event chain, durable opening/OCO evidence, and current-run
        namespace before publishing one unique binding document.  It accepts
        no caller-supplied order, fill, algo, or close identity.
        """

        return _load_canonical_recovery_binding(
            path=path,
            expected_sha256=expected_sha256,
            runtime_root=runtime_root,
            repo_root=repo_root,
            expected_incident_source_head=expected_incident_source_head,
            expected_recovery_code_head=expected_recovery_code_head,
            current_head=current_head,
            binding_external_root=binding_external_root,
            expected_runtime_root_sha256=expected_runtime_root_sha256,
            expected_runtime_state_sha256=expected_runtime_state_sha256,
            expected_runtime_events_sha256=expected_runtime_events_sha256,
            identity_archive_root=identity_archive_root,
            worker_parent_emergency_receipt=worker_parent_emergency_receipt,
            worker_parent_emergency_receipt_sha256=(
                worker_parent_emergency_receipt_sha256
            ),
        )

    @classmethod
    def load_flat_hosted_exit_bundle(
        cls,
        *,
        failed_receipt_path: Path,
        failed_receipt_sha256: str,
        fresh_truth_path: Path,
        fresh_truth_sha256: str,
        fresh_truth_payload_sha256: str,
        fill_diagnostic_path: Path,
        fill_diagnostic_sha256: str,
        fill_diagnostic_payload_sha256: str,
        exit_order_path: Path,
        exit_order_sha256: str,
        exit_order_payload_sha256: str,
        binding_external_root: Path,
        repo_root: Path,
    ) -> "BtcOkxDemoFailedReceiptBinding":
        """Publish the one immutable, flat hosted-OCO identity bundle.

        This is deliberately separate from the canonical durable-runtime v2
        admission.  It has no runtime-root input and never accepts caller
        supplied order/algo identities: all of those values are derived from
        the four immutable source receipts before a binding directory exists.
        """

        return _load_flat_hosted_exit_binding(
            failed_receipt_path=failed_receipt_path,
            failed_receipt_sha256=failed_receipt_sha256,
            fresh_truth_path=fresh_truth_path,
            fresh_truth_sha256=fresh_truth_sha256,
            fresh_truth_payload_sha256=fresh_truth_payload_sha256,
            fill_diagnostic_path=fill_diagnostic_path,
            fill_diagnostic_sha256=fill_diagnostic_sha256,
            fill_diagnostic_payload_sha256=fill_diagnostic_payload_sha256,
            exit_order_path=exit_order_path,
            exit_order_sha256=exit_order_sha256,
            exit_order_payload_sha256=exit_order_payload_sha256,
            binding_external_root=binding_external_root,
            repo_root=repo_root,
        )

    def runtime_authorization(self, *, runtime_source_head: str) -> dict[str, str]:
        authorization = {
            "authorization_ticket": (
                "BTC-OKX-DEMO-INCIDENT-RECOVERY-AND-RECEIPT-05"
            ),
            "runtime_source_head": runtime_source_head,
            "failed_receipt_sha256": self.failed_receipt_sha256,
            "failed_receipt_source_head": self.failed_receipt_source_head,
            "failed_receipt_scenario": self.failed_receipt_scenario,
            "failed_receipt_run_id": self.failed_receipt_run_id,
            "recovery_mode": self.recovery_mode,
            "flat_identity_sha256": self.flat_identity_sha256,
            "opening_cl_ord_id": self.opening_cl_ord_id,
            "opening_order_id": self.opening_order_id,
            "opening_fill_id": self.opening_fill_id,
            "algo_cl_ord_id": self.algo_cl_ord_id,
            "algo_id": self.algo_id,
            "expected_close_cl_ord_id": self.expected_close_cl_ord_id,
        }
        if self.binding_path is not None:
            authorization.update(
                {
                    "recovery_binding_schema_version": (
                        self.binding_schema_version
                        or _RECOVERY_BINDING_SCHEMA_VERSION
                    ),
                    "recovery_binding_source": (
                        self.binding_source
                        or "immutable_demo_incident_recovery"
                    ),
                    "recovery_binding_path": str(self.binding_path),
                    "recovery_binding_sha256": self.binding_sha256,
                    "recovery_runtime_root": str(self.runtime_root or ""),
                    "recovery_runtime_root_sha256": self.runtime_root_sha256,
                    "recovery_runtime_run_id": self.runtime_run_id,
                    "recovery_runtime_state_sha256": self.runtime_state_sha256,
                    "recovery_runtime_events_sha256": self.runtime_events_sha256,
                    "recovery_runtime_last_event_hash": self.runtime_last_event_hash,
                    "recovery_runtime_last_sequence": str(self.runtime_last_sequence),
                    "recovery_binding_current_head": self.binding_current_head,
                    "recovery_account_identity": self.account_identity,
                    "recovery_credential_identity": self.credential_identity,
                    "recovery_client_order_namespace": self.client_order_namespace,
                    "incident_source_head": self.incident_source_head,
                    "recovery_code_head": self.recovery_code_head,
                    "recovery_original_owner_marker_sha256": (
                        self.original_owner_marker_sha256
                    ),
                    "recovery_original_owner_marker_source_head": (
                        self.original_owner_marker_source_head
                    ),
                    "recovery_original_owner_marker_recovery_code_head": (
                        self.original_owner_marker_recovery_code_head
                    ),
                    "recovery_original_owner_marker_runtime_root_sha256": (
                        self.original_owner_marker_runtime_root_sha256
                    ),
                    "recovery_runtime_ledger_sha256": self.runtime_ledger_sha256,
                    "recovery_ancestry_proof": json.dumps(
                        self.ancestry_proof,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        return authorization


def _load_flat_hosted_exit_binding(
    *,
    failed_receipt_path: Path,
    failed_receipt_sha256: str,
    fresh_truth_path: Path,
    fresh_truth_sha256: str,
    fresh_truth_payload_sha256: str,
    fill_diagnostic_path: Path,
    fill_diagnostic_sha256: str,
    fill_diagnostic_payload_sha256: str,
    exit_order_path: Path,
    exit_order_sha256: str,
    exit_order_payload_sha256: str,
    binding_external_root: Path,
    repo_root: Path,
) -> BtcOkxDemoFailedReceiptBinding:
    """Offline publisher for the fixed, already-flat hosted-exit bundle.

    Unlike v2, this intentionally has no durable runtime-root admission.  Its
    source is four already-existing immutable receipts; every exchange identity
    below is extracted from those receipts, never from CLI scalar arguments.
    """

    expected_hashes = (
        failed_receipt_sha256,
        fresh_truth_sha256,
        fresh_truth_payload_sha256,
        fill_diagnostic_sha256,
        fill_diagnostic_payload_sha256,
        exit_order_sha256,
        exit_order_payload_sha256,
    )
    if any(_SHA256_PATTERN.fullmatch(str(value or "")) is None for value in expected_hashes):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_hashes_required")
    resolved_repo = Path(repo_root).resolve()
    try:
        recovery_head = _repo_head(resolved_repo)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_recovery_head_unavailable") from exc

    def read_receipt(
        source_path: Path,
        expected_file_sha: str,
        expected_payload_sha: str = "",
    ) -> tuple[Path, bytes, Mapping[str, Any]]:
        path = Path(source_path).resolve()
        if not path.is_file():
            raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_receipt_missing")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_file_sha:
            raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_receipt_sha256_mismatch")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_receipt_json_invalid") from exc
        if not isinstance(payload, Mapping):
            raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_receipt_json_invalid")
        if expected_payload_sha and payload.get("payload_sha256") != expected_payload_sha:
            raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_payload_sha256_mismatch")
        return path, raw, payload

    failed_path, failed_raw, failed = read_receipt(
        failed_receipt_path, failed_receipt_sha256
    )
    fresh_path, fresh_raw, fresh = read_receipt(
        fresh_truth_path, fresh_truth_sha256, fresh_truth_payload_sha256
    )
    diagnostic_path, diagnostic_raw, diagnostic = read_receipt(
        fill_diagnostic_path,
        fill_diagnostic_sha256,
        fill_diagnostic_payload_sha256,
    )
    order_path, order_raw, order = read_receipt(
        exit_order_path, exit_order_sha256, exit_order_payload_sha256
    )

    envelope = {"environment": "OKX Demo", "instrument_id": "BTC-USDT-SWAP"}
    if any(str(doc.get(key) or "") != value for doc in (fresh, diagnostic, order) for key, value in envelope.items()):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_envelope_mismatch")
    if (
        failed.get("schema_version") != DEMO_FAULT_DRILL_SCHEMA_VERSION
        or failed.get("scenario") != "post_response_loss"
        or failed.get("orders_posted") != 1
        or str(failed.get("environment") or "") != "OKX Demo"
        or str(failed.get("instrument_id") or "") != "BTC-USDT-SWAP"
        or str(failed.get("margin_mode") or "") != "isolated"
        or str(failed.get("leverage") or "") != "3"
        or str(failed.get("order_contracts") or "") != "0.01"
        or failed.get("credentials_redacted") is not True
    ):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_failed_receipt_invalid")
    fresh_status = str(fresh.get("status") or "")
    fresh_blockers = fresh.get("blockers")
    fresh_readonly_status_valid = (
        fresh_status in {"blocked_fail_closed", "completed", "ok"}
        or (
            fresh_status == "blocked"
            and fresh_blockers == ["private_ws_reconciliation_not_current"]
        )
    )
    if (
        fresh.get("schema_version") != "btc_okx_demo_fresh_broker_truth_receipt_v2"
        or diagnostic.get("schema_version") != "btc_okx_demo_fill_identity_diagnostic_v1"
        or order.get("schema_version") != "btc_okx_demo_unknown_fill_exact_order_receipt_v1"
        or not fresh_readonly_status_valid
        or any(doc.get("status") not in {"blocked_fail_closed", "completed", "ok"} for doc in (diagnostic, order))
        or any(doc.get(field) not in {0, False, None} for doc in (fresh, diagnostic, order) for field in ("exchange_order_post_count", "exchange_cancel_post_count", "exchange_transfer_post_count", "exchange_withdraw_post_count", "physical_non_get_count", "non_get_count"))
    ):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_readonly_receipt_invalid")

    incident_head = str(failed.get("source_head") or "")
    evidence_heads = {str(doc.get("main_head") or "") for doc in (fresh, diagnostic, order)}
    if not _HEAD_PATTERN.fullmatch(incident_head) or len(evidence_heads) != 1 or not all(_HEAD_PATTERN.fullmatch(head) for head in evidence_heads):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_head_invalid")
    try:
        proof_heads = (incident_head, *tuple(evidence_heads))
        merge_bases: dict[str, str] = {}
        for source_head in proof_heads:
            result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", source_head, recovery_head],
                cwd=resolved_repo,
                capture_output=True,
                text=True,
            )
            merge_base = subprocess.run(
                ["git", "merge-base", source_head, recovery_head],
                cwd=resolved_repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if result.returncode != 0 or not _HEAD_PATTERN.fullmatch(merge_base):
                raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_ancestry_invalid")
            merge_bases[source_head] = merge_base
    except (OSError, subprocess.SubprocessError) as exc:
        if isinstance(exc, FaultDrillReceiptError):
            raise
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_ancestry_unavailable") from exc
    ancestry_proof = {
        "method": "git merge-base and git merge-base --is-ancestor",
        "incident_source_head": incident_head,
        "evidence_source_head": next(iter(evidence_heads)),
        "recovery_code_head": recovery_head,
        "merge_bases": merge_bases,
        "sources_are_ancestors": True,
    }

    expected_entry = {
        "clOrdId": "btcDP20a8d1650001",
        "ordId": "3816659792351170560",
        "fillId": "4322812521",
    }
    expected_oco = {
        "algoClOrdId": "btcDP20a8d1650001A",
        "algoId": "3816659794069377024",
    }
    post = _mapping(failed.get("post_snapshot"))
    failed_orders = _rows(post.get("orders"))
    failed_fills = _rows(post.get("fills"))
    entry_order = [
        row for row in failed_orders
        if str(row.get("clOrdId") or "") == expected_entry["clOrdId"]
        and str(row.get("order_id") or "") == expected_entry["ordId"]
        and str(row.get("state") or "") == "filled"
    ]
    entry_fill = [
        row for row in failed_fills
        if str(row.get("clOrdId") or "") == expected_entry["clOrdId"]
        and str(row.get("order_id") or "") == expected_entry["ordId"]
        and str(row.get("fill_id") or "") == expected_entry["fillId"]
        and _decimal(row.get("size")) == Decimal("0.01")
    ]
    failed_oco = [
        row for row in _rows(post.get("pending_algo_orders"))
        if str(row.get("algoClOrdId") or "") == expected_oco["algoClOrdId"]
        and str(row.get("algo_id") or "") == expected_oco["algoId"]
        and str(row.get("state") or "") == "live"
    ]
    known = _mapping(_mapping(fresh.get("rest")).get("known_identity"))
    fresh_entry_orders = _rows(known.get("entry_orders"))
    fresh_entry_fills = _rows(known.get("entry_fills"))
    fresh_oco_detail = _rows(known.get("exact_oco_detail"))
    fresh_oco_history = _rows(known.get("exact_oco_history"))
    if not (
        len(entry_order) == len(entry_fill) == len(failed_oco) == 1
        and str(known.get("entry_cl_ord_id") or "") == expected_entry["clOrdId"]
        and str(known.get("entry_ord_id") or "") == expected_entry["ordId"]
        and str(known.get("oco_algo_cl_ord_id") or "") == expected_oco["algoClOrdId"]
        and str(known.get("oco_algo_id") or "") == expected_oco["algoId"]
        and len([row for row in fresh_entry_orders if str(row.get("clOrdId") or "") == expected_entry["clOrdId"] and str(row.get("ordId") or "") == expected_entry["ordId"] and str(row.get("side") or "") == "buy" and str(row.get("posSide") or "") == "long" and str(row.get("state") or "") == "filled" and _decimal(row.get("sz")) == Decimal("0.01") and _decimal(row.get("accFillSz")) == Decimal("0.01")]) == 1
        and len([row for row in fresh_entry_fills if str(row.get("clOrdId") or "") == expected_entry["clOrdId"] and str(row.get("ordId") or "") == expected_entry["ordId"] and str(row.get("side") or "") == "buy" and str(row.get("posSide") or "") == "long" and _decimal(row.get("fillSz")) == Decimal("0.01")]) == 1
        and all(len([row for row in source if str(row.get("algoClOrdId") or "") == expected_oco["algoClOrdId"] and str(row.get("algoId") or "") == expected_oco["algoId"] and str(row.get("ordType") or "") == "oco" and str(row.get("state") or "") == "effective" and str(row.get("reduceOnly") or "") == "true" and str(row.get("side") or "") == "sell" and str(row.get("posSide") or "") == "long" and _decimal(row.get("sz")) == Decimal("0.01")]) == 1 for source in (fresh_oco_detail, fresh_oco_history))
    ):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_entry_oco_identity_invalid")

    exit_order = _mapping(order.get("order"))
    exit_fill_rows = _rows(diagnostic.get("fills"))
    exit_client_order_id = str(exit_order.get("clOrdId") or "")
    exit_order_id = str(exit_order.get("ordId") or "")
    exit_time = str(exit_order.get("uTime") or "")
    matching_exit_fills = [
        row for row in exit_fill_rows
        if str(row.get("clOrdId") or "") == exit_client_order_id
        and str(row.get("ordId") or "") == exit_order_id
        and str(row.get("instId") or "") == "BTC-USDT-SWAP"
        and str(row.get("side") or "") == "sell"
        and str(row.get("posSide") or "") == "long"
        and _decimal(row.get("fillSz")) == Decimal("0.01")
        and str(row.get("ts") or "") == exit_time
        and str(row.get("fillId") or "") == ""
    ]
    if not (
        re.fullmatch(r"O[0-9]{10,}", exit_client_order_id or "")
        and re.fullmatch(r"[0-9]{10,}", exit_order_id or "")
        and str(exit_order.get("algoClOrdId") or "") == expected_oco["algoClOrdId"]
        and str(exit_order.get("algoId") or "") == expected_oco["algoId"]
        and str(exit_order.get("state") or "") == "filled"
        and str(exit_order.get("ordType") or "") == "market"
        and str(exit_order.get("reduceOnly") or "") == "true"
        and str(exit_order.get("side") or "") == "sell"
        and str(exit_order.get("posSide") or "") == "long"
        and _decimal(exit_order.get("sz")) == Decimal("0.01")
        and _decimal(exit_order.get("accFillSz")) == Decimal("0.01")
        and str(_mapping(order.get("known_oco")).get("algo_cl_ord_id") or "") == expected_oco["algoClOrdId"]
        and str(_mapping(order.get("known_oco")).get("algo_id") or "") == expected_oco["algoId"]
        and len(matching_exit_fills) == 1
    ):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_terminal_identity_invalid")
    try:
        entry_timestamp = int(str(fresh_entry_fills[0].get("ts") or ""))
        if int(exit_time) < entry_timestamp:
            raise ValueError
    except (ValueError, IndexError):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_time_link_invalid")

    rest = _mapping(fresh.get("rest"))
    positions = _rows(rest.get("positions"))
    account = _mapping(rest.get("account"))
    leverage_rows = _rows(rest.get("leverage"))
    funding_bills = _rows(_mapping(rest.get("funding_bills")).get("bills"))
    if not (
        len(positions) == 1
        and str(positions[0].get("instId") or "") == "BTC-USDT-SWAP"
        and str(positions[0].get("mgnMode") or "") == "isolated"
        and str(positions[0].get("posSide") or "") == "long"
        and _decimal(positions[0].get("pos")) == 0
        and _decimal(_mapping(rest.get("ordinary_pending")).get("count")) == 0
        and _decimal(_mapping(rest.get("conditional_pending")).get("count")) == 0
        and _decimal(_mapping(rest.get("oco_pending")).get("count")) == 0
        and str(account.get("position_mode") or "") == "long_short_mode"
        and account.get("withdraw_permission_present") is False
        and len([row for row in leverage_rows if str(row.get("instId") or "") == "BTC-USDT-SWAP" and str(row.get("mgnMode") or "") == "isolated" and str(row.get("lever") or "") == "3" and str(row.get("posSide") or "") in {"long", "short"}]) == 2
        and bool(funding_bills)
    ):
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_fresh_state_invalid")

    root = Path(binding_external_root).resolve()
    try:
        root.relative_to(resolved_repo)
    except ValueError:
        pass
    else:
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_output_root_repo_local")
    if not root.is_absolute() or (root / ".git").exists():
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_output_root_invalid")
    source_hashes = {
        "failed_incident": failed_receipt_sha256,
        "fresh_truth": fresh_truth_sha256,
        "fill_diagnostic": fill_diagnostic_sha256,
        "exit_order": exit_order_sha256,
    }
    bundle_seed = _sha256({
        "schema_version": _FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION,
        "heads": ancestry_proof,
        "source_hashes": source_hashes,
        "entry": expected_entry,
        "oco": expected_oco,
        "exit": {"client_order_id": exit_client_order_id, "order_id": exit_order_id, "timestamp_ms": exit_time},
    })
    target = root / recovery_head / "flat_hosted_exit" / bundle_seed
    if target.exists():
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_binding_already_exists")

    document = {
        "schema_version": _FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION,
        "binding_type": _FLAT_HOSTED_EXIT_BINDING_SOURCE,
        "binding_source": _FLAT_HOSTED_EXIT_BINDING_SOURCE,
        "incident_source_head": incident_head,
        "recovery_code_head": recovery_head,
        "ancestry_proof": ancestry_proof,
        "failed_receipt": {"source_file": "sources/failed_incident.json", "sha256": failed_receipt_sha256, "scenario": "post_response_loss", "orders_posted": 1},
        "fresh_truth": {"source_file": "sources/fresh_truth.json", "sha256": fresh_truth_sha256, "payload_sha256": fresh_truth_payload_sha256},
        "fill_diagnostic": {"source_file": "sources/fill_diagnostic.json", "sha256": fill_diagnostic_sha256, "payload_sha256": fill_diagnostic_payload_sha256},
        "exit_order": {"source_file": "sources/exit_order.json", "sha256": exit_order_sha256, "payload_sha256": exit_order_payload_sha256},
        "identity": {
            "opening_cl_ord_id": expected_entry["clOrdId"], "opening_order_id": expected_entry["ordId"], "opening_fill_id": expected_entry["fillId"],
            "algo_cl_ord_id": expected_oco["algoClOrdId"], "algo_id": expected_oco["algoId"],
            "expected_close_cl_ord_id": exit_client_order_id, "expected_close_order_id": exit_order_id,
            "expected_close_fill_id": "", "close_fill_id_available": False, "exit_timestamp_ms": exit_time,
        },
        "safety": {"identity_only": True, "opening_allowed": False, "paper_promotion_allowed": False, "promotion_eligible": False, "live_allowed": False, "private_allowed": False, "order_allowed": False, "transfer_allowed": False, "withdraw_allowed": False},
    }
    document["content_sha256"] = _sha256(document)
    binding_encoded = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    binding_sha256 = hashlib.sha256(binding_encoded).hexdigest()
    completed = {"schema_version": "immutable_binding_completed_v1", "binding_sha256": binding_sha256, "content_sha256": document["content_sha256"], "source_hashes": source_hashes}
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".flat-hosted-exit-", dir=target.parent))
        sources = temporary / "sources"
        sources.mkdir()
        for destination, raw in (("failed_incident.json", failed_raw), ("fresh_truth.json", fresh_raw), ("fill_diagnostic.json", diagnostic_raw), ("exit_order.json", order_raw)):
            (sources / destination).write_bytes(raw)
        (temporary / "binding.json").write_bytes(binding_encoded)
        (temporary / "COMPLETED").write_text(json.dumps(completed, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        if target.exists():
            raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_binding_already_exists")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    binding_path = target / "binding.json"
    if hashlib.sha256(binding_path.read_bytes()).hexdigest() != binding_sha256:
        raise FaultDrillReceiptError("fault_drill_flat_hosted_exit_binding_write_invalid")
    return BtcOkxDemoFailedReceiptBinding(
        path=failed_path,
        failed_receipt_sha256=failed_receipt_sha256,
        failed_receipt_source_head=incident_head,
        failed_receipt_scenario="post_response_loss",
        failed_receipt_run_id=str(failed.get("run_id") or ""),
        opening_cl_ord_id=expected_entry["clOrdId"],
        opening_order_id=expected_entry["ordId"],
        opening_fill_id=expected_entry["fillId"],
        algo_cl_ord_id=expected_oco["algoClOrdId"],
        algo_id=expected_oco["algoId"],
        expected_close_cl_ord_id=exit_client_order_id,
        recovery_mode="already_flat",
        flat_identity_sha256=document["content_sha256"],
        binding_path=binding_path,
        binding_sha256=binding_sha256,
        binding_current_head=recovery_head,
        incident_source_head=incident_head,
        recovery_code_head=recovery_head,
        ancestry_proof=ancestry_proof,
        binding_schema_version=_FLAT_HOSTED_EXIT_BINDING_SCHEMA_VERSION,
        binding_source=_FLAT_HOSTED_EXIT_BINDING_SOURCE,
    )


@dataclass(frozen=True)
class _ImmutableIdentityArchiveAnchor:
    account_identity: str
    credential_identity: str
    archive_id: str
    archive_root: Path
    manifest_sha256: str
    verification_sha256: str
    completed_sha256: str
    owner_marker_sha256: str
    archive_current_head: str
    source_archive_head: str

    def projection(self) -> dict[str, str]:
        """Only identity provenance; never archive run, namespace, or triples."""

        return {
            "source": "immutable_owned_id_restore_archive",
            "archive_id": self.archive_id,
            "archive_root": str(self.archive_root),
            "manifest_sha256": self.manifest_sha256,
            "verification_sha256": self.verification_sha256,
            "completed_sha256": self.completed_sha256,
            "owner_marker_sha256": self.owner_marker_sha256,
            "archive_current_head": self.archive_current_head,
            "source_archive_head": self.source_archive_head,
        }


def _identity_archive_json(path: Path, code: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultDrillReceiptError(code) from exc
    if not isinstance(payload, Mapping):
        raise FaultDrillReceiptError(code)
    return payload


def _identity_archive_canonical_sha256(value: Any) -> str:
    """Match the immutable archive publisher's UTF-8 manifest contract."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _identity_archive_safe_child(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_identity_archive_file_invalid")
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_file_invalid"
        ) from exc
    if not resolved.is_file():
        raise FaultDrillReceiptError("fault_drill_recovery_binding_identity_archive_file_invalid")
    return resolved


def _identity_archive_is_ancestor(
    repo_root: Path,
    ancestor: str,
    descendant: str,
) -> bool:
    if not _HEAD_PATTERN.fullmatch(ancestor) or not _HEAD_PATTERN.fullmatch(descendant):
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_ancestry_unavailable"
        ) from exc
    return result.returncode == 0


def _load_identity_archive_anchor(
    archive_root: Path,
    *,
    repo_root: Path,
    recovery_head: str,
) -> _ImmutableIdentityArchiveAnchor:
    """Strictly validate an identity-only owned-ID archive before any runtime.

    This deliberately reads only execution_identity.  Its selected triples,
    namespace, and run are not an ownership source for the failed incident.
    """

    try:
        root = Path(archive_root).resolve(strict=True)
    except OSError as exc:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_missing"
        ) from exc
    if not root.is_dir() or (root / ".git").exists():
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_invalid"
        )
    try:
        root.relative_to(repo_root.resolve())
    except ValueError:
        pass
    else:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_root_invalid"
        )
    manifest_path = root / "manifest.json"
    verification_path = root / "verification.json"
    completed_path = root / "COMPLETED.json"
    manifest = _identity_archive_json(
        manifest_path,
        "fault_drill_recovery_binding_identity_archive_manifest_invalid",
    )
    verification = _identity_archive_json(
        verification_path,
        "fault_drill_recovery_binding_identity_archive_verification_invalid",
    )
    completed = _identity_archive_json(
        completed_path,
        "fault_drill_recovery_binding_identity_archive_completed_invalid",
    )
    manifest_raw = manifest_path.read_bytes()
    verification_raw = verification_path.read_bytes()
    completed_raw = completed_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    verification_sha = hashlib.sha256(verification_raw).hexdigest()
    completed_sha = hashlib.sha256(completed_raw).hexdigest()
    manifest_body = dict(manifest)
    supplied_manifest_hash = str(manifest_body.pop("manifest_hash", ""))
    if (
        manifest.get("schema_version") != _IDENTITY_ARCHIVE_SCHEMA_VERSION
        or verification.get("schema_version") != _IDENTITY_ARCHIVE_SCHEMA_VERSION
        or completed.get("schema_version")
        != _IDENTITY_ARCHIVE_COMPLETION_SCHEMA_VERSION
        or not _IDENTITY_PATTERN.fullmatch(str(manifest.get("archive_id") or ""))
        or manifest.get("archive_id") != verification.get("archive_id")
        or manifest.get("archive_id") != completed.get("archive_id")
        or manifest.get("immutable") is not True
        or manifest.get("unique_directory_no_overwrite") is not True
        or manifest.get("identity_only") is not True
        or verification.get("identity_only") is not True
        or manifest.get("status") != "verified_fail_closed"
        or verification.get("status") != "verified_fail_closed"
        or verification.get("decision") != "owned_id_restore_admission_only"
        or completed.get("immutable_after_write") is not True
        or supplied_manifest_hash
        != _identity_archive_canonical_sha256(manifest_body)
        or manifest.get("verification_sha256") != verification_sha
        or completed.get("manifest_sha256") != manifest_sha
        or completed.get("verification_sha256") != verification_sha
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_invalid"
        )
    if any(
        manifest.get(field) is not False
        for field in (
            "opening_allowed",
            "order_capability_restored",
            "position_restored",
            "paper_unlock",
            "promotion_unlock",
            "live_unlock",
        )
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_safety_invalid"
        )
    safety = _mapping(manifest.get("safety"))
    verification_safety = _mapping(verification.get("safety"))
    required_false_safety = {
        "live_allowed",
        "network_used",
        "order_endpoint_allowed",
        "paper_allowed",
        "private_endpoint_allowed",
        "promotion_allowed",
        "real_order_submitted",
        "secret_read",
        "transfer_allowed",
        "withdraw_allowed",
    }
    if any(
        safety.get(key) is not False or verification_safety.get(key) is not False
        for key in required_false_safety
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_safety_invalid"
        )
    archive_head = str(manifest.get("current_head") or "")
    source_head = str(verification.get("source_head") or "")
    source_archive_head = str(manifest.get("source_archive_head") or "")
    if (
        not _HEAD_PATTERN.fullmatch(archive_head)
        or source_head != archive_head
        or verification.get("current_head") != archive_head
        or verification.get("source_archive_head") != source_archive_head
        or not _HEAD_PATTERN.fullmatch(source_archive_head)
        or not _identity_archive_is_ancestor(repo_root, source_archive_head, archive_head)
        or not _identity_archive_is_ancestor(repo_root, archive_head, recovery_head)
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_head_invalid"
        )
    owner = _mapping(manifest.get("owner_marker"))
    owner_path_text = str(owner.get("path") or "")
    owner_sha = str(owner.get("sha256") or "")
    owner_identity = str(owner.get("repository_owner_identity") or "")
    if (
        owner.get("immutable_archives_only") is not True
        or not _SHA256_PATTERN.fullmatch(owner_sha)
        or not _SHA256_PATTERN.fullmatch(owner_identity)
        or verification.get("owner_marker_sha256") != owner_sha
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_owner_invalid"
        )
    try:
        owner_path = Path(owner_path_text).resolve(strict=True)
        owner_raw = owner_path.read_bytes()
    except OSError as exc:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_owner_invalid"
        ) from exc
    owner_payload = _identity_archive_json(
        owner_path,
        "fault_drill_recovery_binding_identity_archive_owner_invalid",
    )
    if (
        hashlib.sha256(owner_raw).hexdigest() != owner_sha
        or owner_payload.get("schema_version")
        != "quant_btc_external_evidence_owner_v1"
        or owner_payload.get("immutable_archives_only") is not True
        or owner_payload.get("repository_owner_identity") != owner_identity
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_owner_invalid"
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_files_invalid"
        )
    file_kinds: set[str] = set()
    file_paths: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_identity_archive_files_invalid"
            )
        relative = item.get("archive_relative_path")
        kind = str(item.get("kind") or "")
        expected_sha = str(item.get("sha256") or "")
        expected_size = item.get("size_bytes")
        if (
            kind in file_kinds
            or not isinstance(relative, str)
            or relative in file_paths
            or not _SHA256_PATTERN.fullmatch(expected_sha)
            or not isinstance(expected_size, int)
            or expected_size < 0
        ):
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_identity_archive_files_invalid"
            )
        file_path = _identity_archive_safe_child(root, relative)
        raw = file_path.read_bytes()
        if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_sha:
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_identity_archive_file_hash_invalid"
            )
        file_kinds.add(kind)
        file_paths.add(relative)
    if (
        not _IDENTITY_ARCHIVE_REQUIRED_FILE_KINDS.issubset(file_kinds)
        or "verification.json" not in file_paths
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_files_invalid"
        )
    manifest_identity = _mapping(manifest.get("execution_identity"))
    verification_identity = _mapping(verification.get("execution_identity"))
    account_identity = str(manifest_identity.get("account_identity") or "")
    credential_identity = str(manifest_identity.get("credential_identity") or "")
    if (
        manifest_identity != verification_identity
        or not _SHA256_PATTERN.fullmatch(account_identity)
        or not _IDENTITY_PATTERN.fullmatch(credential_identity)
        or any(
            secret in credential_identity.lower()
            for secret in ("secret", "pass", "token", "key")
        )
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_identity_archive_identity_invalid"
        )
    return _ImmutableIdentityArchiveAnchor(
        account_identity=account_identity,
        credential_identity=credential_identity,
        archive_id=str(manifest.get("archive_id")),
        archive_root=root,
        manifest_sha256=manifest_sha,
        verification_sha256=verification_sha,
        completed_sha256=completed_sha,
        owner_marker_sha256=owner_sha,
        archive_current_head=archive_head,
        source_archive_head=source_archive_head,
    )


def _bounded_recovery_ancestry_probe(
    repo_root: Path,
    ancestor: str,
    descendant: str,
) -> dict[str, str] | None:
    """Prove a recovery Git edge within a bounded, fail-closed window."""

    if not _HEAD_PATTERN.fullmatch(ancestor) or not _HEAD_PATTERN.fullmatch(
        descendant
    ):
        return None
    try:
        merge_base_result = subprocess.run(
            ["git", "merge-base", ancestor, descendant],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=_RECOVERY_GIT_PROBE_TIMEOUT_SECONDS,
        )
        ancestry_result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=_RECOVERY_GIT_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_ancestry_unavailable"
        ) from exc
    merge_base = merge_base_result.stdout.strip()
    if ancestry_result.returncode != 0 or not _HEAD_PATTERN.fullmatch(merge_base):
        return None
    return {"merge_base": merge_base}


def _load_canonical_recovery_binding(
    *,
    path: Path,
    expected_sha256: str,
    runtime_root: Path,
    repo_root: Path,
    expected_incident_source_head: str,
    expected_recovery_code_head: str,
    current_head: str,
    binding_external_root: Path | None,
    expected_runtime_root_sha256: str,
    expected_runtime_state_sha256: str,
    expected_runtime_events_sha256: str,
    identity_archive_root: Path | None,
    worker_parent_emergency_receipt: Path | None,
    worker_parent_emergency_receipt_sha256: str,
) -> BtcOkxDemoFailedReceiptBinding:
    """Offline validator/publisher for the durable incident recovery binding."""

    if any(
        _SHA256_PATTERN.fullmatch(str(value or "")) is None
        for value in (
            expected_runtime_root_sha256,
            expected_runtime_state_sha256,
            expected_runtime_events_sha256,
        )
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_hashes_required"
        )

    incident_head = str(expected_incident_source_head or "")
    expected_recovery_head = str(expected_recovery_code_head or "")
    if not _HEAD_PATTERN.fullmatch(incident_head) or not _HEAD_PATTERN.fullmatch(
        expected_recovery_head
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_heads_required"
        )
    try:
        observed_recovery_head = _repo_head(Path(repo_root).resolve())
    except (OSError, subprocess.SubprocessError) as exc:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_recovery_head_unavailable"
        ) from exc
    if observed_recovery_head != expected_recovery_head:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_recovery_head_mismatch"
        )
    if current_head and current_head != observed_recovery_head:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_current_head_mismatch"
        )
    recovery_ancestry = _bounded_recovery_ancestry_probe(
        Path(repo_root).resolve(), incident_head, observed_recovery_head
    )
    if recovery_ancestry is None:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_incident_not_recovery_ancestor"
        )
    ancestry_proof = {
        "method": "git merge-base and git merge-base --is-ancestor",
        "incident_source_head": incident_head,
        "recovery_code_head": observed_recovery_head,
        "merge_base": recovery_ancestry["merge_base"],
        "incident_is_ancestor": True,
        "recovery_is_ancestor_of_incident": incident_head == observed_recovery_head,
    }

    resolved_receipt = Path(path).resolve()
    resolved_runtime = Path(runtime_root).resolve()
    head = observed_recovery_head
    if not resolved_receipt.is_file():
        raise FaultDrillReceiptError("fault_drill_failed_receipt_file_missing")
    if not resolved_runtime.is_dir() or (resolved_runtime / ".git").exists():
        raise FaultDrillReceiptError("fault_drill_recovery_binding_runtime_root_invalid")

    receipt_raw = resolved_receipt.read_bytes()
    receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
    if not _SHA256_PATTERN.fullmatch(str(expected_sha256 or "")) or receipt_sha != expected_sha256:
        raise FaultDrillReceiptError("fault_drill_failed_receipt_sha256_mismatch")
    try:
        receipt = json.loads(receipt_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultDrillReceiptError("fault_drill_failed_receipt_json_invalid") from exc
    if not isinstance(receipt, Mapping):
        raise FaultDrillReceiptError("fault_drill_failed_receipt_json_not_object")
    envelope = {
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
    }
    if any(str(receipt.get(name) or "") != expected for name, expected in envelope.items()):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_receipt_envelope_mismatch")
    scenario = str(receipt.get("scenario") or "")
    failed_run_id = str(receipt.get("run_id") or "")
    receipt_provenance = _mapping(receipt.get("provenance"))
    supplied_runtime_run_id = receipt_provenance.get("runtime_run_id")
    if (
        supplied_runtime_run_id is not None
        and supplied_runtime_run_id != ""
        and not isinstance(supplied_runtime_run_id, str)
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_receipt_runtime_run_invalid"
        )
    failed_runtime_run_id = (
        supplied_runtime_run_id if isinstance(supplied_runtime_run_id, str) else ""
    )
    receipt_head = str(receipt.get("source_head") or "")
    worker_parent_emergency_enabled = worker_parent_emergency_receipt is not None
    if worker_parent_emergency_enabled != bool(
        str(worker_parent_emergency_receipt_sha256 or "")
    ):
        raise FaultDrillReceiptError(
            "fault_drill_worker_parent_emergency_arguments_required"
        )
    normal_receipt_eligible = (
        receipt.get("schema_version") == DEMO_FAULT_DRILL_SCHEMA_VERSION
        and _HEAD_PATTERN.fullmatch(receipt_head) is not None
        and receipt_head == incident_head
        and scenario in DEMO_FAULT_DRILL_SCENARIOS
        and re.fullmatch(r"[A-Za-z0-9._-]{3,96}", failed_run_id) is not None
        and receipt.get("execution_requested") is True
        and receipt.get("orders_posted") == 1
        and str(receipt.get("decision") or "")
        in {"failed_postflight_frozen", "blocked_frozen_lifecycle_incomplete"}
    )
    if not normal_receipt_eligible and not worker_parent_emergency_enabled:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_receipt_not_eligible")
    if worker_parent_emergency_enabled:
        if normal_receipt_eligible or not (
            receipt.get("schema_version") == DEMO_FAULT_DRILL_SCHEMA_VERSION
            and _HEAD_PATTERN.fullmatch(receipt_head)
            and receipt_head == incident_head
            and scenario == "worker_kill"
            and re.fullmatch(r"[A-Za-z0-9._-]{3,96}", failed_run_id)
            and receipt.get("execution_requested") is True
            and receipt.get("orders_posted") == 0
            and str(receipt.get("decision") or "")
            == "startup_failed_fail_closed"
            and not any(
                str(receipt.get(field) or "")
                for field in ("clOrdId", "algoClOrdId", "algo_id", "closeClOrdId")
            )
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_outer_invalid"
            )
    if receipt.get("credentials_redacted") is not True or any(
        receipt.get(field) is True
        for field in ("opening_allowed", "promotion_eligible", "paper_promotion_allowed", "live_allowed")
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_receipt_safety_invalid")
    if failed_runtime_run_id and re.fullmatch(
        r"[A-Za-z0-9._-]{3,96}", failed_runtime_run_id
    ) is None:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_receipt_runtime_run_invalid"
        )

    opening_clord_id = ""
    opening_order_id = ""
    opening_fill_id = ""
    algo_clord_id = ""
    algo_id = ""
    if not worker_parent_emergency_enabled:
        post_snapshot = _mapping(receipt.get("post_snapshot"))
        opening_clord_id = str(receipt.get("clOrdId") or "")
        if not _PARTIAL_CLIENT_ID_PATTERN.fullmatch(opening_clord_id):
            raise FaultDrillReceiptError("fault_drill_recovery_binding_opening_clordid_missing")
        orders = _rows(post_snapshot.get("orders"))
        fills = _rows(post_snapshot.get("fills"))
        opening_orders = [
            row for row in orders
            if str(row.get("clOrdId") or row.get("client_order_id") or "") == opening_clord_id
            and str(row.get("state") or row.get("status") or "") == "filled"
        ]
        opening_fills = [
            row for row in fills
            if str(row.get("clOrdId") or row.get("client_order_id") or "") == opening_clord_id
            and _decimal(row.get("size") or row.get("fillSz")) == Decimal("0.01")
        ]
        if len(opening_orders) != 1 or len(opening_fills) != 1:
            raise FaultDrillReceiptError("fault_drill_recovery_binding_opening_exchange_identity_invalid")
        opening_order_id = str(opening_orders[0].get("order_id") or opening_orders[0].get("ordId") or "")
        opening_fill_id = str(opening_fills[0].get("fill_id") or opening_fills[0].get("tradeId") or "")
        if not opening_order_id or not opening_fill_id:
            raise FaultDrillReceiptError("fault_drill_recovery_binding_opening_exchange_identity_missing")
        positions = _rows(post_snapshot.get("positions"))
        if not (
            len(positions) == 1
            and str(positions[0].get("instrument_id") or positions[0].get("instId") or "")
            == "BTC-USDT-SWAP"
            and str(positions[0].get("position_side") or positions[0].get("posSide") or "")
            == "long"
            and _decimal(positions[0].get("contracts") or positions[0].get("pos"))
            == Decimal("0.01")
        ):
            raise FaultDrillReceiptError("fault_drill_recovery_binding_position_identity_invalid")
        algo_rows = _rows(post_snapshot.get("pending_algo_orders"))
        algo_rows = [
            row for row in algo_rows
            if str(row.get("parent_client_order_id") or row.get("parentClOrdId") or opening_clord_id) == opening_clord_id
            and str(row.get("state") or "") == "live"
        ]
        algo_clord_id = str(receipt.get("algoClOrdId") or "")
        algo_id = str(receipt.get("algo_id") or "")
        if not algo_clord_id or not algo_id:
            if len(algo_rows) == 1:
                algo_clord_id = str(algo_rows[0].get("algoClOrdId") or algo_rows[0].get("algo_client_order_id") or "")
                algo_id = str(algo_rows[0].get("algo_id") or algo_rows[0].get("algoId") or "")
        if not algo_clord_id or not algo_id or len(algo_rows) != 1:
            raise FaultDrillReceiptError("fault_drill_recovery_binding_oco_identity_missing")

    lock_path = resolved_runtime / ".btc_okx_demo_fault_drill_writer.lock"
    state_path = resolved_runtime / "state.json"
    events_path = resolved_runtime / "events.jsonl"
    if not lock_path.is_file() or not state_path.is_file() or not events_path.is_file():
        raise FaultDrillReceiptError("fault_drill_recovery_binding_runtime_root_files_missing")
    try:
        lock_raw = lock_path.read_bytes()
        lock_payload = json.loads(lock_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_owner_marker_invalid") from exc
    expected_root_sha = _sha256(str(resolved_runtime))
    marker_recovery_head = str(lock_payload.get("recovery_code_head") or "") if isinstance(lock_payload, Mapping) else ""
    marker_is_same_head_legacy = (
        incident_head == head and marker_recovery_head in {"", head}
    )
    marker_is_cross_head_incident = (
        incident_head != head and marker_recovery_head == incident_head
    )
    marker_is_cross_head_multihop = False
    marker_ancestry_proof: dict[str, Any] = {}
    if (
        isinstance(lock_payload, Mapping)
        and lock_payload.get("source_head") == incident_head
        and incident_head != head
        and marker_recovery_head != incident_head
        and _HEAD_PATTERN.fullmatch(marker_recovery_head)
    ):
        try:
            incident_to_marker = _bounded_recovery_ancestry_probe(
                Path(repo_root).resolve(), incident_head, marker_recovery_head
            )
            marker_to_recovery = _bounded_recovery_ancestry_probe(
                Path(repo_root).resolve(), marker_recovery_head, head
            )
        except FaultDrillReceiptError:
            incident_to_marker = None
            marker_to_recovery = None
        if incident_to_marker is not None and marker_to_recovery is not None:
            marker_is_cross_head_multihop = True
            marker_ancestry_proof = {
                "method": "git merge-base and git merge-base --is-ancestor",
                "incident_source_head": incident_head,
                "marker_recovery_code_head": marker_recovery_head,
                "recovery_code_head": head,
                "incident_to_marker_merge_base": incident_to_marker["merge_base"],
                "marker_to_recovery_merge_base": marker_to_recovery["merge_base"],
                "incident_is_marker_ancestor": True,
                "marker_is_recovery_ancestor": True,
            }
    if (
        not isinstance(lock_payload, Mapping)
        or not str(lock_payload.get("nonce") or "")
        or not isinstance(lock_payload.get("process_id"), int)
        or lock_payload.get("process_id") <= 0
        or lock_payload.get("source_head") != incident_head
        or not (
            marker_is_same_head_legacy
            or marker_is_cross_head_incident
            or marker_is_cross_head_multihop
        )
        or lock_payload.get("runtime_root_sha256") != expected_root_sha
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_owner_marker_mismatch")
    if marker_ancestry_proof:
        ancestry_proof["owner_marker_multihop"] = marker_ancestry_proof
    worker_parent_emergency_document: dict[str, Any] | None = None
    worker_parent_emergency_sha = ""
    if worker_parent_emergency_enabled:
        resolved_emergency = Path(worker_parent_emergency_receipt).resolve()
        if not resolved_emergency.is_file():
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_file_missing"
            )
        emergency_raw = resolved_emergency.read_bytes()
        worker_parent_emergency_sha = hashlib.sha256(emergency_raw).hexdigest()
        if (
            _SHA256_PATTERN.fullmatch(
                str(worker_parent_emergency_receipt_sha256 or "")
            ) is None
            or worker_parent_emergency_sha
            != worker_parent_emergency_receipt_sha256
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_sha256_mismatch"
            )
        try:
            emergency_payload = json.loads(emergency_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_json_invalid"
            ) from exc
        if (
            isinstance(emergency_payload, Mapping)
            and emergency_payload.get("run_id") != failed_run_id
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_outer_invalid"
            )
        child = _mapping(
            emergency_payload.get("child")
            if isinstance(emergency_payload, Mapping)
            else None
        )
        if not (
            isinstance(emergency_payload, Mapping)
            and emergency_payload.get("schema_version")
            == "btc_okx_demo_worker_parent_emergency_v1"
            and emergency_payload.get("source_head") == incident_head
            and emergency_payload.get("scenario") == "worker_kill"
            and emergency_payload.get("run_id") == failed_run_id
            and emergency_payload.get("decision")
            == "blocked_fail_closed_worker_supervision_required"
            and emergency_payload.get("disposition")
            == (
                "parent_waiting_on_exact_child_handle_no_kill_without_"
                "query_first_identity_and_protection_proof"
            )
            and emergency_payload.get("failure_code")
            == "worker_parent_marker_wait_failed"
            and emergency_payload.get("failure_stage") == "marker_wait"
            and emergency_payload.get("exact_child_handle_owned") is True
            and emergency_payload.get("credentials_redacted") is True
            and emergency_payload.get("paper_allowed") is False
            and emergency_payload.get("live_allowed") is False
            and emergency_payload.get("promotion_eligible") is False
            and emergency_payload.get("orders_retried") == 0
            and child.get("process_id") == lock_payload.get("process_id")
            and child.get("worker_nonce") == lock_payload.get("nonce")
            and str(child.get("process_create_time") or "")
            == str(lock_payload.get("process_create_time") or "")
            and isinstance(child.get("process_id"), int)
            and child.get("process_id") > 0
            and re.fullmatch(r"[0-9a-f]{32}", str(child.get("worker_nonce") or ""))
            is not None
            and re.fullmatch(r"[0-9]{8,32}", str(child.get("process_create_time") or ""))
            is not None
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_owner_mismatch"
            )
        worker_parent_emergency_document = {
            "path": str(resolved_emergency),
            "sha256": worker_parent_emergency_sha,
            "schema_version": emergency_payload["schema_version"],
            "run_id": failed_run_id,
            "failure_code": emergency_payload["failure_code"],
            "failure_stage": emergency_payload["failure_stage"],
            "child": {
                "process_id": child["process_id"],
                "worker_nonce": child["worker_nonce"],
                "process_create_time": str(child["process_create_time"]),
            },
        }
    state_raw = state_path.read_bytes()
    events_raw = events_path.read_bytes()
    state_sha = hashlib.sha256(state_raw).hexdigest()
    events_sha = hashlib.sha256(events_raw).hexdigest()
    if expected_runtime_root_sha256 and expected_root_sha != expected_runtime_root_sha256:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_runtime_root_sha256_mismatch")
    if expected_runtime_state_sha256 and state_sha != expected_runtime_state_sha256:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_state_sha256_mismatch")
    if expected_runtime_events_sha256 and events_sha != expected_runtime_events_sha256:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_events_sha256_mismatch")
    recovered = BTCRuntimeStore(resolved_runtime).recover()
    if recovered.blockers or recovered.truncated_tail or not recovered.events or not recovered.state:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_runtime_chain_invalid")
    state = _mapping(recovered.state)
    runtime_source_events = _validate_runtime_source_head_chain(
        state=state,
        events=recovered.events,
        incident_head=incident_head,
        recovery_head=head,
        repo_root=Path(repo_root).resolve(),
    )
    runtime = _mapping(state.get("runtime"))
    runtime_run_id = str(runtime.get("run_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,96}", runtime_run_id):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_runtime_run_invalid")
    event_run_ids = [str(event.get("run_id") or "") for event in recovered.events]
    expected_runtime_run_id = (
        runtime_run_id
        if worker_parent_emergency_enabled
        else failed_runtime_run_id or failed_run_id
    )
    if runtime_run_id != expected_runtime_run_id:
        # Older single-run receipts did not carry the later provenance field.
        # Keep that closed compatibility path, but never use it to select a
        # suffix from a mixed runtime root.
        if failed_runtime_run_id or any(
            event_run_id != runtime_run_id for event_run_id in event_run_ids
        ):
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_runtime_receipt_run_mismatch"
            )
    try:
        current_run_start = event_run_ids.index(runtime_run_id)
    except ValueError as exc:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_receipt_run_mismatch"
        ) from exc
    historical_run_ids = event_run_ids[:current_run_start]
    if any(
        event_run_id
        and re.fullmatch(r"[A-Za-z0-9._-]{3,96}", event_run_id) is None
        for event_run_id in historical_run_ids
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_multiple_runtime_runs")
    current_run_events = tuple(recovered.events[current_run_start:])
    if (
        not current_run_events
        or any(
            str(event.get("run_id") or "") != runtime_run_id
            for event in current_run_events
        )
        or int(current_run_events[-1].get("sequence") or -1)
        != recovered.last_sequence
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_multiple_runtime_runs")
    if not any(
        str(event.get("run_id") or "") == runtime_run_id
        and event_source_head == incident_head
        for event, event_source_head in runtime_source_events
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_runtime_source_mismatch")
    risk = _mapping(state.get("risk_control"))
    if worker_parent_emergency_enabled:
        opening_intents = []
        opening_lifecycles = []
        non_opening_order_clients: set[str] = set()
        degraded_events = []
        frozen_events = []
        for event in current_run_events:
            payload = _mapping(event.get("payload"))
            event_type = str(event.get("event_type") or "")
            if event_type == "order_intent_persisted_before_post":
                client_order_id = str(payload.get("client_order_id") or "")
                if (
                    payload.get("action") == "open_long"
                    and payload.get("retry_without_query_allowed") is False
                    and _PARTIAL_CLIENT_ID_PATTERN.fullmatch(client_order_id)
                ):
                    opening_intents.append((client_order_id, payload))
                elif client_order_id:
                    non_opening_order_clients.add(client_order_id)
            elif event_type == "order_lifecycle":
                oms = _mapping(payload.get("oms"))
                client_order_id = str(oms.get("client_order_id") or "")
                if client_order_id:
                    if (
                        payload.get("exchange_state") == "filled"
                        and _mapping(payload.get("order_plan")).get("action")
                        == "open_long"
                    ):
                        opening_lifecycles.append((client_order_id, payload))
                    else:
                        non_opening_order_clients.add(client_order_id)
            elif event_type == "position_safety_degraded":
                if (
                    payload.get("opening_allowed") is False
                    and payload.get("risk_reducing_only") is True
                    and str(payload.get("error") or "")
                ):
                    degraded_events.append(payload)
            elif event_type == "fault_drill_frozen":
                if (
                    payload.get("opening_allowed") is False
                    and payload.get("blind_order_append_allowed") is False
                    and str(payload.get("reason") or "")
                ):
                    frozen_events.append(payload)
        if (
            len(opening_intents) != 1
            or len(opening_lifecycles) != 1
            or non_opening_order_clients
            or len(degraded_events) != 1
            or len(frozen_events) != 1
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_identity_ambiguous"
            )
        opening_clord_id, opening_intent = opening_intents[0]
        lifecycle_client_id, opening_lifecycle = opening_lifecycles[0]
        opening_plan = _mapping(opening_lifecycle.get("order_plan"))
        opening_fills = _rows(opening_lifecycle.get("fills"))
        if (
            lifecycle_client_id != opening_clord_id
            or opening_intent.get("client_order_id") != opening_clord_id
            or opening_plan.get("client_order_id") != opening_clord_id
            or opening_plan.get("risk_reducing_only") is not False
            or opening_plan.get("position_side") != "long"
            or opening_plan.get("side") != "buy"
            or _decimal(opening_plan.get("contracts")) != Decimal("0.01")
            or len(opening_fills) != 1
            or str(opening_fills[0].get("client_order_id") or "")
            != opening_clord_id
            or _decimal(opening_fills[0].get("size")) != Decimal("0.01")
            or opening_fills[0].get("position_side") != "long"
            or opening_fills[0].get("side") != "buy"
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_identity_ambiguous"
            )
        opening_order_id = str(opening_lifecycle.get("exchange_order_id") or "")
        opening_fill_id = str(opening_fills[0].get("fill_id") or "")
        algo_clord_id = str(
            _mapping(opening_plan.get("attached_protection")).get(
                "attachAlgoClOrdId"
            )
            or ""
        )
        pending_algos = _rows(
            _mapping(state.get("exchange")).get("pending_algo_orders")
        )
        matching_algos = [
            row
            for row in pending_algos
            if str(
                row.get("algo_client_order_id") or row.get("algoClOrdId") or ""
            )
            == algo_clord_id
            and str(row.get("state") or "") == "live"
            and str(row.get("order_type") or row.get("ordType") or "") == "oco"
            and str(row.get("instrument_id") or row.get("instId") or "")
            == "BTC-USDT-SWAP"
            and str(row.get("position_side") or row.get("posSide") or "") == "long"
            and _decimal(row.get("size") or row.get("sz")) == Decimal("0.01")
        ]
        if (
            not opening_order_id
            or not opening_fill_id
            or not _PARTIAL_CLIENT_ID_PATTERN.fullmatch(algo_clord_id)
            or len(pending_algos) != 1
            or len(matching_algos) != 1
            or not str(matching_algos[0].get("algo_id") or matching_algos[0].get("algoId") or "")
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_identity_ambiguous"
            )
        pending_algo = matching_algos[0]
        pending_parent = str(
            pending_algo.get("parent_client_order_id")
            or pending_algo.get("parentClOrdId")
            or ""
        )
        algo_id = str(
            pending_algo.get("algo_id")
            or pending_algo.get("algoId")
            or ""
        )
        owned_algos = _mapping(risk.get("owned_attached_algos"))
        owned_matches = [
            _mapping(value)
            for value in owned_algos.values()
            if _mapping(value).get("algo_client_order_id") == algo_clord_id
        ]
        if not (
            len(owned_matches) == 1
            and (not pending_parent or pending_parent == opening_clord_id)
            and owned_matches[0].get("parent_client_order_id") == opening_clord_id
            and owned_matches[0].get("instrument_id") == "BTC-USDT-SWAP"
            and owned_matches[0].get("opening_intent") is True
            and owned_matches[0].get("status") == "submit_pending"
            and str(owned_matches[0].get("algo_id") or "") in {"", algo_id}
        ):
            raise FaultDrillReceiptError(
                "fault_drill_worker_parent_emergency_identity_ambiguous"
            )
    namespace = f"btcDP{runtime_run_id[:8]}"
    if not opening_clord_id.startswith(namespace) or not algo_clord_id.startswith(namespace):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_namespace_mismatch")
    try:
        order_sequence = int(runtime.get("order_sequence") or 0)
    except (TypeError, ValueError):
        order_sequence = -1
    if order_sequence < 0 or order_sequence >= 9999:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_order_sequence_invalid")
    expected_close_clord_id = f"{namespace}{order_sequence + 1:04d}"

    pending = _mapping(risk.get("pending_order_intents"))
    opening = _mapping(pending.get(opening_clord_id))
    if not (
        opening.get("persisted_before_post") is True
        and opening.get("client_order_id") == opening_clord_id
        and opening.get("exchange_order_id") == opening_order_id
        and opening.get("exchange_state") == "filled"
        and opening.get("risk_reducing_only") is False
        and _mapping(opening.get("order")).get("clOrdId") == opening_clord_id
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_durable_opening_invalid")
    lifecycle_events = []
    ledger_events = []
    for event in current_run_events:
        payload = _mapping(event.get("payload"))
        if event.get("event_type") == "order_lifecycle":
            oms = _mapping(payload.get("oms"))
            if oms.get("client_order_id") == opening_clord_id:
                lifecycle_events.append(payload)
        elif event.get("event_type") == "ledger_uow_committed":
            order_rows = _rows(_mapping(payload.get("order_ledger")).get("orders"))
            fill_rows = _rows(payload.get("fill_ledger"))
            if any(str(row.get("client_order_id") or "") == opening_clord_id for row in order_rows) or any(str(row.get("client_order_id") or "") == opening_clord_id for row in fill_rows):
                ledger_events.append(payload)
    if len(lifecycle_events) != 1 or len(ledger_events) < 1:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_durable_lifecycle_missing")
    lifecycle = lifecycle_events[0]
    lifecycle_order_id = str(lifecycle.get("exchange_order_id") or "")
    lifecycle_fills = _rows(lifecycle.get("fills"))
    if lifecycle_order_id != opening_order_id or not any(str(row.get("fill_id") or "") == opening_fill_id for row in lifecycle_fills):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_lifecycle_identity_mismatch")
    ledger_match = False
    for ledger in ledger_events:
        order_rows = _rows(_mapping(ledger.get("order_ledger")).get("orders"))
        fill_rows = _rows(ledger.get("fill_ledger"))
        if (
            len([row for row in order_rows if str(row.get("client_order_id") or "") == opening_clord_id]) == 1
            and len([row for row in fill_rows if str(row.get("client_order_id") or "") == opening_clord_id]) == 1
            and str(next(row for row in order_rows if str(row.get("client_order_id") or "") == opening_clord_id).get("order_id") or "") == opening_order_id
            and str(next(row for row in fill_rows if str(row.get("client_order_id") or "") == opening_clord_id).get("order_id") or "") == opening_order_id
            and str(next(row for row in fill_rows if str(row.get("client_order_id") or "") == opening_clord_id).get("fill_id") or "") == opening_fill_id
        ):
            ledger_match = True
    if not ledger_match:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_ledger_identity_mismatch")
    runtime_ledger_sha256 = _sha256(
        [
            _mapping(event.get("payload"))
            for event in current_run_events
            if event.get("event_type") == "ledger_uow_committed"
        ]
    )

    owned_algos = _mapping(risk.get("owned_attached_algos"))
    owned = _mapping(owned_algos.get(algo_clord_id))
    durable_owned_valid = (
        owned.get("algo_client_order_id") == algo_clord_id
        and owned.get("parent_client_order_id") == opening_clord_id
        and owned.get("instrument_id") == "BTC-USDT-SWAP"
        and owned.get("opening_intent") is True
    )
    if worker_parent_emergency_enabled:
        durable_owned_valid = durable_owned_valid and (
            owned.get("status") == "submit_pending"
            and str(owned.get("algo_id") or "") in {"", algo_id}
        )
    elif owned.get("algo_id") not in {None, "", algo_id}:
        durable_owned_valid = False
    if not durable_owned_valid:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_durable_oco_invalid")
    restore_identity = _mapping(risk.get("owned_id_restore"))
    state_account_identity = str(restore_identity.get("account_identity") or "")
    state_credential_identity = str(
        restore_identity.get("credential_identity") or ""
    )
    state_identity_present = bool(
        state_account_identity or state_credential_identity
    )
    state_identity_valid = (
        _SHA256_PATTERN.fullmatch(state_account_identity) is not None
        and _IDENTITY_PATTERN.fullmatch(state_credential_identity) is not None
        and not any(
            secret in state_credential_identity.lower()
            for secret in ("secret", "pass", "token", "key")
        )
    )
    archive_anchor: _ImmutableIdentityArchiveAnchor | None = None
    if identity_archive_root is not None:
        archive_anchor = _load_identity_archive_anchor(
            identity_archive_root,
            repo_root=Path(repo_root).resolve(),
            recovery_head=head,
        )
        if state_identity_present and (
            not state_identity_valid
            or state_account_identity != archive_anchor.account_identity
            or state_credential_identity != archive_anchor.credential_identity
        ):
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_identity_archive_identity_mismatch"
            )
    if state_identity_present:
        if not state_identity_valid:
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_identity_missing"
            )
        account_identity = state_account_identity
        credential_identity = state_credential_identity
    elif archive_anchor is not None:
        account_identity = archive_anchor.account_identity
        credential_identity = archive_anchor.credential_identity
    else:
        raise FaultDrillReceiptError("fault_drill_recovery_binding_identity_missing")
    exchange = _mapping(state.get("exchange"))
    account = _mapping(exchange.get("account"))
    if (
        str(state.get("environment") or "") != "OKX Demo"
        or str(state.get("instrument_id") or "") != "BTC-USDT-SWAP"
        or str(account.get("position_mode") or "") != "long_short_mode"
        or account.get("withdraw_permission_present") is True
        or _rows(exchange.get("pending_orders"))
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_runtime_envelope_invalid")
    durable_positions = _rows(exchange.get("positions"))
    if not durable_positions or not (
        len(durable_positions) == 1
        and str(durable_positions[0].get("instrument_id") or "") == "BTC-USDT-SWAP"
        and str(durable_positions[0].get("position_side") or "") == "long"
        and _decimal(durable_positions[0].get("contracts")) == Decimal("0.01")
        and str(durable_positions[0].get("margin_mode") or "") == "isolated"
        and _decimal(durable_positions[0].get("leverage")) == Decimal("3")
    ):
        raise FaultDrillReceiptError("fault_drill_recovery_binding_durable_position_invalid")

    binding_root = Path(binding_external_root).resolve() if binding_external_root is not None else resolved_receipt.parent / "recovery_bindings"
    if not binding_root.is_absolute() or (binding_root / ".git").exists():
        raise FaultDrillReceiptError("fault_drill_recovery_binding_output_root_invalid")
    binding_path = binding_root / head / scenario / f"{receipt_sha}-{expected_root_sha}.json"
    document = {
        "schema_version": _RECOVERY_BINDING_SCHEMA_VERSION,
        "binding_type": "immutable_demo_incident_recovery",
        "source_head": incident_head,
        "incident_source_head": incident_head,
        "recovery_code_head": head,
        "runtime_source_head": head,
        "ancestry_proof": ancestry_proof,
        "failed_receipt": {
            "path": str(resolved_receipt),
            "sha256": receipt_sha,
            "source_head": receipt_head,
            "scenario": scenario,
            "run_id": failed_run_id,
            "runtime_run_id": runtime_run_id,
            "orders_posted": int(receipt.get("orders_posted") or 0),
        },
        "runtime_root": {
            "path": str(resolved_runtime),
            "sha256": expected_root_sha,
            "source_head": incident_head,
            "recovery_code_head": head,
            "run_id": runtime_run_id,
            "state_sha256": state_sha,
            "events_sha256": events_sha,
            "ledger_sha256": runtime_ledger_sha256,
            "last_event_hash": recovered.last_event_hash,
            "last_sequence": recovered.last_sequence,
            "current_run_event_scope": {
                "first_sequence": current_run_events[0].get("sequence"),
                "last_sequence": current_run_events[-1].get("sequence"),
                "historical_prefix_event_count": current_run_start,
            },
        },
        "owner_marker": {
            "sha256": hashlib.sha256(lock_raw).hexdigest(),
            "source_head": str(lock_payload.get("source_head") or ""),
            "recovery_code_head": marker_recovery_head,
            "runtime_root_sha256": str(
                lock_payload.get("runtime_root_sha256") or ""
            ),
        },
        "identity": {
            "account_identity": account_identity,
            "credential_identity": credential_identity,
            "client_order_namespace": namespace,
            "opening_cl_ord_id": opening_clord_id,
            "opening_order_id": opening_order_id,
            "opening_fill_id": opening_fill_id,
            "algo_cl_ord_id": algo_clord_id,
            "algo_id": algo_id,
            "expected_close_cl_ord_id": expected_close_clord_id,
        },
        **(
            {"worker_parent_emergency": worker_parent_emergency_document}
            if worker_parent_emergency_document is not None
            else {}
        ),
        **(
            {"identity_archive_anchor": archive_anchor.projection()}
            if archive_anchor is not None
            else {}
        ),
        "durable_attestation": {
            "opening_intent_persisted_before_post": True,
            "opening_order_lifecycle": True,
            "opening_ledger_uow": True,
            "oco_identity_persisted": True,
            "runtime_chain_verified": True,
            "worker_parent_emergency": worker_parent_emergency_enabled,
        },
        "safety": {
            "opening_allowed": False,
            "cancel_only": True,
            "paper_promotion_allowed": False,
            "promotion_eligible": False,
            "live_allowed": False,
            "credentials_redacted": True,
        },
    }
    document["content_sha256"] = _sha256(document)
    _write_immutable_json(binding_path, document)
    binding_sha = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    return BtcOkxDemoFailedReceiptBinding(
        path=resolved_receipt,
        failed_receipt_sha256=receipt_sha,
        failed_receipt_source_head=receipt_head,
        failed_receipt_scenario=scenario,
        failed_receipt_run_id=failed_run_id,
        opening_cl_ord_id=opening_clord_id,
        opening_order_id=opening_order_id,
        opening_fill_id=opening_fill_id,
        algo_cl_ord_id=algo_clord_id,
        algo_id=algo_id,
        expected_close_cl_ord_id=expected_close_clord_id,
        runtime_root=resolved_runtime,
        runtime_root_sha256=expected_root_sha,
        runtime_run_id=runtime_run_id,
        runtime_state_sha256=state_sha,
        runtime_events_sha256=events_sha,
        runtime_last_event_hash=recovered.last_event_hash,
        runtime_last_sequence=recovered.last_sequence,
        binding_path=binding_path,
        binding_sha256=binding_sha,
        binding_current_head=head,
        account_identity=account_identity,
        credential_identity=credential_identity,
        client_order_namespace=namespace,
        incident_source_head=incident_head,
        recovery_code_head=head,
        ancestry_proof=ancestry_proof,
        original_owner_marker_sha256=hashlib.sha256(lock_raw).hexdigest(),
        original_owner_marker_source_head=str(lock_payload.get("source_head") or ""),
        original_owner_marker_recovery_code_head=marker_recovery_head,
        original_owner_marker_runtime_root_sha256=str(
            lock_payload.get("runtime_root_sha256") or ""
        ),
        runtime_ledger_sha256=runtime_ledger_sha256,
    )


def _strict_partial_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _partial_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if any(not isinstance(item, str) or not item for item in value):
        return None
    return list(value)


def _strict_partial_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _partial_result_blockers(
    result: Mapping[str, Any],
    *,
    observed_runtime_run_ids: tuple[str, str] | None = None,
    expected_source_head: str | None = None,
) -> list[str]:
    """Validate the partial-fill evidence boundary before building a receipt."""

    blockers: list[str] = []
    if _strict_partial_int(result.get("entry_attempts")) != 1:
        blockers.append("fault_drill_partial_fill_entry_attempt_not_exactly_once")
    if _strict_partial_int(result.get("entry_retry_count")) != 0:
        blockers.append("fault_drill_partial_fill_entry_retry_forbidden")
    if result.get("entry_fill_classification") != "partial_fill":
        blockers.append("fault_drill_partial_fill_not_exchange_observed_partial")
    if result.get("discrepancy_classification") != "expected_partial_fill_recovery":
        blockers.append("fault_drill_partial_fill_discrepancy_classification_invalid")
    if result.get("entry_order_type") != "ioc":
        blockers.append("fault_drill_partial_fill_entry_order_type_not_ioc")

    requested = _strict_partial_decimal(result.get("requested_contracts"))
    fill = _strict_partial_decimal(result.get("entry_fill_contracts"))
    if requested != Decimal("0.03"):
        blockers.append("fault_drill_partial_fill_requested_contracts_not_exact_0p03")
    if fill is None or not (Decimal("0") < fill < Decimal("0.03")):
        blockers.append("fault_drill_partial_fill_contracts_not_strict_partial")
        blockers.append("fault_drill_partial_fill_not_exchange_observed_partial")
    for field in (
        "entry_order_filled_contracts",
        "entry_fill_sum_contracts",
        "entry_position_contracts",
    ):
        observed = _strict_partial_decimal(result.get(field))
        if fill is None or observed is None or observed != fill:
            blockers.append(
                "fault_drill_partial_fill_exchange_truth_mismatch:" + field
            )

    if result.get("broker_truth_verified") is not True:
        blockers.append("fault_drill_partial_fill_broker_truth_not_verified")
    if result.get("simulation_only") is not False:
        blockers.append("fault_drill_partial_fill_simulation_only_not_false")
    for field, expected in (
        ("synthetic", False),
        ("fixture", False),
        ("simulation", False),
        ("real_exchange_observation", True),
    ):
        if result.get(field) is not expected:
            blockers.append(
                f"fault_drill_partial_fill_{field}_evidence_invalid"
            )

    provenance = _mapping(result.get("provenance"))
    for field, expected in (
        ("runtime_boundary", _PARTIAL_RUNTIME_BOUNDARY),
        ("runtime_version", _PARTIAL_RUNTIME_VERSION),
        ("environment", "OKX Demo"),
        ("source", "exchange_snapshot"),
    ):
        if provenance.get(field) != expected:
            blockers.append(
                "fault_drill_partial_fill_provenance_invalid:" + field
            )
    runtime_attestation = _mapping(result.get("_runtime_attestation"))
    for field in (
        "runtime_boundary",
        "runtime_version",
        "environment",
        "source_head",
        "runtime_run_id",
        "controller_type",
        "attestation_version",
    ):
        if runtime_attestation.get(field) != provenance.get(field):
            blockers.append(
                "fault_drill_partial_fill_runtime_attestation_mismatch:" + field
            )
    if runtime_attestation.get("attestation_version") != _PARTIAL_ATTESTATION_VERSION:
        blockers.append("fault_drill_partial_fill_runtime_attestation_missing")
    if runtime_attestation.get("controller_type") != "OkxDemoPaperRuntimeController":
        blockers.append("fault_drill_partial_fill_runtime_controller_untrusted")
    for field in (
        "authority_version",
        "identity_namespace",
        "authoritative_receipt_sha256",
    ):
        if runtime_attestation.get(field) != provenance.get(field):
            blockers.append(
                "fault_drill_partial_fill_runtime_attestation_mismatch:" + field
            )
    if runtime_attestation.get("authority_version") != _PARTIAL_AUTHORITY_VERSION:
        blockers.append("fault_drill_partial_fill_authority_version_missing")
    provenance_source_head = provenance.get("source_head")
    if not isinstance(provenance_source_head, str) or not _HEAD_PATTERN.fullmatch(
        provenance_source_head
    ):
        blockers.append("fault_drill_partial_fill_provenance_source_head_missing")
    elif expected_source_head is not None and provenance_source_head != expected_source_head:
        blockers.append("fault_drill_partial_fill_provenance_source_head_mismatch")
    if provenance.get("real_exchange_observation") is not True:
        blockers.append("fault_drill_partial_fill_provenance_not_exchange_observed")
    for field in ("fixture", "simulation", "synthetic", "simulation_only"):
        if provenance.get(field) is not False:
            blockers.append(
                "fault_drill_partial_fill_provenance_invalid:" + field
            )
    runtime_run_id = provenance.get("runtime_run_id")
    if not isinstance(runtime_run_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._-]{3,96}", runtime_run_id
    ):
        blockers.append("fault_drill_partial_fill_runtime_run_identity_missing")
    if observed_runtime_run_ids is not None:
        for label, observed in zip(
            ("pre", "post"), observed_runtime_run_ids
        ):
            if not observed or observed != runtime_run_id:
                blockers.append(
                    "fault_drill_partial_fill_runtime_run_identity_mismatch:"
                    + label
                )
    runtime_receipt_sha256 = str(
        result.get("runtime_receipt_sha256") or ""
    )
    if not re.fullmatch(r"[0-9a-f]{64}", runtime_receipt_sha256):
        blockers.append("fault_drill_partial_fill_runtime_receipt_binding_missing")
    authoritative_receipt_sha256 = str(
        result.get("authoritative_receipt_sha256") or ""
    )
    if not re.fullmatch(r"[0-9a-f]{64}", authoritative_receipt_sha256):
        blockers.append(
            "fault_drill_partial_fill_authoritative_receipt_binding_missing"
        )

    reconciliation = _mapping(result.get("four_way_reconciliation"))
    for field in (
        "identity_sync",
        "order_sync",
        "fill_sync",
        "position_sync",
        "oco_sync",
        "ledger_sync",
        "private_ws_sync",
        "match",
    ):
        if reconciliation.get(field) is not True:
            blockers.append(
                "fault_drill_partial_fill_four_way_reconciliation_mismatch:"
                + field
            )

    entry_order_id = result.get("entry_order_id")
    close_order_id = result.get("close_order_id")
    opening_cl_ord_id = result.get("clOrdId")
    close_cl_ord_id = result.get("closeClOrdId")
    algo_cl_ord_id = result.get("algoClOrdId")
    algo_id = result.get("algo_id")
    if not isinstance(opening_cl_ord_id, str) or not _PARTIAL_CLIENT_ID_PATTERN.fullmatch(
        opening_cl_ord_id
    ):
        blockers.append("fault_drill_partial_fill_opening_clordid_invalid")
    if not isinstance(close_cl_ord_id, str) or not _PARTIAL_CLIENT_ID_PATTERN.fullmatch(
        close_cl_ord_id
    ):
        blockers.append("fault_drill_partial_fill_close_clordid_invalid")
    if isinstance(opening_cl_ord_id, str) and isinstance(close_cl_ord_id, str):
        if opening_cl_ord_id == close_cl_ord_id:
            blockers.append("fault_drill_partial_fill_entry_close_clordid_mixed")
    for label, value in (
        ("entry_order_id", entry_order_id),
        ("close_order_id", close_order_id),
        ("algo_id", algo_id),
    ):
        if not isinstance(value, str) or not _PARTIAL_VENUE_ID_PATTERN.fullmatch(value):
            blockers.append(f"fault_drill_partial_fill_{label}_invalid")
    if (
        isinstance(entry_order_id, str)
        and isinstance(close_order_id, str)
        and entry_order_id == close_order_id
    ):
        blockers.append("fault_drill_partial_fill_entry_close_order_id_mixed")
    if (
        isinstance(opening_cl_ord_id, str)
        and isinstance(algo_cl_ord_id, str)
        and algo_cl_ord_id != opening_cl_ord_id + "A"
    ):
        blockers.append("fault_drill_partial_fill_algo_clordid_parent_mismatch")
    if result.get("algo_parent_cl_ord_id") != opening_cl_ord_id:
        blockers.append("fault_drill_partial_fill_algo_parent_ownership_invalid")
    if result.get("entry_order_client_order_id") != opening_cl_ord_id:
        blockers.append("fault_drill_partial_fill_entry_order_ownership_invalid")
    if result.get("close_order_client_order_id") != close_cl_ord_id:
        blockers.append("fault_drill_partial_fill_close_order_ownership_invalid")

    entry_fill_ids = _partial_string_list(result.get("entry_fill_ids"))
    close_fill_ids = _partial_string_list(result.get("close_fill_ids"))
    entry_fill_order_ids = _partial_string_list(
        result.get("entry_fill_order_ids")
    )
    close_fill_order_ids = _partial_string_list(
        result.get("close_fill_order_ids")
    )
    entry_fill_client_ids = _partial_string_list(
        result.get("entry_fill_client_order_ids")
    )
    close_fill_client_ids = _partial_string_list(
        result.get("close_fill_client_order_ids")
    )
    authoritative_identity_projection = _mapping(
        result.get("authoritative_identity_projection")
    )
    attested_identity_projection = _mapping(
        runtime_attestation.get("authoritative_identity_projection")
    )
    provenance_identity_projection = _mapping(
        provenance.get("authoritative_identity_projection")
    )
    if not (
        authoritative_identity_projection
        and attested_identity_projection
        and provenance_identity_projection
    ):
        blockers.append(
            "fault_drill_partial_fill_authoritative_identity_projection_missing"
        )
    elif not (
        authoritative_identity_projection
        == attested_identity_projection
        == provenance_identity_projection
    ):
        blockers.append(
            "fault_drill_partial_fill_authoritative_identity_projection_mismatch"
        )

    if isinstance(runtime_run_id, str) and re.fullmatch(
        r"[A-Za-z0-9._-]{3,96}", runtime_run_id
    ):
        expected_identity_namespace = f"btcDP{runtime_run_id[:8]}"
        for label, value in (
            ("result", result.get("identity_namespace")),
            ("provenance", provenance.get("identity_namespace")),
            ("attestation", runtime_attestation.get("identity_namespace")),
            ("projection", authoritative_identity_projection.get("identity_namespace")),
        ):
            if value != expected_identity_namespace:
                blockers.append(
                    "fault_drill_partial_fill_identity_namespace_mismatch:"
                    + label
                )
        for label, value in (
            ("opening_clordid", result.get("clOrdId")),
            ("close_clordid", result.get("closeClOrdId")),
        ):
            if not isinstance(value, str) or not value.startswith(
                expected_identity_namespace
            ):
                blockers.append(
                    "fault_drill_partial_fill_identity_namespace_mismatch:"
                    + label
                )

    projection_metadata = {
        "authority_version": _PARTIAL_AUTHORITY_VERSION,
        "runtime_boundary": _PARTIAL_RUNTIME_BOUNDARY,
        "runtime_version": _PARTIAL_RUNTIME_VERSION,
        "controller_type": "OkxDemoPaperRuntimeController",
        "source_head": provenance_source_head,
        "runtime_run_id": runtime_run_id,
        "identity_namespace": provenance.get("identity_namespace"),
    }
    if authoritative_identity_projection:
        for field, expected in projection_metadata.items():
            if authoritative_identity_projection.get(field) != expected:
                blockers.append(
                    "fault_drill_partial_fill_authoritative_identity_projection_mismatch:"
                    + field
                )

    identity_projection_pairs = {
        "clOrdId": opening_cl_ord_id,
        "closeClOrdId": close_cl_ord_id,
        "algoClOrdId": algo_cl_ord_id,
        "entry_order_id": entry_order_id,
        "close_order_id": close_order_id,
        "algo_id": algo_id,
        "algo_parent_cl_ord_id": result.get("algo_parent_cl_ord_id"),
        "entry_order_client_order_id": result.get(
            "entry_order_client_order_id"
        ),
        "close_order_client_order_id": result.get(
            "close_order_client_order_id"
        ),
    }
    identity_projection_list_pairs = {
        "entry_fill_ids": entry_fill_ids,
        "close_fill_ids": close_fill_ids,
        "entry_fill_order_ids": entry_fill_order_ids,
        "close_fill_order_ids": close_fill_order_ids,
        "entry_fill_client_order_ids": entry_fill_client_ids,
        "close_fill_client_order_ids": close_fill_client_ids,
    }
    if authoritative_identity_projection:
        for field, expected in identity_projection_pairs.items():
            if authoritative_identity_projection.get(field) != expected:
                label = (
                    "foreign_order_id"
                    if field in {"entry_order_id", "close_order_id"}
                    else "foreign_algo_id"
                    if field in {"algo_id", "algoClOrdId"}
                    else "foreign_client_order_id"
                )
                blockers.append(
                    "fault_drill_partial_fill_authoritative_identity_"
                    + label
                )
        for field, expected in identity_projection_list_pairs.items():
            if authoritative_identity_projection.get(field) != (
                list(expected) if expected is not None else None
            ):
                blockers.append(
                    "fault_drill_partial_fill_authoritative_identity_foreign_fill_id"
                )

    expected_authoritative_receipt_sha256 = _sha256(
        {
            "authority_version": _PARTIAL_AUTHORITY_VERSION,
            "identity_projection": _safe_json(authoritative_identity_projection),
        }
    )
    for label, value in (
        ("result_authoritative", authoritative_receipt_sha256),
        ("result_runtime", runtime_receipt_sha256),
        (
            "provenance",
            str(provenance.get("authoritative_receipt_sha256") or ""),
        ),
        (
            "attestation",
            str(runtime_attestation.get("authoritative_receipt_sha256") or ""),
        ),
    ):
        if value != expected_authoritative_receipt_sha256:
            blockers.append(
                "fault_drill_partial_fill_authoritative_receipt_binding_mismatch:"
                + label
            )
    for label, values in (
        ("entry_fill_ids", entry_fill_ids),
        ("close_fill_ids", close_fill_ids),
        ("entry_fill_order_ids", entry_fill_order_ids),
        ("close_fill_order_ids", close_fill_order_ids),
        ("entry_fill_client_order_ids", entry_fill_client_ids),
        ("close_fill_client_order_ids", close_fill_client_ids),
    ):
        if not values:
            blockers.append(f"fault_drill_partial_fill_{label}_missing")
    if entry_fill_ids is not None and len(entry_fill_ids) != len(set(entry_fill_ids)):
        blockers.append("fault_drill_partial_fill_duplicate_entry_fill_id")
    if close_fill_ids is not None and len(close_fill_ids) != len(set(close_fill_ids)):
        blockers.append("fault_drill_partial_fill_duplicate_close_fill_id")
    for label, values in (
        ("entry_fill_ids", entry_fill_ids),
        ("close_fill_ids", close_fill_ids),
    ):
        if values is not None and any(
            not _PARTIAL_VENUE_ID_PATTERN.fullmatch(value) for value in values
        ):
            blockers.append(f"fault_drill_partial_fill_{label}_format_invalid")
    if entry_fill_ids is not None and close_fill_ids is not None:
        if set(entry_fill_ids) & set(close_fill_ids):
            blockers.append("fault_drill_partial_fill_entry_close_fill_id_mixed")
    if (
        entry_fill_order_ids is not None
        and isinstance(entry_order_id, str)
        and any(value != entry_order_id for value in entry_fill_order_ids)
    ):
        blockers.append("fault_drill_partial_fill_entry_fill_order_ownership_invalid")
    if (
        close_fill_order_ids is not None
        and isinstance(close_order_id, str)
        and any(value != close_order_id for value in close_fill_order_ids)
    ):
        blockers.append("fault_drill_partial_fill_close_fill_order_ownership_invalid")
    if (
        entry_fill_client_ids is not None
        and isinstance(opening_cl_ord_id, str)
        and any(value != opening_cl_ord_id for value in entry_fill_client_ids)
    ):
        blockers.append("fault_drill_partial_fill_entry_fill_client_ownership_invalid")
    if (
        close_fill_client_ids is not None
        and isinstance(close_cl_ord_id, str)
        and any(value != close_cl_ord_id for value in close_fill_client_ids)
    ):
        blockers.append("fault_drill_partial_fill_close_fill_client_ownership_invalid")
    if entry_fill_ids is not None and len(entry_fill_ids) != len(entry_fill_order_ids or []):
        blockers.append("fault_drill_partial_fill_entry_fill_identity_count_mismatch")
    if close_fill_ids is not None and len(close_fill_ids) != len(close_fill_order_ids or []):
        blockers.append("fault_drill_partial_fill_close_fill_identity_count_mismatch")
    if entry_fill_ids is not None and len(entry_fill_ids) != len(entry_fill_client_ids or []):
        blockers.append("fault_drill_partial_fill_entry_fill_owner_count_mismatch")
    if close_fill_ids is not None and len(close_fill_ids) != len(close_fill_client_ids or []):
        blockers.append("fault_drill_partial_fill_close_fill_owner_count_mismatch")

    for field, expected in (
        ("close_fill_contracts", fill),
        ("close_order_filled_contracts", fill),
    ):
        observed = _strict_partial_decimal(result.get(field))
        if expected is None or observed is None or observed != expected:
            blockers.append("fault_drill_partial_fill_close_truth_mismatch:" + field)
    after_truth = _mapping(reconciliation.get("after"))
    if after_truth:
        after_fill = _strict_partial_decimal(after_truth.get("filled_contracts"))
        after_position = _strict_partial_decimal(
            after_truth.get("position_contracts")
        )
        if fill is None or after_fill != fill or after_position != fill:
            blockers.append("fault_drill_partial_fill_reconnect_truth_quantity_mismatch")
        if after_truth.get("exchange_order_id") != entry_order_id:
            blockers.append("fault_drill_partial_fill_reconnect_order_identity_mismatch")
        after_ids = _partial_string_list(after_truth.get("fill_ids"))
        if after_ids != entry_fill_ids:
            blockers.append("fault_drill_partial_fill_reconnect_fill_identity_mismatch")
        if after_truth.get("algo_id") != algo_id:
            blockers.append("fault_drill_partial_fill_reconnect_algo_identity_mismatch")
    else:
        blockers.append("fault_drill_partial_fill_reconnect_truth_missing")

    if result.get("protection_verified") is not True:
        blockers.append("fault_drill_partial_fill_verified_protection_missing")
    if result.get("disconnect_observed") is not True or result.get("reconnect_bounded") is not True:
        blockers.append("fault_drill_partial_fill_disconnect_reconnect_not_proven")
    if result.get("operator_ack_required") is not True:
        blockers.append("fault_drill_partial_fill_operator_ack_contract_missing")
    if result.get("operator_acknowledged") is not True:
        blockers.append("fault_drill_partial_fill_operator_ack_required")
    if result.get("opening_allowed") is not False:
        blockers.append("fault_drill_partial_fill_opening_not_blocked")
    if result.get("recovery_state") != "RECOVERY_PENDING":
        blockers.append("fault_drill_partial_fill_recovery_state_invalid")
    if result.get("decision") not in {
        "completed_flat_fail_closed",
        "completed_safe_flat",
    }:
        blockers.append("fault_drill_partial_fill_decision_invalid")
    if _strict_partial_int(result.get("orders_posted")) != 2:
        blockers.append("fault_drill_partial_fill_real_open_close_not_exactly_two")
    for field in (
        "final_flat",
        "final_no_pending_orders",
        "final_no_pending_algo_orders",
        "final_no_unresolved_intents",
        "final_ledger_reconciled",
        "final_private_ws_reconciled",
    ):
        if result.get(field) is not True:
            blockers.append("fault_drill_partial_fill_final_state_not_proven:" + field)
    algo_cleanup = _mapping(result.get("algo_cleanup"))
    if (
        algo_cleanup.get("pending_readback_empty") is not True
        or algo_cleanup.get("history_terminal_verified") is not True
    ):
        blockers.append("fault_drill_partial_fill_algo_cleanup_not_reconciled")
    pre_hash = str(result.get("pre_reconciliation_sha256") or "")
    post_hash = str(result.get("post_reconciliation_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", pre_hash) or not re.fullmatch(
        r"[0-9a-f]{64}", post_hash
    ):
        blockers.append("fault_drill_partial_fill_reconciliation_hash_missing")
    return _dedupe(blockers)


def _result_blockers(
    scenario: str,
    result: Mapping[str, Any],
    *,
    observed_runtime_run_ids: tuple[str, str] | None = None,
    expected_source_head: str | None = None,
) -> list[str]:
    """Reject flat-looking receipts that did not execute the P0 fault semantics."""

    blockers: list[str] = []
    if scenario == "partial_fill_disconnect":
        return _partial_result_blockers(
            result,
            observed_runtime_run_ids=observed_runtime_run_ids,
            expected_source_head=expected_source_head,
        )
    if int(result.get("orders_posted") or 0) < 2:
        blockers.append(f"fault_drill_{scenario}_real_open_close_missing")
    if result.get("position_observed") is not True:
        blockers.append(f"fault_drill_{scenario}_real_position_evidence_missing")
    if result.get("protection_verified") is not True:
        blockers.append(f"fault_drill_{scenario}_verified_protection_missing")

    pre_hash = str(result.get("pre_reconciliation_sha256") or "")
    post_hash = str(result.get("post_reconciliation_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", pre_hash) or not re.fullmatch(
        r"[0-9a-f]{64}", post_hash
    ):
        blockers.append(f"fault_drill_{scenario}_reconciliation_hash_missing")

    if scenario == "worker_kill":
        termination = _mapping(result.get("child_termination"))
        process_id = result.get("process_id")
        reconstructed_process_id = result.get("reconstructed_process_id")
        if (
            not isinstance(process_id, int)
            or process_id <= 0
            or not isinstance(reconstructed_process_id, int)
            or reconstructed_process_id <= 0
            or reconstructed_process_id == process_id
            or termination.get("external") is not True
            or termination.get("terminated") is not True
            or termination.get("wait_confirmed") is not True
            or result.get("worker_ready_marker_persisted") is not True
        ):
            blockers.append(
                "fault_drill_worker_kill_external_termination_not_proven"
            )
        if result.get("same_position_after_reconstruction") is not True:
            blockers.append(
                "fault_drill_worker_kill_position_not_preserved"
            )
        if result.get("same_protection_after_reconstruction") is not True:
            blockers.append(
                "fault_drill_worker_kill_protection_not_preserved"
            )
    elif scenario == "reconnect_full_reconciliation":
        if (
            result.get("disconnect_observed") is not True
            or result.get("reconciliation_comparison_match") is not True
        ):
            blockers.append(
                "fault_drill_reconnect_full_reconciliation_mismatch"
            )
    elif scenario == "protection_creation_failure":
        if (
            result.get("evidence_mode")
            != "hybrid_real_position_injected_verification_failure"
            or result.get("fault_origin")
            != "local_injected_protection_verification_readback_failure"
            or result.get("injected_protection_verification_failure_observed")
            is not True
        ):
            blockers.append(
                "fault_drill_protection_failure_evidence_mode_invalid"
            )
    elif scenario == "held_position_disconnect":
        if result.get("disconnect_observed") is not True:
            blockers.append("fault_drill_held_position_disconnect_not_observed")
    elif scenario == "post_response_loss":
        if result.get("post_response_loss_reconciled") is not True:
            blockers.append("fault_drill_post_response_loss_not_reconciled")
    return _dedupe(blockers)


def _snapshot_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _mapping(snapshot.get("runtime"))
    risk = _mapping(snapshot.get("risk_control"))
    exchange = _mapping(snapshot.get("exchange"))
    ledger = _mapping(snapshot.get("ledger_reconciliation"))
    private_ws = _mapping(snapshot.get("private_ws"))
    return {
        "run_id": str(runtime.get("run_id") or ""),
        "runtime": {
            key: runtime.get(key)
            for key in (
                "active",
                "opening_allowed",
                "cancel_only",
                "status",
                "last_heartbeat_utc",
                "last_reconciled_at_utc",
            )
        },
        "risk_mode": str(risk.get("mode") or ""),
        "pending_order_intents": {
            str(key): str(_mapping(value).get("status") or "")
            for key, value in _mapping(risk.get("pending_order_intents")).items()
        },
        "private_ws": {
            key: private_ws.get(key)
            for key in (
                "connected",
                "listener_alive",
                "opening_allowed_after_reconciliation",
            )
        },
        "orders": [_public_order(row) for row in _rows(exchange.get("orders"))],
        "fills": [_public_fill(row) for row in _rows(exchange.get("fills"))],
        "positions": [_public_position(row) for row in _rows(exchange.get("positions"))],
        "pending_orders": [
            _public_order(row) for row in _rows(exchange.get("pending_orders"))
        ],
        "pending_algo_orders": [
            _public_algo(row) for row in _rows(exchange.get("pending_algo_orders"))
        ],
        "ledger_reconciliation": {
            "status": str(ledger.get("status") or ""),
            "current_state_exchange_snapshot_match": ledger.get(
                "current_state_exchange_snapshot_match"
            )
            is True,
            "ledger_hash": str(
                ledger.get("ledger_hash")
                or ledger.get("current_state_hash")
                or (_sha256(ledger) if ledger else "")
            ),
        },
    }


def _flat_recovery_identity_projection(
    snapshot: Mapping[str, Any],
    *,
    owned_client_order_ids: tuple[str, ...],
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
                    raise FaultDrillReceiptError(
                        "fault_drill_flat_fill_order_id_mapping_"
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


def _flat_recovery_identity_sha256(
    snapshot: Mapping[str, Any],
    *,
    owned_client_order_ids: tuple[str, ...],
) -> str:
    """Hash only stable order/fill/position/OCO identity for a flat receipt."""

    return hashlib.sha256(
        json.dumps(
            _flat_recovery_identity_projection(
                snapshot,
                owned_client_order_ids=owned_client_order_ids,
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _public_order(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": str(row.get("order_id") or row.get("ordId") or ""),
        "clOrdId": str(row.get("client_order_id") or row.get("clOrdId") or ""),
        "state": str(row.get("state") or row.get("status") or ""),
    }


def _public_fill(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fill_id": str(row.get("fill_id") or row.get("tradeId") or ""),
        "order_id": str(row.get("order_id") or row.get("ordId") or ""),
        "clOrdId": str(row.get("client_order_id") or row.get("clOrdId") or ""),
        "size": str(row.get("size") or row.get("fillSz") or ""),
    }


def _public_position(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "instrument_id": str(row.get("instrument_id") or row.get("instId") or ""),
        "position_side": str(row.get("position_side") or row.get("posSide") or ""),
        "contracts": str(row.get("contracts") or row.get("pos") or "0"),
    }


def _public_algo(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "algo_id": str(row.get("algo_id") or row.get("algoId") or ""),
        "algoClOrdId": str(
            row.get("algo_client_order_id") or row.get("algoClOrdId") or ""
        ),
        "state": str(row.get("state") or ""),
    }


def _receipt_path(config: BtcOkxDemoFaultDrillConfig) -> Path:
    return (
        config.receipt_external_root
        / "btc_okx_demo_fault_drill"
        / config.source_head
        / config.scenario
        / f"{config.run_id}.json"
    )


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise FaultDrillReceiptError("fault_drill_receipt_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(
        _safe_json(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FaultDrillReceiptError(
                "fault_drill_receipt_already_exists"
            ) from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _repo_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _safe_json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")[:240]
    return f"{type(exc).__name__}:{text}"


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [row for row in value or [] if isinstance(row, Mapping)]


def _source_head_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "source_head" and isinstance(nested, str):
                values.append(nested)
            values.extend(_source_head_values(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            values.extend(_source_head_values(nested))
    return values


def _source_head_entries(value: Any) -> list[Any]:
    """Collect runtime-code source heads, excluding archive-only provenance."""

    entries: list[Any] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            # These are immutable provenance/audit subtrees, not the code
            # identity of the runtime event that persisted the projection.
            if key in {"owned_id_restore", "owner_marker_audit"}:
                continue
            if key == "source_head":
                entries.append(nested)
            entries.extend(_source_head_entries(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            entries.extend(_source_head_entries(nested))
    return entries


def _runtime_event_source_head(event: Mapping[str, Any]) -> str:
    """Return one canonical source head for an already hash-verified event."""

    if str(event.get("event_type") or "") == "owned_id_restore_applied":
        # This event records immutable owned-ID archive provenance, not runtime
        # code provenance. Its archive source is independently verified.
        return ""
    values = [value for value in _source_head_entries(event) if value not in {None, ""}]
    if not values:
        return ""
    if any(
        not isinstance(value, str) or _HEAD_PATTERN.fullmatch(value) is None
        for value in values
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_source_mismatch"
        )
    if len(set(values)) != 1:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_source_mismatch"
        )
    return str(values[0])


def _validate_runtime_source_head_chain(
    *,
    state: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    incident_head: str,
    recovery_head: str,
    repo_root: Path,
) -> tuple[tuple[Mapping[str, Any], str], ...]:
    """Accept only a monotonic incident/recovery source-head history.

    A failed read-only recovery may append a committed recovery-code head to
    an immutable incident root.  The opening identity stays anchored to the
    original receipt.  The terminal head must remain inside the proven closed
    interval ``incident_head <= terminal_head <= recovery_head``.
    """

    event_heads: list[tuple[Mapping[str, Any], str]] = []
    for event in events:
        if not isinstance(event, Mapping):
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_runtime_source_mismatch"
            )
        event_head = _runtime_event_source_head(event)
        if event_head:
            event_heads.append((event, event_head))
    runtime_state = state.get("runtime")
    runtime = _mapping(runtime_state)
    state_source_head_missing = (
        isinstance(runtime_state, Mapping) and "source_head" not in runtime_state
    )
    runtime_head = runtime.get("source_head")
    if (
        _HEAD_PATTERN.fullmatch(incident_head) is None
        or _HEAD_PATTERN.fullmatch(recovery_head) is None
        or _bounded_recovery_ancestry_probe(repo_root, incident_head, recovery_head)
        is None
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_source_mismatch"
        )
    if not event_heads:
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_source_mismatch"
        )
    ordered_heads: list[str] = []
    for _, event_head in event_heads:
        if not ordered_heads or ordered_heads[-1] != event_head:
            ordered_heads.append(event_head)
    terminal_head = ordered_heads[-1]
    if (
        _bounded_recovery_ancestry_probe(repo_root, incident_head, terminal_head)
        is None
        or _bounded_recovery_ancestry_probe(repo_root, terminal_head, recovery_head)
        is None
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_source_mismatch"
        )
    if not state_source_head_missing and (
        not isinstance(runtime_head, str)
        or _HEAD_PATTERN.fullmatch(runtime_head) is None
        or runtime_head != terminal_head
    ):
        raise FaultDrillReceiptError(
            "fault_drill_recovery_binding_runtime_source_mismatch"
        )
    for ancestor, descendant in zip(ordered_heads, ordered_heads[1:]):
        if _bounded_recovery_ancestry_probe(repo_root, ancestor, descendant) is None:
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_runtime_source_mismatch"
            )
    return tuple(event_heads)


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("NaN")
    return parsed if parsed.is_finite() else Decimal("NaN")


def _decimal_text(value: Any) -> str:
    parsed = _decimal(value)
    if not parsed.is_finite():
        return "invalid"
    return format(parsed.normalize(), "f")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise FaultDrillReceiptError("fault_drill_clock_must_be_timezone_aware")
    return value.astimezone(timezone.utc)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))
