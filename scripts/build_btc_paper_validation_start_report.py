#!/usr/bin/env python3
"""Build a fail-closed BTC paper-validation start report.

The report is read-only. It does not import paper/live execution modules and it
never starts a validation run. It only turns a fully approved BTC paper
readiness report plus a BTC-specific paper-validation runtime contract into an
authorized start command.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_paper_readiness/latest")
DEFAULT_READINESS_REPORT = DEFAULT_OUTPUT_ROOT / "btc_paper_readiness_report.json"
DEFAULT_OPERATOR_PACKET = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json")
DEFAULT_CANDIDATE_BOUNDED_RETEST_PLAN = Path("artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json")
DEFAULT_CANDIDATE_BOUNDED_RETEST_OUTCOME = Path(
    "artifacts/btc_candidate_gate/latest/candidate_bounded_retest_outcome_report.json"
)
DEFAULT_LEDGER_ROOT = Path("data/paper_ledger/btc")
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_VALIDATION_RUNNER = Path("scripts/run_btc_paper_validation.py")
DEFAULT_PREFLIGHT_RUNNER = Path("scripts/check_btc_paper_validation_readiness.py")
LEDGER_START_LOCK_NAME = "btc_paper_validation_start.lock.json"
RUNTIME_CONTRACT = "btc_paper_validation_runtime_v1"
PREFLIGHT_CONTRACT = "btc_paper_validation_preflight_v1"
PREFLIGHT_PROBE_COMMAND = (
    "python3 scripts/check_btc_paper_validation_readiness.py --repo-root . --symbols BTCUSDT "
    "--market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data "
    "--no-start-report-ready-required --json"
)
APPROVED_START_COMMAND = (
    "python3 scripts/run_btc_paper_validation.py --repo-root . --symbols BTCUSDT "
    "--market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data"
)
APPROVED_RESUME_COMMAND = (
    "python3 scripts/run_btc_paper_validation.py --repo-root . --symbols BTCUSDT "
    "--market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data --resume"
)
APPROVED_PREFLIGHT_COMMAND = (
    "python3 scripts/check_btc_paper_validation_readiness.py --repo-root . --symbols BTCUSDT "
    "--market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data --json"
)
REPORT_REBUILD_COMMAND = "python3 scripts/build_btc_paper_validation_start_report.py"


def build_btc_paper_validation_start_report(
    *,
    repo_root: Path | None = None,
    readiness_report: Path | None = None,
    operator_packet: Path | None = None,
    candidate_bounded_retest_plan: Path | None = None,
    candidate_bounded_retest_outcome: Path | None = None,
    validation_runner: Path | None = None,
    preflight_runner: Path | None = None,
    ledger_root: Path | None = None,
    data_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    readiness_path = _resolve(root, readiness_report or DEFAULT_READINESS_REPORT)
    operator_packet_path = _resolve(root, operator_packet or DEFAULT_OPERATOR_PACKET)
    candidate_bounded_retest_path = _resolve(root, candidate_bounded_retest_plan or DEFAULT_CANDIDATE_BOUNDED_RETEST_PLAN)
    candidate_bounded_retest_outcome_path = _resolve(
        root, candidate_bounded_retest_outcome or DEFAULT_CANDIDATE_BOUNDED_RETEST_OUTCOME
    )
    validation_runner_path = validation_runner or DEFAULT_VALIDATION_RUNNER
    preflight_runner_path = preflight_runner or DEFAULT_PREFLIGHT_RUNNER
    ledger = ledger_root or DEFAULT_LEDGER_ROOT
    data = data_root or DEFAULT_DATA_ROOT
    readiness = _read_json(readiness_path)
    operator_packet_payload = _read_json(operator_packet_path)
    candidate_bounded_retest_payload = _read_json(candidate_bounded_retest_path)
    candidate_bounded_retest_outcome_payload = _read_json(candidate_bounded_retest_outcome_path)
    runtime = _runtime_contract(
        root=root,
        validation_runner=validation_runner_path,
        preflight_runner=preflight_runner_path,
        ledger_root=ledger,
        data_root=data,
    )
    preflight_probe = _preflight_probe(
        root=root,
        runtime=runtime,
        preflight_runner=preflight_runner_path,
        ledger_root=ledger,
        data_root=data,
    )
    ledger_session = _ledger_session_summary(root=root, ledger_root=ledger)
    readiness_summary = _readiness_summary(root, readiness_path, readiness)
    manual_inputs = _manual_inputs_summary(readiness)
    operator_unblock = _operator_manual_unblock(
        root=root,
        path=operator_packet_path,
        payload=operator_packet_payload,
        manual_inputs=manual_inputs,
    )
    approved_review = _approved_review(readiness)
    blockers = _dedupe(
        _readiness_blockers(readiness_summary, approved_review, readiness)
        + _list_of_strings(operator_unblock.get("blockers"))
        + _runtime_blockers(runtime)
        + _preflight_probe_blockers(preflight_probe)
        + _ledger_session_blockers(ledger_session)
    )
    ready = (
        not blockers
        and readiness_summary["status"] == "ready_for_paper_start"
        and readiness_summary["paper_start_allowed"]
        and readiness_summary["paper_execution_authorized"]
        and readiness_summary["live_status"] == "frozen"
        and approved_review["approved"]
        and approved_review["evidence_pack_exists"]
        and runtime["runner_supports_btc_usdm_perpetual"]
        and runtime["preflight_supports_btc_usdm_perpetual"]
        and preflight_probe["ready_without_start_report"]
        and ledger_session["status"] in {"clean_start", "resumable"}
    )
    status = "ready_to_start_paper_validation" if ready else "blocked"
    start_command = APPROVED_START_COMMAND if ready and ledger_session["status"] == "clean_start" else ""
    resume_command = APPROVED_RESUME_COMMAND if ready and ledger_session["status"] == "resumable" else ""
    return {
        "schema_version": "btc_paper_validation_start_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "market_type": "usds_m_perpetual",
        "status": status,
        "paper_start_allowed": ready,
        "paper_execution_authorized": ready,
        "live_status": "frozen" if readiness_summary["live_status"] == "frozen" else readiness_summary["live_status"],
        "next_required_action": _next_required_action(readiness_summary, runtime, ledger_session, operator_unblock, ready),
        "readiness": readiness_summary,
        "manual_inputs": manual_inputs,
        "operator_manual_unblock": operator_unblock,
        "approved_paper_review": approved_review,
        "runtime": runtime,
        "preflight_probe": preflight_probe,
        "ledger_session": ledger_session,
        "unblock_sequence": _unblock_sequence(
            readiness=readiness,
            operator_unblock=operator_unblock,
            candidate_bounded_retest=_candidate_bounded_retest_summary(
                root=root,
                path=candidate_bounded_retest_path,
                payload=candidate_bounded_retest_payload,
                outcome_path=candidate_bounded_retest_outcome_path,
                outcome_payload=candidate_bounded_retest_outcome_payload,
            ),
            approved_review=approved_review,
            runtime=runtime,
            preflight_probe=preflight_probe,
            ledger_session=ledger_session,
            ready=ready,
        ),
        "commands": {
            "report_rebuild_command": REPORT_REBUILD_COMMAND,
            "preflight_command": APPROVED_PREFLIGHT_COMMAND if ready else "",
            "start_command": start_command,
            "resume_command": resume_command,
        },
        "safety": {
            "report_only": True,
            "requires_readiness_report": True,
            "requires_approved_review": True,
            "requires_evidence_pack": True,
            "strategy_direct_broker_forbidden": True,
            "all_orders_must_pass_risk_engine": True,
            "allows_live_orders": False,
            "paper_auto_start": False,
        },
        "blockers": [] if ready else blockers,
    }


def write_btc_paper_validation_start_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_paper_validation_start_report.json"
    _write_json_atomic(output, payload)
    return str(output)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), indent=2, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        return
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--operator-packet", default=str(DEFAULT_OPERATOR_PACKET))
    parser.add_argument("--candidate-bounded-retest-plan", default=str(DEFAULT_CANDIDATE_BOUNDED_RETEST_PLAN))
    parser.add_argument("--candidate-bounded-retest-outcome", default=str(DEFAULT_CANDIDATE_BOUNDED_RETEST_OUTCOME))
    parser.add_argument("--validation-runner", default=str(DEFAULT_VALIDATION_RUNNER))
    parser.add_argument("--preflight-runner", default=str(DEFAULT_PREFLIGHT_RUNNER))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_paper_validation_start_report(
        repo_root=Path(args.repo_root),
        readiness_report=Path(args.readiness_report),
        operator_packet=Path(args.operator_packet),
        candidate_bounded_retest_plan=Path(args.candidate_bounded_retest_plan),
        candidate_bounded_retest_outcome=Path(args.candidate_bounded_retest_outcome),
        validation_runner=Path(args.validation_runner),
        preflight_runner=Path(args.preflight_runner),
        ledger_root=Path(args.ledger_root),
        data_root=Path(args.data_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_paper_validation_start_report(payload, Path(args.output_root)))


def _readiness_summary(root: Path, path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _relpath(path, root),
        "exists": path.exists(),
        "schema_version": str(payload.get("schema_version", "")),
        "status": str(payload.get("status", "missing") or "missing"),
        "paper_queue_status": str(payload.get("paper_queue_status", "locked") or "locked"),
        "paper_start_allowed": bool(payload.get("paper_start_allowed", False)),
        "paper_execution_authorized": bool(payload.get("paper_execution_authorized", False)),
        "live_status": str(payload.get("live_status", "unknown") or "unknown"),
        "next_required_action": str(payload.get("next_required_action", "repair_btc_paper_readiness_evidence") or ""),
        "manual_inputs_status": str(payload.get("manual_inputs_status", "awaiting_manual_inputs") or "awaiting_manual_inputs"),
        "paper_gate_manual_inputs_complete": bool(payload.get("paper_gate_manual_inputs_complete", False)),
        "required_manual_input_count": len(payload.get("required_manual_inputs", []))
        if isinstance(payload.get("required_manual_inputs"), list)
        else 0,
        "blocker_count": len(_list_of_strings(payload.get("blockers"))),
    }


def _manual_inputs_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "manual_inputs_status": str(payload.get("manual_inputs_status", "awaiting_manual_inputs") or "awaiting_manual_inputs"),
        "paper_gate_manual_inputs_complete": bool(payload.get("paper_gate_manual_inputs_complete", False)),
        "required_manual_inputs": _manual_input_statuses(payload.get("required_manual_inputs")),
        "fee_tier_status": _fee_tier_status(payload.get("fee_tier_status")),
    }


def _operator_manual_unblock(
    *,
    root: Path,
    path: Path,
    payload: Mapping[str, Any],
    manual_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    request = _mapping(payload.get("paper_gate_manual_inputs_request"))
    fee_request = _mapping(payload.get("fee_tier_overlay_request"))
    safety = _mapping(payload.get("safety"))
    manual_inputs_complete = bool(manual_inputs.get("paper_gate_manual_inputs_complete", False))
    packet_exists = path.exists()
    blockers: list[str] = []
    if not packet_exists and not manual_inputs_complete:
        blockers.append("btc_paper_validation_operator_packet_missing")
    blockers.extend(_operator_packet_safety_blockers(safety))
    blockers.extend(_operator_packet_capture_request_blockers(payload.get("capture_requests"), packet_exists=packet_exists))
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "packet_path": _relpath(path, root) if packet_exists else None,
        "packet_exists": packet_exists,
        "status": str(payload.get("status", "not_required" if manual_inputs_complete else "missing") or "missing"),
        "manual_inputs_status": str(
            payload.get(
                "manual_inputs_status",
                manual_inputs.get("manual_inputs_status", "manual_inputs_verified" if manual_inputs_complete else "awaiting_manual_inputs"),
            )
            or "awaiting_manual_inputs"
        ),
        "paper_gate_manual_inputs_complete": bool(
            payload.get("paper_gate_manual_inputs_complete", manual_inputs_complete)
        ),
        "required_manual_inputs": _manual_input_statuses(
            payload.get("required_manual_inputs", manual_inputs.get("required_manual_inputs"))
        ),
        "dry_run_command": str(request.get("dry_run_command", "")),
        "apply_command": str(request.get("apply_command", "")),
        "apply_and_validate_command": str(request.get("apply_and_validate_command", "")),
        "post_apply_rebuild_command": str(request.get("post_apply_rebuild_command", "")),
        "post_apply_validation_command": str(request.get("post_apply_validation_command", "")),
        "post_apply_readiness_command": str(request.get("post_apply_readiness_command", "")),
        "capture_requests": _capture_request_summaries(payload.get("capture_requests")),
        "fee_tier_dry_run_command": str(fee_request.get("dry_run_command", "")),
        "fee_tier_apply_command": str(fee_request.get("import_command", "")),
        "safety": {
            "api_key_required": bool(safety.get("api_key_required", False)),
            "private_endpoints_allowed": bool(safety.get("private_endpoints_allowed", False)),
            "order_endpoints_allowed": bool(safety.get("order_endpoints_allowed", False)),
            "paper_or_live_unlock_allowed": bool(safety.get("paper_or_live_unlock_allowed", False)),
        },
        "blockers": _dedupe(blockers),
    }


def _operator_packet_safety_blockers(safety: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if safety.get("api_key_required") is True:
        blockers.append("btc_paper_validation_operator_packet_api_key_required")
    if safety.get("private_endpoints_allowed") is True:
        blockers.append("btc_paper_validation_operator_packet_private_endpoints_allowed")
    if safety.get("order_endpoints_allowed") is True:
        blockers.append("btc_paper_validation_operator_packet_order_endpoints_allowed")
    if safety.get("writes_bundle_files_during_capture") is True:
        blockers.append("btc_paper_validation_operator_packet_writes_bundle_files_during_capture")
    if safety.get("strategy_retest_allowed") is True:
        blockers.append("btc_paper_validation_operator_packet_strategy_retest_allowed")
    if safety.get("paper_or_live_unlock_allowed") is True:
        blockers.append("btc_paper_validation_operator_packet_paper_or_live_unlock_allowed")
    return blockers


def _operator_packet_capture_request_blockers(value: object, *, packet_exists: bool) -> list[str]:
    if not packet_exists:
        return []
    if not isinstance(value, list) or not value:
        return ["btc_paper_validation_operator_packet_capture_requests_missing_or_invalid"]
    blockers: list[str] = []
    allowed = {
        "exchange_info": [
            _capture_request_allowlist_item(
                endpoint="GET /fapi/v1/exchangeInfo",
                url="https://fapi.binance.com/fapi/v1/exchangeInfo",
                output_file="exchange_info_raw.json",
                http_status_file="exchange_info_http_status.txt",
            ),
            _capture_request_allowlist_item(
                endpoint="GET /api/v5/public/instruments",
                url="https://www.okx.com/api/v5/public/instruments?instType=SWAP",
                output_file="exchange_info_raw.json",
                http_status_file="exchange_info_http_status.txt",
            ),
        ],
        "funding_info": [
            _capture_request_allowlist_item(
                endpoint="GET /fapi/v1/fundingInfo",
                url="https://fapi.binance.com/fapi/v1/fundingInfo",
                output_file="funding_info_raw.json",
                http_status_file="funding_info_http_status.txt",
            ),
            _capture_request_allowlist_item(
                endpoint="GET /api/v5/public/funding-rate",
                url="https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
                output_file="funding_info_raw.json",
                http_status_file="funding_info_http_status.txt",
            ),
        ],
    }
    forbidden_terms = ("x-mbx-apikey", "apikey", "account", "order", "position", "listenkey", "userdata")
    for item in value:
        if not isinstance(item, Mapping):
            blockers.append("btc_paper_validation_operator_packet_unsafe_capture_request")
            continue
        name = str(item.get("name", ""))
        expected_options = allowed.get(name, [])
        command = str(item.get("command", ""))
        combined = " ".join(
            [
                str(item.get("endpoint", "")),
                str(item.get("url", "")),
                command,
            ]
        ).lower()
        if not expected_options:
            blockers.append("btc_paper_validation_operator_packet_unsafe_capture_request")
            continue
        if int(item.get("required_http_status", 0) or 0) != 200:
            blockers.append("btc_paper_validation_operator_packet_unsafe_capture_request")
        if not any(_capture_request_matches(item, expected) for expected in expected_options):
            blockers.append("btc_paper_validation_operator_packet_unsafe_capture_request")
        if any(term in combined for term in forbidden_terms):
            blockers.append("btc_paper_validation_operator_packet_unsafe_capture_request")
    return _dedupe(blockers)


def _capture_request_allowlist_item(
    *,
    endpoint: str,
    url: str,
    output_file: str,
    http_status_file: str,
) -> dict[str, str]:
    return {
        "endpoint": endpoint,
        "url": url,
        "output_file": output_file,
        "http_status_file": http_status_file,
        "command": f'curl -sS -o {output_file} -w "%{{http_code}}\\n" "{url}" > {http_status_file}',
    }


def _capture_request_matches(item: Mapping[str, Any], expected: Mapping[str, str]) -> bool:
    return all(
        str(item.get(field, "")) == expected[field]
        for field in ("endpoint", "url", "output_file", "http_status_file", "command")
    )


def _capture_request_summaries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    requests: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        requests.append(
            {
                "name": str(item.get("name", "")),
                "endpoint": str(item.get("endpoint", "")),
                "url": str(item.get("url", "")),
                "command": str(item.get("command", "")),
                "output_file": str(item.get("output_file", "")),
                "http_status_file": str(item.get("http_status_file", "")),
                "required_http_status": int(item.get("required_http_status", 0) or 0),
            }
        )
    return requests


def _approved_review(payload: Mapping[str, Any]) -> dict[str, Any]:
    review = _mapping(payload.get("approved_paper_review"))
    approval = _mapping(review.get("approval"))
    return {
        "approved": bool(review.get("approved", False)),
        "paper_review_id": str(review.get("paper_review_id", "")),
        "status": str(review.get("status", "missing") or "missing"),
        "path": str(review.get("path", "")),
        "strategy_manifest_id": str(review.get("strategy_manifest_id", "")),
        "proposed_symbols": _list_of_strings(review.get("proposed_symbols")),
        "proposed_capital": _float_or_default(review.get("proposed_capital"), 0.0),
        "evidence_pack_path": str(review.get("evidence_pack_path", "")),
        "evidence_pack_exists": bool(review.get("evidence_pack_exists", False)),
        "approval": approval,
    }


def _candidate_bounded_retest_summary(
    *,
    root: Path,
    path: Path,
    payload: Mapping[str, Any],
    outcome_path: Path,
    outcome_payload: Mapping[str, Any],
) -> dict[str, Any]:
    execution = _mapping(payload.get("execution_plan"))
    retest_command = str(execution.get("retest_command", ""))
    readiness_command = str(execution.get("readiness_check_command", "make check-btc-candidate-bounded-retest-readiness"))
    outcome_status = str(outcome_payload.get("status", "missing") or "missing")
    outcome_next_action = str(outcome_payload.get("next_required_action", "") or "")
    repeat_allowed = bool(outcome_payload.get("same_retest_repeat_allowed", True))
    completed_failed = outcome_status == "completed_candidate_gate_failed"
    if completed_failed and not repeat_allowed:
        recommended_action = outcome_next_action or "design_new_fold_specific_hypothesis_or_select_better_candidate"
        recommended_command = ""
    else:
        recommended_action = "run_bounded_candidate_retest_after_data_cost"
        recommended_command = retest_command if retest_command else readiness_command
    return {
        "path": _relpath(path, root) if path.exists() else None,
        "exists": path.exists(),
        "status": str(payload.get("status", "missing") or "missing"),
        "retest_allowed": bool(payload.get("retest_allowed", False)),
        "execution_status": str(execution.get("status", "missing") or "missing"),
        "readiness_check_command": readiness_command,
        "retest_command": retest_command,
        "outcome_path": _relpath(outcome_path, root) if outcome_path.exists() else None,
        "outcome_exists": outcome_path.exists(),
        "outcome_status": outcome_status,
        "same_retest_repeat_allowed": repeat_allowed,
        "outcome_next_required_action": outcome_next_action,
        "recommended_action": recommended_action,
        "recommended_command": recommended_command,
        "blockers": _dedupe(_list_of_strings(payload.get("blockers")) + _list_of_strings(outcome_payload.get("blockers"))),
    }


def _unblock_sequence(
    *,
    readiness: Mapping[str, Any],
    operator_unblock: Mapping[str, Any],
    candidate_bounded_retest: Mapping[str, Any],
    approved_review: Mapping[str, Any],
    runtime: Mapping[str, Any],
    preflight_probe: Mapping[str, Any],
    ledger_session: Mapping[str, Any],
    ready: bool,
) -> list[dict[str, Any]]:
    requirements = _mapping(readiness.get("requirements"))
    manual_gate = _mapping(requirements.get("manual_input_gate"))
    data_gate = _mapping(requirements.get("data_source_gate"))
    cost_gate = _mapping(requirements.get("cost_ledger_gate"))
    candidate_gate = _mapping(requirements.get("candidate_gate"))
    review_gate = _mapping(requirements.get("paper_review_gate"))
    readiness_declares_ready = (
        str(readiness.get("status", "")) == "ready_for_paper_start"
        and bool(readiness.get("paper_start_allowed", False))
        and bool(readiness.get("paper_execution_authorized", False))
    )
    manual_complete = _gate_complete(manual_gate) or bool(readiness.get("paper_gate_manual_inputs_complete", False))
    data_cost_complete = (_gate_complete(data_gate) and _gate_complete(cost_gate)) or ready or readiness_declares_ready
    candidate_complete = _gate_complete(candidate_gate) or ready or readiness_declares_ready
    review_complete = (
        (_gate_complete(review_gate) and bool(approved_review.get("approved", False)))
        or ready
        or (readiness_declares_ready and bool(approved_review.get("approved", False)))
    )
    runtime_complete = bool(
        runtime.get("runner_supports_btc_usdm_perpetual", False)
        and runtime.get("preflight_supports_btc_usdm_perpetual", False)
    )
    preflight_complete = bool(preflight_probe.get("ready_without_start_report", False))
    ledger_status = str(ledger_session.get("status", "dirty") or "dirty")
    paper_start_command = APPROVED_RESUME_COMMAND if ledger_status == "resumable" else APPROVED_START_COMMAND
    paper_start_action = "resume_paper_validation" if ledger_status == "resumable" else "start_paper_validation"
    operator_blockers = _list_of_strings(operator_unblock.get("blockers"))
    manual_step_complete = manual_complete and not operator_blockers
    candidate_action = "none" if candidate_complete else str(
        candidate_bounded_retest.get("recommended_action", "run_bounded_candidate_retest_after_data_cost") or ""
    )
    candidate_command = "" if candidate_complete else str(candidate_bounded_retest.get("recommended_command", "") or "")
    raw_steps = [
        {
            "order": 1,
            "gate": "manual_paper_gate_inputs",
            "status": "complete" if manual_step_complete else "blocked",
            "action": "none" if manual_step_complete else "complete_btc_manual_paper_gate_inputs",
            "command": "" if manual_step_complete else str(operator_unblock.get("apply_and_validate_command", "")),
            "evidence": [_evidence_path(manual_gate, "operator_packet")],
            "blockers": _dedupe(_gate_blockers(manual_gate) + operator_blockers),
        },
        {
            "order": 2,
            "gate": "perpetual_data_cost_evidence",
            "status": "complete" if data_cost_complete else "blocked",
            "action": "none" if data_cost_complete else "complete_btc_perpetual_data_cost_evidence",
            "command": "" if data_cost_complete else "make validate-btc-data-cost-repair",
            "evidence": [
                _evidence_path(data_gate, "data_status"),
                _evidence_path(data_gate, "provider_verification"),
                _evidence_path(cost_gate, "cost_model"),
                _evidence_path(cost_gate, "funding_ledger"),
            ],
            "blockers": _dedupe(_gate_blockers(data_gate) + _gate_blockers(cost_gate)),
        },
        {
            "order": 3,
            "gate": "candidate_metric_gate",
            "status": "complete" if candidate_complete else "blocked",
            "action": candidate_action,
            "command": candidate_command,
            "evidence": [
                _evidence_path(candidate_gate, "candidate_gate"),
                _evidence_path(candidate_gate, "candidate_metric_repair"),
                str(candidate_bounded_retest.get("path", "") or ""),
                str(candidate_bounded_retest.get("outcome_path", "") or ""),
            ],
            "blockers": _dedupe(_gate_blockers(candidate_gate) + _list_of_strings(candidate_bounded_retest.get("blockers"))),
        },
        {
            "order": 4,
            "gate": "human_paper_review",
            "status": "complete" if review_complete else "pending_review",
            "action": "none" if review_complete else "human_paper_review_approval",
            "command": "",
            "evidence": [str(approved_review.get("path", ""))],
            "blockers": _gate_blockers(review_gate),
        },
        {
            "order": 5,
            "gate": "paper_validation_start",
            "status": "ready" if ready else "blocked",
            "action": paper_start_action if ready else "wait_for_prior_gates",
            "command": paper_start_command if ready else "",
            "evidence": [
                str(runtime.get("validation_runner_path", "")),
                str(runtime.get("preflight_runner_path", "")),
            ],
            "blockers": [] if ready else _paper_start_gate_blockers(runtime_complete, preflight_complete, ledger_session),
        },
    ]
    first_open = next((step["order"] for step in raw_steps if step["status"] != "complete"), 0)
    return [
        {
            **step,
            "required_before_paper_start": True,
            "is_next_action": step["order"] == first_open,
            "evidence": [item for item in step["evidence"] if item],
            "blockers": _dedupe(_list_of_strings(step["blockers"])),
        }
        for step in raw_steps
    ]


def _gate_complete(gate: Mapping[str, Any]) -> bool:
    return str(gate.get("status", "missing") or "missing") == "complete"


def _gate_blockers(gate: Mapping[str, Any]) -> list[str]:
    return _list_of_strings(gate.get("blockers"))


def _evidence_path(gate: Mapping[str, Any], name: str) -> str:
    evidence = _mapping(gate.get("evidence"))
    return str(evidence.get(name, "") or "")


def _paper_start_gate_blockers(
    runtime_complete: bool,
    preflight_complete: bool,
    ledger_session: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not runtime_complete:
        blockers.append("btc_paper_validation_runtime_missing")
    if not preflight_complete:
        blockers.append("btc_paper_validation_preflight_probe_not_pass")
    blockers.extend(_ledger_session_blockers(ledger_session))
    return blockers


def _ledger_session_summary(*, root: Path, ledger_root: Path) -> dict[str, Any]:
    ledger = _resolve(root, ledger_root)
    state_path = ledger / "validation_state.json"
    state_exists = state_path.exists()
    state_payload = _read_json(state_path)
    state_valid = _validation_state_valid(state_payload) if state_exists else False
    latest_daily = _latest_daily_result(state_payload)
    latest_reconciliation_status = str(latest_daily.get("reconciliation_status", "") or "")
    artifact = _ledger_reconciliation_artifact_status(latest_daily, root=root)
    history = _validation_state_history_status(state_payload, root=root)
    latest_clean = bool(latest_daily.get("clean", True)) if latest_daily else None
    reconciliation_clean = (
        (not latest_daily and not (state_valid and int(state_payload.get("days_completed", 0) or 0) > 0) and history["ok"])
        or (
            bool(latest_daily.get("clean", False))
            and latest_reconciliation_status in {"clean", "ok", "pass", "passed", "complete"}
            and artifact["ok"]
            and history["ok"]
        )
    )
    session_manifests = _session_manifest_paths(ledger)
    runtime_records = _runtime_record_files(ledger)
    in_progress_markers = _in_progress_marker_paths(ledger)
    in_progress_marker_details = _in_progress_marker_details(ledger, root=root)
    start_lock = _ledger_start_lock_summary(ledger, root=root)
    if in_progress_markers:
        status = "recovery_required"
    elif state_exists and not state_valid:
        status = "dirty"
    elif runtime_records and not state_valid:
        status = "recovery_required"
    elif state_valid or session_manifests:
        status = "resumable" if state_valid else "recovery_required"
    else:
        status = "clean_start"
    return {
        "ledger_root": _relpath(ledger, root),
        "status": status,
        "validation_state_exists": state_exists,
        "validation_state_valid": state_valid,
        "session_manifest_count": len(session_manifests),
        "runtime_record_files": [_relpath(path, root) for path in runtime_records],
        "in_progress_cycle_markers": [_relpath(path, root) for path in in_progress_markers],
        "in_progress_cycle_marker_details": in_progress_marker_details,
        "start_lock_status": start_lock["status"],
        "start_lock_path": start_lock["path"],
        "start_lock_claimable": start_lock["claimable"],
        "latest_reconciliation_status": latest_reconciliation_status,
        "latest_reconciliation_artifact_path": artifact["path"],
        "latest_reconciliation_artifact_hash": artifact["hash"],
        "latest_reconciliation_artifact_verified": artifact["ok"],
        "latest_reconciliation_artifact_blockers": _dedupe([*artifact["blockers"], *history["blockers"]]),
        "latest_clean": latest_clean,
        "reconciliation_clean": reconciliation_clean,
    }


def _ledger_session_blockers(session: Mapping[str, Any]) -> list[str]:
    status = str(session.get("status", "dirty") or "dirty")
    blockers: list[str] = []
    if session.get("start_lock_status") == "active":
        blockers.append("btc_paper_validation_ledger_start_lock_active")
    if status == "dirty":
        blockers.append("btc_paper_validation_ledger_session_dirty")
    elif session.get("reconciliation_clean") is False:
        blockers.append("btc_paper_validation_reconciliation_not_clean")
    if blockers:
        return blockers
    if status in {"clean_start", "resumable"}:
        return []
    if status == "recovery_required":
        return ["btc_paper_validation_ledger_recovery_required"]
    return ["btc_paper_validation_ledger_session_dirty"]


def _json_file_is_object(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, Mapping)


def _latest_daily_result(state: Mapping[str, Any]) -> dict[str, Any]:
    daily = state.get("daily_results")
    if not isinstance(daily, list) or not daily:
        return {}
    latest = daily[-1]
    return dict(latest) if isinstance(latest, Mapping) else {}


def _ledger_reconciliation_artifact_status(latest: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    if not latest:
        return {"ok": True, "path": "", "hash": "", "blockers": []}
    artifact_path = _resolve_review_path(root, latest.get("ledger_reconciliation_artifact_path"))
    expected_hash = str(latest.get("ledger_reconciliation_artifact_hash", "") or "")
    blockers: list[str] = []
    payload: dict[str, Any] = {}
    if artifact_path is None:
        blockers.append("btc_ledger_reconciliation_artifact_path_missing")
    elif not artifact_path.exists():
        blockers.append("btc_ledger_reconciliation_artifact_file_missing")
    else:
        payload = _read_json(artifact_path)
        if not payload:
            blockers.append("btc_ledger_reconciliation_artifact_invalid_json")
    if not _is_sha256(expected_hash):
        blockers.append("btc_ledger_reconciliation_artifact_hash_missing_or_invalid")
    if payload:
        artifact_hash = str(payload.get("artifact_hash", "") or "")
        if not _is_sha256(artifact_hash):
            blockers.append("btc_ledger_reconciliation_artifact_embedded_hash_invalid")
        elif expected_hash and artifact_hash != expected_hash:
            blockers.append("btc_ledger_reconciliation_artifact_hash_mismatch")
        if artifact_hash and compute_ledger_reconciliation_artifact_hash(payload) != artifact_hash:
            blockers.append("btc_ledger_reconciliation_artifact_payload_hash_mismatch")
        if _mapping(payload.get("integrity")).get("passed") is not True:
            blockers.append("btc_ledger_reconciliation_artifact_integrity_not_pass")
        summary = _mapping(_mapping(payload.get("reconciliation")).get("summary"))
        if summary.get("passed") is not True:
            blockers.append("btc_ledger_reconciliation_artifact_reconciliation_not_pass")
    return {
        "ok": not blockers,
        "path": _relpath(artifact_path, root) if artifact_path else "",
        "hash": expected_hash,
        "blockers": _dedupe(blockers),
    }


def _validation_state_history_status(state: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    if not state:
        return {"ok": True, "blockers": []}
    blockers: list[str] = []
    completed = state.get("completed_cycle_keys")
    daily = state.get("daily_results")
    days_completed = _nonnegative_int(state.get("days_completed"))
    if not isinstance(completed, list) or not all(isinstance(item, str) and item for item in completed):
        blockers.append("btc_validation_state_completed_cycle_keys_invalid")
        completed_keys: list[str] = []
    else:
        completed_keys = [str(item) for item in completed]
    if not isinstance(daily, list) or not all(isinstance(item, Mapping) for item in daily):
        blockers.append("btc_validation_state_daily_results_invalid")
        daily_results: list[Mapping[str, Any]] = []
    else:
        daily_results = [dict(item) for item in daily]
    if days_completed is None:
        blockers.append("btc_validation_state_days_completed_invalid")
    elif days_completed != len(daily_results) or days_completed != len(completed_keys):
        blockers.append("btc_validation_state_cycle_counts_mismatch")
    if len(set(completed_keys)) != len(completed_keys):
        blockers.append("btc_validation_state_completed_cycle_keys_duplicate")
    daily_cycle_keys = [str(item.get("cycle_key", "") or "") for item in daily_results]
    if any(not key for key in daily_cycle_keys):
        blockers.append("btc_validation_state_daily_cycle_key_missing")
    if len(set(key for key in daily_cycle_keys if key)) != len([key for key in daily_cycle_keys if key]):
        blockers.append("btc_validation_state_daily_cycle_keys_duplicate")
    if set(completed_keys) != set(key for key in daily_cycle_keys if key):
        blockers.append("btc_validation_state_cycle_keys_mismatch")
    for item in daily_results:
        status = str(item.get("reconciliation_status", "missing") or "missing")
        if not str(item.get("run_id", "") or ""):
            blockers.append("btc_validation_state_daily_run_id_missing")
        if item.get("clean") is not True:
            blockers.append("btc_validation_state_daily_not_clean")
        if item.get("equity_consistent") is not True:
            blockers.append("btc_validation_state_daily_equity_inconsistent")
        if status not in {"clean", "ok", "pass", "passed", "complete"}:
            blockers.append("btc_validation_state_daily_reconciliation_not_clean")
        artifact = _ledger_reconciliation_artifact_status(item, root=root)
        if not artifact["ok"]:
            blockers.append("btc_validation_state_daily_reconciliation_artifact_invalid")
            blockers.extend(str(blocker) for blocker in artifact["blockers"])
    return {"ok": not blockers, "blockers": _dedupe(blockers)}


def _resolve_review_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _is_sha256(raw: str) -> bool:
    return len(raw) == 64 and all(char in "0123456789abcdefABCDEF" for char in raw)


def _validation_state_valid(state: Mapping[str, Any]) -> bool:
    if not state:
        return False
    completed = state.get("completed_cycle_keys")
    daily = state.get("daily_results")
    if not isinstance(completed, list) or not all(isinstance(item, str) and item for item in completed):
        return False
    if not isinstance(daily, list) or not all(isinstance(item, Mapping) for item in daily):
        return False
    days_required = _nonnegative_int(state.get("days_required"))
    days_completed = _nonnegative_int(state.get("days_completed"))
    consecutive = _nonnegative_int(state.get("consecutive_clean_days"))
    return (
        state.get("schema_version") == "btc_paper_validation_state_v1"
        and state.get("asset") == "btc"
        and state.get("symbol") == "BTCUSDT"
        and state.get("market_type") == "usds_m_perpetual"
        and days_required is not None
        and days_required > 0
        and days_completed is not None
        and consecutive is not None
        and consecutive <= days_completed
    )


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _session_manifest_paths(ledger: Path) -> list[Path]:
    paths = [ledger / "audit" / "paper_session_manifest.json"]
    history = ledger / "audit" / "paper_session_manifests"
    if history.exists():
        paths.extend(sorted(path for path in history.glob("*.json") if path.is_file()))
    return [path for path in paths if path.exists()]


def _runtime_record_files(ledger: Path) -> list[Path]:
    return [
        ledger / name
        for name in ("orders.jsonl", "fills.jsonl", "portfolio_snapshots.jsonl", "events.jsonl")
        if (ledger / name).exists() and (ledger / name).stat().st_size > 0
    ]


def _in_progress_marker_paths(ledger: Path) -> list[Path]:
    marker_dir = ledger / "audit" / "paper_validation_in_progress"
    if not marker_dir.exists():
        return []
    return sorted(path for path in marker_dir.glob("*.json") if path.is_file())


def _in_progress_marker_details(ledger: Path, *, root: Path) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for path in _in_progress_marker_paths(ledger):
        payload, parse_ok = _read_marker_json(path)
        blockers = [] if parse_ok else ["btc_paper_validation_in_progress_marker_invalid_json"]
        details.append(
            {
                "path": _relpath(path, root),
                "parse_ok": parse_ok,
                "schema_version": str(payload.get("schema_version", "")),
                "run_id": str(payload.get("run_id", "")),
                "cycle_key": str(payload.get("cycle_key", "")),
                "status": str(payload.get("status", "unknown") or "unknown"),
                "start": str(payload.get("start", "")),
                "end": str(payload.get("end", "")),
                "blockers": blockers,
            }
        )
    return details


def _read_marker_json(path: Path) -> tuple[dict[str, Any], bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, False
    return (dict(payload), True) if isinstance(payload, Mapping) else ({}, False)


def _ledger_start_lock_summary(ledger: Path, *, root: Path) -> dict[str, Any]:
    lock = ledger / "audit" / LEDGER_START_LOCK_NAME
    if not lock.exists() or not lock.is_file():
        return {"status": "absent", "path": "", "claimable": True}
    try:
        fd = os.open(lock, os.O_RDWR)
    except OSError:
        return {"status": "active", "path": _relpath(lock, root), "claimable": False}
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            return {"status": "active", "path": _relpath(lock, root), "claimable": False}
        return {"status": "stale", "path": _relpath(lock, root), "claimable": True}
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def _runtime_contract(
    *,
    root: Path,
    validation_runner: Path,
    preflight_runner: Path,
    ledger_root: Path,
    data_root: Path,
) -> dict[str, Any]:
    runner_path = _resolve(root, validation_runner)
    preflight_path = _resolve(root, preflight_runner)
    default_runner_path = _resolve(root, DEFAULT_VALIDATION_RUNNER)
    default_preflight_path = _resolve(root, DEFAULT_PREFLIGHT_RUNNER)
    runner_source = runner_path.read_text(encoding="utf-8") if runner_path.exists() else ""
    preflight_source = preflight_path.read_text(encoding="utf-8") if preflight_path.exists() else ""
    checks = {
        "validation_runner_exists": runner_path.exists(),
        "preflight_runner_exists": preflight_path.exists(),
        "validation_runner_is_approved_default": _same_resolved_path(runner_path, default_runner_path),
        "preflight_runner_is_approved_default": _same_resolved_path(preflight_path, default_preflight_path),
        "validation_runner_declares_btc_contract": RUNTIME_CONTRACT in runner_source,
        "validation_runner_declares_usds_m_perpetual": "usds_m_perpetual" in runner_source,
        "validation_runner_declares_btcusdt": "BTCUSDT" in runner_source,
        "validation_runner_avoids_equity_only_loader": "asset_class=equity" not in runner_source,
        "preflight_runner_declares_btc_contract": PREFLIGHT_CONTRACT in preflight_source,
        "preflight_runner_declares_usds_m_perpetual": "usds_m_perpetual" in preflight_source,
        "preflight_runner_declares_btcusdt": "BTCUSDT" in preflight_source,
        "preflight_runner_avoids_equity_only_loader": "asset_class=equity" not in preflight_source,
    }
    runner_supports = all(
        checks[name]
        for name in (
            "validation_runner_exists",
            "validation_runner_is_approved_default",
            "validation_runner_declares_btc_contract",
            "validation_runner_declares_usds_m_perpetual",
            "validation_runner_declares_btcusdt",
            "validation_runner_avoids_equity_only_loader",
        )
    )
    preflight_supports = all(
        checks[name]
        for name in (
            "preflight_runner_exists",
            "preflight_runner_is_approved_default",
            "preflight_runner_declares_btc_contract",
            "preflight_runner_declares_usds_m_perpetual",
            "preflight_runner_declares_btcusdt",
            "preflight_runner_avoids_equity_only_loader",
        )
    )
    return {
        "validation_runner_path": _relpath(runner_path, root),
        "preflight_runner_path": _relpath(preflight_path, root),
        "ledger_root": _relpath(_resolve(root, ledger_root), root),
        "data_root": _relpath(_resolve(root, data_root), root),
        "runtime_contract": RUNTIME_CONTRACT,
        "preflight_contract": PREFLIGHT_CONTRACT,
        "runner_supports_btc_usdm_perpetual": runner_supports,
        "preflight_supports_btc_usdm_perpetual": preflight_supports,
        "checks": checks,
    }


def _readiness_blockers(
    readiness: Mapping[str, Any],
    approved_review: Mapping[str, Any],
    raw_readiness: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not readiness["exists"]:
        blockers.append("btc_paper_validation_readiness_report_missing")
    if readiness["status"] != "ready_for_paper_start":
        blockers.append("btc_paper_validation_readiness_not_ready")
    if not readiness["paper_start_allowed"]:
        blockers.append("btc_paper_validation_start_not_allowed")
    if not readiness["paper_execution_authorized"]:
        blockers.append("btc_paper_validation_execution_not_authorized")
    if readiness["live_status"] != "frozen":
        blockers.append("btc_paper_validation_live_not_frozen")
    if not approved_review["approved"]:
        blockers.append("btc_paper_validation_approved_review_missing")
    if approved_review["approved"] and not approved_review["evidence_pack_exists"]:
        blockers.append("btc_paper_validation_evidence_pack_missing")
    blockers.extend(_approved_review_blockers(approved_review))
    blockers.extend(_list_of_strings(raw_readiness.get("blockers")))
    return blockers


def _approved_review_blockers(approved_review: Mapping[str, Any]) -> list[str]:
    approval = _mapping(approved_review.get("approval"))
    gate_snapshot = _mapping(approval.get("gate_snapshot"))
    proposed_symbols = _normalized_symbols(_list_of_strings(approved_review.get("proposed_symbols")))
    proposed_capital = _float_or_default(approved_review.get("proposed_capital"), 0.0)
    approval_candidate = str(approval.get("candidate_id", "") or "")
    snapshot_candidate = str(gate_snapshot.get("candidate_id", "") or "")
    blockers: list[str] = []
    if str(approved_review.get("status", "") or "") != "APPROVED_FOR_PAPER_ONLY":
        blockers.append("btc_paper_validation_approved_review_status_not_paper_only")
    if proposed_symbols != ["BTCUSDT"]:
        blockers.append("btc_paper_validation_approved_review_symbol_scope_mismatch")
    if proposed_capital <= 0:
        blockers.append("btc_paper_validation_approved_review_proposed_capital_missing")
    if approval.get("valid") is not True:
        blockers.append("btc_paper_validation_approved_review_approval_invalid")
    if approval.get("schema_version") != "paper_review_approval_v1":
        blockers.append("btc_paper_validation_approved_review_approval_schema_invalid")
    if not str(approval.get("reviewer", "") or "").strip():
        blockers.append("btc_paper_validation_approved_review_reviewer_missing")
    if not _utc_approval_timestamp(approval.get("timestamp")):
        blockers.append("btc_paper_validation_approved_review_timestamp_invalid")
    if not approval_candidate:
        blockers.append("btc_paper_validation_approved_review_candidate_missing")
    if _list_of_strings(approval.get("blockers")):
        blockers.append("btc_paper_validation_approved_review_approval_has_blockers")
    if not gate_snapshot:
        blockers.append("btc_paper_validation_approved_review_gate_snapshot_missing")
    elif snapshot_candidate != approval_candidate:
        blockers.append("btc_paper_validation_approved_review_candidate_snapshot_mismatch")
    if gate_snapshot and gate_snapshot.get("paper_execution_authorized") is not False:
        blockers.append("btc_paper_validation_approved_review_scope_not_record_only")
    if gate_snapshot and gate_snapshot.get("authorization_scope") != "human_review_only":
        blockers.append("btc_paper_validation_approved_review_scope_not_human_review_only")
    return blockers


def _preflight_probe(
    *,
    root: Path,
    runtime: Mapping[str, Any],
    preflight_runner: Path,
    ledger_root: Path,
    data_root: Path,
) -> dict[str, Any]:
    if not runtime.get("preflight_supports_btc_usdm_perpetual", False):
        return {
            "contract": PREFLIGHT_CONTRACT,
            "command": PREFLIGHT_PROBE_COMMAND,
            "start_report_ready_required": False,
            "status": "NOT_RUN",
            "ready_without_start_report": False,
            "exit_code": None,
            "blocking_reasons": [],
            "error": "btc_paper_validation_preflight_contract_not_available",
        }
    runner = _resolve(root, preflight_runner)
    cmd = [
        "python3",
        str(runner),
        "--repo-root",
        ".",
        "--symbols",
        "BTCUSDT",
        "--market-type",
        "usds_m_perpetual",
        "--ledger-root",
        str(ledger_root),
        "--data-root",
        str(data_root),
        "--no-start-report-ready-required",
        "--json",
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return {
            "contract": PREFLIGHT_CONTRACT,
            "command": PREFLIGHT_PROBE_COMMAND,
            "start_report_ready_required": False,
            "status": "ERROR",
            "ready_without_start_report": False,
            "exit_code": None,
            "blocking_reasons": ["btc_paper_validation_preflight_probe_error"],
            "error": f"{type(exc).__name__}: {exc}",
        }
    payload = _json_from_stdout(completed.stdout)
    if not payload:
        return {
            "contract": PREFLIGHT_CONTRACT,
            "command": PREFLIGHT_PROBE_COMMAND,
            "start_report_ready_required": False,
            "status": "ERROR",
            "ready_without_start_report": False,
            "exit_code": completed.returncode,
            "blocking_reasons": ["btc_paper_validation_preflight_probe_invalid_json"],
            "error": (completed.stderr or completed.stdout).strip()[:500],
        }
    status = str(payload.get("status", "ERROR") or "ERROR")
    blocking = _list_of_strings(payload.get("blocking_reasons"))
    return {
        "contract": str(payload.get("schema_version", PREFLIGHT_CONTRACT) or PREFLIGHT_CONTRACT),
        "command": PREFLIGHT_PROBE_COMMAND,
        "start_report_ready_required": False,
        "status": status,
        "ready_without_start_report": status == "PASS" and not blocking and completed.returncode == 0,
        "exit_code": completed.returncode,
        "blocking_reasons": blocking,
        "error": "",
    }


def _preflight_probe_blockers(probe: Mapping[str, Any]) -> list[str]:
    status = str(probe.get("status", "ERROR") or "ERROR")
    if status == "NOT_RUN":
        return []
    if probe.get("ready_without_start_report") is True:
        return []
    return _dedupe(["btc_paper_validation_preflight_probe_not_pass", *_list_of_strings(probe.get("blocking_reasons"))])


def _runtime_blockers(runtime: Mapping[str, Any]) -> list[str]:
    checks = _mapping(runtime.get("checks"))
    blockers: list[str] = []
    if not checks.get("validation_runner_exists", False):
        blockers.append("btc_paper_validation_runtime_missing")
    else:
        if not checks.get("validation_runner_is_approved_default", False):
            blockers.append("btc_paper_validation_unapproved_validation_runner")
        if not checks.get("validation_runner_declares_btc_contract", False):
            blockers.append("btc_paper_validation_runtime_contract_missing")
        if not checks.get("validation_runner_declares_usds_m_perpetual", False):
            blockers.append("btc_paper_validation_runtime_market_type_missing")
        if not checks.get("validation_runner_declares_btcusdt", False):
            blockers.append("btc_paper_validation_runtime_symbol_missing")
        if not checks.get("validation_runner_avoids_equity_only_loader", False):
            blockers.append("btc_paper_validation_runtime_equity_only_loader_present")
    if not checks.get("preflight_runner_exists", False):
        blockers.append("btc_paper_validation_preflight_missing")
    else:
        if not checks.get("preflight_runner_is_approved_default", False):
            blockers.append("btc_paper_validation_unapproved_preflight_runner")
        if not checks.get("preflight_runner_declares_btc_contract", False):
            blockers.append("btc_paper_validation_preflight_contract_missing")
        if not checks.get("preflight_runner_declares_usds_m_perpetual", False):
            blockers.append("btc_paper_validation_preflight_market_type_missing")
        if not checks.get("preflight_runner_declares_btcusdt", False):
            blockers.append("btc_paper_validation_preflight_symbol_missing")
        if not checks.get("preflight_runner_avoids_equity_only_loader", False):
            blockers.append("btc_paper_validation_preflight_equity_only_loader_present")
    return blockers


def _next_required_action(
    readiness: Mapping[str, Any],
    runtime: Mapping[str, Any],
    ledger_session: Mapping[str, Any],
    operator_unblock: Mapping[str, Any],
    ready: bool,
) -> str:
    if ready:
        return "resume_paper_validation" if ledger_session.get("status") == "resumable" else "start_paper_validation"
    if "btc_paper_validation_operator_packet_missing" in _list_of_strings(operator_unblock.get("blockers")):
        return "rebuild_btc_paper_readiness_chain"
    if _list_of_strings(operator_unblock.get("blockers")):
        return "repair_btc_manual_metadata_operator_packet"
    if readiness["status"] != "ready_for_paper_start":
        action = str(readiness.get("next_required_action", "repair_btc_paper_readiness_evidence") or "")
        return action if action and action != "start_paper_validation" else "repair_btc_paper_readiness_evidence"
    if not runtime["runner_supports_btc_usdm_perpetual"] or not runtime["preflight_supports_btc_usdm_perpetual"]:
        return "implement_btc_paper_validation_runtime"
    return "repair_btc_paper_validation_start_evidence"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _manual_input_statuses(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "name": str(item.get("name", "")),
                "required_for": str(item.get("required_for", "")),
                "status": str(item.get("status", "awaiting_capture") or "awaiting_capture"),
                "action": str(
                    item.get("action", "manual_capture_from_allowed_network") or "manual_capture_from_allowed_network"
                ),
                "blockers": _list_of_strings(item.get("blockers")),
            }
        )
    return result


def _fee_tier_status(value: object) -> dict[str, Any]:
    fee_tier = _mapping(value)
    return {
        "cost_model_report": fee_tier.get("cost_model_report"),
        "cost_model_status": str(fee_tier.get("cost_model_status", "missing") or "missing"),
        "fee_tier_verified": bool(fee_tier.get("fee_tier_verified", False)),
        "manual_capture_required": bool(fee_tier.get("manual_capture_required", True)),
        "maker_fee_bps": _float_or_none(fee_tier.get("maker_fee_bps")),
        "taker_fee_bps": _float_or_none(fee_tier.get("taker_fee_bps")),
        "fee_tier_import_report_verified": bool(fee_tier.get("fee_tier_import_report_verified", False)),
        "fee_blockers": _list_of_strings(fee_tier.get("fee_blockers")),
    }


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _float_or_default(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalized_symbols(values: list[str]) -> list[str]:
    return sorted({str(item).strip().upper() for item in values if str(item).strip()})


def _utc_capture_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _utc_approval_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
