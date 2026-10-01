#!/usr/bin/env python3
"""Validate imported long-horizon L2/tick history evidence for BTC scalping research.

The report is deliberately fail-closed. It only evaluates local manifests for
public or licensed historical market-data archives. It never calls private,
order, broker, paper, or live surfaces, and it never unlocks trading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_IMPORT_MANIFEST_ROOT = Path("data/external/btc_perpetual/okx_swap/historical_l2_tick_imports")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
REPORT_FILENAME = "btc_true_scalping_long_horizon_l2_tick_import_contract_report.json"
REPORT_SCHEMA_VERSION = "btc_true_scalping_long_horizon_l2_tick_import_contract_v1"
MIN_HISTORY_DAYS = 30.0
TICK_ROLES = {"tick_trades", "agg_trades", "trades"}
L2_ROLES = {"l2_order_book", "order_book_depth", "incremental_book_l2", "book_snapshots"}
ALLOWED_SOURCE_TYPES = {
    "okx_historical_data_download",
    "public_archive",
    "licensed_l2_archive",
    "manual_public_archive_import",
}


def build_btc_true_scalping_long_horizon_l2_tick_import_contract_report(
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
        "scope": "research_only_long_horizon_l2_tick_import_contract_no_candidate_no_paper_no_live",
        "status": "long_horizon_l2_tick_import_contract_satisfied_research_only"
        if contract_satisfied
        else "long_horizon_l2_tick_import_contract_missing_or_invalid_research_only",
        "decision": "accept_import_as_long_horizon_market_data_evidence_research_only"
        if contract_satisfied
        else "collect_or_import_30d_tick_and_l2_history_before_true_scalping",
        "next_required_action": "continue_private_execution_latency_queue_and_paper_gate_evidence"
        if contract_satisfied
        else "import_public_or_licensed_30d_tick_and_l2_order_book_history_with_hash_manifest",
        "import_manifest_root": _relpath(manifest_root, root),
        "accepted_source_examples": [
            {
                "source_name": "OKX historical data download",
                "url": "https://www.okx.com/en-us/historical-data",
                "required_data": ["trade_history", "order_book"],
            }
        ],
        "thresholds": {
            "minimum_tick_history_days": MIN_HISTORY_DAYS,
            "minimum_l2_history_days": MIN_HISTORY_DAYS,
            "minimum_common_calendar_span_days": MIN_HISTORY_DAYS,
            "required_roles": ["tick_trades_or_agg_trades", "l2_order_book_or_depth"],
        },
        "manifests": manifests,
        "coverage_totals": totals,
        "validation": validation,
        "blockers": blockers,
        "contract_satisfied": contract_satisfied,
        "long_horizon_l2_tick_history_ready": contract_satisfied,
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


def write_btc_true_scalping_long_horizon_l2_tick_import_contract_report(
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
    payload = build_btc_true_scalping_long_horizon_l2_tick_import_contract_report(
        repo_root=Path(args.repo_root),
        import_manifest_root=Path(args.import_manifest_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_true_scalping_long_horizon_l2_tick_import_contract_report(payload, Path(args.output_root)))


def _manifest_summaries(*, root: Path, manifest_root: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for manifest_path in sorted(manifest_root.glob("*.json")):
        manifest = _read_json(manifest_path)
        files = [_file_summary(root=root, manifest_dir=manifest_path.parent, item=item) for item in _list(manifest.get("files"))]
        source_type = str(manifest.get("source_type", "") or "")
        public_or_licensed = bool(manifest.get("public_or_licensed_archive_only", False))
        private_endpoint_used = bool(manifest.get("private_endpoint_used", True))
        order_endpoint_used = bool(manifest.get("order_endpoint_used", True))
        broker_calls_used = bool(manifest.get("broker_calls_used", True))
        file_blockers = [blocker for item in files for blocker in _list_of_strings(item.get("blockers"))]
        manifest_blockers = []
        if source_type not in ALLOWED_SOURCE_TYPES:
            manifest_blockers.append("btc_long_horizon_import_source_type_not_allowed")
        if not public_or_licensed:
            manifest_blockers.append("btc_long_horizon_import_not_public_or_licensed_archive")
        if private_endpoint_used:
            manifest_blockers.append("btc_long_horizon_import_private_endpoint_used")
        if order_endpoint_used:
            manifest_blockers.append("btc_long_horizon_import_order_endpoint_used")
        if broker_calls_used:
            manifest_blockers.append("btc_long_horizon_import_broker_calls_used")
        if not files:
            manifest_blockers.append("btc_long_horizon_import_manifest_files_missing")
        summaries.append(
            {
                "manifest_path": _relpath(manifest_path, root),
                "manifest_id": str(manifest.get("manifest_id", manifest_path.stem) or manifest_path.stem),
                "source_type": source_type,
                "venue": str(manifest.get("venue", "") or ""),
                "venue_symbol": str(manifest.get("venue_symbol", "") or ""),
                "symbol": str(manifest.get("symbol", "") or ""),
                "public_or_licensed_archive_only": public_or_licensed,
                "private_endpoint_used": private_endpoint_used,
                "order_endpoint_used": order_endpoint_used,
                "broker_calls_used": broker_calls_used,
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
    if role not in TICK_ROLES and role not in L2_ROLES:
        blockers.append("btc_long_horizon_import_file_role_not_supported")
    if not raw_path:
        blockers.append("btc_long_horizon_import_file_path_missing")
    if not resolved.exists() or not resolved.is_file():
        blockers.append("btc_long_horizon_import_file_missing")
    if not expected_sha256:
        blockers.append("btc_long_horizon_import_file_sha256_missing")
    elif actual_sha256 and expected_sha256 != actual_sha256:
        blockers.append("btc_long_horizon_import_file_sha256_mismatch")
    if _datetime_or_none(sample_start) is None or _datetime_or_none(sample_end) is None:
        blockers.append("btc_long_horizon_import_file_sample_window_missing")
    return {
        "role": role,
        "path": _relpath(resolved, root) if raw_path else "",
        "format": str(mapping.get("format", "") or ""),
        "source_endpoint_or_archive": str(mapping.get("source_endpoint_or_archive", "") or ""),
        "record_count": int(mapping.get("record_count", 0) or 0),
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
    tick_files = [_mapping(item) for item in valid_files if str(_mapping(item).get("role", "")) in TICK_ROLES]
    l2_files = [_mapping(item) for item in valid_files if str(_mapping(item).get("role", "")) in L2_ROLES]
    tick_span = _span_days(tick_files)
    l2_span = _span_days(l2_files)
    common_start, common_end = _common_window(tick_files=tick_files, l2_files=l2_files)
    common_span = _window_days(common_start, common_end)
    return {
        "manifest_count": len(manifests),
        "valid_manifest_count": sum(1 for item in manifests if bool(item.get("valid_for_contract", False))),
        "valid_file_count": len(valid_files),
        "tick_file_count": len(tick_files),
        "l2_file_count": len(l2_files),
        "tick_history_days": tick_span,
        "l2_history_days": l2_span,
        "common_calendar_span_days": common_span,
        "remaining_tick_history_days": max(0.0, MIN_HISTORY_DAYS - tick_span),
        "remaining_l2_history_days": max(0.0, MIN_HISTORY_DAYS - l2_span),
        "remaining_common_calendar_span_days": max(0.0, MIN_HISTORY_DAYS - common_span),
        "total_record_count": sum(int(_mapping(item).get("record_count", 0) or 0) for item in valid_files),
        "common_sample_start": common_start.isoformat().replace("+00:00", "Z") if common_start else None,
        "common_sample_end": common_end.isoformat().replace("+00:00", "Z") if common_end else None,
    }


def _validation(*, manifests: list[Mapping[str, Any]], totals: Mapping[str, Any]) -> dict[str, bool]:
    validation = {
        "import_manifests_present": bool(manifests),
        "public_or_licensed_archive_boundary_satisfied": bool(manifests)
        and all(bool(item.get("public_or_licensed_archive_only", False)) for item in manifests),
        "private_order_broker_boundary_satisfied": bool(manifests)
        and all(
            not bool(item.get("private_endpoint_used", True))
            and not bool(item.get("order_endpoint_used", True))
            and not bool(item.get("broker_calls_used", True))
            for item in manifests
        ),
        "file_integrity_satisfied": bool(manifests)
        and all(not _list_of_strings(item.get("blockers")) for item in manifests),
        "tick_history_present": int(totals.get("tick_file_count", 0) or 0) > 0,
        "l2_order_book_history_present": int(totals.get("l2_file_count", 0) or 0) > 0,
        "minimum_tick_history_days_satisfied": float(totals.get("tick_history_days", 0.0) or 0.0) >= MIN_HISTORY_DAYS,
        "minimum_l2_history_days_satisfied": float(totals.get("l2_history_days", 0.0) or 0.0) >= MIN_HISTORY_DAYS,
        "minimum_common_calendar_span_days_satisfied": float(totals.get("common_calendar_span_days", 0.0) or 0.0)
        >= MIN_HISTORY_DAYS,
    }
    validation["contract_satisfied"] = all(validation.values())
    return validation


def _blockers(
    *,
    validation: Mapping[str, bool],
    manifests: list[Mapping[str, Any]],
    totals: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not validation["import_manifests_present"]:
        blockers.append("btc_long_horizon_l2_tick_import_manifest_missing")
    if not validation["public_or_licensed_archive_boundary_satisfied"]:
        blockers.append("btc_long_horizon_l2_tick_import_public_or_licensed_boundary_not_satisfied")
    if not validation["private_order_broker_boundary_satisfied"]:
        blockers.append("btc_long_horizon_l2_tick_import_private_order_broker_boundary_not_satisfied")
    if not validation["file_integrity_satisfied"]:
        blockers.append("btc_long_horizon_l2_tick_import_file_integrity_not_satisfied")
    if not validation["tick_history_present"]:
        blockers.append("btc_long_horizon_l2_tick_import_tick_history_missing")
    if not validation["l2_order_book_history_present"]:
        blockers.append("btc_long_horizon_l2_tick_import_l2_order_book_history_missing")
    if not validation["minimum_tick_history_days_satisfied"]:
        blockers.append(
            "btc_long_horizon_l2_tick_import_tick_history_days_short_"
            f"{float(totals.get('remaining_tick_history_days', 0.0) or 0.0):.6f}"
        )
    if not validation["minimum_l2_history_days_satisfied"]:
        blockers.append(
            "btc_long_horizon_l2_tick_import_l2_history_days_short_"
            f"{float(totals.get('remaining_l2_history_days', 0.0) or 0.0):.6f}"
        )
    if not validation["minimum_common_calendar_span_days_satisfied"]:
        blockers.append(
            "btc_long_horizon_l2_tick_import_common_calendar_span_days_short_"
            f"{float(totals.get('remaining_common_calendar_span_days', 0.0) or 0.0):.6f}"
        )
    for manifest in manifests:
        blockers.extend(_list_of_strings(manifest.get("blockers")))
    return _dedupe(blockers)


def _span_days(files: list[Mapping[str, Any]]) -> float:
    starts = [_datetime_or_none(item.get("sample_start")) for item in files]
    ends = [_datetime_or_none(item.get("sample_end")) for item in files]
    clean_starts = [item for item in starts if item is not None]
    clean_ends = [item for item in ends if item is not None]
    if not clean_starts or not clean_ends:
        return 0.0
    return _window_days(min(clean_starts), max(clean_ends))


def _common_window(
    *,
    tick_files: list[Mapping[str, Any]],
    l2_files: list[Mapping[str, Any]],
) -> tuple[datetime | None, datetime | None]:
    tick_start = min((_datetime_or_none(item.get("sample_start")) for item in tick_files), default=None)
    tick_end = max((_datetime_or_none(item.get("sample_end")) for item in tick_files), default=None)
    l2_start = min((_datetime_or_none(item.get("sample_start")) for item in l2_files), default=None)
    l2_end = max((_datetime_or_none(item.get("sample_end")) for item in l2_files), default=None)
    if not tick_start or not tick_end or not l2_start or not l2_end:
        return None, None
    start = max(tick_start, l2_start)
    end = min(tick_end, l2_end)
    if end <= start:
        return None, None
    return start, end


def _window_days(start: datetime | None, end: datetime | None) -> float:
    if not start or not end:
        return 0.0
    return max(0.0, (end - start).total_seconds() / 86_400.0)


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
