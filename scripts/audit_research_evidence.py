#!/usr/bin/env python3
"""Read-only audit for historical candidate/backtest/data-manifest evidence."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from quant_us.data.storage.data_manifest import (
    DataManifest,
    DataManifestStore,
    validate_manifest_for_promotion,
)


SCHEMA_VERSION = "research_evidence_audit_v1"
SEVERITY_BLOCKER = "BLOCKER"


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    code: str
    scope: str
    subject_id: str
    message: str
    path: str = ""
    candidate_id: str = ""
    data_version: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateRecord:
    candidate_id: str
    candidate_path: str
    data_version: str = ""
    backtest_manifest_path: str = ""
    canonical_backtest_manifest_path: str = ""
    canonical_backtest_manifest_exists: bool = False
    inline_backtest_manifest: bool = False
    resolved_backtest_manifest_path: str = ""
    blocker_codes: list[str] = field(default_factory=list)


@dataclass
class BacktestRecord:
    candidate_id: str
    path: str
    data_version: str = ""
    has_embedded_data_manifest: bool = False
    blocker_codes: list[str] = field(default_factory=list)


@dataclass
class DataManifestRecord:
    data_version: str
    canonical_path: str
    canonical_exists: bool
    paths: list[str]
    impacted_candidates: list[str]
    duplicate_count: int
    quality_score: float = 0.0
    coverage_pct: float = 0.0
    blocker_codes: list[str] = field(default_factory=list)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _try_load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "json_root_not_object"
    return payload, ""


def _looks_like_data_manifest(payload: dict[str, Any]) -> bool:
    return all(payload.get(key) for key in ("data_version", "source", "symbol", "interval"))


def _has_inline_manifest(candidate_data: dict[str, Any]) -> bool:
    metrics = candidate_data.get("metrics", {})
    return isinstance(candidate_data.get("backtest_manifest"), dict) or isinstance(
        metrics.get("backtest_manifest"), dict
    )


def _candidate_manifest_relpath(candidate_id: str) -> str:
    return str(Path("research") / "backtests" / candidate_id / "run_manifest.json")


def _candidate_manifest_path(data_root: Path, candidate_id: str) -> Path:
    return data_root / _candidate_manifest_relpath(candidate_id)


def _resolve_reference_path(root: Path, raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return root / path


def _data_manifest_from_payload(payload: dict[str, Any] | None) -> DataManifest | None:
    if not isinstance(payload, dict):
        return None
    allowed = {item.name for item in fields(DataManifest)}
    filtered = {key: value for key, value in payload.items() if key in allowed}
    required = {"data_version", "source", "symbol", "interval"}
    if not required.issubset(filtered):
        return None
    try:
        return DataManifest(**filtered)
    except (TypeError, ValueError):
        return None


def _compare_embedded_data_manifest(
    *,
    embedded: DataManifest,
    governed: DataManifest,
) -> list[str]:
    mismatches: list[str] = []
    if embedded.data_version != governed.data_version:
        mismatches.append(
            "data_manifest_version_mismatch: "
            f"embedded={embedded.data_version} governed={governed.data_version}"
        )
    if embedded.manifest_id != governed.manifest_id:
        mismatches.append(
            "data_manifest_id_mismatch: "
            f"embedded={embedded.manifest_id} governed={governed.manifest_id}"
        )
    if embedded.effective_checksum != governed.effective_checksum:
        mismatches.append(
            "data_manifest_checksum_mismatch: "
            f"embedded={embedded.effective_checksum} governed={governed.effective_checksum}"
        )
    if embedded.fingerprint != governed.fingerprint:
        mismatches.append(
            "data_manifest_fingerprint_mismatch: "
            f"embedded={embedded.fingerprint} governed={governed.fingerprint}"
        )
    return mismatches


def _scan_data_manifest_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    manifests_root = root / "manifests"
    if not manifests_root.exists():
        return rows
    for path in sorted(manifests_root.glob("*.json")):
        if path.stem.startswith("run_"):
            continue
        payload, error = _try_load_json(path)
        if payload is None or not _looks_like_data_manifest(payload):
            continue
        rows.append(
            {
                "path": path,
                "payload": payload,
                "data_version": str(payload.get("data_version", "") or ""),
            }
        )
    return rows


def _append_finding(
    findings: list[AuditFinding],
    *,
    severity: str,
    code: str,
    scope: str,
    subject_id: str,
    message: str,
    path: str = "",
    candidate_id: str = "",
    data_version: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    findings.append(
        AuditFinding(
            severity=severity,
            code=code,
            scope=scope,
            subject_id=subject_id,
            message=message,
            path=path,
            candidate_id=candidate_id,
            data_version=data_version,
            details=dict(details or {}),
        )
    )


def audit_research_evidence(data_root: str = "data") -> dict[str, Any]:
    root = Path(data_root)
    candidate_paths = sorted((root / "research" / "candidates").glob("*/candidate.json"))
    backtest_paths = sorted((root / "research" / "backtests").glob("*/run_manifest.json"))
    data_rows = _scan_data_manifest_rows(root)

    findings: list[AuditFinding] = []
    candidate_records: dict[str, CandidateRecord] = {}
    backtest_records: dict[str, BacktestRecord] = {}
    data_version_to_candidates: dict[str, set[str]] = {}

    for candidate_path in candidate_paths:
        dir_candidate_id = candidate_path.parent.name
        candidate_payload, error = _try_load_json(candidate_path)
        candidate_record = CandidateRecord(
            candidate_id=dir_candidate_id,
            candidate_path=str(candidate_path),
            canonical_backtest_manifest_path=str(_candidate_manifest_path(root, dir_candidate_id)),
        )
        candidate_records[dir_candidate_id] = candidate_record
        if candidate_payload is None:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="invalid_candidate_json",
                scope="candidate",
                subject_id=dir_candidate_id,
                message=f"candidate.json unreadable: {error}",
                path=str(candidate_path),
                candidate_id=dir_candidate_id,
            )
            continue

        raw_candidate_id = str(candidate_payload.get("candidate_id", "") or "").strip()
        candidate_id = raw_candidate_id or dir_candidate_id
        if candidate_id != dir_candidate_id:
            candidate_id = dir_candidate_id
        data_version = str(candidate_payload.get("data_version", "") or "").strip()
        raw_backtest_path = str(candidate_payload.get("backtest_manifest_path", "") or "").strip()
        canonical_relpath = _candidate_manifest_relpath(candidate_id)
        canonical_backtest_path = _candidate_manifest_path(root, candidate_id)
        inline_backtest_manifest = _has_inline_manifest(candidate_payload)
        resolved_raw_path = _resolve_reference_path(root, raw_backtest_path)
        resolved_existing_path = ""

        candidate_record.data_version = data_version
        candidate_record.backtest_manifest_path = raw_backtest_path
        candidate_record.canonical_backtest_manifest_path = str(canonical_backtest_path)
        candidate_record.canonical_backtest_manifest_exists = canonical_backtest_path.exists()
        candidate_record.inline_backtest_manifest = inline_backtest_manifest

        if data_version:
            data_version_to_candidates.setdefault(data_version, set()).add(candidate_id)

        if not raw_backtest_path:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="missing_backtest_manifest_path",
                scope="candidate",
                subject_id=candidate_id,
                message="candidate is missing backtest_manifest_path",
                path=str(candidate_path),
                candidate_id=candidate_id,
                data_version=data_version,
                details={
                    "expected_backtest_manifest_path": canonical_relpath,
                    "canonical_backtest_manifest_exists": canonical_backtest_path.exists(),
                    "inline_backtest_manifest": inline_backtest_manifest,
                },
            )
        elif raw_backtest_path != canonical_relpath:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="non_canonical_backtest_manifest_path",
                scope="candidate",
                subject_id=candidate_id,
                message="candidate backtest_manifest_path is not the canonical relative path",
                path=str(candidate_path),
                candidate_id=candidate_id,
                data_version=data_version,
                details={
                    "actual_backtest_manifest_path": raw_backtest_path,
                    "expected_backtest_manifest_path": canonical_relpath,
                    "resolved_path": str(resolved_raw_path) if resolved_raw_path is not None else "",
                    "resolved_exists": bool(resolved_raw_path and resolved_raw_path.exists()),
                },
            )

        chosen_backtest_path: Path | None = None
        if resolved_raw_path is not None and resolved_raw_path.exists():
            chosen_backtest_path = resolved_raw_path
        elif canonical_backtest_path.exists():
            chosen_backtest_path = canonical_backtest_path
        if chosen_backtest_path is not None:
            resolved_existing_path = str(chosen_backtest_path)
            candidate_record.resolved_backtest_manifest_path = resolved_existing_path

        if raw_backtest_path and resolved_raw_path is not None and not resolved_raw_path.exists():
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="stale_backtest_manifest_path",
                scope="candidate",
                subject_id=candidate_id,
                message="candidate backtest_manifest_path does not resolve to an existing file",
                path=str(candidate_path),
                candidate_id=candidate_id,
                data_version=data_version,
                details={
                    "actual_backtest_manifest_path": raw_backtest_path,
                    "resolved_path": str(resolved_raw_path),
                    "canonical_backtest_manifest_path": str(canonical_backtest_path),
                    "canonical_backtest_manifest_exists": canonical_backtest_path.exists(),
                },
            )

        if chosen_backtest_path is None:
            if inline_backtest_manifest:
                _append_finding(
                    findings,
                    severity=SEVERITY_BLOCKER,
                    code="inline_only_backtest_manifest",
                    scope="candidate",
                    subject_id=candidate_id,
                    message=(
                        "candidate only carries inline backtest evidence; persisted canonical "
                        "run_manifest.json is required"
                    ),
                    path=str(candidate_path),
                    candidate_id=candidate_id,
                    data_version=data_version,
                    details={
                        "expected_backtest_manifest_path": str(canonical_backtest_path),
                    },
                )
            else:
                _append_finding(
                    findings,
                    severity=SEVERITY_BLOCKER,
                    code="missing_backtest_manifest_file",
                    scope="candidate",
                    subject_id=candidate_id,
                    message="no persisted backtest manifest was found for candidate",
                    path=str(candidate_path),
                    candidate_id=candidate_id,
                    data_version=data_version,
                    details={
                        "expected_backtest_manifest_path": str(canonical_backtest_path),
                        "configured_backtest_manifest_path": raw_backtest_path,
                    },
                )
            continue

        backtest_payload, error = _try_load_json(chosen_backtest_path)
        if backtest_payload is None:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="invalid_backtest_manifest_json",
                scope="backtest_manifest",
                subject_id=candidate_id,
                message=f"backtest manifest unreadable: {error}",
                path=str(chosen_backtest_path),
                candidate_id=candidate_id,
                data_version=data_version,
            )
            continue

        backtest_data_version = str(backtest_payload.get("data_version", "") or data_version).strip()
        embedded_manifest = _data_manifest_from_payload(backtest_payload.get("data_manifest"))
        backtest_records[candidate_id] = BacktestRecord(
            candidate_id=candidate_id,
            path=str(chosen_backtest_path),
            data_version=backtest_data_version,
            has_embedded_data_manifest=embedded_manifest is not None,
        )

        if embedded_manifest is None:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="missing_embedded_data_manifest_binding",
                scope="backtest_manifest",
                subject_id=candidate_id,
                message="backtest manifest is missing embedded canonical data manifest binding",
                path=str(chosen_backtest_path),
                candidate_id=candidate_id,
                data_version=backtest_data_version,
            )
            continue

        governed_manifest = None
        if backtest_data_version:
            governed_manifest = DataManifestStore(root / "manifests").read(backtest_data_version)
        if governed_manifest is None:
            continue

        mismatches = _compare_embedded_data_manifest(
            embedded=embedded_manifest,
            governed=governed_manifest,
        )
        if mismatches:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="stale_data_manifest_binding",
                scope="backtest_manifest",
                subject_id=candidate_id,
                message="embedded backtest data manifest binding differs from canonical persisted manifest",
                path=str(chosen_backtest_path),
                candidate_id=candidate_id,
                data_version=backtest_data_version,
                details={
                    "mismatches": mismatches,
                    "canonical_data_manifest_path": str(root / "manifests" / f"{backtest_data_version}.json"),
                },
            )

    data_manifest_records: list[DataManifestRecord] = []
    rows_by_data_version: dict[str, list[dict[str, Any]]] = {}
    for row in data_rows:
        rows_by_data_version.setdefault(str(row["data_version"]), []).append(row)

    for data_version, rows in sorted(rows_by_data_version.items()):
        candidate_ids = sorted(data_version_to_candidates.get(data_version, set()))
        canonical_path = root / "manifests" / f"{data_version}.json"
        canonical_rows = [row for row in rows if row["path"].resolve() == canonical_path.resolve()]
        store_manifest = DataManifestStore(root / "manifests").read(data_version) if canonical_path.exists() else None

        record = DataManifestRecord(
            data_version=data_version,
            canonical_path=str(canonical_path),
            canonical_exists=canonical_path.exists(),
            paths=[str(row["path"]) for row in rows],
            impacted_candidates=candidate_ids,
            duplicate_count=len(rows),
            quality_score=float(getattr(store_manifest, "quality_score", 0.0) or 0.0),
            coverage_pct=float(getattr(store_manifest, "coverage_pct", 0.0) or 0.0),
        )
        data_manifest_records.append(record)

        if len(rows) > 1:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="duplicate_data_version_manifests",
                scope="data_manifest",
                subject_id=data_version,
                message="multiple persisted manifests share the same data_version",
                path=str(canonical_path),
                data_version=data_version,
                details={
                    "manifest_paths": [str(row["path"]) for row in rows],
                    "impacted_candidates": candidate_ids,
                },
            )

        if rows and not canonical_rows:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="stale_data_manifest",
                scope="data_manifest",
                subject_id=data_version,
                message="canonical data manifest path is missing but alternate manifests exist",
                path=str(canonical_path),
                data_version=data_version,
                details={
                    "alternate_paths": [str(row["path"]) for row in rows],
                    "impacted_candidates": candidate_ids,
                },
            )

        if canonical_path.exists() and len(canonical_rows) != 1:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="conflict_data_manifest",
                scope="data_manifest",
                subject_id=data_version,
                message="canonical data manifest path does not resolve to exactly one persisted manifest row",
                path=str(canonical_path),
                data_version=data_version,
                details={
                    "manifest_paths": [str(row["path"]) for row in rows],
                    "impacted_candidates": candidate_ids,
                },
            )

        if canonical_path.exists() and store_manifest is None:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="invalid_canonical_data_manifest",
                scope="data_manifest",
                subject_id=data_version,
                message="canonical data manifest exists but is unreadable as DataManifest",
                path=str(canonical_path),
                data_version=data_version,
                details={"impacted_candidates": candidate_ids},
            )
            continue

        if store_manifest is None:
            continue

        validation = validate_manifest_for_promotion(store_manifest)
        low_quality_reasons = [
            reason
            for reason in validation.reasons
            if reason.startswith("coverage_below_threshold")
            or reason.startswith("quality_below_threshold")
        ]
        if low_quality_reasons:
            _append_finding(
                findings,
                severity=SEVERITY_BLOCKER,
                code="low_quality_data_manifest",
                scope="data_manifest",
                subject_id=data_version,
                message="canonical data manifest does not meet promotion quality thresholds",
                path=str(canonical_path),
                data_version=data_version,
                details={
                    "coverage_pct": store_manifest.coverage_pct,
                    "quality_score": store_manifest.quality_score,
                    "reasons": low_quality_reasons,
                    "impacted_candidates": candidate_ids,
                },
            )

    blockers_by_candidate: dict[str, set[str]] = {candidate_id: set() for candidate_id in candidate_records}
    blockers_by_data_version: dict[str, set[str]] = {}
    blockers_by_backtest_candidate: dict[str, set[str]] = {
        candidate_id: set() for candidate_id in backtest_records
    }
    for finding in findings:
        if finding.candidate_id:
            blockers_by_candidate.setdefault(finding.candidate_id, set()).add(finding.code)
            if finding.candidate_id in blockers_by_backtest_candidate:
                blockers_by_backtest_candidate[finding.candidate_id].add(finding.code)
        if finding.data_version:
            blockers_by_data_version.setdefault(finding.data_version, set()).add(finding.code)
            for candidate_id in data_version_to_candidates.get(finding.data_version, set()):
                blockers_by_candidate.setdefault(candidate_id, set()).add(finding.code)

    for candidate_id, record in candidate_records.items():
        record.blocker_codes = sorted(blockers_by_candidate.get(candidate_id, set()))
    for candidate_id, record in backtest_records.items():
        record.blocker_codes = sorted(blockers_by_backtest_candidate.get(candidate_id, set()))
    for record in data_manifest_records:
        record.blocker_codes = sorted(blockers_by_data_version.get(record.data_version, set()))

    blocker_count = len(findings)
    counts = {
        "candidate_count": len(candidate_paths),
        "backtest_manifest_count": len(backtest_paths),
        "data_manifest_count": len(data_rows),
        "data_version_count": len(rows_by_data_version),
        "blocker_count": blocker_count,
    }

    report = {
        "schema_version": SCHEMA_VERSION,
        "scope": "report_only",
        "dry_run": True,
        "strict": False,
        "data_root": str(root),
        "counts": counts,
        "blockers": [asdict(finding) for finding in findings],
        "candidates": [asdict(record) for _, record in sorted(candidate_records.items())],
        "backtest_manifests": [asdict(record) for _, record in sorted(backtest_records.items())],
        "data_manifests": [asdict(record) for record in data_manifest_records],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only audit for historical candidate/backtest/data evidence"
    )
    parser.add_argument(
        "--data-root",
        default="data",
        help="Data root containing research candidates, backtests, and manifests",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when one or more BLOCKER findings are present",
    )
    args = parser.parse_args()

    report = audit_research_evidence(data_root=args.data_root)
    report["strict"] = bool(args.strict)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 1 if args.strict and report["counts"]["blocker_count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
