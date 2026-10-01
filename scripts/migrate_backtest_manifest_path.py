#!/usr/bin/env python3
"""Audit and migrate legacy research candidates missing backtest_manifest_path.

This script scans:
    data_root/research/candidates/*/candidate.json
    data_root/research/backtests/<candidate_id>/run_manifest.json

Default mode is dry-run. Use ``--apply`` to persist a canonical
``backtest_manifest_path`` into candidate.json.

Inline backtest manifests are treated as diagnostic only and never as
promotion evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, NamedTuple


class CandidateAuditResult(NamedTuple):
    candidate_id: str
    candidate_path: Path
    manifest_path: Path
    manifest_relpath: str
    status: str
    reason: str
    updated: bool = False


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_manifest_relpath(candidate_id: str) -> str:
    return str(Path("research") / "backtests" / candidate_id / "run_manifest.json")


def _candidate_manifest_path(data_root: Path, candidate_id: str) -> Path:
    return data_root / _candidate_manifest_relpath(candidate_id)


def _has_inline_manifest(candidate_data: dict[str, Any]) -> bool:
    metrics = candidate_data.get("metrics", {})
    return isinstance(candidate_data.get("backtest_manifest"), dict) or isinstance(
        metrics.get("backtest_manifest"), dict
    )


def audit_candidate(candidate_path: Path, data_root: Path) -> CandidateAuditResult:
    candidate_data = _load_json(candidate_path)
    dir_candidate_id = candidate_path.parent.name
    raw_candidate_id = str(candidate_data.get("candidate_id", "")).strip()
    candidate_id = raw_candidate_id or dir_candidate_id
    manifest_relpath = _candidate_manifest_relpath(candidate_id)
    manifest_path = _candidate_manifest_path(data_root, candidate_id)
    existing_path = str(candidate_data.get("backtest_manifest_path", "")).strip()
    inline_manifest = _has_inline_manifest(candidate_data)

    if raw_candidate_id and raw_candidate_id != dir_candidate_id:
        return CandidateAuditResult(
            candidate_id=dir_candidate_id,
            candidate_path=candidate_path,
            manifest_path=manifest_path,
            manifest_relpath=manifest_relpath,
            status="candidate_id_mismatch",
            reason=(
                f"candidate.json candidate_id={raw_candidate_id!r} does not match "
                f"directory name {dir_candidate_id!r}"
            ),
        )

    if existing_path:
        return CandidateAuditResult(
            candidate_id=candidate_id,
            candidate_path=candidate_path,
            manifest_path=manifest_path,
            manifest_relpath=manifest_relpath,
            status="already_present",
            reason=f"candidate already has backtest_manifest_path={existing_path}",
        )

    if manifest_path.exists():
        return CandidateAuditResult(
            candidate_id=candidate_id,
            candidate_path=candidate_path,
            manifest_path=manifest_path,
            manifest_relpath=manifest_relpath,
            status="can_migrate",
            reason=f"canonical manifest found at {manifest_path}",
        )

    if inline_manifest:
        return CandidateAuditResult(
            candidate_id=candidate_id,
            candidate_path=candidate_path,
            manifest_path=manifest_path,
            manifest_relpath=manifest_relpath,
            status="inline_manifest_only",
            reason=(
                "inline backtest_manifest is present but ignored; canonical "
                "run_manifest.json is required for promotion evidence"
            ),
        )

    return CandidateAuditResult(
        candidate_id=candidate_id,
        candidate_path=candidate_path,
        manifest_path=manifest_path,
        manifest_relpath=manifest_relpath,
        status="missing_manifest",
        reason=f"missing canonical manifest at {manifest_path}",
    )


def apply_candidate_migration(result: CandidateAuditResult) -> CandidateAuditResult:
    candidate_data = _load_json(result.candidate_path)
    candidate_data["backtest_manifest_path"] = result.manifest_relpath
    result.candidate_path.write_text(
        json.dumps(candidate_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return CandidateAuditResult(
        candidate_id=result.candidate_id,
        candidate_path=result.candidate_path,
        manifest_path=result.manifest_path,
        manifest_relpath=result.manifest_relpath,
        status="migrated",
        reason=f"wrote backtest_manifest_path={result.manifest_relpath}",
        updated=True,
    )


def audit_candidates(data_root: str = "data", apply: bool = False) -> dict[str, Any]:
    root = Path(data_root)
    candidates_root = root / "research" / "candidates"
    results: list[CandidateAuditResult] = []

    if not candidates_root.exists():
        return {
            "data_root": str(root),
            "apply": apply,
            "results": [],
            "counts": {"candidate_root_missing": 1},
        }

    for candidate_path in sorted(candidates_root.glob("*/candidate.json")):
        audit = audit_candidate(candidate_path, root)
        if apply and audit.status == "can_migrate":
            audit = apply_candidate_migration(audit)
        results.append(audit)

    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    return {
        "data_root": str(root),
        "apply": apply,
        "results": results,
        "counts": counts,
    }


def _print_report(report: dict[str, Any]) -> None:
    mode = "APPLY" if report["apply"] else "DRY-RUN"
    print(f"Legacy backtest_manifest_path migration [{mode}]")
    print(f"data_root={report['data_root']}")

    results: list[CandidateAuditResult] = report["results"]
    if not results:
        print("No candidate.json files found.")
        return

    for result in results:
        print(f"[{result.status}] {result.candidate_id}")
        print(f"  candidate: {result.candidate_path}")
        print(f"  manifest:  {result.manifest_path}")
        print(f"  detail:    {result.reason}")

    print("Summary:")
    for status in sorted(report["counts"]):
        print(f"  {status}: {report['counts'][status]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and migrate legacy research candidates missing "
            "backtest_manifest_path"
        )
    )
    parser.add_argument(
        "--data-root",
        default="data",
        help="Data root containing research/candidates and research/backtests",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist backtest_manifest_path into candidate.json when canonical manifests exist",
    )
    args = parser.parse_args()

    report = audit_candidates(data_root=args.data_root, apply=args.apply)
    _print_report(report)


if __name__ == "__main__":
    main()
