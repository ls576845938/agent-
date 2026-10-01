from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.application.btc_okx_demo_fault_drill import (
    DEMO_FAULT_DRILL_SCENARIOS,
    BtcOkxDemoFaultDrillConfig,
    BtcOkxDemoFaultDrillService,
    BtcOkxDemoFailedReceiptBinding,
    FaultDrillReceiptError,
    FaultDrillInjector,
)
from quant_crypto.application.btc_strategy_registry import (
    OKX_NATIVE_STRATEGY_LINE,
    btc_strategy_registry,
)
from quant_crypto.oms.okx_demo_paper_runtime import (
    OKX_DEMO_APPROVED_PROTECTION_POLICY,
    OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
    OKX_DEMO_PAPER_CONFIRMATION,
    OKX_DEMO_PAPER_ORDER_TAG,
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
)
from quant_crypto.runtime.control_plane import (
    BTCDemoClientCapabilityAdapter,
    BTCDemoExecutionDispatcher,
)


_DEFAULT_STRATEGY_ID = "long_short_donchian_top5"
_DEFAULT_STRATEGY_SPEC = btc_strategy_registry.get(_DEFAULT_STRATEGY_ID)
_DEFAULT_CANDIDATE_ID = _DEFAULT_STRATEGY_SPEC.candidate_id
_DEFAULT_STRATEGY_VERSION = _DEFAULT_STRATEGY_SPEC.strategy_version
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed BTC OKX Demo P0 fault-drill runner",
    )
    parser.add_argument("--scenario", choices=DEMO_FAULT_DRILL_SCENARIOS, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--receipt-external-root", type=Path, required=True)
    parser.add_argument("--environment", choices=("OKX Demo",), required=True)
    parser.add_argument("--instrument-id", choices=("BTC-USDT-SWAP",), required=True)
    parser.add_argument("--margin-mode", choices=("isolated",), required=True)
    parser.add_argument("--leverage", choices=("3",), required=True)
    parser.add_argument("--order-contracts", choices=("0.01", "0.03"), required=True)
    parser.add_argument("--max-notional-usdt", required=True)
    parser.add_argument("--partial-fill-reference-price-usdt", default="")
    parser.add_argument(
        "--confirm-dedicated-demo-account",
        action="store_true",
        required=True,
    )
    parser.add_argument(
        "--execute-demo",
        action="store_true",
        help="Actually use the existing Demo runtime; omitted means zero-POST dry run.",
    )
    parser.add_argument(
        "--operator-ack",
        action="store_true",
        help="Acknowledge the bounded recovery result; opening remains disabled.",
    )
    parser.add_argument("--data-db-path", type=Path)
    parser.add_argument("--runtime-output-dir", type=Path)
    parser.add_argument("--okx-native-shared-manifest-git-spec", default="")
    parser.add_argument("--okx-native-shared-data-root", type=Path)
    parser.add_argument("--okx-native-expected-dataset-id", default="")
    parser.add_argument("--owned-id-restore-archive-root", type=Path)
    parser.add_argument("--owned-id-restore-current-head", default="")
    parser.add_argument("--owned-id-restore-source-head", default="")
    parser.add_argument("--owned-id-restore-account-identity", default="")
    parser.add_argument("--owned-id-restore-credential-identity", default="")
    parser.add_argument("--owned-id-restore-client-order-namespace", default="")
    parser.add_argument("--strategy-id", default=_DEFAULT_STRATEGY_ID)
    parser.add_argument("--candidate-id", default=_DEFAULT_CANDIDATE_ID)
    parser.add_argument("--strategy-version", default=_DEFAULT_STRATEGY_VERSION)
    parser.add_argument(
        "--worker-child-marker",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--worker-nonce", help=argparse.SUPPRESS)
    parser.add_argument("--incident-recovery-failed-receipt", type=Path)
    parser.add_argument("--incident-recovery-failed-receipt-sha256", default="")
    parser.add_argument(
        "--incident-recovery-worker-parent-emergency-receipt",
        type=Path,
        help=(
            "Immutable worker-parent emergency receipt used only by canonical "
            "worker_kill recovery binding."
        ),
    )
    parser.add_argument(
        "--incident-recovery-worker-parent-emergency-receipt-sha256",
        default="",
    )
    parser.add_argument("--incident-recovery-opening-clordid", default="")
    parser.add_argument("--incident-recovery-algo-clordid", default="")
    parser.add_argument("--incident-recovery-algo-id", default="")
    parser.add_argument("--incident-recovery-close-clordid", default="")
    parser.add_argument(
        "--incident-recovery-runtime-root",
        type=Path,
        help="Exact external durable runtime root for canonical recovery binding.",
    )
    parser.add_argument(
        "--incident-recovery-current-head",
        default="",
        help="Legacy single-head field; canonical v2 uses explicit dual-head fields.",
    )
    parser.add_argument(
        "--incident-recovery-incident-source-head",
        default="",
        help="Expected source HEAD recorded by the failed incident/runtime.",
    )
    parser.add_argument(
        "--incident-recovery-recovery-code-head",
        default="",
        help="Expected current recovery code HEAD; verified from Git directly.",
    )
    parser.add_argument(
        "--incident-recovery-repo-root",
        type=Path,
        help="Repository root used for direct current-HEAD and ancestry checks.",
    )
    parser.add_argument(
        "--incident-recovery-binding-external-root",
        type=Path,
        help="External root for the unique immutable recovery binding.",
    )
    parser.add_argument("--incident-recovery-runtime-root-sha256", default="")
    parser.add_argument("--incident-recovery-state-sha256", default="")
    parser.add_argument("--incident-recovery-events-sha256", default="")
    parser.add_argument(
        "--incident-recovery-identity-archive-root",
        type=Path,
        help=(
            "Explicit immutable owned-ID archive used only as a verified "
            "account/credential identity anchor for canonical recovery."
        ),
    )
    parser.add_argument("--flat-hosted-exit-failed-receipt", type=Path)
    parser.add_argument("--flat-hosted-exit-failed-receipt-sha256", default="")
    parser.add_argument("--flat-hosted-exit-fresh-truth-receipt", type=Path)
    parser.add_argument("--flat-hosted-exit-fresh-truth-receipt-sha256", default="")
    parser.add_argument("--flat-hosted-exit-fresh-truth-payload-sha256", default="")
    parser.add_argument("--flat-hosted-exit-fill-diagnostic-receipt", type=Path)
    parser.add_argument("--flat-hosted-exit-fill-diagnostic-receipt-sha256", default="")
    parser.add_argument("--flat-hosted-exit-fill-diagnostic-payload-sha256", default="")
    parser.add_argument("--flat-hosted-exit-order-receipt", type=Path)
    parser.add_argument("--flat-hosted-exit-order-receipt-sha256", default="")
    parser.add_argument("--flat-hosted-exit-order-payload-sha256", default="")
    parser.add_argument("--flat-hosted-exit-binding-external-root", type=Path)
    return parser


def _validate_okx_native_shared_dataset_binding(args: argparse.Namespace) -> None:
    if not getattr(args, "execute_demo", False) or getattr(
        args,
        "strategy_id",
        _DEFAULT_STRATEGY_ID,
    ) != OKX_NATIVE_STRATEGY_LINE:
        return
    missing = [
        flag
        for flag, present in (
            (
                "--okx-native-shared-manifest-git-spec",
                bool(str(args.okx_native_shared_manifest_git_spec).strip()),
            ),
            (
                "--okx-native-shared-data-root",
                args.okx_native_shared_data_root is not None,
            ),
            (
                "--okx-native-expected-dataset-id",
                bool(str(args.okx_native_expected_dataset_id).strip()),
            ),
        )
        if not present
    ]
    if missing:
        raise SystemExit(
            "OKX Native shared dataset binding is required with --execute-demo: "
            + ", ".join(missing)
        )


def _validate_incident_recovery_arguments(args: argparse.Namespace) -> None:
    flat_values = (
        args.flat_hosted_exit_failed_receipt,
        args.flat_hosted_exit_failed_receipt_sha256,
        args.flat_hosted_exit_fresh_truth_receipt,
        args.flat_hosted_exit_fresh_truth_receipt_sha256,
        args.flat_hosted_exit_fresh_truth_payload_sha256,
        args.flat_hosted_exit_fill_diagnostic_receipt,
        args.flat_hosted_exit_fill_diagnostic_receipt_sha256,
        args.flat_hosted_exit_fill_diagnostic_payload_sha256,
        args.flat_hosted_exit_order_receipt,
        args.flat_hosted_exit_order_receipt_sha256,
        args.flat_hosted_exit_order_payload_sha256,
        args.flat_hosted_exit_binding_external_root,
    )
    flat_enabled = any(value is not None and str(value).strip() for value in flat_values)
    if flat_enabled and not all(
        value is not None and str(value).strip() for value in flat_values
    ):
        raise SystemExit(
            "flat hosted exit recovery requires the complete four-receipt hash bundle and external root"
        )
    if flat_enabled and any(
        value is not None and str(value).strip()
        for value in (
            args.incident_recovery_failed_receipt,
            args.incident_recovery_failed_receipt_sha256,
            args.incident_recovery_worker_parent_emergency_receipt,
            args.incident_recovery_worker_parent_emergency_receipt_sha256,
            args.incident_recovery_opening_clordid,
            args.incident_recovery_algo_clordid,
            args.incident_recovery_algo_id,
            args.incident_recovery_close_clordid,
            args.incident_recovery_runtime_root,
            args.incident_recovery_current_head,
            args.incident_recovery_incident_source_head,
            args.incident_recovery_recovery_code_head,
            args.incident_recovery_repo_root,
            args.incident_recovery_binding_external_root,
            args.incident_recovery_runtime_root_sha256,
            args.incident_recovery_state_sha256,
            args.incident_recovery_events_sha256,
            args.incident_recovery_identity_archive_root,
        )
    ):
        raise SystemExit(
            "flat hosted exit recovery cannot mix canonical or caller-supplied incident identity fields"
        )
    if flat_enabled and any(
        _SHA256_PATTERN.fullmatch(str(value or "")) is None
        for value in (
            args.flat_hosted_exit_failed_receipt_sha256,
            args.flat_hosted_exit_fresh_truth_receipt_sha256,
            args.flat_hosted_exit_fresh_truth_payload_sha256,
            args.flat_hosted_exit_fill_diagnostic_receipt_sha256,
            args.flat_hosted_exit_fill_diagnostic_payload_sha256,
            args.flat_hosted_exit_order_receipt_sha256,
            args.flat_hosted_exit_order_payload_sha256,
        )
    ):
        raise SystemExit("flat hosted exit recovery requires lowercase sha256 values")
    canonical_enabled = args.incident_recovery_runtime_root is not None
    worker_parent_emergency_values = (
        args.incident_recovery_worker_parent_emergency_receipt is not None,
        bool(
            str(
                args.incident_recovery_worker_parent_emergency_receipt_sha256
            ).strip()
        ),
    )
    if any(worker_parent_emergency_values) and not all(
        worker_parent_emergency_values
    ):
        raise SystemExit(
            "worker-parent emergency recovery requires immutable receipt path and sha256"
        )
    if any(worker_parent_emergency_values) and not canonical_enabled:
        raise SystemExit(
            "worker-parent emergency receipt is only valid with canonical runtime root"
        )
    if all(worker_parent_emergency_values) and _SHA256_PATTERN.fullmatch(
        str(args.incident_recovery_worker_parent_emergency_receipt_sha256)
    ) is None:
        raise SystemExit("worker-parent emergency recovery requires lowercase sha256")
    if args.incident_recovery_identity_archive_root is not None and not canonical_enabled:
        raise SystemExit(
            "incident recovery identity archive is only valid with canonical runtime root"
        )
    if args.incident_recovery_current_head and not canonical_enabled:
        raise SystemExit(
            "incident recovery current-head is only valid with canonical runtime root"
        )
    canonical_heads = (
        str(getattr(args, "incident_recovery_incident_source_head", "")).strip(),
        str(getattr(args, "incident_recovery_recovery_code_head", "")).strip(),
    )
    canonical_repo_root = getattr(args, "incident_recovery_repo_root", None)
    if canonical_enabled and not (
        args.incident_recovery_failed_receipt is not None
        and bool(str(args.incident_recovery_failed_receipt_sha256).strip())
    ):
        raise SystemExit(
            "canonical incident recovery requires immutable failed receipt path and sha256"
        )
    if canonical_enabled and any(
        _SHA256_PATTERN.fullmatch(str(value or "")) is None
        for value in (
            args.incident_recovery_runtime_root_sha256,
            args.incident_recovery_state_sha256,
            args.incident_recovery_events_sha256,
        )
    ):
        raise SystemExit(
            "canonical incident recovery requires runtime root, state, and events sha256"
        )
    if canonical_enabled and (
        not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in canonical_heads)
        or canonical_repo_root is None
    ):
        raise SystemExit(
            "canonical incident recovery requires incident source, recovery code head, and repo root"
        )
    if canonical_enabled and canonical_heads[0] == "" and canonical_heads[1] == "":
        raise SystemExit(
            "canonical incident recovery requires incident source, recovery code head, and repo root"
        )
    values = (
        args.incident_recovery_failed_receipt is not None,
        bool(str(args.incident_recovery_failed_receipt_sha256).strip()),
        bool(str(args.incident_recovery_opening_clordid).strip()),
        bool(str(args.incident_recovery_algo_clordid).strip()),
        bool(str(args.incident_recovery_algo_id).strip()),
        bool(str(args.incident_recovery_close_clordid).strip()),
    )
    manual_identity_values = values[2:]
    if any(values) and not all(values) and not canonical_enabled:
        raise SystemExit(
            "incident recovery arguments must be supplied all-or-none"
        )
    if (all(values) or canonical_enabled) and not args.execute_demo:
        raise SystemExit("incident recovery requires --execute-demo")
    if canonical_enabled and any(manual_identity_values):
        raise SystemExit(
            "canonical incident recovery must not accept caller-supplied opening/algo/close identities"
        )


def _validate_owned_id_restore_arguments(args: argparse.Namespace) -> None:
    values = (
        getattr(args, "owned_id_restore_archive_root", None) is not None,
        bool(str(getattr(args, "owned_id_restore_current_head", "")).strip()),
        bool(str(getattr(args, "owned_id_restore_source_head", "")).strip()),
        bool(str(getattr(args, "owned_id_restore_account_identity", "")).strip()),
        bool(str(getattr(args, "owned_id_restore_credential_identity", "")).strip()),
        bool(str(getattr(args, "owned_id_restore_client_order_namespace", "")).strip()),
    )
    if any(values) and not all(values):
        raise SystemExit(
            "owned-id restore arguments must be supplied all-or-none"
        )
    if all(values) and not getattr(args, "execute_demo", False):
        raise SystemExit("owned-id restore requires --execute-demo")


def _runtime(args: argparse.Namespace, config: BtcOkxDemoFaultDrillConfig) -> OkxDemoPaperRuntimeController:
    _validate_okx_native_shared_dataset_binding(args)
    _validate_owned_id_restore_arguments(args)
    configured_runtime_output = getattr(args, "runtime_output_dir", None)
    incident_runtime_root = getattr(args, "incident_recovery_runtime_root", None)
    runtime_output_dir = configured_runtime_output or incident_runtime_root
    if (
        incident_runtime_root is not None
        and configured_runtime_output is not None
        and configured_runtime_output.resolve() != incident_runtime_root.resolve()
    ):
        raise SystemExit("incident recovery runtime root conflicts with --runtime-output-dir")
    if args.data_db_path is None or runtime_output_dir is None:
        raise SystemExit(
            "--data-db-path and --runtime-output-dir are required with --execute-demo"
        )
    runtime_config = OkxDemoPaperRuntimeConfig(
            repo_root=config.repo_root,
            data_db_path=args.data_db_path,
            output_dir=runtime_output_dir,
            okx_native_shared_manifest_git_spec=getattr(
                args,
                "okx_native_shared_manifest_git_spec",
                "",
            ),
            okx_native_shared_data_root=getattr(
                args,
                "okx_native_shared_data_root",
                None,
            ),
            okx_native_expected_dataset_id=getattr(
                args,
                "okx_native_expected_dataset_id",
                "",
            ),
            owned_id_restore_archive_root=getattr(
                args, "owned_id_restore_archive_root", None
            ),
            owned_id_restore_current_head=getattr(
                args, "owned_id_restore_current_head", ""
            ),
            owned_id_restore_source_head=getattr(
                args, "owned_id_restore_source_head", ""
            ),
            owned_id_restore_account_identity=getattr(
                args, "owned_id_restore_account_identity", ""
            ),
            owned_id_restore_credential_identity=getattr(
                args, "owned_id_restore_credential_identity", ""
            ),
            owned_id_restore_client_order_namespace=getattr(
                args, "owned_id_restore_client_order_namespace", ""
            ),
        )
    dispatcher = BTCDemoExecutionDispatcher(
        expected_source_head=_read_repo_head(config.repo_root),
        state_directory=(
            Path(runtime_config.output_dir) / "btc-demo-execution-boundary"
        ),
        capability_adapter=BTCDemoClientCapabilityAdapter(),
        credential_service=runtime_config.credential_service,
    )
    return OkxDemoPaperRuntimeController(
        config=replace(runtime_config, execution_dispatcher=dispatcher),
        start_worker=False,
    )


def _read_repo_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _start_runtime(
    runtime: OkxDemoPaperRuntimeController,
    args: argparse.Namespace,
) -> None:
    scenario = str(getattr(args, "scenario", "") or "")
    partial = scenario == "partial_fill_disconnect"
    restore_payload = {
        "owned_id_restore_archive_root": getattr(
            args, "owned_id_restore_archive_root", None
        ),
        "owned_id_restore_current_head": getattr(
            args, "owned_id_restore_current_head", ""
        ),
        "owned_id_restore_source_head": getattr(
            args, "owned_id_restore_source_head", ""
        ),
        "owned_id_restore_account_identity": getattr(
            args, "owned_id_restore_account_identity", ""
        ),
        "owned_id_restore_credential_identity": getattr(
            args, "owned_id_restore_credential_identity", ""
        ),
        "owned_id_restore_client_order_namespace": getattr(
            args, "owned_id_restore_client_order_namespace", ""
        ),
    }
    if restore_payload["owned_id_restore_archive_root"] is None:
        restore_payload = {}
    runtime.start(
        {
            "authorization_ticket": OKX_DEMO_PAPER_AUTHORIZATION_TICKET,
            "strategy_id": args.strategy_id,
            "candidate_id": args.candidate_id,
            "strategy_version": args.strategy_version,
            "instrument_id": "BTC-USDT-SWAP",
            "margin_mode": "isolated",
            "order_contracts": "0.03" if partial else "0.01",
            "max_net_contracts": "0.03" if partial else "0.01",
            "max_notional_usdt": getattr(args, "max_notional_usdt", "10"),
            "confirmation_text": OKX_DEMO_PAPER_CONFIRMATION,
            "confirm_demo_only": True,
            "confirm_automatic_orders": True,
            "confirm_risk_limits": True,
            "confirm_cancel_only_on_error": True,
            "confirm_dedicated_demo_account": True,
            "dead_man_tag": OKX_DEMO_PAPER_ORDER_TAG,
            "server_side_protection_policy": dict(
                OKX_DEMO_APPROVED_PROTECTION_POLICY
            ),
            "fault_drill_scenario": scenario if partial else "",
            **restore_payload,
        }
    )


def _write_worker_marker(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class WorkerParentEmergency(RuntimeError):
    """The exact worker remains fail-closed or requires manual recovery."""


def _worker_emergency_receipt_path(
    config: BtcOkxDemoFaultDrillConfig,
    *,
    nonce: str,
) -> Path:
    return (
        config.receipt_external_root
        / "btc_okx_demo_fault_drill_emergency"
        / config.source_head
        / "worker_kill"
        / f"{config.run_id}-{nonce}.json"
    )


def _write_worker_emergency_receipt(
    *,
    config: BtcOkxDemoFaultDrillConfig,
    process: Any,
    nonce: str,
    process_create_time: str,
    stage: str,
    envelope: Mapping[str, Any],
    parent_readback: Mapping[str, Any],
    failure: BaseException,
) -> Path:
    child_result = dict(envelope.get("result") or {})
    alive = process.poll() is None
    path = _worker_emergency_receipt_path(config, nonce=nonce)
    _write_worker_marker(
        path,
        {
            "schema_version": "btc_okx_demo_worker_parent_emergency_v1",
            "evidence_class": "demo_fault_drill_emergency_evidence",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_head": config.source_head,
            "scenario": "worker_kill",
            "run_id": config.run_id,
            "decision": "blocked_fail_closed_worker_supervision_required",
            "promotion_eligible": False,
            "paper_allowed": False,
            "live_allowed": False,
            "orders_retried": 0,
            "failure_stage": stage,
            "failure_type": type(failure).__name__,
            "failure_code": f"worker_parent_{stage}_failed",
            "parent_process_id": os.getpid(),
            "exact_child_handle_owned": True,
            "child": {
                "process_id": int(process.pid),
                "process_create_time": process_create_time,
                "worker_nonce": nonce,
                "alive_at_receipt": alive,
            },
            "last_proven": {
                "marker_identity_bound": bool(
                    envelope.get("process_id") == process.pid
                    and envelope.get("worker_nonce") == nonce
                    and str(envelope.get("process_create_time") or "")
                    == process_create_time
                ),
                "position_observed_by_child": child_result.get(
                    "position_observed"
                )
                is True,
                "protection_verified_by_child": child_result.get(
                    "protection_verified"
                )
                is True,
                "parent_query_only_readback_verified": parent_readback.get(
                    "verified"
                )
                is True,
                "parent_reconciliation_sha256": str(
                    parent_readback.get("reconciliation_sha256") or ""
                ),
                "parent_ledger_snapshot_sha256": str(
                    parent_readback.get("ledger_snapshot_sha256") or ""
                ),
            },
            "disposition": (
                "parent_waiting_on_exact_child_handle_no_kill_without_"
                "query_first_identity_and_protection_proof"
                if alive
                else "exact_child_exited_recovery_required"
            ),
            "operator_actions": [
                "keep_this_parent_process_running_while_child_is_alive",
                "inspect_runtime_status_read_only",
                "do_not_resend_order_or_cancel_requests",
                "resume_only_with_exact_pid_create_time_nonce_and_"
                "query_first_exchange_reconciliation",
            ],
            "credentials_redacted": True,
        },
    )
    return path


_PERSISTENT_SUPERVISORS: dict[int, threading.Thread] = {}


def _supervise_blocked_child(
    process: Any,
    *,
    deadline_seconds: float = 15.0,
) -> dict[str, Any]:
    """Wait for an exact child only for a fixed, interruptible horizon."""

    deadline = time.monotonic() + max(0.0, float(deadline_seconds))
    while process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "disposition": "supervision_deadline_exceeded",
                "exact_child_exited": False,
                "persistent_supervisor_handoff_confirmed": False,
            }
        try:
            process.wait(timeout=min(5.0, remaining))
        except subprocess.TimeoutExpired:
            continue
    return {
        "disposition": "exact_child_exited",
        "exact_child_exited": True,
        "persistent_supervisor_handoff_confirmed": False,
    }


def _handoff_to_persistent_supervisor(process: Any) -> dict[str, Any]:
    """Retain the exact Popen handle in a confirmed non-daemon supervisor."""

    started = threading.Event()

    def supervise() -> None:
        started.set()
        while process.poll() is None:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                continue
        _PERSISTENT_SUPERVISORS.pop(int(process.pid), None)

    thread = threading.Thread(
        target=supervise,
        name=f"btc-okx-demo-worker-supervisor-{int(process.pid)}",
        daemon=False,
    )
    _PERSISTENT_SUPERVISORS[int(process.pid)] = thread
    thread.start()
    confirmed = started.wait(1.0) and thread.is_alive()
    if not confirmed:
        _PERSISTENT_SUPERVISORS.pop(int(process.pid), None)
        raise WorkerParentEmergency(
            "worker_parent_persistent_supervisor_handoff_failed"
        )
    return {
        "disposition": "persistent_supervisor_handoff",
        "exact_child_exited": False,
        "persistent_supervisor_handoff_confirmed": True,
        "supervisor_name": thread.name,
    }


def _process_create_time(process_id: int) -> str:
    if os.name != "nt":
        stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
        return str(stat.split()[21])
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000, False, process_id)
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")
    try:
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessTimes failed")
        return str(creation.value)
    finally:
        kernel32.CloseHandle(handle)


def _kill_exact_spawned_child(
    process: Any,
    *,
    envelope: Mapping[str, Any],
    expected_nonce: str,
    expected_process_create_time: str,
    parent_readback: Mapping[str, Any],
) -> int:
    child_result = dict(envelope.get("result") or {})
    if not (
        process.poll() is None
        and envelope.get("process_id") == process.pid
        and envelope.get("process_create_time") == expected_process_create_time
        and envelope.get("worker_nonce") == expected_nonce
        and child_result.get("process_id") == process.pid
        and child_result.get("worker_ready_marker_persisted") is True
        and child_result.get("position_observed") is True
        and child_result.get("protection_verified") is True
        and parent_readback.get("verified") is True
        and _process_create_time(process.pid) == expected_process_create_time
    ):
        raise RuntimeError(
            "child identity/protection changed; exact spawned child was not killed"
        )
    process.kill()
    return int(process.wait(timeout=15.0))


class _PreexecutedWorkerRuntime:
    def __init__(
        self,
        *,
        pre_snapshot: Mapping[str, Any],
        post_snapshot: Mapping[str, Any],
        result: Mapping[str, Any],
        recovered_runtime: OkxDemoPaperRuntimeController,
    ) -> None:
        self._pre = dict(pre_snapshot)
        self._post = dict(post_snapshot)
        self._result = dict(result)
        self._run = False
        self._recovered_runtime = recovered_runtime

    def fault_drill_snapshot(self) -> Mapping[str, Any]:
        return self._post if self._run else self._pre

    def run_fault_drill_scenario(self, *_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        self._run = True
        return self._result

    def freeze_fault_drill(self, reason: str) -> None:
        self._recovered_runtime.freeze_fault_drill(reason)


def _run_worker_child(
    args: argparse.Namespace,
    config: BtcOkxDemoFaultDrillConfig,
) -> int:
    if not args.execute_demo or config.scenario != "worker_kill":
        raise SystemExit("worker child is restricted to explicit worker_kill Demo execution")
    runtime = _runtime(args, config)
    if not args.worker_nonce:
        raise SystemExit("worker nonce missing")
    runtime.acquire_fault_drill_process_lock(nonce=args.worker_nonce)
    _start_runtime(runtime, args)
    pre_snapshot = runtime.fault_drill_snapshot()
    injector = FaultDrillInjector("worker_kill")
    process_create_time = _process_create_time(os.getpid())
    result = runtime.run_fault_drill_scenario(
        "worker_kill",
        fault_injector=injector,
        authorization={
            **config.runtime_authorization(),
            "worker_nonce": args.worker_nonce,
            "process_create_time": process_create_time,
        },
    )
    if not (
        result.get("decision") == "worker_ready_for_external_termination"
        and result.get("worker_ready_marker_persisted") is True
        and result.get("position_observed") is True
        and result.get("protection_verified") is True
        and result.get("process_id") == os.getpid()
    ):
        raise SystemExit("worker ready marker lacks verified held protection")
    _write_worker_marker(
        args.worker_child_marker,
        {
            "schema_version": "btc_okx_demo_worker_process_envelope_v1",
            "process_id": os.getpid(),
            "process_create_time": process_create_time,
            "worker_nonce": args.worker_nonce,
            "pre_snapshot": pre_snapshot,
            "worker_ready_marker": runtime.fault_drill_snapshot()["runtime"][
                "fault_drill_worker_ready"
            ],
            "result": result,
            "fault_injection_timeline": injector.timeline,
        },
    )
    while True:
        time.sleep(1.0)


def _run_worker_parent(
    args: argparse.Namespace,
    config: BtcOkxDemoFaultDrillConfig,
) -> tuple[_PreexecutedWorkerRuntime, OkxDemoPaperRuntimeController]:
    if args.runtime_output_dir is None:
        raise SystemExit("--runtime-output-dir is required with worker_kill")
    marker = (
        args.runtime_output_dir.resolve()
        / "fault_drill_worker_markers"
        / f"{config.run_id}.json"
    )
    if marker.exists():
        raise SystemExit("worker marker already exists; choose a new run-id")
    nonce = uuid.uuid4().hex
    child_args = [
        sys.executable,
        str(Path(__file__).resolve()),
        *sys.argv[1:],
        "--worker-child-marker",
        str(marker),
        "--worker-nonce",
        nonce,
    ]
    process = subprocess.Popen(child_args, cwd=config.repo_root)
    stage = "process_create_time"
    process_create_time = ""
    envelope: dict[str, Any] = {}
    parent_readback: dict[str, Any] = {}
    try:
        process_create_time = _process_create_time(process.pid)
        stage = "marker_wait"
        deadline = time.monotonic() + 180.0
        while not marker.exists():
            if process.poll() is not None:
                raise RuntimeError("worker_child_exited_before_ready_marker")
            if time.monotonic() >= deadline:
                raise TimeoutError("worker_child_ready_marker_timed_out")
            time.sleep(0.25)
        stage = "marker_json"
        envelope = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict):
            raise ValueError("worker_ready_envelope_not_object")
        ready_marker = dict(envelope.get("worker_ready_marker") or {})
        stage = "parent_query_only_readback"
        verifier = _runtime(args, config)
        parent_readback = verifier.verify_fault_drill_worker_ready(
            ready_marker,
            expected_nonce=nonce,
            expected_process_id=process.pid,
            expected_process_create_time=process_create_time,
        )
        # Popen owns the exact process handle spawned above. Kill is permitted
        # only after nonce/PID/create-time and independent exchange readback.
        stage = "exact_identity_kill"
        _kill_exact_spawned_child(
            process,
            envelope=envelope,
            expected_nonce=nonce,
            expected_process_create_time=process_create_time,
            parent_readback=parent_readback,
        )
        stage = "query_first_recovery"
        recovered = _runtime(args, config)
        child_termination = {
            "process_id": process.pid,
            "process_create_time": process_create_time,
            "worker_nonce": nonce,
            "external": True,
            "terminated": True,
            "wait_confirmed": process.poll() is not None,
            "returncode": process.returncode,
            "parent_readback_verified": parent_readback.get("verified") is True,
            "parent_reconciliation_sha256": parent_readback.get(
                "reconciliation_sha256"
            ),
            "parent_ledger_snapshot_sha256": parent_readback.get(
                "ledger_snapshot_sha256"
            ),
        }
        result = recovered.recover_fault_drill_after_worker_kill(
            authorization={
                **config.runtime_authorization(),
                "worker_nonce": nonce,
                "process_create_time": process_create_time,
            },
            child_termination=child_termination,
        )
        wrapped = _PreexecutedWorkerRuntime(
            pre_snapshot=dict(envelope.get("pre_snapshot") or {}),
            post_snapshot=recovered.fault_drill_snapshot(),
            result=result,
            recovered_runtime=recovered,
        )
        return wrapped, recovered
    except BaseException as exc:
        emergency_path: Path | None = None
        receipt_failure: BaseException | None = None
        try:
            emergency_path = _write_worker_emergency_receipt(
                config=config,
                process=process,
                nonce=nonce,
                process_create_time=process_create_time,
                stage=stage,
                envelope=envelope,
                parent_readback=parent_readback,
                failure=exc,
            )
        except BaseException as write_exc:
            receipt_failure = write_exc
        if emergency_path is not None:
            print(
                "WORKER_PARENT_BLOCKED_FAIL_CLOSED "
                f"receipt={emergency_path.resolve()} "
                f"child_pid={process.pid} "
                f"child_create_time={process_create_time or 'unknown'}",
                file=sys.stderr,
                flush=True,
            )
        if process.poll() is None:
            try:
                supervision = _supervise_blocked_child(process)
            except KeyboardInterrupt:
                supervision = _handoff_to_persistent_supervisor(process)
                print(
                    "WORKER_PARENT_SUPERVISION "
                    + json.dumps(supervision, sort_keys=True),
                    file=sys.stderr,
                    flush=True,
                )
                raise
            if supervision["exact_child_exited"] is not True:
                supervision = _handoff_to_persistent_supervisor(process)
            print(
                "WORKER_PARENT_SUPERVISION "
                + json.dumps(supervision, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )
        if receipt_failure is not None:
            raise WorkerParentEmergency(
                "worker_parent_emergency_receipt_failed_after_exact_child_exit"
            ) from receipt_failure
        raise WorkerParentEmergency(
            f"worker_parent_blocked_fail_closed:{emergency_path}"
        ) from exc


def main() -> int:
    args = build_parser().parse_args()
    _validate_incident_recovery_arguments(args)
    _validate_owned_id_restore_arguments(args)
    _validate_okx_native_shared_dataset_binding(args)
    canonical_enabled = args.incident_recovery_runtime_root is not None
    if canonical_enabled:
        canonical_repo_root = (
            args.incident_recovery_repo_root or args.repo_root
        ).resolve()
        if args.incident_recovery_repo_root is not None and (
            canonical_repo_root != args.repo_root.resolve()
        ):
            raise SystemExit(
                "canonical incident recovery repo root conflicts with --repo-root"
            )
        try:
            observed_recovery_head = _read_repo_head(canonical_repo_root)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SystemExit(
                "canonical incident recovery current HEAD unavailable"
            ) from exc
        if (
            observed_recovery_head
            != args.incident_recovery_recovery_code_head
            or args.source_head != observed_recovery_head
        ):
            raise SystemExit(
                "canonical incident recovery requires actual recovery code HEAD"
            )
        args.repo_root = canonical_repo_root
        effective_source_head = observed_recovery_head
    else:
        effective_source_head = args.source_head
    config = BtcOkxDemoFaultDrillConfig(
        repo_root=args.repo_root,
        receipt_external_root=args.receipt_external_root,
        source_head=effective_source_head,
        scenario=args.scenario,
        run_id=args.run_id,
        execute_demo=args.execute_demo,
        environment=args.environment,
        instrument_id=args.instrument_id,
        margin_mode=args.margin_mode,
        leverage=args.leverage,
        order_contracts=args.order_contracts,
        max_notional_usdt=args.max_notional_usdt,
        partial_fill_reference_price_usdt=(
            args.partial_fill_reference_price_usdt
        ),
        confirm_dedicated_demo_account=args.confirm_dedicated_demo_account,
        operator_ack=args.operator_ack,
    )
    incident_binding: BtcOkxDemoFailedReceiptBinding | None = None
    if args.worker_child_marker is not None:
        return _run_worker_child(args, config)
    if args.worker_nonce is not None:
        raise SystemExit("--worker-nonce is reserved for the spawned child")
    current_head = _read_repo_head(config.repo_root)
    if (
        (args.incident_recovery_runtime_root is not None
         or args.flat_hosted_exit_failed_receipt is not None)
        and current_head != config.source_head
    ):
        raise SystemExit("incident recovery requires current source HEAD")
    safe_to_construct_runtime = not config.preflight_blockers() and current_head == config.source_head
    service = BtcOkxDemoFaultDrillService()
    runtime: Any = None
    runtime_to_stop: OkxDemoPaperRuntimeController | None = None
    receipt: dict[str, Any] | None = None
    startup_failure: BaseException | None = None
    stop_status: Mapping[str, Any] = {}
    lifecycle_blockers: list[str] = []
    postflight_complete = False
    interrupt: KeyboardInterrupt | None = None
    try:
        if args.flat_hosted_exit_failed_receipt is not None:
            incident_binding = BtcOkxDemoFailedReceiptBinding.load_flat_hosted_exit_bundle(
                failed_receipt_path=args.flat_hosted_exit_failed_receipt,
                failed_receipt_sha256=args.flat_hosted_exit_failed_receipt_sha256,
                fresh_truth_path=args.flat_hosted_exit_fresh_truth_receipt,
                fresh_truth_sha256=args.flat_hosted_exit_fresh_truth_receipt_sha256,
                fresh_truth_payload_sha256=(
                    args.flat_hosted_exit_fresh_truth_payload_sha256
                ),
                fill_diagnostic_path=args.flat_hosted_exit_fill_diagnostic_receipt,
                fill_diagnostic_sha256=(
                    args.flat_hosted_exit_fill_diagnostic_receipt_sha256
                ),
                fill_diagnostic_payload_sha256=(
                    args.flat_hosted_exit_fill_diagnostic_payload_sha256
                ),
                exit_order_path=args.flat_hosted_exit_order_receipt,
                exit_order_sha256=args.flat_hosted_exit_order_receipt_sha256,
                exit_order_payload_sha256=(
                    args.flat_hosted_exit_order_payload_sha256
                ),
                binding_external_root=args.flat_hosted_exit_binding_external_root,
                repo_root=args.repo_root,
            )
        elif args.incident_recovery_failed_receipt is not None:
            if (
                args.incident_recovery_runtime_root is not None
                and args.incident_recovery_recovery_code_head != config.source_head
            ):
                raise FaultDrillReceiptError(
                    "fault_drill_incident_recovery_current_head_mismatch"
                )
            incident_binding = BtcOkxDemoFailedReceiptBinding.load(
                path=args.incident_recovery_failed_receipt,
                expected_sha256=args.incident_recovery_failed_receipt_sha256,
                expected_opening_cl_ord_id=args.incident_recovery_opening_clordid,
                expected_algo_cl_ord_id=args.incident_recovery_algo_clordid,
                expected_algo_id=args.incident_recovery_algo_id,
                expected_close_cl_ord_id=args.incident_recovery_close_clordid,
                runtime_root=args.incident_recovery_runtime_root,
                repo_root=args.repo_root,
                expected_incident_source_head=(
                    args.incident_recovery_incident_source_head
                ),
                expected_recovery_code_head=(
                    args.incident_recovery_recovery_code_head
                ),
                binding_external_root=(
                    args.incident_recovery_binding_external_root
                    or args.receipt_external_root
                    / "btc_okx_demo_recovery_bindings"
                )
                if args.incident_recovery_runtime_root is not None
                else None,
                expected_runtime_root_sha256=args.incident_recovery_runtime_root_sha256,
                expected_runtime_state_sha256=args.incident_recovery_state_sha256,
                expected_runtime_events_sha256=args.incident_recovery_events_sha256,
                identity_archive_root=args.incident_recovery_identity_archive_root,
                worker_parent_emergency_receipt=(
                    args.incident_recovery_worker_parent_emergency_receipt
                ),
                worker_parent_emergency_receipt_sha256=(
                    args.incident_recovery_worker_parent_emergency_receipt_sha256
                ),
            )
        if incident_binding is not None and (
            config.scenario == "partial_fill_disconnect"
            or config.scenario != incident_binding.failed_receipt_scenario
        ):
            raise FaultDrillReceiptError(
                "fault_drill_incident_recovery_scenario_mismatch"
            )
        if (
            args.execute_demo
            and safe_to_construct_runtime
        ):
            if incident_binding is not None:
                runtime = _runtime(args, config)
                runtime_to_stop = runtime
            elif args.scenario == "worker_kill":
                runtime, runtime_to_stop = _run_worker_parent(args, config)
            else:
                runtime = _runtime(args, config)
                runtime_to_stop = runtime
                _start_runtime(runtime, args)
        receipt = (
            service.run_incident_recovery(
                config,
                runtime=runtime,
                binding=incident_binding,
            )
            if incident_binding is not None and runtime is not None
            else service.run(config, runtime=runtime)
        )
        postflight_complete = True
    except KeyboardInterrupt as exc:
        startup_failure = exc
        interrupt = exc
        if runtime_to_stop is not None:
            try:
                runtime_to_stop.freeze_fault_drill(
                    "fault_drill_cli_interrupted"
                )
            except Exception as freeze_exc:
                lifecycle_blockers.append(
                    "fault_drill_cli_freeze_failed:" + type(freeze_exc).__name__
                )
    except Exception as exc:
        startup_failure = exc
        if runtime_to_stop is not None:
            try:
                runtime_to_stop.freeze_fault_drill(
                    "fault_drill_cli_startup_or_execution_failed"
                )
            except Exception as freeze_exc:
                lifecycle_blockers.append(
                    "fault_drill_cli_freeze_failed:" + type(freeze_exc).__name__
                )
    finally:
        incident_recovery_failed = bool(
            incident_binding is not None
            and receipt is not None
            and receipt.get("decision") != "completed_safe_flat"
        )
        if runtime_to_stop is not None and not incident_recovery_failed and (
            startup_failure is None
            or interrupt is not None
            or (incident_binding is not None and receipt is None)
        ):
            try:
                stop_status = (
                    runtime_to_stop.finalize_incident_recovery_local()
                    if incident_binding is not None
                    else runtime_to_stop.stop(
                        {"confirmation_text": OKX_DEMO_PAPER_CONFIRMATION}
                    )
                )
            except Exception as stop_exc:
                lifecycle_blockers.append(
                    "fault_drill_cli_stop_failed:" + type(stop_exc).__name__
                )
                try:
                    runtime_to_stop.freeze_fault_drill(
                        "fault_drill_cli_finalizer_failed"
                    )
                except Exception as freeze_exc:
                    lifecycle_blockers.append(
                        "fault_drill_cli_finalizer_freeze_failed:"
                        + type(freeze_exc).__name__
                    )
        if runtime_to_stop is not None:
            try:
                runtime_to_stop.release_fault_drill_process_lock()
            except Exception as release_exc:
                lifecycle_blockers.append(
                    "fault_drill_cli_writer_lock_release_failed:"
                    + type(release_exc).__name__
                )
            try:
                if not stop_status:
                    stop_status = runtime_to_stop.status()
            except Exception as status_exc:
                lifecycle_blockers.append(
                    "fault_drill_cli_terminal_status_failed:"
                    + type(status_exc).__name__
                )
    if receipt is None:
        assert startup_failure is not None
        receipt = service.build_startup_failure_receipt(
            config,
            error=startup_failure,
            post_snapshot=stop_status,
        )
    runtime_row = dict(stop_status.get("runtime") or {})
    risk_row = dict(stop_status.get("risk_control") or {})
    dead_man = dict(risk_row.get("dead_man") or {})
    private_ws = dict(stop_status.get("private_ws") or {})
    if (
        private_ws.get("cleanup_complete") is False
        or str(private_ws.get("cleanup_error") or "")
    ):
        lifecycle_blockers.append(
            "fault_drill_cli_private_ws_cleanup_unproven"
        )
    startup_resources_terminal = (
        startup_failure is not None
        and runtime_row.get("active") is not True
        and dead_man.get("armed") is not True
    )
    incident_resources_terminal = (
        incident_binding is not None
        and runtime_row.get("active") is not True
        and private_ws.get("listener_alive") is not True
        and private_ws.get("cleanup_complete") is not False
    )
    runtime_clean_stop = (
        runtime_to_stop is None
        or (
            startup_resources_terminal
            or incident_resources_terminal
            or runtime_row.get("status") == "stopped"
        )
    ) and not lifecycle_blockers
    threads_joined = runtime_to_stop is None or (
        runtime_row.get("worker_alive") is not True
        and dead_man.get("heartbeat_thread_alive") is not True
        and private_ws.get("listener_alive") is not True
    )
    dead_man_disarmed = runtime_to_stop is None or dead_man.get("armed") is not True
    writer_lock_released = runtime_to_stop is None or (
        getattr(runtime_to_stop, "_fault_drill_lock_handle", None) is None
    )
    if lifecycle_blockers:
        receipt["blockers"] = list(
            dict.fromkeys(
                [
                    *[str(row) for row in receipt.get("blockers") or []],
                    *lifecycle_blockers,
                ]
            )
        )
    receipt = service.publish_terminal_receipt(
        config,
        receipt,
        lifecycle={
            "terminal": True,
            "postflight_complete": postflight_complete,
            "startup_failed": startup_failure is not None,
            "runtime_not_constructed": runtime_to_stop is None,
            "runtime_clean_stop": runtime_clean_stop,
            "threads_joined": threads_joined,
            "dead_man_disarmed": dead_man_disarmed,
            "dead_man_terminal_evidence": (
                dict(dead_man) if incident_binding is not None else {}
            ),
            "writer_lock_released": writer_lock_released,
            "cleanup_complete": (
                runtime_clean_stop
                and threads_joined
                and dead_man_disarmed
                and writer_lock_released
            ),
            "receipt_written_after_cleanup": True,
        },
    )
    receipt = {**receipt, "receipt_path": str(
        config.receipt_external_root
        / "btc_okx_demo_fault_drill"
        / config.source_head
        / config.scenario
        / f"{config.run_id}.json"
    )}
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if interrupt is not None:
        raise interrupt
    return 0 if receipt["decision"] in {
        "dry_run_fail_closed",
        "completed_safe_flat",
        "completed_flat_fail_closed",
        "blocked_by_venue_lot_and_risk_cap",
        "blocked_by_max_notional_usdt_cap",
        "blocked_no_real_partial_fill_evidence",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
