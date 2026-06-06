#!/usr/bin/env python3
"""Build a read-only QuantStation global research registry.

The builder only summarizes existing artifacts. It does not run backtests,
paper runtimes, live runtimes, brokers, optimizers, or strategy generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir


DEFAULT_OUTPUT = Path("artifacts/global_research_registry/research_registry.json")
BTC_SOURCE_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
BTC_REGISTRY_PATH = Path("artifacts/btc_research_registry/research_registry.json")
BTC_DATA_STATUS_REPORT = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
BTC_FUNDING_RATE_GAP_REPORT = Path("artifacts/btc_data_status/latest/btc_funding_rate_gap_report.json")
BTC_BUNDLE_PREFLIGHT_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json")
BTC_PROVIDER_VERIFICATION_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
BTC_MANUAL_METADATA_CAPTURE_READINESS_REPORT = Path(
    "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json"
)
BTC_MANUAL_METADATA_CAPTURE_OPERATOR_PACKET = Path(
    "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
)
BTC_MANUAL_METADATA_IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
BTC_OBJECTIVE_COMPLETION_AUDIT_REPORT = Path("artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json")
UTC_CAPTURE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BTC_COST_MODEL_REPORT = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
BTC_FUNDING_LEDGER_REPORT = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
BTC_FOLD_REGIME_CONTRACT_REPORT = Path("artifacts/btc_fold_regime/latest/fold_regime_contract_report.json")
BTC_CANDIDATE_GATE_AUDIT_REPORT = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")
BTC_CANDIDATE_METRIC_REPAIR_REPORT = Path("artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json")
BTC_CANDIDATE_BOUNDED_RETEST_PLAN = Path("artifacts/btc_candidate_gate/latest/candidate_bounded_retest_plan.json")
BTC_NEXT_HYPOTHESIS_DECISION_REPORT = Path("artifacts/btc_candidate_gate/latest/btc_next_hypothesis_decision_report.json")
BTC_STRATEGY_FAMILY_ROADMAP_REPORT = Path(
    "artifacts/btc_candidate_gate/latest/btc_strategy_family_roadmap_report.json"
)
BTC_TAIL_DEPENDENCY_REPORT = Path("artifacts/btc_tail_dependency/latest/tail_dependency_report.json")
BTC_COMPRESSION_EXPANSION_ATTRIBUTION_REPORT = Path(
    "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json"
)
DATA_MANIFEST_ROOT = Path("data/manifests")
QLIB_RUNS_ROOT = Path("artifacts/qlib_runs")
PORTFOLIO_RUNS_ROOT = Path("artifacts/portfolio_runs")
GENERATED_FACTORS_PATH = Path("data/research/generated_factors/factors.json")
GENERATED_STRATEGIES_ROOT = Path("data/research/generated_strategies")
FACTOR_MINING_ROOT = Path("data/research/factor_mining")
US_EQUITY_DATA_STATUS_REPORT = Path("artifacts/us_equity_data_status/latest/data_status_report.json")
US_EQUITY_UNIVERSE_MANIFEST = Path("artifacts/us_equity_data_status/latest/universe_manifest.json")
US_EQUITY_CORPORATE_ACTION_REPORT = Path("artifacts/us_equity_data_status/latest/corporate_action_report.json")
US_EQUITY_UNIVERSE_SNAPSHOT_MANIFEST = Path("artifacts/us_equity_data_lineage/latest/universe_snapshot_manifest.json")
US_EQUITY_CORPORATE_ACTION_STATUS_REPORT = Path("artifacts/us_equity_data_lineage/latest/corporate_action_status_report.json")
US_EQUITY_SURVIVORSHIP_AUDIT_REPORT = Path("artifacts/us_equity_data_lineage/latest/survivorship_audit_report.json")
US_EQUITY_PROVIDER_CAPABILITY_MATRIX = Path("artifacts/us_equity_data_lineage/latest/provider_capability_matrix.json")
US_EQUITY_PRODUCTION_BUNDLE_PREFLIGHT_REPORT = Path(
    "artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json"
)
US_EQUITY_PROVIDER_VERIFICATION_REPORT = Path("artifacts/us_equity_data_lineage/latest/provider_verification_report.json")
US_EQUITY_FACTOR_EVIDENCE_PACK = Path("artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json")
US_EQUITY_PORTFOLIO_CANONICAL_REPORT = Path("artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json")


def build_global_registry(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    btc_registry = _read_json(root / BTC_REGISTRY_PATH)
    btc_items = btc_registry.get("items", {}) if isinstance(btc_registry, dict) else {}
    btc_registry_btc = _mapping(btc_registry.get("btc"))
    us_equity = _build_us_equity_summary(root)
    btc_data_status = _btc_data_status(root)
    btc_funding_gap = _read_json(root / BTC_FUNDING_RATE_GAP_REPORT)
    btc_bundle_preflight = _btc_bundle_preflight_status(root)
    btc_provider_verification = _btc_provider_verification_status(root)
    btc_manual_metadata = _btc_manual_metadata_capture_status(root)
    btc_manual_metadata_packet = _btc_manual_metadata_capture_operator_packet_status(root)
    btc_manual_metadata_import = _btc_manual_metadata_import_status(root)
    btc_objective_audit = _btc_objective_completion_status(root)
    btc_cost_model = _btc_cost_model_status(root)
    btc_funding_ledger = _btc_funding_ledger_status(root)
    btc_fold_regime = _btc_fold_regime_status(root)
    btc_candidate_gate = _btc_candidate_gate_status(root)
    btc_candidate_metric_repair = _btc_candidate_metric_repair_status(root)
    btc_candidate_bounded_retest = _btc_candidate_bounded_retest_status(root)
    btc_next_hypothesis = _btc_next_hypothesis_decision_status(root)
    btc_strategy_family = _btc_strategy_family_roadmap_status(root)
    btc_tail_dependency = _btc_tail_dependency_status(root)
    btc_current_candidates = _list_of_strings(btc_registry_btc.get("current_candidates"))
    btc_candidate_passed_internal_gate = int(
        btc_registry_btc.get(
            "candidate_passed_internal_gate",
            btc_candidate_gate.get("candidate_passed_internal_gate", 0),
        )
        or 0
    )
    btc_paper_queue_status = "pending_review" if btc_current_candidates else "locked"
    btc_blockers = _merge_blockers(
        btc_data_status.get("blockers", []),
        btc_funding_gap.get("blockers", []),
        btc_bundle_preflight.get("blockers", []),
        btc_provider_verification.get("blockers", []),
        btc_manual_metadata.get("blockers", []),
        btc_objective_audit.get("blockers", []),
        btc_cost_model.get("blockers", []),
        btc_funding_ledger.get("blockers", []),
        btc_fold_regime.get("blockers", []),
        btc_candidate_gate.get("blockers", []),
        btc_candidate_metric_repair.get("blockers", []),
        btc_candidate_bounded_retest.get("blockers", []),
        btc_next_hypothesis.get("blockers", []),
        btc_strategy_family.get("blockers", []),
        btc_tail_dependency.get("blockers", []),
        _btc_attribution_blockers(root),
    )
    btc = {
        "status": "research_sandbox",
        "paper_queue_status": btc_paper_queue_status,
        "live_status": "frozen",
        "candidate_passed_internal_gate": btc_candidate_passed_internal_gate,
        "latest_registry": str(BTC_REGISTRY_PATH),
        "latest_data_status": _relpath(root / BTC_DATA_STATUS_REPORT, root)
        if (root / BTC_DATA_STATUS_REPORT).exists()
        else None,
        "latest_funding_rate_gap_report": _relpath(root / BTC_FUNDING_RATE_GAP_REPORT, root)
        if (root / BTC_FUNDING_RATE_GAP_REPORT).exists()
        else None,
        "latest_bundle_preflight": _relpath(root / BTC_BUNDLE_PREFLIGHT_REPORT, root)
        if (root / BTC_BUNDLE_PREFLIGHT_REPORT).exists()
        else None,
        "latest_provider_verification": _relpath(root / BTC_PROVIDER_VERIFICATION_REPORT, root)
        if (root / BTC_PROVIDER_VERIFICATION_REPORT).exists()
        else None,
        "latest_manual_metadata_capture_readiness": _relpath(root / BTC_MANUAL_METADATA_CAPTURE_READINESS_REPORT, root)
        if (root / BTC_MANUAL_METADATA_CAPTURE_READINESS_REPORT).exists()
        else None,
        "latest_manual_metadata_capture_operator_packet": _relpath(
            root / BTC_MANUAL_METADATA_CAPTURE_OPERATOR_PACKET, root
        )
        if (root / BTC_MANUAL_METADATA_CAPTURE_OPERATOR_PACKET).exists()
        else None,
        "latest_manual_metadata_import_report": _relpath(root / BTC_MANUAL_METADATA_IMPORT_REPORT, root)
        if (root / BTC_MANUAL_METADATA_IMPORT_REPORT).exists()
        else None,
        "latest_objective_completion_audit": _relpath(root / BTC_OBJECTIVE_COMPLETION_AUDIT_REPORT, root)
        if (root / BTC_OBJECTIVE_COMPLETION_AUDIT_REPORT).exists()
        else None,
        "latest_cost_model": _relpath(root / BTC_COST_MODEL_REPORT, root)
        if (root / BTC_COST_MODEL_REPORT).exists()
        else None,
        "latest_funding_ledger": _relpath(root / BTC_FUNDING_LEDGER_REPORT, root)
        if (root / BTC_FUNDING_LEDGER_REPORT).exists()
        else None,
        "latest_fold_regime_contract": _relpath(root / BTC_FOLD_REGIME_CONTRACT_REPORT, root)
        if (root / BTC_FOLD_REGIME_CONTRACT_REPORT).exists()
        else None,
        "latest_candidate_gate_audit": _relpath(root / BTC_CANDIDATE_GATE_AUDIT_REPORT, root)
        if (root / BTC_CANDIDATE_GATE_AUDIT_REPORT).exists()
        else None,
        "latest_candidate_metric_repair_report": _relpath(root / BTC_CANDIDATE_METRIC_REPAIR_REPORT, root)
        if (root / BTC_CANDIDATE_METRIC_REPAIR_REPORT).exists()
        else None,
        "latest_candidate_bounded_retest_plan": _relpath(root / BTC_CANDIDATE_BOUNDED_RETEST_PLAN, root)
        if (root / BTC_CANDIDATE_BOUNDED_RETEST_PLAN).exists()
        else None,
        "latest_next_hypothesis_decision_report": _relpath(root / BTC_NEXT_HYPOTHESIS_DECISION_REPORT, root)
        if (root / BTC_NEXT_HYPOTHESIS_DECISION_REPORT).exists()
        else None,
        "latest_strategy_family_roadmap_report": _relpath(root / BTC_STRATEGY_FAMILY_ROADMAP_REPORT, root)
        if (root / BTC_STRATEGY_FAMILY_ROADMAP_REPORT).exists()
        else None,
        "latest_tail_dependency": _relpath(root / BTC_TAIL_DEPENDENCY_REPORT, root)
        if (root / BTC_TAIL_DEPENDENCY_REPORT).exists()
        else None,
        "latest_compression_attribution": _relpath(root / BTC_COMPRESSION_EXPANSION_ATTRIBUTION_REPORT, root)
        if (root / BTC_COMPRESSION_EXPANSION_ATTRIBUTION_REPORT).exists()
        else None,
        "data_status": btc_data_status,
        "bundle_preflight_status": btc_bundle_preflight,
        "provider_verification_status": btc_provider_verification,
        "manual_metadata_capture_status": btc_manual_metadata,
        "manual_metadata_capture_operator_packet_status": btc_manual_metadata_packet,
        "manual_metadata_import_status": btc_manual_metadata_import,
        "objective_completion_status": btc_objective_audit,
        "cost_model_status": btc_cost_model,
        "funding_ledger_status": btc_funding_ledger,
        "fold_regime_status": btc_fold_regime,
        "candidate_gate_audit": btc_candidate_gate,
        "candidate_metric_repair_status": btc_candidate_metric_repair,
        "candidate_bounded_retest_status": btc_candidate_bounded_retest,
        "next_hypothesis_decision_status": btc_next_hypothesis,
        "strategy_family_roadmap_status": btc_strategy_family,
        "tail_dependency_status": btc_tail_dependency,
        "current_candidates": btc_current_candidates,
        "attribution_only": _btc_attribution_only(btc_items),
        "compression_boundary": _btc_compression_boundary(root),
        "archived_or_rejected": _btc_archived_or_rejected(btc_items),
        "blockers": btc_blockers,
    }
    return {
        "schema_version": "global_research_registry_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "paper_queue_status": "pending_review" if btc_current_candidates else "locked",
        "live_status": "frozen",
        "candidate_passed_internal_gate": btc_candidate_passed_internal_gate,
        "assets": {
            "us_equity": us_equity,
            "btc": btc,
        },
        "failure_explanations": _failure_explanations(us_equity=us_equity, btc=btc),
    }


def write_registry(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_global_registry(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    output = write_registry(payload, Path(args.output))
    print(output)


def _btc_current_candidates(items: Mapping[str, Any], *, root: Path) -> list[dict[str, Any]]:
    compression = items.get("compression_expansion_breakout", {})
    if str(compression.get("status", "")) == "archived":
        return []
    attribution_path = root / BTC_COMPRESSION_EXPANSION_ATTRIBUTION_REPORT
    return [
        {
            "name": "compression_expansion_breakout",
            "status": str(compression.get("status", "candidate_gate_failed")),
            "allowed_next_action": str(compression.get("allowed_next_action", "attribution_only")),
            "latest_attribution_report": _relpath(attribution_path, root) if attribution_path.exists() else None,
            "paper_review_pending_allowed": False,
        }
    ]


def _btc_attribution_blockers(root: Path) -> list[str]:
    payload = _read_json(root / BTC_COMPRESSION_EXPANSION_ATTRIBUTION_REPORT)
    return _list_of_strings(payload.get("blockers"))


def _btc_compression_boundary(root: Path) -> dict[str, Any]:
    payload = _read_json(root / BTC_COMPRESSION_EXPANSION_ATTRIBUTION_REPORT)
    return {
        "status": "archived",
        "allowed_next_action": "archive_only",
        "archive_recommended": bool(payload.get("archive_recommended", True)),
        "limited_retest_allowed": False,
        "paper_review_pending_allowed": False,
    }


def _btc_attribution_only(items: Mapping[str, Any]) -> list[str]:
    names = []
    for name, row in sorted(items.items()):
        status = str(row.get("status", ""))
        allowed = str(row.get("allowed_next_action", ""))
        if status == "candidate_gate_failed" and allowed == "attribution_only":
            names.append(name)
    return names


def _btc_archived_or_rejected(items: Mapping[str, Any]) -> list[str]:
    names = []
    for name, row in sorted(items.items()):
        status = str(row.get("status", ""))
        if status in {"archived", "hypothesis_rejected"}:
            names.append(name)
    fallback = [
        "perp_dual_trend",
        "low_vol_uptrend",
        "liquidation_shock_recovery",
        "range_reclaim_momentum",
        "compression_expansion_breakout",
    ]
    return names or fallback


def _btc_data_status(root: Path) -> dict[str, Any]:
    path = root / BTC_DATA_STATUS_REPORT
    payload = _read_json(path)
    blockers = []
    if not path.exists():
        blockers.append("btc_data_status_report_missing")
    if isinstance(payload.get("blockers"), list):
        blockers.extend(str(item) for item in payload["blockers"])
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "symbol": str(payload.get("symbol", "")),
        "exchange": str(_mapping(payload.get("instrument")).get("exchange", "")),
        "market_type": str(_mapping(payload.get("instrument")).get("market_type", "")),
        "fold_definition_version": str(payload.get("fold_definition_version", "")),
        "regime_classifier_version": str(payload.get("regime_classifier_version", "")),
        "fold_contract_status": str(payload.get("fold_contract_status", "missing")),
        "regime_contract_status": str(payload.get("regime_contract_status", "missing")),
        "blockers": _merge_blockers(blockers),
    }


def _btc_provider_verification_status(root: Path) -> dict[str, Any]:
    path = root / BTC_PROVIDER_VERIFICATION_REPORT
    payload = _read_json(path)
    blockers = []
    if not path.exists():
        blockers.append("btc_perpetual_provider_verification_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": "pass" if payload.get("perpetual_evidence_ready", False) else "fail",
        "report_path": _relpath(path, root) if path.exists() else None,
        "selected_provider": str(payload.get("selected_provider", "")),
        "selected_bundle_id": payload.get("selected_bundle_id"),
        "source_type": payload.get("source_type"),
        "preflight_pass": bool(payload.get("preflight_pass", False)),
        "perpetual_evidence_ready": bool(payload.get("perpetual_evidence_ready", False)),
        "klines_verified": bool(payload.get("klines_verified", False)),
        "mark_price_klines_verified": bool(payload.get("mark_price_klines_verified", False)),
        "premium_index_klines_verified": bool(payload.get("premium_index_klines_verified", False)),
        "funding_rate_verified": bool(payload.get("funding_rate_verified", False)),
        "funding_info_verified": bool(payload.get("funding_info_verified", False)),
        "exchange_info_verified": bool(payload.get("exchange_info_verified", False)),
        "open_interest_coverage_type": str(payload.get("open_interest_coverage_type", "missing") or "missing"),
        "liquidation_snapshot_gate_eligible": bool(payload.get("liquidation_snapshot_gate_eligible", False)),
        "interval_grid_pass": bool(payload.get("interval_grid_pass", False)),
        "utc_alignment_pass": bool(payload.get("utc_alignment_pass", False)),
        "sample_range_alignment_pass": bool(payload.get("sample_range_alignment_pass", False)),
        "blockers": _merge_blockers(blockers),
    }


def _btc_bundle_preflight_status(root: Path) -> dict[str, Any]:
    path = root / BTC_BUNDLE_PREFLIGHT_REPORT
    payload = _read_json(path)
    blockers = []
    if not path.exists():
        blockers.append("btc_perpetual_bundle_preflight_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": "pass" if payload.get("preflight_pass", False) else "fail",
        "report_path": _relpath(path, root) if path.exists() else None,
        "selected_bundle_id": payload.get("selected_bundle_id"),
        "source_type": payload.get("source_type"),
        "preflight_pass": bool(payload.get("preflight_pass", False)),
        "required_files_present": bool(payload.get("required_files_present", False)),
        "sha256_present": bool(payload.get("sha256_present", False)),
        "record_counts_present": bool(payload.get("record_counts_present", False)),
        "sample_range_present": bool(payload.get("sample_range_present", False)),
        "license_note_present": bool(payload.get("license_note_present", False)),
        "blockers": _merge_blockers(blockers),
    }


def _btc_manual_metadata_capture_status(root: Path) -> dict[str, Any]:
    path = root / BTC_MANUAL_METADATA_CAPTURE_READINESS_REPORT
    payload = _read_json(path)
    exchange = _mapping(payload.get("exchange_info"))
    funding = _mapping(payload.get("funding_info"))
    last_attempt = _mapping(payload.get("last_public_metadata_capture_status"))
    blockers = []
    if not path.exists():
        blockers.append("btc_manual_metadata_capture_readiness_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    manual_capture_required = bool(exchange.get("manual_capture_required", True)) or bool(
        funding.get("manual_capture_required", True)
    )
    if manual_capture_required:
        blockers.extend(_list_of_strings(last_attempt.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "latest_public_metadata_capture_attempt": payload.get("latest_public_metadata_capture_attempt"),
        "last_public_metadata_capture_status": str(last_attempt.get("status", "missing") or "missing"),
        "last_public_metadata_capture_network_called": bool(last_attempt.get("network_called", False)),
        "last_exchange_info_capture_status": str(last_attempt.get("exchange_info_capture_status", "missing") or "missing"),
        "last_exchange_info_http_status": last_attempt.get("exchange_info_http_status"),
        "last_funding_info_capture_status": str(last_attempt.get("funding_info_capture_status", "missing") or "missing"),
        "last_funding_info_http_status": last_attempt.get("funding_info_http_status"),
        "last_public_metadata_next_required_action": str(
            last_attempt.get("next_required_action", "manual_capture_from_allowed_network")
        ),
        "exchange_info_manual_capture_required": bool(exchange.get("manual_capture_required", True)),
        "funding_info_manual_capture_required": bool(funding.get("manual_capture_required", True)),
        "exchange_info_allowed_endpoint": str(exchange.get("allowed_endpoint", "")),
        "funding_info_allowed_endpoint": str(funding.get("allowed_endpoint", "")),
        "api_key_required": bool(_mapping(payload.get("safety")).get("api_key_required", False)),
        "private_endpoints_allowed": bool(_mapping(payload.get("safety")).get("private_endpoints_allowed", False)),
        "order_endpoints_allowed": bool(_mapping(payload.get("safety")).get("order_endpoints_allowed", False)),
        "strategy_retest_allowed": bool(_mapping(payload.get("safety")).get("strategy_retest_allowed", False)),
        "paper_or_live_unlock_allowed": bool(_mapping(payload.get("safety")).get("paper_or_live_unlock_allowed", False)),
        "blockers": _merge_blockers(blockers),
    }


def _btc_manual_metadata_capture_operator_packet_status(root: Path) -> dict[str, Any]:
    path = root / BTC_MANUAL_METADATA_CAPTURE_OPERATOR_PACKET
    payload = _read_json(path)
    last_status = _mapping(payload.get("last_public_metadata_capture_status"))
    required_inputs = _btc_manual_input_statuses(payload.get("required_manual_inputs"))
    fee_tier = _mapping(payload.get("fee_tier_status"))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "operator_action": str(payload.get("operator_action", "manual_capture_from_allowed_network")),
        "manual_inputs_status": str(
            payload.get("manual_inputs_status", "awaiting_manual_inputs") or "awaiting_manual_inputs"
        ),
        "paper_gate_manual_inputs_complete": bool(payload.get("paper_gate_manual_inputs_complete", False)),
        "required_manual_input_count": len(required_inputs),
        "required_manual_inputs": required_inputs,
        "capture_request_count": len(payload.get("capture_requests", []))
        if isinstance(payload.get("capture_requests"), list)
        else 0,
        "dry_run_import_available": bool(payload.get("post_capture_dry_run_import_command")),
        "last_exchange_info_http_status": last_status.get("exchange_info_http_status"),
        "last_funding_info_http_status": last_status.get("funding_info_http_status"),
        "fee_tier_status": {
            "cost_model_report": fee_tier.get("cost_model_report"),
            "cost_model_status": str(fee_tier.get("cost_model_status", "missing") or "missing"),
            "fee_tier_verified": bool(fee_tier.get("fee_tier_verified", False)),
            "manual_capture_required": bool(fee_tier.get("manual_capture_required", True)),
            "maker_fee_bps": _float_or_none(fee_tier.get("maker_fee_bps")),
            "taker_fee_bps": _float_or_none(fee_tier.get("taker_fee_bps")),
            "fee_tier_import_report_verified": bool(fee_tier.get("fee_tier_import_report_verified", False)),
            "fee_blockers": _list_of_strings(fee_tier.get("fee_blockers")),
        },
        "blockers": _merge_blockers(_list_of_strings(payload.get("blockers"))),
    }


def _btc_manual_metadata_import_status(root: Path) -> dict[str, Any]:
    path = root / BTC_MANUAL_METADATA_IMPORT_REPORT
    payload = _read_json(path)
    raw_input_files = _mapping(payload.get("raw_input_files"))
    exchange_raw = _raw_input_file_status(raw_input_files.get("exchange_info_raw"))
    funding_raw = _raw_input_file_status(raw_input_files.get("funding_info_raw"))
    bundle_status = _btc_manual_import_bundle_status(payload, root)
    blockers = _btc_manual_metadata_import_blockers(
        path=path,
        payload=payload,
        exchange_raw=exchange_raw,
        funding_raw=funding_raw,
    )
    blockers.extend(_btc_manual_import_bundle_blockers(payload, bundle_status))
    blockers = _merge_blockers(blockers)
    valid_for_completion = not blockers
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "dry_run": bool(payload.get("dry_run", False)),
        "captured_at": payload.get("captured_at"),
        "bundle_dir": payload.get("bundle_dir"),
        "bundle_dir_exists": bool(bundle_status["exists"]),
        "bundle_dir_matches_selected": bool(bundle_status["matches_selected_bundle"]),
        "bundle_exchange_info_exists": bool(bundle_status["exchange_info_exists"]),
        "bundle_funding_info_exists": bool(bundle_status["funding_info_exists"]),
        "bundle_exchange_info_output_hash_verified": bool(bundle_status["exchange_info_output_hash_verified"]),
        "bundle_funding_info_output_hash_verified": bool(bundle_status["funding_info_output_hash_verified"]),
        "writes_performed": bool(payload.get("writes_performed", False)),
        "exchange_info_verified": bool(payload.get("exchange_info_verified", False)),
        "funding_info_verified": bool(payload.get("funding_info_verified", False)),
        "valid_for_completion": valid_for_completion,
        "raw_input_files": {
            "exchange_info_raw": exchange_raw,
            "funding_info_raw": funding_raw,
        },
        "post_import_validation_command": payload.get("post_import_validation_command"),
        "blockers": blockers,
    }


def _raw_input_file_status(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    return {
        "path": payload.get("path"),
        "exists": bool(payload.get("exists", False)),
        "size_bytes": payload.get("size_bytes"),
        "sha256": payload.get("sha256"),
        "http_status_file": payload.get("http_status_file"),
        "http_status": payload.get("http_status"),
        "http_status_verified": payload.get("http_status_verified") is True,
    }


def _btc_manual_metadata_import_blockers(
    *,
    path: Path,
    payload: Mapping[str, Any],
    exchange_raw: Mapping[str, Any],
    funding_raw: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not path.exists():
        blockers.append("btc_manual_metadata_import_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    if payload.get("schema_version") != "btc_manual_metadata_import_report_v1":
        blockers.append("btc_manual_metadata_import_schema_version_missing_or_invalid")
    if payload.get("status") != "verified":
        blockers.append("btc_manual_metadata_import_not_verified")
    if payload.get("writes_performed") is not True:
        blockers.append("btc_manual_metadata_import_write_not_performed")
    if payload.get("exchange_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_exchange_info_not_verified")
    if payload.get("funding_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_funding_info_not_verified")
    if not _non_empty_text(payload.get("bundle_dir")):
        blockers.append("btc_manual_metadata_import_bundle_dir_missing")
    if not _utc_capture_timestamp(payload.get("captured_at")):
        blockers.append("btc_manual_metadata_import_captured_at_missing")
    if payload.get("post_import_validation_command") != "make validate-btc-public-data-bundle":
        blockers.append("btc_manual_metadata_import_validation_command_missing")
    if not _raw_input_file_verified(exchange_raw):
        blockers.append("btc_exchange_info_raw_import_provenance_missing")
    if not _raw_input_file_verified(funding_raw):
        blockers.append("btc_funding_info_raw_import_provenance_missing")
    if not _raw_input_http_status_verified(exchange_raw):
        blockers.append("btc_exchange_info_raw_http_status_not_200")
    if not _raw_input_http_status_verified(funding_raw):
        blockers.append("btc_funding_info_raw_http_status_not_200")
    return _merge_blockers(blockers)


def _btc_manual_import_bundle_status(payload: Mapping[str, Any], root: Path) -> dict[str, Any]:
    selected_bundle = _selected_btc_bundle_dir(root)
    bundle_dir = _resolve_path(payload.get("bundle_dir"), root)
    exists = bool(bundle_dir and bundle_dir.exists() and bundle_dir.is_dir())
    return {
        "selected_bundle_configured": selected_bundle is not None,
        "exists": exists,
        "matches_selected_bundle": bool(bundle_dir and selected_bundle and _same_resolved_path(bundle_dir, selected_bundle)),
        "exchange_info_exists": bool(exists and bundle_dir and (bundle_dir / "exchange_info.json").exists()),
        "funding_info_exists": bool(exists and bundle_dir and (bundle_dir / "funding_info.json").exists()),
        "exchange_info_output_hash_verified": _btc_output_hash_verified(
            payload,
            root=root,
            bundle_dir=bundle_dir,
            prefix="exchange_info",
            filename="exchange_info.json",
        ),
        "funding_info_output_hash_verified": _btc_output_hash_verified(
            payload,
            root=root,
            bundle_dir=bundle_dir,
            prefix="funding_info",
            filename="funding_info.json",
        ),
    }


def _btc_manual_import_bundle_blockers(payload: Mapping[str, Any], status: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not _non_empty_text(payload.get("bundle_dir")):
        return blockers
    if not status["selected_bundle_configured"]:
        blockers.append("btc_manual_metadata_import_selected_bundle_config_missing")
    if not status["exists"]:
        blockers.append("btc_manual_metadata_import_bundle_dir_missing_on_disk")
    if status["selected_bundle_configured"] and not status["matches_selected_bundle"]:
        blockers.append("btc_manual_metadata_import_bundle_dir_not_selected_bundle")
    if status["exists"] and not status["exchange_info_exists"]:
        blockers.append("btc_manual_metadata_import_bundle_exchange_info_missing")
    if status["exists"] and not status["funding_info_exists"]:
        blockers.append("btc_manual_metadata_import_bundle_funding_info_missing")
    if status["exists"] and not status["exchange_info_output_hash_verified"]:
        blockers.append("btc_manual_metadata_import_exchange_info_output_hash_mismatch")
    if status["exists"] and not status["funding_info_output_hash_verified"]:
        blockers.append("btc_manual_metadata_import_funding_info_output_hash_mismatch")
    return blockers


def _selected_btc_bundle_dir(root: Path) -> Path | None:
    return selected_btc_perpetual_bundle_dir(root, root / BTC_SOURCE_CONFIG)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _resolve_path(value: object, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _btc_output_hash_verified(
    payload: Mapping[str, Any],
    *,
    root: Path,
    bundle_dir: Path | None,
    prefix: str,
    filename: str,
) -> bool:
    expected = bundle_dir / filename if bundle_dir else None
    reported_path = _resolve_path(payload.get(f"{prefix}_output_path"), root)
    reported_hash = payload.get(f"{prefix}_output_sha256")
    return bool(
        expected
        and expected.exists()
        and reported_path
        and _same_resolved_path(reported_path, expected)
        and isinstance(reported_hash, str)
        and SHA256_RE.fullmatch(reported_hash)
        and _sha256(expected) == reported_hash
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_input_file_verified(payload: Mapping[str, Any]) -> bool:
    return bool(
        payload.get("exists") is True
        and isinstance(payload.get("path"), str)
        and bool(str(payload.get("path")).strip())
        and isinstance(payload.get("size_bytes"), int)
        and payload.get("size_bytes") > 0
        and isinstance(payload.get("sha256"), str)
        and SHA256_RE.fullmatch(str(payload.get("sha256")))
        and _raw_input_http_status_verified(payload)
    )


def _raw_input_http_status_verified(payload: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(payload.get("http_status_file"), str)
        and bool(str(payload.get("http_status_file")).strip())
        and payload.get("http_status") == 200
        and payload.get("http_status_verified") is True
    )


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc_capture_timestamp(value: object) -> bool:
    return isinstance(value, str) and bool(UTC_CAPTURE_RE.fullmatch(value))


def _btc_objective_completion_status(root: Path) -> dict[str, Any]:
    path = root / BTC_OBJECTIVE_COMPLETION_AUDIT_REPORT
    payload = _read_json(path)
    requirements = _mapping(payload.get("requirements"))
    incomplete = _list_of_strings(payload.get("incomplete_requirements"))
    complete = [
        name
        for name, value in requirements.items()
        if isinstance(value, Mapping) and value.get("status") == "complete"
    ]
    blockers = []
    if not path.exists():
        blockers.append("btc_objective_completion_audit_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "goal_complete": bool(payload.get("goal_complete", False)),
        "complete_requirements": complete,
        "incomplete_requirements": incomplete,
        "next_required_action": str(payload.get("next_required_action", "manual_capture_from_allowed_network")),
        "blockers": _merge_blockers(blockers),
    }


def _btc_cost_model_status(root: Path) -> dict[str, Any]:
    path = root / BTC_COST_MODEL_REPORT
    payload = _read_json(path)
    funding = _mapping(payload.get("funding_model"))
    fee = _mapping(payload.get("fee_model"))
    slip = _mapping(payload.get("slippage_model"))
    mark = _mapping(payload.get("mark_price_model"))
    rules = _mapping(payload.get("exchange_rules"))
    blockers = []
    if not path.exists():
        blockers.append("btc_cost_model_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "funding_payment_in_ledger": bool(funding.get("funding_payment_in_ledger", False)),
        "fee_in_ledger": bool(fee.get("fee_in_ledger", False)),
        "slippage_in_ledger": bool(slip.get("slippage_in_ledger", False)),
        "mark_price_available": bool(mark.get("mark_price_available", False)),
        "exchange_rules_available": bool(
            rules.get("exchange_rules_available", rules.get("exchange_info_available", False))
        ),
        "blockers": _merge_blockers(blockers),
    }


def _btc_funding_ledger_status(root: Path) -> dict[str, Any]:
    path = root / BTC_FUNDING_LEDGER_REPORT
    payload = _read_json(path)
    blockers = []
    if not path.exists():
        blockers.append("btc_funding_ledger_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": "pass" if payload.get("funding_payment_in_ledger", False) else "fail",
        "report_path": _relpath(path, root) if path.exists() else None,
        "funding_payment_in_ledger": bool(payload.get("funding_payment_in_ledger", False)),
        "funding_payment_count": int(payload.get("funding_payment_count", 0) or 0),
        "funding_pnl_total": float(payload.get("funding_pnl_total", 0.0) or 0.0),
        "blockers": _merge_blockers(blockers),
    }


def _btc_fold_regime_status(root: Path) -> dict[str, Any]:
    path = root / BTC_FOLD_REGIME_CONTRACT_REPORT
    payload = _read_json(path)
    fold = _mapping(payload.get("fold_definition"))
    classifier = _mapping(payload.get("regime_classifier"))
    blockers = []
    if not path.exists():
        blockers.append("btc_fold_regime_contract_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "fold_definition_version": str(fold.get("fold_definition_version", "")),
        "fold_count": int(fold.get("fold_count", 0) or 0),
        "regime_classifier_version": str(classifier.get("regime_classifier_version", "")),
        "gate_regimes": _list_of_strings(classifier.get("gate_regimes")),
        "diagnostic_regimes": _list_of_strings(classifier.get("diagnostic_regimes")),
        "blockers": _merge_blockers(blockers),
    }


def _btc_candidate_gate_status(root: Path) -> dict[str, Any]:
    path = root / BTC_CANDIDATE_GATE_AUDIT_REPORT
    payload = _read_json(path)
    required = _mapping(payload.get("candidate_gate_required_artifacts"))
    blockers = []
    if not path.exists():
        blockers.append("btc_candidate_gate_audit_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "fills_available": bool(required.get("fills", False)),
        "ledger_pnl_available": bool(required.get("ledger_pnl", False)),
        "funding_pnl_available": bool(required.get("funding_pnl", False)),
        "fee_pnl_available": bool(required.get("fee_pnl", False)),
        "slippage_pnl_available": bool(required.get("slippage_pnl", False)),
        "cost_stress_available": bool(required.get("cost_stress_report", False)),
        "walk_forward_available": bool(required.get("walk_forward_report", False)),
        "regime_available": bool(required.get("regime_report", False)),
        "pbo_dsr_available": bool(required.get("PBO_DSR_report", False)),
        "no_lookahead_available": bool(required.get("no_lookahead_report", False)),
        "tail_dependency_available": bool(required.get("tail_dependency_report", False)),
        "candidate_passed_internal_gate": int(payload.get("candidate_passed_internal_gate", 0) or 0),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "blockers": _merge_blockers(blockers),
    }


def _btc_candidate_metric_repair_status(root: Path) -> dict[str, Any]:
    path = root / BTC_CANDIDATE_METRIC_REPAIR_REPORT
    payload = _read_json(path)
    best_candidate = _mapping(payload.get("best_candidate"))
    metrics = _mapping(best_candidate.get("metrics"))
    blockers = []
    if not path.exists():
        blockers.append("btc_candidate_metric_repair_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "best_candidate_strategy_id": str(best_candidate.get("strategy_id", "")),
        "failed_metrics": _list_of_strings(payload.get("failed_metrics")),
        "event_profit_factor": _float_or_none(metrics.get("event_profit_factor")),
        "walk_forward_pass_rate": _float_or_none(metrics.get("walk_forward_pass_rate")),
        "regime_pass_rate": _float_or_none(metrics.get("regime_pass_rate")),
        "recommended_repair_actions": _btc_repair_action_summaries(payload.get("recommended_repair_actions")),
        "blockers": _merge_blockers(blockers),
    }


def _btc_candidate_bounded_retest_status(root: Path) -> dict[str, Any]:
    path = root / BTC_CANDIDATE_BOUNDED_RETEST_PLAN
    payload = _read_json(path)
    candidate = _mapping(payload.get("candidate"))
    context = _mapping(payload.get("metric_repair_context"))
    scope = _mapping(payload.get("test_scope"))
    guardrails = _mapping(payload.get("guardrails"))
    blockers = []
    if not path.exists():
        blockers.append("btc_candidate_bounded_retest_plan_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "retest_allowed": bool(payload.get("retest_allowed", False)),
        "bounded_parameter_search_allowed": bool(payload.get("bounded_parameter_search_allowed", False)),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "candidate_strategy_id": str(candidate.get("strategy_id", "")),
        "failed_metrics": _list_of_strings(context.get("failed_metrics")),
        "focus_failed_folds": _list_of_ints(scope.get("focus_failed_folds")),
        "ordinary_profit_factor_diagnostic_only": guardrails.get(
            "ordinary_profit_factor_diagnostic_only", True
        )
        is not False,
        "paper_or_live_unlock_allowed": bool(guardrails.get("paper_or_live_unlock_allowed", False)),
        "broker_calls_allowed": bool(guardrails.get("broker_calls_allowed", False)),
        "blockers": _merge_blockers(blockers),
    }


def _btc_next_hypothesis_decision_status(root: Path) -> dict[str, Any]:
    path = root / BTC_NEXT_HYPOTHESIS_DECISION_REPORT
    payload = _read_json(path)
    best_event = _mapping(payload.get("best_by_event_profit_factor"))
    best_wf = _mapping(payload.get("best_by_walk_forward_pass_rate"))
    blockers = []
    if not path.exists():
        blockers.append("btc_next_hypothesis_decision_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "decision": str(payload.get("decision", "")),
        "next_required_action": str(payload.get("next_required_action", "")),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "same_family_micro_search_allowed": bool(payload.get("same_family_micro_search_allowed", False)),
        "mode_count": int(payload.get("mode_count", 0) or 0),
        "event_profit_factor_pass_count": int(payload.get("event_profit_factor_pass_count", 0) or 0),
        "walk_forward_pass_rate_pass_count": int(payload.get("walk_forward_pass_rate_pass_count", 0) or 0),
        "best_event_mode": str(best_event.get("mode", "")),
        "best_event_profit_factor": _float_or_none(best_event.get("event_profit_factor")),
        "best_event_walk_forward_pass_rate": _float_or_none(best_event.get("walk_forward_pass_rate")),
        "best_wf_mode": str(best_wf.get("mode", "")),
        "best_wf_event_profit_factor": _float_or_none(best_wf.get("event_profit_factor")),
        "best_wf_pass_rate": _float_or_none(best_wf.get("walk_forward_pass_rate")),
        "blockers": _merge_blockers(blockers),
    }


def _btc_strategy_family_roadmap_status(root: Path) -> dict[str, Any]:
    path = root / BTC_STRATEGY_FAMILY_ROADMAP_REPORT
    payload = _read_json(path)
    selected = _mapping(payload.get("selected_next_family"))
    prerequisites = _mapping(payload.get("data_prerequisites"))
    blockers = []
    if not path.exists():
        blockers.append("btc_strategy_family_roadmap_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": str(payload.get("status", "missing") or "missing"),
        "report_path": _relpath(path, root) if path.exists() else None,
        "decision": str(payload.get("decision", "")),
        "next_required_action": str(payload.get("next_required_action", "")),
        "selected_family_id": str(selected.get("family_id", "")),
        "selected_family": str(selected.get("family", "")),
        "selected_provider": str(prerequisites.get("selected_provider", "")),
        "selected_bundle_id": str(prerequisites.get("selected_bundle_id", "")),
        "selected_bundle_duration_days": _float_or_none(prerequisites.get("selected_bundle_duration_days")),
        "min_required_history_days": _float_or_none(prerequisites.get("min_required_history_days")),
        "funding_rate_record_count": int(prerequisites.get("funding_rate_record_count", 0) or 0),
        "min_required_funding_events": int(prerequisites.get("min_required_funding_events", 0) or 0),
        "hypothesis_distribution_allowed": bool(payload.get("hypothesis_distribution_allowed", False)),
        "candidate_generation_allowed": bool(payload.get("candidate_generation_allowed", False)),
        "strategy_skeleton_generation_allowed": bool(payload.get("strategy_skeleton_generation_allowed", False)),
        "promotion_allowed": bool(payload.get("promotion_allowed", False)),
        "paper_review_pending_allowed": bool(payload.get("paper_review_pending_allowed", False)),
        "paper_or_live_unlock_allowed": bool(payload.get("paper_or_live_unlock_allowed", False)),
        "blockers": _merge_blockers(blockers),
    }


def _btc_repair_action_summaries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    actions: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        actions.append(
            {
                "name": str(item.get("name", "")),
                "priority": int(item.get("priority", 0) or 0),
                "status": str(item.get("status", "")),
            }
        )
    return actions


def _btc_tail_dependency_status(root: Path) -> dict[str, Any]:
    path = root / BTC_TAIL_DEPENDENCY_REPORT
    payload = _read_json(path)
    blockers = []
    if not path.exists():
        blockers.append("btc_tail_dependency_report_missing")
    blockers.extend(_list_of_strings(payload.get("blockers")))
    return {
        "status": "pass" if payload.get("tail_dependency_pass", False) else "fail",
        "report_path": _relpath(path, root) if path.exists() else None,
        "tail_event_count": int(payload.get("tail_event_count", 0) or 0),
        "tail_dependency_pass": bool(payload.get("tail_dependency_pass", False)),
        "single_event_pnl_contribution_ratio": float(
            payload.get("single_event_pnl_contribution_ratio", 0.0) or 0.0
        ),
        "blockers": _merge_blockers(blockers),
    }


def _build_us_equity_summary(root: Path) -> dict[str, Any]:
    data_lineage = _us_data_lineage(root)
    factor_evidence = _us_factor_evidence(root)
    portfolio_evidence = _us_portfolio_evidence(root)
    candidates = _us_current_candidates(root)
    current_factor_candidates = _us_current_factor_candidates(factor_evidence)
    blockers = _merge_blockers(
        data_lineage.get("blockers", []),
        factor_evidence.get("blocker_reasons", factor_evidence.get("blockers", [])),
        portfolio_evidence.get("blockers", []),
    )
    return {
        "status": "mainline",
        "latest_data_status": data_lineage.get("data_status_report")
        or data_lineage.get("latest_data_manifest"),
        "latest_factor_evidence": factor_evidence.get("factor_evidence_pack")
        or factor_evidence.get("latest_factor_mining_report"),
        "latest_portfolio_report": portfolio_evidence.get("portfolio_canonical_report")
        or portfolio_evidence.get("latest_portfolio_run_manifest"),
        "factor_evidence_status": factor_evidence.get("factor_evidence_status", "missing"),
        "factor_count": int(factor_evidence.get("factor_count", 0) or 0),
        "factor_pass_count": int(factor_evidence.get("factor_pass_count", 0) or 0),
        "factor_fail_count": int(factor_evidence.get("factor_fail_count", 0) or 0),
        "current_factor_candidates": current_factor_candidates,
        "blocker_reasons": blockers,
        "data_lineage": data_lineage,
        "factor_evidence": factor_evidence,
        "portfolio_evidence": portfolio_evidence,
        "blockers": blockers,
        "allowed_next_actions": [
            "build_us_equity_data_status_report",
            "standardize_factor_evidence_pack",
            "internal_event_backtest_required",
        ],
        "current_candidates": candidates,
    }


def _us_data_lineage(root: Path) -> dict[str, Any]:
    data_status_path = root / US_EQUITY_DATA_STATUS_REPORT
    universe_manifest_path = root / US_EQUITY_UNIVERSE_MANIFEST
    corporate_action_report_path = root / US_EQUITY_CORPORATE_ACTION_REPORT
    universe_snapshot_manifest_path = root / US_EQUITY_UNIVERSE_SNAPSHOT_MANIFEST
    corporate_action_status_report_path = root / US_EQUITY_CORPORATE_ACTION_STATUS_REPORT
    survivorship_audit_report_path = root / US_EQUITY_SURVIVORSHIP_AUDIT_REPORT
    provider_capability_matrix_path = root / US_EQUITY_PROVIDER_CAPABILITY_MATRIX
    production_bundle_preflight_report_path = root / US_EQUITY_PRODUCTION_BUNDLE_PREFLIGHT_REPORT
    provider_verification_report_path = root / US_EQUITY_PROVIDER_VERIFICATION_REPORT
    data_status = _read_json(data_status_path)
    universe_manifest = _read_json(universe_manifest_path)
    corporate_action_report = _read_json(corporate_action_report_path)
    universe_snapshot_manifest = _read_json(universe_snapshot_manifest_path)
    corporate_action_status_report = _read_json(corporate_action_status_report_path)
    survivorship_audit_report = _read_json(survivorship_audit_report_path)
    provider_capability_matrix = _read_json(provider_capability_matrix_path)
    provider_verification_report = _read_json(provider_verification_report_path)
    manifest_paths = [
        path
        for path in sorted((root / DATA_MANIFEST_ROOT).glob("*.json"))
        if not path.stem.startswith("run_")
    ]
    manifest_items = [
        (path, payload)
        for path in manifest_paths
        for payload in [_read_json(path)]
        if _looks_like_us_equity_manifest(payload)
    ]
    manifests = [payload for _, payload in manifest_items]
    latest_path = _latest_existing_path([path for path, _ in manifest_items])
    survivorship_values = sorted(
        {
            str(item.get("survivorship_bias_risk", "unknown") or "unknown")
            for item in manifests
        }
    )
    adjustment_policies = sorted(
        {
            str(
                item.get("adjustment_policy")
                or item.get("corporate_action_adjustment")
                or item.get("adjustment")
                or "unknown"
            )
            for item in manifests
        }
    )
    blockers: list[str] = []
    if not data_status_path.exists():
        blockers.append("us_equity_data_status_report_missing")
    if not manifests:
        blockers.append("us_equity_data_manifest_missing")
    if not universe_manifest_path.exists():
        blockers.append("us_equity_universe_manifest_missing")
    elif isinstance(universe_manifest.get("blockers"), list):
        blockers.extend(str(item) for item in universe_manifest["blockers"])
    if not corporate_action_report_path.exists():
        blockers.append("us_equity_corporate_action_report_missing")
    elif isinstance(corporate_action_report.get("blockers"), list):
        blockers.extend(str(item) for item in corporate_action_report["blockers"])
    if not universe_snapshot_manifest_path.exists():
        blockers.append("us_equity_universe_snapshot_manifest_missing")
    elif isinstance(universe_snapshot_manifest.get("blockers"), list):
        blockers.extend(str(item) for item in universe_snapshot_manifest["blockers"])
    if not corporate_action_status_report_path.exists():
        blockers.append("us_equity_corporate_action_status_report_missing")
    elif isinstance(corporate_action_status_report.get("blockers"), list):
        blockers.extend(str(item) for item in corporate_action_status_report["blockers"])
    if not survivorship_audit_report_path.exists():
        blockers.append("us_equity_survivorship_audit_report_missing")
    elif isinstance(survivorship_audit_report.get("blockers"), list):
        blockers.extend(str(item) for item in survivorship_audit_report["blockers"])
    if not provider_capability_matrix_path.exists():
        blockers.append("us_equity_provider_capability_matrix_missing")
    elif isinstance(provider_capability_matrix.get("blockers"), list):
        blockers.extend(str(item) for item in provider_capability_matrix["blockers"])
    production_bundle_preflight_report = _read_json(production_bundle_preflight_report_path)
    if not production_bundle_preflight_report_path.exists():
        blockers.append("us_equity_production_bundle_preflight_report_missing")
    elif isinstance(production_bundle_preflight_report.get("blockers"), list):
        blockers.extend(str(item) for item in production_bundle_preflight_report["blockers"])
    if not provider_verification_report_path.exists():
        blockers.append("us_equity_provider_verification_report_missing")
    elif isinstance(provider_verification_report.get("blockers"), list):
        blockers.extend(str(item) for item in provider_verification_report["blockers"])
    if isinstance(data_status.get("blockers"), list):
        blockers.extend(str(item) for item in data_status["blockers"])
    if not survivorship_values or "unknown" in survivorship_values:
        blockers.append("us_equity_survivorship_status_unconfirmed")
    blockers = _merge_blockers(blockers)
    data_status_report = _relpath(data_status_path, root) if data_status_path.exists() else None
    universe_manifest_report = _relpath(universe_manifest_path, root) if universe_manifest_path.exists() else None
    corporate_action_report_ref = (
        _relpath(corporate_action_report_path, root)
        if corporate_action_report_path.exists()
        else None
    )
    universe_snapshot_manifest_ref = (
        _relpath(universe_snapshot_manifest_path, root)
        if universe_snapshot_manifest_path.exists()
        else None
    )
    corporate_action_status_report_ref = (
        _relpath(corporate_action_status_report_path, root)
        if corporate_action_status_report_path.exists()
        else None
    )
    survivorship_audit_report_ref = (
        _relpath(survivorship_audit_report_path, root)
        if survivorship_audit_report_path.exists()
        else None
    )
    provider_capability_matrix_ref = (
        _relpath(provider_capability_matrix_path, root)
        if provider_capability_matrix_path.exists()
        else None
    )
    production_bundle_preflight_report_ref = (
        _relpath(production_bundle_preflight_report_path, root)
        if production_bundle_preflight_report_path.exists()
        else None
    )
    provider_verification_report_ref = (
        _relpath(provider_verification_report_path, root)
        if provider_verification_report_path.exists()
        else None
    )
    status = "missing" if not manifests else ("complete" if not blockers else "partial")
    return {
        "status": status,
        "data_status_report": data_status_report,
        "latest_data_manifest": _relpath(latest_path, root) if latest_path else None,
        "manifest_count": len(manifests),
        "data_versions": [
            str(item.get("data_version", ""))
            for item in manifests
            if item.get("data_version")
        ][:50],
        "symbols": sorted({str(item.get("symbol", "")) for item in manifests if item.get("symbol")})[:100],
        "universe_manifest": universe_manifest_report,
        "corporate_action_report": corporate_action_report_ref,
        "data_lineage_grade": _mapping(data_status.get("data_lineage_grade")) or {
            "value": "L0_fixture",
            "reason": "data lineage grade missing",
        },
        "promotion_clean": bool(data_status.get("promotion_clean", False)),
        "universe_snapshot_manifest": universe_snapshot_manifest_ref,
        "corporate_action_status_report": corporate_action_status_report_ref,
        "survivorship_audit_report": survivorship_audit_report_ref,
        "provider_capability_matrix": provider_capability_matrix_ref,
        "production_bundle_preflight_report": production_bundle_preflight_report_ref,
        "provider_verification_report": provider_verification_report_ref,
        "selected_provider": str(
            provider_verification_report.get("selected_provider")
            or data_status.get("selected_provider")
            or "none"
        ),
        "source_type": str(provider_verification_report.get("source_type", "none") or "none"),
        "bundle_id": provider_verification_report.get("bundle_id"),
        "production_bundle_preflight_pass": bool(
            provider_verification_report.get(
                "production_bundle_preflight_pass",
                production_bundle_preflight_report.get("production_bundle_preflight_pass", False),
            )
        ),
        "explicit_bundle_selection_confirmed": bool(
            provider_verification_report.get("explicit_bundle_selection_confirmed", False)
        ),
        "promotion_clean_allowed_by_config": bool(
            provider_verification_report.get(
                "promotion_clean_allowed_by_config",
                production_bundle_preflight_report.get("promotion_clean_allowed_by_config", False),
            )
        ),
        "promotion_clean_allowed_by_manifest": bool(
            provider_verification_report.get(
                "promotion_clean_allowed_by_manifest",
                production_bundle_preflight_report.get("promotion_clean_allowed_by_manifest", False),
            )
        ),
        "provider_verified_for_promotion": bool(
            provider_verification_report.get("promotion_clean", False)
        ),
        "point_in_time_universe_confirmed": bool(
            provider_verification_report.get("point_in_time_universe_confirmed", False)
            or universe_snapshot_manifest.get("point_in_time_confirmed", False)
        ),
        "delisting_coverage_confirmed": bool(
            provider_verification_report.get("delisting_coverage_confirmed", False)
            or survivorship_audit_report.get("delisted_symbols_included", False)
        ),
        "corporate_action_event_source_available": bool(
            provider_verification_report.get("corporate_action_event_source_available", False)
            or corporate_action_status_report.get("corporate_action_event_source_available", False)
        ),
        "identifier_mapping_available": bool(
            provider_verification_report.get("identifier_mapping_available", False)
        ),
        "adjustment_reproducibility_confirmed": bool(
            provider_verification_report.get("adjustment_reproducibility_confirmed", False)
            or corporate_action_status_report.get("adjustment_reproducible", False)
        ),
        "survivorship_clean": bool(
            provider_verification_report.get("survivorship_clean", False)
        ),
        "survivorship_status": "mixed" if len(survivorship_values) > 1 else (survivorship_values[0] if survivorship_values else "unknown"),
        "adjustment_policies": adjustment_policies,
        "blockers": blockers,
    }


def _us_factor_evidence(root: Path) -> dict[str, Any]:
    factor_evidence_pack_path = root / US_EQUITY_FACTOR_EVIDENCE_PACK
    factor_evidence_pack = _read_json(factor_evidence_pack_path)
    factor_mining_reports = [
        path
        for path in sorted((root / FACTOR_MINING_ROOT).glob("*.json"))
        if not path.name.endswith("_correlation.json")
    ]
    generated_strategies = sorted((root / GENERATED_STRATEGIES_ROOT).glob("*.json"))
    latest_factor_mining = _latest_existing_path(factor_mining_reports)
    generated_factors_exists = (root / GENERATED_FACTORS_PATH).exists()
    has_real_factor_evidence_pack = bool(
        factor_evidence_pack_path.exists()
        and factor_evidence_pack.get("is_data_dependent") is True
        and int(factor_evidence_pack.get("factor_count", 0) or 0) > 0
    )
    blockers: list[str] = []
    if not factor_evidence_pack_path.exists():
        blockers.append("us_equity_factor_evidence_pack_missing")
    if not factor_evidence_pack_path.exists() and not latest_factor_mining and not generated_strategies:
        blockers.append("us_equity_factor_evidence_missing")
    if not generated_factors_exists and not has_real_factor_evidence_pack:
        blockers.append("us_equity_generated_factor_registry_missing")
    if isinstance(factor_evidence_pack.get("blocker_reasons"), list):
        blockers.extend(str(item) for item in factor_evidence_pack["blocker_reasons"])
    if isinstance(factor_evidence_pack.get("blockers"), list):
        blockers.extend(str(item) for item in factor_evidence_pack["blockers"])
    status = "missing"
    if factor_evidence_pack_path.exists():
        status = str(factor_evidence_pack.get("status", "partial") or "partial")
    elif latest_factor_mining or generated_strategies or generated_factors_exists:
        status = "partial"
    rows = factor_evidence_pack.get("factor_evidence_rows") or factor_evidence_pack.get("factor_rows") or []
    row_items = [item for item in rows if isinstance(item, Mapping)] if isinstance(rows, list) else []
    factor_count = int(factor_evidence_pack.get("factor_count", len(row_items)) or 0)
    factor_pass_count = int(
        factor_evidence_pack.get(
            "factor_pass_count",
            sum(
                1
                for row in row_items
                if _mapping(row.get("gates")).get("overall_status") == "pass"
                or row.get("overall_status") == "pass"
            ),
        )
        or 0
    )
    factor_fail_count = int(
        factor_evidence_pack.get(
            "factor_fail_count",
            max(0, factor_count - factor_pass_count),
        )
        or 0
    )
    current_factor_candidates = [
        str(item)
        for item in factor_evidence_pack.get("current_factor_candidates", [])
        if str(item)
    ]
    if not current_factor_candidates:
        current_factor_candidates = [
            str(row.get("factor_name") or row.get("factor_id"))
            for row in row_items
            if row.get("allowed_next_action") == "portfolio_candidate_review"
        ]
    pack_lineage = _mapping(factor_evidence_pack.get("data_lineage"))
    inherited_data_blockers = _list_of_strings(
        factor_evidence_pack.get("inherited_data_blockers")
        or pack_lineage.get("inherited_data_blockers")
    )
    inherited_provider_blockers = _list_of_strings(
        factor_evidence_pack.get("inherited_provider_blockers")
        or pack_lineage.get("inherited_provider_blockers")
    )
    if pack_lineage.get("promotion_clean") is False:
        current_factor_candidates = []
    factor_evidence_status = _factor_evidence_status(
        status=status,
        factor_count=factor_count,
        factor_pass_count=factor_pass_count,
    )
    return {
        "status": status if status in {"missing", "partial", "complete"} else "partial",
        "factor_evidence_status": factor_evidence_status,
        "latest_factor_evidence": _relpath(factor_evidence_pack_path, root) if factor_evidence_pack_path.exists() else None,
        "factor_evidence_pack": _relpath(factor_evidence_pack_path, root) if factor_evidence_pack_path.exists() else None,
        "latest_factor_mining_report": _relpath(latest_factor_mining, root) if latest_factor_mining else None,
        "generated_factors_path": str(GENERATED_FACTORS_PATH) if generated_factors_exists else None,
        "generated_strategy_count": len(generated_strategies),
        "factor_count": factor_count,
        "factor_pass_count": factor_pass_count,
        "factor_fail_count": factor_fail_count,
        "current_factor_candidates": current_factor_candidates,
        "inherited_data_blockers": inherited_data_blockers,
        "inherited_provider_blockers": inherited_provider_blockers,
        "allowed_next_action_summary": str(factor_evidence_pack.get("allowed_next_action", "research_only") or "research_only"),
        "selected_factor_count": int(factor_evidence_pack.get("selected_factor_count", 0) or 0),
        "selected_factor_ids": [str(item) for item in factor_evidence_pack.get("selected_factor_ids", [])],
        "blocker_reasons": _merge_blockers(blockers),
        "blockers": _merge_blockers(blockers),
    }


def _factor_evidence_status(
    *,
    status: str,
    factor_count: int,
    factor_pass_count: int,
) -> str:
    if status == "missing" or factor_count <= 0:
        return "missing"
    if factor_pass_count > 0:
        return "passed"
    return "failed"


def _us_current_factor_candidates(factor_evidence: Mapping[str, Any]) -> list[str]:
    candidates = [
        str(item)
        for item in factor_evidence.get("current_factor_candidates", [])
        if str(item)
    ]
    return candidates if int(factor_evidence.get("factor_pass_count", 0) or 0) > 0 else []


def _us_portfolio_evidence(root: Path) -> dict[str, Any]:
    canonical_report_path = root / US_EQUITY_PORTFOLIO_CANONICAL_REPORT
    canonical_report = _read_json(canonical_report_path)
    run_manifests = sorted((root / PORTFOLIO_RUNS_ROOT).glob("*/run_manifest.json"))
    latest_manifest = _latest_existing_path(run_manifests)
    blockers: list[str] = []
    if not canonical_report_path.exists():
        blockers.append("us_equity_portfolio_canonical_report_missing")
    if not latest_manifest:
        blockers.append("us_equity_portfolio_report_missing")
    if isinstance(canonical_report.get("blockers"), list):
        blockers.extend(str(item) for item in canonical_report["blockers"])
    else:
        blockers.append("us_equity_event_ledger_portfolio_backtest_required")
    status = "missing"
    if canonical_report_path.exists():
        status = str(canonical_report.get("status", "partial") or "partial")
    elif latest_manifest:
        status = "research_only"
    return {
        "status": status if status in {"missing", "research_only", "partial", "complete"} else "research_only",
        "portfolio_canonical_report": _relpath(canonical_report_path, root) if canonical_report_path.exists() else None,
        "latest_portfolio_run_manifest": _relpath(latest_manifest, root) if latest_manifest else None,
        "portfolio_run_count": len(run_manifests),
        "event_ledger_status": str(
            _mapping(canonical_report.get("event_ledger_status")).get("status", "missing")
        ),
        "promotion_ready": bool(canonical_report.get("promotion_ready", False)),
        "blockers": _merge_blockers(blockers),
    }


def _failure_explanations(*, us_equity: Mapping[str, Any], btc: Mapping[str, Any]) -> dict[str, Any]:
    data_lineage = _mapping(us_equity.get("data_lineage"))
    factor_evidence = _mapping(us_equity.get("factor_evidence"))
    portfolio = _mapping(us_equity.get("portfolio_evidence"))
    btc_data = _mapping(btc.get("data_status"))
    btc_cost = _mapping(btc.get("cost_model_status"))
    btc_fold = _mapping(btc.get("fold_regime_status"))
    btc_gate = _mapping(btc.get("candidate_gate_audit"))
    btc_metric_repair = _mapping(btc.get("candidate_metric_repair_status"))
    btc_bounded_retest = _mapping(btc.get("candidate_bounded_retest_status"))
    btc_next_hypothesis = _mapping(btc.get("next_hypothesis_decision_status"))
    btc_strategy_family = _mapping(btc.get("strategy_family_roadmap_status"))
    btc_objective = _mapping(btc.get("objective_completion_status"))
    btc_objective_incomplete = _list_of_strings(btc_objective.get("incomplete_requirements"))
    btc_objective_reasons = [
        f"btc_objective_incomplete:{name}" for name in btc_objective_incomplete
    ]
    btc_reasons = _merge_blockers(
        btc_objective_reasons,
        _list_of_strings(btc.get("blockers")),
        _list_of_strings(btc_data.get("blockers")),
        _list_of_strings(btc_cost.get("blockers")),
        _list_of_strings(btc_fold.get("blockers")),
        _list_of_strings(btc_gate.get("blockers")),
        _list_of_strings(btc_metric_repair.get("blockers")),
        _list_of_strings(btc_bounded_retest.get("blockers")),
        _list_of_strings(btc_next_hypothesis.get("blockers")),
        _list_of_strings(btc_strategy_family.get("blockers")),
        _list_of_strings(btc.get("attribution_only")),
    )
    return {
        "data_lineage": {
            "status": "blocked",
            "top_reasons": _top_reasons(_list_of_strings(data_lineage.get("blockers"))),
            "next_required_action": "manual_data_acquisition",
        },
        "factor_evidence": {
            "status": "blocked",
            "top_reasons": _top_reasons(_list_of_strings(factor_evidence.get("blockers"))),
            "next_required_action": "rerun_after_L4_data",
        },
        "portfolio": {
            "status": "blocked",
            "top_reasons": _top_reasons(_list_of_strings(portfolio.get("blockers"))),
            "next_required_action": "portfolio_event_ledger_after_factor_pass",
        },
        "btc": {
            "status": "incomplete" if btc_objective_incomplete else "archived",
            "top_reasons": _top_reasons(btc_reasons),
            "next_required_action": str(
                btc_objective.get("next_required_action", "manual_exchange_and_funding_info_capture_only")
            ),
            "complete_requirements": _list_of_strings(btc_objective.get("complete_requirements")),
            "incomplete_requirements": btc_objective_incomplete,
        },
        "paper_live": {
            "status": "locked",
            "top_reasons": [
                "paper_queue_status_locked",
                "live_status_frozen",
                "candidate_passed_internal_gate_0",
            ],
            "next_required_action": "none_until_internal_gate_pass",
        },
    }


def _us_current_candidates(root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in sorted((root / QLIB_RUNS_ROOT).glob("*/qlib_strategy_manifest.json")):
        manifest = _read_json(path)
        if not manifest:
            continue
        candidates.append(
            {
                "name": str(manifest.get("strategy_id") or manifest.get("run_id") or path.parent.name),
                "source": "qlib",
                "status": "evidence_candidate",
                "evidence_path": _relpath(path, root),
                "data_versions": [str(item) for item in manifest.get("data_versions", [])],
                "blockers": [
                    "internal_event_ledger_backtest_required",
                    "cost_stress_required",
                    "walk_forward_required",
                    "regime_report_required",
                    "promotion_gate_required",
                ],
                "allowed_next_action": "internal_event_backtest_required",
            }
        )
    return candidates[:20]


def _merge_blockers(*groups: object) -> list[str]:
    blockers: list[str] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            text = str(item)
            if text and text not in blockers:
                blockers.append(text)
    return blockers


def _top_reasons(values: list[str], limit: int = 10) -> list[str]:
    return _merge_blockers(values)[:limit]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _list_of_ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _btc_manual_input_statuses(value: object) -> list[dict[str, Any]]:
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


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _looks_like_data_manifest(data: Mapping[str, Any]) -> bool:
    return all(data.get(key) for key in ("data_version", "source", "symbol", "interval"))


def _looks_like_us_equity_manifest(data: Mapping[str, Any]) -> bool:
    if not _looks_like_data_manifest(data):
        return False
    source = str(data.get("source", "")).lower()
    asset_class = str(data.get("asset_class", "equity")).lower()
    return source in {"yfinance", "alpaca"} and asset_class == "equity"


def _latest_existing_path(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
