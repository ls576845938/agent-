#!/usr/bin/env python3
"""Validate imported execution-latency and queue-position evidence for BTC scalping research.

This builder is read-only. It validates local manifest metadata and file
integrity for externally exported evidence, but it never calls broker,
private, order, paper, or live surfaces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_IMPORT_MANIFEST_ROOT = Path("data/external/btc_perpetual/okx_swap/execution_queue_evidence")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
REPORT_FILENAME = "btc_true_scalping_execution_queue_external_evidence_contract_report.json"
REPORT_SCHEMA_VERSION = "btc_true_scalping_execution_queue_external_evidence_contract_v1"
MIN_EXECUTION_LATENCY_OBSERVATIONS = 100
MIN_QUEUE_POSITION_OBSERVATIONS = 100
EXECUTION_LATENCY_ROLES = {"execution_latency_observations", "order_ack_latency", "fill_latency_observations"}
EXECUTION_MODEL_ROLES = {"execution_latency_model", "private_order_latency_model"}
QUEUE_POSITION_ROLES = {"queue_position_observations", "queue_fill_priority_observations"}
QUEUE_MODEL_ROLES = {"queue_position_model", "exchange_queue_position_model"}
ALLOWED_SOURCE_TYPES = {
    "paper_exchange_order_log_export",
    "sandbox_execution_report_export",
    "exchange_account_order_log_export_readonly",
    "broker_statement_export_readonly",
    "manual_reconciled_execution_log",
}


def build_btc_true_scalping_execution_queue_external_evidence_contract_report(
    *,
    repo_root: Path | None = None,
    import_manifest_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    manifest_root = _resolve(root, import_manifest_root or DEFAULT_IMPORT_MANIFEST_ROOT)
    manifests = _manifest_summaries(root=root, manifest_root=manifest_root)
    totals = _totals(manifests)
    validation = _validation(manifests=manifests, totals=totals)
    blockers = _blockers(validation=validation, manifests=manifests, totals=totals)
    contract_satisfied = bool(validation["contract_satisfied"])
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_execution_queue_external_evidence_contract_no_candidate_no_paper_no_live",
        "status": "execution_queue_external_evidence_contract_satisfied_research_only"
        if contract_satisfied
        else "execution_queue_external_evidence_contract_missing_or_invalid_research_only",
        "decision": "accept_execution_queue_evidence_for_research_gate_only"
        if contract_satisfied
        else "collect_or_import_execution_latency_and_queue_position_evidence",
        "next_required_action": "continue_long_horizon_l2_tick_and_paper_gate_evidence"
        if contract_satisfied
        else "import_read_only_execution_latency_and_queue_position_exports_with_hash_manifest",
        "import_manifest_root": _relpath(manifest_root, root),
        "thresholds": {
            "minimum_execution_latency_observations": MIN_EXECUTION_LATENCY_OBSERVATIONS,
            "minimum_queue_position_observations": MIN_QUEUE_POSITION_OBSERVATIONS,
            "required_execution_roles": [
                "execution_latency_observations",
                "execution_latency_model",
            ],
            "required_queue_roles": [
                "queue_position_observations",
                "queue_position_model",
            ],
        },
        "manifests": manifests,
        "coverage_totals": totals,
        "validation": validation,
        "blockers": blockers,
        "contract_satisfied": contract_satisfied,
        "execution_latency_evidence_contract_satisfied": bool(
            validation["execution_latency_evidence_contract_satisfied"]
        ),
        "queue_position_evidence_contract_satisfied": bool(validation["queue_position_evidence_contract_satisfied"]),
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "guardrails": {
            "research_only": True,
            "status_report_only": True,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "broker_calls_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "true_scalping_claim_allowed": False,
        },
    }


def write_btc_true_scalping_execution_queue_external_evidence_contract_report(
    payload: Mapping[str, Any],
    output_root: Path,
) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / REPORT_FILENAME
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--import-manifest-root", default=str(DEFAULT_IMPORT_MANIFEST_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_execution_queue_external_evidence_contract_report(
        repo_root=Path(args.repo_root),
        import_manifest_root=Path(args.import_manifest_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_true_scalping_execution_queue_external_evidence_contract_report(payload, Path(args.output_root)))


def _manifest_summaries(*, root: Path, manifest_root: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for manifest_path in sorted(manifest_root.glob("*manifest*.json")):
        manifest = _read_json(manifest_path)
        files = [_file_summary(root=root, manifest_dir=manifest_path.parent, item=item) for item in _list(manifest.get("files"))]
        source_type = str(manifest.get("source_type", "") or "")
        read_only_export = bool(manifest.get("read_only_export", False))
        importer_private_endpoint_used = bool(manifest.get("importer_private_endpoint_used", True))
        importer_order_endpoint_used = bool(manifest.get("importer_order_endpoint_used", True))
        broker_calls_used = bool(manifest.get("broker_calls_used", True))
        real_orders_created_for_this_import = bool(manifest.get("real_orders_created_for_this_import", True))
        clock_sync_evidence = bool(manifest.get("clock_sync_evidence", False))
        exchange_order_ids_present = bool(manifest.get("exchange_order_ids_present", False))
        queue_position_labels_present = bool(manifest.get("queue_position_labels_present", False))
        file_blockers = [blocker for item in files for blocker in _list_of_strings(item.get("blockers"))]
        manifest_blockers = []
        if source_type not in ALLOWED_SOURCE_TYPES:
            manifest_blockers.append("btc_execution_queue_import_source_type_not_allowed")
        if not read_only_export:
            manifest_blockers.append("btc_execution_queue_import_not_read_only_export")
        if importer_private_endpoint_used:
            manifest_blockers.append("btc_execution_queue_importer_private_endpoint_used")
        if importer_order_endpoint_used:
            manifest_blockers.append("btc_execution_queue_importer_order_endpoint_used")
        if broker_calls_used:
            manifest_blockers.append("btc_execution_queue_importer_broker_calls_used")
        if real_orders_created_for_this_import:
            manifest_blockers.append("btc_execution_queue_import_created_real_orders")
        if not files:
            manifest_blockers.append("btc_execution_queue_import_manifest_files_missing")
        if not clock_sync_evidence:
            manifest_blockers.append("btc_execution_queue_import_clock_sync_evidence_missing")
        if not exchange_order_ids_present:
            manifest_blockers.append("btc_execution_queue_import_exchange_order_ids_missing")
        if not queue_position_labels_present:
            manifest_blockers.append("btc_execution_queue_import_queue_position_labels_missing")
        summaries.append(
            {
                "manifest_path": _relpath(manifest_path, root),
                "manifest_id": str(manifest.get("manifest_id", manifest_path.stem) or manifest_path.stem),
                "source_type": source_type,
                "venue": str(manifest.get("venue", "") or ""),
                "venue_symbol": str(manifest.get("venue_symbol", "") or ""),
                "symbol": str(manifest.get("symbol", "") or ""),
                "read_only_export": read_only_export,
                "importer_private_endpoint_used": importer_private_endpoint_used,
                "importer_order_endpoint_used": importer_order_endpoint_used,
                "broker_calls_used": broker_calls_used,
                "real_orders_created_for_this_import": real_orders_created_for_this_import,
                "clock_sync_evidence": clock_sync_evidence,
                "exchange_order_ids_present": exchange_order_ids_present,
                "queue_position_labels_present": queue_position_labels_present,
                "files": files,
                "roles_present": sorted({str(item.get("role", "")) for item in files if str(item.get("role", ""))}),
                "blockers": _dedupe([*manifest_blockers, *file_blockers]),
                "valid_for_contract": not manifest_blockers and not file_blockers,
            }
        )
    return summaries


def _file_summary(*, root: Path, manifest_dir: Path, item: object) -> dict[str, Any]:
    mapping = _mapping(item)
    role = str(mapping.get("role", "") or "")
    raw_path = str(mapping.get("path", "") or "")
    resolved = _resolve_manifest_file(root=root, manifest_dir=manifest_dir, raw_path=raw_path)
    expected_sha256 = str(mapping.get("sha256", "") or "")
    actual_sha256 = _sha256(resolved) if resolved.exists() and resolved.is_file() else ""
    sample_start = str(mapping.get("sample_start", "") or "")
    sample_end = str(mapping.get("sample_end", "") or "")
    blockers = []
    if not _supported_role(role):
        blockers.append("btc_execution_queue_import_file_role_not_supported")
    if not raw_path:
        blockers.append("btc_execution_queue_import_file_path_missing")
    if not resolved.exists() or not resolved.is_file():
        blockers.append("btc_execution_queue_import_file_missing")
    if not expected_sha256:
        blockers.append("btc_execution_queue_import_file_sha256_missing")
    elif actual_sha256 and expected_sha256 != actual_sha256:
        blockers.append("btc_execution_queue_import_file_sha256_mismatch")
    if _datetime_or_none(sample_start) is None or _datetime_or_none(sample_end) is None:
        blockers.append("btc_execution_queue_import_file_sample_window_missing")
    return {
        "role": role,
        "path": _relpath(resolved, root) if raw_path else "",
        "format": str(mapping.get("format", "") or ""),
        "source_export": str(mapping.get("source_export", "") or ""),
        "sample_count": int(mapping.get("sample_count", 0) or 0),
        "sample_start": sample_start,
        "sample_end": sample_end,
        "sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "blockers": blockers,
        "valid": not blockers,
    }


def _totals(manifests: list[Mapping[str, Any]]) -> dict[str, Any]:
    valid_files = [
        file_item
        for manifest in manifests
        if bool(manifest.get("valid_for_contract", False))
        for file_item in _list(manifest.get("files"))
        if bool(_mapping(file_item).get("valid", False))
    ]
    execution_obs = [_mapping(item) for item in valid_files if str(_mapping(item).get("role", "")) in EXECUTION_LATENCY_ROLES]
    execution_models = [_mapping(item) for item in valid_files if str(_mapping(item).get("role", "")) in EXECUTION_MODEL_ROLES]
    queue_obs = [_mapping(item) for item in valid_files if str(_mapping(item).get("role", "")) in QUEUE_POSITION_ROLES]
    queue_models = [_mapping(item) for item in valid_files if str(_mapping(item).get("role", "")) in QUEUE_MODEL_ROLES]
    return {
        "manifest_count": len(manifests),
        "valid_manifest_count": sum(1 for item in manifests if bool(item.get("valid_for_contract", False))),
        "valid_file_count": len(valid_files),
        "execution_latency_observation_file_count": len(execution_obs),
        "execution_latency_model_file_count": len(execution_models),
        "queue_position_observation_file_count": len(queue_obs),
        "queue_position_model_file_count": len(queue_models),
        "execution_latency_observation_count": sum(int(item.get("sample_count", 0) or 0) for item in execution_obs),
        "queue_position_observation_count": sum(int(item.get("sample_count", 0) or 0) for item in queue_obs),
        "remaining_execution_latency_observations": max(
            0,
            MIN_EXECUTION_LATENCY_OBSERVATIONS - sum(int(item.get("sample_count", 0) or 0) for item in execution_obs),
        ),
        "remaining_queue_position_observations": max(
            0,
            MIN_QUEUE_POSITION_OBSERVATIONS - sum(int(item.get("sample_count", 0) or 0) for item in queue_obs),
        ),
    }


def _validation(*, manifests: list[Mapping[str, Any]], totals: Mapping[str, Any]) -> dict[str, bool]:
    execution_obs_ok = int(totals.get("execution_latency_observation_count", 0) or 0) >= MIN_EXECUTION_LATENCY_OBSERVATIONS
    queue_obs_ok = int(totals.get("queue_position_observation_count", 0) or 0) >= MIN_QUEUE_POSITION_OBSERVATIONS
    execution_model_ok = int(totals.get("execution_latency_model_file_count", 0) or 0) > 0
    queue_model_ok = int(totals.get("queue_position_model_file_count", 0) or 0) > 0
    base = {
        "import_manifests_present": bool(manifests),
        "read_only_export_boundary_satisfied": bool(manifests)
        and all(bool(item.get("read_only_export", False)) for item in manifests),
        "importer_private_order_broker_boundary_satisfied": bool(manifests)
        and all(
            not bool(item.get("importer_private_endpoint_used", True))
            and not bool(item.get("importer_order_endpoint_used", True))
            and not bool(item.get("broker_calls_used", True))
            and not bool(item.get("real_orders_created_for_this_import", True))
            for item in manifests
        ),
        "file_integrity_satisfied": bool(manifests)
        and all(not _list_of_strings(item.get("blockers")) for item in manifests),
        "clock_sync_evidence_present": bool(manifests)
        and all(bool(item.get("clock_sync_evidence", False)) for item in manifests),
        "exchange_order_ids_present": bool(manifests)
        and all(bool(item.get("exchange_order_ids_present", False)) for item in manifests),
        "queue_position_labels_present": bool(manifests)
        and all(bool(item.get("queue_position_labels_present", False)) for item in manifests),
        "execution_latency_observations_present": int(totals.get("execution_latency_observation_file_count", 0) or 0)
        > 0,
        "execution_latency_model_present": execution_model_ok,
        "minimum_execution_latency_observations_satisfied": execution_obs_ok,
        "queue_position_observations_present": int(totals.get("queue_position_observation_file_count", 0) or 0) > 0,
        "queue_position_model_present": queue_model_ok,
        "minimum_queue_position_observations_satisfied": queue_obs_ok,
    }
    base["execution_latency_evidence_contract_satisfied"] = all(
        bool(base[name])
        for name in (
            "import_manifests_present",
            "read_only_export_boundary_satisfied",
            "importer_private_order_broker_boundary_satisfied",
            "file_integrity_satisfied",
            "clock_sync_evidence_present",
            "exchange_order_ids_present",
            "execution_latency_observations_present",
            "execution_latency_model_present",
            "minimum_execution_latency_observations_satisfied",
        )
    )
    base["queue_position_evidence_contract_satisfied"] = all(
        bool(base[name])
        for name in (
            "import_manifests_present",
            "read_only_export_boundary_satisfied",
            "importer_private_order_broker_boundary_satisfied",
            "file_integrity_satisfied",
            "exchange_order_ids_present",
            "queue_position_labels_present",
            "queue_position_observations_present",
            "queue_position_model_present",
            "minimum_queue_position_observations_satisfied",
        )
    )
    base["contract_satisfied"] = bool(
        base["execution_latency_evidence_contract_satisfied"]
        and base["queue_position_evidence_contract_satisfied"]
    )
    return base


def _blockers(
    *,
    validation: Mapping[str, bool],
    manifests: list[Mapping[str, Any]],
    totals: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not validation["import_manifests_present"]:
        blockers.append("btc_execution_queue_evidence_import_manifest_missing")
    if not validation["read_only_export_boundary_satisfied"]:
        blockers.append("btc_execution_queue_evidence_read_only_export_boundary_not_satisfied")
    if not validation["importer_private_order_broker_boundary_satisfied"]:
        blockers.append("btc_execution_queue_evidence_importer_private_order_broker_boundary_not_satisfied")
    if not validation["file_integrity_satisfied"]:
        blockers.append("btc_execution_queue_evidence_file_integrity_not_satisfied")
    if not validation["clock_sync_evidence_present"]:
        blockers.append("btc_execution_queue_evidence_clock_sync_missing")
    if not validation["exchange_order_ids_present"]:
        blockers.append("btc_execution_queue_evidence_exchange_order_ids_missing")
    if not validation["execution_latency_observations_present"]:
        blockers.append("btc_execution_latency_observations_missing")
    if not validation["execution_latency_model_present"]:
        blockers.append("btc_execution_latency_model_external_evidence_missing")
    if not validation["minimum_execution_latency_observations_satisfied"]:
        blockers.append(
            "btc_execution_latency_observations_short_"
            f"{int(totals.get('remaining_execution_latency_observations', 0) or 0)}"
        )
    if not validation["queue_position_labels_present"]:
        blockers.append("btc_queue_position_labels_missing")
    if not validation["queue_position_observations_present"]:
        blockers.append("btc_queue_position_observations_missing")
    if not validation["queue_position_model_present"]:
        blockers.append("btc_queue_position_model_external_evidence_missing")
    if not validation["minimum_queue_position_observations_satisfied"]:
        blockers.append(
            "btc_queue_position_observations_short_"
            f"{int(totals.get('remaining_queue_position_observations', 0) or 0)}"
        )
    for manifest in manifests:
        blockers.extend(_list_of_strings(manifest.get("blockers")))
    return _dedupe(blockers)


def _supported_role(role: str) -> bool:
    return role in EXECUTION_LATENCY_ROLES | EXECUTION_MODEL_ROLES | QUEUE_POSITION_ROLES | QUEUE_MODEL_ROLES


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _resolve_manifest_file(*, root: Path, manifest_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    root_path = root / path
    if root_path.exists():
        return root_path
    return manifest_dir / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _datetime_or_none(value: object) -> datetime | None:
    text = str(value or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
