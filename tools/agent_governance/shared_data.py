from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

MODULE_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from tools.agent_governance.git_metadata import GitMetadataError, main_repository_root


SCHEMA_VERSION = "shared_dataset_manifest_v1"
MANIFEST_NAME = "_dataset_manifest.json"
DEFAULT_SHARED_DATA_ENV = "QUANT_SHARED_DATA_ROOT"
DATA_STEWARD_ROLE = "data_steward"
READINESS_CLASSES = {
    "quality_checked",
    "research_ready",
    "backtest_ready",
    "promotion_evidence_ready",
}
QUALITY_STATUSES = {"pass", "pass_with_research_only_warnings", "blocked"}
IMMUTABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DISALLOWED_SHARED_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


class SharedDataError(ValueError):
    pass


def default_shared_data_root(repo_root: Path) -> Path:
    configured = os.environ.get(DEFAULT_SHARED_DATA_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        return main_repository_root(repo_root).parent / "shared-data"
    except (OSError, GitMetadataError):
        return repo_root.resolve().parent / "shared-data"


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_directory(source: Path) -> tuple[list[dict[str, Any]], str, int]:
    root = source.resolve()
    if not root.is_dir():
        raise SharedDataError(f"shared_data_source_not_directory:{root}")

    rows: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise SharedDataError(f"shared_data_symlink_not_allowed:{path}")
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        if path.suffix.lower() in DISALLOWED_SHARED_SUFFIXES:
            raise SharedDataError(f"shared_mutable_database_not_allowed:{path.name}")
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        rows.append({"path": relative, "sha256": sha256_file(path), "bytes": size})
        total_bytes += size

    if not rows:
        raise SharedDataError("shared_data_source_empty")
    return rows, aggregate_inventory_hash(rows), total_bytes


def aggregate_inventory_hash(files: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda row: str(row["path"])):
        digest.update(str(item["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["bytes"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_manifest(
    *,
    dataset_id: str,
    dataset_version: str,
    readiness_class: str,
    quality_status: str,
    files: list[dict[str, Any]],
    aggregate_sha256: str,
    total_bytes: int,
    producer_commit: str,
    blockers: Iterable[str] = (),
    known_gaps: Iterable[str] = (),
    schema_name: str,
    coverage_start: str = "",
    coverage_end: str = "",
    published_at: str | None = None,
) -> dict[str, Any]:
    _validate_identifier("dataset_id", dataset_id)
    _validate_identifier("dataset_version", dataset_version)
    if readiness_class not in READINESS_CLASSES:
        raise SharedDataError(f"shared_data_readiness_invalid:{readiness_class}")
    if quality_status not in QUALITY_STATUSES:
        raise SharedDataError(f"shared_data_quality_status_invalid:{quality_status}")
    if not schema_name.strip():
        raise SharedDataError("shared_data_schema_name_missing")
    blocker_list = _dedupe(blockers)
    if quality_status == "blocked" and not blocker_list:
        raise SharedDataError("shared_data_blocked_without_blockers")
    if readiness_class in {"backtest_ready", "promotion_evidence_ready"}:
        if quality_status != "pass" or blocker_list:
            raise SharedDataError("shared_data_advanced_readiness_requires_clean_quality")

    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "producer_role": DATA_STEWARD_ROLE,
        "producer_commit": producer_commit,
        "published_at": published_at or _utc_now(),
        "storage_relative_path": f"datasets/{dataset_id}/{dataset_version}",
        "data_schema": schema_name,
        "coverage": {"start": coverage_start, "end": coverage_end},
        "readiness_class": readiness_class,
        "quality_status": quality_status,
        "aggregate_sha256": aggregate_sha256,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
        "known_gaps": _dedupe(known_gaps),
        "blockers": blocker_list,
        "guardrails": {
            "immutable_version": True,
            "consumer_read_only": True,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
    }


def publish_dataset(
    *,
    source: Path,
    shared_root: Path,
    dataset_id: str,
    dataset_version: str,
    readiness_class: str,
    quality_status: str,
    producer_role: str,
    producer_commit: str,
    schema_name: str,
    blockers: Iterable[str] = (),
    known_gaps: Iterable[str] = (),
    coverage_start: str = "",
    coverage_end: str = "",
    manifest_output: Path | None = None,
) -> dict[str, Any]:
    if producer_role != DATA_STEWARD_ROLE:
        raise SharedDataError(f"shared_data_publish_role_forbidden:{producer_role}")

    files, aggregate_sha256, total_bytes = inventory_directory(source)
    manifest = build_manifest(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        readiness_class=readiness_class,
        quality_status=quality_status,
        files=files,
        aggregate_sha256=aggregate_sha256,
        total_bytes=total_bytes,
        producer_commit=producer_commit,
        blockers=blockers,
        known_gaps=known_gaps,
        schema_name=schema_name,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )

    root = shared_root.resolve()
    target = root / manifest["storage_relative_path"]
    source_resolved = source.resolve()
    if _is_relative_to(source_resolved, target) or _is_relative_to(target, source_resolved):
        raise SharedDataError("shared_data_source_target_overlap")

    if target.exists():
        existing = _read_json(target / MANIFEST_NAME)
        if existing != manifest:
            comparable_existing = dict(existing)
            comparable_manifest = dict(manifest)
            comparable_existing.pop("published_at", None)
            comparable_manifest.pop("published_at", None)
            if comparable_existing != comparable_manifest:
                raise SharedDataError(f"dataset_version_immutable_conflict:{dataset_id}:{dataset_version}")
        resolved = resolve_manifest_payload(existing, shared_root=root, verify_files=True)
        if manifest_output:
            _write_json_atomic(manifest_output, existing)
        return {"status": "already_published", "path": str(resolved), "manifest": existing}

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.publishing-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source_resolved, temporary, copy_function=shutil.copy2)
        copied_files, copied_hash, copied_bytes = inventory_directory(temporary)
        if copied_files != files or copied_hash != aggregate_sha256 or copied_bytes != total_bytes:
            raise SharedDataError("shared_data_copy_verification_failed")
        _write_json_atomic(temporary / MANIFEST_NAME, manifest)
        os.replace(temporary, target)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    if manifest_output:
        _write_json_atomic(manifest_output, manifest)
    return {"status": "published", "path": str(target), "manifest": manifest}


def validate_manifest(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "dataset_id",
        "dataset_version",
        "producer_role",
        "producer_commit",
        "published_at",
        "storage_relative_path",
        "data_schema",
        "coverage",
        "readiness_class",
        "quality_status",
        "aggregate_sha256",
        "file_count",
        "total_bytes",
        "files",
        "known_gaps",
        "blockers",
        "guardrails",
    }
    errors.extend(f"shared_data_manifest_missing:{key}" for key in sorted(required - set(payload)))
    errors.extend(f"shared_data_manifest_unknown:{key}" for key in sorted(set(payload) - required))
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("shared_data_manifest_schema_version_invalid")
    if payload.get("producer_role") != DATA_STEWARD_ROLE:
        errors.append("shared_data_manifest_producer_invalid")
    for key in ("dataset_id", "dataset_version"):
        if not IMMUTABLE_ID_PATTERN.fullmatch(str(payload.get(key, ""))):
            errors.append(f"shared_data_manifest_{key}_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("producer_commit", ""))):
        errors.append("shared_data_manifest_producer_commit_invalid")
    if _parse_timestamp(str(payload.get("published_at", ""))) is None:
        errors.append("shared_data_manifest_published_at_invalid")
    if not str(payload.get("data_schema", "")).strip():
        errors.append("shared_data_manifest_data_schema_invalid")
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != {"start", "end"} or any(not isinstance(coverage.get(key), str) for key in ("start", "end")):
        errors.append("shared_data_manifest_coverage_invalid")
    if payload.get("readiness_class") not in READINESS_CLASSES:
        errors.append("shared_data_manifest_readiness_invalid")
    if payload.get("quality_status") not in QUALITY_STATUSES:
        errors.append("shared_data_manifest_quality_invalid")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        errors.append("shared_data_manifest_files_invalid")
        files = []
    else:
        observed_paths: set[str] = set()
        for index, item in enumerate(files):
            if not isinstance(item, Mapping):
                errors.append(f"shared_data_manifest_file_invalid:{index}")
                continue
            relative = str(item.get("path", ""))
            if not _safe_relative_path(relative):
                errors.append(f"shared_data_manifest_file_path_invalid:{index}")
            if relative in observed_paths:
                errors.append(f"shared_data_manifest_file_path_duplicate:{index}")
            observed_paths.add(relative)
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
                errors.append(f"shared_data_manifest_file_hash_invalid:{index}")
            if not isinstance(item.get("bytes"), int) or int(item.get("bytes", -1)) < 0:
                errors.append(f"shared_data_manifest_file_bytes_invalid:{index}")
            if set(item) != {"path", "sha256", "bytes"}:
                errors.append(f"shared_data_manifest_file_fields_invalid:{index}")
    if files:
        expected_hash = aggregate_inventory_hash(files)
        if payload.get("aggregate_sha256") != expected_hash:
            errors.append("shared_data_manifest_aggregate_hash_invalid")
        if payload.get("file_count") != len(files):
            errors.append("shared_data_manifest_file_count_invalid")
        if payload.get("total_bytes") != sum(int(item.get("bytes", 0)) for item in files if isinstance(item, Mapping)):
            errors.append("shared_data_manifest_total_bytes_invalid")
    expected_storage = f"datasets/{payload.get('dataset_id', '')}/{payload.get('dataset_version', '')}"
    if payload.get("storage_relative_path") != expected_storage:
        errors.append("shared_data_manifest_storage_path_invalid")
    guardrails = payload.get("guardrails")
    required_false = {
        "promotion_unlock_allowed",
        "paper_or_live_unlock_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
    }
    if not isinstance(guardrails, Mapping) or guardrails.get("immutable_version") is not True or guardrails.get("consumer_read_only") is not True:
        errors.append("shared_data_manifest_guardrails_invalid")
    else:
        expected_guardrails = {"immutable_version", "consumer_read_only", *required_false}
        if set(guardrails) != expected_guardrails:
            errors.append("shared_data_manifest_guardrail_fields_invalid")
        if any(guardrails.get(key) is not False for key in required_false):
            errors.append("shared_data_manifest_safety_flag_invalid")
    for key in ("known_gaps", "blockers"):
        value = payload.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"shared_data_manifest_{key}_invalid")
    if payload.get("quality_status") == "blocked" and not payload.get("blockers"):
        errors.append("shared_data_manifest_blocked_without_blockers")
    if payload.get("readiness_class") in {"backtest_ready", "promotion_evidence_ready"}:
        if payload.get("quality_status") != "pass" or payload.get("blockers"):
            errors.append("shared_data_manifest_advanced_readiness_invalid")
    return _dedupe(errors)


def resolve_manifest_payload(
    payload: Mapping[str, Any],
    *,
    shared_root: Path,
    verify_files: bool = True,
) -> Path:
    errors = validate_manifest(payload)
    if errors:
        raise SharedDataError(";".join(errors))
    target = shared_root.resolve() / str(payload["storage_relative_path"])
    if not target.is_dir():
        raise SharedDataError(f"shared_data_physical_version_missing:{target}")
    physical_manifest = _read_json(target / MANIFEST_NAME)
    if dict(physical_manifest) != dict(payload):
        raise SharedDataError("shared_data_physical_manifest_mismatch")
    if verify_files:
        for item in payload["files"]:
            path = target / str(item["path"])
            if not path.is_file():
                raise SharedDataError(f"shared_data_file_missing:{item['path']}")
            if path.stat().st_size != int(item["bytes"]):
                raise SharedDataError(f"shared_data_file_size_mismatch:{item['path']}")
            if sha256_file(path) != item["sha256"]:
                raise SharedDataError(f"shared_data_file_hash_mismatch:{item['path']}")
    return target


def resolve_manifest_file(manifest_path: Path, *, shared_root: Path, verify_files: bool = True) -> Path:
    return resolve_manifest_payload(_read_json(manifest_path), shared_root=shared_root, verify_files=verify_files)


def load_manifest_from_git(repo_root: Path, git_spec: str) -> dict[str, Any]:
    ref, separator, path = git_spec.partition(":")
    if not separator or not ref or not _safe_relative_path(path):
        raise SharedDataError(f"shared_data_manifest_git_spec_invalid:{git_spec}")
    if not path.startswith(".agent/data_manifests/") or not path.endswith(".json"):
        raise SharedDataError(f"shared_data_manifest_git_path_forbidden:{path}")
    try:
        raw = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SharedDataError(f"shared_data_manifest_git_read_failed:{git_spec}") from exc
    if not isinstance(payload, dict):
        raise SharedDataError("shared_data_manifest_not_object")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SharedDataError(f"shared_data_manifest_missing:{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SharedDataError(f"shared_data_manifest_unreadable:{path}") from exc
    if not isinstance(payload, dict):
        raise SharedDataError("shared_data_manifest_not_object")
    return payload


def _safe_relative_path(value: str) -> bool:
    if not value or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _validate_identifier(name: str, value: str) -> None:
    if not IMMUTABLE_ID_PATTERN.fullmatch(value):
        raise SharedDataError(f"shared_data_{name}_invalid:{value}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _git_head(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SharedDataError("shared_data_git_head_unavailable") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish or resolve immutable shared datasets.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--source", type=Path, required=True)
    publish.add_argument("--shared-root", type=Path)
    publish.add_argument("--dataset-id", required=True)
    publish.add_argument("--dataset-version", required=True)
    publish.add_argument("--readiness-class", choices=sorted(READINESS_CLASSES), required=True)
    publish.add_argument("--quality-status", choices=sorted(QUALITY_STATUSES), required=True)
    publish.add_argument("--producer-role", required=True)
    publish.add_argument("--schema-name", required=True)
    publish.add_argument("--coverage-start", default="")
    publish.add_argument("--coverage-end", default="")
    publish.add_argument("--blocker", action="append", default=[])
    publish.add_argument("--known-gap", action="append", default=[])
    publish.add_argument("--manifest-output", type=Path)

    resolve = subparsers.add_parser("resolve")
    manifest_source = resolve.add_mutually_exclusive_group(required=True)
    manifest_source.add_argument("--manifest", type=Path)
    manifest_source.add_argument("--manifest-git-spec")
    resolve.add_argument("--shared-root", type=Path)
    resolve.add_argument("--fast", action="store_true", help="Verify publication marker without hashing every file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    shared_root = (args.shared_root or default_shared_data_root(repo_root)).resolve()
    try:
        if args.command == "publish":
            result = publish_dataset(
                source=args.source,
                shared_root=shared_root,
                dataset_id=args.dataset_id,
                dataset_version=args.dataset_version,
                readiness_class=args.readiness_class,
                quality_status=args.quality_status,
                producer_role=args.producer_role,
                producer_commit=_git_head(repo_root),
                schema_name=args.schema_name,
                blockers=args.blocker,
                known_gaps=args.known_gap,
                coverage_start=args.coverage_start,
                coverage_end=args.coverage_end,
                manifest_output=args.manifest_output,
            )
            output: dict[str, Any] = result
        else:
            if args.manifest_git_spec:
                manifest = load_manifest_from_git(repo_root, args.manifest_git_spec)
                manifest_source = args.manifest_git_spec
                path = resolve_manifest_payload(manifest, shared_root=shared_root, verify_files=not args.fast)
            else:
                manifest_source = str(args.manifest)
                path = resolve_manifest_file(args.manifest, shared_root=shared_root, verify_files=not args.fast)
            output = {
                "status": "resolved",
                "path": str(path),
                "manifest_source": manifest_source,
                "consumer_read_only": True,
            }
    except SharedDataError as exc:
        output = {"status": "blocked", "blockers": str(exc).split(";"), "path": ""}
        exit_code = 2
    else:
        exit_code = 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
