from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA_VERSION = "evidence_registry_v1"
LEGACY_INDEX_SCHEMA_VERSION = "paper_review_evidence_index_v2"
EVIDENCE_REF_SCHEMA_VERSION = "evidence_ref_v1"
CANDIDATE_CHAIN_SCHEMA_VERSION = "candidate_evidence_chain_v1"

INTEGRITY_PASS = "PASS/STABLE"
INTEGRITY_STALE = "STALE/CHANGED"
INTEGRITY_MISSING = "MISSING"
INTEGRITY_CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class EvidenceRef:
    evidence_type: str
    evidence_id: str
    path: str
    status: str
    schema_version: str = EVIDENCE_REF_SCHEMA_VERSION
    integrity_status: str = INTEGRITY_MISSING
    created_at: str = ""
    sha256: str = ""
    size: int = 0
    mtime: str = ""
    size_bytes: int = 0
    mtime_ns: int = 0
    observed_at: str = ""
    content_type: str = ""
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateEvidenceChain:
    candidate_id: str
    status: str
    candidate_path: str
    schema_version: str = CANDIDATE_CHAIN_SCHEMA_VERSION
    chain_status: str = INTEGRITY_MISSING
    experiment_id: str = ""
    notes: list[str] = field(default_factory=list)
    data_manifest: EvidenceRef = field(
        default_factory=lambda: EvidenceRef("data_manifest", "", "", "missing")
    )
    backtest_manifest: EvidenceRef = field(
        default_factory=lambda: EvidenceRef("backtest_manifest", "", "", "missing")
    )
    promotion_result: EvidenceRef = field(
        default_factory=lambda: EvidenceRef("promotion_result", "", "", "missing")
    )
    strategy_manifest: EvidenceRef = field(
        default_factory=lambda: EvidenceRef("strategy_manifest", "", "", "missing")
    )
    paper_review: EvidenceRef = field(
        default_factory=lambda: EvidenceRef("paper_review", "", "", "missing")
    )
    daily_report: EvidenceRef = field(
        default_factory=lambda: EvidenceRef("daily_report", "", "", "stale")
    )


def rebuild_evidence_registry(
    data_root: str | Path = "data",
    *,
    write: bool = True,
) -> dict[str, Any]:
    root = Path(data_root)
    scanned = _scan_all_evidence(root)
    registry = _build_registry_payload(root, scanned)
    if write:
        _registry_path(root).parent.mkdir(parents=True, exist_ok=True)
        _registry_path(root).write_text(
            json.dumps(registry, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _legacy_index_path(root).write_text(
            json.dumps(_legacy_index_payload(registry), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return registry


def inspect_evidence_registry(
    data_root: str | Path = "data",
    *,
    use_saved: bool = True,
    rebuild_if_missing: bool = True,
) -> dict[str, Any]:
    root = Path(data_root)
    if use_saved:
        saved = _load_saved_registry(root)
        if saved is not None:
            current = _scan_all_evidence(root)
            saved_status, saved_notes = _registry_storage_status(saved, current)
            result = dict(saved)
            result["registry_status"] = saved_status
            result["registry_integrity_status"] = _registry_integrity_status(saved_status)
            result["registry_notes"] = saved_notes
            result["rebuild_available"] = True
            return result
        if not rebuild_if_missing:
            return {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "generated_at": "",
                "registry_status": "missing",
                "registry_integrity_status": INTEGRITY_MISSING,
                "registry_notes": ["missing_registry_snapshot"],
                "rebuild_available": True,
                "counts": {},
                "chains": {},
            }
    result = rebuild_evidence_registry(root, write=rebuild_if_missing)
    result["registry_status"] = "rebuilt"
    result["registry_integrity_status"] = INTEGRITY_PASS
    result["registry_notes"] = []
    result["rebuild_available"] = True
    return result


def inspect_candidate_evidence(
    candidate_id: str,
    data_root: str | Path = "data",
    *,
    use_saved: bool = True,
    rebuild_if_missing: bool = True,
) -> CandidateEvidenceChain:
    root = Path(data_root)
    saved_registry = _load_saved_registry(root) if use_saved else None
    registry = inspect_evidence_registry(
        data_root,
        use_saved=use_saved,
        rebuild_if_missing=rebuild_if_missing,
    )
    if use_saved and registry.get("registry_status") in {"stale", "changed"}:
        live_registry = inspect_evidence_registry(
            data_root,
            use_saved=False,
            rebuild_if_missing=rebuild_if_missing,
        )
        live_chain = _chain_from_registry(live_registry, candidate_id)
        saved_chain = _chain_from_registry(saved_registry or {}, candidate_id)
        if live_chain is not None:
            return _merge_saved_chain_delta(
                saved_chain=saved_chain,
                live_chain=live_chain,
            )
        registry = live_registry
    chain = registry.get("chains", {}).get(candidate_id)
    if isinstance(chain, dict):
        return _dict_to_chain(chain)
    return CandidateEvidenceChain(
        candidate_id=candidate_id,
        status="missing",
        candidate_path="",
        chain_status=INTEGRITY_MISSING,
        notes=[f"candidate_not_indexed:{candidate_id}"],
    )


def _build_registry_payload(root: Path, scanned: dict[str, Any]) -> dict[str, Any]:
    chains: dict[str, dict[str, Any]] = {}
    latest_daily_report = _latest_row(scanned["daily_reports"])
    for candidate_id, candidate_row in scanned["candidates"].items():
        chains[candidate_id] = asdict(
            _build_candidate_chain(
                root=root,
                candidate_id=candidate_id,
                candidate_row=candidate_row,
                strategy_manifests=scanned["strategy_manifests"],
                promotion_results=scanned["promotion_results"],
                paper_reviews=scanned["paper_reviews"],
                data_manifests=scanned["data_manifests"],
                latest_daily_report=latest_daily_report,
            )
        )

    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "evidence_ref_schema_version": EVIDENCE_REF_SCHEMA_VERSION,
        "candidate_chain_schema_version": CANDIDATE_CHAIN_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry_path": str(_registry_path(root)),
        "legacy_index_path": str(_legacy_index_path(root)),
        "registry_notes": [],
        "counts": {
            "candidate_count": len(scanned["candidates"]),
            "data_manifest_count": len(scanned["data_manifests"]),
            "backtest_manifest_count": len(scanned["backtest_manifests"]),
            "promotion_result_count": len(scanned["promotion_results"]),
            "strategy_manifest_count": len(scanned["strategy_manifests"]),
            "paper_review_count": len(scanned["paper_reviews"]),
            "daily_report_count": len(scanned["daily_reports"]),
        },
        "latest": {
            "daily_report_path": str(latest_daily_report.get("path", "")) if latest_daily_report else "",
            "strategy_manifest_path": str(_latest_row(scanned["strategy_manifests"]).get("path", "")) if scanned["strategy_manifests"] else "",
            "paper_review_path": str(_latest_row(scanned["paper_reviews"]).get("path", "")) if scanned["paper_reviews"] else "",
            "promotion_result_path": str(_latest_row(scanned["promotion_results"]).get("path", "")) if scanned["promotion_results"] else "",
        },
        "evidence": {
            "data_manifests": scanned["data_manifests"],
            "backtest_manifests": scanned["backtest_manifests"],
            "promotion_results": scanned["promotion_results"],
            "strategy_manifests": scanned["strategy_manifests"],
            "paper_reviews": scanned["paper_reviews"],
            "daily_reports": scanned["daily_reports"],
            "candidates": list(scanned["candidates"].values()),
        },
        "chains": chains,
    }


def _build_candidate_chain(
    *,
    root: Path,
    candidate_id: str,
    candidate_row: dict[str, Any],
    strategy_manifests: list[dict[str, Any]],
    promotion_results: list[dict[str, Any]],
    paper_reviews: list[dict[str, Any]],
    data_manifests: list[dict[str, Any]],
    latest_daily_report: dict[str, Any] | None,
) -> CandidateEvidenceChain:
    payload = candidate_row.get("payload", {})
    data_version = str(payload.get("data_version", "") or "")
    experiment_id = str(payload.get("experiment_id", "") or "")
    notes: list[str] = []

    data_row = next(
        (row for row in data_manifests if row.get("data_version") == data_version),
        None,
    )
    data_ref = _row_to_ref(
        data_row,
        evidence_type="data_manifest",
        fallback_id=data_version,
        missing_summary=f"missing_data_manifest:{data_version or 'unknown'}",
    )
    notes.extend(_ref_notes(data_ref))

    backtest_ref = _resolve_backtest_manifest(root, candidate_id, payload)
    if backtest_ref.status == "stale":
        notes.append("backtest_manifest_link_missing_but_recoverable")
    notes.extend(_ref_notes(backtest_ref))

    promotion_row = _latest_row(
        [row for row in promotion_results if candidate_id in row.get("candidate_ids", [])]
    )
    promotion_ref = _row_to_ref(
        promotion_row,
        evidence_type="promotion_result",
        fallback_id=candidate_id,
        missing_summary=f"missing_promotion_result:{candidate_id}",
    )
    notes.extend(_ref_notes(promotion_ref))

    strategy_row = _latest_row(
        [
            row
            for row in strategy_manifests
            if row.get("source_candidate_id") == candidate_id
            or row.get("strategy_candidate_id") == candidate_id
        ]
    )
    strategy_ref = _row_to_ref(
        strategy_row,
        evidence_type="strategy_manifest",
        fallback_id=candidate_id,
        missing_summary=f"missing_strategy_manifest:{candidate_id}",
    )
    notes.extend(_ref_notes(strategy_ref))

    strategy_manifest_id = str(strategy_row.get("strategy_candidate_id", "")) if strategy_row else ""
    paper_row = _latest_row(
        [
            row
            for row in paper_reviews
            if row.get("strategy_manifest_id") in {candidate_id, strategy_manifest_id}
        ]
    )
    paper_ref = _row_to_ref(
        paper_row,
        evidence_type="paper_review",
        fallback_id=strategy_manifest_id or candidate_id,
        missing_summary=f"missing_paper_review:{strategy_manifest_id or candidate_id}",
    )
    notes.extend(_ref_notes(paper_ref))

    daily_ref = _daily_report_ref(latest_daily_report)
    if daily_ref.status != "present":
        notes.append(f"daily_report_{daily_ref.status}")
    notes.extend(_ref_notes(daily_ref, optional=True))

    chain_status = _chain_status(
        [
            data_ref,
            backtest_ref,
            promotion_ref,
            strategy_ref,
            paper_ref,
            daily_ref,
        ]
    )
    return CandidateEvidenceChain(
        candidate_id=candidate_id,
        status=_legacy_chain_status(chain_status),
        candidate_path=str(candidate_row.get("path", "")),
        chain_status=chain_status,
        experiment_id=experiment_id,
        notes=_dedupe_notes(notes),
        data_manifest=data_ref,
        backtest_manifest=backtest_ref,
        promotion_result=promotion_ref,
        strategy_manifest=strategy_ref,
        paper_review=paper_ref,
        daily_report=daily_ref,
    )


def _resolve_backtest_manifest(
    root: Path,
    candidate_id: str,
    candidate_payload: dict[str, Any],
) -> EvidenceRef:
    raw_path = str(candidate_payload.get("backtest_manifest_path", "") or "")
    manifest_path = _resolve_reference_path(root, raw_path)
    canonical_path = root / "research" / "backtests" / candidate_id / "run_manifest.json"
    fallback_id = candidate_id
    if manifest_path is not None and manifest_path.exists():
        payload = _load_json(manifest_path)
        return EvidenceRef(
            evidence_type="backtest_manifest",
            evidence_id=str(payload.get("run_id") or candidate_id),
            path=str(manifest_path),
            status="present",
            integrity_status=INTEGRITY_PASS,
            created_at=_payload_created_at(payload, manifest_path),
            sha256=_file_sha256(manifest_path),
            size=_file_size_bytes(manifest_path),
            mtime=_file_mtime(manifest_path),
            size_bytes=_file_size_bytes(manifest_path),
            mtime_ns=_file_mtime_ns(manifest_path),
            observed_at=_observed_at(),
            content_type=_content_type(manifest_path),
            summary=str(payload.get("engine", "event_driven")),
            details={
                "canonical_for_promotion": bool(payload.get("canonical_for_promotion", False)),
                "data_version": str(payload.get("data_version", "")),
                "commit_hash": str(payload.get("commit_hash", "")),
            },
        )
    if raw_path and manifest_path is not None and not manifest_path.exists():
        return EvidenceRef(
            evidence_type="backtest_manifest",
            evidence_id=fallback_id,
            path=str(manifest_path),
            status="missing",
            integrity_status=INTEGRITY_MISSING,
            observed_at=_observed_at(),
            content_type=_content_type(manifest_path),
            summary=f"missing_backtest_manifest:{manifest_path}",
        )
    if canonical_path.exists():
        payload = _load_json(canonical_path)
        return EvidenceRef(
            evidence_type="backtest_manifest",
            evidence_id=str(payload.get("run_id") or candidate_id),
            path=str(canonical_path),
            status="stale",
            integrity_status=INTEGRITY_STALE,
            created_at=_payload_created_at(payload, canonical_path),
            sha256=_file_sha256(canonical_path),
            size=_file_size_bytes(canonical_path),
            mtime=_file_mtime(canonical_path),
            size_bytes=_file_size_bytes(canonical_path),
            mtime_ns=_file_mtime_ns(canonical_path),
            observed_at=_observed_at(),
            content_type=_content_type(canonical_path),
            summary="canonical_backtest_manifest_found_but_candidate_path_missing",
            details={
                "canonical_for_promotion": bool(payload.get("canonical_for_promotion", False)),
                "data_version": str(payload.get("data_version", "")),
                "commit_hash": str(payload.get("commit_hash", "")),
            },
        )
    return EvidenceRef(
        evidence_type="backtest_manifest",
        evidence_id=fallback_id,
        path=str(canonical_path if not raw_path else _resolve_reference_path(root, raw_path) or canonical_path),
        status="missing",
        integrity_status=INTEGRITY_MISSING,
        observed_at=_observed_at(),
        content_type=_content_type(canonical_path if not raw_path else _resolve_reference_path(root, raw_path) or canonical_path),
        summary=f"missing_backtest_manifest:{candidate_id}",
    )


def _daily_report_ref(row: dict[str, Any] | None) -> EvidenceRef:
    if row is None:
        return EvidenceRef(
            evidence_type="daily_report",
            evidence_id="",
            path="",
            status="missing",
            integrity_status=INTEGRITY_MISSING,
            observed_at=_observed_at(),
            summary="missing_daily_report",
        )
    report_date = str(row.get("report_date", "") or "")
    status = "present"
    integrity_status = INTEGRITY_PASS
    try:
        if report_date and date.fromisoformat(report_date) < datetime.now(timezone.utc).date():
            status = "stale"
            integrity_status = INTEGRITY_STALE
    except ValueError:
        status = "stale"
        integrity_status = INTEGRITY_STALE
    return _row_to_ref(
        row,
        evidence_type="daily_report",
        fallback_id=report_date,
        missing_summary="missing_daily_report",
        override_status=status,
        override_integrity_status=integrity_status,
    )


def _row_to_ref(
    row: dict[str, Any] | None,
    *,
    evidence_type: str,
    fallback_id: str,
    missing_summary: str,
    override_status: str | None = None,
    override_integrity_status: str | None = None,
) -> EvidenceRef:
    if row is None:
        return EvidenceRef(
            evidence_type=evidence_type,
            evidence_id=fallback_id,
            path="",
            status="missing",
            integrity_status=INTEGRITY_MISSING,
            observed_at=_observed_at(),
            summary=missing_summary,
        )
    return EvidenceRef(
        evidence_type=evidence_type,
        evidence_id=str(row.get("id") or row.get("data_version") or fallback_id),
        path=str(row.get("path", "")),
        status=override_status or str(row.get("status", "present")),
        schema_version=str(row.get("schema_version", EVIDENCE_REF_SCHEMA_VERSION)),
        integrity_status=override_integrity_status or str(row.get("integrity_status", _legacy_ref_integrity_status(str(row.get("status", "present"))))),
        created_at=str(row.get("created_at", "")),
        sha256=str(row.get("sha256", "")),
        size=int(row.get("size", row.get("size_bytes", 0)) or 0),
        mtime=str(row.get("mtime", "")),
        size_bytes=int(row.get("size_bytes", 0) or 0),
        mtime_ns=int(row.get("mtime_ns", 0) or 0),
        observed_at=str(row.get("observed_at", "")),
        content_type=str(row.get("content_type", "")),
        summary=str(row.get("summary", "")),
        details=dict(row.get("details", {})),
    )


def _chain_status(refs: list[EvidenceRef]) -> str:
    required_refs = refs[:-1]
    if any(ref.integrity_status == INTEGRITY_CONFLICT for ref in refs):
        return INTEGRITY_CONFLICT
    if any(ref.integrity_status == INTEGRITY_MISSING for ref in required_refs):
        return INTEGRITY_MISSING
    if any(ref.integrity_status == INTEGRITY_STALE for ref in refs):
        return INTEGRITY_STALE
    return INTEGRITY_PASS


def _scan_all_evidence(root: Path) -> dict[str, Any]:
    return {
        "candidates": _scan_candidates(root),
        "data_manifests": _scan_data_manifests(root),
        "backtest_manifests": _scan_backtest_manifests(root),
        "promotion_results": _scan_promotion_results(root),
        "strategy_manifests": _scan_strategy_manifests(root),
        "paper_reviews": _scan_paper_reviews(root),
        "daily_reports": _scan_daily_reports(root),
    }


def _scan_candidates(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path, payload in _scan_json_rows(root / "research" / "candidates", "candidate.json"):
        candidate_id = str(payload.get("candidate_id") or path.parent.name)
        rows[candidate_id] = _normalize_scanned_row(
            {
            "id": candidate_id,
            "path": str(path),
            "created_at": _payload_created_at(payload, path),
            "status": "present",
            "sha256": _file_sha256(path),
            "size_bytes": _file_size_bytes(path),
            "mtime_ns": _file_mtime_ns(path),
            "observed_at": _observed_at(),
            "content_type": _content_type(path),
            "payload": payload,
            }
        )
    return rows


def _scan_data_manifests(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    manifests_root = root / "manifests"
    if not manifests_root.exists():
        return rows
    for path in sorted(manifests_root.glob("*.json")):
        if path.stem.startswith("run_"):
            continue
        payload = _load_json(path)
        if not _looks_like_data_manifest(payload):
            continue
        rows.append(
            {
                "id": str(payload.get("data_version", "") or path.stem),
                "data_version": str(payload.get("data_version", "") or path.stem),
                "path": str(path),
                "created_at": _payload_created_at(payload, path),
                "status": "present",
                "sha256": _file_sha256(path),
                "size_bytes": _file_size_bytes(path),
                "mtime_ns": _file_mtime_ns(path),
                "observed_at": _observed_at(),
                "content_type": _content_type(path),
                "summary": str(payload.get("symbol", "")),
                "details": {
                    "source": str(payload.get("source", "")),
                    "interval": str(payload.get("interval", "")),
                    "quality_score": float(payload.get("quality_score", 0.0)),
                },
            }
        )
    return _sort_rows(_normalize_scanned_rows(rows))


def _scan_backtest_manifests(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "research" / "backtests").glob("*/run_manifest.json")):
        payload = _load_json(path)
        candidate_id = path.parent.name
        rows.append(
            {
                "id": str(payload.get("run_id") or candidate_id),
                "candidate_id": candidate_id,
                "path": str(path),
                "created_at": _payload_created_at(payload, path),
                "status": "present",
                "sha256": _file_sha256(path),
                "size_bytes": _file_size_bytes(path),
                "mtime_ns": _file_mtime_ns(path),
                "observed_at": _observed_at(),
                "content_type": _content_type(path),
                "summary": str(payload.get("engine", "")),
                "details": {
                    "canonical_for_promotion": bool(payload.get("canonical_for_promotion", False)),
                    "data_version": str(payload.get("data_version", "")),
                    "commit_hash": str(payload.get("commit_hash", "")),
                },
            }
        )
    for path in sorted((root / "manifests").glob("run_*.json")):
        payload = _load_json(path)
        rows.append(
            {
                "id": str(payload.get("run_id") or path.stem),
                "candidate_id": "",
                "path": str(path),
                "created_at": _payload_created_at(payload, path),
                "status": "present",
                "sha256": _file_sha256(path),
                "size_bytes": _file_size_bytes(path),
                "mtime_ns": _file_mtime_ns(path),
                "observed_at": _observed_at(),
                "content_type": _content_type(path),
                "summary": str(payload.get("engine", "")),
                "details": {
                    "canonical_for_promotion": bool(payload.get("canonical_for_promotion", False)),
                    "data_version": str(payload.get("data_version", "")),
                    "commit_hash": str(payload.get("commit_hash", "")),
                },
            }
        )
    return _sort_rows(_normalize_scanned_rows(rows))


def _scan_promotion_results(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "research" / "pipeline_results").glob("*.json")):
        payload = _load_json(path)
        gate_results = payload.get("promotion_gate_results", {})
        if not isinstance(gate_results, dict):
            continue
        rows.append(
            {
                "id": str(payload.get("pipeline_id") or path.stem),
                "candidate_ids": sorted(gate_results.keys()),
                "path": str(path),
                "created_at": str(payload.get("created_at", "")),
                "status": "present",
                "sha256": _file_sha256(path),
                "size_bytes": _file_size_bytes(path),
                "mtime_ns": _file_mtime_ns(path),
                "observed_at": _observed_at(),
                "content_type": _content_type(path),
                "summary": str(payload.get("status", "")),
                "details": {
                    "paper_review_ready": list(payload.get("paper_review_ready", [])),
                    "promotion_gate_results": gate_results,
                },
            }
        )
    return _sort_rows(_normalize_scanned_rows(rows))


def _scan_strategy_manifests(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, payload in _scan_json_rows(root / "research" / "manifests", "manifest.json"):
        rows.append(
            {
                "id": str(payload.get("strategy_candidate_id") or path.parent.name),
                "strategy_candidate_id": str(payload.get("strategy_candidate_id") or path.parent.name),
                "source_candidate_id": str(payload.get("source_candidate_id", "")),
                "path": str(path),
                "created_at": _payload_created_at(payload, path),
                "status": "present",
                "sha256": _file_sha256(path),
                "size_bytes": _file_size_bytes(path),
                "mtime_ns": _file_mtime_ns(path),
                "observed_at": _observed_at(),
                "content_type": _content_type(path),
                "summary": str(payload.get("promotion_status", "")),
                "details": {
                    "promotion_status": str(payload.get("promotion_status", "")),
                    "source_experiment_id": str(payload.get("source_experiment_id", "")),
                },
            }
        )
    return _sort_rows(_normalize_scanned_rows(rows))


def _scan_paper_reviews(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, payload in _scan_json_rows(root / "research" / "paper_reviews", "review.json"):
        approval = payload.get("approval", {})
        if not isinstance(approval, dict):
            approval = {}
        rows.append(
            {
                "id": str(payload.get("paper_review_id") or path.parent.name),
                "strategy_manifest_id": str(payload.get("strategy_manifest_id", "")),
                "path": str(path),
                "created_at": _payload_created_at(payload, path),
                "status": "present",
                "sha256": _file_sha256(path),
                "size_bytes": _file_size_bytes(path),
                "mtime_ns": _file_mtime_ns(path),
                "observed_at": _observed_at(),
                "content_type": _content_type(path),
                "summary": str(payload.get("status", "")),
                "details": {
                    "status": str(payload.get("status", "")),
                    "evidence_pack_path": str(payload.get("evidence_pack_path", "")),
                    "candidate_id": str(approval.get("candidate_id", "")),
                    "reviewer": str(payload.get("reviewer", "")),
                    "reviewed_at": str(payload.get("reviewed_at", "")),
                    "reason": str(payload.get("review_notes", "")),
                    "approval": dict(approval),
                },
            }
        )
    return _sort_rows(_normalize_scanned_rows(rows))


def _scan_daily_reports(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/daily_report_*.json")):
        payload = _load_json(path)
        rows.append(
            {
                "id": str(payload.get("report_date") or path.stem),
                "report_date": str(payload.get("report_date", "")),
                "path": str(path),
                "created_at": str(payload.get("generated_at", "")) or _payload_created_at(payload, path),
                "status": "present",
                "sha256": _file_sha256(path),
                "size_bytes": _file_size_bytes(path),
                "mtime_ns": _file_mtime_ns(path),
                "observed_at": _observed_at(),
                "content_type": _content_type(path),
                "summary": str(payload.get("reconciliation_status", "")),
                "details": {
                    "orders_submitted": int(payload.get("orders_submitted", 0)),
                    "kill_switch_triggered": bool(payload.get("kill_switch_triggered", False)),
                },
            }
        )
    return _sort_rows(_normalize_scanned_rows(rows))


def _legacy_index_payload(registry: dict[str, Any]) -> dict[str, Any]:
    reviews = list(registry.get("evidence", {}).get("paper_reviews", []))
    manifests = list(registry.get("evidence", {}).get("strategy_manifests", []))
    latest_review = _latest_row(reviews)
    latest_manifest = _latest_row(manifests)
    return {
        "schema_version": LEGACY_INDEX_SCHEMA_VERSION,
        "generated_at": str(registry.get("generated_at", "")),
        "latest_review_path": str(latest_review.get("path", "")) if latest_review else "",
        "latest_manifest_path": str(latest_manifest.get("path", "")) if latest_manifest else "",
        "review_count": len(reviews),
        "manifest_count": len(manifests),
        "reviews": [
            {
                "path": row.get("path", ""),
                "id": row.get("id", ""),
                "status": row.get("details", {}).get("status", row.get("summary", "")),
                "created_at": row.get("created_at", ""),
            }
            for row in reviews
        ],
        "manifests": [
            {
                "path": row.get("path", ""),
                "id": row.get("strategy_candidate_id", row.get("id", "")),
                "status": row.get("details", {}).get("promotion_status", row.get("summary", "")),
                "created_at": row.get("created_at", ""),
            }
            for row in manifests
        ],
        "registry_path": str(registry.get("registry_path", "")),
    }


def _registry_path(root: Path) -> Path:
    return root / "research" / "evidence_registry.json"


def _legacy_index_path(root: Path) -> Path:
    return root / "research" / "paper_review_index.json"


def _load_saved_registry(root: Path) -> dict[str, Any] | None:
    for path in (_registry_path(root), _legacy_index_path(root)):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("schema_version") == REGISTRY_SCHEMA_VERSION:
            return payload
        if payload.get("registry_path"):
            registry_path = Path(str(payload.get("registry_path")))
            if registry_path.exists():
                try:
                    registry = json.loads(registry_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(registry, dict) and registry.get("schema_version") == REGISTRY_SCHEMA_VERSION:
                    return registry
    return None


def _registry_storage_status(saved: dict[str, Any], current: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []
    saved_paths = _registry_evidence_paths(saved)
    missing_paths = [path for path in sorted(saved_paths) if not Path(path).exists()]
    if missing_paths:
        notes.extend(f"missing_artifact:{path}" for path in missing_paths)
        return "stale", notes

    saved_counts = dict(saved.get("counts", {}))
    current_counts = {
        "candidate_count": len(current["candidates"]),
        "data_manifest_count": len(current["data_manifests"]),
        "backtest_manifest_count": len(current["backtest_manifests"]),
        "promotion_result_count": len(current["promotion_results"]),
        "strategy_manifest_count": len(current["strategy_manifests"]),
        "paper_review_count": len(current["paper_reviews"]),
        "daily_report_count": len(current["daily_reports"]),
    }
    for key, current_count in current_counts.items():
        if int(saved_counts.get(key, 0)) != current_count:
            notes.append(f"stale_snapshot:count_mismatch:{key}")
            return "stale", notes

    current_paths = _scanned_evidence_paths(current)
    if saved_paths != current_paths:
        notes.append("stale_snapshot:path_set_changed")
        return "stale", notes

    saved_meta = _registry_evidence_meta(saved)
    current_meta = _scanned_evidence_meta(current)
    if set(saved_meta) != set(current_meta):
        notes.append("stale_snapshot:meta_index_changed")
        return "stale", notes
    changed_paths: list[str] = []
    incomplete_saved_meta: list[str] = []
    for path in sorted(current_meta):
        saved_row = saved_meta[path]
        current_row = current_meta[path]
        if not _row_has_integrity_meta(saved_row):
            incomplete_saved_meta.append(path)
            continue
        if not _artifact_meta_matches(saved_row, current_row):
            changed_paths.append(path)
    if incomplete_saved_meta:
        notes.extend(f"stale_snapshot:missing_integrity_meta:{path}" for path in incomplete_saved_meta)
        return "stale", notes
    if changed_paths:
        notes.extend(f"content_changed:{path}" for path in changed_paths)
        return "changed", notes

    saved_generated_at = _parse_dt(str(saved.get("generated_at", "")))
    latest_evidence_time = max(
        (
            _artifact_event_time(row)
            for section in (
                current["data_manifests"],
                current["backtest_manifests"],
                current["promotion_results"],
                current["strategy_manifests"],
                current["paper_reviews"],
                current["daily_reports"],
            )
            for row in section
        ),
        default=datetime.min.replace(tzinfo=timezone.utc),
    )
    if not saved_generated_at:
        notes.append("stale_snapshot:missing_generated_at")
        return "stale", notes
    if latest_evidence_time > saved_generated_at:
        notes.append("stale_snapshot:source_newer_than_registry")
        return "stale", notes
    return "present", notes


def _registry_evidence_paths(registry: dict[str, Any]) -> set[str]:
    evidence = dict(registry.get("evidence", {}))
    paths: set[str] = set()
    for section_name in (
        "data_manifests",
        "backtest_manifests",
        "promotion_results",
        "strategy_manifests",
        "paper_reviews",
        "daily_reports",
        "candidates",
    ):
        rows = evidence.get(section_name, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("path"):
                paths.add(str(row["path"]))
    return paths


def _scanned_evidence_paths(scanned: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for section_name in (
        "data_manifests",
        "backtest_manifests",
        "promotion_results",
        "strategy_manifests",
        "paper_reviews",
        "daily_reports",
    ):
        for row in scanned[section_name]:
            if row.get("path"):
                paths.add(str(row["path"]))
    for row in scanned["candidates"].values():
        if row.get("path"):
            paths.add(str(row["path"]))
    return paths


def _registry_evidence_meta(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence = dict(registry.get("evidence", {}))
    rows: dict[str, dict[str, Any]] = {}
    for section_name in (
        "data_manifests",
        "backtest_manifests",
        "promotion_results",
        "strategy_manifests",
        "paper_reviews",
        "daily_reports",
        "candidates",
    ):
        section_rows = evidence.get(section_name, [])
        if not isinstance(section_rows, list):
            continue
        for row in section_rows:
            if isinstance(row, dict) and row.get("path"):
                rows[str(row["path"])] = row
    return rows


def _scanned_evidence_meta(scanned: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for section_name in (
        "data_manifests",
        "backtest_manifests",
        "promotion_results",
        "strategy_manifests",
        "paper_reviews",
        "daily_reports",
    ):
        for row in scanned[section_name]:
            if row.get("path"):
                rows[str(row["path"])] = row
    for row in scanned["candidates"].values():
            if row.get("path"):
                rows[str(row["path"])] = row
    return rows


def _normalize_scanned_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_scanned_row(row) for row in rows]
    _mark_conflicts(normalized)
    return normalized


def _normalize_scanned_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    status = str(normalized.get("status", "present"))
    normalized["schema_version"] = str(
        normalized.get("schema_version", EVIDENCE_REF_SCHEMA_VERSION)
    )
    normalized["integrity_status"] = str(
        normalized.get("integrity_status", _legacy_ref_integrity_status(status))
    )
    normalized["size"] = int(
        normalized.get("size", normalized.get("size_bytes", 0)) or 0
    )
    normalized["mtime"] = str(
        normalized.get("mtime", _mtime_ns_to_iso(normalized.get("mtime_ns", 0)))
    )
    return normalized


def _mark_conflicts(rows: list[dict[str, Any]]) -> None:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row_id = str(row.get("id", "")).strip()
        if not row_id:
            continue
        by_id.setdefault(row_id, []).append(row)
    for row_id, group in by_id.items():
        if len(group) < 2:
            continue
        path_set = {str(row.get("path", "")) for row in group if row.get("path")}
        hash_set = {str(row.get("sha256", "")) for row in group if row.get("sha256")}
        if len(path_set) <= 1 and len(hash_set) <= 1:
            continue
        for row in group:
            row["status"] = "conflict"
            row["integrity_status"] = INTEGRITY_CONFLICT
            details = dict(row.get("details", {}))
            details["conflict_paths"] = sorted(path_set)
            details["conflict_hashes"] = sorted(hash_set)
            details["conflict_id"] = row_id
            row["details"] = details
            summary = str(row.get("summary", "")).strip()
            if summary:
                row["summary"] = f"conflict:{summary}"
            else:
                row["summary"] = f"conflict:{row_id}"


def _scan_json_rows(root: Path, leaf_name: str) -> list[tuple[Path, dict[str, Any]]]:
    if not root.exists():
        return []
    rows: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob(f"*/{leaf_name}")):
        payload = _load_json(path)
        if isinstance(payload, dict):
            rows.append((path, payload))
    return rows


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(
        key=lambda row: (
            str(row.get("created_at", "")),
            str(row.get("path", "")),
        ),
        reverse=True,
    )
    return rows


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return _sort_rows(list(rows))[0]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _looks_like_data_manifest(payload: dict[str, Any]) -> bool:
    return all(payload.get(key) for key in ("data_version", "source", "symbol", "interval"))


def _payload_created_at(payload: dict[str, Any], path: Path) -> str:
    created_at = str(payload.get("created_at", "") or payload.get("generated_at", ""))
    if created_at:
        return created_at
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _artifact_event_time(row: dict[str, Any]) -> datetime | None:
    mtime_ns = int(row.get("mtime_ns", 0) or 0)
    if mtime_ns > 0:
        return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=timezone.utc)
    return _parse_dt(str(row.get("created_at", "")))


def _resolve_reference_path(root: Path, raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return root / path


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _observed_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_type(path: Path | None) -> str:
    if path is None:
        return ""
    if path.suffix.lower() == ".json":
        return "application/json"
    return "application/octet-stream"


def _file_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _file_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _file_mtime(path: Path) -> str:
    return _mtime_ns_to_iso(_file_mtime_ns(path))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _row_has_integrity_meta(row: dict[str, Any]) -> bool:
    return bool(str(row.get("sha256", ""))) and int(row.get("size_bytes", 0) or 0) >= 0 and int(row.get("mtime_ns", 0) or 0) > 0


def _artifact_meta_matches(saved_row: dict[str, Any], current_row: dict[str, Any]) -> bool:
    return (
        str(saved_row.get("sha256", "")) == str(current_row.get("sha256", ""))
        and int(saved_row.get("size_bytes", 0) or 0) == int(current_row.get("size_bytes", 0) or 0)
        and int(saved_row.get("mtime_ns", 0) or 0) == int(current_row.get("mtime_ns", 0) or 0)
    )


def _mtime_ns_to_iso(value: Any) -> str:
    try:
        mtime_ns = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if mtime_ns <= 0:
        return ""
    return datetime.fromtimestamp(
        mtime_ns / 1_000_000_000,
        tz=timezone.utc,
    ).isoformat()


def _legacy_ref_integrity_status(status: str) -> str:
    if status == "missing":
        return INTEGRITY_MISSING
    if status in {"stale", "changed"}:
        return INTEGRITY_STALE
    if status == "conflict":
        return INTEGRITY_CONFLICT
    return INTEGRITY_PASS


def _legacy_chain_status(chain_status: str) -> str:
    if chain_status == INTEGRITY_MISSING:
        return "missing"
    if chain_status == INTEGRITY_CONFLICT:
        return "conflict"
    if chain_status == INTEGRITY_STALE:
        return "stale"
    return "complete"


def _registry_integrity_status(status: str) -> str:
    if status == "missing":
        return INTEGRITY_MISSING
    if status in {"stale", "changed"}:
        return INTEGRITY_STALE
    return INTEGRITY_PASS


def _ref_notes(ref: EvidenceRef, *, optional: bool = False) -> list[str]:
    prefix = ref.evidence_type
    if ref.integrity_status == INTEGRITY_CONFLICT:
        return [f"{prefix}_conflict:{ref.path or ref.evidence_id or 'unknown'}"]
    if ref.integrity_status == INTEGRITY_MISSING:
        if optional:
            return [f"{prefix}_missing_optional"]
        return [f"{prefix}_missing"]
    if ref.integrity_status == INTEGRITY_STALE:
        return [f"{prefix}_stale_or_changed"]
    return []


def _dedupe_notes(notes: list[str]) -> list[str]:
    return list(dict.fromkeys(note for note in notes if note))


def _chain_from_registry(
    registry: dict[str, Any],
    candidate_id: str,
) -> CandidateEvidenceChain | None:
    chains = registry.get("chains", {}) if isinstance(registry, dict) else {}
    if not isinstance(chains, dict):
        return None
    chain = chains.get(candidate_id)
    if isinstance(chain, dict):
        return _dict_to_chain(chain)
    return None


def _merge_saved_chain_delta(
    *,
    saved_chain: CandidateEvidenceChain | None,
    live_chain: CandidateEvidenceChain,
) -> CandidateEvidenceChain:
    if saved_chain is None:
        return live_chain
    notes = list(live_chain.notes)
    chain_status = live_chain.chain_status
    for evidence_type in (
        "data_manifest",
        "backtest_manifest",
        "promotion_result",
        "strategy_manifest",
        "paper_review",
        "daily_report",
    ):
        saved_ref = getattr(saved_chain, evidence_type)
        live_ref = getattr(live_chain, evidence_type)
        if saved_ref.path and live_ref.integrity_status == INTEGRITY_MISSING:
            notes.append(f"missing_evidence:{evidence_type}:{saved_ref.path}")
            chain_status = _merge_integrity_status(chain_status, INTEGRITY_MISSING)
            continue
        if saved_ref.path and live_ref.path and saved_ref.path != live_ref.path:
            notes.append(
                f"path_changed:{evidence_type}:{saved_ref.path}->{live_ref.path}"
            )
            chain_status = _merge_integrity_status(chain_status, INTEGRITY_STALE)
        if (
            saved_ref.path
            and live_ref.path
            and saved_ref.path == live_ref.path
            and saved_ref.sha256
            and live_ref.sha256
            and saved_ref.sha256 != live_ref.sha256
        ):
            notes.append(f"hash_changed:{evidence_type}:{live_ref.path}")
            chain_status = _merge_integrity_status(chain_status, INTEGRITY_STALE)
        if live_ref.integrity_status == INTEGRITY_CONFLICT:
            notes.append(f"conflicting_evidence:{evidence_type}:{live_ref.path}")
            chain_status = _merge_integrity_status(chain_status, INTEGRITY_CONFLICT)
    if saved_chain.experiment_id and live_chain.experiment_id != saved_chain.experiment_id:
        notes.append(
            f"candidate_changed:experiment_id:{saved_chain.experiment_id}->{live_chain.experiment_id}"
        )
        chain_status = _merge_integrity_status(chain_status, INTEGRITY_STALE)
    return replace(
        live_chain,
        status=_legacy_chain_status(chain_status),
        chain_status=chain_status,
        notes=_dedupe_notes(notes),
    )


def _merge_integrity_status(current: str, new: str) -> str:
    precedence = {
        INTEGRITY_PASS: 0,
        INTEGRITY_STALE: 1,
        INTEGRITY_MISSING: 2,
        INTEGRITY_CONFLICT: 3,
    }
    return new if precedence[new] > precedence[current] else current


def _dict_to_ref(data: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        evidence_type=str(data.get("evidence_type", "")),
        evidence_id=str(data.get("evidence_id", "")),
        path=str(data.get("path", "")),
        status=str(data.get("status", "")),
        schema_version=str(data.get("schema_version", EVIDENCE_REF_SCHEMA_VERSION)),
        integrity_status=str(
            data.get(
                "integrity_status",
                _legacy_ref_integrity_status(str(data.get("status", ""))),
            )
        ),
        created_at=str(data.get("created_at", "")),
        sha256=str(data.get("sha256", "")),
        size=int(data.get("size", data.get("size_bytes", 0)) or 0),
        mtime=str(data.get("mtime", "")),
        size_bytes=int(data.get("size_bytes", 0) or 0),
        mtime_ns=int(data.get("mtime_ns", 0) or 0),
        observed_at=str(data.get("observed_at", "")),
        content_type=str(data.get("content_type", "")),
        summary=str(data.get("summary", "")),
        details=dict(data.get("details", {})),
    )


def _dict_to_chain(data: dict[str, Any]) -> CandidateEvidenceChain:
    chain_status = str(
        data.get(
            "chain_status",
            data.get("integrity_status", ""),
        )
    ) or _registry_integrity_status(str(data.get("status", "missing")))
    return CandidateEvidenceChain(
        candidate_id=str(data.get("candidate_id", "")),
        status=str(data.get("status", "")),
        candidate_path=str(data.get("candidate_path", "")),
        schema_version=str(
            data.get("schema_version", CANDIDATE_CHAIN_SCHEMA_VERSION)
        ),
        chain_status=chain_status,
        experiment_id=str(data.get("experiment_id", "")),
        notes=[str(item) for item in data.get("notes", [])],
        data_manifest=_dict_to_ref(dict(data.get("data_manifest", {}))),
        backtest_manifest=_dict_to_ref(dict(data.get("backtest_manifest", {}))),
        promotion_result=_dict_to_ref(dict(data.get("promotion_result", {}))),
        strategy_manifest=_dict_to_ref(dict(data.get("strategy_manifest", {}))),
        paper_review=_dict_to_ref(dict(data.get("paper_review", {}))),
        daily_report=_dict_to_ref(dict(data.get("daily_report", {}))),
    )
