"""Read-only, fail-closed consumer for US ETF26 and production PIT inputs."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

from quant_shared.core.serialization import canonical_payload_hash


SCHEMA_VERSION = "us_equity_pit_dataready_consumption_report_v1"
PRODUCTION_MANIFEST_NAME = "provider_bundle_manifest.json"
PRODUCTION_TABLES = (
    "universe_membership_events",
    "delisted_symbols",
    "corporate_actions",
    "symbol_mapping",
    "adjustment_replay",
    "macro_release_calendar",
)
PRODUCTION_FILES = (PRODUCTION_MANIFEST_NAME,) + tuple(
    f"{table}.csv" for table in PRODUCTION_TABLES
)
VISIBILITY_FIELDS = ("event_time", "available_time", "ingested_at")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def build_pit_dataready_consumption_report(
    *,
    repo_root: Path,
    config: Mapping[str, Any],
    production_bundle_root: Path | None,
    pit_lite_proof: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate committed inputs without mutating data or publishing manifests."""

    root = repo_root.resolve()
    now = _parse_utc(generated_at or _utc_now())
    etf26 = consume_etf26_manifest(repo_root=root, config=config, as_of=now)
    pit_lite = evaluate_pit_lite_zero_event_proof(pit_lite_proof)
    production = evaluate_production_pit_bundle(
        repo_root=root,
        bundle_root=production_bundle_root,
        config=config,
        as_of=now,
    )
    blockers = list(production["blockers"])
    if etf26["state"] != "research_ready":
        blockers.append(f"etf26_manifest_{etf26['state']}")
    blockers = _dedupe(blockers)
    status = (
        "production_pit_accepted"
        if production["accepted"] and not blockers
        else "blocked_external_data"
    )
    decision = (
        "production_pit_consumer_contract_satisfied_but_promotion_remains_locked"
        if status == "production_pit_accepted"
        else "wait_for_data_steward_immutable_production_pit_handoff"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_utc(now),
        "asset": "us_equity",
        "status": status,
        "decision": decision,
        "etf26_minute": etf26,
        "pit_lite": pit_lite,
        "production_pit": production,
        "blockers": blockers,
        "readiness": {
            "research_ready": etf26["state"] == "research_ready",
            "promotion_evidence_ready": False,
            "production_pit_accepted": production["accepted"],
        },
        "next_handoff_contract": {
            "owner": "data_steward",
            "producer_role": "data_steward",
            "readiness_class": "research_ready",
            "immutable_version_required": True,
            "required_files": list(PRODUCTION_FILES),
            "required_manifest_fields": [
                "schema_version",
                "bundle_id",
                "bundle_version",
                "immutable_version",
                "producer_role",
                "producer_commit",
                "published_at",
                "coverage",
                "calendar",
                "source_splices",
                "files",
            ],
            "required_row_visibility_fields": list(VISIBILITY_FIELDS),
            "required_adjustment_visibility_field": "adjustment_available_time",
            "consumer_action": (
                "publish committed append-only handoff referencing an immutable "
                "manifest and all seven verified bundle files"
            ),
        },
        "guardrails": _false_safety_flags(),
    }
    report["artifact_identity_sha256"] = canonical_payload_hash(
        {
            "schema_version": report["schema_version"],
            "asset": report["asset"],
            "status": report["status"],
            "decision": report["decision"],
            "etf26_minute": report["etf26_minute"],
            "pit_lite": report["pit_lite"],
            "production_pit": report["production_pit"],
            "blockers": report["blockers"],
            "readiness": report["readiness"],
            "next_handoff_contract": report["next_handoff_contract"],
            "guardrails": report["guardrails"],
        }
    )
    return report


def consume_etf26_manifest(
    *, repo_root: Path, config: Mapping[str, Any], as_of: datetime
) -> dict[str, Any]:
    """Consume the manifest from committed Git bytes and validate its handoff."""

    cfg = _mapping(config.get("etf26_manifest"))
    git_spec = str(cfg.get("git_spec", ""))
    handoff_path = str(cfg.get("handoff_path", ""))
    expected_event_id = str(cfg.get("handoff_event_id", ""))
    constraints: list[str] = []
    errors: list[str] = []

    manifest_bytes = _git_show(repo_root, git_spec)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        manifest = {}
        errors.append("invalid_json")
    if not isinstance(manifest, Mapping):
        manifest = {}
        errors.append("not_object")

    expected = {
        "schema_version": "shared_dataset_manifest_v1",
        "dataset_id": str(cfg.get("dataset_id", "")),
        "dataset_version": str(cfg.get("dataset_version", "")),
        "producer_role": "data_steward",
        "readiness_class": "research_ready",
        "aggregate_sha256": str(cfg.get("aggregate_sha256", "")),
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            errors.append(f"{field}_mismatch")
    if manifest_sha != str(cfg.get("manifest_sha256", "")):
        errors.append("manifest_sha256_mismatch")
    producer_commit = str(manifest.get("producer_commit", ""))
    if not COMMIT_RE.fullmatch(producer_commit):
        errors.append("producer_commit_invalid")
    elif not _git_commit_exists(repo_root, producer_commit):
        errors.append("producer_commit_missing")
    guardrails = _mapping(manifest.get("guardrails"))
    if (
        guardrails.get("immutable_version") is not True
        or guardrails.get("consumer_read_only") is not True
    ):
        errors.append("immutable_read_only_guardrail_missing")
    if (
        guardrails.get("promotion_unlock_allowed") is not False
        or guardrails.get("paper_or_live_unlock_allowed") is not False
    ):
        errors.append("unsafe_unlock_guardrail")
    coverage = _mapping(manifest.get("coverage"))
    if not coverage.get("start") or not coverage.get("end"):
        errors.append("coverage_missing")
    if not manifest.get("calendar"):
        constraints.append("etf26_manifest_calendar_contract_missing")
    known_gaps = [str(item) for item in _list(manifest.get("known_gaps"))]
    if any("splice" in item for item in known_gaps):
        constraints.append("etf26_source_splice_equivalence_unproven")
    if any("adjustment_available_time" in item for item in known_gaps):
        constraints.append("etf26_adjustment_visibility_replay_missing")
    published_at = _try_parse_utc(manifest.get("published_at"))
    max_age_days = int(cfg.get("max_manifest_age_days", 30))
    if published_at is None:
        errors.append("published_at_invalid")
    elif as_of - published_at > timedelta(days=max_age_days):
        errors.append("stale")

    handoff_validation = _validate_handoff(
        repo_root=repo_root,
        handoff_path=handoff_path,
        expected_event_id=expected_event_id,
    )
    if handoff_validation != "valid":
        errors.append(f"handoff_{handoff_validation}")
    else:
        event = json.loads((repo_root / handoff_path).read_text(encoding="utf-8"))
        matching = [
            item
            for item in _list(event.get("deliverables"))
            if isinstance(item, Mapping)
            and str(item.get("path", "")) == git_spec.split(":", 1)[-1]
            and str(item.get("sha256", "")) == manifest_sha
            and item.get("readiness_class") == "research_ready"
        ]
        if not matching:
            errors.append("handoff_manifest_identity_mismatch")
    immutable_resolution = _resolve_shared_manifest(
        repo_root=repo_root,
        manifest_git_spec=git_spec,
    )
    if immutable_resolution["status"] != "resolved":
        errors.append("immutable_dataset_not_resolved")

    return {
        "state": "research_ready" if not errors else errors[0],
        "scope": "frozen_etf26_research_observation_only",
        "manifest_git_spec": git_spec,
        "manifest_sha256": manifest_sha,
        "dataset_id": str(manifest.get("dataset_id", "")),
        "dataset_version": str(manifest.get("dataset_version", "")),
        "producer_role": str(manifest.get("producer_role", "")),
        "producer_commit": producer_commit,
        "readiness_class": str(manifest.get("readiness_class", "")),
        "coverage": dict(coverage),
        "immutable_resolution": immutable_resolution,
        "constraints": _dedupe(constraints),
        "errors": _dedupe(errors),
        "promotion_evidence_ready": False,
    }


def evaluate_pit_lite_zero_event_proof(
    proof: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Accept only an explicit, immutable zero-event proof for research observation."""

    if proof is None:
        return {
            "state": "not_supplied",
            "scope": "frozen_etf26_research_observation_only",
            "production_pit_substitute": False,
            "errors": [],
        }
    errors: list[str] = []
    if proof.get("schema_version") != "us_equity_pit_lite_zero_event_proof_v1":
        errors.append("schema_version_mismatch")
    if proof.get("producer_role") != "data_steward":
        errors.append("producer_role_mismatch")
    if proof.get("immutable_version") is not True:
        errors.append("immutable_version_missing")
    for field in ("membership_event_count", "corporate_action_event_count"):
        if proof.get(field) != 0:
            errors.append(f"{field}_not_zero")
    return {
        "state": "pit_lite_zero_event_proof" if not errors else "invalid",
        "scope": "frozen_etf26_research_observation_only",
        "production_pit_substitute": False,
        "errors": errors,
    }


def evaluate_production_pit_bundle(
    *,
    repo_root: Path,
    bundle_root: Path | None,
    config: Mapping[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    """Validate a seven-file immutable bundle, or fail closed when absent."""

    if bundle_root is None:
        return _missing_production_bundle("production_pit_bundle_root_not_supplied")
    root = bundle_root.resolve()
    manifest_path = root / PRODUCTION_MANIFEST_NAME
    if not root.is_dir() or not manifest_path.is_file():
        return _missing_production_bundle("production_pit_bundle_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _invalid_production_bundle(["production_pit_manifest_invalid_json"])
    if not isinstance(manifest, Mapping):
        return _invalid_production_bundle(["production_pit_manifest_not_object"])
    return validate_production_pit_payload(
        repo_root=repo_root,
        bundle_root=root,
        manifest=manifest,
        config=config,
        as_of=as_of,
    )


def validate_production_pit_payload(
    *,
    repo_root: Path,
    bundle_root: Path,
    manifest: Mapping[str, Any],
    config: Mapping[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    """Validate metadata, files, coverage, splice lineage and visibility order."""

    cfg = _mapping(config.get("production_pit"))
    blockers: list[str] = []
    required_values = {
        "schema_version": "us_equity_production_pit_bundle_v1",
        "producer_role": "data_steward",
        "immutable_version": True,
    }
    for field, expected in required_values.items():
        if manifest.get(field) != expected:
            blockers.append(f"production_pit_manifest_{field}_mismatch")
    for field in ("bundle_id", "bundle_version", "source_provider", "producer_commit"):
        if not str(manifest.get(field, "")):
            blockers.append(f"production_pit_manifest_{field}_missing")
    if not COMMIT_RE.fullmatch(str(manifest.get("producer_commit", ""))):
        blockers.append("production_pit_manifest_producer_commit_invalid")
    elif not _git_commit_exists(repo_root, str(manifest.get("producer_commit"))):
        blockers.append("production_pit_manifest_producer_commit_missing")
    published_at = _try_parse_utc(manifest.get("published_at"))
    if published_at is None:
        blockers.append("production_pit_manifest_published_at_invalid")
    elif as_of - published_at > timedelta(
        days=int(cfg.get("max_manifest_age_days", 30))
    ):
        blockers.append("production_pit_manifest_stale")
    coverage = _mapping(manifest.get("coverage"))
    coverage_start = _try_parse_utc(coverage.get("start"))
    coverage_end = _try_parse_utc(coverage.get("end"))
    required_start = _try_parse_utc(cfg.get("required_coverage_start"))
    required_end = _try_parse_utc(cfg.get("required_coverage_end"))
    if (
        coverage_start is None
        or coverage_end is None
        or (required_start and coverage_start > required_start)
        or (required_end and coverage_end < required_end)
    ):
        blockers.append("production_pit_partial_coverage")
    if manifest.get("calendar") != cfg.get("calendar", "XNYS"):
        blockers.append("production_pit_calendar_mismatch")
    splice_ids = {
        str(item.get("splice_id"))
        for item in _list(manifest.get("source_splices"))
        if isinstance(item, Mapping)
        and item.get("splice_id")
        and item.get("source")
        and item.get("start")
        and item.get("end")
    }
    if not splice_ids:
        blockers.append("production_pit_source_splice_missing")

    files = _mapping(manifest.get("files"))
    validated_files: list[dict[str, Any]] = []
    max_visibility_lag = timedelta(
        hours=int(cfg.get("max_visibility_lag_hours", 168))
    )
    for table in PRODUCTION_TABLES:
        spec = _mapping(files.get(table))
        rel_path = str(spec.get("path", ""))
        if rel_path != f"{table}.csv":
            blockers.append(f"production_pit_{table}_path_mismatch")
            continue
        path = (bundle_root / rel_path).resolve()
        if not _is_within(bundle_root, path) or not path.is_file():
            blockers.append(f"production_pit_{table}_missing")
            continue
        actual_hash = _sha256_file(path)
        if not SHA256_RE.fullmatch(str(spec.get("sha256", ""))):
            blockers.append(f"production_pit_{table}_hash_missing")
        elif actual_hash != spec.get("sha256"):
            blockers.append(f"production_pit_{table}_hash_mismatch")
        rows = _read_csv(path)
        if len(rows) != spec.get("record_count"):
            blockers.append(f"production_pit_{table}_record_count_mismatch")
        if not rows:
            blockers.append(f"production_pit_{table}_empty")
        for row_number, row in enumerate(rows, start=2):
            times = [_try_parse_utc(row.get(field)) for field in VISIBILITY_FIELDS]
            if any(value is None for value in times):
                blockers.append(
                    f"production_pit_{table}_visibility_timestamp_invalid"
                )
                continue
            event_time, available_time, ingested_at = times
            if not event_time <= available_time <= ingested_at:
                blockers.append(f"production_pit_{table}_visibility_order_invalid")
            if available_time - event_time > max_visibility_lag:
                blockers.append(f"production_pit_{table}_late_visibility")
            if str(row.get("source_splice_id", "")) not in splice_ids:
                blockers.append(f"production_pit_{table}_source_splice_unverified")
            if table == "adjustment_replay":
                adjustment_available = _try_parse_utc(
                    row.get("adjustment_available_time")
                )
                if (
                    adjustment_available is None
                    or not event_time <= adjustment_available <= available_time
                ):
                    blockers.append(
                        "production_pit_adjustment_replay_visibility_invalid"
                    )
            if row_number > 100_000:
                blockers.append(f"production_pit_{table}_row_limit_exceeded")
                break
        validated_files.append(
            {
                "table": table,
                "path": rel_path,
                "sha256": actual_hash,
                "record_count": len(rows),
            }
        )
    blockers = _dedupe(blockers)
    accepted = not blockers and len(validated_files) == len(PRODUCTION_TABLES)
    return {
        "state": "accepted" if accepted else "rejected",
        "accepted": accepted,
        "bundle_id": str(manifest.get("bundle_id", "")),
        "bundle_version": str(manifest.get("bundle_version", "")),
        "producer_role": str(manifest.get("producer_role", "")),
        "producer_commit": str(manifest.get("producer_commit", "")),
        "calendar": str(manifest.get("calendar", "")),
        "coverage": dict(coverage),
        "validated_files": validated_files,
        "blockers": blockers,
        "data_modified": False,
        "manifest_published_by_consumer": False,
    }


def _missing_production_bundle(reason: str) -> dict[str, Any]:
    return {
        "state": "missing",
        "accepted": False,
        "bundle_id": "",
        "bundle_version": "",
        "producer_role": "",
        "producer_commit": "",
        "calendar": "",
        "coverage": {},
        "validated_files": [],
        "blockers": [
            reason,
            *[
                f"production_pit_required_file_missing:{name}"
                for name in PRODUCTION_FILES
            ],
        ],
        "data_modified": False,
        "manifest_published_by_consumer": False,
    }


def _invalid_production_bundle(blockers: list[str]) -> dict[str, Any]:
    result = _missing_production_bundle(blockers[0])
    result["state"] = "rejected"
    result["blockers"] = blockers
    return result


def _false_safety_flags() -> dict[str, bool]:
    return {
        "consumer_read_only": True,
        "data_manifest_written": False,
        "network_used": False,
        "promotion_evidence_ready": False,
        "promotion_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_endpoint_used": False,
        "withdraw_allowed": False,
        "demo_allowed": False,
        "paper_queue_write_allowed": False,
        "real_order_submitted": False,
    }


def _validate_handoff(
    *, repo_root: Path, handoff_path: str, expected_event_id: str
) -> str:
    path = (repo_root / handoff_path).resolve()
    if not _is_within(repo_root, path) or not path.is_file():
        return "missing"
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools/agent_governance/handoff.py"),
            "--repo-root",
            str(repo_root),
            "validate",
            "--input",
            str(path),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return "invalid"
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return "invalid"
    if payload.get("status") != "valid":
        return "invalid"
    return "valid" if payload.get("event_id") == expected_event_id else "wrong_event"


def _git_show(repo_root: Path, git_spec: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", git_spec],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError("etf26_manifest_git_spec_unreadable")
    return completed.stdout


def _git_commit_exists(repo_root: Path, commit: str) -> bool:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def _resolve_shared_manifest(
    *, repo_root: Path, manifest_git_spec: str
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools/agent_governance/shared_data.py"),
            "--repo-root",
            str(repo_root),
            "resolve",
            "--manifest-git-spec",
            manifest_git_spec,
            "--fast",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return {
            "status": "unresolved",
            "consumer_read_only": True,
            "mode": "publication_marker_fast",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "unresolved",
            "consumer_read_only": True,
            "mode": "publication_marker_fast",
        }
    resolved = (
        payload.get("status") == "resolved"
        and payload.get("consumer_read_only") is True
    )
    return {
        "status": "resolved" if resolved else "unresolved",
        "consumer_read_only": True,
        "mode": "publication_marker_fast",
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_utc(value: str) -> datetime:
    parsed = _try_parse_utc(value)
    if parsed is None:
        raise ValueError(f"UTC datetime required: {value!r}")
    return parsed


def _try_parse_utc(value: Any) -> datetime | None:
    text = str(value or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return _iso_utc(datetime.now(timezone.utc))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True
