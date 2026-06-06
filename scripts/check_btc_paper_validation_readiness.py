#!/usr/bin/env python3
"""Read-only preflight for BTC USD-M paper validation.

Contract marker: btc_paper_validation_preflight_v1

This preflight is intentionally separate from the generic equity paper
validation checks. BTC paper validation must use governed USD-M perpetual
evidence and must not fall through to the equity data path.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash
from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_provider


SCHEMA_VERSION = "btc_paper_validation_preflight_v1"
SYMBOL = "BTCUSDT"
MARKET_TYPE = "usds_m_perpetual"
DATA_STATUS_SCHEMA_VERSION = "btc_data_status_report_v1"
PROVIDER_SCHEMA_VERSION = "btc_perpetual_provider_verification_report_v1"
BUNDLE_PREFLIGHT_SCHEMA_VERSION = "btc_perpetual_bundle_preflight_report_v1"
COST_MODEL_SCHEMA_VERSION = "btc_cost_model_contract_v1"
CANDIDATE_GATE_SCHEMA_VERSION = "btc_candidate_gate_audit_report_v1"
CANDIDATE_METRIC_REPAIR_SCHEMA_VERSION = "btc_candidate_metric_repair_report_v1"
DEFAULT_READINESS_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json")
DEFAULT_START_REPORT = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json")
DEFAULT_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
DEFAULT_PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DEFAULT_MANUAL_METADATA_IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
DEFAULT_BUNDLE_PREFLIGHT = Path("artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json")
DEFAULT_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
DEFAULT_CANDIDATE_GATE = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")
DEFAULT_CANDIDATE_METRIC_REPAIR = Path("artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_LEDGER_ROOT = Path("data/paper_ledger/btc")
DEFAULT_DATA_ROOT = Path("data")
MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER = ".btc_manual_metadata_import_in_progress.json"
LEDGER_START_LOCK_NAME = "btc_paper_validation_start.lock.json"
DEFAULT_INTERVAL = "1h"
APPROVED_START_ARGV = [
    "python3",
    "scripts/run_btc_paper_validation.py",
    "--repo-root",
    ".",
    "--symbols",
    "BTCUSDT",
    "--market-type",
    "usds_m_perpetual",
    "--ledger-root",
    "data/paper_ledger/btc",
    "--data-root",
    "data",
]
APPROVED_RESUME_ARGV = [*APPROVED_START_ARGV, "--resume"]
APPROVED_PREFLIGHT_ARGV = [
    "python3",
    "scripts/check_btc_paper_validation_readiness.py",
    "--repo-root",
    ".",
    "--symbols",
    "BTCUSDT",
    "--market-type",
    "usds_m_perpetual",
    "--ledger-root",
    "data/paper_ledger/btc",
    "--data-root",
    "data",
    "--json",
]
APPROVED_REPORT_REBUILD_COMMAND = "python3 scripts/build_btc_paper_validation_start_report.py"


def check_btc_paper_validation_readiness(
    *,
    repo_root: Path | None = None,
    symbols: list[str] | None = None,
    market_type: str = MARKET_TYPE,
    interval: str = DEFAULT_INTERVAL,
    ledger_root: Path | None = None,
    data_root: Path | None = None,
    readiness_report: Path | None = None,
    start_report: Path | None = None,
    data_status_report: Path | None = None,
    provider_report: Path | None = None,
    bundle_preflight_report: Path | None = None,
    cost_model_report: Path | None = None,
    candidate_gate_report: Path | None = None,
    candidate_metric_repair_report: Path | None = None,
    config_path: Path | None = None,
    require_start_report_ready: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    requested_symbols = _normalized_symbols(symbols or [SYMBOL])
    readiness_path = _resolve(root, readiness_report or DEFAULT_READINESS_REPORT)
    start_path = _resolve(root, start_report or DEFAULT_START_REPORT)
    data_status_path = _resolve(root, data_status_report or DEFAULT_DATA_STATUS)
    provider_path = _resolve(root, provider_report or DEFAULT_PROVIDER_VERIFICATION)
    bundle_path = _resolve(root, bundle_preflight_report or DEFAULT_BUNDLE_PREFLIGHT)
    cost_path = _resolve(root, cost_model_report or DEFAULT_COST_MODEL)
    candidate_path = _resolve(root, candidate_gate_report or DEFAULT_CANDIDATE_GATE)
    candidate_metric_repair_path = _resolve(root, candidate_metric_repair_report or DEFAULT_CANDIDATE_METRIC_REPAIR)
    config_abs = _resolve(root, config_path or DEFAULT_CONFIG)
    ledger = _resolve(root, ledger_root or DEFAULT_LEDGER_ROOT)
    data = _resolve(root, data_root or DEFAULT_DATA_ROOT)

    readiness = _read_json(readiness_path)
    start = _read_json(start_path)
    data_status = _read_json(data_status_path)
    provider = _read_json(provider_path)
    bundle_preflight = _read_json(bundle_path)
    cost = _read_json(cost_path)
    candidate = _read_json(candidate_path)
    candidate_metric_repair = _read_json(candidate_metric_repair_path)
    bundle_dir = _selected_bundle_dir(root, config_abs)
    bundle_manifest = _read_json(bundle_dir / "btc_perpetual_bundle_manifest.json") if bundle_dir else {}
    interval_file = bundle_dir / f"klines_{interval}.csv" if bundle_dir else None
    interval_summary = _interval_file_summary(interval_file, interval=interval)
    approved_review = _mapping(readiness.get("approved_paper_review"))
    approval = _mapping(approved_review.get("approval"))
    start_report_blockers = _start_report_blockers(start)

    checks = [
        _check(
            "symbol_scope",
            requested_symbols == [SYMBOL],
            f"symbols={','.join(requested_symbols) or '(missing)'} required={SYMBOL}",
        ),
        _check("market_type", market_type == MARKET_TYPE, f"market_type={market_type} required={MARKET_TYPE}"),
        _check(
            "readiness_report",
            _readiness_ready(readiness),
            f"status={readiness.get('status', 'missing')} paper_start_allowed={readiness.get('paper_start_allowed', False)}",
            readiness_path,
        ),
        _check(
            "start_report",
            (not require_start_report_ready) or not start_report_blockers,
            (
                f"required={require_start_report_ready} status={start.get('status', 'missing')} "
                f"paper_start_allowed={start.get('paper_start_allowed', False)} "
                f"blockers={','.join(start_report_blockers) or '(none)'}"
            ),
            start_path,
        ),
        _check(
            "approved_paper_review",
            bool(approved_review.get("approved"))
            and bool(approved_review.get("evidence_pack_exists"))
            and bool(approval.get("valid", False)),
            (
                f"approved={bool(approved_review.get('approved'))} "
                f"evidence_pack_exists={bool(approved_review.get('evidence_pack_exists'))} "
                f"approval_valid={bool(approval.get('valid', False))}"
            ),
            Path(str(approved_review.get("path") or readiness_path)),
        ),
        _approved_paper_review_integrity_check(root=root, approved_review=approved_review),
        _check(
            "data_status",
            _schema_version_is(data_status, DATA_STATUS_SCHEMA_VERSION)
            and str(data_status.get("status", "missing")) == "pass"
            and str(_mapping(data_status.get("instrument")).get("market_type", "")) == MARKET_TYPE,
            (
                f"schema_version={data_status.get('schema_version', 'missing')} "
                f"status={data_status.get('status', 'missing')} "
                f"instrument_market_type={_mapping(data_status.get('instrument')).get('market_type', '')}"
            ),
            data_status_path,
        ),
        _check(
            "perpetual_provider",
            _schema_version_is(provider, PROVIDER_SCHEMA_VERSION)
            and bool(provider.get("perpetual_evidence_ready", False)),
            (
                f"schema_version={provider.get('schema_version', 'missing')} "
                f"perpetual_evidence_ready={bool(provider.get('perpetual_evidence_ready', False))} "
                f"exchange_info_verified={bool(provider.get('exchange_info_verified', False))} "
                f"funding_info_verified={bool(provider.get('funding_info_verified', False))}"
            ),
            provider_path,
        ),
        _check(
            "bundle_preflight",
            _schema_version_is(bundle_preflight, BUNDLE_PREFLIGHT_SCHEMA_VERSION)
            and bool(bundle_preflight.get("preflight_pass", False)),
            (
                f"schema_version={bundle_preflight.get('schema_version', 'missing')} "
                f"preflight_pass={bool(bundle_preflight.get('preflight_pass', False))}"
            ),
            bundle_path,
        ),
        _manual_metadata_import_marker_check(bundle_dir, root=root),
        _manual_metadata_import_lineage_check(root=root, bundle_dir=bundle_dir),
        _check(
            "bundle_klines",
            interval_summary["exists"] and interval_summary["row_count"] > 0,
            f"path={interval_summary['path']} rows={interval_summary['row_count']}",
            interval_file,
        ),
        _check(
            "cost_model",
            _cost_model_ready_for_paper(cost),
            _cost_model_detail(cost),
            cost_path,
        ),
        _check(
            "candidate_gate",
            _schema_version_is(candidate, CANDIDATE_GATE_SCHEMA_VERSION)
            and str(candidate.get("status", "missing")) == "pass"
            and int(candidate.get("candidate_passed_internal_gate", 0) or 0) > 0,
            (
                f"schema_version={candidate.get('schema_version', 'missing')} "
                f"status={candidate.get('status', 'missing')} "
                f"candidate_passed_internal_gate={candidate.get('candidate_passed_internal_gate', 0)}"
            ),
            candidate_path,
        ),
        _check(
            "candidate_metric_repair",
            _candidate_metric_repair_ready_for_paper(candidate_metric_repair),
            _candidate_metric_repair_detail(candidate_metric_repair),
            candidate_metric_repair_path,
            _candidate_metric_repair_facts(candidate_metric_repair),
        ),
        _ledger_safety_check(ledger),
        _ledger_reconciliation_check(ledger, root=root),
    ]
    blocking = _dedupe([_reason_code(check) for check in checks if check["status"] == "BLOCKED"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": SYMBOL,
        "symbols": requested_symbols,
        "market_type": MARKET_TYPE,
        "status": "PASS" if not blocking else "BLOCKED",
        "mode": "read_only_preflight",
        "require_start_report_ready": bool(require_start_report_ready),
        "inputs": {
            "data_root": _relpath(data, root),
            "ledger_root": _relpath(ledger, root),
            "readiness_report": _relpath(readiness_path, root),
            "start_report": _relpath(start_path, root),
            "data_status_report": _relpath(data_status_path, root),
            "provider_report": _relpath(provider_path, root),
            "bundle_preflight_report": _relpath(bundle_path, root),
            "cost_model_report": _relpath(cost_path, root),
            "candidate_gate_report": _relpath(candidate_path, root),
            "candidate_metric_repair_report": _relpath(candidate_metric_repair_path, root),
            "config_path": _relpath(config_abs, root),
            "bundle_dir": _relpath(bundle_dir, root) if bundle_dir else "",
            "bundle_manifest": _relpath(bundle_dir / "btc_perpetual_bundle_manifest.json", root) if bundle_dir else "",
            "interval": interval,
        },
        "approved_paper_review": {
            "approved": bool(approved_review.get("approved", False)),
            "paper_review_id": str(approved_review.get("paper_review_id", "")),
            "status": str(approved_review.get("status", "missing") or "missing"),
            "path": str(approved_review.get("path", "")),
            "strategy_manifest_id": str(approved_review.get("strategy_manifest_id", "")),
            "proposed_symbols": _list_of_strings(approved_review.get("proposed_symbols")),
            "proposed_capital": _float_or_none(approved_review.get("proposed_capital")),
            "evidence_pack_path": str(approved_review.get("evidence_pack_path", "")),
            "evidence_pack_exists": bool(approved_review.get("evidence_pack_exists", False)),
            "approval": approval,
        },
        "bundle": {
            "selected_bundle_id": str(_provider_config(config_abs).get("selected_bundle_id", "")),
            "manifest_source_type": str(bundle_manifest.get("source_type", "")),
            "promotion_clean_allowed": bool(bundle_manifest.get("promotion_clean_allowed", False)),
            "interval": interval,
            "interval_file": interval_summary,
        },
        "execution_constraints": {
            "paper_broker": "simulated",
            "real_order_submission": False,
            "allows_live_orders": False,
            "strategy_direct_broker_forbidden": True,
            "orders_require_risk_engine": True,
            "pnl_source": "fills_and_ledger",
            "network_required": False,
        },
        "checks": checks,
        "blocking_reasons": blocking,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only BTC USD-M paper-validation preflight. "
            "This command never starts paper/live trading and never contacts a broker."
        )
    )
    parser.add_argument("--symbols", default=SYMBOL)
    parser.add_argument("--market-type", default=MARKET_TYPE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--readiness-report", default=str(DEFAULT_READINESS_REPORT))
    parser.add_argument("--start-report", default=str(DEFAULT_START_REPORT))
    parser.add_argument("--candidate-metric-repair-report", default=str(DEFAULT_CANDIDATE_METRIC_REPAIR))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--no-start-report-ready-required",
        action="store_true",
        help="Check static prerequisites without requiring the start report to be approved.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = check_btc_paper_validation_readiness(
        repo_root=Path(args.repo_root),
        symbols=_parse_symbols(args.symbols),
        market_type=args.market_type,
        interval=args.interval,
        ledger_root=Path(args.ledger_root),
        data_root=Path(args.data_root),
        readiness_report=Path(args.readiness_report),
        start_report=Path(args.start_report),
        candidate_metric_repair_report=Path(args.candidate_metric_repair_report),
        config_path=Path(args.config_path),
        require_start_report_ready=not args.no_start_report_ready_required,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("BTC Paper Validation Preflight")
        print("=" * 60)
        print(f"  status:      {payload['status']}")
        print(f"  symbol:      {payload['symbol']}")
        print(f"  market_type: {payload['market_type']}")
        print(f"  ledger_root: {payload['inputs']['ledger_root']}")
        print("  checks:")
        for check in payload["checks"]:
            print(f"    [{check['status']}] {check['name']}: {check['detail']}")
        if payload["blocking_reasons"]:
            print(f"  blocking_reasons: {', '.join(payload['blocking_reasons'])}")
        else:
            print("  blocking_reasons: (none)")
        print("=" * 60)
    raise SystemExit(0 if payload["status"] == "PASS" else 1)


def _readiness_ready(payload: Mapping[str, Any]) -> bool:
    return (
        str(payload.get("schema_version", "")) == "btc_paper_readiness_report_v1"
        and str(payload.get("status", "")) == "ready_for_paper_start"
        and bool(payload.get("paper_start_allowed", False))
        and bool(payload.get("paper_execution_authorized", False))
        and str(payload.get("live_status", "")) == "frozen"
    )


def _start_report_ready(payload: Mapping[str, Any]) -> bool:
    return not _start_report_blockers(payload)


def _start_report_blockers(payload: Mapping[str, Any]) -> list[str]:
    commands = _mapping(payload.get("commands"))
    safety = _mapping(payload.get("safety"))
    operator_unblock = _mapping(payload.get("operator_manual_unblock"))
    operator_safety = _mapping(operator_unblock.get("safety"))
    start_command_ready = _command_argv_matches(str(commands.get("start_command", "")), APPROVED_START_ARGV)
    resume_command_ready = _command_argv_matches(str(commands.get("resume_command", "")), APPROVED_RESUME_ARGV)
    preflight_command_ready = _command_argv_matches(
        str(commands.get("preflight_command", "")),
        APPROVED_PREFLIGHT_ARGV,
    )
    blockers: list[str] = []
    if str(payload.get("asset", "")) != "btc":
        blockers.append("btc_paper_validation_start_report_asset_invalid")
    if str(payload.get("symbol", "")) != SYMBOL:
        blockers.append("btc_paper_validation_start_report_symbol_invalid")
    if str(payload.get("market_type", "")) != MARKET_TYPE:
        blockers.append("btc_paper_validation_start_report_market_type_invalid")
    if str(payload.get("schema_version", "")) != "btc_paper_validation_start_report_v1":
        blockers.append("btc_paper_validation_start_report_schema_version_invalid")
    if str(payload.get("status", "")) != "ready_to_start_paper_validation":
        blockers.append("btc_paper_validation_start_report_status_not_ready")
    if payload.get("paper_start_allowed") is not True:
        blockers.append("btc_paper_validation_start_report_start_not_allowed")
    if payload.get("paper_execution_authorized") is not True:
        blockers.append("btc_paper_validation_start_report_execution_not_authorized")
    if str(payload.get("live_status", "")) != "frozen":
        blockers.append("btc_paper_validation_start_report_live_not_frozen")
    if start_command_ready == resume_command_ready:
        blockers.append("btc_paper_validation_start_report_command_not_exclusive")
    if start_command_ready and str(payload.get("next_required_action", "")) != "start_paper_validation":
        blockers.append("btc_paper_validation_start_report_start_action_mismatch")
    if resume_command_ready and str(payload.get("next_required_action", "")) != "resume_paper_validation":
        blockers.append("btc_paper_validation_start_report_resume_action_mismatch")
    if str(commands.get("report_rebuild_command", "")) != APPROVED_REPORT_REBUILD_COMMAND:
        blockers.append("btc_paper_validation_start_report_rebuild_command_invalid")
    if not preflight_command_ready:
        blockers.append("btc_paper_validation_start_report_preflight_command_invalid")
    if _list_of_strings(payload.get("blockers")):
        blockers.append("btc_paper_validation_start_report_has_blockers")
    required_true_safety = (
        "report_only",
        "requires_readiness_report",
        "requires_approved_review",
        "requires_evidence_pack",
        "strategy_direct_broker_forbidden",
        "all_orders_must_pass_risk_engine",
    )
    required_false_safety = ("allows_live_orders", "paper_auto_start")
    if not safety:
        blockers.append("btc_paper_validation_start_report_safety_missing")
    for name in required_true_safety:
        if safety.get(name) is not True:
            blockers.append(f"btc_paper_validation_start_report_safety_{name}_not_true")
    for name in required_false_safety:
        if safety.get(name) is not False:
            blockers.append(f"btc_paper_validation_start_report_safety_{name}_not_false")
    if not operator_unblock:
        blockers.append("btc_paper_validation_start_report_operator_unblock_missing")
    if _list_of_strings(operator_unblock.get("blockers")):
        blockers.append("btc_paper_validation_start_report_operator_unblock_blocked")
    for name in ("api_key_required", "private_endpoints_allowed", "order_endpoints_allowed", "paper_or_live_unlock_allowed"):
        if operator_safety.get(name) is not False:
            blockers.append(f"btc_paper_validation_start_report_operator_safety_{name}_not_false")
    return _dedupe(blockers)


def _cost_model_ready_for_paper(payload: Mapping[str, Any]) -> bool:
    fee_model = _mapping(payload.get("fee_model"))
    slippage_model = _mapping(payload.get("slippage_model"))
    taker_fee_bps = _float_or_none(fee_model.get("taker_fee_bps"))
    slippage_bps = _float_or_none(slippage_model.get("slippage_bps"))
    return (
        _schema_version_is(payload, COST_MODEL_SCHEMA_VERSION)
        and str(payload.get("status", "missing")) == "pass"
        and fee_model.get("fee_tier_verified") is True
        and taker_fee_bps is not None
        and taker_fee_bps >= 0
        and slippage_bps is not None
        and slippage_bps >= 0
    )


def _cost_model_detail(payload: Mapping[str, Any]) -> str:
    fee_model = _mapping(payload.get("fee_model"))
    slippage_model = _mapping(payload.get("slippage_model"))
    return (
        f"schema_version={payload.get('schema_version', 'missing')} "
        f"status={payload.get('status', 'missing')} "
        f"fee_tier_verified={bool(fee_model.get('fee_tier_verified', False))} "
        f"taker_fee_bps={fee_model.get('taker_fee_bps', 'missing')} "
        f"slippage_bps={slippage_model.get('slippage_bps', 'missing')}"
    )


def _candidate_metric_repair_ready_for_paper(payload: Mapping[str, Any]) -> bool:
    return (
        _schema_version_is(payload, CANDIDATE_METRIC_REPAIR_SCHEMA_VERSION)
        and str(payload.get("status", "missing")) == "candidate_metric_gate_passed"
        and bool(payload.get("promotion_allowed", False))
        and bool(payload.get("paper_review_pending_allowed", False))
        and not _list_of_strings(payload.get("failed_metrics"))
        and not _list_of_strings(payload.get("blockers"))
    )


def _candidate_metric_repair_detail(payload: Mapping[str, Any]) -> str:
    facts = _candidate_metric_repair_facts(payload)
    return (
        f"schema_version={facts['schema_version']} "
        f"status={facts['status']} "
        f"promotion_allowed={facts['promotion_allowed']} "
        f"paper_review_pending_allowed={facts['paper_review_pending_allowed']} "
        f"failed_metrics={','.join(facts['failed_metrics']) or '(none)'}"
    )


def _candidate_metric_repair_facts(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": str(payload.get("schema_version", "missing") or "missing"),
        "status": str(payload.get("status", "missing") or "missing"),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "failed_metrics": _list_of_strings(payload.get("failed_metrics")),
        "blockers": _list_of_strings(payload.get("blockers")),
    }


def _approved_paper_review_integrity_check(*, root: Path, approved_review: Mapping[str, Any]) -> dict[str, Any]:
    approval = _mapping(approved_review.get("approval"))
    gate_snapshot = _mapping(approval.get("gate_snapshot"))
    review_path = _resolve_report_path(approved_review.get("path"), root)
    evidence_pack = _resolve_report_path(approved_review.get("evidence_pack_path"), root)
    source = _resolve_report_path(approval.get("source"), root)
    source_sha256 = str(approval.get("source_sha256", "") or "")
    approved_symbols = _normalized_symbols(_list_of_strings(approved_review.get("proposed_symbols")))
    approval_candidate = str(approval.get("candidate_id", "") or "")
    snapshot_candidate = str(gate_snapshot.get("candidate_id", "") or "")
    approved_review_root = root / "data/research/paper_reviews"
    evidence_pack_root = root / "data/research/evidence_packs"
    blockers: list[str] = []
    if not approved_review.get("approved"):
        blockers.append("btc_approved_paper_review_missing")
    if str(approved_review.get("status", "") or "") != "APPROVED_FOR_PAPER_ONLY":
        blockers.append("btc_approved_paper_review_status_not_paper_only")
    if approved_symbols != [SYMBOL]:
        blockers.append("btc_approved_paper_review_symbol_scope_mismatch")
    if _float_or_none(approved_review.get("proposed_capital")) is None:
        blockers.append("btc_approved_paper_review_proposed_capital_missing")
    if review_path is None:
        blockers.append("btc_approved_paper_review_path_missing")
    elif not _path_is_relative_to(review_path, approved_review_root):
        blockers.append("btc_approved_paper_review_path_outside_allowed_root")
    elif not review_path.exists():
        blockers.append("btc_approved_paper_review_file_missing")
    if evidence_pack is None:
        blockers.append("btc_approved_paper_review_evidence_pack_path_missing")
    elif not _path_is_relative_to(evidence_pack, evidence_pack_root):
        blockers.append("btc_approved_paper_review_evidence_pack_path_outside_allowed_root")
    elif not evidence_pack.exists():
        blockers.append("btc_approved_paper_review_evidence_pack_file_missing")
    if approval.get("valid") is not True:
        blockers.append("btc_approved_paper_review_approval_invalid")
    if approval.get("schema_version") != "paper_review_approval_v1":
        blockers.append("btc_approved_paper_review_approval_schema_invalid")
    if not str(approval.get("reviewer", "") or "").strip():
        blockers.append("btc_approved_paper_review_reviewer_missing")
    if not _utc_approval_timestamp(approval.get("timestamp")):
        blockers.append("btc_approved_paper_review_timestamp_invalid")
    if not approval_candidate:
        blockers.append("btc_approved_paper_review_candidate_missing")
    if _list_of_strings(approval.get("blockers")):
        blockers.append("btc_approved_paper_review_approval_has_blockers")
    if not gate_snapshot:
        blockers.append("btc_approved_paper_review_gate_snapshot_missing")
    elif snapshot_candidate != approval_candidate:
        blockers.append("btc_approved_paper_review_candidate_snapshot_mismatch")
    if gate_snapshot and gate_snapshot.get("paper_execution_authorized") is not False:
        blockers.append("btc_approved_paper_review_scope_not_record_only")
    if gate_snapshot and gate_snapshot.get("authorization_scope") != "human_review_only":
        blockers.append("btc_approved_paper_review_scope_not_human_review_only")
    if source is None:
        blockers.append("btc_approved_paper_review_source_missing")
    elif not _path_is_relative_to(source, evidence_pack_root):
        blockers.append("btc_approved_paper_review_source_path_outside_allowed_root")
    elif evidence_pack is not None and not _same_resolved_path(source, evidence_pack):
        blockers.append("btc_approved_paper_review_source_not_evidence_pack")
    if not _is_sha256(source_sha256):
        blockers.append("btc_approved_paper_review_source_sha256_invalid")
    elif evidence_pack is not None and evidence_pack.exists() and _sha256(evidence_pack) != source_sha256:
        blockers.append("btc_approved_paper_review_source_sha256_mismatch")
    blockers = _dedupe(blockers)
    detail = (
        f"status={approved_review.get('status', 'missing')} "
        f"symbols={','.join(approved_symbols) or '(missing)'} "
        f"review={_relpath(review_path, root) if review_path else '(missing)'} "
        f"evidence_pack={_relpath(evidence_pack, root) if evidence_pack else '(missing)'} "
        f"source_sha256={source_sha256 or '(missing)'} blockers={','.join(blockers) or '(none)'}"
    )
    return _check("approved_paper_review_integrity", not blockers, detail, evidence_pack)


def _ledger_safety_check(ledger_root: Path) -> dict[str, Any]:
    if not ledger_root.exists():
        return _check(
            "ledger_root",
            True,
            f"clean_start path={ledger_root}",
            ledger_root,
            {
                "path": str(ledger_root),
                "symbols": [],
                "invalid_rows": 0,
                "live_markers": [],
                "in_progress_cycle_markers": [],
                "in_progress_cycle_marker_statuses": [],
                "start_lock": "",
            },
        )
    symbols = set()
    invalid_rows = 0
    live_markers: list[str] = []
    in_progress_markers = _in_progress_cycle_markers(ledger_root)
    in_progress_marker_summaries = _in_progress_cycle_marker_summaries(ledger_root)
    start_lock = _ledger_start_lock(ledger_root)
    for name in ("orders.jsonl", "fills.jsonl", "portfolio_snapshots.jsonl"):
        path = ledger_root / name
        if not path.exists():
            continue
        for row in _read_jsonl(path):
            if not isinstance(row, dict):
                invalid_rows += 1
                continue
            symbol = str(row.get("symbol", "")).upper()
            if symbol:
                symbols.add(symbol)
            broker = str(row.get("broker", row.get("broker_order_id", ""))).lower()
            if "alpaca" in broker or "ibkr" in broker or "live" in broker:
                live_markers.append(name)
    safe = (
        invalid_rows == 0
        and symbols.issubset({SYMBOL})
        and not live_markers
        and not in_progress_markers
        and not start_lock
    )
    detail = (
        f"path={ledger_root} symbols={','.join(sorted(symbols)) or '(none)'} "
        f"invalid_rows={invalid_rows} live_markers={','.join(live_markers) or '(none)'} "
        f"in_progress_cycle_markers={','.join(in_progress_markers) or '(none)'} "
        f"in_progress_cycle_marker_statuses={','.join(in_progress_marker_summaries) or '(none)'} "
        f"start_lock={start_lock or '(none)'}"
    )
    return _check(
        "ledger_root",
        safe,
        detail,
        ledger_root,
        {
            "path": str(ledger_root),
            "symbols": sorted(symbols),
            "invalid_rows": invalid_rows,
            "live_markers": live_markers,
            "in_progress_cycle_markers": in_progress_markers,
            "in_progress_cycle_marker_statuses": in_progress_marker_summaries,
            "start_lock": start_lock,
        },
    )


def _ledger_reconciliation_check(ledger_root: Path, *, root: Path) -> dict[str, Any]:
    state = _read_json(ledger_root / "validation_state.json")
    latest = _latest_daily_result(state)
    history = _validation_state_history_status(state, root=root)
    if not latest:
        has_completed_state = bool(state) and (
            int(state.get("days_completed", 0) or 0) > 0
            or bool(_list_of_strings(state.get("completed_cycle_keys")))
        )
        detail = (
            f"path={ledger_root} latest_status=(none) "
            f"history_blockers={','.join(history['blockers']) or '(none)'}"
        )
        return _check(
            "ledger_reconciliation",
            not has_completed_state and history["ok"],
            detail,
            ledger_root / "validation_state.json",
            {
                "path": str(ledger_root),
                "latest_status": "",
                "latest_run_id": "",
                "has_completed_state": has_completed_state,
                "clean": None,
                "reconciliation_status": "",
                "artifact_path": "",
                "artifact_hash": "",
                "artifact_blockers": [],
                "history_blockers": history["blockers"],
                "failed_cycle_keys": history["failed_cycle_keys"],
            },
        )
    status = str(latest.get("reconciliation_status", "missing") or "missing")
    artifact = _ledger_reconciliation_artifact_status(latest, root=root)
    clean = (
        bool(latest.get("clean", False))
        and status in {"clean", "ok", "pass", "passed", "complete"}
        and artifact["ok"]
        and history["ok"]
    )
    detail = (
        f"path={ledger_root} latest_run_id={latest.get('run_id', '')} "
        f"clean={bool(latest.get('clean', False))} reconciliation_status={status} "
        f"artifact={artifact['path']} artifact_hash={artifact['hash']} "
        f"artifact_blockers={','.join(artifact['blockers']) or '(none)'} "
        f"history_blockers={','.join(history['blockers']) or '(none)'} "
        f"failed_cycle_keys={','.join(history['failed_cycle_keys']) or '(none)'}"
    )
    return _check(
        "ledger_reconciliation",
        clean,
        detail,
        ledger_root / "validation_state.json",
        {
            "path": str(ledger_root),
            "latest_status": status,
            "latest_run_id": str(latest.get("run_id", "") or ""),
            "has_completed_state": True,
            "clean": bool(latest.get("clean", False)),
            "reconciliation_status": status,
            "artifact_path": artifact["path"],
            "artifact_hash": artifact["hash"],
            "artifact_blockers": artifact["blockers"],
            "history_blockers": history["blockers"],
            "failed_cycle_keys": history["failed_cycle_keys"],
            "daily_result_count": history["daily_result_count"],
            "completed_cycle_key_count": history["completed_cycle_key_count"],
        },
    )


def _validation_state_history_status(state: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    if not state:
        return {
            "ok": True,
            "blockers": [],
            "failed_cycle_keys": [],
            "daily_result_count": 0,
            "completed_cycle_key_count": 0,
        }
    blockers: list[str] = []
    failed_cycle_keys: list[str] = []
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
        cycle_key = str(item.get("cycle_key", "") or "(missing)")
        item_failed = False
        status = str(item.get("reconciliation_status", "missing") or "missing")
        if not str(item.get("run_id", "") or ""):
            blockers.append("btc_validation_state_daily_run_id_missing")
            item_failed = True
        if item.get("clean") is not True:
            blockers.append("btc_validation_state_daily_not_clean")
            item_failed = True
        if item.get("equity_consistent") is not True:
            blockers.append("btc_validation_state_daily_equity_inconsistent")
            item_failed = True
        if status not in {"clean", "ok", "pass", "passed", "complete"}:
            blockers.append("btc_validation_state_daily_reconciliation_not_clean")
            item_failed = True
        artifact = _ledger_reconciliation_artifact_status(item, root=root)
        if not artifact["ok"]:
            blockers.append("btc_validation_state_daily_reconciliation_artifact_invalid")
            blockers.extend(str(blocker) for blocker in artifact["blockers"])
            item_failed = True
        if item_failed:
            failed_cycle_keys.append(cycle_key)
    return {
        "ok": not blockers,
        "blockers": _dedupe(blockers),
        "failed_cycle_keys": _dedupe(failed_cycle_keys),
        "daily_result_count": len(daily_results),
        "completed_cycle_key_count": len(completed_keys),
    }


def _latest_daily_result(state: Mapping[str, Any]) -> dict[str, Any]:
    daily = state.get("daily_results")
    if not isinstance(daily, list) or not daily:
        return {}
    latest = daily[-1]
    return dict(latest) if isinstance(latest, Mapping) else {}


def _ledger_reconciliation_artifact_status(latest: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    artifact_path = _resolve_report_path(latest.get("ledger_reconciliation_artifact_path"), root)
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
        "path": _relpath(artifact_path, root) if artifact_path else "(missing)",
        "hash": expected_hash or "(missing)",
        "blockers": _dedupe(blockers),
    }


def _in_progress_cycle_markers(ledger_root: Path) -> list[str]:
    marker_dir = ledger_root / "audit" / "paper_validation_in_progress"
    if not marker_dir.exists():
        return []
    return sorted(path.name for path in marker_dir.glob("*.json") if path.is_file())


def _in_progress_cycle_marker_summaries(ledger_root: Path) -> list[str]:
    marker_dir = ledger_root / "audit" / "paper_validation_in_progress"
    if not marker_dir.exists():
        return []
    summaries: list[str] = []
    for path in sorted(marker_dir.glob("*.json")):
        if not path.is_file():
            continue
        payload, parse_ok = _read_marker_json(path)
        status = str(payload.get("status", "unknown") or "unknown")
        run_id = str(payload.get("run_id", "") or "")
        cycle_key = str(payload.get("cycle_key", "") or "")
        parse_status = "parse_ok" if parse_ok else "parse_error"
        summaries.append(
            f"{path.name}:{parse_status}:{status}:run_id={run_id or '(missing)'}:"
            f"cycle_key={cycle_key or '(missing)'}"
        )
    return summaries


def _read_marker_json(path: Path) -> tuple[dict[str, Any], bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, False
    return (dict(payload), True) if isinstance(payload, Mapping) else ({}, False)


def _ledger_start_lock(ledger_root: Path) -> str:
    lock = ledger_root / "audit" / LEDGER_START_LOCK_NAME
    if not lock.exists() or not lock.is_file():
        return ""
    try:
        fd = os.open(lock, os.O_RDWR)
    except OSError:
        return lock.name
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            return lock.name
        return ""
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


def _interval_file_summary(path: Path | None, *, interval: str) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"path": str(path or ""), "exists": False, "row_count": 0, "first_timestamp": "", "last_timestamp": ""}
    row_count = 0
    first = ""
    last = ""
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                timestamp = str(row.get("timestamp", ""))
                if not first:
                    first = timestamp
                last = timestamp
                row_count += 1
    except OSError:
        return {"path": str(path), "exists": True, "row_count": 0, "first_timestamp": "", "last_timestamp": ""}
    return {
        "path": str(path),
        "exists": True,
        "row_count": row_count,
        "first_timestamp": first,
        "last_timestamp": last,
        "interval": interval,
    }


def _selected_bundle_dir(root: Path, config_path: Path) -> Path | None:
    provider = _provider_config(config_path)
    selected_bundle_id = str(provider.get("selected_bundle_id", "")).strip()
    if not selected_bundle_id:
        return None
    selected_provider, _selected_provider_config = selected_btc_perpetual_provider(config_path)
    bundle_root = root / str(provider.get("root", f"data/external/btc_perpetual/{selected_provider}/")) / "bundles"
    return bundle_root / selected_bundle_id


def _manual_metadata_import_marker_check(bundle_dir: Path | None, *, root: Path) -> dict[str, Any]:
    marker = bundle_dir / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER if bundle_dir else None
    marker_exists = bool(marker and marker.exists())
    detail = f"marker={_relpath(marker, root) if marker_exists and marker else '(none)'}"
    return _check("manual_metadata_import_marker", not marker_exists, detail, marker if marker_exists else None)


def _manual_metadata_import_lineage_check(*, root: Path, bundle_dir: Path | None) -> dict[str, Any]:
    report_path = root / DEFAULT_MANUAL_METADATA_IMPORT_REPORT
    report = _read_json(report_path)
    blockers: list[str] = []
    if bundle_dir is None:
        blockers.append("btc_manual_metadata_import_selected_bundle_missing")
    if not report_path.exists():
        blockers.append("btc_manual_metadata_import_report_missing")
    if report.get("schema_version") != "btc_manual_metadata_import_report_v1":
        blockers.append("btc_manual_metadata_import_schema_version_missing_or_invalid")
    if report.get("status") != "verified":
        blockers.append("btc_manual_metadata_import_not_verified")
    if report.get("dry_run") is not False:
        blockers.append("btc_manual_metadata_import_is_dry_run")
    if report.get("writes_performed") is not True:
        blockers.append("btc_manual_metadata_import_write_not_performed")
    if report.get("exchange_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_exchange_info_not_verified")
    if report.get("funding_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_funding_info_not_verified")
    if not _utc_capture_timestamp(report.get("captured_at")):
        blockers.append("btc_manual_metadata_import_captured_at_missing")
    if report.get("post_import_validation_command") != "make validate-btc-public-data-bundle":
        blockers.append("btc_manual_metadata_import_validation_command_missing")
    blockers.extend(_manual_metadata_raw_input_blockers(report, root=root))
    if bundle_dir is not None:
        reported_bundle = _resolve_report_path(report.get("bundle_dir"), root)
        if reported_bundle is None or not _same_resolved_path(reported_bundle, bundle_dir):
            blockers.append("btc_manual_metadata_import_bundle_dir_not_selected_bundle")
        blockers.extend(
            _manual_metadata_output_hash_blockers(
                report,
                root=root,
                bundle_dir=bundle_dir,
                prefix="exchange_info",
                filename="exchange_info.json",
            )
        )
        blockers.extend(
            _manual_metadata_output_hash_blockers(
                report,
                root=root,
                bundle_dir=bundle_dir,
                prefix="funding_info",
                filename="funding_info.json",
            )
        )
    blockers = _dedupe(blockers)
    detail = f"report={_relpath(report_path, root)} blockers={','.join(blockers) or '(none)'}"
    return _check("manual_metadata_import_lineage", not blockers, detail, report_path)


def _manual_metadata_raw_input_blockers(report: Mapping[str, Any], *, root: Path) -> list[str]:
    raw_inputs = _mapping(report.get("raw_input_files"))
    return [
        *_manual_metadata_raw_file_blockers(
            _mapping(raw_inputs.get("exchange_info_raw")),
            root=root,
            prefix="exchange_info",
        ),
        *_manual_metadata_raw_file_blockers(
            _mapping(raw_inputs.get("funding_info_raw")),
            root=root,
            prefix="funding_info",
        ),
    ]


def _manual_metadata_raw_file_blockers(raw: Mapping[str, Any], *, root: Path, prefix: str) -> list[str]:
    blockers: list[str] = []
    path = _resolve_report_path(raw.get("path"), root)
    reported_size = raw.get("size_bytes")
    reported_hash = raw.get("sha256")
    status_path = _resolve_report_path(raw.get("http_status_file"), root)
    provenance_ok = (
        raw.get("exists") is True
        and path is not None
        and isinstance(reported_size, int)
        and reported_size > 0
        and isinstance(reported_hash, str)
        and _is_sha256(reported_hash)
    )
    if not provenance_ok:
        blockers.append(f"btc_{prefix}_raw_import_provenance_missing")
    if not _manual_metadata_raw_current_file_verified(path, reported_size, reported_hash):
        blockers.append(f"btc_{prefix}_raw_import_current_file_mismatch")
    if not (
        status_path is not None
        and status_path.exists()
        and _read_int_file(status_path) == 200
        and raw.get("http_status") == 200
        and raw.get("http_status_verified") is True
    ):
        blockers.append(f"btc_{prefix}_raw_http_status_not_200")
    return blockers


def _manual_metadata_raw_current_file_verified(
    path: Path | None,
    reported_size: object,
    reported_hash: object,
) -> bool:
    if path is None or not path.exists() or not isinstance(reported_size, int) or not isinstance(reported_hash, str):
        return False
    return path.stat().st_size == reported_size and _sha256(path) == reported_hash


def _manual_metadata_output_hash_blockers(
    report: Mapping[str, Any],
    *,
    root: Path,
    bundle_dir: Path,
    prefix: str,
    filename: str,
) -> list[str]:
    expected_path = bundle_dir / filename
    reported_path = _resolve_report_path(report.get(f"{prefix}_output_path"), root)
    reported_hash = report.get(f"{prefix}_output_sha256")
    blockers: list[str] = []
    if reported_path is None:
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_path_missing")
    elif not _same_resolved_path(reported_path, expected_path):
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_path_not_selected_bundle")
    if not expected_path.exists():
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_file_missing")
    if not isinstance(reported_hash, str) or len(reported_hash) != 64:
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_sha256_missing")
    elif expected_path.exists() and _sha256(expected_path) != reported_hash:
        blockers.append(f"btc_manual_metadata_import_{prefix}_output_hash_mismatch")
    return blockers


def _provider_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    _selected_provider, provider = selected_btc_perpetual_provider(path)
    return dict(provider)


def _check(
    name: str,
    passed: bool,
    detail: str,
    artifact_path: Path | None = None,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if passed else "BLOCKED",
        "detail": detail,
        "artifact_path": str(artifact_path) if artifact_path else "",
        "facts": dict(facts or {}),
    }


def _reason_code(check: Mapping[str, Any]) -> str:
    return f"btc_paper_validation_{check.get('name', 'unknown')}_blocked"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _schema_version_is(payload: Mapping[str, Any], expected: str) -> bool:
    return str(payload.get("schema_version", "")) == expected


def _is_sha256(raw: str) -> bool:
    return len(raw) == 64 and all(char in "0123456789abcdefABCDEF" for char in raw)


def _read_jsonl(path: Path) -> list[object]:
    rows: list[object] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append(None)
    except OSError:
        return [None]
    return rows


def _read_int_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _parse_symbols(raw: str) -> list[str]:
    return _normalized_symbols([item for item in raw.split(",") if item.strip()])


def _command_argv_matches(raw: str, expected: list[str]) -> bool:
    try:
        return shlex.split(raw) == expected
    except ValueError:
        return False


def _normalized_symbols(values: list[str]) -> list[str]:
    return sorted({str(item).strip().upper() for item in values if str(item).strip()})


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _resolve_report_path(value: object, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
