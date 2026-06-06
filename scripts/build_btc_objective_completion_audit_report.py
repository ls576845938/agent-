#!/usr/bin/env python3
"""Build a requirement-level audit for the current BTC repair objective."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")
BTC_SOURCE_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
PROVIDER_REPORT = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
READINESS_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json")
CAPTURE_ATTEMPT_REPORT = Path("artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json")
OPERATOR_PACKET_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json")
IMPORT_REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json")
FUNDING_LEDGER_REPORT = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
COMPRESSION_ATTRIBUTION_REPORT = Path(
    "artifacts/btc_candidate_attribution/latest_compression_expansion_attribution/attribution_report.json"
)
BTC_REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
HYPOTHESIS_V2_MANIFEST = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle/run_manifest.json")
HYPOTHESIS_V2_DECISION = Path(
    "artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle/hypothesis_decision_v2.json"
)
UTC_CAPTURE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_btc_objective_completion_audit_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    provider = _read_json(root / PROVIDER_REPORT)
    readiness = _read_json(root / READINESS_REPORT)
    capture = _read_json(root / CAPTURE_ATTEMPT_REPORT)
    operator_packet = _read_json(root / OPERATOR_PACKET_REPORT)
    import_report = _read_json(root / IMPORT_REPORT)
    funding = _read_json(root / FUNDING_LEDGER_REPORT)
    attribution = _read_json(root / COMPRESSION_ATTRIBUTION_REPORT)
    registry = _read_json(root / BTC_REGISTRY)
    v2_manifest = _read_json(root / HYPOTHESIS_V2_MANIFEST)
    v2_decision = _read_json(root / HYPOTHESIS_V2_DECISION)
    requirements = {
        "manual_exchange_info_capture": _manual_exchange_info_requirement(
            provider, readiness, capture, operator_packet, import_report, root
        ),
        "funding_info_endpoint_policy_repair": _funding_info_requirement(
            provider, readiness, capture, operator_packet, import_report, root
        ),
        "funding_ledger_net_pnl_integration": _funding_ledger_requirement(funding, root),
        "archive_compression_expansion_breakout": _compression_archive_requirement(attribution, registry),
        "btc_hypothesis_lab_v2_controlled_search": _hypothesis_v2_requirement(v2_manifest, v2_decision),
    }
    incomplete = [name for name, item in requirements.items() if item["status"] != "complete"]
    blockers = _dedupe([blocker for item in requirements.values() for blocker in item.get("blockers", [])])
    return {
        "schema_version": "btc_objective_completion_audit_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "status": "complete" if not incomplete else "incomplete",
        "goal_complete": not incomplete,
        "requirements": requirements,
        "incomplete_requirements": incomplete,
        "blockers": blockers,
        "next_required_action": "manual_capture_from_allowed_network" if incomplete else "none",
    }


def write_btc_objective_completion_audit_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_objective_completion_audit_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_objective_completion_audit_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_objective_completion_audit_report(payload, Path(args.output_root)))


def _manual_exchange_info_requirement(
    provider: Mapping[str, Any],
    readiness: Mapping[str, Any],
    capture: Mapping[str, Any],
    operator_packet: Mapping[str, Any],
    import_report: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    exchange_result = _mapping(_mapping(capture.get("endpoint_results")).get("exchange_info"))
    packet_status = _mapping(operator_packet.get("last_public_metadata_capture_status"))
    provider_verified = bool(provider.get("exchange_info_verified", False))
    import_verified = _manual_import_verified(import_report, root)
    complete = provider_verified and import_verified
    blockers: list[str] = []
    if not complete:
        if not provider_verified:
            blockers.append("btc_perpetual_exchange_info_not_verified")
        blockers.extend(_list_of_strings(exchange_result.get("blockers")))
        blockers.extend(_list_of_strings(operator_packet.get("blockers")))
        blockers.extend(_manual_import_blockers(import_report, root))
    return {
        "status": "complete" if complete else ("blocked_external_capture" if not provider_verified else "incomplete"),
        "evidence": {
            "provider_verification_report": str(PROVIDER_REPORT),
            "manual_readiness_report": str(READINESS_REPORT),
            "public_capture_attempt_report": str(CAPTURE_ATTEMPT_REPORT),
            "manual_capture_operator_packet": str(OPERATOR_PACKET_REPORT),
            "manual_metadata_import_report": str(IMPORT_REPORT),
        },
        "completion_criteria": _manual_metadata_completion_criteria(),
        "verified": provider_verified,
        "manual_capture_required": bool(_mapping(readiness.get("exchange_info")).get("manual_capture_required", True)),
        "operator_action": str(operator_packet.get("operator_action", "manual_capture_from_allowed_network")),
        "import_status": str(import_report.get("status", "missing") or "missing"),
        "import_writes_performed": bool(import_report.get("writes_performed", False)),
        "import_captured_at": import_report.get("captured_at"),
        "import_bundle_dir": _manual_import_bundle_status(import_report, root),
        "raw_input_files": _raw_input_files(import_report, root),
        "last_capture_status": str(exchange_result.get("capture_status", "missing") or "missing"),
        "last_http_status": exchange_result.get("http_status", packet_status.get("exchange_info_http_status")),
        "blockers": _dedupe(blockers),
    }


def _funding_info_requirement(
    provider: Mapping[str, Any],
    readiness: Mapping[str, Any],
    capture: Mapping[str, Any],
    operator_packet: Mapping[str, Any],
    import_report: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    funding_result = _mapping(_mapping(capture.get("endpoint_results")).get("funding_info"))
    packet_status = _mapping(operator_packet.get("last_public_metadata_capture_status"))
    provider_verified = bool(provider.get("funding_info_verified", False))
    endpoint_response_available = bool(provider.get("funding_info_endpoint_response_available", False))
    import_verified = _manual_import_verified(import_report, root)
    complete = provider_verified and endpoint_response_available and import_verified
    blockers: list[str] = []
    if not complete:
        if not provider_verified:
            blockers.append("btc_perpetual_funding_info_not_verified")
        if not endpoint_response_available:
            blockers.append("btc_funding_info_endpoint_response_not_available")
        blockers.extend(_list_of_strings(funding_result.get("blockers")))
        blockers.extend(_list_of_strings(operator_packet.get("blockers")))
        blockers.extend(_manual_import_blockers(import_report, root))
    return {
        "status": "complete" if complete else ("blocked_external_capture" if not provider_verified else "incomplete"),
        "evidence": {
            "provider_verification_report": str(PROVIDER_REPORT),
            "manual_readiness_report": str(READINESS_REPORT),
            "public_capture_attempt_report": str(CAPTURE_ATTEMPT_REPORT),
            "manual_capture_operator_packet": str(OPERATOR_PACKET_REPORT),
            "manual_metadata_import_report": str(IMPORT_REPORT),
        },
        "completion_criteria": _manual_metadata_completion_criteria(),
        "verified": provider_verified,
        "manual_capture_required": bool(_mapping(readiness.get("funding_info")).get("manual_capture_required", True)),
        "operator_action": str(operator_packet.get("operator_action", "manual_capture_from_allowed_network")),
        "import_status": str(import_report.get("status", "missing") or "missing"),
        "import_writes_performed": bool(import_report.get("writes_performed", False)),
        "import_captured_at": import_report.get("captured_at"),
        "import_bundle_dir": _manual_import_bundle_status(import_report, root),
        "raw_input_files": _raw_input_files(import_report, root),
        "endpoint_response_available": endpoint_response_available,
        "last_capture_status": str(funding_result.get("capture_status", "missing") or "missing"),
        "last_http_status": funding_result.get("http_status", packet_status.get("funding_info_http_status")),
        "blockers": _dedupe(blockers),
    }


def _funding_ledger_requirement(funding: Mapping[str, Any], root: Path) -> dict[str, Any]:
    reconciliation_delta = _float_or_none(funding.get("funding_adjusted_net_pnl_reconciliation_delta"))
    reconciled = (
        funding.get("funding_adjusted_net_pnl_reconciled") is True
        and reconciliation_delta is not None
        and abs(reconciliation_delta) <= 1e-9
    )
    ledger_status = _funding_adjusted_ledger_file_status(funding, root)
    funding_events_count = _int_or_none(funding.get("funding_events_count")) or 0
    funding_payment_count = _int_or_none(funding.get("funding_payment_count")) or 0
    complete = bool(
        funding.get("funding_payment_in_ledger", False)
        and funding.get("funding_merged_into_net_ledger", False)
        and funding_events_count > 0
        and funding_payment_count > 0
        and reconciled
        and ledger_status["exists"]
        and ledger_status["reconciled_to_report"]
    )
    blockers = []
    if funding.get("funding_payment_in_ledger") is not True:
        blockers.append("btc_funding_payment_not_in_ledger")
    if funding_events_count <= 0:
        blockers.append("btc_funding_events_missing_for_ledger_integration")
    if funding_payment_count <= 0:
        blockers.append("btc_funding_payments_missing_for_ledger_integration")
    if funding.get("funding_merged_into_net_ledger") is not True:
        blockers.append("btc_funding_not_merged_into_net_ledger")
    if not reconciled:
        blockers.append("btc_funding_adjusted_net_pnl_reconciliation_failed")
    if not ledger_status["exists"]:
        blockers.append("btc_funding_adjusted_trade_ledger_missing")
    if ledger_status["exists"] and not ledger_status["reconciled_to_report"]:
        blockers.append("btc_funding_adjusted_trade_ledger_report_mismatch")
    return {
        "status": "complete" if complete else "incomplete",
        "evidence": {"funding_ledger_report": str(FUNDING_LEDGER_REPORT)},
        "funding_payment_in_ledger": bool(funding.get("funding_payment_in_ledger", False)),
        "funding_merged_into_net_ledger": bool(funding.get("funding_merged_into_net_ledger", False)),
        "funding_events_count": funding_events_count,
        "funding_payment_count": funding_payment_count,
        "funding_adjusted_net_pnl_reconciled": reconciled,
        "funding_adjusted_net_pnl_reconciliation_delta": reconciliation_delta,
        "trade_ledger_net_pnl_total": funding.get("trade_ledger_net_pnl_total"),
        "funding_pnl_total": funding.get("funding_pnl_total"),
        "expected_funding_adjusted_net_pnl_total": funding.get("expected_funding_adjusted_net_pnl_total"),
        "funding_adjusted_net_pnl_total": funding.get("funding_adjusted_net_pnl_total"),
        "funding_adjusted_ledger_path": funding.get("funding_adjusted_ledger_path"),
        "funding_adjusted_ledger_exists": bool(ledger_status["exists"]),
        "funding_adjusted_ledger_reconciled_to_report": bool(ledger_status["reconciled_to_report"]),
        "funding_adjusted_ledger_trade_count": ledger_status["trade_count"],
        "funding_adjusted_ledger_funding_pnl_total": ledger_status["funding_pnl_total"],
        "funding_adjusted_ledger_net_pnl_before_total": ledger_status["net_pnl_before_total"],
        "funding_adjusted_ledger_net_pnl_after_total": ledger_status["net_pnl_after_total"],
        "blockers": _dedupe(blockers),
    }


def _compression_archive_requirement(attribution: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    item = _mapping(_mapping(registry.get("items")).get("compression_expansion_breakout"))
    registry_btc = _mapping(registry.get("btc"))
    complete = (
        attribution.get("status") == "archived"
        and attribution.get("allowed_next_action") == "archive_only"
        and attribution.get("paper_review_pending_allowed") is False
        and attribution.get("paper_review_pending_created") is False
        and attribution.get("promotion_ready") is False
        and attribution.get("paper_queue") == "LOCKED"
        and attribution.get("live") == "FROZEN"
        and item.get("status") == "archived"
        and item.get("next_action") == "do_not_retest_without_new_hypothesis"
        and item.get("archive_recommended") is True
        and item.get("limited_retest_allowed") is False
        and "compression_expansion_breakout" in _list_of_strings(registry_btc.get("archived_or_rejected"))
    )
    blockers = []
    if attribution.get("status") != "archived" or item.get("status") != "archived":
        blockers.append("btc_compression_expansion_not_archived")
    if attribution.get("allowed_next_action") != "archive_only":
        blockers.append("btc_compression_expansion_archive_next_action_not_archive_only")
    if item.get("next_action") != "do_not_retest_without_new_hypothesis":
        blockers.append("btc_compression_expansion_registry_next_action_allows_retest")
    if item.get("archive_recommended") is not True:
        blockers.append("btc_compression_expansion_archive_not_recommended")
    if item.get("limited_retest_allowed") is not False:
        blockers.append("btc_compression_expansion_limited_retest_not_disabled")
    if attribution.get("paper_review_pending_allowed") is not False or attribution.get("paper_review_pending_created") is not False:
        blockers.append("btc_compression_expansion_paper_review_not_locked")
    if attribution.get("promotion_ready") is not False:
        blockers.append("btc_compression_expansion_promotion_not_locked")
    if attribution.get("paper_queue") != "LOCKED" or attribution.get("live") != "FROZEN":
        blockers.append("btc_compression_expansion_paper_live_not_locked")
    if "compression_expansion_breakout" not in _list_of_strings(registry_btc.get("archived_or_rejected")):
        blockers.append("btc_compression_expansion_missing_from_archived_or_rejected")
    return {
        "status": "complete" if complete else "incomplete",
        "evidence": {
            "compression_attribution_report": str(COMPRESSION_ATTRIBUTION_REPORT),
            "btc_research_registry": str(BTC_REGISTRY),
        },
        "attribution_status": attribution.get("status"),
        "registry_status": item.get("status"),
        "allowed_next_action": attribution.get("allowed_next_action"),
        "registry_next_action": item.get("next_action"),
        "archive_recommended": bool(item.get("archive_recommended", False)),
        "limited_retest_allowed": bool(item.get("limited_retest_allowed", True)),
        "paper_review_pending_allowed": bool(attribution.get("paper_review_pending_allowed", True)),
        "paper_review_pending_created": bool(attribution.get("paper_review_pending_created", True)),
        "promotion_ready": bool(attribution.get("promotion_ready", True)),
        "paper_queue": attribution.get("paper_queue"),
        "live": attribution.get("live"),
        "archived_or_rejected": _list_of_strings(registry_btc.get("archived_or_rejected")),
        "blockers": _dedupe(blockers),
    }


def _hypothesis_v2_requirement(manifest: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(manifest.get("controlled_search_policy"))
    generated_artifacts = _list_of_strings(manifest.get("generated_artifacts"))
    forbidden_outputs = _list_of_strings(manifest.get("forbidden_outputs"))
    required_forbidden = {"strategy_skeleton", "candidate_config", "paper_order", "live_order", "broker_call"}
    generated_forbidden = [
        item
        for item in generated_artifacts
        if any(marker in item for marker in ("skeleton", "candidate_config", "paper_order", "live_order", "broker"))
    ]
    checks = {
        "mode": policy.get("mode") == "hypothesis_level_only",
        "strategy_skeleton_generation_disallowed": policy.get("strategy_skeleton_generation_allowed") is False,
        "candidate_generation_disallowed": policy.get("candidate_generation_allowed") is False
        and manifest.get("candidate_generation_allowed") is False,
        "paper_live_side_effects_disallowed": policy.get("paper_or_live_side_effects_allowed") is False,
        "strategy_skeleton_not_generated": manifest.get("strategy_skeleton_generated") is False
        and decision.get("strategy_skeleton_generated") is False,
        "strategy_skeleton_path_empty": manifest.get("strategy_skeleton_path") == ""
        and decision.get("strategy_skeleton_path", "") == "",
        "candidate_not_generated": manifest.get("candidate_generated") is False,
        "allowed_output_level_hypothesis": manifest.get("allowed_output_level") == "hypothesis",
        "paper_live_locked": manifest.get("paper_queue") == "LOCKED" and manifest.get("live") == "FROZEN",
        "forbidden_outputs_declared": required_forbidden.issubset(set(forbidden_outputs)),
        "generated_artifacts_hypothesis_only": not generated_forbidden,
    }
    blockers = [f"btc_hypothesis_lab_v2_{name}_failed" for name, passed in checks.items() if not passed]
    complete = not blockers
    return {
        "status": "complete" if complete else "incomplete",
        "evidence": {
            "hypothesis_v2_manifest": str(HYPOTHESIS_V2_MANIFEST),
            "hypothesis_v2_decision": str(HYPOTHESIS_V2_DECISION),
        },
        "mode": policy.get("mode"),
        "allowed_output_level": manifest.get("allowed_output_level"),
        "strategy_skeleton_generation_allowed": bool(policy.get("strategy_skeleton_generation_allowed", True)),
        "strategy_skeleton_generated": bool(manifest.get("strategy_skeleton_generated", True)),
        "strategy_skeleton_path": str(manifest.get("strategy_skeleton_path", "")),
        "candidate_generation_allowed": bool(manifest.get("candidate_generation_allowed", True)),
        "candidate_generated": bool(manifest.get("candidate_generated", True)),
        "paper_or_live_side_effects_allowed": bool(policy.get("paper_or_live_side_effects_allowed", True)),
        "paper_queue": manifest.get("paper_queue"),
        "live": manifest.get("live"),
        "generated_artifacts": generated_artifacts,
        "forbidden_outputs": forbidden_outputs,
        "decision": decision.get("decision"),
        "blockers": blockers,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _funding_adjusted_ledger_file_status(funding: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path_value = funding.get("funding_adjusted_ledger_path")
    path = _resolve_artifact_path(path_value, root)
    status = {
        "exists": bool(path and path.exists()),
        "reconciled_to_report": False,
        "trade_count": 0,
        "funding_pnl_total": None,
        "net_pnl_before_total": None,
        "net_pnl_after_total": None,
    }
    if not path or not path.exists():
        return status
    rows: list[dict[str, str]] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return status
    funding_total = _sum_csv_float(rows, "funding_pnl")
    before_total = _sum_csv_float(rows, "net_pnl_before_funding")
    after_total = _sum_csv_float(rows, "net_pnl_after_funding")
    status.update(
        {
            "trade_count": len(rows),
            "funding_pnl_total": funding_total,
            "net_pnl_before_total": before_total,
            "net_pnl_after_total": after_total,
        }
    )
    expected_trade_count = _int_or_none(funding.get("funding_adjusted_trade_count"))
    status["reconciled_to_report"] = bool(
        expected_trade_count == len(rows)
        and _numbers_close(funding_total, _float_or_none(funding.get("funding_pnl_total")))
        and _numbers_close(before_total, _float_or_none(funding.get("trade_ledger_net_pnl_total")))
        and _numbers_close(after_total, _float_or_none(funding.get("funding_adjusted_net_pnl_total")))
    )
    return status


def _resolve_artifact_path(value: object, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _sum_csv_float(rows: list[Mapping[str, str]], field: str) -> float | None:
    total = 0.0
    for row in rows:
        value = _float_or_none(row.get(field))
        if value is None:
            return None
        total += value
    return round(total, 12)


def _raw_input_files(import_report: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    raw = _mapping(import_report.get("raw_input_files"))
    return {
        "exchange_info_raw": _raw_file(_mapping(raw.get("exchange_info_raw")), root),
        "funding_info_raw": _raw_file(_mapping(raw.get("funding_info_raw")), root),
    }


def _manual_metadata_completion_criteria() -> list[str]:
    return [
        "provider_metadata_verified=true",
        "manual_metadata_import_report.schema_version=btc_manual_metadata_import_report_v1",
        "manual_metadata_import_report.status=verified",
        "manual_metadata_import_report.writes_performed=true",
        "manual_metadata_import_report.bundle_dir matches selected BTC bundle",
        "manual_metadata_import_report.bundle_dir contains exchange_info.json and funding_info.json",
        "manual_metadata_import_report.exchange_info_output_sha256 matches selected bundle exchange_info.json",
        "manual_metadata_import_report.funding_info_output_sha256 matches selected bundle funding_info.json",
        "manual_metadata_import_report.captured_at=UTC ISO-8601",
        "manual_metadata_import_report.post_import_validation_command=make validate-btc-public-data-bundle",
        "exchange_info_raw.exists=true with path, size_bytes, and sha256",
        "funding_info_raw.exists=true with path, size_bytes, and sha256",
        "exchange_info_raw.http_status=200 and funding_info_raw.http_status=200",
        "raw_input_files.current_file_verified=true when import report is used for completion",
    ]


def _manual_import_verified(import_report: Mapping[str, Any], root: Path) -> bool:
    raw = _raw_input_files(import_report, root)
    return (
        import_report.get("schema_version") == "btc_manual_metadata_import_report_v1"
        and import_report.get("status") == "verified"
        and import_report.get("writes_performed") is True
        and import_report.get("exchange_info_verified") is True
        and import_report.get("funding_info_verified") is True
        and _manual_import_bundle_verified(_manual_import_bundle_status(import_report, root))
        and _list_of_strings(import_report.get("blockers")) == []
        and _utc_capture_timestamp(import_report.get("captured_at"))
        and _post_import_validation_command_verified(import_report.get("post_import_validation_command"))
        and _raw_file_verified(raw["exchange_info_raw"])
        and _raw_file_verified(raw["funding_info_raw"])
    )


def _manual_import_blockers(import_report: Mapping[str, Any], root: Path) -> list[str]:
    if not import_report:
        return ["btc_manual_metadata_import_report_missing"]
    blockers = _list_of_strings(import_report.get("blockers"))
    if import_report.get("schema_version") != "btc_manual_metadata_import_report_v1":
        blockers.append("btc_manual_metadata_import_schema_version_missing_or_invalid")
    if import_report.get("status") != "verified":
        blockers.append("btc_manual_metadata_import_not_verified")
    if import_report.get("writes_performed") is not True:
        blockers.append("btc_manual_metadata_import_write_not_performed")
    if import_report.get("exchange_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_exchange_info_not_verified")
    if import_report.get("funding_info_verified") is not True:
        blockers.append("btc_manual_metadata_import_funding_info_not_verified")
    if not _non_empty_text(import_report.get("bundle_dir")):
        blockers.append("btc_manual_metadata_import_bundle_dir_missing")
    bundle_status = _manual_import_bundle_status(import_report, root)
    if not bundle_status["selected_bundle_configured"]:
        blockers.append("btc_manual_metadata_import_selected_bundle_config_missing")
    if _non_empty_text(import_report.get("bundle_dir")) and not bundle_status["exists"]:
        blockers.append("btc_manual_metadata_import_bundle_dir_missing_on_disk")
    if bundle_status["selected_bundle_configured"] and not bundle_status["matches_selected_bundle"]:
        blockers.append("btc_manual_metadata_import_bundle_dir_not_selected_bundle")
    if bundle_status["exists"] and not bundle_status["exchange_info_exists"]:
        blockers.append("btc_manual_metadata_import_bundle_exchange_info_missing")
    if bundle_status["exists"] and not bundle_status["funding_info_exists"]:
        blockers.append("btc_manual_metadata_import_bundle_funding_info_missing")
    if bundle_status["exists"] and not bundle_status["exchange_info_output_hash_verified"]:
        blockers.append("btc_manual_metadata_import_exchange_info_output_hash_mismatch")
    if bundle_status["exists"] and not bundle_status["funding_info_output_hash_verified"]:
        blockers.append("btc_manual_metadata_import_funding_info_output_hash_mismatch")
    if not _utc_capture_timestamp(import_report.get("captured_at")):
        blockers.append("btc_manual_metadata_import_captured_at_missing")
    if not _post_import_validation_command_verified(import_report.get("post_import_validation_command")):
        blockers.append("btc_manual_metadata_import_validation_command_missing")
    raw = _raw_input_files(import_report, root)
    if not _raw_file_verified(raw["exchange_info_raw"]):
        blockers.append("btc_exchange_info_raw_import_provenance_missing")
    if not _raw_file_verified(raw["funding_info_raw"]):
        blockers.append("btc_funding_info_raw_import_provenance_missing")
    if not _raw_file_current_match_verified(raw["exchange_info_raw"]):
        blockers.append("btc_exchange_info_raw_import_current_file_mismatch")
    if not _raw_file_current_match_verified(raw["funding_info_raw"]):
        blockers.append("btc_funding_info_raw_import_current_file_mismatch")
    if not _raw_file_http_status_verified(raw["exchange_info_raw"]):
        blockers.append("btc_exchange_info_raw_http_status_not_200")
    if not _raw_file_http_status_verified(raw["funding_info_raw"]):
        blockers.append("btc_funding_info_raw_http_status_not_200")
    return _dedupe(blockers)


def _manual_import_bundle_status(import_report: Mapping[str, Any], root: Path) -> dict[str, Any]:
    selected_bundle = _selected_btc_bundle_dir(root)
    bundle_dir = _resolve_raw_file_path(import_report.get("bundle_dir"), root)
    exists = bool(bundle_dir and bundle_dir.exists() and bundle_dir.is_dir())
    matches_selected = bool(
        bundle_dir
        and selected_bundle
        and _same_resolved_path(bundle_dir, selected_bundle)
    )
    return {
        "path": import_report.get("bundle_dir"),
        "selected_bundle_path": _relpath(selected_bundle, root) if selected_bundle else None,
        "selected_bundle_configured": selected_bundle is not None,
        "exists": exists,
        "matches_selected_bundle": matches_selected,
        "exchange_info_exists": bool(exists and bundle_dir and (bundle_dir / "exchange_info.json").exists()),
        "funding_info_exists": bool(exists and bundle_dir and (bundle_dir / "funding_info.json").exists()),
        "exchange_info_output_hash_verified": _manual_output_hash_verified(
            import_report,
            root=root,
            bundle_dir=bundle_dir,
            prefix="exchange_info",
            filename="exchange_info.json",
        ),
        "funding_info_output_hash_verified": _manual_output_hash_verified(
            import_report,
            root=root,
            bundle_dir=bundle_dir,
            prefix="funding_info",
            filename="funding_info.json",
        ),
    }


def _manual_import_bundle_verified(status: Mapping[str, Any]) -> bool:
    return bool(
        status.get("selected_bundle_configured") is True
        and status.get("exists") is True
        and status.get("matches_selected_bundle") is True
        and status.get("exchange_info_exists") is True
        and status.get("funding_info_exists") is True
        and status.get("exchange_info_output_hash_verified") is True
        and status.get("funding_info_output_hash_verified") is True
    )


def _manual_output_hash_verified(
    import_report: Mapping[str, Any],
    *,
    root: Path,
    bundle_dir: Path | None,
    prefix: str,
    filename: str,
) -> bool:
    expected = bundle_dir / filename if bundle_dir else None
    reported_path = _resolve_raw_file_path(import_report.get(f"{prefix}_output_path"), root)
    reported_hash = import_report.get(f"{prefix}_output_sha256")
    return bool(
        expected
        and expected.exists()
        and reported_path
        and _same_resolved_path(reported_path, expected)
        and isinstance(reported_hash, str)
        and SHA256_RE.fullmatch(reported_hash)
        and _sha256(expected) == reported_hash
    )


def _selected_btc_bundle_dir(root: Path) -> Path | None:
    return selected_btc_perpetual_bundle_dir(root, root / BTC_SOURCE_CONFIG)


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _raw_file(payload: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    out = {
        "path": payload.get("path"),
        "exists": bool(payload.get("exists", False)),
        "size_bytes": payload.get("size_bytes"),
        "sha256": payload.get("sha256"),
        "http_status_file": payload.get("http_status_file"),
        "http_status": payload.get("http_status"),
        "http_status_verified": payload.get("http_status_verified") is True,
        "current_file_verified": False,
    }
    path = _resolve_raw_file_path(payload.get("path"), root)
    if path and path.exists() and isinstance(payload.get("size_bytes"), int) and isinstance(payload.get("sha256"), str):
        out["current_file_verified"] = bool(
            path.stat().st_size == payload.get("size_bytes") and _sha256(path) == payload.get("sha256")
        )
    return out


def _raw_file_verified(payload: Mapping[str, Any]) -> bool:
    return bool(
        payload.get("exists") is True
        and isinstance(payload.get("path"), str)
        and bool(str(payload.get("path")).strip())
        and isinstance(payload.get("size_bytes"), int)
        and payload.get("size_bytes") > 0
        and isinstance(payload.get("sha256"), str)
        and SHA256_RE.fullmatch(str(payload.get("sha256")))
        and _raw_file_http_status_verified(payload)
        and payload.get("current_file_verified") is True
    )


def _raw_file_current_match_verified(payload: Mapping[str, Any]) -> bool:
    return payload.get("current_file_verified") is True


def _raw_file_http_status_verified(payload: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(payload.get("http_status_file"), str)
        and bool(str(payload.get("http_status_file")).strip())
        and payload.get("http_status") == 200
        and payload.get("http_status_verified") is True
    )


def _resolve_raw_file_path(value: object, root: Path | None) -> Path | None:
    if not isinstance(value, str) or not value.strip() or root is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


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


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _numbers_close(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and abs(left - right) <= 1e-9


def _post_import_validation_command_verified(value: object) -> bool:
    return value == "make validate-btc-public-data-bundle"


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc_capture_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not UTC_CAPTURE_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


if __name__ == "__main__":
    main()
